"""Build and verify a portable manifest for canonical frozen Parquet evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

SCHEMA_VERSION = "frozen-evidence-portable-manifest-v1"
MANIFEST_FIELDS = {
    "schema_version",
    "source_sha",
    "tree_sha",
    "inputs_hash",
    "generator_hash",
    "dependency_lock_hash",
    "python_version",
    "pyarrow_version",
    "artifact_files",
}
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class ManifestError(RuntimeError):
    """Raised when evidence or manifest verification fails closed."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ManifestError(f"MANIFEST_PATH_NOT_REPO_RELATIVE:{value}")
    if len(path.parts[0]) == 2 and path.parts[0][1] == ":":
        raise ManifestError(f"MANIFEST_WINDOWS_PATH_FORBIDDEN:{value}")
    return path


def _schema_contract(schema: pa.Schema) -> list[dict[str, object]]:
    return [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
            "metadata": {
                key.decode("utf-8"): value.decode("utf-8")
                for key, value in sorted((field.metadata or {}).items())
            },
        }
        for field in schema
    ]


def schema_hash(schema: pa.Schema) -> str:
    return hashlib.sha256(canonical_json(_schema_contract(schema))).hexdigest()


def _typed_value(value: object) -> object:
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        if math.isnan(value):
            return ["float64", "nan"]
        return ["float64", struct.pack(">d", value).hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, list):
        return ["list", [_typed_value(item) for item in value]]
    if isinstance(value, Mapping):
        return [
            "map",
            [
                [str(key), _typed_value(item)]
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ],
        ]
    return [type(value).__name__, str(value)]


def semantic_hash(path: Path) -> str:
    parquet = pq.ParquetFile(path)
    digest = hashlib.sha256()
    digest.update(canonical_json({"schema_hash": schema_hash(parquet.schema_arrow)}))
    for batch in parquet.iter_batches(batch_size=4096):
        for row in batch.to_pylist():
            digest.update(canonical_json([_typed_value(row[field.name]) for field in batch.schema]))
            digest.update(b"\n")
    return digest.hexdigest()


def _combined_hash(repo_root: Path, relatives: Sequence[str]) -> str:
    entries: list[dict[str, str]] = []
    for relative in sorted(relatives):
        portable = _portable_relative(relative)
        path = repo_root.joinpath(*portable.parts)
        if not path.is_file():
            raise ManifestError(f"MANIFEST_INPUT_MISSING:{portable.as_posix()}")
        entries.append({"path": portable.as_posix(), "sha256": sha256_file(path)})
    return hashlib.sha256(canonical_json(entries)).hexdigest()


def parquet_entry(path: Path) -> dict[str, object]:
    parquet = pq.ParquetFile(path)
    metadata = parquet.metadata
    compression = sorted(
        {
            metadata.row_group(row_group).column(column).compression
            for row_group in range(metadata.num_row_groups)
            for column in range(metadata.num_columns)
        }
    )
    return {
        "name": path.name,
        "file_sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": metadata.num_rows,
        "column_count": metadata.num_columns,
        "schema_hash": schema_hash(parquet.schema_arrow),
        "semantic_hash": semantic_hash(path),
        "created_by": metadata.created_by,
        "compression": compression,
    }


def build_manifest(
    *,
    repo_root: Path,
    artifact_root: str,
    source_sha: str,
    tree_sha: str,
    inputs: Sequence[str],
    generators: Sequence[str],
    dependency_lock: str,
    python_version: str,
    pyarrow_version: str,
) -> dict[str, object]:
    if not GIT_SHA_PATTERN.fullmatch(source_sha):
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_SHA_INVALID")
    if not GIT_SHA_PATTERN.fullmatch(tree_sha):
        raise ManifestError("FROZEN_EVIDENCE_TREE_SHA_INVALID")
    if not inputs:
        raise ManifestError("FROZEN_EVIDENCE_INPUTS_MISSING")
    if not generators:
        raise ManifestError("FROZEN_EVIDENCE_GENERATORS_MISSING")
    if not python_version or not pyarrow_version:
        raise ManifestError("FROZEN_EVIDENCE_RUNTIME_VERSION_MISSING")
    portable_root = _portable_relative(artifact_root)
    root = repo_root.joinpath(*portable_root.parts)
    files = sorted(root.glob("*.parquet"))
    if not files:
        raise ManifestError("FROZEN_EVIDENCE_PARQUET_MISSING")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "tree_sha": tree_sha,
        "inputs_hash": _combined_hash(repo_root, inputs),
        "generator_hash": _combined_hash(repo_root, generators),
        "dependency_lock_hash": _combined_hash(repo_root, [dependency_lock]),
        "python_version": python_version,
        "pyarrow_version": pyarrow_version,
        "artifact_files": [parquet_entry(path) for path in files],
    }


def verify_manifest(
    *,
    repo_root: Path,
    artifact_root: str,
    manifest: Mapping[str, Any],
    expected_source_sha: str,
    expected_tree_sha: str,
    inputs: Sequence[str],
    generators: Sequence[str],
    dependency_lock: str,
    expected_python_version: str,
    expected_pyarrow_version: str,
) -> None:
    if set(manifest) != MANIFEST_FIELDS:
        raise ManifestError("FROZEN_EVIDENCE_MANIFEST_FIELDS_INVALID")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError("FROZEN_EVIDENCE_MANIFEST_SCHEMA_INVALID")
    if not GIT_SHA_PATTERN.fullmatch(expected_source_sha):
        raise ManifestError("FROZEN_EVIDENCE_EXPECTED_SOURCE_SHA_INVALID")
    if manifest.get("source_sha") != expected_source_sha:
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_SHA_MISMATCH")
    if not GIT_SHA_PATTERN.fullmatch(expected_tree_sha):
        raise ManifestError("FROZEN_EVIDENCE_EXPECTED_TREE_SHA_INVALID")
    if manifest.get("tree_sha") != expected_tree_sha:
        raise ManifestError("FROZEN_EVIDENCE_TREE_SHA_MISMATCH")
    if not inputs or manifest.get("inputs_hash") != _combined_hash(repo_root, inputs):
        raise ManifestError("FROZEN_EVIDENCE_INPUTS_HASH_MISMATCH")
    if not generators or manifest.get("generator_hash") != _combined_hash(
        repo_root, generators
    ):
        raise ManifestError("FROZEN_EVIDENCE_GENERATOR_HASH_MISMATCH")
    if manifest.get("dependency_lock_hash") != _combined_hash(
        repo_root, [dependency_lock]
    ):
        raise ManifestError("FROZEN_EVIDENCE_DEPENDENCY_LOCK_HASH_MISMATCH")
    if manifest.get("python_version") != expected_python_version:
        raise ManifestError("FROZEN_EVIDENCE_PYTHON_VERSION_MISMATCH")
    if manifest.get("pyarrow_version") != expected_pyarrow_version:
        raise ManifestError("FROZEN_EVIDENCE_PYARROW_VERSION_MISMATCH")
    entries = manifest.get("artifact_files")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("FROZEN_EVIDENCE_MANIFEST_FILES_MISSING")
    root = repo_root.joinpath(*_portable_relative(artifact_root).parts)
    expected_names: set[str] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("name"), str):
            raise ManifestError("FROZEN_EVIDENCE_MANIFEST_ENTRY_INVALID")
        name = str(raw_entry["name"])
        if PurePosixPath(name).name != name:
            raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_NAME_INVALID")
        expected_names.add(name)
        try:
            actual = parquet_entry(root / name)
        except (OSError, pa.ArrowException) as exc:
            raise ManifestError(f"FROZEN_EVIDENCE_ARTIFACT_UNREADABLE:{name}") from exc
        if actual != raw_entry:
            raise ManifestError(f"FROZEN_EVIDENCE_ARTIFACT_MISMATCH:{name}")
    if len(expected_names) != len(entries):
        raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_DUPLICATE")
    actual_names = {path.name for path in root.glob("*.parquet")}
    if actual_names != expected_names:
        raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_SET_MISMATCH")


def _write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(manifest) + b"\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--repo-root", default=".")
    build.add_argument("--artifact-root", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--tree-sha", required=True)
    build.add_argument("--input", action="append", required=True)
    build.add_argument("--generator", action="append", required=True)
    build.add_argument("--dependency-lock", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--repo-root", default=".")
    verify.add_argument("--artifact-root", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--expected-source-sha", required=True)
    verify.add_argument("--expected-tree-sha", required=True)
    verify.add_argument("--input", action="append", required=True)
    verify.add_argument("--generator", action="append", required=True)
    verify.add_argument("--dependency-lock", required=True)
    return parser


def main() -> int:
    import platform

    args = _parser().parse_args()
    repo_root = Path(args.repo_root).resolve()
    if args.command == "build":
        manifest = build_manifest(
            repo_root=repo_root,
            artifact_root=args.artifact_root,
            source_sha=args.source_sha,
            tree_sha=args.tree_sha,
            inputs=args.input,
            generators=args.generator,
            dependency_lock=args.dependency_lock,
            python_version=platform.python_version(),
            pyarrow_version=pa.__version__,
        )
        output = repo_root.joinpath(*_portable_relative(args.output).parts)
        _write_manifest(output, manifest)
        print("FROZEN_EVIDENCE_MANIFEST_BUILT")
        return 0
    manifest_path = repo_root.joinpath(*_portable_relative(args.manifest).parts)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ManifestError("FROZEN_EVIDENCE_MANIFEST_OBJECT_REQUIRED")
    verify_manifest(
        repo_root=repo_root,
        artifact_root=args.artifact_root,
        manifest=payload,
        expected_source_sha=args.expected_source_sha,
        expected_tree_sha=args.expected_tree_sha,
        inputs=args.input,
        generators=args.generator,
        dependency_lock=args.dependency_lock,
        expected_python_version=platform.python_version(),
        expected_pyarrow_version=pa.__version__,
    )
    print("FROZEN_EVIDENCE_MANIFEST_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
