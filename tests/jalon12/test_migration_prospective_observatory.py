from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from robin.storage.database import build_engine
from robin.storage.models import Base
from scripts.run_prospective_observatory import (
    EXPECTED_ALEMBIC_REVISION,
    SQLAlchemyOperationalState,
)

JALON12_TABLES = {
    "prospective_fixtures",
    "capture_windows",
    "capture_attempts",
    "capture_receipts",
    "prospective_payload_index",
    "prospective_player_status",
    "prospective_injuries",
    "prospective_lineups",
    "prospective_formations",
    "prospective_odds_snapshots",
    "temporal_data_gates",
    "provider_budget_ledger",
}


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_upgrade_downgrade_upgrade_and_append_only_guards(tmp_path: Path) -> None:
    database = tmp_path / "jalon12.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert JALON12_TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
            "0013_historical_evidence_index"
        )

    fixture = sa.Table(
        "prospective_fixtures",
        sa.MetaData(),
        autoload_with=engine,
    )
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    row = {
        "id": "fixture-record-1",
        "idempotency_key": "fixture:api-football:123",
        "fixture_id": "fixture-1",
        "competition": "Ligue 1",
        "season": "2026",
        "phase": "Regular Season",
        "home_team_id": "home",
        "away_team_id": "away",
        "kickoff_at": now,
        "provider": "api-football",
        "provider_fixture_id": "123",
        "registered_at": now,
        "registry_hash": "a" * 64,
        "code_revision": "revision-j12",
        "cancelled": False,
        "kickoff_reliable": True,
        "append_only": True,
    }
    with engine.begin() as connection:
        connection.execute(fixture.insert().values(**row))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            fixture.update().where(fixture.c.id == row["id"]).values(phase="Mutated")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(fixture.delete().where(fixture.c.id == row["id"]))

    command.downgrade(config, "0008_jalon11_deep_football")
    assert JALON12_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert JALON12_TABLES <= set(sa.inspect(engine).get_table_names())


def test_orm_and_migration_have_no_raw_payload_body_columns() -> None:
    forbidden = {"payload", "payload_body", "raw_payload", "raw_body"}
    for table_name in JALON12_TABLES:
        table = Base.metadata.tables[table_name]
        assert forbidden.isdisjoint(table.c.keys())
        assert "append_only" in table.c
        timestamp_columns = [
            column for column in table.c if isinstance(column.type, sa.DateTime)
        ]
        assert timestamp_columns
        assert all(column.type.timezone for column in timestamp_columns)


def test_raw_payload_key_is_shareable_but_receipt_key_stays_unique(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jalon12-payload-key.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_config(url), "head")
    engine = build_engine(url)
    inspector = sa.inspect(engine)

    for table_name in ("capture_receipts", "prospective_payload_index"):
        orm_table = Base.metadata.tables[table_name]
        assert orm_table.c.r2_key.unique is not True
        assert orm_table.c.receipt_r2_key.unique is True

        unique_column_sets = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        }
        assert ("r2_key",) not in unique_column_sets
        assert ("receipt_r2_key",) in unique_column_sets
        indexed_column_sets = {
            tuple(index["column_names"])
            for index in inspector.get_indexes(table_name)
        }
        assert ("r2_key",) in indexed_column_sets


def test_revision_fits_alembic_version_column_and_postgresql_ddl_compiles() -> None:
    config = _config("sqlite+pysqlite:///:memory:")
    revision = ScriptDirectory.from_config(config).get_current_head()
    assert revision == "0013_historical_evidence_index"
    assert revision == EXPECTED_ALEMBIC_REVISION
    assert len(revision) <= 32
    for table_name in JALON12_TABLES:
        ddl = str(
            CreateTable(Base.metadata.tables[table_name]).compile(
                dialect=postgresql.dialect()
            )
        )
        assert f"CREATE TABLE {table_name}" in ddl


def test_operational_state_rejects_the_previous_schema_revision(
    tmp_path: Path,
) -> None:
    database = tmp_path / "previous-schema.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _config(url)
    command.upgrade(config, "0012_universal_genome_v2")
    engine = build_engine(url)

    with pytest.raises(
        RuntimeError,
        match="^PROSPECTIVE_DATABASE_REVISION_0013_REQUIRED$",
    ):
        SQLAlchemyOperationalState(engine)
