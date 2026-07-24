"""Détection conservatrice des zéros potentiellement artificiels."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from pydantic import BaseModel, ConfigDict

from robin.domain.enums import QualityStatus

DEFAULT_COLUMNS = ("hthg", "htag", "hy", "ay", "hr", "ar", "hc", "ac")
PAIRS = {
    "hthg": "htag",
    "htag": "hthg",
    "hy": "ay",
    "ay": "hy",
    "hr": "ar",
    "ar": "hr",
    "hc": "ac",
    "ac": "hc",
}


class ZeroAuditRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    competition: str
    season: str
    column: str
    rows: int
    zeros: int
    missing: int
    non_zero: int
    zero_rate: float
    min_value: float | None
    median_value: float | None
    max_value: float | None
    artificial_probability: float
    quality_status: QualityStatus
    impact: str


def _probability(
    column: str,
    rows: int,
    zero_rate: float,
    pair_zero_rate: float,
) -> float:
    if rows < 20:
        return 0.2
    pair_all_zero = zero_rate == 1.0 and pair_zero_rate == 1.0
    if pair_all_zero and column in {"hthg", "htag", "hy", "ay", "hc", "ac"}:
        return 0.99
    if pair_all_zero and column in {"hr", "ar"}:
        return 0.75
    if zero_rate >= 0.98 and column not in {"hr", "ar"}:
        return 0.85
    return 0.05


def audit_suspect_zeros(
    frame: pd.DataFrame,
    *,
    provider: str,
    columns: Iterable[str] = DEFAULT_COLUMNS,
) -> list[ZeroAuditRow]:
    required = {"league", "season"}
    if not required.issubset(frame.columns):
        raise ValueError("l'audit exige league et season")
    available = [column for column in columns if column in frame.columns]
    results: list[ZeroAuditRow] = []

    for (competition, season), group in frame.groupby(["league", "season"], dropna=False):
        zero_rates = {
            column: float(group[column].eq(0).mean()) for column in available
        }
        for column in available:
            values = pd.to_numeric(group[column], errors="coerce")
            zeros = int(values.eq(0).sum())
            missing = int(values.isna().sum())
            pair = PAIRS[column]
            probability = _probability(
                column,
                len(group),
                zero_rates[column],
                zero_rates.get(pair, 0.0),
            )
            status = (
                QualityStatus.SUSPECT_ZERO
                if probability >= 0.8
                else QualityStatus.OBSERVED
            )
            results.append(
                ZeroAuditRow(
                    provider=provider,
                    competition=str(competition),
                    season=str(season),
                    column=column,
                    rows=len(group),
                    zeros=zeros,
                    missing=missing,
                    non_zero=int(values.notna().sum() - zeros),
                    zero_rate=zeros / len(group) if len(group) else 0.0,
                    min_value=float(values.min()) if values.notna().any() else None,
                    median_value=(
                        float(values.median()) if values.notna().any() else None
                    ),
                    max_value=float(values.max()) if values.notna().any() else None,
                    artificial_probability=probability,
                    quality_status=status,
                    impact=(
                        "exclure des features et modèles concernés"
                        if status == QualityStatus.SUSPECT_ZERO
                        else "aucun verrou automatique"
                    ),
                )
            )
    return results


def build_value_quality(
    frame: pd.DataFrame,
    audit: Iterable[ZeroAuditRow],
) -> dict[str, pd.Series]:
    """Construire un statut par valeur sans muter les données sources."""
    statuses = {
        column: pd.Series(
            QualityStatus.OBSERVED.value,
            index=frame.index,
            dtype="string",
        )
        for column in DEFAULT_COLUMNS
        if column in frame.columns
    }
    for column, values in statuses.items():
        values.loc[frame[column].isna()] = QualityStatus.MISSING.value
    for row in audit:
        if row.quality_status != QualityStatus.SUSPECT_ZERO:
            continue
        mask = (
            (frame["league"].astype(str) == row.competition)
            & (frame["season"].astype(str) == row.season)
            & frame[row.column].eq(0)
        )
        statuses[row.column].loc[mask] = QualityStatus.SUSPECT_ZERO.value
    return statuses


def values_eligible_for_model(
    values: pd.Series,
    statuses: pd.Series,
) -> pd.Series:
    allowed = {
        QualityStatus.OBSERVED.value,
        QualityStatus.DERIVED.value,
        QualityStatus.CORRECTED.value,
    }
    return values.where(statuses.isin(allowed))
