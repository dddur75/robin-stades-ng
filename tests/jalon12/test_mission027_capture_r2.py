import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.storage import InMemoryObjectStore
from scripts import run_mission027_capture as capture
from scripts import run_prospective_observatory as base

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def fixture_record():
    return dict(
        fixture=dict(
            id=10, date=(NOW + timedelta(minutes=30)).isoformat(), status=dict(short="NS")
        ),
        league=dict(id=61, season=2026, round="Regular Season - 8"),
        teams=dict(home=dict(id=1), away=dict(id=2)),
    )


@pytest.mark.parametrize("database_present", [False, True])
def test_cli_capture_and_restart_use_only_r2_without_neon(monkeypatch, tmp_path, database_present):
    store, calls = InMemoryObjectStore(), []
    teams = [
        dict(
            team=dict(id=i),
            formation="4-3-3",
            startXI=[dict(player=dict(id=n)) for n in range(i * 20, i * 20 + 11)],
        )
        for i in (1, 2)
    ]

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    def forbidden_database(*args, **kwargs):
        pytest.fail("Mission 027 must never open Neon")

    def transport(url, *, params, **kwargs):
        calls.append((url.rsplit("/", 1)[-1], params))
        if url.endswith("/status"):
            response = dict(
                subscription=dict(plan="Mega", active=True, end="2027-01-01"),
                requests=dict(limit_day=150000, current=0),
            )
        elif url.endswith("/lineups"):
            response = teams
        else:
            response = [fixture_record()] if params.get("league", 61) == 61 else []
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(response=response))

    real_client = capture.ApiFootballDeepClient
    real_quota = capture.QuotaController
    monkeypatch.setattr(capture, "datetime", FixedDatetime)
    monkeypatch.setattr(
        capture, "ApiFootballDeepClient", lambda **kw: real_client(**kw, now=lambda: NOW)
    )
    monkeypatch.setattr(
        capture, "QuotaController", lambda proof: real_quota(proof, now=lambda: NOW)
    )
    monkeypatch.setattr(capture, "R2ObjectStore", lambda environment: store)
    monkeypatch.setattr(capture.requests, "get", transport)
    monkeypatch.setattr(base, "build_engine", forbidden_database)
    for key in ("DATABASE_URL", "ROBIN_DATABASE_URL"):
        if database_present:
            monkeypatch.setenv(key, "postgresql://must-not-connect/production")
        else:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("API_FOOTBALL_KEY", "synthetic")
    monkeypatch.setenv("GITHUB_SHA", "test")
    argv = ["capture", "capture-lineup", "--output", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", [*argv, "--estimate"])
    assert capture.main() == 0
    assert calls == []
    for run in ("first", "restart"):
        monkeypatch.setenv("GITHUB_RUN_ID", run)
        monkeypatch.setattr(
            sys,
            "argv",
            [*argv, "--execute", "--estimate-file", str(tmp_path / "lineup-capture-estimate.json")],
        )
        result = capture.main()
        assert result == 0, (tmp_path / "lineup-capture-report.json").read_text()
        report = json.loads(store.get_object(f"{capture.PREFIX}/runs/{run}.json"))
        assert report["captured_fixtures"] == 1 and report["daily_reserved"] == 7
        assert report["state_backend"] == "R2_ONLY"
        assert report["status_calls"] == int(run == "first")
        assert all(c["received_at"] < c["kickoff_at"] for c in report["captures"])
    assert len(calls) == 8 and sum(name == "status" for name, _ in calls) == 1
    repository = base.ProspectiveR2Repository(capture.SeasonStore(store))
    receipts = [
        repository.read_capture(
            json.loads(repository.store.get_object(k))["receipt"]["receipt_r2_key"]
        ).receipt
        for k in repository.store.iter_keys(capture.RECOVERY)
    ]
    assert {r.family.value for r in receipts} == {"FIXTURE", "LINEUP", "FORMATION"}
