"""Fondation transactionnelle du jalon 1.

Revision ID: 0001_jalon1
Revises:
Create Date: 2026-07-24
"""

from typing import Sequence

from alembic import op

from robin.storage.models import Base

revision: str = "0001_jalon1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Révision bootstrap : le schéma versionné est défini par les modèles du
    # commit. Les prochaines évolutions utiliseront des opérations explicites.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
