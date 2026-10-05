from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_SIMPLIFICATION_EXPLORATION_20261005"
MANIFEST = ROOT / "configs/execution/robin-simplification-exploration-20261005.json"
REPORTS = (
    "robin-simplification-exploration-c1-architecture-v1.json",
    "robin-simplification-exploration-dp5-performance-v1.json",
    "robin-simplification-exploration-a2-operations-v1.json",
    "robin-simplification-exploration-dp6-science-v1.json",
    "robin-simplification-exploration-ux6-ux-v1.json",
    "robin-simplification-exploration-c2-qa-v1.json",
)


def _json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_mission_manifest_is_exact_and_provider_free() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
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
    assert manifest["authorized_stages"] == ["E1", "E2", "E3A", "E3B", "E4"]
    assert manifest["maximum_stage"] == "E4"
    assert manifest["source_hash"] == (
        "cba3fd7074ca102fb629c5e1b1507412f53bbd1a680cc6307e0043f4a1e46dd9"
    )
    effects = ";".join(manifest["external_effects"])
    for denied in (
        "PROVIDER_HTTP_REQUESTS_0",
        "PURCHASES_0",
        "REAL_BETS_0",
        "PROMOTIONS_0",
        "SOCIAL_PUBLICATIONS_0",
        "BACKFILLS_0",
    ):
        assert denied in effects


def test_matrix_schema_and_six_read_only_reports_bind_the_mission() -> None:
    matrix = _json("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][MISSION_ID]
    assert mission["writer"] == "C0"
    assert {"C0", "C1", "C2", "DP5", "DP6", "UX6", "A2"} <= set(
        mission["agents"]
    )
    assert mission["scale_ceiling"] == "E4"

    schema = _json("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
    validator = Draft202012Validator(schema)
    observed_agents: set[str] = set()
    for name in REPORTS:
        report = _json(f"reports/council/{name}")
        validator.validate(report)
        assert report["mission_id"] == MISSION_ID
        observed_agents.add(report["agent_id"])
    assert observed_agents == {"C1", "C2", "DP5", "DP6", "UX6", "A2"}


def test_real_capture_pair_and_ci_baseline_are_frozen_claims() -> None:
    receipt = ROOT / "reports/evidence/robin-autonomous-lab-run-37292740942-public-receipt.json"
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == (
        "18e2cc5638bb348f0bb264cb5a5c1ae9973cf65379448310910fda9859d45e3d"
    )
    receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_data["slot_start_utc"] == "2026-10-05T10:00:00Z"
    assert receipt_data["validated_capture_count"] == 5
    assert receipt_data["provider_requests_new"] == 5
    assert receipt_data["private_report_r2_status"] == "VERIFIED"

    graph = _json("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    ci = claims["PERF.ROBIN.SIMPLIFICATION.CI.BASELINE.V1.001"]
    assert ci["status"] == "VERIFIED"
    assert ci["baseline_run_ids"] == [37285435788, 37257455182, 37251657005]
    assert ci["baseline_median_minutes"] == 65.13
    assert ci["target_median_minutes_max"] == 45.0
    assert ci["target_relative_reduction_min"] == 0.309
    pair = claims["DATA.ROBIN.SIMPLIFICATION.CAPTURE_PAIR.V1.001"]
    assert pair["status"] == "VERIFIED"
    assert pair["slot_start_utc"] == [
        "2026-10-05T08:00:00Z",
        "2026-10-05T10:00:00Z",
    ]
    assert pair["provider_http_requests_new"] == 10


def test_authorization_is_the_latest_canonical_ledger_record() -> None:
    records = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    record_index = next(
        index
        for index in range(len(records) - 1, -1, -1)
        if records[index]["record_type"] == "MISSION_AUTHORIZED"
        and records[index]["context"].get("mission_id") == MISSION_ID
    )
    record = records[record_index]
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["context"]["mission_id"] == MISSION_ID
    assert record["context"]["writer"] == "C0"
    assert record["context"]["writer_count"] == 1
    assert record["previous_hash"] == records[record_index - 1]["hash"]
    unhashed = {key: value for key, value in record.items() if key != "hash"}
    canonical = json.dumps(
        unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == record["hash"]
