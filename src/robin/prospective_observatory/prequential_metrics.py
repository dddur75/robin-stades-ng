"""Proper scoring rules and segmented prequential metric snapshots."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Iterable, Mapping

from robin.prospective_observatory.prequential_contracts import (
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    PredictionMarket,
    PredictionScore,
    PredictionStatus,
)

EPSILON = 1e-15


def settlement_outcome(
    settlement: FixtureSettlementRecord,
    market: PredictionMarket,
) -> str | None:
    if settlement.effective_status is PredictionStatus.VOID:
        return None
    result = settlement.result
    if result.home_goals is None or result.away_goals is None:
        raise ValueError("SETTLED_SCORE_REQUIRED")
    if market is PredictionMarket.ONE_X_TWO:
        if result.home_goals > result.away_goals:
            return "HOME"
        if result.home_goals < result.away_goals:
            return "AWAY"
        return "DRAW"
    return "OVER" if result.home_goals + result.away_goals > 2.5 else "UNDER"


def score_prediction(
    prediction: FrozenPredictionRecord,
    settlement: FixtureSettlementRecord,
    *,
    scored_at: datetime,
    score_id: str,
    reference_log_loss: float | None = None,
) -> PredictionScore | None:
    if prediction.status is not PredictionStatus.FROZEN:
        raise ValueError("ONLY_FROZEN_PREDICTIONS_CAN_BE_SCORED")
    if prediction.fixture_id != settlement.result.fixture_id:
        raise ValueError("PREDICTION_SETTLEMENT_FIXTURE_MISMATCH")
    outcome = settlement_outcome(settlement, prediction.market)
    if outcome is None:
        return None
    probability = max(
        min(prediction.probabilities[outcome], 1.0 - EPSILON),
        EPSILON,
    )
    log_loss = -math.log(probability)
    selections = tuple(prediction.probabilities)
    brier = sum(
        (
            prediction.probabilities[selection]
            - (1.0 if selection == outcome else 0.0)
        )
        ** 2
        for selection in selections
    ) / len(selections)
    predicted_selection = max(
        prediction.probabilities,
        key=prediction.probabilities.__getitem__,
    )
    return PredictionScore(
        score_id=score_id,
        prediction_id=prediction.prediction_id,
        settlement_id=settlement.settlement_id,
        fixture_id=prediction.fixture_id,
        competition=prediction.competition,
        market=prediction.market,
        cutoff_name=prediction.cutoff_name,
        model_id=prediction.model_id,
        model_version=prediction.model_version,
        scored_at=scored_at,
        outcome=outcome,
        log_loss=log_loss,
        brier_score=brier,
        accurate=predicted_selection == outcome,
        reference_log_loss_delta=(
            log_loss - reference_log_loss
            if reference_log_loss is not None
            else None
        ),
    )


def _calibration_error(
    rows: Iterable[tuple[float, bool]],
    *,
    bins: int = 10,
) -> float | None:
    values = tuple(rows)
    if not values:
        return None
    grouped: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for probability, observed in values:
        index = min(int(probability * bins), bins - 1)
        grouped[index].append((probability, observed))
    total = len(values)
    return sum(
        len(items)
        / total
        * abs(
            sum(probability for probability, _ in items) / len(items)
            - sum(1.0 if observed else 0.0 for _, observed in items) / len(items)
        )
        for items in grouped.values()
    )


def aggregate_metrics(
    *,
    predictions: Iterable[FrozenPredictionRecord],
    scores: Iterable[PredictionScore],
    missingness_by_prediction: Mapping[str, Mapping[str, bool]] | None = None,
) -> dict[str, object]:
    frozen = {
        prediction.prediction_id: prediction
        for prediction in predictions
        if prediction.status is PredictionStatus.FROZEN
    }
    scored = tuple(score for score in scores if score.prediction_id in frozen)
    calibration_rows: list[tuple[float, bool]] = []
    for score in scored:
        prediction = frozen[score.prediction_id]
        for selection, probability in prediction.probabilities.items():
            calibration_rows.append((probability, selection == score.outcome))
    missing_values = [
        missing
        for prediction_id in frozen
        for missing in (missingness_by_prediction or {}).get(
            prediction_id,
            {},
        ).values()
    ]
    return {
        "support": len(scored),
        "log_loss": (
            sum(score.log_loss for score in scored) / len(scored)
            if scored
            else None
        ),
        "brier_score": (
            sum(score.brier_score for score in scored) / len(scored)
            if scored
            else None
        ),
        "calibration_error": _calibration_error(calibration_rows),
        "accuracy_descriptive": (
            sum(1 for score in scored if score.accurate) / len(scored)
            if scored
            else None
        ),
        "coverage": len(scored) / len(frozen) if frozen else 0.0,
        "missingness": (
            sum(1 for missing in missing_values if missing) / len(missing_values)
            if missing_values
            else None
        ),
        "reference_log_loss_delta": (
            sum(
                value
                for score in scored
                if (value := score.reference_log_loss_delta) is not None
            )
            / sum(
                1
                for score in scored
                if score.reference_log_loss_delta is not None
            )
            if any(score.reference_log_loss_delta is not None for score in scored)
            else None
        ),
    }


def segmented_metrics(
    *,
    predictions: Iterable[FrozenPredictionRecord],
    scores: Iterable[PredictionScore],
    missingness_by_prediction: Mapping[str, Mapping[str, bool]] | None = None,
) -> tuple[dict[str, object], ...]:
    prediction_rows = tuple(predictions)
    by_id = {prediction.prediction_id: prediction for prediction in prediction_rows}
    groups: dict[
        tuple[str, str, str, str, str, str],
        list[PredictionScore],
    ] = defaultdict(list)
    for score in scores:
        prediction = by_id.get(score.prediction_id)
        if prediction is None:
            continue
        month = score.scored_at.strftime("%Y-%m")
        key = (
            prediction.competition,
            prediction.market.value,
            prediction.cutoff_name.value,
            prediction.model_id,
            prediction.model_version,
            month,
        )
        groups[key].append(score)
    output: list[dict[str, object]] = []
    for key, group_scores in sorted(groups.items()):
        competition, market, cutoff, model_id, model_version, month = key
        prediction_ids = {score.prediction_id for score in group_scores}
        group_predictions = tuple(
            prediction
            for prediction in prediction_rows
            if prediction.prediction_id in prediction_ids
        )
        output.append(
            {
                "competition": competition,
                "market": market,
                "cutoff": cutoff,
                "model_id": model_id,
                "model_version": model_version,
                "month": month,
                "metrics": aggregate_metrics(
                    predictions=group_predictions,
                    scores=group_scores,
                    missingness_by_prediction=missingness_by_prediction,
                ),
            }
        )
    return tuple(output)


__all__ = [
    "aggregate_metrics",
    "score_prediction",
    "segmented_metrics",
    "settlement_outcome",
]
