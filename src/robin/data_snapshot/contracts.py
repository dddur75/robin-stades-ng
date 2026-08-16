"""Small, deterministic contracts shared by the frozen-snapshot builder."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TypeAlias, cast

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = Any
JsonObject: TypeAlias = dict[str, Any]

AUTHORIZED_MAIN_SHA256 = "26cbb8e14814093cc44e17a46a3ef2c899b13d07"
EXPECTED_BATCH_ID = "FIVE_CANARY_RECEIPT_BATCH_V1"
EXPECTED_EXTERNAL_BATCH_DIRECTORY = "five-canary-receipt-batch-20260816"
SYNTHETIC_BATCH_ID = "SYNTHETIC_FIVE_CANARY_RECEIPT_BATCH_V1"
EXPECTED_CAPTURE_CODE_REVISION = "828dde735c9104ee033fb199922d115f7b08578e"
EXPECTED_CAPTURE_HARNESS_VERSION = "robin-receipt-capture-harness-v1"
SNAPSHOT_VERSION = "robin-first-frozen-receipt-backed-snapshot-v1"
PROTOCOL_SOURCE_SHA256 = "317355fa5d55696d8ea6538aad62737b0ea9583e4614b74644903d3f87a7e0e5"
READINESS_MATRIX_CANONICAL_SHA256 = (
    "47a303eaefb971429a92094d08f0200a852a39d17a519518920f050da842755f"
)
RETENTION_POLICY_ID = "INTERNAL_MARKET_DATA_RETENTION_POLICY_V1"
TERMINAL_MARKER_STATUSES = frozenset(
    {"FINALIZED", "COMPLETE", "COMPLETED", "FINISHED", "SUCCESS", "SUCCEEDED"}
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOW_STATUSES = frozenset(
    {
        "WINDOW_VALID",
        "WINDOW_MISSED",
        "WINDOW_NOT_APPLICABLE",
        "WINDOW_MAPPING_AMBIGUOUS",
        "WINDOW_RECEIPT_INVALID",
    }
)
MAPPING_STATUSES = frozenset(
    {
        "FIXTURE_MAPPING_PROVEN",
        "FIXTURE_MAPPING_AMBIGUOUS",
        "FIXTURE_MAPPING_UNPROVEN",
        "FIXTURE_MAPPING_CONFLICT",
    }
)
READINESS_STATUSES = frozenset(
    {
        "OBSERVATION_PIPELINE_PROVEN",
        "ACCUMULATION_STARTED",
        "WINDOW_COVERAGE_PARTIAL",
        "MARKET_COVERAGE_PARTIAL",
        "MISSING_SETTLEMENT_LABEL_SOURCE",
        "MISSING_ENRICHED_SOURCE",
        "MINIMUM_SAMPLE_NOT_REACHED",
        "PROTOCOL_SUCCESSOR_REQUIRED",
        "DATA_GATE_BLOCKED",
    }
)


class SnapshotValidationError(RuntimeError):
    """Fail-closed error carrying a stable public code only."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def canonical_json_bytes(value: object) -> bytes:
    """Return the sole byte representation used for identities and hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = item
    return result


def _reject_non_finite_json_constant(value: str) -> object:
    del value
    raise ValueError("NON_FINITE_JSON_NUMBER")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("NON_FINITE_JSON_NUMBER")
    return parsed


def _strict_json_loads(value: bytes) -> object:
    return json.loads(
        value.decode("utf-8", errors="strict"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_non_finite_json_constant,
        parse_float=_strict_json_float,
    )


def json_object_from_bytes(value: bytes, *, code: str) -> JsonObject:
    try:
        parsed = _strict_json_loads(value)
    except (UnicodeDecodeError, ValueError):
        raise SnapshotValidationError(code) from None
    if not isinstance(parsed, dict):
        raise SnapshotValidationError(code)
    return cast(JsonObject, parsed)


def json_value_from_bytes(value: bytes, *, code: str) -> JsonValue:
    try:
        return cast(JsonValue, _strict_json_loads(value))
    except (UnicodeDecodeError, ValueError):
        raise SnapshotValidationError(code) from None


def require_object(value: object, *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SnapshotValidationError(code)
    return cast(dict[str, Any], value)


def require_array(value: object, *, code: str) -> list[Any]:
    if not isinstance(value, list):
        raise SnapshotValidationError(code)
    return value


def require_string(value: object, *, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise SnapshotValidationError(code)
    return value


def require_sha256(value: object, *, code: str) -> str:
    text = require_string(value, code=code)
    if SHA256_RE.fullmatch(text) is None:
        raise SnapshotValidationError(code)
    return text


def parse_utc(value: object, *, code: str) -> datetime:
    text = require_string(value, code=code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise SnapshotValidationError(code) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SnapshotValidationError(code)
    return parsed.astimezone(UTC)


def utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotValidationError("SNAPSHOT_TIMESTAMP_NOT_UTC_AWARE")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def safe_logical_path(value: object, *, code: str) -> str:
    text = require_string(value, code=code).replace("\\", "/")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or text.startswith(("/", "./"))
        or ":" in text
        or "?" in text
        or "#" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SnapshotValidationError(code)
    return path.as_posix()


def inside(root: Path, logical_path: str, *, code: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / logical_path).resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise SnapshotValidationError(code)
    return candidate


def pseudonym(namespace: str, value: str) -> str:
    digest = hashlib.sha256(f"{namespace}\0{value}".encode()).hexdigest()
    return f"{namespace}-{digest[:16]}"
