"""Elo, Poisson, Dixon-Coles, consensus et baseline marché."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from robin.domain.enums import QualityStatus
from robin.domain.temporal import require_utc


class MatchProbabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)
    expected_home_goals: float = Field(ge=0)
    expected_away_goals: float = Field(ge=0)

    @property
    def total(self) -> float:
        return self.home + self.draw + self.away


class ShadowPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction_id: str
    fixture_id: str
    generated_at: datetime
    as_of_time: datetime
    model_name: str
    model_version: str
    dataset_version: str
    feature_version: str
    probability_home: float
    probability_draw: float
    probability_away: float
    expected_home_goals: float
    expected_away_goals: float
    data_quality_status: QualityStatus
    uncertainty_status: str
    market_snapshot_id: str | None = None


@dataclass
class EloModel:
    k_factor: float = 20.0
    home_advantage: float = 65.0

    def __post_init__(self) -> None:
        self.ratings: dict[str, float] = {}

    def rating(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def predict(self, home: str, away: str) -> MatchProbabilities:
        delta = self.rating(home) + self.home_advantage - self.rating(away)
        home_no_draw = 1.0 / (1.0 + 10 ** (-delta / 400.0))
        draw = 0.25 * math.exp(-abs(delta) / 500.0)
        home_prob = (1.0 - draw) * home_no_draw
        away_prob = 1.0 - draw - home_prob
        return MatchProbabilities(
            home=home_prob,
            draw=draw,
            away=away_prob,
            expected_home_goals=max(0.2, 1.35 + delta / 800.0),
            expected_away_goals=max(0.2, 1.10 - delta / 800.0),
        )

    def update(self, home: str, away: str, home_goals: int, away_goals: int) -> None:
        prediction = self.predict(home, away)
        actual = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        expected = prediction.home + prediction.draw / 2.0
        change = self.k_factor * (actual - expected)
        self.ratings[home] = self.rating(home) + change
        self.ratings[away] = self.rating(away) - change


def _poisson_pmf(goals: int, expected: float) -> float:
    return math.exp(-expected) * expected**goals / math.factorial(goals)


def poisson_probabilities(
    expected_home: float,
    expected_away: float,
    *,
    dixon_coles: bool = False,
    rho: float = -0.08,
) -> MatchProbabilities:
    home = draw = away = 0.0
    for home_goals in range(11):
        for away_goals in range(11):
            probability = _poisson_pmf(home_goals, expected_home) * _poisson_pmf(
                away_goals, expected_away
            )
            if dixon_coles and home_goals <= 1 and away_goals <= 1:
                if (home_goals, away_goals) == (0, 0):
                    probability *= 1.0 - expected_home * expected_away * rho
                elif (home_goals, away_goals) == (0, 1):
                    probability *= 1.0 + expected_home * rho
                elif (home_goals, away_goals) == (1, 0):
                    probability *= 1.0 + expected_away * rho
                else:
                    probability *= 1.0 - rho
            if home_goals > away_goals:
                home += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away += probability
    total = home + draw + away
    return MatchProbabilities(
        home=home / total,
        draw=draw / total,
        away=away / total,
        expected_home_goals=expected_home,
        expected_away_goals=expected_away,
    )


def estimate_expected_goals(
    history: pd.DataFrame,
    *,
    home_team: str,
    away_team: str,
    as_of_time: datetime,
) -> tuple[float, float]:
    cutoff = pd.Timestamp(require_utc(as_of_time, "as_of_time"))
    dates = pd.to_datetime(history["date"], utc=True)
    prior = history.loc[dates < cutoff]
    if prior.empty:
        return 1.35, 1.10
    league_home = float(prior["fthg"].mean())
    league_away = float(prior["ftag"].mean())
    home_rows = prior[prior["home"] == home_team].tail(20)
    away_rows = prior[prior["away"] == away_team].tail(20)
    home_attack = (
        float(home_rows["fthg"].mean()) / league_home
        if len(home_rows) >= 5 and league_home > 0
        else 1.0
    )
    away_defence = (
        float(away_rows["fthg"].mean()) / league_home
        if len(away_rows) >= 5 and league_home > 0
        else 1.0
    )
    away_attack = (
        float(away_rows["ftag"].mean()) / league_away
        if len(away_rows) >= 5 and league_away > 0
        else 1.0
    )
    home_defence = (
        float(home_rows["ftag"].mean()) / league_away
        if len(home_rows) >= 5 and league_away > 0
        else 1.0
    )
    return (
        max(0.2, min(4.0, league_home * home_attack * away_defence)),
        max(0.2, min(4.0, league_away * away_attack * home_defence)),
    )


def market_probabilities(home: float, draw: float, away: float) -> MatchProbabilities:
    inverses = [1.0 / home, 1.0 / draw, 1.0 / away]
    total = sum(inverses)
    return MatchProbabilities(
        home=inverses[0] / total,
        draw=inverses[1] / total,
        away=inverses[2] / total,
        expected_home_goals=0.0,
        expected_away_goals=0.0,
    )


def consensus(*predictions: MatchProbabilities) -> MatchProbabilities:
    if not predictions:
        raise ValueError("au moins une prédiction est requise")
    count = len(predictions)
    return MatchProbabilities(
        home=sum(item.home for item in predictions) / count,
        draw=sum(item.draw for item in predictions) / count,
        away=sum(item.away for item in predictions) / count,
        expected_home_goals=sum(item.expected_home_goals for item in predictions)
        / count,
        expected_away_goals=sum(item.expected_away_goals for item in predictions)
        / count,
    )
