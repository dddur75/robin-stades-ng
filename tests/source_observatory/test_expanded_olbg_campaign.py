from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from robin.source_observatory import expanded_olbg_campaign as campaign
from robin.source_observatory.connectors import Response


def setup(monkeypatch, *, empty=False, expiry_seconds=86400):
    now = datetime(2026, 11, 20, 10, tzinfo=UTC)
    fixture = {
        "id": "synthetic-fixture",
        "label": "Home – Away",
        "kickoff": (now + timedelta(days=1)).isoformat(),
        "homeAliases": ["Home"],
        "awayAliases": ["Away"],
    }
    plan = {
        "notBefore": (now - timedelta(minutes=1)).isoformat(),
        "slots": [(now + timedelta(hours=3)).isoformat(), (now + timedelta(hours=5)).isoformat()],
        "caSha256": "a" * 64,
        "rulesSha256": "b" * 64,
        "parserSha256": "c" * 64,
        "calendarSha256": "d" * 64,
        "fixtures": [fixture],
    }
    mission = {
        "mission_id": campaign.MISSION,
        "authorized_stages": ["E1", "E2"],
        "maximum_stage": "E2",
        "external_effects": {"https_get_max": 9, "per_source_max": 9},
        "compute_budget": {"workers": 1},
        "time_budget": {"seconds": 600, "per_slot_seconds": 150},
        "source_hash": "e" * 64,
        "expires_at": (now + timedelta(seconds=expiry_seconds)).isoformat(),
    }
    monkeypatch.setattr(campaign, "validate", lambda _: (plan, mission))
    monkeypatch.setattr(campaign, "rules_digest", lambda _: "b" * 64)
    monkeypatch.setattr(campaign, "extract_profile", lambda *_: {})
    pick = {
        "id": "olbg-tip:1",
        "sourceId": "SRC_014",
        "authorId": "olbg:383717",
        "authorUrl": campaign.PROFILE,
        "sourceUrl": campaign.PROFILE,
        "sourceTipId": 1,
        "sourceEventId": 1,
        "fixtureId": fixture["id"],
        "fixtureLabel": fixture["label"],
        "kickoff": fixture["kickoff"],
        "observedAt": now.isoformat(),
        "selection": "Home",
        "market": "source_native",
        "sourceMarketLabel": "",
        "sourceBetType": "Win",
        "performanceEvaluationAllowed": False,
        "sourceEventTimezone": None,
        "publishedAt": None,
        "publishedCivilDate": None,
        "responseSha256": sha256(b"profile").hexdigest(),
        "parserSha256": "c" * 64,
        "calendarSha256": "d" * 64,
    }
    monkeypatch.setattr(campaign, "admit_facts", lambda *a, **k: [] if empty else [pick])
    return now, plan, mission


def test_manual_canary_collects_once_and_keeps_native_receipt(monkeypatch, tmp_path):
    now, _, _ = setup(monkeypatch)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response(
            200,
            b"User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else b"profile",
            "text/plain" if url.endswith("robots.txt") else "text/html",
            None,
        )

    result = campaign.run_slot(
        tmp_path, get=get, canary=True, clock=lambda: now, sleep=lambda _: None
    )
    assert result["state"] == "collected" and result["count"] == 1 and result["requests"] == 3
    again = campaign.run_slot(
        tmp_path, get=get, canary=True, clock=lambda: now, sleep=lambda _: None
    )
    assert again["state"] == "already_started" and len(calls) == 3


def test_empty_admissible_set_halts_without_future_retry(monkeypatch, tmp_path):
    now, _, _ = setup(monkeypatch, empty=True)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response(
            200,
            b"User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else b"profile",
            "text/plain" if url.endswith("robots.txt") else "text/html",
            None,
        )

    assert (
        campaign.run_slot(tmp_path, get=get, canary=True, clock=lambda: now, sleep=lambda _: None)[
            "state"
        ]
        == "halted"
    )
    assert (
        campaign.run_slot(tmp_path, get=get, canary=True, clock=lambda: now, sleep=lambda _: None)[
            "state"
        ]
        == "halted"
    )
    assert len(calls) == 3


@pytest.mark.parametrize(
    "body,mime",
    [
        (b"User-agent: *\nDisallow: /use\n", "text/plain"),
        (b"<html>login</html>", "text/plain"),
        (b"User-agent: *\0", "text/plain"),
        (b"User-agent: *", "text/html"),
    ],
)
def test_invalid_or_denied_robots_never_reads_terms(monkeypatch, tmp_path, body, mime):
    now, _, _ = setup(monkeypatch)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response(200, body, mime, None)

    assert (
        campaign.run_slot(tmp_path, get=get, canary=True, clock=lambda: now, sleep=lambda _: None)[
            "state"
        ]
        == "halted"
    )
    assert calls == [campaign.URLS[0]]


def test_expiry_during_delay_prevents_next_get(monkeypatch, tmp_path):
    now, _, _ = setup(monkeypatch, expiry_seconds=1)
    current = [now]
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response(200, b"User-agent: *\nAllow: /\n", "text/plain", None)

    def sleep(seconds):
        current[0] += timedelta(seconds=seconds)

    assert (
        campaign.run_slot(tmp_path, get=get, canary=True, clock=lambda: current[0], sleep=sleep)[
            "state"
        ]
        == "halted"
    )
    assert len(calls) == 1


def test_not_due_and_missing_authority_make_no_request(monkeypatch, tmp_path):
    with pytest.raises(OSError):
        campaign.validate(tmp_path)
    now, _, _ = setup(monkeypatch)
    assert (
        campaign.run_slot(tmp_path, get=lambda *a, **k: pytest.fail("not due"), clock=lambda: now)[
            "state"
        ]
        == "not_due"
    )


def test_expiry_during_reservation_prevents_network(monkeypatch, tmp_path):
    now, _, _ = setup(monkeypatch, expiry_seconds=1)
    current = [now]
    original = campaign.Journal.reserve

    def reserve(self, source, url):
        result = original(self, source, url)
        current[0] += timedelta(seconds=2)
        return result

    monkeypatch.setattr(campaign.Journal, "reserve", reserve)
    result = campaign.run_slot(
        tmp_path,
        get=lambda *a, **k: pytest.fail("expired after fsync"),
        canary=True,
        clock=lambda: current[0],
        sleep=lambda _: None,
    )
    assert result["state"] == "halted" and result["requests"] == 1


def test_scalar_e2_journal_is_unavailable_without_hiding_e1(monkeypatch, tmp_path):
    setup(monkeypatch)
    (tmp_path / "events.jsonl").write_text("null\n", encoding="utf-8")
    state, bundles, active = campaign.read_state(tmp_path)
    assert state["state"] == "unavailable" and bundles == [] and active is False
