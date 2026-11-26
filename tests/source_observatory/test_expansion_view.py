from copy import deepcopy

from robin.source_observatory.expansion_view import add_public_expansion, apply_expansion_rows


def inputs():
    url = "https://www.olbg.com/tipsters/tips/383717"
    prior = {
        "personallyProven": False,
        "picks": [],
        "label": "Ancien contrôle",
        "reason": "Inconnu",
    }
    row = {
        "id": "candidate",
        "sourceUrl": url,
        "origin": {"sheet": "Catalogue", "row": 270},
        "qualification": prior,
        "collectionEnabled": True,
    }
    other = {**deepcopy(row), "id": "unrelated", "sourceUrl": "https://example.org/other"}
    base = {
        "candidates": [row, other],
        "qualification": {"status": "ok", "operationalBySource": {"SRC_014": True}},
    }
    case = {
        "id": "candidate",
        "sourceUrl": url,
        "label": "Prouvé",
        "reason": "Source lue",
        "requiredAccess": "Grant de profil",
        "ownerAction": "Récurrence distincte",
        "observedAt": "2026-11-20T09:00:00Z",
        "profileVisited": True,
        "platform": "OLBG",
    }
    report = {"claimId": "SYNTHETIC.EXPANSION", "profiles": [case]}
    bundle = {"picks": [{"id": "new", "authorUrl": url, "sourceTipId": 1}]}
    content = {"platforms": {"OLBG": {"profiles": []}, "TP": {"profiles": []}}}
    return base, report, bundle, content, url


def test_e1_proof_does_not_inherit_another_author_campaign():
    base, report, bundle, content, url = inputs()
    old = deepcopy(base)
    result = apply_expansion_rows(base, report, bundle, content)
    assert result["candidates"][0]["qualification"]["personallyProven"] is True
    assert result["candidates"][0]["collectionEnabled"] is False
    assert result["candidates"][1] == old["candidates"][1] and base == old
    assert apply_expansion_rows(result, report, bundle, content) == result
    enabled = apply_expansion_rows(base, report, bundle, content, active_urls=frozenset({url}))
    assert enabled["candidates"][0]["collectionEnabled"] is True


def test_unknown_qualification_and_missing_packet_preserve_existing_facts(tmp_path):
    base, report, bundle, content, _ = inputs()
    base["qualification"]["status"] = "unavailable"
    result = apply_expansion_rows(base, report, bundle, content)
    assert result["candidates"] == base["candidates"]
    seed = {"picks": [{"id": "old"}], "claimId": "SYNTHETIC.OLD"}
    result = add_public_expansion(seed, tmp_path)
    assert result["picks"] == seed["picks"] and result["sourceExpansion"]["state"] == "unavailable"


def test_corrupt_e2_keeps_old_collection_and_independent_e1(monkeypatch, tmp_path):
    from robin.source_observatory import expanded_olbg_campaign, expansion_view

    directory = tmp_path / "cockpit/.ci/tipsters-expanded-olbg-e2-20261120-v2"
    directory.mkdir(parents=True)
    (directory / "events.jsonl").write_text("null\n", encoding="utf-8")
    monkeypatch.setattr(expanded_olbg_campaign, "validate", lambda _: ({}, {}))
    seed = {"claimId": "SYNTHETIC.OLD", "picks": [{"id": "old", "authorId": "old-author"}]}
    bundle = {
        "claimId": "SYNTHETIC.E1",
        "picks": [{"id": "new", "authorId": "new-author"}],
        "fixtures": [],
    }
    report = {"claimId": "SYNTHETIC.E1", "counts": {"newPrematchChoices": 1}, "profiles": []}
    monkeypatch.setattr(expansion_view, "load_expansion", lambda _: (report, bundle, {}))
    result = expansion_view.add_public_expansion(seed, tmp_path)
    assert {p["id"] for p in result["picks"]} == {"old", "new"}
    assert result["expandedOlbgCampaign"]["state"] == "unavailable"
