"""Durcir le versionnage et l'immutabilité du registre Jalon 10.

Revision ID: 0007_jalon10_immutable_evidence
Revises: 0006_jalon10_pattern_ledger
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_jalon10_immutable_evidence"
down_revision: str | None = "0006_jalon10_pattern_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_TABLES = (
    "pattern_decisions",
    "pattern_settlements",
    "bankroll_events",
    "evidence_ledger",
)


def _replace_experiment_uniqueness(*, versioned: bool) -> None:
    columns = (
        ["preregistration_hash", "experiment_version"]
        if versioned
        else ["preregistration_hash"]
    )
    with op.batch_alter_table("experiment_registry") as batch_op:
        batch_op.drop_constraint(
            "uq_experiment_preregistration_hash",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_experiment_preregistration_hash",
            columns,
        )


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_append_only_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only table % cannot be mutated', TG_TABLE_NAME;
            END;
            $$;
            """
        )
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION robin_reject_append_only_mutation();
                """
            )
        return

    if dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for operation in ("UPDATE", "DELETE"):
                suffix = operation.lower()
                op.execute(
                    f"""
                    CREATE TRIGGER trg_{table}_append_only_{suffix}
                    BEFORE {operation} ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, 'append-only table cannot be mutated');
                    END;
                    """
                )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in APPEND_ONLY_TABLES:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"
            )
        op.execute(
            "DROP FUNCTION IF EXISTS robin_reject_append_only_mutation()"
        )
        return

    if dialect == "sqlite":
        for table in APPEND_ONLY_TABLES:
            for operation in ("update", "delete"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"trg_{table}_append_only_{operation}"
                )


def upgrade() -> None:
    _replace_experiment_uniqueness(versioned=True)
    _create_append_only_guards()


def downgrade() -> None:
    _drop_append_only_guards()
    _replace_experiment_uniqueness(versioned=False)
