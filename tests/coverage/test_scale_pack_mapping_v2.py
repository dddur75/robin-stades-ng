from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from robin.governance.autoscale import EvidenceStage, MissionManifest
from tests.coverage.scale_pack_mapping import (
    LEGACY_SCHEMA,
    V2_SCHEMA,
    ScalePackMappingError,
    council_stage_proven,
    resolve_stage,
    validate_source_bindings,
)

ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = ROOT / "configs/data/coverage-scale-pack-manifests-v2.json"
SOURCE_PATH = ROOT / "configs/data/p0-coverage-source-config-v1.json"
MISSION_PATH = ROOT / "configs/data/p0-coverage-evidence-mission-v1.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def mapping() -> dict[str, Any]:
    return load(MAPPING_PATH)


def test_source_bindings_pin_current_lf_hashes_and_legacy_v1() -> None:
    contract = mapping()
    observed = {
        binding["path"]: lf_sha256(ROOT / binding["path"])
        for binding in contract["source_bindings"].values()
    }
    validate_source_bindings(contract, observed_hashes=observed)
    assert observed["configs/data/coverage-scale-pack-manifests-v1.json"] == (
        "21ce418bb326e9c9e247ca80e7f9f6936b85ec9fd9d98d0b511dc9ace3c00d64"
    )
    changed = dict(observed)
    changed["configs/experiments/scale-policy-v3.json"] = "0" * 64
    with pytest.raises(ScalePackMappingError, match="SOURCE_HASH_MISMATCH"):
        validate_source_bindings(contract, observed_hashes=changed)


def test_exact_domain_council_orders_and_composite_e1() -> None:
    contract = mapping()
    assert contract["stage_orders"] == {
        "domain": ["E0", "E1A", "E1B", "E2", "E3A", "E3B", "E4"],
        "council": ["E1", "E2", "E3A", "E3B", "E4"],
    }
    assert not council_stage_proven(
        contract, council_stage="E1", proven_domain_stages={"E1A"}
    )
    assert not council_stage_proven(
        contract, council_stage="E1", proven_domain_stages={"E1B"}
    )
    assert council_stage_proven(
        contract, council_stage="E1", proven_domain_stages={"E1A", "E1B"}
    )
    assert council_stage_proven(
        contract, council_stage="E2", proven_domain_stages={"E2"}
    )


def test_level_cardinalities_and_closure_ceiling_are_exact() -> None:
    contract = mapping()
    ceilings = {"E0": 0, "E1A": 0, "E1B": 0, "E2": 0, "E3A": 16, "E3B": 80, "E4": 480}
    closable = {"E3A", "E3B", "E4"}
    for stage, ceiling in ceilings.items():
        resolution = resolve_stage(
            contract,
            source_schema_version=V2_SCHEMA,
            requested_stage=stage,
            operation="READ",
        )
        assert resolution.maximum_scope_cells == ceiling
        assert resolution.can_close_real_cell is (stage in closable)
        assert resolution.grants_execution_authority is False
    assert contract["levels"]["E1A"]["scope"]["fixture_count"] == 10
    assert contract["levels"]["E1B"]["scope"]["fixtures_per_competition"] == 2
    assert contract["levels"]["E2"]["scope"]["fixture_count"] == 100
    assert contract["levels"]["E4"]["scope"]["cell_count"] == 480
    assert contract["levels"]["E4"]["scope"]["maximum_matrix_jobs"] == 120


def test_four_family_groups_partition_the_sixteen_families_once() -> None:
    contract = mapping()
    source = load(SOURCE_PATH)
    grouped = [family for group in contract["family_groups"].values() for family in group]
    expected = source["scope"]["normalized_p0_families"]
    assert len(grouped) == len(set(grouped)) == 16
    assert set(grouped) == set(expected)


def test_legacy_read_mapping_is_explicit_and_never_writable() -> None:
    contract = mapping()
    expected = {"E0": "E0", "E1": "E1A", "E3": "E3A", "E4": "E4"}
    for legacy, canonical in expected.items():
        resolution = resolve_stage(
            contract,
            source_schema_version=LEGACY_SCHEMA,
            requested_stage=legacy,
            operation="READ",
        )
        assert resolution.canonical_stage == canonical
        assert resolution.legacy_read_only is True
        assert resolution.grants_execution_authority is False
    with pytest.raises(ScalePackMappingError, match="LEGACY_E2_50_NOT_V2_E2_100"):
        resolve_stage(
            contract,
            source_schema_version=LEGACY_SCHEMA,
            requested_stage="E2",
            operation="READ",
        )
    with pytest.raises(ScalePackMappingError, match="LEGACY_SCHEMA_WRITE_FORBIDDEN"):
        resolve_stage(
            contract,
            source_schema_version=LEGACY_SCHEMA,
            requested_stage="E1",
            operation="WRITE",
        )


@pytest.mark.parametrize("stage", ["E1", "E3"])
def test_ambiguous_v2_write_labels_are_rejected(stage: str) -> None:
    with pytest.raises(ScalePackMappingError, match="AMBIGUOUS_STAGE_WRITE_FORBIDDEN"):
        resolve_stage(
            mapping(),
            source_schema_version=V2_SCHEMA,
            requested_stage=stage,
            operation="WRITE",
        )


def test_unknown_schema_stage_operation_and_council_stage_fail_closed() -> None:
    contract = mapping()
    with pytest.raises(ScalePackMappingError, match="UNKNOWN_SCALE_PACK_SCHEMA"):
        resolve_stage(
            contract,
            source_schema_version="unknown",
            requested_stage="E1A",
            operation="READ",
        )
    with pytest.raises(ScalePackMappingError, match="UNKNOWN_STAGE"):
        resolve_stage(
            contract,
            source_schema_version=V2_SCHEMA,
            requested_stage="E9",
            operation="READ",
        )
    with pytest.raises(ScalePackMappingError, match="UNKNOWN_OPERATION"):
        resolve_stage(
            contract,
            source_schema_version=V2_SCHEMA,
            requested_stage="E1A",
            operation=cast(Any, "DELETE"),
        )
    with pytest.raises(ScalePackMappingError, match="UNKNOWN_COUNCIL_STAGE"):
        council_stage_proven(
            contract, council_stage="E9", proven_domain_stages=set()
        )


def test_source_pin_is_exact_get_only_and_not_denominator_authority() -> None:
    source = load(SOURCE_PATH)
    inventory = source["inventory"]
    access = source["access_policy"]
    assert inventory["manifest_sha256"] == (
        "87326eba00976c8cdd00c68e7d24b98c1ccd4f109b38681228f527bcb273e28d"
    )
    assert access["bootstrap_exact_keys"] == [inventory["durable_key"]]
    assert access["mode"] == "EXACT_GET_READ_ONLY"
    assert access["raw_prefix_listing_allowed"] is False
    assert access["derived_prefix_listing_allowed"] is False
    assert access["r2_writes"] == access["r2_deletes"] == access["provider_calls"] == 0
    assert inventory["objects_expected"] == 2321
    assert inventory["segments_expected"] == 371
    assert source["quality_limits"]["inventory_rows_received_is_empirical_denominator"] is False
    assert source["derived_ranking_context"]["verified_sample_denominators"] == 0


def test_identity_registry_is_non_positional_and_architecture_hash_is_exact() -> None:
    registry = load(SOURCE_PATH)["identity_registry"]
    unsigned = {key: value for key, value in registry.items() if key != "architecture_hash"}
    digest = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == registry["architecture_hash"]
    assert registry["position_fields_forbidden"] is True
    assert registry["absence_partition"] == ["SUSPENSION", "INJURY", "UNCLASSIFIABLE"]
    assert registry["third_unchanged_attempt"] == "FAIL_AND_STOP"


def test_mission_has_exactly_eight_fields_and_pins_source_config() -> None:
    mission = load(MISSION_PATH)
    assert set(mission) == {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    assert mission["source_hash"] == lf_sha256(SOURCE_PATH)
    parsed = MissionManifest(
        mission_id=mission["mission_id"],
        authorized_stages=tuple(EvidenceStage(value) for value in mission["authorized_stages"]),
        maximum_stage=EvidenceStage(mission["maximum_stage"]),
        external_effects=tuple(mission["external_effects"]),
        compute_budget=mission["compute_budget"],
        time_budget=mission["time_budget"],
        source_hash=mission["source_hash"],
        expires_at=datetime.fromisoformat(mission["expires_at"].replace("Z", "+00:00")),
    )
    assert parsed.maximum_stage is EvidenceStage.E4
    assert parsed.authorized_stages == tuple(EvidenceStage)
    assert parsed.external_effects == (
        "github_actions_execute_read_only",
        "r2_read_existing_immutable_evidence",
    )


def test_mapping_and_source_config_grant_no_execution_by_themselves() -> None:
    contract = mapping()
    assert contract["contract_role"] == "DOMAIN_STAGE_MAPPING_ONLY_NO_EXECUTION_AUTHORITY"
    assert contract["mission_authority"] == {
        "mapping_grants_workload_authority": False,
        "mapping_grants_scale_authority": False,
        "separate_eight_field_council_manifest_required": True,
        "frozen_level_selection_manifest_before_calculation_required": True,
        "e1a_alone_cannot_mark_council_e1_proven": True,
    }
    effects = contract["effects"]
    assert effects["provider_calls"] == effects["r2_writes"] == effects["r2_deletes"] == 0
    assert effects["remote_sql_reads"] == effects["remote_sql_writes"] == 0
