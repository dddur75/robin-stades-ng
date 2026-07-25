"""Datasets canoniques API-Football strictement point-in-time."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from robin.historical.features import (
    assert_temporal_integrity,
    build_team_feature_rows,
    dataset_manifest,
)
from robin.historical.readiness import observation_dimensions
from robin.historical.storage import PartitionedParquetStore

ROLLING_TEAM_STATISTICS = {
    "shots": "Total Shots",
    "shots_on_goal": "Shots on Goal",
    "possession": "Ball Possession",
    "corners": "Corner Kicks",
    "fouls": "Fouls",
    "yellow_cards": "Yellow Cards",
    "red_cards": "Red Cards",
}


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _integer(value: object) -> int:
    return int(str(value))


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _partition(state: Path, season: int, entity: str) -> Path | None:
    paths = sorted(
        (
            state
            / "parquet"
            / "competition=Ligue-1"
            / f"season={season}"
            / f"entity_type={entity}"
        ).rglob("*.parquet")
    )
    return paths[0] if paths else None


def canonical_fixture_facts(
    state: Path,
    seasons: Iterable[int],
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for season in seasons:
        path = _partition(state, season, "fixtures")
        if path is None:
            continue
        for row in pd.read_parquet(path).to_dict(orient="records"):
            payload = _payload(row.get("payload"))
            fixture = payload.get("fixture", {})
            league = payload.get("league", {})
            teams = payload.get("teams", {})
            goals = payload.get("goals", {})
            if not all(
                isinstance(value, Mapping)
                for value in (fixture, league, teams, goals)
            ):
                continue
            status = str(fixture.get("status", {}).get("short", "")).upper()
            if (
                not str(league.get("round", "")).startswith("Regular Season")
                or status in {"CANC", "ABD", "INT", "SUSP"}
                or not isinstance(fixture.get("id"), int)
            ):
                continue
            home = teams.get("home", {})
            away = teams.get("away", {})
            if not isinstance(home, Mapping) or not isinstance(away, Mapping):
                continue
            facts.append(
                {
                    "fixture_id": int(fixture["id"]),
                    "competition": "Ligue 1",
                    "season": season,
                    "kickoff_at": str(fixture.get("date")),
                    "home_team_id": home.get("id"),
                    "away_team_id": away.get("id"),
                    "home_team": home.get("name"),
                    "away_team": away.get("name"),
                    "home_goals": goals.get("home"),
                    "away_goals": goals.get("away"),
                    "round": league.get("round"),
                    "status": status,
                    "raw_payload_hash": row.get("raw_payload_hash"),
                    "source": "API-FOOTBALL HISTORICAL",
                }
            )
    unique = {_integer(fact["fixture_id"]): fact for fact in facts}
    return sorted(
        unique.values(),
        key=lambda fact: (str(fact["kickoff_at"]), _integer(fact["fixture_id"])),
    )


def _team_statistics(
    state: Path,
    seasons: Iterable[int],
) -> dict[tuple[int, int], dict[str, float | None]]:
    dimensions = observation_dimensions(state)
    output: dict[tuple[int, int], dict[str, float | None]] = {}
    for season in seasons:
        path = _partition(state, season, "fixture_team_statistics")
        if path is None:
            continue
        for row in pd.read_parquet(path).to_dict(orient="records"):
            context = dimensions.get(str(row.get("raw_payload_hash", "")), {})
            fixture_id = context.get("fixture_id")
            payload = _payload(row.get("payload"))
            team = payload.get("team", {})
            statistics = payload.get("statistics", [])
            if (
                not isinstance(fixture_id, int)
                or not isinstance(team, Mapping)
                or not isinstance(team.get("id"), int)
                or not isinstance(statistics, list)
            ):
                continue
            by_type = {
                str(item.get("type")): item.get("value")
                for item in statistics
                if isinstance(item, Mapping)
            }
            output[(fixture_id, int(team["id"]))] = {
                feature: _numeric(by_type.get(source_name))
                for feature, source_name in ROLLING_TEAM_STATISTICS.items()
            }
    return output


def _team_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    folded = "".join(character for character in text if not unicodedata.combining(character))
    compact = "".join(character for character in folded.casefold() if character.isalnum())
    aliases = {
        "parissaintgermain": "parissg",
        "stetienne": "saintetienne",
        "olympiquedemarseille": "marseille",
        "olympiquelyonnais": "lyon",
    }
    return aliases.get(compact, compact)


def _legacy_market_index(legacy: Path) -> dict[tuple[str, str, str], dict[str, object]]:
    if not legacy.exists():
        return {}
    frame = pd.read_parquet(legacy)
    frame = frame.loc[frame["league"] == "F1"]
    output: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in frame.to_dict(orient="records"):
        kickoff = pd.Timestamp(row["date"])
        key = (
            kickoff.date().isoformat(),
            _team_key(row.get("home")),
            _team_key(row.get("away")),
        )
        output[key] = {
            "odds_home": _numeric(row.get("psch") or row.get("psh")),
            "odds_draw": _numeric(row.get("pscd") or row.get("psd")),
            "odds_away": _numeric(row.get("psca") or row.get("psa")),
            "odds_over_25": _numeric(row.get("pc_o25") or row.get("p_o25")),
            "odds_under_25": _numeric(row.get("pc_u25") or row.get("p_u25")),
            "market_source": "Football-Data.co.uk / LEGACY SOURCE",
            "market_temporal_status": "HISTORICAL_CLOSING_MARKET",
        }
    return output


def _devig(prices: Iterable[float | None]) -> list[float | None]:
    values = list(prices)
    implied = [1.0 / value if value is not None and value > 1.0 else None for value in values]
    total = sum(value for value in implied if value is not None)
    return [value / total if value is not None and total > 0 else None for value in implied]


def build_api_team_pre_match(
    state: Path,
    *,
    seasons: tuple[int, ...],
    legacy_matches: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Construire les features avant d'ajouter les statistiques du match cible."""

    fixtures = canonical_fixture_facts(state, seasons)
    statistics = _team_statistics(state, seasons)
    markets = _legacy_market_index(legacy_matches)
    baseline_input = [
        {
            "match_id": fixture["fixture_id"],
            "league": "Ligue 1",
            "season": fixture["season"],
            "date": fixture["kickoff_at"],
            "home": fixture["home_team_id"],
            "away": fixture["away_team_id"],
            "fthg": fixture["home_goals"],
            "ftag": fixture["away_goals"],
            "source": "API-FOOTBALL HISTORICAL",
        }
        for fixture in fixtures
    ]
    baseline_by_id = {
        _integer(row["fixture_id"]): row
        for row in build_team_feature_rows(baseline_input)
    }
    histories: defaultdict[int, dict[str, deque[float | None]]] = defaultdict(
        lambda: {
            feature: deque(maxlen=20) for feature in ROLLING_TEAM_STATISTICS
        }
    )
    rows: list[dict[str, object]] = []
    market_rows: list[dict[str, object]] = []
    for fixture in fixtures:
        fixture_id = _integer(fixture["fixture_id"])
        home_id = _integer(fixture["home_team_id"])
        away_id = _integer(fixture["away_team_id"])
        row = dict(baseline_by_id[fixture_id])
        row.update(
            {
                "dataset_name": "api_team_pre_match_v1",
                "dataset_version": "api_team_pre_match_v1",
                "home_team_id": home_id,
                "away_team_id": away_id,
                "home_team_name": fixture["home_team"],
                "away_team_name": fixture["away_team"],
                "temporal_policy": "HISTORICAL POINT-IN-TIME",
            }
        )
        for feature in ROLLING_TEAM_STATISTICS:
            for window in (5, 10):
                row[f"home_{feature}_{window}"] = _mean(
                    list(histories[home_id][feature])[-window:]
                )
                row[f"away_{feature}_{window}"] = _mean(
                    list(histories[away_id][feature])[-window:]
                )
        kickoff = datetime.fromisoformat(
            str(fixture["kickoff_at"]).replace("Z", "+00:00")
        )
        market = markets.get(
            (
                kickoff.date().isoformat(),
                _team_key(fixture["home_team"]),
                _team_key(fixture["away_team"]),
            ),
            {},
        )
        row.update(market)
        rows.append(row)
        prices = [
            _numeric(market.get("odds_home")),
            _numeric(market.get("odds_draw")),
            _numeric(market.get("odds_away")),
        ]
        probabilities = _devig(prices)
        if any(price is not None for price in prices):
            market_rows.append(
                {
                    "dataset_name": "api_market_baseline_v1",
                    "dataset_version": "api_market_baseline_v1",
                    "fixture_id": fixture_id,
                    "competition": "Ligue 1",
                    "season": fixture["season"],
                    "kickoff_at": fixture["kickoff_at"],
                    "as_of_time": fixture["kickoff_at"],
                    "market": "1X2",
                    "odds_home": prices[0],
                    "odds_draw": prices[1],
                    "odds_away": prices[2],
                    "implied_home": probabilities[0],
                    "implied_draw": probabilities[1],
                    "implied_away": probabilities[2],
                    "bookmaker_margin": (
                        sum(1.0 / price for price in prices if price is not None) - 1.0
                        if all(price is not None for price in prices)
                        else None
                    ),
                    "source": market.get("market_source"),
                    "availability_status": "HISTORICAL_CLOSING_MARKET",
                    "quality_status": "JOINED_BY_DATE_AND_CANONICAL_TEAMS",
                }
            )
        for team_id in (home_id, away_id):
            current = statistics.get((fixture_id, team_id), {})
            for feature in ROLLING_TEAM_STATISTICS:
                histories[team_id][feature].append(current.get(feature))
    assert_temporal_integrity(rows)
    return rows, market_rows


def _statistic(item: Mapping[str, Any], group: str, name: str) -> float | None:
    statistics = item.get("statistics", [])
    if not isinstance(statistics, list) or not statistics:
        return None
    first = statistics[0]
    if not isinstance(first, Mapping):
        return None
    values = first.get(group, {})
    return _numeric(values.get(name)) if isinstance(values, Mapping) else None


def player_match_facts(
    state: Path,
    *,
    seasons: tuple[int, ...],
) -> list[dict[str, object]]:
    dimensions = observation_dimensions(state)
    fixture_index = {
        _integer(fixture["fixture_id"]): fixture
        for fixture in canonical_fixture_facts(state, seasons)
    }
    output: list[dict[str, object]] = []
    for season in seasons:
        path = _partition(state, season, "fixture_player_statistics")
        if path is None:
            continue
        for row in pd.read_parquet(path).to_dict(orient="records"):
            context = dimensions.get(str(row.get("raw_payload_hash", "")), {})
            fixture_id = context.get("fixture_id")
            fixture = fixture_index.get(int(fixture_id)) if isinstance(fixture_id, int) else None
            payload = _payload(row.get("payload"))
            team = payload.get("team", {})
            players = payload.get("players", [])
            if fixture is None or not isinstance(team, Mapping) or not isinstance(players, list):
                continue
            team_id = team.get("id")
            if not isinstance(team_id, int):
                continue
            for item in players:
                if not isinstance(item, Mapping):
                    continue
                player = item.get("player", {})
                if not isinstance(player, Mapping) or not isinstance(player.get("id"), int):
                    continue
                statistics = item.get("statistics", [])
                first_statistics = (
                    statistics[0]
                    if isinstance(statistics, list)
                    and statistics
                    and isinstance(statistics[0], Mapping)
                    else {}
                )
                games = first_statistics.get("games", {})
                substitute = (
                    games.get("substitute")
                    if isinstance(games, Mapping)
                    else None
                )
                output.append(
                    {
                        "fixture_id": _integer(fixture_id),
                        "competition": "Ligue 1",
                        "season": season,
                        "kickoff_at": fixture["kickoff_at"],
                        "player_id": int(player["id"]),
                        "player_name": player.get("name"),
                        "team_id": team_id,
                        "position": (
                            games.get("position")
                            if isinstance(games, Mapping)
                            else None
                        ),
                        "minutes": _statistic(item, "games", "minutes"),
                        "starter": (
                            not bool(substitute)
                            if isinstance(substitute, bool)
                            else None
                        ),
                        "rating": _statistic(item, "games", "rating"),
                        "goals": _statistic(item, "goals", "total"),
                        "assists": _statistic(item, "goals", "assists"),
                        "shots": _statistic(item, "shots", "total"),
                        "shots_on_goal": _statistic(item, "shots", "on"),
                        "key_passes": _statistic(item, "passes", "key"),
                        "tackles": _statistic(item, "tackles", "total"),
                        "interceptions": _statistic(item, "tackles", "interceptions"),
                        "duels": _statistic(item, "duels", "total"),
                        "duels_won": _statistic(item, "duels", "won"),
                        "fouls": _statistic(item, "fouls", "committed"),
                        "yellow_cards": _statistic(item, "cards", "yellow"),
                        "red_cards": _statistic(item, "cards", "red"),
                        "source": "API-FOOTBALL HISTORICAL",
                        "availability_status": "POST_MATCH_ONLY",
                        "raw_payload_hash": row.get("raw_payload_hash"),
                    }
                )
    unique = {
        (
            _integer(row["fixture_id"]),
            _integer(row["player_id"]),
            _integer(row["team_id"]),
        ): row
        for row in output
    }
    return sorted(
        unique.values(),
        key=lambda row: (
            str(row["kickoff_at"]),
            _integer(row["fixture_id"]),
            _integer(row["player_id"]),
        ),
    )


def _feature_values(
    history: Sequence[Mapping[str, object]],
    kickoff: datetime,
) -> dict[str, object]:
    previous = sorted(history, key=lambda row: str(row["kickoff_at"]))
    minutes = [_numeric(row.get("minutes")) for row in previous]
    recent_five = previous[-5:]
    recent_ten = previous[-10:]
    last_kickoff = (
        datetime.fromisoformat(str(previous[-1]["kickoff_at"]).replace("Z", "+00:00"))
        if previous
        else None
    )

    def recent_sum(name: str, count: int) -> float | None:
        return _mean(
            _numeric(row.get(name))
            for row in previous[-count:]
        )

    def optional_sum(values: Iterable[float | None]) -> float | None:
        present = [value for value in values if value is not None]
        return sum(present) if present else None

    def minutes_in_days(days: int) -> float | None:
        return optional_sum(
            _numeric(row.get("minutes"))
            for row in previous
            if (
                kickoff
                - datetime.fromisoformat(
                    str(row["kickoff_at"]).replace("Z", "+00:00")
                )
            ).days
            <= days
        )

    minutes_support = sum(value for value in minutes if value is not None)
    offensive = _mean(
        [
            recent_sum("goals", 10),
            recent_sum("assists", 10),
            recent_sum("shots_on_goal", 10),
            recent_sum("key_passes", 10),
        ]
    )
    defensive = _mean(
        [
            recent_sum("tackles", 10),
            recent_sum("interceptions", 10),
            recent_sum("duels_won", 10),
        ]
    )
    rating = _mean(_numeric(row.get("rating")) for row in recent_five)
    regularization = minutes_support / (minutes_support + 900.0)
    strength_components = [
        rating,
        offensive,
        defensive,
        _mean(_numeric(row.get("minutes")) for row in recent_five),
    ]
    raw_strength = _mean(strength_components)
    goals_last_10 = optional_sum(
        _numeric(row.get("goals")) for row in recent_ten
    )
    assists_last_10 = optional_sum(
        _numeric(row.get("assists")) for row in recent_ten
    )
    shots_last_10 = optional_sum(
        _numeric(row.get("shots")) for row in recent_ten
    )
    shots_on_goal_last_10 = optional_sum(
        _numeric(row.get("shots_on_goal")) for row in recent_ten
    )
    recent_ratings = [
        value
        for value in [_numeric(row.get("rating")) for row in recent_ten]
        if value is not None
    ]
    minutes_14_days = minutes_in_days(14)
    return {
        "minutes_last_5": optional_sum(
            _numeric(row.get("minutes")) for row in recent_five
        ),
        "minutes_last_10": optional_sum(
            _numeric(row.get("minutes")) for row in recent_ten
        ),
        "minutes_7_days": minutes_in_days(7),
        "minutes_14_days": minutes_in_days(14),
        "minutes_30_days": minutes_in_days(30),
        "days_since_last_start": (
            (kickoff - last_kickoff).days if last_kickoff is not None else None
        ),
        "starts_last_5": (
            sum(row.get("starter") is True for row in recent_five)
            if recent_five
            else None
        ),
        "substitute_appearances_last_5": (
            sum(row.get("starter") is False for row in recent_five)
            if recent_five
            else None
        ),
        "goals_last_10": goals_last_10,
        "assists_last_10": assists_last_10,
        "shots_last_10": shots_last_10,
        "shots_on_goal_last_10": shots_on_goal_last_10,
        "offensive_contribution_per_90": (
            (goals_last_10 + assists_last_10) * 90.0 / minutes_support
            if goals_last_10 is not None
            and assists_last_10 is not None
            and minutes_support > 0
            else None
        ),
        "recent_form_score": rating,
        "form_volatility": (
            float(pd.Series(recent_ratings).std(ddof=0))
            if recent_ratings
            else None
        ),
        "offensive_contribution_score": offensive,
        "defensive_contribution_score": defensive,
        "role_importance_score": (
            _mean(_numeric(row.get("minutes")) for row in recent_ten)
        ),
        "minutes_support": minutes_support,
        "player_strength": (
            raw_strength * regularization if raw_strength is not None else None
        ),
        "uncertainty": 1.0 - regularization,
        "fatigue_estimate": (
            minutes_14_days / 1_260.0
            if minutes_14_days is not None
            else None
        ),
    }


def _lineups(
    state: Path,
    seasons: tuple[int, ...],
) -> dict[tuple[int, int], dict[str, object]]:
    dimensions = observation_dimensions(state)
    output: dict[tuple[int, int], dict[str, object]] = {}
    for season in seasons:
        path = _partition(state, season, "lineups")
        if path is None:
            continue
        for row in pd.read_parquet(path).to_dict(orient="records"):
            context = dimensions.get(str(row.get("raw_payload_hash", "")), {})
            fixture_id = context.get("fixture_id")
            payload = _payload(row.get("payload"))
            team = payload.get("team", {})
            start_xi = payload.get("startXI", [])
            substitutes = payload.get("substitutes", [])
            if (
                not isinstance(fixture_id, int)
                or not isinstance(team, Mapping)
                or not isinstance(team.get("id"), int)
                or not isinstance(start_xi, list)
                or not isinstance(substitutes, list)
            ):
                continue
            output[(fixture_id, int(team["id"]))] = {
                "starting_ids": [
                    item.get("player", {}).get("id")
                    for item in start_xi
                    if isinstance(item, Mapping)
                ],
                "bench_ids": [
                    item.get("player", {}).get("id")
                    for item in substitutes
                    if isinstance(item, Mapping)
                ],
                "formation": payload.get("formation"),
            }
    return output


def build_player_feature_datasets(
    state: Path,
    *,
    team_rows: list[dict[str, object]],
    seasons: tuple[int, ...],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Créer le store long, le PRE_LINEUP et le POST_LINEUP_SIMULATED."""

    facts = player_match_facts(state, seasons=seasons)
    facts_by_fixture: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for fact in facts:
        facts_by_fixture[_integer(fact["fixture_id"])].append(fact)
    lineups = _lineups(state, seasons)
    histories: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    team_rosters: defaultdict[int, set[int]] = defaultdict(set)
    latest_team: dict[int, int] = {}
    feature_rows: list[dict[str, object]] = []
    pre_rows: list[dict[str, object]] = []
    post_rows: list[dict[str, object]] = []
    for team_row in sorted(team_rows, key=lambda row: str(row["kickoff_at"])):
        fixture_id = _integer(team_row["fixture_id"])
        kickoff = datetime.fromisoformat(
            str(team_row["kickoff_at"]).replace("Z", "+00:00")
        )
        summaries: dict[int, dict[str, object]] = {}
        expected_rosters: dict[int, list[int]] = {}
        for team_id in (
            _integer(team_row["home_team_id"]),
            _integer(team_row["away_team_id"]),
        ):
            for player_id in team_rosters[team_id]:
                summaries[player_id] = _feature_values(histories[player_id], kickoff)
            ranked = sorted(
                team_rosters[team_id],
                key=lambda player_id: (
                    _numeric(summaries.get(player_id, {}).get("starts_last_5"))
                    or -1.0,
                    _numeric(summaries.get(player_id, {}).get("minutes_last_5"))
                    or -1.0,
                    -player_id,
                ),
                reverse=True,
            )
            expected_rosters[team_id] = ranked[:18]
            # Le store long conserve 16 joueurs par équipe et par cutoff ; les
            # agrégats de banc utilisent encore les 18 candidats. Cette borne
            # évite que l'artefact régénérable pousse le scénario haut au-delà
            # du seuil de 750 MB.
            for player_id in expected_rosters[team_id][:16]:
                for feature_name, value in summaries[player_id].items():
                    feature_rows.append(
                        {
                            "feature_name": feature_name,
                            "feature_version": "player_feature_store_v1",
                            "player_id": player_id,
                            "team_id": team_id,
                            "fixture_id": fixture_id,
                            "as_of_time": kickoff.isoformat(),
                            "value": value,
                            "source": "API-FOOTBALL HISTORICAL",
                            "quality_status": "CALCULATED_FROM_PRIOR_FIXTURES",
                            "availability_status": "PRE_LINEUP",
                            "leakage_risk": "LAG_ENFORCED",
                            "calculated_at": kickoff.isoformat(),
                            "season": team_row["season"],
                            "competition": "Ligue 1",
                        }
                    )

        def aggregate(team_id: int, actual: bool) -> dict[str, object]:
            lineup = lineups.get((fixture_id, team_id), {})
            if actual:
                starting_values = lineup.get("starting_ids", [])
                bench_values = lineup.get("bench_ids", [])
                player_ids = [
                    int(value)
                    for value in starting_values
                    if isinstance(value, int)
                ] if isinstance(starting_values, list) else []
                bench_ids = [
                    int(value)
                    for value in bench_values
                    if isinstance(value, int)
                ] if isinstance(bench_values, list) else []
            else:
                ranked = expected_rosters[team_id]
                player_ids, bench_ids = ranked[:11], ranked[11:18]
            strengths = [
                _numeric(summaries.get(player_id, {}).get("player_strength"))
                for player_id in player_ids
            ]
            bench_strengths = [
                _numeric(summaries.get(player_id, {}).get("player_strength"))
                for player_id in bench_ids
            ]
            return {
                "starting_xi_strength": _mean(strengths),
                "bench_strength": _mean(bench_strengths),
                "lineup_continuity": (
                    sum(
                        _numeric(summaries.get(player_id, {}).get("starts_last_5"))
                        is not None
                        for player_id in player_ids
                    )
                    / len(player_ids)
                    if player_ids
                    else None
                ),
                "formation": lineup.get("formation") if actual else None,
                "lineup_uncertainty": _mean(
                    _numeric(summaries.get(player_id, {}).get("uncertainty"))
                    for player_id in player_ids
                ),
                "resolved_players": sum(player_id in summaries for player_id in player_ids),
                "lineup_size": len(player_ids),
            }

        home_id = _integer(team_row["home_team_id"])
        away_id = _integer(team_row["away_team_id"])
        expected_home = aggregate(home_id, False)
        expected_away = aggregate(away_id, False)
        pre = dict(team_row)
        pre.update(
            {
                "dataset_name": "api_player_pre_lineup_v1",
                "dataset_version": "api_player_pre_lineup_v1",
                "temporal_policy": "PRE_LINEUP",
                **{f"home_expected_{key}": value for key, value in expected_home.items()},
                **{f"away_expected_{key}": value for key, value in expected_away.items()},
            }
        )
        pre_rows.append(pre)
        confirmed_home = aggregate(home_id, True)
        confirmed_away = aggregate(away_id, True)
        if confirmed_home["lineup_size"] == 11 and confirmed_away["lineup_size"] == 11:
            post = dict(pre)
            post.update(
                {
                    "dataset_name": "api_post_lineup_simulated_v1",
                    "dataset_version": "api_post_lineup_simulated_v1",
                    "temporal_policy": "POST_LINEUP_SIMULATED",
                    "availability_status": "HISTORICAL SIMULATED",
                    **{
                        f"home_confirmed_{key}": value
                        for key, value in confirmed_home.items()
                    },
                    **{
                        f"away_confirmed_{key}": value
                        for key, value in confirmed_away.items()
                    },
                }
            )
            home_expected = _numeric(expected_home["starting_xi_strength"])
            away_expected = _numeric(expected_away["starting_xi_strength"])
            home_confirmed = _numeric(confirmed_home["starting_xi_strength"])
            away_confirmed = _numeric(confirmed_away["starting_xi_strength"])
            post["home_difference_vs_expected"] = (
                home_confirmed - home_expected
                if home_confirmed is not None and home_expected is not None
                else None
            )
            post["away_difference_vs_expected"] = (
                away_confirmed - away_expected
                if away_confirmed is not None and away_expected is not None
                else None
            )
            post_rows.append(post)
        for fact in facts_by_fixture[fixture_id]:
            player_id = _integer(fact["player_id"])
            team_id = _integer(fact["team_id"])
            previous_team = latest_team.get(player_id)
            if previous_team is not None and previous_team != team_id:
                team_rosters[previous_team].discard(player_id)
            histories[player_id].append(fact)
            team_rosters[team_id].add(player_id)
            latest_team[player_id] = team_id
    return feature_rows, pre_rows, post_rows


def write_dataset(
    state: Path,
    *,
    name: str,
    rows: list[dict[str, object]],
    code_revision: str,
    temporal_policy: str,
) -> dict[str, object]:
    store = PartitionedParquetStore(state / "derived")
    partitions: list[dict[str, object]] = []
    for season in sorted({_integer(row["season"]) for row in rows}):
        season_rows = [row for row in rows if _integer(row["season"]) == season]
        partitions.append(
            store.write_records(
                season_rows,
                competition="Ligue-1",
                season=season,
                entity_type=name,
                dataset_version=name,
            )
        )
    manifest = dataset_manifest(
        rows,
        name=name,
        code_version=code_revision,
        policy=temporal_policy,
    )
    manifest.update(
        {
            "fixtures": len({row.get("fixture_id") for row in rows}),
            "targets": ["1X2", "OVER_UNDER_2_5"],
            "excluded_rows": 0,
            "source": sorted({str(row.get("source", "API-FOOTBALL HISTORICAL")) for row in rows}),
            "generated_at": manifest.pop("created_at"),
            "code_revision": manifest.pop("code_version"),
            "partitions": partitions,
            "status": (
                "POST_LINEUP_SIMULATED_READY"
                if name == "api_post_lineup_simulated_v1"
                else "API_PLAYER_DATASET_READY"
                if name == "api_player_pre_lineup_v1"
                else "PLAYER_FEATURE_FACTORY_ACTIVE"
                if name in {"player_feature_store_v1", "api_player_match_facts_v1"}
                else "API_MARKET_BASELINE_READY"
                if name == "api_market_baseline_v1"
                else "API_TEAM_DATASET_READY"
            ),
        }
    )
    return manifest


def content_hash(rows: Iterable[Mapping[str, object]]) -> str:
    payload = json.dumps(
        [dict(row) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
