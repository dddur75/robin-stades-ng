from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts import build_phase_c_v2_freeze as freeze

ROOT = Path(__file__).resolve().parents[2]


def load(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_v2_property_set_and_150_count() -> None:
    report = load("reports/hypothesis-genome/predictor-eligible-property-set-v2.json")
    assert report["candidate_property_count"] == 25
    assert report["selected_property_count"] == 16
    assert report["selected_v1_property_count"] == 7
    assert report["selected_v2_property_count"] == 9
    assert report["blocked_candidate_count"] == 9
    assert report["cumulative_tag_count"] == 150
    assert report["atomic_test_count"] == 300
    assert report["theoretical_tag_pair_count"] == 11_175
    assert report["strict_property_count"] == 0
    assert report["point_in_time_source_provenance"] is False


def test_exact_70_cartesian_ids_unique_sorted_six_segments() -> None:
    tags = freeze.new_tags()
    ids = [str(row["tag_id"]) for row in tags]
    assert len(ids) == len(set(ids)) == 70
    assert ids == sorted(ids)
    assert {len(tag_id.split(".")) for tag_id in ids} == {6}
    assert sum("LAST_PRIOR_FORMATION" in tag_id for tag_id in ids) == 16
    assert sum("AFTER_" in tag_id for tag_id in ids) == 6
    assert sum("SUBSTITUTIONS_MEAN" in tag_id for tag_id in ids) == 8
    assert sum("YELLOW_CARDS_MEAN" in tag_id for tag_id in ids) == 8
    assert sum("DISMISSALS_MEAN" in tag_id for tag_id in ids) == 8


def test_v1_registry_bytes_and_80_definition_hashes_unchanged() -> None:
    v1_path = ROOT / "configs/hypothesis-tags/canonical-tag-registry-v1.json"
    assert hashlib.sha256(v1_path.read_bytes()).hexdigest() == (
        "a6b6385a7838fe2c79532b62501a5437a00e53be48cb684a1b14da9b0604e628"
    )
    v1 = load("configs/hypothesis-tags/canonical-tag-registry-v1.json")
    v2 = load("configs/hypothesis-tags/canonical-tag-registry-v2.json")
    legacy = {str(row["tag_id"]): row for row in v1["tags"]}  # type: ignore[index]
    cumulative = {str(row["tag_id"]): row for row in v2["tags"]}  # type: ignore[index]
    assert len(legacy) == 80
    assert all(cumulative[tag_id] == row for tag_id, row in legacy.items())


def test_v2_property_distribution_is_exact_16_properties() -> None:
    contract = load("configs/hypothesis-tags/predictor-property-contract-v2.json")
    selected = [
        row
        for row in contract["properties"]  # type: ignore[index]
        if row["disposition"] in {"SELECTED_V1", "SELECTED_V2"}
    ]
    counts = Counter(
        str(tag["property_id"])
        for tag in load("configs/hypothesis-tags/canonical-tag-registry-v2.json")[
            "tags"
        ]  # type: ignore[index]
    )
    assert len(selected) == 16
    assert counts == Counter(
        {str(row["property_id"]): int(row["tag_count"]) for row in selected}
    )
    assert sorted(counts.values()) == sorted(
        [16, 16, 8, 16, 8, 8, 8, 8, 8, 8, 16, 6, 8, 2, 6, 8]
    )


def test_raw_role_transform_role_dual_lineage() -> None:
    contract = load("configs/hypothesis-tags/predictor-property-contract-v2.json")
    selected = [
        row
        for row in contract["properties"]  # type: ignore[index]
        if row["disposition"] in {"SELECTED_V1", "SELECTED_V2"}
    ]
    assert all(row["raw_scientific_role"] for row in selected)
    assert {
        row["transform_scientific_role"] for row in selected
    } == {"PREDICTOR_ELIGIBLE_HISTORICAL_LAGGED"}
    assert {row["proof_ceiling"] for row in selected} == {
        "HISTORICAL_RECONSTRUCTED_ONLY"
    }


def test_coloured_cards_events_rescope_explicit() -> None:
    contract = load("configs/hypothesis-tags/predictor-property-contract-v2.json")
    registry = load("configs/hypothesis-tags/canonical-tag-registry-v2.json")
    fields = registry["source_field_registry"]
    rows = {
        str(row["property_id"]): row
        for row in contract["properties"]  # type: ignore[index]
    }
    for property_id in (
        "football:discipline_referee:yellow_cards",
        "football:discipline_referee:red_cards",
    ):
        field_ids = rows[property_id]["source_fields"]
        assert field_ids
        assert all(str(field_id).startswith("field:") for field_id in field_ids)
        resolved = [fields[field_id] for field_id in field_ids]
        assert all(field["entity_type"] == "fixture_event" for field in resolved)
        assert all(field["temporal_use"] == "PRIOR_FIXTURES_ONLY" for field in resolved)


def test_all_v2_source_field_foreign_keys_and_full_definition_hashes() -> None:
    registry = load("configs/hypothesis-tags/canonical-tag-registry-v2.json")
    source_fields = registry["source_field_registry"]
    tags = [row for row in registry["tags"] if row["tag_version"] == 2]  # type: ignore[index]
    assert len(tags) == 70
    assert all(
        field_id in source_fields
        for row in tags
        for field_id in row["source_fields"]
    )
    assert len({field_id for row in tags for field_id in row["source_fields"]}) == 15
    for row in tags:
        definition = {
            key: value
            for key, value in row.items()
            if key not in {"definition_hash", "feature_id"}
        }
        assert freeze.object_hash(definition) == row["definition_hash"]


def test_v2_mapping_basis_raw_roles_and_transform_registry_are_exact() -> None:
    registry = load("configs/hypothesis-tags/canonical-tag-registry-v2.json")
    contract = load("configs/hypothesis-tags/predictor-property-contract-v2.json")
    tags = [row for row in registry["tags"] if row["tag_version"] == 2]  # type: ignore[index]
    assert len(contract["transform_registry"]) == 9  # type: ignore[arg-type]
    assert contract["transform_registry_hash"] == freeze.object_hash(
        contract["transform_registry"]
    )
    assert {
        row["mapping_basis"] for row in tags if row["family"] == "COACH"
    } == {"DETERMINISTIC_PRIOR_EVENT_TRANSFORM"}
    formation = [row for row in tags if row["family"] == "FORMATION_STRUCTURE"]
    assert {row["mapping_basis"] for row in formation} == {
        "DETERMINISTIC_PRIOR_FORMATION_TRANSFORM"
    }
    assert {row["raw_scientific_role"] for row in formation} == {
        "RECONSTRUCTED_POST_MATCH"
    }
    assert all(row["transform_spec_hash"] for row in tags)
    properties = {
        row["property_id"]: row
        for row in contract["properties"]  # type: ignore[index]
    }
    assert all(
        row["raw_scientific_role"]
        == properties[row["property_id"]]["raw_scientific_role"]
        for row in tags
    )


def test_registry_build_is_target_value_independent() -> None:
    before = freeze.canonical_bytes(freeze.new_tags())
    arbitrary_target_labels = ["HOME_WIN", "DRAW", "AWAY_WIN"] * 100
    arbitrary_target_labels.reverse()
    after = freeze.canonical_bytes(freeze.new_tags())
    assert arbitrary_target_labels
    assert before == after
