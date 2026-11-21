from pathlib import Path
from robin.source_observatory import profile_collection


def test_profile_authority_never_activates_another_author(monkeypatch):
    choice = {
        "id": "olbg-tip:1",
        "authorId": "olbg:669088",
        "authorUrl": "https://www.olbg.com/tipsters/tips/669088",
        "observedAt": "2026-11-20T20:00:00Z",
    }
    monkeypatch.setattr(
        profile_collection,
        "read_campaign",
        lambda path: (
            {
                "picks": [choice],
                "claimId": "RECURRENT",
                "profileCampaign": {"campaignId": "EXACT", "authorUrl": choice["authorUrl"]},
            },
            True,
        ),
    )
    row = {
        "sourceUrl": choice["authorUrl"],
        "origin": {"sheet": "Catalogue", "row": 70},
        "collectionEnabled": False,
        "qualification": {"picks": []},
    }
    other = {
        **row,
        "sourceUrl": "https://www.olbg.com/tipsters/tips/158",
        "qualification": {"picks": []},
    }
    base = {"candidates": [row, other], "qualification": {"status": "ok"}}
    result = profile_collection.add_profile_candidates(base, Path("."))
    assert result["candidates"][0]["collectionEnabled"] is True
    assert result["candidates"][1]["collectionEnabled"] is False
    assert not base["candidates"][0]["collectionEnabled"]


def test_profile_failure_keeps_existing_data(monkeypatch):
    def failed(path):
        raise ValueError("tampered")

    monkeypatch.setattr(profile_collection, "read_campaign", failed)
    base = {"picks": [{"id": "old"}], "claimId": "OLD"}
    result = profile_collection.add_profile_public(base, Path("."))
    assert result["picks"] == base["picks"] and result["profileCampaign"]["state"] == "unavailable"


def test_accepted_recurring_profile_recomputes_qualification_when_family_overlay_is_missing(
    monkeypatch,
):
    choice = {
        "id": "olbg-tip:1",
        "authorId": "olbg:669088",
        "authorUrl": "https://www.olbg.com/tipsters/tips/669088",
        "observedAt": "2026-11-20T20:00:00Z",
    }
    monkeypatch.setattr(
        profile_collection,
        "read_campaign",
        lambda path: (
            {
                "picks": [choice],
                "claimId": "RECURRENT",
                "profileCampaign": {"campaignId": "EXACT", "authorUrl": choice["authorUrl"]},
            },
            True,
        ),
    )
    row = {
        "sourceUrl": choice["authorUrl"],
        "origin": {"sheet": "Catalogue", "row": 70},
        "collectionEnabled": False,
        "qualification": {"picks": [], "personallyProven": False},
    }
    prior = {"qualification": {"picks": [], "personallyProven": True}, "collectionEnabled": False}
    base = {
        "candidates": [prior, row],
        "qualification": {
            "status": "ok",
            "qualifiedCount": 1,
            "familyCollectionState": "unavailable",
        },
    }
    result = profile_collection.add_profile_candidates(base, Path("."))
    assert result["qualification"]["qualifiedCount"] == 2
    assert result["qualification"]["familyCollectionState"] == "unavailable"
