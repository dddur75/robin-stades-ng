"""One group's quotas and per-author stop must never borrow other campaigns."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from robin.source_observatory import roster_campaign as engine
from robin.source_observatory.connectors import Journal, Response, canonical, read_events

NOW = datetime(2026, 11, 20, 21, 55, tzinfo=UTC)
REGISTRATION = engine.validate_registration


@pytest.fixture
def packet(tmp_path: Path, monkeypatch):
    fixtures = [
        dict(
            id="f",
            label="Home – Away",
            kickoff="2026-11-21T15:00:00Z",
            homeAliases=["Home"],
            awayAliases=["Away"],
        )
    ]
    plan = dict(
        id="SYNTHETIC",
        pool=[10, 20],
        canaryAuthors=[10],
        slots=["2026-11-20T23:00:00Z", "2026-11-21T05:00:00Z", "2026-11-21T11:00:00Z"],
        canaryNotBefore="2026-11-20T21:00:00Z",
        canaryExpires="2026-11-20T22:30:00Z",
        fixtures=fixtures,
        calendarSha256=sha256(canonical(fixtures)).hexdigest(),
        parserSha256="b" * 64,
        claimId="DATA.SYNTHETIC",
        requestMax=11,
    )
    mission = dict(
        mission_id=plan["id"],
        authorized_stages=["E1", "E2"],
        maximum_stage="E2",
        external_effects=dict(https_get_max=11, per_source_max=11),
        compute_budget=dict(workers=1),
        time_budget=dict(seconds=600),
        source_hash="a" * 64,
        expires_at="2026-11-21T11:15:00Z",
    )
    monkeypatch.setattr(engine, "validate_packet", lambda _: (plan, mission))
    monkeypatch.setattr(engine, "validate_registration", lambda _: dict(status="PASS"))
    return tmp_path


def fake(calls, *, empty=0, denied=0):
    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("robots.txt"):
            return Response(200, b"User-agent: *\nAllow: /\n", "text/plain", None)
        owner = int(url.rsplit("/", 1)[-1])
        if owner == denied:
            return Response(403, b"", "text/html", None)
        tip = dict(
            tipid=owner * 100,
            eventid=1,
            selection="Home",
            eventname="Home v Away",
            event_datetime="2026-11-21 15:00:00",
            market="",
            winew="Win",
            hcap_market=False,
            result="Open",
            vc_sport_id=1,
        )
        literal = (
            '{mode:"current",effectiveTipsterId:'
            + str(owner)
            + ',tipsterUsername:"Synthetic",tipsByDate:[{events:[{tips:'
            + json.dumps([] if owner == empty else [tip])
            + "}]}]}"
        )
        return Response(
            200, ("<script>var x=" + literal + ";</script>").encode(), "text/html", None
        )

    return get


def test_canary_and_future_slot_use_one_shared_journal_and_reject_duplicate(packet):
    calls = []
    first = engine.run_slot(
        packet, canary=True, get=fake(calls), clock=lambda: NOW, sleep=lambda _: None
    )
    assert first["requests"] == 2 and first["observedAuthors"] == [10]
    later = datetime(2026, 11, 20, 23, tzinfo=UTC)
    second = engine.run_slot(packet, get=fake(calls), clock=lambda: later, sleep=lambda _: None)
    assert second["requests"] == 3 and second["observedAuthors"] == [10, 20]
    before = len(calls)
    with pytest.raises(ValueError):
        engine.run_slot(packet, get=fake(calls), clock=lambda: later, sleep=lambda _: None)
    assert len(calls) == before
    assert sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(packet / "events.jsonl")) == 5


def test_empty_author_stops_only_that_profile_for_all_remaining_slots(packet):
    calls = []
    engine.run_slot(packet, canary=True, get=fake(calls), clock=lambda: NOW, sleep=lambda _: None)
    engine.run_slot(
        packet,
        get=fake(calls, empty=20),
        clock=lambda: datetime(2026, 11, 20, 23, tzinfo=UTC),
        sleep=lambda _: None,
    )
    later = engine.run_slot(
        packet,
        get=fake(calls),
        clock=lambda: datetime(2026, 11, 21, 5, tzinfo=UTC),
        sleep=lambda _: None,
    )
    assert later["observedAuthors"] == [10] and later["activeAuthors"] == [10]
    assert calls.count("https://www.olbg.com/tipsters/tips/20") == 1


def test_host_refusal_permanently_halts_group_without_retry(packet):
    calls = []
    first = engine.run_slot(
        packet, canary=True, get=fake(calls, denied=10), clock=lambda: NOW, sleep=lambda _: None
    )
    assert first["state"] == "halted" and len(calls) == 2
    with pytest.raises(ValueError):
        engine.run_slot(
            packet,
            get=fake(calls),
            clock=lambda: datetime(2026, 11, 20, 23, tzinfo=UTC),
            sleep=lambda _: None,
        )
    assert len(calls) == 2


def test_late_or_missed_slot_never_catches_up(packet):
    calls = []
    engine.run_slot(packet, canary=True, get=fake(calls), clock=lambda: NOW, sleep=lambda _: None)
    with pytest.raises(ValueError):
        engine.run_slot(
            packet,
            get=fake(calls),
            clock=lambda: datetime(2026, 11, 21, 5, tzinfo=UTC),
            sleep=lambda _: None,
        )
    assert len(calls) == 2


def test_expiry_during_reservation_fsync_prevents_network(packet, monkeypatch):
    calls = []
    current = [NOW]
    original = Journal.reserve

    def reserve(self, *args):
        value = original(self, *args)
        current[0] = datetime(2026, 11, 21, 11, 15, tzinfo=UTC)
        return value

    monkeypatch.setattr(Journal, "reserve", reserve)
    result = engine.run_slot(
        packet, canary=True, get=fake(calls), clock=lambda: current[0], sleep=lambda _: None
    )
    assert result["state"] == "halted" and calls == []


def test_boolean_football_marker_is_not_admitted_as_integer_sport_id():
    tip = dict(
        tipid=1,
        eventid=1,
        selection="Home",
        eventname="Home v Away",
        event_datetime="2026-11-21 15:00:00",
        market="",
        winew="Win",
        hcap_market=False,
        result="Open",
        vc_sport_id=True,
    )
    fixtures = [
        dict(
            id="f",
            label="Home – Away",
            kickoff="2026-11-21T15:00:00Z",
            homeAliases=["Home"],
            awayAliases=["Away"],
        )
    ]
    source = dict(
        profiles=[
            dict(
                facts=dict(authorId=10, authorLabel="A", mode="current", records=[tip]),
                request=dict(
                    url="https://www.olbg.com/tipsters/tips/10",
                    observedAt=NOW.isoformat(),
                    responseSha256="a" * 64,
                ),
            )
        ],
        fixtures=fixtures,
        calendarSha256=sha256(canonical(fixtures)).hexdigest(),
    )
    assert engine._choices(
        source,
        dict(fixtures=fixtures, parserSha256="b" * 64, calendarSha256=source["calendarSha256"]),
    ) == ([], [])


def test_canary_deadline_is_rechecked_after_reservation(packet, monkeypatch):
    calls = []
    current = [NOW]
    original = Journal.reserve

    def reserve(self, *args):
        value = original(self, *args)
        current[0] = datetime(2026, 11, 20, 22, 30, tzinfo=UTC)
        return value

    monkeypatch.setattr(Journal, "reserve", reserve)
    result = engine.run_slot(
        packet, canary=True, get=fake(calls), clock=lambda: current[0], sleep=lambda _: None
    )
    assert result["state"] == "halted" and not calls


def test_reader_detects_missed_slot_before_another_job_runs(packet):
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    view, operational = engine.read_campaign(packet, now=datetime(2026, 11, 21, 1, tzinfo=UTC))
    assert not operational and view["rosterCampaign"]["state"] == "halted"
    assert len(view["picks"]) == 1


def test_reader_retains_closed_prefix_and_rejects_orphan_active_state(packet):
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    _, mission = engine.validate_packet(packet)
    Journal(packet, mission, now=lambda: NOW).append("RUN_STARTED", slot="2026-11-20T23:00:00Z")
    view, operational = engine.read_campaign(packet, now=datetime(2026, 11, 20, 23, tzinfo=UTC))
    assert (
        not operational and view["rosterCampaign"]["state"] == "halted" and len(view["picks"]) == 1
    )


def test_new_choice_contract_revision_after_canary_stops_its_profile(packet):
    calls = []
    engine.run_slot(packet, canary=True, get=fake(calls), clock=lambda: NOW, sleep=lambda _: None)
    base = fake(calls)

    def revised(url, **kwargs):
        response = base(url, **kwargs)
        body = (
            response.body.replace(b'"selection": "Home"', b'"selection": "Away"')
            if url.endswith("/10")
            else response.body
        )
        return Response(response.status, body, response.content_type, response.location)

    result = engine.run_slot(
        packet,
        get=revised,
        clock=lambda: datetime(2026, 11, 20, 23, tzinfo=UTC),
        sleep=lambda _: None,
    )
    assert result["activeAuthors"] == [20] and result["observedAuthors"] == [20]


def test_opaque_contract_keeps_handicap_presence_and_types():
    value = dict(id="p", sourceFields=dict(hcap="0.25", hcap_market=False))
    assert engine._contract(value) != engine._contract(
        dict(value, sourceFields=dict(hcap=0.25, hcap_market=False))
    )
    assert engine._contract(value) != engine._contract(
        dict(value, sourceFields=dict(hcap="0.25", hcap_market=0))
    )
    assert engine._contract(dict(id="p", sourceFields={})) != engine._contract(
        dict(id="p", sourceFields=dict(hcap=None))
    )


def test_observation_requires_its_exact_reservation_and_response(packet):
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    plan, _ = engine.validate_packet(packet)
    events = read_events(packet / "events.jsonl")
    response = next(
        e for e in events if e["kind"] == "REQUEST_FINISHED" and e["url"].endswith("/10")
    )
    response["reservation"] = "0" * 64
    with pytest.raises(ValueError, match="reservation"):
        engine._observations(packet, plan, events)


def test_registration_requires_the_real_three_author_canary_and_current_head(packet, monkeypatch):
    plan, mission = engine.validate_packet(packet)
    plan.update(
        pool=[10, 20, 30], canaryAuthors=[10, 20, 30], registrationDecisionId="SYNTHETIC_KEY"
    )
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    events = read_events(packet / "events.jsonl")
    receipt = dict(
        status="PASS",
        taskRegistrationAuthorized=True,
        planSha256=mission["source_hash"],
        canaryHeadHash=events[-1]["hash"],
        decisionRecordHash="f" * 64,
    )
    (packet / "canary-recette.json").write_bytes(canonical(receipt))
    monkeypatch.setattr(engine, "ROOT", packet)
    ledger = packet / "reports/council/decision-ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(
        canonical(
            dict(
                decision_id="SYNTHETIC_KEY",
                hash="f" * 64,
                decision="PASS_AND_HOLD",
                context=dict(
                    keys=["C0", "C1", "C2", "C4"],
                    plan_sha256=mission["source_hash"],
                    canary_head_hash=events[-1]["hash"],
                ),
            )
        )
        + b"\n"
    )
    assert REGISTRATION(packet, for_install=True)["status"] == "PASS"
    Journal(packet, mission, now=lambda: NOW).append(
        "CAMPAIGN_HALTED", slot="SYNTHETIC", reason="test"
    )
    with pytest.raises(ValueError, match="current canary head"):
        REGISTRATION(packet, for_install=True)


def test_failed_pass_is_not_counted_as_successful(packet):
    engine.run_slot(
        packet, canary=True, get=fake([], denied=10), clock=lambda: NOW, sleep=lambda _: None
    )
    view, operational = engine.read_campaign(packet, now=NOW)
    assert not operational and view["rosterCampaign"]["successfulSlots"] == 0


def test_timely_busy_pass_remains_checking_after_two_minute_start_window(packet):
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    _, mission = engine.validate_packet(packet)
    Journal(packet, mission, now=lambda: datetime(2026, 11, 20, 23, tzinfo=UTC)).append(
        "RUN_STARTED", slot="2026-11-20T23:00:00Z"
    )
    (packet / "busy.lock").write_text("owned by synthetic running worker")
    view, operational = engine.read_campaign(
        packet, now=datetime(2026, 11, 20, 23, 2, 5, tzinfo=UTC)
    )
    assert not operational and view["rosterCampaign"]["state"] == "checking"


@pytest.mark.parametrize(
    "field,value,reason",
    [("status", 403, "HTTP status/MIME"), ("observedAt", "2026-11-20T20:00:00Z", "clock interval")],
)
def test_coherently_changed_response_still_needs_http_and_run_time_proof(
    packet, field, value, reason
):
    engine.run_slot(packet, canary=True, get=fake([]), clock=lambda: NOW, sleep=lambda _: None)
    plan, _ = engine.validate_packet(packet)
    events = read_events(packet / "events.jsonl")
    event = next(e for e in events if e["kind"] == "PROFILE_OBSERVATIONS_PREPARED")
    original = packet / f"profile-{event['observationSha256']}.json"
    data = json.loads(original.read_bytes())
    data["source"]["profiles"][0]["request"][field] = value
    encoded = canonical(data) + b"\n"
    event["observationSha256"] = sha256(encoded).hexdigest()
    (packet / f"profile-{event['observationSha256']}.json").write_bytes(encoded)
    response = next(
        e for e in events if e["kind"] == "REQUEST_FINISHED" and e["url"].endswith("/10")
    )
    response[field] = value
    if field == "observedAt":
        event[field] = value
    with pytest.raises(ValueError, match=reason):
        engine._observations(packet, plan, events)
