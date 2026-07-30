from __future__ import annotations

from robin.historical_deep.genome import build_genome_availability_projection
from robin.hypothesis_intelligence.ontology import property_universe_hash


def test_genome_projection_preserves_frozen_scientific_definitions() -> None:
    gates = {
        "TEAM": {"status": "READY_STRICT"},
        "PLAYER": {"status": "READY_STRICT"},
        "PLAYER_FORM": {"status": "READY_STRICT"},
        "STARTER_BASELINE": {"status": "READY_STRICT"},
        "LINEUP": {"status": "READY_RECONSTRUCTED"},
        "FORMATION": {"status": "READY_RECONSTRUCTED"},
        "ABSENCE": {"status": "BLOCKED_BY_TEMPORALITY"},
        "DISCIPLINE": {"status": "READY_STRICT"},
        "FOOTEDNESS": {"status": "BLOCKED_BY_SOURCE"},
        "WEATHER": {"status": "BLOCKED_BY_SOURCE"},
    }
    projection = build_genome_availability_projection(gates)
    assert projection["properties"] == 486
    assert projection["scientific_definitions_modified"] is False
    assert projection["frozen_property_universe_hash"] == property_universe_hash()
    assert projection["projection_hash"]
    items = {item["family"]: item for item in projection["items"]}
    assert items["ATTACK"]["derived_availability_status"] == "READY_STRICT"
    assert (
        items["LINEUP_CONTINUITY"]["derived_availability_status"]
        == "READY_RECONSTRUCTED"
    )
    assert items["ABSENCE_RETURN"]["derived_availability_status"] == "DATA_GATE_BLOCKED"
    assert (
        items["FOOTEDNESS_LATERALITY"]["derived_availability_status"]
        == "DATA_GATE_BLOCKED"
    )
