"""Provider-free PostgreSQL 16 role lifecycle for Chronos through revision 0015."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import ClientCursor, Connection, sql
from psycopg.errors import InsufficientPrivilege

from robin.chronos_production import ChronosProductionError, require_identifier

GROUP_ROLES = (
    "chronos_authority_executor",
    "chronos_reader",
    "chronos_runtime_writer",
    "chronos_test_writer",
)
BOOTSTRAP_AUTHORITY = "chronos_bootstrap_authority"
BOOTSTRAP_EXECUTOR_PREFIX = "chronos_bootstrap_executor_"
RUNTIME_ROLE_GROUPS = {
    "chronos_authority_runtime_login": "chronos_authority_executor",
    "chronos_effect_runtime_login": "chronos_runtime_writer",
    "chronos_reader_login": "chronos_reader",
}
ROLE_MARKER = "managed-by:chronos-dual-principal-authority-e1-v2"
MIGRATOR_MARKER = "managed-by:chronos-dual-principal-authority-e1-v2:migrator"
AUTHORITY_MARKER = "managed-by:chronos-dual-principal-authority-e1-v2:authority"
EXECUTOR_MARKER = "managed-by:chronos-dual-principal-authority-e1-v2:executor"
LIFECYCLE_LOCK_KEYS = (0x4348524F, 0x4E4F5332)
CHRONOS_BASE_FUNCTION_SIGNATURES = {
    "chronos_framed_sha256": "text[]",
    "chronos_effect_event_hash": (
        "bigint, text, text, text, text, text, text, timestamp with time zone, "
        "bigint, integer, text, text"
    ),
    "chronos_reject_mutation": "",
    "chronos_issue_effect_authority": (
        "text, bigint, integer, text, text, text, text, text, bytea, integer, text"
    ),
    "chronos_claim_effect_authority": (
        "text, text, bigint, integer, text, text, text, text, text, bytea, "
        "text, text, text, text, text"
    ),
    "chronos_append_effect_event": (
        "text, text, text, bigint, integer, text, text, text, text, text, bytea, text"
    ),
    "chronos_get_effect_state": "text",
}
CHRONOS_TORRENT_FUNCTION_SIGNATURES = {
    "chronos_claim_opportunity": (
        "text, text, bigint, integer, text, text, text, text, text, bytea, text, text, text, text"
    ),
    "chronos_reserve_torrent_external_effect": (
        "text, text, integer, text, integer, integer, integer, bigint, integer, text, bytea"
    ),
    "chronos_append_torrent_external_effect": (
        "text, text, integer, integer, integer, bigint, integer, text, bytea"
    ),
    "chronos_record_torrent_batch": (
        "text, text, text, text, text, text, text, text, jsonb, jsonb, jsonb, "
        "jsonb, jsonb, integer, integer, integer, integer, bigint, bigint, "
        "bigint, bigint, bigint, bigint, integer, bigint, double precision, "
        "double precision, double precision, double precision, bigint, "
        "double precision, double precision, double precision, boolean, "
        "integer, integer, integer, integer, integer, integer, integer, "
        "integer, integer, integer, integer, integer, integer, integer, "
        "boolean, bigint, integer, text, bytea"
    ),
    "chronos_reject_torrent_mutation": "",
}
CHRONOS_FUNCTION_SIGNATURES = {
    **CHRONOS_BASE_FUNCTION_SIGNATURES,
    **CHRONOS_TORRENT_FUNCTION_SIGNATURES,
}
CHRONOS_BASE_RELATIONS = (
    "chronos_effect_authorities",
    "chronos_effect_events",
    "chronos_effect_accounting",
)
CHRONOS_TORRENT_RELATIONS = (
    "chronos_opportunity_claims",
    "chronos_torrent_external_effect_permits",
    "chronos_torrent_external_effect_events",
    "chronos_torrent_batches",
    "chronos_opportunity_claim_audit",
    "chronos_torrent_batch_audit",
    "chronos_torrent_external_effect_audit",
)
CHRONOS_RELATIONS = CHRONOS_BASE_RELATIONS + CHRONOS_TORRENT_RELATIONS


def role_inventory_snapshot(
    connection: Connection[Any],
) -> dict[str, tuple[Any, ...]]:
    """Capture every role so an unmarked helper alias cannot hide from deltas."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname,oid,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
            "rolcreaterole,rolreplication,rolbypassrls,rolconfig,"
            "rolvaliduntil::text,"
            "coalesce(pg_catalog.shobj_description(oid,'pg_authid'),'') "
            "FROM pg_catalog.pg_roles ORDER BY rolname"
        )
        rows = cursor.fetchall()
    return {str(row[0]): tuple(row[1:]) for row in rows}


def role_inventory_hash(connection: Connection[Any]) -> str:
    snapshot = role_inventory_snapshot(connection)
    payload = [[name, *values] for name, values in sorted(snapshot.items())]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def assert_role_inventory_delta(
    connection: Connection[Any],
    *,
    baseline: dict[str, tuple[Any, ...]],
    expected_new_roles: Sequence[str],
) -> None:
    current = role_inventory_snapshot(connection)
    if any(current.get(name) != state for name, state in baseline.items()) or set(
        current
    ).difference(baseline) != set(expected_new_roles):
        raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_DELTA_UNSAFE")


@dataclass(frozen=True, slots=True)
class RoleEdgeAudit:
    phase: str
    bootstrap_owner: str
    lifecycle_admin: str
    lifecycle_admin_superuser: bool
    executor_role: str | None
    bootstrap_system_grantor: str
    migrator_role: str | None
    role_inventory: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    forbidden_edge_count: int
    runtime_effective_bootstrap_edge_count: int
    migrator_runtime_edge_count: int
    runtime_to_authority_path_count: int
    runtime_to_lifecycle_admin_path_count: int
    executor_role_count: int
    executor_membership_count: int
    neon_platform_edge_count: int
    neon_platform_descendant_count: int

    def report(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "bootstrap_authority": self.bootstrap_owner,
            "bootstrap_owner": self.bootstrap_owner,
            "lifecycle_admin": self.lifecycle_admin,
            "lifecycle_admin_superuser": self.lifecycle_admin_superuser,
            "executor_role": self.executor_role,
            "bootstrap_system_grantor": self.bootstrap_system_grantor,
            "migrator_role": self.migrator_role,
            "role_inventory": list(self.role_inventory),
            "edges": list(self.edges),
            "edge_count": len(self.edges),
            "forbidden_edge_count": self.forbidden_edge_count,
            "hidden_edge_count": self.forbidden_edge_count,
            "runtime_effective_bootstrap_edge_count": (self.runtime_effective_bootstrap_edge_count),
            "migrator_runtime_edge_count": self.migrator_runtime_edge_count,
            "runtime_to_authority_path_count": self.runtime_to_authority_path_count,
            "runtime_to_lifecycle_admin_path_count": (self.runtime_to_lifecycle_admin_path_count),
            "executor_role_count": self.executor_role_count,
            "executor_membership_count": self.executor_membership_count,
            "neon_platform_edge_count": self.neon_platform_edge_count,
            "neon_platform_descendant_count": (self.neon_platform_descendant_count),
        }


@dataclass(frozen=True, slots=True)
class BootstrapExecutorLease:
    authority: str
    authority_oid: int
    executor_role: str
    lifecycle_admin: str
    lifecycle_admin_superuser: bool
    valid_until: datetime


def stable_migrator_role(production_branch_id: str) -> str:
    """Derive a stable bounded role name from database branch identity."""

    if not production_branch_id:
        raise ChronosProductionError("CHRONOS_PRODUCTION_BRANCH_ID_MISSING")
    suffix = hashlib.sha256(production_branch_id.encode("utf-8")).hexdigest()[:16]
    return f"chronos_migrator_0014_{suffix}"


def _configure_transaction(connection: Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL createrole_self_grant = ''")
        cursor.execute("SET LOCAL statement_timeout = '300s'")
        cursor.execute("SET LOCAL idle_session_timeout = '60s'")
        cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '60s'")
        cursor.execute("SHOW createrole_self_grant")
        row = cursor.fetchone()
        if row is None or str(row[0]) != "":
            raise ChronosProductionError("CHRONOS_CREATEROLE_SELF_GRANT_UNSAFE")


def _configure_executor_session(connection: Connection[Any]) -> None:
    """Bound the authenticated executor session across transaction commits."""

    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = '300s'")
        cursor.execute("SET idle_session_timeout = '10min'")
        cursor.execute("SET idle_in_transaction_session_timeout = '60s'")


def acquire_lifecycle_lock(connection: Connection[Any]) -> None:
    """Fence one lifecycle attempt for the lifetime of the admin connection."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_try_advisory_lock(%s,%s)",
            LIFECYCLE_LOCK_KEYS,
        )
        row = cursor.fetchone()
    if row is None or not bool(row[0]):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_ALREADY_RUNNING")


def release_lifecycle_lock(connection: Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_unlock(%s,%s)",
            LIFECYCLE_LOCK_KEYS,
        )
        row = cursor.fetchone()
    if row is None or not bool(row[0]):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_LOCK_NOT_HELD")


def assert_lifecycle_admin(connection: Connection[Any]) -> tuple[str, bool]:
    """Require a direct external admin session, superuser or CREATEROLE."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT session_user,current_user,rolcanlogin,rolsuper,rolcreaterole "
            "FROM pg_catalog.pg_roles WHERE rolname=current_user"
        )
        row = cursor.fetchone()
    if row is None:
        raise ChronosProductionError("CHRONOS_LIFECYCLE_ADMIN_MISSING")
    session_role = str(row[0])
    current_role = str(row[1])
    forbidden = (
        current_role == BOOTSTRAP_AUTHORITY
        or current_role in GROUP_ROLES
        or current_role in RUNTIME_ROLE_GROUPS
        or current_role.startswith(BOOTSTRAP_EXECUTOR_PREFIX)
        or current_role.startswith("chronos_migrator_")
    )
    if (
        session_role != current_role
        or not bool(row[2])
        or not (bool(row[3]) or bool(row[4]))
        or forbidden
    ):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_ADMIN_UNSAFE")
    return current_role, bool(row[3])


def assert_privileged_catalog_visibility(connection: Connection[Any]) -> None:
    """Fail before mutation unless password-null proofs are possible."""

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolpassword IS NULL FROM pg_catalog.pg_authid WHERE rolname=current_user"
            )
            row = cursor.fetchone()
    except InsufficientPrivilege:
        raise ChronosProductionError("CHRONOS_PG_AUTHID_VISIBILITY_REQUIRED") from None
    if row is None:
        raise ChronosProductionError("CHRONOS_PG_AUTHID_VISIBILITY_REQUIRED")


def _assert_permanent_authority_catalog(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT oid,rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,"
            "rolreplication,rolbypassrls,rolconfig,rolvaliduntil,"
            "pg_catalog.shobj_description(oid,'pg_authid') "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (authority,),
        )
        row = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=%s",
            (authority,),
        )
        sessions = cursor.fetchone()
    if (
        row is None
        or bool(row[1])
        or bool(row[2])
        or bool(row[3])
        or bool(row[4])
        or not bool(row[5])
        or bool(row[6])
        or bool(row[7])
        or row[8] is not None
        or row[9] is not None
        or str(row[10]) != AUTHORITY_MARKER
        or sessions is None
        or int(sessions[0]) != 0
    ):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_UNSAFE")
    _assert_role_has_no_ownership_or_settings(connection, authority)
    return int(row[0])


def assert_authority_password_null(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> None:
    """Privileged catalog proof used by PostgreSQL 16 CI and capable admins."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolpassword IS NULL FROM pg_catalog.pg_authid WHERE rolname=%s",
            (authority,),
        )
        row = cursor.fetchone()
    if row is None or not bool(row[0]):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_PASSWORD_UNSAFE")


def _assert_authority_memberships_safe(
    connection: Connection[Any],
    *,
    authority: str,
    lifecycle_admin: str,
    lifecycle_admin_superuser: bool,
) -> None:
    """Reject hidden direct or transitive authority privilege before SET ROLE."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT granted.rolname,member.rolname,grantor.rolname,"
            "grantor.rolsuper,m.admin_option,m.inherit_option,m.set_option,"
            "coalesce(pg_catalog.shobj_description(granted.oid,'pg_authid'),''),"
            "coalesce(pg_catalog.shobj_description(member.oid,'pg_authid'),'') "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=%s OR member.rolname=%s ORDER BY 1,2,3",
            (authority, authority),
        )
        edges = cursor.fetchall()
        cursor.execute(
            "SELECT rolname FROM pg_catalog.pg_roles r WHERE rolname<>%s AND "
            "(pg_catalog.pg_has_role(%s,r.oid,'USAGE') OR "
            "pg_catalog.pg_has_role(%s,r.oid,'SET')) ORDER BY rolname",
            (authority, authority, authority),
        )
        effective_targets = {str(row[0]) for row in cursor.fetchall()}

    for edge in edges:
        granted = str(edge[0])
        member = str(edge[1])
        grantor_superuser = bool(edge[3])
        options = (bool(edge[4]), bool(edge[5]), bool(edge[6]))
        granted_marker = str(edge[7])
        member_marker = str(edge[8])
        creator_target = (
            granted in GROUP_ROLES
            or granted in RUNTIME_ROLE_GROUPS
            or (granted_marker == MIGRATOR_MARKER)
        )
        is_creator_edge = (
            member == authority
            and creator_target
            and grantor_superuser
            and options == (True, False, False)
        )
        is_external_admin_edge = (
            not lifecycle_admin_superuser
            and granted == authority
            and member == lifecycle_admin
            and grantor_superuser
            and options == (True, False, False)
        )
        is_executor_edge = (
            granted == authority
            and member.startswith(BOOTSTRAP_EXECUTOR_PREFIX)
            and member_marker == EXECUTOR_MARKER
            and str(edge[2]) == lifecycle_admin
            and options == (False, False, True)
        )
        if not (is_creator_edge or is_external_admin_edge or is_executor_edge):
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_MEMBERSHIP_UNSAFE")

    if effective_targets:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_EFFECTIVE_ROLE_UNSAFE")


def provision_permanent_bootstrap_authority(
    connection: Connection[Any],
    *,
    authority: str = BOOTSTRAP_AUTHORITY,
    lifecycle_lock_held: bool = False,
) -> tuple[str, int, str, bool]:
    """Create or assert the permanent NOLOGIN authority as the external admin."""

    require_identifier(authority, field="bootstrap_authority")
    lifecycle_admin, lifecycle_admin_superuser = assert_lifecycle_admin(connection)
    assert_privileged_catalog_visibility(connection)
    if not lifecycle_lock_held:
        acquire_lifecycle_lock(connection)
    _configure_transaction(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s)",
            (authority,),
        )
        exists = cursor.fetchone()
        if exists is None:
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_LOOKUP_FAILED")
        if not bool(exists[0]):
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "CREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL"
                ).format(sql.Identifier(authority))
            )
            with _client_cursor(connection) as client_cursor:
                client_cursor.execute(
                    sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(authority)),
                    (AUTHORITY_MARKER,),
                )
        cursor.execute(
            "SELECT owner.rolname, pg_catalog.pg_has_role("
            "CURRENT_USER,n.nspowner,'SET') FROM pg_catalog.pg_namespace n "
            "JOIN pg_catalog.pg_roles owner ON owner.oid=n.nspowner "
            "WHERE n.nspname='public'"
        )
        schema_owner = cursor.fetchone()
        if schema_owner is None:
            raise ChronosProductionError("CHRONOS_PUBLIC_SCHEMA_OWNER_MISSING")
        schema_owner_name = str(schema_owner[0])
        can_set_schema_owner = bool(schema_owner[1])
        _grant_bootstrap_authority_schema(
            cursor,
            authority=authority,
            lifecycle_admin=lifecycle_admin,
            schema_owner_name=schema_owner_name,
            can_set_schema_owner=can_set_schema_owner,
        )
        cursor.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                "public.alembic_version TO {} WITH GRANT OPTION"
            ).format(sql.Identifier(authority))
        )
    authority_oid = _assert_permanent_authority_catalog(connection, authority=authority)
    assert_authority_password_null(connection, authority=authority)
    _assert_authority_memberships_safe(
        connection,
        authority=authority,
        lifecycle_admin=lifecycle_admin,
        lifecycle_admin_superuser=lifecycle_admin_superuser,
    )
    _assert_authority_bootstrap_acl(
        connection, authority=authority, lifecycle_admin=lifecycle_admin
    )
    connection.commit()
    return (
        authority,
        authority_oid,
        lifecycle_admin,
        lifecycle_admin_superuser,
    )


def _grant_bootstrap_authority_schema(
    cursor: Any,
    *,
    authority: str,
    lifecycle_admin: str,
    schema_owner_name: str,
    can_set_schema_owner: bool,
) -> None:
    """Grant schema ACLs without masking a failed GRANT with RESET ROLE."""

    switched_to_schema_owner = schema_owner_name != lifecycle_admin and can_set_schema_owner
    if switched_to_schema_owner:
        cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(schema_owner_name)))
    cursor.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {} WITH GRANT OPTION").format(
            sql.Identifier(authority)
        )
    )
    if switched_to_schema_owner:
        cursor.execute("RESET ROLE")


def _executor_names(connection: Connection[Any]) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname LIKE %s ORDER BY rolname",
            (BOOTSTRAP_EXECUTOR_PREFIX + "%",),
        )
        return [str(row[0]) for row in cursor.fetchall()]


def _assert_executor_catalog(
    connection: Connection[Any],
    *,
    role: str,
    require_live_window: bool,
    expected_login: bool | None = True,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,"
            "rolreplication,rolbypassrls,rolconnlimit,rolconfig,"
            "rolvaliduntil IS NOT NULL,rolvaliduntil>clock_timestamp(),"
            "rolvaliduntil<=clock_timestamp()+interval '10 minutes',"
            "pg_catalog.shobj_description(oid,'pg_authid') "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        )
        row = cursor.fetchone()
    if (
        row is None
        or (expected_login is not None and bool(row[0]) is not expected_login)
        or bool(row[1])
        or any(bool(value) for value in row[2:7])
        or int(row[7]) != 1
        or row[8] is not None
        or not bool(row[9])
        or (require_live_window and not bool(row[10]))
        or not bool(row[11])
        or str(row[12]) != EXECUTOR_MARKER
    ):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_UNSAFE")
    _assert_role_has_no_smuggled_state(connection, role)


def _executor_memberships(
    connection: Connection[Any], *, executor_role: str
) -> list[tuple[str, str, str, bool, bool, bool, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT granted.rolname,member.rolname,grantor.rolname,"
            "grantor.rolsuper,m.admin_option,m.inherit_option,m.set_option "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=%s OR member.rolname=%s "
            "ORDER BY 1,2,3",
            (executor_role, executor_role),
        )
        return [
            (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                bool(row[3]),
                bool(row[4]),
                bool(row[5]),
                bool(row[6]),
            )
            for row in cursor.fetchall()
        ]


def _assert_executor_has_no_functional_privileges(
    connection: Connection[Any], *, executor_role: str
) -> None:
    """Evaluate PUBLIC and direct privileges on every existing Chronos object."""

    table_privileges = (
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    )
    column_privileges = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.has_schema_privilege(%s,'public','CREATE')",
            (executor_role,),
        )
        schema_create = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN unnest(%s::text[]) privilege "
            "WHERE n.nspname='public' "
            "AND (c.relname LIKE 'chronos\\_%%' ESCAPE '\\' "
            "OR c.relname='alembic_version') "
            "AND c.relkind IN ('r','p','v','m','f') "
            "AND pg_catalog.has_table_privilege(%s,c.oid,privilege)",
            (list(table_privileges), executor_role),
        )
        table_count = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN unnest(%s::text[]) privilege "
            "WHERE n.nspname='public' "
            "AND (c.relname LIKE 'chronos\\_%%' ESCAPE '\\' "
            "OR c.relname='alembic_version') "
            "AND c.relkind IN ('r','p','v','m','f') "
            "AND pg_catalog.has_any_column_privilege(%s,c.oid,privilege)",
            (list(column_privileges), executor_role),
        )
        column_count = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN unnest(ARRAY['SELECT','USAGE','UPDATE']) privilege "
            "WHERE n.nspname='public' AND c.relname LIKE 'chronos\\_%%' ESCAPE '\\' "
            "AND c.relkind='S' "
            "AND pg_catalog.has_sequence_privilege(%s,c.oid,privilege)",
            (executor_role,),
        )
        sequence_count = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname=ANY(%s) "
            "AND pg_catalog.has_function_privilege(%s,p.oid,'EXECUTE')",
            (list(CHRONOS_FUNCTION_SIGNATURES), executor_role),
        )
        function_count = cursor.fetchone()
    if (
        schema_create is None
        or bool(schema_create[0])
        or table_count is None
        or int(table_count[0]) != 0
        or column_count is None
        or int(column_count[0]) != 0
        or sequence_count is None
        or int(sequence_count[0]) != 0
        or function_count is None
        or int(function_count[0]) != 0
    ):
        raise ChronosProductionError("CHRONOS_EXECUTOR_EFFECTIVE_PRIVILEGE_UNSAFE")


def cleanup_bootstrap_executor(
    connection: Connection[Any],
    *,
    executor_role: str,
    authority: str,
    lifecycle_admin: str,
    lifecycle_admin_superuser: bool,
) -> None:
    """Externally revoke, neutralize and delete one never-adopted executor."""

    _assert_executor_catalog(
        connection,
        role=executor_role,
        require_live_window=False,
        expected_login=None,
    )
    with connection.cursor() as cursor:
        # pg_stat_activity can be transaction-snapshot cached.  Recovery may retry
        # cleanup on the same lifecycle-admin connection after the executor exits.
        cursor.execute("SELECT pg_catalog.pg_stat_clear_snapshot()")
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=%s",
            (executor_role,),
        )
        sessions = cursor.fetchone()
    if sessions is None or int(sessions[0]) != 0:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_SESSION_ACTIVE")
    memberships = _executor_memberships(connection, executor_role=executor_role)
    temporary = (
        authority,
        executor_role,
        lifecycle_admin,
        lifecycle_admin_superuser,
        False,
        False,
        True,
    )
    creator = (
        executor_role,
        lifecycle_admin,
        "",
        True,
        True,
        False,
        False,
    )
    for edge in memberships:
        if edge == temporary:
            continue
        if (
            not lifecycle_admin_superuser
            and edge[0] == creator[0]
            and edge[1] == creator[1]
            and edge[3:] == creator[3:]
        ):
            continue
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_MEMBERSHIP_UNSAFE")
    with connection.cursor() as cursor:
        if temporary in memberships:
            cursor.execute(
                sql.SQL("REVOKE {} FROM {}").format(
                    sql.Identifier(authority), sql.Identifier(executor_role)
                )
            )
        with _client_cursor(connection) as client_cursor:
            client_cursor.execute(
                sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(executor_role))
            )
        cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(executor_role)))
    if _executor_names(connection):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_TERMINAL_UNSAFE")
    connection.commit()


def provision_bootstrap_executor(
    connection: Connection[Any],
    *,
    executor_role: str,
    password: str,
    valid_until: datetime,
    authority: str = BOOTSTRAP_AUTHORITY,
    checkpoint: Callable[[str], None] | None = None,
    lifecycle_lock_held: bool = False,
) -> BootstrapExecutorLease:
    """Create a fresh bounded executor and its single SET-only delegation."""

    if not re.fullmatch(re.escape(BOOTSTRAP_EXECUTOR_PREFIX) + r"[a-z0-9]{8,24}", executor_role):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_NAME_INVALID")
    require_identifier(executor_role, field="bootstrap_executor")
    if not password:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_PASSWORD_MISSING")
    now = datetime.now(UTC)
    if valid_until <= now or valid_until > now + timedelta(minutes=10):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_WINDOW_INVALID")
    (
        authority,
        authority_oid,
        lifecycle_admin,
        lifecycle_admin_superuser,
    ) = provision_permanent_bootstrap_authority(
        connection,
        authority=authority,
        lifecycle_lock_held=lifecycle_lock_held,
    )
    stale = _executor_names(connection)
    if len(stale) > 1:
        raise ChronosProductionError("CHRONOS_MULTIPLE_BOOTSTRAP_EXECUTORS")
    if stale:
        if stale[0] == executor_role:
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_NAME_REUSE")
        cleanup_bootstrap_executor(
            connection,
            executor_role=stale[0],
            authority=authority,
            lifecycle_admin=lifecycle_admin,
            lifecycle_admin_superuser=lifecycle_admin_superuser,
        )
        _configure_transaction(connection)
    try:
        with _client_cursor(connection) as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1 "
                    "PASSWORD %s VALID UNTIL {}"
                ).format(
                    sql.Identifier(executor_role),
                    sql.Literal(valid_until.isoformat()),
                ),
                (password,),
            )
            cursor.execute(
                sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(executor_role)),
                (EXECUTOR_MARKER,),
            )
    except Exception:
        connection.rollback()
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_EXECUTOR_CREATE_FAILED") from None
    _assert_executor_catalog(connection, role=executor_role, require_live_window=True)
    connection.commit()
    if checkpoint is not None:
        checkpoint("executor_created")
    _configure_transaction(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT {} TO {} WITH SET TRUE, INHERIT FALSE, ADMIN FALSE").format(
                sql.Identifier(authority), sql.Identifier(executor_role)
            )
        )
    connection.commit()
    if checkpoint is not None:
        checkpoint("executor_granted")
    return BootstrapExecutorLease(
        authority=authority,
        authority_oid=authority_oid,
        executor_role=executor_role,
        lifecycle_admin=lifecycle_admin,
        lifecycle_admin_superuser=lifecycle_admin_superuser,
        valid_until=valid_until,
    )


def _bootstrap_context(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> tuple[str, str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT session_user,current_user")
        principals = cursor.fetchone()
        cursor.execute(
            "SELECT grantor.rolname,m.admin_option,m.inherit_option,m.set_option "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=%s AND member.rolname=session_user",
            (authority,),
        )
        edge = cursor.fetchall()
    if principals is None:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_SESSION_MISSING")
    executor_role = str(principals[0])
    if (
        str(principals[1]) != authority
        or not executor_role.startswith(BOOTSTRAP_EXECUTOR_PREFIX)
        or len(edge) != 1
        or bool(edge[0][1])
        or bool(edge[0][2])
        or not bool(edge[0][3])
    ):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_SET_ROLE_CONTEXT_UNSAFE")
    return executor_role, str(edge[0][0])


def assert_executor_before_set_role(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> tuple[str, str]:
    _configure_executor_session(connection)
    with connection.cursor() as cursor:
        cursor.execute("SELECT session_user,current_user")
        principals = cursor.fetchone()
    if principals is None or str(principals[0]) != str(principals[1]):
        raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_IDENTITY_UNSAFE")
    executor_role = str(principals[0])
    if not executor_role.startswith(BOOTSTRAP_EXECUTOR_PREFIX):
        raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_IDENTITY_UNSAFE")
    _assert_executor_catalog(connection, role=executor_role, require_live_window=True)
    memberships = _executor_memberships(connection, executor_role=executor_role)
    temporary = [edge for edge in memberships if edge[0] == authority and edge[1] == executor_role]
    if len(temporary) != 1:
        raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_PRIVILEGE_UNSAFE")
    lifecycle_admin = str(temporary[0][2])
    lifecycle_admin_superuser = bool(temporary[0][3])
    for edge in memberships:
        if edge == temporary[0]:
            continue
        if (
            not lifecycle_admin_superuser
            and edge[0] == executor_role
            and edge[1] == lifecycle_admin
            and edge[3:7] == (True, True, False, False)
        ):
            continue
        raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_PRIVILEGE_UNSAFE")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcreaterole,"
            "pg_catalog.pg_has_role(%s,%s,'SET'),"
            "pg_catalog.pg_has_role(%s,%s,'USAGE'),"
            "NOT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles g ON g.oid=m.roleid "
            "WHERE m.member=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s) "
            "AND g.rolname=ANY(%s)) "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (
                executor_role,
                authority,
                executor_role,
                authority,
                executor_role,
                list(GROUP_ROLES),
                executor_role,
            ),
        )
        state = cursor.fetchone()
    if (
        temporary[0][4:7] != (False, False, True)
        or state is None
        or bool(state[0])
        or not bool(state[1])
        or bool(state[2])
        or not bool(state[3])
    ):
        raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_PRIVILEGE_UNSAFE")
    _assert_executor_has_no_functional_privileges(connection, executor_role=executor_role)
    return executor_role, lifecycle_admin


def assert_executor_cannot_create_role(connection: Connection[Any], *, probe_role: str) -> None:
    """Execute the decisive negative control without leaving a catalog residue."""

    require_identifier(probe_role, field="executor_probe_role")
    assert_executor_before_set_role(connection)
    with connection.cursor() as cursor:
        cursor.execute("SAVEPOINT chronos_executor_pre_set_probe")
        try:
            cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(probe_role)))
        except InsufficientPrivilege as error:
            if error.sqlstate != "42501":
                raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_SQLSTATE_UNSAFE") from None
            cursor.execute("ROLLBACK TO SAVEPOINT chronos_executor_pre_set_probe")
            cursor.execute("RELEASE SAVEPOINT chronos_executor_pre_set_probe")
        else:
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(probe_role)))
            cursor.execute("RELEASE SAVEPOINT chronos_executor_pre_set_probe")
            raise ChronosProductionError("CHRONOS_EXECUTOR_PRE_SET_CREATE_ROLE_SUCCEEDED")


def set_permanent_bootstrap_authority(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> tuple[str, str]:
    executor_role, lifecycle_admin = assert_executor_before_set_role(
        connection, authority=authority
    )
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(authority)))
    assert_permanent_bootstrap_authority(connection, authority=authority)
    return executor_role, lifecycle_admin


def reset_permanent_bootstrap_authority(connection: Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("SELECT session_user,current_user")
        row = cursor.fetchone()
    if row is None or str(row[0]) != str(row[1]):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_RESET_ROLE_FAILED")


def assert_permanent_bootstrap_authority(
    connection: Connection[Any], *, authority: str = BOOTSTRAP_AUTHORITY
) -> str:
    """Pure assertion: the permanent authority has always been NOLOGIN."""

    executor_role, _lifecycle_admin = _bootstrap_context(connection, authority=authority)
    _assert_permanent_authority_catalog(connection, authority=authority)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT a.rolcreaterole,e.rolcreaterole "
            "FROM pg_catalog.pg_roles a,pg_catalog.pg_roles e "
            "WHERE a.rolname=%s AND e.rolname=%s",
            (authority, executor_role),
        )
        row = cursor.fetchone()
    if row is None or not bool(row[0]) or bool(row[1]):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_EFFECT_UNSAFE")
    return authority


def _client_cursor(connection: Connection[Any]) -> ClientCursor[Any]:
    """Bind utility-statement parameters safely on the client side."""

    return ClientCursor(connection)


def _role_state(connection: Connection[Any], role: str) -> tuple[Any, ...] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
            "rolcreaterole,rolreplication,rolbypassrls,rolconfig,"
            "pg_catalog.shobj_description(oid,'pg_authid') "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        )
        return cursor.fetchone()


def _assert_role_state(
    connection: Connection[Any],
    role: str,
    *,
    can_login: bool,
    inherit: bool,
    marker: str,
) -> None:
    row = _role_state(connection, role)
    if row is None:
        raise ChronosProductionError("CHRONOS_ROLE_MISSING")
    if (
        bool(row[1]) is not can_login
        or bool(row[2]) is not inherit
        or any(bool(value) for value in row[3:8])
        or row[8] is not None
        or str(row[9]) != marker
    ):
        raise ChronosProductionError("CHRONOS_ROLE_STATE_UNSAFE")


def _assert_role_has_no_smuggled_state(connection: Connection[Any], role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_db_role_setting s "
            "JOIN pg_catalog.pg_roles r ON r.oid=s.setrole WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_database d "
            "JOIN pg_catalog.pg_roles r ON r.oid=d.datdba WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n "
            "JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_roles r ON r.oid=c.relowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_roles r ON r.oid=p.proowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_type t "
            "JOIN pg_catalog.pg_roles r ON r.oid=t.typowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_database d, "
            "LATERAL pg_catalog.aclexplode(d.datacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n, "
            "LATERAL pg_catalog.aclexplode(n.nspacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_class c, "
            "LATERAL pg_catalog.aclexplode(c.relacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_proc p, "
            "LATERAL pg_catalog.aclexplode(p.proacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_default_acl d, "
            "LATERAL pg_catalog.aclexplode(d.defaclacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee WHERE r.rolname=%s)",
            (role,) * 11,
        )
        row = cursor.fetchone()
    if row is None or bool(row[0]) or _direct_acl_rows(connection, role):
        raise ChronosProductionError("CHRONOS_GROUP_ROLE_SMUGGLED_PRIVILEGE")


def _assert_role_has_no_ownership_or_settings(connection: Connection[Any], role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_db_role_setting s "
            "JOIN pg_catalog.pg_roles r ON r.oid=s.setrole WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_database d "
            "JOIN pg_catalog.pg_roles r ON r.oid=d.datdba WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n "
            "JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_roles r ON r.oid=c.relowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_roles r ON r.oid=p.proowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_type t "
            "JOIN pg_catalog.pg_roles r ON r.oid=t.typowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_default_acl d "
            "JOIN pg_catalog.pg_roles r ON r.oid=d.defaclrole WHERE r.rolname=%s)",
            (role,) * 7,
        )
        row = cursor.fetchone()
    if row is None or bool(row[0]):
        raise ChronosProductionError("CHRONOS_ROLE_OWNERSHIP_OR_SETTING_UNSAFE")


def _direct_acl_rows(
    connection: Connection[Any], role: str
) -> set[tuple[str, str, str, str, bool]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT object_kind,object_name,privilege_type,grantor_role,is_grantable "
            "FROM ("
            "SELECT 'database' AS object_kind,d.datname::text AS object_name,"
            "a.privilege_type,g.rolname AS grantor_role,a.is_grantable "
            "FROM pg_catalog.pg_database d CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(d.datacl) a JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE r.rolname=%s UNION ALL "
            "SELECT 'schema',n.nspname,a.privilege_type,g.rolname,a.is_grantable "
            "FROM pg_catalog.pg_namespace n CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(n.nspacl) a JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE r.rolname=%s UNION ALL "
            "SELECT 'relation',n.nspname||'.'||c.relname,a.privilege_type,"
            "g.rolname,a.is_grantable FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
            "JOIN pg_catalog.pg_roles g ON g.oid=a.grantor WHERE r.rolname=%s "
            "AND a.grantee<>c.relowner "
            "UNION ALL SELECT 'function',n.nspname||'.'||p.proname||'('||"
            "pg_catalog.oidvectortypes(p.proargtypes)||')',"
            "a.privilege_type,g.rolname,a.is_grantable FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(coalesce("
            "p.proacl,pg_catalog.acldefault('f',p.proowner))) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
            "JOIN pg_catalog.pg_roles g ON g.oid=a.grantor WHERE r.rolname=%s "
            "AND a.grantee<>p.proowner "
            "UNION ALL SELECT 'column',n.nspname||'.'||c.relname||'.'||att.attname,"
            "a.privilege_type,g.rolname,a.is_grantable FROM pg_catalog.pg_attribute att "
            "JOIN pg_catalog.pg_class c ON c.oid=att.attrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(att.attacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
            "JOIN pg_catalog.pg_roles g ON g.oid=a.grantor WHERE r.rolname=%s "
            "AND a.grantee<>c.relowner "
            "UNION ALL SELECT 'type',n.nspname||'.'||t.typname,a.privilege_type,"
            "g.rolname,a.is_grantable FROM pg_catalog.pg_type t "
            "JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(t.typacl) a "
            "JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
            "JOIN pg_catalog.pg_roles g ON g.oid=a.grantor WHERE r.rolname=%s "
            "AND a.grantee<>t.typowner "
            "UNION ALL SELECT 'default_acl',coalesce(n.nspname,'*')||':'||"
            "d.defaclobjtype::text,"
            "a.privilege_type,g.rolname,a.is_grantable "
            "FROM pg_catalog.pg_default_acl d LEFT JOIN pg_catalog.pg_namespace n "
            "ON n.oid=d.defaclnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(d.defaclacl) a JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE r.rolname=%s) acl ORDER BY 1,2,3,4,5",
            (role,) * 7,
        )
        rows = cursor.fetchall()
    return {(str(row[0]), str(row[1]), str(row[2]), str(row[3]), bool(row[4])) for row in rows}


def _assert_authority_bootstrap_acl(
    connection: Connection[Any], *, authority: str, lifecycle_admin: str
) -> None:
    observed = _direct_acl_rows(connection, authority)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.rolname FROM pg_catalog.pg_namespace n "
            "JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner "
            "WHERE n.nspname='public'"
        )
        owner = cursor.fetchone()
    if owner is None:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_ACL_UNSAFE")
    schema_grantors = {lifecycle_admin, str(owner[0])}
    expected_shape = {
        ("schema", "public", "CREATE"),
        ("schema", "public", "USAGE"),
        *{
            (
                "relation",
                "public.alembic_version",
                privilege,
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
        },
    }
    if (
        {(kind, name, privilege) for kind, name, privilege, _, _ in observed} != expected_shape
        or any(not grantable for *_, grantable in observed)
        or any(
            (kind == "schema" and grantor not in schema_grantors)
            or (kind == "relation" and grantor != lifecycle_admin)
            for kind, _, _, grantor, _ in observed
        )
    ):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_AUTHORITY_ACL_UNSAFE")


def _chronos_object_acl_rows(
    connection: Connection[Any], *, migrator_role: str
) -> set[tuple[str, str, str, str, str, bool]]:
    groups = list(GROUP_ROLES)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT object_kind,object_name,grantee_role,grantor_role,"
            "privilege_type,is_grantable FROM ("
            "SELECT 'schema' AS object_kind,n.nspname::text AS object_name,"
            "coalesce(r.rolname,'PUBLIC') AS grantee_role,g.rolname AS grantor_role,"
            "a.privilege_type,a.is_grantable FROM pg_catalog.pg_namespace n "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) a "
            "LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee "
            "JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE n.nspname='public' AND (r.rolname=ANY(%s) OR g.rolname=%s) "
            "UNION ALL SELECT 'relation',n.nspname||'.'||c.relname,"
            "coalesce(r.rolname,'PUBLIC'),g.rolname,a.privilege_type,a.is_grantable "
            "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(c.relacl) a LEFT JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE n.nspname='public' AND ("
            "c.relname=ANY(%s) AND a.grantee<>c.relowner OR "
            "c.relname='alembic_version' AND (r.rolname=ANY(%s) OR g.rolname=%s)) "
            "UNION ALL SELECT 'function',n.nspname||'.'||p.proname||'('||"
            "pg_catalog.oidvectortypes(p.proargtypes)||')',"
            "coalesce(r.rolname,'PUBLIC'),g.rolname,a.privilege_type,a.is_grantable "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
            "ON n.oid=p.pronamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(coalesce(p.proacl,"
            "pg_catalog.acldefault('f',p.proowner))) a "
            "LEFT JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE n.nspname='public' AND p.proname=ANY(%s) "
            "AND a.grantee<>p.proowner "
            "UNION ALL SELECT 'column',n.nspname||'.'||c.relname||'.'||att.attname,"
            "coalesce(r.rolname,'PUBLIC'),g.rolname,a.privilege_type,a.is_grantable "
            "FROM pg_catalog.pg_attribute att JOIN pg_catalog.pg_class c "
            "ON c.oid=att.attrelid JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(att.attacl) a LEFT JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE n.nspname='public' AND c.relname=ANY(%s) "
            "UNION ALL SELECT 'type',n.nspname||'.'||t.typname,"
            "coalesce(r.rolname,'PUBLIC'),g.rolname,a.privilege_type,a.is_grantable "
            "FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n "
            "ON n.oid=t.typnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(t.typacl) a LEFT JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE n.nspname='public' AND t.typname=ANY(%s) "
            "UNION ALL SELECT 'default_acl',coalesce(n.nspname,'*')||':'||"
            "d.defaclobjtype::text,"
            "coalesce(r.rolname,'PUBLIC'),g.rolname,a.privilege_type,a.is_grantable "
            "FROM pg_catalog.pg_default_acl d LEFT JOIN pg_catalog.pg_namespace n "
            "ON n.oid=d.defaclnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(d.defaclacl) a LEFT JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE r.rolname=ANY(%s) OR g.rolname=%s) observed "
            "ORDER BY 1,2,3,4,5,6",
            (
                groups,
                migrator_role,
                list(CHRONOS_RELATIONS),
                groups,
                migrator_role,
                list(CHRONOS_FUNCTION_SIGNATURES),
                list(CHRONOS_RELATIONS),
                list(CHRONOS_RELATIONS),
                groups,
                migrator_role,
            ),
        )
        rows = cursor.fetchall()
    return {
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            bool(row[5]),
        )
        for row in rows
    }


def _assert_migrator_acl(
    connection: Connection[Any],
    *,
    role: str,
    complete: bool,
    dormant: bool = False,
    grantor: str | None = None,
) -> None:
    bootstrap_owner = grantor or assert_permanent_bootstrap_authority(connection)
    base = {
        ("schema", "public", "USAGE", bootstrap_owner, True),
        ("relation", "public.alembic_version", "SELECT", bootstrap_owner, True),
    }
    active = {
        ("schema", "public", "CREATE", bootstrap_owner, False),
        *{
            (
                "relation",
                "public.alembic_version",
                privilege,
                bootstrap_owner,
                False,
            )
            for privilege in ("INSERT", "UPDATE", "DELETE")
        },
    }
    observed = _direct_acl_rows(connection, role)
    if (
        (dormant and observed != base)
        or (not dormant and complete and observed != base | active)
        or (not dormant and not complete and not observed <= base | active)
    ):
        raise ChronosProductionError("CHRONOS_MIGRATOR_ACL_UNSAFE")


def _assert_migrator_ownership(connection: Connection[Any], *, role: str, revision: str) -> None:
    with connection.cursor() as cursor:
        allowed_relations = (
            CHRONOS_RELATIONS
            if revision == "0015_data_torrent_opportunity"
            else CHRONOS_BASE_RELATIONS
            if revision == "0014_chronos_control_plane_v2"
            else ()
        )
        cursor.execute(
            "SELECT EXISTS ("
            "SELECT 1 FROM pg_catalog.pg_db_role_setting s JOIN pg_catalog.pg_roles r "
            "ON r.oid=s.setrole WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_database d JOIN pg_catalog.pg_roles r "
            "ON r.oid=d.datdba WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_namespace n JOIN pg_catalog.pg_roles r "
            "ON r.oid=n.nspowner WHERE r.rolname=%s "
            "UNION ALL SELECT 1 FROM pg_catalog.pg_default_acl d "
            "JOIN pg_catalog.pg_roles r ON r.oid=d.defaclrole WHERE r.rolname=%s)",
            (role,) * 4,
        )
        base_unsafe = cursor.fetchone()
        cursor.execute(
            "WITH base AS (SELECT c.oid FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname=ANY(%s)), "
            "toast AS (SELECT c.reltoastrelid AS oid FROM pg_catalog.pg_class c "
            "WHERE c.oid IN (SELECT oid FROM base) AND c.reltoastrelid<>0), "
            "allowed AS (SELECT oid FROM base UNION SELECT indexrelid "
            "FROM pg_catalog.pg_index WHERE indrelid IN (SELECT oid FROM base) "
            "UNION SELECT oid FROM toast UNION SELECT indexrelid "
            "FROM pg_catalog.pg_index WHERE indrelid IN (SELECT oid FROM toast)) "
            "SELECT c.oid FROM pg_catalog.pg_class c WHERE "
            "(c.relowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s) "
            "AND c.oid NOT IN (SELECT oid FROM allowed)) OR "
            "(c.oid IN (SELECT oid FROM allowed) AND c.relowner<>"
            "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s))",
            (
                list(allowed_relations),
                role,
                role,
            ),
        )
        unexpected_classes = cursor.fetchall()
        cursor.execute(
            "SELECT n.nspname,p.proname,"
            "pg_catalog.oidvectortypes(p.proargtypes) "
            "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n "
            "ON n.oid=p.pronamespace JOIN pg_catalog.pg_roles r "
            "ON r.oid=p.proowner WHERE r.rolname=%s ORDER BY 1,2,3",
            (role,),
        )
        owned_functions = {(str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()}
        cursor.execute(
            "WITH base AS (SELECT c.oid FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname=ANY(%s)), "
            "toast AS (SELECT c.reltoastrelid AS oid FROM pg_catalog.pg_class c "
            "WHERE c.oid IN (SELECT oid FROM base) AND c.reltoastrelid<>0), "
            "allowed_rel AS (SELECT oid FROM base UNION SELECT oid FROM toast), "
            "composite AS (SELECT t.oid FROM pg_catalog.pg_type t "
            "WHERE t.typrelid IN (SELECT oid FROM allowed_rel)), "
            "allowed_types AS (SELECT oid FROM composite UNION SELECT t.oid "
            "FROM pg_catalog.pg_type t WHERE t.typelem IN (SELECT oid FROM composite)) "
            "SELECT t.oid FROM pg_catalog.pg_type t WHERE "
            "(t.typowner=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s) "
            "AND t.oid NOT IN (SELECT oid FROM allowed_types)) OR "
            "(t.oid IN (SELECT oid FROM allowed_types) AND t.typowner<>"
            "(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s))",
            (
                list(allowed_relations),
                role,
                role,
            ),
        )
        unexpected_types = cursor.fetchall()
    expected_signatures = (
        CHRONOS_FUNCTION_SIGNATURES
        if revision == "0015_data_torrent_opportunity"
        else CHRONOS_BASE_FUNCTION_SIGNATURES
        if revision == "0014_chronos_control_plane_v2"
        else {}
    )
    expected_functions = {
        ("public", name, signature) for name, signature in expected_signatures.items()
    }
    if (
        base_unsafe is None
        or bool(base_unsafe[0])
        or unexpected_classes
        or unexpected_types
        or owned_functions != expected_functions
    ):
        raise ChronosProductionError("CHRONOS_MIGRATOR_OWNERSHIP_UNSAFE")


def assert_post_migration_role_state(
    connection: Connection[Any],
    *,
    migrator_role: str,
    bootstrap_owner: str | None = None,
) -> None:
    """Require the exact 0015 role attributes, ownership and object ACLs."""

    migrator_state = _role_state(connection, migrator_role)
    if migrator_state is None:
        raise ChronosProductionError("CHRONOS_MIGRATOR_MISSING")
    _assert_role_state(
        connection,
        migrator_role,
        can_login=bool(migrator_state[1]),
        inherit=False,
        marker=MIGRATOR_MARKER,
    )
    if bool(migrator_state[1]):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolvaliduntil IS NOT NULL,"
                "rolvaliduntil<=clock_timestamp()+interval '6 minutes' "
                "FROM pg_catalog.pg_roles WHERE rolname=%s",
                (migrator_role,),
            )
            window = cursor.fetchone()
        if window is None or not bool(window[0]) or not bool(window[1]):
            raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_UNSAFE")
    for role in GROUP_ROLES:
        _assert_role_state(connection, role, can_login=False, inherit=True, marker=ROLE_MARKER)
        _assert_role_has_no_ownership_or_settings(connection, role)
    observed_acl: set[tuple[str, str, str, str, bool]] = set()
    for role in GROUP_ROLES:
        observed_acl.update(_direct_acl_rows(connection, role))
    # Include the grantee in the comparison by checking each role independently.
    per_role = {role: _direct_acl_rows(connection, role) for role in GROUP_ROLES}
    exact = {
        "chronos_authority_executor": {
            ("schema", "public", "USAGE", migrator_role, False),
            (
                "function",
                "public.chronos_issue_effect_authority("
                + CHRONOS_FUNCTION_SIGNATURES["chronos_issue_effect_authority"]
                + ")",
                "EXECUTE",
                migrator_role,
                False,
            ),
        },
        "chronos_runtime_writer": {
            ("schema", "public", "USAGE", migrator_role, False),
            *{
                (
                    "function",
                    f"public.{name}({CHRONOS_FUNCTION_SIGNATURES[name]})",
                    "EXECUTE",
                    migrator_role,
                    False,
                )
                for name in (
                    "chronos_claim_effect_authority",
                    "chronos_append_effect_event",
                    "chronos_get_effect_state",
                    "chronos_claim_opportunity",
                    "chronos_reserve_torrent_external_effect",
                    "chronos_append_torrent_external_effect",
                    "chronos_record_torrent_batch",
                )
            },
        },
        "chronos_reader": {
            ("schema", "public", "USAGE", migrator_role, False),
            (
                "relation",
                "public.alembic_version",
                "SELECT",
                migrator_role,
                False,
            ),
            (
                "relation",
                "public.chronos_effect_accounting",
                "SELECT",
                migrator_role,
                False,
            ),
            (
                "function",
                "public.chronos_get_effect_state("
                + CHRONOS_FUNCTION_SIGNATURES["chronos_get_effect_state"]
                + ")",
                "EXECUTE",
                migrator_role,
                False,
            ),
            *{
                (
                    "relation",
                    f"public.{name}",
                    "SELECT",
                    migrator_role,
                    False,
                )
                for name in (
                    "chronos_opportunity_claim_audit",
                    "chronos_torrent_batch_audit",
                    "chronos_torrent_external_effect_audit",
                )
            },
        },
        "chronos_test_writer": set(),
    }
    if per_role != exact or observed_acl != set().union(*exact.values()):
        raise ChronosProductionError("CHRONOS_POST_MIGRATION_ACL_UNSAFE")
    expected_global: set[tuple[str, str, str, str, str, bool]] = {
        (
            object_kind,
            object_name,
            grantee,
            migrator_role,
            privilege,
            False,
        )
        for grantee, grants in exact.items()
        for object_kind, object_name, privilege, _grantor, _grantable in grants
    }
    if _chronos_object_acl_rows(connection, migrator_role=migrator_role) != expected_global:
        raise ChronosProductionError("CHRONOS_GLOBAL_OBJECT_ACL_UNSAFE")
    _assert_migrator_acl(
        connection,
        role=migrator_role,
        complete=False,
        grantor=bootstrap_owner,
    )
    _assert_migrator_ownership(
        connection,
        role=migrator_role,
        revision="0015_data_torrent_opportunity",
    )


def _role_inventory(
    connection: Connection[Any],
    *,
    phase: str,
    bootstrap_owner: str,
    lifecycle_admin: str,
    executor_role: str | None,
    migrator_role: str | None,
    active_runtime: set[str],
) -> tuple[dict[str, Any], ...]:
    expected = (
        set(GROUP_ROLES)
        | active_runtime
        | {
            bootstrap_owner,
            lifecycle_admin,
        }
    )
    if executor_role is not None:
        expected.add(executor_role)
    if migrator_role is not None:
        expected.add(migrator_role)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
            "rolcreaterole,rolreplication,rolbypassrls,rolconnlimit,rolconfig,"
            "rolvaliduntil::text,"
            "pg_catalog.shobj_description(oid,'pg_authid') "
            "FROM pg_catalog.pg_roles WHERE rolname=ANY(%s) OR "
            "pg_catalog.shobj_description(oid,'pg_authid')=ANY(%s) "
            "ORDER BY rolname",
            (
                sorted(expected),
                [ROLE_MARKER, MIGRATOR_MARKER, AUTHORITY_MARKER, EXECUTOR_MARKER],
            ),
        )
        rows = cursor.fetchall()
    if {str(row[1]) for row in rows} != expected:
        raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_MISMATCH")
    inventory: list[dict[str, Any]] = []
    for row in rows:
        name = str(row[1])
        marker = None if row[12] is None else str(row[12])
        is_owner = name == bootstrap_owner
        is_lifecycle_admin = name == lifecycle_admin
        is_executor = name == executor_role
        is_group = name in GROUP_ROLES
        is_runtime = name in active_runtime
        is_migrator = name == migrator_role
        expected_marker = (
            AUTHORITY_MARKER
            if is_owner
            else EXECUTOR_MARKER
            if is_executor
            else None
            if is_lifecycle_admin
            else MIGRATOR_MARKER
            if is_migrator
            else ROLE_MARKER
        )
        unsafe_managed = not is_lifecycle_admin and any(
            bool(value) for value in (row[4], row[5], row[7], row[8])
        )
        if (
            unsafe_managed
            or (not is_lifecycle_admin and row[10] is not None)
            or (not is_lifecycle_admin and marker != expected_marker)
            or (not is_lifecycle_admin and bool(row[6]) is not is_owner)
            or (is_group and (bool(row[2]) or not bool(row[3])))
            or (is_runtime and (not bool(row[2]) or bool(row[3])))
            or (is_migrator and bool(row[3]))
            or (is_owner and bool(row[3]))
            or (is_owner and bool(row[2]))
            or (is_executor and (not bool(row[2]) or bool(row[3]) or int(row[9]) != 1))
            or (is_lifecycle_admin and (not bool(row[2]) or not (bool(row[4]) or bool(row[6]))))
        ):
            raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_UNSAFE")
        inventory.append(
            {
                "oid": int(row[0]),
                "role": name,
                "can_login": bool(row[2]),
                "inherit": bool(row[3]),
                "createrole": bool(row[6]),
                "superuser": bool(row[4]),
                "valid_until": row[11],
                "marker": marker,
            }
        )
    return tuple(inventory)


def _membership_rows(
    connection: Connection[Any], names: Sequence[str], bootstrap_owner: str
) -> list[dict[str, Any]]:
    scope = sorted(set(names) | {bootstrap_owner})
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT granted.rolname,member.rolname,grantor.rolname,"
            "grantor.rolsuper,m.admin_option,m.inherit_option,m.set_option,"
            "pg_catalog.pg_has_role(member.oid,granted.oid,'USAGE'),"
            "pg_catalog.pg_has_role(member.oid,granted.oid,'SET'),"
            "member.rolcanlogin,granted.rolcanlogin,member.rolinherit "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=ANY(%s) OR member.rolname=ANY(%s) "
            "OR member.rolname=%s OR granted.rolname=%s "
            "OR grantor.rolname=%s "
            "ORDER BY granted.rolname,member.rolname,grantor.rolname",
            (scope, scope, bootstrap_owner, bootstrap_owner, bootstrap_owner),
        )
        rows = cursor.fetchall()
    return [
        {
            "granted_role": str(row[0]),
            "member_role": str(row[1]),
            "grantor_role": str(row[2]),
            "grantor_superuser": bool(row[3]),
            "admin_option": bool(row[4]),
            "inherit_option": bool(row[5]),
            "set_option": bool(row[6]),
            "runtime_usage": bool(row[7]),
            "runtime_set": bool(row[8]),
            "member_authenticatable": bool(row[9]),
            "granted_authenticatable": bool(row[10]),
            "member_inherit": bool(row[11]),
        }
        for row in rows
    ]


def _is_expected_neon_platform_edge(
    row: Mapping[str, Any],
    *,
    lifecycle_admin: str,
    lifecycle_admin_superuser: bool,
    lifecycle_admin_inherit: bool,
) -> bool:
    """Recognize the one provider-managed membership that Neon actors require."""

    return bool(
        row["granted_role"] == "neon_superuser"
        and row["member_role"] == lifecycle_admin
        and row["grantor_superuser"] is True
        and not row["granted_authenticatable"]
        and row["member_authenticatable"]
        and not row["admin_option"]
        and row["inherit_option"] is lifecycle_admin_inherit
        and row["set_option"]
        and row["runtime_set"]
        and row["runtime_usage"] is (lifecycle_admin_superuser or lifecycle_admin_inherit)
        and row["member_inherit"] is lifecycle_admin_inherit
    )


def audit_role_edges(
    connection: Connection[Any],
    *,
    phase: str,
    bootstrap_owner: str,
    lifecycle_admin: str | None = None,
    executor_role: str | None = None,
    migrator_role: str | None = None,
    pinned_system_grantor: str | None = None,
    runtime_roles: Sequence[str] | None = None,
) -> RoleEdgeAudit:
    """Classify the complete bidirectional lifecycle membership graph."""

    if phase not in {
        "groups",
        "migrator",
        "runtime_partial",
        "final",
        "terminal",
    }:
        raise ChronosProductionError("CHRONOS_ROLE_EDGE_PHASE_INVALID")
    active_groups = set(GROUP_ROLES)
    if phase in {"final", "terminal"}:
        active_runtime = set(RUNTIME_ROLE_GROUPS)
    elif phase == "runtime_partial":
        active_runtime = set(runtime_roles or ())
        if not active_runtime < set(RUNTIME_ROLE_GROUPS):
            raise ChronosProductionError("CHRONOS_RUNTIME_PARTIAL_SET_INVALID")
    else:
        active_runtime = set()
    active_migrator = {migrator_role} if migrator_role is not None else set()
    if phase != "terminal" and (lifecycle_admin is None or executor_role is None):
        discovered_executor, discovered_admin = _bootstrap_context(
            connection, authority=bootstrap_owner
        )
        executor_role = executor_role or discovered_executor
        lifecycle_admin = lifecycle_admin or discovered_admin
    if lifecycle_admin is None:
        raise ChronosProductionError("CHRONOS_LIFECYCLE_ADMIN_MISSING")
    _assert_permanent_authority_catalog(connection, authority=bootstrap_owner)
    _assert_authority_bootstrap_acl(
        connection,
        authority=bootstrap_owner,
        lifecycle_admin=lifecycle_admin,
    )
    if executor_role is not None:
        _assert_executor_catalog(connection, role=executor_role, require_live_window=True)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolsuper,rolinherit,rolcanlogin FROM pg_catalog.pg_roles WHERE rolname=%s",
            (lifecycle_admin,),
        )
        lifecycle_state = cursor.fetchone()
    if lifecycle_state is None or not bool(lifecycle_state[2]):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_ADMIN_MISSING")
    lifecycle_admin_superuser = bool(lifecycle_state[0])
    lifecycle_admin_inherit = bool(lifecycle_state[1])
    names = sorted(
        active_groups
        | active_runtime
        | active_migrator
        | {lifecycle_admin}
        | ({executor_role} if executor_role is not None else set())
    )
    inventory = _role_inventory(
        connection,
        phase=phase,
        bootstrap_owner=bootstrap_owner,
        lifecycle_admin=lifecycle_admin,
        executor_role=executor_role,
        migrator_role=migrator_role,
        active_runtime=active_runtime,
    )
    rows = _membership_rows(connection, names, bootstrap_owner)

    expected_admin_roles = active_groups | active_runtime | active_migrator
    candidates = {
        row["grantor_role"]
        for row in rows
        if (
            (row["member_role"] == bootstrap_owner and row["granted_role"] in expected_admin_roles)
            or (
                not lifecycle_admin_superuser
                and row["member_role"] == lifecycle_admin
                and row["granted_role"]
                in {
                    bootstrap_owner,
                    *({executor_role} if executor_role is not None else set()),
                }
            )
        )
        and row["grantor_superuser"]
        and row["admin_option"]
        and not row["inherit_option"]
        and not row["set_option"]
    }
    if pinned_system_grantor is not None:
        candidates.add(pinned_system_grantor)
    if len(candidates) != 1:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_GRANTOR_MISMATCH")
    system_grantor = next(iter(candidates))

    classified: list[dict[str, Any]] = []
    forbidden = 0
    runtime_effective_bootstrap = 0
    migrator_runtime = 0
    for row in rows:
        classification = "FORBIDDEN_MEMBERSHIP"
        reason = "edge is outside the exact lifecycle allowlist"
        is_functional = (
            phase in {"final", "terminal", "runtime_partial"}
            and RUNTIME_ROLE_GROUPS.get(row["member_role"]) == row["granted_role"]
            and row["grantor_role"] == bootstrap_owner
            and not row["grantor_superuser"]
            and not row["admin_option"]
            and row["inherit_option"]
            and not row["set_option"]
        )
        is_migrator_admin = (
            migrator_role is not None
            and row["granted_role"] == migrator_role
            and row["member_role"] == bootstrap_owner
            and row["grantor_role"] == system_grantor
            and row["grantor_superuser"]
            and row["admin_option"]
            and not row["inherit_option"]
            and not row["set_option"]
        )
        is_bootstrap_admin = (
            row["granted_role"] in (active_groups | active_runtime)
            and row["member_role"] == bootstrap_owner
            and row["grantor_role"] == system_grantor
            and row["grantor_superuser"]
            and row["admin_option"]
            and not row["inherit_option"]
            and not row["set_option"]
        )
        is_external_authority_admin = (
            not lifecycle_admin_superuser
            and row["granted_role"] == bootstrap_owner
            and row["member_role"] == lifecycle_admin
            and row["grantor_role"] == system_grantor
            and row["grantor_superuser"]
            and row["admin_option"]
            and not row["inherit_option"]
            and not row["set_option"]
        )
        is_executor_admin = (
            executor_role is not None
            and not lifecycle_admin_superuser
            and row["granted_role"] == executor_role
            and row["member_role"] == lifecycle_admin
            and row["grantor_role"] == system_grantor
            and row["grantor_superuser"]
            and row["admin_option"]
            and not row["inherit_option"]
            and not row["set_option"]
        )
        is_executor_set = (
            executor_role is not None
            and row["granted_role"] == bootstrap_owner
            and row["member_role"] == executor_role
            and row["grantor_role"] == lifecycle_admin
            and row["admin_option"] is False
            and row["inherit_option"] is False
            and row["set_option"] is True
        )
        is_neon_platform = _is_expected_neon_platform_edge(
            row,
            lifecycle_admin=lifecycle_admin,
            lifecycle_admin_superuser=lifecycle_admin_superuser,
            lifecycle_admin_inherit=lifecycle_admin_inherit,
        )
        if is_functional:
            classification = "EXPECTED_RUNTIME_GROUP_EDGE"
            reason = "exact functional group inheritance without ADMIN or SET"
        elif is_migrator_admin:
            classification = "EXPECTED_MIGRATOR_ADMIN_EDGE"
            reason = "automatic PostgreSQL creator edge to offline bootstrap owner"
        elif is_bootstrap_admin:
            classification = "EXPECTED_BOOTSTRAP_ADMIN_EDGE"
            reason = "automatic PostgreSQL creator edge to offline bootstrap owner"
        elif is_external_authority_admin:
            classification = "EXPECTED_LIFECYCLE_ADMIN_AUTHORITY_EDGE"
            reason = "visible creator edge for non-superuser lifecycle admin"
        elif is_executor_admin:
            classification = "EXPECTED_EXECUTOR_ADMIN_EDGE"
            reason = "ephemeral creator edge for non-superuser lifecycle admin"
        elif is_executor_set:
            classification = "EXPECTED_EXECUTOR_SET_EDGE"
            reason = "temporary SET-only delegation to the NOLOGIN authority"
        elif is_neon_platform:
            classification = "EXPECTED_NEON_PLATFORM_EDGE"
            reason = "single provider-managed Neon actor membership"
        else:
            forbidden += 1
        runtime_effective = bool(row["runtime_usage"] or row["runtime_set"])
        if (is_bootstrap_admin or is_migrator_admin) and runtime_effective:
            runtime_effective_bootstrap += 1
        if migrator_role is not None and (
            (row["granted_role"] == migrator_role and row["member_role"] in active_runtime)
            or (row["member_role"] == migrator_role and row["granted_role"] in active_runtime)
        ):
            migrator_runtime += 1
        classified.append(
            {
                **{key: value for key, value in row.items() if key != "runtime_usage"},
                "classification": classification,
                "runtime_effective": runtime_effective,
                "direct_member_authenticatable": bool(
                    row["admin_option"] and row["member_authenticatable"]
                ),
                "administratively_effective_via_set_role": bool(
                    row["admin_option"]
                    and (
                        row["member_authenticatable"]
                        or (executor_role is not None and row["member_role"] == bootstrap_owner)
                    )
                ),
                "reason": reason,
            }
        )

    actual_neon_platform = sum(
        edge["classification"] == "EXPECTED_NEON_PLATFORM_EDGE" for edge in classified
    )
    expected_neon_platform = 1 if actual_neon_platform == 1 else 0
    expected_count = (
        len(active_groups)
        + len(active_migrator)
        + 2 * len(active_runtime)
        + (0 if lifecycle_admin_superuser else 1)
        + (0 if executor_role is None else 1 + (0 if lifecycle_admin_superuser else 1))
        + expected_neon_platform
    )
    expected_functional = len(active_runtime)
    actual_functional = sum(
        edge["classification"] == "EXPECTED_RUNTIME_GROUP_EDGE" for edge in classified
    )
    expected_external = 0 if lifecycle_admin_superuser else 1
    actual_external = sum(
        edge["classification"] == "EXPECTED_LIFECYCLE_ADMIN_AUTHORITY_EDGE" for edge in classified
    )
    expected_executor = 0 if executor_role is None else 1
    actual_executor = sum(
        edge["classification"] == "EXPECTED_EXECUTOR_SET_EDGE" for edge in classified
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FILTER (WHERE "
            "pg_catalog.pg_has_role(r.rolname,%s,'USAGE') OR "
            "pg_catalog.pg_has_role(r.rolname,%s,'SET')),"
            "count(*) FILTER (WHERE "
            "pg_catalog.pg_has_role(r.rolname,%s,'USAGE') OR "
            "pg_catalog.pg_has_role(r.rolname,%s,'SET')) "
            "FROM pg_catalog.pg_roles r WHERE r.rolname=ANY(%s)",
            (
                bootstrap_owner,
                bootstrap_owner,
                lifecycle_admin,
                lifecycle_admin,
                sorted(active_runtime),
            ),
        )
        path_counts = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname LIKE %s",
            (BOOTSTRAP_EXECUTOR_PREFIX + "%",),
        )
        executor_roles = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles g ON g.oid=m.roleid "
            "JOIN pg_catalog.pg_roles u ON u.oid=m.member "
            "WHERE g.rolname LIKE %s OR u.rolname LIKE %s",
            (BOOTSTRAP_EXECUTOR_PREFIX + "%", BOOTSTRAP_EXECUTOR_PREFIX + "%"),
        )
        executor_memberships = cursor.fetchone()
        cursor.execute(
            "WITH RECURSIVE platform AS (SELECT oid FROM pg_catalog.pg_roles "
            "WHERE rolname='neon_superuser'), descendants(member) AS ("
            "SELECT membership.member FROM pg_catalog.pg_auth_members membership "
            "JOIN platform ON platform.oid=membership.roleid UNION SELECT "
            "nested.member FROM pg_catalog.pg_auth_members nested "
            "JOIN descendants prior ON nested.roleid=prior.member) "
            "SELECT (SELECT count(*) FROM descendants),"
            "(SELECT count(*) FROM descendants JOIN pg_catalog.pg_roles role "
            "ON role.oid=descendants.member WHERE role.rolname=%s)",
            (lifecycle_admin,),
        )
        platform_descendants = cursor.fetchone()
    runtime_to_authority = 0 if path_counts is None else int(path_counts[0])
    runtime_to_lifecycle = 0 if path_counts is None else int(path_counts[1])
    executor_role_count = 0 if executor_roles is None else int(executor_roles[0])
    executor_membership_count = 0 if executor_memberships is None else int(executor_memberships[0])
    neon_platform_descendant_count = (
        0 if platform_descendants is None else int(platform_descendants[0])
    )
    neon_actor_descendant_count = (
        0 if platform_descendants is None else int(platform_descendants[1])
    )
    if (
        len(classified) != expected_count
        or actual_functional != expected_functional
        or actual_external != expected_external
        or actual_executor != expected_executor
        or actual_neon_platform not in {0, 1}
        or neon_platform_descendant_count != actual_neon_platform
        or neon_actor_descendant_count != actual_neon_platform
        or forbidden
        or runtime_effective_bootstrap
        or migrator_runtime
        or runtime_to_authority
        or runtime_to_lifecycle
        or executor_role_count != (0 if executor_role is None else 1)
        or executor_membership_count
        != (0 if executor_role is None else 1 + (0 if lifecycle_admin_superuser else 1))
    ):
        raise ChronosProductionError("CHRONOS_ROLE_EDGE_AUDIT_FAILED")
    return RoleEdgeAudit(
        phase=phase,
        bootstrap_owner=bootstrap_owner,
        lifecycle_admin=lifecycle_admin,
        lifecycle_admin_superuser=lifecycle_admin_superuser,
        executor_role=executor_role,
        bootstrap_system_grantor=system_grantor,
        migrator_role=migrator_role,
        role_inventory=inventory,
        edges=tuple(classified),
        forbidden_edge_count=forbidden,
        runtime_effective_bootstrap_edge_count=runtime_effective_bootstrap,
        migrator_runtime_edge_count=migrator_runtime,
        runtime_to_authority_path_count=runtime_to_authority,
        runtime_to_lifecycle_admin_path_count=runtime_to_lifecycle,
        executor_role_count=executor_role_count,
        executor_membership_count=executor_membership_count,
        neon_platform_edge_count=actual_neon_platform,
        neon_platform_descendant_count=neon_platform_descendant_count,
    )


def provision_chronos_group_roles(
    connection: Connection[Any],
    *,
    migrator_role: str | None = None,
) -> RoleEdgeAudit:
    """Create or adopt exact Chronos NOLOGIN groups as the bootstrap owner."""

    _configure_transaction(connection)
    bootstrap_owner = assert_permanent_bootstrap_authority(connection)
    with connection.cursor() as cursor:
        for role in GROUP_ROLES:
            state = _role_state(connection, role)
            if state is None:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN INHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role))
                )
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(role)),
                        (ROLE_MARKER,),
                    )
            _assert_role_state(
                connection,
                role,
                can_login=False,
                inherit=True,
                marker=ROLE_MARKER,
            )
            _assert_role_has_no_smuggled_state(connection, role)
    existing_migrator = (
        migrator_role
        if migrator_role is not None and _role_state(connection, migrator_role) is not None
        else None
    )
    existing_runtime = {
        role for role in RUNTIME_ROLE_GROUPS if _role_state(connection, role) is not None
    }
    phase = (
        "final"
        if len(existing_runtime) == len(RUNTIME_ROLE_GROUPS)
        else "runtime_partial"
        if existing_runtime
        else "migrator"
        if existing_migrator is not None
        else "groups"
    )
    audit = audit_role_edges(
        connection,
        phase=phase,
        bootstrap_owner=bootstrap_owner,
        migrator_role=existing_migrator,
        runtime_roles=sorted(existing_runtime),
    )
    connection.commit()
    return audit


def provision_migrator(
    connection: Connection[Any],
    *,
    role: str,
    password: str,
    valid_until: datetime,
    pinned_system_grantor: str,
    audit_phase: str = "migrator",
    runtime_roles: Sequence[str] | None = None,
) -> RoleEdgeAudit:
    """Create or re-enable the persistent migrator as a bounded LOGIN."""

    require_identifier(role, field="migrator_role")
    if not password:
        raise ChronosProductionError("CHRONOS_MIGRATOR_PASSWORD_MISSING")
    now = datetime.now(UTC)
    if valid_until <= now or valid_until > now + timedelta(minutes=6):
        raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_INVALID")
    _configure_transaction(connection)
    bootstrap_owner = assert_permanent_bootstrap_authority(connection)
    _assert_no_role_sessions(
        connection,
        role=role,
        error_code="CHRONOS_MIGRATOR_SESSION_ACTIVE",
    )
    with connection.cursor() as cursor:
        state = _role_state(connection, role)
        if state is None:
            try:
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s "
                            "VALID UNTIL {}"
                        ).format(
                            sql.Identifier(role),
                            sql.Literal(valid_until.isoformat()),
                        ),
                        (password,),
                    )
                    client_cursor.execute(
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(role)),
                        (MIGRATOR_MARKER,),
                    )
            except Exception:
                connection.rollback()
                raise ChronosProductionError("CHRONOS_MIGRATOR_CREATE_FAILED") from None
        else:
            _assert_role_state(
                connection,
                role,
                can_login=bool(state[1]),
                inherit=False,
                marker=MIGRATOR_MARKER,
            )
            if bool(state[1]):
                raise ChronosProductionError("CHRONOS_MIGRATOR_MUST_BE_DISABLED")
            cursor.execute("SELECT version_num FROM public.alembic_version")
            revision_row = cursor.fetchone()
            if revision_row is None:
                raise ChronosProductionError("CHRONOS_MIGRATOR_REVISION_MISSING")
            _assert_migrator_acl(connection, role=role, complete=False)
            _assert_migrator_ownership(connection, role=role, revision=str(revision_row[0]))
            try:
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL("ALTER ROLE {} LOGIN PASSWORD %s VALID UNTIL {}").format(
                            sql.Identifier(role),
                            sql.Literal(valid_until.isoformat()),
                        ),
                        (password,),
                    )
            except Exception:
                connection.rollback()
                raise ChronosProductionError("CHRONOS_MIGRATOR_REACTIVATION_FAILED") from None
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {} WITH GRANT OPTION").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON TABLE public.alembic_version TO {} WITH GRANT OPTION").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL("GRANT INSERT, UPDATE, DELETE ON TABLE public.alembic_version TO {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            "SELECT rolcreaterole FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        )
        row = cursor.fetchone()
        if row is None or bool(row[0]):
            raise ChronosProductionError("CHRONOS_MIGRATOR_CREATEROLE_FORBIDDEN")
        _assert_migrator_acl(connection, role=role, complete=True)
    audit = audit_role_edges(
        connection,
        phase=audit_phase,
        bootstrap_owner=bootstrap_owner,
        migrator_role=role,
        pinned_system_grantor=pinned_system_grantor,
        runtime_roles=runtime_roles,
    )
    connection.commit()
    return audit


def _assert_no_role_sessions(connection: Connection[Any], *, role: str, error_code: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.pg_stat_clear_snapshot()")
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=%s",
            (role,),
        )
        row = cursor.fetchone()
    if row is None or int(row[0]) != 0:
        raise ChronosProductionError(error_code)


def disable_migrator(connection: Connection[Any], *, role: str) -> None:
    """Remove temporary grants and authentication from the persistent migrator."""

    _configure_transaction(connection)
    bootstrap_owner = assert_permanent_bootstrap_authority(connection)
    _assert_no_role_sessions(
        connection,
        role=role,
        error_code="CHRONOS_MIGRATOR_SESSION_ACTIVE",
    )
    with connection.cursor() as cursor:
        state = _role_state(connection, role)
        if state is None:
            raise ChronosProductionError("CHRONOS_MIGRATOR_MISSING")
        _assert_role_state(
            connection,
            role,
            can_login=bool(state[1]),
            inherit=False,
            marker=MIGRATOR_MARKER,
        )
        cursor.execute(
            "SELECT rolvaliduntil IS NOT NULL,"
            "rolvaliduntil<=clock_timestamp()+interval '6 minutes' "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        )
        window = cursor.fetchone()
        if bool(state[1]) and (window is None or not bool(window[0]) or not bool(window[1])):
            raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_UNSAFE")
        cursor.execute("SELECT version_num FROM public.alembic_version")
        revision = cursor.fetchone()
        if revision is None:
            raise ChronosProductionError("CHRONOS_MIGRATOR_REVISION_MISSING")
        _assert_migrator_acl(connection, role=role, complete=False)
        _assert_migrator_ownership(connection, role=role, revision=str(revision[0]))
        cursor.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("REVOKE INSERT, UPDATE, DELETE ON TABLE public.alembic_version FROM {}").format(
                sql.Identifier(role)
            )
        )
        with _client_cursor(connection) as client_cursor:
            client_cursor.execute(
                sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(sql.Identifier(role))
            )
    connection.commit()
    assert_migrator_disabled(connection, role=role, bootstrap_owner=bootstrap_owner)


def assert_migrator_disabled(
    connection: Connection[Any], *, role: str, bootstrap_owner: str
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolcanlogin,rolinherit,rolsuper,rolcreatedb,rolcreaterole,"
            "rolreplication,rolbypassrls,rolconfig "
            "FROM pg_catalog.pg_roles WHERE rolname=%s",
            (role,),
        )
        row = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity WHERE usename=%s",
            (role,),
        )
        sessions = cursor.fetchone()
        cursor.execute("SELECT version_num FROM public.alembic_version")
        revision = cursor.fetchone()
    if (
        row is None
        or bool(row[0])
        or bool(row[1])
        or any(bool(value) for value in row[2:7])
        or row[7] is not None
        or sessions is None
        or int(sessions[0]) != 0
        or revision is None
    ):
        raise ChronosProductionError("CHRONOS_MIGRATOR_TERMINAL_STATE_UNSAFE")
    _assert_migrator_acl(
        connection,
        role=role,
        complete=False,
        dormant=True,
        grantor=bootstrap_owner,
    )
    _assert_migrator_ownership(connection, role=role, revision=str(revision[0]))


def provision_runtime_logins(
    connection: Connection[Any],
    *,
    accounts: Sequence[tuple[str, str, str]],
    migrator_role: str,
    pinned_system_grantor: str,
    complete: bool = True,
) -> RoleEdgeAudit:
    """Provision the three scoped LOGIN identities as the bootstrap owner."""

    supplied = {login: group for login, group, _ in accounts}
    if (
        not accounts
        or len(supplied) != len(accounts)
        or any(RUNTIME_ROLE_GROUPS.get(login) != group for login, group in supplied.items())
        or (complete and supplied != RUNTIME_ROLE_GROUPS)
    ):
        raise ChronosProductionError("CHRONOS_RUNTIME_ACCOUNT_MAPPING_INVALID")
    _configure_transaction(connection)
    bootstrap_owner = assert_permanent_bootstrap_authority(connection)
    with connection.cursor() as cursor:
        for login, group, password in accounts:
            require_identifier(login, field="runtime_login")
            if not password:
                raise ChronosProductionError("CHRONOS_RUNTIME_PASSWORD_MISSING")
            state = _role_state(connection, login)
            if state is None:
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s"
                        ).format(sql.Identifier(login)),
                        (password,),
                    )
                    client_cursor.execute(
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(login)),
                        (ROLE_MARKER,),
                    )
            else:
                _assert_role_state(
                    connection,
                    login,
                    can_login=True,
                    inherit=False,
                    marker=ROLE_MARKER,
                )
                cursor.execute(
                    "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                    "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                    "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
                    "WHERE granted.rolname=%s AND member.rolname=%s "
                    "AND grantor.rolname=%s AND grantor.rolsuper "
                    "AND m.admin_option AND NOT m.inherit_option "
                    "AND NOT m.set_option",
                    (login, bootstrap_owner, pinned_system_grantor),
                )
                edge = cursor.fetchone()
                if edge is None or int(edge[0]) != 1:
                    raise ChronosProductionError("CHRONOS_RUNTIME_PROVIDER_IDENTITY_FORBIDDEN")
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(login)),
                        (password,),
                    )
            _assert_role_has_no_smuggled_state(connection, login)
            cursor.execute(
                sql.SQL("GRANT {} TO {} WITH ADMIN FALSE, INHERIT TRUE, SET FALSE").format(
                    sql.Identifier(group), sql.Identifier(login)
                )
            )
    active_runtime = {
        role for role in RUNTIME_ROLE_GROUPS if _role_state(connection, role) is not None
    }
    if complete and active_runtime != set(RUNTIME_ROLE_GROUPS):
        raise ChronosProductionError("CHRONOS_RUNTIME_INVENTORY_INCOMPLETE")
    audit = audit_role_edges(
        connection,
        phase="final" if active_runtime == set(RUNTIME_ROLE_GROUPS) else "runtime_partial",
        bootstrap_owner=bootstrap_owner,
        migrator_role=migrator_role,
        pinned_system_grantor=pinned_system_grantor,
        runtime_roles=sorted(active_runtime),
    )
    connection.commit()
    return audit


def audit_terminal_lifecycle(
    connection: Connection[Any],
    *,
    bootstrap_owner: str,
    lifecycle_admin: str,
    migrator_role: str,
) -> RoleEdgeAudit:
    """Prove the authority is permanent, the migrator dormant and executor gone."""

    _assert_permanent_authority_catalog(connection, authority=bootstrap_owner)
    assert_authority_password_null(connection, authority=bootstrap_owner)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname,rolcanlogin,rolcreaterole,rolsuper,rolcreatedb,"
            "rolreplication,rolbypassrls,rolconfig "
            "FROM pg_catalog.pg_roles WHERE rolname=ANY(%s) ORDER BY rolname",
            ([bootstrap_owner, migrator_role],),
        )
        states = cursor.fetchall()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE pid<>pg_catalog.pg_backend_pid() "
            "AND backend_type='client backend' AND "
            "(usename=ANY(%s) OR usename LIKE %s)",
            (
                [bootstrap_owner, lifecycle_admin, migrator_role],
                BOOTSTRAP_EXECUTOR_PREFIX + "%",
            ),
        )
        sessions = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname LIKE %s",
            (BOOTSTRAP_EXECUTOR_PREFIX + "%",),
        )
        executor_roles = cursor.fetchone()
    by_name = {str(row[0]): row for row in states}
    owner = by_name.get(bootstrap_owner)
    migrator = by_name.get(migrator_role)
    if (
        owner is None
        or migrator is None
        or bool(owner[1])
        or not bool(owner[2])
        or any(bool(value) for value in owner[3:7])
        or owner[7] is not None
        or bool(migrator[1])
        or bool(migrator[2])
        or any(bool(value) for value in migrator[3:7])
        or migrator[7] is not None
        or sessions is None
        or int(sessions[0]) != 0
        or executor_roles is None
        or int(executor_roles[0]) != 0
    ):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_TERMINAL_STATE_UNSAFE")
    assert_migrator_disabled(connection, role=migrator_role, bootstrap_owner=bootstrap_owner)
    assert_post_migration_role_state(
        connection,
        migrator_role=migrator_role,
        bootstrap_owner=bootstrap_owner,
    )
    return audit_role_edges(
        connection,
        phase="terminal",
        bootstrap_owner=bootstrap_owner,
        lifecycle_admin=lifecycle_admin,
        executor_role=None,
        migrator_role=migrator_role,
    )


__all__ = [
    "AUTHORITY_MARKER",
    "BOOTSTRAP_AUTHORITY",
    "BOOTSTRAP_EXECUTOR_PREFIX",
    "EXECUTOR_MARKER",
    "GROUP_ROLES",
    "MIGRATOR_MARKER",
    "ROLE_MARKER",
    "RUNTIME_ROLE_GROUPS",
    "BootstrapExecutorLease",
    "RoleEdgeAudit",
    "acquire_lifecycle_lock",
    "assert_authority_password_null",
    "assert_executor_before_set_role",
    "assert_executor_cannot_create_role",
    "assert_lifecycle_admin",
    "assert_migrator_disabled",
    "assert_permanent_bootstrap_authority",
    "assert_post_migration_role_state",
    "assert_privileged_catalog_visibility",
    "assert_role_inventory_delta",
    "audit_terminal_lifecycle",
    "audit_role_edges",
    "cleanup_bootstrap_executor",
    "disable_migrator",
    "provision_chronos_group_roles",
    "provision_bootstrap_executor",
    "provision_permanent_bootstrap_authority",
    "provision_migrator",
    "provision_runtime_logins",
    "release_lifecycle_lock",
    "reset_permanent_bootstrap_authority",
    "role_inventory_hash",
    "role_inventory_snapshot",
    "set_permanent_bootstrap_authority",
    "stable_migrator_role",
]
