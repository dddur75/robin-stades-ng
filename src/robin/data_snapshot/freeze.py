"""Content-addressed snapshot assembly and committable aggregate report rendering."""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from robin.capture.storage import CaptureStorageError, validate_capture_workspace
from robin.data_snapshot.contracts import (
    AUTHORIZED_MAIN_SHA256,
    EXPECTED_BATCH_ID,
    EXPECTED_EXTERNAL_BATCH_DIRECTORY,
    SNAPSHOT_VERSION,
    SYNTHETIC_BATCH_ID,
    JsonObject,
    JsonValue,
    SnapshotValidationError,
    canonical_json_bytes,
    canonical_sha256,
    json_object_from_bytes,
    parse_utc,
    pretty_json_bytes,
    sha256_bytes,
)
from robin.data_snapshot.leak_scan import (
    authenticated_url_occurrences,
    structured_secret_occurrences,
)
from robin.data_snapshot.profiling import ProfileResult, profile_batch
from robin.data_snapshot.source import (
    NetworkBlockade,
    VerifiedBatch,
    _batch_files,
    _is_reparse_point,
    _reject_reparse_path,
    verify_finalized_batch,
)

_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/][^\\/\s]+)", re.IGNORECASE
)
_POSIX_LOCAL_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9])/(?!/)[A-Za-z0-9._-]+(?:/[^\s\"']*)?", re.IGNORECASE
)
_WEB_URL_PREFIX = re.compile(r"https?://[^?\s\"']+", re.IGNORECASE)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_SCHEMA_PATH = (
    _REPOSITORY_ROOT / "schemas" / "data-sourcing" / "frozen-snapshot-manifest-v1.schema.json"
)
_REPORTS_SCHEMA_PATH = (
    _REPOSITORY_ROOT / "schemas" / "data-sourcing" / "frozen-snapshot-reports-v1.schema.json"
)
_MANIFEST_SCHEMA_CANONICAL_SHA256 = (
    "0f51ff4df2a5b99633a288700b60c8ccc7cbe640e725f62cdc121020b3d71bd0"
)
_REPORTS_SCHEMA_CANONICAL_SHA256 = (
    "a8fc70476fb903968f1313e9bbe74b1460ee69698190e6e73dc1a5b1be633716"
)
_REPORT_ARTIFACTS = {
    "experiment-readiness-gate-v1.json": "experiment-readiness-gate-v1",
    "first-accumulation-candidates-v1.json": "first-accumulation-candidates-v1",
    "first-snapshot-external-reference-v1.json": "first-snapshot-external-reference-v1",
    "five-canary-batch-quality-summary-v1.json": "five-canary-batch-quality-summary-v1",
    "five-canary-schema-drift-v1.json": "five-canary-schema-drift-v1",
    "five-canary-temporal-coverage-v1.json": "five-canary-temporal-coverage-v1",
    "frozen-snapshot-contract-v1.json": "frozen-snapshot-contract-v1",
}
_SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "const",
        "contains",
        "description",
        "enum",
        "format",
        "if",
        "items",
        "maxContains",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minContains",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "oneOf",
        "pattern",
        "properties",
        "propertyNames",
        "required",
        "then",
        "title",
        "type",
        "uniqueItems",
    }
)
_SCHEMA_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_DRAFT_2020_12_SCHEMA = "https://json-schema.org/draft/2020-12/schema"
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, dict):
        return set(left) == set(right) and all(_json_equal(left[key], right[key]) for key in left)
    return bool(left == right)


def _schema_contract_error() -> SnapshotValidationError:
    return SnapshotValidationError("FROZEN_SNAPSHOT_SCHEMA_CONTRACT_INVALID")


def _schema_mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _schema_contract_error()
    return cast(Mapping[str, Any], value)


def _schema_array(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise _schema_contract_error()
    return value


def _schema_non_negative_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _schema_contract_error()
    return value


def _validate_schema_contract(schema_value: object) -> None:
    if isinstance(schema_value, bool):
        return
    schema = _schema_mapping(schema_value)
    if set(schema) - _SUPPORTED_SCHEMA_KEYWORDS:
        raise _schema_contract_error()
    for key in ("$schema", "$id", "$ref", "title", "description"):
        if key in schema and not isinstance(schema[key], str):
            raise _schema_contract_error()
    if "$schema" in schema and schema["$schema"] != _DRAFT_2020_12_SCHEMA:
        raise _schema_contract_error()
    if "$ref" in schema and not cast(str, schema["$ref"]).startswith("#/"):
        raise _schema_contract_error()
    if "type" in schema:
        declared_type = schema["type"]
        declared_types = (
            [declared_type] if isinstance(declared_type, str) else _schema_array(declared_type)
        )
        if (
            not declared_types
            or not all(isinstance(item, str) and item in _SCHEMA_TYPES for item in declared_types)
            or len(set(cast(list[str], declared_types))) != len(declared_types)
        ):
            raise _schema_contract_error()
    if "enum" in schema:
        enum = _schema_array(schema["enum"])
        if not enum or any(
            _json_equal(left, right)
            for index, left in enumerate(enum)
            for right in enum[index + 1 :]
        ):
            raise _schema_contract_error()
    if "format" in schema and schema["format"] != "date-time":
        raise _schema_contract_error()
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str):
            raise _schema_contract_error()
        try:
            re.compile(schema["pattern"])
        except re.error:
            raise _schema_contract_error() from None
    for key in (
        "minContains",
        "maxContains",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "minProperties",
        "maxProperties",
    ):
        if key in schema:
            _schema_non_negative_integer(schema[key])
    for minimum_key, maximum_key in (
        ("minContains", "maxContains"),
        ("minItems", "maxItems"),
        ("minLength", "maxLength"),
        ("minProperties", "maxProperties"),
    ):
        if (
            minimum_key in schema
            and maximum_key in schema
            and cast(int, schema[minimum_key]) > cast(int, schema[maximum_key])
        ):
            raise _schema_contract_error()
    if ("minContains" in schema or "maxContains" in schema) and "contains" not in schema:
        raise _schema_contract_error()
    for key in ("minimum", "maximum"):
        if key in schema and (
            not isinstance(schema[key], int | float) or isinstance(schema[key], bool)
        ):
            raise _schema_contract_error()
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise _schema_contract_error()
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise _schema_contract_error()
    if "required" in schema:
        required = _schema_array(schema["required"])
        if not all(isinstance(item, str) for item in required) or len(set(required)) != len(
            required
        ):
            raise _schema_contract_error()
    for key in ("$defs", "properties"):
        if key in schema:
            mapped_children = _schema_mapping(schema[key])
            for child in mapped_children.values():
                _validate_schema_contract(child)
    if "additionalProperties" in schema:
        additional = schema["additionalProperties"]
        if not isinstance(additional, bool | dict):
            raise _schema_contract_error()
        _validate_schema_contract(additional)
    for key in ("propertyNames", "items", "contains", "if", "then"):
        if key in schema:
            _validate_schema_contract(schema[key])
    for key in ("oneOf", "allOf"):
        if key in schema:
            listed_children = _schema_array(schema[key])
            if not listed_children:
                raise _schema_contract_error()
            for child in listed_children:
                _validate_schema_contract(child)


def _resolve_schema_reference(root_schema: Mapping[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise _schema_contract_error()
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise _schema_contract_error()
        current = current[part]
    if not isinstance(current, bool | dict):
        raise _schema_contract_error()
    return current


def _matches_schema_type(value: Any, declared: str) -> bool:
    return {
        "array": isinstance(value, list),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }[declared]


def _valid_rfc3339_date_time(value: str) -> bool:
    if _RFC3339_DATE_TIME.fullmatch(value) is None:
        return False
    try:
        parse_utc(value, code="FROZEN_SNAPSHOT_SCHEMA_DATE_TIME_INVALID")
    except SnapshotValidationError:
        return False
    return True


def _matches_schema(
    value: Any,
    schema_value: object,
    root_schema: Mapping[str, Any],
    *,
    depth: int = 0,
) -> bool:
    if depth > 256:
        raise _schema_contract_error()
    if isinstance(schema_value, bool):
        return schema_value
    schema = _schema_mapping(schema_value)
    next_depth = depth + 1
    if "$ref" in schema and not _matches_schema(
        value,
        _resolve_schema_reference(root_schema, cast(str, schema["$ref"])),
        root_schema,
        depth=next_depth,
    ):
        return False
    if "type" in schema:
        declared = schema["type"]
        declared_types = [declared] if isinstance(declared, str) else cast(list[Any], declared)
        if not any(_matches_schema_type(value, cast(str, item)) for item in declared_types):
            return False
    if "const" in schema and not _json_equal(value, schema["const"]):
        return False
    if "enum" in schema and not any(
        _json_equal(value, item) for item in cast(list[Any], schema["enum"])
    ):
        return False
    if "oneOf" in schema:
        matches = sum(
            _matches_schema(value, child, root_schema, depth=next_depth)
            for child in cast(list[Any], schema["oneOf"])
        )
        if matches != 1:
            return False
    if "allOf" in schema and not all(
        _matches_schema(value, child, root_schema, depth=next_depth)
        for child in cast(list[Any], schema["allOf"])
    ):
        return False
    if "if" in schema and _matches_schema(value, schema["if"], root_schema, depth=next_depth):
        if "then" in schema and not _matches_schema(
            value, schema["then"], root_schema, depth=next_depth
        ):
            return False
    if isinstance(value, str):
        if "minLength" in schema and len(value) < cast(int, schema["minLength"]):
            return False
        if "maxLength" in schema and len(value) > cast(int, schema["maxLength"]):
            return False
        if "pattern" in schema and re.search(cast(str, schema["pattern"]), value) is None:
            return False
        if schema.get("format") == "date-time" and not _valid_rfc3339_date_time(value):
            return False
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < cast(int | float, schema["minimum"]):
            return False
        if "maximum" in schema and value > cast(int | float, schema["maximum"]):
            return False
    if isinstance(value, list):
        if "minItems" in schema and len(value) < cast(int, schema["minItems"]):
            return False
        if "maxItems" in schema and len(value) > cast(int, schema["maxItems"]):
            return False
        if schema.get("uniqueItems") is True and any(
            _json_equal(left, right)
            for index, left in enumerate(value)
            for right in value[index + 1 :]
        ):
            return False
        if "items" in schema and not all(
            _matches_schema(item, schema["items"], root_schema, depth=next_depth) for item in value
        ):
            return False
        if "contains" in schema:
            contained = sum(
                _matches_schema(item, schema["contains"], root_schema, depth=next_depth)
                for item in value
            )
            minimum = cast(int, schema.get("minContains", 1))
            maximum = cast(int | None, schema.get("maxContains"))
            if contained < minimum or (maximum is not None and contained > maximum):
                return False
    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < cast(int, schema["minProperties"]):
            return False
        if "maxProperties" in schema and len(value) > cast(int, schema["maxProperties"]):
            return False
        if "required" in schema and any(
            key not in value for key in cast(list[str], schema["required"])
        ):
            return False
        if "propertyNames" in schema and not all(
            _matches_schema(key, schema["propertyNames"], root_schema, depth=next_depth)
            for key in value
        ):
            return False
        properties = cast(Mapping[str, Any], schema.get("properties", {}))
        if not all(
            _matches_schema(value[key], child, root_schema, depth=next_depth)
            for key, child in properties.items()
            if key in value
        ):
            return False
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            return False
        if isinstance(additional, dict) and not all(
            _matches_schema(value[key], additional, root_schema, depth=next_depth) for key in extras
        ):
            return False
    return True


def _document_matches_schema(document: JsonObject, schema: JsonObject) -> bool:
    _validate_schema_contract(schema)
    return _matches_schema(document, schema, schema)


def _validated_output_schema_path(path: Path, expected: Path) -> tuple[Path, Path]:
    unresolved, resolved = _validated_repository_path(
        path,
        expected,
        mismatch_code="FROZEN_SNAPSHOT_SCHEMA_PATH_MISMATCH",
    )
    if not resolved.is_file():
        raise SnapshotValidationError("FROZEN_SNAPSHOT_SCHEMA_PATH_INVALID")
    return unresolved, resolved


def _load_output_schema(path: Path, expected: Path, expected_sha256: str) -> JsonObject:
    unresolved, resolved = _validated_output_schema_path(path, expected)
    try:
        before = resolved.stat()
        value = resolved.read_bytes()
        after = resolved.stat()
    except OSError:
        raise _schema_contract_error() from None
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_SCHEMA_PATH_CHANGED")
    _revalidate_repository_path(
        unresolved,
        resolved,
        expected,
        changed_code="FROZEN_SNAPSHOT_SCHEMA_PATH_CHANGED",
    )
    schema = json_object_from_bytes(value, code="FROZEN_SNAPSHOT_SCHEMA_CONTRACT_INVALID")
    if canonical_sha256(schema) != expected_sha256:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_SCHEMA_CONTRACT_HASH_MISMATCH")
    return schema


def _validate_output_documents(
    manifest: JsonObject,
    files: Mapping[str, bytes],
    reports: Mapping[str, bytes],
) -> None:
    manifest_schema = _load_output_schema(
        _MANIFEST_SCHEMA_PATH,
        _MANIFEST_SCHEMA_PATH,
        _MANIFEST_SCHEMA_CANONICAL_SHA256,
    )
    reports_schema = _load_output_schema(
        _REPORTS_SCHEMA_PATH,
        _REPORTS_SCHEMA_PATH,
        _REPORTS_SCHEMA_CANONICAL_SHA256,
    )
    manifest_bytes = files.get("manifest.json")
    if manifest_bytes is None:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_MANIFEST_SCHEMA_INVALID")
    manifest_document = json_object_from_bytes(
        manifest_bytes, code="FROZEN_SNAPSHOT_MANIFEST_SCHEMA_INVALID"
    )
    if not _json_equal(manifest_document, manifest) or not _document_matches_schema(
        manifest_document, manifest_schema
    ):
        raise SnapshotValidationError("FROZEN_SNAPSHOT_MANIFEST_SCHEMA_INVALID")
    if set(reports) != set(_REPORT_ARTIFACTS):
        raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORT_SET_INVALID")
    for name, expected_artifact in sorted(_REPORT_ARTIFACTS.items()):
        report = json_object_from_bytes(reports[name], code="FROZEN_SNAPSHOT_REPORT_SCHEMA_INVALID")
        if report.get("artifact") != expected_artifact or not _document_matches_schema(
            report, reports_schema
        ):
            raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORT_SCHEMA_INVALID")


@dataclass(frozen=True, slots=True)
class BuildResult:
    snapshot_id: str
    snapshot_directory: Path
    manifest_sha256: str
    report_hashes: JsonObject
    real_market_data_leak_count: int
    network_calls: int
    provider_calls: int
    secret_reads: int
    check_only: bool
    verdicts: tuple[str, ...]


def _write_file(path: Path, value: bytes) -> None:
    _reject_reparse_path(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_path(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            _reject_reparse_path(path.parent)
            _reject_reparse_path(path)
        except SnapshotValidationError:
            pass
        else:
            path.unlink(missing_ok=True)
        raise


def _reject_reparse_below(anchor: Path, path: Path) -> None:
    try:
        relative = path.relative_to(anchor)
    except ValueError:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_REPOSITORY_PATH_MISMATCH") from None
    current = anchor
    if _is_reparse_point(current):
        raise SnapshotValidationError("BATCH_REPARSE_POINT_FORBIDDEN")
    for part in relative.parts:
        current /= part
        if _is_reparse_point(current):
            raise SnapshotValidationError("BATCH_REPARSE_POINT_FORBIDDEN")


def _atomic_replace(path: Path, value: bytes, *, trusted_anchor: Path | None = None) -> None:
    if trusted_anchor is None:
        _reject_reparse_path(path.parent)
    else:
        _reject_reparse_below(trusted_anchor, path.parent)
    if trusted_anchor is None:
        _reject_reparse_path(path)
    else:
        _reject_reparse_below(trusted_anchor, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if trusted_anchor is None:
        _reject_reparse_path(path.parent)
    else:
        _reject_reparse_below(trusted_anchor, path.parent)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if trusted_anchor is None:
            _reject_reparse_path(path)
        else:
            _reject_reparse_below(trusted_anchor, path)
        os.replace(temporary, path)
    finally:
        try:
            if trusted_anchor is None:
                _reject_reparse_path(temporary.parent)
                _reject_reparse_path(temporary)
            else:
                _reject_reparse_below(trusted_anchor, temporary.parent)
                _reject_reparse_below(trusted_anchor, temporary)
        except SnapshotValidationError:
            pass
        else:
            temporary.unlink(missing_ok=True)


def _is_unc_path(path: Path) -> bool:
    value = os.fspath(path).replace("/", "\\")
    return value.startswith("\\\\")


def _is_remote_drive(path: Path) -> bool:
    if os.name != "nt":
        return False
    drive, _tail = os.path.splitdrive(os.path.abspath(os.fspath(path)))
    if not drive:
        return False
    import ctypes

    drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
    return bool(drive_type == 4)


def _same_lexical_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )


def _validated_local_path(path: Path, *, unc_code: str) -> tuple[Path, Path]:
    if _is_unc_path(path) or _is_remote_drive(path):
        raise SnapshotValidationError(unc_code)
    unresolved = Path(os.path.abspath(os.fspath(path)))
    _reject_reparse_path(unresolved)
    return unresolved, unresolved.resolve()


def _validated_repository_path(
    path: Path, expected: Path, *, mismatch_code: str
) -> tuple[Path, Path]:
    if _is_unc_path(path) or not _same_lexical_path(path, expected):
        raise SnapshotValidationError(mismatch_code)
    if _is_remote_drive(path):
        raise SnapshotValidationError("FROZEN_SNAPSHOT_REPOSITORY_NETWORK_DRIVE_FORBIDDEN")
    unresolved = Path(os.path.abspath(os.fspath(path)))
    _reject_reparse_below(_REPOSITORY_ROOT, unresolved)
    try:
        metadata = unresolved.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_REPOSITORY_PATH_INVALID") from None
    else:
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_REPOSITORY_HARDLINK_FORBIDDEN")
    return unresolved, unresolved.resolve()


def _revalidate_repository_path(
    unresolved: Path, expected_resolved: Path, expected: Path, *, changed_code: str
) -> Path:
    _current_unresolved, current_resolved = _validated_repository_path(
        unresolved, expected, mismatch_code=changed_code
    )
    if current_resolved != expected_resolved:
        raise SnapshotValidationError(changed_code)
    return current_resolved


def _revalidate_local_path(
    unresolved: Path,
    expected_resolved: Path,
    *,
    unc_code: str,
    changed_code: str,
) -> Path:
    _current_unresolved, current_resolved = _validated_local_path(unresolved, unc_code=unc_code)
    if current_resolved != expected_resolved:
        raise SnapshotValidationError(changed_code)
    return current_resolved


def _validate_external_output_root(
    root: Path,
    *,
    require_approved_root: bool = True,
    reproducibility_run: bool = False,
) -> Path:
    if require_approved_root:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            raise SnapshotValidationError("SNAPSHOT_OUTPUT_LOCALAPPDATA_REQUIRED")
        approved = Path(os.path.abspath(Path(local_appdata) / "Robin" / "snapshots"))
        reproducibility_parent = Path(
            os.path.abspath(Path(local_appdata) / "Robin" / "snapshot-reproducibility")
        )
        requested = Path(os.path.abspath(os.fspath(root)))
        reproducibility_root_valid = (
            reproducibility_run
            and _same_lexical_path(requested.parent, reproducibility_parent)
            and requested.name.startswith("run-")
        )
        if reproducibility_run:
            root_valid = reproducibility_root_valid
        else:
            root_valid = _same_lexical_path(requested, approved)
        if not root_valid:
            raise SnapshotValidationError("SNAPSHOT_OUTPUT_APPROVED_ROOT_MISMATCH")
    unresolved, resolved = _validated_local_path(
        root, unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN"
    )
    try:
        validate_capture_workspace(resolved)
    except CaptureStorageError as error:
        if error.code == "CAPTURE_WORKSPACE_SYNCHRONIZED":
            raise SnapshotValidationError("SNAPSHOT_OUTPUT_SYNCHRONIZED_FORBIDDEN") from None
        if error.code == "CAPTURE_WORKSPACE_IN_GIT":
            raise SnapshotValidationError("SNAPSHOT_OUTPUT_IN_GIT_FORBIDDEN") from None
        raise SnapshotValidationError("SNAPSHOT_OUTPUT_WORKSPACE_INVALID") from None
    return resolved


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _public_windows(profile: ProfileResult) -> list[JsonObject]:
    result: list[JsonObject] = []
    entries = cast(list[Any], profile.temporal_report["entries"])
    for entry_value in entries:
        entry = cast(dict[str, Any], entry_value)
        result.append(
            {
                "capture_label": cast(JsonValue, entry.get("capture_label")),
                "claimed_window": cast(JsonValue, entry.get("claimed_window")),
                "earliest_admissible": cast(JsonValue, entry.get("earliest_admissible")),
                "fixture_pseudonym": cast(JsonValue, entry.get("fixture_pseudonym")),
                "latest_admissible": cast(JsonValue, entry.get("latest_admissible")),
                "status": cast(JsonValue, entry.get("status")),
            }
        )
    return result


def _report_delivery_status(*, synthetic_contract: bool) -> JsonObject:
    return {
        "real_data_status": "NOT_AVAILABLE" if synthetic_contract else "AVAILABLE",
        "synthetic_validation_status": "PASS",
        "tooling_status": "OFFLINE_DRAFT_READY",
    }


def _external_reference(batch: VerifiedBatch, snapshot_id: str) -> JsonObject:
    synthetic_contract = batch.batch_id == SYNTHETIC_BATCH_ID
    return {
        "absolute_local_path_serialized": False,
        "artifact": "first-snapshot-external-reference-v1",
        "claim_id": "DATA.FROZEN_SNAPSHOT.EXTERNAL_REFERENCE.V1.001",
        "external_snapshot_reference": {
            "logical_store": (
                "SYNTHETIC_TEMPORARY_CONTRACT_SNAPSHOTS"
                if synthetic_contract
                else "ROBIN_LOCAL_CONTENT_ADDRESSED_SNAPSHOTS"
            ),
            "snapshot_id": snapshot_id,
        },
        "provider_event_ids_committed": False,
        "raw_payload_sha256_list": [capture.raw_payload_sha256 for capture in batch.captures],
        "real_bookmakers_committed": False,
        "real_odds_committed": False,
        "real_raw_payloads_committed": False,
        "real_teams_committed": False,
        "retention_policy_sha256": batch.retention_policy_sha256,
        "schema_version": "robin-first-snapshot-external-reference-v1",
        "source_batch_id": batch.batch_id,
        "source_batch_manifest_sha256": batch.source_manifest_sha256,
        "status": (
            "SYNTHETIC_CONTRACT_SNAPSHOT_REFERENCE_ONLY"
            if synthetic_contract
            else "EXTERNAL_FROZEN_READ_ONLY_REFERENCE"
        ),
        "real_snapshot_count": 0 if synthetic_contract else 1,
        "real_snapshot_status": "NOT_CREATED" if synthetic_contract else "CREATED",
        **_report_delivery_status(synthetic_contract=synthetic_contract),
    }


def _frozen_marker_contract(*, synthetic_contract: bool) -> JsonObject:
    return {
        "network_calls": 0,
        "provider_calls": 0,
        "real_snapshot_status": "NOT_CREATED" if synthetic_contract else "CREATED",
        "secret_" + "reads": 0,
        "snapshot_scope": (
            "SYNTHETIC_CONTRACT_ONLY" if synthetic_contract else "REAL_RECEIPT_BACKED"
        ),
        "status": "FROZEN_IMMUTABLE",
        "verdicts": (
            [
                "FROZEN_SNAPSHOT_SYNTHETIC_CONTRACT_PROVEN",
                "SYNTHETIC_CONTRACT_SNAPSHOT_IMMUTABLE",
                "NO_REAL_SNAPSHOT_CREATED",
            ]
            if synthetic_contract
            else [
                "ROBIN_FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT_V1_CREATED",
                "FIRST_FROZEN_SNAPSHOT_IMMUTABLE",
            ]
        ),
    }


def _contract_report(*, synthetic_contract: bool = True) -> JsonObject:
    return {
        "artifact": "frozen-snapshot-contract-v1",
        "canonicalization": {
            "encoding": "UTF-8",
            "json": "sorted keys, compact separators, no NaN",
            "snapshot_id": "SHA-256(canonical manifest excluding snapshot_id)",
        },
        "claim_id": "DATA.FROZEN_SNAPSHOT.CONTRACT.V1.001",
        "denominators": [
            "selected_fixture_count",
            "uniquely_mapped_fixture_count",
            "ambiguous_fixture_count",
            "capture_window_count",
            "satisfied_window_count",
            "missed_window_count",
            "mutualized_window_count",
            "HTTP_request_count",
            "billable_request_count",
            "credit_count",
            "raw_payload_count",
            "receipt_count",
            "event_count",
            "unique_bookmaker_count",
            "event_bookmaker_occurrence_count",
            "h2h_market_object_count",
            "totals_market_object_count",
            "h2h_outcome_count",
            "totals_outcome_count",
            "normalized_observation_count",
        ],
        "immutable_marker": "FROZEN.json written last",
        "manifest_fields": [
            "snapshot_id",
            "snapshot_version",
            "source_batch_id",
            "source_batch_manifest_sha256",
            "authorized_main_sha",
            "capture_harness_version",
            "capture_code_revision",
            "receipt_ids",
            "raw_payload_sha256_list",
            "normalized_partition_hashes",
            "request_fingerprints",
            "capture_windows",
            "fixture_mapping_statuses",
            "schema_fingerprints",
            "quota_observations",
            "retention_policy_hash",
            "raw_delete_after_values",
            "quality_report_hash",
            "readiness_report_hash",
            "schema_drift_report_hash",
            "temporal_coverage_report_hash",
            "accumulation_report_hash",
            "receipt_index_hash",
            "source_inventory_hash",
            "source_reference_hash",
            "external_reference_template_hash",
            "frozen_marker_contract_hash",
            "created_at",
            "status",
            "snapshot_scope",
            "real_data_status",
            "real_snapshot_status",
            "tooling_status",
        ],
        "network_policy": "socket, DNS, urllib and stdlib HTTP blocked",
        "raw_payloads_in_git": False,
        "readiness_statuses": (
            [
                "WINDOW_COVERAGE_PARTIAL",
                "MARKET_COVERAGE_PARTIAL",
                "MISSING_SETTLEMENT_LABEL_SOURCE",
                "MISSING_ENRICHED_SOURCE",
                "MINIMUM_SAMPLE_NOT_REACHED",
                "PROTOCOL_SUCCESSOR_REQUIRED",
                "DATA_GATE_BLOCKED",
            ]
            if synthetic_contract
            else [
                "OBSERVATION_PIPELINE_PROVEN",
                "ACCUMULATION_STARTED",
                "WINDOW_COVERAGE_PARTIAL",
                "MARKET_COVERAGE_PARTIAL",
                "MISSING_SETTLEMENT_LABEL_SOURCE",
                "MISSING_ENRICHED_SOURCE",
                "MINIMUM_SAMPLE_NOT_REACHED",
                "PROTOCOL_SUCCESSOR_REQUIRED",
                "DATA_GATE_BLOCKED",
            ]
        ),
        "schema_version": "robin-frozen-snapshot-contract-v1",
        "real_snapshot_status": "NOT_CREATED" if synthetic_contract else "CREATED",
        "snapshot_scope": (
            "SYNTHETIC_CONTRACT_ONLY" if synthetic_contract else "REAL_RECEIPT_BACKED"
        ),
        **_report_delivery_status(synthetic_contract=synthetic_contract),
    }


def _snapshot_material(
    batch: VerifiedBatch,
    profile: ProfileResult,
) -> tuple[str, JsonObject, dict[str, bytes], JsonObject]:
    quality_bytes = pretty_json_bytes(profile.quality_report)
    schema_bytes = pretty_json_bytes(profile.schema_report)
    temporal_bytes = pretty_json_bytes(profile.temporal_report)
    readiness_bytes = pretty_json_bytes(profile.readiness_report)
    accumulation_bytes = pretty_json_bytes(profile.accumulation_report)
    receipt_index_bytes = pretty_json_bytes(profile.receipt_index)
    inventory_document: JsonObject = {
        "files": [entry.public() for entry in batch.inventory],
        "schema_version": "robin-source-batch-inventory-v1",
        "source_batch_id": batch.batch_id,
        "source_manifest_sha256": batch.source_manifest_sha256,
    }
    inventory_bytes = pretty_json_bytes(inventory_document)
    source_reference: JsonObject = {
        "finalized_marker_sha256": batch.finalized_marker_sha256,
        "logical_workspace_identity": batch.batch_id,
        "sha256sums_sha256": batch.sha256sums_sha256,
        "source_manifest_logical_path": batch.source_manifest_logical_path,
        "source_manifest_sha256": batch.source_manifest_sha256,
    }
    source_reference_bytes = pretty_json_bytes(source_reference)
    external_reference_template_hash = sha256_bytes(
        canonical_json_bytes(_external_reference(batch, "SELF"))
    )
    synthetic_contract = batch.batch_id == SYNTHETIC_BATCH_ID
    frozen_marker_contract_hash = sha256_bytes(
        canonical_json_bytes(_frozen_marker_contract(synthetic_contract=synthetic_contract))
    )
    normalized_hashes = {
        path: sha256_bytes(value) for path, value in sorted(profile.normalized_partitions.items())
    }
    report_hashes: JsonObject = {
        "accumulation_report_hash": sha256_bytes(accumulation_bytes),
        "quality_report_hash": sha256_bytes(quality_bytes),
        "readiness_report_hash": sha256_bytes(readiness_bytes),
        "receipt_index_hash": sha256_bytes(receipt_index_bytes),
        "schema_drift_report_hash": sha256_bytes(schema_bytes),
        "source_inventory_hash": sha256_bytes(inventory_bytes),
        "source_reference_hash": sha256_bytes(source_reference_bytes),
        "temporal_coverage_report_hash": sha256_bytes(temporal_bytes),
    }
    manifest_without_id: JsonObject = {
        "authorized_main_sha": AUTHORIZED_MAIN_SHA256,
        "capture_code_revision": batch.capture_code_revision,
        "capture_harness_version": batch.capture_harness_version,
        "capture_windows": _public_windows(profile),
        "created_at": batch.finalized_at,
        "fixture_mapping_statuses": {
            capture.label: list(capture.mapping_statuses) for capture in batch.captures
        },
        "external_reference_template_hash": external_reference_template_hash,
        "frozen_marker_contract_hash": frozen_marker_contract_hash,
        "normalized_partition_hashes": cast(JsonObject, normalized_hashes),
        "quality_report_hash": report_hashes["quality_report_hash"],
        "accumulation_report_hash": report_hashes["accumulation_report_hash"],
        "quota_observations": {capture.label: capture.quota for capture in batch.captures},
        "raw_delete_after_values": {
            capture.label: capture.delete_after for capture in batch.captures
        },
        "raw_payload_sha256_list": sorted(capture.raw_payload_sha256 for capture in batch.captures),
        "readiness_report_hash": report_hashes["readiness_report_hash"],
        "receipt_index_hash": report_hashes["receipt_index_hash"],
        "receipt_ids": sorted(capture.receipt_id for capture in batch.captures),
        "request_fingerprints": sorted(
            capture.request_fingerprint_sha256 for capture in batch.captures
        ),
        "retention_policy_hash": batch.retention_policy_sha256,
        "schema_fingerprints": sorted(
            capture.schema_fingerprint_sha256 for capture in batch.captures
        ),
        "schema_drift_report_hash": report_hashes["schema_drift_report_hash"],
        "snapshot_version": SNAPSHOT_VERSION,
        "source_batch_id": batch.batch_id,
        "source_batch_manifest_sha256": batch.source_manifest_sha256,
        "source_inventory_hash": report_hashes["source_inventory_hash"],
        "source_reference_hash": report_hashes["source_reference_hash"],
        "status": "FROZEN",
        "snapshot_scope": (
            "SYNTHETIC_CONTRACT_ONLY" if synthetic_contract else "REAL_RECEIPT_BACKED"
        ),
        "real_data_status": "NOT_AVAILABLE" if synthetic_contract else "AVAILABLE",
        "real_snapshot_status": "NOT_CREATED" if synthetic_contract else "CREATED",
        "tooling_status": "OFFLINE_DRAFT_READY",
        "temporal_coverage_report_hash": report_hashes["temporal_coverage_report_hash"],
    }
    snapshot_id = sha256_bytes(canonical_json_bytes(manifest_without_id))
    manifest: JsonObject = {"snapshot_id": snapshot_id, **manifest_without_id}
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    external_reference = _external_reference(batch, snapshot_id)
    files: dict[str, bytes] = {
        "manifest.json": manifest_bytes,
        "quality/five-canary-batch-quality-summary-v1.json": quality_bytes,
        "quality/five-canary-schema-drift-v1.json": schema_bytes,
        "quality/five-canary-temporal-coverage-v1.json": temporal_bytes,
        "readiness/experiment-readiness-gate-v1.json": readiness_bytes,
        "readiness/first-accumulation-candidates-v1.json": accumulation_bytes,
        "receipt-index.json": receipt_index_bytes,
        "references/first-snapshot-external-reference-v1.json": pretty_json_bytes(
            external_reference
        ),
        "references/source-batch-inventory-v1.json": inventory_bytes,
        "references/source-batch-reference-v1.json": source_reference_bytes,
        **profile.normalized_partitions,
    }
    return snapshot_id, manifest, files, report_hashes


def _checksums(files: dict[str, bytes]) -> bytes:
    return (
        "\n".join(f"{sha256_bytes(value)}  {path}" for path, value in sorted(files.items())) + "\n"
    ).encode()


def _frozen_marker(
    *, snapshot_id: str, manifest: JsonObject, checksums: bytes, batch: VerifiedBatch
) -> bytes:
    marker: JsonObject = {
        "created_at": batch.finalized_at,
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest) + b"\n"),
        "sha256sums_sha256": sha256_bytes(checksums),
        "snapshot_id": snapshot_id,
        **_frozen_marker_contract(synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID),
    }
    return pretty_json_bytes(marker)


def _expected_files(
    batch: VerifiedBatch, profile: ProfileResult
) -> tuple[str, JsonObject, dict[str, bytes], JsonObject]:
    snapshot_id, manifest, files, report_hashes = _snapshot_material(batch, profile)
    checksums = _checksums(files)
    files["sha256sums.txt"] = checksums
    files["FROZEN.json"] = _frozen_marker(
        snapshot_id=snapshot_id,
        manifest=manifest,
        checksums=checksums,
        batch=batch,
    )
    return snapshot_id, manifest, files, report_hashes


def _tree_bytes(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in _batch_files(root):
        try:
            metadata = path.stat()
        except OSError:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_FILE_STAT_FAILED") from None
        if metadata.st_nlink != 1:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_HARDLINK_FORBIDDEN")
        _reject_reparse_path(path)
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _materialize_snapshot(root: Path, snapshot_id: str, files: dict[str, bytes]) -> Path:
    root = _revalidate_local_path(
        root,
        root,
        unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN",
        changed_code="SNAPSHOT_OUTPUT_ROOT_CHANGED",
    )
    root.mkdir(parents=True, exist_ok=True)
    _revalidate_local_path(
        root,
        root,
        unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN",
        changed_code="SNAPSHOT_OUTPUT_ROOT_CHANGED",
    )
    target = root / snapshot_id
    _reject_reparse_path(target)
    if target.exists():
        if not (target / "FROZEN.json").is_file() or _tree_bytes(target) != files:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_COLLISION")
        return target
    staging = Path(tempfile.mkdtemp(prefix=f".building-{snapshot_id[:12]}-", dir=root))
    try:
        for logical_path, value in sorted(files.items()):
            if logical_path == "FROZEN.json":
                continue
            _write_file(staging / logical_path, value)
        # The terminal marker is the only final write inside the snapshot.
        _write_file(staging / "FROZEN.json", files["FROZEN.json"])
        if _tree_bytes(staging) != files:
            raise SnapshotValidationError("FROZEN_SNAPSHOT_MATERIALIZATION_MISMATCH")
        _revalidate_local_path(
            root,
            root,
            unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN",
            changed_code="SNAPSHOT_OUTPUT_ROOT_CHANGED",
        )
        os.replace(staging, target)
    finally:
        _reject_reparse_path(root)
        try:
            staging.lstat()
        except FileNotFoundError:
            pass
        else:
            _reject_reparse_path(staging)
            if not _same_lexical_path(staging.parent, root):  # pragma: no cover - invariant
                raise SnapshotValidationError("FROZEN_SNAPSHOT_STAGING_ROOT_CHANGED")
            shutil.rmtree(staging)
    return target


def _committable_reports(
    batch: VerifiedBatch,
    profile: ProfileResult,
    snapshot_id: str,
) -> dict[str, bytes]:
    return {
        "frozen-snapshot-contract-v1.json": pretty_json_bytes(
            _contract_report(synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID)
        ),
        "five-canary-batch-quality-summary-v1.json": pretty_json_bytes(profile.quality_report),
        "five-canary-schema-drift-v1.json": pretty_json_bytes(profile.schema_report),
        "five-canary-temporal-coverage-v1.json": pretty_json_bytes(profile.temporal_report),
        "first-snapshot-external-reference-v1.json": pretty_json_bytes(
            _external_reference(batch, snapshot_id)
        ),
        "experiment-readiness-gate-v1.json": pretty_json_bytes(profile.readiness_report),
        "first-accumulation-candidates-v1.json": pretty_json_bytes(profile.accumulation_report),
    }


def scan_committable_reports(
    reports: dict[str, bytes], batch: VerifiedBatch, *, forbidden_paths: tuple[str, ...]
) -> JsonObject:
    combined = b"\n".join(reports[name] for name in sorted(reports))
    documents = [
        json_object_from_bytes(reports[name], code="COMMITTABLE_REPORT_INVALID")
        for name in sorted(reports)
    ]

    def text_values(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [text for key, item in value.items() for text in (key, *text_values(item))]
        if isinstance(value, list):
            return [text for item in value for text in text_values(item)]
        return [value] if isinstance(value, str) else []

    decoded_text = [text for document in documents for text in text_values(document)]

    def detailed_price_field_count(value: Any) -> int:
        if isinstance(value, dict):
            return sum(
                int(key.casefold() in {"price", "outcome_price", "odds", "decimal_odds"})
                + detailed_price_field_count(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return sum(detailed_price_field_count(item) for item in value)
        return 0

    category_counts: dict[str, int] = {}
    for category, tokens in batch.leak_tokens.items():
        if category == "price_fragments":
            category_counts[category] = sum(combined.count(token) for token in tokens if token)
        else:
            category_counts[category] = sum(
                value.casefold().count(token.decode("utf-8").casefold())
                for token in tokens
                if token
                for value in decoded_text
            )
    category_counts["price_fragments"] = category_counts.get("price_fragments", 0) + sum(
        detailed_price_field_count(document) for document in documents
    )
    real_count = sum(category_counts.values())
    absolute_count = sum(
        len(_WINDOWS_ABSOLUTE_PATH.findall(_WEB_URL_PREFIX.sub("", value)))
        + len(_POSIX_LOCAL_ABSOLUTE_PATH.findall(_WEB_URL_PREFIX.sub("", value)))
        for value in decoded_text
    )
    authenticated_url_count = sum(authenticated_url_occurrences(value) for value in decoded_text)
    structured_secret_count = sum(structured_secret_occurrences(document) for document in documents)
    exact_path_count = sum(
        value.casefold().count(path.casefold())
        + value.replace("\\", "/").casefold().count(path.replace("\\", "/").casefold())
        for value in decoded_text
        for path in forbidden_paths
        if path
    )
    total = (
        real_count
        + absolute_count
        + authenticated_url_count
        + structured_secret_count
        + exact_path_count
    )
    return {
        "absolute_path_occurrences": absolute_count,
        "authenticated_url_occurrences": authenticated_url_count,
        "exact_forbidden_path_occurrences": exact_path_count,
        "real_market_data_categories": cast(JsonObject, category_counts),
        "real_market_data_leak_count": real_count,
        "structured_secret_occurrences": structured_secret_count,
        "total_failure_count": total,
        "verdict": "PASS" if total == 0 else "FAIL",
    }


def _write_reports(output: Path, reports: dict[str, bytes], *, check: bool) -> None:
    repository_reports = _REPOSITORY_ROOT / "reports" / "data-sourcing"
    trusted_anchor: Path | None = None
    if _same_lexical_path(output, repository_reports):
        output = _revalidate_repository_path(
            output,
            output,
            repository_reports,
            changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
        )
        trusted_anchor = _REPOSITORY_ROOT
    else:
        output = _revalidate_local_path(
            output,
            output,
            unc_code="FROZEN_SNAPSHOT_REPORTS_NETWORK_SHARE_FORBIDDEN",
            changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
        )
    if check:
        for name, expected in reports.items():
            path = output / name
            if trusted_anchor is None:
                _reject_reparse_path(path)
            else:
                _reject_reparse_below(trusted_anchor, path)
            try:
                metadata = path.stat()
            except OSError:
                raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORT_CHECK_FAILED") from None
            if metadata.st_nlink != 1:
                raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORT_HARDLINK_FORBIDDEN")
            if not path.is_file() or path.read_bytes() != expected:
                raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORT_CHECK_FAILED")
        return
    for name, value in reports.items():
        _atomic_replace(output / name, value, trusted_anchor=trusted_anchor)


def build_frozen_snapshot(
    *,
    source_root: Path,
    output_root: Path,
    protocols_path: Path,
    readiness_matrix_path: Path | None = None,
    reports_output: Path | None = None,
    expected_batch_id: str = EXPECTED_BATCH_ID,
    observation_seconds: int = 300,
    check: bool = False,
    test_only_allow_short_observation: bool = False,
    reproducibility_run: bool = False,
) -> BuildResult:
    """Verify a terminal batch and assemble one immutable external snapshot."""

    if test_only_allow_short_observation:
        if expected_batch_id != SYNTHETIC_BATCH_ID:
            raise SnapshotValidationError("FINALIZED_OBSERVATION_TEST_BYPASS_REAL_BATCH_FORBIDDEN")
    elif expected_batch_id != EXPECTED_BATCH_ID:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_BATCH_ID_OVERRIDE_FORBIDDEN")
    synthetic_test_mode = (
        expected_batch_id == SYNTHETIC_BATCH_ID and test_only_allow_short_observation
    )
    if not synthetic_test_mode and reports_output is None:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_REPORTS_OUTPUT_REQUIRED")
    expected_protocols = (
        _REPOSITORY_ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
    )
    expected_matrix = (
        _REPOSITORY_ROOT / "reports" / "data-sourcing" / "experiment-data-window-matrix-v1.json"
    )
    repository_reports = _REPOSITORY_ROOT / "reports" / "data-sourcing"
    # Pin both runtime contracts before any source byte is read. They are revalidated
    # and content-hash checked at their single read below.
    _validated_output_schema_path(_MANIFEST_SCHEMA_PATH, _MANIFEST_SCHEMA_PATH)
    _validated_output_schema_path(_REPORTS_SCHEMA_PATH, _REPORTS_SCHEMA_PATH)
    if not synthetic_test_mode:
        local_appdata = os.environ.get("LOCALAPPDATA")
        if not local_appdata:
            raise SnapshotValidationError("BATCH_SOURCE_LOCALAPPDATA_REQUIRED")
        expected_source = Path(
            os.path.abspath(Path(local_appdata) / "Robin" / EXPECTED_EXTERNAL_BATCH_DIRECTORY)
        )
        if not _same_lexical_path(source_root, expected_source):
            raise SnapshotValidationError("BATCH_SOURCE_APPROVED_ROOT_MISMATCH")
    unresolved_source, source = _validated_local_path(
        source_root, unc_code="FROZEN_SNAPSHOT_SOURCE_NETWORK_SHARE_FORBIDDEN"
    )
    output = _validate_external_output_root(
        output_root,
        require_approved_root=not synthetic_test_mode,
        reproducibility_run=reproducibility_run,
    )
    reports_are_repository = False
    if reports_output is not None:
        if not synthetic_test_mode and not reproducibility_run:
            unresolved_reports, reports_root = _validated_repository_path(
                reports_output,
                repository_reports,
                mismatch_code="FROZEN_SNAPSHOT_REPORTS_ROOT_MISMATCH",
            )
            reports_are_repository = True
        else:
            if not synthetic_test_mode:
                expected_parent = Path(
                    os.path.abspath(
                        Path(cast(str, local_appdata))
                        / "Robin"
                        / "snapshot-reproducibility-reports"
                    )
                )
                requested_reports = Path(os.path.abspath(os.fspath(reports_output)))
                requested_output = Path(os.path.abspath(os.fspath(output_root)))
                expected_reports = expected_parent / requested_output.name
                if not _same_lexical_path(requested_reports, expected_reports):
                    raise SnapshotValidationError(
                        "FROZEN_SNAPSHOT_REPRODUCIBILITY_REPORTS_ROOT_MISMATCH"
                    )
            unresolved_reports, reports_root = _validated_local_path(
                reports_output, unc_code="FROZEN_SNAPSHOT_REPORTS_NETWORK_SHARE_FORBIDDEN"
            )
    else:
        reports_root = None
    if synthetic_test_mode:
        unresolved_protocols, protocols_file = _validated_local_path(
            protocols_path, unc_code="FROZEN_SNAPSHOT_PROTOCOLS_NETWORK_SHARE_FORBIDDEN"
        )
    else:
        unresolved_protocols, protocols_file = _validated_repository_path(
            protocols_path,
            expected_protocols,
            mismatch_code="FROZEN_SNAPSHOT_PROTOCOLS_PATH_MISMATCH",
        )
    matrix_input = readiness_matrix_path or (
        unresolved_protocols.parent.parent
        / "data-sourcing"
        / "experiment-data-window-matrix-v1.json"
    )
    if synthetic_test_mode:
        unresolved_matrix, matrix_file = _validated_local_path(
            matrix_input, unc_code="FROZEN_SNAPSHOT_MATRIX_NETWORK_SHARE_FORBIDDEN"
        )
    else:
        unresolved_matrix, matrix_file = _validated_repository_path(
            matrix_input,
            expected_matrix,
            mismatch_code="FROZEN_SNAPSHOT_MATRIX_PATH_MISMATCH",
        )
    roots = [("SOURCE", source), ("OUTPUT", output)]
    if reports_root is not None:
        roots.append(("REPORTS", reports_root))
    for index, (left_name, left) in enumerate(roots):
        for right_name, right in roots[index + 1 :]:
            if _paths_overlap(left, right):
                raise SnapshotValidationError(f"FROZEN_SNAPSHOT_{left_name}_{right_name}_OVERLAP")
    with NetworkBlockade() as blockade:
        batch = verify_finalized_batch(
            unresolved_source,
            expected_batch_id=expected_batch_id,
            observation_seconds=observation_seconds,
            test_only_allow_short_observation=test_only_allow_short_observation,
        )
        output = _revalidate_local_path(
            output,
            output,
            unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN",
            changed_code="SNAPSHOT_OUTPUT_ROOT_CHANGED",
        )
        if reports_root is not None:
            if reports_are_repository:
                reports_root = _revalidate_repository_path(
                    unresolved_reports,
                    reports_root,
                    repository_reports,
                    changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
                )
            else:
                reports_root = _revalidate_local_path(
                    unresolved_reports,
                    reports_root,
                    unc_code="FROZEN_SNAPSHOT_REPORTS_NETWORK_SHARE_FORBIDDEN",
                    changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
                )
        if synthetic_test_mode:
            protocols_file = _revalidate_local_path(
                unresolved_protocols,
                protocols_file,
                unc_code="FROZEN_SNAPSHOT_PROTOCOLS_NETWORK_SHARE_FORBIDDEN",
                changed_code="FROZEN_SNAPSHOT_PROTOCOLS_PATH_CHANGED",
            )
            matrix_file = _revalidate_local_path(
                unresolved_matrix,
                matrix_file,
                unc_code="FROZEN_SNAPSHOT_MATRIX_NETWORK_SHARE_FORBIDDEN",
                changed_code="FROZEN_SNAPSHOT_MATRIX_PATH_CHANGED",
            )
        else:
            protocols_file = _revalidate_repository_path(
                unresolved_protocols,
                protocols_file,
                expected_protocols,
                changed_code="FROZEN_SNAPSHOT_PROTOCOLS_PATH_CHANGED",
            )
            matrix_file = _revalidate_repository_path(
                unresolved_matrix,
                matrix_file,
                expected_matrix,
                changed_code="FROZEN_SNAPSHOT_MATRIX_PATH_CHANGED",
            )
        protocols = json_object_from_bytes(protocols_file.read_bytes(), code="PROTOCOLS_INVALID")
        readiness_matrix = json_object_from_bytes(
            matrix_file.read_bytes(), code="READINESS_MATRIX_INVALID"
        )
        profile = profile_batch(batch, protocols, readiness_matrix)
        if profile.data_gate_blocked:
            raise SnapshotValidationError("SCIENTIFIC_DATA_GATE_BLOCKED")
        snapshot_id, manifest, files, report_hashes = _expected_files(batch, profile)
        committable_reports = _committable_reports(batch, profile, snapshot_id)
        _validate_output_documents(manifest, files, committable_reports)
        leak_scan = scan_committable_reports(
            committable_reports,
            batch,
            forbidden_paths=(str(source), str(output)),
        )
        if leak_scan["verdict"] != "PASS":
            raise SnapshotValidationError("REAL_MARKET_DATA_LEAK_DETECTED")
        output = _revalidate_local_path(
            output,
            output,
            unc_code="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN",
            changed_code="SNAPSHOT_OUTPUT_ROOT_CHANGED",
        )
        target = output / snapshot_id
        if check:
            _reject_reparse_path(target)
            if not target.is_dir() or _tree_bytes(target) != files:
                raise SnapshotValidationError("FROZEN_SNAPSHOT_CHECK_FAILED")
        else:
            target = _materialize_snapshot(output, snapshot_id, files)
        if reports_root is not None:
            if reports_are_repository:
                reports_root = _revalidate_repository_path(
                    unresolved_reports,
                    reports_root,
                    repository_reports,
                    changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
                )
            else:
                reports_root = _revalidate_local_path(
                    unresolved_reports,
                    reports_root,
                    unc_code="FROZEN_SNAPSHOT_REPORTS_NETWORK_SHARE_FORBIDDEN",
                    changed_code="FROZEN_SNAPSHOT_REPORTS_ROOT_CHANGED",
                )
            _write_reports(reports_root, committable_reports, check=check)
    if blockade.attempts != 0:
        raise SnapshotValidationError("FROZEN_SNAPSHOT_NETWORK_ATTEMPTED")
    synthetic_verdicts = (
        "SNAPSHOT_TOOLING_OFFLINE_DRAFT_READY",
        "FROZEN_SNAPSHOT_SYNTHETIC_CONTRACT_PROVEN",
        "SYNTHETIC_CONTRACT_SNAPSHOT_IMMUTABLE",
        *(("FROZEN_SNAPSHOT_SYNTHETIC_REPRODUCIBLE",) if check else ()),
        "NO_REAL_SNAPSHOT_CREATED",
        "NO_EXPERIMENT_READINESS_CLAIMED",
        "ZERO_ACCUMULATION_CANDIDATES_WITH_CLOSED_DATA_GATE",
    )
    real_verdicts = (
        "ROBIN_FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT_V1_CREATED",
        "FIRST_FROZEN_SNAPSHOT_IMMUTABLE",
        *(("FIRST_FROZEN_SNAPSHOT_REPRODUCIBLE",) if check else ()),
        "FIVE_CANARY_BATCH_QUALITY_PROFILED",
        "REAL_MARKET_SCHEMA_DRIFT_CLASSIFIED",
        "REAL_TEMPORAL_WINDOW_COVERAGE_PROFILED",
        "ROBIN_FIRST_25_EXPERIMENT_READINESS_REASSESSED",
        "ZERO_PREMATURE_EXPERIMENT_EXECUTION",
        "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED",
    )
    return BuildResult(
        snapshot_id=snapshot_id,
        snapshot_directory=target,
        manifest_sha256=sha256_bytes(canonical_json_bytes(manifest) + b"\n"),
        report_hashes=report_hashes,
        real_market_data_leak_count=cast(int, leak_scan["real_market_data_leak_count"]),
        network_calls=0,
        provider_calls=0,
        secret_reads=0,
        check_only=check,
        verdicts=(
            *(synthetic_verdicts if synthetic_test_mode else real_verdicts),
            "NO_PROVIDER_CALL",
            "NO_SECRET_READ",
            "NO_PURCHASE",
            "NO_PROMOTION",
            "NO_BET",
        ),
    )
