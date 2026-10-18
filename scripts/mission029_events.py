"""Frozen 028 + 027 + archived Ligue 1 population; full calendars and events."""
import hashlib
import json
from pathlib import Path

from scripts import run_mission029 as base
from scripts.run_mission028 import census_queries
from scripts.run_mission028_details import load_mapping

L1_SHA256 = '293bfe08dae7e6470392a544585c617b384cc5a437d3e9d66c8826369aa0cce9'
IDS_SHA256 = '0f652e40d430f4670436318858161d90fa8ebebe85cd3fcb6d6e77178f56833f'


def targets_b():
    raw = Path('configs/execution/mission029-l1-targets.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != L1_SHA256:
        raise ValueError('MISSION029_L1_HASH')
    rows = base.targets_a() + [dict(code=r['ligue_fd'], league=int(r['league_id']),
        season=int(r['season']), fixture=r['fixture_id'], goals=int(r['buts_dom']) + int(r['buts_ext']))
        for r in load_mapping()]
    rows += [dict(code='Ligue-1', league=61, season=g['season'], fixture=i, goals=h+a)
        for g in json.loads(raw)['groups'] for i, h, a in g['fixtures']]
    ids = sorted(r['fixture'] for r in rows)
    if len(ids) != len(set(ids)) or len(ids) != 70084 or any(
        r['season'] not in range(2018, 2025) for r in rows) or hashlib.sha256(
        ''.join(f'{i}\n' for i in ids).encode()).hexdigest() != IDS_SHA256:
        raise ValueError('MISSION029_POPULATION_CHANGED')
    return sorted(rows, key=lambda r: r['fixture'])


def calendar_targets():
    return [dict(code=c, league=league, season=y, fixture=-league) for c, league, y in census_queries()]


def quality(family, call, row):
    records = call.records
    if call.paging_total != 1:
        raise ValueError('MISSION029_PAGINATION')
    if family == 'fixtures':
        if any(r['league']['id'] != row['league'] or r['league']['season'] != row['season']
               for r in records):
            raise ValueError('MISSION029_CALENDAR_SCOPE')
        return bool(records)
    try:
        valid = bool(records) and all(type(r['time']['elapsed']) is int
            and 0 <= r['time']['elapsed'] <= 150 and r['team']['id']
            and r['type'].casefold() in ('goal', 'card', 'subst', 'var')
            and (r['type'].casefold() == 'var' or r['player']['id']) for r in records)
        goals = sum(r['type'] == 'Goal' and r.get('detail') != 'Missed Penalty' for r in records)
        return valid and (row.get('goals') is None or row['goals'] == goals)
    except (KeyError, TypeError, AttributeError):
        return False


def main():
    rows = targets_b()  # All inputs validated before R2 or provider access.
    if base.R2ObjectStore(base.os.environ).get_object(f'{base.PREFIX}/terminal/B-calendars') is None:
        result = base.run_phase('B-calendars', calendar_targets(), ['fixtures'], quality=quality)
        if result:
            return result
    return base.run_phase('B', rows, ['events'], quality=quality)
