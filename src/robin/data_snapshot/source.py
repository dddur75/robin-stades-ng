"""Read-only verification of a terminal receipt-backed batch."""

from __future__ import annotations

import _socket
import http.client
import json
import os
import re
import socket
import stat
import time
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from robin.capture import (
    CaptureManifest,
    FixtureMapping,
    InternalRetentionPolicy,
    NormalizedMarketObservation,
    RawPayloadReceipt,
)
from robin.capture.normalization import (
    CaptureValidationError,
    normalize_payload,
    normalized_jsonl_bytes,
)
from robin.capture.normalization import (
    schema_fingerprint as capture_schema_fingerprint,
)
from robin.data_snapshot.contracts import (
    EXPECTED_BATCH_ID,
    EXPECTED_CAPTURE_CODE_REVISION,
    EXPECTED_CAPTURE_HARNESS_VERSION,
    EXPECTED_EXTERNAL_BATCH_DIRECTORY,
    SYNTHETIC_BATCH_ID,
    TERMINAL_MARKER_STATUSES,
    JsonObject,
    JsonValue,
    SnapshotValidationError,
    canonical_json_bytes,
    inside,
    json_object_from_bytes,
    json_value_from_bytes,
    parse_utc,
    require_array,
    require_object,
    require_sha256,
    require_string,
    safe_logical_path,
    sha256_bytes,
    sha256_file,
    utc_text,
)
from robin.data_snapshot.leak_scan import serialized_secret_or_authenticated_url_occurrences
from robin.data_snapshot.stability import (
    ContinuousTreeObservation,
    _windows_drive_type,
    continuous_tree_observer,
)

_CAPTURE_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_TECHNICAL_RECEIPT_PATH = re.compile(r"^receipts/([0-9a-f]{64})\.json$")
_LEGACY_RECEIPT_PATH = re.compile(r"^receipts/([A-Za-z][A-Za-z0-9_-]{0,31})\.json$")
_RAW_PAYLOAD_PATH = re.compile(r"^raw/sha256/([0-9a-f]{2})/([0-9a-f]{64})\.bin$")
_TECHNICAL_MANIFEST_PATH = re.compile(r"^manifests/([0-9a-f]{64})\.json$")


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    logical_path: str
    file_role: str
    size: int
    sha256: str
    capture_association: tuple[str, ...]
    receipt_association: tuple[str, ...]
    retention_status: str
    admissibility: str

    def public(self) -> JsonObject:
        return {
            "admissibility": self.admissibility,
            "capture_association": list(self.capture_association),
            "file_role": self.file_role,
            "logical_path": self.logical_path,
            "receipt_association": list(self.receipt_association),
            "retention_status": self.retention_status,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class VerifiedCapture:
    label: str
    receipt_id: str
    receipt_file_sha256: str
    raw_payload_sha256: str
    raw_payload_size: int
    request_fingerprint_sha256: str
    schema_fingerprint_sha256: str
    first_observed_at: str
    ingested_at: str
    available_at: str
    delete_after: str
    normalized_source_sha256: str | None
    quota: JsonObject
    mapping_statuses: tuple[str, ...]
    mapping_revision: str | None
    fixture_mappings: tuple[JsonObject, ...]
    raw_payload: JsonValue
    source_normalized_rows: tuple[JsonObject, ...]
    technical_harness_contract_verified: bool


@dataclass(frozen=True, slots=True)
class VerifiedBatch:
    batch_id: str
    finalized_at: str
    source_manifest_sha256: str
    source_manifest_logical_path: str
    source_manifest: JsonObject
    finalized_marker_sha256: str
    sha256sums_sha256: str
    inventory: tuple[InventoryEntry, ...]
    captures: tuple[VerifiedCapture, ...]
    capture_windows: tuple[JsonObject, ...]
    selected_fixtures: tuple[JsonObject, ...]
    retention_policy_sha256: str
    capture_code_revision: str
    capture_harness_version: str
    leak_tokens: Mapping[str, frozenset[bytes]]
    network_attempts: int
    secret_reads: int
    stable_observation_seconds: int


@dataclass(frozen=True, slots=True)
class _ReceiptInventory:
    technical: bool
    payload_sha256s: frozenset[str]
    normalized_paths: frozenset[str]


class NetworkBlockade:
    """Turn standard-library socket, DNS and HTTP attempts into a hard failure."""

    def __init__(self) -> None:
        self.attempts = 0
        self._restorers: list[Callable[[], None]] = []

    def _forbidden(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.attempts += 1
        raise SnapshotValidationError("FROZEN_SNAPSHOT_NETWORK_FORBIDDEN")

    def _patch(self, owner: object, name: str) -> None:
        if not hasattr(owner, name):
            return
        original = getattr(owner, name)
        setattr(owner, name, self._forbidden)
        self._restorers.append(lambda: setattr(owner, name, original))

    def __enter__(self) -> NetworkBlockade:
        if self._restorers:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_NETWORK_BLOCKADE_REENTERED")
        try:
            for owner, names in (
                (
                    socket.socket,
                    (
                        "accept",
                        "bind",
                        "connect",
                        "connect_ex",
                        "ioctl",
                        "listen",
                        "recv",
                        "recv_into",
                        "recvfrom",
                        "recvfrom_into",
                        "recvmsg",
                        "recvmsg_into",
                        "send",
                        "sendall",
                        "sendfile",
                        "sendmsg",
                        "sendmsg_afalg",
                        "sendto",
                        "shutdown",
                    ),
                ),
                (
                    socket,
                    (
                        "create_connection",
                        "create_server",
                        "fromfd",
                        "fromshare",
                        "getaddrinfo",
                        "gethostbyaddr",
                        "gethostbyname",
                        "gethostbyname_ex",
                        "getnameinfo",
                        "SocketType",
                        "socketpair",
                    ),
                ),
                (
                    _socket,
                    (
                        "getaddrinfo",
                        "gethostbyaddr",
                        "gethostbyname",
                        "gethostbyname_ex",
                        "getnameinfo",
                        "SocketType",
                        "socketpair",
                        "socket",
                    ),
                ),
                (http.client.HTTPConnection, ("connect", "request", "send")),
                (http.client.HTTPSConnection, ("connect",)),
                (urllib.request, ("urlopen", "urlretrieve")),
            ):
                for name in names:
                    self._patch(owner, name)
        except BaseException:
            self._restore()
            raise
        return self

    def _restore(self) -> None:
        while self._restorers:
            self._restorers.pop()()

    def __exit__(self, *args: object) -> None:
        del args
        self._restore()


def _first(mapping: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _consistent_alias(
    mapping: Mapping[str, Any],
    names: tuple[str, ...],
    *,
    code: str,
) -> Any:
    declared = [mapping[name] for name in names if name in mapping]
    if not declared:
        return None
    if any(value != declared[0] for value in declared[1:]):
        raise SnapshotValidationError(code)
    return declared[0]


def _role(logical_path: str) -> str:
    lowered = logical_path.casefold()
    if lowered == "finalized.json":
        return "FINALIZATION_MARKER"
    if lowered == "sha256sums.txt":
        return "INTEGRITY_INDEX"
    if lowered.startswith("raw/sha256/"):
        return "RAW_CONTENT_ADDRESSED_PAYLOAD"
    if lowered.startswith("receipts/") or lowered.endswith("receipts.jsonl"):
        return "CAPTURE_RECEIPT"
    if lowered.startswith("normalized/"):
        return "NORMALIZED_DERIVATION"
    if "manifest" in lowered:
        return "MANIFEST"
    if "retention" in lowered or "deletion" in lowered:
        return "RETENTION_EVIDENCE"
    if "schema" in lowered or "coverage" in lowered or "quota" in lowered:
        return "DERIVED_EVIDENCE"
    return "SUPPORTING_EVIDENCE"


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    junction = getattr(path, "is_junction", None)
    return (
        path.is_symlink()
        or (callable(junction) and bool(junction()))
        or bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    )


def _is_remote_drive(path: Path) -> bool:
    if os.name != "nt":
        return False
    drive, _tail = os.path.splitdrive(os.path.abspath(os.fspath(path)))
    if not drive:
        return False
    return bool(_windows_drive_type(f"{drive}\\") == 4)


def _reject_reparse_path(path: Path) -> None:
    """Reject a reparse point anywhere in the lexical path before content reads."""

    absolute = path.absolute()
    for component in reversed((absolute, *absolute.parents)):
        if _is_reparse_point(component):
            raise SnapshotValidationError("BATCH_REPARSE_POINT_FORBIDDEN")


def _batch_files(root: Path) -> tuple[Path, ...]:
    _reject_reparse_path(root)
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            raise SnapshotValidationError("BATCH_DIRECTORY_SCAN_FAILED") from None
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                raise SnapshotValidationError("BATCH_ENTRY_STAT_FAILED") from None
            if entry.is_symlink() or bool(
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise SnapshotValidationError("BATCH_REPARSE_POINT_FORBIDDEN")
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                raise SnapshotValidationError("BATCH_SPECIAL_FILE_FORBIDDEN")
    return tuple(sorted(files))


def _reject_reparse_components(root: Path, logical_path: str) -> None:
    _reject_reparse_path(root)
    current = root
    for part in Path(logical_path).parts:
        current /= part
        if _is_reparse_point(current):
            raise SnapshotValidationError("BATCH_REPARSE_POINT_FORBIDDEN")


def _tree_state(root: Path) -> tuple[tuple[str, int, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            path.stat().st_size,
            sha256_file(path),
        )
        for path in _batch_files(root)
    )


def _parse_sha256sums(value: bytes) -> dict[str, str]:
    try:
        lines = value.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise SnapshotValidationError("BATCH_SHA256SUMS_INVALID") from None
    result: dict[str, str] = {}
    for line in lines:
        digest, separator, raw_path = line.partition("  ")
        logical_path = safe_logical_path(raw_path, code="BATCH_SHA256SUMS_PATH_INVALID")
        if not separator or logical_path in result:
            raise SnapshotValidationError("BATCH_SHA256SUMS_INVALID")
        result[logical_path] = require_sha256(digest, code="BATCH_SHA256SUMS_INVALID")
    if not result:
        raise SnapshotValidationError("BATCH_SHA256SUMS_EMPTY")
    return result


def _marker_contract(marker: JsonObject) -> tuple[str, str, str, str]:
    status = require_string(
        _consistent_alias(
            marker,
            ("status", "state", "final_status"),
            code="FINALIZED_MARKER_STATUS_INVALID",
        ),
        code="FINALIZED_MARKER_STATUS_INVALID",
    ).upper()
    if status not in TERMINAL_MARKER_STATUSES:
        raise SnapshotValidationError("FINALIZED_MARKER_NOT_TERMINAL")
    batch_id = require_string(
        _consistent_alias(
            marker,
            ("batch_id", "source_batch_id", "mission_id"),
            code="FINALIZED_MARKER_BATCH_ID_MISSING",
        ),
        code="FINALIZED_MARKER_BATCH_ID_MISSING",
    )
    manifest_path_value = _consistent_alias(
        marker,
        (
            "manifest_path",
            "batch_manifest_path",
            "source_manifest_path",
            "capture_manifest_path",
        ),
        code="FINALIZED_MARKER_MANIFEST_PATH_INVALID",
    )
    manifest_path = safe_logical_path(
        manifest_path_value if manifest_path_value is not None else "capture-manifest.json",
        code="FINALIZED_MARKER_MANIFEST_PATH_INVALID",
    )
    manifest_sha = require_sha256(
        _consistent_alias(
            marker,
            (
                "manifest_sha256",
                "batch_manifest_sha256",
                "source_manifest_sha256",
                "capture_manifest_sha256",
            ),
            code="FINALIZED_MARKER_MANIFEST_SHA256_INVALID",
        ),
        code="FINALIZED_MARKER_MANIFEST_SHA256_INVALID",
    )
    finalized_at = utc_text(
        parse_utc(
            _consistent_alias(
                marker,
                ("finalized_at", "completed_at", "created_at"),
                code="FINALIZED_MARKER_TIME_INVALID",
            ),
            code="FINALIZED_MARKER_TIME_INVALID",
        )
    )
    return batch_id, manifest_path, manifest_sha, finalized_at


def _require_real_terminal_manifest(manifest: Mapping[str, Any], batch_id: str) -> None:
    terminal_status = manifest.get("status")
    terminal_captures = manifest.get("captures")
    terminal_selections = manifest.get("selected_fixtures")
    terminal_windows = manifest.get("capture_windows")
    if (
        manifest.get("batch_id") != batch_id
        or not isinstance(terminal_status, str)
        or terminal_status.upper() not in TERMINAL_MARKER_STATUSES
        or not isinstance(terminal_captures, list)
        or len(terminal_captures) != 5
        or not all(isinstance(item, dict) for item in terminal_captures)
        or not isinstance(terminal_selections, list)
        or len(terminal_selections) != 5
        or not isinstance(terminal_windows, list)
        or not terminal_windows
        or not all(isinstance(item, dict) for item in terminal_windows)
    ):
        raise SnapshotValidationError("REAL_BATCH_TERMINAL_MANIFEST_CONTRACT_INVALID")


def _capture_metadata(manifest: Mapping[str, Any], label: str) -> dict[str, Any]:
    for key in ("captures", "capture_plan", "capture_schedule", "capture_windows"):
        value = manifest.get(key)
        if isinstance(value, dict):
            candidate = value.get(label)
            if isinstance(candidate, dict):
                return cast(dict[str, Any], candidate)
        if isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                candidate = cast(dict[str, Any], item)
                item_label = _first(candidate, ("capture_label", "capture_code", "label", "id"))
                if item_label == label:
                    return candidate
    return {}


def _capture_metadata_for_receipt(
    manifest: Mapping[str, Any],
    *,
    receipt_id: str,
    raw_payload_sha256: str | None,
    snapshot_id: str | None,
    technical_receipt: RawPayloadReceipt | None = None,
    technical_manifest: CaptureManifest | None = None,
) -> dict[str, Any]:
    candidates: list[tuple[str | None, dict[str, Any]]] = []
    metadata_keys = (
        ("captures",)
        if technical_receipt is not None and technical_manifest is not None
        else ("captures", "capture_plan", "capture_schedule", "capture_windows")
    )
    for key in metadata_keys:
        value = manifest.get(key)
        if isinstance(value, dict):
            candidates.extend(
                (str(label), cast(dict[str, Any], item))
                for label, item in value.items()
                if isinstance(item, dict)
            )
        elif isinstance(value, list):
            candidates.extend(
                (None, cast(dict[str, Any], item)) for item in value if isinstance(item, dict)
            )
    if technical_receipt is not None and technical_manifest is not None:
        expected_groups: tuple[tuple[tuple[str, ...], object, bool], ...] = (
            (("receipt_id",), technical_receipt.receipt_id, False),
            (
                ("raw_payload_sha256", "payload_sha256"),
                technical_receipt.payload_sha256,
                False,
            ),
            (("snapshot_id", "capture_snapshot_id"), technical_manifest.snapshot_id, False),
            (
                ("normalized_path", "normalized_storage_key"),
                technical_manifest.normalized_storage_key,
                False,
            ),
            (
                ("normalized_sha256", "normalized_payload_sha256"),
                technical_manifest.normalized_sha256,
                False,
            ),
            (
                ("normalized_observation_count", "observation_count"),
                technical_manifest.observation_count,
                False,
            ),
            (
                ("request_fingerprint_sha256", "request_sha256"),
                technical_receipt.request_fingerprint_sha256,
                False,
            ),
            (
                ("schema_fingerprint_sha256", "schema_sha256"),
                technical_manifest.schema_fingerprint.schema_sha256,
                False,
            ),
            (("captured_at",), technical_manifest.captured_at, True),
            (("robin_first_observed_at",), technical_receipt.robin_first_observed_at, True),
            (("robin_ingested_at",), technical_receipt.robin_ingested_at, True),
            (("available_at",), technical_receipt.available_at, True),
            (("delete_after", "raw_expires_at"), technical_receipt.raw_expires_at, True),
        )

        def matches_expected(value: object, expected: object, temporal: bool) -> bool:
            if not temporal:
                return type(value) is type(expected) and value == expected
            try:
                return parse_utc(value, code="CAPTURE_TERMINAL_MANIFEST_TIME_INVALID") == expected
            except SnapshotValidationError:
                return False

        related: list[tuple[str | None, dict[str, Any]]] = []
        related = [
            (keyed_label, candidate)
            for keyed_label, candidate in candidates
            if candidate.get("receipt_id") == technical_receipt.receipt_id
        ]
        if not related:
            raise SnapshotValidationError("CAPTURE_TERMINAL_MANIFEST_ENTRY_REQUIRED")
        if len(related) != 1:
            raise SnapshotValidationError("CAPTURE_TERMINAL_MANIFEST_ENTRY_DUPLICATED")
        keyed_label, candidate = related[0]
        for aliases, expected, temporal in expected_groups:
            for alias in aliases:
                if alias in candidate and not matches_expected(
                    candidate[alias], expected, temporal
                ):
                    raise SnapshotValidationError("CAPTURE_TERMINAL_MANIFEST_BINDING_MISMATCH")
        if keyed_label is not None:
            for alias in ("capture_label", "capture_code", "label"):
                if alias in candidate and candidate[alias] != keyed_label:
                    raise SnapshotValidationError("CAPTURE_TERMINAL_MANIFEST_BINDING_MISMATCH")
        result = dict(candidate)
        if keyed_label is not None:
            result.setdefault("capture_label", keyed_label)
        return result

    for keyed_label, candidate in candidates:
        matches = (
            candidate.get("receipt_id") == receipt_id
            or (
                raw_payload_sha256 is not None
                and _first(candidate, ("raw_payload_sha256", "payload_sha256"))
                == raw_payload_sha256
            )
            or (
                snapshot_id is not None
                and _first(candidate, ("snapshot_id", "capture_snapshot_id")) == snapshot_id
            )
        )
        if matches:
            result = dict(candidate)
            if keyed_label is not None:
                result.setdefault("capture_label", keyed_label)
            return result
    return {}


def _mapping_status(value: Mapping[str, Any]) -> str:
    """Normalize only explicit failure states; declarations can never self-prove a mapping."""

    raw = str(_first(value, ("mapping_status", "status")) or "").upper()
    if raw in {
        "FIXTURE_MAPPING_AMBIGUOUS",
        "FIXTURE_MAPPING_UNPROVEN",
        "FIXTURE_MAPPING_CONFLICT",
    }:
        return raw
    if raw in {"AMBIGUOUS", "MAPPING_AMBIGUOUS"}:
        return "FIXTURE_MAPPING_AMBIGUOUS"
    if raw in {"CONFLICT", "MAPPING_CONFLICT"}:
        return "FIXTURE_MAPPING_CONFLICT"
    return "FIXTURE_MAPPING_UNPROVEN"


def _mapping_declarations(
    owner: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...] | None:
    candidate = _first(owner, ("fixture_mappings", "mappings", "fixture_mapping"))
    if candidate is None:
        return None
    if isinstance(candidate, Mapping):
        return (candidate,)
    if not isinstance(candidate, list) or not all(isinstance(item, Mapping) for item in candidate):
        raise SnapshotValidationError("FIXTURE_MAPPING_DECLARATION_INVALID")
    return tuple(cast(Mapping[str, Any], item) for item in candidate)


def _technical_mapping_index(
    values: tuple[Mapping[str, Any], ...],
    *,
    code: str,
) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    required = {
        "candidate_fixture_ids",
        "fixture_id",
        "mapping_revision",
        "provider_event_id",
        "status",
    }
    for value in values:
        if not required <= set(value):
            raise SnapshotValidationError(code)
        material = {name: value[name] for name in required}
        try:
            mapping = FixtureMapping.model_validate(material)
        except (ValidationError, ValueError):
            raise SnapshotValidationError(code) from None
        normalized = mapping.model_dump(mode="json")
        provider_event_id = mapping.provider_event_id
        if provider_event_id in result:
            raise SnapshotValidationError(code)
        result[provider_event_id] = normalized
    return result


def _selected_fixture_canonical(value: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    sport_key = value.get("sport_key")
    kickoff = value.get("kickoff_at")
    home = value.get("home_team")
    away = value.get("away_team")
    if not all(isinstance(item, str) and item for item in (sport_key, kickoff, home, away)):
        return None
    try:
        kickoff_utc = utc_text(parse_utc(kickoff, code="FIXTURE_SELECTED_KICKOFF_INVALID"))
    except SnapshotValidationError:
        return None
    return str(sport_key), kickoff_utc, str(home), str(away)


def _raw_event_canonical(value: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    sport_key = value.get("sport_key")
    kickoff = value.get("commence_time")
    home = value.get("home_team")
    away = value.get("away_team")
    if not all(isinstance(item, str) and item for item in (sport_key, kickoff, home, away)):
        return None
    try:
        kickoff_utc = utc_text(parse_utc(kickoff, code="FIXTURE_RAW_KICKOFF_INVALID"))
    except SnapshotValidationError:
        return None
    return str(sport_key), kickoff_utc, str(home), str(away)


def _selected_fixture_evidence_indexes(
    selected_fixtures: tuple[JsonObject, ...],
) -> (
    tuple[
        dict[str, JsonObject],
        dict[str, JsonObject],
        dict[tuple[str, str, str, str], JsonObject],
    ]
    | None
):
    """Index a complete candidate universe or reject it entirely as non-probative."""

    if not selected_fixtures:
        return None
    by_fixture: dict[str, JsonObject] = {}
    by_provider: dict[str, JsonObject] = {}
    by_canonical: dict[tuple[str, str, str, str], JsonObject] = {}
    for selected in selected_fixtures:
        fixture_id = selected.get("fixture_id")
        provider_event_id = selected.get("provider_event_id")
        canonical = _selected_fixture_canonical(selected)
        if (
            not isinstance(fixture_id, str)
            or not fixture_id
            or not isinstance(provider_event_id, str)
            or not provider_event_id
            or canonical is None
            or fixture_id in by_fixture
            or provider_event_id in by_provider
            or canonical in by_canonical
        ):
            return None
        by_fixture[fixture_id] = selected
        by_provider[provider_event_id] = selected
        by_canonical[canonical] = selected
    return by_fixture, by_provider, by_canonical


def _mapping_proven_from_bound_evidence(
    mapping: Mapping[str, Any],
    *,
    raw_events: tuple[JsonObject, ...],
    selected_fixtures: tuple[JsonObject, ...],
) -> bool:
    """Recalculate the six mapping predicates from hash-bound canonical evidence."""

    if mapping.get("status") != "MAPPED":
        return False
    fixture_id = mapping.get("fixture_id")
    provider_event_id = mapping.get("provider_event_id")
    candidate_fixture_ids = mapping.get("candidate_fixture_ids")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id
        or not isinstance(provider_event_id, str)
        or not provider_event_id
        or candidate_fixture_ids != [fixture_id]
    ):
        return False
    selected_indexes = _selected_fixture_evidence_indexes(selected_fixtures)
    if selected_indexes is None:
        return False
    selected_by_fixture, selected_by_provider, selected_by_canonical = selected_indexes
    selected = selected_by_fixture.get(fixture_id)
    selected_for_provider = selected_by_provider.get(provider_event_id)
    raw_provider_matches = [event for event in raw_events if event.get("id") == provider_event_id]
    if (
        selected is None
        or selected_for_provider is None
        or selected_for_provider.get("fixture_id") != fixture_id
        or len(raw_provider_matches) != 1
    ):
        return False
    selected_canonical = _selected_fixture_canonical(selected)
    raw_canonical = _raw_event_canonical(raw_provider_matches[0])
    if selected_canonical is None or raw_canonical != selected_canonical:
        return False
    selected_for_canonical = selected_by_canonical.get(raw_canonical)
    raw_candidates = [
        event for event in raw_events if _raw_event_canonical(event) == selected_canonical
    ]
    return (
        selected_for_canonical is not None
        and selected_for_canonical.get("fixture_id") == fixture_id
        and len(raw_candidates) == 1
        and raw_candidates[0].get("id") == provider_event_id
    )


def _mapping_contracts(
    batch_manifest: Mapping[str, Any],
    metadata: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    expected_provider_event_ids: set[str],
    raw_events: tuple[JsonObject, ...],
    selected_fixtures: tuple[JsonObject, ...],
    technical_mappings: tuple[FixtureMapping, ...] | None,
) -> tuple[tuple[str, ...], str | None, tuple[JsonObject, ...]]:
    revision: str | None = None
    technical_index: dict[str, JsonObject] | None = None
    values: tuple[Mapping[str, Any], ...]
    if technical_mappings is not None:
        technical_values = tuple(
            cast(Mapping[str, Any], mapping.model_dump(mode="json"))
            for mapping in technical_mappings
        )
        technical_index = _technical_mapping_index(
            technical_values,
            code="FIXTURE_MAPPING_TECHNICAL_CONTRACT_INVALID",
        )
        if set(technical_index) != expected_provider_event_ids:
            raise SnapshotValidationError("FIXTURE_MAPPING_TECHNICAL_EVENT_SET_MISMATCH")
        for owner in (metadata, batch_manifest, receipt):
            declarations = _mapping_declarations(owner)
            if declarations is None:
                continue
            declared_index = _technical_mapping_index(
                declarations,
                code="FIXTURE_MAPPING_TECHNICAL_CONTRACT_MISMATCH",
            )
            if declared_index != technical_index:
                raise SnapshotValidationError("FIXTURE_MAPPING_TECHNICAL_CONTRACT_MISMATCH")
        technical_revisions = {
            str(mapping["mapping_revision"]) for mapping in technical_index.values()
        }
        for owner in (metadata, batch_manifest):
            declared_revision = _first(owner, ("mapping_revision", "fixture_mapping_revision"))
            if declared_revision is not None and technical_revisions != {declared_revision}:
                raise SnapshotValidationError("FIXTURE_MAPPING_TECHNICAL_CONTRACT_MISMATCH")
        revision = next(iter(technical_revisions)) if len(technical_revisions) == 1 else None
        values = tuple(technical_index[key] for key in sorted(technical_index))
    else:
        values = ()
        for owner in (metadata, receipt, batch_manifest):
            declarations = _mapping_declarations(owner)
            if declarations is not None:
                values = declarations
                break
        revision_value = _first(metadata, ("mapping_revision", "fixture_mapping_revision"))
        if revision_value is None:
            revision_value = _first(receipt, ("mapping_revision", "fixture_mapping_revision"))
        revision = (
            str(revision_value) if isinstance(revision_value, str) and revision_value else None
        )
    by_provider_event: dict[str, JsonObject] = {}
    for value in values:
        provider_event_value = _first(value, ("provider_event_id", "event_id"))
        if not isinstance(provider_event_value, str) or not provider_event_value:
            raise SnapshotValidationError("FIXTURE_MAPPING_PROVIDER_EVENT_ID_REQUIRED")
        if (
            provider_event_value not in expected_provider_event_ids
            or provider_event_value in by_provider_event
        ):
            raise SnapshotValidationError("FIXTURE_MAPPING_PROVIDER_EVENT_ID_INVALID")
        status = (
            "FIXTURE_MAPPING_PROVEN"
            if technical_index is not None
            and _mapping_proven_from_bound_evidence(
                value,
                raw_events=raw_events,
                selected_fixtures=selected_fixtures,
            )
            else _mapping_status(value)
        )
        fixture_value = value.get("fixture_id")
        fixture_id = fixture_value if isinstance(fixture_value, str) and fixture_value else None
        if status == "FIXTURE_MAPPING_PROVEN" and fixture_id is None:
            raise SnapshotValidationError("FIXTURE_MAPPING_PROVEN_FIXTURE_ID_REQUIRED")
        by_provider_event[provider_event_value] = {
            "candidate_fixture_ids": list(value.get("candidate_fixture_ids", [])),
            "fixture_id": fixture_id,
            "mapping_revision": _first(value, ("mapping_revision",)) or revision,
            "provider_event_id": provider_event_value,
            "status": status,
        }
    for provider_event_id in expected_provider_event_ids - set(by_provider_event):
        by_provider_event[provider_event_id] = {
            "candidate_fixture_ids": [],
            "fixture_id": None,
            "mapping_revision": revision,
            "provider_event_id": provider_event_id,
            "status": "FIXTURE_MAPPING_UNPROVEN",
        }
    proven_fixture_ids = [
        str(item["fixture_id"])
        for item in by_provider_event.values()
        if item["status"] == "FIXTURE_MAPPING_PROVEN"
    ]
    if len(proven_fixture_ids) != len(set(proven_fixture_ids)):
        raise SnapshotValidationError("FIXTURE_MAPPING_PROVEN_FIXTURE_ID_NOT_UNIQUE")
    mappings = tuple(by_provider_event[key] for key in sorted(by_provider_event))
    statuses = tuple(sorted({str(item["status"]) for item in mappings}))
    return statuses, revision, mappings


def _read_jsonl(value: bytes, *, code: str) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        rows.append(json_object_from_bytes(line, code=code))
    return tuple(rows)


def _contains_secret_or_authenticated_url(value: bytes) -> bool:
    return serialized_secret_or_authenticated_url_occurrences(value) > 0


def _manifest_for_receipt(root: Path, receipt_id: str) -> tuple[JsonObject, str] | None:
    manifest_root = root / "manifests"
    if not manifest_root.is_dir():
        return None
    matches: list[tuple[JsonObject, str]] = []
    for path in sorted(manifest_root.glob("*.json")):
        document = json_object_from_bytes(path.read_bytes(), code="CAPTURE_MANIFEST_INVALID")
        if document.get("receipt_id") == receipt_id:
            matches.append((document, path.relative_to(root).as_posix()))
    if len(matches) > 1:
        raise SnapshotValidationError("CAPTURE_TECHNICAL_MANIFEST_DUPLICATED")
    return matches[0] if matches else None


def _verify_intake_receipt(root: Path, receipt: RawPayloadReceipt) -> None:
    intake_id = receipt.intake_receipt_id
    if intake_id is None:
        raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_REQUIRED")
    intake_relative = f"receipts/{intake_id}.json"
    intake_path = inside(root, intake_relative, code="CAPTURE_INTAKE_RECEIPT_PATH_INVALID")
    try:
        intake_bytes = intake_path.read_bytes()
    except FileNotFoundError:
        raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_MISSING") from None
    if intake_path.stem != intake_id:
        raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_PATH_IDENTITY_MISMATCH")
    try:
        intake = RawPayloadReceipt.model_validate_json(intake_bytes)
    except (ValidationError, ValueError):
        raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_CONTRACT_INVALID") from None
    if (
        intake.receipt_id != intake_id
        or intake.admission_status.value != "INTAKE_PENDING"
        or intake.intake_receipt_id is not None
        or intake.request_fingerprint_sha256 != receipt.request_fingerprint_sha256
        or intake.payload_sha256 != receipt.payload_sha256
        or intake.payload_byte_length != receipt.payload_byte_length
        or intake.http_status != receipt.http_status
        or intake.robin_first_observed_at != receipt.robin_first_observed_at
        or intake.robin_ingested_at != receipt.robin_ingested_at
        or intake.available_at != receipt.available_at
        or intake.raw_expires_at != receipt.raw_expires_at
        or intake.raw_storage_key != receipt.raw_storage_key
    ):
        raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_LINK_MISMATCH")


def _require_real_admitted_receipt_contract(
    receipt: RawPayloadReceipt,
    document: Mapping[str, Any],
) -> None:
    if type(document.get("http_status")) is not int or receipt.http_status != 200:
        raise SnapshotValidationError("REAL_BATCH_ADMITTED_HTTP_STATUS_INVALID")
    quota = receipt.quota
    raw_quota = document.get("quota")
    quota_counts = (
        tuple(
            raw_quota.get(name) for name in ("requests_last", "requests_remaining", "requests_used")
        )
        if isinstance(raw_quota, dict)
        else ()
    )
    if (
        quota is None
        or not isinstance(raw_quota, dict)
        or len(quota_counts) != 3
        or any(type(value) is not int or value < 0 for value in quota_counts)
        or quota.requests_last is None
        or quota.requests_remaining is None
        or quota.requests_used is None
        or quota.requests_used < quota.requests_last
        or raw_quota.get("observed_at") != utc_text(receipt.robin_ingested_at)
        or quota.observed_at != receipt.robin_ingested_at
    ):
        raise SnapshotValidationError("REAL_BATCH_QUOTA_EVIDENCE_REQUIRED")
    if receipt.schema_fingerprint_sha256 is None or receipt.raw_storage_key is None:
        raise SnapshotValidationError("REAL_BATCH_ADMITTED_EVIDENCE_INCOMPLETE")


def _validated_receipt_inventory(
    root: Path,
    receipt_documents: list[tuple[Path, JsonObject]],
    *,
    logical_paths: Iterable[str],
    expected_batch_id: str,
    source_manifest_logical_path: str,
) -> _ReceiptInventory:
    all_logical_paths = tuple(logical_paths)
    receipt_like_paths = {
        logical
        for logical in all_logical_paths
        if logical.casefold().startswith("receipts/")
        or logical.casefold().endswith("receipts.jsonl")
    }
    parsed_paths = {path.relative_to(root).as_posix() for path, _document in receipt_documents}
    if receipt_like_paths != parsed_paths:
        raise SnapshotValidationError("BATCH_RECEIPT_PATH_GRAMMAR_INVALID")
    dialects = {
        "technical" if "receipt_id" in document else "legacy" for _, document in receipt_documents
    }
    if len(dialects) > 1:
        raise SnapshotValidationError("BATCH_RECEIPT_DIALECT_MIXED")
    technical = dialects == {"technical"}
    if not technical:
        if expected_batch_id != SYNTHETIC_BATCH_ID:
            raise SnapshotValidationError("REAL_BATCH_PR59_RECEIPT_CONTRACT_REQUIRED")
        payload_sha256s: set[str] = set()
        normalized_paths: set[str] = set()
        for path, document in receipt_documents:
            logical = path.relative_to(root).as_posix()
            match = _LEGACY_RECEIPT_PATH.fullmatch(logical)
            if match is None:
                raise SnapshotValidationError("BATCH_RECEIPT_PATH_GRAMMAR_INVALID")
            raw_sha = require_sha256(
                _first(document, ("raw_payload_sha256", "payload_sha256")),
                code="CAPTURE_RAW_SHA256_INVALID",
            )
            payload_sha256s.add(raw_sha)
            normalized = _first(document, ("normalized_path", "normalized_storage_key"))
            if normalized is not None:
                normalized_paths.add(
                    safe_logical_path(
                        normalized,
                        code="CAPTURE_NORMALIZED_REFERENCE_INVALID",
                    )
                )
        return _ReceiptInventory(
            technical=False,
            payload_sha256s=frozenset(payload_sha256s),
            normalized_paths=frozenset(normalized_paths),
        )

    receipts_by_id: dict[str, RawPayloadReceipt] = {}
    for path, document in receipt_documents:
        logical = path.relative_to(root).as_posix()
        match = _TECHNICAL_RECEIPT_PATH.fullmatch(logical)
        if match is None:
            raise SnapshotValidationError("BATCH_RECEIPT_PATH_GRAMMAR_INVALID")
        try:
            receipt = RawPayloadReceipt.model_validate(document)
        except (ValidationError, ValueError):
            raise SnapshotValidationError("CAPTURE_RECEIPT_CONTRACT_INVALID") from None
        if match.group(1) != receipt.receipt_id or path.stem != receipt.receipt_id:
            raise SnapshotValidationError("CAPTURE_RECEIPT_FILENAME_IDENTITY_MISMATCH")
        if receipt.receipt_id in receipts_by_id:
            raise SnapshotValidationError("BATCH_DUPLICATE_RECEIPT_ID")
        receipts_by_id[receipt.receipt_id] = receipt

    finals = tuple(
        receipt
        for receipt in receipts_by_id.values()
        if receipt.admission_status.value == "ADMITTED"
    )
    expected_receipt_ids: set[str] = set()
    referenced_intakes: set[str] = set()
    for final in finals:
        intake_id = final.intake_receipt_id
        if intake_id is None:
            raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_REQUIRED")
        if intake_id in referenced_intakes:
            raise SnapshotValidationError("BATCH_RECEIPT_DISPOSITION_INVALID")
        intake = receipts_by_id.get(intake_id)
        if intake is None:
            raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_MISSING")
        if intake.admission_status.value != "INTAKE_PENDING":
            raise SnapshotValidationError("BATCH_RECEIPT_DISPOSITION_INVALID")
        referenced_intakes.add(intake_id)
        expected_receipt_ids.update((final.receipt_id, intake_id))
        if expected_batch_id != SYNTHETIC_BATCH_ID:
            _require_real_admitted_receipt_contract(
                final,
                next(
                    document
                    for _path, document in receipt_documents
                    if document.get("receipt_id") == final.receipt_id
                ),
            )
    if set(receipts_by_id) != expected_receipt_ids:
        raise SnapshotValidationError("BATCH_RECEIPT_DISPOSITION_INVALID")

    actual_manifest_paths = {
        logical
        for logical in all_logical_paths
        if logical.casefold().startswith("manifests/") and logical != source_manifest_logical_path
    }
    if len(actual_manifest_paths) != len(finals) or any(
        _TECHNICAL_MANIFEST_PATH.fullmatch(logical) is None for logical in actual_manifest_paths
    ):
        raise SnapshotValidationError("BATCH_TECHNICAL_MANIFEST_DISPOSITION_MISMATCH")
    technical_normalized_paths: set[str] = set()
    technical_manifest_paths: set[str] = set()
    for final in finals:
        capture_manifest = _manifest_for_receipt(root, final.receipt_id)
        if capture_manifest is None:
            raise SnapshotValidationError("CAPTURE_TECHNICAL_MANIFEST_REQUIRED")
        try:
            parsed_manifest = CaptureManifest.model_validate(capture_manifest[0])
        except (ValidationError, ValueError):
            raise SnapshotValidationError("CAPTURE_MANIFEST_CONTRACT_INVALID") from None
        if parsed_manifest.receipt_id != final.receipt_id:
            raise SnapshotValidationError("CAPTURE_MANIFEST_RECEIPT_BINDING_MISMATCH")
        expected_manifest_path = f"manifests/{parsed_manifest.snapshot_id}.json"
        if capture_manifest[1] != expected_manifest_path:
            raise SnapshotValidationError("CAPTURE_MANIFEST_PATH_IDENTITY_MISMATCH")
        technical_manifest_paths.add(expected_manifest_path)
        technical_normalized_paths.add(parsed_manifest.normalized_storage_key)
    if actual_manifest_paths != technical_manifest_paths:
        raise SnapshotValidationError("BATCH_TECHNICAL_MANIFEST_DISPOSITION_MISMATCH")
    return _ReceiptInventory(
        technical=True,
        payload_sha256s=frozenset(receipt.payload_sha256 for receipt in receipts_by_id.values()),
        normalized_paths=frozenset(technical_normalized_paths),
    )


def _raw_payload_paths(logical_paths: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for logical in logical_paths:
        if not logical.casefold().startswith("raw/"):
            continue
        match = _RAW_PAYLOAD_PATH.fullmatch(logical)
        if match is None or match.group(1) != match.group(2)[:2]:
            raise SnapshotValidationError("BATCH_RAW_PATH_GRAMMAR_INVALID")
        result[logical] = match.group(2)
    return result


def _verified_capture(
    root: Path,
    receipt_path: Path,
    receipt: JsonObject,
    manifest: JsonObject,
) -> VerifiedCapture | None:
    receipt_bytes = receipt_path.read_bytes()
    receipt_file_sha = sha256_bytes(receipt_bytes)
    receipt_id_value = receipt.get("receipt_id")
    receipt_id = (
        require_sha256(receipt_id_value, code="CAPTURE_RECEIPT_ID_INVALID")
        if receipt_id_value is not None
        else receipt_file_sha
    )
    technical_receipt: RawPayloadReceipt | None = None
    technical_capture_manifest: CaptureManifest | None = None
    technical_manifest: JsonObject = {}
    if receipt_id_value is not None:
        if receipt_path.stem != receipt_id:
            raise SnapshotValidationError("CAPTURE_RECEIPT_FILENAME_IDENTITY_MISMATCH")
        try:
            technical_receipt = RawPayloadReceipt.model_validate(receipt)
        except (ValidationError, ValueError):
            raise SnapshotValidationError("CAPTURE_RECEIPT_CONTRACT_INVALID") from None
        admission = str(receipt.get("admission_status") or "").upper()
        if admission != "ADMITTED":
            return None
        _verify_intake_receipt(root, technical_receipt)
        capture_manifest = _manifest_for_receipt(root, receipt_id)
        if capture_manifest is None:
            raise SnapshotValidationError("CAPTURE_TECHNICAL_MANIFEST_REQUIRED")
        technical_manifest = capture_manifest[0]
        try:
            technical_capture_manifest = CaptureManifest.model_validate(technical_manifest)
        except (ValidationError, ValueError):
            raise SnapshotValidationError("CAPTURE_MANIFEST_CONTRACT_INVALID") from None
        if technical_capture_manifest.receipt_id != technical_receipt.receipt_id:
            raise SnapshotValidationError("CAPTURE_MANIFEST_RECEIPT_BINDING_MISMATCH")
        expected_manifest_path = f"manifests/{technical_capture_manifest.snapshot_id}.json"
        if capture_manifest[1] != expected_manifest_path:
            raise SnapshotValidationError("CAPTURE_MANIFEST_PATH_IDENTITY_MISMATCH")
    else:
        if receipt.get("status") != "CAPTURED_AND_REPLAYED" or receipt.get("http_status") != 200:
            raise SnapshotValidationError("CAPTURE_LEGACY_RECEIPT_CONTRACT_INVALID")

    raw_sha_hint = _first(receipt, ("raw_payload_sha256", "payload_sha256"))
    metadata = _capture_metadata_for_receipt(
        manifest,
        receipt_id=receipt_id,
        raw_payload_sha256=raw_sha_hint if isinstance(raw_sha_hint, str) else None,
        snapshot_id=(
            technical_capture_manifest.snapshot_id
            if technical_capture_manifest is not None
            else None
        ),
        technical_receipt=technical_receipt,
        technical_manifest=technical_capture_manifest,
    )
    label_value = _first(receipt, ("capture_label", "capture_code", "label"))
    if label_value is None:
        label_value = _first(metadata, ("capture_label", "capture_code", "label", "id"))
    if label_value is None and receipt_id_value is None:
        label_value = receipt_path.stem
    label = require_string(label_value, code="CAPTURE_LABEL_INVALID")
    if _CAPTURE_LABEL.fullmatch(label) is None:
        raise SnapshotValidationError("CAPTURE_LABEL_INVALID")
    if not metadata:
        metadata = _capture_metadata(manifest, label)

    raw_relative = safe_logical_path(
        _first(receipt, ("raw_payload_path", "raw_storage_key")),
        code="CAPTURE_RAW_REFERENCE_INVALID",
    )
    raw_path = inside(root, raw_relative, code="CAPTURE_RAW_PATH_ESCAPES_BATCH")
    expected_raw_sha = require_sha256(
        _first(receipt, ("raw_payload_sha256", "payload_sha256")),
        code="CAPTURE_RAW_SHA256_INVALID",
    )
    if raw_relative != f"raw/sha256/{expected_raw_sha[:2]}/{expected_raw_sha}.bin":
        raise SnapshotValidationError("CAPTURE_RAW_REFERENCE_INVALID")
    raw_bytes = raw_path.read_bytes()
    if sha256_bytes(raw_bytes) != expected_raw_sha:
        raise SnapshotValidationError("CAPTURE_RAW_HASH_MISMATCH")
    size_value = _first(receipt, ("raw_payload_bytes", "payload_byte_length"))
    if (
        not isinstance(size_value, int)
        or isinstance(size_value, bool)
        or size_value != len(raw_bytes)
    ):
        raise SnapshotValidationError("CAPTURE_RAW_LENGTH_MISMATCH")
    if technical_receipt is not None and (
        technical_receipt.payload_sha256 != expected_raw_sha
        or technical_receipt.payload_byte_length != len(raw_bytes)
    ):
        raise SnapshotValidationError("CAPTURE_TECHNICAL_RECEIPT_RAW_BINDING_MISMATCH")
    raw_payload = json_value_from_bytes(raw_bytes, code="CAPTURE_RAW_JSON_INVALID")
    if not isinstance(raw_payload, list):
        raise SnapshotValidationError("CAPTURE_RAW_ROOT_NOT_ARRAY")

    request_fingerprint = require_sha256(
        _first(receipt, ("request_fingerprint_sha256", "request_sha256")),
        code="CAPTURE_REQUEST_FINGERPRINT_INVALID",
    )
    request_value = receipt.get("request")
    if (
        request_value is not None
        and sha256_bytes(canonical_json_bytes(request_value)) != request_fingerprint
    ):
        raise SnapshotValidationError("CAPTURE_REQUEST_FINGERPRINT_MISMATCH")
    if technical_capture_manifest is not None and (
        technical_capture_manifest.request_fingerprint_sha256 != request_fingerprint
        or technical_capture_manifest.raw_payload_sha256 != expected_raw_sha
    ):
        raise SnapshotValidationError("CAPTURE_MANIFEST_REQUEST_RAW_BINDING_MISMATCH")

    technical_schema = technical_manifest.get("schema_fingerprint")
    technical_schema_sha = (
        cast(dict[str, Any], technical_schema).get("schema_sha256")
        if isinstance(technical_schema, dict)
        else None
    )
    schema_fingerprint = require_sha256(
        _first(receipt, ("schema_fingerprint_sha256", "schema_sha256")) or technical_schema_sha,
        code="CAPTURE_SCHEMA_FINGERPRINT_INVALID",
    )
    computed_schema_fingerprint = capture_schema_fingerprint(raw_payload)
    if (
        technical_capture_manifest is not None
        and computed_schema_fingerprint.schema_sha256 != schema_fingerprint
    ):
        raise SnapshotValidationError("CAPTURE_SCHEMA_FINGERPRINT_RAW_MISMATCH")
    if technical_capture_manifest is not None and (
        technical_receipt is None
        or technical_receipt.schema_fingerprint_sha256 != schema_fingerprint
        or technical_capture_manifest.schema_fingerprint.schema_sha256 != schema_fingerprint
        or technical_capture_manifest.schema_fingerprint.paths_and_types
        != computed_schema_fingerprint.paths_and_types
    ):
        raise SnapshotValidationError("CAPTURE_SCHEMA_FINGERPRINT_BINDING_MISMATCH")
    first = parse_utc(receipt.get("robin_first_observed_at"), code="CAPTURE_FIRST_OBSERVED_INVALID")
    ingested = parse_utc(receipt.get("robin_ingested_at"), code="CAPTURE_INGESTED_AT_INVALID")
    available = parse_utc(
        receipt.get("available_at", receipt.get("robin_first_observed_at")),
        code="CAPTURE_AVAILABLE_AT_INVALID",
    )
    delete_after = parse_utc(
        _first(receipt, ("delete_after", "raw_expires_at")),
        code="CAPTURE_DELETE_AFTER_INVALID",
    )
    if ingested < first or available < first:
        raise SnapshotValidationError("CAPTURE_TEMPORAL_ORDER_INVALID")
    if delete_after not in {first + timedelta(days=30), ingested + timedelta(days=30)}:
        raise SnapshotValidationError("CAPTURE_RETENTION_TTL_INVALID")
    if (
        technical_capture_manifest is not None
        and technical_capture_manifest.captured_at != ingested
    ):
        raise SnapshotValidationError("CAPTURE_MANIFEST_CAPTURED_AT_MISMATCH")

    normalized_relative_value = _first(
        receipt,
        ("normalized_path", "normalized_storage_key"),
    )
    if normalized_relative_value is None:
        normalized_relative_value = technical_manifest.get("normalized_storage_key")
    if normalized_relative_value is None:
        candidate = f"normalized/{label}-market-observations.jsonl"
        normalized_relative_value = candidate if (root / candidate).is_file() else None
    normalized_rows: tuple[JsonObject, ...] = ()
    normalized_sha: str | None = None
    normalized_bytes: bytes | None = None
    if normalized_relative_value is not None:
        normalized_relative = safe_logical_path(
            normalized_relative_value, code="CAPTURE_NORMALIZED_REFERENCE_INVALID"
        )
        normalized_path = inside(
            root, normalized_relative, code="CAPTURE_NORMALIZED_PATH_ESCAPES_BATCH"
        )
        normalized_bytes = normalized_path.read_bytes()
        normalized_sha = sha256_bytes(normalized_bytes)
        expected_normalized = _first(
            technical_manifest,
            ("normalized_sha256", "normalized_payload_sha256"),
        ) or _first(receipt, ("normalized_sha256", "normalized_payload_sha256"))
        if expected_normalized is not None and normalized_sha != require_sha256(
            expected_normalized, code="CAPTURE_NORMALIZED_SHA256_INVALID"
        ):
            raise SnapshotValidationError("CAPTURE_NORMALIZED_HASH_MISMATCH")
        normalized_rows = _read_jsonl(normalized_bytes, code="CAPTURE_NORMALIZED_JSONL_INVALID")
        expected_count = _first(technical_manifest, ("observation_count",))
        if expected_count is None:
            expected_count = _first(receipt, ("normalized_observation_count", "observation_count"))
        if expected_count is not None and (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count != len(normalized_rows)
        ):
            raise SnapshotValidationError("CAPTURE_NORMALIZED_COUNT_MISMATCH")
        for row in normalized_rows:
            if technical_capture_manifest is not None:
                try:
                    technical_observation = NormalizedMarketObservation.model_validate(row)
                except (ValidationError, ValueError):
                    raise SnapshotValidationError("CAPTURE_NORMALIZED_CONTRACT_INVALID") from None
                if (
                    technical_observation.receipt_id != receipt_id
                    or technical_observation.snapshot_id != technical_capture_manifest.snapshot_id
                    or technical_observation.payload_sha256 != expected_raw_sha
                ):
                    raise SnapshotValidationError("CAPTURE_NORMALIZED_TECHNICAL_BINDING_MISMATCH")
            if _first(row, ("raw_payload_sha256", "payload_sha256")) != expected_raw_sha:
                raise SnapshotValidationError("CAPTURE_NORMALIZED_RAW_BINDING_MISMATCH")
            normalized_receipt = row.get("receipt_id")
            if normalized_receipt is not None and normalized_receipt != receipt_id:
                raise SnapshotValidationError("CAPTURE_NORMALIZED_RECEIPT_BINDING_MISMATCH")
            normalized_label = _first(row, ("capture_label", "capture_code"))
            if normalized_label is not None and normalized_label != label:
                raise SnapshotValidationError("CAPTURE_NORMALIZED_LABEL_BINDING_MISMATCH")
        if technical_capture_manifest is not None and (
            technical_capture_manifest.normalized_sha256 != normalized_sha
            or technical_capture_manifest.observation_count != len(normalized_rows)
            or technical_capture_manifest.schema_fingerprint.schema_sha256 != schema_fingerprint
        ):
            raise SnapshotValidationError("CAPTURE_MANIFEST_NORMALIZED_BINDING_MISMATCH")
        if technical_capture_manifest is not None:
            if technical_receipt is None:
                raise SnapshotValidationError("CAPTURE_RECEIPT_CONTRACT_INVALID")
            try:
                replayed_schema, replayed_rows = normalize_payload(
                    raw_payload,
                    receipt=technical_receipt,
                    mappings=technical_capture_manifest.fixture_mappings,
                )
            except CaptureValidationError:
                raise SnapshotValidationError("CAPTURE_NORMALIZED_REPLAY_INVALID") from None
            if (
                replayed_schema != technical_capture_manifest.schema_fingerprint
                or normalized_jsonl_bytes(replayed_rows) != normalized_bytes
            ):
                raise SnapshotValidationError("CAPTURE_NORMALIZED_REPLAY_MISMATCH")

    quota_value = receipt.get("quota")
    if isinstance(quota_value, dict):
        quota = quota_value
    else:
        quota = {
            "requests_last": receipt.get("x_requests_last"),
            "requests_remaining": receipt.get("x_requests_remaining"),
            "requests_used": receipt.get("x_requests_used"),
        }
    raw_events = tuple(
        require_object(event, code="CAPTURE_EVENT_INVALID")
        for event in require_array(raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY")
    )
    provider_event_values = [
        require_string(event.get("id"), code="CAPTURE_EVENT_IDENTITY_INVALID")
        for event in raw_events
    ]
    provider_event_ids = set(provider_event_values)
    if len(provider_event_ids) != len(provider_event_values):
        raise SnapshotValidationError("CAPTURE_DUPLICATE_PROVIDER_EVENT_ID")
    mapping_statuses, mapping_revision, fixture_mappings = _mapping_contracts(
        manifest,
        metadata,
        receipt,
        expected_provider_event_ids=provider_event_ids,
        raw_events=raw_events,
        selected_fixtures=_selected_fixtures(manifest),
        technical_mappings=(
            technical_capture_manifest.fixture_mappings
            if technical_capture_manifest is not None
            else None
        ),
    )
    return VerifiedCapture(
        label=label,
        receipt_id=receipt_id,
        receipt_file_sha256=receipt_file_sha,
        raw_payload_sha256=expected_raw_sha,
        raw_payload_size=len(raw_bytes),
        request_fingerprint_sha256=request_fingerprint,
        schema_fingerprint_sha256=schema_fingerprint,
        first_observed_at=utc_text(first),
        ingested_at=utc_text(ingested),
        available_at=utc_text(available),
        delete_after=utc_text(delete_after),
        normalized_source_sha256=normalized_sha,
        quota=quota,
        mapping_statuses=mapping_statuses,
        mapping_revision=mapping_revision,
        fixture_mappings=fixture_mappings,
        raw_payload=raw_payload,
        source_normalized_rows=normalized_rows,
        technical_harness_contract_verified=technical_receipt is not None,
    )


def _capture_windows(manifest: Mapping[str, Any]) -> tuple[JsonObject, ...]:
    result: list[JsonObject] = []
    for key in ("capture_windows", "windows", "window_evidence"):
        if key not in manifest:
            continue
        value = manifest[key]
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise SnapshotValidationError("CAPTURE_WINDOWS_CONTRACT_INVALID")
        result.extend(cast(JsonObject, item) for item in value)
        break
    if not result:
        captures = manifest.get("captures")
        if isinstance(captures, list):
            for item in captures:
                if not isinstance(item, dict):
                    raise SnapshotValidationError("CAPTURE_WINDOWS_CONTRACT_INVALID")
                candidate = cast(dict[str, Any], item)
                windows = _first(candidate, ("windows", "capture_windows"))
                if windows is None:
                    continue
                if not isinstance(windows, list) or not all(
                    isinstance(window, dict) for window in windows
                ):
                    raise SnapshotValidationError("CAPTURE_WINDOWS_CONTRACT_INVALID")
                for window in windows:
                    merged = dict(cast(dict[str, Any], window))
                    merged.setdefault(
                        "capture_label",
                        _first(candidate, ("capture_label", "capture_code", "label")),
                    )
                    result.append(merged)
    identities: set[tuple[object, ...]] = set()
    for window in result:
        receipt_claim = _consistent_alias(
            window,
            ("receipt_id", "capture_receipt_id", "receipt"),
            code="CAPTURE_WINDOW_RECEIPT_ALIAS_CONFLICT",
        )
        if receipt_claim is not None:
            require_sha256(receipt_claim, code="CAPTURE_WINDOW_RECEIPT_ID_INVALID")
        temporal_role = window.get("temporal_role")
        if not isinstance(temporal_role, str) or temporal_role not in {
            "PREDICTOR",
            "TARGET",
            "UNSPECIFIED",
        }:
            raise SnapshotValidationError("CAPTURE_WINDOW_TEMPORAL_ROLE_INVALID")
        earliest_admissible = _consistent_alias(
            window,
            ("earliest_admissible", "window_start", "start"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        latest_admissible = _consistent_alias(
            window,
            ("latest_admissible", "window_end", "end"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        kickoff = _consistent_alias(
            window,
            ("kickoff", "kickoff_at", "commence_time"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        for timestamp, code in (
            (earliest_admissible, "CAPTURE_WINDOW_EARLIEST_ADMISSIBLE_INVALID"),
            (latest_admissible, "CAPTURE_WINDOW_LATEST_ADMISSIBLE_INVALID"),
            (kickoff, "CAPTURE_WINDOW_KICKOFF_INVALID"),
        ):
            parsed = parse_utc(timestamp, code=code)
            if timestamp != utc_text(parsed):
                raise SnapshotValidationError(code)
        identity = (
            _consistent_alias(
                window,
                ("capture_label", "capture_code", "capture", "label"),
                code="CAPTURE_WINDOW_ALIAS_CONFLICT",
            ),
            _consistent_alias(
                window,
                ("fixture_id", "selected_fixture_id"),
                code="CAPTURE_WINDOW_ALIAS_CONFLICT",
            ),
            _consistent_alias(
                window,
                ("provider_event_id", "event_id"),
                code="CAPTURE_WINDOW_ALIAS_CONFLICT",
            ),
            temporal_role,
            _consistent_alias(
                window,
                ("window_id", "claimed_window", "window"),
                code="CAPTURE_WINDOW_ALIAS_CONFLICT",
            ),
            earliest_admissible,
            latest_admissible,
            kickoff,
        )
        if any(
            not isinstance(value, str) or not value
            for index, value in enumerate(identity)
            if index != 2 or value is not None
        ):
            raise SnapshotValidationError("CAPTURE_WINDOW_IDENTITY_INVALID")
        logical_identity = (identity[0], identity[1], identity[3], identity[4])
        if logical_identity in identities:
            raise SnapshotValidationError("CAPTURE_WINDOW_IDENTITY_DUPLICATED")
        identities.add(logical_identity)
    return tuple(sorted(result, key=lambda item: canonical_json_bytes(item)))


def _selected_fixtures(manifest: Mapping[str, Any]) -> tuple[JsonObject, ...]:
    value = _first(manifest, ("selected_fixtures", "fixtures", "fixture_selection"))
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SnapshotValidationError("BATCH_SELECTED_FIXTURES_CONTRACT_INVALID")
    result: list[JsonObject] = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            result.append(cast(JsonObject, item))
        elif isinstance(item, str):
            result.append({"fixture_id": item, "selection_index": index})
        else:
            raise SnapshotValidationError("BATCH_SELECTED_FIXTURES_CONTRACT_INVALID")
    identities = {
        canonical_json_bytes(
            {key: item for key, item in fixture.items() if key != "selection_index"}
        )
        for fixture in result
    }
    if len(identities) != len(result):
        raise SnapshotValidationError("BATCH_SELECTED_FIXTURE_DUPLICATED")
    return tuple(result)


def _require_real_selected_fixtures(
    selected_fixtures: tuple[JsonObject, ...],
) -> None:
    selected_fixture_ids = [fixture.get("fixture_id") for fixture in selected_fixtures]
    selected_provider_ids = [
        fixture.get("provider_event_id")
        for fixture in selected_fixtures
        if "provider_event_id" in fixture
    ]
    if (
        len(selected_fixtures) != 5
        or any(
            not isinstance(fixture_id, str) or not fixture_id for fixture_id in selected_fixture_ids
        )
        or len(set(cast(list[str], selected_fixture_ids))) != 5
        or any(
            not isinstance(provider_id, str) or not provider_id
            for provider_id in selected_provider_ids
        )
        or len(set(cast(list[str], selected_provider_ids))) != len(selected_provider_ids)
    ):
        raise SnapshotValidationError("REAL_BATCH_FIVE_SELECTED_FIXTURES_REQUIRED")


def _leak_tokens(captures: Iterable[VerifiedCapture]) -> dict[str, frozenset[bytes]]:
    values: dict[str, set[bytes]] = {
        "provider_event_ids": set(),
        "team_names": set(),
        "bookmaker_identities": set(),
        "price_fragments": set(),
    }
    for capture in captures:
        for event_value in require_array(capture.raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY"):
            event = require_object(event_value, code="CAPTURE_EVENT_INVALID")
            event_id = event.get("id")
            if isinstance(event_id, str) and event_id:
                values["provider_event_ids"].add(event_id.encode())
            for name in (event.get("home_team"), event.get("away_team")):
                if isinstance(name, str) and name:
                    values["team_names"].add(name.encode())
            bookmakers = event.get("bookmakers")
            if not isinstance(bookmakers, list):
                continue
            for bookmaker_value in bookmakers:
                if not isinstance(bookmaker_value, dict):
                    continue
                bookmaker = cast(dict[str, Any], bookmaker_value)
                for identity in (bookmaker.get("key"), bookmaker.get("title")):
                    if isinstance(identity, str) and identity:
                        values["bookmaker_identities"].add(identity.encode())
                markets = bookmaker.get("markets")
                if not isinstance(markets, list):
                    continue
                for market_value in markets:
                    if not isinstance(market_value, dict):
                        continue
                    outcomes = cast(dict[str, Any], market_value).get("outcomes")
                    if not isinstance(outcomes, list):
                        continue
                    for outcome_value in outcomes:
                        if not isinstance(outcome_value, dict):
                            continue
                        price = cast(dict[str, Any], outcome_value).get("price")
                        fragment = json.dumps(price, separators=(",", ":"))
                        values["price_fragments"].update(
                            {
                                f'"price":{fragment}'.encode(),
                                f'"outcome_price":{fragment}'.encode(),
                            }
                        )
    return {key: frozenset(items) for key, items in values.items()}


def _scan_source_for_credentials(root: Path) -> None:
    for path in _batch_files(root):
        value = path.read_bytes()
        if _contains_secret_or_authenticated_url(value):
            raise SnapshotValidationError("BATCH_SECRET_OR_AUTHENTICATED_URL_DETECTED")


def verify_finalized_batch(
    root: Path,
    *,
    expected_batch_id: str = EXPECTED_BATCH_ID,
    observation_seconds: int = 300,
    sleeper: Callable[[float], None] = time.sleep,
    test_only_allow_short_observation: bool = False,
) -> VerifiedBatch:
    """Read FINALIZED first, then validate every admitted byte without mutation."""

    return _verify_finalized_batch_impl(
        root,
        expected_batch_id=expected_batch_id,
        observation_seconds=observation_seconds,
        sleeper=sleeper,
        test_only_allow_short_observation=test_only_allow_short_observation,
        continuous_observation=None,
    )


def _verify_finalized_batch_impl(
    root: Path,
    *,
    expected_batch_id: str,
    observation_seconds: int,
    sleeper: Callable[[float], None],
    test_only_allow_short_observation: bool,
    continuous_observation: ContinuousTreeObservation | None,
) -> VerifiedBatch:

    if observation_seconds < 0:
        raise SnapshotValidationError("FINALIZED_OBSERVATION_SECONDS_INVALID")
    if test_only_allow_short_observation:
        if expected_batch_id != SYNTHETIC_BATCH_ID:
            raise SnapshotValidationError("FINALIZED_OBSERVATION_TEST_BYPASS_REAL_BATCH_FORBIDDEN")
    elif expected_batch_id != EXPECTED_BATCH_ID:
        raise SnapshotValidationError("BATCH_ID_OVERRIDE_FORBIDDEN")
    if observation_seconds < 300 and not test_only_allow_short_observation:
        raise SnapshotValidationError("FINALIZED_OBSERVATION_FIVE_MINUTES_REQUIRED")
    if sleeper is not time.sleep and not test_only_allow_short_observation:
        raise SnapshotValidationError("FINALIZED_OBSERVATION_CUSTOM_SLEEPER_FORBIDDEN")
    lexical_root = os.fspath(root).replace("/", "\\")
    if lexical_root.startswith("\\\\"):
        raise SnapshotValidationError("BATCH_SOURCE_NETWORK_SHARE_FORBIDDEN")
    unresolved = Path(os.path.abspath(os.fspath(root)))
    if expected_batch_id == EXPECTED_BATCH_ID:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            raise SnapshotValidationError("BATCH_SOURCE_LOCALAPPDATA_REQUIRED")
        expected_source = Path(
            os.path.abspath(Path(local_appdata) / "Robin" / EXPECTED_EXTERNAL_BATCH_DIRECTORY)
        )
        if os.path.normcase(os.fspath(unresolved)) != os.path.normcase(os.fspath(expected_source)):
            raise SnapshotValidationError("BATCH_SOURCE_APPROVED_ROOT_MISMATCH")
    if _is_remote_drive(unresolved):
        raise SnapshotValidationError("BATCH_SOURCE_NETWORK_SHARE_FORBIDDEN")
    _reject_reparse_path(unresolved)
    resolved = unresolved.resolve()
    # A marker link is invalid batch structure, not a watcher-arm failure.  Check
    # its metadata before arming the observer; no source bytes are read here.
    _reject_reparse_components(resolved, "FINALIZED.json")
    if continuous_observation is None:
        with continuous_tree_observer(resolved) as observation:
            return _verify_finalized_batch_impl(
                root,
                expected_batch_id=expected_batch_id,
                observation_seconds=observation_seconds,
                sleeper=sleeper,
                test_only_allow_short_observation=test_only_allow_short_observation,
                continuous_observation=observation,
            )
    marker_path = resolved / "FINALIZED.json"
    _reject_reparse_components(resolved, "FINALIZED.json")
    if not marker_path.is_file():
        raise SnapshotValidationError("FINALIZED_MARKER_REQUIRED")

    # This is deliberately the first file read beneath the source workspace.
    marker_bytes = marker_path.read_bytes()
    marker = json_object_from_bytes(marker_bytes, code="FINALIZED_MARKER_INVALID")
    batch_id, manifest_logical, expected_manifest_sha, finalized_at = _marker_contract(marker)
    if batch_id != expected_batch_id:
        raise SnapshotValidationError("FINALIZED_MARKER_BATCH_ID_MISMATCH")

    manifest_path = inside(
        resolved, manifest_logical, code="FINALIZED_MARKER_MANIFEST_PATH_INVALID"
    )
    _reject_reparse_components(resolved, manifest_logical)
    manifest_bytes = manifest_path.read_bytes()
    if sha256_bytes(manifest_bytes) != expected_manifest_sha:
        raise SnapshotValidationError("FINALIZED_MANIFEST_HASH_MISMATCH")
    manifest = json_object_from_bytes(manifest_bytes, code="BATCH_MANIFEST_INVALID")
    manifest_batch_id = _consistent_alias(
        manifest,
        ("batch_id", "source_batch_id", "mission_id"),
        code="BATCH_MANIFEST_IDENTITY_MISMATCH",
    )
    if manifest_batch_id is not None and manifest_batch_id != batch_id:
        raise SnapshotValidationError("BATCH_MANIFEST_IDENTITY_MISMATCH")
    if expected_batch_id != SYNTHETIC_BATCH_ID:
        _require_real_terminal_manifest(manifest, batch_id)

    before = _tree_state(resolved)
    continuous_observation.assert_unchanged()
    sha_path_value = _consistent_alias(
        marker,
        ("sha256sums_path", "integrity_index_path"),
        code="BATCH_SHA256SUMS_PATH_INVALID",
    )
    sha_logical = safe_logical_path(
        sha_path_value if sha_path_value is not None else "sha256sums.txt",
        code="BATCH_SHA256SUMS_PATH_INVALID",
    )
    sha_path = inside(resolved, sha_logical, code="BATCH_SHA256SUMS_PATH_INVALID")
    _reject_reparse_components(resolved, sha_logical)
    sha_bytes = sha_path.read_bytes()
    declared = _parse_sha256sums(sha_bytes)
    state_map = {logical: (size, digest) for logical, size, digest in before}
    if (
        state_map.get("FINALIZED.json", (0, ""))[1] != sha256_bytes(marker_bytes)
        or state_map.get(manifest_logical, (0, ""))[1] != expected_manifest_sha
        or state_map.get(sha_logical, (0, ""))[1] != sha256_bytes(sha_bytes)
    ):
        raise SnapshotValidationError("FINALIZED_BATCH_MUTATED")
    for logical, expected in declared.items():
        actual = state_map.get(logical)
        if actual is None or actual[1] != expected:
            raise SnapshotValidationError("BATCH_SHA256SUMS_INTEGRITY_FAILURE")
    exempt = {"FINALIZED.json", sha_logical}
    orphans = set(state_map) - set(declared) - exempt
    if orphans:
        raise SnapshotValidationError("BATCH_ORPHAN_FILE_DETECTED")

    receipt_root = resolved / "receipts"
    if not receipt_root.is_dir():
        raise SnapshotValidationError("BATCH_RECEIPTS_DIRECTORY_REQUIRED")
    receipt_documents: list[tuple[Path, JsonObject]] = []
    for receipt_path in sorted(receipt_root.glob("*.json")):
        receipt_documents.append(
            (
                receipt_path,
                json_object_from_bytes(receipt_path.read_bytes(), code="CAPTURE_RECEIPT_INVALID"),
            )
        )
    receipt_inventory = _validated_receipt_inventory(
        resolved,
        receipt_documents,
        logical_paths=(logical for logical, _size, _digest in before),
        expected_batch_id=expected_batch_id,
        source_manifest_logical_path=manifest_logical,
    )
    captures = tuple(
        capture
        for receipt_path, receipt in receipt_documents
        if (capture := _verified_capture(resolved, receipt_path, receipt, manifest)) is not None
    )
    if not captures:
        raise SnapshotValidationError("BATCH_ADMITTED_CAPTURE_REQUIRED")
    if expected_batch_id != SYNTHETIC_BATCH_ID and not all(
        capture.technical_harness_contract_verified for capture in captures
    ):
        raise SnapshotValidationError("REAL_BATCH_PR59_RECEIPT_CONTRACT_REQUIRED")
    if expected_batch_id != SYNTHETIC_BATCH_ID and len(captures) != 5:
        raise SnapshotValidationError("REAL_BATCH_FIVE_ADMITTED_CAPTURES_REQUIRED")
    if len({capture.receipt_id for capture in captures}) != len(captures):
        raise SnapshotValidationError("BATCH_DUPLICATE_RECEIPT_ID")
    if len({capture.label for capture in captures}) != len(captures):
        raise SnapshotValidationError("BATCH_DUPLICATE_CAPTURE_LABEL")
    finalized_time = parse_utc(finalized_at, code="FINALIZED_MARKER_TIME_INVALID")
    manifest_finalized_at = _consistent_alias(
        manifest,
        ("finalized_at", "completed_at"),
        code="BATCH_MANIFEST_FINALIZED_AT_MISMATCH",
    )
    if manifest_finalized_at is not None and utc_text(
        parse_utc(manifest_finalized_at, code="BATCH_MANIFEST_FINALIZED_AT_INVALID")
    ) != utc_text(finalized_time):
        raise SnapshotValidationError("BATCH_MANIFEST_FINALIZED_AT_MISMATCH")
    latest_capture_time = max(
        parse_utc(timestamp, code="CAPTURE_TEMPORAL_ORDER_INVALID")
        for capture in captures
        for timestamp in (capture.ingested_at, capture.available_at)
    )
    if finalized_time < latest_capture_time:
        raise SnapshotValidationError("FINALIZED_MARKER_PRECEDES_CAPTURE")
    selected_fixtures = _selected_fixtures(manifest)
    selected_identities = {
        canonical_json_bytes(
            {key: value for key, value in fixture.items() if key != "selection_index"}
        )
        for fixture in selected_fixtures
    }
    if expected_batch_id != SYNTHETIC_BATCH_ID:
        if len(selected_identities) != 5:
            raise SnapshotValidationError("REAL_BATCH_FIVE_SELECTED_FIXTURES_REQUIRED")
        _require_real_selected_fixtures(selected_fixtures)
    capture_windows = _capture_windows(manifest)
    if expected_batch_id != SYNTHETIC_BATCH_ID and not capture_windows:
        raise SnapshotValidationError("REAL_BATCH_CAPTURE_WINDOWS_REQUIRED")
    receipts_by_capture_label = {capture.label: capture.receipt_id for capture in captures}
    fixture_pairs = {
        (mapping.get("fixture_id"), mapping.get("provider_event_id"))
        for capture in captures
        for mapping in capture.fixture_mappings
        if isinstance(mapping.get("fixture_id"), str)
        and isinstance(mapping.get("provider_event_id"), str)
    }
    fixtures_by_provider: dict[str, set[str]] = {}
    providers_by_fixture: dict[str, set[str]] = {}
    for fixture_id, provider_event_id in fixture_pairs:
        fixture = cast(str, fixture_id)
        provider = cast(str, provider_event_id)
        fixtures_by_provider.setdefault(provider, set()).add(fixture)
        providers_by_fixture.setdefault(fixture, set()).add(provider)
    for window in capture_windows:
        capture_label_value = _consistent_alias(
            window,
            ("capture_label", "capture_code", "capture", "label"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        receipt_claim = _consistent_alias(
            window,
            ("receipt_id", "capture_receipt_id", "receipt"),
            code="CAPTURE_WINDOW_RECEIPT_ALIAS_CONFLICT",
        )
        if (
            receipt_claim is not None
            and receipts_by_capture_label.get(cast(str, capture_label_value)) != receipt_claim
        ):
            raise SnapshotValidationError("CAPTURE_WINDOW_RECEIPT_BINDING_MISMATCH")
        fixture_value = _consistent_alias(
            window,
            ("fixture_id", "selected_fixture_id"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        provider_value = _consistent_alias(
            window,
            ("provider_event_id", "event_id"),
            code="CAPTURE_WINDOW_ALIAS_CONFLICT",
        )
        if isinstance(fixture_value, str) and isinstance(provider_value, str):
            if (
                (fixture_value, provider_value) not in fixture_pairs
                or fixtures_by_provider.get(provider_value) != {fixture_value}
                or providers_by_fixture.get(fixture_value) != {provider_value}
            ):
                raise SnapshotValidationError("CAPTURE_WINDOW_FIXTURE_MAPPING_MISMATCH")
    raw_paths = _raw_payload_paths(logical for logical, _size, _digest in before)
    if any(state_map[logical][1] != payload_sha for logical, payload_sha in raw_paths.items()):
        raise SnapshotValidationError("BATCH_RAW_CONTENT_ADDRESS_MISMATCH")
    raw_files = set(raw_paths.values())
    if raw_files != set(receipt_inventory.payload_sha256s):
        raise SnapshotValidationError("BATCH_RAW_RECEIPT_DISPOSITION_MISMATCH")
    normalized_hashes = {
        capture.normalized_source_sha256
        for capture in captures
        if capture.normalized_source_sha256 is not None
    }
    normalized_paths = {
        logical
        for logical, _size, _digest in before
        if logical.casefold().startswith("normalized/")
    }
    if normalized_paths != set(receipt_inventory.normalized_paths):
        raise SnapshotValidationError("BATCH_NORMALIZED_PATH_DISPOSITION_MISMATCH")
    normalized_files = {digest for logical, _size, digest in before if logical in normalized_paths}
    if normalized_files != normalized_hashes:
        raise SnapshotValidationError("BATCH_OBSERVATION_RECEIPT_DISPOSITION_MISMATCH")

    _scan_source_for_credentials(resolved)
    capture_associations_by_path: dict[str, set[str]] = {}
    receipt_associations_by_path: dict[str, set[str]] = {}

    def associate(
        logical: str,
        *,
        labels: Iterable[str],
        receipt_ids: Iterable[str],
    ) -> None:
        capture_associations_by_path.setdefault(logical, set()).update(labels)
        receipt_associations_by_path.setdefault(logical, set()).update(receipt_ids)

    for capture in captures:
        technical_document = next(
            (
                (path, document)
                for path, document in receipt_documents
                if document.get("receipt_id") == capture.receipt_id
            ),
            None,
        )
        if technical_document is not None:
            final_path, final_document = technical_document
            final_receipt = RawPayloadReceipt.model_validate(final_document)
            intake_id = final_receipt.intake_receipt_id
            if intake_id is None:  # pragma: no cover - inventory invariant
                raise SnapshotValidationError("CAPTURE_INTAKE_RECEIPT_REQUIRED")
            final_logical = final_path.relative_to(resolved).as_posix()
            intake_logical = f"receipts/{intake_id}.json"
            graph_receipts = (capture.receipt_id, intake_id)
            associate(
                final_logical,
                labels=(capture.label,),
                receipt_ids=(capture.receipt_id,),
            )
            associate(
                intake_logical,
                labels=(capture.label,),
                receipt_ids=(intake_id,),
            )
            raw_logical = cast(str, final_receipt.raw_storage_key)
            technical_manifest_entry = _manifest_for_receipt(resolved, capture.receipt_id)
            if technical_manifest_entry is None:  # pragma: no cover - verified above
                raise SnapshotValidationError("CAPTURE_TECHNICAL_MANIFEST_REQUIRED")
            parsed_technical_manifest = CaptureManifest.model_validate(technical_manifest_entry[0])
            for logical in (
                raw_logical,
                parsed_technical_manifest.normalized_storage_key,
                technical_manifest_entry[1],
            ):
                associate(
                    logical,
                    labels=(capture.label,),
                    receipt_ids=graph_receipts,
                )
            associate(
                manifest_logical,
                labels=(capture.label,),
                receipt_ids=graph_receipts,
            )
        else:
            legacy_entry = next(
                (
                    (path, document)
                    for path, document in receipt_documents
                    if sha256_bytes(path.read_bytes()) == capture.receipt_file_sha256
                ),
                None,
            )
            if legacy_entry is None:  # pragma: no cover - verified above
                raise SnapshotValidationError("CAPTURE_RECEIPT_INVALID")
            legacy_path, legacy_document = legacy_entry
            legacy_logical = legacy_path.relative_to(resolved).as_posix()
            raw_logical = safe_logical_path(
                _first(legacy_document, ("raw_payload_path", "raw_storage_key")),
                code="CAPTURE_RAW_REFERENCE_INVALID",
            )
            normalized_logical = safe_logical_path(
                _first(legacy_document, ("normalized_path", "normalized_storage_key")),
                code="CAPTURE_NORMALIZED_REFERENCE_INVALID",
            )
            for logical in (legacy_logical, raw_logical, normalized_logical, manifest_logical):
                associate(
                    logical,
                    labels=(capture.label,),
                    receipt_ids=(capture.receipt_id,),
                )
    inventory: list[InventoryEntry] = []
    for logical, size, digest in before:
        associations = tuple(sorted(capture_associations_by_path.get(logical, set())))
        receipt_associations = tuple(sorted(receipt_associations_by_path.get(logical, set())))
        retention = "NOT_APPLICABLE"
        if logical.startswith("raw/sha256/"):
            matching = next(capture for capture in captures if capture.raw_payload_sha256 == digest)
            retention = (
                "ACTIVE_UNTIL_DELETE_AFTER"
                if parse_utc(matching.delete_after, code="CAPTURE_DELETE_AFTER_INVALID")
                > finalized_time
                else "DELETE_AFTER_REACHED"
            )
        inventory.append(
            InventoryEntry(
                logical_path=logical,
                file_role=_role(logical),
                size=size,
                sha256=digest,
                capture_association=associations,
                receipt_association=receipt_associations,
                retention_status=retention,
                admissibility=(
                    "TERMINAL_MARKER"
                    if logical == "FINALIZED.json"
                    else "INTEGRITY_INDEX"
                    if logical == sha_logical
                    else "DECLARED_HASH_VERIFIED"
                ),
            )
        )

    observation_started = time.monotonic()
    sleeper(float(observation_seconds))
    observation_elapsed = time.monotonic() - observation_started
    if not test_only_allow_short_observation and observation_elapsed < observation_seconds:
        raise SnapshotValidationError("FINALIZED_OBSERVATION_FIVE_MINUTES_NOT_ELAPSED")
    after = _tree_state(resolved)
    continuous_observation.assert_unchanged()
    if before != after:
        raise SnapshotValidationError("FINALIZED_BATCH_MUTATED")

    retention_entries = [entry for entry in inventory if entry.file_role == "RETENTION_EVIDENCE"]
    if len(retention_entries) != 1:
        raise SnapshotValidationError("BATCH_RETENTION_POLICY_EXACTLY_ONE_REQUIRED")
    retention_entry = retention_entries[0]
    retention_sha_value = _first(manifest, ("retention_policy_sha256", "retention_policy_hash"))
    retention_sha = require_sha256(retention_sha_value, code="BATCH_RETENTION_POLICY_HASH_INVALID")
    if retention_sha != retention_entry.sha256:
        raise SnapshotValidationError("BATCH_RETENTION_POLICY_HASH_MISMATCH")
    retention_path = inside(
        resolved,
        retention_entry.logical_path,
        code="BATCH_RETENTION_POLICY_PATH_INVALID",
    )
    _reject_reparse_components(resolved, retention_entry.logical_path)
    retention_bytes = retention_path.read_bytes()
    if sha256_bytes(retention_bytes) != retention_entry.sha256:
        raise SnapshotValidationError("BATCH_RETENTION_POLICY_HASH_MISMATCH")
    if expected_batch_id != SYNTHETIC_BATCH_ID:
        retention_document = json_object_from_bytes(
            retention_bytes,
            code="BATCH_RETENTION_POLICY_INVALID",
        )
        try:
            InternalRetentionPolicy.model_validate(retention_document)
        except (ValidationError, ValueError):
            raise SnapshotValidationError("BATCH_RETENTION_POLICY_INVALID") from None
    capture_revision = require_string(
        _first(manifest, ("capture_code_revision", "capture_code_sha256", "code_revision")),
        code="BATCH_CAPTURE_CODE_REVISION_MISSING",
    )
    harness_version = require_string(
        _first(manifest, ("capture_harness_version", "harness_version", "schema_version")),
        code="BATCH_CAPTURE_HARNESS_VERSION_MISSING",
    )
    if expected_batch_id != SYNTHETIC_BATCH_ID and (
        capture_revision != EXPECTED_CAPTURE_CODE_REVISION
        or harness_version != EXPECTED_CAPTURE_HARNESS_VERSION
    ):
        raise SnapshotValidationError("BATCH_CAPTURE_LINEAGE_MISMATCH")
    return VerifiedBatch(
        batch_id=batch_id,
        finalized_at=finalized_at,
        source_manifest_sha256=expected_manifest_sha,
        source_manifest_logical_path=manifest_logical,
        source_manifest=manifest,
        finalized_marker_sha256=sha256_bytes(marker_bytes),
        sha256sums_sha256=sha256_bytes(sha_bytes),
        inventory=tuple(inventory),
        captures=tuple(sorted(captures, key=lambda item: item.label)),
        capture_windows=capture_windows,
        selected_fixtures=selected_fixtures,
        retention_policy_sha256=retention_sha,
        capture_code_revision=capture_revision,
        capture_harness_version=harness_version,
        leak_tokens=_leak_tokens(captures),
        network_attempts=0,
        secret_reads=0,
        stable_observation_seconds=observation_seconds,
    )
