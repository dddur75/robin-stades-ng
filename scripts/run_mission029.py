"""029: the existing collector, once per fixture/family, with immutable projections."""
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from robin.historical.normalization import normalize_records
from robin.historical.storage import PartitionedParquetStore
from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.provider import ApiFootballDeepClient, ProviderError
from robin.historical_deep.storage import R2FirstRepository
from scripts.run_mission027_lineups import LEAGUES, validate_targets
from scripts.run_mission028 import Transport
from scripts.run_mission028_details import complete

PREFIX = 'historical-deep-data/schema-v1/_control/mission-029'
OUTPUT = Path('artifacts/historical-deep/mission029')


def targets_a():
    groups = json.loads(Path('configs/execution/mission027-targets.json').read_text())['groups']
    validate_targets(groups)
    return [dict(code=g['competition'], league=LEAGUES[g['competition']],
        season=g['season'], fixture=i) for g in groups for i in g['fixture_ids']]


def collect_once(collector, store, request):
    if request['season'] == 2025:
        raise ValueError('MISSION029_HOLDOUT')
    task = collector._make_task(**request, identity=None)
    if collector.repository.receipt_for(task) is not None:
        return collector._collect(**request)
    getattr(getattr(collector, 'provider', None), 'assert_transport_available', lambda: None)()
    identity = request['params'].get('fixture') or hashlib.sha256(
        json.dumps(request['params'], sort_keys=True).encode()).hexdigest()
    marker = f"{PREFIX}/once/{request['family']}/{identity}.json"
    if not store.put_if_absent(marker, b'{"reserved":true}'):
        return None
    return collector._collect(**request)


def request_for(row, family):
    return dict(phase='mission029', competition=row['league'], season=row['season'], family=family,
        endpoint='/fixtures' if family == 'fixtures' else f'/fixtures/{family}',
        params=dict(league=row['league'], season=row['season']) if family == 'fixtures'
            else dict(fixture=row['fixture']))


def run_phase(phase, targets, families, *, clock=lambda: datetime.now(UTC), quality=None):
    if any(r['season'] == 2025 for r in targets):
        raise ValueError('MISSION029_HOLDOUT')
    digest = hashlib.sha256(json.dumps(targets, sort_keys=True).encode()).hexdigest()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    receipt = dict(phase=phase, status='PARTIAL', targets=len(targets), targets_sha256=digest,
        calls=0, complete={}, missing=[], uncertain=[], request_errors=[], partitions=[],
        run_id=os.environ.get('GITHUB_RUN_ID', 'local'), code_revision=os.environ.get('GITHUB_SHA'),
        observed_at=clock().isoformat(), total_cap=240000, daily_cap=130000, provider_reserve=5000)
    receipt['fixture_ids_sha256'] = hashlib.sha256(''.join(
        f'{i}\n' for i in sorted({r['fixture'] for r in targets})).encode()).hexdigest()
    store = transport = client = None
    try:
        assert_safety_locks(os.environ)
        if os.environ.get('WORKFLOW71_ADMISSION') != 'true' or os.environ.get('GITHUB_ACTIONS') != 'true':
            raise RuntimeError('MISSION029_ACTIONS_REQUIRED')
        os.environ['MISSION029_ACTIVE'] = 'true'
        store, now = R2ObjectStore(os.environ), clock()
        binding = json.dumps(targets, sort_keys=True).encode()
        key = f'{PREFIX}/targets/{phase}.json'
        if not (store.put_if_absent(key, binding) or store.get_object(key) == binding):
            raise ValueError('MISSION029_TARGETS_CHANGED')
        transport = Transport(now + timedelta(minutes=95))
        client = ApiFootballDeepClient(api_key=os.environ['API_FOOTBALL_KEY'],
            transport=transport, max_retries=0, status_ttl_seconds=7200)
        status = client.get_status()
        transport.deadline = min(transport.deadline, status.status_expires_at,
            now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        collector = HistoricalDeepCollector(client, R2FirstRepository(store),
            source_commit=os.environ['GITHUB_SHA'])
        parquet = PartitionedParquetStore(OUTPUT / 'historical/parquet')
        for row in targets:
            for family in families:
                if clock() >= transport.deadline:
                    raise RuntimeError('MISSION029_SLICE_ENDED')
                request = request_for(row, family)
                try:
                    call = collect_once(collector, store, request)
                except ProviderError as error:
                    receipt['request_errors'].append([row['fixture'], family, type(error).__name__])
                    call = None
                if call is None:
                    receipt['uncertain'].append([row['fixture'], family])
                    continue
                if call.paging_total != 1:
                    raise ValueError('MISSION029_PAGINATION')
                valid = quality(family, call, row) if quality else complete(family, call.records)
                receipt['complete'][family] = receipt['complete'].get(family, 0) + int(valid)
                if not valid:
                    receipt['missing'].append([row['fixture'], family])
                rows = normalize_records(request['endpoint'], call.records,
                    competition_id=row['league'], season=row['season'], ingestion_run_id='mission029',
                    raw_payload_hash=call.payload_sha256, request_params=request['params'],
                    observed_at=call.received_at)
                partition = parquet.write_records(rows, competition=row['code'], season=row['season'],
                    entity_type=family, dataset_version='api-football-v3')
                path = Path(partition['path']).rename(Path(partition['path']).with_name(
                    f"fixture-{row['fixture']}.parquet"))
                key = f"{PREFIX}/projection/{path.relative_to(OUTPUT.resolve()).as_posix()}"
                if not (store.put_if_absent(key, path.read_bytes()) or store.get_object(key) == path.read_bytes()):
                    raise ValueError('MISSION029_PROJECTION_CONFLICT')
                receipt['partitions'].append(dict(path=path.relative_to(OUTPUT.resolve()).as_posix(),
                    sha256=partition['sha256'], r2_key=key))
        receipt['status'] = 'EXHAUSTED'
    except Exception as error:
        receipt['reason_class'] = type(error).__name__
        if str(error).startswith(('W71_', 'MISSION029_', 'MISSION028_PREFLIGHT_')):
            receipt['reason_code'] = str(error)
    receipt['complete_fraction'] = {f: receipt['complete'].get(f, 0) / len(targets)
        if targets else 1 for f in families}
    receipt.update(calls=transport.calls if transport else 0,
        quota_remaining=client.quota.status.daily_remaining if client and client.quota else None)
    body = (json.dumps(receipt, indent=2) + '\n').encode()
    run = os.environ.get('GITHUB_RUN_ID', 'local') + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    (OUTPUT / f'{phase}-public-receipt.json').write_bytes(body)
    if store:
        if receipt['status'] == 'EXHAUSTED':
            store.put_if_absent(f'{PREFIX}/terminal/{phase}', body)
        store.put_if_absent(f'{PREFIX}/runs/{run}/{phase}-public-receipt.json', body)
    return 0 if receipt['status'] == 'EXHAUSTED' else 2


def main():
    targets = targets_a()
    phase = os.environ.get('MISSION029_PHASE', 'auto')
    if phase not in ('auto', 'A', 'B'):
        raise ValueError('MISSION029_PHASE_INVALID')
    store = R2ObjectStore(os.environ)
    if phase == 'B' and store.get_object(f'{PREFIX}/terminal/A') is None:
        raise ValueError('MISSION029_PREDECESSOR_REQUIRED')
    if phase == 'A' or (phase == 'auto' and store.get_object(f'{PREFIX}/terminal/A') is None):
        return run_phase('A', targets, ['statistics'])
    terminal = store.get_object(f'{PREFIX}/terminal/B')
    if terminal and phase == 'auto':
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'B-public-receipt.json').write_bytes(terminal)
        return 0
    from scripts.mission029_events import main as events
    return events()


if __name__ == '__main__':
    raise SystemExit(main())
