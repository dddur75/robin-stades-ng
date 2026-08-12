from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from robin.storage.database import alembic_database_url
from robin.storage.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("ROBIN_DATABASE_URL") or config.get_main_option(
    "sqlalchemy.url"
)
config.set_main_option("sqlalchemy.url", alembic_database_url(database_url))

target_metadata = Base.metadata


def _configure_context(*, connection: object | None = None) -> None:
    """Pin Alembic's version table to public on PostgreSQL."""

    common: dict[str, Any] = {
        "target_metadata": target_metadata,
        "compare_type": True,
    }
    if connection is None:
        url = config.get_main_option("sqlalchemy.url") or ""
        common.update(
            {
                "url": url,
                "literal_binds": True,
                "dialect_opts": {"paramstyle": "named"},
            }
        )
        if url.startswith("postgresql"):
            common["version_table_schema"] = "public"
    else:
        common["connection"] = connection
        dialect = getattr(connection, "dialect", None)
        if getattr(dialect, "name", None) == "postgresql":
            common["version_table_schema"] = "public"
    context.configure(**common)


def run_migrations_offline() -> None:
    _configure_context()
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        _configure_context(connection=supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _configure_context(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
