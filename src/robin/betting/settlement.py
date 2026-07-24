"""Règlement canonique et versionné des marchés initiaux."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from robin.domain.enums import (
    FixtureStatus,
    MarketType,
    Selection,
    SettlementOutcome,
)
from robin.domain.odds import MarketKey


class MatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: FixtureStatus
    home_goals: int | None = Field(default=None, ge=0)
    away_goals: int | None = Field(default=None, ge=0)
    result_version: int = Field(default=1, ge=1)


class Settlement(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: SettlementOutcome
    settlement_rule_version: str
    result_version: int
    profit_per_unit: Decimal | None
    reason: str


def _won_one_x_two(selection: Selection, home: int, away: int) -> bool:
    return (
        (selection == Selection.HOME and home > away)
        or (selection == Selection.DRAW and home == away)
        or (selection == Selection.AWAY and away > home)
    )

def _won_double_chance(selection: Selection, home: int, away: int) -> bool:
    return (
        (selection == Selection.HOME_OR_DRAW and home >= away)
        or (selection == Selection.HOME_OR_AWAY and home != away)
        or (selection == Selection.DRAW_OR_AWAY and away >= home)
    )


def settle_market(
    market: MarketKey,
    result: MatchResult,
    *,
    odds_decimal: Decimal,
) -> Settlement:
    if result.status in {FixtureStatus.CANCELLED, FixtureStatus.POSTPONED}:
        return Settlement(
            outcome=SettlementOutcome.VOID,
            settlement_rule_version=market.settlement_rule_version,
            result_version=result.result_version,
            profit_per_unit=Decimal("0"),
            reason=f"fixture {result.status.value.lower()}",
        )
    if result.status != FixtureStatus.FINISHED:
        return Settlement(
            outcome=SettlementOutcome.UNSETTLED,
            settlement_rule_version=market.settlement_rule_version,
            result_version=result.result_version,
            profit_per_unit=None,
            reason="résultat final indisponible",
        )
    if result.home_goals is None or result.away_goals is None:
        raise ValueError("un match terminé exige ses deux scores")

    home, away = result.home_goals, result.away_goals
    push = False
    if market.market_type == MarketType.ONE_X_TWO:
        won = _won_one_x_two(market.selection, home, away)
    elif market.market_type == MarketType.DOUBLE_CHANCE:
        won = _won_double_chance(market.selection, home, away)
    elif market.market_type == MarketType.BOTH_TEAMS_TO_SCORE:
        both = home > 0 and away > 0
        won = (
            market.selection == Selection.YES and both
        ) or (market.selection == Selection.NO and not both)
    elif market.market_type == MarketType.TOTAL_GOALS:
        if market.line_value is None:
            raise ValueError("ligne absente")
        total = Decimal(home + away)
        push = total == market.line_value
        won = (
            market.selection == Selection.OVER and total > market.line_value
        ) or (
            market.selection == Selection.UNDER and total < market.line_value
        )
    else:
        raise ValueError(f"marché non géré: {market.market_type}")

    if push:
        outcome = SettlementOutcome.PUSH
        profit = Decimal("0")
    elif won:
        outcome = SettlementOutcome.WON
        profit = odds_decimal - Decimal("1")
    else:
        outcome = SettlementOutcome.LOST
        profit = Decimal("-1")
    return Settlement(
        outcome=outcome,
        settlement_rule_version=market.settlement_rule_version,
        result_version=result.result_version,
        profit_per_unit=profit,
        reason="règle canonique appliquée",
    )
