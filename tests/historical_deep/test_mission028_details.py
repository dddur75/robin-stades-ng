import csv
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
from scripts.mission028_budget import reserve_status
from scripts.run_mission028_details import DaySlots, complete, load_mapping, once

NOW = datetime(2026, 10, 17, 23, 59, tzinfo=UTC)
@pytest.mark.parametrize("code,season,league", [("E1", "2019-20", 40), ("ARG", "2023", 1032)])
def test_mapping_hash_and_source_identity_fail_closed(tmp_path, monkeypatch, code, season, league):
    from scripts import run_mission028_details as run
    original = dict(ligue_fd=code, saison_fd=season, date=season[:4]+"-08-01",
                    equipe_dom_fd="A", equipe_ext_fd="B", buts_dom="1", buts_ext="0")
    monkeypatch.setattr(run, "load_targets", lambda: [original])
    path, manifest = tmp_path / "mapping.csv", tmp_path / "manifest.json"
    row = dict(original, source_row=1, league_id=league, season=int(season[:4]), fixture_id=10, reason="MATCHED")
    def write():
        with path.open("w", newline="") as stream:
            csv.writer(stream).writerows([row.keys(), row.values()])
        manifest.write_text(json.dumps(dict(source_sha256=run.DIGEST,
            mapping_sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    write()
    assert load_mapping(path, manifest)[0]["fixture_id"] == 10
    row["season"] = 2025
    write()
    with pytest.raises(ValueError, match="MAPPING"):
        load_mapping(path, manifest)
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="HASH"):
        load_mapping(path, manifest)
def test_shared_atomic_daily_slots_include_phase1_reserve_and_midnight():
    store = InMemoryObjectStore()
    left, right = DaySlots(store, NOW, worker=5), DaySlots(store, NOW, worker=5)
    left.next_slot = right.next_slot = 129749
    left.reserve(NOW, 5001)
    with pytest.raises(RuntimeError, match="BUDGET"):
        right.reserve(NOW, 150000)
    with pytest.raises(RuntimeError, match="DAY"):
        left.reserve(NOW + timedelta(minutes=2), 150000)
    with pytest.raises(RuntimeError, match="RESERVE"):
        DaySlots(store, NOW + timedelta(days=1)).reserve(NOW + timedelta(days=1), 5000)
def test_once_after_crash_has_no_second_http_request():
    class Provider:
        calls = 0
        def get(self, endpoint, params):
            self.calls += 1
            raise RuntimeError("FAILED")
    store, provider = InMemoryObjectStore(), Provider()
    request = dict(phase="mission028", competition=40, season=2019, family="lineups",
                   endpoint="/fixtures/lineups", params=dict(fixture=10))
    for _ in range(2):
        collector = HistoricalDeepCollector(provider, R2FirstRepository(store))
        try:
            once(collector, store, DaySlots(store, NOW), request, NOW, 150000)
        except RuntimeError:
            pass
    assert provider.calls == 1
def test_lineups_require_two_teams_formation_and_eleven_unique_players():
    teams = [dict(team=dict(id=i), formation="4-3-3", startXI=[dict(player=dict(id=n))
             for n in range(1, 12)]) for i in (1, 2)]
    assert complete("lineups", teams)
    teams[1]["startXI"][0] = teams[1]["startXI"][1]
    assert not complete("lineups", teams)
    assert complete("statistics", [dict(team=dict(id=i), statistics=[dict(type="Shots", value=0)])
                                    for i in (1, 2)])
    assert not complete("statistics", [])
@pytest.mark.parametrize("family", ["lineups", "statistics"])
@pytest.mark.parametrize("code,year,league", [("E1", 2019, 40), ("ARG", 2023, 1032)])
def test_details_entrypoint_persists_parquet_and_resumes_without_http(monkeypatch, tmp_path, family, code, year, league):
    from robin.historical_deep.contracts import ProviderStatus
    from scripts import run_mission028_details as run
    store, calls, now = InMemoryObjectStore(), [], datetime.now(UTC)
    for key, value in dict(STORAGE_PAUSED="true", P3_P4_PAUSED="true", PRODUCTION_LOCKED="true",
        REAL_BETS="false", NO_BET_DEFAULT="true", PROMOTION_LOCKED="true", SOCIAL_PUBLISHING_ENABLED="false",
        DEMO_MODE_ENABLED="false", POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES="false",
        THE_ODDS_API_HISTORICAL_CREDITS="false", MISSION028_WORKER=str(sorted(run.LEAGUES).index(code) % 16), MISSION028_FAMILY=family,
        GITHUB_RUN_ID="synthetic", GITHUB_SHA="a" * 40).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("API_FOOTBALL_KEY", str(tmp_path))
    monkeypatch.setattr(run, "OUTPUT", tmp_path)
    monkeypatch.setattr(run, "R2ObjectStore", lambda env: store)
    monkeypatch.setattr(run, "load_mapping", lambda: [dict(ligue_fd=code, season=str(year), fixture_id=10, league_id=league)])
    (tmp_path / "preflight.json").write_text(ProviderStatus(plan="Mega", active=True,
        daily_limit=150000, daily_used=0, daily_remaining=150000, checked_at=now,
        expires_at=now + timedelta(minutes=110), subscription_end=now + timedelta(days=30)).model_dump_json())
    teams = [dict(team=dict(id=i), formation="4-3-3", startXI=[dict(player=dict(id=n))
             for n in range(1, 12)]) for i in (1, 2)]
    if family == "statistics":
        teams = [dict(team=dict(id=i), statistics=[dict(type="Shots", value=0)]) for i in (1, 2)]
    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["params"] == {"fixture": 10}
        calls.append(url)
        return SimpleNamespace(status_code=200, headers={}, json=lambda: {"response": teams})
    monkeypatch.setattr("requests.get", get)
    assert run.main() == 0
    monkeypatch.setenv("GITHUB_RUN_ID", "synthetic-resume")
    assert run.main() == 0 and len(calls) == 1
    receipt = json.loads(next(tmp_path.glob("worker-*-public-receipt.json")).read_text())
    assert receipt["daily_cap"] == 130000 and receipt["daily_reserve"] == 5000
    files = list(tmp_path.rglob("*.parquet"))
    assert len(files) == 1
    assert all(r["competition_id"] == league for r in run.pq.ParquetFile(files[0]).read().to_pylist())
@pytest.mark.parametrize("status_slots", [0, 49, 925])
def test_preflight_refuses_a_different_binding_or_exhausted_status_slots(monkeypatch, tmp_path, status_slots):
    from scripts import run_mission028_details as run
    store, manifest = InMemoryObjectStore(), tmp_path / "mapping.json"
    manifest.write_bytes(b"second")
    for name, value in dict(OUTPUT=tmp_path, MANIFEST=manifest, load_mapping=lambda: [],
        R2ObjectStore=lambda env: store, assert_safety_locks=lambda env: None,
        ApiFootballDeepClient=lambda **kwargs: pytest.fail("provider must not be created")).items():
        monkeypatch.setattr(run, name, value)
    store.put_if_absent(f"{run.PREFIX}/mapping-manifest.json", b"second" if status_slots else b"first")
    day = datetime.now(UTC).date().isoformat() if status_slots == 49 else "old"
    for i in range(status_slots):
        store.put_if_absent(f"{run.PREFIX}/status-slots/{day}/{i:02d}", b'{}')
    assert run.preflight() == 2
    assert json.loads((tmp_path / "preflight-public-receipt.json").read_text())["reason_class"] == "RuntimeError"
    assert json.loads((tmp_path / "preflight-public-receipt.json").read_text())["status_calls"] == 0
@pytest.mark.parametrize("count,duplicate,allowed", [(61001, False, False), (2, True, False), (61000, False, True)])
def test_mapping_family_ceiling_and_unique_fixtures(tmp_path, monkeypatch, count, duplicate, allowed):
    from scripts import run_mission028_details as run
    source = dict(ligue_fd="E1", saison_fd="2019-20")
    monkeypatch.setattr(run, "load_targets", lambda: [source] * count)
    path, manifest = tmp_path / "mapping.csv", tmp_path / "manifest.json"
    path.write_text("ligue_fd,saison_fd,source_row,league_id,season,fixture_id,reason\n" + "".join(
        f"E1,2019-20,{i + 1},40,2019,{1 if duplicate else i + 1},MATCHED\n" for i in range(count)))
    manifest.write_text(json.dumps(dict(source_sha256=run.DIGEST,
        mapping_sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    if allowed:
        assert len(load_mapping(path, manifest)) == count
    else:
        with pytest.raises(ValueError, match="MISSION028_MAPPING_DUPLICATE_OR_OVERSIZED"):
            load_mapping(path, manifest)
@pytest.mark.parametrize("total,limit,reason", [(False, 49, "DAILY_BUDGET"), (True, 925, "TOTAL_BUDGET")])
def test_status_reservations_bound_daily_and_total_calls(total, limit, reason):
    from scripts.run_mission028 import PREFIX
    store = InMemoryObjectStore()
    for i in range(limit):
        store.put_if_absent(f"{PREFIX}/status-slots/{'old' if total else NOW.date().isoformat()}/{i:02d}", b'{}')
    with pytest.raises(RuntimeError, match=reason):
        reserve_status(store, NOW)
    if not total:
        reserve_status(store, NOW + timedelta(days=1))


def test_sixteen_workers_are_paced_to_eight_requests_per_second(monkeypatch, tmp_path):
    from scripts import mission028_performance as performance
    from scripts import run_mission028_details as run
    clock, sleeps = [100.], []
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    monkeypatch.setattr(performance.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(performance.time, "sleep", sleep)
    monkeypatch.setattr(run.requests, "get", lambda *a, **kw: None)
    monkeypatch.setattr(run, "datetime", SimpleNamespace(now=lambda tz: NOW - timedelta(minutes=1)))
    transport = run.PacedTransport(NOW, tmp_path / "pace.sqlite3")
    transport.get("https://example.invalid")
    transport.get("https://example.invalid")
    assert sleeps == [pytest.approx(.126)]
