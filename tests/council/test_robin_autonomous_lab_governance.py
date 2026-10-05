from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_AUTONOMOUS_LAB_20261004"
SCHEDULE_MISSION_ID = "ROBIN_AUTONOMOUS_LAB_SCHEDULE_RELIABILITY_20261004"
SOURCE = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md"
SCHEDULE_SOURCE = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-SCHEDULE-RELIABILITY-2026-10-04.md"
MANIFEST = "configs/execution/robin-autonomous-lab-20261004.json"
SCHEDULE_MANIFEST = "configs/execution/robin-autonomous-lab-schedule-reliability-20261004.json"
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
SCHEDULE_FAILURE_CLAIM_ID = "GOV.SCHEDULER.ROBIN_AUTONOMOUS_LAB.NON_MATERIALIZATION.V1.001"
SCHEDULE_AUTHORIZATION_CLAIM_ID = (
    "GOV.AUTHORIZATION.ROBIN_AUTONOMOUS_LAB.SCHEDULE_RELIABILITY.V1.001"
)
SCHEDULE_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_AUTONOMOUS_LAB.PROJECTION.V1.006"
SCHEDULE_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_AUTONOMOUS_LAB.FINAL.V1.006"
SCHEDULE_FAILURE_DECISION_ID = "RCV3-20261004-229"
SCHEDULE_REDESIGN_DECISION_ID = "RCV3-20261004-230"
SCHEDULE_RELEASE_DECISION_ID = "RCV3-20261004-231"
ESTABLISHED_MISSION_ID = "ROBIN_AUTONOMOUS_LAB_ESTABLISHED_SCHEDULER_20261004"
ESTABLISHED_SOURCE = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-ESTABLISHED-SCHEDULER-2026-10-04.md"
ESTABLISHED_MANIFEST = "configs/execution/robin-autonomous-lab-established-scheduler-20261004.json"
ESTABLISHED_SECOND_FAILURE_CLAIM_ID = (
    "GOV.SCHEDULER.ROBIN_AUTONOMOUS_LAB.NON_MATERIALIZATION.V1.002"
)
ESTABLISHED_HISTORY_CLAIM_ID = "GOV.SCHEDULER.ROBIN_AUTONOMOUS_LAB.ESTABLISHED_ROUTE_HISTORY.V1.001"
ESTABLISHED_AUTHORIZATION_CLAIM_ID = (
    "GOV.AUTHORIZATION.ROBIN_AUTONOMOUS_LAB.ESTABLISHED_SCHEDULER.V1.001"
)
ESTABLISHED_FORMAT_FAILURE_CLAIM_ID = (
    "GOV.CI.ROBIN_AUTONOMOUS_LAB.ESTABLISHED_SCHEDULER.RUFF.FORMAT.FAILURE.V1.001"
)
ESTABLISHED_LEDGER_ASSERTION_FAILURE_CLAIM_ID = (
    "GOV.CI.ROBIN_AUTONOMOUS_LAB.ESTABLISHED_SCHEDULER.LEDGER.SUCCESSION.ASSERTION.FAILURE.V1.001"
)
ESTABLISHED_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_AUTONOMOUS_LAB.PROJECTION.V1.009"
ESTABLISHED_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_AUTONOMOUS_LAB.FINAL.V1.009"
ESTABLISHED_FAILURE_DECISION_ID = "RCV3-20261004-232"
ESTABLISHED_REDESIGN_DECISION_ID = "RCV3-20261004-233"
ESTABLISHED_FORMAT_FAILURE_DECISION_ID = "RCV3-20261004-235"
ESTABLISHED_LEDGER_ASSERTION_FAILURE_DECISION_ID = "RCV3-20261004-237"
ESTABLISHED_RELEASE_DECISION_ID = "RCV3-20261004-238"
SCHEDULE_PROJECTION_PATHS = {
    ".github/workflows/92-robin-autonomous-lab.yml",
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/execution/robin-autonomous-lab-20261004.json",
    SCHEDULE_MANIFEST,
    "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md",
    SCHEDULE_SOURCE,
    "docs/superpowers/plans/2026-10-04-robin-autonomous-lab.md",
    "docs/superpowers/specs/2026-10-04-robin-autonomous-lab-design.md",
    RECEIPT,
    "scripts/run_recurring_real_data.py",
    "src/robin/capture/real_data_dashboard.py",
    "src/robin/capture/real_data_result.py",
    "src/robin/capture/recurring_real_data.py",
    "src/robin/prospective_observatory/chronos_r2.py",
    "tests/capture/test_real_data_dashboard.py",
    "tests/capture/test_recurring_real_data.py",
    "tests/capture/test_recurring_real_data_workflow.py",
    "tests/capture/test_reprise_collecte_workflow.py",
    "tests/capture/test_run_recurring_real_data_cli.py",
    "tests/chronos/test_chronos_r2_effects_v2.py",
    "tests/council/test_real_data_result_governance_v1.py",
    "tests/council/test_robin_autonomous_lab_governance.py",
    "tests/council/test_robin_council_os_v3.py",
}
ESTABLISHED_PROJECTION_PATHS = SCHEDULE_PROJECTION_PATHS | {
    ".github/workflows/prospective-deep-scheduler.yml",
    "RUNBOOK.md",
    ESTABLISHED_MANIFEST,
    ESTABLISHED_SOURCE,
    "docs/prospective-observatory/OBSERVATORY-OPERATIONS.md",
    "tests/activation/test_migration_path_neutralization.py",
    "tests/jalon12/test_workflows_prospective.py",
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


def test_schedule_reliability_overlay_preserves_parent_authority_and_budgets() -> None:
    parent = _load(MANIFEST)
    overlay = _load(SCHEDULE_MANIFEST)
    assert _lf_sha256(MANIFEST) == (
        "98b1538384f942d54535517e445ab2e9bf347e080b7f20bc92f3bb02aaede00a"
    )
    assert (
        set(overlay)
        == set(parent)
        == {
            "mission_id",
            "authorized_stages",
            "maximum_stage",
            "external_effects",
            "compute_budget",
            "time_budget",
            "source_hash",
            "expires_at",
        }
    )
    assert overlay["mission_id"] == SCHEDULE_MISSION_ID
    assert overlay["authorized_stages"] == parent["authorized_stages"]
    assert overlay["maximum_stage"] == parent["maximum_stage"] == "E3B"
    assert overlay["compute_budget"] == parent["compute_budget"] == 32_000
    assert overlay["time_budget"] == parent["time_budget"] == 2_592_000
    assert overlay["expires_at"] == parent["expires_at"] == "2026-11-03T23:59:59Z"
    assert overlay["source_hash"] == _lf_sha256(SCHEDULE_SOURCE)
    assert set(overlay["external_effects"]) == {
        "github_actions_schedule_hourly_minute_37",
        "github_actions_schedule_reuses_parent_two_hour_idempotent_slots",
        "github_actions_duplicate_closed_slot_zero_provider_dispatch",
        "github_actions_parent_rolling_budgets_unchanged",
    }


def test_schedule_reliability_overlay_has_one_writer_and_existing_review_keys() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][SCHEDULE_MISSION_ID]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C2", "A2"]
    assert mission["scale_ceiling"] == "E3B"
    assert mission["delivery_keys"] == {
        "governance": ["C2"],
        "platform": ["A2"],
    }
    allowed = set(mission["allowed_paths"])
    assert {
        ".github/workflows/92-robin-autonomous-lab.yml",
        SCHEDULE_MANIFEST,
        SCHEDULE_SOURCE,
        "tests/capture/test_recurring_real_data.py",
        "tests/capture/test_recurring_real_data_workflow.py",
    } <= allowed
    schema = _load("configs/agents/agent-report-schema-v3.json")
    assert SCHEDULE_MISSION_ID in schema["properties"]["mission_id"]["enum"]


def test_schedule_reliability_failure_authority_projection_and_review_are_bound() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}

    failure = claims[SCHEDULE_FAILURE_CLAIM_ID]
    assert failure["status"] == "VERIFIED"
    assert failure["workflow_id"] == 374_470_410
    assert failure["main_revision"] == "9b5afa27a039c0434934fda6f951102f555481d9"
    assert failure["missing_occurrences_utc"] == [
        "2026-10-04T10:17:00Z",
        "2026-10-04T12:17:00Z",
        "2026-10-04T14:17:00Z",
    ]
    assert failure["materialized_run_count"] == 0
    assert failure["provider_http_requests_new"] == failure["provider_credits_new"] == 0
    assert failure["r2_reads_new"] == failure["r2_writes_new"] == 0
    assert failure["historical_http_accounted"] == 16
    assert failure["historical_credit_accounted"] == 34

    authority = claims[SCHEDULE_AUTHORIZATION_CLAIM_ID]
    assert authority["status"] == "VERIFIED"
    assert authority["hash"] == _lf_sha256(SCHEDULE_MANIFEST)
    assert authority["source_hash"] == _lf_sha256(SCHEDULE_SOURCE)
    assert authority["parent_manifest_hash"] == (
        "98b1538384f942d54535517e445ab2e9bf347e080b7f20bc92f3bb02aaede00a"
    )
    assert authority["provider_http_budget_increment"] == 0
    assert authority["provider_credit_budget_increment"] == 0

    projection = claims[SCHEDULE_PROJECTION_CLAIM_ID]
    assert projection["status"] == "VERIFIED"
    assert projection["successor_of"] == ("GOV.ENGINEERING.ROBIN_AUTONOMOUS_LAB.PROJECTION.V1.005")
    assert set(projection["artifact_hashes"]) == SCHEDULE_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()

    review = claims[SCHEDULE_REVIEW_CLAIM_ID]
    assert review["status"] == "VERIFIED"
    assert (
        review["candidate_engineering_projection_sha256"]
        == projection["engineering_projection_sha256"]
    )
    assert review["p0_findings"] == review["p1_findings"] == 0
    report_path = "reports/council/robin-autonomous-lab-final-review-v1.json"
    assert review["hash"] == _lf_sha256(report_path)
    assert review["artifact_hashes"] == {report_path: _lf_sha256(report_path)}
    review_canonical = json.dumps(
        review["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert review["engineering_projection_sha256"] == hashlib.sha256(review_canonical).hexdigest()
    assert review["successor_of"] == "GOV.REVIEW.ROBIN_AUTONOMOUS_LAB.FINAL.V1.005"
    report = _load(report_path)
    assert report["mission_id"] == SCHEDULE_MISSION_ID


def test_schedule_reliability_records_failure_redesign_and_release_in_order() -> None:
    records = _ledger()
    by_id = {record["decision_id"]: record for record in records}
    failure = by_id[SCHEDULE_FAILURE_DECISION_ID]
    redesign = by_id[SCHEDULE_REDESIGN_DECISION_ID]
    release = by_id[SCHEDULE_RELEASE_DECISION_ID]
    assert failure["record_type"] == "FAILURE"
    assert failure["decision"] == "FAIL_AND_REDESIGN"
    assert failure["context"]["current_stage"] == "E1"
    assert failure["context"]["maximum_authority_stage"] == "E3B"
    assert redesign["record_type"] == "REDESIGN"
    assert redesign["decision"] == "PASS_AND_HOLD"
    assert release["record_type"] == "DECISION"
    assert release["decision"] == "PASS_AND_HOLD"
    assert redesign["previous_hash"] == failure["hash"]
    assert release["previous_hash"] == redesign["hash"]
    assert release["context"]["writer"] == "C0"
    assert release["context"]["writer_count"] == 1
    assert release["context"]["branch"] == "codex/robin-schedule-reliability-v1"
    assert release["context"]["head"] == "9b5afa27a039c0434934fda6f951102f555481d9"
    assert release["context"]["pr"] == "86"
    assert release["context"]["observed_external_effects"] == {
        "provider_http_requests_new": 0,
        "provider_credits_new": 0,
        "r2_reads_new": 0,
        "r2_writes_new": 0,
        "public_artifacts_new": 0,
        "purchases": 0,
        "bets": 0,
    }
    for record in (failure, redesign, release):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    graph = _load("reports/evidence/evidence-graph.json")
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert decisions[SCHEDULE_FAILURE_DECISION_ID]["ledger_record_hash"] == failure["hash"]
    assert decisions[SCHEDULE_REDESIGN_DECISION_ID]["ledger_record_hash"] == redesign["hash"]
    assert decisions[SCHEDULE_RELEASE_DECISION_ID]["ledger_record_hash"] == release["hash"]


def test_established_scheduler_manifest_has_exact_successor_authority() -> None:
    parent = _load(MANIFEST)
    successor = _load(ESTABLISHED_MANIFEST)
    assert set(successor) == set(parent)
    assert successor["mission_id"] == ESTABLISHED_MISSION_ID
    assert successor["authorized_stages"] == parent["authorized_stages"]
    assert successor["maximum_stage"] == parent["maximum_stage"] == "E3B"
    assert successor["compute_budget"] == parent["compute_budget"] == 32_000
    assert successor["time_budget"] == parent["time_budget"] == 2_592_000
    assert successor["expires_at"] == parent["expires_at"] == "2026-11-03T23:59:59Z"
    assert successor["source_hash"] == _lf_sha256(ESTABLISHED_SOURCE)
    assert set(successor["external_effects"]) == {
        "github_actions_established_workflow_id_321915839",
        "github_actions_schedule_hourly_minute_13",
        "github_actions_prior_workflow_id_374470410_disabled",
        "github_actions_schedule_reuses_parent_two_hour_idempotent_slots",
        "github_actions_parent_rolling_budgets_unchanged",
    }


def test_established_scheduler_has_one_writer_and_existing_review_keys() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][ESTABLISHED_MISSION_ID]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C2", "A2", "A3"]
    assert mission["scale_ceiling"] == "E3B"
    assert mission["delivery_keys"] == {
        "governance": ["C2"],
        "platform": ["A2", "A3"],
    }
    assert {
        ".github/workflows/prospective-deep-scheduler.yml",
        ".github/workflows/92-robin-autonomous-lab.yml",
        ESTABLISHED_MANIFEST,
        ESTABLISHED_SOURCE,
        "tests/capture/test_recurring_real_data_workflow.py",
    } <= set(mission["allowed_paths"])
    schema = _load("configs/agents/agent-report-schema-v3.json")
    assert ESTABLISHED_MISSION_ID in schema["properties"]["mission_id"]["enum"]


def test_established_scheduler_failure_history_and_authority_are_exact() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}

    failure = claims[ESTABLISHED_SECOND_FAILURE_CLAIM_ID]
    assert failure["status"] == "VERIFIED"
    assert failure["workflow_id"] == 374_470_410
    assert failure["main_revision"] == "2c8cfdd00461b35058dda573e4c64a3cb36711ee"
    assert failure["missing_occurrences_utc"] == [
        "2026-10-04T17:37:00Z",
        "2026-10-04T18:37:00Z",
    ]
    assert failure["materialized_run_count"] == 0
    assert failure["provider_http_requests_new"] == failure["provider_credits_new"] == 0
    assert failure["r2_reads_new"] == failure["r2_writes_new"] == 0

    history = claims[ESTABLISHED_HISTORY_CLAIM_ID]
    assert history["status"] == "VERIFIED"
    assert history["workflow_id"] == 321_915_839
    assert history["workflow_path"] == ".github/workflows/prospective-deep-scheduler.yml"
    assert history["historical_schedule_run_count"] == 139
    assert history["verified_reference_run_ids"] == [
        31_234_773_039,
        31_311_550_636,
        31_322_020_695,
    ]
    assert history["historical_cron"] == "13 * * * *"

    authority = claims[ESTABLISHED_AUTHORIZATION_CLAIM_ID]
    assert authority["status"] == "VERIFIED"
    assert authority["hash"] == _lf_sha256(ESTABLISHED_MANIFEST)
    assert authority["source_hash"] == _lf_sha256(ESTABLISHED_SOURCE)
    assert authority["parent_manifest_hash"] == _lf_sha256(MANIFEST)
    assert authority["schedule_overlay_manifest_hash"] == _lf_sha256(SCHEDULE_MANIFEST)
    assert authority["provider_http_budget_increment"] == 0
    assert authority["provider_credit_budget_increment"] == 0

    format_failure = claims[ESTABLISHED_FORMAT_FAILURE_CLAIM_ID]
    assert format_failure["status"] == "VERIFIED"
    assert format_failure["github_run_id"] == 37_228_983_739
    assert format_failure["github_job_id"] == 111_514_447_832
    assert format_failure["affected_files"] == [
        "tests/capture/test_recurring_real_data_workflow.py"
    ]
    assert format_failure["provider_http_requests_new"] == 0
    assert format_failure["provider_credits_new"] == 0

    ledger_assertion_failure = claims[ESTABLISHED_LEDGER_ASSERTION_FAILURE_CLAIM_ID]
    assert ledger_assertion_failure["status"] == "VERIFIED"
    assert ledger_assertion_failure["failed_tests"] == 1
    assert ledger_assertion_failure["passed_tests"] == 72
    assert ledger_assertion_failure["affected_files"] == [
        "tests/council/test_robin_autonomous_lab_governance.py"
    ]
    assert ledger_assertion_failure["provider_http_requests_new"] == 0
    assert ledger_assertion_failure["provider_credits_new"] == 0


def test_established_scheduler_projection_and_independent_review_are_bound() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    projection = claims[ESTABLISHED_PROJECTION_CLAIM_ID]
    assert projection["status"] == "VERIFIED"
    assert projection["successor_of"] == ("GOV.ENGINEERING.ROBIN_AUTONOMOUS_LAB.PROJECTION.V1.008")
    assert set(projection["artifact_hashes"]) == ESTABLISHED_PROJECTION_PATHS
    canonical = json.dumps(
        projection["artifact_hashes"], sort_keys=True, separators=(",", ":")
    ).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()

    review = claims[ESTABLISHED_REVIEW_CLAIM_ID]
    report_path = "reports/council/robin-autonomous-lab-established-scheduler-final-review-v1.json"
    assert review["status"] == "VERIFIED"
    assert (
        review["candidate_engineering_projection_sha256"]
        == (projection["engineering_projection_sha256"])
    )
    assert review["p0_findings"] == review["p1_findings"] == 0
    assert review["hash"] == _lf_sha256(report_path)
    assert review["successor_of"] == "GOV.REVIEW.ROBIN_AUTONOMOUS_LAB.FINAL.V1.008"
    report = _load(report_path)
    assert report["mission_id"] == ESTABLISHED_MISSION_ID


def test_established_scheduler_records_second_failure_redesign_and_release() -> None:
    records = _ledger()
    by_id = {record["decision_id"]: record for record in records}
    failure = by_id[ESTABLISHED_FAILURE_DECISION_ID]
    redesign = by_id[ESTABLISHED_REDESIGN_DECISION_ID]
    initial_release = by_id["RCV3-20261004-234"]
    format_failure = by_id[ESTABLISHED_FORMAT_FAILURE_DECISION_ID]
    format_release = by_id["RCV3-20261004-236"]
    ledger_assertion_failure = by_id[ESTABLISHED_LEDGER_ASSERTION_FAILURE_DECISION_ID]
    release = by_id[ESTABLISHED_RELEASE_DECISION_ID]
    assert failure["record_type"] == "FAILURE"
    assert failure["decision"] == "FAIL_AND_REDESIGN"
    assert failure["context"]["similar_failure_ordinal"] == 2
    assert failure["context"]["current_stage"] == "E1"
    assert redesign["record_type"] == "REDESIGN"
    assert redesign["decision"] == "PASS_AND_HOLD"
    assert format_failure["record_type"] == "FAILURE"
    assert format_failure["decision"] == "PASS_AND_HOLD"
    assert format_release["record_type"] == "DECISION"
    assert format_release["decision"] == "PASS_AND_HOLD"
    assert ledger_assertion_failure["record_type"] == "FAILURE"
    assert ledger_assertion_failure["decision"] == "PASS_AND_HOLD"
    assert release["record_type"] == "DECISION"
    assert release["decision"] == "PASS_AND_HOLD"
    assert redesign["previous_hash"] == failure["hash"]
    assert initial_release["previous_hash"] == redesign["hash"]
    assert format_failure["previous_hash"] == initial_release["hash"]
    assert format_release["previous_hash"] == format_failure["hash"]
    assert ledger_assertion_failure["previous_hash"] == format_release["hash"]
    assert release["previous_hash"] == ledger_assertion_failure["hash"]
    assert release["context"]["writer"] == "C0"
    assert release["context"]["writer_count"] == 1
    assert release["context"]["branch"] == "codex/robin-established-scheduler-v1"
    assert release["context"]["head"] == "4249a2ceda4d927dbafbe8b54ebd83b8245c3b4a"
    assert release["context"]["pr"] == "87"
    for record in (
        failure,
        redesign,
        initial_release,
        format_failure,
        format_release,
        ledger_assertion_failure,
        release,
    ):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    decisions = {
        node["decision_id"]: node
        for node in _load("reports/evidence/evidence-graph.json")["decision_nodes"]
    }
    assert decisions[ESTABLISHED_FAILURE_DECISION_ID]["ledger_record_hash"] == failure["hash"]
    assert decisions[ESTABLISHED_REDESIGN_DECISION_ID]["ledger_record_hash"] == redesign["hash"]
    assert (
        decisions[ESTABLISHED_FORMAT_FAILURE_DECISION_ID]["ledger_record_hash"]
        == (format_failure["hash"])
    )
    assert (
        decisions[ESTABLISHED_LEDGER_ASSERTION_FAILURE_DECISION_ID]["ledger_record_hash"]
        == ledger_assertion_failure["hash"]
    )
    assert decisions[ESTABLISHED_RELEASE_DECISION_ID]["ledger_record_hash"] == release["hash"]


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


def test_trigger_recovery_overlay_preserves_parent_budgets_and_exact_source() -> None:
    mission_id = "ROBIN_AUTONOMOUS_LAB_TRIGGER_RECOVERY_20261005"
    manifest_path = "configs/execution/robin-autonomous-lab-trigger-recovery-20261005.json"
    source_path = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-2026-10-05.md"
    parent = _load(MANIFEST)
    manifest = _load(manifest_path)
    assert (
        set(manifest)
        == set(parent)
        == {
            "mission_id",
            "authorized_stages",
            "maximum_stage",
            "external_effects",
            "compute_budget",
            "time_budget",
            "source_hash",
            "expires_at",
        }
    )
    assert manifest["mission_id"] == mission_id
    assert manifest["authorized_stages"] == parent["authorized_stages"]
    assert manifest["maximum_stage"] == parent["maximum_stage"] == "E3B"
    assert manifest["compute_budget"] == parent["compute_budget"] == 32_000
    assert manifest["time_budget"] == parent["time_budget"] == 2_592_000
    assert manifest["expires_at"] == parent["expires_at"] == "2026-11-03T23:59:59Z"
    assert manifest["source_hash"] == _lf_sha256(source_path)
    assert _lf_sha256(manifest_path) == (
        "b4752462dd798014b5930efca231caba36dea76e1b192b854d581fea2791d55b"
    )
    assert set(manifest["external_effects"]) == {
        "github_actions_manual_bootstrap_provider_free_only",
        "github_actions_workflow_dispatch_probe_max_2_automatic_hops",
        "github_actions_workflow_dispatch_recurring_self_relay",
        "github_actions_environment_robin_autonomous_relay_v1_wait_timer_60_minutes_main_only_no_secrets",
        "github_actions_control_jobs_actions_write_without_provider_or_r2_secrets",
        "github_actions_capture_actions_read_with_scoped_existing_secrets",
        "github_actions_schedule_watchdog_provider_secret_r2_zero_same_relay_dispatch_max_1_if_none_queued_or_in_progress",
        "github_actions_reuses_parent_two_hour_idempotent_slots",
        "github_actions_duplicate_closed_slot_zero_provider_dispatch",
        "github_actions_parent_rolling_budgets_unchanged",
        "provider_accounting_conservative_baseline_requests_21_credits_44_no_reset",
    }


def test_trigger_recovery_matrix_has_one_writer_without_new_provider_authority() -> None:
    mission_id = "ROBIN_AUTONOMOUS_LAB_TRIGGER_RECOVERY_20261005"
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][mission_id]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C2", "C4", "A2", "A3"]
    assert mission["scale_ceiling"] == "E3B"
    assert mission["delivery_keys"] == {
        "governance": ["C2"],
        "security": ["C4"],
        "platform": ["A2", "A3"],
    }
    assert {
        ".github/workflows/prospective-deep-scheduler.yml",
        "scripts/run_recurring_real_data.py",
        "src/robin/capture/recurring_real_data.py",
        "reports/evidence/robin-autonomous-lab-run-37231859661-public-receipt.json",
        "configs/execution/robin-autonomous-lab-trigger-recovery-v2-20261005.json",
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-V2-2026-10-05.md",
        "reports/evidence/robin-autonomous-lab-run-37245531093-public-receipt.json",
    } <= set(mission["allowed_paths"])
    authority = matrix["authorization"]
    for suffix in ("delivery", "effect_budget", "ordering", "source_boundary"):
        assert f"robin_autonomous_lab_trigger_recovery_20261005_{suffix}" in authority
    assert mission_id not in authority["provider_calls"]
    schema = _load("configs/agents/agent-report-schema-v3.json")
    assert mission_id in schema["properties"]["mission_id"]["enum"]


def test_trigger_recovery_v2_preserves_limits_and_advances_only_accounting() -> None:
    manifest_path = "configs/execution/robin-autonomous-lab-trigger-recovery-v2-20261005.json"
    source_path = "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-V2-2026-10-05.md"
    predecessor = _load("configs/execution/robin-autonomous-lab-trigger-recovery-20261005.json")
    manifest = _load(manifest_path)
    assert set(manifest) == set(predecessor)
    for field in (
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "compute_budget",
        "time_budget",
        "expires_at",
    ):
        assert manifest[field] == predecessor[field]
    assert manifest["source_hash"] == _lf_sha256(source_path)
    assert _lf_sha256(manifest_path) == (
        "4c150973fc3d486e3738f80716019839ac2c4126644849d336e267e6929e6d87"
    )
    assert set(manifest["external_effects"]) == {
        "successor_of_trigger_recovery_manifest_b4752462dd798014b5930efca231caba36dea76e1b192b854d581fea2791d55b",
        "github_actions_manual_bootstrap_provider_free_only",
        "github_actions_workflow_dispatch_probe_max_2_automatic_hops",
        "github_actions_workflow_dispatch_recurring_self_relay",
        "github_actions_environment_robin_autonomous_relay_v1_wait_timer_60_minutes_main_only_no_secrets",
        "github_actions_control_jobs_actions_write_without_provider_or_r2_secrets",
        "github_actions_capture_actions_read_with_scoped_existing_secrets",
        "github_actions_schedule_watchdog_provider_secret_r2_zero_same_relay_dispatch_max_1_if_none_active",
        "github_actions_reuses_parent_two_hour_idempotent_slots",
        "github_actions_duplicate_closed_slot_zero_provider_dispatch",
        "github_actions_parent_rolling_budgets_unchanged",
        "provider_accounting_conservative_baseline_requests_26_credits_54_no_reset",
    }


def test_trigger_recovery_real_failure_and_conservative_accounting_are_bound() -> None:
    receipt_path = "reports/evidence/robin-autonomous-lab-run-37231859661-public-receipt.json"
    receipt = _load(receipt_path)
    assert receipt["github_run_id"] == "37231859661"
    assert receipt["status"] == "REAL_DATA_FAILED"
    assert receipt["validated_capture_count"] == 0
    assert receipt["provider_requests_new"] == 0
    assert receipt["provider_requests_reserved"] == 5
    assert receipt["provider_credits_reserved"] == 10
    assert receipt["lifetime_requests"] == 21
    assert receipt["lifetime_credits"] == 44
    assert receipt["display_data_role"] == "CARRY_FORWARD_STALE"
    assert receipt["private_report_r2_status"] == "VERIFIED"

    claims = {
        claim["claim_id"]: claim
        for claim in _load("reports/evidence/evidence-graph.json")["claims"]
    }
    failure = claims["RUNTIME.ROBIN.AUTONOMOUS_LAB.DNS.CLOCK.ORDERING.FAILURE.V1.001"]
    assert failure["status"] == "VERIFIED"
    assert failure["github_run_id"] == 37_231_859_661
    assert failure["artifact_id"] == 11_314_001_640
    assert failure["diagnostic_code"] == "RECURRING_DNS_RESOLUTION_EXPIRED"
    assert failure["provider_requests_new"] == 0
    assert failure["lifetime_requests_conservative"] == 21
    assert failure["lifetime_credits_conservative"] == 44
    assert failure["provider_credits_actually_charged"] == "UNKNOWN"
    assert failure["ai_credits"] == "NOT_MEASURED"
    assert failure["hash"] == _lf_sha256(receipt_path)

    authority = claims["GOV.AUTHORIZATION.ROBIN_AUTONOMOUS_LAB.TRIGGER_RECOVERY.V1.001"]
    assert authority["hash"] == _lf_sha256(
        "configs/execution/robin-autonomous-lab-trigger-recovery-20261005.json"
    )
    assert authority["source_hash"] == _lf_sha256(
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-2026-10-05.md"
    )
    assert authority["provider_http_budget_increment"] == 0
    assert authority["provider_credit_budget_increment"] == 0


def test_trigger_recovery_late_run_is_preserved_and_advances_conservative_baseline() -> None:
    receipt_path = "reports/evidence/robin-autonomous-lab-run-37245531093-public-receipt.json"
    receipt = _load(receipt_path)
    assert receipt["github_run_id"] == "37245531093"
    assert receipt["status"] == "REAL_DATA_FAILED"
    assert receipt["validated_capture_count"] == 0
    assert receipt["provider_requests_new"] == 0
    assert receipt["provider_requests_reserved"] == 5
    assert receipt["provider_credits_reserved"] == 10
    assert receipt["rolling_24h_requests"] == 10
    assert receipt["rolling_24h_credits"] == 20
    assert receipt["lifetime_requests"] == 26
    assert receipt["lifetime_credits"] == 54
    assert receipt["display_data_role"] == "CARRY_FORWARD_STALE"
    assert receipt["private_report_r2_status"] == "VERIFIED"

    claims = {
        claim["claim_id"]: claim
        for claim in _load("reports/evidence/evidence-graph.json")["claims"]
    }
    failure = claims["RUNTIME.ROBIN.AUTONOMOUS_LAB.DNS.CLOCK.ORDERING.FAILURE.V1.002"]
    assert failure["github_run_id"] == 37_245_531_093
    assert failure["artifact_id"] == 11_319_146_929
    assert failure["provider_requests_new"] == 0
    assert failure["lifetime_requests_conservative"] == 26
    assert failure["lifetime_credits_conservative"] == 54
    assert failure["provider_credits_actually_charged"] == "UNKNOWN"
    assert failure["ai_credits"] == "NOT_MEASURED"
    assert failure["hash"] == _lf_sha256(receipt_path)

    authority = claims["GOV.AUTHORIZATION.ROBIN_AUTONOMOUS_LAB.TRIGGER_RECOVERY.V1.003"]
    assert authority["hash"] == _lf_sha256(
        "configs/execution/robin-autonomous-lab-trigger-recovery-v2-20261005.json"
    )
    assert authority["source_hash"] == _lf_sha256(
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-V2-2026-10-05.md"
    )
    assert authority["provider_http_conservative_baseline"] == 26
    assert authority["provider_credit_conservative_baseline"] == 54


def test_trigger_recovery_records_primary_failure_and_authority_append_only() -> None:
    records = _ledger()
    by_id = {record["decision_id"]: record for record in records}
    failure = by_id["RCV3-20261005-239"]
    authority = by_id["RCV3-20261005-240"]
    assert failure["record_type"] == "FAILURE"
    assert failure["decision"] == "FAIL_AND_STOP"
    assert failure["context"]["route_scope"] == "SCHEDULE_AS_PRIMARY_COLLECTION_CLOCK"
    assert authority["record_type"] == "MISSION_AUTHORIZED"
    assert authority["decision"] == "PASS_AND_HOLD"
    assert authority["context"]["writer"] == "C0"
    assert authority["context"]["writer_count"] == 1
    assert authority["context"]["branch"] == "codex/robin-trigger-recovery-v1"
    assert authority["context"]["head"] == "563c37901647e5b3cce29a141cea153dabbe5941"
    assert authority["context"]["pr"] == "PENDING"
    assert authority["previous_hash"] == failure["hash"]
    for record in (failure, authority):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    graph = _load("reports/evidence/evidence-graph.json")
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert decisions["RCV3-20261005-239"]["ledger_record_hash"] == failure["hash"]
    assert decisions["RCV3-20261005-240"]["ledger_record_hash"] == authority["hash"]
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert set(edges) >= {f"EDGE.{number}" for number in range(913, 919)}


def test_trigger_recovery_v2_records_late_failure_and_successor_authority() -> None:
    records = _ledger()
    by_id = {record["decision_id"]: record for record in records}
    failure = by_id["RCV3-20261005-241"]
    authority = by_id["RCV3-20261005-242"]
    assert failure["record_type"] == "FAILURE"
    assert failure["decision"] == "FAIL_AND_REDESIGN"
    assert failure["context"]["similar_failure_ordinal"] == 2
    assert failure["context"]["provider_http_baseline_after"] == 26
    assert failure["context"]["provider_credit_baseline_after"] == 54
    assert authority["record_type"] == "MISSION_AUTHORIZED"
    assert authority["decision"] == "PASS_AND_HOLD"
    assert authority["context"]["writer"] == "C0"
    assert authority["context"]["writer_count"] == 1
    assert authority["context"]["historical_provider_http_requests_conservative"] == 26
    assert authority["context"]["historical_provider_credits_conservative"] == 54
    assert authority["previous_hash"] == failure["hash"]
    for record in (failure, authority):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    graph = _load("reports/evidence/evidence-graph.json")
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert decisions["RCV3-20261005-241"]["ledger_record_hash"] == failure["hash"]
    assert decisions["RCV3-20261005-242"]["ledger_record_hash"] == authority["hash"]
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert set(edges) >= {f"EDGE.{number}" for number in range(919, 925)}


def test_trigger_recovery_provider_free_probe_opens_only_e2_after_two_hops() -> None:
    receipt_path = "reports/evidence/robin-autonomous-relay-probe-20261005.json"
    receipt = _load(receipt_path)
    generation = "4c150973fc3d486e3738f80716019839ac2c4126644849d336e267e6929e6d87"
    assert receipt["main_sha"] == "b5352127f1ebba653bf42d37c5a93319159f4569"
    assert receipt["generation"] == generation
    assert receipt["environment"] == {
        "name": "robin-autonomous-relay-v1",
        "created_at_utc": "2026-10-05T02:33:41Z",
        "wait_timer_minutes": 1,
        "protection_rule_types": ["branch_policy", "wait_timer"],
        "protected_branches": False,
        "custom_branch_policies": True,
        "branch_policies": [{"name": "main", "type": "branch"}],
        "secret_count": 0,
        "variable_count": 0,
        "repository_activation_variable_present": False,
    }
    assert [run["run_id"] for run in receipt["runs"]] == [
        37_255_909_445,
        37_255_920_150,
        37_256_000_103,
    ]
    assert [run["actor"] for run in receipt["runs"][1:]] == [
        "github-actions[bot]",
        "github-actions[bot]",
    ]
    assert all(run["capture_conclusion"] == "skipped" for run in receipt["runs"])
    assert receipt["observations"] == {
        "distinct_run_count": 3,
        "automatic_relay_hops": 2,
        "automatic_relay_actors": ["github-actions[bot]", "github-actions[bot]"],
        "sequence_3_count": 0,
        "active_generation_run_count_after_probe": 0,
        "capture_jobs_executed": 0,
        "provider_http_requests_new": 0,
        "provider_credits_new": 0,
        "r2_reads_new": 0,
        "r2_writes_new": 0,
        "purchases": 0,
        "bets": 0,
        "ai_credits": "NOT_MEASURED",
    }

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    probe = claims["GOV.SCHEDULER.ROBIN_AUTONOMOUS_LAB.RELAY.PROBE.V1.001"]
    assert probe["hash"] == _lf_sha256(receipt_path)
    assert probe["automatic_run_ids"] == [37_255_920_150, 37_256_000_103]
    assert probe["provider_http_requests_new"] == 0
    assert probe["provider_credits_new"] == 0

    records = _ledger()
    by_id = {record["decision_id"]: record for record in records}
    finished = by_id["RCV3-20261005-249"]
    scale = by_id["RCV3-20261005-250"]
    assert finished["record_type"] == "STAGE_FINISHED"
    assert finished["decision"] == "PASS_AND_HOLD"
    assert scale["record_type"] == "DECISION"
    assert scale["decision"] == "PASS_AND_SCALE"
    assert scale["context"]["current_stage"] == "E1"
    assert scale["context"]["opened_stage"] == "E2"
    assert scale["context"]["generation"] == generation
    assert scale["context"]["historical_provider_http_requests_conservative"] == 26
    assert scale["context"]["historical_provider_credits_conservative"] == 54
    assert scale["previous_hash"] == finished["hash"]
    for record in (finished, scale):
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]

    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert decisions["RCV3-20261005-249"]["ledger_record_hash"] == finished["hash"]
    assert decisions["RCV3-20261005-250"]["ledger_record_hash"] == scale["hash"]
    edges = {edge["edge_id"]: edge for edge in graph["edges"]}
    assert set(edges) >= {f"EDGE.{number}" for number in range(943, 948)}


def test_automatic_capture_replay_capture_receipts_close_only_observed_e2() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    captures = claims["DATA.ROBIN.AUTONOMOUS_LAB.RECURRING_CAPTURES.V1.002"]
    view = claims["DATA.ROBIN.AUTONOMOUS_LAB.RECURRING_VIEW.V1.002"]
    consumption = claims["GOV.ROBIN.AUTONOMOUS_LAB.RECURRING_CONSUMPTION.V1.002"]
    runs = captures["automatic_runs"]
    assert len(runs) == 3
    assert [run["sequence"] for run in runs] == [2, 3, 4]
    assert len({run["run_id"] for run in runs}) == 3
    generation = _lf_sha256(
        "configs/execution/robin-autonomous-lab-trigger-recovery-v2-20261005.json"
    )
    for run in runs:
        assert run["event"] == "workflow_dispatch"
        assert run["actor"] == run["triggering_actor"] == "github-actions[bot]"
        assert run["conclusion"] == "success"
        assert run["run_attempt"] == 1
        assert run["generation"] == generation
        assert run["chain_id"] == "37262108579"
        assert run["head_sha"] == "8f21c7c1be5f18721de4859acbd84751e072183f"
        assert run["successor_created_at_utc"] <= run["relay_completed_at_utc"]
        assert run["relay_completed_at_utc"] <= run["capture_started_at_utc"]
    paths = [
        f"reports/evidence/robin-autonomous-lab-run-{run['run_id']}-public-receipt.json"
        for run in runs
    ]
    mission = _load("configs/agents/mission-activation-matrix-v3.json")["missions"][
        "ROBIN_AUTONOMOUS_LAB_TRIGGER_RECOVERY_20261005"
    ]
    assert set(paths) <= set(mission["allowed_paths"])
    receipts = [_load(path) for path in paths]
    first, replay, last = receipts
    assert [r["delivery_github_run_id"] for r in receipts] == [str(run["run_id"]) for run in runs]
    assert [r["github_run_id"] for r in receipts] == [
        str(runs[0]["run_id"]),
        str(runs[0]["run_id"]),
        str(runs[2]["run_id"]),
    ]
    assert [r["replayed_existing_slot"] for r in receipts] == [False, True, False]
    assert [r["provider_requests_new"] for r in receipts] == [5, 0, 5]
    for field in (
        "slot_start_utc",
        "capture_times_utc",
        "private_report_r2_key",
        "private_report_r2_sha256",
        "relay_lineage",
        "csv_sha256",
        "lifetime_requests",
        "lifetime_credits",
    ):
        assert first[field] == replay[field]
    assert first["slot_start_utc"] < last["slot_start_utc"]
    for field in ("private_report_r2_key", "private_report_r2_sha256"):
        assert first[field] != last[field]
    assert last["lifetime_requests"] == first["lifetime_requests"] + 5
    assert last["lifetime_credits"] == first["lifetime_credits"] + 10
    for receipt in receipts:
        assert receipt["mission_id"] == MISSION_ID
        assert receipt["status"] in {"REAL_DATA_COMPLETE", "REAL_DATA_PARTIAL"}
        assert receipt["validated_capture_count"] == 5
        assert receipt["incomplete_branch_count"] == 0
        assert receipt["market_branch_coverage"] == {"h2h": 5, "totals": 5}
        assert receipt["display_data_role"] == "CURRENT"
        assert receipt["row_count"] == receipt["display_row_count"] > 0
        assert receipt["private_report_r2_status"] == "VERIFIED"
        assert receipt["credit_bound_valid"] is True
        assert receipt["provider_requests_reserved"] == 5
        assert receipt["provider_credits_reserved"] == 10
        assert receipt["rolling_24h_requests"] <= 140
        assert receipt["rolling_24h_credits"] <= 280
        assert receipt["rolling_30d_requests"] <= 4000
        assert receipt["rolling_30d_credits"] <= 8000
        for field in ("automatic_retries", "purchases", "real_bets", "backfills", "promotions"):
            assert receipt[field] == 0
    expected_hashes = {path: _lf_sha256(path) for path in paths}
    for claim in (captures, view, consumption):
        assert claim["status"] == "VERIFIED"
        assert claim["receipt_hashes"] == expected_hashes
        assert claims[claim["successor_of"]]["status"] == "PARTIAL"
        assert claim["stability_24h"] == "TO_OBSERVE"
    assert consumption["provider_http_requests_new"] == 10
    assert consumption["provider_credits_reserved_increment"] == 20
    assert consumption["provider_credits_actually_charged"] == "UNKNOWN"
    assert consumption["ai_credits"] == "NOT_MEASURED"

    projection = claims["GOV.ENGINEERING.ROBIN_AUTONOMOUS_LAB.PROJECTION.V1.015"]
    assert projection["artifact_path_count"] == 24
    assert projection["artifact_hashes"] == {
        path: _lf_sha256(path) for path in projection["artifact_hashes"]
    }
    review = claims["GOV.REVIEW.ROBIN_AUTONOMOUS_LAB.FINAL.V1.014"]
    assert (
        review["candidate_engineering_projection_sha256"]
        == projection["engineering_projection_sha256"]
    )
    assert review["hash"] == _lf_sha256(review["artifact"])
    assert review["p0_findings"] == review["p1_findings"] == 0
    decision = next(r for r in _ledger() if r["decision_id"] == "RCV3-20261005-253")
    assert decision["record_type"] == "STAGE_FINISHED"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["context"]["current_stage"] == "E2"
    assert decision["context"]["outcome"] == "AUTOMATIC_CAPTURE_REPLAY_CAPTURE_VERIFIED"
    assert decision["context"]["stability_24h"] == "TO_OBSERVE"
    assert decision["context"]["continuation"] == "E2_WITHIN_EXISTING_AUTHORITY"
    canonical = json.dumps(
        {key: value for key, value in decision.items() if key != "hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert decision["hash"] == hashlib.sha256(canonical).hexdigest()
    nodes = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert nodes[decision["decision_id"]]["ledger_record_hash"] == decision["hash"]
