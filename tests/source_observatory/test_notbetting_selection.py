"""Synthetic selector regression; no provider payloads or network."""

from typing import Any

import pytest

from robin.source_observatory.notbetting_selection import select_records


def record(competition: str, number: int, **extra: Any) -> dict[str, Any]:
    return dict(
        competition=competition,
        createdAt="SYNTHETIC",
        event="SYNTHETIC",
        id=str(number),
        kind="PICK",
        pick="SYNTHETIC",
        status="PUBLISHED",
        isReco=False,
        tipster={},
        **extra,
    )


def selected(items: list[dict[str, Any]], competition: str = "Bundesliga") -> dict[str, Any]:
    return select_records(
        {"items": items}, competition=competition, shared_budget={"remaining": 150000}
    )


def test_nonmatching_prefix_does_not_spend_target_quota() -> None:
    target = record("Bundesliga", 4)
    result = selected([record("NBA", i) for i in range(4)] + [target])
    assert result["records"] == [target]
    assert result["records"][0] is target


def test_paid_and_parent_gates_stay_closed() -> None:
    target = record("Bundesliga", 2)
    result = selected(
        [
            record("Bundesliga", 0, isPaid=True),
            record("Bundesliga", 1, requiresSubscription=True),
            target,
        ]
    )
    assert result["records"] == [target]
    blocked = select_records(
        {"requiresAuth": True, "items": [target]},
        competition="Bundesliga",
        shared_budget={"remaining": 150000},
    )
    assert blocked["records"] == []


def test_competition_is_literal_without_alias_or_case_inference() -> None:
    result = selected(
        [
            record(" bundesliga", 0),
            record("Bundesliga2", 1),
            record("bundesliga", 2),
            record("Bundesliga", 3),
        ]
    )
    assert [row["id"] for row in result["records"]] == ["3"]


def test_quota_keeps_global_coverage_unknown() -> None:
    result = selected([record("Bundesliga", i) for i in range(5)])
    assert len(result["records"]) == 4
    diagnostics = result["diagnostics"]
    assert diagnostics["selectionLimitReached"] and not diagnostics["selectionComplete"]
    assert diagnostics["globalCoverage"] == "UNKNOWN"
    assert diagnostics["sourceReady"] is False and diagnostics["admissions"] == 0


def test_sensitive_branches_are_pruned() -> None:
    result = select_records(
        {"cookie": record("Bundesliga", 0), "items": [record("Bundesliga", 1)]},
        competition="Bundesliga",
        shared_budget={"remaining": 150000},
    )
    assert [row["id"] for row in result["records"]] == ["1"]
    assert result["diagnostics"]["prunedSensitiveSubtrees"] == 1


def test_shared_budget_is_consumed_and_exhaustion_is_partial() -> None:
    budget = {"remaining": 150000}
    result = select_records(
        {"items": [record("Bundesliga", 0)]}, competition="Bundesliga", shared_budget=budget
    )
    assert 0 <= budget["remaining"] < 150000
    assert result["diagnostics"]["physicalVisitedNodes"] == 150000 - budget["remaining"]
    empty = select_records(
        {"items": [record("Bundesliga", 1)]},
        competition="Bundesliga",
        shared_budget={"remaining": 0},
    )
    assert empty["records"] == [] and empty["diagnostics"]["omittedBranches"] > 0
    assert empty["diagnostics"]["selectionComplete"] is False


def test_depth_cap_and_diagnostic_privacy() -> None:
    node: dict[str, Any] = record("Bundesliga", 0)
    for _ in range(34):
        node = {"items": [node]}
    result = select_records(node, competition="Bundesliga", shared_budget={"remaining": 150000})
    assert result["records"] == [] and result["diagnostics"]["omittedBranches"] > 0
    assert all(not isinstance(value, (list, dict)) for value in result["diagnostics"].values())
    assert "event" not in result["diagnostics"] and "pick" not in result["diagnostics"]


def test_invalid_competition_and_budget_fail_closed() -> None:
    for competition in ["", " X ", "x" * 201, "x\n"]:
        with pytest.raises(ValueError, match="SELECTION_CONTRACT"):
            selected([], competition)
    with pytest.raises(ValueError, match="SELECTION_CONTRACT"):
        select_records({}, competition="Bundesliga", shared_budget={"remaining": True})
