"""Personal use narrows access requirements without inventing collection authority."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from robin.source_observatory.personal_access import apply_personal_access, read_personal_access


def fixture(tmp_path: Path) -> tuple[dict, Path, str]:
    assessment = dict(
        label="Personal facts access to verify",
        reason="Commercial licence not established as necessary",
        requiredAccess="Public route and personal proof",
        ownerAction="Technical qualification, no purchase requested",
        status="personal_route_unverified",
        observedAt="2026-11-20T16:00:00Z",
        evidenceRefs=["PERSONAL.TEST"],
    )
    report = dict(
        schemaVersion="robin-personal-access-v1",
        claimId="ENG.PERSONAL.TEST",
        scope="LOCAL_PERSONAL_NONCOMMERCIAL_NO_REDISTRIBUTION",
        platforms=[
            dict(platform="Coteur", **assessment),
            dict(
                platform="Kicktipp",
                **assessment,
                contestAssessments={
                    "pronostics-ligue1": {
                        **assessment,
                        "requiredAccess": "Current contest hides choices until kickoff",
                    }
                },
            ),
        ],
    )
    p = tmp_path / "report.json"
    p.write_bytes(json.dumps(report).encode())
    base = dict(
        status="ok",
        qualification=dict(
            status="ok",
            qualifiedCount=1,
            platforms=[
                dict(platform="Coteur", label="Written permission needed"),
                dict(platform="Kicktipp", label="All choices hidden"),
            ],
        ),
        enabledCount=1,
        candidates=[
            dict(
                id="one",
                platform="Coteur",
                sourceUrl="https://www.coteur.com/tipster/a",
                collectionEnabled=True,
                qualification=dict(
                    label="Personal pick proven", personallyProven=True, picks=[dict(id="pick1")]
                ),
            ),
            dict(
                id="two",
                platform="Kicktipp",
                sourceUrl="https://www.kicktipp.fr/pronostics-ligue1/tippuebersicht",
                collectionEnabled=False,
                qualification=dict(personallyProven=False, picks=[]),
            ),
        ],
    )
    return base, p, sha256(p.read_bytes()).hexdigest()


def test_personal_overlay_preserves_facts_flags_and_history(tmp_path: Path) -> None:
    base, p, h = fixture(tmp_path)
    before = deepcopy(base)
    result = apply_personal_access(base, p, h)
    assert base == before
    assert result["enabledCount"] == 1
    assert result["candidates"][0]["collectionEnabled"] is True
    assert result["candidates"][0]["qualification"]["picks"] == [dict(id="pick1")]
    assert result["candidates"][0]["qualification"]["personallyProven"] is True
    assert result["candidates"][0]["qualification"]["label"] == "Personal pick proven"
    assert (
        result["qualification"]["platforms"][0]["previousPersonalAssessment"]["label"]
        == "Written permission needed"
    )
    assert (
        result["candidates"][1]["qualification"]["requiredAccess"]
        == "Current contest hides choices until kickoff"
    )
    assert result["candidates"][1]["collectionEnabled"] is False
    assert apply_personal_access(result, p, h) == result


def test_altered_or_missing_report_preserves_previous_data(tmp_path: Path) -> None:
    base, p, h = fixture(tmp_path)
    p.write_bytes(p.read_bytes() + b" ")
    result = read_personal_access(base, p, h)
    assert result["candidates"] == base["candidates"]
    assert result["qualification"]["personalOverlayState"] == "unavailable"
    p.unlink()
    assert read_personal_access(base, p, h) == result


def test_unknown_qualification_is_not_upgraded(tmp_path: Path) -> None:
    base, p, h = fixture(tmp_path)
    base["qualification"]["status"] = "unavailable"
    result = apply_personal_access(base, p, h)
    assert result["qualification"]["status"] == "unavailable"
    assert result["qualification"]["personalOverlayState"] == "unavailable"
    assert result["candidates"] == base["candidates"]


def test_duplicate_platform_or_unsafe_contest_is_rejected(tmp_path: Path) -> None:
    base, p, _ = fixture(tmp_path)
    data = json.loads(p.read_bytes())
    data["platforms"].append(data["platforms"][0])
    p.write_bytes(json.dumps(data).encode())
    with pytest.raises(ValueError):
        apply_personal_access(base, p, sha256(p.read_bytes()).hexdigest())


def test_extra_historical_proof_preserves_observation_clock_and_recurring_state():
    from robin.source_observatory.personal_access import merge_personal_public

    old = dict(
        claimId="OLD",
        picks=[dict(id="old", authorId="old-author", observedAt="2026-11-20T15:00:00Z")],
        recurring=True,
        fixtures=[],
        generatedAt="2026-11-20T17:00:00Z",
    )
    bundle = dict(
        claimId="NEW",
        picks=[
            dict(
                id="new",
                authorId="new-author",
                observedAt="2026-11-20T09:38:00Z",
                firstSeenAt="2026-11-20T09:38:00Z",
            )
        ],
        recurring=False,
        fixtures=[dict(id="f", kickoff="2026-11-21T15:00:00Z")],
        qualifiedAt="2026-11-20T16:00:00Z",
    )
    result = merge_personal_public(old, bundle)
    assert result["distinctPicks"] == 2 and result["recurring"] is True
    assert result["generatedAt"] == "2026-11-20T17:00:00Z"
    assert result["sourceObservedThrough"] == "2026-11-20T15:00:00Z"
    assert (
        next(p for p in result["picks"] if p["id"] == "new")["observedAt"] == "2026-11-20T09:38:00Z"
    )
    assert merge_personal_public(result, bundle)["distinctPicks"] == 2
    assert len(old["picks"]) == 1


def test_new_candidate_proof_does_not_activate_expired_campaign():
    from robin.source_observatory.personal_access import merge_personal_candidates

    url = "https://www.olbg.com/tipsters/tips/383717"
    row = dict(
        id="candidate",
        sourceUrl=url,
        origin=dict(sheet="Catalogue", row=270),
        collectionEnabled=False,
        qualification=dict(
            personallyProven=True, picks=[dict(id="old")], unadmittedFacts=[dict(sourceTipId=8)]
        ),
    )
    base = dict(candidates=[row], enabledCount=0, qualification=dict(status="ok", qualifiedCount=1))
    bundle = dict(claimId="NEW", picks=[dict(id="new", sourceTipId=8, authorUrl=url)])
    grant = dict(candidateId="candidate", sourceUrl=url, sheet="Catalogue", row=270)
    result = merge_personal_candidates(base, bundle, grant)
    assert result["enabledCount"] == 0 and result["candidates"][0]["collectionEnabled"] is False
    assert len(result["candidates"][0]["qualification"]["picks"]) == 2
    assert result["candidates"][0]["qualification"]["unadmittedFacts"] == []
    assert merge_personal_candidates(result, bundle, grant) == result
    mismatch = {**grant, "row": 271}
    assert merge_personal_candidates(base, bundle, mismatch)["candidates"] == base["candidates"]
    missing_previous = deepcopy(base)
    missing_previous["qualification"]["qualifiedCount"] = 0
    missing_previous["candidates"][0]["qualification"].update(personallyProven=False, picks=[])
    recovered = merge_personal_candidates(missing_previous, bundle, grant)
    assert recovered["qualification"]["qualifiedCount"] == 1
    assert recovered["candidates"][0]["collectionEnabled"] is False
