from __future__ import annotations

import copy
import platform
import subprocess  # nosec B404
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


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(  # nosec B603 B607
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


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
    (tmp_path / "input.json").write_bytes(b"{}\n")
    (tmp_path / "generator.py").write_bytes(b"print('stable')\n")
    (tmp_path / "requirements.lock").write_bytes(b"locked==1\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "manifest-test")
    _git(tmp_path, "config", "user.email", "manifest-test@example.invalid")
    _git(tmp_path, "config", "core.autocrlf", "false")
    _git(tmp_path, "add", "generator.py", "requirements.lock")
    _git(tmp_path, "commit", "-qm", "initial tracked provenance")
    source_sha = _git(tmp_path, "rev-parse", "HEAD")
    tree_sha = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    arguments: dict[str, object] = {
        "repo_root": tmp_path,
        "artifact_root": "artifacts",
        "source_sha": source_sha,
        "tree_sha": tree_sha,
        "inputs": ["input.json"],
        "generators": ["generator.py"],
        "dependency_lock": "requirements.lock",
        "python_version": platform.python_version(),
        "pyarrow_version": pa.__version__,
    }
    return build_manifest(**arguments), arguments


def _build(arguments: dict[str, object]) -> dict[str, object]:
    return build_manifest(**arguments)


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
    assert manifest["schema_version"] == "frozen-evidence-portable-manifest-v2"
    assert manifest["hash_basis"] == {
        "inputs_hash": "runtime_file_bytes",
        "generator_hash": "git_blob_bytes_at_source_sha",
        "dependency_lock_hash": "git_blob_bytes_at_source_sha",
        "artifact_file_sha256": "runtime_file_bytes",
        "artifact_semantic_hash": "canonical_scientific_contents",
    }


def test_git_blob_provenance_is_identical_for_lf_and_crlf_worktrees(
    tmp_path: Path,
) -> None:
    lf_manifest, arguments = _complete_manifest(tmp_path)
    (tmp_path / "generator.py").write_bytes(b"print('stable')\r\n")
    crlf_manifest = _build(arguments)
    assert crlf_manifest == lf_manifest
    assert crlf_manifest["generator_hash"] == lf_manifest["generator_hash"]


def test_uncommitted_generator_change_does_not_change_source_identity(
    tmp_path: Path,
) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    (tmp_path / "generator.py").write_bytes(b"print('dirty worktree')\r\n")
    rebuilt = _build(arguments)
    assert rebuilt["generator_hash"] == manifest["generator_hash"]


def test_real_generator_blob_change_changes_generator_hash(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    (tmp_path / "generator.py").write_bytes(b"print('new commit')\n")
    _git(tmp_path, "add", "generator.py")
    _git(tmp_path, "commit", "-qm", "change generator")
    arguments["source_sha"] = _git(tmp_path, "rev-parse", "HEAD")
    arguments["tree_sha"] = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    rebuilt = _build(arguments)
    assert rebuilt["generator_hash"] != manifest["generator_hash"]


def test_dependency_lock_uses_the_same_git_blob_contract(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    (tmp_path / "requirements.lock").write_bytes(b"locked==1\r\n")
    crlf_worktree = _build(arguments)
    assert crlf_worktree["dependency_lock_hash"] == manifest["dependency_lock_hash"]

    (tmp_path / "requirements.lock").write_bytes(b"locked==2\n")
    _git(tmp_path, "add", "requirements.lock")
    _git(tmp_path, "commit", "-qm", "change dependency lock")
    arguments["source_sha"] = _git(tmp_path, "rev-parse", "HEAD")
    arguments["tree_sha"] = _git(tmp_path, "rev-parse", "HEAD^{tree}")
    changed_blob = _build(arguments)
    assert changed_blob["dependency_lock_hash"] != manifest["dependency_lock_hash"]


def test_runtime_input_change_changes_inputs_hash(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    (tmp_path / "input.json").write_bytes(b'{"changed":true}\n')
    rebuilt = _build(arguments)
    assert rebuilt["inputs_hash"] != manifest["inputs_hash"]
    assert rebuilt["generator_hash"] == manifest["generator_hash"]


@pytest.mark.parametrize(
    "field",
    [
        "tree_sha",
        "hash_basis",
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
        ("hash_basis", {}, "HASH_BASIS_INVALID"),
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


def test_manifest_verification_rejects_nested_hash_basis_tampering(
    tmp_path: Path,
) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    basis = manifest["hash_basis"]
    assert isinstance(basis, dict)
    basis["generator_hash"] = "worktree_file_bytes"
    with pytest.raises(ManifestError, match="HASH_BASIS_INVALID"):
        _verify(manifest, arguments)


@pytest.mark.parametrize(
    "name",
    ["..\\outside.parquet", "file.parquet:alternate-stream", "nested\\sample.parquet"],
)
def test_manifest_rejects_non_portable_artifact_name(
    tmp_path: Path, name: str
) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    entries = manifest["artifact_files"]
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    entry["name"] = name
    with pytest.raises(ManifestError, match="ARTIFACT_NAME_INVALID"):
        _verify(manifest, arguments)


def test_manifest_rejects_artifact_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest, arguments = _complete_manifest(repo)
    artifact = repo / "artifacts" / "sample.parquet"
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(artifact.read_bytes())
    artifact.unlink()
    try:
        artifact.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ManifestError, match="PATH_ESCAPES_REPOSITORY"):
        _build(arguments)
    with pytest.raises(ManifestError, match="PATH_ESCAPES_REPOSITORY"):
        _verify(manifest, arguments)


def test_manifest_verification_rejects_incorrect_source_sha(tmp_path: Path) -> None:
    manifest, arguments = _complete_manifest(tmp_path)
    arguments["source_sha"] = "f" * 40
    with pytest.raises(ManifestError, match="SOURCE_SHA_MISMATCH"):
        _verify(manifest, arguments)


def test_manifest_build_rejects_incorrect_source_sha(tmp_path: Path) -> None:
    _, arguments = _complete_manifest(tmp_path)
    arguments["source_sha"] = "f" * 40
    with pytest.raises(ManifestError, match="SOURCE_SHA_NOT_COMMIT"):
        _build(arguments)


def test_manifest_build_rejects_tree_not_owned_by_source(tmp_path: Path) -> None:
    _, arguments = _complete_manifest(tmp_path)
    arguments["tree_sha"] = "f" * 40
    with pytest.raises(ManifestError, match="SOURCE_TREE_MISMATCH"):
        _build(arguments)


@pytest.mark.parametrize(
    "path",
    [
        "../input.json",
        "/absolute/input.json",
        "C:drive-relative.json",
        "D:drive-relative.json",
        "file.json:alternate-stream",
        "\\\\server\\share\\input.json",
    ],
)
def test_manifest_rejects_non_repo_relative_path(tmp_path: Path, path: str) -> None:
    _, arguments = _complete_manifest(tmp_path)
    arguments["inputs"] = [path]
    with pytest.raises(
        ManifestError, match="PATH_NOT_REPO_RELATIVE|WINDOWS_PATH_FORBIDDEN"
    ):
        _build(arguments)


def test_manifest_rejects_symlink_escape_from_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _, arguments = _complete_manifest(repo)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}\n")
    link = repo / "escaped-input.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    arguments["inputs"] = ["escaped-input.json"]
    with pytest.raises(ManifestError, match="PATH_ESCAPES_REPOSITORY"):
        _build(arguments)
