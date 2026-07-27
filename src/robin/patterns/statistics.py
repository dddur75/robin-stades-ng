"""Deterministic statistical primitives for Jalon 10 pattern research.

The functions in this module are deliberately independent from providers and
storage.  They operate on explicit, already point-in-time inputs so research
runs can be replayed without network access.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

DEFAULT_SEED = 10_010
DEFAULT_BOOTSTRAP_ITERATIONS = 2_000
DEFAULT_PERMUTATIONS = 1_000
MIN_BOOTSTRAP_ITERATIONS = 1_000
MIN_PERMUTATIONS = 100

Alternative = Literal["greater", "less", "two-sided"]
LabelT = TypeVar("LabelT")


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Confidence interval for an arithmetic mean from a cluster bootstrap."""

    estimate: float
    lower: float
    upper: float
    confidence: float
    iterations: int
    seed: int
    groups: int


@dataclass(frozen=True, slots=True)
class MultipleTestingResult:
    """Benjamini-Hochberg decisions in the original hypothesis order."""

    q_values: tuple[float, ...]
    rejected: tuple[bool, ...]
    alpha: float
    hypotheses: int


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One expanding-window fold with strictly earlier training periods."""

    fold_index: int
    train_periods: tuple[int, ...]
    test_period: int
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PermutationTestResult:
    """Monte Carlo permutation result with a finite-sample corrected p-value."""

    observed_statistic: float
    null_mean: float
    p_value: float
    extreme_count: int
    permutations: int
    seed: int
    alternative: Alternative


@dataclass(frozen=True, slots=True)
class FlatStakeMetrics:
    """Financial measures for a chronologically ordered fixed-stake series."""

    bets: int
    settled_bets: int
    wins: int
    losses: int
    voids: int
    stake_per_bet: float
    total_staked_units: float
    turnover_units: float
    profit_units: float
    roi: float
    hit_rate: float | None
    average_odds: float
    median_odds: float
    max_drawdown_units: float
    max_losing_streak: int
    gross_profit_units: float
    gross_loss_units: float
    profit_factor: float | None
    starting_bankroll_units: float
    ending_bankroll_units: float


@dataclass(frozen=True, slots=True)
class SupportAssessment:
    """A preregisterable minimum-support gate."""

    observations: int
    distinct_groups: int
    minimum_observations: int
    minimum_groups: int
    sufficient: bool
    status: Literal["SUFFICIENT_SUPPORT", "INSUFFICIENT_SUPPORT"]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PerfectPerformanceAssessment:
    """Red-team assessment for a suspiciously frictionless result."""

    suspicious: bool
    status: Literal[
        "PERFORMANCE_NOT_PERFECT",
        "SUSPICIOUS_PERFECT_PERFORMANCE",
    ]
    reasons: tuple[str, ...]


def _finite_values(values: Sequence[float], *, name: str) -> tuple[float, ...]:
    converted = tuple(float(value) for value in values)
    if not converted:
        raise ValueError(f"{name}_EMPTY")
    if not all(math.isfinite(value) for value in converted):
        raise ValueError(f"{name}_NON_FINITE")
    return converted


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated quantile from an already sorted sample."""

    if not sorted_values:
        raise ValueError("QUANTILE_EMPTY")
    position = probability * (len(sorted_values) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return float(sorted_values[lower_index])
    weight = position - lower_index
    lower = float(sorted_values[lower_index])
    upper = float(sorted_values[upper_index])
    return lower + (upper - lower) * weight


def grouped_bootstrap_mean(
    values: Sequence[float],
    groups: Sequence[str],
    *,
    confidence: float = 0.95,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> BootstrapResult:
    """Bootstrap whole groups and estimate an interval for the record-level mean.

    A sampled group contributes all its records.  This preserves dependence
    within a fixture-day, round, team, or other cluster selected by the caller.
    """

    numeric = _finite_values(values, name="BOOTSTRAP_VALUES")
    if len(numeric) != len(groups):
        raise ValueError("BOOTSTRAP_LENGTH_MISMATCH")
    if not 0.0 < confidence < 1.0:
        raise ValueError("BOOTSTRAP_CONFIDENCE_OUT_OF_RANGE")
    if iterations < MIN_BOOTSTRAP_ITERATIONS:
        raise ValueError("BOOTSTRAP_ITERATIONS_TOO_LOW")

    group_totals: dict[str, float] = {}
    group_sizes: dict[str, int] = {}
    for group, value in zip(groups, numeric, strict=True):
        key = str(group)
        group_totals[key] = group_totals.get(key, 0.0) + value
        group_sizes[key] = group_sizes.get(key, 0) + 1
    keys = sorted(group_totals)
    if len(keys) < 2:
        raise ValueError("BOOTSTRAP_REQUIRES_MULTIPLE_GROUPS")

    # Deterministic simulation is required; this is not a security token.
    generator = random.Random(seed)  # nosec B311
    estimates: list[float] = []
    for _ in range(iterations):
        sampled_total = 0.0
        sampled_size = 0
        for _ in keys:
            sampled_key = keys[generator.randrange(len(keys))]
            sampled_total += group_totals[sampled_key]
            sampled_size += group_sizes[sampled_key]
        estimates.append(sampled_total / sampled_size)

    estimates.sort()
    tail = (1.0 - confidence) / 2.0
    return BootstrapResult(
        estimate=statistics.fmean(numeric),
        lower=_quantile(estimates, tail),
        upper=_quantile(estimates, 1.0 - tail),
        confidence=confidence,
        iterations=iterations,
        seed=seed,
        groups=len(keys),
    )


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Compute monotone Benjamini-Hochberg q-values and FDR decisions."""

    if not 0.0 < alpha < 1.0:
        raise ValueError("FDR_ALPHA_OUT_OF_RANGE")
    values = tuple(float(value) for value in p_values)
    if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
        raise ValueError("INVALID_P_VALUE")
    hypotheses = len(values)
    if hypotheses == 0:
        return MultipleTestingResult((), (), alpha, 0)

    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ordered_q_values = [1.0] * hypotheses
    running_minimum = 1.0
    for position in range(hypotheses - 1, -1, -1):
        rank = position + 1
        adjusted = min(ordered[position][1] * hypotheses / rank, 1.0)
        running_minimum = min(running_minimum, adjusted)
        ordered_q_values[position] = running_minimum

    q_values = [1.0] * hypotheses
    for ordered_position, (original_position, _) in enumerate(ordered):
        q_values[original_position] = ordered_q_values[ordered_position]
    q_value_tuple = tuple(q_values)
    return MultipleTestingResult(
        q_values=q_value_tuple,
        rejected=tuple(value <= alpha for value in q_value_tuple),
        alpha=alpha,
        hypotheses=hypotheses,
    )


def walk_forward_splits(
    periods: Sequence[int],
    *,
    minimum_train_periods: int = 2,
) -> tuple[WalkForwardFold, ...]:
    """Build expanding temporal folds without same-period or future training data."""

    if minimum_train_periods < 1:
        raise ValueError("MINIMUM_TRAIN_PERIODS_TOO_LOW")
    if not periods or any(isinstance(period, bool) for period in periods):
        raise ValueError("INVALID_TEMPORAL_PERIODS")
    normalized = tuple(int(period) for period in periods)
    unique_periods = tuple(sorted(set(normalized)))
    if len(unique_periods) <= minimum_train_periods:
        raise ValueError("INSUFFICIENT_TEMPORAL_PERIODS")

    folds: list[WalkForwardFold] = []
    for test_position in range(minimum_train_periods, len(unique_periods)):
        train_periods = unique_periods[:test_position]
        test_period = unique_periods[test_position]
        train_indices = tuple(
            index
            for index, period in enumerate(normalized)
            if period in train_periods
        )
        test_indices = tuple(
            index
            for index, period in enumerate(normalized)
            if period == test_period
        )
        folds.append(
            WalkForwardFold(
                fold_index=len(folds),
                train_periods=train_periods,
                test_period=test_period,
                train_indices=train_indices,
                test_indices=test_indices,
            )
        )
    return tuple(folds)


def shuffle_labels(
    labels: Sequence[LabelT],
    *,
    seed: int = DEFAULT_SEED,
) -> tuple[LabelT, ...]:
    """Return a deterministic label permutation without mutating the input."""

    shuffled = list(labels)
    # Deterministic simulation is required; this is not a security token.
    random.Random(seed).shuffle(shuffled)  # nosec B311
    return tuple(shuffled)


def permutation_test(
    values: Sequence[float],
    labels: Sequence[int],
    statistic: Callable[[Sequence[float], Sequence[int]], float],
    *,
    permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = DEFAULT_SEED,
    alternative: Alternative = "greater",
) -> PermutationTestResult:
    """Run a deterministic label-permutation control.

    The p-value uses the ``(extreme + 1) / (permutations + 1)`` correction, so
    even a very strong finite Monte Carlo result is never reported as p=0.
    """

    numeric = _finite_values(values, name="PERMUTATION_VALUES")
    normalized_labels = tuple(int(label) for label in labels)
    if len(numeric) != len(normalized_labels) or len(numeric) < 2:
        raise ValueError("INVALID_PERMUTATION_INPUT")
    if len(set(normalized_labels)) < 2:
        raise ValueError("LABELS_NOT_PERMUTABLE")
    if permutations < MIN_PERMUTATIONS:
        raise ValueError("PERMUTATIONS_TOO_LOW")
    if alternative not in ("greater", "less", "two-sided"):
        raise ValueError("INVALID_PERMUTATION_ALTERNATIVE")

    observed = float(statistic(numeric, normalized_labels))
    if not math.isfinite(observed):
        raise ValueError("NON_FINITE_OBSERVED_STATISTIC")
    # Deterministic simulation is required; this is not a security token.
    generator = random.Random(seed)  # nosec B311
    null_statistics: list[float] = []
    for _ in range(permutations):
        permuted = list(normalized_labels)
        generator.shuffle(permuted)
        null_value = float(statistic(numeric, permuted))
        if not math.isfinite(null_value):
            raise ValueError("NON_FINITE_PERMUTATION_STATISTIC")
        null_statistics.append(null_value)

    tolerance = 1e-12
    null_mean = statistics.fmean(null_statistics)
    if alternative == "greater":
        extreme = sum(value >= observed - tolerance for value in null_statistics)
    elif alternative == "less":
        extreme = sum(value <= observed + tolerance for value in null_statistics)
    else:
        extreme = sum(
            abs(value - null_mean) >= abs(observed - null_mean) - tolerance
            for value in null_statistics
        )
    return PermutationTestResult(
        observed_statistic=observed,
        null_mean=null_mean,
        p_value=(extreme + 1) / (permutations + 1),
        extreme_count=extreme,
        permutations=permutations,
        seed=seed,
        alternative=alternative,
    )


def flat_stake_metrics(
    odds: Sequence[float],
    outcomes: Sequence[bool | None],
    *,
    stake_units: float = 1.0,
    starting_bankroll_units: float = 1_000.0,
) -> FlatStakeMetrics:
    """Evaluate observed decimal odds with one fixed stake per recorded bet.

    ``True`` is a win, ``False`` a loss and ``None`` a void.  Voids have zero
    profit but remain part of turnover because the stake was placed and later
    returned.
    """

    prices = _finite_values(odds, name="ODDS")
    if len(prices) != len(outcomes):
        raise ValueError("FLAT_STAKE_LENGTH_MISMATCH")
    if any(price <= 1.0 for price in prices):
        raise ValueError("INVALID_OBSERVED_ODDS")
    stake = float(stake_units)
    initial_bankroll = float(starting_bankroll_units)
    if not math.isfinite(stake) or stake <= 0.0:
        raise ValueError("INVALID_STAKE")
    if not math.isfinite(initial_bankroll) or initial_bankroll < 0.0:
        raise ValueError("INVALID_STARTING_BANKROLL")

    profits: list[float] = []
    wins = 0
    losses = 0
    voids = 0
    losing_streak = 0
    maximum_losing_streak = 0
    bankroll = initial_bankroll
    peak = initial_bankroll
    maximum_drawdown = 0.0
    for price, outcome in zip(prices, outcomes, strict=True):
        if outcome is True:
            profit = stake * (price - 1.0)
            wins += 1
            losing_streak = 0
        elif outcome is False:
            profit = -stake
            losses += 1
            losing_streak += 1
            maximum_losing_streak = max(maximum_losing_streak, losing_streak)
        elif outcome is None:
            profit = 0.0
            voids += 1
            losing_streak = 0
        else:
            raise ValueError("INVALID_BET_OUTCOME")
        profits.append(profit)
        bankroll += profit
        peak = max(peak, bankroll)
        maximum_drawdown = max(maximum_drawdown, peak - bankroll)

    bets = len(profits)
    settled_bets = wins + losses
    total_staked = stake * bets
    total_profit = math.fsum(profits)
    gross_profit = math.fsum(max(profit, 0.0) for profit in profits)
    gross_loss = math.fsum(-min(profit, 0.0) for profit in profits)
    return FlatStakeMetrics(
        bets=bets,
        settled_bets=settled_bets,
        wins=wins,
        losses=losses,
        voids=voids,
        stake_per_bet=stake,
        total_staked_units=total_staked,
        turnover_units=total_staked,
        profit_units=total_profit,
        roi=total_profit / total_staked,
        hit_rate=wins / settled_bets if settled_bets else None,
        average_odds=statistics.fmean(prices),
        median_odds=float(statistics.median(prices)),
        max_drawdown_units=maximum_drawdown,
        max_losing_streak=maximum_losing_streak,
        gross_profit_units=gross_profit,
        gross_loss_units=gross_loss,
        profit_factor=gross_profit / gross_loss if gross_loss > 0.0 else None,
        starting_bankroll_units=initial_bankroll,
        ending_bankroll_units=initial_bankroll + total_profit,
    )


def assess_support(
    observations: int,
    groups: Sequence[str],
    *,
    minimum_observations: int,
    minimum_groups: int,
) -> SupportAssessment:
    """Apply explicit support thresholds without looking at performance."""

    if observations < 0 or len(groups) != observations:
        raise ValueError("INVALID_SUPPORT_INPUT")
    if minimum_observations < 1 or minimum_groups < 1:
        raise ValueError("INVALID_SUPPORT_THRESHOLD")
    distinct_groups = len(set(str(group) for group in groups))
    reasons: list[str] = []
    if observations < minimum_observations:
        reasons.append("OBSERVATIONS_BELOW_MINIMUM")
    if distinct_groups < minimum_groups:
        reasons.append("GROUPS_BELOW_MINIMUM")
    sufficient = not reasons
    return SupportAssessment(
        observations=observations,
        distinct_groups=distinct_groups,
        minimum_observations=minimum_observations,
        minimum_groups=minimum_groups,
        sufficient=sufficient,
        status="SUFFICIENT_SUPPORT" if sufficient else "INSUFFICIENT_SUPPORT",
        reasons=tuple(reasons),
    )


def detect_perfect_performance(
    metrics: FlatStakeMetrics,
    *,
    tolerance: float = 1e-12,
) -> PerfectPerformanceAssessment:
    """Flag positive performance with no observed friction for red-team review."""

    if tolerance < 0.0 or not math.isfinite(tolerance):
        raise ValueError("INVALID_PERFECT_PERFORMANCE_TOLERANCE")
    reasons: list[str] = []
    if (
        metrics.settled_bets > 0
        and metrics.hit_rate is not None
        and metrics.hit_rate >= 1.0 - tolerance
    ):
        reasons.append("PERFECT_HIT_RATE")
    if metrics.profit_units > tolerance and metrics.max_drawdown_units <= tolerance:
        reasons.append("POSITIVE_PROFIT_WITH_ZERO_DRAWDOWN")
    if metrics.gross_profit_units > tolerance and metrics.gross_loss_units <= tolerance:
        reasons.append("NO_OBSERVED_GROSS_LOSS")
    suspicious = bool(reasons)
    return PerfectPerformanceAssessment(
        suspicious=suspicious,
        status=(
            "SUSPICIOUS_PERFECT_PERFORMANCE"
            if suspicious
            else "PERFORMANCE_NOT_PERFECT"
        ),
        reasons=tuple(reasons),
    )


__all__ = [
    "DEFAULT_BOOTSTRAP_ITERATIONS",
    "DEFAULT_PERMUTATIONS",
    "DEFAULT_SEED",
    "BootstrapResult",
    "FlatStakeMetrics",
    "MultipleTestingResult",
    "PerfectPerformanceAssessment",
    "PermutationTestResult",
    "SupportAssessment",
    "WalkForwardFold",
    "assess_support",
    "benjamini_hochberg",
    "detect_perfect_performance",
    "flat_stake_metrics",
    "grouped_bootstrap_mean",
    "permutation_test",
    "shuffle_labels",
    "walk_forward_splits",
]
