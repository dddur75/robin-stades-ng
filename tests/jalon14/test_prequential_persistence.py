from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    feature_snapshot_record_id,
    freeze_feature_snapshot,
    persist_source_receipt,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    ModelRole,
    ModelScope,
    PredictionMarket,
    PrequentialEventKind,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_factory import (
    PrequentialLearningFactory,
    initial_model_versions,
)
from robin.prospective_observatory.prequential_persistence import (
    PrequentialSQLRepository,
)
from robin.prospective_observatory.prequential_replay import (
    replay_prequential_rows,
)
from robin.prospective_observatory.prequential_storage import (
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
    StoredArtifact,
)
from robin.storage.database import build_engine
from robin.storage.models import Base
from robin.storage.prequential_models import PREQUENTIAL_TABLES
from scripts.run_prequential_learning_factory import (
    _restore_factory,
    _verify_replay_artifacts,
)

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _persisted_provenance(
    repository: PrequentialArtifactRepository,
    *,
    family: str,
    value: object,
    fixture_id: str,
    fixture_record_id: str,
    observed_at: datetime,
) -> dict[str, object]:
    receipt = persist_source_receipt(
        repository,
        source_name="TEST",
        request_identity=f"persistence-test:{family}",
        payload={
            "fixture_id": fixture_id,
            "fixture_record_id": fixture_record_id,
            "family": family,
            "value": value,
        },
        observed_at=observed_at,
        ingested_at=observed_at,
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
    record: dict[str, object],
) -> StoredArtifact:
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
            "guarded_at": (observed_at - timedelta(seconds=1)).isoformat(),
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
            "record": record,
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
            "completed_at": observed_at.isoformat(),
        },
    )
    return observation


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _upgrade(tmp_path: Path) -> tuple[sa.Engine, str]:
    url = f"sqlite+pysqlite:///{(tmp_path / 'prequential.db').as_posix()}"
    command.upgrade(_config(url), "head")
    return build_engine(url), url


def _fixture_row() -> dict[str, object]:
    return {
        "id": "fixture-record-1",
        "idempotency_key": "fixture:api-football:42",
        "fixture_id": "api-football:42",
        "competition": "Ligue 1",
        "season": "2026",
        "phase": "Regular Season",
        "home_team_id": "api-football:1",
        "away_team_id": "api-football:2",
        "kickoff_at": NOW + timedelta(hours=2),
        "provider": "api-football",
        "provider_fixture_id": "42",
        "registered_at": NOW - timedelta(days=1),
        "registry_hash": "a" * 64,
        "code_revision": "test-revision",
        "cancelled": False,
        "kickoff_reliable": True,
        "append_only": True,
    }


def _seed_fixture(engine: sa.Engine) -> None:
    table = sa.Table(
        "prospective_fixtures",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        connection.execute(table.insert().values(**_fixture_row()))


def _factory_records() -> tuple[
    PrequentialLearningFactory,
    object,
    object,
    tuple[object, ...],
]:
    contract = {"version": "prequential-features-v1"}
    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    models = initial_model_versions(
        created_at=NOW - timedelta(days=1),
        feature_contract_hash=canonical_sha256(contract),
        code_revision="test-revision",
    )
    factory = PrequentialLearningFactory(
        artifact_repository=repository,
        models=models,
        devig_method="PROPORTIONAL",
    )
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "margin": 0.05,
        "decimal_odds": {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
    }
    values["team"] = {
        "home": "api-football:1",
        "away": "api-football:2",
        "kickoff_at": (NOW + timedelta(hours=2)).isoformat(),
        "competition": "Ligue 1",
        "provider": "api-football",
        "provider_fixture_id": "provider:fixture-record-1",
    }
    availability["market"] = availability["team"] = True
    provenance = {
        family: _persisted_provenance(
            repository,
            family=family,
            value=values[family],
            fixture_id="api-football:42",
            fixture_record_id="fixture-record-1",
            observed_at=NOW - timedelta(minutes=10),
        )
        for family in ("market", "team")
    }
    provenance["market"]["odds_snapshot_id"] = "odds-1"
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id="fixture-record-1",
        fixture_id="api-football:42",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=NOW,
        created_at=NOW - timedelta(minutes=10),
        feature_contract_version="prequential-features-v1",
        feature_contract=contract,
        values=values,
        availability=availability,
        provenance=provenance,
        quality={"status": "TEST_ONLY"},
        code_revision="test-revision",
    )
    factory.register_snapshot(snapshot)
    reference = next(
        model
        for model in models
        if model.role is ModelRole.REFERENCE
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    prediction = factory.forecast(
        fixture_record_id="fixture-record-1",
        fixture_id="api-football:42",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=NOW,
        kickoff_at=NOW + timedelta(hours=2),
        predicted_at=NOW - timedelta(minutes=5),
        model_id=reference.model_id,
        model_version=reference.version,
        feature_snapshot_id=snapshot.snapshot_id,
        gate_statuses={"fixture": True},
        required_gates=("fixture",),
        decimal_odds={"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        odds_snapshot_id="odds-1",
        challenger_probabilities=None,
        code_revision="test-revision",
    )
    verified_at = NOW + timedelta(hours=4)
    provider_fixture_id = "provider:fixture-record-1"
    observation = _persist_result_observation(
        repository,
        fixture_id="api-football:42",
        fixture_record_id="fixture-record-1",
        provider_fixture_id=provider_fixture_id,
        attempt=1,
        observed_at=verified_at,
        record={
            "fixture": {
                "id": provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {"home": 2, "away": 1},
        },
    )
    settlement, scores, _ = factory.settle(
        VerifiedFixtureResult(
            fixture_record_id="fixture-record-1",
            fixture_id="api-football:42",
            competition="Ligue 1",
            kickoff_at=NOW + timedelta(hours=2),
            status=FixtureResultStatus.FINISHED,
            verified_at=verified_at,
            home_goals=2,
            away_goals=1,
            source_hash=observation.sha256,
        ),
        settled_at=NOW + timedelta(hours=4),
    )
    return factory, snapshot, prediction, (settlement, *scores)


def test_migration_creates_eight_append_only_tables_and_round_trips(
    tmp_path: Path,
) -> None:
    engine, url = _upgrade(tmp_path)
    assert PREQUENTIAL_TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        ) == "0015_data_torrent_opportunity"

    command.downgrade(_config(url), "0009_jalon12_observatory")
    assert PREQUENTIAL_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(_config(url), "head")
    assert PREQUENTIAL_TABLES <= set(sa.inspect(engine).get_table_names())


def test_sql_repository_is_idempotent_and_replay_is_identical(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        assert sql.append_model(model) is True
        assert sql.append_model(model) is False
    assert sql.append_snapshot(snapshot) is True
    assert sql.append_snapshot(snapshot) is False
    assert sql.append_prediction(prediction) is True
    assert sql.append_prediction(prediction) is False
    assert sql.append_settlement(settlement) is True
    assert sql.append_settlement(settlement) is False
    assert sql.append_scores(scores) == len(scores)
    assert sql.append_scores(scores) == 0
    assert sql.append_events(factory.ledger.events) == len(factory.ledger.events)
    assert sql.append_events(factory.ledger.events) == 0

    first = replay_prequential_rows(sql.replay_rows())
    second = replay_prequential_rows(sql.replay_rows())
    assert first == second
    assert first.status == "PREQUENTIAL_REPLAY_IDENTICAL"
    assert first.provider_calls == 0
    assert first.predictions == first.settlements == 1
    assert first.ledger_events == len(factory.ledger.events)


def _drop_sqlite_update_guard(
    connection: sa.Connection,
    table_name: str,
) -> None:
    trigger_name = f"trg_{table_name}_append_only_update"
    connection.exec_driver_sql(f'DROP TRIGGER "{trigger_name}"')


@pytest.mark.parametrize("tamper_target", ("prediction", "score"))
def test_operational_restore_replays_semantics_before_registry_consumption(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)

    prediction_table = sa.Table(
        "prequential_predictions",
        sa.MetaData(),
        autoload_with=engine,
    )
    score_table = sa.Table(
        "prequential_prediction_scores",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        if tamper_target == "prediction":
            _drop_sqlite_update_guard(connection, "prequential_predictions")
            forged_prediction = replace(
                prediction,
                probabilities={"HOME": 0.01, "DRAW": 0.49, "AWAY": 0.50},
                persisted_payload_hash=None,
            )
            connection.execute(
                prediction_table.update()
                .where(prediction_table.c.id == prediction.prediction_id)
                .values(
                    probabilities=dict(forged_prediction.probabilities),
                    payload_hash=forged_prediction.payload_hash,
                )
            )
        else:
            _drop_sqlite_update_guard(
                connection,
                "prequential_prediction_scores",
            )
            forged_score = replace(
                scores[0],
                outcome="AWAY",
                log_loss=0.1,
                brier_score=0.1,
                accurate=True,
            )
            connection.execute(
                score_table.update()
                .where(score_table.c.id == scores[0].score_id)
                .values(
                    outcome=forged_score.outcome,
                    log_loss=forged_score.log_loss,
                    brier_score=forged_score.brier_score,
                    accurate=forged_score.accurate,
                    score_hash=forged_score.score_hash,
                )
            )

    with pytest.raises(ValueError, match="PREQUENTIAL_REPLAY_"):
        _restore_factory(
            sql,
            factory.artifact_repository,
            now=NOW + timedelta(hours=5),
            feature_contract_hash=snapshot.feature_contract_hash,
            code_revision="test-revision",
        )


@pytest.mark.parametrize(
    "field_name,invalid_value",
    (
        ("log_loss", float("nan")),
        ("brier_score", float("inf")),
        ("reference_log_loss_delta", float("-inf")),
    ),
)
def test_prediction_score_rejects_non_finite_metrics(
    field_name: str,
    invalid_value: float,
) -> None:
    _factory_value, _snapshot_value, _prediction, settlement_and_scores = (
        _factory_records()
    )
    with pytest.raises(ValueError, match="PREQUENTIAL_SCORE_INVALID"):
        replace(settlement_and_scores[1], **{field_name: invalid_value})


def test_active_loaders_reject_tampered_durable_hashes_and_nested_events(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    factory.ledger.append(
        kind=PrequentialEventKind.PROMOTION_BLOCKED,
        recorded_at=NOW + timedelta(hours=5),
        stream_key="test:nested-event",
        evidence_hashes=(prediction.payload_hash,),
        details={"nested": {"status": "UNCHANGED"}},
    )
    assert sql.append_events(factory.ledger.events) == len(factory.ledger.events)
    assert sql.load_events()[-1].details["nested"] == {
        "status": "UNCHANGED"
    }

    model_table = sa.Table(
        "prequential_model_versions",
        sa.MetaData(),
        autoload_with=engine,
    )
    settlement_table = sa.Table(
        "prequential_fixture_settlements",
        sa.MetaData(),
        autoload_with=engine,
    )
    score_table = sa.Table(
        "prequential_prediction_scores",
        sa.MetaData(),
        autoload_with=engine,
    )
    event_table = sa.Table(
        "prequential_ledger_events",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        for table_name in (
            "prequential_model_versions",
            "prequential_fixture_settlements",
            "prequential_prediction_scores",
            "prequential_ledger_events",
        ):
            _drop_sqlite_update_guard(connection, table_name)
        connection.execute(
            model_table.update()
            .where(
                model_table.c.id
                == "model-" + next(iter(factory.models.values())).registry_hash
            )
            .values(created_at=NOW - timedelta(days=30))
        )
        connection.execute(
            settlement_table.update()
            .where(settlement_table.c.id == settlement.settlement_id)
            .values(source_hash="e" * 64)
        )
        connection.execute(
            score_table.update()
            .where(score_table.c.id == scores[0].score_id)
            .values(outcome="AWAY")
        )
        connection.execute(
            event_table.update()
            .where(event_table.c.id == factory.ledger.events[-1].event_id)
            .values(details={"nested": {"status": "MUTATED"}})
        )

    with pytest.raises(ValueError, match="PREQUENTIAL_MODEL_REGISTRY_HASH_MISMATCH"):
        sql.load_models()
    with pytest.raises(ValueError, match="PREQUENTIAL_SETTLEMENT_HASH_MISMATCH"):
        sql.load_settlements()
    with pytest.raises(ValueError, match="PREQUENTIAL_SCORE_HASH_MISMATCH"):
        sql.load_scores()
    with pytest.raises(ValueError, match="PREQUENTIAL_LEDGER_EVENT_HASH_MISMATCH"):
        sql.load_events()


def test_legacy_prediction_hash_restores_for_inspection_but_exact_replay_rejects_it(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, _ = _factory_records()
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    table = sa.Table(
        "prequential_predictions",
        sa.MetaData(),
        autoload_with=engine,
    )
    model_table = sa.Table(
        "prequential_model_versions",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        model_row_id = connection.scalar(
            sa.select(model_table.c.id).where(
                model_table.c.model_id == prediction.model_id,
                model_table.c.model_version == prediction.model_version,
            )
        )
        connection.execute(
            table.insert().values(
                id=prediction.prediction_id,
                prediction_id=prediction.prediction_id,
                fixture_record_id=prediction.fixture_record_id,
                fixture_id=prediction.fixture_id,
                competition=prediction.competition,
                market=prediction.market.value,
                cutoff_name=prediction.cutoff_name.value,
                cutoff_at=prediction.cutoff_at,
                kickoff_at=prediction.kickoff_at,
                predicted_at=prediction.predicted_at,
                model_version_id=model_row_id,
                model_id=prediction.model_id,
                model_version=prediction.model_version,
                feature_snapshot_id=prediction.feature_snapshot_id,
                probabilities=dict(prediction.probabilities),
                market_probabilities=(
                    dict(prediction.market_probabilities)
                    if prediction.market_probabilities is not None
                    else None
                ),
                odds_snapshot_id=prediction.odds_snapshot_id,
                code_revision=prediction.code_revision,
                payload_hash=prediction.legacy_payload_hash,
                status=prediction.status.value,
                rejection_reason=prediction.rejection_reason,
                append_only=True,
            )
        )
    assert sql.append_prediction(prediction) is False
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(table.c.payload_hash).where(
                table.c.id == prediction.prediction_id
            )
        ) == prediction.legacy_payload_hash
    loaded = sql.load_predictions()[0]
    assert loaded.legacy_payload_hash == prediction.legacy_payload_hash
    assert loaded.payload_hash == prediction.legacy_payload_hash
    assert loaded.computed_payload_hash == prediction.payload_hash
    assert loaded.scientific_lineage_status == "SCIENTIFIC_LINEAGE_NOT_PERSISTED"
    assert loaded.as_dict()["payload_hash"] == prediction.legacy_payload_hash
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_PREDICTION_SCIENTIFIC_LINEAGE_UNPROVEN",
    ):
        replay_prequential_rows(sql.replay_rows())


def test_prediction_loader_rejects_unknown_persisted_hash(tmp_path: Path) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, _ = _factory_records()
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    assert sql.append_prediction(prediction) is True
    table = sa.Table(
        "prequential_predictions",
        sa.MetaData(),
        autoload_with=engine,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER trg_prequential_predictions_append_only_update"
        )
        connection.execute(
            table.update()
            .where(table.c.id == prediction.prediction_id)
            .values(payload_hash="f" * 64)
        )
    with pytest.raises(ValueError, match="PREQUENTIAL_PERSISTED_PAYLOAD_HASH_INVALID"):
        sql.load_predictions()


def test_database_guards_reject_update_and_delete(tmp_path: Path) -> None:
    engine, _ = _upgrade(tmp_path)
    sql = PrequentialSQLRepository(engine)
    factory, _, _, _ = _factory_records()
    model = next(iter(factory.models.values()))
    sql.append_model(model)
    table = sa.Table(
        "prequential_model_versions",
        sa.MetaData(),
        autoload_with=engine,
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            table.update().where(table.c.model_id == model.model_id).values(
                status="MUTATED"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            table.delete().where(table.c.model_id == model.model_id)
        )


def test_replay_rejects_prediction_and_training_leakage() -> None:
    empty = {
        table: []
        for table in PREQUENTIAL_TABLES
    }
    leaked_prediction = {
        "id": "prediction-1",
        "status": "FROZEN",
        "predicted_at": NOW.isoformat(),
        "cutoff_at": (NOW - timedelta(seconds=1)).isoformat(),
        "kickoff_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    empty["prequential_predictions"] = [leaked_prediction]
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_PREDICTION_LEAKAGE",
    ):
        replay_prequential_rows(empty)


def test_replay_rejects_broken_exact_lineage_edges(tmp_path: Path) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, _ = _factory_records()
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    rows = sql.replay_rows()
    rows["prequential_predictions"][0]["feature_snapshot_id"] = "missing"
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_PREDICTION_HASH_INVALID",
    ):
        replay_prequential_rows(rows)


@pytest.mark.parametrize(
    ("table_name", "hash_field", "error_code"),
    (
        (
            "prequential_model_versions",
            "registry_hash",
            "PREQUENTIAL_REPLAY_MODEL_REGISTRY_HASH_INVALID",
        ),
        (
            "prequential_predictions",
            "payload_hash",
            "PREQUENTIAL_REPLAY_PREDICTION_HASH_INVALID",
        ),
        (
            "prequential_fixture_settlements",
            "settlement_hash",
            "PREQUENTIAL_REPLAY_SETTLEMENT_HASH_INVALID",
        ),
        (
            "prequential_prediction_scores",
            "score_hash",
            "PREQUENTIAL_REPLAY_SCORE_HASH_INVALID",
        ),
        (
            "prequential_metric_snapshots",
            "metric_hash",
            "PREQUENTIAL_REPLAY_METRIC_HASH_INVALID",
        ),
    ),
)
def test_replay_recomputes_durable_record_hashes(
    tmp_path: Path,
    table_name: str,
    hash_field: str,
    error_code: str,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_metric_snapshot(
        {
            "competition": prediction.competition,
            "market": prediction.market.value,
            "cutoff": prediction.cutoff_name.value,
            "model_id": prediction.model_id,
            "model_version": prediction.model_version,
            "month": prediction.predicted_at.strftime("%Y-%m"),
            "metrics": {
                "support": 1,
                "log_loss": scores[0].log_loss,
                "brier_score": scores[0].brier_score,
                "calibration_error": 0.1,
                "accuracy_descriptive": 1.0,
                "coverage": 1.0,
                "missingness": None,
                "reference_log_loss_delta": None,
            },
        },
        measured_at=NOW + timedelta(hours=4),
    )
    rows = sql.replay_rows()
    rows[table_name][0][hash_field] = "f" * 64
    with pytest.raises(ValueError, match=error_code):
        replay_prequential_rows(rows)


@pytest.mark.parametrize(
    ("kind", "error_code"),
    (
        ("snapshot", "PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_ID_INVALID"),
        ("prediction", "PREQUENTIAL_REPLAY_PREDICTION_ID_INVALID"),
        ("settlement", "PREQUENTIAL_REPLAY_SETTLEMENT_ID_INVALID"),
        ("score", "PREQUENTIAL_REPLAY_SCORE_ID_INVALID"),
    ),
)
def test_replay_rejects_self_hashed_noncanonical_record_ids(
    tmp_path: Path,
    kind: str,
    error_code: str,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    score = settlement_and_scores[1]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores((score,))
    sql.append_events(factory.ledger.events)
    rows = copy.deepcopy(sql.replay_rows())

    if kind == "snapshot":
        forged = replace(snapshot, snapshot_id="feature-forged-id")
        row = rows["prequential_feature_snapshots"][0]
        row["id"] = row["snapshot_id"] = forged.snapshot_id
        row["snapshot_hash"] = forged.snapshot_hash
    elif kind == "prediction":
        forged_prediction = replace(
            prediction,
            prediction_id="prediction-forged-id",
        )
        row = rows["prequential_predictions"][0]
        row["id"] = row["prediction_id"] = forged_prediction.prediction_id
        row["payload_hash"] = forged_prediction.computed_payload_hash
    elif kind == "settlement":
        forged_settlement = replace(
            settlement,
            settlement_id="settlement-forged-id",
        )
        row = rows["prequential_fixture_settlements"][0]
        row["id"] = row["settlement_id"] = forged_settlement.settlement_id
        row["settlement_hash"] = forged_settlement.settlement_hash
    else:
        forged_score = replace(score, score_id="score-forged-id")
        row = rows["prequential_prediction_scores"][0]
        row["id"] = row["score_id"] = forged_score.score_id
        row["score_hash"] = forged_score.score_hash

    with pytest.raises(ValueError, match=error_code):
        replay_prequential_rows(rows)


def test_replay_rejects_broken_feature_snapshot_revision_chain(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, _prediction, _settlement_and_scores = _factory_records()
    candidate = replace(
        snapshot,
        snapshot_id="feature-placeholder",
        created_at=snapshot.created_at + timedelta(minutes=1),
        quality={"status": "UNLINKED_REVISION"},
        supersedes_id=None,
    )
    candidate = replace(
        candidate,
        snapshot_id=feature_snapshot_record_id(
            fixture_record_id=candidate.fixture_record_id,
            fixture_id=candidate.fixture_id,
            market=candidate.market,
            cutoff_name=candidate.cutoff_name,
            cutoff_at=candidate.cutoff_at,
            feature_contract_version=candidate.feature_contract_version,
            feature_contract_hash=candidate.feature_contract_hash,
            values=candidate.values,
            missingness=candidate.missingness,
            provenance=candidate.provenance,
            quality=candidate.quality,
            supersedes_id=candidate.supersedes_id,
        ),
    )
    sql.append_snapshot(snapshot)
    sql.append_snapshot(candidate)
    factory.ledger.append(
        kind=PrequentialEventKind.FEATURE_SNAPSHOT_FROZEN,
        recorded_at=NOW,
        stream_key=f"feature:{candidate.fixture_record_id}",
        evidence_hashes=(candidate.snapshot_hash,),
        fixture_id=candidate.fixture_id,
        details={"snapshot_id": candidate.snapshot_id},
    )
    sql.append_events(factory.ledger.events)

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_CHAIN_INVALID",
    ):
        replay_prequential_rows(sql.replay_rows())


def test_replay_rejects_self_hashed_odds_snapshot_edge_tamper(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)
    rows = sql.replay_rows()
    forged = replace(prediction, odds_snapshot_id="odds-forged-self-hashed")
    prediction_row = rows["prequential_predictions"][0]
    prediction_row["odds_snapshot_id"] = forged.odds_snapshot_id
    prediction_row["payload_hash"] = forged.computed_payload_hash
    for event in rows["prequential_ledger_events"]:
        if event["kind"] == "PREDICTION_FROZEN":
            event["evidence_hashes"] = [forged.computed_payload_hash]
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_ODDS_SNAPSHOT_EDGE_MISMATCH",
    ):
        replay_prequential_rows(rows)


def test_replay_rejects_frozen_prediction_without_fixture_projection(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)
    rows = sql.replay_rows()

    missingness = dict(snapshot.missingness)
    missingness["team"] = True
    values = dict(snapshot.values)
    values["team"] = None
    provenance = dict(snapshot.provenance)
    provenance.pop("team")
    forged_snapshot = replace(
        snapshot,
        snapshot_id="feature-placeholder",
        values=values,
        missingness=missingness,
        provenance=provenance,
    )
    forged_snapshot = replace(
        forged_snapshot,
        snapshot_id=feature_snapshot_record_id(
            fixture_record_id=forged_snapshot.fixture_record_id,
            fixture_id=forged_snapshot.fixture_id,
            market=forged_snapshot.market,
            cutoff_name=forged_snapshot.cutoff_name,
            cutoff_at=forged_snapshot.cutoff_at,
            feature_contract_version=forged_snapshot.feature_contract_version,
            feature_contract_hash=forged_snapshot.feature_contract_hash,
            values=forged_snapshot.values,
            missingness=forged_snapshot.missingness,
            provenance=forged_snapshot.provenance,
            quality=forged_snapshot.quality,
            supersedes_id=forged_snapshot.supersedes_id,
        ),
    )
    forged_prediction = replace(
        prediction,
        feature_snapshot_id=forged_snapshot.snapshot_id,
        persisted_payload_hash=None,
    )
    snapshot_row = rows["prequential_feature_snapshots"][0]
    snapshot_row.update(forged_snapshot.as_manifest())
    snapshot_row["id"] = forged_snapshot.snapshot_id
    snapshot_row["snapshot_hash"] = forged_snapshot.snapshot_hash
    prediction_row = rows["prequential_predictions"][0]
    prediction_row["feature_snapshot_id"] = forged_snapshot.snapshot_id
    prediction_row["payload_hash"] = forged_prediction.computed_payload_hash
    for event in rows["prequential_ledger_events"]:
        if event["kind"] == "FEATURE_SNAPSHOT_FROZEN":
            event["evidence_hashes"] = [forged_snapshot.snapshot_hash]
        elif event["kind"] == "PREDICTION_FROZEN":
            event["evidence_hashes"] = [forged_prediction.computed_payload_hash]

    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_FIXTURE_PROJECTION_MISMATCH",
    ):
        replay_prequential_rows(rows)


def test_replay_rejects_result_for_different_provider_fixture(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)
    wrong_provider_fixture_id = "provider:different-fixture"
    observation = _persist_result_observation(
        factory.artifact_repository,
        fixture_id=settlement.result.fixture_id,
        fixture_record_id=settlement.result.fixture_record_id,
        provider_fixture_id=wrong_provider_fixture_id,
        attempt=2,
        observed_at=settlement.result.verified_at,
        record={
            "fixture": {
                "id": wrong_provider_fixture_id,
                "status": {"short": "FT"},
            },
            "goals": {
                "home": settlement.result.home_goals,
                "away": settlement.result.away_goals,
            },
        },
    )
    rows = sql.replay_rows()
    rows["prequential_fixture_settlements"][0]["source_hash"] = observation.sha256
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_RESULT_FIXTURE_IDENTITY_MISMATCH",
    ):
        _verify_replay_artifacts(
            artifacts=factory.artifact_repository,
            rows=rows,
        )


def test_replay_rejects_self_hashed_score_projection_tamper(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)
    rows = sql.replay_rows()
    original_score = scores[0]
    forged = replace(original_score, fixture_id="fixture-forged-self-hashed")
    score_row = rows["prequential_prediction_scores"][0]
    score_row.update(
        {
            "score_id": forged.score_id,
            "prediction_id": forged.prediction_id,
            "settlement_id": forged.settlement_id,
            "fixture_id": forged.fixture_id,
            "competition": forged.competition,
            "market": forged.market.value,
            "cutoff_name": forged.cutoff_name.value,
            "model_id": forged.model_id,
            "model_version": forged.model_version,
            "scored_at": forged.scored_at.isoformat(),
            "outcome": forged.outcome,
            "log_loss": forged.log_loss,
            "brier_score": forged.brier_score,
            "accurate": forged.accurate,
            "reference_log_loss_delta": forged.reference_log_loss_delta,
        }
    )
    score_row["score_hash"] = forged.score_hash
    for event in rows["prequential_ledger_events"]:
        if event["kind"] == "PREDICTION_SCORED":
            event["fixture_id"] = forged.fixture_id
            event["evidence_hashes"] = [forged.score_hash]
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_SCORE_PROJECTION_MISMATCH",
    ):
        replay_prequential_rows(rows)


def test_replay_rejects_self_hashed_false_metric_denominator(
    tmp_path: Path,
) -> None:
    engine, _ = _upgrade(tmp_path)
    _seed_fixture(engine)
    sql = PrequentialSQLRepository(engine)
    factory, snapshot, prediction, settlement_and_scores = _factory_records()
    settlement = settlement_and_scores[0]
    scores = settlement_and_scores[1:]
    for model in factory.models.values():
        sql.append_model(model)
    sql.append_snapshot(snapshot)
    sql.append_prediction(prediction)
    sql.append_settlement(settlement)
    sql.append_scores(scores)
    sql.append_events(factory.ledger.events)
    sql.append_metric_snapshot(
        {
            "competition": prediction.competition,
            "market": prediction.market.value,
            "cutoff": prediction.cutoff_name.value,
            "model_id": prediction.model_id,
            "model_version": prediction.model_version,
            "month": prediction.predicted_at.strftime("%Y-%m"),
            "metrics": {
                "support": 999,
                "log_loss": 0.0,
                "brier_score": 0.0,
                "calibration_error": 0.0,
                "accuracy_descriptive": 1.0,
                "coverage": 0.123,
                "missingness": 0.0,
                "reference_log_loss_delta": None,
            },
        },
        measured_at=NOW + timedelta(hours=4),
    )
    with pytest.raises(
        ValueError,
        match="PREQUENTIAL_REPLAY_METRIC_SEMANTICS_MISMATCH",
    ):
        replay_prequential_rows(sql.replay_rows())


def test_schema_contains_no_raw_payload_or_delete_surface() -> None:
    forbidden = {"payload", "raw_payload", "raw_body", "provider_response"}
    for table_name in PREQUENTIAL_TABLES:
        columns = set(Base.metadata.tables[table_name].c.keys())
        assert forbidden.isdisjoint(columns)
        assert "append_only" in columns
