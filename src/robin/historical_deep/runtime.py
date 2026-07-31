"""Durable runtime helpers shared by the bounded GitHub Actions jobs."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from .normalization import (
    NormalizationError,
    canonical_json_bytes,
    canonical_sha256,
    normalize_payload,
)

RAW_NAMESPACE = "historical-deep-data/schema-v1"
DERIVED_NAMESPACE = f"{RAW_NAMESPACE}/_derived"
CONTROL_NAMESPACE = f"{RAW_NAMESPACE}/_control"
_CONTINUATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
R2_READ_MAX_WORKERS = 8
NON_PROJECTING_ENDPOINTS = frozenset({"/leagues", "/status"})


class RuntimeObjectStore(Protocol):
    def get_object(self, key: str) -> bytes | None: ...

    def put_if_absent(self, key: str, data: bytes) -> bool: ...

    def iter_keys(self, prefix: str) -> Iterable[str]: ...


def read_objects_bounded(
    store: RuntimeObjectStore,
    keys: Iterable[str],
    *,
    max_workers: int = R2_READ_MAX_WORKERS,
) -> tuple[tuple[str, bytes | None], ...]:
    """Read immutable objects concurrently while preserving key order.

    R2/S3 clients are safe for concurrent reads, but their default connection
    pool is deliberately small.  Eight workers remove the per-object latency
    multiplier without creating unbounded requests or changing deterministic
    processing order.
    """

    ordered = tuple(keys)
    if max_workers < 1:
        raise ValueError("RUNTIME_READ_WORKERS_MUST_BE_POSITIVE")
    if len(ordered) < 2 or max_workers == 1:
        return tuple((key, store.get_object(key)) for key in ordered)

    def load(key: str) -> tuple[str, bytes | None]:
        return key, store.get_object(key)

    workers = min(max_workers, len(ordered))
    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="historical-r2-read",
    ) as executor:
        return tuple(executor.map(load, ordered))


def _plain(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("RUNTIME_DATETIME_MUST_BE_TIMEZONE_AWARE")
        return value.astimezone(UTC).isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _plain(model_dump(mode="json"))
    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        return _plain(as_dict())
    return repr(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RUNTIME_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _decode_json(data: bytes, *, label: str) -> object:
    try:
        raw = gzip.decompress(data) if data.startswith(b"\x1f\x8b") else data
        return json.loads(raw)
    except (gzip.BadGzipFile, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_INVALID") from error


def _response_items(payload: object) -> tuple[Mapping[str, object], ...]:
    mapped = _mapping(payload)
    response = mapped.get("response")
    if isinstance(response, Sequence) and not isinstance(
        response,
        (str, bytes, bytearray),
    ):
        return tuple(item for item in response if isinstance(item, Mapping))
    return ()


def _receipt_payload_key(receipt: Mapping[str, object]) -> str:
    for field in ("payload_key", "r2_key", "payload_r2_key"):
        value = receipt.get(field)
        if isinstance(value, str) and value:
            return value
    raise ValueError("RUNTIME_RECEIPT_PAYLOAD_KEY_MISSING")


def _receipt_params(receipt: Mapping[str, object]) -> Mapping[str, object]:
    for field in ("parameters", "params", "request_parameters"):
        value = receipt.get(field)
        if isinstance(value, Mapping):
            return value
    return {}


class DurableRuntimeLedger:
    """Append-only reports, mission clock, and provider-free raw replay index."""

    def __init__(
        self,
        store: RuntimeObjectStore,
        *,
        campaign_id: str = "historical-deep-data-harvest-v1",
    ) -> None:
        self.store = store
        self.campaign_id = campaign_id

    def _put_immutable(self, key: str, data: bytes) -> bool:
        created = self.store.put_if_absent(key, data)
        if created:
            return True
        existing = self.store.get_object(key)
        if existing != data:
            raise ValueError(f"RUNTIME_APPEND_ONLY_MISMATCH:{key}")
        return False

    def put_json(
        self,
        category: str,
        value: object,
        *,
        recorded_at: datetime,
    ) -> str:
        plain = _plain(value)
        envelope = {
            "schema_version": "historical-deep-derived-envelope-v1",
            "campaign_id": self.campaign_id,
            "category": category,
            "recorded_at": _plain(recorded_at),
            "value": plain,
        }
        body = canonical_json_bytes(envelope)
        digest = canonical_sha256(envelope)
        key = (
            f"{DERIVED_NAMESPACE}/{category.strip('/')}/"
            f"record-{_timestamp(recorded_at)}-{digest}.json.gz"
        )
        compressed = gzip.compress(body, compresslevel=9, mtime=0)
        self._put_immutable(key, compressed)
        return key

    def values(self, category: str) -> tuple[Mapping[str, object], ...]:
        prefix = f"{DERIVED_NAMESPACE}/{category.strip('/')}/"
        output: list[Mapping[str, object]] = []
        keys = (
            key
            for key in sorted(set(self.store.iter_keys(prefix)))
            if "/" not in key[len(prefix) :]
            and key[len(prefix) :].startswith("record-")
        )
        for key, body in read_objects_bounded(self.store, keys):
            if body is None:
                raise ValueError(f"RUNTIME_DERIVED_OBJECT_MISSING:{key}")
            envelope = _mapping(_decode_json(body, label="RUNTIME_DERIVED_OBJECT"))
            if (
                envelope.get("schema_version")
                != "historical-deep-derived-envelope-v1"
                or envelope.get("campaign_id") != self.campaign_id
                or envelope.get("category") != category
            ):
                raise ValueError(f"RUNTIME_DERIVED_CONTRACT_MISMATCH:{key}")
            output.append(envelope)
        return tuple(output)

    def latest_value(self, category: str) -> object | None:
        values = self.values(category)
        if not values:
            return None
        latest = max(values, key=lambda item: str(item.get("recorded_at", "")))
        return latest.get("value")

    def mission_start(
        self,
        *,
        now: datetime,
        code_revision: str,
        maximum_minutes: int,
    ) -> datetime:
        if maximum_minutes <= 0:
            raise ValueError("MISSION_MAXIMUM_MINUTES_MUST_BE_POSITIVE")
        key = f"{CONTROL_NAMESPACE}/mission-start.json"
        candidate = {
            "schema_version": "historical-deep-mission-clock-v1",
            "campaign_id": self.campaign_id,
            "started_at": _plain(now),
            "code_revision": code_revision,
            "maximum_minutes": maximum_minutes,
        }
        body = canonical_json_bytes(candidate)
        if self.store.put_if_absent(key, body):
            return now.astimezone(UTC)
        existing_body = self.store.get_object(key)
        if existing_body is None:
            raise ValueError("MISSION_CLOCK_CONDITIONAL_WRITE_INCONSISTENT")
        existing = _mapping(_decode_json(existing_body, label="MISSION_CLOCK"))
        if (
            existing.get("schema_version") != "historical-deep-mission-clock-v1"
            or existing.get("campaign_id") != self.campaign_id
        ):
            raise ValueError("MISSION_CLOCK_CONTRACT_MISMATCH")
        started_at = existing.get("started_at")
        if not isinstance(started_at, str):
            raise ValueError("MISSION_CLOCK_START_MISSING")
        parsed = datetime.fromisoformat(started_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("MISSION_CLOCK_START_NAIVE")
        return parsed.astimezone(UTC)

    def continuation_start(
        self,
        *,
        continuation_id: str,
        continuation_of: str,
        run_purpose: str,
        now: datetime,
        code_revision: str,
        maximum_minutes: int,
    ) -> datetime:
        """Create or resume a mission clock without mutating the parent clock."""

        if not _CONTINUATION_ID_PATTERN.fullmatch(continuation_id):
            raise ValueError("CONTINUATION_ID_INVALID")
        if not continuation_of or not run_purpose:
            raise ValueError("CONTINUATION_LINEAGE_REQUIRED")
        if maximum_minutes <= 0:
            raise ValueError("MISSION_MAXIMUM_MINUTES_MUST_BE_POSITIVE")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("CONTINUATION_START_MUST_BE_TIMEZONE_AWARE")
        lineage_hash = hashlib.sha256(
            f"{continuation_of}\n{run_purpose}".encode("utf-8")
        ).hexdigest()
        key = (
            f"{CONTROL_NAMESPACE}/continuations/"
            f"continuation={continuation_id}/mission-start.json"
        )
        candidate = {
            "schema_version": "historical-deep-continuation-clock-v1",
            "campaign_id": self.campaign_id,
            "continuation_id": continuation_id,
            "continuation_of": continuation_of,
            "run_purpose": run_purpose,
            "lineage_hash": lineage_hash,
            "started_at": _plain(now),
            "code_revision_at_start": code_revision,
            "maximum_minutes": maximum_minutes,
            "parent_clock_mutated": False,
        }
        body = canonical_json_bytes(candidate)
        if self.store.put_if_absent(key, body):
            return now.astimezone(UTC)
        existing_body = self.store.get_object(key)
        if existing_body is None:
            raise ValueError("CONTINUATION_CLOCK_CONDITIONAL_WRITE_INCONSISTENT")
        existing = _mapping(
            _decode_json(existing_body, label="CONTINUATION_CLOCK")
        )
        for field, expected in (
            ("schema_version", "historical-deep-continuation-clock-v1"),
            ("campaign_id", self.campaign_id),
            ("continuation_id", continuation_id),
            ("continuation_of", continuation_of),
            ("run_purpose", run_purpose),
            ("lineage_hash", lineage_hash),
            ("parent_clock_mutated", False),
        ):
            if existing.get(field) != expected:
                raise ValueError("CONTINUATION_CLOCK_CONTRACT_MISMATCH")
        started_at = existing.get("started_at")
        if not isinstance(started_at, str):
            raise ValueError("CONTINUATION_CLOCK_START_MISSING")
        parsed = datetime.fromisoformat(started_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("CONTINUATION_CLOCK_START_NAIVE")
        return parsed.astimezone(UTC)

    def mission_has_time(
        self,
        *,
        now: datetime,
        started_at: datetime,
        maximum_minutes: int,
    ) -> bool:
        return now.astimezone(UTC) < started_at + timedelta(minutes=maximum_minutes)

    def checkpoint(
        self,
        *,
        phase: str,
        status: str,
        provider_calls: int,
        tasks_completed: int,
        started_at: datetime,
        recorded_at: datetime,
        reason: str | None = None,
    ) -> str:
        return self.put_json(
            f"checkpoints/{phase}",
            {
                "phase": phase,
                "status": status,
                "provider_calls": provider_calls,
                "tasks_completed": tasks_completed,
                "started_at": _plain(started_at),
                "last_heartbeat": _plain(recorded_at),
                "reason": reason,
            },
            recorded_at=recorded_at,
        )

    def raw_evidence(
        self,
    ) -> tuple[dict[str, bytes], tuple[Mapping[str, object], ...]]:
        payloads: dict[str, bytes] = {}
        receipts: list[Mapping[str, object]] = []
        for receipt, payload_body in self.iter_raw_evidence():
            payload_key = _receipt_payload_key(receipt)
            payloads[payload_key] = payload_body
            receipts.append(receipt)
        return payloads, tuple(receipts)

    def iter_raw_evidence(
        self,
    ) -> Iterator[tuple[Mapping[str, object], bytes]]:
        """Yield one receipt and referenced payload at a time."""

        for receipt in self._raw_receipts():
            payload_key = _receipt_payload_key(receipt)
            payload_body = self.store.get_object(payload_key)
            if payload_body is None:
                raise ValueError(f"RUNTIME_PAYLOAD_MISSING:{payload_key}")
            yield receipt, payload_body

    def raw_payload_keys(self) -> Iterator[str]:
        """Yield every immutable raw payload key for orphan detection."""

        prefix = f"{RAW_NAMESPACE}/competition="
        for key in sorted(set(self.store.iter_keys(prefix))):
            if "/payload-" in key and key.endswith(".json.gz"):
                yield key

    def normalized_records(self) -> tuple[list[dict[str, object]], tuple[str, ...]]:
        rows: list[dict[str, object]] = []
        errors: list[str] = []
        for receipt in self._raw_receipts():
            payload_key = _receipt_payload_key(receipt)
            payload_body = self.store.get_object(payload_key)
            if payload_body is None:
                raise ValueError(f"RUNTIME_PAYLOAD_MISSING:{payload_key}")
            payload = _decode_json(
                payload_body,
                label="RUNTIME_PAYLOAD",
            )
            endpoint = str(receipt.get("endpoint", receipt.get("source_endpoint", "")))
            if not endpoint or endpoint.rstrip("/") in NON_PROJECTING_ENDPOINTS:
                continue
            competition_value = str(receipt.get("competition", ""))
            tail = competition_value.rsplit(":", 1)[-1]
            competition_id = int(tail) if tail.isdigit() else None
            season_value = receipt.get("season")
            season = (
                int(season_value)
                if isinstance(season_value, (int, str))
                and not isinstance(season_value, bool)
                and str(season_value).isdigit()
                else None
            )
            task_id = str(receipt.get("task_id", ""))
            observed_raw = receipt.get(
                "received_at",
                receipt.get("response_received_at", receipt.get("completed_at")),
            )
            observed = (
                datetime.fromisoformat(str(observed_raw))
                if observed_raw is not None
                else datetime.now(UTC)
            )
            if observed.tzinfo is None or observed.utcoffset() is None:
                observed = observed.replace(tzinfo=UTC)
            try:
                normalized = normalize_payload(
                    payload,
                    endpoint=endpoint,
                    competition_id=competition_id,
                    season=season,
                    task_id=task_id,
                    source_payload_hash=str(
                        receipt.get("payload_sha256", canonical_sha256(payload))
                    ),
                    request_params=_receipt_params(receipt),
                    observed_at=observed,
                    ingested_at=observed,
                )
            except NormalizationError as error:
                errors.append(f"{task_id}:{error}")
                continue
            for family, family_rows in normalized.items():
                rows.extend(
                    {"normalized_family": family, **dict(row)} for row in family_rows
                )
        rows.sort(
            key=lambda row: (
                str(row.get("normalized_family", "")),
                str(row.get("competition_id", "")),
                str(row.get("season", "")),
                str(row.get("fixture_id", "")),
                str(row.get("provider_id", "")),
                str(row.get("task_id", "")),
            )
        )
        return rows, tuple(errors)

    def evidence_metrics(self) -> dict[str, object]:
        """Aggregate receipt metadata without loading raw provider payloads."""

        payload_keys: set[str] = set()
        families: dict[str, int] = {}
        statuses: dict[str, int] = {}
        competition_seasons: set[tuple[str, str]] = set()
        receipt_count = 0
        payload_bytes = 0
        stored_bytes = 0
        provider_calls = 0
        attempts = 0
        rows_normalized = 0
        for receipt in self._raw_receipts():
            receipt_count += 1
            payload_keys.add(_receipt_payload_key(receipt))
            family = str(receipt.get("family", "UNKNOWN"))
            status = str(receipt.get("status", "UNKNOWN"))
            families[family] = families.get(family, 0) + 1
            statuses[status] = statuses.get(status, 0) + 1
            competition_seasons.add(
                (
                    str(receipt.get("competition", "UNKNOWN")),
                    str(receipt.get("season", "UNKNOWN")),
                )
            )
            for field, target in (
                ("payload_bytes", "payload"),
                ("stored_bytes", "stored"),
                ("provider_calls", "calls"),
                ("attempts", "attempts"),
                ("rows_normalized", "rows"),
            ):
                raw = receipt.get(field, 0)
                value = (
                    int(raw)
                    if isinstance(raw, (int, str))
                    and not isinstance(raw, bool)
                    and str(raw).isdigit()
                    else 0
                )
                if target == "payload":
                    payload_bytes += value
                elif target == "stored":
                    stored_bytes += value
                elif target == "calls":
                    provider_calls += value
                elif target == "attempts":
                    attempts += value
                else:
                    rows_normalized += value
        metrics = {
            "schema_version": "historical-deep-storage-metrics-v1",
            "receipts": receipt_count,
            "payload_objects": len(payload_keys),
            "payload_bytes": payload_bytes,
            "stored_bytes": stored_bytes,
            "provider_calls_in_receipts": provider_calls,
            "attempts_in_receipts": attempts,
            "retries_in_receipts": max(0, attempts - receipt_count),
            "rows_normalized_in_receipts": rows_normalized,
            "families": dict(sorted(families.items())),
            "statuses": dict(sorted(statuses.items())),
            "competition_seasons": len(competition_seasons),
            "hash_mismatches": None,
            "hash_verification": "NOT_EVALUATED_USE_REPLAY_PROOF",
            "deletions": 0,
            "raw_payloads_in_git": 0,
        }
        metrics.update(self.task_attempt_metrics())
        return metrics

    def task_attempt_metrics(self) -> dict[str, object]:
        """Summarize each task's latest immutable journal event."""

        latest: dict[str, tuple[str, Mapping[str, object]]] = {}
        prefix = f"{RAW_NAMESPACE}/competition="
        keys = tuple(
            key
            for key in sorted(set(self.store.iter_keys(prefix)))
            if "/attempts/attempt=" in key
            and "/event=" in key
            and key.endswith(".json")
        )
        for key, body in read_objects_bounded(self.store, keys):
            if body is None:
                raise ValueError(f"RUNTIME_TASK_ATTEMPT_MISSING:{key}")
            event = _mapping(_decode_json(body, label="RUNTIME_TASK_ATTEMPT"))
            if (
                event.get("schema_version")
                != "historical-deep-task-attempt-v1"
                or event.get("campaign_id") != self.campaign_id
            ):
                raise ValueError(f"RUNTIME_TASK_ATTEMPT_CONTRACT_MISMATCH:{key}")
            task_id = event.get("task_id")
            status = event.get("status")
            if not isinstance(task_id, str) or not isinstance(status, str):
                raise ValueError(f"RUNTIME_TASK_ATTEMPT_FIELDS_MISSING:{key}")
            previous = latest.get(task_id)
            if previous is None or key > previous[0]:
                latest[task_id] = (key, event)

        statuses: dict[str, int] = {}
        last_heartbeat: str | None = None
        rows_received = 0
        for _key, event in latest.values():
            status = str(event["status"])
            statuses[status] = statuses.get(status, 0) + 1
            heartbeat = event.get("heartbeat_at")
            if isinstance(heartbeat, str) and (
                last_heartbeat is None or heartbeat > last_heartbeat
            ):
                last_heartbeat = heartbeat
            value = event.get("rows_received")
            if isinstance(value, int) and not isinstance(value, bool):
                rows_received += value
        success = statuses.get("COMPLETE", 0) + statuses.get("EMPTY_VALID", 0)
        failures = statuses.get("FAILED", 0)
        blocked = statuses.get("BLOCKED_COVERAGE", 0) + statuses.get(
            "BLOCKED_PROVIDER",
            0,
        )
        retryable = (
            statuses.get("PENDING", 0)
            + statuses.get("RUNNING", 0)
            + statuses.get("RETRYABLE", 0)
        )
        return {
            "task_events": len(keys),
            "tasks": len(latest),
            "task_statuses": dict(sorted(statuses.items())),
            "tasks_completed": success,
            "tasks_remaining": retryable + blocked,
            "tasks_blocked": blocked,
            "tasks_failed": failures,
            "task_errors": retryable + blocked + failures,
            "rows_received_in_task_journal": rows_received,
            "last_task_heartbeat": last_heartbeat,
        }

    def _raw_receipts(
        self,
        *,
        league: int | None = None,
        season: int | None = None,
    ) -> Iterator[Mapping[str, object]]:
        """Read receipt metadata without touching any referenced payload body."""

        if (league is None) != (season is None):
            raise ValueError("RUNTIME_RECEIPT_SCOPE_REQUIRES_LEAGUE_AND_SEASON")
        prefix = (
            f"{RAW_NAMESPACE}/competition=api-football:{league}/season={season}/"
            if league is not None and season is not None
            else f"{RAW_NAMESPACE}/competition="
        )
        keys = (
            key
            for key in sorted(set(self.store.iter_keys(prefix)))
            if key.endswith("/receipt.json")
        )
        for key, body in read_objects_bounded(self.store, keys):
            if body is None:
                raise ValueError(f"RUNTIME_RECEIPT_MISSING:{key}")
            yield _mapping(_decode_json(body, label="RUNTIME_RECEIPT"))

    def _payload_from_receipt(
        self,
        receipt: Mapping[str, object],
        *,
        label: str,
    ) -> object:
        payload_key = _receipt_payload_key(receipt)
        body = self.store.get_object(payload_key)
        if body is None:
            raise ValueError(f"RUNTIME_PAYLOAD_MISSING:{payload_key}")
        return _decode_json(body, label=label)

    def fixture_inventory(
        self,
        *,
        league: int,
        season: int,
    ) -> tuple[int, ...]:
        fixture_ids: set[int] = set()
        for receipt in self._raw_receipts(league=league, season=season):
            endpoint = str(receipt.get("endpoint", receipt.get("source_endpoint", "")))
            params = _receipt_params(receipt)
            if (
                endpoint.rstrip("/") != "/fixtures"
                or str(params.get("league")) != str(league)
                or str(params.get("season")) != str(season)
                or params.get("ids") is not None
            ):
                continue
            payload = self._payload_from_receipt(
                receipt,
                label="RUNTIME_FIXTURE_PAYLOAD",
            )
            for item in _response_items(payload):
                fixture = _mapping(item.get("fixture"))
                fixture_id = fixture.get("id", item.get("id"))
                if isinstance(fixture_id, int) and not isinstance(fixture_id, bool):
                    fixture_ids.add(fixture_id)
        return tuple(sorted(fixture_ids))

    def coverage_flags(
        self,
        *,
        league: int,
        season: int,
    ) -> dict[str, bool | None]:
        flags: dict[str, bool | None] = {}
        for receipt in self._raw_receipts(league=league, season=season):
            endpoint = str(receipt.get("endpoint", receipt.get("source_endpoint", "")))
            params = _receipt_params(receipt)
            if (
                endpoint.rstrip("/") != "/leagues"
                or str(params.get("id")) != str(league)
                or str(params.get("season")) != str(season)
            ):
                continue
            payload = self._payload_from_receipt(
                receipt,
                label="RUNTIME_COVERAGE_PAYLOAD",
            )
            for league_record in _response_items(payload):
                seasons = league_record.get("seasons")
                if not isinstance(seasons, Sequence) or isinstance(
                    seasons,
                    (str, bytes, bytearray),
                ):
                    continue
                for season_record in seasons:
                    mapped_season = _mapping(season_record)
                    if mapped_season.get("year") != season:
                        continue
                    coverage = _mapping(mapped_season.get("coverage"))
                    fixtures = _mapping(coverage.get("fixtures"))
                    flags.update(
                        {
                            "events": (
                                bool(fixtures["events"])
                                if isinstance(fixtures.get("events"), bool)
                                else None
                            ),
                            "lineups": (
                                bool(fixtures["lineups"])
                                if isinstance(fixtures.get("lineups"), bool)
                                else None
                            ),
                            "statistics": (
                                bool(fixtures["statistics_fixtures"])
                                if isinstance(
                                    fixtures.get("statistics_fixtures"),
                                    bool,
                                )
                                else None
                            ),
                            "players": (
                                bool(fixtures["statistics_players"])
                                if isinstance(
                                    fixtures.get("statistics_players"),
                                    bool,
                                )
                                else None
                            ),
                        }
                    )
        return flags


def compact_artifact(value: object) -> object:
    """Remove row-level material before publishing GitHub artifacts."""

    if isinstance(value, Mapping):
        compact: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name in {"payload", "entries", "items"}:
                if isinstance(item, Sequence) and not isinstance(
                    item,
                    (str, bytes, bytearray),
                ):
                    compact[f"{name}_count"] = len(item)
                else:
                    compact[f"{name}_present"] = item is not None
                continue
            if name == "normalized" and isinstance(item, Mapping):
                compact["normalized_counts"] = {
                    str(family): (
                        len(rows)
                        if isinstance(rows, Sequence)
                        and not isinstance(rows, (str, bytes, bytearray))
                        else 0
                    )
                    for family, rows in item.items()
                }
                compact["normalized_hash"] = canonical_sha256(item)
                continue
            compact[name] = compact_artifact(item)
        return compact
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [compact_artifact(item) for item in value]
    return _plain(value)


def write_artifact(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        compact_artifact(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    path.write_text(f"{text}\n", encoding="utf-8")


__all__ = [
    "CONTROL_NAMESPACE",
    "DERIVED_NAMESPACE",
    "RAW_NAMESPACE",
    "DurableRuntimeLedger",
    "RuntimeObjectStore",
    "compact_artifact",
    "write_artifact",
]
