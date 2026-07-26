"""Migration progressive, vérifiée et non destructive vers Cloudflare R2."""

from __future__ import annotations

import hashlib
import importlib
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from robin.historical.critical_closure import (
    ObjectStorageAdapter,
    ObjectStorageIntegrityError,
    S3CompatibleClient,
)
from robin.historical.storage import write_json_atomic

REPORT_RELATIVE_PATH = Path("storage/r2-migration-latest.json")
Snapshot = dict[str, tuple[int, str]]
ClientFactory = Callable[[Mapping[str, str]], tuple[S3CompatibleClient, str]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_migration_report(relative: Path) -> bool:
    return (
        len(relative.parts) >= 2
        and relative.parts[0] == "storage"
        and relative.suffix == ".json"
        and relative.name.startswith("r2-migration-")
    )


def source_paths(state: Path) -> list[Path]:
    """Lister le périmètre stable sans inclure les rapports produits par la migration."""

    return sorted(
        path
        for path in state.rglob("*")
        if path.is_file() and not _is_migration_report(path.relative_to(state))
    )


def source_snapshot(state: Path) -> Snapshot:
    snapshot: Snapshot = {}
    for path in source_paths(state):
        payload = path.read_bytes()
        snapshot[path.relative_to(state).as_posix()] = (len(payload), _sha256(payload))
    return snapshot


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


def _initial_report(
    *,
    execute: bool,
    before: Snapshot,
    selected: list[str],
    started_at: str,
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
    }


def _report_int(report: Mapping[str, object], key: str) -> int:
    value = report[key]
    if not isinstance(value, int):
        raise TypeError(f"INVALID_REPORT_COUNTER:{key}")
    return value


def _increment(report: dict[str, object], key: str, amount: int = 1) -> None:
    report[key] = _report_int(report, key) + amount


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
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory = create_r2_client,
) -> dict[str, object]:
    """Exécuter un lot cumulatif et persister le rapport même en cas d'échec."""

    started_at = _utc_now()
    before = source_snapshot(state)
    selected = list(before)[: max(max_files, 0)]
    report = _initial_report(
        execute=execute,
        before=before,
        selected=selected,
        started_at=started_at,
    )
    failure: Exception | None = None
    try:
        if not execute:
            report["status"] = "DRY_RUN_READY"
        else:
            client, bucket = client_factory(environment if environment is not None else os.environ)
            report["bucket_hash"] = _sha256(bucket.encode())
            adapter = ObjectStorageAdapter(client, bucket)
            for key in selected:
                path = state / Path(key)
                payload = path.read_bytes()
                expected_size, expected_hash = before[key]
                if len(payload) != expected_size or _sha256(payload) != expected_hash:
                    raise RuntimeError(f"SOURCE_MUTATED_DURING_MIGRATION:{key}")
                outcome = adapter.upload(key, payload)
                counter = "uploaded" if outcome["uploaded"] else "replayed"
                _increment(report, counter)
                _increment(report, "remote_verified")
            report["status"] = (
                "COMPLETE_VERIFIED"
                if len(selected) == len(before)
                else "PARTIAL_VERIFIED"
            )
    except ObjectStorageIntegrityError as error:
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
        report["status"] = _client_error_status(error)
        failure = error
    except Exception as error:
        message = str(error)
        report["status"] = (
            message.split(":", maxsplit=1)[0] if message else type(error).__name__
        )
        failure = error
    finally:
        after = source_snapshot(state)
        _finalize_source_proof(report, before=before, after=after)
        if _report_int(report, "source_mutations") > 0:
            report["status"] = "SOURCE_MUTATION"
            if failure is None:
                failure = RuntimeError("SOURCE_MUTATION")
        report["complete"] = (
            execute
            and report["status"] == "COMPLETE_VERIFIED"
            and report["remote_verified"] == report["source_files"]
            and report["hash_mismatches"] == 0
            and report["size_mismatches"] == 0
            and report["missing_remote_objects"] == 0
            and report["double_write"] is True
        )
        report["completed_at"] = _utc_now()
        write_json_atomic(state / REPORT_RELATIVE_PATH, report)
    if failure is not None:
        raise failure
    return report
