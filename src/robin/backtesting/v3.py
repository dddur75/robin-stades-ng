"""Backtest V3 borné, avec bankroll fictive et protection anti-data-mining."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np


@dataclass(frozen=True)
class StrategyParameters:
    name: str
    market: str
    minimum_edge: float
    minimum_probability: float = 0.0
    staking: str = "FIXED"
    kelly_fraction: float = 0.25
    stake_cap: float = 2.0


def _float(value: object) -> float:
    return float(str(value))


def _int(value: object) -> int:
    return int(str(value))


def devig_probabilities(prices: Iterable[float | None]) -> list[float | None]:
    values = list(prices)
    implied = [
        1.0 / price if price is not None and price > 1.0 else None
        for price in values
    ]
    total = sum(value for value in implied if value is not None)
    return [
        value / total if value is not None and total > 0.0 else None
        for value in implied
    ]


def _stake(
    probability: float,
    odds: float,
    bankroll: float,
    parameters: StrategyParameters,
) -> float:
    if parameters.staking == "FIXED":
        return min(1.0, parameters.stake_cap)
    if parameters.staking == "PROPORTIONAL":
        return min(bankroll * 0.01, parameters.stake_cap)
    if parameters.staking == "FRACTIONAL_KELLY":
        net = odds - 1.0
        kelly = max((probability * odds - 1.0) / net, 0.0)
        return min(bankroll * kelly * parameters.kelly_fraction, parameters.stake_cap)
    raise ValueError(f"staking inconnu: {parameters.staking}")


def _confidence_interval(profits: list[float], *, seed: int = 42) -> list[float | None]:
    if len(profits) < 2:
        return [None, None]
    generator = np.random.default_rng(seed)
    values = np.asarray(profits)
    samples = generator.choice(values, size=(2_000, len(values)), replace=True)
    means = samples.mean(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _adjusted_p_value(profits: list[float], hypotheses: int) -> float | None:
    if len(profits) < 2:
        return None
    values = np.asarray(profits)
    standard_error = float(values.std(ddof=1) / math.sqrt(len(values)))
    if standard_error == 0.0:
        raw = 0.0 if float(values.mean()) > 0.0 else 1.0
    else:
        z_score = float(values.mean()) / standard_error
        raw = math.erfc(abs(z_score) / math.sqrt(2.0))
    return min(raw * max(hypotheses, 1), 1.0)


def run_backtest(
    predictions: Iterable[Mapping[str, object]],
    parameters: StrategyParameters,
    *,
    hypotheses_tested: int = 1,
) -> dict[str, object]:
    """Exécuter un backtest sur un seul segment explicitement OOS."""

    bankroll = 100.0
    peak = bankroll
    maximum_drawdown = 0.0
    loss_streak = 0
    maximum_loss_streak = 0
    profits: list[float] = []
    details: list[dict[str, object]] = []
    for row in sorted(predictions, key=lambda item: str(item.get("kickoff_at", ""))):
        if row.get("origin") != "OOS HISTORICAL":
            raise ValueError("BACKTEST_SEGMENT_MIXED")
        if parameters.market == "1X2":
            probabilities = [
                _float(row[f"probability_{label}"])
                for label in ("home", "draw", "away")
            ]
            odds = [
                _float(row[f"odds_{label}"])
                if row.get(f"odds_{label}") is not None
                else None
                for label in ("home", "draw", "away")
            ]
            target = _int(row["target"])
        elif parameters.market == "OVER_UNDER_2_5":
            if row.get("probability_over_25") is None:
                continue
            over_probability = _float(row["probability_over_25"])
            probabilities = [over_probability, 1.0 - over_probability]
            odds = [
                _float(row["odds_over_25"])
                if row.get("odds_over_25") is not None
                else None,
                _float(row["odds_under_25"])
                if row.get("odds_under_25") is not None
                else None,
            ]
            target = _int(row["target_over_25"])
        else:
            raise ValueError(f"marché inconnu: {parameters.market}")
        market = devig_probabilities(odds)
        candidates = [
            (
                index,
                probability,
                price,
                probability - float(market_probability),
            )
            for index, (probability, price, market_probability) in enumerate(
                zip(probabilities, odds, market, strict=True)
            )
            if price is not None and market_probability is not None
        ]
        if not candidates:
            continue
        selection, probability, price, edge = max(
            candidates,
            key=lambda candidate: candidate[3],
        )
        if (
            edge < parameters.minimum_edge
            or probability < parameters.minimum_probability
        ):
            continue
        stake = _stake(probability, price, bankroll, parameters)
        profit = stake * (price - 1.0) if selection == target else -stake
        bankroll += profit
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, peak - bankroll)
        loss_streak = loss_streak + 1 if profit < 0 else 0
        maximum_loss_streak = max(maximum_loss_streak, loss_streak)
        profits.append(profit)
        details.append(
            {
                "fixture_id": row.get("fixture_id"),
                "selection": selection,
                "probability": probability,
                "market_probability": market[selection],
                "odds": price,
                "edge": edge,
                "stake": stake,
                "profit": profit,
                "bankroll": bankroll,
                "segment": "BLIND_OOS",
            }
        )
    interval = _confidence_interval(profits)
    adjusted_p = _adjusted_p_value(profits, hypotheses_tested)
    profit = sum(profits)
    status = (
        "REJECTED"
        if interval[1] is not None and float(interval[1]) < 0.0
        else "INCONCLUSIVE"
    )
    return {
        "backtest_version": "api_football_backtest_v3",
        "strategy": parameters.name,
        "market": parameters.market,
        "parameters": {
            "minimum_edge": parameters.minimum_edge,
            "minimum_probability": parameters.minimum_probability,
            "staking": parameters.staking,
            "kelly_fraction": parameters.kelly_fraction,
            "stake_cap": parameters.stake_cap,
        },
        "segment": "BLIND_OOS",
        "bets": len(profits),
        "profit_units": profit,
        "roi": profit / sum(abs(value) for value in profits) if profits else None,
        "yield": profit / len(profits) if profits else None,
        "max_drawdown_units": maximum_drawdown,
        "max_loss_streak": maximum_loss_streak,
        "confidence_interval_per_bet": interval,
        "hypotheses_tested": hypotheses_tested,
        "multiple_testing_method": "BONFERRONI",
        "adjusted_p_value": adjusted_p,
        "status": status,
        "promotion": "NO_PROMOTION",
        "production_status": "PRODUCTION_LOCKED",
        "details": details,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def strategy_sensitivity(
    predictions: Iterable[Mapping[str, object]],
    *,
    model_version: str,
    edges: tuple[float, ...] = (0.02, 0.04, 0.06),
) -> list[dict[str, object]]:
    rows = [
        row for row in predictions if str(row.get("model_version")) == model_version
    ]
    return [
        run_backtest(
            rows,
            StrategyParameters(
                name=f"{model_version}_1x2_edge_{edge:.2f}",
                market="1X2",
                minimum_edge=edge,
            ),
            hypotheses_tested=len(edges),
        )
        for edge in edges
    ]
