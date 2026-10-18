"""Per-match player statistics on exactly the events population."""
import json

from scripts import run_mission029 as base
from scripts.mission029_events import targets_b


def quality(family, call, row):
    teams = call.records
    try:
        if call.paging_total != 1 or len(teams) != 2 or len({t['team']['id'] for t in teams}) != 2:
            return False
        for team in teams:
            players = team['players']
            if not team['team']['id'] or len({p['player']['id'] for p in players}) != len(players):
                return False
            participants = []
            for player in players:
                stats = player['statistics'][0]
                if not player['player']['id'] or not all(isinstance(stats[k], dict)
                    for k in ('games', 'shots', 'passes', 'duels')):
                    return False
                if 'rating' not in stats['games'] or not all('total' in stats[k]
                    for k in ('shots', 'passes', 'duels')):
                    return False
                minutes = stats['games']['minutes']
                if minutes is not None:
                    if type(minutes) is not int or not 0 <= minutes <= 150:
                        return False
                    participants.append(minutes)
            if len(participants) < 11 or not any(participants):
                return False
        return True
    except (KeyError, TypeError, IndexError, AttributeError):
        return False


def main():
    rows = targets_b()
    binding = base.R2ObjectStore(base.os.environ).get_object(f'{base.PREFIX}/targets/B.json')
    if binding != json.dumps(rows, sort_keys=True).encode():
        raise ValueError('MISSION029_EVENTS_PLAYERS_BINDING')
    return base.run_phase('C', rows, ['players'], quality=quality, coverage=.85)
