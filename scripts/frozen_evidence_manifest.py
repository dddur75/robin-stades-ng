"""Build and verify a portable manifest for canonical frozen Parquet evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess  # nosec B404
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

SCHEMA_VERSION = "frozen-evidence-portable-manifest-v2"
HASH_BASIS = {
    "inputs_hash": "runtime_file_bytes",
    "generator_hash": "git_blob_bytes_at_source_sha",
    "dependency_lock_hash": "git_blob_bytes_at_source_sha",
    "artifact_file_sha256": "runtime_file_bytes",
    "artifact_semantic_hash": "canonical_scientific_contents",
}
MANIFEST_FIELDS = {
    "schema_version",
    "source_sha",
    "tree_sha",
    "hash_basis",
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
    if ":" in value:
        raise ManifestError(f"MANIFEST_WINDOWS_PATH_FORBIDDEN:{value}")
    return path


def _repo_path(repo_root: Path, portable: PurePosixPath, *, strict: bool) -> Path:
    root = repo_root.resolve(strict=True)
    candidate = root.joinpath(*portable.parts)
    try:
        resolved = candidate.resolve(strict=strict)
    except OSError as exc:
        raise ManifestError(f"MANIFEST_INPUT_MISSING:{portable.as_posix()}") from exc
    if not resolved.is_relative_to(root):
        raise ManifestError(f"MANIFEST_PATH_ESCAPES_REPOSITORY:{portable.as_posix()}")
    return candidate


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


def _combined_hash_entries(entries: list[dict[str, str]]) -> str:
    return hashlib.sha256(canonical_json(entries)).hexdigest()


def combined_runtime_file_hash(repo_root: Path, relatives: Sequence[str]) -> str:
    """Hash exact bytes materialized for runtime or transferred inputs."""
    entries: list[dict[str, str]] = []
    for relative in sorted(relatives):
        portable = _portable_relative(relative)
        path = _repo_path(repo_root, portable, strict=True)
        if not path.is_file():
            raise ManifestError(f"MANIFEST_INPUT_MISSING:{portable.as_posix()}")
        entries.append({"path": portable.as_posix(), "sha256": sha256_file(path)})
    return _combined_hash_entries(entries)


def _git_blob_bytes(repo_root: Path, source_sha: str, relative: str) -> bytes:
    portable = _portable_relative(relative)
    try:
        result = subprocess.run(  # nosec B603 B607
            [
                "git",
                "--no-replace-objects",
                "cat-file",
                "blob",
                f"{source_sha}:{portable.as_posix()}",
            ],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ManifestError("FROZEN_EVIDENCE_GIT_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise ManifestError(
            f"MANIFEST_GIT_BLOB_MISSING:{portable.as_posix()}"
        )
    return result.stdout


def combined_git_blob_hash(
    repo_root: Path, source_sha: str, relatives: Sequence[str]
) -> str:
    """Hash exact tracked blobs at the immutable source commit."""
    if not GIT_SHA_PATTERN.fullmatch(source_sha):
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_SHA_INVALID")
    entries = [
        {
            "path": portable.as_posix(),
            "sha256": hashlib.sha256(
                _git_blob_bytes(repo_root, source_sha, portable.as_posix())
            ).hexdigest(),
        }
        for portable in sorted(_portable_relative(value) for value in relatives)
    ]
    return _combined_hash_entries(entries)


def _git_tree_sha(repo_root: Path, source_sha: str) -> str:
    try:
        commit = subprocess.run(  # nosec B603 B607
            ["git", "--no-replace-objects", "rev-parse", f"{source_sha}^{{commit}}"],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
        )
        tree = subprocess.run(  # nosec B603 B607
            ["git", "--no-replace-objects", "rev-parse", f"{source_sha}^{{tree}}"],
            cwd=repo_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
        )
    except OSError as exc:
        raise ManifestError("FROZEN_EVIDENCE_GIT_UNAVAILABLE") from exc
    resolved_commit = commit.stdout.strip()
    resolved_tree = tree.stdout.strip()
    if (
        commit.returncode != 0
        or tree.returncode != 0
        or resolved_commit != source_sha
        or not GIT_SHA_PATTERN.fullmatch(resolved_tree)
    ):
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_SHA_NOT_COMMIT")
    return resolved_tree


def _verify_source_tree(repo_root: Path, source_sha: str, tree_sha: str) -> None:
    if _git_tree_sha(repo_root, source_sha) != tree_sha:
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_TREE_MISMATCH")


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
    _verify_source_tree(repo_root, source_sha, tree_sha)
    if not inputs:
        raise ManifestError("FROZEN_EVIDENCE_INPUTS_MISSING")
    if not generators:
        raise ManifestError("FROZEN_EVIDENCE_GENERATORS_MISSING")
    if not python_version or not pyarrow_version:
        raise ManifestError("FROZEN_EVIDENCE_RUNTIME_VERSION_MISSING")
    portable_root = _portable_relative(artifact_root)
    root = _repo_path(repo_root, portable_root, strict=True)
    files: list[Path] = []
    for candidate in sorted(root.glob("*.parquet")):
        portable_name = _portable_relative(candidate.name)
        if len(portable_name.parts) != 1:
            raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_NAME_INVALID")
        files.append(_repo_path(root, portable_name, strict=True))
    if not files:
        raise ManifestError("FROZEN_EVIDENCE_PARQUET_MISSING")
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "tree_sha": tree_sha,
        "hash_basis": dict(HASH_BASIS),
        "inputs_hash": combined_runtime_file_hash(repo_root, inputs),
        "generator_hash": combined_git_blob_hash(repo_root, source_sha, generators),
        "dependency_lock_hash": combined_git_blob_hash(
            repo_root, source_sha, [dependency_lock]
        ),
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
    if manifest.get("hash_basis") != HASH_BASIS:
        raise ManifestError("FROZEN_EVIDENCE_HASH_BASIS_INVALID")
    if not GIT_SHA_PATTERN.fullmatch(expected_source_sha):
        raise ManifestError("FROZEN_EVIDENCE_EXPECTED_SOURCE_SHA_INVALID")
    if manifest.get("source_sha") != expected_source_sha:
        raise ManifestError("FROZEN_EVIDENCE_SOURCE_SHA_MISMATCH")
    if not GIT_SHA_PATTERN.fullmatch(expected_tree_sha):
        raise ManifestError("FROZEN_EVIDENCE_EXPECTED_TREE_SHA_INVALID")
    if manifest.get("tree_sha") != expected_tree_sha:
        raise ManifestError("FROZEN_EVIDENCE_TREE_SHA_MISMATCH")
    _verify_source_tree(repo_root, expected_source_sha, expected_tree_sha)
    if not inputs or manifest.get("inputs_hash") != combined_runtime_file_hash(
        repo_root, inputs
    ):
        raise ManifestError("FROZEN_EVIDENCE_INPUTS_HASH_MISMATCH")
    if not generators or manifest.get("generator_hash") != combined_git_blob_hash(
        repo_root, expected_source_sha, generators
    ):
        raise ManifestError("FROZEN_EVIDENCE_GENERATOR_HASH_MISMATCH")
    if manifest.get("dependency_lock_hash") != combined_git_blob_hash(
        repo_root, expected_source_sha, [dependency_lock]
    ):
        raise ManifestError("FROZEN_EVIDENCE_DEPENDENCY_LOCK_HASH_MISMATCH")
    if manifest.get("python_version") != expected_python_version:
        raise ManifestError("FROZEN_EVIDENCE_PYTHON_VERSION_MISMATCH")
    if manifest.get("pyarrow_version") != expected_pyarrow_version:
        raise ManifestError("FROZEN_EVIDENCE_PYARROW_VERSION_MISMATCH")
    entries = manifest.get("artifact_files")
    if not isinstance(entries, list) or not entries:
        raise ManifestError("FROZEN_EVIDENCE_MANIFEST_FILES_MISSING")
    root = _repo_path(repo_root, _portable_relative(artifact_root), strict=True)
    expected_names: set[str] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or not isinstance(raw_entry.get("name"), str):
            raise ManifestError("FROZEN_EVIDENCE_MANIFEST_ENTRY_INVALID")
        name = str(raw_entry["name"])
        try:
            portable_name = _portable_relative(name)
        except ManifestError as exc:
            raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_NAME_INVALID") from exc
        if len(portable_name.parts) != 1:
            raise ManifestError("FROZEN_EVIDENCE_ARTIFACT_NAME_INVALID")
        expected_names.add(name)
        try:
            actual = parquet_entry(
                _repo_path(root, portable_name, strict=True)
            )
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
        output = _repo_path(repo_root, _portable_relative(args.output), strict=False)
        _write_manifest(output, manifest)
        print("FROZEN_EVIDENCE_MANIFEST_BUILT")
        return 0
    manifest_path = _repo_path(
        repo_root, _portable_relative(args.manifest), strict=True
    )
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
