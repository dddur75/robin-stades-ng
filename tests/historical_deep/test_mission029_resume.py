from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.provider import CircuitOpenError
from robin.historical_deep.storage import InMemoryObjectStore


def test_open_circuit_stops_before_marking_uncalled_matches_uncertain(monkeypatch, tmp_path):
    from scripts import run_mission029 as run
    store, now = InMemoryObjectStore(), datetime.now(UTC)
    def deny():
        raise CircuitOpenError('CIRCUIT_OPEN')
    client = SimpleNamespace(quota=None, assert_transport_available=deny,
        get_status=lambda: SimpleNamespace(status_expires_at=now + timedelta(hours=1)))
    monkeypatch.setattr(run, 'ApiFootballDeepClient', lambda **kw: client)
    monkeypatch.setattr(run, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(run, 'assert_safety_locks', lambda env: None)
    monkeypatch.setattr(run, 'OUTPUT', tmp_path)
    for key, value in dict(WORKFLOW71_ADMISSION='true', GITHUB_ACTIONS='true',
        GITHUB_SHA='a' * 40).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('API_FOOTBALL_KEY', 'synthetic')
    rows = [dict(code='E0', league=39, season=2020, fixture=i) for i in (1, 2)]
    assert run.run_phase('A', rows, ['statistics']) == 2
    assert not list(store.iter_keys(f'{run.PREFIX}/results/'))
    assert not list(store.iter_keys(f'{run.PREFIX}/once/'))


def test_provider_reserve_does_not_burn_an_uncalled_fixture_marker():
    from scripts import run_mission029 as run
    store = InMemoryObjectStore()
    collector = SimpleNamespace(_make_task=lambda **kw: object(), _collect=lambda **kw: None,
        repository=SimpleNamespace(receipt_for=lambda task: None),
        provider=SimpleNamespace(quota=SimpleNamespace(status=SimpleNamespace(daily_remaining=5000))))
    with pytest.raises(RuntimeError, match='RESERVE'):
        run.collect_once(collector, store, dict(season=2020, family='statistics', params=dict(fixture=1)))
    assert not list(store.iter_keys(f'{run.PREFIX}/once/'))
