import json
from pathlib import Path

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
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
