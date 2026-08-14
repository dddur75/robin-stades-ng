"""Stockage historique à trois niveaux : brut gzip, Parquet, métadonnées."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import tarfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from robin.providers.base import PayloadBackend

DATASET_SNAPSHOT_SCHEMA_VERSION = "historical-dataset-snapshot-v1"


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


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _record_hashes_sha256(record_hashes: Iterable[str]) -> str:
    payload = json.dumps(
        list(record_hashes),
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_indices_sha256(indices: Iterable[int]) -> str:
    payload = json.dumps(list(indices), separators=(",", ":")).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _canonical_rows_sha256(rows: Iterable[Mapping[str, object]]) -> str:
    payload = json.dumps(
        [dict(row) for row in rows],
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

    def snapshot_partition_path(
        self,
        *,
        competition: object,
        season: object,
        entity_type: object,
        dataset_version: object,
        snapshot_sha256: str,
    ) -> Path:
        if not _is_sha256(snapshot_sha256):
            raise ValueError("DATASET_SNAPSHOT_SHA256_INVALID")
        base = self.partition_path(
            competition=competition,
            season=season,
            entity_type=entity_type,
            dataset_version=dataset_version,
        )
        return base.parent / f"snapshot_sha256={snapshot_sha256}" / base.name

    def write_snapshot_records(
        self,
        records: Iterable[dict[str, object]],
        *,
        competition: object,
        season: object,
        entity_type: object,
        dataset_version: object,
        snapshot_sha256: str,
        snapshot_indices: Iterable[int],
    ) -> dict[str, object]:
        """Write one immutable partition addressed by the complete snapshot hash."""

        path = self.snapshot_partition_path(
            competition=competition,
            season=season,
            entity_type=entity_type,
            dataset_version=dataset_version,
            snapshot_sha256=snapshot_sha256,
        )
        originals = [dict(record) for record in records]
        indices = list(snapshot_indices)
        if (
            len(indices) != len(originals)
            or any(index < 0 for index in indices)
            or len(indices) != len(set(indices))
        ):
            raise ValueError("DATASET_SNAPSHOT_ROW_INDICES_INVALID")
        incoming = [_tabular(record) for record in originals]
        for index, original, record in zip(
            indices,
            originals,
            incoming,
            strict=True,
        ):
            record["_snapshot_row_index"] = index
            record["_snapshot_row_json"] = json.dumps(
                original,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            record["_record_hash"] = canonical_record_hash(original)
        incoming_hashes = [str(record["_record_hash"]) for record in incoming]
        hashes_sha256 = _record_hashes_sha256(incoming_hashes)
        if path.exists():
            existing = pd.read_parquet(path)
            existing_hashes = (
                [str(value) for value in existing["_record_hash"].tolist()]
                if "_record_hash" in existing.columns
                else []
            )
            existing_payloads = (
                [str(value) for value in existing["_snapshot_row_json"].tolist()]
                if "_snapshot_row_json" in existing.columns
                else []
            )
            existing_indices = (
                [int(value) for value in existing["_snapshot_row_index"].tolist()]
                if "_snapshot_row_index" in existing.columns
                else []
            )
            incoming_payloads = [str(record["_snapshot_row_json"]) for record in incoming]
            try:
                existing_payload_hashes: list[str] = []
                for payload in existing_payloads:
                    restored = json.loads(payload)
                    if not isinstance(restored, dict):
                        raise ValueError("snapshot row is not an object")
                    existing_payload_hashes.append(canonical_record_hash(restored))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("DATASET_SNAPSHOT_IMMUTABLE_VIOLATION") from exc
            if (
                existing_hashes != incoming_hashes
                or existing_payloads != incoming_payloads
                or existing_indices != indices
                or existing_payload_hashes != existing_hashes
            ):
                raise RuntimeError("DATASET_SNAPSHOT_IMMUTABLE_VIOLATION")
            inserted = 0
            duplicates_avoided = len(incoming)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(incoming).to_parquet(path, index=False)
            inserted = len(incoming)
            duplicates_avoided = 0
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "path": path.as_posix(),
            "rows": len(incoming),
            "inserted": inserted,
            "duplicates_avoided": duplicates_avoided,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "records_sha256": hashes_sha256,
            "row_indices_sha256": _snapshot_indices_sha256(indices),
            "snapshot_sha256": snapshot_sha256,
            "immutable": True,
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


def load_dataset_snapshot(
    state_root: Path,
    manifest: Mapping[str, object],
    *,
    expected_dataset_name: str,
) -> list[dict[str, object]]:
    """Load only the immutable partitions named by one exact dataset manifest."""

    if manifest.get("snapshot_schema_version") != DATASET_SNAPSHOT_SCHEMA_VERSION:
        raise RuntimeError("DATASET_SNAPSHOT_SCHEMA_INVALID")
    if manifest.get("dataset_name") != expected_dataset_name:
        raise RuntimeError("DATASET_SNAPSHOT_NAME_MISMATCH")
    if manifest.get("dataset_version") != expected_dataset_name:
        raise RuntimeError("DATASET_SNAPSHOT_VERSION_MISMATCH")
    snapshot_sha256 = manifest.get("sha256")
    if not _is_sha256(snapshot_sha256):
        raise RuntimeError("DATASET_SNAPSHOT_SHA256_INVALID")
    if manifest.get("immutable") is not True:
        raise RuntimeError("DATASET_SNAPSHOT_NOT_IMMUTABLE")
    partitions = manifest.get("partitions")
    if not isinstance(partitions, list):
        raise RuntimeError("DATASET_SNAPSHOT_PARTITIONS_INVALID")

    state = state_root.resolve()
    derived_root = (state / "derived").resolve()
    seen_paths: set[Path] = set()
    indexed_rows: list[tuple[int, dict[str, object]]] = []
    for item in partitions:
        if not isinstance(item, Mapping):
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_INVALID")
        relative_text = item.get("path")
        if not isinstance(relative_text, str) or not relative_text:
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_PATH_INVALID")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_PATH_INVALID")
        path = (state / relative).resolve()
        if derived_root not in path.parents or path in seen_paths:
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_SCOPE_INVALID")
        seen_paths.add(path)
        if (
            f"entity_type={expected_dataset_name}" not in path.parts
            or f"dataset_version={_safe_partition(expected_dataset_name)}"
            not in path.parts
            or f"snapshot_sha256={snapshot_sha256}" not in path.parts
            or item.get("snapshot_sha256") != snapshot_sha256
            or item.get("immutable") is not True
        ):
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_IDENTITY_MISMATCH")
        if not path.is_file():
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_MISSING")
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_HASH_MISMATCH")
        frame = pd.read_parquet(path)
        if (
            len(frame) != item.get("rows")
            or "_record_hash" not in frame.columns
            or "_snapshot_row_json" not in frame.columns
            or "_snapshot_row_index" not in frame.columns
        ):
            raise RuntimeError("DATASET_SNAPSHOT_PARTITION_ROWS_MISMATCH")
        record_hashes = [str(value) for value in frame["_record_hash"].tolist()]
        if (
            not all(_is_sha256(value) for value in record_hashes)
            or _record_hashes_sha256(record_hashes) != item.get("records_sha256")
        ):
            raise RuntimeError("DATASET_SNAPSHOT_RECORD_HASH_MISMATCH")
        row_indices = [int(value) for value in frame["_snapshot_row_index"].tolist()]
        if (
            len(row_indices) != len(set(row_indices))
            or _snapshot_indices_sha256(row_indices)
            != item.get("row_indices_sha256")
        ):
            raise RuntimeError("DATASET_SNAPSHOT_ROW_INDICES_INVALID")
        for record in frame.to_dict(orient="records"):
            try:
                restored = json.loads(str(record["_snapshot_row_json"]))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("DATASET_SNAPSHOT_ROW_PAYLOAD_INVALID") from exc
            if (
                not isinstance(restored, dict)
                or canonical_record_hash(restored) != str(record["_record_hash"])
            ):
                raise RuntimeError("DATASET_SNAPSHOT_RECORD_HASH_MISMATCH")
            indexed_rows.append(
                (
                    int(record["_snapshot_row_index"]),
                    {str(key): value for key, value in restored.items()},
                )
            )
    indexed_rows.sort(key=lambda item: item[0])
    if [index for index, _ in indexed_rows] != list(range(len(indexed_rows))):
        raise RuntimeError("DATASET_SNAPSHOT_ROW_INDICES_INVALID")
    rows = [row for _, row in indexed_rows]
    if len(rows) != manifest.get("rows"):
        raise RuntimeError("DATASET_SNAPSHOT_TOTAL_ROWS_MISMATCH")
    if _canonical_rows_sha256(rows) != snapshot_sha256:
        raise RuntimeError("DATASET_SNAPSHOT_CONTENT_HASH_MISMATCH")
    return rows


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

    def restore_bundle(self, manifest_path: Path, destination: Path) -> int:
        """Valider une fois puis restaurer toutes les entrées en un seul parcours."""

        self.verify_bundle(manifest_path)
        manifest = json.loads(manifest_path.read_text("utf-8"))
        archive = self.state_root / str(manifest["archive"])
        index = json.loads(
            (self.state_root / str(manifest["index"])).read_text("utf-8")
        )
        expected = {
            str(entry["path"]): str(entry["sha256"])
            for entry in index.get("entries", [])
        }
        root = destination.resolve()
        restored = 0
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                if not member.isfile() or member.name not in expected:
                    continue
                target = (root / member.name).resolve()
                if root not in target.parents:
                    raise ValueError(f"entrée de bundle interdite: {member.name}")
                stream = bundle.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"entrée illisible: {member.name}")
                data = stream.read()
                if hashlib.sha256(data).hexdigest() != expected[member.name]:
                    raise RuntimeError(f"hash individuel invalide: {member.name}")
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == (
                    expected[member.name]
                ):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                restored += 1
        return restored


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
