"""Jalon 4 : registre prospectif durable.

Revision ID: 0003_jalon4_durable_shadow
Revises: 0002_jalon2_shadow
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from robin.storage.durable_schema import JALON4_TABLES, metadata

revision: str = "0003_jalon4_durable_shadow"
down_revision: str | None = "0002_jalon2_shadow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_ORDER = [
    "ingestion_runs",
    "raw_payloads",
    "provider_requests",
    *sorted(
        JALON4_TABLES
        - {"ingestion_runs", "raw_payloads", "provider_requests"}
    ),
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
        if table_name in existing:
            metadata.tables[table_name].drop(bind=bind, checkfirst=True)
