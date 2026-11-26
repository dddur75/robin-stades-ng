import json
from hashlib import sha256

import pytest

from robin.source_observatory.olbg_store import read_bundle, read_olbg_companion


def bundle():
    return dict(
        schemaVersion="robin-native-tipsters-v1",
        claimId="DATA.SOURCE_OBSERVATORY.OLBG.NATIVE.PICKS.20261119",
        missionId="test",
        generatedAt="2026-11-19T17:00:00Z",
        fixtures=[dict(id="f", label="Nice – PSG", kickoff="2026-11-21T16:15:00Z")],
        picks=[
            dict(
                id="olbg-tip:123",
                sourceId="SRC_014",
                sourceTipId=123,
                sourceEventId=999,
                authorId="olbg:42",
                authorUrl="https://www.olbg.com/tipsters/tips/42",
                sourceUrl="https://www.olbg.com/tipsters/tips/42",
                authorLabel="Synthetic",
                fixtureId="f",
                fixtureLabel="Nice – PSG",
                kickoff="2026-11-21T16:15:00Z",
                observedAt="2026-11-19T17:00:00Z",
                firstSeenAt="2026-11-19T17:00:00Z",
                selection="PSG",
                market="source_native",
                sourceMarketLabel="",
                sourceBetType="Win",
                sourceEventLocalText="2026-11-21 16:15:00",
                sourceEventTimezone=None,
                publishedCivilDate=None,
                performanceEvaluationAllowed=False,
                responseSha256="1" * 64,
                parserSha256="2" * 64,
                calendarSha256="3" * 64,
                versions=[dict(selection="PSG", observedAt="2026-11-19T17:00:00Z")],
            )
        ],
    )


def write(d, value):
    raw = json.dumps(value).encode()
    h = sha256(raw).hexdigest()
    p = d / ("observations-" + h + ".json")
    p.write_bytes(raw)
    return p, h


def test_native_choices_are_read_without_becoming_scores(tmp_path):
    p, h = write(tmp_path, bundle())
    v = read_bundle(p, h)
    assert v["picks"][0]["selection"] == "PSG"


@pytest.mark.parametrize(
    "key,value",
    [
        ("market", "correct_score"),
        ("performanceEvaluationAllowed", True),
        ("sourceEventTimezone", "UTC"),
        ("publishedAt", "2026-11-19T10:00:00Z"),
        ("kickoff", "2026-11-18T00:00:00Z"),
    ],
)
def test_corruption_and_false_normalization_rejected(tmp_path, key, value):
    v = bundle()
    v["picks"][0][key] = value
    p, h = write(tmp_path, v)
    with pytest.raises(ValueError):
        read_bundle(p, h)


def test_seed_survives_unavailable_campaign(tmp_path, monkeypatch):
    from robin.source_observatory import olbg_authority

    d = tmp_path / "e1"
    d.mkdir()
    p, h = write(d, bundle())
    monkeypatch.setattr(olbg_authority, "APPROVED_E1_SHA256", h)
    base = dict(picks=[dict(id="old", authorId="oldauthor")], claimId="OLD")
    v, n, active = read_olbg_companion(base, d, tmp_path / "missing")
    assert len(v["picks"]) == 2 and not active and n["picks"][0]["sourceId"] == "SRC_014"


def test_bad_native_seed_does_not_mask_other_sources(tmp_path, monkeypatch):
    from robin.source_observatory import olbg_authority

    monkeypatch.setattr(olbg_authority, "APPROVED_E1_SHA256", "0" * 64)
    base = dict(picks=[dict(id="old", authorId="oldauthor")], claimId="OLD")
    v, _, active = read_olbg_companion(base, tmp_path, tmp_path / "missing")
    assert v["picks"] == base["picks"] and not active


def test_accepted_bundle_without_its_get_and_qualification_cannot_activate(tmp_path, monkeypatch):
    import robin.source_observatory.olbg_store as store

    v = bundle()
    p, h = write(tmp_path, v)
    plan = dict(
        id="test",
        endpoint="https://www.olbg.com/tipsters/tips/648433",
        fixtures=v["fixtures"],
        parserSha256="4" * 64,
        calendarSha256="5" * 64,
        slots=["2026-11-19T17:00:00Z"],
    )
    monkeypatch.setattr(
        store, "validate_olbg_campaign", lambda _: (plan, dict(expires_at="2099-01-01T00:00:00Z"))
    )
    monkeypatch.setattr(
        store,
        "read_events",
        lambda _: [
            dict(
                kind="PUBLIC_COLLECTION_ACCEPTED",
                observationFile=p.name,
                observationSha256=h,
                count=1,
                slot=plan["slots"][0],
            ),
            dict(kind="PUBLIC_SLOT_FINISHED", slot=plan["slots"][0]),
        ],
    )
    data, _, active = read_olbg_companion(
        dict(picks=[], claimId="OLD"), tmp_path / "missing", tmp_path
    )
    assert not active and data["olbgCampaign"]["state"] == "invalid_package" and not data["picks"]


def test_orphan_finished_slot_cannot_activate_valid_seed(tmp_path, monkeypatch):
    import robin.source_observatory.olbg_store as store
    from robin.source_observatory import olbg_authority

    seed = tmp_path / "seed"
    seed.mkdir()
    _, h = write(seed, bundle())
    monkeypatch.setattr(olbg_authority, "APPROVED_E1_SHA256", h)
    monkeypatch.setattr(
        store,
        "validate_olbg_campaign",
        lambda _: ({"slots": ["s"]}, {"expires_at": "2099-01-01T00:00:00Z"}),
    )
    monkeypatch.setattr(
        store, "read_events", lambda _: [{"kind": "PUBLIC_SLOT_FINISHED", "slot": "s"}]
    )
    data, _, active = read_olbg_companion(dict(picks=[], claimId="OLD"), seed, tmp_path)
    assert (
        not active
        and data["olbgCampaign"]["state"] == "invalid_package"
        and len(data["picks"]) == 1
    )
