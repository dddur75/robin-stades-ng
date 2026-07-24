"""Baselines walk-forward du Jalon 2."""

from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass

import pandas as pd

from robin.modeling.reference import EloModel, consensus, poisson_probabilities


def _as_int(value: object) -> int:
    return int(float(str(value)))


def _as_float(value: object) -> float:
    return float(str(value))


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    bets: int
    wins: int
    profit: float
    roi: float
    roi_ci_low: float
    roi_ci_high: float
    max_drawdown: float
    status: str
    note: str


class RollingGoals:
    def __init__(self) -> None:
        self.home_for: dict[str, list[int]] = {}
        self.home_against: dict[str, list[int]] = {}
        self.away_for: dict[str, list[int]] = {}
        self.away_against: dict[str, list[int]] = {}
        self.all_home: list[int] = []
        self.all_away: list[int] = []

    @staticmethod
    def _mean(values: list[int], fallback: float) -> float:
        return sum(values[-20:]) / len(values[-20:]) if values else fallback

    def predict(self, home: str, away: str) -> tuple[float, float]:
        league_home = self._mean(self.all_home, 1.35)
        league_away = self._mean(self.all_away, 1.10)
        home_for = self._mean(self.home_for.get(home, []), league_home)
        home_against = self._mean(self.home_against.get(home, []), league_away)
        away_for = self._mean(self.away_for.get(away, []), league_away)
        away_against = self._mean(self.away_against.get(away, []), league_home)
        return (
            max(0.2, min(4.0, (home_for + away_against) / 2.0)),
            max(0.2, min(4.0, (away_for + home_against) / 2.0)),
        )

    def update(self, home: str, away: str, home_goals: int, away_goals: int) -> None:
        self.home_for.setdefault(home, []).append(home_goals)
        self.home_against.setdefault(home, []).append(away_goals)
        self.away_for.setdefault(away, []).append(away_goals)
        self.away_against.setdefault(away, []).append(home_goals)
        self.all_home.append(home_goals)
        self.all_away.append(away_goals)


def _profit(odds: float, won: bool) -> float:
    return odds - 1.0 if won else -1.0


def _drawdown(profits: list[float]) -> float:
    equity = peak = worst = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _result(name: str, profits: list[float], wins: int, note: str) -> StrategyResult:
    bets = len(profits)
    profit = sum(profits)
    roi = profit / bets if bets else 0.0
    standard_error = (
        statistics.stdev(profits) / math.sqrt(bets) if bets >= 2 else 0.0
    )
    ci_low = roi - 1.96 * standard_error
    ci_high = roi + 1.96 * standard_error
    if bets < 100:
        status = "INSUFFICIENT_SAMPLE"
    elif roi <= 0:
        status = "REJECTED_OOS"
    elif ci_low <= 0:
        status = "INCONCLUSIVE_OOS"
    else:
        status = "CANDIDATE_FOR_SHADOW"
    return StrategyResult(
        strategy=name,
        bets=bets,
        wins=wins,
        profit=profit,
        roi=roi,
        roi_ci_low=ci_low,
        roi_ci_high=ci_high,
        max_drawdown=_drawdown(profits),
        status=status,
        note=note,
    )


def evaluate_walk_forward(
    frame: pd.DataFrame,
    *,
    holdout_season: str = "2025-26",
    min_edge: float = 0.04,
) -> list[StrategyResult]:
    ordered = frame.copy()
    ordered["date"] = pd.to_datetime(ordered["date"], utc=True)
    ordered = ordered.sort_values(["date", "match_id"])
    train = ordered[ordered["season"] != holdout_season]
    holdout = ordered[ordered["season"] == holdout_season]
    elo = EloModel()
    goals = RollingGoals()
    for row in train.itertuples(index=False):
        elo.update(str(row.home), str(row.away), _as_int(row.fthg), _as_int(row.ftag))
        goals.update(str(row.home), str(row.away), _as_int(row.fthg), _as_int(row.ftag))

    ledgers: dict[str, list[float]] = {
        "aucun_pari": [],
        "favori_marche": [],
        "favori_domicile": [],
        "aleatoire_controlee": [],
        "seuil_probabilite": [],
        "value_betting_simple": [],
        "value_edge_2pct": [],
        "value_edge_6pct": [],
        "cote_fixe_1_80_2_20": [],
        "over_2_5_value": [],
        "btts_value": [],
    }
    wins = {key: 0 for key in ledgers}
    for _, batch in holdout.groupby("date", sort=True):
        for row in batch.itertuples(index=False):
            home = str(row.home)
            away = str(row.away)
            home_goals = _as_int(row.fthg)
            away_goals = _as_int(row.ftag)
            elo_prediction = elo.predict(home, away)
            expected_home, expected_away = goals.predict(home, away)
            poisson = poisson_probabilities(expected_home, expected_away)
            model = consensus(elo_prediction, poisson)
            odds = [_as_float(row.psch), _as_float(row.pscd), _as_float(row.psca)]
            valid_1x2 = all(pd.notna(value) and value > 1.0 for value in odds)
            outcomes = [
                home_goals > away_goals,
                home_goals == away_goals,
                home_goals < away_goals,
            ]
            model_probs = [model.home, model.draw, model.away]
            if valid_1x2:
                favorite = min(range(3), key=odds.__getitem__)
                ledgers["favori_marche"].append(
                    _profit(odds[favorite], outcomes[favorite])
                )
                wins["favori_marche"] += int(outcomes[favorite])
                if favorite == 0:
                    ledgers["favori_domicile"].append(
                        _profit(odds[0], outcomes[0])
                    )
                    wins["favori_domicile"] += int(outcomes[0])
                random_index = int(
                    hashlib.sha256(str(row.match_id).encode()).hexdigest()[:8],
                    16,
                ) % 3
                ledgers["aleatoire_controlee"].append(
                    _profit(odds[random_index], outcomes[random_index])
                )
                wins["aleatoire_controlee"] += int(outcomes[random_index])
                best_model = max(range(3), key=model_probs.__getitem__)
                if model_probs[best_model] >= 0.55:
                    ledgers["seuil_probabilite"].append(
                        _profit(odds[best_model], outcomes[best_model])
                    )
                    wins["seuil_probabilite"] += int(outcomes[best_model])
                inverse = [1.0 / value for value in odds]
                margin = sum(inverse)
                fair = [value / margin for value in inverse]
                edges = [
                    model_probability - market_probability
                    for model_probability, market_probability in zip(
                        model_probs, fair, strict=True
                    )
                ]
                best_edge = max(range(3), key=edges.__getitem__)
                if edges[best_edge] >= min_edge:
                    ledgers["value_betting_simple"].append(
                        _profit(odds[best_edge], outcomes[best_edge])
                    )
                    wins["value_betting_simple"] += int(outcomes[best_edge])
                if edges[best_edge] >= 0.02:
                    ledgers["value_edge_2pct"].append(
                        _profit(odds[best_edge], outcomes[best_edge])
                    )
                    wins["value_edge_2pct"] += int(outcomes[best_edge])
                if edges[best_edge] >= 0.06:
                    ledgers["value_edge_6pct"].append(
                        _profit(odds[best_edge], outcomes[best_edge])
                    )
                    wins["value_edge_6pct"] += int(outcomes[best_edge])
                if 1.8 <= odds[0] <= 2.2:
                    ledgers["cote_fixe_1_80_2_20"].append(
                        _profit(odds[0], outcomes[0])
                    )
                    wins["cote_fixe_1_80_2_20"] += int(outcomes[0])
            over_odds = (
                _as_float(row.pc_o25) if pd.notna(row.pc_o25) else float("nan")
            )
            if over_odds > 1.0:
                expected_total = expected_home + expected_away
                under_probability = sum(
                    _poisson_total(total, expected_total) for total in range(3)
                )
                over_probability = 1.0 - under_probability
                if over_probability - 1.0 / over_odds >= min_edge:
                    over_won = home_goals + away_goals > 2
                    ledgers["over_2_5_value"].append(
                        _profit(over_odds, over_won)
                    )
                    wins["over_2_5_value"] += int(over_won)
        for row in batch.itertuples(index=False):
            elo.update(
                str(row.home),
                str(row.away),
                _as_int(row.fthg),
                _as_int(row.ftag),
            )
            goals.update(
                str(row.home),
                str(row.away),
                _as_int(row.fthg),
                _as_int(row.ftag),
            )

    notes = {
        "aucun_pari": "baseline nulle",
        "favori_marche": "cote de clôture legacy dé-vig non requise",
        "favori_domicile": "favori uniquement lorsqu'il joue à domicile",
        "aleatoire_controlee": "tirage déterministe par match_id",
        "seuil_probabilite": "consensus Elo-Poisson >= 55 %",
        "value_betting_simple": f"edge dé-viggé >= {min_edge:.0%}",
        "value_edge_2pct": "sensibilité edge dé-viggé >= 2 %",
        "value_edge_6pct": "sensibilité edge dé-viggé >= 6 %",
        "cote_fixe_1_80_2_20": "domicile dans le segment de cote",
        "over_2_5_value": f"Poisson vs cote O2,5, edge >= {min_edge:.0%}",
        "btts_value": "bloqué : aucune cote BTTS fiable dans le dataset legacy",
    }
    return [
        _result(name, ledger, wins[name], notes[name])
        for name, ledger in ledgers.items()
    ]


def _poisson_total(goals: int, expected: float) -> float:
    import math

    return math.exp(-expected) * expected**goals / math.factorial(goals)
