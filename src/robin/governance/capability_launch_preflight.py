"""Pure, local preflight for a future capability-scoped execution mission.

This module validates immutable launch inputs and exercises checkpoint semantics
with synthetic fixtures.  It never reads a remote service and never executes a
scientific workload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MECHANICAL_LABEL = "MECHANICAL_PREFLIGHT_ONLY"
SOURCE_MAIN_SHA = "4d12da146602585a9df58b9db725a1c483d230d0"
CAPABILITY_CONTRACT_CANONICAL_HASH = (
    "2333bf06c788cd5c3de88633711c3f25a5eb4a9d0af2467bd52d4842de8f559a"
)
STAGE_ORDER = ("E1B", "E2", "E3A", "E3B")
ALLOWED_STAGES = (
    "E1B",
    "E2",
    "E3A",
    "E3B",
    "MASK_BENCHMARK",
    "ATOMIC_PROPERTIES",
    "PAIR_SEARCH",
)
FORBIDDEN_STAGES = (
    "TRIPLE_SEARCH",
    "DEPTH_4_PLUS",
    "MODEL_PROMOTION",
    "REAL_BETS",
    "SOCIAL_PUBLICATION",
)
STOP_CONDITIONS = (
    "SOURCE_HASH_MISMATCH",
    "CAPABILITY_CONTRACT_HASH_MISMATCH",
    "GRAIN_CATALOG_HASH_MISMATCH",
    "PROVIDER_INVENTORY_HASH_MISMATCH",
    "MISSING_REQUIRED_RECEIPT_OR_MANIFEST",
    "TEMPORAL_LEAKAGE",
    "UNKNOWN_COERCED",
    "DUPLICATE_OR_AMBIGUOUS_IDENTITY",
    "BUDGET_EXCEEDED",
    "JOB_TIMEOUT",
    "CRITICAL_VETO",
    "FORBIDDEN_EXTERNAL_EFFECT",
    "THIRD_UNCHANGED_ATTEMPT",
)
TRIPLE_GATE_CONDITIONS = (
    "ATOMIC_MASKS_VALIDATED",
    "HISTORICAL_PRICES_ADMISSIBLE",
    "MINIMUM_SUPPORT_FROZEN",
    "TEMPORAL_FOLDS_AVAILABLE",
    "STATISTICAL_CONTRACT_FROZEN",
    "PAIRS_EXECUTED_AND_AUDITED",
    "COMPUTE_BUDGET_APPROVED",
    "CHECKPOINTING_PROVEN",
)
HASHED_INPUTS = {
    "capability_contract_hash": Path(
        "configs/data/capability-scoped-evidence-ladder-v2.json"
    ),
    "grain_catalog_hash": Path("configs/data/football-grain-catalog-v1.json"),
    "provider_inventory_hash": Path("docs/data-sources/PROVIDER-INVENTORY.md"),
}
REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "manifest_role",
    "mission_id",
    "source_main_sha",
    "capability_contract_hash",
    "capability_contract_canonical_hash",
    "grain_catalog_hash",
    "provider_inventory_hash",
    "allowed_stages",
    "maximum_stage",
    "conditional_stage",
    "forbidden_stages",
    "time_budget_hours",
    "compute_budget",
    "r2_read_budget",
    "r2_write_budget",
    "r2_checkpoint_policy",
    "api_football_budget",
    "odds_credit_budget",
    "sql_read_budget",
    "sql_write_budget",
    "checkpoint_interval",
    "retry_policy",
    "concurrency_policy",
    "stop_conditions",
    "current_preflight_consumption",
    "council_activation",
    "triple_search_gate",
}


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    """Hash a JSON-compatible value canonically."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file_lf(path: Path) -> str:
    """Hash committed text bytes with Git's canonical LF convention."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_manifest_contract(
    manifest: Mapping[str, Any],
    *,
    root: Path,
    activation_override: Mapping[str, Any] | None = None,
) -> None:
    """Validate the frozen contract without granting live execution authority."""

    _validate_manifest_values(manifest)
    for field, relative_path in HASHED_INPUTS.items():
        if manifest[field] != sha256_file_lf(root / relative_path):
            raise ValueError(f"{field} mismatch")
    capability_contract = load_json(root / HASHED_INPUTS["capability_contract_hash"])
    if manifest["capability_contract_canonical_hash"] != canonical_sha256(
        capability_contract
    ):
        raise ValueError("capability_contract_canonical_hash mismatch")
    _validate_council_activation_contract(
        manifest,
        root=root,
        activation_override=activation_override,
    )


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    root: Path,
) -> None:
    """Validate frozen inputs and fail closed on live Council expiration."""

    validate_manifest_contract(manifest, root=root)
    validate_council_activation(manifest, root=root)


def _validate_manifest_values(manifest: Mapping[str, Any]) -> None:
    if set(manifest) != REQUIRED_MANIFEST_FIELDS:
        raise ValueError("manifest must contain the exact frozen field set")
    if manifest["schema_version"] != "p0-capability-execution-manifest-v1":
        raise ValueError("schema_version drift")
    if manifest["manifest_role"] != "FUTURE_MISSION_CONTRACT_NOT_ACTIVE":
        raise ValueError("manifest_role drift")
    if manifest["mission_id"] != "p0-capability-execution-long-mission-v1":
        raise ValueError("mission_id drift")
    if manifest["source_main_sha"] != SOURCE_MAIN_SHA:
        raise ValueError("source_main_sha drift")
    if manifest["capability_contract_canonical_hash"] != (
        CAPABILITY_CONTRACT_CANONICAL_HASH
    ):
        raise ValueError("capability contract canonical authority drift")
    if tuple(manifest["allowed_stages"]) != ALLOWED_STAGES:
        raise ValueError("allowed_stages drift")
    if manifest["maximum_stage"] != "PAIR_SEARCH":
        raise ValueError("maximum_stage must stop at PAIR_SEARCH")
    if tuple(manifest.get("forbidden_stages", ())) != FORBIDDEN_STAGES:
        raise ValueError("forbidden stages must remain locked")
    if manifest["time_budget_hours"] != 50:
        raise ValueError("time budget must be fifty hours")

    compute = _mapping(manifest["compute_budget"], "compute_budget")
    checkpoint = _mapping(manifest["checkpoint_interval"], "checkpoint_interval")
    if set(compute) != {
        "target_minutes_per_job",
        "maximum_minutes_per_job",
        "maximum_checkpoint_minutes",
        "maximum_parallel_read_only_jobs",
        "maximum_stateful_writers",
        "maximum_total_job_minutes",
    }:
        raise ValueError("compute budget field set drift")
    if set(checkpoint) != {
        "maximum_minutes",
        "required_after_each_stage",
        "required_after_each_shard",
    }:
        raise ValueError("checkpoint interval field set drift")
    if compute.get("target_minutes_per_job") != 10:
        raise ValueError("target job duration must be ten minutes")
    if compute.get("maximum_minutes_per_job") != 15:
        raise ValueError("job duration ceiling must be fifteen minutes")
    if compute.get("maximum_checkpoint_minutes") != 5:
        raise ValueError("checkpoint duration ceiling must be five minutes")
    if compute.get("maximum_parallel_read_only_jobs") != 5:
        raise ValueError("read-only concurrency ceiling drift")
    if compute.get("maximum_stateful_writers") != 1:
        raise ValueError("exactly one stateful writer is required")
    if compute.get("maximum_total_job_minutes") != 3000:
        raise ValueError("total compute budget drift")
    if checkpoint.get("maximum_minutes") != 5:
        raise ValueError("checkpoint interval must be five minutes")
    if checkpoint.get("required_after_each_stage") is not True:
        raise ValueError("stage checkpoints are mandatory")
    if checkpoint.get("required_after_each_shard") is not True:
        raise ValueError("shard checkpoints are mandatory")

    for field in (
        "api_football_budget",
        "odds_credit_budget",
        "sql_read_budget",
        "sql_write_budget",
    ):
        if manifest[field] != 0:
            raise ValueError(f"{field} must remain zero")
    if manifest["r2_read_budget"] != 10000:
        raise ValueError("R2 future read ceiling drift")
    if manifest["r2_write_budget"] != 256:
        raise ValueError("R2 checkpoint write ceiling drift")
    r2_checkpoint = _mapping(
        manifest.get("r2_checkpoint_policy"), "r2_checkpoint_policy"
    )
    if r2_checkpoint != {
        "prefix": (
            "historical-deep-data/schema-v1/_derived/capability-execution/"
            "checkpoints/mission=p0-capability-execution-long-mission-v1/"
        ),
        "object_types": [
            "compact_checkpoint_json",
            "compact_stage_manifest_json",
        ],
        "append_only": True,
        "raw_payloads": False,
        "overwrites": False,
        "deletes": False,
        "activation_gate": (
            "APPEND_ONLY_R2_CHECKPOINT_DECISION_REQUIRED_BEFORE_FIRST_WRITE"
        ),
    }:
        raise ValueError("R2 checkpoint policy drift")
    current = _mapping(
        manifest.get("current_preflight_consumption"),
        "current_preflight_consumption",
    )
    if set(current) != {
        "r2_reads",
        "r2_writes",
        "api_football_calls",
        "odds_credits",
        "sql_reads",
        "sql_writes",
    } or any(value != 0 for value in current.values()):
        raise ValueError("current preflight consumption must remain exactly zero")

    retry = _mapping(manifest["retry_policy"], "retry_policy")
    if set(retry) != {
        "similar_failure_key",
        "first_similar_failure",
        "second_similar_failure",
        "third_unchanged_attempt",
    }:
        raise ValueError("retry policy field set drift")
    if tuple(retry.get("similar_failure_key", ())) != (
        "failure_taxonomy",
        "root_cause_signature",
        "capability_scope",
    ):
        raise ValueError("similar failure key drift")
    if retry.get("first_similar_failure") != "MINIMAL_FIX_AND_HOLD":
        raise ValueError("first similar failure action drift")
    if retry.get("second_similar_failure") != "REDESIGN_REQUIRED":
        raise ValueError("second similar failure must require redesign")
    if retry.get("third_unchanged_attempt") != "FORBIDDEN_FAIL_AND_STOP":
        raise ValueError("third unchanged attempt must be forbidden")
    if tuple(manifest["stop_conditions"]) != STOP_CONDITIONS:
        raise ValueError("stop_conditions drift")
    concurrency = _mapping(manifest["concurrency_policy"], "concurrency_policy")
    if concurrency != {
        "manual_group": "p0-capability-manual",
        "scheduled_group": "p0-capability-scheduled",
        "mask_group": "hypothesis-mask-build",
        "pair_group": "hypothesis-pair-search",
        "stateful_writer_group": "p0-capability-stateful-writer",
        "isolated_groups": ["cockpit-refresh", "deployment"],
        "cancel_in_progress": False,
        "pending_intent_must_be_committed_before_dispatch": True,
        "overlapping_identical_attempts": False,
    }:
        raise ValueError("concurrency policy drift")
    conditional = _mapping(manifest.get("conditional_stage"), "conditional_stage")
    if conditional != {
        "stage": "E4",
        "authorized": False,
        "activation_rule": (
            "ONLY_IF_A_USEFUL_CAPABILITY_REMAINS_UNDECIDABLE_AND_P0_CLOSURE_IS_NECESSARY"
        ),
    }:
        raise ValueError("E4 must remain conditional and unauthorized")
    council = _mapping(manifest.get("council_activation"), "council_activation")
    if set(council) != {"status", "path", "required_exact_fields"}:
        raise ValueError("Council activation pointer field set drift")
    if council.get("status") != "NOT_ACTIVE_MUST_BE_MATERIALIZED_AT_EXECUTION_START":
        raise ValueError("Council activation must remain inactive during preflight")
    if council.get("path") != (
        "configs/execution/p0-capability-council-activation-v1.json"
    ):
        raise ValueError("Council activation path drift")
    if tuple(council.get("required_exact_fields", ())) != (
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    ):
        raise ValueError("Council activation field contract drift")
    triple_gate = _mapping(manifest.get("triple_search_gate"), "triple_search_gate")
    if set(triple_gate) != {"status", "required_conditions"}:
        raise ValueError("triple gate field set drift")
    if triple_gate.get("status") != "TRIPLE_SEARCH_LOCKED":
        raise ValueError("triple search must remain locked")
    if tuple(triple_gate.get("required_conditions", ())) != TRIPLE_GATE_CONDITIONS:
        raise ValueError("triple search requires eight frozen gates")


def validate_council_activation(
    manifest: Mapping[str, Any],
    *,
    root: Path,
    activation_override: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    """Validate the exact Council envelope and its live UTC expiration."""

    expires_at = _validate_council_activation_contract(
        manifest,
        root=root,
        activation_override=activation_override,
    )
    reference = now or datetime.now(timezone.utc)
    if expires_at <= reference:
        raise ValueError("Council activation is expired")


def _validate_council_activation_contract(
    manifest: Mapping[str, Any],
    *,
    root: Path,
    activation_override: Mapping[str, Any] | None = None,
) -> datetime:
    """Validate Council structure and binding without consulting wall time."""

    council = _mapping(manifest.get("council_activation"), "council_activation")
    activation: Mapping[str, Any] = (
        activation_override
        if activation_override is not None
        else load_json(root / str(council["path"]))
    )
    required = tuple(council["required_exact_fields"])
    if set(activation) != set(required):
        raise ValueError("Council activation must contain exactly eight fields")
    if activation["mission_id"] != manifest["mission_id"]:
        raise ValueError("Council activation mission mismatch")
    if activation["authorized_stages"] != ["E1", "E2", "E3A", "E3B"]:
        raise ValueError("Council activation evidence stages drift")
    if activation["maximum_stage"] != "E3B":
        raise ValueError("Council activation maximum stage drift")
    if activation["external_effects"] != [
        "github_actions_execute_bounded",
        "r2_read_existing_immutable_evidence",
        "r2_write_compact_append_only_checkpoints",
    ]:
        raise ValueError("Council activation external effects drift")
    if activation["compute_budget"] != 3000 or activation["time_budget"] != 180000:
        raise ValueError("Council activation budgets drift")
    detailed = root / "configs/execution/p0-capability-execution-manifest-v1.json"
    if activation["source_hash"] != sha256_file_lf(detailed):
        raise ValueError("Council activation source hash mismatch")
    try:
        expires_at = datetime.fromisoformat(
            str(activation["expires_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError("Council activation expiration is invalid") from exc
    if expires_at.tzinfo is None:
        raise ValueError("Council activation expiration must be timezone-aware")
    return expires_at


def build_golden_pack() -> dict[str, Any]:
    """Build the deterministic five-league, 100-fixture synthetic pack."""

    leagues = [f"SYNTHETIC_LEAGUE_{index}" for index in range(1, 6)]
    fixtures = [
        {
            "fixture_id": f"SYN-L{league_index}-F{fixture_index:02d}",
            "league": league,
            "season": "SYNTHETIC_MINI_SEASON",
        }
        for league_index, league in enumerate(leagues, start=1)
        for fixture_index in range(1, 21)
    ]
    scenarios = [
        {
            "scenario": "CAPABILITY_READY",
            "capability_id": "TEAM",
            "status_after": "READY_STRICT",
            "policy": "CONFIRMED_ONLY",
        },
        {
            "scenario": "CAPABILITY_PARTIAL",
            "capability_id": "INJURY_CONFIRMED",
            "status_after": "MEASURED_PARTIAL",
            "policy": "CONFIRMED_ONLY",
        },
        {
            "scenario": "BLOCKED_BY_SOURCE",
            "capability_id": "PLAYER_FORM",
            "status_after": "BLOCKED_BY_SOURCE",
            "policy": "CONFIRMED_ONLY",
        },
        {
            "scenario": "BLOCKED_BY_TEMPORALITY",
            "capability_id": "LINEUP",
            "status_after": "BLOCKED_BY_TEMPORALITY",
            "policy": "CONFIRMED_ONLY",
        },
        {
            "scenario": "LOCAL_CAMPAIGN_STOP",
            "capability_id": "ABSENCE_CAUSE_EXACT",
            "status_after": "STOPPED_LOCAL_CAMPAIGN",
            "policy": "INCLUDE_UNKNOWN_AS_UNKNOWN",
        },
        {
            "scenario": "UNKNOWN_FIRST_CLASS",
            "capability_id": "ABSENCE_GENERIC",
            "status_after": "MEASURED_PARTIAL",
            "policy": "INCLUDE_UNKNOWN_AS_UNKNOWN",
            "value": "UNKNOWN",
        },
        {
            "scenario": "VALID_EMPTY_RESPONSE",
            "capability_id": "EVENTS",
            "status_after": "NOT_EVALUATED",
            "policy": "CONFIRMED_ONLY",
        },
    ]
    return {
        "label": MECHANICAL_LABEL,
        "leagues": leagues,
        "fixtures": fixtures,
        "stage_fixture_ids": {
            "E1B": [item["fixture_id"] for item in fixtures[:10]],
            "E2": [item["fixture_id"] for item in fixtures],
            "E3A": [item["fixture_id"] for item in fixtures[:20]],
            "E3B": [item["fixture_id"] for item in fixtures],
        },
        "scenarios": scenarios,
        "identity_cases": [
            {
                "case": "DUPLICATE_IDENTITY",
                "records": [
                    {"source_id": "SYN-L1-F01", "canonical_id": "FIXTURE-001"},
                    {"source_id": "SYN-L1-F01", "canonical_id": "FIXTURE-001"},
                ],
                "expected": "REJECTED_LOCAL",
            },
            {
                "case": "AMBIGUOUS_IDENTITY",
                "records": [
                    {"source_id": "SYN-AMBIGUOUS", "canonical_id": "TEAM-A"},
                    {"source_id": "SYN-AMBIGUOUS", "canonical_id": "TEAM-B"},
                ],
                "expected": "REJECTED_LOCAL",
            },
        ],
    }


def run_synthetic_preflight(
    manifest: Mapping[str, Any],
    capability_contract: Mapping[str, Any],
    *,
    resume_checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Exercise progression, local stops, checkpoints, resume and budgets."""

    _validate_manifest_values(manifest)
    _validate_capability_contract(manifest, capability_contract)
    pack = build_golden_pack()
    status_before = {
        str(item["capability_id"]): str(item["status"])
        for item in _sequence(capability_contract.get("capabilities"), "capabilities")
        if isinstance(item, Mapping)
    }
    identity_outcomes = _validate_identity_cases(
        _sequence(pack["identity_cases"], "identity_cases")
    )
    previous_hash: str | None = None
    start_index = 0
    if resume_checkpoint is not None:
        _validate_resume_checkpoint(manifest, capability_contract, resume_checkpoint)
        resume_stage = str(resume_checkpoint["stage"])
        resume_index = STAGE_ORDER.index(resume_stage)
        start_index = (
            resume_index + 1
            if resume_checkpoint["status"] == "COMPLETED"
            else resume_index
        )
        previous_hash = str(resume_checkpoint["checkpoint_hash"])
        fixture_ids_by_stage = _mapping(pack["stage_fixture_ids"], "stage_fixture_ids")
        for completed_stage in STAGE_ORDER[:start_index]:
            completed_ids = _sequence(
                fixture_ids_by_stage[completed_stage], completed_stage
            )
            completed_gates = _build_stage_gates(
                stage=completed_stage,
                fixture_count=len(completed_ids),
                scenarios=_sequence(pack["scenarios"], "scenarios"),
                status_before=status_before,
            )
            status_before.update(
                {
                    str(item["capability_id"]): str(item["status_after"])
                    for item in completed_gates
                }
            )

    checkpoints: list[dict[str, Any]] = []
    gate_records: list[dict[str, Any]] = []
    progression: list[dict[str, str]] = []
    fixture_ids_by_stage = _mapping(pack["stage_fixture_ids"], "stage_fixture_ids")
    for stage_index, stage in enumerate(STAGE_ORDER[start_index:], start=start_index):
        fixture_ids = _sequence(fixture_ids_by_stage[stage], stage)
        stage_gates = _build_stage_gates(
            stage=stage,
            fixture_count=len(fixture_ids),
            scenarios=_sequence(pack["scenarios"], "scenarios"),
            status_before=status_before,
        )
        gate_records.extend(stage_gates)
        checkpoint = _build_checkpoint(
            manifest=manifest,
            stage=stage,
            stage_index=stage_index,
            fixture_ids=fixture_ids,
            previous_hash=previous_hash,
            gate_records=stage_gates,
        )
        checkpoints.append(checkpoint)
        previous_hash = str(checkpoint["checkpoint_hash"])
        status_before.update(
            {
                str(item["capability_id"]): str(item["status_after"])
                for item in stage_gates
            }
        )
        reliable_subspace = any(
            item["scale_decision"] == "PASS_AND_SCALE" for item in stage_gates
        )
        if stage_index + 1 < len(STAGE_ORDER) and reliable_subspace:
            progression.append(
                {
                    "from": stage,
                    "decision": "PASS_AND_SCALE",
                    "to": STAGE_ORDER[stage_index + 1],
                }
            )
        elif stage_index + 1 < len(STAGE_ORDER):
            break

    return {
        "label": MECHANICAL_LABEL,
        "scientific_evidence": false_value(),
        "golden_pack_hash": canonical_sha256(pack),
        "leagues": len(pack["leagues"]),
        "fixtures_e1b": len(fixture_ids_by_stage["E1B"]),
        "fixtures_e2": len(fixture_ids_by_stage["E2"]),
        "fixtures_e3a": len(fixture_ids_by_stage["E3A"]),
        "fixtures_e3b": len(fixture_ids_by_stage["E3B"]),
        "progression": progression,
        "gate_records": gate_records,
        "identity_cases": identity_outcomes,
        "checkpoints": checkpoints,
        "final_checkpoint_hash": previous_hash,
        "resume_from": (
            str(resume_checkpoint["stage"]) if resume_checkpoint is not None else None
        ),
        "external_consumption": {
            "r2_reads": 0,
            "r2_writes": 0,
            "api_football_calls": 0,
            "odds_credits": 0,
            "sql_reads": 0,
            "sql_writes": 0,
        },
        "global_block": false_value(),
        "verdict": "MECHANICAL_PREFLIGHT_PASSED",
    }


def build_synthetic_checkpointed_probe(
    manifest: Mapping[str, Any],
    capability_contract: Mapping[str, Any],
    *,
    stage: str = "E2",
    fixtures_processed: int = 50,
) -> dict[str, Any]:
    """Create a deterministic mid-shard checkpoint for resume testing."""

    _validate_manifest_values(manifest)
    _validate_capability_contract(manifest, capability_contract)
    if stage not in STAGE_ORDER:
        raise ValueError("checkpointed probe stage is invalid")
    pack = build_golden_pack()
    fixture_ids_by_stage = _mapping(pack["stage_fixture_ids"], "stage_fixture_ids")
    status_before = {
        str(item["capability_id"]): str(item["status"])
        for item in _sequence(capability_contract.get("capabilities"), "capabilities")
        if isinstance(item, Mapping)
    }
    previous_hash: str | None = None
    for stage_index, candidate in enumerate(STAGE_ORDER):
        fixture_ids = _sequence(fixture_ids_by_stage[candidate], candidate)
        if candidate == stage:
            if fixtures_processed <= 0 or fixtures_processed >= len(fixture_ids):
                raise ValueError("checkpointed probe must stop inside the shard")
            processed_ids = fixture_ids[:fixtures_processed]
            gates = _build_stage_gates(
                stage=candidate,
                fixture_count=len(processed_ids),
                scenarios=_sequence(pack["scenarios"], "scenarios"),
                status_before=status_before,
            )
            return _build_checkpoint(
                manifest=manifest,
                stage=candidate,
                stage_index=stage_index,
                fixture_ids=fixture_ids,
                processed_fixture_ids=processed_ids,
                previous_hash=previous_hash,
                gate_records=gates,
                status="CHECKPOINTED",
                next_action_override=f"RESUME_{candidate}",
            )
        gates = _build_stage_gates(
            stage=candidate,
            fixture_count=len(fixture_ids),
            scenarios=_sequence(pack["scenarios"], "scenarios"),
            status_before=status_before,
        )
        completed = _build_checkpoint(
            manifest=manifest,
            stage=candidate,
            stage_index=stage_index,
            fixture_ids=fixture_ids,
            previous_hash=previous_hash,
            gate_records=gates,
        )
        previous_hash = str(completed["checkpoint_hash"])
        status_before.update(
            {
                str(item["capability_id"]): str(item["status_after"])
                for item in gates
            }
        )
    raise AssertionError("unreachable checkpointed probe stage")


def false_value() -> bool:
    """Use an explicit function to keep false scientific claims conspicuous."""

    return False


def _gate_record(
    *,
    stage: str,
    fixture_count: int,
    scenario: Mapping[str, Any],
    status_before: Mapping[str, str],
) -> dict[str, Any]:
    capability_id = str(scenario["capability_id"])
    status_after = str(scenario["status_after"])
    expected = 0 if scenario["scenario"] == "VALID_EMPTY_RESPONSE" else fixture_count
    unknown = (
        max(1, fixture_count // 7)
        if scenario["scenario"] in {"LOCAL_CAMPAIGN_STOP", "UNKNOWN_FIRST_CLASS"}
        else max(1, fixture_count // 4)
        if scenario["scenario"] == "CAPABILITY_PARTIAL"
        else 0
    )
    if status_after == "BLOCKED_BY_SOURCE":
        received = 0
        block_reason: str | None = "SYNTHETIC_REQUIRED_SOURCE_ABSENT"
    elif status_after == "BLOCKED_BY_TEMPORALITY":
        received = fixture_count // 2
        block_reason = "SYNTHETIC_AS_OF_CUTOFF_MISSING"
    elif scenario["scenario"] == "CAPABILITY_PARTIAL":
        received = expected - unknown
        block_reason = "SYNTHETIC_COVERAGE_PARTIAL"
    elif expected == 0:
        received = 0
        block_reason = None
    else:
        received = expected
        block_reason = (
            "SYNTHETIC_EXACT_CAUSE_UNKNOWN"
            if status_after == "STOPPED_LOCAL_CAMPAIGN"
            else None
        )
    coverage = None if expected == 0 else round(received / expected, 6)
    if status_after == "STOPPED_LOCAL_CAMPAIGN":
        scale_decision = "FAIL_AND_STOP"
    elif status_after in {"READY_STRICT", "READY_RECONSTRUCTED"}:
        scale_decision = "PASS_AND_SCALE"
    else:
        scale_decision = "PASS_AND_HOLD"
    return {
        "stage": stage,
        "capability_id": capability_id,
        "tested_scope": MECHANICAL_LABEL,
        "grain": "SYNTHETIC_FIXTURE",
        "expected": expected,
        "received": received,
        "unknown": unknown,
        "invalid": 0,
        "coverage": coverage,
        "temporal_class": "SYNTHETIC_AS_OF",
        "status_before": status_before.get(capability_id, "NOT_EVALUATED"),
        "status_after": status_after,
        "scale_decision": scale_decision,
        "block_reason": block_reason,
    }


def _build_stage_gates(
    *,
    stage: str,
    fixture_count: int,
    scenarios: Sequence[Any],
    status_before: Mapping[str, str],
) -> list[dict[str, Any]]:
    return [
        _gate_record(
            stage=stage,
            fixture_count=fixture_count,
            scenario=scenario,
            status_before=status_before,
        )
        for scenario in scenarios
        if isinstance(scenario, Mapping)
    ]


def _validate_resume_checkpoint(
    manifest: Mapping[str, Any],
    capability_contract: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
) -> None:
    required = {
        "mission_id",
        "stage",
        "source_sha",
        "checkpoint_hash",
        "status",
    }
    if required - checkpoint.keys():
        raise ValueError("resume checkpoint is incomplete")
    if checkpoint["stage"] not in STAGE_ORDER:
        raise ValueError("resume stage is invalid")
    pack = build_golden_pack()
    fixture_ids_by_stage = _mapping(pack["stage_fixture_ids"], "stage_fixture_ids")
    status_before = {
        str(item["capability_id"]): str(item["status"])
        for item in _sequence(capability_contract.get("capabilities"), "capabilities")
        if isinstance(item, Mapping)
    }
    previous_hash: str | None = None
    for stage_index, stage in enumerate(STAGE_ORDER):
        fixture_ids = _sequence(fixture_ids_by_stage[stage], stage)
        stage_gates = _build_stage_gates(
            stage=stage,
            fixture_count=len(fixture_ids),
            scenarios=_sequence(pack["scenarios"], "scenarios"),
            status_before=status_before,
        )
        if checkpoint["status"] == "CHECKPOINTED" and stage == checkpoint["stage"]:
            processed = checkpoint.get("fixtures_processed")
            if not isinstance(processed, int) or not 0 < processed < len(fixture_ids):
                raise ValueError("checkpointed cursor is outside the shard")
            processed_ids = fixture_ids[:processed]
            partial_gates = _build_stage_gates(
                stage=stage,
                fixture_count=len(processed_ids),
                scenarios=_sequence(pack["scenarios"], "scenarios"),
                status_before=status_before,
            )
            expected = _build_checkpoint(
                manifest=manifest,
                stage=stage,
                stage_index=stage_index,
                fixture_ids=fixture_ids,
                processed_fixture_ids=processed_ids,
                previous_hash=previous_hash,
                gate_records=partial_gates,
                status="CHECKPOINTED",
                next_action_override=f"RESUME_{stage}",
            )
        else:
            expected = _build_checkpoint(
                manifest=manifest,
                stage=stage,
                stage_index=stage_index,
                fixture_ids=fixture_ids,
                previous_hash=previous_hash,
                gate_records=stage_gates,
            )
        if stage == checkpoint["stage"]:
            if dict(checkpoint) != expected:
                raise ValueError("resume checkpoint does not match the frozen chain")
            return
        previous_hash = str(expected["checkpoint_hash"])
        status_before.update(
            {
                str(item["capability_id"]): str(item["status_after"])
                for item in stage_gates
            }
        )


def _build_checkpoint(
    *,
    manifest: Mapping[str, Any],
    stage: str,
    stage_index: int,
    fixture_ids: Sequence[Any],
    previous_hash: str | None,
    gate_records: Sequence[Mapping[str, Any]],
    processed_fixture_ids: Sequence[Any] | None = None,
    status: str = "COMPLETED",
    next_action_override: str | None = None,
) -> dict[str, Any]:
    processed_ids = processed_fixture_ids or fixture_ids
    next_action = next_action_override or (
        STAGE_ORDER[stage_index + 1]
        if stage_index + 1 < len(STAGE_ORDER)
        else "MASK_BENCHMARK_IF_RELIABLE_SUBSPACE_EXISTS"
    )
    body: dict[str, Any] = {
        "mission_id": manifest["mission_id"],
        "stage": stage,
        "capability_scope": "INDEPENDENT_CAPABILITY_GATES",
        "shard_id": f"SYNTHETIC-{stage}-SHARD-0001",
        "source_sha": manifest["source_main_sha"],
        "dataset_hash": canonical_sha256(fixture_ids),
        "gate_results_hash": canonical_sha256(gate_records),
        "cursor": processed_ids[-1],
        "objects_read": 0,
        "bytes_read": 0,
        "fixtures_processed": len(processed_ids),
        "status": status,
        "next_action": next_action,
        "attempt": 1,
        "previous_checkpoint_hash": previous_hash,
        "external_consumption": {
            "r2_reads": 0,
            "r2_writes": 0,
            "api_football_calls": 0,
            "odds_credits": 0,
            "sql_reads": 0,
            "sql_writes": 0,
        },
    }
    return {**body, "checkpoint_hash": canonical_sha256(body)}


def _validate_identity_cases(cases: Sequence[Any]) -> list[dict[str, str]]:
    outcomes: list[dict[str, str]] = []
    for item in cases:
        case = _mapping(item, "identity_case")
        records = [
            _mapping(record, "identity_record")
            for record in _sequence(case.get("records"), "identity_records")
        ]
        case_id = str(case.get("case"))
        if case_id == "DUPLICATE_IDENTITY":
            keys = [
                (str(record.get("source_id")), str(record.get("canonical_id")))
                for record in records
            ]
            rejected = len(keys) != len(set(keys))
        elif case_id == "AMBIGUOUS_IDENTITY":
            candidates: dict[str, set[str]] = {}
            for record in records:
                candidates.setdefault(str(record.get("source_id")), set()).add(
                    str(record.get("canonical_id"))
                )
            rejected = any(len(values) > 1 for values in candidates.values())
        else:
            raise ValueError("unknown synthetic identity case")
        if not rejected:
            raise ValueError(f"{case_id} was not rejected")
        outcomes.append({"case": case_id, "status": "REJECTED_LOCAL"})
    return outcomes


def _validate_capability_contract(
    manifest: Mapping[str, Any], capability_contract: Mapping[str, Any]
) -> None:
    if canonical_sha256(capability_contract) != manifest.get(
        "capability_contract_canonical_hash"
    ):
        raise ValueError("capability contract does not match the frozen manifest")
    statuses = [
        str(item["status"])
        for item in _sequence(capability_contract.get("capabilities"), "capabilities")
        if isinstance(item, Mapping)
    ]
    if len(statuses) != 18:
        raise ValueError("capability contract must contain eighteen capabilities")
    if statuses.count("NOT_EVALUATED") != 14:
        raise ValueError("capability NOT_EVALUATED count drift")
    if statuses.count("MEASURED_PARTIAL") != 3:
        raise ValueError("capability MEASURED_PARTIAL count drift")
    if statuses.count("STOPPED_LOCAL_CAMPAIGN") != 1:
        raise ValueError("capability local stop count drift")


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be an array")
    return value
