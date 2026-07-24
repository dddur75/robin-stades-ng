"""jalon 2 shadow

Revision ID: 0002_jalon2_shadow
Revises: 0001_jalon1
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from robin.storage.models import Base

revision: str = "0002_jalon2_shadow"
down_revision: str | None = "0001_jalon1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JALON2_TABLES = {
    "provider_call_logs",
    "shadow_predictions",
    "shadow_decisions",
    "legacy_migration_runs",
    "operational_metrics",
    "operational_alerts",
}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in sorted(JALON2_TABLES - existing):
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in sorted(JALON2_TABLES & existing, reverse=True):
        Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
