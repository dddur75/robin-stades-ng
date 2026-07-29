from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from robin.prospective_observatory.prequential import (
    FrozenPrediction,
    MatchSettlement,
    ModelRole,
    ModelScope,
    ModelVersion,
    PrequentialEventKind,
    PrequentialLedger,
    ShadowAction,
)

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _model(
    scope: ModelScope,
    role: ModelRole,
    *,
    version: str = "v1",
    created_at: datetime = NOW,
) -> ModelVersion:
    return ModelVersion(
        model_id=f"{role.value.casefold()}-{scope.value.casefold()}",
        scope=scope,
        role=role,
        version=version,
        artifact_sha256=HASH_A if version == "v1" else HASH_D,
        created_at=created_at,
    )


def _ledger() -> tuple[PrequentialLedger, ModelVersion, ModelVersion]:
    references = tuple(_model(scope, ModelRole.REFERENCE) for scope in ModelScope)
    challenger = _model(ModelScope.GLOBAL_FIVE_LEAGUES, ModelRole.CHALLENGER)
    reference = next(
        model
        for model in references
        if model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    return PrequentialLedger((*references, challenger)), reference, challenger


def _prediction(model: ModelVersion) -> FrozenPrediction:
    return FrozenPrediction(
        fixture_id="api-football:42",
        competition="Premier League",
        model_id=model.model_id,
        model_version=model.version,
        features_sha256=HASH_A,
        cutoff_at=NOW + timedelta(hours=1),
        frozen_at=NOW,
        kickoff_at=NOW + timedelta(hours=2),
        odds_sha256=HASH_B,
        shadow_action=ShadowAction.NO_BET,
        prediction_payload_sha256=HASH_C,
    )


def test_reference_and_challenger_models_cover_global_and_each_league() -> None:
    ledger, _, _ = _ledger()
    assert ledger.audit() == {
        "status": "PREQUENTIAL_LEDGER_VERIFIED",
        "events": 0,
        "head_hash": "0" * 64,
        "reference_updates": 0,
        "promotions": 0,
    }


def test_training_before_settlement_is_rejected() -> None:
    ledger, _, challenger = _ledger()
    ledger.freeze_prediction(_prediction(challenger))
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_TRAINING_BEFORE_SETTLEMENT_REJECTED",
    ):
        ledger.update_challenger(
            fixture_id="api-football:42",
            model_id=challenger.model_id,
            previous_version="v1",
            next_model=_model(
                ModelScope.GLOBAL_FIVE_LEAGUES,
                ModelRole.CHALLENGER,
                version="v2",
            ),
            training_dataset_sha256=HASH_D,
            updated_at=NOW + timedelta(hours=3),
        )


def test_result_cannot_be_used_before_kickoff_or_before_prediction() -> None:
    ledger, _, challenger = _ledger()
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SETTLEMENT_WITHOUT_PREDICTION",
    ):
        ledger.settle(
            MatchSettlement(
                fixture_id="api-football:42",
                result_sha256=HASH_D,
                settled_at=NOW + timedelta(hours=3),
            )
        )
    ledger.freeze_prediction(_prediction(challenger))
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SETTLEMENT_BEFORE_KICKOFF_REJECTED",
    ):
        ledger.settle(
            MatchSettlement(
                fixture_id="api-football:42",
                result_sha256=HASH_D,
                settled_at=NOW + timedelta(minutes=90),
            )
        )


def test_settlement_makes_only_challenger_eligible_and_reference_unchanged() -> None:
    ledger, reference, challenger = _ledger()
    ledger.freeze_prediction(_prediction(reference))
    ledger.freeze_prediction(_prediction(challenger))
    settlement_events = ledger.settle(
        MatchSettlement(
            fixture_id="api-football:42",
            result_sha256=HASH_D,
            settled_at=NOW + timedelta(hours=3),
        )
    )
    kinds = [event.kind for event in settlement_events]
    assert kinds.count(PrequentialEventKind.MATCH_SETTLED) == 2
    assert PrequentialEventKind.REFERENCE_UNCHANGED in kinds
    assert PrequentialEventKind.CHALLENGER_TRAINING_ELIGIBLE in kinds
    update = ledger.update_challenger(
        fixture_id="api-football:42",
        model_id=challenger.model_id,
        previous_version="v1",
        next_model=_model(
            ModelScope.GLOBAL_FIVE_LEAGUES,
            ModelRole.CHALLENGER,
            version="v2",
            created_at=NOW + timedelta(hours=4),
        ),
        training_dataset_sha256=HASH_D,
        updated_at=NOW + timedelta(hours=4),
    )
    assert update.kind is PrequentialEventKind.CHALLENGER_UPDATED
    audit = ledger.audit()
    assert audit["status"] == "PREQUENTIAL_LEDGER_VERIFIED"
    assert audit["reference_updates"] == 0
    assert audit["promotions"] == 0


def test_frozen_prediction_is_idempotent_and_immutable() -> None:
    ledger, _, challenger = _ledger()
    prediction = _prediction(challenger)
    first = ledger.freeze_prediction(prediction)
    second = ledger.freeze_prediction(prediction)
    assert first == second
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_PREDICTION_IMMUTABILITY_CONFLICT",
    ):
        ledger.freeze_prediction(
            replace(prediction, prediction_payload_sha256=HASH_D)
        )


def test_prediction_rejects_future_feature_cutoff_and_wrong_league_scope() -> None:
    ledger, _, _ = _ledger()
    with pytest.raises(ValueError, match="PREQUENTIAL_PREDICTION_INVALID"):
        replace(
            _prediction(
                _model(
                    ModelScope.PREMIER_LEAGUE,
                    ModelRole.REFERENCE,
                )
            ),
            cutoff_at=NOW - timedelta(minutes=1),
        )
    league_model = _model(
        ModelScope.PREMIER_LEAGUE,
        ModelRole.REFERENCE,
    )
    with pytest.raises(ValueError, match="PREQUENTIAL_MODEL_SCOPE_MISMATCH"):
        ledger.freeze_prediction(
            replace(_prediction(league_model), competition="Liga")
        )


def test_challenger_version_cannot_predate_settlement() -> None:
    ledger, _, challenger = _ledger()
    ledger.freeze_prediction(_prediction(challenger))
    ledger.settle(
        MatchSettlement(
            fixture_id="api-football:42",
            result_sha256=HASH_D,
            settled_at=NOW + timedelta(hours=3),
        )
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_CHALLENGER_UPDATE_INVALID",
    ):
        ledger.update_challenger(
            fixture_id="api-football:42",
            model_id=challenger.model_id,
            previous_version="v1",
            next_model=_model(
                ModelScope.GLOBAL_FIVE_LEAGUES,
                ModelRole.CHALLENGER,
                version="v2",
                created_at=NOW,
            ),
            training_dataset_sha256=HASH_D,
            updated_at=NOW + timedelta(hours=4),
        )
