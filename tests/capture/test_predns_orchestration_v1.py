from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

import robin.capture.predns_orchestration as predns_module
import robin.capture.provider_network as provider_network_module
from robin.capture.bootstrap_contracts import (
    CampaignSelectionAuthorityV1,
    CampaignWindowSelectionV1,
    FirstC0CanarySelectionV1,
    OwnerReviewPackV1,
    ProviderNetworkBindingV1,
    ProviderNetworkResolutionClaimV1,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
)
from robin.capture.contracts import canonical_json_bytes
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS
from robin.capture.official_schedule_sources import (
    DFB_DATACENTER_HTML_V1,
    LALIGA_PUBLIC_MATCHES_JSON_V1,
    LEGA_SERIE_A_CALENDAR_PDF_V1,
    LIGUE1_PROGRAMMATION_HTML_V1,
    PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    OfficialHttpResponse,
    OfficialScheduleEvidence,
    OfficialScheduleSourceError,
    OfficialSourceSpec,
    SupportingOfficialRead,
    build_official_schedule_evidence,
    fetch_official_schedule_source,
    load_official_source_plan_bytes,
)
from robin.capture.predns_orchestration import (
    HistoricalMarkerExpectationV1,
    MarkerInspectionV1,
    PreDnsOrchestrationError,
    freeze_official_schedule_evidence_v1,
    inspect_provider_markers_read_only_v1,
    load_pre_dns_bundle_v1,
    prepare_owner_review_pack_inputs_v1,
    run_owner_review_pack_once_v1,
    verify_raw_official_evidence_v1,
)
from robin.capture.storage import exclusive_local_directory_fingerprint

BASE = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
MAIN_SHA = "2" * 40
MANIFEST_SOURCE_HASH = "2451cd643c2d3ffcd3c5cc9fcd4a5f81f785978e0aa20429b4d182ceb9b1f22b"
ADAPTERS = {
    "soccer_epl": PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    "soccer_spain_la_liga": LALIGA_PUBLIC_MATCHES_JSON_V1,
    "soccer_germany_bundesliga": DFB_DATACENTER_HTML_V1,
    "soccer_italy_serie_a": LEGA_SERIE_A_CALENDAR_PDF_V1,
    "soccer_france_ligue_one": LIGUE1_PROGRAMMATION_HTML_V1,
}
URLS = {
    "soccer_epl": "https://www.premierleague.com/en/news/season",
    "soccer_spain_la_liga": (
        "https://apim.laliga.com/public-service/api/v1/matches?"
        "subscription=laliga-easports-2026&competition=primera-division&limit=100&offset=300"
    ),
    "soccer_germany_bundesliga": "https://datencenter.dfb.de/competitions/12/seasons/current",
    "soccer_italy_serie_a": "https://images.legaseriea.it/calendar.pdf",
    "soccer_france_ligue_one": "https://ligue1.com/fr/articles/j2",
}
CONTENT_TYPES = {
    "soccer_epl": "text/html",
    "soccer_spain_la_liga": "application/json",
    "soccer_germany_bundesliga": "text/html",
    "soccer_italy_serie_a": "application/pdf",
    "soccer_france_ligue_one": "text/html",
}


def _load_first_c0_canary_cli() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "data-sourcing"
        / "prepare_first_c0_canary_selection_v1.py"
    )
    specification = importlib.util.spec_from_file_location(
        "predns_first_c0_canary_cli_tests",
        path,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


FIRST_C0_CANARY_CLI = _load_first_c0_canary_cli()


@dataclass
class Counter:
    value: int = 0


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SequenceClock:
    def __init__(self, values: Iterable[datetime]) -> None:
        self._values = iter(values)
        self._last = BASE

    def __call__(self) -> datetime:
        self._last = next(self._values, self._last)
        return self._last


class SequenceMonotonic:
    def __init__(self, values: Iterable[float] | None = None) -> None:
        self._values = iter(values or ())
        self._last = 0.0

    def __call__(self) -> float:
        self._last = next(self._values, self._last)
        return self._last


class SyntheticFetcher:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
        self.calls += 1
        supporting_raw = (
            b'<script id="__NEXT_DATA__">'
            b'{"runtimeConfig":{"backendSubscription":"public-test-subscription"}}'
            b"</script>"
        )
        supporting = (
            (
                SupportingOfficialRead(
                    requested_url="https://www.laliga.com/en-GB/laliga-easports/results",
                    final_url="https://www.laliga.com/en-GB/laliga-easports/results",
                    official_domain="www.laliga.com",
                    status_code=200,
                    content_type="text/html",
                    byte_count=len(supporting_raw),
                    raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
                    redirect_chain=(),
                ),
            )
            if source.adapter == LALIGA_PUBLIC_MATCHES_JSON_V1
            else ()
        )
        return OfficialHttpResponse(
            status_code=200,
            final_url=source.url,
            content_type=CONTENT_TYPES[source.sport_key],
            body=f"official-{source.sport_key}-{self.calls}".encode(),
            supporting_official_reads=supporting,
            supporting_official_raw_bytes=(supporting_raw,) if supporting else (),
        )


class FailingLaLigaFetcher:
    def __init__(self) -> None:
        self.physical_reads = 0

    def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
        self.physical_reads += 1
        if source.adapter == LALIGA_PUBLIC_MATCHES_JSON_V1:
            self.physical_reads += 1
            raise OfficialScheduleSourceError("LALIGA_MAIN_READ_FAILED_AFTER_BOOTSTRAP")
        raise AssertionError("LaLiga must remain the first source in the frozen plan")


class SyntheticEvidenceBuilder:
    def __init__(
        self,
        kickoffs_by_iteration: tuple[datetime, ...],
        *,
        fail_sport: str | None = None,
        stale: bool = False,
    ) -> None:
        self.kickoffs = kickoffs_by_iteration
        self.fail_sport = fail_sport
        self.stale = stale
        self.calls = 0
        self.horizons: list[tuple[datetime, datetime]] = []

    def __call__(
        self,
        source: OfficialSourceSpec,
        fetch_result: object,
        *,
        horizon_not_before_utc: datetime,
        horizon_expires_at_utc: datetime,
        pdf_text_extractor: object = None,
    ) -> OfficialScheduleEvidence:
        from robin.capture.official_schedule_sources import OfficialFetchResult, OfficialFixture

        assert isinstance(fetch_result, OfficialFetchResult)
        self.horizons.append((horizon_not_before_utc, horizon_expires_at_utc))
        if source.sport_key == self.fail_sport:
            raise OfficialScheduleSourceError("OFFICIAL_SCHEDULE_HORIZON_PARTIAL")
        iteration = min(self.calls // 5, len(self.kickoffs) - 1)
        kickoff = self.kickoffs[iteration]
        league_index = LIVE_ALLOWED_SPORT_KEYS.index(source.sport_key)
        self.calls += 1
        observed = fetch_result.receipt.observed_at_utc
        if self.stale:
            observed -= timedelta(minutes=31)
        return OfficialScheduleEvidence(
            sport_key=source.sport_key,
            source_authority=source.url,
            source_content_sha256=hashlib.sha256(fetch_result.raw_bytes).hexdigest(),
            source_observed_at_utc=observed,
            horizon_not_before_utc=horizon_not_before_utc,
            horizon_expires_at_utc=horizon_expires_at_utc,
            fixtures=(
                OfficialFixture(
                    home=f"Home {league_index}",
                    away=f"Away {league_index}",
                    kickoff_utc=kickoff,
                    official_id=f"fixture-{iteration}-{league_index}",
                ),
            ),
            adapter_revision=source.adapter,
            parser_metadata={"synthetic": True},
        )


def marker_ok() -> MarkerInspectionV1:
    return MarkerInspectionV1(
        historical_marker_unchanged=True,
        current_marker_present=False,
        historical_raw_sha256="a" * 64,
        historical_acl_sha256="b" * 64,
        historical_marker_path="synthetic-historical-marker",
        historical_authority_manifest_sha256="c" * 64,
        current_authority_manifest_sha256="d" * 64,
        current_local_marker="synthetic-local-marker",
        current_global_marker="synthetic-global-marker",
    )


def marker_inspector(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
) -> MarkerInspectionV1:
    assert workspace.authorized_main_sha == MAIN_SHA
    assert manifest.source_hash == MANIFEST_SOURCE_HASH
    return marker_ok()


def synthetic_raw_evidence_verifier(*args: object) -> None:
    assert len(args) == 6


def build_authority(
    tmp_path: Path,
) -> tuple[
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    control = tmp_path / "control"
    capture = tmp_path / "capture"
    for path in (repository, control, capture):
        path.mkdir(exist_ok=True)
    git_path = tmp_path / "git.exe"
    git_path.write_bytes(b"git")
    workspace = RealCaptureWorkspaceReceiptV1.issue(
        authorized_main_sha=MAIN_SHA,
        bootstrap_mode="VERIFY",
        bootstrap_tool_source_repository_root=os.path.abspath(repository),
        bootstrap_tool_loaded_from_runtime_repository=True,
        bootstrap_package_source_repository_root=os.path.abspath(repository),
        bootstrap_package_loaded_from_runtime_repository=True,
        authority_eligible_for_real_execution=True,
        prepared_at_utc=BASE - timedelta(minutes=5),
        runtime_repository_root=os.path.abspath(repository),
        repository_root_fingerprint="1" * 64,
        repository_security_descriptor_sha256="2" * 64,
        control_temp_root=os.path.abspath(control),
        control_temp_fingerprint=exclusive_local_directory_fingerprint(control),
        control_temp_security_descriptor_sha256="4" * 64,
        capture_root=os.path.abspath(capture),
        capture_root_fingerprint="5" * 64,
        capture_security_descriptor_sha256="6" * 64,
        git_executable_path=os.path.abspath(git_path),
        git_executable_sha256=hashlib.sha256(b"git").hexdigest(),
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
        source_hash=MANIFEST_SOURCE_HASH,
        expires_at=BASE + timedelta(days=1),
    )
    return workspace, manifest


def source_plan_bytes() -> bytes:
    return json.dumps(
        {
            "schema_version": "robin-official-schedule-source-plan-v1",
            "season": "2026-2027",
            "sources": {
                sport_key: {"adapter": ADAPTERS[sport_key], "url": URLS[sport_key]}
                for sport_key in LIVE_ALLOWED_SPORT_KEYS
            },
        },
        sort_keys=True,
    ).encode()


def test_historical_marker_is_bound_to_exact_authority_manifest_and_registry_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, manifest = build_authority(tmp_path / "authority")
    local_app_data = tmp_path / "local-app-data"
    registry = local_app_data / "RobinRealExecutionMissionClaimsV1"
    registry.mkdir(parents=True)
    historical_manifest_sha256 = "c" * 64
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=historical_manifest_sha256,
        workspace_receipt_sha256="1" * 64,
        campaign_selection_sha256="2" * 64,
        fixture_target_set_sha256="3" * 64,
        claimed_at_utc=BASE - timedelta(days=1),
        mission_expires_at_utc=BASE + timedelta(days=1),
    )
    payload = canonical_model_bytes(claim)
    historical = registry / (f"{manifest.mission_id.casefold()}-{historical_manifest_sha256}.json")
    historical.write_bytes(payload)
    monkeypatch.setattr(predns_module, "_local_app_data_readonly", lambda: local_app_data)
    expectation = HistoricalMarkerExpectationV1(
        path=historical,
        authority_manifest_sha256=historical_manifest_sha256,
        raw_sha256=hashlib.sha256(payload).hexdigest(),
    )

    inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert inspection.historical_marker_unchanged is True
    assert inspection.historical_authority_manifest_sha256 == historical_manifest_sha256
    assert inspection.current_authority_manifest_sha256 == manifest.canonical_manifest_sha256()

    substituted = tmp_path / "substituted-historical-marker.json"
    substituted.write_bytes(payload)
    substituted_inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=replace(expectation, path=substituted),
    )
    assert substituted_inspection.historical_marker_unchanged is False


def corpus_bytes(observed_at: datetime = BASE) -> bytes:
    return json.dumps(
        {
            "schema_version": "robin-owner-observed-scientific-corpus-v1",
            "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
            "admitted_fixture_counts": {sport_key: 0 for sport_key in LIVE_ALLOWED_SPORT_KEYS},
        },
        sort_keys=True,
    ).encode()


def reviews() -> dict[str, bytes]:
    return {
        name: json.dumps(
            {
                "reviewer": name,
                "verdict": "ACCEPT",
                "p0": 0,
                "p1": 0,
                "p2": 0,
                "open_threads": 0,
            },
            sort_keys=True,
        ).encode()
        for name in ("DP6", "C4", "C2", "A2")
    }


def canonical_model_bytes(model: object) -> bytes:
    assert hasattr(model, "model_dump")
    return canonical_json_bytes(model.model_dump(mode="json")) + b"\n"


def rewrite_bundle_artifact(bundle: Path, name: str, payload: bytes) -> None:
    (bundle / name).write_bytes(payload)
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifacts"][name] = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_count": len(payload),
    }
    without_hash = {
        key: value for key, value in manifest.items() if key != "canonical_bundle_manifest_sha256"
    }
    manifest["canonical_bundle_manifest_sha256"] = hashlib.sha256(
        canonical_json_bytes(without_hash) + b"\n"
    ).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")


def run_predns(
    tmp_path: Path,
    *,
    builder: SyntheticEvidenceBuilder,
    workspace_validator: object = lambda workspace: None,
    monotonic: SequenceMonotonic | None = None,
    source_plan_payload: bytes | None = None,
    clock: Callable[[], datetime] | None = None,
):
    workspace, manifest = build_authority(tmp_path)
    fetcher = SyntheticFetcher()
    result = prepare_owner_review_pack_inputs_v1(
        workspace_receipt=workspace,
        workspace_receipt_bytes=canonical_model_bytes(workspace),
        mission_manifest=manifest,
        mission_manifest_bytes=canonical_model_bytes(manifest),
        source_plan_bytes=source_plan_payload or source_plan_bytes(),
        corpus_evidence_reader=lambda: corpus_bytes(),
        output_parent=Path(workspace.control_temp_root),
        reviews=reviews(),
        fetcher=fetcher,
        marker_inspector=marker_inspector,
        clock=clock or FixedClock(BASE),
        monotonic=monotonic or SequenceMonotonic(),
        workspace_validator=workspace_validator,
        evidence_builder=builder,
    )
    return result, fetcher, workspace, manifest


def test_predns_immediate_success_has_exact_budgets_and_immutable_bundle(tmp_path: Path) -> None:
    builder = SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),))
    result, fetcher, _, manifest = run_predns(
        tmp_path,
        builder=builder,
    )
    assert result.status == "PRE_DNS_READY_NOW"
    assert result.counters.official_reads == fetcher.calls == 5
    assert result.counters.supporting_official_reads == 1
    assert set(builder.horizons) == {(BASE, BASE + timedelta(days=8))}
    assert BASE + timedelta(days=8) > manifest.expires_at
    assert BASE + timedelta(days=8) < datetime(2026, 9, 4, tzinfo=UTC)
    assert result.counters.corpus_snapshots == result.counters.corpus_validations == 2
    assert result.counters.target_set_freezes == 5
    assert result.counters.selector_invocations == 2
    assert result.bundle_directory is not None
    loaded = load_pre_dns_bundle_v1(
        result.bundle_directory,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert (
        loaded.campaign_selection.canonical_selection_hash
        == result.selection.canonical_selection_hash
    )
    assert loaded.marker_inspection.current_marker_present is False


def test_predns_bundle_recomposes_reconciliation_and_supporting_raw_bytes(
    tmp_path: Path,
) -> None:
    reconciliation_result, _, _, _ = run_predns(
        tmp_path / "reconciliation",
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert reconciliation_result.bundle_directory is not None
    reconciliation_path = (
        reconciliation_result.bundle_directory / "official-schedule-reconciliation.json"
    )
    reconciliation = json.loads(reconciliation_path.read_bytes())
    reconciliation["fixture_counts"]["soccer_epl"] += 1
    rewrite_bundle_artifact(
        reconciliation_result.bundle_directory,
        reconciliation_path.name,
        canonical_json_bytes(reconciliation) + b"\n",
    )
    with pytest.raises(PreDnsOrchestrationError, match="OFFICIAL_RECONCILIATION_INVALID"):
        load_pre_dns_bundle_v1(
            reconciliation_result.bundle_directory,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )

    support_result, _, _, _ = run_predns(
        tmp_path / "supporting",
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert support_result.bundle_directory is not None
    support_name = "raw-supporting-soccer_spain_la_liga-01.bin"
    support_path = support_result.bundle_directory / support_name
    rewrite_bundle_artifact(
        support_result.bundle_directory,
        support_name,
        support_path.read_bytes() + b"tampered",
    )
    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_BUNDLE_AUTHORITY_MISMATCH"):
        load_pre_dns_bundle_v1(
            support_result.bundle_directory,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_predns_crossed_kickoff_invalidates_then_succeeds_without_backfill(
    tmp_path: Path,
) -> None:
    builder = SyntheticEvidenceBuilder(
        (BASE + timedelta(seconds=299), BASE + timedelta(minutes=135))
    )
    result, fetcher, _, _ = run_predns(tmp_path, builder=builder)
    assert result.status == "PRE_DNS_READY_NOW"
    assert result.counters.iterations == 2
    assert result.counters.official_reads == fetcher.calls == 10
    assert result.counters.corpus_snapshots == 4
    assert result.counters.target_set_freezes == 5
    assert result.counters.selector_invocations == 2
    assert "ANTI_ROLLOVER_SAFETY_CUTOFF" in result.iteration_codes
    assert result.selection is not None
    assert all(
        target.official_kickoff_utc == BASE + timedelta(minutes=135)
        for target_set in result.selection.source_target_sets
        for target in target_set.targets
    )


def test_predns_future_window_has_exact_recommended_refresh(tmp_path: Path) -> None:
    result, _, _, _ = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=180),)),
    )
    assert result.status == "PRE_DNS_FUTURE_WINDOW_PLANNED"
    assert result.recommended_refresh_utc == BASE + timedelta(minutes=40)
    assert result.selection is not None
    assert result.selection.selected_candidate().status == "FUTURE_NOT_OPEN"


@pytest.mark.parametrize(
    ("kickoff", "publication_time", "expected_code"),
    (
        (
            BASE + timedelta(minutes=135),
            BASE + timedelta(minutes=31),
            "CAMPAIGN_NO_REMAINING_SELECTABLE_CANDIDATE",
        ),
        (
            BASE + timedelta(minutes=180),
            BASE + timedelta(minutes=46),
            "CAPTURE_CONTRACT_INVALID",
        ),
    ),
)
def test_predns_revalidates_time_after_selection_before_bundle_publication(
    tmp_path: Path,
    kickoff: datetime,
    publication_time: datetime,
    expected_code: str,
) -> None:
    clock = SequenceClock((*([BASE] * 11), publication_time))
    result, _, _, _ = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((kickoff,)),
        clock=clock,
    )
    assert result.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert result.bundle_directory is None
    assert expected_code in result.iteration_codes


def test_predns_insufficient_margin_and_stale_source_fail_closed(tmp_path: Path) -> None:
    insufficient, _, _, _ = run_predns(
        tmp_path / "margin",
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=130),)),
    )
    assert insufficient.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert "PRE_DNS_OPEN_MARGIN_INSUFFICIENT" in insufficient.iteration_codes
    stale, _, _, _ = run_predns(
        tmp_path / "stale",
        builder=SyntheticEvidenceBuilder(
            (BASE + timedelta(minutes=135),),
            stale=True,
        ),
    )
    assert stale.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert stale.counters.target_set_freezes == 0
    assert stale.counters.selector_invocations == 0


def test_predns_partial_source_and_workspace_drift_stop_before_selector(
    tmp_path: Path,
) -> None:
    partial, _, _, _ = run_predns(
        tmp_path / "partial",
        builder=SyntheticEvidenceBuilder(
            (BASE + timedelta(minutes=135),),
            fail_sport="soccer_germany_bundesliga",
        ),
    )
    assert partial.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert partial.counters.selector_invocations == 0
    drift_calls = Counter()

    def drift_validator(workspace: RealCaptureWorkspaceReceiptV1) -> None:
        drift_calls.value += 1
        raise RuntimeError("drift")

    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_WORKSPACE_DRIFT"):
        run_predns(
            tmp_path / "drift",
            builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
            workspace_validator=drift_validator,
        )
    assert drift_calls.value == 1


def test_predns_freeze_to_selector_over_thirty_seconds_invalidates(tmp_path: Path) -> None:
    result, _, _, _ = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
        monotonic=SequenceMonotonic((0.0, 31.0, 31.0, 62.0)),
    )
    assert result.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert result.counters.selector_invocations == 0
    assert "ITERATION_INVALIDATED" in result.iteration_codes


def test_predns_provider_hostname_is_refused_before_connection(tmp_path: Path) -> None:
    forbidden_plan = source_plan_bytes().replace(
        URLS["soccer_epl"].encode(),
        b"https://api.the-odds-api.com/v4/sports",
    )
    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_INPUT_AUTHORITY_INVALID"):
        run_predns(
            tmp_path,
            builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
            source_plan_payload=forbidden_plan,
        )


def test_predns_requires_a2_accept_before_any_official_read(tmp_path: Path) -> None:
    workspace, manifest = build_authority(tmp_path)
    for review_payloads in (
        {name: payload for name, payload in reviews().items() if name != "A2"},
        {
            **reviews(),
            "A2": json.dumps(
                {
                    "reviewer": "A2",
                    "verdict": "REWORK",
                    "p0": 0,
                    "p1": 1,
                    "p2": 0,
                    "open_threads": 1,
                },
                sort_keys=True,
            ).encode(),
        },
    ):
        fetcher = SyntheticFetcher()
        with pytest.raises(
            PreDnsOrchestrationError,
            match=(
                "PRE_DNS_INPUT_AUTHORITY_INVALID|PRE_DNS_REVIEW_INVALID|PRE_DNS_REVIEW_NOT_ACCEPTED"
            ),
        ):
            prepare_owner_review_pack_inputs_v1(
                workspace_receipt=workspace,
                workspace_receipt_bytes=canonical_model_bytes(workspace),
                mission_manifest=manifest,
                mission_manifest_bytes=canonical_model_bytes(manifest),
                source_plan_bytes=source_plan_bytes(),
                corpus_evidence_reader=lambda: corpus_bytes(),
                output_parent=Path(workspace.control_temp_root),
                reviews=review_payloads,
                fetcher=fetcher,
                marker_inspector=marker_inspector,
                clock=FixedClock(BASE),
                workspace_validator=lambda _: None,
                evidence_builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
            )
        assert fetcher.calls == 0


def test_predns_rejects_output_outside_control_root_before_fetch(tmp_path: Path) -> None:
    workspace, manifest = build_authority(tmp_path / "authority")
    fetcher = SyntheticFetcher()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_OUTPUT_OUTSIDE_CONTROL_TEMP"):
        prepare_owner_review_pack_inputs_v1(
            workspace_receipt=workspace,
            workspace_receipt_bytes=canonical_model_bytes(workspace),
            mission_manifest=manifest,
            mission_manifest_bytes=canonical_model_bytes(manifest),
            source_plan_bytes=source_plan_bytes(),
            corpus_evidence_reader=lambda: corpus_bytes(),
            output_parent=outside,
            reviews=reviews(),
            fetcher=fetcher,
            marker_inspector=marker_inspector,
            clock=FixedClock(BASE),
            workspace_validator=lambda _: None,
            evidence_builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
        )
    assert fetcher.calls == 0
    assert tuple(outside.iterdir()) == ()


def test_default_raw_verifier_reparses_laliga_evidence(tmp_path: Path) -> None:
    source = load_official_source_plan_bytes(source_plan_bytes()).source("soccer_spain_la_liga")
    clubs = [f"Liga Club {index:02d}" for index in range(20)]
    rotating = list(clubs)
    matches: list[dict[str, object]] = []
    latest = BASE + timedelta(days=10)
    for week in range(1, 9):
        for game_index in range(10):
            home = rotating[game_index]
            away = rotating[-game_index - 1]
            index = len(matches)
            matches.append(
                {
                    "id": f"laliga-{index:03d}",
                    "competition": {"slug": "primera-division"},
                    "date": (latest - timedelta(days=week - 1, minutes=game_index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "home_team": {"name": home},
                    "away_team": {"name": away},
                    "gameweek": {"week": week},
                }
            )
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    raw = json.dumps({"total": 380, "matches": matches}, sort_keys=True).encode()
    supporting_raw = (
        b'<script id="__NEXT_DATA__">'
        b'{"runtimeConfig":{"backendSubscription":"public-test-subscription"}}'
        b"</script>"
    )
    supporting = SupportingOfficialRead(
        requested_url="https://www.laliga.com/en-GB/laliga-easports/results",
        final_url="https://www.laliga.com/en-GB/laliga-easports/results",
        official_domain="www.laliga.com",
        status_code=200,
        content_type="text/html",
        byte_count=len(supporting_raw),
        raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
        redirect_chain=(),
    )

    class StaticFetcher:
        def fetch(self, requested: OfficialSourceSpec) -> OfficialHttpResponse:
            assert requested == source
            return OfficialHttpResponse(
                200,
                source.url,
                "application/json",
                raw,
                supporting_official_reads=(supporting,),
                supporting_official_raw_bytes=(supporting_raw,),
            )

    fetched = fetch_official_schedule_source(
        source,
        fetcher=StaticFetcher(),
        observed_at_utc=BASE,
    )
    evidence = build_official_schedule_evidence(
        source,
        fetched,
        horizon_not_before_utc=BASE,
        horizon_expires_at_utc=BASE + timedelta(days=14),
    )
    workspace, _ = build_authority(tmp_path / "raw-verifier-authority")
    target_set = freeze_official_schedule_evidence_v1(
        evidence,
        workspace_receipt=workspace,
        created_at_utc=BASE,
    )
    receipt_payload = canonical_json_bytes(fetched.receipt.to_json()) + b"\n"
    evidence_payload = canonical_json_bytes(evidence.to_json()) + b"\n"
    verify_raw_official_evidence_v1(
        source,
        raw,
        receipt_payload,
        evidence_payload,
        target_set,
        (supporting_raw,),
    )
    with pytest.raises(PreDnsOrchestrationError, match="OFFICIAL_SCHEDULE_REPARSE_MISMATCH"):
        verify_raw_official_evidence_v1(
            source,
            raw,
            receipt_payload,
            evidence_payload.replace(b'"Liga Club 00"', b'"Tampered"', 1),
            target_set,
            (supporting_raw,),
        )
    for supporting_payloads in ((), (supporting_raw + b"tampered",)):
        with pytest.raises(
            PreDnsOrchestrationError,
            match="OFFICIAL_SUPPORTING_READ_INVALID|OFFICIAL_FETCH_RECEIPT_INVALID",
        ):
            verify_raw_official_evidence_v1(
                source,
                raw,
                receipt_payload,
                evidence_payload,
                target_set,
                supporting_payloads,
            )


def test_predns_reserves_laliga_supporting_read_even_when_main_read_fails(
    tmp_path: Path,
) -> None:
    workspace, manifest = build_authority(tmp_path)
    fetcher = FailingLaLigaFetcher()
    result = prepare_owner_review_pack_inputs_v1(
        workspace_receipt=workspace,
        workspace_receipt_bytes=canonical_model_bytes(workspace),
        mission_manifest=manifest,
        mission_manifest_bytes=canonical_model_bytes(manifest),
        source_plan_bytes=source_plan_bytes(),
        corpus_evidence_reader=lambda: corpus_bytes(),
        output_parent=Path(workspace.control_temp_root),
        reviews=reviews(),
        fetcher=fetcher,
        marker_inspector=marker_inspector,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        evidence_builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert result.status == "PRE_DNS_CONVERGENCE_EXHAUSTED"
    assert result.counters.official_reads == result.counters.supporting_official_reads == 4
    assert fetcher.physical_reads == 8
    assert (
        result.counters.official_reads + result.counters.supporting_official_reads
        == fetcher.physical_reads
        <= 20
    )


def fake_binding_preparer(
    *,
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    mission_manifest: RealExecutionMissionManifestV1,
    campaign_selection: CampaignSelectionAuthorityV1,
    output_path: Path,
    resolver: Callable[[str, int, int, int, int], Iterable[tuple[object, ...]]],
    clock: Callable[[], datetime],
    binding_ttl_seconds: int,
) -> ProviderNetworkBindingV1:
    claimed = clock()
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=mission_manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace_receipt.canonical_receipt_hash,
        campaign_selection_sha256=campaign_selection.canonical_selection_hash,
        fixture_target_set_sha256=(
            campaign_selection.selected_candidate().fixture_target_set.canonical_set_hash
        ),
        claimed_at_utc=claimed,
        mission_expires_at_utc=mission_manifest.expires_at,
    )
    (output_path.parent / "provider-network-resolution-one-shot-v1.json").write_bytes(
        canonical_model_bytes(claim)
    )
    tuple(resolver("api.the-odds-api.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, 0))
    binding = ProviderNetworkBindingV1.issue(
        resolution_claim=claim,
        resolver_identity="SYNTHETIC_OS_STUB_RESOLVER",
        observed_at_utc=claimed,
        expires_at_utc=claimed + timedelta(seconds=binding_ttl_seconds),
        binding_ttl_seconds=binding_ttl_seconds,
        resolved_ip_addresses=("8.8.8.8",),
    )
    output_path.write_bytes(canonical_model_bytes(binding))
    return binding


def synthetic_resolver(
    host: str,
    port: int,
    family: int,
    socket_type: int,
    protocol: int,
) -> Iterable[tuple[object, ...]]:
    assert (host, port, family, socket_type, protocol) == (
        "api.the-odds-api.com",
        443,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
        0,
    )
    return ((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),)


def build_ready_bundle(tmp_path: Path):
    result, _, workspace, manifest = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert result.bundle_directory is not None
    return result.bundle_directory, workspace, manifest


def _canary_round_robin_rounds(
    clubs: list[str],
    count: int,
) -> list[list[tuple[str, str]]]:
    rotating = list(clubs)
    rounds: list[list[tuple[str, str]]] = []
    for _ in range(count):
        rounds.append(
            [(rotating[index], rotating[-index - 1]) for index in range(len(rotating) // 2)]
        )
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    return rounds


def _canary_laliga_payload(earliest: datetime) -> bytes:
    latest = earliest + timedelta(days=7)
    clubs = [f"Canary Liga Club {index:02d}" for index in range(20)]
    matches: list[dict[str, object]] = []
    for week_index, games in enumerate(_canary_round_robin_rounds(clubs, 8), start=1):
        for home, away in games:
            matches.append(
                {
                    "id": f"canary-laliga-{len(matches):03d}",
                    "competition": {"slug": "primera-division"},
                    "date": (latest - timedelta(days=week_index - 1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "home_team": {"name": home},
                    "away_team": {"name": away},
                    "gameweek": {"week": week_index},
                }
            )
    return json.dumps({"total": 380, "matches": matches}, sort_keys=True).encode()


def build_ready_canary_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    refresh_cycle: bool = False,
) -> tuple[
    Path,
    RealCaptureWorkspaceReceiptV1,
    RealExecutionMissionManifestV1,
    Callable[
        [RealCaptureWorkspaceReceiptV1, RealExecutionMissionManifestV1],
        MarkerInspectionV1,
    ],
    datetime,
]:
    workspace, manifest = build_authority(tmp_path)
    control = Path(workspace.control_temp_root)
    local_app_data = tmp_path / "local-app-data"
    local_app_data.mkdir()
    global_marker = (
        local_app_data
        / "RobinRealExecutionMissionClaimsV1"
        / (f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json")
    )
    local_marker = control / "provider-network-resolution-one-shot-v1.json"
    monkeypatch.setattr(predns_module, "_local_app_data_readonly", lambda: local_app_data)
    source_url = URLS["soccer_spain_la_liga"]
    source_plan = json.dumps(
        {
            "schema_version": "robin-first-c0-canary-source-plan-v1",
            "sport_key": "soccer_spain_la_liga",
            "adapter": LALIGA_PUBLIC_MATCHES_JSON_V1,
            "url": source_url,
        },
        sort_keys=True,
    ).encode()
    raw = _canary_laliga_payload(
        BASE + timedelta(hours=3) if refresh_cycle else BASE + timedelta(minutes=135)
    )
    supporting_raw = (
        b'<script id="__NEXT_DATA__">'
        b'{"runtimeConfig":{"backendSubscription":"laliga-easports-2026"}}'
        b"</script>"
    )
    supporting = SupportingOfficialRead(
        requested_url="https://www.laliga.com/en-GB/laliga-easports/results",
        final_url="https://www.laliga.com/en-GB/laliga-easports/results",
        official_domain="www.laliga.com",
        status_code=200,
        content_type="text/html",
        byte_count=len(supporting_raw),
        raw_sha256=hashlib.sha256(supporting_raw).hexdigest(),
        redirect_chain=(),
    )

    class CanaryFetcher:
        def fetch(self, source: OfficialSourceSpec) -> OfficialHttpResponse:
            assert source.url == source_url
            return OfficialHttpResponse(
                status_code=200,
                final_url=source.url,
                content_type="application/json",
                body=raw,
                supporting_official_reads=(supporting,),
                supporting_official_raw_bytes=(supporting_raw,),
            )

    frozen_marker = {
        "schema_version": "robin-first-c0-canary-marker-inspection-v1",
        "local_marker_path": str(local_marker.absolute()),
        "global_marker_path": str(global_marker.absolute()),
        "local_marker_present": False,
        "global_marker_present": False,
        "inspected_read_only": True,
    }
    arguments = {
        "workspace_receipt": workspace,
        "workspace_receipt_bytes": canonical_model_bytes(workspace),
        "mission_manifest": manifest,
        "mission_manifest_bytes": canonical_model_bytes(manifest),
        "source_plan_bytes": source_plan,
        "fetcher": CanaryFetcher(),
        "workspace_validator": lambda _: None,
        "marker_inspector": lambda _workspace, _manifest: frozen_marker,
    }
    result = FIRST_C0_CANARY_CLI.prepare_first_c0_canary_selection_v1(
        **arguments,
        output_directory=control / "first-c0-canary-ready-bundle",
        clock=FixedClock(BASE),
    )
    if refresh_cycle:
        assert result.status == "CANARY_FUTURE_WINDOW"
        result = FIRST_C0_CANARY_CLI.prepare_first_c0_canary_selection_v1(
            **arguments,
            output_directory=control / "first-c0-canary-refreshed-bundle",
            clock=FixedClock(result.recommended_refresh_utc),
        )
    assert result.status in {"CANARY_READY_NOW", "CANARY_FUTURE_WINDOW"}
    execution_at = result.selection.selected_not_before_utc

    def current_marker_inspector(
        _workspace: RealCaptureWorkspaceReceiptV1,
        _manifest: RealExecutionMissionManifestV1,
    ) -> MarkerInspectionV1:
        return replace(
            marker_ok(),
            current_marker_present=local_marker.exists() or global_marker.exists(),
            current_authority_manifest_sha256=manifest.canonical_manifest_sha256(),
            current_local_marker=str(local_marker.absolute()),
            current_global_marker=str(global_marker.absolute()),
        )

    return (
        result.bundle_directory,
        workspace,
        manifest,
        current_marker_inspector,
        execution_at,
    )


def test_canary_refresh_cycle_bundle_has_closed_read_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _, _, _, _ = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(bundle)
    assert isinstance(loaded.campaign_selection, FirstC0CanarySelectionV1)
    assert loaded.manifest["preparation_cycle"] == 2
    assert loaded.manifest["cumulative_official_reads"] == 4
    names = {path.name for path in bundle.iterdir()}
    assert "prior-cycle-01-read-reservation.json" in names
    assert "prior-cycle-01-attempt-receipt.json" in names


def _write_canonical_test_json(path: Path, payload: object) -> bytes:
    encoded = canonical_json_bytes(payload) + b"\n"
    path.write_bytes(encoded)
    return encoded


@pytest.mark.parametrize("schema_mode", ["missing", "unknown"])
def test_canary_bundle_loader_rejects_missing_or_unknown_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema_mode: str,
) -> None:
    bundle, _, _, _, _ = build_ready_canary_bundle(tmp_path, monkeypatch)
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if schema_mode == "missing":
        del manifest["schema_version"]
    else:
        manifest["schema_version"] = "robin-first-c0-canary-bundle-v999"
    _write_canonical_test_json(manifest_path, manifest)

    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_BUNDLE_MANIFEST_INVALID"):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_canary_bundle_loader_rejects_artifact_hash_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _, _, _, _ = build_ready_canary_bundle(tmp_path, monkeypatch)
    raw_path = bundle / "official-source-raw.bin"
    raw_path.write_bytes(raw_path.read_bytes() + b"tamper")

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_BUNDLE_ARTIFACT_HASH_MISMATCH",
    ):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


@pytest.mark.parametrize("receipt_mode", ["missing", "wrong-backlink"])
def test_canary_bundle_loader_requires_current_receipt_and_manifest_backlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_mode: str,
) -> None:
    bundle, workspace, _, _, _ = build_ready_canary_bundle(tmp_path, monkeypatch)
    receipt_path = (
        Path(workspace.control_temp_root) / "first-c0-canary-cycle-01-attempt-receipt-v1.json"
    )
    if receipt_mode == "missing":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_bytes())
        receipt["bundle_manifest_sha256"] = "0" * 64
        _write_canonical_test_json(receipt_path, receipt)

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_BUNDLE_LINEAGE_INVALID",
    ):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_canary_bundle_loader_rejects_rehashed_cycle_transition_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, _, _, _ = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    current_reservation_path = bundle / "current-cycle-read-reservation.json"
    manifest_path = bundle / "bundle-manifest.json"
    current_attempt_path = (
        Path(workspace.control_temp_root) / "first-c0-canary-cycle-02-attempt-receipt-v1.json"
    )

    current_reservation = json.loads(current_reservation_path.read_bytes())
    assert current_reservation["cycle_role"] == "PRIMARY_REFRESH"
    current_reservation["cycle_role"] = "PRIMARY_RETRY"
    current_reservation_bytes = _write_canonical_test_json(
        current_reservation_path,
        current_reservation,
    )

    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifact_sha256"][current_reservation_path.name] = hashlib.sha256(
        current_reservation_bytes
    ).hexdigest()
    manifest_bytes = _write_canonical_test_json(manifest_path, manifest)

    current_attempt = json.loads(current_attempt_path.read_bytes())
    assert current_attempt["cycle_role"] == "PRIMARY_REFRESH"
    current_attempt["cycle_role"] = "PRIMARY_RETRY"
    current_attempt["reservation_sha256"] = hashlib.sha256(current_reservation_bytes).hexdigest()
    current_attempt["bundle_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    _write_canonical_test_json(current_attempt_path, current_attempt)

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_BUNDLE_LINEAGE_INVALID",
    ):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_canary_bundle_loader_rejects_rehashed_manifest_authority_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, _, _, _ = build_ready_canary_bundle(tmp_path, monkeypatch)
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["fixture_target_set_sha256"] = "0" * 64
    manifest_bytes = _write_canonical_test_json(manifest_path, manifest)

    current_attempt_path = (
        Path(workspace.control_temp_root) / "first-c0-canary-cycle-01-attempt-receipt-v1.json"
    )
    current_attempt = json.loads(current_attempt_path.read_bytes())
    current_attempt["bundle_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    _write_canonical_test_json(current_attempt_path, current_attempt)

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_BUNDLE_AUTHORITY_MISMATCH",
    ):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_canary_bundle_runs_through_atomic_runner_with_one_injected_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
    )
    loaded = load_pre_dns_bundle_v1(bundle)
    assert isinstance(loaded.campaign_selection, FirstC0CanarySelectionV1)
    binding = Path(workspace.control_temp_root) / "canary-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "canary-owner-review-pack"
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack_directory,
        resolver=synthetic_resolver,
        marker_inspector=current_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
    )
    assert result.status == "OWNER_REVIEW_PACK_CREATED", result.preflight.errors
    assert result.resolver_operations == result.pack_builds == 1
    artifacts = tuple(
        path for path in pack_directory.iterdir() if path.name != "execution-receipt.json"
    )
    assert len(artifacts) == 11
    pack_paths = tuple(pack_directory.glob("owner-review-pack-*.json"))
    assert len(pack_paths) == 1
    pack = OwnerReviewPackV1.model_validate_json(pack_paths[0].read_bytes())
    assert isinstance(pack.campaign_selection, FirstC0CanarySelectionV1)
    assert pack.campaign_selection == loaded.campaign_selection
    assert pack.owner_authorization_candidate.maximum_http_calls == 1
    assert pack.owner_authorization_candidate.maximum_credits == 1
    assert pack.owner_authorization_candidate.authorization_status == "OWNER_REVIEW_CANDIDATE"
    assert pack.owner_authorization_candidate.review_candidate_sha256 is None


def test_canary_runner_forgotten_resolver_is_denied_and_marker_is_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_network_guard: object,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
    )

    def forgotten_stub_resolver(
        host: str,
        port: int,
        family: int,
        socket_type: int,
        protocol: int,
    ) -> Iterable[tuple[object, ...]]:
        return socket.getaddrinfo(host, port, family, socket_type, protocol)

    binding = Path(workspace.control_temp_root) / "forgotten-stub-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "forgotten-stub-pack"
    assert hasattr(capture_network_guard, "expect_forbidden")
    with capture_network_guard.expect_forbidden():
        result = run_owner_review_pack_once_v1(
            bundle_directory=bundle,
            workspace_receipt=workspace,
            mission_manifest=manifest,
            output_binding_path=binding,
            output_pack_directory=pack_directory,
            resolver=forgotten_stub_resolver,
            marker_inspector=current_marker_inspector,
            execute=True,
            owner_present_for_review=True,
            clock=FixedClock(execution_at),
            workspace_validator=lambda _: None,
            binding_preparer=fake_binding_preparer,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "TEST_REAL_NETWORK_FORBIDDEN"
    assert result.resolver_operations == 1
    assert result.pack_builds == 0
    assert getattr(capture_network_guard, "expected_attempts") == 1
    assert not binding.exists() and not pack_directory.exists()
    assert result.receipt_path is not None
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure_phase"] == "RESOLVER"
    assert receipt["resolver_completed"] is False
    assert receipt["binding_persisted"] is False
    assert (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    ).is_file()


def test_canary_post_dns_pack_failure_is_one_shot_and_non_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
    )
    resolver_calls = Counter()

    def resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        return synthetic_resolver(*args)  # type: ignore[arg-type]

    def failing_pack_builder(**_kwargs: object) -> object:
        raise PreDnsOrchestrationError("SYNTHETIC_CANARY_PACK_FAILURE")

    binding = Path(workspace.control_temp_root) / "failed-pack-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "failed-canary-pack"
    first = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack_directory,
        resolver=resolver,
        marker_inspector=current_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        pack_builder=failing_pack_builder,  # type: ignore[arg-type]
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert first.status == "POST_DNS_HARD_STOP"
    assert first.hard_stop_code == "SYNTHETIC_CANARY_PACK_FAILURE"
    assert first.resolver_operations == first.pack_builds == resolver_calls.value == 1
    assert first.receipt_path is not None and first.receipt_path.is_file()
    assert (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    ).is_file()
    second = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack_directory,
        resolver=resolver,
        marker_inspector=current_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        pack_builder=failing_pack_builder,  # type: ignore[arg-type]
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert second.status == "PREFLIGHT_REJECTED"
    assert second.resolver_operations == second.pack_builds == 0
    assert resolver_calls.value == 1


def test_canary_runner_rechecks_840_second_margin_after_marker_before_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
    )
    underlying_resolver_calls = Counter()

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        underlying_resolver_calls.value += 1
        raise AssertionError("resolver must not run below the canary margin")

    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    usable_expires = loaded.campaign_selection.selected_candidate().usable_expires_at_utc
    clock = SequenceClock(
        (
            execution_at,
            execution_at,
            execution_at,
            usable_expires - timedelta(seconds=841),
            usable_expires - timedelta(seconds=839),
        )
    )
    binding = Path(workspace.control_temp_root) / "eroded-margin-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "eroded-margin-pack"
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack_directory,
        resolver=forbidden_resolver,
        marker_inspector=current_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=clock,
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "OWNER_REVIEW_USABLE_MARGIN_INSUFFICIENT"
    assert result.resolver_operations == underlying_resolver_calls.value == 0
    assert (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    ).is_file()


def test_runner_preflight_invalid_and_owner_presence_gate_use_zero_dns(tmp_path: Path) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    resolver_calls = Counter()

    def resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        return ()

    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"
    binding.write_bytes(b"already")
    invalid = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert invalid.status == "PREFLIGHT_REJECTED"
    assert invalid.resolver_operations == resolver_calls.value == 0
    binding.unlink()
    missing_owner = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=False,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert missing_owner.status == "PREFLIGHT_REJECTED"
    assert missing_owner.resolver_operations == resolver_calls.value == 0
    insufficient_ttl = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        binding_ttl_seconds=600,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert insufficient_ttl.status == "PREFLIGHT_REJECTED"
    assert insufficient_ttl.resolver_operations == resolver_calls.value == 0
    fractional_ttl = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        binding_ttl_seconds=840.5,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert fractional_ttl.status == "PREFLIGHT_REJECTED"
    assert fractional_ttl.resolver_operations == resolver_calls.value == 0


def test_runner_rejects_historical_marker_authority_substitution_before_dns(
    tmp_path: Path,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    resolver_calls = Counter()

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        del args
        resolver_calls.value += 1
        return ()

    def substituted_marker_inspector(
        _workspace: RealCaptureWorkspaceReceiptV1,
        _manifest: RealExecutionMissionManifestV1,
    ) -> MarkerInspectionV1:
        return replace(marker_ok(), historical_authority_manifest_sha256="e" * 64)

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "substitution-binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "substitution-pack",
        resolver=forbidden_resolver,
        marker_inspector=substituted_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "PROVIDER_MARKER_AUTHORITY_MISMATCH" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0


def test_runner_synthetic_success_is_one_dns_one_pack_and_dual_nonce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"
    rename_calls = Counter()
    secret_reads = Counter()
    real_rename = os.rename

    from robin.capture.live_transport import EnvironmentSecretReader

    def forbidden_secret_read(self: EnvironmentSecretReader) -> str:
        secret_reads.value += 1
        raise AssertionError("secret read forbidden during successful execution")

    monkeypatch.setattr(EnvironmentSecretReader, "read", forbidden_secret_read)

    def counted_rename(source: str | bytes | Path, destination: str | bytes | Path) -> None:
        rename_calls.value += 1
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", counted_rename)
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=synthetic_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        monotonic=SequenceMonotonic((0.0, 0.1, 1.0)),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "OWNER_REVIEW_PACK_CREATED"
    assert result.resolver_operations == result.pack_builds == 1
    assert binding.is_file()
    assert pack.is_dir()
    assert (
        len(tuple(path for path in pack.iterdir() if path.name != "execution-receipt.json")) == 11
    )
    assert rename_calls.value == 1
    assert result.pack_sha256 is not None
    assert result.receipt_path == pack / "execution-receipt.json"
    assert result.receipt_path.is_file()
    success_receipt = json.loads(result.receipt_path.read_bytes())
    assert success_receipt["failure_phase"] is None
    assert success_receipt["resolver_completed"] is True
    assert success_receipt["binding_persisted"] is True
    assert success_receipt["pack_staged"] is True
    assert success_receipt["publication_completed"] is True
    assert success_receipt["expected_output_directory_name"] == pack.name
    assert secret_reads.value == 0


@pytest.mark.parametrize(
    ("monotonic_values", "expected_status", "expected_pack_builds"),
    (
        ((0.0, 5.0, 120.0, 120.0), "OWNER_REVIEW_PACK_CREATED", 1),
        ((0.0, 5.001), "POST_DNS_HARD_STOP", 0),
        ((0.0, 5.0, 120.001), "POST_DNS_HARD_STOP", 1),
    ),
)
def test_runner_enforces_inclusive_five_and_120_second_budgets(
    tmp_path: Path,
    monotonic_values: tuple[float, ...],
    expected_status: str,
    expected_pack_builds: int,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=synthetic_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        monotonic=SequenceMonotonic(monotonic_values),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == expected_status
    assert result.resolver_operations == 1
    assert result.pack_builds == expected_pack_builds
    assert pack.is_dir() is (expected_status == "OWNER_REVIEW_PACK_CREATED")


def test_runner_publication_rename_failure_retains_staging_and_hard_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"
    rename_calls = Counter()

    def failing_rename(source: str | bytes | Path, destination: str | bytes | Path) -> None:
        del source, destination
        rename_calls.value += 1
        raise OSError("synthetic atomic publication failure")

    monkeypatch.setattr(os, "rename", failing_rename)
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=synthetic_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        monotonic=SequenceMonotonic((0.0, 0.1, 1.0, 1.1)),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.resolver_operations == result.pack_builds == rename_calls.value == 1
    assert not pack.exists()
    staging = tuple(pack.parent.glob(".pack.staging-*"))
    assert len(staging) == 1
    assert not (staging[0] / "execution-receipt.json").exists()
    assert result.receipt_path is not None and result.receipt_path.is_file()
    hard_stop = json.loads(result.receipt_path.read_bytes())
    assert hard_stop["failure_phase"] == "PACK_PUBLICATION"
    assert hard_stop["resolver_completed"] is True
    assert hard_stop["binding_persisted"] is True
    assert hard_stop["pack_staged"] is True
    assert hard_stop["publication_completed"] is False


def test_runner_success_receipt_failure_is_post_publication_and_hard_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"
    original_writer = predns_module._write_runner_receipt

    def fail_only_success_receipt(path: Path, **kwargs: object) -> None:
        if path == pack / "execution-receipt.json":
            raise PreDnsOrchestrationError("SYNTHETIC_SUCCESS_RECEIPT_FAILURE")
        original_writer(path, **kwargs)

    monkeypatch.setattr(predns_module, "_write_runner_receipt", fail_only_success_receipt)
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=synthetic_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        monotonic=SequenceMonotonic((0.0, 0.1, 1.0, 1.1)),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert binding.is_file() and pack.is_dir()
    assert not (pack / "execution-receipt.json").exists()
    assert result.receipt_path is not None and result.receipt_path.is_file()
    hard_stop = json.loads(result.receipt_path.read_bytes())
    assert hard_stop["hard_stop_code"] == "SYNTHETIC_SUCCESS_RECEIPT_FAILURE"
    assert hard_stop["failure_phase"] == "RECEIPT_FINALIZATION"
    assert hard_stop["resolver_completed"] is True
    assert hard_stop["binding_persisted"] is True
    assert hard_stop["pack_staged"] is True
    assert hard_stop["publication_completed"] is True


def test_runner_resamples_currentness_immediately_before_dns(tmp_path: Path) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    resolver_calls = Counter()

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden after final preflight expiry")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=SequenceClock((BASE, BASE + timedelta(minutes=31))),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "CAMPAIGN_SELECTION_NOT_CURRENT" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0


@pytest.mark.parametrize("alias_kind", ("pack", "hard-stop-receipt"))
def test_runner_rejects_output_aliases_before_dns(tmp_path: Path, alias_kind: str) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    resolver_calls = Counter()
    pack = Path(workspace.control_temp_root) / "pack"
    binding = pack if alias_kind == "pack" else pack.parent / f"{pack.name}-hard-stop-receipt.json"

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden for aliased outputs")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "ATOMIC_RUNNER_OUTPUT_ALIAS" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0


@pytest.mark.parametrize("alias_kind", ("resolution-marker", "pack-staging"))
def test_runner_reserves_provider_output_namespace_before_dns(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    resolver_calls = Counter()
    pack = Path(workspace.control_temp_root) / "pack"
    binding = (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
        if alias_kind == "resolution-marker"
        else Path(workspace.control_temp_root) / ".pack.staging-collision"
    )

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden for reserved output namespace")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "ATOMIC_RUNNER_OUTPUT_ALIAS" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0


def test_runner_rechecks_840_second_margin_at_binding_boundary(tmp_path: Path) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    selected = loaded.campaign_selection.selected_candidate()
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    ceiling = min(
        manifest.expires_at,
        selected.usable_expires_at_utc,
        earliest_kickoff - timedelta(minutes=5),
    )
    resolver_calls = Counter()

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden below 840-second margin")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=SequenceClock((BASE, BASE, ceiling - timedelta(seconds=839))),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "OWNER_REVIEW_USABLE_MARGIN_INSUFFICIENT" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0
    assert not (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    ).exists()


def test_runner_stops_after_reservation_if_margin_crosses_before_resolver(
    tmp_path: Path,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    selected = loaded.campaign_selection.selected_candidate()
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    ceiling = min(
        manifest.expires_at,
        selected.usable_expires_at_utc,
        earliest_kickoff - timedelta(minutes=5),
    )
    boundary = ceiling - timedelta(seconds=840)
    resolver_calls = Counter()
    marker = Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"

    def reserving_preparer(
        *,
        workspace_receipt: RealCaptureWorkspaceReceiptV1,
        mission_manifest: RealExecutionMissionManifestV1,
        campaign_selection: CampaignWindowSelectionV1,
        output_path: Path,
        resolver: Callable[[str, int, int, int, int], Iterable[tuple[object, ...]]],
        clock: Callable[[], datetime],
        binding_ttl_seconds: int,
    ) -> ProviderNetworkBindingV1:
        del workspace_receipt, mission_manifest, campaign_selection, output_path
        del binding_ttl_seconds
        clock()
        marker.write_bytes(b"reserved-before-resolver")
        tuple(resolver("api.the-odds-api.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, 0))
        raise AssertionError("resolver boundary must stop before a binding is returned")

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("underlying resolver forbidden below 840-second margin")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=SequenceClock((BASE, BASE, boundary, boundary, boundary + timedelta(seconds=1))),
        workspace_validator=lambda _: None,
        binding_preparer=reserving_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "OWNER_REVIEW_USABLE_MARGIN_INSUFFICIENT"
    assert result.resolver_operations == resolver_calls.value == 0
    assert marker.is_file()
    assert result.receipt_path is not None and result.receipt_path.is_file()


def test_runner_rejects_outputs_outside_receipt_control_root_without_writes(
    tmp_path: Path,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path / "authority")
    outside = tmp_path / "outside"
    outside.mkdir()
    resolver_calls = Counter()

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden outside control root")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=outside / "binding.json",
        output_pack_directory=outside / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "ATOMIC_RUNNER_OUTPUT_PARENT_MISMATCH" in result.preflight.errors
    assert result.resolver_operations == resolver_calls.value == 0
    assert tuple(outside.iterdir()) == ()


def test_runner_pack_failure_after_dns_retains_marker_and_hard_stops(tmp_path: Path) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "binding.json"
    pack = Path(workspace.control_temp_root) / "pack"

    def failing_pack_builder(**kwargs: object) -> object:
        raise RuntimeError("synthetic pack failure")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack,
        resolver=synthetic_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(BASE),
        monotonic=SequenceMonotonic((0.0, 0.1)),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        pack_builder=failing_pack_builder,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.resolver_operations == result.pack_builds == 1
    assert binding.is_file()
    assert (binding.parent / "provider-network-resolution-one-shot-v1.json").is_file()
    assert result.receipt_path is not None and result.receipt_path.is_file()
    hard_stop = json.loads(result.receipt_path.read_bytes())
    assert hard_stop["failure_phase"] == "PACK_BUILD"
    assert hard_stop["resolver_completed"] is True
    assert hard_stop["binding_persisted"] is True
    assert hard_stop["pack_staged"] is False
    assert hard_stop["publication_completed"] is False


def test_runner_forgotten_stub_is_blocked_before_os_resolver_and_receipted(
    tmp_path: Path,
    capture_network_guard: object,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "forgotten-binding.json"
    pack = Path(workspace.control_temp_root) / "forgotten-pack"

    def forgotten_stub_resolver(
        host: str,
        port: int,
        family: int,
        socket_type: int,
        protocol: int,
    ) -> Iterable[tuple[object, ...]]:
        return socket.getaddrinfo(host, port, family, socket_type, protocol)

    assert hasattr(capture_network_guard, "expect_forbidden")
    with capture_network_guard.expect_forbidden():
        result = run_owner_review_pack_once_v1(
            bundle_directory=bundle,
            workspace_receipt=workspace,
            mission_manifest=manifest,
            output_binding_path=binding,
            output_pack_directory=pack,
            resolver=forgotten_stub_resolver,
            marker_inspector=marker_inspector,
            execute=True,
            owner_present_for_review=True,
            clock=FixedClock(BASE),
            workspace_validator=lambda _: None,
            binding_preparer=fake_binding_preparer,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "TEST_REAL_NETWORK_FORBIDDEN"
    assert result.resolver_operations == 1
    assert not binding.exists() and not pack.exists()
    assert result.receipt_path is not None and result.receipt_path.is_file()
    receipt = json.loads(result.receipt_path.read_bytes())
    assert receipt["failure_phase"] == "RESOLVER"
    assert receipt["resolver_completed"] is False
    assert receipt["binding_persisted"] is False
    assert receipt["pack_builds"] == 0
    assert receipt["pack_staged"] is False
    assert receipt["publication_completed"] is False


def test_runner_hard_stop_receipt_write_failure_is_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    binding = Path(workspace.control_temp_root) / "receipt-failure-binding.json"
    pack = Path(workspace.control_temp_root) / "receipt-failure-pack"

    def failing_pack_builder(**kwargs: object) -> object:
        del kwargs
        raise RuntimeError("synthetic pack failure")

    def failing_receipt_writer(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise PreDnsOrchestrationError("SYNTHETIC_RECEIPT_WRITE_FAILURE")

    monkeypatch.setattr(predns_module, "_write_runner_receipt", failing_receipt_writer)
    with pytest.raises(
        PreDnsOrchestrationError,
        match="POST_DNS_HARD_STOP_RECEIPT_WRITE_FAILED",
    ):
        run_owner_review_pack_once_v1(
            bundle_directory=bundle,
            workspace_receipt=workspace,
            mission_manifest=manifest,
            output_binding_path=binding,
            output_pack_directory=pack,
            resolver=synthetic_resolver,
            marker_inspector=marker_inspector,
            execute=True,
            owner_present_for_review=True,
            clock=FixedClock(BASE),
            monotonic=SequenceMonotonic((0.0, 0.1)),
            workspace_validator=lambda _: None,
            binding_preparer=fake_binding_preparer,
            pack_builder=failing_pack_builder,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )
    assert binding.is_file()
    assert (binding.parent / "provider-network-resolution-one-shot-v1.json").is_file()
    assert not pack.exists()


def test_runner_future_selection_and_secret_sentinel_use_zero_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, workspace, manifest = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=180),)),
    )
    assert result.bundle_directory is not None
    secret_reads = Counter()
    resolver_calls = Counter()

    from robin.capture.live_transport import EnvironmentSecretReader

    def forbidden_secret_read(self: EnvironmentSecretReader) -> str:
        secret_reads.value += 1
        raise AssertionError("secret read forbidden")

    monkeypatch.setattr(EnvironmentSecretReader, "read", forbidden_secret_read)

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("resolver forbidden")

    runner = run_owner_review_pack_once_v1(
        bundle_directory=result.bundle_directory,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=False,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert runner.status == "FUTURE_WINDOW_NOT_OPEN"
    assert runner.resolver_operations == resolver_calls.value == secret_reads.value == 0

    ready_bundle, ready_workspace, ready_manifest = build_ready_bundle(tmp_path / "stale")
    stale = run_owner_review_pack_once_v1(
        bundle_directory=ready_bundle,
        workspace_receipt=ready_workspace,
        mission_manifest=ready_manifest,
        output_binding_path=Path(ready_workspace.control_temp_root) / "binding.json",
        output_pack_directory=Path(ready_workspace.control_temp_root) / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=False,
        clock=FixedClock(BASE + timedelta(minutes=31)),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert stale.status == "PREFLIGHT_REJECTED"
    assert stale.resolver_operations == resolver_calls.value == secret_reads.value == 0


def test_real_runner_cli_defaults_to_preflight_and_requires_explicit_execute_owner_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    control = Path(workspace.control_temp_root)
    workspace_path = control / "workspace.json"
    manifest_path = control / "manifest.json"
    workspace_path.write_bytes(canonical_model_bytes(workspace))
    manifest_path.write_bytes(canonical_model_bytes(manifest))
    binding = control / "binding.json"
    pack = control / "pack"
    historical = control / "historical-marker.json"
    historical.write_bytes(b"historical")

    script_path = Path(__file__).parents[2] / "tools/data-sourcing/run_owner_review_pack_once_v1.py"
    spec = importlib.util.spec_from_file_location("atomic_owner_pack_cli_under_test", script_path)
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    real_runner = run_owner_review_pack_once_v1
    synthetic_resolver_calls = Counter()
    cli_system_resolver_calls = Counter()
    registry = tmp_path / "mission-global-claim-registry"
    registry.mkdir()

    def forbidden_cli_system_resolver(
        *args: object,
    ) -> Iterable[tuple[object, ...]]:
        del args
        cli_system_resolver_calls.value += 1
        raise AssertionError("TEST_REAL_NETWORK_FORBIDDEN")

    def counted_synthetic_resolver(
        host: str,
        port: int,
        family: int,
        socket_type: int,
        protocol: int,
    ) -> Iterable[tuple[object, ...]]:
        synthetic_resolver_calls.value += 1
        assert (host, port, family, socket_type, protocol) == (
            "api.the-odds-api.com",
            443,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
        return ((socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),)

    monkeypatch.setattr(cli, "assert_real_capture_workspace_receipt_current_v1", lambda _: None)
    monkeypatch.setattr(
        cli,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: manifest,
    )
    monkeypatch.setattr(
        cli,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(cli, "_system_resolver", forbidden_cli_system_resolver)
    monkeypatch.setattr(
        provider_network_module,
        "_mission_global_claim_registry_root_v1",
        lambda: registry,
    )

    def injected_runner(**kwargs: object):
        assert kwargs["resolver"] is forbidden_cli_system_resolver
        runner_arguments = {
            **kwargs,
            "resolver": counted_synthetic_resolver,
            "marker_inspector": marker_inspector,
            "clock": FixedClock(BASE),
            "monotonic": SequenceMonotonic((0.0, 0.1, 1.0, 1.1)),
            "workspace_validator": lambda _: None,
            "raw_evidence_verifier": synthetic_raw_evidence_verifier,
        }
        return real_runner(
            **runner_arguments,
        )

    monkeypatch.setattr(cli, "run_owner_review_pack_once_v1", injected_runner)
    base_argv = [
        str(script_path),
        "--workspace-receipt",
        str(workspace_path),
        "--mission-manifest",
        str(manifest_path),
        "--pre-dns-bundle",
        str(bundle),
        "--output-binding",
        str(binding),
        "--output-pack-directory",
        str(pack),
        "--historical-marker",
        str(historical),
        "--historical-marker-manifest-sha256",
        "c" * 64,
        "--historical-marker-sha256",
        "a" * 64,
        "--historical-marker-acl-sha256",
        "b" * 64,
    ]
    monkeypatch.setattr(sys, "argv", base_argv)
    assert cli.main() == 0
    preflight = json.loads(capsys.readouterr().out)
    assert preflight["status"] == "PREFLIGHT_ACCEPT"
    assert preflight["resolver_operations"] == preflight["pack_builds"] == 0
    assert synthetic_resolver_calls.value == cli_system_resolver_calls.value == 0
    assert not binding.exists() and not pack.exists()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()

    monkeypatch.setattr(sys, "argv", [*base_argv, "--execute", "--owner-present-for-review"])
    assert cli.main() == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["status"] == "OWNER_REVIEW_PACK_CREATED"
    assert executed["resolver_operations"] == executed["pack_builds"] == 1
    assert synthetic_resolver_calls.value == 1
    assert cli_system_resolver_calls.value == 0
    assert binding.is_file() and pack.is_dir()
    assert (control / "provider-network-resolution-one-shot-v1.json").is_file()
    global_marker = registry / (
        f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json"
    )
    assert global_marker.is_file()
    assert executed["owner_authorization_statement"]


def test_real_runner_cli_forgotten_stub_fails_before_system_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle, workspace, manifest = build_ready_bundle(tmp_path)
    control = Path(workspace.control_temp_root)
    workspace_path = control / "workspace.json"
    manifest_path = control / "manifest.json"
    workspace_path.write_bytes(canonical_model_bytes(workspace))
    manifest_path.write_bytes(canonical_model_bytes(manifest))
    binding = control / "forgotten-stub-binding.json"
    pack = control / "forgotten-stub-pack"
    historical = control / "historical-marker.json"
    historical.write_bytes(b"historical")

    script_path = Path(__file__).parents[2] / "tools/data-sourcing/run_owner_review_pack_once_v1.py"
    spec = importlib.util.spec_from_file_location(
        "atomic_owner_pack_cli_forgotten_stub", script_path
    )
    assert spec is not None and spec.loader is not None
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    cli_system_resolver_calls = Counter()

    class ForgottenResolverInjectionError(AssertionError):
        code = "TEST_REAL_NETWORK_FORBIDDEN"

    def forbidden_cli_system_resolver(
        *args: object,
    ) -> Iterable[tuple[object, ...]]:
        del args
        cli_system_resolver_calls.value += 1
        return ()

    def require_explicit_test_resolver(**kwargs: object) -> object:
        assert kwargs["resolver"] is forbidden_cli_system_resolver
        raise ForgottenResolverInjectionError

    monkeypatch.setattr(cli, "assert_real_capture_workspace_receipt_current_v1", lambda _: None)
    monkeypatch.setattr(
        cli,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: manifest,
    )
    monkeypatch.setattr(
        cli,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(cli, "_system_resolver", forbidden_cli_system_resolver)
    monkeypatch.setattr(cli, "run_owner_review_pack_once_v1", require_explicit_test_resolver)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script_path),
            "--workspace-receipt",
            str(workspace_path),
            "--mission-manifest",
            str(manifest_path),
            "--pre-dns-bundle",
            str(bundle),
            "--output-binding",
            str(binding),
            "--output-pack-directory",
            str(pack),
            "--historical-marker",
            str(historical),
            "--historical-marker-manifest-sha256",
            "c" * 64,
            "--historical-marker-sha256",
            "a" * 64,
            "--historical-marker-acl-sha256",
            "b" * 64,
            "--execute",
            "--owner-present-for-review",
        ],
    )

    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "FAILED",
        "code": "TEST_REAL_NETWORK_FORBIDDEN",
    }
    assert cli_system_resolver_calls.value == 0
    assert not binding.exists() and not pack.exists()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()
