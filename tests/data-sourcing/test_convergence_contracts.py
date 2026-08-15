from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

ROOT = Path(__file__).parents[2]
REPORTS = ROOT / "reports" / "data-sourcing"
MODULE_PATH = ROOT / "tools" / "data-sourcing" / "recalculate_convergence.py"
GENERATED_REPORTS = {
    "blocked-experiments-v1.json",
    "credit-budget-scenarios-v1.json",
    "data-hypothesis-convergence-v1.json",
    "event-aware-capture-plan-v1.json",
    "experiment-data-window-matrix-v1.json",
    "first-receipt-backed-capture-pilot-v1.json",
    "official-source-assumptions-v1.json",
    "source-gap-roadmap-v1.json",
}


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recalculate_convergence", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((REPORTS / name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    module = _load_module()
    return cast(dict[str, str], module.build_documents(ROOT, "2026-08-14T22:22:16Z"))


def test_generator_reproduces_exact_repository_reports(generated: dict[str, str]) -> None:
    assert set(generated) == GENERATED_REPORTS
    for name, content in generated.items():
        assert (REPORTS / name).read_bytes() == content.encode("utf-8")


def test_all_25_protocol_rows_are_complete_and_blocked() -> None:
    matrix = _json("experiment-data-window-matrix-v1.json")
    rows = matrix["experiments"]
    required = {
        "experiment_id",
        "hypothesis_id",
        "family",
        "supportability_category",
        "predictors",
        "targets",
        "labels",
        "metadata",
        "predictor_cutoff",
        "target_window",
        "maximum_staleness",
        "markets",
        "bookmaker_grain",
        "league_grain",
        "minimum_bookmakers",
        "minimum_snapshots",
        "minimum_sample",
        "negative_controls",
        "de_vig_branches",
        "source_candidates",
        "receipt_requirements",
        "settlement_requirements",
        "current_data_gate",
        "execution_status",
        "execution_authority",
        "promotion_status",
        "profitability_status",
        "capture_design_status",
    }

    assert len(rows) == matrix["row_count"] == 25
    assert len({row["experiment_id"] for row in rows}) == 25
    assert matrix["category_counts"] == {"A": 8, "B": 11, "C": 5, "D": 1}
    assert all(required <= row.keys() for row in rows)
    assert all(row["execution_status"] == "NOT_RUN" for row in rows)
    assert all(row["execution_authority"] == "NOT_AUTHORIZED_IN_THIS_MISSION" for row in rows)
    assert all(row["promotion_status"] == "NOT_PROMOTED" for row in rows)
    assert all(row["profitability_status"] == "NOT_QUALIFIED_PROFITABLE" for row in rows)


def test_temporal_roles_never_admit_a_target_as_predictor() -> None:
    matrix = _json("experiment-data-window-matrix-v1.json")
    schedule = _json("event-aware-capture-plan-v1.json")

    for row in matrix["experiments"]:
        predictor_datasets = {item["dataset"] for item in row["predictors"]}
        target_datasets = {item["dataset"] for item in row["targets"]}
        assert predictor_datasets.isdisjoint(target_datasets)
        assert all(not item["eligible_as_pre_cutoff_predictor"] for item in row["targets"])
        assert all(not item["eligible_as_pre_cutoff_predictor"] for item in row["labels"])

    windows = schedule["window_definitions"]
    assert windows["H24"]["role"] == "PREDICTOR"
    assert windows["H24"]["maximum_staleness_minutes"] == 120
    assert windows["H2"]["maximum_staleness_minutes"] == 15
    assert windows["H1"]["role"] == "TARGET"
    assert windows["H2"]["protocol_role_bindings"]["TARGET"] == ["RDS-EXP-V1-006"]
    assert all(all(group["compatibility_proof"].values()) for group in schedule["call_groups"])


def test_event_aware_grouping_preserves_every_protocol() -> None:
    schedule = _json("event-aware-capture-plan-v1.json")
    metrics = schedule["exact_horizon_metrics"]

    assert len(schedule["capture_requirements"]) == 335
    assert len(schedule["call_groups"]) == 227
    assert metrics["calls_before_grouping"] == 335
    assert metrics["calls_after_grouping"] == 227
    assert metrics["calls_saved"] == metrics["credits_saved"] == 108
    assert len(metrics["protocols_preserved"]) == 25


def test_grouping_contract_is_recomputed_and_rejects_tampering() -> None:
    module = _load_module()
    schedule = _json("event-aware-capture-plan-v1.json")

    module.verify_call_group_contract(schedule)
    tampered = deepcopy(schedule)
    tampered["call_groups"][0]["scheduled_at"] = "2000-01-01T00:00:00Z"
    with pytest.raises(AssertionError, match="admissible interval violated"):
        module.verify_call_group_contract(tampered)

    role_tampered = deepcopy(schedule)
    role_tampered["window_definitions"]["H2"]["protocol_role_bindings"]["PREDICTOR"].append(
        "RDS-EXP-V1-006"
    )
    for requirement in role_tampered["capture_requirements"]:
        if requirement["window_id"] == "H2":
            requirement["protocol_role_bindings"]["PREDICTOR"].append("RDS-EXP-V1-006")
    with pytest.raises(AssertionError, match="window authority mismatch"):
        module.verify_call_group_contract(role_tampered)

    authority_tampered = deepcopy(schedule)
    authority_tampered["window_definitions"]["H2"]["authority"] = "UNREVIEWED_AUTHORITY"
    with pytest.raises(AssertionError, match="window authority mismatch"):
        module.verify_call_group_contract(authority_tampered)


def test_exp009_requires_a_successor_before_execution() -> None:
    matrix = _json("experiment-data-window-matrix-v1.json")
    schedule = _json("event-aware-capture-plan-v1.json")
    exp009 = next(row for row in matrix["experiments"] if row["experiment_id"] == "RDS-EXP-V1-009")

    assert (
        "EXP009_PROTOCOL_SUCCESSOR_REQUIRED_BEFORE_EXECUTION"
        in exp009["current_data_gate"]["convergence_gates"]
    )
    assert exp009["capture_design_status"] == "EXP009_CAPTURE_DESIGN_CANDIDATE"
    assert {"H24", "H12", "H6", "H2"} <= set(schedule["window_definitions"])
    assert schedule["window_definitions"]["H12"]["authority"] == "PROPOSED_NOT_FROZEN_FOR_EXP009"
    assert schedule["window_definitions"]["H6"]["authority"] == "PROPOSED_NOT_FROZEN_FOR_EXP009"


def test_pilot_is_bounded_and_not_authorized() -> None:
    pilot = _json("first-receipt-backed-capture-pilot-v1.json")
    calls = pilot["planned_calls"]

    assert pilot["scope"]["fixture_count"] == 18
    assert pilot["scope"]["canary_fixture_count"] == 5
    assert pilot["scope"]["matchdays"] == [1, 2]
    assert pilot["scope"]["no_backfill"] is True
    assert calls["the_odds_api_total_http_calls"] == 75
    assert calls["the_odds_api_chargeable_calls"] == 73
    assert pilot["planned_credits"]["total_maximum"] == 88
    assert pilot["markets"]["totals_status"] == "TOTALS_COVERAGE_TO_BE_PROVEN"
    assert [row["strategy"] for row in pilot["markets"]["strategy_comparison"]] == [
        "H2H_ONLY",
        "H2H_PLUS_TOTALS_SYSTEMATIC",
        "H2H_SYSTEMATIC_PLUS_TOTALS_PILOT",
        "TOTALS_AFTER_COVERAGE_THRESHOLD",
    ]
    assert pilot["retention"]["status"] == "RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED"
    assert {
        "DESIGN_ONLY",
        "NOT_AUTHORIZED",
        "NO_PROVIDER_CALL",
        "NO_PURCHASE",
        "NO_PROMOTION",
        "NO_BET",
    } <= set(pilot["status"])
    assert pilot["experiments_execution_unblocked"] == []


def test_official_provider_assumptions_fail_closed() -> None:
    assumptions = _json("official-source-assumptions-v1.json")
    convergence = _json("data-hypothesis-convergence-v1.json")
    provider = assumptions["provider_facts"]

    assert provider["official_domain_only"] == "https://the-odds-api.com/"
    assert provider["forbidden_impostor_domain"] == "https://theoddsapi.com/"
    assert assumptions["analysis_dates"]["public_sources_accessed"] == "2026-08-15"
    assert provider["market_sync_field"] == "bookmakers[].markets[].last_update"
    assert provider["market_sync_grain"] == "bookmaker_market"
    assert provider["market_synchronization_verdict"] == (
        "MARKET_SYNCHRONIZATION_OBSERVABLE_DESIGN_ONLY"
    )
    assert provider["retention_verdict"] == ("RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED")
    scope = convergence["reproducibility_scope"]
    assert scope["verdict"] == "DATA_HYPOTHESIS_CONVERGENCE_REPRODUCIBLE"
    assert "does_not_prove" in scope
    assert scope["external_pack_boundary"] == {
        "manifest_sha256_reference": "269f4066b13e88f4397aecd6f1a3d7ba154dc8468415581ce0f6b8922f1537b4",
        "repository_evidence": "NOT_COMMITTED_BY_MISSION_RULE",
        "status": "EXTERNAL_INPUT_NOT_REPRODUCIBLE_FROM_REPOSITORY",
    }
    assert convergence["external_effects"] == {
        "production_connections": 0,
        "promotions": 0,
        "provider_calls": 0,
        "purchases": 0,
        "r2_operations": 0,
        "real_bets": 0,
        "workflow_live_dispatches": 0,
    }


def test_s6_capacity_and_current_recommendation_are_canonical() -> None:
    budgets = _json("credit-budget-scenarios-v1.json")
    recommendation = _json("first-prospective-capture-recommendation-v1.json")
    scenario = next(row for row in budgets["scenarios"] if row["scenario_id"] == "S6")

    assert scenario["annual_credits"] == 13236
    assert scenario["safety_reserve"]["monthly_capacity_required"] == 1986
    assert recommendation["recommended_pilot"]["maximum_credits"] == 88
    assert recommendation["legacy_projection"]["status"] == (
        "NON_CANONICAL_SUPERSEDED_BY_EVENT_AWARE_PLAN"
    )
    assert recommendation["next_mission"] == "FIRST_RECEIPT_BACKED_CAPTURE_PILOT_V1"
