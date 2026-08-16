from __future__ import annotations

import os
from pathlib import Path

import pytest

from robin.data_snapshot.contracts import SnapshotValidationError
from robin.data_snapshot.freeze import _validate_external_output_root


def test_real_snapshot_output_is_pinned_to_approved_localappdata_root() -> None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        pytest.skip("LOCALAPPDATA is required by the Windows production contract")
    approved = Path(local_appdata) / "Robin" / "snapshots"
    assert _validate_external_output_root(approved) == approved.resolve()


def test_real_snapshot_output_rejects_an_arbitrary_local_root(tmp_path: Path) -> None:
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_OUTPUT_APPROVED_ROOT_MISMATCH"):
        _validate_external_output_root(tmp_path / "snapshots")


def test_real_reproducibility_output_is_bounded_to_named_localappdata_children() -> None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        pytest.skip("LOCALAPPDATA is required by the Windows production contract")
    allowed = Path(local_appdata) / "Robin" / "snapshot-reproducibility" / "run-one"
    assert _validate_external_output_root(allowed, reproducibility_run=True) == allowed.resolve()
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_OUTPUT_APPROVED_ROOT_MISMATCH"):
        _validate_external_output_root(
            Path(local_appdata) / "Robin" / "snapshots",
            reproducibility_run=True,
        )
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_OUTPUT_APPROVED_ROOT_MISMATCH"):
        _validate_external_output_root(
            Path(local_appdata) / "Robin" / "other" / "run-one",
            reproducibility_run=True,
        )


@pytest.mark.parametrize("sync_name", ("OneDrive - Org", "Dropbox", "Google Drive", "iCloud"))
def test_snapshot_output_rejects_synchronized_roots(tmp_path: Path, sync_name: str) -> None:
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_OUTPUT_SYNCHRONIZED_FORBIDDEN"):
        _validate_external_output_root(
            tmp_path / sync_name / "snapshots", require_approved_root=False
        )


def test_synthetic_test_output_may_use_a_non_synchronized_temp_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "snapshots"
    assert _validate_external_output_root(target, require_approved_root=False) == target.resolve()


def test_unc_output_is_rejected_before_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    unc = Path(r"\\server\share\snapshots")

    def forbidden_resolve(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("UNC path was resolved before rejection")

    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    with pytest.raises(SnapshotValidationError, match="SNAPSHOT_OUTPUT_NETWORK_SHARE_FORBIDDEN"):
        _validate_external_output_root(unc, require_approved_root=False)
