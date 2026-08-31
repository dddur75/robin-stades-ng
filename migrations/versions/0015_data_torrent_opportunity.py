"""Cross-run opportunity claims and terminal data-torrent batch index.

Revision ID: 0015_data_torrent_opportunity
Revises: 0014_chronos_control_plane_v2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.engine import Connection

revision: str = "0015_data_torrent_opportunity"
down_revision: str | None = "0014_chronos_control_plane_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

# Resolve the cross-revision composite foreign key without asking this migration
# to create or drop the 0014 authority table.
sa.Table(
    "chronos_effect_authorities",
    metadata,
    sa.Column("authority_id", sa.String(length=96), primary_key=True),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.UniqueConstraint(
        "authority_id",
        "github_run_id",
        "github_run_attempt",
        "code_revision",
        name="uq_chronos_authority_run_revision",
    ),
)

chronos_opportunity_claims = sa.Table(
    "chronos_opportunity_claims",
    metadata,
    sa.Column("opportunity_id", sa.String(length=64), primary_key=True),
    sa.Column("opportunity_kind", sa.String(length=96), nullable=False),
    sa.Column("canonical_key", sa.String(length=1024), nullable=False),
    sa.Column("mission_id", sa.String(length=160), nullable=False),
    sa.Column("authority_id", sa.String(length=96), nullable=False, unique=True),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("github_sha", sa.String(length=64), nullable=False),
    sa.Column("github_workflow_ref", sa.String(length=1024), nullable=False),
    sa.Column("github_workflow_sha", sa.String(length=64), nullable=False),
    sa.Column("github_repository", sa.String(length=255), nullable=False),
    sa.Column("github_ref", sa.String(length=1024), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.Column("db_claimed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("postgres_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column("claim_hash", sa.String(length=64), nullable=False, unique=True),
    sa.ForeignKeyConstraint(
        ["authority_id", "github_run_id", "github_run_attempt", "code_revision"],
        [
            "chronos_effect_authorities.authority_id",
            "chronos_effect_authorities.github_run_id",
            "chronos_effect_authorities.github_run_attempt",
            "chronos_effect_authorities.code_revision",
        ],
        name="fk_chronos_opportunity_authority_run_revision",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "length(opportunity_id) = 64 AND length(claim_hash) = 64",
        name="ck_chronos_opportunity_hashes",
    ),
    sa.CheckConstraint(
        "github_run_id > 0 AND github_run_attempt > 0 AND code_revision = github_sha",
        name="ck_chronos_opportunity_run",
    ),
)

chronos_torrent_batches = sa.Table(
    "chronos_torrent_batches",
    metadata,
    sa.Column("opportunity_id", sa.String(length=64), primary_key=True),
    sa.Column("raw_operation_id", sa.String(length=64), nullable=False, unique=True),
    sa.Column("raw_object_key", sa.String(length=1500), nullable=False, unique=True),
    sa.Column("raw_object_sha256", sa.String(length=64), nullable=False),
    sa.Column("normalized_operation_id", sa.String(length=64), nullable=False, unique=True),
    sa.Column("normalized_object_key", sa.String(length=1500), nullable=False, unique=True),
    sa.Column("normalized_object_sha256", sa.String(length=64), nullable=False),
    sa.Column("canonical_dataset_sha256", sa.String(length=64), nullable=False),
    sa.Column("manifest", sa.JSON(), nullable=False),
    sa.Column("raw_index", sa.JSON(), nullable=False),
    sa.Column("normalized_index", sa.JSON(), nullable=False),
    sa.Column("quality_report", sa.JSON(), nullable=False),
    sa.Column("coverage_matrix", sa.JSON(), nullable=False),
    sa.Column("official_physical_reads", sa.Integer(), nullable=False),
    sa.Column("odds_provider_requests", sa.Integer(), nullable=False),
    sa.Column("odds_credits_used", sa.Integer(), nullable=False),
    sa.Column("raw_responses", sa.Integer(), nullable=False),
    sa.Column("raw_bytes", sa.BigInteger(), nullable=False),
    sa.Column("normalized_records", sa.BigInteger(), nullable=False),
    sa.Column("rejected_records", sa.BigInteger(), nullable=False),
    sa.Column("silent_drops", sa.BigInteger(), nullable=False),
    sa.Column("logical_duplicates", sa.BigInteger(), nullable=False),
    sa.Column("temporal_leakage", sa.BigInteger(), nullable=False),
    sa.Column("replay_multiplier", sa.Integer(), nullable=False),
    sa.Column("replay_equivalent_records", sa.BigInteger(), nullable=False),
    sa.Column("replay_records_per_second", sa.Float(), nullable=False),
    sa.Column("replay_bytes_per_second", sa.Float(), nullable=False),
    sa.Column("replay_p50_latency_ms", sa.Float(), nullable=False),
    sa.Column("replay_p95_latency_ms", sa.Float(), nullable=False),
    sa.Column("replay_peak_memory_bytes", sa.BigInteger(), nullable=False),
    sa.Column("normal_required_records_per_second", sa.Float(), nullable=False),
    sa.Column("normal_required_bytes_per_second", sa.Float(), nullable=False),
    sa.Column("throughput_ratio", sa.Float(), nullable=False),
    sa.Column("idempotent_replay", sa.Boolean(), nullable=False),
    sa.Column("r2_puts", sa.Integer(), nullable=False),
    sa.Column("r2_gets", sa.Integer(), nullable=False),
    sa.Column("r2_lists", sa.Integer(), nullable=False),
    sa.Column("r2_deletes", sa.Integer(), nullable=False),
    sa.Column("r2_objects", sa.Integer(), nullable=False),
    sa.Column("automatic_retries", sa.Integer(), nullable=False),
    sa.Column("unaccounted_external_effects", sa.Integer(), nullable=False),
    sa.Column("qa_acceptance_percent", sa.Integer(), nullable=False),
    sa.Column("p0", sa.Integer(), nullable=False),
    sa.Column("p1", sa.Integer(), nullable=False),
    sa.Column("p2", sa.Integer(), nullable=False),
    sa.Column("open_threads", sa.Integer(), nullable=False),
    sa.Column("edge_promotions", sa.Integer(), nullable=False),
    sa.Column("bet_calls", sa.Integer(), nullable=False),
    sa.Column("data_torrent_ready", sa.Boolean(), nullable=False),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.Column("db_recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("postgres_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column("record_hash", sa.String(length=64), nullable=False, unique=True),
    sa.ForeignKeyConstraint(
        ["opportunity_id"],
        ["chronos_opportunity_claims.opportunity_id"],
        name="fk_chronos_torrent_opportunity",
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint(
        "length(raw_operation_id) = 64 AND length(raw_object_sha256) = 64 "
        "AND length(normalized_operation_id) = 64 "
        "AND length(normalized_object_sha256) = 64 "
        "AND length(canonical_dataset_sha256) = 64 AND length(record_hash) = 64",
        name="ck_chronos_torrent_hashes",
    ),
    sa.CheckConstraint(
        "raw_operation_id <> normalized_operation_id AND raw_object_key <> normalized_object_key",
        name="ck_chronos_torrent_distinct_objects",
    ),
    sa.CheckConstraint(
        "official_physical_reads BETWEEN 5 AND 50 "
        "AND odds_provider_requests = 5 "
        "AND odds_credits_used BETWEEN 1 AND 1000 "
        "AND raw_responses >= 10 AND raw_bytes > 0 "
        "AND normalized_records > 0 AND rejected_records >= 0",
        name="ck_chronos_torrent_budgets",
    ),
    sa.CheckConstraint(
        "silent_drops = 0 AND logical_duplicates = 0 AND temporal_leakage = 0 "
        "AND replay_multiplier >= 100 "
        "AND replay_equivalent_records = normalized_records * replay_multiplier "
        "AND replay_records_per_second > 0 AND replay_bytes_per_second > 0 "
        "AND replay_records_per_second < 1e308 "
        "AND replay_bytes_per_second < 1e308 "
        "AND replay_p50_latency_ms >= 0 "
        "AND replay_p95_latency_ms >= replay_p50_latency_ms "
        "AND replay_p95_latency_ms < 1e308 "
        "AND replay_peak_memory_bytes >= 0 "
        "AND normal_required_records_per_second > 0 "
        "AND normal_required_bytes_per_second > 0 "
        "AND normal_required_records_per_second < 1e308 "
        "AND normal_required_bytes_per_second < 1e308 "
        "AND throughput_ratio >= 5 AND throughput_ratio < 1e308 "
        "AND replay_records_per_second >= "
        "5 * normal_required_records_per_second "
        "AND replay_bytes_per_second >= 5 * normal_required_bytes_per_second "
        "AND idempotent_replay AND qa_acceptance_percent = 100 "
        "AND r2_puts = 2 AND r2_gets BETWEEN 0 AND 2 "
        "AND r2_lists BETWEEN 0 AND 2 AND r2_deletes = 0 "
        "AND r2_objects = 2 AND automatic_retries = 0 "
        "AND unaccounted_external_effects = 0 "
        "AND p0 = 0 AND p1 = 0 AND p2 = 0 AND open_threads = 0 "
        "AND edge_promotions = 0 AND bet_calls = 0 AND data_torrent_ready",
        name="ck_chronos_torrent_acceptance",
    ),
)

chronos_torrent_external_effect_permits = sa.Table(
    "chronos_torrent_external_effect_permits",
    metadata,
    sa.Column("operation_id", sa.String(length=64), primary_key=True),
    sa.Column("opportunity_id", sa.String(length=64), nullable=False),
    sa.Column("effect_family", sa.String(length=16), nullable=False),
    sa.Column("effect_sequence", sa.Integer(), nullable=False),
    sa.Column("request_hash", sa.String(length=64), nullable=False),
    sa.Column("max_official_reads", sa.Integer(), nullable=False),
    sa.Column("max_odds_requests", sa.Integer(), nullable=False),
    sa.Column("max_odds_credits", sa.Integer(), nullable=False),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.Column("db_permitted_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("postgres_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column("permit_hash", sa.String(length=64), nullable=False, unique=True),
    sa.ForeignKeyConstraint(
        ["opportunity_id"],
        ["chronos_opportunity_claims.opportunity_id"],
        name="fk_chronos_torrent_external_opportunity",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "opportunity_id",
        "effect_family",
        "effect_sequence",
        name="uq_chronos_torrent_external_sequence",
    ),
    sa.CheckConstraint(
        "effect_family IN ('OFFICIAL','ODDS') AND effect_sequence > 0 "
        "AND length(operation_id) = 64 AND length(request_hash) = 64 "
        "AND length(permit_hash) = 64",
        name="ck_chronos_torrent_external_permit_identity",
    ),
    sa.CheckConstraint(
        "(effect_family = 'OFFICIAL' AND max_official_reads BETWEEN 1 AND 12 "
        "AND max_odds_requests = 0 AND max_odds_credits = 0) OR "
        "(effect_family = 'ODDS' AND max_official_reads = 0 "
        "AND max_odds_requests = 1 AND max_odds_credits BETWEEN 1 AND 1000)",
        name="ck_chronos_torrent_external_permit_budget",
    ),
)

chronos_torrent_external_effect_events = sa.Table(
    "chronos_torrent_external_effect_events",
    metadata,
    sa.Column("event_id", sa.String(length=96), primary_key=True),
    sa.Column("operation_id", sa.String(length=64), nullable=False),
    sa.Column("event_seq", sa.Integer(), nullable=False),
    sa.Column("event_type", sa.String(length=40), nullable=False),
    sa.Column("actual_official_reads", sa.Integer(), nullable=False),
    sa.Column("actual_odds_requests", sa.Integer(), nullable=False),
    sa.Column("actual_odds_credits", sa.Integer(), nullable=False),
    sa.Column("db_recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("postgres_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column("previous_event_hash", sa.String(length=64), nullable=False),
    sa.Column("event_hash", sa.String(length=64), nullable=False, unique=True),
    sa.ForeignKeyConstraint(
        ["operation_id"],
        ["chronos_torrent_external_effect_permits.operation_id"],
        name="fk_chronos_torrent_external_event_permit",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "operation_id",
        "event_seq",
        name="uq_chronos_torrent_external_event_sequence",
    ),
    sa.UniqueConstraint(
        "operation_id",
        "event_type",
        name="uq_chronos_torrent_external_event_type",
    ),
    sa.CheckConstraint(
        "event_seq BETWEEN 1 AND 2 AND event_type IN "
        "('DISPATCHED','CONFIRMED','FAILED_BEFORE_DISPATCH',"
        "'FAILED_AFTER_DISPATCH','AMBIGUOUS') "
        "AND actual_official_reads >= 0 AND actual_odds_requests >= 0 "
        "AND actual_odds_credits >= 0 AND length(previous_event_hash) = 64 "
        "AND length(event_hash) = 64",
        name="ck_chronos_torrent_external_event",
    ),
)

TABLES = (
    "chronos_opportunity_claims",
    "chronos_torrent_external_effect_permits",
    "chronos_torrent_external_effect_events",
    "chronos_torrent_batches",
)


def _storage_metadata(dialect_name: str) -> sa.MetaData:
    if dialect_name != "postgresql":
        return metadata
    qualified = sa.MetaData()
    for table in metadata.sorted_tables:
        table.to_metadata(qualified, schema="public")
    return qualified


def _owned_tables(storage: sa.MetaData, dialect_name: str) -> list[sa.Table]:
    prefix = "public." if dialect_name == "postgresql" else ""
    return [storage.tables[f"{prefix}{name}"] for name in TABLES]


def _existing_owned_table_names(connection: Connection) -> set[str]:
    schema = "public" if connection.dialect.name == "postgresql" else None
    return set(inspect(connection).get_table_names(schema=schema))


def _create_sqlite_guards() -> None:
    for table_name in TABLES:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN');
                END
                """
            )


def _create_postgresql_objects() -> None:
    op.execute(
        """
        CREATE FUNCTION public.chronos_claim_opportunity(
          p_authority_id text, p_mission_id text, p_github_run_id bigint,
          p_github_run_attempt integer, p_github_sha text,
          p_github_workflow_ref text, p_github_workflow_sha text,
          p_github_repository text, p_github_ref text,
          p_generation_nonce bytea, p_opportunity_id text,
          p_opportunity_kind text, p_canonical_key text, p_code_revision text)
        RETURNS TABLE(opportunity_id text, acquired_now boolean,
          winner_authority_id text, winner_github_run_id bigint,
          winner_github_run_attempt integer, db_claimed_at timestamptz,
          postgres_server_epoch timestamptz, claim_receipt_hash text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          a public.chronos_effect_authorities%ROWTYPE;
          c public.chronos_opportunity_claims%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz; v_expected_id text;
          v_generation text; v_inserted boolean := false;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_runtime_writer', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_RUNTIME_WRITER_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID'; END IF;
          IF p_authority_id IS NULL OR p_mission_id IS NULL
             OR p_github_run_id IS NULL OR p_github_run_attempt IS NULL
             OR p_github_sha IS NULL OR p_github_workflow_ref IS NULL
             OR p_github_workflow_sha IS NULL OR p_github_repository IS NULL
             OR p_github_ref IS NULL OR p_opportunity_id IS NULL
             OR p_opportunity_kind IS NULL OR p_canonical_key IS NULL
             OR p_code_revision IS NULL OR p_opportunity_kind = ''
             OR p_canonical_key = '' THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_INPUT_INVALID'; END IF;
          v_expected_id := public.chronos_framed_sha256(VARIADIC ARRAY[
            'data-torrent-opportunity-v1', p_opportunity_kind, p_canonical_key]);
          IF v_expected_id IS DISTINCT FROM p_opportunity_id THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_ID_MISMATCH'; END IF;
          SELECT * INTO a FROM public.chronos_effect_authorities
          WHERE chronos_effect_authorities.authority_id=p_authority_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_FOUND'; END IF;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          v_generation := pg_catalog.encode(
            pg_catalog.sha256(p_generation_nonce), 'hex');
          IF a.mission_id IS DISTINCT FROM p_mission_id
             OR a.github_run_id IS DISTINCT FROM p_github_run_id
             OR a.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR a.github_sha IS DISTINCT FROM p_github_sha
             OR a.github_workflow_ref IS DISTINCT FROM p_github_workflow_ref
             OR a.github_workflow_sha IS DISTINCT FROM p_github_workflow_sha
             OR a.github_repository IS DISTINCT FROM p_github_repository
             OR a.github_ref IS DISTINCT FROM p_github_ref
             OR a.code_revision IS DISTINCT FROM p_code_revision THEN
            RAISE EXCEPTION 'CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH'; END IF;
          IF a.postgres_server_epoch IS DISTINCT FROM v_epoch THEN
            RAISE EXCEPTION 'CHRONOS_SERVER_EPOCH_MISMATCH'; END IF;
          IF a.control_plane_generation_hash IS DISTINCT FROM v_generation THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          IF NOT (a.planned_at <= v_now AND v_now < a.expires_at) THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_ACTIVE'; END IF;

          INSERT INTO public.chronos_opportunity_claims (
            opportunity_id, opportunity_kind, canonical_key, mission_id,
            authority_id, github_run_id, github_run_attempt, github_sha,
            github_workflow_ref, github_workflow_sha, github_repository,
            github_ref, code_revision, db_claimed_at, postgres_server_epoch,
            claim_hash)
          VALUES (
            p_opportunity_id, p_opportunity_kind, p_canonical_key, p_mission_id,
            p_authority_id, p_github_run_id, p_github_run_attempt, p_github_sha,
            p_github_workflow_ref, p_github_workflow_sha, p_github_repository,
            p_github_ref, p_code_revision, v_now, v_epoch,
            public.chronos_framed_sha256(VARIADIC ARRAY[
              'data-torrent-opportunity-claim-v1', p_opportunity_id,
              p_authority_id, p_github_run_id::text,
              p_github_run_attempt::text, p_code_revision,
              pg_catalog.to_char(v_now AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
              pg_catalog.to_char(v_epoch AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')]))
          ON CONFLICT ON CONSTRAINT chronos_opportunity_claims_pkey DO NOTHING
          RETURNING * INTO c;
          v_inserted := FOUND;
          IF NOT v_inserted THEN
            SELECT * INTO c FROM public.chronos_opportunity_claims
            WHERE chronos_opportunity_claims.opportunity_id=p_opportunity_id;
          END IF;
          IF c.opportunity_kind IS DISTINCT FROM p_opportunity_kind
             OR c.canonical_key IS DISTINCT FROM p_canonical_key THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_ID_COLLISION'; END IF;
          RETURN QUERY SELECT c.opportunity_id::text, v_inserted,
            c.authority_id::text, c.github_run_id, c.github_run_attempt,
            c.db_claimed_at, c.postgres_server_epoch, c.claim_hash::text;
        END;
        $fn$;

        CREATE FUNCTION public.chronos_reserve_torrent_external_effect(
          p_opportunity_id text, p_effect_family text,
          p_effect_sequence integer, p_request_hash text,
          p_max_official_reads integer, p_max_odds_requests integer,
          p_max_odds_credits integer, p_github_run_id bigint,
          p_github_run_attempt integer, p_code_revision text,
          p_generation_nonce bytea)
        RETURNS TABLE(operation_id text, created_now boolean,
          db_permitted_at timestamptz, postgres_server_epoch timestamptz,
          permit_hash text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          c public.chronos_opportunity_claims%ROWTYPE;
          a public.chronos_effect_authorities%ROWTYPE;
          p public.chronos_torrent_external_effect_permits%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz;
          v_operation_id text; v_permit_hash text;
          v_official integer; v_odds_requests integer; v_odds_credits integer;
          v_generation text; v_inserted boolean := false;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_runtime_writer', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_RUNTIME_WRITER_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID'; END IF;
          IF p_opportunity_id IS NULL OR p_effect_family IS NULL
             OR p_effect_sequence IS NULL OR p_request_hash IS NULL
             OR p_max_official_reads IS NULL OR p_max_odds_requests IS NULL
             OR p_max_odds_credits IS NULL OR p_github_run_id IS NULL
             OR p_github_run_attempt IS NULL OR p_code_revision IS NULL
             OR pg_catalog.length(p_opportunity_id) <> 64
             OR pg_catalog.length(p_request_hash) <> 64
             OR p_effect_sequence <= 0 THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_INPUT_INVALID'; END IF;
          IF NOT (
            (p_effect_family='OFFICIAL'
              AND p_max_official_reads BETWEEN 1 AND 12
              AND p_max_odds_requests=0 AND p_max_odds_credits=0)
            OR (p_effect_family='ODDS' AND p_max_official_reads=0
              AND p_max_odds_requests=1
              AND p_max_odds_credits BETWEEN 1 AND 1000)) THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_BUDGET_INVALID'; END IF;
          SELECT * INTO c FROM public.chronos_opportunity_claims
          WHERE chronos_opportunity_claims.opportunity_id=p_opportunity_id
          FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_NOT_FOUND'; END IF;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          IF c.github_run_id IS DISTINCT FROM p_github_run_id
             OR c.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR c.code_revision IS DISTINCT FROM p_code_revision THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_WINNER_REQUIRED'; END IF;
          IF c.postgres_server_epoch IS DISTINCT FROM v_epoch THEN
            RAISE EXCEPTION 'CHRONOS_SERVER_EPOCH_MISMATCH'; END IF;
          SELECT * INTO a FROM public.chronos_effect_authorities
          WHERE chronos_effect_authorities.authority_id=c.authority_id;
          v_generation := a.control_plane_generation_hash;
          IF v_generation IS DISTINCT FROM pg_catalog.encode(
              pg_catalog.sha256(p_generation_nonce), 'hex') THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          IF NOT (a.planned_at <= v_now AND v_now < a.expires_at) THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_ACTIVE'; END IF;
          IF EXISTS (SELECT 1 FROM public.chronos_torrent_batches b
                     WHERE b.opportunity_id=p_opportunity_id) THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_ACCEPTANCE_FAILED'; END IF;
          v_operation_id := public.chronos_framed_sha256(VARIADIC ARRAY[
            'data-torrent-external-effect-v1', p_opportunity_id,
            p_github_run_id::text, p_github_run_attempt::text,
            p_effect_family, p_effect_sequence::text, p_request_hash]);
          SELECT * INTO p FROM public.chronos_torrent_external_effect_permits
          WHERE opportunity_id=p_opportunity_id
            AND effect_family=p_effect_family
            AND effect_sequence=p_effect_sequence;
          IF FOUND THEN
            IF p.operation_id IS DISTINCT FROM v_operation_id
               OR p.request_hash IS DISTINCT FROM p_request_hash
               OR p.max_official_reads IS DISTINCT FROM p_max_official_reads
               OR p.max_odds_requests IS DISTINCT FROM p_max_odds_requests
               OR p.max_odds_credits IS DISTINCT FROM p_max_odds_credits
               OR p.github_run_id IS DISTINCT FROM p_github_run_id
               OR p.github_run_attempt IS DISTINCT FROM p_github_run_attempt
               OR p.code_revision IS DISTINCT FROM p_code_revision THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_PERMIT_CONFLICT'; END IF;
            RETURN QUERY SELECT p.operation_id::text, false,
              p.db_permitted_at, p.postgres_server_epoch, p.permit_hash::text;
            RETURN;
          END IF;
          SELECT * INTO p FROM public.chronos_torrent_external_effect_permits
          WHERE chronos_torrent_external_effect_permits.operation_id=
            v_operation_id;
          IF FOUND THEN
            IF p.opportunity_id IS DISTINCT FROM p_opportunity_id
               OR p.effect_family IS DISTINCT FROM p_effect_family
               OR p.effect_sequence IS DISTINCT FROM p_effect_sequence
               OR p.request_hash IS DISTINCT FROM p_request_hash
               OR p.max_official_reads IS DISTINCT FROM p_max_official_reads
               OR p.max_odds_requests IS DISTINCT FROM p_max_odds_requests
               OR p.max_odds_credits IS DISTINCT FROM p_max_odds_credits
               OR p.github_run_id IS DISTINCT FROM p_github_run_id
               OR p.github_run_attempt IS DISTINCT FROM p_github_run_attempt
               OR p.code_revision IS DISTINCT FROM p_code_revision THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_PERMIT_CONFLICT'; END IF;
            RETURN QUERY SELECT p.operation_id::text, false,
              p.db_permitted_at, p.postgres_server_epoch, p.permit_hash::text;
            RETURN;
          END IF;
          SELECT
            COALESCE(pg_catalog.sum(max_official_reads),0)::integer,
            COALESCE(pg_catalog.sum(max_odds_requests),0)::integer,
            COALESCE(pg_catalog.sum(max_odds_credits),0)::integer
          INTO v_official, v_odds_requests, v_odds_credits
          FROM public.chronos_torrent_external_effect_permits
          WHERE opportunity_id=p_opportunity_id;
          IF v_official + p_max_official_reads > 50
             OR v_odds_requests + p_max_odds_requests > 5
             OR v_odds_credits + p_max_odds_credits > 1000 THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_BUDGET_EXCEEDED'; END IF;
          v_permit_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
            'data-torrent-external-effect-permit-v1', v_operation_id,
            p_opportunity_id, p_effect_family, p_effect_sequence::text,
            p_request_hash, p_max_official_reads::text,
            p_max_odds_requests::text, p_max_odds_credits::text,
            pg_catalog.to_char(v_now AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            pg_catalog.to_char(v_epoch AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')]);
          INSERT INTO public.chronos_torrent_external_effect_permits (
            operation_id, opportunity_id, effect_family, effect_sequence,
            request_hash, max_official_reads, max_odds_requests,
            max_odds_credits, github_run_id, github_run_attempt, code_revision,
            db_permitted_at, postgres_server_epoch, permit_hash)
          VALUES (v_operation_id, p_opportunity_id, p_effect_family,
            p_effect_sequence, p_request_hash, p_max_official_reads,
            p_max_odds_requests, p_max_odds_credits, p_github_run_id,
            p_github_run_attempt, p_code_revision, v_now, v_epoch,
            v_permit_hash)
          ON CONFLICT ON CONSTRAINT chronos_torrent_external_effect_permits_pkey
          DO NOTHING RETURNING * INTO p;
          v_inserted := FOUND;
          IF NOT v_inserted THEN
            SELECT * INTO p FROM public.chronos_torrent_external_effect_permits
            WHERE chronos_torrent_external_effect_permits.operation_id=
              v_operation_id;
            IF p.opportunity_id IS DISTINCT FROM p_opportunity_id
               OR p.effect_family IS DISTINCT FROM p_effect_family
               OR p.effect_sequence IS DISTINCT FROM p_effect_sequence
               OR p.request_hash IS DISTINCT FROM p_request_hash
               OR p.max_official_reads IS DISTINCT FROM p_max_official_reads
               OR p.max_odds_requests IS DISTINCT FROM p_max_odds_requests
               OR p.max_odds_credits IS DISTINCT FROM p_max_odds_credits
               OR p.github_run_id IS DISTINCT FROM p_github_run_id
               OR p.github_run_attempt IS DISTINCT FROM p_github_run_attempt
               OR p.code_revision IS DISTINCT FROM p_code_revision THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_PERMIT_CONFLICT'; END IF;
          END IF;
          RETURN QUERY SELECT p.operation_id::text, v_inserted,
            p.db_permitted_at, p.postgres_server_epoch, p.permit_hash::text;
        END;
        $fn$;

        CREATE FUNCTION public.chronos_append_torrent_external_effect(
          p_operation_id text, p_event_type text,
          p_actual_official_reads integer, p_actual_odds_requests integer,
          p_actual_odds_credits integer, p_github_run_id bigint,
          p_github_run_attempt integer, p_code_revision text,
          p_generation_nonce bytea)
        RETURNS TABLE(operation_id text, event_seq integer, event_type text,
          actual_official_reads integer, actual_odds_requests integer,
          actual_odds_credits integer, db_recorded_at timestamptz,
          postgres_server_epoch timestamptz, previous_event_hash text,
          event_hash text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          p public.chronos_torrent_external_effect_permits%ROWTYPE;
          c public.chronos_opportunity_claims%ROWTYPE;
          a public.chronos_effect_authorities%ROWTYPE;
          previous public.chronos_torrent_external_effect_events%ROWTYPE;
          e public.chronos_torrent_external_effect_events%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz;
          v_sequence integer; v_previous_hash text; v_hash text;
          v_generation text;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_runtime_writer', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_RUNTIME_WRITER_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID'; END IF;
          IF p_operation_id IS NULL OR p_event_type IS NULL
             OR p_actual_official_reads IS NULL
             OR p_actual_odds_requests IS NULL OR p_actual_odds_credits IS NULL
             OR p_github_run_id IS NULL OR p_github_run_attempt IS NULL
             OR p_code_revision IS NULL OR p_actual_official_reads < 0
             OR p_actual_odds_requests < 0 OR p_actual_odds_credits < 0 THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_INPUT_INVALID'; END IF;
          SELECT * INTO p FROM public.chronos_torrent_external_effect_permits
          WHERE chronos_torrent_external_effect_permits.operation_id=
            p_operation_id FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_PERMIT_NOT_FOUND'; END IF;
          SELECT * INTO c FROM public.chronos_opportunity_claims
          WHERE chronos_opportunity_claims.opportunity_id=p.opportunity_id;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          IF c.github_run_id IS DISTINCT FROM p_github_run_id
             OR c.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR c.code_revision IS DISTINCT FROM p_code_revision
             OR p.github_run_id IS DISTINCT FROM p_github_run_id
             OR p.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR p.code_revision IS DISTINCT FROM p_code_revision THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_WINNER_REQUIRED'; END IF;
          IF p.postgres_server_epoch IS DISTINCT FROM v_epoch
             OR c.postgres_server_epoch IS DISTINCT FROM v_epoch THEN
            RAISE EXCEPTION 'CHRONOS_SERVER_EPOCH_MISMATCH'; END IF;
          SELECT * INTO a FROM public.chronos_effect_authorities
          WHERE chronos_effect_authorities.authority_id=c.authority_id;
          v_generation := a.control_plane_generation_hash;
          IF v_generation IS DISTINCT FROM pg_catalog.encode(
              pg_catalog.sha256(p_generation_nonce), 'hex') THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          IF p_event_type='DISPATCHED'
             AND NOT (a.planned_at <= v_now AND v_now < a.expires_at) THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_ACTIVE'; END IF;
          SELECT * INTO previous
          FROM public.chronos_torrent_external_effect_events
          WHERE chronos_torrent_external_effect_events.operation_id=
            p_operation_id
          ORDER BY chronos_torrent_external_effect_events.event_seq DESC
          LIMIT 1;
          IF FOUND AND previous.event_type=p_event_type THEN
            IF previous.actual_official_reads IS DISTINCT FROM
                 p_actual_official_reads
               OR previous.actual_odds_requests IS DISTINCT FROM
                 p_actual_odds_requests
               OR previous.actual_odds_credits IS DISTINCT FROM
                 p_actual_odds_credits THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_EVENT_CONFLICT'; END IF;
            RETURN QUERY SELECT previous.operation_id::text,
              previous.event_seq, previous.event_type::text,
              previous.actual_official_reads, previous.actual_odds_requests,
              previous.actual_odds_credits, previous.db_recorded_at,
              previous.postgres_server_epoch,
              previous.previous_event_hash::text, previous.event_hash::text;
            RETURN;
          END IF;
          IF NOT FOUND THEN
            IF p_event_type NOT IN ('DISPATCHED','FAILED_BEFORE_DISPATCH') THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_TRANSITION_FORBIDDEN'; END IF;
            v_sequence := 1; v_previous_hash := p.permit_hash;
          ELSE
            IF previous.event_type <> 'DISPATCHED'
               OR p_event_type NOT IN
                 ('CONFIRMED','FAILED_AFTER_DISPATCH','AMBIGUOUS') THEN
              RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_TRANSITION_FORBIDDEN'; END IF;
            v_sequence := 2; v_previous_hash := previous.event_hash;
          END IF;
          IF p_event_type IN ('DISPATCHED','FAILED_BEFORE_DISPATCH')
             AND (p_actual_official_reads <> 0 OR p_actual_odds_requests <> 0
                  OR p_actual_odds_credits <> 0) THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_ACCOUNTING_INVALID'; END IF;
          IF p_event_type='CONFIRMED' AND NOT (
            (p.effect_family='OFFICIAL'
              AND p_actual_official_reads BETWEEN 1 AND p.max_official_reads
              AND p_actual_odds_requests=0 AND p_actual_odds_credits=0)
            OR (p.effect_family='ODDS' AND p_actual_official_reads=0
              AND p_actual_odds_requests=1
              AND p_actual_odds_credits BETWEEN 0 AND p.max_odds_credits)) THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_ACCOUNTING_INVALID'; END IF;
          IF p_event_type IN ('FAILED_AFTER_DISPATCH','AMBIGUOUS')
             AND (p_actual_official_reads > p.max_official_reads
               OR p_actual_odds_requests > p.max_odds_requests
               OR p_actual_odds_credits > p.max_odds_credits) THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECT_ACCOUNTING_INVALID'; END IF;
          v_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
            'data-torrent-external-effect-event-v1', p_operation_id,
            v_sequence::text, p_event_type, p_actual_official_reads::text,
            p_actual_odds_requests::text, p_actual_odds_credits::text,
            pg_catalog.to_char(v_now AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            pg_catalog.to_char(v_epoch AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), v_previous_hash]);
          INSERT INTO public.chronos_torrent_external_effect_events VALUES (
            'torrent-external-event:' || v_hash, p_operation_id, v_sequence,
            p_event_type, p_actual_official_reads, p_actual_odds_requests,
            p_actual_odds_credits, v_now, v_epoch, v_previous_hash, v_hash)
          RETURNING * INTO e;
          RETURN QUERY SELECT e.operation_id::text, e.event_seq,
            e.event_type::text, e.actual_official_reads,
            e.actual_odds_requests, e.actual_odds_credits, e.db_recorded_at,
            e.postgres_server_epoch, e.previous_event_hash::text,
            e.event_hash::text;
        END;
        $fn$;

        CREATE FUNCTION public.chronos_record_torrent_batch(
          p_opportunity_id text,
          p_raw_operation_id text, p_raw_object_key text,
          p_raw_object_sha256 text,
          p_normalized_operation_id text, p_normalized_object_key text,
          p_normalized_object_sha256 text, p_canonical_dataset_sha256 text,
          p_manifest jsonb, p_raw_index jsonb, p_normalized_index jsonb,
          p_quality_report jsonb, p_coverage_matrix jsonb,
          p_official_physical_reads integer, p_odds_provider_requests integer,
          p_odds_credits_used integer, p_raw_responses integer,
          p_raw_bytes bigint, p_normalized_records bigint,
          p_rejected_records bigint, p_silent_drops bigint,
          p_logical_duplicates bigint, p_temporal_leakage bigint,
          p_replay_multiplier integer, p_replay_equivalent_records bigint,
          p_replay_records_per_second double precision,
          p_replay_bytes_per_second double precision,
          p_replay_p50_latency_ms double precision,
          p_replay_p95_latency_ms double precision,
          p_replay_peak_memory_bytes bigint,
          p_normal_required_records_per_second double precision,
          p_normal_required_bytes_per_second double precision,
          p_throughput_ratio double precision, p_idempotent_replay boolean,
          p_r2_puts integer, p_r2_gets integer, p_r2_lists integer,
          p_r2_deletes integer, p_r2_objects integer,
          p_automatic_retries integer, p_unaccounted_external_effects integer,
          p_qa_acceptance_percent integer, p_p0 integer, p_p1 integer,
          p_p2 integer, p_open_threads integer, p_edge_promotions integer,
          p_bet_calls integer, p_data_torrent_ready boolean,
          p_github_run_id bigint,
          p_github_run_attempt integer, p_code_revision text,
          p_generation_nonce bytea)
        RETURNS TABLE(opportunity_id text, created_now boolean,
          db_recorded_at timestamptz, postgres_server_epoch timestamptz,
          record_hash text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          c public.chronos_opportunity_claims%ROWTYPE;
          b public.chronos_torrent_batches%ROWTYPE;
          raw_event public.chronos_effect_events%ROWTYPE;
          normalized_event public.chronos_effect_events%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz;
          v_record_hash text; v_inserted boolean := false;
          v_official_permits integer; v_odds_permits integer;
          v_official_reads integer; v_odds_requests integer;
          v_odds_credits integer;
          v_r2_puts integer; v_r2_gets integer;
          v_recovery_v2 boolean;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_runtime_writer', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_RUNTIME_WRITER_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID'; END IF;
          IF p_opportunity_id IS NULL OR p_raw_operation_id IS NULL
             OR p_raw_object_key IS NULL OR p_raw_object_sha256 IS NULL
             OR p_normalized_operation_id IS NULL
             OR p_normalized_object_key IS NULL
             OR p_normalized_object_sha256 IS NULL
             OR p_canonical_dataset_sha256 IS NULL OR p_manifest IS NULL
             OR p_raw_index IS NULL OR p_normalized_index IS NULL
             OR p_quality_report IS NULL OR p_coverage_matrix IS NULL
             OR p_official_physical_reads IS NULL
             OR p_odds_provider_requests IS NULL
             OR p_odds_credits_used IS NULL OR p_raw_responses IS NULL
             OR p_raw_bytes IS NULL OR p_normalized_records IS NULL
             OR p_rejected_records IS NULL OR p_silent_drops IS NULL
             OR p_logical_duplicates IS NULL OR p_temporal_leakage IS NULL
             OR p_replay_multiplier IS NULL
             OR p_replay_equivalent_records IS NULL
             OR p_replay_records_per_second IS NULL
             OR p_replay_bytes_per_second IS NULL
             OR p_replay_p50_latency_ms IS NULL
             OR p_replay_p95_latency_ms IS NULL
             OR p_replay_peak_memory_bytes IS NULL
             OR p_normal_required_records_per_second IS NULL
             OR p_normal_required_bytes_per_second IS NULL
             OR p_throughput_ratio IS NULL OR p_idempotent_replay IS NULL
             OR p_r2_puts IS NULL OR p_r2_gets IS NULL
             OR p_r2_lists IS NULL OR p_r2_deletes IS NULL
             OR p_r2_objects IS NULL OR p_automatic_retries IS NULL
             OR p_unaccounted_external_effects IS NULL
             OR p_qa_acceptance_percent IS NULL OR p_p0 IS NULL
             OR p_p1 IS NULL OR p_p2 IS NULL OR p_open_threads IS NULL
             OR p_edge_promotions IS NULL OR p_bet_calls IS NULL
             OR p_data_torrent_ready IS NULL
             OR p_github_run_id IS NULL OR p_github_run_attempt IS NULL
             OR p_code_revision IS NULL THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_BATCH_INPUT_INVALID'; END IF;
          IF p_raw_operation_id=p_normalized_operation_id
             OR p_raw_object_key=p_normalized_object_key THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_BATCH_INPUT_INVALID'; END IF;
          v_recovery_v2 := p_manifest->>'mission_id' =
            'data-torrent-recovery-v2';
          IF p_manifest->>'mission_id' IS NULL
             OR p_manifest->>'mission_id' NOT IN
                ('data-torrent-ready-v1','data-torrent-recovery-v2')
             OR p_raw_index->>'mission_id' IS DISTINCT FROM
                p_manifest->>'mission_id'
             OR p_normalized_index->>'mission_id' IS DISTINCT FROM
                p_manifest->>'mission_id'
             OR p_quality_report->>'mission_id' IS DISTINCT FROM
                p_manifest->>'mission_id'
             OR pg_catalog.jsonb_typeof(p_manifest) IS DISTINCT FROM 'object'
             OR pg_catalog.jsonb_typeof(p_raw_index) IS DISTINCT FROM 'object'
             OR pg_catalog.jsonb_typeof(p_normalized_index) IS DISTINCT FROM 'object'
             OR pg_catalog.jsonb_typeof(p_quality_report) IS DISTINCT FROM 'object'
             OR p_manifest->>'schema_version' IS DISTINCT FROM
                'robin-data-torrent-real-batch-manifest-v1'
             OR p_manifest->>'status' IS DISTINCT FROM 'SUCCESS'
             OR pg_catalog.jsonb_typeof(p_manifest->'post_merge_ci_proof')
                IS DISTINCT FROM 'object'
             OR p_manifest#>>'{post_merge_ci_proof,conclusion}'
                IS DISTINCT FROM 'success'
             OR pg_catalog.jsonb_typeof(p_manifest->'artifacts')
                IS DISTINCT FROM 'array'
             OR pg_catalog.jsonb_array_length(p_manifest->'artifacts') <> 18
             OR (
               SELECT pg_catalog.array_agg(
                 artifact->>'name' ORDER BY artifact->>'name')
               FROM pg_catalog.jsonb_array_elements(
                 p_manifest->'artifacts') artifact
             ) IS DISTINCT FROM ARRAY[
               'hypothesis-backlog-from-real-data-v1.md',
               'hypothesis-ready-field-dictionary-v1.json',
               'robin-data-torrent-operations-pack-v1.md',
               'robin-data-torrent-recovery-pack-v1.md',
               'torrent-canonical-dataset-hash-v1.json',
               'torrent-control-plane-event-chain-v1.json',
               'torrent-load-replay-report-v1.json',
               'torrent-load-replay-report-v1.md',
               'torrent-official-read-receipts-v1.json',
               'torrent-opportunity-claim-receipt-v1.json',
               'torrent-provider-credit-receipt-v1.json',
               'torrent-qa-acceptance-matrix-v1.json',
               'torrent-r2-inventory-v1.json',
               'torrent-raw-to-normalized-lineage-v1.json',
               'torrent-real-batch-coverage-matrix-v1.csv',
               'torrent-real-batch-normalized-index-v1.json',
               'torrent-real-batch-quality-report-v1.json',
               'torrent-real-batch-raw-index-v1.json'
             ]::text[]
             OR EXISTS (
               SELECT 1 FROM pg_catalog.jsonb_array_elements(
                 p_manifest->'artifacts') artifact
               WHERE pg_catalog.jsonb_typeof(artifact) IS DISTINCT FROM 'object'
                  OR (
                    SELECT pg_catalog.array_agg(key ORDER BY key)
                    FROM pg_catalog.jsonb_object_keys(artifact) key
                  ) IS DISTINCT FROM ARRAY['bytes','name','sha256']::text[]
                  OR artifact->>'sha256' !~ '^[0-9a-f]{64}$'
                  OR pg_catalog.jsonb_typeof(artifact->'bytes')
                     IS DISTINCT FROM 'number'
                  OR (artifact->>'bytes')::bigint <= 0)
             OR (
               v_recovery_v2 AND (
                 p_raw_object_key IS DISTINCT FROM
                   'data-torrent/recovery-v2/' || p_opportunity_id || '/raw.tar.gz'
                 OR p_normalized_object_key IS DISTINCT FROM
                   'data-torrent/recovery-v2/' || p_opportunity_id ||
                   '/normalized-evidence.tar.gz'
                 OR p_manifest#>>'{evidence_validity,mode}' IS DISTINCT FROM
                   'DIRECT_CREATED_DURABLE_BINDING_V2'
                 OR p_manifest#>>'{durability,verification_status}'
                   IS DISTINCT FROM 'CREATED_CONFIRMED_BEFORE_REPLAY'
                  OR p_manifest->>'hypotheses_generated' IS DISTINCT FROM '0'
                  OR p_manifest->>'purchases' IS DISTINCT FROM '0'
                  OR p_manifest->>'missed_windows' IS DISTINCT FROM
                    'MISSED_NOT_BACKDATED'
                  OR p_raw_index#>>'{archive_object,object_key}' IS DISTINCT FROM
                    p_raw_object_key
                  OR p_raw_index#>>'{archive_object,sha256}' IS DISTINCT FROM
                    p_raw_object_sha256
                  OR p_raw_index#>>'{archive_object,media_type}' IS DISTINCT FROM
                    'application/gzip'
                  OR p_raw_index#>>'{archive_object,format}' IS DISTINCT FROM
                    'DETERMINISTIC_USTAR_GZIP_V1'
                  OR pg_catalog.jsonb_typeof(
                    p_raw_index#>'{archive_object,bytes}') IS DISTINCT FROM 'number'
                  OR (p_raw_index#>>'{archive_object,bytes}')::bigint <= 0
                  OR p_manifest#>>'{durability,raw_object,role}' IS DISTINCT FROM
                    'RAW'
                  OR p_manifest#>>'{durability,raw_object,object_key}'
                    IS DISTINCT FROM p_raw_object_key
                  OR p_manifest#>>'{durability,raw_object,object_sha256}'
                    IS DISTINCT FROM p_raw_object_sha256
                  OR p_manifest#>>'{durability,raw_object,operation_id}'
                    IS DISTINCT FROM p_raw_operation_id
                  OR p_manifest#>>'{durability,raw_object,terminal_event}'
                    IS DISTINCT FROM 'CREATED_CONFIRMED'
                  OR p_manifest#>>'{durability,raw_object,terminal_event_hash}'
                    !~ '^[0-9a-f]{64}$'
                  OR pg_catalog.jsonb_typeof(
                    p_manifest#>'{durability,raw_object,object_bytes}')
                    IS DISTINCT FROM 'number'
                  OR (p_manifest#>>'{durability,raw_object,object_bytes}')::bigint <= 0
                  OR p_manifest#>>'{durability,raw_object,object_bytes}'
                    IS DISTINCT FROM p_raw_index#>>'{archive_object,bytes}'
               ))
             OR (
               NOT v_recovery_v2 AND (
                 p_raw_object_key IS DISTINCT FROM
                   'data-torrent/v1/' || p_opportunity_id || '/raw.tar.gz'
                 OR p_normalized_object_key IS DISTINCT FROM
                   'data-torrent/v1/' || p_opportunity_id ||
                   '/normalized-evidence.tar.gz'
                 OR p_manifest#>>'{evidence_validity,mode}' IS DISTINCT FROM
                   'CONDITIONAL_APPEND_ONLY_EXTERNAL_BINDING_V1'
                 OR p_manifest#>>'{durability,verification_status}'
                   IS DISTINCT FROM 'VALID_ONLY_WITH_APPEND_ONLY_BINDING'
               ))
             OR p_manifest#>>'{evidence_validity,unbound_status}'
                IS DISTINCT FROM 'INVALID'
             OR p_manifest#>'{evidence_validity,binding}' IS DISTINCT FROM
                p_normalized_index->'archive_object'
             OR p_manifest#>'{durability,normalized_evidence_binding}'
                IS DISTINCT FROM p_normalized_index->'archive_object'
             OR p_manifest->>'canonical_dataset_sha256' IS DISTINCT FROM
                p_canonical_dataset_sha256
             OR p_manifest->>'data_torrent_ready' IS DISTINCT FROM 'true'
             OR p_manifest->>'edge_promotions' IS DISTINCT FROM
                p_edge_promotions::text
             OR p_manifest->>'bet_calls' IS DISTINCT FROM p_bet_calls::text
             OR p_manifest#>>'{counts,raw_responses}' IS DISTINCT FROM
                p_raw_responses::text
             OR p_manifest#>>'{counts,raw_bytes}' IS DISTINCT FROM
                p_raw_bytes::text
             OR p_manifest#>>'{counts,normalized_records}' IS DISTINCT FROM
                p_normalized_records::text
             OR p_manifest#>>'{counts,rejected_records}' IS DISTINCT FROM
                p_rejected_records::text
             OR p_manifest#>>'{counts,silent_drops}' IS DISTINCT FROM
                p_silent_drops::text
             OR p_manifest#>>'{counts,logical_duplicates}' IS DISTINCT FROM
                p_logical_duplicates::text
             OR p_manifest#>>'{counts,temporal_leakage}' IS DISTINCT FROM
                p_temporal_leakage::text
             OR p_manifest#>>'{effect_summary,unaccounted_external_effects}'
                IS DISTINCT FROM p_unaccounted_external_effects::text
             OR p_manifest#>>'{integrity,raw_response_accounting}'
                IS DISTINCT FROM 'COMPLETE'
             OR p_manifest#>>'{integrity,raw_to_normalized_lineage}'
                IS DISTINCT FROM 'COMPLETE'
             OR p_manifest#>>'{integrity,canonical_replay_equality}'
                IS DISTINCT FROM 'true'
             OR p_manifest#>>'{integrity,idempotent_replay}'
                IS DISTINCT FROM p_idempotent_replay::text
             OR p_manifest#>>'{integrity,temporal_validity}'
                IS DISTINCT FROM 'PASS'
             OR p_raw_index->>'schema_version' IS DISTINCT FROM
                'robin-data-torrent-real-batch-raw-index-v1'
             OR pg_catalog.jsonb_typeof(p_raw_index->'responses')
                IS DISTINCT FROM 'array'
             OR pg_catalog.jsonb_array_length(p_raw_index->'responses') <>
                p_raw_responses
             OR p_raw_index#>>'{totals,raw_responses}' IS DISTINCT FROM
                p_raw_responses::text
             OR p_raw_index#>>'{totals,raw_bytes}' IS DISTINCT FROM
                p_raw_bytes::text
             OR p_raw_index#>>'{totals,official_physical_reads}'
                IS DISTINCT FROM p_official_physical_reads::text
             OR p_raw_index#>>'{totals,odds_provider_requests}'
                IS DISTINCT FROM p_odds_provider_requests::text
             OR p_raw_index#>>'{totals,odds_credits_used}' IS DISTINCT FROM
                p_odds_credits_used::text
             OR p_raw_index#>>'{totals,accounted_responses}' IS DISTINCT FROM
                p_raw_responses::text
             OR p_raw_index#>>'{totals,silent_responses}' IS DISTINCT FROM '0'
             OR p_raw_index#>>'{totals,accounting_status}' IS DISTINCT FROM
                'COMPLETE'
             OR p_normalized_index->>'schema_version' IS DISTINCT FROM
                'robin-data-torrent-normalized-index-v1'
             OR p_normalized_index#>>'{archive_object,role}' IS DISTINCT FROM
                'NORMALIZED_EVIDENCE'
             OR p_normalized_index#>>'{archive_object,object_key}'
                IS DISTINCT FROM p_normalized_object_key
             OR p_normalized_index#>>'{archive_object,archive_format}'
                IS DISTINCT FROM 'DETERMINISTIC_USTAR_GZIP_V1'
             OR (
               NOT v_recovery_v2 AND (
                 p_normalized_index#>>'{archive_object,schema_version}'
                   IS DISTINCT FROM
                   'robin-data-torrent-normalized-evidence-binding-v1'
                 OR p_normalized_index#>>'{archive_object,evidence_member_prefix}'
                   IS DISTINCT FROM 'evidence/'
                 OR p_normalized_index#>>'{archive_object,manifest_self_witness,member}'
                   IS DISTINCT FROM
                   'evidence/torrent-real-batch-manifest-v1.json'
                 OR p_normalized_index#>>'{archive_object,manifest_self_witness,rule}'
                   IS DISTINCT FROM 'PRESENT_WITHOUT_SELF_HASH'
                 OR p_normalized_index#>>'{archive_object,resolver,relation}'
                   IS DISTINCT FROM 'public.chronos_torrent_batch_audit'
                 OR p_normalized_index#>>'{archive_object,resolver,lookup,opportunity_id}'
                   IS DISTINCT FROM p_opportunity_id
                 OR p_normalized_index#>>'{archive_object,resolver,unbound_bundle_validity}'
                   IS DISTINCT FROM 'INVALID'
                 OR p_normalized_index#>>'{archive_object,resolver,required_columns,object_key}'
                   IS DISTINCT FROM 'normalized_object_key'
                 OR p_normalized_index#>>'{archive_object,resolver,required_columns,object_sha256}'
                   IS DISTINCT FROM 'normalized_object_sha256'
                 OR p_normalized_index#>>'{archive_object,resolver,required_columns,operation_id}'
                   IS DISTINCT FROM 'normalized_operation_id'
                 OR p_normalized_index#>>'{archive_object,resolver,required_columns,terminal_event}'
                   IS DISTINCT FROM 'normalized_terminal_event_type'
                 OR p_normalized_index#>>'{archive_object,resolver,required_columns,terminal_event_hash}'
                   IS DISTINCT FROM 'normalized_terminal_event_hash'
                 OR p_normalized_index#>'{archive_object,resolver,required_terminal_events}'
                   IS DISTINCT FROM
                   '["CREATED_CONFIRMED","PREEXISTING_CONFIRMED"]'::jsonb
                 OR (
                   SELECT pg_catalog.array_agg(value ORDER BY value)
                   FROM pg_catalog.jsonb_array_elements_text(
                     p_normalized_index#>'{archive_object,evidence_members}') value
                 ) IS DISTINCT FROM ARRAY[
                   'hypothesis-backlog-from-real-data-v1.md',
                   'hypothesis-ready-field-dictionary-v1.json',
                   'robin-data-torrent-operations-pack-v1.md',
                   'robin-data-torrent-recovery-pack-v1.md',
                   'torrent-canonical-dataset-hash-v1.json',
                   'torrent-control-plane-event-chain-v1.json',
                   'torrent-load-replay-report-v1.json',
                   'torrent-load-replay-report-v1.md',
                   'torrent-official-read-receipts-v1.json',
                   'torrent-opportunity-claim-receipt-v1.json',
                   'torrent-provider-credit-receipt-v1.json',
                   'torrent-qa-acceptance-matrix-v1.json',
                   'torrent-r2-inventory-v1.json',
                   'torrent-raw-to-normalized-lineage-v1.json',
                   'torrent-real-batch-coverage-matrix-v1.csv',
                   'torrent-real-batch-manifest-v1.json',
                   'torrent-real-batch-normalized-index-v1.json',
                   'torrent-real-batch-quality-report-v1.json',
                   'torrent-real-batch-raw-index-v1.json'
                 ]::text[]
                 OR (
                   SELECT pg_catalog.array_agg(value ORDER BY value)
                   FROM pg_catalog.jsonb_array_elements_text(
                     p_normalized_index#>'{archive_object,normalized_core_members}') value
                 ) IS DISTINCT FROM ARRAY[
                   'config/team-alias-registry-v1.json',
                   'data/normalized-records.jsonl',
                   'data/rejected-records.jsonl',
                   'lineage/raw-to-normalized-v1.json',
                   'operations/operations-pack-v1.md',
                   'operations/recovery-pack-v1.md',
                   'reports/coverage-v1.csv',
                   'reports/load-replay-v1.json',
                   'science/field-dictionary-v1.json',
                   'science/hypothesis-backlog-v1.md'
                 ]::text[]
               ))
             OR (
               v_recovery_v2 AND (
                 (
                   SELECT pg_catalog.array_agg(key ORDER BY key)
                   FROM pg_catalog.jsonb_object_keys(
                     p_normalized_index->'archive_object') key
                 ) IS DISTINCT FROM ARRAY[
                   'archive_format','canonical_dataset_sha256','members',
                   'object_bytes','object_key','object_sha256','operation_id',
                   'role','schema_version','terminal_artifacts_location',
                   'terminal_event','terminal_event_hash'
                 ]::text[]
                 OR p_normalized_index#>>'{archive_object,schema_version}'
                   IS DISTINCT FROM
                   'robin-data-torrent-normalized-evidence-binding-v2'
                 OR p_normalized_index#>>'{archive_object,object_sha256}'
                   IS DISTINCT FROM p_normalized_object_sha256
                 OR p_normalized_index#>>'{archive_object,operation_id}'
                   IS DISTINCT FROM p_normalized_operation_id
                 OR p_normalized_index#>>'{archive_object,terminal_event}'
                   IS DISTINCT FROM 'CREATED_CONFIRMED'
                 OR p_normalized_index#>>'{archive_object,terminal_artifacts_location}'
                   IS DISTINCT FROM
                   'GITHUB_RUN_ARTIFACT_AFTER_REPLAY_AND_TERMINAL_QA'
                 OR p_normalized_index#>>'{archive_object,canonical_dataset_sha256}'
                   IS DISTINCT FROM p_canonical_dataset_sha256
                 OR pg_catalog.jsonb_typeof(
                   p_normalized_index#>'{archive_object,object_bytes}')
                   IS DISTINCT FROM 'number'
                 OR (p_normalized_index#>>'{archive_object,object_bytes}')::bigint <= 0
                 OR pg_catalog.jsonb_typeof(
                   p_normalized_index#>'{archive_object,members}')
                   IS DISTINCT FROM 'array'
                 OR pg_catalog.jsonb_array_length(
                   p_normalized_index#>'{archive_object,members}') <> 5
                 OR EXISTS (
                   SELECT 1 FROM pg_catalog.jsonb_array_elements(
                     p_normalized_index#>'{archive_object,members}') member
                   WHERE pg_catalog.jsonb_typeof(member) IS DISTINCT FROM 'object'
                     OR (
                       SELECT pg_catalog.array_agg(key ORDER BY key)
                       FROM pg_catalog.jsonb_object_keys(member) key
                     ) IS DISTINCT FROM ARRAY['bytes','name','sha256']::text[]
                     OR member->>'sha256' !~ '^[0-9a-f]{64}$'
                     OR pg_catalog.jsonb_typeof(member->'bytes')
                       IS DISTINCT FROM 'number'
                     OR (member->>'bytes')::bigint <= 0)
                 OR (
                   SELECT pg_catalog.array_agg(member->>'name' ORDER BY member->>'name')
                   FROM pg_catalog.jsonb_array_elements(
                     p_normalized_index#>'{archive_object,members}') member
                 ) IS DISTINCT FROM ARRAY[
                   'config/team-alias-registry-v1.json',
                   'data/normalized-records.jsonl',
                   'data/rejected-records.jsonl',
                   'lineage/raw-to-normalized-v1.json',
                   'reports/coverage-v1.csv'
                 ]::text[]
                 OR (
                   SELECT member->>'sha256'
                   FROM pg_catalog.jsonb_array_elements(
                     p_normalized_index#>'{archive_object,members}') member
                   WHERE member->>'name'='data/normalized-records.jsonl'
                 ) IS DISTINCT FROM p_canonical_dataset_sha256
                 OR p_normalized_index->'members' IS DISTINCT FROM
                   p_normalized_index#>'{archive_object,members}'
               ))
             OR p_normalized_index->>'canonical_dataset_sha256'
                IS DISTINCT FROM p_canonical_dataset_sha256
             OR (
               NOT v_recovery_v2 AND (
                 pg_catalog.jsonb_typeof(p_normalized_index->'members')
                   IS DISTINCT FROM 'array'
                 OR pg_catalog.jsonb_array_length(p_normalized_index->'members') <> 10
                 OR (
                   SELECT pg_catalog.array_agg(member->>'name' ORDER BY member->>'name')
                   FROM pg_catalog.jsonb_array_elements(
                     p_normalized_index->'members') member
                 ) IS DISTINCT FROM ARRAY[
                   'config/team-alias-registry-v1.json',
                   'data/normalized-records.jsonl',
                   'data/rejected-records.jsonl',
                   'lineage/raw-to-normalized-v1.json',
                   'operations/operations-pack-v1.md',
                   'operations/recovery-pack-v1.md',
                   'reports/coverage-v1.csv',
                   'reports/load-replay-v1.json',
                   'science/field-dictionary-v1.json',
                   'science/hypothesis-backlog-v1.md'
                 ]::text[]
               ))
             OR pg_catalog.jsonb_typeof(
                p_normalized_index->'record_type_counts') IS DISTINCT FROM 'array'
             OR pg_catalog.jsonb_array_length(
                p_normalized_index->'record_type_counts') <= 0
             OR p_normalized_index->'league_market_counts'
                IS DISTINCT FROM p_coverage_matrix
             OR p_normalized_index#>>'{totals,normalized_records}'
                IS DISTINCT FROM p_normalized_records::text
             OR p_normalized_index#>>'{totals,rejected_records}'
                IS DISTINCT FROM p_rejected_records::text
             OR p_normalized_index#>>'{totals,logical_duplicates}'
                IS DISTINCT FROM p_logical_duplicates::text
             OR p_quality_report->>'schema_version' IS DISTINCT FROM
                'robin-data-torrent-quality-report-v1'
             OR p_quality_report->>'quality_status' IS DISTINCT FROM 'PASS'
             OR p_quality_report#>>'{response_accounting,observed}'
                IS DISTINCT FROM p_raw_responses::text
             OR p_quality_report#>>'{response_accounting,accounted}'
                IS DISTINCT FROM p_raw_responses::text
             OR p_quality_report#>>'{response_accounting,silent}'
                IS DISTINCT FROM '0'
             OR p_quality_report->>'logical_duplicates' IS DISTINCT FROM
                p_logical_duplicates::text
              OR p_quality_report#>>'{temporal,leakage_total}' IS DISTINCT FROM
                 p_temporal_leakage::text
              OR (
                v_recovery_v2 AND
                p_quality_report#>>'{temporal,missed_windows}' IS DISTINCT FROM
                  'MISSED_NOT_BACKDATED')
             OR p_quality_report#>>'{coverage,emitted_cells}' IS DISTINCT FROM '10'
             OR p_quality_report#>>'{coverage,incomplete_cells}' IS DISTINCT FROM '0'
             OR p_quality_report#>>'{durability,raw_verified}' IS DISTINCT FROM 'true'
             OR (
               v_recovery_v2 AND
               p_quality_report#>>'{durability,normalized_verified}'
                 IS DISTINCT FROM 'DIRECT_CREATED_CONFIRMED_BEFORE_REPLAY_V2')
             OR (
               NOT v_recovery_v2 AND
               p_quality_report#>>'{durability,normalized_verified}'
                 IS DISTINCT FROM 'CONDITIONAL_APPEND_ONLY_BINDING')
             OR p_quality_report#>'{durability,normalized_evidence_binding}'
                IS DISTINCT FROM p_normalized_index->'archive_object'
             OR p_quality_report#>>'{external_effects,unaccounted}'
                IS DISTINCT FROM p_unaccounted_external_effects::text
             OR pg_catalog.jsonb_typeof(p_quality_report->'gates')
                IS DISTINCT FROM 'array'
             OR pg_catalog.jsonb_array_length(p_quality_report->'gates') <> 6
             OR (
               SELECT pg_catalog.count(DISTINCT gate->>'gate_id')
               FROM pg_catalog.jsonb_array_elements(
                 p_quality_report->'gates') gate
               WHERE gate->>'gate_id' IN (
                 'silent_drops','logical_duplicates','temporal_leakage',
                 'replay_multiplier','throughput_ratio',
                 'unaccounted_external_effects')) <> 6
             OR EXISTS (
               SELECT 1 FROM pg_catalog.jsonb_array_elements(
                 p_quality_report->'gates') gate
               WHERE gate->>'status' IS DISTINCT FROM 'PASS') THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID'; END IF;
          SELECT * INTO c FROM public.chronos_opportunity_claims
          WHERE chronos_opportunity_claims.opportunity_id=p_opportunity_id
          FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_NOT_FOUND'; END IF;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          IF c.mission_id IS DISTINCT FROM p_manifest->>'mission_id'
             OR c.github_run_id IS DISTINCT FROM p_github_run_id
             OR c.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR c.code_revision IS DISTINCT FROM p_code_revision THEN
            RAISE EXCEPTION 'CHRONOS_OPPORTUNITY_WINNER_REQUIRED'; END IF;
          IF c.postgres_server_epoch IS DISTINCT FROM v_epoch THEN
            RAISE EXCEPTION 'CHRONOS_SERVER_EPOCH_MISMATCH'; END IF;
          IF NOT EXISTS (
            SELECT 1 FROM public.chronos_effect_authorities a
            WHERE a.authority_id=c.authority_id
              AND a.github_run_id=p_github_run_id
              AND a.github_run_attempt=p_github_run_attempt
              AND a.code_revision=p_code_revision
              AND a.control_plane_generation_hash=pg_catalog.encode(
                pg_catalog.sha256(p_generation_nonce), 'hex')
              AND a.postgres_server_epoch=v_epoch) THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          SELECT * INTO raw_event FROM public.chronos_effect_events
          WHERE chronos_effect_events.operation_id=p_raw_operation_id
          ORDER BY event_seq DESC LIMIT 1;
          SELECT * INTO normalized_event FROM public.chronos_effect_events
          WHERE chronos_effect_events.operation_id=p_normalized_operation_id
          ORDER BY event_seq DESC LIMIT 1;
          IF raw_event.operation_id IS NULL
             OR normalized_event.operation_id IS NULL
             OR (v_recovery_v2 AND raw_event.event_type IS DISTINCT FROM
                'CREATED_CONFIRMED')
             OR (NOT v_recovery_v2 AND raw_event.event_type NOT IN
                ('CREATED_CONFIRMED','PREEXISTING_CONFIRMED'))
             OR raw_event.resource_key IS DISTINCT FROM p_raw_object_key
             OR raw_event.payload_hash IS DISTINCT FROM p_raw_object_sha256
             OR raw_event.github_run_id IS DISTINCT FROM p_github_run_id
             OR raw_event.github_run_attempt IS DISTINCT FROM
                p_github_run_attempt
             OR raw_event.code_revision IS DISTINCT FROM p_code_revision
             OR raw_event.recorded_server_epoch IS DISTINCT FROM v_epoch
             OR (v_recovery_v2 AND normalized_event.event_type IS DISTINCT FROM
                'CREATED_CONFIRMED')
             OR (NOT v_recovery_v2 AND normalized_event.event_type NOT IN
                ('CREATED_CONFIRMED','PREEXISTING_CONFIRMED'))
             OR normalized_event.resource_key IS DISTINCT FROM p_normalized_object_key
             OR normalized_event.payload_hash IS DISTINCT FROM p_normalized_object_sha256
             OR normalized_event.github_run_id IS DISTINCT FROM p_github_run_id
             OR normalized_event.github_run_attempt IS DISTINCT FROM
                p_github_run_attempt
             OR normalized_event.code_revision IS DISTINCT FROM p_code_revision
             OR normalized_event.recorded_server_epoch IS DISTINCT FROM v_epoch
              OR (v_recovery_v2 AND
                p_normalized_index#>>'{archive_object,terminal_event_hash}'
                  IS DISTINCT FROM normalized_event.event_hash)
              OR (v_recovery_v2 AND
                p_manifest#>>'{durability,raw_object,terminal_event_hash}'
                  IS DISTINCT FROM raw_event.event_hash)
             OR NOT EXISTS (
               SELECT 1 FROM public.chronos_effect_authorities a
               WHERE a.authority_id=raw_event.authority_id
                 AND a.mission_id=c.mission_id || '-raw-r2'
                 AND a.github_run_id=p_github_run_id
                 AND a.github_run_attempt=p_github_run_attempt
                 AND a.code_revision=p_code_revision
                 AND a.postgres_server_epoch=v_epoch
                 AND a.control_plane_generation_hash=pg_catalog.encode(
                   pg_catalog.sha256(p_generation_nonce), 'hex'))
             OR NOT EXISTS (
               SELECT 1 FROM public.chronos_effect_authorities a
               WHERE a.authority_id=normalized_event.authority_id
                 AND a.mission_id=c.mission_id || '-normalized-evidence-r2'
                 AND a.github_run_id=p_github_run_id
                 AND a.github_run_attempt=p_github_run_attempt
                 AND a.code_revision=p_code_revision
                 AND a.postgres_server_epoch=v_epoch
                 AND a.control_plane_generation_hash=pg_catalog.encode(
                   pg_catalog.sha256(p_generation_nonce), 'hex'))
          THEN RAISE EXCEPTION 'CHRONOS_TORRENT_DURABILITY_NOT_PROVEN'; END IF;
          SELECT
            pg_catalog.count(*) FILTER
              (WHERE event_type='PUT_DISPATCHED')::integer,
            pg_catalog.count(*) FILTER
              (WHERE event_type='R2_GET_DISPATCHED')::integer
          INTO v_r2_puts, v_r2_gets
          FROM public.chronos_effect_events
          WHERE operation_id IN
            (p_raw_operation_id, p_normalized_operation_id);
          IF EXISTS (
            SELECT 1
            FROM public.chronos_torrent_external_effect_permits p
            LEFT JOIN LATERAL (
              SELECT event_type
              FROM public.chronos_torrent_external_effect_events e
              WHERE e.operation_id=p.operation_id
              ORDER BY event_seq DESC LIMIT 1) terminal ON true
            WHERE p.opportunity_id=p_opportunity_id
              AND terminal.event_type IS DISTINCT FROM 'CONFIRMED') THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECTS_UNACCOUNTED'; END IF;
          SELECT
            pg_catalog.count(*) FILTER
              (WHERE p.effect_family='OFFICIAL')::integer,
            pg_catalog.count(*) FILTER
              (WHERE p.effect_family='ODDS')::integer,
            COALESCE(pg_catalog.sum(e.actual_official_reads),0)::integer,
            COALESCE(pg_catalog.sum(e.actual_odds_requests),0)::integer,
            COALESCE(pg_catalog.sum(e.actual_odds_credits),0)::integer
          INTO v_official_permits, v_odds_permits, v_official_reads,
            v_odds_requests, v_odds_credits
          FROM public.chronos_torrent_external_effect_permits p
          JOIN LATERAL (
            SELECT actual_official_reads, actual_odds_requests,
              actual_odds_credits
            FROM public.chronos_torrent_external_effect_events e
            WHERE e.operation_id=p.operation_id
            ORDER BY event_seq DESC LIMIT 1) e ON true
          WHERE p.opportunity_id=p_opportunity_id;
          IF v_official_permits <> 5 OR v_odds_permits <> 5
             OR v_official_reads IS DISTINCT FROM p_official_physical_reads
             OR v_odds_requests IS DISTINCT FROM p_odds_provider_requests
             OR v_odds_credits IS DISTINCT FROM p_odds_credits_used
             OR p_raw_responses <> v_official_reads + v_odds_requests THEN
            RAISE EXCEPTION 'CHRONOS_EXTERNAL_EFFECTS_UNACCOUNTED'; END IF;
          IF p_official_physical_reads NOT BETWEEN 5 AND 50
             OR p_odds_provider_requests <> 5
             OR p_odds_credits_used NOT BETWEEN 1 AND 1000
             OR p_raw_responses < 10 OR p_raw_bytes <= 0
             OR p_normalized_records <= 0 OR p_rejected_records < 0
             OR pg_catalog.jsonb_typeof(p_coverage_matrix) <> 'array'
             OR pg_catalog.jsonb_array_length(p_coverage_matrix) <> 10
             OR (
               SELECT pg_catalog.count(DISTINCT
                 (cell->>'sport_key') || pg_catalog.chr(31) ||
                 (cell->>'market'))
               FROM pg_catalog.jsonb_array_elements(p_coverage_matrix) cell
             ) <> 10
             OR EXISTS (
               SELECT 1
               FROM pg_catalog.jsonb_array_elements(p_coverage_matrix) cell
               WHERE pg_catalog.jsonb_typeof(cell) <> 'object'
                 OR NOT cell ?& ARRAY[
                   'league','sport_key','market','fixtures_available',
                   'fixtures_captured','markets_requested','markets_returned',
                   'records_normalized','records_rejected',
                   'coverage_percentage','absence_reason']
                 OR cell->>'sport_key' NOT IN (
                   'soccer_spain_la_liga','soccer_france_ligue_one',
                   'soccer_epl','soccer_italy_serie_a',
                   'soccer_germany_bundesliga')
                 OR cell->>'market' NOT IN ('h2h','totals')
                 OR (cell->>'fixtures_available')::bigint <= 0
                 OR (cell->>'fixtures_captured')::bigint <= 0
                 OR (cell->>'fixtures_captured')::bigint <>
                    (cell->>'fixtures_available')::bigint
                 OR (cell->>'markets_requested')::integer <> 1
                 OR (cell->>'markets_returned')::integer <> 1
                 OR (cell->>'records_normalized')::bigint <= 0
                 OR (cell->>'records_rejected')::bigint < 0
                 OR (cell->>'coverage_percentage')::double precision < 100
                 OR (cell->>'coverage_percentage')::double precision > 100
                 OR cell->>'absence_reason' <> 'NONE'
             )
             OR EXISTS (
               SELECT 1
               FROM pg_catalog.jsonb_array_elements(p_coverage_matrix) cell
               GROUP BY cell->>'sport_key'
               HAVING pg_catalog.sum(
                 (cell->>'records_normalized')::bigint) <= 0
             )
             OR EXISTS (
               SELECT 1
               FROM pg_catalog.jsonb_array_elements(p_coverage_matrix) cell
               GROUP BY cell->>'market'
               HAVING pg_catalog.sum(
                 (cell->>'records_normalized')::bigint) <= 0
             )
             OR p_silent_drops <> 0 OR p_logical_duplicates <> 0
              OR p_temporal_leakage <> 0
              OR (v_recovery_v2 AND p_replay_multiplier <> 100)
              OR (NOT v_recovery_v2 AND p_replay_multiplier < 100)
             OR p_replay_equivalent_records < 0
             OR p_replay_equivalent_records <>
                p_normalized_records * p_replay_multiplier
             OR p_replay_records_per_second <= 0
             OR p_replay_bytes_per_second <= 0
             OR p_replay_p50_latency_ms < 0
             OR p_replay_p95_latency_ms < p_replay_p50_latency_ms
             OR p_replay_peak_memory_bytes < 0
             OR p_normal_required_records_per_second <= 0
             OR p_normal_required_bytes_per_second <= 0
             OR p_throughput_ratio < 5
             OR p_replay_records_per_second <
                5 * p_normal_required_records_per_second
             OR p_replay_bytes_per_second <
                5 * p_normal_required_bytes_per_second
             OR p_replay_records_per_second::text IN
                ('NaN','Infinity','-Infinity')
             OR p_replay_bytes_per_second::text IN
                ('NaN','Infinity','-Infinity')
             OR p_replay_p50_latency_ms::text IN
                ('NaN','Infinity','-Infinity')
             OR p_replay_p95_latency_ms::text IN
                ('NaN','Infinity','-Infinity')
             OR p_normal_required_records_per_second::text IN
                ('NaN','Infinity','-Infinity')
             OR p_normal_required_bytes_per_second::text IN
                ('NaN','Infinity','-Infinity')
             OR p_throughput_ratio::text IN
                ('NaN','Infinity','-Infinity')
              OR p_r2_puts <> 2
              OR p_r2_puts IS DISTINCT FROM v_r2_puts
              OR (
                v_recovery_v2 AND (
                  v_r2_gets <> 0 OR p_r2_gets <> 1 OR p_r2_lists <> 0))
              OR (
                NOT v_recovery_v2 AND (
                  p_r2_gets NOT BETWEEN 0 AND 2
                  OR p_r2_gets <> v_r2_gets
                  OR p_r2_lists NOT BETWEEN 0 AND 2))
              OR p_r2_deletes <> 0
             OR p_r2_objects <> 2 OR p_automatic_retries <> 0
             OR p_unaccounted_external_effects <> 0
             OR p_idempotent_replay IS DISTINCT FROM true
             OR p_qa_acceptance_percent <> 100
             OR p_p0 <> 0 OR p_p1 <> 0 OR p_p2 <> 0
             OR p_open_threads <> 0 OR p_edge_promotions <> 0
             OR p_bet_calls <> 0
             OR p_data_torrent_ready IS DISTINCT FROM true THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_ACCEPTANCE_FAILED'; END IF;
          v_record_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
            'data-torrent-batch-v1', p_opportunity_id, p_raw_operation_id,
            p_raw_object_key, p_raw_object_sha256, p_normalized_operation_id,
            p_normalized_object_key, p_normalized_object_sha256,
            p_canonical_dataset_sha256, p_manifest::text, p_raw_index::text,
            p_normalized_index::text, p_quality_report::text,
            p_coverage_matrix::text, p_official_physical_reads::text,
            p_odds_provider_requests::text, p_odds_credits_used::text,
            p_raw_responses::text, p_raw_bytes::text,
            p_normalized_records::text, p_rejected_records::text,
            p_silent_drops::text, p_logical_duplicates::text,
            p_temporal_leakage::text, p_replay_multiplier::text,
            p_replay_equivalent_records::text,
            p_replay_records_per_second::text,
            p_replay_bytes_per_second::text, p_replay_p50_latency_ms::text,
            p_replay_p95_latency_ms::text, p_replay_peak_memory_bytes::text,
            p_normal_required_records_per_second::text,
            p_normal_required_bytes_per_second::text,
            p_throughput_ratio::text, p_idempotent_replay::text,
            p_r2_puts::text, p_r2_gets::text, p_r2_lists::text,
            p_r2_deletes::text, p_r2_objects::text,
            p_automatic_retries::text, p_unaccounted_external_effects::text,
            p_qa_acceptance_percent::text, p_p0::text, p_p1::text,
            p_p2::text, p_open_threads::text, p_edge_promotions::text,
            p_bet_calls::text, p_data_torrent_ready::text,
            p_github_run_id::text,
            p_github_run_attempt::text, p_code_revision]);
          INSERT INTO public.chronos_torrent_batches (
            opportunity_id, raw_operation_id, raw_object_key, raw_object_sha256,
            normalized_operation_id, normalized_object_key,
            normalized_object_sha256, canonical_dataset_sha256, manifest,
            raw_index, normalized_index, quality_report, coverage_matrix,
            official_physical_reads, odds_provider_requests, odds_credits_used,
            raw_responses, raw_bytes, normalized_records, rejected_records,
            silent_drops, logical_duplicates, temporal_leakage, replay_multiplier,
            replay_equivalent_records, replay_records_per_second,
            replay_bytes_per_second, replay_p50_latency_ms,
            replay_p95_latency_ms, replay_peak_memory_bytes,
            normal_required_records_per_second,
            normal_required_bytes_per_second, throughput_ratio,
            idempotent_replay, r2_puts, r2_gets, r2_lists, r2_deletes,
            r2_objects, automatic_retries, unaccounted_external_effects,
            qa_acceptance_percent, p0, p1, p2, open_threads,
            edge_promotions, bet_calls, data_torrent_ready, github_run_id,
            github_run_attempt, code_revision,
            db_recorded_at, postgres_server_epoch, record_hash)
          VALUES (
            p_opportunity_id, p_raw_operation_id, p_raw_object_key,
            p_raw_object_sha256, p_normalized_operation_id,
            p_normalized_object_key, p_normalized_object_sha256,
            p_canonical_dataset_sha256, p_manifest, p_raw_index,
            p_normalized_index, p_quality_report, p_coverage_matrix,
            p_official_physical_reads, p_odds_provider_requests,
            p_odds_credits_used, p_raw_responses, p_raw_bytes,
            p_normalized_records, p_rejected_records, p_silent_drops,
            p_logical_duplicates, p_temporal_leakage, p_replay_multiplier,
            p_replay_equivalent_records, p_replay_records_per_second,
            p_replay_bytes_per_second, p_replay_p50_latency_ms,
            p_replay_p95_latency_ms, p_replay_peak_memory_bytes,
            p_normal_required_records_per_second,
            p_normal_required_bytes_per_second, p_throughput_ratio,
            p_idempotent_replay, p_r2_puts, p_r2_gets, p_r2_lists,
            p_r2_deletes, p_r2_objects, p_automatic_retries,
            p_unaccounted_external_effects, p_qa_acceptance_percent,
            p_p0, p_p1, p_p2, p_open_threads, p_edge_promotions,
            p_bet_calls, p_data_torrent_ready, p_github_run_id,
            p_github_run_attempt, p_code_revision, v_now, v_epoch, v_record_hash)
          ON CONFLICT ON CONSTRAINT chronos_torrent_batches_pkey
          DO NOTHING RETURNING * INTO b;
          v_inserted := FOUND;
          IF NOT v_inserted THEN
            SELECT * INTO b FROM public.chronos_torrent_batches
            WHERE chronos_torrent_batches.opportunity_id=p_opportunity_id;
            IF b.record_hash IS DISTINCT FROM v_record_hash THEN
              RAISE EXCEPTION 'CHRONOS_TORRENT_BATCH_CONFLICT'; END IF;
          END IF;
          RETURN QUERY SELECT b.opportunity_id::text, v_inserted,
            b.db_recorded_at, b.postgres_server_epoch, b.record_hash::text;
        END;
        $fn$;

        DO $contract$
        DECLARE
          v_signature text :=
            'public.chronos_record_torrent_batch(' ||
            'text,text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,' ||
            'integer,integer,integer,integer,bigint,bigint,bigint,bigint,bigint,' ||
            'bigint,integer,bigint,double precision,double precision,' ||
            'double precision,double precision,bigint,double precision,' ||
            'double precision,double precision,boolean,' ||
            'integer,integer,integer,integer,integer,integer,integer,integer,' ||
            'integer,integer,integer,integer,integer,integer,' ||
            'boolean,bigint,integer,text,bytea)';
          v_function oid;
          v_definition text;
          v_marker text;
        BEGIN
          v_function := pg_catalog.to_regprocedure(v_signature);
          IF v_function IS NULL THEN
            RAISE EXCEPTION 'CHRONOS_TORRENT_SQL_CONTRACT_FUNCTION_MISSING';
          END IF;
          v_definition := pg_catalog.pg_get_functiondef(v_function);
          v_marker := 'DATA_TORRENT_RECOVERY_V2_SQL_CONTRACT_V1:' ||
            pg_catalog.encode(
              pg_catalog.sha256(pg_catalog.convert_to(v_definition, 'UTF8')),
              'hex');
          EXECUTE pg_catalog.format(
            'COMMENT ON FUNCTION %s IS %L', v_signature, v_marker);
        END;
        $contract$;

        CREATE FUNCTION public.chronos_reject_torrent_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $fn$
        BEGIN
          RAISE EXCEPTION 'CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN';
        END;
        $fn$;

        CREATE TRIGGER trg_chronos_opportunity_claims_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_opportunity_claims
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_opportunity_claims_no_truncate
          BEFORE TRUNCATE ON public.chronos_opportunity_claims
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_batches_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_torrent_batches
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_batches_no_truncate
          BEFORE TRUNCATE ON public.chronos_torrent_batches
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_external_effect_permits_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_torrent_external_effect_permits
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_external_effect_permits_no_truncate
          BEFORE TRUNCATE ON public.chronos_torrent_external_effect_permits
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_external_effect_events_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_torrent_external_effect_events
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_torrent_mutation();
        CREATE TRIGGER trg_chronos_torrent_external_effect_events_no_truncate
          BEFORE TRUNCATE ON public.chronos_torrent_external_effect_events
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_torrent_mutation();

        CREATE VIEW public.chronos_opportunity_claim_audit AS
          SELECT opportunity_id, opportunity_kind, canonical_key, mission_id,
            authority_id, github_run_id, github_run_attempt, github_sha,
            github_workflow_ref, github_workflow_sha, github_repository,
            github_ref, code_revision, db_claimed_at, postgres_server_epoch,
            claim_hash
          FROM public.chronos_opportunity_claims;
        CREATE VIEW public.chronos_torrent_batch_audit AS
          SELECT opportunity_id, raw_operation_id, raw_object_key,
            raw_object_sha256, normalized_operation_id, normalized_object_key,
            normalized_object_sha256, canonical_dataset_sha256,
            (SELECT e.event_type
             FROM public.chronos_effect_events e
             WHERE e.operation_id=b.raw_operation_id
             ORDER BY e.event_seq DESC LIMIT 1) AS raw_terminal_event_type,
            (SELECT e.event_hash
             FROM public.chronos_effect_events e
             WHERE e.operation_id=b.raw_operation_id
             ORDER BY e.event_seq DESC LIMIT 1) AS raw_terminal_event_hash,
            (SELECT e.event_type
             FROM public.chronos_effect_events e
             WHERE e.operation_id=b.normalized_operation_id
             ORDER BY e.event_seq DESC LIMIT 1) AS normalized_terminal_event_type,
            (SELECT e.event_hash
             FROM public.chronos_effect_events e
             WHERE e.operation_id=b.normalized_operation_id
             ORDER BY e.event_seq DESC LIMIT 1) AS normalized_terminal_event_hash,
            official_physical_reads, odds_provider_requests, odds_credits_used,
            raw_responses, raw_bytes, normalized_records, rejected_records,
            silent_drops, logical_duplicates, temporal_leakage,
            replay_multiplier, replay_equivalent_records,
            replay_records_per_second, replay_bytes_per_second,
            replay_p50_latency_ms, replay_p95_latency_ms,
            replay_peak_memory_bytes, normal_required_records_per_second,
            normal_required_bytes_per_second, throughput_ratio,
            idempotent_replay, r2_puts, r2_gets, r2_lists, r2_deletes,
            r2_objects, automatic_retries, unaccounted_external_effects,
            qa_acceptance_percent, p0, p1, p2, open_threads,
            edge_promotions, bet_calls, data_torrent_ready, github_run_id,
            github_run_attempt, code_revision, db_recorded_at,
            postgres_server_epoch, record_hash
          FROM public.chronos_torrent_batches b;
        CREATE VIEW public.chronos_torrent_external_effect_audit AS
          SELECT p.operation_id, p.opportunity_id, p.effect_family,
            p.effect_sequence, p.request_hash, p.max_official_reads,
            p.max_odds_requests, p.max_odds_credits, p.github_run_id,
            p.github_run_attempt, p.code_revision, p.db_permitted_at,
            p.postgres_server_epoch, p.permit_hash, e.event_seq,
            e.event_type, e.actual_official_reads, e.actual_odds_requests,
            e.actual_odds_credits, e.db_recorded_at,
            e.postgres_server_epoch AS event_postgres_server_epoch,
            e.previous_event_hash, e.event_hash
          FROM public.chronos_torrent_external_effect_permits p
          LEFT JOIN public.chronos_torrent_external_effect_events e
            ON e.operation_id=p.operation_id;

        REVOKE ALL ON public.chronos_opportunity_claims,
          public.chronos_torrent_external_effect_permits,
          public.chronos_torrent_external_effect_events,
          public.chronos_torrent_batches,
          public.chronos_opportunity_claim_audit,
          public.chronos_torrent_batch_audit,
          public.chronos_torrent_external_effect_audit
          FROM PUBLIC, chronos_reader, chronos_test_writer,
          chronos_runtime_writer, chronos_authority_executor;
        REVOKE EXECUTE ON FUNCTION public.chronos_claim_opportunity(
          text,text,bigint,integer,text,text,text,text,text,bytea,
          text,text,text,text),
          public.chronos_record_torrent_batch(
          text,text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,
          integer,integer,integer,integer,bigint,bigint,bigint,bigint,bigint,
          bigint,integer,bigint,double precision,double precision,
          double precision,double precision,bigint,double precision,
          double precision,double precision,boolean,
          integer,integer,integer,integer,integer,integer,integer,integer,
          integer,integer,integer,integer,integer,integer,
          boolean,bigint,integer,text,bytea),
          public.chronos_reserve_torrent_external_effect(
          text,text,integer,text,integer,integer,integer,bigint,integer,
          text,bytea),
          public.chronos_append_torrent_external_effect(
          text,text,integer,integer,integer,bigint,integer,text,bytea),
          public.chronos_reject_torrent_mutation()
          FROM PUBLIC;
        GRANT SELECT ON public.chronos_opportunity_claim_audit,
          public.chronos_torrent_batch_audit,
          public.chronos_torrent_external_effect_audit TO chronos_reader;
        GRANT EXECUTE ON FUNCTION public.chronos_claim_opportunity(
          text,text,bigint,integer,text,text,text,text,text,bytea,
          text,text,text,text) TO chronos_runtime_writer;
        GRANT EXECUTE ON FUNCTION public.chronos_reserve_torrent_external_effect(
          text,text,integer,text,integer,integer,integer,bigint,integer,
          text,bytea) TO chronos_runtime_writer;
        GRANT EXECUTE ON FUNCTION public.chronos_append_torrent_external_effect(
          text,text,integer,integer,integer,bigint,integer,text,bytea)
          TO chronos_runtime_writer;
        GRANT EXECUTE ON FUNCTION public.chronos_record_torrent_batch(
          text,text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,
          integer,integer,integer,integer,bigint,bigint,bigint,bigint,bigint,
          bigint,integer,bigint,double precision,double precision,
          double precision,double precision,bigint,double precision,
          double precision,double precision,boolean,
          integer,integer,integer,integer,integer,integer,integer,integer,
          integer,integer,integer,integer,integer,integer,
          boolean,bigint,integer,text,bytea) TO chronos_runtime_writer;
        """
    )


def _drop_postgresql_objects() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS public.chronos_torrent_batch_audit;
        DROP VIEW IF EXISTS public.chronos_torrent_external_effect_audit;
        DROP VIEW IF EXISTS public.chronos_opportunity_claim_audit;
        DROP FUNCTION IF EXISTS public.chronos_record_torrent_batch(
          text,text,text,text,text,text,text,text,jsonb,jsonb,jsonb,jsonb,jsonb,
          integer,integer,integer,integer,bigint,bigint,bigint,bigint,bigint,
          bigint,integer,bigint,double precision,double precision,
          double precision,double precision,bigint,double precision,
          double precision,double precision,boolean,
          integer,integer,integer,integer,integer,integer,integer,integer,
          integer,integer,integer,integer,integer,integer,
          boolean,bigint,integer,text,bytea);
        DROP FUNCTION IF EXISTS public.chronos_claim_opportunity(
          text,text,bigint,integer,text,text,text,text,text,bytea,
          text,text,text,text);
        DROP FUNCTION IF EXISTS public.chronos_append_torrent_external_effect(
          text,text,integer,integer,integer,bigint,integer,text,bytea);
        DROP FUNCTION IF EXISTS public.chronos_reserve_torrent_external_effect(
          text,text,integer,text,integer,integer,integer,bigint,integer,
          text,bytea);
        """
    )


def upgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name
    existing = _existing_owned_table_names(connection)
    present = set(TABLES) & existing
    if present:
        raise RuntimeError("CHRONOS_TORRENT_UPGRADE_SCHEMA_DRIFT")
    storage = _storage_metadata(dialect)
    storage.create_all(
        connection,
        tables=_owned_tables(storage, dialect),
        checkfirst=False,
    )
    if dialect == "postgresql":
        _create_postgresql_objects()
    else:
        _create_sqlite_guards()


def downgrade() -> None:
    connection = op.get_bind()
    existing = _existing_owned_table_names(connection)
    present = set(TABLES) & existing
    if present != set(TABLES):
        raise RuntimeError("CHRONOS_TORRENT_DOWNGRADE_SCHEMA_DRIFT")
    if connection.dialect.name == "postgresql":
        targets = ", ".join(f"public.{name}" for name in TABLES)
        connection.execute(sa.text(f"LOCK TABLE {targets} IN ACCESS EXCLUSIVE MODE"))
    for table_name in TABLES:
        qualified = (
            f"public.{table_name}" if connection.dialect.name == "postgresql" else table_name
        )
        # `qualified` is derived exclusively from the module-level TABLES allowlist.
        count = connection.execute(
            sa.text(f"SELECT count(*) FROM {qualified}")  # nosec B608
        ).scalar_one()
        if int(count) != 0:
            raise RuntimeError("CHRONOS_TORRENT_DOWNGRADE_REFUSED_NONEMPTY")
    if connection.dialect.name == "postgresql":
        _drop_postgresql_objects()
    else:
        for table_name in TABLES:
            for operation in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_{operation}")
    storage = _storage_metadata(connection.dialect.name)
    storage.drop_all(
        connection,
        tables=_owned_tables(storage, connection.dialect.name),
        checkfirst=False,
    )
    if connection.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS public.chronos_reject_torrent_mutation()")
