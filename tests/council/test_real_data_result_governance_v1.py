from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_REAL_DATA_RESULT_20261003"
SOURCE_SHA256 = "f01be9dddc7d7a098caec9fc3bf623ab2b53803ce03b6202f5b3fcdcad0ad25b"
BASE_MAIN_SHA = "150c14f76c5f51f0efa6211f4742ea2291a9234c"
AUTHORIZATION_DECISION_ID = "RCV3-20261003-208"
SOCKET_FAILURE_DECISION_ID = "RCV3-20261003-209"
AUTHORIZATION_CLAIM_ID = "GOV.AUTHORIZATION.ROBIN_REAL_DATA_RESULT.V1.001"
SOCKET_FAILURE_CLAIM_ID = (
    "RUNTIME.TRANSPORT.DEADLINE_SOCKET.CONNECTION_CLOSE.LIFETIME.FAILURE.V1.001"
)
SOCKET_REGRESSION_CLAIM_ID = (
    "RUNTIME.TRANSPORT.DEADLINE_SOCKET.CONNECTION_CLOSE.LIFETIME.REGRESSION.V1.001"
)
DIAGNOSTIC_CLAIM_ID = "SECURITY.TRANSPORT.REDACTED.DIAGNOSTIC.V1.001"
PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REAL_DATA_RESULT.PROJECTION.V1.001"
FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REAL_DATA_RESULT.FINAL.V1.001"
FINAL_DECISION_ID = "RCV3-20261003-210"
HISTORICAL_ASSERTION_FAILURE_CLAIM_ID = (
    "GOV.CI.ROBIN_REAL_DATA_RESULT.HISTORICAL_ASSERTIONS.FAILURE.V1.001"
)
HISTORICAL_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REAL_DATA_RESULT.PROJECTION.V1.002"
HISTORICAL_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REAL_DATA_RESULT.FINAL.V1.002"
REPRESENTATION_FAILURE_CLAIM_ID = (
    "GOV.CI.ROBIN_REAL_DATA_RESULT.REPOSITORY_TEXT.REPRESENTATION.FAILURE.V1.001"
)
PREFLIGHT_FAILURE_CLAIM_ID = (
    "RUNTIME.ROBIN.REAL.RESULT.PREFLIGHT.RESERVATION.ORDERING.FAILURE.V1.001"
)
PREFLIGHT_REGRESSION_CLAIM_ID = "RUNTIME.ROBIN.REAL.RESULT.PREFLIGHT.RESERVATION.RECOVERY.V1.001"
TRANSPORT_CLOSE_FAILURE_CLAIM_ID = "RUNTIME.TRANSPORT.DEADLINE_SOCKET.FINAL_CLOSE.FAILURE.V1.001"
TRANSPORT_CLOSE_REGRESSION_CLAIM_ID = (
    "RUNTIME.TRANSPORT.DEADLINE_SOCKET.FINAL_CLOSE.REGRESSION.V1.001"
)
ACTIVE_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REAL_DATA_RESULT.PROJECTION.V1.003"
ACTIVE_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REAL_DATA_RESULT.FINAL.V1.003"
PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID = (
    "GOV.CI.ROBIN_REAL_DATA_RESULT.PROVIDER_NETWORK_BINDING.RESPONSE_CLOSE.COMPATIBILITY.V1.001"
)
LATEST_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REAL_DATA_RESULT.PROJECTION.V1.004"
LATEST_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REAL_DATA_RESULT.FINAL.V1.004"
WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID = (
    "GOV.CI.ROBIN_REAL_DATA_RESULT.WORKFLOW.MANIFEST.HASH.LF.COMPATIBILITY.V1.001"
)
SUCCESSOR_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REAL_DATA_RESULT.PROJECTION.V1.005"
SUCCESSOR_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REAL_DATA_RESULT.FINAL.V1.005"
HISTORICAL_ASSERTION_FAILURE_DECISION_ID = "RCV3-20261003-211"
HISTORICAL_FINAL_DECISION_ID = "RCV3-20261003-212"
REPRESENTATION_FAILURE_DECISION_ID = "RCV3-20261003-213"
PREFLIGHT_FAILURE_DECISION_ID = "RCV3-20261003-214"
TRANSPORT_CLOSE_FAILURE_DECISION_ID = "RCV3-20261003-215"
ACTIVE_FINAL_DECISION_ID = "RCV3-20261003-216"
PROVIDER_RESPONSE_CLOSE_FAILURE_DECISION_ID = "RCV3-20261003-217"
LATEST_FINAL_DECISION_ID = "RCV3-20261003-218"
WORKFLOW_HASH_FAILURE_DECISION_ID = "RCV3-20261003-219"
SUCCESSOR_FINAL_DECISION_ID = "RCV3-20261003-220"
DATA_CLAIM_IDS = {
    "DATA.ROBIN.REAL.RESULT.CAPTURES.V1.001",
    "DATA.ROBIN.REAL.RESULT.VIEW.V1.001",
    "GOV.ROBIN.REAL.RESULT.CONSUMPTION.V1.001",
}
EXPECTED_PROJECTION_PATHS = {
    ".github/workflows/91-robin-real-data-result.yml",
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/execution/robin-real-data-result-20261003.json",
    "docs/data-sourcing/ROBIN-REAL-DATA-RESULT-2026-10-03.md",
    "docs/superpowers/plans/2026-10-03-robin-real-data-result.md",
    "docs/superpowers/specs/2026-10-03-robin-real-data-result-design.md",
    "scripts/run_real_data_result.py",
    "src/robin/capture/live_transport.py",
    "src/robin/capture/real_data_result.py",
    "tests/capture/test_live_canary_transport.py",
    "tests/capture/test_real_data_result.py",
    "tests/capture/test_real_data_result_workflow.py",
    "tests/capture/test_reprise_collecte_workflow.py",
    "tests/capture/test_run_real_data_result_cli.py",
    "tests/council/test_real_data_result_governance_v1.py",
    "tests/council/test_robin_council_os_v3.py",
}
EXPECTED_HISTORICAL_PROJECTION_PATHS = EXPECTED_PROJECTION_PATHS | {
    "tests/council/test_real_execution_bootstrap_governance.py",
    "tests/council/test_reprise_collecte_governance_v1.py",
}
EXPECTED_ACTIVE_PROJECTION_PATHS = EXPECTED_HISTORICAL_PROJECTION_PATHS | {
    "scripts/export_phase_c_v2_source_bundle.py",
    "scripts/run_phase_c_v2_campaign.py",
    "tests/activation/test_chronos_controlled_go_durable_seal_v1.py",
    "tests/data-sourcing/test_convergence_contracts.py",
    "tests/hypothesis_intelligence/test_phase_c_factory_contract.py",
    "tests/hypothesis_intelligence/test_phase_c_v2_campaign_results.py",
    "tests/hypothesis_intelligence/test_phase_c_v2_freeze.py",
    "tests/hypothesis_intelligence/test_phase_c_v2_source_bundle.py",
}
EXPECTED_LATEST_PROJECTION_PATHS = EXPECTED_ACTIVE_PROJECTION_PATHS | {
    "tests/capture/test_provider_network_binding.py",
}
EXPECTED_SUCCESSOR_PROJECTION_PATHS = EXPECTED_LATEST_PROJECTION_PATHS
REVIEW_ARTIFACTS = {
    "data": "reports/council/robin-real-data-result-data-review-v1.json",
    "security": "reports/council/robin-real-data-result-security-review-v1.json",
    "governance": "reports/council/robin-real-data-result-governance-review-v1.json",
    "platform": "reports/council/robin-real-data-result-platform-review-v1.json",
    "final": "reports/council/robin-real-data-result-final-review-v1.json",
}
HISTORICAL_REVIEW_ARTIFACTS = {
    "data": "reports/council/robin-real-data-result-data-review-v1.json",
    "security": "reports/council/robin-real-data-result-security-review-v1.json",
    "governance": "reports/council/robin-real-data-result-governance-review-v2.json",
    "platform": "reports/council/robin-real-data-result-platform-review-v2.json",
    "final": "reports/council/robin-real-data-result-final-review-v2.json",
}
ACTIVE_REVIEW_ARTIFACTS = {
    "data": "reports/council/robin-real-data-result-data-review-v2.json",
    "security": "reports/council/robin-real-data-result-security-review-v2.json",
    "governance": "reports/council/robin-real-data-result-governance-review-v3.json",
    "platform": "reports/council/robin-real-data-result-platform-review-v3.json",
    "final": "reports/council/robin-real-data-result-final-review-v3.json",
}
LATEST_REVIEW_ARTIFACTS = {
    "data": "reports/council/robin-real-data-result-data-review-v2.json",
    "security": "reports/council/robin-real-data-result-security-review-v2.json",
    "governance": "reports/council/robin-real-data-result-governance-review-v4.json",
    "platform": "reports/council/robin-real-data-result-platform-review-v3.json",
    "final": "reports/council/robin-real-data-result-final-review-v4.json",
}
SUCCESSOR_REVIEW_ARTIFACTS = {
    "data": "reports/council/robin-real-data-result-data-review-v2.json",
    "security": "reports/council/robin-real-data-result-security-review-v2.json",
    "governance": "reports/council/robin-real-data-result-governance-review-v5.json",
    "platform": "reports/council/robin-real-data-result-platform-review-v3.json",
    "final": "reports/council/robin-real-data-result-final-review-v5.json",
}


def _load(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_result_mission_manifest_is_exact_and_current() -> None:
    manifest = _load("configs/execution/robin-real-data-result-20261003.json")
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
    assert manifest["authorized_stages"] == ["E1", "E2", "E3A", "E3B"]
    assert manifest["maximum_stage"] == "E3B"
    assert manifest["compute_budget"] == 16_000
    assert manifest["time_budget"] == 28_800
    assert manifest["source_hash"] == SOURCE_SHA256
    assert manifest["expires_at"] == "2026-10-06T12:03:57Z"
    assert manifest["external_effects"] == [
        "git_remote_write_non_force",
        "github_pull_request_write",
        "github_merge_commit",
        "github_actions_observe",
        "github_actions_workflow_dispatch_max_3_after_merge",
        "github_actions_artifact_upload_normalized_public_repository",
        "provider_public_dns_resolution_per_dispatch_max_1",
        "provider_secret_read_per_dispatch_max_1",
        "provider_https_get_successor_slot_max_15",
        "provider_credit_reservation_successor_max_30",
        "provider_http_cumulative_max_40_with_prior_baseline_1",
        "provider_credit_cumulative_max_60_with_prior_reserve_4",
        "r2_immutable_attempt_reservation_before_each_provider_request",
        "r2_immutable_raw_capture_and_exact_readback",
        "r2_immutable_cycle_receipt_and_final_report",
        "offline_replay_from_r2_readback",
        "normalized_csv_html_consultable_delivery",
    ]


def test_result_mission_is_materialized_without_rewriting_predecessors() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][MISSION_ID]
    assert mission["agents"] == ["C0", "C2", "C4", "DP6", "A2"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E3B"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
        "platform": ["A2"],
    }
    authorization = matrix["authorization"]
    assert (
        "EXACT_BASE_150C14F76C5F51F0EFA6211F4742EA2291A9234C"
        in (authorization["robin_real_data_result_20261003_delivery"])
    )
    delivery = authorization["robin_real_data_result_20261003_delivery"]
    assert "CURRENT_STAGE_E1" in delivery
    assert "SCALE_DECISION_PASS_AND_HOLD" in delivery
    assert "NO_E1_TO_E2_E3_TRANSITION" in delivery
    assert "FIVE_ENDPOINTS_NOT_SEASON_PROOF" in delivery
    assert "SCIENTIFIC_PROMOTION_AND_SOCIAL_PUBLICATION" in delivery
    assert (
        "PROVIDER_HTTP_REQUESTS_SUCCESSOR_MAX_15"
        in (authorization["robin_real_data_result_20261003_effect_budget"])
    )
    assert (
        "PROVIDER_HTTP_REQUESTS_CUMULATIVE_MAX_40_PRIOR_BASELINE_1"
        in (authorization["robin_real_data_result_20261003_effect_budget"])
    )
    assert (
        "PROVIDER_CREDITS_CUMULATIVE_MAX_60_PRIOR_RESERVE_4"
        in (authorization["robin_real_data_result_20261003_effect_budget"])
    )
    assert (
        "R2_PUT_REQUESTS_ANY_DISPATCH_MAX_34_FULL_REPLAY_DISPATCH_MAX_19_TOTAL_MAX_72"
        in (authorization["robin_real_data_result_20261003_effect_budget"])
    )
    assert (
        "R2_EXACT_READBACK_GETS_ANY_DISPATCH_MAX_34_TOTAL_MAX_102"
        in (authorization["robin_real_data_result_20261003_effect_budget"])
    )
    assert (
        "FIXED_SLOT_RESERVATION_BEFORE_EACH_PROVIDER_REQUEST"
        in (authorization["robin_real_data_result_20261003_ordering"])
    )
    assert (
        "FIVE_EXACT_SPORT_KEYS_REGION_EU_MARKETS_H2H_AND_TOTALS"
        in (authorization["robin_real_data_result_20261003_source_boundary"])
    )
    assert (
        "PLAINTEXT_CONSULTABLE_GITHUB_ACTIONS_ARTIFACT_ON_PUBLIC_REPOSITORY"
        in (authorization["robin_real_data_result_20261003_source_boundary"])
    )

    schema = _load("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]

    original_manifest = _load("configs/execution/reprise-collecte-20261002.json")
    assert original_manifest["source_hash"] == (
        "0a48756520b7f77f6c2d66d27e3b423d5f62d0468bd8b8607aa1cebf5f391d22"
    )
    assert original_manifest["expires_at"] == "2026-10-03T18:27:48Z"


def test_authority_and_socket_failure_are_append_only_and_evidenced() -> None:
    records = _records()
    by_id = {record["decision_id"]: record for record in records}
    authorization = by_id[AUTHORIZATION_DECISION_ID]
    failure = by_id[SOCKET_FAILURE_DECISION_ID]
    assert authorization["record_type"] == "MISSION_AUTHORIZED"
    assert authorization["context"]["base_main_sha"] == BASE_MAIN_SHA
    assert authorization["context"]["writer"] == "C0"
    assert authorization["proof"] == [AUTHORIZATION_CLAIM_ID]
    assert failure["record_type"] == "FAILURE"
    assert failure["previous_hash"] == authorization["hash"]
    assert failure["proof"] == [SOCKET_FAILURE_CLAIM_ID]
    assert failure["context"]["reproduction"] == {
        "http_status": 200,
        "connection_header": "close",
        "body_bytes": 20_000,
        "failure_after_bytes": 8_192,
        "exception_class": "OSError",
        "errno": 9,
    }
    assert failure["context"]["past_pilot_attribution"] == "HYPOTHESIS_ONLY"

    for record in (authorization, failure):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert claims[AUTHORIZATION_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[SOCKET_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[SOCKET_REGRESSION_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[DIAGNOSTIC_CLAIM_ID]["status"] == "VERIFIED"
    assert decisions[AUTHORIZATION_DECISION_ID]["ledger_record_hash"] == (authorization["hash"])
    assert decisions[SOCKET_FAILURE_DECISION_ID]["ledger_record_hash"] == failure["hash"]


def test_final_reviews_projection_and_precommit_decision_are_exact() -> None:
    required_report_fields = {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
    reports = {key: _load(path) for key, path in REVIEW_ARTIFACTS.items()}
    assert reports["data"]["agent_id"] == "DP6"
    assert reports["security"]["agent_id"] == "C4"
    assert reports["governance"]["agent_id"] == "C2"
    assert reports["platform"]["agent_id"] == "A2"
    assert reports["final"]["agent_id"] == "C0"
    assert all(set(report) == required_report_fields for report in reports.values())
    assert all(report["mission_id"] == MISSION_ID for report in reports.values())

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    projection = claims[PROJECTION_CLAIM_ID]
    assert projection["status"] == "SUPERSEDED"
    assert projection["superseded_by"] == HISTORICAL_PROJECTION_CLAIM_ID
    assert set(projection["artifact_hashes"]) == EXPECTED_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert claims[FINAL_REVIEW_CLAIM_ID]["status"] == "SUPERSEDED"
    assert claims[FINAL_REVIEW_CLAIM_ID]["superseded_by"] == (HISTORICAL_FINAL_REVIEW_CLAIM_ID)
    assert all(claims[claim_id]["status"] == "PARTIAL" for claim_id in DATA_CLAIM_IDS)

    records = _records()
    index = next(
        i for i, record in enumerate(records) if record["decision_id"] == FINAL_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "DECISION"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["context"]["writer"] == "C0"
    assert record["context"]["writer_count"] == 1
    assert record["context"]["current_stage"] == "E1"
    assert record["context"]["maximum_authority_stage"] == "E3B"
    assert (
        record["context"]["reviewed_projection"]["sha256"]
        == projection["engineering_projection_sha256"]
    )
    assert (
        record["context"]["reviewed_projection"]["path_count"] == projection["artifact_path_count"]
    )
    assert record["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, path in REVIEW_ARTIFACTS.items()
    }
    assert set(record["proof"]) == {
        AUTHORIZATION_CLAIM_ID,
        SOCKET_FAILURE_CLAIM_ID,
        SOCKET_REGRESSION_CLAIM_ID,
        DIAGNOSTIC_CLAIM_ID,
        PROJECTION_CLAIM_ID,
        FINAL_REVIEW_CLAIM_ID,
        *DATA_CLAIM_IDS,
    }
    canonical_record = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(canonical_record).hexdigest() == record["hash"]


def test_historical_assertion_correction_has_exact_active_projection_and_review() -> None:
    required_report_fields = {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
    reports = {key: _load(path) for key, path in HISTORICAL_REVIEW_ARTIFACTS.items()}
    assert all(set(report) == required_report_fields for report in reports.values())
    assert all(report["mission_id"] == MISSION_ID for report in reports.values())
    assert reports["data"]["agent_id"] == "DP6"
    assert reports["security"]["agent_id"] == "C4"
    assert reports["governance"]["agent_id"] == "C2"
    assert reports["platform"]["agent_id"] == "A2"
    assert reports["final"]["agent_id"] == "C0"

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    predecessor = claims[PROJECTION_CLAIM_ID]
    projection = claims[HISTORICAL_PROJECTION_CLAIM_ID]
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == HISTORICAL_PROJECTION_CLAIM_ID
    assert projection["status"] == "SUPERSEDED"
    assert projection["superseded_by"] == ACTIVE_PROJECTION_CLAIM_ID
    assert projection["successor_of"] == PROJECTION_CLAIM_ID
    assert PROJECTION_CLAIM_ID in projection["supersedes"]
    assert set(projection["artifact_hashes"]) == EXPECTED_HISTORICAL_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert claims[HISTORICAL_ASSERTION_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    historical_review = claims[HISTORICAL_FINAL_REVIEW_CLAIM_ID]
    assert historical_review["status"] == "SUPERSEDED"
    assert historical_review["superseded_by"] == ACTIVE_FINAL_REVIEW_CLAIM_ID
    assert historical_review["successor_of"] == FINAL_REVIEW_CLAIM_ID

    records = _records()
    failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == HISTORICAL_ASSERTION_FAILURE_DECISION_ID
    )
    decision_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == HISTORICAL_FINAL_DECISION_ID
    )
    failure = records[failure_index]
    decision = records[decision_index]
    assert decision_index == failure_index + 1
    assert failure["record_type"] == "FAILURE"
    assert failure["previous_hash"] == records[failure_index - 1]["hash"]
    assert failure["proof"] == [HISTORICAL_ASSERTION_FAILURE_CLAIM_ID]
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["previous_hash"] == failure["hash"]
    assert decision["context"]["writer"] == "C0"
    assert decision["context"]["writer_count"] == 1
    assert decision["context"]["reviewed_projection"] == {
        "sha256": projection["engineering_projection_sha256"],
        "path_count": projection["artifact_path_count"],
        "normalization": "LF_NORMALIZED_TEXT_BYTES",
        "byte_frozen": True,
    }
    assert decision["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, path in HISTORICAL_REVIEW_ARTIFACTS.items()
    }
    assert set(decision["proof"]) == {
        HISTORICAL_ASSERTION_FAILURE_CLAIM_ID,
        HISTORICAL_PROJECTION_CLAIM_ID,
        HISTORICAL_FINAL_REVIEW_CLAIM_ID,
    }
    for candidate in (failure, decision):
        canonical_record = json.dumps(
            {key: value for key, value in candidate.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical_record).hexdigest() == candidate["hash"]


def test_provider_response_close_compatibility_has_exact_active_successor() -> None:
    required_report_fields = {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
    reports = {key: _load(path) for key, path in LATEST_REVIEW_ARTIFACTS.items()}
    assert all(set(report) == required_report_fields for report in reports.values())
    assert all(report["mission_id"] == MISSION_ID for report in reports.values())
    assert reports["data"]["agent_id"] == "DP6"
    assert reports["security"]["agent_id"] == "C4"
    assert reports["governance"]["agent_id"] == "C2"
    assert reports["platform"]["agent_id"] == "A2"
    assert reports["final"]["agent_id"] == "C0"

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    predecessor = claims[ACTIVE_PROJECTION_CLAIM_ID]
    projection = claims[LATEST_PROJECTION_CLAIM_ID]
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == LATEST_PROJECTION_CLAIM_ID
    assert projection["status"] == "SUPERSEDED"
    assert projection["superseded_by"] == SUCCESSOR_PROJECTION_CLAIM_ID
    assert projection["successor_of"] == ACTIVE_PROJECTION_CLAIM_ID
    assert ACTIVE_PROJECTION_CLAIM_ID in projection["supersedes"]
    assert set(projection["artifact_hashes"]) == EXPECTED_LATEST_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
    compatibility = claims[PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID]
    assert compatibility["status"] == "VERIFIED"
    predecessor_review = claims[ACTIVE_FINAL_REVIEW_CLAIM_ID]
    review = claims[LATEST_FINAL_REVIEW_CLAIM_ID]
    assert predecessor_review["status"] == "SUPERSEDED"
    assert predecessor_review["superseded_by"] == LATEST_FINAL_REVIEW_CLAIM_ID
    assert review["status"] == "SUPERSEDED"
    assert review["superseded_by"] == SUCCESSOR_FINAL_REVIEW_CLAIM_ID
    assert review["successor_of"] == ACTIVE_FINAL_REVIEW_CLAIM_ID
    assert review["engineering_projection_sha256"] == projection["engineering_projection_sha256"]

    records = _records()
    failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == PROVIDER_RESPONSE_CLOSE_FAILURE_DECISION_ID
    )
    decision_index = next(
        i for i, record in enumerate(records) if record["decision_id"] == LATEST_FINAL_DECISION_ID
    )
    failure = records[failure_index]
    decision = records[decision_index]
    assert (
        failure_index
        == next(
            i
            for i, record in enumerate(records)
            if record["decision_id"] == ACTIVE_FINAL_DECISION_ID
        )
        + 1
    )
    assert decision_index == failure_index + 1
    assert failure["record_type"] == "FAILURE"
    assert failure["previous_hash"] == records[failure_index - 1]["hash"]
    assert failure["proof"] == [PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID]
    assert failure["context"]["same_environment"] is True
    assert failure["context"]["reproduction"] == {
        "full_suite_before": "1_FAILED_3607_PASSED_33_SKIPPED",
        "clean_main_exact_node": "1_PASSED",
        "candidate_before_exact_node": ("1_FAILED_LIVE_TRANSPORT_CONNECTION_CLOSE_FAILED"),
        "candidate_after_exact_node": "1_PASSED",
        "combined_after": "130_PASSED",
        "unapproved_network_attempts": 0,
    }
    assert failure["context"]["correction_boundary"] == {
        "test_only": True,
        "runtime_changed": False,
        "assertions_removed": 0,
        "connection_binding_contract_preserved": True,
        "cleanup_fail_closed_preserved": True,
        "external_effects": 0,
    }
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["previous_hash"] == failure["hash"]
    assert decision["context"]["writer"] == "C0"
    assert decision["context"]["writer_count"] == 1
    assert decision["context"]["reviewed_projection"] == {
        "sha256": projection["engineering_projection_sha256"],
        "path_count": projection["artifact_path_count"],
        "normalization": "LF_NORMALIZED_TEXT_BYTES",
        "byte_frozen": True,
    }
    assert decision["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, path in LATEST_REVIEW_ARTIFACTS.items()
    }
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    allowed_paths = matrix["missions"][MISSION_ID]["allowed_paths"]
    v1005_reports = {
        "reports/council/robin-real-data-result-final-review-v5.json",
        "reports/council/robin-real-data-result-governance-review-v5.json",
    }
    assert len(decision["context"]["files"]) == 45
    assert set(decision["context"]["files"]) == set(allowed_paths) - v1005_reports
    assert set(decision["proof"]) == {
        PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID,
        LATEST_PROJECTION_CLAIM_ID,
        LATEST_FINAL_REVIEW_CLAIM_ID,
    }
    expected_edges = [
        {
            "edge_id": "EDGE.837",
            "from_claim_id": PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID,
            "to_decision_id": PROVIDER_RESPONSE_CLOSE_FAILURE_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.838",
            "from_claim_id": PROVIDER_RESPONSE_CLOSE_COMPATIBILITY_CLAIM_ID,
            "to_decision_id": LATEST_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.839",
            "from_claim_id": LATEST_PROJECTION_CLAIM_ID,
            "to_decision_id": LATEST_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.840",
            "from_claim_id": LATEST_FINAL_REVIEW_CLAIM_ID,
            "to_decision_id": LATEST_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
    ]
    edge_start = next(i for i, edge in enumerate(graph["edges"]) if edge["edge_id"] == "EDGE.837")
    assert graph["edges"][edge_start : edge_start + len(expected_edges)] == expected_edges
    for candidate in (failure, decision):
        canonical_record = json.dumps(
            {key: value for key, value in candidate.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical_record).hexdigest() == candidate["hash"]


def test_workflow_hash_compatibility_has_exact_active_successor() -> None:
    required_report_fields = {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
    reports = {key: _load(path) for key, path in SUCCESSOR_REVIEW_ARTIFACTS.items()}
    assert all(set(report) == required_report_fields for report in reports.values())
    assert all(report["mission_id"] == MISSION_ID for report in reports.values())
    assert {key: report["agent_id"] for key, report in reports.items()} == {
        "data": "DP6",
        "security": "C4",
        "governance": "C2",
        "platform": "A2",
        "final": "C0",
    }

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    predecessor = claims[LATEST_PROJECTION_CLAIM_ID]
    projection = claims[SUCCESSOR_PROJECTION_CLAIM_ID]
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == SUCCESSOR_PROJECTION_CLAIM_ID
    assert projection["status"] == "VERIFIED"
    assert projection["successor_of"] == LATEST_PROJECTION_CLAIM_ID
    assert LATEST_PROJECTION_CLAIM_ID in projection["supersedes"]
    assert set(projection["artifact_hashes"]) == EXPECTED_SUCCESSOR_PROJECTION_PATHS
    recalculated = {
        path: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(EXPECTED_SUCCESSOR_PROJECTION_PATHS)
    }
    assert projection["artifact_hashes"] == recalculated
    canonical = json.dumps(recalculated, sort_keys=True, separators=(",", ":")).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
    compatibility = claims[WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID]
    assert compatibility["status"] == "VERIFIED"
    assert compatibility["windows_capture_result"] == "1_FAILED_790_PASSED"
    assert compatibility["targeted_after_result"] == "1_PASSED"
    assert compatibility["runtime_changed"] is False
    assert compatibility["workflow_changed"] is False
    assert compatibility["assertions_removed"] == 0
    predecessor_review = claims[LATEST_FINAL_REVIEW_CLAIM_ID]
    review = claims[SUCCESSOR_FINAL_REVIEW_CLAIM_ID]
    assert predecessor_review["status"] == "SUPERSEDED"
    assert predecessor_review["superseded_by"] == SUCCESSOR_FINAL_REVIEW_CLAIM_ID
    assert review["status"] == "VERIFIED"
    assert review["successor_of"] == LATEST_FINAL_REVIEW_CLAIM_ID
    assert review["engineering_projection_sha256"] == projection["engineering_projection_sha256"]

    records = _records()
    failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == WORKFLOW_HASH_FAILURE_DECISION_ID
    )
    decision_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == SUCCESSOR_FINAL_DECISION_ID
    )
    failure = records[failure_index]
    decision = records[decision_index]
    latest_index = next(
        i for i, record in enumerate(records) if record["decision_id"] == LATEST_FINAL_DECISION_ID
    )
    assert failure_index == latest_index + 1
    assert decision_index == failure_index + 1
    assert failure["record_type"] == "FAILURE"
    assert failure["previous_hash"] == records[failure_index - 1]["hash"]
    assert failure["proof"] == [WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID]
    assert failure["context"]["reproduction"] == {
        "pr83_windows_capture": "1_FAILED_790_PASSED",
        "exact_node": (
            "tests/capture/test_real_data_result_workflow.py::"
            "test_successor_workflow_pins_actions_dependencies_manifest_and_source"
        ),
        "manifest_raw_crlf_sha256": (
            "e6ed3910873fcf6c2e6d6f708c44134cd587ac8975090bc4c17b4723c1fbd992"
        ),
        "manifest_canonical_lf_sha256": (
            "4d91084d8446d794083b3729c34ac32e438c72c28b9db180979c4c5f2af74aa2"
        ),
        "source_forced_crlf_sha256": (
            "4ed36fb362a06318c08559f31dfb188cc7959e7ae416ef77bb18e1661b6e46d3"
        ),
        "source_canonical_lf_sha256": (
            "f01be9dddc7d7a098caec9fc3bf623ab2b53803ce03b6202f5b3fcdcad0ad25b"
        ),
        "targeted_after": "1_PASSED",
        "unapproved_network_attempts": 0,
    }
    assert failure["context"]["correction_boundary"] == {
        "test_only": True,
        "runtime_changed": False,
        "workflow_changed": False,
        "expected_hash_changed": False,
        "assertions_removed": 0,
        "lf_normalized_text_bytes": True,
        "external_effects": 0,
    }
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["previous_hash"] == failure["hash"]
    assert decision["context"]["writer"] == "C0"
    assert decision["context"]["writer_count"] == 1
    assert decision["context"]["pr"] == "83"
    assert decision["context"]["reviewed_projection"] == {
        "sha256": projection["engineering_projection_sha256"],
        "path_count": projection["artifact_path_count"],
        "normalization": "LF_NORMALIZED_TEXT_BYTES",
        "byte_frozen": True,
    }
    assert decision["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, path in SUCCESSOR_REVIEW_ARTIFACTS.items()
    }
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    allowed_paths = matrix["missions"][MISSION_ID]["allowed_paths"]
    assert len(allowed_paths) == 47
    assert set(decision["context"]["files"]) == set(allowed_paths)
    assert set(decision["proof"]) == {
        WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID,
        SUCCESSOR_PROJECTION_CLAIM_ID,
        SUCCESSOR_FINAL_REVIEW_CLAIM_ID,
    }
    expected_edges = [
        {
            "edge_id": "EDGE.841",
            "from_claim_id": WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID,
            "to_decision_id": WORKFLOW_HASH_FAILURE_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.842",
            "from_claim_id": WORKFLOW_HASH_COMPATIBILITY_CLAIM_ID,
            "to_decision_id": SUCCESSOR_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.843",
            "from_claim_id": SUCCESSOR_PROJECTION_CLAIM_ID,
            "to_decision_id": SUCCESSOR_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.844",
            "from_claim_id": SUCCESSOR_FINAL_REVIEW_CLAIM_ID,
            "to_decision_id": SUCCESSOR_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
    ]
    assert graph["edges"][-len(expected_edges) :] == expected_edges
    for candidate in (failure, decision):
        canonical_record = json.dumps(
            {key: value for key, value in candidate.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical_record).hexdigest() == candidate["hash"]


def test_repository_text_successor_has_exact_active_projection_and_review() -> None:
    required_report_fields = {
        "agent_id",
        "mission_id",
        "facts_verified",
        "unknowns",
        "assumptions",
        "main_objection",
        "risks",
        "minimum_decisive_test",
        "recommended_action",
        "scale_condition",
        "estimated_compute",
        "estimated_external_cost",
        "estimated_human_time",
        "maintenance_impact",
        "confidence",
    }
    reports = {key: _load(path) for key, path in ACTIVE_REVIEW_ARTIFACTS.items()}
    assert all(set(report) == required_report_fields for report in reports.values())
    assert all(report["mission_id"] == MISSION_ID for report in reports.values())
    assert reports["data"]["agent_id"] == "DP6"
    assert reports["security"]["agent_id"] == "C4"
    assert reports["governance"]["agent_id"] == "C2"
    assert reports["platform"]["agent_id"] == "A2"
    assert reports["final"]["agent_id"] == "C0"

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    predecessor = claims[HISTORICAL_PROJECTION_CLAIM_ID]
    projection = claims[ACTIVE_PROJECTION_CLAIM_ID]
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == ACTIVE_PROJECTION_CLAIM_ID
    assert projection["status"] == "SUPERSEDED"
    assert projection["superseded_by"] == LATEST_PROJECTION_CLAIM_ID
    assert projection["successor_of"] == HISTORICAL_PROJECTION_CLAIM_ID
    assert HISTORICAL_PROJECTION_CLAIM_ID in projection["supersedes"]
    assert set(projection["artifact_hashes"]) == EXPECTED_ACTIVE_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert claims[REPRESENTATION_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[PREFLIGHT_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[PREFLIGHT_REGRESSION_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[TRANSPORT_CLOSE_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[TRANSPORT_CLOSE_REGRESSION_CLAIM_ID]["status"] == "VERIFIED"
    review = claims[ACTIVE_FINAL_REVIEW_CLAIM_ID]
    assert review["status"] == "SUPERSEDED"
    assert review["superseded_by"] == LATEST_FINAL_REVIEW_CLAIM_ID
    assert review["successor_of"] == HISTORICAL_FINAL_REVIEW_CLAIM_ID
    assert review["engineering_projection_sha256"] == projection["engineering_projection_sha256"]

    records = _records()
    representation_failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == REPRESENTATION_FAILURE_DECISION_ID
    )
    preflight_failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == PREFLIGHT_FAILURE_DECISION_ID
    )
    transport_close_failure_index = next(
        i
        for i, record in enumerate(records)
        if record["decision_id"] == TRANSPORT_CLOSE_FAILURE_DECISION_ID
    )
    decision_index = next(
        i for i, record in enumerate(records) if record["decision_id"] == ACTIVE_FINAL_DECISION_ID
    )
    representation_failure = records[representation_failure_index]
    preflight_failure = records[preflight_failure_index]
    transport_close_failure = records[transport_close_failure_index]
    decision = records[decision_index]
    assert preflight_failure_index == representation_failure_index + 1
    assert transport_close_failure_index == preflight_failure_index + 1
    assert decision_index == transport_close_failure_index + 1
    assert representation_failure["record_type"] == "FAILURE"
    assert (
        representation_failure["previous_hash"] == records[representation_failure_index - 1]["hash"]
    )
    assert representation_failure["proof"] == [REPRESENTATION_FAILURE_CLAIM_ID]
    assert representation_failure["context"]["same_environment"] is True
    assert representation_failure["context"]["reproduction"] == {
        "chronos_append_only_edge": {
            "clean_main": "1_PASSED",
            "candidate_before": "1_FAILED",
            "candidate_after": "1_PASSED",
        },
        "repository_text_representation": {
            "clean_main": "26_FAILED_10_PASSED",
            "candidate_before": "26_FAILED_10_PASSED",
            "candidate_after": "36_PASSED",
        },
    }
    assert representation_failure["context"]["correction_boundary"] == {
        "scientific_runtime_scripts_changed": True,
        "provider_live_runtime_changed": False,
        "tests_changed": True,
        "assertions_removed": 0,
        "gzip_binary_identity_weakened": False,
        "external_effects": 0,
    }
    assert preflight_failure["record_type"] == "FAILURE"
    assert preflight_failure["previous_hash"] == representation_failure["hash"]
    assert preflight_failure["proof"] == [PREFLIGHT_FAILURE_CLAIM_ID]
    assert preflight_failure["context"]["reproduction"] == {
        "local_preflight_ordering": {
            "before": "2_FAILED",
            "after": "2_PASSED",
        },
        "durable_slot_recovery": {
            "before": "PARTIAL_12_VALIDATED_CUMULATIVE_13_CREDITS_28",
            "after": "COMPLETE_15_VALIDATED_CUMULATIVE_16_CREDITS_34",
        },
        "durable_failure_history": {
            "before": "THIRD_IDENTICAL_HTTP_404_ATTEMPTED_ACROSS_DISPATCHES",
            "after": "0_NEW_REQUESTS_BRANCH_STOP",
        },
        "mixed_live_replay_quota_sequence": {
            "before": "PARTIAL_FAIL_CLOSED_FALSE_SEQUENCE_STOP",
            "after": "COMPLETE_3_LIVE_12_REPLAY_PASS",
        },
        "low_quota_durable_inventory": {
            "before": "VALIDATED_1_CUMULATIVE_2_CREDITS_6",
            "after": "VALIDATED_13_CUMULATIVE_14_CREDITS_30",
        },
        "later_slot_low_quota_inventory": {
            "before": "14_NEW_REQUESTS_AFTER_LOW_QUOTA_REPLAY",
            "after": "0_NEW_REQUESTS_QUOTA_INSUFFICIENT",
        },
        "invalid_payload_verified_quota": {
            "before": "14_NEW_REQUESTS_AFTER_HTTP_404_LOW_QUOTA_REPLAY",
            "after": "0_NEW_REQUESTS_QUOTA_INSUFFICIENT",
        },
        "complete_replay_provider_access": {
            "before": "DNS_AND_SECRET_REQUIRED",
            "after": "DNS_0_SECRET_0",
        },
        "unapproved_network_attempts": 0,
    }
    assert preflight_failure["context"]["correction_boundary"] == {
        "provider_live_runtime_changed": True,
        "preflight_moved_before_reservation": True,
        "durable_inventory_precedes_new_call_stops": True,
        "all_slots_inventoried_before_provider_access": True,
        "durable_proven_failures_counted_across_dispatches": True,
        "verified_quota_survives_payload_replay_failure": True,
        "replay_quota_compared_as_current_live_sequence": False,
        "complete_replay_provider_access_reads": 0,
        "r2_get_requests_per_dispatch_maximum": 34,
        "prior_ambiguity_counts_as_new_attempt": False,
        "automatic_provider_retries": 0,
        "external_effects": 0,
    }
    assert transport_close_failure["record_type"] == "FAILURE"
    assert transport_close_failure["previous_hash"] == preflight_failure["hash"]
    assert transport_close_failure["proof"] == [TRANSPORT_CLOSE_FAILURE_CLAIM_ID]
    assert transport_close_failure["context"]["reproduction"] == {
        "adapter_transient_close": {
            "before": "CLOSE_CALLS_1_CLOSED_FALSE_FLAG_TRUE",
            "after": "CLOSE_CALLS_2_CLOSED_TRUE_CONFIRMED_TRUE",
        },
        "post_tls_peer_mismatch": {
            "before": "RAW_CLOSED_WRAPPED_OPEN",
            "after": "WRAPPED_CLOSED_RAW_NOT_REUSED",
        },
        "successful_response_persistent_cleanup_failure": {
            "before": "HTTP_200_RETURNED",
            "after": "LIVE_TRANSPORT_CONNECTION_CLOSE_FAILED",
        },
        "unapproved_network_attempts": 0,
    }
    assert transport_close_failure["context"]["correction_boundary"] == {
        "tls_verification_preserved": True,
        "absolute_deadlines_preserved": True,
        "response_before_connection_cleanup": True,
        "cleanup_attempts_maximum_per_resource": 2,
        "automatic_provider_retries": 0,
        "external_effects": 0,
    }
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["previous_hash"] == transport_close_failure["hash"]
    assert decision["context"]["writer"] == "C0"
    assert decision["context"]["writer_count"] == 1
    assert decision["context"]["reviewed_projection"] == {
        "sha256": projection["engineering_projection_sha256"],
        "path_count": projection["artifact_path_count"],
        "normalization": "LF_NORMALIZED_TEXT_BYTES",
        "byte_frozen": True,
    }
    historical_bindings = [
        {
            "decision_id": "RCV3-20261003-210",
            "ledger_record_hash": "d3303b7b8ac3a09731d60121bebea49bb2469db4a8f902da241daafd7b4cacc0",
            "projection_claim_id": PROJECTION_CLAIM_ID,
            "projection_sha256": "70003fdb199d64f5686f3b1047a4c01e42b1aabd4fdf1e6553d86e0013762158",
            "path_count": 17,
        },
        {
            "decision_id": "RCV3-20261003-212",
            "ledger_record_hash": "d6a531bc95014cd62d7d9b4eb0c50ba5d3f075cbe81a0a3d6d6b5d8167700a7d",
            "projection_claim_id": HISTORICAL_PROJECTION_CLAIM_ID,
            "projection_sha256": "5053ca50893277af22e656ab92c5e9bfd2c1252ee57693839b483caf84b58833",
            "path_count": 19,
        },
    ]
    assert decision["context"]["historical_decision_bindings"] == historical_bindings
    records_by_id = {record["decision_id"]: record for record in records}
    for binding in historical_bindings:
        historical_record = records_by_id[binding["decision_id"]]
        assert historical_record["hash"] == binding["ledger_record_hash"]
        assert binding["projection_claim_id"] in historical_record["proof"]
        assert (
            historical_record["context"]["reviewed_projection"]["sha256"]
            == (binding["projection_sha256"])
        )
        assert (
            historical_record["context"]["reviewed_projection"]["path_count"]
            == (binding["path_count"])
        )
    assert decision["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, path in ACTIVE_REVIEW_ARTIFACTS.items()
    }
    assert set(decision["proof"]) == {
        REPRESENTATION_FAILURE_CLAIM_ID,
        PREFLIGHT_FAILURE_CLAIM_ID,
        PREFLIGHT_REGRESSION_CLAIM_ID,
        TRANSPORT_CLOSE_FAILURE_CLAIM_ID,
        TRANSPORT_CLOSE_REGRESSION_CLAIM_ID,
        ACTIVE_PROJECTION_CLAIM_ID,
        ACTIVE_FINAL_REVIEW_CLAIM_ID,
    }
    expected_edges = [
        {
            "edge_id": "EDGE.827",
            "from_claim_id": REPRESENTATION_FAILURE_CLAIM_ID,
            "to_decision_id": REPRESENTATION_FAILURE_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.828",
            "from_claim_id": PREFLIGHT_FAILURE_CLAIM_ID,
            "to_decision_id": PREFLIGHT_FAILURE_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.829",
            "from_claim_id": TRANSPORT_CLOSE_FAILURE_CLAIM_ID,
            "to_decision_id": TRANSPORT_CLOSE_FAILURE_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.830",
            "from_claim_id": REPRESENTATION_FAILURE_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.831",
            "from_claim_id": PREFLIGHT_FAILURE_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.832",
            "from_claim_id": PREFLIGHT_REGRESSION_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.833",
            "from_claim_id": TRANSPORT_CLOSE_FAILURE_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.834",
            "from_claim_id": TRANSPORT_CLOSE_REGRESSION_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.835",
            "from_claim_id": ACTIVE_PROJECTION_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
        {
            "edge_id": "EDGE.836",
            "from_claim_id": ACTIVE_FINAL_REVIEW_CLAIM_ID,
            "to_decision_id": ACTIVE_FINAL_DECISION_ID,
            "relation": "SUPPORTS",
            "status": "RECORDED",
        },
    ]
    edge_start = next(i for i, edge in enumerate(graph["edges"]) if edge["edge_id"] == "EDGE.827")
    assert graph["edges"][edge_start : edge_start + len(expected_edges)] == expected_edges
    for candidate in (
        representation_failure,
        preflight_failure,
        transport_close_failure,
        decision,
    ):
        canonical_record = json.dumps(
            {key: value for key, value in candidate.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical_record).hexdigest() == candidate["hash"]
