"""Idempotent settlement of frozen predictions from verified final results."""

from __future__ import annotations

from datetime import datetime

from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.prequential_contracts import (
    FixtureResultStatus,
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    PredictionScore,
    PredictionStatus,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_metrics import score_prediction

FINAL_SCORE_STATUSES = {
    FixtureResultStatus.FINISHED,
    FixtureResultStatus.CORRECTED,
}
FINAL_VOID_STATUSES = {
    FixtureResultStatus.CANCELLED,
    FixtureResultStatus.ABANDONED,
}


class SettlementRegistry:
    def __init__(self) -> None:
        self._settlements_by_id: dict[str, FixtureSettlementRecord] = {}
        self._versions_by_fixture: dict[str, list[FixtureSettlementRecord]] = {}
        self._scores: dict[tuple[str, str], PredictionScore] = {}

    @property
    def settlements(self) -> tuple[FixtureSettlementRecord, ...]:
        return tuple(self._settlements_by_id.values())

    @property
    def scores(self) -> tuple[PredictionScore, ...]:
        return tuple(self._scores.values())

    def latest(self, fixture_id: str) -> FixtureSettlementRecord | None:
        versions = self._versions_by_fixture.get(fixture_id, [])
        return versions[-1] if versions else None

    def restore(
        self,
        settlement: FixtureSettlementRecord,
        scores: tuple[PredictionScore, ...] = (),
    ) -> None:
        existing = self._settlements_by_id.get(settlement.settlement_id)
        if existing is not None:
            if existing != settlement:
                raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_CONFLICT")
            return
        latest = self.latest(settlement.result.fixture_id)
        if latest is None and settlement.supersedes_id is not None:
            raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_PARENT_MISSING")
        if latest is not None and settlement.supersedes_id != latest.settlement_id:
            raise ValueError("PREQUENTIAL_SETTLEMENT_RESTORE_CHAIN_INVALID")
        self._settlements_by_id[settlement.settlement_id] = settlement
        self._versions_by_fixture.setdefault(
            settlement.result.fixture_id,
            [],
        ).append(settlement)
        for score in scores:
            if score.settlement_id != settlement.settlement_id:
                raise ValueError("PREQUENTIAL_SCORE_RESTORE_SETTLEMENT_MISMATCH")
            self._scores[(score.prediction_id, score.settlement_id)] = score

    def settle(
        self,
        result: VerifiedFixtureResult,
        *,
        predictions: tuple[FrozenPredictionRecord, ...],
        settled_at: datetime,
    ) -> tuple[FixtureSettlementRecord, tuple[PredictionScore, ...], bool]:
        if result.status in {
            FixtureResultStatus.SCHEDULED,
            FixtureResultStatus.IN_PLAY,
            FixtureResultStatus.POSTPONED,
        }:
            raise ValueError("PREQUENTIAL_RESULT_NOT_FINAL")
        if result.status not in FINAL_SCORE_STATUSES | FINAL_VOID_STATUSES:
            raise ValueError("PREQUENTIAL_RESULT_STATUS_UNSUPPORTED")
        matching = tuple(
            prediction
            for prediction in predictions
            if prediction.fixture_id == result.fixture_id
            and prediction.status is PredictionStatus.FROZEN
        )
        if not matching:
            raise ValueError("PREQUENTIAL_SETTLEMENT_WITHOUT_FROZEN_PREDICTION")
        latest = self.latest(result.fixture_id)
        if latest is not None and latest.result.result_hash == result.result_hash:
            existing_scores = tuple(
                score
                for (prediction_id, settlement_id), score in self._scores.items()
                if settlement_id == latest.settlement_id
                and any(
                    prediction.prediction_id == prediction_id
                    for prediction in matching
                )
            )
            return latest, existing_scores, False
        if latest is not None:
            if result.result_version <= latest.result.result_version:
                raise ValueError("PREQUENTIAL_RESULT_CORRECTION_VERSION_INVALID")
            if result.status is not FixtureResultStatus.CORRECTED:
                raise ValueError("PREQUENTIAL_RESULT_CORRECTION_STATUS_REQUIRED")
        effective = (
            PredictionStatus.SETTLED
            if result.status in FINAL_SCORE_STATUSES
            else PredictionStatus.VOID
        )
        settlement_identity = canonical_sha256(
            {
                "fixture_id": result.fixture_id,
                "result_hash": result.result_hash,
                "supersedes_id": latest.settlement_id if latest else None,
            }
        )
        settlement = FixtureSettlementRecord(
            settlement_id=f"settlement-{settlement_identity}",
            result=result,
            settled_at=settled_at,
            effective_status=effective,
            supersedes_id=latest.settlement_id if latest else None,
        )
        self._settlements_by_id[settlement.settlement_id] = settlement
        self._versions_by_fixture.setdefault(result.fixture_id, []).append(settlement)
        scores: list[PredictionScore] = []
        if effective is PredictionStatus.SETTLED:
            reference_losses: dict[tuple[str, str], float] = {}
            provisional: list[tuple[FrozenPredictionRecord, PredictionScore]] = []
            for prediction in matching:
                score_identity = canonical_sha256(
                    {
                        "prediction_id": prediction.prediction_id,
                        "settlement_id": settlement.settlement_id,
                    }
                )
                score = score_prediction(
                    prediction,
                    settlement,
                    scored_at=settled_at,
                    score_id=f"score-{score_identity}",
                )
                if score is None:
                    continue
                provisional.append((prediction, score))
                if prediction.model_id.startswith("reference-"):
                    reference_losses[
                        (prediction.market.value, prediction.cutoff_name.value)
                    ] = score.log_loss
            for prediction, score in provisional:
                reference_loss = reference_losses.get(
                    (prediction.market.value, prediction.cutoff_name.value)
                )
                if (
                    reference_loss is not None
                    and not prediction.model_id.startswith("reference-")
                ):
                    score = PredictionScore(
                        score_id=score.score_id,
                        prediction_id=score.prediction_id,
                        settlement_id=score.settlement_id,
                        fixture_id=score.fixture_id,
                        competition=score.competition,
                        market=score.market,
                        cutoff_name=score.cutoff_name,
                        model_id=score.model_id,
                        model_version=score.model_version,
                        scored_at=score.scored_at,
                        outcome=score.outcome,
                        log_loss=score.log_loss,
                        brier_score=score.brier_score,
                        accurate=score.accurate,
                        reference_log_loss_delta=score.log_loss - reference_loss,
                    )
                self._scores[(score.prediction_id, settlement.settlement_id)] = score
                scores.append(score)
        return settlement, tuple(scores), True


__all__ = [
    "FINAL_SCORE_STATUSES",
    "FINAL_VOID_STATUSES",
    "SettlementRegistry",
]
