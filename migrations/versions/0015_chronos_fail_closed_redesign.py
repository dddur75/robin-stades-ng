"""Chronos fail-closed canary, lineage and price provenance redesign.

Revision ID: 0015_chronos_fail_closed
Revises: 0014_robin_chronos_v1
"""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, select

from robin.storage import chronos_models as chronos_models  # noqa: F401
from robin.storage.models import Base

revision = "0015_chronos_fail_closed"
down_revision = "0014_robin_chronos_v1"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "chronos_canary_cohort_fixtures",
    "chronos_canary_usage_events",
    "chronos_canary_run_windows",
    "market_snapshot_metadata",
    "chronos_lineage_nodes",
)
PRICE_CONTRACT_HASH = (
    "18835b64961986d154a1bc26211c0c2ee09075af42aa59a954d6ba5461e3de4c"
)
CANONICAL_TAG_REGISTRY_HASH = (
    "c95bedfe0a02e2858722e93af13023b5cf4edb53692f7e46216599a3a3979d7d"
)
NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _columns(table_name: str) -> dict[str, dict[str, Any]]:
    return {
        str(column["name"]): cast(dict[str, Any], column)
        for column in inspect(op.get_bind()).get_columns(table_name)
    }


def _checks(table_name: str) -> set[str]:
    return {
        str(check["name"])
        for check in inspect(op.get_bind()).get_check_constraints(table_name)
        if check.get("name")
    }


def _foreign_key_name(table_name: str, column_name: str) -> str | None:
    for constraint in inspect(op.get_bind()).get_foreign_keys(table_name):
        if column_name not in constraint.get("constrained_columns", ()):
            continue
        name = constraint.get("name")
        if name:
            return str(name)
        return (
            f"fk_{table_name}_{column_name}_"
            f"{constraint['referred_table']}"
        )
    return None


def _assert_empty(table_name: str) -> None:
    table = sa.Table(table_name, sa.MetaData(), autoload_with=op.get_bind())
    if op.get_bind().execute(select(table).limit(1)).first() is not None:
        raise RuntimeError(f"CHRONOS_0015_REPLAY_REQUIRED:{table_name}")


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in chronos_models.CHRONOS_TABLE_NAMES:
            if table_name in inspect(op.get_bind()).get_table_names():
                op.execute(
                    f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
                    f"ON {table_name}"
                )
    elif dialect == "sqlite":
        for table_name in chronos_models.CHRONOS_TABLE_NAMES:
            for operation in ("update", "delete"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"trg_{table_name}_append_only_{operation}"
                )


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    existing = set(inspect(op.get_bind()).get_table_names())
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_chronos_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'append-only Chronos table % cannot be mutated',
                    TG_TABLE_NAME;
            END;
            $$;
            """
        )
        for table_name in chronos_models.CHRONOS_TABLE_NAMES:
            if table_name not in existing:
                continue
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table_name} FOR EACH ROW "
                "EXECUTE FUNCTION robin_reject_chronos_mutation()"
            )
    elif dialect == "sqlite":
        for table_name in chronos_models.CHRONOS_TABLE_NAMES:
            if table_name not in existing:
                continue
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER trg_{table_name}_append_only_"
                    f"{operation.lower()} BEFORE {operation} ON {table_name} "
                    "BEGIN SELECT RAISE(ABORT, "
                    "'append-only Chronos table cannot be mutated'); END"
                )


def _upgrade_known_at() -> None:
    columns = _columns("known_at_fact_metadata")
    checks = _checks("known_at_fact_metadata")
    needs_rebuild = any(
        not bool(columns[name].get("nullable"))
        for name in ("requested_at", "response_received_at", "known_at")
    ) or "supersedes_fact_id" not in columns
    if not needs_rebuild:
        return
    with op.batch_alter_table("known_at_fact_metadata") as batch:
        if "ck_chronos_known_at_fact_temporal" in checks:
            batch.drop_constraint(
                "ck_chronos_known_at_fact_temporal", type_="check"
            )
        for name in ("requested_at", "response_received_at", "known_at"):
            if not bool(columns[name].get("nullable")):
                batch.alter_column(name, existing_type=sa.DateTime(), nullable=True)
        if "supersedes_fact_id" not in columns:
            batch.add_column(sa.Column("supersedes_fact_id", sa.String(96)))
            batch.create_foreign_key(
                "fk_chronos_fact_supersedes",
                "known_at_fact_metadata",
                ["supersedes_fact_id"],
                ["fact_id"],
                ondelete="RESTRICT",
            )
        batch.create_check_constraint(
            "ck_chronos_known_at_fact_temporal",
            "length(fact_id) > 64 AND length(source_object_hash) = 64 "
            "AND length(normalized_fact_hash) = 64 "
            "AND (requested_at IS NULL OR response_received_at IS NULL "
            "OR requested_at <= response_received_at) "
            "AND (response_received_at IS NULL OR known_at IS NULL "
            "OR response_received_at <= known_at) AND cutoff_at < kickoff_at "
            "AND ((temporal_class = 'KNOWN_AT_UNKNOWN' "
            "AND requested_at IS NULL AND response_received_at IS NULL "
            "AND known_at IS NULL) OR (temporal_class = 'ON_TIME' "
            "AND known_at <= cutoff_at) OR (temporal_class = 'LATE_FOR_CUTOFF' "
            "AND known_at > cutoff_at AND known_at < kickoff_at) OR "
            "(temporal_class = 'POST_KICKOFF_ONLY' "
            "AND known_at >= kickoff_at)) AND "
            "(supersedes_fact_id IS NULL OR supersedes_fact_id <> fact_id) "
            "AND append_only = true",
        )


def _add_empty_table_columns(
    table_name: str,
    columns: tuple[sa.Column[Any], ...],
) -> None:
    existing = _columns(table_name)
    missing = tuple(column for column in columns if column.name not in existing)
    if not missing:
        return
    _assert_empty(table_name)
    with op.batch_alter_table(table_name) as batch:
        for column in missing:
            batch.add_column(column)


def _upgrade_capture_intents() -> bool:
    if "price_contract_hash" not in _columns("capture_intents"):
        op.add_column(
            "capture_intents",
            sa.Column("price_contract_hash", sa.String(64), nullable=True),
        )
        op.execute(
            sa.text(
                "UPDATE capture_intents SET price_contract_hash = :hash "
                "WHERE family = 'ODDS'"
            ).bindparams(hash=PRICE_CONTRACT_HASH)
        )
        return True
    return False


def _upgrade_tag_snapshot() -> bool:
    if "supersedes_tag_snapshot_hash" in _columns("tag_snapshot_metadata"):
        return False
    _assert_empty("tag_snapshot_metadata")
    with op.batch_alter_table("tag_snapshot_metadata") as batch:
        batch.add_column(sa.Column("supersedes_tag_snapshot_hash", sa.String(64)))
        batch.create_foreign_key(
            "fk_chronos_tag_supersedes",
            "tag_snapshot_metadata",
            ["supersedes_tag_snapshot_hash"],
            ["tag_snapshot_hash"],
            ondelete="RESTRICT",
        )
    return True


def _replace_check_if_columns_added(
    table_name: str,
    *,
    added: bool,
    constraint_name: str,
    expression: str,
) -> None:
    if not added:
        return
    with op.batch_alter_table(table_name) as batch:
        if constraint_name in _checks(table_name):
            batch.drop_constraint(constraint_name, type_="check")
        batch.create_check_constraint(constraint_name, expression)


def _create_insert_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_validate_chronos_lineage_nodes()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM chronos_lineage_nodes n
                    WHERE n.node_id = NEW.upstream_id
                      AND n.node_kind = NEW.upstream_type
                      AND n.content_hash = NEW.upstream_hash
                ) OR NOT EXISTS (
                    SELECT 1 FROM chronos_lineage_nodes n
                    WHERE n.node_id = NEW.downstream_id
                      AND n.node_kind = NEW.downstream_type
                      AND n.content_hash = NEW.downstream_hash
                ) THEN
                    RAISE EXCEPTION 'Chronos lineage node missing or mismatched';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        op.execute(
            "CREATE TRIGGER trg_chronos_lineage_nodes_required BEFORE INSERT "
            "ON chronos_lineage_edges FOR EACH ROW EXECUTE FUNCTION "
            "robin_validate_chronos_lineage_nodes()"
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_validate_chronos_fact_supersession()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.supersedes_fact_id IS NULL THEN RETURN NEW; END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM known_at_fact_metadata predecessor
                    JOIN capture_intents predecessor_intent
                      ON predecessor_intent.id = predecessor.intent_id
                    JOIN capture_intents current_intent
                      ON current_intent.id = NEW.intent_id
                    WHERE predecessor.fact_id = NEW.supersedes_fact_id
                      AND predecessor.fixture_id = NEW.fixture_id
                      AND predecessor.entity_id = NEW.entity_id
                      AND predecessor.source = NEW.source
                      AND predecessor.family = NEW.family
                      AND predecessor.cutoff_id = NEW.cutoff_id
                      AND predecessor_intent.request_contract_hash
                          = current_intent.request_contract_hash
                ) THEN
                    RAISE EXCEPTION 'Chronos fact supersession scope mismatch';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        op.execute(
            "CREATE TRIGGER trg_chronos_fact_supersession_scope BEFORE INSERT "
            "ON known_at_fact_metadata FOR EACH ROW EXECUTE FUNCTION "
            "robin_validate_chronos_fact_supersession()"
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_chronos_lineage_nodes_required
            BEFORE INSERT ON chronos_lineage_edges
            WHEN NOT EXISTS (
                SELECT 1 FROM chronos_lineage_nodes n
                WHERE n.node_id = NEW.upstream_id
                  AND n.node_kind = NEW.upstream_type
                  AND n.content_hash = NEW.upstream_hash
            ) OR NOT EXISTS (
                SELECT 1 FROM chronos_lineage_nodes n
                WHERE n.node_id = NEW.downstream_id
                  AND n.node_kind = NEW.downstream_type
                  AND n.content_hash = NEW.downstream_hash
            )
            BEGIN
                SELECT RAISE(ABORT, 'Chronos lineage node missing or mismatched');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_chronos_fact_supersession_scope
            BEFORE INSERT ON known_at_fact_metadata
            WHEN NEW.supersedes_fact_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM known_at_fact_metadata predecessor
                JOIN capture_intents predecessor_intent
                  ON predecessor_intent.id = predecessor.intent_id
                JOIN capture_intents current_intent
                  ON current_intent.id = NEW.intent_id
                WHERE predecessor.fact_id = NEW.supersedes_fact_id
                  AND predecessor.fixture_id = NEW.fixture_id
                  AND predecessor.entity_id = NEW.entity_id
                  AND predecessor.source = NEW.source
                  AND predecessor.family = NEW.family
                  AND predecessor.cutoff_id = NEW.cutoff_id
                  AND predecessor_intent.request_contract_hash
                      = current_intent.request_contract_hash
            )
            BEGIN
                SELECT RAISE(ABORT, 'Chronos fact supersession scope mismatch');
            END;
            """
        )


def _drop_attempt_guard() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_capture_attempts_chronos_limit "
            "ON capture_attempts"
        )
        op.execute("DROP FUNCTION IF EXISTS robin_enforce_chronos_attempt_limit()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_capture_attempts_chronos_limit")


def _create_attempt_guard() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_enforce_chronos_attempt_limit()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE intent capture_intents%ROWTYPE;
            BEGIN
                SELECT * INTO intent FROM capture_intents
                WHERE window_record_id = NEW.window_record_id;
                IF FOUND AND (
                    NEW.attempt_number > intent.max_technical_attempts
                    OR NEW.fixture_id <> intent.fixture_id
                    OR NEW.family <> intent.family
                    OR (NEW.provider_calls > 0 AND NEW.provider <> intent.source)
                ) THEN
                    RAISE EXCEPTION
                        'Chronos capture attempt exceeds immutable intent';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        op.execute(
            "CREATE TRIGGER trg_capture_attempts_chronos_limit BEFORE INSERT "
            "ON capture_attempts FOR EACH ROW EXECUTE FUNCTION "
            "robin_enforce_chronos_attempt_limit()"
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
                    OR (NEW.provider_calls > 0 AND NEW.provider <> intent.source)
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


def _downgrade_existing_tables() -> None:
    """Restore the exact 0014 column/check shape or refuse lossy conversion."""

    bind = op.get_bind()
    facts = sa.Table(
        "known_at_fact_metadata", sa.MetaData(), autoload_with=bind
    )
    incompatible_fact = bind.execute(
        select(facts.c.fact_id).where(
            sa.or_(
                facts.c.requested_at.is_(None),
                facts.c.response_received_at.is_(None),
                facts.c.known_at.is_(None),
                facts.c.supersedes_fact_id.is_not(None),
            )
        ).limit(1)
    ).first()
    if incompatible_fact is not None:
        raise RuntimeError("CHRONOS_0015_DOWNGRADE_REPLAY_REQUIRED:known_at_fact_metadata")

    for table_name in (
        "price_snapshot_metadata",
        "price_derivation_metadata",
        "tag_snapshot_metadata",
        "chronos_lineage_edges",
    ):
        _assert_empty(table_name)

    fact_fk = _foreign_key_name(
        "known_at_fact_metadata", "supersedes_fact_id"
    )
    with op.batch_alter_table(
        "known_at_fact_metadata", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("ck_chronos_known_at_fact_temporal", type_="check")
        if fact_fk is not None:
            batch.drop_constraint(fact_fk, type_="foreignkey")
        batch.drop_column("supersedes_fact_id")
        for name in ("requested_at", "response_received_at", "known_at"):
            batch.alter_column(name, existing_type=sa.DateTime(), nullable=False)
        batch.create_check_constraint(
            "ck_chronos_known_at_fact_temporal",
            "length(fact_id) > 64 AND length(source_object_hash) = 64 "
            "AND length(normalized_fact_hash) = 64 "
            "AND requested_at <= response_received_at "
            "AND response_received_at <= known_at AND cutoff_at < kickoff_at "
            "AND ((temporal_class = 'ON_TIME' AND known_at <= cutoff_at) "
            "OR (temporal_class = 'LATE_FOR_CUTOFF' AND known_at > cutoff_at "
            "AND known_at < kickoff_at) OR "
            "(temporal_class = 'POST_KICKOFF_ONLY' AND known_at >= kickoff_at)) "
            "AND append_only = true",
        )

    with op.batch_alter_table("capture_intents") as batch:
        batch.drop_constraint(
            "ck_chronos_capture_intent_bounds", type_="check"
        )
        batch.drop_column("price_contract_hash")
        batch.create_check_constraint(
            "ck_chronos_capture_intent_bounds",
            "opens_at <= due_at AND due_at <= cutoff_at "
            "AND cutoff_at < kickoff_at AND max_technical_attempts <= 2 "
            "AND reserved_provider_units >= 0 AND reserved_r2_objects >= 0 "
            "AND reserved_postgresql_rows >= 0 AND append_only = true",
        )

    with op.batch_alter_table("price_snapshot_metadata") as batch:
        batch.drop_constraint("ck_chronos_price_snapshot", type_="check")
        batch.drop_column("price_contract_hash")
        batch.drop_column("price_age_seconds")
        batch.create_check_constraint(
            "ck_chronos_price_snapshot",
            "length(price_snapshot_id) > 64 AND length(raw_object_hash) = 64 "
            "AND length(receipt_hash) = 64 AND odds_decimal > 1 "
            "AND requested_at <= response_received_at "
            "AND response_received_at = known_at AND cutoff_at < kickoff_at "
            "AND ((market = 'MATCH_RESULT_90M' AND line IS NULL "
            "AND selection IN ('HOME','DRAW','AWAY')) OR "
            "(market = 'TOTAL_GOALS_2_5_90M' AND line = 2.5 "
            "AND selection IN ('OVER_2_5','UNDER_2_5'))) "
            "AND append_only = true",
        )

    with op.batch_alter_table("price_derivation_metadata") as batch:
        batch.drop_constraint("ck_chronos_price_derivation", type_="check")
        batch.drop_column("price_contract_hash")
        batch.create_check_constraint(
            "ck_chronos_price_derivation",
            "length(source_price_set_hash) = 64 AND length(definition_hash) = 64 "
            "AND length(inputs_hash) = 64 AND implied_probability > 0 "
            "AND devigged_probability > 0 AND devigged_probability <= 1 "
            "AND price_age_seconds >= 0 AND append_only = true",
        )

    tag_fk = _foreign_key_name(
        "tag_snapshot_metadata", "supersedes_tag_snapshot_hash"
    )
    with op.batch_alter_table(
        "tag_snapshot_metadata", naming_convention=NAMING_CONVENTION
    ) as batch:
        batch.drop_constraint("ck_chronos_tag_snapshot", type_="check")
        if tag_fk is not None:
            batch.drop_constraint(tag_fk, type_="foreignkey")
        batch.drop_column("supersedes_tag_snapshot_hash")
        batch.create_check_constraint(
            "ck_chronos_tag_snapshot",
            "length(tag_snapshot_hash) = 64 AND length(tag_registry_hash) = 64 "
            "AND length(facts_manifest_hash) = 64 AND cutoff_at < kickoff_at "
            "AND true_count + false_count = known_count "
            "AND known_count + unknown_count = tag_count "
            "AND append_only = true",
        )

    with op.batch_alter_table("chronos_lineage_edges") as batch:
        batch.drop_constraint("ck_chronos_lineage_edge", type_="check")
        batch.drop_column("contract_hash")
        batch.drop_column("downstream_hash")
        batch.drop_column("upstream_hash")
        batch.create_check_constraint(
            "ck_chronos_lineage_edge",
            "length(edge_hash) = 64 AND upstream_id <> downstream_id "
            "AND append_only = true",
        )


def upgrade() -> None:
    bind = op.get_bind()
    _drop_attempt_guard()
    _drop_append_only_guards()
    existing = set(inspect(bind).get_table_names())
    for table_name in NEW_TABLES:
        if table_name not in existing:
            Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _upgrade_known_at()
    capture_intent_column_added = _upgrade_capture_intents()
    _replace_check_if_columns_added(
        "capture_intents",
        added=capture_intent_column_added,
        constraint_name="ck_chronos_capture_intent_bounds",
        expression=(
            "opens_at <= due_at AND due_at <= cutoff_at "
            "AND cutoff_at < kickoff_at AND max_technical_attempts <= 2 "
            "AND reserved_provider_units >= 0 AND reserved_r2_objects >= 0 "
            "AND reserved_postgresql_rows >= 0 "
            f"AND ((family = 'ODDS' AND price_contract_hash = "
            f"'{PRICE_CONTRACT_HASH}') OR (family <> 'ODDS' "
            "AND price_contract_hash IS NULL)) AND append_only = true"
        ),
    )
    price_columns_before = _columns("price_snapshot_metadata")
    _add_empty_table_columns(
        "price_snapshot_metadata",
        (
            sa.Column("price_age_seconds", sa.Integer(), nullable=True),
            sa.Column("price_contract_hash", sa.String(64), nullable=False),
        ),
    )
    _replace_check_if_columns_added(
        "price_snapshot_metadata",
        added="price_contract_hash" not in price_columns_before,
        constraint_name="ck_chronos_price_snapshot",
        expression=(
            "length(price_snapshot_id) > 64 AND length(raw_object_hash) = 64 "
            "AND length(receipt_hash) = 64 "
            "AND length(request_contract_hash) = 64 "
            f"AND price_contract_hash = '{PRICE_CONTRACT_HASH}' "
            "AND odds_decimal > 1 AND requested_at <= response_received_at "
            "AND response_received_at = known_at AND cutoff_at < kickoff_at "
            "AND ((temporal_class = 'ON_TIME' AND known_at <= cutoff_at) OR "
            "(temporal_class = 'LATE_FOR_CUTOFF' AND known_at > cutoff_at "
            "AND known_at < kickoff_at) OR (temporal_class = 'POST_KICKOFF_ONLY' "
            "AND known_at >= kickoff_at)) AND ((provider_updated_at IS NULL "
            "AND price_age_seconds IS NULL AND quality_status = 'NO_PRICE') "
            "OR provider_updated_at IS NOT NULL) AND "
            "((market = 'MATCH_RESULT_90M' AND line IS NULL "
            "AND selection IN ('HOME','DRAW','AWAY')) OR "
            "(market = 'TOTAL_GOALS_2_5_90M' AND line = 2.5 "
            "AND selection IN ('OVER_2_5','UNDER_2_5'))) "
            "AND append_only = true"
        ),
    )
    derivation_columns_before = _columns("price_derivation_metadata")
    _add_empty_table_columns(
        "price_derivation_metadata",
        (sa.Column("price_contract_hash", sa.String(64), nullable=False),),
    )
    _replace_check_if_columns_added(
        "price_derivation_metadata",
        added="price_contract_hash" not in derivation_columns_before,
        constraint_name="ck_chronos_price_derivation",
        expression=(
            "length(source_price_set_hash) = 64 "
            f"AND price_contract_hash = '{PRICE_CONTRACT_HASH}' "
            "AND length(definition_hash) = 64 AND length(inputs_hash) = 64 "
            "AND implied_probability > 0 AND devigged_probability > 0 "
            "AND devigged_probability <= 1 AND price_age_seconds >= 0 "
            "AND append_only = true"
        ),
    )
    tag_column_added = _upgrade_tag_snapshot()
    _replace_check_if_columns_added(
        "tag_snapshot_metadata",
        added=tag_column_added,
        constraint_name="ck_chronos_tag_snapshot",
        expression=(
            "length(tag_snapshot_hash) = 64 "
            f"AND tag_registry_hash = '{CANONICAL_TAG_REGISTRY_HASH}' "
            "AND length(facts_manifest_hash) = 64 AND cutoff_at < kickoff_at "
            "AND true_count + false_count = known_count "
            "AND known_count + unknown_count = tag_count "
            "AND (supersedes_tag_snapshot_hash IS NULL OR "
            "supersedes_tag_snapshot_hash <> tag_snapshot_hash) "
            "AND append_only = true"
        ),
    )
    lineage_columns_before = _columns("chronos_lineage_edges")
    _add_empty_table_columns(
        "chronos_lineage_edges",
        (
            sa.Column("upstream_hash", sa.String(64), nullable=False),
            sa.Column("downstream_hash", sa.String(64), nullable=False),
            sa.Column("contract_hash", sa.String(64), nullable=False),
        ),
    )
    _replace_check_if_columns_added(
        "chronos_lineage_edges",
        added="upstream_hash" not in lineage_columns_before,
        constraint_name="ck_chronos_lineage_edge",
        expression=(
            "length(edge_hash) = 64 AND upstream_id <> downstream_id "
            "AND length(upstream_hash) = 64 AND length(downstream_hash) = 64 "
            "AND length(contract_hash) = 64 AND append_only = true"
        ),
    )
    _create_append_only_guards()
    _create_insert_guards()
    _create_attempt_guard()


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_chronos_lineage_nodes_required "
            "ON chronos_lineage_edges"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS robin_validate_chronos_lineage_nodes()"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_chronos_fact_supersession_scope "
            "ON known_at_fact_metadata"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS robin_validate_chronos_fact_supersession()"
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_chronos_lineage_nodes_required")
        op.execute("DROP TRIGGER IF EXISTS trg_chronos_fact_supersession_scope")
    _drop_attempt_guard()
    _drop_append_only_guards()
    _downgrade_existing_tables()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(NEW_TABLES):
        if table_name in existing:
            Base.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
    _create_append_only_guards()
    _create_attempt_guard()
