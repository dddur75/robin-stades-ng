from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path

import pytest
import yaml

import scripts.chronos_neon_branch_identity_v2 as identity
import scripts.chronos_production_recovery_v2 as bootstrap
import scripts.recovery_v2_supervision as supervision
import scripts.run_data_torrent_v2 as live
import scripts.seal_chronos_identity_go_v2 as seal
from robin.chronos_production import ChronosProductionError


class _Process:
    pid = 123

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes

    def wait(self, *, timeout: int) -> int:
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return int(outcome)

    @staticmethod
    def poll() -> None:
        return None


class _ClearFlag:
    @staticmethod
    def is_set() -> bool:
        return False


class _CapturedLateExit:
    def __init__(self) -> None:
        self.poll_calls = 0

    def poll(self) -> int:
        self.poll_calls += 1
        return 0


def _publish_test_namespace_pidfd(
    *_args: object,
    namespace_pidfd_holder: list[int | None],
    **_kwargs: object,
) -> int:
    namespace_pidfd_holder[0] = 41
    return 41


def test_captured_wait_rejects_late_exit_before_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _CapturedLateExit()
    capture = type("Capture", (), {"failure": _ClearFlag(), "overflow": _ClearFlag()})()
    monkeypatch.setattr(supervision.time, "monotonic", lambda: 101.0)
    assert supervision._wait_for_captured_root(  # type: ignore[arg-type]
        process,
        capture,
        capture,
        deadline_monotonic=100.0,
    ) == ("TIMEOUT", None)
    assert process.poll_calls == 0


def test_captured_wait_rejects_poll_that_returns_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Process:
        poll_calls = 0

        def poll(self) -> int:
            self.poll_calls += 1
            clock[0] = 102.0
            return 0

    process = Process()
    capture = type("Capture", (), {"failure": _ClearFlag(), "overflow": _ClearFlag()})()
    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    assert supervision._wait_for_captured_root(  # type: ignore[arg-type]
        process,
        capture,
        capture,
        deadline_monotonic=101.0,
    ) == ("TIMEOUT", None)
    assert process.poll_calls == 1


def test_shared_wait_rejects_success_returned_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Process:
        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout == 1.0
            clock[0] = 102.0
            return 0

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    with pytest.raises(supervision.subprocess.TimeoutExpired):
        supervision._wait_for_process_before_deadline(  # type: ignore[arg-type]
            Process(),
            command=("target",),
            timeout_seconds=1,
            deadline_monotonic=101.0,
        )


def test_posix_gate_poll_completed_after_deadline_is_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Process:
        @staticmethod
        def poll() -> int:
            clock[0] = 102.0
            return 0

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TIMEOUT",
    ):
        supervision._release_posix_namespace_gate(  # type: ignore[arg-type]
            object(),
            Process(),
            None,
            None,
            namespace_pidfd_holder=[None],
            environment={},
            deadline_monotonic=101.0,
        )


def test_posix_gate_publishes_pidfd_before_release_return_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace_pidfd_holder: list[int | None] = [None]
    release_markers: list[bytes] = []
    killed_descriptors: list[int] = []
    closed_descriptors: list[int] = []

    class Connection:
        @staticmethod
        def getsockopt(*_args: object) -> bytes:
            return supervision.struct.pack("3i", 23, 1000, 1000)

        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def sendmsg(parts: tuple[bytes, ...], _ancillary: object) -> int:
            assert namespace_pidfd_holder == [41]
            release_markers.extend(parts)
            return 1

        @staticmethod
        def sendall(_payload: bytes) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    connection = Connection()

    class Listener:
        @staticmethod
        def settimeout(_timeout: float) -> None:
            return None

        @staticmethod
        def accept() -> tuple[Connection, None]:
            return connection, None

    class Process:
        pid = 17

        @staticmethod
        def poll() -> None:
            return None

    monkeypatch.setattr(supervision.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        supervision,
        "_socket_read_exact",
        lambda *_args, **_kwargs: supervision._POSIX_NAMESPACE_READY,
    )
    monkeypatch.setattr(supervision, "_required_posix_identity", lambda: (1000, 1000, ()))
    monkeypatch.setattr(supervision, "_process_descends_from", lambda *_args: True)
    monkeypatch.setattr(supervision, "_pidfd_open", lambda _pid: 41)
    monkeypatch.setattr(supervision, "_peer_is_namespace_pid_one", lambda _pid: True)
    monkeypatch.setattr(
        supervision,
        "_pidfd_send_kill",
        lambda descriptor: killed_descriptors.append(descriptor) or True,
    )
    monkeypatch.setattr(supervision.os, "close", closed_descriptors.append)
    source, start_line = inspect.getsourcelines(supervision._release_posix_namespace_gate)
    return_line = next(
        start_line + offset
        for offset, line in enumerate(source)
        if line.strip() == "return pidfd"
    )

    def interrupt_on_return(frame: object, event: str, _argument: object) -> object:
        if (
            getattr(frame, "f_code", None)
            is supervision._release_posix_namespace_gate.__code__
            and event == "line"
            and getattr(frame, "f_lineno", None) == return_line
        ):
            raise KeyboardInterrupt
        return interrupt_on_return

    sys.settrace(interrupt_on_return)
    try:
        with pytest.raises(KeyboardInterrupt):
            supervision._release_posix_namespace_gate(  # type: ignore[arg-type]
                Listener(),
                Process(),
                None,
                None,
                namespace_pidfd_holder=namespace_pidfd_holder,
                environment={},
                deadline_monotonic=101.0,
            )
    finally:
        sys.settrace(None)
    assert release_markers == [b"\x01"]
    assert namespace_pidfd_holder == [41]
    assert killed_descriptors == []
    assert closed_descriptors == []


def test_windows_job_constructor_closes_handle_when_local_configuration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls = 0

    def base_init(instance: object) -> None:
        setattr(instance, "_handle", 1)

    def close(_instance: object) -> None:
        nonlocal close_calls
        close_calls += 1

    def fail_configuration(*_args: object, **_kwargs: object) -> object:
        raise supervision.WorkspaceBootstrapError(
            "WORKSPACE_COMMAND_CONTAINMENT_FAILED"
        )

    monkeypatch.setattr(supervision._BaseWindowsJobObject, "__init__", base_init)
    monkeypatch.setattr(supervision._WindowsJobObject, "close", close)
    monkeypatch.setattr(supervision.ctypes, "WinDLL", lambda *_a, **_k: object(), raising=False)
    monkeypatch.setattr(supervision, "_configured_windows_function", fail_configuration)
    with pytest.raises(supervision.WorkspaceBootstrapError):
        supervision._WindowsJobObject()
    assert close_calls == 1


def test_pipe_join_completed_after_cleanup_deadline_is_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Thread:
        @staticmethod
        def join(*, timeout: float) -> None:
            assert timeout == 1.0
            clock[0] = 102.0

        @staticmethod
        def is_alive() -> bool:
            return False

    capture = supervision._BoundedPipeCapture(BytesIO(), maximum_bytes=1)
    capture._started = True
    capture._thread = Thread()  # type: ignore[assignment]
    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",
    ):
        capture.join_and_read(cleanup_deadline_monotonic=101.0)


def test_pipe_drain_runtime_failure_is_never_accepted_as_truncated_success() -> None:
    class Stream:
        reads = 0

        def read(self, _size: int) -> bytes:
            self.reads += 1
            if self.reads == 1:
                return b"valid-prefix"
            raise RuntimeError("synthetic read failure")

        @staticmethod
        def close() -> None:
            return None

    capture = supervision._BoundedPipeCapture(  # type: ignore[arg-type]
        Stream(),
        maximum_bytes=64,
    )
    capture._drain()
    assert capture.failure.is_set()
    class DeadThread:
        @staticmethod
        def join(*, timeout: float) -> None:
            assert timeout > 0

        @staticmethod
        def is_alive() -> bool:
            return False

    capture._started = True
    capture._thread = DeadThread()  # type: ignore[assignment]
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_INVALID",
    ):
        capture.join_and_read(cleanup_deadline_monotonic=time.monotonic() + 1.0)


def test_pipe_close_completed_after_cleanup_deadline_dominates_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    close_calls: list[str] = []

    class Capture:
        def __init__(self, name: str, *, invalid: bool) -> None:
            self.name = name
            self.invalid = invalid

        def join_and_read(self, **_kwargs: object) -> bytes:
            if self.invalid:
                raise supervision.RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_INVALID"
                )
            return b"ok"

        def close(self) -> None:
            close_calls.append(self.name)
            if self.name == "stdout":
                clock[0] = 102.0

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",
    ):
        supervision._finish_pipe_captures(  # type: ignore[arg-type]
            Capture("stdout", invalid=True),
            Capture("stderr", invalid=False),
            cleanup_deadline_monotonic=101.0,
        )
    assert close_calls == ["stdout", "stderr"]


@pytest.mark.skipif(os.name != "nt", reason="Windows release deadline")
def test_windows_release_delay_cannot_reuse_stale_wait_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    wait_calls = 0

    class Stdin:
        @staticmethod
        def write(_payload: bytes) -> None:
            clock[0] = 102.0

        @staticmethod
        def close() -> None:
            return None

    class Gate:
        pid = 17
        stdin = Stdin()

        @staticmethod
        def wait(*, timeout: float) -> int:
            nonlocal wait_calls
            wait_calls += 1
            return 0

        @staticmethod
        def poll() -> int:
            return 124

        @staticmethod
        def kill() -> None:
            return None

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            return None

        @staticmethod
        def terminate_and_confirm_before_deadline(**_kwargs: object) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: Gate())
    assert (
        supervision._run_windows_child_once(("target.exe",), timeout_seconds=1)
        == supervision.SUPERVISOR_TIMEOUT_EXIT
    )
    assert wait_calls == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows wait deadline")
def test_windows_late_success_is_timeout_and_cleanup_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    cleanup_calls = 0

    class Stdin:
        @staticmethod
        def write(_payload: bytes) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    class Gate:
        pid = 17
        stdin = Stdin()

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout == 1.0
            clock[0] = 102.0
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            return None

        @staticmethod
        def terminate_and_confirm_before_deadline(**_kwargs: object) -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: Gate())
    assert (
        supervision._run_windows_child_once(("target.exe",), timeout_seconds=1)
        == supervision.SUPERVISOR_TIMEOUT_EXIT
    )
    assert cleanup_calls == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows quiescence deadline")
def test_windows_quiescence_returned_after_cleanup_deadline_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    close_calls = 0

    class Stdin:
        @staticmethod
        def write(_payload: bytes) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    class Gate:
        pid = 17
        stdin = Stdin()

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout == 1.0
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            return None

        @staticmethod
        def wait_for_quiescence(_timeout_seconds: float) -> bool:
            clock[0] = 122.0
            return True

        @staticmethod
        def close() -> None:
            nonlocal close_calls
            close_calls += 1

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: Gate())
    assert (
        supervision._run_windows_child_once(("target.exe",), timeout_seconds=1)
        == supervision.SUPERVISOR_CHILD_STUCK_EXIT
    )
    assert close_calls == 1


def test_windows_unexpected_wait_failure_terminates_live_job_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    termination_calls = 0

    class StartupInfo:
        lpAttributeList: dict[str, object]

    class Stdin:
        @staticmethod
        def write(_payload: bytes) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    class Gate:
        pid = 17
        stdin = Stdin()

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout > 0
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            return None

        @staticmethod
        def wait_for_quiescence(_timeout_seconds: float) -> bool:
            raise KeyboardInterrupt

        @staticmethod
        def terminate_and_confirm_before_deadline(**_kwargs: object) -> None:
            nonlocal termination_calls
            termination_calls += 1

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(
        supervision.subprocess,
        "STARTUPINFO",
        StartupInfo,
        raising=False,
    )
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_a, **_k: Gate())
    with pytest.raises(KeyboardInterrupt):
        supervision._run_windows_child_once_inner(
            ("target.exe",),
            timeout_seconds=1,
        )
    assert termination_calls == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows assignment cleanup deadline")
def test_windows_assignment_failure_rejects_late_gate_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Gate:
        pid = 17
        stdin = None

        @staticmethod
        def kill() -> None:
            return None

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout == 21.0
            clock[0] = 122.0
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            raise supervision.WorkspaceBootstrapError(
                "WORKSPACE_COMMAND_CONTAINMENT_FAILED"
            )

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: Gate())
    assert (
        supervision._run_windows_child_once(("target.exe",), timeout_seconds=1)
        == supervision.SUPERVISOR_CHILD_STUCK_EXIT
    )


def test_posix_late_success_is_timeout_and_cleanup_is_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    cleanup_calls = 0

    class Listener:
        def __enter__(self) -> Listener:
            return self

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

        @staticmethod
        def bind(path: str) -> None:
            Path(path).touch()

        @staticmethod
        def listen(_backlog: int) -> None:
            return None

    pid_namespace_directory = tmp_path / "pidns"
    pid_namespace_directory.mkdir()

    class TemporaryDirectory:
        def __enter__(self) -> str:
            return str(pid_namespace_directory)

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

    class Process:
        pid = 17

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout == 1.0
            clock[0] = 102.0
            return 0

    def terminate(*_args: object, **_kwargs: object) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return True

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision.socket, "socket", lambda *_args, **_kwargs: Listener())
    monkeypatch.setattr(
        supervision.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: TemporaryDirectory(),
    )
    monkeypatch.setattr(
        supervision,
        "_contained_posix_command",
        lambda *_args, **_kwargs: ("launcher",),
    )
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(
        supervision,
        "_release_posix_namespace_gate",
        _publish_test_namespace_pidfd,
    )
    monkeypatch.setattr(supervision, "_terminate_captured_posix_tree", terminate)
    monkeypatch.setattr(supervision.os, "close", lambda _descriptor: None)
    assert (
        supervision._run_posix_child_once(("target",), timeout_seconds=1)
        == supervision.SUPERVISOR_TIMEOUT_EXIT
    )
    assert cleanup_calls == 1


@pytest.mark.parametrize("interrupt_point", ("gate_return", "context_exit", "wait"))
def test_posix_unexpected_interrupt_after_release_cleans_tree_and_pidfd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_point: str,
) -> None:
    cleanup_calls = 0
    closed_descriptors: list[int] = []

    class Listener:
        def __enter__(self) -> Listener:
            return self

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

        @staticmethod
        def bind(path: str) -> None:
            Path(path).touch()

        @staticmethod
        def listen(_backlog: int) -> None:
            return None

    pid_namespace_directory = tmp_path / "pidns-interrupt"
    pid_namespace_directory.mkdir()

    class TemporaryDirectory:
        def __enter__(self) -> str:
            return str(pid_namespace_directory)

        @staticmethod
        def __exit__(*_args: object) -> None:
            if interrupt_point == "context_exit":
                raise KeyboardInterrupt

    class Process:
        pid = 17

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout > 0
            if interrupt_point == "wait":
                raise KeyboardInterrupt
            return 0

    def terminate(*_args: object, **_kwargs: object) -> bool:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return True

    def release_gate(
        *_args: object,
        namespace_pidfd_holder: list[int | None],
        **_kwargs: object,
    ) -> int:
        namespace_pidfd_holder[0] = 41
        if interrupt_point == "gate_return":
            raise KeyboardInterrupt
        return 41

    monkeypatch.setattr(supervision.socket, "socket", lambda *_a, **_k: Listener())
    monkeypatch.setattr(
        supervision.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: TemporaryDirectory(),
    )
    monkeypatch.setattr(
        supervision,
        "_contained_posix_command",
        lambda *_args, **_kwargs: ("launcher",),
    )
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_a, **_k: Process())
    monkeypatch.setattr(
        supervision,
        "_release_posix_namespace_gate",
        release_gate,
    )
    monkeypatch.setattr(supervision, "_terminate_captured_posix_tree", terminate)
    monkeypatch.setattr(supervision.os, "close", closed_descriptors.append)
    with pytest.raises(KeyboardInterrupt):
        supervision._run_posix_child_once(("target",), timeout_seconds=1)
    assert cleanup_calls == 1
    assert closed_descriptors.count(41) == 1


def test_posix_cleanup_failure_dominates_unexpected_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Listener:
        def __enter__(self) -> Listener:
            return self

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

        @staticmethod
        def bind(path: str) -> None:
            Path(path).touch()

        @staticmethod
        def listen(_backlog: int) -> None:
            return None

    pid_namespace_directory = tmp_path / "pidns-cleanup-failure"
    pid_namespace_directory.mkdir()

    class TemporaryDirectory:
        def __enter__(self) -> str:
            return str(pid_namespace_directory)

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

    class Process:
        pid = 17

        @staticmethod
        def wait(*, timeout: float) -> int:
            assert timeout > 0
            raise KeyboardInterrupt

    monkeypatch.setattr(supervision.socket, "socket", lambda *_a, **_k: Listener())
    monkeypatch.setattr(
        supervision.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: TemporaryDirectory(),
    )
    monkeypatch.setattr(
        supervision,
        "_contained_posix_command",
        lambda *_args, **_kwargs: ("launcher",),
    )
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_a, **_k: Process())
    monkeypatch.setattr(
        supervision,
        "_release_posix_namespace_gate",
        _publish_test_namespace_pidfd,
    )
    monkeypatch.setattr(
        supervision,
        "_terminate_captured_posix_tree",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(supervision.os, "close", lambda _descriptor: None)
    assert (
        supervision._run_posix_child_once(("target",), timeout_seconds=1)
        == supervision.SUPERVISOR_CHILD_STUCK_EXIT
    )


def test_pidfd_exit_probe_returned_after_cleanup_deadline_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    def late_exit(_pidfd: int) -> bool:
        clock[0] = 122.0
        return True

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_pidfd_exited", late_exit)
    assert not supervision._pidfd_exited_before_deadline(
        41,
        deadline_monotonic=121.0,
    )


def test_cleanup_proofs_refuse_quiescence_first_observed_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervision.time, "monotonic", lambda: 101.0)
    signals: list[bool] = []
    monkeypatch.setattr(
        supervision,
        "_signal_process_group",
        lambda _process, *, force: signals.append(force),
    )
    process = _Process([])
    assert not supervision._terminate_captured_posix_tree(  # type: ignore[arg-type]
        process,
        None,
        cleanup_deadline_monotonic=100.0,
    )
    assert signals == [True]

    class Job:
        active_calls = 0

        def active_processes(self) -> int:
            self.active_calls += 1
            return 0

    job = Job()
    with pytest.raises(supervision.WorkspaceBootstrapError):
        supervision._WindowsJobObject.terminate_and_confirm_before_deadline(  # type: ignore[arg-type]
            job,
            timeout_seconds=0.0,
            deadline_monotonic=100.0,
        )
    assert job.active_calls == 0

    capture = type("Capture", (), {"failure": _ClearFlag(), "overflow": _ClearFlag()})()
    assert (
        supervision._wait_for_captured_windows_quiescence(  # type: ignore[arg-type]
            job,
            capture,
            capture,
            cleanup_deadline_monotonic=100.0,
        )
        == "RESIDUAL"
    )
    assert job.active_calls == 0


def test_windows_termination_rejects_confirmation_completed_after_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Job:
        @staticmethod
        def terminate_and_confirm_before_deadline(**_kwargs: object) -> None:
            clock[0] = 102.0

        @staticmethod
        def active_processes() -> int:
            raise AssertionError("late confirmation must not be accepted")

    class Gate:
        @staticmethod
        def poll() -> int:
            raise AssertionError("late confirmation must not be accepted")

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    assert not supervision._terminate_captured_windows_tree(  # type: ignore[arg-type]
        Job(),
        Gate(),
        cleanup_deadline_monotonic=101.0,
    )


def test_windows_quiescence_probe_completed_after_deadline_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]

    class Job:
        @staticmethod
        def active_processes() -> int:
            clock[0] = 102.0
            return 0

    class Gate:
        @staticmethod
        def poll() -> int:
            raise AssertionError("late job proof must stop before polling the gate")

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    assert not supervision._captured_windows_tree_quiescent_before_deadline(  # type: ignore[arg-type]
        Job(),
        Gate(),
        cleanup_deadline_monotonic=101.0,
    )


def test_captured_windows_late_final_probe_forces_termination_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    termination_calls = 0

    class Stdin:
        @staticmethod
        def write(_payload: bytes) -> None:
            return None

        @staticmethod
        def close() -> None:
            return None

    class Gate:
        pid = 17
        stdin = Stdin()
        stdout = BytesIO()
        stderr = BytesIO()

        @staticmethod
        def poll() -> int:
            return 0

    class Job:
        @staticmethod
        def assign_process(_process_id: int) -> None:
            return None

        @staticmethod
        def active_processes() -> int:
            clock[0] = 122.0
            return 0

        @staticmethod
        def close() -> None:
            return None

    def terminate(*_args: object, **_kwargs: object) -> bool:
        nonlocal termination_calls
        termination_calls += 1
        return False

    monkeypatch.setattr(supervision.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(supervision, "_WindowsJobObject", Job)
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_a, **_k: Gate())
    monkeypatch.setattr(
        supervision,
        "_wait_for_captured_root",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    monkeypatch.setattr(supervision, "_terminate_captured_windows_tree", terminate)
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",
    ):
        supervision._run_captured_windows_child_once(
            ("target.exe",),
            deadline_monotonic=101.0,
            cleanup_deadline_monotonic=121.0,
            cwd=None,
            environment={},
            maximum_stdout_bytes=1,
            maximum_stderr_bytes=1,
        )
    assert termination_calls == 1


def test_gate_received_after_deadline_never_launches_target(tmp_path: Path) -> None:
    marker = tmp_path / "late-gate-release.txt"
    gate = supervision.subprocess.Popen(  # nosec B603
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            supervision._WINDOWS_GATE_SOURCE,
            "",
            str(time.monotonic_ns() + 50_000_000),
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('released')",
            str(marker),
        ),
        stdin=supervision.subprocess.PIPE,
        stdout=supervision.subprocess.PIPE,
        stderr=supervision.subprocess.PIPE,
    )
    time.sleep(0.1)
    _stdout, _stderr = gate.communicate(
        input=supervision._WINDOWS_GATE_RELEASE_TOKEN,
        timeout=2,
    )
    assert gate.returncode == 252
    assert not marker.exists()


def test_posix_namespace_termination_kills_pid_one_once_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process([])
    signals: list[bool] = []
    pidfd_kills: list[int] = []
    monkeypatch.setattr(process, "poll", lambda: 0)
    monkeypatch.setattr(supervision, "_pidfd_exited", lambda _pidfd: True)
    monkeypatch.setattr(supervision, "_posix_process_group_exists", lambda _process: False)
    monkeypatch.setattr(
        supervision,
        "_pidfd_send_kill",
        lambda pidfd: pidfd_kills.append(pidfd) or True,
    )
    monkeypatch.setattr(
        supervision,
        "_signal_process_group",
        lambda _process, *, force: signals.append(force),
    )
    assert supervision._terminate_captured_posix_tree(  # type: ignore[arg-type]
        process,
        41,
        cleanup_deadline_monotonic=time.monotonic() + 1.0,
    )
    assert pidfd_kills == [41]
    assert signals == [True]


def test_posix_namespace_termination_refuses_unconfirmed_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process([])
    signals: list[bool] = []
    monkeypatch.setattr(supervision, "_pidfd_send_kill", lambda _pidfd: True)
    monkeypatch.setattr(supervision, "_pidfd_exited", lambda _pidfd: False)
    monkeypatch.setattr(supervision, "_posix_process_group_exists", lambda _process: True)
    monkeypatch.setattr(supervision.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        supervision,
        "_signal_process_group",
        lambda _process, *, force: signals.append(force),
    )
    assert not supervision._terminate_captured_posix_tree(  # type: ignore[arg-type]
        process,
        42,
        cleanup_deadline_monotonic=100.0,
    )
    assert signals == [True]


def test_captured_posix_pipe_cleanup_failure_dominates_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish_calls = 0

    class Listener:
        def __enter__(self) -> Listener:
            return self

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

        @staticmethod
        def bind(path: str) -> None:
            Path(path).touch()

        @staticmethod
        def listen(_backlog: int) -> None:
            return None

    pid_namespace_directory = tmp_path / "pidns-captured-cleanup"
    pid_namespace_directory.mkdir()

    class TemporaryDirectory:
        def __enter__(self) -> str:
            return str(pid_namespace_directory)

        @staticmethod
        def __exit__(*_args: object) -> None:
            return None

    class Process:
        pid = 17
        stdout = BytesIO()
        stderr = BytesIO()

    class Capture:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        @staticmethod
        def start() -> None:
            return None

    def finish(*_args: object, **_kwargs: object) -> tuple[bytes, bytes]:
        nonlocal finish_calls
        finish_calls += 1
        if finish_calls == 1:
            raise KeyboardInterrupt
        raise supervision.RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
        )

    monkeypatch.setattr(supervision.socket, "socket", lambda *_a, **_k: Listener())
    monkeypatch.setattr(
        supervision.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: TemporaryDirectory(),
    )
    monkeypatch.setattr(
        supervision,
        "_contained_posix_command",
        lambda *_args, **_kwargs: ("launcher",),
    )
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_a, **_k: Process())
    monkeypatch.setattr(supervision, "_BoundedPipeCapture", Capture)
    monkeypatch.setattr(
        supervision,
        "_release_posix_namespace_gate",
        _publish_test_namespace_pidfd,
    )
    monkeypatch.setattr(
        supervision,
        "_wait_for_captured_root",
        lambda *_args, **_kwargs: ("TIMEOUT", None),
    )
    monkeypatch.setattr(
        supervision,
        "_terminate_captured_posix_tree",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        supervision,
        "_captured_posix_tree_quiescent_before_deadline",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(supervision, "_finish_pipe_captures", finish)
    monkeypatch.setattr(supervision.os, "close", lambda _descriptor: None)
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",
    ):
        supervision._run_captured_posix_child_once(
            ("target",),
            deadline_monotonic=time.monotonic() + 1.0,
            cleanup_deadline_monotonic=time.monotonic() + 2.0,
            cwd=None,
            environment={},
            maximum_stdout_bytes=1,
            maximum_stderr_bytes=1,
        )
    assert finish_calls == 2


def test_supervisor_drains_delayed_descendant_after_normal_parent_exit(tmp_path: Path) -> None:
    marker = tmp_path / "late-descendant-write.txt"
    child = (
        "import pathlib,time;"
        "time.sleep(0.75);"
        f"pathlib.Path({str(marker)!r}).write_text('late',encoding='utf-8')"
    )
    parent = (
        "import subprocess,sys;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
        "raise SystemExit(0)"
    )

    assert supervision.run_child_once((sys.executable, "-c", parent), timeout_seconds=5) == 0
    time.sleep(1.0)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("target_exit", "expected"),
    ((0, 0), (1, 1), (124, 1), (125, 1), (126, 1), (252, 1), (254, 1)),
)
def test_supervisor_reserves_sentinel_codes_from_target(
    target_exit: int,
    expected: int,
) -> None:
    assert (
        supervision.run_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                f"raise SystemExit({target_exit})",
            ),
            timeout_seconds=5,
        )
        == expected
    )


def test_supervisor_missing_target_uses_export_sentinel(tmp_path: Path) -> None:
    assert (
        supervision.run_child_once(
            (str(tmp_path / "missing-recovery-v2-executable"),),
            timeout_seconds=5,
        )
        == supervision.SUPERVISOR_EXPORT_EXIT
    )


def test_supervisor_timeout_uses_timeout_sentinel() -> None:
    assert (
        supervision.run_child_once(
            (sys.executable, "-I", "-B", "-c", "import time;time.sleep(60)"),
            timeout_seconds=1,
        )
        == supervision.SUPERVISOR_TIMEOUT_EXIT
    )


@pytest.mark.parametrize("stream", ("stdout", "stderr"))
@pytest.mark.parametrize("size", (65_536, 65_537))
def test_captured_child_enforces_each_raw_output_limit(stream: str, size: int) -> None:
    target = "sys.stdout" if stream == "stdout" else "sys.stderr"
    source = f"import sys; {target}.buffer.write(b'x' * {size}); {target}.flush()"
    if size == 65_537:
        with pytest.raises(
            supervision.RecoveryV2SupervisionError,
            match="RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
        ):
            supervision.run_captured_child_once(
                (sys.executable, "-I", "-B", "-c", source),
                timeout_seconds=5,
                cwd=None,
                environment=dict(os.environ),
                maximum_stdout_bytes=65_536,
                maximum_stderr_bytes=65_536,
            )
        return
    result = supervision.run_captured_child_once(
        (sys.executable, "-I", "-B", "-c", source),
        timeout_seconds=5,
        cwd=None,
        environment=dict(os.environ),
        maximum_stdout_bytes=65_536,
        maximum_stderr_bytes=65_536,
    )
    assert result.returncode == 0
    assert len(result.stdout if stream == "stdout" else result.stderr) == size


def test_captured_child_kills_residual_descendant_before_return(tmp_path: Path) -> None:
    marker = tmp_path / "captured-late-descendant-write.txt"
    child = (
        "import pathlib,time;"
        "time.sleep(0.75);"
        f"pathlib.Path({str(marker)!r}).write_text('late',encoding='utf-8')"
    )
    parent = (
        "import subprocess,sys;"
        f"subprocess.Popen([sys.executable,'-I','-B','-c',{child!r}]);"
        "raise SystemExit(0)"
    )
    invocation = {
        "timeout_seconds": 5,
        "cwd": tmp_path,
        "environment": dict(os.environ),
        "maximum_stdout_bytes": 65_536,
        "maximum_stderr_bytes": 65_536,
    }
    if os.name == "nt":
        with pytest.raises(
            supervision.RecoveryV2SupervisionError,
            match="RECOVERY_V2_CAPTURE_RESIDUAL_DESCENDANT",
        ):
            supervision.run_captured_child_once(
                (sys.executable, "-I", "-B", "-c", parent),
                **invocation,  # type: ignore[arg-type]
            )
    else:
        result = supervision.run_captured_child_once(
            (sys.executable, "-I", "-B", "-c", parent),
            **invocation,  # type: ignore[arg-type]
        )
        assert result.returncode == 0
    time.sleep(1.0)
    assert not marker.exists()


def test_captured_child_timeout_kills_sigterm_ignoring_tree_once(tmp_path: Path) -> None:
    marker = tmp_path / "captured-timeout-heartbeat.bin"
    descendant = (
        "import pathlib,signal,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "p=pathlib.Path(sys.argv[1]);"
        "f=p.open('ab',buffering=0);"
        "[(f.write(b'x'),time.sleep(0.025)) for _ in range(2400)]"
    )
    root = (
        "import pathlib,signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "pathlib.Path(sys.argv[2]).write_bytes(b'ROOT\\n');"
        "subprocess.Popen([sys.executable,'-I','-B','-c',sys.argv[1],sys.argv[2]],"
        "start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL,close_fds=True);"
        "time.sleep(60)"
    )
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TIMEOUT",
    ):
        supervision.run_captured_child_once(
            (sys.executable, "-I", "-B", "-c", root, descendant, str(marker)),
            timeout_seconds=1,
            cwd=tmp_path,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
        )
    observed = marker.read_bytes()
    assert observed.count(b"ROOT\n") == 1
    time.sleep(0.25)
    assert marker.read_bytes() == observed


def test_captured_child_overflow_kills_live_tree_before_timeout(tmp_path: Path) -> None:
    marker = tmp_path / "captured-overflow-heartbeat.bin"
    descendant = (
        "import pathlib,sys,time;"
        "p=pathlib.Path(sys.argv[1]);"
        "f=p.open('ab',buffering=0);"
        "[(f.write(b'x'),time.sleep(0.025)) for _ in range(2400)]"
    )
    root = (
        "import os,pathlib,subprocess,sys,time\n"
        "subprocess.Popen(\n"
        "    [sys.executable,'-I','-B','-c',sys.argv[1],sys.argv[2]],\n"
        "    start_new_session=True,\n"
        "    stdin=subprocess.DEVNULL,\n"
        "    stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL,\n"
        "    close_fds=True,\n"
        ")\n"
        "marker=pathlib.Path(sys.argv[2])\n"
        "deadline=time.monotonic()+1\n"
        "while not marker.exists():\n"
        "    if time.monotonic() >= deadline:\n"
        "        raise SystemExit(17)\n"
        "    time.sleep(.005)\n"
        "for _ in range(2048):\n"
        "    os.write(1,b'y'*8192)\n"
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
    ):
        supervision.run_captured_child_once(
            (sys.executable, "-I", "-B", "-c", root, descendant, str(marker)),
            timeout_seconds=5,
            cwd=tmp_path,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
        )
    assert time.monotonic() - started < 3.0
    observed = marker.read_bytes()
    assert observed
    time.sleep(0.25)
    assert marker.read_bytes() == observed


def test_captured_child_detects_cap_plus_one_before_sleeping_target_timeout() -> None:
    started = time.monotonic()
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
    ):
        supervision.run_captured_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import os,time;os.write(1,b'x'*65537);time.sleep(60)",
            ),
            timeout_seconds=2,
            cwd=None,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
        )
    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize("target_exit", (1, 124, 125, 126, 252, 254))
def test_captured_target_nonzero_exit_is_normalized(target_exit: int) -> None:
    result = supervision.run_captured_child_once(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            f"raise SystemExit({target_exit})",
        ),
        timeout_seconds=5,
        cwd=None,
        environment=dict(os.environ),
        maximum_stdout_bytes=65_536,
        maximum_stderr_bytes=65_536,
    )
    assert result.returncode == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows blocked-gate deadline")
def test_captured_windows_never_releases_target_after_work_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "captured-windows-late-release.txt"
    original_start = supervision._BoundedPipeCapture.start
    starts = 0

    def delayed_start(capture: supervision._BoundedPipeCapture) -> None:
        nonlocal starts
        original_start(capture)
        starts += 1
        if starts == 1:
            time.sleep(0.05)

    monkeypatch.setattr(supervision._BoundedPipeCapture, "start", delayed_start)
    observed = time.monotonic()
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TIMEOUT",
    ):
        supervision.run_captured_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('released')",
                str(marker),
            ),
            timeout_seconds=5,
            cwd=tmp_path,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
            absolute_deadline_monotonic=observed + 0.01,
            cleanup_deadline_monotonic=observed + 2.0,
        )
    assert not marker.exists()


def test_captured_windows_quiescence_tolerates_short_accounting_lag() -> None:
    observed = time.monotonic()

    class LaggingJob:
        @staticmethod
        def active_processes() -> int:
            return int(time.monotonic() - observed < 0.03)

        @staticmethod
        def has_live_processes() -> bool:
            return False

    stdout = supervision._BoundedPipeCapture(BytesIO(), maximum_bytes=1)
    stderr = supervision._BoundedPipeCapture(BytesIO(), maximum_bytes=1)
    assert (
        supervision._wait_for_captured_windows_quiescence(  # type: ignore[arg-type]
            LaggingJob(),
            stdout,
            stderr,
            cleanup_deadline_monotonic=time.monotonic() + 1.0,
        )
        == "QUIESCENT"
    )
    assert time.monotonic() - observed >= 0.025


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object assignment barrier")
def test_captured_windows_assignment_failure_never_launches_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "captured-target-launched.txt"

    def reject_assignment(_job: object, _process_id: int) -> None:
        raise supervision.WorkspaceBootstrapError("WORKSPACE_COMMAND_CONTAINMENT_FAILED")

    monkeypatch.setattr(
        supervision._WindowsJobObject,
        "assign_process",
        reject_assignment,
    )
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_START_FAILED",
    ):
        supervision.run_captured_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('launched')",
                str(marker),
            ),
            timeout_seconds=5,
            cwd=tmp_path,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
        )
    assert not marker.exists()


def test_captured_child_preserves_exact_cwd_and_environment(tmp_path: Path) -> None:
    environment = dict(os.environ)
    environment["RECOVERY_V2_CAPTURE_TEST"] = "exact-value"
    source = (
        "import json,os;"
        "print(json.dumps({'cwd':os.getcwd(),'value':os.environ.get("
        "'RECOVERY_V2_CAPTURE_TEST')}))"
    )
    result = supervision.run_captured_child_once(
        (sys.executable, "-I", "-B", "-c", source),
        timeout_seconds=5,
        cwd=tmp_path,
        environment=environment,
        maximum_stdout_bytes=65_536,
        maximum_stderr_bytes=65_536,
    )
    observed = json.loads(result.stdout)
    assert Path(observed["cwd"]).resolve() == tmp_path.resolve()
    assert observed["value"] == "exact-value"
    assert result.stderr == b""


@pytest.mark.skipif(sys.platform != "linux", reason="Linux PID namespace FD transfer")
def test_posix_namespace_transfers_output_capability_with_scm_rights() -> None:
    read_fd, write_fd = os.pipe()
    try:
        result = supervision.run_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import os,sys;os.write(int(sys.argv[1]),b'capability-ok')",
                str(write_fd),
            ),
            timeout_seconds=5,
            pass_fds=(write_fd,),
        )
        assert result == 0
        os.close(write_fd)
        write_fd = -1
        assert os.read(read_fd, 64) == b"capability-ok"
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux PID namespace double-fork")
def test_captured_pid_namespace_kills_double_fork_setsid_escape(tmp_path: Path) -> None:
    marker = tmp_path / "captured-double-fork-heartbeat.bin"
    source = (
        "import os,pathlib,sys,time\n"
        "pid=os.fork()\n"
        "if pid == 0:\n"
        "    os.setsid()\n"
        "    if os.fork() > 0:\n"
        "        os._exit(0)\n"
        "    heartbeat=pathlib.Path(sys.argv[1]).open('ab',buffering=0)\n"
        "    for _ in range(2400):\n"
        "        heartbeat.write(b'x')\n"
        "        time.sleep(0.025)\n"
        "time.sleep(60)\n"
    )
    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_CAPTURE_TIMEOUT",
    ):
        supervision.run_captured_child_once(
            (sys.executable, "-I", "-B", "-c", source, str(marker)),
            timeout_seconds=1,
            cwd=tmp_path,
            environment=dict(os.environ),
            maximum_stdout_bytes=65_536,
            maximum_stderr_bytes=65_536,
        )
    observed = marker.read_bytes()
    assert observed
    time.sleep(0.25)
    assert marker.read_bytes() == observed


@pytest.mark.skipif(sys.platform != "linux", reason="Linux containment capability")
def test_posix_containment_capability_failure_never_releases_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "posix-containment-unavailable.txt"
    monkeypatch.setattr(supervision, "_required_posix_identity", lambda: (1000, 1000, (1000,)))

    def unavailable(_name: str) -> str:
        raise supervision.RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )

    monkeypatch.setattr(supervision, "_trusted_posix_launcher", unavailable)
    assert (
        supervision._run_posix_child_once(
            (
                sys.executable,
                "-I",
                "-B",
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('released')",
                str(marker),
            ),
            timeout_seconds=1,
        )
        == supervision.SUPERVISOR_EXPORT_EXIT
    )
    assert not marker.exists()


def test_early_deadline_reserves_cleanup_and_publication_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH", "2000")
    monkeypatch.setattr(supervision.time, "time", lambda: 1500.9)
    assert live._LIVE_SUPERVISOR_TIMEOUT_SECONDS == 1_080
    assert supervision.remaining_effect_timeout(live._LIVE_SUPERVISOR_TIMEOUT_SECONDS) == 479


def test_live_supervisor_refuses_output_outside_checkout_before_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside" / "artifacts"
    child_calls = 0

    def child(*_args: object, **_kwargs: object) -> int:
        nonlocal child_calls
        child_calls += 1
        return 0

    monkeypatch.setattr(live, "ROOT", root)
    monkeypatch.setattr(live, "run_child_once", child)
    assert live._supervise(
        config=root / "config.json",
        output_dir=outside,
        failure_report=tmp_path / "failure.json",
    ) == live.SUPERVISOR_EXPORT_EXIT
    assert child_calls == 0
    assert not outside.exists()


def test_live_direct_cli_refuses_output_outside_checkout_before_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    outside = tmp_path / "outside" / "artifacts"
    executor_calls = 0

    def execute(**_kwargs: object) -> dict[str, object]:
        nonlocal executor_calls
        executor_calls += 1
        return {"data_torrent_ready": True}

    monkeypatch.setattr(live, "ROOT", root)
    monkeypatch.setattr(live, "execute_data_torrent_v2", execute)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_data_torrent_v2.py", "--output-dir", str(outside)],
    )
    with pytest.raises(SystemExit) as caught:
        live.main()
    assert caught.value.code == 2
    assert executor_calls == 0
    assert not outside.exists()


def test_live_child_flag_without_inherited_capability_never_reaches_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    output = root / ".torrent" / "candidate" / "artifacts"
    root.mkdir()
    executor_calls = 0

    def execute(**_kwargs: object) -> dict[str, object]:
        nonlocal executor_calls
        executor_calls += 1
        return {"data_torrent_ready": True}

    monkeypatch.setattr(live, "ROOT", root)
    monkeypatch.setattr(live, "execute_data_torrent_v2", execute)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_data_torrent_v2.py",
            "--output-dir",
            str(output),
            "--supervised-child",
        ],
    )
    assert live.main() == live.SUPERVISOR_EXPORT_EXIT
    assert executor_calls == 0
    assert not output.exists()


def test_live_supervisor_adopts_precheckout_fallback_outside_checkout_and_reaches_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    runner_temp = tmp_path / "runner-temp" / "recovery-v2"
    runner_temp.mkdir(parents=True)
    failure_report = runner_temp / "torrent-run-failure-v2.json"
    fallback = supervision.canonical_json_bytes(live._supervisor_fallback())
    failure_report.write_bytes(fallback)
    child_calls = 0

    def child(*_args: object, **_kwargs: object) -> int:
        nonlocal child_calls
        child_calls += 1
        return live.SUPERVISOR_TIMEOUT_EXIT

    monkeypatch.setattr(live, "ROOT", root)
    monkeypatch.setattr(live, "run_child_once", child)
    assert live._supervise(
        config=root / "config.json",
        output_dir=root / ".torrent" / "artifacts",
        failure_report=failure_report,
    ) == live.SUPERVISOR_TIMEOUT_EXIT
    assert child_calls == 1
    assert failure_report.read_bytes() == fallback


@pytest.mark.parametrize(
    ("deadline", "expected"),
    ((1522, 1), (1521, 0), (1520, 0)),
)
def test_child_cutoff_preserves_the_exact_effect_finalization_margin(
    monkeypatch: pytest.MonkeyPatch,
    deadline: int,
    expected: int,
) -> None:
    monkeypatch.setenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH", str(deadline))
    monkeypatch.setattr(supervision.time, "time", lambda: 1500.9)
    assert (
        supervision.remaining_effect_timeout(live._LIVE_SUPERVISOR_TIMEOUT_SECONDS)
        == expected
    )
    assert supervision._FINALIZATION_MARGIN_SECONDS == 20


def test_candidate_is_validated_before_atomic_fallback_replacement(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    candidate = tmp_path / "candidate.json"
    fallback_sha = supervision.write_json_exclusive(destination, {"status": "FAILED"})
    candidate.write_bytes(b'{"status":"PASS"}\n')

    def reject(_path: Path) -> None:
        raise ValueError("invalid candidate")

    with pytest.raises(ValueError, match="invalid candidate"):
        supervision.promote_validated_file(
            candidate,
            destination,
            expected_fallback_sha256=fallback_sha,
            validator=reject,
        )
    assert destination.read_bytes() == b'{"status":"FAILED"}\n'


def test_candidate_crossing_effect_deadline_is_never_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "receipt.json"
    candidate = tmp_path / "candidate.json"
    fallback_sha = supervision.write_json_exclusive(destination, {"status": "FAILED"})
    candidate.write_bytes(b'{"status":"PASS"}\n')
    clock = [199.0]
    monkeypatch.setenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH", "200")
    monkeypatch.setattr(supervision.time, "time", lambda: clock[0])

    def validate(_path: Path) -> dict[str, str]:
        clock[0] = 201.0
        return {"status": "PASS"}

    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_SUPERVISOR_DEADLINE_EXPIRED",
    ):
        supervision.promote_validated_file(
            candidate,
            destination,
            expected_fallback_sha256=fallback_sha,
            validator=validate,
        )
    assert destination.read_bytes() == b'{"status":"FAILED"}\n'
    assert candidate.exists()


def test_exact_early_fallback_is_adopted_without_rewrite(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    expected = {"effect_counter_certainty": "UNKNOWN_OR_UPPER_BOUND", "status": "FAILED"}
    expected_bytes = supervision.canonical_json_bytes(expected)
    destination.write_bytes(expected_bytes)

    observed = supervision.adopt_or_create_json_fallback(destination, expected)

    assert observed == hashlib.sha256(expected_bytes).hexdigest()
    assert destination.read_bytes() == expected_bytes


def test_early_fallback_drift_is_rejected_without_rewrite(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    destination.write_bytes(b'{"status":"MUTATED"}\n')

    with pytest.raises(supervision.RecoveryV2SupervisionError, match="FALLBACK_DRIFT"):
        supervision.adopt_or_create_json_fallback(destination, {"status": "FAILED"})


def test_guard_failure_restores_separate_immutable_fallback_template(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    template = tmp_path / ".receipt.json.fallback-template"
    expected = supervision.canonical_json_bytes({"status": "FAILED"})
    template.write_bytes(expected)
    destination.write_bytes(b'{"status":"SUCCESS_BUT_INVALID"}\n')

    observed = supervision.restore_fallback_template(
        template,
        destination,
        expected_sha256=hashlib.sha256(expected).hexdigest(),
    )

    assert observed == hashlib.sha256(expected).hexdigest()
    assert destination.read_bytes() == expected
    assert template.read_bytes() == expected


def test_fallback_restore_rejects_template_drift_without_touching_destination(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "receipt.json"
    template = tmp_path / ".receipt.json.fallback-template"
    destination.write_bytes(b"current\n")
    template.write_bytes(b"drift\n")

    with pytest.raises(
        supervision.RecoveryV2SupervisionError,
        match="RECOVERY_V2_SUPERVISOR_FALLBACK_DRIFT",
    ):
        supervision.restore_fallback_template(
            template,
            destination,
            expected_sha256=hashlib.sha256(b"expected\n").hexdigest(),
        )

    assert destination.read_bytes() == b"current\n"


def test_valid_candidate_atomically_replaces_fallback_on_windows_too(tmp_path: Path) -> None:
    destination = tmp_path / "receipt.json"
    candidate = tmp_path / "candidate.json"
    fallback_sha = supervision.write_json_exclusive(destination, {"status": "FAILED"})
    candidate.write_bytes(b'{"status":"PASS"}\n')

    result = supervision.promote_validated_file(
        candidate,
        destination,
        expected_fallback_sha256=fallback_sha,
        validator=lambda path: path.read_bytes(),
    )

    assert result == b'{"status":"PASS"}\n'
    assert destination.read_bytes() == b'{"status":"PASS"}\n'
    assert not candidate.exists()


def test_precheckout_workflow_fallbacks_match_python_factories_exactly() -> None:
    root = Path(__file__).resolve().parents[2]
    identity_workflow = yaml.safe_load(
        (root / ".github/workflows/chronos-neon-branch-identity-v2.yml").read_text(
            encoding="utf-8"
        )
    )
    seal_workflow = yaml.safe_load(
        (root / ".github/workflows/chronos-identity-seal-v2.yml").read_text(encoding="utf-8")
    )
    bootstrap_workflow = yaml.safe_load(
        (root / ".github/workflows/chronos-production-bootstrap-v4.yml").read_text(
            encoding="utf-8"
        )
    )
    live_workflow = yaml.safe_load(
        (root / ".github/workflows/data-torrent-live-v2.yml").read_text(encoding="utf-8")
    )

    identity_template = identity._failure_report(
        RuntimeError("synthetic"),
        identity.IdentityExecutionState(),
        conservative_timeout=True,
        observed_at="2026-01-01T00:00:00Z",
    )
    identity_template["observed_at"] = ""
    identity_literal = identity_workflow["jobs"]["identity"]["steps"][0]["env"][
        "FALLBACK_TEMPLATE_B64"
    ]
    assert base64.b64decode(identity_literal, validate=True) == supervision.canonical_json_bytes(
        identity_template
    )
    seal_literal = seal_workflow["jobs"]["seal"]["steps"][0]["env"]["FALLBACK_B64"]
    assert base64.b64decode(seal_literal, validate=True) == supervision.canonical_json_bytes(
        seal._supervisor_fallback()
    )
    for mode in ("PREFLIGHT", "MIGRATE", "VERIFY"):
        literal = bootstrap_workflow["env"][f"RECOVERY_V2_{mode}_FALLBACK_B64"]
        assert base64.b64decode(literal, validate=True) == supervision.canonical_json_bytes(
            bootstrap._supervisor_fallback(mode)
        )
    live_literal = live_workflow["env"]["RECOVERY_V2_LIVE_FALLBACK_B64"]
    assert base64.b64decode(live_literal, validate=True) == supervision.canonical_json_bytes(
        live._supervisor_fallback()
    )

    for workflow, job_names in (
        (identity_workflow, ("identity",)),
        (seal_workflow, ("seal",)),
        (bootstrap_workflow, ("preflight", "migrate", "verify")),
        (live_workflow, ("torrent",)),
    ):
        for job_name in job_names:
            job = workflow["jobs"][job_name]
            first = job["steps"][0]
            assert first["name"] == "Precreate the conservative one-shot receipt and deadline"
            assert "runner.temp" in first["env"]["RECEIPT_PATH"]
            assert "os.O_EXCL" in first["run"]
            assert "os.link" in first["run"]
            assert "os.fsync" in first["run"]
            assert "GITHUB_ENV" in first["run"]
    assert "if" not in identity_workflow["jobs"]["identity"]
    assert "if" not in seal_workflow["jobs"]["seal"]
    for job_name in ("preflight", "migrate", "verify"):
        assert "always()" in bootstrap_workflow["jobs"][job_name]["if"]
    assert "always()" in live_workflow["jobs"]["torrent"]["if"]


def test_live_supervisor_rejects_a_different_safe_failure_code(tmp_path: Path) -> None:
    document = live._supervisor_fallback()
    document["error_code"] = "DATA_TORRENT_OTHER_SAFE_FAILURE"
    path = tmp_path / "live-supervised-failure.json"
    path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )

    with pytest.raises(ChronosProductionError, match="DATA_TORRENT_FAILURE_EXPORT_INVALID"):
        live._load_guarded_failure(path)
