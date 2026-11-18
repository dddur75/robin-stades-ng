from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from robin.source_observatory.connectors import Response, canonical
from robin.source_observatory.recurring import (
    execute_slot,
    close_campaign,
    origin_url,
    plan_hash,
    project_forecasts,
    snapshot,
)

NOW = datetime(2026, 11, 18, 13, tzinfo=UTC)


def card():
    return {
        "schema_version": "2.0",
        "page_type": "event",
        "canonical": "/football/matches/synthetic/",
        "event": {
            "id": "synthetic-event",
            "starts_at": "2026-11-20T20:00:00Z",
            "competition_name": "Ligue 1",
            "status": "scheduled",
            "condition": "scheduled",
        },
        "evidence_items": [
            {
                "observation_id": "synthetic-pick",
                "withdrawn": False,
                "origin": "recorded_before_kickoff",
                "status": "recognised",
                "authorship": {"forecaster": "Synthetic Author", "forecaster_named_in_text": True},
                "source_info": {
                    "url": "https://example.invalid/video",
                    "publisher": "Synthetic publisher",
                },
                "dates": {"detected_at": "2026-11-18T12:00:00Z"},
                "published_at": "2026-11-18T11:00:00Z",
                "author_claim": {
                    "market_key": "total",
                    "choice_key": "over",
                    "line": 2.5,
                    "period": "full_time",
                    "author_odds": 1.85,
                },
            }
        ],
    }


def test_actual_prematch_lineage_and_pseudonym():
    picks = project_forecasts(
        card(), "https://forecastrecord.com/football/matches/synthetic/index.json", NOW
    )
    assert len(picks) == 1
    pick = picks[0]
    assert pick["observedAt"] == NOW.isoformat()
    assert pick["kickoff"] == "2026-11-20T20:00:00+00:00"
    assert pick["line"] == "2.5"
    assert pick["declaredOdds"] == "1.85"
    assert pick["authorId"].startswith("forecaster:")
    assert "Synthetic Author" not in str(picks)


@pytest.mark.parametrize(
    "change",
    [
        {"late_publication": True},
        {"withdrawn": True},
        {"authorship": {"forecaster": "Editorial team", "forecaster_named_in_text": False}},
        {"authorship": {"forecaster": "Named document author"}},
        {"authorship": {"forecaster_named_in_text": True}, "source_info": {"speaker": "Document author", "url": "https://example.invalid/a"}},
        {
            "authorship": {
                "forecaster": "Synthetic Author",
                "excluded_from_individual_summaries": True,
            }
        },
        {
            "source_info": {
                "url": "https://example.invalid/video",
                "authorship": "channel_consensus",
            }
        },
        {"dates": {"detected_at": "2026-11-20T20:00:01Z"}},
        {"published_at": "2026-11-18T14:00:00Z"},
    ],
)
def test_late_withdrawn_consensus_and_future_publication_are_not_picks(change):
    data = card()
    data["evidence_items"][0].update(change)
    assert (
        project_forecasts(
            data, "https://forecastrecord.com/football/matches/synthetic/index.json", NOW
        )
        == []
    )


def test_late_local_detection_is_not_retroactive_evidence():
    assert (
        project_forecasts(
            card(),
            "https://forecastrecord.com/football/matches/synthetic/index.json",
            datetime(2026, 11, 21, tzinfo=UTC),
        )
        == []
    )


def package(tmp_path, budget=12):
    manifest = dict(
        mission_id="test",
        authorized_stages=["E1", "E2"],
        maximum_stage="E2",
        external_effects=dict(https_get_max=budget, per_source_max=budget),
        compute_budget=dict(max_bytes=2000000),
        time_budget=dict(seconds=600),
        source_hash="0" * 64,
        expires_at=(NOW + timedelta(hours=4)).isoformat(),
    )
    plan = dict(
        id="test",
        sourceHash="0" * 64,
        startsAt=NOW.isoformat(),
        expiresAt=manifest["expires_at"],
        slots=[NOW.isoformat(), (NOW + timedelta(hours=2)).isoformat()],
        maxEventsPerSlot=3,
        dueWindowSeconds=180,
        indexUrl="https://forecastrecord.com/football/matches/europe/france/index.json",
        codePins={"runner": "a"},
    )
    (tmp_path / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    (tmp_path / "plan.json").write_bytes(canonical(plan) + b"\n")
    (tmp_path / "authorization.json").write_bytes(
        canonical(
            dict(
                decision="AUTHORIZED",
                decisionReference="synthetic",
                planSha256=plan_hash(plan),
                manifestSha256=sha256((tmp_path / "manifest.json").read_bytes()).hexdigest(),
            )
        )
    )
    return plan


def fake_get(calls):
    def get(url):
        calls.append(url)
        if url.endswith("robots.txt"):
            return Response(200, b"User-agent: *\nAllow: /\n", "text/plain", None)
        if "/api/" in url:
            data = dict(
                schema_version="2.0",
                page_type="api",
                plans=[
                    dict(
                        display_name="Public",
                        status="available",
                        requests_per_month=1000,
                        limit_per_minute=10,
                    )
                ],
                text_blocks=[
                    dict(
                        heading="Rules of use",
                        body="Attribution to the source page is required; what we license is the measurement",
                    )
                ],
            )
        elif "/france/" in url:
            data = dict(
                schema_version="2.0",
                catalog=dict(
                    contract_version="1",
                    groups=[
                        dict(
                            title="France · Ligue 1",
                            items=[dict(url="/football/matches/synthetic/", name="PSG Lens")],
                        )
                    ],
                ),
            )
        else:
            data = card()
        return Response(200, canonical(data), "application/json", None)

    return get


def test_repeat_slot_is_idempotent_and_distinct_slots_recur(tmp_path):
    package(tmp_path)
    calls = []
    assert (
        execute_slot(
            tmp_path,
            pins={"runner": "a"},
            now=lambda: NOW,
            get=fake_get(calls),
            sleep=lambda _: None,
        )
        == "recorded"
    )
    assert len(calls) == 4
    assert (
        execute_slot(
            tmp_path,
            pins={"runner": "a"},
            now=lambda: NOW,
            get=fake_get(calls),
            sleep=lambda _: None,
        )
        == "already_claimed"
    )
    assert len(calls) == 4
    execute_slot(
        tmp_path,
        pins={"runner": "a"},
        now=lambda: NOW + timedelta(hours=2),
        get=fake_get(calls),
        sleep=lambda _: None,
    )
    assert len(calls) == 8
    view = snapshot(tmp_path, now=NOW + timedelta(hours=2))
    assert view["distinctPicks"] == 1
    assert len(view["picks"][0]["versions"]) == 1
    assert view["picks"][0]["firstSeenAt"] == NOW.isoformat()


def test_missing_authority_and_pin_drift_send_zero_requests(tmp_path):
    package(tmp_path)
    calls = []
    with pytest.raises(ValueError):
        execute_slot(tmp_path, pins={"runner": "wrong"}, now=lambda: NOW, get=fake_get(calls))
    (tmp_path / "authorization.json").unlink()
    with pytest.raises(ValueError):
        execute_slot(tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=fake_get(calls))
    assert not calls
    assert not (tmp_path / "events.jsonl").exists()


def test_global_budget_survives_wakeup_and_missed_slots_are_counted(tmp_path):
    package(tmp_path, budget=5)
    calls = []
    execute_slot(
        tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=fake_get(calls), sleep=lambda _: None
    )
    execute_slot(
        tmp_path,
        pins={"runner": "a"},
        now=lambda: NOW + timedelta(hours=2),
        get=fake_get(calls),
        sleep=lambda _: None,
    )
    assert len(calls) == 5
    assert snapshot(tmp_path, now=NOW + timedelta(hours=3))["counts"]["failed"] == 1


def test_late_wakeup_never_catches_up(tmp_path):
    package(tmp_path)
    calls = []
    assert (
        execute_slot(
            tmp_path,
            pins={"runner": "a"},
            now=lambda: NOW + timedelta(minutes=10),
            get=fake_get(calls),
        )
        == "no_due_slot"
    )
    assert snapshot(tmp_path, now=NOW + timedelta(minutes=10))["counts"]["missed"] == 1
    assert not calls


def test_public_video_id_is_retained_tracking_and_secrets_are_not():
    assert (
        origin_url("https://www.youtube.com/watch?v=abcdef12345&utm_source=foo")
        == "https://www.youtube.com/watch?v=abcdef12345"
    )
    assert origin_url("https://example.invalid/a?token=secret") is None


def test_response_after_slot_window_is_not_projected(tmp_path):
    package(tmp_path)
    clock = [NOW]
    calls = []
    get = fake_get(calls)

    def advancing_get(url):
        response = get(url)
        clock[0] = NOW + timedelta(minutes=4)
        return response

    execute_slot(
        tmp_path,
        pins={"runner": "a"},
        now=lambda: clock[0],
        get=advancing_get,
        sleep=lambda _: None,
    )
    assert len(calls) == 1
    assert snapshot(tmp_path, now=clock[0])["distinctPicks"] == 0


def test_verdict_requires_both_slots_and_a_closed_window(tmp_path):
    package(tmp_path)
    calls = []
    execute_slot(
        tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=fake_get(calls), sleep=lambda _: None
    )
    assert snapshot(tmp_path, now=NOW)["technicalVerdict"] == "PENDING"
    assert snapshot(tmp_path, now=NOW + timedelta(hours=5))["technicalVerdict"] == "PARTIAL"
    execute_slot(
        tmp_path,
        pins={"runner": "a"},
        now=lambda: NOW + timedelta(hours=2),
        get=fake_get(calls),
        sleep=lambda _: None,
    )
    assert snapshot(tmp_path, now=NOW + timedelta(hours=5))["technicalVerdict"] == "PASS_AND_HOLD"


def test_provider_withdrawal_hides_pick_without_rewriting_history(tmp_path):
    package(tmp_path)
    calls = []
    execute_slot(
        tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=fake_get(calls), sleep=lambda _: None
    )
    prefix = (tmp_path / "events.jsonl").read_bytes()
    original = fake_get(calls)

    def withdrawn(url):
        response = original(url)
        if "/matches/synthetic/" in url:
            data = card()
            data["restrictions"] = {"name_withdrawn": True}
            return Response(200, canonical(data), "application/json", None)
        return response

    execute_slot(
        tmp_path,
        pins={"runner": "a"},
        now=lambda: NOW + timedelta(hours=2),
        get=withdrawn,
        sleep=lambda _: None,
    )
    view = snapshot(tmp_path, now=NOW + timedelta(hours=3))
    assert view["distinctPicks"] == 0
    assert view["historicalPickCount"] == view["withdrawnPickCount"] == 1
    assert (tmp_path / "events.jsonl").read_bytes().startswith(prefix)


def test_rate_limit_halts_future_requests(tmp_path):
    package(tmp_path)
    calls = []

    def limited(url):
        calls.append(url)
        return Response(429, b"", "text/plain", None)

    execute_slot(tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=limited, sleep=lambda _: None)
    assert (
        execute_slot(
            tmp_path,
            pins={"runner": "a"},
            now=lambda: NOW + timedelta(hours=2),
            get=limited,
            sleep=lambda _: None,
        )
        == "halted"
    )
    assert len(calls) == 1


def test_legacy_byline_and_seed_are_excluded_without_rewriting_journal(tmp_path):
    import json
    from robin.source_observatory.connectors import Journal

    plan = package(tmp_path)
    pick = project_forecasts(
        card(), "https://forecastrecord.com/football/matches/synthetic/index.json", NOW
    )[0]
    pick.pop("attributionRole")
    journal = Journal(
        tmp_path, json.loads((tmp_path / "manifest.json").read_bytes()), now=lambda: NOW
    )
    journal.append(
        "FORECAST_VISIT",
        eventId="synthetic-event",
        kickoff=pick["kickoff"],
        label="Synthetic",
        observedAt=NOW.isoformat(),
        picks=[pick],
        eventStatus="scheduled",
    )
    prefix = (tmp_path / "events.jsonl").read_bytes()
    seed = canonical(
        dict(picks=[dict(id="legacy-seed", authorId="publisher", fixtureId="synthetic-event")])
    )
    (tmp_path / "seed.json").write_bytes(seed)
    plan["seedFileSha256"] = sha256(seed).hexdigest()
    (tmp_path / "plan.json").write_bytes(canonical(plan))
    view = snapshot(tmp_path, now=NOW)
    assert view["distinctPicks"] == 0
    assert view["unresolvedAttributions"] == 1
    assert view["tipsters"] == []
    assert (tmp_path / "events.jsonl").read_bytes() == prefix


def test_closure_is_serialized_idempotent_and_never_networks(tmp_path):
    from robin.source_observatory.connectors import read_events

    package(tmp_path)
    with pytest.raises(ValueError, match="before expiry"):
        close_campaign(tmp_path, now=NOW)
    (tmp_path / "recurring.lock").write_text("another runner")
    with pytest.raises(FileExistsError):
        close_campaign(tmp_path, now=NOW + timedelta(hours=5))
    (tmp_path / "recurring.lock").unlink()
    close_campaign(tmp_path, now=NOW + timedelta(hours=5))
    prefix = (tmp_path / "events.jsonl").read_bytes()
    close_campaign(tmp_path, now=NOW + timedelta(hours=5))
    assert (tmp_path / "events.jsonl").read_bytes() == prefix
    assert [e["kind"] for e in read_events(tmp_path / "events.jsonl")] == ["CAMPAIGN_CLOSED"]


def test_started_slot_is_running_until_its_deadline(tmp_path):
    import json
    from robin.source_observatory.connectors import Journal

    package(tmp_path)
    j = Journal(tmp_path, json.loads((tmp_path / "manifest.json").read_bytes()), now=lambda: NOW)
    j.append("SLOT_STARTED", slot=NOW.isoformat())
    assert snapshot(tmp_path, now=NOW + timedelta(seconds=10))["counts"]["running"] == 1
    assert snapshot(tmp_path, now=NOW + timedelta(seconds=181))["counts"]["interrupted"] == 1


def test_missing_required_personal_attribution_stops_campaign(tmp_path):
    import json
    from robin.source_observatory.connectors import read_events

    package(tmp_path)
    calls = []
    original = fake_get(calls)

    def collective(url):
        response = original(url)
        if "/matches/synthetic/" in url:
            data = card()
            data["evidence_items"][0]["authorship"] = {"forecaster": "Editorial team"}
            return Response(200, canonical(data), "application/json", None)
        return response

    execute_slot(tmp_path, pins={"runner": "a"}, now=lambda: NOW, get=collective, sleep=lambda _: None)
    used = len(calls)
    assert execute_slot(tmp_path, pins={"runner": "a"}, now=lambda: NOW + timedelta(hours=2), get=collective) == "halted"
    assert len(calls) == used
    assert snapshot(tmp_path, now=NOW)["distinctPicks"] == 0
    halt = next(e for e in read_events(tmp_path / "events.jsonl") if e["kind"] == "CAMPAIGN_HALTED")
    assert halt["decision"] == "FAIL_AND_STOP"


def test_reader_rejects_an_authorization_file_with_wrong_hash(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from robin.source_observatory.recurring import code_pins

    root = Path(__file__).resolve().parents[2]
    plan = package(tmp_path)
    plan.update(codePins=code_pins(root), intervalSeconds=7200, authorizationText="Synthetic")
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    manifest["external_effects"]["scheduled_task"] = "Synthetic"
    (tmp_path / "manifest.json").write_bytes(canonical(manifest))
    (tmp_path / "plan.json").write_bytes(canonical(plan))
    # The authorization still pins the old plan. Presence alone grants nothing.
    result = subprocess.run([sys.executable, "-X", "utf8", str(root / "cockpit/scripts/read-tipsters-recurring.py"),
                             "--directory", str(tmp_path), "--campaign-directory", str(tmp_path)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    view = json.loads(result.stdout)
    assert view["campaign"]["state"] == "invalid_package"
    assert view["campaign"]["authorizationText"] is None
    assert not (tmp_path / "events.jsonl").exists()
