from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from robin.governance import capability_launch_preflight as preflight_module
from robin.governance.capability_launch_preflight import (
    ALLOWED_STAGES,
    FORBIDDEN_STAGES,
    MECHANICAL_LABEL,
    build_golden_pack,
    build_synthetic_checkpointed_probe,
    canonical_sha256,
    load_json,
    run_synthetic_preflight,
    validate_council_activation,
    validate_manifest,
    validate_manifest_contract,
)

ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "configs/execution/p0-capability-execution-manifest-v1.json"
CAPABILITY_PATH = ROOT / "configs/data/capability-scoped-evidence-ladder-v2.json"


@pytest.fixture
def manifest() -> dict[str, object]:
    return load_json(MANIFEST_PATH)


@pytest.fixture
def capability_contract() -> dict[str, object]:
    return load_json(CAPABILITY_PATH)


def test_manifest_is_frozen_and_fail_closed(manifest: dict[str, object]) -> None:
    validate_manifest_contract(manifest, root=ROOT)
    assert tuple(manifest["allowed_stages"]) == ALLOWED_STAGES
    assert tuple(manifest["forbidden_stages"]) == FORBIDDEN_STAGES
    assert manifest["maximum_stage"] == "PAIR_SEARCH"
    assert manifest["r2_read_budget"] == 10_000
    for field in (
        "api_football_budget",
        "odds_credit_budget",
        "sql_read_budget",
        "sql_write_budget",
    ):
        assert manifest[field] == 0
    assert manifest["r2_write_budget"] == 256
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    assert set(activation) == set(manifest["council_activation"]["required_exact_fields"])
    assert activation["maximum_stage"] == "E3B"


def test_manifest_rejects_hash_drift(
    manifest: dict[str, object],
) -> None:
    changed = dict(manifest)
    changed["capability_contract_hash"] = "0" * 64
    with pytest.raises(ValueError, match="capability_contract_hash mismatch"):
        validate_manifest_contract(changed, root=ROOT)


def test_manifest_rejects_budget_checkpoint_stop_and_source_drift(
    manifest: dict[str, object],
) -> None:
    mutations: list[tuple[tuple[str, ...], object]] = [
        (("time_budget_hours",), 5000),
        (("source_main_sha",), "x" * 40),
        (("r2_write_budget",), 0),
        (("compute_budget", "maximum_total_job_minutes"), 999999),
        (("checkpoint_interval", "required_after_each_stage"), False),
        (("checkpoint_interval", "required_after_each_shard"), False),
        (("current_preflight_consumption", "r2_reads"), 999),
    ]
    for keys, value in mutations:
        changed = deepcopy(manifest)
        target = changed
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        with pytest.raises(ValueError):
            validate_manifest_contract(changed, root=ROOT)

    changed = deepcopy(manifest)
    changed["stop_conditions"].remove("UNKNOWN_COERCED")
    with pytest.raises(ValueError, match="stop_conditions drift"):
        validate_manifest_contract(changed, root=ROOT)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("compute_budget",),
        ("checkpoint_interval",),
        ("retry_policy",),
        ("conditional_stage",),
        ("council_activation",),
        ("triple_search_gate",),
    ],
)
def test_manifest_rejects_unknown_authority_fields(
    manifest: dict[str, object], path: tuple[str, ...]
) -> None:
    changed = deepcopy(manifest)
    target = changed
    for key in path:
        target = target[key]
    target["unlimited_external_budget"] = 1
    with pytest.raises(ValueError):
        validate_manifest_contract(changed, root=ROOT)


def test_council_activation_rejects_effect_drift_and_expiration(
    manifest: dict[str, object],
) -> None:
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    changed = deepcopy(activation)
    changed["external_effects"].append("forbidden_effect")
    with pytest.raises(ValueError, match="external effects drift"):
        validate_council_activation(
            manifest,
            root=ROOT,
            activation_override=changed,
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )

    expired = deepcopy(activation)
    expired["expires_at"] = "2026-08-06T00:00:00Z"
    with pytest.raises(ValueError, match="is expired"):
        validate_council_activation(
            manifest,
            root=ROOT,
            activation_override=expired,
            now=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )


def test_frozen_contract_remains_valid_after_wall_clock_expiry(
    manifest: dict[str, object],
) -> None:
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    expires_at = datetime.fromisoformat(
        str(activation["expires_at"]).replace("Z", "+00:00")
    )
    assert expires_at + timedelta(seconds=1) > expires_at
    validate_manifest_contract(manifest, root=ROOT)
    with pytest.raises(ValueError, match="Council activation is expired"):
        validate_manifest(manifest, root=ROOT)


def test_live_activation_is_valid_one_second_before_expiration(
    manifest: dict[str, object],
) -> None:
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    expires_at = datetime.fromisoformat(
        str(activation["expires_at"]).replace("Z", "+00:00")
    )
    validate_council_activation(
        manifest,
        root=ROOT,
        activation_override=activation,
        now=expires_at - timedelta(seconds=1),
    )


@pytest.mark.parametrize("offset_seconds", [0, 1])
def test_live_activation_fails_at_and_after_expiration(
    manifest: dict[str, object], offset_seconds: int
) -> None:
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    expires_at = datetime.fromisoformat(
        str(activation["expires_at"]).replace("Z", "+00:00")
    )
    with pytest.raises(ValueError, match="Council activation is expired"):
        validate_council_activation(
            manifest,
            root=ROOT,
            activation_override=activation,
            now=expires_at + timedelta(seconds=offset_seconds),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("external_effects", [], "external effects drift"),
        ("source_hash", "0" * 64, "source hash mismatch"),
        ("authorized_stages", ["E1"], "evidence stages drift"),
        ("compute_budget", 3001, "budgets drift"),
    ],
)
def test_frozen_contract_rejects_council_authority_drift(
    manifest: dict[str, object], field: str, value: object, message: str
) -> None:
    activation = load_json(
        ROOT / "configs/execution/p0-capability-council-activation-v1.json"
    )
    activation[field] = value
    with pytest.raises(ValueError, match=message):
        validate_manifest_contract(
            manifest,
            root=ROOT,
            activation_override=activation,
        )


def test_golden_pack_has_required_scales_and_edge_cases() -> None:
    pack = build_golden_pack()
    stages = pack["stage_fixture_ids"]
    assert pack["label"] == MECHANICAL_LABEL
    assert len(pack["leagues"]) == 5
    assert len(pack["fixtures"]) == 100
    assert len(stages["E1B"]) == 10
    assert len(stages["E2"]) == 100
    assert len(stages["E3A"]) == 20
    assert len(stages["E3B"]) == 100
    scenario_names = {item["scenario"] for item in pack["scenarios"]}
    assert {
        "CAPABILITY_READY",
        "CAPABILITY_PARTIAL",
        "BLOCKED_BY_SOURCE",
        "BLOCKED_BY_TEMPORALITY",
        "LOCAL_CAMPAIGN_STOP",
        "UNKNOWN_FIRST_CLASS",
        "VALID_EMPTY_RESPONSE",
    } <= scenario_names
    assert {item["case"] for item in pack["identity_cases"]} == {
        "DUPLICATE_IDENTITY",
        "AMBIGUOUS_IDENTITY",
    }


def test_synthetic_progression_is_local_and_not_scientific(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    result = run_synthetic_preflight(manifest, capability_contract)
    assert result["label"] == MECHANICAL_LABEL
    assert result["scientific_evidence"] is False
    assert result["global_block"] is False
    assert [item["to"] for item in result["progression"]] == ["E2", "E3A", "E3B"]
    e3b = [item for item in result["gate_records"] if item["stage"] == "E3B"]
    statuses = {item["capability_id"]: item["status_after"] for item in e3b}
    assert statuses["TEAM"] == "READY_STRICT"
    assert statuses["INJURY_CONFIRMED"] == "MEASURED_PARTIAL"
    assert statuses["PLAYER_FORM"] == "BLOCKED_BY_SOURCE"
    assert statuses["LINEUP"] == "BLOCKED_BY_TEMPORALITY"
    assert statuses["ABSENCE_CAUSE_EXACT"] == "STOPPED_LOCAL_CAMPAIGN"
    assert statuses["EVENTS"] == "NOT_EVALUATED"
    assert "READY" not in statuses.values()
    decisions = {item["capability_id"]: item["scale_decision"] for item in e3b}
    assert decisions["TEAM"] == "PASS_AND_SCALE"
    assert decisions["INJURY_CONFIRMED"] == "PASS_AND_HOLD"
    assert decisions["ABSENCE_GENERIC"] == "PASS_AND_HOLD"
    e2 = [item for item in result["gate_records"] if item["stage"] == "E2"]
    e2_before = {item["capability_id"]: item["status_before"] for item in e2}
    assert e2_before["TEAM"] == "READY_STRICT"
    assert e2_before["INJURY_CONFIRMED"] == "MEASURED_PARTIAL"


def test_progression_stops_without_a_ready_subspace(
    manifest: dict[str, object],
    capability_contract: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = build_golden_pack()
    ready = next(
        item for item in pack["scenarios"] if item["scenario"] == "CAPABILITY_READY"
    )
    ready["status_after"] = "MEASURED_PARTIAL"
    monkeypatch.setattr(preflight_module, "build_golden_pack", lambda: pack)
    result = run_synthetic_preflight(manifest, capability_contract)
    assert result["progression"] == []
    assert [item["stage"] for item in result["checkpoints"]] == ["E1B"]


def test_identity_cases_are_actually_rejected(
    manifest: dict[str, object],
    capability_contract: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = build_golden_pack()
    duplicate = next(
        item for item in pack["identity_cases"] if item["case"] == "DUPLICATE_IDENTITY"
    )
    duplicate["records"][1]["canonical_id"] = "FIXTURE-002"
    monkeypatch.setattr(preflight_module, "build_golden_pack", lambda: pack)
    with pytest.raises(ValueError, match="was not rejected"):
        run_synthetic_preflight(manifest, capability_contract)


def test_unknown_is_never_coerced() -> None:
    pack = build_golden_pack()
    unknown = next(
        item for item in pack["scenarios"] if item["scenario"] == "UNKNOWN_FIRST_CLASS"
    )
    assert unknown["value"] == "UNKNOWN"
    assert unknown["policy"] == "INCLUDE_UNKNOWN_AS_UNKNOWN"


def test_checkpoints_are_complete_and_external_budgets_stay_zero(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    result = run_synthetic_preflight(manifest, capability_contract)
    checkpoints = result["checkpoints"]
    assert [item["stage"] for item in checkpoints] == ["E1B", "E2", "E3A", "E3B"]
    required = {
        "mission_id",
        "stage",
        "capability_scope",
        "shard_id",
        "source_sha",
        "dataset_hash",
        "gate_results_hash",
        "cursor",
        "objects_read",
        "bytes_read",
        "fixtures_processed",
        "status",
        "next_action",
    }
    for checkpoint in checkpoints:
        assert required <= checkpoint.keys()
        assert set(checkpoint["external_consumption"].values()) == {0}
    assert set(result["external_consumption"].values()) == {0}


def test_resume_matches_uninterrupted_final_checkpoint(
    manifest: dict[str, object], capability_contract: dict[str, object], tmp_path: Path
) -> None:
    uninterrupted = run_synthetic_preflight(manifest, capability_contract)
    e2_checkpoint = uninterrupted["checkpoints"][1]
    durable_copy = tmp_path / "checkpoint.json"
    durable_copy.write_text(
        json.dumps(e2_checkpoint, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    resumed = run_synthetic_preflight(
        manifest,
        capability_contract,
        resume_checkpoint=json.loads(durable_copy.read_text(encoding="utf-8")),
    )
    assert resumed["resume_from"] == "E2"
    assert resumed["final_checkpoint_hash"] == uninterrupted["final_checkpoint_hash"]


def test_resume_from_checkpointed_mid_shard_preserves_results(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    uninterrupted = run_synthetic_preflight(manifest, capability_contract)
    checkpointed = build_synthetic_checkpointed_probe(
        manifest,
        capability_contract,
        stage="E2",
        fixtures_processed=50,
    )
    assert checkpointed["status"] == "CHECKPOINTED"
    assert checkpointed["shard_id"] == "SYNTHETIC-E2-SHARD-0001"
    assert checkpointed["cursor"] == "SYN-L3-F10"
    resumed = run_synthetic_preflight(
        manifest,
        capability_contract,
        resume_checkpoint=checkpointed,
    )
    assert resumed["resume_from"] == "E2"
    assert resumed["checkpoints"][0]["stage"] == "E2"
    assert (
        resumed["checkpoints"][0]["previous_checkpoint_hash"]
        == checkpointed["checkpoint_hash"]
    )
    assert (
        resumed["checkpoints"][-1]["dataset_hash"]
        == uninterrupted["checkpoints"][-1]["dataset_hash"]
    )
    assert (
        resumed["checkpoints"][-1]["gate_results_hash"]
        == uninterrupted["checkpoints"][-1]["gate_results_hash"]
    )


def test_repeated_dry_run_is_idempotent(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    first = run_synthetic_preflight(manifest, capability_contract)
    second = run_synthetic_preflight(manifest, capability_contract)
    assert first == second


def test_resume_rejects_tampered_checkpoint(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    result = run_synthetic_preflight(manifest, capability_contract)
    tampered = dict(result["checkpoints"][1])
    tampered["fixtures_processed"] = 101
    with pytest.raises(ValueError, match="frozen chain"):
        run_synthetic_preflight(
            manifest, capability_contract, resume_checkpoint=tampered
        )


def test_resume_rejects_rehashed_checkpoint_with_false_budget_or_lineage(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    result = run_synthetic_preflight(manifest, capability_contract)
    tampered = deepcopy(result["checkpoints"][1])
    tampered["dataset_hash"] = "0" * 64
    tampered["previous_checkpoint_hash"] = "1" * 64
    tampered["objects_read"] = 999
    tampered["external_consumption"]["r2_reads"] = 999
    unhashed = {key: value for key, value in tampered.items() if key != "checkpoint_hash"}
    tampered["checkpoint_hash"] = canonical_sha256(unhashed)
    with pytest.raises(ValueError, match="frozen chain"):
        run_synthetic_preflight(
            manifest, capability_contract, resume_checkpoint=tampered
        )


def test_synthetic_run_rejects_an_altered_capability_contract(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    altered = deepcopy(capability_contract)
    exact = next(
        item
        for item in altered["capabilities"]
        if item["capability_id"] == "ABSENCE_CAUSE_EXACT"
    )
    exact["status"] = "READY_STRICT"
    with pytest.raises(ValueError, match="frozen manifest"):
        run_synthetic_preflight(manifest, altered)


def test_current_scientific_contract_is_not_mutated(
    capability_contract: dict[str, object]
) -> None:
    statuses = {
        item["capability_id"]: item["status"]
        for item in capability_contract["capabilities"]
    }
    assert statuses["ABSENCE_CAUSE_EXACT"] == "STOPPED_LOCAL_CAMPAIGN"
    assert sum(status == "NOT_EVALUATED" for status in statuses.values()) == 14
    assert sum(status == "MEASURED_PARTIAL" for status in statuses.values()) == 3
    assert not any(status.startswith("READY_") for status in statuses.values())


def test_committed_report_matches_deterministic_dry_run(
    manifest: dict[str, object], capability_contract: dict[str, object]
) -> None:
    report = load_json(
        ROOT / "reports/preflight/p0-capability-launch-readiness-v1.json"
    )
    result = run_synthetic_preflight(manifest, capability_contract)
    dry_run = report["dry_run"]
    assert dry_run["label"] == MECHANICAL_LABEL
    assert dry_run["scientific_evidence"] is False
    assert dry_run["golden_pack_hash"] == result["golden_pack_hash"]
    assert dry_run["final_checkpoint_hash"] == result["final_checkpoint_hash"]
    assert dry_run["checkpoint_hashes"] == [
        item["checkpoint_hash"] for item in result["checkpoints"]
    ]
    assert dry_run["gate_result_hashes"] == [
        item["gate_results_hash"] for item in result["checkpoints"]
    ]


def test_readiness_report_science_matches_committed_e1a_evidence() -> None:
    report = load_json(
        ROOT / "reports/preflight/p0-capability-launch-readiness-v1.json"
    )
    scope = load_json(ROOT / "reports/coverage/e1a-capability-scope-status-v1.json")
    unknown = load_json(ROOT / "reports/coverage/e1a-unknown-profile-v1.json")
    state = report["scientific_state_unchanged"]
    identity = scope["absence_identity"]
    assert state["absence_records_total"] == identity["total"]
    assert state["injuries_confirmed"] == identity["injuries_confirmed"]
    assert state["suspensions_confirmed"] == identity["suspensions_confirmed"]
    assert state["absence_cause_unknown"] == identity["absence_cause_unknown"]
    assert state["absence_cause_unknown"] == unknown["unknown_count"]
    assert state["absence_records_total"] == unknown["total_absence_records"]
    assert identity["identity_exact"] is True


def test_platform_audit_keeps_runtime_unknown_and_effects_zero() -> None:
    audit = load_json(
        ROOT / "reports/preflight/p0-capability-platform-audit-v1.json"
    )
    assert audit["audit_mode"] == "CODE_AND_DOCUMENTATION_ONLY_NO_REMOTE_ACCESS"
    assert audit["r2"]["runtime_unknown_status"] == "UNKNOWN_TO_BE_VERIFIED_AT_RUNTIME"
    assert audit["neon"]["runtime_unknown_status"] == "UNKNOWN_TO_BE_VERIFIED_AT_RUNTIME"
    assert set(audit["security"].values()) == {0}
    assert audit["github"]["workflow_inventory"]["total_yml"] == 66
    assert len(audit["github"]["future_workflow_contracts"]) == 6
    assert all(
        item["implementation"] == "NOT_IMPLEMENTED_CONTRACT_ONLY"
        for item in audit["github"]["future_workflow_contracts"]
    )


def test_dashboard_matrix_contains_28_owner_records() -> None:
    path = ROOT / "docs/ux/DASHBOARD-OWNER-DECISION-MATRIX-V1.md"
    text = path.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| UX-")]
    header = next(line for line in text.splitlines() if line.startswith("| decision_id"))
    assert len(rows) == 28
    assert len({row.split("|")[1].strip() for row in rows}) == 28
    for field in (
        "decision_id",
        "route",
        "problem",
        "user_profile",
        "current_state",
        "desired_state",
        "depends_on_real_data",
        "priority",
        "owner_decision_required",
        "implementation_mission",
    ):
        assert field in header


def test_next_mission_prompt_freezes_budgets_and_triples() -> None:
    prompt = (ROOT / "NEXT-MISSION-PROMPT.md").read_text(encoding="utf-8")
    assert "MODÈLE = GPT-5.6 Sol" in prompt
    assert "RAISONNEMENT = Très élevé" in prompt
    assert "DURÉE = 20 à 50 heures utiles" in prompt
    assert "r2_read_budget = 10000 GET" in prompt
    assert "r2_write_budget = 0" in prompt
    assert "api_football_budget = 0" in prompt
    assert "sql_read_budget = 0" in prompt
    assert "TRIPLE_SEARCH_LOCKED" in prompt
    assert "Ne jamais lancer" in prompt or "Ne jamais lancer de triple" in prompt


def test_preflight_text_files_are_utf8_without_known_mojibake() -> None:
    paths = [
        MANIFEST_PATH,
        ROOT / "docs/runbooks/P0-CAPABILITY-EXECUTION-RUNBOOK-V1.md",
        ROOT / "docs/operations/P0-CAPABILITY-CHECKPOINT-AND-RESUME-V1.md",
        ROOT / "docs/ux/DASHBOARD-OWNER-DECISION-MATRIX-V1.md",
        ROOT / "NEXT-MISSION-BRIEF.md",
        ROOT / "NEXT-MISSION-PROMPT.md",
    ]
    forbidden = ("\ufffd", "Ã", "Â", "â€", "ind?pend", "capacit?")
    for path in paths:
        text = path.read_bytes().decode("utf-8")
        assert not any(token in text for token in forbidden), path
