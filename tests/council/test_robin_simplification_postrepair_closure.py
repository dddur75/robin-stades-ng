from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CLOSURE_PATH = (
    ROOT / "reports" / "evidence" / "robin-simplification-postrepair-closure-20261006.json"
)
GRAPH_PATH = ROOT / "reports" / "evidence" / "evidence-graph.json"
LEDGER_PATH = ROOT / "reports" / "council" / "decision-ledger.jsonl"
FINAL_ACCEPTANCE_PATH = (
    ROOT / "reports" / "evidence" / "robin-simplification-final-acceptance-20261006.json"
)
POSTMERGE_DELIVERY_PATH = (
    ROOT / "reports" / "evidence" / "robin-simplification-postmerge-delivery-20261006.json"
)
R3_PATH = ROOT / "reports" / "hypothesis-evidence" / "r3-jalon10-non-regression.json"
REVIEW_PATHS = {
    "architecture": ROOT
    / "reports"
    / "council"
    / "robin-simplification-postrepair-final-c1-architecture-v1.json",
    "operations": ROOT
    / "reports"
    / "council"
    / "robin-simplification-postrepair-final-c2-operations-v1.json",
    "performance": ROOT
    / "reports"
    / "council"
    / "robin-simplification-postrepair-final-c4-performance-v1.json",
}
MERGED_MAIN = "7e7ffb0b1982d26ccccb9a28a26c3ae828780c26"
REPAIR_COMMIT = "123c6340e985a6519a40bea44ed35a68accd8e2c"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_postrepair_closure_binds_real_delivery_and_automatic_handoff() -> None:
    closure = _load(CLOSURE_PATH)
    assert closure["schema_version"] == "robin-simplification-postrepair-closure-v1"
    assert closure["mission_id"] == "ROBIN_SIMPLIFICATION_EXPLORATION_20261005"
    assert closure["status"] == "PASS"
    assert closure["repository_revision"] == MERGED_MAIN
    assert closure["repair"] == {
        "failed_run_id": 37514038870,
        "failure_boundary": "PRE_CAPTURE_JSON_CONSUMING_CONTROL_UNTRACED_ENDPOINT",
        "exact_failed_endpoint": "UNKNOWN_NOT_IN_LOG",
        "repair_commit": REPAIR_COMMIT,
        "exact_head_ci_run_id": 37523345904,
        "exact_head_ci_jobs_passed": 17,
        "exact_head_ci_jobs_total": 17,
        "pull_request": 95,
        "merged_main": MERGED_MAIN,
    }

    rearm = closure["maintenance_rearm"]
    assert rearm["run_id"] == 37528320108
    assert rearm["head_sha"] == MERGED_MAIN
    assert rearm["pre_rearm_active_target_runs"] == 0
    assert rearm["authorized_maintenance"] is True
    assert rearm["autonomy_proof"] is False
    assert rearm["counters_reset"] is False
    assert rearm["existing_data_reset"] is False

    cycle = closure["automatic_cycle"]
    assert cycle["run_id"] == 37528344645
    assert cycle["head_sha"] == MERGED_MAIN
    assert cycle["actor"] == "github-actions[bot]"
    assert cycle["triggering_actor"] == "github-actions[bot]"
    assert cycle["conclusion"] == "success"
    assert cycle["workflow_jobs"] == {"relay": "success", "capture": "success"}
    assert cycle["artifact"] == {
        "id": 11446741531,
        "name": "robin-autonomous-lab-37528344645",
        "archive_sha256": "b4316cb32966c5a2718c2489a88a4a86be8f95386fb046c9d0f2d8cec698ecf3",
        "file_count": 4,
    }
    receipt = cycle["receipt"]
    assert receipt["schema_version"] == "robin-autonomous-lab-public-receipt-v1"
    assert receipt["explorer_schema_version"] == "robin-real-data-explorer-v2"
    assert receipt["slot_start_utc"] == "2026-10-06T20:00:00Z"
    assert receipt["status"] == "REAL_DATA_PARTIAL"
    assert receipt["validated_captures"] == 5
    assert receipt["provider_requests_new"] == 5
    assert receipt["provider_credits_new"] == 10
    assert receipt["r2_readback_status"] == "VERIFIED"
    assert receipt["observations"] == 7542
    assert receipt["matches"] == 96
    assert receipt["bookmakers"] == 25
    assert receipt["lifetime_provider_requests"] == 121
    assert receipt["lifetime_provider_credits"] == 244
    assert receipt["previous_lifetime_provider_requests"] == 116
    assert receipt["previous_lifetime_provider_credits"] == 234
    assert receipt["automatic_retries"] == 0
    assert receipt["automatic_backfills"] == 0
    assert receipt["purchases"] == 0
    assert receipt["real_bets"] == 0
    assert receipt["promotions"] == 0
    assert cycle["content_verification"]["json_csv_rows"] == 7542
    assert cycle["content_verification"]["source_field_mismatches"] == 0
    assert cycle["content_verification"]["forbidden_raw_fields"] == []

    handoff = closure["automatic_handoff"]
    assert handoff["run_id"] == 37535663388
    assert handoff["head_sha"] == MERGED_MAIN
    assert handoff["actor"] == "github-actions[bot]"
    assert handoff["triggering_actor"] == "github-actions[bot]"
    assert handoff["sequence"] == 2
    assert handoff["unique_exact_successors"] == 1
    assert handoff["created_before_parent_capture"] is True
    assert handoff["observed_status"] == "waiting"
    assert any(
        "its unique creation proves the handoff, not its later terminal outcome" in limit
        for limit in closure["limitations"]
    )


def test_explorer_received_delivery_without_manual_refresh_and_preserved_filter() -> None:
    explorer = _load(CLOSURE_PATH)["explorer"]
    assert explorer["manual_copy_or_command"] is False
    assert explorer["automatic_poll_observed"] is True
    assert explorer["current_delivery_run_id"] == "37528344645"
    assert explorer["current_slot_start_utc"] == "2026-10-06T20:00:00Z"
    assert explorer["freshness"] == "FRESH"
    assert explorer["search_before"] == explorer["search_after"] == "Real Madrid"
    assert explorer["selected_offers"] == 144
    assert explorer["selected_matches"] == 2
    assert explorer["selected_bookmakers"] == 20
    assert explorer["selected_acquisitions"] == 2
    assert explorer["comparison_slots_utc"] == [
        "2026-10-06T16:00:00Z",
        "2026-10-06T20:00:00Z",
    ]
    assert explorer["console_errors"] == []
    assert explorer["console_warnings"] == []
    export = explorer["export"]
    assert export["displayed_rows"] == export["csv_rows"] == export["json_rows"] == 144
    assert export["source_identity_mismatches"] == 0
    assert export["csv_json_value_mismatches_after_formula_guard"] == 0
    assert export["numeric_tolerance_consumed"] == Decimal("0")
    assert export["negative_formula_guard_cells"] == 12


def test_closure_reuses_immutable_acceptance_and_r3_evidence() -> None:
    closure = _load(CLOSURE_PATH)
    assert closure["immutable_reused_evidence"] == {
        str(FINAL_ACCEPTANCE_PATH.relative_to(ROOT)).replace("\\", "/"): (
            "c798bf64643dbb94be0990e1cb21453443baced13286da042317892e847ece87"
        ),
        str(POSTMERGE_DELIVERY_PATH.relative_to(ROOT)).replace("\\", "/"): (
            "571f14dc9b13a156b739e6d364e0c1f762a39005eeab0c54b9b25a3325ed627f"
        ),
        str(R3_PATH.relative_to(ROOT)).replace("\\", "/"): (
            "32a2ded72c0e18a1f56583e1f06bc91583b728f7e1ca4448ca0dd7d1469c1c33"
        ),
    }
    assert closure["immutable_reused_evidence_hashing"] == ("SHA256_LF_NORMALIZED_TEXT_BYTES")
    assert (
        _lf_sha256(FINAL_ACCEPTANCE_PATH)
        == closure["immutable_reused_evidence"][
            "reports/evidence/robin-simplification-final-acceptance-20261006.json"
        ]
    )
    assert (
        _lf_sha256(POSTMERGE_DELIVERY_PATH)
        == closure["immutable_reused_evidence"][
            "reports/evidence/robin-simplification-postmerge-delivery-20261006.json"
        ]
    )
    assert (
        _lf_sha256(R3_PATH)
        == closure["immutable_reused_evidence"][
            "reports/hypothesis-evidence/r3-jalon10-non-regression.json"
        ]
    )
    assert closure["criteria"] == {f"R{number}": "PASS" for number in range(1, 9)}
    assert closure["jalon10_non_regression"]["identity_mismatches"] == 0
    assert closure["jalon10_non_regression"]["odds_mismatches"] == 0
    assert closure["jalon10_non_regression"]["settlement_mismatches"] == 0
    assert closure["jalon10_non_regression"]["profit_mismatches"] == 0
    assert closure["jalon10_non_regression"]["roi_mismatches"] == 0
    assert closure["jalon10_non_regression"]["drawdown_mismatches"] == 0
    assert closure["jalon10_non_regression"]["scientific_verdict_changed"] is False
    assert closure["measured_gain"]["wall_time_gain_percent"] == 39.176
    assert closure["measured_gain"]["job_minute_gain_percent"] == 30.135


def test_closure_is_independently_reviewed_and_append_only_bound() -> None:
    closure = _load(CLOSURE_PATH)
    schema = _load(ROOT / "configs" / "agents" / "agent-report-schema-v3.json")
    expected_agents = {"architecture": "C1", "operations": "C2", "performance": "C4"}
    for role, path in REVIEW_PATHS.items():
        review = _load(path)
        Draft202012Validator(schema).validate(review)
        assert review["agent_id"] == expected_agents[role]
        assert review["mission_id"] == closure["mission_id"]
        assert review["main_objection"].startswith("PASS")
        assert review["unknowns"] == []
        assert not any(
            risk["severity"] in {"CRITICAL", "HIGH", "MEDIUM"} for risk in review["risks"]
        )

    graph = _load(GRAPH_PATH)
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    for claim_id in closure["claim_ids"]:
        claim = claims[claim_id]
        assert claim["status"] == "VERIFIED"
        assert claim["artifact"] == str(CLOSURE_PATH.relative_to(ROOT)).replace("\\", "/")
        assert claim["hash"] == _lf_sha256(CLOSURE_PATH)

    ledger_records = [json.loads(line) for line in LEDGER_PATH.read_text().splitlines()]
    decision = next(
        record for record in ledger_records if record["decision_id"] == closure["decision_id"]
    )
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert (
        decision["previous_hash"]
        == "78ae520387d369507b387901497905ef40e191df7e6cc638f08a97cd3b523f12"
    )
    nodes = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert nodes[decision["decision_id"]]["ledger_record_hash"] == decision["hash"]


def test_safety_locks_and_schedule_uncertainty_remain_explicit() -> None:
    closure = _load(CLOSURE_PATH)
    assert closure["safety_locks"] == {
        "STORAGE_PAUSED": True,
        "P3_P4_PAUSED": True,
        "PRODUCTION_LOCKED": True,
        "REAL_BETS": False,
        "NO_BET_DEFAULT": True,
        "PROMOTION_LOCKED": True,
        "SOCIAL_PUBLISHING_ENABLED": False,
        "DEMO_MODE_ENABLED": False,
    }
    assert closure["workflow_configuration"] == {
        "workflow_id": 321915839,
        "state": "active",
        "path": ".github/workflows/prospective-deep-scheduler.yml",
    }
    schedule = closure["schedule_observation"]
    assert schedule["new_schedule_event_observed_after_merge"] is False
    assert schedule["cause"] == "UNKNOWN_NOT_EXPOSED_BY_OBSERVED_EVIDENCE"
    assert schedule["github_cause_claimed"] is False
    assert closure["limitations"]
