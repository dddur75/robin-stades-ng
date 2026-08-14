"""Backtest V3 borné, avec bankroll fictive et protection anti-data-mining."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from robin.market_math import (
    DevigInputError,
    DevigMethod,
    decide_market,
    kernel_versions,
    performance_summary,
    settle_profit,
    stake_units,
)


class TemporalBacktestMode(StrEnum):
    REQUIRE_POINT_IN_TIME = "REQUIRE_POINT_IN_TIME"
    LOCAL_DETERMINISTIC_FIXTURE_ONLY = "LOCAL_DETERMINISTIC_FIXTURE_ONLY"


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


def _kickoff_sort_key(row: Mapping[str, object]) -> tuple[datetime, str]:
    raw = str(row.get("kickoff_at", ""))
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("BACKTEST_KICKOFF_INVALID") from error
    if value.tzinfo is None:
        raise ValueError("BACKTEST_KICKOFF_TIMEZONE_REQUIRED")
    return value.astimezone(UTC), str(row.get("fixture_id", ""))


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
    devig_method: DevigMethod | str,
    hypotheses_tested: int = 1,
    temporal_mode: TemporalBacktestMode | str = TemporalBacktestMode.REQUIRE_POINT_IN_TIME,
) -> dict[str, object]:
    """Exécuter un backtest sur un seul segment explicitement OOS."""

    starting_bankroll = 100.0
    bankroll = starting_bankroll
    peak = bankroll
    maximum_drawdown = 0.0
    loss_streak = 0
    maximum_loss_streak = 0
    profits: list[float] = []
    stakes: list[float] = []
    details: list[dict[str, object]] = []
    invalid_market_reasons: dict[str, int] = {}
    temporal_rejection_reasons: dict[str, int] = {}
    temporal_admissible_rows = 0
    try:
        validated_temporal_mode = TemporalBacktestMode(temporal_mode)
    except ValueError as error:
        raise ValueError("BACKTEST_TEMPORAL_MODE_INVALID") from error
    for row in sorted(predictions, key=_kickoff_sort_key):
        if row.get("origin") != "OOS HISTORICAL":
            raise ValueError("BACKTEST_SEGMENT_MIXED")
        if validated_temporal_mode is TemporalBacktestMode.REQUIRE_POINT_IN_TIME:
            # Historical rows currently carry only self-declared scalar hashes.
            # Until an adapter can re-read and bind the feature, odds, and model
            # artifacts, none of those rows may be promoted to point-in-time.
            reason = "POINT_IN_TIME_RECEIPT_VERIFIER_REQUIRED"
            temporal_rejection_reasons[reason] = (
                temporal_rejection_reasons.get(reason, 0) + 1
            )
            continue
        temporal_admissible_rows += 1
        outcome_labels: tuple[str, ...]
        if parameters.market == "1X2":
            outcome_labels = ("HOME", "DRAW", "AWAY")
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
            outcome_labels = ("OVER", "UNDER")
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
        if target not in range(len(outcome_labels)):
            raise ValueError("BACKTEST_TARGET_OUT_OF_RANGE")
        try:
            decision = decide_market(
                odds,
                probabilities,
                method=devig_method,
                threshold=parameters.minimum_edge,
                minimum_probability=parameters.minimum_probability,
                outcome_labels=outcome_labels,
            )
        except DevigInputError as error:
            invalid_market_reasons[error.code] = (
                invalid_market_reasons.get(error.code, 0) + 1
            )
            continue
        if not decision.accepted:
            continue
        selection = decision.selected_index
        probability = decision.model_probabilities[selection]
        price_value = odds[selection]
        if price_value is None:
            raise AssertionError("DEVIG_ACCEPTED_MISSING_SELECTED_ODDS")
        price = float(price_value)
        edge = decision.selected_edge
        stake = stake_units(
            probability=probability,
            odds=price,
            bankroll_units=bankroll,
            staking=parameters.staking,
            kelly_fraction=parameters.kelly_fraction,
            stake_cap_units=parameters.stake_cap,
        )
        if stake <= 0.0:
            continue
        profit = settle_profit(
            stake_units=stake,
            odds=price,
            won=selection == target,
        )
        bankroll += profit
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, peak - bankroll)
        loss_streak = loss_streak + 1 if profit < 0 else 0
        maximum_loss_streak = max(maximum_loss_streak, loss_streak)
        profits.append(profit)
        stakes.append(stake)
        details.append(
            {
                "fixture_id": row.get("fixture_id"),
                "selection": selection,
                "probability": probability,
                "market_probability": decision.devig.fair_probabilities[selection],
                "odds": price,
                "edge": edge,
                "stake": stake,
                "profit": profit,
                "bankroll": bankroll,
                "segment": "BLIND_OOS",
                "devig_method": decision.devig.method.value,
                "devig_effective_method": decision.devig.effective_method.value,
                "devig_fallback_reason": decision.devig.fallback_reason,
                "devig_version": decision.devig.version,
                "devig_definition_hash": decision.devig.definition_hash,
                "point_in_time_status": (
                    "LOCAL_DETERMINISTIC_FIXTURE_ONLY"
                    if validated_temporal_mode
                    is TemporalBacktestMode.LOCAL_DETERMINISTIC_FIXTURE_ONLY
                    else "POINT_IN_TIME_NOT_PROVEN"
                ),
            }
        )
    interval = _confidence_interval(profits)
    adjusted_p = _adjusted_p_value(profits, hypotheses_tested)
    performance = performance_summary(
        starting_bankroll_units=starting_bankroll,
        stakes=stakes,
        profits=profits,
    )
    status = (
        "REJECTED"
        if interval[1] is not None and float(interval[1]) < 0.0
        else "INCONCLUSIVE"
    )
    return {
        "backtest_version": "api_football_backtest_v3",
        **kernel_versions(devig_method),
        "strategy": parameters.name,
        "market": parameters.market,
        "parameters": {
            "minimum_edge": parameters.minimum_edge,
            "minimum_probability": parameters.minimum_probability,
            "staking": parameters.staking,
            "kelly_fraction": parameters.kelly_fraction,
            "stake_cap": parameters.stake_cap,
            "devig_method": kernel_versions(devig_method)["devig_method"],
        },
        "segment": "BLIND_OOS",
        "invalid_market_rows": sum(invalid_market_reasons.values()),
        "invalid_market_reasons": invalid_market_reasons,
        "temporal_validation_mode": validated_temporal_mode.value,
        "temporal_admissible_rows": temporal_admissible_rows,
        "temporal_rejected_rows": sum(temporal_rejection_reasons.values()),
        "temporal_rejection_reasons": temporal_rejection_reasons,
        "point_in_time_status": (
            "LOCAL_DETERMINISTIC_FIXTURE_ONLY"
            if validated_temporal_mode
            is TemporalBacktestMode.LOCAL_DETERMINISTIC_FIXTURE_ONLY
            else "POINT_IN_TIME_NOT_PROVEN"
        ),
        **performance,
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
    devig_method: DevigMethod | str,
    edges: tuple[float, ...] = (0.02, 0.04, 0.06),
    temporal_mode: TemporalBacktestMode | str = TemporalBacktestMode.REQUIRE_POINT_IN_TIME,
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
            devig_method=devig_method,
            hypotheses_tested=len(edges),
            temporal_mode=temporal_mode,
        )
        for edge in edges
    ]


__all__ = [
    "StrategyParameters",
    "TemporalBacktestMode",
    "run_backtest",
    "strategy_sensitivity",
]
