"""2015-2018 calendars, then four detail families according to actual availability."""
import json
from types import SimpleNamespace

from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.storage import R2FirstRepository
from scripts import run_mission029 as base
from scripts.mission029_events import quality as event_quality
from scripts.mission029_players import quality as player_quality

LEAGUES = dict(E0=('Premier-League', 39), D1=('Bundesliga', 78), I1=('Serie-A', 135),
    SP1=('La-Liga', 140), F1=('Ligue-1', 61))


def calendar_targets():
    return [dict(code=name, league=league, season=year, fixture=-league)
        for name, league in LEAGUES.values() for year in range(2015, 2019)]


def replay_calendars(store, calendars, *, allowed_seasons):
    if any(r['season'] == 2025 or r['season'] not in allowed_seasons
        or r['league'] not in {league for _, league in LEAGUES.values()} for r in calendars):
        raise ValueError('MISSION029_CALENDAR_REPLAY_SCOPE')
    def deny(*args, **kwargs):
        raise RuntimeError('MISSION029_OFFLINE_REPLAY_ONLY')
    repository = R2FirstRepository(store)
    reader = HistoricalDeepCollector(SimpleNamespace(get=deny), repository)
    selected, availability = {}, []
    for row in calendars:
        request = base.request_for(row, 'fixtures')
        task = reader._make_task(**request, identity=None)
        if repository.receipt_for(task) is None:
            availability.append(dict(league=row['league'], season=row['season'], availability='UNCONFIRMED'))
            continue
        call = reader._collect(**request)  # Receipt checked: never calls the provider.
        event_quality('fixtures', call, row)
        availability.append(dict(league=row['league'], season=row['season'],
            availability='CAPTURED' if call.records else 'PROVIDER_EMPTY', fixtures=len(call.records)))
        for record in call.records:
            if record['fixture']['status']['short'] not in ('FT', 'AET', 'PEN'):
                continue
            fixture = record['fixture']['id']
            goals = [record['goals']['home'], record['goals']['away']]
            target = dict(code=row['code'], league=row['league'], season=row['season'],
                fixture=fixture, goals=sum(goals) if all(type(g) is int for g in goals) else None,
                date=record['fixture'].get('date'))
            if fixture in selected and selected[fixture] != target:
                raise ValueError('MISSION029_CALENDAR_DUPLICATE_SCOPE')
            if type(fixture) is not int or fixture <= 0:
                raise ValueError('MISSION029_FIXTURE_ID_INVALID')
            selected[fixture] = target
    return sorted(selected.values(), key=lambda r: r['fixture']), availability


def quality(family, call, row):
    if family == 'events':
        return event_quality(family, call, row)
    if family == 'players':
        return player_quality(family, call, row)
    return base.complete(family, call.records)


def main():
    calendars = calendar_targets()
    store = base.R2ObjectStore(base.os.environ)
    if store.get_object(f'{base.PREFIX}/terminal/D-calendars') is None:
        result = base.run_phase('D-calendars', calendars, ['fixtures'], quality=event_quality)
        if result:
            return result
    rows, scopes = replay_calendars(store, calendars, allowed_seasons=set(range(2015, 2019)))
    body = json.dumps(dict(phase='D-availability', scopes=scopes, played_targets=len(rows),
        provider_calls=0, note='UNCONFIRMED is distinct from PROVIDER_EMPTY'), indent=2).encode()
    base.OUTPUT.mkdir(parents=True, exist_ok=True)
    (base.OUTPUT / 'D-availability-public-receipt.json').write_bytes(body)
    run = base.os.environ.get('GITHUB_RUN_ID', 'local') + '-' + base.os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    store.put_if_absent(f'{base.PREFIX}/runs/{run}/D-availability-public-receipt.json', body)
    return base.run_phase('D', rows, ['lineups', 'statistics', 'events', 'players'], quality=quality,
        coverage=dict(lineups=.95, statistics=.90, events=.90, players=.85))
