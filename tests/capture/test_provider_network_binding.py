from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import robin.capture.provider_network as provider_network_module
from robin.capture import (
    CampaignLeagueCorpusCountV1,
    CampaignWindowSelectionV1,
    CaptureContractError,
    FixtureTargetSetV1,
    OfficialFixtureTargetV1,
    ProviderNetworkBindingV1,
    ProviderNetworkResolutionClaimV1,
    PublicProviderRequestV2,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
    ScientificCorpusSnapshotV1,
    StrictHttpsTransportV2,
)
from robin.capture.contracts import ProviderRequestSpec
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS
from robin.capture.live_transport import LiveTransportError
from robin.capture.provider_network import (
    ProviderNetworkPreparationError,
    prepare_provider_network_binding_once_v1,
    prepare_provider_network_binding_v1,
)
from robin.capture.storage import exclusive_local_directory_fingerprint

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_mission_global_claim_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = tmp_path / "mission-global-claim-registry"
    registry.mkdir()
    monkeypatch.setattr(
        provider_network_module,
        "_mission_global_claim_registry_root_v1",
        lambda: registry,
    )


def resolution_claim() -> ProviderNetworkResolutionClaimV1:
    return ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256="1" * 64,
        workspace_receipt_sha256="2" * 64,
        campaign_selection_sha256="3" * 64,
        fixture_target_set_sha256="4" * 64,
        claimed_at_utc=NOW - timedelta(seconds=1),
        mission_expires_at_utc=NOW + timedelta(days=1),
    )


def binding(*addresses: str, ttl: int = 600) -> ProviderNetworkBindingV1:
    return ProviderNetworkBindingV1.issue(
        resolution_claim=resolution_claim(),
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=NOW,
        expires_at_utc=NOW + timedelta(seconds=ttl),
        binding_ttl_seconds=ttl,
        resolved_ip_addresses=addresses,
    )


def request(network_binding: ProviderNetworkBindingV1) -> PublicProviderRequestV2:
    spec = ProviderRequestSpec(
        sport_key="soccer_epl",
        endpoint="/v4/sports/soccer_epl/odds",
        region="eu",
        markets=("h2h",),
        odds_format="decimal",
        date_format="iso",
        timeout_seconds=5,
    )
    return PublicProviderRequestV2.from_spec(
        spec,
        maximum_response_bytes=10_000,
        provider_network_binding=network_binding,
    )


def test_single_resolution_is_canonical_deduplicated_and_order_stable() -> None:
    calls: list[tuple[object, ...]] = []

    def resolver(*arguments: object) -> list[tuple[object, ...]]:
        calls.append(arguments)
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.4.4", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.4.4", 443)),
        ]

    first = prepare_provider_network_binding_v1(
        resolution_claim=resolution_claim(),
        resolver=resolver,
        clock=lambda: NOW,
        binding_ttl_seconds=600,
        resolver_identity="TEST_OS_STUB_RESOLVER",
    )
    second = binding("2606:4700:4700::1111", "8.8.8.8", "8.8.4.4")
    assert calls == [
        (
            "api.the-odds-api.com",
            443,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
    ]
    assert first.resolved_ip_addresses == (
        "8.8.4.4",
        "8.8.8.8",
        "2606:4700:4700::1111",
    )
    assert first.selected_ip_address == "8.8.4.4"
    assert first.canonical_binding_hash == second.canonical_binding_hash
    assert first.provider_http_requests == first.provider_tcp_connections == 0
    assert first.provider_secret_reads == 0


@pytest.mark.parametrize(
    "address",
    (
        "not-an-ip",
        "10.0.0.1",
        "127.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "0.0.0.0",
        "192.0.2.1",
        "192.0.0.9",
        "192.0.0.10",
        "192.31.196.1",
        "192.52.193.1",
        "192.88.99.1",
        "192.175.48.1",
        "64:ff9b::808:808",
        "2001:1::1",
        "2001:3::1",
        "2001:4:112::1",
        "2001:20::1",
        "2001:30::1",
        "2620:4f:8000::1",
        "fec0::1",
        "::ffff:8.8.8.8",
    ),
)
def test_non_global_or_malformed_address_is_rejected(address: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        binding(address)


def test_binding_hash_hostname_selection_family_and_expiry_fail_closed() -> None:
    original = binding("8.8.8.8")
    material = original.model_dump(mode="json")
    for field, value in (
        ("selected_ip_address", "1.1.1.1"),
        ("address_family", "IPv6"),
        ("canonical_binding_hash", "0" * 64),
        ("canonical_hostname", "example.com"),
    ):
        mutated = {**material, field: value}
        with pytest.raises(CaptureContractError):
            ProviderNetworkBindingV1.model_validate(mutated)
    original.assert_current(original.expires_at_utc - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="NETWORK_BINDING_EXPIRED"):
        original.assert_current(original.expires_at_utc)


def test_binding_ttl_requires_exact_duration_without_fractional_truncation() -> None:
    with pytest.raises(CaptureContractError):
        ProviderNetworkBindingV1.issue(
            resolution_claim=resolution_claim(),
            resolver_identity="TEST_OS_STUB_RESOLVER",
            observed_at_utc=NOW,
            expires_at_utc=NOW + timedelta(seconds=600, microseconds=500_000),
            binding_ttl_seconds=600,
            resolved_ip_addresses=("8.8.8.8",),
        )


def test_binding_cannot_be_observed_at_or_extend_past_claim_mission_expiry() -> None:
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256="1" * 64,
        workspace_receipt_sha256="2" * 64,
        campaign_selection_sha256="3" * 64,
        fixture_target_set_sha256="4" * 64,
        claimed_at_utc=NOW - timedelta(seconds=1),
        mission_expires_at_utc=NOW + timedelta(seconds=10),
    )
    for observed, expires in (
        (NOW + timedelta(seconds=10), NOW + timedelta(seconds=11)),
        (NOW, NOW + timedelta(seconds=11)),
    ):
        with pytest.raises(CaptureContractError):
            ProviderNetworkBindingV1.issue(
                resolution_claim=claim,
                resolver_identity="TEST_OS_STUB_RESOLVER",
                observed_at_utc=observed,
                expires_at_utc=expires,
                binding_ttl_seconds=int((expires - observed).total_seconds()),
                resolved_ip_addresses=("8.8.8.8",),
            )


class _Response:
    status = 200

    def getheaders(self) -> list[tuple[str, str]]:
        return [("x-requests-last", "1")]

    def read1(self, _amount: int | None = None) -> bytes:
        if hasattr(self, "_read"):
            return b""
        self._read = True
        return b"[]"

    def read(self, _amount: int | None = None) -> bytes:
        return b"[]"


class _Connection:
    debuglevel = 0

    def __init__(
        self,
        *,
        expected_ip: str,
        guard: Any,
        clock_state: list[datetime],
        expire_during_request: bool,
    ) -> None:
        self.sock = self
        self.expected_ip = expected_ip
        self.guard = guard
        self.clock_state = clock_state
        self.expire_during_request = expire_during_request

    def set_debuglevel(self, value: int) -> None:
        self.debuglevel = value

    def request(self, *_args: object, **_kwargs: object) -> None:
        if self.expire_during_request:
            self.clock_state[0] = NOW + timedelta(minutes=10)
        self.guard()

    def getpeername(self) -> tuple[str, int]:
        return self.expected_ip, 443

    def settimeout(self, _value: float) -> None:
        return None

    def getresponse(self) -> _Response:
        return _Response()

    def close(self) -> None:
        return None


def _tls_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _mission_manifest(expires_at: datetime) -> RealExecutionMissionManifestV1:
    return RealExecutionMissionManifestV1.issue(
        authorized_stages=("E1",),
        maximum_stage="E1",
        external_effects=(
            "local_standalone_runtime_create_after_merge",
            "github_public_full_clone_after_merge",
            "provider_public_dns_resolution_exactly_once_after_merge",
            "official_schedule_public_read_after_merge",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ),
        compute_budget=8000,
        time_budget=345600,
        expires_at=expires_at,
    )


def _network_workspace(tmp_path: Path) -> tuple[RealCaptureWorkspaceReceiptV1, Path]:
    repository = tmp_path / "repository"
    control = tmp_path / "control-temp"
    capture = tmp_path / "capture"
    for directory in (repository, control, capture):
        directory.mkdir()
    git = tmp_path / "git.exe"
    git.write_bytes(b"synthetic")
    return (
        RealCaptureWorkspaceReceiptV1.issue(
            authorized_main_sha="a" * 40,
            bootstrap_mode="VERIFY",
            bootstrap_tool_source_repository_root=str(repository.absolute()),
            bootstrap_tool_loaded_from_runtime_repository=True,
            bootstrap_package_source_repository_root=str(repository.absolute()),
            bootstrap_package_loaded_from_runtime_repository=True,
            authority_eligible_for_real_execution=True,
            prepared_at_utc=NOW - timedelta(minutes=3),
            runtime_repository_root=str(repository.absolute()),
            repository_root_fingerprint="3" * 64,
            repository_security_descriptor_sha256="7" * 64,
            control_temp_root=str(control.absolute()),
            control_temp_fingerprint=exclusive_local_directory_fingerprint(control),
            control_temp_security_descriptor_sha256="8" * 64,
            capture_root=str(capture.absolute()),
            capture_root_fingerprint="5" * 64,
            capture_security_descriptor_sha256="9" * 64,
            git_executable_path=str(git.absolute()),
            git_executable_sha256="6" * 64,
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
        ),
        control,
    )


def _campaign_selection(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
) -> CampaignWindowSelectionV1:
    selected_at = NOW - timedelta(seconds=5)
    source_observed = NOW - timedelta(minutes=2)
    created = NOW - timedelta(minutes=1)
    target_sets = []
    for index, sport_key in enumerate(LIVE_ALLOWED_SPORT_KEYS):
        target = OfficialFixtureTargetV1.issue(
            internal_fixture_target_id=f"fixture-{index}",
            competition=f"Competition {index}",
            sport_key=sport_key,
            official_home_team=f"Home {index}",
            official_away_team=f"Away {index}",
            official_kickoff_utc=NOW + timedelta(hours=2, minutes=10),
            official_source_authority="https://official.example/schedule",
            source_observed_at_utc=source_observed,
            source_evidence_sha256=f"{index + 1}" * 64,
        )
        target_sets.append(
            FixtureTargetSetV1.issue(
                target_set_id=f"official-target-set-{index}",
                sport_key=sport_key,
                workspace_receipt_sha256=workspace.canonical_receipt_hash,
                created_at_utc=created,
                official_schedule_horizon_not_before_utc=selected_at - timedelta(minutes=1),
                official_schedule_horizon_expires_at_utc=NOW + timedelta(days=1),
                official_schedule_fixture_count=1,
                official_schedule_completeness=("OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON"),
                targets=(target,),
            )
        )
    corpus = ScientificCorpusSnapshotV1.issue(
        observed_at_utc=selected_at,
        source_evidence_sha256="f" * 64,
        league_counts=tuple(
            CampaignLeagueCorpusCountV1(
                sport_key=sport_key,
                admitted_fixture_count=0,
            )
            for sport_key in LIVE_ALLOWED_SPORT_KEYS
        ),
    )
    return CampaignWindowSelectionV1.issue(
        selected_at_utc=selected_at,
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        workspace_prepared_at_utc=workspace.prepared_at_utc,
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        mission_expires_at_utc=manifest.expires_at,
        source_target_sets=tuple(target_sets),
        corpus_snapshot=corpus,
    )


def test_v2_transport_uses_one_selected_ip_and_rechecks_inside_connect() -> None:
    network_binding = binding("8.8.8.8")
    clock_state = [NOW + timedelta(minutes=1)]
    factory_calls: list[str] = []

    def factory(
        _host: str,
        ip: str,
        _port: int,
        _timeout: float,
        _context: ssl.SSLContext,
        _monotonic: Any,
        _started: float,
        guard: Any,
    ) -> _Connection:
        factory_calls.append(ip)
        return _Connection(
            expected_ip=ip,
            guard=guard,
            clock_state=clock_state,
            expire_during_request=False,
        )

    transport = StrictHttpsTransportV2(
        clock=lambda: clock_state[0],
        connection_factory=factory,
        ssl_context_factory=_tls_context,
    )
    public_request = request(network_binding)
    transport.preflight(public_request)
    response = transport.dispatch(public_request, api_key="a" * 32)
    assert response.payload == b"[]"
    assert factory_calls == [network_binding.selected_ip_address]


def test_v2_transport_rejects_binding_expiry_between_dispatch_gate_and_connect() -> None:
    network_binding = binding("8.8.8.8")
    clock_state = [NOW + timedelta(minutes=1)]

    def factory(
        _host: str,
        ip: str,
        _port: int,
        _timeout: float,
        _context: ssl.SSLContext,
        _monotonic: Any,
        _started: float,
        guard: Any,
    ) -> _Connection:
        return _Connection(
            expected_ip=ip,
            guard=guard,
            clock_state=clock_state,
            expire_during_request=True,
        )

    transport = StrictHttpsTransportV2(
        clock=lambda: clock_state[0],
        connection_factory=factory,
        ssl_context_factory=_tls_context,
    )
    public_request = request(network_binding)
    transport.preflight(public_request)
    with pytest.raises(LiveTransportError, match="LIVE_PROVIDER_NETWORK_BINDING_EXPIRED"):
        transport.dispatch(public_request, api_key="a" * 32)


def test_durable_claim_prevents_second_resolution_even_with_different_output(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    control = tmp_path / "control-temp"
    capture = tmp_path / "capture"
    for directory in (repository, control, capture):
        directory.mkdir()
    git = tmp_path / "git.exe"
    git.write_bytes(b"synthetic")
    workspace = RealCaptureWorkspaceReceiptV1.issue(
        authorized_main_sha="a" * 40,
        bootstrap_mode="VERIFY",
        bootstrap_tool_source_repository_root=str(repository.absolute()),
        bootstrap_tool_loaded_from_runtime_repository=True,
        bootstrap_package_source_repository_root=str(repository.absolute()),
        bootstrap_package_loaded_from_runtime_repository=True,
        authority_eligible_for_real_execution=True,
        prepared_at_utc=NOW - timedelta(minutes=3),
        runtime_repository_root=str(repository.absolute()),
        repository_root_fingerprint="3" * 64,
        repository_security_descriptor_sha256="7" * 64,
        control_temp_root=str(control.absolute()),
        control_temp_fingerprint=exclusive_local_directory_fingerprint(control),
        control_temp_security_descriptor_sha256="8" * 64,
        capture_root=str(capture.absolute()),
        capture_root_fingerprint="5" * 64,
        capture_security_descriptor_sha256="9" * 64,
        git_executable_path=str(git.absolute()),
        git_executable_sha256="6" * 64,
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
    manifest = RealExecutionMissionManifestV1.issue(
        authorized_stages=("E1",),
        maximum_stage="E1",
        external_effects=(
            "local_standalone_runtime_create_after_merge",
            "github_public_full_clone_after_merge",
            "provider_public_dns_resolution_exactly_once_after_merge",
            "official_schedule_public_read_after_merge",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ),
        compute_budget=8000,
        time_budget=345600,
        expires_at=NOW + timedelta(days=1),
    )
    calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal calls
        calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    prepare_provider_network_binding_once_v1(
        workspace_receipt=workspace,
        mission_manifest=manifest,
        campaign_selection=_campaign_selection(workspace, manifest),
        output_path=control / "binding-first.json",
        resolver=resolver,
        clock=lambda: NOW,
    )
    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_RESOLUTION_ALREADY_CONSUMED",
    ):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding-second.json",
            resolver=resolver,
            clock=lambda: NOW,
        )
    assert calls == 1


def test_mission_global_claim_blocks_a_second_verified_workspace_before_dns(
    tmp_path: Path,
) -> None:
    first_parent = tmp_path / "first-runtime"
    second_parent = tmp_path / "second-runtime"
    first_parent.mkdir()
    second_parent.mkdir()
    first_workspace, first_control = _network_workspace(first_parent)
    second_workspace, second_control = _network_workspace(second_parent)
    manifest = _mission_manifest(NOW + timedelta(days=1))
    resolver_calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    prepare_provider_network_binding_once_v1(
        workspace_receipt=first_workspace,
        mission_manifest=manifest,
        campaign_selection=_campaign_selection(first_workspace, manifest),
        output_path=first_control / "binding.json",
        resolver=resolver,
        clock=lambda: NOW,
    )
    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_RESOLUTION_ALREADY_CONSUMED",
    ):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=second_workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(second_workspace, manifest),
            output_path=second_control / "binding.json",
            resolver=resolver,
            clock=lambda: NOW,
        )
    assert resolver_calls == 1
    assert not (second_control / "provider-network-resolution-one-shot-v1.json").exists()


def test_one_shot_binding_is_clamped_to_campaign_activation_ceiling(
    tmp_path: Path,
) -> None:
    workspace, control = _network_workspace(tmp_path)
    manifest = _mission_manifest(NOW + timedelta(days=1))
    selection = _campaign_selection(workspace, manifest)
    selected = selection.selected_candidate()
    binding_artifact = prepare_provider_network_binding_once_v1(
        workspace_receipt=workspace,
        mission_manifest=manifest,
        campaign_selection=selection,
        output_path=control / "binding.json",
        resolver=lambda *_arguments: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ],
        clock=lambda: NOW,
        binding_ttl_seconds=900,
    )
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    expected_ceiling = min(
        manifest.expires_at,
        selected.usable_expires_at_utc,
        earliest_kickoff - timedelta(minutes=5),
    )
    assert binding_artifact.expires_at_utc == expected_ceiling
    assert binding_artifact.binding_ttl_seconds == int((expected_ceiling - NOW).total_seconds())


def test_insufficient_owner_review_ttl_stops_before_claim_or_dns(tmp_path: Path) -> None:
    workspace, control = _network_workspace(tmp_path)
    manifest = _mission_manifest(NOW + timedelta(days=1))
    resolver_calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_OWNER_REVIEW_WINDOW_INSUFFICIENT",
    ):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding.json",
            resolver=resolver,
            clock=lambda: NOW,
            binding_ttl_seconds=60,
        )
    assert resolver_calls == 0
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()


def test_resolution_rechecks_mission_expiry_at_observed_boundary(tmp_path: Path) -> None:
    workspace, control = _network_workspace(tmp_path)
    manifest = _mission_manifest(NOW + timedelta(minutes=2))
    times = iter((NOW, NOW + timedelta(minutes=2)))
    resolver_calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    with pytest.raises(ProviderNetworkPreparationError, match="BOOTSTRAP_MISSION_EXPIRED"):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding.json",
            resolver=resolver,
            clock=lambda: next(times),
        )
    assert resolver_calls == 0
    assert (control / "provider-network-resolution-one-shot-v1.json").is_file()


def test_resolution_rechecks_claim_age_before_the_only_dns_operation(tmp_path: Path) -> None:
    workspace, control = _network_workspace(tmp_path)
    manifest = _mission_manifest(NOW + timedelta(days=1))
    times = iter((NOW, NOW + timedelta(minutes=1, microseconds=1)))
    resolver_calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_RESOLUTION_CLAIM_NOT_CURRENT",
    ):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding.json",
            resolver=resolver,
            clock=lambda: next(times),
        )
    assert resolver_calls == 0
    assert (control / "provider-network-resolution-one-shot-v1.json").is_file()


def test_control_root_replacement_after_claim_stops_before_dns(tmp_path: Path) -> None:
    workspace, control = _network_workspace(tmp_path)
    manifest = _mission_manifest(NOW + timedelta(days=1))
    retired = tmp_path / "retired-control-temp"
    clock_calls = 0
    resolver_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 2:
            control.rename(retired)
            control.mkdir()
        return NOW

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_WORKSPACE_IDENTITY_CHANGED",
    ):
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding.json",
            resolver=resolver,
            clock=clock,
        )
    assert resolver_calls == 0
    assert (retired / "provider-network-resolution-one-shot-v1.json").is_file()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()


def test_workspace_identity_replacement_stops_before_resolution(tmp_path: Path) -> None:
    workspace, control = _network_workspace(tmp_path)
    control.rename(tmp_path / "retired-control-temp")
    control.mkdir()
    resolver_calls = 0

    def resolver(*_arguments: object) -> list[tuple[object, ...]]:
        nonlocal resolver_calls
        resolver_calls += 1
        return []

    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_WORKSPACE_IDENTITY_CHANGED",
    ):
        manifest = _mission_manifest(NOW + timedelta(days=1))
        prepare_provider_network_binding_once_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=_campaign_selection(workspace, manifest),
            output_path=control / "binding.json",
            resolver=resolver,
            clock=lambda: NOW,
        )
    assert resolver_calls == 0
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()
