from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from robin.prospective_observatory.chronos_control_plane import (
    EffectEventType,
    derive_event_hash,
    derive_operation_id,
)
from robin.storage.database import build_engine

POSTGRES_URL = os.getenv("ROBIN_TEST_POSTGRES_URL", "")
MIGRATOR_ROLE = os.getenv("ROBIN_TEST_CHRONOS_MIGRATOR_ROLE", "")
SENTINEL_ROLE = os.getenv("ROBIN_TEST_CHRONOS_SENTINEL_ROLE", "")
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
) -> sa.RowMapping:
    operation_id = derive_operation_id(
        mission_id=MISSION,
        github_run_id=RUN_ID,
        github_run_attempt=RUN_ATTEMPT,
        resource_kind=RESOURCE_KIND,
        canonical_key=RESOURCE_KEY,
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
            "resource_key": RESOURCE_KEY,
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
                    "SELECT * FROM public.chronos_effect_events ORDER BY event_seq"
                )
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
        assert {row["rolname"] for row in role_rows} == {
            "chronos_authority_executor",
            "chronos_reader",
            "chronos_runtime_writer",
            "chronos_test_writer",
        }
        for row in role_rows:
            assert not any(
                row[name]
                for name in (
                    "rolcanlogin",
                    "rolsuper",
                    "rolcreatedb",
                    "rolcreaterole",
                    "rolreplication",
                    "rolbypassrls",
                )
            )
            assert row["rolconfig"] is None
            assert row["provenance"] == "managed-by:0014_chronos_control_plane_v2"
        memberships = connection.execute(
            sa.text(
                "SELECT granted.rolname AS granted_role,member.rolname AS member_role,"
                "m.grantor='10'::pg_catalog.oid AS bootstrap_grantor,"
                "m.admin_option,m.inherit_option,m.set_option "
                "FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE granted.rolname LIKE 'chronos_%' "
                "OR member.rolname LIKE 'chronos_%'"
            )
        ).mappings().all()
        if MIGRATOR_ROLE:
            assert {row["granted_role"] for row in memberships} == {
                "chronos_authority_executor",
                "chronos_reader",
                "chronos_runtime_writer",
                "chronos_test_writer",
            }
            assert len(memberships) == 4
            assert all(
                row["member_role"] == MIGRATOR_ROLE
                and row["bootstrap_grantor"]
                and row["admin_option"]
                and not row["inherit_option"]
                and not row["set_option"]
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
                "'chronos_effect_accounting') AND acl.grantee<>c.relowner "
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
                "'chronos_append_effect_event','chronos_get_effect_state') "
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
        }


@pytest.mark.skipif(
    not MIGRATOR_ROLE or not SENTINEL_ROLE,
    reason="the PostgreSQL 16 non-superuser migrator fixture is not configured",
)
def test_non_superuser_migrator_is_admin_only_and_default_acl_is_neutralized(
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
        assert dict(migrator) == {"rolsuper": False, "rolcreaterole": True}
        default_insert = connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_default_acl d "
                "JOIN pg_catalog.pg_roles owner ON owner.oid=d.defaclrole "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) acl "
                "JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee "
                "WHERE owner.rolname=:owner AND grantee.rolname=:sentinel "
                "AND acl.privilege_type='INSERT'"
            ),
            {"owner": MIGRATOR_ROLE, "sentinel": SENTINEL_ROLE},
        )
        assert default_insert == 1
        usable_chronos_roles = connection.scalar(
            sa.text(
                "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE granted.rolname LIKE 'chronos_%' "
                "AND member.rolname=:migrator "
                "AND pg_catalog.pg_has_role(member.oid,granted.oid,'USAGE')"
            ),
            {"migrator": MIGRATOR_ROLE},
        )
        assert usable_chronos_roles == 0
        sentinel_table_privileges = connection.scalar(
            sa.text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee=:sentinel AND table_schema='public' "
                "AND table_name LIKE 'chronos_%'"
            ),
            {"sentinel": SENTINEL_ROLE},
        )
        assert sentinel_table_privileges == 0
