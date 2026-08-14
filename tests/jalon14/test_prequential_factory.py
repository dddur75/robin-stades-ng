from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from robin.prospective_observatory.contracts import (
    canonical_json_bytes,
    canonical_sha256,
)
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    freeze_feature_snapshot,
    persist_source_receipt,
    verify_feature_snapshot_artifact,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    PredictionMarket,
    PredictionStatus,
    PrequentialEventKind,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_factory import (
    HashChainedPrequentialLedger,
    PrequentialLearningFactory,
    initial_model_versions,
)
from robin.prospective_observatory.prequential_metrics import (
    aggregate_metrics,
    segmented_metrics,
)
from robin.prospective_observatory.prequential_storage import (
    ArtifactIntegrityError,
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
    StoredArtifact,
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


def _canonical_kickoff(cutoff_name: CutoffName, cutoff_at: datetime) -> datetime:
    minutes = 120 if cutoff_name is CutoffName.H_2 else 1
    return cutoff_at + timedelta(minutes=minutes)


def _persisted_provenance(
    repository: PrequentialArtifactRepository,
    *,
    family: str,
    value: object,
    fixture_id: str,
    fixture_record_id: str,
    observed_at: datetime,
    ingested_at: datetime | None = None,
    marker: str = "default",
) -> dict[str, object]:
    receipt = persist_source_receipt(
        repository,
        source_name="TEST",
        request_identity=f"test:{family}:{marker}",
        payload={
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "family": family,
            "value": value,
        },
        observed_at=observed_at,
        ingested_at=ingested_at or observed_at,
        code_revision="test-revision",
    )
    return {
        **receipt.as_dict(),
        "source": receipt.source_name,
        "source_identity": receipt.storage_identity,
        "observed_at": receipt.robin_first_observed_at.isoformat(),
    }


def _persist_result_observation(
    repository: PrequentialArtifactRepository,
    *,
    fixture_id: str,
    fixture_record_id: str,
    provider_fixture_id: str,
    attempt: int,
    observed_at: datetime,
    record: Mapping[str, object],
    completed_at: datetime | None = None,
) -> StoredArtifact:
    guarded_at = observed_at - timedelta(seconds=1)
    guard_identity = {
        "fixture_id": fixture_id,
        "fixture_record_id": fixture_record_id,
        "provider_fixture_id": provider_fixture_id,
        "attempt": attempt,
        "operation": "VERIFY_FINAL_RESULT",
    }
    guard = repository.put_manifest(
        "provider-call-guards",
        {
            "schema_version": "prequential-provider-call-guard-v1",
            **guard_identity,
            "guard_id": canonical_sha256(guard_identity),
            "guarded_at": guarded_at.isoformat(),
        },
    )
    observation = repository.put_manifest(
        "result-observations",
        {
            "schema_version": "prequential-result-observation-v1",
            "provider": "api-football",
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "provider_fixture_id": provider_fixture_id,
            "attempt": attempt,
            "observed_at": observed_at.isoformat(),
            "availability": "PRESENT",
            "http_status": 200,
            "record": dict(record),
            "provider_calls": 1,
        },
    )
    repository.put_manifest(
        "provider-call-completions",
        {
            "schema_version": "prequential-provider-call-completion-v1",
            "guard_sha256": guard.sha256,
            "observation_sha256": observation.sha256,
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "attempt": attempt,
            "completed_at": (completed_at or observed_at).isoformat(),
        },
    )
    return observation


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
            devig_method="PROPORTIONAL",
        ),
        repository,
    )


def test_prequential_factory_rejects_protocol_not_round_trippable_in_store() -> None:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    models = initial_model_versions(
        created_at=NOW - timedelta(days=100),
        feature_contract_hash=CONTRACT_HASH,
        code_revision="test-revision",
    )
    with pytest.raises(ValueError, match="PREQUENTIAL_DEVIG_PROTOCOL_UNSUPPORTED"):
        PrequentialLearningFactory(
            artifact_repository=repository,
            models=models,
            devig_method="SHIN",
        )


def test_reference_model_rejects_self_declared_artifact_hash() -> None:
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    models = list(
        initial_model_versions(
            created_at=NOW - timedelta(days=100),
            feature_contract_hash=CONTRACT_HASH,
            code_revision="test-revision",
        )
    )
    reference_index = next(
        index
        for index, model in enumerate(models)
        if model.role is ModelRole.REFERENCE
    )
    models[reference_index] = replace(
        models[reference_index],
        artifact_sha256="f" * 64,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REFERENCE_MODEL_ROOT_INVALID",
    ):
        PrequentialLearningFactory(
            artifact_repository=repository,
            models=models,
            devig_method="PROPORTIONAL",
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
    created_at: datetime | None = None,
    fixture_kickoff_at: datetime | None = None,
    fixture_competition: str | None = None,
    provider_fixture_id: str | None = None,
    decimal_odds: dict[str, float] | None = None,
    odds_snapshot_id: str = "odds-test",
) -> str:
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    market_odds = decimal_odds or (
        {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4}
        if market is PredictionMarket.ONE_X_TWO
        else {"OVER": 1.95, "UNDER": 1.95}
    )
    values["market"] = {
        "source": "TEST",
        "margin": 0.05,
        "decimal_odds": market_odds,
    }
    values["team"] = {
        "home": "home",
        "away": "away",
        "kickoff_at": (
            fixture_kickoff_at or _canonical_kickoff(cutoff_name, cutoff_at)
        ).isoformat(),
        "competition": fixture_competition or competition,
        "provider": "api-football",
        "provider_fixture_id": (
            provider_fixture_id or f"provider:{fixture_record_id}"
        ),
    }
    availability["market"] = True
    availability["team"] = True
    observed_at = cutoff_at - timedelta(minutes=10)
    provenance = {
        family: _persisted_provenance(
            repository,
            family=family,
            value=values[family],
            fixture_id=fixture_id,
            fixture_record_id=fixture_record_id,
            observed_at=observed_at,
            marker=f"{fixture_record_id}:{market.value}:{cutoff_name.value}",
        )
        for family in ("market", "team")
    }
    provenance["market"]["odds_snapshot_id"] = odds_snapshot_id
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        created_at=created_at or observed_at,
        feature_contract_version="prequential-features-v1",
        feature_contract=CONTRACT,
        values=values,
        availability=availability,
        provenance=provenance,
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
    kickoff_at: datetime | None = None,
    predicted_at: datetime | None = None,
    odds: dict[str, float] | None = None,
    no_odds: bool = False,
    odds_snapshot_id: str = "odds-test",
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
        kickoff_at=kickoff_at or _canonical_kickoff(cutoff_name, cutoff_at),
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
        odds_snapshot_id=odds_snapshot_id,
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
    verified_at = kickoff_at + timedelta(hours=2 + version)
    provider_fixture_id = f"provider:{fixture_record_id}"
    observation = _persist_result_observation(
        factory.artifact_repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=provider_fixture_id,
        attempt=version,
        observed_at=verified_at,
        record={
            "fixture": {
                "id": provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": version, "away": 0},
        },
    )
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
        verified_at=verified_at,
        home_goals=version,
        away_goals=0,
        result_version=version,
        source_hash=observation.sha256,
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


def test_fixture_gate_cannot_override_missing_team_receipt() -> None:
    factory, repository = _factory()
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "source": "TEST",
        "margin": 0.05,
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
    }
    availability["market"] = True
    observed_at = NOW - timedelta(minutes=10)
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id="record-missing-team-receipt",
        fixture_id="fixture-missing-team-receipt",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=NOW,
        created_at=observed_at,
        feature_contract_version="prequential-features-v1",
        feature_contract=CONTRACT,
        values=values,
        availability=availability,
        provenance={
            "market": _persisted_provenance(
                repository,
                family="market",
                value=values["market"],
                fixture_id="fixture-missing-team-receipt",
                fixture_record_id="record-missing-team-receipt",
                observed_at=observed_at,
                marker="missing-team-receipt",
            )
        },
        quality={"status": "TEAM_RECEIPT_NOT_PROVEN"},
        code_revision="test-revision",
    )
    factory.register_snapshot(snapshot)
    prediction = _freeze_reference(
        factory,
        fixture_id=snapshot.fixture_id,
        fixture_record_id=snapshot.fixture_record_id,
        competition=snapshot.competition,
        snapshot_id=snapshot.snapshot_id,
        gate_statuses={"fixture": True, "market": True},
        required_gates=(),
    )
    assert prediction.status is PredictionStatus.REJECTED_MISSING_GATE
    assert prediction.rejection_reason == "MISSING_GATES:fixture"


def test_required_feature_gate_cannot_override_missing_receipt() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-missing-lineup-receipt",
        fixture_record_id="record-missing-lineup-receipt",
        competition="Ligue 1",
    )

    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-missing-lineup-receipt",
        fixture_record_id="record-missing-lineup-receipt",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
        required_gates=("fixture", "lineup"),
        gate_statuses={"fixture": True, "lineup": True},
    )

    assert prediction.status is PredictionStatus.REJECTED_MISSING_GATE
    assert prediction.rejection_reason == "MISSING_GATES:lineup"


def test_fixture_gate_requires_receipt_bound_exact_kickoff() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-kickoff-receipt",
        fixture_record_id="record-kickoff-receipt",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-kickoff-receipt",
        fixture_record_id="record-kickoff-receipt",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
        kickoff_at=NOW + timedelta(hours=3),
        gate_statuses={"fixture": True},
        required_gates=(),
    )
    assert prediction.status is PredictionStatus.REJECTED_MISSING_GATE
    assert prediction.rejection_reason == "MISSING_GATES:fixture"


def test_fixture_gate_requires_receipt_bound_exact_competition() -> None:
    factory, repository = _factory()
    with pytest.raises(
        ValueError,
        match="AVAILABLE_TEAM_FIXTURE_PROJECTION_INVALID",
    ):
        _snapshot(
            factory,
            repository,
            fixture_id="fixture-competition-receipt",
            fixture_record_id="record-competition-receipt",
            competition="Premier League",
            fixture_competition="Ligue 1",
        )


def test_frozen_prediction_rejects_noncanonical_cutoff_horizon() -> None:
    factory, repository = _factory()
    cutoff_at = NOW + timedelta(minutes=10)
    kickoff_at = NOW + timedelta(hours=2)
    with pytest.raises(
        ValueError,
        match="AVAILABLE_TEAM_FIXTURE_PROJECTION_INVALID",
    ):
        _snapshot(
            factory,
            repository,
            fixture_id="fixture-cutoff-policy",
            fixture_record_id="record-cutoff-policy",
            competition="Ligue 1",
            cutoff_at=cutoff_at,
            fixture_kickoff_at=kickoff_at,
        )


def test_required_lineup_gate_rejects_receipted_empty_projection() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-empty-lineup"
    fixture_record_id = "record-empty-lineup"
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "source": "TEST",
        "margin": 0.05,
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
    }
    values["team"] = {
        "home": "home",
        "away": "away",
        "kickoff_at": (NOW + timedelta(hours=2)).isoformat(),
        "competition": "Ligue 1",
        "provider": "api-football",
        "provider_fixture_id": f"provider:{fixture_record_id}",
    }
    values["lineup"] = {}
    for family in ("market", "team", "lineup"):
        availability[family] = True
    observed_at = NOW - timedelta(minutes=10)
    provenance = {
        family: _persisted_provenance(
            repository,
            family=family,
            value=values[family],
            fixture_id=fixture_id,
            fixture_record_id=fixture_record_id,
            observed_at=observed_at,
            marker="empty-lineup",
        )
        for family in ("market", "team", "lineup")
    }
    provenance["market"]["odds_snapshot_id"] = "odds-test"
    with pytest.raises(ValueError, match="AVAILABLE_LINEUP_FEATURE_INVALID"):
        freeze_feature_snapshot(
            repository=repository,
            registry=factory.features,
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition="Ligue 1",
            market=PredictionMarket.ONE_X_TWO,
            cutoff_name=CutoffName.H_2,
            cutoff_at=NOW,
            created_at=observed_at,
            feature_contract_version="prequential-features-v1",
            feature_contract=CONTRACT,
            values=values,
            availability=availability,
            provenance=provenance,
            quality={"status": "TEST_ONLY"},
            code_revision="test-revision",
        )


@pytest.mark.parametrize(
    "team_value",
    (
        {"home": "same", "away": "same"},
        {"home_team_id": "same", "away_team_id": "same"},
        {
            "home": "home",
            "away": "away",
            "home_team_id": "other-home",
            "away_team_id": "other-away",
        },
    ),
)
def test_available_team_identity_must_be_distinct_and_coherent(
    team_value: dict[str, str],
) -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-invalid-team-identity",
        fixture_record_id="record-invalid-team-identity",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    with pytest.raises(ValueError, match="AVAILABLE_TEAM_FEATURE_INVALID"):
        replace(
            snapshot,
            values={**snapshot.values, "team": team_value},
        )


@pytest.mark.parametrize(
    "lineup_value",
    (
        {
            "unrelated-home": [f"home-{index}" for index in range(11)],
            "unrelated-away": [f"away-{index}" for index in range(11)],
        },
        {
            "home": [f"same-{index}" for index in range(11)],
            "away": [f"same-{index}" for index in range(11)],
        },
    ),
)
def test_available_lineup_must_match_teams_and_have_22_unique_players(
    lineup_value: dict[str, list[str]],
) -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-invalid-lineup-identity",
        fixture_record_id="record-invalid-lineup-identity",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    evidence = _persisted_provenance(
        repository,
        family="lineup",
        value=lineup_value,
        fixture_id=snapshot.fixture_id,
        fixture_record_id=snapshot.fixture_record_id,
        observed_at=snapshot.created_at,
        marker="invalid-lineup-identity",
    )
    with pytest.raises(ValueError, match="AVAILABLE_LINEUP_FEATURE_INVALID"):
        replace(
            snapshot,
            values={**snapshot.values, "lineup": lineup_value},
            missingness={**snapshot.missingness, "lineup": False},
            provenance={**snapshot.provenance, "lineup": evidence},
        )


def test_required_injuries_gate_rejects_scalar_and_accepts_attested_empty_set() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-injuries-contract"
    fixture_record_id = "record-injuries-contract"
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    values.update(
        {
            "market": {
                "margin": 0.05,
                "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
            },
            "team": {
                "home": "home",
                "away": "away",
                "kickoff_at": (NOW + timedelta(hours=2)).isoformat(),
                "competition": "Ligue 1",
                "provider": "api-football",
                "provider_fixture_id": f"provider:{fixture_record_id}",
            },
            "injuries": [],
        }
    )
    for family in ("market", "team", "injuries"):
        availability[family] = True
    observed_at = NOW - timedelta(minutes=10)

    def provenance_for(family: str, value: object) -> dict[str, object]:
        return _persisted_provenance(
            repository,
            family=family,
            value=value,
            fixture_id=fixture_id,
            fixture_record_id=fixture_record_id,
            observed_at=observed_at,
            marker=f"injuries-contract:{family}",
        )

    provenance = {
        family: provenance_for(family, values[family])
        for family in ("market", "team", "injuries")
    }
    provenance["market"]["odds_snapshot_id"] = "odds-test"
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=NOW,
        created_at=observed_at,
        feature_contract_version="prequential-features-v1",
        feature_contract=CONTRACT,
        values=values,
        availability=availability,
        provenance=provenance,
        quality={
            "status": "TEST_ONLY",
            "required_gates": ["injuries"],
        },
        code_revision="test-revision",
    )
    factory.register_snapshot(snapshot)
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
        snapshot_id=snapshot.snapshot_id,
        required_gates=("fixture", "injuries"),
        gate_statuses={"fixture": True, "injuries": True},
    )
    assert prediction.status is PredictionStatus.FROZEN

    scalar = "THIS_IS_NOT_AN_INJURY_PROJECTION"
    with pytest.raises(ValueError, match="AVAILABLE_INJURIES_FEATURE_INVALID"):
        replace(
            snapshot,
            values={**snapshot.values, "injuries": scalar},
            provenance={
                **snapshot.provenance,
                "injuries": provenance_for("injuries", scalar),
            },
        )


def test_frozen_prediction_probabilities_are_recursively_immutable() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-immutable",
        fixture_record_id="fixture-record-immutable",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-immutable",
        fixture_record_id="fixture-record-immutable",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    assert isinstance(prediction, FrozenPredictionRecord)
    caller_probabilities = dict(prediction.probabilities)
    caller_market_probabilities = dict(prediction.market_probabilities or {})
    frozen = replace(
        prediction,
        prediction_id="prediction-immutable-copy",
        probabilities=caller_probabilities,
        market_probabilities=caller_market_probabilities,
        persisted_payload_hash=None,
    )
    frozen_hash = frozen.payload_hash
    caller_probabilities["HOME"] = 0.6
    caller_market_probabilities["HOME"] = 0.6
    assert frozen.payload_hash == frozen_hash
    with pytest.raises(TypeError):
        frozen.probabilities["HOME"] = 0.6  # type: ignore[index]
    assert frozen.market_probabilities is not None
    with pytest.raises(TypeError):
        frozen.market_probabilities["HOME"] = 0.6  # type: ignore[index]


def test_prequential_ledger_event_details_are_recursively_immutable() -> None:
    ledger = HashChainedPrequentialLedger()
    caller_details: dict[str, object] = {
        "status": "FROZEN",
        "nested": {"value": 1},
    }
    event = ledger.append(
        kind=PrequentialEventKind.PREDICTION_FROZEN,
        recorded_at=NOW,
        stream_key="fixture:immutable-ledger",
        fixture_id="immutable-ledger",
        evidence_hashes=("a" * 64,),
        details=caller_details,
    )
    before = ledger.audit()
    caller_details["status"] = "MUTATED"
    nested = caller_details["nested"]
    assert isinstance(nested, dict)
    nested["value"] = 2
    assert ledger.audit() == before
    with pytest.raises(TypeError):
        event.details["status"] = "MUTATED"  # type: ignore[index]
    event_nested = event.details["nested"]
    assert isinstance(event_nested, Mapping)
    with pytest.raises(TypeError):
        event_nested["value"] = 2  # type: ignore[index]


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
    changed_odds = {"HOME": 1.9, "DRAW": 3.5, "AWAY": 4.2}
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_ODDS_VALUES_LINEAGE_MISMATCH",
    ):
        _freeze_reference(
            factory,
            fixture_id="fixture-immutable",
            fixture_record_id="record-immutable",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            odds=changed_odds,
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
    future_provenance = _persisted_provenance(
        repository,
        family="market",
        value=snapshot.values["market"],
        fixture_id=snapshot.fixture_id,
        fixture_record_id=snapshot.fixture_record_id,
        observed_at=NOW + timedelta(seconds=1),
        marker="future",
    )
    with pytest.raises(ValueError, match="FEATURE_PROVENANCE_AFTER_CUTOFF"):
        replace(
            snapshot,
            provenance={
                **snapshot.provenance,
                "market": future_provenance,
            },
        )


def test_self_declared_receipt_and_late_ingestion_fail_closed() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-receipt-contract",
        fixture_record_id="record-receipt-contract",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    self_declared = dict(snapshot.provenance["market"])
    self_declared["receipt_id"] = "f" * 64
    with pytest.raises(ValueError, match="SOURCE_RECEIPT_CONTENT_ADDRESS_MISMATCH"):
        replace(
            snapshot,
            provenance={**snapshot.provenance, "market": self_declared},
        )

    late_ingestion = _persisted_provenance(
        repository,
        family="market",
        value=snapshot.values["market"],
        fixture_id=snapshot.fixture_id,
        fixture_record_id=snapshot.fixture_record_id,
        observed_at=NOW - timedelta(minutes=11),
        ingested_at=NOW + timedelta(microseconds=1),
        marker="late-ingestion",
    )
    with pytest.raises(
        ValueError,
        match="FEATURE_PROVENANCE_INGESTED_AFTER_CUTOFF",
    ):
        replace(
            snapshot,
            provenance={**snapshot.provenance, "market": late_ingestion},
        )


def test_forecast_reverifies_source_receipt_bytes() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-source-bytes",
        fixture_record_id="record-source-bytes",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    source_key = str(snapshot.provenance["market"]["storage_identity"])
    store = repository.store
    assert isinstance(store, InMemoryArtifactStore)
    store._objects.pop(source_key)  # noqa: SLF001 - deliberate corruption probe
    with pytest.raises(ArtifactIntegrityError, match="PREQUENTIAL_ARTIFACT_MISSING"):
        _freeze_reference(
            factory,
            fixture_id=snapshot.fixture_id,
            fixture_record_id=snapshot.fixture_record_id,
            competition=snapshot.competition,
            snapshot_id=snapshot.snapshot_id,
        )


def test_forecast_binds_used_odds_values_and_identity_to_verified_snapshot() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-odds-lineage",
        fixture_record_id="record-odds-lineage",
        competition="Ligue 1",
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_ODDS_VALUES_LINEAGE_MISMATCH",
    ):
        _freeze_reference(
            factory,
            fixture_id="fixture-odds-lineage",
            fixture_record_id="record-odds-lineage",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            odds={"HOME": 1.9, "DRAW": 3.5, "AWAY": 4.2},
        )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_ODDS_SNAPSHOT_LINEAGE_MISMATCH",
    ):
        _freeze_reference(
            factory,
            fixture_id="fixture-odds-lineage",
            fixture_record_id="record-odds-lineage",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            odds_snapshot_id="odds-other",
        )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-odds-lineage",
        fixture_record_id="record-odds-lineage",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    assert prediction.status is PredictionStatus.FROZEN
    assert prediction.odds_snapshot_id == "odds-test"


def test_feature_snapshot_rejects_receipt_payload_value_mismatch() -> None:
    factory, repository = _factory()
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        "source": "TEST",
    }
    availability["market"] = True
    wrong_evidence = _persisted_provenance(
        repository,
        family="market",
        value={
            "decimal_odds": {"HOME": 9.0, "DRAW": 9.0, "AWAY": 9.0},
            "source": "TEST",
        },
        fixture_id="fixture-receipt-value-mismatch",
        fixture_record_id="record-receipt-value-mismatch",
        observed_at=NOW - timedelta(minutes=10),
        marker="wrong-market-value",
    )
    wrong_evidence["odds_snapshot_id"] = "odds-test"
    with pytest.raises(
        ValueError,
        match="FEATURE_SOURCE_RECEIPT_VALUE_MISMATCH",
    ):
        freeze_feature_snapshot(
            repository=repository,
            registry=factory.features,
            fixture_record_id="record-receipt-value-mismatch",
            fixture_id="fixture-receipt-value-mismatch",
            competition="Ligue 1",
            market=PredictionMarket.ONE_X_TWO,
            cutoff_name=CutoffName.H_2,
            cutoff_at=NOW,
            created_at=NOW - timedelta(minutes=10),
            feature_contract_version="prequential-features-v1",
            feature_contract=CONTRACT,
            values=values,
            availability=availability,
            provenance={"market": wrong_evidence},
            quality={"status": "TEST_ONLY"},
            code_revision="test-revision",
        )


def test_feature_snapshot_rejects_receipts_from_another_fixture() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-receipt-owner-a",
        fixture_record_id="record-receipt-owner-a",
        competition="Ligue 1",
    )
    source = factory.features.get(snapshot_id)
    assert source is not None
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SOURCE_RECEIPT_FIXTURE_MISMATCH",
    ):
        freeze_feature_snapshot(
            repository=repository,
            registry=factory.features,
            fixture_record_id="record-receipt-owner-b",
            fixture_id="fixture-receipt-owner-b",
            competition=source.competition,
            market=source.market,
            cutoff_name=source.cutoff_name,
            cutoff_at=source.cutoff_at,
            created_at=source.created_at,
            feature_contract_version=source.feature_contract_version,
            feature_contract=CONTRACT,
            values=dict(source.values),
            availability={
                family: not missing
                for family, missing in source.missingness.items()
            },
            provenance=dict(source.provenance),
            quality=dict(source.quality),
            code_revision="test-revision",
        )


def test_feature_snapshot_is_deeply_immutable_and_r2_exact() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-deep-immutable",
        fixture_record_id="record-deep-immutable",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    initial_hash = snapshot.snapshot_hash
    market = snapshot.values["market"]
    assert isinstance(market, Mapping)
    with pytest.raises(TypeError):
        market["margin"] = 9.0  # type: ignore[index]
    assert snapshot.snapshot_hash == initial_hash
    paris = ZoneInfo("Europe/Paris")
    equivalent = replace(
        snapshot,
        cutoff_at=snapshot.cutoff_at.astimezone(paris),
        created_at=snapshot.created_at.astimezone(paris),
    )
    assert equivalent.snapshot_hash == initial_hash
    verify_feature_snapshot_artifact(repository, snapshot)
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_FEATURE_SNAPSHOT_ID_INVALID",
    ):
        verify_feature_snapshot_artifact(
            repository,
            replace(snapshot, quality={"status": "MUTATED"}),
        )


def test_forecast_and_settlement_require_exact_point_in_time_lineage() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-late-snapshot",
        fixture_record_id="record-late-snapshot",
        competition="Ligue 1",
        created_at=NOW - timedelta(minutes=1),
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_FEATURE_SNAPSHOT_AFTER_PREDICTION",
    ):
        _freeze_reference(
            factory,
            fixture_id="fixture-late-snapshot",
            fixture_record_id="record-late-snapshot",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
        )

    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-lineage",
        fixture_record_id="record-lineage-v1",
        competition="Ligue 1",
    )
    reference = _reference(factory)
    late_model = replace(reference, created_at=NOW)
    factory.models[(late_model.model_id, late_model.version)] = late_model
    with pytest.raises(ValueError, match="MODEL_NOT_AVAILABLE_AT_CUTOFF"):
        _freeze_reference(
            factory,
            fixture_id="fixture-lineage",
            fixture_record_id="record-lineage-v1",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
        )

    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-lineage",
        fixture_record_id="record-lineage-v1",
        competition="Ligue 1",
    )
    reference = _reference(factory)
    incompatible = replace(reference, feature_contract_hash="f" * 64)
    factory.models[(incompatible.model_id, incompatible.version)] = incompatible
    with pytest.raises(ValueError, match="PREQUENTIAL_FEATURE_CONTRACT_MISMATCH"):
        _freeze_reference(
            factory,
            fixture_id="fixture-lineage",
            fixture_record_id="record-lineage-v1",
            competition="Ligue 1",
            snapshot_id=snapshot_id,
        )

    factory.models[(reference.model_id, reference.version)] = reference
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-lineage",
        fixture_record_id="record-lineage-v1",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    verified_at = prediction.kickoff_at + timedelta(hours=2)
    provider_fixture_id = "provider:record-lineage-v2"
    observation = _persist_result_observation(
        factory.artifact_repository,
        fixture_id=prediction.fixture_id,
        fixture_record_id="record-lineage-v2",
        provider_fixture_id=provider_fixture_id,
        attempt=1,
        observed_at=verified_at,
        record={
            "fixture": {
                "id": provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": 1, "away": 0},
        },
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_FIXTURE_IDENTITY_MISMATCH",
    ):
        factory.settle(
            VerifiedFixtureResult(
                fixture_record_id="record-lineage-v2",
                fixture_id=prediction.fixture_id,
                competition=prediction.competition,
                kickoff_at=prediction.kickoff_at,
                status=FixtureResultStatus.FINISHED,
                verified_at=verified_at,
                home_goals=1,
                away_goals=0,
                source_hash=observation.sha256,
            ),
            settled_at=prediction.kickoff_at + timedelta(hours=2),
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


def test_settlement_requires_provider_guard_and_completion_chain() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-result-chain"
    fixture_record_id = "record-result-chain"
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    observed_at = prediction.kickoff_at + timedelta(hours=2)
    provider_fixture_id = f"provider:{fixture_record_id}"
    record: dict[str, object] = {
        "fixture": {
            "id": provider_fixture_id,
            "status": {"short": "FT"},
        },
        "goals": {"home": 2, "away": 1},
    }
    standalone = repository.put_manifest(
        "result-observations",
        {
            "schema_version": "prequential-result-observation-v1",
            "provider": "api-football",
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "provider_fixture_id": provider_fixture_id,
            "attempt": 1,
            "observed_at": observed_at.isoformat(),
            "availability": "PRESENT",
            "http_status": 200,
            "record": record,
            "provider_calls": 1,
        },
    )
    result = VerifiedFixtureResult(
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition="Ligue 1",
        kickoff_at=prediction.kickoff_at,
        status=FixtureResultStatus.FINISHED,
        verified_at=observed_at,
        home_goals=2,
        away_goals=1,
        source_hash=standalone.sha256,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_OBSERVATION_COMPLETION_REQUIRED",
    ):
        factory.settle(result, settled_at=observed_at)

    linked = _persist_result_observation(
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=provider_fixture_id,
        attempt=1,
        observed_at=observed_at,
        record=record,
    )
    assert linked.sha256 == standalone.sha256
    _settlement, _scores, inserted = factory.settle(
        result,
        settled_at=observed_at,
    )
    assert inserted is True


def test_settlement_rejects_provider_completion_after_settlement_time() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-delayed-completion"
    fixture_record_id = "record-delayed-completion"
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    observed_at = prediction.kickoff_at + timedelta(hours=2)
    provider_fixture_id = f"provider:{fixture_record_id}"
    observation = _persist_result_observation(
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=provider_fixture_id,
        attempt=1,
        observed_at=observed_at,
        completed_at=observed_at + timedelta(seconds=1),
        record={
            "fixture": {
                "id": provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": 2, "away": 1},
        },
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_OBSERVATION_CALL_TIME_INVALID",
    ):
        factory.settle(
            VerifiedFixtureResult(
                fixture_record_id=fixture_record_id,
                fixture_id=fixture_id,
                competition="Ligue 1",
                kickoff_at=prediction.kickoff_at,
                status=FixtureResultStatus.FINISHED,
                verified_at=observed_at,
                home_goals=2,
                away_goals=1,
                source_hash=observation.sha256,
            ),
            settled_at=observed_at,
        )


def test_settlement_rejects_result_for_different_provider_fixture() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-provider-identity"
    fixture_record_id = "record-provider-identity"
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    observed_at = prediction.kickoff_at + timedelta(hours=2)
    wrong_provider_fixture_id = "provider:different-fixture"
    observation = _persist_result_observation(
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=wrong_provider_fixture_id,
        attempt=1,
        observed_at=observed_at,
        record={
            "fixture": {
                "id": wrong_provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": 2, "away": 1},
        },
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_FIXTURE_IDENTITY_MISMATCH",
    ):
        factory.settle(
            VerifiedFixtureResult(
                fixture_record_id=fixture_record_id,
                fixture_id=fixture_id,
                competition="Ligue 1",
                kickoff_at=prediction.kickoff_at,
                status=FixtureResultStatus.FINISHED,
                verified_at=observed_at,
                home_goals=2,
                away_goals=1,
                source_hash=observation.sha256,
            ),
            settled_at=observed_at,
        )


def test_future_duplicate_completion_cannot_invalidate_past_settlement() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-future-duplicate-completion"
    fixture_record_id = "record-future-duplicate-completion"
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    observed_at = prediction.kickoff_at + timedelta(hours=2)
    provider_fixture_id = f"provider:{fixture_record_id}"
    observation = _persist_result_observation(
        repository,
        fixture_id=fixture_id,
        fixture_record_id=fixture_record_id,
        provider_fixture_id=provider_fixture_id,
        attempt=1,
        observed_at=observed_at,
        record={
            "fixture": {
                "id": provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": 2, "away": 1},
        },
    )
    guard_key = next(
        key
        for key in repository.store.iter_keys(
            f"{repository.namespace}/provider-call-guards/"
        )
    )
    guard_sha256 = guard_key.rsplit("/", 1)[-1][:-5]
    repository.put_manifest(
        "provider-call-completions",
        {
            "schema_version": "prequential-provider-call-completion-v1",
            "guard_sha256": guard_sha256,
            "observation_sha256": observation.sha256,
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "attempt": 1,
            "completed_at": (observed_at + timedelta(hours=1)).isoformat(),
        },
    )
    settlement, _scores, inserted = factory.settle(
        VerifiedFixtureResult(
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition="Ligue 1",
            kickoff_at=prediction.kickoff_at,
            status=FixtureResultStatus.FINISHED,
            verified_at=observed_at,
            home_goals=2,
            away_goals=1,
            source_hash=observation.sha256,
        ),
        settled_at=observed_at,
    )
    assert inserted is True
    assert settlement.result.source_hash == observation.sha256


def test_factory_settlement_requires_immutable_result_observation() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-unreceipted-result",
        fixture_record_id="record-unreceipted-result",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-unreceipted-result",
        fixture_record_id="record-unreceipted-result",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_OBSERVATION_BYTES_INVALID",
    ):
        factory.settle(
            VerifiedFixtureResult(
                fixture_record_id=prediction.fixture_record_id,
                fixture_id=prediction.fixture_id,
                competition=prediction.competition,
                kickoff_at=prediction.kickoff_at,
                status=FixtureResultStatus.FINISHED,
                verified_at=prediction.kickoff_at + timedelta(hours=2),
                home_goals=1,
                away_goals=0,
                source_hash="f" * 64,
            ),
            settled_at=prediction.kickoff_at + timedelta(hours=2),
        )


def test_factory_registration_and_training_reverify_durable_artifacts() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-artifact-boundary",
        fixture_record_id="record-artifact-boundary",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    forged_snapshot = replace(
        snapshot,
        snapshot_id="feature-forged-artifact",
        r2_manifest_key=(
            "prequential-learning/schema-v1/feature-snapshots/"
            + "0" * 64
            + ".json"
        ),
        supersedes_id=snapshot.snapshot_id,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_FEATURE_SNAPSHOT_ID_INVALID",
    ):
        factory.register_snapshot(forged_snapshot)

    unreceipted_result = VerifiedFixtureResult(
        fixture_record_id="record-artifact-boundary",
        fixture_id="fixture-artifact-boundary",
        competition="Ligue 1",
        kickoff_at=NOW - timedelta(hours=3),
        status=FixtureResultStatus.FINISHED,
        verified_at=NOW - timedelta(hours=1),
        home_goals=1,
        away_goals=0,
        source_hash="f" * 64,
    )
    factory.settlements.restore(
        FixtureSettlementRecord(
            settlement_id="settlement-unreceipted-training",
            result=unreceipted_result,
            settled_at=NOW,
            effective_status=PredictionStatus.SETTLED,
        )
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_OBSERVATION_BYTES_INVALID",
    ):
        factory.train(
            model_id="challenger-global_five_leagues",
            previous_version="untrained-v1",
            training_cutoff=NOW + timedelta(days=1),
            code_revision="test-revision",
        )


def test_factory_rejects_content_addressed_snapshot_with_unknown_availability() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-empty-availability",
        fixture_record_id="record-empty-availability",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    empty = replace(
        snapshot,
        snapshot_id="feature-empty-availability",
        values={},
        missingness={},
        provenance={},
        r2_manifest_key=(
            "prequential-learning/schema-v1/feature-snapshots/"
            + "0" * 64
            + ".json"
        ),
        supersedes_id=snapshot.snapshot_id,
    )
    stored = repository.put_manifest(
        "feature-snapshots",
        empty.storage_manifest(),
    )
    empty = replace(empty, r2_manifest_key=stored.key)
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_FEATURE_SNAPSHOT_SHAPE_INVALID",
    ):
        factory.register_snapshot(empty)


def test_factory_rejects_receipted_null_feature_marked_available() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-null-team",
        fixture_record_id="record-null-team",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    with pytest.raises(ValueError, match="AVAILABLE_FEATURE_VALUE_REQUIRED"):
        replace(
            snapshot,
            values={**snapshot.values, "team": None},
        )


def test_factory_rejects_receipted_empty_team_marked_available() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-empty-team",
        fixture_record_id="record-empty-team",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    with pytest.raises(ValueError, match="AVAILABLE_TEAM_FEATURE_INVALID"):
        replace(
            snapshot,
            values={**snapshot.values, "team": {}},
        )


def test_snapshot_rejects_future_provenance_for_missing_family() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-missing-injuries",
        fixture_record_id="record-missing-injuries",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    future_evidence = _persisted_provenance(
        repository,
        family="injuries",
        value=None,
        fixture_id=snapshot.fixture_id,
        fixture_record_id=snapshot.fixture_record_id,
        observed_at=snapshot.cutoff_at + timedelta(minutes=1),
    )
    with pytest.raises(
        ValueError,
        match="FEATURE_PROVENANCE_FAMILY_SET_INVALID",
    ):
        replace(
            snapshot,
            provenance={**snapshot.provenance, "injuries": future_evidence},
        )


def test_training_ignores_unselected_future_artifact_corruption() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-future-corrupt-artifact",
        fixture_record_id="record-future-corrupt-artifact",
        competition="Ligue 1",
    )
    snapshot = factory.features.get(snapshot_id)
    assert snapshot is not None
    training_cutoff = NOW + timedelta(days=1)
    future_snapshot = replace(
        snapshot,
        snapshot_id="feature-future-corrupt-artifact",
        fixture_record_id="record-future-corrupt-artifact-v2",
        fixture_id="fixture-future-corrupt-artifact-v2",
        cutoff_at=training_cutoff + timedelta(days=1),
        created_at=training_cutoff + timedelta(hours=1),
        values={
            **snapshot.values,
            "team": {
                **snapshot.values["team"],
                "kickoff_at": (
                    training_cutoff + timedelta(days=1, hours=2)
                ).isoformat(),
                "provider_fixture_id": (
                    "provider:record-future-corrupt-artifact-v2"
                ),
            },
        },
        r2_manifest_key=(
            "prequential-learning/schema-v1/feature-snapshots/"
            + "0" * 64
            + ".json"
        ),
        supersedes_id=None,
    )
    factory.features.append(future_snapshot)

    decision = factory.train(
        model_id="challenger-global_five_leagues",
        previous_version="untrained-v1",
        training_cutoff=training_cutoff,
        code_revision="test-revision",
    )
    assert decision.status == TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT


def test_training_does_not_fallback_when_latest_logical_revision_is_unsettled() -> None:
    factory, repository = _factory()
    old_cutoff = NOW - timedelta(days=1, hours=2)
    old_snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-revised",
        fixture_record_id="record-revised-v1",
        competition="Ligue 1",
        cutoff_at=old_cutoff,
    )
    _freeze_reference(
        factory,
        fixture_id="fixture-revised",
        fixture_record_id="record-revised-v1",
        competition="Ligue 1",
        snapshot_id=old_snapshot_id,
        cutoff_at=old_cutoff,
    )
    _settle(
        factory,
        fixture_id="fixture-revised",
        fixture_record_id="record-revised-v1",
        competition="Ligue 1",
        kickoff_at=old_cutoff + timedelta(hours=2),
    )
    revised_cutoff = old_cutoff - timedelta(minutes=5)
    _snapshot(
        factory,
        repository,
        fixture_id="fixture-revised",
        fixture_record_id="record-revised-v2",
        competition="Ligue 1",
        cutoff_at=revised_cutoff,
        created_at=revised_cutoff - timedelta(minutes=1),
    )

    examples = eligible_training_examples(
        settlements=factory.settlements.settlements,
        snapshots=factory.features.snapshots,
        training_cutoff=NOW + timedelta(hours=1),
    )

    assert old_snapshot_id
    assert examples == ()


def test_training_uses_linked_snapshot_chain_head_with_earlier_cutoff() -> None:
    factory, repository = _factory()
    old_cutoff = NOW - timedelta(days=1)
    old_snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-linked-correction",
        fixture_record_id="record-linked-correction",
        competition="Ligue 1",
        cutoff_at=old_cutoff,
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-linked-correction",
        fixture_record_id="record-linked-correction",
        competition="Ligue 1",
        snapshot_id=old_snapshot_id,
        cutoff_at=old_cutoff,
    )
    _settle(
        factory,
        fixture_id="fixture-linked-correction",
        fixture_record_id="record-linked-correction",
        competition="Ligue 1",
        kickoff_at=prediction.kickoff_at,
    )
    old_snapshot = factory.features.get(old_snapshot_id)
    assert old_snapshot is not None
    corrected_values = dict(old_snapshot.values)
    corrected_values["market"] = None
    corrected_availability = {
        family: not bool(old_snapshot.missingness[family])
        for family in FEATURE_FAMILIES
    }
    corrected_availability["market"] = False
    corrected_provenance = {
        family: dict(evidence)
        for family, evidence in old_snapshot.provenance.items()
        if family != "market"
    }
    correction_cutoff = old_cutoff - timedelta(minutes=5)
    corrected_values["team"] = {
        **old_snapshot.values["team"],
        "kickoff_at": (correction_cutoff + timedelta(hours=2)).isoformat(),
    }
    corrected_provenance["team"] = _persisted_provenance(
        repository,
        family="team",
        value=corrected_values["team"],
        fixture_id=old_snapshot.fixture_id,
        fixture_record_id=old_snapshot.fixture_record_id,
        observed_at=correction_cutoff - timedelta(minutes=1),
        marker="linked-correction-team",
    )
    corrected = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=old_snapshot.fixture_record_id,
        fixture_id=old_snapshot.fixture_id,
        competition=old_snapshot.competition,
        market=old_snapshot.market,
        cutoff_name=old_snapshot.cutoff_name,
        cutoff_at=correction_cutoff,
        created_at=correction_cutoff - timedelta(minutes=1),
        feature_contract_version=old_snapshot.feature_contract_version,
        feature_contract=CONTRACT,
        values=corrected_values,
        availability=corrected_availability,
        provenance=corrected_provenance,
        quality={"status": "MARKET_INVALIDATED"},
        code_revision="test-revision",
        supersedes_id=old_snapshot.snapshot_id,
    )

    examples = eligible_training_examples(
        settlements=factory.settlements.settlements,
        snapshots=factory.features.snapshots,
        training_cutoff=NOW + timedelta(hours=1),
        required_feature_contract_hash=CONTRACT_HASH,
    )

    assert corrected.cutoff_at < old_snapshot.cutoff_at
    assert corrected.created_at > old_snapshot.created_at
    assert examples == ()


def test_training_rejects_incompatible_logical_head_contract_without_fallback() -> None:
    factory, repository = _factory()
    old_cutoff = NOW - timedelta(days=1)
    old_snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-contract-revision",
        fixture_record_id="record-contract-v1",
        competition="Ligue 1",
        cutoff_at=old_cutoff,
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-contract-revision",
        fixture_record_id="record-contract-v1",
        competition="Ligue 1",
        snapshot_id=old_snapshot_id,
        cutoff_at=old_cutoff,
    )
    _settle(
        factory,
        fixture_id="fixture-contract-revision",
        fixture_record_id="record-contract-v1",
        competition="Ligue 1",
        kickoff_at=prediction.kickoff_at,
    )
    revised_cutoff = old_cutoff - timedelta(minutes=5)
    revised_created = revised_cutoff - timedelta(minutes=1)
    revised_record_id = "record-contract-v2"
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "margin": 0.05,
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
    }
    values["team"] = {
        "home": "home",
        "away": "away",
        "kickoff_at": (revised_cutoff + timedelta(hours=2)).isoformat(),
        "competition": "Ligue 1",
        "provider": "api-football",
        "provider_fixture_id": f"provider:{revised_record_id}",
    }
    availability["market"] = availability["team"] = True
    provenance = {
        family: _persisted_provenance(
            repository,
            family=family,
            value=values[family],
            fixture_id="fixture-contract-revision",
            fixture_record_id=revised_record_id,
            observed_at=revised_created,
            marker="contract-v2",
        )
        for family in ("market", "team")
    }
    provenance["market"]["odds_snapshot_id"] = "odds-test"
    contract_v2 = {"version": "prequential-features-v2"}
    freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=revised_record_id,
        fixture_id="fixture-contract-revision",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=revised_cutoff,
        created_at=revised_created,
        feature_contract_version="prequential-features-v2",
        feature_contract=contract_v2,
        values=values,
        availability=availability,
        provenance=provenance,
        quality={"status": "CONTRACT_V2"},
        code_revision="test-revision",
    )

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_TRAINING_FEATURE_CONTRACT_MISMATCH",
    ):
        eligible_training_examples(
            settlements=factory.settlements.settlements,
            snapshots=factory.features.snapshots,
            training_cutoff=NOW + timedelta(hours=1),
            required_feature_contract_hash=CONTRACT_HASH,
        )


def test_challenger_forecast_rederives_probabilities_from_model_artifact() -> None:
    factory, repository = _factory()
    training_cutoff = NOW - timedelta(days=1)
    artifact_body = {
        "schema_version": "prequential-challenger-artifact-v1",
        "training_manifest_hash": "a" * 64,
        "training_cutoff": training_cutoff.isoformat(),
        "counts_by_market": {
            "1X2": {"HOME": 30, "DRAW": 0, "AWAY": 0}
        },
        "support_fixtures": 30,
        "support_examples": 30,
        "competitions": ["Ligue 1", "Premier League"],
        "promotion_status": "PROMOTION_LOCKED",
    }
    stored = repository.put_artifact(
        "challenger-models",
        canonical_json_bytes(artifact_body),
    )
    challenger = next(
        model
        for model in factory.models.values()
        if model.role is ModelRole.CHALLENGER
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    active = replace(
        challenger,
        version="active-receipt-backed-v1",
        artifact_sha256=stored.sha256,
        artifact_r2_key=stored.key,
        created_at=training_cutoff,
        training_cutoff=training_cutoff,
        status=ModelStatus.ACTIVE,
    )
    factory.models[(active.model_id, active.version)] = active
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-challenger-artifact",
        fixture_record_id="record-challenger-artifact",
        competition="Ligue 1",
    )
    arguments = {
        "fixture_record_id": "record-challenger-artifact",
        "fixture_id": "fixture-challenger-artifact",
        "competition": "Ligue 1",
        "market": PredictionMarket.ONE_X_TWO,
        "cutoff_name": CutoffName.H_2,
        "cutoff_at": NOW,
        "kickoff_at": NOW + timedelta(hours=2),
        "predicted_at": NOW - timedelta(minutes=5),
        "model_id": active.model_id,
        "model_version": active.version,
        "feature_snapshot_id": snapshot_id,
        "gate_statuses": {"fixture": True, "market": True},
        "required_gates": ("fixture", "market"),
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        "odds_snapshot_id": "odds-test",
        "code_revision": "test-revision",
    }
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_CHALLENGER_PROBABILITY_MISMATCH",
    ):
        factory.forecast(
            **arguments,
            challenger_probabilities={"HOME": 0.1, "DRAW": 0.2, "AWAY": 0.7},
        )
    prediction = factory.forecast(
        **arguments,
        challenger_probabilities=None,
    )
    assert prediction.status is PredictionStatus.FROZEN
    assert prediction.probabilities == pytest.approx(
        {"HOME": 31 / 33, "DRAW": 1 / 33, "AWAY": 1 / 33}
    )

    future_artifact = repository.put_artifact(
        "challenger-models",
        canonical_json_bytes(
            {
                **artifact_body,
                "training_cutoff": (NOW + timedelta(days=1)).isoformat(),
            }
        ),
    )
    backdated_model = replace(
        active,
        version="backdated-registry-v1",
        artifact_sha256=future_artifact.sha256,
        artifact_r2_key=future_artifact.key,
    )
    factory.models[(backdated_model.model_id, backdated_model.version)] = (
        backdated_model
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_CHALLENGER_ARTIFACT_TIME_MISMATCH",
    ):
        factory.forecast(
            **{**arguments, "model_version": backdated_model.version},
            challenger_probabilities=None,
        )


@pytest.mark.parametrize(
    ("version", "corrected", "error"),
    (
        (2, False, "PREQUENTIAL_RESULT_INITIAL_VERSION_INVALID"),
        (1, True, "PREQUENTIAL_RESULT_INITIAL_VERSION_INVALID"),
    ),
)
def test_initial_settlement_rejects_noncanonical_result_chain(
    version: int,
    corrected: bool,
    error: str,
) -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-bad-result-chain",
        fixture_record_id="record-bad-result-chain",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-bad-result-chain",
        fixture_record_id="record-bad-result-chain",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    with pytest.raises(ValueError, match=error):
        _settle(
            factory,
            fixture_id=prediction.fixture_id,
            fixture_record_id=prediction.fixture_record_id,
            competition=prediction.competition,
            kickoff_at=prediction.kickoff_at,
            version=version,
            corrected=corrected,
        )


def test_settlement_requires_exact_frozen_fixture_projection() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-result-projection",
        fixture_record_id="record-result-projection",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-result-projection",
        fixture_record_id="record-result-projection",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_SETTLEMENT_FIXTURE_PROJECTION_MISMATCH",
    ):
        _settle(
            factory,
            fixture_id=prediction.fixture_id,
            fixture_record_id=prediction.fixture_record_id,
            competition="Premier League",
            kickoff_at=prediction.kickoff_at,
        )


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
    void_verified_at = NOW + timedelta(hours=3)
    void_provider_fixture_id = "provider:record-void"
    void_observation = _persist_result_observation(
        factory.artifact_repository,
        fixture_id="fixture-void",
        fixture_record_id="record-void",
        provider_fixture_id=void_provider_fixture_id,
        attempt=1,
        observed_at=void_verified_at,
        record={
            "fixture": {
                "id": void_provider_fixture_id,
                "status": {"short": "CANC"},
            },
            "goals": None,
        },
    )
    void_result = VerifiedFixtureResult(
        fixture_record_id="record-void",
        fixture_id="fixture-void",
        competition="Premier League",
        kickoff_at=NOW + timedelta(hours=2),
        status=FixtureResultStatus.CANCELLED,
        verified_at=void_verified_at,
        source_hash=void_observation.sha256,
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


def test_settlement_rejects_correction_reusing_same_observation() -> None:
    factory, repository = _factory()
    snapshot_id = _snapshot(
        factory,
        repository,
        fixture_id="fixture-reused-result-observation",
        fixture_record_id="record-reused-result-observation",
        competition="Ligue 1",
    )
    prediction = _freeze_reference(
        factory,
        fixture_id="fixture-reused-result-observation",
        fixture_record_id="record-reused-result-observation",
        competition="Ligue 1",
        snapshot_id=snapshot_id,
    )
    first, _scores, inserted = _settle(
        factory,
        fixture_id=prediction.fixture_id,
        fixture_record_id=prediction.fixture_record_id,
        competition=prediction.competition,
        kickoff_at=prediction.kickoff_at,
    )
    assert inserted is True
    repeated_observation = replace(
        first.result,
        result_version=2,
        status=FixtureResultStatus.CORRECTED,
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_RESULT_CORRECTION_TIME_INVALID",
    ):
        factory.settle(
            repeated_observation,
            settled_at=first.settled_at,
        )


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


@pytest.mark.parametrize(
    ("parent_created_at", "parent_training_cutoff", "last_training_at", "error"),
    (
        (
            NOW + timedelta(days=2),
            None,
            None,
            "PREQUENTIAL_PARENT_MODEL_AFTER_TRAINING_CUTOFF",
        ),
        (
            NOW + timedelta(days=2),
            NOW + timedelta(days=1),
            None,
            "PREQUENTIAL_PARENT_MODEL_AFTER_TRAINING_CUTOFF",
        ),
        (
            NOW - timedelta(days=2),
            None,
            NOW + timedelta(days=1),
            "PREQUENTIAL_LAST_TRAINING_AFTER_CUTOFF",
        ),
    ),
)
def test_training_rejects_future_parent_or_last_training_boundary(
    parent_created_at: datetime,
    parent_training_cutoff: datetime | None,
    last_training_at: datetime | None,
    error: str,
) -> None:
    factory, _ = _factory()
    parent = next(
        model
        for model in factory.models.values()
        if model.role is ModelRole.CHALLENGER
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    future_parent = replace(
        parent,
        version="future-parent",
        created_at=parent_created_at,
        training_cutoff=parent_training_cutoff,
    )
    factory.models[(future_parent.model_id, future_parent.version)] = future_parent
    with pytest.raises(ValueError, match=error):
        factory.train(
            model_id=future_parent.model_id,
            previous_version=future_parent.version,
            training_cutoff=NOW,
            code_revision="test-revision",
            last_training_at=last_training_at,
        )


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


def test_training_deduplicates_ordered_logical_fixture_revisions() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-logical-revision"
    for suffix, cutoff_at in (
        ("v1", NOW - timedelta(days=3)),
        ("v2", NOW - timedelta(days=2)),
    ):
        record_id = f"record-logical-{suffix}"
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            cutoff_at=cutoff_at,
        )
        prediction = _freeze_reference(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            cutoff_at=cutoff_at,
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
    assert len(examples) == 1
    assert examples[0].fixture_record_id == "record-logical-v2"


def test_training_fails_closed_on_exact_logical_revision_tie() -> None:
    factory, repository = _factory()
    fixture_id = "fixture-logical-tie"
    cutoff_at = NOW - timedelta(days=2)
    for suffix in ("v1", "v2"):
        record_id = f"record-logical-tie-{suffix}"
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            cutoff_at=cutoff_at,
        )
        prediction = _freeze_reference(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            snapshot_id=snapshot_id,
            cutoff_at=cutoff_at,
        )
        _settle(
            factory,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Ligue 1",
            kickoff_at=prediction.kickoff_at,
        )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_TRAINING_LOGICAL_REVISION_AMBIGUOUS",
    ):
        eligible_training_examples(
            settlements=factory.settlements.settlements,
            snapshots=factory.features.snapshots,
            training_cutoff=NOW + timedelta(days=1),
        )


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


def test_segment_coverage_uses_every_frozen_prediction_as_denominator() -> None:
    factory, repository = _factory()
    predictions = []
    for suffix in ("scored", "unscored"):
        fixture_id = f"fixture-coverage-{suffix}"
        record_id = f"record-coverage-{suffix}"
        snapshot_id = _snapshot(
            factory,
            repository,
            fixture_id=fixture_id,
            fixture_record_id=record_id,
            competition="Serie A",
        )
        predictions.append(
            _freeze_reference(
                factory,
                fixture_id=fixture_id,
                fixture_record_id=record_id,
                competition="Serie A",
                snapshot_id=snapshot_id,
            )
        )
    _settle(
        factory,
        fixture_id=predictions[0].fixture_id,
        fixture_record_id=predictions[0].fixture_record_id,
        competition=predictions[0].competition,
        kickoff_at=predictions[0].kickoff_at,
    )
    aggregate = aggregate_metrics(
        predictions=factory.predictions.predictions,
        scores=factory.settlements.scores,
    )
    segments = segmented_metrics(
        predictions=factory.predictions.predictions,
        scores=factory.settlements.scores,
    )
    assert aggregate["coverage"] == 0.5
    assert len(segments) == 1
    assert segments[0]["metrics"]["coverage"] == 0.5
