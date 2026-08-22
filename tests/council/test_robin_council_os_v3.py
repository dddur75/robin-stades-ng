from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TEXT_ARTIFACT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}


def load_json(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def artifact_sha256(path: Path) -> str:
    payload = path.read_bytes()
    if path.suffix.casefold() in TEXT_ARTIFACT_SUFFIXES:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def committed_changed_paths(repo: Path, base_revision: str, head_revision: str) -> set[str]:
    """Return only paths changed between two committed Git trees."""

    def tree_oid(revision: str) -> str:
        return subprocess.run(
            ["git", "rev-parse", "--verify", f"{revision}^{{tree}}"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    payload = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            "-z",
            tree_oid(base_revision),
            tree_oid(head_revision),
            "--",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    return {raw_path.decode("utf-8") for raw_path in payload.split(b"\0") if raw_path}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _committed_scope_repository(
    tmp_path: Path,
) -> tuple[Path, str, str, Path]:
    repo = tmp_path / "committed-scope"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Council CI Isolation")
    _git(repo, "config", "user.email", "council-ci-isolation@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")

    allowed_path = repo / "allowed-change.txt"
    campaign_path = repo / "reports/pattern-research/campaign-summary.json"
    campaign_path.parent.mkdir(parents=True)
    allowed_path.write_bytes(b"base\n")
    campaign_path.write_bytes(b'{"state":"base"}\n')
    _git(
        repo,
        "add",
        "--",
        "allowed-change.txt",
        "reports/pattern-research/campaign-summary.json",
    )
    _git(repo, "commit", "-m", "base")
    base_revision = _git(repo, "rev-parse", "HEAD")

    allowed_path.write_bytes(b"head\n")
    _git(repo, "add", "--", "allowed-change.txt")
    _git(repo, "commit", "-m", "head")
    head_revision = _git(repo, "rev-parse", "HEAD")
    return repo, base_revision, head_revision, campaign_path


def test_committed_scope_is_invariant_to_runtime_worktree_contamination(
    tmp_path: Path,
) -> None:
    repo, base_revision, head_revision, campaign_path = _committed_scope_repository(tmp_path)
    expected_scope = {"allowed-change.txt"}

    campaign_path.write_bytes(b'{"state":"base"}\r\n')
    runtime_artifact = repo / "runtime/untracked-artifact.json"
    runtime_artifact.parent.mkdir()
    runtime_artifact.write_bytes(b"{}\r\n")
    dirty_scope = committed_changed_paths(repo, base_revision, head_revision)
    assert dirty_scope == expected_scope, "COUNCIL_COMMITTED_SCOPE_IS_WORKTREE_INVARIANT"

    old_tracked_scope = {
        path
        for path in _git(
            repo,
            "diff",
            "--name-only",
            base_revision,
        ).splitlines()
        if path
    }
    old_untracked_scope = {
        path
        for path in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        if path
    }
    assert old_tracked_scope | old_untracked_scope == {
        "allowed-change.txt",
        "reports/pattern-research/campaign-summary.json",
        "runtime/untracked-artifact.json",
    }


def test_campaign_summary_runtime_line_endings_do_not_expand_mission_scope(
    tmp_path: Path,
) -> None:
    repo, base_revision, head_revision, campaign_path = _committed_scope_repository(tmp_path)
    expected_scope = {"allowed-change.txt"}
    head_bytes = subprocess.run(
        [
            "git",
            "show",
            f"{head_revision}:reports/pattern-research/campaign-summary.json",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout

    campaign_path.write_bytes(head_bytes)
    head_bytes_scope = committed_changed_paths(repo, base_revision, head_revision)
    campaign_path.write_bytes(head_bytes.replace(b"\r\n", b"\n"))
    lf_bytes_scope = committed_changed_paths(repo, base_revision, head_revision)
    campaign_path.write_bytes(head_bytes.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    crlf_bytes_scope = committed_changed_paths(repo, base_revision, head_revision)

    assert head_bytes_scope == lf_bytes_scope == crlf_bytes_scope == expected_scope, (
        "CAMPAIGN_SUMMARY_RUNTIME_LINE_ENDINGS_DO_NOT_EXPAND_MISSION_SCOPE"
    )


def test_required_governance_artifacts_exist_and_are_valid_json() -> None:
    required = {
        "AGENTS.md",
        "docs/operations/ROBIN-COUNCIL-OS-V3.md",
        "docs/operations/EXPERIMENT-LADDER-V3.md",
        "docs/operations/EVIDENCE-GRAPH-CONTRACT.md",
        "docs/operations/SERVICE-CAPABILITIES-AND-LIMITS.md",
        "docs/operations/GITHUB-ACTIONS-OPERATING-CONTRACT.md",
        "configs/agents/agent-registry-v3.json",
        "configs/agents/mission-activation-matrix-v3.json",
        "configs/agents/agent-report-schema-v3.json",
        "configs/experiments/scale-policy-v3.json",
        "configs/platform/service-capabilities-v1.json",
        "reports/council/decision-ledger.jsonl",
        "reports/council/governance-quality-score-v3.json",
        "reports/council/governance-validation-v3.json",
        "reports/evidence/evidence-graph.json",
        "reports/platform/platform-audit.json",
    }
    assert all((ROOT / path).is_file() for path in required)
    for path in required:
        if path.endswith(".json"):
            load_json(path)


def test_agent_registry_is_complete_unique_and_never_self_validates() -> None:
    registry = load_json("configs/agents/agent-registry-v3.json")
    expected = {
        *(f"C{i}" for i in range(5)),
        *(f"DP{i}" for i in range(1, 7)),
        *(f"RP{i}" for i in range(1, 11)),
        *(f"UX{i}" for i in range(1, 7)),
        *(f"A{i}" for i in range(1, 4)),
    }
    ids = [agent["agent_id"] for agent in registry["agents"]]
    assert set(ids) == expected
    assert len(ids) == len(set(ids)) == 30
    assert registry["single_writer_required"] is True
    assert registry["self_validation_allowed"] is False


def test_activation_is_on_demand_bounded_and_references_known_agents() -> None:
    registry = load_json("configs/agents/agent-registry-v3.json")
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    known = {agent["agent_id"] for agent in registry["agents"]}
    assert matrix["activation_policy"] == "ON_DEMAND_ONLY"
    authorization = matrix["authorization"]
    assert authorization["default"] == "DENY"
    assert authorization["r2_delete"] == "DENY"
    assert authorization["database_destructive_write"] == "DENY"
    assert authorization["real_bet"] == "DENY"
    assert authorization["purchase"] == "DENY"
    assert set(matrix["missions"]) == {
        "GOVERNANCE",
        "PR26",
        "CHRONOS_LOOP53",
        "SCIENTIFIC_TRUTH_KERNEL",
        "POINT_IN_TIME_LINEAGE",
        "FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT",
        "JALON4_WALL_CLOCK_DECAY_FIX_V1",
        "BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_SUCCESSOR_V2",
        "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1",
        "COVERAGE_P0",
        "HYPERGRAPH",
        "COCKPIT",
    }
    for mission in matrix["missions"].values():
        assert len(mission["agents"]) == len(set(mission["agents"]))
        assert set(mission["agents"]) <= known
        assert len(mission["agents"]) < len(known)
        assert mission["writer"] in {"C0", "C0_DESIGNATE"}
        assert mission["allowed_paths"]
        assert mission["scale_ceiling"]
        for validators in mission["delivery_keys"].values():
            assert set(validators) <= set(mission["agents"])
    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    precommit = next(record for record in reversed(ledger) if record["record_type"] == "PRE_COMMIT")
    assert set(matrix["missions"]["GOVERNANCE"]["allowed_paths"]) == set(
        precommit["context"]["files"]
    )
    governance_keys = matrix["missions"]["GOVERNANCE"]["delivery_keys"]
    assert governance_keys == {
        "platform": ["DP5", "A2"],
        "product": ["C3", "UX6"],
    }
    assert set(matrix["missions"]["COCKPIT"]["required_acceptance_checks"]) == {
        "non_technical_french_journey",
        "keyboard",
        "manual_screen_reader_trace",
        "zoom_200",
        "viewport_360",
        "viewport_375",
        "viewport_390",
        "viewport_430",
        "console_and_pageerror",
        "links",
        "reduced_motion",
        "fr_fr_and_i18n_readiness",
        "ssr_and_hydration",
        "empty_states",
    }


def test_agent_report_schema_requires_the_mission_contract() -> None:
    schema = load_json("configs/agents/agent-report-schema-v3.json")
    required = {
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
    assert set(schema["required"]) == required
    assert schema["additionalProperties"] is False
    assert schema["properties"]["confidence"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
    }
    assert schema["properties"]["agent_id"]["enum"]
    assert schema["properties"]["mission_id"]["enum"] == [
        "GOVERNANCE",
        "PR26",
        "CHRONOS_LOOP53",
        "SCIENTIFIC_TRUTH_KERNEL",
        "POINT_IN_TIME_LINEAGE",
        "FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT",
        "JALON4_WALL_CLOCK_DECAY_FIX_V1",
        "BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_SUCCESSOR_V2",
        "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1",
        "COVERAGE_P0",
        "HYPERGRAPH",
        "COCKPIT",
    ]
    assert schema["$defs"]["fact"]["additionalProperties"] is False
    assert schema["$defs"]["risk"]["additionalProperties"] is False


def test_scientific_truth_kernel_authority_is_offline_bounded_and_exact() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/scientific-truth-kernel-v1.json")
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
    assert manifest["mission_id"] == "SCIENTIFIC_TRUTH_KERNEL"
    assert manifest["authorized_stages"] == ["E1"]
    assert manifest["maximum_stage"] == "E1"
    assert manifest["compute_budget"] == 2000
    assert manifest["time_budget"] == 172800
    assert manifest["external_effects"] == [
        "git_remote_write_non_force",
        "github_pull_request_write",
        "github_merge_commit",
        "github_actions_observe",
    ]
    assert manifest["source_hash"] == (
        "bba610364cff4cb0e3b3af6fa35463fb5cbb503a6581b1a0b3a6c5758490ba71"
    )
    mission = matrix["missions"]["SCIENTIFIC_TRUTH_KERNEL"]
    assert mission["scale_ceiling"] == manifest["maximum_stage"]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C1", "C2", "C4", "DP6", "RP8", "RP9", "A1"]
    allowed_paths = mission["allowed_paths"]
    assert len(allowed_paths) == len(set(allowed_paths)) == 68
    assert (
        hashlib.sha256(
            json.dumps(
                allowed_paths,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        == "939e255aacb69b576eb990310781daf2522a10c633ef4b4a5f6db7836e5aab72"
    )
    assert mission["delivery_keys"] == {
        "data": ["DP6", "C2"],
        "science": ["C2", "RP8", "RP9", "A1"],
        "security": ["C4", "C1"],
    }
    assert "NEON_API_CALLS_0" in matrix["authorization"]["scientific_truth_kernel_effect_budget"]
    assert "FORBID_FORCE_PUSH" in matrix["authorization"]["scientific_truth_kernel_delivery"]


def test_point_in_time_lineage_authority_is_offline_bounded_and_exact() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/point-in-time-lineage-closure-v1.json")
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
    assert manifest["mission_id"] == "POINT_IN_TIME_LINEAGE"
    assert manifest["authorized_stages"] == ["E1"]
    assert manifest["maximum_stage"] == "E1"
    assert manifest["compute_budget"] == 2000
    assert manifest["time_budget"] == 172800
    assert manifest["external_effects"] == [
        "git_remote_write_non_force",
        "github_pull_request_write",
        "github_merge_commit",
        "github_actions_observe",
    ]
    assert manifest["source_hash"] == (
        "fd1de7f4c573047d15ef1561fc8f4e8a1dd5558534234f53941c9cba22e265a3"
    )
    assert manifest["expires_at"] == "2026-08-17T23:59:59Z"

    mission = matrix["missions"]["POINT_IN_TIME_LINEAGE"]
    assert set(mission) == {
        "agents",
        "writer",
        "allowed_paths",
        "scale_ceiling",
        "delivery_keys",
    }
    assert mission["scale_ceiling"] == manifest["maximum_stage"]
    assert mission["writer"] == "C0"
    assert mission["agents"] == [
        "C0",
        "C1",
        "C2",
        "C4",
        "DP5",
        "DP6",
        "RP8",
        "RP9",
        "A1",
    ]
    allowed_paths = mission["allowed_paths"]
    assert allowed_paths == sorted(allowed_paths)
    assert len(allowed_paths) == len(set(allowed_paths)) == 113
    assert (
        hashlib.sha256(
            json.dumps(
                allowed_paths,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        == "07977602548623af20bf6b5f5267702bc8c64e19b09171645121e2e44e96b01a"
    )
    assert all(
        path
        and path == path.strip()
        and not path.startswith(("/", "./"))
        and "\\" not in path
        and ":" not in path
        and not Path(path).is_absolute()
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and not any(marker in path for marker in ("*", "?", "[", "]"))
        for path in allowed_paths
    )
    assert not any(
        path.casefold().startswith((".github/workflows/", "migrations/", "src/robin/storage/"))
        for path in allowed_paths
    )
    assert mission["delivery_keys"] == {
        "data": ["DP6", "C2"],
        "platform": ["DP5"],
        "science": ["C2", "RP8", "RP9", "A1"],
        "security": ["C4", "C1"],
    }
    authorization = matrix["authorization"]
    assert authorization["point_in_time_lineage_effect_budget"] == (
        "BUSINESS_DATA_NETWORK_CALLS_0;NEON_API_CALLS_0;"
        "POSTGRESQL_PRODUCTION_CONNECTIONS_0;PRODUCTION_SQL_READS_0;"
        "PRODUCTION_SQL_WRITES_0;"
        "LOCAL_TEMPORARY_SQLITE_READS_ALLOWED_FOR_TESTS_AND_OFFLINE_REPLAY_ONLY;"
        "LOCAL_TEMPORARY_SQLITE_WRITES_ALLOWED_FOR_TESTS_AND_OFFLINE_REPLAY_ONLY;"
        "LOCAL_TEMPORARY_SQLITE_MUST_USE_PYTEST_TMP_PATH_OR_OS_TEMP;"
        "PERSISTENT_LOCAL_DATABASE_MUTATIONS_0;"
        "EPHEMERAL_CI_POSTGRESQL_TEST_SERVICE_ALLOWED;R2_OPERATIONS_0;"
        "PROVIDER_CALLS_0;API_FOOTBALL_CALLS_0;ODDS_PROVIDER_CALLS_0;"
        "LIVE_WORKFLOW_DISPATCHES_0;MIGRATION_0014_0;"
        "NEW_DATABASE_MIGRATIONS_0;RECOVERY_BRANCH_CREATIONS_0;"
        "ROLE_CREATIONS_0;PURCHASES_0;REAL_BETS_0;PROMOTIONS_0;"
        "SOCIAL_PUBLICATIONS_0"
    )
    assert authorization["point_in_time_lineage_delivery"] == (
        "ALLOW_ONE_INITIAL_NON_FORCE_PUSH_PLUS_MAXIMUM_THREE_DIRECTLY_"
        "CONSEQUENTIAL_NON_FORCE_CORRECTIVE_PUSHES_FOR_DETERMINISTIC_CI_"
        "FAILURES_TEMPORAL_CONTRACT_DEFECTS_TEST_FIXTURE_DEFECTS_REPORT_"
        "EVIDENCE_CONSISTENCY_OR_CROSS_PLATFORM_LINE_ENDINGS;ALLOW_ONE_"
        "DRAFT_PULL_REQUEST_TITLED_ROBIN_POINT_IN_TIME_LINEAGE_CLOSURE_V1;"
        "ALLOW_MERGE_COMMIT_ONLY_AFTER_EXACT_HEAD_CI_GREEN_THREE_INDEPENDENT_"
        "REVIEWS_P0_ZERO_P1_ZERO_SCORE_AT_LEAST_95_THREADS_ZERO_FUTURE_"
        "MUTATION_MATRIX_PASS_PROSPECTIVE_FAIL_CLOSED_PASS_HISTORICAL_"
        "LIMITATIONS_EXPLICIT_AND_MERGEABLE_CLEAN;FORBID_FORCE_PUSH_REBASE_"
        "SQUASH_ADMIN_BYPASS_BRANCH_DELETE_LIVE_WORKFLOW_DISPATCH_PRODUCTION_"
        "ACCESS_AND_NEW_DATABASE_MIGRATION"
    )
    assert authorization["point_in_time_lineage_storage_gate"] == (
        "IF_DURABLE_POINT_IN_TIME_PROOF_REQUIRES_ANY_SCHEMA_CHANGE_OR_DATABASE_"
        "MIGRATION_THEN_RECORD_TEMPORAL_STORAGE_MIGRATION_REQUIRED_SET_ROBIN_"
        "POINT_IN_TIME_LINEAGE_V1_PARTIAL_ALLOW_ONLY_EXISTING_REPORT_AND_DOC_"
        "DESIGN_EVIDENCE_AND_FAIL_AND_STOP_BEFORE_SCHEMA_CODE_BUSINESS_CODE_"
        "MERGE_PROMOTION_OR_PRODUCTION_USE"
    )
    assert authorization["point_in_time_lineage_base"] == (
        "REQUIRE_EXACT_BASE_71833964E5D7BA7F5882BFFF49B39D567FD5473B_AND_"
        "BRANCH_CODEX_POINT_IN_TIME_LINEAGE_CLOSURE_V1;ON_BASE_DRIFT_TOUCHING_"
        "TEMPORAL_DECISION_PATHS_FAIL_AND_STOP"
    )
    assert authorization["mission_manifest_external_effects"] == (
        "MUST_NOT_OVERRIDE_THIS_AUTHORIZATION_MATRIX"
    )

    expected_record157_proof = [
        "GOV.SCIENTIFIC.TRUTH.DEFECT.INVENTORY.V1.003",
        "EVAL.SCIENTIFIC.ROI.TURNOVER.REPAIR.V1.003",
        "GOV.SCIENTIFIC.YIELD.CONSUMER.INVENTORY.V1.003",
        "GOV.SCIENTIFIC.DEVIG.IMPLEMENTATION.INVENTORY.V1.003",
        "EVAL.SCIENTIFIC.DEVIG.CANONICALIZATION.V1.003",
        "GOV.SCIENTIFIC.DECISION.PATH.TRACE.V1.003",
        "REPLAY.SCIENTIFIC.HISTORICAL.TRUTH.V1.003",
        "GOV.SCIENTIFIC.HISTORICAL.INVALIDATION.LEDGER.V1.003",
        "SCIENCE.TRUTH_KERNEL.REGRESSION.V1.003",
        "SCIENCE.TRUTH_KERNEL.REPORTS.RECEIPT.V1.003",
        "SECURITY.SCIENTIFIC.TRUTH_KERNEL.ZERO_EFFECTS.V1.003",
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.012",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.021",
        "SCIENCE.TRUTH_KERNEL.CROSS_PLATFORM.HASHING.V1.002",
        "SCIENCE.TRUTH_KERNEL.MODEL_LAB.DEVIG.ARITY.TYPE.V1.002",
        "SCIENCE.TRUTH_KERNEL.PROSPECTIVE.DEVIG.PRICE.TYPE.V1.002",
        "GOV.AUTHORIZATION.POINT_IN_TIME_LINEAGE.001",
        "GOV.TEMPORAL.DEFECT.INVENTORY.V1.001",
        "GOV.TEMPORAL.SURFACE.INVENTORY.V1.001",
        "SCIENCE.TEMPORAL.AVAILABILITY.CONTRACT.V1.001",
        "GOV.TEMPORAL.SOURCE.RECEIPT.INVENTORY.V1.001",
        "EVAL.TEMPORAL.ASOF.JOIN.AUDIT.V1.001",
        "EVAL.TEMPORAL.TEST.COVERAGE.V1.001",
        "EVAL.TEMPORAL.FUTURE.MUTATION.MATRIX.V1.001",
        "GOV.TEMPORAL.DECISION.LINEAGE.TRACE.V1.001",
        "REPLAY.TEMPORAL.HISTORICAL.POINT_IN_TIME.V1.001",
        "GOV.TEMPORAL.INVALIDATION.LEDGER.V1.001",
        "SCIENCE.POINT_IN_TIME_LINEAGE.REGRESSION.V1.001",
        "SCIENCE.POINT_IN_TIME_LINEAGE.REPORTS.RECEIPT.V1.001",
        "SECURITY.POINT_IN_TIME_LINEAGE.ZERO_EFFECTS.V1.001",
    ]
    graph = load_json("reports/evidence/evidence-graph.json")
    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    record157 = next(record for record in ledger if record["decision_id"] == "RCV3-20260814-157")
    assert record157["decision"] == "PASS_AND_HOLD"
    assert record157["context"]["candidate_context"] is True
    assert record157["context"]["commit_context"] is False
    assert record157["proof"] == expected_record157_proof
    assert (
        next(
            node
            for node in graph["decision_nodes"]
            if node["decision_id"] == record157["decision_id"]
        )["ledger_record_hash"]
        == record157["hash"]
    )
    record157_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == record157["decision_id"]
    ]
    assert [edge["edge_id"] for edge in record157_edges] == [
        f"EDGE.{index}" for index in range(485, 515)
    ]
    assert [edge["from_claim_id"] for edge in record157_edges] == (expected_record157_proof)


def test_first_frozen_snapshot_authority_is_exact_offline_and_secret_free() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/first-frozen-receipt-backed-snapshot-v1.json")
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
    assert manifest == {
        "mission_id": "FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": [
            "local_temporary_synthetic_contract_snapshot_write",
            "local_temporary_synthetic_contract_report_set_write",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_actions_observe",
        ],
        "compute_budget": 2000,
        "time_budget": 172800,
        "source_hash": ("df111223524b89b1b8fa51867ee84dba3cb6367d18020c758f1f164b97c1d258"),
        "expires_at": "2026-08-18T00:30:00Z",
    }
    mission = matrix["missions"]["FIRST_FROZEN_RECEIPT_BACKED_SNAPSHOT"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == manifest["maximum_stage"]
    assert mission["agents"] == [
        "C0",
        "C1",
        "C2",
        "C4",
        "DP5",
        "DP6",
        "RP8",
        "RP9",
        "A1",
    ]
    allowed_paths = mission["allowed_paths"]
    assert allowed_paths == sorted(allowed_paths)
    assert len(allowed_paths) == len(set(allowed_paths)) == 38
    assert (
        hashlib.sha256(
            json.dumps(
                allowed_paths,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        == "e4e0dfcca3413bb6d4dc80152a0ac184038119c6b3578a5bbe61bd0acb94a72e"
    )
    assert mission["delivery_keys"] == {
        "data": ["DP6", "C2"],
        "platform": ["DP5"],
        "science": ["C2", "RP8", "RP9", "A1"],
        "security": ["C4", "C1"],
    }
    authorization = matrix["authorization"]
    effect_budget = authorization["first_frozen_snapshot_effect_budget"]
    assert effect_budget.split(";") == [
        "LOCAL_NON_EXECUTION_EVIDENCE_READS_EXACT_2_READ_ONLY",
        "LOCAL_SYNTHETIC_CONTRACT_SNAPSHOT_WRITES_MAX_2_DELETE_AFTER_VERIFICATION",
        "LOCAL_SYNTHETIC_CONTRACT_REPORT_SET_WRITES_MAX_2_DELETE_AFTER_VERIFICATION",
        "LOCAL_REAL_BATCH_CAPTURE_FILE_READS_0",
        "LOCAL_REAL_SNAPSHOT_WRITES_0",
        "LOCAL_SYNTHETIC_SNAPSHOT_CHECK_WRITES_0",
        "LOCAL_SYNTHETIC_REPORT_CHECK_WRITES_0",
        "PROVIDER_NETWORK_CALLS_0",
        "PROVIDER_DNS_RESOLUTION_0",
        "PROVIDER_SECRET_READS_0",
        "NEON_API_CALLS_0",
        "POSTGRESQL_PRODUCTION_CONNECTIONS_0",
        "SQL_READS_0",
        "SQL_WRITES_0",
        "R2_OPERATIONS_0",
        "LIVE_WORKFLOW_DISPATCHES_0",
        "PURCHASES_0",
        "PROMOTIONS_0",
        "REAL_BETS_0",
        "BACKTESTS_0",
        "EDGE_CALCULATIONS_0",
    ]
    for lock in (
        "PROVIDER_NETWORK_CALLS_0",
        "PROVIDER_DNS_RESOLUTION_0",
        "PROVIDER_SECRET_READS_0",
        "NEON_API_CALLS_0",
        "POSTGRESQL_PRODUCTION_CONNECTIONS_0",
        "R2_OPERATIONS_0",
        "PURCHASES_0",
        "PROMOTIONS_0",
        "REAL_BETS_0",
        "BACKTESTS_0",
        "EDGE_CALCULATIONS_0",
    ):
        assert lock in effect_budget
    delivery = authorization["first_frozen_snapshot_delivery"]
    assert "REQUIRE_EXACT_BASE_26CBB8E14814093CC44E17A46A3EF2C899B13D07" in delivery
    assert (
        "ALLOW_ONE_DRAFT_PULL_REQUEST_TITLED_FROZEN_RECEIPT_BACKED_SNAPSHOT_TOOLING_V1" in delivery
    )
    assert "FORBID_READY_MERGE_MAIN_MODIFICATION" in delivery
    assert "REAL_BATCH_NOT_EXECUTED" in delivery
    assert "ZERO_ACCUMULATION_CANDIDATES" in delivery
    boundary = authorization["first_frozen_snapshot_source_boundary"]
    assert boundary.split(";") == [
        "READ_ONLY_EXACT_NON_EXECUTION_REPORT_AND_PREFLIGHT_EVIDENCE",
        "FORBID_FINALIZED_JSON_POLLING_AND_REAL_CAPTURE_FILE_READS",
        "REAL_BATCH_STATUS_NOT_EXECUTED",
        "REAL_CAPTURE_COUNT_0",
        "REAL_SNAPSHOT_STATUS_NOT_CREATED",
        "EXPERIMENT_READINESS_NOT_ASSESSED_ON_REAL_DATA",
        "SYNTHETIC_FIXTURES_CONTRACT_VALIDATION_ONLY",
        "REQUIRE_FAIL_CLOSED_REAL_DATA_GATE_AND_ZERO_ACCUMULATION_CANDIDATES",
        "REQUIRE_SEVEN_COMMITTABLE_SYNTHETIC_AGGREGATE_REPORTS_PLUS_SANITIZED_NON_EXECUTION_WITNESS",
        "RAW_AND_DETAILED_NORMALIZED_DATA_EXTERNAL_ONLY",
        "GIT_HASHES_COUNTS_RATIOS_SCHEMA_FINGERPRINTS_STATUSES_PSEUDONYMS_AND_AGGREGATES_ONLY",
        "REAL_DATA_AND_SECRET_LEAK_COUNT_0",
    ]


def test_jalon4_wall_clock_decay_fix_authority_and_succession_are_exact() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/jalon4-wall-clock-decay-fix-v1.json")
    assert manifest == {
        "mission_id": "JALON4_WALL_CLOCK_DECAY_FIX_V1",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": [
            "local_temporary_synthetic_test_write",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ],
        "compute_budget": 1000,
        "time_budget": 86400,
        "source_hash": ("44afeb5095e34157cf13e9b7990b07ce6af80d7b99d3341c136f6707ccb5f00c"),
        "expires_at": "2026-08-23T23:59:59Z",
    }

    mission = matrix["missions"]["JALON4_WALL_CLOCK_DECAY_FIX_V1"]
    assert mission == {
        "agents": ["C0", "C2", "C4", "DP6"],
        "writer": "C0",
        "allowed_paths": [
            "configs/agents/mission-activation-matrix-v3.json",
            "configs/execution/jalon4-wall-clock-decay-fix-v1.json",
            "reports/council/decision-ledger.jsonl",
            "reports/evidence/evidence-graph.json",
            "tests/council/test_robin_council_os_v3.py",
            "tests/jalon4/test_durable_shadow.py",
        ],
        "scale_ceiling": "E1",
        "delivery_keys": {
            "data": ["DP6"],
            "governance": ["C2"],
            "security": ["C4"],
        },
    }
    assert (
        hashlib.sha256(
            json.dumps(mission["allowed_paths"], ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        == "430941e5aea501b830f632ee09662a35a7233774a0c9634859003edf8a4e77ef"
    )

    authorization = matrix["authorization"]
    assert authorization["jalon4_wall_clock_decay_fix_base"] == (
        "REQUIRE_EXACT_BASE_780E224492CA9B689826857E9EDF6AA9AB95D8F5_AND_"
        "BRANCH_CODEX_JALON4_WALL_CLOCK_DECAY_FIX_V1;ON_BASE_DRIFT_FAIL_AND_STOP"
    )
    assert authorization["jalon4_wall_clock_decay_fix_effect_budget"].split(";") == [
        "LOCAL_TEMPORARY_SYNTHETIC_TEST_WRITES_PYTEST_TMP_ONLY",
        "BUSINESS_DATA_NETWORK_CALLS_0",
        "PROVIDER_CALLS_0",
        "PROVIDER_DNS_CALLS_0",
        "PROVIDER_SECRET_READS_0",
        "REAL_OWNER_AUTHORIZATIONS_0",
        "REAL_ACTIVATIONS_0",
        "REAL_BATCHES_0",
        "REAL_SNAPSHOTS_0",
        "PRODUCTION_WRITES_0",
        "R2_OPERATIONS_0",
        "LIVE_WORKFLOW_DISPATCHES_0",
        "PURCHASES_0",
        "PROMOTIONS_0",
        "REAL_BETS_0",
    ]
    delivery = authorization["jalon4_wall_clock_decay_fix_delivery"]
    for required in (
        "MAXIMUM_ONE_DIRECTLY_CONSEQUENTIAL_CORRECTIVE_PUSH",
        "DRAFT_PULL_REQUEST_TITLED_JALON_4_WALL_CLOCK_DECAY_FIX_V1",
        "MERGE_COMMIT_ONLY",
        "EXACT_HEAD_REPOSITORY_WIDE_CI_GREEN",
        "TEST_ONLY_EXPLICIT_CLOCK_AND_EXPIRED_FIXTURE_MIRROR",
        "FORBID_ARBITRARY_FUTURE_DATE_SHIFT_NOW_PLUS_DELTA_PRODUCTION_CODE_CHANGE",
        "PROVIDER_ACCESS_SECRET_READ_PRODUCTION_ACCESS_PROMOTION_AND_BET",
    ):
        assert required in delivery

    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.019",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.028",
        "GOV.AUTHORIZATION.JALON4.WALL_CLOCK.DECAY.MANIFEST.V1.001",
        "TEMPORAL.JALON4.WALL_CLOCK.DECAY.REGRESSION.V1.001",
        "SECURITY.JALON4.WALL_CLOCK.DECAY.ZERO.EFFECTS.V1.001",
        "GOV.COUNCIL.JALON4.WALL_CLOCK.DECAY.EVIDENCE.SUCCESSION.LEDGER.V1.001",
    ]
    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    record = next(item for item in ledger if item["decision_id"] == "RCV3-20260822-169")
    assert record["previous_hash"] == (
        "a2b01c2b33e60b163a4c3163c8d67d8f7dbc2924832b6c2885224bc747d25f72"
    )
    assert record["proof"] == expected_proof
    assert record["context"]["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "resolved_p1": 1,
        "resolved_p1_ids": ["J4TIME-001"],
    }

    graph = load_json("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    assert len(graph["claims"]) == 404
    assert len(graph["decision_nodes"]) == 166
    assert len(graph["edges"]) == 698
    expected_statuses = {
        expected_proof[0]: "SUPERSEDED",
        expected_proof[1]: "SUPERSEDED",
        **{claim_id: "VERIFIED" for claim_id in expected_proof[2:5]},
        expected_proof[5]: "SUPERSEDED",
    }
    assert {
        claim_id: claims[claim_id]["status"] for claim_id in expected_proof
    } == expected_statuses
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.018"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.019"
    )
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.027"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.028"
    )
    assert (
        claims["GOV.COUNCIL.PR60.EVIDENCE.SUCCESSION.LEDGER.V1.001"]["superseded_by"]
        == "GOV.COUNCIL.JALON4.WALL_CLOCK.DECAY.EVIDENCE.SUCCESSION.LEDGER.V1.001"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.019"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.020"
    )
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.028"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.029"
    )
    assert claims["GOV.COUNCIL.JALON4.WALL_CLOCK.DECAY.EVIDENCE.SUCCESSION.LEDGER.V1.001"][
        "superseded_by"
    ] == ("GOV.COUNCIL.BOUNDED_LIVE_CANARY.EVIDENCE.SUCCESSION.LEDGER.V2.001")
    node = next(
        item for item in graph["decision_nodes"] if item["decision_id"] == record["decision_id"]
    )
    assert node["ledger_record_hash"] == record["hash"]
    edges = [edge for edge in graph["edges"] if edge["to_decision_id"] == record["decision_id"]]
    assert [edge["edge_id"] for edge in edges] == [f"EDGE.{number}" for number in range(655, 661)]
    assert [edge["from_claim_id"] for edge in edges] == expected_proof


def test_bounded_live_canary_successor_v2_authority_and_succession_are_exact() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/bounded-multi-league-live-canary-capability-v2.json")
    assert manifest == {
        "mission_id": "BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_SUCCESSOR_V2",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": [
            "local_temporary_synthetic_capture_write",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ],
        "compute_budget": 5000,
        "time_budget": 345600,
        "source_hash": ("44afeb5095e34157cf13e9b7990b07ce6af80d7b99d3341c136f6707ccb5f00c"),
        "expires_at": "2026-08-26T02:00:00Z",
    }

    mission = matrix["missions"]["BOUNDED_MULTI_LEAGUE_LIVE_CANARY_CAPABILITY_SUCCESSOR_V2"]
    assert mission["agents"] == ["C0", "C2", "C4", "DP6"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E1"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "governance": ["C2"],
        "security": ["C4"],
    }
    assert len(mission["allowed_paths"]) == 40
    assert mission["allowed_paths"] == sorted(set(mission["allowed_paths"]))
    assert (
        hashlib.sha256(
            json.dumps(mission["allowed_paths"], ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        == "77598f8d0e90092c5a5bec6af7d04d99a07a35dd2879cd63f4d96a830b8fc170"
    )

    authorization = matrix["authorization"]
    delivery = authorization["bounded_live_canary_capability_successor_v2_delivery"]
    donor = authorization["bounded_live_canary_capability_successor_v2_donor"]
    assert "REQUIRE_EXACT_BASE_6C975DAE257DB73CA3EF61C5A6E1FB5B6C3F64DD" in delivery
    assert "MAXIMUM_TWO_DIRECTLY_CONSEQUENTIAL_NON_FORCE_CORRECTIVE_PUSHES" in delivery
    assert "MERGE_COMMIT_ONLY" in delivery
    assert "DONOR_PR61_READ_ONLY_HISTORICAL" in donor
    assert "HEAD_CD9269BA1D33A3165C2BB3344A4C50C66FAE6E5F" in donor
    assert "ALLOW_COMMENT_AND_CLOSE_ONLY_AFTER_SUCCESSOR_MERGED" in donor

    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.020",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.029",
        "GOV.CI.BOUNDED_LIVE_CANARY.CAPABILITY.WORKFLOW.V2.001",
        "GOV.AUTHORIZATION.BOUNDED_LIVE_CANARY.CAPABILITY.MANIFEST.V2.001",
        "GOV.BOUNDED_LIVE_CANARY.CAPABILITY.REPORT.V1.001",
        "SCIENCE.BOUNDED_LIVE_CANARY.NON_EXECUTION.V1.001",
        "SECURITY.BOUNDED_LIVE_CANARY.ZERO_EFFECTS.V1.001",
        "GOV.BOUNDED_LIVE_CANARY.FINAL.REVIEW.V2.001",
        "GOV.COUNCIL.BOUNDED_LIVE_CANARY.EVIDENCE.SUCCESSION.LEDGER.V2.001",
    ]
    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    record = next(item for item in ledger if item["decision_id"] == "RCV3-20260822-170")
    assert record["previous_hash"] == (
        "0a2a3cc652fe4c2da6b29961ce342bc6e182a080cd8d717ae17feae7328bab06"
    )
    assert record["proof"] == expected_proof
    assert record["context"]["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 4,
        "resolved_delivery_defects": [
            "LINUX_IDENTITY_SWAP_EXPECTATION_TOO_NARROW",
            "BOUNDED_UBUNTU_SHALLOW_COUNCIL_SCOPE",
        ],
    }
    assert record["context"]["external_effects"] == {
        "provider_calls": 0,
        "provider_dns_calls": 0,
        "provider_secret_reads": 0,
        "real_owner_authorizations": 0,
        "real_activations": 0,
        "real_batches": 0,
        "real_snapshots": 0,
        "purchases": 0,
        "promotions": 0,
        "real_bets": 0,
    }

    graph = load_json("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    assert len(graph["claims"]) == 404
    assert len(graph["decision_nodes"]) == 166
    assert len(graph["edges"]) == 698
    assert {claim_id: claims[claim_id]["status"] for claim_id in expected_proof} == {
        expected_proof[0]: "SUPERSEDED",
        expected_proof[1]: "SUPERSEDED",
        expected_proof[2]: "SUPERSEDED",
        **{claim_id: "VERIFIED" for claim_id in expected_proof[3:8]},
        expected_proof[8]: "SUPERSEDED",
    }
    for predecessor in (
        "GOV.CI.POSTMERGE.TIMEOUT.BUDGET.PR58.WORKFLOW.V1.001",
        "CI.POSTMERGE.TIMEOUT.BUDGET.PR58.RUN1.V1.001",
        "SECURITY.CI.POSTMERGE.TIMEOUT.BUDGET.PR58.ZERO.EFFECTS.V1.001",
    ):
        assert claims[predecessor]["status"] == "SUPERSEDED"
        assert claims[predecessor]["superseded_by"] == (
            "GOV.CI.BOUNDED_LIVE_CANARY.CAPABILITY.WORKFLOW.V2.001"
        )
    node = next(
        item for item in graph["decision_nodes"] if item["decision_id"] == record["decision_id"]
    )
    assert node["ledger_record_hash"] == record["hash"]
    edges = [edge for edge in graph["edges"] if edge["to_decision_id"] == record["decision_id"]]
    assert [edge["edge_id"] for edge in edges] == [f"EDGE.{number}" for number in range(661, 670)]
    assert [edge["from_claim_id"] for edge in edges] == expected_proof


def test_real_execution_bootstrap_closure_v1_authority_and_succession_are_exact() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/real-execution-bootstrap-closure-v1.json")
    assert manifest == {
        "mission_id": "REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1",
        "authorized_stages": ["E1"],
        "maximum_stage": "E1",
        "external_effects": [
            "local_standalone_runtime_create_after_merge",
            "github_public_full_clone_after_merge",
            "provider_public_dns_resolution_exactly_once_after_merge",
            "official_schedule_public_read_after_merge",
            "git_remote_write_non_force",
            "github_pull_request_write",
            "github_merge_commit",
            "github_actions_observe",
        ],
        "compute_budget": 8000,
        "time_budget": 345600,
        "source_hash": "0783d995e95c0a8a969f76ff3f468c3b96a697155a7ad01e0676963c6bab9f43",
        "expires_at": "2026-08-26T10:00:00Z",
    }

    mission = matrix["missions"]["REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1"]
    assert mission["agents"] == ["C0", "C2", "C4", "DP6"]
    assert mission["writer"] == "C0"
    assert mission["scale_ceiling"] == "E1"
    assert mission["delivery_keys"] == {
        "data": ["DP6"],
        "security": ["C4"],
        "governance": ["C2"],
    }
    assert len(mission["allowed_paths"]) == 38
    assert mission["allowed_paths"] == sorted(set(mission["allowed_paths"]))
    assert (
        hashlib.sha256(
            json.dumps(mission["allowed_paths"], ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        == "0f7ecdb5faf9421fd7d7558810efdc9fb9363641dcd9adb1e7eadb98710b2b6b"
    )

    authorization = matrix["authorization"]
    delivery = authorization["real_execution_bootstrap_closure_v1_delivery"]
    ordering = authorization["real_execution_bootstrap_closure_v1_ordering"]
    effects = authorization["real_execution_bootstrap_closure_v1_effect_budget"]
    live = authorization["real_execution_bootstrap_closure_v1_live_boundary"]
    assert "REQUIRE_EXACT_BASE_0591F01C580EB853890E9C1C304A78C21BA9DE63" in delivery
    assert "DRAFT_PULL_REQUEST_TITLED_REAL_EXECUTION_BOOTSTRAP_CLOSURE_V1" in delivery
    assert "MERGE_COMMIT_ONLY" in delivery
    assert "POST_MERGE_PROVIDER_DNS_RESOLUTION_EXACTLY_1" in effects
    assert "PROVIDER_HTTP_CALLS_0" in effects
    assert "REAL_PROVIDER_SECRET_READS_0" in effects
    assert "ENGINEERING_AND_EXACT_HEAD_CI_AND_THREE_REVIEWS_AND_MERGE_FIRST" in ordering
    assert "STOP_BEFORE_ENVIRONMENT_SECRET_READER_OR_PROVIDER_TRANSPORT" in ordering
    assert "NO_REAL_LIVE_CAPTURE_AUTHORIZED" in live

    expected_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.021",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.030",
        "GOV.CI.REAL_EXECUTION_BOOTSTRAP.CLOSURE.WORKFLOW.V1.001",
        "GOV.AUTHORIZATION.REAL_EXECUTION_BOOTSTRAP.CLOSURE.MANIFEST.V1.001",
        "DATA.REAL_EXECUTION_BOOTSTRAP.CLOSURE.DP6.REVIEW.V1.001",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C4.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C2.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.FINAL.REVIEW.V1.001",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.CLOSURE.ZERO.EFFECTS.V1.001",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.001",
    ]
    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    record = next(item for item in ledger if item["decision_id"] == "RCV3-20260822-171")
    assert record["previous_hash"] == (
        "971510aa8e766a7d538c908c314abc89726214d16ffb30d5a7f178e63c6b4a63"
    )
    assert record["proof"] == expected_proof
    assert record["context"]["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
    }
    assert record["context"]["external_effects"] == {
        "engineering_provider_dns_resolutions": 0,
        "provider_tcp_connections": 0,
        "provider_http_calls": 0,
        "real_secret_reads": 0,
        "real_capture_calls": 0,
        "real_owner_authorizations": 0,
        "real_activations": 0,
        "real_batches": 0,
        "real_snapshots": 0,
        "purchases": 0,
        "promotions": 0,
        "real_bets": 0,
    }

    graph = load_json("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    assert len(graph["claims"]) == 404
    assert len(graph["decision_nodes"]) == 166
    assert len(graph["edges"]) == 698
    assert {claim_id: claims[claim_id]["status"] for claim_id in expected_proof} == {
        expected_proof[0]: "SUPERSEDED",
        expected_proof[1]: "SUPERSEDED",
        **{claim_id: "VERIFIED" for claim_id in expected_proof[2:9]},
        expected_proof[9]: "SUPERSEDED",
    }
    predecessors = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.020": expected_proof[0],
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.029": expected_proof[1],
        "GOV.CI.BOUNDED_LIVE_CANARY.CAPABILITY.WORKFLOW.V2.001": expected_proof[2],
        "GOV.COUNCIL.BOUNDED_LIVE_CANARY.EVIDENCE.SUCCESSION.LEDGER.V2.001": (expected_proof[9]),
    }
    for predecessor, successor in predecessors.items():
        assert claims[predecessor]["status"] == "SUPERSEDED"
        assert claims[predecessor]["superseded_by"] == successor

    node = next(
        item for item in graph["decision_nodes"] if item["decision_id"] == record["decision_id"]
    )
    assert node["ledger_record_hash"] == record["hash"]
    edges = [edge for edge in graph["edges"] if edge["to_decision_id"] == record["decision_id"]]
    assert [edge["edge_id"] for edge in edges] == [f"EDGE.{number}" for number in range(670, 680)]
    assert [edge["from_claim_id"] for edge in edges] == expected_proof

    correction_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.022",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.031",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.WINDOWS_API_TYPING.V1.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.NETWORK.WINDOWS_API_TYPING.V1.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.WINDOWS_SYNC_REGISTRY.ABSENT_KEY.V1.001",
        "DATA.REAL_EXECUTION_BOOTSTRAP.CLOSURE.DP6.REVIEW.V1.001",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C4.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C2.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.FINAL.REVIEW.V1.001",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.002",
    ]
    correction = next(item for item in ledger if item["decision_id"] == "RCV3-20260822-172")
    assert correction["previous_hash"] == record["hash"]
    assert correction["proof"] == correction_proof
    assert correction["context"]["failed_exact_head_run"] == {
        "run_id": 32576737145,
        "attempt": 1,
        "head_sha": "cb7d46e902c60c8bfab0d2f0337250be7cd54461",
        "status": "completed",
        "conclusion": "failure",
        "root_cause_job_ids": [97040064697, 97040064712],
        "failed_jobs": [
            {
                "job_id": 97040064697,
                "name": "Bounded live canary - Windows",
                "failed_step": "Compiler et tester la capacité bornée",
                "classification": "ABSENT_SYNC_PROVIDER_REGISTRY_ROOT_MISCLASSIFIED_UNAVAILABLE",
                "pytest_failed": 11,
                "pytest_passed": 376,
                "affected_file": "src/robin/capture/workspace_bootstrap.py",
            },
            {
                "job_id": 97040064712,
                "name": "Bounded live canary - Ubuntu",
                "failed_step": "Vérifier le typage strict de la capacité bornée",
                "classification": "LINUX_STUB_ONLY_WINDOWS_DYNAMIC_API_TYPING",
                "mypy_error_count": 10,
                "affected_files": [
                    "src/robin/capture/provider_network.py",
                    "src/robin/capture/workspace_bootstrap.py",
                ],
            },
            {
                "job_id": 97043362274,
                "name": "tests",
                "failed_step": "Refuser tout prerequis absent, annule ou en echec",
                "classification": "FAIL_CLOSED_PREREQUISITE_PROPAGATION",
                "independent_defect": False,
                "root_cause_job_ids": [97040064697, 97040064712],
            },
        ],
        "rerun_performed": False,
    }
    assert correction["context"]["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
        "resolved_ci_defect_ids": [
            "TASKD-CI-PORTABILITY-001",
            "TASKD-CI-WINDOWS-SYNC-REGISTRY-002",
        ],
        "resolved_review_defect_ids": [
            "C4-SYNC-ENUM-001",
            "C4-SYNC-FNF-SCOPE-002",
        ],
    }
    assert correction["context"]["delivery_authority"] == {
        "first_directly_consequential_corrective_commit_authorized_now": True,
        "first_directly_consequential_non_force_push_authorized_now": True,
        "remaining_directly_consequential_corrective_pushes_after_this": 1,
        "automatic_new_exact_head_ci_required": True,
        "rerun_32576737145_authorized": False,
        "merge_authorized_now": False,
        "force_push_authorized": False,
        "squash_merge_authorized": False,
        "rebase_merge_authorized": False,
        "admin_bypass_authorized": False,
        "branch_deletion_authorized": False,
    }
    assert correction["context"]["external_effects"] == record["context"]["external_effects"]
    assert {claim_id: claims[claim_id]["status"] for claim_id in correction_proof} == {
        correction_proof[0]: "SUPERSEDED",
        correction_proof[1]: "SUPERSEDED",
        correction_proof[2]: "SUPERSEDED",
        correction_proof[3]: "VERIFIED",
        correction_proof[4]: "SUPERSEDED",
        **{claim_id: "VERIFIED" for claim_id in correction_proof[5:9]},
        correction_proof[9]: "SUPERSEDED",
    }
    correction_successors = {
        expected_proof[0]: correction_proof[0],
        expected_proof[1]: correction_proof[1],
        expected_proof[9]: correction_proof[9],
    }
    for predecessor, successor in correction_successors.items():
        assert claims[predecessor]["status"] == "SUPERSEDED"
        assert claims[predecessor]["superseded_by"] == successor

    correction_node = next(
        item for item in graph["decision_nodes"] if item["decision_id"] == correction["decision_id"]
    )
    assert correction_node["ledger_record_hash"] == correction["hash"]
    correction_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == correction["decision_id"]
    ]
    assert [edge["edge_id"] for edge in correction_edges] == [
        f"EDGE.{number}" for number in range(680, 690)
    ]
    assert [edge["from_claim_id"] for edge in correction_edges] == correction_proof

    postmerge_correction_proof = [
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.023",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.032",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE.TIMEOUT.BUDGET.V1.001",
        "PORTABILITY.REAL_EXECUTION_BOOTSTRAP.WORKSPACE.FULL_CLONE.TIMEOUT.REGRESSION.V1.001",
        "DATA.REAL_EXECUTION_BOOTSTRAP.CLOSURE.DP6.REVIEW.V1.001",
        "SECURITY.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C4.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.C2.REVIEW.V1.001",
        "GOV.REAL_EXECUTION_BOOTSTRAP.CLOSURE.FINAL.REVIEW.V1.001",
        "GOV.COUNCIL.REAL_EXECUTION_BOOTSTRAP.CLOSURE.EVIDENCE.SUCCESSION.LEDGER.V1.003",
    ]
    postmerge_correction = next(
        item for item in ledger if item["decision_id"] == "RCV3-20260822-173"
    )
    assert postmerge_correction["previous_hash"] == correction["hash"]
    assert postmerge_correction["proof"] == postmerge_correction_proof
    assert postmerge_correction["decision"] == "PASS_AND_HOLD"
    postmerge_context = postmerge_correction["context"]
    assert postmerge_context["candidate_context"] is True
    assert postmerge_context["commit_context"] is False
    assert postmerge_context["base_revision"] == ("d50fb62f04549f5a0413cf91d3f3fe88b1c5e9a6")
    assert postmerge_context["correction_candidate_parent_sha"] == (
        "d50fb62f04549f5a0413cf91d3f3fe88b1c5e9a6"
    )
    assert postmerge_context["files"] == [
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "src/robin/capture/workspace_bootstrap.py",
        "tests/capture/test_real_capture_workspace_bootstrap.py",
        "tests/council/test_robin_council_os_v3.py",
    ]
    assert postmerge_context["scope"] == {
        "allowed_paths": 38,
        "corrective_changed_paths": 5,
        "pull_request_changed_paths": 5,
        "outside_allowlist": [],
        "allowlist_sha256": ("0f7ecdb5faf9421fd7d7558810efdc9fb9363641dcd9adb1e7eadb98710b2b6b"),
    }
    failed_create = postmerge_context["failed_postmerge_create"]
    assert failed_create == {
        "authorized_main_sha": "d50fb62f04549f5a0413cf91d3f3fe88b1c5e9a6",
        "runtime_root": "${LOCALAPPDATA}/RobinRuntime",
        "create_timeout_seconds": 300,
        "status": "FAILED",
        "error_code": "WORKSPACE_COMMAND_FAILED",
        "creation_receipt_created": False,
        "authority_receipt_created": False,
        "staging_pack_bytes": 2_998_659_804,
        "pack_first_observed_at_utc": "2026-08-22T15:30:53.5753938Z",
        "pack_finalized_at_utc": "2026-08-22T15:45:27.4989281Z",
        "pack_write_span_seconds": 873.9235343,
        "late_origin_main_sha": "d50fb62f04549f5a0413cf91d3f3fe88b1c5e9a6",
        "runtime_repository_created": False,
        "checkout_completed": False,
        "final_validation_completed": False,
        "post_timeout_descendant_effect_observed": True,
        "failed_root_retained": True,
        "failed_root_reuse_authorized": False,
        "failed_root_cleanup_authorized": False,
    }
    assert postmerge_context["corrected_contract"] == {
        "full_clone_timeout_seconds": 3600,
        "checkout_timeout_seconds": 900,
        "fsck_timeout_seconds": 1800,
        "small_git_read_timeout_seconds": 120,
        "windows_job_object_kill_on_close": True,
        "windows_target_launch_blocked_until_job_assignment": True,
        "timeout_returns_only_after_process_tree_quiescence": True,
        "posix_process_group_termination": True,
        "partial_state_reuse_forbidden": True,
        "automatic_partial_state_cleanup": False,
        "user_controlled_timeout": False,
    }
    assert postmerge_context["defects"] == {
        "open_p0": 0,
        "open_p1": 0,
        "open_p2": 0,
        "open_critical_threads": 0,
        "resolved_defect_ids": [
            "TASKD-POSTMERGE-CLONE-TIMEOUT-001",
            "TASKD-POSTMERGE-TIMEOUT-DESCENDANT-002",
        ],
        "similar_failure_ordinal": 1,
        "next_same_failure_action": "FAIL_AND_REDESIGN_RETURN_E1",
        "third_same_attempt_authorized": False,
    }
    assert postmerge_context["reviews"] == {
        reviewer: {
            "verdict": "ACCEPT",
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
        }
        for reviewer in ("DP6", "C4", "C2")
    }
    assert postmerge_context["delivery_authority"] == {
        "postmerge_consequential_corrective_pr_derived_from_unfulfilled_owner_outcome": True,
        "one_corrective_commit_authorized_now": True,
        "one_non_force_push_authorized_now": True,
        "new_draft_pull_request_authorized_now": True,
        "automatic_new_exact_head_ci_required": True,
        "failed_runtime_retry_authorized_before_corrective_merge": False,
        "ready_authorized_now": False,
        "merge_authorized_now": False,
        "force_push_authorized": False,
        "squash_merge_authorized": False,
        "rebase_merge_authorized": False,
        "admin_bypass_authorized": False,
        "branch_deletion_authorized": False,
    }
    assert postmerge_context["external_effects"] == record["context"]["external_effects"]
    assert postmerge_context["provider_dns_budget"] == {"used": 0, "remaining": 1}
    assert {claim_id: claims[claim_id]["status"] for claim_id in postmerge_correction_proof} == {
        postmerge_correction_proof[0]: "PARTIAL",
        postmerge_correction_proof[1]: "PARTIAL",
        **{claim_id: "VERIFIED" for claim_id in postmerge_correction_proof[2:]},
    }
    postmerge_successors = {
        correction_proof[0]: postmerge_correction_proof[0],
        correction_proof[1]: postmerge_correction_proof[1],
        correction_proof[2]: postmerge_correction_proof[2],
        correction_proof[4]: postmerge_correction_proof[3],
        correction_proof[9]: postmerge_correction_proof[8],
    }
    for predecessor, successor in postmerge_successors.items():
        assert claims[predecessor]["status"] == "SUPERSEDED"
        assert claims[predecessor]["superseded_by"] == successor

    postmerge_node = next(
        item
        for item in graph["decision_nodes"]
        if item["decision_id"] == postmerge_correction["decision_id"]
    )
    assert postmerge_node["ledger_record_hash"] == postmerge_correction["hash"]
    postmerge_edges = [
        edge
        for edge in graph["edges"]
        if edge["to_decision_id"] == postmerge_correction["decision_id"]
    ]
    assert [edge["edge_id"] for edge in postmerge_edges] == [
        f"EDGE.{number}" for number in range(690, 699)
    ]
    assert [edge["from_claim_id"] for edge in postmerge_edges] == (postmerge_correction_proof)


def test_chronos_loop53_authority_is_exact_bounded_and_manifest_cannot_expand_it() -> None:
    matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
    manifest = load_json("configs/execution/chronos-residual-defect-extermination-v1.json")
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
    assert manifest["mission_id"] == "CHRONOS_LOOP53"
    assert manifest["authorized_stages"] == ["E1", "E2", "E3A", "E3B", "E4"]
    assert manifest["maximum_stage"] == "E4"
    assert manifest["external_effects"] == [
        "git_remote_write",
        "github_pull_request_write",
        "github_merge_commit",
        "github_actions_observe",
        "github_actions_dispatch_exactly_once",
        "github_actions_sanitized_report_upload_exactly_once",
        "neon_control_plane_read_only",
        "neon_compute_wake_at_most_once",
        "postgresql_read_only_connection_at_most_once",
    ]
    authorization = matrix["authorization"]
    assert authorization["mission_manifest_external_effects"] == (
        "MUST_NOT_OVERRIDE_THIS_AUTHORIZATION_MATRIX"
    )
    assert authorization["chronos_loop53_live_effect_budget"] == (
        "NEON_GETS_MAX_25;NEON_MUTATIONS_0;"
        "POSTGRESQL_READ_ONLY_CONNECTION_ATTEMPTS_MAX_1;"
        "POSTGRESQL_CONNECTION_RETRIES_0;COMPUTE_WAKE_EVENTS_MAX_1;"
        "SQL_STATEMENTS_MAX_25;SQL_READ_ONLY_ONLY;SQL_WRITES_0;"
        "RECOVERY_BRANCH_CREATIONS_0;ROLE_CREATIONS_0;MIGRATION_0014_0;"
        "R2_OPERATIONS_0;PROVIDER_CALLS_0;PURCHASES_0"
    )
    dispatch = authorization["chronos_loop53_dispatch"]
    assert "CHRONOS_LOOP53_EXTERNAL_AUTHORITY_BOUNDARY_SATISFIED" in dispatch
    assert "ALLOW_EXACTLY_ONE_SANITIZED_REPORT_ARTIFACT_UPLOAD" in dispatch
    assert "FORBID_RERUN_31587004959" in dispatch
    assert "FORBID_SECOND_DISPATCH_6140e09cb38b5fecee5da85882aa8a879dbce780" in dispatch
    delivery = authorization["chronos_loop53_delivery"]
    assert (
        "ALLOW_MAXIMUM_TWO_ADDITIONAL_NON_FORCE_CORRECTIVE_PUSHES_TO_THE_SAME_"
        "EXISTING_PULL_REQUEST_53_AFTER_FAILED_EXACT_HEAD_RUN_31668336473" in delivery
    )
    assert "FIRST_ADDITIONAL_PUSH_ONLY_FOR_COMMITTED_SCOPE_CI_ISOLATION" in delivery
    assert (
        "SECOND_ADDITIONAL_PUSH_ONLY_IF_NEW_EXACT_HEAD_CI_REVEALS_ONE_DIRECTLY_"
        "CONSEQUENTIAL_DETERMINISTIC_FAILURE_IN_PREVIOUSLY_MASKED_STEPS" in delivery
    )
    assert "ALLOW_NO_OTHER_PUSH" in delivery
    assert "FORBID_RERUN_31587004959" in delivery
    assert "FORBID_RERUN_31634267437" in delivery
    assert "FORBID_RERUN_31651412900" in delivery
    assert "FORBID_RERUN_31668336473" in delivery
    assert "COMMITTED_MISSION_SCOPE_MUST_USE_BASE_TREE_VS_HEAD_TREE_ONLY" in delivery
    assert "WORKTREE_CLEANLINESS_IS_A_SEPARATE_PRECOMMIT_CONTRACT" in delivery
    assert "FORBID_SQUASH_REBASE_FORCE_PUSH_AND_BRANCH_DELETE" in delivery
    assert "CHRONOS_LOOP53_EXTERNAL_AUTHORITY_BOUNDARY_SATISFIED" in delivery
    assert authorization["chronos_loop53_external_authority_boundary"] == (
        "REQUIRE_WORKFLOW_IDS_319920551_327137040_327137044_329278452_"
        "329420317_DISABLED_MANUALLY_BEFORE_CORRECTIVE_PUSH_IN_NEW_EXACT_HEAD_"
        "CI_IMMEDIATELY_BEFORE_MERGE_AND_BEFORE_LIVE;ON_DRIFT_FAIL_AND_STOP_"
        "NO_PUSH_NO_MERGE_NO_LIVE_PENDING_SEPARATE_OWNER_AUTHORITY"
    )
    mission = matrix["missions"]["CHRONOS_LOOP53"]
    assert mission["scale_ceiling"] == manifest["maximum_stage"]
    assert mission["delivery_keys"] == {
        "platform": ["DP5"],
        "data": ["DP6"],
        "security": ["C4"],
    }
    exact_loop53_paths = {
        ".github/workflows/chronos-bootstrap-ci-v3.yml",
        ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml",
        ".github/workflows/chronos-neon-pure-readonly-preflight-v4.yml",
        ".github/workflows/ci.yml",
        "configs/agents/agent-report-schema-v3.json",
        "configs/agents/mission-activation-matrix-v3.json",
        "configs/data/p0-coverage-authority-matrix-snapshot-v1.json",
        "configs/execution/chronos-residual-defect-extermination-v1.json",
        "migrations/env.py",
        "reports/activation/chronos-end-to-end-live-path-certification-v1.json",
        "reports/activation/chronos-residual-defect-inventory-v1.json",
        "reports/council/decision-ledger.jsonl",
        "reports/evidence/evidence-graph.json",
        "scripts/chronos_live_path_artifact_guard_v1.py",
        "scripts/chronos_neon_controlled_idle_wake_readonly_v1.py",
        "scripts/chronos_neon_pure_readonly_preflight_v4.py",
        "scripts/chronos_production_bootstrap_v3.py",
        "scripts/run_chronos_dual_principal_ci_v2.py",
        "scripts/run_p0_e2_capability_sample.py",
        "src/robin/chronos_alembic.py",
        "src/robin/historical_deep/coverage_evidence.py",
        "src/robin/historical_deep/e1b_canary.py",
        "src/robin/chronos_production.py",
        "src/robin/chronos_role_lifecycle.py",
        "tests/activation/fixtures/chronos_neon_live_contract_structures_v1.json",
        "tests/activation/fixtures/chronos_neon_positive_project_ownership_witness_v1_golden_pack.json",
        "tests/activation/fixtures/chronos_neon_project_identity_pagination_v1_golden_pack.json",
        "tests/activation/fixtures/chronos_neon_pure_readonly_preflight_v4_neon_api.json",
        "tests/activation/test_chronos_end_to_end_live_path_v1.py",
        "tests/activation/test_chronos_neon_controlled_idle_wake_readonly_v1.py",
        "tests/activation/test_chronos_neon_pure_readonly_preflight_v4.py",
        "tests/activation/test_chronos_production_bootstrap_v3.py",
        "tests/activation/test_migration_path_neutralization.py",
        "tests/chronos/test_chronos_dual_principal_v2.py",
        "tests/chronos/test_chronos_migration_v2.py",
        "tests/coverage/test_scale_pack_mapping_v2.py",
        "tests/council/test_robin_council_os_v3.py",
        "tests/historical_deep/test_coverage_proof_export.py",
        "tests/historical_deep/test_workflow_contracts.py",
        "tests/jalon10/test_workflows_and_guards.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
    }
    assert set(mission["allowed_paths"]) == exact_loop53_paths
    assert all(not path.endswith("/") for path in mission["allowed_paths"])
    committed_scope = committed_changed_paths(
        ROOT,
        "6140e09cb38b5fecee5da85882aa8a879dbce780",
        "1ffeec1cd89e83deda008da39bb22540a70db896",
    )
    assert committed_scope == exact_loop53_paths

    graph = load_json("reports/evidence/evidence-graph.json")
    claims = {claim["claim_id"]: claim for claim in graph["claims"]}
    initial_loop53_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.001",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.001",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.001",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.001",
    }
    exact_path_loop53_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.002",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.002",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.002",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.002",
    }
    correction_candidate_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.003",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.003",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.003",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.003",
    }
    redesign_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.003",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.004",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.004",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.004",
    }
    causal_order_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.003",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.005",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.005",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.005",
    }
    canonical_boundary_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.003",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.006",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.006",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.006",
    }
    current_loop53_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.004",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.007",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.007",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.007",
    }
    aligned_boundary_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.005",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.008",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.008",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.008",
    }
    current_observation_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.006",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.009",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.009",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.009",
    }
    final_review_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.006",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.010",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.009",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.010",
    }
    push_gate_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.006",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.011",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.010",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.011",
    }
    status_gate_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.006",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.012",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.011",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.012",
    }
    final_correction_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.007",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.013",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.012",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.013",
    }
    ci_isolation_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.008",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.014",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.013",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.014",
    }
    review_binding_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.008",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.015",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.014",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.015",
    }
    ci_isolation_push_gate_claim_ids = {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.008",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.016",
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.014",
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.016",
    }
    assert (
        initial_loop53_claim_ids
        | exact_path_loop53_claim_ids
        | correction_candidate_claim_ids
        | redesign_claim_ids
        | causal_order_claim_ids
        | canonical_boundary_claim_ids
        | current_loop53_claim_ids
        | aligned_boundary_claim_ids
        | current_observation_claim_ids
        | final_review_claim_ids
        | push_gate_claim_ids
        | status_gate_claim_ids
        | final_correction_claim_ids
        | ci_isolation_claim_ids
        | review_binding_claim_ids
        | ci_isolation_push_gate_claim_ids
        <= set(claims)
    )
    assert claims["GOV.AUTHORIZATION.COVERAGE.002"] == {
        **claims["GOV.AUTHORIZATION.COVERAGE.002"],
        "status": "SUPERSEDED",
        "superseded_by": "GOV.AUTHORIZATION.CHRONOS_LOOP53.001",
    }
    assert claims["GOV.EVIDENCE.REVISION_POLICY.002"]["status"] == "SUPERSEDED"
    assert claims["GOV.EVIDENCE.REVISION_POLICY.002"]["superseded_by"] == (
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.001"
    )
    old_workflow_claim = claims["GOV.CHRONOS.NEON.CONTROLLED_WAKE.ENTRYPOINT.CORRECTION.V1.001"]
    assert old_workflow_claim["status"] == "SUPERSEDED"
    assert old_workflow_claim["superseded_by"] == (
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001"
    )
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.001": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.002"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.001": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.002"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.001": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.002"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.001": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.002"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.015": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.016"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.015": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.016"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.014": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.015"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.013": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.014"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.014": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.015"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.007": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.008"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.013": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.014"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.012": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.013"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.013": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.014"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.006": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.007"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.012": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.013"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.011": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.012"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.012": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.013"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.011": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.012"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.010": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.011"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.011": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.012"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.010": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.011"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.009": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.010"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.010": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.011"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.009": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.010"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.009": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.010"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.005": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.006"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.008": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.009"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.008": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.009"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.008": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.009"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.004": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.005"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.007": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.008"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.007": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.008"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.007": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.008"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.003": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.004"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.006": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.007"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.006": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.007"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.006": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.007"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.005": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.006"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.005": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.006"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.005": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.006"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.004": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.005"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.004": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.005"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.004": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.005"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.003": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.004"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.003": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.004"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.003": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.004"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    for old_claim_id, new_claim_id in {
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.002": ("GOV.AUTHORIZATION.CHRONOS_LOOP53.003"),
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.002": (
            "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.003"
        ),
        "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.002": (
            "GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.003"
        ),
        "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.002": (
            "GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.003"
        ),
    }.items():
        assert claims[old_claim_id]["status"] == "SUPERSEDED"
        assert claims[old_claim_id]["superseded_by"] == new_claim_id
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.006"]["status"] == "SUPERSEDED"
    assert claims["GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.009"]["status"] == "SUPERSEDED"
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.010"]["status"] == "SUPERSEDED"
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.011"]["status"] == "SUPERSEDED"
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.012"]["status"] == "SUPERSEDED"
    assert claims["GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.011"]["status"] == "SUPERSEDED"
    assert claims["GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.012"]["status"] == "SUPERSEDED"
    for claim_id in ci_isolation_push_gate_claim_ids - {
        "GOV.CHRONOS.NEON.CONTROLLED.WORKFLOW.LOOP53.001",
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.008",
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.016",
    }:
        assert claims[claim_id]["status"] == "PARTIAL"
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.008"]["status"] == ("SUPERSEDED")
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.008"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.009"
    )
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.016"]["status"] == "SUPERSEDED"
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.016"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.017"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.009"]["status"] == "SUPERSEDED"
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.009"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.010"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.010"]["status"] == ("SUPERSEDED")
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.010"]["successor_of"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.009"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.010"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.011"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.011"]["status"] == ("SUPERSEDED")
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.011"]["successor_of"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.010"
    )
    assert claims["GOV.AUTHORIZATION.CHRONOS_LOOP53.011"]["superseded_by"] == (
        "GOV.AUTHORIZATION.CHRONOS_LOOP53.012"
    )

    def assert_append_only_partial_tail(start_claim_id: str) -> str:
        current_claim_id = start_claim_id
        visited: set[str] = set()
        while claims[current_claim_id]["status"] == "SUPERSEDED":
            assert current_claim_id not in visited
            visited.add(current_claim_id)
            successor_id = claims[current_claim_id]["superseded_by"]
            assert successor_id in claims
            assert claims[successor_id]["successor_of"] == current_claim_id
            current_claim_id = successor_id
        assert claims[current_claim_id]["status"] == "PARTIAL"
        assert "superseded_by" not in claims[current_claim_id]
        return current_claim_id

    assert assert_append_only_partial_tail("GOV.AUTHORIZATION.CHRONOS_LOOP53.011").startswith(
        "GOV.AUTHORIZATION.CHRONOS_LOOP53."
    )
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.017"]["status"] == "SUPERSEDED"
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.017"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.018"
    )
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.018"]["status"] == "SUPERSEDED"
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.018"]["successor_of"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.017"
    )
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.018"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.019"
    )
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.019"]["status"] == "SUPERSEDED"
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.019"]["successor_of"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.018"
    )
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.019"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.020"
    )
    assert claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.020"]["status"] == "SUPERSEDED"
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.020"]["successor_of"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.019"
    )
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.020"]["superseded_by"]
        == "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.021"
    )
    assert assert_append_only_partial_tail(
        "GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.020"
    ).startswith("GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.")
    snapshot = ROOT / "configs/data/p0-coverage-authority-matrix-snapshot-v1.json"
    assert artifact_sha256(snapshot) == (
        "52306f04d9e751b8bf32ffff6f6517e5b090754ef789a59276ac75af30d64266"
    )
    historical_resolver = (ROOT / "src/robin/historical_deep/coverage_evidence.py").read_text(
        encoding="utf-8"
    )
    assert "_historical_contract_hash_matches" in historical_resolver
    assert "p0-coverage-authority-matrix-snapshot-v1.json" in historical_resolver

    ledger = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    loop53_record = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-127"
    )
    assert loop53_record["decision_id"] == "RCV3-20260812-127"
    assert loop53_record["record_type"] == "MISSION_AUTHORIZED"
    assert set(loop53_record["proof"]) == initial_loop53_claim_ids
    assert loop53_record["context"]["delivery_keys"] == {
        "platform": "DP5",
        "data": "DP6",
        "security": "C4",
    }
    clarification = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-128"
    )
    assert clarification["decision_id"] == "RCV3-20260812-128"
    assert clarification["record_type"] == "MISSION_AUTHORITY_CLARIFICATION"
    assert clarification["context"]["stage_order"] == [
        "FROZEN_TRIPLE_REVIEW",
        "LOCAL_COMMIT_NON_FORCE_PUSH_AND_ONE_PULL_REQUEST",
        "EXACT_HEAD_CI_GREEN",
        "MERGE_COMMIT",
        "MERGED_MAIN_CI_AND_PAGES_GREEN_THEN_ACTIONS_QUIESCENT",
        "EXACTLY_ONE_NEW_ATTEMPT_ONE_CONTROLLED_READONLY_DISPATCH",
    ]
    assert clarification["context"]["migration_authorized"] is False
    metric_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-129"
    )
    assert metric_correction["decision_id"] == "RCV3-20260812-129"
    assert metric_correction["record_type"] == "EVIDENCE_METRIC_CORRECTION"
    assert metric_correction["context"] == {
        "authority_expanded": False,
        "bounded_matrix_collected": 482,
        "bounded_matrix_file_count": 8,
        "bounded_matrix_result": "481 passed, 1 skipped",
        "corrects_metric_in": "RCV3-20260812-127",
        "dual_principal_file": "15 passed",
        "external_effects": 0,
        "reason": (
            "test_primary_sql_failure_survives_a_secondary_rollback_failure added one passing case"
        ),
        "workflow_exact_three_file_command": "364 passed, 1 skipped",
    }
    inventory_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-130"
    )
    assert inventory_correction["decision_id"] == "RCV3-20260812-130"
    assert inventory_correction["record_type"] == ("RESIDUAL_DEFECT_INVENTORY_CORRECTION")
    assert inventory_correction["context"]["added_defect_id"] == ("CHR53-EVIDENCE-002")
    assert inventory_correction["context"]["counts"] == {
        "deferred": 0,
        "discovered": 78,
        "fixed": 77,
        "known_live_reachable_defects": 0,
        "known_untested_live_path_stages": 0,
        "open_p0": 0,
        "open_p1": 0,
        "p0": 12,
        "p1": 60,
        "p2": 6,
        "p3": 0,
        "privacy_boundary": 1,
    }
    frozen_reviews = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-131"
    )
    assert frozen_reviews["decision_id"] == "RCV3-20260812-131"
    assert frozen_reviews["record_type"] == "FROZEN_TRIPLE_REVIEW_ACCEPTED"
    assert frozen_reviews["context"]["reviews"] == {
        "C4": {"p0": 0, "p1": 0, "score": 98, "verdict": "PASS"},
        "DP5": {"p0": 0, "p1": 0, "score": 97, "verdict": "PASS"},
        "DP6": {"p0": 0, "p1": 0, "score": 97, "verdict": "PASS"},
    }
    assert frozen_reviews["context"]["red_team_answer"] == "YES"
    assert frozen_reviews["context"]["live_authorized_now"] is False
    scope_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-132"
    )
    assert scope_correction["decision_id"] == "RCV3-20260812-132"
    assert scope_correction["record_type"] == "MISSION_EXACT_PATH_SCOPE_CORRECTION"
    assert set(scope_correction["proof"]) == exact_path_loop53_claim_ids
    assert set(scope_correction["context"]["exact_allowed_paths"]) == (
        exact_loop53_paths
        - {
            "configs/data/p0-coverage-authority-matrix-snapshot-v1.json",
            "src/robin/historical_deep/coverage_evidence.py",
            "src/robin/historical_deep/e1b_canary.py",
            "scripts/run_p0_e2_capability_sample.py",
            "tests/coverage/test_scale_pack_mapping_v2.py",
            "tests/historical_deep/test_coverage_proof_export.py",
            "tests/historical_deep/test_workflow_contracts.py",
            "tests/jalon10/test_workflows_and_guards.py",
        }
    )
    assert scope_correction["context"]["changed_path_count"] == 33
    assert scope_correction["context"]["outside_exact_allowlist"] == []
    assert scope_correction["context"]["prior_reviews_applicable"] is False
    exact_path_reviews = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-133"
    )
    assert exact_path_reviews["decision_id"] == "RCV3-20260812-133"
    assert exact_path_reviews["record_type"] == ("EXACT_PATH_FROZEN_TRIPLE_REVIEW_ACCEPTED")
    assert set(exact_path_reviews["proof"]) == exact_path_loop53_claim_ids
    assert exact_path_reviews["context"]["reviews"] == {
        "C4": {"p0": 0, "p1": 0, "score": 97, "verdict": "PASS"},
        "DP5": {"p0": 0, "p1": 0, "score": 97, "verdict": "PASS"},
        "DP6": {"p0": 0, "p1": 0, "score": 97, "verdict": "PASS"},
    }
    assert exact_path_reviews["context"]["red_team_answer"] == "YES"
    assert exact_path_reviews["context"]["changed_paths_equal_allowed"] is True
    assert exact_path_reviews["context"]["live_authorized_now"] is False
    correction = next(record for record in ledger if record["decision_id"] == "RCV3-20260812-134")
    assert correction["decision_id"] == "RCV3-20260812-134"
    assert correction["record_type"] == "FAILURE"
    assert set(correction["proof"]) == correction_candidate_claim_ids
    assert correction["context"]["failed_exact_head_run"] == {
        "attempt": 1,
        "head_sha": "42a78d4e1a17b3bf5b04f5f006dde1dad5e0c82a",
        "rerun_performed": False,
        "run_id": 31634267437,
    }
    assert correction["context"]["failed_contexts"] == [
        "Historical Deep quality",
        "Chronos exact workflow entrypoint",
        "Chronos PostgreSQL profile superuser",
        "Chronos PostgreSQL profile non_superuser_createrole",
    ]
    assert correction["context"]["changed_path_count"] == 38
    assert correction["context"]["changed_paths_equal_allowed"] is True
    assert correction["context"]["prior_reviews_applicable"] is False
    assert correction["context"]["corrective_push_authorized"] == (
        "EXACTLY_ONE_NON_FORCE_PUSH_TO_EXISTING_PR_53_AFTER_NEW_FROZEN_REVIEWS"
    )
    assert correction["context"]["live_workflow_dispatched"] is False
    assert correction["context"]["migration_authorized"] is False
    correction_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == correction["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in correction_edges} == set(correction["proof"])
    assert all(
        edge["relation"] == "SUPPORTS" and edge["status"] == "RECORDED" for edge in correction_edges
    )
    redesign = next(record for record in ledger if record["decision_id"] == "RCV3-20260812-135")
    assert redesign["record_type"] == "REDESIGN"
    assert set(redesign["proof"]) == redesign_claim_ids
    assert redesign["context"]["invalidates_snapshot_record"] == ("RCV3-20260812-134")
    assert redesign["context"]["added_defect_id"] == "CHR53-CI-008"
    assert redesign["context"]["stage_reset"] == "E1"
    assert redesign["context"]["valid_platform_topologies"] == [
        "ZERO_EXACT_EDGE_ZERO_DESCENDANT",
        "ONE_EXACT_ACTOR_EDGE_ONE_ACTOR_DESCENDANT",
    ]
    assert redesign["context"]["live_authorized_now"] is False
    assert redesign["context"]["corrective_push_authorized_now"] is False
    redesign_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == redesign["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in redesign_edges} == set(redesign["proof"])
    causal_order = next(record for record in ledger if record["decision_id"] == "RCV3-20260812-136")
    assert causal_order["record_type"] == "DECISION"
    assert set(causal_order["proof"]) == causal_order_claim_ids
    assert causal_order["context"]["added_defect_id"] == "CHR53-EVIDENCE-003"
    assert causal_order["context"]["stage_order"] == [
        "BOUNDED_LOCAL_PROOF_AND_FRESH_FROZEN_TRIPLE_REVIEW",
        "ONE_CORRECTIVE_LOCAL_COMMIT_AND_NON_FORCE_PUSH_TO_EXISTING_PR_53",
        "NEW_EXACT_HEAD_LINUX_CI_GREEN_INCLUDING_REAL_PG16_HOSTILE_TOPOLOGIES",
        "MERGE_COMMIT",
        "MERGED_MAIN_CI_AND_PAGES_GREEN_THEN_ACTIONS_QUIESCENT",
        "EXACTLY_ONE_NEW_ATTEMPT_ONE_CONTROLLED_READONLY_DISPATCH",
    ]
    assert causal_order["context"]["current_push_authorized"] is False
    assert causal_order["context"]["live_authorized_now"] is False
    assert causal_order["context"]["migration_authorized"] is False
    causal_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == causal_order["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in causal_edges} == set(causal_order["proof"])
    journal_veto = next(record for record in ledger if record["decision_id"] == "RCV3-20260812-137")
    assert journal_veto["record_type"] == "VETO"
    assert journal_veto["decision"] == "PASS_AND_HOLD"
    assert set(journal_veto["proof"]) == canonical_boundary_claim_ids
    assert journal_veto["context"]["added_defect_id"] == "CHR53-GOV-006"
    assert journal_veto["context"]["legacy_prefix"] == {
        "classification": (
            "IMMUTABLE_LEGACY_EVIDENCE_PREFIX_NONCONFORMING_TO_V3_1_ENUMS_"
            "NON_AUTHORITATIVE_FOR_NEW_RUNTIME_DECISIONS"
        ),
        "decision_enum_deviations": 127,
        "record_count": 129,
        "record_type_enum_deviations": 33,
        "tip_hash": ("a882c44b09abba2c28c76411c52ea5e80abe9958dfb6e86a02242fef19ff344f"),
        "tip_id": "RCV3-20260812-136",
    }
    assert journal_veto["context"]["canonical_suffix_start"] == ("RCV3-20260812-137")
    assert journal_veto["context"]["current_push_authorized"] is False
    assert journal_veto["context"]["live_authorized_now"] is False
    assert journal_veto["context"]["migration_authorized"] is False
    allowed_record_types = {
        "MISSION_AUTHORIZED",
        "STAGE_STARTED",
        "STAGE_FINISHED",
        "DECISION",
        "FAILURE",
        "VETO",
        "REDESIGN",
    }
    allowed_decisions = {
        "PASS_AND_SCALE",
        "PASS_AND_HOLD",
        "FAIL_AND_REDESIGN",
        "FAIL_AND_STOP",
        "BLOCKED_EXTERNAL_ACTION",
    }
    boundary_index = ledger.index(journal_veto)
    legacy_prefix = ledger[:boundary_index]
    canonical_suffix = ledger[boundary_index:]
    assert len(legacy_prefix) == 129
    assert sum(record["record_type"] not in allowed_record_types for record in legacy_prefix) == 33
    assert sum(record["decision"] not in allowed_decisions for record in legacy_prefix) == 127
    assert all(record["record_type"] in allowed_record_types for record in canonical_suffix)
    assert all(record["decision"] in allowed_decisions for record in canonical_suffix)

    def rehash_mutation(field: str, value: str) -> dict[str, Any]:
        mutated = {**journal_veto, field: value}
        canonical = json.dumps(
            {key: item for key, item in mutated.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        mutated["hash"] = hashlib.sha256(canonical).hexdigest()
        return mutated

    forbidden_type = rehash_mutation("record_type", "EVIDENCE_CORRECTION")
    forbidden_decision = rehash_mutation("decision", "PASS_AND_HOLD. narrative")
    assert forbidden_type["record_type"] not in allowed_record_types
    assert forbidden_decision["decision"] not in allowed_decisions
    journal_veto_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == journal_veto["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in journal_veto_edges} == set(journal_veto["proof"])
    consumer_veto = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-138"
    )
    assert consumer_veto["record_type"] == "VETO"
    assert consumer_veto["decision"] == "PASS_AND_HOLD"
    assert set(consumer_veto["proof"]) == current_loop53_claim_ids
    assert consumer_veto["context"]["added_defect_ids"] == [
        "CHR53-GOV-007",
        "CHR53-EVIDENCE-004",
    ]
    assert consumer_veto["context"]["changed_path_count"] == 40
    assert consumer_veto["context"]["file_scope_expanded"] is True
    assert consumer_veto["context"]["file_scope_change"] == (
        "38_TO_40_FOR_MINIMAL_DISCOVERED_P1_CORRECTION"
    )
    assert consumer_veto["context"]["external_effect_authority_expanded"] is False
    assert consumer_veto["context"]["legacy_authority_consumers"] == {
        "e1b": "DENY_NO_CANONICAL_SUFFIX_AUTHORITY_AT_CORRECTED_REVISION",
        "e2": "DENY_NO_CANONICAL_SUFFIX_AUTHORITY_AT_CORRECTED_REVISION",
        "replacement_authority_created": False,
    }
    assert consumer_veto["context"]["external_boundary"] == {
        "disabled_workflow_ids": [
            319920551,
            327137040,
            327137044,
            329278452,
            329420317,
        ],
        "expected_state": "disabled_manually",
        "historical_refs_rewritten": False,
        "observed_at": "2026-08-12T22:00:47Z",
        "on_drift": ("FAIL_AND_STOP_NO_PUSH_NO_MERGE_NO_LIVE_PENDING_SEPARATE_OWNER_AUTHORITY"),
        "revalidate": [
            "BEFORE_CORRECTIVE_PUSH",
            "IN_NEW_EXACT_HEAD_CI",
            "IMMEDIATELY_BEFORE_MERGE",
            "BEFORE_LIVE",
        ],
        "sanitized_observation_sha256": (
            "f226731b04491264972a3777d3c60d2a6e174cecbf54854d050edecdd8e83803"
        ),
    }
    assert (
        claims["GOV.EVIDENCE.REVISION_POLICY.CHRONOS_LOOP53.007"]["temporal_class"]
        == "CODE_AND_EXTERNAL_CONFIGURATION_AS_OF"
    )
    assert consumer_veto["context"]["current_push_authorized"] is False
    assert consumer_veto["context"]["live_authorized_now"] is False
    assert consumer_veto["context"]["migration_authorized"] is False
    consumer_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == consumer_veto["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in consumer_edges} == set(consumer_veto["proof"])
    evidence_veto = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-139"
    )
    assert evidence_veto["record_type"] == "VETO"
    assert evidence_veto["decision"] == "PASS_AND_HOLD"
    assert set(evidence_veto["proof"]) == aligned_boundary_claim_ids
    assert evidence_veto["context"]["added_defect_ids"] == [
        "CHR53-EVIDENCE-005",
        "CHR53-EVIDENCE-006",
    ]
    assert evidence_veto["context"]["invalidates_snapshot_record"] == ("RCV3-20260812-138")
    expected_workflow_ids = [
        319920551,
        327137040,
        327137044,
        329278452,
        329420317,
    ]
    expected_checkpoints = [
        "BEFORE_CORRECTIVE_PUSH",
        "IN_NEW_EXACT_HEAD_CI",
        "IMMEDIATELY_BEFORE_MERGE",
        "BEFORE_LIVE",
    ]
    assert evidence_veto["context"]["external_boundary"] == {
        "disabled_workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "on_drift": ("FAIL_AND_STOP_NO_PUSH_NO_MERGE_NO_LIVE_PENDING_SEPARATE_OWNER_AUTHORITY"),
        "revalidate": expected_checkpoints,
    }
    assert evidence_veto["context"]["current_push_authorized"] is False
    assert evidence_veto["context"]["live_authorized_now"] is False
    assert evidence_veto["context"]["migration_authorized"] is False
    evidence_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == evidence_veto["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in evidence_edges} == set(evidence_veto["proof"])
    observation_veto = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-140"
    )
    assert observation_veto["record_type"] == "VETO"
    assert observation_veto["decision"] == "PASS_AND_HOLD"
    assert set(observation_veto["proof"]) == current_observation_claim_ids
    assert observation_veto["context"]["added_defect_id"] == ("CHR53-EVIDENCE-007")
    assert observation_veto["context"]["invalidates_snapshot_record"] == ("RCV3-20260812-139")
    assert observation_veto["context"]["full_observation"] == {
        "observed_at": "2026-08-12T22:00:47Z",
        "sanitized_observation_sha256": (
            "f226731b04491264972a3777d3c60d2a6e174cecbf54854d050edecdd8e83803"
        ),
        "preserved": True,
    }
    assert observation_veto["context"]["workflow_state_revalidation"] == {
        "checked_at": "2026-08-12T22:37:31Z",
        "sanitized_observation_sha256": (
            "6d94da1c5bf52d0740732f5606711cbda3ee7b823f1e225729d1158c528eaf58"
        ),
        "disabled_workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
    }
    assert observation_veto["context"]["external_boundary_policy"] == {
        "revalidate": expected_checkpoints,
        "on_drift": ("FAIL_AND_STOP_NO_PUSH_NO_MERGE_NO_LIVE_PENDING_SEPARATE_OWNER_AUTHORITY"),
    }
    assert (
        observation_veto["context"]["prior_observation_hash_preserved_in_historical_lineage"]
        is True
    )
    assert observation_veto["context"]["current_observation_hash_recomputed"] is True
    assert observation_veto["context"]["current_push_authorized"] is False
    assert observation_veto["context"]["live_authorized_now"] is False
    assert observation_veto["context"]["migration_authorized"] is False
    observation_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == observation_veto["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in observation_edges} == set(observation_veto["proof"])
    final_reviews = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-141"
    )
    assert final_reviews["record_type"] == "DECISION"
    assert final_reviews["decision"] == "PASS_AND_HOLD"
    assert set(final_reviews["proof"]) == final_review_claim_ids
    assert final_reviews["context"]["reviewed_snapshot"] == {
        "aggregate_algorithm": ("SHA256_CONCAT_SORTED_UTF8_PATH_NUL_RAW_FILE_SHA256_DIGEST"),
        "aggregate_sha256": ("69b7848a7cf8625b4c252aa7d9d5322c925dfe828488d85cab9097e536f389a8"),
        "changed_path_count": 40,
        "changed_paths_equal_allowed": True,
        "staged_files": 0,
        "ledger_tip": ("a0b942c20bf316bb07d60210479e9f56223a35bd0531c691443d1a63c61c1619"),
        "graph_counts": {"claims": 169, "decision_nodes": 133, "edges": 369},
    }
    assert final_reviews["context"]["reviews"] == {
        "DP5": {"verdict": "PASS", "score": 98, "p0": 0, "p1": 0, "p2": 0},
        "DP6": {"verdict": "PASS", "score": 98, "p0": 0, "p1": 0, "p2": 0},
        "C4": {
            "verdict": "PASS_AND_HOLD",
            "score": 97,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
    }
    assert final_reviews["context"]["red_team_answer"] == "YES"
    assert final_reviews["context"]["pre_push_external_boundary"] == {
        "checked_at": "2026-08-12T23:15:39Z",
        "workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "result": "PASS",
    }
    assert final_reviews["context"]["current_push_authorized"] is True
    assert final_reviews["context"]["merge_authorized_now"] is False
    assert final_reviews["context"]["live_authorized_now"] is False
    assert final_reviews["context"]["migration_authorized"] is False
    final_review_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == final_reviews["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in final_review_edges} == set(final_reviews["proof"])
    push_gate_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-142"
    )
    assert push_gate_correction["record_type"] == "VETO"
    assert push_gate_correction["decision"] == "PASS_AND_HOLD"
    assert set(push_gate_correction["proof"]) == push_gate_claim_ids
    assert push_gate_correction["context"]["added_defect_id"] == ("CHR53-EVIDENCE-008")
    assert push_gate_correction["context"]["invalidates_snapshot_record"] == ("RCV3-20260812-141")
    push_gate_edges = [
        edge
        for edge in graph["edges"]
        if edge["to_decision_id"] == push_gate_correction["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in push_gate_edges} == set(push_gate_correction["proof"])
    status_gate_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260812-143"
    )
    assert status_gate_correction["record_type"] == "VETO"
    assert status_gate_correction["decision"] == "PASS_AND_HOLD"
    assert set(status_gate_correction["proof"]) == status_gate_claim_ids
    assert status_gate_correction["context"]["added_defect_id"] == ("CHR53-EVIDENCE-009")
    assert status_gate_correction["context"]["invalidates_snapshot_record"] == ("RCV3-20260812-142")
    status_gate_edges = [
        edge
        for edge in graph["edges"]
        if edge["to_decision_id"] == status_gate_correction["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in status_gate_edges} == set(
        status_gate_correction["proof"]
    )
    final_correction = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260813-144"
    )
    assert final_correction["record_type"] == "DECISION"
    assert final_correction["decision"] == "PASS_AND_HOLD"
    assert set(final_correction["proof"]) == final_correction_claim_ids
    assert final_correction["context"]["failed_exact_head_run"] == {
        "attempt": 1,
        "head_sha": "78ad4f7c1a9368f26c070aad209d3ff670b05b47",
        "rerun_performed": False,
        "run_id": 31651412900,
        "sole_failing_test_per_profile": (
            "tests/jalon10/test_workflows_and_guards.py::"
            "test_ci_replays_frozen_jalon10_on_windows_before_linux_checks"
        ),
        "profile_results": {
            "superuser": {
                "job_id": 94297598361,
                "passed": 1981,
                "skipped": 21,
                "failed": 1,
                "targeted_postgresql_contracts": "PASS",
            },
            "non_superuser_createrole": {
                "job_id": 94297598907,
                "passed": 1981,
                "skipped": 21,
                "failed": 1,
                "targeted_postgresql_contracts": "PASS",
            },
        },
        "aggregate_tests_job": {
            "job_id": 94299546212,
            "classification": "FAIL_CLOSED_PREREQUISITE_PROPAGATION",
        },
    }
    assert final_correction["context"]["reviewed_snapshot"] == {
        "aggregate_algorithm": ("SHA256_CONCAT_SORTED_UTF8_PATH_NUL_RAW_FILE_SHA256_DIGEST"),
        "aggregate_sha256": ("f7c9119808e6c65a68e352b069873b7834b899b922dcd896466d07fecf5319e0"),
        "changed_path_count": 41,
        "changed_paths_equal_allowed": True,
        "staged_files": 0,
        "ledger_tip": ("d3d25fca55a44452a2ab2aaf9b76049327526facea92fa0b5ce8f37a4736a9ea"),
        "graph_counts": {"claims": 177, "decision_nodes": 136, "edges": 384},
    }
    assert final_correction["context"]["reviews"] == {
        "DP5": {
            "verdict": "PASS_AND_HOLD",
            "score": 97,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
        "DP6": {
            "verdict": "PASS_AND_HOLD",
            "score": 98,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
        "C4": {
            "verdict": "PASS_AND_HOLD",
            "score": 97,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
    }
    assert final_correction["context"]["red_team_answer"] == "YES"
    assert final_correction["context"]["pre_push_external_boundary"] == {
        "checked_at": "2026-08-13T04:36:21Z",
        "workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "result": "PASS",
    }
    assert final_correction["context"]["current_push_authorized"] is True
    assert final_correction["context"]["second_final_corrective_push"] == {
        "same_existing_pull_request": 53,
        "non_force": True,
        "commit_limit": 1,
        "push_limit": 1,
        "all_other_pushes_authorized": False,
    }
    assert final_correction["context"]["rerun_31634267437_authorized"] is False
    assert final_correction["context"]["rerun_31651412900_authorized"] is False
    assert final_correction["context"]["merge_authorized_now"] is False
    assert final_correction["context"]["live_authorized_now"] is False
    assert final_correction["context"]["migration_authorized"] is False
    assert final_correction["context"]["delivery_effects_since_record_143"] == {
        "git_remote_non_force_pushes": 1,
        "github_actions_exact_head_runs": 1,
        "reruns": 0,
        "merges": 0,
    }
    assert final_correction["context"]["live_or_provider_mutating_effects_since_record_143"] == 0
    final_correction_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == final_correction["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in final_correction_edges} == set(
        final_correction["proof"]
    )
    assert all(
        edge["relation"] == "SUPPORTS" and edge["status"] == "RECORDED"
        for edge in final_correction_edges
    )
    ci_isolation = next(record for record in ledger if record["decision_id"] == "RCV3-20260813-145")
    assert ci_isolation["record_type"] == "DECISION"
    assert ci_isolation["decision"] == "PASS_AND_HOLD"
    assert set(ci_isolation["proof"]) == ci_isolation_claim_ids
    assert ci_isolation["context"]["decision_name"] == (
        "CHRONOS_LOOP53_COMMITTED_SCOPE_CI_ISOLATION_DECISION"
    )
    assert ci_isolation["context"]["added_defect_id"] == "CHR53-CI-010"
    assert ci_isolation["context"]["failure"] == (
        "WORKTREE_CONTAMINATION_BY_RESTORED_WINDOWS_ARTIFACT"
    )
    assert ci_isolation["context"]["failed_exact_head_run"] == {
        "run_id": 31668336473,
        "attempt": 1,
        "head_sha": "74c0cf8ca6c579d5afafbfdf767b0cf0f982cb0f",
        "rerun_performed": False,
        "aggregate_tests_job": 94350863752,
        "repository_wide_result": "1990 passed, 12 skipped, 1 failed",
        "contaminating_path": "reports/pattern-research/campaign-summary.json",
        "scientific_manifest_validation": "PASS",
    }
    assert ci_isolation["context"]["committed_scope_contract"] == {
        "old_scope_basis": "BASE_VS_WORKTREE",
        "old_scope_union_untracked": True,
        "new_scope_basis": "BASE_TREE_VS_HEAD_TREE",
        "exact_path_count": 41,
        "campaign_summary_allowlisted": False,
        "committed_scope_expansion": False,
        "mission_authority_expansion": False,
        "worktree_contamination_regression": "PASS",
        "campaign_summary_head_lf_crlf_invariance": "PASS",
    }
    assert ci_isolation["context"]["reviews"] == {
        "DP5": "PENDING",
        "DP6": "PENDING",
        "C4": "PENDING",
    }
    assert ci_isolation["context"]["current_push_authorized"] is False
    assert ci_isolation["context"]["first_additional_push_authorized"] is False
    assert ci_isolation["context"]["second_additional_push_authorized"] is False
    assert ci_isolation["context"]["rerun_authorized"] is False
    assert ci_isolation["context"]["merge_authorized_now"] is False
    assert ci_isolation["context"]["live_authorized_now"] is False
    assert ci_isolation["context"]["migration_authorized"] is False
    ci_isolation_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == ci_isolation["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in ci_isolation_edges} == set(ci_isolation["proof"])
    assert all(
        edge["relation"] == "SUPPORTS" and edge["status"] == "RECORDED"
        for edge in ci_isolation_edges
    )
    review_binding = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260813-146"
    )
    assert review_binding["record_type"] == "VETO"
    assert review_binding["decision"] == "PASS_AND_HOLD"
    assert set(review_binding["proof"]) == review_binding_claim_ids
    assert review_binding["context"]["added_defect_id"] == "CHR53-EVIDENCE-010"
    assert review_binding["context"]["invalidates_review_binding_record"] == ("RCV3-20260813-145")
    assert review_binding["context"]["record145_immutable"] is True
    assert review_binding["context"]["record145_mislabelled_field"] == (
        "reviewed_substantive_snapshot"
    )
    assert review_binding["context"]["intermediate_snapshot"] == {
        "aggregate_sha256": ("779b73e8447cf7c160c50a2f56bfac94235985277a91d54fff1030e3d1711342"),
        "classification": "UNREVIEWED_PRE_SUFFIX_CANDIDATE",
        "must_not_support_review_or_push": True,
    }
    assert review_binding["context"]["actual_record145_frozen_snapshot"] == {
        "aggregate_algorithm": ("SHA256_CONCAT_SORTED_UTF8_PATH_NUL_RAW_FILE_SHA256_DIGEST"),
        "aggregate_sha256": ("85a584ed5e8745c5faa61cd4c906584e16e66cce924d1fd35d841a4ca825377e"),
        "changed_path_count": 41,
        "changed_paths_equal_allowed": True,
        "staged_files": 0,
        "untracked_files": 0,
        "ledger_tip": ("ce840bece7d35eb2497b1ad302a09b53ebd8302902f60a9ccc8273cb1fc9b09f"),
        "graph_counts": {"claims": 185, "decision_nodes": 138, "edges": 394},
    }
    assert review_binding["context"]["c4_finding"] == {
        "verdict": "NO_GO",
        "score": 93,
        "p0": 0,
        "p1": 1,
        "p2": 0,
        "red_team_answer": "NO",
    }
    assert review_binding["context"]["reviews"] == {
        "DP5": "PENDING",
        "DP6": "PENDING",
        "C4": "PENDING",
    }
    assert review_binding["context"]["current_push_authorized"] is False
    assert review_binding["context"]["first_additional_push_authorized"] is False
    assert review_binding["context"]["second_additional_push_authorized"] is False
    assert review_binding["context"]["rerun_authorized"] is False
    assert review_binding["context"]["merge_authorized_now"] is False
    assert review_binding["context"]["live_authorized_now"] is False
    assert review_binding["context"]["migration_authorized"] is False
    assert review_binding["context"]["delivery_effects_since_record_145"] == {
        "git_remote_non_force_pushes": 0,
        "github_actions_exact_head_runs": 0,
        "reruns": 0,
        "merges": 0,
    }
    assert review_binding["context"]["live_or_provider_mutating_effects_since_record_145"] == 0
    review_binding_edges = [
        edge for edge in graph["edges"] if edge["to_decision_id"] == review_binding["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in review_binding_edges} == set(review_binding["proof"])
    assert all(
        edge["relation"] == "SUPPORTS" and edge["status"] == "RECORDED"
        for edge in review_binding_edges
    )
    ci_isolation_push_gate = next(
        record for record in ledger if record["decision_id"] == "RCV3-20260813-147"
    )
    assert ci_isolation_push_gate["record_type"] == "DECISION"
    assert ci_isolation_push_gate["decision"] == "PASS_AND_HOLD"
    assert set(ci_isolation_push_gate["proof"]) == ci_isolation_push_gate_claim_ids
    assert ci_isolation_push_gate["context"]["reviewed_snapshot"] == {
        "aggregate_algorithm": ("SHA256_CONCAT_SORTED_UTF8_PATH_NUL_RAW_FILE_SHA256_DIGEST"),
        "aggregate_sha256": ("27f150fff626df47c3ecfc51eeb6bd5edb2e9b9fd7d90e15162408e188959f43"),
        "changed_path_count": 41,
        "changed_paths_equal_allowed": True,
        "staged_files": 0,
        "untracked_files": 0,
        "ledger_tip": ("6bc09723de2e341c357b7a185d66dde6fcd17b5959f293676db3d6d76611b59f"),
        "graph_counts": {"claims": 188, "decision_nodes": 139, "edges": 399},
    }
    expected_ci_isolation_reviews = {
        "DP5": {
            "verdict": "PASS_AND_HOLD",
            "score": 97,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
        "DP6": {
            "verdict": "PASS_AND_HOLD",
            "score": 98,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
        "C4": {
            "verdict": "PASS_AND_HOLD",
            "score": 98,
            "p0": 0,
            "p1": 0,
            "p2": 0,
        },
    }
    assert ci_isolation_push_gate["context"]["reviews"] == (expected_ci_isolation_reviews)
    assert ci_isolation_push_gate["context"]["red_team_question"] == (
        "Can runtime artifact restoration alter the committed mission scope verdict?"
    )
    assert ci_isolation_push_gate["context"]["red_team_answer"] == "NO"
    assert ci_isolation_push_gate["context"]["pre_push_external_boundary"] == {
        "checked_at": "2026-08-13T08:22:04Z",
        "workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "result": "PASS",
    }
    assert ci_isolation_push_gate["context"]["current_push_authorized"] is True
    assert ci_isolation_push_gate["context"]["first_additional_push_authorized"] is True
    assert ci_isolation_push_gate["context"]["second_additional_push_authorized"] is False
    assert ci_isolation_push_gate["context"]["rerun_authorized"] is False
    assert ci_isolation_push_gate["context"]["merge_authorized_now"] is False
    assert ci_isolation_push_gate["context"]["live_authorized_now"] is False
    assert ci_isolation_push_gate["context"]["migration_authorized"] is False
    assert ci_isolation_push_gate["context"]["delivery_effects_since_record_146"] == {
        "git_remote_non_force_pushes": 0,
        "github_actions_exact_head_runs": 0,
        "reruns": 0,
        "merges": 0,
    }
    assert (
        ci_isolation_push_gate["context"]["live_or_provider_mutating_effects_since_record_146"] == 0
    )
    ci_isolation_push_gate_edges = [
        edge
        for edge in graph["edges"]
        if edge["to_decision_id"] == ci_isolation_push_gate["decision_id"]
    ]
    assert {edge["from_claim_id"] for edge in ci_isolation_push_gate_edges} == set(
        ci_isolation_push_gate["proof"]
    )
    assert all(
        edge["relation"] == "SUPPORTS" and edge["status"] == "RECORDED"
        for edge in ci_isolation_push_gate_edges
    )
    certification = load_json(
        "reports/activation/chronos-end-to-end-live-path-certification-v1.json"
    )
    inventory = load_json("reports/activation/chronos-residual-defect-inventory-v1.json")
    assert certification["claim_id"] == ("GOV.CHRONOS.END_TO_END.LIVE_PATH.CERTIFICATION.V1.016")
    assert certification["inventory_claim_id"] == ("GOV.CHRONOS.RESIDUAL.DEFECT.INVENTORY.V1.014")
    assert certification["reviews"] == {
        "prior_snapshot_reviews_applicable": True,
        "reviewed_snapshot_aggregate_sha256": (
            "27f150fff626df47c3ecfc51eeb6bd5edb2e9b9fd7d90e15162408e188959f43"
        ),
        "DP5_PLATFORM_SRE": expected_ci_isolation_reviews["DP5"],
        "DP6_EVIDENCE_DBA": expected_ci_isolation_reviews["DP6"],
        "C4_SEC_RED": expected_ci_isolation_reviews["C4"],
        "minimum_required_score": 95,
        "red_team_question": (
            "Can runtime artifact restoration alter the committed mission scope verdict?"
        ),
        "answer": "NO",
    }
    assert certification["corrective_delivery_gate_order"]["current_push_authorized"] is True
    assert certification["corrective_delivery_gate_order"]["current_stage"] == (
        "POST_REVIEW_FIRST_ADDITIONAL_CI_ISOLATION_PUSH_GATE_OPEN"
    )
    assert certification["certification_status"] == (
        "POST_REVIEW_FIRST_ADDITIONAL_CI_ISOLATION_PUSH_GATE_OPEN_PENDING_NEW_EXACT_HEAD_CI"
    )
    assert certification["review_binding_clarification"] == {
        "decision_id": "RCV3-20260813-146",
        "record145_immutable": True,
        "record145_mislabelled_field": "reviewed_substantive_snapshot",
        "intermediate_snapshot": review_binding["context"]["intermediate_snapshot"],
        "actual_record145_frozen_snapshot": review_binding["context"][
            "actual_record145_frozen_snapshot"
        ],
        "c4_finding": review_binding["context"]["c4_finding"],
        "current_snapshot_reviews": {
            "aggregate_sha256": (
                "27f150fff626df47c3ecfc51eeb6bd5edb2e9b9fd7d90e15162408e188959f43"
            ),
            **expected_ci_isolation_reviews,
            "red_team_answer": "NO",
        },
    }
    assert certification["corrective_delivery_gate_order"][
        "first_additional_ci_isolation_push_receipt"
    ] == {
        "decision_id": "RCV3-20260813-147",
        "checked_at": "2026-08-13T08:22:04Z",
        "workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "result": "PASS",
    }
    assert certification["corrective_delivery_gate_order"][
        "second_final_corrective_push_receipt"
    ] == {
        "decision_id": "RCV3-20260813-144",
        "checked_at": "2026-08-13T04:36:21Z",
        "workflow_ids": expected_workflow_ids,
        "expected_state": "disabled_manually",
        "result": "PASS",
    }
    boundary = certification["external_contracts"]["historical_authority_workflow_boundary"]
    assert [item["workflow_id"] for item in boundary["disabled_workflows"]] == (
        expected_workflow_ids
    )
    assert boundary["observed_at"] == "2026-08-12T22:00:47Z"
    canonical_boundary = json.dumps(
        {key: value for key, value in boundary.items() if key != "sanitized_observation_sha256"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert (
        hashlib.sha256(canonical_boundary).hexdigest() == (boundary["sanitized_observation_sha256"])
    )
    assert boundary["sanitized_observation_sha256"] == (
        "f226731b04491264972a3777d3c60d2a6e174cecbf54854d050edecdd8e83803"
    )
    policy = certification["external_contracts"]["historical_authority_workflow_policy"]
    assert policy == {
        "required_workflow_ids": expected_workflow_ids,
        "required_state": "disabled_manually",
        "revalidate": expected_checkpoints,
        "on_state_drift": evidence_veto["context"]["external_boundary"]["on_drift"],
        "authority_matrix_gate": ("CHRONOS_LOOP53_EXTERNAL_AUTHORITY_BOUNDARY_SATISFIED"),
    }
    revalidation = certification["external_contracts"][
        "historical_authority_workflow_state_revalidation"
    ]
    assert revalidation["checked_at"] == "2026-08-12T22:37:31Z"
    assert revalidation["repository"] == "dddur75/robin-stades-ng"
    assert [item["workflow_id"] for item in revalidation["workflows"]] == (expected_workflow_ids)
    assert all(item["state"] == "disabled_manually" for item in revalidation["workflows"])
    canonical_revalidation = json.dumps(
        {
            key: value
            for key, value in revalidation.items()
            if key != "sanitized_observation_sha256"
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert (
        hashlib.sha256(canonical_revalidation).hexdigest()
        == (revalidation["sanitized_observation_sha256"])
    )
    assert revalidation["sanitized_observation_sha256"] == (
        "6d94da1c5bf52d0740732f5606711cbda3ee7b823f1e225729d1158c528eaf58"
    )
    assert all(
        boundary[key]
        for key in (
            "revalidate_before_corrective_push",
            "revalidate_in_new_exact_head_ci",
            "revalidate_immediately_before_merge",
            "revalidate_before_live",
        )
    )
    assert (
        certification["governance"]["legacy_authority_consumers"]["authority_matrix_gate"]
        == "CHRONOS_LOOP53_EXTERNAL_AUTHORITY_BOUNDARY_SATISFIED"
    )
    assert certification["corrective_delivery_gate_order"]["pre_push_external_boundary"] == (
        "REVALIDATE_WORKFLOW_IDS_319920551_327137040_327137044_329278452_"
        "329420317_DISABLED_MANUALLY_OR_ABORT"
    )
    assert certification["governance"]["legacy_authority_consumers"][
        "historical_workflow_state_precondition"
    ] == (
        "WORKFLOW_IDS_319920551_327137040_327137044_329278452_329420317_"
        "DISABLED_MANUALLY_AT_OBSERVATION_AND_REVALIDATED_BEFORE_CORRECTIVE_"
        "PUSH_IN_NEW_EXACT_HEAD_CI_IMMEDIATELY_BEFORE_MERGE_AND_BEFORE_LIVE"
    )
    boundary_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-004"
    )
    assert boundary_defect["external_effect_before_failure"] == (
        "zero in the observed state because workflow IDs 319920551, 327137040, "
        "327137044, 329278452 and 329420317 are disabled_manually; re-enabling "
        "an old workflow would restore its historical bounded R2-read path"
    )
    assert boundary_defect["fix_required"] == (
        "scope consumer revocation to the corrected code revision, preserve "
        "historical refs, bind the exact five disabled workflow IDs and "
        "unprotected ref observations, and require fail-closed revalidation "
        "before the corrective push, in new exact-head CI, immediately before "
        "merge and before any Chronos live authorization"
    )
    assert boundary_defect["test_added"] == (
        "Council binds CODE_AND_EXTERNAL_CONFIGURATION_AS_OF scope, the exact "
        "five workflow IDs/states, all four revalidation checkpoints, historical "
        "ref non-rewrite, zero external-effect expansion and abort-on-drift "
        "preconditions"
    )
    defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-005"
    )
    assert defect["severity"] == "P2"
    assert defect["status"] == "FIXED"
    metric_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-006"
    )
    assert metric_defect["severity"] == "P2"
    assert metric_defect["status"] == "FIXED"
    hash_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-007"
    )
    assert hash_defect["severity"] == "P1"
    assert hash_defect["status"] == "FIXED"
    stage_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-008"
    )
    assert stage_defect["severity"] == "P2"
    assert stage_defect["live_reachable"] is False
    assert stage_defect["status"] == "FIXED"
    status_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-009"
    )
    assert status_defect["severity"] == "P2"
    assert status_defect["live_reachable"] is False
    assert status_defect["status"] == "FIXED"
    production_sources = {
        path
        for path in exact_loop53_paths
        if path.endswith(".py") and not path.startswith("tests/")
    }
    assert len(production_sources) == 12
    assert certification["local_validation"]["mypy_strict"] == (
        "PASS_STRICT_ALL_TWELVE_CHANGED_PRODUCTION_SOURCES"
    )
    ci_defect = next(item for item in inventory["defects"] if item["defect_id"] == "CHR53-CI-009")
    assert ci_defect["severity"] == "P1"
    assert ci_defect["status"] == "FIXED"
    isolation_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-CI-010"
    )
    assert isolation_defect["severity"] == "P1"
    assert isolation_defect["status"] == "FIXED"
    assert isolation_defect["live_reachable"] is False
    review_binding_defect = next(
        item for item in inventory["defects"] if item["defect_id"] == "CHR53-EVIDENCE-010"
    )
    assert review_binding_defect["severity"] == "P1"
    assert review_binding_defect["status"] == "FIXED"
    assert review_binding_defect["live_reachable"] is False
    assert (
        "BASE_TREE_VS_HEAD_TREE"
        in certification["exact_head_ci_history"]["third_failed_run"]["new_scope_basis"]
    )
    assert "reports/pattern-research/campaign-summary.json" not in exact_loop53_paths
    assert inventory["counts"]["discovered"] == 96
    assert inventory["counts"]["fixed"] == 95
    assert inventory["counts"]["p1_discovered"] == 73
    assert inventory["counts"]["p2_discovered"] == 11


def test_scale_policy_has_stop_rules_and_strict_job_ceiling() -> None:
    policy = load_json("configs/experiments/scale-policy-v3.json")
    levels = {level["id"]: level for level in policy["levels"]}
    assert policy["policy_role"] == "CONTROL_AND_RECORD_ONLY"
    assert policy["executes_workloads"] is False
    assert policy["stage_order"] == ["E1", "E2", "E3A", "E3B", "E4"]
    assert list(levels) == policy["stage_order"]
    assert levels["E4"]["absolute_max_minutes_per_job"] == 20
    assert levels["E4"]["max_checkpoint_minutes"] == 5
    assert policy["decisions"] == [
        "PASS_AND_SCALE",
        "PASS_AND_HOLD",
        "FAIL_AND_REDESIGN",
        "FAIL_AND_STOP",
        "BLOCKED_EXTERNAL_ACTION",
    ]
    assert policy["transition_policy"]["automatic_transitions"] == {
        "E1": "E2",
        "E2": "E3A",
        "E3A": "E3B",
        "E3B": "E4",
    }
    assert policy["transition_policy"]["external_effect_default"] == "DENY"
    assert policy["retry_policy"]["similar_failure_key"] == [
        "failure_taxonomy",
        "root_cause_signature",
        "scope",
    ]
    assert policy["retry_policy"]["second_similar_failure"] == ("FAIL_AND_REDESIGN_RETURN_TO_E1")
    assert policy["retry_policy"]["third_unchanged_attempt"] == ("FORBIDDEN_FAIL_AND_STOP")
    assert policy["append_only_journal"]["hash_algorithm"] == "SHA-256"
    assert policy["quality_ready_gate"]["minimum_score"] == 95
    assert policy["implementation_limits"] == {
        "production_lines_max": 1000,
        "test_lines_max": 2000,
        "schema_lines_max": 500,
        "new_dependencies": 0,
        "external_services": 0,
    }


def test_service_capabilities_are_sourced_and_unknowns_are_explicit() -> None:
    config = load_json("configs/platform/service-capabilities-v1.json")
    required = {
        "service",
        "plan_or_tier",
        "capability",
        "limit",
        "official_source",
        "observed_value",
        "observed_at",
        "confidence",
        "fallback",
    }
    services = {entry["service"] for entry in config["capabilities"]}
    assert services == {
        "GitHub Actions",
        "Cloudflare R2",
        "Neon PostgreSQL",
        "ChatGPT Sites/Vinext",
        "API-Football",
        "The Odds API",
        "Codex local runtime",
    }
    assert all(required <= set(entry) for entry in config["capabilities"])
    assert config["unknown_policy"] == "UNKNOWN_NOT_INVENTED"


def test_evidence_graph_and_append_only_ledger_have_mandatory_fields() -> None:
    graph = load_json("reports/evidence/evidence-graph.json")
    claim_fields = {
        "claim_id",
        "claim",
        "scope",
        "source",
        "grain",
        "temporal_class",
        "artifact",
        "hash",
        "code_revision",
        "execution_id",
        "scientific_lineage_id",
        "dataset_lineage_id",
        "status",
        "verified_by",
    }
    claim_ids = [claim["claim_id"] for claim in graph["claims"]]
    registry = load_json("configs/agents/agent-registry-v3.json")
    registered_agents = {agent["agent_id"] for agent in registry["agents"]}
    assert len(claim_ids) == len(set(claim_ids))
    assert all(claim_fields <= set(claim) for claim in graph["claims"])
    assert all(claim["verified_by"] for claim in graph["claims"])
    assert all(set(claim["verified_by"]) <= registered_agents for claim in graph["claims"])
    assert all(
        claim["status"] in {"VERIFIED", "PARTIAL", "BLOCKED", "INVALIDATED", "SUPERSEDED"}
        for claim in graph["claims"]
    )
    assert all(
        len(claim["verified_by"]) >= 2 for claim in graph["claims"] if claim["status"] == "VERIFIED"
    )
    for claim in graph["claims"]:
        if claim["status"] == "SUPERSEDED":
            assert claim.get("superseded_by") in set(claim_ids)
            continue
        if claim["status"] == "INVALIDATED":
            assert claim.get("invalidation_reason")
            continue
        artifact = ROOT / claim["artifact"]
        assert artifact.is_file()
        if len(claim["hash"]) == 64:
            assert artifact_sha256(artifact) == claim["hash"]

    decision_nodes = {
        node["decision_id"]: node["ledger_record_hash"] for node in graph["decision_nodes"]
    }
    edge_ids = [edge["edge_id"] for edge in graph["edges"]]
    assert graph["edges"]
    assert len(edge_ids) == len(set(edge_ids))
    assert all(edge["from_claim_id"] in set(claim_ids) for edge in graph["edges"])
    assert all(edge["to_decision_id"] in decision_nodes for edge in graph["edges"])

    records = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    decision_fields = {
        "decision_id",
        "record_type",
        "date",
        "proposal",
        "objections",
        "proof",
        "decision",
        "dissent",
        "responsible",
        "context",
        "previous_hash",
        "hash_algorithm",
        "hash",
    }
    assert len({record["decision_id"] for record in records}) == len(records)
    assert all(decision_fields <= set(record) for record in records)
    assert set(decision_nodes) == {record["decision_id"] for record in records}
    assert all(decision_nodes[record["decision_id"]] == record["hash"] for record in records)
    assert all(set(record["proof"]) <= set(claim_ids) for record in records)

    previous_hash = "0" * 64
    for record in records:
        assert record["previous_hash"] == previous_hash
        assert record["hash_algorithm"] == "SHA-256"
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]
        previous_hash = record["hash"]

    commit_context_records = [
        record
        for record in records
        if record["record_type"] in {"DECISION", "STAGE_FINISHED"}
        and isinstance(record.get("context"), dict)
        and record["context"].get("commit_context") is True
    ]
    assert commit_context_records
    context = commit_context_records[-1]["context"]
    assert context is not None
    assert {
        "worktree",
        "branch",
        "head",
        "pr",
        "writer",
        "files",
        "targeted_tests",
        "reused_evidence",
    } <= set(context)
    assert all((ROOT / path).is_file() for path in context["files"])


def test_scorecard_weights_total_100_and_stays_fail_closed_until_review() -> None:
    scorecard = load_json("reports/council/governance-quality-score-v3.json")
    assert sum(category["weight"] for category in scorecard["categories"]) == 100
    if not scorecard["reviewed_by"]:
        assert scorecard["ready"] is False
        assert scorecard["total_score"] is None
        assert scorecard["critical_objections_open"] > 0
        assert scorecard["required_evidence_missing"] > 0
    if scorecard["ready"]:
        assert scorecard["status"] == "READY"
        assert scorecard["total_score"] >= scorecard["minimum_ready_score"]
        assert scorecard["critical_objections_open"] == 0
        assert scorecard["required_evidence_missing"] == 0
        assert scorecard["security_locks_weakened"] == 0
        matrix = load_json("configs/agents/mission-activation-matrix-v3.json")
        governance = matrix["missions"]["GOVERNANCE"]
        reviewers = set(scorecard["reviewed_by"])
        assert governance["writer"] not in reviewers
        assert all(
            set(validators) <= reviewers for validators in governance["delivery_keys"].values()
        )


def test_root_instructions_preserve_entry_branch_and_security_locks() -> None:
    instructions = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "codex/hypothesis-universe-experience-v1" in instructions
    assert "rédacteur unique" in instructions
    assert "troisième tentative identique est interdite" in instructions
    for lock in (
        "STORAGE_PAUSED=true",
        "P3_P4_PAUSED=true",
        "PRODUCTION_LOCKED=true",
        "REAL_BETS=false",
        "NO_BET_DEFAULT=true",
        "PROMOTION_LOCKED=true",
        "SOCIAL_PUBLISHING_ENABLED=false",
        "DEMO_MODE_ENABLED=false",
    ):
        assert lock in instructions
    security_locks = load_json("reports/hypothesis-genome/security-locks.json")
    assert security_locks == {
        "DEMO_MODE_ENABLED": False,
        "NO_BET_DEFAULT": True,
        "P3_P4_PAUSED": True,
        "PRODUCTION_LOCKED": True,
        "PROMOTION_LOCKED": True,
        "REAL_BETS": False,
        "SOCIAL_PUBLISHING_ENABLED": False,
        "STORAGE_PAUSED": True,
        "odds_api_credits": 0,
        "paid_weather_calls": 0,
        "provider_calls": 0,
    }
    runtime = (ROOT / "config/runtime.yaml").read_text(encoding="utf-8")
    assert "mode: SIMULATION" in runtime
    assert "real_bets_enabled: false" in runtime


def test_platform_inventory_has_required_safety_columns() -> None:
    audit = load_json("reports/platform/platform-audit.json")
    required = {
        "worktree_path",
        "branch",
        "head",
        "clean",
        "status_count",
        "associated_pr",
        "purpose",
        "safe_to_use",
    }
    assert all(set(worktree) == required for worktree in audit["worktrees"])
    entry = next(
        item
        for item in audit["worktrees"]
        if item["branch"] == "codex/hypothesis-universe-experience-v1"
    )
    assert entry["safe_to_use"] is False
    assert audit["entry_checkout_preserved"] is True
    assert audit["provider_calls"] == 0
    assert audit["odds_credits"] == 0
    assert audit["purchases"] == 0
    assert all("C:/Users/" not in item["worktree_path"] for item in audit["worktrees"])
    assert all(item["worktree_path"].startswith("${") for item in audit["worktrees"])


def test_pr28_non_canonical_fork_archive_is_complete_and_hash_chained() -> None:
    archive = load_json("reports/council/pr28-decision-fork-archive-v1.json")
    assert archive["status"] == "IMMUTABLE_NON_CANONICAL_ARCHIVE"
    assert archive["source"] == {
        "pr": 28,
        "branch": "codex/historical-coverage-denominator-closure-v1",
        "commit": "bd2661650621912a0d340ffedceb84b78fe4bf28",
        "ledger_path": "reports/council/decision-ledger.jsonl",
    }
    records = archive["fork_records"]
    assert [record["decision_id"] for record in records] == [
        "RCV3-20260804-012",
        "RCV3-20260805-013",
        "RCV3-20260805-014",
    ]

    previous_hash = archive["common_prefix"]["head_hash"]
    for record in records:
        assert record["previous_hash"] == previous_hash
        canonical = json.dumps(
            {key: value for key, value in record.items() if key != "hash"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == record["hash"]
        previous_hash = record["hash"]

    fork_suffix = (
        "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records
        )
        + "\n"
    ).encode()
    assert hashlib.sha256(fork_suffix).hexdigest() == archive["fork_suffix_sha256"]

    audit = load_json("reports/coverage/pr28-main-integration-audit-v1.json")
    source = audit["archived_source_evidence"]
    assert source["decision_ledger_sha256"] == (
        "64fb8be9891d34a904782ca612db2d17c17fa71031cdd90f7cbabcc7cc7f8c3e"
    )
    assert source["evidence_graph_sha256"] == (
        "cc76da3134a9f67631fc902199edf682e499ec592c29ad3bd543c725f312c36d"
    )
