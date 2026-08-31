"""Portable one-shot supervision primitives for Recovery V2 effect stages."""

from __future__ import annotations

import array
import ctypes
import hashlib
import json
import math
import os
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, TypeVar, cast

from robin.capture.workspace_bootstrap import (
    WorkspaceBootstrapError,
    _configured_windows_function,
    _windows_handle_value,
)
from robin.capture.workspace_bootstrap import (
    _WindowsJobObject as _BaseWindowsJobObject,
)
from robin.chronos_production import (
    ChronosProductionError,
    _recovery_v2_prepare_repository_directory,
    _recovery_v2_publish_exclusive_bytes,
    _recovery_v2_read_bytes,
    _recovery_v2_replace_bytes,
)

SUPERVISOR_TIMEOUT_EXIT = 124
SUPERVISOR_EXPORT_EXIT = 125
SUPERVISOR_CHILD_STUCK_EXIT = 126
_TERMINATE_GRACE_SECONDS = 5
_KILL_GRACE_SECONDS = 5
_FINALIZATION_MARGIN_SECONDS = 20
CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS = 31.0
_CAPTURE_POLL_SECONDS = 0.025
_T = TypeVar("_T")

_WINDOWS_GATE_RELEASE_TOKEN = b"\x01"
_WINDOWS_GATE_TARGET_START_FAILED = 254
_POSIX_NAMESPACE_READY = b"RECOVERY_V2_PID1_READY\n"
_POSIX_GATE_PAYLOAD_LIMIT_BYTES = 262_144
_POSIX_GATE_MAXIMUM_FDS = 16
_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_MAXIMUM_JOB_PROCESS_IDS = 4_096
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_POSIX_NAMESPACE_GATE_SOURCE = """
import array
import ctypes
import fcntl
import json
import os
import socket
import struct
import sys
import time

READY = b"RECOVERY_V2_PID1_READY\\n"
MAXIMUM_PAYLOAD_BYTES = 262144
MAXIMUM_FDS = 16

def read_exact(connection, size):
    payload = bytearray()
    while len(payload) < size:
        chunk = connection.recv(size - len(payload))
        if not chunk:
            raise RuntimeError
        payload.extend(chunk)
    return bytes(payload)

if os.getpid() != 1 or len(sys.argv) < 6:
    raise SystemExit(254)
try:
    target_uid = int(sys.argv[2])
    target_gid = int(sys.argv[3])
    target_groups = [int(raw) for raw in sys.argv[4].split(",") if raw]
    if target_uid < 0 or target_gid < 0 or any(group < 0 for group in target_groups):
        raise ValueError
    os.setgroups(target_groups)
    os.setgid(target_gid)
    os.setuid(target_uid)
    if (
        os.geteuid() != target_uid
        or os.getegid() != target_gid
        or sorted(os.getgroups()) != sorted(target_groups)
    ):
        raise RuntimeError
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl")
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(sys.argv[1])
    connection.sendall(READY)
    marker, ancillary, flags, _ = connection.recvmsg(
        1,
        socket.CMSG_SPACE(MAXIMUM_FDS * struct.calcsize("i")),
    )
    if marker != b"\\x01" or flags & socket.MSG_CTRUNC:
        raise RuntimeError
    received_fds = []
    for level, message_type, raw_fds in ancillary:
        if level != socket.SOL_SOCKET or message_type != socket.SCM_RIGHTS:
            raise RuntimeError
        descriptors = array.array("i")
        usable = len(raw_fds) - (len(raw_fds) % descriptors.itemsize)
        descriptors.frombytes(raw_fds[:usable])
        received_fds.extend(descriptors.tolist())
    payload_size = struct.unpack("!I", read_exact(connection, 4))[0]
    if payload_size > MAXIMUM_PAYLOAD_BYTES:
        raise ValueError
    document = json.loads(read_exact(connection, payload_size).decode("utf-8"))
    connection.close()
    environment = document["environment"]
    fd_targets = document["fd_targets"]
    deadline_monotonic_ns = document["deadline_monotonic_ns"]
    if (
        not isinstance(environment, dict)
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or "\\x00" in name
            or "\\x00" in value
            for name, value in environment.items()
        )
    ):
        raise ValueError
    if (
        type(deadline_monotonic_ns) is not int
        or deadline_monotonic_ns <= 0
        or not isinstance(fd_targets, list)
        or len(fd_targets) != len(received_fds)
        or len(fd_targets) > MAXIMUM_FDS
        or any(
            not isinstance(descriptor, int)
            or isinstance(descriptor, bool)
            or descriptor < 3
            for descriptor in fd_targets
        )
        or len(set(fd_targets)) != len(fd_targets)
    ):
        raise ValueError
    minimum_copy_fd = max([2, *fd_targets]) + 1
    copied_fds = [
        fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, minimum_copy_fd)
        for descriptor in received_fds
    ]
    for descriptor in received_fds:
        os.close(descriptor)
    for copied, target_descriptor in zip(copied_fds, fd_targets, strict=True):
        os.dup2(copied, target_descriptor, inheritable=True)
        os.close(copied)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(null_fd, 0)
    finally:
        if null_fd != 0:
            os.close(null_fd)
    if time.monotonic_ns() >= deadline_monotonic_ns:
        raise SystemExit(252)
    os.execve(sys.argv[5], sys.argv[5:], environment)
except (KeyError, OSError, RuntimeError, TypeError, ValueError):
    raise SystemExit(254)
"""
_WINDOWS_GATE_SOURCE = """
import os
import subprocess
import sys
import time

if sys.stdin.buffer.read(1) != b"\\x01":
    raise SystemExit(253)
try:
    handles = tuple(int(raw) for raw in sys.argv[1].split(",") if raw)
    deadline_text = sys.argv[2]
    deadline_monotonic_ns = int(deadline_text)
    if deadline_monotonic_ns <= 0 or str(deadline_monotonic_ns) != deadline_text:
        raise ValueError
    if time.monotonic_ns() >= deadline_monotonic_ns:
        raise SystemExit(252)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.lpAttributeList = {"handle_list": list(handles)}
    for handle in handles:
        os.set_handle_inheritable(handle, True)
except (AttributeError, OSError, TypeError, ValueError):
    raise SystemExit(254)
try:
    if time.monotonic_ns() >= deadline_monotonic_ns:
        raise SystemExit(252)
    child = subprocess.Popen(
        sys.argv[3:],
        stdin=subprocess.DEVNULL,
        close_fds=True,
        startupinfo=startupinfo,
    )
except (OSError, ValueError):
    raise SystemExit(254)
finally:
    for handle in handles:
        try:
            os.set_handle_inheritable(handle, False)
        except OSError:
            pass
raise SystemExit(0 if child.wait() == 0 else 1)
"""
_WINDOWS_CAPTURE_GATE_SOURCE = _WINDOWS_GATE_SOURCE


class _RecoveryJobProcessIdList(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wintypes.DWORD),
        ("NumberOfProcessIdsInList", wintypes.DWORD),
        ("ProcessIdList", ctypes.c_size_t * _MAXIMUM_JOB_PROCESS_IDS),
    ]


class _WindowsJobObject(_BaseWindowsJobObject):
    """Recovery-local Job Object proof with absolute cleanup deadlines."""

    def __init__(self) -> None:
        super().__init__()
        try:
            raw_loader = getattr(ctypes, "WinDLL", None)
            if not callable(raw_loader):
                raise WorkspaceBootstrapError("WORKSPACE_COMMAND_CONTAINMENT_FAILED")
            kernel32 = raw_loader("kernel32", use_last_error=True)
            self._wait_for_single_object = _configured_windows_function(
                kernel32,
                "WaitForSingleObject",
                argtypes=(wintypes.HANDLE, wintypes.DWORD),
                restype=wintypes.DWORD,
            )
        except WorkspaceBootstrapError:
            try:
                self.close()
            except WorkspaceBootstrapError:
                pass
            raise
        except (AttributeError, OSError, TypeError, ValueError):
            try:
                self.close()
            except WorkspaceBootstrapError:
                pass
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_CONTAINMENT_FAILED") from None

    def _listed_process_ids(self) -> tuple[int, ...]:
        process_list = _RecoveryJobProcessIdList()
        if not bool(
            self._query_information(
                self._required_handle(),
                _JOB_OBJECT_BASIC_PROCESS_ID_LIST,
                ctypes.byref(process_list),
                ctypes.sizeof(process_list),
                None,
            )
        ):
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
        assigned = int(process_list.NumberOfAssignedProcesses)
        listed = int(process_list.NumberOfProcessIdsInList)
        if assigned > _MAXIMUM_JOB_PROCESS_IDS or listed > assigned:
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
        if listed < assigned:
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
        return tuple(int(process_list.ProcessIdList[index]) for index in range(listed))

    def has_live_processes(self) -> bool:
        for process_id in self._listed_process_ids():
            process_handle = _windows_handle_value(
                self._open_process(_SYNCHRONIZE, False, process_id)
            )
            if not process_handle:
                raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
            try:
                wait_result = cast(int, self._wait_for_single_object(process_handle, 0))
            finally:
                handle_closed = bool(self._close_handle(process_handle))
            if not handle_closed:
                raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
            if wait_result == _WAIT_TIMEOUT:
                return True
            if wait_result != _WAIT_OBJECT_0:
                raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")
        return False

    def terminate_and_confirm_before_deadline(
        self,
        *,
        timeout_seconds: float,
        deadline_monotonic: float,
    ) -> None:
        if (
            not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
            or not math.isfinite(deadline_monotonic)
        ):
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED")

        def require_time_remaining() -> None:
            if time.monotonic() >= deadline_monotonic:
                raise WorkspaceBootstrapError(
                    "WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED"
                )

        try:
            require_time_remaining()
            active_processes = self.active_processes()
            require_time_remaining()
            terminated = bool(
                self._terminate_job(self._required_handle(), SUPERVISOR_TIMEOUT_EXIT)
            )
            require_time_remaining()
            if not terminated and active_processes != 0:
                remaining_processes = self.active_processes()
                require_time_remaining()
                if remaining_processes != 0:
                    raise WorkspaceBootstrapError(
                        "WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED"
                    )
            while True:
                require_time_remaining()
                remaining_processes = self.active_processes()
                require_time_remaining()
                if remaining_processes == 0:
                    return
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    raise WorkspaceBootstrapError(
                        "WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED"
                    )
                time.sleep(min(_CAPTURE_POLL_SECONDS, remaining))
        except WorkspaceBootstrapError:
            raise
        except (OSError, TypeError, ValueError):
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED") from None


class RecoveryV2SupervisionError(RuntimeError):
    """Fail-closed sanitized supervision failure."""


@dataclass(frozen=True)
class CapturedChildResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def canonical_json_bytes(document: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            dict(document),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_json_exclusive(
    path: Path,
    document: Mapping[str, object],
    *,
    repository_root: Path | None = None,
) -> str:
    """Create the durable fallback before starting an effect-bearing child."""

    payload = canonical_json_bytes(document)
    root = path.parent if repository_root is None else repository_root
    try:
        _recovery_v2_prepare_repository_directory(
            path.parent,
            repository_root=root,
        )
        _recovery_v2_publish_exclusive_bytes(
            path,
            payload,
            repository_root=root,
        )
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID") from None
    return hashlib.sha256(payload).hexdigest()


def adopt_or_create_json_fallback(
    path: Path,
    document: Mapping[str, object],
    *,
    repository_root: Path | None = None,
) -> str:
    """Adopt only the byte-exact early fallback, or create it once if absent."""

    payload = canonical_json_bytes(document)
    root = path.parent if repository_root is None else repository_root
    try:
        _recovery_v2_prepare_repository_directory(
            path.parent,
            repository_root=root,
        )
        try:
            path.lstat()
        except FileNotFoundError:
            _recovery_v2_publish_exclusive_bytes(
                path,
                payload,
                repository_root=root,
            )
        else:
            if not _regular_file(path):
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID"
                )
            observed = _recovery_v2_read_bytes(
                path,
                repository_root=root,
                maximum_bytes=2 * 1024 * 1024,
            )
            if observed != payload:
                raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_DRIFT")
    except RecoveryV2SupervisionError:
        raise
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID") from None
    return hashlib.sha256(payload).hexdigest()


def restore_fallback_template(
    template: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> str:
    """Restore an immutable pre-effect template after any failed output guard."""

    if (
        template.parent != destination.parent
        or template == destination
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or not _regular_file(template)
    ):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID")
    try:
        payload = _recovery_v2_read_bytes(
            template,
            repository_root=template.parent,
            maximum_bytes=2 * 1024 * 1024,
        )
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID") from None
    if not payload or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_DRIFT")
    if _regular_file(destination):
        try:
            observed = _recovery_v2_read_bytes(
                destination,
                repository_root=destination.parent,
                maximum_bytes=2 * 1024 * 1024,
            )
        except (ChronosProductionError, OSError):
            observed = b""
        if observed == payload:
            try:
                _recovery_v2_replace_bytes(
                    destination,
                    payload,
                    repository_root=destination.parent,
                )
            except (ChronosProductionError, OSError):
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID"
                ) from None
            return expected_sha256
    try:
        _recovery_v2_replace_bytes(
            destination,
            payload,
            repository_root=destination.parent,
        )
        if (
            _recovery_v2_read_bytes(
                destination,
                repository_root=destination.parent,
                maximum_bytes=max(len(payload), 1),
            )
            != payload
        ):
            raise OSError
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_INVALID") from None
    return expected_sha256


def _regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return not bool(attributes & reparse)


def promote_validated_file(
    candidate: Path,
    destination: Path,
    *,
    expected_fallback_sha256: str,
    validator: Callable[[Path], _T],
) -> _T:
    """Atomically replace the untouched fallback with one validated candidate."""

    if not _regular_file(candidate) or not _regular_file(destination):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
    try:
        fallback = _recovery_v2_read_bytes(
            destination,
            repository_root=destination.parent,
            maximum_bytes=2 * 1024 * 1024,
        )
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_EXPORT_INVALID") from None
    if hashlib.sha256(fallback).hexdigest() != expected_fallback_sha256:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_FALLBACK_DRIFT")
    try:
        candidate_payload = _recovery_v2_read_bytes(
            candidate,
            repository_root=candidate.parent,
            maximum_bytes=16 * 1024 * 1024,
        )
    except ChronosProductionError:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_EXPORT_INVALID") from None
    validated = validator(candidate)
    try:
        if candidate_payload != _recovery_v2_read_bytes(
            candidate,
            repository_root=candidate.parent,
            maximum_bytes=max(len(candidate_payload), 1),
        ):
            raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_EXPORT_INVALID")
        require_effect_deadline_open()
        _recovery_v2_replace_bytes(
            destination,
            candidate_payload,
            repository_root=destination.parent,
        )
    except (ChronosProductionError, OSError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_EXPORT_INVALID") from None
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        pass
    return validated


def _signal_process_group(process: subprocess.Popen[bytes], *, force: bool) -> None:
    try:
        if os.name == "nt":
            (process.kill if force else process.terminate)()
        else:
            kill_process_group = getattr(os, "killpg")
            selected_signal = getattr(signal, "SIGKILL" if force else "SIGTERM")
            kill_process_group(process.pid, selected_signal)
    except (OSError, ProcessLookupError):
        return


def _posix_process_group_exists(process: subprocess.Popen[bytes]) -> bool:
    if os.name == "nt":
        return False
    try:
        getattr(os, "killpg")(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_POSIX_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _required_posix_identity() -> tuple[int, int, tuple[int, ...]]:
    get_uid = getattr(os, "getuid", None)
    get_effective_uid = getattr(os, "geteuid", None)
    get_gid = getattr(os, "getgid", None)
    get_groups = getattr(os, "getgroups", None)
    if not all(
        callable(function)
        for function in (get_uid, get_effective_uid, get_gid, get_groups)
    ):
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    uid = int(cast(Callable[[], int], get_uid)())
    effective_uid = int(cast(Callable[[], int], get_effective_uid)())
    gid = int(cast(Callable[[], int], get_gid)())
    groups = tuple(int(group) for group in cast(Callable[[], list[int]], get_groups)())
    if uid <= 0 or effective_uid <= 0 or gid < 0 or any(group < 0 for group in groups):
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    return uid, gid, groups


def _trusted_posix_launcher(name: str) -> str:
    if sys.platform != "linux":
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    candidate = shutil.which(name, path=_POSIX_SYSTEM_PATH)
    if candidate is None:
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    try:
        resolved = Path(candidate).resolve(strict=True)
        metadata = resolved.stat()
    except (OSError, RuntimeError):
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        ) from None
    if (
        not resolved.is_absolute()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not os.access(resolved, os.X_OK)
    ):
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    return str(resolved)


def _resolved_posix_target(
    executable: str,
    *,
    environment: Mapping[str, str],
) -> str:
    candidate = (
        executable
        if os.path.isabs(executable)
        else shutil.which(executable, path=environment.get("PATH") or os.defpath)
    )
    if candidate is None:
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED")
    try:
        resolved = Path(candidate).resolve(strict=True)
        metadata = resolved.stat()
    except (OSError, RuntimeError):
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED") from None
    if (
        not resolved.is_absolute()
        or not stat.S_ISREG(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
    ):
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED")
    return str(resolved)


def _contained_posix_command(
    command: Sequence[str],
    *,
    control_socket: Path,
    environment: Mapping[str, str],
) -> tuple[str, ...]:
    """Make the target PID 1 so setsid/double-fork cannot escape teardown."""

    target_uid, target_gid, target_groups = _required_posix_identity()
    unshare = _trusted_posix_launcher("unshare")
    gate_python = _trusted_posix_launcher("python3")
    target = _resolved_posix_target(command[0], environment=environment)
    namespace_command = (
        unshare,
        "--pid",
        "--fork",
        "--kill-child=SIGKILL",
        "--",
        gate_python,
        "-I",
        "-B",
        "-c",
        _POSIX_NAMESPACE_GATE_SOURCE,
        str(control_socket),
        str(target_uid),
        str(target_gid),
        ",".join(str(group) for group in target_groups),
        target,
        *command[1:],
    )
    sudo = _trusted_posix_launcher("sudo")
    return (sudo, "-n", "--", *namespace_command)


def _drain_posix_process_group(process: subprocess.Popen[bytes]) -> bool:
    """Terminate every descendant left in the child's dedicated POSIX session."""

    if os.name == "nt" or not _posix_process_group_exists(process):
        return True
    _signal_process_group(process, force=False)
    deadline = time.monotonic() + _TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not _posix_process_group_exists(process):
            return True
        time.sleep(0.05)
    _signal_process_group(process, force=True)
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not _posix_process_group_exists(process):
            return True
        time.sleep(0.05)
    return not _posix_process_group_exists(process)


def _wait_for_process_before_deadline(
    process: subprocess.Popen[bytes],
    *,
    command: Sequence[str],
    timeout_seconds: int,
    deadline_monotonic: float,
) -> int:
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, timeout_seconds)
    return_code = int(process.wait(timeout=remaining))
    if time.monotonic() >= deadline_monotonic:
        raise subprocess.TimeoutExpired(command, timeout_seconds)
    return return_code


def _poll_process_before_deadline(
    process: subprocess.Popen[bytes],
    *,
    command: Sequence[str],
    deadline_monotonic: float,
) -> int | None:
    if time.monotonic() >= deadline_monotonic:
        raise subprocess.TimeoutExpired(command, 0)
    return_code = process.poll()
    if time.monotonic() >= deadline_monotonic:
        raise subprocess.TimeoutExpired(command, 0)
    return None if return_code is None else int(return_code)


def _pidfd_exited_before_deadline(pidfd: int, *, deadline_monotonic: float) -> bool:
    if time.monotonic() >= deadline_monotonic:
        return False
    exited = _pidfd_exited(pidfd)
    return time.monotonic() < deadline_monotonic and exited


def _run_posix_child_once(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    pass_fds: Sequence[int] = (),
) -> int:
    deadline_monotonic = time.monotonic() + timeout_seconds
    cleanup_deadline_monotonic = deadline_monotonic + _FINALIZATION_MARGIN_SECONDS
    process: subprocess.Popen[bytes] | None = None
    namespace_pidfd_holder: list[int | None] = [None]
    try:
        with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-pidns-") as raw:
            Path(raw).chmod(0o700)
            control_socket = Path(raw) / "gate.sock"
            with socket.socket(
                getattr(socket, "AF_UNIX", 1),
                socket.SOCK_STREAM,
            ) as listener:
                listener.bind(str(control_socket))
                control_socket.chmod(0o600)
                listener.listen(1)
                contained_command = _contained_posix_command(
                    command,
                    control_socket=control_socket,
                    environment=os.environ,
                )
                process = subprocess.Popen(  # nosec B603
                    contained_command,
                    env={
                        "PATH": _POSIX_SYSTEM_PATH,
                        "LC_ALL": "C",
                        "LANG": "C",
                    },
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                _release_posix_namespace_gate(
                    listener,
                    process,
                    None,
                    None,
                    namespace_pidfd_holder=namespace_pidfd_holder,
                    environment=os.environ,
                    pass_fds=pass_fds,
                    deadline_monotonic=deadline_monotonic,
                )
    except (OSError, RecoveryV2SupervisionError, ValueError):
        cleanup_confirmed = process is None
        if process is not None:
            try:
                cleanup_confirmed = _terminate_captured_posix_tree(
                    process,
                    namespace_pidfd_holder[0],
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
            except BaseException:
                cleanup_confirmed = False
        if namespace_pidfd_holder[0] is not None:
            try:
                os.close(namespace_pidfd_holder[0])
            except OSError:
                pass
        return (
            SUPERVISOR_EXPORT_EXIT
            if cleanup_confirmed
            else SUPERVISOR_CHILD_STUCK_EXIT
        )
    except BaseException:
        cleanup_confirmed = process is None
        if process is not None:
            try:
                cleanup_confirmed = _terminate_captured_posix_tree(
                    process,
                    namespace_pidfd_holder[0],
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
            except BaseException:
                cleanup_confirmed = False
        if namespace_pidfd_holder[0] is not None:
            try:
                os.close(namespace_pidfd_holder[0])
            except OSError:
                pass
        if not cleanup_confirmed:
            return SUPERVISOR_CHILD_STUCK_EXIT
        raise
    try:
        try:
            return_code = _wait_for_process_before_deadline(
                process,
                command=command,
                timeout_seconds=timeout_seconds,
                deadline_monotonic=deadline_monotonic,
            )
        except subprocess.TimeoutExpired:
            confirmed = _terminate_captured_posix_tree(
                process,
                namespace_pidfd_holder[0],
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            )
            return (
                SUPERVISOR_TIMEOUT_EXIT
                if confirmed
                else SUPERVISOR_CHILD_STUCK_EXIT
            )
        if namespace_pidfd_holder[0] is None:
            _terminate_captured_posix_tree(
                process,
                None,
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            )
            return SUPERVISOR_CHILD_STUCK_EXIT
        if not _pidfd_exited_before_deadline(
            namespace_pidfd_holder[0],
            deadline_monotonic=cleanup_deadline_monotonic,
        ):
            if not _terminate_captured_posix_tree(
                process,
                namespace_pidfd_holder[0],
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            ):
                return SUPERVISOR_CHILD_STUCK_EXIT
        return 0 if return_code == 0 else 1
    except BaseException:
        cleanup_confirmed = process is None
        if process is not None:
            try:
                cleanup_confirmed = _terminate_captured_posix_tree(
                    process,
                    namespace_pidfd_holder[0],
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
            except BaseException:
                cleanup_confirmed = False
        if not cleanup_confirmed:
            return SUPERVISOR_CHILD_STUCK_EXIT
        raise
    finally:
        if namespace_pidfd_holder[0] is not None:
            try:
                os.close(namespace_pidfd_holder[0])
            except OSError:
                pass


class _WindowsCleanupUnconfirmed(RuntimeError):
    pass


def _run_windows_child_once_inner(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    pass_handles: Sequence[int] = (),
) -> int:
    """Assign a blocked gate before it can start the target or any descendant."""

    deadline_monotonic = time.monotonic() + timeout_seconds
    cleanup_deadline_monotonic = deadline_monotonic + _FINALIZATION_MARGIN_SECONDS
    try:
        job = _WindowsJobObject()
    except WorkspaceBootstrapError:
        return SUPERVISOR_EXPORT_EXIT
    gate: subprocess.Popen[bytes] | None = None
    assigned = False
    gate_exit_confirmed = False
    job_quiescence_confirmed = False
    try:
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {"handle_list": list(pass_handles)}
            for handle in pass_handles:
                os.set_handle_inheritable(handle, True)
            try:
                gate = subprocess.Popen(  # nosec B603
                    (
                        os.path.abspath(sys.executable),
                        "-I",
                        "-B",
                        "-c",
                        _WINDOWS_GATE_SOURCE,
                        ",".join(str(handle) for handle in pass_handles),
                        str(int(deadline_monotonic * 1_000_000_000)),
                        *command,
                    ),
                    stdin=subprocess.PIPE,
                    close_fds=True,
                    startupinfo=startupinfo,
                )
            finally:
                for handle in pass_handles:
                    try:
                        os.set_handle_inheritable(handle, False)
                    except OSError:
                        pass
        except (OSError, ValueError):
            return SUPERVISOR_EXPORT_EXIT
        try:
            job.assign_process(gate.pid)
            assigned = True
        except WorkspaceBootstrapError:
            try:
                gate.kill()
                _wait_for_process_before_deadline(
                    gate,
                    command=command,
                    timeout_seconds=timeout_seconds,
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                gate_exit_confirmed = True
            except (OSError, subprocess.SubprocessError):
                return SUPERVISOR_CHILD_STUCK_EXIT
            return SUPERVISOR_EXPORT_EXIT
        try:
            if gate.stdin is None:
                raise OSError
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            gate.stdin.write(_WINDOWS_GATE_RELEASE_TOKEN)
            gate.stdin.close()
            return_code = _wait_for_process_before_deadline(
                gate,
                command=command,
                timeout_seconds=timeout_seconds,
                deadline_monotonic=deadline_monotonic,
            )
            gate_exit_confirmed = True
        except subprocess.TimeoutExpired:
            try:
                job.terminate_and_confirm_before_deadline(
                    timeout_seconds=max(
                        0.0,
                        cleanup_deadline_monotonic - time.monotonic(),
                    ),
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                job_quiescence_confirmed = True
                gate_state = _poll_process_before_deadline(
                    gate,
                    command=command,
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                if gate_state is None:
                    _wait_for_process_before_deadline(
                        gate,
                        command=command,
                        timeout_seconds=timeout_seconds,
                        deadline_monotonic=cleanup_deadline_monotonic,
                    )
                gate_exit_confirmed = True
            except (OSError, WorkspaceBootstrapError, subprocess.SubprocessError):
                return SUPERVISOR_CHILD_STUCK_EXIT
            return SUPERVISOR_TIMEOUT_EXIT
        except (OSError, subprocess.SubprocessError):
            try:
                job.terminate_and_confirm_before_deadline(
                    timeout_seconds=max(
                        0.0,
                        cleanup_deadline_monotonic - time.monotonic(),
                    ),
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                job_quiescence_confirmed = True
                gate_state = _poll_process_before_deadline(
                    gate,
                    command=command,
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                if gate_state is None:
                    _wait_for_process_before_deadline(
                        gate,
                        command=command,
                        timeout_seconds=timeout_seconds,
                        deadline_monotonic=cleanup_deadline_monotonic,
                    )
                gate_exit_confirmed = True
            except (OSError, WorkspaceBootstrapError, subprocess.SubprocessError):
                return SUPERVISOR_CHILD_STUCK_EXIT
            return SUPERVISOR_EXPORT_EXIT
        if return_code == _WINDOWS_GATE_TARGET_START_FAILED:
            return SUPERVISOR_EXPORT_EXIT
        try:
            quiescent = job.wait_for_quiescence(
                min(
                    0.05,
                    max(0.0, cleanup_deadline_monotonic - time.monotonic()),
                )
            )
            if time.monotonic() >= cleanup_deadline_monotonic:
                return SUPERVISOR_CHILD_STUCK_EXIT
            if not quiescent:
                job.terminate_and_confirm_before_deadline(
                    timeout_seconds=max(
                        0.0,
                        cleanup_deadline_monotonic - time.monotonic(),
                    ),
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
            job_quiescence_confirmed = True
        except WorkspaceBootstrapError:
            return SUPERVISOR_CHILD_STUCK_EXIT
        return 0 if return_code == 0 else 1
    finally:
        cleanup_failed = False
        if assigned and not job_quiescence_confirmed:
            try:
                job.terminate_and_confirm_before_deadline(
                    timeout_seconds=max(
                        0.0,
                        cleanup_deadline_monotonic - time.monotonic(),
                    ),
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                job_quiescence_confirmed = True
            except BaseException:
                cleanup_failed = True
        if gate is not None and not gate_exit_confirmed:
            try:
                gate_state = _poll_process_before_deadline(
                    gate,
                    command=command,
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                if gate_state is None:
                    if assigned and not job_quiescence_confirmed:
                        job.terminate_and_confirm_before_deadline(
                            timeout_seconds=max(
                                0.0,
                                cleanup_deadline_monotonic - time.monotonic(),
                            ),
                            deadline_monotonic=cleanup_deadline_monotonic,
                        )
                        job_quiescence_confirmed = True
                    else:
                        gate.kill()
                    _wait_for_process_before_deadline(
                        gate,
                        command=command,
                        timeout_seconds=timeout_seconds,
                        deadline_monotonic=cleanup_deadline_monotonic,
                    )
                gate_exit_confirmed = True
            except BaseException:
                cleanup_failed = True
        if time.monotonic() >= cleanup_deadline_monotonic:
            cleanup_failed = True
        try:
            job.close()
        except WorkspaceBootstrapError:
            cleanup_failed = True
        if time.monotonic() >= cleanup_deadline_monotonic:
            cleanup_failed = True
        if cleanup_failed:
            raise _WindowsCleanupUnconfirmed


def _run_windows_child_once(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    pass_handles: Sequence[int] = (),
) -> int:
    try:
        return _run_windows_child_once_inner(
            command,
            timeout_seconds=timeout_seconds,
            pass_handles=pass_handles,
        )
    except _WindowsCleanupUnconfirmed:
        return SUPERVISOR_CHILD_STUCK_EXIT


def run_child_once(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    pass_fds: Sequence[int] = (),
    pass_handles: Sequence[int] = (),
) -> int:
    """Run one child once and prove that its process tree is quiescent on return."""

    if (
        type(timeout_seconds) is not int
        or timeout_seconds < 1
        or not command
        or any(not isinstance(argument, str) or not argument for argument in command)
        or any(type(descriptor) is not int or descriptor < 3 for descriptor in pass_fds)
        or any(type(handle) is not int or handle <= 0 for handle in pass_handles)
        or len(set(pass_fds)) != len(tuple(pass_fds))
        or len(set(pass_handles)) != len(tuple(pass_handles))
        or len(tuple(pass_fds)) > _POSIX_GATE_MAXIMUM_FDS
        or any("\x00" in argument for argument in command)
    ):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_INVOCATION_INVALID")
    if os.name == "nt":
        if pass_fds:
            raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_INVOCATION_INVALID")
        return _run_windows_child_once(
            command,
            timeout_seconds=timeout_seconds,
            pass_handles=pass_handles,
        )
    if pass_handles:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_INVOCATION_INVALID")
    return _run_posix_child_once(
        command,
        timeout_seconds=timeout_seconds,
        pass_fds=pass_fds,
    )


class _BoundedPipeCapture:
    def __init__(self, stream: BinaryIO, *, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._payload = bytearray()
        self.overflow = threading.Event()
        self.failure = threading.Event()
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._started = False

    def start(self) -> None:
        try:
            self._thread.start()
            self._started = True
        except RuntimeError:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID") from None

    def _drain(self) -> None:
        try:
            while True:
                chunk = self._stream.read(8_192)
                if not chunk:
                    return
                retained = self._maximum_bytes + 1 - len(self._payload)
                if retained > 0:
                    self._payload.extend(chunk[:retained])
                if len(chunk) > retained or len(self._payload) > self._maximum_bytes:
                    self.overflow.set()
        except Exception:
            self.failure.set()

    def join_and_read(self, *, cleanup_deadline_monotonic: float) -> bytes:
        if not self._started:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID")
        if time.monotonic() >= cleanup_deadline_monotonic:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            )
        self._thread.join(
            timeout=max(0.0, cleanup_deadline_monotonic - time.monotonic())
        )
        if time.monotonic() >= cleanup_deadline_monotonic:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            )
        thread_alive = self._thread.is_alive()
        if time.monotonic() >= cleanup_deadline_monotonic or thread_alive:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            )
        if self.failure.is_set():
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID")
        if self.overflow.is_set() or len(self._payload) > self._maximum_bytes:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_OUTPUT_LIMIT")
        return bytes(self._payload)

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID") from None


def _finish_pipe_captures(
    stdout_capture: _BoundedPipeCapture,
    stderr_capture: _BoundedPipeCapture,
    *,
    cleanup_deadline_monotonic: float,
) -> tuple[bytes, bytes]:
    payloads: list[bytes] = []
    first_error: RecoveryV2SupervisionError | None = None
    termination_unconfirmed = False
    for capture in (stdout_capture, stderr_capture):
        try:
            payloads.append(
                capture.join_and_read(
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic
                )
            )
        except RecoveryV2SupervisionError as error:
            if error.args == ("RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",):
                termination_unconfirmed = True
            first_error = first_error or error
            payloads.append(b"")
    for capture in (stdout_capture, stderr_capture):
        if time.monotonic() >= cleanup_deadline_monotonic:
            termination_unconfirmed = True
        try:
            capture.close()
        except RecoveryV2SupervisionError as error:
            first_error = first_error or error
        if time.monotonic() >= cleanup_deadline_monotonic:
            termination_unconfirmed = True
    if termination_unconfirmed:
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
        )
    if first_error is not None:
        raise first_error
    return payloads[0], payloads[1]


def _wait_for_captured_root(
    process: subprocess.Popen[bytes],
    stdout_capture: _BoundedPipeCapture,
    stderr_capture: _BoundedPipeCapture,
    *,
    deadline_monotonic: float,
) -> tuple[Literal["CAPTURE_INVALID", "COMPLETE", "OUTPUT_LIMIT", "TIMEOUT"], int | None]:
    while True:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            return "TIMEOUT", None
        if stdout_capture.failure.is_set() or stderr_capture.failure.is_set():
            return "CAPTURE_INVALID", None
        if stdout_capture.overflow.is_set() or stderr_capture.overflow.is_set():
            return "OUTPUT_LIMIT", None
        returncode = process.poll()
        if time.monotonic() >= deadline_monotonic:
            return "TIMEOUT", None
        if returncode is not None:
            return "COMPLETE", int(returncode)
        time.sleep(min(_CAPTURE_POLL_SECONDS, remaining))


def _socket_read_exact(
    connection: socket.socket,
    size: int,
    *,
    deadline_monotonic: float,
) -> bytes:
    payload = bytearray()
    while len(payload) < size:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
        connection.settimeout(remaining)
        try:
            chunk = connection.recv(size - len(payload))
        except (OSError, TimeoutError):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            ) from None
        if not chunk:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            )
        payload.extend(chunk)
    return bytes(payload)


def _pidfd_open(process_id: int) -> int:
    open_pidfd = getattr(os, "pidfd_open", None)
    send_pidfd_signal = getattr(signal, "pidfd_send_signal", None)
    if not callable(open_pidfd) or not callable(send_pidfd_signal):
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        )
    try:
        return int(open_pidfd(process_id, 0))
    except OSError:
        raise RecoveryV2SupervisionError(
            "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
        ) from None


def _peer_is_namespace_pid_one(process_id: int) -> bool:
    try:
        with (Path("/proc") / str(process_id) / "status").open("rb") as status_file:
            payload = status_file.read(65_537)
    except OSError:
        return False
    if len(payload) > 65_536:
        return False
    for line in payload.splitlines():
        if not line.startswith(b"NSpid:"):
            continue
        try:
            identifiers = tuple(int(raw) for raw in line.split()[1:])
        except ValueError:
            return False
        return (
            len(identifiers) >= 2
            and identifiers[0] == process_id
            and identifiers[-1] == 1
        )
    return False


def _process_descends_from(process_id: int, ancestor_process_id: int) -> bool:
    current = process_id
    observed: set[int] = set()
    for _ in range(32):
        if current == ancestor_process_id:
            return True
        if current <= 1 or current in observed:
            return False
        observed.add(current)
        try:
            with (Path("/proc") / str(current) / "status").open("rb") as status_file:
                payload = status_file.read(65_537)
        except OSError:
            return False
        if len(payload) > 65_536:
            return False
        parent: int | None = None
        for line in payload.splitlines():
            if line.startswith(b"PPid:"):
                try:
                    parent = int(line.split()[1])
                except (IndexError, ValueError):
                    return False
                break
        if parent is None:
            return False
        current = parent
    return False


def _pidfd_send_kill(pidfd: int) -> bool:
    send_pidfd_signal = getattr(signal, "pidfd_send_signal", None)
    if not callable(send_pidfd_signal):
        return False
    try:
        send_pidfd_signal(pidfd, 9, None, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def _pidfd_exited(pidfd: int, *, timeout_seconds: float = 0.0) -> bool:
    try:
        readable, _, _ = select.select((pidfd,), (), (), max(0.0, timeout_seconds))
    except (OSError, ValueError):
        return False
    return bool(readable)


def _release_posix_namespace_gate(
    listener: socket.socket,
    process: subprocess.Popen[bytes],
    stdout_capture: _BoundedPipeCapture | None,
    stderr_capture: _BoundedPipeCapture | None,
    *,
    namespace_pidfd_holder: list[int | None],
    environment: Mapping[str, str],
    pass_fds: Sequence[int] = (),
    deadline_monotonic: float,
) -> int:
    connection: socket.socket | None = None
    pidfd: int | None = None
    try:
        while connection is None:
            if (
                stdout_capture is not None
                and stderr_capture is not None
                and (
                    stdout_capture.failure.is_set()
                    or stderr_capture.failure.is_set()
                )
            ):
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID")
            if (
                stdout_capture is not None
                and stderr_capture is not None
                and (
                    stdout_capture.overflow.is_set()
                    or stderr_capture.overflow.is_set()
                )
            ):
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_OUTPUT_LIMIT")
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
            returncode = process.poll()
            if time.monotonic() >= deadline_monotonic:
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
            if returncode is not None:
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
                )
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
            listener.settimeout(min(_CAPTURE_POLL_SECONDS, remaining))
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
                ) from None
        ready = _socket_read_exact(
            connection,
            len(_POSIX_NAMESPACE_READY),
            deadline_monotonic=deadline_monotonic,
        )
        if ready != _POSIX_NAMESPACE_READY:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            )
        try:
            credentials = connection.getsockopt(
                socket.SOL_SOCKET,
                getattr(socket, "SO_PEERCRED", 17),
                struct.calcsize("3i"),
            )
            peer_pid, peer_uid, _ = struct.unpack("3i", credentials)
        except (AttributeError, OSError, struct.error):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            ) from None
        if (
            peer_pid <= 0
            or peer_uid != _required_posix_identity()[0]
            or not _process_descends_from(peer_pid, process.pid)
        ):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            )
        pidfd = _pidfd_open(peer_pid)
        if not _peer_is_namespace_pid_one(peer_pid):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            )
        # Publish ownership while PID 1 is still blocked. A BaseException either
        # precedes this atomic store (the callee owns cleanup) or follows it (the
        # caller owns cleanup), including the instruction immediately after release.
        namespace_pidfd_holder[0] = pidfd
        payload = json.dumps(
            {
                "deadline_monotonic_ns": int(deadline_monotonic * 1_000_000_000),
                "environment": dict(environment),
                "fd_targets": list(pass_fds),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > _POSIX_GATE_PAYLOAD_LIMIT_BYTES:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_INVOCATION_INVALID"
            )
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
        connection.settimeout(remaining)
        try:
            ancillary = []
            if pass_fds:
                descriptor_bytes = array.array("i", pass_fds).tobytes()
                ancillary = [
                    (
                        socket.SOL_SOCKET,
                        getattr(socket, "SCM_RIGHTS", 1),
                        descriptor_bytes,
                    )
                ]
            send_message = getattr(connection, "sendmsg", None)
            if not callable(send_message) or send_message((b"\x01",), ancillary) != 1:
                raise OSError
            connection.sendall(struct.pack("!I", len(payload)) + payload)
        except (OSError, TimeoutError):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_CONTAINMENT_UNAVAILABLE"
            ) from None
        return pidfd
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass
        if pidfd is not None and namespace_pidfd_holder[0] != pidfd:
            _pidfd_send_kill(pidfd)
            os.close(pidfd)


def _terminate_captured_posix_tree(
    process: subprocess.Popen[bytes],
    namespace_pidfd: int | None,
    *,
    cleanup_deadline_monotonic: float,
) -> bool:
    namespace_signalled = namespace_pidfd is None or _pidfd_send_kill(namespace_pidfd)
    _signal_process_group(process, force=True)
    while True:
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        namespace_exited = namespace_pidfd is None or _pidfd_exited(namespace_pidfd)
        root_exited = process.poll() is not None
        group_exited = not _posix_process_group_exists(process)
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        if namespace_signalled and namespace_exited and root_exited and group_exited:
            return True
        remaining = cleanup_deadline_monotonic - time.monotonic()
        if remaining <= 0:
            return False
        if not root_exited:
            try:
                process.wait(timeout=min(_CAPTURE_POLL_SECONDS, remaining))
            except subprocess.TimeoutExpired:
                pass
        else:
            time.sleep(min(_CAPTURE_POLL_SECONDS, remaining))


def _captured_posix_tree_quiescent_before_deadline(
    process: subprocess.Popen[bytes],
    namespace_pidfd: int | None,
    *,
    cleanup_deadline_monotonic: float,
) -> bool:
    if namespace_pidfd is None or time.monotonic() >= cleanup_deadline_monotonic:
        return False
    root_exited = process.poll() is not None
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    group_exited = not _posix_process_group_exists(process)
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    namespace_exited = _pidfd_exited(namespace_pidfd)
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    return root_exited and group_exited and namespace_exited


def _run_captured_posix_child_once(
    command: Sequence[str],
    *,
    deadline_monotonic: float,
    cleanup_deadline_monotonic: float,
    cwd: Path | None,
    environment: Mapping[str, str],
    maximum_stdout_bytes: int,
    maximum_stderr_bytes: int,
) -> CapturedChildResult:
    process: subprocess.Popen[bytes] | None = None
    namespace_pidfd_holder: list[int | None] = [None]
    stdout_capture: _BoundedPipeCapture | None = None
    stderr_capture: _BoundedPipeCapture | None = None
    captures_finish_confirmed = False
    try:
        try:
            with tempfile.TemporaryDirectory(prefix="robin-recovery-v2-pidns-") as raw:
                Path(raw).chmod(0o700)
                control_socket = Path(raw) / "gate.sock"
                with socket.socket(
                    getattr(socket, "AF_UNIX", 1),
                    socket.SOCK_STREAM,
                ) as listener:
                    listener.bind(str(control_socket))
                    control_socket.chmod(0o600)
                    listener.listen(1)
                    contained_command = _contained_posix_command(
                        command,
                        control_socket=control_socket,
                        environment=environment,
                    )
                    process = subprocess.Popen(  # nosec B603
                        contained_command,
                        cwd=cwd,
                        env={
                            "PATH": _POSIX_SYSTEM_PATH,
                            "LC_ALL": "C",
                            "LANG": "C",
                        },
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=0,
                        close_fds=True,
                        start_new_session=True,
                    )
                    if process.stdout is None or process.stderr is None:
                        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID")
                    stdout_capture = _BoundedPipeCapture(
                        cast(BinaryIO, process.stdout),
                        maximum_bytes=maximum_stdout_bytes,
                    )
                    stderr_capture = _BoundedPipeCapture(
                        cast(BinaryIO, process.stderr),
                        maximum_bytes=maximum_stderr_bytes,
                    )
                    stdout_capture.start()
                    stderr_capture.start()
                    _release_posix_namespace_gate(
                        listener,
                        process,
                        stdout_capture,
                        stderr_capture,
                        namespace_pidfd_holder=namespace_pidfd_holder,
                        environment=environment,
                        deadline_monotonic=deadline_monotonic,
                    )
        except (OSError, ValueError):
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_START_FAILED"
            ) from None
        if process is None or stdout_capture is None or stderr_capture is None:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED")
        state, returncode = _wait_for_captured_root(
            process,
            stdout_capture,
            stderr_capture,
            deadline_monotonic=deadline_monotonic,
        )
        failure_code: str | None = None
        if state != "COMPLETE":
            if not _terminate_captured_posix_tree(
                process,
                namespace_pidfd_holder[0],
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            ):
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            failure_code = {
                "CAPTURE_INVALID": "RECOVERY_V2_CAPTURE_INVALID",
                "OUTPUT_LIMIT": "RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
                "TIMEOUT": "RECOVERY_V2_CAPTURE_TIMEOUT",
            }[state]
        elif not _captured_posix_tree_quiescent_before_deadline(
            process,
            namespace_pidfd_holder[0],
            cleanup_deadline_monotonic=cleanup_deadline_monotonic,
        ):
            if not _terminate_captured_posix_tree(
                process,
                namespace_pidfd_holder[0],
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            ):
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            failure_code = "RECOVERY_V2_CAPTURE_RESIDUAL_DESCENDANT"
        if returncode is None:
            if failure_code is None:
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            returncode = SUPERVISOR_CHILD_STUCK_EXIT
        try:
            stdout, stderr = _finish_pipe_captures(
                stdout_capture,
                stderr_capture,
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            )
            captures_finish_confirmed = True
        except RecoveryV2SupervisionError as error:
            if error.args == ("RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",):
                raise
            if failure_code is None:
                raise
            stdout = b""
            stderr = b""
        if failure_code is not None:
            raise RecoveryV2SupervisionError(failure_code)
        return CapturedChildResult(
            returncode=0 if returncode == 0 else 1,
            stdout=stdout,
            stderr=stderr,
        )
    except BaseException as primary_error:
        cleanup_confirmed = not (
            isinstance(primary_error, RecoveryV2SupervisionError)
            and primary_error.args
            == ("RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",)
        )
        if process is not None:
            try:
                quiescent = _captured_posix_tree_quiescent_before_deadline(
                    process,
                    namespace_pidfd_holder[0],
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
            except BaseException:
                quiescent = False
            if not quiescent:
                try:
                    process_cleanup_confirmed = _terminate_captured_posix_tree(
                        process,
                        namespace_pidfd_holder[0],
                        cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                    )
                except BaseException:
                    process_cleanup_confirmed = False
                cleanup_confirmed = (
                    cleanup_confirmed and process_cleanup_confirmed
                )
        if (
            stdout_capture is not None
            and stderr_capture is not None
            and not captures_finish_confirmed
        ):
            try:
                _finish_pipe_captures(
                    stdout_capture,
                    stderr_capture,
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
                captures_finish_confirmed = True
            except RecoveryV2SupervisionError as error:
                if error.args == (
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED",
                ):
                    cleanup_confirmed = False
            except BaseException:
                cleanup_confirmed = False
        if not cleanup_confirmed:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            ) from None
        raise
    finally:
        if namespace_pidfd_holder[0] is not None:
            try:
                os.close(namespace_pidfd_holder[0])
            except OSError:
                pass


def _terminate_captured_windows_tree(
    job: _WindowsJobObject,
    gate: subprocess.Popen[bytes],
    *,
    cleanup_deadline_monotonic: float,
) -> bool:
    try:
        remaining = max(0.0, cleanup_deadline_monotonic - time.monotonic())
        job.terminate_and_confirm_before_deadline(
            timeout_seconds=remaining,
            deadline_monotonic=cleanup_deadline_monotonic,
        )
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        gate_state = gate.poll()
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        if gate_state is None:
            remaining = max(0.0, cleanup_deadline_monotonic - time.monotonic())
            gate.wait(timeout=remaining)
            if time.monotonic() >= cleanup_deadline_monotonic:
                return False
        gate_state = gate.poll()
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        active_processes = job.active_processes()
        if time.monotonic() >= cleanup_deadline_monotonic:
            return False
        return gate_state is not None and active_processes == 0
    except (WorkspaceBootstrapError, subprocess.TimeoutExpired):
        return False


def _captured_windows_tree_quiescent_before_deadline(
    job: _WindowsJobObject,
    gate: subprocess.Popen[bytes],
    *,
    cleanup_deadline_monotonic: float,
) -> bool:
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    active_processes = job.active_processes()
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    gate_state = gate.poll()
    if time.monotonic() >= cleanup_deadline_monotonic:
        return False
    return gate_state is not None and active_processes == 0


def _wait_for_captured_windows_quiescence(
    job: _WindowsJobObject,
    stdout_capture: _BoundedPipeCapture,
    stderr_capture: _BoundedPipeCapture,
    *,
    cleanup_deadline_monotonic: float,
) -> Literal["CAPTURE_INVALID", "OUTPUT_LIMIT", "QUIESCENT", "RESIDUAL"]:
    settlement_deadline_monotonic = min(
        cleanup_deadline_monotonic,
        time.monotonic() + 1.0,
    )
    while True:
        if time.monotonic() >= settlement_deadline_monotonic:
            return "RESIDUAL"
        if stdout_capture.failure.is_set() or stderr_capture.failure.is_set():
            return "CAPTURE_INVALID"
        if stdout_capture.overflow.is_set() or stderr_capture.overflow.is_set():
            return "OUTPUT_LIMIT"
        try:
            active_processes = job.active_processes()
            if time.monotonic() >= settlement_deadline_monotonic:
                return "RESIDUAL"
            if active_processes == 0:
                return "QUIESCENT"
            live_processes = job.has_live_processes()
            if time.monotonic() >= settlement_deadline_monotonic:
                return "RESIDUAL"
            if live_processes:
                return "RESIDUAL"
        except WorkspaceBootstrapError:
            return "CAPTURE_INVALID"
        remaining = settlement_deadline_monotonic - time.monotonic()
        if remaining <= 0:
            return "RESIDUAL"
        time.sleep(min(0.025, remaining))


def _run_captured_windows_child_once(
    command: Sequence[str],
    *,
    deadline_monotonic: float,
    cleanup_deadline_monotonic: float,
    cwd: Path | None,
    environment: Mapping[str, str],
    maximum_stdout_bytes: int,
    maximum_stderr_bytes: int,
) -> CapturedChildResult:
    try:
        job = _WindowsJobObject()
    except WorkspaceBootstrapError:
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED") from None
    gate: subprocess.Popen[bytes] | None = None
    assigned = False
    termination_attempted = False
    termination_confirmed = False
    gate_exit_confirmed = False
    job_quiescence_confirmed = False
    stdout_capture: _BoundedPipeCapture | None = None
    stderr_capture: _BoundedPipeCapture | None = None
    captures_finish_confirmed = False

    def terminate_once() -> bool:
        nonlocal termination_attempted, termination_confirmed
        nonlocal gate_exit_confirmed, job_quiescence_confirmed
        if termination_attempted:
            return termination_confirmed
        if gate is None:
            return False
        termination_attempted = True
        try:
            termination_confirmed = _terminate_captured_windows_tree(
                job,
                gate,
                cleanup_deadline_monotonic=cleanup_deadline_monotonic,
            )
        except BaseException:
            termination_confirmed = False
        if termination_confirmed:
            gate_exit_confirmed = True
            job_quiescence_confirmed = True
        return termination_confirmed

    try:
        try:
            gate = subprocess.Popen(  # nosec B603
                (
                    os.path.abspath(sys.executable),
                    "-I",
                    "-B",
                    "-c",
                    _WINDOWS_CAPTURE_GATE_SOURCE,
                    "",
                    str(int(deadline_monotonic * 1_000_000_000)),
                    *command,
                ),
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                close_fds=True,
            )
        except (OSError, ValueError):
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED") from None
        try:
            job.assign_process(gate.pid)
            assigned = True
        except WorkspaceBootstrapError:
            gate.kill()
            try:
                _wait_for_process_before_deadline(
                    gate,
                    command=command,
                    timeout_seconds=max(
                        1,
                        int(cleanup_deadline_monotonic - time.monotonic()),
                    ),
                    deadline_monotonic=cleanup_deadline_monotonic,
                )
                gate_exit_confirmed = True
            except (OSError, subprocess.SubprocessError):
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                ) from None
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED") from None
        if gate.stdout is None or gate.stderr is None:
            if not terminate_once():
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVALID")
        stdout_capture = _BoundedPipeCapture(
            cast(BinaryIO, gate.stdout),
            maximum_bytes=maximum_stdout_bytes,
        )
        stderr_capture = _BoundedPipeCapture(
            cast(BinaryIO, gate.stderr),
            maximum_bytes=maximum_stderr_bytes,
        )
        try:
            stdout_capture.start()
            stderr_capture.start()
        except RecoveryV2SupervisionError:
            if not terminate_once():
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                ) from None
            raise
        try:
            if gate.stdin is None:
                raise OSError
            if time.monotonic() >= deadline_monotonic:
                if not terminate_once():
                    raise RecoveryV2SupervisionError(
                        "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                    )
                raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
            gate.stdin.write(_WINDOWS_GATE_RELEASE_TOKEN)
            gate.stdin.close()
        except (OSError, subprocess.SubprocessError):
            if not terminate_once():
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                ) from None
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED") from None
        state, returncode = _wait_for_captured_root(
            gate,
            stdout_capture,
            stderr_capture,
            deadline_monotonic=deadline_monotonic,
        )
        if state == "COMPLETE" and returncode is not None:
            gate_exit_confirmed = True
        if state != "COMPLETE":
            if not terminate_once():
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            raise RecoveryV2SupervisionError(
                {
                    "CAPTURE_INVALID": "RECOVERY_V2_CAPTURE_INVALID",
                    "OUTPUT_LIMIT": "RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
                    "TIMEOUT": "RECOVERY_V2_CAPTURE_TIMEOUT",
                }[state]
            )
        if returncode == _WINDOWS_GATE_TARGET_START_FAILED:
            raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_START_FAILED")
        quiescence = _wait_for_captured_windows_quiescence(
            job,
            stdout_capture,
            stderr_capture,
            cleanup_deadline_monotonic=cleanup_deadline_monotonic,
        )
        if quiescence != "QUIESCENT":
            if not terminate_once():
                raise RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
            raise RecoveryV2SupervisionError(
                {
                    "CAPTURE_INVALID": "RECOVERY_V2_CAPTURE_INVALID",
                    "OUTPUT_LIMIT": "RECOVERY_V2_CAPTURE_OUTPUT_LIMIT",
                    "RESIDUAL": "RECOVERY_V2_CAPTURE_RESIDUAL_DESCENDANT",
                }[quiescence]
            )
        job_quiescence_confirmed = True
        if returncode is None:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            )
        stdout, stderr = _finish_pipe_captures(
            stdout_capture,
            stderr_capture,
            cleanup_deadline_monotonic=cleanup_deadline_monotonic,
        )
        captures_finish_confirmed = True
        return CapturedChildResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        cleanup_failed = False
        capture_cleanup_error: RecoveryV2SupervisionError | None = None
        if gate is not None:
            if assigned:
                try:
                    timely_quiescence = termination_confirmed or (
                        gate_exit_confirmed and job_quiescence_confirmed
                    )
                    if not timely_quiescence:
                        timely_quiescence = (
                            _captured_windows_tree_quiescent_before_deadline(
                                job,
                                gate,
                                cleanup_deadline_monotonic=(
                                    cleanup_deadline_monotonic
                                ),
                            )
                        )
                        if timely_quiescence:
                            gate_exit_confirmed = True
                            job_quiescence_confirmed = True
                    if not timely_quiescence:
                        cleanup_failed = not terminate_once()
                except BaseException:
                    cleanup_failed = not terminate_once()
            elif not gate_exit_confirmed:
                try:
                    gate_state = _poll_process_before_deadline(
                        gate,
                        command=command,
                        deadline_monotonic=cleanup_deadline_monotonic,
                    )
                    if gate_state is None:
                        gate.kill()
                        _wait_for_process_before_deadline(
                            gate,
                            command=command,
                            timeout_seconds=max(
                                1,
                                int(
                                    cleanup_deadline_monotonic - time.monotonic()
                                ),
                            ),
                            deadline_monotonic=cleanup_deadline_monotonic,
                        )
                    gate_exit_confirmed = True
                except BaseException:
                    cleanup_failed = True
        if (
            stdout_capture is not None
            and stderr_capture is not None
            and not captures_finish_confirmed
        ):
            try:
                _finish_pipe_captures(
                    stdout_capture,
                    stderr_capture,
                    cleanup_deadline_monotonic=cleanup_deadline_monotonic,
                )
                captures_finish_confirmed = True
            except RecoveryV2SupervisionError as error:
                capture_cleanup_error = error
            except BaseException:
                capture_cleanup_error = RecoveryV2SupervisionError(
                    "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
                )
        if time.monotonic() >= cleanup_deadline_monotonic:
            cleanup_failed = True
        try:
            job.close()
        except WorkspaceBootstrapError:
            cleanup_failed = True
        if time.monotonic() >= cleanup_deadline_monotonic:
            cleanup_failed = True
        if cleanup_failed:
            raise RecoveryV2SupervisionError(
                "RECOVERY_V2_CAPTURE_TERMINATION_UNCONFIRMED"
            )
        if capture_cleanup_error is not None:
            raise capture_cleanup_error


def run_captured_child_once(
    command: Sequence[str],
    *,
    timeout_seconds: int,
    cwd: Path | None,
    environment: Mapping[str, str],
    maximum_stdout_bytes: int,
    maximum_stderr_bytes: int,
    absolute_deadline_monotonic: float | None = None,
    cleanup_deadline_monotonic: float | None = None,
) -> CapturedChildResult:
    """Run once, cap both output streams, and prove the whole tree quiescent."""

    if (
        type(timeout_seconds) is not int
        or timeout_seconds < 1
        or not command
        or any(not isinstance(argument, str) or not argument for argument in command)
        or type(maximum_stdout_bytes) is not int
        or maximum_stdout_bytes < 0
        or type(maximum_stderr_bytes) is not int
        or maximum_stderr_bytes < 0
        or any("\x00" in argument for argument in command)
        or (
            absolute_deadline_monotonic is not None
            and (
                isinstance(absolute_deadline_monotonic, bool)
                or not isinstance(absolute_deadline_monotonic, (int, float))
                or not math.isfinite(float(absolute_deadline_monotonic))
            )
        )
        or (
            cleanup_deadline_monotonic is not None
            and (
                isinstance(cleanup_deadline_monotonic, bool)
                or not isinstance(cleanup_deadline_monotonic, (int, float))
                or not math.isfinite(float(cleanup_deadline_monotonic))
            )
        )
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or "\x00" in name
            or "\x00" in value
            for name, value in environment.items()
        )
    ):
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_INVOCATION_INVALID")
    observed_monotonic = time.monotonic()
    deadline_monotonic = observed_monotonic + timeout_seconds
    if absolute_deadline_monotonic is not None:
        deadline_monotonic = min(
            deadline_monotonic,
            float(absolute_deadline_monotonic),
        )
    cleanup_deadline = (
        deadline_monotonic + CAPTURED_CHILD_CLEANUP_RESERVE_SECONDS
        if cleanup_deadline_monotonic is None
        else float(cleanup_deadline_monotonic)
    )
    if (
        deadline_monotonic <= observed_monotonic
        or cleanup_deadline <= deadline_monotonic
    ):
        raise RecoveryV2SupervisionError("RECOVERY_V2_CAPTURE_TIMEOUT")
    if os.name == "nt":
        return _run_captured_windows_child_once(
            command,
            deadline_monotonic=deadline_monotonic,
            cleanup_deadline_monotonic=cleanup_deadline,
            cwd=cwd,
            environment=environment,
            maximum_stdout_bytes=maximum_stdout_bytes,
            maximum_stderr_bytes=maximum_stderr_bytes,
        )
    return _run_captured_posix_child_once(
        command,
        deadline_monotonic=deadline_monotonic,
        cleanup_deadline_monotonic=cleanup_deadline,
        cwd=cwd,
        environment=environment,
        maximum_stdout_bytes=maximum_stdout_bytes,
        maximum_stderr_bytes=maximum_stderr_bytes,
    )


def remaining_effect_timeout(
    maximum_seconds: int,
    *,
    environment_name: str = "RECOVERY_V2_EFFECT_DEADLINE_EPOCH",
) -> int:
    """Bound production effects by the immutable workflow effect deadline."""

    if type(maximum_seconds) is not int or maximum_seconds < 1:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_INVOCATION_INVALID")
    raw = os.getenv(environment_name, "")
    if not raw:
        return maximum_seconds
    if not raw.isascii() or not raw.isdigit() or len(raw) > 12:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_DEADLINE_INVALID")
    remaining = math.floor(int(raw) - time.time() - _FINALIZATION_MARGIN_SECONDS)
    return max(0, min(maximum_seconds, remaining))


def require_effect_deadline_open(
    *,
    environment_name: str = "RECOVERY_V2_EFFECT_DEADLINE_EPOCH",
) -> None:
    """Refuse a parent-side evidence publication at or after its effect deadline."""

    raw = os.getenv(environment_name, "")
    if not raw:
        return
    if not raw.isascii() or not raw.isdigit() or len(raw) > 12:
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_DEADLINE_INVALID")
    if time.time() >= int(raw):
        raise RecoveryV2SupervisionError("RECOVERY_V2_SUPERVISOR_DEADLINE_EXPIRED")
