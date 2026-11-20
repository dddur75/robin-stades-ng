"""Roster facts must remain distinct from recurrent activation and the L1 register."""

from copy import deepcopy
from pathlib import Path

import pytest

from robin.source_observatory.roster_collection import (
    add_roster_public,
    merge_roster_candidates,
    merge_roster_public,
)


def assessment():
    return dict(
        claimId="DATA.ROSTER",
        qualifiedAt="2026-11-20T21:25:00Z",
        rosterCount=138,
        inventoriedCount=25,
        profiles=[
            dict(
                profile=dict(
                    candidateId="c1",
                    recordId="w1",
                    sheet="Catalogue",
                    row=12,
                    sourceUrl="https://www.olbg.com/tipsters/tips/10",
                    authorId=10,
                ),
                observedAt="2026-11-19T10:00:00Z",
                facts=3,
                omittedRecords=0,
                nativeCount=1,
                opaqueCount=0,
            )
        ],
    )


def test_public_adds_unique_facts_without_rewriting_old_observations():
    previous = dict(
        id="olbg-tip:1",
        sourceId="SRC_014",
        sourceTipId=1,
        authorId="olbg:10",
        selection="Home",
        observedAt="2026-11-20T21:00:00Z",
        firstSeenAt="2026-11-19T09:00:00Z",
        versions=[dict(selection="Home", observedAt="2026-11-19T09:00:00Z")],
    )
    base = dict(picks=[previous], fixtures=[], claimId="OLD", generatedAt="2026-11-20T23:00:00Z")
    before = deepcopy(base)
    older = dict(previous, observedAt="2026-11-19T10:00:00Z")
    new = dict(older, id="olbg-tip:2", sourceTipId=2)
    value = merge_roster_public(base, assessment(), [older, new], [])
    assert base == before and value["picks"][0] == previous
    assert value["distinctPicks"] == 2 and value["authorCount"] == 1
    assert value["generatedAt"] == base["generatedAt"]
    assert value["rosterCollection"]["recurrenceAuthorized"] is False


def test_profile_join_requires_full_documentary_identity_and_never_activates():
    q = dict(
        personallyProven=False,
        picks=[],
        observedAt="2026-11-20T21:00:00Z",
        unadmittedFacts=[
            dict(sourceUrl="https://www.olbg.com/tipsters/tips/10", sourceTipId=1),
            dict(sourceUrl="https://www.olbg.com/tipsters/tips/10", sourceTipId=9),
        ],
    )
    matched = dict(
        id="c1",
        sourceUrl="https://www.olbg.com/tipsters/tips/10",
        origin=dict(sheet="Catalogue", row=12),
        collectionEnabled=False,
        qualification=q,
    )
    mismatch = dict(matched, id="wrong", origin=dict(sheet="Catalogue", row=13))
    base = dict(candidates=[matched, mismatch], count=317, qualification=dict(status="ok"))
    pick = dict(
        id="olbg-tip:1",
        sourceId="SRC_014",
        sourceTipId=1,
        authorId="olbg:10",
        authorUrl=matched["sourceUrl"],
    )
    value = merge_roster_candidates(base, assessment(), [pick])
    assert value["count"] == 317 and len(value["candidates"]) == 2
    assert value["candidates"][0]["qualification"]["personallyProven"]
    assert not value["candidates"][0]["collectionEnabled"]
    assert not value["candidates"][1]["qualification"]["personallyProven"]
    assert value["qualification"]["qualifiedCount"] == 1
    assert len(value["rosterAssessments"]) == 1
    actual = value["candidates"][0]["qualification"]
    assert [f["sourceTipId"] for f in actual["unadmittedFacts"]] == [9]
    assert actual["observedAt"] == q["observedAt"]
    assert actual["rosterObservedAt"] == "2026-11-19T10:00:00Z"


def test_roster_cannot_bypass_failed_original_qualification():
    base = dict(candidates=[], qualification=dict(status="unavailable"))
    value = merge_roster_candidates(base, assessment(), [])
    assert value["qualification"]["rosterCollectionState"] == "unavailable"
    assert "rosterAssessments" not in value


def test_unavailable_new_evidence_preserves_old_public_objects(tmp_path: Path):
    base = dict(picks=[dict(id="old", authorId="a")], claimId="OLD")
    before = deepcopy(base)
    value = add_roster_public(base, tmp_path)
    assert value["picks"] == base["picks"] and base == before
    assert value["rosterCollection"]["state"] == "unavailable"


def test_conflicting_source_identity_does_not_silently_replace_old_choice():
    old = dict(
        id="olbg-tip:1",
        sourceId="SRC_014",
        authorId="olbg:10",
        sourceTipId=1,
        fixtureId="f",
        selection="Home",
        market="source_native",
    )
    base = dict(picks=[old])
    with pytest.raises(ValueError, match="contradicts"):
        merge_roster_public(base, assessment(), [dict(old, selection="Away")], [])
    person = assessment()["profiles"][0]["profile"]
    candidates = dict(
        candidates=[
            dict(
                id=person["candidateId"],
                sourceUrl=person["sourceUrl"],
                origin=dict(sheet=person["sheet"], row=person["row"]),
                qualification=dict(picks=[dict(old, authorUrl=person["sourceUrl"])]),
            )
        ],
        qualification=dict(status="ok"),
    )
    with pytest.raises(ValueError, match="contradicts"):
        merge_roster_candidates(
            candidates, assessment(), [dict(old, authorUrl=person["sourceUrl"], selection="Away")]
        )
