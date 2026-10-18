from types import SimpleNamespace

import pytest

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository
from scripts.run_mission029 import collect_once, request_for


def test_extension_has_exactly_twenty_calendars_2015_to_2018():
    from scripts.mission029_extension import calendar_targets
    rows = calendar_targets()
    assert len(rows) == 20
    assert {(r['league'], r['season']) for r in rows} == {
        (league, year) for league in (39, 78, 135, 140, 61) for year in range(2015, 2019)}


def test_calendar_replay_is_offline_and_reports_unavailable_scopes():
    from scripts.mission029_extension import replay_calendars
    store = InMemoryObjectStore()
    row = dict(code='Premier-League', league=39, season=2015, fixture=-39)
    missing = dict(code='Ligue-1', league=61, season=2018, fixture=-61)
    empty = dict(code='Serie-A', league=135, season=2015, fixture=-135)
    played = dict(fixture=dict(id=1, status=dict(short='FT'), date='2015-08-01'),
        league=dict(id=39, season=2015), goals=dict(home=0, away=0))
    scheduled = dict(played, fixture=dict(id=2, status=dict(short='NS'), date='2015-08-02'))
    calls = []
    def get(endpoint, params):
        calls.append(params)
        return dict(response=[played, scheduled] if params['league'] == 39 else [])
    collector = HistoricalDeepCollector(SimpleNamespace(get=get), R2FirstRepository(store))
    for target in (row, empty):
        collect_once(collector, store, request_for(target, 'fixtures'))
    for _ in range(2):
        selected, availability = replay_calendars(store, [row, missing, empty], allowed_seasons=set(range(2015, 2019)))
        assert [r['fixture'] for r in selected] == [1] and selected[0]['goals'] == 0
        assert [r['availability'] for r in availability] == ['CAPTURED', 'UNCONFIRMED', 'PROVIDER_EMPTY']
    assert len(calls) == 2
    with pytest.raises(ValueError, match='SCOPE'):
        replay_calendars(store, [dict(row, season=2025)], allowed_seasons={2025})


def test_extension_collects_all_four_families_and_keeps_nulls(monkeypatch, tmp_path):
    from scripts import mission029_extension as ext
    from scripts import run_mission029 as base
    rows = [dict(code='Premier-League', league=39, season=2015, fixture=1, goals=0)]
    store = InMemoryObjectStore()
    monkeypatch.setattr(base, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(base, 'OUTPUT', tmp_path)
    monkeypatch.setattr(ext, 'replay_calendars', lambda *a, **kw: (rows, []))
    observed = []
    monkeypatch.setattr(base, 'run_phase', lambda *a, **kw: observed.append(a) or 0)
    assert ext.main() == 0
    assert observed[0][0] == 'D-calendars'
    assert observed[1] == ('D', rows, ['lineups', 'statistics', 'events', 'players'])
    assert list(tmp_path.glob('D-availability-public-receipt.json'))


def test_calendar_partitions_do_not_collide_for_distinct_queries():
    from scripts.run_mission029 import projection_name
    row = dict(code='Ligue-1', league=61, season=2026, fixture=-61)
    left = request_for(dict(row, query={'from': '2026-10-05', 'to': '2026-10-11'}), 'fixtures')
    right = request_for(dict(row, query={'from': '2026-10-12', 'to': '2026-10-18'}), 'fixtures')
    assert left['params']['from'] == '2026-10-05'
    assert projection_name(left) != projection_name(right)


def test_restarting_extension_does_not_recall_any_of_the_four_families():
    store, calls = InMemoryObjectStore(), []
    def get(endpoint, params):
        calls.append((endpoint, params))
        return dict(response=[])
    row = dict(code='Ligue-1', league=61, season=2018, fixture=123)
    for phase in ('B', 'D', 'D'):
        reader = HistoricalDeepCollector(SimpleNamespace(get=get), R2FirstRepository(store))
        for family in ('lineups', 'statistics', 'events', 'players'):
            collect_once(reader, store, dict(request_for(row, family), phase=phase))
    assert len(calls) == 4
    assert {endpoint for endpoint, _ in calls} == {
        '/fixtures/lineups', '/fixtures/statistics', '/fixtures/events', '/fixtures/players'}
