"""Restauration R2 représentative, isolée et vérifiée."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter

import pandas as pd

from robin.historical.critical_closure import ObjectStorageAdapter
from robin.historical.object_storage_migration import (
    ClientFactory,
    _record_object_result,
    create_r2_client,
    load_object_index,
    save_object_index,
    source_snapshot,
)
from robin.historical.storage import HistoricalBundleStore, write_json_atomic

RESTORE_REPORT_RELATIVE_PATH = Path("storage/r2-restore-latest.json")
REQUIRED_CATEGORIES = ("json", "parquet", "csv", "manifest", "checkpoint")


def _sha256(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _safe_target(root: Path, key: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / Path(key)).resolve()
    if resolved_root not in target.parents:
        raise ValueError(f"R2_RESTORE_PATH_FORBIDDEN:{key}")
    return target


def _first_matching(
    keys: list[str],
    predicate: Callable[[str], bool],
) -> str | None:
    for key in keys:
        if predicate(key):
            return key
    return None


def select_representative_keys(state: Path) -> dict[str, str]:
    snapshot = source_snapshot(state)
    keys = list(snapshot)
    selected = {
        "parquet": _first_matching(keys, lambda key: key.endswith(".parquet")),
        "csv": _first_matching(keys, lambda key: key.endswith(".csv")),
        "manifest": _first_matching(keys, lambda key: key.endswith(".manifest.json")),
        "checkpoint": _first_matching(
            keys,
            lambda key: "checkpoint" in Path(key).name.lower(),
        ),
    }
    used = {key for key in selected.values() if key is not None}
    selected["json"] = _first_matching(
        keys,
        lambda key: key.endswith(".json") and key not in used,
    )
    missing = [category for category, key in selected.items() if key is None]
    if missing:
        raise RuntimeError(f"R2_RESTORE_SAMPLE_MISSING:{','.join(sorted(missing))}")
    return {category: str(key) for category, key in selected.items()}


def _bundle_companions(state: Path, manifest_key: str) -> list[str]:
    manifest = json.loads((state / Path(manifest_key)).read_text("utf-8"))
    companions = [manifest_key]
    for field in ("index", "archive"):
        value = manifest.get(field)
        if isinstance(value, str):
            companions.append(value)
    return companions


def _verified_index_record(
    index: Mapping[str, object],
    *,
    key: str,
    size: int,
    digest: str,
) -> bool:
    objects = index.get("objects")
    if not isinstance(objects, Mapping):
        return False
    record = objects.get(key)
    return (
        isinstance(record, Mapping)
        and record.get("status") == "verified"
        and record.get("size") == size
        and record.get("sha256") == digest
    )


def run_representative_restore(
    *,
    state: Path,
    destination: Path,
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory = create_r2_client,
) -> dict[str, object]:
    """Uploader si nécessaire puis restaurer un échantillon dans un dossier vide."""

    started = perf_counter()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError("R2_RESTORE_DESTINATION_NOT_EMPTY")
    destination.mkdir(parents=True, exist_ok=True)
    before = source_snapshot(state)
    categories = select_representative_keys(state)
    keys = list(dict.fromkeys(categories.values()))
    keys.extend(
        key
        for key in _bundle_companions(state, categories["manifest"])
        if key not in keys
    )
    client, bucket = client_factory(
        environment if environment is not None else os.environ
    )
    adapter = ObjectStorageAdapter(client, bucket)
    index = load_object_index(state)
    uploaded = 0
    replayed = 0
    remote_verified = 0
    hash_mismatches = 0
    size_mismatches = 0
    restored = 0
    for key in keys:
        payload = (state / Path(key)).read_bytes()
        outcome = adapter.upload(key, payload)
        if outcome["uploaded"]:
            uploaded += 1
            action = "uploaded"
        else:
            replayed += 1
            action = "replayed"
        remote_verified += 1
        _record_object_result(
            index,
            key=key,
            size=before[key][0],
            digest=before[key][1],
            action=action,
        )
        remote = adapter.download(key)
        expected_size, expected_hash = before[key]
        hash_mismatches += int(_sha256(remote) != expected_hash)
        size_mismatches += int(len(remote) != expected_size)
        target = _safe_target(destination, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(remote)
        restored += 1
    parquet_readable = 0
    business_duplicates = 0
    for parquet in destination.rglob("*.parquet"):
        frame = pd.read_parquet(parquet)
        parquet_readable += 1
        if "_record_hash" in frame.columns:
            business_duplicates += int(frame["_record_hash"].duplicated().sum())
    bundle_replay_files = 0
    manifest_path = destination / Path(categories["manifest"])
    if manifest_path.exists():
        replay_destination = destination / "_bundle_replay"
        bundle_replay_files = HistoricalBundleStore(destination).restore_bundle(
            manifest_path,
            replay_destination,
        )
    save_object_index(state, index)
    registry_verified = all(
        _verified_index_record(
            index,
            key=key,
            size=before[key][0],
            digest=before[key][1],
        )
        for key in keys
    )
    after = source_snapshot(state)
    source_mutations = sum(
        1 for key in set(before) | set(after) if before.get(key) != after.get(key)
    )
    data_loss = len(keys) - restored
    status = (
        "RESTORE_VERIFIED"
        if hash_mismatches == 0
        and size_mismatches == 0
        and data_loss == 0
        and business_duplicates == 0
        and parquet_readable >= 1
        and registry_verified
        and source_mutations == 0
        else "RESTORE_FAILED"
    )
    report: dict[str, object] = {
        "schema_version": "r2-restore-report-v1",
        "status": status,
        "categories": categories,
        "selected_files": len(keys),
        "uploaded": uploaded,
        "replayed": replayed,
        "remote_verified": remote_verified,
        "restored_files": restored,
        "hash_mismatches": hash_mismatches,
        "size_mismatches": size_mismatches,
        "data_loss": data_loss,
        "business_duplicates": business_duplicates,
        "parquet_readable": parquet_readable,
        "bundle_replay_files": bundle_replay_files,
        "registry_verified": registry_verified,
        "provider_calls": 0,
        "source_mutations": source_mutations,
        "deletions": 0,
        "duration_seconds": perf_counter() - started,
    }
    write_json_atomic(state / RESTORE_REPORT_RELATIVE_PATH, report)
    return report


__all__ = [
    "REQUIRED_CATEGORIES",
    "RESTORE_REPORT_RELATIVE_PATH",
    "run_representative_restore",
    "select_representative_keys",
]
