"""Fenced in-process Alembic execution for the Chronos lifecycle."""

from __future__ import annotations

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from robin.chronos_production import ChronosProductionError
from robin.storage.database import database_url_object

_ALEMBIC_SESSION_OPTIONS = (
    "-c statement_timeout=300000 "
    "-c idle_session_timeout=60000 "
    "-c idle_in_transaction_session_timeout=60000"
)


def run_fenced_alembic(database_url: str, target: str) -> None:
    """Run Alembic in the fence-owning process with one injected connection."""

    engine = create_engine(
        database_url_object(database_url),
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 10,
            "options": _ALEMBIC_SESSION_OPTIONS,
        },
    )
    try:
        with engine.connect() as migration_connection:
            configuration = AlembicConfig(
                str(Path(__file__).resolve().parents[2] / "alembic.ini")
            )
            configuration.attributes["connection"] = migration_connection
            alembic_command.upgrade(configuration, target)
    except Exception:
        raise ChronosProductionError("CHRONOS_ALEMBIC_EXECUTION_FAILED") from None
    finally:
        engine.dispose()


__all__ = ["run_fenced_alembic"]
