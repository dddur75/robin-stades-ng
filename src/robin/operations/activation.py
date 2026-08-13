"""Décisions factuelles de provenance, de quota et d'activation live."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from robin.market_math import DevigInputError, DevigMethod, devig_probabilities

WORKFLOW_SUCCESS_NO_DATA = "WORKFLOW_SUCCESS_NO_DATA"
WORKFLOW_SUCCESS_LIVE_DATA = "WORKFLOW_SUCCESS_LIVE_DATA"
WORKFLOW_PARTIAL = "WORKFLOW_PARTIAL"
WORKFLOW_FAILED = "WORKFLOW_FAILED"


def audit_secret_presence(
    environment: Mapping[str, str | None],
    names: Sequence[str],
) -> dict[str, bool]:
    """Retourner uniquement la présence des secrets, jamais leur valeur."""

    return {
        name: bool((environment.get(name) or "").strip())
        for name in names
    }


def workflow_outcome(
    *,
    authenticated: bool,
    records_received: int,
    records_persisted: int,
    failed: bool = False,
) -> str:
    if failed:
        return WORKFLOW_FAILED
    if not authenticated:
        return WORKFLOW_PARTIAL
    if records_received > 0 and records_persisted > 0:
        return WORKFLOW_SUCCESS_LIVE_DATA
    return WORKFLOW_SUCCESS_NO_DATA


def normalized_market_probabilities(
    home_prices: Sequence[float],
    draw_prices: Sequence[float],
    away_prices: Sequence[float],
    *,
    devig_method: DevigMethod | str,
) -> tuple[float, float, float] | None:
    """Calculer une baseline marché dé-viggée à partir de cotes réelles."""

    if not home_prices or not draw_prices or not away_prices:
        return None
    prices = (
        sum(home_prices) / len(home_prices),
        sum(draw_prices) / len(draw_prices),
        sum(away_prices) / len(away_prices),
    )
    if any(price <= 1 for price in prices):
        return None
    try:
        result = devig_probabilities(
            prices,
            method=devig_method,
            outcome_labels=("HOME", "DRAW", "AWAY"),
        )
    except DevigInputError:
        return None
    return result.fair_probabilities


@dataclass(frozen=True)
class QuotaForecast:
    matches_per_month: int
    windows_per_match: int
    credits_per_snapshot: int
    forecast_credits: int
    quota_limit: int
    reserve_credits: int
    usable_credits: int
    headroom_credits: int
    headroom_pct: float
    strategy: str

    def as_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def forecast_monthly_quota(
    *,
    matches_per_month: int,
    windows_per_match: int = 9,
    credits_per_snapshot: int = 2,
    quota_limit: int = 20_000,
    reserve_pct: float = 0.20,
) -> QuotaForecast:
    if not 0 <= reserve_pct < 1:
        raise ValueError("reserve_pct doit être compris entre 0 et 1")
    if min(
        matches_per_month,
        windows_per_match,
        credits_per_snapshot,
        quota_limit,
    ) < 0:
        raise ValueError("les paramètres de quota doivent être positifs")
    reserve = int(quota_limit * reserve_pct)
    usable = quota_limit - reserve
    forecast = matches_per_month * windows_per_match * credits_per_snapshot
    headroom = usable - forecast
    if headroom >= 0:
        strategy = "NINE_WINDOWS_WITH_20_PERCENT_RESERVE"
    else:
        strategy = "ADAPTIVE_NEAREST_WINDOWS"
    return QuotaForecast(
        matches_per_month=matches_per_month,
        windows_per_match=windows_per_match,
        credits_per_snapshot=credits_per_snapshot,
        forecast_credits=forecast,
        quota_limit=quota_limit,
        reserve_credits=reserve,
        usable_credits=usable,
        headroom_credits=headroom,
        headroom_pct=round(headroom / quota_limit, 4) if quota_limit else 0,
        strategy=strategy,
    )
