from __future__ import annotations

import copy
import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from robin.chronos_production import ChronosProductionError
from robin.data_torrent.claims import (
    DataTorrentOpportunity,
    PostgresExternalEffectLedger,
    PostgresOpportunityClaimer,
    PostgresTorrentBatchRecorder,
)
from robin.data_torrent.runtime import (
    FINAL_ARTIFACT_NAMES,
    NORMALIZED_CORE_MEMBER_NAMES,
    RECOVERY_V2_DURABLE_NORMALIZED_MEMBER_NAMES,
    _assert_scoped_database_identities,
    _normalized_evidence_binding,
)
from robin.prospective_observatory.chronos_control_plane import (
    ChronosControlPlaneError,
    EffectEvent,
    EffectEventType,
    EffectOperation,
    GitHubRunIdentity,
    PostgresAuthorityIssuer,
    PostgresEffectLedger,
)
from robin.prospective_observatory.chronos_postgres import (
    SQLAlchemyPostgresFunctionClient,
)
from robin.storage.database import build_engine
from scripts import chronos_production_bootstrap_v3 as bootstrap

POSTGRES_URL = os.getenv("ROBIN_TEST_POSTGRES_URL", "")
AUTHORITY_URL = os.getenv("ROBIN_TEST_CHRONOS_AUTHORITY_URL", "")
RUNTIME_URL = os.getenv("ROBIN_TEST_CHRONOS_RUNTIME_URL", "")
READER_URL = os.getenv("ROBIN_TEST_CHRONOS_READER_URL", "")
pytestmark = pytest.mark.skipif(
    not all((POSTGRES_URL, AUTHORITY_URL, RUNTIME_URL, READER_URL)),
    reason="scoped PostgreSQL 16 contract service is not configured",
)

GENERATION_TOKEN = "ab" * 32
CODE_SHA = "1" * 40
LEAGUES = (
    ("soccer_spain_la_liga", "La Liga"),
    ("soccer_france_ligue_one", "Ligue 1"),
    ("soccer_epl", "Premier League"),
    ("soccer_italy_serie_a", "Serie A"),
    ("soccer_germany_bundesliga", "Bundesliga"),
)
EXPECTED_TABLES = {
    "chronos_effect_authorities",
    "chronos_effect_events",
    "chronos_opportunity_claims",
    "chronos_torrent_external_effect_permits",
    "chronos_torrent_external_effect_events",
    "chronos_torrent_batches",
}
EXPECTED_VIEWS = {
    "chronos_effect_accounting",
    "chronos_opportunity_claim_audit",
    "chronos_torrent_batch_audit",
    "chronos_torrent_external_effect_audit",
}
EXPECTED_FUNCTIONS = {
    "chronos_framed_sha256",
    "chronos_effect_event_hash",
    "chronos_reject_mutation",
    "chronos_issue_effect_authority",
    "chronos_claim_effect_authority",
    "chronos_append_effect_event",
    "chronos_get_effect_state",
    "chronos_claim_opportunity",
    "chronos_reserve_torrent_external_effect",
    "chronos_append_torrent_external_effect",
    "chronos_record_torrent_batch",
    "chronos_reject_torrent_mutation",
}
EXPECTED_TRIGGERS = {
    ("chronos_effect_authorities", "trg_chronos_authorities_append_only"),
    ("chronos_effect_authorities", "trg_chronos_authorities_no_truncate"),
    ("chronos_effect_events", "trg_chronos_events_append_only"),
    ("chronos_effect_events", "trg_chronos_events_no_truncate"),
    ("chronos_opportunity_claims", "trg_chronos_opportunity_claims_append_only"),
    ("chronos_opportunity_claims", "trg_chronos_opportunity_claims_no_truncate"),
    ("chronos_torrent_batches", "trg_chronos_torrent_batches_append_only"),
    ("chronos_torrent_batches", "trg_chronos_torrent_batches_no_truncate"),
    (
        "chronos_torrent_external_effect_permits",
        "trg_chronos_torrent_external_effect_permits_append_only",
    ),
    (
        "chronos_torrent_external_effect_permits",
        "trg_chronos_torrent_external_effect_permits_no_truncate",
    ),
    (
        "chronos_torrent_external_effect_events",
        "trg_chronos_torrent_external_effect_events_append_only",
    ),
    (
        "chronos_torrent_external_effect_events",
        "trg_chronos_torrent_external_effect_events_no_truncate",
    ),
}


def _run_id() -> int:
    return int(uuid.uuid4().hex[:12], 16)


def _identity(run_id: int) -> GitHubRunIdentity:
    return GitHubRunIdentity(
        github_run_id=run_id,
        github_run_attempt=1,
        github_sha=CODE_SHA,
        github_workflow_ref=(
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        github_workflow_sha=CODE_SHA,
        github_repository="dddur75/robin-stades-ng",
        github_ref="refs/heads/main",
    )


def _clients() -> tuple[
    Engine,
    Engine,
    SQLAlchemyPostgresFunctionClient,
    SQLAlchemyPostgresFunctionClient,
]:
    authority_engine = build_engine(AUTHORITY_URL)
    runtime_engine = build_engine(RUNTIME_URL)
    return (
        authority_engine,
        runtime_engine,
        SQLAlchemyPostgresFunctionClient(authority_engine),
        SQLAlchemyPostgresFunctionClient(runtime_engine),
    )


def _authority(
    client: SQLAlchemyPostgresFunctionClient,
    *,
    identity: GitHubRunIdentity,
    mission_id: str,
) -> str:
    return PostgresAuthorityIssuer(client).issue_authority(
        mission_id=mission_id,
        identity=identity,
        generation_token=GENERATION_TOKEN,
        ttl_seconds=600,
        code_revision=CODE_SHA,
    )


def _claimed_context(
    mission_id: str = "data-torrent-ready-v1",
) -> tuple[
    Engine,
    Engine,
    SQLAlchemyPostgresFunctionClient,
    SQLAlchemyPostgresFunctionClient,
    GitHubRunIdentity,
    str,
    str,
]:
    authority_engine, runtime_engine, authority_client, runtime_client = _clients()
    identity = _identity(_run_id())
    authority_id = _authority(authority_client, identity=identity, mission_id=mission_id)
    opportunity = DataTorrentOpportunity(
        opportunity_kind="POSTGRESQL_CONTRACT",
        canonical_key=f"contract:{uuid.uuid4().hex}",
    )
    receipt = PostgresOpportunityClaimer(runtime_client).claim(
        authority_id=authority_id,
        mission_id=mission_id,
        identity=identity,
        generation_token=GENERATION_TOKEN,
        opportunity=opportunity,
        code_revision=CODE_SHA,
    )
    assert receipt.acquired_now is True
    return (
        authority_engine,
        runtime_engine,
        authority_client,
        runtime_client,
        identity,
        mission_id,
        opportunity.opportunity_id,
    )


def test_postgresql_0015_inventory_and_scoped_rbac_are_exact() -> None:
    admin = build_engine(POSTGRES_URL)
    reader = build_engine(READER_URL)
    runtime = build_engine(RUNTIME_URL)
    authority = build_engine(AUTHORITY_URL)
    try:
        with admin.connect() as connection:
            assert (
                connection.scalar(sa.text("SELECT version_num FROM public.alembic_version"))
                == "0015_data_torrent_opportunity"
            )
            tables = {
                str(row[0])
                for row in connection.execute(
                    sa.text(
                        "SELECT tablename FROM pg_catalog.pg_tables "
                        "WHERE schemaname='public' AND tablename LIKE 'chronos_%'"
                    )
                )
            }
            views = {
                str(row[0])
                for row in connection.execute(
                    sa.text(
                        "SELECT viewname FROM pg_catalog.pg_views "
                        "WHERE schemaname='public' AND viewname LIKE 'chronos_%'"
                    )
                )
            }
            function_rows = connection.execute(
                sa.text(
                    "SELECT p.proname FROM pg_catalog.pg_proc p "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.proname LIKE 'chronos_%'"
                )
            ).all()
            trigger_rows = connection.execute(
                sa.text(
                    "SELECT c.relname,t.tgname,t.tgenabled,p.proname,"
                    "pg_catalog.pg_get_triggerdef(t.oid) "
                    "FROM pg_catalog.pg_trigger t "
                    "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal "
                    "AND t.tgname LIKE 'trg_chronos_%'"
                )
            ).all()
        assert tables == EXPECTED_TABLES
        assert views == EXPECTED_VIEWS
        assert {str(row[0]) for row in function_rows} == EXPECTED_FUNCTIONS
        assert len(function_rows) == len(EXPECTED_FUNCTIONS)
        assert {(str(row[0]), str(row[1])) for row in trigger_rows} == EXPECTED_TRIGGERS
        assert len(trigger_rows) == len(EXPECTED_TRIGGERS)
        assert all(str(row[2]) == "O" for row in trigger_rows)
        assert all(
            str(row[3])
            in {
                "chronos_reject_mutation",
                "chronos_reject_torrent_mutation",
            }
            and str(row[4]).startswith("CREATE TRIGGER")
            for row in trigger_rows
        )
        with reader.connect() as connection:
            assert (
                connection.scalar(
                    sa.text("SELECT count(*) FROM public.chronos_opportunity_claim_audit")
                )
                is not None
            )
        with pytest.raises(sa.exc.DBAPIError) as denied:
            with reader.begin() as connection:
                connection.execute(sa.text("SELECT * FROM public.chronos_opportunity_claims"))
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        with pytest.raises(sa.exc.DBAPIError) as denied:
            with runtime.begin() as connection:
                connection.execute(sa.text("SELECT * FROM public.chronos_torrent_batches"))
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"
        with authority.connect() as connection:
            allowed = bool(
                connection.scalar(
                    sa.text(
                        "SELECT pg_catalog.has_function_privilege("
                        "current_user,'public.chronos_claim_opportunity(text,text,bigint,"
                        "integer,text,text,text,text,text,bytea,text,text,text,text)','EXECUTE')"
                    )
                )
            )
        assert allowed is False
    finally:
        admin.dispose()
        reader.dispose()
        runtime.dispose()
        authority.dispose()


def test_runtime_scoped_database_identity_preflight_accepts_exact_0015_acl() -> None:
    engines = [build_engine(url) for url in (AUTHORITY_URL, RUNTIME_URL, READER_URL)]
    try:
        _assert_scoped_database_identities(
            targets=[engine.url for engine in engines],
            engines=engines,
        )
    finally:
        for engine in engines:
            engine.dispose()


def test_recovery_v2_verify_rejects_all_direct_column_acl_mutants() -> None:
    admin = build_engine(POSTGRES_URL)
    role = bootstrap.RECOVERY_V2_EXECUTOR_ROLE
    assert role == "chronos_bootstrap_executor_recoveryv2"

    def observe(connection: Connection) -> tuple[list[tuple[Any, ...]], int, int, int]:
        rows = [
            tuple(row)
            for row in connection.execute(
                sa.text(
                    "SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,"
                    "rolreplication,rolbypassrls,rolconnlimit,rolconfig,"
                    "rolvaliduntil=to_timestamp(0),"
                    "pg_catalog.shobj_description(oid,'pg_authid') "
                    "FROM pg_catalog.pg_roles WHERE rolname LIKE :pattern ORDER BY rolname"
                ),
                {"pattern": "chronos_bootstrap_executor_%"},
            )
        ]
        memberships = int(
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "WHERE granted.rolname LIKE :pattern OR member.rolname LIKE :pattern"
                ),
                {"pattern": "chronos_bootstrap_executor_%"},
            )
            or 0
        )
        sessions = int(
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                    "WHERE usename LIKE :pattern"
                ),
                {"pattern": "chronos_bootstrap_executor_%"},
            )
            or 0
        )
        privileges = int(
            connection.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_catalog.pg_attribute a "
                    "JOIN pg_catalog.pg_class c ON c.oid=a.attrelid "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege "
                    "WHERE n.nspname='public' AND "
                    "(c.relname LIKE 'chronos\\_%' ESCAPE '\\' "
                    "OR c.relname='alembic_version') "
                    "AND c.relkind IN ('r','p','v','m','f') "
                    "AND a.attnum>0 AND NOT a.attisdropped "
                    "AND pg_catalog.has_column_privilege(:role,c.oid,a.attnum,privilege)"
                ),
                {"role": role},
            )
            or 0
        )
        return rows, memberships, sessions, privileges

    mutants = (
        "GRANT SELECT (opportunity_id) ON TABLE public.chronos_opportunity_claims "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT INSERT (opportunity_id) ON TABLE public.chronos_opportunity_claims "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT UPDATE (opportunity_id) ON TABLE public.chronos_opportunity_claims "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT REFERENCES (opportunity_id) ON TABLE public.chronos_opportunity_claims "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT SELECT (version_num) ON TABLE public.alembic_version "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT INSERT (version_num) ON TABLE public.alembic_version "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT UPDATE (version_num) ON TABLE public.alembic_version "
        "TO chronos_bootstrap_executor_recoveryv2",
        "GRANT REFERENCES (version_num) ON TABLE public.alembic_version "
        "TO chronos_bootstrap_executor_recoveryv2",
    )
    try:
        with admin.connect() as connection:
            outer = connection.begin()
            try:
                assert (
                    connection.scalar(
                        sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=:role"),
                        {"role": role},
                    )
                    is None
                )
                connection.execute(
                    sa.text(
                        "CREATE ROLE chronos_bootstrap_executor_recoveryv2 "
                        "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 0 "
                        "PASSWORD NULL VALID UNTIL 'epoch'"
                    )
                )
                connection.execute(
                    sa.text(
                        "COMMENT ON ROLE chronos_bootstrap_executor_recoveryv2 IS "
                        "'managed-by:chronos-dual-principal-authority-e1-v2:"
                        "executor-tombstone-recovery-v2'"
                    )
                )
                proof = bootstrap._recovery_v2_executor_terminal_proof()
                rows, memberships, sessions, privileges = observe(connection)
                assert privileges == 0
                bootstrap._assert_recovery_v2_executor_terminal_observation(
                    executor_rows=rows,
                    membership_count=memberships,
                    session_count=sessions,
                    effective_chronos_privilege_count=privileges,
                    migration_proof=proof,
                )
                for grant in mutants:
                    savepoint = connection.begin_nested()
                    try:
                        connection.execute(sa.text(grant))
                        rows, memberships, sessions, privileges = observe(connection)
                        assert privileges == 1
                        with pytest.raises(
                            ChronosProductionError,
                            match="^CHRONOS_VERIFY_ROLE_LIFECYCLE_UNSAFE$",
                        ):
                            bootstrap._assert_recovery_v2_executor_terminal_observation(
                                executor_rows=rows,
                                membership_count=memberships,
                                session_count=sessions,
                                effective_chronos_privilege_count=privileges,
                                migration_proof=proof,
                            )
                    finally:
                        savepoint.rollback()
                    assert observe(connection)[3] == 0
            finally:
                outer.rollback()
            assert (
                connection.scalar(
                    sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=:role"),
                    {"role": role},
                )
                is None
            )
    finally:
        admin.dispose()


def test_cross_run_claim_has_one_winner_and_loser_has_zero_permits() -> None:
    authority_engine, runtime_engine, authority_client, runtime_client = _clients()
    reader_engine = build_engine(READER_URL)
    mission_id = f"data-torrent-race-{uuid.uuid4().hex}"
    opportunity = DataTorrentOpportunity(
        opportunity_kind="POSTGRESQL_RACE",
        canonical_key=f"race:{uuid.uuid4().hex}",
    )
    identities = (_identity(_run_id()), _identity(_run_id()))
    authorities = tuple(
        _authority(authority_client, identity=identity, mission_id=mission_id)
        for identity in identities
    )

    barrier = Barrier(2)

    def compete(index: int, *, synchronize: bool = True) -> object:
        thread_engine = build_engine(RUNTIME_URL)
        try:
            if synchronize:
                barrier.wait(timeout=10)
            return PostgresOpportunityClaimer(
                SQLAlchemyPostgresFunctionClient(thread_engine)
            ).claim(
                authority_id=authorities[index],
                mission_id=mission_id,
                identity=identities[index],
                generation_token=GENERATION_TOKEN,
                opportunity=opportunity,
                code_revision=CODE_SHA,
            )
        finally:
            thread_engine.dispose()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = tuple(executor.submit(compete, index) for index in (0, 1))
            receipts = tuple(future.result(timeout=20) for future in futures)
        assert sum(bool(getattr(item, "acquired_now")) for item in receipts) == 1
        assert len({getattr(item, "claim_receipt_hash") for item in receipts}) == 1
        winner_index = next(
            index for index, item in enumerate(receipts) if bool(getattr(item, "acquired_now"))
        )
        loser_index = 1 - winner_index
        replay = compete(winner_index, synchronize=False)
        assert getattr(replay, "acquired_now") is False
        ledger = PostgresExternalEffectLedger(runtime_client)
        with pytest.raises(ChronosControlPlaneError, match="CHRONOS_OPPORTUNITY_WINNER_REQUIRED"):
            ledger.reserve(
                opportunity_id=opportunity.opportunity_id,
                effect_family="OFFICIAL",
                effect_sequence=1,
                request_hash=hashlib.sha256(b"loser-read").hexdigest(),
                max_official_reads=1,
                max_odds_requests=0,
                max_odds_credits=0,
                identity=identities[loser_index],
                generation_token=GENERATION_TOKEN,
            )
        with reader_engine.connect() as connection:
            claim_row = (
                connection.execute(
                    sa.text(
                        "SELECT authority_id,github_run_id,github_run_attempt "
                        "FROM public.chronos_opportunity_claim_audit "
                        "WHERE opportunity_id=:opportunity_id"
                    ),
                    {"opportunity_id": opportunity.opportunity_id},
                )
                .mappings()
                .one()
            )
            assert claim_row["authority_id"] == authorities[winner_index]
            assert claim_row["github_run_id"] == identities[winner_index].github_run_id
            assert claim_row["github_run_attempt"] == 1
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM public.chronos_torrent_external_effect_audit "
                        "WHERE opportunity_id=:opportunity_id"
                    ),
                    {"opportunity_id": opportunity.opportunity_id},
                )
                == 0
            )
        permit = ledger.reserve(
            opportunity_id=opportunity.opportunity_id,
            effect_family="OFFICIAL",
            effect_sequence=1,
            request_hash=hashlib.sha256(b"winner-preflight").hexdigest(),
            max_official_reads=1,
            max_odds_requests=0,
            max_odds_credits=0,
            identity=identities[winner_index],
            generation_token=GENERATION_TOKEN,
        )
        terminal = ledger.append(
            operation_id=permit.operation_id,
            event_type="FAILED_BEFORE_DISPATCH",
            actual_official_reads=0,
            actual_odds_requests=0,
            actual_odds_credits=0,
            identity=identities[winner_index],
            generation_token=GENERATION_TOKEN,
        )
        assert terminal.event_seq == 1
        with reader_engine.connect() as connection:
            effect_row = (
                connection.execute(
                    sa.text(
                        "SELECT event_type,actual_official_reads,actual_odds_requests,"
                        "actual_odds_credits FROM public.chronos_torrent_external_effect_audit "
                        "WHERE opportunity_id=:opportunity_id"
                    ),
                    {"opportunity_id": opportunity.opportunity_id},
                )
                .mappings()
                .one()
            )
            assert dict(effect_row) == {
                "event_type": "FAILED_BEFORE_DISPATCH",
                "actual_official_reads": 0,
                "actual_odds_requests": 0,
                "actual_odds_credits": 0,
            }
    finally:
        authority_engine.dispose()
        runtime_engine.dispose()
        reader_engine.dispose()


def test_terminal_batch_function_executes_all_53_parameters_on_postgresql() -> None:
    (
        authority_engine,
        runtime_engine,
        authority_client,
        runtime_client,
        identity,
        mission_id,
        opportunity_id,
    ) = _claimed_context()
    ledger = PostgresExternalEffectLedger(runtime_client)
    try:
        for sequence in range(1, 6):
            official = ledger.reserve(
                opportunity_id=opportunity_id,
                effect_family="OFFICIAL",
                effect_sequence=sequence,
                request_hash=hashlib.sha256(f"official:{sequence}".encode()).hexdigest(),
                max_official_reads=1,
                max_odds_requests=0,
                max_odds_credits=0,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
            ledger.append(
                operation_id=official.operation_id,
                event_type="DISPATCHED",
                actual_official_reads=0,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
            ledger.append(
                operation_id=official.operation_id,
                event_type="CONFIRMED",
                actual_official_reads=1,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
            odds = ledger.reserve(
                opportunity_id=opportunity_id,
                effect_family="ODDS",
                effect_sequence=sequence,
                request_hash=hashlib.sha256(f"odds:{sequence}".encode()).hexdigest(),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
            ledger.append(
                operation_id=odds.operation_id,
                event_type="DISPATCHED",
                actual_official_reads=0,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
            ledger.append(
                operation_id=odds.operation_id,
                event_type="CONFIRMED",
                actual_official_reads=0,
                actual_odds_requests=1,
                actual_odds_credits=1,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
        with pytest.raises(
            ChronosControlPlaneError, match="CHRONOS_EXTERNAL_EFFECT_BUDGET_EXCEEDED"
        ):
            ledger.reserve(
                opportunity_id=opportunity_id,
                effect_family="ODDS",
                effect_sequence=6,
                request_hash=hashlib.sha256(b"odds:6").hexdigest(),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=1,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )
        with pytest.raises(
            ChronosControlPlaneError,
            match="CHRONOS_EXTERNAL_EFFECT_PERMIT_CONFLICT",
        ):
            ledger.reserve(
                opportunity_id=opportunity_id,
                effect_family="ODDS",
                effect_sequence=1,
                request_hash=hashlib.sha256(b"odds:1-conflict").hexdigest(),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                identity=identity,
                generation_token=GENERATION_TOKEN,
            )

        base_ledger = PostgresEffectLedger(runtime_client)

        def durable_object(role: str, *, mission_suffix: str) -> EffectOperation:
            payload_hash = hashlib.sha256(role.encode()).hexdigest()
            operation = EffectOperation(
                mission_id=f"{mission_id}-{mission_suffix}",
                identity=identity,
                resource_kind="R2_OBJECT",
                canonical_key=f"data-torrent/v1/{opportunity_id}/{role}.tar.gz",
                canonical_payload_hash=payload_hash,
                code_revision=CODE_SHA,
            )
            authority_id = _authority(
                authority_client,
                identity=identity,
                mission_id=operation.mission_id,
            )
            base_ledger.claim_effect_authority(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
            )
            base_ledger.append_event(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
                event_type=EffectEventType.PUT_DISPATCHED,
            )
            base_ledger.append_event(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
                event_type=EffectEventType.R2_GET_DISPATCHED,
            )
            base_ledger.append_event(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
                event_type=EffectEventType.PREEXISTING_CONFIRMED,
            )
            return operation

        raw_operation = durable_object("raw", mission_suffix="raw-r2")
        normalized_operation = durable_object(
            "normalized-evidence",
            mission_suffix="normalized-evidence-r2",
        )
        coverage = [
            {
                "league": league,
                "sport_key": sport_key,
                "market": market,
                "fixtures_available": 1,
                "fixtures_captured": 1,
                "markets_requested": 1,
                "markets_returned": 1,
                "records_normalized": 1,
                "records_rejected": 0,
                "coverage_percentage": 100.0,
                "absence_reason": "NONE",
            }
            for sport_key, league in LEAGUES
            for market in ("h2h", "totals")
        ]
        recorder = PostgresTorrentBatchRecorder(runtime_client)
        canonical_dataset_sha256 = hashlib.sha256(b"dataset").hexdigest()
        normalized_binding = _normalized_evidence_binding(
            opportunity_id=opportunity_id,
            object_key=normalized_operation.canonical_key,
        )
        manifest = {
            "schema_version": "robin-data-torrent-real-batch-manifest-v1",
            "mission_id": mission_id,
            "status": "SUCCESS",
            "evidence_validity": {
                "mode": "CONDITIONAL_APPEND_ONLY_EXTERNAL_BINDING_V1",
                "binding": normalized_binding,
                "unbound_status": "INVALID",
            },
            "post_merge_ci_proof": {"conclusion": "success"},
            "artifacts": [
                {"name": name, "bytes": 1, "sha256": "a" * 64}
                for name in sorted(FINAL_ARTIFACT_NAMES - {"torrent-real-batch-manifest-v1.json"})
            ],
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "data_torrent_ready": True,
            "edge_promotions": 0,
            "bet_calls": 0,
            "counts": {
                "raw_responses": 10,
                "raw_bytes": 100,
                "normalized_records": 10,
                "rejected_records": 0,
                "silent_drops": 0,
                "logical_duplicates": 0,
                "temporal_leakage": 0,
            },
            "effect_summary": {"unaccounted_external_effects": 0},
            "durability": {
                "normalized_evidence_binding": normalized_binding,
                "verification_status": "VALID_ONLY_WITH_APPEND_ONLY_BINDING",
            },
            "integrity": {
                "raw_response_accounting": "COMPLETE",
                "raw_to_normalized_lineage": "COMPLETE",
                "canonical_replay_equality": True,
                "idempotent_replay": True,
                "temporal_validity": "PASS",
            },
        }
        raw_index = {
            "schema_version": "robin-data-torrent-real-batch-raw-index-v1",
            "mission_id": mission_id,
            "responses": [{"response_id": index} for index in range(10)],
            "totals": {
                "raw_responses": 10,
                "raw_bytes": 100,
                "official_physical_reads": 5,
                "odds_provider_requests": 5,
                "odds_credits_used": 5,
                "accounted_responses": 10,
                "silent_responses": 0,
                "accounting_status": "COMPLETE",
            },
        }
        normalized_index = {
            "schema_version": "robin-data-torrent-normalized-index-v1",
            "mission_id": mission_id,
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "archive_object": normalized_binding,
            "members": [{"name": name} for name in sorted(NORMALIZED_CORE_MEMBER_NAMES)],
            "record_type_counts": [{"record_type": "ODDS_OUTCOME", "records": 10}],
            "league_market_counts": coverage,
            "totals": {
                "normalized_records": 10,
                "rejected_records": 0,
                "logical_duplicates": 0,
            },
        }
        quality_report = {
            "schema_version": "robin-data-torrent-quality-report-v1",
            "mission_id": mission_id,
            "quality_status": "PASS",
            "response_accounting": {"observed": 10, "accounted": 10, "silent": 0},
            "logical_duplicates": 0,
            "temporal": {"leakage_total": 0},
            "coverage": {"emitted_cells": 10, "incomplete_cells": 0},
            "durability": {
                "raw_verified": True,
                "normalized_verified": "CONDITIONAL_APPEND_ONLY_BINDING",
                "normalized_evidence_binding": normalized_binding,
            },
            "external_effects": {"unaccounted": 0},
            "gates": [
                {"gate_id": gate_id, "status": "PASS"}
                for gate_id in (
                    "silent_drops",
                    "logical_duplicates",
                    "temporal_leakage",
                    "replay_multiplier",
                    "throughput_ratio",
                    "unaccounted_external_effects",
                )
            ],
        }
        arguments = {
            "opportunity_id": opportunity_id,
            "raw_operation_id": raw_operation.operation_id,
            "raw_object_key": raw_operation.canonical_key,
            "raw_object_sha256": raw_operation.canonical_payload_hash,
            "normalized_operation_id": normalized_operation.operation_id,
            "normalized_object_key": normalized_operation.canonical_key,
            "normalized_object_sha256": normalized_operation.canonical_payload_hash,
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "manifest": manifest,
            "raw_index": raw_index,
            "normalized_index": normalized_index,
            "quality_report": quality_report,
            "coverage_matrix": coverage,
            "official_physical_reads": 5,
            "odds_provider_requests": 5,
            "odds_credits_used": 5,
            "raw_responses": 10,
            "raw_bytes": 100,
            "normalized_records": 10,
            "rejected_records": 0,
            "silent_drops": 0,
            "logical_duplicates": 0,
            "temporal_leakage": 0,
            "replay_multiplier": 100,
            "replay_equivalent_records": 1000,
            "replay_records_per_second": 50.0,
            "replay_bytes_per_second": 1000.0,
            "replay_p50_latency_ms": 1.0,
            "replay_p95_latency_ms": 2.0,
            "replay_peak_memory_bytes": 1024,
            "normal_required_records_per_second": 10.0,
            "normal_required_bytes_per_second": 200.0,
            "throughput_ratio": 5.0,
            "idempotent_replay": True,
            "r2_puts": 2,
            "r2_gets": 2,
            "r2_lists": 0,
            "r2_deletes": 0,
            "r2_objects": 2,
            "automatic_retries": 0,
            "unaccounted_external_effects": 0,
            "qa_acceptance_percent": 100,
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
            "edge_promotions": 0,
            "bet_calls": 0,
            "data_torrent_ready": True,
            "identity": identity,
            "generation_token": GENERATION_TOKEN,
        }
        record_call = cast(Any, recorder.record)
        created = record_call(**arguments)
        replayed = record_call(**arguments)
        assert created.created_now is True
        assert replayed.created_now is False
        assert replayed.record_hash == created.record_hash
        with pytest.raises(ValueError, match="DATA_TORRENT_REPLAY_THROUGHPUT_INVALID"):
            record_call(**{**arguments, "throughput_ratio": float("nan")})
        with pytest.raises(
            ChronosControlPlaneError,
            match="CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID",
        ):
            record_call(
                **{
                    **arguments,
                    "quality_report": {**quality_report, "quality_status": "FAIL"},
                }
            )
        with pytest.raises(ChronosControlPlaneError, match="CHRONOS_TORRENT_BATCH_CONFLICT"):
            record_call(
                **{
                    **arguments,
                    "quality_report": {**quality_report, "variant": 2},
                }
            )
        admin = build_engine(POSTGRES_URL)
        try:
            mutations = (
                "UPDATE public.chronos_opportunity_claims SET canonical_key=canonical_key "
                "WHERE opportunity_id=:opportunity_id",
                "DELETE FROM public.chronos_opportunity_claims "
                "WHERE opportunity_id=:opportunity_id",
                "UPDATE public.chronos_torrent_batches SET record_hash=record_hash "
                "WHERE opportunity_id=:opportunity_id",
                "DELETE FROM public.chronos_torrent_batches WHERE opportunity_id=:opportunity_id",
                "UPDATE public.chronos_torrent_external_effect_permits "
                "SET request_hash=request_hash WHERE opportunity_id=:opportunity_id",
                "DELETE FROM public.chronos_torrent_external_effect_permits "
                "WHERE opportunity_id=:opportunity_id",
                "UPDATE public.chronos_torrent_external_effect_events SET event_hash=event_hash "
                "WHERE operation_id IN (SELECT operation_id FROM "
                "public.chronos_torrent_external_effect_permits "
                "WHERE opportunity_id=:opportunity_id)",
                "DELETE FROM public.chronos_torrent_external_effect_events "
                "WHERE operation_id IN (SELECT operation_id FROM "
                "public.chronos_torrent_external_effect_permits "
                "WHERE opportunity_id=:opportunity_id)",
            )
            for mutation in mutations:
                with pytest.raises(sa.exc.DBAPIError) as rejected:
                    with admin.begin() as connection:
                        connection.execute(
                            sa.text(mutation),
                            {"opportunity_id": opportunity_id},
                        )
                assert cast(Any, rejected.value.orig).diag.message_primary == (
                    "CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN"
                )
            with pytest.raises(sa.exc.DBAPIError) as rejected:
                with admin.begin() as connection:
                    connection.execute(
                        sa.text(
                            "TRUNCATE public.chronos_torrent_external_effect_events,"
                            "public.chronos_torrent_external_effect_permits,"
                            "public.chronos_torrent_batches,"
                            "public.chronos_opportunity_claims"
                        )
                    )
            assert cast(Any, rejected.value.orig).diag.message_primary == (
                "CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN"
            )
        finally:
            admin.dispose()
    finally:
        authority_engine.dispose()
        runtime_engine.dispose()


def test_recovery_v2_batch_contract_accepts_exact_created_binding_and_rejects_mutants() -> None:
    (
        authority_engine,
        runtime_engine,
        authority_client,
        runtime_client,
        identity,
        mission_id,
        opportunity_id,
    ) = _claimed_context("data-torrent-recovery-v2")
    external_ledger = PostgresExternalEffectLedger(runtime_client)
    try:
        for sequence in range(1, 6):
            for family in ("OFFICIAL", "ODDS"):
                permit = external_ledger.reserve(
                    opportunity_id=opportunity_id,
                    effect_family=family,
                    effect_sequence=sequence,
                    request_hash=hashlib.sha256(f"{family}:{sequence}".encode()).hexdigest(),
                    max_official_reads=1 if family == "OFFICIAL" else 0,
                    max_odds_requests=1 if family == "ODDS" else 0,
                    max_odds_credits=200 if family == "ODDS" else 0,
                    identity=identity,
                    generation_token=GENERATION_TOKEN,
                )
                external_ledger.append(
                    operation_id=permit.operation_id,
                    event_type="DISPATCHED",
                    actual_official_reads=0,
                    actual_odds_requests=0,
                    actual_odds_credits=0,
                    identity=identity,
                    generation_token=GENERATION_TOKEN,
                )
                external_ledger.append(
                    operation_id=permit.operation_id,
                    event_type="CONFIRMED",
                    actual_official_reads=1 if family == "OFFICIAL" else 0,
                    actual_odds_requests=1 if family == "ODDS" else 0,
                    actual_odds_credits=1 if family == "ODDS" else 0,
                    identity=identity,
                    generation_token=GENERATION_TOKEN,
                )

        base_ledger = PostgresEffectLedger(runtime_client)

        def durable_object(
            role: str, filename: str, mission_suffix: str
        ) -> tuple[EffectOperation, EffectEvent]:
            operation = EffectOperation(
                mission_id=f"{mission_id}-{mission_suffix}",
                identity=identity,
                resource_kind="R2_OBJECT",
                canonical_key=(
                    f"data-torrent/recovery-v2/{opportunity_id}/{filename}.tar.gz"
                ),
                canonical_payload_hash=hashlib.sha256(role.encode()).hexdigest(),
                code_revision=CODE_SHA,
            )
            authority_id = _authority(
                authority_client,
                identity=identity,
                mission_id=operation.mission_id,
            )
            base_ledger.claim_effect_authority(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
            )
            base_ledger.append_event(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
                event_type=EffectEventType.PUT_DISPATCHED,
            )
            terminal = base_ledger.append_event(
                authority_id=authority_id,
                operation=operation,
                generation_token=GENERATION_TOKEN,
                event_type=EffectEventType.CREATED_CONFIRMED,
            )
            return operation, terminal

        raw_operation, raw_terminal = durable_object("RAW", "raw", "raw-r2")
        normalized_operation, normalized_terminal = durable_object(
            "NORMALIZED_EVIDENCE",
            "normalized-evidence",
            "normalized-evidence-r2",
        )
        coverage = [
            {
                "league": league,
                "sport_key": sport_key,
                "market": market,
                "fixtures_available": 1,
                "fixtures_captured": 1,
                "markets_requested": 1,
                "markets_returned": 1,
                "records_normalized": 1,
                "records_rejected": 0,
                "coverage_percentage": 100.0,
                "absence_reason": "NONE",
            }
            for sport_key, league in LEAGUES
            for market in ("h2h", "totals")
        ]
        canonical_dataset_sha256 = hashlib.sha256(b"recovery-v2-dataset").hexdigest()
        normalized_members = [
            {
                "name": name,
                "bytes": 1,
                "sha256": (
                    canonical_dataset_sha256
                    if name == "data/normalized-records.jsonl"
                    else hashlib.sha256(name.encode()).hexdigest()
                ),
            }
            for name in sorted(RECOVERY_V2_DURABLE_NORMALIZED_MEMBER_NAMES)
        ]
        normalized_binding = {
            "schema_version": "robin-data-torrent-normalized-evidence-binding-v2",
            "role": "NORMALIZED_EVIDENCE",
            "object_key": normalized_operation.canonical_key,
            "object_bytes": 456,
            "object_sha256": normalized_operation.canonical_payload_hash,
            "operation_id": normalized_operation.operation_id,
            "terminal_event": "CREATED_CONFIRMED",
            "terminal_event_hash": normalized_terminal.event_hash,
            "archive_format": "DETERMINISTIC_USTAR_GZIP_V1",
            "members": normalized_members,
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "terminal_artifacts_location": (
                "GITHUB_RUN_ARTIFACT_AFTER_REPLAY_AND_TERMINAL_QA"
            ),
        }
        manifest = {
            "schema_version": "robin-data-torrent-real-batch-manifest-v1",
            "mission_id": mission_id,
            "status": "SUCCESS",
            "evidence_validity": {
                "mode": "DIRECT_CREATED_DURABLE_BINDING_V2",
                "binding": normalized_binding,
                "unbound_status": "INVALID",
            },
            "post_merge_ci_proof": {"conclusion": "success"},
            "artifacts": [
                {"name": name, "bytes": 1, "sha256": "a" * 64}
                for name in sorted(
                    FINAL_ARTIFACT_NAMES - {"torrent-real-batch-manifest-v1.json"}
                )
            ],
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "data_torrent_ready": True,
            "hypotheses_generated": 0,
            "purchases": 0,
            "missed_windows": "MISSED_NOT_BACKDATED",
            "edge_promotions": 0,
            "bet_calls": 0,
            "counts": {
                "raw_responses": 10,
                "raw_bytes": 100,
                "normalized_records": 10,
                "rejected_records": 0,
                "silent_drops": 0,
                "logical_duplicates": 0,
                "temporal_leakage": 0,
            },
            "effect_summary": {"unaccounted_external_effects": 0},
            "durability": {
                "raw_object": {
                    "role": "RAW",
                    "object_key": raw_operation.canonical_key,
                    "object_bytes": 321,
                    "object_sha256": raw_operation.canonical_payload_hash,
                    "operation_id": raw_operation.operation_id,
                    "terminal_event": "CREATED_CONFIRMED",
                    "terminal_event_hash": raw_terminal.event_hash,
                },
                "normalized_evidence_binding": normalized_binding,
                "verification_status": "CREATED_CONFIRMED_BEFORE_REPLAY",
            },
            "integrity": {
                "raw_response_accounting": "COMPLETE",
                "raw_to_normalized_lineage": "COMPLETE",
                "canonical_replay_equality": True,
                "idempotent_replay": True,
                "temporal_validity": "PASS",
            },
        }
        raw_index = {
            "schema_version": "robin-data-torrent-real-batch-raw-index-v1",
            "mission_id": mission_id,
            "archive_object": {
                "object_key": raw_operation.canonical_key,
                "sha256": raw_operation.canonical_payload_hash,
                "media_type": "application/gzip",
                "format": "DETERMINISTIC_USTAR_GZIP_V1",
                "bytes": 321,
            },
            "responses": [{"response_id": index} for index in range(10)],
            "totals": {
                "raw_responses": 10,
                "raw_bytes": 100,
                "official_physical_reads": 5,
                "odds_provider_requests": 5,
                "odds_credits_used": 5,
                "accounted_responses": 10,
                "silent_responses": 0,
                "accounting_status": "COMPLETE",
            },
        }
        normalized_index = {
            "schema_version": "robin-data-torrent-normalized-index-v1",
            "mission_id": mission_id,
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "archive_object": normalized_binding,
            "members": normalized_members,
            "record_type_counts": [{"record_type": "ODDS_OUTCOME", "records": 10}],
            "league_market_counts": coverage,
            "totals": {
                "normalized_records": 10,
                "rejected_records": 0,
                "logical_duplicates": 0,
            },
        }
        quality_report = {
            "schema_version": "robin-data-torrent-quality-report-v1",
            "mission_id": mission_id,
            "quality_status": "PASS",
            "response_accounting": {"observed": 10, "accounted": 10, "silent": 0},
            "logical_duplicates": 0,
            "temporal": {
                "leakage_total": 0,
                "missed_windows": "MISSED_NOT_BACKDATED",
            },
            "coverage": {"emitted_cells": 10, "incomplete_cells": 0},
            "durability": {
                "raw_verified": True,
                "normalized_verified": "DIRECT_CREATED_CONFIRMED_BEFORE_REPLAY_V2",
                "normalized_evidence_binding": normalized_binding,
            },
            "external_effects": {"unaccounted": 0},
            "gates": [
                {"gate_id": gate_id, "status": "PASS"}
                for gate_id in (
                    "silent_drops",
                    "logical_duplicates",
                    "temporal_leakage",
                    "replay_multiplier",
                    "throughput_ratio",
                    "unaccounted_external_effects",
                )
            ],
        }
        arguments: dict[str, Any] = {
            "opportunity_id": opportunity_id,
            "raw_operation_id": raw_operation.operation_id,
            "raw_object_key": raw_operation.canonical_key,
            "raw_object_sha256": raw_operation.canonical_payload_hash,
            "normalized_operation_id": normalized_operation.operation_id,
            "normalized_object_key": normalized_operation.canonical_key,
            "normalized_object_sha256": normalized_operation.canonical_payload_hash,
            "canonical_dataset_sha256": canonical_dataset_sha256,
            "manifest": manifest,
            "raw_index": raw_index,
            "normalized_index": normalized_index,
            "quality_report": quality_report,
            "coverage_matrix": coverage,
            "official_physical_reads": 5,
            "odds_provider_requests": 5,
            "odds_credits_used": 5,
            "raw_responses": 10,
            "raw_bytes": 100,
            "normalized_records": 10,
            "rejected_records": 0,
            "silent_drops": 0,
            "logical_duplicates": 0,
            "temporal_leakage": 0,
            "replay_multiplier": 100,
            "replay_equivalent_records": 1000,
            "replay_records_per_second": 50.0,
            "replay_bytes_per_second": 1000.0,
            "replay_p50_latency_ms": 1.0,
            "replay_p95_latency_ms": 2.0,
            "replay_peak_memory_bytes": 1024,
            "normal_required_records_per_second": 10.0,
            "normal_required_bytes_per_second": 200.0,
            "throughput_ratio": 5.0,
            "idempotent_replay": True,
            "r2_puts": 2,
            "r2_gets": 1,
            "r2_lists": 0,
            "r2_deletes": 0,
            "r2_objects": 2,
            "automatic_retries": 0,
            "unaccounted_external_effects": 0,
            "qa_acceptance_percent": 100,
            "p0": 0,
            "p1": 0,
            "p2": 0,
            "open_threads": 0,
            "edge_promotions": 0,
            "bet_calls": 0,
            "data_torrent_ready": True,
            "identity": identity,
            "generation_token": GENERATION_TOKEN,
        }
        record_call = cast(Any, PostgresTorrentBatchRecorder(runtime_client).record)
        created = record_call(**arguments)
        replayed = record_call(**arguments)
        assert created.created_now is True
        assert replayed.created_now is False
        assert replayed.record_hash == created.record_hash

        mutants: list[tuple[dict[str, Any], str]] = [
            ({**arguments, "replay_multiplier": 101}, "CHRONOS_TORRENT_ACCEPTANCE_FAILED"),
            ({**arguments, "r2_lists": 1}, "CHRONOS_TORRENT_ACCEPTANCE_FAILED"),
            ({**arguments, "r2_gets": 0}, "CHRONOS_TORRENT_ACCEPTANCE_FAILED"),
            ({**arguments, "r2_gets": 2}, "CHRONOS_TORRENT_ACCEPTANCE_FAILED"),
            (
                {**arguments, "raw_object_key": raw_operation.canonical_key + "-prefix-drift"},
                "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID",
            ),
        ]
        mission_drift = copy.deepcopy(arguments)
        mission_drift["quality_report"]["mission_id"] = "data-torrent-ready-v1"
        mutants.append((mission_drift, "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID"))
        preexisting = copy.deepcopy(arguments)
        preexisting["manifest"]["durability"]["raw_object"]["terminal_event"] = (
            "PREEXISTING_CONFIRMED"
        )
        mutants.append((preexisting, "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID"))
        raw_bytes_drift = copy.deepcopy(arguments)
        raw_bytes_drift["manifest"]["durability"]["raw_object"]["object_bytes"] = 322
        mutants.append((raw_bytes_drift, "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID"))
        binding_drift = copy.deepcopy(arguments)
        for binding in (
            binding_drift["manifest"]["evidence_validity"]["binding"],
            binding_drift["manifest"]["durability"]["normalized_evidence_binding"],
            binding_drift["normalized_index"]["archive_object"],
            binding_drift["quality_report"]["durability"]["normalized_evidence_binding"],
        ):
            binding["terminal_event_hash"] = "f" * 64
        mutants.append((binding_drift, "CHRONOS_TORRENT_DURABILITY_NOT_PROVEN"))
        member_drift = copy.deepcopy(arguments)
        for member in member_drift["normalized_index"]["archive_object"]["members"]:
            if member["name"] == "data/normalized-records.jsonl":
                member["sha256"] = "f" * 64
        mutants.append((member_drift, "CHRONOS_TORRENT_ARTIFACT_CONTRACT_INVALID"))

        for mutant, expected_error in mutants:
            with pytest.raises(sa.exc.DBAPIError) as rejected:
                record_call(**mutant)
            assert cast(Any, rejected.value.orig).diag.message_primary == expected_error
        conflict = copy.deepcopy(arguments)
        conflict["quality_report"]["variant"] = "post-insert-conflict"
        with pytest.raises(sa.exc.DBAPIError) as rejected:
            record_call(**conflict)
        assert cast(Any, rejected.value.orig).diag.message_primary == (
            "CHRONOS_TORRENT_BATCH_CONFLICT"
        )
    finally:
        authority_engine.dispose()
        runtime_engine.dispose()
