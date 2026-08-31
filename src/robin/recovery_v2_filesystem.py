"""Handle-anchored filesystem access for Recovery V2 evidence."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import secrets
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


class RecoveryV2FilesystemError(OSError):
    """A path could not be mutated inside its verified repository capability."""


def _lexical_parts(path: Path, *, repository_root: Path) -> tuple[Path, Path, tuple[str, ...]]:
    root = Path(os.path.abspath(repository_root))
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID") from None
    parts = relative.parts
    if any(not part or part in {".", ".."} for part in parts):
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    return root, candidate, parts


def _regular(metadata: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISREG(metadata.st_mode) and not bool(
        getattr(metadata, "st_file_attributes", 0) & reparse
    )


def _directory(metadata: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISDIR(metadata.st_mode) and not bool(
        getattr(metadata, "st_file_attributes", 0) & reparse
    )


def _after_parent_capability_acquired(_parent: Path) -> None:
    """Deterministic test seam after every ancestor is anchored."""


def _write_fd(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_WRITE_INVALID")
        offset += written
    os.fsync(descriptor)


def _posix_open_directory_chain(
    path: Path,
    *,
    repository_root: Path,
) -> tuple[list[int], int]:
    root, candidate, parts = _lexical_parts(path, repository_root=repository_root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        descriptor = os.open(root, flags)
        descriptors.append(descriptor)
        if not _directory(os.fstat(descriptor)):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID")
        for part in parts:
            child = os.open(part, flags, dir_fd=descriptor)
            if not _directory(os.fstat(child)):
                os.close(child)
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                )
            descriptors.append(child)
            descriptor = child
        if candidate != root.joinpath(*parts):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
        return descriptors, descriptor
    except BaseException:
        for opened in reversed(descriptors):
            try:
                os.close(opened)
            except OSError:
                pass
        raise


def _posix_require_attached_directory(
    descriptor: int,
    path: Path,
    *,
    repository_root: Path,
) -> None:
    """Bind an acquired directory back to the current no-symlink root chain."""

    try:
        descriptors, observed = _posix_open_directory_chain(
            path,
            repository_root=repository_root,
        )
    except OSError:
        raise RecoveryV2FilesystemError(
            "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
        ) from None
    try:
        anchored = os.fstat(descriptor)
        current = os.fstat(observed)
        if (anchored.st_dev, anchored.st_ino) != (current.st_dev, current.st_ino):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED")
    finally:
        for opened in reversed(descriptors):
            try:
                os.close(opened)
            except OSError:
                pass


@contextmanager
def _posix_directory_capability(
    path: Path,
    *,
    repository_root: Path,
    create: bool,
) -> Iterator[int]:
    root, candidate, parts = _lexical_parts(path, repository_root=repository_root)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        descriptor = os.open(root, flags)
        descriptors.append(descriptor)
        if not _directory(os.fstat(descriptor)):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID")
        for part in parts:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            metadata = os.fstat(child)
            if not _directory(metadata):
                os.close(child)
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                )
            descriptors.append(child)
            descriptor = child
        if candidate != root.joinpath(*parts):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
        _after_parent_capability_acquired(candidate)
        _posix_require_attached_directory(
            descriptor,
            candidate,
            repository_root=root,
        )
        yield descriptor
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _NTDLL = ctypes.WinDLL("ntdll")
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _DELETE = 0x00010000
    _SYNCHRONIZE = 0x00100000
    _FILE_LIST_DIRECTORY = 0x00000001
    _FILE_ADD_SUBDIRECTORY = 0x00000004
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
    _FILE_RENAME_INFORMATION_CLASS = 10
    _FILE_DISPOSITION_INFORMATION_CLASS = 13
    _OBJECT_CASE_INSENSITIVE = 0x00000040
    _FILE_OPEN = 1
    _FILE_CREATE = 2
    _FILE_DIRECTORY_FILE = 0x00000001
    _FILE_WRITE_THROUGH_OPTION = 0x00000002
    _FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _FILE_NON_DIRECTORY_FILE = 0x00000040
    _FILE_OPEN_REPARSE_POINT_OPTION = 0x00200000
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
    _ERROR_FILE_EXISTS = 80
    _ERROR_ALREADY_EXISTS = 183

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD))

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("FileAttributes", wintypes.DWORD),
            ("CreationTimeLow", wintypes.DWORD),
            ("CreationTimeHigh", wintypes.DWORD),
            ("LastAccessTimeLow", wintypes.DWORD),
            ("LastAccessTimeHigh", wintypes.DWORD),
            ("LastWriteTimeLow", wintypes.DWORD),
            ("LastWriteTimeHigh", wintypes.DWORD),
            ("VolumeSerialNumber", wintypes.DWORD),
            ("FileSizeHigh", wintypes.DWORD),
            ("FileSizeLow", wintypes.DWORD),
            ("NumberOfLinks", wintypes.DWORD),
            ("FileIndexHigh", wintypes.DWORD),
            ("FileIndexLow", wintypes.DWORD),
        )

    class _FileRenameInfo(ctypes.Structure):
        _fields_ = (
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        )

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = (("DeleteFile", ctypes.c_ubyte),)

    class _IoStatusBlock(ctypes.Structure):
        _fields_ = (("Status", ctypes.c_long), ("Information", ctypes.c_void_p))

    class _UnicodeString(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        )

    class _ObjectAttributes(ctypes.Structure):
        _fields_ = (
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        )

    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _CREATE_FILE.restype = wintypes.HANDLE
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = (wintypes.HANDLE,)
    _CLOSE_HANDLE.restype = wintypes.BOOL
    _GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandleEx
    _GET_FILE_INFORMATION.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _GET_FILE_INFORMATION.restype = wintypes.BOOL
    _GET_FILE_ATTRIBUTES = _KERNEL32.GetFileAttributesW
    _GET_FILE_ATTRIBUTES.argtypes = (wintypes.LPCWSTR,)
    _GET_FILE_ATTRIBUTES.restype = wintypes.DWORD
    _GET_FILE_INFORMATION_BY_HANDLE = _KERNEL32.GetFileInformationByHandle
    _GET_FILE_INFORMATION_BY_HANDLE.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    )
    _GET_FILE_INFORMATION_BY_HANDLE.restype = wintypes.BOOL
    _WRITE_FILE = _KERNEL32.WriteFile
    _WRITE_FILE.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _WRITE_FILE.restype = wintypes.BOOL
    _READ_FILE = _KERNEL32.ReadFile
    _READ_FILE.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _READ_FILE.restype = wintypes.BOOL
    _GET_FILE_SIZE = _KERNEL32.GetFileSizeEx
    _GET_FILE_SIZE.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    _GET_FILE_SIZE.restype = wintypes.BOOL
    _FLUSH_FILE_BUFFERS = _KERNEL32.FlushFileBuffers
    _FLUSH_FILE_BUFFERS.argtypes = (wintypes.HANDLE,)
    _FLUSH_FILE_BUFFERS.restype = wintypes.BOOL
    _NT_SET_FILE_INFORMATION = _NTDLL.NtSetInformationFile
    _NT_SET_FILE_INFORMATION.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    )
    _NT_SET_FILE_INFORMATION.restype = ctypes.c_long
    _NT_CREATE_FILE = _NTDLL.NtCreateFile
    _NT_CREATE_FILE.argtypes = (
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        wintypes.LPVOID,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.LPVOID,
        wintypes.ULONG,
    )
    _NT_CREATE_FILE.restype = ctypes.c_long
    _RTL_NT_STATUS_TO_DOS_ERROR = _NTDLL.RtlNtStatusToDosError
    _RTL_NT_STATUS_TO_DOS_ERROR.argtypes = (ctypes.c_long,)
    _RTL_NT_STATUS_TO_DOS_ERROR.restype = wintypes.ULONG


def _windows_error(path: Path) -> OSError:
    code = ctypes.get_last_error()
    message = ctypes.FormatError(code)
    if code in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
        return FileNotFoundError(code, message, str(path))
    if code in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
        return FileExistsError(code, message, str(path))
    return RecoveryV2FilesystemError(code, message, str(path))


def _windows_close(handle: int) -> None:
    if handle not in {0, None, _INVALID_HANDLE_VALUE}:
        _CLOSE_HANDLE(handle)


def _windows_attributes(handle: int) -> int:
    information = _FileAttributeTagInfo()
    if not _GET_FILE_INFORMATION(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise _windows_error(Path("<handle>"))
    return int(information.FileAttributes)


def _windows_identity(handle: int) -> tuple[int, int]:
    information = _ByHandleFileInformation()
    if not _GET_FILE_INFORMATION_BY_HANDLE(handle, ctypes.byref(information)):
        raise _windows_error(Path("<handle>"))
    return (
        int(information.VolumeSerialNumber),
        (int(information.FileIndexHigh) << 32) | int(information.FileIndexLow),
    )


def _windows_open_directory(
    path: Path,
    *,
    create_children: bool = False,
    mutation: bool = False,
    share_delete: bool = False,
) -> int:
    access = _FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
    if create_children:
        access |= _FILE_ADD_SUBDIRECTORY
    if mutation:
        access |= _GENERIC_WRITE
    handle = _CREATE_FILE(
        str(path),
        access,
        _FILE_SHARE_READ
        | _FILE_SHARE_WRITE
        | (_FILE_SHARE_DELETE if share_delete else 0),
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise _windows_error(path)
    attributes = _windows_attributes(handle)
    if not attributes & _FILE_ATTRIBUTE_DIRECTORY or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        _windows_close(handle)
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID")
    return int(handle)


def _windows_relative_name(name: str) -> tuple[ctypes.Array[ctypes.c_wchar], _UnicodeString]:
    if not name or name in {".", ".."} or "\\" in name or "/" in name:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    name_buffer = ctypes.create_unicode_buffer(name)
    encoded_length = len(name.encode("utf-16-le"))
    object_name = _UnicodeString(
        Length=encoded_length,
        MaximumLength=encoded_length + ctypes.sizeof(wintypes.WCHAR),
        Buffer=ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    return name_buffer, object_name


def _windows_open_relative(
    *,
    parent_handle: int,
    name: str,
    desired_access: int,
    share_access: int,
    disposition: int,
    attributes: int,
    create_options: int,
) -> int:
    name_buffer, object_name = _windows_relative_name(name)
    object_attributes = _ObjectAttributes(
        Length=ctypes.sizeof(_ObjectAttributes),
        RootDirectory=parent_handle,
        ObjectName=ctypes.pointer(object_name),
        Attributes=_OBJECT_CASE_INSENSITIVE,
        SecurityDescriptor=None,
        SecurityQualityOfService=None,
    )
    status_block = _IoStatusBlock()
    handle = wintypes.HANDLE()
    status = _NT_CREATE_FILE(
        ctypes.byref(handle),
        desired_access,
        ctypes.byref(object_attributes),
        ctypes.byref(status_block),
        None,
        attributes,
        share_access,
        disposition,
        create_options,
        None,
        0,
    )
    _ = name_buffer
    if status != 0:
        ctypes.set_last_error(int(_RTL_NT_STATUS_TO_DOS_ERROR(status)))
        raise _windows_error(Path(name))
    return int(handle.value)


def _windows_create_directory(*, parent_handle: int, name: str) -> int:
    handle = _windows_open_relative(
        parent_handle=parent_handle,
        name=name,
        desired_access=(
            _FILE_LIST_DIRECTORY
            | _FILE_ADD_SUBDIRECTORY
            | _FILE_READ_ATTRIBUTES
            | _GENERIC_WRITE
            | _SYNCHRONIZE
        ),
        share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        disposition=_FILE_CREATE,
        attributes=_FILE_ATTRIBUTE_DIRECTORY,
        create_options=(
            _FILE_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_WRITE_THROUGH_OPTION
            | _FILE_OPEN_REPARSE_POINT_OPTION
        ),
    )
    attributes = _windows_attributes(handle)
    if not attributes & _FILE_ATTRIBUTE_DIRECTORY or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        _windows_close(handle)
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID")
    return handle


@contextmanager
def _windows_directory_capability(
    path: Path,
    *,
    repository_root: Path,
    create: bool,
    mutation: bool,
) -> Iterator[int]:
    root, candidate, parts = _lexical_parts(path, repository_root=repository_root)
    handles: list[int] = []
    try:
        handle = _windows_open_directory(
            root,
            create_children=create,
            mutation=mutation or create,
        )
        handles.append(handle)
        current = root
        for part in parts:
            current = current / part
            try:
                child = _windows_open_directory(
                    current,
                    create_children=create,
                    mutation=mutation or create,
                )
            except FileNotFoundError:
                if not create:
                    raise
                child = _windows_create_directory(parent_handle=handle, name=part)
                _windows_flush_handle(handle)
            handles.append(child)
            handle = child
        if candidate != current:
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
        _after_parent_capability_acquired(candidate)
        yield handle
    finally:
        for handle in reversed(handles):
            _windows_close(handle)


@contextmanager
def _directory_capability(
    path: Path,
    *,
    repository_root: Path,
    create: bool,
    mutation: bool = False,
) -> Iterator[int]:
    if os.name == "nt":
        with _windows_directory_capability(
            path,
            repository_root=repository_root,
            create=create,
            mutation=mutation,
        ) as handle:
            yield handle
    else:
        with _posix_directory_capability(
            path,
            repository_root=repository_root,
            create=create,
        ) as descriptor:
            yield descriptor


def _windows_create_file(*, parent_handle: int, name: str) -> int:
    return _windows_open_relative(
        parent_handle=parent_handle,
        name=name,
        desired_access=_GENERIC_READ | _GENERIC_WRITE | _DELETE | _SYNCHRONIZE,
        share_access=_FILE_SHARE_READ,
        disposition=_FILE_CREATE,
        attributes=_FILE_ATTRIBUTE_NORMAL,
        create_options=(
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_WRITE_THROUGH_OPTION
            | _FILE_OPEN_REPARSE_POINT_OPTION
        ),
    )


def _windows_write(handle: int, payload: bytes) -> None:
    if payload:
        buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        if not _WRITE_FILE(handle, buffer, len(payload), ctypes.byref(written), None):
            raise _windows_error(Path("<handle>"))
        if int(written.value) != len(payload):
            raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_WRITE_INVALID")
    if not _FLUSH_FILE_BUFFERS(handle):
        raise _windows_error(Path("<handle>"))


def _windows_flush_handle(handle: int) -> None:
    if not _FLUSH_FILE_BUFFERS(handle):
        raise _windows_error(Path("<handle>"))


def _windows_rename_handle(
    handle: int,
    *,
    parent_handle: int,
    destination_name: str,
    replace: bool,
) -> None:
    encoded = destination_name.encode("utf-16-le")
    offset = _FileRenameInfo.FileName.offset
    buffer = ctypes.create_string_buffer(offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR))
    information = _FileRenameInfo.from_buffer(buffer)
    information.ReplaceIfExists = bool(replace)
    information.RootDirectory = parent_handle
    information.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
    status_block = _IoStatusBlock()
    status = _NT_SET_FILE_INFORMATION(
        handle,
        ctypes.byref(status_block),
        buffer,
        len(buffer),
        _FILE_RENAME_INFORMATION_CLASS,
    )
    if status != 0:
        ctypes.set_last_error(int(_RTL_NT_STATUS_TO_DOS_ERROR(status)))
        raise _windows_error(Path(destination_name))


def _windows_delete_handle(handle: int) -> None:
    information = _FileDispositionInfo(DeleteFile=True)
    status_block = _IoStatusBlock()
    status = _NT_SET_FILE_INFORMATION(
        handle,
        ctypes.byref(status_block),
        ctypes.byref(information),
        ctypes.sizeof(information),
        _FILE_DISPOSITION_INFORMATION_CLASS,
    )
    if status != 0:
        ctypes.set_last_error(int(_RTL_NT_STATUS_TO_DOS_ERROR(status)))
        raise _windows_error(Path("<handle>"))


def _windows_require_regular_handle(handle: int) -> None:
    attributes = _windows_attributes(handle)
    if attributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_FILE_INVALID")


def _windows_open_read(
    *,
    parent_handle: int,
    name: str,
    share_delete: bool = False,
) -> int:
    handle = _windows_open_relative(
        parent_handle=parent_handle,
        name=name,
        desired_access=_GENERIC_READ | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_access=(
            _FILE_SHARE_READ | (_FILE_SHARE_DELETE if share_delete else 0)
        ),
        disposition=_FILE_OPEN,
        attributes=_FILE_ATTRIBUTE_NORMAL,
        create_options=(
            _FILE_NON_DIRECTORY_FILE
            | _FILE_SYNCHRONOUS_IO_NONALERT
            | _FILE_OPEN_REPARSE_POINT_OPTION
        ),
    )
    try:
        _windows_require_regular_handle(handle)
    except BaseException:
        _windows_close(handle)
        raise
    return handle


def _windows_read(handle: int, *, maximum_bytes: int) -> bytes:
    size = ctypes.c_longlong()
    if not _GET_FILE_SIZE(handle, ctypes.byref(size)):
        raise _windows_error(Path("<handle>"))
    if size.value < 0 or size.value > maximum_bytes:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_SIZE_INVALID")
    if size.value == 0:
        return b""
    buffer = ctypes.create_string_buffer(size.value)
    read = wintypes.DWORD()
    if not _READ_FILE(handle, buffer, size.value, ctypes.byref(read), None):
        raise _windows_error(Path("<handle>"))
    if int(read.value) != size.value:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_READ_INVALID")
    return bytes(buffer.raw)


def _posix_unlink_if_identity(
    name: str,
    *,
    parent: int,
    expected: os.stat_result,
) -> None:
    try:
        observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if _regular(observed) and (observed.st_dev, observed.st_ino) == (
        expected.st_dev,
        expected.st_ino,
    ):
        os.unlink(name, dir_fd=parent)


def _posix_rename_noreplace(
    source_name: str,
    *,
    source_parent: int,
    destination_name: str,
    destination_parent: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RecoveryV2FilesystemError(
            "RECOVERY_V2_FILESYSTEM_NOREPLACE_UNSUPPORTED"
        )
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_parent,
        os.fsencode(source_name),
        destination_parent,
        os.fsencode(destination_name),
        1,  # RENAME_NOREPLACE
    )
    if result == 0:
        return
    code = ctypes.get_errno()
    if code == errno.EEXIST:
        raise FileExistsError(code, os.strerror(code), destination_name)
    raise RecoveryV2FilesystemError(code, os.strerror(code), destination_name)


def prepare_repository_directory(path: Path, *, repository_root: Path) -> None:
    with _directory_capability(path, repository_root=repository_root, create=True):
        return


def require_inherited_windows_directory_capability(
    handle: int,
    path: Path,
    *,
    repository_root: Path,
) -> None:
    """Prove that an inherited Windows handle is the expected rooted directory."""

    if os.name != "nt" or type(handle) is not int or handle <= 0:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    _root, candidate, _parts = _lexical_parts(path, repository_root=repository_root)
    try:
        attributes = _windows_attributes(handle)
        inherited_identity = _windows_identity(handle)
    except OSError:
        raise RecoveryV2FilesystemError(
            "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
        ) from None
    observed = _windows_open_directory(candidate)
    try:
        if (
            attributes & _FILE_ATTRIBUTE_REPARSE_POINT
            or not attributes & _FILE_ATTRIBUTE_DIRECTORY
            or _windows_identity(observed) != inherited_identity
        ):
            raise RecoveryV2FilesystemError(
                "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
            )
    finally:
        _windows_close(observed)


@dataclass(frozen=True)
class AnchoredTemporaryDirectory:
    """A newly created directory whose capability remains open for one child run."""

    path: Path
    runtime_path: Path
    pass_fds: tuple[int, ...]
    pass_handles: tuple[int, ...]
    _handle: int
    _repository_root: Path

    def require_attached(self) -> None:
        if os.name == "nt":
            observed = _windows_open_directory(self.path)
            try:
                if _windows_identity(observed) != _windows_identity(self._handle):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
                    )
            finally:
                _windows_close(observed)
            return
        _posix_require_attached_directory(
            self._handle,
            self.path,
            repository_root=self._repository_root,
        )


@contextmanager
def anchored_temporary_directory(
    parent: Path,
    *,
    prefix: str,
    repository_root: Path,
) -> Iterator[AnchoredTemporaryDirectory]:
    """Create one unpredictable directory below an anchored repository parent.

    The directory is deliberately retained after the context exits. On POSIX the
    child receives an inherited descriptor path, so a concurrent path rename cannot
    redirect its writes. Windows keeps a non-delete-shared handle open instead.
    """

    if (
        not prefix
        or len(prefix) > 80
        or prefix in {".", ".."}
        or "/" in prefix
        or "\\" in prefix
    ):
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    root, parent_path, _parts = _lexical_parts(parent, repository_root=repository_root)
    with _directory_capability(
        parent_path,
        repository_root=root,
        create=False,
        mutation=True,
    ) as parent_handle:
        for _attempt in range(128):
            name = f"{prefix}{secrets.token_hex(16)}"
            directory_path = parent_path / name
            if os.name == "nt":
                try:
                    handle = _windows_create_directory(
                        parent_handle=parent_handle,
                        name=name,
                    )
                except FileExistsError:
                    continue
                try:
                    _windows_flush_handle(handle)
                    _windows_flush_handle(parent_handle)
                    lease = AnchoredTemporaryDirectory(
                        path=directory_path,
                        runtime_path=directory_path,
                        pass_fds=(),
                        pass_handles=(handle,),
                        _handle=handle,
                        _repository_root=root,
                    )
                    lease.require_attached()
                    yield lease
                finally:
                    _windows_close(handle)
                return

            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_handle)
            except FileExistsError:
                continue
            descriptor: int | None = None
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_handle,
                )
                if not _directory(os.fstat(descriptor)):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                    )
                os.fsync(parent_handle)
                lease = AnchoredTemporaryDirectory(
                    path=directory_path,
                    runtime_path=Path(f"/proc/self/fd/{descriptor}"),
                    pass_fds=(descriptor,),
                    pass_handles=(),
                    _handle=descriptor,
                    _repository_root=root,
                )
                lease.require_attached()
                yield lease
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            return
    raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_TEMPORARY_EXHAUSTED")


def read_bytes(path: Path, *, repository_root: Path, maximum_bytes: int) -> bytes:
    """Read one regular leaf while its verified parent capability remains anchored."""

    if type(maximum_bytes) is not int or maximum_bytes < 0:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_SIZE_INVALID")
    _root, target, parts = _lexical_parts(path, repository_root=repository_root)
    if not parts:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    with _directory_capability(
        target.parent,
        repository_root=repository_root,
        create=False,
    ) as parent:
        if os.name == "nt":
            handle = _windows_open_read(parent_handle=parent, name=target.name)
            try:
                return _windows_read(handle, maximum_bytes=maximum_bytes)
            finally:
                _windows_close(handle)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(target.name, flags, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            if not _regular(before) or before.st_size < 0 or before.st_size > maximum_bytes:
                raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_FILE_INVALID")
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            after = os.fstat(descriptor)
            if (
                len(payload) > maximum_bytes
                or len(payload) != after.st_size
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )
            ):
                raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_READ_INVALID")
            _posix_require_attached_directory(
                parent,
                target.parent,
                repository_root=repository_root,
            )
            return payload
        finally:
            os.close(descriptor)


def publish_exclusive_bytes(path: Path, payload: bytes, *, repository_root: Path) -> None:
    _root, target, parts = _lexical_parts(path, repository_root=repository_root)
    if not parts:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    candidate_name = f".{target.name}.recovery-v2-create"
    with _directory_capability(
        target.parent,
        repository_root=repository_root,
        create=True,
        mutation=True,
    ) as parent:
        if os.name == "nt":
            attributes = int(_GET_FILE_ATTRIBUTES(str(target)))
            if attributes != 0xFFFFFFFF:
                raise FileExistsError(str(target))
            handle = _windows_create_file(parent_handle=parent, name=candidate_name)
            renamed = False
            try:
                _windows_write(handle, payload)
                _windows_rename_handle(
                    handle,
                    parent_handle=parent,
                    destination_name=target.name,
                    replace=False,
                )
                renamed = True
                _windows_require_regular_handle(handle)
                _windows_flush_handle(handle)
                _windows_flush_handle(parent)
            except OSError:
                rollback_failed = False
                try:
                    if renamed:
                        _windows_rename_handle(
                            handle,
                            parent_handle=parent,
                            destination_name=candidate_name,
                            replace=False,
                        )
                    _windows_delete_handle(handle)
                    _windows_flush_handle(parent)
                except OSError:
                    rollback_failed = True
                if rollback_failed:
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                    ) from None
                raise
            finally:
                _windows_close(handle)
            return
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(candidate_name, flags, 0o600, dir_fd=parent)
            target_published = False
            committed = False
            metadata: os.stat_result | None = None
            try:
                _write_fd(descriptor, payload)
                metadata = os.fstat(descriptor)
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
                os.link(
                    candidate_name,
                    target.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
                target_published = True
                observed = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
                if not _regular(observed) or (observed.st_dev, observed.st_ino) != (
                    metadata.st_dev,
                    metadata.st_ino,
                ):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                    )
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
                os.fsync(parent)
                committed = True
            except OSError:
                rollback_failed = False
                try:
                    if metadata is not None:
                        if target_published and not committed:
                            _posix_unlink_if_identity(
                                target.name,
                                parent=parent,
                                expected=metadata,
                            )
                        _posix_unlink_if_identity(
                            candidate_name,
                            parent=parent,
                            expected=metadata,
                        )
                    os.fsync(parent)
                except OSError:
                    rollback_failed = True
                if rollback_failed:
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                    ) from None
                raise
            try:
                os.unlink(candidate_name, dir_fd=parent)
            except OSError:
                pass
            try:
                os.fsync(parent)
            except OSError:
                pass
            try:
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
            except OSError:
                assert metadata is not None
                rollback_failed = False
                try:
                    _posix_unlink_if_identity(
                        target.name,
                        parent=parent,
                        expected=metadata,
                    )
                    _posix_unlink_if_identity(
                        candidate_name,
                        parent=parent,
                        expected=metadata,
                    )
                    os.fsync(parent)
                except OSError:
                    rollback_failed = True
                if rollback_failed:
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                    ) from None
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
                ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)


def replace_bytes(path: Path, payload: bytes, *, repository_root: Path) -> None:
    _root, target, parts = _lexical_parts(path, repository_root=repository_root)
    if not parts:
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")
    candidate_name = f".{target.name}.recovery-v2-update"
    backup_name = f".{target.name}.recovery-v2-previous"
    with _directory_capability(
        target.parent,
        repository_root=repository_root,
        create=False,
        mutation=True,
    ) as parent:
        if os.name == "nt":
            current_handle = _windows_open_read(parent_handle=parent, name=target.name)
            try:
                old_payload = _windows_read(current_handle, maximum_bytes=64 * 1024 * 1024)
            finally:
                _windows_close(current_handle)
            handle = _windows_create_file(parent_handle=parent, name=candidate_name)
            renamed = False
            try:
                _windows_write(handle, payload)
                _windows_rename_handle(
                    handle,
                    parent_handle=parent,
                    destination_name=target.name,
                    replace=True,
                )
                renamed = True
                _windows_require_regular_handle(handle)
                _windows_flush_handle(handle)
                _windows_flush_handle(parent)
            except OSError:
                rollback_failed = False
                rollback_handle: int | None = None
                try:
                    if renamed:
                        _windows_rename_handle(
                            handle,
                            parent_handle=parent,
                            destination_name=candidate_name,
                            replace=False,
                        )
                        rollback_name = f".{target.name}.recovery-v2-rollback"
                        rollback_handle = _windows_create_file(
                            parent_handle=parent,
                            name=rollback_name,
                        )
                        _windows_write(rollback_handle, old_payload)
                        _windows_rename_handle(
                            rollback_handle,
                            parent_handle=parent,
                            destination_name=target.name,
                            replace=False,
                        )
                        _windows_flush_handle(rollback_handle)
                    _windows_delete_handle(handle)
                    _windows_flush_handle(parent)
                except OSError:
                    rollback_failed = True
                finally:
                    if rollback_handle is not None:
                        _windows_close(rollback_handle)
                if rollback_failed:
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                    ) from None
                raise
            finally:
                _windows_close(handle)
            return
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        current_descriptor: int | None = None
        descriptor: int | None = None
        try:
            current_descriptor = os.open(
                target.name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent,
            )
            current = os.fstat(current_descriptor)
            if (
                not _regular(current)
                or current.st_size < 0
                or current.st_size > 64 * 1024 * 1024
            ):
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                )
            old_chunks: list[bytes] = []
            old_remaining = current.st_size
            while old_remaining:
                chunk = os.read(current_descriptor, min(old_remaining, 1024 * 1024))
                if not chunk:
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_READ_INVALID"
                    )
                old_chunks.append(chunk)
                old_remaining -= len(chunk)
            old_payload = b"".join(old_chunks)
            current_after = os.fstat(current_descriptor)
            if (
                len(old_payload) != current_after.st_size
                or (
                    current.st_dev,
                    current.st_ino,
                    current.st_size,
                    current.st_mtime_ns,
                    current.st_ctime_ns,
                )
                != (
                    current_after.st_dev,
                    current_after.st_ino,
                    current_after.st_size,
                    current_after.st_mtime_ns,
                    current_after.st_ctime_ns,
                )
            ):
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_READ_INVALID"
                )
            descriptor = os.open(candidate_name, flags, 0o600, dir_fd=parent)
            metadata = os.fstat(descriptor)
            backup_created = False
            replacement_published = False

            def rollback() -> bool:
                nonlocal backup_created
                rollback_descriptor: int | None = None
                try:
                    if backup_created:
                        os.replace(
                            backup_name,
                            target.name,
                            src_dir_fd=parent,
                            dst_dir_fd=parent,
                        )
                        backup_created = False
                    else:
                        rollback_name = f".{target.name}.recovery-v2-rollback"
                        rollback_descriptor = os.open(
                            rollback_name,
                            flags,
                            0o600,
                            dir_fd=parent,
                        )
                        _write_fd(rollback_descriptor, old_payload)
                        os.close(rollback_descriptor)
                        rollback_descriptor = None
                        os.replace(
                            rollback_name,
                            target.name,
                            src_dir_fd=parent,
                            dst_dir_fd=parent,
                        )
                    _posix_unlink_if_identity(
                        candidate_name,
                        parent=parent,
                        expected=metadata,
                    )
                    os.fsync(parent)
                    restored = os.open(
                        target.name,
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent,
                    )
                    try:
                        restored_metadata = os.fstat(restored)
                        restored_payload = b""
                        while len(restored_payload) < restored_metadata.st_size:
                            chunk = os.read(
                                restored,
                                min(
                                    restored_metadata.st_size - len(restored_payload),
                                    1024 * 1024,
                                ),
                            )
                            if not chunk:
                                break
                            restored_payload += chunk
                        if not _regular(restored_metadata) or restored_payload != old_payload:
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                            )
                    finally:
                        os.close(restored)
                    return True
                except OSError:
                    return False
                finally:
                    if rollback_descriptor is not None:
                        os.close(rollback_descriptor)

            try:
                _write_fd(descriptor, payload)
                metadata = os.fstat(descriptor)
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
                os.link(
                    target.name,
                    backup_name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                    follow_symlinks=False,
                )
                backup_created = True
                backup = os.stat(backup_name, dir_fd=parent, follow_symlinks=False)
                if not _regular(backup) or (backup.st_dev, backup.st_ino) != (
                    current.st_dev,
                    current.st_ino,
                ):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                    )
                os.replace(
                    candidate_name,
                    target.name,
                    src_dir_fd=parent,
                    dst_dir_fd=parent,
                )
                replacement_published = True
                published = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
                if not _regular(published) or (published.st_dev, published.st_ino) != (
                    metadata.st_dev,
                    metadata.st_ino,
                ):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                    )
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
                os.fsync(parent)
            except OSError:
                if replacement_published:
                    if not rollback():
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                        ) from None
                else:
                    try:
                        if backup_created:
                            os.unlink(backup_name, dir_fd=parent)
                            backup_created = False
                        _posix_unlink_if_identity(
                            candidate_name,
                            parent=parent,
                            expected=metadata,
                        )
                        os.fsync(parent)
                    except OSError:
                        pass
                raise
            try:
                os.unlink(backup_name, dir_fd=parent)
                backup_created = False
            except OSError:
                pass
            try:
                os.fsync(parent)
            except OSError:
                pass
            try:
                _posix_require_attached_directory(
                    parent,
                    target.parent,
                    repository_root=repository_root,
                )
            except OSError:
                if not rollback():
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                    ) from None
                raise RecoveryV2FilesystemError(
                    "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
                ) from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if current_descriptor is not None:
                os.close(current_descriptor)


def publish_directory_noreplace(
    source: Path,
    destination: Path,
    *,
    repository_root: Path,
    expected_files: Mapping[str, str] | None = None,
) -> None:
    """Durably move one validated flat directory without replacing a winner."""

    root, source_path, source_parts = _lexical_parts(
        source,
        repository_root=repository_root,
    )
    _root, destination_path, destination_parts = _lexical_parts(
        destination,
        repository_root=repository_root,
    )
    if (
        not source_parts
        or not destination_parts
        or source_path == destination_path
        or source_path.parent == source_path
        or destination_path.parent == destination_path
    ):
        raise RecoveryV2FilesystemError("RECOVERY_V2_FILESYSTEM_PATH_INVALID")

    with _directory_capability(
        source_path.parent,
        repository_root=root,
        create=False,
        mutation=True,
    ) as source_parent:
        with _directory_capability(
            destination_path.parent,
            repository_root=root,
            create=False,
            mutation=True,
        ) as destination_parent:
            if os.name == "nt":
                source_handle = _windows_open_relative(
                    parent_handle=source_parent,
                    name=source_path.name,
                    desired_access=(
                        _FILE_LIST_DIRECTORY
                        | _FILE_READ_ATTRIBUTES
                        | _GENERIC_WRITE
                        | _DELETE
                        | _SYNCHRONIZE
                    ),
                    share_access=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
                    disposition=_FILE_OPEN,
                    attributes=_FILE_ATTRIBUTE_DIRECTORY,
                    create_options=(
                        _FILE_DIRECTORY_FILE
                        | _FILE_SYNCHRONOUS_IO_NONALERT
                        | _FILE_WRITE_THROUGH_OPTION
                        | _FILE_OPEN_REPARSE_POINT_OPTION
                    ),
                )
                renamed = False
                file_handles: list[int] = []
                try:
                    attributes = _windows_attributes(source_handle)
                    if (
                        not attributes & _FILE_ATTRIBUTE_DIRECTORY
                        or attributes & _FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                        )
                    entries = sorted(os.scandir(source_path), key=lambda entry: entry.name)
                    names = [entry.name for entry in entries]
                    snapshots: dict[str, tuple[tuple[int, int], bytes]] = {}
                    total_bytes = 0
                    for entry in entries:
                        metadata = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or not _regular(metadata):
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                            )
                        flush_handle = _windows_open_relative(
                            parent_handle=source_handle,
                            name=entry.name,
                            desired_access=(
                                _GENERIC_WRITE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE
                            ),
                            share_access=_FILE_SHARE_READ,
                            disposition=_FILE_OPEN,
                            attributes=_FILE_ATTRIBUTE_NORMAL,
                            create_options=(
                                _FILE_NON_DIRECTORY_FILE
                                | _FILE_SYNCHRONOUS_IO_NONALERT
                                | _FILE_WRITE_THROUGH_OPTION
                                | _FILE_OPEN_REPARSE_POINT_OPTION
                            ),
                        )
                        try:
                            _windows_require_regular_handle(flush_handle)
                            _windows_flush_handle(flush_handle)
                        finally:
                            _windows_close(flush_handle)
                        file_handle = _windows_open_read(
                            parent_handle=source_handle,
                            name=entry.name,
                            share_delete=True,
                        )
                        file_handles.append(file_handle)
                        file_payload = _windows_read(
                            file_handle,
                            maximum_bytes=64 * 1024 * 1024,
                        )
                        total_bytes += len(file_payload)
                        if total_bytes > 64 * 1024 * 1024:
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_SIZE_INVALID"
                            )
                        snapshots[entry.name] = (
                            _windows_identity(file_handle),
                            file_payload,
                        )

                    if expected_files is not None and (
                        sorted(expected_files) != names
                        or any(
                            type(expected_files[name]) is not str
                            or len(expected_files[name]) != 64
                            or hashlib.sha256(snapshots[name][1]).hexdigest()
                            != expected_files[name]
                            for name in names
                        )
                    ):
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                        )

                    def require_windows_snapshot(path: Path, *, retain: bool = False) -> None:
                        if sorted(entry.name for entry in os.scandir(path)) != names:
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                            )
                        for name in names:
                            observed_handle = _windows_open_read(
                                parent_handle=source_handle,
                                name=name,
                                share_delete=True,
                            )
                            try:
                                observed = (
                                    _windows_identity(observed_handle),
                                    _windows_read(
                                        observed_handle,
                                        maximum_bytes=64 * 1024 * 1024,
                                    ),
                                )
                                if observed != snapshots[name]:
                                    raise RecoveryV2FilesystemError(
                                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                                    )
                            finally:
                                if retain:
                                    file_handles.append(observed_handle)
                                else:
                                    _windows_close(observed_handle)

                    require_windows_snapshot(source_path)
                    _windows_flush_handle(source_handle)
                    # Windows cannot rename a non-empty directory while descendants
                    # remain open, even when they share delete. The byte/identity
                    # snapshot closes that narrow gap and is re-opened immediately at
                    # the destination before publication can succeed.
                    for file_handle in reversed(file_handles):
                        _windows_close(file_handle)
                    file_handles.clear()
                    _windows_rename_handle(
                        source_handle,
                        parent_handle=destination_parent,
                        destination_name=destination_path.name,
                        replace=False,
                    )
                    renamed = True
                    _windows_flush_handle(source_handle)
                    _windows_flush_handle(destination_parent)
                    _windows_flush_handle(source_parent)
                    destination_handle = _windows_open_directory(
                        destination_path,
                        mutation=False,
                        share_delete=True,
                    )
                    try:
                        if _windows_identity(destination_handle) != _windows_identity(
                            source_handle
                        ):
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
                            )
                    finally:
                        _windows_close(destination_handle)
                    require_windows_snapshot(destination_path, retain=True)
                except OSError:
                    if renamed:
                        # A post-rename snapshot failure can leave retained child
                        # handles open. Windows will not move the non-empty
                        # directory back until those handles are closed, even
                        # though they were opened with delete sharing.
                        for file_handle in reversed(file_handles):
                            _windows_close(file_handle)
                        file_handles.clear()
                        try:
                            _windows_rename_handle(
                                source_handle,
                                parent_handle=source_parent,
                                destination_name=source_path.name,
                                replace=False,
                            )
                            _windows_flush_handle(source_handle)
                            _windows_flush_handle(source_parent)
                            _windows_flush_handle(destination_parent)
                        except OSError:
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                            ) from None
                    raise
                finally:
                    for file_handle in reversed(file_handles):
                        _windows_close(file_handle)
                    _windows_close(source_handle)
                return

            source_descriptor = os.open(
                source_path.name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_parent,
            )
            file_descriptors: list[int] = []
            renamed = False
            try:
                source_metadata = os.fstat(source_descriptor)
                if not _directory(source_metadata):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                    )
                names = sorted(os.listdir(source_descriptor))
                snapshots: dict[
                    str,
                    tuple[int, int, int, int, int, bytes],
                ] = {}
                descriptor_by_name: dict[str, int] = {}
                total_bytes = 0
                for name in names:
                    file_descriptor = os.open(
                        name,
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=source_descriptor,
                    )
                    file_descriptors.append(file_descriptor)
                    metadata = os.fstat(file_descriptor)
                    if not _regular(metadata):
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_FILE_INVALID"
                        )
                    chunks: list[bytes] = []
                    remaining = metadata.st_size
                    while remaining:
                        chunk = os.read(file_descriptor, min(remaining, 1024 * 1024))
                        if not chunk:
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_READ_INVALID"
                            )
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    file_payload = b"".join(chunks)
                    metadata_after = os.fstat(file_descriptor)
                    if (
                        metadata.st_size > 64 * 1024 * 1024
                        or (
                            metadata.st_dev,
                            metadata.st_ino,
                            metadata.st_size,
                            metadata.st_mtime_ns,
                            metadata.st_ctime_ns,
                        )
                        != (
                            metadata_after.st_dev,
                            metadata_after.st_ino,
                            metadata_after.st_size,
                            metadata_after.st_mtime_ns,
                            metadata_after.st_ctime_ns,
                        )
                    ):
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                        )
                    total_bytes += len(file_payload)
                    if total_bytes > 64 * 1024 * 1024:
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_SIZE_INVALID"
                        )
                    os.fsync(file_descriptor)
                    snapshots[name] = (
                        metadata.st_dev,
                        metadata.st_ino,
                        metadata.st_size,
                        metadata.st_mtime_ns,
                        metadata.st_ctime_ns,
                        file_payload,
                    )
                    descriptor_by_name[name] = file_descriptor

                if expected_files is not None and (
                    sorted(expected_files) != names
                    or any(
                        type(expected_files[name]) is not str
                        or len(expected_files[name]) != 64
                        or hashlib.sha256(snapshots[name][-1]).hexdigest()
                        != expected_files[name]
                        for name in names
                    )
                ):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                    )

                def require_posix_snapshot() -> None:
                    if sorted(os.listdir(source_descriptor)) != names:
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                        )
                    for name in names:
                        descriptor = descriptor_by_name[name]
                        before = os.fstat(descriptor)
                        observed = os.stat(
                            name,
                            dir_fd=source_descriptor,
                            follow_symlinks=False,
                        )
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        chunks: list[bytes] = []
                        remaining = before.st_size
                        while remaining:
                            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                            if not chunk:
                                break
                            chunks.append(chunk)
                            remaining -= len(chunk)
                        after = os.fstat(descriptor)
                        snapshot = (
                            after.st_dev,
                            after.st_ino,
                            after.st_size,
                            after.st_mtime_ns,
                            after.st_ctime_ns,
                            b"".join(chunks),
                        )
                        if (
                            not _regular(observed)
                            or (observed.st_dev, observed.st_ino)
                            != (after.st_dev, after.st_ino)
                            or (
                                before.st_dev,
                                before.st_ino,
                                before.st_size,
                                before.st_mtime_ns,
                                before.st_ctime_ns,
                            )
                            != (
                                after.st_dev,
                                after.st_ino,
                                after.st_size,
                                after.st_mtime_ns,
                                after.st_ctime_ns,
                            )
                            or snapshot != snapshots[name]
                        ):
                            raise RecoveryV2FilesystemError(
                                "RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED"
                            )

                require_posix_snapshot()
                os.fsync(source_descriptor)
                _posix_require_attached_directory(
                    source_descriptor,
                    source_path,
                    repository_root=root,
                )
                _posix_require_attached_directory(
                    destination_parent,
                    destination_path.parent,
                    repository_root=root,
                )
                _posix_rename_noreplace(
                    source_path.name,
                    source_parent=source_parent,
                    destination_name=destination_path.name,
                    destination_parent=destination_parent,
                )
                renamed = True
                moved = os.stat(
                    destination_path.name,
                    dir_fd=destination_parent,
                    follow_symlinks=False,
                )
                if not _directory(moved) or (moved.st_dev, moved.st_ino) != (
                    source_metadata.st_dev,
                    source_metadata.st_ino,
                ):
                    raise RecoveryV2FilesystemError(
                        "RECOVERY_V2_FILESYSTEM_DIRECTORY_INVALID"
                    )
                _posix_require_attached_directory(
                    source_descriptor,
                    destination_path,
                    repository_root=root,
                )
                require_posix_snapshot()
                _posix_require_attached_directory(
                    destination_parent,
                    destination_path.parent,
                    repository_root=root,
                )
                _posix_require_attached_directory(
                    source_parent,
                    source_path.parent,
                    repository_root=root,
                )
                os.fsync(destination_parent)
                if source_parent != destination_parent:
                    os.fsync(source_parent)
                _posix_require_attached_directory(
                    source_descriptor,
                    destination_path,
                    repository_root=root,
                )
                _posix_require_attached_directory(
                    destination_parent,
                    destination_path.parent,
                    repository_root=root,
                )
                _posix_require_attached_directory(
                    source_parent,
                    source_path.parent,
                    repository_root=root,
                )
                require_posix_snapshot()
            except OSError:
                if renamed:
                    try:
                        _posix_rename_noreplace(
                            destination_path.name,
                            source_parent=destination_parent,
                            destination_name=source_path.name,
                            destination_parent=source_parent,
                        )
                        os.fsync(source_parent)
                        if source_parent != destination_parent:
                            os.fsync(destination_parent)
                    except OSError:
                        raise RecoveryV2FilesystemError(
                            "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"
                        ) from None
                raise
            finally:
                for file_descriptor in reversed(file_descriptors):
                    os.close(file_descriptor)
                os.close(source_descriptor)
