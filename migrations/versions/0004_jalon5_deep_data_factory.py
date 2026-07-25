"""Jalon 5 : Deep Data Factory historique.

Revision ID: 0004_jalon5_deep_data_factory
Revises: 0003_jalon4_durable_shadow
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from robin.storage.historical_schema import HISTORICAL_TABLES, metadata

revision: str = "0004_jalon5_deep_data_factory"
down_revision: str | None = "0003_jalon4_durable_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_ORDER = [
    "api_football_coverage",
    "historical_ingestion_runs",
    "historical_backfill_tasks",
    "competitions",
    "seasons",
    "players",
    "coaches",
    "venues",
    "referees",
    "team_seasons",
    "player_seasons",
    "squads",
    "fixture_status_history",
    "fixture_events",
    "fixture_team_statistics",
    "fixture_player_statistics",
    "lineups",
    "lineup_players",
    "formations",
    "injuries",
    "suspensions",
    "transfers",
    "standings_snapshots",
    "feature_definitions",
    "feature_snapshots",
    "dataset_versions",
    "training_runs",
    "model_versions",
    "backtest_runs",
    "strategy_versions",
    "strategy_results",
]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in CREATE_ORDER:
        if table_name not in existing:
            metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(CREATE_ORDER):
        if table_name in HISTORICAL_TABLES and table_name in existing:
            metadata.tables[table_name].drop(bind=bind, checkfirst=True)
