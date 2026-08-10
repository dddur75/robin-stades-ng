"""DB-clocked Chronos authority and append-only effect ledger.

Revision ID: 0014_chronos_control_plane_v2
Revises: 0013_historical_evidence_index
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0014_chronos_control_plane_v2"
down_revision: str | None = "0013_historical_evidence_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

metadata = sa.MetaData()

chronos_effect_authorities = sa.Table(
    "chronos_effect_authorities",
    metadata,
    sa.Column("authority_id", sa.String(length=96), primary_key=True),
    sa.Column("mission_id", sa.String(length=160), nullable=False),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("github_sha", sa.String(length=64), nullable=False),
    sa.Column("github_workflow_ref", sa.String(length=1024), nullable=False),
    sa.Column("github_workflow_sha", sa.String(length=64), nullable=False),
    sa.Column("github_repository", sa.String(length=255), nullable=False),
    sa.Column("github_ref", sa.String(length=1024), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("db_issued_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("postgres_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "control_plane_generation_hash",
        sa.String(length=64),
        nullable=False,
    ),
    sa.Column("authority_hash", sa.String(length=64), nullable=False, unique=True),
    sa.Column("max_r2_put_requests", sa.Integer(), nullable=False),
    sa.UniqueConstraint(
        "authority_id",
        "github_run_id",
        "github_run_attempt",
        "code_revision",
        name="uq_chronos_authority_run_revision",
    ),
    sa.CheckConstraint(
        "github_run_id > 0 AND github_run_attempt > 0",
        name="ck_chronos_authority_run",
    ),
    sa.CheckConstraint(
        "length(github_sha) IN (40, 64) "
        "AND length(github_workflow_sha) IN (40, 64) "
        "AND code_revision = github_sha",
        name="ck_chronos_authority_revisions",
    ),
    sa.CheckConstraint(
        "db_issued_at <= planned_at AND planned_at < expires_at",
        name="ck_chronos_authority_window",
    ),
    sa.CheckConstraint(
        "length(control_plane_generation_hash) = 64 "
        "AND length(authority_hash) = 64",
        name="ck_chronos_authority_hashes",
    ),
    sa.CheckConstraint(
        "max_r2_put_requests = 1",
        name="ck_chronos_authority_effect_limit",
    ),
)

_EVENT_TYPES = (
    "AUTHORITY_GRANTED",
    "EFFECT_RESERVED",
    "PUT_DISPATCHED",
    "R2_GET_DISPATCHED",
    "CREATED_CONFIRMED",
    "PREEXISTING_CONFIRMED",
    "PUT_COMMITTED_ACTUAL_PENDING",
    "FAILED_BEFORE_DISPATCH",
    "FAILED_AFTER_DISPATCH",
    "INTEGRITY_CONFLICT",
    "RECOVERY_OBSERVED_MATCHING_OBJECT",
)

chronos_effect_events = sa.Table(
    "chronos_effect_events",
    metadata,
    sa.Column("event_id", sa.String(length=96), primary_key=True),
    sa.Column("event_seq", sa.BigInteger(), nullable=False),
    sa.Column("operation_id", sa.String(length=64), nullable=False),
    sa.Column("authority_id", sa.String(length=96), nullable=False),
    sa.Column("event_type", sa.String(length=48), nullable=False),
    sa.Column("resource_kind", sa.String(length=64), nullable=False),
    sa.Column("resource_key", sa.String(length=1500), nullable=False),
    sa.Column("payload_hash", sa.String(length=64), nullable=False),
    sa.Column("db_recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("recorded_server_epoch", sa.DateTime(timezone=True), nullable=False),
    sa.Column("github_run_id", sa.BigInteger(), nullable=False),
    sa.Column("github_run_attempt", sa.Integer(), nullable=False),
    sa.Column("code_revision", sa.String(length=64), nullable=False),
    sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
    sa.Column("event_hash", sa.String(length=64), nullable=False, unique=True),
    sa.ForeignKeyConstraint(
        [
            "authority_id",
            "github_run_id",
            "github_run_attempt",
            "code_revision",
        ],
        [
            "chronos_effect_authorities.authority_id",
            "chronos_effect_authorities.github_run_id",
            "chronos_effect_authorities.github_run_attempt",
            "chronos_effect_authorities.code_revision",
        ],
        name="fk_chronos_event_authority_run_revision",
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "operation_id",
        "event_type",
        name="uq_chronos_event_operation_type",
    ),
    sa.UniqueConstraint(
        "operation_id",
        "event_seq",
        name="uq_chronos_event_operation_sequence",
    ),
    sa.UniqueConstraint(
        "authority_id",
        "event_seq",
        name="uq_chronos_event_authority_sequence",
    ),
    sa.UniqueConstraint(
        "previous_event_hash",
        name="uq_chronos_event_previous_hash",
    ),
    sa.CheckConstraint(
        "event_seq >= 0 AND ((event_seq = 0 AND previous_event_hash IS NULL) "
        "OR (event_seq > 0 AND previous_event_hash IS NOT NULL))",
        name="ck_chronos_event_sequence",
    ),
    sa.CheckConstraint(
        "length(operation_id) = 64 AND length(payload_hash) = 64 "
        "AND length(event_hash) = 64 "
        "AND (previous_event_hash IS NULL OR length(previous_event_hash) = 64)",
        name="ck_chronos_event_hashes",
    ),
    sa.CheckConstraint(
        "event_type IN (" + ",".join(f"'{value}'" for value in _EVENT_TYPES) + ")",
        name="ck_chronos_event_type",
    ),
)

TABLES = ("chronos_effect_authorities", "chronos_effect_events")


def _storage_metadata(dialect_name: str) -> sa.MetaData:
    if dialect_name != "postgresql":
        return metadata
    qualified = sa.MetaData()
    for table in metadata.sorted_tables:
        table.to_metadata(qualified, schema="public")
    return qualified


def _create_sqlite_guards() -> None:
    for table_name in TABLES:
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN');
                END;
                """
            )
    op.execute(
        """
        CREATE TRIGGER trg_chronos_effect_events_fsm
        BEFORE INSERT ON chronos_effect_events
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM chronos_effect_authorities a
                WHERE a.authority_id = NEW.authority_id
                  AND a.github_run_id = NEW.github_run_id
                  AND a.github_run_attempt = NEW.github_run_attempt
                  AND a.code_revision = NEW.code_revision
                  AND a.postgres_server_epoch = NEW.recorded_server_epoch
            ) THEN RAISE(ABORT, 'CHRONOS_EVENT_AUTHORITY_MISMATCH') END;

            SELECT CASE WHEN NEW.event_seq = 0 AND NOT (
                NEW.event_type = 'AUTHORITY_GRANTED'
                AND NEW.previous_event_hash IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM chronos_effect_events
                    WHERE authority_id = NEW.authority_id
                )
            ) THEN RAISE(ABORT, 'CHRONOS_EFFECT_TRANSITION_FORBIDDEN') END;

            SELECT CASE WHEN NEW.event_seq > 0 AND NOT EXISTS (
                SELECT 1 FROM chronos_effect_events p
                WHERE p.operation_id = NEW.operation_id
                  AND p.event_seq = NEW.event_seq - 1
                  AND p.event_hash = NEW.previous_event_hash
                  AND p.authority_id = NEW.authority_id
                  AND p.resource_kind = NEW.resource_kind
                  AND p.resource_key = NEW.resource_key
                  AND p.payload_hash = NEW.payload_hash
                  AND (
                    (p.event_type = 'AUTHORITY_GRANTED'
                     AND NEW.event_type = 'EFFECT_RESERVED')
                    OR (p.event_type = 'EFFECT_RESERVED'
                        AND NEW.event_type IN (
                            'FAILED_BEFORE_DISPATCH', 'PUT_DISPATCHED'
                        ))
                    OR (p.event_type = 'PUT_DISPATCHED'
                        AND NEW.event_type IN (
                            'CREATED_CONFIRMED', 'R2_GET_DISPATCHED',
                            'PUT_COMMITTED_ACTUAL_PENDING',
                            'FAILED_AFTER_DISPATCH'
                        ))
                    OR (p.event_type = 'PUT_COMMITTED_ACTUAL_PENDING'
                        AND NEW.event_type = 'R2_GET_DISPATCHED')
                    OR (p.event_type = 'R2_GET_DISPATCHED'
                        AND NEW.event_type IN (
                            'PREEXISTING_CONFIRMED',
                            'PUT_COMMITTED_ACTUAL_PENDING',
                            'RECOVERY_OBSERVED_MATCHING_OBJECT',
                            'INTEGRITY_CONFLICT'
                        ))
                  )
            ) THEN RAISE(ABORT, 'CHRONOS_EFFECT_TRANSITION_FORBIDDEN') END;
        END;
        """
    )


def _assert_postgresql_roles() -> None:
    op.execute(
        """
        DO $roles$
        DECLARE v_role text;
        DECLARE v_unsafe boolean;
        DECLARE v_oid oid;
        DECLARE v_marker constant text :=
          'managed-by:chronos-dual-principal-authority-e1-v2';
        BEGIN
          IF current_setting('statement_timeout')::interval <= interval '0'
             OR current_setting('statement_timeout')::interval > interval '300 seconds'
             OR current_setting('idle_session_timeout')::interval <= interval '0'
             OR current_setting('idle_session_timeout')::interval > interval '60 seconds'
             OR current_setting('idle_in_transaction_session_timeout')::interval
                <= interval '0'
             OR current_setting('idle_in_transaction_session_timeout')::interval
                > interval '60 seconds' THEN
            RAISE EXCEPTION 'CHRONOS_MIGRATOR_TIMEOUTS_UNSAFE';
          END IF;
          FOREACH v_role IN ARRAY ARRAY[
            'chronos_reader', 'chronos_test_writer',
            'chronos_runtime_writer', 'chronos_authority_executor'
          ] LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=v_role) THEN
              RAISE EXCEPTION 'CHRONOS_GROUP_ROLE_MISSING:%', v_role;
            END IF;
            SELECT oid,
                   rolcanlogin OR NOT rolinherit OR rolsuper OR rolcreatedb OR rolcreaterole
                   OR rolreplication OR rolbypassrls OR rolconfig IS NOT NULL
            INTO v_oid, v_unsafe
            FROM pg_catalog.pg_roles WHERE rolname=v_role;
            IF v_unsafe THEN
              RAISE EXCEPTION 'CHRONOS_ROLE_UNSAFE:%', v_role;
            END IF;
            IF pg_catalog.shobj_description(v_oid, 'pg_authid')
               IS DISTINCT FROM v_marker THEN
              RAISE EXCEPTION 'CHRONOS_ROLE_PROVENANCE_UNSAFE:%', v_role;
            END IF;
            IF EXISTS (
              SELECT 1 FROM pg_catalog.pg_db_role_setting WHERE setrole=v_oid
            ) THEN
              RAISE EXCEPTION 'CHRONOS_ROLE_SETTING_UNSAFE:%', v_role;
            END IF;
            IF EXISTS (
              SELECT 1 FROM pg_catalog.pg_database d,
                LATERAL pg_catalog.aclexplode(d.datacl) acl
                WHERE acl.grantee=v_oid
              UNION ALL
              SELECT 1 FROM pg_catalog.pg_namespace n,
                LATERAL pg_catalog.aclexplode(n.nspacl) acl
                WHERE acl.grantee=v_oid
              UNION ALL
              SELECT 1 FROM pg_catalog.pg_class c,
                LATERAL pg_catalog.aclexplode(c.relacl) acl
                WHERE acl.grantee=v_oid
              UNION ALL
              SELECT 1 FROM pg_catalog.pg_proc p,
                LATERAL pg_catalog.aclexplode(p.proacl) acl
                WHERE acl.grantee=v_oid
              UNION ALL
              SELECT 1 FROM pg_catalog.pg_default_acl d,
                LATERAL pg_catalog.aclexplode(d.defaclacl) acl
                WHERE acl.grantee=v_oid
            ) THEN
              RAISE EXCEPTION 'CHRONOS_ROLE_ACL_UNSAFE:%', v_role;
            END IF;
            IF EXISTS (
              SELECT 1 FROM pg_catalog.pg_database WHERE datdba=v_oid
              UNION ALL SELECT 1 FROM pg_catalog.pg_namespace WHERE nspowner=v_oid
              UNION ALL SELECT 1 FROM pg_catalog.pg_class WHERE relowner=v_oid
              UNION ALL SELECT 1 FROM pg_catalog.pg_proc WHERE proowner=v_oid
              UNION ALL SELECT 1 FROM pg_catalog.pg_type WHERE typowner=v_oid
            ) THEN
              RAISE EXCEPTION 'CHRONOS_ROLE_OWNERSHIP_UNSAFE:%', v_role;
            END IF;
          END LOOP;
        END;
        $roles$;
        """
    )


def _create_postgresql_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.chronos_framed_sha256(VARIADIC p_parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT
        SET search_path = pg_catalog AS $fn$
        DECLARE v_part text; v_bytes bytea; v_material bytea := ''::bytea;
        BEGIN
          FOREACH v_part IN ARRAY p_parts LOOP
            v_bytes := pg_catalog.convert_to(v_part, 'UTF8');
            v_material := v_material
              || pg_catalog.convert_to(
                   pg_catalog.octet_length(v_bytes)::text || ':' || v_part,
                   'UTF8');
          END LOOP;
          RETURN pg_catalog.encode(pg_catalog.sha256(v_material), 'hex');
        END;
        $fn$;

        CREATE FUNCTION public.chronos_effect_event_hash(
          p_event_seq bigint, p_operation_id text, p_authority_id text,
          p_event_type text, p_resource_kind text, p_resource_key text,
          p_payload_hash text, p_db_recorded_at timestamptz,
          p_github_run_id bigint, p_github_run_attempt integer,
          p_code_revision text, p_previous_event_hash text)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT
        SET search_path = pg_catalog AS $fn$
          SELECT public.chronos_framed_sha256(VARIADIC ARRAY[
            'chronos-effect-event-v1', p_event_seq::text, p_operation_id,
            p_authority_id, p_event_type, p_resource_kind, p_resource_key,
            p_payload_hash,
            pg_catalog.to_char(p_db_recorded_at AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            p_github_run_id::text, p_github_run_attempt::text,
            p_code_revision, p_previous_event_hash
          ]);
        $fn$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.chronos_issue_effect_authority(
          p_mission_id text, p_github_run_id bigint,
          p_github_run_attempt integer, p_github_sha text,
          p_github_workflow_ref text, p_github_workflow_sha text,
          p_github_repository text, p_github_ref text,
          p_generation_nonce bytea, p_ttl_seconds integer,
          p_code_revision text)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog AS $fn$
        DECLARE
          v_now timestamptz := pg_catalog.clock_timestamp();
          v_epoch timestamptz := pg_catalog.pg_postmaster_start_time();
          v_generation text; v_hash text; v_authority_id text;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_authority_executor', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_AUTHORITY_EXECUTOR_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID';
          END IF;
          IF p_mission_id IS NULL OR p_github_run_id IS NULL
             OR p_github_run_attempt IS NULL OR p_github_sha IS NULL
             OR p_github_workflow_ref IS NULL OR p_github_workflow_sha IS NULL
             OR p_github_repository IS NULL OR p_github_ref IS NULL
             OR p_code_revision IS NULL THEN
            RAISE EXCEPTION 'CHRONOS_GITHUB_RUN_IDENTITY_INVALID';
          END IF;
          IF p_ttl_seconds IS NULL OR p_ttl_seconds < 1
             OR p_ttl_seconds > 1200 THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_TTL_INVALID';
          END IF;
          IF p_code_revision IS DISTINCT FROM p_github_sha THEN
            RAISE EXCEPTION 'CHRONOS_CODE_REVISION_MISMATCH';
          END IF;
          v_generation := pg_catalog.encode(
            pg_catalog.sha256(p_generation_nonce), 'hex');
          v_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
            'chronos-authority-v2', p_mission_id, p_github_run_id::text,
            p_github_run_attempt::text, p_github_sha, p_github_workflow_ref,
            p_github_workflow_sha, p_github_repository, p_github_ref,
            p_code_revision, v_generation,
            pg_catalog.to_char(v_now AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            pg_catalog.to_char(v_epoch AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            p_ttl_seconds::text, '1',
            pg_catalog.pg_backend_pid()::text, pg_catalog.txid_current()::text
          ]);
          v_authority_id := 'chronos-authority:' || v_hash;
          INSERT INTO public.chronos_effect_authorities (
            authority_id, mission_id, github_run_id, github_run_attempt,
            github_sha, github_workflow_ref, github_workflow_sha,
            github_repository, github_ref, code_revision, planned_at,
            expires_at, db_issued_at, postgres_server_epoch,
            control_plane_generation_hash, authority_hash,
            max_r2_put_requests)
          VALUES (
            v_authority_id, p_mission_id, p_github_run_id,
            p_github_run_attempt, p_github_sha, p_github_workflow_ref,
            p_github_workflow_sha, p_github_repository, p_github_ref,
            p_code_revision, v_now,
            v_now + pg_catalog.make_interval(secs => p_ttl_seconds),
            v_now, v_epoch, v_generation, v_hash, 1);
          RETURN v_authority_id;
        END;
        $fn$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.chronos_claim_effect_authority(
          p_authority_id text, p_mission_id text, p_github_run_id bigint,
          p_github_run_attempt integer, p_github_sha text,
          p_github_workflow_ref text, p_github_workflow_sha text,
          p_github_repository text, p_github_ref text,
          p_generation_nonce bytea, p_operation_id text,
          p_resource_kind text, p_resource_key text, p_payload_hash text,
          p_code_revision text)
        RETURNS TABLE(authority_id text, db_authorized_at timestamptz,
          expires_at timestamptz, postgres_server_epoch timestamptz,
          authority_receipt_hash text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          a public.chronos_effect_authorities%ROWTYPE;
          g public.chronos_effect_events%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz;
          v_operation_id text; v_grant_hash text; v_reserve_hash text;
          v_receipt_hash text;
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
             OR p_github_ref IS NULL OR p_operation_id IS NULL
             OR p_resource_kind IS NULL OR p_resource_key IS NULL
             OR p_payload_hash IS NULL OR p_code_revision IS NULL THEN
            RAISE EXCEPTION 'CHRONOS_CLAIM_INPUT_INVALID';
          END IF;
          SELECT * INTO a FROM public.chronos_effect_authorities
          WHERE chronos_effect_authorities.authority_id=p_authority_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_FOUND'; END IF;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          IF a.mission_id IS DISTINCT FROM p_mission_id
             OR a.github_run_id IS DISTINCT FROM p_github_run_id
             OR a.github_run_attempt IS DISTINCT FROM p_github_run_attempt
             OR a.github_sha IS DISTINCT FROM p_github_sha
             OR a.github_workflow_ref IS DISTINCT FROM p_github_workflow_ref
             OR a.github_workflow_sha IS DISTINCT FROM p_github_workflow_sha
             OR a.github_repository IS DISTINCT FROM p_github_repository
             OR a.github_ref IS DISTINCT FROM p_github_ref
             OR a.code_revision IS DISTINCT FROM p_code_revision THEN
            RAISE EXCEPTION 'CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH';
          END IF;
          IF a.postgres_server_epoch IS DISTINCT FROM v_epoch THEN
            RAISE EXCEPTION 'CHRONOS_SERVER_EPOCH_MISMATCH'; END IF;
          IF a.control_plane_generation_hash IS DISTINCT FROM pg_catalog.encode(
              pg_catalog.sha256(p_generation_nonce), 'hex') THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          v_operation_id := public.chronos_framed_sha256(VARIADIC ARRAY[
            p_mission_id, p_github_run_id::text, p_github_run_attempt::text,
            p_resource_kind, p_resource_key, p_payload_hash]);
          IF v_operation_id IS DISTINCT FROM p_operation_id THEN
            RAISE EXCEPTION 'CHRONOS_OPERATION_ID_MISMATCH'; END IF;
          SELECT * INTO g FROM public.chronos_effect_events
          WHERE chronos_effect_events.authority_id=p_authority_id
            AND event_type='AUTHORITY_GRANTED';
          IF FOUND THEN
            IF g.operation_id IS DISTINCT FROM p_operation_id
               OR g.resource_kind IS DISTINCT FROM p_resource_kind
               OR g.resource_key IS DISTINCT FROM p_resource_key
               OR g.payload_hash IS DISTINCT FROM p_payload_hash
            THEN RAISE EXCEPTION 'CHRONOS_AUTHORITY_ALREADY_CONSUMED'; END IF;
            v_receipt_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
              a.authority_id,
              pg_catalog.to_char(g.db_recorded_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
              pg_catalog.to_char(a.expires_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
              pg_catalog.to_char(a.postgres_server_epoch AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
              p_operation_id, a.control_plane_generation_hash,
              a.github_run_id::text, a.github_run_attempt::text,
              a.github_sha, a.github_workflow_ref, a.github_workflow_sha,
              a.github_repository, a.github_ref]);
            RETURN QUERY SELECT a.authority_id::text, g.db_recorded_at, a.expires_at,
              a.postgres_server_epoch, v_receipt_hash;
            RETURN;
          END IF;
          IF NOT a.planned_at <= v_now OR NOT v_now < a.expires_at THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_ACTIVE'; END IF;
          v_grant_hash := public.chronos_effect_event_hash(
            0, p_operation_id, p_authority_id, 'AUTHORITY_GRANTED',
            p_resource_kind, p_resource_key, p_payload_hash, v_now,
            p_github_run_id, p_github_run_attempt, p_code_revision, '');
          INSERT INTO public.chronos_effect_events VALUES (
            'chronos-event:' || v_grant_hash, 0, p_operation_id, p_authority_id,
            'AUTHORITY_GRANTED', p_resource_kind, p_resource_key, p_payload_hash,
            v_now, v_epoch, p_github_run_id, p_github_run_attempt,
            p_code_revision, NULL, v_grant_hash);
          v_reserve_hash := public.chronos_effect_event_hash(
            1, p_operation_id, p_authority_id, 'EFFECT_RESERVED',
            p_resource_kind, p_resource_key, p_payload_hash, v_now,
            p_github_run_id, p_github_run_attempt, p_code_revision, v_grant_hash);
          INSERT INTO public.chronos_effect_events VALUES (
            'chronos-event:' || v_reserve_hash, 1, p_operation_id, p_authority_id,
            'EFFECT_RESERVED', p_resource_kind, p_resource_key, p_payload_hash,
            v_now, v_epoch, p_github_run_id, p_github_run_attempt,
            p_code_revision, v_grant_hash, v_reserve_hash);
          v_receipt_hash := public.chronos_framed_sha256(VARIADIC ARRAY[
            a.authority_id,
            pg_catalog.to_char(v_now AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            pg_catalog.to_char(a.expires_at AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            pg_catalog.to_char(a.postgres_server_epoch AT TIME ZONE 'UTC',
              'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            p_operation_id, a.control_plane_generation_hash,
            a.github_run_id::text, a.github_run_attempt::text,
            a.github_sha, a.github_workflow_ref, a.github_workflow_sha,
            a.github_repository, a.github_ref]);
          RETURN QUERY SELECT a.authority_id::text, v_now, a.expires_at,
            a.postgres_server_epoch, v_receipt_hash;
        END;
        $fn$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.chronos_append_effect_event(
          p_authority_id text, p_operation_id text, p_event_type text,
          p_github_run_id bigint, p_github_run_attempt integer,
          p_github_sha text, p_github_workflow_ref text,
          p_github_workflow_sha text, p_github_repository text,
          p_github_ref text, p_generation_nonce bytea, p_code_revision text)
        RETURNS SETOF public.chronos_effect_events LANGUAGE plpgsql
        SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE
          a public.chronos_effect_authorities%ROWTYPE;
          e public.chronos_effect_events%ROWTYPE;
          previous public.chronos_effect_events%ROWTYPE;
          v_now timestamptz; v_epoch timestamptz; v_hash text;
        BEGIN
          IF NOT pg_catalog.pg_has_role(
            session_user, 'chronos_runtime_writer', 'USAGE')
          THEN RAISE EXCEPTION 'CHRONOS_RUNTIME_WRITER_REQUIRED'; END IF;
          IF p_generation_nonce IS NULL
             OR pg_catalog.octet_length(p_generation_nonce) <> 32 THEN
            RAISE EXCEPTION 'CHRONOS_GENERATION_NONCE_INVALID'; END IF;
          IF p_authority_id IS NULL OR p_operation_id IS NULL
             OR p_event_type IS NULL OR p_github_run_id IS NULL
             OR p_github_run_attempt IS NULL OR p_github_sha IS NULL
             OR p_github_workflow_ref IS NULL OR p_github_workflow_sha IS NULL
             OR p_github_repository IS NULL OR p_github_ref IS NULL
             OR p_code_revision IS NULL THEN
            RAISE EXCEPTION 'CHRONOS_APPEND_INPUT_INVALID';
          END IF;
          SELECT * INTO a FROM public.chronos_effect_authorities
          WHERE chronos_effect_authorities.authority_id=p_authority_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_FOUND'; END IF;
          v_now := pg_catalog.clock_timestamp();
          v_epoch := pg_catalog.pg_postmaster_start_time();
          IF a.github_run_id IS DISTINCT FROM p_github_run_id
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
          IF a.control_plane_generation_hash IS DISTINCT FROM pg_catalog.encode(
              pg_catalog.sha256(p_generation_nonce), 'hex') THEN
            RAISE EXCEPTION 'CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH'; END IF;
          SELECT * INTO e FROM public.chronos_effect_events
          WHERE operation_id=p_operation_id AND event_type=p_event_type;
          IF FOUND THEN
            IF p_event_type='PUT_DISPATCHED' THEN
              RAISE EXCEPTION 'CHRONOS_DISPATCH_PERMIT_ALREADY_EXISTS';
            END IF;
            IF p_event_type='R2_GET_DISPATCHED' THEN
              RAISE EXCEPTION 'CHRONOS_R2_GET_PERMIT_ALREADY_EXISTS';
            END IF;
            RETURN NEXT e;
            RETURN;
          END IF;
          SELECT * INTO previous FROM public.chronos_effect_events
          WHERE operation_id=p_operation_id ORDER BY event_seq DESC LIMIT 1 FOR UPDATE;
          IF NOT FOUND OR previous.authority_id IS DISTINCT FROM p_authority_id THEN
            RAISE EXCEPTION 'CHRONOS_EFFECT_NOT_RESERVED'; END IF;
          IF NOT (
            (previous.event_type='EFFECT_RESERVED' AND
              p_event_type IN ('FAILED_BEFORE_DISPATCH','PUT_DISPATCHED')) OR
            (previous.event_type='PUT_DISPATCHED' AND p_event_type IN (
              'CREATED_CONFIRMED','R2_GET_DISPATCHED',
              'PUT_COMMITTED_ACTUAL_PENDING','FAILED_AFTER_DISPATCH')) OR
            (previous.event_type='PUT_COMMITTED_ACTUAL_PENDING' AND
              p_event_type='R2_GET_DISPATCHED') OR
            (previous.event_type='R2_GET_DISPATCHED' AND
              p_event_type IN ('RECOVERY_OBSERVED_MATCHING_OBJECT',
                               'PREEXISTING_CONFIRMED',
                               'PUT_COMMITTED_ACTUAL_PENDING',
                               'INTEGRITY_CONFLICT'))
          ) THEN RAISE EXCEPTION 'CHRONOS_EFFECT_TRANSITION_FORBIDDEN'; END IF;
          IF p_event_type='PUT_DISPATCHED'
             AND (NOT a.planned_at <= v_now OR NOT v_now < a.expires_at) THEN
            RAISE EXCEPTION 'CHRONOS_AUTHORITY_NOT_ACTIVE'; END IF;
          v_hash := public.chronos_effect_event_hash(
            previous.event_seq + 1, p_operation_id, p_authority_id,
            p_event_type, previous.resource_kind, previous.resource_key,
            previous.payload_hash, v_now, p_github_run_id,
            p_github_run_attempt, p_code_revision, previous.event_hash);
          INSERT INTO public.chronos_effect_events VALUES (
            'chronos-event:' || v_hash, previous.event_seq + 1,
            p_operation_id, p_authority_id, p_event_type,
            previous.resource_kind, previous.resource_key, previous.payload_hash,
            v_now, v_epoch, p_github_run_id, p_github_run_attempt,
            p_code_revision, previous.event_hash, v_hash)
          RETURNING * INTO e;
          RETURN NEXT e;
        END;
        $fn$;

        CREATE FUNCTION public.chronos_get_effect_state(p_operation_id text)
        RETURNS SETOF public.chronos_effect_events LANGUAGE sql STABLE
        SECURITY DEFINER SET search_path = pg_catalog AS $fn$
          SELECT * FROM public.chronos_effect_events
          WHERE operation_id=p_operation_id ORDER BY event_seq DESC LIMIT 1;
        $fn$;
        """
    )


def _create_postgresql_guards_and_grants() -> None:
    op.execute(
        """
        CREATE FUNCTION public.chronos_reject_mutation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $fn$
        BEGIN RAISE EXCEPTION 'CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN'; END;
        $fn$;
        CREATE TRIGGER trg_chronos_authorities_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_effect_authorities
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_mutation();
        CREATE TRIGGER trg_chronos_authorities_no_truncate
          BEFORE TRUNCATE ON public.chronos_effect_authorities
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_mutation();
        CREATE TRIGGER trg_chronos_events_append_only
          BEFORE UPDATE OR DELETE ON public.chronos_effect_events
          FOR EACH ROW EXECUTE FUNCTION public.chronos_reject_mutation();
        CREATE TRIGGER trg_chronos_events_no_truncate
          BEFORE TRUNCATE ON public.chronos_effect_events
          FOR EACH STATEMENT EXECUTE FUNCTION public.chronos_reject_mutation();

        CREATE VIEW public.chronos_effect_accounting AS
        WITH latest AS (
          SELECT DISTINCT ON (operation_id) operation_id, event_type
          FROM public.chronos_effect_events ORDER BY operation_id, event_seq DESC
        )
        SELECT
          count(*) FILTER (WHERE event_type='EFFECT_RESERVED')
            AS r2_write_units_reserved,
          count(*) FILTER (WHERE event_type='PUT_DISPATCHED')
            AS r2_put_requests_dispatched,
          count(*) FILTER (WHERE event_type='R2_GET_DISPATCHED')
            AS r2_get_requests_dispatched,
          count(*) FILTER (WHERE event_type='CREATED_CONFIRMED')
            AS r2_objects_created_confirmed,
          count(*) FILTER (WHERE event_type='PREEXISTING_CONFIRMED')
            AS r2_objects_preexisting_confirmed,
          (SELECT count(*) FROM latest WHERE event_type IN (
            'PUT_DISPATCHED','R2_GET_DISPATCHED',
            'PUT_COMMITTED_ACTUAL_PENDING',
            'RECOVERY_OBSERVED_MATCHING_OBJECT')) AS r2_write_outcomes_pending,
          count(*) FILTER (WHERE event_type='INTEGRITY_CONFLICT')
            AS r2_integrity_conflicts
        FROM public.chronos_effect_events;

        REVOKE ALL ON public.chronos_effect_authorities,
          public.chronos_effect_events FROM PUBLIC, chronos_reader,
          chronos_test_writer, chronos_runtime_writer,
          chronos_authority_executor;
        REVOKE ALL ON public.chronos_effect_accounting FROM PUBLIC,
          chronos_reader, chronos_test_writer, chronos_runtime_writer,
          chronos_authority_executor;
        REVOKE ALL ON public.alembic_version FROM chronos_reader;
        REVOKE EXECUTE ON FUNCTION public.chronos_framed_sha256(text[]),
          public.chronos_effect_event_hash(
            bigint,text,text,text,text,text,text,timestamptz,
            bigint,integer,text,text),
          public.chronos_reject_mutation(),
          public.chronos_issue_effect_authority(
            text,bigint,integer,text,text,text,text,text,bytea,integer,text),
          public.chronos_claim_effect_authority(
            text,text,bigint,integer,text,text,text,text,text,
            bytea,text,text,text,text,text),
          public.chronos_append_effect_event(
            text,text,text,bigint,integer,text,text,text,text,text,bytea,text),
          public.chronos_get_effect_state(text)
          FROM PUBLIC;

        DO $revoke_unexpected$
        DECLARE v record;
        BEGIN
          FOR v IN
            SELECT DISTINCT c.relname, r.rolname
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) acl
            JOIN pg_catalog.pg_roles r ON r.oid=acl.grantee
            WHERE n.nspname='public'
              AND c.relname IN (
                'chronos_effect_authorities', 'chronos_effect_events',
                'chronos_effect_accounting')
              AND acl.grantee <> c.relowner
          LOOP
            EXECUTE pg_catalog.format(
              'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I',
              'public', v.relname, v.rolname);
          END LOOP;
          FOR v IN
            SELECT DISTINCT p.proname,
              pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments,
              r.rolname
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) acl
            JOIN pg_catalog.pg_roles r ON r.oid=acl.grantee
            WHERE n.nspname='public'
              AND p.proname IN (
                'chronos_framed_sha256', 'chronos_effect_event_hash',
                'chronos_reject_mutation', 'chronos_issue_effect_authority',
                'chronos_claim_effect_authority',
                'chronos_append_effect_event', 'chronos_get_effect_state')
              AND acl.grantee <> p.proowner
          LOOP
            EXECUTE pg_catalog.format(
              'REVOKE ALL PRIVILEGES ON FUNCTION %I.%I(%s) FROM %I',
              'public', v.proname, v.arguments, v.rolname);
          END LOOP;
        END;
        $revoke_unexpected$;

        GRANT USAGE ON SCHEMA public TO chronos_reader,
          chronos_runtime_writer, chronos_authority_executor;
        GRANT SELECT ON public.alembic_version TO chronos_reader;
        GRANT SELECT ON public.chronos_effect_accounting TO chronos_reader;
        GRANT EXECUTE ON FUNCTION public.chronos_issue_effect_authority(
          text,bigint,integer,text,text,text,text,text,bytea,integer,text)
          TO chronos_authority_executor;
        GRANT EXECUTE ON FUNCTION public.chronos_claim_effect_authority(
          text,text,bigint,integer,text,text,text,text,text,bytea,text,text,text,text,text)
          TO chronos_runtime_writer;
        GRANT EXECUTE ON FUNCTION public.chronos_append_effect_event(
          text,text,text,bigint,integer,text,text,text,text,text,bytea,text)
          TO chronos_runtime_writer;
        GRANT EXECUTE ON FUNCTION public.chronos_get_effect_state(text)
          TO chronos_reader, chronos_runtime_writer;

        DO $acl$
        DECLARE v_unexpected text;
        BEGIN
          SELECT pg_catalog.string_agg(
            object_name || ':' || grantee || ':' || privilege_type, ',')
          INTO v_unexpected
          FROM (
            SELECT c.relname AS object_name,
              coalesce(r.rolname, 'PUBLIC') AS grantee,
              acl.privilege_type
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
              coalesce(
                c.relacl, pg_catalog.acldefault('r', c.relowner))) acl
            LEFT JOIN pg_catalog.pg_roles r ON r.oid=acl.grantee
            WHERE n.nspname='public'
              AND c.relname IN (
                'chronos_effect_authorities', 'chronos_effect_events',
                'chronos_effect_accounting')
              AND acl.grantee <> c.relowner
              AND NOT (
                c.relname='chronos_effect_accounting'
                AND r.rolname='chronos_reader'
                AND acl.privilege_type='SELECT')
            UNION ALL
            SELECT p.proname,
              coalesce(r.rolname, 'PUBLIC'), acl.privilege_type
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
              coalesce(
                p.proacl, pg_catalog.acldefault('f', p.proowner))) acl
            LEFT JOIN pg_catalog.pg_roles r ON r.oid=acl.grantee
            WHERE n.nspname='public'
              AND p.proname IN (
                'chronos_framed_sha256', 'chronos_effect_event_hash',
                'chronos_reject_mutation', 'chronos_issue_effect_authority',
                'chronos_claim_effect_authority',
                'chronos_append_effect_event', 'chronos_get_effect_state')
              AND acl.grantee <> p.proowner
              AND NOT (
                (p.proname='chronos_issue_effect_authority'
                  AND r.rolname='chronos_authority_executor'
                  AND acl.privilege_type='EXECUTE')
                OR (p.proname IN (
                      'chronos_claim_effect_authority',
                      'chronos_append_effect_event')
                  AND r.rolname='chronos_runtime_writer'
                  AND acl.privilege_type='EXECUTE')
                OR (p.proname='chronos_get_effect_state'
                  AND r.rolname IN ('chronos_reader','chronos_runtime_writer')
                  AND acl.privilege_type='EXECUTE'))
          ) unexpected;
          IF v_unexpected IS NOT NULL THEN
            RAISE EXCEPTION 'CHRONOS_OBJECT_ACL_UNSAFE:%', v_unexpected;
          END IF;
        END;
        $acl$;
        """
    )


def _drop_sqlite_guards() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_chronos_effect_events_fsm")
    for table_name in TABLES:
        for operation in ("update", "delete"):
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only_{operation}"
            )


def _drop_postgresql_objects() -> None:
    op.execute(
        """
        REVOKE ALL ON public.chronos_effect_accounting FROM chronos_reader;
        REVOKE ALL ON public.alembic_version FROM chronos_reader;
        REVOKE USAGE ON SCHEMA public FROM chronos_reader,
          chronos_runtime_writer, chronos_authority_executor;
        REVOKE EXECUTE ON FUNCTION public.chronos_issue_effect_authority(
          text,bigint,integer,text,text,text,text,text,bytea,integer,text)
          FROM chronos_authority_executor;
        REVOKE EXECUTE ON FUNCTION public.chronos_claim_effect_authority(
          text,text,bigint,integer,text,text,text,text,text,bytea,text,text,text,text,text)
          FROM chronos_runtime_writer;
        REVOKE EXECUTE ON FUNCTION public.chronos_append_effect_event(
          text,text,text,bigint,integer,text,text,text,text,text,bytea,text)
          FROM chronos_runtime_writer;
        REVOKE EXECUTE ON FUNCTION public.chronos_get_effect_state(text)
          FROM chronos_reader, chronos_runtime_writer;
        DROP VIEW IF EXISTS public.chronos_effect_accounting;
        DROP FUNCTION IF EXISTS public.chronos_get_effect_state(text);
        DROP FUNCTION IF EXISTS public.chronos_append_effect_event(
          text,text,text,bigint,integer,text,text,text,text,text,bytea,text);
        DROP FUNCTION IF EXISTS public.chronos_claim_effect_authority(
          text,text,bigint,integer,text,text,text,text,text,bytea,text,text,text,text,text);
        DROP FUNCTION IF EXISTS public.chronos_issue_effect_authority(
          text,bigint,integer,text,text,text,text,text,bytea,integer,text);
        DROP TRIGGER IF EXISTS trg_chronos_events_no_truncate
          ON public.chronos_effect_events;
        DROP TRIGGER IF EXISTS trg_chronos_events_append_only
          ON public.chronos_effect_events;
        DROP TRIGGER IF EXISTS trg_chronos_authorities_no_truncate
          ON public.chronos_effect_authorities;
        DROP TRIGGER IF EXISTS trg_chronos_authorities_append_only
          ON public.chronos_effect_authorities;
        DROP FUNCTION IF EXISTS public.chronos_reject_mutation();
        DROP FUNCTION IF EXISTS public.chronos_effect_event_hash(
          bigint,text,text,text,text,text,text,timestamptz,bigint,integer,text,text);
        DROP FUNCTION IF EXISTS public.chronos_framed_sha256(text[]);
        """
    )


def upgrade() -> None:
    bind = op.get_bind()
    schema = "public" if bind.dialect.name == "postgresql" else None
    existing = set(inspect(bind).get_table_names(schema=schema))
    if set(TABLES).intersection(existing):
        raise RuntimeError("CHRONOS_CONTROL_PLANE_UPGRADE_SCHEMA_DRIFT")
    if bind.dialect.name == "postgresql":
        _assert_postgresql_roles()
    storage = _storage_metadata(bind.dialect.name)
    for table in storage.sorted_tables:
        table.create(bind=bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        _create_postgresql_functions()
        _create_postgresql_guards_and_grants()
    elif bind.dialect.name == "sqlite":
        _create_sqlite_guards()


def downgrade() -> None:
    bind = op.get_bind()
    schema = "public" if bind.dialect.name == "postgresql" else None
    existing = set(inspect(bind).get_table_names(schema=schema))
    if not set(TABLES).issubset(existing):
        raise RuntimeError("CHRONOS_CONTROL_PLANE_DOWNGRADE_SCHEMA_DRIFT")
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "LOCK TABLE public.chronos_effect_authorities, "
                "public.chronos_effect_events IN ACCESS EXCLUSIVE MODE"
            )
        )
    storage = _storage_metadata(bind.dialect.name)
    for table in reversed(storage.sorted_tables):
        if bind.execute(sa.select(sa.literal(1)).select_from(table).limit(1)).first():
            raise RuntimeError("CHRONOS_CONTROL_PLANE_DOWNGRADE_REFUSED_NONEMPTY")
    if bind.dialect.name == "postgresql":
        _drop_postgresql_objects()
    elif bind.dialect.name == "sqlite":
        _drop_sqlite_guards()
    for table in reversed(storage.sorted_tables):
        table.drop(bind=bind, checkfirst=False)
