import hashlib
import subprocess

import pytest

from robin.historical_deep.storage import InMemoryObjectStore


def test_common_population_is_exact_unique_and_holdout_free():
    from scripts.mission029_events import IDS_SHA256, targets_b
    rows = targets_b()
    assert len(rows) == len({r['fixture'] for r in rows}) == 70084
    assert hashlib.sha256(''.join(f"{i}\n" for i in sorted(
        r['fixture'] for r in rows)).encode()).hexdigest() == IDS_SHA256
    assert {r['season'] for r in rows} <= set(range(2018, 2025))
    assert sum(r['league'] == 61 for r in rows) == 2419


def test_events_need_minutes_identity_and_known_goal_total():
    from types import SimpleNamespace

    from scripts.mission029_events import quality
    def call(records):
        return SimpleNamespace(records=records, paging_total=1)
    row = dict(goals=1, league=61, season=2020)
    event = dict(time=dict(elapsed=90), team=dict(id=1), player=dict(id=2), type='Goal')
    assert quality('events', call([event]), row)
    assert not quality('events', call([]), dict(row, goals=0))
    assert not quality('events', call([event]), dict(row, goals=2))
    assert not quality('events', call([dict(event, time={})]), row)
    assert not quality('events', call([dict(event, player={})]), row)


def test_full_calendars_keep_all_fields_and_replay_without_request():
    from types import SimpleNamespace

    from robin.historical_deep.collector import HistoricalDeepCollector
    from robin.historical_deep.storage import R2FirstRepository
    from scripts.mission029_events import calendar_targets, quality
    from scripts.run_mission029 import collect_once, request_for
    targets = calendar_targets()
    assert len(targets) == 200 and {r['season'] for r in targets} == set(range(2019, 2025))
    row, store, calls = targets[0], InMemoryObjectStore(), []
    payload = dict(response=[dict(league=dict(id=row['league'], season=row['season']),
        fixture=dict(id=11, referee='Arbitre', venue=dict(name='Stade'), date='2019-08-01'))])
    def get(endpoint, params):
        calls.append(params)
        return payload
    for _ in range(2):
        collector = HistoricalDeepCollector(SimpleNamespace(get=get), R2FirstRepository(store))
        result = collect_once(collector, store, request_for(row, 'fixtures'))
        assert result.payload == payload and quality('fixtures', result, row)
    assert len(calls) == 1
    payload['response'][0]['league']['season'] = 2025
    with pytest.raises(ValueError, match='SCOPE'):
        quality('fixtures', SimpleNamespace(records=payload['response'], paging_total=1), row)


def test_git_publication_is_append_only_and_refuses_holdout(tmp_path, monkeypatch):
    from scripts.publish_mission029 import append_tree
    for name in ('GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME'):
        monkeypatch.setenv(name, 'Synthetic')
    for name in ('GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.setenv(name, 'synthetic@example.invalid')
    subprocess.run(['git', 'init', '--bare', str(tmp_path)], check=True, capture_output=True)
    def git(*args, data=None):
        return subprocess.check_output(['git', '--git-dir', str(tmp_path), *args], input=data).strip()
    tree = git('mktree', data=b'')
    head = git('commit-tree', tree.decode(), data=b'Initial\n')
    git('update-ref', 'refs/heads/historical-data', head.decode())
    path = 'historical/parquet/competition=E0/season=2020/entity_type=statistics/part.parquet'
    assert append_tree(tmp_path, {path: b'synthetic parquet'})
    assert append_tree(tmp_path, {path: b'synthetic parquet'}) is None
    with pytest.raises(ValueError, match='CONFLICT'):
        append_tree(tmp_path, {path: b'changed'})
    with pytest.raises(ValueError, match='HOLDOUT'):
        append_tree(tmp_path, {path.replace('2020', '2025'): b'blocked'})
    assert git('show', 'historical-data:' + path) == b'synthetic parquet'


def test_concurrent_status_refresh_is_single_and_legacy_usage_counts():
    from datetime import UTC, datetime

    from robin.historical_deep.admission import OLD, PREFIX, Admission
    now, store = datetime.now(UTC), InMemoryObjectStore()
    store.put_if_absent(f'{OLD}/daily/{now.date()}/0', b'{}')
    left, right = Admission(store), Admission(store)
    left.reserve('/status', mission=False)
    with pytest.raises(RuntimeError, match='PENDING'):
        right.reserve('/status', mission=False)
    assert left.legacy == 1
    store.put_if_absent(f'{PREFIX}/daily/{now.date()}/129998', b'{}')
    gate = Admission(store)
    gate.proof = dict(remaining=150000, baseline=129999)
    with pytest.raises(RuntimeError, match='LIMIT'):
        gate.reserve('/fixtures/events', mission=False)


def test_direct_client_and_collector_refuse_holdout_before_any_io(monkeypatch):
    from types import SimpleNamespace

    from robin.historical_deep.collector import HistoricalDeepCollector
    from robin.historical_deep.provider import ApiFootballDeepClient
    monkeypatch.setenv('WORKFLOW71_ADMISSION', 'true')
    monkeypatch.setattr('robin.historical_deep.admission.workflow_budget', lambda: object())
    client = ApiFootballDeepClient(api_key='synthetic')
    with pytest.raises(ValueError, match='HOLDOUT'):
        client.get('/fixtures', params=dict(season='2025'))
    def deny(*args):
        raise AssertionError('Holdout repository accessed')
    collector = HistoricalDeepCollector(client, SimpleNamespace(receipt_for=deny))
    with pytest.raises(ValueError, match='HOLDOUT'):
        collector._collect(phase='test', competition=61, season=2025, family='events',
            endpoint='/fixtures/events', params=dict(fixture=1))
