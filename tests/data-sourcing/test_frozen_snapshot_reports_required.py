from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from robin.data_snapshot.contracts import (
    EXPECTED_EXTERNAL_BATCH_DIRECTORY,
    SYNTHETIC_BATCH_ID,
    SnapshotValidationError,
)
from robin.data_snapshot.freeze import build_frozen_snapshot

ROOT = Path(__file__).parents[2]
CLI_PATH = ROOT / "tools" / "data-sourcing" / "build_frozen_snapshot_v1.py"


def test_real_build_requires_reports_output_before_any_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("real input must not be read before the reports guard")

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(SnapshotValidationError, match="FROZEN_SNAPSHOT_REPORTS_OUTPUT_REQUIRED"):
        build_frozen_snapshot(
            source_root=tmp_path / "real-source",
            output_root=tmp_path / "output",
            protocols_path=tmp_path / "protocols.json",
        )

    assert reads == []


def test_private_synthetic_mode_alone_may_omit_reports_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("overlap guard should precede any source read")

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(SnapshotValidationError, match="FROZEN_SNAPSHOT_SOURCE_OUTPUT_OVERLAP"):
        build_frozen_snapshot(
            source_root=tmp_path / "synthetic-source",
            output_root=tmp_path / "synthetic-source",
            protocols_path=tmp_path / "protocols.json",
            reports_output=None,
            expected_batch_id=SYNTHETIC_BATCH_ID,
            observation_seconds=0,
            test_only_allow_short_observation=True,
        )

    assert reads == []


def test_real_cli_requires_explicit_reports_output(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("frozen_snapshot_cli", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(CLI_PATH),
            "--source",
            "source",
            "--output-root",
            "output",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        module.parse_args()

    assert raised.value.code == 2


def test_cli_exposes_only_the_exact_synthetic_contract_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location("frozen_snapshot_cli_synthetic", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(CLI_PATH),
            "--source",
            "synthetic-source",
            "--output-root",
            "synthetic-output",
            "--reports-output",
            "synthetic-reports",
            "--observation-seconds",
            "0",
            "--synthetic-contract",
        ],
    )

    args = module.parse_args()

    assert args.synthetic_contract is True
    assert args.observation_seconds == 0
    assert not hasattr(args, "expected_batch_id")


@pytest.mark.parametrize("check", (False, True))
def test_durable_and_check_reports_are_pinned_to_the_repository_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, check: bool
) -> None:
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    reads: list[Path] = []

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("real input must not be read before the reports pin")

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(SnapshotValidationError, match="FROZEN_SNAPSHOT_REPORTS_ROOT_MISMATCH"):
        build_frozen_snapshot(
            source_root=local_appdata / "Robin" / EXPECTED_EXTERNAL_BATCH_DIRECTORY,
            output_root=local_appdata / "Robin" / "snapshots",
            protocols_path=ROOT
            / "reports"
            / "hypothesis-lab"
            / "first-25-experiment-protocols-v1.json",
            reports_output=tmp_path / "wrong-reports",
            check=check,
        )

    assert reads == []


def test_reproducibility_reports_must_match_the_output_run_before_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    reads: list[Path] = []

    def recording_read(path: Path) -> bytes:
        reads.append(path)
        raise AssertionError("real input must not be read before the reports run pin")

    monkeypatch.setattr(Path, "read_bytes", recording_read)
    with pytest.raises(
        SnapshotValidationError,
        match="FROZEN_SNAPSHOT_REPRODUCIBILITY_REPORTS_ROOT_MISMATCH",
    ):
        build_frozen_snapshot(
            source_root=local_appdata / "Robin" / EXPECTED_EXTERNAL_BATCH_DIRECTORY,
            output_root=local_appdata / "Robin" / "snapshot-reproducibility" / "run-one",
            protocols_path=ROOT
            / "reports"
            / "hypothesis-lab"
            / "first-25-experiment-protocols-v1.json",
            reports_output=local_appdata / "Robin" / "snapshot-reproducibility-reports" / "run-two",
            reproducibility_run=True,
        )

    assert reads == []
