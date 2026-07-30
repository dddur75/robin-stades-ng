from __future__ import annotations

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
    freeze_feature_snapshot,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    ModelRole,
    ModelScope,
    PredictionMarket,
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
)
from robin.storage.database import build_engine
from robin.storage.models import Base
from robin.storage.prequential_models import PREQUENTIAL_TABLES

NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


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
    )
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {"margin": 0.05}
    values["team"] = {"home": "api-football:1", "away": "api-football:2"}
    availability["market"] = availability["team"] = True
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
        provenance={
            family: {
                "source": "TEST",
                "observed_at": (NOW - timedelta(minutes=10)).isoformat(),
            }
            for family in ("market", "team")
        },
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
    settlement, scores, _ = factory.settle(
        VerifiedFixtureResult(
            fixture_record_id="fixture-record-1",
            fixture_id="api-football:42",
            competition="Ligue 1",
            kickoff_at=NOW + timedelta(hours=2),
            status=FixtureResultStatus.FINISHED,
            verified_at=NOW + timedelta(hours=4),
            home_goals=2,
            away_goals=1,
            source_hash="b" * 64,
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
        ) == "0013_historical_evidence_index"

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


def test_schema_contains_no_raw_payload_or_delete_surface() -> None:
    forbidden = {"payload", "raw_payload", "raw_body", "provider_response"}
    for table_name in PREQUENTIAL_TABLES:
        columns = set(Base.metadata.tables[table_name].c.keys())
        assert forbidden.isdisjoint(columns)
        assert "append_only" in columns
