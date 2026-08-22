"""Fail-closed orchestration for one externally authorized live plan item."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import struct

# Only an owner-pinned local Git executable is allowed.
import subprocess  # nosec B404
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, Self

from pydantic import Field, model_validator

from robin.capture.contracts import (
    AdmissionStatus,
    CaptureBudget,
    CaptureContractError,
    CaptureMode,
    FixtureMapping,
    FrozenContract,
    ProviderRequestSpec,
    RawPayloadReceipt,
    RequestFingerprint,
    canonical_sha256,
    ensure_utc,
)
from robin.capture.harness import CaptureGuardError as HarnessGuardError
from robin.capture.harness import CaptureHarness, CaptureRejected
from robin.capture.live_contracts import (
    LIVE_ALLOWED_SPORT_KEYS,
    ActivationEnvelopeV1,
    LiveExecutionAttemptReceiptV1,
    LiveExecutionReceiptV1,
    LiveLeaseV1,
    LivePlanItemV1,
    LivePlanV1,
    LiveTerminalDisposition,
    OwnerAuthorizationV1,
)
from robin.capture.live_storage import (
    LiveBudgetReservation,
    LiveStateStore,
    LiveStorageError,
)
from robin.capture.live_transport import (
    LiveTransport,
    LiveTransportError,
    PublicProviderRequestV1,
    SecretReader,
    reject_unsafe_response,
    validate_provider_secret,
)
from robin.capture.normalization import CaptureValidationError
from robin.capture.storage import (
    _MAX_CONTRACT_BYTES,
    CaptureStorageError,
    CaptureStore,
    _path_exists_no_follow,
    _reject_reparse_path,
    exclusive_local_directory_fingerprint,
    validate_exclusive_local_directory_identity,
)


class LiveGuardError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RepositoryStateV1(FrozenContract):
    repository_identity: Literal["dddur75/robin-stades-ng"] = "dddur75/robin-stades-ng"
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    main_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    worktree_clean: Literal[True] = True
    repository_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    control_temp_root_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_execution_boundary: Literal["OWNER_ATTESTED_EXCLUSIVE_OS_ACL_NO_CONCURRENT_MUTATOR"] = (
        "OWNER_ATTESTED_EXCLUSIVE_OS_ACL_NO_CONCURRENT_MUTATOR"
    )

    @model_validator(mode="after")
    def validate_exact_main(self) -> Self:
        if self.head_sha != self.main_sha:
            raise ValueError("LIVE_REPOSITORY_NOT_EXACT_MAIN")
        return self


class RepositoryStateReader(Protocol):
    def read(self) -> RepositoryStateV1: ...


class OwnerAuthorizationVerifier(Protocol):
    def verify(self, authorization: OwnerAuthorizationV1) -> None: ...


class PinnedOwnerAuthorizationVerifier:
    """Bind execution to an owner-provided hash pin outside the authorization bundle."""

    def __init__(self, expected_authorization_sha256: str) -> None:
        if len(expected_authorization_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in expected_authorization_sha256
        ):
            raise LiveGuardError("LIVE_OWNER_AUTHORIZATION_PIN_INVALID")
        self.expected_authorization_sha256 = expected_authorization_sha256

    def verify(self, authorization: OwnerAuthorizationV1) -> None:
        if authorization.canonical_authorization_hash != self.expected_authorization_sha256:
            raise LiveGuardError("LIVE_OWNER_AUTHORIZATION_PIN_MISMATCH")


class GitRepositoryStateReader:
    """Read local Git state only; it performs no fetch or remote network call."""

    _ALLOWED_ORIGINS = {
        "https://github.com/dddur75/robin-stades-ng.git",
        "git@github.com:dddur75/robin-stades-ng.git",
        "ssh://git@github.com/dddur75/robin-stades-ng.git",
    }

    def __init__(
        self,
        repository_root: Path,
        *,
        git_executable: Path,
        git_executable_sha256: str,
        control_temp_root: Path,
        repository_root_fingerprint: str,
        control_temp_root_fingerprint: str,
    ) -> None:
        self.repository_root = validate_exclusive_local_directory_identity(repository_root)
        self.control_temp_root = validate_exclusive_local_directory_identity(control_temp_root)
        try:
            if os.path.commonpath((self.repository_root, self.control_temp_root)) == os.fspath(
                self.repository_root
            ):
                raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_INSIDE_REPOSITORY")
        except ValueError:
            pass
        try:
            self._repository_root_fingerprint = exclusive_local_directory_fingerprint(
                self.repository_root
            )
            self._control_temp_fingerprint = exclusive_local_directory_fingerprint(
                self.control_temp_root
            )
        except CaptureStorageError:
            raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE") from None
        if (
            self._repository_root_fingerprint != repository_root_fingerprint
            or self._control_temp_fingerprint != control_temp_root_fingerprint
        ):
            raise LiveGuardError("LIVE_GIT_OWNER_ATTESTED_ROOT_MISMATCH")
        if len(git_executable_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in git_executable_sha256
        ):
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_PIN_INVALID")
        self.git_executable_sha256 = git_executable_sha256
        self.git_executable, self._git_executable_identity = self._validated_executable(
            git_executable
        )
        digest = self._executable_sha256(self.git_executable)
        if digest != self.git_executable_sha256:
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_PIN_MISMATCH")

    def _assert_control_temp_identity(self) -> None:
        try:
            observed = exclusive_local_directory_fingerprint(self.control_temp_root)
        except CaptureStorageError:
            raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE") from None
        if observed != self._control_temp_fingerprint:
            raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_IDENTITY_CHANGED")

    def _assert_repository_root_identity(self) -> None:
        try:
            observed = exclusive_local_directory_fingerprint(self.repository_root)
        except CaptureStorageError:
            raise LiveGuardError("LIVE_REPOSITORY_ROOT_UNSAFE") from None
        if observed != self._repository_root_fingerprint:
            raise LiveGuardError("LIVE_REPOSITORY_ROOT_IDENTITY_CHANGED")

    @staticmethod
    def _validated_executable(path: Path) -> tuple[Path, tuple[int, int, int, int]]:
        absolute = Path(os.path.abspath(os.fspath(path)))
        if absolute.name.casefold() not in {"git", "git.exe"}:
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_NOT_APPROVED")
        try:
            validate_exclusive_local_directory_identity(absolute.parent)
            _reject_reparse_path(absolute)
            metadata = absolute.lstat()
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_NOT_APPROVED") from None
        if not stat.S_ISREG(metadata.st_mode):
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_NOT_APPROVED")
        return absolute, (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )

    @staticmethod
    def _executable_sha256(path: Path) -> str:
        descriptor = -1
        try:
            _reject_reparse_path(path)
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != current.st_dev
                or opened.st_ino != current.st_ino
                or opened.st_size > 67_108_864
            ):
                raise OSError
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1_048_576):
                digest.update(chunk)
            final = os.fstat(descriptor)
            if (
                final.st_dev != opened.st_dev
                or final.st_ino != opened.st_ino
                or final.st_size != opened.st_size
                or final.st_mtime_ns != opened.st_mtime_ns
            ):
                raise OSError
            return digest.hexdigest()
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_NOT_APPROVED") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _control_bytes(path: Path, *, maximum_bytes: int) -> bytes:
        descriptor = -1
        try:
            _reject_reparse_path(path)
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOINHERIT", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != current.st_dev
                or opened.st_ino != current.st_ino
                or opened.st_size > maximum_bytes
            ):
                raise OSError
            payload = bytearray()
            while chunk := os.read(descriptor, min(1_048_576, maximum_bytes + 1)):
                payload.extend(chunk)
                if len(payload) > maximum_bytes:
                    raise OSError
            final = os.fstat(descriptor)
            current = path.lstat()
            if (
                final.st_dev != opened.st_dev
                or final.st_ino != opened.st_ino
                or final.st_size != opened.st_size
                or final.st_mtime_ns != opened.st_mtime_ns
                or current.st_dev != opened.st_dev
                or current.st_ino != opened.st_ino
            ):
                raise OSError
            return bytes(payload)
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @classmethod
    def _control_text(cls, path: Path, *, maximum_bytes: int = 16_384) -> str:
        try:
            text = cls._control_bytes(path, maximum_bytes=maximum_bytes).decode("utf-8")
        except UnicodeDecodeError:
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None
        if "\x00" in text:
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
        return text

    @classmethod
    def _referenced_directory(cls, *, base: Path, reference: str) -> Path:
        if (
            not reference
            or "\r" in reference
            or "\n" in reference
            or reference.startswith(("\\\\", "//"))
            or reference.casefold().startswith(("file://", "http://", "https://", "ssh://"))
        ):
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
        candidate = Path(reference)
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            return validate_exclusive_local_directory_identity(candidate)
        except CaptureStorageError:
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None

    @classmethod
    def _validate_config(cls, path: Path, *, required: bool) -> str | None:
        if not _path_exists_no_follow(path):
            if required:
                raise LiveGuardError("LIVE_GIT_CONFIG_REQUIRED")
            return None
        text = cls._control_text(path, maximum_bytes=_MAX_CONTRACT_BYTES)
        section: tuple[str, str | None] | None = None
        seen: set[tuple[str, str | None, str]] = set()
        origin: str | None = None
        core_values = {
            "repositoryformatversion": {"0"},
            "filemode": {"true", "false"},
            "bare": {"false"},
            "logallrefupdates": {"true"},
            "symlinks": {"true", "false"},
            "ignorecase": {"true", "false"},
        }
        section_pattern = re.compile(r'^\[([A-Za-z][A-Za-z0-9.-]*)(?: "([A-Za-z0-9._/@+\-]+)")?\]$')
        key_pattern = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*=\s*(.*)$")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.endswith("\\") or "\x00" in line:
                raise LiveGuardError("LIVE_GIT_CONFIG_SYNTAX_FORBIDDEN")
            section_match = section_pattern.fullmatch(line)
            if section_match is not None:
                section = (
                    section_match.group(1).casefold(),
                    section_match.group(2),
                )
                continue
            key_match = key_pattern.fullmatch(line)
            if section is None or key_match is None:
                raise LiveGuardError("LIVE_GIT_CONFIG_SYNTAX_FORBIDDEN")
            key = key_match.group(1).casefold()
            value = key_match.group(2).strip()
            identity = (*section, key)
            if identity in seen:
                raise LiveGuardError("LIVE_GIT_CONFIG_DUPLICATE_KEY")
            seen.add(identity)
            name, subsection = section
            if name == "core" and subsection is None:
                if key not in core_values or value.casefold() not in core_values[key]:
                    raise LiveGuardError("LIVE_GIT_CONFIG_KEY_FORBIDDEN")
            elif name == "extensions" and subsection is None:
                if key != "worktreeconfig" or value.casefold() != "true":
                    raise LiveGuardError("LIVE_GIT_CONFIG_KEY_FORBIDDEN")
            elif name == "remote" and subsection == "origin":
                if key == "url" and value in cls._ALLOWED_ORIGINS:
                    origin = value
                elif key == "fetch" and value == "+refs/heads/*:refs/remotes/origin/*":
                    pass
                else:
                    raise LiveGuardError("LIVE_GIT_CONFIG_KEY_FORBIDDEN")
            elif name == "branch" and subsection is not None:
                if key == "remote" and value == "origin":
                    pass
                elif key == "merge" and re.fullmatch(r"refs/heads/[A-Za-z0-9._/+\-]+", value):
                    pass
                else:
                    raise LiveGuardError("LIVE_GIT_CONFIG_KEY_FORBIDDEN")
            elif name == "user" and subsection is None:
                if key not in {"name", "email"} or any(
                    character in value for character in ("\r", "\n", "\\")
                ):
                    raise LiveGuardError("LIVE_GIT_CONFIG_KEY_FORBIDDEN")
            else:
                raise LiveGuardError("LIVE_GIT_CONFIG_SECTION_FORBIDDEN")
        return origin

    @staticmethod
    def _validate_metadata_tree(root: Path, *, maximum_entries: int) -> None:
        if not _path_exists_no_follow(root):
            return
        try:
            validate_exclusive_local_directory_identity(root)
            entries = 0
            for current, directories, files in os.walk(root, followlinks=False):
                current_path = Path(current)
                _reject_reparse_path(current_path)
                for name in (*directories, *files):
                    entries += 1
                    if entries > maximum_entries:
                        raise LiveGuardError("LIVE_GIT_METADATA_TOO_COMPLEX")
                    candidate = current_path / name
                    _reject_reparse_path(candidate)
                    metadata = candidate.lstat()
                    if name in directories:
                        if not stat.S_ISDIR(metadata.st_mode):
                            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
                    elif not stat.S_ISREG(metadata.st_mode):
                        raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None

    def _validate_worktree_tree(self) -> None:
        entries = 0
        try:
            for current, directories, files in os.walk(
                self.repository_root,
                followlinks=False,
            ):
                current_path = Path(current)
                if current_path == self.repository_root and ".git" in directories:
                    directories.remove(".git")
                for name in (*directories, *files):
                    if current_path == self.repository_root and name == ".git":
                        continue
                    entries += 1
                    if entries > 50_000:
                        raise LiveGuardError("LIVE_REPOSITORY_TREE_TOO_COMPLEX")
                    candidate = current_path / name
                    _reject_reparse_path(candidate)
                    metadata = candidate.lstat()
                    if name in directories:
                        if not stat.S_ISDIR(metadata.st_mode):
                            raise LiveGuardError("LIVE_REPOSITORY_TREE_UNSAFE")
                    elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                        raise LiveGuardError("LIVE_REPOSITORY_TREE_UNSAFE")
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_REPOSITORY_TREE_UNSAFE") from None

    def _validate_git_metadata(self) -> tuple[str, Path, Path]:
        git_control = self.repository_root / ".git"
        try:
            metadata = git_control.lstat()
        except OSError:
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None
        if stat.S_ISDIR(metadata.st_mode):
            try:
                git_directory = validate_exclusive_local_directory_identity(git_control)
            except CaptureStorageError:
                raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE") from None
        elif stat.S_ISREG(metadata.st_mode):
            control = self._control_text(git_control, maximum_bytes=4_096)
            lines = control.splitlines()
            if len(lines) != 1 or not lines[0].startswith("gitdir: "):
                raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
            git_directory = self._referenced_directory(
                base=self.repository_root,
                reference=lines[0].removeprefix("gitdir: "),
            )
        else:
            raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")

        common_directory = git_directory
        common_reference = git_directory / "commondir"
        if _path_exists_no_follow(common_reference):
            common_text = self._control_text(common_reference, maximum_bytes=4_096)
            lines = common_text.splitlines()
            if len(lines) != 1:
                raise LiveGuardError("LIVE_GIT_METADATA_UNSAFE")
            common_directory = self._referenced_directory(
                base=git_directory,
                reference=lines[0],
            )

        if _path_exists_no_follow(self.repository_root / ".gitmodules"):
            raise LiveGuardError("LIVE_GIT_SUBMODULES_FORBIDDEN")
        origin = self._validate_config(common_directory / "config", required=True)
        for config_path in {
            git_directory / "config",
            git_directory / "config.worktree",
        } - {common_directory / "config"}:
            candidate_origin = self._validate_config(config_path, required=False)
            if candidate_origin is not None:
                if origin is not None and candidate_origin != origin:
                    raise LiveGuardError("LIVE_GIT_CONFIG_ORIGIN_AMBIGUOUS")
                origin = candidate_origin
        if origin not in self._ALLOWED_ORIGINS:
            raise LiveGuardError("LIVE_REPOSITORY_IDENTITY_MISMATCH")
        for alternate in {
            common_directory / "objects" / "info" / "alternates",
            common_directory / "objects" / "info" / "http-alternates",
            git_directory / "objects" / "info" / "alternates",
            git_directory / "objects" / "info" / "http-alternates",
        }:
            if _path_exists_no_follow(alternate):
                raise LiveGuardError("LIVE_GIT_ALTERNATES_FORBIDDEN")
        for forbidden in {
            common_directory / "info" / "grafts",
            git_directory / "info" / "grafts",
            common_directory / "refs" / "replace",
            git_directory / "refs" / "replace",
        }:
            if _path_exists_no_follow(forbidden):
                raise LiveGuardError("LIVE_GIT_REPLACE_OBJECTS_FORBIDDEN")
        for packed_refs in {
            common_directory / "packed-refs",
            git_directory / "packed-refs",
        }:
            if _path_exists_no_follow(packed_refs) and b" refs/replace/" in self._control_bytes(
                packed_refs, maximum_bytes=_MAX_CONTRACT_BYTES
            ):
                raise LiveGuardError("LIVE_GIT_REPLACE_OBJECTS_FORBIDDEN")
        for control_file, maximum_bytes in {
            git_directory / "HEAD": _MAX_CONTRACT_BYTES,
            git_directory / "index": 67_108_864,
            common_directory / "HEAD": _MAX_CONTRACT_BYTES,
            common_directory / "info" / "exclude": _MAX_CONTRACT_BYTES,
            common_directory / "info" / "attributes": _MAX_CONTRACT_BYTES,
        }.items():
            if _path_exists_no_follow(control_file):
                self._control_bytes(control_file, maximum_bytes=maximum_bytes)
        self._validate_metadata_tree(common_directory / "refs", maximum_entries=50_000)
        self._validate_metadata_tree(common_directory / "objects", maximum_entries=200_000)
        return origin, git_directory, common_directory

    @contextmanager
    def _sanitized_index(self, git_directory: Path) -> Iterator[Path]:
        try:
            payload = self._control_bytes(
                git_directory / "index",
                maximum_bytes=67_108_864,
            )
        except (CaptureStorageError, OSError):
            raise LiveGuardError("LIVE_GIT_INDEX_INVALID") from None
        if len(payload) < 32 or payload[:4] != b"DIRC":
            raise LiveGuardError("LIVE_GIT_INDEX_INVALID")
        version, count = struct.unpack(">II", payload[4:12])
        if version != 2 or count > 50_000:
            raise LiveGuardError("LIVE_GIT_INDEX_FORMAT_FORBIDDEN")
        if hashlib.sha1(payload[:-20], usedforsecurity=False).digest() != payload[-20:]:
            raise LiveGuardError("LIVE_GIT_INDEX_CHECKSUM_MISMATCH")
        sanitized = bytearray(payload[:-20])
        cursor = 12
        limit = len(payload) - 20
        paths: set[str] = set()
        entry_starts: list[int] = []
        for _entry in range(count):
            entry_start = cursor
            entry_starts.append(entry_start)
            if cursor + 62 > limit:
                raise LiveGuardError("LIVE_GIT_INDEX_INVALID")
            sanitized[cursor : cursor + 24] = b"\0" * 24
            sanitized[cursor + 28 : cursor + 40] = b"\0" * 12
            mode = int.from_bytes(payload[cursor + 24 : cursor + 28], "big")
            if mode not in {0o100644, 0o100755}:
                raise LiveGuardError("LIVE_GIT_INDEX_MODE_FORBIDDEN")
            flags = int.from_bytes(payload[cursor + 60 : cursor + 62], "big")
            if flags & 0xF000:
                raise LiveGuardError("LIVE_GIT_INDEX_FLAGS_FORBIDDEN")
            cursor += 62
            terminator = payload.find(b"\0", cursor, limit)
            if terminator < 0:
                raise LiveGuardError("LIVE_GIT_INDEX_INVALID")
            try:
                path_text = payload[cursor:terminator].decode("utf-8")
            except UnicodeDecodeError:
                raise LiveGuardError("LIVE_GIT_INDEX_PATH_INVALID") from None
            logical_path = PurePosixPath(path_text)
            declared_length = flags & 0x0FFF
            if (
                not path_text
                or path_text in paths
                or path_text.startswith(("/", "\\"))
                or "\\" in path_text
                or ":" in path_text
                or any(ord(character) < 32 for character in path_text)
                or any(part in {"", ".", "..", ".git"} for part in logical_path.parts)
                or (declared_length != 0x0FFF and declared_length != terminator - cursor)
            ):
                raise LiveGuardError("LIVE_GIT_INDEX_PATH_INVALID")
            paths.add(path_text)
            cursor = terminator + 1
            cursor += (8 - ((cursor - entry_start) % 8)) % 8
        body = bytes(sanitized[:cursor])
        complete = body + hashlib.sha1(body, usedforsecurity=False).digest()
        self._assert_control_temp_identity()
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".robin-live-git-index-",
            suffix=".tmp",
            dir=self.control_temp_root,
        )
        path = Path(raw_path)
        self._assert_control_temp_identity()
        created_identity = path.lstat()
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(complete)
                stream.flush()
                os.fsync(stream.fileno())
            initial = path.lstat()
            if (
                not stat.S_ISREG(initial.st_mode)
                or initial.st_nlink != 1
                or initial.st_dev != created_identity.st_dev
                or initial.st_ino != created_identity.st_ino
            ):
                raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE")
            yield path
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                self._assert_control_temp_identity()
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE")
                try:
                    refreshed = self._control_bytes(
                        path,
                        maximum_bytes=67_108_864,
                    )
                except LiveGuardError:
                    raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE") from None
                if (
                    len(refreshed) != len(complete)
                    or hashlib.sha1(  # noqa: S324 - Git index identity is SHA-1.
                        refreshed[:-20],
                        usedforsecurity=False,
                    ).digest()
                    != refreshed[-20:]
                ):
                    raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE")
                normalized = bytearray(refreshed[:-20])
                for entry_start in entry_starts:
                    normalized[entry_start : entry_start + 24] = b"\0" * 24
                    normalized[entry_start + 28 : entry_start + 40] = b"\0" * 12
                normalized_body = bytes(normalized)
                normalized_complete = (
                    normalized_body
                    + hashlib.sha1(  # noqa: S324
                        normalized_body,
                        usedforsecurity=False,
                    ).digest()
                )
                if normalized_complete != complete:
                    raise LiveGuardError("LIVE_GIT_CONTROL_TEMP_UNSAFE")
                path.unlink()
            except FileNotFoundError:
                pass

    def _git(
        self,
        *arguments: str,
        extra_environment: Mapping[str, str] | None = None,
        allowed_returncodes: frozenset[int] = frozenset({0}),
    ) -> tuple[str, int]:
        executable, identity = self._validated_executable(self.git_executable)
        if identity != self._git_executable_identity:
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_IDENTITY_CHANGED")
        digest = self._executable_sha256(executable)
        if digest != self.git_executable_sha256:
            raise LiveGuardError("LIVE_GIT_EXECUTABLE_IDENTITY_CHANGED")
        environment: dict[str, str] = {}
        for key in ("SYSTEMROOT", "WINDIR"):
            if key in os.environ:
                try:
                    validate_exclusive_local_directory_identity(Path(os.environ[key]))
                except CaptureStorageError:
                    raise LiveGuardError("LIVE_GIT_PROCESS_ENVIRONMENT_UNSAFE") from None
                environment[key] = os.environ[key]
        environment.update(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_PAGER": "cat",
                "LANG": "C",
                "LC_ALL": "C",
            }
        )
        if extra_environment is not None:
            environment.update(extra_environment)
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                [
                    executable,
                    "--no-optional-locks",
                    "--no-replace-objects",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "core.untrackedCache=false",
                    "-c",
                    "core.autocrlf=true",
                    "-c",
                    "core.safecrlf=true",
                    "-c",
                    f"core.attributesFile={os.devnull}",
                    "-c",
                    f"core.excludesFile={os.devnull}",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.file.allow=never",
                    "-C",
                    str(self.repository_root),
                    *arguments,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise LiveGuardError("LIVE_REPOSITORY_STATE_UNAVAILABLE") from None
        returncode = int(getattr(result, "returncode", 0))
        if returncode not in allowed_returncodes:
            raise LiveGuardError("LIVE_REPOSITORY_STATE_UNAVAILABLE")
        return result.stdout.strip(), returncode

    def read(self) -> RepositoryStateV1:
        self._assert_repository_root_identity()
        self._assert_control_temp_identity()
        origin, git_directory, _common_directory = self._validate_git_metadata()
        if origin not in self._ALLOWED_ORIGINS:
            raise LiveGuardError("LIVE_REPOSITORY_IDENTITY_MISMATCH")
        self._validate_worktree_tree()
        with self._sanitized_index(git_directory) as index_path:
            index_environment = {"GIT_INDEX_FILE": os.fspath(index_path)}
            head_sha, _ = self._git(
                "rev-parse",
                "--verify",
                "HEAD",
                extra_environment=index_environment,
            )
            main_sha, _ = self._git(
                "rev-parse",
                "--verify",
                "refs/remotes/origin/main",
                extra_environment=index_environment,
            )
            _output, cached_code = self._git(
                "diff-index",
                "--cached",
                "--quiet",
                "--no-ext-diff",
                "HEAD",
                "--",
                extra_environment=index_environment,
                allowed_returncodes=frozenset({0, 1}),
            )
            if cached_code != 0:
                raise LiveGuardError("LIVE_REPOSITORY_WORKTREE_NOT_CLEAN")
            _output, refresh_code = self._git(
                "update-index",
                "--really-refresh",
                "--",
                extra_environment=index_environment,
                allowed_returncodes=frozenset({0, 1}),
            )
            if refresh_code != 0:
                raise LiveGuardError("LIVE_REPOSITORY_WORKTREE_NOT_CLEAN")
            _output, worktree_code = self._git(
                "diff-files",
                "--quiet",
                "--no-ext-diff",
                "--",
                extra_environment=index_environment,
                allowed_returncodes=frozenset({0, 1}),
            )
            if worktree_code != 0:
                raise LiveGuardError("LIVE_REPOSITORY_WORKTREE_NOT_CLEAN")
            untracked, _ = self._git(
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                extra_environment=index_environment,
            )
            _output, final_worktree_code = self._git(
                "diff-files",
                "--quiet",
                "--no-ext-diff",
                "--",
                extra_environment=index_environment,
                allowed_returncodes=frozenset({0, 1}),
            )
            if final_worktree_code != 0:
                raise LiveGuardError("LIVE_REPOSITORY_WORKTREE_NOT_CLEAN")
        self._validate_worktree_tree()
        final_origin, final_git_directory, final_common_directory = self._validate_git_metadata()
        if (
            final_origin != origin
            or final_git_directory != git_directory
            or final_common_directory != _common_directory
        ):
            raise LiveGuardError("LIVE_GIT_METADATA_IDENTITY_CHANGED")
        if untracked:
            raise LiveGuardError("LIVE_REPOSITORY_WORKTREE_NOT_CLEAN")
        self._assert_repository_root_identity()
        self._assert_control_temp_identity()
        if any(
            len(value) != 40 or any(character not in "0123456789abcdef" for character in value)
            for value in (head_sha, main_sha)
        ):
            raise LiveGuardError("LIVE_REPOSITORY_STATE_UNAVAILABLE")
        return RepositoryStateV1(
            repository_identity="dddur75/robin-stades-ng",
            head_sha=head_sha,
            main_sha=main_sha,
            worktree_clean=True,
            repository_root_fingerprint=self._repository_root_fingerprint,
            control_temp_root_fingerprint=self._control_temp_fingerprint,
        )


def fixture_mappings_sha256(mappings: tuple[FixtureMapping, ...]) -> str:
    return canonical_sha256([mapping.model_dump(mode="json") for mapping in mappings])


class BoundedLiveCanaryExecutor:
    """Execute at most one fake-or-real transport dispatch for one leased item."""

    def __init__(
        self,
        *,
        capture_store: CaptureStore,
        repository_state_reader: RepositoryStateReader,
        owner_authorization_verifier: OwnerAuthorizationVerifier,
        secret_reader: SecretReader,
        transport: LiveTransport,
        clock: Callable[[], datetime],
        maximum_payload_bytes: int = 1_048_576,
        stage_observer: Callable[[str], None] | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        if maximum_payload_bytes <= 0:
            raise LiveGuardError("LIVE_PAYLOAD_LIMIT_INVALID")
        self.capture_store = capture_store
        self.live_store = LiveStateStore(
            capture_store,
            failure_injector=self._crash_point,
        )
        self.repository_state_reader = repository_state_reader
        self.owner_authorization_verifier = owner_authorization_verifier
        self.secret_reader = secret_reader
        self.transport = transport
        self.clock = clock
        self.maximum_payload_bytes = maximum_payload_bytes
        self.stage_observer = stage_observer
        self.failure_injector = failure_injector

    def _emit(self, stage: str) -> None:
        if self.stage_observer is not None:
            try:
                self.stage_observer(stage)
            except BaseException:
                # Observability can never reopen or interrupt a dispatch boundary.
                pass

    def _crash_point(self, stage: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(stage)

    def _ingestion_stage(self, stage: str) -> None:
        self._emit(stage)
        self._crash_point(stage)

    @staticmethod
    def _validate_authority(
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        *,
        now: datetime,
    ) -> None:
        if not authorization.not_before_utc <= now < authorization.expires_at_utc:
            raise LiveGuardError("LIVE_OWNER_AUTHORIZATION_NOT_ACTIVE")
        if (
            activation.authorization_id != authorization.authorization_id
            or activation.authorization_hash != authorization.canonical_authorization_hash
            or activation.repository_sha != authorization.authorized_main_sha
        ):
            raise LiveGuardError("LIVE_ACTIVATION_AUTHORIZATION_MISMATCH")
        if (
            activation.sport_key not in authorization.allowed_sport_keys
            or activation.region != authorization.allowed_region
            or activation.markets not in authorization.allowed_market_sets
        ):
            raise LiveGuardError("LIVE_ACTIVATION_SCOPE_ESCALATION")
        if (
            activation.maximum_http_calls > authorization.maximum_http_calls
            or activation.maximum_credits > authorization.maximum_credits
            or activation.not_before_utc < authorization.not_before_utc
            or activation.expires_at_utc > authorization.expires_at_utc
        ):
            raise LiveGuardError("LIVE_ACTIVATION_AUTHORITY_ESCALATION")

    @staticmethod
    def _validate_activation_ttl(
        activation: ActivationEnvelopeV1,
        *,
        now: datetime,
    ) -> None:
        if not activation.not_before_utc <= now < activation.expires_at_utc:
            raise LiveGuardError("LIVE_ACTIVATION_NOT_ACTIVE")

    @staticmethod
    def _validate_plan(
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
    ) -> None:
        if (
            plan.activation_id != activation.activation_id
            or plan.activation_hash != activation.activation_scope_sha256
            or plan.repository_sha != activation.repository_sha
            or plan.canonical_plan_hash != activation.plan_sha256
        ):
            raise LiveGuardError("LIVE_PLAN_ACTIVATION_MISMATCH")
        if (
            plan.created_at_utc < activation.not_before_utc
            or plan.expires_at_utc > activation.expires_at_utc
            or plan.maximum_http_calls != activation.maximum_http_calls
            or plan.maximum_credits != activation.maximum_credits
            or len(plan.items) > authorization.maximum_plan_items
        ):
            raise LiveGuardError("LIVE_PLAN_SCOPE_ESCALATION")
        if any(
            item.sport_key != activation.sport_key
            or item.region != activation.region
            or item.markets != activation.markets
            for item in plan.items
        ):
            raise LiveGuardError("LIVE_PLAN_ITEM_SCOPE_MISMATCH")

    @staticmethod
    def _validate_item(
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        request: ProviderRequestSpec,
        mappings: tuple[FixtureMapping, ...],
        *,
        now: datetime,
    ) -> RequestFingerprint:
        matching = tuple(candidate for candidate in plan.items if candidate.item_id == item.item_id)
        if len(matching) != 1 or matching[0] != item:
            raise LiveGuardError("LIVE_PLAN_ITEM_NOT_EXACT_MEMBER")
        if not item.not_before_utc <= now < item.expires_at_utc:
            raise LiveGuardError("LIVE_PLAN_ITEM_NOT_ACTIVE")
        if (
            item.sport_key != activation.sport_key
            or request.sport_key != item.sport_key
            or request.region != item.region
            or request.markets != item.markets
            or request.endpoint != f"/v4/sports/{item.sport_key}/odds"
        ):
            raise LiveGuardError("LIVE_PLAN_ITEM_REQUEST_SCOPE_MISMATCH")
        fingerprint = RequestFingerprint.create(request)
        if fingerprint.request_sha256 != item.provider_request_fingerprint:
            raise LiveGuardError("LIVE_PLAN_ITEM_REQUEST_FINGERPRINT_MISMATCH")
        if tuple(sorted(mappings, key=lambda value: value.provider_event_id)) != mappings:
            raise LiveGuardError("LIVE_FIXTURE_MAPPINGS_NOT_CANONICAL")
        if fixture_mappings_sha256(mappings) != item.fixture_mappings_sha256:
            raise LiveGuardError("LIVE_FIXTURE_MAPPINGS_HASH_MISMATCH")
        return fingerprint

    def _terminal_receipt(
        self,
        *,
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        lease: LiveLeaseV1,
        reservation: LiveBudgetReservation | None,
        fingerprint: RequestFingerprint,
        disposition: LiveTerminalDisposition,
        secret_reads: int,
        dispatch_started_at: datetime | None = None,
        first_observed_at: datetime | None = None,
        ingested_at: datetime | None = None,
        http_status: int | Literal["UNKNOWN"] = "UNKNOWN",
        network_calls: int = 0,
        receipt: RawPayloadReceipt | None = None,
        payload_sha256: str | None = None,
        payload_byte_length: int | None = None,
        manifest_id: str | None = None,
        manifest_hash: str | None = None,
        offline_replay_verdict: Literal[
            "ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN", "NOT_POSSIBLE", "FAILED"
        ] = "NOT_POSSIBLE",
        execution_attempt_id: str | None = None,
        response_intake_claim_sha256: str | None = None,
        terminal_at: datetime | None = None,
    ) -> LiveExecutionReceiptV1:
        self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
        result = LiveExecutionReceiptV1.issue(
            authorization_id=authorization.authorization_id,
            authorization_hash=authorization.canonical_authorization_hash,
            activation_id=activation.activation_id,
            activation_hash=activation.canonical_activation_hash,
            repository_sha=activation.repository_sha,
            plan_id=plan.plan_id,
            plan_hash=plan.canonical_plan_hash,
            item_id=item.item_id,
            item_hash=item.canonical_item_hash,
            lease_id=lease.lease_id,
            lease_hash=lease.lease_id,
            request_fingerprint_sha256=fingerprint.request_sha256,
            response_intake_claim_sha256=response_intake_claim_sha256,
            execution_attempt_id=execution_attempt_id,
            dispatch_started_at_utc=dispatch_started_at,
            first_observed_at_utc=first_observed_at,
            ingested_at_utc=ingested_at,
            terminal_at_utc=(
                ensure_utc(terminal_at, field="live_terminal_at")
                if terminal_at is not None
                else ensure_utc(self.clock(), field="live_terminal_at")
            ),
            http_status=http_status,
            network_calls=network_calls,
            provider_calls=network_calls,
            reserved_requests=1 if reservation is not None else 0,
            reserved_credits=(reservation.reserved_credits if reservation else 0),
            observed_quota=receipt.quota if receipt is not None else None,
            payload_sha256=payload_sha256,
            payload_byte_length=payload_byte_length,
            intake_receipt_id=receipt.intake_receipt_id if receipt is not None else None,
            final_receipt_id=receipt.receipt_id if receipt is not None else None,
            manifest_id=manifest_id,
            manifest_hash=manifest_hash,
            offline_replay_verdict=offline_replay_verdict,
            secret_reads_count=secret_reads,
            terminal_disposition=disposition,
        )
        self.live_store.store_terminal_receipt(result)
        self._emit("PLAN_ITEM_TERMINALIZED")
        return result

    def _recovered_terminal_is_bound(
        self,
        terminal: LiveExecutionReceiptV1,
        *,
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        permit: object,
        lease: LiveLeaseV1,
        fingerprint: RequestFingerprint,
        dispatch_started_at: datetime,
    ) -> bool:
        from robin.capture.live_contracts import LiveAdmissionPermitV1

        if not isinstance(permit, LiveAdmissionPermitV1):
            return False
        if (
            terminal.terminal_disposition is LiveTerminalDisposition.PRE_DISPATCH_REJECTED
            or terminal.authorization_id != authorization.authorization_id
            or terminal.authorization_hash != authorization.canonical_authorization_hash
            or terminal.activation_id != activation.activation_id
            or terminal.activation_hash != activation.canonical_activation_hash
            or terminal.repository_sha != activation.repository_sha
            or terminal.plan_id != plan.plan_id
            or terminal.plan_hash != plan.canonical_plan_hash
            or terminal.item_id != item.item_id
            or terminal.item_hash != item.canonical_item_hash
            or terminal.lease_id != lease.lease_id
            or terminal.lease_hash != lease.lease_id
            or terminal.request_fingerprint_sha256 != fingerprint.request_sha256
            or terminal.dispatch_started_at_utc != dispatch_started_at
            or terminal.network_calls != 1
            or terminal.provider_calls != 1
            or terminal.secret_reads_count != 1
            or terminal.reserved_requests != 1
            or terminal.reserved_credits != permit.reserved_credits
            or terminal.terminal_at_utc < dispatch_started_at
        ):
            return False
        if terminal.execution_attempt_id is None:
            return terminal.terminal_disposition is LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN
        try:
            attempt = self.live_store.load_execution_attempt(
                terminal.execution_attempt_id,
                manifest_id=terminal.manifest_id,
            )
            if (
                attempt.authorization_hash != permit.authorization_hash
                or attempt.activation_hash != permit.activation_hash
                or attempt.plan_hash != permit.plan_hash
                or attempt.item_hash != permit.item_hash
                or attempt.lease_id != permit.lease_id
                or attempt.request_fingerprint_sha256 != permit.request_fingerprint_sha256
                or attempt.dispatch_started_at_utc != dispatch_started_at
                or terminal.first_observed_at_utc != attempt.first_observed_at_utc
                or terminal.ingested_at_utc != attempt.ingested_at_utc
                or terminal.http_status != attempt.http_status
                or terminal.payload_sha256 != attempt.payload_sha256
                or terminal.payload_byte_length != attempt.payload_byte_length
                or terminal.final_receipt_id != attempt.capture_receipt_id
                or terminal.manifest_id != attempt.manifest_id
                or terminal.manifest_hash != attempt.manifest_hash
                or terminal.response_intake_claim_sha256 != attempt.response_intake_claim_sha256
            ):
                return False
            if terminal.final_receipt_id is not None:
                capture_receipt = self.capture_store.load_receipt(terminal.final_receipt_id)
                if (
                    terminal.intake_receipt_id != capture_receipt.intake_receipt_id
                    or terminal.observed_quota != capture_receipt.quota
                    or terminal.http_status != capture_receipt.http_status
                    or terminal.first_observed_at_utc != capture_receipt.robin_first_observed_at
                    or terminal.ingested_at_utc != capture_receipt.robin_ingested_at
                    or terminal.payload_sha256 != capture_receipt.payload_sha256
                    or terminal.payload_byte_length != capture_receipt.payload_byte_length
                    or terminal.request_fingerprint_sha256
                    != capture_receipt.request_fingerprint_sha256
                ):
                    return False
                if capture_receipt.admission_status is AdmissionStatus.QUARANTINED:
                    if capture_receipt.rejection_code in {
                        "CAPTURE_REDIRECT_FORBIDDEN",
                        "CAPTURE_HTTP_STATUS_REJECTED",
                    }:
                        expected_disposition = LiveTerminalDisposition.HTTP_REJECTED
                    elif capture_receipt.rejection_code in {
                        "CAPTURE_QUOTA_HEADERS_INVALID",
                        "CAPTURE_QUOTA_HEADERS_MISSING",
                        "CAPTURE_QUOTA_RECONCILIATION_FAILED",
                    }:
                        expected_disposition = LiveTerminalDisposition.QUOTA_RECONCILIATION_FAILED
                    else:
                        expected_disposition = LiveTerminalDisposition.PAYLOAD_REJECTED
                    if terminal.terminal_disposition is not expected_disposition:
                        return False
                elif terminal.terminal_disposition not in {
                    LiveTerminalDisposition.SUCCESS,
                    LiveTerminalDisposition.QUOTA_RECONCILIATION_FAILED,
                    LiveTerminalDisposition.OFFLINE_REPLAY_FAILED,
                }:
                    return False
            elif (
                terminal.intake_receipt_id is not None
                or terminal.observed_quota is not None
                or terminal.terminal_disposition is not LiveTerminalDisposition.PAYLOAD_REJECTED
            ):
                return False
            if terminal.manifest_id is not None:
                manifest = self.capture_store.load_manifest(terminal.manifest_id)
                if (
                    terminal.terminal_disposition
                    not in {
                        LiveTerminalDisposition.SUCCESS,
                        LiveTerminalDisposition.QUOTA_RECONCILIATION_FAILED,
                        LiveTerminalDisposition.OFFLINE_REPLAY_FAILED,
                    }
                    or terminal.manifest_hash != manifest.manifest_sha256
                    or terminal.final_receipt_id != manifest.receipt_id
                    or terminal.request_fingerprint_sha256 != manifest.request_fingerprint_sha256
                    or terminal.payload_sha256 != manifest.raw_payload_sha256
                ):
                    return False
                try:
                    replay = self.capture_store._replay_preterminal_live(
                        terminal.manifest_id,
                    )
                except (
                    CaptureContractError,
                    CaptureStorageError,
                    CaptureValidationError,
                    LiveStorageError,
                ):
                    if (
                        terminal.terminal_disposition
                        is LiveTerminalDisposition.OFFLINE_REPLAY_FAILED
                        and terminal.offline_replay_verdict == "FAILED"
                    ):
                        replay = None
                    else:
                        return False
                if terminal.terminal_disposition is LiveTerminalDisposition.OFFLINE_REPLAY_FAILED:
                    if replay is not None or terminal.offline_replay_verdict != "FAILED":
                        return False
                elif (
                    replay is None
                    or replay.verdict != "ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN"
                    or terminal.offline_replay_verdict != "ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN"
                ):
                    return False
            elif terminal.terminal_disposition in {
                LiveTerminalDisposition.SUCCESS,
                LiveTerminalDisposition.OFFLINE_REPLAY_FAILED,
            }:
                return False
        except (
            CaptureContractError,
            CaptureStorageError,
            LiveStorageError,
            OSError,
            TypeError,
            ValueError,
        ):
            return False
        return True

    def _recover_started_dispatch(
        self,
        *,
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        request: ProviderRequestSpec,
        mappings: tuple[FixtureMapping, ...],
    ) -> LiveExecutionReceiptV1 | None:
        try:
            recovery = self.live_store.load_dispatch_started(item.canonical_item_hash)
        except CaptureStorageError:
            return None
        if recovery is None or self.live_store.terminal_marker_exists(item.canonical_item_hash):
            return None
        self.owner_authorization_verifier.verify(authorization)
        self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
        fingerprint = RequestFingerprint.create(request)
        permit = recovery.admission_permit
        if (
            permit.authorization_id != authorization.authorization_id
            or permit.authorization_hash != authorization.canonical_authorization_hash
            or permit.activation_id != activation.activation_id
            or permit.activation_hash != activation.canonical_activation_hash
            or permit.repository_sha != activation.repository_sha
            or permit.plan_id != plan.plan_id
            or permit.plan_hash != plan.canonical_plan_hash
            or permit.item_id != item.item_id
            or permit.item_hash != item.canonical_item_hash
            or permit.request_fingerprint_sha256 != fingerprint.request_sha256
            or item.provider_request_fingerprint != fingerprint.request_sha256
            or fixture_mappings_sha256(mappings) != item.fixture_mappings_sha256
            or tuple(candidate for candidate in plan.items if candidate == item) != (item,)
        ):
            raise LiveStorageError("LIVE_DISPATCH_RECOVERY_SCOPE_MISMATCH")
        try:
            existing_terminal = self.live_store.load_unterminalized_receipt(
                item.canonical_item_hash
            )
        except LiveStorageError:
            existing_terminal = None
        if existing_terminal is not None and self._recovered_terminal_is_bound(
            existing_terminal,
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=item,
            permit=permit,
            lease=recovery.lease,
            fingerprint=fingerprint,
            dispatch_started_at=recovery.dispatch_started_at_utc,
        ):
            self.live_store.store_terminal_receipt(existing_terminal)
            self._emit("DISPATCH_TERMINAL_RECEIPT_RECOVERED")
            return existing_terminal
        recovered_reservation = LiveBudgetReservation(
            entry_sha256=permit.budget_dispatch_entry_sha256,
            reserved_requests=1,
            reserved_credits=permit.reserved_credits,
            maximum_requests=plan.maximum_http_calls,
            maximum_credits=plan.maximum_credits,
        )
        self._emit("DISPATCH_OUTCOME_UNKNOWN_RECOVERY_STARTED")
        recovered_at = ensure_utc(self.clock(), field="live_dispatch_recovered_at")
        return self._terminal_receipt(
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=item,
            lease=recovery.lease,
            reservation=recovered_reservation,
            fingerprint=fingerprint,
            disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
            secret_reads=1,
            dispatch_started_at=recovery.dispatch_started_at_utc,
            network_calls=1,
            terminal_at=max(recovered_at, recovery.dispatch_started_at_utc),
        )

    def execute(
        self,
        *,
        mode: CaptureMode | str,
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        request: ProviderRequestSpec,
        mappings: tuple[FixtureMapping, ...],
    ) -> LiveExecutionReceiptV1:
        try:
            lock_mode = CaptureMode(mode)
        except ValueError:
            raise LiveGuardError("LIVE_MODE_INVALID") from None
        if lock_mode is not CaptureMode.LIVE_CANARY:
            raise LiveGuardError("LIVE_MODE_EXPLICIT_REQUIRED")
        try:
            lock_item = LivePlanItemV1.model_validate(item.model_dump(mode="json"))
            lock_authorization = OwnerAuthorizationV1.model_validate(
                authorization.model_dump(mode="json")
            )
            lock_activation = ActivationEnvelopeV1.model_validate(
                activation.model_dump(mode="json")
            )
            lock_plan = LivePlanV1.model_validate(plan.model_dump(mode="json"))
            lock_request = ProviderRequestSpec.model_validate(request.model_dump(mode="json"))
            lock_mappings = tuple(
                FixtureMapping.model_validate(mapping.model_dump(mode="json"))
                for mapping in mappings
            )
        except (AttributeError, CaptureContractError, TypeError, ValueError):
            raise LiveGuardError("LIVE_INPUT_CONTRACT_INVALID") from None
        # The execution lock itself is a durable write under the capture root.  Bind the
        # root identity before creating/opening that lock, then repeat the check at the
        # ordered pre-dispatch gate below.
        self.live_store.assert_capture_root(lock_authorization.approved_capture_root_fingerprint)
        with self.live_store.item_execution_lock(lock_item.canonical_item_hash):
            return self._execute_once_locked(
                mode=lock_mode,
                authorization=lock_authorization,
                activation=lock_activation,
                plan=lock_plan,
                item=lock_item,
                request=lock_request,
                mappings=lock_mappings,
            )

    def _execute_once_locked(
        self,
        *,
        mode: CaptureMode | str,
        authorization: OwnerAuthorizationV1,
        activation: ActivationEnvelopeV1,
        plan: LivePlanV1,
        item: LivePlanItemV1,
        request: ProviderRequestSpec,
        mappings: tuple[FixtureMapping, ...],
    ) -> LiveExecutionReceiptV1:
        try:
            authorization = OwnerAuthorizationV1.model_validate(
                authorization.model_dump(mode="json")
            )
            activation = ActivationEnvelopeV1.model_validate(activation.model_dump(mode="json"))
            plan = LivePlanV1.model_validate(plan.model_dump(mode="json"))
            item = LivePlanItemV1.model_validate(item.model_dump(mode="json"))
            request = ProviderRequestSpec.model_validate(request.model_dump(mode="json"))
            mappings = tuple(
                FixtureMapping.model_validate(mapping.model_dump(mode="json"))
                for mapping in mappings
            )
        except (AttributeError, CaptureContractError, TypeError, ValueError):
            raise LiveGuardError("LIVE_INPUT_CONTRACT_INVALID") from None
        try:
            validated_mode = CaptureMode(mode)
        except ValueError:
            raise LiveGuardError("LIVE_MODE_INVALID") from None
        self._emit("01_MODE_VALIDATED")
        if validated_mode is not CaptureMode.LIVE_CANARY:
            raise LiveGuardError("LIVE_MODE_EXPLICIT_REQUIRED")

        recovered = self._recover_started_dispatch(
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=item,
            request=request,
            mappings=mappings,
        )
        if recovered is not None:
            return recovered
        self.live_store.assert_item_not_previously_claimed(item.canonical_item_hash)

        repository = self.repository_state_reader.read()
        if (
            repository.repository_identity != authorization.repository_identity
            or repository.head_sha != authorization.authorized_main_sha
            or repository.main_sha != authorization.authorized_main_sha
            or repository.repository_root_fingerprint
            != authorization.approved_repository_root_fingerprint
            or repository.control_temp_root_fingerprint
            != authorization.approved_control_temp_root_fingerprint
            or repository.local_execution_boundary != authorization.local_execution_boundary
            or activation.repository_sha != authorization.authorized_main_sha
        ):
            raise LiveGuardError("LIVE_REPOSITORY_SHA_MISMATCH")
        self._emit("02_REPOSITORY_EXACT_SHA_VERIFIED")

        now = ensure_utc(self.clock(), field="live_validation_at")
        self.owner_authorization_verifier.verify(authorization)
        self._validate_authority(authorization, activation, now=now)
        self._emit("03_OWNER_AUTHORIZATION_VALIDATED")
        self._emit("04_ACTIVATION_VALIDATED")
        self._validate_activation_ttl(activation, now=now)
        self._emit("05_ACTIVATION_TTL_VALIDATED")
        if activation.sport_key not in LIVE_ALLOWED_SPORT_KEYS:
            raise LiveGuardError("LIVE_SPORT_FORBIDDEN")
        self._emit("06_EXACT_SCOPE_VALIDATED")
        self._validate_plan(authorization, activation, plan)
        self._emit("07_PLAN_HASH_VALIDATED")
        fingerprint = self._validate_item(
            activation,
            plan,
            item,
            request,
            mappings,
            now=now,
        )
        self._emit("08_PLAN_ITEM_VALIDATED")

        # Safety prerequisite: validate before writing; step 11 revalidates identity.
        self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
        lease = self.live_store.acquire_lease(
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=item,
            acquired_at=ensure_utc(self.clock(), field="live_lease_at"),
        )
        self._emit("09_ONE_SHOT_LEASE_ACQUIRED")
        self._crash_point("AFTER_LEASE")

        reservation: LiveBudgetReservation | None = None
        try:
            reservation = self.live_store.reserve_budget(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                reserved_at=ensure_utc(self.clock(), field="live_budget_reserved_at"),
            )
        except (LiveStorageError, CaptureStorageError):
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=None,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.PRE_DISPATCH_REJECTED,
                secret_reads=0,
            )
        self._emit("10_PERSISTENT_BUDGET_RESERVED")
        self._crash_point("AFTER_BUDGET_RESERVE")

        try:
            self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
        except (CaptureStorageError, LiveStorageError):
            # The approved root is no longer a safe place for a terminal receipt.
            raise LiveStorageError("LIVE_CAPTURE_ROOT_FINGERPRINT_MISMATCH") from None
        self._emit("11_CAPTURE_ROOT_REVALIDATED")
        try:
            public_request = PublicProviderRequestV1.from_spec(
                request,
                maximum_response_bytes=self.maximum_payload_bytes,
                approved_provider_ip_address=authorization.approved_provider_ip_address,
            )
            public_material = public_request.canonical_public_bytes()
            if not public_material or request.model_dump_json().find("apiKey") >= 0:
                raise LiveGuardError("LIVE_PUBLIC_REQUEST_MATERIAL_INVALID")
            self.transport.preflight(public_request)
            self._emit("12_PUBLIC_REQUEST_FINALIZED")
            armed_at = ensure_utc(self.clock(), field="live_dispatch_armed_at")
            admission_permit = self.live_store.arm_dispatch(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                request_fingerprint_sha256=fingerprint.request_sha256,
                armed_at=armed_at,
            )
        except (
            CaptureContractError,
            CaptureStorageError,
            LiveGuardError,
            LiveStorageError,
            LiveTransportError,
            OSError,
        ):
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.PRE_DISPATCH_REJECTED,
                secret_reads=0,
            )
        self._crash_point("AFTER_DISPATCH_ARMED")

        try:
            repository = self.repository_state_reader.read()
            if (
                repository.repository_identity != authorization.repository_identity
                or repository.head_sha != authorization.authorized_main_sha
                or repository.main_sha != authorization.authorized_main_sha
                or repository.repository_root_fingerprint
                != authorization.approved_repository_root_fingerprint
                or repository.control_temp_root_fingerprint
                != authorization.approved_control_temp_root_fingerprint
                or repository.local_execution_boundary != authorization.local_execution_boundary
            ):
                raise LiveGuardError("LIVE_REPOSITORY_SHA_MISMATCH")
            pre_secret_now = ensure_utc(self.clock(), field="live_pre_secret_validation_at")
            self._validate_authority(authorization, activation, now=pre_secret_now)
            self._validate_activation_ttl(activation, now=pre_secret_now)
            self._validate_plan(authorization, activation, plan)
            self._validate_item(
                activation,
                plan,
                item,
                request,
                mappings,
                now=pre_secret_now,
            )
            self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
            admission_permit = self.live_store.verify_admission_permit(
                admission_permit,
                consume=True,
            )
        except (CaptureContractError, CaptureStorageError, LiveGuardError, LiveStorageError):
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.PRE_DISPATCH_REJECTED,
                secret_reads=0,
            )
        self._emit("12B_PRE_SECRET_STATE_REVALIDATED")
        self._emit("12C_ADMISSION_PERMIT_CONSUMED")
        self._crash_point("AFTER_ADMISSION_CONSUMED")

        secret_reads = 1
        api_key = ""
        try:
            try:
                api_key = validate_provider_secret(self.secret_reader.read())
            except Exception:
                return self._terminal_receipt(
                    authorization=authorization,
                    activation=activation,
                    plan=plan,
                    item=item,
                    lease=lease,
                    reservation=reservation,
                    fingerprint=fingerprint,
                    disposition=LiveTerminalDisposition.PRE_DISPATCH_REJECTED,
                    secret_reads=secret_reads,
                )
            self._emit("13_PROVIDER_SECRET_READ_ONCE")
            try:
                repository = self.repository_state_reader.read()
                if (
                    repository.repository_identity != authorization.repository_identity
                    or repository.head_sha != authorization.authorized_main_sha
                    or repository.main_sha != authorization.authorized_main_sha
                    or repository.repository_root_fingerprint
                    != authorization.approved_repository_root_fingerprint
                    or repository.control_temp_root_fingerprint
                    != authorization.approved_control_temp_root_fingerprint
                    or repository.local_execution_boundary != authorization.local_execution_boundary
                ):
                    raise LiveGuardError("LIVE_REPOSITORY_SHA_MISMATCH")
                after_secret_now = ensure_utc(
                    self.clock(),
                    field="live_post_secret_validation_at",
                )
                self._validate_authority(
                    authorization,
                    activation,
                    now=after_secret_now,
                )
                self._validate_activation_ttl(activation, now=after_secret_now)
                self._validate_plan(authorization, activation, plan)
                self._validate_item(
                    activation,
                    plan,
                    item,
                    request,
                    mappings,
                    now=after_secret_now,
                )
                self.live_store.assert_capture_root(authorization.approved_capture_root_fingerprint)
                self.live_store.verify_admission_permit(
                    admission_permit,
                    consume=False,
                )
                dispatch_started = ensure_utc(
                    self.clock(),
                    field="live_dispatch_started_at",
                )
                self._validate_authority(
                    authorization,
                    activation,
                    now=dispatch_started,
                )
                self._validate_activation_ttl(activation, now=dispatch_started)
                self._validate_item(
                    activation,
                    plan,
                    item,
                    request,
                    mappings,
                    now=dispatch_started,
                )
                self.live_store.mark_dispatch_started(
                    admission_permit,
                    dispatch_started_at=dispatch_started,
                )
            except Exception:
                return self._terminal_receipt(
                    authorization=authorization,
                    activation=activation,
                    plan=plan,
                    item=item,
                    lease=lease,
                    reservation=reservation,
                    fingerprint=fingerprint,
                    disposition=LiveTerminalDisposition.PRE_DISPATCH_REJECTED,
                    secret_reads=secret_reads,
                )
            self._emit("14_DISPATCH_STARTED")
            self._crash_point("AFTER_DISPATCH_STARTED")
            try:
                response = self.transport.dispatch(public_request, api_key=api_key)
                if isinstance(response.payload, bytes) and isinstance(response.headers, Mapping):
                    reject_unsafe_response(response.payload, response.headers, api_key)
            except Exception:
                return self._terminal_receipt(
                    authorization=authorization,
                    activation=activation,
                    plan=plan,
                    item=item,
                    lease=lease,
                    reservation=reservation,
                    fingerprint=fingerprint,
                    disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
                    secret_reads=secret_reads,
                    dispatch_started_at=dispatch_started,
                    network_calls=1,
                )
        finally:
            api_key = ""
        self._emit("15_HTTPS_GET_ONCE")
        if (
            isinstance(response.http_status, bool)
            or not isinstance(response.http_status, int)
            or not 100 <= response.http_status <= 599
            or not isinstance(response.headers, Mapping)
            or not isinstance(response.payload, bytes)
            or response.network_calls != 1
            or response.provider_calls != 1
            or response.retries != 0
            or response.redirects != 0
        ):
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
                secret_reads=secret_reads,
                dispatch_started_at=dispatch_started,
                network_calls=1,
            )
        try:
            first_observed = ensure_utc(
                response.first_observed_at_utc,
                field="live_first_observed_at",
            )
        except (AttributeError, TypeError, ValueError):
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
                secret_reads=secret_reads,
                dispatch_started_at=dispatch_started,
                network_calls=1,
            )
        self._emit("16_FIRST_OBSERVATION_TIMESTAMPED")
        ingested = ensure_utc(self.clock(), field="live_ingested_at")
        if first_observed < dispatch_started or ingested < first_observed:
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
                secret_reads=secret_reads,
                dispatch_started_at=dispatch_started,
                network_calls=1,
            )
        self._emit("17_RAW_RESPONSE_OBTAINED")
        self._crash_point("AFTER_RESPONSE")

        harness = CaptureHarness(
            self.capture_store,
            CaptureBudget(
                maximum_requests=activation.maximum_http_calls,
                maximum_credits=activation.maximum_credits,
            ),
            maximum_payload_bytes=self.maximum_payload_bytes,
        )
        manifest = None
        final_receipt: RawPayloadReceipt | None = None
        rejection: CaptureRejected | None = None
        ingestion_failed = False
        try:
            manifest = harness.record_live_response(
                request,
                expected_request_fingerprint_sha256=fingerprint.request_sha256,
                payload=response.payload,
                http_status=response.http_status,
                response_headers=response.headers,
                mappings=mappings,
                admission_permit=admission_permit,
                first_observed_at=first_observed,
                ingested_at=ingested,
                stage_observer=self._ingestion_stage,
            )
            final_receipt = self.capture_store.load_receipt(manifest.receipt_id)
        except CaptureRejected as error:
            rejection = error
            try:
                final_receipt = self.capture_store.load_receipt(error.receipt_id)
            except CaptureStorageError:
                final_receipt = None
        except (
            CaptureContractError,
            HarnessGuardError,
            CaptureStorageError,
            CaptureValidationError,
        ):
            ingestion_failed = True

        disposition = (
            LiveTerminalDisposition.PAYLOAD_REJECTED
            if ingestion_failed
            else LiveTerminalDisposition.SUCCESS
        )
        if rejection is not None:
            if rejection.code in {
                "CAPTURE_REDIRECT_FORBIDDEN",
                "CAPTURE_HTTP_STATUS_REJECTED",
            }:
                disposition = LiveTerminalDisposition.HTTP_REJECTED
            elif rejection.code in {
                "CAPTURE_QUOTA_HEADERS_INVALID",
                "CAPTURE_QUOTA_HEADERS_MISSING",
                "CAPTURE_QUOTA_RECONCILIATION_FAILED",
            }:
                disposition = LiveTerminalDisposition.QUOTA_RECONCILIATION_FAILED
            else:
                disposition = LiveTerminalDisposition.PAYLOAD_REJECTED

        try:
            response_intake_claim = self.live_store.load_response_intake_claim(
                item.canonical_item_hash
            )
        except LiveStorageError:
            return self._terminal_receipt(
                authorization=authorization,
                activation=activation,
                plan=plan,
                item=item,
                lease=lease,
                reservation=reservation,
                fingerprint=fingerprint,
                disposition=LiveTerminalDisposition.DISPATCH_OUTCOME_UNKNOWN,
                secret_reads=secret_reads,
                dispatch_started_at=dispatch_started,
                network_calls=1,
            )

        if final_receipt is not None and final_receipt.quota is not None:
            try:
                self.live_store.reconcile_budget(
                    authorization=authorization,
                    activation=activation,
                    plan=plan,
                    item=item,
                    quota=final_receipt.quota,
                    reconciled_at=ensure_utc(self.clock(), field="live_budget_reconciled_at"),
                )
                self._emit("26_QUOTA_BUDGET_RECONCILED")
            except LiveStorageError:
                disposition = LiveTerminalDisposition.QUOTA_RECONCILIATION_FAILED

        payload_sha256 = (
            final_receipt.payload_sha256
            if final_receipt is not None
            else rejection.payload_sha256
            if rejection is not None
            else hashlib.sha256(response.payload).hexdigest()
        )
        attempt = LiveExecutionAttemptReceiptV1.issue(
            authorization_hash=authorization.canonical_authorization_hash,
            activation_hash=activation.canonical_activation_hash,
            plan_hash=plan.canonical_plan_hash,
            item_hash=item.canonical_item_hash,
            lease_id=lease.lease_id,
            request_fingerprint_sha256=fingerprint.request_sha256,
            response_intake_claim_sha256=(response_intake_claim.canonical_intake_claim_sha256),
            dispatch_started_at_utc=dispatch_started,
            first_observed_at_utc=first_observed,
            ingested_at_utc=ingested,
            prepared_at_utc=ensure_utc(self.clock(), field="live_attempt_prepared_at"),
            http_status=response.http_status,
            payload_sha256=payload_sha256,
            payload_byte_length=len(response.payload),
            capture_receipt_id=(final_receipt.receipt_id if final_receipt is not None else None),
            manifest_id=manifest.snapshot_id if manifest is not None else None,
            manifest_hash=manifest.manifest_sha256 if manifest is not None else None,
        )
        self.live_store.store_execution_attempt(attempt)
        self._emit("27_LIVE_EXECUTION_ATTEMPT_RECEIPT_DURABLE")
        replay_verdict: Literal["ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN", "NOT_POSSIBLE", "FAILED"] = (
            "NOT_POSSIBLE"
        )
        if manifest is not None:
            try:
                replay = self.capture_store._replay_preterminal_live(
                    manifest.snapshot_id,
                )
                replay_verdict = replay.verdict
                self._emit("28_OFFLINE_REPLAY_PROVEN")
                self._crash_point("AFTER_OFFLINE_REPLAY_BEFORE_TERMINAL")
            except (
                CaptureContractError,
                CaptureStorageError,
                CaptureValidationError,
                LiveStorageError,
                OSError,
            ):
                replay_verdict = "FAILED"
                disposition = LiveTerminalDisposition.OFFLINE_REPLAY_FAILED

        return self._terminal_receipt(
            authorization=authorization,
            activation=activation,
            plan=plan,
            item=item,
            lease=lease,
            reservation=reservation,
            fingerprint=fingerprint,
            disposition=disposition,
            secret_reads=secret_reads,
            dispatch_started_at=dispatch_started,
            first_observed_at=first_observed,
            ingested_at=ingested,
            http_status=response.http_status,
            network_calls=1,
            receipt=final_receipt,
            payload_sha256=payload_sha256,
            payload_byte_length=len(response.payload),
            manifest_id=manifest.snapshot_id if manifest is not None else None,
            manifest_hash=manifest.manifest_sha256 if manifest is not None else None,
            offline_replay_verdict=replay_verdict,
            execution_attempt_id=attempt.execution_attempt_id,
            response_intake_claim_sha256=(response_intake_claim.canonical_intake_claim_sha256),
        )
