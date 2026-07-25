"""Pont durable append-only du backfill historique vers ``historical-data``."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

from robin.historical.storage import HistoricalBundleStore


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_target(root: Path, relative: Path) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / relative).resolve()
    if resolved_root not in target.parents:
        raise ValueError(f"chemin historique interdit: {relative}")
    return target


def append_state(state: Path, registry: Path) -> dict[str, object]:
    destination = registry / "historical"
    copied = 0
    unchanged = 0
    for source in sorted(path for path in state.rglob("*") if path.is_file()):
        relative = source.relative_to(state)
        target = safe_target(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if file_hash(source) == file_hash(target):
                unchanged += 1
                continue
            if "raw" in relative.parts and "payloads" in relative.parts:
                raise RuntimeError(f"payload brut immuable altéré: {relative}")
        shutil.copy2(source, target)
        copied += 1
    compacted = 0
    for bundle_manifest in sorted((state / "bundles").rglob("*.manifest.json")):
        manifest = json.loads(bundle_manifest.read_text("utf-8"))
        if not manifest.get("sources_removed"):
            continue
        index_path = state / str(manifest["index"])
        index = json.loads(index_path.read_text("utf-8"))
        for entry in index.get("entries", []):
            target = safe_target(destination, Path(str(entry["path"])))
            if target.exists():
                target.unlink()
                compacted += 1
    manifest = {
        "schema_version": "jalon5-historical-v1",
        "files": {
            path.relative_to(destination).as_posix(): file_hash(path)
            for path in sorted(destination.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        },
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "APPENDED",
        "copied": copied,
        "unchanged": unchanged,
        "compacted_sources_removed": compacted,
    }


def verify_state(registry: Path) -> dict[str, object]:
    root = registry / "historical"
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return {"status": "EMPTY", "files": 0}
    manifest = json.loads(manifest_path.read_text("utf-8"))
    failures: list[str] = []
    for relative, expected in manifest.get("files", {}).items():
        path = safe_target(root, Path(relative))
        if not path.exists() or file_hash(path) != expected:
            failures.append(relative)
            continue
        if path.suffix == ".gz" and "payloads" in path.parts:
            payload = gzip.decompress(path.read_bytes())
            filename_hash = path.name.split(".", 1)[0]
            if hashlib.sha256(payload).hexdigest() != filename_hash:
                failures.append(f"{relative}:payload_hash")
    if failures:
        raise RuntimeError(f"registre historique invalide: {len(failures)} fichier(s)")
    return {"status": "VERIFIED", "files": len(manifest.get("files", {}))}


def restore_state(registry: Path, destination: Path) -> dict[str, object]:
    source = registry / "historical"
    if not source.exists():
        return {"status": "STATE_NOT_FOUND", "files": 0}
    restored = 0
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.name == "manifest.json":
            continue
        relative = path.relative_to(source)
        target = safe_target(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or file_hash(target) != file_hash(path):
            shutil.copy2(path, target)
            restored += 1
    replayed = 0
    bundle_store = HistoricalBundleStore(destination)
    for manifest_path in sorted((destination / "bundles").rglob("*.manifest.json")):
        manifest = json.loads(manifest_path.read_text("utf-8"))
        index = json.loads((destination / str(manifest["index"])).read_text("utf-8"))
        for entry in index.get("entries", []):
            relative = str(entry["path"])
            target = safe_target(destination, Path(relative))
            if target.exists() and file_hash(target) == entry["sha256"]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle_store.replay_file(manifest_path, relative))
            replayed += 1
    return {"status": "RESTORED", "files": restored, "bundle_files_replayed": replayed}


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("append", "verify", "restore"):
        child = subparsers.add_parser(name)
        child.add_argument("--registry", type=Path, required=True)
        if name == "append":
            child.add_argument("--state", type=Path, required=True)
        if name == "restore":
            child.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "append":
        result = append_state(args.state, args.registry)
    elif args.command == "verify":
        result = verify_state(args.registry)
    else:
        result = restore_state(args.registry, args.destination)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
