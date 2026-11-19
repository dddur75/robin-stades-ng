import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from robin.source_observatory.connectors import Response, canonical, read_events
from robin.source_observatory.sro_campaign import (
    PINS,
    rules_digest,
    run_sro_slot,
    validate_sro_campaign,
)

FIX = [
    dict(
        id="j11-troyes-havre",
        label="Troyes – Le Havre",
        kickoff="2026-11-20T19:45:00Z",
        publicationWindowStart="2026-11-09",
        homeAliases=["ESTAC Troyes"],
        awayAliases=["Havre AC"],
    )
]


def html():
    return b'<div id="p42" class="blockpost"><h2>15-11-2026 18:45:20</h2><div class="postleft"><dt><a href="profile.php?id=15388">Nomade</a></dt></div><div class="postmsg">ESTAC Troyes 3 - 1 Havre AC</div></div>'


NOW = datetime(2026, 11, 19, 15, tzinfo=UTC)
LEGAL = b"<h2>R\xc3\xa8gles du forum</h2><p>Private factual access; no abusive posts.</p><h2>Pied de page</h2>"


@pytest.fixture
def packet(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    plan = dict(
        id="SRO-TEST",
        taskName="Robin-Tipsters-SRO-V1-20261119",
        sourceId="SRC_039",
        ownerMessage="owner activation request",
        scope="LOCAL_PERSONAL_NONCOMMERCIAL",
        endpoint="https://forum.stade-rennais-online.com/viewtopic.php?id=6368",
        robotsUrl="https://forum.stade-rennais-online.com/robots.txt",
        termsUrl="https://forum.stade-rennais-online.com/misc.php?action=rules",
        rulesSha256=rules_digest(LEGAL),
        fixtures=FIX,
        calendarSha256=sha256(canonical(FIX)).hexdigest(),
        parserSha256=sha256(
            (root / "src/robin/source_observatory/candidate_forums.py")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        codePins={
            p: sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in PINS
        },
        priorGET=3,
        sharedGETCeiling=39,
        e1EvidenceSha256="0" * 64,
        calendarEvidenceSha256="1" * 64,
        slots=[NOW.isoformat()]
        + [f"2026-11-20T{h:02}:00:00+00:00" for h in range(7, 24, 2)]
        + ["2026-11-21T01:00:00+00:00", "2026-11-21T03:00:00+00:00"],
        claimId="DATA.SOURCE_OBSERVATORY.SRO.PICKS.20261119",
    )
    manifest = dict(
        mission_id=plan["id"],
        authorized_stages=["E1", "E2"],
        maximum_stage="E2",
        external_effects=dict(https_get_max=36, per_source_max=36),
        compute_budget=dict(workers=1),
        time_budget=dict(seconds=900),
        source_hash=sha256(canonical(plan)).hexdigest(),
        expires_at="2026-11-21T07:00:00+00:00",
    )
    grant = dict(
        planSha256=manifest["source_hash"],
        manifestSha256=sha256(canonical(manifest)).hexdigest(),
        ownerMessage=plan["ownerMessage"],
    )
    import robin.source_observatory.sro_campaign as campaign

    monkeypatch.setattr(campaign, "APPROVED_PLAN_SHA256", manifest["source_hash"])
    monkeypatch.setattr(campaign, "APPROVED_MANIFEST_SHA256", grant["manifestSha256"])
    for name, value in [
        ("plan.json", plan),
        ("manifest.json", manifest),
        ("authorization.json", grant),
    ]:
        (tmp_path / name).write_bytes(canonical(value) + b"\n")
    return tmp_path


def transport(url, **kw):
    return (
        Response(404, b"", "text/plain", None)
        if url.endswith("robots.txt")
        else Response(200, LEGAL if "misc.php" in url else html(), "text/html", None)
    )


def run(packet, get=transport, now=NOW):
    return run_sro_slot(packet, now=now, clock=lambda: now, get=get, sleep=lambda _: None)


def test_404_then_current_charter_and_personal_pick(packet):
    assert run(packet) == dict(state="succeeded", picks=1, requests=3)
    assert (
        len([e for e in read_events(packet / "events.jsonl") if e["kind"] == "REQUEST_RESERVED"])
        == 3
    )
    assert run(packet)["state"] == "already_started"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_refusal_halts_without_retry(packet, status):
    def get(*a, **k):
        return Response(status, b"", "text/plain", None)

    with pytest.raises(ValueError):
        run(packet, get)
    assert run(packet)["state"] == "halted"
    assert (
        len([e for e in read_events(packet / "events.jsonl") if e["kind"] == "REQUEST_RESERVED"])
        == 1
    )


def test_changed_charter_and_empty_pick_halt(packet):
    def changed(url, **kw):
        r = transport(url, **kw)
        return (
            Response(200, LEGAL.replace(b"Private", b"Forbidden"), "text/html", None)
            if "misc.php" in url
            else r
        )

    with pytest.raises(ValueError, match="terms changed"):
        run(packet, changed)


def test_not_due_and_expired_do_not_contact_source(packet):
    def never(*a, **k):
        pytest.fail("source contacted")

    assert run(packet, never, datetime(2026, 11, 19, 14, tzinfo=UTC))["state"] == "not_due"
    assert run(packet, never, datetime(2026, 11, 21, 7, tzinfo=UTC))["state"] == "expired"


def test_tampered_grant_refused(packet):
    (packet / "authorization.json").write_text("{}")
    with pytest.raises(ValueError):
        validate_sro_campaign(packet)


def test_volatile_banner_ignored_but_actual_charter_not():
    assert rules_digest(b"news1" + LEGAL) == rules_digest(b"news2" + LEGAL)
    assert rules_digest(LEGAL) != rules_digest(LEGAL.replace(b"Private", b"Forbidden"))


def test_missing_admissible_pick_stops(packet):
    def empty(url, **kw):
        return (
            transport(url, **kw)
            if "viewtopic" not in url
            else Response(200, b"<html>No personal pick</html>", "text/html", None)
        )

    with pytest.raises(ValueError, match="no admissible"):
        run(packet, empty)
    assert run(packet)["state"] == "halted"


def test_consistent_recomputed_but_unapproved_packet_is_rejected(packet):
    plan = json.loads((packet / "plan.json").read_bytes())
    mission = json.loads((packet / "manifest.json").read_bytes())
    grant = json.loads((packet / "authorization.json").read_bytes())
    plan["ownerMessage"] = "unapproved alteration"
    mission["source_hash"] = sha256(canonical(plan)).hexdigest()
    grant.update(
        ownerMessage=plan["ownerMessage"],
        planSha256=mission["source_hash"],
        manifestSha256=sha256(canonical(mission)).hexdigest(),
    )
    for name, value in [
        ("plan.json", plan),
        ("manifest.json", mission),
        ("authorization.json", grant),
    ]:
        (packet / name).write_bytes(canonical(value) + b"\n")
    with pytest.raises(ValueError, match="independent"):
        validate_sro_campaign(packet)


def test_compliant_crawl_delay_fifteen_seconds_is_supported(packet):
    def paced(url, **kw):
        return (
            Response(200, b"User-agent: *\nCrawl-delay: 15\n", "text/plain", None)
            if url.endswith("robots.txt")
            else transport(url, **kw)
        )

    assert run(packet, paced)["state"] == "succeeded"


@pytest.mark.parametrize("field", ["rulesSha256", "e1EvidenceSha256", "calendarEvidenceSha256"])
def test_malformed_evidence_hash_is_refused_before_network(packet, monkeypatch, field):
    import robin.source_observatory.sro_campaign as campaign

    plan = json.loads((packet / "plan.json").read_bytes())
    mission = json.loads((packet / "manifest.json").read_bytes())
    grant = json.loads((packet / "authorization.json").read_bytes())
    plan[field] += "0"
    mission["source_hash"] = sha256(canonical(plan)).hexdigest()
    grant.update(
        planSha256=mission["source_hash"], manifestSha256=sha256(canonical(mission)).hexdigest()
    )
    monkeypatch.setattr(campaign, "APPROVED_PLAN_SHA256", mission["source_hash"])
    monkeypatch.setattr(campaign, "APPROVED_MANIFEST_SHA256", grant["manifestSha256"])
    for name, value in [
        ("plan.json", plan),
        ("manifest.json", mission),
        ("authorization.json", grant),
    ]:
        (packet / name).write_bytes(canonical(value) + b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        validate_sro_campaign(packet)
