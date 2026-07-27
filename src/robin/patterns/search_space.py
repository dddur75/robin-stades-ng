"""Espace de recherche préenregistré, compact et déterministe."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from robin.patterns.contracts import ConditionOperator, PatternCondition
from robin.patterns.engine import MARKET_COLUMNS, Rule

ODDS_BANDS: tuple[tuple[float, float], ...] = (
    (1.20, 1.60),
    (1.60, 2.00),
    (2.00, 2.50),
    (2.50, 3.25),
    (3.25, 5.00),
)
MARGIN_LIMITS: tuple[float, ...] = (0.06, 0.08, 0.10)
SUPPORTED_PRICE_TYPES = (
    "HISTORICAL_CLOSING_MARKET",
    "HISTORICAL_PRE_CLOSING_MARKET",
)


def _condition(
    feature: str,
    operator: ConditionOperator,
    value: object,
) -> PatternCondition:
    return PatternCondition(
        feature=feature,
        operator=operator,
        value=value,
        source="FOOTBALL_DATA",
        available_at="HISTORICAL_PRICE_CATEGORY",
    )


def generate_rules(
    rows: Iterable[Mapping[str, object]],
    *,
    include_two_conditions: bool = True,
    include_three_conditions: bool = True,
) -> list[Rule]:
    """Génère un univers borné; aucune valeur n'est choisie après lecture du ROI."""

    materialized = list(rows)
    competitions = sorted(
        {
            str(row["competition"])
            for row in materialized
            if row.get("competition") is not None
        }
    )
    rules: dict[str, Rule] = {}
    for market, (odds_column, selection) in MARKET_COLUMNS.items():
        margin_column = (
            "market_margin_totals" if market.startswith("TOTAL_") else "market_margin_1x2"
        )
        price_column = "totals_price_type" if market.startswith("TOTAL_") else "price_type"
        odds_conditions = [
            _condition(odds_column, ConditionOperator.BETWEEN, list(band))
            for band in ODDS_BANDS
        ]
        margin_conditions = [
            _condition(margin_column, ConditionOperator.LE, limit)
            for limit in MARGIN_LIMITS
        ]
        price_conditions = [
            _condition(price_column, ConditionOperator.EQ, price_type)
            for price_type in SUPPORTED_PRICE_TYPES
        ]
        competition_conditions = [
            PatternCondition(
                feature="competition",
                operator=ConditionOperator.EQ,
                value=competition,
                source="API_FOOTBALL_FIXTURE",
                available_at="FIXTURE_PUBLICATION",
            )
            for competition in competitions
        ]
        single = (
            odds_conditions
            + margin_conditions
            + price_conditions
            + competition_conditions
        )
        for conditions in single:
            rule = Rule(market, selection, (conditions,))
            rules[rule.digest] = rule
        if include_two_conditions:
            pairs = [
                (odds_condition, extra)
                for odds_condition in odds_conditions
                for extra in margin_conditions + price_conditions + competition_conditions
            ]
            for pair in pairs:
                rule = Rule(market, selection, pair)
                rules[rule.digest] = rule
        if include_three_conditions:
            triples = [
                (odds_condition, margin_condition, competition_condition)
                for odds_condition in odds_conditions
                for margin_condition in margin_conditions
                for competition_condition in competition_conditions
            ]
            for triple in triples:
                rule = Rule(market, selection, triple)
                rules[rule.digest] = rule
    return sorted(rules.values(), key=lambda rule: rule.digest)
