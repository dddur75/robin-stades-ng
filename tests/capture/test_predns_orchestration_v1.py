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
from functools import partial
from pathlib import Path
from types import ModuleType
from typing import cast
from zoneinfo import ZoneInfo

import pytest

import robin.capture.predns_orchestration as predns_module
import robin.capture.provider_network as provider_network_module
from robin.capture.bootstrap_contracts import (
    FIRST_C0_VERTICAL_EXTERNAL_EFFECTS,
    FIRST_C0_VERTICAL_MANIFEST_EXPIRES_AT,
    FIRST_C0_VERTICAL_MANIFEST_SOURCE_HASH,
    PRE_KICKOFF_SAFETY_MARGIN,
    CampaignSelectionAuthorityV1,
    CampaignWindowSelectionV1,
    FirstC0CanarySelectionV1,
    FirstC0PrefetchedWindowHandoffV1,
    FirstC0WindowOpenRevalidationV1,
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
    LIGUE1_CALENDAR_JSON_V1,
    LIGUE1_CALENDAR_URL,
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
    AtomicRunnerResultV1,
    HistoricalMarkerExpectationV1,
    LoadedPreDnsBundleV1,
    MarkerInspectionV1,
    PreDnsOrchestrationError,
    RunnerPreflightV1,
    freeze_official_schedule_evidence_v1,
    inspect_provider_markers_read_only_v1,
    load_first_c0_prefetch_handoff_v1,
    load_first_c0_window_open_revalidation_v1,
    load_pre_dns_bundle_v1,
    revalidate_prefetched_window_open_v1,
    verify_raw_official_evidence_v1,
)
from robin.capture.predns_orchestration import (
    _prepare_owner_review_pack_inputs_v1 as prepare_owner_review_pack_inputs_v1,
)
from robin.capture.predns_orchestration import (
    _run_first_c0_owner_review_pack_once_after_owner_gate_v1 as run_owner_review_pack_once_v1,
)
from robin.capture.predns_orchestration import (
    prepare_owner_review_pack_inputs_v1 as public_prepare_owner_review_pack_inputs_v1,
)
from robin.capture.predns_orchestration import (
    run_owner_review_pack_once_v1 as public_run_owner_review_pack_once_v1,
)
from robin.capture.provider_network import (
    ProviderNetworkPreparationError,
    prepare_provider_network_binding_once_v1,
    reserve_provider_network_resolution_v1,
)
from robin.capture.storage import exclusive_local_directory_fingerprint

BASE = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
MAIN_SHA = "2" * 40
MANIFEST_SOURCE_HASH = "204e4323d0b99fdfa8c655cdc3a08a8d2b3c82ac0a784f9a97982c90ab3a7312"
HISTORICAL_V3_MANIFEST_SHA256 = "d895e0b2ddded2c9763d85a08efbd64dc0185d26f66bb2b73fbe52cc05411206"
HISTORICAL_V3_MARKER_RAW_SHA256 = "a1b7cbb95b5c7a221a7c50147e202d8d80649ec7049d0c132317803b0e51b28c"
HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256 = (
    "b032d14d479bbddd354c1a9a43250d4033f3029147a322f7177988fb4b15730a"
)
HISTORICAL_V3_RESOLUTION_CLAIM_SHA256 = (
    "ed2185b98bf56c978261b30d3bc396099d1f2b698719f47dfff79f45eea664d7"
)
ADAPTERS = {
    "soccer_epl": PREMIER_LEAGUE_FULL_SEASON_HTML_V1,
    "soccer_spain_la_liga": LALIGA_PUBLIC_MATCHES_JSON_V1,
    "soccer_germany_bundesliga": DFB_DATACENTER_HTML_V1,
    "soccer_italy_serie_a": LEGA_SERIE_A_CALENDAR_PDF_V1,
    "soccer_france_ligue_one": LIGUE1_CALENDAR_JSON_V1,
}
URLS = {
    "soccer_epl": "https://www.premierleague.com/en/news/season",
    "soccer_spain_la_liga": (
        "https://apim.laliga.com/public-service/api/v1/matches?"
        "subscription=laliga-easports-2026&competition=primera-division&limit=100&offset=300"
    ),
    "soccer_germany_bundesliga": "https://datencenter.dfb.de/competitions/12/seasons/current",
    "soccer_italy_serie_a": "https://images.legaseriea.it/calendar.pdf",
    "soccer_france_ligue_one": LIGUE1_CALENDAR_URL,
}
CONTENT_TYPES = {
    "soccer_epl": "text/html",
    "soccer_spain_la_liga": "application/json",
    "soccer_germany_bundesliga": "text/html",
    "soccer_italy_serie_a": "application/pdf",
    "soccer_france_ligue_one": "application/json",
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


@pytest.fixture(autouse=True)
def _isolated_mission_global_preparation_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    registry = tmp_path / "mission-global-preparation-registry-v2"
    legacy_registry = tmp_path / "mission-global-preparation-registry-v1"
    registry.mkdir()
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "resolve_global_claim_root_candidate_v2",
        lambda _workspace: registry,
    )
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "ensure_global_claim_root_v2",
        lambda _workspace, **_kwargs: registry,
    )
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "inspect_global_claim_root_identity_v2",
        lambda _workspace: ("synthetic-stable-global-root",),
    )

    def read_snapshot(_workspace: object) -> tuple[Path, tuple[object, ...]]:
        selected = FIRST_C0_CANARY_CLI.global_claims.resolve_global_claim_root_candidate_v2(
            _workspace
        )
        metadata = selected.lstat()
        return selected, ("synthetic-global-root", metadata.st_dev, metadata.st_ino)

    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "_global_claim_root_read_snapshot_v2",
        read_snapshot,
    )
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "inspect_global_claim_root_identity_v2",
        lambda workspace: read_snapshot(workspace)[1],
    )

    def ensure_with_identity(
        workspace: object,
        *,
        expected_read_identity: tuple[object, ...] | None = None,
    ) -> object:
        selected, identity = read_snapshot(workspace)
        if expected_read_identity is not None and identity != expected_read_identity:
            raise FIRST_C0_CANARY_CLI.global_claims.GlobalClaimBoundaryError(
                "GLOBAL_CLAIM_ROOT_IDENTITY_CHANGED"
            )
        return FIRST_C0_CANARY_CLI.global_claims._EnsuredGlobalClaimRootV2(
            selected,
            identity,
        )

    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "_ensure_global_claim_root_with_identity_v2",
        ensure_with_identity,
    )
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "resolve_legacy_global_claim_root_read_only_v1",
        lambda: legacy_registry,
    )
    return registry


def _load_first_c0_owner_atomic_cli() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "data-sourcing"
        / "run_first_c0_owner_pack_atomic_v1.py"
    )
    specification = importlib.util.spec_from_file_location(
        "predns_first_c0_owner_atomic_cli_tests",
        path,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


FIRST_C0_OWNER_ATOMIC_CLI = _load_first_c0_owner_atomic_cli()


def _load_legacy_predns_cli() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "data-sourcing"
        / "prepare_owner_review_pack_inputs_v1.py"
    )
    specification = importlib.util.spec_from_file_location(
        "predns_legacy_owner_inputs_cli_tests",
        path,
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


LEGACY_PRE_DNS_CLI = _load_legacy_predns_cli()


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


class CoherentSequenceTimeline:
    def __init__(
        self,
        values: Iterable[datetime],
        *,
        initial_wall: datetime = BASE,
        initial_monotonic: float = 0.0,
    ) -> None:
        self._values = iter(values)
        self.wall = initial_wall
        self.monotonic_value = initial_monotonic

    def clock(self) -> datetime:
        observed = next(self._values, self.wall)
        self.monotonic_value += (observed - self.wall).total_seconds()
        self.wall = observed
        return observed

    def monotonic(self) -> float:
        return self.monotonic_value


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
        parser_metadata: dict[str, object] = {"synthetic": True}
        if source.adapter == LIGUE1_CALENDAR_JSON_V1:
            synthetic_id = f"fixture-{iteration}-{league_index}"
            parser_metadata.update(
                {
                    "covered_not_before": horizon_not_before_utc.isoformat().replace("+00:00", "Z"),
                    "covered_expires": horizon_expires_at_utc.isoformat().replace("+00:00", "Z"),
                    "complete_official_horizon": True,
                    "calendar_gameweeks_total": 34,
                    "calendar_match_ids_total": 306,
                    "calendar_club_identities_total": 18,
                    "calendar_club_identities_sha256": "0" * 64,
                    "calendar_ids_expected": [synthetic_id],
                    "calendar_ids_accounted": [synthetic_id],
                    "gameweeks_fetched": [1],
                }
            )
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
            parser_metadata=parser_metadata,
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
        current_v2_global_marker="synthetic-v2-global-marker",
        current_legacy_global_marker="synthetic-legacy-global-marker",
    )


def marker_inspector(
    workspace: RealCaptureWorkspaceReceiptV1,
    manifest: RealExecutionMissionManifestV1,
) -> MarkerInspectionV1:
    assert workspace.authorized_main_sha == MAIN_SHA
    assert manifest.source_hash == MANIFEST_SOURCE_HASH
    marker_name = f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json"
    marker_paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        marker_name,
    )
    marker_pair = predns_module.global_claims.read_global_claim_marker_pair_v2(
        workspace,
        marker_name,
    )
    return replace(
        marker_ok(),
        current_local_marker=str(
            Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
        ),
        current_v2_global_marker=str(marker_paths.v2),
        current_legacy_global_marker=str(marker_paths.legacy),
        current_v2_root_identity=marker_pair.v2_root_identity,
        current_legacy_root_identity=marker_pair.legacy_root_identity,
    )


def synthetic_raw_evidence_verifier(*args: object) -> None:
    assert len(args) == 6


def build_authority(
    tmp_path: Path,
    *,
    mission_expires_at: datetime | None = None,
    first_c0_vertical: bool = False,
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
    if first_c0_vertical:
        manifest = RealExecutionMissionManifestV1.issue(
            mission_id="FIRST_C0_VERTICAL_V1",
            authorized_stages=("E1",),
            maximum_stage="E1",
            external_effects=FIRST_C0_VERTICAL_EXTERNAL_EFFECTS,
            compute_budget=4000,
            time_budget=259200,
            source_hash=FIRST_C0_VERTICAL_MANIFEST_SOURCE_HASH,
            expires_at=FIRST_C0_VERTICAL_MANIFEST_EXPIRES_AT,
        )
    else:
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
            expires_at=mission_expires_at or BASE + timedelta(days=1),
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


@pytest.mark.parametrize("historical_location", ("legacy", "v2"))
def test_historical_marker_is_bound_to_exact_authority_manifest_and_registry_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    historical_location: str,
) -> None:
    workspace, manifest = build_authority(tmp_path / "authority")
    historical_manifest_sha256 = HISTORICAL_V3_MANIFEST_SHA256
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=historical_manifest_sha256,
        workspace_receipt_sha256=(
            "f12d4fc65cac3930c7df850ed0221fc9b9f7e0519b1d108f6b4ad417342f57c9"
        ),
        campaign_selection_sha256=(
            "ae46d11a6c414fb721f49744672fce3c02724cd605453e5ec3f5d8c43ef6bfc1"
        ),
        fixture_target_set_sha256=(
            "ea1d07b58f26f1bab1aa221c1a8cfd75103bb11139534b21f17b2638d400d2d4"
        ),
        claimed_at_utc=datetime(2026, 8, 26, 17, 51, 51, 776902, tzinfo=UTC),
        mission_expires_at_utc=datetime(2026, 9, 1, 20, tzinfo=UTC),
    )
    assert claim.canonical_claim_hash == HISTORICAL_V3_RESOLUTION_CLAIM_SHA256
    payload = canonical_model_bytes(claim)
    assert hashlib.sha256(payload).hexdigest() == HISTORICAL_V3_MARKER_RAW_SHA256
    historical_paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        f"{manifest.mission_id.casefold()}-{historical_manifest_sha256}.json",
    )
    historical = historical_paths.legacy if historical_location == "legacy" else historical_paths.v2
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_bytes(payload)

    class NtOsProxy:
        name = "nt"

        def __getattr__(self, attribute: str) -> object:
            return getattr(os, attribute)

    monkeypatch.setattr(predns_module, "os", NtOsProxy())
    acl_result = [(HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256, True)]
    acl_paths: list[Path] = []

    class StubWindowsBoundaryInspector:
        def _security_facts(self, path: Path) -> tuple[str, bool]:
            acl_paths.append(path)
            return acl_result[0]

    monkeypatch.setattr(
        predns_module,
        "WindowsBoundaryInspector",
        StubWindowsBoundaryInspector,
    )
    expectation = HistoricalMarkerExpectationV1(
        path=historical,
        authority_manifest_sha256=historical_manifest_sha256,
        raw_sha256=HISTORICAL_V3_MARKER_RAW_SHA256,
        acl_sha256=HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256,
    )

    inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert inspection.historical_marker_unchanged is True
    assert inspection.current_marker_present is False
    assert inspection.historical_raw_sha256 == HISTORICAL_V3_MARKER_RAW_SHA256
    assert inspection.historical_acl_sha256 == HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256
    assert inspection.historical_authority_manifest_sha256 == historical_manifest_sha256
    assert inspection.current_authority_manifest_sha256 == manifest.canonical_manifest_sha256()
    assert inspection.current_authority_manifest_sha256 != historical_manifest_sha256
    assert acl_paths == [historical.absolute()]
    current_paths = (
        Path(inspection.current_local_marker),
        Path(inspection.current_v2_global_marker),
        Path(inspection.current_legacy_global_marker),
    )
    assert all(not os.path.lexists(path) for path in current_paths)

    wrong_raw = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=replace(expectation, raw_sha256="0" * 64),
    )
    assert wrong_raw.historical_marker_unchanged is False

    acl_result[0] = ("0" * 64, True)
    wrong_acl = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert wrong_acl.historical_marker_unchanged is False
    assert wrong_acl.historical_raw_sha256 == HISTORICAL_V3_MARKER_RAW_SHA256
    assert wrong_acl.historical_acl_sha256 == "0" * 64

    acl_result[0] = (HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256, False)
    nonexclusive_acl = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert nonexclusive_acl.historical_marker_unchanged is False
    acl_result[0] = (HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256, True)

    substituted = tmp_path / "substituted-historical-marker.json"
    substituted.write_bytes(payload)
    substituted_inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=replace(expectation, path=substituted),
    )
    assert substituted_inspection.historical_marker_unchanged is False

    historical.write_bytes(payload[:-1] + b"\r\n")
    tampered_inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert tampered_inspection.historical_marker_unchanged is False
    assert tampered_inspection.historical_raw_sha256 != HISTORICAL_V3_MARKER_RAW_SHA256
    assert tampered_inspection.historical_acl_sha256 == HISTORICAL_V3_GLOBAL_MARKER_ACL_SHA256
    historical.unlink()
    missing_inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=expectation,
    )
    assert missing_inspection.historical_marker_unchanged is False
    assert missing_inspection.historical_raw_sha256 is None
    assert all(not os.path.lexists(path) for path in current_paths)


@pytest.mark.parametrize("current_state", ("v2", "legacy", "equal"))
def test_current_provider_marker_presence_inspects_v2_and_legacy_read_only(
    tmp_path: Path,
    current_state: str,
) -> None:
    workspace, manifest = build_authority(tmp_path / "authority")
    marker_name = f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json"
    paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        marker_name,
    )
    claim = ProviderNetworkResolutionClaimV1.issue(
        mission_manifest_sha256=manifest.canonical_manifest_sha256(),
        workspace_receipt_sha256=workspace.canonical_receipt_hash,
        campaign_selection_sha256="a" * 64,
        fixture_target_set_sha256="b" * 64,
        claimed_at_utc=BASE,
        mission_expires_at_utc=manifest.expires_at,
    )
    payload = canonical_model_bytes(claim)
    paths.legacy.parent.mkdir()
    if current_state in {"v2", "equal"}:
        paths.v2.write_bytes(payload)
    if current_state in {"legacy", "equal"}:
        paths.legacy.write_bytes(payload)
    before = {path: path.read_bytes() for path in (paths.v2, paths.legacy) if path.exists()}
    historical_paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        f"{manifest.mission_id.casefold()}-{'e' * 64}.json",
    )

    inspection = inspect_provider_markers_read_only_v1(
        workspace,
        manifest,
        historical_marker=HistoricalMarkerExpectationV1(
            path=historical_paths.legacy,
            authority_manifest_sha256="e" * 64,
            raw_sha256="f" * 64,
        ),
    )

    assert inspection.current_marker_present is True
    assert Path(inspection.current_v2_global_marker) == paths.v2
    assert Path(inspection.current_legacy_global_marker) == paths.legacy
    assert before == {path: path.read_bytes() for path in (paths.v2, paths.legacy) if path.exists()}
    assert not historical_paths.v2.exists()
    assert not historical_paths.legacy.exists()


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


def rewrite_canary_bundle_artifact(
    bundle: Path,
    workspace: RealCaptureWorkspaceReceiptV1,
    name: str,
    payload: bytes,
) -> None:
    (bundle / name).write_bytes(payload)
    manifest_path = bundle / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["artifact_sha256"][name] = hashlib.sha256(payload).hexdigest()
    manifest_bytes = canonical_json_bytes(manifest) + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    cycle = manifest["preparation_cycle"]
    receipt_path = (
        Path(workspace.control_temp_root)
        / f"first-c0-canary-cycle-{cycle:02d}-attempt-receipt-v1.json"
    )
    receipt = json.loads(receipt_path.read_bytes())
    receipt["bundle_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    receipt_path.write_bytes(canonical_json_bytes(receipt) + b"\n")


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


def test_frozen_provider_v1_marker_bundle_replays_via_legacy_root(
    tmp_path: Path,
) -> None:
    result, _, workspace, mission = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert result.bundle_directory is not None
    bundle = result.bundle_directory
    marker_name = f"{mission.mission_id.casefold()}-{mission.canonical_manifest_sha256()}.json"
    marker_paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        marker_name,
    )
    v2 = json.loads((bundle / "provider-marker-inspection.json").read_bytes())
    frozen_v1 = {
        "schema_version": "robin-provider-marker-readonly-inspection-v1",
        "historical_marker_unchanged": v2["historical_marker_unchanged"],
        "current_marker_present": v2["current_marker_present"],
        "historical_raw_sha256": v2["historical_raw_sha256"],
        "historical_acl_sha256": v2["historical_acl_sha256"],
        "historical_marker_path": v2["historical_marker_path"],
        "historical_authority_manifest_sha256": v2["historical_authority_manifest_sha256"],
        "current_authority_manifest_sha256": v2["current_authority_manifest_sha256"],
        "current_local_marker": str(
            Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
        ),
        "current_global_marker": str(marker_paths.legacy),
        "filesystem_writes": 0,
    }
    rewrite_bundle_artifact(
        bundle,
        "provider-marker-inspection.json",
        canonical_json_bytes(frozen_v1) + b"\n",
    )

    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert isinstance(loaded.marker_inspection, predns_module.LegacyMarkerInspectionV1)
    observed = replace(
        marker_ok(),
        current_local_marker=frozen_v1["current_local_marker"],
        current_v2_global_marker=str(marker_paths.v2),
        current_legacy_global_marker=str(marker_paths.legacy),
    )
    assert predns_module._first_c0_canary_marker_authority_matches_v1(
        observed,
        loaded.marker_inspection,
    )


def test_frozen_provider_v1_marker_rejects_arbitrary_global_path(
    tmp_path: Path,
) -> None:
    result, _, workspace, _ = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert result.bundle_directory is not None
    bundle = result.bundle_directory
    v2 = json.loads((bundle / "provider-marker-inspection.json").read_bytes())
    frozen_v1 = {
        "schema_version": "robin-provider-marker-readonly-inspection-v1",
        "historical_marker_unchanged": v2["historical_marker_unchanged"],
        "current_marker_present": v2["current_marker_present"],
        "historical_raw_sha256": v2["historical_raw_sha256"],
        "historical_acl_sha256": v2["historical_acl_sha256"],
        "historical_marker_path": v2["historical_marker_path"],
        "historical_authority_manifest_sha256": v2["historical_authority_manifest_sha256"],
        "current_authority_manifest_sha256": v2["current_authority_manifest_sha256"],
        "current_local_marker": str(
            Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
        ),
        "current_global_marker": str(tmp_path / "arbitrary-global-root" / "claim.json"),
        "filesystem_writes": 0,
    }
    rewrite_bundle_artifact(
        bundle,
        "provider-marker-inspection.json",
        canonical_json_bytes(frozen_v1) + b"\n",
    )

    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_MARKER_INSPECTION_INVALID"):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


def test_provider_v2_marker_rejects_arbitrary_current_paths(
    tmp_path: Path,
) -> None:
    result, _, _, _ = run_predns(
        tmp_path,
        builder=SyntheticEvidenceBuilder((BASE + timedelta(minutes=135),)),
    )
    assert result.bundle_directory is not None
    bundle = result.bundle_directory
    marker = json.loads((bundle / "provider-marker-inspection.json").read_bytes())
    marker["current_v2_global_marker"] = str(tmp_path / "arbitrary-global-root" / "claim.json")
    rewrite_bundle_artifact(
        bundle,
        "provider-marker-inspection.json",
        canonical_json_bytes(marker) + b"\n",
    )

    with pytest.raises(PreDnsOrchestrationError, match="PRE_DNS_MARKER_INSPECTION_INVALID"):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


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
    expected_global_v2_read_identity: tuple[object, ...],
    expected_global_legacy_root_identity: tuple[object, ...],
    final_pre_effect_assertion: Callable[[], None],
) -> ProviderNetworkBindingV1:
    assert expected_global_v2_read_identity
    assert expected_global_legacy_root_identity
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
    final_pre_effect_assertion()
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
    ready_now: bool = False,
    earliest: datetime | None = None,
    mission_expires_at: datetime | None = None,
    first_c0_vertical: bool = False,
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
    workspace, manifest = build_authority(
        tmp_path,
        mission_expires_at=mission_expires_at,
        first_c0_vertical=first_c0_vertical,
    )
    control = Path(workspace.control_temp_root)
    global_markers = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json",
    )
    local_marker = control / "provider-network-resolution-one-shot-v1.json"
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
        earliest
        if earliest is not None
        else BASE + timedelta(hours=3)
        if refresh_cycle
        else BASE + timedelta(minutes=140)
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
        "schema_version": "robin-first-c0-canary-marker-inspection-v2",
        "local_marker_path": str(local_marker.absolute()),
        "v2_global_marker_path": str(global_markers.v2),
        "legacy_global_marker_path": str(global_markers.legacy),
        "local_marker_present": False,
        "v2_global_marker_present": False,
        "legacy_global_marker_present": False,
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
    result = FIRST_C0_CANARY_CLI._prepare_first_c0_canary_selection_v1(
        **arguments,
        output_directory=control / "first-c0-canary-ready-bundle",
        clock=FixedClock(BASE),
    )
    if refresh_cycle:
        assert result.status == "CANARY_FUTURE_WINDOW"
        result = FIRST_C0_CANARY_CLI._prepare_first_c0_canary_selection_v1(
            **arguments,
            output_directory=control / "first-c0-canary-refreshed-bundle",
            clock=FixedClock(result.recommended_refresh_utc),
        )
    elif ready_now and result.status == "CANARY_FUTURE_WINDOW":
        result = FIRST_C0_CANARY_CLI._prepare_first_c0_canary_selection_v1(
            **arguments,
            output_directory=control / "first-c0-canary-open-bundle",
            clock=FixedClock(result.selection.selected_not_before_utc),
        )
    if ready_now:
        assert result.status == "CANARY_READY_NOW"
    assert result.status in {
        "CANARY_READY_NOW",
        "CANARY_FUTURE_WINDOW",
        "PREFETCHED_FUTURE_WINDOW",
    }
    execution_at = result.selection.selected_not_before_utc

    def current_marker_inspector(
        _workspace: RealCaptureWorkspaceReceiptV1,
        _manifest: RealExecutionMissionManifestV1,
    ) -> MarkerInspectionV1:
        marker_pair = predns_module.global_claims.read_global_claim_marker_pair_v2(
            workspace,
            global_markers.v2.name,
        )
        return replace(
            marker_ok(),
            current_marker_present=(
                local_marker.exists()
                or marker_pair.v2_payload is not None
                or marker_pair.legacy_payload is not None
            ),
            current_authority_manifest_sha256=manifest.canonical_manifest_sha256(),
            current_local_marker=str(local_marker.absolute()),
            current_v2_global_marker=str(global_markers.v2),
            current_legacy_global_marker=str(global_markers.legacy),
            current_v2_root_identity=marker_pair.v2_root_identity,
            current_legacy_root_identity=marker_pair.legacy_root_identity,
        )

    return (
        result.bundle_directory,
        workspace,
        manifest,
        current_marker_inspector,
        execution_at,
    )


def activate_prefetched_canary_bundle(
    bundle: Path,
    execution_at: datetime,
) -> tuple[LoadedPreDnsBundleV1, Path, Path]:
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at,
        wait_started_monotonic=0.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([0.0]),
        workspace_validator=lambda _: None,
    )
    assert receipt.status == "READY_NOW"
    return loaded, handoff_path, receipt_path


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
    assert loaded.manifest["schema_version"] == "robin-first-c0-prefetched-window-bundle-v1"
    assert loaded.manifest["status"] == "PREFETCHED_FUTURE_WINDOW"
    assert loaded.manifest["preparation_cycle"] == 2
    assert loaded.manifest["cumulative_official_reads"] == 4
    names = {path.name for path in bundle.iterdir()}
    assert "prior-cycle-01-read-reservation.json" in names
    assert "prior-cycle-01-attempt-receipt.json" in names
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    assert isinstance(handoff, FirstC0PrefetchedWindowHandoffV1)
    assert handoff.additional_official_reads_authorized == 0
    assert handoff.additional_preparation_cycles_authorized == 0
    assert handoff.additional_selector_invocations_authorized == 0
    assert handoff.additional_target_set_freezes_authorized == 0


def test_frozen_first_c0_v1_marker_bundle_replays_via_legacy_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, current_marker_inspector, _ = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
    )
    marker_name = f"{mission.mission_id.casefold()}-{mission.canonical_manifest_sha256()}.json"
    marker_paths = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        marker_name,
    )
    v2 = json.loads((bundle / "marker-inspection.json").read_bytes())
    frozen_v1 = {
        "schema_version": "robin-first-c0-canary-marker-inspection-v1",
        "local_marker_path": v2["local_marker_path"],
        "global_marker_path": str(marker_paths.legacy),
        "local_marker_present": False,
        "global_marker_present": False,
        "inspected_read_only": True,
    }
    rewrite_canary_bundle_artifact(
        bundle,
        workspace,
        "marker-inspection.json",
        canonical_json_bytes(frozen_v1) + b"\n",
    )

    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert isinstance(
        loaded.marker_inspection,
        predns_module.LegacyFirstC0CanaryMarkerInspectionV1,
    )
    assert predns_module._first_c0_canary_marker_authority_matches_v1(
        current_marker_inspector(workspace, mission),
        loaded.marker_inspection,
    )


def test_frozen_first_c0_v1_marker_rejects_arbitrary_global_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, _, _, _ = build_ready_canary_bundle(tmp_path, monkeypatch)
    v2 = json.loads((bundle / "marker-inspection.json").read_bytes())
    frozen_v1 = {
        "schema_version": "robin-first-c0-canary-marker-inspection-v1",
        "local_marker_path": v2["local_marker_path"],
        "global_marker_path": str(tmp_path / "arbitrary-global-root" / "claim.json"),
        "local_marker_present": False,
        "global_marker_present": False,
        "inspected_read_only": True,
    }
    rewrite_canary_bundle_artifact(
        bundle,
        workspace,
        "marker-inspection.json",
        canonical_json_bytes(frozen_v1) + b"\n",
    )

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_MARKER_INSPECTION_INVALID",
    ):
        load_pre_dns_bundle_v1(
            bundle,
            raw_evidence_verifier=synthetic_raw_evidence_verifier,
        )


@pytest.mark.parametrize(
    "source_hash",
    (
        MANIFEST_SOURCE_HASH,
        "3d3b43f68c0d339448e52de7ec66cce068646a4a006e267dfe063bffe2767f5e",
        "0270bdd51d8d50b7d3c9f608e4f429b46b94b789d92d4b13055b81c9b72e6291",
    ),
)
def test_prefetch_rejects_legacy_api_and_cli_model_copy_before_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source_hash: str,
) -> None:
    bundle, workspace, manifest, _, _ = build_ready_canary_bundle(
        tmp_path / "prefetch",
        monkeypatch,
        refresh_cycle=True,
    )
    public_manifest = manifest.model_copy(update={"source_hash": source_hash})
    control = Path(workspace.control_temp_root)
    names_before = {path.name for path in control.iterdir()}
    fetch_calls = 0

    class ForbiddenFetcher:
        def fetch(self, _source: OfficialSourceSpec) -> OfficialHttpResponse:
            nonlocal fetch_calls
            fetch_calls += 1
            raise AssertionError("legacy five-league path reached an official read")

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_SINGLE_OWNER_ENTRYPOINT_REQUIRED",
    ):
        public_prepare_owner_review_pack_inputs_v1(
            workspace_receipt=workspace,
            workspace_receipt_bytes=canonical_model_bytes(workspace),
            mission_manifest=public_manifest,
            mission_manifest_bytes=canonical_model_bytes(public_manifest),
            source_plan_bytes=b"must-not-be-parsed",
            corpus_evidence_reader=lambda: b"must-not-be-read",
            output_parent=control,
            reviews={},
            fetcher=ForbiddenFetcher(),
            marker_inspector=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("legacy five-league path reached marker inspection")
            ),
        )
    assert fetch_calls == 0
    assert {path.name for path in control.iterdir()} == names_before
    assert bundle.is_dir()

    workspace_path = tmp_path / "workspace-receipt.json"
    manifest_path = tmp_path / "mission-manifest.json"
    source_plan_path = tmp_path / "legacy-source-plan.json"
    corpus_path = tmp_path / "scientific-corpus.json"
    historical_marker_path = tmp_path / "historical-marker.json"
    review_paths = {name: tmp_path / f"review-{name.casefold()}.json" for name in reviews()}
    read_payloads = {
        workspace_path: canonical_model_bytes(workspace),
        manifest_path: canonical_model_bytes(public_manifest),
    }
    monkeypatch.setattr(
        LEGACY_PRE_DNS_CLI,
        "_read",
        lambda path, maximum_bytes=0: read_payloads.get(path, b"must-not-be-read"),
    )
    monkeypatch.setattr(
        LEGACY_PRE_DNS_CLI,
        "assert_real_capture_workspace_receipt_current_v1",
        lambda _workspace: None,
    )
    monkeypatch.setattr(
        LEGACY_PRE_DNS_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(
        LEGACY_PRE_DNS_CLI,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _repository, _path: public_manifest,
    )
    forbidden_fetcher = ForbiddenFetcher()
    monkeypatch.setattr(
        LEGACY_PRE_DNS_CLI,
        "BuiltinHttpsOfficialScheduleFetcher",
        lambda: forbidden_fetcher,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_owner_review_pack_inputs_v1.py",
            "--workspace-receipt",
            str(workspace_path),
            "--mission-manifest",
            str(manifest_path),
            "--source-plan",
            str(source_plan_path),
            "--scientific-corpus-evidence",
            str(corpus_path),
            "--review-dp6",
            str(review_paths["DP6"]),
            "--review-c4",
            str(review_paths["C4"]),
            "--review-c2",
            str(review_paths["C2"]),
            "--review-a2",
            str(review_paths["A2"]),
            "--historical-marker",
            str(historical_marker_path),
            "--historical-marker-manifest-sha256",
            "1" * 64,
            "--historical-marker-sha256",
            "2" * 64,
            "--historical-marker-acl-sha256",
            "3" * 64,
            "--output-parent",
            str(control),
        ],
    )
    assert LEGACY_PRE_DNS_CLI.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "FAILED",
        "code": "FIRST_C0_SINGLE_OWNER_ENTRYPOINT_REQUIRED",
    }
    assert fetch_calls == 0
    assert {path.name for path in control.iterdir()} == names_before


@pytest.mark.parametrize(
    ("preflight_seconds", "accepted"),
    [(5, True), (30, True), (45, True), (46, False), (60, False), (61, False)],
)
def test_prefetched_h2_clock_only_activation_and_preflight_deadline_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preflight_seconds: int,
    accepted: bool,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    before_hashes = dict(loaded.manifest["artifact_sha256"])
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([100.0]),
        workspace_validator=lambda _: None,
    )
    assert isinstance(receipt, FirstC0WindowOpenRevalidationV1)
    assert receipt.status == "READY_NOW"
    assert receipt.usable_margin_seconds >= 840
    assert receipt.official_reads_delta == 0
    assert receipt.preparation_cycles_delta == 0
    assert receipt.target_set_freezes_delta == 0
    assert receipt.selector_invocations_delta == 0
    assert receipt.provider_effects == 0
    assert dict(load_pre_dns_bundle_v1(bundle).manifest["artifact_sha256"]) == before_hashes

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=False,
        owner_present_for_review=False,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at + timedelta(seconds=preflight_seconds)),
        monotonic=SequenceMonotonic([100.0 + preflight_seconds]),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.preflight.accepted is accepted
    assert result.resolver_operations == 0
    assert result.pack_builds == 0
    if accepted:
        assert result.preflight.usable_margin_seconds >= 840
    else:
        assert "FIRST_C0_OPEN_TO_PREFLIGHT_BUDGET_EXCEEDED" in result.preflight.errors


@pytest.mark.parametrize(
    ("execute", "owner_present"),
    [
        (False, False),
        (True, False),
        (False, True),
        (1, True),
        (True, 1),
        ("true", True),
        (True, "false"),
    ],
)
def test_single_owner_entrypoint_requires_both_gates_before_any_observation(
    tmp_path: Path,
    execute: object,
    owner_present: object,
) -> None:
    workspace, mission = build_authority(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("OWNER_GATE_OBSERVED_EXTERNAL_STATE")

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=tmp_path / "absent-bundle",
        prefetch_handoff_path=tmp_path / "absent-handoff.json",
        window_open_receipt_path=tmp_path / "absent-window.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=tmp_path / "binding.json",
        output_pack_directory=tmp_path / "pack",
        resolver=forbidden,
        marker_inspector=forbidden,
        execute=execute,
        owner_present_for_at_least_20_minutes=owner_present,
        clock=forbidden,
        monotonic=forbidden,
        sleeper=forbidden,
        workspace_validator=forbidden,
        raw_evidence_verifier=forbidden,
        atomic_runner=forbidden,
    )
    assert result.status == "OWNER_GATE_REJECTED"
    assert result.atomic_result is None


def test_h2_preparation_started_at_window_open_fails_without_publishing_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        FIRST_C0_CANARY_CLI.FirstC0CanaryPreparationError,
        match="^FIRST_C0_H2_PREFETCH_REQUIRED_BEFORE_WINDOW_OPEN$",
    ):
        build_ready_canary_bundle(
            tmp_path,
            monkeypatch,
            earliest=BASE + timedelta(hours=3),
            ready_now=True,
        )
    control = tmp_path / "control"
    assert not (control / "first-c0-canary-open-bundle").exists()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()


@pytest.mark.parametrize(("validation_seconds", "accepted"), [(45, True), (46, False)])
def test_ready_h2_read_only_preflight_resamples_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validation_seconds: int,
    accepted: bool,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at,
        wait_started_monotonic=100.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([100.0]),
        workspace_validator=lambda _: None,
    )
    timeline = CoherentSequenceTimeline(
        (execution_at, execution_at + timedelta(seconds=validation_seconds)),
        initial_wall=execution_at,
        initial_monotonic=100.0,
    )

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_args: (),
        marker_inspector=marker_inspector,
        execute=False,
        owner_present_for_review=False,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=timeline.clock,
        monotonic=timeline.monotonic,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )

    assert result.preflight.accepted is accepted
    assert result.resolver_operations == result.pack_builds == 0
    if not accepted:
        assert "FIRST_C0_OPEN_TO_PREFLIGHT_BUDGET_EXCEEDED" in result.preflight.errors


def test_legacy_h2_future_bundle_cannot_activate_without_window_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
    )
    resolver_calls = Counter()

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("LEGACY_FUTURE_REACHED_DNS")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "FIRST_C0_WINDOW_RECEIPT_REQUIRED" in result.preflight.errors
    assert result.resolver_operations == 0
    assert result.pack_builds == 0
    assert resolver_calls.value == 0


@pytest.mark.parametrize("provider_operation", ["reserve", "bind_once"])
def test_first_c0_provider_api_requires_atomic_preflight_before_claim_or_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_operation: str,
) -> None:
    bundle, workspace, mission, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    resolver_calls = Counter()

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("FIRST_C0_PROVIDER_API_REACHED_DNS")

    with pytest.raises(
        ProviderNetworkPreparationError,
        match="FIRST_C0_ATOMIC_PREFLIGHT_REQUIRED",
    ):
        if provider_operation == "reserve":
            reserve_provider_network_resolution_v1(
                workspace_receipt=workspace,
                mission_manifest=mission,
                campaign_selection=loaded.campaign_selection,
                output_path=bundle.parent / "binding.json",
                clock=FixedClock(execution_at),
            )
        else:
            prepare_provider_network_binding_once_v1(
                workspace_receipt=workspace,
                mission_manifest=mission,
                campaign_selection=loaded.campaign_selection,
                output_path=bundle.parent / "binding.json",
                resolver=forbidden_resolver,
                clock=FixedClock(execution_at),
            )

    assert resolver_calls.value == 0
    assert not (bundle.parent / "provider-network-resolution-one-shot-v1.json").exists()
    assert not (bundle.parent / "binding.json").exists()


@pytest.mark.parametrize(
    ("observation", "expected_status", "expected_code"),
    (
        (
            "window_open",
            "STOP_TOO_LATE_BEFORE_DNS",
            "FIRST_C0_PREFETCH_REQUIRED_BEFORE_WINDOW_OPEN",
        ),
        ("window_expired", "STOP_EXPIRED_BEFORE_DNS", "FIRST_C0_WINDOW_EXPIRED"),
    ),
)
def test_legacy_future_entrypoint_never_reports_future_after_window_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observation: str,
    expected_status: str,
    expected_code: str,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    selected = loaded.campaign_selection.selected_candidate()
    observed_at = execution_at if observation == "window_open" else selected.window_expires_at_utc
    delegated = Counter()
    resolver_calls = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("LEGACY_ENTRYPOINT_DELEGATED")

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("LEGACY_ENTRYPOINT_REACHED_DNS")

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=None,
        window_open_receipt_path=bundle.parent / "unused-window-open-receipt.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(observed_at),
        monotonic=SequenceMonotonic((100.0,)),
        sleeper=lambda _seconds: None,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )

    assert result.status == expected_status
    assert result.code == expected_code
    assert result.atomic_result is None
    assert delegated.value == resolver_calls.value == 0


def test_rehashed_prefetched_to_legacy_schema_downgrade_cannot_reach_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    downgraded_manifest = dict(loaded.manifest)
    downgraded_manifest["schema_version"] = "robin-first-c0-canary-bundle-v1"
    downgraded_manifest["status"] = "CANARY_FUTURE_WINDOW"
    for field in (
        "h2_window_duration_seconds",
        "h2_prefetch_lead_seconds",
        "post_open_total_budget_seconds",
        "post_open_safety_reserve_seconds",
        "maximum_open_to_preflight_seconds",
    ):
        downgraded_manifest.pop(field)
    downgraded = replace(loaded, manifest=downgraded_manifest)
    monkeypatch.setattr(
        predns_module, "load_pre_dns_bundle_v1", lambda *_args, **_kwargs: downgraded
    )
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (_ for _ in ()).throw(AssertionError("DOWNGRADE_REACHED_DNS")),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "FIRST_C0_WINDOW_RECEIPT_REQUIRED" in result.preflight.errors
    assert result.resolver_operations == 0
    assert result.pack_builds == 0


@pytest.mark.parametrize(
    ("seconds_until_open", "expected_code"),
    [(900.0, "PREFETCH_REQUIRED_AT_RECOMMENDED_START"), (900.001, None)],
)
def test_single_owner_entrypoint_local_wait_planning_boundary_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seconds_until_open: float,
    expected_code: str | None,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=3),
    )
    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=None,
        window_open_receipt_path=bundle.parent / "unused-window-open-receipt.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(execution_at - timedelta(seconds=seconds_until_open)),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "FUTURE_OWNER_SEQUENCE_PLANNED"
    assert result.code == expected_code


def test_h24_future_planning_and_ready_direct_behavior_are_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=BASE + timedelta(hours=27),
        mission_expires_at=BASE + timedelta(hours=4),
    )
    future = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=future_bundle,
        prefetch_handoff_path=None,
        window_open_receipt_path=future_bundle.parent / "unused-window-open-receipt.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=future_bundle.parent / "future-binding.json",
        output_pack_directory=future_bundle.parent / "future-pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert future.status == "FUTURE_OWNER_SEQUENCE_PLANNED"
    assert future.recommended_owner_sequence_start_utc == execution_at - timedelta(seconds=60)

    ready_registry = tmp_path / "ready-mission-global-preparation-registry"
    ready_registry.mkdir()
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "resolve_global_claim_root_candidate_v2",
        lambda _workspace: ready_registry,
    )
    monkeypatch.setattr(
        FIRST_C0_CANARY_CLI.global_claims,
        "ensure_global_claim_root_v2",
        lambda _workspace, **_kwargs: ready_registry,
    )
    ready_bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path / "ready",
        monkeypatch,
        ready_now=True,
        earliest=BASE + timedelta(hours=27),
        mission_expires_at=BASE + timedelta(hours=4),
    )
    resolver_calls = Counter()

    def counted_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        return synthetic_resolver(*args)

    ready = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=ready_bundle,
        prefetch_handoff_path=None,
        window_open_receipt_path=ready_bundle.parent / "unused-window-open-receipt.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=ready_bundle.parent / "binding.json",
        output_pack_directory=ready_bundle.parent / "pack",
        resolver=counted_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=partial(
            run_owner_review_pack_once_v1,
            binding_preparer=fake_binding_preparer,
        ),
    )
    assert ready.status == "OWNER_REVIEW_PACK_CREATED"
    assert resolver_calls.value == 1


def test_single_owner_future_plan_crosses_utc_date_without_timing_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        earliest=datetime(2026, 8, 25, 2, 17, tzinfo=UTC),
    )
    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=None,
        window_open_receipt_path=bundle.parent / "unused-window-open-receipt.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(BASE),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "FUTURE_OWNER_SEQUENCE_PLANNED"
    assert execution_at == datetime(2026, 8, 25, 0, 2, tzinfo=UTC)
    assert result.recommended_owner_sequence_start_utc == datetime(
        2026,
        8,
        24,
        23,
        57,
        tzinfo=UTC,
    )


def test_single_owner_paris_rendering_disambiguates_dst_fold() -> None:
    first_fold = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    second_fold = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert FIRST_C0_OWNER_ATOMIC_CLI._europe_paris_text(first_fold) == ("2026-10-25T02:30:00+02:00")
    assert FIRST_C0_OWNER_ATOMIC_CLI._europe_paris_text(second_fold) == (
        "2026-10-25T02:30:00+01:00"
    )
    assert FIRST_C0_OWNER_ATOMIC_CLI._utc_text(first_fold) == "2026-10-25T00:30:00Z"
    assert FIRST_C0_OWNER_ATOMIC_CLI._utc_text(second_fold) == "2026-10-25T01:30:00Z"


def _first_c0_owner_cli_arguments(tmp_path: Path) -> list[str]:
    return [
        "run_first_c0_owner_pack_atomic_v1.py",
        "--workspace-receipt",
        str(tmp_path / "workspace.json"),
        "--mission-manifest",
        str(tmp_path / "mission.json"),
        "--pre-dns-bundle",
        str(tmp_path / "bundle"),
        "--window-open-receipt",
        str(tmp_path / "window-open.json"),
        "--output-binding",
        str(tmp_path / "binding.json"),
        "--output-pack-directory",
        str(tmp_path / "pack"),
        "--historical-marker",
        str(tmp_path / "historical-marker.json"),
        "--historical-marker-manifest-sha256",
        "c" * 64,
        "--historical-marker-sha256",
        "a" * 64,
        "--historical-marker-acl-sha256",
        "b" * 64,
    ]


def test_single_owner_cli_rejects_absent_gates_before_any_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden_read(_path: Path) -> bytes:
        raise AssertionError("OWNER_GATE_READ_EXTERNAL_STATE")

    monkeypatch.setattr(FIRST_C0_OWNER_ATOMIC_CLI, "_read", forbidden_read)
    monkeypatch.setattr(sys, "argv", _first_c0_owner_cli_arguments(tmp_path))
    assert FIRST_C0_OWNER_ATOMIC_CLI.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "OWNER_GATE_REJECTED",
        "code": "EXECUTE_AND_OWNER_PRESENCE_REQUIRED",
        "provider_dns": 0,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,
        "pack_builds": 0,
        "owner_authorizations": 0,
        "c0_calls": 0,
        "effects_complete": True,
    }


def test_single_owner_cli_reports_effects_truthfully_after_resolver_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, mission = build_authority(tmp_path)
    control = Path(workspace.control_temp_root)
    workspace_path = tmp_path / "workspace.json"
    workspace_path.write_bytes(canonical_model_bytes(workspace))

    class FailureAfterResolver(RuntimeError):
        code = "SYNTHETIC_FAILURE_AFTER_RESOLVER"

    def fail_after_resolver(**kwargs: object) -> object:
        resolver = cast(Callable[..., Iterable[tuple[object, ...]]], kwargs["resolver"])
        tuple(resolver("api.the-odds-api.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, 0))
        raise FailureAfterResolver

    monkeypatch.setattr(
        FIRST_C0_OWNER_ATOMIC_CLI,
        "assert_real_capture_workspace_receipt_current_v1",
        lambda _workspace: None,
    )
    monkeypatch.setattr(
        FIRST_C0_OWNER_ATOMIC_CLI,
        "load_tracked_real_execution_mission_manifest_v1",
        lambda _root, _path: mission,
    )
    monkeypatch.setattr(
        FIRST_C0_OWNER_ATOMIC_CLI,
        "assert_workspace_control_artifact_destination_v1",
        lambda _workspace, destination: destination,
    )
    monkeypatch.setattr(FIRST_C0_OWNER_ATOMIC_CLI, "_system_resolver", synthetic_resolver)
    monkeypatch.setattr(
        FIRST_C0_OWNER_ATOMIC_CLI,
        "_run_first_c0_owner_pack_atomic_v1",
        fail_after_resolver,
    )
    arguments = _first_c0_owner_cli_arguments(tmp_path)
    arguments[2] = str(workspace_path)
    arguments.extend(("--execute", "--owner-present-for-at-least-20-minutes"))
    monkeypatch.setattr(sys, "argv", arguments)
    assert FIRST_C0_OWNER_ATOMIC_CLI.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "FAILED",
        "code": "SYNTHETIC_FAILURE_AFTER_RESOLVER",
        "provider_dns": 1,
        "resolver_operations": 1,
        "provider_tcp": 0,
        "provider_http": 0,
        "secret_reads": 0,
        "pack_builds": None,
        "owner_authorizations": 0,
        "c0_calls": 0,
        "effects_complete": False,
    }
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()


class ResidentTimeline:
    def __init__(self, wall: datetime, monotonic: float) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def clock(self) -> datetime:
        return self.wall

    def monotonic_clock(self) -> float:
        return self.monotonic

    def sleep(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic += seconds


class OneStepAnomalousResidentTimeline(ResidentTimeline):
    def __init__(
        self,
        wall: datetime,
        monotonic: float,
        *,
        target_wall: datetime,
        target_monotonic: float,
    ) -> None:
        super().__init__(wall, monotonic)
        self.target_wall = target_wall
        self.target_monotonic = target_monotonic

    def sleep(self, _seconds: float) -> None:
        self.wall = self.target_wall
        self.monotonic = self.target_monotonic


class PostLoopAdvanceResidentTimeline(ResidentTimeline):
    def __init__(
        self,
        wall: datetime,
        monotonic: float,
        *,
        activation_at: datetime,
    ) -> None:
        super().__init__(wall, monotonic)
        self.activation_at = activation_at
        self.clock_calls = 0

    def clock(self) -> datetime:
        self.clock_calls += 1
        if self.clock_calls == 4:
            delta = (self.activation_at - self.wall).total_seconds()
            assert delta >= 0
            self.wall = self.activation_at
            self.monotonic += delta
        return self.wall


class InstantTimeline(ResidentTimeline):
    def sleep(self, seconds: float) -> None:
        zone = self.wall.tzinfo
        assert zone is not None
        self.wall = (self.wall.astimezone(UTC) + timedelta(seconds=seconds)).astimezone(zone)
        self.monotonic += seconds


@pytest.mark.parametrize("handoff_gap", ["coherent_ten_seconds", "wall_rollback"])
def test_single_owner_resamples_a_coherent_pair_after_handoff_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handoff_gap: str,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    timeline = ResidentTimeline(execution_at - timedelta(seconds=10), 100.0)
    original_loader = FIRST_C0_OWNER_ATOMIC_CLI.load_first_c0_prefetch_handoff_v1
    delegated = Counter()
    resolver_calls = Counter()

    def load_with_gap(
        path: Path,
        loaded: LoadedPreDnsBundleV1,
    ) -> FirstC0PrefetchedWindowHandoffV1:
        handoff = original_loader(path, loaded)
        if handoff_gap == "coherent_ten_seconds":
            timeline.sleep(10.0)
        else:
            timeline.wall -= timedelta(seconds=1)
            timeline.monotonic += 1.0
        return handoff

    def atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        return AtomicRunnerResultV1(
            status="OWNER_REVIEW_PACK_CREATED",
            preflight=RunnerPreflightV1(
                accepted=True,
                status="PREFLIGHT_ACCEPT",
                errors=(),
                checked_at_utc=execution_at,
                usable_margin_seconds=900,
            ),
            resolver_operations=1,
            pack_builds=1,
            binding_sha256="a" * 64,
            pack_sha256="b" * 64,
            receipt_path=bundle.parent / "pack" / "execution-receipt.json",
            hard_stop_code=None,
        )

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("HANDOFF_GAP_REACHED_REAL_RESOLVER")

    monkeypatch.setattr(
        FIRST_C0_OWNER_ATOMIC_CLI,
        "load_first_c0_prefetch_handoff_v1",
        load_with_gap,
    )
    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=bundle.parent / "first-c0-prefetched-window-handoff-v1.json",
        window_open_receipt_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=atomic,
    )

    assert resolver_calls.value == 0
    if handoff_gap == "coherent_ten_seconds":
        assert result.status == "OWNER_REVIEW_PACK_CREATED"
        assert delegated.value == 1
        assert result.window_open_receipt is not None
        assert result.window_open_receipt.status == "READY_NOW"
        assert result.window_open_receipt.wall_elapsed_seconds == 0
    else:
        assert result.status == "CLOCK_INVALID_BEFORE_DNS"
        assert result.code == "FIRST_C0_PREFLIGHT_CLOCK_INVALID"
        assert result.window_open_receipt is None
        assert delegated.value == 0


def test_prefetched_owner_sequence_propagates_atomic_hard_stop_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    timeline = ResidentTimeline(execution_at, 100.0)

    def hard_stopped_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        return AtomicRunnerResultV1(
            status="POST_DNS_HARD_STOP",
            preflight=RunnerPreflightV1(
                accepted=True,
                status="PREFLIGHT_ACCEPT",
                errors=(),
                checked_at_utc=execution_at,
                usable_margin_seconds=900,
            ),
            resolver_operations=1,
            pack_builds=0,
            binding_sha256=None,
            pack_sha256=None,
            receipt_path=bundle.parent / "pack-hard-stop-receipt.json",
            hard_stop_code="SYNTHETIC_POST_DNS_FAILURE",
        )

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=bundle.parent / "first-c0-prefetched-window-handoff-v1.json",
        window_open_receipt_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_args: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=hard_stopped_atomic,
    )

    assert result.status == "POST_DNS_HARD_STOP"
    assert result.code == "SYNTHETIC_POST_DNS_FAILURE"
    assert result.atomic_result is not None
    assert result.window_open_receipt is not None
    assert result.window_open_receipt.status == "READY_NOW"


@pytest.mark.parametrize(
    "scenario",
    [
        "clock_rollback",
        "clock_forward_jump",
        "monotonic_divergence",
    ],
)
def test_single_owner_resident_wait_rejects_temporal_anomalies_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
        earliest=BASE + timedelta(hours=3),
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    wait_started = execution_at - timedelta(seconds=10)
    target_wall_by_scenario = {
        "clock_rollback": wait_started - timedelta(seconds=1),
        "clock_forward_jump": wait_started + timedelta(seconds=60),
        "monotonic_divergence": wait_started + timedelta(seconds=1),
    }
    target_wall = target_wall_by_scenario[scenario]
    wall_elapsed = (target_wall - wait_started).total_seconds()
    target_monotonic = (
        110.0
        if scenario == "monotonic_divergence"
        else 101.0
        if scenario == "clock_rollback"
        else 100.0 + max(0.0, wall_elapsed)
    )
    timeline = OneStepAnomalousResidentTimeline(
        wait_started,
        100.0,
        target_wall=target_wall,
        target_monotonic=target_monotonic,
    )
    delegated = Counter()
    resolver_calls = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("TEMPORAL_ANOMALY_DELEGATED")

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("TEMPORAL_ANOMALY_REACHED_DNS")

    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )
    assert result.status == "CLOCK_INVALID_BEFORE_DNS"
    assert result.code == "FIRST_C0_WINDOW_CLOCK_INVALID"
    assert result.atomic_result is None
    assert delegated.value == resolver_calls.value == 0
    assert result.window_open_receipt is not None
    receipt = result.window_open_receipt
    assert receipt.status == "CLOCK_INVALID"
    assert receipt.clock_path_valid is False
    assert receipt.provider_effects == 0
    assert receipt_path.is_file()
    if scenario == "clock_rollback":
        assert receipt.wall_elapsed_seconds < 0
    elif scenario == "clock_forward_jump":
        assert receipt.wall_elapsed_seconds == 60
    else:
        assert receipt.clock_divergence_seconds > 2


@pytest.mark.parametrize("terminal", ["mission_expiry", "window_closed"])
def test_single_owner_resident_terminal_expiry_is_not_a_clock_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    open_at = BASE + timedelta(minutes=45)
    mission_expiry = open_at + timedelta(seconds=885) if terminal == "mission_expiry" else None
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
        earliest=BASE + timedelta(hours=3),
        mission_expires_at=mission_expiry,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    selected = loaded.campaign_selection.selected_candidate()
    activation_at = (
        mission.expires_at if terminal == "mission_expiry" else selected.window_expires_at_utc
    )
    timeline = PostLoopAdvanceResidentTimeline(
        execution_at - timedelta(seconds=1),
        100.0,
        activation_at=activation_at,
    )
    delegated = Counter()
    resolver_calls = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("EXPIRED_RESIDENT_DELEGATED")

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("EXPIRED_RESIDENT_REACHED_DNS")

    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )
    assert result.status == "STOP_EXPIRED_BEFORE_DNS"
    assert result.code == "FIRST_C0_WINDOW_EXPIRED"
    assert result.atomic_result is None
    assert delegated.value == resolver_calls.value == 0
    assert result.window_open_receipt is not None
    receipt = result.window_open_receipt
    assert receipt.status == "EXPIRED"
    assert receipt.clock_path_valid is True
    assert receipt.checked_at_utc == activation_at
    if terminal == "mission_expiry":
        assert receipt.checked_at_utc < receipt.window_expires_at_utc
        assert receipt.mission_current is False
    else:
        assert receipt.checked_at_utc == receipt.window_expires_at_utc
        assert receipt.mission_current is True


@pytest.mark.parametrize("dominated_boundary", ["source_stale", "kickoff_safety_ceiling"])
def test_single_owner_resident_dominated_boundaries_stop_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dominated_boundary: str,
) -> None:
    bundle, workspace, mission, marker_inspector, _ = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    selected = loaded.campaign_selection.selected_candidate()
    earliest_kickoff = min(
        target.official_kickoff_utc for target in selected.fixture_target_set.targets
    )
    source_stale_after = handoff.source_observed_at_utc + timedelta(
        seconds=handoff.maximum_source_age_seconds,
        microseconds=1,
    )
    kickoff_ceiling = earliest_kickoff - PRE_KICKOFF_SAFETY_MARGIN
    assert selected.window_expires_at_utc < source_stale_after
    assert selected.window_expires_at_utc < kickoff_ceiling
    checked_at = source_stale_after if dominated_boundary == "source_stale" else kickoff_ceiling
    delegated = Counter()
    resolver_calls = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("DOMINATED_BOUNDARY_DELEGATED")

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("DOMINATED_BOUNDARY_REACHED_DNS")

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(checked_at),
        monotonic=SequenceMonotonic([100.0]),
        sleeper=lambda _seconds: None,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )
    assert result.status == "STOP_TOO_LATE_BEFORE_DNS"
    assert result.code == "FIRST_C0_OWNER_SEQUENCE_STARTED_TOO_LATE"
    assert result.atomic_result is None
    assert result.window_open_receipt is None
    assert delegated.value == resolver_calls.value == 0


@pytest.mark.parametrize(
    ("open_at", "zone_name"),
    [
        (datetime(2027, 3, 28, 1, 0, 5, tzinfo=UTC), "Europe/Paris"),
        (datetime(2026, 10, 25, 1, 0, 5, tzinfo=UTC), "Europe/Paris"),
        (datetime(2026, 8, 25, 0, 0, 5, tzinfo=UTC), "UTC"),
    ],
)
def test_single_owner_resident_activation_is_portable_across_dst_and_utc_rollover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    open_at: datetime,
    zone_name: str,
) -> None:
    case_base = open_at - timedelta(minutes=45)
    monkeypatch.setattr(sys.modules[__name__], "BASE", case_base)
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
        earliest=case_base + timedelta(hours=3),
    )
    assert execution_at == open_at
    zone = ZoneInfo(zone_name)
    wait_started = (open_at - timedelta(seconds=10)).astimezone(zone)
    timeline = InstantTimeline(wait_started, 100.0)
    delegated = Counter()

    def accepting_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        return AtomicRunnerResultV1(
            status="OWNER_REVIEW_PACK_CREATED",
            preflight=RunnerPreflightV1(
                accepted=True,
                status="PREFLIGHT_ACCEPT",
                errors=(),
                checked_at_utc=open_at,
                usable_margin_seconds=900,
            ),
            resolver_operations=1,
            pack_builds=1,
            binding_sha256="a" * 64,
            pack_sha256="b" * 64,
            receipt_path=bundle.parent / "pack" / "execution-receipt.json",
            hard_stop_code=None,
        )

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=bundle.parent / "first-c0-prefetched-window-handoff-v1.json",
        window_open_receipt_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=accepting_atomic,
    )
    assert result.status == "OWNER_REVIEW_PACK_CREATED"
    assert delegated.value == 1
    assert result.window_open_receipt is not None
    receipt = result.window_open_receipt
    assert receipt.status == "READY_NOW"
    assert receipt.checked_at_utc == open_at
    assert receipt.wall_elapsed_seconds == receipt.monotonic_elapsed_seconds == 10
    assert (
        receipt.official_reads_delta
        == receipt.preparation_cycles_delta
        == receipt.selector_invocations_delta
        == receipt.target_set_freezes_delta
        == receipt.provider_effects
        == 0
    )
    if zone_name == "Europe/Paris":
        assert wait_started.utcoffset() != timeline.wall.utcoffset()
    else:
        assert wait_started.date() != timeline.wall.date()


def test_single_owner_rejects_post_loop_clock_rollback_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    wall_clock = SequenceClock(
        (
            execution_at - timedelta(seconds=1),
            execution_at + timedelta(seconds=1),
            execution_at + timedelta(milliseconds=500),
        )
    )
    monotonic_clock = SequenceMonotonic((100.0, 101.0, 100.5))
    delegated = Counter()
    resolver_calls = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("POST_LOOP_ROLLBACK_DELEGATED")

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("POST_LOOP_ROLLBACK_REACHED_DNS")

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=forbidden_resolver,
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=wall_clock,
        monotonic=monotonic_clock,
        sleeper=lambda _seconds: None,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )
    assert result.status == "CLOCK_INVALID_BEFORE_DNS"
    assert result.code == "FIRST_C0_WINDOW_CLOCK_INVALID"
    assert result.atomic_result is None
    assert delegated.value == resolver_calls.value == 0
    assert result.window_open_receipt is not None
    assert result.window_open_receipt.status == "CLOCK_INVALID"
    assert result.window_open_receipt.clock_path_valid is False
    assert result.window_open_receipt.checked_at_utc == execution_at + timedelta(milliseconds=500)
    assert receipt_path.is_file()


def test_single_owner_entrypoint_stays_resident_and_delegates_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    timeline = ResidentTimeline(execution_at - timedelta(seconds=10), 100.0)
    delegated: list[dict[str, object]] = []

    def atomic_runner(**kwargs: object) -> AtomicRunnerResultV1:
        delegated.append(dict(kwargs))
        assert Path(cast(Path, kwargs["window_open_receipt_path"])).is_file()
        preflight = RunnerPreflightV1(
            accepted=True,
            status="PREFLIGHT_ACCEPT",
            errors=(),
            checked_at_utc=execution_at + timedelta(seconds=5),
            usable_margin_seconds=895,
        )
        return AtomicRunnerResultV1(
            status="OWNER_REVIEW_PACK_CREATED",
            preflight=preflight,
            resolver_operations=1,
            pack_builds=1,
            binding_sha256="a" * 64,
            pack_sha256="b" * 64,
            receipt_path=bundle.parent / "pack" / "execution-receipt.json",
            hard_stop_code=None,
        )

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=timeline.clock,
        monotonic=timeline.monotonic_clock,
        sleeper=timeline.sleep,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=atomic_runner,
    )
    assert result.status == "OWNER_REVIEW_PACK_CREATED"
    assert len(delegated) == 1
    assert result.window_open_receipt is not None
    assert result.window_open_receipt.status == "READY_NOW"
    assert result.window_open_receipt.official_reads_delta == 0
    assert result.window_open_receipt.preparation_cycles_delta == 0
    assert result.window_open_receipt.selector_invocations_delta == 0
    assert result.window_open_receipt.target_set_freezes_delta == 0


def test_single_owner_entrypoint_stops_too_late_before_delegate_or_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    delegated = Counter()

    def forbidden_atomic(**_kwargs: object) -> AtomicRunnerResultV1:
        delegated.value += 1
        raise AssertionError("TOO_LATE_DELEGATED")

    result = FIRST_C0_OWNER_ATOMIC_CLI._run_first_c0_owner_pack_atomic_v1(
        bundle_directory=bundle,
        prefetch_handoff_path=bundle.parent / "first-c0-prefetched-window-handoff-v1.json",
        window_open_receipt_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_at_least_20_minutes=True,
        clock=FixedClock(execution_at + timedelta(seconds=16)),
        monotonic=SequenceMonotonic([100.0]),
        sleeper=lambda _: None,
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
        atomic_runner=forbidden_atomic,
    )
    assert result.status == "STOP_TOO_LATE_BEFORE_DNS"
    assert delegated.value == 0
    assert result.atomic_result is None


def test_prefetched_bundle_cannot_bypass_window_open_receipt_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (_ for _ in ()).throw(AssertionError("DNS_BYPASS")),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        clock=FixedClock(execution_at),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "FIRST_C0_WINDOW_RECEIPT_REQUIRED" in result.preflight.errors
    assert result.resolver_operations == 0
    assert result.pack_builds == 0


@pytest.mark.parametrize(
    ("checked_delta", "monotonic_delta", "clock_path_valid", "expected_status"),
    [
        (-11, 10.0, True, "CLOCK_INVALID"),
        (0, 1.0, True, "CLOCK_INVALID"),
        (0, 10.0, False, "CLOCK_INVALID"),
        (46, 56.0, True, "HARD_STOP"),
        (901, 911.0, True, "EXPIRED"),
    ],
)
def test_window_open_revalidation_fails_closed_on_clock_and_window_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checked_delta: int,
    monotonic_delta: float,
    clock_path_valid: bool,
    expected_status: str,
) -> None:
    bundle, _, _, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock_path_valid=clock_path_valid,
        clock=FixedClock(execution_at + timedelta(seconds=checked_delta)),
        monotonic=SequenceMonotonic([90.0 + monotonic_delta]),
        workspace_validator=lambda _: None,
    )
    assert receipt.status == expected_status
    assert receipt.provider_effects == 0


@pytest.mark.parametrize(
    ("source_age_seconds", "expected_status"),
    [(1800.0, "READY_NOW"), (1800.001, "STALE")],
)
def test_window_open_source_freshness_fractional_boundary_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_age_seconds: float,
    expected_status: str,
) -> None:
    bundle, _, _, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    original = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    handoff_data = original.model_dump(
        mode="python",
        exclude={"canonical_receipt_sha256"},
    )
    handoff_data["source_observed_at_utc"] = execution_at - timedelta(seconds=1800)
    handoff_data["source_age_at_window_open_seconds"] = 1800
    handoff = FirstC0PrefetchedWindowHandoffV1.issue(**handoff_data)
    _write_canonical_test_json(handoff_path, handoff.model_dump(mode="json"))
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at + timedelta(seconds=source_age_seconds - 1800)),
        monotonic=SequenceMonotonic([100.0 + source_age_seconds - 1800]),
        workspace_validator=lambda _: None,
    )
    assert receipt.source_age_seconds == 1800
    assert receipt.source_fresh is (expected_status == "READY_NOW")
    assert receipt.status == expected_status
    assert receipt.provider_effects == 0


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_window_open_nonfinite_monotonic_is_recorded_as_clock_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nonfinite: float,
) -> None:
    bundle, _, _, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([nonfinite]),
        workspace_validator=lambda _: None,
    )
    assert receipt.status == "CLOCK_INVALID"
    assert receipt.clock_path_valid is False
    assert receipt_path.is_file()
    assert receipt.provider_effects == 0


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf")])
def test_nonfinite_monotonic_after_activation_rejects_before_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nonfinite: float,
) -> None:
    bundle, workspace, mission, marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([100.0]),
        workspace_validator=lambda _: None,
    )
    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=mission,
        output_binding_path=bundle.parent / "binding.json",
        output_pack_directory=bundle.parent / "pack",
        resolver=lambda *_: (_ for _ in ()).throw(AssertionError("NONFINITE_REACHED_DNS")),
        marker_inspector=marker_inspector,
        execute=True,
        owner_present_for_review=True,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at + timedelta(seconds=5)),
        monotonic=SequenceMonotonic([nonfinite]),
        workspace_validator=lambda _: None,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "PREFLIGHT_REJECTED"
    assert "FIRST_C0_PREFLIGHT_CLOCK_INVALID" in result.preflight.errors
    assert result.resolver_operations == 0
    assert result.pack_builds == 0


@pytest.mark.parametrize("tamper_target", ["bundle", "handoff"])
def test_window_open_revalidation_detects_prefetch_tampering_during_local_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_target: str,
) -> None:
    bundle, _, _, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    if tamper_target == "bundle":
        (bundle / "official-source-raw.bin").write_bytes(b"tampered")
    else:
        handoff_path.write_bytes(handoff_path.read_bytes() + b" ")
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=bundle.parent / "first-c0-window-open-revalidation-v1.json",
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([100.0]),
        workspace_validator=lambda _: None,
    )
    assert receipt.status == "HARD_STOP"
    assert not receipt.bundle_current or not receipt.handoff_current
    assert receipt.provider_effects == 0


def test_handoff_and_window_receipt_canonical_hash_tampering_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _, _, _, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    handoff_path = bundle.parent / "first-c0-prefetched-window-handoff-v1.json"
    handoff = load_first_c0_prefetch_handoff_v1(handoff_path, loaded)
    receipt_path = bundle.parent / "first-c0-window-open-revalidation-v1.json"
    receipt = revalidate_prefetched_window_open_v1(
        loaded=loaded,
        handoff=handoff,
        handoff_path=handoff_path,
        output_path=receipt_path,
        wait_started_at_utc=execution_at - timedelta(seconds=10),
        wait_started_monotonic=90.0,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic([100.0]),
        workspace_validator=lambda _: None,
    )
    receipt_payload = json.loads(receipt_path.read_bytes())
    receipt_payload["usable_margin_seconds"] -= 1
    _write_canonical_test_json(receipt_path, receipt_payload)
    with pytest.raises(PreDnsOrchestrationError, match="FIRST_C0_WINDOW_RECEIPT_INVALID"):
        load_first_c0_window_open_revalidation_v1(
            receipt_path,
            loaded,
            handoff,
            handoff_path=handoff_path,
        )
    assert receipt.canonical_receipt_sha256 != receipt_payload["canonical_receipt_sha256"] or (
        receipt.usable_margin_seconds != receipt_payload["usable_margin_seconds"]
    )


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


def test_first_c0_vertical_bundle_enforces_two_read_ceiling_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, _, _ = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        first_c0_vertical=True,
    )
    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    counters_path = bundle / "preparation-counters.json"
    counters = json.loads(counters_path.read_bytes())
    assert manifest.mission_id == "FIRST_C0_VERTICAL_V1"
    assert loaded.mission_manifest == manifest
    assert loaded.manifest["official_physical_reads_maximum"] == 2
    assert counters["official_physical_reads_maximum"] == 2
    assert counters["cumulative_official_reads"] == 2

    counters["official_physical_reads_maximum"] = 12
    counters_bytes = _write_canonical_test_json(counters_path, counters)
    bundle_manifest_path = bundle / "bundle-manifest.json"
    bundle_manifest = json.loads(bundle_manifest_path.read_bytes())
    bundle_manifest["artifact_sha256"][counters_path.name] = hashlib.sha256(
        counters_bytes
    ).hexdigest()
    bundle_manifest_bytes = _write_canonical_test_json(
        bundle_manifest_path,
        bundle_manifest,
    )
    current_attempt_path = (
        Path(workspace.control_temp_root) / "first-c0-canary-cycle-01-attempt-receipt-v1.json"
    )
    current_attempt = json.loads(current_attempt_path.read_bytes())
    current_attempt["bundle_manifest_sha256"] = hashlib.sha256(bundle_manifest_bytes).hexdigest()
    _write_canonical_test_json(current_attempt_path, current_attempt)

    with pytest.raises(
        PreDnsOrchestrationError,
        match="FIRST_C0_CANARY_BUNDLE_COUNTERS_INVALID",
    ):
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
        refresh_cycle=True,
    )
    loaded, handoff_path, receipt_path = activate_prefetched_canary_bundle(
        bundle,
        execution_at,
    )
    assert isinstance(loaded.campaign_selection, FirstC0CanarySelectionV1)
    binding = Path(workspace.control_temp_root) / "canary-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "canary-owner-review-pack"
    preflight_authority_uses = Counter()

    def gated_binding_preparer(
        *,
        workspace_receipt: RealCaptureWorkspaceReceiptV1,
        mission_manifest: RealExecutionMissionManifestV1,
        campaign_selection: CampaignSelectionAuthorityV1,
        output_path: Path,
        resolver: Callable[[str, int, int, int, int], Iterable[tuple[object, ...]]],
        clock: Callable[[], datetime],
        binding_ttl_seconds: int,
        expected_global_v2_read_identity: tuple[object, ...],
        expected_global_legacy_root_identity: tuple[object, ...],
        final_pre_effect_assertion: Callable[[], None],
    ) -> ProviderNetworkBindingV1:
        preflight_authority_uses.value += 1
        return fake_binding_preparer(
            workspace_receipt=workspace_receipt,
            mission_manifest=mission_manifest,
            campaign_selection=campaign_selection,
            output_path=output_path,
            resolver=resolver,
            clock=clock,
            binding_ttl_seconds=binding_ttl_seconds,
            expected_global_v2_read_identity=expected_global_v2_read_identity,
            expected_global_legacy_root_identity=expected_global_legacy_root_identity,
            final_pre_effect_assertion=final_pre_effect_assertion,
        )

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
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
        workspace_validator=lambda _: None,
        binding_preparer=gated_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "OWNER_REVIEW_PACK_CREATED", result.preflight.errors
    assert result.resolver_operations == result.pack_builds == 1
    assert preflight_authority_uses.value == 1
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


@pytest.mark.parametrize(
    ("root", "expected_code"),
    (
        ("v2", "GLOBAL_CLAIM_ROOT_IDENTITY_CHANGED"),
        ("legacy", "GLOBAL_CLAIM_LEGACY_CONFLICT"),
    ),
)
def test_global_root_swap_after_final_preflight_stops_before_real_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _isolated_mission_global_preparation_registry: Path,
    root: str,
    expected_code: str,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    _, handoff_path, receipt_path = activate_prefetched_canary_bundle(bundle, execution_at)
    binding = Path(workspace.control_temp_root) / "swap-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "swap-pack"
    real_preparer = predns_module._prepare_provider_network_binding_after_atomic_preflight_v1
    swapped = False
    resolver_calls = Counter()

    def swap_then_prepare(**kwargs: object) -> ProviderNetworkBindingV1:
        nonlocal swapped
        if not swapped:
            swapped = True
            if root == "v2":
                displaced = _isolated_mission_global_preparation_registry.with_name(
                    "mission-global-preparation-registry-v2-before-dns"
                )
                _isolated_mission_global_preparation_registry.rename(displaced)
                _isolated_mission_global_preparation_registry.mkdir()
            else:
                legacy = predns_module.global_claims.resolve_legacy_global_claim_root_read_only_v1()
                legacy.mkdir()
        return real_preparer(**kwargs)  # type: ignore[arg-type]

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("split-root preflight reached the real resolver")

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
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
        workspace_validator=lambda _: None,
        binding_preparer=swap_then_prepare,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )

    assert swapped
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == expected_code
    assert result.resolver_operations == resolver_calls.value == 0
    assert not binding.exists()
    assert not (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    ).exists()


def test_historical_marker_mutation_on_provider_clock_stops_before_real_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    _, handoff_path, receipt_path = activate_prefetched_canary_bundle(bundle, execution_at)
    binding = Path(workspace.control_temp_root) / "historical-mutation-binding.json"
    pack_directory = Path(workspace.control_temp_root) / "historical-mutation-pack"
    monkeypatch.setattr(
        provider_network_module,
        "_assert_workspace_root_identities_current",
        lambda _workspace: None,
    )
    real_preparer = predns_module._prepare_provider_network_binding_after_atomic_preflight_v1
    historical_marker_mutated = False
    provider_clock_calls = Counter()
    marker_inspections = Counter()
    resolver_calls = Counter()

    def stateful_marker_inspector(
        observed_workspace: RealCaptureWorkspaceReceiptV1,
        observed_manifest: RealExecutionMissionManifestV1,
    ) -> MarkerInspectionV1:
        marker_inspections.value += 1
        observed = current_marker_inspector(observed_workspace, observed_manifest)
        if not historical_marker_mutated:
            return observed
        return replace(
            observed,
            historical_marker_unchanged=False,
            historical_raw_sha256="e" * 64,
        )

    def mutate_on_provider_clock(**kwargs: object) -> ProviderNetworkBindingV1:
        original_clock = cast(Callable[[], datetime], kwargs["clock"])

        def mutating_clock() -> datetime:
            nonlocal historical_marker_mutated
            provider_clock_calls.value += 1
            observed = original_clock()
            historical_marker_mutated = True
            return observed

        kwargs["clock"] = mutating_clock
        return real_preparer(**kwargs)  # type: ignore[arg-type]

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("mutated historical evidence reached the real resolver")

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=binding,
        output_pack_directory=pack_directory,
        resolver=forbidden_resolver,
        marker_inspector=stateful_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
        workspace_validator=lambda _: None,
        binding_preparer=mutate_on_provider_clock,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )

    assert historical_marker_mutated
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "HISTORICAL_MARKER_CHANGED"
    assert provider_clock_calls.value >= 1
    assert marker_inspections.value >= 3
    assert result.resolver_operations == resolver_calls.value == 0
    assert not binding.exists()


def test_counted_resolver_adds_no_clock_callback_after_provider_final_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    _, handoff_path, receipt_path = activate_prefetched_canary_bundle(bundle, execution_at)
    clock_calls = Counter()
    preparer_entry_calls = -1
    resolver_clock_calls: list[int] = []

    def counting_clock() -> datetime:
        clock_calls.value += 1
        return execution_at

    def observing_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_clock_calls.append(clock_calls.value)
        return synthetic_resolver(*args)

    def sampled_binding_preparer(**kwargs: object) -> ProviderNetworkBindingV1:
        nonlocal preparer_entry_calls
        preparer_entry_calls = clock_calls.value
        return fake_binding_preparer(**kwargs)  # type: ignore[arg-type]

    result = run_owner_review_pack_once_v1(
        bundle_directory=bundle,
        workspace_receipt=workspace,
        mission_manifest=manifest,
        output_binding_path=Path(workspace.control_temp_root) / "clock-binding.json",
        output_pack_directory=Path(workspace.control_temp_root) / "clock-pack",
        resolver=observing_resolver,
        marker_inspector=current_marker_inspector,
        execute=True,
        owner_present_for_review=True,
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=counting_clock,
        monotonic=SequenceMonotonic(),
        workspace_validator=lambda _: None,
        binding_preparer=sampled_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )

    assert result.status == "OWNER_REVIEW_PACK_CREATED", result.preflight.errors
    assert resolver_clock_calls == [preparer_entry_calls + 1]
    assert result.resolver_operations == 1


def test_canary_runner_forgotten_resolver_is_denied_and_marker_is_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_network_guard: object,
) -> None:
    bundle, workspace, manifest, current_marker_inspector, execution_at = build_ready_canary_bundle(
        tmp_path,
        monkeypatch,
        refresh_cycle=True,
    )
    _, handoff_path, receipt_path = activate_prefetched_canary_bundle(bundle, execution_at)

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
            prefetch_handoff_path=handoff_path,
            window_open_receipt_path=receipt_path,
            clock=FixedClock(execution_at),
            monotonic=SequenceMonotonic(),
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
        refresh_cycle=True,
    )
    _, handoff_path, receipt_path = activate_prefetched_canary_bundle(bundle, execution_at)
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
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
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
        prefetch_handoff_path=handoff_path,
        window_open_receipt_path=receipt_path,
        clock=FixedClock(execution_at),
        monotonic=SequenceMonotonic(),
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
        ready_now=True,
        earliest=BASE + timedelta(hours=27),
        mission_expires_at=BASE + timedelta(hours=1, minutes=15),
    )
    underlying_resolver_calls = Counter()
    claim_marker = (
        Path(workspace.control_temp_root) / "provider-network-resolution-one-shot-v1.json"
    )

    def forbidden_resolver(*_args: object) -> Iterable[tuple[object, ...]]:
        underlying_resolver_calls.value += 1
        raise AssertionError("resolver must not run below the canary margin")

    def rechecking_binding_preparer(
        *,
        workspace_receipt: RealCaptureWorkspaceReceiptV1,
        mission_manifest: RealExecutionMissionManifestV1,
        campaign_selection: CampaignSelectionAuthorityV1,
        output_path: Path,
        resolver: Callable[[str, int, int, int, int], Iterable[tuple[object, ...]]],
        clock: Callable[[], datetime],
        binding_ttl_seconds: int,
        expected_global_v2_read_identity: tuple[object, ...],
        expected_global_legacy_root_identity: tuple[object, ...],
        final_pre_effect_assertion: Callable[[], None],
    ) -> ProviderNetworkBindingV1:
        del workspace_receipt, mission_manifest, campaign_selection, output_path
        del resolver, binding_ttl_seconds, expected_global_v2_read_identity
        del expected_global_legacy_root_identity
        del final_pre_effect_assertion
        clock()
        claim_marker.write_bytes(b"reserved-before-final-time-sample")
        clock()
        raise AssertionError("eroded margin passed the final provider sample")

    loaded = load_pre_dns_bundle_v1(
        bundle,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    usable_expires = loaded.campaign_selection.selected_candidate().usable_expires_at_utc
    timeline = CoherentSequenceTimeline(
        (
            execution_at,
            execution_at,
            execution_at,
            usable_expires - timedelta(seconds=841),
            usable_expires - timedelta(seconds=839),
        ),
        initial_wall=execution_at,
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
        clock=timeline.clock,
        monotonic=timeline.monotonic,
        workspace_validator=lambda _: None,
        binding_preparer=rechecking_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "OWNER_REVIEW_USABLE_MARGIN_INSUFFICIENT"
    assert result.resolver_operations == underlying_resolver_calls.value == 0
    assert (claim_marker).is_file()


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
        monotonic=SequenceMonotonic(),
        duration_monotonic=SequenceMonotonic(monotonic_values),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )
    assert result.status == expected_status
    assert result.resolver_operations == 1
    assert result.pack_builds == expected_pack_builds
    assert pack.is_dir() is (expected_status == "OWNER_REVIEW_PACK_CREATED")


@pytest.mark.parametrize(
    "monotonic_values",
    (
        (float("nan"),),
        (float("inf"),),
        (10.0, 9.999),
    ),
)
def test_runner_hard_stops_on_nonfinite_or_rollback_duration_clock(
    tmp_path: Path,
    monotonic_values: tuple[float, ...],
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
        monotonic=SequenceMonotonic(),
        duration_monotonic=SequenceMonotonic(monotonic_values),
        workspace_validator=lambda _: None,
        binding_preparer=fake_binding_preparer,
        raw_evidence_verifier=synthetic_raw_evidence_verifier,
    )

    assert result.status == "POST_DNS_HARD_STOP"
    assert result.hard_stop_code == "DNS_TO_PACK_MONOTONIC_INVALID"
    assert result.resolver_operations == 1
    assert not pack.exists()
    assert result.receipt_path is not None and result.receipt_path.is_file()


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
    timeline = CoherentSequenceTimeline((BASE, BASE + timedelta(minutes=31)))

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
        clock=timeline.clock,
        monotonic=timeline.monotonic,
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

    timeline = CoherentSequenceTimeline((BASE, BASE, ceiling - timedelta(seconds=839)))
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
        clock=timeline.clock,
        monotonic=timeline.monotonic,
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
        expected_global_v2_read_identity: tuple[object, ...],
        expected_global_legacy_root_identity: tuple[object, ...],
        final_pre_effect_assertion: Callable[[], None],
    ) -> ProviderNetworkBindingV1:
        del workspace_receipt, mission_manifest, campaign_selection, output_path
        del binding_ttl_seconds, expected_global_v2_read_identity
        del expected_global_legacy_root_identity
        del final_pre_effect_assertion
        clock()
        marker.write_bytes(b"reserved-before-resolver")
        clock()
        tuple(resolver("api.the-odds-api.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, 0))
        raise AssertionError("resolver boundary must stop before a binding is returned")

    def forbidden_resolver(*args: object) -> Iterable[tuple[object, ...]]:
        resolver_calls.value += 1
        raise AssertionError("underlying resolver forbidden below 840-second margin")

    timeline = CoherentSequenceTimeline(
        (BASE, BASE, boundary, boundary, boundary + timedelta(seconds=1))
    )
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
        clock=timeline.clock,
        monotonic=timeline.monotonic,
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


def test_legacy_runner_cli_preflights_but_rejects_v5_execute_and_type_substitution(
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
    real_runner = public_run_owner_review_pack_once_v1
    synthetic_resolver_calls = Counter()
    cli_system_resolver_calls = Counter()
    marker_name = f"{manifest.mission_id.casefold()}-{manifest.canonical_manifest_sha256()}.json"
    registry = predns_module.global_claims.global_claim_marker_paths_v2(
        workspace,
        marker_name,
    ).v2.parent
    registry.mkdir(parents=True, exist_ok=True)

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
        provider_network_module.global_claims,
        "resolve_global_claim_root_candidate_v2",
        lambda _workspace: registry,
    )
    monkeypatch.setattr(
        provider_network_module.global_claims,
        "ensure_global_claim_root_v2",
        lambda _workspace, **_kwargs: registry,
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
    assert cli.main() == 2
    executed = json.loads(capsys.readouterr().out)
    assert executed["status"] == "PREFLIGHT_REJECTED"
    assert "FIRST_C0_SINGLE_OWNER_ENTRYPOINT_REQUIRED" in executed["preflight_errors"]
    assert executed["resolver_operations"] == executed["pack_builds"] == 0
    assert synthetic_resolver_calls.value == cli_system_resolver_calls.value == 0
    assert not binding.exists() and not pack.exists()
    assert not (control / "provider-network-resolution-one-shot-v1.json").exists()
    assert tuple(registry.iterdir()) == ()
    assert executed["owner_authorization_statement"] is None


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
