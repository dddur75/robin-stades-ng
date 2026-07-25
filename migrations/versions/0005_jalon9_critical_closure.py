"""Jalon 9 : priorité métier du backfill.

Revision ID: 0005_jalon9_critical_closure
Revises: 0004_jalon5_deep_data_factory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_jalon9_critical_closure"
down_revision: str | None = "0004_jalon5_deep_data_factory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {
        str(column["name"])
        for column in inspector.get_columns("historical_backfill_tasks")
    }
    if "business_value_priority" not in columns:
        op.add_column(
            "historical_backfill_tasks",
            sa.Column(
                "business_value_priority",
                sa.String(length=40),
                nullable=False,
                server_default="P4_DEFERRED",
            ),
        )
    indexes = {
        str(index["name"])
        for index in inspect(op.get_bind()).get_indexes(
            "historical_backfill_tasks"
        )
    }
    if "ix_historical_tasks_business_ready" not in indexes:
        op.create_index(
            "ix_historical_tasks_business_ready",
            "historical_backfill_tasks",
            ["status", "business_value_priority", "season"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    indexes = {
        str(index["name"])
        for index in inspector.get_indexes("historical_backfill_tasks")
    }
    if "ix_historical_tasks_business_ready" in indexes:
        op.drop_index(
            "ix_historical_tasks_business_ready",
            table_name="historical_backfill_tasks",
        )
    columns = {
        str(column["name"])
        for column in inspect(op.get_bind()).get_columns(
            "historical_backfill_tasks"
        )
    }
    if "business_value_priority" in columns:
        op.drop_column("historical_backfill_tasks", "business_value_priority")
