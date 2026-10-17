import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
from scripts import run_mission028_details as run
from scripts.mission028_performance import MeasuredStore, Timings

NOW = datetime.now(UTC)
class Store(InMemoryObjectStore):
    def __init__(self):
        super().__init__()
        self.operations = Counter()
    def get_object(self, key):
        self.operations['get'] += 1
        return super().get_object(key)
    def iter_keys(self, prefix):
        self.operations['list'] += 1
        return super().iter_keys(prefix)
    def put_if_absent(self, key, body):
        self.operations['slot' if '/daily/' in key else 'put'] += 1
        return super().put_if_absent(key, body)


def test_timings_include_failed_calls_and_exact_total_and_median():
    ticks = iter([0., 1., 10., 13.])
    timings = Timings(clock=lambda: next(ticks))
    assert timings.call('provider_http', lambda: 7) == 7
    with pytest.raises(ValueError):
        timings.call('provider_http', lambda: int('bad'))
    assert timings.summary()['provider_http'] == dict(count=2, total_seconds=4., median_seconds=2.)


def test_worker_slots_partition_exact_daily_cap_and_one_put_per_call():
    store = Store()
    slots = [run.DaySlots(store, NOW, worker=w) for w in range(16)]
    for worker, slot in enumerate(slots):
        for _ in range(len(range(worker, 129750, 16))):
            slot.reserve(NOW, 5001)
        with pytest.raises(RuntimeError, match='DAILY_BUDGET'):
            slot.reserve(NOW, 150000)
    assert store.operations['slot'] == 129750
    assert len(tuple(store.iter_keys(f'{run.PREFIX}/daily/{NOW.date()}/'))) == 129750
    with pytest.raises(RuntimeError, match='RESERVE'):
        run.DaySlots(store, NOW + timedelta(days=1), worker=0).reserve(NOW + timedelta(days=1), 5000)


@pytest.mark.parametrize('fail', [None, 'payload-', 'receipt.json'])
def test_constant_storage_work_and_no_duplicate_after_capture_crash(fail):
    class Failing(Store):
        def put_if_absent(self, key, body):
            if fail and key.rsplit('/', 1)[-1].startswith(fail):
                raise RuntimeError('synthetic interruption')
            return super().put_if_absent(key, body)
    store, calls = Failing(), []
    provider = SimpleNamespace(get=lambda *a, **kw: calls.append(1) or {'response': []})
    request = dict(phase='mission028', competition=40, season=2020, family='lineups', endpoint='/fixtures/lineups', params=dict(fixture=10))
    for attempt in range(2):
        measured = MeasuredStore(store, Timings())
        collector = HistoricalDeepCollector(provider, R2FirstRepository(measured))
        slots = run.DaySlots(measured, NOW, worker=15)
        before = store.operations.copy()
        try:
            run.once(collector, measured, slots, request, NOW, 150000)
        except RuntimeError:
            assert attempt == 0
        if attempt == 0 and fail is None:
            counts = store.operations - before
            assert counts == Counter(get=7, put=10, slot=1, list=1)
        fail = None
    assert len(calls) == 1
    request.update(family='statistics', endpoint='/fixtures/statistics')
    for _ in range(2):
        run.once(collector, measured, slots, request, NOW, 150000)
    assert len(calls) == 2  # Same match, independent family, each called once.


def test_sixteen_workers_sustain_six_to_eight_calls_per_second(tmp_path, monkeypatch):
    starts = []
    def get(*a, **kw):
        starts.append(time.monotonic())
        time.sleep(.05)
        return SimpleNamespace(json=lambda: {'response': []})
    monkeypatch.setattr(run.requests, 'get', get)
    class LatencyStore(Store):
        def get_object(self, key):
            time.sleep(.1)
            return super().get_object(key)
        def put_if_absent(self, key, body):
            time.sleep(.1)
            return super().put_if_absent(key, body)
        def iter_keys(self, prefix):
            time.sleep(.1)
            return super().iter_keys(prefix)
    def worker(number):
        timings = Timings()
        transport = run.PacedTransport(datetime.now(UTC) + timedelta(minutes=1), tmp_path / 'pace.sqlite3', timings)
        store = MeasuredStore(LatencyStore(), timings)
        slots = run.DaySlots(store, NOW, worker=number)
        provider = SimpleNamespace(get=lambda endpoint, params: transport.get('https://example.invalid', params=params, timeout=10).json())
        collector = HistoricalDeepCollector(provider, R2FirstRepository(store))
        for index in range(3):
            request = dict(phase='mission028', competition=40, season=2020, family='lineups', endpoint='/fixtures/lineups', params=dict(fixture=number * 10 + index))
            run.once(collector, store, slots, request, NOW, 150000)
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(worker, range(16)))
    starts.sort()
    rate = (len(starts) - 1) / (starts[-1] - starts[0])
    print(f'Synthetic: 16 workers, R2=100ms/op, HTTP=50ms, sustained={rate:.3f}/s')
    assert 6 <= rate <= 8
    assert all(sum(0 <= other - start < 1 for other in starts) <= 8 for start in starts)


@pytest.mark.parametrize('mode', ['deadline', 'error', 'error_after_deadline', 'response_error'])
def test_worker_deadline_is_partial_success_but_real_errors_fail(monkeypatch, tmp_path, mode):
    from robin.historical_deep.contracts import ProviderStatus
    wall, store = [NOW], InMemoryObjectStore()
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall[0]
    monkeypatch.setattr(run, 'datetime', Clock)
    monkeypatch.setattr(run, 'OUTPUT', tmp_path)
    monkeypatch.setattr(run, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(run, 'assert_safety_locks', lambda env: None)
    monkeypatch.setattr(run, 'load_mapping', lambda: [dict(ligue_fd='ARG', season=2020, league_id=128, fixture_id=10)])
    for key, value in dict(MISSION028_WORKER='0', MISSION028_FAMILY='lineups', GITHUB_RUN_ID='synthetic', GITHUB_SHA='test').items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv('API_FOOTBALL_KEY', str(tmp_path))
    proof = ProviderStatus(plan='Mega', active=True, daily_limit=150000, daily_remaining=150000,
        daily_used=0, checked_at=NOW, expires_at=NOW + timedelta(minutes=110))
    (tmp_path / 'preflight.json').write_text(proof.model_dump_json())
    def acquire(gate):
        if mode == 'deadline':
            wall[0] = NOW + timedelta(minutes=95)
    monkeypatch.setattr(run.RateGate, 'acquire', acquire)
    def get(*a, **kw):
        assert mode != 'deadline'
        if mode == 'response_error':
            return SimpleNamespace(status_code=400, headers={})
        if mode == 'error_after_deadline':
            wall[0] = NOW + timedelta(minutes=95)
        raise RuntimeError('synthetic transport failure')
    monkeypatch.setattr(run.requests, 'get', get)
    result = run.main()
    import json
    receipt = json.loads((tmp_path / 'worker-0-lineups-public-receipt.json').read_text())
    assert receipt['status'] == 'PARTIAL'
    assert {'provider_http', 'day_slots_reserve', 'receipt_for', 'get_object', 'capture_r2', 'write_parquet'} <= receipt['timings'].keys()
    if mode == 'deadline':
        assert result == 0 and receipt['reason_code'] == 'MISSION028_TIME_SLICE_ENDED'
        assert receipt['calls'] == 0 and not tuple(store.iter_keys(f'{run.PREFIX}/terminal/'))
        assert not tuple(store.iter_keys(f'{run.PREFIX}/pause/'))
    else:
        assert result == 2 and receipt['reason_class'] == ('ProviderResponseError' if mode == 'response_error' else 'ProviderTransportError')
        assert tuple(store.iter_keys(f'{run.PREFIX}/pause/'))


@pytest.mark.parametrize('age,remaining,new_call', [(20, 100, 0), (94, 16, 1), (20, 90, 1), (10, 99, 1)])
def test_preflight_requires_full_slice_plus_margin(monkeypatch, tmp_path, age, remaining, new_call):
    import json

    from robin.historical_deep.contracts import ProviderStatus
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    store, calls = InMemoryObjectStore(), []
    manifest = tmp_path / 'mapping.json'
    manifest.write_bytes(b'synthetic mapping')
    def proof(checked, expiry):
        return ProviderStatus(plan='Mega', active=True, daily_limit=150000, daily_used=0,
            daily_remaining=150000, checked_at=checked, expires_at=expiry)
    old = proof(NOW - timedelta(minutes=age), NOW + timedelta(minutes=remaining))
    store.put_if_absent(f'{run.PREFIX}/preflight/old.json', old.model_dump_json().encode())
    def client(**kwargs):
        calls.append(kwargs['status_ttl_seconds'])
        return SimpleNamespace(get_status=lambda: proof(NOW, NOW + timedelta(seconds=kwargs['status_ttl_seconds'])))
    for name, value in dict(datetime=Clock, OUTPUT=tmp_path, MANIFEST=manifest, load_mapping=lambda: [],
            R2ObjectStore=lambda env: store, assert_safety_locks=lambda env: None, ApiFootballDeepClient=client).items():
        monkeypatch.setattr(run, name, value)
    monkeypatch.setenv('GITHUB_RUN_ID', 'synthetic')
    monkeypatch.setenv('API_FOOTBALL_KEY', str(tmp_path))
    assert run.preflight() == 0
    assert calls == ([7200] if new_call else [])
    receipt = json.loads((tmp_path / 'preflight-public-receipt.json').read_text())
    assert receipt['status_calls'] == new_call
    assert len(tuple(store.iter_keys(f'{run.PREFIX}/status-slots/'))) == new_call
