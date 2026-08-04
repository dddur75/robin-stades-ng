from __future__ import annotations

from tests.coverage.build_denominator_artifacts import build_artifacts
from tests.coverage.denominator_oracle import GATES_PATH, ROOT, load_json


def test_eight_functional_gates_and_two_source_blocks_are_separate() -> None:
    contract = load_json(GATES_PATH)
    functional = [gate for gate in contract["gates"] if gate["families"]]
    source = [gate for gate in contract["gates"] if not gate["families"]]
    assert len(functional) == 8
    assert {gate["status"] for gate in functional} == {"BLOCKED_BY_COVERAGE"}
    assert {gate["id"] for gate in source} == {"WEATHER_GATE", "FOOTEDNESS_GATE"}
    assert {gate["status"] for gate in source} == {"BLOCKED_BY_SOURCE"}
    assert all(gate["blocks_p0_api_football_coverage"] is False for gate in source)


def test_required_readiness_verdicts_are_distinct_and_evidenced() -> None:
    verdicts = load_json(GATES_PATH)["readiness_verdicts"]
    assert len(verdicts) == len({item["id"] for item in verdicts}) == 8
    assert all(item["evidence_refs"] for item in verdicts)
    ids = {item["id"] for item in verdicts}
    assert {
        "HISTORICAL_DEEP_PIPELINE_READY",
        "HISTORICAL_DEEP_R2_REPLAY_READY",
        "P0_API_FOOTBALL_COVERAGE_PARTIAL",
        "P0_STRICT_FEATURE_READINESS_PARTIAL",
        "P0_RECONSTRUCTED_FEATURE_READINESS_PARTIAL",
        "HYPOTHESIS_BACKTEST_READINESS_PARTIAL",
        "WEATHER_SOURCE_BLOCKED",
        "FOOTEDNESS_SOURCE_BLOCKED",
    } == ids

    claim_ids = {
        claim["claim_id"]
        for claim in load_json(ROOT / "reports/evidence/evidence-graph.json")["claims"]
    }
    graph_refs = {
        ref
        for verdict in verdicts
        for ref in verdict["evidence_refs"]
        if ref.startswith("PR26.")
    }
    assert graph_refs <= claim_ids


def test_generated_gate_and_property_reports_unlock_nothing() -> None:
    artifacts = build_artifacts()
    gate = next(
        item
        for item in artifacts.values()
        if item["schema_version"] == "p0-readiness-gates-report-v1"
    )
    properties = next(
        item
        for item in artifacts.values()
        if item["schema_version"] == "p0-property-readiness-v1"
    )
    assert gate["counts"] == {
        "functional_total": 8,
        "functional_ready": 0,
        "blocked_by_coverage": 8,
        "blocked_by_source": 2,
    }
    assert gate["properties_unlocked"] == []
    assert properties["families_exploitable"] == []
    assert properties["properties_unlocked"] == []
    assert properties["hypergraph_verdict"] == "NOT_OPENED_DATA_GATES_INSUFFICIENT"
