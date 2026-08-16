from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from robin.data_snapshot.contracts import SnapshotValidationError
from robin.data_snapshot.stability import continuous_tree_observer

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not sys.platform.startswith("linux"),
    reason="continuous observation is intentionally fail-closed on unsupported platforms",
)


def test_continuous_tree_observer_accepts_an_unchanged_tree(tmp_path: Path) -> None:
    root = tmp_path / "terminal-batch"
    nested = root / "raw"
    nested.mkdir(parents=True)
    payload = nested / "payload.bin"
    payload.write_bytes(b"stable-bytes")

    with continuous_tree_observer(root) as observation:
        assert payload.read_bytes() == b"stable-bytes"
        observation.assert_unchanged()


def test_continuous_tree_observer_detects_mutation_restored_before_final_scan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "terminal-batch"
    root.mkdir()
    manifest = root / "capture-manifest.json"
    original = b'{"status":"FINALIZED"}\n'
    manifest.write_bytes(original)

    try:
        with continuous_tree_observer(root) as observation:
            try:
                manifest.write_bytes(b'{"status":"TRANSIENT"}\n')
                manifest.write_bytes(original)
            except OSError:
                assert manifest.read_bytes() == original
                return
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                observation.assert_unchanged()
                time.sleep(0.01)
            pytest.fail("filesystem notification was not delivered")
    except SnapshotValidationError as error:
        assert str(error) == "FINALIZED_BATCH_MUTATED"


def test_continuous_tree_observer_rejects_an_existing_external_hardlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "terminal-batch"
    root.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"stable-bytes")
    try:
        os.link(outside, root / "payload.bin")
    except OSError as error:
        pytest.skip(f"hardlinks unavailable: {error}")

    with pytest.raises(
        SnapshotValidationError,
        match="CONTINUOUS_TREE_OBSERVATION_ARM_FAILED",
    ):
        with continuous_tree_observer(root):
            pass


def test_external_hardlink_mutation_is_prevented_or_detected(tmp_path: Path) -> None:
    root = tmp_path / "terminal-batch"
    root.mkdir()
    inside = root / "payload.bin"
    original = b"stable-bytes"
    inside.write_bytes(original)
    outside = tmp_path / "outside.bin"

    try:
        try:
            with continuous_tree_observer(root) as observation:
                try:
                    os.link(inside, outside)
                    outside.write_bytes(b"transient")
                    outside.write_bytes(original)
                    outside.unlink()
                except OSError:
                    assert inside.read_bytes() == original
                    return
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    observation.assert_unchanged()
                    time.sleep(0.01)
                pytest.fail("hardlink mutation was neither prevented nor detected")
        except SnapshotValidationError as error:
            assert str(error) == "FINALIZED_BATCH_MUTATED"
    finally:
        outside.unlink(missing_ok=True)


def test_continuous_tree_observer_rejects_an_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "terminal-batch"
    root.mkdir()
    monkeypatch.setattr(sys, "platform", "unsupported-test-platform")

    with pytest.raises(
        SnapshotValidationError,
        match="CONTINUOUS_TREE_OBSERVATION_UNSUPPORTED",
    ):
        with continuous_tree_observer(root):
            pass
