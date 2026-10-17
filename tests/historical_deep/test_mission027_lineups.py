import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
from scripts import run_mission027_lineups as runner


def test_whitelist_and_two_complete_teams_are_required():
    groups = json.loads(Path("configs/execution/mission027-targets.json").read_text())["groups"]
    runner.validate_targets(groups)
    groups[0]["season"] = 2025
    with pytest.raises(AssertionError):
        runner.validate_targets(groups)
    teams = [dict(team=dict(id=n), formation="4-3-3", startXI=[dict(player=dict(id=p)) for p in range(1, 12)]) for n in (1, 2)]
    assert runner.complete(teams)
    assert not runner.complete([{"team": None}, {}])
    teams[0]["startXI"].pop()
    assert not runner.complete(teams)

def test_reservation_prevents_duplicate_calls_and_uncertain_retry():
    calls, store = [], InMemoryObjectStore()
    provider = SimpleNamespace(get=lambda endpoint, params:
        calls.append((endpoint, params)) or {"response": []})
    collector = HistoricalDeepCollector(provider, runner.ReceiptBoundary(R2FirstRepository(store)))
    request = dict(phase="lineups_only", competition=39, season=2020, family="lineups",
                   endpoint="/fixtures/lineups", params={"fixture": 1})
    assert runner.collect_once(collector, store, request) is not None
    assert runner.collect_once(collector, store, request).reused
    assert calls == [("/fixtures/lineups", {"fixture": 1})]
    collector.repository = R2FirstRepository(InMemoryObjectStore())
    assert runner.collect_once(collector, store, request) is None
    assert calls == [("/fixtures/lineups", {"fixture": 1})]

def test_progress_reads_only_reservation_keys_without_provider_credentials(monkeypatch, tmp_path):
    workflow = yaml.safe_load(Path(".github/workflows/71-historical-deep-fixture-bundle-harvest.yml").read_text())
    for key, value in workflow["jobs"]["fixture-bundles"]["env"].items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    fixture = json.loads(Path("configs/execution/mission027-targets.json").read_text())["groups"][0]["fixture_ids"][0]
    monkeypatch.setattr(sys, "argv", ["run", "--progress"])
    monkeypatch.setattr(runner, "OUTPUT", tmp_path)
    probe = SimpleNamespace(iter_keys=lambda prefix: [f"{prefix}{fixture}.json"])
    monkeypatch.setattr(runner, "R2ObjectStore", lambda environment: probe)
    monkeypatch.setattr(runner.requests, "get", lambda *a, **kw: pytest.fail("provider forbidden"))
    assert runner.main() == 0
    result = json.loads((tmp_path / "progress.json").read_text())
    assert result["reserved_targets"] == 1
    assert result["reserved_by_scope"]["Premier-League"] == 1
    assert result["lineup_calls"] == result["status_calls"] == result["r2_writes"] == 0

def test_each_worker_is_limited_to_two_rps_and_original_proof_lease(monkeypatch):
    clock, sent = [0.0], []
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runner.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(runner.requests, "get", lambda *a, **kw: sent.append(clock[0]))
    transport = runner.LineupTransport()
    for _ in range(3):
        transport.get("https://example.test/fixtures/lineups")
    assert sent == [0.0, 0.5, 1.0] and transport.calls == 3
    transport.deadline = runner.datetime.now(runner.UTC) - runner.timedelta(seconds=1)
    with pytest.raises(RuntimeError, match="STATUS_PROOF_LEASE_ENDED"):
        transport.get("https://example.test/fixtures/lineups")
    assert transport.calls == 3

@pytest.mark.parametrize("fixture,season", [(1, 2020), (2, 2020), (1, 2025)])
def test_cached_projection_rejects_wrong_fixture_or_season(fixture, season):
    body, group = io.BytesIO(), {"fixture_ids": [1], "season": 2020}
    pq.write_table(pa.Table.from_pylist([{"provider_fixture_id": fixture, "season": season,
        "availability_status": "POST_MATCH_ONLY", "payload": '{"team":{"id":1}}'}]), body)
    if (fixture, season) == (1, 2020):
        rows, projected = runner.projection_records(body.getvalue(), group)
        assert len(rows) == 1 and projected == {1: [{"team": {"id": 1}}]}
    else:
        with pytest.raises(AssertionError):
            runner.projection_records(body.getvalue(), group)

@pytest.mark.parametrize("calls,remaining,error", [(8000, 150000, "MISSION_BUDGET_REACHED"),
    (8001, 150000, "MISSION_BUDGET_REACHED"), (0, 5000, "MISSION_BUDGET_REACHED"),
    (0, 4999, "MISSION_BUDGET_REACHED"), (7999, 5001, "HTTP_FORBIDDEN")])
def test_mission_budget_and_reserve_stop_before_collection(monkeypatch, tmp_path, calls, remaining, error):
    config = json.loads(Path("configs/execution/mission027-targets.json").read_text())
    raw = json.dumps(dict(status="PASS", status_calls=1, checked_at=runner.datetime.now(runner.UTC).isoformat(),
        subscription_end="2027-01-01T00:00:00Z", daily_limit=150000, quota_remaining=remaining)).encode()
    config["status_receipt_sha256"] = runner.hashlib.sha256(raw).hexdigest()
    for name, value in dict(Path=lambda _: SimpleNamespace(read_text=lambda: json.dumps(config), read_bytes=lambda: raw),
        OUTPUT=tmp_path, Exception=LookupError,  # Expose the exact budget error.
        assert_safety_locks=lambda env: None, R2ObjectStore=lambda env: InMemoryObjectStore(),
        QuotaController=lambda status: SimpleNamespace(status=status)).items():
        monkeypatch.setattr(runner, name, value, raising=False)
    monkeypatch.setattr(runner.LineupTransport, "calls", calls)
    def forbidden(*args):
        raise RuntimeError("HTTP_FORBIDDEN")
    monkeypatch.setattr(runner, "collect_once", forbidden)
    for name, value in {"MISSION027_COMPETITION": "Premier-League", "API_FOOTBALL_KEY": str(tmp_path),
        "GITHUB_SHA": "a" * 40}.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=error):
        runner.main()
