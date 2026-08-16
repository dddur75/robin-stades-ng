from __future__ import annotations

from pathlib import Path

import pytest

import robin.data_snapshot.source as source_module
from robin.data_snapshot.contracts import (
    EXPECTED_BATCH_ID,
    SYNTHETIC_BATCH_ID,
    SnapshotValidationError,
)
from robin.data_snapshot.freeze import build_frozen_snapshot
from robin.data_snapshot.source import verify_finalized_batch


def test_real_observation_cannot_be_shortened_or_faked_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []
    original = Path.read_bytes

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(
        SnapshotValidationError, match="FINALIZED_OBSERVATION_FIVE_MINUTES_REQUIRED"
    ):
        verify_finalized_batch(
            tmp_path / "missing-real-batch",
            expected_batch_id=EXPECTED_BATCH_ID,
            observation_seconds=0,
        )
    with pytest.raises(
        SnapshotValidationError, match="FINALIZED_OBSERVATION_CUSTOM_SLEEPER_FORBIDDEN"
    ):
        verify_finalized_batch(
            tmp_path / "missing-real-batch",
            expected_batch_id=EXPECTED_BATCH_ID,
            observation_seconds=300,
            sleeper=lambda _seconds: None,
        )
    with pytest.raises(SnapshotValidationError, match="BATCH_SOURCE_APPROVED_ROOT_MISMATCH"):
        verify_finalized_batch(
            tmp_path / "wrong-real-batch-root",
            expected_batch_id=EXPECTED_BATCH_ID,
            observation_seconds=300,
        )
    assert reads == []


def test_non_real_batch_identity_requires_private_synthetic_test_mode_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []
    original = Path.read_bytes

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(SnapshotValidationError, match="BATCH_ID_OVERRIDE_FORBIDDEN"):
        verify_finalized_batch(
            tmp_path / "synthetic-not-authorized",
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=300,
        )
    with pytest.raises(
        SnapshotValidationError, match="FROZEN_SNAPSHOT_BATCH_ID_OVERRIDE_FORBIDDEN"
    ):
        build_frozen_snapshot(
            source_root=tmp_path / "synthetic-not-authorized",
            output_root=tmp_path / "output",
            protocols_path=tmp_path / "protocols.json",
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=300,
        )
    assert reads == []


def test_direct_real_source_pin_and_remote_drive_fail_before_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_probe(_path: Path) -> bool:
        raise AssertionError("mismatched source reached drive probing")

    def forbidden_metadata(_path: Path) -> None:
        raise AssertionError("remote source reached reparse metadata")

    monkeypatch.setattr(source_module, "_is_remote_drive", forbidden_probe)
    monkeypatch.setattr(source_module, "_reject_reparse_path", forbidden_metadata)
    with pytest.raises(SnapshotValidationError, match="BATCH_SOURCE_APPROVED_ROOT_MISMATCH"):
        verify_finalized_batch(Path(r"Z:\wrong\batch"), observation_seconds=300)

    monkeypatch.setenv("LOCALAPPDATA", r"Z:\AppData\Local")
    monkeypatch.setattr(source_module, "_is_remote_drive", lambda _path: True)
    with pytest.raises(SnapshotValidationError, match="BATCH_SOURCE_NETWORK_SHARE_FORBIDDEN"):
        verify_finalized_batch(
            Path(r"Z:\AppData\Local\Robin\five-canary-receipt-batch-20260816"),
            observation_seconds=300,
        )


@pytest.mark.parametrize(
    ("protocols_path", "matrix_path", "reports_path", "error_code"),
    (
        (
            Path(r"\\server\share\protocols.json"),
            None,
            None,
            "FROZEN_SNAPSHOT_PROTOCOLS_NETWORK_SHARE_FORBIDDEN",
        ),
        (
            Path(__file__).parents[2]
            / "reports"
            / "hypothesis-lab"
            / "first-25-experiment-protocols-v1.json",
            Path(r"\\server\share\matrix.json"),
            None,
            "FROZEN_SNAPSHOT_MATRIX_NETWORK_SHARE_FORBIDDEN",
        ),
        (
            Path(__file__).parents[2]
            / "reports"
            / "hypothesis-lab"
            / "first-25-experiment-protocols-v1.json",
            None,
            Path(r"\\server\share\reports"),
            "FROZEN_SNAPSHOT_REPORTS_NETWORK_SHARE_FORBIDDEN",
        ),
    ),
)
def test_all_builder_auxiliary_paths_reject_unc_before_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protocols_path: Path,
    matrix_path: Path | None,
    reports_path: Path | None,
    error_code: str,
) -> None:
    reads: list[Path] = []
    original = Path.read_bytes

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(SnapshotValidationError, match=error_code):
        build_frozen_snapshot(
            source_root=tmp_path / "source",
            output_root=tmp_path / "output",
            reports_output=reports_path,
            protocols_path=protocols_path,
            readiness_matrix_path=matrix_path,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )
    assert reads == []


@pytest.mark.parametrize(
    ("output_suffix", "reports_suffix", "error_code"),
    (
        (".", None, "FROZEN_SNAPSHOT_SOURCE_OUTPUT_OVERLAP"),
        ("snapshots", None, "FROZEN_SNAPSHOT_SOURCE_OUTPUT_OVERLAP"),
        ("../output", "reports", "FROZEN_SNAPSHOT_SOURCE_REPORTS_OVERLAP"),
        ("../output", "../output/reports", "FROZEN_SNAPSHOT_OUTPUT_REPORTS_OVERLAP"),
    ),
)
def test_source_output_and_report_roots_must_be_disjoint_before_any_write(
    tmp_path: Path,
    output_suffix: str,
    reports_suffix: str | None,
    error_code: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    sentinel = source / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    output = (source / output_suffix).resolve()
    reports = (source / reports_suffix).resolve() if reports_suffix is not None else None
    with pytest.raises(SnapshotValidationError, match=error_code):
        build_frozen_snapshot(
            source_root=source,
            output_root=output,
            reports_output=reports,
            protocols_path=tmp_path / "not-read-protocols.json",
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
