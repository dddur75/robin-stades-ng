from __future__ import annotations

from tests.coverage.denominator_oracle import (
    CALENDAR_PATH,
    calendar_family_status,
    canonical_calendar_property_ids,
    load_json,
)


def test_calendar_fatigue_has_exact_property_level_contract() -> None:
    contract = load_json(CALENDAR_PATH)
    properties = contract["properties"]
    assert len(properties) == len({item["id"] for item in properties}) == 17
    assert {item["id"] for item in properties} == canonical_calendar_property_ids()
    assert contract["current_ready_properties"] == 0
    assert contract["scientific_family_status"] == "PARTIAL"
    assert contract["opens_hypergraph"] is False
    next_match = next(item for item in properties if item["id"] == "next_match_importance")
    assert next_match["status"] == "BLOCKED_STANDINGS_NOT_POINT_IN_TIME"


def test_property_aggregation_never_overstates_the_family() -> None:
    assert calendar_family_status(0) == "CLOSED"
    assert calendar_family_status(1) == "PARTIAL_OPEN_SCOPED"
    assert calendar_family_status(16) == "PARTIAL_OPEN_SCOPED"
    assert calendar_family_status(17) == "READY_STRICT"


def test_team_only_cannot_open_any_calendar_property() -> None:
    contract = load_json(CALENDAR_PATH)
    assert all("fixtures" in item["families"] for item in contract["properties"])
    assert all(item["families"] != ["teams"] for item in contract["properties"])
