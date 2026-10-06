from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_PATH = (
    ROOT / "reports" / "evidence" / "robin-simplification-final-acceptance-20261006.json"
)
FINAL_REVIEW_PATH = (
    ROOT / "reports" / "council" / "robin-simplification-exploration-final-review-v1.json"
)
EVIDENCE_GRAPH_PATH = ROOT / "reports" / "evidence" / "evidence-graph.json"
INDEPENDENT_REVIEW_PATHS = {
    "architecture": (
        ROOT
        / "reports"
        / "council"
        / "robin-simplification-exploration-final-c1-architecture-v1.json"
    ),
    "operations": (
        ROOT
        / "reports"
        / "council"
        / "robin-simplification-exploration-final-c2-operations-v1.json"
    ),
    "performance": (
        ROOT
        / "reports"
        / "council"
        / "robin-simplification-exploration-final-c4-performance-v1.json"
    ),
}
FUNCTIONAL_REVISION = "fc45ebe78260af3eb39cdd2ed567071439e1a380"
WINDOW_START = "2026-10-05T09:50:52Z"
WINDOW_END = "2026-10-06T09:50:52Z"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_final_acceptance_requires_eight_passes_on_the_deployed_revision() -> None:
    acceptance = _load(ACCEPTANCE_PATH)
    assert acceptance["schema_version"] == "robin-simplification-final-acceptance-v1"
    assert acceptance["mission_id"] == "ROBIN_SIMPLIFICATION_EXPLORATION_20261005"
    assert acceptance["status"] == "PASS"
    assert acceptance["functional_revision"] == FUNCTIONAL_REVISION
    assert acceptance["safety_locks"] == {
        "STORAGE_PAUSED": True,
        "P3_P4_PAUSED": True,
        "PRODUCTION_LOCKED": True,
        "REAL_BETS": False,
        "NO_BET_DEFAULT": True,
        "PROMOTION_LOCKED": True,
        "SOCIAL_PUBLISHING_ENABLED": False,
        "DEMO_MODE_ENABLED": False,
    }

    criteria = acceptance["criteria"]
    assert isinstance(criteria, dict)
    assert set(criteria) == {f"R{number}" for number in range(1, 9)}
    for criterion in criteria.values():
        assert criterion["status"] == "PASS"
        assert criterion["claim_ids"]
        assert criterion["evidence_refs"]
        assert criterion["counterexamples"]

    graph = _load(EVIDENCE_GRAPH_PATH)
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    asserted_claim_ids = {
        claim_id for criterion in criteria.values() for claim_id in criterion["claim_ids"]
    }
    for claim_id in asserted_claim_ids:
        claim = claims[claim_id]
        assert claim["status"] == "VERIFIED"
        artifact_path = ROOT / claim["artifact"]
        assert artifact_path.is_file()
        assert _lf_sha256(artifact_path) == claim["hash"]

    review = _load(FINAL_REVIEW_PATH)
    Draft202012Validator(
        _load(ROOT / "configs" / "agents" / "agent-report-schema-v3.json")
    ).validate(review)
    assert review["agent_id"] == "C0"
    assert review["mission_id"] == acceptance["mission_id"]
    assert review["main_objection"].startswith("PASS_AND_HOLD")
    assert review["unknowns"] == []
    assert review["independent_review"] == {
        "architecture": "PASS",
        "operations": "PASS",
        "performance": "PASS",
    }
    schema = _load(ROOT / "configs" / "agents" / "agent-report-schema-v3.json")
    expected_agent_ids = {"architecture": "C1", "operations": "C2", "performance": "C4"}
    for role, path in INDEPENDENT_REVIEW_PATHS.items():
        independent_review = _load(path)
        Draft202012Validator(schema).validate(independent_review)
        assert independent_review["agent_id"] == expected_agent_ids[role]
        assert independent_review["mission_id"] == acceptance["mission_id"]
        assert independent_review["main_objection"].startswith("PASS")
        assert independent_review["unknowns"] == []
        assert independent_review["facts_verified"]
        assert all(fact["status"] == "VERIFIED" for fact in independent_review["facts_verified"])
        assert not any(
            risk["severity"] in {"CRITICAL", "HIGH"} for risk in independent_review["risks"]
        )


def test_continuity_reconciles_the_complete_frozen_24_hour_window() -> None:
    continuity = _load(ACCEPTANCE_PATH)["continuity"]
    assert continuity["window_start_utc"] == WINDOW_START
    assert continuity["window_end_utc"] == WINDOW_END
    start = datetime.fromisoformat(WINDOW_START.replace("Z", "+00:00"))
    end = datetime.fromisoformat(WINDOW_END.replace("Z", "+00:00"))
    assert (end - start).total_seconds() == 86_400

    slots = continuity["expected_slots"]
    assert [slot["slot_start_utc"] for slot in slots] == [
        "2026-10-05T10:00:00Z",
        "2026-10-05T12:00:00Z",
        "2026-10-05T14:00:00Z",
        "2026-10-05T16:00:00Z",
        "2026-10-05T18:00:00Z",
        "2026-10-05T20:00:00Z",
        "2026-10-05T22:00:00Z",
        "2026-10-06T00:00:00Z",
        "2026-10-06T02:00:00Z",
        "2026-10-06T04:00:00Z",
        "2026-10-06T06:00:00Z",
        "2026-10-06T08:00:00Z",
    ]
    assert all(slot["classification"] in {"ACQUISITION", "REPLAY", "INCIDENT"} for slot in slots)
    assert any(slot["classification"] == "INCIDENT" for slot in slots)
    assert continuity["unresolved_recurrence_defects"] == []
    assert continuity["coverage"] == {
        "leagues": 5,
        "h2h_branches": 5,
        "totals_branches": 5,
        "partial_provider_coverage_visible": True,
    }


def test_postmerge_delivery_is_uploaded_and_loaded_without_manual_copy() -> None:
    delivery = _load(ACCEPTANCE_PATH)["postmerge_delivery"]
    assert delivery["repository_sha"] == FUNCTIONAL_REVISION
    assert delivery["workflow_run_id"] > 0
    assert delivery["artifact_id"] > 0
    assert delivery["artifact_name"] == f"robin-autonomous-lab-{delivery['workflow_run_id']}"
    assert delivery["schema_version"] == "robin-real-data-explorer-v2"
    assert delivery["validation_outcome"] == "success"
    assert delivery["upload_outcome"] == "success"
    assert delivery["r2_readback_status"] == "VERIFIED"
    assert delivery["local_refresh"]["manual_copy_or_command"] is False
    assert delivery["local_refresh"]["filter_before"] == "Real Madrid"
    assert delivery["local_refresh"]["filter_after"] == "Real Madrid"
    assert delivery["local_refresh"]["current_delivery_run_id"] == str(delivery["workflow_run_id"])
    assert delivery["local_refresh"]["automatic_poll_observed"] is True
    assert delivery["local_refresh"]["status_last_error_code"] is None


def test_incident_and_measurement_limits_remain_visible() -> None:
    acceptance = _load(ACCEPTANCE_PATH)
    incident = acceptance["resolved_delivery_incident"]
    assert incident["failed_run_ids"] == [37405164519, 37410003793]
    assert incident["failed_at"] == "Validate normalized delivery and publish run summary:56"
    assert incident["producer_schema"] == "robin-real-data-explorer-v2"
    assert incident["former_validator_schema"] == "robin-real-data-dashboard-v1"
    assert incident["resolution"] == "ACTIVE_VALIDATOR_ALIGNED_WITH_PRODUCER"
    assert incident["failed_uploads_reclassified_as_success"] is False

    gain = acceptance["measured_gain"]
    assert gain["baseline_wall_minutes"] == 65.1333
    assert gain["candidate_wall_median_minutes"] == 39.6167
    assert gain["absolute_gain_minutes"] == 25.5167
    assert gain["relative_gain_percent"] == 39.176
    assert gain["candidate_wall_range_minutes"] == 3.5333
    assert gain["human_time"] == "NOT_MEASURED"
    assert gain["human_time_gain_claimed"] is False
    assert gain["new_recurring_manual_execution_steps"] == 0
    assert gain["financial_gain_claimed"] is False


def test_real_explorer_acceptance_covers_the_complete_user_path() -> None:
    acceptance = _load(ACCEPTANCE_PATH)
    exploration = acceptance["real_explorer_acceptance"]
    assert exploration["dataset"] == "AUTOMATIC_POSTMERGE_DELIVERY"
    assert exploration["observed_delivery_run_id"] == str(
        acceptance["postmerge_delivery"]["workflow_run_id"]
    )
    assert exploration["search"]["query"] == "Real Madrid"
    assert exploration["search"]["selected_offers"] > 0
    assert exploration["search"]["selected_matches"] > 0
    assert exploration["comparison"]["bookmakers"] >= 2
    assert exploration["comparison"]["acquisitions"] == 2
    assert len(exploration["comparison"]["slot_start_utc"]) == 2
    assert len(set(exploration["comparison"]["slot_start_utc"])) == 2
    assert exploration["tracking"]["matched_rows"] > 0
    assert (
        exploration["tracking"]["matched_rows"]
        + exploration["tracking"]["appeared_rows"]
        + exploration["tracking"]["not_observed_rows"]
        == exploration["search"]["selected_offers"]
    )
    assert exploration["export"]["displayed_rows"] == exploration["export"]["csv_rows"]
    assert exploration["export"]["displayed_rows"] == exploration["export"]["json_rows"]
    assert exploration["export"]["displayed_rows"] == exploration["search"]["selected_offers"]
    assert exploration["export"]["source_identity_mismatches"] == 0
    assert exploration["export"]["csv_json_value_mismatches"] == 0
    assert len(exploration["export"]["csv_sha256"]) == 64
    assert len(exploration["export"]["json_sha256"]) == 64
    assert exploration["history_pin"]["preserved_after_refresh"] is True
    assert exploration["history_pin"]["pinned_delivery_run_id"]
    assert exploration["controls"] == {
        "search": "PASS",
        "sort": "PASS",
        "filters": "PASS",
        "reset": "PASS",
        "stale_state": "PASS",
        "failure_state": "PASS",
        "missing_market_state": "PASS",
    }
    assert exploration["restart"]["automatic_logon_restart_claimed"] is False
    assert exploration["restart"]["service_relaunch"] == "PASS"
    assert exploration["restart"]["state_preserved"] is True
    assert exploration["restart"]["hidden_gh_launcher"] == "PASS"
    assert exploration["restart"]["healthy_hidden_refresh_cycles"] >= 2
    assert exploration["restart"]["runtime_manifest_schema"] == (
        "robin-real-data-explorer-runtime-v2"
    )
    assert exploration["restart"]["runtime_file_count"] > 0
    assert exploration["restart"]["runtime_missing_files"] == 0
    assert exploration["restart"]["runtime_worktree_reference"] is False


def test_jalon10_witnesses_preserve_internal_results_and_memberships() -> None:
    witnesses = _load(ACCEPTANCE_PATH)["jalon10_non_regression"]
    assert witnesses["corpus"] == "ORIGINAL_2020_2025"
    assert witnesses["stake_units"] == 1
    assert witnesses["membership_count"] == 865
    assert witnesses["identity_mismatches"] == 0
    assert witnesses["odds_mismatches"] == 0
    assert witnesses["settlement_mismatches"] == 0
    assert witnesses["profit_mismatches"] == 0
    assert witnesses["roi_mismatches"] == 0
    assert witnesses["drawdown_mismatches"] == 0
    assert witnesses["internal_tolerance"] == {
        "type": "FLOAT64_REPRESENTATION_ONLY",
        "relative": 0.0,
        "per_bet_absolute": 1e-12,
        "aggregate_units_absolute": 1e-9,
        "roi_absolute": 1e-12,
    }
    assert [
        (
            witness["rule"],
            witness["bets"],
            witness["profit_units"],
            witness["roi_internal"],
            witness["max_drawdown_units"],
        )
        for witness in witnesses["witnesses"]
    ] == [
        (
            "La Liga|AWAY|2.00-2.50|margin<=0.06",
            261,
            43.43,
            0.1663984674329502,
            9.269999999999982,
        ),
        (
            "Serie A|DRAW|2.50-3.25|margin<=0.06",
            363,
            57.88,
            0.1594490358126722,
            19.519999999999868,
        ),
        (
            "Serie A|AWAY|1.60-2.00|margin<=0.06",
            241,
            33.42,
            0.1386721991701245,
            7.220000000000027,
        ),
    ]
    assert witnesses["scientific_verdict_changed"] is False


def test_descriptive_experience_stays_non_predictive_and_reproducible() -> None:
    experience = _load(ACCEPTANCE_PATH)["descriptive_experience"]
    assert experience["input_rows"] == 7_648
    assert experience["changed_rows"] == 682
    assert experience["changed_share_percent"] == 8.9174
    assert experience["three_sourced_findings"] == [
        "682 of 7648 matched offers changed between captures (8.9174%).",
        "Serie A changed 202 of 1608 matched offers (12.5622%).",
        "504 of 5352 matched H2H offers changed; 178 of 2296 matched totals offers changed.",
    ]
    assert experience["predictive_claims"] == []
    assert experience["edge_claimed"] is False
    assert experience["profitability_claimed"] is False
    assert experience["reproducible_report"] == (
        "reports/experiments/robin-descriptive-20261005-0800-1000.json"
    )
