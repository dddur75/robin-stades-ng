import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
from scripts.run_mission028 import Budget, collect_once, load_targets, match_rows, season_start

NOW = datetime(2026, 10, 17, 23, 59, tzinfo=UTC)
ROW = dict(ligue_fd="E1", saison_fd="2019-20", date="2019-08-01",
           equipe_dom_fd="Bristol City", equipe_ext_fd="QPR", buts_dom="2", buts_ext="1")


def fixture(identifier=1, day="2019-08-02", home="Bristol City", away="Queens Park Rangers"):
    return dict(fixture=dict(id=identifier, date=day + "T00:00:00+00:00"),
                league=dict(id=40, season=2019), goals=dict(home=2, away=1),
                teams=dict(home=dict(name=home), away=dict(name=away)))


def test_frozen_population_and_hash_before_use(tmp_path):
    rows = load_targets()
    assert len(rows) == 60515
    assert len({r["ligue_fd"] for r in rows}) == 33
    assert len({(r["ligue_fd"], season_start(r["saison_fd"])) for r in rows}) == 198
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="HASH"):
        load_targets(bad)


@pytest.mark.parametrize("label", ["2025", "2025-26", "2025/2026", "2018", "2024/2026"])
def test_holdout_and_invalid_seasons_rejected(label):
    with pytest.raises(ValueError, match="SEASON"):
        season_start(label)


def test_match_requires_date_both_names_score_and_unique_fixture():
    aliases = {"E1|QPR": "Queens Park Rangers"}
    table, rates = match_rows([ROW], [fixture()], aliases)
    assert table[0]["fixture_id"] == 1 and rates["E1"]["fraction"] == 1
    for candidates in ([fixture(day="2019-08-03")], [fixture(home="Bristol Rovers")],
                       [dict(fixture(), goals=dict(home=1, away=2))], [fixture(), fixture(2)]):
        table, rates = match_rows([ROW], candidates, aliases)
        assert table[0]["fixture_id"] is None and rates["E1"]["fraction"] == 0
    table, _ = match_rows([ROW, ROW], [fixture()], aliases)
    assert all(row["fixture_id"] is None for row in table)


def test_budget_daily_utc_total_and_reserve_survive_resume():
    for entries, remaining in (([{"day": "2026-10-17"}] * 70000, 150000),
                               ([{"day": "2026-10-16"}] * 122200, 150000), ([], 5000)):
        budget = Budget(entries)
        with pytest.raises(RuntimeError, match="BUDGET"):
            budget.reserve(NOW, remaining)
    budget = Budget([{"day": "2026-10-17"}] * 69999)
    budget.reserve(NOW, 5001)
    with pytest.raises(RuntimeError):
        budget.reserve(NOW, 150000)
    budget.reserve(NOW + timedelta(minutes=2), 150000)
    assert budget.total == 70001


@pytest.mark.parametrize("crash", [False, True])
def test_once_only_even_after_failure_and_new_collector(crash):
    class Provider:
        calls = 0

        def get(self, endpoint, params):
            self.calls += 1
            if crash:
                raise RuntimeError("NETWORK_FAILED")
            return {"response": [fixture()]}

    store, provider, budget = InMemoryObjectStore(), Provider(), Budget([])
    request = dict(phase="mission028", competition=40, season=2019, family="fixtures",
                   endpoint="/fixtures", params={"league": 40, "season": 2019})
    for _ in range(2):
        collector = HistoricalDeepCollector(provider, R2FirstRepository(store))
        try:
            collect_once(collector, store, budget, request, NOW, 150000)
        except RuntimeError:
            assert crash
    assert provider.calls == budget.total == 1


def test_entrypoint_then_replay_uses_durable_cache_without_http(monkeypatch, tmp_path):
    from scripts import run_mission028 as run
    store, endpoints = InMemoryObjectStore(), []
    locks = dict(STORAGE_PAUSED="true", P3_P4_PAUSED="true", PRODUCTION_LOCKED="true",
        REAL_BETS="false", NO_BET_DEFAULT="true", PROMOTION_LOCKED="true",
        SOCIAL_PUBLISHING_ENABLED="false", DEMO_MODE_ENABLED="false",
        POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES="false", THE_ODDS_API_HISTORICAL_CREDITS="false",
        GITHUB_RUN_ID="synthetic", GITHUB_SHA="a" * 40)
    for key, value in locks.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(run, "load_targets", lambda: [ROW])
    monkeypatch.setattr(run, "LEAGUES", {"E1": 40})
    monkeypatch.setattr(run, "OUTPUT", tmp_path)
    monkeypatch.setattr(run, "R2ObjectStore", lambda env: store)

    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        endpoints.append(url.rsplit("/", 1)[1])
        response = dict(subscription=dict(plan="Mega", active=True, end="2026-11-25"),
                        requests=dict(limit_day=150000, current=0))
        if endpoints[-1] != "status":
            f = fixture(identifier=kwargs["params"]["season"], away="QPR")
            f["league"]["season"] = kwargs["params"]["season"]
            response = [f]
        return SimpleNamespace(status_code=200, headers={}, json=lambda: {"response": response})

    monkeypatch.setattr(run.requests, "get", get)
    assert run.main() == 0
    assert endpoints == ["status"] + ["fixtures"] * 6
    receipt = json.loads((tmp_path / "public-receipt.json").read_text())
    assert receipt["calls"] == 6 and receipt["status_calls"] == 1
    monkeypatch.setenv("GITHUB_RUN_ID", "synthetic-replay")
    monkeypatch.setenv("MISSION028_REPLAY", "true")
    assert run.main() == 0 and len(endpoints) == 7
