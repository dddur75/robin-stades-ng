"""Fondation transactionnelle du jalon 1.

Revision ID: 0001_jalon1
Revises:
Create Date: 2026-07-24
"""

from typing import Sequence

from alembic import op
from sqlalchemy import inspect

from robin.storage.models import Base

revision: str = "0001_jalon1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JALON1_TABLES = [
    "internal_entities",
    "pipeline_runs",
    "raw_observations",
    "provider_mappings",
    "fixtures",
    "feature_values",
    "quality_checks",
    "bookmaker_quotes",
    "market_opportunities",
    "selected_bets",
    "settled_bets",
]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in JALON1_TABLES:
        if table_name not in existing:
            Base.metadata.tables[table_name].create(
                bind=bind,
                checkfirst=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(JALON1_TABLES):
        if table_name in existing:
            Base.metadata.tables[table_name].drop(
                bind=bind,
                checkfirst=True,
            )
