from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_AUTONOMOUS_LAB_20261004"
SOURCE = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md"
MANIFEST = "configs/execution/robin-autonomous-lab-20261004.json"
RECEIPT = "reports/evidence/robin-real-data-result-run-37153158456-public-receipt.json"
DECISION_ID = "RCV3-20261004-225"
CLAIM_IDS = {
    "GOV.AUTHORIZATION.ROBIN_AUTONOMOUS_LAB.V1.001",
    "DATA.ROBIN.AUTONOMOUS_LAB.SEED_CAPTURES.V1.001",
    "DATA.ROBIN.AUTONOMOUS_LAB.SEED_VIEW.V1.001",
    "GOV.ROBIN.AUTONOMOUS_LAB.SEED_CONSUMPTION.V1.001",
}
RECURRING_CLAIM_IDS = {
    "DATA.ROBIN.AUTONOMOUS_LAB.RECURRING_CAPTURES.V1.001",
    "DATA.ROBIN.AUTONOMOUS_LAB.RECURRING_VIEW.V1.001",
    "GOV.ROBIN.AUTONOMOUS_LAB.RECURRING_CONSUMPTION.V1.001",
}
HISTORICAL_CLAIM_IDS = {
    "DATA.ROBIN.REAL.RESULT.CAPTURES.V1.001",
    "DATA.ROBIN.REAL.RESULT.VIEW.V1.001",
    "GOV.ROBIN.REAL.RESULT.CONSUMPTION.V1.001",
}


def _load(relative: str) -> object:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _lf_sha256(relative: str) -> str:
    data = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _ledger() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_successor_manifest_has_exact_authority_and_source_hash() -> None:
    manifest = _load(MANIFEST)
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
    assert manifest["compute_budget"] == 32_000
    assert manifest["time_budget"] == 2_592_000
    assert manifest["source_hash"] == _lf_sha256(SOURCE)
    assert manifest["expires_at"] == "2026-11-03T23:59:59Z"
    effects = set(manifest["external_effects"])
    assert {
        "github_actions_schedule_every_2_hours_minute_17",
        "github_actions_artifact_upload_normalized_public_repository_existing_channel",
        "provider_http_rolling_24h_max_140",
        "provider_credit_rolling_24h_max_280",
        "provider_http_rolling_30d_max_4000",
        "provider_credit_rolling_30d_max_8000",
        "provider_existing_secret_read",
        "r2_immutable_raw_capture_and_exact_readback",
        "r2_atomic_accounting_head_compare_and_swap",
        "r2_private_latest_projection",
    } <= effects


def test_verified_seed_receipt_is_exact_and_does_not_relabel_partial_branches() -> None:
    receipt = _load(RECEIPT)
    receipt_bytes = (ROOT / RECEIPT).read_bytes().replace(b"\r\n", b"\n").rstrip(b"\n")
    assert hashlib.sha256(receipt_bytes).hexdigest() == (
        "72b0ba67363658f7503968e43c831e5485d2c6ea9f1f1a2a8b73a0cb5ac38e37"
    )
    assert receipt["github_run_id"] == "37153158456"
    assert receipt["repository_sha"] == "0be96131d1c9c6d7337629f906ead3b282304293"
    assert receipt["validated_capture_count"] == 15
    assert receipt["row_count"] == 21_759
    assert receipt["match_count"] == 96
    assert receipt["bookmaker_count"] == 25
    assert receipt["completed_cycle_count"] == 3
    assert receipt["incomplete_branch_count"] == 15
    assert receipt["status"] == "REAL_DATA_PARTIAL"
    assert receipt["private_report_r2_status"] == "VERIFIED"
    assert receipt["provider_requests_cumulative"] == 16
    assert receipt["provider_credits_cumulative_upper_bound"] == 34
    assert receipt["real_bets"] == 0
    assert receipt["purchases"] == 0
    assert receipt["backfills"] == 0


def test_successor_is_bound_to_single_writer_matrix_and_schema() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][MISSION_ID]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C2", "C4", "DP6", "A2"]
    assert mission["scale_ceiling"] == "E3B"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
        "platform": ["A2"],
    }
    authority = matrix["authorization"]
    assert (
        "ROLLING_24H_HTTP_MAX_140_CREDITS_MAX_280"
        in authority["robin_autonomous_lab_20261004_effect_budget"]
    )
    assert (
        "ROLLING_30D_HTTP_MAX_4000_CREDITS_MAX_8000"
        in authority["robin_autonomous_lab_20261004_effect_budget"]
    )
    assert (
        "ACCOUNTING_CAS_BEFORE_ANY_PROVIDER_DISPATCH"
        in authority["robin_autonomous_lab_20261004_ordering"]
    )
    assert (
        "NORMALIZED_EXISTING_GITHUB_ARTIFACT_CHANNEL"
        in authority["robin_autonomous_lab_20261004_source_boundary"]
    )
    schema = _load("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]


def test_seed_claims_and_authorization_are_append_only_without_rewriting_history() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    assert CLAIM_IDS <= claims.keys()
    assert RECURRING_CLAIM_IDS <= claims.keys()
    assert all(claims[claim_id]["status"] == "VERIFIED" for claim_id in CLAIM_IDS)
    assert all(claims[claim_id]["status"] == "PARTIAL" for claim_id in RECURRING_CLAIM_IDS)
    assert all(claims[claim_id]["status"] == "PARTIAL" for claim_id in HISTORICAL_CLAIM_IDS)
    assert claims["DATA.ROBIN.AUTONOMOUS_LAB.SEED_CAPTURES.V1.001"]["validated_capture_count"] == 15
    assert claims["DATA.ROBIN.AUTONOMOUS_LAB.SEED_VIEW.V1.001"]["row_count"] == 21_759
    assert (
        claims["GOV.ROBIN.AUTONOMOUS_LAB.SEED_CONSUMPTION.V1.001"]["provider_requests_cumulative"]
        == 16
    )
    assert (
        claims["GOV.ROBIN.AUTONOMOUS_LAB.SEED_CONSUMPTION.V1.001"][
            "provider_credits_cumulative_upper_bound"
        ]
        == 34
    )

    records = _ledger()
    record = next(item for item in records if item["decision_id"] == DECISION_ID)
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["responsible"] == "C0"
    assert record["context"]["writer"] == "C0"
    assert record["context"]["writer_count"] == 1
    assert set(record["proof"]) == CLAIM_IDS
    record_index = records.index(record)
    assert record_index > 0
    assert record["previous_hash"] == records[record_index - 1]["hash"]
    canonical = json.dumps(
        {key: value for key, value in record.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(canonical).hexdigest() == record["hash"]
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert decisions[DECISION_ID]["ledger_record_hash"] == record["hash"]
