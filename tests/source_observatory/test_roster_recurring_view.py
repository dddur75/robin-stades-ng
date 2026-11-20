import pytest

from robin.source_observatory.roster_recurring_view import (
    CAMPAIGN_ID,
    merge_group_candidates,
    merge_group_public,
)


def observed():
    return dict(
        picks=[
            dict(
                id="olbg-tip:1",
                sourceId="SRC_014",
                sourceTipId=1,
                authorId="olbg:10",
                authorUrl="https://www.olbg.com/tipsters/tips/10",
                observedAt="2026-11-20T22:00:00Z",
            )
        ],
        fixtures=[],
        claimId="DATA.GROUP",
        generatedAt="2026-11-20T22:00:00Z",
        rosterCampaign=dict(campaignId="EXACT", authorIds=["olbg:10"], state="collecting"),
    )


def test_group_data_preserves_old_choice_and_adds_only_exact_source_author():
    old = dict(observed()["picks"][0], observedAt="2026-11-20T20:00:00Z")
    base = dict(picks=[old], claimId="OLD", generatedAt="2026-11-20T21:00:00Z")
    value = merge_group_public(base, observed())
    assert value["picks"] == [old] and value["distinctPicks"] == 1
    assert value["rosterCampaign"]["state"] == "collecting"


def test_group_enables_only_exact_documentary_join_and_active_author():
    row = dict(
        id="candidate",
        sourceUrl="https://www.olbg.com/tipsters/tips/10",
        origin=dict(sheet="Catalogue", row=5),
        qualification=dict(picks=[], personallyProven=True),
        collectionEnabled=False,
    )
    witness = dict(
        candidateId="candidate",
        sourceUrl=row["sourceUrl"],
        sheet="Catalogue",
        row=5,
        qualification={},
    )
    base = dict(
        candidates=[row, dict(row, id="wrong")],
        rosterAssessments=[witness],
        qualification=dict(status="ok"),
    )
    value = merge_group_candidates(base, observed(), True)
    assert [r["collectionEnabled"] for r in value["candidates"]] == [True, False]
    assert value["candidates"][0]["qualification"]["rosterCampaignId"] == "EXACT"
    assert not base["candidates"][0]["collectionEnabled"]
    assert not merge_group_candidates(base, observed(), False)["candidates"][0]["collectionEnabled"]


def test_stopped_author_keeps_archived_choices_and_loses_only_its_grant():
    row = dict(
        id="candidate",
        sourceUrl="https://www.olbg.com/tipsters/tips/10",
        origin=dict(sheet="Catalogue", row=5),
        qualification=dict(picks=[], personallyProven=True),
        collectionEnabled=False,
    )
    witness = dict(
        candidateId="candidate",
        sourceUrl=row["sourceUrl"],
        sheet="Catalogue",
        row=5,
        qualification={},
    )
    base = dict(candidates=[row], rosterAssessments=[witness], qualification=dict(status="ok"))
    first = merge_group_candidates(base, observed(), True)
    stopped = observed()
    stopped["rosterCampaign"]["authorIds"] = []
    last = merge_group_candidates(first, stopped, True)
    assert not last["candidates"][0]["collectionEnabled"]
    assert not last["rosterAssessments"][0]["collectionEnabled"]
    assert len(last["candidates"][0]["qualification"]["picks"]) == 1
    assert len(last["rosterAssessments"][0]["qualification"]["picks"]) == 1


def test_group_rejects_contradiction_and_never_uses_qualification_as_source_clock():
    old = dict(observed()["picks"][0], observedAt="2026-11-20T20:00:00Z")
    base = dict(picks=[old], claimId="OLD", generatedAt="2026-11-20T23:00:00Z")
    assert merge_group_public(base, observed())["sourceObservedThrough"] == "2026-11-20T22:00:00Z"
    changed = observed()
    changed["picks"][0]["selection"] = "Changed"
    with pytest.raises(ValueError, match="contradicts"):
        merge_group_public(base, changed)


@pytest.mark.parametrize("failure", ["qualification", "join"])
def test_owned_grant_is_revoked_before_qualification_and_join_fallbacks(failure):
    source = "https://www.olbg.com/tipsters/tips/10"
    row = dict(
        id="candidate",
        sourceUrl=source,
        origin=dict(sheet="Catalogue", row=5),
        qualification=dict(picks=[], rosterCampaignId=CAMPAIGN_ID),
        collectionEnabled=True,
    )
    case = dict(
        candidateId="candidate",
        sourceUrl=source,
        sheet="Catalogue",
        row=5,
        qualification=dict(rosterCampaignId=CAMPAIGN_ID),
        collectionEnabled=True,
    )
    base = dict(
        candidates=[row],
        rosterAssessments=[case],
        qualification=dict(status="unavailable" if failure == "qualification" else "ok"),
    )
    if failure == "join":
        row["origin"]["row"] = 6
    value = merge_group_candidates(
        base,
        dict(
            observed(),
            rosterCampaign=dict(observed()["rosterCampaign"], campaignId=CAMPAIGN_ID, authorIds=[]),
        ),
        False,
    )
    assert not value["candidates"][0]["collectionEnabled"]
    assert not value["rosterAssessments"][0]["collectionEnabled"]
