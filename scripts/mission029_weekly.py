"""Weekly 2026-27 statistics/events, driven by workflow 71's existing cron."""
import json
from datetime import UTC, date, datetime, timedelta

from robin.historical_deep.admission import PREFIX as BUDGET
from scripts import run_mission029 as base
from scripts.mission029_extension import LEAGUES, quality, replay_calendars


def completed_week(now):
    if now.tzinfo is None:
        raise ValueError('MISSION029_WEEK_TIMEZONE_REQUIRED')
    today = now.astimezone(UTC).date()
    end = today - timedelta(days=today.weekday() + 1)
    return end - timedelta(days=6), end


def calendar_targets(start, end):
    return [dict(code=name, league=league, season=2026, fixture=-league,
        query={'from': start.isoformat(), 'to': end.isoformat()}) for name, league in LEAGUES.values()]


def select_week(rows, start, end):
    if any(r['season'] != 2026 for r in rows):
        raise ValueError('MISSION029_WEEK_HOLDOUT')
    selected = []
    for row in rows:
        kickoff = datetime.fromisoformat(row['date'].replace('Z', '+00:00'))
        if kickoff.tzinfo is None:
            raise ValueError('MISSION029_KICKOFF_TIMEZONE_REQUIRED')
        if start <= kickoff.astimezone(UTC).date() <= end:
            selected.append(row)
    return selected


def summarize(store, start, end, details, scopes, finalized):
    calls = len(tuple(store.iter_keys(f'{BUDGET}/weeks/{start}/')))
    coverage = bool(finalized and details.get('targets') and details.get('coverage_met')
        and len(scopes) == 5 and all(s['availability'] != 'UNCONFIRMED' for s in scopes))
    prior = store.get_object(f'{base.PREFIX}/weekly/{start - timedelta(days=7)}.json')
    previous = json.loads(prior) if prior else {}
    ready = coverage and calls < 150 and previous.get('season') == 2026 and (
        previous.get('coverage_met') and previous.get('finalized') and previous.get('targets', 0) > 0
        and previous.get('calls', 150) < 150)
    return dict(phase='E', season=2026, week_start=str(start), week_end=str(end),
        calls=calls, call_count_basis='durable_reservations_including_uncertain_attempts',
        targets=details.get('targets', 0), complete=details.get('complete', {}),
        fixture_ids_sha256=details.get('fixture_ids_sha256'), quota_remaining=details.get('quota_remaining'),
        calendar_scopes=scopes, coverage_met=coverage, finalized=bool(finalized),
        under_150_calls=calls < 150, two_consecutive_ready=bool(ready))


def main(now=None):
    start, end = completed_week(now or datetime.now(UTC))
    base.OUTPUT.mkdir(parents=True, exist_ok=True)
    if end < date(2026, 7, 1) or start > date(2027, 6, 30):
        (base.OUTPUT / 'weekly-idle-public-receipt.json').write_text(json.dumps(
            dict(phase='E', status='OUTSIDE_2026_SEASON', calls=0)))
        return 0
    if base.os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('MISSION029_ACTIONS_REQUIRED')
    base.os.environ['MISSION029_WEEK'] = str(start)
    store = base.R2ObjectStore(base.os.environ)
    final_key = f'{base.PREFIX}/weekly/{start}.json'
    output = base.OUTPUT / f'weekly-{start}-public-receipt.json'
    previous = store.get_object(final_key)
    if previous is not None:
        output.write_bytes(previous)
        return 0  # Subsequent cron ticks perform no provider call.
    phase, calendars = f'E-{start}', calendar_targets(start, end)
    result = 0
    if store.get_object(f'{base.PREFIX}/terminal/{phase}-calendars') is None:
        from scripts.mission029_events import quality as calendar_quality
        result = base.run_phase(phase+'-calendars', calendars, ['fixtures'], quality=calendar_quality)
    rows, scopes = replay_calendars(store, calendars, allowed_seasons={2026})
    if not result:
        result = base.run_phase(phase, select_week(rows, start, end), ['statistics', 'events'], quality=quality)
    path = base.OUTPUT / f'{phase}-public-receipt.json'
    details = json.loads(path.read_bytes()) if path.exists() else {}
    finalized = store.get_object(f'{base.PREFIX}/terminal/{phase}') is not None
    receipt = summarize(store, start, end, details, scopes, finalized)
    body = (json.dumps(receipt, indent=2) + '\n').encode()
    output.write_bytes(body)
    run = base.os.environ.get('GITHUB_RUN_ID', 'local') + '-' + base.os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    store.put_if_absent(f'{base.PREFIX}/runs/{run}/weekly-{start}-public-receipt.json', body)
    if finalized:
        store.put_if_absent(final_key, body)
    return result
