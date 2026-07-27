"""Paired market-residual scoring for bounded Jalon 11 models."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from robin.deep_football.datasets import exact_pairing


@dataclass(frozen=True, slots=True)
class PairedScore:
    matches: int
    reference_log_loss: float
    challenger_log_loss: float
    delta_log_loss: float
    reference_brier: float
    challenger_brier: float
    delta_brier: float


def devig_1x2(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
) -> tuple[float, float, float]:
    odds = (float(odds_home), float(odds_draw), float(odds_away))
    if any(not math.isfinite(value) or value <= 1.0 for value in odds):
        raise ValueError("INVALID_1X2_ODDS")
    implied = tuple(1.0 / value for value in odds)
    total = sum(implied)
    return (
        implied[0] / total,
        implied[1] / total,
        implied[2] / total,
    )


def _probabilities(row: Mapping[str, object]) -> tuple[float, float, float]:
    values = (
        float(str(row["p_home"])),
        float(str(row["p_draw"])),
        float(str(row["p_away"])),
    )
    if (
        any(not math.isfinite(value) or value <= 0.0 for value in values)
        or abs(sum(values) - 1.0) > 1e-6
    ):
        raise ValueError("INVALID_PROBABILITY_VECTOR")
    return values


def _label(row: Mapping[str, object]) -> int:
    value = row.get("outcome")
    if value not in {"HOME", "DRAW", "AWAY"}:
        raise ValueError("OUTCOME_REQUIRED")
    return {"HOME": 0, "DRAW": 1, "AWAY": 2}[str(value)]


def _log_loss(probabilities: tuple[float, ...], label: int) -> float:
    return -math.log(max(probabilities[label], 1e-12))


def _brier(probabilities: tuple[float, ...], label: int) -> float:
    return sum(
        (value - (1.0 if position == label else 0.0)) ** 2
        for position, value in enumerate(probabilities)
    ) / 3.0


def paired_score(
    reference: Sequence[Mapping[str, object]],
    challenger: Sequence[Mapping[str, object]],
) -> PairedScore:
    paired = exact_pairing(reference, challenger)
    reference_log: list[float] = []
    challenger_log: list[float] = []
    reference_brier: list[float] = []
    challenger_brier: list[float] = []
    for left, right in zip(paired.left, paired.right, strict=True):
        left_label = _label(left)
        right_label = _label(right)
        if left_label != right_label:
            raise ValueError("PAIRED_OUTCOME_MISMATCH")
        left_probabilities = _probabilities(left)
        right_probabilities = _probabilities(right)
        reference_log.append(_log_loss(left_probabilities, left_label))
        challenger_log.append(_log_loss(right_probabilities, right_label))
        reference_brier.append(_brier(left_probabilities, left_label))
        challenger_brier.append(_brier(right_probabilities, right_label))
    if not reference_log:
        raise ValueError("PAIRED_SAMPLE_EMPTY")
    reference_log_loss = sum(reference_log) / len(reference_log)
    challenger_log_loss = sum(challenger_log) / len(challenger_log)
    reference_brier_score = sum(reference_brier) / len(reference_brier)
    challenger_brier_score = sum(challenger_brier) / len(challenger_brier)
    return PairedScore(
        matches=len(reference_log),
        reference_log_loss=reference_log_loss,
        challenger_log_loss=challenger_log_loss,
        delta_log_loss=challenger_log_loss - reference_log_loss,
        reference_brier=reference_brier_score,
        challenger_brier=challenger_brier_score,
        delta_brier=challenger_brier_score - reference_brier_score,
    )


def flat_stake_roi(
    odds: Sequence[float | None],
    wins: Sequence[bool | None],
) -> dict[str, float | int]:
    if len(odds) != len(wins):
        raise ValueError("ROI_LENGTH_MISMATCH")
    returns: list[float] = []
    for price, won in zip(odds, wins, strict=True):
        if price is None or won is None:
            continue
        if not math.isfinite(price) or price <= 1.0:
            raise ValueError("ROI_REQUIRES_OBSERVED_VALID_ODDS")
        returns.append(price - 1.0 if won else -1.0)
    if not returns:
        return {"bets": 0, "profit_units": 0.0, "roi": 0.0}
    profit = sum(returns)
    return {
        "bets": len(returns),
        "profit_units": profit,
        "roi": profit / len(returns),
    }
