from hashlib import sha256

import pytest

from robin.source_observatory.connectors import canonical
from robin.source_observatory.qualification_view import apply_qualification, merge_sro_collection


@pytest.fixture
def base():
    return dict(
        status="ok",
        receipt=dict(registrySha256="a" * 64),
        candidates=[
            dict(
                id="one",
                sourceUrl="https://forum.stade-rennais-online.com/profile.php?id=1",
                platform="Stade Rennais Online",
                status="pending_qualification",
                collectionEnabled=False,
            ),
            dict(
                id="two",
                sourceUrl="https://example.invalid/2",
                platform="Other",
                status="pending_qualification",
                collectionEnabled=False,
            ),
        ],
    )


@pytest.fixture
def assessment(tmp_path, base):
    data = dict(
        schemaVersion="robin-candidate-qualification-v1",
        registrySha256="a" * 64,
        claimId="DATA.SOURCE_OBSERVATORY.QUALIFICATION317.20261119",
        platforms=[
            dict(
                platform="Stade Rennais Online",
                label="Source publique accessible",
                reason="Subject observed",
                requiredAccess="Aucun pour ce canari",
                ownerAction="Aucune",
                url="https://forum.stade-rennais-online.com/",
                observedAt="2026-11-19T15:00:00Z",
            ),
            dict(
                platform="Other",
                label="Accès refusé",
                reason="HTTP403",
                requiredAccess="Accès officiel autorisé",
                ownerAction="Obtenir un flux autorisé",
                url="https://example.invalid/",
                observedAt="2026-11-19T15:00:00Z",
            ),
        ],
        candidates=[
            dict(id=r["id"], profileVisited=False, documentaryIssues=[]) for r in base["candidates"]
        ],
    )
    raw = canonical(data) + b"\n"
    (tmp_path / "assessment.json").write_bytes(raw)
    return tmp_path, sha256(raw).hexdigest()


def public():
    return dict(
        status="ok",
        recurring=True,
        halted=False,
        picks=[
            dict(
                id="pick",
                sourceId="SRC_039",
                authorUrl="https://forum.stade-rennais-online.com/profile.php?id=1",
                authorId="author",
                selection="3-1",
                fixtureId="fixture",
                fixtureLabel="Troyes – Le Havre",
                observedAt="2026-11-19T15:00:00Z",
                kickoff="2026-11-20T19:45:00Z",
                versions=[dict(selection="3-1", observedAt="2026-11-19T15:00:00Z")],
            )
        ],
        generatedAt="2026-11-19T15:00:00Z",
        claimId="DATA.SOURCE_OBSERVATORY.SRO.PICKS.20261119",
    )


def test_joins_only_exact_profile_and_preserves_base(base, assessment):
    directory, digest = assessment
    result = apply_qualification(
        base, directory, expected_sha256=digest, public_data=public(), operational=True
    )
    assert result["enabledCount"] == 1 and result["qualification"]["qualifiedCount"] == 1
    assert result["candidates"][0]["qualification"]["picks"][0]["selection"] == "3-1"
    assert result["candidates"][1]["qualification"]["label"] == "Accès refusé"
    assert base["candidates"][0]["collectionEnabled"] is False


def test_no_future_or_unrelated_proof_and_inactive_without_task(base, assessment):
    directory, digest = assessment
    p = public()
    p["picks"][0]["sourceId"] = "other"
    r = apply_qualification(
        base, directory, expected_sha256=digest, public_data=p, operational=False
    )
    assert r["enabledCount"] == 0 and r["qualification"]["qualifiedCount"] == 0


@pytest.mark.parametrize("sro,olbg", [(True, False), (False, True), (True, True), (False, False)])
def test_operation_authority_is_independent_per_source(base, assessment, sro, olbg):
    import json

    directory, _ = assessment
    base["candidates"][1]["platform"] = "OLBG"
    base["candidates"][1]["sourceUrl"] = "https://www.olbg.com/tipsters/tips/648433"
    a = json.loads((directory / "assessment.json").read_bytes())
    a["platforms"][1]["platform"] = "OLBG"
    raw = canonical(a)
    (directory / "assessment.json").write_bytes(raw)
    p = public()
    p["picks"].append(
        dict(
            p["picks"][0],
            id="native",
            sourceId="SRC_014",
            authorUrl=base["candidates"][1]["sourceUrl"],
            authorId="olbg:648433",
            selection="PSG",
            market="source_native",
        )
    )
    result = apply_qualification(
        base,
        directory,
        expected_sha256=sha256(raw).hexdigest(),
        public_data=p,
        operational_by_source={"SRC_039": sro, "SRC_014": olbg},
    )
    assert result["qualification"]["qualifiedCount"] == 2
    assert [r["collectionEnabled"] for r in result["candidates"]] == [sro, olbg]
    assert result["enabledCount"] == int(sro) + int(olbg)


def test_tampered_or_incomplete_assessment_refused(base, assessment):
    directory, digest = assessment
    (directory / "assessment.json").write_text("{}")
    with pytest.raises(ValueError):
        apply_qualification(base, directory, expected_sha256=digest)


def test_new_collection_preserves_original_and_tracks_versions():
    seed = dict(
        picks=[dict(id="seed", authorId="old", selection="1-0")],
        claimId="old",
        generatedAt="2026-11-19T10:00:00Z",
    )
    first = merge_sro_collection(seed, public())
    assert first["distinctPicks"] == 2 and first["authorCount"] == 2
    assert merge_sro_collection(first, public())["distinctPicks"] == 2
    changed = public()
    changed["picks"][0]["selection"] = "0-0"
    changed["picks"][0]["versions"].append(dict(selection="0-0", observedAt="2026-11-19T16:00:00Z"))
    second = merge_sro_collection(first, changed)
    assert second["distinctPicks"] == 2 and len(second["picks"][-1]["versions"]) == 2
    assert len(first["picks"][-1]["versions"]) == 1


def test_same_selection_does_not_create_a_false_revision():
    initial = public()
    initial["picks"][0]["firstSeenAt"] = "2026-11-19T14:00:00Z"
    seed = merge_sro_collection(dict(picks=[], claimId="seed"), initial)
    later = public()
    later["picks"][0]["versions"][0]["observedAt"] = "2026-11-19T16:00:00Z"
    merged = merge_sro_collection(seed, later)
    assert len(merged["picks"][0]["versions"]) == 1


@pytest.mark.parametrize("bad_file", ["events.jsonl", "authorization.json"])
def test_scalar_companion_never_hides_original_seed(tmp_path, monkeypatch, bad_file):
    import robin.source_observatory.sro_campaign as campaign
    from robin.source_observatory.qualification_view import read_sro_companion

    monkeypatch.setattr(campaign, "validate_sro_campaign", lambda d: ({}, {}))
    (tmp_path / bad_file).write_text("null\n")
    seed = dict(picks=[dict(id="original", authorId="old", selection="1-0")], claimId="old")
    result, _, _ = read_sro_companion(seed, tmp_path)
    assert result["picks"] == seed["picks"] and result["sroCampaign"]["state"] == "invalid_package"


def test_independent_e1_evidence_survives_invalid_recurring_packet(tmp_path, monkeypatch):
    import robin.source_observatory.qualification_view as view
    import robin.source_observatory.sro_campaign as campaign

    monkeypatch.setattr(view, "read_sro_e1", lambda d: public(), raising=False)

    def invalid(d):
        raise ValueError("bad E2 grant")

    monkeypatch.setattr(campaign, "validate_sro_campaign", invalid)
    seed = dict(picks=[dict(id="original", authorId="old", selection="1-0")], claimId="old")
    result, personal, active = view.read_sro_companion(seed, tmp_path)
    assert result["distinctPicks"] == 2 and personal["picks"][0]["id"] == "pick" and not active
