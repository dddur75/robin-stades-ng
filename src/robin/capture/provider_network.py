"""Owner-preparation DNS boundary for an immutable provider network binding."""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from robin.capture.bootstrap_contracts import (
    MIN_OWNER_REVIEW_WINDOW,
    PRE_KICKOFF_SAFETY_MARGIN,
    PROVIDER_CANONICAL_HOSTNAME,
    CampaignWindowSelectionV1,
    ProviderNetworkBindingV1,
    ProviderNetworkResolutionClaimV1,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
)
from robin.capture.contracts import canonical_json_bytes, ensure_utc
from robin.capture.storage import (
    CaptureStorageError,
    _path_exists_no_follow,
    _reject_reparse_path,
    exclusive_local_directory_fingerprint,
    validate_exclusive_local_directory_identity,
)

_RESOLUTION_CLAIM_NAME = "provider-network-resolution-one-shot-v1.json"
_MISSION_GLOBAL_CLAIM_ROOT_NAME = "RobinRealExecutionMissionClaimsV1"


class ProviderNetworkPreparationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResolverV1(Protocol):
    def __call__(
        self,
        host: str,
        port: int,
        family: int,
        socket_type: int,
        protocol: int,
    ) -> Iterable[tuple[Any, ...]]: ...


def _system_getaddrinfo(
    host: str,
    port: int,
    family: int,
    socket_type: int,
    protocol: int,
) -> Iterable[tuple[Any, ...]]:
    return socket.getaddrinfo(host, port, family, socket_type, protocol)


def system_resolver_identity_v1() -> str:
    if os.name == "nt":
        return "WINDOWS_WINSOCK_SYSTEM_STUB_RESOLVER"
    if os.name == "posix":
        return "POSIX_LIBC_SYSTEM_STUB_RESOLVER"
    return "PYTHON_SOCKET_SYSTEM_STUB_RESOLVER"


def prepare_provider_network_binding_v1(
    *,
    resolution_claim: ProviderNetworkResolutionClaimV1,
    resolver: ResolverV1 = _system_getaddrinfo,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    binding_ttl_seconds: int = 900,
    resolver_identity: str | None = None,
    maximum_expires_at_utc: datetime | None = None,
    minimum_binding_ttl_seconds: int = 1,
    observed_at_utc: datetime | None = None,
) -> ProviderNetworkBindingV1:
    """Resolve the one literal host once and perform no provider transport."""

    if (
        not 1 <= binding_ttl_seconds <= 900
        or not 1 <= minimum_binding_ttl_seconds <= binding_ttl_seconds
    ):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_TTL_INVALID")
    observed_at = ensure_utc(
        observed_at_utc if observed_at_utc is not None else clock(),
        field="network_binding_observed_at",
    )
    if observed_at >= resolution_claim.mission_expires_at_utc:
        raise ProviderNetworkPreparationError("BOOTSTRAP_MISSION_EXPIRED")
    if (
        observed_at < resolution_claim.claimed_at_utc
        or observed_at - resolution_claim.claimed_at_utc > timedelta(minutes=1)
    ):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_CLAIM_NOT_CURRENT")
    expiry_ceiling = resolution_claim.mission_expires_at_utc
    if maximum_expires_at_utc is not None:
        expiry_ceiling = min(
            expiry_ceiling,
            ensure_utc(maximum_expires_at_utc, field="network_binding_maximum_expires_at"),
        )
    available_whole_seconds = int((expiry_ceiling - observed_at).total_seconds())
    effective_ttl_seconds = min(binding_ttl_seconds, available_whole_seconds)
    if effective_ttl_seconds < minimum_binding_ttl_seconds:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_OWNER_REVIEW_WINDOW_INSUFFICIENT")
    try:
        # This is the sole resolver operation.  No fallback invocation is permitted.
        answers = tuple(
            resolver(
                PROVIDER_CANONICAL_HOSTNAME,
                443,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
            )
        )
    except (OSError, TypeError, ValueError):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_FAILED") from None
    addresses: list[str] = []
    for answer in answers:
        if not isinstance(answer, tuple) or len(answer) < 5:
            raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_RESULT_INVALID")
        socket_address = answer[4]
        if not isinstance(socket_address, tuple) or not socket_address:
            raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_RESULT_INVALID")
        address = socket_address[0]
        if not isinstance(address, str):
            raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_RESULT_INVALID")
        addresses.append(address)
    try:
        return ProviderNetworkBindingV1.issue(
            resolution_claim=resolution_claim,
            resolver_identity=resolver_identity or system_resolver_identity_v1(),
            observed_at_utc=observed_at,
            expires_at_utc=observed_at + timedelta(seconds=effective_ttl_seconds),
            binding_ttl_seconds=effective_ttl_seconds,
            resolved_ip_addresses=tuple(addresses),
        )
    except ValueError:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_INVALID") from None


def _validated_control_destination(
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    output_path: Path,
) -> tuple[Path, Path]:
    try:
        control_root = validate_exclusive_local_directory_identity(
            Path(workspace_receipt.control_temp_root)
        )
        parent = validate_exclusive_local_directory_identity(output_path.absolute().parent)
        destination = parent / output_path.name
        _reject_reparse_path(destination)
    except (CaptureStorageError, OSError, ValueError):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_OUTPUT_UNSAFE") from None
    if parent != control_root:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_OUTPUT_OUTSIDE_CONTROL_TEMP")
    try:
        if (
            exclusive_local_directory_fingerprint(control_root)
            != workspace_receipt.control_temp_fingerprint
        ):
            raise ProviderNetworkPreparationError("PROVIDER_NETWORK_WORKSPACE_IDENTITY_CHANGED")
    except CaptureStorageError:
        raise ProviderNetworkPreparationError(
            "PROVIDER_NETWORK_WORKSPACE_IDENTITY_CHANGED"
        ) from None
    return control_root, destination


def _mission_global_claim_registry_root_v1() -> Path:
    """Resolve one OS-known, fixed, ACL-verified registry shared by all workspaces."""

    if os.name != "nt":
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_GLOBAL_CLAIM_BOUNDARY_UNAVAILABLE")
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32_768)
        result = ctypes.windll.shell32.SHGetFolderPathW(
            None,
            0x001C,
            None,
            0,
            buffer,
        )
        if result != 0 or not buffer.value:
            raise OSError
        from robin.capture.workspace_bootstrap import (
            WindowsBoundaryInspector,
            _inspect_approved_root,
        )

        inspector = WindowsBoundaryInspector()
        local_app_data = Path(buffer.value)
        _inspect_approved_root(inspector, local_app_data)
        registry = local_app_data / _MISSION_GLOBAL_CLAIM_ROOT_NAME
        try:
            registry.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            pass
        inspection = _inspect_approved_root(inspector, registry)
        canonical = validate_exclusive_local_directory_identity(inspection.canonical_path)
        if canonical != inspection.canonical_path:
            raise OSError
        return canonical
    except (CaptureStorageError, OSError, TypeError, ValueError):
        raise ProviderNetworkPreparationError(
            "PROVIDER_NETWORK_GLOBAL_CLAIM_BOUNDARY_UNAVAILABLE"
        ) from None


def _write_resolution_claim_marker_v1(
    marker: Path,
    payload: bytes,
    *,
    failure_code: str,
) -> None:
    try:
        descriptor = os.open(
            marker,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError:
        raise ProviderNetworkPreparationError(
            "PROVIDER_NETWORK_RESOLUTION_ALREADY_CONSUMED"
        ) from None
    except OSError:
        raise ProviderNetworkPreparationError(failure_code) from None


def reserve_provider_network_resolution_v1(
    *,
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
    campaign_selection: CampaignWindowSelectionV1,
    output_path: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    binding_ttl_seconds: int = 900,
) -> ProviderNetworkResolutionClaimV1:
    """Durably consume the sole DNS attempt before the resolver can run."""

    if not 1 <= binding_ttl_seconds <= 900:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_TTL_INVALID")
    control_root, destination = _validated_control_destination(workspace_receipt, output_path)
    if not workspace_receipt.authority_eligible_for_real_execution:
        raise ProviderNetworkPreparationError("WORKSPACE_IN_CLONE_VERIFY_REQUIRED")
    marker = control_root / _RESOLUTION_CLAIM_NAME
    if _path_exists_no_follow(destination):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_OUTPUT_EXISTS")
    claimed_at = ensure_utc(clock(), field="network_resolution_claimed_at")
    if claimed_at >= mission_manifest.expires_at:
        raise ProviderNetworkPreparationError("BOOTSTRAP_MISSION_EXPIRED")
    try:
        campaign_selection.assert_selected_candidate_current(claimed_at)
    except ValueError:
        raise ProviderNetworkPreparationError("CAMPAIGN_SELECTION_NOT_CURRENT") from None
    selected = campaign_selection.selected_candidate()
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    campaign_expiry_ceiling = min(
        mission_manifest.expires_at,
        selected.usable_expires_at_utc,
        earliest_kickoff - PRE_KICKOFF_SAFETY_MARGIN,
    )
    requested_expiry = claimed_at + timedelta(seconds=binding_ttl_seconds)
    if min(requested_expiry, campaign_expiry_ceiling) - claimed_at < MIN_OWNER_REVIEW_WINDOW:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_OWNER_REVIEW_WINDOW_INSUFFICIENT")
    if (
        campaign_selection.workspace_receipt_sha256 != workspace_receipt.canonical_receipt_hash
        or campaign_selection.workspace_prepared_at_utc != workspace_receipt.prepared_at_utc
        or campaign_selection.mission_manifest_sha256
        != mission_manifest.canonical_manifest_sha256()
        or campaign_selection.mission_expires_at_utc != mission_manifest.expires_at
        or campaign_selection.selected_fixture_target_set_sha256
        != selected.fixture_target_set.canonical_set_hash
    ):
        raise ProviderNetworkPreparationError("CAMPAIGN_SELECTION_AUTHORITY_MISMATCH")
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace_receipt.canonical_receipt_hash,
        campaign_selection_sha256=campaign_selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=claimed_at,
        mission_expires_at_utc=mission_manifest.expires_at,
    )
    payload = canonical_json_bytes(claim.model_dump(mode="json")) + b"\n"
    registry = _mission_global_claim_registry_root_v1()
    global_marker = registry / (
        f"{mission_manifest.mission_id.casefold()}-"
        f"{mission_manifest.canonical_manifest_sha256()}.json"
    )
    _write_resolution_claim_marker_v1(
        global_marker,
        payload,
        failure_code="PROVIDER_NETWORK_GLOBAL_RESOLUTION_CLAIM_FAILED",
    )
    _write_resolution_claim_marker_v1(
        marker,
        payload,
        failure_code="PROVIDER_NETWORK_RESOLUTION_CLAIM_FAILED",
    )
    return claim


def prepare_provider_network_binding_once_v1(
    *,
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
    campaign_selection: CampaignWindowSelectionV1,
    output_path: Path,
    resolver: ResolverV1 = _system_getaddrinfo,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    binding_ttl_seconds: int = 900,
    resolver_identity: str | None = None,
) -> ProviderNetworkBindingV1:
    """Reserve, resolve exactly once, and persist; any failure permanently forbids retry."""

    claim = reserve_provider_network_resolution_v1(
        workspace_receipt=workspace_receipt,
        mission_manifest=mission_manifest,
        campaign_selection=campaign_selection,
        output_path=output_path,
        clock=clock,
        binding_ttl_seconds=binding_ttl_seconds,
    )
    selected = campaign_selection.selected_candidate()
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    campaign_expiry_ceiling = min(
        mission_manifest.expires_at,
        selected.usable_expires_at_utc,
        earliest_kickoff - PRE_KICKOFF_SAFETY_MARGIN,
    )
    observed_at = ensure_utc(clock(), field="network_binding_observed_at")
    if observed_at >= mission_manifest.expires_at:
        raise ProviderNetworkPreparationError("BOOTSTRAP_MISSION_EXPIRED")
    if observed_at < claim.claimed_at_utc or observed_at - claim.claimed_at_utc > timedelta(
        minutes=1
    ):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_RESOLUTION_CLAIM_NOT_CURRENT")
    try:
        campaign_selection.assert_selected_candidate_current(observed_at)
    except ValueError:
        raise ProviderNetworkPreparationError("CAMPAIGN_SELECTION_NOT_CURRENT") from None
    _validated_control_destination(workspace_receipt, output_path)
    binding = prepare_provider_network_binding_v1(
        resolution_claim=claim,
        resolver=resolver,
        clock=clock,
        binding_ttl_seconds=binding_ttl_seconds,
        resolver_identity=resolver_identity,
        maximum_expires_at_utc=campaign_expiry_ceiling,
        minimum_binding_ttl_seconds=int(MIN_OWNER_REVIEW_WINDOW.total_seconds()),
        observed_at_utc=observed_at,
    )
    write_immutable_network_binding_v1(binding, output_path)
    return binding


def write_immutable_network_binding_v1(
    binding: ProviderNetworkBindingV1,
    output_path: Path,
) -> None:
    """Create one immutable artifact and refuse replacement or reparse traversal."""

    try:
        validated = ProviderNetworkBindingV1.model_validate(binding.model_dump(mode="json"))
        parent = validate_exclusive_local_directory_identity(output_path.parent)
        destination = parent / output_path.name
        _reject_reparse_path(destination)
        payload = canonical_json_bytes(validated.model_dump(mode="json")) + b"\n"
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError:
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_OUTPUT_EXISTS") from None
    except (AttributeError, CaptureStorageError, OSError, TypeError, ValueError):
        raise ProviderNetworkPreparationError("PROVIDER_NETWORK_BINDING_WRITE_FAILED") from None


def default_binding_output_name(binding: ProviderNetworkBindingV1) -> str:
    return f"provider-network-binding-{binding.canonical_binding_hash}.json"
