from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from robin.capture import RealExecutionMissionManifestV1
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1"
START_MAIN = "0591f01c580eb853890e9c1c304a78c21ba9de63"
SOURCE_HASH = "0270bdd51d8d50b7d3c9f608e4f429b46b94b789d92d4b13055b81c9b72e6291"
OLD_SOURCE_HASH = "2451cd643c2d3ffcd3c5cc9fcd4a5f81f785978e0aa20429b4d182ceb9b1f22b"
EXPECTED_CANONICAL_MANIFEST_SHA256 = (
    "d895e0b2ddded2c9763d85a08efbd64dc0185d26f66bb2b73fbe52cc05411206"
)


def load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_mission_manifest_matches_the_exact_external_effect_boundary() -> None:
    manifest = load("configs/execution/real-execution-bootstrap-closure-v1.json")
    assert set(manifest) == {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    assert manifest["mission_id"] == MISSION_ID
    assert manifest["authorized_stages"] == ["E1"]
    assert manifest["maximum_stage"] == "E1"
    assert manifest["source_hash"] == SOURCE_HASH
    effects = manifest["external_effects"]
    assert isinstance(effects, list)
    assert "provider_public_dns_resolution_exactly_once_after_merge" in effects
    assert all("provider_http" not in effect for effect in effects)
    validated = RealExecutionMissionManifestV1.issue(**manifest)
    assert validated.canonical_manifest_sha256() == EXPECTED_CANONICAL_MANIFEST_SHA256
    assert validated.expires_at.isoformat().replace("+00:00", "Z") == ("2026-09-01T20:00:00Z")
    assert validated.external_effects == tuple(effects)

    historical = dict(manifest)
    historical["source_hash"] = OLD_SOURCE_HASH
    with pytest.raises(ValueError):
        RealExecutionMissionManifestV1.issue(**historical)

    serialized_effects = json.dumps(effects).casefold()
    assert "provider_http" not in serialized_effects
    assert "provider_tcp" not in serialized_effects
    assert "secret" not in serialized_effects


def test_production_bootstrap_clis_do_not_accept_backdated_timestamps_or_self_pins() -> None:
    forbidden = {
        "tools/data-sourcing/prepare_real_capture_workspace_v1.py": "--prepared-at-utc",
        "tools/data-sourcing/freeze_official_fixture_target_set_v1.py": "--created-at-utc",
        "tools/data-sourcing/select_campaign_window_v1.py": "--selected-at-utc",
        "tools/data-sourcing/build_owner_review_pack_v1.py": "--generated-at-utc",
        "tools/data-sourcing/run_bounded_live_canary_v2.py": "--owner-authorization-sha256",
    }
    for path, argument in forbidden.items():
        assert argument not in (ROOT / path).read_text(encoding="utf-8")
    owner_pack_cli = (ROOT / "tools/data-sourcing/build_owner_review_pack_v1.py").read_text(
        encoding="utf-8"
    )
    dns_cli = (ROOT / "tools/data-sourcing/prepare_provider_network_binding_v1.py").read_text(
        encoding="utf-8"
    )
    assert "--fixture-target-set" not in owner_pack_cli
    assert "--request" not in owner_pack_cli
    assert "--campaign-selection" in owner_pack_cli
    assert "--campaign-selection" in dns_cli
    assert owner_pack_cli.index("paths = write_owner_review_pack_v1") < owner_pack_cli.index(
        "assert_owner_review_pack_completion_current_v1(pack"
    )
    assert "--official-source-content" in (
        ROOT / "tools/data-sourcing/freeze_official_fixture_target_set_v1.py"
    ).read_text(encoding="utf-8")
    for path in (
        "tools/data-sourcing/freeze_official_fixture_target_set_v1.py",
        "tools/data-sourcing/select_campaign_window_v1.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
        "tools/data-sourcing/build_owner_review_pack_v1.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        assert "assert_real_capture_workspace_receipt_current_v1" in source
        assert "assert_workspace_control_artifact_destination_v1" in source
    for path in (
        "tools/data-sourcing/select_campaign_window_v1.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
        "tools/data-sourcing/build_owner_review_pack_v1.py",
        "tools/data-sourcing/run_bounded_live_canary_v2.py",
    ):
        source = (ROOT / path).read_text(encoding="utf-8")
        manifest_load = source.index("manifest = load_tracked_real_execution_mission_manifest_v1(")
        effect_boundary = source.index(
            {
                "tools/data-sourcing/select_campaign_window_v1.py": (
                    "selection = CampaignWindowSelectionV1.issue("
                ),
                "tools/data-sourcing/prepare_provider_network_binding_v1.py": (
                    "binding = prepare_provider_network_binding_once_v1("
                ),
                "tools/data-sourcing/build_owner_review_pack_v1.py": (
                    "pack = build_owner_review_pack_v1("
                ),
                "tools/data-sourcing/run_bounded_live_canary_v2.py": (
                    "secret_reader=EnvironmentSecretReader(),"
                ),
            }[path]
        )
        assert manifest_load < effect_boundary


def test_matrix_authorizes_only_ordered_bootstrap_and_owner_candidates() -> None:
    matrix = load("configs/agents/mission-activation-matrix-v3.json")
    authorization = matrix["authorization"]
    assert isinstance(authorization, dict)
    delivery = authorization["real_execution_bootstrap_closure_v1_delivery"]
    effects = authorization["real_execution_bootstrap_closure_v1_effect_budget"]
    ordering = authorization["real_execution_bootstrap_closure_v1_ordering"]
    live = authorization["real_execution_bootstrap_closure_v1_live_boundary"]
    assert f"REQUIRE_EXACT_BASE_{START_MAIN.upper()}" in delivery
    assert "MERGE_COMMIT_ONLY" in delivery
    assert "POST_MERGE_PROVIDER_DNS_RESOLUTION_EXACTLY_1" in effects
    assert "PROVIDER_HTTP_CALLS_0" in effects
    assert "REAL_PROVIDER_SECRET_READS_0" in effects
    assert "ENGINEERING_AND_EXACT_HEAD_CI_AND_THREE_REVIEWS_AND_MERGE_FIRST" in ordering
    assert "STOP_BEFORE_ENVIRONMENT_SECRET_READER_OR_PROVIDER_TRANSPORT" in ordering
    assert "NO_REAL_LIVE_CAPTURE_AUTHORIZED" in live
    mission = matrix["missions"][MISSION_ID]
    assert mission["agents"] == ["C0", "C2", "C4", "DP6"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E1"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
    }
    paths = mission["allowed_paths"]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))


def test_agent_schema_and_three_independent_final_reviews_accept() -> None:
    schema = load("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
    validator = Draft202012Validator(schema)
    paths = (
        "reports/council/real-execution-bootstrap-dp6-review-v3.json",
        "reports/council/real-execution-bootstrap-c4-review-v3.json",
        "reports/council/real-execution-bootstrap-c2-review-v3.json",
    )
    agents: list[str] = []
    for path in paths:
        report = load(path)
        validator.validate(report)
        assert report["mission_id"] == MISSION_ID
        agents.append(str(report["agent_id"]))
    assert agents == ["DP6", "C4", "C2"]
    aggregate = load("reports/council/real-execution-bootstrap-final-review-v3.json")
    assert aggregate["mission_id"] == MISSION_ID
    assert [review["agent_id"] for review in aggregate["reviewers"]] == agents
    assert all(review["verdict"] == "ACCEPT" for review in aggregate["reviewers"])
    assert aggregate["aggregate_gate"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
        "independent_review_count": 3,
        "required_axes_covered": True,
    }
    assert aggregate["verdict"] == "ACCEPT_ENGINEERING_FOR_DRAFT_DELIVERY"
    assert aggregate["real_effects"] == {
        "engineering_provider_dns_resolutions": 0,
        "provider_tcp_connections": 0,
        "provider_http_calls": 0,
        "real_secret_reads": 0,
        "real_capture_calls": 0,
        "real_batch": "NOT_EXECUTED",
        "real_snapshot": "NOT_CREATED",
    }


def test_committed_report_has_zero_real_effects_and_no_local_runtime_paths() -> None:
    report = load("reports/data-sourcing/real-execution-bootstrap-closure-v1.json")
    assert report["starting_main_sha"] == START_MAIN
    for field in (
        "engineering_provider_dns_resolutions",
        "provider_tcp_connections",
        "provider_http_calls",
        "real_secret_reads",
        "real_market_capture_calls",
        "purchases",
        "promotions",
        "bets",
    ):
        assert report[field] == 0
    assert report["real_batch_status"] == "NOT_EXECUTED"
    assert report["real_snapshot_status"] == "NOT_CREATED"
    serialized = json.dumps(report, sort_keys=True)
    assert "C:\\Users\\" not in serialized
    assert "/home/" not in serialized


def test_dns_preparation_tool_has_no_secret_or_transport_capability() -> None:
    paths = (
        "src/robin/capture/provider_network.py",
        "tools/data-sourcing/prepare_provider_network_binding_v1.py",
    )
    source = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)
    assert "EnvironmentSecretReader" not in source
    assert "THE_ODDS_API_KEY" not in source
    assert "socket.connect" not in source
    assert "HTTPSConnection" not in source
    assert "requests." not in source


def test_first_c0_single_league_canary_authority_is_additive_and_fail_closed() -> None:
    bootstrap = (ROOT / "src/robin/capture/bootstrap_contracts.py").read_text(encoding="utf-8")
    provider = (ROOT / "src/robin/capture/provider_network.py").read_text(encoding="utf-8")
    owner_pack = (ROOT / "src/robin/capture/owner_review_pack.py").read_text(encoding="utf-8")
    canary_cli = (ROOT / "tools/data-sourcing/prepare_first_c0_canary_selection_v1.py").read_text(
        encoding="utf-8"
    )
    dns_cli = (ROOT / "tools/data-sourcing/prepare_provider_network_binding_v1.py").read_text(
        encoding="utf-8"
    )
    pack_cli = (ROOT / "tools/data-sourcing/build_owner_review_pack_v1.py").read_text(
        encoding="utf-8"
    )

    assert "class FirstC0CanarySelectionV1(FrozenContract):" in bootstrap
    assert '"robin-first-c0-canary-selection-v1"' in bootstrap
    assert '"single-league-first-real-c0-canary-v1"' in bootstrap
    assert 'Literal["FIRST_REAL_CAPTURE_CANARY_ONLY"]' in bootstrap
    assert (
        "CampaignSelectionAuthorityV1: TypeAlias = "
        "CampaignWindowSelectionV1 | FirstC0CanarySelectionV1"
    ) in bootstrap
    assert "def load_campaign_selection_authority_v1(payload: object)" in bootstrap
    assert 'Field(discriminator="schema_version")' in bootstrap
    assert "CAMPAIGN_SELECTION_AUTHORITY_SCHEMA_UNSUPPORTED" in bootstrap
    assert "CAMPAIGN_SELECTION_AUTHORITY_PAYLOAD_INVALID" in bootstrap
    assert "CAMPAIGN_SELECTION_REVISION: Final[" in bootstrap
    assert '"complete-five-league-interval-clique-ranking-v2"' in bootstrap
    assert (
        "CAMPAIGN_RANKING_POLICY: Final[" in bootstrap
        and "cross-league-desc;earliest-readiness-asc;stable-group-hash-asc" in bootstrap
    )
    assert LIVE_ALLOWED_SPORT_KEYS == (
        "soccer_spain_la_liga",
        "soccer_france_ligue_one",
        "soccer_epl",
        "soccer_italy_serie_a",
        "soccer_germany_bundesliga",
    )

    assert canary_cli.count("parser.add_argument(") == 4
    for argument in (
        "--workspace-receipt",
        "--mission-manifest",
        "--source-plan",
        "--output-directory",
    ):
        assert f'parser.add_argument("{argument}"' in canary_cli
    for forbidden_argument in (
        "--skip-five-league",
        "--unsafe-canary",
        "--force",
        "--test-mode",
    ):
        assert forbidden_argument not in canary_cli
        assert forbidden_argument not in dns_cli
        assert forbidden_argument not in pack_cli

    assert 'host != "apim.laliga.com"' in canary_cli
    assert 'parsed.path != "/public-service/api/v1/matches"' in canary_cli
    assert 'query.get("competition") != ["primera-division"]' in canary_cli
    assert 'query.get("limit") != ["100"]' in canary_cli
    assert 'query.get("offset") != ["300"]' in canary_cli
    assert 'host != "datencenter.dfb.de"' in canary_cli
    assert 'parsed.path != "/competitions/12/seasons/current"' in canary_cli
    assert canary_cli.index("workspace_validator(workspace_receipt)") < canary_cli.index(
        "marker_inspection = marker_inspector"
    )
    assert canary_cli.index("marker_inspection = marker_inspector") < canary_cli.index(
        "fetch_result = fetch_official_schedule_source("
    )
    assert canary_cli.index(
        "mission_manifest = load_tracked_real_execution_mission_manifest_v1("
    ) < canary_cli.index("result = prepare_first_c0_canary_selection_v1(")
    assert '_PRIMARY_SPORT_KEY = "soccer_spain_la_liga"' in canary_cli
    assert '_FALLBACK_SPORT_KEY = "soccer_germany_bundesliga"' in canary_cli
    assert (
        '_CYCLE_RESERVATION_NAME = "first-c0-canary-cycle-{cycle:02d}-read-reservation-v1.json"'
        in canary_cli
    )
    assert (
        '_CYCLE_RECEIPT_NAME = "first-c0-canary-cycle-{cycle:02d}-attempt-receipt-v1.json"'
        in canary_cli
    )
    assert "_MAXIMUM_PREPARATION_CYCLES = 3" in canary_cli
    assert "_MAXIMUM_OFFICIAL_PHYSICAL_READS = 12" in canary_cli
    assert (
        'receipt.get("status") not in {"SUCCEEDED", "FAILED_BEFORE_DNS", "FAILED_NO_FALLBACK"}'
        in (canary_cli)
    )
    assert 'previous.get("status") == "SUCCEEDED"' in canary_cli
    assert "plan.source.sport_key != _FALLBACK_SPORT_KEY" in canary_cli
    assert "cumulative_official_reads > _MAXIMUM_OFFICIAL_PHYSICAL_READS" in canary_cli
    assert "anticipated_reads > 2" in canary_cli
    assert "EnvironmentSecretReader" not in canary_cli
    assert "THE_ODDS_API_KEY" not in canary_cli
    assert "socket.connect" not in canary_cli
    assert "api.the-odds-api.com" not in canary_cli

    for source in (dns_cli, pack_cli):
        assert "load_campaign_selection_authority_v1" in source
        assert "CampaignWindowSelectionV1.model_validate" not in source
    assert '_RESOLUTION_CLAIM_NAME = "provider-network-resolution-one-shot-v1.json"' in (provider)
    assert '_MISSION_GLOBAL_CLAIM_ROOT_NAME = "RobinRealExecutionMissionClaimsV1"' in (provider)
    assert "_FIRST_C0_CANARY_MINIMUM_PRE_DNS_MARGIN = timedelta(seconds=840)" in provider
    assert "write_owner_review_pack_v1(arguments.output_directory, pack)" in pack_cli
    assert "assert_owner_review_pack_completion_current_v1(pack" in pack_cli
    assert "SELECTION_SCHEMA={selection.schema_version}" in owner_pack
    assert "SELECTION_PURPOSE={selection.purpose}" in owner_pack
    assert "SOURCE_TARGET_SET_COUNT={selection.source_target_set_count}" in owner_pack
    assert "SCIENTIFIC_EDGE_CLAIM={str(selection.scientific_edge_claim).lower()}" in owner_pack

    matrix_payload = (
        (ROOT / "configs/agents/mission-activation-matrix-v3.json")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    assert hashlib.sha256(matrix_payload).hexdigest() == (
        "6777e609247356a9e93fb089a928d25f28c5ba7f9d3fb39a199130d6e866f5ef"
    )
