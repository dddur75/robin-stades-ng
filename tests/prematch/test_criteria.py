from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from robin.prematch.criteria import Fixture, PlayerStat, PrematchEngine, goal_state

START = datetime(2020, 1, 1, 12, tzinfo=UTC)


def fixture(i, **kwargs):
    return Fixture(i, "TEST", 2020, START + timedelta(days=i * 4), 1, 2, 0, 0, **kwargs)


def event(minute, team=1, kind="Goal", detail="Normal Goal", player=1, extra=None):
    return {"time": {"elapsed": minute, "extra": extra}, "team": {"id": team},
            "player": {"id": player}, "type": kind, "detail": detail}


def pack(n=12):
    fixtures = [fixture(i) for i in range(n)]
    players = {(f.fixture_id, t): [PlayerStat(p, 90, 7.0) for p in range(1, 12)]
               for f in fixtures for t in (1, 2)}
    lineups = {(f.fixture_id, t): tuple(range(1, 12)) for f in fixtures for t in (1, 2)}
    events = {f.fixture_id: [event(40, kind="Card", detail="Yellow Card", player=99)]
              for f in fixtures}
    return fixtures, players, lineups, events


def engine(data):
    fixtures, players, lineups, events = data
    return PrematchEngine(fixtures, players, lineups, events)


def test_goal_state_uses_pre_goal_score_and_excludes_missed_penalty():
    f = replace(fixture(1), home_goals=3, away_goals=1)
    goals = [event(10), event(20), event(30), event(85, 2),
             event(90, detail="Missed Penalty")]
    state = goal_state(f, goals, 1)
    assert state == {"minutes": 20.0, "buts_pour": 2, "buts_contre": 0,
                     "points_tardifs": 0}


def test_goal_at_80_counts_in_score80_but_stoppage_goal_changes_points():
    f = replace(fixture(1), home_goals=1, away_goals=1)
    state = goal_state(f, [event(80), event(90, 2, extra=4)], 1)
    assert state["points_tardifs"] == -2
    assert state["minutes"] == 90
    assert state["buts_contre"] == 1


def test_goal_events_must_reconcile_with_official_score():
    assert goal_state(fixture(1), [event(10)], 1) is None
    assert goal_state(fixture(1), None, 1) is None
    assert goal_state(fixture(1), [], 1)["minutes"] == 90


def test_windows_require_ten_and_five_prior_matches_and_count_zero():
    data = pack()
    e = engine(data)
    assert e.team(data[0][4], 1)["points_tardifs5"] is None
    assert e.team(data[0][5], 1)["points_tardifs5"] == 0
    assert e.team(data[0][9], 1)["etat_score_buts10"] is None
    values = e.team(data[0][10], 1)
    assert values["etat_score_buts10"] == {"minutes": 900.0, "buts_pour": 0, "buts_contre": 0}
    assert values["tc_neutre10"] is None
    assert values["cong21"] is None
    assert values["repos_jours"] is None
    assert values["source_compo"] == "feuille_officielle"


def test_absent_share_and_xi_ratings_use_only_past_season():
    data = pack()
    data[2][(10, 1)] = tuple(range(2, 13))
    for i in range(10):
        data[1][(i, 1)].append(PlayerStat(12, 1, 9.0))
    values = engine(data).team(data[0][10], 1)
    assert values["absents_cles"] == pytest.approx(1 / 11)
    assert values["force_xi"] == pytest.approx((10 * 7 + 9) / 11 - (11 * 7 + 9) / 12)


def test_future_and_target_postmatch_mutations_cannot_change_predictors():
    data = pack()
    target = data[0][10]
    baseline = engine(data).team(target, 1)
    for i in (10, 11):
        data[1][(i, 1)] = [PlayerStat(999, 99999, 1.0)]
        data[3][i] = [event(1)]
        data[0][i] = replace(data[0][i], home_goals=99)
    assert engine(data).team(target, 1) == baseline
    truncated = tuple([f for f in data[0] if f.kickoff < target.kickoff] if j == 0 else
                      {k: v for k, v in data[j].items() if
                       (k[0] if isinstance(k, tuple) else k) < 10 or
                       (j == 2 and k[0] == 10)} for j in range(4))
    assert engine(truncated).team(target, 1) == baseline


def test_simultaneous_and_unfinished_fixtures_are_excluded():
    data = pack()
    target = data[0][10]
    data[0][9] = replace(data[0][9], kickoff=target.kickoff - timedelta(hours=2))
    values = engine(data).team(target, 1)
    assert values["etat_score_buts10"] is None
    assert values["history_count"] == 9
    data[0][9] = replace(data[0][9], kickoff=target.kickoff)
    assert engine(data).team(target, 1)["history_count"] == 9


def test_missing_middle_match_is_not_skipped_to_fill_window():
    data = pack(13)
    del data[3][7]
    values = engine(data).team(data[0][12], 1)
    assert values["etat_score_buts10"] is None
    assert values["reasons"]["etat_score_buts10"] == "goal_events_missing_or_inconsistent"


def test_direct_red_proves_next_match_ban_for_core_player():
    data = pack()
    data[3][9] = [event(60, kind="Card", detail="Red Card")]
    e = engine(data)
    assert e.team(data[0][10], 1)["cadre_suspendu_rouge"] is True
    assert e.team(data[0][10], 1)["cadre_suspendu"] is True
    assert e.team(data[0][10], 1)["cadre_suspendu_cumul"] is None
    assert e.team(data[0][11], 1)["cadre_suspendu_rouge"] is False
    assert e.team(data[0][11], 1)["cadre_suspendu"] is None


def test_second_yellow_and_bench_red_do_not_invent_direct_red_ban():
    data = pack()
    data[3][9] = [event(60, kind="Card", detail="Second Yellow card"),
                  event(65, kind="Card", detail="Red Card", player=999)]
    assert engine(data).team(data[0][10], 1)["cadre_suspendu_rouge"] is False


def test_missing_player_block_does_not_become_zero_absences_or_rating():
    data = pack()
    del data[1][(3, 1)]
    values = engine(data).team(data[0][10], 1)
    assert values["absents_cles"] is None
    assert values["force_xi"] is None
    assert values["cadre_suspendu_rouge"] is None


def test_season_top_eleven_does_not_use_prior_season_minutes():
    data = pack(22)
    data[0][:11] = [replace(f, season=2019) for f in data[0][:11]]
    for i in range(11, 21):
        data[1][(i, 1)] = [PlayerStat(p, 90, 8) for p in range(2, 13)]
    data[2][(21, 1)] = tuple(range(2, 13))
    values = engine(data).team(data[0][21], 1)
    assert values["absents_cles"] == 0
    assert values["force_xi"] == 0


def test_holdout_rejected_before_calculation():
    with pytest.raises(ValueError, match="holdout"):
        PrematchEngine([replace(fixture(1), season=2025)], {}, {}, {})


def test_red_with_unknown_player_cannot_prove_negative_suspension():
    data = pack()
    data[3][9] = [event(60, kind="Card", detail="Red Card", player=None)]
    values = engine(data).team(data[0][10], 1)
    assert values["cadre_suspendu_rouge"] is None
    assert values["reasons"]["cadre_suspendu_rouge"] == "red_card_identity_unknown"


def test_red_after_second_yellow_is_not_a_direct_red():
    data = pack()
    data[3][9] = [event(30, kind="Card", detail="Yellow Card"),
                  event(60, kind="Card", detail="Yellow Card"),
                  event(60, kind="Card", detail="Red Card")]
    assert engine(data).team(data[0][10], 1)["cadre_suspendu_rouge"] is False


def test_core_player_threshold_is_inclusive_at_600_minutes():
    data = pack()
    for i in range(10):
        data[1][(i, 1)][0] = PlayerStat(1, 60, 7)
    data[3][9] = [event(60, kind="Card", detail="Red Card")]
    assert engine(data).team(data[0][10], 1)["cadre_suspendu"] is True
    data[1][(0, 1)][0] = PlayerStat(1, 59, 7)
    assert engine(data).team(data[0][10], 1)["cadre_suspendu_rouge"] is False
