from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import DBAPIError

from robin.prospective_observatory.chronos_control_plane import (
    EffectEventType,
    derive_event_hash,
    derive_operation_id,
)
from robin.storage.database import build_engine

POSTGRES_URL = os.getenv("ROBIN_TEST_POSTGRES_URL", "")
MIGRATOR_ROLE = os.getenv("ROBIN_TEST_CHRONOS_MIGRATOR_ROLE", "")
MIGRATOR_URL = os.getenv("ROBIN_TEST_CHRONOS_MIGRATOR_URL", "")
BOOTSTRAP_AUTHORITY_ROLE = os.getenv("ROBIN_TEST_CHRONOS_BOOTSTRAP_AUTHORITY_ROLE", "")
LIFECYCLE_ADMIN_ROLE = os.getenv("ROBIN_TEST_CHRONOS_LIFECYCLE_ADMIN_ROLE", "")
SCOPED_LOGIN_URLS = {
    "chronos_authority_runtime_login": os.getenv(
        "ROBIN_TEST_CHRONOS_AUTHORITY_URL", ""
    ),
    "chronos_effect_runtime_login": os.getenv("ROBIN_TEST_CHRONOS_RUNTIME_URL", ""),
    "chronos_reader_login": os.getenv("ROBIN_TEST_CHRONOS_READER_URL", ""),
}
SCOPED_LOGIN_GROUPS = {
    "chronos_authority_runtime_login": "chronos_authority_executor",
    "chronos_effect_runtime_login": "chronos_runtime_writer",
    "chronos_reader_login": "chronos_reader",
}
SCOPED_LOGINS_CONFIGURED = all(SCOPED_LOGIN_URLS.values())
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="local PostgreSQL contract service is not configured",
)

GENERATION = bytes.fromhex("ab" * 32)
SHA = "1" * 40
WORKFLOW_SHA = "2" * 40
MISSION = "chronos-postgresql-contract"
RUN_ID = 8675309
RUN_ATTEMPT = 1
RESOURCE_KIND = "R2_OBJECT"
RESOURCE_KEY = "chronos/contract/payload.json"
PAYLOAD_HASH = hashlib.sha256(b"payload").hexdigest()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    value = build_engine(POSTGRES_URL)
    yield value
    value.dispose()


def issue(
    connection: Connection,
    *,
    ttl_seconds: int = 60,
    generation: bytes | None = GENERATION,
) -> str:
    return str(
        connection.execute(
            sa.text(
                "SELECT public.chronos_issue_effect_authority("
                ":mission,:run_id,:attempt,:sha,:workflow_ref,:workflow_sha,"
                ":repository,:ref,:generation,:ttl,:code_revision) AS authority_id"
            ),
            {
                "mission": MISSION,
                "run_id": RUN_ID,
                "attempt": RUN_ATTEMPT,
                "sha": SHA,
                "workflow_ref": "org/repo/.github/workflows/chronos.yml@refs/heads/main",
                "workflow_sha": WORKFLOW_SHA,
                "repository": "org/repo",
                "ref": "refs/heads/main",
                "generation": generation,
                "ttl": ttl_seconds,
                "code_revision": SHA,
            },
        ).mappings().one()["authority_id"]
    )


def claim(
    connection: Connection,
    authority_id: str,
    *,
    generation: bytes | None = GENERATION,
    run_id: int | None = RUN_ID,
    resource_key: str = RESOURCE_KEY,
) -> sa.RowMapping:
    operation_id = derive_operation_id(
        mission_id=MISSION,
        github_run_id=RUN_ID,
        github_run_attempt=RUN_ATTEMPT,
        resource_kind=RESOURCE_KIND,
        canonical_key=resource_key,
        canonical_payload_hash=PAYLOAD_HASH,
    )
    return connection.execute(
        sa.text(
            "SELECT * FROM public.chronos_claim_effect_authority("
            ":authority_id,:mission,:run_id,:attempt,:sha,:workflow_ref,"
            ":workflow_sha,:repository,:ref,:generation,:operation_id,"
            ":resource_kind,:resource_key,:payload_hash,:code_revision)"
        ),
        {
            "authority_id": authority_id,
            "mission": MISSION,
            "run_id": run_id,
            "attempt": RUN_ATTEMPT,
            "sha": SHA,
            "workflow_ref": "org/repo/.github/workflows/chronos.yml@refs/heads/main",
            "workflow_sha": WORKFLOW_SHA,
            "repository": "org/repo",
            "ref": "refs/heads/main",
            "generation": generation,
            "operation_id": operation_id,
            "resource_kind": RESOURCE_KIND,
            "resource_key": resource_key,
            "payload_hash": PAYLOAD_HASH,
            "code_revision": SHA,
        },
    ).mappings().one()


def append(
    connection: Connection,
    authority_id: str,
    operation_id: str,
    event_type: str,
    *,
    generation: bytes | None = GENERATION,
) -> sa.RowMapping:
    return connection.execute(
        sa.text(
            "SELECT * FROM public.chronos_append_effect_event("
            ":authority_id,:operation_id,:event_type,:run_id,:attempt,:sha,"
            ":workflow_ref,:workflow_sha,:repository,:ref,:generation,"
            ":code_revision)"
        ),
        {
            "authority_id": authority_id,
            "operation_id": operation_id,
            "event_type": event_type,
            "run_id": RUN_ID,
            "attempt": RUN_ATTEMPT,
            "sha": SHA,
            "workflow_ref": "org/repo/.github/workflows/chronos.yml@refs/heads/main",
            "workflow_sha": WORKFLOW_SHA,
            "repository": "org/repo",
            "ref": "refs/heads/main",
            "generation": generation,
            "code_revision": SHA,
        },
    ).mappings().one()


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def framed_hash(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = str(part).encode()
        digest.update(str(len(encoded)).encode() + b":" + encoded)
    return digest.hexdigest()


def test_non_superuser_createrole_receives_unrevokable_admin_edge(
    engine: Engine,
) -> None:
    creator = "rds_ci_createrole_root_cause"
    created_login = "rds_ci_created_login_root_cause"
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                f"CREATE ROLE {creator} LOGIN NOINHERIT NOSUPERUSER "
                "NOCREATEDB CREATEROLE NOREPLICATION NOBYPASSRLS "
                "PASSWORD 'root_cause_only'"
            )
        )
    creator_url = make_url(POSTGRES_URL).set(
        username=creator,
        password="root_cause_only",
    )
    creator_engine = sa.create_engine(creator_url)
    try:
        with creator_engine.begin() as connection:
            connection.execute(sa.text("SET LOCAL createrole_self_grant = ''"))
            assert connection.scalar(
                sa.text("SELECT current_setting('createrole_self_grant')")
            ) == ""
            connection.execute(
                sa.text(
                    f"CREATE ROLE {created_login} LOGIN NOINHERIT NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS "
                    "PASSWORD 'created_login_only'"
                )
            )

        def automatic_edge() -> sa.RowMapping:
            with engine.connect() as connection:
                return connection.execute(
                    sa.text(
                        "SELECT grantor.rolsuper AS grantor_superuser,"
                        "m.admin_option,m.inherit_option,m.set_option "
                        "FROM pg_catalog.pg_auth_members m "
                        "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                        "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                        "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
                        "WHERE granted.rolname=:granted AND member.rolname=:member"
                    ),
                    {"granted": created_login, "member": creator},
                ).mappings().one()

        assert dict(automatic_edge()) == {
            "grantor_superuser": True,
            "admin_option": True,
            "inherit_option": False,
            "set_option": False,
        }
        try:
            with creator_engine.begin() as connection:
                connection.execute(
                    sa.text(f"REVOKE {created_login} FROM CURRENT_USER")
                )
        except DBAPIError:
            pass
        assert dict(automatic_edge()) == {
            "grantor_superuser": True,
            "admin_option": True,
            "inherit_option": False,
            "set_option": False,
        }
    finally:
        creator_engine.dispose()
        with engine.begin() as connection:
            connection.execute(sa.text(f"DROP ROLE {created_login}"))
            connection.execute(sa.text(f"DROP ROLE {creator}"))


@pytest.mark.skipif(
    not MIGRATOR_URL or not MIGRATOR_ROLE,
    reason="the active PostgreSQL 16 migrator fixture is not configured",
)
def test_nocreaterole_migrator_cannot_mutate_role_lifecycle() -> None:
    migrator_engine = sa.create_engine(MIGRATOR_URL)
    try:
        with migrator_engine.connect() as connection:
            assert connection.scalar(
                sa.text(
                    "SELECT rolcreaterole FROM pg_catalog.pg_roles "
                    "WHERE rolname=current_user"
                )
            ) is False
            assert connection.scalar(
                sa.text(
                    "SELECT current_setting('statement_timeout')::interval "
                    "= interval '1 second'"
                )
            )
            assert connection.scalar(
                sa.text(
                    "SELECT current_setting('idle_session_timeout')::interval "
                    "= interval '60 seconds'"
                )
            )
            assert connection.scalar(
                sa.text(
                    "SELECT current_setting('idle_in_transaction_session_timeout')"
                    "::interval = interval '60 seconds'"
                )
            )
            with pytest.raises(DBAPIError) as cancelled:
                connection.execute(sa.text("SELECT pg_sleep(2)"))
            assert getattr(cancelled.value.orig, "sqlstate", None) == "57014"
        forbidden = (
            "CREATE ROLE rds_forbidden_migrator_alias NOLOGIN",
            "ALTER ROLE chronos_reader LOGIN",
            f"GRANT chronos_reader TO {MIGRATOR_ROLE}",
        )
        for statement in forbidden:
            with migrator_engine.connect() as connection:
                with pytest.raises(DBAPIError) as denied:
                    connection.execute(sa.text(statement))
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    finally:
        migrator_engine.dispose()


def test_server_clock_claim_is_atomic_and_hashes_match_python(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            before = connection.scalar(sa.text("SELECT clock_timestamp()"))
            authority_id = issue(connection)
            receipt = claim(connection, authority_id)
            after = connection.scalar(sa.text("SELECT clock_timestamp()"))
            assert before <= receipt["db_authorized_at"] <= after
            assert receipt["postgres_server_epoch"] == connection.scalar(
                sa.text("SELECT pg_postmaster_start_time()")
            )
            events = connection.execute(
                sa.text(
                    "SELECT * FROM public.chronos_effect_events "
                    "WHERE authority_id=:authority_id ORDER BY event_seq"
                ),
                {"authority_id": authority_id},
            ).mappings().all()
            assert [(row["event_type"], row["event_seq"]) for row in events] == [
                ("AUTHORITY_GRANTED", 0),
                ("EFFECT_RESERVED", 1),
            ]
            assert events[1]["previous_event_hash"] == events[0]["event_hash"]
            for event in events:
                expected_hash = derive_event_hash(
                    event_seq=event["event_seq"],
                    operation_id=event["operation_id"],
                    authority_id=event["authority_id"],
                    event_type=EffectEventType(event["event_type"]),
                    resource_kind=event["resource_kind"],
                    resource_key=event["resource_key"],
                    payload_hash=event["payload_hash"],
                    db_recorded_at=event["db_recorded_at"],
                    github_run_id=event["github_run_id"],
                    github_run_attempt=event["github_run_attempt"],
                    code_revision=event["code_revision"],
                    previous_event_hash=event["previous_event_hash"],
                )
                assert event["event_hash"] == expected_hash
            assert receipt["authority_receipt_hash"] == framed_hash(
                authority_id,
                timestamp(receipt["db_authorized_at"]),
                timestamp(receipt["expires_at"]),
                timestamp(receipt["postgres_server_epoch"]),
                events[0]["operation_id"],
                hashlib.sha256(GENERATION).hexdigest(),
                RUN_ID,
                RUN_ATTEMPT,
                SHA,
                "org/repo/.github/workflows/chronos.yml@refs/heads/main",
                WORKFLOW_SHA,
                "org/repo",
                "refs/heads/main",
            )
            assert claim(connection, authority_id) == receipt
            dispatched = append(
                connection,
                authority_id,
                derive_operation_id(
                    mission_id=MISSION,
                    github_run_id=RUN_ID,
                    github_run_attempt=RUN_ATTEMPT,
                    resource_kind=RESOURCE_KIND,
                    canonical_key=RESOURCE_KEY,
                    canonical_payload_hash=PAYLOAD_HASH,
                ),
                "PUT_DISPATCHED",
            )
            assert dispatched["event_type"] == "PUT_DISPATCHED"
            with pytest.raises(
                DBAPIError,
                match="CHRONOS_DISPATCH_PERMIT_ALREADY_EXISTS",
            ), connection.begin_nested():
                append(
                    connection,
                    authority_id,
                    dispatched["operation_id"],
                    "PUT_DISPATCHED",
                )
            assert append(
                connection,
                authority_id,
                dispatched["operation_id"],
                "CREATED_CONFIRMED",
            )["event_type"] == "CREATED_CONFIRMED"
            stored_generation = connection.scalar(
                sa.text(
                    "SELECT control_plane_generation_hash "
                    "FROM chronos_effect_authorities WHERE authority_id=:id"
                ),
                {"id": authority_id},
            )
            assert stored_generation == hashlib.sha256(GENERATION).hexdigest()
        finally:
            transaction.rollback()


def test_database_expiry_cannot_be_reactivated_by_caller_time(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        authority_id = issue(connection, ttl_seconds=1)
        connection.execute(sa.text("SELECT pg_sleep(1.05)"))
        with pytest.raises(DBAPIError, match="CHRONOS_AUTHORITY_NOT_ACTIVE"):
            claim(connection, authority_id)
        transaction.rollback()


def test_get_permit_and_finalization_are_allowed_after_put_expiry(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        authority_id = issue(connection, ttl_seconds=1)
        receipt = claim(connection, authority_id)
        operation_id = derive_operation_id(
            mission_id=MISSION,
            github_run_id=RUN_ID,
            github_run_attempt=RUN_ATTEMPT,
            resource_kind=RESOURCE_KIND,
            canonical_key=RESOURCE_KEY,
            canonical_payload_hash=PAYLOAD_HASH,
        )
        append(connection, authority_id, operation_id, "PUT_DISPATCHED")
        for forbidden in ("PREEXISTING_CONFIRMED", "INTEGRITY_CONFLICT"):
            with pytest.raises(
                DBAPIError,
                match="CHRONOS_EFFECT_TRANSITION_FORBIDDEN",
            ), connection.begin_nested():
                append(connection, authority_id, operation_id, forbidden)
        connection.execute(sa.text("SELECT pg_sleep(1.05)"))
        permit = append(connection, authority_id, operation_id, "R2_GET_DISPATCHED")
        assert permit["event_type"] == "R2_GET_DISPATCHED"
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_R2_GET_PERMIT_ALREADY_EXISTS",
        ), connection.begin_nested():
            append(connection, authority_id, operation_id, "R2_GET_DISPATCHED")
        final = append(connection, authority_id, operation_id, "PREEXISTING_CONFIRMED")
        assert final["event_type"] == "PREEXISTING_CONFIRMED"
        assert receipt["expires_at"] < final["db_recorded_at"]
        transaction.rollback()


def test_null_nonce_and_identity_inputs_fail_closed(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        authority_id = issue(connection)
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_GENERATION_NONCE_INVALID",
        ), connection.begin_nested():
            claim(connection, authority_id, generation=None)
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_CLAIM_INPUT_INVALID",
        ), connection.begin_nested():
            claim(connection, authority_id, run_id=None)
        receipt = claim(connection, authority_id)
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_GENERATION_NONCE_INVALID",
        ), connection.begin_nested():
            append(
                connection,
                authority_id,
                derive_operation_id(
                    mission_id=MISSION,
                    github_run_id=RUN_ID,
                    github_run_attempt=RUN_ATTEMPT,
                    resource_kind=RESOURCE_KIND,
                    canonical_key=RESOURCE_KEY,
                    canonical_payload_hash=PAYLOAD_HASH,
                ),
                "PUT_DISPATCHED",
                generation=None,
            )
        assert receipt["authority_id"] == authority_id
        transaction.rollback()


def test_tables_are_append_only_even_for_owner(engine: Engine) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        authority_id = issue(connection)
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN",
        ), connection.begin_nested():
            connection.execute(
                sa.text(
                    "UPDATE chronos_effect_authorities SET mission_id='mutated' "
                    "WHERE authority_id=:id"
                ),
                {"id": authority_id},
            )
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN",
        ), connection.begin_nested():
            connection.execute(
                sa.text(
                    "TRUNCATE public.chronos_effect_authorities, "
                    "public.chronos_effect_events"
                )
            )
        with pytest.raises(
            DBAPIError,
            match="CHRONOS_APPEND_ONLY_MUTATION_FORBIDDEN",
        ), connection.begin_nested():
            connection.execute(sa.text("TRUNCATE public.chronos_effect_events"))
        transaction.rollback()


def test_roles_have_only_the_reviewed_capabilities(engine: Engine) -> None:
    with engine.connect() as connection:
        role_rows = connection.execute(
            sa.text(
                "SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                "rolreplication,rolbypassrls,rolconfig,"
                "shobj_description(oid,'pg_authid') AS provenance FROM pg_roles "
                "WHERE rolname LIKE 'chronos_%' ORDER BY rolname"
            )
        ).mappings().all()
        expected_roles = {
            "chronos_authority_executor",
            "chronos_reader",
            "chronos_runtime_writer",
            "chronos_test_writer",
            BOOTSTRAP_AUTHORITY_ROLE,
        }
        if SCOPED_LOGINS_CONFIGURED:
            expected_roles.update(SCOPED_LOGIN_GROUPS)
        assert {row["rolname"] for row in role_rows} == expected_roles
        for row in role_rows:
            is_scoped_login = row["rolname"] in SCOPED_LOGIN_GROUPS
            is_bootstrap_authority = row["rolname"] == BOOTSTRAP_AUTHORITY_ROLE
            assert row["rolcanlogin"] == is_scoped_login
            assert not any(
                row[name]
                for name in (
                    "rolsuper",
                    "rolcreatedb",
                    "rolreplication",
                    "rolbypassrls",
                )
            )
            assert bool(row["rolcreaterole"]) is is_bootstrap_authority
            assert row["rolconfig"] is None
            expected_provenance = (
                "managed-by:chronos-dual-principal-authority-e1-v2"
                + (":authority" if is_bootstrap_authority else "")
            )
            assert row["provenance"] == expected_provenance
        memberships = connection.execute(
            sa.text(
                "SELECT granted.rolname AS granted_role,member.rolname AS member_role,"
                "grantor.rolname AS grantor_role,"
                "grantor.rolsuper AS grantor_superuser,"
                "m.admin_option,m.inherit_option,m.set_option,"
                "pg_catalog.pg_has_role(member.oid,granted.oid,'USAGE') "
                "AS runtime_usage,"
                "pg_catalog.pg_has_role(member.oid,granted.oid,'SET') "
                "AS runtime_set "
                "FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
                "WHERE granted.rolname LIKE 'chronos_%' "
                "OR member.rolname LIKE 'chronos_%' "
                "OR granted.rolname=:migrator OR member.rolname=:migrator "
                "OR granted.rolname=:owner OR member.rolname=:owner"
            ),
            {"migrator": MIGRATOR_ROLE, "owner": BOOTSTRAP_AUTHORITY_ROLE},
        ).mappings().all()
        if MIGRATOR_ROLE and BOOTSTRAP_AUTHORITY_ROLE:
            migrator_groups = set(SCOPED_LOGIN_GROUPS.values()) | {
                "chronos_test_writer"
            }
            expected_memberships = {
                (role, BOOTSTRAP_AUTHORITY_ROLE) for role in migrator_groups
            }
            if SCOPED_LOGINS_CONFIGURED:
                expected_memberships.update(
                    (group, login) for login, group in SCOPED_LOGIN_GROUPS.items()
                )
                expected_memberships.update(
                    (login, BOOTSTRAP_AUTHORITY_ROLE) for login in SCOPED_LOGIN_GROUPS
                )
            expected_memberships.add((MIGRATOR_ROLE, BOOTSTRAP_AUTHORITY_ROLE))
            lifecycle_admin_superuser = bool(
                connection.scalar(
                    sa.text(
                        "SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname=:role"
                    ),
                    {"role": LIFECYCLE_ADMIN_ROLE},
                )
            )
            if LIFECYCLE_ADMIN_ROLE and not lifecycle_admin_superuser:
                expected_memberships.add(
                    (BOOTSTRAP_AUTHORITY_ROLE, LIFECYCLE_ADMIN_ROLE)
                )
            assert {
                (row["granted_role"], row["member_role"]) for row in memberships
            } == expected_memberships
            system_grantors = {
                row["grantor_role"]
                for row in memberships
                if row["member_role"] == BOOTSTRAP_AUTHORITY_ROLE
            }
            assert len(system_grantors) == 1
            assert all(
                (
                    row["member_role"] == BOOTSTRAP_AUTHORITY_ROLE
                    and row["grantor_superuser"]
                    and row["admin_option"]
                    and not row["inherit_option"]
                    and not row["set_option"]
                    and not row["runtime_usage"]
                    and not row["runtime_set"]
                )
                or (
                    not lifecycle_admin_superuser
                    and row["granted_role"] == BOOTSTRAP_AUTHORITY_ROLE
                    and row["member_role"] == LIFECYCLE_ADMIN_ROLE
                    and row["grantor_superuser"]
                    and row["admin_option"]
                    and not row["inherit_option"]
                    and not row["set_option"]
                    and not row["runtime_usage"]
                    and not row["runtime_set"]
                )
                or (
                    row["member_role"] in SCOPED_LOGIN_GROUPS
                    and row["grantor_role"] == BOOTSTRAP_AUTHORITY_ROLE
                    and not row["grantor_superuser"]
                    and not row["admin_option"]
                    and row["inherit_option"]
                    and not row["set_option"]
                    and row["runtime_usage"]
                    and not row["runtime_set"]
                )
                for row in memberships
            )
        else:
            assert memberships == []
        direct_dml = connection.scalar(
            sa.text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee IN ('chronos_runtime_writer','chronos_test_writer',"
                "'chronos_authority_executor') AND privilege_type IN "
                "('INSERT','UPDATE','DELETE','TRUNCATE')"
            )
        )
        assert direct_dml == 0
        test_executes = connection.scalar(
            sa.text(
                "SELECT count(*) FROM information_schema.routine_privileges "
                "WHERE grantee='chronos_test_writer' "
                "AND routine_name LIKE 'chronos_%' AND privilege_type='EXECUTE'"
            )
        )
        assert test_executes == 0
        object_acl_rows = connection.execute(
            sa.text(
                "SELECT 'relation' AS object_kind,c.relname AS object_name,"
                "coalesce(r.rolname,'PUBLIC') AS grantee,acl.privilege_type "
                "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                "ON n.oid=c.relnamespace CROSS JOIN LATERAL "
                "pg_catalog.aclexplode(coalesce(c.relacl,"
                "pg_catalog.acldefault('r',c.relowner))) acl LEFT JOIN "
                "pg_catalog.pg_roles r ON r.oid=acl.grantee "
                "WHERE n.nspname='public' AND c.relname IN "
                "('chronos_effect_authorities','chronos_effect_events',"
                "'chronos_effect_accounting','chronos_opportunity_claims',"
                "'chronos_torrent_external_effect_permits',"
                "'chronos_torrent_external_effect_events',"
                "'chronos_torrent_batches','chronos_opportunity_claim_audit',"
                "'chronos_torrent_batch_audit',"
                "'chronos_torrent_external_effect_audit') "
                "AND acl.grantee<>c.relowner "
                "UNION ALL SELECT 'function',p.proname,"
                "coalesce(r.rolname,'PUBLIC'),acl.privilege_type "
                "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
                "ON n.oid=p.pronamespace CROSS JOIN LATERAL "
                "pg_catalog.aclexplode(coalesce(p.proacl,"
                "pg_catalog.acldefault('f',p.proowner))) acl LEFT JOIN "
                "pg_catalog.pg_roles r ON r.oid=acl.grantee "
                "WHERE n.nspname='public' AND p.proname IN "
                "('chronos_framed_sha256','chronos_effect_event_hash',"
                "'chronos_reject_mutation','chronos_issue_effect_authority',"
                "'chronos_claim_effect_authority',"
                "'chronos_append_effect_event','chronos_get_effect_state',"
                "'chronos_claim_opportunity',"
                "'chronos_reserve_torrent_external_effect',"
                "'chronos_append_torrent_external_effect',"
                "'chronos_record_torrent_batch',"
                "'chronos_reject_torrent_mutation') "
                "AND acl.grantee<>p.proowner"
            )
        ).all()
        assert {tuple(row) for row in object_acl_rows} == {
            (
                "relation",
                "chronos_effect_accounting",
                "chronos_reader",
                "SELECT",
            ),
            (
                "function",
                "chronos_issue_effect_authority",
                "chronos_authority_executor",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_claim_effect_authority",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_append_effect_event",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_get_effect_state",
                "chronos_reader",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_get_effect_state",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "relation",
                "chronos_opportunity_claim_audit",
                "chronos_reader",
                "SELECT",
            ),
            (
                "relation",
                "chronos_torrent_batch_audit",
                "chronos_reader",
                "SELECT",
            ),
            (
                "relation",
                "chronos_torrent_external_effect_audit",
                "chronos_reader",
                "SELECT",
            ),
            (
                "function",
                "chronos_claim_opportunity",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_reserve_torrent_external_effect",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_append_torrent_external_effect",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
            (
                "function",
                "chronos_record_torrent_batch",
                "chronos_runtime_writer",
                "EXECUTE",
            ),
        }


@pytest.mark.skipif(
    not SCOPED_LOGINS_CONFIGURED,
    reason="the three PostgreSQL 16 scoped LOGIN fixtures are not configured",
)
def test_scoped_login_connections_enforce_allows_and_denials() -> None:
    engines = {
        role: build_engine(url) for role, url in SCOPED_LOGIN_URLS.items()
    }
    try:
        authority_engine = engines["chronos_authority_runtime_login"]
        runtime_engine = engines["chronos_effect_runtime_login"]
        reader_engine = engines["chronos_reader_login"]

        with authority_engine.begin() as connection:
            assert connection.scalar(sa.text("SELECT current_user")) == (
                "chronos_authority_runtime_login"
            )
            authority_id = issue(connection)
        with authority_engine.connect() as connection:
            with pytest.raises(DBAPIError) as denied:
                connection.execute(
                    sa.text("SELECT * FROM public.chronos_get_effect_state(:operation_id)"),
                    {"operation_id": "0" * 64},
                ).all()
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"

        with runtime_engine.begin() as connection:
            assert connection.scalar(sa.text("SELECT current_user")) == (
                "chronos_effect_runtime_login"
            )
            resource_key = f"{RESOURCE_KEY}/{authority_id}"
            claim(connection, authority_id, resource_key=resource_key)
            operation_id = derive_operation_id(
                mission_id=MISSION,
                github_run_id=RUN_ID,
                github_run_attempt=RUN_ATTEMPT,
                resource_kind=RESOURCE_KIND,
                canonical_key=resource_key,
                canonical_payload_hash=PAYLOAD_HASH,
            )
        with runtime_engine.connect() as connection:
            with pytest.raises(DBAPIError) as denied:
                issue(connection)
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"

        with reader_engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT current_user")) == (
                "chronos_reader_login"
            )
            assert connection.scalar(
                sa.text("SELECT version_num FROM public.alembic_version")
            ) == "0015_data_torrent_opportunity"
            state = connection.execute(
                sa.text("SELECT * FROM public.chronos_get_effect_state(:operation_id)"),
                {"operation_id": operation_id},
            ).mappings().one()
            assert state["operation_id"] == operation_id
        with reader_engine.connect() as connection:
            with pytest.raises(DBAPIError) as denied:
                claim(connection, authority_id)
            assert getattr(denied.value.orig, "sqlstate", None) == "42501"

        for login, scoped_engine in engines.items():
            other_login = next(name for name in engines if name != login)
            for statement in (
                "CREATE ROLE rds_forbidden_runtime_alias NOLOGIN",
                f"ALTER ROLE {other_login} CREATEROLE",
                f"GRANT chronos_reader TO {login}",
                f"SET ROLE {other_login}",
                f"SET ROLE {MIGRATOR_ROLE}",
            ):
                with scoped_engine.connect() as connection:
                    with pytest.raises(DBAPIError) as denied:
                        connection.execute(sa.text(statement))
                    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
    finally:
        for value in engines.values():
            value.dispose()


@pytest.mark.skipif(
    not MIGRATOR_ROLE or not BOOTSTRAP_AUTHORITY_ROLE,
    reason="the PostgreSQL 16 non-superuser migrator fixture is not configured",
)
def test_non_superuser_migrator_is_nocreaterole_and_has_no_runtime_edge(
    engine: Engine,
) -> None:
    with engine.connect() as connection:
        migrator = connection.execute(
            sa.text(
                "SELECT rolsuper,rolcreaterole FROM pg_catalog.pg_roles "
                "WHERE rolname=:role"
            ),
            {"role": MIGRATOR_ROLE},
        ).mappings().one()
        assert dict(migrator) == {"rolsuper": False, "rolcreaterole": False}
        terminal_states = connection.execute(
            sa.text(
                "SELECT r.rolname,r.rolcanlogin,r.rolcreaterole,"
                "a.rolpassword IS NULL AS password_null "
                "FROM pg_catalog.pg_roles r "
                "JOIN pg_catalog.pg_authid a ON a.oid=r.oid "
                "WHERE r.rolname=ANY(:roles) ORDER BY r.rolname"
            ),
            {"roles": [MIGRATOR_ROLE, BOOTSTRAP_AUTHORITY_ROLE]},
        ).mappings().all()
        assert [dict(row) for row in terminal_states] == [
            {
                "rolname": BOOTSTRAP_AUTHORITY_ROLE,
                "rolcanlogin": False,
                "rolcreaterole": True,
                "password_null": True,
            },
            {
                "rolname": MIGRATOR_ROLE,
                "rolcanlogin": False,
                "rolcreaterole": False,
                "password_null": True,
            },
        ]
        active_lifecycle_sessions = connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_stat_activity "
                "WHERE usename=ANY(:roles)"
            ),
            {"roles": [MIGRATOR_ROLE, BOOTSTRAP_AUTHORITY_ROLE]},
        )
        assert active_lifecycle_sessions == 0
        migrator_runtime_edges = connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE (granted.rolname=:migrator "
                "AND member.rolname=ANY(:runtime)) OR "
                "(member.rolname=:migrator AND granted.rolname=ANY(:runtime))"
            ),
            {
                "migrator": MIGRATOR_ROLE,
                "runtime": list(SCOPED_LOGIN_GROUPS),
            },
        )
        assert migrator_runtime_edges == 0
