"""An additive admission must preserve history and fail closed on damage."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from robin.source_observatory import retained_choices
from robin.source_observatory.connectors import canonical
from robin.source_observatory.retained_choices import (
    add_retained_candidates,
    add_retained_public,
    merge_retained_candidates,
    merge_retained_public,
)


def test_adding_retained_choices_preserves_history_fixtures_and_is_idempotent():
    old = dict(
        id="old",
        sourceId="SRC_014",
        authorId="olbg:1",
        sourceTipId=1,
        fixtureId="f",
        selection="old",
    )
    base = dict(
        picks=[old],
        fixtures=[dict(id="f", kickoff="2026-11-21T14:30:00Z", matchday=10)],
        claimId="OLD",
        generatedAt="2026-11-21T09:00:00Z",
        sourceObservedThrough="2026-11-21T08:00:00Z",
        campaign=dict(state="halted"),
    )
    before = deepcopy(base)
    new = dict(
        old,
        id="new",
        sourceTipId=2,
        authorId="olbg:2",
        observedAt="2026-11-20T21:00:00Z",
        kickoff="2026-11-21T14:30:00Z",
    )
    bundle = dict(
        claimId="DATA.NEW",
        qualifiedAt="2026-11-21T10:30:00Z",
        picks=[new],
        fixtures=[dict(id="f", kickoff="2026-11-21T14:30:00Z")],
    )
    first = merge_retained_public(base, bundle)
    assert base == before and first["picks"] == [old, new]
    assert first["fixtures"] == base["fixtures"] and first["campaign"] == base["campaign"]
    assert first["sourceObservedThrough"] == base["sourceObservedThrough"]
    assert first["distinctPicks"] == 2 and first["authorCount"] == 2
    assert merge_retained_public(first, bundle) == first


def test_liverpool_retained_admission_does_not_restart_halted_profile():
    claim = "DATA.SOURCE_OBSERVATORY.OLBG.LIVERPOOL.ONE.RETAINED.PREMATCH.20261121"
    old = dict(id="old", authorId="olbg:669088", sourceTipId=1)
    new = dict(
        id="new",
        authorId="olbg:669088",
        authorUrl="https://www.olbg.com/tipsters/tips/669088",
        sourceTipId=2,
        observedAt="2026-11-20T19:00:00Z",
    )
    base = dict(
        picks=[old],
        fixtures=[],
        claimId="OLD",
        generatedAt="2026-11-21T12:00:00Z",
        profileCampaign=dict(state="halted"),
    )
    bundle = dict(
        claimId=claim,
        qualifiedAt="2026-11-21T13:00:00Z",
        picks=[new],
        fixtures=[dict(id="synthetic-new-fixture", kickoff="2026-11-22T16:30:00Z")],
    )
    result = merge_retained_public(base, bundle)
    assert result["picks"] == [old, new] and result["profileCampaign"] == dict(state="halted")
    identity = dict(
        authorId=669088,
        candidateId="c",
        recordId="r",
        sourceUrl=new["authorUrl"],
        sheet="Catalogue",
        row=70,
    )
    candidates = dict(
        candidates=[
            dict(
                id="c",
                sourceUrl=new["authorUrl"],
                origin=dict(sheet="Catalogue", row=70),
                collectionEnabled=False,
                qualification=dict(picks=[old], profileCampaign=dict(state="halted")),
            )
        ],
        qualification=dict(status="ok"),
    )
    enriched = merge_retained_candidates(candidates, dict(bundle=bundle, identities=[identity]))
    assert enriched["candidates"][0]["collectionEnabled"] is False
    assert enriched["candidates"][0]["qualification"]["profileCampaign"] == dict(state="halted")


def test_missing_or_corrupt_addition_preserves_all_previous_objects(tmp_path: Path):
    base = dict(picks=[dict(id="old")], fixtures=[dict(id="f")], campaign=dict(state="halted"))
    before = deepcopy(base)
    assert add_retained_public(base, tmp_path)["picks"] == before["picks"]
    packet = tmp_path / "cockpit/.ci/olbg-six-offline-20261121"
    packet.mkdir(parents=True)
    (packet / "envelope.json").write_text("{}")
    value = add_retained_public(base, tmp_path)
    assert value["picks"] == before["picks"] and value["fixtures"] == before["fixtures"]
    assert value["campaign"] == before["campaign"] and base == before
    assert value["retainedCollection"]["state"] == "unavailable"


def test_candidates_require_documentary_identity_and_never_enable_collection():
    identity = dict(
        authorId=2,
        candidateId="c",
        recordId="r",
        sourceUrl="https://www.olbg.com/tipsters/tips/2",
        sheet="Catalogue",
        row=2,
    )
    pick = dict(
        id="new",
        sourceId="SRC_014",
        authorId="olbg:2",
        authorUrl=identity["sourceUrl"],
        sourceTipId=2,
    )
    good = dict(
        id="c",
        sourceUrl=identity["sourceUrl"],
        origin=dict(sheet="Catalogue", row=2),
        collectionEnabled=False,
        qualification=dict(picks=[], personallyProven=False),
    )
    wrong = dict(deepcopy(good), origin=dict(sheet="Catalogue", row=3))
    base = dict(candidates=[good, wrong], qualification=dict(status="ok"), enabledCount=0)
    before = deepcopy(base)
    envelope = dict(
        identities=[identity],
        bundle=dict(picks=[pick], claimId="DATA.NEW", qualifiedAt="2026-11-21T10:30:00Z"),
    )
    value = merge_retained_candidates(base, envelope)
    assert base == before and value["candidates"][0]["qualification"]["picks"] == [pick]
    assert not value["candidates"][1]["qualification"]["personallyProven"]
    assert value["enabledCount"] == 0 and not value["candidates"][0]["collectionEnabled"]
    assert value["qualification"]["qualifiedCount"] == 1
    assert merge_retained_candidates(value, envelope) == value


def test_new_accepted_fixture_is_added_without_replacing_old_metadata():
    old = dict(id="old", kickoff="2026-11-21T14:30:00Z", matchday=10)
    base = dict(picks=[], fixtures=[old], claimId="OLD", generatedAt="2026-11-21T09:00:00Z")
    new = dict(id="new", kickoff="2026-11-21T14:30:00Z", matchday=10)
    bundle = dict(
        picks=[],
        fixtures=[dict(id="old", kickoff=old["kickoff"]), new],
        claimId=retained_choices.CONTEXTUAL_CLAIM,
        qualifiedAt="2026-11-21T10:30:00Z",
    )
    value = merge_retained_public(base, bundle)
    assert base["fixtures"] == [old] and value["fixtures"] == [old, new]
    assert merge_retained_public(value, bundle) == value


def test_separately_accepted_norwich_fixture_is_additive():
    base = dict(picks=[], fixtures=[], claimId="OLD", generatedAt="2026-11-21T09:00:00Z")
    fixture = dict(id="championship-20261121-norwich-cardiff", kickoff="2026-11-21T12:30:00Z")
    bundle = dict(
        picks=[],
        fixtures=[fixture],
        claimId="DATA.SOURCE_OBSERVATORY.OLBG.NORWICH.SEVEN.PREMATCH.20261121",
        qualifiedAt="2026-11-21T11:36:44Z",
    )
    value = merge_retained_public(base, bundle)
    assert value["fixtures"] == [fixture] and base["fixtures"] == []


def test_conflicting_fixture_never_rewrites_history():
    base = dict(
        picks=[],
        fixtures=[dict(id="old", kickoff="2026-11-21T14:30:00Z", matchday=10)],
        claimId="OLD",
        generatedAt="2026-11-21T09:00:00Z",
    )
    before = deepcopy(base)
    bundle = dict(
        picks=[],
        fixtures=[dict(id="old", kickoff="2026-11-21T15:30:00Z")],
        claimId="DATA.NEW",
        qualifiedAt="2026-11-21T10:30:00Z",
    )
    with pytest.raises(ValueError):
        merge_retained_public(base, bundle)
    assert base == before


def test_historical_six_cannot_recreate_a_missing_fixture():
    base = dict(picks=[], fixtures=[], claimId="OLD", generatedAt="2026-11-21T09:00:00Z")
    bundle = dict(
        picks=[],
        fixtures=[dict(id="missing", kickoff="2026-11-21T14:30:00Z")],
        claimId="DATA.SOURCE_OBSERVATORY.OLBG.SIX.RETAINED.PREMATCH.20261121",
        qualifiedAt="2026-11-21T10:30:00Z",
    )
    with pytest.raises(ValueError):
        merge_retained_public(base, bundle)
    assert base["fixtures"] == []


def test_unavailable_registry_never_reports_loaded_batches_as_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    base = dict(candidates=[], qualification=dict(status="unavailable"))
    source = dict(profiles=[], fixtures=[], calendarSha256="b" * 64)
    bundle = dict(
        claimId=retained_choices.CLAIM,
        recurrence=False,
        sourceResultSha256=sha256(canonical(source) + b"\n").hexdigest(),
        acceptedSourceTipIds=[],
        lexicalParserSha256="a" * 64,
        picks=[],
    )
    raw = (json.dumps(dict(source=source, bundle=bundle, identities=[])) + "\n").encode()
    valid = tmp_path / retained_choices.DIRECTORY
    valid.mkdir(parents=True)
    (valid / "envelope.json").write_bytes(raw)
    monkeypatch.setattr(
        retained_choices,
        "BATCHES",
        (
            (retained_choices.DIRECTORY, sha256(raw).hexdigest(), retained_choices.CLAIM),
            retained_choices.BATCHES[1],
        ),
    )
    target = tmp_path / "cockpit/.ci/olbg-two-context-mappings-20261121"
    target.mkdir(parents=True)
    (target / "envelope.json").write_text("corrupt")
    value = add_retained_candidates(base, tmp_path)
    assert value["qualification"]["retainedCollectionState"] == "unavailable"
    assert all(row["state"] != "accepted" for row in value["retainedAdmissions"])
    assert value["candidates"] == base["candidates"]
