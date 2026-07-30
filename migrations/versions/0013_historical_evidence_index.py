"""Compact historical hypothesis evidence projections and artifact indexes.

Revision ID: 0013_historical_evidence_index
Revises: 0012_universal_genome_v2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0013_historical_evidence_index"
down_revision: str | None = "0012_universal_genome_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

hypothesis_historical_evidence_summaries = sa.Table(
    "hypothesis_historical_evidence_summaries",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("hypothesis_id", sa.String(length=120), nullable=False),
    sa.Column("rule_hash", sa.String(length=64), nullable=False),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("campaign_result_hash", sa.String(length=64), nullable=False),
    sa.Column("evidence_hash", sa.String(length=64), nullable=False),
    sa.Column("source_revision", sa.String(length=40), nullable=False),
    sa.Column("occurrences", sa.Integer(), nullable=False),
    sa.Column("settled", sa.Integer(), nullable=False),
    sa.Column("wins", sa.Integer(), nullable=False),
    sa.Column("losses", sa.Integer(), nullable=False),
    sa.Column("voids", sa.Integer(), nullable=False),
    sa.Column("hit_rate", sa.Numeric(precision=24, scale=18), nullable=True),
    sa.Column("average_odds", sa.Numeric(precision=24, scale=18), nullable=True),
    sa.Column("median_odds", sa.Numeric(precision=24, scale=18), nullable=True),
    sa.Column(
        "total_stake_units",
        sa.Numeric(precision=24, scale=8),
        nullable=False,
    ),
    sa.Column(
        "total_return_units",
        sa.Numeric(precision=24, scale=8),
        nullable=False,
    ),
    sa.Column("profit_units", sa.Numeric(precision=24, scale=8), nullable=False),
    sa.Column("roi", sa.Numeric(precision=24, scale=18), nullable=True),
    sa.Column(
        "max_drawdown_units",
        sa.Numeric(precision=24, scale=8),
        nullable=False,
    ),
    sa.Column("max_losing_streak", sa.Integer(), nullable=False),
    sa.Column("confidence_interval", sa.JSON(), nullable=False),
    sa.Column("eligible_folds", sa.Integer(), nullable=False),
    sa.Column("positive_folds", sa.Integer(), nullable=False),
    sa.Column("distinct_seasons", sa.Integer(), nullable=False),
    sa.Column("distinct_teams", sa.Integer(), nullable=False),
    sa.Column("distinct_groups", sa.Integer(), nullable=False),
    sa.Column("p_value", sa.Float(), nullable=True),
    sa.Column("q_value", sa.Float(), nullable=True),
    sa.Column("status", sa.String(length=100), nullable=False),
    sa.Column("payload_object_key", sa.String(length=1500), nullable=False),
    sa.Column("payload_sha256", sa.String(length=64), nullable=False),
    sa.Column("schema_version", sa.String(length=80), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        "dataset_hash",
        "rule_hash",
        name="uq_historical_evidence_summary_identity",
    ),
    sa.CheckConstraint(
        "length(id) = 36 "
        "AND length(rule_hash) = 64 "
        "AND length(dataset_hash) = 64 "
        "AND length(campaign_result_hash) = 64 "
        "AND length(evidence_hash) = 64 "
        "AND length(source_revision) = 40 "
        "AND length(payload_sha256) = 64",
        name="ck_historical_evidence_summary_hashes",
    ),
    sa.CheckConstraint(
        "occurrences >= 0 "
        "AND settled >= 0 "
        "AND settled <= occurrences "
        "AND wins >= 0 "
        "AND losses >= 0 "
        "AND voids >= 0 "
        "AND wins + losses + voids = settled "
        "AND max_losing_streak >= 0 "
        "AND eligible_folds >= 0 "
        "AND positive_folds >= 0 "
        "AND positive_folds <= eligible_folds "
        "AND distinct_seasons >= 0 "
        "AND distinct_teams >= 0 "
        "AND distinct_groups >= 0",
        name="ck_historical_evidence_summary_counts",
    ),
    sa.CheckConstraint(
        "(hit_rate IS NULL OR (hit_rate >= 0 AND hit_rate <= 1)) "
        "AND (average_odds IS NULL OR average_odds >= 1) "
        "AND (median_odds IS NULL OR median_odds >= 1) "
        "AND total_stake_units >= 0 "
        "AND total_return_units >= 0 "
        "AND max_drawdown_units >= 0 "
        "AND (p_value IS NULL OR (p_value >= 0 AND p_value <= 1)) "
        "AND (q_value IS NULL OR (q_value >= 0 AND q_value <= 1))",
        name="ck_historical_evidence_summary_metrics",
    ),
    sa.CheckConstraint(
        "length(hypothesis_id) > 0 "
        "AND length(status) > 0 "
        "AND length(payload_object_key) > 0 "
        "AND length(schema_version) > 0 "
        "AND append_only = true "
        "AND simulation = true",
        name="ck_historical_evidence_summary_security",
    ),
)
sa.Index(
    "ix_historical_evidence_summary_hypothesis",
    hypothesis_historical_evidence_summaries.c.hypothesis_id,
)
sa.Index(
    "ix_historical_evidence_summary_rule",
    hypothesis_historical_evidence_summaries.c.rule_hash,
)
sa.Index(
    "ix_historical_evidence_summary_status",
    hypothesis_historical_evidence_summaries.c.status,
)

hypothesis_evidence_artifact_indexes = sa.Table(
    "hypothesis_evidence_artifact_indexes",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("campaign_result_hash", sa.String(length=64), nullable=False),
    sa.Column("artifact_kind", sa.String(length=80), nullable=False),
    sa.Column("object_key", sa.String(length=1500), nullable=False),
    sa.Column("payload_sha256", sa.String(length=64), nullable=False),
    sa.Column("row_count", sa.BigInteger(), nullable=False),
    sa.Column("byte_size", sa.BigInteger(), nullable=False),
    sa.Column("content_type", sa.String(length=120), nullable=False),
    sa.Column("schema_version", sa.String(length=80), nullable=False),
    sa.Column("partition_key", sa.String(length=500), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        "dataset_hash",
        "artifact_kind",
        "object_key",
        name="uq_hypothesis_evidence_artifact_identity",
    ),
    sa.CheckConstraint(
        "length(id) = 36 "
        "AND length(dataset_hash) = 64 "
        "AND length(campaign_result_hash) = 64 "
        "AND length(payload_sha256) = 64",
        name="ck_hypothesis_evidence_artifact_hashes",
    ),
    sa.CheckConstraint(
        "artifact_kind IN ("
        "'HISTORICAL_FIXTURE_EVIDENCE',"
        "'HYPOTHESIS_FIXTURE_MEMBERSHIP',"
        "'HYPOTHESIS_HISTORICAL_EVIDENCE_SUMMARY'"
        ")",
        name="ck_hypothesis_evidence_artifact_kind",
    ),
    sa.CheckConstraint(
        "row_count >= 0 "
        "AND byte_size >= 0 "
        "AND length(object_key) > 0 "
        "AND length(content_type) > 0 "
        "AND length(schema_version) > 0 "
        "AND append_only = true "
        "AND simulation = true",
        name="ck_hypothesis_evidence_artifact_security",
    ),
)
sa.Index(
    "ix_hypothesis_evidence_artifact_dataset_kind",
    hypothesis_evidence_artifact_indexes.c.dataset_hash,
    hypothesis_evidence_artifact_indexes.c.artifact_kind,
)
sa.Index(
    "ix_hypothesis_evidence_artifact_object_key",
    hypothesis_evidence_artifact_indexes.c.object_key,
)

historical_fixture_evidence_indexes = sa.Table(
    "historical_fixture_evidence_indexes",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("canonical_match_id", sa.String(length=160), nullable=False),
    sa.Column("provider_fixture_id", sa.String(length=160), nullable=False),
    sa.Column("competition_key", sa.String(length=120), nullable=False),
    sa.Column("competition_name", sa.String(length=200), nullable=False),
    sa.Column("season", sa.Integer(), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("home_team_id", sa.String(length=160), nullable=False),
    sa.Column("home_team_name", sa.String(length=240), nullable=False),
    sa.Column("away_team_id", sa.String(length=160), nullable=False),
    sa.Column("away_team_name", sa.String(length=240), nullable=False),
    sa.Column("home_goals", sa.Integer(), nullable=False),
    sa.Column("away_goals", sa.Integer(), nullable=False),
    sa.Column("final_status", sa.String(length=80), nullable=False),
    sa.Column("source_row_hash", sa.String(length=64), nullable=False),
    sa.Column("artifact_object_key", sa.String(length=1500), nullable=False),
    sa.Column("artifact_row_group", sa.Integer(), nullable=False),
    sa.Column("artifact_row_offset", sa.BigInteger(), nullable=False),
    sa.Column("schema_version", sa.String(length=80), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        "dataset_hash",
        "canonical_match_id",
        name="uq_historical_fixture_index_identity",
    ),
    sa.UniqueConstraint(
        "dataset_hash",
        "artifact_object_key",
        "artifact_row_group",
        "artifact_row_offset",
        name="uq_historical_fixture_index_artifact_row",
    ),
    sa.CheckConstraint(
        "length(id) = 36 AND length(dataset_hash) = 64 AND length(source_row_hash) = 64",
        name="ck_historical_fixture_index_hashes",
    ),
    sa.CheckConstraint(
        "length(canonical_match_id) > 0 "
        "AND length(provider_fixture_id) > 0 "
        "AND length(competition_key) > 0 "
        "AND length(competition_name) > 0 "
        "AND season > 0 "
        "AND length(home_team_id) > 0 "
        "AND length(home_team_name) > 0 "
        "AND length(away_team_id) > 0 "
        "AND length(away_team_name) > 0 "
        "AND home_goals >= 0 "
        "AND away_goals >= 0 "
        "AND length(final_status) > 0 "
        "AND artifact_row_group >= 0 "
        "AND artifact_row_offset >= 0 "
        "AND length(artifact_object_key) > 0 "
        "AND length(schema_version) > 0",
        name="ck_historical_fixture_index_values",
    ),
    sa.CheckConstraint(
        "append_only = true AND simulation = true",
        name="ck_historical_fixture_index_security",
    ),
)
sa.Index(
    "ix_historical_fixture_competition_season_kickoff",
    historical_fixture_evidence_indexes.c.competition_key,
    historical_fixture_evidence_indexes.c.season,
    historical_fixture_evidence_indexes.c.kickoff_at,
)
sa.Index(
    "ix_historical_fixture_home_team_kickoff",
    historical_fixture_evidence_indexes.c.home_team_id,
    historical_fixture_evidence_indexes.c.kickoff_at,
)
sa.Index(
    "ix_historical_fixture_away_team_kickoff",
    historical_fixture_evidence_indexes.c.away_team_id,
    historical_fixture_evidence_indexes.c.kickoff_at,
)

hypothesis_fixture_membership_indexes = sa.Table(
    "hypothesis_fixture_membership_indexes",
    metadata,
    sa.Column("id", sa.String(length=36), primary_key=True),
    sa.Column("dataset_hash", sa.String(length=64), nullable=False),
    sa.Column("campaign_result_hash", sa.String(length=64), nullable=False),
    sa.Column("hypothesis_id", sa.String(length=120), nullable=False),
    sa.Column("rule_hash", sa.String(length=64), nullable=False),
    sa.Column("canonical_match_id", sa.String(length=160), nullable=False),
    sa.Column("membership_hash", sa.String(length=64), nullable=False),
    sa.Column("competition_key", sa.String(length=120), nullable=False),
    sa.Column("season", sa.Integer(), nullable=False),
    sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("outcome", sa.String(length=8), nullable=False),
    sa.Column(
        "observed_odds",
        sa.Numeric(precision=24, scale=18),
        nullable=False,
    ),
    sa.Column(
        "market_margin",
        sa.Numeric(precision=24, scale=18),
        nullable=False,
    ),
    sa.Column(
        "profit_units",
        sa.Numeric(precision=24, scale=8),
        nullable=False,
    ),
    sa.Column("chronological_fold", sa.String(length=80), nullable=False),
    sa.Column("artifact_object_key", sa.String(length=1500), nullable=False),
    sa.Column("artifact_row_group", sa.Integer(), nullable=False),
    sa.Column("artifact_row_offset", sa.BigInteger(), nullable=False),
    sa.Column("schema_version", sa.String(length=80), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        "dataset_hash",
        "rule_hash",
        "canonical_match_id",
        name="uq_hypothesis_membership_index_identity",
    ),
    sa.UniqueConstraint(
        "dataset_hash",
        "artifact_object_key",
        "artifact_row_group",
        "artifact_row_offset",
        name="uq_hypothesis_membership_index_artifact_row",
    ),
    sa.ForeignKeyConstraint(
        ["dataset_hash", "canonical_match_id"],
        [
            "historical_fixture_evidence_indexes.dataset_hash",
            "historical_fixture_evidence_indexes.canonical_match_id",
        ],
        name="fk_hypothesis_membership_index_fixture",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "length(id) = 36 "
        "AND length(dataset_hash) = 64 "
        "AND length(campaign_result_hash) = 64 "
        "AND length(rule_hash) = 64 "
        "AND length(membership_hash) = 64",
        name="ck_hypothesis_membership_index_hashes",
    ),
    sa.CheckConstraint(
        "length(hypothesis_id) > 0 "
        "AND length(canonical_match_id) > 0 "
        "AND length(competition_key) > 0 "
        "AND season > 0 "
        "AND outcome IN ('WON', 'LOST', 'VOID') "
        "AND observed_odds >= 1 "
        "AND market_margin >= 0 "
        "AND artifact_row_group >= 0 "
        "AND artifact_row_offset >= 0 "
        "AND length(chronological_fold) > 0 "
        "AND length(artifact_object_key) > 0 "
        "AND length(schema_version) > 0",
        name="ck_hypothesis_membership_index_values",
    ),
    sa.CheckConstraint(
        "append_only = true AND simulation = true",
        name="ck_hypothesis_membership_index_security",
    ),
)
sa.Index(
    "ix_hypothesis_membership_hypothesis_kickoff",
    hypothesis_fixture_membership_indexes.c.hypothesis_id,
    hypothesis_fixture_membership_indexes.c.kickoff_at,
    hypothesis_fixture_membership_indexes.c.canonical_match_id,
)
sa.Index(
    "ix_hypothesis_membership_canonical_match",
    hypothesis_fixture_membership_indexes.c.canonical_match_id,
    hypothesis_fixture_membership_indexes.c.hypothesis_id,
)

CREATE_ORDER = (
    "hypothesis_historical_evidence_summaries",
    "hypothesis_evidence_artifact_indexes",
    "historical_fixture_evidence_indexes",
    "hypothesis_fixture_membership_indexes",
)


def _create_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION robin_reject_historical_evidence_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'append-only historical evidence table % cannot be mutated',
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
                EXECUTE FUNCTION robin_reject_historical_evidence_mutation();
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
                            'append-only historical evidence table cannot be mutated'
                        );
                    END;
                    """
                )


def _drop_append_only_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table_name in CREATE_ORDER:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}")
        op.execute("DROP FUNCTION IF EXISTS robin_reject_historical_evidence_mutation()")
    elif dialect == "sqlite":
        for table_name in CREATE_ORDER:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_{operation}")


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
