import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.storage import InMemoryObjectStore

NOW = datetime(2026, 10, 18, 23, 59, tzinfo=UTC)


def test_exact_shared_daily_total_and_provider_boundaries():
    from robin.historical_deep.admission import PREFIX, Admission
    store = InMemoryObjectStore()
    gate = Admission(store, lambda: NOW)
    gate.proof = dict(remaining=5001, baseline=129999)
    store.put_if_absent(f'{PREFIX}/daily/{NOW.date()}/129998', b'{}')
    store.put_if_absent(f'{PREFIX}/mission029/239998', b'{}')
    gate.reserve('/fixtures/statistics', mission=True)
    with pytest.raises(RuntimeError, match='LIMIT'):
        gate.reserve('/fixtures/statistics', mission=True)
    gate = Admission(InMemoryObjectStore(), lambda: NOW)
    gate.proof = dict(remaining=5000, baseline=0)
    with pytest.raises(RuntimeError, match='RESERVE'):
        gate.reserve('/fixtures/statistics', mission=True)


def test_independent_gates_cannot_spend_the_last_slot_twice():
    from robin.historical_deep.admission import PREFIX, Admission
    store = InMemoryObjectStore()
    store.put_if_absent(f'{PREFIX}/daily/{NOW.date()}/129998', b'{}')
    gates = [Admission(store, lambda: NOW) for _ in range(2)]
    for gate in gates:
        gate.proof = dict(remaining=150000, baseline=129999)
    gates[0].reserve('/fixtures/events', mission=False)
    with pytest.raises(RuntimeError, match='LIMIT'):
        gates[1].reserve('/fixtures/events', mission=False)


def test_status_exact_caps_and_utc_rollover():
    from robin.historical_deep.admission import PREFIX, Admission
    store = InMemoryObjectStore()
    store.put_if_absent(f'{PREFIX}/statuses/total/923', b'{}')
    store.put_if_absent(f'{PREFIX}/statuses/{NOW.date()}/47', b'{}')
    gate = Admission(store, lambda: NOW)
    gate.reserve('/status', mission=True)
    with pytest.raises(RuntimeError, match='LIMIT'):
        gate.reserve('/status', mission=True)
    gate.clock = lambda: NOW + timedelta(minutes=2)
    with pytest.raises(RuntimeError, match='DAY'):
        gate.reserve('/status', mission=True)


def test_total_cap_survives_a_new_day_and_a_new_process():
    from robin.historical_deep.admission import PREFIX, Admission
    store = InMemoryObjectStore()
    store.put_if_absent(f'{PREFIX}/mission029/239999', b'{}')
    gate = Admission(store, lambda: NOW + timedelta(days=1))
    gate.proof = dict(remaining=150000, baseline=0)
    with pytest.raises(RuntimeError, match='LIMIT'):
        gate.reserve('/fixtures/players', mission=True)


def test_frozen_phase_a_and_crash_resume_never_calls_again():
    from scripts.run_mission029 import collect_once, targets_a
    targets = targets_a()
    assert len(targets) == 7228 and {r['season'] for r in targets} == set(range(2020, 2025))
    calls, store = [], InMemoryObjectStore()
    def fail(**request):
        calls.append(request)
        raise RuntimeError('CRASH')
    collector = SimpleNamespace(_make_task=lambda **kw: object(),
        repository=SimpleNamespace(receipt_for=lambda task: None), _collect=fail)
    request = dict(season=2020, family='statistics', params=dict(fixture=1))
    with pytest.raises(RuntimeError, match='CRASH'):
        collect_once(collector, store, request)
    assert collect_once(collector, store, request) is None and len(calls) == 1
    with pytest.raises(ValueError, match='HOLDOUT'):
        collect_once(collector, store, dict(request, season=2025))


def test_status_cache_reuses_110_minutes_and_rejects_an_old_day():
    from robin.historical_deep.admission import PREFIX, Admission
    gate = Admission(InMemoryObjectStore(), lambda: NOW)
    body = dict(checked_at=(NOW - timedelta(minutes=109)).isoformat(),
        remaining=10000, baseline=0, status=dict(proof=True))
    gate.store.put_if_absent(f'{PREFIX}/proofs/{NOW.date()}/1', json.dumps(body).encode())
    assert gate.cached_status() == dict(proof=True)
    gate.clock = lambda: NOW + timedelta(minutes=2)
    assert gate.cached_status() is None


def test_entrypoint_archives_statistics_and_replays_without_http(monkeypatch, tmp_path):
    from robin.historical_deep.admission import Admission
    from scripts import run_mission029 as run
    now, store, urls = datetime.now(UTC), InMemoryObjectStore(), []
    gate = Admission(store)
    monkeypatch.setattr('robin.historical_deep.admission.workflow_budget', lambda: gate)
    monkeypatch.setattr(run, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(run, 'OUTPUT', tmp_path)
    for name in ('STORAGE_PAUSED', 'P3_P4_PAUSED', 'PRODUCTION_LOCKED', 'NO_BET_DEFAULT',
                 'PROMOTION_LOCKED', 'WORKFLOW71_ADMISSION', 'GITHUB_ACTIONS'):
        monkeypatch.setenv(name, 'true')
    for name in ('REAL_BETS', 'SOCIAL_PUBLISHING_ENABLED', 'DEMO_MODE_ENABLED',
                 'POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES', 'THE_ODDS_API_HISTORICAL_CREDITS'):
        monkeypatch.setenv(name, 'false')
    monkeypatch.setenv('API_FOOTBALL_KEY', 'synthetic')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    def get(url, **kwargs):
        urls.append(url)
        records = [dict(team=dict(id=i), statistics=[dict(type='Shots', value=0)]) for i in (1, 2)]
        if url.endswith('/status'):
            records = dict(subscription=dict(plan='Mega', active=True,
                end=(now + timedelta(days=30)).isoformat()), requests=dict(limit_day=150000, current=0))
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(response=records))
    monkeypatch.setattr('requests.get', get)
    targets = [dict(code='E0', league=39, season=2020, fixture=1)]
    payload_reads, original = [], run.R2FirstRepository.payload_for
    def observe(*args, **kwargs):
        payload_reads.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(run.R2FirstRepository, 'payload_for', observe)
    for attempt in range(2):
        if attempt:
            payload_reads.clear()
        assert run.run_phase('A', targets, ['statistics']) == 0
    assert payload_reads == []
    assert len(urls) == 2
    receipt = json.loads((tmp_path / 'A-public-receipt.json').read_bytes())
    assert receipt['complete']['statistics'] == 1 and receipt['calls'] == 0
    assert len(list(tmp_path.rglob('*.parquet'))) == 1
    assert json.loads(store.get_object(f'{run.PREFIX}/terminal/A'))['complete']['statistics'] == 1
    assert json.loads(store.get_object(f'{run.PREFIX}/terminal/A'))['calls'] == 2
