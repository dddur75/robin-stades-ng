from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from robin.capture.bootstrap_contracts import (
    FIRST_C0_CANARY_RANKING_POLICY,
    FIRST_C0_CANARY_SELECTION_REVISION,
    CampaignWindowCandidateV1,
    FirstC0CanarySelectionV1,
    FixtureTargetSetV1,
    OfficialFixtureTargetV1,
    OwnerReviewPackV1,
    ProviderNetworkBindingV1,
    ProviderNetworkResolutionClaimV1,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
    _first_c0_canary_candidate_rank_v1,
    load_campaign_selection_authority_v1,
)
from robin.capture.contracts import CaptureContractError, canonical_sha256
from robin.capture.official_schedule_sources import (
    LALIGA_BOOTSTRAP_URL,
    OfficialHttpResponse,
    SupportingOfficialRead,
)
from robin.capture.owner_review_pack import (
    build_owner_review_pack_v1,
    owner_authorization_statement_v1,
    write_owner_review_pack_v1,
)
from robin.capture.provider_network import (
    ProviderNetworkPreparationError,
    prepare_provider_network_binding_v1,
    reserve_provider_network_resolution_v1,
)

BASE = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
MAIN_SHA = "a" * 40
LALIGA_SOURCE = (
    "https://apim.laliga.com/public-service/api/v1/matches?"
    "subscription=laliga-easports-2026&competition=primera-division&limit=100&offset=300"
)
BUNDESLIGA_SOURCE = "https://datencenter.dfb.de/competitions/12/seasons/current"


def _load_canary_cli() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "data-sourcing"
        / "prepare_first_c0_canary_selection_v1.py"
    )
    specification = importlib.util.spec_from_file_location("first_c0_canary_cli_tests", path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


CANARY_CLI = _load_canary_cli()


def _load_data_sourcing_cli(filename: str, module_name: str) -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "tools" / "data-sourcing" / filename
    specification = importlib.util.spec_from_file_location(module_name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


PROVIDER_BINDING_CLI = _load_data_sourcing_cli(
    "prepare_provider_network_binding_v1.py",
    "first_c0_canary_provider_binding_cli_tests",
)
OWNER_PACK_CLI = _load_data_sourcing_cli(
    "build_owner_review_pack_v1.py",
    "first_c0_canary_owner_pack_cli_tests",
)


def mission_manifest(
    *, expires_at: datetime = BASE + timedelta(days=2)
) -> RealExecutionMissionManifestV1:
    return RealExecutionMissionManifestV1.issue(
        mission_id="REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1",
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
        source_hash="2451cd643c2d3ffcd3c5cc9fcd4a5f81f785978e0aa20429b4d182ceb9b1f22b",
        expires_at=expires_at,
    )


def workspace_receipt(tmp_path: Path) -> RealCaptureWorkspaceReceiptV1:
    repository = os.path.abspath(tmp_path / "repository")
    control = os.path.abspath(tmp_path / "control")
    capture = os.path.abspath(tmp_path / "capture")
    git_path = os.path.abspath(tmp_path / "git.exe")
    return RealCaptureWorkspaceReceiptV1.issue(
        authorized_main_sha=MAIN_SHA,
        bootstrap_mode="VERIFY",
        bootstrap_tool_source_repository_root=repository,
        bootstrap_tool_loaded_from_runtime_repository=True,
        bootstrap_package_source_repository_root=repository,
        bootstrap_package_loaded_from_runtime_repository=True,
        authority_eligible_for_real_execution=True,
        prepared_at_utc=BASE - timedelta(minutes=5),
        runtime_repository_root=repository,
        repository_root_fingerprint="1" * 64,
        repository_security_descriptor_sha256="2" * 64,
        control_temp_root=control,
        control_temp_fingerprint="3" * 64,
        control_temp_security_descriptor_sha256="4" * 64,
        capture_root=capture,
        capture_root_fingerprint="5" * 64,
        capture_security_descriptor_sha256="6" * 64,
        git_executable_path=git_path,
        git_executable_sha256="7" * 64,
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


def source_target_set(
    workspace: RealCaptureWorkspaceReceiptV1,
    *,
    kickoffs: tuple[datetime, ...] = (BASE + timedelta(minutes=135),),
    sport_key: str = "soccer_spain_la_liga",
    authority: str | None = None,
    created_at: datetime = BASE - timedelta(minutes=3),
    observed_at: datetime = BASE - timedelta(minutes=4),
) -> FixtureTargetSetV1:
    expected_authority = (
        authority
        if authority is not None
        else LALIGA_SOURCE
        if sport_key == "soccer_spain_la_liga"
        else BUNDESLIGA_SOURCE
    )
    competition = "LALIGA EA SPORTS" if sport_key == "soccer_spain_la_liga" else "Bundesliga"
    targets = tuple(
        OfficialFixtureTargetV1.issue(
            internal_fixture_target_id=f"canary-fixture-{index}",
            competition=competition,
            sport_key=sport_key,
            official_home_team=f"Home {index}",
            official_away_team=f"Away {index}",
            official_kickoff_utc=kickoff,
            official_source_authority=expected_authority,
            source_observed_at_utc=observed_at,
            source_evidence_sha256="f" * 64,
        )
        for index, kickoff in enumerate(kickoffs, start=1)
    )
    return FixtureTargetSetV1.issue(
        target_set_id=f"canary-source-{sport_key}",
        sport_key=sport_key,
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        created_at_utc=created_at,
        official_schedule_horizon_not_before_utc=BASE - timedelta(hours=1),
        official_schedule_horizon_expires_at_utc=BASE + timedelta(days=8),
        official_schedule_fixture_count=len(targets),
        official_schedule_completeness="OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON",
        targets=targets,
    )


def canary_selection(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
    *,
    target_sets: tuple[FixtureTargetSetV1, ...] | None = None,
    selected_at: datetime = BASE,
) -> FirstC0CanarySelectionV1:
    return FirstC0CanarySelectionV1.issue(
        selected_at_utc=selected_at,
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        workspace_prepared_at_utc=workspace.prepared_at_utc,
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        mission_expires_at_utc=manifest.expires_at,
        source_target_sets=target_sets or (source_target_set(workspace),),
    )


def test_nominal_single_laliga_h2_contract_is_one_call_one_credit(tmp_path: Path) -> None:
    workspace = workspace_receipt(tmp_path)
    selection = canary_selection(workspace, mission_manifest())
    selected = selection.selected_candidate()

    assert selection.schema_version == "robin-first-c0-canary-selection-v1"
    assert selection.selection_revision == FIRST_C0_CANARY_SELECTION_REVISION
    assert selection.purpose == "FIRST_REAL_CAPTURE_CANARY_ONLY"
    assert selection.ranking_policy == FIRST_C0_CANARY_RANKING_POLICY
    assert selection.source_target_set_count == selection.sport_key_count == 1
    assert selection.sport_key == "soccer_spain_la_liga"
    assert selected.window_id == "H2"
    assert selected.status == "OPEN_SELECTABLE"
    assert selected.request.sport_key == selection.sport_key
    assert selected.request.markets == selection.markets == ("h2h",)
    assert selected.request.region == selection.region == "eu"
    assert selected.one_call_http_ceiling == selection.maximum_http_calls == 1
    assert selected.one_call_credit_ceiling == selection.maximum_credits == 1
    assert selected.prior_admitted_fixture_count == 0
    assert selected.cross_league_corpus_value == 0
    assert selection.production_selection_authority is False
    assert selection.promotion_authority is False
    assert selection.batch_authority is False
    assert selection.scientific_edge_claim is False
    assert selection.selected_fixture_target_set_sha256 == (
        selected.fixture_target_set.canonical_set_hash
    )
    assert selection.canonical_selection_hash == canonical_sha256(selection.identity_material())


def test_exactly_one_official_target_set_and_one_sport_are_required(tmp_path: Path) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    laliga = source_target_set(workspace)
    bundesliga = source_target_set(
        workspace,
        sport_key="soccer_germany_bundesliga",
        kickoffs=(BASE + timedelta(minutes=130),),
    )
    common = {
        "selected_at_utc": BASE,
        "workspace_receipt_sha256": workspace.canonical_receipt_hash,
        "workspace_prepared_at_utc": workspace.prepared_at_utc,
        "mission_manifest_sha256": manifest.canonical_manifest_sha256(),
        "mission_expires_at_utc": manifest.expires_at,
    }
    with pytest.raises(
        ValueError,
        match="FIRST_C0_CANARY_SOURCE_TARGET_SET_COUNT_INVALID",
    ):
        FirstC0CanarySelectionV1.issue(**common, source_target_sets=())
    with pytest.raises(
        ValueError,
        match="FIRST_C0_CANARY_SOURCE_TARGET_SET_COUNT_INVALID",
    ):
        FirstC0CanarySelectionV1.issue(
            **common,
            source_target_sets=(laliga, bundesliga),
        )


def test_official_source_staleness_forgery_and_kickoff_past_are_rejected(
    tmp_path: Path,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    stale = source_target_set(
        workspace,
        created_at=BASE - timedelta(minutes=31),
        observed_at=BASE - timedelta(minutes=32),
        kickoffs=(BASE + timedelta(hours=3),),
    )
    with pytest.raises(ValueError, match="CAPTURE_CONTRACT_INVALID"):
        canary_selection(workspace, manifest, target_sets=(stale,))

    forged = source_target_set(
        workspace,
        authority="https://fixtures.example.test/not-official",
    )
    with pytest.raises(ValueError, match="CAPTURE_CONTRACT_INVALID"):
        canary_selection(workspace, manifest, target_sets=(forged,))

    passed = source_target_set(
        workspace,
        kickoffs=(BASE - timedelta(minutes=1),),
    )
    with pytest.raises(
        ValueError,
        match="FIRST_C0_CANARY_NO_REMAINING_SELECTABLE_CANDIDATE",
    ):
        canary_selection(workspace, manifest, target_sets=(passed,))


def test_temporal_statuses_roll_without_backdating_and_margin_is_required(
    tmp_path: Path,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    future = canary_selection(
        workspace,
        manifest,
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(BASE + timedelta(hours=3),),
            ),
        ),
    )
    assert future.selected_candidate().status == "FUTURE_NOT_OPEN"
    assert future.selected_ready_at_selection is False
    with pytest.raises(
        ValueError,
        match="FIRST_C0_CANARY_SELECTED_CANDIDATE_NOT_OPEN",
    ):
        future.assert_selected_candidate_current(BASE)

    rollover = canary_selection(
        workspace,
        manifest,
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(
                    BASE + timedelta(minutes=119),
                    BASE + timedelta(hours=3),
                ),
            ),
        ),
    )
    assert any(candidate.status == "MISSED_NOT_BACKDATED" for candidate in rollover.candidates)
    assert rollover.selected_candidate().status == "FUTURE_NOT_OPEN"

    short_manifest = mission_manifest(expires_at=BASE + timedelta(seconds=60))
    with pytest.raises(
        ValueError,
        match="FIRST_C0_CANARY_NO_REMAINING_SELECTABLE_CANDIDATE",
    ):
        canary_selection(workspace, short_manifest)


def test_intrinsically_short_h2_clique_is_never_selected_for_canary_execution(
    tmp_path: Path,
) -> None:
    workspace = workspace_receipt(tmp_path)
    selection = canary_selection(
        workspace,
        mission_manifest(),
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(
                    BASE + timedelta(minutes=140),
                    BASE + timedelta(minutes=149),
                ),
            ),
        ),
    )
    short_cliques = tuple(
        candidate
        for candidate in selection.candidates
        if candidate.window_id == "H2"
        and candidate.fixture_coverage == 2
        and candidate.timing_margin_seconds < 840
    )
    assert short_cliques
    selected = selection.selected_candidate()
    assert selected.timing_margin_seconds >= 840
    assert selected.fixture_coverage == 1


def _changed_candidate(
    candidate: CampaignWindowCandidateV1,
    **updates: object,
) -> CampaignWindowCandidateV1:
    return candidate.model_copy(update=updates)


def test_canary_ranking_is_coverage_protocol_margin_readiness_then_hash(
    tmp_path: Path,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    coverage_selection = canary_selection(
        workspace,
        manifest,
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(
                    BASE + timedelta(hours=25),
                    BASE + timedelta(hours=25, minutes=20),
                ),
            ),
        ),
    )
    assert coverage_selection.selected_candidate().window_id == "H24"
    assert coverage_selection.selected_candidate().fixture_coverage == 2

    protocol_selection = canary_selection(
        workspace,
        manifest,
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(BASE + timedelta(hours=25),),
            ),
        ),
    )
    assert protocol_selection.selected_candidate().window_id == "H2"

    readiness_selection = canary_selection(
        workspace,
        manifest,
        target_sets=(
            source_target_set(
                workspace,
                kickoffs=(
                    BASE + timedelta(hours=3),
                    BASE + timedelta(hours=4),
                ),
            ),
        ),
    )
    assert readiness_selection.selected_candidate().window_not_before_utc == (
        BASE + timedelta(minutes=45)
    )

    candidate = readiness_selection.selected_candidate()
    higher_coverage = _changed_candidate(
        candidate,
        fixture_coverage=candidate.fixture_coverage + 1,
    )
    higher_protocol = _changed_candidate(
        candidate,
        protocol_role_value=candidate.protocol_role_value + 1,
    )
    no_margin = _changed_candidate(candidate, timing_margin_seconds=0)
    later = _changed_candidate(
        candidate,
        window_not_before_utc=candidate.window_not_before_utc + timedelta(minutes=1),
    )
    higher_hash = _changed_candidate(candidate, stable_group_hash="f" * 64)
    assert _first_c0_canary_candidate_rank_v1(higher_coverage) < (
        _first_c0_canary_candidate_rank_v1(candidate)
    )
    assert _first_c0_canary_candidate_rank_v1(higher_protocol) < (
        _first_c0_canary_candidate_rank_v1(candidate)
    )
    assert _first_c0_canary_candidate_rank_v1(candidate) < (
        _first_c0_canary_candidate_rank_v1(no_margin)
    )
    assert _first_c0_canary_candidate_rank_v1(candidate) < (
        _first_c0_canary_candidate_rank_v1(later)
    )
    if candidate.stable_group_hash < higher_hash.stable_group_hash:
        assert _first_c0_canary_candidate_rank_v1(candidate) < (
            _first_c0_canary_candidate_rank_v1(higher_hash)
        )


def test_discriminated_loader_accepts_only_exact_known_schema(tmp_path: Path) -> None:
    selection = canary_selection(workspace_receipt(tmp_path), mission_manifest())
    loaded = load_campaign_selection_authority_v1(selection.model_dump(mode="json"))
    assert isinstance(loaded, FirstC0CanarySelectionV1)
    assert loaded == selection
    for payload, code in (
        ([], "CAMPAIGN_SELECTION_AUTHORITY_PAYLOAD_INVALID"),
        ({"schema_version": "unknown"}, "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED"),
        ({}, "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED"),
    ):
        with pytest.raises(CaptureContractError, match=code):
            load_campaign_selection_authority_v1(payload)
    tampered = selection.model_dump(mode="json")
    tampered["production_selection_authority"] = True
    with pytest.raises(
        CaptureContractError,
        match="FIRST_C0_CANARY_SELECTION_AUTHORITY_INVALID",
    ):
        load_campaign_selection_authority_v1(tampered)

    class DuckSelection:
        schema_version = selection.schema_version

        def model_dump(self) -> dict[str, object]:
            return selection.model_dump(mode="json")

    for duck_payload in (selection, DuckSelection()):
        with pytest.raises(
            CaptureContractError,
            match="CAMPAIGN_SELECTION_AUTHORITY_PAYLOAD_INVALID",
        ):
            load_campaign_selection_authority_v1(duck_payload)

    canary_masquerading_as_five_league = selection.model_dump(mode="json")
    canary_masquerading_as_five_league["schema_version"] = "robin-campaign-window-selection-v1"
    with pytest.raises(
        CaptureContractError,
        match="CAMPAIGN_WINDOW_SELECTION_AUTHORITY_INVALID",
    ):
        load_campaign_selection_authority_v1(canary_masquerading_as_five_league)

    five_league_masquerading_as_canary = {
        "schema_version": "robin-first-c0-canary-selection-v1",
        "selection_revision": "complete-five-league-interval-clique-ranking-v2",
        "source_target_sets": [],
    }
    with pytest.raises(
        CaptureContractError,
        match="FIRST_C0_CANARY_SELECTION_AUTHORITY_INVALID",
    ):
        load_campaign_selection_authority_v1(five_league_masquerading_as_canary)


def test_provider_binding_and_owner_pack_clis_accept_exact_canary_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    selection = canary_selection(workspace, manifest, selected_at=BASE)
    selected = selection.selected_candidate()
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        campaign_selection_sha256=selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=manifest.expires_at,
    )
    binding = ProviderNetworkBindingV1.issue(
        resolution_claim=claim,
        resolver_identity="SYNTHETIC_CLI_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=14),
        binding_ttl_seconds=900,
        resolved_ip_addresses=("8.8.8.8",),
    )
    control = Path(workspace.control_temp_root)
    control.mkdir()
    workspace_path = control / "workspace.json"
    manifest_path = control / "manifest.json"
    selection_path = control / "selection.json"
    binding_path = control / "binding.json"
    provider_output = control / "provider-output.json"
    pack_output = control / "owner-pack"
    payloads: dict[Path, object] = {
        workspace_path: workspace.model_dump(mode="json"),
        selection_path: selection.model_dump(mode="json"),
        binding_path: binding.model_dump(mode="json"),
    }

    observed_provider_selection: list[FirstC0CanarySelectionV1] = []

    def fake_prepare_binding(**kwargs: object) -> ProviderNetworkBindingV1:
        campaign_selection = kwargs["campaign_selection"]
        assert isinstance(campaign_selection, FirstC0CanarySelectionV1)
        observed_provider_selection.append(campaign_selection)
        return binding

    monkeypatch.setattr(
        PROVIDER_BINDING_CLI,
        "parse_args",
        lambda: SimpleNamespace(
            workspace_receipt=workspace_path,
            mission_manifest=manifest_path,
            campaign_selection=selection_path,
            output=provider_output,
            binding_ttl_seconds=900,
        ),
    )
    monkeypatch.setattr(PROVIDER_BINDING_CLI, "_load", lambda path: payloads[path])
    monkeypatch.setattr(
        PROVIDER_BINDING_CLI,
        "assert_real_capture_workspace_receipt_current_v1",
        lambda _workspace: None,
    )
    monkeypatch.setattr(
        PROVIDER_BINDING_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(
        PROVIDER_BINDING_CLI,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: manifest,
    )
    monkeypatch.setattr(
        PROVIDER_BINDING_CLI,
        "prepare_provider_network_binding_once_v1",
        fake_prepare_binding,
    )
    payloads[selection_path] = {"schema_version": "unknown-selection-schema"}
    assert PROVIDER_BINDING_CLI.main() == 2
    rejected_provider = json.loads(capsys.readouterr().out)
    assert rejected_provider == {
        "code": "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED",
        "status": "FAILED",
    }
    assert observed_provider_selection == []
    assert not provider_output.exists()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()

    payloads[selection_path] = selection.model_dump(mode="json")
    assert PROVIDER_BINDING_CLI.main() == 0
    provider_result = json.loads(capsys.readouterr().out)
    assert provider_result["status"] == "BOUND"
    assert observed_provider_selection == [selection]
    assert provider_result["campaign_selection_sha256"] == selection.canonical_selection_hash

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return BASE

    monkeypatch.setattr(
        OWNER_PACK_CLI,
        "_parser",
        lambda: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                workspace_receipt=workspace_path,
                mission_manifest=manifest_path,
                provider_network_binding=binding_path,
                campaign_selection=selection_path,
                output_directory=pack_output,
            )
        ),
    )
    monkeypatch.setattr(OWNER_PACK_CLI, "_load", lambda path: payloads[path])
    monkeypatch.setattr(OWNER_PACK_CLI, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        OWNER_PACK_CLI,
        "assert_real_capture_workspace_receipt_current_v1",
        lambda _workspace: None,
    )
    monkeypatch.setattr(
        OWNER_PACK_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(
        OWNER_PACK_CLI,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: manifest,
    )
    monkeypatch.setattr(
        OWNER_PACK_CLI,
        "assert_owner_review_pack_completion_current_v1",
        lambda _pack, _observed_at: None,
    )
    original_pack_builder = OWNER_PACK_CLI.build_owner_review_pack_v1
    original_pack_writer = OWNER_PACK_CLI.write_owner_review_pack_v1
    pack_build_calls = 0
    pack_write_calls = 0

    def observed_pack_builder(**kwargs: object) -> OwnerReviewPackV1:
        nonlocal pack_build_calls
        pack_build_calls += 1
        return original_pack_builder(**kwargs)

    def observed_pack_writer(output: Path, pack: OwnerReviewPackV1) -> object:
        nonlocal pack_write_calls
        pack_write_calls += 1
        return original_pack_writer(output, pack)

    monkeypatch.setattr(OWNER_PACK_CLI, "build_owner_review_pack_v1", observed_pack_builder)
    monkeypatch.setattr(OWNER_PACK_CLI, "write_owner_review_pack_v1", observed_pack_writer)
    payloads[selection_path] = {}
    assert OWNER_PACK_CLI.main() == 2
    rejected_pack = json.loads(capsys.readouterr().out)
    assert rejected_pack == {
        "code": "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED",
        "status": "FAILED",
    }
    assert pack_build_calls == pack_write_calls == 0
    assert not pack_output.exists()

    payloads[selection_path] = selection.model_dump(mode="json")
    assert OWNER_PACK_CLI.main() == 0
    pack_result = json.loads(capsys.readouterr().out)
    assert pack_result["status"] == "OWNER_AUTHORIZATION_READY"
    assert pack_result["campaign_selection_sha256"] == selection.canonical_selection_hash
    pack = OwnerReviewPackV1.model_validate_json(
        Path(pack_result["outputs"]["owner_review_pack"]).read_bytes()
    )
    assert isinstance(pack.campaign_selection, FirstC0CanarySelectionV1)
    assert pack.campaign_selection == selection
    assert pack_build_calls == pack_write_calls == 1


def test_injected_dns_is_once_exact_and_system_resolver_is_never_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    selection = canary_selection(workspace, manifest, selected_at=BASE - timedelta(minutes=2))
    selected = selection.selected_candidate()
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        campaign_selection_sha256=selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=manifest.expires_at,
    )
    system_calls = 0

    def forbidden_system_resolver(*_args: object, **_kwargs: object) -> object:
        nonlocal system_calls
        system_calls += 1
        raise AssertionError("TEST_REAL_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_system_resolver)
    resolver_calls: list[tuple[object, ...]] = []

    def resolver(*args: object) -> tuple[tuple[object, ...], ...]:
        resolver_calls.append(args)
        return (
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", 443),
            ),
        )

    binding = prepare_provider_network_binding_v1(
        resolution_claim=claim,
        resolver=resolver,
        observed_at_utc=BASE - timedelta(minutes=1),
        binding_ttl_seconds=900,
        resolver_identity="SYNTHETIC_INJECTED_RESOLVER",
    )
    assert len(resolver_calls) == 1
    assert system_calls == 0
    assert binding.resolution_operations == 1
    assert binding.resolution_claim.campaign_selection_sha256 == (
        selection.canonical_selection_hash
    )
    assert binding.resolution_claim.fixture_target_set_sha256 == (
        selected.fixture_target_set.canonical_set_hash
    )
    assert binding.provider_tcp_connections == binding.provider_http_requests == 0
    assert binding.provider_secret_reads == 0


def test_canary_840_second_gate_rejects_before_marker_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    selection = canary_selection(workspace, manifest)
    output = tmp_path / "binding.json"
    writes = 0

    monkeypatch.setattr(
        "robin.capture.provider_network._validated_control_destination",
        lambda _workspace, _output: (tmp_path, output),
    )

    def write_forbidden(*_args: object, **_kwargs: object) -> None:
        nonlocal writes
        writes += 1

    monkeypatch.setattr(
        "robin.capture.provider_network._write_resolution_claim_marker_v1",
        write_forbidden,
    )
    with pytest.raises(
        ProviderNetworkPreparationError,
        match="PROVIDER_NETWORK_OWNER_REVIEW_WINDOW_INSUFFICIENT",
    ):
        reserve_provider_network_resolution_v1(
            workspace_receipt=workspace,
            mission_manifest=manifest,
            campaign_selection=selection,
            output_path=output,
            clock=lambda: BASE,
            binding_ttl_seconds=839,
        )
    assert writes == 0


def test_synthetic_canary_pack_has_11_recomputable_artifacts_and_no_authority(
    tmp_path: Path,
) -> None:
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    selection = canary_selection(workspace, manifest, selected_at=BASE - timedelta(minutes=2))
    selected = selection.selected_candidate()
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        campaign_selection_sha256=selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=manifest.expires_at,
    )
    binding = prepare_provider_network_binding_v1(
        resolution_claim=claim,
        resolver=lambda *_args: (
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("8.8.8.8", 443),
            ),
        ),
        observed_at_utc=BASE - timedelta(minutes=1),
        binding_ttl_seconds=900,
        resolver_identity="SYNTHETIC_INJECTED_RESOLVER",
    )
    request_hash = canonical_sha256(selected.request.fingerprint_material())
    generated_text = BASE.isoformat().replace("+00:00", "Z")
    nonce_hash = canonical_sha256(
        {
            "workspace": workspace.canonical_receipt_hash,
            "binding": binding.canonical_binding_hash,
            "targets": selected.fixture_target_set.canonical_set_hash,
            "campaign_selection": selection.canonical_selection_hash,
            "request": request_hash,
            "generated_at": generated_text,
        }
    )
    owner_nonce = f"owner-{nonce_hash[:40]}"
    activation_nonce = f"activation-{nonce_hash[24:64]}"
    pack = build_owner_review_pack_v1(
        workspace_receipt=workspace,
        mission_manifest=manifest,
        provider_network_binding=binding,
        campaign_selection=selection,
        generated_at_utc=BASE,
        authorization_nonce=owner_nonce,
        activation_nonce=activation_nonce,
    )
    round_trip = OwnerReviewPackV1.model_validate(pack.model_dump(mode="json"))
    assert isinstance(round_trip.campaign_selection, FirstC0CanarySelectionV1)
    assert round_trip.campaign_selection == selection
    assert pack.canonical_pack_hash == canonical_sha256(pack.identity_material())
    assert pack.owner_authorization_candidate.canonical_authorization_hash == canonical_sha256(
        pack.owner_authorization_candidate.identity_material()
    )
    assert pack.activation_candidate.canonical_activation_hash == canonical_sha256(
        pack.activation_candidate.identity_material()
    )
    assert pack.owner_authorization_candidate.authorization_nonce == owner_nonce
    assert pack.activation_candidate.activation_nonce == activation_nonce
    assert pack.owner_authorization_candidate.authorization_status == "OWNER_REVIEW_CANDIDATE"
    assert pack.owner_authorization_candidate.review_candidate_sha256 is None
    assert pack.owner_authorization_candidate.maximum_http_calls == 1
    assert pack.owner_authorization_candidate.maximum_credits == 1
    assert pack.owner_authorization_candidate.maximum_plan_items == 1
    assert pack.provider_http_calls == pack.real_secret_reads == pack.real_capture_calls == 0
    output = tmp_path / "owner-review-pack"
    output.mkdir()
    paths = write_owner_review_pack_v1(output, pack)
    assert len(paths) == 11
    assert set(paths) == {
        "owner_review_pack",
        "owner_authorization_candidate",
        "activation_candidate",
        "plan_candidate",
        "plan_item_candidate",
        "campaign_selection",
        "fixture_target_set",
        "provider_network_binding",
        "mission_manifest",
        "workspace_receipt",
        "request",
    }
    assert all(path.is_file() for path in paths.values())
    statement = owner_authorization_statement_v1(pack)
    for literal in (
        "SELECTION_SCHEMA=robin-first-c0-canary-selection-v1",
        "SELECTION_PURPOSE=FIRST_REAL_CAPTURE_CANARY_ONLY",
        "SOURCE_TARGET_SET_COUNT=1",
        "PRODUCTION_SELECTION_AUTHORITY=false",
        "PROMOTION_AUTHORITY=false",
        "BATCH_AUTHORITY=false",
        "SCIENTIFIC_EDGE_CLAIM=false",
    ):
        assert literal in statement


def _source_plan_bytes(sport_key: str, adapter: str, url: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "robin-first-c0-canary-source-plan-v1",
            "sport_key": sport_key,
            "adapter": adapter,
            "url": url,
        },
        sort_keys=True,
    ).encode()


def _round_robin_rounds(clubs: list[str], count: int) -> list[list[tuple[str, str]]]:
    rotating = list(clubs)
    rounds: list[list[tuple[str, str]]] = []
    for _ in range(count):
        rounds.append(
            [(rotating[index], rotating[-index - 1]) for index in range(len(rotating) // 2)]
        )
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    return rounds


def _laliga_payload() -> bytes:
    matches: list[dict[str, object]] = []
    latest = datetime(2026, 9, 7, 21, 0, tzinfo=UTC)
    clubs = [f"Liga Club {index:02d}" for index in range(20)]
    for week_index, games in enumerate(_round_robin_rounds(clubs, 8), start=1):
        for game_index, (home, away) in enumerate(games):
            matches.append(
                {
                    "id": f"laliga-{len(matches):03d}",
                    "competition": {"slug": "primera-division"},
                    "date": (latest - timedelta(days=week_index - 1, minutes=game_index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "home_team": {"name": home},
                    "away_team": {"name": away},
                    "gameweek": {"week": week_index},
                }
            )
    return json.dumps({"total": 380, "matches": matches}, sort_keys=True).encode()


def _bundesliga_payload() -> bytes:
    sections: list[str] = []
    base = datetime(2026, 8, 29, 15, 30)
    weekdays = {
        0: "Montag",
        1: "Dienstag",
        2: "Mittwoch",
        3: "Donnerstag",
        4: "Freitag",
        5: "Samstag",
        6: "Sonntag",
    }
    clubs = [f"Bund Club {index:02d}" for index in range(18)]
    rounds = _round_robin_rounds(clubs, 5)
    fixture_index = 0
    for matchday in range(1, 35):
        rows: list[str] = []
        if matchday <= 5:
            for game_index, (home, away) in enumerate(rounds[matchday - 1]):
                kickoff = base + timedelta(days=matchday - 1, minutes=game_index)
                rows.append(
                    '<div class="c-MatchTable-row">'
                    f'<span id="match_{1000 + fixture_index}"></span>'
                    f"{weekdays[kickoff.weekday()]}, {kickoff.strftime('%d.%m.%Y %H:%M')} Uhr"
                    '<div class="c-MatchTable-team--home"><a href="#">'
                    f"{home}</a></div>"
                    '<div class="c-MatchTable-team--away"><a href="#">'
                    f"{away}</a></div></div>"
                )
                fixture_index += 1
        sections.append(f"<h2>{matchday}. Spieltag</h2>{''.join(rows)}")
    return f"Bundesliga 2026/27 der Spielplan{''.join(sections)}".encode()


def test_cli_pipeline_publishes_one_immutable_selection_bundle_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = tmp_path / "control"
    control.mkdir()
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest(expires_at=BASE + timedelta(days=10))
    plan_bytes = _source_plan_bytes(
        "soccer_spain_la_liga",
        "LALIGA_PUBLIC_MATCHES_JSON_V1",
        LALIGA_SOURCE,
    )
    raw = _laliga_payload()
    supporting_raw = b"<html>public LaLiga bootstrap</html>"
    supporting = SupportingOfficialRead(
        requested_url=LALIGA_BOOTSTRAP_URL,
        final_url=LALIGA_BOOTSTRAP_URL,
        official_domain="www.laliga.com",
        status_code=200,
        content_type="text/html",
        byte_count=len(supporting_raw),
        raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
        redirect_chain=(),
    )
    fetch_calls = 0

    class SyntheticFetcher:
        def fetch(self, source: object) -> OfficialHttpResponse:
            nonlocal fetch_calls
            fetch_calls += 1
            return OfficialHttpResponse(
                status_code=200,
                final_url=getattr(source, "url"),
                content_type="application/json",
                body=raw,
                supporting_official_reads=(supporting,),
                supporting_official_raw_bytes=(supporting_raw,),
            )

    tick = BASE

    def clock() -> datetime:
        nonlocal tick
        observed = tick
        tick += timedelta(seconds=1)
        return observed

    monkeypatch.setattr(
        CANARY_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    result = CANARY_CLI.prepare_first_c0_canary_selection_v1(
        workspace_receipt=workspace,
        workspace_receipt_bytes=workspace.model_dump_json().encode(),
        mission_manifest=manifest,
        mission_manifest_bytes=manifest.model_dump_json().encode(),
        source_plan_bytes=plan_bytes,
        output_directory=control / "canary-bundle",
        fetcher=SyntheticFetcher(),
        clock=clock,
        workspace_validator=lambda _workspace: None,
        marker_inspector=lambda _workspace, _manifest: {
            "schema_version": "synthetic-marker-inspection-v1",
            "local_marker_present": False,
            "global_marker_present": False,
            "inspected_read_only": True,
        },
    )
    assert fetch_calls == 1
    assert result.official_reads == 2
    assert result.cycle_index == 1
    assert result.cumulative_official_reads == 2
    assert result.supporting_official_reads == 1
    assert result.status in {"CANARY_READY_NOW", "CANARY_FUTURE_WINDOW"}
    assert result.selection.source_target_set_count == 1
    assert result.selection.sport_key == "soccer_spain_la_liga"
    names = {path.name for path in result.bundle_directory.iterdir()}
    assert {
        "workspace-receipt.json",
        "mission-manifest.json",
        "source-plan.json",
        "official-source-raw.bin",
        "official-supporting-source-raw-1.bin",
        "official-fetch-receipt.json",
        "official-schedule-evidence.json",
        "fixture-target-set.json",
        "first-c0-canary-selection.json",
        "marker-inspection.json",
        "preparation-counters.json",
        "current-cycle-read-reservation.json",
        "bundle-manifest.json",
    } == names
    manifest_payload = json.loads((result.bundle_directory / "bundle-manifest.json").read_bytes())
    for name, expected_hash in manifest_payload["artifact_sha256"].items():
        assert (
            hashlib.sha256((result.bundle_directory / name).read_bytes()).hexdigest()
            == expected_hash
        )
    assert manifest_payload["provider_dns"] == 0
    assert manifest_payload["provider_http"] == 0
    assert manifest_payload["secret_reads"] == 0
    assert (control / "first-c0-canary-cycle-01-read-reservation-v1.json").is_file()
    assert (control / "first-c0-canary-cycle-01-attempt-receipt-v1.json").is_file()


def test_laliga_future_window_refreshes_before_open_within_global_cycle_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = tmp_path / "control"
    control.mkdir()
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest(expires_at=BASE + timedelta(days=10))
    plan_bytes = _source_plan_bytes(
        "soccer_spain_la_liga",
        "LALIGA_PUBLIC_MATCHES_JSON_V1",
        LALIGA_SOURCE,
    )
    raw = _laliga_payload()
    supporting_raw = b"<html>public LaLiga bootstrap</html>"
    supporting = SupportingOfficialRead(
        requested_url=LALIGA_BOOTSTRAP_URL,
        final_url=LALIGA_BOOTSTRAP_URL,
        official_domain="www.laliga.com",
        status_code=200,
        content_type="text/html",
        byte_count=len(supporting_raw),
        raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
        redirect_chain=(),
    )
    fetch_calls = 0

    class SyntheticFetcher:
        def fetch(self, source: object) -> OfficialHttpResponse:
            nonlocal fetch_calls
            fetch_calls += 1
            return OfficialHttpResponse(
                status_code=200,
                final_url=getattr(source, "url"),
                content_type="application/json",
                body=raw,
                supporting_official_reads=(supporting,),
                supporting_official_raw_bytes=(supporting_raw,),
            )

    tick = BASE

    def clock() -> datetime:
        nonlocal tick
        observed = tick
        tick += timedelta(seconds=1)
        return observed

    monkeypatch.setattr(
        CANARY_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    common = {
        "workspace_receipt": workspace,
        "workspace_receipt_bytes": workspace.model_dump_json().encode(),
        "mission_manifest": manifest,
        "mission_manifest_bytes": manifest.model_dump_json().encode(),
        "source_plan_bytes": plan_bytes,
        "fetcher": SyntheticFetcher(),
        "clock": clock,
        "workspace_validator": lambda _workspace: None,
        "marker_inspector": lambda _workspace, _manifest: {
            "local_marker_present": False,
            "global_marker_present": False,
            "inspected_read_only": True,
        },
    }
    first = CANARY_CLI.prepare_first_c0_canary_selection_v1(
        **common,
        output_directory=control / "cycle-1-bundle",
    )
    assert first.status == "CANARY_FUTURE_WINDOW"
    assert first.cycle_index == 1
    assert first.cumulative_official_reads == 2
    tick = first.recommended_refresh_utc
    second = CANARY_CLI.prepare_first_c0_canary_selection_v1(
        **common,
        output_directory=control / "cycle-2-bundle",
    )
    assert second.status == "CANARY_FUTURE_WINDOW"
    assert second.cycle_index == 2
    assert second.cumulative_official_reads == 4
    assert fetch_calls == 2
    names = {path.name for path in second.bundle_directory.iterdir()}
    assert "prior-cycle-01-read-reservation.json" in names
    assert "prior-cycle-01-attempt-receipt.json" in names
    assert "current-cycle-read-reservation.json" in names
    tick = second.selection.selected_not_before_utc
    second.selection.assert_selected_candidate_current(tick)
    assert fetch_calls == 2


def test_single_source_plan_is_strict_and_bundesliga_requires_primary_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    laliga_bytes = _source_plan_bytes(
        "soccer_spain_la_liga",
        "LALIGA_PUBLIC_MATCHES_JSON_V1",
        LALIGA_SOURCE,
    )
    plan = CANARY_CLI.load_first_c0_canary_source_plan_v1(laliga_bytes)
    assert plan.source.sport_key == "soccer_spain_la_liga"
    assert len(plan.canonical_sha256) == 64
    bad_offset = laliga_bytes.replace(b"offset=300", b"offset=200")
    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID",
    ):
        CANARY_CLI.load_first_c0_canary_source_plan_v1(bad_offset)
    extra_query = laliga_bytes.replace(b"offset=300", b"offset=300&extra=1")
    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID",
    ):
        CANARY_CLI.load_first_c0_canary_source_plan_v1(extra_query)
    bad_dfb_path = _source_plan_bytes(
        "soccer_germany_bundesliga",
        "DFB_DATACENTER_HTML_V1",
        f"{BUNDESLIGA_SOURCE}/extra",
    )
    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_SOURCE_PLAN_AUTHORITY_INVALID",
    ):
        CANARY_CLI.load_first_c0_canary_source_plan_v1(bad_dfb_path)

    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    bundesliga_bytes = _source_plan_bytes(
        "soccer_germany_bundesliga",
        "DFB_DATACENTER_HTML_V1",
        BUNDESLIGA_SOURCE,
    )
    monkeypatch.setattr(
        CANARY_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    fetch_calls = 0

    class ForbiddenFetcher:
        def fetch(self, _source: object) -> object:
            nonlocal fetch_calls
            fetch_calls += 1
            raise AssertionError("FALLBACK_FETCH_BEFORE_PRIMARY_RECEIPT")

    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_PRIMARY_SOURCE_REQUIRED_FIRST",
    ):
        CANARY_CLI.prepare_first_c0_canary_selection_v1(
            workspace_receipt=workspace,
            workspace_receipt_bytes=workspace.model_dump_json().encode(),
            mission_manifest=manifest,
            mission_manifest_bytes=manifest.model_dump_json().encode(),
            source_plan_bytes=bundesliga_bytes,
            output_directory=tmp_path / "bundle",
            fetcher=ForbiddenFetcher(),
            workspace_validator=lambda _workspace: None,
            marker_inspector=lambda _workspace, _manifest: {
                "local_marker_present": False,
                "global_marker_present": False,
                "inspected_read_only": True,
            },
        )
    assert fetch_calls == 0


def test_failed_no_fallback_receipt_cannot_authorize_a_bundesliga_read() -> None:
    laliga_plan = CANARY_CLI.load_first_c0_canary_source_plan_v1(
        _source_plan_bytes(
            "soccer_spain_la_liga",
            "LALIGA_PUBLIC_MATCHES_JSON_V1",
            LALIGA_SOURCE,
        )
    )
    bundesliga_plan = CANARY_CLI.load_first_c0_canary_source_plan_v1(
        _source_plan_bytes(
            "soccer_germany_bundesliga",
            "DFB_DATACENTER_HTML_V1",
            BUNDESLIGA_SOURCE,
        )
    )
    history = (
        CANARY_CLI.FirstC0CanaryCycleHistoryV1(
            cycle_index=1,
            reservation={},
            receipt={
                "sport_key": "soccer_spain_la_liga",
                "source_plan_sha256": laliga_plan.canonical_sha256,
                "cumulative_official_reads": 2,
                "status": "FAILED_NO_FALLBACK",
                "failure_classification": "DETERMINISTIC",
                "fallback_category": None,
            },
            reservation_bytes=b"reservation",
            receipt_bytes=b"receipt",
            receipt_sha256="0" * 64,
        ),
    )

    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_FALLBACK_NOT_AUTHORIZED",
    ):
        CANARY_CLI._next_cycle_authority(
            history,
            bundesliga_plan,
            started_at_utc=BASE,
        )


def test_deterministic_primary_rejection_falls_back_and_refreshes_with_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = tmp_path / "control"
    control.mkdir()
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest(expires_at=BASE + timedelta(days=10))
    laliga_plan = _source_plan_bytes(
        "soccer_spain_la_liga",
        "LALIGA_PUBLIC_MATCHES_JSON_V1",
        LALIGA_SOURCE,
    )
    bundesliga_plan = _source_plan_bytes(
        "soccer_germany_bundesliga",
        "DFB_DATACENTER_HTML_V1",
        BUNDESLIGA_SOURCE,
    )
    tick = BASE

    def clock() -> datetime:
        nonlocal tick
        observed = tick
        tick += timedelta(seconds=1)
        return observed

    monkeypatch.setattr(
        CANARY_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    shared = {
        "workspace_receipt": workspace,
        "workspace_receipt_bytes": workspace.model_dump_json().encode(),
        "mission_manifest": manifest,
        "mission_manifest_bytes": manifest.model_dump_json().encode(),
        "clock": clock,
        "workspace_validator": lambda _workspace: None,
        "marker_inspector": lambda _workspace, _manifest: {
            "local_marker_present": False,
            "global_marker_present": False,
            "inspected_read_only": True,
        },
    }

    class DeterministicRejectedFetcher:
        def fetch(self, source: object) -> OfficialHttpResponse:
            return OfficialHttpResponse(
                status_code=403,
                final_url=getattr(source, "url"),
                content_type="application/json",
                body=b"forbidden",
            )

    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="OFFICIAL_SOURCE_HTTP_STATUS_INVALID",
    ):
        CANARY_CLI.prepare_first_c0_canary_selection_v1(
            **shared,
            source_plan_bytes=laliga_plan,
            output_directory=control / "cycle-1-rejected",
            fetcher=DeterministicRejectedFetcher(),
        )
    primary_receipt = json.loads(
        (control / "first-c0-canary-cycle-01-attempt-receipt-v1.json").read_bytes()
    )
    assert primary_receipt["failure_classification"] == "DETERMINISTIC"
    assert primary_receipt["http_status"] == 403
    assert primary_receipt["cumulative_official_reads"] == 2

    bundesliga_raw = _bundesliga_payload()

    class BundesligaFetcher:
        def fetch(self, source: object) -> OfficialHttpResponse:
            return OfficialHttpResponse(
                status_code=200,
                final_url=getattr(source, "url"),
                content_type="text/html",
                body=bundesliga_raw,
            )

    fallback = CANARY_CLI.prepare_first_c0_canary_selection_v1(
        **shared,
        source_plan_bytes=bundesliga_plan,
        output_directory=control / "cycle-2-fallback",
        fetcher=BundesligaFetcher(),
    )
    assert fallback.status == "CANARY_FUTURE_WINDOW"
    assert fallback.cycle_index == 2
    assert fallback.cumulative_official_reads == 3
    tick = fallback.recommended_refresh_utc
    refreshed = CANARY_CLI.prepare_first_c0_canary_selection_v1(
        **shared,
        source_plan_bytes=bundesliga_plan,
        output_directory=control / "cycle-3-fallback-refresh",
        fetcher=BundesligaFetcher(),
    )
    assert refreshed.status == "CANARY_FUTURE_WINDOW"
    assert refreshed.cycle_index == 3
    assert refreshed.cumulative_official_reads == 4
    tick = refreshed.selection.selected_not_before_utc
    refreshed.selection.assert_selected_candidate_current(tick)
    final_names = {path.name for path in refreshed.bundle_directory.iterdir()}
    for cycle in (1, 2):
        assert f"prior-cycle-{cycle:02d}-read-reservation.json" in final_names
        assert f"prior-cycle-{cycle:02d}-attempt-receipt.json" in final_names


def test_official_read_reservation_is_durable_before_fetch_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control = tmp_path / "control"
    control.mkdir()
    workspace = workspace_receipt(tmp_path)
    manifest = mission_manifest()
    plan_bytes = _source_plan_bytes(
        "soccer_spain_la_liga",
        "LALIGA_PUBLIC_MATCHES_JSON_V1",
        LALIGA_SOURCE,
    )
    monkeypatch.setattr(
        CANARY_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    fetch_calls = 0

    class InterruptedFetcher:
        def fetch(self, _source: object) -> object:
            nonlocal fetch_calls
            fetch_calls += 1
            raise RuntimeError("SYNTHETIC_PROCESS_INTERRUPTION")

    arguments = {
        "workspace_receipt": workspace,
        "workspace_receipt_bytes": workspace.model_dump_json().encode(),
        "mission_manifest": manifest,
        "mission_manifest_bytes": manifest.model_dump_json().encode(),
        "source_plan_bytes": plan_bytes,
        "output_directory": control / "bundle",
        "fetcher": InterruptedFetcher(),
        "workspace_validator": lambda _workspace: None,
        "marker_inspector": lambda _workspace, _manifest: {
            "local_marker_present": False,
            "global_marker_present": False,
            "inspected_read_only": True,
        },
    }
    with pytest.raises(RuntimeError, match="SYNTHETIC_PROCESS_INTERRUPTION"):
        CANARY_CLI.prepare_first_c0_canary_selection_v1(**arguments)
    reservation = control / "first-c0-canary-cycle-01-read-reservation-v1.json"
    assert reservation.is_file()
    payload = json.loads(reservation.read_bytes())
    assert payload["status"] == "RESERVED_BEFORE_OFFICIAL_READ"
    assert payload["official_reads_reserved"] == 2
    assert payload["provider_dns"] == payload["provider_http"] == 0
    with pytest.raises(
        CANARY_CLI.FirstC0CanaryPreparationError,
        match="FIRST_C0_CANARY_PREVIOUS_CYCLE_INCOMPLETE",
    ):
        CANARY_CLI.prepare_first_c0_canary_selection_v1(**arguments)
    assert fetch_calls == 1
