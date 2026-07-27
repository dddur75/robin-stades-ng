"""Jalon 11 : feature factory profonde et arène de matchups.

Revision ID: 0008_jalon11_deep_football
Revises: 0007_jalon10_immutable_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008_jalon11_deep_football"
down_revision: str | None = "0007_jalon10_immutable_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

deep_feature_definitions = sa.Table(
    "deep_feature_definitions",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("feature_id", sa.String(length=120), nullable=False),
    sa.Column("feature_version", sa.String(length=40), nullable=False),
    sa.Column("feature_family", sa.String(length=80), nullable=False),
    sa.Column("entity_level", sa.String(length=40), nullable=False),
    sa.Column("cutoff_policy", sa.String(length=80), nullable=False),
    sa.Column("contract", sa.JSON(), nullable=False),
    sa.Column("definition_hash", sa.String(length=64), nullable=False),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "supersedes_id",
        sa.String(length=36),
        sa.ForeignKey("deep_feature_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
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
        "feature_id",
        "feature_version",
        name="uq_deep_feature_definition_version",
    ),
    sa.UniqueConstraint(
        "definition_hash",
        "feature_version",
        name="uq_deep_feature_definition_hash_version",
    ),
    sa.CheckConstraint(
        "length(definition_hash) = 64 AND length(dataset_hash) = 64",
        name="ck_deep_feature_definition_hashes",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_deep_feature_definition_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_deep_feature_definition_simulation",
    ),
)
sa.Index(
    "ix_deep_feature_definition_family",
    deep_feature_definitions.c.feature_family,
    deep_feature_definitions.c.entity_level,
)

deep_feature_observations = sa.Table(
    "deep_feature_observations",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column(
        "feature_definition_id",
        sa.String(length=36),
        sa.ForeignKey("deep_feature_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("fixture_id", sa.String(length=120), nullable=False),
    sa.Column("entity_id", sa.String(length=120), nullable=False),
    sa.Column("side", sa.String(length=20), nullable=False),
    sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("value", sa.JSON(), nullable=True),
    sa.Column("missing_reason", sa.String(length=120), nullable=True),
    sa.Column("source_hash", sa.String(length=64), nullable=False),
    sa.Column("observation_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
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
    sa.UniqueConstraint(
        "feature_definition_id",
        "fixture_id",
        "entity_id",
        "as_of_at",
        "dataset_version",
        name="uq_deep_feature_observation_business",
    ),
    sa.CheckConstraint(
        "length(source_hash) = 64 "
        "AND length(observation_hash) = 64 "
        "AND length(dataset_hash) = 64",
        name="ck_deep_feature_observation_hashes",
    ),
    sa.CheckConstraint(
        "value IS NOT NULL OR missing_reason IS NOT NULL",
        name="ck_deep_feature_observation_missing",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_deep_feature_observation_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_deep_feature_observation_simulation",
    ),
)
sa.Index(
    "ix_deep_feature_observation_fixture",
    deep_feature_observations.c.fixture_id,
    deep_feature_observations.c.as_of_at,
)

coverage_gates = sa.Table(
    "coverage_gates",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("gate_key", sa.String(length=120), nullable=False),
    sa.Column("gate_version", sa.String(length=40), nullable=False),
    sa.Column("competition", sa.String(length=120), nullable=False),
    sa.Column("season", sa.String(length=40), nullable=False),
    sa.Column("feature_family", sa.String(length=80), nullable=False),
    sa.Column("cutoff_class", sa.String(length=80), nullable=False),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("coverage", sa.Float(), nullable=False),
    sa.Column("quality_score", sa.Float(), nullable=False),
    sa.Column("evidence", sa.JSON(), nullable=False),
    sa.Column("evidence_hash", sa.String(length=64), nullable=False),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
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
        "gate_key",
        "gate_version",
        "competition",
        "season",
        "cutoff_class",
        name="uq_coverage_gate_scope",
    ),
    sa.CheckConstraint(
        "status IN ('READY', 'PARTIAL', 'BLOCKED_BY_COVERAGE', "
        "'BLOCKED_BY_TEMPORALITY', 'BLOCKED_BY_IDENTITY', "
        "'MARKET_UNAVAILABLE')",
        name="ck_coverage_gate_status",
    ),
    sa.CheckConstraint(
        "coverage >= 0 AND coverage <= 1 "
        "AND quality_score >= 0 AND quality_score <= 1",
        name="ck_coverage_gate_scores",
    ),
    sa.CheckConstraint(
        "length(evidence_hash) = 64 AND length(dataset_hash) = 64",
        name="ck_coverage_gate_hashes",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_coverage_gate_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_coverage_gate_simulation",
    ),
)
sa.Index(
    "ix_coverage_gate_status",
    coverage_gates.c.gate_key,
    coverage_gates.c.status,
    coverage_gates.c.evaluated_at,
)

matchup_hypotheses = sa.Table(
    "matchup_hypotheses",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("hypothesis_id", sa.String(length=120), nullable=False),
    sa.Column("hypothesis_version", sa.String(length=40), nullable=False),
    sa.Column("title", sa.String(length=250), nullable=False),
    sa.Column("family", sa.String(length=80), nullable=False),
    sa.Column("hypothesis", sa.Text(), nullable=False),
    sa.Column("protocol", sa.JSON(), nullable=False),
    sa.Column("required_gates", sa.JSON(), nullable=False),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("preregistration_hash", sa.String(length=64), nullable=False),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "supersedes_id",
        sa.String(length=36),
        sa.ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT"),
        nullable=True,
    ),
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
        "hypothesis_id",
        "hypothesis_version",
        name="uq_matchup_hypothesis_version",
    ),
    sa.UniqueConstraint(
        "preregistration_hash",
        "hypothesis_version",
        name="uq_matchup_hypothesis_preregistration_version",
    ),
    sa.CheckConstraint(
        "length(preregistration_hash) = 64 AND length(dataset_hash) = 64",
        name="ck_matchup_hypothesis_hashes",
    ),
    sa.CheckConstraint(
        "frozen_at >= registered_at",
        name="ck_matchup_hypothesis_frozen",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_matchup_hypothesis_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_matchup_hypothesis_simulation",
    ),
)
sa.Index(
    "ix_matchup_hypothesis_status",
    matchup_hypotheses.c.family,
    matchup_hypotheses.c.status,
    matchup_hypotheses.c.registered_at,
)

matchup_evaluations = sa.Table(
    "matchup_evaluations",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column(
        "hypothesis_id",
        sa.String(length=36),
        sa.ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "coverage_gate_id",
        sa.String(length=36),
        sa.ForeignKey("coverage_gates.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("evaluation_scope", sa.String(length=50), nullable=False),
    sa.Column("fold_key", sa.String(length=120), nullable=False),
    sa.Column("model_key", sa.String(length=120), nullable=False),
    sa.Column("market", sa.String(length=80), nullable=False),
    sa.Column("support", sa.Integer(), nullable=False),
    sa.Column("effect", sa.Float(), nullable=True),
    sa.Column("metrics", sa.JSON(), nullable=False),
    sa.Column("p_value", sa.Float(), nullable=True),
    sa.Column("q_value_family", sa.Float(), nullable=True),
    sa.Column("q_value_global", sa.Float(), nullable=True),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("paired_sample_hash", sa.String(length=64), nullable=False),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("evaluation_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
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
        "hypothesis_id",
        "evaluation_scope",
        "fold_key",
        "model_key",
        "dataset_hash",
        name="uq_matchup_evaluation_fold",
    ),
    sa.CheckConstraint(
        "support >= 0",
        name="ck_matchup_evaluation_support",
    ),
    sa.CheckConstraint(
        "(p_value IS NULL OR (p_value >= 0 AND p_value <= 1)) "
        "AND (q_value_family IS NULL OR "
        "(q_value_family >= 0 AND q_value_family <= 1)) "
        "AND (q_value_global IS NULL OR "
        "(q_value_global >= 0 AND q_value_global <= 1))",
        name="ck_matchup_evaluation_probabilities",
    ),
    sa.CheckConstraint(
        "length(paired_sample_hash) = 64 "
        "AND length(dataset_hash) = 64 "
        "AND length(evaluation_hash) = 64",
        name="ck_matchup_evaluation_hashes",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_matchup_evaluation_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_matchup_evaluation_simulation",
    ),
)
sa.Index(
    "ix_matchup_evaluation_status",
    matchup_evaluations.c.evaluation_scope,
    matchup_evaluations.c.status,
    matchup_evaluations.c.evaluated_at,
)

prospective_watchlist = sa.Table(
    "prospective_watchlist",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("candidate_key", sa.String(length=160), nullable=False),
    sa.Column("watchlist_version", sa.String(length=40), nullable=False),
    sa.Column(
        "hypothesis_id",
        sa.String(length=36),
        sa.ForeignKey("matchup_hypotheses.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "evaluation_id",
        sa.String(length=36),
        sa.ForeignKey("matchup_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("evidence", sa.JSON(), nullable=False),
    sa.Column("evidence_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        "candidate_key",
        "watchlist_version",
        name="uq_prospective_watchlist_version",
    ),
    sa.CheckConstraint(
        "expires_at IS NULL OR expires_at >= entered_at",
        name="ck_prospective_watchlist_window",
    ),
    sa.CheckConstraint(
        "length(evidence_hash) = 64 AND length(dataset_hash) = 64",
        name="ck_prospective_watchlist_hashes",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_prospective_watchlist_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_prospective_watchlist_simulation",
    ),
)
sa.Index(
    "ix_prospective_watchlist_status",
    prospective_watchlist.c.status,
    prospective_watchlist.c.entered_at,
)

shadow_candidate_versions = sa.Table(
    "shadow_candidate_versions",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("idempotency_key", sa.String(length=250), nullable=False, unique=True),
    sa.Column("candidate_key", sa.String(length=160), nullable=False),
    sa.Column("candidate_version", sa.String(length=40), nullable=False),
    sa.Column(
        "watchlist_id",
        sa.String(length=36),
        sa.ForeignKey("prospective_watchlist.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("status", sa.String(length=50), nullable=False),
    sa.Column("selection_rule", sa.JSON(), nullable=False),
    sa.Column("selection_rule_hash", sa.String(length=64), nullable=False),
    sa.Column("evidence_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("dataset_version", sa.String(length=120), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("code_revision", sa.String(length=80), nullable=False),
    sa.Column(
        "production_status",
        sa.String(length=40),
        nullable=False,
        server_default="PRODUCTION_LOCKED",
    ),
    sa.Column(
        "real_bets",
        sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    ),
    sa.Column(
        "no_bet_default",
        sa.Boolean(),
        nullable=False,
        server_default=sa.true(),
    ),
    sa.Column("payload", sa.JSON(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "supersedes_id",
        sa.String(length=36),
        sa.ForeignKey("shadow_candidate_versions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
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
        "candidate_key",
        "candidate_version",
        name="uq_shadow_candidate_version",
    ),
    sa.CheckConstraint(
        "length(selection_rule_hash) = 64 "
        "AND length(evidence_hash) = 64 "
        "AND length(dataset_hash) = 64",
        name="ck_shadow_candidate_hashes",
    ),
    sa.CheckConstraint(
        "production_status = 'PRODUCTION_LOCKED' "
        "AND real_bets = false AND no_bet_default = true",
        name="ck_shadow_candidate_production_locked",
    ),
    sa.CheckConstraint(
        "append_only = true",
        name="ck_shadow_candidate_append_only",
    ),
    sa.CheckConstraint(
        "simulation = true",
        name="ck_shadow_candidate_simulation",
    ),
)
sa.Index(
    "ix_shadow_candidate_status",
    shadow_candidate_versions.c.status,
    shadow_candidate_versions.c.created_at,
)

CREATE_ORDER = (
    "deep_feature_definitions",
    "deep_feature_observations",
    "coverage_gates",
    "matchup_hypotheses",
    "matchup_evaluations",
    "prospective_watchlist",
    "shadow_candidate_versions",
)


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_j11_append_only_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only J11 table % cannot be mutated',
                    TG_TABLE_NAME;
            END;
            $$;
            """
        )
        for table in CREATE_ORDER:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION robin_reject_j11_append_only_mutation();
                """
            )
        return

    if dialect == "sqlite":
        for table in CREATE_ORDER:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"""
                    CREATE TRIGGER trg_{table}_append_only_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'append-only J11 table cannot be mutated'
                        );
                    END;
                    """
                )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in CREATE_ORDER:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}"
            )
        op.execute(
            "DROP FUNCTION IF EXISTS robin_reject_j11_append_only_mutation()"
        )
        return

    if dialect == "sqlite":
        for table in CREATE_ORDER:
            for operation in ("update", "delete"):
                op.execute(
                    f"DROP TRIGGER IF EXISTS "
                    f"trg_{table}_append_only_{operation}"
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
