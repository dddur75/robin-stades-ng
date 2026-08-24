from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from robin.capture import RealExecutionMissionManifestV1

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1"
START_MAIN = "0591f01c580eb853890e9c1c304a78c21ba9de63"
SOURCE_HASH = "2451cd643c2d3ffcd3c5cc9fcd4a5f81f785978e0aa20429b4d182ceb9b1f22b"
OLD_SOURCE_HASH = "0783d995e95c0a8a969f76ff3f468c3b96a697155a7ad01e0676963c6bab9f43"
EXPECTED_CANONICAL_MANIFEST_SHA256 = (
    "5f8d1db2586adbc397d1b4e814e85946c84327537872df6aeded0fbbbc5498c0"
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
    assert validated.expires_at.isoformat().replace("+00:00", "Z") == ("2026-08-26T10:00:00Z")
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
