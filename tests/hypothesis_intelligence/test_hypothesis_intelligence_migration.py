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
from robin.storage.hypothesis_models import HYPOTHESIS_TABLES
from robin.storage.models import Base

HEAD = "0014_chronos_control_plane_v2"


def _config(url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migration_round_trip_and_append_only_guards(tmp_path: Path) -> None:
    database = tmp_path / "hypothesis-intelligence.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = _config(url)
    command.upgrade(config, "head")
    engine = build_engine(url)
    assert HYPOTHESIS_TABLES <= set(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD

    registry = sa.Table(
        "hypothesis_registry",
        sa.MetaData(),
        autoload_with=engine,
    )
    row = {
        "id": "registry-J10-M001",
        "hypothesis_id": "J10-M001",
        "origin": "MACHINE_DISCOVERED",
        "family": "1X2",
        "market": "1X2_AWAY",
        "selection": "AWAY",
        "status": "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING",
        "canonical_fingerprint": "a" * 64,
        "created_at": datetime(2026, 7, 29, tzinfo=UTC),
        "promotion_locked": True,
        "append_only": True,
    }
    with engine.begin() as connection:
        connection.execute(registry.insert().values(**row))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            registry.update().where(registry.c.id == row["id"]).values(status="VALIDATED")
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(registry.delete().where(registry.c.id == row["id"]))

    events = sa.Table(
        "hypothesis_status_events",
        sa.MetaData(),
        autoload_with=engine,
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            events.insert().values(
                id="event-forbidden-validation",
                hypothesis_id="J10-M001",
                sequence_no=0,
                kind="HYPOTHESIS_VALIDATED",
                recorded_at=datetime(2026, 7, 29, tzinfo=UTC),
                code_revision="0057e1caf57bd4d6084ab456f7ee386fff728c2c",
                evidence_hashes=["b" * 64],
                details={"decision": "AUTOMATIC"},
                previous_hash="0" * 64,
                event_hash="c" * 64,
                automatic=True,
                production_locked=True,
                real_bets=False,
                promoted=False,
                append_only=True,
            )
        )

    command.downgrade(config, "0010_prequential_v1")
    assert HYPOTHESIS_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert HYPOTHESIS_TABLES <= set(sa.inspect(engine).get_table_names())


def test_schema_is_bounded_versioned_and_contains_no_raw_provider_payload() -> None:
    forbidden = {
        "payload",
        "payload_body",
        "raw_payload",
        "raw_body",
        "provider_response",
    }
    for table_name in HYPOTHESIS_TABLES:
        table = Base.metadata.tables[table_name]
        assert forbidden.isdisjoint(table.c.keys())
        assert "append_only" in table.c
    revision = ScriptDirectory.from_config(
        _config("sqlite+pysqlite:///:memory:")
    ).get_current_head()
    assert revision == HEAD
    assert len(revision) <= 32
