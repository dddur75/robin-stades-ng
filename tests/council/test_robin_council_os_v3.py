from __future__ import annotations

import hashlib
import json
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
        "COVERAGE_P0",
        "HYPERGRAPH",
        "COCKPIT",
    ]
    assert schema["$defs"]["fact"]["additionalProperties"] is False
    assert schema["$defs"]["risk"]["additionalProperties"] is False


def test_scale_policy_has_stop_rules_and_strict_job_ceiling() -> None:
    policy = load_json("configs/experiments/scale-policy-v3.json")
    levels = {level["id"]: level for level in policy["levels"]}
    assert list(levels) == ["E0", "E1", "E2", "E3", "E4", "E5"]
    assert levels["E0"]["remote_services"] is False
    assert levels["E4"]["absolute_max_minutes_per_job"] == 20
    assert levels["E4"]["max_checkpoint_minutes"] == 5
    assert levels["E5"]["target_minutes_per_job"] == 15
    assert levels["E5"]["absolute_max_minutes_per_job"] == 20
    assert levels["E5"]["max_checkpoint_minutes"] == 5
    assert len(policy["failure_taxonomy"]) == 6
    assert policy["similar_failure_key"] == [
        "failure_taxonomy",
        "root_cause_signature",
        "scope",
    ]
    assert all(
        pack["status"] == "NOT_MATERIALIZED"
        and pack["manifest_required_before_use"] is True
        for pack in policy["permanent_packs"].values()
    )
    assert policy["retry_policy"]["maximum_similar_failures"] == 2
    assert policy["retry_policy"]["third_identical_attempt_forbidden"] is True
    assert policy["quality_ready_gate"]["minimum_score"] == 92


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
    assert all(
        set(claim["verified_by"]) <= registered_agents for claim in graph["claims"]
    )
    assert all(
        claim["status"]
        in {"VERIFIED", "PARTIAL", "BLOCKED", "INVALIDATED", "SUPERSEDED"}
        for claim in graph["claims"]
    )
    assert all(
        len(claim["verified_by"]) >= 2
        for claim in graph["claims"]
        if claim["status"] == "VERIFIED"
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
        node["decision_id"]: node["ledger_record_hash"]
        for node in graph["decision_nodes"]
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
    assert all(
        decision_nodes[record["decision_id"]] == record["hash"] for record in records
    )
    assert all(
        set(record["proof"]) <= set(claim_ids)
        for record in records
    )

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

    precommit = [record for record in records if record["record_type"] == "PRE_COMMIT"]
    assert precommit
    context = precommit[-1]["context"]
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
            set(validators) <= reviewers
            for validators in governance["delivery_keys"].values()
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
