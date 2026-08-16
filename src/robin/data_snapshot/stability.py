"""Fail-closed continuous observation of a local filesystem tree."""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from robin.data_snapshot.contracts import SnapshotValidationError

_MUTATED = "FINALIZED_BATCH_MUTATED"
_UNSUPPORTED = "CONTINUOUS_TREE_OBSERVATION_UNSUPPORTED"
_ARM_FAILED = "CONTINUOUS_TREE_OBSERVATION_ARM_FAILED"
_FAILED = "CONTINUOUS_TREE_OBSERVATION_FAILED"
_CLOSED = "CONTINUOUS_TREE_OBSERVATION_CLOSED"
_WINDOWS_API_UNAVAILABLE = "WINDOWS_STABILITY_API_UNAVAILABLE"


class _CtypesFunction(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, *args: object) -> object: ...


class _WinDllLoader(Protocol):
    def __call__(self, name: str, *, use_last_error: bool) -> object: ...


_CreateFileW = Callable[[str, int, int, object | None, int, int, object | None], int | None]
_CreateEventW = Callable[[object | None, bool, bool, str | None], int | None]
_ReadDirectoryChangesW = Callable[
    [int, object, int, bool, int, object | None, object, object | None], int
]
_WaitForSingleObject = Callable[[int, int], int]
_CancelIoEx = Callable[[int, object], int]
_GetOverlappedResult = Callable[[int, object, object, bool], int]
_GetFileInformationByHandle = Callable[[int, object], int]
_CloseHandle = Callable[[int], int]
_GetDriveTypeW = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class _WindowsApi:
    create_file: _CreateFileW
    create_event: _CreateEventW
    read_directory_changes: _ReadDirectoryChangesW
    wait_for_single_object: _WaitForSingleObject
    cancel_io: _CancelIoEx
    get_overlapped_result: _GetOverlappedResult
    get_file_information: _GetFileInformationByHandle
    close_handle: _CloseHandle
    get_drive_type: _GetDriveTypeW
    get_last_error: Callable[[], int]
    set_last_error: Callable[[int], int]


def _configured_ctypes_function(
    owner: object,
    name: str,
    *,
    argtypes: tuple[object, ...],
    restype: object,
) -> _CtypesFunction:
    raw_function = getattr(owner, name, None)
    if not callable(raw_function):
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE)
    function = cast(_CtypesFunction, raw_function)
    try:
        function.argtypes = list(argtypes)
        function.restype = restype
    except (AttributeError, TypeError, ValueError):
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE) from None
    return function


def _resolve_windows_api(ctypes_module: object = ctypes) -> _WindowsApi:
    """Resolve the exact Windows symbols behind a narrow, typed boundary."""

    if sys.platform != "win32":
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE)
    raw_loader = getattr(ctypes_module, "WinDLL", None)
    raw_get_last_error = getattr(ctypes_module, "get_last_error", None)
    raw_set_last_error = getattr(ctypes_module, "set_last_error", None)
    if not all(callable(value) for value in (raw_loader, raw_get_last_error, raw_set_last_error)):
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE)
    loader = cast(_WinDllLoader, raw_loader)
    try:
        kernel32 = loader("kernel32", use_last_error=True)
        create_file = cast(
            _CreateFileW,
            _configured_ctypes_function(
                kernel32,
                "CreateFileW",
                argtypes=(
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.HANDLE,
                ),
                restype=wintypes.HANDLE,
            ),
        )
        create_event = cast(
            _CreateEventW,
            _configured_ctypes_function(
                kernel32,
                "CreateEventW",
                argtypes=(
                    wintypes.LPVOID,
                    wintypes.BOOL,
                    wintypes.BOOL,
                    wintypes.LPCWSTR,
                ),
                restype=wintypes.HANDLE,
            ),
        )
        read_directory_changes = cast(
            _ReadDirectoryChangesW,
            _configured_ctypes_function(
                kernel32,
                "ReadDirectoryChangesW",
                argtypes=(
                    wintypes.HANDLE,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.BOOL,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    ctypes.POINTER(_WindowsOverlapped),
                    wintypes.LPVOID,
                ),
                restype=wintypes.BOOL,
            ),
        )
        wait_for_single_object = cast(
            _WaitForSingleObject,
            _configured_ctypes_function(
                kernel32,
                "WaitForSingleObject",
                argtypes=(wintypes.HANDLE, wintypes.DWORD),
                restype=wintypes.DWORD,
            ),
        )
        cancel_io = cast(
            _CancelIoEx,
            _configured_ctypes_function(
                kernel32,
                "CancelIoEx",
                argtypes=(wintypes.HANDLE, ctypes.POINTER(_WindowsOverlapped)),
                restype=wintypes.BOOL,
            ),
        )
        get_overlapped_result = cast(
            _GetOverlappedResult,
            _configured_ctypes_function(
                kernel32,
                "GetOverlappedResult",
                argtypes=(
                    wintypes.HANDLE,
                    ctypes.POINTER(_WindowsOverlapped),
                    ctypes.POINTER(wintypes.DWORD),
                    wintypes.BOOL,
                ),
                restype=wintypes.BOOL,
            ),
        )
        get_file_information = cast(
            _GetFileInformationByHandle,
            _configured_ctypes_function(
                kernel32,
                "GetFileInformationByHandle",
                argtypes=(
                    wintypes.HANDLE,
                    ctypes.POINTER(_WindowsByHandleFileInformation),
                ),
                restype=wintypes.BOOL,
            ),
        )
        close_handle = cast(
            _CloseHandle,
            _configured_ctypes_function(
                kernel32,
                "CloseHandle",
                argtypes=(wintypes.HANDLE,),
                restype=wintypes.BOOL,
            ),
        )
        get_drive_type = cast(
            _GetDriveTypeW,
            _configured_ctypes_function(
                kernel32,
                "GetDriveTypeW",
                argtypes=(wintypes.LPCWSTR,),
                restype=wintypes.UINT,
            ),
        )
    except SnapshotValidationError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE) from None
    return _WindowsApi(
        create_file=create_file,
        create_event=create_event,
        read_directory_changes=read_directory_changes,
        wait_for_single_object=wait_for_single_object,
        cancel_io=cancel_io,
        get_overlapped_result=get_overlapped_result,
        get_file_information=get_file_information,
        close_handle=close_handle,
        get_drive_type=get_drive_type,
        get_last_error=cast(Callable[[], int], raw_get_last_error),
        set_last_error=cast(Callable[[int], int], raw_set_last_error),
    )


def _windows_drive_type(root: str, *, api: _WindowsApi | None = None) -> int:
    if sys.platform != "win32":
        raise SnapshotValidationError(_WINDOWS_API_UNAVAILABLE)
    resolved = api if api is not None else _resolve_windows_api()
    return int(resolved.get_drive_type(root))


class ContinuousTreeObservation(Protocol):
    """An already-armed sentinel for one filesystem tree."""

    def assert_unchanged(self) -> None:
        """Raise if any mutation or observation failure has occurred."""

    def close(self) -> None:
        """Perform a final check and release operating-system resources."""


class _WindowsOverlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class _WindowsByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _WindowsTreeObservation:
    _FILE_LIST_DIRECTORY = 0x0001
    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_OVERLAPPED = 0x40000000
    # Names, attributes, size, creation and ACLs. Existing files are protected by
    # deny-write handles; LAST_WRITE is excluded because traversing a child directory
    # can itself emit that notification on Windows.
    _NOTIFY_FILTER = 0x0000014F
    _ERROR_IO_PENDING = 997
    _ERROR_OPERATION_ABORTED = 995
    _ERROR_NOT_FOUND = 1168
    _WAIT_OBJECT_0 = 0
    _WAIT_TIMEOUT = 258
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _BUFFER_BYTES = 64 * 1024

    def __init__(self, root: Path, *, windows_api: _WindowsApi | None = None) -> None:
        self._closed = False
        self._changed = False
        self._armed = False
        self._handle = 0
        self._event = 0
        self._file_handles: list[int] = []
        self._windows_api = windows_api
        self._buffer: object | None = None
        self._overlapped = _WindowsOverlapped()
        self._arm(root)

    def _require_windows_api(self) -> _WindowsApi:
        if self._windows_api is None:
            raise SnapshotValidationError(_FAILED)
        return self._windows_api

    def _arm(self, root: Path) -> None:
        try:
            api = self._windows_api if self._windows_api is not None else _resolve_windows_api()
            self._windows_api = api
            raw_handle = api.create_file(
                os.path.abspath(os.fspath(root)),
                self._FILE_LIST_DIRECTORY,
                self._FILE_SHARE_READ | self._FILE_SHARE_WRITE,
                None,
                self._OPEN_EXISTING,
                self._FILE_FLAG_BACKUP_SEMANTICS
                | self._FILE_FLAG_OPEN_REPARSE_POINT
                | self._FILE_FLAG_OVERLAPPED,
                None,
            )
            if raw_handle in {None, self._INVALID_HANDLE_VALUE}:
                raise SnapshotValidationError(_ARM_FAILED)
            self._handle = int(raw_handle)

            raw_event = api.create_event(None, True, False, None)
            if not raw_event:
                raise SnapshotValidationError(_ARM_FAILED)
            self._event = int(raw_event)
            self._overlapped.hEvent = self._event
            self._buffer = ctypes.create_string_buffer(self._BUFFER_BYTES)

            api.set_last_error(0)
            started = bool(
                api.read_directory_changes(
                    self._handle,
                    self._buffer,
                    self._BUFFER_BYTES,
                    True,
                    self._NOTIFY_FILTER,
                    None,
                    ctypes.byref(self._overlapped),
                    None,
                )
            )
            if not started and api.get_last_error() != self._ERROR_IO_PENDING:
                raise SnapshotValidationError(_ARM_FAILED)
            self._armed = True
            self._lock_tree_files(root)
            self.assert_unchanged()
        except SnapshotValidationError:
            if self._armed:
                self._cancel_and_release()
            else:
                self._release_unarmed()
            raise
        except (AttributeError, OSError, TypeError, ValueError):
            if self._armed:
                self._cancel_and_release()
            else:
                self._release_unarmed()
            raise SnapshotValidationError(_ARM_FAILED) from None

    def _lock_tree_files(self, root: Path) -> None:
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda entry: entry.name)
            except OSError:
                raise SnapshotValidationError(_ARM_FAILED) from None
            for entry in entries:
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    raise SnapshotValidationError(_ARM_FAILED) from None
                attributes = getattr(metadata, "st_file_attributes", 0)
                if entry.is_symlink() or attributes & self._FILE_ATTRIBUTE_REPARSE_POINT:
                    raise SnapshotValidationError(_ARM_FAILED)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                # Windows DirEntry.stat() may report st_nlink=0. The authoritative
                # link count is checked from the opened handle in _lock_file().
                if not entry.is_file(follow_symlinks=False):
                    raise SnapshotValidationError(_ARM_FAILED)
                self._lock_file(Path(entry.path))

    def _lock_file(self, path: Path) -> None:
        api = self._require_windows_api()
        raw_handle = api.create_file(
            os.path.abspath(os.fspath(path)),
            self._GENERIC_READ,
            self._FILE_SHARE_READ,
            None,
            self._OPEN_EXISTING,
            self._FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
        if raw_handle in {None, self._INVALID_HANDLE_VALUE}:
            raise SnapshotValidationError(_ARM_FAILED)
        handle = int(raw_handle)
        information = _WindowsByHandleFileInformation()
        if not api.get_file_information(handle, ctypes.byref(information)):
            api.close_handle(handle)
            raise SnapshotValidationError(_ARM_FAILED)
        if (
            information.dwFileAttributes
            & (self._FILE_ATTRIBUTE_DIRECTORY | self._FILE_ATTRIBUTE_REPARSE_POINT)
            or information.nNumberOfLinks != 1
        ):
            api.close_handle(handle)
            raise SnapshotValidationError(_ARM_FAILED)
        self._file_handles.append(handle)

    def _release_unarmed(self) -> None:
        if self._windows_api is None:
            return
        api = self._windows_api
        for handle in reversed(self._file_handles):
            api.close_handle(handle)
        self._file_handles.clear()
        if self._event:
            api.close_handle(self._event)
            self._event = 0
        if self._handle:
            api.close_handle(self._handle)
            self._handle = 0

    def assert_unchanged(self) -> None:
        if self._closed:
            raise SnapshotValidationError(_CLOSED)
        if self._changed:
            raise SnapshotValidationError(_MUTATED)
        result = int(self._require_windows_api().wait_for_single_object(self._event, 0))
        if result == self._WAIT_TIMEOUT:
            return
        if result == self._WAIT_OBJECT_0:
            self._changed = True
            raise SnapshotValidationError(_MUTATED)
        raise SnapshotValidationError(_FAILED)

    def _cancel_and_release(self) -> str | None:
        failure: str | None = None
        api = self._require_windows_api()
        if self._armed:
            api.set_last_error(0)
            cancelled = bool(api.cancel_io(self._handle, ctypes.byref(self._overlapped)))
            cancel_error = api.get_last_error()
            if not cancelled and cancel_error != self._ERROR_NOT_FOUND:
                failure = _FAILED
            transferred = wintypes.DWORD()
            api.set_last_error(0)
            completed = bool(
                api.get_overlapped_result(
                    self._handle,
                    ctypes.byref(self._overlapped),
                    ctypes.byref(transferred),
                    True,
                )
            )
            completion_error = api.get_last_error()
            if completed:
                failure = _MUTATED
            elif completion_error != self._ERROR_OPERATION_ABORTED:
                failure = _FAILED
        for handle in reversed(self._file_handles):
            if not api.close_handle(handle):
                failure = failure or _FAILED
        self._file_handles.clear()
        if self._event and not api.close_handle(self._event):
            failure = failure or _FAILED
        if self._handle and not api.close_handle(self._handle):
            failure = failure or _FAILED
        self._event = 0
        self._handle = 0
        self._armed = False
        return failure

    def close(self) -> None:
        if self._closed:
            return
        observed_error: SnapshotValidationError | None = None
        try:
            self.assert_unchanged()
        except SnapshotValidationError as exc:
            observed_error = exc
        self._closed = True
        cleanup_failure = self._cancel_and_release()
        if observed_error is not None:
            raise observed_error
        if cleanup_failure is not None:
            raise SnapshotValidationError(cleanup_failure)


class _LinuxTreeObservation:
    _IN_MODIFY = 0x00000002
    _IN_ATTRIB = 0x00000004
    _IN_CLOSE_WRITE = 0x00000008
    _IN_MOVED_FROM = 0x00000040
    _IN_MOVED_TO = 0x00000080
    _IN_CREATE = 0x00000100
    _IN_DELETE = 0x00000200
    _IN_DELETE_SELF = 0x00000400
    _IN_MOVE_SELF = 0x00000800
    _IN_UNMOUNT = 0x00002000
    _IN_Q_OVERFLOW = 0x00004000
    _IN_IGNORED = 0x00008000
    _IN_ONLYDIR = 0x01000000
    _IN_DONT_FOLLOW = 0x02000000
    _COMMON_WATCH_MASK = (
        _IN_MODIFY
        | _IN_ATTRIB
        | _IN_CLOSE_WRITE
        | _IN_DELETE_SELF
        | _IN_MOVE_SELF
        | _IN_UNMOUNT
        | _IN_Q_OVERFLOW
        | _IN_IGNORED
        | _IN_DONT_FOLLOW
    )
    _DIRECTORY_WATCH_MASK = (
        _COMMON_WATCH_MASK | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE | _IN_ONLYDIR
    )
    _FILE_WATCH_MASK = _COMMON_WATCH_MASK
    _BUFFER_BYTES = 64 * 1024

    def __init__(self, root: Path) -> None:
        self._closed = False
        self._changed = False
        self._fd = -1
        self._libc: Any = None
        self._watch_descriptors: set[int] = set()
        self._arm(root)

    def _arm(self, root: Path) -> None:
        try:
            libc: Any = ctypes.CDLL(None, use_errno=True)
            init = libc.inotify_init1
            add_watch = libc.inotify_add_watch
        except (AttributeError, OSError):
            raise SnapshotValidationError(_UNSUPPORTED) from None
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        self._libc = libc
        nonblocking = getattr(os, "O_NONBLOCK", None)
        close_on_exec = getattr(os, "O_CLOEXEC", None)
        if not isinstance(nonblocking, int) or not isinstance(close_on_exec, int):
            raise SnapshotValidationError(_UNSUPPORTED)
        self._fd = int(init(nonblocking | close_on_exec))
        if self._fd < 0:
            raise SnapshotValidationError(_ARM_FAILED)
        try:
            self._arm_tree(root, add_watch)
            self.assert_unchanged()
        except SnapshotValidationError:
            os.close(self._fd)
            self._fd = -1
            raise
        except OSError:
            os.close(self._fd)
            self._fd = -1
            raise SnapshotValidationError(_ARM_FAILED) from None

    def _add_watch(self, path: Path, add_watch: Any, mask: int) -> None:
        descriptor = int(add_watch(self._fd, os.fsencode(path), ctypes.c_uint32(mask)))
        if descriptor < 0:
            raise SnapshotValidationError(_ARM_FAILED)
        self._watch_descriptors.add(descriptor)

    def _arm_tree(self, root: Path, add_watch: Any) -> None:
        root_metadata = os.lstat(root)
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise SnapshotValidationError(_ARM_FAILED)
        pending = [root]
        seen: set[tuple[int, int]] = set()
        while pending:
            directory = pending.pop()
            metadata = os.lstat(directory)
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            self._add_watch(directory, add_watch, self._DIRECTORY_WATCH_MASK)
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name, reverse=True)
            for entry in children:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if (
                    entry.is_symlink()
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_nlink != 1
                ):
                    raise SnapshotValidationError(_ARM_FAILED)
                self._add_watch(Path(entry.path), add_watch, self._FILE_WATCH_MASK)

    def assert_unchanged(self) -> None:
        if self._closed:
            raise SnapshotValidationError(_CLOSED)
        if self._changed:
            raise SnapshotValidationError(_MUTATED)
        try:
            events = os.read(self._fd, self._BUFFER_BYTES)
        except BlockingIOError:
            return
        except OSError:
            raise SnapshotValidationError(_FAILED) from None
        if events:
            self._changed = True
            raise SnapshotValidationError(_MUTATED)
        raise SnapshotValidationError(_FAILED)

    def close(self) -> None:
        if self._closed:
            return
        observed_error: SnapshotValidationError | None = None
        try:
            self.assert_unchanged()
        except SnapshotValidationError as exc:
            observed_error = exc
        self._closed = True
        try:
            os.close(self._fd)
        except OSError:
            if observed_error is None:
                observed_error = SnapshotValidationError(_FAILED)
        self._fd = -1
        if observed_error is not None:
            raise observed_error


def _new_observation(root: Path) -> ContinuousTreeObservation:
    if sys.platform == "win32":
        return _WindowsTreeObservation(root)
    if sys.platform.startswith("linux"):
        return _LinuxTreeObservation(root)
    raise SnapshotValidationError(_UNSUPPORTED)


@contextmanager
def continuous_tree_observer(root: Path) -> Iterator[ContinuousTreeObservation]:
    """Arm a recursive OS sentinel before yielding control to the caller."""

    observation = _new_observation(root)
    try:
        yield observation
    except BaseException:
        try:
            observation.close()
        except SnapshotValidationError:
            pass
        raise
    else:
        observation.close()
