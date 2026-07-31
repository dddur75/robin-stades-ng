"""R2-first append-only storage for historical deep raw payloads."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from urllib.parse import quote

from pydantic import Field, model_validator

from robin.historical_deep.contracts import (
    R2_NAMESPACE,
    FrozenContract,
    HarvestTask,
    TaskStatus,
    TemporalClass,
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
)

RECEIPT_SCHEMA_VERSION = "historical-deep-receipt-v1"
CHECKPOINT_SCHEMA_VERSION = "historical-deep-checkpoint-v1"
TASK_VERSION_SCHEMA_VERSION = "historical-deep-task-version-v1"
RECOVERY_SCHEMA_VERSION = "historical-deep-recovery-intent-v1"
TASK_INDEX_SCHEMA_VERSION = "historical-deep-task-index-v1"
TASK_ATTEMPT_SCHEMA_VERSION = "historical-deep-task-attempt-v1"
_TASK_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ERROR_CLASS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
_SAFE_ERROR_MESSAGE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_]*(?::[A-Z0-9_]+)?$"
)
_SAFE_PROVIDER_ERROR_MESSAGES = frozenset(
    {
        "API_FOOTBALL_AUTHENTICATION_FAILED",
        "API_FOOTBALL_CIRCUIT_OPEN",
        "API_FOOTBALL_JSON_INVALID",
        "API_FOOTBALL_MEGA_ACTIVE_REQUIRED",
        "API_FOOTBALL_MINUTE_QUOTA_EXHAUSTED",
        "API_FOOTBALL_MINUTE_QUOTA_EXHAUSTED_RESET_UNKNOWN",
        "API_FOOTBALL_MINUTE_QUOTA_RESET_NOT_REACHED",
        "API_FOOTBALL_MINUTE_QUOTA_RESET_WAIT_EXCEEDS_BOUND",
        "API_FOOTBALL_PROTECTED_QUOTA_EXHAUSTED",
        "API_FOOTBALL_RATE_LIMIT_RETRY_EXHAUSTED",
        "API_FOOTBALL_RESPONSE_ERRORS",
        "API_FOOTBALL_RETRY_STATE_INVALID",
        "API_FOOTBALL_STATUS_FIELDS_MISSING",
        "API_FOOTBALL_STATUS_INVALID",
        "API_FOOTBALL_STATUS_PAYLOAD_INVALID",
        "API_FOOTBALL_STATUS_PROOF_EXPIRED",
        "API_FOOTBALL_STATUS_PROOF_REQUIRED",
        "API_FOOTBALL_STATUS_RESPONSE_MISSING",
        "API_FOOTBALL_SUBSCRIPTION_END_INVALID",
        "API_FOOTBALL_TRANSPORT_FAILED",
        "RUNNER_HEARTBEAT_STALE",
    }
)
_SAFE_PROVIDER_HTTP_ERROR_PATTERN = re.compile(r"^API_FOOTBALL_HTTP_[45][0-9]{2}$")
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "x-apisports-key",
    }
)
_SAFE_QUOTA_HEADER_NAMES = frozenset(
    {
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-requests-limit",
        "x-ratelimit-requests-remaining",
        "x-ratelimit-requests-reset",
        "x-ratelimit-rps-limit",
        "x-ratelimit-reset",
        "x-rate-limit-limit",
        "x-rate-limit-remaining",
        "x-rate-limit-requests-limit",
        "x-rate-limit-requests-remaining",
        "x-rate-limit-requests-reset",
        "x-rate-limit-rps-limit",
        "x-rate-limit-reset",
        "x-requests-per-minute",
        "x-requests-per-second",
    }
)
_TASK_TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETE,
        TaskStatus.EMPTY_VALID,
        TaskStatus.RETRYABLE,
        TaskStatus.STALE_RETRYABLE,
        TaskStatus.BLOCKED_COVERAGE,
        TaskStatus.BLOCKED_PROVIDER,
        TaskStatus.FAILED,
    }
)
_TASK_FAILURE_STATUSES = frozenset(
    {
        TaskStatus.RETRYABLE,
        TaskStatus.STALE_RETRYABLE,
        TaskStatus.BLOCKED_COVERAGE,
        TaskStatus.BLOCKED_PROVIDER,
        TaskStatus.FAILED,
    }
)


class AppendOnlyViolation(RuntimeError):
    """Raised when an immutable key already contains different bytes."""


class PayloadIntegrityError(RuntimeError):
    """Raised when a receipt, payload or recovery intent cannot be trusted."""


@runtime_checkable
class ObjectStore(Protocol):
    """Secret-agnostic append-only object-store surface."""

    def get_object(self, key: str) -> bytes | None: ...

    def put_if_absent(self, key: str, data: bytes) -> bool: ...

    def iter_keys(self, prefix: str) -> Iterable[str]: ...


class InMemoryObjectStore:
    """Strict in-memory implementation; overwrite and deletion do not exist."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def get_object(self, key: str) -> bytes | None:
        value = self._objects.get(key)
        return bytes(value) if value is not None else None

    def put_if_absent(self, key: str, data: bytes) -> bool:
        if key in self._objects:
            return False
        self._objects[key] = bytes(data)
        return True

    def iter_keys(self, prefix: str) -> Iterable[str]:
        return tuple(sorted(key for key in self._objects if key.startswith(prefix)))

    @property
    def object_count(self) -> int:
        return len(self._objects)


def _safe_segment(value: str, *, allow_colon: bool = False) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("HISTORICAL_DEEP_R2_KEY_SEGMENT_INVALID")
    safe = "-_.~:" if allow_colon else "-_.~"
    return quote(value, safe=safe)


def task_prefix(task: HarvestTask) -> str:
    endpoint = task.endpoint.strip("/")
    return (
        f"{R2_NAMESPACE}/"
        f"competition={_safe_segment(task.competition, allow_colon=True)}/"
        f"season={task.season}/"
        f"family={_safe_segment(task.family.value)}/"
        f"endpoint={_safe_segment(endpoint)}/"
        f"task={task.task_id}"
    )


def payload_key(task: HarvestTask, payload_sha256: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
        raise ValueError("HISTORICAL_DEEP_PAYLOAD_SHA256_INVALID")
    return f"{task_prefix(task)}/payload-{payload_sha256}.json.gz"


def receipt_key(task: HarvestTask) -> str:
    return f"{task_prefix(task)}/receipt.json"


def checkpoint_key(task: HarvestTask) -> str:
    return f"{task_prefix(task)}/checkpoint.json"


def version_key(task: HarvestTask) -> str:
    return f"{task_prefix(task)}/version.json"


def recovery_key(task: HarvestTask) -> str:
    return f"{task_prefix(task)}/recovery-intent.json"


def task_index_key(task_id: str) -> str:
    if not _TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError("HISTORICAL_DEEP_TASK_ID_INVALID")
    return f"{R2_NAMESPACE}/task-index/task={task_id}.json"


def task_attempt_prefix(task: HarvestTask) -> str:
    return f"{task_prefix(task)}/attempts/"


class HarvestReceipt(FrozenContract):
    schema_version: str = RECEIPT_SCHEMA_VERSION
    campaign_id: str
    task_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    competition: str
    league_id: int = Field(gt=0)
    season: int
    family: str
    endpoint: str
    request_method: str = "GET"
    provider: str = "api-football"
    parameters: dict[str, str | int | float | bool | None]
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    temporal_class: TemporalClass
    status: TaskStatus
    requested_at: datetime
    received_at: datetime
    started_at: datetime
    completed_at: datetime
    heartbeat_at: datetime
    http_status: int = Field(ge=200, le=299)
    attempts: int = Field(ge=1, le=4)
    provider_calls: int = Field(ge=1, le=4)
    sanitized_quota_headers: dict[str, str] = Field(default_factory=dict)
    collector_version: str = Field(min_length=1, max_length=120)
    source_commit: str = Field(min_length=1, max_length=120)
    rows_normalized: int = Field(default=0, ge=0)
    error_code: None = None
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stored_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_bytes: int = Field(ge=0)
    stored_bytes: int = Field(gt=0)
    payload_key: str
    receipt_key: str
    checkpoint_key: str
    version_key: str
    recovery_key: str

    @model_validator(mode="after")
    def validate_receipt(self) -> HarvestReceipt:
        requested = ensure_utc(self.requested_at, field="requested_at")
        received = ensure_utc(self.received_at, field="received_at")
        started = ensure_utc(self.started_at, field="started_at")
        completed = ensure_utc(self.completed_at, field="completed_at")
        heartbeat = ensure_utc(self.heartbeat_at, field="heartbeat_at")
        if not started <= requested <= received <= completed:
            raise ValueError("HARVEST_RECEIPT_TEMPORAL_ORDER_INVALID")
        if not started <= heartbeat <= completed:
            raise ValueError("HARVEST_RECEIPT_HEARTBEAT_OUTSIDE_RUN")
        if self.status not in {TaskStatus.COMPLETE, TaskStatus.EMPTY_VALID}:
            raise ValueError("HARVEST_RECEIPT_REQUIRES_SUCCESS_STATUS")
        if self.request_method != "GET" or self.provider != "api-football":
            raise ValueError("HARVEST_RECEIPT_REQUEST_METADATA_INVALID")
        if self.parameters_hash != canonical_sha256(self.parameters):
            raise ValueError("HARVEST_RECEIPT_PARAMETERS_HASH_MISMATCH")
        if self.provider_calls < self.attempts:
            raise ValueError("HARVEST_RECEIPT_PROVIDER_CALLS_BELOW_ATTEMPTS")
        if any(
            key != key.casefold() or key not in _SAFE_QUOTA_HEADER_NAMES
            for key in self.sanitized_quota_headers
        ):
            raise ValueError("HARVEST_RECEIPT_CONTAINS_UNAPPROVED_QUOTA_HEADER")
        if not self.payload_key.endswith(
            f"/payload-{self.payload_sha256}.json.gz"
        ):
            raise ValueError("HARVEST_RECEIPT_PAYLOAD_KEY_HASH_MISMATCH")
        expected_prefix = self.payload_key.rsplit("/", 1)[0]
        expected_keys = {
            "receipt_key": f"{expected_prefix}/receipt.json",
            "checkpoint_key": f"{expected_prefix}/checkpoint.json",
            "version_key": f"{expected_prefix}/version.json",
            "recovery_key": f"{expected_prefix}/recovery-intent.json",
        }
        if any(getattr(self, name) != expected for name, expected in expected_keys.items()):
            raise ValueError("HARVEST_RECEIPT_OBJECT_KEYS_INCONSISTENT")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


class HarvestCheckpoint(FrozenContract):
    schema_version: str = CHECKPOINT_SCHEMA_VERSION
    task_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: TaskStatus
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_key: str
    checkpoint_key: str
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_checkpoint(self) -> HarvestCheckpoint:
        ensure_utc(self.recorded_at, field="recorded_at")
        if self.status not in {TaskStatus.COMPLETE, TaskStatus.EMPTY_VALID}:
            raise ValueError("HARVEST_CHECKPOINT_REQUIRES_SUCCESS_STATUS")
        return self


class TaskAttemptEvent(FrozenContract):
    """One immutable state transition in a task's provider-attempt journal."""

    schema_version: str = TASK_ATTEMPT_SCHEMA_VERSION
    campaign_id: str
    task_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    competition: str
    league_id: int = Field(gt=0)
    season: int
    family: str
    endpoint: str
    request_method: str = "GET"
    provider: str = "api-football"
    parameters: dict[str, str | int | float | bool | None]
    parameters_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1)
    temporal_class: TemporalClass
    attempt_number: int = Field(ge=1)
    event_index: int = Field(ge=1, le=3)
    status: TaskStatus
    attempts: int = Field(ge=0, le=4)
    provider_calls: int = Field(ge=0, le=4)
    started_at: datetime
    recorded_at: datetime
    heartbeat_at: datetime
    completed_at: datetime | None = None
    error_class: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$",
    )
    error_message: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]*(?::[A-Z0-9_]+)?$",
    )
    payload_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    r2_key: str | None = None
    rows_normalized: int | None = Field(default=None, ge=0)
    rows_received: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_attempt_event(self) -> TaskAttemptEvent:
        started = ensure_utc(self.started_at, field="started_at")
        recorded = ensure_utc(self.recorded_at, field="recorded_at")
        heartbeat = ensure_utc(self.heartbeat_at, field="heartbeat_at")
        if not started <= heartbeat <= recorded:
            raise ValueError("HARVEST_TASK_ATTEMPT_TEMPORAL_ORDER_INVALID")
        if self.completed_at is not None:
            completed = ensure_utc(self.completed_at, field="completed_at")
            if not started <= completed <= recorded:
                raise ValueError("HARVEST_TASK_ATTEMPT_COMPLETION_INVALID")
        expected_event_index = {
            TaskStatus.PENDING: 1,
            TaskStatus.RUNNING: 2,
        }.get(self.status, 3)
        if self.event_index != expected_event_index:
            raise ValueError("HARVEST_TASK_ATTEMPT_EVENT_INDEX_INVALID")
        if self.parameters_hash != canonical_sha256(self.parameters):
            raise ValueError("HARVEST_TASK_ATTEMPT_PARAMETERS_HASH_MISMATCH")
        if self.request_method != "GET" or self.provider != "api-football":
            raise ValueError("HARVEST_TASK_ATTEMPT_REQUEST_METADATA_INVALID")
        if self.provider_calls < self.attempts:
            raise ValueError("HARVEST_TASK_ATTEMPT_PROVIDER_CALLS_BELOW_ATTEMPTS")
        if self.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            if (
                self.completed_at is not None
                or self.error_class is not None
                or self.error_message is not None
                or self.payload_hash is not None
                or self.r2_key is not None
                or self.rows_normalized is not None
                or self.rows_received is not None
            ):
                raise ValueError("HARVEST_TASK_ATTEMPT_OPEN_STATE_INVALID")
        elif self.status not in _TASK_TERMINAL_STATUSES:
            raise ValueError("HARVEST_TASK_ATTEMPT_STATUS_INVALID")
        elif self.completed_at is None:
            raise ValueError("HARVEST_TASK_ATTEMPT_TERMINAL_REQUIRES_COMPLETION")
        if self.status in _TASK_FAILURE_STATUSES:
            if self.error_class is None or self.error_message is None:
                raise ValueError("HARVEST_TASK_ATTEMPT_FAILURE_REQUIRES_ERROR")
        elif self.error_class is not None or self.error_message is not None:
            raise ValueError("HARVEST_TASK_ATTEMPT_SUCCESS_CONTAINS_ERROR")
        if self.error_message is not None and not (
            self.error_message == "UNCLASSIFIED_ERROR"
            or self.error_message in _SAFE_PROVIDER_ERROR_MESSAGES
            or _SAFE_PROVIDER_HTTP_ERROR_PATTERN.fullmatch(self.error_message)
        ):
            raise ValueError("HARVEST_TASK_ATTEMPT_ERROR_MESSAGE_UNAPPROVED")
        if (self.payload_hash is None) != (self.r2_key is None):
            raise ValueError("HARVEST_TASK_ATTEMPT_PAYLOAD_POINTER_INCOMPLETE")
        if self.r2_key is not None and not self.r2_key.endswith(
            f"/payload-{self.payload_hash}.json.gz"
        ):
            raise ValueError("HARVEST_TASK_ATTEMPT_PAYLOAD_POINTER_INVALID")
        return self

    @property
    def event_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def task_attempt_key(task: HarvestTask, event: TaskAttemptEvent) -> str:
    if event.task_id != task.task_id or event.task_hash != task.task_hash:
        raise ValueError("HARVEST_TASK_ATTEMPT_TASK_MISMATCH")
    return (
        f"{task_attempt_prefix(task)}"
        f"attempt={event.attempt_number:06d}/"
        f"event={event.event_index:02d}-{event.status.value}-"
        f"{event.event_hash}.json"
    )


class TaskVersion(FrozenContract):
    schema_version: str = TASK_VERSION_SCHEMA_VERSION
    task: HarvestTask
    receipt: HarvestReceipt
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_key: str

    @model_validator(mode="after")
    def validate_version(self) -> TaskVersion:
        if self.task_hash != self.task.task_hash:
            raise ValueError("HARVEST_TASK_VERSION_HASH_MISMATCH")
        if self.version_key != version_key(self.task):
            raise ValueError("HARVEST_TASK_VERSION_KEY_MISMATCH")
        if (
            self.receipt.task_id != self.task.task_id
            or self.receipt.task_hash != self.task_hash
            or self.receipt.version_key != self.version_key
        ):
            raise ValueError("HARVEST_TASK_VERSION_RECEIPT_MISMATCH")
        return self


@dataclass(frozen=True, slots=True)
class StoredPayload:
    receipt: HarvestReceipt
    payload: object
    recovery_created: bool
    version_created: bool
    payload_created: bool
    receipt_created: bool
    checkpoint_created: bool
    index_created: bool


def _payload_is_empty(payload: object) -> bool:
    if isinstance(payload, list):
        return not payload
    if isinstance(payload, dict):
        response = payload.get("response")
        return isinstance(response, list) and not response
    return False


def _sanitize_quota_headers(
    headers: Mapping[str, object] | None,
) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for raw_key, value in (headers or {}).items():
        key = str(raw_key).casefold()
        if key in _SENSITIVE_HEADER_NAMES:
            raise ValueError("HARVEST_CAPTURE_SENSITIVE_HEADER_FORBIDDEN")
        looks_like_quota_header = (
            key == "retry-after"
            or key.startswith("x-ratelimit")
            or key.startswith("x-rate-limit")
            or key.startswith("x-requests-")
        )
        if looks_like_quota_header and key not in _SAFE_QUOTA_HEADER_NAMES:
            raise ValueError("HARVEST_CAPTURE_UNAPPROVED_QUOTA_HEADER_FORBIDDEN")
        if key in _SAFE_QUOTA_HEADER_NAMES:
            sanitized[key] = str(value)
    return dict(sorted(sanitized.items()))


def _sanitized_error(error: BaseException) -> tuple[str, str]:
    error_class = type(error).__name__
    if not _SAFE_ERROR_CLASS_PATTERN.fullmatch(error_class):
        error_class = "UnclassifiedError"
    raw_message = error.args[0] if len(error.args) == 1 else None
    error_message = (
        raw_message
        if isinstance(raw_message, str)
        and _SAFE_ERROR_MESSAGE_PATTERN.fullmatch(raw_message)
        and (
            raw_message in _SAFE_PROVIDER_ERROR_MESSAGES
            or _SAFE_PROVIDER_HTTP_ERROR_PATTERN.fullmatch(raw_message)
        )
        else "UNCLASSIFIED_ERROR"
    )
    return error_class, error_message


class R2FirstRepository:
    """Raw payload authority with immutable receipts and provider-free recovery."""

    def __init__(
        self,
        store: ObjectStore,
        *,
        namespace: str = R2_NAMESPACE,
    ) -> None:
        if namespace != R2_NAMESPACE:
            raise ValueError("HISTORICAL_DEEP_R2_NAMESPACE_MUST_BE_CANONICAL")
        if not isinstance(store, ObjectStore):
            raise TypeError("HISTORICAL_DEEP_OBJECT_STORE_PROTOCOL_REQUIRED")
        self.store = store
        self.namespace = namespace

    @staticmethod
    def _put_immutable(store: ObjectStore, key: str, data: bytes) -> bool:
        created = store.put_if_absent(key, data)
        if created:
            return True
        existing = store.get_object(key)
        if existing is None:
            raise AppendOnlyViolation("HISTORICAL_DEEP_CONDITIONAL_WRITE_INCONSISTENT")
        if existing != data:
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_APPEND_ONLY_OBJECT_MISMATCH:{key}"
            )
        return False

    @staticmethod
    def _attempt_matches_task(
        event: TaskAttemptEvent,
        task: HarvestTask,
    ) -> bool:
        return (
            event.campaign_id == task.campaign_id
            and event.task_id == task.task_id
            and event.task_hash == task.task_hash
            and event.competition == task.competition
            and event.league_id == task.league_id
            and event.season == task.season
            and event.family == task.family.value
            and event.endpoint == task.endpoint
            and event.parameters == task.params
            and event.parameters_hash == canonical_sha256(task.params)
            and event.page == task.page
            and event.temporal_class == task.temporal_class
        )

    def _read_task_attempt_at(
        self,
        task: HarvestTask,
        key: str,
    ) -> TaskAttemptEvent:
        raw = self.store.get_object(key)
        if raw is None:
            raise PayloadIntegrityError("HARVEST_TASK_ATTEMPT_MISSING")
        try:
            event = TaskAttemptEvent.model_validate_json(raw)
        except ValueError as exc:
            raise PayloadIntegrityError("HARVEST_TASK_ATTEMPT_INVALID") from exc
        if not self._attempt_matches_task(event, task):
            raise PayloadIntegrityError("HARVEST_TASK_ATTEMPT_TASK_MISMATCH")
        if task_attempt_key(task, event) != key:
            raise PayloadIntegrityError("HARVEST_TASK_ATTEMPT_KEY_MISMATCH")
        return event

    def iter_task_attempts(
        self,
        task: HarvestTask,
    ) -> Iterator[TaskAttemptEvent]:
        """Read the hash-addressed append-only attempt journal for one task."""

        for key in self.store.iter_keys(task_attempt_prefix(task)):
            if key.endswith(".json"):
                yield self._read_task_attempt_at(task, key)

    def next_task_attempt_number(self, task: HarvestTask) -> int:
        return max(
            (event.attempt_number for event in self.iter_task_attempts(task)),
            default=0,
        ) + 1

    def record_task_attempt(
        self,
        *,
        task: HarvestTask,
        attempt_number: int,
        status: TaskStatus,
        started_at: datetime,
        recorded_at: datetime,
        heartbeat_at: datetime | None = None,
        completed_at: datetime | None = None,
        attempts: int = 0,
        provider_calls: int = 0,
        error: BaseException | None = None,
        payload_hash: str | None = None,
        r2_key: str | None = None,
        rows_normalized: int | None = None,
        rows_received: int | None = None,
        known_events: Sequence[TaskAttemptEvent] | None = None,
    ) -> TaskAttemptEvent:
        """Append one secret-safe state transition without changing receipts."""

        normalized_status = TaskStatus(status)
        terminal = normalized_status in _TASK_TERMINAL_STATUSES
        error_class: str | None = None
        error_message: str | None = None
        if error is not None:
            error_class, error_message = _sanitized_error(error)
        event = TaskAttemptEvent(
            campaign_id=task.campaign_id,
            task_id=task.task_id,
            task_hash=task.task_hash,
            competition=task.competition,
            league_id=task.league_id,
            season=task.season,
            family=task.family.value,
            endpoint=task.endpoint,
            parameters=dict(task.params),
            parameters_hash=canonical_sha256(task.params),
            page=task.page,
            temporal_class=task.temporal_class,
            attempt_number=attempt_number,
            event_index=(
                1
                if normalized_status is TaskStatus.PENDING
                else 2
                if normalized_status is TaskStatus.RUNNING
                else 3
            ),
            status=normalized_status,
            attempts=attempts,
            provider_calls=provider_calls,
            started_at=started_at,
            recorded_at=recorded_at,
            heartbeat_at=heartbeat_at or recorded_at,
            completed_at=(completed_at or recorded_at) if terminal else None,
            error_class=error_class,
            error_message=error_message,
            payload_hash=payload_hash,
            r2_key=r2_key,
            rows_normalized=rows_normalized,
            rows_received=rows_received,
        )
        key = task_attempt_key(task, event)
        event_bytes = canonical_json_bytes(event.model_dump(mode="json"))
        existing_bytes = self.store.get_object(key)
        if existing_bytes is not None:
            if existing_bytes != event_bytes:
                raise AppendOnlyViolation(
                    f"HISTORICAL_DEEP_TASK_ATTEMPT_MISMATCH:{task.task_id}"
                )
            return self._read_task_attempt_at(task, key)

        journal = (
            tuple(self.iter_task_attempts(task))
            if known_events is None
            else tuple(
                sorted(
                    known_events,
                    key=lambda item: (
                        item.attempt_number,
                        item.event_index,
                        item.recorded_at,
                    ),
                )
            )
        )
        if any(not self._attempt_matches_task(item, task) for item in journal):
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_TASK_ATTEMPT_TASK_MISMATCH:{task.task_id}"
            )
        current_attempt = tuple(
            item for item in journal if item.attempt_number == attempt_number
        )
        expected_statuses: tuple[TaskStatus, ...]
        if normalized_status is TaskStatus.PENDING:
            expected_statuses = ()
        elif normalized_status is TaskStatus.RUNNING:
            expected_statuses = (TaskStatus.PENDING,)
        else:
            expected_statuses = (TaskStatus.PENDING, TaskStatus.RUNNING)
        if (
            normalized_status is TaskStatus.PENDING
            and attempt_number
            != max((item.attempt_number for item in journal), default=0) + 1
        ):
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_TASK_ATTEMPT_NUMBER_INVALID:{task.task_id}"
            )
        if tuple(item.status for item in current_attempt) != expected_statuses:
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_TASK_ATTEMPT_TRANSITION_INVALID:{task.task_id}"
            )
        self._put_immutable(self.store, key, event_bytes)
        return event

    @staticmethod
    def _build_materialization(
        *,
        task: HarvestTask,
        payload: object,
        requested_at: datetime,
        received_at: datetime,
        http_status: int,
        status: TaskStatus | None,
        sanitized_quota_headers: Mapping[str, object] | None,
        collector_version: str,
        source_commit: str,
        attempts: int,
        provider_calls: int,
        rows_normalized: int,
        started_at: datetime | None,
        completed_at: datetime | None,
        heartbeat_at: datetime | None,
    ) -> tuple[
        HarvestReceipt,
        TaskVersion,
        HarvestCheckpoint,
        bytes,
        bytes,
        bytes,
        bytes,
        bytes,
        bytes,
    ]:
        requested = ensure_utc(requested_at, field="requested_at")
        received = ensure_utc(received_at, field="received_at")
        if requested > received:
            raise ValueError("HARVEST_CAPTURE_TEMPORAL_ORDER_INVALID")
        if not 200 <= http_status <= 299:
            raise ValueError("HARVEST_CAPTURE_REQUIRES_SUCCESS_HTTP_STATUS")
        canonical_payload = canonical_json_bytes(payload)
        payload_sha256 = hashlib.sha256(canonical_payload).hexdigest()
        compressed_payload = gzip.compress(
            canonical_payload,
            compresslevel=9,
            mtime=0,
        )
        final_status = status or (
            TaskStatus.EMPTY_VALID if _payload_is_empty(payload) else TaskStatus.COMPLETE
        )
        started = ensure_utc(
            started_at or requested,
            field="started_at",
        )
        completed = ensure_utc(
            completed_at or received,
            field="completed_at",
        )
        heartbeat = ensure_utc(
            heartbeat_at or completed,
            field="heartbeat_at",
        )
        parameters = dict(task.params)
        receipt = HarvestReceipt(
            campaign_id=task.campaign_id,
            task_id=task.task_id,
            task_hash=task.task_hash,
            competition=task.competition,
            league_id=task.league_id,
            season=task.season,
            family=task.family.value,
            endpoint=task.endpoint,
            parameters=parameters,
            parameters_hash=canonical_sha256(parameters),
            page=task.page,
            temporal_class=task.temporal_class,
            status=final_status,
            requested_at=requested,
            received_at=received,
            started_at=started,
            completed_at=completed,
            heartbeat_at=heartbeat,
            http_status=http_status,
            attempts=attempts,
            provider_calls=provider_calls,
            sanitized_quota_headers=_sanitize_quota_headers(
                sanitized_quota_headers
            ),
            collector_version=collector_version,
            source_commit=source_commit,
            rows_normalized=rows_normalized,
            payload_sha256=payload_sha256,
            stored_sha256=hashlib.sha256(compressed_payload).hexdigest(),
            payload_bytes=len(canonical_payload),
            stored_bytes=len(compressed_payload),
            payload_key=payload_key(task, payload_sha256),
            receipt_key=receipt_key(task),
            checkpoint_key=checkpoint_key(task),
            version_key=version_key(task),
            recovery_key=recovery_key(task),
        )
        version = TaskVersion(
            task=task,
            receipt=receipt,
            task_hash=task.task_hash,
            version_key=version_key(task),
        )
        checkpoint = HarvestCheckpoint(
            task_id=task.task_id,
            task_hash=task.task_hash,
            status=receipt.status,
            payload_sha256=payload_sha256,
            receipt_hash=receipt.receipt_hash,
            receipt_key=receipt.receipt_key,
            checkpoint_key=receipt.checkpoint_key,
            recorded_at=received,
        )
        receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json"))
        version_bytes = canonical_json_bytes(version.model_dump(mode="json"))
        checkpoint_bytes = canonical_json_bytes(checkpoint.model_dump(mode="json"))
        index_bytes = canonical_json_bytes(
            {
                "schema_version": TASK_INDEX_SCHEMA_VERSION,
                "task_id": task.task_id,
                "task_hash": task.task_hash,
                "receipt_hash": receipt.receipt_hash,
                "receipt_key": receipt.receipt_key,
                "payload_key": receipt.payload_key,
            }
        )
        recovery_bytes = canonical_json_bytes(
            {
                "schema_version": RECOVERY_SCHEMA_VERSION,
                "task_id": task.task_id,
                "task_hash": task.task_hash,
                "receipt_hash": receipt.receipt_hash,
                "version_key": receipt.version_key,
                "payload_key": receipt.payload_key,
                "payload_sha256": receipt.payload_sha256,
                "stored_sha256": receipt.stored_sha256,
            }
        )
        return (
            receipt,
            version,
            checkpoint,
            compressed_payload,
            receipt_bytes,
            version_bytes,
            checkpoint_bytes,
            index_bytes,
            recovery_bytes,
        )

    def capture(
        self,
        *,
        task: HarvestTask,
        payload: object,
        requested_at: datetime,
        received_at: datetime,
        http_status: int = 200,
        status: TaskStatus | None = None,
        sanitized_quota_headers: Mapping[str, object] | None = None,
        collector_version: str = "historical-deep-collector-v1",
        source_commit: str = "UNSPECIFIED",
        attempts: int = 1,
        provider_calls: int | None = None,
        rows_normalized: int = 0,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        heartbeat_at: datetime | None = None,
    ) -> StoredPayload:
        """Durably own response bytes before acknowledging task completion."""

        materialization = self._build_materialization(
            task=task,
            payload=payload,
            requested_at=requested_at,
            received_at=received_at,
            http_status=http_status,
            status=status,
            sanitized_quota_headers=sanitized_quota_headers,
            collector_version=collector_version,
            source_commit=source_commit,
            attempts=attempts,
            provider_calls=provider_calls if provider_calls is not None else attempts,
            rows_normalized=rows_normalized,
            started_at=started_at,
            completed_at=completed_at,
            heartbeat_at=heartbeat_at,
        )
        (
            receipt,
            _version,
            _checkpoint,
            compressed_payload,
            receipt_bytes,
            version_bytes,
            checkpoint_bytes,
            index_bytes,
            recovery_bytes,
        ) = materialization

        existing = self.receipt_for(task)
        if existing is not None:
            if existing.payload_sha256 != receipt.payload_sha256:
                raise AppendOnlyViolation(
                    f"HISTORICAL_DEEP_TASK_PAYLOAD_MISMATCH:{task.task_id}"
                )
            stored_payload = self.read_payload(existing)
            return StoredPayload(
                receipt=existing,
                payload=stored_payload,
                recovery_created=False,
                version_created=False,
                payload_created=False,
                receipt_created=False,
                checkpoint_created=False,
                index_created=False,
            )

        version_created = self.store.put_if_absent(
            receipt.version_key,
            version_bytes,
        )
        durable_version_bytes = (
            version_bytes
            if version_created
            else self.store.get_object(receipt.version_key)
        )
        if durable_version_bytes is None:
            raise AppendOnlyViolation(
                "HISTORICAL_DEEP_CONDITIONAL_WRITE_INCONSISTENT"
            )
        try:
            durable_version = TaskVersion.model_validate_json(
                durable_version_bytes
            )
        except ValueError as exc:
            raise PayloadIntegrityError(
                "HARVEST_TASK_VERSION_INVALID"
            ) from exc
        if durable_version.task != task:
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_TASK_VERSION_MISMATCH:{task.task_id}"
            )
        if durable_version.receipt.payload_sha256 != receipt.payload_sha256:
            raise AppendOnlyViolation(
                f"HISTORICAL_DEEP_TASK_PAYLOAD_MISMATCH:{task.task_id}"
            )

        durable_receipt = durable_version.receipt
        durable_materialization = self._build_materialization(
            task=durable_version.task,
            payload=payload,
            requested_at=durable_receipt.requested_at,
            received_at=durable_receipt.received_at,
            http_status=durable_receipt.http_status,
            status=durable_receipt.status,
            sanitized_quota_headers=durable_receipt.sanitized_quota_headers,
            collector_version=durable_receipt.collector_version,
            source_commit=durable_receipt.source_commit,
            attempts=durable_receipt.attempts,
            provider_calls=durable_receipt.provider_calls,
            rows_normalized=durable_receipt.rows_normalized,
            started_at=durable_receipt.started_at,
            completed_at=durable_receipt.completed_at,
            heartbeat_at=durable_receipt.heartbeat_at,
        )
        (
            receipt,
            _version,
            _checkpoint,
            compressed_payload,
            receipt_bytes,
            rebuilt_version_bytes,
            checkpoint_bytes,
            index_bytes,
            recovery_bytes,
        ) = durable_materialization
        if rebuilt_version_bytes != durable_version_bytes:
            raise PayloadIntegrityError(
                "HARVEST_TASK_VERSION_MATERIALIZATION_MISMATCH"
            )

        payload_created = self._put_immutable(
            self.store,
            receipt.payload_key,
            compressed_payload,
        )
        recovery_created = self._put_immutable(
            self.store,
            receipt.recovery_key,
            recovery_bytes,
        )
        receipt_created = self._put_immutable(
            self.store,
            receipt.receipt_key,
            receipt_bytes,
        )
        checkpoint_created = self._put_immutable(
            self.store,
            receipt.checkpoint_key,
            checkpoint_bytes,
        )
        index_created = self._put_immutable(
            self.store,
            task_index_key(task.task_id),
            index_bytes,
        )
        return StoredPayload(
            receipt=receipt,
            payload=payload,
            recovery_created=recovery_created,
            version_created=version_created,
            payload_created=payload_created,
            receipt_created=receipt_created,
            checkpoint_created=checkpoint_created,
            index_created=index_created,
        )

    @staticmethod
    def _decode_json(data: bytes, *, error: str) -> dict[str, object]:
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadIntegrityError(error) from exc
        if not isinstance(value, dict):
            raise PayloadIntegrityError(error)
        return value

    def _recover_intent(self, intent_key: str) -> HarvestReceipt:
        intent_bytes = self.store.get_object(intent_key)
        if intent_bytes is None:
            raise PayloadIntegrityError("HARVEST_RECOVERY_INTENT_DISAPPEARED")
        intent = self._decode_json(
            intent_bytes,
            error="HARVEST_RECOVERY_INTENT_INVALID",
        )
        if intent.get("schema_version") != RECOVERY_SCHEMA_VERSION:
            raise PayloadIntegrityError("HARVEST_RECOVERY_SCHEMA_INVALID")
        version_key_value = intent.get("version_key")
        if not isinstance(version_key_value, str):
            raise PayloadIntegrityError("HARVEST_RECOVERY_VERSION_KEY_MISSING")
        version_bytes = self.store.get_object(version_key_value)
        if version_bytes is None:
            raise PayloadIntegrityError("HARVEST_RECOVERY_VERSION_MISSING")
        try:
            version = TaskVersion.model_validate_json(version_bytes)
        except ValueError as exc:
            raise PayloadIntegrityError("HARVEST_RECOVERY_INTENT_INVALID") from exc
        task = version.task
        receipt = version.receipt
        compressed = self.store.get_object(receipt.payload_key)
        if compressed is None:
            raise PayloadIntegrityError("HARVEST_RECOVERY_PAYLOAD_MISSING")
        if intent_key != receipt.recovery_key or receipt.recovery_key != recovery_key(task):
            raise PayloadIntegrityError("HARVEST_RECOVERY_KEY_MISMATCH")
        if task.task_hash != receipt.task_hash or task.task_id != receipt.task_id:
            raise PayloadIntegrityError("HARVEST_RECOVERY_TASK_MISMATCH")
        if receipt.parameters != task.params:
            raise PayloadIntegrityError("HARVEST_RECOVERY_PARAMETERS_MISMATCH")
        if (
            intent.get("task_id") != task.task_id
            or intent.get("task_hash") != task.task_hash
            or intent.get("receipt_hash") != receipt.receipt_hash
            or intent.get("payload_key") != receipt.payload_key
            or intent.get("payload_sha256") != receipt.payload_sha256
            or intent.get("stored_sha256") != receipt.stored_sha256
        ):
            raise PayloadIntegrityError("HARVEST_RECOVERY_POINTER_MISMATCH")
        if hashlib.sha256(compressed).hexdigest() != receipt.stored_sha256:
            raise PayloadIntegrityError("HARVEST_RECOVERY_COMPRESSED_HASH_MISMATCH")
        try:
            canonical_payload = gzip.decompress(compressed)
            decoded_payload = json.loads(canonical_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadIntegrityError("HARVEST_RECOVERY_PAYLOAD_INVALID") from exc
        if canonical_json_bytes(decoded_payload) != canonical_payload:
            raise PayloadIntegrityError("HARVEST_RECOVERY_PAYLOAD_NOT_CANONICAL")
        if hashlib.sha256(canonical_payload).hexdigest() != receipt.payload_sha256:
            raise PayloadIntegrityError("HARVEST_RECOVERY_PAYLOAD_HASH_MISMATCH")

        version = TaskVersion(
            task=task,
            receipt=receipt,
            task_hash=task.task_hash,
            version_key=receipt.version_key,
        )
        checkpoint = HarvestCheckpoint(
            task_id=task.task_id,
            task_hash=task.task_hash,
            status=receipt.status,
            payload_sha256=receipt.payload_sha256,
            receipt_hash=receipt.receipt_hash,
            receipt_key=receipt.receipt_key,
            checkpoint_key=receipt.checkpoint_key,
            recorded_at=receipt.received_at,
        )
        self._put_immutable(
            self.store,
            receipt.version_key,
            canonical_json_bytes(version.model_dump(mode="json")),
        )
        self._put_immutable(self.store, receipt.payload_key, compressed)
        self._put_immutable(
            self.store,
            receipt.receipt_key,
            canonical_json_bytes(receipt.model_dump(mode="json")),
        )
        self._put_immutable(
            self.store,
            receipt.checkpoint_key,
            canonical_json_bytes(checkpoint.model_dump(mode="json")),
        )
        self._put_immutable(
            self.store,
            task_index_key(task.task_id),
            canonical_json_bytes(
                {
                    "schema_version": TASK_INDEX_SCHEMA_VERSION,
                    "task_id": task.task_id,
                    "task_hash": task.task_hash,
                    "receipt_hash": receipt.receipt_hash,
                    "receipt_key": receipt.receipt_key,
                    "payload_key": receipt.payload_key,
                }
            ),
        )
        return receipt

    def _recover_version(self, key: str) -> HarvestReceipt | None:
        version_bytes = self.store.get_object(key)
        if version_bytes is None:
            raise PayloadIntegrityError("HARVEST_TASK_VERSION_MISSING")
        try:
            version = TaskVersion.model_validate_json(version_bytes)
        except ValueError as exc:
            raise PayloadIntegrityError("HARVEST_TASK_VERSION_INVALID") from exc
        receipt = version.receipt
        compressed = self.store.get_object(receipt.payload_key)
        if compressed is None:
            return None
        if hashlib.sha256(compressed).hexdigest() != receipt.stored_sha256:
            raise PayloadIntegrityError("HARVEST_TASK_VERSION_PAYLOAD_MISMATCH")
        recovery_bytes = canonical_json_bytes(
            {
                "schema_version": RECOVERY_SCHEMA_VERSION,
                "task_id": version.task.task_id,
                "task_hash": version.task_hash,
                "receipt_hash": receipt.receipt_hash,
                "version_key": receipt.version_key,
                "payload_key": receipt.payload_key,
                "payload_sha256": receipt.payload_sha256,
                "stored_sha256": receipt.stored_sha256,
            }
        )
        self._put_immutable(
            self.store,
            receipt.recovery_key,
            recovery_bytes,
        )
        return self._recover_intent(receipt.recovery_key)

    def resume_pending(
        self,
        *,
        known_versions: Mapping[str, TaskVersion] | None = None,
        known_keys: Iterable[str] | None = None,
    ) -> tuple[HarvestReceipt, ...]:
        """Complete every write-ahead intent without another provider call."""

        if (known_versions is None) != (known_keys is None):
            raise ValueError(
                "HARVEST_RECOVERY_SNAPSHOT_REQUIRES_VERSIONS_AND_KEYS"
            )
        recovered: dict[str, HarvestReceipt] = {}
        prefix = f"{self.namespace}/competition="
        if known_keys is None:
            keys = tuple(self.store.iter_keys(prefix))
            known_key_set = set(keys)
            known_key_set.update(
                self.store.iter_keys(f"{self.namespace}/task-index/")
            )
        else:
            known_key_set = set(known_keys)
            keys = tuple(
                sorted(key for key in known_key_set if key.startswith(prefix))
            )
        versions_by_key = {
            item.version_key: item for item in (known_versions or {}).values()
        }
        complete_recovery_keys: set[str] = set()
        for key in keys:
            if key.endswith("/version.json"):
                version = versions_by_key.get(key)
                if version is None:
                    version_bytes = self.store.get_object(key)
                    if version_bytes is None:
                        raise PayloadIntegrityError("HARVEST_TASK_VERSION_MISSING")
                    try:
                        version = TaskVersion.model_validate_json(version_bytes)
                    except ValueError as exc:
                        raise PayloadIntegrityError(
                            "HARVEST_TASK_VERSION_INVALID"
                        ) from exc
                receipt = version.receipt
                materialization_keys = {
                    receipt.version_key,
                    receipt.payload_key,
                    receipt.recovery_key,
                    receipt.receipt_key,
                    receipt.checkpoint_key,
                    task_index_key(version.task.task_id),
                }
                if materialization_keys <= known_key_set:
                    complete_recovery_keys.add(receipt.recovery_key)
                    continue
                recovered_receipt = self._recover_version(key)
                if recovered_receipt is not None:
                    recovered[recovered_receipt.task_id] = recovered_receipt
                    known_key_set.update(materialization_keys)
                    complete_recovery_keys.add(
                        recovered_receipt.recovery_key
                    )
        for key in keys:
            if (
                key.endswith("/recovery-intent.json")
                and key not in complete_recovery_keys
            ):
                receipt = self._recover_intent(key)
                recovered[receipt.task_id] = receipt
        return tuple(recovered[key] for key in sorted(recovered))

    def _read_receipt_at(self, key: str) -> HarvestReceipt:
        raw = self.store.get_object(key)
        if raw is None:
            raise PayloadIntegrityError("HARVEST_RECEIPT_MISSING")
        try:
            receipt = HarvestReceipt.model_validate_json(raw)
        except ValueError as exc:
            raise PayloadIntegrityError("HARVEST_RECEIPT_INVALID") from exc
        if receipt.receipt_key != key:
            raise PayloadIntegrityError("HARVEST_RECEIPT_KEY_MISMATCH")
        return receipt

    def receipt_for(
        self,
        task: HarvestTask | str,
    ) -> HarvestReceipt | None:
        if isinstance(task, HarvestTask):
            direct_key = receipt_key(task)
            if self.store.get_object(direct_key) is None:
                if self.store.get_object(recovery_key(task)) is not None:
                    self._recover_intent(recovery_key(task))
                elif self.store.get_object(version_key(task)) is not None:
                    self._recover_version(version_key(task))
            if self.store.get_object(direct_key) is None:
                return None
            receipt = self._read_receipt_at(direct_key)
            if receipt.task_hash != task.task_hash:
                raise PayloadIntegrityError("HARVEST_RECEIPT_TASK_HASH_MISMATCH")
            return receipt

        index_key = task_index_key(task)
        raw_index = self.store.get_object(index_key)
        if raw_index is None:
            self.resume_pending()
            raw_index = self.store.get_object(index_key)
        if raw_index is None:
            return None
        index = self._decode_json(raw_index, error="HARVEST_TASK_INDEX_INVALID")
        if (
            index.get("schema_version") != TASK_INDEX_SCHEMA_VERSION
            or index.get("task_id") != task
            or not isinstance(index.get("receipt_key"), str)
        ):
            raise PayloadIntegrityError("HARVEST_TASK_INDEX_INVALID")
        receipt = self._read_receipt_at(str(index["receipt_key"]))
        if (
            receipt.task_id != task
            or receipt.receipt_hash != index.get("receipt_hash")
            or receipt.payload_key != index.get("payload_key")
        ):
            raise PayloadIntegrityError("HARVEST_TASK_INDEX_MISMATCH")
        return receipt

    load_receipt = receipt_for

    def contains(self, task: HarvestTask | str) -> bool:
        return self.receipt_for(task) is not None

    def read_payload(self, receipt: HarvestReceipt) -> object:
        raw = self.store.get_object(receipt.payload_key)
        if raw is None:
            raise PayloadIntegrityError("HARVEST_PAYLOAD_MISSING")
        if len(raw) != receipt.stored_bytes:
            raise PayloadIntegrityError("HARVEST_STORED_BYTES_MISMATCH")
        if hashlib.sha256(raw).hexdigest() != receipt.stored_sha256:
            raise PayloadIntegrityError("HARVEST_STORED_SHA256_MISMATCH")
        try:
            canonical_payload = gzip.decompress(raw)
            payload = json.loads(canonical_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PayloadIntegrityError("HARVEST_PAYLOAD_INVALID") from exc
        if len(canonical_payload) != receipt.payload_bytes:
            raise PayloadIntegrityError("HARVEST_PAYLOAD_BYTES_MISMATCH")
        if canonical_json_bytes(payload) != canonical_payload:
            raise PayloadIntegrityError("HARVEST_PAYLOAD_NOT_CANONICAL")
        if hashlib.sha256(canonical_payload).hexdigest() != receipt.payload_sha256:
            raise PayloadIntegrityError("HARVEST_PAYLOAD_HASH_MISMATCH")
        return payload

    def payload_for(
        self,
        task: HarvestTask | HarvestReceipt | str,
    ) -> object | None:
        if isinstance(task, HarvestReceipt):
            return self.read_payload(task)
        receipt = self.receipt_for(task)
        return None if receipt is None else self.read_payload(receipt)

    load_payload = payload_for

    def write_checkpoint(
        self,
        *,
        task: HarvestTask,
        receipt: HarvestReceipt | None = None,
    ) -> HarvestCheckpoint:
        durable_receipt = receipt or self.receipt_for(task)
        if durable_receipt is None:
            raise ValueError("HARVEST_CHECKPOINT_REQUIRES_DURABLE_RECEIPT")
        checkpoint = HarvestCheckpoint(
            task_id=task.task_id,
            task_hash=task.task_hash,
            status=durable_receipt.status,
            payload_sha256=durable_receipt.payload_sha256,
            receipt_hash=durable_receipt.receipt_hash,
            receipt_key=durable_receipt.receipt_key,
            checkpoint_key=durable_receipt.checkpoint_key,
            recorded_at=durable_receipt.received_at,
        )
        self._put_immutable(
            self.store,
            checkpoint.checkpoint_key,
            canonical_json_bytes(checkpoint.model_dump(mode="json")),
        )
        return checkpoint

    checkpoint = write_checkpoint

    def iter_receipts(self) -> Iterator[HarvestReceipt]:
        """Iterate durable receipts without mutating or repairing raw evidence."""

        prefix = f"{self.namespace}/competition="
        for key in self.store.iter_keys(prefix):
            if key.endswith("/receipt.json"):
                yield self._read_receipt_at(key)

    def iter_captures(self) -> Iterator[StoredPayload]:
        """Safely read every receipt and its hash-verified raw payload."""

        for receipt in self.iter_receipts():
            yield StoredPayload(
                receipt=receipt,
                payload=self.read_payload(receipt),
                recovery_created=False,
                version_created=False,
                payload_created=False,
                receipt_created=False,
                checkpoint_created=False,
                index_created=False,
            )
