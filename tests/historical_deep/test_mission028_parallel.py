import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import InMemoryObjectStore
from scripts import run_mission028_details as run
from scripts.mission028_budget import RunBudget
from scripts.mission028_resume import checkpoint, choose

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


@pytest.mark.parametrize('remaining,used,reason', [(150000, 121073, 'TOTAL_BUDGET'), (5002, 1, 'RESERVE')])
def test_run_budget_is_shared_counts_old_calls_and_rebuilds_after_restart(tmp_path, remaining, used, reason):
    class Store(InMemoryObjectStore):
        listings = 0
        def iter_keys(self, prefix):
            self.listings += 1
            return (f'{run.PREFIX}/daily/{NOW.date()}/{i:06d}' for i in range(used))
    store = Store()
    budgets = [RunBudget(tmp_path / 'budget.db', 'run', store, NOW, remaining) for _ in range(64)]
    assert store.listings == 1
    budgets[0].take()
    with pytest.raises(RuntimeError, match=reason):
        budgets[-1].take()
    # A new runner reconstructs from the durable day reservations, never a fresh allowance.
    used += 1
    with pytest.raises(RuntimeError, match=reason):
        RunBudget(tmp_path / 'restart.db', 'next-run', store, NOW, remaining).take()


def test_sixty_four_lanes_keep_exact_day_cap():
    store = InMemoryObjectStore()
    lanes = [run.DaySlots(store, NOW, worker=i, stride=64) for i in range(64)]
    for i, lane in enumerate(lanes):
        for _ in range(len(range(i, 129750, 64))):
            lane.reserve(NOW, 5001)
        with pytest.raises(RuntimeError, match='DAILY_BUDGET'):
            lane.reserve(NOW, 5001)
    assert len(tuple(store.iter_keys(f'{run.PREFIX}/daily/{NOW.date()}/'))) == 129750


@pytest.mark.parametrize('error', ['ProviderTransportError', 'ProviderRateLimitError', 'ProviderResponseError'])
def test_missing_matches_never_pause_and_new_revision_ignores_old_pause(error):
    store = InMemoryObjectStore()
    store.put_if_absent(f'{run.PREFIX}/pause/old/worker.json', b'{}')
    checkpoint(store, dict(family='lineups', worker=0, reason_class=error), NOW, 'new')
    assert choose(store, NOW, 'old', 0) == ('PAUSED', 'none')
    assert choose(store, NOW, 'new', 0) == ('READY', 'lineups')


def setup_worker(monkeypatch, tmp_path):
    store, lock = InMemoryObjectStore(), Lock()
    for name in ('get_object', 'put_if_absent', 'iter_keys'):
        method = getattr(store, name)
        def synchronized(*args, method=method):
            with lock:
                return method(*args)
        monkeypatch.setattr(store, name, synchronized)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    for name, value in dict(datetime=Clock, OUTPUT=tmp_path, R2ObjectStore=lambda env: store,
            assert_safety_locks=lambda env: None,
            load_mapping=lambda: [dict(ligue_fd='ARG', season=2020, league_id=128, fixture_id=f) for f in range(10, 15)],
            QuotaController=lambda proof: QuotaController(proof, now=lambda: NOW, sleeper=lambda _: None, clock=lambda: 100.)).items():
        monkeypatch.setattr(run, name, value)
    monkeypatch.setattr(run.RateGate, 'acquire', lambda gate: None)
    for key, value in dict(MISSION028_WORKER='0', MISSION028_FAMILY='lineups', GITHUB_RUN_ID='test', GITHUB_SHA='new').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('API_FOOTBALL_KEY', str(tmp_path))
    proof = ProviderStatus(plan='Mega', active=True, daily_limit=150000, daily_used=0,
        daily_remaining=150000, checked_at=NOW, expires_at=NOW + timedelta(hours=2))
    (tmp_path / 'preflight.json').write_text(proof.model_dump_json())
    return store


@pytest.mark.parametrize('failure', ['timeout', 'network', '429', '503', 'invalid', 'recover'])
def test_four_inflight_retry_budget_continue_and_restart(monkeypatch, tmp_path, failure):
    store = setup_worker(monkeypatch, tmp_path)
    calls, waits, rendezvous = Counter(), [], Barrier(4, timeout=20)
    monkeypatch.setattr(run.time, 'sleep', waits.append)
    teams = [dict(team=dict(id=i), formation='4-3-3', startXI=[dict(player=dict(id=n))
             for n in range(1, 12)]) for i in (1, 2)]
    def get(url, **kwargs):
        fixture = kwargs['params']['fixture']
        calls[fixture] += 1
        if fixture < 14 and calls[fixture] == 1:
            rendezvous.wait()  # Four HTTP calls must be in flight; no elapsed-time assertion.
        status = 200
        if fixture == 10 and (failure != 'recover' or calls[fixture] < 4):
            if failure in ('timeout', 'network'):
                raise (run.requests.Timeout if failure == 'timeout' else run.requests.ConnectionError)('synthetic')
            status = 429 if failure == '429' else 503 if failure in ('503', 'recover') else 400
        return SimpleNamespace(status_code=status, headers={}, json=lambda: {'response': teams})
    monkeypatch.setattr(run.requests, 'get', get)
    assert run.main() == 0
    receipt = json.loads((tmp_path / 'worker-0-lineups-public-receipt.json').read_text())
    assert calls == Counter({10: 1 if failure == 'invalid' else 4, **dict.fromkeys(range(11, 15), 1)})
    assert waits == ([] if failure == 'invalid' else [1., 2., 4.])
    assert receipt['calls'] == sum(calls.values()) and receipt['distinct_matches_called'] == 5
    assert len(tuple(store.iter_keys(f'{run.PREFIX}/daily/'))) == receipt['calls']
    assert receipt['missing'] == ([] if failure == 'recover' else [10])
    assert len(receipt['request_errors']) == int(failure != 'recover')
    assert not tuple(store.iter_keys(f'{run.PREFIX}/pause/'))
    previous = calls.copy()
    monkeypatch.setenv('GITHUB_RUN_ID', 'restart')
    assert run.main() == 0 and calls == previous


@pytest.mark.parametrize('fatal', ['authentication', 'total', 'reserve', 'quota'])
def test_fatal_error_stops_queued_work_and_peers_before_extra_http(monkeypatch, tmp_path, fatal):
    store = setup_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(run, 'THREADS', 1)
    monkeypatch.setattr(run.time, 'sleep', lambda delay: None)
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs['params']['fixture'])
        return SimpleNamespace(status_code=401 if fatal == 'authentication' else 503, headers={})
    monkeypatch.setattr(run.requests, 'get', get)
    if fatal in ('total', 'reserve'):
        def budget(path, run_id, store, now, remaining):
            budget = RunBudget(path, run_id, store, now, remaining)
            with budget.connection:
                budget.connection.execute('UPDATE budget SET remaining=1, reason=?',
                    ('MISSION028_TOTAL_BUDGET_REACHED' if fatal == 'total' else 'MISSION028_RESERVE_REACHED',))
            return budget
        monkeypatch.setattr(run, 'RunBudget', budget)
    if fatal == 'quota':
        monkeypatch.setattr(run, 'QuotaController', lambda proof: QuotaController(proof,
            now=lambda: NOW, sleeper=lambda _: None, clock=lambda: 100., initial_mission_used=99999))
    assert run.main() == (2 if fatal == 'authentication' else 0)
    receipt = json.loads((tmp_path / 'worker-0-lineups-public-receipt.json').read_text())
    assert calls == [10] and receipt['calls'] == 1
    assert receipt.get('reason_code') != 'MISSION028_STOP_REQUESTED'  # Preserve the originating error.
    assert bool(tuple(store.iter_keys(f'{run.PREFIX}/pause/new/'))) == (fatal == 'authentication')
    with pytest.raises(RuntimeError, match='STOP_REQUESTED'):
        run.PacedTransport(NOW + timedelta(minutes=10)).check_deadline()


def test_later_fatal_future_is_not_masked_by_earlier_success(monkeypatch, tmp_path):
    from pathlib import Path
    setup_worker(monkeypatch, tmp_path)
    stopped, rendezvous, touch = Event(), Barrier(4, timeout=20), Path.touch
    def signal(path, *args, **kwargs):
        touch(path, *args, **kwargs)
        if path == run.halt_path():
            stopped.set()
    monkeypatch.setattr(Path, 'touch', signal)
    def get(url, **kwargs):
        fixture = kwargs['params']['fixture']
        assert fixture < 14
        rendezvous.wait()
        if fixture != 11:
            assert stopped.wait(20)
        return SimpleNamespace(status_code=401 if fixture == 11 else 200, headers={}, json=lambda: {'response': []})
    monkeypatch.setattr(run.requests, 'get', get)
    assert run.main() == 2
    receipt = json.loads((tmp_path / 'worker-0-lineups-public-receipt.json').read_text())
    assert receipt['reason_class'] == 'ProviderAuthenticationError'
