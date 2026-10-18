import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from robin.historical_deep.admission import Admission
from robin.historical_deep.storage import InMemoryObjectStore
from scripts import run_mission029 as run

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@pytest.mark.parametrize('failure', [False, True])
def test_four_collectors_capture_independent_projections_and_never_retry(monkeypatch, tmp_path, failure):
    store, lock, calls, barrier = InMemoryObjectStore(), Lock(), Counter(), Barrier(4, timeout=3)
    for name in ('get_object', 'put_if_absent', 'iter_keys'):
        method = getattr(store, name)
        def synchronized(*a, method=method, name=name):
            with lock:
                result = method(*a)
                return tuple(result) if name == 'iter_keys' else result
        monkeypatch.setattr(store, name, synchronized)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    for module in ('scripts.run_mission028', 'robin.historical_deep.provider', 'robin.historical_deep.quota'):
        monkeypatch.setattr(module + '.datetime', Clock)
    gate = Admission(store, lambda: NOW)
    monkeypatch.setattr('robin.historical_deep.admission.workflow_budget', lambda: gate)
    monkeypatch.setattr(run, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(run, 'OUTPUT', tmp_path)
    monkeypatch.setattr(run, 'assert_safety_locks', lambda env: None)
    for key in ('WORKFLOW71_ADMISSION', 'GITHUB_ACTIONS'):
        monkeypatch.setenv(key, 'true')
    monkeypatch.setenv('API_FOOTBALL_KEY', 'synthetic')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    def get(url, **kw):
        if url.endswith('/status'):
            records = dict(subscription=dict(plan='Mega', active=True,
                end=(NOW + timedelta(days=30)).isoformat()), requests=dict(limit_day=150000, current=0))
        else:
            fixture = kw['params']['fixture']
            calls[fixture] += 1
            barrier.wait()
            if failure and fixture == 1:
                raise TimeoutError('synthetic')
            records = [dict(team=dict(id=i), statistics=[dict(type='Shots', value=fixture)]) for i in (1, 2)]
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(response=records))
    monkeypatch.setattr('requests.get', get)
    targets = [dict(code='E0', league=39, season=2020, fixture=i) for i in range(1, 5)]
    assert run.run_phase('A', targets, ['statistics'], clock=lambda: NOW) == 0
    receipt = json.loads((tmp_path / 'A-public-receipt.json').read_text())
    assert calls == Counter(dict.fromkeys(range(1, 5), 1))
    assert receipt['calls'] == 5 and receipt['complete']['statistics'] == 4 - failure
    assert len(receipt['uncertain']) == failure
    assert len(receipt['partitions']) == 4 - failure
    for partition in receipt['partitions']:
        import pyarrow.parquet as pq
        rows = pq.ParquetFile(tmp_path / partition['path']).read().to_pylist()
        assert len({row['provider_fixture_id'] for row in rows}) == 1
    assert run.run_phase('A', targets, ['statistics'], clock=lambda: NOW) == 0
    assert calls == Counter(dict.fromkeys(range(1, 5), 1))
    assert json.loads((tmp_path / 'A-public-receipt.json').read_text())['calls'] == 0


def rendezvous(item, barrier):
    import os
    from threading import get_ident
    index, tasks = item
    barrier.wait()
    return os.getpid(), get_ident(), index, tasks


def test_sixteen_processes_each_run_four_collectors():
    from functools import partial
    from multiprocessing import get_context

    from scripts.mission029_parallel import parallel
    barrier = get_context('spawn').Barrier(64, timeout=30)
    results = parallel(partial(rendezvous, barrier=barrier), list(range(128)))
    assert len(results) == 64
    assert len({r[0] for r in results}) == 16
    assert all(sum(r[0] == pid for r in results) == 4 for pid in {r[0] for r in results})
    assert len({(r[0], r[1]) for r in results}) == 64
    assert sorted(t for r in results for t in r[3]) == list(range(128))


def test_simulated_95_minute_slice_exceeds_250_calls_per_minute(monkeypatch, tmp_path, record_property):
    import heapq

    from scripts import mission028_performance as pace
    from scripts.mission029_parallel import PacedTransport
    ticks, starts = [0.], []
    monkeypatch.setattr(pace.time, 'monotonic', lambda: ticks[0])
    monkeypatch.setattr(pace.time, 'sleep', lambda delay: ticks.__setitem__(0, ticks[0] + delay))
    monkeypatch.setattr('requests.get', lambda *a, **kw: starts.append(ticks[0]))
    def clock():
        return NOW + timedelta(seconds=ticks[0])
    transports = [PacedTransport(NOW + timedelta(minutes=95), tmp_path / 'pace.db',
        clock, tmp_path / 'halt') for _ in range(64)]
    ready = [(0., i) for i in range(64)]
    try:
        while True:
            at, i = heapq.heappop(ready)
            ticks[0] = max(ticks[0], at)
            transports[i].get('synthetic')
            heapq.heappush(ready, (ticks[0] + 12., i))  # 12 seconds of concurrent HTTP/storage work.
    except RuntimeError as error:
        assert str(error) == 'MISSION029_SLICE_ENDED'
    record_property('synthetic_calls_per_minute', len(starts) / 95)
    assert len(starts) / 95 >= 250
    assert sum(t.calls for t in transports) == len(starts)
    assert all(b - a >= .126 - 1e-9 for a, b in zip(starts, starts[1:]))
    assert max(starts) < 95 * 60
    (tmp_path / 'halt').touch()
    ticks[0] = 0
    with pytest.raises(RuntimeError, match='STOP_REQUESTED'):
        transports[0].get('synthetic')


def test_holdout_is_rejected_before_any_store_access(monkeypatch):
    def deny(env):
        pytest.fail('holdout accessed storage')
    monkeypatch.setattr(run, 'R2ObjectStore', deny)
    with pytest.raises(ValueError, match='HOLDOUT'):
        run.run_phase('A', [dict(season=2025)], ['statistics'])
