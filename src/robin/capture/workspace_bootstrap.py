"""Fail-closed preparation of a standalone Windows real-capture workspace."""

from __future__ import annotations

import hashlib
import inspect
import os
import stat
import subprocess  # nosec B404
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from robin.capture.bootstrap_contracts import (
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
)
from robin.capture.contracts import canonical_json_bytes, ensure_utc, strict_json_object
from robin.capture.storage import (
    CaptureStorageError,
    _path_exists_no_follow,
    _reject_reparse_path,
    _safe_read_bounded,
    capture_root_fingerprint,
    exclusive_local_directory_fingerprint,
)

EXPECTED_ORIGIN = "https://github.com/dddur75/robin-stades-ng.git"
TRACKED_REAL_EXECUTION_MISSION_MANIFEST = Path(
    "configs/execution/real-execution-bootstrap-closure-v1.json"
)
BootstrapMode = Literal["CREATE", "VERIFY", "INSPECT"]

_MAXIMUM_MISSION_MANIFEST_BYTES = 1_048_576

_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_FORBIDDEN_CLOUD_ATTRIBUTES = (
    _FILE_ATTRIBUTE_REPARSE_POINT
    | _FILE_ATTRIBUTE_OFFLINE
    | _FILE_ATTRIBUTE_RECALL_ON_OPEN
    | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


class WorkspaceBootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LocalBoundaryInspection:
    canonical_path: Path
    filesystem_name: str
    volume_identity: str
    device: int
    inode: int
    attributes: int
    security_descriptor_sha256: str
    fixed_local_filesystem: bool
    acl_exclusive: bool
    synchronized: bool


class BoundaryInspector(Protocol):
    def inspect(self, path: Path) -> LocalBoundaryInspection: ...


class CommandRunner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None,
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> str: ...


class SubprocessCommandRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None,
        environment: Mapping[str, str],
        timeout_seconds: int,
    ) -> str:
        try:
            result = subprocess.run(  # noqa: S603  # nosec B603
                list(arguments),
                cwd=cwd,
                env=dict(environment),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_FAILED") from None
        if result.returncode != 0:
            raise WorkspaceBootstrapError("WORKSPACE_COMMAND_FAILED")
        return result.stdout


def _acl_security_probe_script_v1() -> str:
    """Use stable SIDs so the exclusivity proof is independent of OS language."""

    return (
        "$ErrorActionPreference='Stop';"
        "$a=Get-Acl -LiteralPath $env:ROBIN_BOOTSTRAP_INSPECT_PATH;"
        "$sidType=[System.Security.Principal.SecurityIdentifier];"
        "$ownerSid=(New-Object System.Security.Principal.NTAccount "
        "-ArgumentList $a.Owner).Translate($sidType).Value;"
        "$currentSid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        "if($ownerSid -ne $currentSid){exit 8};"
        "$allowed=@($ownerSid,'S-1-5-18','S-1-5-32-544');"
        "$bad=@($a.Access|Where-Object {"
        "$sid=$_.IdentityReference.Translate($sidType).Value;"
        "$_.AccessControlType -eq "
        "[System.Security.AccessControl.AccessControlType]::Allow -and "
        "$_.FileSystemRights.ToString() -match "
        "'Write|Modify|FullControl|Create|Delete|ChangePermissions|TakeOwnership' -and "
        "$sid -notin $allowed});"
        "if($bad.Count -ne 0){exit 7};"
        "[Console]::Out.Write($a.Sddl)"
    )


def _canonical_path(path: Path) -> Path:
    raw = os.path.abspath(os.fspath(path))
    if raw.startswith(("\\\\", "//")) or raw.casefold().startswith("\\\\?\\unc\\"):
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_UNC_FORBIDDEN")
    try:
        _reject_reparse_path(Path(raw))
        resolved = Path(raw).resolve(strict=True)
    except (CaptureStorageError, OSError):
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_PATH_IDENTITY_UNAVAILABLE") from None
    if os.fspath(resolved).startswith(("\\\\", "//")):
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_UNC_FORBIDDEN")
    return Path(os.path.normcase(os.fspath(resolved)))


def _source_repository_root_v1(source_file: Path) -> Path:
    """Find the real checkout owning a loaded source file, including linked worktrees."""

    resolved = _canonical_path(source_file)
    for candidate in (resolved.parent, *resolved.parents):
        git_entry = candidate / ".git"
        if _path_exists_no_follow(git_entry):
            return _canonical_path(candidate)
    raise WorkspaceBootstrapError("BOOTSTRAP_TOOL_SOURCE_REPOSITORY_UNRESOLVED")


def _loaded_package_repository_root_v1() -> Path:
    """Derive provenance from the module Python actually imported, not a caller claim."""

    return _source_repository_root_v1(Path(__file__))


def _calling_entrypoint_repository_root_v1() -> Path:
    """Derive the direct external caller from Python's loaded code object."""

    frame = inspect.currentframe()
    try:
        external = frame.f_back if frame else None
        module_file = _canonical_path(Path(__file__))
        while external is not None:
            try:
                external_file = _canonical_path(Path(external.f_code.co_filename))
            except WorkspaceBootstrapError:
                external = external.f_back
                continue
            if external_file != module_file:
                break
            external = external.f_back
        if external is None:
            raise WorkspaceBootstrapError("BOOTSTRAP_TOOL_ENTRYPOINT_UNRESOLVED")
        return _source_repository_root_v1(external_file)
    finally:
        del frame


def _is_within(path: Path, parent: Path) -> bool:
    candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
    boundary = os.path.normcase(os.path.abspath(os.fspath(parent)))
    try:
        return os.path.commonpath((candidate, boundary)) == boundary
    except ValueError:
        return False


def _windows_registry_enumeration_complete(error: OSError) -> bool:
    return getattr(error, "winerror", None) == 259


def _registered_windows_sync_roots() -> tuple[Path, ...]:
    if os.name != "nt":
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_WINDOWS_REQUIRED")
    candidates: set[str] = set()
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial", "Dropbox"):
        value = os.environ.get(variable)
        if value:
            candidates.add(os.path.normcase(os.path.abspath(value)))
    try:
        import winreg
    except ImportError:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_SYNC_ROOT_INSPECTION_UNAVAILABLE") from None

    registry = cast(Any, winreg)
    try:
        providers_key = registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            r"Software\SyncEngines\Providers",
        )
    except FileNotFoundError:
        return tuple(Path(value) for value in sorted(candidates))
    except OSError:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_SYNC_ROOT_INSPECTION_UNAVAILABLE") from None

    try:
        with providers_key as providers:
            provider_index = 0
            while True:
                try:
                    provider_name = registry.EnumKey(providers, provider_index)
                except OSError as error:
                    if _windows_registry_enumeration_complete(error):
                        break
                    raise
                provider_index += 1
                try:
                    provider_key = registry.OpenKey(providers, provider_name)
                except FileNotFoundError:
                    continue
                with provider_key as provider:
                    value_index = 0
                    while True:
                        try:
                            _name, value, _kind = registry.EnumValue(provider, value_index)
                        except OSError as error:
                            if _windows_registry_enumeration_complete(error):
                                break
                            raise
                        value_index += 1
                        if isinstance(value, str) and os.path.isabs(value):
                            candidates.add(os.path.normcase(os.path.abspath(value)))
    except OSError:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_SYNC_ROOT_INSPECTION_UNAVAILABLE") from None
    return tuple(Path(value) for value in sorted(candidates))


class WindowsBoundaryInspector:
    """Inspect fixed-volume, cloud, sync-root and ACL facts without mutating them."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        sync_roots: tuple[Path, ...] | None = None,
    ) -> None:
        if os.name != "nt":
            raise WorkspaceBootstrapError("LOCAL_RUNTIME_WINDOWS_REQUIRED")
        self._runner = command_runner or SubprocessCommandRunner()
        roots = _registered_windows_sync_roots() if sync_roots is None else sync_roots
        self._sync_roots = tuple(
            Path(os.path.normcase(os.path.abspath(os.fspath(value)))) for value in roots
        )

    @staticmethod
    def _volume_facts(path: Path) -> tuple[str, str, bool]:
        import ctypes
        from ctypes import wintypes

        root = Path(path.anchor)
        windows_api = cast(Any, ctypes).windll
        get_drive_type = windows_api.kernel32.GetDriveTypeW
        get_drive_type.argtypes = [wintypes.LPCWSTR]
        get_drive_type.restype = wintypes.UINT
        drive_type = int(get_drive_type(os.fspath(root)))
        volume_name = ctypes.create_unicode_buffer(261)
        filesystem_name = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        maximum_component = wintypes.DWORD()
        flags = wintypes.DWORD()
        success = windows_api.kernel32.GetVolumeInformationW(
            os.fspath(root),
            volume_name,
            len(volume_name),
            ctypes.byref(serial),
            ctypes.byref(maximum_component),
            ctypes.byref(flags),
            filesystem_name,
            len(filesystem_name),
        )
        if not success:
            raise WorkspaceBootstrapError("LOCAL_RUNTIME_VOLUME_INSPECTION_FAILED")
        filesystem = filesystem_name.value.upper()
        fixed = drive_type == 3 and filesystem in {"NTFS", "REFS"}
        volume_identity = hashlib.sha256(
            f"{path.anchor}|{serial.value}|{filesystem}".encode("utf-8")
        ).hexdigest()
        return filesystem, volume_identity, fixed

    def _security_facts(self, path: Path) -> tuple[str, bool]:
        powershell = (
            Path(
                os.environ.get(
                    "SystemRoot",
                    os.environ.get("WINDIR", r"C:\Windows"),
                )
            )
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        script = _acl_security_probe_script_v1()
        environment: dict[str, str] = {}
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        environment["ROBIN_BOOTSTRAP_INSPECT_PATH"] = os.fspath(path)
        try:
            sddl = self._runner.run(
                (
                    os.fspath(powershell),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    script,
                ),
                cwd=None,
                environment=environment,
                timeout_seconds=20,
            )
        except WorkspaceBootstrapError:
            return "0" * 64, False
        if not sddl or any(character in sddl for character in "\r\n"):
            return "0" * 64, False
        return hashlib.sha256(sddl.encode("utf-8")).hexdigest(), True

    def inspect(self, path: Path) -> LocalBoundaryInspection:
        canonical = _canonical_path(path)
        try:
            metadata = canonical.lstat()
        except OSError:
            raise WorkspaceBootstrapError("LOCAL_RUNTIME_PATH_IDENTITY_UNAVAILABLE") from None
        if not stat.S_ISDIR(metadata.st_mode):
            raise WorkspaceBootstrapError("LOCAL_RUNTIME_DIRECTORY_REQUIRED")
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if attributes & _FORBIDDEN_CLOUD_ATTRIBUTES:
            raise WorkspaceBootstrapError("LOCAL_RUNTIME_CLOUD_OR_REPARSE_FORBIDDEN")
        synchronized = any(_is_within(canonical, root) for root in self._sync_roots)
        filesystem, volume_identity, fixed = self._volume_facts(canonical)
        descriptor_hash, acl_exclusive = self._security_facts(canonical)
        return LocalBoundaryInspection(
            canonical_path=canonical,
            filesystem_name=filesystem,
            volume_identity=volume_identity,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            attributes=attributes,
            security_descriptor_sha256=descriptor_hash,
            fixed_local_filesystem=fixed,
            acl_exclusive=acl_exclusive,
            synchronized=synchronized,
        )


def _validated_git_executable(path: Path) -> tuple[Path, str]:
    try:
        canonical = _canonical_path(path.parent) / path.name
        _reject_reparse_path(canonical)
        metadata = canonical.lstat()
    except (CaptureStorageError, OSError, WorkspaceBootstrapError):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_EXECUTABLE_INVALID") from None
    if canonical.name.casefold() not in {"git", "git.exe"} or not stat.S_ISREG(metadata.st_mode):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_EXECUTABLE_INVALID")
    digest = hashlib.sha256()
    try:
        with canonical.open("rb") as stream:
            while chunk := stream.read(1_048_576):
                digest.update(chunk)
    except OSError:
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_EXECUTABLE_INVALID") from None
    return Path(os.path.normcase(os.path.abspath(os.fspath(canonical)))), digest.hexdigest()


def _git_environment(empty_template: Path) -> dict[str, str]:
    environment: dict[str, str] = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_TEMPLATE_DIR": os.fspath(empty_template),
        "LANG": "C",
        "LC_ALL": "C",
    }
    for name in ("SystemRoot", "WINDIR"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return environment


def _git_prefix(git_executable: Path) -> tuple[str, ...]:
    return (
        os.fspath(git_executable),
        "--no-optional-locks",
        "--no-replace-objects",
        "-c",
        "credential.helper=",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "http.proxy=",
        "-c",
        "https.proxy=",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "protocol.file.allow=never",
    )


def _git(
    runner: CommandRunner,
    git_executable: Path,
    environment: Mapping[str, str],
    repository: Path | None,
    *arguments: str,
    timeout_seconds: int = 120,
) -> str:
    prefix = list(_git_prefix(git_executable))
    if repository is not None:
        prefix.extend(("-C", os.fspath(repository)))
    return runner.run(
        (*prefix, *arguments),
        cwd=None,
        environment=environment,
        timeout_seconds=timeout_seconds,
    ).strip()


def _assert_safe_git_tree(
    runner: CommandRunner,
    git_executable: Path,
    environment: Mapping[str, str],
    repository: Path,
    expected_main_sha: str,
) -> None:
    git_directory = repository / ".git"
    try:
        metadata = git_directory.lstat()
    except OSError:
        raise WorkspaceBootstrapError("BOOTSTRAP_STANDALONE_GIT_REQUIRED") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise WorkspaceBootstrapError("BOOTSTRAP_STANDALONE_GIT_REQUIRED")
    forbidden = (
        git_directory / "commondir",
        git_directory / "shallow",
        git_directory / "shallow.lock",
        git_directory / "worktrees",
        git_directory / "modules",
        git_directory / "objects" / "info" / "alternates",
        git_directory / "objects" / "info" / "http-alternates",
        repository / ".gitmodules",
    )
    if any(_path_exists_no_follow(value) for value in forbidden):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_FEATURE_FORBIDDEN")
    hooks = git_directory / "hooks"
    if _path_exists_no_follow(hooks) and any(hooks.iterdir()):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_HOOKS_FORBIDDEN")
    if _git(runner, git_executable, environment, repository, "rev-parse", "HEAD") != (
        expected_main_sha
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_HEAD_MISMATCH")
    if (
        _git(
            runner,
            git_executable,
            environment,
            repository,
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
        )
        != "HEAD"
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_DETACHED_HEAD_REQUIRED")
    if (
        _git(
            runner,
            git_executable,
            environment,
            repository,
            "rev-parse",
            "refs/remotes/origin/main",
        )
        != expected_main_sha
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_MAIN_MISMATCH")
    if (
        _git(
            runner,
            git_executable,
            environment,
            repository,
            "remote",
            "get-url",
            "origin",
        )
        != EXPECTED_ORIGIN
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_ORIGIN_MISMATCH")
    if _git(
        runner,
        git_executable,
        environment,
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_WORKTREE_DIRTY")
    index_flags = _git(
        runner,
        git_executable,
        environment,
        repository,
        "ls-files",
        "-v",
    )
    if any(line and line[0] != "H" for line in index_flags.splitlines()):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_INDEX_FLAGS_FORBIDDEN")
    _git(
        runner,
        git_executable,
        environment,
        repository,
        "fsck",
        "--full",
        "--strict",
        timeout_seconds=300,
    )


def _create_exact_clone(
    *,
    runner: CommandRunner,
    git_executable: Path,
    environment: Mapping[str, str],
    runtime_parent: Path,
    repository: Path,
    expected_main_sha: str,
) -> None:
    staging = runtime_parent / ".repository-staging"
    if _path_exists_no_follow(staging) or _path_exists_no_follow(repository):
        raise WorkspaceBootstrapError("BOOTSTRAP_PARTIAL_STATE_PRESENT")
    _git(
        runner,
        git_executable,
        environment,
        None,
        "clone",
        "--no-checkout",
        "--no-local",
        "--origin",
        "origin",
        "--template",
        environment["GIT_TEMPLATE_DIR"],
        EXPECTED_ORIGIN,
        os.fspath(staging),
        timeout_seconds=300,
    )
    if (
        _git(
            runner,
            git_executable,
            environment,
            staging,
            "rev-parse",
            "refs/remotes/origin/main",
        )
        != expected_main_sha
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_MAIN_MISMATCH")
    tree = _git(
        runner,
        git_executable,
        environment,
        staging,
        "ls-tree",
        "-r",
        "--full-tree",
        expected_main_sha,
    )
    for line in tree.splitlines():
        metadata, _, path = line.partition("\t")
        mode = metadata.split(" ", 1)[0]
        if mode in {"120000", "160000"} or path == ".gitmodules":
            raise WorkspaceBootstrapError("BOOTSTRAP_GIT_TREE_FEATURE_FORBIDDEN")
    _git(
        runner,
        git_executable,
        environment,
        staging,
        "checkout",
        "--detach",
        expected_main_sha,
        timeout_seconds=300,
    )
    staging.rename(repository)


def _assert_roots_non_overlapping(inspections: tuple[LocalBoundaryInspection, ...]) -> None:
    for index, left in enumerate(inspections):
        for right in inspections[index + 1 :]:
            if left.volume_identity == right.volume_identity and (
                _is_within(left.canonical_path, right.canonical_path)
                or _is_within(right.canonical_path, left.canonical_path)
            ):
                raise WorkspaceBootstrapError("LOCAL_RUNTIME_ROOTS_OVERLAP")


def _inspect_approved_root(
    inspector: BoundaryInspector,
    path: Path,
) -> LocalBoundaryInspection:
    inspection = inspector.inspect(path)
    if not inspection.fixed_local_filesystem:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_FIXED_ACL_FILESYSTEM_REQUIRED")
    if inspection.synchronized:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_SYNCHRONIZED_ROOT_FORBIDDEN")
    if inspection.attributes & _FORBIDDEN_CLOUD_ATTRIBUTES:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_CLOUD_OR_REPARSE_FORBIDDEN")
    if not inspection.acl_exclusive:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_ACL_EXCLUSIVITY_REQUIRED")
    return inspection


def assert_runtime_tool_provenance_v1(
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
) -> None:
    """Require the actual entrypoint and imported package to be the verified clone."""

    if not workspace_receipt.authority_eligible_for_real_execution:
        raise WorkspaceBootstrapError("WORKSPACE_IN_CLONE_VERIFY_REQUIRED")
    runtime_repository = _canonical_path(Path(workspace_receipt.runtime_repository_root))
    entrypoint_repository = _canonical_path(_calling_entrypoint_repository_root_v1())
    package_repository = _canonical_path(_loaded_package_repository_root_v1())
    if (
        entrypoint_repository != runtime_repository
        or package_repository != runtime_repository
        or os.path.normcase(workspace_receipt.bootstrap_tool_source_repository_root)
        != os.path.normcase(os.fspath(runtime_repository))
        or os.path.normcase(workspace_receipt.bootstrap_package_source_repository_root)
        != os.path.normcase(os.fspath(runtime_repository))
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_RUNTIME_TOOL_SOURCE_DRIFT")


def assert_real_capture_workspace_receipt_current_v1(
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    *,
    inspector: BoundaryInspector | None = None,
    command_runner: CommandRunner | None = None,
) -> None:
    """Recheck boundary identities, exact Git, and loaded-code provenance."""

    assert_runtime_tool_provenance_v1(workspace_receipt)
    runner = command_runner or SubprocessCommandRunner()
    boundary_inspector = inspector or WindowsBoundaryInspector(command_runner=runner)
    repository = _canonical_path(Path(workspace_receipt.runtime_repository_root))
    control_temp = _canonical_path(Path(workspace_receipt.control_temp_root))
    capture = _canonical_path(Path(workspace_receipt.capture_root))
    empty_template = _canonical_path(repository.parent / ".empty-git-template")
    inspections = tuple(
        _inspect_approved_root(boundary_inspector, path)
        for path in (repository, control_temp, capture)
    )
    _assert_roots_non_overlapping(inspections)
    if (
        inspections[0].canonical_path != repository
        or inspections[1].canonical_path != control_temp
        or inspections[2].canonical_path != capture
        or inspections[0].security_descriptor_sha256
        != workspace_receipt.repository_security_descriptor_sha256
        or inspections[1].security_descriptor_sha256
        != workspace_receipt.control_temp_security_descriptor_sha256
        or inspections[2].security_descriptor_sha256
        != workspace_receipt.capture_security_descriptor_sha256
        or exclusive_local_directory_fingerprint(repository)
        != workspace_receipt.repository_root_fingerprint
        or exclusive_local_directory_fingerprint(control_temp)
        != workspace_receipt.control_temp_fingerprint
        or capture_root_fingerprint(capture) != workspace_receipt.capture_root_fingerprint
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_WORKSPACE_RECEIPT_STALE")
    git_executable, git_sha256 = _validated_git_executable(
        Path(workspace_receipt.git_executable_path)
    )
    if git_sha256 != workspace_receipt.git_executable_sha256:
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_EXECUTABLE_CHANGED")
    _assert_safe_git_tree(
        runner,
        git_executable,
        _git_environment(empty_template),
        repository,
        workspace_receipt.authorized_main_sha,
    )
    try:
        from robin.capture.live_executor import GitRepositoryStateReader, LiveGuardError

        hardened_reader = GitRepositoryStateReader(
            repository,
            git_executable=git_executable,
            git_executable_sha256=git_sha256,
            control_temp_root=control_temp,
            repository_root_fingerprint=workspace_receipt.repository_root_fingerprint,
            control_temp_root_fingerprint=workspace_receipt.control_temp_fingerprint,
        )
        hardened_reader._assert_standalone_git_directory()
        hardened_reader._validate_git_metadata()
        hardened_reader._validate_worktree_tree()
        if isinstance(runner, SubprocessCommandRunner):
            state = hardened_reader.read_v2(
                approved_git_executable_path=workspace_receipt.git_executable_path,
                approved_git_executable_sha256=(workspace_receipt.git_executable_sha256),
            )
            if (
                state.head_sha != workspace_receipt.authorized_main_sha
                or state.main_sha != workspace_receipt.authorized_main_sha
            ):
                raise WorkspaceBootstrapError("BOOTSTRAP_RUNTIME_READER_MISMATCH")
    except LiveGuardError:
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_METADATA_OR_TREE_CHANGED") from None


def assert_workspace_control_artifact_destination_v1(
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    destination: Path,
) -> Path:
    """Restrict preparation writes to the receipt-bound control-temp root."""

    control_temp = _canonical_path(Path(workspace_receipt.control_temp_root))
    parent = _canonical_path(destination.absolute().parent)
    if parent != control_temp:
        raise WorkspaceBootstrapError("BOOTSTRAP_ARTIFACT_OUTSIDE_CONTROL_TEMP")
    if (
        exclusive_local_directory_fingerprint(control_temp)
        != workspace_receipt.control_temp_fingerprint
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_CONTROL_TEMP_IDENTITY_CHANGED")
    return Path(os.path.normcase(os.path.abspath(os.fspath(destination))))


def load_tracked_real_execution_mission_manifest_v1(
    repository_root: Path,
    requested_path: Path,
) -> RealExecutionMissionManifestV1:
    """Load only the exact pristine mission authority tracked by the runtime clone."""

    repository = _canonical_path(repository_root)
    expected = _canonical_path(repository / TRACKED_REAL_EXECUTION_MISSION_MANIFEST)
    requested = _canonical_path(requested_path)
    if requested != expected:
        raise WorkspaceBootstrapError("BOOTSTRAP_MISSION_MANIFEST_PATH_MISMATCH")
    try:
        payload = strict_json_object(
            _safe_read_bounded(expected, maximum_bytes=_MAXIMUM_MISSION_MANIFEST_BYTES)
        )
        return RealExecutionMissionManifestV1.issue(**payload)
    except (CaptureStorageError, OSError, TypeError, ValueError):
        raise WorkspaceBootstrapError("BOOTSTRAP_MISSION_MANIFEST_INVALID") from None


def discover_local_runtime_candidates_v1() -> tuple[Path, ...]:
    """Return deterministic, uncreated candidates on fixed local Windows volumes."""

    if os.name != "nt":
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_WINDOWS_REQUIRED")
    raw_candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        raw_candidates.append(Path(local_app_data) / "RobinRuntime")
    try:
        import ctypes

        windows_api = cast(Any, ctypes).windll
        mask = int(windows_api.kernel32.GetLogicalDrives())
        get_drive_type = windows_api.kernel32.GetDriveTypeW
        for index in range(26):
            if mask & (1 << index):
                root = f"{chr(ord('A') + index)}:\\"
                if int(get_drive_type(root)) == 3:
                    raw_candidates.append(Path(root) / "RobinRuntime")
    except (AttributeError, OSError, TypeError, ValueError):
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_CANDIDATE_DISCOVERY_FAILED") from None
    candidates: dict[str, Path] = {}
    for candidate in raw_candidates:
        raw = os.fspath(candidate)
        if raw.startswith(("\\\\", "//")):
            continue
        normalized = os.path.normcase(os.path.abspath(raw))
        candidates[normalized] = Path(normalized)
    if not candidates:
        raise WorkspaceBootstrapError("LOCAL_RUNTIME_BOUNDARY_UNAVAILABLE")
    return tuple(candidates.values())


def _select_runtime_candidate(
    runtime_parent: Path | None,
    *,
    mode: BootstrapMode,
    inspector: BoundaryInspector,
) -> Path:
    if runtime_parent is None and mode != "CREATE":
        raise WorkspaceBootstrapError("BOOTSTRAP_RUNTIME_PARENT_REQUIRED")
    candidates = (
        (runtime_parent,) if runtime_parent is not None else discover_local_runtime_candidates_v1()
    )
    last_error: WorkspaceBootstrapError | None = None
    for raw_candidate in candidates:
        raw = os.fspath(raw_candidate)
        if raw.startswith(("\\\\", "//")) or raw.casefold().startswith("\\\\?\\unc\\"):
            error = WorkspaceBootstrapError("LOCAL_RUNTIME_UNC_FORBIDDEN")
            if runtime_parent is not None:
                raise error
            last_error = error
            continue
        candidate = Path(os.path.normcase(os.path.abspath(raw)))
        if not _path_exists_no_follow(candidate.parent):
            error = WorkspaceBootstrapError("LOCAL_RUNTIME_CANDIDATE_PARENT_MISSING")
            if runtime_parent is not None:
                raise error
            last_error = error
            continue
        try:
            _reject_reparse_path(candidate.parent)
            parent = _inspect_approved_root(inspector, candidate.parent)
        except CaptureStorageError:
            reparse_error = WorkspaceBootstrapError("LOCAL_RUNTIME_REPARSE_PARENT_FORBIDDEN")
            if runtime_parent is not None:
                raise reparse_error from None
            last_error = reparse_error
            continue
        except WorkspaceBootstrapError as error:
            if runtime_parent is not None:
                raise
            last_error = error
            continue
        selected = parent.canonical_path / candidate.name
        sync_roots = _registered_windows_sync_roots() if os.name == "nt" else ()
        if any(_is_within(selected, root) for root in sync_roots):
            sync_error = WorkspaceBootstrapError("LOCAL_RUNTIME_SYNCHRONIZED_ROOT_FORBIDDEN")
            if runtime_parent is not None:
                raise sync_error
            last_error = sync_error
            continue
        return selected
    raise WorkspaceBootstrapError("LOCAL_RUNTIME_BOUNDARY_UNAVAILABLE") from last_error


def write_workspace_receipt_immutable(
    path: Path,
    receipt: RealCaptureWorkspaceReceiptV1,
) -> None:
    try:
        _reject_reparse_path(path)
        parent_metadata = path.parent.lstat()
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_PARENT_UNSAFE")
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_ALREADY_EXISTS") from None
    except (CaptureStorageError, OSError):
        raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_WRITE_FAILED") from None


def prepare_real_capture_workspace_v1(
    *,
    runtime_parent: Path | None,
    expected_main_sha: str,
    git_executable: Path,
    mode: BootstrapMode,
    prepared_at_utc: datetime,
    receipt_output: Path | None = None,
    inspector: BoundaryInspector | None = None,
    command_runner: CommandRunner | None = None,
) -> RealCaptureWorkspaceReceiptV1:
    """Create or verify a complete local clone; never inspect provider credentials."""

    if mode not in {"CREATE", "VERIFY", "INSPECT"}:
        raise WorkspaceBootstrapError("BOOTSTRAP_MODE_INVALID")
    if len(expected_main_sha) != 40 or any(
        character not in "0123456789abcdef" for character in expected_main_sha
    ):
        raise WorkspaceBootstrapError("BOOTSTRAP_MAIN_SHA_INVALID")
    observed_at = ensure_utc(prepared_at_utc, field="bootstrap_prepared_at")
    runner = command_runner or SubprocessCommandRunner()
    boundary_inspector = inspector or WindowsBoundaryInspector(command_runner=runner)
    canonical_git, git_sha256 = _validated_git_executable(git_executable)
    runtime = _select_runtime_candidate(
        runtime_parent,
        mode=mode,
        inspector=boundary_inspector,
    )
    repository = runtime / "repository"
    control_temp = runtime / "control-temp"
    capture = runtime / "capture"
    empty_template = runtime / ".empty-git-template"
    tool_source_repository = _canonical_path(_calling_entrypoint_repository_root_v1())
    package_source_repository = _canonical_path(_loaded_package_repository_root_v1())

    if mode == "CREATE":
        if _path_exists_no_follow(runtime):
            raise WorkspaceBootstrapError("BOOTSTRAP_PARTIAL_STATE_PRESENT")
        try:
            runtime.mkdir(parents=False, exist_ok=False)
            _inspect_approved_root(boundary_inspector, runtime)
            control_temp.mkdir(parents=False, exist_ok=False)
            _inspect_approved_root(boundary_inspector, control_temp)
            capture.mkdir(parents=False, exist_ok=False)
            _inspect_approved_root(boundary_inspector, capture)
            empty_template.mkdir(parents=False, exist_ok=False)
            _inspect_approved_root(boundary_inspector, empty_template)
        except WorkspaceBootstrapError:
            raise
        except OSError:
            raise WorkspaceBootstrapError("BOOTSTRAP_DIRECTORY_CREATE_FAILED") from None
        environment = _git_environment(empty_template)
        _create_exact_clone(
            runner=runner,
            git_executable=canonical_git,
            environment=environment,
            runtime_parent=runtime,
            repository=repository,
            expected_main_sha=expected_main_sha,
        )
    else:
        if not all(
            _path_exists_no_follow(path)
            for path in (runtime, repository, control_temp, capture, empty_template)
        ):
            raise WorkspaceBootstrapError("BOOTSTRAP_WORKSPACE_INCOMPLETE")

    inspections = tuple(
        _inspect_approved_root(boundary_inspector, path)
        for path in (repository, control_temp, capture)
    )
    _assert_roots_non_overlapping(inspections)
    environment = _git_environment(empty_template)
    _assert_safe_git_tree(
        runner,
        canonical_git,
        environment,
        repository,
        expected_main_sha,
    )
    if _validated_git_executable(canonical_git) != (canonical_git, git_sha256):
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_EXECUTABLE_CHANGED")
    try:
        repository_fingerprint = exclusive_local_directory_fingerprint(repository)
        control_fingerprint = exclusive_local_directory_fingerprint(control_temp)
        capture_fingerprint = capture_root_fingerprint(capture)
    except CaptureStorageError:
        raise WorkspaceBootstrapError("BOOTSTRAP_ROOT_FINGERPRINT_FAILED") from None
    try:
        from robin.capture.live_executor import GitRepositoryStateReader, LiveGuardError

        runtime_reader = GitRepositoryStateReader(
            repository,
            git_executable=canonical_git,
            git_executable_sha256=git_sha256,
            control_temp_root=control_temp,
            repository_root_fingerprint=repository_fingerprint,
            control_temp_root_fingerprint=control_fingerprint,
        )
        runtime_reader._assert_standalone_git_directory()
        runtime_reader._validate_git_metadata()
        runtime_reader._validate_worktree_tree()
        if isinstance(runner, SubprocessCommandRunner):
            state = runtime_reader.read_v2(
                approved_git_executable_path=os.fspath(canonical_git),
                approved_git_executable_sha256=git_sha256,
            )
            if state.head_sha != expected_main_sha or state.main_sha != expected_main_sha:
                raise WorkspaceBootstrapError("BOOTSTRAP_RUNTIME_READER_MISMATCH")
    except LiveGuardError:
        raise WorkspaceBootstrapError("BOOTSTRAP_GIT_METADATA_OR_TREE_UNSAFE") from None
    receipt = RealCaptureWorkspaceReceiptV1.issue(
        authorized_main_sha=expected_main_sha,
        bootstrap_mode=mode,
        bootstrap_tool_source_repository_root=os.fspath(tool_source_repository),
        bootstrap_tool_loaded_from_runtime_repository=(
            tool_source_repository == inspections[0].canonical_path
        ),
        bootstrap_package_source_repository_root=os.fspath(package_source_repository),
        bootstrap_package_loaded_from_runtime_repository=(
            package_source_repository == inspections[0].canonical_path
        ),
        authority_eligible_for_real_execution=(
            mode == "VERIFY"
            and tool_source_repository == inspections[0].canonical_path
            and package_source_repository == inspections[0].canonical_path
        ),
        prepared_at_utc=observed_at,
        runtime_repository_root=os.fspath(inspections[0].canonical_path),
        repository_root_fingerprint=repository_fingerprint,
        repository_security_descriptor_sha256=(inspections[0].security_descriptor_sha256),
        control_temp_root=os.fspath(inspections[1].canonical_path),
        control_temp_fingerprint=control_fingerprint,
        control_temp_security_descriptor_sha256=(inspections[1].security_descriptor_sha256),
        capture_root=os.fspath(inspections[2].canonical_path),
        capture_root_fingerprint=capture_fingerprint,
        capture_security_descriptor_sha256=(inspections[2].security_descriptor_sha256),
        git_executable_path=os.fspath(canonical_git),
        git_executable_sha256=git_sha256,
        exact_detached_checkout=True,
        worktree_pristine=True,
        index_pristine=True,
        expected_remote_verified=True,
        submodules_absent=True,
        alternates_absent=True,
        unsafe_config_includes_absent=True,
        synchronized_roots_absent=True,
        cloud_placeholders_absent=True,
        reparse_escapes_absent=True,
        roots_non_overlapping=True,
        local_fixed_filesystem_verified=True,
        acl_exclusivity_verified=True,
    )
    if mode != "INSPECT":
        output = Path(
            os.path.normcase(
                os.path.abspath(
                    os.fspath(
                        receipt_output
                        or control_temp / f"workspace-{receipt.canonical_receipt_hash}.json"
                    )
                )
            )
        )
        try:
            output_parent = _inspect_approved_root(boundary_inspector, output.parent)
            _reject_reparse_path(output)
        except (CaptureStorageError, WorkspaceBootstrapError):
            raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_OUTPUT_UNSAFE") from None
        if not _is_within(output_parent.canonical_path, inspections[1].canonical_path):
            raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_OUTPUT_OUTSIDE_CONTROL_TEMP")
        write_workspace_receipt_immutable(output, receipt)
        repeated_parent = _inspect_approved_root(boundary_inspector, output.parent)
        if repeated_parent != output_parent:
            raise WorkspaceBootstrapError("BOOTSTRAP_RECEIPT_PARENT_IDENTITY_CHANGED")
    return receipt
