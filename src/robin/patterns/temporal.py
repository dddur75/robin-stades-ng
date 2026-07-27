"""Registre point-in-time et contrôles adversariaux anti-fuite."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from robin.patterns.contracts import PatternCondition


@dataclass(frozen=True)
class FeatureAvailability:
    feature: str
    source: str
    availability: str
    window: str
    delay: str
    allowed_markets: frozenset[str]
    live_usable: bool


MARKETS = frozenset(
    {
        "1X2_HOME",
        "1X2_DRAW",
        "1X2_AWAY",
        "TOTAL_OVER_2_5",
        "TOTAL_UNDER_2_5",
    }
)


def _market_feature(name: str) -> FeatureAvailability:
    return FeatureAvailability(
        feature=name,
        source="FOOTBALL_DATA",
        availability="HISTORICAL_PRICE_CATEGORY",
        window="SINGLE_OBSERVED_PRICE",
        delay="SOURCE_CLASS_ONLY_NO_INTRADAY_TIMESTAMP",
        allowed_markets=MARKETS,
        live_usable=False,
    )


FEATURE_REGISTRY: dict[str, FeatureAvailability] = {
    "competition": FeatureAvailability(
        "competition",
        "API_FOOTBALL_FIXTURE",
        "FIXTURE_PUBLICATION",
        "STATIC",
        "NONE",
        MARKETS,
        True,
    ),
    "season": FeatureAvailability(
        "season",
        "API_FOOTBALL_FIXTURE",
        "FIXTURE_PUBLICATION",
        "STATIC",
        "NONE",
        MARKETS,
        True,
    ),
    "price_type": _market_feature("price_type"),
    "totals_price_type": _market_feature("totals_price_type"),
    "bookmaker_1x2": _market_feature("bookmaker_1x2"),
    "bookmaker_totals": _market_feature("bookmaker_totals"),
    "odds_home": _market_feature("odds_home"),
    "odds_draw": _market_feature("odds_draw"),
    "odds_away": _market_feature("odds_away"),
    "odds_over_25": _market_feature("odds_over_25"),
    "odds_under_25": _market_feature("odds_under_25"),
    "market_margin_1x2": _market_feature("market_margin_1x2"),
    "market_margin_totals": _market_feature("market_margin_totals"),
    "de_vig_home": _market_feature("de_vig_home"),
    "de_vig_draw": _market_feature("de_vig_draw"),
    "de_vig_away": _market_feature("de_vig_away"),
    "de_vig_over_25": _market_feature("de_vig_over_25"),
    "de_vig_under_25": _market_feature("de_vig_under_25"),
}

FORBIDDEN_EXACT = frozenset(
    {
        "home_goals",
        "away_goals",
        "full_time_result",
        "target",
        "label",
        "winner",
        "loser",
        "profit_units",
        "settlement",
    }
)
FORBIDDEN_FRAGMENTS = (
    "winner_",
    "loser_",
    "future_",
    "post_match",
    "final_score",
    "result_",
)


class LeakageError(ValueError):
    pass


def validate_conditions(
    conditions: Iterable[PatternCondition],
    *,
    market: str,
    require_live_usable: bool = False,
) -> None:
    for condition in conditions:
        folded = condition.feature.casefold()
        if folded in FORBIDDEN_EXACT or any(
            fragment in folded for fragment in FORBIDDEN_FRAGMENTS
        ):
            raise LeakageError(f"LEAKAGE_REJECTED:{condition.feature}")
        feature = FEATURE_REGISTRY.get(condition.feature)
        if feature is None:
            raise LeakageError(f"UNKNOWN_FEATURE_AVAILABILITY:{condition.feature}")
        if market not in feature.allowed_markets:
            raise LeakageError(
                f"FEATURE_NOT_ALLOWED_FOR_MARKET:{condition.feature}:{market}"
            )
        if require_live_usable and not feature.live_usable:
            raise LeakageError(
                f"FEATURE_NOT_LIVE_POINT_IN_TIME:{condition.feature}"
            )


def validate_observation_cutoff(
    row: Mapping[str, object],
    *,
    cutoff_at: datetime,
    observed_at_field: str = "observed_at",
) -> None:
    observed = row.get(observed_at_field)
    if not isinstance(observed, datetime):
        raise LeakageError("OBSERVATION_TIMESTAMP_REQUIRED")
    if observed > cutoff_at:
        raise LeakageError("ODDS_AFTER_CUTOFF")


def rolling_history_before_target(
    rows: Iterable[Mapping[str, object]],
    *,
    target_time: datetime,
    time_field: str,
) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    for row in rows:
        observed = row.get(time_field)
        if not isinstance(observed, datetime):
            raise LeakageError("ROLLING_TIMESTAMP_REQUIRED")
        if observed < target_time:
            output.append(row)
    return sorted(output, key=lambda item: cast(datetime, item[time_field]))


def adversarial_leakage_scan(columns: Iterable[str]) -> list[str]:
    rejected: list[str] = []
    for column in columns:
        folded = column.casefold()
        if folded in FORBIDDEN_EXACT or any(
            fragment in folded for fragment in FORBIDDEN_FRAGMENTS
        ):
            rejected.append(column)
    return sorted(set(rejected))
