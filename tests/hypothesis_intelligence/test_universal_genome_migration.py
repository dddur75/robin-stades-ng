from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from robin.storage.database import build_engine
from robin.storage.universal_genome_models import UNIVERSAL_GENOME_TABLES

HEAD = "0013_historical_evidence_index"


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_universal_genome_migration_is_append_only(tmp_path: Path) -> None:
    database = tmp_path / "universal-genome.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert UNIVERSAL_GENOME_TABLES <= set(sa.inspect(engine).get_table_names())
    properties = sa.Table(
        "football_property_definitions",
        sa.MetaData(),
        autoload_with=engine,
    )
    row = {
        "id": "property-test-1.0.0",
        "property_id": "football:test",
        "version": "1.0.0",
        "family": "TEST",
        "subfamily": "TEST",
        "entity": "MATCH",
        "data_type": "QUANTITY",
        "source": "TEST",
        "source_field": "test",
        "availability_status": "DATA_GATE_BLOCKED",
        "definition": {"missingness": "MISSING_NOT_ZERO"},
        "property_hash": "a" * 64,
        "created_at": datetime(2026, 7, 29, tzinfo=UTC),
        "append_only": True,
    }
    with engine.begin() as connection:
        connection.execute(properties.insert().values(**row))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            properties.update()
            .where(properties.c.id == row["id"])
            .values(availability_status="READY")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(properties.delete().where(properties.c.id == row["id"]))
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD


def test_universal_genome_is_single_migration_head() -> None:
    revision = ScriptDirectory.from_config(
        _config("sqlite+pysqlite:///:memory:")
    ).get_current_head()
    assert revision == HEAD
    assert len(revision) <= 32
