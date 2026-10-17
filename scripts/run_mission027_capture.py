"""027: compositions 2026 only, durable reservations, canonical prospective storage."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import requests

from robin.historical_deep.adapters import R2ObjectStore
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import ApiFootballDeepClient
from robin.historical_deep.quota import QuotaController
from robin.prospective_observatory.r2 import ProspectiveR2Repository
from robin.prospective_observatory.temporal import schedule_windows
from robin.storage.database import build_engine

try:
    from scripts import run_prospective_observatory as base
except ModuleNotFoundError:
    import run_prospective_observatory as base

LEAGUES = {39: 'Premier League', 61: 'Ligue 1', 78: 'Bundesliga', 135: 'Serie A', 140: 'Liga'}
PREFIX = 'prospective-lineups/mission027/season=2026'
RECOVERY = 'prospective-deep-data-recovery/schema-v1/'
CAP = 60


class Transport:
    cutoff = None

    def get(self, url, **kwargs):
        if self.cutoff is not None and datetime.now(UTC) >= self.cutoff:
            raise RuntimeError('MISSION027_WINDOW_ENDED')
        timeout = kwargs.pop('timeout', 10)
        return requests.get(url, allow_redirects=False, timeout=timeout, **kwargs)


def reserve(store, now):
    day = now.astimezone(UTC).date().isoformat()
    for slot in range(CAP):
        if store.put_if_absent(f'{PREFIX}/daily/{day}/{slot:02d}', b'{}'):
            return f'{PREFIX}/daily/{day}/{slot:02d}'
    raise RuntimeError('MISSION027_DAILY_BUDGET_REACHED')


class SeasonStore:
    """Route new recovery intents through a season-scoped physical namespace."""
    def __init__(self, store):
        self.store = store

    def key(self, key):
        if key.startswith('prospective-deep-budget/prospective-provider-budget-v1/'):
            return key
        if key.startswith(RECOVERY):
            return key.replace(RECOVERY, f'{PREFIX}/recovery/', 1)
        allowed = [f'prospective-deep-data/schema-v1/competition={quote(c, safe="-_.~")}/season=2026/'
                   for c in LEAGUES.values()]
        if not any(key.startswith(p) for p in allowed):
            raise ValueError('MISSION027_STORAGE_SCOPE')
        return key

    def get_object(self, key):
        return self.store.get_object(self.key(key))

    def put_if_absent(self, key, body):
        return self.store.put_if_absent(self.key(key), body)

    def iter_keys(self, prefix):
        if prefix != RECOVERY:
            raise ValueError('MISSION027_STORAGE_SCOPE')
        return (k.replace(f'{PREFIX}/recovery/', RECOVERY, 1)
                for k in self.store.iter_keys(f'{PREFIX}/recovery/'))


def collect(store, state, client, *, clock=lambda: datetime.now(UTC), revision):
    repository = ProspectiveR2Repository(SeasonStore(store))
    repository.reconcile_pending_receipts()
    captures = [repository.read_capture(json.loads(repository.store.get_object(k))['receipt']['receipt_r2_key'])
                for k in repository.store.iter_keys(RECOVERY)]
    sink = base.SQLAlchemyProjectionSink(state) if isinstance(state, base.SQLAlchemyOperationalState) else state.projection_sink()
    if isinstance(sink, base.SQLAlchemyProjectionSink):
        sink.bootstrap(captures, tolerance=timedelta(hours=1))
    for saved in captures:
        if saved.receipt.family == base.CaptureFamily.FIXTURE:
            state.register_fixture(base.ProspectiveFixture.model_validate(saved.payload['fixture_contract']), saved)
        else:
            state.persist_capture(saved)
            projection = base._operational_replay_projection(saved.receipt, saved.payload)
            sink.insert_capture(saved.receipt, projection, base.canonical_sha256(projection))
    now = clock()

    def request(endpoint, params, cutoff=None):
        current = clock()
        if current.date() != now.date() or (cutoff is not None and current >= cutoff):
            raise RuntimeError('MISSION027_WINDOW_ENDED')
        if getattr(client, 'quota', None) is not None and client.quota.status.daily_remaining <= 5000:
            raise RuntimeError('MISSION027_RESERVE_REACHED')
        if isinstance(getattr(client, '_transport', None), Transport):
            client._transport.cutoff = min(cutoff or now + timedelta(days=1), now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        key = reserve(store, current)  # Failed transports and unresolved reservations stay spent.
        base._record_provider_units_before_call(state, repository, operation_key=key, step='request',
            provider=base.ProviderKind.API_FOOTBALL, units=1, recorded_at=current, code_revision=revision,
            provider_remaining=client.quota.status.daily_remaining if getattr(client, 'quota', None) else 0,
            provider_reserve=5000, budget_scope='MISSION027_LINEUPS_2026')
        return client.get(endpoint, params=params)

    def save(fixture, family, response, payload, window=None, calls=0):
        cutoff = window.cutoff_at if window else fixture.kickoff_at - timedelta(microseconds=1)
        complete = family == base.CaptureFamily.FIXTURE or base._capture_payload_complete(
            family=family, payload=payload, fixture=fixture)
        quality = base.AvailabilityStatus.CAPTURED if complete else base.AvailabilityStatus.INVALID_PAYLOAD
        if response.received_at >= cutoff:
            quality = base.AvailabilityStatus.TEMPORALITY_FAILED
        context = base.CaptureContext(fixture_id=fixture.fixture_id, competition=fixture.competition,
            season='2026', provider='api-football', family=family,
            requested_at=response.requested_at, response_received_at=response.received_at,
            observed_at=response.received_at, kickoff_at=fixture.kickoff_at, cutoff_at=cutoff,
            http_status=response.http_status, source_endpoint='/fixtures/lineups' if window else '/fixtures',
            complete=quality == base.AvailabilityStatus.CAPTURED, quality_status=quality, provider_calls=calls, code_revision=revision,
            materialized_at=max(clock(), response.received_at),
            window_id=window.window_id if window else None, window_label=window.label if window else 'REGISTRY')
        body = dict(raw_payload_kind='PROVIDER_RESPONSE_ENVELOPE', raw_provider_payload=response.payload,
                    normalized_family_records=payload)
        if window is None:
            body['fixture_contract'] = fixture.model_dump(mode='json')
        saved = repository.capture(context=context, payload=body)
        captures.append(saved)
        if window is None:
            state.register_fixture(fixture, saved)
        else:
            state.persist_capture(saved)
            projection = base._operational_replay_projection(saved.receipt, saved.payload)
            sink.insert_capture(saved.receipt, projection, base.canonical_sha256(projection))

    for league, competition in LEAGUES.items():
        key = f'{PREFIX}/calendars/{now.date()}/{league}'
        if not store.put_if_absent(key, b'{}'):
            continue
        result = request('/fixtures', dict(league=league, season=2026,
            **{'from': now.date().isoformat(), 'to': (now + timedelta(days=1)).date().isoformat()}))
        if any(r['league']['season'] != 2026 or r['league']['id'] != league for r in result.payload['response']):
            raise RuntimeError('MISSION027_CALENDAR_SCOPE')
        store.put_if_absent(f'{key}/response.json', json.dumps(dict(payload=result.payload, received_at=result.received_at.isoformat())).encode())
        for number, record in enumerate(result.payload['response']):
            fixture = base._prospective_fixture(record, competition=competition, registered_at=now,
                code_revision=revision, horizon_days=2, excluded_statuses={'CANC', 'PST', 'ABD'},
                require_verified_phase=True, require_reliable_utc_kickoff=True)
            if fixture is not None and not fixture.cancelled:
                save(fixture, base.CaptureFamily.FIXTURE, result, [record], calls=int(number == 0))
    due = []
    for fixture in state.fixtures():
        if fixture.season != '2026' or fixture.competition not in LEAGUES.values() or fixture.cancelled:
            continue
        windows = {f: schedule_windows(fixture, f, scheduled_at=now) for f in base.LINEUP_FAMILIES}
        state.schedule_windows_batch(w for group in windows.values() for w in group)
        for lineup, formation in zip(*windows.values(), strict=True):
            if lineup.opens_at <= now < lineup.cutoff_at:
                due.append((fixture, lineup, formation))
    try:
        for fixture, lineup, formation in sorted(due, key=lambda x: (x[1].label != 'NEAR_KICKOFF', x[0].kickoff_at)):
            if len(tuple(store.iter_keys(f'{PREFIX}/daily/{now.date()}/'))) > CAP - 2:
                break
            key = f'{PREFIX}/attempts/{lineup.window_id}'
            if not store.put_if_absent(key, b'{}'):
                continue  # Never retry an uncertain physical request.
            fresh = request('/fixtures', dict(id=int(fixture.provider_fixture_id)), lineup.cutoff_at)
            records = fresh.payload['response']
            if (len(records) != 1 or records[0]['league']['season'] != 2026
                or LEAGUES.get(records[0]['league']['id']) != fixture.competition or fresh.received_at >= lineup.cutoff_at):
                continue
            # Preserve existing kickoff/team/status identity checks.
            proxy = base.ProviderResult(provider='api-football', endpoint='/fixtures', records=tuple(records),
                observed_at=fresh.received_at, availability=base.DataAvailability.PRESENT,
                origin=base.DataOrigin.LIVE_SOURCE, http_status=fresh.http_status)
            if base._fixture_freshness_error(proxy, fixture):
                continue
            save(fixture, base.CaptureFamily.FIXTURE, fresh, records, calls=1)
            result = request('/fixtures/lineups', dict(fixture=int(fixture.provider_fixture_id)), lineup.cutoff_at)
            records = result.payload['response']
            save(fixture, base.CaptureFamily.LINEUP, result, records, lineup, 1)
            save(fixture, base.CaptureFamily.FORMATION, result,
                [dict(team=r.get('team'), formation=r.get('formation')) for r in records], formation)
    except RuntimeError as error:
        if str(error) not in ('MISSION027_DAILY_BUDGET_REACHED', 'MISSION027_WINDOW_ENDED'):
            raise
    formations = {(c.receipt.fixture_id, c.receipt.observed_at, c.receipt.window_label) for c in captures
        if c.receipt.family == base.CaptureFamily.FORMATION and c.receipt.quality_status == base.AvailabilityStatus.CAPTURED}
    completed = {r.fixture_id for r in (c.receipt for c in captures) if r.family == base.CaptureFamily.LINEUP
        and r.season == '2026' and r.quality_status == base.AvailabilityStatus.CAPTURED
        and r.response_received_at < r.kickoff_at and (r.fixture_id, r.observed_at, r.window_label) in formations}
    return dict(status='OBSERVED', captured_fixtures=len(completed), daily_cap=CAP, status_calls=0,
        captures=[dict(fixture_id=c.receipt.fixture_id, competition=c.receipt.competition,
            received_at=c.receipt.response_received_at.isoformat(), kickoff_at=c.receipt.kickoff_at.isoformat(),
            receipt_r2_key=c.receipt.receipt_r2_key) for c in captures
            if c.receipt.family == base.CaptureFamily.LINEUP and c.receipt.fixture_id in completed and c.receipt.quality_status == base.AvailabilityStatus.CAPTURED and c.receipt.response_received_at < c.receipt.kickoff_at],
        daily_reserved=len(tuple(store.iter_keys(f'{PREFIX}/daily/{now.date()}/'))),
        competitions=list(LEAGUES.values()), season=2026)


def main():
    args = base.build_parser().parse_args()
    policy = base.ObservatoryPolicy.load(args.policy)
    estimate = dict(daily_cap=CAP, season=2026, leagues=LEAGUES, policy_sha256=policy.sha256)
    path = args.output / 'lineup-capture-estimate.json'
    if args.estimate:
        base._write_json(path, estimate)
        return 0
    report = dict(status='PARTIAL', daily_cap=CAP, status_calls=0)
    try:
        if not args.execute or base._read_json(args.estimate_file) != json.loads(json.dumps(estimate)):
            raise ValueError('MISSION027_ESTIMATE_REQUIRED')
        store, now = R2ObjectStore(os.environ), datetime.now(UTC)
        proofs = [ProviderStatus.model_validate_json(store.get_object(k)) for k in
            store.iter_keys('historical-deep-data/schema-v1/_control/mission-028/preflight/')]
        fresh = [p for p in proofs if p.is_fresh(now) and p.checked_at.date() == now.date()
                 and timedelta(0) <= now - p.checked_at < timedelta(minutes=110)]
        if not fresh:
            raise RuntimeError('MISSION027_FRESH_QUOTA_PROOF_REQUIRED')
        quota = QuotaController(max(fresh, key=lambda p: p.checked_at))
        client = ApiFootballDeepClient(api_key=os.environ['API_FOOTBALL_KEY'], quota=quota, max_retries=0, transport=Transport())
        state = base.SQLAlchemyOperationalState(build_engine(os.environ['ROBIN_DATABASE_URL']),
            restore_scope=('2026', tuple(LEAGUES.values())))
        report = collect(store, state, client, revision=os.environ['GITHUB_SHA'])
        report['quota_remaining'] = quota.status.daily_remaining
        store.put_if_absent(f'{PREFIX}/runs/{os.environ["GITHUB_RUN_ID"]}.json', json.dumps(report).encode())
    except Exception as error:
        report['reason_code'] = str(error) if str(error).startswith('MISSION027_') else type(error).__name__
    base._write_json(args.output / 'lineup-capture-report.json', report)
    return 2 if report['status'] == 'PARTIAL' else 0


if __name__ == '__main__':
    raise SystemExit(main())
