"""Stockage historique à trois niveaux : brut gzip, Parquet, métadonnées."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import tarfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from robin.providers.base import PayloadBackend


class GzipPayloadBackend(PayloadBackend):
    """Backend immuable compressant les payloads sans modifier leur hash source."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        candidate = (self.root / f"{object_key}.gz").resolve()
        if self.root not in candidate.parents:
            raise ValueError("object_key sort du stockage historique autorisé")
        return candidate

    def put_if_absent(self, object_key: str, payload: bytes) -> str:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        compressed = gzip.compress(payload, compresslevel=9, mtime=0)
        try:
            with path.open("xb") as stream:
                stream.write(compressed)
        except FileExistsError:
            if gzip.decompress(path.read_bytes()) != payload:
                raise RuntimeError("collision de hash historique") from None
        return f"{object_key}.gz".replace("\\", "/")

    def read(self, object_key: str) -> bytes:
        relative = object_key[:-3] if object_key.endswith(".gz") else object_key
        return gzip.decompress(self._path(relative).read_bytes())


def canonical_record_hash(record: dict[str, object]) -> str:
    payload = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_partition(value: object) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value).strip())
    return normalized.strip("-") or "unknown"


def _tabular(record: dict[str, object]) -> dict[str, object]:
    return {
        key: (
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            if isinstance(value, (dict, list, tuple))
            else value
        )
        for key, value in record.items()
    }


class PartitionedParquetStore:
    """Écriture idempotente par hash métier dans des partitions explicites."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def partition_path(
        self,
        *,
        competition: object,
        season: object,
        entity_type: object,
        dataset_version: object,
    ) -> Path:
        return (
            self.root
            / f"competition={_safe_partition(competition)}"
            / f"season={_safe_partition(season)}"
            / f"entity_type={_safe_partition(entity_type)}"
            / f"dataset_version={_safe_partition(dataset_version)}"
            / "part-00000.parquet"
        )

    def write_records(
        self,
        records: Iterable[dict[str, object]],
        *,
        competition: object,
        season: object,
        entity_type: object,
        dataset_version: object,
    ) -> dict[str, object]:
        path = self.partition_path(
            competition=competition,
            season=season,
            entity_type=entity_type,
            dataset_version=dataset_version,
        )
        incoming = [_tabular(record) for record in records]
        for record in incoming:
            record["_record_hash"] = canonical_record_hash(record)
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        frame = pd.concat([existing, pd.DataFrame(incoming)], ignore_index=True)
        before = len(frame)
        if "_record_hash" in frame.columns:
            frame = frame.drop_duplicates("_record_hash", keep="first")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": path.as_posix(),
            "rows": len(frame),
            "inserted": len(frame) - len(existing),
            "duplicates_avoided": before - len(frame),
            "bytes": path.stat().st_size,
            "sha256": digest,
        }

    def validate(self) -> list[str]:
        failures: list[str] = []
        for path in self.root.rglob("*.parquet"):
            frame = pd.read_parquet(path)
            if "_record_hash" not in frame.columns:
                failures.append(f"{path}: _record_hash absent")
            elif bool(frame["_record_hash"].duplicated().any()):
                failures.append(f"{path}: doublons de hash")
        return failures


def directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class HistoricalBundleStore:
    """Bundles immuables et rejouables, avec index et hashes par fichier."""

    SCHEMA_VERSION = "historical-bundle-v1"

    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root.resolve()
        self.bundle_root = self.state_root / "bundles"
        self.bundle_root.mkdir(parents=True, exist_ok=True)

    def create_bundle(
        self,
        files: Iterable[Path],
        *,
        run_id: str,
        competition: str,
        season: int,
        endpoint: str,
        remove_sources: bool = False,
    ) -> dict[str, object]:
        entries: list[dict[str, object]] = []
        sources: list[Path] = []
        for source in sorted({path.resolve() for path in files}):
            if self.state_root not in source.parents or not source.is_file():
                raise ValueError(f"fichier hors état historique: {source}")
            relative = source.relative_to(self.state_root).as_posix()
            if relative.startswith("bundles/"):
                continue
            sources.append(source)
            entries.append(
                {
                    "path": relative,
                    "size": source.stat().st_size,
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            )
        global_hash = hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        directory = (
            self.bundle_root
            / _safe_partition(run_id)
            / _safe_partition(competition)
            / str(season)
            / _safe_partition(endpoint)
        )
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / f"{global_hash}.tar.gz"
        index_path = directory / f"{global_hash}.index.json"
        manifest_path = directory / f"{global_hash}.manifest.json"
        if not archive.exists():
            with tarfile.open(archive, "w:gz", compresslevel=9) as bundle:
                for source, entry in zip(sources, entries, strict=True):
                    bundle.add(source, arcname=str(entry["path"]), recursive=False)
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        index = {
            "schema_version": self.SCHEMA_VERSION,
            "entries": entries,
        }
        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": run_id,
            "competition": competition,
            "season": season,
            "endpoint": endpoint,
            "payload_count": len(entries),
            "global_hash": global_hash,
            "archive_sha256": archive_hash,
            "archive_bytes": archive.stat().st_size,
            "index": index_path.relative_to(self.state_root).as_posix(),
            "archive": archive.relative_to(self.state_root).as_posix(),
            "sources_removed": remove_sources,
        }
        write_json_atomic(index_path, index)
        write_json_atomic(manifest_path, manifest)
        self.verify_bundle(manifest_path)
        if remove_sources:
            for source in sources:
                source.unlink()
        return manifest

    def verify_bundle(self, manifest_path: Path) -> dict[str, object]:
        manifest = json.loads(manifest_path.read_text("utf-8"))
        archive = self.state_root / str(manifest["archive"])
        index_path = self.state_root / str(manifest["index"])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
            raise RuntimeError("hash global d'archive historique invalide")
        index = json.loads(index_path.read_text("utf-8"))
        expected = {
            str(entry["path"]): str(entry["sha256"])
            for entry in index.get("entries", [])
        }
        found: dict[str, str] = {}
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                if not member.isfile():
                    continue
                stream = bundle.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"entrée illisible: {member.name}")
                found[member.name] = hashlib.sha256(stream.read()).hexdigest()
        if found != expected:
            raise RuntimeError("index de bundle historique incohérent")
        return {"status": "VERIFIED", "files": len(found)}

    def replay_file(self, manifest_path: Path, relative: str) -> bytes:
        self.verify_bundle(manifest_path)
        manifest = json.loads(manifest_path.read_text("utf-8"))
        archive = self.state_root / str(manifest["archive"])
        with tarfile.open(archive, "r:gz") as bundle:
            try:
                member = bundle.getmember(relative)
            except KeyError as exc:
                raise FileNotFoundError(relative) from exc
            stream = bundle.extractfile(member)
            if stream is None:
                raise FileNotFoundError(relative)
            return stream.read()


def storage_inventory(root: Path) -> dict[str, object]:
    files = [path for path in root.rglob("*") if path.is_file()]
    bundles = [path for path in files if path.name.endswith(".manifest.json")]
    payloads = [path for path in files if "payloads" in path.parts and path.suffix == ".gz"]
    parquet = [path for path in files if path.suffix == ".parquet"]
    return {
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "bundles": len(bundles),
        "payloads": len(payloads),
        "parquet": len(parquet),
    }
