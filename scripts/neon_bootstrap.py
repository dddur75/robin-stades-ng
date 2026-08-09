"""Synchronisation legacy du registre, sans autorité de migration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import MetaData, func, inspect, select, text

from robin.storage.database import (
    DatabaseConfigurationError,
    build_engine,
    normalize_database_url,
)
from robin.storage.durable_schema import JALON4_TABLES, metadata

if __package__:
    from scripts.manage_durable_registry import audit_database, persist_registry
else:
    from manage_durable_registry import (  # type: ignore[import-not-found,no-redef]
        audit_database,
        persist_registry,
    )

HISTORICAL_EVIDENCE_INDEX_TABLES = frozenset(
    {
        "historical_fixture_evidence_indexes",
        "hypothesis_evidence_artifact_indexes",
        "hypothesis_fixture_membership_indexes",
        "hypothesis_historical_evidence_summaries",
    }
)
CHRONOS_CONTROL_PLANE_TABLES = frozenset(
    {"chronos_effect_authorities", "chronos_effect_events"}
)
EXPECTED_REVISION = "0013_historical_evidence_index"


def table_row_counts(database_url: str) -> dict[str, int]:
    engine = build_engine(database_url)
    names = sorted(
        name
        for name in inspect(engine).get_table_names()
        if name != "alembic_version"
    )
    additional_tables = (
        HISTORICAL_EVIDENCE_INDEX_TABLES | CHRONOS_CONTROL_PLANE_TABLES
    )
    known_tables = set(metadata.tables) | additional_tables
    unknown_tables = set(names) - known_tables
    if unknown_tables:
        raise RuntimeError("tables inconnues présentes ; rollback refusé")
    reflected_metadata = MetaData()
    reflected_names = sorted(set(names) & additional_tables)
    if reflected_names:
        reflected_metadata.reflect(bind=engine, only=reflected_names)
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for name in names:
            table = metadata.tables.get(name)
            if table is None:
                table = reflected_metadata.tables.get(name)
            if table is None:
                raise RuntimeError(
                    "table connue introuvable ; rollback refusé"
                )
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
) -> dict[str, object]:
    normalized = normalize_database_url(database_url)
    engine = build_engine(normalized)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    revision = migration_revision(normalized)
    if revision != EXPECTED_REVISION:
        raise RuntimeError("DATABASE_MIGRATION_REQUIRED")
    tables = set(inspect(engine).get_table_names())
    missing_tables = sorted(JALON4_TABLES - tables)
    if missing_tables:
        raise RuntimeError("DATABASE_MIGRATION_REQUIRED")
    first = persist_registry(registry, normalized)
    second = persist_registry(registry, normalized)
    audit = audit_database(registry, normalized)
    if audit["status"] != "PASSED":
        raise RuntimeError("audit PostgreSQL incomplet")
    if second["records_inserted"] or second["raw_payloads_inserted"]:
        raise RuntimeError("replay non idempotent")
    return {
        "status": "NEON_BOOTSTRAP_VERIFIED_READ_ONLY_REVISION",
        "postgresql": "CONNECTED_AND_PERSISTED",
        "driver": "postgresql+psycopg",
        "ssl_required": "sslmode=require" in normalized,
        "migration_revision": revision,
        "automatic_migration_performed": False,
        "controlled_rollback_performed": False,
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
    args = parser.parse_args()
    database_url = os.getenv("ROBIN_DATABASE_URL")
    try:
        result = bootstrap(
            registry=args.registry,
            database_url=database_url or "",
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
