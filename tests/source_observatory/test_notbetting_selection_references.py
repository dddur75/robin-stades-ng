"""Synthetic Flight-reference selection; no source payloads or network."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest

from robin.source_observatory.notbetting_prospective import qualify_documents
from robin.source_observatory.notbetting_selection import select_records

UID = "11111111-1111-1111-1111-111111111111"
KO = "2026-11-27T19:30:00+00:00"
SHA = "a" * 64


def row(competition: str = "$a:league") -> dict[str, Any]:
    return dict(
        id="22222222-2222-2222-2222-222222222222",
        event="Synthetic Home - Synthetic Away",
        pick="Synthetic opaque",
        competition=competition,
        date=KO,
        createdAt=KO,
        kind="PICK",
        status="PUBLISHED",
        isReco=False,
        tipsterId=UID,
        tipster=dict(
            user=dict(id=UID, username="Synthetic Owner", tipster=dict(id=UID, userId=UID))
        ),
    )


def select(documents: dict[str, Any], budget: int = 150000) -> dict[str, Any]:
    return select_records(documents, competition="Bundesliga", shared_budget={"remaining": budget})


def test_references_resolve_before_quota_and_keep_original_object() -> None:
    target = row()
    others = [row("$b:league") for _ in range(4)]
    documents = {"0": others + [target], "a": {"league": "Bundesliga"}, "b": {"league": "NBA"}}
    result = select(documents)
    assert result["records"] == [target] and result["records"][0] is target
    diag = result["diagnostics"]
    assert diag["referenceVisitedNodes"] > 0
    assert (
        diag["selectionVisitedNodes"]
        == diag["physicalVisitedNodes"] + diag["referenceVisitedNodes"]
    )
    assert diag["globalCoverage"] == "UNKNOWN" and diag["admissions"] == 0


@pytest.mark.parametrize(
    ("reference", "extra"),
    [
        ("$a:league", {"a": {"isPaid": True, "league": "Bundesliga"}}),
        ("$a:league", {"a": {"league": "$a:league"}}),
        ("$0a:league", {"0a": {"league": "Bundesliga"}}),
        ("$L1", {}),
        ("$a:league", {"__flight_import_ids": ["a"], "a": {"league": "Bundesliga"}}),
        ("$f:league", {}),
        ("$a:secret", {"a": {"secret": "Bundesliga"}}),
        ("$a:00", {"a": ["Bundesliga"]}),
        ("$a:league", {"a": {"league": "$" + "f" * 513}}),
        ("$a:league", {"__flight_import_ids": ["f" * 513], "a": {"league": "Bundesliga"}}),
    ],
)
def test_unsupported_or_gated_reference_is_incomplete(
    reference: str, extra: dict[str, Any]
) -> None:
    result = select({"0": [row(reference)], **extra})
    assert result["records"] == [] and not result["diagnostics"]["selectionComplete"]


def test_canonical_list_index_is_supported() -> None:
    target = row("$a:0")
    assert select({"0": [target], "a": ["Bundesliga"]})["records"][0] is target


def test_shared_work_and_reference_hops_are_bounded() -> None:
    assert not select({"0": [row()], "a": {"league": "Bundesliga"}}, 1)["diagnostics"][
        "selectionComplete"
    ]
    documents: dict[str, Any] = {"0": [row("$1")]}
    documents.update({format(i, "x"): "$" + format(i + 1, "x") for i in range(1, 14)})
    documents["e"] = "Bundesliga"
    result = select(documents)
    assert result["records"] == [] and not result["diagnostics"]["selectionComplete"]


def test_oversized_physical_key_fails_contract() -> None:
    # The physical key contract also rejects this fixture; it does not prove
    # the resolver's oversized segment branch independently.
    with pytest.raises(ValueError, match="SELECTION_CONTRACT"):
        select({"0": [row()], "a": {"x" * 513: "Bundesliga"}})


@pytest.mark.parametrize("field", ["tipster", "createdAt"])
def test_unsupported_candidate_shapes_remain_unselected(field: str) -> None:
    target = row()
    if field == "tipster":
        target["tipster"] = "$c"
    else:
        del target[field]
    assert select({"0": [target], "a": {"league": "Bundesliga"}})["records"] == []


def test_selected_reference_and_literal_have_same_qualified_pick() -> None:
    referenced = {"0": [row()], "a": {"league": "Bundesliga"}}
    literal = deepcopy(referenced)
    literal["0"][0]["competition"] = "Bundesliga"
    fixture = dict(
        id="synthetic",
        home="Synthetic Home",
        away="Synthetic Away",
        kickoff=KO,
        competition="Bundesliga",
        calendarSHA=SHA,
        calendarClaim="SYNTHETIC.CALENDAR",
    )
    kwargs = dict(
        ownerSpec=dict(uid=UID, label="Synthetic Owner"),
        competition="Bundesliga",
        responseSHA=SHA,
        parserSHA=SHA,
        calendarSHA=SHA,
        calendarClaim="SYNTHETIC.CALENDAR",
    )
    first = qualify_documents(
        referenced, [fixture], datetime(2026, 11, 24, tzinfo=timezone.utc), **kwargs
    )
    second = qualify_documents(
        literal, [fixture], datetime(2026, 11, 24, tzinfo=timezone.utc), **kwargs
    )
    assert first["picks"] == second["picks"] and len(first["picks"]) == 1
    assert select(referenced)["records"][0] is referenced["0"][0]
