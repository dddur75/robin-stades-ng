from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_REPRISE_COLLECTE_20261002"
CONTINUATION_MISSION_ID = "ROBIN_REPRISE_COLLECTE_20261002_CONTINUATION_V1"
SQLITE_CONTINUATION_MISSION_ID = "ROBIN_REPRISE_COLLECTE_20261002_CONTINUATION_V2"
MANDATE_SHA256 = "0a48756520b7f77f6c2d66d27e3b423d5f62d0468bd8b8607aa1cebf5f391d22"
CONTINUATION_SOURCE_SHA256 = "7896c7a87b9d686571d8c15cec2f62fefa63a7a7e2c3dca4fc093c7c455b6c42"
SQLITE_CONTINUATION_SOURCE_SHA256 = (
    "cb3d52256d483142e8f299b7839673eff3b8fd4c92008b7cde2eddd12047b387"
)
BASE_MAIN_SHA = "9b207cd1efd7f51ead29ff5b8c2709b6062fa763"
AUTHORIZATION_DECISION_ID = "RCV3-20261002-197"
CONTINUATION_AUTHORIZATION_DECISION_ID = "RCV3-20261002-198"
SQLITE_FAILURE_DECISION_ID = "RCV3-20261003-201"
SQLITE_CONTINUATION_AUTHORIZATION_DECISION_ID = "RCV3-20261003-202"
MATRIX_HASH_FAILURE_DECISION_ID = "RCV3-20261003-204"
SQLITE_PRECOMMIT_DECISION_ID = "RCV3-20261003-205"
SQLITE_EVIDENCE_FAILURE_DECISION_ID = "RCV3-20261003-206"
SQLITE_CORRECTED_PRECOMMIT_DECISION_ID = "RCV3-20261003-207"
AUTHORIZATION_CLAIM_ID = "GOV.AUTHORIZATION.ROBIN_REPRISE_COLLECTE.V1.001"
CONTINUATION_AUTHORIZATION_CLAIM_ID = "GOV.AUTHORIZATION.ROBIN_REPRISE_COLLECTE.CONTINUATION.V1.001"
SQLITE_CONTINUATION_AUTHORIZATION_CLAIM_ID = (
    "GOV.AUTHORIZATION.ROBIN_REPRISE_COLLECTE.CONTINUATION.V2.001"
)
SQLITE_FAILURE_CLAIM_ID = "GOV.CI.ROBIN_REPRISE_COLLECTE.SQLITE.URL.TEXTUAL.CONTRACT.FAILURE.V1.001"
SQLITE_PORTABILITY_CLAIM_ID = (
    "PORTABILITY.ROBIN_REPRISE_COLLECTE.SQLITE.URL.SEMANTIC.REGRESSION.V1.001"
)
MATRIX_HASH_FAILURE_CLAIM_ID = "GOV.CI.ROBIN_REPRISE_COLLECTE.MATRIX.HASH.PIN.DRIFT.V2.001"
SQLITE_EVIDENCE_FAILURE_CLAIM_ID = (
    "GOV.EVIDENCE.ROBIN_REPRISE_COLLECTE.V2.002.REVIEW.BINDING.FAILURE.V1.001"
)
SQLITE_EVIDENCE_CORRECTION_CLAIM_ID = (
    "GOV.EVIDENCE.ROBIN_REPRISE_COLLECTE.V2.003.REVIEW.BINDING.CORRECTION.V1.001"
)
SQLITE_PRECOMMIT_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REPRISE_COLLECTE.FINAL.V2.002"
SQLITE_FINAL_REVIEW_CLAIM_ID = "GOV.REVIEW.ROBIN_REPRISE_COLLECTE.FINAL.V2.003"
OLDER_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REPRISE_COLLECTE.PROJECTION.V1.003"
PREDECESSOR_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REPRISE_COLLECTE.PROJECTION.V2.001"
SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REPRISE_COLLECTE.PROJECTION.V2.002"
PROJECTION_CLAIM_ID = "GOV.ENGINEERING.ROBIN_REPRISE_COLLECTE.PROJECTION.V2.003"

EXPECTED_EFFECTS = [
    "git_remote_write_non_force",
    "github_pull_request_write",
    "github_merge_commit",
    "github_actions_observe",
    "github_actions_workflow_dispatch_exactly_once_after_merge",
    "github_actions_artifact_upload_encrypted",
    "provider_public_dns_resolution_exactly_once",
    "provider_secret_read_exactly_once",
    "provider_tcp_tls_connection_max_2",
    "provider_https_get_max_2",
    "provider_credit_consume_max_4",
    "r2_conditional_put_max_5",
    "r2_exact_key_get_max_3",
    "local_private_delivery_artifact_writes",
    "offline_replay_from_captured_bytes",
]

EXPECTED_CONTINUATION_EFFECTS = [
    "git_remote_write_non_force",
    "github_pull_request_write",
    "github_merge_commit",
    "github_actions_observe",
    "reuse_parent_runtime_authority_sha256_815788fb8ba61b21782797cd32d36a4b49a8b6d072610a59ba3295136750fdb2_without_expansion",
    "parent_and_continuation_workflow_dispatch_total_max_1_parent_baseline_0",
    "parent_and_continuation_provider_public_dns_resolution_total_max_1_parent_baseline_0",
    "parent_and_continuation_provider_secret_read_total_max_1_parent_baseline_0",
    "parent_and_continuation_provider_tcp_tls_connection_total_max_2_parent_baseline_0",
    "parent_and_continuation_provider_https_get_total_max_2_parent_baseline_0",
    "parent_and_continuation_provider_credit_consume_total_max_4_parent_baseline_0",
    "parent_and_continuation_r2_conditional_put_total_max_5_parent_baseline_0",
    "parent_and_continuation_r2_exact_key_get_total_max_3_parent_baseline_0",
    "local_private_delivery_artifact_writes_under_parent_runtime_authority",
    "offline_replay_from_parent_authorized_captured_bytes",
]

EXPECTED_SQLITE_CONTINUATION_EFFECTS = [
    "git_remote_write_non_force",
    "github_pull_request_write",
    "github_merge_commit",
    "github_actions_observe",
    "local_test_only_sqlalchemy_representation_compatibility_correction",
    "successor_runtime_effect_budget_increment_0",
    "reuse_parent_runtime_authority_sha256_815788fb8ba61b21782797cd32d36a4b49a8b6d072610a59ba3295136750fdb2_without_expansion",
    "parent_runtime_authority_not_reactivated_after_expiry",
    "corrective_push_family_budget_not_reset_one_remaining_after_rcv3_20261002_200",
    "parent_and_continuations_compute_budget_total_max_4000_not_reset",
    "parent_and_continuations_workflow_dispatch_total_max_1_parent_baseline_0",
    "parent_and_continuations_provider_public_dns_resolution_total_max_1_parent_baseline_0",
    "parent_and_continuations_provider_secret_read_total_max_1_parent_baseline_0",
    "parent_and_continuations_provider_tcp_tls_connection_total_max_2_parent_baseline_0",
    "parent_and_continuations_provider_https_get_total_max_2_parent_baseline_0",
    "parent_and_continuations_provider_credit_consume_total_max_4_parent_baseline_0",
    "parent_and_continuations_r2_conditional_put_total_max_5_parent_baseline_0",
    "parent_and_continuations_r2_exact_key_get_total_max_3_parent_baseline_0",
    "local_private_delivery_artifact_writes_under_parent_runtime_authority",
    "offline_replay_from_parent_authorized_captured_bytes",
]

EXPECTED_PATHS = [
    ".github/workflows/90-reprise-collecte-pilot.yml",
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/execution/reprise-collecte-code-attestation.json",
    "configs/execution/reprise-collecte-code-attestation.sig",
    "configs/execution/reprise-collecte-recipient-cert.pem",
    "configs/execution/reprise-collecte-20261002.json",
    "docs/superpowers/plans/2026-10-02-reprise-collecte-pilot.md",
    "reports/council/decision-ledger.jsonl",
    "reports/council/reprise-collecte-20261002-data-review-v3.json",
    "reports/council/reprise-collecte-20261002-final-review-v3.json",
    "reports/council/reprise-collecte-20261002-governance-review-v3.json",
    "reports/council/reprise-collecte-20261002-platform-review-v3.json",
    "reports/council/reprise-collecte-20261002-security-review-v3.json",
    "reports/evidence/evidence-graph.json",
    "scripts/run_reprise_collecte.py",
    "src/robin/capture/reprise_collecte.py",
    "tests/capture/test_reprise_collecte.py",
    "tests/capture/test_reprise_collecte_workflow.py",
    "tests/capture/test_run_reprise_collecte_cli.py",
    "tests/council/test_reprise_collecte_governance_v1.py",
    "tests/council/test_real_execution_bootstrap_governance.py",
    "tests/council/test_robin_council_os_v3.py",
]

EXPECTED_CONTINUATION_PATHS = [
    ".github/workflows/90-reprise-collecte-pilot.yml",
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/execution/reprise-collecte-code-attestation.json",
    "configs/execution/reprise-collecte-code-attestation.sig",
    "configs/execution/reprise-collecte-recipient-cert.pem",
    "configs/execution/reprise-collecte-20261002.json",
    "configs/execution/reprise-collecte-20261002-continuation-v1.json",
    "docs/superpowers/plans/2026-10-02-reprise-collecte-pilot.md",
    "reports/council/decision-ledger.jsonl",
    "reports/council/reprise-collecte-20261002-ci-baseline-review-v3.json",
    "reports/council/reprise-collecte-20261002-data-review-v3.json",
    "reports/council/reprise-collecte-20261002-final-review-v3.json",
    "reports/council/reprise-collecte-20261002-governance-review-v3.json",
    "reports/council/reprise-collecte-20261002-platform-review-v3.json",
    "reports/council/reprise-collecte-20261002-security-review-v3.json",
    "reports/evidence/evidence-graph.json",
    "scripts/run_reprise_collecte.py",
    "src/robin/capture/reprise_collecte.py",
    "tests/activation/historical_data_torrent_authority.py",
    "tests/activation/test_chronos_controlled_go_durable_seal_v1.py",
    "tests/activation/test_chronos_end_to_end_live_path_v1.py",
    "tests/activation/test_chronos_neon_controlled_idle_wake_readonly_v1.py",
    "tests/activation/test_chronos_neon_pure_readonly_preflight_v4.py",
    "tests/activation/test_chronos_production_bootstrap_v3.py",
    "tests/activation/test_chronos_runtime_bindings_v1.py",
    "tests/data_torrent/test_live_runtime_effect_accounting_v1.py",
    "tests/data_torrent/test_source_effect_lineage_v1.py",
    "tests/capture/test_reprise_collecte.py",
    "tests/capture/test_reprise_collecte_workflow.py",
    "tests/capture/test_run_reprise_collecte_cli.py",
    "tests/council/test_reprise_collecte_governance_v1.py",
    "tests/council/test_real_execution_bootstrap_governance.py",
    "tests/council/test_robin_council_os_v3.py",
]

EXPECTED_SQLITE_CONTINUATION_PATHS = [
    *EXPECTED_CONTINUATION_PATHS[:8],
    "configs/execution/reprise-collecte-20261002-continuation-v2.json",
    *EXPECTED_CONTINUATION_PATHS[8:16],
    "reports/council/reprise-collecte-20261002-sqlite-data-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-final-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-governance-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-platform-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-security-review-v3.json",
    *EXPECTED_CONTINUATION_PATHS[16:],
    "tests/jalon4/test_database_urls.py",
]

EXPECTED_PROJECTION_ADDITIONS: set[str] = set()

EXPECTED_SQLITE_PRECOMMIT_FILES = [
    "configs/agents/agent-report-schema-v3.json",
    "configs/agents/mission-activation-matrix-v3.json",
    "configs/execution/reprise-collecte-20261002-continuation-v2.json",
    "reports/council/decision-ledger.jsonl",
    "reports/council/reprise-collecte-20261002-sqlite-data-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-final-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-governance-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-platform-review-v3.json",
    "reports/council/reprise-collecte-20261002-sqlite-security-review-v3.json",
    "reports/evidence/evidence-graph.json",
    "tests/council/test_real_execution_bootstrap_governance.py",
    "tests/council/test_reprise_collecte_governance_v1.py",
    "tests/council/test_robin_council_os_v3.py",
    "tests/jalon4/test_database_urls.py",
]

EXPECTED_SQLITE_PRECOMMIT_EFFECTS = {
    "workflow_dispatches": 0,
    "provider_dns": 0,
    "provider_secret_reads": 0,
    "provider_tcp_tls_connections": 0,
    "provider_http_requests": 0,
    "provider_credits": 0,
    "r2_puts": 0,
    "r2_gets": 0,
    "purchases": 0,
    "real_captures": 0,
    "bets": 0,
    "git_non_force_pushes": 2,
    "pull_requests_created": 1,
    "merges": 0,
}

EXPECTED_SQLITE_V2_002_REVIEW_HASHES = {
    "data": "74f7e9412cd0b32884aec6860e82e5b59ca77eb830d85436ce40756579159d98",
    "security": "6afd5b86003cd6fcbf2645cf0aaaf684024538282cfbb035892ac3308f2b4b97",
    "governance": "77e89c819155bd6463aa110454f5828d684ff6c9c9deff792f6a4f634758c198",
    "platform": "0e56ae5a15e832817006d3e7401879d158e4b2a729924ac0d474fa955997419d",
    "final": "8896b22cb9ae4c1271d5a0fb2024bd55fad6e036ebe05f4bc7d3a15fb0477a20",
}


def _load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_manifest_bounds_the_owner_authorized_pilot_to_two_calls_and_four_credits() -> None:
    manifest = _load("configs/execution/reprise-collecte-20261002.json")

    assert manifest == {
        "mission_id": MISSION_ID,
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": EXPECTED_EFFECTS,
        "compute_budget": 4000,
        "time_budget": 7200,
        "source_hash": MANDATE_SHA256,
        "expires_at": "2026-10-03T18:27:48Z",
    }


def test_successor_is_non_runtime_and_reuses_the_parent_cumulative_budget() -> None:
    manifest = _load("configs/execution/reprise-collecte-20261002-continuation-v1.json")

    assert manifest == {
        "mission_id": CONTINUATION_MISSION_ID,
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": EXPECTED_CONTINUATION_EFFECTS,
        "compute_budget": 4000,
        "time_budget": 7200,
        "source_hash": CONTINUATION_SOURCE_SHA256,
        "expires_at": "2026-10-03T18:27:48Z",
    }
    assert (
        hashlib.sha256(
            (ROOT / "configs/execution/reprise-collecte-20261002.json").read_bytes()
        ).hexdigest()
        == "815788fb8ba61b21782797cd32d36a4b49a8b6d072610a59ba3295136750fdb2"
    )


def test_sqlite_successor_is_test_only_and_does_not_extend_runtime_authority() -> None:
    manifest = _load("configs/execution/reprise-collecte-20261002-continuation-v2.json")

    assert manifest == {
        "mission_id": SQLITE_CONTINUATION_MISSION_ID,
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": EXPECTED_SQLITE_CONTINUATION_EFFECTS,
        "compute_budget": 4000,
        "time_budget": 7200,
        "source_hash": SQLITE_CONTINUATION_SOURCE_SHA256,
        "expires_at": "2026-10-04T08:00:00Z",
    }
    assert (
        hashlib.sha256(
            (ROOT / "configs/execution/reprise-collecte-20261002.json").read_bytes()
        ).hexdigest()
        == "815788fb8ba61b21782797cd32d36a4b49a8b6d072610a59ba3295136750fdb2"
    )
    assert (
        hashlib.sha256(
            (ROOT / "configs/execution/reprise-collecte-20261002-continuation-v1.json").read_bytes()
        ).hexdigest()
        == "c79855b5953d94ea042438a8137d4b95e4dcb01e3441bdafa5cd2a740a471289"
    )


def test_successor_does_not_enter_the_signed_runtime_boundary() -> None:
    attestation = _load("configs/execution/reprise-collecte-code-attestation.json")
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    artifact_hashes = attestation["artifact_hashes"]
    continuation_path = "configs/execution/reprise-collecte-20261002-continuation-v1.json"
    sqlite_continuation_path = "configs/execution/reprise-collecte-20261002-continuation-v2.json"

    assert attestation["mission_id"] == MISSION_ID
    assert artifact_hashes["configs/execution/reprise-collecte-20261002.json"] == (
        "815788fb8ba61b21782797cd32d36a4b49a8b6d072610a59ba3295136750fdb2"
    )
    assert len(artifact_hashes) == 39
    assert continuation_path not in artifact_hashes
    assert sqlite_continuation_path not in artifact_hashes
    assert CONTINUATION_MISSION_ID not in matrix["authorization"]["provider_calls"]
    assert SQLITE_CONTINUATION_MISSION_ID not in matrix["authorization"]["provider_calls"]

    literal_runtime_paths = [
        ".github/workflows/90-reprise-collecte-pilot.yml",
        "src/robin/capture/reprise_collecte.py",
    ]
    for path in literal_runtime_paths:
        runtime_text = (ROOT / path).read_text(encoding="utf-8")
        assert MISSION_ID in runtime_text
        assert CONTINUATION_MISSION_ID not in runtime_text
        assert SQLITE_CONTINUATION_MISSION_ID not in runtime_text

    cli_text = (ROOT / "scripts/run_reprise_collecte.py").read_text(encoding="utf-8")
    assert "from robin.capture.reprise_collecte import (" in cli_text
    assert "MISSION_ID," in cli_text
    assert CONTINUATION_MISSION_ID not in cli_text
    assert SQLITE_CONTINUATION_MISSION_ID not in cli_text


def test_activation_matrix_requires_independent_keys_and_fail_closed_ordering() -> None:
    matrix = _load("configs/agents/mission-activation-matrix-v3.json")
    authorization = matrix["authorization"]
    assert isinstance(authorization, dict)

    delivery = authorization["reprise_collecte_20261002_delivery"]
    budget = authorization["reprise_collecte_20261002_effect_budget"]
    ordering = authorization["reprise_collecte_20261002_ordering"]
    boundary = authorization["reprise_collecte_20261002_source_boundary"]

    assert f"REQUIRE_EXACT_BASE_{BASE_MAIN_SHA.upper()}" in delivery
    assert "BRANCH_CODEX_REPRISE_COLLECTE_20261002_V1" in delivery
    assert "EXACTLY_ONE_MANUAL_WORKFLOW_DISPATCH_AFTER_MERGED_MAIN" in delivery
    assert "FORBID_RERUN_FORCE_PUSH_REBASE_SQUASH_ADMIN_BYPASS" in delivery
    assert "PROVIDER_HTTP_REQUESTS_MAX_2" in budget
    assert "PROVIDER_CREDITS_MAX_4" in budget
    assert "PURCHASES_0" in budget
    assert "REAL_BETS_0" in budget
    assert "CAPTURE_1_AUDIT_BEFORE_CAPTURE_2" in ordering
    assert "ON_UNKNOWN_COST_QUOTA_PERSISTENCE_OR_REPLAY_FAIL_AND_STOP" in ordering
    assert "SPORT_SOCCER_EPL_REGION_EU_MARKET_H2H" in boundary
    assert "RAW_PROVIDER_PAYLOADS_R2_ONLY" in boundary
    assert "GIT_RAW_ODDS_0" in boundary
    assert "PUBLIC_ARTIFACT_PLAINTEXT_ODDS_0" in boundary

    mission = matrix["missions"][MISSION_ID]
    assert mission == {
        "agents": ["C0", "C2", "C4", "DP6", "A2"],
        "writer": "C0",
        "allowed_paths": EXPECTED_PATHS,
        "scale_ceiling": "E1",
        "delivery_keys": {
            "data": ["DP6"],
            "security": ["C4"],
            "governance": ["C2"],
            "platform": ["A2"],
        },
    }

    continuation_delivery = authorization["reprise_collecte_20261002_continuation_v1_delivery"]
    continuation_budget = authorization["reprise_collecte_20261002_continuation_v1_effect_budget"]
    continuation_ordering = authorization["reprise_collecte_20261002_continuation_v1_ordering"]
    assert "NON_RUNTIME_CONTINUATION_ONLY" in continuation_delivery
    assert "PARENT_RUNTIME_AUTHORITY_REMAINS_EXCLUSIVE" in continuation_delivery
    assert "SUCCESSOR_RUNTIME_EFFECT_BUDGET_INCREMENT_0" in continuation_budget
    assert "PROVIDER_HTTP_REQUESTS_TOTAL_MAX_2_PARENT_BASELINE_0" in continuation_budget
    assert "PROVIDER_CREDITS_TOTAL_MAX_4_PARENT_BASELINE_0" in continuation_budget
    assert "PURCHASES_0" in continuation_budget
    assert "REAL_BETS_0" in continuation_budget
    assert "FIRST_CALL_THEN_TARGETED_AUDIT_THEN_SECOND_CALL_ONLY_AFTER_PASS" in (
        continuation_ordering
    )
    continuation = matrix["missions"][CONTINUATION_MISSION_ID]
    assert continuation == {
        "agents": ["C0", "C2", "C4", "DP6", "A2"],
        "writer": "C0",
        "allowed_paths": EXPECTED_CONTINUATION_PATHS,
        "scale_ceiling": "E1",
        "delivery_keys": {
            "data": ["DP6"],
            "security": ["C4"],
            "governance": ["C2"],
            "platform": ["A2"],
        },
    }

    sqlite_delivery = authorization["reprise_collecte_20261002_continuation_v2_delivery"]
    sqlite_budget = authorization["reprise_collecte_20261002_continuation_v2_effect_budget"]
    sqlite_ordering = authorization["reprise_collecte_20261002_continuation_v2_ordering"]
    assert "NON_RUNTIME_CONTINUATION_ONLY" in sqlite_delivery
    assert "V2_EXPIRY_DOES_NOT_EXTEND_PARENT_RUNTIME_AUTHORITY_EXPIRY" in (sqlite_delivery)
    assert "REQUIRE_EXACT_PREDECESSOR_HEAD_5EACC412" in sqlite_delivery
    assert "TEST_REMOVAL_ASSERTION_WEAKENING_REQUIRED_CHECK_CHANGE" in sqlite_delivery
    assert "SUCCESSOR_RUNTIME_EFFECT_BUDGET_INCREMENT_0" in sqlite_budget
    assert "PARENT_AND_CONTINUATIONS_COMPUTE_BUDGET_TOTAL_MAX_4000_NOT_RESET" in (sqlite_budget)
    assert "PROVIDER_HTTP_REQUESTS_TOTAL_MAX_2_PARENT_BASELINE_0" in sqlite_budget
    assert "PROVIDER_CREDITS_TOTAL_MAX_4_PARENT_BASELINE_0" in sqlite_budget
    assert "PURCHASES_0" in sqlite_budget
    assert "REAL_BETS_0" in sqlite_budget
    assert "VERIFY_SQLALCHEMY_2_0_51_AND_2_1_3_DRIVER_DATABASE_AND_SELECT_1" in (sqlite_ordering)
    sqlite_continuation = matrix["missions"][SQLITE_CONTINUATION_MISSION_ID]
    assert sqlite_continuation == {
        "agents": ["C0", "C2", "C4", "DP6", "A2"],
        "writer": "C0",
        "allowed_paths": EXPECTED_SQLITE_CONTINUATION_PATHS,
        "scale_ceiling": "E1",
        "delivery_keys": {
            "data": ["DP6"],
            "security": ["C4"],
            "governance": ["C2"],
            "platform": ["A2"],
        },
    }


def test_agent_report_schema_accepts_the_reprise_collecte_mission() -> None:
    schema = _load("configs/agents/agent-report-schema-v3.json")

    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
    assert CONTINUATION_MISSION_ID in schema["properties"]["mission_id"]["enum"]
    assert SQLITE_CONTINUATION_MISSION_ID in schema["properties"]["mission_id"]["enum"]


def test_authorization_is_append_only_hash_chained_and_projected_in_evidence_graph() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == AUTHORIZATION_DECISION_ID
    )
    record = records[index]
    assert index > 0
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["proof"] == [AUTHORIZATION_CLAIM_ID]
    assert record["context"]["mission_id"] == MISSION_ID
    assert record["context"]["base_main_sha"] == BASE_MAIN_SHA
    assert record["context"]["mandate_sha256"] == MANDATE_SHA256
    assert record["context"]["writer"] == "C0"
    assert record["context"]["writer_count"] == 1

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
    assert claims[AUTHORIZATION_CLAIM_ID]["source_hash"] == MANDATE_SHA256
    assert decisions[AUTHORIZATION_DECISION_ID]["ledger_record_hash"] == record["hash"]


def test_continuation_authorization_is_append_only_and_non_runtime() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == CONTINUATION_AUTHORIZATION_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["proof"] == [CONTINUATION_AUTHORIZATION_CLAIM_ID]
    assert record["context"]["mission_id"] == CONTINUATION_MISSION_ID
    assert record["context"]["runtime_authority_mission_id"] == MISSION_ID
    assert record["context"]["runtime_authority_expanded"] is False
    assert record["context"]["provider_calls_parent_baseline"] == 0
    assert record["context"]["provider_calls_family_total_max"] == 2
    assert record["context"]["provider_credits_parent_baseline"] == 0
    assert record["context"]["provider_credits_family_total_max"] == 4
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
    continuation_claim = claims[CONTINUATION_AUTHORIZATION_CLAIM_ID]
    assert continuation_claim["status"] == "VERIFIED"
    assert continuation_claim["source_hash"] == CONTINUATION_SOURCE_SHA256
    assert continuation_claim["runtime_authority_expanded"] is False
    assert all(
        value == 0
        for value in continuation_claim["successor_runtime_effect_budget_increment"].values()
    )
    assert (
        decisions[CONTINUATION_AUTHORIZATION_DECISION_ID]["ledger_record_hash"] == (record["hash"])
    )


def test_sqlite_continuation_authorization_is_append_only_and_non_runtime() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == SQLITE_CONTINUATION_AUTHORIZATION_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "MISSION_AUTHORIZED"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["proof"] == [SQLITE_CONTINUATION_AUTHORIZATION_CLAIM_ID]
    assert record["context"]["mission_id"] == SQLITE_CONTINUATION_MISSION_ID
    assert record["context"]["runtime_authority_mission_id"] == MISSION_ID
    assert record["context"]["runtime_authority_expanded"] is False
    assert record["context"]["provider_calls_family_total_max"] == 2
    assert record["context"]["provider_credits_family_total_max"] == 4
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
    claim = claims[SQLITE_CONTINUATION_AUTHORIZATION_CLAIM_ID]
    assert claim["status"] == "VERIFIED"
    assert claim["source_hash"] == SQLITE_CONTINUATION_SOURCE_SHA256
    assert claim["runtime_authority_expanded"] is False
    assert all(value == 0 for value in claim["successor_runtime_effect_budget_increment"].values())
    assert (
        decisions[SQLITE_CONTINUATION_AUTHORIZATION_DECISION_ID]["ledger_record_hash"]
        == record["hash"]
    )


def test_sqlite_failure_is_recorded_without_rerun_or_preexisting_shortcut() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == SQLITE_FAILURE_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "FAILURE"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["proof"] == [SQLITE_FAILURE_CLAIM_ID]
    run = record["context"]["failed_exact_head_run"]
    assert run["run_id"] == 37077584541
    assert run["rerun_performed"] is False
    assert run["nodeid"] == ("tests/jalon4/test_database_urls.py::test_url_sqlite_reste_compatible")
    reproduction = record["context"]["same_environment_reproduction"]
    assert reproduction["clean_main_result"] == "1_FAILED"
    assert reproduction["candidate_head_result"] == "1_FAILED"
    assert reproduction["test_blob_both"] == ("11e60afc18fe1cc55cf1c171483decc13cb268b8")
    assert record["context"]["failure_policy"] == {
        "similar_failure_ordinal": 1,
        "failure_class_distinct_from_record_200": True,
        "correction_policy": "TEST_ONLY_SEMANTIC_COMPATIBILITY_AND_HOLD",
        "architectures_failed": 0,
        "new_successor_manifest_required": True,
    }
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
    assert claims[SQLITE_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[SQLITE_FAILURE_CLAIM_ID]["rerun_performed"] is False
    assert decisions[SQLITE_FAILURE_DECISION_ID]["ledger_record_hash"] == record["hash"]


def test_matrix_hash_pin_failure_is_recorded_before_successor_projection() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == MATRIX_HASH_FAILURE_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "FAILURE"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["proof"] == [MATRIX_HASH_FAILURE_CLAIM_ID]
    reproduction = record["context"]["same_environment_reproduction"]
    assert reproduction["clean_main_result"] == "1_PASSED"
    assert reproduction["v2_candidate_before_fix_result"] == "1_FAILED"
    assert reproduction["old_expected_matrix_sha256"] == (
        "216c30ef7ce27e92ac3b70d9f08ea8531f7e4b4be025e42e809c2428c074e752"
    )
    assert reproduction["authorized_v2_matrix_sha256"] == (
        "d6cc116789e4571eaa3ee7a082a988db31e65e9880991ce90a54e121f97489e0"
    )
    assert record["context"]["failure_policy"] == {
        "similar_failure_ordinal": 1,
        "failure_class_distinct_from_records_200_and_201": True,
        "correction_policy": "TEST_ONLY_EXACT_AUTHORIZED_MATRIX_HASH_REFRESH_SAME_LEVEL",
        "assertion_weakened": False,
        "architectures_failed": 0,
        "successor_projection_required": True,
    }
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
    assert claims[MATRIX_HASH_FAILURE_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[MATRIX_HASH_FAILURE_CLAIM_ID]["assertion_weakened"] is False
    assert decisions[MATRIX_HASH_FAILURE_DECISION_ID]["ledger_record_hash"] == record["hash"]


def test_sqlite_precommit_decision_binds_projection_reviews_and_zero_effects() -> None:
    records = _records()
    index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == SQLITE_PRECOMMIT_DECISION_ID
    )
    record = records[index]
    assert record["record_type"] == "DECISION"
    assert record["decision"] == "PASS_AND_HOLD"
    assert record["previous_hash"] == records[index - 1]["hash"]
    assert record["context"]["commit_context"] is True
    assert record["context"]["mission_id"] == SQLITE_CONTINUATION_MISSION_ID
    assert record["context"]["writer"] == "C0"
    assert record["context"]["writer_count"] == 1
    assert record["context"]["pr"] == 82
    assert record["context"]["files"] == EXPECTED_SQLITE_PRECOMMIT_FILES
    assert record["context"]["review_hashes"] == EXPECTED_SQLITE_V2_002_REVIEW_HASHES
    assert record["proof"] == [
        SQLITE_CONTINUATION_AUTHORIZATION_CLAIM_ID,
        SQLITE_FAILURE_CLAIM_ID,
        MATRIX_HASH_FAILURE_CLAIM_ID,
        SQLITE_PORTABILITY_CLAIM_ID,
        SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID,
        SQLITE_PRECOMMIT_FINAL_REVIEW_CLAIM_ID,
    ]
    assert record["context"]["observed_external_effects"] == EXPECTED_SQLITE_PRECOMMIT_EFFECTS
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
    assert claims[SQLITE_PORTABILITY_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID]["status"] == "SUPERSEDED"
    assert claims[SQLITE_PRECOMMIT_FINAL_REVIEW_CLAIM_ID]["status"] == "SUPERSEDED"
    assert decisions[SQLITE_PRECOMMIT_DECISION_ID]["ledger_record_hash"] == record["hash"]


def test_sqlite_corrected_precommit_decision_binds_exact_current_evidence() -> None:
    records = _records()
    failure_index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == SQLITE_EVIDENCE_FAILURE_DECISION_ID
    )
    decision_index = next(
        position
        for position, record in enumerate(records)
        if record["decision_id"] == SQLITE_CORRECTED_PRECOMMIT_DECISION_ID
    )
    failure = records[failure_index]
    decision = records[decision_index]

    assert failure["record_type"] == "FAILURE"
    assert failure["previous_hash"] == records[failure_index - 1]["hash"]
    assert failure["proof"] == [SQLITE_EVIDENCE_FAILURE_CLAIM_ID]
    assert decision_index == failure_index + 1
    assert decision["record_type"] == "DECISION"
    assert decision["decision"] == "PASS_AND_HOLD"
    assert decision["previous_hash"] == failure["hash"]
    assert decision["context"]["files"] == EXPECTED_SQLITE_PRECOMMIT_FILES
    assert decision["context"]["observed_external_effects"] == (EXPECTED_SQLITE_PRECOMMIT_EFFECTS)
    review_artifacts = {
        "data": "reports/council/reprise-collecte-20261002-sqlite-data-review-v3.json",
        "security": "reports/council/reprise-collecte-20261002-sqlite-security-review-v3.json",
        "governance": "reports/council/reprise-collecte-20261002-sqlite-governance-review-v3.json",
        "platform": "reports/council/reprise-collecte-20261002-sqlite-platform-review-v3.json",
        "final": "reports/council/reprise-collecte-20261002-sqlite-final-review-v3.json",
    }
    assert decision["context"]["review_hashes"] == {
        key: hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for key, relative in review_artifacts.items()
    }
    assert decision["proof"] == [
        SQLITE_CONTINUATION_AUTHORIZATION_CLAIM_ID,
        SQLITE_FAILURE_CLAIM_ID,
        MATRIX_HASH_FAILURE_CLAIM_ID,
        SQLITE_PORTABILITY_CLAIM_ID,
        SQLITE_EVIDENCE_CORRECTION_CLAIM_ID,
        PROJECTION_CLAIM_ID,
        SQLITE_FINAL_REVIEW_CLAIM_ID,
    ]

    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    decisions = {node["decision_id"]: node for node in graph["decision_nodes"]}
    assert claims[SQLITE_EVIDENCE_FAILURE_CLAIM_ID]["status"] == "SUPERSEDED"
    assert claims[SQLITE_EVIDENCE_CORRECTION_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[PROJECTION_CLAIM_ID]["status"] == "VERIFIED"
    assert claims[SQLITE_FINAL_REVIEW_CLAIM_ID]["status"] == "VERIFIED"
    assert decisions[SQLITE_EVIDENCE_FAILURE_DECISION_ID]["ledger_record_hash"] == (failure["hash"])
    assert (
        decisions[SQLITE_CORRECTED_PRECOMMIT_DECISION_ID]["ledger_record_hash"]
        == (decision["hash"])
    )


def test_continuation_projection_supersedes_the_stale_predecessor() -> None:
    graph = _load("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    older = claims[OLDER_PROJECTION_CLAIM_ID]
    predecessor = claims[PREDECESSOR_PROJECTION_CLAIM_ID]
    precommit_projection = claims[SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID]
    projection = claims[PROJECTION_CLAIM_ID]

    assert older["status"] == "SUPERSEDED"
    assert older["superseded_by"] == PREDECESSOR_PROJECTION_CLAIM_ID
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by"] == SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID
    assert precommit_projection["status"] == "SUPERSEDED"
    assert precommit_projection["superseded_by"] == PROJECTION_CLAIM_ID
    assert projection["status"] == "VERIFIED"
    assert projection["successor_of"] == SQLITE_PRECOMMIT_PROJECTION_CLAIM_ID
    expected_paths = set(precommit_projection["artifact_hashes"]) | (EXPECTED_PROJECTION_ADDITIONS)
    assert len(expected_paths) == 41
    assert set(projection["artifact_hashes"]) == expected_paths

    recalculated_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(expected_paths)
    }
    assert projection["artifact_hashes"] == recalculated_hashes
    canonical = json.dumps(recalculated_hashes, sort_keys=True, separators=(",", ":")).encode()
    assert projection["engineering_projection_sha256"] == hashlib.sha256(canonical).hexdigest()
