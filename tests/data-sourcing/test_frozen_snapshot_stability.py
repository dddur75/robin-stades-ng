from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast, get_type_hints

import pytest

import robin.data_snapshot.stability as stability_module
from robin.data_snapshot.contracts import SnapshotValidationError
from robin.data_snapshot.stability import (
    _resolve_windows_api,
    _windows_drive_type,
    continuous_tree_observer,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" and not sys.platform.startswith("linux"),
    reason="continuous observation is intentionally fail-closed on unsupported platforms",
)


class _FakeCtypesFunction:
    def __init__(
        self,
        result: object = 1,
        *,
        callback: Callable[[tuple[object, ...]], object] | None = None,
    ) -> None:
        self.argtypes: object = None
        self.restype: object = None
        self.result = result
        self.callback = callback
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        if self.callback is not None:
            return self.callback(args)
        return self.result


class _FakeKernel32:
    def __init__(self) -> None:
        self.CreateFileW = _FakeCtypesFunction(101)
        self.CreateEventW = _FakeCtypesFunction(202)
        self.ReadDirectoryChangesW = _FakeCtypesFunction(1)
        self.WaitForSingleObject = _FakeCtypesFunction(258)
        self.CancelIoEx = _FakeCtypesFunction(1)
        self.GetOverlappedResult = _FakeCtypesFunction(0)
        self.GetFileInformationByHandle = _FakeCtypesFunction(1)
        self.CloseHandle = _FakeCtypesFunction(1)
        self.GetDriveTypeW = _FakeCtypesFunction(4)


class _FakeCtypesModule:
    def __init__(self) -> None:
        self.kernel32 = _FakeKernel32()
        self.last_error = 0
        self.load_calls: list[tuple[str, bool]] = []
        self.kernel32.GetFileInformationByHandle = _FakeCtypesFunction(
            callback=self._complete_file_information
        )
        self.kernel32.GetOverlappedResult = _FakeCtypesFunction(
            callback=self._abort_overlapped_operation
        )

    def _complete_file_information(self, args: tuple[object, ...]) -> object:
        information = cast(
            stability_module._WindowsByHandleFileInformation,
            getattr(args[1], "_obj"),
        )
        information.dwFileAttributes = 0
        information.nNumberOfLinks = 1
        return 1

    def _abort_overlapped_operation(self, _args: tuple[object, ...]) -> object:
        self.last_error = 995
        return 0

    def WinDLL(self, name: str, *, use_last_error: bool) -> object:
        self.load_calls.append((name, use_last_error))
        return self.kernel32

    def get_last_error(self) -> int:
        return self.last_error

    def set_last_error(self, value: int) -> int:
        previous = self.last_error
        self.last_error = value
        return previous


def test_windows_api_resolution_is_not_attempted_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCtypesModule()
    monkeypatch.setattr(sys, "platform", "linux")

    with pytest.raises(SnapshotValidationError, match="WINDOWS_STABILITY_API_UNAVAILABLE"):
        _resolve_windows_api(fake)

    assert fake.load_calls == []


def test_complete_fake_windows_api_resolves_and_wraps_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCtypesModule()
    monkeypatch.setattr(sys, "platform", "win32")

    api = _resolve_windows_api(fake)
    assert fake.load_calls == [("kernel32", True)]
    assert fake.kernel32.CreateFileW.argtypes is not None
    assert fake.kernel32.CreateFileW.restype is not None
    assert api.set_last_error(37) == 0
    assert api.get_last_error() == 37
    assert _windows_drive_type("Z:\\", api=api) == 4
    assert fake.kernel32.GetDriveTypeW.calls == [("Z:\\",)]


def test_incomplete_fake_windows_api_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCtypesModule()
    delattr(fake.kernel32, "CancelIoEx")
    monkeypatch.setattr(sys, "platform", "win32")

    with pytest.raises(SnapshotValidationError, match="WINDOWS_STABILITY_API_UNAVAILABLE"):
        _resolve_windows_api(fake)


def test_fake_windows_observer_preserves_calls_flags_and_release_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeCtypesModule()
    monkeypatch.setattr(sys, "platform", "win32")
    api = _resolve_windows_api(fake)
    root = tmp_path / "terminal-batch"
    root.mkdir()
    payload = root / "payload.bin"
    payload.write_bytes(b"stable")

    observation = stability_module._WindowsTreeObservation(root, windows_api=api)
    observation.assert_unchanged()
    observation.close()

    assert fake.kernel32.CreateFileW.calls == [
        (
            os.path.abspath(os.fspath(root)),
            0x0001,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000 | 0x00200000 | 0x40000000,
            None,
        ),
        (
            os.path.abspath(os.fspath(payload)),
            0x80000000,
            0x00000001,
            None,
            3,
            0x00200000,
            None,
        ),
    ]
    directory_change_call = fake.kernel32.ReadDirectoryChangesW.calls[0]
    assert directory_change_call[0] == 101
    assert directory_change_call[2:6] == (64 * 1024, True, 0x0000014F, None)
    assert directory_change_call[7] is None
    assert fake.kernel32.CancelIoEx.calls[0][0] == 101
    assert fake.kernel32.CloseHandle.calls == [(101,), (202,), (101,)]


def test_public_stability_signatures_do_not_expose_any() -> None:
    public_hints = {
        **get_type_hints(stability_module.continuous_tree_observer),
        **get_type_hints(stability_module._new_observation),
    }
    assert all("Any" not in repr(value) for value in public_hints.values())


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
