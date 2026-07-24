"""Mise en service sûre de Neon et migration du registre shadow."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text

from robin.storage.database import (
    DatabaseConfigurationError,
    alembic_database_url,
    build_engine,
    normalize_database_url,
)
from robin.storage.durable_schema import JALON4_TABLES, metadata

if __package__:
    from scripts.manage_durable_registry import audit_database, persist_registry
else:
    from manage_durable_registry import audit_database, persist_registry

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", alembic_database_url(database_url))
    return config


def table_row_counts(database_url: str) -> dict[str, int]:
    engine = build_engine(database_url)
    names = sorted(
        name
        for name in inspect(engine).get_table_names()
        if name != "alembic_version"
    )
    unknown_tables = set(names) - set(metadata.tables)
    if unknown_tables:
        raise RuntimeError("tables inconnues présentes ; rollback refusé")
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for name in names:
            table = metadata.tables.get(name)
            assert table is not None
            counts[name] = int(
                connection.execute(
                    select(func.count()).select_from(table)
                ).scalar_one()
            )
    return counts


def migration_revision(database_url: str) -> str | None:
    engine = build_engine(database_url)
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


def bootstrap(
    *,
    registry: Path,
    database_url: str,
    controlled_rollback: bool,
) -> dict[str, object]:
    normalized = normalize_database_url(database_url)
    engine = build_engine(normalized)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    config = alembic_config(normalized)
    command.upgrade(config, "head")
    tables_after_upgrade = set(inspect(engine).get_table_names())
    missing_tables = sorted(JALON4_TABLES - tables_after_upgrade)
    if missing_tables:
        raise RuntimeError("tables durables manquantes après migration")
    rollback_performed = False
    rollback_skipped_reason: str | None = None
    if controlled_rollback:
        counts_before_rollback = table_row_counts(normalized)
        if any(counts_before_rollback.values()):
            rollback_skipped_reason = "DATA_ALREADY_PRESENT"
        else:
            command.downgrade(config, "0002_jalon2_shadow")
            remaining = set(inspect(engine).get_table_names())
            if JALON4_TABLES & remaining:
                raise RuntimeError("rollback contrôlé incomplet")
            command.upgrade(config, "head")
            rollback_performed = True
    revision = migration_revision(normalized)
    first = persist_registry(registry, normalized)
    second = persist_registry(registry, normalized)
    audit = audit_database(registry, normalized)
    if audit["status"] != "PASSED":
        raise RuntimeError("audit PostgreSQL incomplet")
    if second["records_inserted"] or second["raw_payloads_inserted"]:
        raise RuntimeError("replay non idempotent")
    return {
        "status": "NEON_BOOTSTRAP_VERIFIED",
        "postgresql": "CONNECTED_AND_PERSISTED",
        "driver": "postgresql+psycopg",
        "ssl_required": "sslmode=require" in normalized,
        "migration_revision": revision,
        "controlled_rollback_requested": controlled_rollback,
        "controlled_rollback_performed": rollback_performed,
        "controlled_rollback_skipped_reason": rollback_skipped_reason,
        "first_persistence": first,
        "second_persistence": second,
        "audit": audit,
        "replay": {
            "provider_calls": 0,
            "quota_consumed": 0,
            "records_inserted": second["records_inserted"],
            "duplicates_avoided": second["duplicates_avoided"],
        },
        "production_status": "PRODUCTION_LOCKED",
        "strategy_promotion": "NONE",
    }


def safe_failure(error: Exception) -> dict[str, object]:
    if isinstance(error, DatabaseConfigurationError):
        error_code = "INVALID_DATABASE_CONFIGURATION"
    elif isinstance(error, RuntimeError):
        error_code = "NEON_INTEGRITY_CHECK_FAILED"
    else:
        error_code = "NEON_CONNECTION_OR_MIGRATION_FAILED"
    return {
        "status": "FAILED",
        "error_code": error_code,
        "message": "Échec Neon ; valeur de connexion masquée.",
        "production_status": "PRODUCTION_LOCKED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--controlled-rollback", action="store_true")
    args = parser.parse_args()
    database_url = os.getenv("ROBIN_DATABASE_URL")
    try:
        result = bootstrap(
            registry=args.registry,
            database_url=database_url or "",
            controlled_rollback=args.controlled_rollback,
        )
    except Exception as error:  # aucun détail fournisseur ou secret dans les logs
        result = safe_failure(error)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
