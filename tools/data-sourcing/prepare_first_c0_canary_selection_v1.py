#!/usr/bin/env python3
"""Prepare one immutable single-league First-C0 selection bundle and stop before DNS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from robin.capture.bootstrap_contracts import (
    FirstC0CanarySelectionV1,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
)
from robin.capture.contracts import canonical_json_bytes, strict_json_loads
from robin.capture.official_schedule_sources import (
    DFB_DATACENTER_HTML_V1,
    LALIGA_PUBLIC_MATCHES_JSON_V1,
    BuiltinHttpsOfficialScheduleFetcher,
    OfficialScheduleFetcher,
    OfficialScheduleSourceError,
    OfficialSourceSpec,
    build_official_schedule_evidence,
    fetch_official_schedule_source,
)
from robin.capture.predns_orchestration import (
    _CONTROL_MARKER_NAME,
    _GLOBAL_MARKER_ROOT_NAME,
    MINIMUM_READY_MARGIN_SECONDS,
    OFFICIAL_SCHEDULE_HORIZON_DAYS,
    SAFETY_CUTOFF_SECONDS,
    _local_app_data_readonly,
    freeze_official_schedule_evidence_v1,
)
from robin.capture.storage import (
    _safe_read_bounded,
    validate_exclusive_local_directory_identity,
)
from robin.capture.workspace_bootstrap import (
    assert_real_capture_workspace_receipt_current_v1,
    assert_workspace_control_artifact_destination_v1,
    load_tracked_real_execution_mission_manifest_v1,
)

_SOURCE_PLAN_SCHEMA = "robin-first-c0-canary-source-plan-v1"
_BUNDLE_SCHEMA = "robin-first-c0-canary-bundle-v1"
_ATTEMPT_RECEIPT_SCHEMA = "robin-first-c0-canary-attempt-receipt-v1"
_OFFICIAL_READ_RESERVATION_SCHEMA = "robin-first-c0-canary-official-read-reservation-v1"
_CYCLE_RESERVATION_NAME = "first-c0-canary-cycle-{cycle:02d}-read-reservation-v1.json"
_CYCLE_RECEIPT_NAME = "first-c0-canary-cycle-{cycle:02d}-attempt-receipt-v1.json"
_MAXIMUM_JSON_BYTES = 4_194_304
_MAXIMUM_SOURCE_PLAN_BYTES = 1_048_576
_MAXIMUM_PREPARATION_CYCLES = 3
_MAXIMUM_OFFICIAL_PHYSICAL_READS = 12
_PRIMARY_SPORT_KEY = "soccer_spain_la_liga"
_FALLBACK_SPORT_KEY = "soccer_germany_bundesliga"
_ADAPTER_BY_SPORT = {
    _PRIMARY_SPORT_KEY: LALIGA_PUBLIC_MATCHES_JSON_V1,
    _FALLBACK_SPORT_KEY: DFB_DATACENTER_HTML_V1,
}
_FALLBACK_CATEGORIES = {
    "SOURCE_UNAVAILABLE",
    "PARSER_FAIL_CLOSED",
    "NO_PROSPECTIVE_FIXTURE",
    "NO_H24_H2_WINDOW",
}
_OFFICIAL_READ_RESERVATION_FIELDS = {
    "schema_version",
    "cycle_index",
    "cycle_role",
    "workspace_receipt_sha256",
    "mission_manifest_sha256",
    "source_plan_sha256",
    "prior_cycle_receipt_sha256",
    "sport_key",
    "adapter",
    "url",
    "status",
    "official_reads_reserved",
    "cumulative_official_reads_reserved",
    "provider_dns",
    "provider_tcp",
    "provider_http",
    "secret_reads",
    "owner_review_pack_builds",
    "recorded_at_utc",
}
_ATTEMPT_RECEIPT_FIELDS = {
    "schema_version",
    "cycle_index",
    "cycle_role",
    "workspace_receipt_sha256",
    "mission_manifest_sha256",
    "source_plan_sha256",
    "prior_cycle_receipt_sha256",
    "reservation_sha256",
    "sport_key",
    "adapter",
    "url",
    "status",
    "code",
    "fallback_category",
    "failure_classification",
    "http_status",
    "official_reads",
    "supporting_official_reads",
    "cumulative_official_reads",
    "recommended_refresh_utc",
    "selected_not_before_utc",
    "bundle_manifest_sha256",
    "official_fetch_receipt",
    "provider_dns",
    "provider_tcp",
    "provider_http",
    "secret_reads",
    "owner_review_pack_builds",
    "recorded_at_utc",
}
_TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_DETERMINISTIC_HTTP_STATUSES = {400, 401, 403, 404, 405, 410}


class FirstC0CanaryPreparationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FirstC0CanarySourcePlanV1:
    source: OfficialSourceSpec
    canonical_sha256: str


@dataclass(frozen=True, slots=True)
class FirstC0CanaryPreparationResultV1:
    status: str
    selection: FirstC0CanarySelectionV1
    bundle_directory: Path
    bundle_manifest_sha256: str
    recommended_refresh_utc: datetime
    cycle_index: int
    official_reads: int
    cumulative_official_reads: int
    supporting_official_reads: int
    marker_inspection: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class FirstC0CanaryCycleHistoryV1:
    cycle_index: int
    reservation: Mapping[str, object]
    receipt: Mapping[str, object]
    reservation_bytes: bytes
    receipt_bytes: bytes
    receipt_sha256: str


def _read(path: Path, *, maximum_bytes: int = _MAXIMUM_JSON_BYTES) -> bytes:
    return _safe_read_bounded(path.absolute(), maximum_bytes=maximum_bytes)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc(value: datetime, *, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FirstC0CanaryPreparationError(code)
    return value.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return _utc(value, code="FIRST_C0_CANARY_DATETIME_INVALID").isoformat().replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _write_exclusive(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_ARTIFACT_EXISTS") from None
    except OSError:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_ARTIFACT_WRITE_FAILED") from None


def load_first_c0_canary_source_plan_v1(payload: bytes) -> FirstC0CanarySourcePlanV1:
    if len(payload) > _MAXIMUM_SOURCE_PLAN_BYTES:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_TOO_LARGE")
    try:
        raw = strict_json_loads(payload)
    except (TypeError, ValueError):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_INVALID") from None
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "sport_key", "adapter", "url"}
        or raw.get("schema_version") != _SOURCE_PLAN_SCHEMA
    ):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_INVALID")
    sport_key = raw.get("sport_key")
    adapter = raw.get("adapter")
    url = raw.get("url")
    if (
        not isinstance(sport_key, str)
        or sport_key not in _ADAPTER_BY_SPORT
        or adapter != _ADAPTER_BY_SPORT[sport_key]
        or not isinstance(url, str)
    ):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise FirstC0CanaryPreparationError(
            "FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID"
        ) from None
    host = (parsed.hostname or "").rstrip(".").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID")
    if sport_key == _PRIMARY_SPORT_KEY:
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            host != "apim.laliga.com"
            or parsed.path != "/public-service/api/v1/matches"
            or set(query) != {"subscription", "competition", "limit", "offset"}
            or query.get("subscription") != ["laliga-easports-2026"]
            or query.get("competition") != ["primera-division"]
            or query.get("limit") != ["100"]
            or query.get("offset") != ["300"]
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID")
    elif (
        host != "datencenter.dfb.de"
        or parsed.path != "/competitions/12/seasons/current"
        or parsed.query
    ):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID")
    canonical = {
        "schema_version": _SOURCE_PLAN_SCHEMA,
        "sport_key": sport_key,
        "adapter": adapter,
        "url": url,
    }
    return FirstC0CanarySourcePlanV1(
        source=OfficialSourceSpec(sport_key=sport_key, adapter=adapter, url=url),
        canonical_sha256=_sha256(canonical_json_bytes(canonical)),
    )


def inspect_first_c0_canary_markers_read_only_v1(
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
) -> Mapping[str, object]:
    local_marker = Path(workspace_receipt.control_temp_root) / _CONTROL_MARKER_NAME
    global_marker = (
        _local_app_data_readonly()
        / _GLOBAL_MARKER_ROOT_NAME
        / (
            f"{mission_manifest.mission_id.casefold()}-"
            f"{mission_manifest.canonical_manifest_sha256()}.json"
        )
    )
    return {
        "schema_version": "robin-first-c0-canary-marker-inspection-v1",
        "local_marker_path": str(local_marker.absolute()),
        "global_marker_path": str(global_marker.absolute()),
        "local_marker_present": os.path.lexists(local_marker),
        "global_marker_present": os.path.lexists(global_marker),
        "inspected_read_only": True,
    }


def _assert_markers_absent(marker_inspection: Mapping[str, object]) -> None:
    if (
        marker_inspection.get("local_marker_present") is not False
        or marker_inspection.get("global_marker_present") is not False
        or marker_inspection.get("inspected_read_only") is not True
    ):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PROVIDER_MARKER_PRESENT")


def _cycle_reservation_path(
    workspace: RealCaptureWorkspaceReceiptV1,
    cycle_index: int,
) -> Path:
    return Path(workspace.control_temp_root) / _CYCLE_RESERVATION_NAME.format(cycle=cycle_index)


def _cycle_receipt_path(
    workspace: RealCaptureWorkspaceReceiptV1,
    cycle_index: int,
) -> Path:
    return Path(workspace.control_temp_root) / _CYCLE_RECEIPT_NAME.format(cycle=cycle_index)


def _parse_utc_text(value: object, *, code: str) -> datetime:
    if not isinstance(value, str):
        raise FirstC0CanaryPreparationError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FirstC0CanaryPreparationError(code) from None
    return _utc(parsed, code=code)


def _cycle_role_prefix(sport_key: str) -> str:
    return "PRIMARY" if sport_key == _PRIMARY_SPORT_KEY else "FALLBACK"


def _load_cycle_history(
    workspace: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
) -> tuple[FirstC0CanaryCycleHistoryV1, ...]:
    history: list[FirstC0CanaryCycleHistoryV1] = []
    previous_receipt_sha256: str | None = None
    previous_cumulative_reads = 0
    for cycle_index in range(1, _MAXIMUM_PREPARATION_CYCLES + 1):
        reservation_path = _cycle_reservation_path(workspace, cycle_index)
        receipt_path = _cycle_receipt_path(workspace, cycle_index)
        reservation_present = os.path.lexists(reservation_path)
        receipt_present = os.path.lexists(receipt_path)
        if not reservation_present and not receipt_present:
            for later_cycle in range(cycle_index + 1, _MAXIMUM_PREPARATION_CYCLES + 1):
                if os.path.lexists(
                    _cycle_reservation_path(workspace, later_cycle)
                ) or os.path.lexists(_cycle_receipt_path(workspace, later_cycle)):
                    raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PREPARATION_HISTORY_GAP")
            break
        if not reservation_present or not receipt_present:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PREVIOUS_CYCLE_INCOMPLETE")
        try:
            reservation_bytes = _read(reservation_path)
            receipt_bytes = _read(receipt_path)
            reservation = strict_json_loads(reservation_bytes)
            receipt = strict_json_loads(receipt_bytes)
        except (OSError, TypeError, ValueError):
            raise FirstC0CanaryPreparationError(
                "FIRST_C0_CANARY_PREPARATION_HISTORY_INVALID"
            ) from None
        if not isinstance(reservation, dict) or not isinstance(receipt, dict):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PREPARATION_HISTORY_INVALID")
        sport_key = reservation.get("sport_key")
        official_reads = reservation.get("official_reads_reserved")
        cumulative_reads = reservation.get("cumulative_official_reads_reserved")
        if (
            set(reservation) != _OFFICIAL_READ_RESERVATION_FIELDS
            or reservation.get("schema_version") != _OFFICIAL_READ_RESERVATION_SCHEMA
            or reservation.get("cycle_index") != cycle_index
            or reservation.get("cycle_role")
            not in {
                "PRIMARY_INITIAL",
                "PRIMARY_RETRY",
                "PRIMARY_REFRESH",
                "FALLBACK_INITIAL",
                "FALLBACK_RETRY",
                "FALLBACK_REFRESH",
            }
            or reservation.get("workspace_receipt_sha256") != workspace.canonical_receipt_hash
            or reservation.get("mission_manifest_sha256")
            != mission_manifest.canonical_manifest_sha256()
            or reservation.get("prior_cycle_receipt_sha256") != previous_receipt_sha256
            or sport_key not in _ADAPTER_BY_SPORT
            or reservation.get("adapter") != _ADAPTER_BY_SPORT[cast(str, sport_key)]
            or not isinstance(reservation.get("source_plan_sha256"), str)
            or len(cast(str, reservation.get("source_plan_sha256"))) != 64
            or not isinstance(reservation.get("url"), str)
            or reservation.get("status") != "RESERVED_BEFORE_OFFICIAL_READ"
            or not isinstance(official_reads, int)
            or isinstance(official_reads, bool)
            or not 1 <= official_reads <= 2
            or not isinstance(cumulative_reads, int)
            or isinstance(cumulative_reads, bool)
            or cumulative_reads != previous_cumulative_reads + official_reads
            or cumulative_reads > _MAXIMUM_OFFICIAL_PHYSICAL_READS
            or any(
                reservation.get(field) != 0
                for field in (
                    "provider_dns",
                    "provider_tcp",
                    "provider_http",
                    "secret_reads",
                    "owner_review_pack_builds",
                )
            )
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_OFFICIAL_READ_RESERVATION_INVALID")
        _parse_utc_text(
            reservation.get("recorded_at_utc"),
            code="FIRST_C0_CANARY_OFFICIAL_READ_RESERVATION_INVALID",
        )
        reservation_sha256 = _sha256(reservation_bytes)
        if (
            set(receipt) != _ATTEMPT_RECEIPT_FIELDS
            or receipt.get("schema_version") != _ATTEMPT_RECEIPT_SCHEMA
            or receipt.get("cycle_index") != cycle_index
            or receipt.get("cycle_role") != reservation.get("cycle_role")
            or receipt.get("workspace_receipt_sha256") != workspace.canonical_receipt_hash
            or receipt.get("mission_manifest_sha256")
            != mission_manifest.canonical_manifest_sha256()
            or receipt.get("source_plan_sha256") != reservation.get("source_plan_sha256")
            or receipt.get("prior_cycle_receipt_sha256") != previous_receipt_sha256
            or receipt.get("reservation_sha256") != reservation_sha256
            or receipt.get("sport_key") != sport_key
            or receipt.get("adapter") != reservation.get("adapter")
            or receipt.get("url") != reservation.get("url")
            or receipt.get("status") not in {"SUCCEEDED", "FAILED_BEFORE_DNS", "FAILED_NO_FALLBACK"}
            or not isinstance(receipt.get("code"), str)
            or receipt.get("failure_classification") not in {None, "TRANSIENT", "DETERMINISTIC"}
            or not isinstance(receipt.get("http_status"), int)
            or isinstance(receipt.get("http_status"), bool)
            or receipt.get("official_reads") != official_reads
            or not isinstance(receipt.get("supporting_official_reads"), int)
            or isinstance(receipt.get("supporting_official_reads"), bool)
            or receipt.get("cumulative_official_reads") != cumulative_reads
            or any(
                receipt.get(field) != 0
                for field in (
                    "provider_dns",
                    "provider_tcp",
                    "provider_http",
                    "secret_reads",
                    "owner_review_pack_builds",
                )
            )
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID")
        _parse_utc_text(
            receipt.get("recorded_at_utc"),
            code="FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID",
        )
        if receipt.get("status") == "SUCCEEDED":
            if (
                receipt.get("failure_classification") is not None
                or receipt.get("fallback_category") is not None
                or receipt.get("code") not in {"CANARY_READY_NOW", "CANARY_FUTURE_WINDOW"}
                or not isinstance(receipt.get("bundle_manifest_sha256"), str)
                or len(cast(str, receipt.get("bundle_manifest_sha256"))) != 64
                or not isinstance(receipt.get("official_fetch_receipt"), dict)
            ):
                raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID")
            _parse_utc_text(
                receipt.get("recommended_refresh_utc"),
                code="FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID",
            )
            _parse_utc_text(
                receipt.get("selected_not_before_utc"),
                code="FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID",
            )
        elif (
            receipt.get("failure_classification") not in {"TRANSIENT", "DETERMINISTIC"}
            or receipt.get("recommended_refresh_utc") is not None
            or receipt.get("selected_not_before_utc") is not None
            or receipt.get("bundle_manifest_sha256") is not None
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID")
        receipt_sha256 = _sha256(receipt_bytes)
        history.append(
            FirstC0CanaryCycleHistoryV1(
                cycle_index=cycle_index,
                reservation=reservation,
                receipt=receipt,
                reservation_bytes=reservation_bytes,
                receipt_bytes=receipt_bytes,
                receipt_sha256=receipt_sha256,
            )
        )
        previous_receipt_sha256 = receipt_sha256
        previous_cumulative_reads = cumulative_reads
    return tuple(history)


def _next_cycle_authority(
    history: tuple[FirstC0CanaryCycleHistoryV1, ...],
    plan: FirstC0CanarySourcePlanV1,
    *,
    started_at_utc: datetime,
) -> tuple[int, str, int, str | None]:
    cycle_index = len(history) + 1
    if cycle_index > _MAXIMUM_PREPARATION_CYCLES:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PREPARATION_CYCLE_BUDGET_EXHAUSTED")
    if not history:
        if plan.source.sport_key != _PRIMARY_SPORT_KEY:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_PRIMARY_SOURCE_REQUIRED_FIRST")
        return cycle_index, "PRIMARY_INITIAL", 0, None

    previous = history[-1].receipt
    previous_sport = cast(str, previous["sport_key"])
    previous_plan_hash = cast(str, previous["source_plan_sha256"])
    previous_cumulative_reads = cast(int, previous["cumulative_official_reads"])
    previous_receipt_sha256 = history[-1].receipt_sha256
    if previous.get("status") == "SUCCEEDED":
        if previous.get("code") == "CANARY_READY_NOW":
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_READY_SELECTION_ALREADY_PREPARED")
        refresh_at = _parse_utc_text(
            previous.get("recommended_refresh_utc"),
            code="FIRST_C0_CANARY_ATTEMPT_RECEIPT_INVALID",
        )
        if started_at_utc < refresh_at:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_REFRESH_NOT_DUE")
        if plan.source.sport_key != previous_sport or plan.canonical_sha256 != previous_plan_hash:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_REFRESH_SOURCE_SIGNATURE_MISMATCH")
        return (
            cycle_index,
            f"{_cycle_role_prefix(previous_sport)}_REFRESH",
            previous_cumulative_reads,
            previous_receipt_sha256,
        )

    if previous.get("status") != "FAILED_BEFORE_DNS":
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_FALLBACK_NOT_AUTHORIZED")

    failure_classification = previous.get("failure_classification")
    if previous_sport == _FALLBACK_SPORT_KEY:
        same_signature_attempts = sum(
            1 for item in history if item.receipt.get("source_plan_sha256") == previous_plan_hash
        )
        if (
            failure_classification == "TRANSIENT"
            and same_signature_attempts < 2
            and plan.source.sport_key == _FALLBACK_SPORT_KEY
            and plan.canonical_sha256 == previous_plan_hash
        ):
            return (
                cycle_index,
                "FALLBACK_RETRY",
                previous_cumulative_reads,
                previous_receipt_sha256,
            )
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_FALLBACK_SOURCE_EXHAUSTED")

    same_signature_attempts = sum(
        1 for item in history if item.receipt.get("source_plan_sha256") == previous_plan_hash
    )
    if failure_classification == "TRANSIENT" and same_signature_attempts < 2:
        if (
            plan.source.sport_key != _PRIMARY_SPORT_KEY
            or plan.canonical_sha256 != previous_plan_hash
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_TRANSIENT_PRIMARY_RETRY_REQUIRED")
        return (
            cycle_index,
            "PRIMARY_RETRY",
            previous_cumulative_reads,
            previous_receipt_sha256,
        )
    if plan.source.sport_key != _FALLBACK_SPORT_KEY:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_FALLBACK_SOURCE_REQUIRED")
    if previous.get("fallback_category") not in _FALLBACK_CATEGORIES:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_FALLBACK_NOT_AUTHORIZED")
    return (
        cycle_index,
        "FALLBACK_INITIAL",
        previous_cumulative_reads,
        previous_receipt_sha256,
    )


def _write_official_read_reservation(
    workspace: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
    plan: FirstC0CanarySourcePlanV1,
    *,
    cycle_index: int,
    cycle_role: str,
    prior_cycle_receipt_sha256: str | None,
    official_reads_reserved: int,
    cumulative_official_reads_reserved: int,
    recorded_at_utc: datetime,
) -> bytes:
    payload = {
        "schema_version": _OFFICIAL_READ_RESERVATION_SCHEMA,
        "cycle_index": cycle_index,
        "cycle_role": cycle_role,
        "workspace_receipt_sha256": workspace.canonical_receipt_hash,
        "mission_manifest_sha256": mission_manifest.canonical_manifest_sha256(),
        "source_plan_sha256": plan.canonical_sha256,
        "prior_cycle_receipt_sha256": prior_cycle_receipt_sha256,
        "sport_key": plan.source.sport_key,
        "adapter": plan.source.adapter,
        "url": plan.source.url,
        "status": "RESERVED_BEFORE_OFFICIAL_READ",
        "official_reads_reserved": official_reads_reserved,
        "cumulative_official_reads_reserved": cumulative_official_reads_reserved,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,  # nosec B105
        "owner_review_pack_builds": 0,
        "recorded_at_utc": _utc_text(recorded_at_utc),
    }
    serialized = _json_bytes(payload)
    _write_exclusive(_cycle_reservation_path(workspace, cycle_index), serialized)
    return serialized


def _write_attempt_receipt(
    workspace: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
    plan: FirstC0CanarySourcePlanV1,
    *,
    cycle_index: int,
    cycle_role: str,
    prior_cycle_receipt_sha256: str | None,
    reservation_sha256: str,
    status: str,
    code: str,
    fallback_category: str | None,
    failure_classification: str | None,
    http_status: int,
    official_reads: int,
    supporting_official_reads: int,
    cumulative_official_reads: int,
    recommended_refresh_utc: datetime | None,
    selected_not_before_utc: datetime | None,
    bundle_manifest_sha256: str | None,
    official_fetch_receipt: object,
    recorded_at_utc: datetime,
) -> None:
    payload = {
        "schema_version": _ATTEMPT_RECEIPT_SCHEMA,
        "cycle_index": cycle_index,
        "cycle_role": cycle_role,
        "workspace_receipt_sha256": workspace.canonical_receipt_hash,
        "mission_manifest_sha256": mission_manifest.canonical_manifest_sha256(),
        "source_plan_sha256": plan.canonical_sha256,
        "prior_cycle_receipt_sha256": prior_cycle_receipt_sha256,
        "reservation_sha256": reservation_sha256,
        "sport_key": plan.source.sport_key,
        "adapter": plan.source.adapter,
        "url": plan.source.url,
        "status": status,
        "code": code,
        "fallback_category": fallback_category,
        "failure_classification": failure_classification,
        "http_status": http_status,
        "official_reads": official_reads,
        "supporting_official_reads": supporting_official_reads,
        "cumulative_official_reads": cumulative_official_reads,
        "recommended_refresh_utc": (
            _utc_text(recommended_refresh_utc) if recommended_refresh_utc is not None else None
        ),
        "selected_not_before_utc": (
            _utc_text(selected_not_before_utc) if selected_not_before_utc is not None else None
        ),
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "official_fetch_receipt": official_fetch_receipt,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,  # nosec B105
        "owner_review_pack_builds": 0,
        "recorded_at_utc": _utc_text(recorded_at_utc),
    }
    _write_exclusive(
        _cycle_receipt_path(workspace, cycle_index),
        _json_bytes(payload),
    )


def _publish_bundle(
    *,
    output_directory: Path,
    status: str,
    cycle_index: int,
    cumulative_official_reads: int,
    published_at_utc: datetime,
    workspace_bytes: bytes,
    mission_manifest_bytes: bytes,
    source_plan_bytes: bytes,
    source_plan: FirstC0CanarySourcePlanV1,
    raw_bytes: bytes,
    supporting_raw_bytes: tuple[bytes, ...],
    fetch_receipt: object,
    evidence: object,
    target_set: object,
    selection: FirstC0CanarySelectionV1,
    marker_inspection: Mapping[str, object],
    official_reads: int,
    history: tuple[FirstC0CanaryCycleHistoryV1, ...],
    current_reservation_bytes: bytes,
) -> tuple[Path, str]:
    staging_directory = output_directory.with_name(
        f".{output_directory.name}.staging-{selection.canonical_selection_hash[:16]}"
    )
    try:
        if os.path.lexists(output_directory) or os.path.lexists(staging_directory):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_BUNDLE_OUTPUT_EXISTS")
        staging_directory.mkdir(parents=False, exist_ok=False)
        staging_root = validate_exclusive_local_directory_identity(staging_directory)
    except FirstC0CanaryPreparationError:
        raise
    except (OSError, ValueError):
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_BUNDLE_OUTPUT_INVALID") from None
    artifacts: dict[str, bytes] = {
        "workspace-receipt.json": workspace_bytes,
        "mission-manifest.json": mission_manifest_bytes,
        "source-plan.json": source_plan_bytes,
        "official-source-raw.bin": raw_bytes,
        "official-fetch-receipt.json": _json_bytes(fetch_receipt),
        "official-schedule-evidence.json": _json_bytes(evidence),
        "fixture-target-set.json": _json_bytes(target_set),
        "first-c0-canary-selection.json": _json_bytes(selection.model_dump(mode="json")),
        "marker-inspection.json": _json_bytes(marker_inspection),
        "preparation-counters.json": _json_bytes(
            {
                "official_reads": official_reads,
                "cumulative_official_reads": cumulative_official_reads,
                "preparation_cycle": cycle_index,
                "preparation_cycles_maximum": _MAXIMUM_PREPARATION_CYCLES,
                "official_physical_reads_maximum": _MAXIMUM_OFFICIAL_PHYSICAL_READS,
                "supporting_official_reads": len(supporting_raw_bytes),
                "target_set_freezes": 1,
                "selector_invocations": 1,
                "provider_dns": 0,
                "provider_tcp": 0,
                "provider_http": 0,
                "secret_reads": 0,  # nosec B105
                "owner_review_pack_builds": 0,
            }
        ),
        "current-cycle-read-reservation.json": current_reservation_bytes,
    }
    for item in history:
        artifacts[f"prior-cycle-{item.cycle_index:02d}-read-reservation.json"] = (
            item.reservation_bytes
        )
        artifacts[f"prior-cycle-{item.cycle_index:02d}-attempt-receipt.json"] = item.receipt_bytes
    for index, payload in enumerate(supporting_raw_bytes, start=1):
        artifacts[f"official-supporting-source-raw-{index}.bin"] = payload
    artifact_hashes = {name: _sha256(payload) for name, payload in sorted(artifacts.items())}
    selected = selection.selected_candidate()
    manifest = {
        "schema_version": _BUNDLE_SCHEMA,
        "status": status,
        "preparation_cycle": cycle_index,
        "cumulative_official_reads": cumulative_official_reads,
        "preparation_cycles_maximum": _MAXIMUM_PREPARATION_CYCLES,
        "official_physical_reads_maximum": _MAXIMUM_OFFICIAL_PHYSICAL_READS,
        "published_at_utc": _utc_text(published_at_utc),
        "source_plan_sha256": source_plan.canonical_sha256,
        "sport_key": source_plan.source.sport_key,
        "official_source": source_plan.source.url,
        "workspace_receipt_sha256": selection.workspace_receipt_sha256,
        "mission_manifest_sha256": selection.mission_manifest_sha256,
        "selection_schema": selection.schema_version,
        "selection_purpose": selection.purpose,
        "selection_sha256": selection.canonical_selection_hash,
        "fixture_target_set_sha256": selected.fixture_target_set.canonical_set_hash,
        "selected_window_id": selected.window_id,
        "selected_not_before_utc": _utc_text(selection.selected_not_before_utc),
        "selected_usable_expires_at_utc": _utc_text(selected.usable_expires_at_utc),
        "maximum_http_calls": selection.maximum_http_calls,
        "maximum_credits": selection.maximum_credits,
        "markets": list(selection.markets),
        "region": selection.region,
        "production_selection_authority": selection.production_selection_authority,
        "promotion_authority": selection.promotion_authority,
        "batch_authority": selection.batch_authority,
        "scientific_edge_claim": selection.scientific_edge_claim,
        "artifact_sha256": artifact_hashes,
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,  # nosec B105
        "owner_review_pack_builds": 0,
    }
    for name, payload in artifacts.items():
        _write_exclusive(staging_root / name, payload)
    manifest_payload = _json_bytes(manifest)
    _write_exclusive(staging_root / "bundle-manifest.json", manifest_payload)
    try:
        os.rename(staging_root, output_directory)
        root = validate_exclusive_local_directory_identity(output_directory)
    except (OSError, ValueError):
        raise FirstC0CanaryPreparationError(
            "FIRST_C0_CANARY_BUNDLE_ATOMIC_PUBLISH_FAILED"
        ) from None
    return root, _sha256(manifest_payload)


def _fallback_category_for_source_error(code: str, *, stage: str) -> str:
    if code == "OFFICIAL_SCHEDULE_HORIZON_EMPTY":
        return "NO_PROSPECTIVE_FIXTURE"
    if stage == "FETCH":
        return "SOURCE_UNAVAILABLE"
    return "PARSER_FAIL_CLOSED"


def _source_failure_classification(
    error: OfficialScheduleSourceError,
) -> tuple[str, int, object]:
    receipt = error.receipt
    http_status = receipt.http_status if receipt is not None else 0
    receipt_payload: object = receipt.to_json() if receipt is not None else None
    if error.code == "OFFICIAL_SOURCE_NETWORK_FAILED" or http_status in _TRANSIENT_HTTP_STATUSES:
        return "TRANSIENT", http_status, receipt_payload
    if http_status in _DETERMINISTIC_HTTP_STATUSES or error.code:
        return "DETERMINISTIC", http_status, receipt_payload
    raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_SOURCE_FAILURE_UNCLASSIFIED")


def prepare_first_c0_canary_selection_v1(
    *,
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    workspace_receipt_bytes: bytes,
    mission_manifest: RealExecutionMissionManifestV1,
    mission_manifest_bytes: bytes,
    source_plan_bytes: bytes,
    output_directory: Path,
    fetcher: OfficialScheduleFetcher,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    workspace_validator: Callable[
        [RealCaptureWorkspaceReceiptV1], None
    ] = assert_real_capture_workspace_receipt_current_v1,
    marker_inspector: Callable[
        [RealCaptureWorkspaceReceiptV1, RealExecutionMissionManifestV1],
        Mapping[str, object],
    ] = inspect_first_c0_canary_markers_read_only_v1,
) -> FirstC0CanaryPreparationResultV1:
    try:
        if (
            RealCaptureWorkspaceReceiptV1.model_validate_json(workspace_receipt_bytes)
            != workspace_receipt
            or RealExecutionMissionManifestV1.model_validate_json(mission_manifest_bytes)
            != mission_manifest
            or not workspace_receipt.authority_eligible_for_real_execution
            or workspace_receipt.provider_http_requests != 0
            or workspace_receipt.provider_tcp_connections != 0
            or workspace_receipt.provider_secret_reads != 0
        ):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_INPUT_AUTHORITY_INVALID")
        source_plan = load_first_c0_canary_source_plan_v1(source_plan_bytes)
        workspace_validator(workspace_receipt)
        assert_workspace_control_artifact_destination_v1(workspace_receipt, output_directory)
        if os.path.lexists(output_directory):
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_BUNDLE_OUTPUT_EXISTS")
        marker_inspection = marker_inspector(workspace_receipt, mission_manifest)
        _assert_markers_absent(marker_inspection)
    except FirstC0CanaryPreparationError:
        raise
    except Exception:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_INPUT_AUTHORITY_INVALID") from None
    started_at = _utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID")
    if started_at >= mission_manifest.expires_at:
        raise FirstC0CanaryPreparationError("BOOTSTRAP_MISSION_EXPIRED")
    history = _load_cycle_history(workspace_receipt, mission_manifest)
    cycle_index, cycle_role, previous_reads, prior_cycle_receipt_sha256 = _next_cycle_authority(
        history,
        source_plan,
        started_at_utc=started_at,
    )
    sport_key = source_plan.source.sport_key
    anticipated_supporting_reads = int(source_plan.source.adapter == LALIGA_PUBLIC_MATCHES_JSON_V1)
    anticipated_reads = 1 + anticipated_supporting_reads
    cumulative_official_reads = previous_reads + anticipated_reads
    if anticipated_reads > 2 or cumulative_official_reads > _MAXIMUM_OFFICIAL_PHYSICAL_READS:
        raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_OFFICIAL_READ_BUDGET_EXHAUSTED")
    official_reads = anticipated_reads
    reservation_bytes = _write_official_read_reservation(
        workspace_receipt,
        mission_manifest,
        source_plan,
        cycle_index=cycle_index,
        cycle_role=cycle_role,
        prior_cycle_receipt_sha256=prior_cycle_receipt_sha256,
        official_reads_reserved=official_reads,
        cumulative_official_reads_reserved=cumulative_official_reads,
        recorded_at_utc=started_at,
    )
    reservation_sha256 = _sha256(reservation_bytes)
    try:
        fetch_result = fetch_official_schedule_source(
            source_plan.source,
            fetcher=fetcher,
            clock=clock,
        )
    except OfficialScheduleSourceError as error:
        failure_classification, http_status, rejected_receipt = _source_failure_classification(
            error
        )
        _write_attempt_receipt(
            workspace_receipt,
            mission_manifest,
            source_plan,
            cycle_index=cycle_index,
            cycle_role=cycle_role,
            prior_cycle_receipt_sha256=prior_cycle_receipt_sha256,
            reservation_sha256=reservation_sha256,
            status="FAILED_BEFORE_DNS",
            code=error.code,
            fallback_category=(
                _fallback_category_for_source_error(error.code, stage="FETCH")
                if sport_key == _PRIMARY_SPORT_KEY
                else None
            ),
            failure_classification=failure_classification,
            http_status=http_status,
            official_reads=official_reads,
            supporting_official_reads=anticipated_supporting_reads,
            cumulative_official_reads=cumulative_official_reads,
            recommended_refresh_utc=None,
            selected_not_before_utc=None,
            bundle_manifest_sha256=None,
            official_fetch_receipt=rejected_receipt,
            recorded_at_utc=_utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID"),
        )
        raise FirstC0CanaryPreparationError(error.code) from None
    if (
        len(fetch_result.receipt.supporting_official_reads) != anticipated_supporting_reads
        or len(fetch_result.supporting_official_raw_bytes) != anticipated_supporting_reads
    ):
        _write_attempt_receipt(
            workspace_receipt,
            mission_manifest,
            source_plan,
            cycle_index=cycle_index,
            cycle_role=cycle_role,
            prior_cycle_receipt_sha256=prior_cycle_receipt_sha256,
            reservation_sha256=reservation_sha256,
            status="FAILED_BEFORE_DNS",
            code="FIRST_C0_CANARY_OFFICIAL_SUPPORTING_READ_BUDGET_INVALID",
            fallback_category=("PARSER_FAIL_CLOSED" if sport_key == _PRIMARY_SPORT_KEY else None),
            failure_classification="DETERMINISTIC",
            http_status=fetch_result.receipt.http_status,
            official_reads=official_reads,
            supporting_official_reads=len(fetch_result.receipt.supporting_official_reads),
            cumulative_official_reads=cumulative_official_reads,
            recommended_refresh_utc=None,
            selected_not_before_utc=None,
            bundle_manifest_sha256=None,
            official_fetch_receipt=fetch_result.receipt.to_json(),
            recorded_at_utc=_utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID"),
        )
        raise FirstC0CanaryPreparationError(
            "FIRST_C0_CANARY_OFFICIAL_SUPPORTING_READ_BUDGET_INVALID"
        )
    stage = "PARSE"
    failure: FirstC0CanaryPreparationError | None
    fallback_category: str | None
    try:
        evidence = build_official_schedule_evidence(
            source_plan.source,
            fetch_result,
            horizon_not_before_utc=started_at,
            horizon_expires_at_utc=started_at + timedelta(days=OFFICIAL_SCHEDULE_HORIZON_DAYS),
        )
        stage = "FREEZE"
        frozen_at = _utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID")
        target_set = freeze_official_schedule_evidence_v1(
            evidence,
            workspace_receipt=workspace_receipt,
            created_at_utc=frozen_at,
        )
        stage = "SELECT"
        selected_at = _utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID")
        selection = FirstC0CanarySelectionV1.issue(
            selected_at_utc=selected_at,
            workspace_receipt_sha256=workspace_receipt.canonical_receipt_hash,
            workspace_prepared_at_utc=workspace_receipt.prepared_at_utc,
            mission_manifest_sha256=mission_manifest.canonical_manifest_sha256(),
            mission_expires_at_utc=mission_manifest.expires_at,
            source_target_sets=(target_set,),
        )
        selected = selection.selected_candidate()
        usable_ceiling = min(
            mission_manifest.expires_at,
            selected.usable_expires_at_utc,
            min(target.official_kickoff_utc for target in selected.fixture_target_set.targets)
            - timedelta(seconds=SAFETY_CUTOFF_SECONDS),
        )
        ready_margin = int((usable_ceiling - selected_at).total_seconds())
        if selected.status == "OPEN_SELECTABLE" and ready_margin < MINIMUM_READY_MARGIN_SECONDS:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_OPEN_MARGIN_INSUFFICIENT")
        if selected.status not in {"OPEN_SELECTABLE", "FUTURE_NOT_OPEN"}:
            raise FirstC0CanaryPreparationError("FIRST_C0_CANARY_NO_H24_H2_WINDOW")
    except OfficialScheduleSourceError as error:
        failure = FirstC0CanaryPreparationError(error.code)
        fallback_category = _fallback_category_for_source_error(error.code, stage="PARSE")
    except (TypeError, ValueError) as error:
        failure = FirstC0CanaryPreparationError(str(error) or "FIRST_C0_CANARY_SELECTION_INVALID")
        fallback_category = "NO_H24_H2_WINDOW" if stage == "SELECT" else "PARSER_FAIL_CLOSED"
    except FirstC0CanaryPreparationError as error:
        failure = error
        fallback_category = (
            "NO_H24_H2_WINDOW"
            if error.code
            in {
                "FIRST_C0_CANARY_OPEN_MARGIN_INSUFFICIENT",
                "FIRST_C0_CANARY_NO_H24_H2_WINDOW",
            }
            else None
        )
    else:
        failure = None
        fallback_category = None
    if failure is not None:
        _write_attempt_receipt(
            workspace_receipt,
            mission_manifest,
            source_plan,
            cycle_index=cycle_index,
            cycle_role=cycle_role,
            prior_cycle_receipt_sha256=prior_cycle_receipt_sha256,
            reservation_sha256=reservation_sha256,
            status=(
                "FAILED_BEFORE_DNS"
                if sport_key == _PRIMARY_SPORT_KEY and fallback_category in _FALLBACK_CATEGORIES
                else "FAILED_NO_FALLBACK"
            ),
            code=failure.code,
            fallback_category=(fallback_category if sport_key == _PRIMARY_SPORT_KEY else None),
            failure_classification="DETERMINISTIC",
            http_status=fetch_result.receipt.http_status,
            official_reads=official_reads,
            supporting_official_reads=len(fetch_result.receipt.supporting_official_reads),
            cumulative_official_reads=cumulative_official_reads,
            recommended_refresh_utc=None,
            selected_not_before_utc=None,
            bundle_manifest_sha256=None,
            official_fetch_receipt=fetch_result.receipt.to_json(),
            recorded_at_utc=_utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID"),
        )
        raise failure
    selected = selection.selected_candidate()
    status = "CANARY_READY_NOW" if selected.status == "OPEN_SELECTABLE" else "CANARY_FUTURE_WINDOW"
    # Refresh official evidence shortly before the window opens.  The refreshed
    # selection remains FUTURE until ``window_not_before_utc`` but can then be
    # promoted to the atomic PRE-DNS path without spending another read cycle.
    # Sixty seconds leaves the full 900-second H2 binding window available at
    # open while bounding how early the final official observation can occur.
    refresh = max(
        selected_at,
        selected.window_not_before_utc - timedelta(seconds=60),
    )
    published_at = _utc(clock(), code="FIRST_C0_CANARY_CLOCK_INVALID")
    root, bundle_hash = _publish_bundle(
        output_directory=output_directory,
        status=status,
        cycle_index=cycle_index,
        cumulative_official_reads=cumulative_official_reads,
        published_at_utc=published_at,
        workspace_bytes=workspace_receipt_bytes,
        mission_manifest_bytes=mission_manifest_bytes,
        source_plan_bytes=source_plan_bytes,
        source_plan=source_plan,
        raw_bytes=fetch_result.raw_bytes,
        supporting_raw_bytes=fetch_result.supporting_official_raw_bytes,
        fetch_receipt=fetch_result.receipt.to_json(),
        evidence=evidence.to_json(),
        target_set=target_set.model_dump(mode="json"),
        selection=selection,
        marker_inspection=marker_inspection,
        official_reads=official_reads,
        history=history,
        current_reservation_bytes=reservation_bytes,
    )
    _write_attempt_receipt(
        workspace_receipt,
        mission_manifest,
        source_plan,
        cycle_index=cycle_index,
        cycle_role=cycle_role,
        prior_cycle_receipt_sha256=prior_cycle_receipt_sha256,
        reservation_sha256=reservation_sha256,
        status="SUCCEEDED",
        code=status,
        fallback_category=None,
        failure_classification=None,
        http_status=fetch_result.receipt.http_status,
        official_reads=official_reads,
        supporting_official_reads=len(fetch_result.receipt.supporting_official_reads),
        cumulative_official_reads=cumulative_official_reads,
        recommended_refresh_utc=refresh,
        selected_not_before_utc=selection.selected_not_before_utc,
        bundle_manifest_sha256=bundle_hash,
        official_fetch_receipt=fetch_result.receipt.to_json(),
        recorded_at_utc=published_at,
    )
    return FirstC0CanaryPreparationResultV1(
        status=status,
        selection=selection,
        bundle_directory=root,
        bundle_manifest_sha256=bundle_hash,
        recommended_refresh_utc=refresh,
        cycle_index=cycle_index,
        official_reads=official_reads,
        cumulative_official_reads=cumulative_official_reads,
        supporting_official_reads=anticipated_supporting_reads,
        marker_inspection=marker_inspection,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-receipt", required=True, type=Path)
    parser.add_argument("--mission-manifest", required=True, type=Path)
    parser.add_argument("--source-plan", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        workspace_bytes = _read(arguments.workspace_receipt)
        workspace = RealCaptureWorkspaceReceiptV1.model_validate_json(workspace_bytes)
        assert_real_capture_workspace_receipt_current_v1(workspace)
        mission_manifest_bytes = _read(arguments.mission_manifest)
        mission_manifest = load_tracked_real_execution_mission_manifest_v1(
            Path(workspace.runtime_repository_root),
            arguments.mission_manifest,
        )
        result = prepare_first_c0_canary_selection_v1(
            workspace_receipt=workspace,
            workspace_receipt_bytes=workspace_bytes,
            mission_manifest=mission_manifest,
            mission_manifest_bytes=mission_manifest_bytes,
            source_plan_bytes=_read(
                arguments.source_plan,
                maximum_bytes=_MAXIMUM_SOURCE_PLAN_BYTES,
            ),
            output_directory=arguments.output_directory,
            fetcher=BuiltinHttpsOfficialScheduleFetcher(),
        )
    except Exception as error:
        code = getattr(error, "code", "FIRST_C0_CANARY_PREPARATION_FAILED")
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": code,
                    "provider_dns": 0,
                    "provider_tcp": 0,
                    "provider_http": 0,
                    "secret_reads": 0,  # nosec B105
                    "owner_review_pack_builds": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    selected = result.selection.selected_candidate()
    print(
        json.dumps(
            {
                "status": result.status,
                "bundle_directory": str(result.bundle_directory),
                "bundle_manifest_sha256": result.bundle_manifest_sha256,
                "selection_schema": result.selection.schema_version,
                "selection_purpose": result.selection.purpose,
                "campaign_selection_sha256": result.selection.canonical_selection_hash,
                "fixture_target_set_sha256": (selected.fixture_target_set.canonical_set_hash),
                "sport_key": result.selection.sport_key,
                "selected_window_id": selected.window_id,
                "selected_not_before_utc": _utc_text(result.selection.selected_not_before_utc),
                "selected_usable_expires_at_utc": _utc_text(selected.usable_expires_at_utc),
                "recommended_refresh_utc": _utc_text(result.recommended_refresh_utc),
                "preparation_cycle": result.cycle_index,
                "official_reads": result.official_reads,
                "cumulative_official_reads": result.cumulative_official_reads,
                "preparation_cycles_maximum": _MAXIMUM_PREPARATION_CYCLES,
                "official_physical_reads_maximum": _MAXIMUM_OFFICIAL_PHYSICAL_READS,
                "supporting_official_reads": result.supporting_official_reads,
                "provider_dns": 0,
                "provider_tcp": 0,
                "provider_http": 0,
                "secret_reads": 0,  # nosec B105
                "owner_review_pack_builds": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
