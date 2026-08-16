from __future__ import annotations

import _socket
import os
import socket
import subprocess
from pathlib import Path

import pytest

import robin.data_snapshot.freeze as freeze_module
import robin.data_snapshot.source as source_module
from robin.data_snapshot.contracts import SYNTHETIC_BATCH_ID, SnapshotValidationError
from robin.data_snapshot.freeze import (
    _MANIFEST_SCHEMA_CANONICAL_SHA256,
    _REPOSITORY_ROOT,
    _load_output_schema,
    _tree_bytes,
    _validate_external_output_root,
    _validated_local_path,
    _validated_repository_path,
    build_frozen_snapshot,
)
from robin.data_snapshot.source import NetworkBlockade, verify_finalized_batch


def _symlink_or_skip(link: Path, target: Path, *, directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
        return
    except (NotImplementedError, OSError) as error:
        if os.name != "nt" or not directory:
            pytest.skip(f"symlinks unavailable: {error}")
    command_processor = os.environ.get("COMSPEC")
    if command_processor is None:
        pytest.skip("Windows command processor unavailable for junction test")
    completed = subprocess.run(  # nosec B603
        [command_processor, "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"directory reparse points unavailable: {completed.stderr}")


def _record_content_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    reads: list[Path] = []
    original = Path.read_bytes

    def recording_read(path: Path) -> bytes:
        reads.append(path.resolve())
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    return reads


def test_source_root_symlink_is_rejected_before_any_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "FINALIZED.json").write_text("{}\n", encoding="utf-8")
    linked_source = tmp_path / "linked-source"
    _symlink_or_skip(linked_source, source, directory=True)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        verify_finalized_batch(
            linked_source,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_public_builder_rejects_source_reparse_before_resolving_or_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    original = source_module._is_reparse_point

    def source_is_reparse(path: Path) -> bool:
        return path == source or original(path)

    monkeypatch.setattr(source_module, "_is_reparse_point", source_is_reparse)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        build_frozen_snapshot(
            source_root=source,
            output_root=tmp_path / "output",
            protocols_path=tmp_path / "protocols.json",
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_output_root_reparse_is_rejected_before_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    original = source_module._is_reparse_point

    def output_is_reparse(path: Path) -> bool:
        return path == output or original(path)

    monkeypatch.setattr(source_module, "_is_reparse_point", output_is_reparse)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        _validate_external_output_root(output, require_approved_root=False)


def test_reports_root_reparse_is_rejected_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    original = source_module._is_reparse_point

    def reports_are_reparse(path: Path) -> bool:
        return path == reports or original(path)

    monkeypatch.setattr(source_module, "_is_reparse_point", reports_are_reparse)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        build_frozen_snapshot(
            source_root=source,
            output_root=tmp_path / "output",
            reports_output=reports,
            protocols_path=tmp_path / "protocols.json",
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_repository_validation_trusts_only_ancestors_above_the_pinned_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (
        _REPOSITORY_ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
    )
    original = freeze_module._is_reparse_point

    monkeypatch.setattr(
        freeze_module,
        "_is_reparse_point",
        lambda path: path == _REPOSITORY_ROOT.parent or original(path),
    )
    unresolved, resolved = _validated_repository_path(
        expected, expected, mismatch_code="REPOSITORY_PATH_MISMATCH"
    )
    assert unresolved == expected
    assert resolved == expected.resolve()

    monkeypatch.setattr(
        freeze_module,
        "_is_reparse_point",
        lambda path: path == expected or original(path),
    )
    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        _validated_repository_path(expected, expected, mismatch_code="REPOSITORY_PATH_MISMATCH")


def test_remote_drive_is_rejected_before_reparse_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeze_module, "_is_remote_drive", lambda _path: True)

    def forbidden_metadata(_path: Path) -> None:
        raise AssertionError("remote-drive metadata was inspected")

    monkeypatch.setattr(freeze_module, "_reject_reparse_path", forbidden_metadata)
    with pytest.raises(
        SnapshotValidationError, match="FROZEN_SNAPSHOT_PROTOCOLS_NETWORK_SHARE_FORBIDDEN"
    ):
        _validated_local_path(
            Path(r"Z:\remote\protocols.json"),  # PORTABILITY_TEST_FIXTURE
            unc_code="FROZEN_SNAPSHOT_PROTOCOLS_NETWORK_SHARE_FORBIDDEN",
        )


def test_repository_path_mismatch_fails_before_remote_drive_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (
        _REPOSITORY_ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
    )

    def forbidden_probe(_path: Path) -> bool:
        raise AssertionError("mismatched path reached drive probing")

    monkeypatch.setattr(freeze_module, "_is_remote_drive", forbidden_probe)
    with pytest.raises(SnapshotValidationError, match="REPOSITORY_PATH_MISMATCH"):
        _validated_repository_path(
            Path(r"Z:\remote\protocols.json"),  # PORTABILITY_TEST_FIXTURE
            expected,
            mismatch_code="REPOSITORY_PATH_MISMATCH",
        )


def test_finalized_marker_symlink_is_rejected_before_target_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside_marker = tmp_path / "outside-finalized.json"
    outside_marker.write_text("{}\n", encoding="utf-8")
    _symlink_or_skip(source / "FINALIZED.json", outside_marker, directory=False)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        verify_finalized_batch(
            source,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_finalized_marker_reparse_guard_runs_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    marker = source / "FINALIZED.json"
    marker.write_text("{}\n", encoding="utf-8")
    original = source_module._is_reparse_point

    def marker_is_reparse(path: Path) -> bool:
        return path == marker or original(path)

    monkeypatch.setattr(source_module, "_is_reparse_point", marker_is_reparse)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        verify_finalized_batch(
            source,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_snapshot_tree_walker_rejects_nested_symlink_without_reading_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tmp_path / "snapshot"
    tree.mkdir()
    (tree / "manifest.json").write_text("{}\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text('{"secret":"must-not-be-read"}\n', encoding="utf-8")
    _symlink_or_skip(tree / "linked", outside, directory=True)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        _tree_bytes(tree)

    assert reads == []


def test_snapshot_tree_walker_reads_only_regular_files(tmp_path: Path) -> None:
    tree = tmp_path / "snapshot"
    nested = tree / "quality"
    nested.mkdir(parents=True)
    (tree / "manifest.json").write_bytes(b"{}\n")
    (nested / "report.json").write_bytes(b'{"status":"PASS"}\n')

    assert _tree_bytes(tree) == {
        "manifest.json": b"{}\n",
        "quality/report.json": b'{"status":"PASS"}\n',
    }


def test_snapshot_tree_walker_rejects_hardlink_before_content_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = tmp_path / "snapshot"
    tree.mkdir()
    outside = tmp_path / "outside-secret.json"
    outside.write_text('{"secret":"must-not-be-read"}\n', encoding="utf-8")
    os.link(outside, tree / "manifest.json")
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="FROZEN_SNAPSHOT_HARDLINK_FORBIDDEN"):
        _tree_bytes(tree)

    assert reads == []


def test_network_blockade_intercepts_udp_dns_and_low_level_socket_without_network() -> None:
    original_sendto = socket.socket.sendto
    original_getaddrinfo = socket.getaddrinfo
    original_socket_type = socket.SocketType
    original_low_level_getaddrinfo = _socket.getaddrinfo
    original_low_level_socket = _socket.socket
    original_low_level_socket_type = _socket.SocketType
    datagram = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with NetworkBlockade() as blockade:
            attempts = (
                (datagram.sendto, (b"offline-probe", ("127.0.0.1", 9))),
                (socket.getaddrinfo, ("offline.invalid", 443)),
                (_socket.getaddrinfo, ("offline.invalid", 443, 0, 0, 0, 0)),
                (socket.SocketType, ()),
                (_socket.SocketType, ()),
                (_socket.socket, ()),
            )
            for expected_attempts, (operation, arguments) in enumerate(attempts, start=1):
                with pytest.raises(
                    SnapshotValidationError,
                    match="FROZEN_SNAPSHOT_NETWORK_FORBIDDEN",
                ):
                    operation(*arguments)
                assert blockade.attempts == expected_attempts
    finally:
        datagram.close()

    assert socket.socket.sendto is original_sendto
    assert socket.getaddrinfo is original_getaddrinfo
    assert socket.SocketType is original_socket_type
    assert _socket.getaddrinfo is original_low_level_getaddrinfo
    assert _socket.socket is original_low_level_socket
    assert _socket.SocketType is original_low_level_socket_type


@pytest.mark.parametrize(
    "method_name",
    ("accept", "bind", "connect", "connect_ex", "listen", "send", "sendall", "sendto"),
)
def test_network_blockade_replaces_and_exactly_restores_socket_methods(
    method_name: str,
) -> None:
    original = getattr(socket.socket, method_name)

    with NetworkBlockade() as blockade:
        blocked = getattr(socket.socket, method_name)
        assert blocked is not original
        with pytest.raises(SnapshotValidationError, match="FROZEN_SNAPSHOT_NETWORK_FORBIDDEN"):
            blocked()
        assert blockade.attempts == 1

    assert getattr(socket.socket, method_name) is original


def test_runtime_schema_directory_junction_is_rejected_before_target_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    schema_name = "manifest.schema.json"
    (outside / schema_name).write_text("{}\n", encoding="utf-8")
    linked_schemas = repository / "schemas"
    _symlink_or_skip(linked_schemas, outside, directory=True)
    schema_path = linked_schemas / schema_name
    monkeypatch.setattr(freeze_module, "_REPOSITORY_ROOT", repository)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(SnapshotValidationError, match="BATCH_REPARSE_POINT_FORBIDDEN"):
        _load_output_schema(
            schema_path,
            schema_path,
            _MANIFEST_SCHEMA_CANONICAL_SHA256,
        )

    assert reads == []


def test_runtime_schema_hardlink_is_rejected_before_content_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    original_schema = tmp_path / "original.schema.json"
    original_schema.write_text("{}\n", encoding="utf-8")
    schema_path = repository / "manifest.schema.json"
    os.link(original_schema, schema_path)
    monkeypatch.setattr(freeze_module, "_REPOSITORY_ROOT", repository)
    reads = _record_content_reads(monkeypatch)

    with pytest.raises(
        SnapshotValidationError,
        match="FROZEN_SNAPSHOT_REPOSITORY_HARDLINK_FORBIDDEN",
    ):
        _load_output_schema(
            schema_path,
            schema_path,
            _MANIFEST_SCHEMA_CANONICAL_SHA256,
        )

    assert reads == []
