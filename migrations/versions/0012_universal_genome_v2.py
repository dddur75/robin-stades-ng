"""Universal Football Hypothesis Genome V2.

Revision ID: 0012_universal_genome_v2
Revises: 0011_hypothesis_intelligence_v1
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from robin.storage import universal_genome_models as universal_genome_models
from robin.storage.models import Base

revision: str = "0012_universal_genome_v2"
down_revision: str | None = "0011_hypothesis_intelligence_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATE_ORDER = (
    "football_property_definitions",
    "hypothesis_campaigns",
    "hypothesis_tree_nodes",
    "hypothesis_derivation_edges",
    "source_field_classifications",
)


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_universal_genome_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only universal genome table % cannot be mutated',
                    TG_TABLE_NAME;
            END;
            $$;
            """
        )
        for table_name in CREATE_ORDER:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION robin_reject_universal_genome_mutation();
                """
            )
    elif dialect == "sqlite":
        for table_name in CREATE_ORDER:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"""
                    CREATE TRIGGER
                        trg_{table_name}_append_only_{operation.lower()}
                    BEFORE {operation} ON {table_name}
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'append-only universal genome table cannot be mutated'
                        );
                    END;
                    """
                )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in CREATE_ORDER:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}")
        op.execute("DROP FUNCTION IF EXISTS robin_reject_universal_genome_mutation()")
    elif dialect == "sqlite":
        for table_name in CREATE_ORDER:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_{operation}")


def upgrade() -> None:
    _ = universal_genome_models
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in CREATE_ORDER:
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _create_append_only_guards()


def downgrade() -> None:
    bind = op.get_bind()
    _drop_append_only_guards()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(CREATE_ORDER):
        if table_name in existing:
            Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
