from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from robin.storage.database import build_engine


def alembic_config(database_url: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_upgrade_est_idempotente_et_downgrade_fonctionne(tmp_path) -> None:
    database = tmp_path / "jalon1.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    tables = set(inspect(build_engine(url)).get_table_names())

    assert {
        "internal_entities",
        "provider_mappings",
        "raw_observations",
        "fixtures",
        "feature_values",
        "bookmaker_quotes",
        "market_opportunities",
        "selected_bets",
        "settled_bets",
        "quality_checks",
        "pipeline_runs",
        "provider_call_logs",
        "shadow_predictions",
        "shadow_decisions",
        "legacy_migration_runs",
        "operational_metrics",
        "operational_alerts",
    }.issubset(tables)

    command.downgrade(config, "base")
    remaining = set(inspect(build_engine(url)).get_table_names())
    assert remaining <= {"alembic_version"}
