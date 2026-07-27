"""Moteur déterministe de règles football, borné et sans appel fournisseur."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from robin.patterns.contracts import (
    ConditionOperator,
    PatternCondition,
    rule_hash,
)
from robin.patterns.temporal import validate_conditions

MARKET_COLUMNS: dict[str, tuple[str, str]] = {
    "1X2_HOME": ("odds_home", "HOME"),
    "1X2_DRAW": ("odds_draw", "DRAW"),
    "1X2_AWAY": ("odds_away", "AWAY"),
    "TOTAL_OVER_2_5": ("odds_over_25", "OVER"),
    "TOTAL_UNDER_2_5": ("odds_under_25", "UNDER"),
}


@dataclass(frozen=True)
class Rule:
    market: str
    selection: str
    conditions: tuple[PatternCondition, ...]

    @property
    def digest(self) -> str:
        return rule_hash(
            market=self.market,
            selection=self.selection,
            conditions=list(self.conditions),
        )


@dataclass(frozen=True)
class FixedStakeMetrics:
    bets: int
    wins: int
    losses: int
    turnover_units: float
    profit_units: float
    roi: float
    hit_rate: float
    average_odds: float
    median_odds: float
    max_drawdown_units: float
    max_losing_streak: int
    profit_factor: float | None
    final_bankroll: float


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def condition_matches(
    row: Mapping[str, object],
    condition: PatternCondition,
) -> bool:
    actual = row.get(condition.feature)
    expected = condition.value
    operator = condition.operator
    if operator == ConditionOperator.EQ:
        return bool(actual == expected)
    if operator == ConditionOperator.NE:
        return bool(actual != expected)
    if operator == ConditionOperator.IN:
        return isinstance(expected, list | tuple | set) and actual in expected
    actual_number = _number(actual)
    if actual_number is None:
        return False
    if operator == ConditionOperator.BETWEEN:
        if not isinstance(expected, list | tuple) or len(expected) != 2:
            return False
        lower = _number(expected[0])
        upper = _number(expected[1])
        return (
            lower is not None
            and upper is not None
            and lower <= actual_number < upper
        )
    expected_number = _number(expected)
    if expected_number is None:
        return False
    if operator == ConditionOperator.LT:
        return actual_number < expected_number
    if operator == ConditionOperator.LE:
        return actual_number <= expected_number
    if operator == ConditionOperator.GT:
        return actual_number > expected_number
    if operator == ConditionOperator.GE:
        return actual_number >= expected_number
    return False


def apply_rule(
    rows: Iterable[Mapping[str, object]],
    rule: Rule,
) -> list[Mapping[str, object]]:
    validate_conditions(rule.conditions, market=rule.market)
    return [
        row
        for row in rows
        if all(condition_matches(row, condition) for condition in rule.conditions)
    ]


def observed_odds(row: Mapping[str, object], market: str) -> float | None:
    try:
        odds_column, _ = MARKET_COLUMNS[market]
    except KeyError as exc:
        raise ValueError(f"MARKET_UNAVAILABLE:{market}") from exc
    odds = _number(row.get(odds_column))
    if odds is None or odds <= 1.0:
        return None
    observed_status = row.get("observed_time_status")
    if observed_status != "SOURCE_PRICE_CLASS_ONLY":
        return None
    price_column = "totals_price_type" if market.startswith("TOTAL_") else "price_type"
    margin_column = (
        "market_margin_totals" if market.startswith("TOTAL_") else "market_margin_1x2"
    )
    price_type = row.get(price_column)
    margin = _number(row.get(margin_column))
    if price_type not in {
        "HISTORICAL_CLOSING_MARKET",
        "HISTORICAL_PRE_CLOSING_MARKET",
    }:
        return None
    if margin is None or not 0.0 < margin < 0.25:
        return None
    return odds


def market_won(row: Mapping[str, object], market: str) -> bool | None:
    home = _number(row.get("home_goals"))
    away = _number(row.get("away_goals"))
    if home is None or away is None:
        return None
    if market == "1X2_HOME":
        return home > away
    if market == "1X2_DRAW":
        return home == away
    if market == "1X2_AWAY":
        return home < away
    if market == "TOTAL_OVER_2_5":
        return home + away > 2.5
    if market == "TOTAL_UNDER_2_5":
        return home + away < 2.5
    raise ValueError(f"MARKET_UNAVAILABLE:{market}")


def returns_for_rule(
    rows: Iterable[Mapping[str, object]],
    rule: Rule,
) -> tuple[list[float], list[float], list[str]]:
    returns: list[float] = []
    odds_values: list[float] = []
    groups: list[str] = []
    for row in apply_rule(rows, rule):
        odds = observed_odds(row, rule.market)
        won = market_won(row, rule.market)
        if odds is None or won is None:
            continue
        returns.append(odds - 1.0 if won else -1.0)
        odds_values.append(odds)
        groups.append(str(row.get("match_date") or row.get("fixture_id") or "UNKNOWN"))
    return returns, odds_values, groups


def fixed_stake_metrics(
    returns: Sequence[float],
    odds: Sequence[float],
    *,
    initial_bankroll: float = 1000.0,
) -> FixedStakeMetrics:
    if len(returns) != len(odds):
        raise ValueError("RETURNS_ODDS_LENGTH_MISMATCH")
    if initial_bankroll <= 0:
        raise ValueError("INITIAL_BANKROLL_MUST_BE_POSITIVE")
    if not returns:
        return FixedStakeMetrics(
            bets=0,
            wins=0,
            losses=0,
            turnover_units=0.0,
            profit_units=0.0,
            roi=0.0,
            hit_rate=0.0,
            average_odds=0.0,
            median_odds=0.0,
            max_drawdown_units=0.0,
            max_losing_streak=0,
            profit_factor=None,
            final_bankroll=initial_bankroll,
        )
    bankroll = initial_bankroll
    peak = initial_bankroll
    max_drawdown = 0.0
    losing_streak = 0
    max_losing_streak = 0
    gross_wins = 0.0
    gross_losses = 0.0
    wins = 0
    for result in returns:
        bankroll += result
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, peak - bankroll)
        if result > 0:
            wins += 1
            gross_wins += result
            losing_streak = 0
        else:
            gross_losses += abs(result)
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)
    profit = float(sum(returns))
    bets = len(returns)
    return FixedStakeMetrics(
        bets=bets,
        wins=wins,
        losses=bets - wins,
        turnover_units=float(bets),
        profit_units=profit,
        roi=profit / bets,
        hit_rate=wins / bets,
        average_odds=sum(odds) / len(odds),
        median_odds=float(median(odds)),
        max_drawdown_units=max_drawdown,
        max_losing_streak=max_losing_streak,
        profit_factor=(gross_wins / gross_losses if gross_losses else None),
        final_bankroll=bankroll,
    )


def canonical_selection_ids(
    rows: Iterable[Mapping[str, object]],
    rule: Rule,
) -> frozenset[str]:
    selected: set[str] = set()
    for row in apply_rule(rows, rule):
        if observed_odds(row, rule.market) is not None:
            selected.add(str(row.get("fixture_id")))
    return frozenset(selected)


def jaccard_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def is_subrule(simple: Rule, complex_rule: Rule) -> bool:
    if simple.market != complex_rule.market or simple.selection != complex_rule.selection:
        return False
    simple_conditions = {
        condition.model_dump_json(exclude_none=False)
        for condition in simple.conditions
    }
    complex_conditions = {
        condition.model_dump_json(exclude_none=False)
        for condition in complex_rule.conditions
    }
    return simple_conditions < complex_conditions


def dominated_by_simpler_rule(
    *,
    candidate: Rule,
    candidate_roi: float,
    candidate_ids: Iterable[str],
    accepted: Iterable[tuple[Rule, float, Iterable[str]]],
    minimum_roi_improvement: float = 0.01,
    overlap_threshold: float = 0.90,
) -> str | None:
    for simpler, simpler_roi, simpler_ids in accepted:
        if not is_subrule(simpler, candidate):
            continue
        overlap = jaccard_similarity(candidate_ids, simpler_ids)
        if overlap >= overlap_threshold and (
            candidate_roi - simpler_roi < minimum_roi_improvement
        ):
            return "DOMINATED"
    return None
