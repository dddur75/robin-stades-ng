from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from robin.historical_deep.storage import InMemoryObjectStore
from scripts import run_mission027_capture as capture
from scripts import run_prospective_observatory as base

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)

def fixture_record(league=61, season=2026):
    return dict(fixture=dict(id=10, date=(NOW + timedelta(minutes=30)).isoformat(),
        status=dict(short="NS")), league=dict(id=league, season=season, round="Regular Season - 8"), teams=dict(home=dict(id=1), away=dict(id=2)))

def test_scoped_recovery_never_reads_legacy_or_other_seasons():
    class StrictStore(InMemoryObjectStore):
        def get_object(self, key):
            assert '2025' not in key and not key.startswith(capture.RECOVERY)
            return super().get_object(key)
    store = StrictStore()
    scoped = capture.SeasonStore(store)
    old = capture.RECOVERY + 'intent-' + 'a' * 64 + '.json'
    assert scoped.put_if_absent(old, b'{}')
    store.put_if_absent(capture.RECOVERY + 'intent-' + 'b' * 64 + '.json', b'forbidden')
    assert list(scoped.iter_keys(capture.RECOVERY)) == [old] and scoped.get_object(old) == b'{}'
    with pytest.raises(ValueError, match="SCOPE"):
        scoped.get_object('prospective-deep-data/schema-v1/competition=Ligue%201/season=2025/payload')

@pytest.mark.parametrize('formation,late,expected', [('4-3-3', False, 1), (None, False, 0), ('4-3-3', True, 0)])
def test_refresh_and_capture_replay_r2_before_sql_without_duplicate_calls(formation, late, expected):
    store, state, calls = InMemoryObjectStore(), base.MemoryOperationalState(), []
    teams = [dict(team=dict(id=i), formation=formation, startXI=[dict(player=dict(id=n)) for n in range(i * 20, i * 20 + 11)]) for i in (1, 2)]
    def get(endpoint, *, params):
        calls.append((endpoint, params))
        payload = teams if endpoint.endswith('lineups') else [fixture_record()] if params.get('league', 61) == 61 else []
        return SimpleNamespace(payload=dict(response=payload), requested_at=NOW, received_at=NOW + timedelta(hours=int(late and endpoint.endswith('lineups'))), http_status=200)
    client = SimpleNamespace(get=get)
    report = capture.collect(store, state, client, clock=lambda: NOW, revision='test')
    assert report['captured_fixtures'] == expected and report['daily_reserved'] == 7
    assert len(calls) == sum(e.units for e in state.budget_entries()) == sum(e.units for e in base.ProspectiveR2Repository(store).provider_budgets()) == 7  # calendars + freshness + lineup
    capture.collect(store, state, client, clock=lambda: NOW, revision='test')
    assert len(calls) == 7
    assert {r.family.value for r in state.receipts()} >= {'FIXTURE', 'LINEUP', 'FORMATION'}
    assert max(r.provider_calls for r in state.receipts()) <= 1
    assert all(r.season == '2026' and (not r.complete or r.response_received_at < r.kickoff_at) for r in state.receipts())

@pytest.mark.parametrize('mode', ['failure', 'late', 'stale'])
def test_failed_uncertain_or_late_capture_cannot_be_retried_or_counted(mode):
    store, state, calls = InMemoryObjectStore(), base.MemoryOperationalState(), []
    def get(endpoint, *, params):
        calls.append(endpoint)
        if 'id' in params and mode == 'failure':
            raise RuntimeError('synthetic failure')
        record = fixture_record(season=2025 if 'id' in params and mode == 'stale' else 2026)
        return SimpleNamespace(payload=dict(response=[record] if params.get('league', 61) == 61 else []), requested_at=NOW,
            received_at=NOW + timedelta(hours=1) if 'id' in params and mode == 'late' else NOW, http_status=200)
    client = SimpleNamespace(get=get)
    for _ in range(2):
        try:
            report = capture.collect(store, state, client, clock=lambda: NOW, revision='test')
            assert report['captured_fixtures'] == 0
        except RuntimeError:
            assert mode == 'failure'
    assert calls.count('/fixtures') == 6 and '/fixtures/lineups' not in calls

def test_scoped_sql_select_excludes_holdout_before_loading_rows():
    from sqlalchemy import Column, MetaData, String, Table, create_engine
    engine, metadata = create_engine('sqlite://'), MetaData()
    fixtures = Table('prospective_fixtures', metadata, *[ Column(name, String) for name in ('fixture_id', 'season', 'competition')])
    windows = Table('capture_windows', metadata, Column('fixture_id', String))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(fixtures.insert(), [dict(fixture_id='old', season='2025', competition='Ligue 1'),
            dict(fixture_id='ok', season='2026', competition='Ligue 1'), dict(fixture_id='other', season='2026', competition='Other')])
        connection.execute(windows.insert(), [dict(fixture_id=i) for i in ('old', 'ok', 'other')])
    state = object.__new__(base.SQLAlchemyOperationalState)
    state.tables, state.restore_scope = dict(prospective_fixtures=fixtures), ('2026', tuple(capture.LEAGUES.values()))
    with engine.connect() as connection:
        assert connection.execute(state._restore_select(windows)).scalars().all() == ['ok']

def test_calendar_requests_obey_60_61_boundary_rerun_and_utc_reset():
    store, calls = InMemoryObjectStore(), []
    for _ in range(59):
        capture.reserve(store, NOW)
    def get(endpoint, *, params):
        calls.append(endpoint)
        return SimpleNamespace(payload=dict(response=[]), received_at=NOW)
    with pytest.raises(RuntimeError, match='DAILY_BUDGET'):
        capture.collect(store, base.MemoryOperationalState(), SimpleNamespace(get=get), clock=lambda: NOW, revision='test')
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="DAILY_BUDGET"):
        capture.reserve(store, NOW.astimezone(__import__("datetime").timezone(timedelta(hours=14))))
    capture.reserve(store, NOW + timedelta(days=1))

def status_client(calls, *, fail=False, now=NOW):
    def get(url, **kwargs):
        calls.append(url)
        if fail:
            raise RuntimeError('uncertain status')
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(response=dict(
            subscription=dict(plan='Mega', active=True, end='2027-01-01'), requests=dict(limit_day=150000, current=0))))
    return capture.ApiFootballDeepClient(api_key='synthetic', transport=SimpleNamespace(get=get), now=lambda: now, max_retries=0, status_ttl_seconds=6600)

def test_status_24_allowed_25_refused_without_provider_and_utc_reset():
    store, calls = InMemoryObjectStore(), []
    for n in range(23):
        with pytest.raises(RuntimeError, match='TRANSPORT_FAILED'):
            capture.quota_proof(store, status_client(calls, fail=True), NOW, str(n))
        with pytest.raises(RuntimeError, match='STATUS_RUN'):
            capture.quota_proof(store, status_client(calls), NOW, str(n))
        assert len(calls) == n + 1
    capture.quota_proof(store, status_client(calls), NOW, '24')
    assert len(calls) == len(tuple(store.iter_keys(f'{capture.PREFIX}/status-slots/2026-10-17/'))) == 24
    with pytest.raises(RuntimeError, match='BUDGET'):
        capture.quota_proof(store, status_client(calls), NOW + timedelta(minutes=110), '25')
    assert len(calls) == 24
    tomorrow = NOW + timedelta(days=1)
    capture.quota_proof(store, status_client(calls, now=tomorrow), tomorrow, 'next-day')
    assert len(calls) == 25 and not tuple(store.iter_keys(f'{capture.PREFIX}/daily/'))

@pytest.mark.parametrize('source', ['own', 'workflow71'])
def test_status_reused_until_110_minutes_and_once_per_run(source):
    store, calls = InMemoryObjectStore(), []
    proof = capture.quota_proof(store, status_client(calls), NOW, 'initial')
    if source == 'workflow71':
        store = InMemoryObjectStore()
        store.put_if_absent('historical-deep-data/schema-v1/_control/mission-028/preflight/proof.json', proof.model_dump_json().encode())
    for age, expected in [(timedelta(minutes=109, seconds=59), 1), (timedelta(minutes=110), 2)]:
        capture.quota_proof(store, status_client(calls, now=NOW + age), NOW + age, 'second')
        assert len(calls) == expected
    with pytest.raises(RuntimeError, match='STATUS_RUN'):
        capture.quota_proof(store, status_client(calls), NOW + timedelta(minutes=220), 'second')
    assert len(calls) == 2
