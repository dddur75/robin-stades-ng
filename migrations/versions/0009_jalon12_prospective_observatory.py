"""Jalon 12: R2-first prospective deep-data observatory.

Revision ID: 0009_jalon12_observatory
Revises: 0008_jalon11_deep_football
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0009_jalon12_observatory"
down_revision: str | None = "0008_jalon11_deep_football"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

prospective_fixtures = sa.Table(
    "prospective_fixtures",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("idempotency_key", sa.String(250), nullable=False, unique=True),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("competition", sa.String(120), nullable=False),
    sa.Column("season", sa.String(40), nullable=False),
    sa.Column("phase", sa.String(120), nullable=False),
    sa.Column("home_team_id", sa.String(120), nullable=False),
    sa.Column("away_team_id", sa.String(120), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("provider", sa.String(120), nullable=False),
    sa.Column("provider_fixture_id", sa.String(120), nullable=False),
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("registry_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("kickoff_reliable", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "provider", "provider_fixture_id", "registry_hash",
        name="uq_prospective_fixture_version",
    ),
    sa.CheckConstraint(
        "length(registry_hash) = 64 AND append_only = true",
        name="ck_prospective_fixture_integrity",
    ),
)
sa.Index(
    "ix_prospective_fixture_kickoff",
    prospective_fixtures.c.competition,
    prospective_fixtures.c.kickoff_at,
)
sa.Index("ix_prospective_fixtures_fixture_id", prospective_fixtures.c.fixture_id)

capture_windows = sa.Table(
    "capture_windows",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("window_id", sa.String(250), nullable=False, unique=True),
    sa.Column(
        "fixture_record_id",
        sa.String(36),
        sa.ForeignKey("prospective_fixtures.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("family", sa.String(40), nullable=False),
    sa.Column("label", sa.String(40), nullable=False),
    sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("operational_tolerance_seconds", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(40), nullable=False),
    sa.Column("policy_version", sa.String(80), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.CheckConstraint(
        "opens_at <= due_at AND due_at <= cutoff_at AND cutoff_at < kickoff_at",
        name="ck_capture_window_temporal_order",
    ),
    sa.CheckConstraint("append_only = true", name="ck_capture_window_append_only"),
)
sa.Index("ix_capture_window_due", capture_windows.c.status, capture_windows.c.due_at)
sa.Index("ix_capture_windows_fixture_id", capture_windows.c.fixture_id)

capture_attempts = sa.Table(
    "capture_attempts",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("attempt_id", sa.String(250), nullable=False, unique=True),
    sa.Column("idempotency_key", sa.String(250), nullable=False, unique=True),
    sa.Column("window_id", sa.String(250), nullable=False),
    sa.Column(
        "window_record_id",
        sa.String(36),
        sa.ForeignKey("capture_windows.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("provider", sa.String(120), nullable=False),
    sa.Column("family", sa.String(40), nullable=False),
    sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.String(40), nullable=False),
    sa.Column("retry_disposition", sa.String(40), nullable=False),
    sa.Column("attempt_number", sa.Integer(), nullable=False),
    sa.Column("http_status", sa.Integer(), nullable=True),
    sa.Column("provider_calls", sa.Integer(), nullable=False),
    sa.Column("provider_credits", sa.Integer(), nullable=False),
    sa.Column("error_code", sa.String(120), nullable=True),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "window_record_id", "attempt_number",
        name="uq_capture_attempt_window_number",
    ),
    sa.CheckConstraint(
        "attempt_number >= 1 AND attempt_number <= 5 "
        "AND provider_calls >= 0 AND provider_calls <= 1 "
        "AND provider_credits >= 0 AND append_only = true",
        name="ck_capture_attempt_bounds",
    ),
)
sa.Index(
    "ix_capture_attempt_status",
    capture_attempts.c.status,
    capture_attempts.c.attempted_at,
)
sa.Index("ix_capture_attempts_fixture_id", capture_attempts.c.fixture_id)
sa.Index("ix_capture_attempts_window_id", capture_attempts.c.window_id)

capture_receipts = sa.Table(
    "capture_receipts",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("receipt_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("window_id", sa.String(250), nullable=True),
    sa.Column(
        "window_record_id",
        sa.String(36),
        sa.ForeignKey("capture_windows.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("competition", sa.String(120), nullable=False),
    sa.Column("season", sa.String(40), nullable=False),
    sa.Column("provider", sa.String(120), nullable=False),
    sa.Column("family", sa.String(40), nullable=False),
    sa.Column("window_label", sa.String(40), nullable=False),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("response_received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
    sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("materialized_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("seconds_before_kickoff", sa.Integer(), nullable=False),
    sa.Column("http_status", sa.Integer(), nullable=False),
    sa.Column("payload_sha256", sa.String(64), nullable=False),
    sa.Column("payload_bytes", sa.Integer(), nullable=False),
    sa.Column("stored_bytes", sa.Integer(), nullable=False),
    sa.Column("r2_key", sa.String(1500), nullable=False),
    sa.Column("receipt_r2_key", sa.String(1500), nullable=False, unique=True),
    sa.Column("source_endpoint", sa.String(500), nullable=False),
    sa.Column("complete", sa.Boolean(), nullable=False),
    sa.Column("quality_status", sa.String(40), nullable=False),
    sa.Column("provider_calls", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.CheckConstraint(
        "length(receipt_hash) = 64 AND length(payload_sha256) = 64 "
        "AND payload_bytes >= 0 AND stored_bytes >= 0 "
        "AND provider_calls >= 0 AND provider_calls <= 1 "
        "AND cutoff_at < kickoff_at AND append_only = true",
        name="ck_capture_receipt_integrity",
    ),
)
sa.Index(
    "ix_capture_receipt_fixture_family",
    capture_receipts.c.fixture_id,
    capture_receipts.c.family,
    capture_receipts.c.observed_at,
)
sa.Index("ix_capture_receipts_fixture_id", capture_receipts.c.fixture_id)
sa.Index("ix_capture_receipts_r2_key", capture_receipts.c.r2_key)

prospective_payload_index = sa.Table(
    "prospective_payload_index",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column(
        "receipt_id",
        sa.String(36),
        sa.ForeignKey("capture_receipts.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("family", sa.String(40), nullable=False),
    sa.Column("r2_key", sa.String(1500), nullable=False),
    sa.Column("receipt_r2_key", sa.String(1500), nullable=False, unique=True),
    sa.Column("payload_sha256", sa.String(64), nullable=False),
    sa.Column("payload_bytes", sa.Integer(), nullable=False),
    sa.Column("stored_bytes", sa.Integer(), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.CheckConstraint(
        "length(payload_sha256) = 64 AND payload_bytes >= 0 "
        "AND stored_bytes >= 0 AND append_only = true",
        name="ck_prospective_payload_index_integrity",
    ),
)
sa.Index(
    "ix_prospective_payload_fixture",
    prospective_payload_index.c.fixture_id,
    prospective_payload_index.c.family,
    prospective_payload_index.c.observed_at,
)
sa.Index("ix_prospective_payload_r2_key", prospective_payload_index.c.r2_key)


def _projection_base(name: str) -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "receipt_id",
            sa.String(36),
            sa.ForeignKey("capture_receipts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fixture_id", sa.String(120), nullable=False),
    ]


prospective_player_status = sa.Table(
    "prospective_player_status",
    metadata,
    *_projection_base("prospective_player_status"),
    sa.Column("team_id", sa.String(120), nullable=False),
    sa.Column("player_id", sa.String(120), nullable=False),
    sa.Column("status", sa.String(80), nullable=False),
    sa.Column("reason", sa.String(250), nullable=True),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("projection_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "receipt_id", "player_id",
        name="uq_prospective_player_status_receipt_player",
    ),
    sa.CheckConstraint(
        "length(projection_hash) = 64 AND append_only = true",
        name="ck_prospective_player_status_integrity",
    ),
)
sa.Index(
    "ix_prospective_player_status_fixture_id",
    prospective_player_status.c.fixture_id,
)

prospective_injuries = sa.Table(
    "prospective_injuries",
    metadata,
    *_projection_base("prospective_injuries"),
    sa.Column("team_id", sa.String(120), nullable=False),
    sa.Column("player_id", sa.String(120), nullable=False),
    sa.Column("status", sa.String(80), nullable=False),
    sa.Column("reason", sa.Text(), nullable=True),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("projection_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "receipt_id", "player_id", "status",
        name="uq_prospective_injury_receipt_player_status",
    ),
    sa.CheckConstraint(
        "length(projection_hash) = 64 AND append_only = true",
        name="ck_prospective_injury_integrity",
    ),
)
sa.Index("ix_prospective_injuries_fixture_id", prospective_injuries.c.fixture_id)

prospective_lineups = sa.Table(
    "prospective_lineups",
    metadata,
    *_projection_base("prospective_lineups"),
    sa.Column("team_id", sa.String(120), nullable=False),
    sa.Column("starter_ids", sa.JSON(), nullable=False),
    sa.Column("starter_count", sa.Integer(), nullable=False),
    sa.Column("identities_complete", sa.Boolean(), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("lineup_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "receipt_id", "team_id", name="uq_prospective_lineup_receipt_team"
    ),
    sa.CheckConstraint(
        "starter_count = 11 AND identities_complete = true "
        "AND length(lineup_hash) = 64 AND append_only = true",
        name="ck_prospective_lineup_integrity",
    ),
)
sa.Index("ix_prospective_lineups_fixture_id", prospective_lineups.c.fixture_id)

prospective_formations = sa.Table(
    "prospective_formations",
    metadata,
    *_projection_base("prospective_formations"),
    sa.Column("team_id", sa.String(120), nullable=False),
    sa.Column("formation", sa.String(40), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("projection_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "receipt_id", "team_id", name="uq_prospective_formation_receipt_team"
    ),
    sa.CheckConstraint(
        "length(projection_hash) = 64 AND append_only = true",
        name="ck_prospective_formation_integrity",
    ),
)
sa.Index("ix_prospective_formations_fixture_id", prospective_formations.c.fixture_id)

prospective_odds_snapshots = sa.Table(
    "prospective_odds_snapshots",
    metadata,
    *_projection_base("prospective_odds_snapshots"),
    sa.Column("bookmaker", sa.String(120), nullable=False),
    sa.Column("market", sa.String(80), nullable=False),
    sa.Column("selection", sa.String(120), nullable=False),
    sa.Column("odds", sa.Float(), nullable=False),
    sa.Column("margin", sa.Float(), nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("fixture_match_status", sa.String(40), nullable=False),
    sa.Column("snapshot_hash", sa.String(64), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "receipt_id", "bookmaker", "market", "selection",
        name="uq_prospective_odds_receipt_selection",
    ),
    sa.CheckConstraint(
        "odds > 1 AND margin >= 0 AND length(snapshot_hash) = 64 "
        "AND append_only = true",
        name="ck_prospective_odds_integrity",
    ),
)
sa.Index(
    "ix_prospective_odds_fixture",
    prospective_odds_snapshots.c.fixture_id,
    prospective_odds_snapshots.c.observed_at,
)

temporal_data_gates = sa.Table(
    "temporal_data_gates",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("idempotency_key", sa.String(250), nullable=False),
    sa.Column("fixture_id", sa.String(120), nullable=False),
    sa.Column("gate_name", sa.String(120), nullable=False),
    sa.Column("status", sa.String(60), nullable=False),
    sa.Column("coverage", sa.Float(), nullable=False),
    sa.Column("observations", sa.Integer(), nullable=False),
    sa.Column("reason", sa.String(250), nullable=False),
    sa.Column("evidence", sa.JSON(), nullable=False),
    sa.Column("evidence_hash", sa.String(64), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "idempotency_key", name="uq_temporal_data_gate_idempotency"
    ),
    sa.CheckConstraint(
        "coverage >= 0 AND coverage <= 1 "
        "AND length(evidence_hash) = 64 AND append_only = true",
        name="ck_temporal_data_gate_integrity",
    ),
)
sa.Index(
    "ix_temporal_data_gate_fixture",
    temporal_data_gates.c.fixture_id,
    temporal_data_gates.c.gate_name,
    temporal_data_gates.c.evaluated_at,
)

provider_budget_ledger = sa.Table(
    "provider_budget_ledger",
    metadata,
    sa.Column("id", sa.String(36), primary_key=True),
    sa.Column("idempotency_key", sa.String(250), nullable=False),
    sa.Column("provider", sa.String(80), nullable=False),
    sa.Column("units", sa.Integer(), nullable=False),
    sa.Column("cumulative_units", sa.Integer(), nullable=False),
    sa.Column("hard_limit", sa.Integer(), nullable=False),
    sa.Column("provider_remaining", sa.Integer(), nullable=False),
    sa.Column("provider_reserve", sa.Integer(), nullable=False),
    sa.Column("reason", sa.String(250), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("code_revision", sa.String(80), nullable=False),
    sa.Column("append_only", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.UniqueConstraint(
        "idempotency_key", name="uq_provider_budget_ledger_idempotency"
    ),
    sa.CheckConstraint(
        "units >= 0 AND cumulative_units >= units AND hard_limit > 0 "
        "AND provider_remaining >= 0 AND provider_reserve >= 0 "
        "AND append_only = true",
        name="ck_provider_budget_ledger_bounds",
    ),
)
sa.Index(
    "ix_provider_budget_recorded",
    provider_budget_ledger.c.provider,
    provider_budget_ledger.c.recorded_at,
)

CREATE_ORDER = (
    "prospective_fixtures",
    "capture_windows",
    "capture_attempts",
    "capture_receipts",
    "prospective_payload_index",
    "prospective_player_status",
    "prospective_injuries",
    "prospective_lineups",
    "prospective_formations",
    "prospective_odds_snapshots",
    "temporal_data_gates",
    "provider_budget_ledger",
)


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_j12_append_only_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only J12 table % cannot be mutated',
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
                EXECUTE FUNCTION robin_reject_j12_append_only_mutation();
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
                            'append-only J12 table cannot be mutated'
                        );
                    END;
                    """
                )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in CREATE_ORDER:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
            )
        op.execute(
            "DROP FUNCTION IF EXISTS robin_reject_j12_append_only_mutation()"
        )
    elif dialect == "sqlite":
        for table_name in CREATE_ORDER:
            for operation in ("update", "delete"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"trg_{table_name}_append_only_{operation}"
                )


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table_name in CREATE_ORDER:
        if table_name not in existing:
            metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _create_append_only_guards()


def downgrade() -> None:
    bind = op.get_bind()
    _drop_append_only_guards()
    existing = set(inspect(bind).get_table_names())
    for table_name in reversed(CREATE_ORDER):
        if table_name in existing:
            metadata.tables[table_name].drop(bind=bind, checkfirst=True)
