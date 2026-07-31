"""Checkpointed, provider-free replay for the Historical Deep continuation.

The module deliberately separates immutable inventory, independent segment
projection, sequential staging reduction, and a second idempotence pass.  Raw
provider payloads never leave the object store.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import signal
import time
import tracemalloc
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .contracts import HarvestTask, TaskStatus, canonical_json_bytes, canonical_sha256
from .normalization import NormalizationError, normalize_payload
from .replay import replay_stream_cache_only
from .runtime import DERIVED_NAMESPACE, DurableRuntimeLedger, read_objects_bounded
from .storage import (
    HarvestReceipt,
    R2FirstRepository,
    TaskAttemptEvent,
    TaskVersion,
    task_attempt_key,
)

INVENTORY_SCHEMA_VERSION = "historical-deep-replay-inventory-v2"
SEGMENT_SCHEMA_VERSION = "historical-deep-replay-segment-v2"
SEGMENT_CHECKPOINT_SCHEMA_VERSION = "historical-deep-replay-checkpoint-v2"
REDUCER_SCHEMA_VERSION = "historical-deep-replay-reducer-v2"
CONTINUATION_SCHEMA_VERSION = "historical-deep-continuation-v1"

DEFAULT_MAX_OBJECTS = 250
DEFAULT_MAX_LOGICAL_BYTES = 75 * 1024 * 1024
DEFAULT_MAX_ESTIMATED_SECONDS = 10 * 60
DEFAULT_ESTIMATED_SECONDS_PER_OBJECT = 2.4
CHECKPOINT_MAX_OBJECTS = 50
CHECKPOINT_MAX_SECONDS = 5 * 60
STALE_HEARTBEAT_MINUTES = 15
GITHUB_MATRIX_MAX_JOBS = 256
SEGMENTS_PER_MATRIX_JOB = 2

STAGING_TABLES = (
    "fixtures",
    "teams",
    "venues",
    "referees",
    "events",
    "lineups",
    "lineup_players",
    "formations",
    "team_match_statistics",
    "player_match_statistics",
    "players",
    "player_season_statistics",
    "injuries",
    "suspensions",
    "standings",
    "rounds",
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ATTEMPT_TASK_ID = re.compile(r"/task=([0-9a-f]{64})/attempts/")


class RunnerShutdownRecovered(RuntimeError):
    """Raised after the current bounded checkpoint is durably persisted."""


def build_segment_batches(
    segment_ids: Sequence[str],
    *,
    segments_per_batch: int = SEGMENTS_PER_MATRIX_JOB,
    max_batches: int = GITHUB_MATRIX_MAX_JOBS,
) -> list[dict[str, str]]:
    """Pack bounded replay segments into a GitHub-compatible matrix."""

    if segments_per_batch < 1 or max_batches < 1:
        raise ValueError("REPLAY_SEGMENT_BATCH_LIMIT_INVALID")
    if len(set(segment_ids)) != len(segment_ids) or any(
        not _SAFE_ID.fullmatch(segment_id) for segment_id in segment_ids
    ):
        raise ValueError("REPLAY_SEGMENT_BATCH_IDS_INVALID")
    batches = [
        {
            "batch_id": f"batch-{ordinal:04d}",
            "segment_ids_json": json.dumps(
                list(segment_ids[offset : offset + segments_per_batch]),
                separators=(",", ":"),
            ),
        }
        for ordinal, offset in enumerate(
            range(0, len(segment_ids), segments_per_batch),
            start=1,
        )
    ]
    if len(batches) > max_batches:
        raise ValueError(
            f"REPLAY_SEGMENT_MATRIX_LIMIT_EXCEEDED:{len(batches)}>{max_batches}"
        )
    return batches


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise ValueError(f"{label}_MUST_BE_A_MAPPING")


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    raise ValueError(f"{label}_MUST_BE_A_SEQUENCE")


def _integer(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{label}_MUST_BE_AN_INTEGER")
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{label}_MUST_BE_AN_INTEGER") from error
    if parsed < minimum:
        raise ValueError(f"{label}_BELOW_MINIMUM")
    return parsed


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label}_MUST_BE_NUMERIC")
    try:
        return float(value)
    except ValueError as error:
        raise ValueError(f"{label}_MUST_BE_NUMERIC") from error


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label}_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _validate_id(value: str, *, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label}_INVALID")
    return value


def _decode_json_bytes(data: bytes, *, label: str) -> object:
    try:
        raw = gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data
        return json.loads(raw)
    except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_INVALID") from error


def _put_immutable(store: Any, key: str, data: bytes) -> bool:
    created = bool(store.put_if_absent(key, data))
    if created:
        return True
    existing = store.get_object(key)
    if existing != data:
        raise ValueError(f"SEGMENTED_REPLAY_APPEND_ONLY_MISMATCH:{key}")
    return False


def _signed(value: Mapping[str, object], *, field: str) -> dict[str, object]:
    if field in value:
        raise ValueError("SEGMENTED_REPLAY_SIGNATURE_FIELD_RESERVED")
    result = dict(value)
    result[field] = canonical_sha256(value)
    return result


def _verify_signature(value: Mapping[str, object], *, field: str, label: str) -> str:
    signature = value.get(field)
    if not isinstance(signature, str) or len(signature) != 64:
        raise ValueError(f"{label}_SIGNATURE_MISSING")
    unsigned = {key: item for key, item in value.items() if key != field}
    if canonical_sha256(unsigned) != signature:
        raise ValueError(f"{label}_SIGNATURE_MISMATCH")
    return signature


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _write_gzip_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(canonical_json_bytes(value), compresslevel=9, mtime=0))


def _raw_object_keys(repository: R2FirstRepository) -> tuple[str, ...]:
    raw_prefix = f"{repository.namespace}/competition="
    index_prefix = f"{repository.namespace}/task-index/"
    return tuple(
        sorted(
            set(repository.store.iter_keys(raw_prefix))
            | set(repository.store.iter_keys(index_prefix))
        )
    )


def _task_versions(
    repository: R2FirstRepository,
    keys: Sequence[str],
) -> dict[str, TaskVersion]:
    output: dict[str, TaskVersion] = {}
    version_keys = (key for key in keys if key.endswith("/version.json"))
    for key, body in read_objects_bounded(repository.store, version_keys):
        if body is None:
            raise ValueError(f"CONTINUATION_TASK_VERSION_MISSING:{key}")
        try:
            version = TaskVersion.model_validate_json(body)
        except ValueError as error:
            raise ValueError(f"CONTINUATION_TASK_VERSION_INVALID:{key}") from error
        if version.version_key != key:
            raise ValueError(f"CONTINUATION_TASK_VERSION_KEY_MISMATCH:{key}")
        previous = output.get(version.task.task_id)
        if previous is not None and previous != version:
            raise ValueError("CONTINUATION_DUPLICATE_TASK_VERSION")
        output[version.task.task_id] = version
    return output


def _receipts_from_versions(
    versions: Mapping[str, TaskVersion],
    keys: Sequence[str],
) -> dict[str, HarvestReceipt]:
    by_key = {item.receipt.receipt_key: item.receipt for item in versions.values()}
    receipt_keys = {key for key in keys if key.endswith("/receipt.json")}
    unknown = receipt_keys - set(by_key)
    if unknown:
        raise ValueError(
            f"CONTINUATION_RECEIPT_WITHOUT_VERSION:{min(unknown)}"
        )
    return {
        receipt.task_id: receipt
        for key in sorted(receipt_keys)
        for receipt in (by_key[key],)
    }


def _attempt_from_body(
    key: str,
    body: bytes | None,
) -> tuple[HarvestTask, TaskAttemptEvent]:
    if body is None:
        raise ValueError(f"CONTINUATION_TASK_ATTEMPT_MISSING:{key}")
    try:
        event = TaskAttemptEvent.model_validate_json(body)
        task = HarvestTask.model_validate(
            {
                "task_id": event.task_id,
                "campaign_id": event.campaign_id,
                "competition": event.competition,
                "league_id": event.league_id,
                "season": event.season,
                "family": event.family,
                "endpoint": event.endpoint,
                "params": event.parameters,
                "page": event.page,
                "status": TaskStatus.PENDING,
                "temporal_class": event.temporal_class,
            }
        )
    except ValueError as error:
        raise ValueError(f"CONTINUATION_TASK_ATTEMPT_INVALID:{key}") from error
    if task.task_hash != event.task_hash:
        raise ValueError("CONTINUATION_TASK_ATTEMPT_HASH_MISMATCH")
    if task_attempt_key(task, event) != key:
        raise ValueError("CONTINUATION_TASK_ATTEMPT_KEY_MISMATCH")
    return task, event


def _attempt_at(
    repository: R2FirstRepository,
    key: str,
) -> tuple[HarvestTask, TaskAttemptEvent]:
    return _attempt_from_body(key, repository.store.get_object(key))


def _task_attempt_snapshot(
    repository: R2FirstRepository,
    versions: Mapping[str, TaskVersion],
    keys: Sequence[str],
) -> tuple[
    dict[str, HarvestTask],
    dict[str, tuple[TaskAttemptEvent, ...]],
    dict[str, tuple[str, ...]],
]:
    tasks = {task_id: version.task for task_id, version in versions.items()}
    grouped_keys: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        if "/attempts/attempt=" not in key or not key.endswith(".json"):
            continue
        match = _ATTEMPT_TASK_ID.search(key)
        if match is None:
            raise ValueError(f"CONTINUATION_TASK_ATTEMPT_KEY_INVALID:{key}")
        grouped_keys[match.group(1)].append(key)
    latest_events: dict[str, TaskAttemptEvent] = {}
    latest_keys = tuple(
        (task_id, max(task_keys))
        for task_id, task_keys in sorted(grouped_keys.items())
    )
    bodies = read_objects_bounded(
        repository.store,
        (key for _task_id, key in latest_keys),
    )
    for (task_id, expected_key), (key, body) in zip(
        latest_keys,
        bodies,
        strict=True,
    ):
        if key != expected_key:
            raise ValueError("CONTINUATION_TASK_ATTEMPT_READ_ORDER_MISMATCH")
        task, event = _attempt_from_body(key, body)
        if task.task_id != task_id:
            raise ValueError("CONTINUATION_TASK_ATTEMPT_KEY_TASK_MISMATCH")
        previous = tasks.get(task.task_id)
        if previous is not None and previous != task:
            raise ValueError("CONTINUATION_TASK_IDENTITY_CONFLICT")
        tasks[task.task_id] = task
        latest_events[task.task_id] = event
    attempts: dict[str, tuple[TaskAttemptEvent, ...]] = {
        task_id: ((latest_events[task_id],) if task_id in latest_events else ())
        for task_id in tasks
    }
    attempt_keys = {
        task_id: tuple(sorted(grouped_keys.get(task_id, ())))
        for task_id in tasks
    }
    return tasks, attempts, attempt_keys


def _attempt_events_for_keys(
    repository: R2FirstRepository,
    task: HarvestTask,
    keys: Sequence[str],
) -> list[TaskAttemptEvent]:
    events: list[TaskAttemptEvent] = []
    for key in keys:
        stored_task, event = _attempt_at(repository, key)
        if stored_task != task:
            raise ValueError("CONTINUATION_TASK_IDENTITY_CONFLICT")
        events.append(event)
    return sorted(
        events,
        key=lambda item: (
            item.attempt_number,
            item.event_index,
            item.recorded_at,
        ),
    )


def _append_receipt_success(
    repository: R2FirstRepository,
    *,
    task: HarvestTask,
    receipt: HarvestReceipt,
    events: list[TaskAttemptEvent],
    now: datetime,
) -> int:
    latest = events[-1] if events else None
    if latest is not None and latest.status in {
        TaskStatus.COMPLETE,
        TaskStatus.EMPTY_VALID,
    }:
        return 0
    if latest is None or latest.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        attempt_number = max(
            (item.attempt_number for item in events),
            default=0,
        ) + 1
        started_at = now
        event = repository.record_task_attempt(
            task=task,
            attempt_number=attempt_number,
            status=TaskStatus.PENDING,
            started_at=started_at,
            recorded_at=now,
            known_events=events,
        )
        events.append(event)
        latest_status = TaskStatus.PENDING
    else:
        attempt_number = latest.attempt_number
        started_at = latest.started_at
        latest_status = latest.status
    if latest_status is TaskStatus.PENDING:
        event = repository.record_task_attempt(
            task=task,
            attempt_number=attempt_number,
            status=TaskStatus.RUNNING,
            started_at=started_at,
            recorded_at=now,
            known_events=events,
        )
        events.append(event)
    event = repository.record_task_attempt(
        task=task,
        attempt_number=attempt_number,
        status=receipt.status,
        started_at=started_at,
        recorded_at=now,
        attempts=0,
        provider_calls=0,
        payload_hash=receipt.payload_sha256,
        r2_key=receipt.payload_key,
        rows_normalized=receipt.rows_normalized,
        rows_received=receipt.rows_normalized,
        known_events=events,
    )
    events.append(event)
    return 1


def _latest_task_state(
    *,
    versions: Mapping[str, object],
    receipts: Mapping[str, HarvestReceipt],
    attempts: Mapping[str, Sequence[TaskAttemptEvent]],
    payload_keys: set[str],
    now: datetime,
    stale_after: timedelta,
) -> dict[str, object]:
    task_ids = set(versions) | set(receipts) | set(attempts)
    statuses: dict[str, int] = defaultdict(int)
    running_stale = 0
    for task_id in sorted(task_ids):
        receipt = receipts.get(task_id)
        latest = attempts.get(task_id, ())[-1] if attempts.get(task_id) else None
        status = receipt.status if receipt is not None else (
            latest.status if latest is not None else TaskStatus.PENDING
        )
        statuses[status.value] += 1
        if (
            status is TaskStatus.RUNNING
            and latest is not None
            and _utc(latest.heartbeat_at, label="TASK_HEARTBEAT") <= now - stale_after
        ):
            running_stale += 1
    receipt_payload_keys = {item.payload_key for item in receipts.values()}
    missing_receipt_payloads = sum(
        item.payload_key not in payload_keys for item in receipts.values()
    )
    return {
        "tasks_total": len(task_ids),
        "tasks_complete": statuses.get(TaskStatus.COMPLETE.value, 0),
        "tasks_empty_valid": statuses.get(TaskStatus.EMPTY_VALID.value, 0),
        "tasks_retryable": statuses.get(TaskStatus.RETRYABLE.value, 0)
        + statuses.get(TaskStatus.STALE_RETRYABLE.value, 0),
        "tasks_failed": statuses.get(TaskStatus.FAILED.value, 0),
        "tasks_running_stale": running_stale,
        "tasks_pending": statuses.get(TaskStatus.PENDING.value, 0),
        "tasks_blocked": statuses.get(TaskStatus.BLOCKED_COVERAGE.value, 0)
        + statuses.get(TaskStatus.BLOCKED_PROVIDER.value, 0),
        "receipts": len(receipts),
        "payloads": len(payload_keys),
        "unique_payload_hashes": len({item.payload_sha256 for item in receipts.values()}),
        "orphans": len(payload_keys - receipt_payload_keys) + missing_receipt_payloads,
        "duplicate_receipts": max(0, len(receipts) - len(set(receipts))),
        "task_statuses": dict(sorted(statuses.items())),
    }


def audit_and_reconcile(
    repository: R2FirstRepository,
    ledger: DurableRuntimeLedger,
    *,
    continuation_id: str,
    continuation_of: str,
    run_purpose: str,
    code_revision: str,
    run_token: str,
    now: datetime,
    stale_heartbeat_minutes: int = STALE_HEARTBEAT_MINUTES,
) -> dict[str, object]:
    """Rebuild task state from R2 and reconcile only evidence-backed states."""

    _validate_id(continuation_id, label="CONTINUATION_ID")
    checked_at = _utc(now, label="CONTINUATION_AUDIT_TIME")
    stale_after = timedelta(minutes=stale_heartbeat_minutes)
    raw_keys_before = _raw_object_keys(repository)
    versions_before = _task_versions(repository, raw_keys_before)
    receipts_before = _receipts_from_versions(
        versions_before, raw_keys_before
    )
    tasks_before, attempts_before, attempt_keys_before = _task_attempt_snapshot(
        repository, versions_before, raw_keys_before
    )
    payload_keys_before = {
        key
        for key in raw_keys_before
        if "/payload-" in key and key.endswith(".json.gz")
    }
    state_before = _latest_task_state(
        versions=tasks_before,
        receipts=receipts_before,
        attempts=attempts_before,
        payload_keys=payload_keys_before,
        now=checked_at,
        stale_after=stale_after,
    )

    recovered_receipts = repository.resume_pending(
        known_versions=versions_before,
        known_keys=raw_keys_before,
    )
    if recovered_receipts:
        raw_keys = _raw_object_keys(repository)
        versions = _task_versions(repository, raw_keys)
        receipts = _receipts_from_versions(versions, raw_keys)
        tasks, attempts, attempt_keys = _task_attempt_snapshot(
            repository, versions, raw_keys
        )
    else:
        raw_keys = raw_keys_before
        versions = versions_before
        receipts = receipts_before
        tasks = tasks_before
        attempts = attempts_before
        attempt_keys = attempt_keys_before
    attempts_after = dict(attempts)
    tasks_reconciled = 0
    tasks_reset_pending = 0
    stale_recovered = 0
    for task_id, task in sorted(tasks.items()):
        latest_events = attempts.get(task_id, ())
        latest = latest_events[-1] if latest_events else None
        receipt = receipts.get(task_id)
        if receipt is not None:
            if latest is not None and latest.status in {
                TaskStatus.COMPLETE,
                TaskStatus.EMPTY_VALID,
            }:
                continue
            events = _attempt_events_for_keys(
                repository,
                task,
                attempt_keys.get(task_id, ()),
            )
            reconciled = _append_receipt_success(
                repository,
                task=task,
                receipt=receipt,
                events=events,
                now=checked_at,
            )
            tasks_reconciled += reconciled
            if reconciled:
                attempts_after[task_id] = (events[-1],)
            continue
        if latest is not None and latest.status is TaskStatus.RUNNING:
            if _utc(latest.heartbeat_at, label="TASK_HEARTBEAT") <= checked_at - stale_after:
                events = _attempt_events_for_keys(
                    repository,
                    task,
                    attempt_keys.get(task_id, ()),
                )
                latest = events[-1]
                event = repository.record_task_attempt(
                    task=task,
                    attempt_number=latest.attempt_number,
                    status=TaskStatus.STALE_RETRYABLE,
                    started_at=latest.started_at,
                    recorded_at=checked_at,
                    attempts=latest.attempts,
                    provider_calls=latest.provider_calls,
                    error=RuntimeError("RUNNER_HEARTBEAT_STALE"),
                    known_events=events,
                )
                events.append(event)
                attempts_after[task_id] = (event,)
                stale_recovered += 1
        elif latest is not None and latest.status is TaskStatus.FAILED:
            events = _attempt_events_for_keys(
                repository,
                task,
                attempt_keys.get(task_id, ()),
            )
            next_attempt = max(
                (item.attempt_number for item in events),
                default=0,
            ) + 1
            event = repository.record_task_attempt(
                task=task,
                attempt_number=next_attempt,
                status=TaskStatus.PENDING,
                started_at=checked_at,
                recorded_at=checked_at,
                known_events=events,
            )
            events.append(event)
            attempts_after[task_id] = (event,)
            tasks_reset_pending += 1

    payload_keys = {
        key
        for key in raw_keys
        if "/payload-" in key and key.endswith(".json.gz")
    }
    state_after = _latest_task_state(
        versions=tasks,
        receipts=receipts,
        attempts=attempts_after,
        payload_keys=payload_keys,
        now=checked_at,
        stale_after=stale_after,
    )
    lineage = {
        "schema_version": CONTINUATION_SCHEMA_VERSION,
        "continuation_id": continuation_id,
        "continuation_of": continuation_of,
        "run_purpose": run_purpose,
        "code_revision": code_revision,
        "run_token": run_token,
        "recorded_at": checked_at.isoformat(),
        "parent_clock_mutated": False,
        "parent_verdict_mutated": False,
        "provider_calls": 0,
    }
    result: dict[str, object] = {
        "schema_version": "historical-deep-continuation-audit-v1",
        **lineage,
        **state_after,
        "before": state_before,
        "after": state_after,
        "tasks_reconciled": tasks_reconciled,
        "tasks_reset_pending": tasks_reset_pending,
        "stale_tasks_recovered": stale_recovered,
        "write_ahead_receipts_recovered": len(set(receipts) - set(receipts_before)),
        "write_ahead_receipts_verified": len(recovered_receipts),
        "tasks_recalled": 0,
        "tasks_avoided": _integer(
            state_after["tasks_complete"], label="AUDIT_TASKS_COMPLETE"
        )
        + _integer(state_after["tasks_empty_valid"], label="AUDIT_TASKS_EMPTY"),
        "status": "CONTINUATION_R2_AUDIT_RECONCILED",
    }
    result["audit_hash"] = canonical_sha256(result)
    result["durable_key"] = ledger.put_json(
        "continuation/audit", result, recorded_at=checked_at
    )
    ledger.put_json("continuation/lineage", lineage, recorded_at=checked_at)
    return result


@dataclass(frozen=True, slots=True)
class InventoryObject:
    object_id: str
    receipt_id: str
    receipt_hash: str
    receipt_key: str
    payload_key: str
    payload_sha256: str
    stored_sha256: str
    logical_bytes: int
    stored_bytes: int
    competition: str
    season: int
    family: str
    task_id: str
    provider_calls: int
    rows_received: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _inventory_objects(ledger: DurableRuntimeLedger) -> list[InventoryObject]:
    payload_keys = set(ledger.raw_payload_keys())
    referenced: set[str] = set()
    objects: list[InventoryObject] = []
    task_ids: set[str] = set()
    receipt_keys: set[str] = set()
    for raw_receipt in ledger._raw_receipts():  # noqa: SLF001 - same package boundary
        try:
            receipt = HarvestReceipt.model_validate(raw_receipt)
        except ValueError as error:
            raise ValueError("REPLAY_INVENTORY_RECEIPT_INVALID") from error
        if receipt.task_id in task_ids or receipt.receipt_key in receipt_keys:
            raise ValueError("REPLAY_INVENTORY_DUPLICATE_RECEIPT")
        task_ids.add(receipt.task_id)
        receipt_keys.add(receipt.receipt_key)
        if receipt.payload_key not in payload_keys:
            raise ValueError(f"REPLAY_INVENTORY_PAYLOAD_MISSING:{receipt.payload_key}")
        referenced.add(receipt.payload_key)
        identity = {
            "receipt_key": receipt.receipt_key,
            "receipt_hash": receipt.receipt_hash,
            "payload_key": receipt.payload_key,
            "payload_sha256": receipt.payload_sha256,
        }
        objects.append(
            InventoryObject(
                object_id=canonical_sha256(identity),
                receipt_id=receipt.task_id,
                receipt_hash=receipt.receipt_hash,
                receipt_key=receipt.receipt_key,
                payload_key=receipt.payload_key,
                payload_sha256=receipt.payload_sha256,
                stored_sha256=receipt.stored_sha256,
                logical_bytes=receipt.payload_bytes,
                stored_bytes=receipt.stored_bytes,
                competition=receipt.competition,
                season=receipt.season,
                family=receipt.family,
                task_id=receipt.task_id,
                provider_calls=receipt.provider_calls,
                rows_received=receipt.rows_normalized,
            )
        )
    orphans = payload_keys - referenced
    if orphans:
        raise ValueError(f"REPLAY_INVENTORY_UNEXPLAINED_ORPHANS:{len(orphans)}")
    return sorted(
        objects,
        key=lambda item: (
            item.competition,
            item.season,
            item.family,
            item.payload_key,
            item.receipt_id,
        ),
    )


def build_replay_inventory(
    ledger: DurableRuntimeLedger,
    *,
    continuation_id: str,
    continuation_of: str,
    run_purpose: str,
    code_revision: str,
    run_token: str,
    now: datetime,
    max_objects: int = DEFAULT_MAX_OBJECTS,
    max_logical_bytes: int = DEFAULT_MAX_LOGICAL_BYTES,
    max_estimated_seconds: float = DEFAULT_MAX_ESTIMATED_SECONDS,
    estimated_seconds_per_object: float = DEFAULT_ESTIMATED_SECONDS_PER_OBJECT,
) -> dict[str, object]:
    """Produce and persist one immutable deterministic global manifest."""

    _validate_id(continuation_id, label="CONTINUATION_ID")
    if max_objects < 1 or max_objects > DEFAULT_MAX_OBJECTS:
        raise ValueError("REPLAY_SEGMENT_OBJECT_LIMIT_INVALID")
    if max_logical_bytes < 1 or max_logical_bytes > DEFAULT_MAX_LOGICAL_BYTES:
        raise ValueError("REPLAY_SEGMENT_LOGICAL_BYTE_LIMIT_INVALID")
    if not 0 < max_estimated_seconds <= DEFAULT_MAX_ESTIMATED_SECONDS:
        raise ValueError("REPLAY_SEGMENT_DURATION_LIMIT_INVALID")
    if estimated_seconds_per_object <= 0:
        raise ValueError("REPLAY_SEGMENT_ESTIMATE_INVALID")
    objects = _inventory_objects(ledger)
    by_partition: dict[tuple[str, int, str], list[InventoryObject]] = defaultdict(list)
    for item in objects:
        by_partition[(item.competition, item.season, item.family)].append(item)
    segments: list[dict[str, object]] = []
    ordinal = 0
    for partition, partition_objects in sorted(by_partition.items()):
        current: list[InventoryObject] = []
        current_bytes = 0
        current_seconds = 0.0

        def flush() -> None:
            nonlocal ordinal, current, current_bytes, current_seconds
            if not current:
                return
            ordinal += 1
            competition, season, family = partition
            segment_identity = {
                "competition": competition,
                "season": season,
                "family": family,
                "segment": len(
                    [
                        item
                        for item in segments
                        if item["competition"] == competition
                        and item["season"] == season
                        and item["family"] == family
                    ]
                )
                + 1,
                "object_ids": [item.object_id for item in current],
            }
            digest = canonical_sha256(segment_identity)[:16]
            segments.append(
                {
                    **segment_identity,
                    "segment_id": f"seg-{ordinal:06d}-{digest}",
                    "object_count": len(current),
                    "logical_bytes": current_bytes,
                    "estimated_seconds": round(current_seconds, 3),
                    "oversized_single_object": (
                        len(current) == 1
                        and (
                            current_bytes > max_logical_bytes
                            or current_seconds > max_estimated_seconds
                        )
                    ),
                }
            )
            current = []
            current_bytes = 0
            current_seconds = 0.0

        for item in partition_objects:
            would_exceed = current and (
                len(current) >= max_objects
                or current_bytes + item.logical_bytes > max_logical_bytes
                or current_seconds + estimated_seconds_per_object
                > max_estimated_seconds
            )
            if would_exceed:
                flush()
            current.append(item)
            current_bytes += item.logical_bytes
            current_seconds += estimated_seconds_per_object
            if (
                len(current) >= max_objects
                or current_bytes >= max_logical_bytes
                or current_seconds >= max_estimated_seconds
            ):
                flush()
        flush()
    unsigned: dict[str, object] = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "continuation_id": continuation_id,
        "continuation_of": continuation_of,
        "run_purpose": run_purpose,
        "code_revision": code_revision,
        "partition_key": ["competition", "season", "family", "segment"],
        "limits": {
            "objects": max_objects,
            "logical_bytes": max_logical_bytes,
            "estimated_seconds": max_estimated_seconds,
            "checkpoint_objects": CHECKPOINT_MAX_OBJECTS,
            "checkpoint_seconds": CHECKPOINT_MAX_SECONDS,
        },
        "objects_expected": len(objects),
        "logical_bytes": sum(item.logical_bytes for item in objects),
        "stored_bytes": sum(item.stored_bytes for item in objects),
        "segments_expected": len(segments),
        "objects": [item.as_dict() for item in objects],
        "segments": segments,
        "provider_calls": 0,
    }
    manifest = _signed(unsigned, field="manifest_sha256")
    digest = str(manifest["manifest_sha256"])
    key = (
        f"{DERIVED_NAMESPACE}/replay/inventories/"
        f"continuation={continuation_id}/inventory={digest}/manifest.json.gz"
    )
    compressed = gzip.compress(canonical_json_bytes(manifest), compresslevel=9, mtime=0)
    _put_immutable(ledger.store, key, compressed)
    recorded_at = _utc(now, label="REPLAY_INVENTORY_TIME")
    result = {
        **manifest,
        "run_token": run_token,
        "generated_at": recorded_at.isoformat(),
        "durable_key": key,
    }
    ledger.put_json("replay/inventory", result, recorded_at=recorded_at)
    return result


def validate_inventory(value: Mapping[str, object]) -> str:
    if value.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise ValueError("REPLAY_INVENTORY_SCHEMA_INVALID")
    unsigned = {
        key: item
        for key, item in value.items()
        if key not in {"durable_key", "run_token", "generated_at"}
    }
    return _verify_signature(unsigned, field="manifest_sha256", label="REPLAY_INVENTORY")


def _segment_definition(
    inventory: Mapping[str, object], segment_id: str
) -> Mapping[str, object]:
    matches = [
        _mapping(item, label="REPLAY_SEGMENT_DEFINITION")
        for item in _sequence(inventory.get("segments"), label="REPLAY_SEGMENTS")
        if _mapping(item, label="REPLAY_SEGMENT_DEFINITION").get("segment_id")
        == segment_id
    ]
    if len(matches) != 1:
        raise ValueError("REPLAY_SEGMENT_ID_NOT_UNIQUE")
    return matches[0]


def _inventory_object_index(
    inventory: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    output: dict[str, Mapping[str, object]] = {}
    for value in _sequence(inventory.get("objects"), label="REPLAY_OBJECTS"):
        item = _mapping(value, label="REPLAY_OBJECT")
        object_id = item.get("object_id")
        if not isinstance(object_id, str) or object_id in output:
            raise ValueError("REPLAY_OBJECT_ID_INVALID_OR_DUPLICATE")
        output[object_id] = item
    return output


def _receipt_parameters(receipt: Mapping[str, object]) -> Mapping[str, object]:
    value = receipt.get("parameters")
    return value if isinstance(value, Mapping) else {}


def _normalize_receipt_payload(
    receipt: HarvestReceipt,
    payload: object,
) -> list[dict[str, object]]:
    if receipt.endpoint == "/status":
        return []
    try:
        normalized = normalize_payload(
            payload,
            endpoint=receipt.endpoint,
            competition_id=receipt.league_id,
            season=receipt.season,
            task_id=receipt.task_id,
            source_payload_hash=receipt.payload_sha256,
            request_params=_receipt_parameters(receipt.model_dump(mode="json")),
            observed_at=receipt.received_at,
            ingested_at=receipt.completed_at,
        )
    except NormalizationError as error:
        raise ValueError(f"REPLAY_NORMALIZATION_FAILED:{receipt.task_id}") from error
    rows = [
        {"normalized_family": family, **dict(row)}
        for family, family_rows in normalized.items()
        for row in family_rows
    ]
    return sorted(rows, key=canonical_sha256)


def _memory_bytes() -> int:
    current, peak = tracemalloc.get_traced_memory()
    return max(current, peak)


def _checkpoint_category(
    continuation_id: str,
    inventory_hash: str,
    pass_id: int,
    segment_id: str,
) -> str:
    return (
        f"replay/checkpoints/{continuation_id}/{inventory_hash}/"
        f"pass-{pass_id}/{segment_id}"
    )


def _latest_checkpoint(
    ledger: DurableRuntimeLedger,
    *,
    category: str,
) -> Mapping[str, object] | None:
    values = ledger.values(category)
    if not values:
        return None
    latest = max(values, key=lambda item: str(item.get("recorded_at", "")))
    value = latest.get("value")
    return value if isinstance(value, Mapping) else None


def _chunk_value(
    *,
    continuation_id: str,
    inventory_hash: str,
    segment_id: str,
    pass_id: int,
    object_ids: Sequence[str],
    entries: Sequence[Mapping[str, object]],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": "historical-deep-replay-chunk-v2",
        "continuation_id": continuation_id,
        "inventory_sha256": inventory_hash,
        "segment_id": segment_id,
        "pass_id": pass_id,
        "object_ids": list(object_ids),
        "entries": [dict(item) for item in entries],
        "rows": [dict(item) for item in rows],
    }
    return _signed(unsigned, field="chunk_sha256")


def _write_chunk(ledger: DurableRuntimeLedger, value: Mapping[str, object]) -> str:
    digest = _verify_signature(value, field="chunk_sha256", label="REPLAY_CHUNK")
    key = (
        f"{DERIVED_NAMESPACE}/replay/segments/"
        f"continuation={value['continuation_id']}/"
        f"inventory={value['inventory_sha256']}/pass={value['pass_id']}/"
        f"segment={value['segment_id']}/chunks/chunk-{digest}.json.gz"
    )
    data = gzip.compress(canonical_json_bytes(value), compresslevel=9, mtime=0)
    _put_immutable(ledger.store, key, data)
    return key


def _load_chunk(ledger: DurableRuntimeLedger, key: str) -> Mapping[str, object]:
    body = ledger.store.get_object(key)
    if body is None:
        raise ValueError(f"REPLAY_CHUNK_MISSING:{key}")
    value = _mapping(_decode_json_bytes(body, label="REPLAY_CHUNK"), label="REPLAY_CHUNK")
    _verify_signature(value, field="chunk_sha256", label="REPLAY_CHUNK")
    return value


def _segment_artifact(
    ledger: DurableRuntimeLedger,
    *,
    inventory: Mapping[str, object],
    segment: Mapping[str, object],
    pass_id: int,
    chunk_keys: Sequence[str],
    duration_seconds: float,
    recovered_shutdowns: int,
    output_dir: Path,
) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    object_ids: list[str] = []
    for key in chunk_keys:
        chunk = _load_chunk(ledger, key)
        object_ids.extend(str(item) for item in _sequence(chunk.get("object_ids"), label="REPLAY_CHUNK_OBJECTS"))
        entries.extend(
            dict(_mapping(item, label="REPLAY_CHUNK_ENTRY"))
            for item in _sequence(chunk.get("entries"), label="REPLAY_CHUNK_ENTRIES")
        )
        rows.extend(
            dict(_mapping(item, label="REPLAY_CHUNK_ROW"))
            for item in _sequence(chunk.get("rows"), label="REPLAY_CHUNK_ROWS")
        )
    expected_ids = [
        str(item)
        for item in _sequence(segment.get("object_ids"), label="REPLAY_SEGMENT_OBJECTS")
    ]
    if object_ids != expected_ids:
        raise ValueError("REPLAY_SEGMENT_CHECKPOINT_CURSOR_MISMATCH")
    entries.sort(key=lambda item: (str(item.get("payload_key", "")), str(item.get("receipt_id", ""))))
    rows.sort(key=canonical_sha256)
    manifest_unsigned: dict[str, object] = {
        "schema_version": "historical-deep-replay-segment-manifest-v2",
        "continuation_id": inventory["continuation_id"],
        "continuation_of": inventory["continuation_of"],
        "run_purpose": inventory["run_purpose"],
        "inventory_sha256": inventory["manifest_sha256"],
        "segment_id": segment["segment_id"],
        "competition": segment["competition"],
        "season": segment["season"],
        "family": segment["family"],
        "segment": segment["segment"],
        "pass_id": pass_id,
        "object_ids": object_ids,
        "objects_verified": len(object_ids),
        "logical_bytes": segment["logical_bytes"],
        "entry_hash": canonical_sha256(entries),
        "row_count": len(rows),
        "rows_hash": canonical_sha256(rows),
        "chunk_keys": list(chunk_keys),
        "duration_seconds": round(duration_seconds, 3),
        "memory_bytes": _memory_bytes(),
        "errors": [],
        "provider_calls": 0,
        "recovered_shutdowns": recovered_shutdowns,
        "status": "SEGMENT_REPLAY_VERIFIED",
    }
    manifest = _signed(manifest_unsigned, field="manifest_sha256")
    result: dict[str, object] = {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "manifest": manifest,
        "entries": entries,
        "rows": rows,
    }
    _write_gzip_json(output_dir / "segment-result.json.gz", result)
    _write_json(output_dir / "segment-manifest.json", manifest)
    return result


def replay_segment(
    ledger: DurableRuntimeLedger,
    *,
    inventory: Mapping[str, object],
    segment_id: str,
    pass_id: int,
    output_dir: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Replay one independent segment with R2-backed 50-object checkpoints."""

    inventory_hash = validate_inventory(inventory)
    if pass_id not in {1, 2}:
        raise ValueError("REPLAY_PASS_ID_INVALID")
    segment = _segment_definition(inventory, segment_id)
    object_index = _inventory_object_index(inventory)
    object_ids = [
        str(item)
        for item in _sequence(segment.get("object_ids"), label="REPLAY_SEGMENT_OBJECTS")
    ]
    category = _checkpoint_category(
        str(inventory["continuation_id"]), inventory_hash, pass_id, segment_id
    )
    checkpoint = _latest_checkpoint(ledger, category=category)
    cursor = _integer(checkpoint.get("cursor", 0), label="REPLAY_CURSOR") if checkpoint else 0
    chunk_keys = (
        [str(item) for item in _sequence(checkpoint.get("chunk_keys", ()), label="REPLAY_CHUNK_KEYS")]
        if checkpoint
        else []
    )
    recovered_shutdowns = (
        _integer(checkpoint.get("recovered_shutdowns", 0), label="REPLAY_RECOVERED_SHUTDOWNS")
        if checkpoint
        else 0
    )
    if cursor > len(object_ids):
        raise ValueError("REPLAY_CHECKPOINT_CURSOR_OUT_OF_RANGE")
    recovered_ids: list[str] = []
    for key in chunk_keys:
        chunk = _load_chunk(ledger, key)
        recovered_ids.extend(str(item) for item in _sequence(chunk.get("object_ids"), label="REPLAY_CHUNK_OBJECTS"))
    if recovered_ids != object_ids[:cursor]:
        raise ValueError("REPLAY_CHECKPOINT_OBJECTS_MISMATCH")
    if checkpoint and checkpoint.get("status") == "COMPLETE" and cursor == len(object_ids):
        return _segment_artifact(
            ledger,
            inventory=inventory,
            segment=segment,
            pass_id=pass_id,
            chunk_keys=chunk_keys,
            duration_seconds=_number(
                checkpoint.get("duration_seconds", 0.0),
                label="REPLAY_DURATION_SECONDS",
            ),
            recovered_shutdowns=recovered_shutdowns,
            output_dir=output_dir,
        )

    shutdown_requested = False

    def request_shutdown(_signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    previous_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, request_shutdown)
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    started = monotonic()
    last_checkpoint = started
    current_object_ids: list[str] = []
    current_entries: list[dict[str, object]] = []
    current_rows: list[dict[str, object]] = []

    def flush(status: str, event: str | None = None) -> None:
        nonlocal cursor, last_checkpoint
        if current_object_ids:
            chunk = _chunk_value(
                continuation_id=str(inventory["continuation_id"]),
                inventory_hash=inventory_hash,
                segment_id=segment_id,
                pass_id=pass_id,
                object_ids=current_object_ids,
                entries=current_entries,
                rows=current_rows,
            )
            chunk_keys.append(_write_chunk(ledger, chunk))
            cursor += len(current_object_ids)
            current_object_ids.clear()
            current_entries.clear()
            current_rows.clear()
        checkpoint_value = {
            "schema_version": SEGMENT_CHECKPOINT_SCHEMA_VERSION,
            "continuation_id": inventory["continuation_id"],
            "inventory_sha256": inventory_hash,
            "segment_id": segment_id,
            "pass_id": pass_id,
            "status": status,
            "event": event,
            "cursor": cursor,
            "objects_verified": cursor,
            "object_hashes": object_ids[:cursor],
            "chunk_keys": list(chunk_keys),
            "normalized_rows": sum(
                len(_sequence(_load_chunk(ledger, key).get("rows"), label="REPLAY_CHUNK_ROWS"))
                for key in chunk_keys
            ),
            "errors": [],
            "memory_bytes": _memory_bytes(),
            "duration_seconds": round(monotonic() - started, 3),
            "recovered_shutdowns": recovered_shutdowns + int(event == "RUNNER_SHUTDOWN_RECOVERED"),
            "provider_calls": 0,
        }
        ledger.put_json(category, checkpoint_value, recorded_at=_utc(now(), label="REPLAY_CHECKPOINT_TIME"))
        last_checkpoint = monotonic()

    try:
        remaining_ids = object_ids[cursor:]
        remaining_items = [object_index[object_id] for object_id in remaining_ids]
        required_keys = tuple(
            dict.fromkeys(
                str(key)
                for item in remaining_items
                for key in (item["receipt_key"], item["payload_key"])
            )
        )
        object_bodies = dict(read_objects_bounded(ledger.store, required_keys))
        if shutdown_requested:
            flush("STALE_RETRYABLE", "RUNNER_SHUTDOWN_RECOVERED")
            raise RunnerShutdownRecovered("RUNNER_SHUTDOWN_RECOVERED")
        for object_id in object_ids[cursor:]:
            item = object_index[object_id]
            receipt_key = str(item["receipt_key"])
            payload_key = str(item["payload_key"])
            receipt_body = object_bodies.get(receipt_key)
            if receipt_body is None:
                raise ValueError(f"REPLAY_SEGMENT_RECEIPT_MISSING:{receipt_key}")
            try:
                receipt = HarvestReceipt.model_validate_json(receipt_body)
            except ValueError as error:
                raise ValueError(f"REPLAY_SEGMENT_RECEIPT_INVALID:{receipt_key}") from error
            if (
                receipt.receipt_hash != item["receipt_hash"]
                or receipt.payload_key != payload_key
                or receipt.task_id != item["task_id"]
            ):
                raise ValueError("REPLAY_SEGMENT_RECEIPT_INVENTORY_MISMATCH")
            payload_body = object_bodies.get(payload_key)
            if payload_body is None:
                raise ValueError(f"REPLAY_SEGMENT_PAYLOAD_MISSING:{payload_key}")
            if len(payload_body) != _integer(item["stored_bytes"], label="REPLAY_STORED_BYTES"):
                raise ValueError(f"REPLAY_SEGMENT_SIZE_MISMATCH:{payload_key}")
            if hashlib.sha256(payload_body).hexdigest() != item["stored_sha256"]:
                raise ValueError(f"REPLAY_SEGMENT_STORED_HASH_MISMATCH:{payload_key}")
            try:
                logical_body = gzip.decompress(payload_body)
                payload = json.loads(logical_body)
            except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"REPLAY_SEGMENT_PAYLOAD_INVALID:{payload_key}") from error
            if len(logical_body) != _integer(item["logical_bytes"], label="REPLAY_LOGICAL_BYTES"):
                raise ValueError(f"REPLAY_SEGMENT_LOGICAL_SIZE_MISMATCH:{payload_key}")
            verification = replay_stream_cache_only(
                [(receipt.model_dump(mode="json"), payload_body)],
                require_all_payloads_referenced=False,
                retain_projections=False,
            )
            if verification.hash_mismatches or verification.missing_payloads:
                raise ValueError("REPLAY_SEGMENT_VERIFICATION_FAILED")
            verified_entry = verification.entries[0].as_dict()
            current_entries.append(
                {
                    key: verified_entry[key]
                    for key in (
                        "receipt_id",
                        "payload_key",
                        "payload_sha256",
                        "projection_sha256",
                    )
                }
            )
            current_rows.extend(_normalize_receipt_payload(receipt, payload))
            current_object_ids.append(object_id)
            due = (
                len(current_object_ids) >= CHECKPOINT_MAX_OBJECTS
                or monotonic() - last_checkpoint >= CHECKPOINT_MAX_SECONDS
            )
            if due:
                flush("RUNNING")
            if shutdown_requested:
                flush("STALE_RETRYABLE", "RUNNER_SHUTDOWN_RECOVERED")
                raise RunnerShutdownRecovered("RUNNER_SHUTDOWN_RECOVERED")
        flush("COMPLETE")
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
    completed = _latest_checkpoint(ledger, category=category)
    if completed is None:
        raise ValueError("REPLAY_SEGMENT_COMPLETION_CHECKPOINT_MISSING")
    return _segment_artifact(
        ledger,
        inventory=inventory,
        segment=segment,
        pass_id=pass_id,
        chunk_keys=chunk_keys,
        duration_seconds=_number(
            completed.get("duration_seconds", monotonic() - started),
            label="REPLAY_DURATION_SECONDS",
        ),
        recovered_shutdowns=_integer(
            completed.get("recovered_shutdowns", recovered_shutdowns),
            label="REPLAY_RECOVERED_SHUTDOWNS",
        ),
        output_dir=output_dir,
    )


def load_segment_result(path: Path) -> Mapping[str, object]:
    value = _mapping(_decode_json_bytes(path.read_bytes(), label="REPLAY_SEGMENT_ARTIFACT"), label="REPLAY_SEGMENT_ARTIFACT")
    if value.get("schema_version") != SEGMENT_SCHEMA_VERSION:
        raise ValueError("REPLAY_SEGMENT_ARTIFACT_SCHEMA_INVALID")
    manifest = _mapping(value.get("manifest"), label="REPLAY_SEGMENT_MANIFEST")
    _verify_signature(manifest, field="manifest_sha256", label="REPLAY_SEGMENT_MANIFEST")
    rows = [dict(_mapping(item, label="REPLAY_SEGMENT_ROW")) for item in _sequence(value.get("rows"), label="REPLAY_SEGMENT_ROWS")]
    entries = [dict(_mapping(item, label="REPLAY_SEGMENT_ENTRY")) for item in _sequence(value.get("entries"), label="REPLAY_SEGMENT_ENTRIES")]
    if canonical_sha256(rows) != manifest.get("rows_hash") or len(rows) != manifest.get("row_count"):
        raise ValueError("REPLAY_SEGMENT_ROWS_MISMATCH")
    if canonical_sha256(entries) != manifest.get("entry_hash"):
        raise ValueError("REPLAY_SEGMENT_ENTRIES_MISMATCH")
    return value


def _staging_table_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, list[dict[str, object]]]:
    tables: dict[str, list[dict[str, object]]] = {name: [] for name in STAGING_TABLES}
    for row in rows:
        family = str(row.get("normalized_family", row.get("family", "")))
        if family not in tables:
            continue
        tables[family].append(dict(row))
    for values in tables.values():
        values.sort(key=canonical_sha256)
    return tables


def _metric(
    name: str,
    grain: str,
    value: int,
    *,
    source: str,
    lineage: str,
) -> dict[str, object]:
    return {
        "metric_name": name,
        "entity_grain": grain,
        "value": value,
        "source": source,
        "lineage": lineage,
    }


def _entity_metrics(
    *,
    inventory: Mapping[str, object],
    tables: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    lineage = str(inventory["continuation_id"])
    objects = [
        _mapping(item, label="REPLAY_METRIC_OBJECT")
        for item in _sequence(inventory.get("objects"), label="REPLAY_METRIC_OBJECTS")
    ]
    fixture_ids = {
        str(row.get("provider_fixture_id"))
        for row in tables["fixtures"]
        if row.get("provider_fixture_id") is not None
    }
    player_ids = {
        str(row.get("provider_player_id"))
        for table in ("players", "player_match_statistics", "player_season_statistics")
        for row in tables[table]
        if row.get("provider_player_id") is not None
    }
    values = (
        ("tasks", "provider-request task", len(objects), "R2 inventory"),
        ("calls", "provider HTTP call", sum(_integer(item.get("provider_calls", 0), label="METRIC_PROVIDER_CALLS") for item in objects), "immutable receipts"),
        ("payloads", "R2 raw payload object", len(objects), "R2 inventory"),
        ("receipts", "immutable receipt", len(objects), "R2 inventory"),
        ("rows_received", "receipt normalized row", sum(_integer(item.get("rows_received", 0), label="METRIC_ROWS_RECEIVED") for item in objects), "immutable receipts"),
        ("fixtures_unique", "fixture", len(fixture_ids), "staging fixtures"),
        ("players_unique", "player", len(player_ids), "staging player tables"),
        ("player_match_appearances", "player-fixture", len(tables["player_match_statistics"]), "staging player_match_statistics"),
        ("lineups", "team-fixture lineup", len(tables["lineups"]), "staging lineups"),
        ("formations", "team-fixture formation", len(tables["formations"]), "staging formations"),
        ("events", "fixture event", len(tables["events"]), "staging events"),
        ("team_statistics", "team-fixture statistic", len(tables["team_match_statistics"]), "staging team_match_statistics"),
        ("player_statistics", "player-fixture statistic", len(tables["player_match_statistics"]), "staging player_match_statistics"),
        ("injuries", "injury record", len(tables["injuries"]), "staging injuries"),
    )
    return [_metric(name, grain, value, source=source, lineage=lineage) for name, grain, value, source in values]


def reduce_segments(
    ledger: DurableRuntimeLedger,
    *,
    inventory: Mapping[str, object],
    segments_root: Path,
    pass_id: int,
    idempotent: bool,
    code_revision: str,
    run_token: str,
    now: datetime,
) -> dict[str, object]:
    """Verify every segment exactly once and write only isolated staging."""

    inventory_hash = validate_inventory(inventory)
    expected_segments = {
        str(_mapping(item, label="REPLAY_SEGMENT_DEFINITION")["segment_id"]): _mapping(item, label="REPLAY_SEGMENT_DEFINITION")
        for item in _sequence(inventory.get("segments"), label="REPLAY_SEGMENTS")
    }
    results: dict[str, Mapping[str, object]] = {}
    for path in sorted(segments_root.rglob("segment-result.json.gz")):
        result = load_segment_result(path)
        manifest = _mapping(result["manifest"], label="REPLAY_SEGMENT_MANIFEST")
        if manifest.get("inventory_sha256") != inventory_hash or manifest.get("pass_id") != pass_id:
            continue
        segment_id = str(manifest.get("segment_id", ""))
        if segment_id in results:
            raise ValueError(f"REPLAY_REDUCER_DUPLICATE_SEGMENT:{segment_id}")
        results[segment_id] = result
    missing = sorted(set(expected_segments) - set(results))
    extra = sorted(set(results) - set(expected_segments))
    if missing or extra:
        raise ValueError(f"REPLAY_REDUCER_SEGMENT_SET_MISMATCH:{len(missing)}:{len(extra)}")
    seen_objects: set[str] = set()
    entries: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    segment_content: list[dict[str, object]] = []
    interruptions = 0
    duration_seconds = 0.0
    for segment_id in sorted(results):
        result = results[segment_id]
        manifest = _mapping(result["manifest"], label="REPLAY_SEGMENT_MANIFEST")
        definition = expected_segments[segment_id]
        object_ids = [str(item) for item in _sequence(manifest.get("object_ids"), label="REPLAY_SEGMENT_OBJECTS")]
        expected_ids = [str(item) for item in _sequence(definition.get("object_ids"), label="REPLAY_SEGMENT_OBJECTS")]
        if object_ids != expected_ids:
            raise ValueError("REPLAY_REDUCER_SEGMENT_OBJECT_MISMATCH")
        duplicates = seen_objects.intersection(object_ids)
        if duplicates:
            raise ValueError(f"REPLAY_REDUCER_OBJECT_COUNTED_TWICE:{len(duplicates)}")
        seen_objects.update(object_ids)
        segment_entries = [dict(_mapping(item, label="REPLAY_SEGMENT_ENTRY")) for item in _sequence(result.get("entries"), label="REPLAY_SEGMENT_ENTRIES")]
        segment_rows = [dict(_mapping(item, label="REPLAY_SEGMENT_ROW")) for item in _sequence(result.get("rows"), label="REPLAY_SEGMENT_ROWS")]
        entries.extend(segment_entries)
        rows.extend(segment_rows)
        interruptions += _integer(manifest.get("recovered_shutdowns", 0), label="REPLAY_INTERRUPTION_COUNT")
        duration_seconds += _number(
            manifest.get("duration_seconds", 0.0),
            label="REPLAY_DURATION_SECONDS",
        )
        segment_content.append(
            {
                "segment_id": segment_id,
                "object_ids": object_ids,
                "entry_hash": manifest["entry_hash"],
                "rows_hash": manifest["rows_hash"],
            }
        )
    all_expected_object_ids = {
        str(item)
        for definition in expected_segments.values()
        for item in _sequence(definition.get("object_ids"), label="REPLAY_SEGMENT_OBJECTS")
    }
    if seen_objects != all_expected_object_ids:
        raise ValueError("REPLAY_REDUCER_OBJECT_COVERAGE_MISMATCH")
    entries.sort(key=lambda item: (str(item.get("payload_key", "")), str(item.get("receipt_id", ""))))
    rows.sort(key=canonical_sha256)
    tables = _staging_table_rows(rows)
    table_manifests: dict[str, object] = {}
    new_inserts = 0
    duplicates_avoided = 0
    for table, table_rows in tables.items():
        table_hash = canonical_sha256(table_rows)
        table_value = {
            "schema_version": "historical-deep-staging-table-v1",
            "continuation_id": inventory["continuation_id"],
            "inventory_sha256": inventory_hash,
            "table": table,
            "rows": table_rows,
            "row_count": len(table_rows),
            "table_sha256": table_hash,
        }
        key = (
            f"{DERIVED_NAMESPACE}/staging/continuation={inventory['continuation_id']}/"
            f"inventory={inventory_hash}/table={table}/part-{table_hash}.json.gz"
        )
        data = gzip.compress(canonical_json_bytes(table_value), compresslevel=9, mtime=0)
        created = _put_immutable(ledger.store, key, data)
        if created:
            new_inserts += len(table_rows)
        else:
            duplicates_avoided += len(table_rows)
        table_manifests[table] = {
            "row_count": len(table_rows),
            "table_sha256": table_hash,
            "staging_key": key,
            "created": created,
        }
    replay_content_hash = canonical_sha256(
        {
            "inventory_sha256": inventory_hash,
            "entries": entries,
            "rows": rows,
        }
    )
    global_hash = canonical_sha256(
        {
            "replay_content_hash": replay_content_hash,
            "tables": {
                name: {
                    key: value
                    for key, value in _mapping(manifest, label="STAGING_MANIFEST").items()
                    if key != "created"
                }
                for name, manifest in table_manifests.items()
            },
        }
    )
    source_entries = [
        {
            "receipt_id": item["receipt_id"],
            "payload_key": item["payload_key"],
            "payload_sha256": item["payload_sha256"],
        }
        for item in entries
    ]
    replay_entries = [
        {
            **item,
        }
        for item in entries
    ]
    source_hash = canonical_sha256(source_entries)
    replay_hash = canonical_sha256(replay_entries)
    projection_hash = canonical_sha256(rows)
    recorded_at = _utc(now, label="REPLAY_REDUCER_TIME")
    gates = [
        "CURRENT_R2_REPLAY_VERIFIED",
        "CURRENT_PROJECTION_RECONSTRUCTED",
    ]
    status = "REPLAY_REDUCED"
    if idempotent:
        first_passes = [
            _mapping(envelope.get("value"), label="REPLAY_REDUCER_VALUE")
            for envelope in ledger.values("replay/reducer")
            if _mapping(envelope.get("value"), label="REPLAY_REDUCER_VALUE").get("continuation_id")
            == inventory["continuation_id"]
            and _mapping(envelope.get("value"), label="REPLAY_REDUCER_VALUE").get("inventory_sha256")
            == inventory_hash
            and _mapping(envelope.get("value"), label="REPLAY_REDUCER_VALUE").get("pass_id") == 1
        ]
        if not first_passes:
            raise ValueError("REPLAY_IDEMPOTENCE_FIRST_PASS_MISSING")
        first = first_passes[-1]
        if first.get("replay_content_hash") != replay_content_hash:
            raise ValueError("REPLAY_IDEMPOTENCE_CONTENT_HASH_MISMATCH")
        if new_inserts != 0 or duplicates_avoided != len(rows):
            raise ValueError("REPLAY_IDEMPOTENCE_INSERT_CONTRACT_FAILED")
        gates.append("CURRENT_SECOND_PASS_IDEMPOTENT")
        status = "SECOND_PASS_IDEMPOTENT"
    projection = {
        "schema_version": "historical-deep-normalized-replay-v1",
        "continuation_id": inventory["continuation_id"],
        "continuation_of": inventory["continuation_of"],
        "run_purpose": inventory["run_purpose"],
        "code_revision": code_revision,
        "run_token": run_token,
        "rows": rows,
        "row_count": len(rows),
        "normalization_errors": [],
        "projection_hash": projection_hash,
        "provider_calls": 0,
        "staging_tables": table_manifests,
    }
    replay = {
        "schema_version": "historical-deep-segmented-replay-proof-v1",
        "status": "CACHE_ONLY_REPLAY_VERIFIED",
        "continuation_id": inventory["continuation_id"],
        "continuation_of": inventory["continuation_of"],
        "run_purpose": inventory["run_purpose"],
        "code_revision": code_revision,
        "run_token": run_token,
        "payloads_replayed": len(entries),
        "receipts_verified": len(entries),
        "provider_calls": 0,
        "provider_credits": 0,
        "hash_mismatches": 0,
        "missing_payloads": 0,
        "extra_payloads": 0,
        "source_hash": source_hash,
        "replay_hash": replay_hash,
        "expected_replay_hash": None,
        "hash_identical": True,
        "entries": entries,
        "normalized_rows": len(rows),
        "normalization_errors": [],
        "normalized_projection_hash": projection_hash,
        "inventory_sha256": inventory_hash,
        "replay_content_hash": replay_content_hash,
        "gates": gates,
    }
    if not idempotent:
        projection["durable_key"] = ledger.put_json(
            "replay/projection", projection, recorded_at=recorded_at
        )
        replay["durable_key"] = ledger.put_json("replay", replay, recorded_at=recorded_at)
    metrics = _entity_metrics(inventory=inventory, tables=tables)
    report: dict[str, object] = {
        "schema_version": REDUCER_SCHEMA_VERSION,
        "status": status,
        "continuation_id": inventory["continuation_id"],
        "continuation_of": inventory["continuation_of"],
        "run_purpose": inventory["run_purpose"],
        "code_revision": code_revision,
        "run_token": run_token,
        "inventory_sha256": inventory_hash,
        "pass_id": pass_id,
        "segments": len(results),
        "objects": len(seen_objects),
        "logical_bytes": inventory["logical_bytes"],
        "stored_bytes": inventory["stored_bytes"],
        "volume_definitions": {
            "stored_bytes": "physical gzip bytes stored in R2 receipts",
            "logical_bytes": "canonical uncompressed provider payload bytes",
        },
        "duration_seconds": round(duration_seconds, 3),
        "interruptions": interruptions,
        "resumptions": interruptions,
        "missing_segments": 0,
        "duplicate_objects": 0,
        "hash_mismatches": 0,
        "normalization_errors": 0,
        "provider_calls": 0,
        "rows": len(rows),
        "new_inserts": new_inserts,
        "duplicates_avoided": duplicates_avoided,
        "table_manifests": table_manifests,
        "source_hash": source_hash,
        "replay_hash": replay_hash,
        "projection_hash": projection_hash,
        "replay_content_hash": replay_content_hash,
        "global_hash": global_hash,
        "segment_content": segment_content,
        "gates": gates,
        "metrics": metrics,
        "staging_reconstructible_from_r2": True,
    }
    category = "replay/idempotence" if idempotent else "replay/reducer"
    report["durable_key"] = ledger.put_json(category, report, recorded_at=recorded_at)
    return report


__all__ = [
    "CHECKPOINT_MAX_OBJECTS",
    "CHECKPOINT_MAX_SECONDS",
    "DEFAULT_MAX_ESTIMATED_SECONDS",
    "DEFAULT_MAX_LOGICAL_BYTES",
    "DEFAULT_MAX_OBJECTS",
    "RunnerShutdownRecovered",
    "STAGING_TABLES",
    "audit_and_reconcile",
    "build_replay_inventory",
    "load_segment_result",
    "reduce_segments",
    "replay_segment",
    "validate_inventory",
]
