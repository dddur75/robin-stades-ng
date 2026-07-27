"""Jalon 10 : recherche de patterns et registre public append-only.

Revision ID: 0006_jalon10_pattern_ledger
Revises: 0005_jalon9_critical_closure
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0006_jalon10_pattern_ledger"
down_revision: str | None = "0005_jalon9_critical_closure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

pattern_definitions = sa.Table(
    "pattern_definitions",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("pattern_id", sa.String(length=80), nullable=False),
    sa.Column("pattern_version", sa.String(length=40), nullable=False),
    sa.Column("rule_hash", sa.String(length=64), nullable=False),
    sa.Column("sport", sa.String(length=30), nullable=False),
    sa.Column("market", sa.String(length=80), nullable=False),
    sa.Column("selection", sa.String(length=80), nullable=False),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("evidence_scope", sa.String(length=50), nullable=False),
    sa.Column("definition", sa.JSON(), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("dataset_hashes", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "supersedes_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.UniqueConstraint(
        "pattern_id",
        "pattern_version",
        name="uq_pattern_definition_version",
    ),
    sa.UniqueConstraint(
        "rule_hash",
        "pattern_version",
        name="uq_pattern_definition_rule_version",
    ),
)
sa.Index(
    "ix_pattern_definition_status",
    pattern_definitions.c.status,
    pattern_definitions.c.evidence_scope,
)

pattern_runs = sa.Table(
    "pattern_runs",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("run_type", sa.String(length=40), nullable=False),
    sa.Column("seed", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("configuration", sa.JSON(), nullable=False),
    sa.Column("dataset_hashes", sa.JSON(), nullable=False),
    sa.Column("environment", sa.JSON(), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("status", sa.String(length=40), nullable=False),
    sa.Column("rules_generated", sa.Integer(), nullable=False),
    sa.Column("rules_executed", sa.Integer(), nullable=False),
    sa.Column("rules_rejected", sa.Integer(), nullable=False),
    sa.Column("cost_units", sa.Float(), nullable=False),
    sa.Column("checkpoint", sa.JSON(), nullable=False),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.CheckConstraint("simulation = true", name="ck_pattern_run_simulation"),
    sa.CheckConstraint(
        "rules_generated >= 0 AND rules_executed >= 0 "
        "AND rules_rejected >= 0",
        name="ck_pattern_run_counts",
    ),
)
sa.Index(
    "ix_pattern_run_status",
    pattern_runs.c.run_type,
    pattern_runs.c.status,
    pattern_runs.c.started_at,
)

pattern_evaluations = sa.Table(
    "pattern_evaluations",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column(
        "pattern_definition_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "pattern_run_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_runs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("evaluation_scope", sa.String(length=50), nullable=False),
    sa.Column("fold_key", sa.String(length=120), nullable=False),
    sa.Column("support", sa.Integer(), nullable=False),
    sa.Column("metrics", sa.JSON(), nullable=False),
    sa.Column("p_value", sa.Float(), nullable=True),
    sa.Column("q_value", sa.Float(), nullable=True),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.UniqueConstraint(
        "pattern_definition_id",
        "pattern_run_id",
        "evaluation_scope",
        "fold_key",
        name="uq_pattern_evaluation_fold",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_pattern_evaluation_simulation",
    ),
    sa.CheckConstraint(
        "support >= 0",
        name="ck_pattern_evaluation_support",
    ),
    sa.CheckConstraint(
        "(p_value IS NULL OR (p_value >= 0 AND p_value <= 1)) "
        "AND (q_value IS NULL OR (q_value >= 0 AND q_value <= 1))",
        name="ck_pattern_evaluation_probabilities",
    ),
)
sa.Index(
    "ix_pattern_evaluation_status",
    pattern_evaluations.c.evaluation_scope,
    pattern_evaluations.c.status,
    pattern_evaluations.c.evaluated_at,
)

pattern_decisions = sa.Table(
    "pattern_decisions",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("decision_id", sa.String(length=120), nullable=False, unique=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column(
        "pattern_definition_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column(
        "pattern_run_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_runs.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("fixture_id", sa.String(length=100), nullable=False),
    sa.Column("competition", sa.String(length=120), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("market", sa.String(length=80), nullable=False),
    sa.Column("selection", sa.String(length=80), nullable=False),
    sa.Column("odds", sa.Float(), nullable=True),
    sa.Column("odds_source", sa.String(length=160), nullable=False),
    sa.Column("decision", sa.String(length=40), nullable=False),
    sa.Column("stake_units", sa.Float(), nullable=False),
    sa.Column("shadow_bankroll_before", sa.Float(), nullable=False),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column(
        "append_only",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_pattern_decision_simulation",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_pattern_decision_append_only",
    ),
    sa.CheckConstraint(
        "published_at <= cutoff_at AND cutoff_at < kickoff_at",
        name="ck_pattern_decision_temporal",
    ),
    sa.CheckConstraint(
        "decision IN ('BET', 'NO_BET', 'NO_BET_DATA_UNAVAILABLE')",
        name="ck_pattern_decision_value",
    ),
    sa.CheckConstraint(
        "(decision = 'BET' AND stake_units = 1) "
        "OR (decision <> 'BET' AND stake_units = 0)",
        name="ck_pattern_decision_stake",
    ),
    sa.UniqueConstraint(
        "fixture_id",
        "market",
        "selection",
        "cutoff_at",
        name="uq_pattern_decision_business",
    ),
)
sa.Index(
    "ix_pattern_decision_fixture",
    pattern_decisions.c.fixture_id,
    pattern_decisions.c.kickoff_at,
)

pattern_settlements = sa.Table(
    "pattern_settlements",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("settlement_id", sa.String(length=120), nullable=False, unique=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column(
        "pattern_decision_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("result", sa.String(length=20), nullable=False),
    sa.Column("profit_units", sa.Float(), nullable=False),
    sa.Column("shadow_bankroll_after", sa.Float(), nullable=False),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column(
        "append_only",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.UniqueConstraint(
        "pattern_decision_id",
        name="uq_pattern_settlement_decision",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_pattern_settlement_simulation",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_pattern_settlement_append_only",
    ),
    sa.CheckConstraint(
        "result IN ('WIN', 'LOSS', 'VOID')",
        name="ck_pattern_settlement_result",
    ),
)
sa.Index(
    "ix_pattern_settlement_time",
    pattern_settlements.c.settled_at,
)

bankroll_events = sa.Table(
    "bankroll_events",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("event_id", sa.String(length=120), nullable=False, unique=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("event_type", sa.String(length=40), nullable=False),
    sa.Column(
        "pattern_decision_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_decisions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column(
        "pattern_settlement_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_settlements.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("amount_units", sa.Float(), nullable=False),
    sa.Column("balance_before", sa.Float(), nullable=False),
    sa.Column("balance_after", sa.Float(), nullable=False),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column(
        "append_only",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.UniqueConstraint(
        "pattern_settlement_id",
        name="uq_bankroll_event_settlement",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_bankroll_event_simulation",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_bankroll_event_append_only",
    ),
    sa.CheckConstraint(
        "balance_before >= 0 AND balance_after >= 0",
        name="ck_bankroll_event_balances",
    ),
)
sa.Index(
    "ix_bankroll_event_time",
    bankroll_events.c.occurred_at,
)

evidence_ledger = sa.Table(
    "evidence_ledger",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("record_id", sa.String(length=120), nullable=False, unique=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("sequence_no", sa.Integer(), nullable=False, unique=True),
    sa.Column("record_type", sa.String(length=30), nullable=False),
    sa.Column(
        "pattern_decision_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_decisions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column(
        "pattern_settlement_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_settlements.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("previous_record_hash", sa.String(length=64), nullable=False),
    sa.Column("record_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "append_only",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_evidence_ledger_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_evidence_ledger_simulation",
    ),
    sa.CheckConstraint(
        "sequence_no >= 0",
        name="ck_evidence_ledger_sequence",
    ),
)
sa.Index(
    "ix_evidence_ledger_recorded",
    evidence_ledger.c.recorded_at,
    evidence_ledger.c.record_type,
)

experiment_registry = sa.Table(
    "experiment_registry",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("experiment_id", sa.String(length=120), nullable=False),
    sa.Column("experiment_version", sa.String(length=40), nullable=False),
    sa.Column("preregistration_hash", sa.String(length=64), nullable=False),
    sa.Column("hypothesis", sa.Text(), nullable=False),
    sa.Column("protocol", sa.JSON(), nullable=False),
    sa.Column("dataset_scope", sa.JSON(), nullable=False),
    sa.Column("status", sa.String(length=40), nullable=False),
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column(
        "pattern_definition_id",
        sa.String(length=36),
        sa.ForeignKey("pattern_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column(
        "supersedes_id",
        sa.String(length=36),
        sa.ForeignKey("experiment_registry.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column(
        "simulation",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.UniqueConstraint(
        "experiment_id",
        "experiment_version",
        name="uq_experiment_registry_version",
    ),
    sa.UniqueConstraint(
        "preregistration_hash",
        name="uq_experiment_preregistration_hash",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_experiment_registry_simulation",
    ),
    sa.CheckConstraint(
        "frozen_at >= registered_at",
        name="ck_experiment_registry_frozen",
    ),
)
sa.Index(
    "ix_experiment_registry_status",
    experiment_registry.c.status,
    experiment_registry.c.registered_at,
)

CREATE_ORDER = [
    "pattern_definitions",
    "pattern_runs",
    "pattern_evaluations",
    "pattern_decisions",
    "pattern_settlements",
    "bankroll_events",
    "evidence_ledger",
    "experiment_registry",
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
