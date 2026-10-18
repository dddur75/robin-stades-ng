import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.storage import InMemoryObjectStore


def test_completed_week_uses_utc_across_local_midnight_and_year_end():
    from scripts.mission029_weekly import completed_week
    assert tuple(map(str, completed_week(datetime.fromisoformat('2026-10-19T00:30:00+02:00')))) == (
        '2026-10-05', '2026-10-11')
    assert tuple(map(str, completed_week(datetime(2026, 10, 19, tzinfo=UTC)))) == (
        '2026-10-12', '2026-10-18')
    assert tuple(map(str, completed_week(datetime(2027, 1, 4, tzinfo=UTC)))) == (
        '2026-12-28', '2027-01-03')


def test_weekly_targets_have_five_leagues_only_2026_and_exact_dates():
    from scripts.mission029_weekly import calendar_targets, completed_week, select_week
    start, end = completed_week(datetime(2026, 10, 19, tzinfo=UTC))
    rows = calendar_targets(start, end)
    assert len(rows) == 5 and {r['season'] for r in rows} == {2026}
    assert all(r['query'] == {'from': '2026-10-12', 'to': '2026-10-18'} for r in rows)
    source = [dict(season=2026, fixture=i, date=day) for i, day in (
        (1, '2026-10-18T23:59:59+00:00'), (2, '2026-10-19T00:00:00+00:00'))]
    assert [r['fixture'] for r in select_week(source, start, end)] == [1]
    with pytest.raises(ValueError, match='HOLDOUT'):
        select_week([dict(source[0], season=2025)], start, end)


def test_week_counter_is_durable_and_does_not_replace_global_caps(monkeypatch):
    from robin.historical_deep.admission import PREFIX, Admission
    monkeypatch.setenv('MISSION029_WEEK', '2026-10-12')
    store = InMemoryObjectStore()
    for _ in range(2):
        Admission(store).reserve('/fixtures/events', mission=True, remaining=150000)
    assert len(list(store.iter_keys(f'{PREFIX}/weeks/2026-10-12/'))) == 2
    assert len(list(store.iter_keys(f'{PREFIX}/mission029/'))) == 2
    before = list(store.iter_keys(''))
    monkeypatch.setenv('MISSION029_WEEK', '2025-10-13')
    with pytest.raises(RuntimeError, match='SCOPE'):
        Admission(store).reserve('/fixtures/events', mission=True, remaining=150000)
    assert list(store.iter_keys('')) == before


def test_two_consecutive_receipts_require_coverage_and_149_150_boundary():
    from robin.historical_deep.admission import PREFIX as BUDGET
    from scripts.mission029_weekly import completed_week, summarize
    from scripts.run_mission029 import PREFIX
    store = InMemoryObjectStore()
    start, end = completed_week(datetime(2026, 10, 19, tzinfo=UTC))
    previous = dict(season=2026, coverage_met=True, calls=149, finalized=True, targets=1)
    store.put_if_absent(f'{PREFIX}/weekly/2026-10-05.json', json.dumps(previous).encode())
    for number in range(149):
        store.put_if_absent(f'{BUDGET}/weeks/{start}/{number:06d}', b'{}')
    details = dict(coverage_met=True, targets=1, complete={'statistics': 1, 'events': 1})
    scopes = [dict(availability='CAPTURED') for _ in range(5)]
    assert summarize(store, start, end, details, scopes, True)['two_consecutive_ready']
    store.put_if_absent(f'{BUDGET}/weeks/{start}/000149', b'{}')
    assert not summarize(store, start, end, details, scopes, True)['two_consecutive_ready']
    assert not summarize(store, start, end, dict(details, coverage_met=False), scopes, True)['coverage_met']
    assert not summarize(store, start, end, details, scopes, False)['finalized']


def test_weekly_entrypoint_replays_without_recalling_any_match(monkeypatch, tmp_path):
    from robin.historical_deep.admission import Admission
    from scripts import mission029_weekly as weekly
    from scripts import run_mission029 as base
    now, store, urls = datetime.now(UTC), InMemoryObjectStore(), []
    gate = Admission(store)
    monkeypatch.setattr('robin.historical_deep.admission.workflow_budget', lambda: gate)
    monkeypatch.setattr(base, 'R2ObjectStore', lambda env: store)
    monkeypatch.setattr(base, 'OUTPUT', tmp_path)
    for name in ('STORAGE_PAUSED', 'P3_P4_PAUSED', 'PRODUCTION_LOCKED', 'NO_BET_DEFAULT',
                 'PROMOTION_LOCKED', 'WORKFLOW71_ADMISSION', 'GITHUB_ACTIONS', 'MISSION029_ACTIVE'):
        monkeypatch.setenv(name, 'true')
    for name in ('REAL_BETS', 'SOCIAL_PUBLISHING_ENABLED', 'DEMO_MODE_ENABLED',
                 'POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES', 'THE_ODDS_API_HISTORICAL_CREDITS'):
        monkeypatch.setenv(name, 'false')
    monkeypatch.setenv('MISSION029_WEEK', '')
    monkeypatch.setenv('API_FOOTBALL_KEY', 'synthetic')
    monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    def get(url, **kwargs):
        urls.append(url)
        params = kwargs['params']
        if url.endswith('/status'):
            records = dict(subscription=dict(plan='Mega', active=True,
                end=(now + timedelta(days=30)).isoformat()), requests=dict(limit_day=150000, current=0))
        elif url.endswith('/fixtures'):
            assert params['season'] == 2026
            records = [dict(league=dict(id=params['league'], season=2026), goals=dict(home=1, away=0),
                fixture=dict(id=params['league'], status=dict(short='FT'), date=params['from']+'T12:00:00Z'))]
        elif url.endswith('/statistics'):
            records = [dict(team=dict(id=i), statistics=[dict(type='Shots', value=0)]) for i in (1, 2)]
        else:
            records = [dict(time=dict(elapsed=1), team=dict(id=1), player=dict(id=1), type='Goal')]
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(response=records))
    monkeypatch.setattr('requests.get', get)
    for _ in range(2):
        assert weekly.main(now=datetime(2026, 10, 19, tzinfo=UTC)) == 0
    assert len(urls) == 16  # Five calendars, ten detail calls, one /status in total.
    receipt = json.loads((tmp_path / 'weekly-2026-10-12-public-receipt.json').read_bytes())
    assert receipt['calls'] == 16 and receipt['coverage_met'] and receipt['targets'] == 5
    assert not receipt['two_consecutive_ready']
