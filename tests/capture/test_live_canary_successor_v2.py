from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin.capture import (
    ActivationEnvelopeV2,
    BoundedLiveCanaryExecutor,
    CampaignLeagueCorpusCountV1,
    CampaignWindowSelectionV1,
    CaptureContractError,
    CaptureMode,
    CaptureStore,
    FixtureTargetSetV1,
    InternalRetentionPolicy,
    LiveCaptureLineageV2,
    LivePlanItemV2,
    LivePlanV2,
    OfficialFixtureTargetV1,
    OwnerAuthorizationV2,
    OwnerReviewPackV1,
    PinnedOwnerAuthorizationVerifier,
    ProviderNetworkBindingV1,
    ProviderNetworkResolutionClaimV1,
    ProviderRequestSpec,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
    RequestFingerprint,
    ScientificCorpusSnapshotV1,
)
from robin.capture.bootstrap_contracts import (
    CAMPAIGN_RANKING_POLICY,
    CAMPAIGN_SELECTION_REVISION,
    _derive_campaign_candidates_v1,
    _derive_window_candidates_v1,
    _interval_candidate_groups_v1,
    load_campaign_selection_authority_v1,
)
from robin.capture.contracts import canonical_json_bytes, canonical_sha256
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS, LiveTerminalDisposition
from robin.capture.live_executor import (
    LiveGuardError,
    RepositoryStateV1,
    RepositoryStateV2,
    ReviewedOwnerAuthorizationVerifierV2,
)
from robin.capture.live_transport import LiveTransportResponse, PublicProviderRequestV2
from robin.capture.owner_review_pack import (
    OwnerReviewPackError,
    assert_owner_review_pack_completion_current_v1,
    build_owner_review_pack_v1,
    owner_authorization_statement_v1,
    write_owner_review_pack_v1,
)
from robin.capture.storage import CaptureStorageError

BASE = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
MAIN_SHA = "a" * 40
REPOSITORY_FINGERPRINT = "d" * 64
CONTROL_FINGERPRINT = "e" * 64
SECRET = "synthetic-secret-sentinel-never-real"


class TickingClock:
    def __init__(self) -> None:
        self.value = BASE

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class V2RepositoryReader:
    def __init__(self, git_path: str, git_sha256: str, *, returned_path: str | None = None) -> None:
        self.git_path = git_path
        self.git_sha256 = git_sha256
        self.returned_path = returned_path or git_path
        self.reads = 0

    def read(self) -> RepositoryStateV1:
        raise AssertionError("V1_REPOSITORY_READER_FORBIDDEN")

    def read_v2(
        self,
        *,
        approved_git_executable_path: str,
        approved_git_executable_sha256: str,
    ) -> RepositoryStateV2:
        self.reads += 1
        assert approved_git_executable_path == self.git_path
        assert approved_git_executable_sha256 == self.git_sha256
        return RepositoryStateV2(
            head_sha=MAIN_SHA,
            main_sha=MAIN_SHA,
            worktree_clean=True,
            repository_root_fingerprint=REPOSITORY_FINGERPRINT,
            control_temp_root_fingerprint=CONTROL_FINGERPRINT,
            git_executable_canonical_path=self.returned_path,
            git_executable_sha256=self.git_sha256,
            standalone_git_directory=True,
        )


class SpySecretReader:
    def __init__(self) -> None:
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return SECRET


class V2Transport:
    def __init__(self, payload: bytes, clock: TickingClock) -> None:
        self.payload = payload
        self.clock = clock
        self.preflights = 0
        self.calls = 0
        self.requests: list[PublicProviderRequestV2] = []

    def preflight(self, request: PublicProviderRequestV2) -> None:
        self.preflights += 1
        self.requests.append(request)

    def dispatch(
        self,
        request: PublicProviderRequestV2,
        *,
        api_key: str,
    ) -> LiveTransportResponse:
        assert api_key == SECRET
        assert request.provider_network_binding.selected_ip_address == "8.8.8.8"
        self.calls += 1
        return LiveTransportResponse(
            http_status=200,
            headers={
                "x-requests-last": "1",
                "x-requests-used": "1",
                "x-requests-remaining": "999",
            },
            payload=self.payload,
            first_observed_at_utc=self.clock(),
        )


@dataclass(frozen=True, slots=True)
class V2Bundle:
    store: CaptureStore
    mission_manifest: RealExecutionMissionManifestV1
    workspace: RealCaptureWorkspaceReceiptV1
    review_candidate: OwnerAuthorizationV2
    authorization: OwnerAuthorizationV2
    activation: ActivationEnvelopeV2
    plan: LivePlanV2
    item: LivePlanItemV2
    request: ProviderRequestSpec
    targets: FixtureTargetSetV1
    network_binding: ProviderNetworkBindingV1
    git_path: str
    git_sha256: str
    payload: bytes


def build_campaign_selection(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
    *,
    selected_at: datetime = BASE - timedelta(seconds=90),
    kickoff_at: datetime = BASE + timedelta(hours=2, minutes=10),
    first_league_coverage: int = 2,
) -> CampaignWindowSelectionV1:
    source_observed = workspace.prepared_at_utc + timedelta(seconds=30)
    created = source_observed + timedelta(seconds=30)
    target_sets: list[FixtureTargetSetV1] = []
    for league_index, sport_key in enumerate(LIVE_ALLOWED_SPORT_KEYS):
        coverage = first_league_coverage if league_index == 0 else 1
        targets = tuple(
            OfficialFixtureTargetV1.issue(
                internal_fixture_target_id=f"campaign-{league_index}-{target_index}",
                competition=f"Competition {league_index}",
                sport_key=sport_key,
                official_home_team=f"Home {league_index} {target_index}",
                official_away_team=f"Away {league_index} {target_index}",
                official_kickoff_utc=kickoff_at,
                official_source_authority="https://official.example/current-schedule",
                source_observed_at_utc=source_observed,
                source_evidence_sha256=f"{league_index + 1}" * 64,
            )
            for target_index in range(coverage)
        )
        target_sets.append(
            FixtureTargetSetV1.issue(
                target_set_id=f"campaign-source-{league_index}",
                sport_key=sport_key,
                workspace_receipt_sha256=workspace.canonical_receipt_hash,
                created_at_utc=created,
                official_schedule_horizon_not_before_utc=selected_at - timedelta(minutes=1),
                official_schedule_horizon_expires_at_utc=kickoff_at + timedelta(days=1),
                official_schedule_fixture_count=len(targets),
                official_schedule_completeness=("OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON"),
                targets=targets,
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


def build_bundle(
    tmp_path: Path,
    *,
    authorized: bool = True,
    extra_unmatched_target: bool = False,
) -> V2Bundle:
    capture_root = tmp_path / "capture"
    store = CaptureStore(
        capture_root,
        InternalRetentionPolicy(),
        approved_local_root=capture_root,
    )
    git_file = tmp_path / "git.exe"
    git_file.write_bytes(b"synthetic-git")
    git_path = os.path.normcase(os.path.abspath(git_file))
    git_sha256 = hashlib.sha256(b"synthetic-git").hexdigest()
    mission_manifest = RealExecutionMissionManifestV1.issue(
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
        source_hash="0270bdd51d8d50b7d3c9f608e4f429b46b94b789d92d4b13055b81c9b72e6291",
        expires_at=BASE + timedelta(days=4),
    )
    workspace = RealCaptureWorkspaceReceiptV1.issue(
        authorized_main_sha=MAIN_SHA,
        bootstrap_mode="VERIFY",
        bootstrap_tool_source_repository_root=os.path.abspath(tmp_path / "repository"),
        bootstrap_tool_loaded_from_runtime_repository=True,
        bootstrap_package_source_repository_root=os.path.abspath(tmp_path / "repository"),
        bootstrap_package_loaded_from_runtime_repository=True,
        authority_eligible_for_real_execution=True,
        prepared_at_utc=BASE - timedelta(minutes=3),
        runtime_repository_root=os.path.abspath(tmp_path / "repository"),
        repository_root_fingerprint=REPOSITORY_FINGERPRINT,
        repository_security_descriptor_sha256="1" * 64,
        control_temp_root=os.path.abspath(tmp_path / "control-temp"),
        control_temp_fingerprint=CONTROL_FINGERPRINT,
        control_temp_security_descriptor_sha256="2" * 64,
        capture_root=os.path.abspath(capture_root),
        capture_root_fingerprint=store.capture_root_fingerprint(),
        capture_security_descriptor_sha256="3" * 64,
        git_executable_path=git_path,
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
    target = OfficialFixtureTargetV1.issue(
        internal_fixture_target_id="fixture-official-001",
        competition="Premier League",
        sport_key="soccer_epl",
        official_home_team="Home Alpha",
        official_away_team="Away Beta",
        official_kickoff_utc=BASE + timedelta(days=1),
        official_source_authority="https://example.test/official",
        source_observed_at_utc=BASE - timedelta(hours=1),
        source_evidence_sha256="f" * 64,
    )
    target_items = [target]
    if extra_unmatched_target:
        target_items.append(
            OfficialFixtureTargetV1.issue(
                internal_fixture_target_id="fixture-official-002",
                competition="Premier League",
                sport_key="soccer_epl",
                official_home_team="West Town",
                official_away_team="South United",
                official_kickoff_utc=BASE + timedelta(days=1, hours=2),
                official_source_authority="https://example.test/official",
                source_observed_at_utc=BASE - timedelta(hours=1),
                source_evidence_sha256="f" * 64,
            )
        )
    targets = FixtureTargetSetV1.issue(
        target_set_id="official-targets-001",
        sport_key="soccer_epl",
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        created_at_utc=BASE - timedelta(minutes=2),
        targets=tuple(target_items),
    )
    resolution_claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        campaign_selection_sha256="1" * 64,
        fixture_target_set_sha256=targets.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(minutes=1, seconds=5),
        mission_expires_at_utc=mission_manifest.expires_at,
    )
    network_binding = ProviderNetworkBindingV1.issue(
        resolution_claim=resolution_claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=10),
        binding_ttl_seconds=660,
        resolved_ip_addresses=("8.8.8.8",),
    )
    request = ProviderRequestSpec(
        endpoint="/v4/sports/soccer_epl/odds",
        sport_key="soccer_epl",
        region="eu",
        markets=("h2h",),
        timeout_seconds=5,
    )
    fingerprint = RequestFingerprint.create(request)
    authorization_data = dict(
        authorization_id="owner-v2-001",
        authorized_main_sha=MAIN_SHA,
        mission_manifest_sha256=mission_manifest.canonical_manifest_sha256(),
        mission_expires_at_utc=mission_manifest.expires_at,
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        issued_at_utc=BASE - timedelta(minutes=3),
        not_before_utc=BASE - timedelta(minutes=2),
        expires_at_utc=BASE + timedelta(minutes=8),
        allowed_sport_keys=("soccer_epl",),
        allowed_market_sets=(("h2h",),),
        maximum_http_calls=1,
        maximum_credits=1,
        maximum_plan_items=1,
        approved_capture_root_fingerprint=store.capture_root_fingerprint(),
        approved_repository_root_fingerprint=REPOSITORY_FINGERPRINT,
        approved_control_temp_root_fingerprint=CONTROL_FINGERPRINT,
        approved_git_executable_path=git_path,
        approved_git_executable_sha256=git_sha256,
        provider_network_binding_sha256=network_binding.canonical_binding_hash,
        approved_provider_ip_address=network_binding.selected_ip_address,
        campaign_selection_sha256="1" * 64,
        fixture_target_set_sha256=targets.canonical_set_hash,
        authorization_nonce="owner-v2-nonce-00000001",
    )
    review_candidate = OwnerAuthorizationV2.issue(
        **authorization_data,
        authorization_status="OWNER_REVIEW_CANDIDATE",
    )
    authorization = (
        OwnerAuthorizationV2.issue(
            **authorization_data,
            authorization_status="OWNER_AUTHORIZED",
            review_candidate_sha256=review_candidate.canonical_authorization_hash,
        )
        if authorized
        else review_candidate
    )
    activation_seed = ActivationEnvelopeV2.issue(
        activation_id="activation-v2-001",
        authorization_id=authorization.authorization_id,
        authorization_hash=authorization.canonical_authorization_hash,
        repository_sha=MAIN_SHA,
        provider_network_binding_sha256=network_binding.canonical_binding_hash,
        fixture_target_set_sha256=targets.canonical_set_hash,
        sport_key="soccer_epl",
        region="eu",
        markets=("h2h",),
        not_before_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=7),
        maximum_http_calls=1,
        maximum_credits=1,
        plan_sha256="0" * 64,
        activation_nonce="activation-v2-nonce-0001",
    )
    item = LivePlanItemV2.issue(
        item_id="item-v2-001",
        plan_id="plan-v2-001",
        sequence=1,
        sport_key="soccer_epl",
        region="eu",
        markets=("h2h",),
        provider_request_fingerprint=fingerprint.request_sha256,
        fixture_target_set_sha256=targets.canonical_set_hash,
        provider_network_binding_sha256=network_binding.canonical_binding_hash,
        not_before_utc=BASE - timedelta(seconds=30),
        expires_at_utc=BASE + timedelta(minutes=6),
        maximum_credits=1,
        purpose="synthetic successor integration",
        window_label="synthetic-window",
    )
    plan = LivePlanV2.issue(
        plan_id="plan-v2-001",
        activation_id=activation_seed.activation_id,
        activation_hash=activation_seed.activation_scope_sha256,
        repository_sha=MAIN_SHA,
        provider_network_binding_sha256=network_binding.canonical_binding_hash,
        fixture_target_set_sha256=targets.canonical_set_hash,
        created_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=7),
        items=(item,),
        maximum_http_calls=1,
        maximum_credits=1,
    )
    activation = ActivationEnvelopeV2.issue(
        **{
            **activation_seed.model_dump(
                mode="python",
                exclude={
                    "activation_scope_sha256",
                    "canonical_activation_hash",
                    "plan_sha256",
                },
            ),
            "plan_sha256": plan.canonical_plan_hash,
        }
    )
    payload = json.dumps(
        [
            {
                "id": "provider-event-001",
                "sport_key": "soccer_epl",
                "commence_time": (BASE + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "home_team": "Home Alpha",
                "away_team": "Away Beta",
                "bookmakers": [
                    {
                        "key": "synthetic-book",
                        "markets": [
                            {
                                "key": "h2h",
                                "last_update": BASE.isoformat().replace("+00:00", "Z"),
                                "outcomes": [
                                    {"name": "Home Alpha", "price": 2.1},
                                    {"name": "Draw", "price": 3.2},
                                    {"name": "Away Beta", "price": 3.4},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return V2Bundle(
        store=store,
        mission_manifest=mission_manifest,
        workspace=workspace,
        review_candidate=review_candidate,
        authorization=authorization,
        activation=activation,
        plan=plan,
        item=item,
        request=request,
        targets=targets,
        network_binding=network_binding,
        git_path=git_path,
        git_sha256=git_sha256,
        payload=payload,
    )


def executor(
    bundle: V2Bundle,
    secret: SpySecretReader,
    transport: V2Transport,
    clock: TickingClock,
    *,
    returned_git_path: str | None = None,
) -> BoundedLiveCanaryExecutor:
    return BoundedLiveCanaryExecutor(
        capture_store=bundle.store,
        repository_state_reader=V2RepositoryReader(
            bundle.git_path,
            bundle.git_sha256,
            returned_path=returned_git_path,
        ),
        owner_authorization_verifier=PinnedOwnerAuthorizationVerifier(
            bundle.authorization.canonical_authorization_hash
        ),
        secret_reader=secret,
        transport=transport,
        clock=clock,
    )


def test_successor_predispatch_contracts_contain_no_provider_ids_or_mapping_hash(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    material = json.dumps(
        {
            "authorization": bundle.authorization.model_dump(mode="json"),
            "activation": bundle.activation.model_dump(mode="json"),
            "plan": bundle.plan.model_dump(mode="json"),
            "item": bundle.item.model_dump(mode="json"),
            "targets": bundle.targets.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    assert "provider_event_id" not in material
    assert "fixture_mappings_sha256" not in material
    assert bundle.item.fixture_target_set_sha256 == bundle.targets.canonical_set_hash


def test_review_candidate_cannot_reach_repository_secret_or_transport(tmp_path: Path) -> None:
    bundle = build_bundle(tmp_path, authorized=False)
    secret = SpySecretReader()
    clock = TickingClock()
    transport = V2Transport(bundle.payload, clock)
    with pytest.raises(
        LiveGuardError,
        match="LIVE_OWNER_AUTHORIZATION_CANDIDATE_NOT_EXECUTABLE",
    ):
        executor(bundle, secret, transport, clock).execute_v2(
            mode=CaptureMode.LIVE_CANARY,
            authorization=bundle.authorization,
            activation=bundle.activation,
            plan=bundle.plan,
            item=bundle.item,
            request=bundle.request,
            fixture_target_set=bundle.targets,
            provider_network_binding=bundle.network_binding,
            mission_manifest=bundle.mission_manifest,
            review_candidate=bundle.review_candidate,
        )
    assert secret.reads == transport.preflights == transport.calls == 0


def test_git_path_mismatch_stops_before_secret(tmp_path: Path) -> None:
    bundle = build_bundle(tmp_path)
    secret = SpySecretReader()
    clock = TickingClock()
    transport = V2Transport(bundle.payload, clock)
    alternate_path = os.path.normcase(os.path.abspath(tmp_path / "alternate" / "git.exe"))
    with pytest.raises(LiveGuardError, match="LIVE_V2_REPOSITORY_BINDING_MISMATCH"):
        executor(
            bundle,
            secret,
            transport,
            clock,
            returned_git_path=alternate_path,
        ).execute_v2(
            mode=CaptureMode.LIVE_CANARY,
            authorization=bundle.authorization,
            activation=bundle.activation,
            plan=bundle.plan,
            item=bundle.item,
            request=bundle.request,
            fixture_target_set=bundle.targets,
            provider_network_binding=bundle.network_binding,
            mission_manifest=bundle.mission_manifest,
            review_candidate=bundle.review_candidate,
        )
    assert secret.reads == transport.preflights == transport.calls == 0


def test_runtime_requires_exact_reviewed_candidate_artifact(tmp_path: Path) -> None:
    bundle = build_bundle(tmp_path)
    wrong_candidate = OwnerAuthorizationV2.issue(
        **{
            **bundle.review_candidate.model_dump(
                mode="python",
                exclude={"canonical_authorization_hash", "authorization_nonce"},
            ),
            "authorization_nonce": "different-owner-review-nonce-0001",
        }
    )
    secret = SpySecretReader()
    clock = TickingClock()
    transport = V2Transport(bundle.payload, clock)
    with pytest.raises(LiveGuardError, match="LIVE_SUCCESSOR_AUTHORITY_BINDING_MISMATCH"):
        executor(bundle, secret, transport, clock).execute_v2(
            mode=CaptureMode.LIVE_CANARY,
            authorization=bundle.authorization,
            activation=bundle.activation,
            plan=bundle.plan,
            item=bundle.item,
            request=bundle.request,
            fixture_target_set=bundle.targets,
            provider_network_binding=bundle.network_binding,
            mission_manifest=bundle.mission_manifest,
            review_candidate=wrong_candidate,
        )
    assert secret.reads == transport.preflights == transport.calls == 0


def test_successor_full_flow_maps_only_after_durable_raw_and_replays_offline(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    secret = SpySecretReader()
    clock = TickingClock()
    transport = V2Transport(bundle.payload, clock)
    stages: list[str] = []
    live_executor = BoundedLiveCanaryExecutor(
        capture_store=bundle.store,
        repository_state_reader=V2RepositoryReader(bundle.git_path, bundle.git_sha256),
        owner_authorization_verifier=PinnedOwnerAuthorizationVerifier(
            bundle.authorization.canonical_authorization_hash
        ),
        secret_reader=secret,
        transport=transport,
        clock=clock,
        stage_observer=stages.append,
    )
    receipt = live_executor.execute_v2(
        mode=CaptureMode.LIVE_CANARY,
        authorization=bundle.authorization,
        activation=bundle.activation,
        plan=bundle.plan,
        item=bundle.item,
        request=bundle.request,
        fixture_target_set=bundle.targets,
        provider_network_binding=bundle.network_binding,
        mission_manifest=bundle.mission_manifest,
        review_candidate=bundle.review_candidate,
    )
    assert receipt.terminal_disposition is LiveTerminalDisposition.SUCCESS
    assert receipt.network_calls == transport.calls == 1
    assert receipt.secret_reads_count == secret.reads == 1
    assert receipt.manifest_id is not None
    lineage = bundle.store._load_live_capture_lineage(
        bundle.store.load_manifest(receipt.manifest_id)
    )
    assert getattr(lineage, "scientific_admission") == "FULL"
    assert (
        stages.index("RAW_SHA256_COMPUTED")
        < stages.index("INTAKE_RECEIPT_DURABLE")
        < stages.index("RAW_CONTENT_ADDRESSED_DURABLE")
        < stages.index("IDENTITY_ENVELOPE_PARSE_STARTED")
        < stages.index("POST_CAPTURE_MAPPING_DERIVED")
        < stages.index("POST_CAPTURE_MAPPING_EVIDENCE_DURABLE")
        < stages.index("NORMALIZATION_COMPLETED")
        < stages.index("FINAL_RECEIPT_DURABLE")
        < stages.index("MANIFEST_DURABLE")
    )
    replay = bundle.store.replay(receipt.manifest_id)
    assert replay.deterministic is True
    assert replay.secret_reads_count == 0


@pytest.mark.parametrize(
    ("extra_target", "break_mapping", "expected_admission", "expected_rows"),
    (
        (True, False, "PARTIAL", 3),
        (False, True, "NONE", 0),
    ),
)
def test_successor_capture_success_is_distinct_from_partial_or_zero_scientific_admission(
    tmp_path: Path,
    extra_target: bool,
    break_mapping: bool,
    expected_admission: str,
    expected_rows: int,
) -> None:
    bundle = build_bundle(tmp_path, extra_unmatched_target=extra_target)
    if break_mapping:
        material = json.loads(bundle.payload)
        material[0]["home_team"] = "Unrelated Home"
        material[0]["away_team"] = "Unrelated Away"
        bundle = replace(
            bundle,
            payload=json.dumps(material, sort_keys=True, separators=(",", ":")).encode(),
        )
    secret = SpySecretReader()
    clock = TickingClock()
    transport = V2Transport(bundle.payload, clock)
    receipt = executor(bundle, secret, transport, clock).execute_v2(
        mode=CaptureMode.LIVE_CANARY,
        authorization=bundle.authorization,
        activation=bundle.activation,
        plan=bundle.plan,
        item=bundle.item,
        request=bundle.request,
        fixture_target_set=bundle.targets,
        provider_network_binding=bundle.network_binding,
        mission_manifest=bundle.mission_manifest,
        review_candidate=bundle.review_candidate,
    )
    assert receipt.terminal_disposition is LiveTerminalDisposition.SUCCESS
    assert receipt.manifest_id is not None
    manifest = bundle.store.load_manifest(receipt.manifest_id)
    lineage = bundle.store._load_live_capture_lineage(manifest)
    assert getattr(lineage, "scientific_admission") == expected_admission
    assert manifest.observation_count == expected_rows
    assert bundle.store.replay(receipt.manifest_id).deterministic is True


def _rehash_campaign_selection(material: dict[str, object]) -> dict[str, object]:
    provisional = CampaignWindowSelectionV1.model_construct(
        canonical_selection_hash="0" * 64,
        **material,
    )
    return {
        **material,
        "canonical_selection_hash": canonical_sha256(provisional.identity_material()),
    }


def _campaign_selection_material(
    selection: CampaignWindowSelectionV1,
) -> dict[str, object]:
    return {
        field: getattr(selection, field)
        for field in type(selection).model_fields
        if field != "canonical_selection_hash"
    }


def _build_rollover_selection(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
) -> CampaignWindowSelectionV1:
    selected_at = BASE - timedelta(seconds=90)
    observed_at = BASE - timedelta(seconds=170)
    source_created_at = BASE - timedelta(seconds=160)
    target_sets: list[FixtureTargetSetV1] = []
    for league_index, sport_key in enumerate(LIVE_ALLOWED_SPORT_KEYS):
        kickoffs = (
            (
                selected_at - timedelta(seconds=30),
                BASE + timedelta(hours=2, minutes=10),
                BASE + timedelta(hours=2, minutes=10),
            )
            if league_index == 0
            else (BASE + timedelta(hours=5, minutes=league_index),)
        )
        targets = tuple(
            OfficialFixtureTargetV1.issue(
                internal_fixture_target_id=f"rollover-{league_index}-{target_index}",
                competition=f"Rollover Competition {league_index}",
                sport_key=sport_key,
                official_home_team=f"Rollover Home {league_index} {target_index}",
                official_away_team=f"Rollover Away {league_index} {target_index}",
                official_kickoff_utc=kickoff,
                official_source_authority="https://official.example/rollover",
                source_observed_at_utc=observed_at,
                source_evidence_sha256=f"{league_index + 1}" * 64,
            )
            for target_index, kickoff in enumerate(kickoffs)
        )
        target_sets.append(
            FixtureTargetSetV1.issue(
                target_set_id=f"rollover-source-{league_index}",
                sport_key=sport_key,
                workspace_receipt_sha256=workspace.canonical_receipt_hash,
                created_at_utc=source_created_at,
                official_schedule_horizon_not_before_utc=selected_at - timedelta(minutes=5),
                official_schedule_horizon_expires_at_utc=BASE + timedelta(days=1),
                official_schedule_fixture_count=len(targets),
                official_schedule_completeness="OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON",
                targets=targets,
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


def test_campaign_selection_derives_complete_statuses_and_unique_ranked_winner(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    winner = selection.selected_candidate()
    assert winner.window_id == "H2"
    assert winner.request.sport_key == LIVE_ALLOWED_SPORT_KEYS[0]
    assert winner.fixture_coverage == 2
    assert winner.protocol_role_value == 25
    assert winner.status == "OPEN_SELECTABLE"
    assert sum(item.status == "MISSED_NOT_BACKDATED" for item in selection.candidates) == 5
    assert (
        sum(item.status == "NON_ADMITTING_SCIENTIFIC_AUTHORITY" for item in selection.candidates)
        == 5
    )
    assert sum(item.status == "FUTURE_NOT_OPEN" for item in selection.candidates) == 0
    assert sum(item.status == "OPEN_SELECTABLE" for item in selection.candidates) == 5
    assert len(selection.candidates) == 15
    loaded = load_campaign_selection_authority_v1(selection.model_dump(mode="json"))
    assert isinstance(loaded, CampaignWindowSelectionV1)
    assert loaded == selection
    masquerading = selection.model_dump(mode="json")
    masquerading["schema_version"] = "robin-first-c0-canary-selection-v1"
    with pytest.raises(
        CaptureContractError,
        match="FIRST_C0_CANARY_SELECTION_AUTHORITY_INVALID",
    ):
        load_campaign_selection_authority_v1(masquerading)


def test_five_league_selection_refactor_preserves_exact_historical_scoring(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    maximum_corpus_count = max(
        item.admitted_fixture_count for item in selection.corpus_snapshot.league_counts
    )
    prior_counts = {
        target_set.sport_key: selection.corpus_snapshot.admitted_count(target_set.sport_key)
        for target_set in selection.source_target_sets
    }
    explicit = _derive_window_candidates_v1(
        source_target_sets=selection.source_target_sets,
        window_definitions=selection.window_definitions,
        prior_admitted_counts=prior_counts,
        cross_league_corpus_values={
            sport_key: maximum_corpus_count - prior_count
            for sport_key, prior_count in prior_counts.items()
        },
        evaluated_at_utc=selection.selected_at_utc,
        mission_expires_at_utc=selection.mission_expires_at_utc,
    )
    historical = _derive_campaign_candidates_v1(
        source_target_sets=selection.source_target_sets,
        window_definitions=selection.window_definitions,
        corpus_snapshot=selection.corpus_snapshot,
        evaluated_at_utc=selection.selected_at_utc,
        mission_expires_at_utc=selection.mission_expires_at_utc,
    )
    assert selection.selection_revision == ("complete-five-league-interval-clique-ranking-v2")
    assert selection.ranking_policy == (
        "coverage-desc;protocol-role-desc;positive-margin-required;"
        "cross-league-desc;earliest-readiness-asc;stable-group-hash-asc"
    )
    assert CAMPAIGN_SELECTION_REVISION == selection.selection_revision
    assert CAMPAIGN_RANKING_POLICY == selection.ranking_policy
    assert tuple(item.sport_key for item in selection.source_target_sets) == (
        LIVE_ALLOWED_SPORT_KEYS
    )
    assert explicit == historical == selection.candidates
    assert selection.canonical_selection_hash == canonical_sha256(selection.identity_material())


def test_campaign_selection_rolls_past_kickoff_without_backdating_or_candidate_loss(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = _build_rollover_selection(bundle.workspace, bundle.mission_manifest)
    repeated = _build_rollover_selection(bundle.workspace, bundle.mission_manifest)
    source_created_by_hash = {
        source.canonical_set_hash: source.created_at_utc for source in selection.source_target_sets
    }
    past_candidates = tuple(
        candidate for candidate in selection.candidates if "rollover-0-0" in candidate.target_ids
    )
    future_candidates = tuple(
        candidate for candidate in selection.candidates if "rollover-0-1" in candidate.target_ids
    )
    assert past_candidates
    assert all(candidate.status == "MISSED_NOT_BACKDATED" for candidate in past_candidates)
    assert any(
        candidate.status in {"OPEN_SELECTABLE", "FUTURE_NOT_OPEN"}
        for candidate in future_candidates
    )
    assert selection.selected_candidate().status in {"OPEN_SELECTABLE", "FUTURE_NOT_OPEN"}
    assert selection.canonical_selection_hash == repeated.canonical_selection_hash
    assert all(
        candidate.fixture_target_set.created_at_utc
        == source_created_by_hash[candidate.source_target_set_sha256]
        for candidate in selection.candidates
    )
    assert all(
        candidate.fixture_target_set.created_at_utc < candidate.evaluated_at_utc
        for candidate in selection.candidates
    )


def test_campaign_selector_cli_survives_rollover_with_zero_provider_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = build_bundle(tmp_path)
    expected = _build_rollover_selection(bundle.workspace, bundle.mission_manifest)
    control_root = Path(bundle.workspace.control_temp_root)
    control_root.mkdir()
    workspace_path = control_root / "workspace.json"
    manifest_path = control_root / "mission.json"
    corpus_path = control_root / "corpus.json"
    output_path = control_root / "selection.json"
    workspace_path.write_bytes(
        canonical_json_bytes(bundle.workspace.model_dump(mode="json")) + b"\n"
    )
    manifest_path.write_bytes(
        canonical_json_bytes(bundle.mission_manifest.model_dump(mode="json")) + b"\n"
    )
    corpus_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": "robin-owner-observed-scientific-corpus-v1",
                "observed_at_utc": expected.corpus_snapshot.observed_at_utc.isoformat().replace(
                    "+00:00", "Z"
                ),
                "admitted_fixture_counts": {
                    item.sport_key: item.admitted_fixture_count
                    for item in expected.corpus_snapshot.league_counts
                },
            }
        )
        + b"\n"
    )
    target_paths: list[Path] = []
    for index, target_set in enumerate(expected.source_target_sets):
        path = control_root / f"target-set-{index}.json"
        path.write_bytes(canonical_json_bytes(target_set.model_dump(mode="json")) + b"\n")
        target_paths.append(path)

    script_path = Path(__file__).parents[2] / "tools/data-sourcing/select_campaign_window_v1.py"
    spec = importlib.util.spec_from_file_location("selector_rollover_cli_under_test", script_path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return expected.selected_at_utc

    monkeypatch.setattr(cli, "datetime", FrozenDateTime)
    monkeypatch.setattr(cli, "assert_real_capture_workspace_receipt_current_v1", lambda _: None)
    monkeypatch.setattr(
        cli,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: bundle.mission_manifest,
    )
    monkeypatch.setattr(
        cli,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    argv = [
        str(script_path),
        "--workspace-receipt",
        str(workspace_path),
        "--mission-manifest",
        str(manifest_path),
    ]
    for path in target_paths:
        argv.extend(("--fixture-target-set", str(path)))
    argv.extend(("--corpus-evidence", str(corpus_path), "--output", str(output_path)))
    monkeypatch.setattr(sys, "argv", argv)

    exit_code = cli.main()
    result = json.loads(capsys.readouterr().out)
    observed = CampaignWindowSelectionV1.model_validate(json.loads(output_path.read_bytes()))
    assert exit_code == 0
    assert result["candidate_status_counts"]["MISSED_NOT_BACKDATED"] > 0
    assert observed.selected_candidate().status in {"OPEN_SELECTABLE", "FUTURE_NOT_OPEN"}
    assert result["provider_http_requests"] == 0
    assert result["provider_tcp_connections"] == 0
    assert result["provider_secret_reads"] == 0


def test_campaign_selection_rejects_omitted_candidate_and_schedule_or_corpus_tamper(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)

    omitted = _campaign_selection_material(selection)
    omitted["candidates"] = selection.candidates[:-1]
    with pytest.raises(CaptureContractError):
        CampaignWindowSelectionV1.model_validate(_rehash_campaign_selection(omitted))

    original_set = selection.source_target_sets[0]
    original_target = original_set.targets[0]
    changed_target = OfficialFixtureTargetV1.issue(
        **original_target.model_dump(
            mode="python",
            exclude={"canonical_target_hash", "official_kickoff_utc"},
        ),
        official_kickoff_utc=original_target.official_kickoff_utc + timedelta(minutes=1),
    )
    changed_set = FixtureTargetSetV1.issue(
        **original_set.model_dump(
            mode="python",
            exclude={"canonical_set_hash", "targets"},
        ),
        targets=(changed_target, *original_set.targets[1:]),
    )
    changed_schedule = _campaign_selection_material(selection)
    changed_schedule["source_target_sets"] = (
        changed_set,
        *selection.source_target_sets[1:],
    )
    with pytest.raises(CaptureContractError):
        CampaignWindowSelectionV1.model_validate(_rehash_campaign_selection(changed_schedule))

    changed_corpus = ScientificCorpusSnapshotV1.issue(
        observed_at_utc=selection.corpus_snapshot.observed_at_utc,
        source_evidence_sha256="e" * 64,
        league_counts=tuple(
            CampaignLeagueCorpusCountV1(
                sport_key=sport_key,
                admitted_fixture_count=99 if index == 0 else 0,
            )
            for index, sport_key in enumerate(LIVE_ALLOWED_SPORT_KEYS)
        ),
    )
    changed_scoring = _campaign_selection_material(selection)
    changed_scoring["corpus_snapshot"] = changed_corpus
    with pytest.raises(CaptureContractError):
        CampaignWindowSelectionV1.model_validate(_rehash_campaign_selection(changed_scoring))

    incomplete_source = FixtureTargetSetV1.issue(
        target_set_id=original_set.target_set_id,
        sport_key=original_set.sport_key,
        workspace_receipt_sha256=original_set.workspace_receipt_sha256,
        created_at_utc=original_set.created_at_utc,
        targets=original_set.targets,
    )
    with pytest.raises(CaptureContractError):
        CampaignWindowSelectionV1.issue(
            selected_at_utc=selection.selected_at_utc,
            workspace_receipt_sha256=selection.workspace_receipt_sha256,
            workspace_prepared_at_utc=selection.workspace_prepared_at_utc,
            mission_manifest_sha256=selection.mission_manifest_sha256,
            mission_expires_at_utc=selection.mission_expires_at_utc,
            source_target_sets=(
                incomplete_source,
                *selection.source_target_sets[1:],
            ),
            corpus_snapshot=selection.corpus_snapshot,
        )


def test_campaign_interval_cliques_do_not_omit_later_maximum_coverage_group() -> None:
    def target(label: str) -> OfficialFixtureTargetV1:
        return OfficialFixtureTargetV1.issue(
            internal_fixture_target_id=f"counterexample-{label}",
            competition="Counterexample League",
            sport_key="soccer_epl",
            official_home_team=f"Home {label}",
            official_away_team=f"Away {label}",
            official_kickoff_utc=BASE + timedelta(days=1),
            official_source_authority="https://official.example/counterexample",
            source_observed_at_utc=BASE - timedelta(minutes=1),
            source_evidence_sha256="a" * 64,
        )

    fixture_a, fixture_b, fixture_c, fixture_d = (target(label) for label in ("A", "B", "C", "D"))
    groups = _interval_candidate_groups_v1(
        (
            (fixture_a, BASE, BASE + timedelta(minutes=10)),
            (fixture_b, BASE - timedelta(minutes=9), BASE + timedelta(minutes=1)),
            (fixture_c, BASE + timedelta(minutes=2), BASE + timedelta(minutes=12)),
            (fixture_d, BASE + timedelta(minutes=2), BASE + timedelta(minutes=12)),
        )
    )
    target_id_groups = {
        frozenset(target.internal_fixture_target_id for target in targets)
        for targets, _, _ in groups
    }
    assert (
        frozenset({"counterexample-A", "counterexample-C", "counterexample-D"}) in target_id_groups
    )
    assert max(len(group) for group in target_id_groups) == 3


def test_campaign_selection_keeps_future_winner_and_uses_stable_hash_final_tie_break(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    tied = build_campaign_selection(
        bundle.workspace,
        bundle.mission_manifest,
        first_league_coverage=1,
    )
    open_candidates = tuple(
        candidate for candidate in tied.candidates if candidate.status == "OPEN_SELECTABLE"
    )
    assert tied.selected_candidate().stable_group_hash == min(
        candidate.stable_group_hash for candidate in open_candidates
    )
    tied.assert_selected_candidate_current(BASE)
    with pytest.raises(ValueError, match="CAMPAIGN_NO_REMAINING_SELECTABLE_CANDIDATE"):
        tied.assert_selected_candidate_current(BASE + timedelta(minutes=11))

    future = build_campaign_selection(
        bundle.workspace,
        bundle.mission_manifest,
        kickoff_at=BASE + timedelta(hours=5),
    )
    assert future.selected_candidate().status == "FUTURE_NOT_OPEN"
    assert future.selected_ready_at_selection is False
    assert future.selected_not_before_utc == future.selected_candidate().window_not_before_utc
    with pytest.raises(ValueError, match="CAMPAIGN_SELECTED_CANDIDATE_NOT_OPEN"):
        future.assert_selected_candidate_current(BASE)
    with pytest.raises(ValueError, match="CAMPAIGN_SELECTION_SOURCE_STALE"):
        future.assert_selected_candidate_current(future.selected_at_utc + timedelta(minutes=31))


def test_owner_review_pack_is_complete_unexecuted_and_statement_binds_every_gate(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    campaign_selection = build_campaign_selection(
        bundle.workspace,
        bundle.mission_manifest,
    )
    selected = campaign_selection.selected_candidate()
    resolution_claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=bundle.mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=bundle.workspace.canonical_receipt_hash,
        campaign_selection_sha256=campaign_selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=bundle.mission_manifest.expires_at,
    )
    network_binding = ProviderNetworkBindingV1.issue(
        resolution_claim=resolution_claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=10),
        binding_ttl_seconds=660,
        resolved_ip_addresses=("8.8.8.8",),
    )
    pack = build_owner_review_pack_v1(
        workspace_receipt=bundle.workspace,
        mission_manifest=bundle.mission_manifest,
        provider_network_binding=network_binding,
        campaign_selection=campaign_selection,
        generated_at_utc=BASE,
        authorization_nonce="owner-pack-nonce-0000001",
        activation_nonce="activation-pack-nonce-001",
    )
    assert pack.owner_authorization_ready is True
    assert pack.owner_authorization_candidate.authorization_status == "OWNER_REVIEW_CANDIDATE"
    assert pack.activation_candidate.authorization_hash == (
        pack.expected_owner_authorization_sha256
    )
    assert pack.provider_http_calls == pack.real_secret_reads == pack.real_capture_calls == 0
    assert pack.plan_item_candidate.fixture_target_set_sha256 == (
        selected.fixture_target_set.canonical_set_hash
    )
    assert "provider_event_id" not in pack.model_dump_json()
    statement = owner_authorization_statement_v1(pack)
    for value in (
        MAIN_SHA,
        pack.owner_authorization_candidate.canonical_authorization_hash,
        pack.expected_owner_authorization_sha256,
        pack.activation_candidate.canonical_activation_hash,
        network_binding.canonical_binding_hash,
        network_binding.selected_ip_address,
        campaign_selection.canonical_selection_hash,
        selected.canonical_candidate_hash,
        selected.fixture_target_set.canonical_set_hash,
        pack.request_fingerprint_sha256,
        pack.canonical_pack_hash,
        pack.plan_candidate.canonical_plan_hash,
        pack.plan_item_candidate.canonical_item_hash,
    ):
        assert value in statement
    output = tmp_path / "owner-pack"
    output.mkdir()
    paths = write_owner_review_pack_v1(output, pack)
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

    candidate = pack.owner_authorization_candidate
    promoted = OwnerAuthorizationV2.issue(
        **candidate.model_dump(
            mode="python",
            exclude={
                "authorization_status",
                "review_candidate_sha256",
                "canonical_authorization_hash",
            },
        ),
        authorization_status="OWNER_AUTHORIZED",
        review_candidate_sha256=candidate.canonical_authorization_hash,
    )
    immutable_successor_hashes = (
        pack.activation_candidate.canonical_activation_hash,
        pack.plan_candidate.canonical_plan_hash,
        pack.plan_item_candidate.canonical_item_hash,
    )
    assert promoted.canonical_authorization_hash == (
        candidate.expected_promoted_authorization_hash()
    )
    assert promoted.canonical_authorization_hash == pack.expected_owner_authorization_sha256
    clock = TickingClock()
    secret = SpySecretReader()
    transport = V2Transport(bundle.payload, clock)
    receipt = BoundedLiveCanaryExecutor(
        capture_store=bundle.store,
        repository_state_reader=V2RepositoryReader(bundle.git_path, bundle.git_sha256),
        owner_authorization_verifier=ReviewedOwnerAuthorizationVerifierV2(candidate),
        secret_reader=secret,
        transport=transport,
        clock=clock,
    ).execute_v2(
        mode=CaptureMode.LIVE_CANARY,
        authorization=promoted,
        activation=pack.activation_candidate,
        plan=pack.plan_candidate,
        item=pack.plan_item_candidate,
        request=pack.request,
        fixture_target_set=pack.fixture_target_set,
        provider_network_binding=pack.provider_network_binding,
        mission_manifest=pack.mission_manifest,
        review_candidate=candidate,
    )
    assert receipt.terminal_disposition is LiveTerminalDisposition.SUCCESS
    assert immutable_successor_hashes == (
        pack.activation_candidate.canonical_activation_hash,
        pack.plan_candidate.canonical_plan_hash,
        pack.plan_item_candidate.canonical_item_hash,
    )
    with pytest.raises(OwnerReviewPackError, match="NETWORK_BINDING_EXPIRED"):
        assert_owner_review_pack_completion_current_v1(
            pack,
            pack.provider_network_binding.expires_at_utc,
        )


def test_owner_review_pack_cli_canonicalizes_generated_at_for_nonce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = build_bundle(tmp_path)
    campaign_selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    selected = campaign_selection.selected_candidate()
    resolution_claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=bundle.mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=bundle.workspace.canonical_receipt_hash,
        campaign_selection_sha256=campaign_selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=bundle.mission_manifest.expires_at,
    )
    network_binding = ProviderNetworkBindingV1.issue(
        resolution_claim=resolution_claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=10),
        binding_ttl_seconds=660,
        resolved_ip_addresses=("8.8.8.8",),
    )
    repository = Path(bundle.workspace.runtime_repository_root)
    manifest_path = repository / "configs/execution/real-execution-bootstrap-closure-v1.json"
    inputs = tmp_path / "cli-inputs"
    inputs.mkdir()
    manifest_path.parent.mkdir(parents=True)
    workspace_path = inputs / "workspace-receipt.json"
    binding_path = inputs / "provider-network-binding.json"
    selection_path = inputs / "campaign-selection.json"
    for path, artifact in (
        (workspace_path, bundle.workspace),
        (manifest_path, bundle.mission_manifest),
        (binding_path, network_binding),
        (selection_path, campaign_selection),
    ):
        path.write_bytes(canonical_json_bytes(artifact.model_dump(mode="json")) + b"\n")
    control_temp = Path(bundle.workspace.control_temp_root)
    control_temp.mkdir()
    output = control_temp / "owner-review-pack"

    script_path = Path(__file__).parents[2] / "tools/data-sourcing/build_owner_review_pack_v1.py"
    spec = importlib.util.spec_from_file_location("owner_review_pack_cli_under_test", script_path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return BASE

    serialization_errors: list[str] = []

    def observed_sha256(value: object) -> str:
        try:
            return canonical_sha256(value)
        except TypeError as error:
            serialization_errors.append(str(error))
            raise

    monkeypatch.setattr(cli, "datetime", FrozenDateTime)
    monkeypatch.setattr(cli, "canonical_sha256", observed_sha256)
    monkeypatch.setattr(cli, "assert_real_capture_workspace_receipt_current_v1", lambda _: None)
    monkeypatch.setattr(
        cli,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--workspace-receipt",
            str(workspace_path),
            "--mission-manifest",
            str(manifest_path),
            "--provider-network-binding",
            str(binding_path),
            "--campaign-selection",
            str(selection_path),
            "--output-directory",
            str(output),
        ],
    )

    exit_code = cli.main()
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0, serialization_errors
    assert result["status"] == "OWNER_AUTHORIZATION_READY"
    assert set(result["outputs"]) == {
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
    assert all(Path(path).is_file() for path in result["outputs"].values())
    assert all(
        isinstance(json.loads(Path(path).read_text(encoding="utf-8")), dict)
        for path in result["outputs"].values()
    )

    pack_payload = json.loads(
        Path(result["outputs"]["owner_review_pack"]).read_text(encoding="utf-8")
    )
    pack = OwnerReviewPackV1.model_validate(pack_payload)
    generated_text = pack_payload["generated_at_utc"]
    assert isinstance(generated_text, str)
    assert generated_text.endswith("Z")
    assert datetime.fromisoformat(generated_text.replace("Z", "+00:00")).utcoffset() == timedelta(0)
    assert pack.generated_at_utc == BASE
    nonce_hash = canonical_sha256(
        {
            "workspace": pack.workspace_receipt.canonical_receipt_hash,
            "binding": pack.provider_network_binding.canonical_binding_hash,
            "targets": pack.fixture_target_set.canonical_set_hash,
            "campaign_selection": pack.campaign_selection.canonical_selection_hash,
            "request": canonical_sha256(pack.request.fingerprint_material()),
            "generated_at": generated_text,
        }
    )
    assert pack.owner_authorization_candidate.authorization_nonce == f"owner-{nonce_hash[:40]}"
    assert pack.activation_candidate.activation_nonce == f"activation-{nonce_hash[24:64]}"
    assert result["pack_sha256"] == pack.canonical_pack_hash
    assert result["provider_http_calls"] == 0
    assert result["real_secret_reads"] == 0
    assert result["real_capture_calls"] == 0


def test_owner_review_pack_rejects_network_claim_bound_to_another_campaign(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    selected = selection.selected_candidate()
    wrong_claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=bundle.mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=bundle.workspace.canonical_receipt_hash,
        campaign_selection_sha256="9" * 64,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=bundle.mission_manifest.expires_at,
    )
    wrong_binding = ProviderNetworkBindingV1.issue(
        resolution_claim=wrong_claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=10),
        binding_ttl_seconds=660,
        resolved_ip_addresses=("8.8.8.8",),
    )
    with pytest.raises(OwnerReviewPackError, match="OWNER_REVIEW_PACK_INPUT_SCOPE_INVALID"):
        build_owner_review_pack_v1(
            workspace_receipt=bundle.workspace,
            mission_manifest=bundle.mission_manifest,
            provider_network_binding=wrong_binding,
            campaign_selection=selection,
            generated_at_utc=BASE,
            authorization_nonce="owner-pack-nonce-0000001",
            activation_nonce="activation-pack-nonce-001",
        )


def test_owner_review_pack_reports_exact_expired_network_binding_code(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    selected = selection.selected_candidate()
    expired_claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=bundle.mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=bundle.workspace.canonical_receipt_hash,
        campaign_selection_sha256=selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(minutes=1, seconds=5),
        mission_expires_at_utc=bundle.mission_manifest.expires_at,
    )
    expired_binding = ProviderNetworkBindingV1.issue(
        resolution_claim=expired_claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE,
        binding_ttl_seconds=60,
        resolved_ip_addresses=("8.8.8.8",),
    )
    with pytest.raises(OwnerReviewPackError, match="NETWORK_BINDING_EXPIRED"):
        build_owner_review_pack_v1(
            workspace_receipt=bundle.workspace,
            mission_manifest=bundle.mission_manifest,
            provider_network_binding=expired_binding,
            campaign_selection=selection,
            generated_at_utc=BASE,
            authorization_nonce="owner-pack-nonce-0000001",
            activation_nonce="activation-pack-nonce-001",
        )


def _issue_rehashed_owner_pack_tamper(
    pack: OwnerReviewPackV1,
    *,
    authorization_changes: dict[str, object] | None = None,
    activation_changes: dict[str, object] | None = None,
    plan_changes: dict[str, object] | None = None,
    item_changes: dict[str, object] | None = None,
    add_second_item: bool = False,
) -> OwnerReviewPackV1:
    authorization = OwnerAuthorizationV2.issue(
        **{
            **pack.owner_authorization_candidate.model_dump(
                mode="python",
                exclude={"canonical_authorization_hash"},
            ),
            **(authorization_changes or {}),
        }
    )
    expected_authorization_hash = authorization.expected_promoted_authorization_hash()
    activation_seed = ActivationEnvelopeV2.issue(
        **{
            **pack.activation_candidate.model_dump(
                mode="python",
                exclude={
                    "activation_scope_sha256",
                    "canonical_activation_hash",
                    "plan_sha256",
                },
            ),
            "authorization_id": authorization.authorization_id,
            "authorization_hash": expected_authorization_hash,
            "plan_sha256": "0" * 64,
            **(activation_changes or {}),
        }
    )
    requested_plan_changes = plan_changes or {}
    plan_id = str(requested_plan_changes.get("plan_id", pack.plan_candidate.plan_id))
    item = LivePlanItemV2.issue(
        **{
            **pack.plan_item_candidate.model_dump(
                mode="python",
                exclude={"canonical_item_hash"},
            ),
            "plan_id": plan_id,
            **(item_changes or {}),
        }
    )
    items = (item,)
    if add_second_item:
        items += (
            LivePlanItemV2.issue(
                **{
                    **item.model_dump(
                        mode="python",
                        exclude={"canonical_item_hash", "item_id", "sequence"},
                    ),
                    "item_id": f"{item.item_id}-second",
                    "sequence": 2,
                }
            ),
        )
    plan = LivePlanV2.issue(
        **{
            **pack.plan_candidate.model_dump(
                mode="python",
                exclude={"canonical_plan_hash"},
            ),
            "activation_id": activation_seed.activation_id,
            "activation_hash": activation_seed.activation_scope_sha256,
            "items": items,
            **requested_plan_changes,
        }
    )
    activation = ActivationEnvelopeV2.issue(
        **{
            **activation_seed.model_dump(
                mode="python",
                exclude={
                    "activation_scope_sha256",
                    "canonical_activation_hash",
                    "plan_sha256",
                },
            ),
            "plan_sha256": plan.canonical_plan_hash,
        }
    )
    pack_fields = {
        field: getattr(pack, field)
        for field in type(pack).model_fields
        if field != "canonical_pack_hash"
    }
    return OwnerReviewPackV1.issue(
        **{
            **pack_fields,
            "owner_authorization_candidate": authorization,
            "expected_owner_authorization_sha256": expected_authorization_hash,
            "activation_candidate": activation,
            "plan_candidate": plan,
            "plan_item_candidate": item,
        }
    )


def test_owner_review_pack_rejects_coherently_rehashed_scope_budget_and_id_tamper(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    selection = build_campaign_selection(bundle.workspace, bundle.mission_manifest)
    selected = selection.selected_candidate()
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=bundle.mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=bundle.workspace.canonical_receipt_hash,
        campaign_selection_sha256=selection.canonical_selection_hash,
        fixture_target_set_sha256=selected.fixture_target_set.canonical_set_hash,
        claimed_at_utc=BASE - timedelta(seconds=65),
        mission_expires_at_utc=bundle.mission_manifest.expires_at,
    )
    binding = ProviderNetworkBindingV1.issue(
        resolution_claim=claim,
        resolver_identity="TEST_OS_STUB_RESOLVER",
        observed_at_utc=BASE - timedelta(minutes=1),
        expires_at_utc=BASE + timedelta(minutes=10),
        binding_ttl_seconds=660,
        resolved_ip_addresses=("8.8.8.8",),
    )
    pack = build_owner_review_pack_v1(
        workspace_receipt=bundle.workspace,
        mission_manifest=bundle.mission_manifest,
        provider_network_binding=binding,
        campaign_selection=selection,
        generated_at_utc=BASE,
        authorization_nonce="owner-pack-nonce-0000001",
        activation_nonce="activation-pack-nonce-001",
    )
    other_git = os.path.normcase(os.path.abspath(str(tmp_path / "other-git.exe")))
    tamper_cases = (
        {"authorization_changes": {"authorized_main_sha": "b" * 40}},
        {
            "authorization_changes": {
                "approved_repository_root_fingerprint": "1" * 64,
            }
        },
        {"authorization_changes": {"approved_git_executable_path": other_git}},
        {"authorization_changes": {"approved_git_executable_sha256": "2" * 64}},
        {
            "authorization_changes": {
                "allowed_sport_keys": ("soccer_france_ligue_one",),
            }
        },
        {
            "authorization_changes": {
                "authorization_id": "owner-review-diverged-0001",
            }
        },
        {
            "activation_changes": {
                "activation_id": "activation-review-diverged-0001",
            }
        },
        {"plan_changes": {"plan_id": "plan-review-diverged-0001"}},
        {"plan_changes": {"created_at_utc": BASE - timedelta(seconds=1)}},
        {
            "authorization_changes": {
                "maximum_http_calls": 2,
                "maximum_plan_items": 2,
                "maximum_credits": 4,
            },
            "activation_changes": {
                "maximum_http_calls": 2,
                "maximum_credits": 4,
            },
            "plan_changes": {
                "maximum_http_calls": 2,
                "maximum_credits": 4,
            },
            "add_second_item": True,
        },
    )
    for tamper in tamper_cases:
        with pytest.raises(CaptureContractError, match="CAPTURE_CONTRACT_INVALID"):
            _issue_rehashed_owner_pack_tamper(pack, **tamper)


def test_v2_lineage_counts_are_rederived_from_mapping_on_store_and_load(
    tmp_path: Path,
) -> None:
    bundle = build_bundle(tmp_path)
    secret = SpySecretReader()
    clock = TickingClock()
    receipt = executor(
        bundle,
        secret,
        V2Transport(bundle.payload, clock),
        clock,
    ).execute_v2(
        mode=CaptureMode.LIVE_CANARY,
        authorization=bundle.authorization,
        activation=bundle.activation,
        plan=bundle.plan,
        item=bundle.item,
        request=bundle.request,
        fixture_target_set=bundle.targets,
        provider_network_binding=bundle.network_binding,
        mission_manifest=bundle.mission_manifest,
        review_candidate=bundle.review_candidate,
    )
    assert receipt.manifest_id is not None
    manifest = bundle.store.load_manifest(receipt.manifest_id)
    lineage = bundle.store._load_live_capture_lineage(manifest)
    assert isinstance(lineage, LiveCaptureLineageV2)
    bad = LiveCaptureLineageV2.issue(
        **{
            **lineage.model_dump(
                mode="python",
                exclude={"canonical_lineage_sha256"},
            ),
            "request": lineage.request,
            "admission_permit": lineage.admission_permit,
            "response_intake_claim": lineage.response_intake_claim,
            "scientific_admission": "NONE",
            "mapped_target_count": 0,
            "non_admitted_target_count": 1,
        }
    )
    with pytest.raises(CaptureStorageError, match="LIVE_V2_MAPPING_SUMMARY_MISMATCH"):
        bundle.store.store_live_capture_lineage(bad)

    lineage_path = bundle.store._path(f"live/capture-lineage/{manifest.snapshot_id}.json")
    lineage_path.write_bytes(canonical_json_bytes(bad.model_dump(mode="json")) + b"\n")
    with pytest.raises(CaptureStorageError, match="LIVE_V2_MAPPING_SUMMARY_MISMATCH"):
        bundle.store._load_live_capture_lineage(manifest)
