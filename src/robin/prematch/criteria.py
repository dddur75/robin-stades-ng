"""Pure calculations. No provider, database, storage client or network dependency."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

METRICS = (
    "tc_neutre10", "etat_score_buts10", "absents_cles", "force_xi", "cong21",
    "repos_jours", "cadre_suspendu", "cadre_suspendu_rouge", "cadre_suspendu_cumul",
    "points_tardifs5",
)


@dataclass(frozen=True)
class Fixture:
    fixture_id: int
    competition: str
    season: int
    kickoff: datetime
    home: int
    away: int
    home_goals: int | None
    away_goals: int | None
    status: str = "FT"
    home_name: str = ""
    away_name: str = ""

    def __post_init__(self) -> None:
        if self.season == 2025:
            raise ValueError("holdout season forbidden")
        if self.kickoff.tzinfo is None or self.kickoff.utcoffset() is None:
            raise ValueError("aware kickoff required")
        if self.home == self.away:
            raise ValueError("distinct teams required")
        if any(type(i) is not int for i in (self.fixture_id, self.home, self.away)):
            raise ValueError("integer fixture and team identities required")
        if any(g is not None and (type(g) is not int or g < 0)
               for g in (self.home_goals, self.away_goals)):
            raise ValueError("invalid regulation score")


@dataclass(frozen=True)
class PlayerStat:
    player_id: int
    minutes: int | None
    rating: float | None


def _points(a: int, b: int) -> int:
    return 3 if a > b else 1 if a == b else 0


def goal_state(
    fixture: Fixture, events: list[dict[str, Any]] | None, team: int,
) -> dict[str, float | int] | None:
    """Reconstruct official regulation score; stoppage events retain their ordering."""
    if events is None or fixture.home_goals is None or fixture.away_goals is None:
        return None
    if fixture.status not in {"FT", "AET", "PEN"}:
        return None
    goals = []
    for position, event in enumerate(events):
        if event.get("type") != "Goal" or event.get("detail") == "Missed Penalty":
            continue
        minute = event.get("time", {}).get("elapsed")
        extra = event.get("time", {}).get("extra") or 0
        scoring_team = event.get("team", {}).get("id")
        if (type(minute) is not int or not 0 <= minute <= 150 or
                type(extra) is not int or extra < 0 or
                scoring_team not in {fixture.home, fixture.away}):
            return None
        if minute <= 90:
            goals.append((minute, extra, position, scoring_team))
    home = away = at80_home = at80_away = 0
    last = 0
    minutes = 0.0
    scored = conceded = 0
    for minute, _extra, _position, scoring_team in sorted(goals):
        neutral = abs(home - away) <= 1
        if neutral:
            minutes += minute - last
            scored += scoring_team == team
            conceded += scoring_team != team
        home += scoring_team == fixture.home
        away += scoring_team == fixture.away
        if minute <= 80:
            at80_home, at80_away = home, away
        last = minute
    if (home, away) != (fixture.home_goals, fixture.away_goals):
        return None
    if abs(home - away) <= 1:
        minutes += 90 - last
    a, b, a80, b80 = ((home, away, at80_home, at80_away) if team == fixture.home else
                       (away, home, at80_away, at80_home))
    return {"minutes": minutes, "buts_pour": scored, "buts_contre": conceded,
            "points_tardifs": _points(a, b) - _points(a80, b80)}


class PrematchEngine:
    def __init__(
        self, fixtures: list[Fixture], players: dict[tuple[int, int], list[PlayerStat]],
        lineups: dict[tuple[int, int], tuple[int, ...]],
        events: dict[int, list[dict[str, Any]]],
        calendar_complete: dict[tuple[str, int], bool] | None = None,
    ) -> None:
        if any(f.season == 2025 for f in fixtures):
            raise ValueError("holdout season forbidden")
        if len({f.fixture_id for f in fixtures}) != len(fixtures):
            raise ValueError("duplicate fixture")
        self.players, self.lineups, self.events = players, lineups, events
        self.calendar_complete = calendar_complete
        self.history: dict[tuple[str, int], list[Fixture]] = defaultdict(list)
        for f in sorted(fixtures, key=lambda f: (f.kickoff, f.fixture_id)):
            if f.status in {"FT", "AET", "PEN"}:
                for team in (f.home, f.away):
                    self.history[f.competition, team].append(f)
        self.dates = {k: [f.kickoff for f in fs] for k, fs in self.history.items()}

    def team(self, target: Fixture, team: int) -> dict[str, Any]:
        if team not in {target.home, target.away}:
            raise ValueError("team outside fixture")
        values: dict[str, Any] = dict.fromkeys(METRICS)
        reasons = {k: "insufficient_history" for k in METRICS}
        reasons.update(tc_neutre10="timestamped_shots_unavailable",
                       cong21="all_competitions_calendar_unproven",
                       repos_jours="all_competitions_calendar_unproven",
                       cadre_suspendu_cumul="league_season_yellow_rule_undocumented")
        values.update(source_compo=None, history_count=0, cong21_observe=None,
                      repos_jours_observe=None, reasons=reasons)
        key = target.competition, team
        end = bisect_left(self.dates.get(key, []), target.kickoff - timedelta(hours=3))
        prior = self.history.get(key, [])[:end]
        values["history_count"] = len(prior)
        if prior:
            values["cong21_observe"] = sum(
                f.kickoff >= target.kickoff - timedelta(days=21) for f in prior)
            values["repos_jours_observe"] = (
                target.kickoff - prior[-1].kickoff).total_seconds() / 86400
        xi = self.lineups.get((target.fixture_id, team))
        if xi is not None and len(xi) == len(set(xi)) == 11:
            values["source_compo"] = "feuille_officielle"
        else:
            xi = None
        if self.calendar_complete is not None and not all(
            self.calendar_complete.get((target.competition, season), False)
            for season in {target.season, *(f.season for f in prior[-10:])}
        ):
            for metric in METRICS:
                if reasons[metric] == "insufficient_history":
                    reasons[metric] = "fixture_calendar_incomplete"
            return values

        for n, metric in ((10, "etat_score_buts10"), (5, "points_tardifs5")):
            if len(prior) < n:
                continue
            states = [goal_state(f, self.events.get(f.fixture_id), team) for f in prior[-n:]]
            if any(s is None for s in states):
                reasons[metric] = "goal_events_missing_or_inconsistent"
            elif metric == "points_tardifs5":
                values[metric] = sum(s["points_tardifs"] for s in states if s is not None)
            else:
                values[metric] = {k: sum(s[k] for s in states if s is not None)
                                  for k in ("minutes", "buts_pour", "buts_contre")}

        season_prior = [f for f in prior if f.season == target.season]
        season_stats = [self.players.get((f.fixture_id, team)) for f in season_prior]
        blocks_ok = bool(season_stats) and all(self._minutes_valid(b) for b in season_stats)
        if xi is None:
            reasons.update(absents_cles="official_lineup_missing_or_invalid",
                           force_xi="official_lineup_missing_or_invalid")
        elif not blocks_ok:
            reasons.update(absents_cles="season_player_minutes_incomplete",
                           force_xi="season_player_statistics_incomplete")
        else:
            minutes_by_player: dict[int, int] = defaultdict(int)
            ratings = []
            for block in season_stats:
                for p in block or []:
                    minutes_by_player[p.player_id] += p.minutes or 0
                    if p.rating is not None:
                        ratings.append(p.rating)
            top = sorted(minutes_by_player, key=lambda p: (-minutes_by_player[p], p))[:11]
            last5 = [self.players.get((f.fixture_id, team)) for f in prior[-5:]]
            if len(prior) >= 5 and len(top) == 11 and all(
                self._minutes_valid(b) for b in last5
            ):
                denominator = sum(p.minutes or 0 for b in last5 for p in b or []
                                  if p.player_id in top)
                numerator = sum(p.minutes or 0 for b in last5 for p in b or []
                                if p.player_id in top and p.player_id not in xi)
                if denominator:
                    values["absents_cles"] = numerator / denominator
            last10 = [self.players.get((f.fixture_id, team)) for f in prior[-10:]]
            if len(prior) >= 10 and all(self._minutes_valid(b) for b in last10):
                individual = {p: [s.rating for b in last10 for s in b or []
                                  if s.player_id == p and s.rating is not None] for p in xi}
                if ratings and all(individual.values()):
                    values["force_xi"] = mean(mean(rs) for rs in individual.values()) - mean(ratings)
                else:
                    reasons["force_xi"] = "starting_player_rating_missing"

        if len(prior) >= 10:
            blocks = [self.players.get((f.fixture_id, team)) for f in prior[-10:]]
            cards = self.events.get(prior[-1].fixture_id)
            if not all(self._minutes_valid(b) for b in blocks):
                reasons["cadre_suspendu_rouge"] = "last10_player_minutes_incomplete"
            elif not cards:
                reasons["cadre_suspendu_rouge"] = "card_events_missing_or_empty"
            elif goal_state(prior[-1], cards, team) is None:
                reasons["cadre_suspendu_rouge"] = "card_match_events_inconsistent"
            elif any(e.get("type") == "Card" and e.get("detail") == "Red Card"
                     and (type(e.get("player", {}).get("id")) is not int or
                          e.get("team", {}).get("id") not in {prior[-1].home, prior[-1].away})
                     for e in cards):
                reasons["cadre_suspendu_rouge"] = "red_card_identity_unknown"
            else:
                totals: dict[int, int] = defaultdict(int)
                for b in blocks:
                    for p in b or []:
                        totals[p.player_id] += p.minutes or 0
                yellows = Counter(e.get("player", {}).get("id") for e in cards
                                  if e.get("type") == "Card" and e.get("detail") == "Yellow Card"
                                  and e.get("team", {}).get("id") == team)
                values["cadre_suspendu_rouge"] = any(
                    e.get("type") == "Card" and e.get("detail") == "Red Card"
                    and e.get("team", {}).get("id") == team
                    and yellows[e.get("player", {}).get("id")] < 2
                    and not any(term in (e.get("comments") or "").casefold()
                                for term in ("second yellow", "2nd yellow", "yellow red"))
                    and totals.get(e.get("player", {}).get("id"), 0) >= 600
                    for e in cards)
        if values["cadre_suspendu_rouge"] is True:
            values["cadre_suspendu"] = True
        else:
            reasons["cadre_suspendu"] = "yellow_accumulation_unknown"
        for metric in METRICS:
            if values[metric] is not None:
                reasons.pop(metric, None)
        return values

    @staticmethod
    def _minutes_valid(block: list[PlayerStat] | None) -> bool:
        return bool(block) and len({p.player_id for p in block or []}) == len(block or []) and all(
            type(p.minutes) is int and 0 <= p.minutes <= 150 for p in block or [])
