"""Fail-closed, read-only Alembic revision guard for ordinary workloads."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping

from sqlalchemy import text

from robin.storage.database import build_engine


class DatabaseMigrationRequired(RuntimeError):
    """Raised when the database is not at the one explicitly allowed revision."""


def current_revisions(database_url: str) -> tuple[str, ...]:
    """Read the qualified PostgreSQL Alembic row without migration code."""
    engine = build_engine(database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise DatabaseMigrationRequired("DATABASE_MIGRATION_REQUIRED")
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            )
            return tuple(str(row[0]) for row in rows)
    finally:
        engine.dispose()


def require_database_revision(database_url: str, expected: str) -> None:
    """Require one exact revision and fail closed on every other state."""
    if not database_url or current_revisions(database_url) != (expected,):
        raise DatabaseMigrationRequired("DATABASE_MIGRATION_REQUIRED")


def database_url_from_environment(environment: Mapping[str, str]) -> str:
    """Resolve only the explicit runtime URL without a legacy fallback."""
    return environment.get("ROBIN_DATABASE_URL", "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    try:
        require_database_revision(
            database_url_from_environment(os.environ),
            args.expected,
        )
    except Exception:
        print("DATABASE_MIGRATION_REQUIRED")
        raise SystemExit(1) from None
    print(f"DATABASE_REVISION_VERIFIED:{args.expected}")


if __name__ == "__main__":
    main()
