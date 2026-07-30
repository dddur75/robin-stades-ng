"""Bounded, deterministic collection for the historical-deep campaign.

The collector deliberately depends on two very small structural interfaces:

* a provider exposing ``get(endpoint, params=...)``;
* an optional append-only repository exposing ``contains``/``receipt_for`` and
  ``capture``.

This keeps the collection logic testable without network or object storage,
while still making the R2 receipt the idempotency boundary in production.
"""

from __future__ import annotations

import gzip
import inspect
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, TypedDict, cast

from .contracts import TaskStatus
from .normalization import (
    NORMALIZER_VERSION,
    SUPPORTED_FAMILIES,
    NormalizationError,
    canonical_json_bytes,
    canonical_sha256,
    classify_temporal,
    detect_integrated_families,
    normalize_family,
)
from .provider import (
    CircuitOpenError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderStatusError,
    ProviderTransportError,
)
from .quota import QuotaExhaustedError, QuotaStatusExpiredError

CAMPAIGN_ID = "historical-deep-data-harvest-v1"
COLLECTOR_VERSION = "historical-deep-collector-v1"
BUNDLE_CANDIDATE_SIZES = (20, 10, 5, 1)
BUNDLE_FAMILIES = (
    "fixtures",
    "events",
    "lineups",
    "lineup_players",
    "formations",
    "team_match_statistics",
    "player_match_statistics",
    "referees",
    "venues",
    "teams",
)
_FIXTURE_CENSUS_FAMILIES = frozenset((*BUNDLE_FAMILIES, "rounds"))
FALLBACK_FAMILIES = ("events", "lineups", "statistics", "players")
DEFAULT_REQUESTED_FAMILIES = tuple(sorted(SUPPORTED_FAMILIES))

_FALLBACK_ENDPOINTS: dict[str, str] = {
    "events": "/fixtures/events",
    "lineups": "/fixtures/lineups",
    "statistics": "/fixtures/statistics",
    "players": "/fixtures/players",
}
_FALLBACK_NORMALIZED_FAMILIES: dict[str, tuple[str, ...]] = {
    "events": ("events",),
    "lineups": ("lineups", "lineup_players", "formations"),
    "statistics": ("team_match_statistics",),
    "players": ("player_match_statistics",),
}
_FALLBACK_DETECTION_FAMILY: dict[str, str] = {
    "events": "events",
    "lineups": "lineups",
    "statistics": "team_match_statistics",
    "players": "player_match_statistics",
}
_CONTRACT_FAMILY_ALIASES = {
    "coverage": "fixtures",
    "fixtures_sample": "fixtures",
    "fixture_bundle": "fixtures",
    "statistics": "team_match_statistics",
    "sidelined": "sidelined_periods",
}
_TEMPORAL_FAMILY_ALIASES = {
    "coverage": "fixtures",
    "fixtures_sample": "fixtures",
    "fixture_bundle": "fixtures",
    "statistics": "team_match_statistics",
    "sidelined_periods": "sidelined",
}

_COVERAGE_PATHS: dict[str, tuple[str, ...] | None] = {
    "fixtures": ("fixtures",),
    "events": ("fixtures", "events"),
    "lineups": ("fixtures", "lineups"),
    "lineup_players": ("fixtures", "lineups"),
    "formations": ("fixtures", "lineups"),
    "team_match_statistics": ("fixtures", "statistics_fixtures"),
    "player_match_statistics": ("fixtures", "statistics_players"),
    "referees": ("fixtures",),
    "venues": ("fixtures",),
    "teams": ("fixtures",),
    "standings": ("standings",),
    "rounds": ("fixtures",),
    "players": ("players",),
    "player_season_statistics": ("players",),
    "injuries": ("injuries",),
    "suspensions": ("injuries",),
    "sidelined": None,
    "coaches": None,
}


class DeepProvider(Protocol):
    """Minimal provider surface used by the campaign collector."""

    def get(
        self,
        endpoint: str,
        params: Mapping[str, object] | None = None,
    ) -> object: ...


class ReceiptRepository(Protocol):
    """Structural subset of the append-only repository used by collection."""

    def contains(self, task: object) -> bool: ...

    def receipt_for(self, task: object) -> object | None: ...

    def capture(self, **kwargs: object) -> object: ...


class _NormalizationArgs(TypedDict):
    endpoint: str
    competition_id: int | None
    season: int
    task_id: str
    source_payload_hash: str
    observed_at: datetime
    ingested_at: datetime
    request_params: Mapping[str, object]
    fixture_id: int | None


@dataclass(frozen=True, slots=True)
class CollectionTask:
    """Portable fallback task when the foundation contract is not imported."""

    task_id: str
    campaign_id: str
    phase: str
    competition: str
    season: int | None
    family: str
    endpoint: str
    params: dict[str, object]
    status: str = "PENDING"


@dataclass(frozen=True, slots=True)
class CollectedResponse:
    """One provider response plus the deterministic evidence needed downstream."""

    task_id: str
    task: object
    endpoint: str
    params: dict[str, object]
    payload: object | None
    records: tuple[Mapping[str, Any], ...]
    paging_current: int
    paging_total: int
    errors: tuple[object, ...]
    http_status: int | None
    requested_at: datetime
    received_at: datetime
    payload_sha256: str | None
    receipt: object | None
    reused: bool

    def as_dict(self, *, include_payload: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "task_id": self.task_id,
            "endpoint": self.endpoint,
            "params": dict(self.params),
            "record_count": len(self.records),
            "paging_current": self.paging_current,
            "paging_total": self.paging_total,
            "errors": list(self.errors),
            "http_status": self.http_status,
            "requested_at": self.requested_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "payload_sha256": self.payload_sha256,
            "receipt": _json_value(self.receipt),
            "reused": self.reused,
        }
        if include_payload:
            result["payload"] = _json_value(self.payload)
        return result


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_value(model_dump(mode="json"))
    return repr(value)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _positive_int(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        (str, bytes, bytearray, int, float),
    ):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _deep_size(value: object, seen: set[int] | None = None) -> int:
    visited = seen if seen is not None else set()
    identity = id(value)
    if identity in visited:
        return 0
    visited.add(identity)
    size = sys.getsizeof(value)
    if isinstance(value, Mapping):
        return size + sum(
            _deep_size(key, visited) + _deep_size(item, visited) for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return size + sum(_deep_size(item, visited) for item in value)
    return size


def _error_items(value: object) -> tuple[object, ...]:
    if value is None or value == {} or value == [] or value == "":
        return ()
    if isinstance(value, Mapping):
        return tuple(
            {"field": str(key), "message": _json_value(item)}
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_json_value(item) for item in value)
    return (_json_value(value),)


def _provider_id(record: Mapping[str, Any]) -> int | str | None:
    fixture = _mapping(record.get("fixture"))
    value = fixture.get("id", record.get("id"))
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        return value
    return None


def make_task_id(
    *,
    campaign_id: str,
    phase: str,
    competition: int | str,
    season: int | None,
    family: str,
    endpoint: str,
    params: Mapping[str, object],
    identity: Mapping[str, object] | None = None,
) -> str:
    """Return a stable task id independent of mapping or input ordering."""

    material = {
        "campaign_id": campaign_id,
        "phase": phase,
        "competition": str(competition),
        "season": season,
        "family": family,
        "endpoint": endpoint,
        "params": dict(params),
        "identity": dict(identity or {}),
    }
    return canonical_sha256(material)


def _competition_parts(
    competition: object,
) -> tuple[int | str, str]:
    if isinstance(competition, Mapping):
        provider_id = competition.get(
            "provider_league_id",
            competition.get("league_id", competition.get("id")),
        )
        if not isinstance(provider_id, (int, str)) or isinstance(provider_id, bool):
            raise ValueError("competition requires provider_league_id")
        canonical = competition.get("canonical_key", f"api-football:{provider_id}")
        return provider_id, str(canonical)
    provider_id = getattr(competition, "provider_league_id", None)
    canonical = getattr(competition, "canonical_key", None)
    if isinstance(provider_id, int) and not isinstance(provider_id, bool):
        return provider_id, str(canonical or f"api-football:{provider_id}")
    if isinstance(competition, bool) or not isinstance(competition, (int, str)):
        raise TypeError("competition must be a mapping, integer, or string")
    if isinstance(competition, str) and ":" in competition:
        tail = competition.rsplit(":", 1)[1]
        provider_id = int(tail) if tail.isdigit() else tail
        return provider_id, competition
    return competition, f"api-football:{competition}"


def _decoded_payload(value: object) -> object:
    if isinstance(value, bytes):
        raw = gzip.decompress(value) if value[:2] == b"\x1f\x8b" else value
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("repository payload must contain JSON") from exc
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _extract_envelope(
    result: object,
) -> tuple[
    object,
    tuple[Mapping[str, Any], ...],
    int,
    int,
    tuple[object, ...],
    int | None,
]:
    payload: object
    raw_payload = getattr(result, "raw_payload", None)
    payload_attr = getattr(result, "payload", None)
    if raw_payload is not None:
        payload = raw_payload
    elif payload_attr is not None:
        payload = payload_attr
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        records_attr = getattr(result, "records", ())
        payload = {"response": list(_sequence(records_attr))}

    payload = _decoded_payload(payload)
    mapped_payload = _mapping(payload)
    raw_records: object = mapped_payload.get("response")
    if raw_records is None:
        raw_records = getattr(result, "records", ())
    records = tuple(dict(item) for item in _sequence(raw_records) if isinstance(item, Mapping))

    paging = _mapping(mapped_payload.get("paging"))
    current = _positive_int(
        getattr(result, "paging_current", paging.get("current", 1)),
        1,
    )
    total = _positive_int(
        getattr(result, "paging_total", paging.get("total", current)),
        current,
    )
    errors = _error_items(getattr(result, "errors", mapped_payload.get("errors")))
    status_value = getattr(
        result,
        "http_status",
        getattr(result, "status_code", mapped_payload.get("status")),
    )
    http_status = (
        int(status_value)
        if isinstance(status_value, (int, str))
        and not isinstance(status_value, bool)
        and str(status_value).isdigit()
        else None
    )
    return payload, records, current, total, errors, http_status


def _receipt_value(receipt: object, field: str) -> object | None:
    if isinstance(receipt, Mapping):
        return receipt.get(field)
    return getattr(receipt, field, None)


def _receipt_datetime(receipt: object, field: str, default: datetime) -> datetime:
    value = _receipt_value(receipt, field)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return default
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(UTC)
    return default


def _failure_task_status(error: Exception) -> TaskStatus:
    if isinstance(
        error,
        (
            ProviderAuthenticationError,
            ProviderStatusError,
        ),
    ):
        return TaskStatus.BLOCKED_PROVIDER
    if isinstance(
        error,
        (
            ProviderRateLimitError,
            ProviderTransportError,
            CircuitOpenError,
            QuotaExhaustedError,
            QuotaStatusExpiredError,
        ),
    ):
        return TaskStatus.RETRYABLE
    if isinstance(error, ProviderResponseError):
        return TaskStatus.FAILED
    return TaskStatus.FAILED


def _success_task_status(payload: object, receipt: object | None) -> TaskStatus:
    receipt_status = _receipt_value(receipt, "status")
    if receipt_status is not None:
        try:
            status = TaskStatus(str(receipt_status))
        except ValueError:
            status = TaskStatus.COMPLETE
        if status in {TaskStatus.COMPLETE, TaskStatus.EMPTY_VALID}:
            return status
    if isinstance(payload, list) and not payload:
        return TaskStatus.EMPTY_VALID
    if isinstance(payload, Mapping):
        response = payload.get("response")
        if isinstance(response, list) and not response:
            return TaskStatus.EMPTY_VALID
    return TaskStatus.COMPLETE


def _coverage_at(coverage: Mapping[str, Any], path: tuple[str, ...] | None) -> bool | None:
    if path is None:
        return None
    value: object = coverage
    for part in path:
        mapped = _mapping(value)
        if part not in mapped:
            return None
        value = mapped[part]
    if isinstance(value, bool):
        return value
    if path == ("fixtures",) and isinstance(value, Mapping):
        return True
    return None


def _coverage_for_season(
    league_records: Sequence[Mapping[str, Any]],
    season: int,
) -> Mapping[str, Any]:
    for league_record in league_records:
        for season_record in _sequence(league_record.get("seasons")):
            mapped = _mapping(season_record)
            if mapped.get("year") == season:
                return _mapping(mapped.get("coverage"))
    return {}


def _actual_families(records: Sequence[Mapping[str, Any]]) -> set[str]:
    actual: set[str] = set()
    if records:
        actual.add("fixtures")
    for record in records:
        actual.update(detect_integrated_families(record))
    if "lineups" in actual:
        actual.update(("lineup_players", "formations"))
    return actual


def _matrix_state(advertised: bool | None, actual: bool) -> str:
    if advertised is True and actual:
        return "ADVERTISED_AND_OBSERVED"
    if advertised is True:
        return "ADVERTISED_NOT_OBSERVED"
    if advertised is False and actual:
        return "OBSERVED_BUT_NOT_ADVERTISED"
    if advertised is False:
        return "NOT_ADVERTISED_NOT_OBSERVED"
    if actual:
        return "OBSERVED_WITHOUT_FLAG"
    return "UNKNOWN"


class HistoricalDeepCollector:
    """Collect raw historical evidence with bounded calls and stable tasks."""

    def __init__(
        self,
        provider: DeepProvider,
        repository: ReceiptRepository | object | None = None,
        *,
        campaign_id: str = CAMPAIGN_ID,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.perf_counter,
        source_commit: str = "UNSPECIFIED",
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.campaign_id = campaign_id
        self.clock = clock
        self.monotonic = monotonic
        self.source_commit = source_commit
        self._completed: dict[str, CollectedResponse] = {}

    def _make_task(
        self,
        *,
        phase: str,
        competition: int | str,
        season: int | None,
        family: str,
        endpoint: str,
        params: Mapping[str, object],
        identity: Mapping[str, object] | None,
    ) -> object:
        try:
            from .contracts import CompetitionSpec, HarvestTask
        except ImportError:
            task_id = make_task_id(
                campaign_id=self.campaign_id,
                phase=phase,
                competition=competition,
                season=season,
                family=family,
                endpoint=endpoint,
                params=params,
                identity=identity,
            )
            return CollectionTask(
                task_id=task_id,
                campaign_id=self.campaign_id,
                phase=phase,
                competition=str(competition),
                season=season,
                family=family,
                endpoint=endpoint,
                params=dict(params),
            )
        if season is None:
            raise ValueError("foundation HarvestTask requires a season")
        league_id, canonical = _competition_parts(competition)
        if not isinstance(league_id, int):
            raise ValueError("foundation HarvestTask requires an integer league id")
        contract_family = _CONTRACT_FAMILY_ALIASES.get(family, family)
        temporal_family = _TEMPORAL_FAMILY_ALIASES.get(contract_family, contract_family)
        competition_spec = CompetitionSpec(
            canonical_key=canonical,
            name=canonical,
            provider_league_id=league_id,
        )
        return HarvestTask.create(
            campaign_id=self.campaign_id,
            competition=competition_spec,
            season=season,
            family=contract_family,
            endpoint=endpoint,
            temporal_class=classify_temporal(temporal_family),
            params=cast(Any, dict(params)),
            page=_positive_int(params.get("page"), 1),
        )

    @staticmethod
    def _task_id(task: object) -> str:
        if isinstance(task, Mapping):
            return str(task["task_id"])
        return str(getattr(task, "task_id"))

    def _repository_receipt(self, task: object) -> object | None:
        if self.repository is None:
            return None
        for name in ("receipt_for", "load_receipt", "get_receipt"):
            method = getattr(self.repository, name, None)
            if callable(method):
                try:
                    receipt: object = method(task)
                except (KeyError, TypeError):
                    receipt = method(self._task_id(task))
                if receipt is not None:
                    return receipt
        contains = getattr(self.repository, "contains", None)
        if callable(contains):
            try:
                exists = bool(contains(task))
            except (KeyError, TypeError):
                exists = bool(contains(self._task_id(task)))
            if exists:
                return {"task_id": self._task_id(task), "status": "COMPLETE"}
        return None

    def _repository_payload(self, task: object, receipt: object) -> object | None:
        if self.repository is None:
            return None
        for name in ("payload_for", "load_payload", "get_payload"):
            method = getattr(self.repository, name, None)
            if not callable(method):
                continue
            for reference in (task, receipt, self._task_id(task)):
                try:
                    payload: object = method(reference)
                except (KeyError, TypeError, ValueError):
                    continue
                if payload is not None:
                    return payload
        return None

    def _next_task_attempt_number(self, task: object) -> int:
        if self.repository is None:
            return 1
        method = getattr(self.repository, "next_task_attempt_number", None)
        if not callable(method):
            return 1
        value = method(task)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("TASK_ATTEMPT_NUMBER_INVALID")
        return value

    def _record_task_state(
        self,
        *,
        task: object,
        attempt_number: int,
        status: TaskStatus,
        started_at: datetime,
        recorded_at: datetime,
        attempts: int = 0,
        provider_calls: int = 0,
        error: Exception | None = None,
        payload_hash: str | None = None,
        r2_key: str | None = None,
        rows_normalized: int | None = None,
        rows_received: int | None = None,
    ) -> None:
        if self.repository is None:
            return
        method = getattr(self.repository, "record_task_attempt", None)
        if not callable(method):
            return
        method(
            task=task,
            attempt_number=attempt_number,
            status=status,
            started_at=started_at,
            recorded_at=recorded_at,
            heartbeat_at=recorded_at,
            completed_at=(
                recorded_at
                if status
                in {
                    TaskStatus.COMPLETE,
                    TaskStatus.EMPTY_VALID,
                    TaskStatus.RETRYABLE,
                    TaskStatus.BLOCKED_COVERAGE,
                    TaskStatus.BLOCKED_PROVIDER,
                    TaskStatus.FAILED,
                }
                else None
            ),
            attempts=attempts,
            provider_calls=provider_calls,
            error=error,
            payload_hash=payload_hash,
            r2_key=r2_key,
            rows_normalized=rows_normalized,
            rows_received=rows_received,
        )

    def _mission_used(self) -> int | None:
        quota = getattr(self.provider, "quota", None)
        value = getattr(quota, "mission_used", None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def _capture(
        self,
        *,
        task: object,
        payload: object,
        requested_at: datetime,
        received_at: datetime,
        http_status: int | None,
        sanitized_quota_headers: Mapping[str, object] | None,
        attempts: int,
    ) -> object | None:
        if self.repository is None:
            return None
        capture = getattr(self.repository, "capture", None)
        if not callable(capture):
            raise TypeError("repository must expose capture(...)")
        kwargs: dict[str, object] = {
            "task": task,
            "payload": payload,
            "requested_at": requested_at,
            "received_at": received_at,
            "http_status": http_status if http_status is not None else 200,
            "sanitized_quota_headers": dict(sanitized_quota_headers or {}),
            "attempts": attempts,
            "provider_calls": attempts,
            "collector_version": COLLECTOR_VERSION,
            "source_commit": self.source_commit,
            "started_at": requested_at,
            "completed_at": received_at,
            "heartbeat_at": received_at,
        }
        try:
            stored: object = capture(**kwargs)
        except TypeError:
            signature = inspect.signature(capture)
            accepted = {key: value for key, value in kwargs.items() if key in signature.parameters}
            stored = capture(**accepted)
        return getattr(stored, "receipt", stored)

    def _collect(
        self,
        *,
        phase: str,
        competition: int | str,
        season: int | None,
        family: str,
        endpoint: str,
        params: Mapping[str, object],
        identity: Mapping[str, object] | None = None,
    ) -> CollectedResponse:
        task = self._make_task(
            phase=phase,
            competition=competition,
            season=season,
            family=family,
            endpoint=endpoint,
            params=params,
            identity=identity,
        )
        task_id = self._task_id(task)
        if task_id in self._completed:
            previous = self._completed[task_id]
            return CollectedResponse(
                **{
                    **asdict(previous),
                    "task": previous.task,
                    "receipt": previous.receipt,
                    "reused": True,
                }
            )

        receipt = self._repository_receipt(task)
        if receipt is not None:
            now = self.clock()
            requested_at = _receipt_datetime(receipt, "requested_at", now)
            received_at = _receipt_datetime(receipt, "received_at", requested_at)
            payload = self._repository_payload(task, receipt)
            if payload is None:
                records: tuple[Mapping[str, Any], ...] = ()
                current = 1
                total = 1
                errors: tuple[object, ...] = ()
                http_status = None
                payload_hash = None
            else:
                (
                    payload,
                    records,
                    current,
                    total,
                    errors,
                    http_status,
                ) = _extract_envelope(payload)
                payload_hash = canonical_sha256(payload)
                expected_hash = _receipt_value(receipt, "payload_sha256")
                if (
                    isinstance(expected_hash, str)
                    and expected_hash
                    and expected_hash != payload_hash
                ):
                    raise ValueError(f"REPOSITORY_PAYLOAD_HASH_MISMATCH:{task_id}")
            response = CollectedResponse(
                task_id=task_id,
                task=task,
                endpoint=endpoint,
                params=dict(params),
                payload=payload,
                records=records,
                paging_current=current,
                paging_total=total,
                errors=errors,
                http_status=http_status,
                requested_at=requested_at,
                received_at=received_at,
                payload_sha256=payload_hash,
                receipt=receipt,
                reused=True,
            )
            self._completed[task_id] = response
            return response

        started_at = self.clock()
        attempt_number = self._next_task_attempt_number(task)
        self._record_task_state(
            task=task,
            attempt_number=attempt_number,
            status=TaskStatus.PENDING,
            started_at=started_at,
            recorded_at=started_at,
        )
        running_at = self.clock()
        self._record_task_state(
            task=task,
            attempt_number=attempt_number,
            status=TaskStatus.RUNNING,
            started_at=started_at,
            recorded_at=running_at,
        )

        mission_used_before = self._mission_used()
        attempts = 0
        provider_calls = 0
        try:
            requested_at = self.clock()
            result = self.provider.get(endpoint, params=dict(params))
            received_at = self.clock()
            provider_requested_at = getattr(result, "requested_at", None)
            provider_received_at = getattr(result, "received_at", None)
            if isinstance(provider_requested_at, datetime):
                requested_at = provider_requested_at
            if isinstance(provider_received_at, datetime):
                received_at = provider_received_at
            attempts = min(
                4,
                _positive_int(getattr(result, "attempts", 1), 1),
            )
            mission_used_after = self._mission_used()
            mission_delta = (
                mission_used_after - mission_used_before
                if mission_used_before is not None
                and mission_used_after is not None
                and mission_used_after >= mission_used_before
                else 0
            )
            provider_calls = min(4, max(attempts, mission_delta))
            (
                payload,
                records,
                current,
                total,
                errors,
                http_status,
            ) = _extract_envelope(result)
            headers_value = getattr(result, "headers", {})
            sanitized_headers = (
                headers_value if isinstance(headers_value, Mapping) else {}
            )
            payload_hash = canonical_sha256(payload)
            receipt = self._capture(
                task=task,
                payload=payload,
                requested_at=requested_at,
                received_at=received_at,
                http_status=http_status,
                sanitized_quota_headers=sanitized_headers,
                attempts=attempts,
            )
        except Exception as exc:
            mission_used_after = self._mission_used()
            mission_delta = (
                mission_used_after - mission_used_before
                if mission_used_before is not None
                and mission_used_after is not None
                and mission_used_after >= mission_used_before
                else 0
            )
            if mission_used_before is None or mission_used_after is None:
                mission_delta = max(1, attempts)
            provider_calls = min(4, max(provider_calls, mission_delta))
            attempts = min(4, max(attempts, provider_calls))
            failed_at = self.clock()
            self._record_task_state(
                task=task,
                attempt_number=attempt_number,
                status=_failure_task_status(exc),
                started_at=started_at,
                recorded_at=failed_at,
                attempts=attempts,
                provider_calls=provider_calls,
                error=exc,
            )
            raise

        completed_at = self.clock()
        receipt_payload_hash = _receipt_value(receipt, "payload_sha256")
        receipt_r2_key = _receipt_value(receipt, "payload_key")
        receipt_rows_normalized = _receipt_value(receipt, "rows_normalized")
        self._record_task_state(
            task=task,
            attempt_number=attempt_number,
            status=_success_task_status(payload, receipt),
            started_at=started_at,
            recorded_at=completed_at,
            attempts=attempts,
            provider_calls=provider_calls,
            payload_hash=(
                str(receipt_payload_hash)
                if isinstance(receipt_payload_hash, str)
                else payload_hash
            ),
            r2_key=(
                str(receipt_r2_key)
                if isinstance(receipt_r2_key, str)
                else None
            ),
            rows_normalized=(
                int(receipt_rows_normalized)
                if isinstance(receipt_rows_normalized, int)
                and not isinstance(receipt_rows_normalized, bool)
                else 0
            ),
            rows_received=len(records),
        )
        response = CollectedResponse(
            task_id=task_id,
            task=task,
            endpoint=endpoint,
            params=dict(params),
            payload=payload,
            records=records,
            paging_current=current,
            paging_total=total,
            errors=errors,
            http_status=http_status,
            requested_at=requested_at,
            received_at=received_at,
            payload_sha256=payload_hash,
            receipt=receipt,
            reused=False,
        )
        self._completed[task_id] = response
        return response

    def _normalization_context(
        self,
        call: CollectedResponse,
        *,
        competition: int | str,
        season: int,
        fixture_id: int | None = None,
    ) -> _NormalizationArgs:
        _, canonical = _competition_parts(competition)
        tail = canonical.rsplit(":", 1)[-1]
        competition_id = int(tail) if tail.isdigit() else None
        return {
            "endpoint": call.endpoint,
            "competition_id": competition_id,
            "season": season,
            "task_id": call.task_id,
            "source_payload_hash": call.payload_sha256 or canonical_sha256({}),
            "observed_at": call.received_at,
            "ingested_at": call.received_at,
            "request_params": call.params,
            "fixture_id": fixture_id,
        }

    def _record_has_normalized_family(
        self,
        call: CollectedResponse,
        record: Mapping[str, Any],
        *,
        family: str,
        competition: int | str,
        season: int,
    ) -> bool:
        """Require a substantive normalized row before claiming sampled content."""

        context = self._normalization_context(
            call,
            competition=competition,
            season=season,
            fixture_id=(
                provider_id
                if isinstance(
                    provider_id := _provider_id(record),
                    int,
                )
                and not isinstance(provider_id, bool)
                else None
            ),
        )
        try:
            rows = normalize_family(family, [record], **context)
        except NormalizationError:
            return False
        return any(
            row.get("data") not in (None, "", [], {})
            for row in rows
        )

    def coverage_census(
        self,
        competitions: Sequence[Mapping[str, object] | int],
        seasons: Sequence[int],
        *,
        requested_families: Sequence[str] = DEFAULT_REQUESTED_FAMILIES,
        sample_limit: int = 20,
    ) -> dict[str, object]:
        """Compare advertised coverage with sampled content for every league/season."""

        if sample_limit < 1:
            raise ValueError("sample_limit must be positive")
        observations: list[dict[str, object]] = []
        for competition in competitions:
            league_id, canonical = _competition_parts(competition)
            for season in sorted({int(value) for value in seasons}):
                league_call = self._collect(
                    phase="coverage_census",
                    competition=canonical,
                    season=season,
                    family="coverage",
                    endpoint="/leagues",
                    params={"id": league_id, "season": season},
                )
                fixture_call = self._collect(
                    phase="coverage_census",
                    competition=canonical,
                    season=season,
                    family="fixtures_sample",
                    endpoint="/fixtures",
                    params={"league": league_id, "season": season},
                    identity={"sample_limit": sample_limit},
                )
                sampled = fixture_call.records[:sample_limit]
                sampled_ids = [
                    str(provider_id)
                    for record in sampled
                    if (provider_id := _provider_id(record)) is not None
                ]
                detail_call = (
                    self._collect(
                        phase="coverage_census",
                        competition=canonical,
                        season=season,
                        family="fixture_bundle",
                        endpoint="/fixtures",
                        params={"ids": "-".join(sampled_ids)},
                        identity={"sample_limit": sample_limit},
                    )
                    if sampled_ids
                    else None
                )
                player_call = self._collect(
                    phase="coverage_census",
                    competition=canonical,
                    season=season,
                    family="players",
                    endpoint="/players",
                    params={"league": league_id, "season": season, "page": 1},
                )
                injury_call = self._collect(
                    phase="coverage_census",
                    competition=canonical,
                    season=season,
                    family="injuries",
                    endpoint="/injuries",
                    params={"league": league_id, "season": season},
                )
                standing_call = self._collect(
                    phase="coverage_census",
                    competition=canonical,
                    season=season,
                    family="standings",
                    endpoint="/standings",
                    params={"league": league_id, "season": season},
                )
                coverage = _coverage_for_season(league_call.records, season)
                expected_fixture_ids = set(sampled_ids)
                fixture_families = (
                    set(requested_families) & _FIXTURE_CENSUS_FAMILIES
                ) | {"fixtures"}
                observed_fixture_ids: dict[str, set[str]] = {
                    family: set() for family in fixture_families
                }
                fixture_sources: list[
                    tuple[CollectedResponse, Sequence[Mapping[str, Any]]]
                ] = [(fixture_call, sampled)]
                if detail_call is not None:
                    fixture_sources.append((detail_call, detail_call.records))
                for source_call, source_records in fixture_sources:
                    for record in source_records:
                        provider_id = _provider_id(record)
                        if (
                            provider_id is None
                            or str(provider_id) not in expected_fixture_ids
                        ):
                            continue
                        for family in fixture_families:
                            if self._record_has_normalized_family(
                                source_call,
                                record,
                                family=family,
                                competition=canonical,
                                season=season,
                            ):
                                observed_fixture_ids[family].add(str(provider_id))

                direct_sources = {
                    "players": player_call,
                    "player_season_statistics": player_call,
                    "injuries": injury_call,
                    "suspensions": injury_call,
                    "standings": standing_call,
                }
                non_null_counts: dict[str, int] = {}
                denominators: dict[str, int | None] = {}
                evidence_sources: dict[str, str | None] = {}
                for family in requested_families:
                    if family in _FIXTURE_CENSUS_FAMILIES:
                        non_null_counts[family] = len(
                            observed_fixture_ids.get(family, set())
                        )
                        denominators[family] = len(sampled)
                        evidence_sources[family] = (
                            "fixtures_sample_and_bundle"
                        )
                        continue
                    direct_call = direct_sources.get(family)
                    if direct_call is None:
                        non_null_counts[family] = 0
                        denominators[family] = None
                        evidence_sources[family] = None
                        continue
                    non_null_counts[family] = sum(
                        self._record_has_normalized_family(
                            direct_call,
                            record,
                            family=family,
                            competition=canonical,
                            season=season,
                        )
                        for record in direct_call.records
                    )
                    denominators[family] = len(direct_call.records)
                    evidence_sources[family] = (
                        f"{direct_call.endpoint}:page=1"
                        if direct_call.endpoint == "/players"
                        else direct_call.endpoint
                    )

                sample_coverage_rates = {
                    family: (
                        non_null_counts[family] / denominator
                        if denominator is not None and denominator > 0
                        else None
                    )
                    for family, denominator in denominators.items()
                }
                actual = {
                    family
                    for family, count in non_null_counts.items()
                    if count > 0
                }
                matrix: dict[str, dict[str, object]] = {}
                for family in requested_families:
                    path = _COVERAGE_PATHS.get(family)
                    advertised = _coverage_at(coverage, path)
                    observed = family in actual
                    matrix[family] = {
                        "advertised_flag": advertised,
                        "advertised_path": ".".join(path) if path else None,
                        "actual_content": observed,
                        "sample_non_null_count": non_null_counts[family],
                        "sample_denominator": denominators[family],
                        "sample_coverage_rate": sample_coverage_rates[family],
                        "evidence_source": evidence_sources[family],
                        "state": _matrix_state(advertised, observed),
                    }
                fixture_identities = sum(
                    _provider_id(record) is not None for record in sampled
                )
                fixture_content_verified = bool(
                    observed_fixture_ids.get("fixtures")
                )
                observations.append(
                    {
                        "competition": canonical,
                        "provider_league_id": league_id,
                        "season": season,
                        "advertised_coverage": _json_value(coverage),
                        "sample_requested": sample_limit,
                        "sample_received": len(sampled),
                        "fixtures_expected": len(fixture_call.records),
                        "fixtures_received": len(fixture_call.records),
                        "actual_families": sorted(actual),
                        "actual_coverage": {
                            family: family in actual for family in requested_families
                        },
                        "sample_coverage_rates": sample_coverage_rates,
                        "null_rates": {
                            family: (
                                1.0 - coverage_rate
                                if (
                                    coverage_rate := sample_coverage_rates[family]
                                )
                                is not None
                                else None
                            )
                            for family in requested_families
                        },
                        "identity_rate": (
                            fixture_identities / len(sampled) if sampled else None
                        ),
                        "temporal_class": "COVERAGE_VALIDATION_ONLY",
                        "gate": (
                            "PARTIAL"
                            if fixture_content_verified
                            else "BLOCKED_BY_COVERAGE"
                        ),
                        "reason": (
                            "REAL_FIXTURE_SAMPLE_RECEIVED"
                            if fixture_content_verified
                            else "NO_VERIFIED_FIXTURE_CONTENT_RECEIVED"
                        ),
                        "field_matrix": matrix,
                        "calls": [
                            league_call.as_dict(),
                            fixture_call.as_dict(),
                            *(
                                [detail_call.as_dict()]
                                if detail_call is not None
                                else []
                            ),
                            player_call.as_dict(),
                            injury_call.as_dict(),
                            standing_call.as_dict(),
                        ],
                    }
                )
        return {
            "schema_version": "historical-deep-coverage-census-v1",
            "campaign_id": self.campaign_id,
            "requested_families": list(requested_families),
            "observations": observations,
            "observation_count": len(observations),
            "hash": canonical_sha256(observations),
        }

    def harvest_season_context(
        self,
        league: int,
        season: int,
    ) -> dict[str, object]:
        """Collect the season-level standings and round vocabulary."""

        canonical = f"api-football:{league}"
        calls: list[dict[str, object]] = []
        normalized: dict[str, list[dict[str, object]]] = {
            "standings": [],
            "rounds": [],
        }
        for family, endpoint in (
            ("standings", "/standings"),
            ("rounds", "/fixtures/rounds"),
        ):
            call = self._collect(
                phase="season_context_harvest",
                competition=canonical,
                season=season,
                family=family,
                endpoint=endpoint,
                params={"league": league, "season": season},
            )
            calls.append(call.as_dict())
            if call.payload is None:
                continue
            context = self._normalization_context(
                call,
                competition=canonical,
                season=season,
            )
            normalized[family].extend(
                normalize_family(family, call.payload, **context)
            )
        result = {
            "schema_version": "historical-deep-season-context-v1",
            "campaign_id": self.campaign_id,
            "competition": canonical,
            "season": season,
            "calls": calls,
            "normalized": normalized,
            "normalizer_version": NORMALIZER_VERSION,
        }
        result["hash"] = canonical_sha256(result)
        return result

    def pilot_fixture_bundles(
        self,
        fixture_ids: Sequence[int | str],
        *,
        competition: Mapping[str, object] | int | str,
        season: int,
        candidate_sizes: Sequence[int] = BUNDLE_CANDIDATE_SIZES,
        required_families: Sequence[str] = BUNDLE_FAMILIES,
    ) -> dict[str, object]:
        """Measure bundle size, duration, errors, completeness, and memory."""

        _, canonical = _competition_parts(competition)
        ids = tuple(dict.fromkeys(str(value) for value in fixture_ids))
        if not ids:
            raise ValueError("fixture_ids must not be empty")
        measurements: list[dict[str, object]] = []
        for candidate in candidate_sizes:
            size = int(candidate)
            if size < 1:
                raise ValueError("candidate sizes must be positive")
            selected = ids[:size]
            started = self.monotonic()
            call = self._collect(
                phase="fixture_bundle_pilot",
                competition=canonical,
                season=season,
                family="fixture_bundle",
                endpoint="/fixtures",
                params={"ids": "-".join(selected)},
                identity={"candidate_size": size},
            )
            duration_ms = max(0.0, (self.monotonic() - started) * 1000.0)
            returned_ids = {
                str(value) for record in call.records if (value := _provider_id(record)) is not None
            }
            present = sum(fixture_id in returned_ids for fixture_id in selected)
            actual = _actual_families(call.records)
            missing = sorted(set(required_families) - actual)
            payload = call.payload if call.payload is not None else {}
            complete = present == len(selected)
            success = complete and not call.errors
            measurements.append(
                {
                    "candidate_size": size,
                    "ids_sent": len(selected),
                    "duration_ms": round(duration_ms, 3),
                    "response_size_bytes": len(canonical_json_bytes(payload)),
                    "memory_bytes": _deep_size(payload),
                    "error_count": len(call.errors),
                    "errors": list(call.errors),
                    "fixtures_returned": len(call.records),
                    "fixtures_matched": present,
                    "completeness": present / len(selected),
                    "complete": complete,
                    "success": success,
                    "integrated_families": sorted(actual),
                    "missing_families": missing,
                    "call": call.as_dict(),
                }
            )
        safe_sizes = [
            _positive_int(item["candidate_size"], 1)
            for item in measurements
            if bool(item["success"])
        ]
        return {
            "schema_version": "historical-deep-fixture-bundle-pilot-v1",
            "campaign_id": self.campaign_id,
            "competition": canonical,
            "season": season,
            "candidate_sizes": [int(value) for value in candidate_sizes],
            "measurements": measurements,
            "recommended_size": max(safe_sizes) if safe_sizes else None,
            "hash": canonical_sha256(measurements),
        }

    @staticmethod
    def _fallback_flag(
        coverage_flags: Mapping[str, bool | None],
        family: str,
    ) -> bool | None:
        aliases = {
            "events": ("events",),
            "lineups": ("lineups", "lineup_players", "formations"),
            "statistics": ("statistics", "team_match_statistics"),
            "players": ("players", "player_match_statistics"),
        }
        for key in aliases[family]:
            if key in coverage_flags:
                return coverage_flags[key]
        return None

    @staticmethod
    def _fallback_receipt(
        *,
        fixture: int | str,
        missing_family: str,
        flag: bool | None,
        endpoint: str,
        calls: int,
        result: str,
        reason: str,
        call: CollectedResponse | None = None,
    ) -> dict[str, object]:
        content: dict[str, object] = {
            "fixture": fixture,
            "missing_family": missing_family,
            "flag": flag,
            "bundle_checked": True,
            "endpoint": endpoint,
            "calls": calls,
            "result": result,
            "reason": reason,
        }
        if call is not None:
            content["task_id"] = call.task_id
            content["payload_sha256"] = call.payload_sha256
        content["hash"] = canonical_sha256(content)
        return content

    def _targeted_fallbacks(
        self,
        *,
        fixture_id: int | str,
        competition: str,
        season: int,
        actual_families: set[str],
        coverage_flags: Mapping[str, bool | None],
        fallback_families: Sequence[str],
    ) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]]]:
        receipts: list[dict[str, object]] = []
        normalized: dict[str, list[dict[str, object]]] = {}
        for family in fallback_families:
            if family not in _FALLBACK_ENDPOINTS:
                raise ValueError(f"unsupported fallback family: {family}")
            endpoint = _FALLBACK_ENDPOINTS[family]
            detection_family = _FALLBACK_DETECTION_FAMILY[family]
            flag = self._fallback_flag(coverage_flags, family)
            if detection_family in actual_families:
                receipts.append(
                    self._fallback_receipt(
                        fixture=fixture_id,
                        missing_family=family,
                        flag=flag,
                        endpoint=endpoint,
                        calls=0,
                        result="SKIPPED",
                        reason="BUNDLE_FAMILY_PRESENT",
                    )
                )
                continue
            if flag is not True:
                receipts.append(
                    self._fallback_receipt(
                        fixture=fixture_id,
                        missing_family=family,
                        flag=flag,
                        endpoint=endpoint,
                        calls=0,
                        result="SKIPPED",
                        reason=(
                            "COVERAGE_NOT_ADVERTISED" if flag is False else "COVERAGE_FLAG_UNKNOWN"
                        ),
                    )
                )
                continue

            call = self._collect(
                phase="fixture_fallback",
                competition=competition,
                season=season,
                family=detection_family,
                endpoint=endpoint,
                params={"fixture": fixture_id},
            )
            has_content = bool(call.records)
            result = (
                "COLLECTED"
                if has_content and not call.errors
                else ("ERROR" if call.errors else "EMPTY_VALID")
            )
            reason = (
                "TARGETED_FALLBACK_OBSERVED"
                if result == "COLLECTED"
                else "PROVIDER_ERROR"
                if result == "ERROR"
                else "TARGETED_FALLBACK_EMPTY"
            )
            receipts.append(
                self._fallback_receipt(
                    fixture=fixture_id,
                    missing_family=family,
                    flag=flag,
                    endpoint=endpoint,
                    calls=0 if call.reused else 1,
                    result=result,
                    reason=reason,
                    call=call,
                )
            )
            if call.payload is None:
                continue
            context = self._normalization_context(
                call,
                competition=competition,
                season=season,
                fixture_id=int(fixture_id) if str(fixture_id).isdigit() else None,
            )
            for normalized_family in _FALLBACK_NORMALIZED_FAMILIES[family]:
                rows = normalize_family(normalized_family, call.payload, **context)
                normalized.setdefault(normalized_family, []).extend(rows)
        return receipts, normalized

    def harvest_fixture_bundles(
        self,
        fixture_ids: Sequence[int | str],
        *,
        competition: Mapping[str, object] | int | str,
        season: int,
        batch_size: int = 20,
        coverage_flags: Mapping[str, bool | None] | None = None,
        fallback_families: Sequence[str] = FALLBACK_FAMILIES,
    ) -> dict[str, object]:
        """Collect fixture bundles, then only advertised and missing fallbacks."""

        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        _, canonical = _competition_parts(competition)
        ids = tuple(dict.fromkeys(str(value) for value in fixture_ids))
        flags = dict(coverage_flags or {})
        calls: list[dict[str, object]] = []
        bundle_split_receipts: list[dict[str, object]] = []
        fallback_receipts: list[dict[str, object]] = []
        normalized: dict[str, list[dict[str, object]]] = {}
        for offset in range(0, len(ids), batch_size):
            queue: list[tuple[str, ...]] = [ids[offset : offset + batch_size]]
            while queue:
                selected = queue.pop(0)
                call = self._collect(
                    phase="fixture_bundle_harvest",
                    competition=canonical,
                    season=season,
                    family="fixture_bundle",
                    endpoint="/fixtures",
                    params={"ids": "-".join(selected)},
                )
                calls.append(call.as_dict())
                by_id = {
                    str(fixture_id): record
                    for record in call.records
                    if (fixture_id := _provider_id(record)) is not None
                }
                missing = tuple(
                    fixture_id
                    for fixture_id in selected
                    if fixture_id not in by_id
                )
                if missing and len(selected) > 1:
                    split_size = max(1, len(selected) // 2)
                    children = [
                        missing[index : index + split_size]
                        for index in range(0, len(missing), split_size)
                    ]
                    queue.extend(children)
                    bundle_split_receipts.append(
                        {
                            "ids_sent": len(selected),
                            "fixtures_returned": len(by_id),
                            "missing_fixture_ids": list(missing),
                            "next_batch_size": split_size,
                            "child_batches": len(children),
                            "reason": "BUNDLE_INCOMPLETE_RESPLIT",
                            "task_id": call.task_id,
                            "payload_sha256": call.payload_sha256,
                        }
                    )
                if call.payload is not None:
                    context = self._normalization_context(
                        call,
                        competition=canonical,
                        season=season,
                    )
                    for family in BUNDLE_FAMILIES:
                        rows = normalize_family(family, call.payload, **context)
                        normalized.setdefault(family, []).extend(rows)
                fallback_candidates = [
                    fixture_id
                    for fixture_id in selected
                    if fixture_id in by_id or len(selected) == 1
                ]
                for fixture_id in fallback_candidates:
                    record = by_id.get(fixture_id, {})
                    actual = set(detect_integrated_families(record))
                    if record:
                        actual.add("fixtures")
                    receipts, fallback_rows = self._targeted_fallbacks(
                        fixture_id=(
                            int(fixture_id)
                            if fixture_id.isdigit()
                            else fixture_id
                        ),
                        competition=canonical,
                        season=season,
                        actual_families=actual,
                        coverage_flags=flags,
                        fallback_families=fallback_families,
                    )
                    fallback_receipts.extend(receipts)
                    for family, rows in fallback_rows.items():
                        normalized.setdefault(family, []).extend(rows)
        result = {
            "schema_version": "historical-deep-fixture-harvest-v1",
            "campaign_id": self.campaign_id,
            "competition": canonical,
            "season": season,
            "fixture_count": len(ids),
            "calls": calls,
            "bundle_split_receipts": bundle_split_receipts,
            "fallback_receipts": fallback_receipts,
            "normalized": normalized,
            "normalizer_version": NORMALIZER_VERSION,
        }
        result["hash"] = canonical_sha256(result)
        return result

    def harvest_player_pages(
        self,
        league: int,
        season: int,
        *,
        start_page: int = 1,
        max_pages: int | None = None,
    ) -> dict[str, object]:
        """Collect all advertised player pages with repeated-page protection."""

        if start_page < 1:
            raise ValueError("start_page must be positive")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive when set")
        canonical = f"api-football:{league}"
        calls: list[dict[str, object]] = []
        normalized: dict[str, list[dict[str, object]]] = {
            "players": [],
            "player_season_statistics": [],
        }
        page = start_page
        page_hashes: set[str] = set()
        stop_reason = "PAGING_COMPLETE"
        while True:
            if max_pages is not None and len(calls) >= max_pages:
                stop_reason = "MAX_PAGES_REACHED"
                break
            call = self._collect(
                phase="player_pages_harvest",
                competition=canonical,
                season=season,
                family="players",
                endpoint="/players",
                params={"league": league, "season": season, "page": page},
            )
            calls.append(call.as_dict())
            if call.payload is None:
                stop_reason = "ALREADY_CAPTURED_WITHOUT_LOCAL_PAYLOAD"
                break
            semantic_hash = canonical_sha256(call.records)
            if semantic_hash in page_hashes:
                stop_reason = "REPEATED_PAGE_HASH"
                break
            page_hashes.add(semantic_hash)
            context = self._normalization_context(
                call,
                competition=canonical,
                season=season,
            )
            for family in normalized:
                normalized[family].extend(normalize_family(family, call.payload, **context))
            if not call.records:
                stop_reason = "EMPTY_PAGE"
                break
            if call.paging_current >= call.paging_total:
                stop_reason = "PAGING_COMPLETE"
                break
            next_page = call.paging_current + 1
            if next_page <= page:
                stop_reason = "NON_MONOTONIC_PAGING"
                break
            page = next_page
        result = {
            "schema_version": "historical-deep-player-pages-harvest-v1",
            "campaign_id": self.campaign_id,
            "competition": canonical,
            "season": season,
            "start_page": start_page,
            "pages_collected": len(calls),
            "stop_reason": stop_reason,
            "calls": calls,
            "normalized": normalized,
            "normalizer_version": NORMALIZER_VERSION,
        }
        result["hash"] = canonical_sha256(result)
        return result

    def harvest_injuries_sidelined(
        self,
        league: int,
        season: int,
        *,
        max_sidelined_players: int = 500,
        max_injury_pages: int | None = None,
    ) -> dict[str, object]:
        """Collect injuries first, then a deterministic bounded sidelined subset."""

        if max_sidelined_players < 0:
            raise ValueError("max_sidelined_players must be non-negative")
        if max_injury_pages is not None and max_injury_pages < 1:
            raise ValueError("max_injury_pages must be positive when set")
        canonical = f"api-football:{league}"
        injury_calls: list[dict[str, object]] = []
        injury_payloads: list[tuple[CollectedResponse, object]] = []
        page = 1
        while True:
            if max_injury_pages is not None and len(injury_calls) >= max_injury_pages:
                break
            params: dict[str, object] = {"league": league, "season": season}
            if page > 1:
                params["page"] = page
            call = self._collect(
                phase="injuries_harvest",
                competition=canonical,
                season=season,
                family="injuries",
                endpoint="/injuries",
                params=params,
            )
            injury_calls.append(call.as_dict())
            if call.payload is None:
                break
            injury_payloads.append((call, call.payload))
            if call.paging_current >= call.paging_total or not call.records:
                break
            next_page = call.paging_current + 1
            if next_page <= page:
                break
            page = next_page

        normalized: dict[str, list[dict[str, object]]] = {
            "injuries": [],
            "suspensions": [],
            "sidelined": [],
        }
        player_ids: set[int] = set()
        for call, payload in injury_payloads:
            context = self._normalization_context(
                call,
                competition=canonical,
                season=season,
            )
            normalized["injuries"].extend(normalize_family("injuries", payload, **context))
            normalized["suspensions"].extend(normalize_family("suspensions", payload, **context))
            for record in call.records:
                player_id = _mapping(record.get("player")).get("id")
                if isinstance(player_id, int) and not isinstance(player_id, bool):
                    player_ids.add(player_id)

        selected_players = sorted(player_ids)[:max_sidelined_players]
        sidelined_calls: list[dict[str, object]] = []
        for player_id in selected_players:
            call = self._collect(
                phase="sidelined_harvest",
                competition=canonical,
                season=season,
                family="sidelined",
                endpoint="/sidelined",
                params={"player": player_id},
            )
            sidelined_calls.append(call.as_dict())
            if call.payload is None:
                continue
            context = self._normalization_context(
                call,
                competition=canonical,
                season=season,
            )
            normalized["sidelined"].extend(normalize_family("sidelined", call.payload, **context))

        result = {
            "schema_version": "historical-deep-injuries-sidelined-harvest-v1",
            "campaign_id": self.campaign_id,
            "competition": canonical,
            "season": season,
            "injury_calls": injury_calls,
            "sidelined_calls": sidelined_calls,
            "injury_player_count": len(player_ids),
            "sidelined_player_limit": max_sidelined_players,
            "sidelined_players_selected": selected_players,
            "sidelined_players_omitted": max(0, len(player_ids) - len(selected_players)),
            "normalized": normalized,
            "normalizer_version": NORMALIZER_VERSION,
        }
        result["hash"] = canonical_sha256(result)
        return result


__all__ = [
    "BUNDLE_CANDIDATE_SIZES",
    "BUNDLE_FAMILIES",
    "CAMPAIGN_ID",
    "COLLECTOR_VERSION",
    "DEFAULT_REQUESTED_FAMILIES",
    "FALLBACK_FAMILIES",
    "CollectedResponse",
    "CollectionTask",
    "DeepProvider",
    "HistoricalDeepCollector",
    "ReceiptRepository",
    "make_task_id",
]
