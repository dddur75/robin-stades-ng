"""Migration progressive, vérifiée et non destructive vers Cloudflare R2."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from robin.historical.critical_closure import (
    ObjectStorageAdapter,
    ObjectStorageIntegrityError,
    S3CompatibleClient,
)
from robin.historical.storage import write_json_atomic

REPORT_RELATIVE_PATH = Path("storage/r2-migration-latest.json")
SCOPE_RELATIVE_PATH = Path("storage/r2-migration-scope.json")
INDEX_RELATIVE_PATH = Path("storage/r2-object-index.json")
CHECKPOINT_RELATIVE_PATH = Path("storage/r2-migration-checkpoint.json")
AUDIT_CHECKPOINT_RELATIVE_PATH = Path("storage/r2-audit-checkpoint.json")
REPLICATION_REPORT_RELATIVE_PATH = Path("storage/r2-replication-latest.json")
Snapshot = dict[str, tuple[int, str]]
ClientFactory = Callable[[Mapping[str, str]], tuple[S3CompatibleClient, str]]
RetrySleep = Callable[[float], None]
RETRYABLE_R2_CODES = {
    "429",
    "500",
    "502",
    "503",
    "504",
    "InternalError",
    "RequestTimeout",
    "ServiceUnavailable",
    "SlowDown",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_migration_control(relative: Path) -> bool:
    return (
        len(relative.parts) >= 2
        and relative.parts[0] == "storage"
        and relative.suffix == ".json"
        and relative.name.startswith("r2-")
    )


def source_paths(state: Path) -> list[Path]:
    """Lister le périmètre stable sans inclure les rapports produits par la migration."""

    return sorted(
        path
        for path in state.rglob("*")
        if path.is_file() and not _is_migration_control(path.relative_to(state))
    )


def source_snapshot(state: Path) -> Snapshot:
    snapshot: Snapshot = {}
    for path in source_paths(state):
        payload = path.read_bytes()
        snapshot[path.relative_to(state).as_posix()] = (len(payload), _sha256(payload))
    return snapshot


def _scope_hash(entries: list[dict[str, object]]) -> str:
    payload = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _sha256(payload)


def load_or_create_scope(state: Path, snapshot: Snapshot) -> dict[str, object]:
    """Figer une fois le périmètre de migration dans un ordre déterministe."""

    path = state / SCOPE_RELATIVE_PATH
    if path.exists():
        loaded = json.loads(path.read_text("utf-8"))
        if not isinstance(loaded, dict) or loaded.get("schema_version") != (
            "r2-migration-scope-v1"
        ):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE")
        raw_entries = loaded.get("entries")
        if not isinstance(raw_entries, list):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRIES")
        entries = [
            dict(entry) for entry in raw_entries if isinstance(entry, Mapping)
        ]
        if len(entries) != len(raw_entries) or loaded.get(
            "scope_hash"
        ) != _scope_hash(entries):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_HASH")
        return loaded
    entries = [
        {"key": key, "size": size, "sha256": digest}
        for key, (size, digest) in snapshot.items()
    ]
    scope = {
        "schema_version": "r2-migration-scope-v1",
        "created_at": _utc_now(),
        "scope_hash": _scope_hash(entries),
        "source_files": len(entries),
        "source_bytes": sum(int(entry["size"]) for entry in entries),
        "entries": entries,
    }
    write_json_atomic(path, scope)
    return scope


def _scope_keys(scope: Mapping[str, object]) -> list[str]:
    entries = scope.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRIES")
    keys: list[str] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("key"), str):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRY")
        keys.append(str(entry["key"]))
    return keys


def _scope_snapshot(scope: Mapping[str, object]) -> Snapshot:
    entries = scope.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRIES")
    snapshot: Snapshot = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRY")
        key = entry.get("key")
        size = entry.get("size")
        digest = entry.get("sha256")
        if (
            not isinstance(key, str)
            or not isinstance(size, int)
            or not isinstance(digest, str)
        ):
            raise RuntimeError("INVALID_R2_MIGRATION_SCOPE_ENTRY")
        snapshot[key] = (size, digest)
    return snapshot


def load_object_index(state: Path) -> dict[str, object]:
    path = state / INDEX_RELATIVE_PATH
    if not path.exists():
        return {
            "schema_version": "r2-object-index-v1",
            "updated_at": None,
            "objects": {},
        }
    loaded = json.loads(path.read_text("utf-8"))
    if not isinstance(loaded, dict) or loaded.get("schema_version") != (
        "r2-object-index-v1"
    ):
        raise RuntimeError("INVALID_R2_OBJECT_INDEX")
    if not isinstance(loaded.get("objects"), dict):
        raise RuntimeError("INVALID_R2_OBJECT_INDEX_OBJECTS")
    return loaded


def _record_object_result(
    index: dict[str, object],
    *,
    key: str,
    size: int,
    digest: str,
    action: str,
    status: str = "verified",
) -> None:
    objects = index["objects"]
    if not isinstance(objects, dict):
        raise RuntimeError("INVALID_R2_OBJECT_INDEX_OBJECTS")
    objects[key] = {
        "size": size,
        "sha256": digest,
        "status": status,
        "last_action": action,
        "verified_at": _utc_now() if status == "verified" else None,
    }
    index["updated_at"] = _utc_now()


def save_object_index(state: Path, index: Mapping[str, object]) -> None:
    write_json_atomic(state / INDEX_RELATIVE_PATH, index)


def load_checkpoint(
    state: Path,
    *,
    scope_hash: str,
    audit: bool = False,
) -> dict[str, object]:
    path = state / (
        AUDIT_CHECKPOINT_RELATIVE_PATH if audit else CHECKPOINT_RELATIVE_PATH
    )
    schema_version = (
        "r2-audit-checkpoint-v1" if audit else "r2-migration-checkpoint-v1"
    )
    if not path.exists():
        return {
            "schema_version": schema_version,
            "scope_hash": scope_hash,
            "next_index": 0,
            "last_key": None,
            "uploaded": 0,
            "replayed": 0,
            "verified": 0,
            "failed": 0,
            "status": "PENDING",
            "updated_at": None,
        }
    loaded = json.loads(path.read_text("utf-8"))
    if not isinstance(loaded, dict) or loaded.get("schema_version") != schema_version:
        raise RuntimeError(
            "INVALID_R2_AUDIT_CHECKPOINT"
            if audit
            else "INVALID_R2_MIGRATION_CHECKPOINT"
        )
    if loaded.get("scope_hash") != scope_hash:
        raise RuntimeError("R2_MIGRATION_CHECKPOINT_SCOPE_MISMATCH")
    return loaded


def save_checkpoint(
    state: Path,
    checkpoint: Mapping[str, object],
    *,
    audit: bool = False,
) -> None:
    relative_path = (
        AUDIT_CHECKPOINT_RELATIVE_PATH if audit else CHECKPOINT_RELATIVE_PATH
    )
    write_json_atomic(state / relative_path, checkpoint)


def _scope_index_counts(
    scope_keys: list[str],
    index: Mapping[str, object],
) -> dict[str, int]:
    objects = index.get("objects")
    if not isinstance(objects, Mapping):
        raise RuntimeError("INVALID_R2_OBJECT_INDEX_OBJECTS")
    verified = 0
    failed = 0
    for key in scope_keys:
        record = objects.get(key)
        if not isinstance(record, Mapping):
            continue
        if record.get("status") == "verified":
            verified += 1
        elif record.get("status") == "failed":
            failed += 1
    return {
        "pending": len(scope_keys) - verified,
        "verified": verified,
        "failed": failed,
    }


def _required_secret(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def create_r2_client(environment: Mapping[str, str]) -> tuple[S3CompatibleClient, str]:
    """Construire le client S3 Cloudflare sans journaliser les credentials."""

    account = _required_secret(environment, "R2_ACCOUNT_ID")
    access_key = _required_secret(environment, "R2_ACCESS_KEY_ID")
    secret_key = _required_secret(environment, "R2_SECRET_ACCESS_KEY")
    bucket = _required_secret(environment, "R2_BUCKET_NAME")
    boto3 = importlib.import_module("boto3")
    client: Any = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    return cast(S3CompatibleClient, client), bucket


def _client_error_status(error: ClientError) -> str:
    details = error.response.get("Error", {})
    if isinstance(details, Mapping):
        code = str(details.get("Code", "UNKNOWN"))
    else:
        code = "UNKNOWN"
    return f"R2_CLIENT_ERROR_{code}"


def _client_error_code(error: ClientError) -> str:
    details = error.response.get("Error", {})
    if isinstance(details, Mapping):
        return str(details.get("Code", "UNKNOWN"))
    return "UNKNOWN"


def upload_with_retry(
    adapter: ObjectStorageAdapter,
    *,
    key: str,
    payload: bytes,
    max_retries: int,
    retry_sleep: RetrySleep = time.sleep,
) -> tuple[dict[str, object], int]:
    retries = 0
    while True:
        try:
            return adapter.upload(key, payload), retries
        except ClientError as error:
            if (
                retries >= max(max_retries, 0)
                or _client_error_code(error) not in RETRYABLE_R2_CODES
            ):
                raise
            retry_sleep(float(2**retries))
            retries += 1


def _initial_report(
    *,
    execute: bool,
    before: Snapshot,
    selected: list[str],
    started_at: str,
    initial_scan_seconds: float,
) -> dict[str, object]:
    return {
        "mode": "EXECUTE" if execute else "DRY_RUN",
        "source_files": len(before),
        "source_bytes": sum(size for size, _ in before.values()),
        "selected_files": len(selected),
        "selected_bytes": sum(before[key][0] for key in selected),
        "uploaded": 0,
        "replayed": 0,
        "remote_verified": 0,
        "hash_mismatches": 0,
        "size_mismatches": 0,
        "missing_remote_objects": 0,
        "source_files_after": 0,
        "source_bytes_after": 0,
        "source_mutations": 0,
        "deletions": 0,
        "double_write": False,
        "complete": False,
        "status": "RUNNING",
        "bucket_hash": None,
        "started_at": started_at,
        "completed_at": None,
        "initial_scan_seconds": initial_scan_seconds,
        "final_scan_seconds": 0.0,
        "scan_seconds": initial_scan_seconds,
        "head_seconds": 0.0,
        "upload_seconds": 0.0,
        "download_seconds": 0.0,
        "object_processing_seconds": 0.0,
        "duration_seconds": 0.0,
        "files_per_minute": 0.0,
        "bytes_per_minute": 0.0,
        "head_operations": 0,
        "put_operations": 0,
        "get_operations": 0,
        "r2_operations": 0,
        "retry_count": 0,
    }


def _report_int(report: Mapping[str, object], key: str) -> int:
    value = report[key]
    if not isinstance(value, int):
        raise TypeError(f"INVALID_REPORT_COUNTER:{key}")
    return value


def _increment(report: dict[str, object], key: str, amount: int = 1) -> None:
    report[key] = _report_int(report, key) + amount


def _report_float(report: Mapping[str, object], key: str) -> float:
    value = report[key]
    if not isinstance(value, (int, float)):
        raise TypeError(f"INVALID_REPORT_DURATION:{key}")
    return float(value)


def _add_duration(report: dict[str, object], key: str, amount: object) -> None:
    if not isinstance(amount, (int, float)):
        raise TypeError(f"INVALID_OUTCOME_DURATION:{key}")
    report[key] = _report_float(report, key) + float(amount)


def _finalize_source_proof(
    report: dict[str, object],
    *,
    before: Snapshot,
    after: Snapshot,
) -> None:
    before_keys = set(before)
    after_keys = set(after)
    deletions = len(before_keys - after_keys)
    mutations = sum(
        1 for key in before_keys | after_keys if before.get(key) != after.get(key)
    )
    source_bytes_after = sum(size for size, _ in after.values())
    report.update(
        {
            "source_files_after": len(after),
            "source_bytes_after": source_bytes_after,
            "source_mutations": mutations,
            "deletions": deletions,
            "double_write": (
                mutations == 0
                and deletions == 0
                and len(before) == len(after)
                and report["source_bytes"] == source_bytes_after
            ),
        }
    )


def run_migration(
    *,
    state: Path,
    execute: bool,
    max_files: int,
    resume: bool = False,
    audit: bool = False,
    start_after: str | None = None,
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory = create_r2_client,
) -> dict[str, object]:
    """Exécuter un lot cumulatif et persister le rapport même en cas d'échec."""

    total_started = perf_counter()
    started_at = _utc_now()
    scan_started = perf_counter()
    before = source_snapshot(state)
    initial_scan_seconds = perf_counter() - scan_started
    scope = load_or_create_scope(state, before)
    scope_keys = _scope_keys(scope)
    scope_snapshot = _scope_snapshot(scope)
    scope_hash = str(scope["scope_hash"])
    if audit and not resume:
        raise ValueError("R2_AUDIT_REQUIRES_RESUME")
    checkpoint = load_checkpoint(state, scope_hash=scope_hash, audit=audit)
    object_index = load_object_index(state)
    start_index = 0
    if start_after is not None:
        try:
            start_index = scope_keys.index(start_after) + 1
        except ValueError as error:
            raise RuntimeError(f"R2_START_AFTER_NOT_IN_SCOPE:{start_after}") from error
    elif resume:
        checkpoint_index = checkpoint.get("next_index", 0)
        if not isinstance(checkpoint_index, int) or checkpoint_index < 0:
            raise RuntimeError("INVALID_R2_MIGRATION_CHECKPOINT_CURSOR")
        start_index = checkpoint_index
        if not audit and checkpoint.get("updated_at") is None:
            objects = object_index.get("objects")
            if not isinstance(objects, Mapping):
                raise RuntimeError("INVALID_R2_OBJECT_INDEX_OBJECTS")
            while start_index < len(scope_keys):
                key = scope_keys[start_index]
                size, digest = scope_snapshot[key]
                if not _index_record_matches(
                    objects.get(key),
                    size=size,
                    digest=digest,
                ):
                    break
                start_index += 1
            checkpoint["next_index"] = start_index
            checkpoint["verified"] = start_index
            checkpoint["bootstrapped_from_index"] = start_index
    selected = scope_keys[start_index : start_index + max(max_files, 0)]
    missing_scope_sources = [key for key in selected if key not in before]
    if missing_scope_sources:
        raise RuntimeError(
            f"MIGRATION_SCOPE_SOURCE_MISSING:{missing_scope_sources[0]}"
        )
    report = _initial_report(
        execute=execute,
        before=before,
        selected=selected,
        started_at=started_at,
        initial_scan_seconds=initial_scan_seconds,
    )
    report["scope_hash"] = scope["scope_hash"]
    report["scope_files"] = scope["source_files"]
    report["scope_bytes"] = scope["source_bytes"]
    report["resume"] = resume
    report["audit"] = audit
    report["selection_start_index"] = start_index
    report["selection_end_index"] = start_index + len(selected)
    report["start_after"] = start_after
    failure: Exception | None = None
    current_key: str | None = None
    try:
        if not execute:
            report["status"] = "DRY_RUN_READY"
        else:
            client, bucket = client_factory(environment if environment is not None else os.environ)
            report["bucket_hash"] = _sha256(bucket.encode())
            adapter = ObjectStorageAdapter(client, bucket)
            object_processing_started = perf_counter()
            for key in selected:
                current_key = key
                path = state / Path(key)
                payload = path.read_bytes()
                expected_size, expected_hash = before[key]
                if len(payload) != expected_size or _sha256(payload) != expected_hash:
                    raise RuntimeError(f"SOURCE_MUTATED_DURING_MIGRATION:{key}")
                outcome = (
                    adapter.verify(key, payload)
                    if audit
                    else adapter.upload(key, payload)
                )
                counter = "uploaded" if outcome["uploaded"] else "replayed"
                _increment(report, counter)
                _increment(report, "remote_verified")
                _record_object_result(
                    object_index,
                    key=key,
                    size=expected_size,
                    digest=expected_hash,
                    action=counter,
                )
                for duration_key in (
                    "head_seconds",
                    "upload_seconds",
                    "download_seconds",
                ):
                    _add_duration(report, duration_key, outcome[duration_key])
                for operation_key in (
                    "head_operations",
                    "put_operations",
                    "get_operations",
                ):
                    operation_count = outcome[operation_key]
                    if not isinstance(operation_count, int):
                        raise TypeError(f"INVALID_OUTCOME_COUNTER:{operation_key}")
                    _increment(report, operation_key, operation_count)
            report["object_processing_seconds"] = (
                perf_counter() - object_processing_started
            )
            scope_counts = _scope_index_counts(scope_keys, object_index)
            report["status"] = (
                "AUDIT_BATCH_VERIFIED"
                if audit
                else "COMPLETE_VERIFIED"
                if scope_counts["verified"] == len(scope_keys)
                else "PARTIAL_VERIFIED"
            )
    except ObjectStorageIntegrityError as error:
        if current_key is not None and current_key in before:
            failed_size, failed_hash = before[current_key]
            _record_object_result(
                object_index,
                key=current_key,
                size=failed_size,
                digest=failed_hash,
                action="failed",
                status="failed",
            )
        _increment(report, "hash_mismatches", int(error.hash_mismatch))
        _increment(report, "size_mismatches", int(error.size_mismatch))
        _increment(
            report,
            "missing_remote_objects",
            int(error.missing_remote_object),
        )
        report["status"] = error.code
        failure = error
    except ClientError as error:
        if current_key is not None and current_key in before:
            failed_size, failed_hash = before[current_key]
            _record_object_result(
                object_index,
                key=current_key,
                size=failed_size,
                digest=failed_hash,
                action="failed",
                status="failed",
            )
        report["status"] = _client_error_status(error)
        failure = error
    except Exception as error:
        if current_key is not None and current_key in before:
            failed_size, failed_hash = before[current_key]
            _record_object_result(
                object_index,
                key=current_key,
                size=failed_size,
                digest=failed_hash,
                action="failed",
                status="failed",
            )
        message = str(error)
        report["status"] = (
            message.split(":", maxsplit=1)[0] if message else type(error).__name__
        )
        failure = error
    finally:
        final_scan_started = perf_counter()
        after = source_snapshot(state)
        final_scan_seconds = perf_counter() - final_scan_started
        report["final_scan_seconds"] = final_scan_seconds
        report["scan_seconds"] = initial_scan_seconds + final_scan_seconds
        _finalize_source_proof(report, before=before, after=after)
        if _report_int(report, "source_mutations") > 0:
            report["status"] = "SOURCE_MUTATION"
            if failure is None:
                failure = RuntimeError("SOURCE_MUTATION")
        scope_counts = _scope_index_counts(scope_keys, object_index)
        report["mirror_verified_objects"] = scope_counts["verified"]
        report["pending"] = scope_counts["pending"]
        report["verified"] = scope_counts["verified"]
        report["failed"] = scope_counts["failed"]
        report["current_source_lag"] = max(
            len(before) - scope_counts["verified"],
            0,
        )
        if resume:
            checkpoint["next_index"] = start_index + _report_int(
                report, "remote_verified"
            )
            checkpoint["last_key"] = (
                selected[_report_int(report, "remote_verified") - 1]
                if _report_int(report, "remote_verified") > 0
                else checkpoint.get("last_key")
            )
            checkpoint["uploaded"] = _report_int(
                checkpoint, "uploaded"
            ) + _report_int(report, "uploaded")
            checkpoint["replayed"] = _report_int(
                checkpoint, "replayed"
            ) + _report_int(report, "replayed")
            progress_verified = (
                _report_int(checkpoint, "next_index")
                if audit
                else scope_counts["verified"]
            )
            progress_failed = (
                int(failure is not None)
                if audit
                else scope_counts["failed"]
            )
            checkpoint["verified"] = progress_verified
            checkpoint["failed"] = progress_failed
            checkpoint["status"] = (
                "COMPLETE"
                if progress_verified == len(scope_keys) and progress_failed == 0
                else "FAILED"
                if failure is not None
                else "IN_PROGRESS"
            )
            checkpoint["updated_at"] = _utc_now()
            save_checkpoint(state, checkpoint, audit=audit)
            if audit:
                report["pending"] = len(scope_keys) - progress_verified
                report["verified"] = progress_verified
                report["failed"] = progress_failed
                report["status"] = (
                    "AUDIT_COMPLETE_VERIFIED"
                    if progress_verified == len(scope_keys) and progress_failed == 0
                    else "AUDIT_PARTIAL_VERIFIED"
                    if failure is None
                    else report["status"]
                )
        report["complete"] = (
            execute
            and report["status"]
            == ("AUDIT_COMPLETE_VERIFIED" if audit else "COMPLETE_VERIFIED")
            and (
                _report_int(report, "verified")
                if audit
                else scope_counts["verified"]
            )
            == len(scope_keys)
            and report["hash_mismatches"] == 0
            and report["size_mismatches"] == 0
            and report["missing_remote_objects"] == 0
            and report["double_write"] is True
        )
        object_processing_seconds = _report_float(
            report, "object_processing_seconds"
        )
        if object_processing_seconds > 0:
            report["files_per_minute"] = (
                _report_int(report, "remote_verified")
                * 60
                / object_processing_seconds
            )
            report["bytes_per_minute"] = (
                _report_int(report, "selected_bytes")
                * 60
                / object_processing_seconds
            )
        report["r2_operations"] = sum(
            _report_int(report, key)
            for key in ("head_operations", "put_operations", "get_operations")
        )
        report["duration_seconds"] = perf_counter() - total_started
        report["completed_at"] = _utc_now()
        save_object_index(state, object_index)
        write_json_atomic(state / REPORT_RELATIVE_PATH, report)
    if failure is not None:
        raise failure
    return report


def _index_record_matches(
    record: object,
    *,
    size: int,
    digest: str,
) -> bool:
    return (
        isinstance(record, Mapping)
        and record.get("status") == "verified"
        and record.get("size") == size
        and record.get("sha256") == digest
    )


def run_continuous_replication(
    *,
    state: Path,
    max_files: int,
    max_retries: int = 2,
    circuit_breaker_failures: int = 3,
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory = create_r2_client,
    retry_sleep: RetrySleep = time.sleep,
) -> dict[str, object]:
    """Répliquer seulement le delta courant et publier un lag durable."""

    started_at = _utc_now()
    started = perf_counter()
    before = source_snapshot(state)
    index = load_object_index(state)
    objects = index["objects"]
    if not isinstance(objects, dict):
        raise RuntimeError("INVALID_R2_OBJECT_INDEX_OBJECTS")
    pending = [
        key
        for key, (size, digest) in before.items()
        if not _index_record_matches(objects.get(key), size=size, digest=digest)
    ]
    selected = pending[: max(max_files, 0)]
    report: dict[str, object] = {
        "schema_version": "r2-replication-report-v1",
        "started_at": started_at,
        "completed_at": None,
        "replication_enabled": True,
        "source_primary": "historical-data",
        "mirror": "cloudflare-r2",
        "expected_objects": len(before),
        "expected_bytes": sum(size for size, _ in before.values()),
        "selected_files": len(selected),
        "selected_bytes": sum(before[key][0] for key in selected),
        "uploaded": 0,
        "replayed": 0,
        "remote_verified": 0,
        "verified_objects": 0,
        "lag_objects": len(pending),
        "errors": 0,
        "retry_count": 0,
        "circuit_breaker": "CLOSED",
        "last_checkpoint": index.get("updated_at"),
        "source_mutations": 0,
        "deletions": 0,
        "source_preserved": False,
        "duration_seconds": 0.0,
        "status": "RUNNING",
    }
    try:
        client, bucket = client_factory(
            environment if environment is not None else os.environ
        )
    except Exception:
        after = source_snapshot(state)
        before_keys = set(before)
        after_keys = set(after)
        report["deletions"] = len(before_keys - after_keys)
        report["source_mutations"] = sum(
            1
            for key in before_keys | after_keys
            if before.get(key) != after.get(key)
        )
        report["source_preserved"] = (
            report["deletions"] == 0 and report["source_mutations"] == 0
        )
        report["errors"] = 1
        report["circuit_breaker"] = "OPEN"
        report["status"] = "CIRCUIT_OPEN"
        report["client_initialization_failed"] = True
        report["duration_seconds"] = perf_counter() - started
        report["completed_at"] = _utc_now()
        write_json_atomic(state / REPLICATION_REPORT_RELATIVE_PATH, report)
        raise
    adapter = ObjectStorageAdapter(client, bucket)
    consecutive_failures = 0
    for key in selected:
        payload = (state / Path(key)).read_bytes()
        expected_size, expected_hash = before[key]
        if len(payload) != expected_size or _sha256(payload) != expected_hash:
            report["errors"] = _report_int(report, "errors") + 1
            _record_object_result(
                index,
                key=key,
                size=expected_size,
                digest=expected_hash,
                action="failed",
                status="failed",
            )
            break
        try:
            outcome, retries = upload_with_retry(
                adapter,
                key=key,
                payload=payload,
                max_retries=max_retries,
                retry_sleep=retry_sleep,
            )
        except (ClientError, ObjectStorageIntegrityError):
            report["errors"] = _report_int(report, "errors") + 1
            consecutive_failures += 1
            _record_object_result(
                index,
                key=key,
                size=expected_size,
                digest=expected_hash,
                action="failed",
                status="failed",
            )
            if consecutive_failures >= max(circuit_breaker_failures, 1):
                report["circuit_breaker"] = "OPEN"
                break
            continue
        consecutive_failures = 0
        report["retry_count"] = _report_int(report, "retry_count") + retries
        action = "uploaded" if outcome["uploaded"] else "replayed"
        report[action] = _report_int(report, action) + 1
        report["remote_verified"] = _report_int(report, "remote_verified") + 1
        _record_object_result(
            index,
            key=key,
            size=expected_size,
            digest=expected_hash,
            action=action,
        )
    after = source_snapshot(state)
    before_keys = set(before)
    after_keys = set(after)
    report["deletions"] = len(before_keys - after_keys)
    report["source_mutations"] = sum(
        1 for key in before_keys | after_keys if before.get(key) != after.get(key)
    )
    report["source_preserved"] = (
        report["deletions"] == 0 and report["source_mutations"] == 0
    )
    verified_objects = sum(
        _index_record_matches(objects.get(key), size=size, digest=digest)
        for key, (size, digest) in after.items()
    )
    report["verified_objects"] = verified_objects
    report["lag_objects"] = len(after) - verified_objects
    report["last_checkpoint"] = index.get("updated_at")
    report["status"] = (
        "CIRCUIT_OPEN"
        if report["circuit_breaker"] == "OPEN"
        else "SYNCED"
        if report["lag_objects"] == 0 and report["errors"] == 0
        else "LAGGING"
    )
    report["duration_seconds"] = perf_counter() - started
    report["completed_at"] = _utc_now()
    save_object_index(state, index)
    write_json_atomic(state / REPLICATION_REPORT_RELATIVE_PATH, report)
    return report
