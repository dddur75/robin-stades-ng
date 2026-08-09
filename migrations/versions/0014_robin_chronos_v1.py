"""Robin Chronos known-at and point-in-time price observatory V1.

Revision ID: 0014_robin_chronos_v1
Revises: 0013_historical_evidence_index
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from alembic import op
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Connection

from robin.storage import chronos_models as chronos_models
from robin.storage import prospective_models as prospective_models  # noqa: F401
from robin.storage.models import Base

revision = "0014_robin_chronos_v1"
down_revision = "0013_historical_evidence_index"
branch_labels = None
depends_on = None

CREATE_ORDER = chronos_models.CHRONOS_TABLE_NAMES


def _stable_payload_index_id(receipt_hash: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"robin:j12:payload-index:{receipt_hash}",
        )
    )


def _same(left: object, right: object) -> bool:
    return str(left) == str(right) or left == right


def _expected_index(receipt: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": _stable_payload_index_id(str(receipt["receipt_hash"])),
        "receipt_id": receipt["id"],
        "fixture_id": receipt["fixture_id"],
        "family": receipt["family"],
        "r2_key": receipt["r2_key"],
        "receipt_r2_key": receipt["receipt_r2_key"],
        "payload_sha256": receipt["payload_sha256"],
        "payload_bytes": receipt["payload_bytes"],
        "stored_bytes": receipt["stored_bytes"],
        "observed_at": receipt["observed_at"],
        "indexed_at": receipt["materialized_at"],
        "code_revision": receipt["code_revision"],
        "append_only": True,
    }


def _reconcile_payload_index(connection: Connection) -> int:
    names = set(inspect(connection).get_table_names())
    if not {"capture_receipts", "prospective_payload_index"} <= names:
        raise RuntimeError("CHRONOS_PAYLOAD_INDEX_PREREQUISITES_MISSING")
    metadata = MetaData()
    receipts = Table("capture_receipts", metadata, autoload_with=connection)
    indexes = Table("prospective_payload_index", metadata, autoload_with=connection)
    existing = {
        str(row["receipt_id"]): row
        for row in connection.execute(select(indexes)).mappings()
    }
    inserted = 0
    for receipt in connection.execute(select(receipts)).mappings():
        expected = _expected_index(receipt)
        current = existing.get(str(receipt["id"]))
        if current is not None:
            if any(not _same(current[key], value) for key, value in expected.items()):
                raise RuntimeError(
                    "CHRONOS_PAYLOAD_INDEX_DIVERGENCE:"
                    f"{receipt['receipt_hash']}"
                )
            continue
        connection.execute(indexes.insert().values(**expected))
        inserted += 1
    orphan = set(existing) - {
        str(value)
        for value in connection.execute(select(receipts.c.id)).scalars()
    }
    if orphan:
        raise RuntimeError("CHRONOS_PAYLOAD_INDEX_ORPHAN")
    return inserted


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_chronos_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only Chronos table % cannot be mutated',
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
                EXECUTE FUNCTION robin_reject_chronos_mutation();
                """
            )
    elif dialect == "sqlite":
        for table_name in CREATE_ORDER:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"""
                    CREATE TRIGGER trg_{table_name}_append_only_{operation.lower()}
                    BEFORE {operation} ON {table_name}
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'append-only Chronos table cannot be mutated'
                        );
                    END;
                    """
                )


def _create_attempt_guard() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_enforce_chronos_attempt_limit()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                intent capture_intents%ROWTYPE;
            BEGIN
                SELECT * INTO intent
                FROM capture_intents
                WHERE window_record_id = NEW.window_record_id;
                IF FOUND AND (
                    NEW.attempt_number > intent.max_technical_attempts
                    OR NEW.fixture_id <> intent.fixture_id
                    OR NEW.family <> intent.family
                    OR (
                        NEW.provider_calls > 0
                        AND NEW.provider <> intent.source
                    )
                ) THEN
                    RAISE EXCEPTION 'Chronos capture attempt exceeds immutable intent';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_capture_attempts_chronos_limit
            BEFORE INSERT ON capture_attempts
            FOR EACH ROW
            EXECUTE FUNCTION robin_enforce_chronos_attempt_limit();
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_capture_attempts_chronos_limit
            BEFORE INSERT ON capture_attempts
            WHEN EXISTS (
                SELECT 1 FROM capture_intents AS intent
                WHERE intent.window_record_id = NEW.window_record_id
                  AND (
                    NEW.attempt_number > intent.max_technical_attempts
                    OR NEW.fixture_id <> intent.fixture_id
                    OR NEW.family <> intent.family
                    OR (
                      NEW.provider_calls > 0
                      AND NEW.provider <> intent.source
                    )
                  )
            )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Chronos capture attempt exceeds immutable intent'
                );
            END;
            """
        )


def _drop_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_capture_attempts_chronos_limit "
            "ON capture_attempts"
        )
        op.execute("DROP FUNCTION IF EXISTS robin_enforce_chronos_attempt_limit()")
        for table_name in CREATE_ORDER:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
                f"ON {table_name}"
            )
        op.execute("DROP FUNCTION IF EXISTS robin_reject_chronos_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_capture_attempts_chronos_limit")
        for table_name in CREATE_ORDER:
            for operation in ("update", "delete"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"trg_{table_name}_append_only_{operation}"
                )


def upgrade() -> None:
    bind = op.get_bind()
    _reconcile_payload_index(bind)
    existing = set(inspect(bind).get_table_names())
    for table_name in CREATE_ORDER:
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _create_append_only_guards()
    _create_attempt_guard()


def downgrade() -> None:
    bind = op.get_bind()
    _drop_guards()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(CREATE_ORDER):
        if table_name in existing:
            Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
