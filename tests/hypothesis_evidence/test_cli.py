from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import robin.hypothesis_evidence.runtime as evidence_runtime
from robin.hypothesis_evidence.runtime import process_peak_memory_bytes


def test_cli_documents_cache_only_sources_and_resume() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "build_hypothesis_evidence.py"),
            "--help",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--git-blobs" in completed.stdout
    assert "--historical-root" in completed.stdout
    assert "--no-resume" in completed.stdout
    assert "without network, providers, R2 or database writes" in completed.stdout


def test_cli_memory_metric_is_explicit_and_positive() -> None:
    peak_bytes, measurement = process_peak_memory_bytes()
    assert isinstance(peak_bytes, int)
    assert peak_bytes > 0
    assert measurement in {"WINDOWS_PEAK_WORKING_SET", "RU_MAXRSS"}


def test_cli_memory_metric_fails_closed_without_windows_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evidence_runtime.os, "name", "nt")
    monkeypatch.delattr(evidence_runtime.ctypes, "WinDLL", raising=False)

    assert evidence_runtime.process_peak_memory_bytes() == (
        None,
        "WINDOWS_PEAK_WORKING_SET_UNAVAILABLE",
    )
