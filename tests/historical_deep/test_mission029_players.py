import json
from types import SimpleNamespace

import pytest

from robin.historical_deep.storage import InMemoryObjectStore


def teams():
    return [dict(team=dict(id=team), players=[dict(player=dict(id=team*100+i),
        statistics=[dict(games=dict(minutes=90, rating='6.0'), shots=dict(total=0),
            passes=dict(total=0), duels=dict(total=0))]) for i in range(11)]) for team in (1, 2)]


def test_players_require_two_teams_eleven_participants_and_real_stat_blocks():
    from scripts.mission029_players import quality
    data = teams()
    call = SimpleNamespace(records=data, paging_total=1)
    assert quality('players', call, {})
    data[0]['players'][0]['statistics'][0]['games']['minutes'] = 0
    assert quality('players', call, {})
    data[0]['players'][0]['statistics'][0]['games']['minutes'] = None
    assert not quality('players', call, {})
    data = teams()
    data[1]['players'][0]['player']['id'] = data[1]['players'][1]['player']['id']
    assert not quality('players', SimpleNamespace(records=data, paging_total=1), {})
    data = teams()
    del data[1]['players'][0]['statistics'][0]['passes']
    assert not quality('players', SimpleNamespace(records=data, paging_total=1), {})


def test_players_use_the_exact_events_binding_before_any_call(monkeypatch):
    from scripts import mission029_players as players
    from scripts import run_mission029 as base
    store, rows = InMemoryObjectStore(), [dict(code='E0', league=39, season=2020, fixture=1)]
    monkeypatch.setattr(players, 'targets_b', lambda: rows)
    monkeypatch.setattr(base, 'R2ObjectStore', lambda env: store)
    observed = []
    monkeypatch.setattr(base, 'run_phase', lambda *a, **kw: observed.append(a) or 0)
    with pytest.raises(ValueError, match='BINDING'):
        players.main()
    assert observed == []
    store.put_if_absent(f'{base.PREFIX}/targets/B.json', json.dumps(rows, sort_keys=True).encode())
    assert players.main() == 0 and observed[0] == ('C', rows, ['players'])


def test_players_task_is_post_match_and_total_stop_does_not_consume_another_slot():
    from robin.historical_deep.admission import PREFIX, Admission
    from robin.historical_deep.collector import HistoricalDeepCollector
    from scripts.run_mission029 import request_for
    request = request_for(dict(league=39, season=2020, fixture=1), 'players')
    assert request['family'] == 'players' and request['endpoint'] == '/fixtures/players'
    task = HistoricalDeepCollector(object(), None)._make_task(**request, identity=None)
    assert str(task.temporal_class) == 'POST_MATCH_ONLY'
    store = InMemoryObjectStore()
    store.put_if_absent(f'{PREFIX}/mission029/239999', b'{}')
    before = list(store.iter_keys(''))
    with pytest.raises(RuntimeError, match='LIMIT'):
        Admission(store).reserve('/status', mission=True)
    assert list(store.iter_keys('')) == before
