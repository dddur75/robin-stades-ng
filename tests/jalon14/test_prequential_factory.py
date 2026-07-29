from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    freeze_feature_snapshot,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    ModelRole,
    ModelScope,
    ModelStatus,
    PredictionMarket,
    PredictionStatus,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_factory import (
    PrequentialLearningFactory,
    initial_model_versions,
)
from robin.prospective_observatory.prequential_metrics import (
    aggregate_metrics,
    segmented_metrics,
)
from robin.prospective_observatory.prequential_storage import (
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
)
from robin.prospective_observatory.prequential_training import (
    TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT,
    eligible_training_examples,
)

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)
CONTRACT = {
    "version": "prequential-features-v1",
    "missing_value_policy": "NULL_WITH_PROVENANCE",
}
CONTRACT_HASH = canonical_sha256(CONTRACT)


def _factory() -> tuple[
    PrequentialLearningFactory,
    PrequentialArtifactRepository,
]:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    models = initial_model_versions(
        created_at=NOW - timedelta(days=100),
        feature_contract_hash=CONTRACT_HASH,
        code_revision="test-revision",
    )
    return (
        PrequentialLearningFactory(
            artifact_repository=repository,
            models=models,
        ),
        repository,
    )


def _reference(factory: PrequentialLearningFactory) -> object:
    return next(
        model
        for model in factory.models.values()
        if model.role is ModelRole.REFERENCE
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )


def _snapshot(
    factory: PrequentialLearningFactory,
    repository: PrequentialArtifactRepository,
    *,
    fixture_id: str,
    fixture_record_id: str,
    competition: str,
    market: PredictionMarket = PredictionMarket.ONE_X_TWO,
    cutoff_name: CutoffName = CutoffName.H_2,
    cutoff_at: datetime = NOW,
) -> str:
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {"source": "TEST", "margin": 0.05}
    values["team"] = {"home": "home", "away": "away"}
    availability["market"] = True
    availability["team"] = True
    observed_at = cutoff_at - timedelta(minutes=10)
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        created_at=observed_at,
        feature_contract_version="prequential-features-v1",
        feature_contract=CONTRACT,
        values=values,
        availability=availability,
        provenance={
            family: {
                "source": "TEST",
                "observed_at": observed_at.isoformat(),
            }
            for family in ("market", "team")
        },
        quality={"status": "TEST_ONLY"},
        code_revision="test-revision",
    )
    factory.register_snapshot(snapshot)
    return snapshot.snapshot_id


def _freeze_reference(
    factory: PrequentialLearningFactory,
    *,
    fixture_id: str,
    fixture_record_id: str,
    competition: str,
    snapshot_id: str | None,
    market: PredictionMarket = PredictionMarket.ONE_X_TWO,
    cutoff_name: CutoffName = CutoffName.H_2,
    cutoff_at: datetime = NOW,
    predicted_at: datetime | None = None,
    odds: dict[str, float] | None = None,
    no_odds: bool = False,
    required_gates: tuple[str, ...] = ("fixture",),
    gate_statuses: dict[str, bool] | None = None,
) -> object:
    reference = _reference(factory)
    return factory.forecast(
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        kickoff_at=cutoff_at + timedelta(hours=2),
        predicted_at=predicted_at or cutoff_at - timedelta(minutes=5),
        model_id=reference.model_id,
        model_version=reference.version,
        feature_snapshot_id=snapshot_id,
        gate_statuses=gate_statuses or {"fixture": True},
        required_gates=required_gates,
        decimal_odds=None
        if no_odds
        else (
            odds
            if odds is not None
            else (
                {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4}
                if market is PredictionMarket.ONE_X_TWO
                else {"OVER": 1.95, "UNDER": 1.95}
            )
        ),
        odds_snapshot_id="odds-test",
        challenger_probabilities=None,
        code_revision="test-revision",
    )


def _settle(
    factory: PrequentialLearningFactory,
    *,
    fixture_id: str,
    fixture_record_id: str,
    competition: str,
    kickoff_at: datetime,
    version: int = 1,
    corrected: bool = False,
) -> tuple[object, tuple[object, ...], bool]:
    result = VerifiedFixtureResult(
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        kickoff_at=kickoff_at,
        status=(
            FixtureResultStatus.CORRECTED
            if corrected
            else FixtureResultStatus.FINISHED
        ),
        verified_at=kickoff_at + timedelta(hours=2 + version),
        home_goals=version,
        away_goals=0,
        result_version=version,
        source_hash=canonical_sha256(
            {"fixture_id": fixture_id, "version": version}
        ),
    )
    return factory.settle(
        result,
        settled_at=kickoff_at + timedelta(hours=2 + version),
    )


def test_initial_registry_prepares_reference_and_challenger_for_all_scopes() -> None:
    factory, _ = _factory()
    scopes_by_role = {
        role: {
            model.scope
            for model in factory.models.values()
            if model.role is role
        }
        for role in ModelRole
    }
    assert scopes_by_role[ModelRole.REFERENCE] == set(ModelScope)
    assert scopes_by_role[ModelRole.CHALLENGER] == set(ModelScope)
    assert all(
        model.status is ModelStatus.INSUFFICIENT_TRAINING_SUPPORT
        for model in factory.models.values()
        if model.role is ModelRole.CHALLENGER
    )


@pytest.mark.parametrize("market", tuple(PredictionMarket))
@pytest.mark.parametrize("cutoff_name", tuple(CutoffName))
def test_prediction_before_cutoff_is_frozen_for_both_markets_and_cutoffs(
    market: PredictionMarket,
    cutoff_name: CutoffName,
) -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-1",
        fixture_record_id="record-1",
        competition="Ligue 1",
        market=market,
        cutoff_name=cutoff_name,
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-1",
        fixture_record_id="record-1",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
        market=market,
        cutoff_name=cutoff_name,
    )
    assert prediction.status is PredictionStatus.FROZEN
    assert prediction.predicted_at <= prediction.cutoff_at < prediction.kickoff_at
    assert prediction.payload_hash == prediction.payload_hash


def test_late_prediction_and_missing_gate_are_append_only_rejections() -> None:
    factory, _ = _factory()
    late = _freeze_reference(
        factory,
        fixture_id="fixture-late",
        fixture_record_id="record-late",
        competition="Ligue 1",
        snapshot_id=None,
        predicted_at=NOW + timedelta(seconds=1),
    )
    missing = _freeze_reference(
        factory,
        fixture_id="fixture-gate",
        fixture_record_id="record-gate",
        competition="Ligue 1",
        snapshot_id=None,
        required_gates=("fixture", "market"),
        gate_statuses={"fixture": True, "market": False},
    )
    assert late.status is PredictionStatus.REJECTED_LATE
    assert missing.status is PredictionStatus.REJECTED_MISSING_GATE
    assert late.probabilities == missing.probabilities == {}


def test_absent_market_is_not_invented() -> None:
    factory, _ = _factory()
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-no-odds",
        fixture_record_id="record-no-odds",
        competition="Ligue 1",
        snapshot_id=None,
        no_odds=True,
    )
    assert prediction.status is PredictionStatus.NO_ODDS_REFERENCE
    assert prediction.market_probabilities is None


def test_frozen_prediction_cannot_be_replaced_or_mutated() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-immutable",
        fixture_record_id="record-immutable",
        competition="Ligue 1",
    )
    first = _freeze_reference(
        factory,
        fixture_id="fixture-immutable",
        fixture_record_id="record-immutable",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    retry = _freeze_reference(
        factory,
        fixture_id="fixture-immutable",
        fixture_record_id="record-immutable",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    assert retry == first
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_PREDICTION_IMMUTABILITY_CONFLICT",
    ):
        _freeze_reference(
            factory,
            fixture_id="fixture-immutable",
            fixture_record_id="record-immutable",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            odds={"HOME": 1.9, "DRAW": 3.5, "AWAY": 4.2},
        )
    with pytest.raises(Exception):  # frozen dataclass
        first.status = PredictionStatus.VOID


def test_missing_feature_is_null_and_post_cutoff_provenance_is_rejected() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-missing",
        fixture_record_id="record-missing",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    assert snapshot.values["players"] is None
    assert snapshot.missingness["players"] is True
    assert snapshot.status == "FROZEN"
    assert snapshot.payload_hash == snapshot.snapshot_hash
    with pytest.raises(ValueError, match="FEATURE_PROVENANCE_AFTER_CUTOFF"):
        replace(
            snapshot,
            provenance={
                **snapshot.provenance,
                "market": {
                    "source": "TEST",
                    "observed_at": (NOW + timedelta(seconds=1)).isoformat(),
                },
            },
        )


def test_non_final_result_is_rejected_and_final_settlement_is_idempotent() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-settle"
    record_id = "record-settle"
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id=fixture_id,
        fixture_record_id=record_id,
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=record_id,
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    with pytest.raises(ValueError, match="PREQUENTIAL_RESULT_NOT_FINAL"):
        factory.settle(
            VerifiedFixtureResult(
                fixture_record_id=record_id,
                fixture_id=fixture_id,
                competition="Ligue 1",
                kickoff_at=prediction.kickoff_at,
                status=FixtureResultStatus.POSTPONED,
                verified_at=prediction.kickoff_at + timedelta(hours=1),
                source_hash="a" * 64,
            ),
            settled_at=prediction.kickoff_at + timedelta(hours=1),
        )
    first, first_scores, inserted = _settle(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=record_id,
        competition="Ligue 1",
        kickoff_at=prediction.kickoff_at,
    )
    second, second_scores, retried = _settle(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=record_id,
        competition="Ligue 1",
        kickoff_at=prediction.kickoff_at,
    )
    assert inserted is True
    assert retried is False
    assert second == first
    assert second_scores == first_scores
    assert len(first_scores) == 1


def test_void_and_corrected_results_create_new_linked_versions() -> None:
    factory, repository = _factory()
    for suffix in ("void", "corrected"):
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=f"fixture-{suffix}",
            fixture_record_id=f"record-{suffix}",
            competition="Premier League",
        )
        _freeze_reference(
            factory,
            fixture_id=f"fixture-{suffix}",
            fixture_record_id=f"record-{suffix}",
            competition="Premier League",
            snapshot_id=snapshot_id,
        )
    void_result = VerifiedFixtureResult(
        fixture_record_id="record-void",
        fixture_id="fixture-void",
        competition="Premier League",
        kickoff_at=NOW + timedelta(hours=2),
        status=FixtureResultStatus.CANCELLED,
        verified_at=NOW + timedelta(hours=3),
        source_hash="b" * 64,
    )
    void_settlement, void_scores, _ = factory.settle(
        void_result,
        settled_at=NOW + timedelta(hours=3),
    )
    assert void_settlement.effective_status is PredictionStatus.VOID
    assert void_scores == ()

    first, _, _ = _settle(
        factory,
        fixture_id="fixture-corrected",
        fixture_record_id="record-corrected",
        competition="Premier League",
        kickoff_at=NOW + timedelta(hours=2),
    )
    corrected, _, inserted = _settle(
        factory,
        fixture_id="fixture-corrected",
        fixture_record_id="record-corrected",
        competition="Premier League",
        kickoff_at=NOW + timedelta(hours=2),
        version=2,
        corrected=True,
    )
    assert inserted is True
    assert corrected.supersedes_id == first.settlement_id


def test_training_before_settlement_and_under_threshold_are_deferred() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-training",
        fixture_record_id="record-training",
        competition="Ligue 1",
    )
    _freeze_reference(
        factory,
        fixture_id="fixture-training",
        fixture_record_id="record-training",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    decision = factory.train(
        model_id="challenger-global_five_leagues",
        previous_version="untrained-v1",
        training_cutoff=NOW + timedelta(days=1),
        code_revision="test-revision",
    )
    assert decision.status == TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT
    assert decision.eligible_fixtures == 0
    assert decision.next_model is None


def test_training_dataset_contains_only_settled_past_and_two_markets() -> None:
    factory, repository = _factory()
    for index, market in enumerate(PredictionMarket):
        fixture_id = f"fixture-history-{index}"
        record_id = f"record-history-{index}"
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            market=market,
            cutoff_at=NOW - timedelta(days=2),
        )
        prediction = _freeze_reference(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            market=market,
            cutoff_at=NOW - timedelta(days=2),
        )
        _settle(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            kickoff_at=prediction.kickoff_at,
        )
    examples = eligible_training_examples(
        settlements=factory.settlements.settlements,
        snapshots=factory.features.snapshots,
        training_cutoff=NOW + timedelta(days=1),
    )
    assert {example.market for example in examples} == {
        market.value for market in PredictionMarket
    }
    assert all(example.settled_at < NOW + timedelta(days=1) for example in examples)


def test_eligible_training_creates_new_challenger_and_blocks_promotion() -> None:
    factory, repository = _factory()
    reference = _reference(factory)
    for index in range(30):
        competition = "Ligue 1" if index % 2 == 0 else "Premier League"
        fixture_id = f"fixture-support-{index}"
        record_id = f"record-support-{index}"
        cutoff = NOW - timedelta(days=60 - index)
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition=competition,
            cutoff_at=cutoff,
        )
        prediction = _freeze_reference(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition=competition,
            snapshot_id=snapshot_id,
            cutoff_at=cutoff,
        )
        _settle(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition=competition,
            kickoff_at=prediction.kickoff_at,
        )
    decision = factory.train(
        model_id="challenger-global_five_leagues",
        previous_version="untrained-v1",
        training_cutoff=NOW + timedelta(days=1),
        code_revision="test-revision",
    )
    assert decision.status == "CHALLENGER_VERSION_CREATED"
    assert decision.eligible_fixtures == 30
    assert decision.represented_leagues == 2
    assert decision.next_model is not None
    assert decision.next_model.parent_version == "untrained-v1"
    assert decision.manifest is not None
    assert decision.manifest.training_metrics["fixtures"] == 30
    assert factory.models[(reference.model_id, reference.version)] == reference
    assert factory.ledger.audit()["promotion_status"] == "PROMOTION_LOCKED"
    assert any(
        event.kind.value == "PROMOTION_BLOCKED"
        for event in factory.ledger.events
    )


def test_metrics_are_segmented_without_roi() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-metrics",
        fixture_record_id="record-metrics",
        competition="Serie A",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-metrics",
        fixture_record_id="record-metrics",
        competition="Serie A",
        snapshot_id=snapshot_id,
    )
    _settle(
        factory,
        fixture_id="fixture-metrics",
        fixture_record_id="record-metrics",
        competition="Serie A",
        kickoff_at=prediction.kickoff_at,
    )
    aggregate = aggregate_metrics(
        predictions=factory.predictions.predictions,
        scores=factory.settlements.scores,
    )
    segments = segmented_metrics(
        predictions=factory.predictions.predictions,
        scores=factory.settlements.scores,
    )
    assert aggregate["support"] == 1
    assert aggregate["log_loss"] is not None
    assert "roi" not in aggregate
    assert segments[0]["competition"] == "Serie A"
    assert segments[0]["month"] == NOW.strftime("%Y-%m")
