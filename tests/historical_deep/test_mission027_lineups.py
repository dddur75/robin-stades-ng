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
from scripts.run_mission027_lineups import ReceiptBoundary, collect_once, complete, validate_targets


def test_whitelist_and_two_complete_teams_are_required():
    groups = json.loads(Path("configs/execution/mission027-targets.json").read_text())["groups"]
    validate_targets(groups)
    groups[0]["season"] = 2025
    with pytest.raises(AssertionError):
        validate_targets(groups)
    teams = [{"team": {"id": n}, "formation": "4-3-3", "startXI": [
        {"player": {"id": p}} for p in range(1, 12)
    ]} for n in (1, 2)]
    assert complete(teams)
    assert not complete([{"team": None}, {}])
    teams[0]["startXI"].pop()
    assert not complete(teams)


def test_reservation_prevents_duplicate_calls_and_uncertain_retry():
    class Provider:
        calls = 0

        def get(self, endpoint, params):
            assert endpoint == "/fixtures/lineups" and params == {"fixture": 1}
            self.calls += 1
            return {"response": []}

    provider, store = Provider(), InMemoryObjectStore()
    collector = HistoricalDeepCollector(provider, ReceiptBoundary(R2FirstRepository(store)))
    request = dict(phase="lineups_only", competition=39, season=2020, family="lineups",
                   endpoint="/fixtures/lineups", params={"fixture": 1})
    assert collect_once(collector, store, request) is not None
    assert collect_once(collector, store, request).reused
    assert provider.calls == 1
    collector.repository = R2FirstRepository(InMemoryObjectStore())
    assert collect_once(collector, store, request) is None
    assert provider.calls == 1


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
    assert result["receipt_metadata_reads"] == 0
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
    body = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([{"provider_fixture_id": fixture, "season": season,
        "availability_status": "POST_MATCH_ONLY", "payload": '{"team":{"id":1}}'}]), body)
    group = {"fixture_ids": [1], "season": 2020}
    if (fixture, season) == (1, 2020):
        rows, projected = runner.projection_records(body.getvalue(), group)
        assert len(rows) == 1 and projected == {1: [{"team": {"id": 1}}]}
    else:
        with pytest.raises(AssertionError):
            runner.projection_records(body.getvalue(), group)
