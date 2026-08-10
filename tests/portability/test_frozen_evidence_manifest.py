from __future__ import annotations

import copy
import platform
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from scripts.frozen_evidence_manifest import (
    ManifestError,
    build_manifest,
    parquet_entry,
    verify_manifest,
)


def _sample(path: Path, *, store_schema: bool) -> None:
    rows = [
        {"record_id": f"row-{index:04d}", "value": index / 10, "valid": index % 2 == 0}
        for index in range(100)
    ]
    schema = pa.schema(
        [
            ("record_id", pa.string(), False),
            ("value", pa.float64(), False),
            ("valid", pa.bool_(), False),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        path,
        compression="zstd",
        compression_level=3,
        data_page_version="2.0",
        store_schema=store_schema,
    )


def test_semantic_hash_is_independent_from_container_metadata(tmp_path: Path) -> None:
    with_schema = tmp_path / "with-schema.parquet"
    without_schema = tmp_path / "without-schema.parquet"
    _sample(with_schema, store_schema=True)
    _sample(without_schema, store_schema=False)
    left = parquet_entry(with_schema)
    right = parquet_entry(without_schema)
    assert left["file_sha256"] != right["file_sha256"]
    assert left["semantic_hash"] == right["semantic_hash"]
    assert left["schema_hash"] == right["schema_hash"]
    assert left["row_count"] == right["row_count"] == 100


def _complete_manifest(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    parquet = artifact_root / "sample.parquet"
    _sample(parquet, store_schema=True)
    (tmp_path / "input.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "generator.py").write_text("print('stable')\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("locked==1\n", encoding="utf-8")
    arguments: dict[str, object] = {
        "repo_root": tmp_path,
        "artifact_root": "artifacts",
        "source_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "inputs": ["input.json"],
        "generators": ["generator.py"],
        "dependency_lock": "requirements.lock",
        "python_version": platform.python_version(),
        "pyarrow_version": pa.__version__,
    }
    return build_manifest(**arguments), arguments


def _verify(manifest: dict[str, object], arguments: dict[str, object]) -> None:
    verify_manifest(
        repo_root=arguments["repo_root"],
        artifact_root=arguments["artifact_root"],
        manifest=manifest,
        expected_source_sha=arguments["source_sha"],
        expected_tree_sha=arguments["tree_sha"],
        inputs=arguments["inputs"],
        generators=arguments["generators"],
        dependency_lock=arguments["dependency_lock"],
        expected_python_version=arguments["python_version"],
        expected_pyarrow_version=arguments["pyarrow_version"],
    )


def test_manifest_verification_accepts_complete_provenance(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    _verify(manifest, arguments)


@pytest.mark.parametrize(
    "field",
    [
        "tree_sha",
        "inputs_hash",
        "generator_hash",
        "dependency_lock_hash",
        "python_version",
        "pyarrow_version",
    ],
)
def test_manifest_verification_rejects_missing_provenance(
    tmp_path: Path, field: str
) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    del manifest[field]
    with pytest.raises(ManifestError, match="MANIFEST_FIELDS_INVALID"):
        _verify(manifest, arguments)


@pytest.mark.parametrize(
    ("field", "replacement", "error"),
    [
        ("tree_sha", "c" * 40, "TREE_SHA_MISMATCH"),
        ("inputs_hash", "0" * 64, "INPUTS_HASH_MISMATCH"),
        ("generator_hash", "0" * 64, "GENERATOR_HASH_MISMATCH"),
        ("dependency_lock_hash", "0" * 64, "DEPENDENCY_LOCK_HASH_MISMATCH"),
        ("python_version", "0.0.0", "PYTHON_VERSION_MISMATCH"),
        ("pyarrow_version", "0.0.0", "PYARROW_VERSION_MISMATCH"),
    ],
)
def test_manifest_verification_rejects_tampered_provenance(
    tmp_path: Path, field: str, replacement: str, error: str
) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    manifest[field] = replacement
    with pytest.raises(ManifestError, match=error):
        _verify(manifest, arguments)


def test_manifest_verification_rejects_artifact_tampering(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    parquet = tmp_path / "artifacts" / "sample.parquet"
    parquet.write_bytes(parquet.read_bytes()[:-1] + b"X")
    with pytest.raises(ManifestError, match="ARTIFACT_"):
        _verify(copy.deepcopy(manifest), arguments)
