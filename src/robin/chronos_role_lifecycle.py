"""Provider-free PostgreSQL 16 role lifecycle for Chronos revision 0014."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import ClientCursor, Connection, sql

from robin.chronos_production import ChronosProductionError, require_identifier

GROUP_ROLES = (
    "chronos_authority_executor",
    "chronos_reader",
    "chronos_runtime_writer",
    "chronos_test_writer",
)
RUNTIME_ROLE_GROUPS = {
    "chronos_authority_runtime_login": "chronos_authority_executor",
    "chronos_effect_runtime_login": "chronos_runtime_writer",
    "chronos_reader_login": "chronos_reader",
}
ROLE_MARKER = "managed-by:chronos-role-lifecycle-e1-v1"
MIGRATOR_MARKER = "managed-by:chronos-role-lifecycle-e1-v1:migrator"
CHRONOS_FUNCTION_SIGNATURES = {
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
    if (
        any(current.get(name) != state for name, state in baseline.items())
        or set(current).difference(baseline) != set(expected_new_roles)
    ):
        raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_DELTA_UNSAFE")


@dataclass(frozen=True, slots=True)
class RoleEdgeAudit:
    phase: str
    bootstrap_owner: str
    bootstrap_system_grantor: str
    migrator_role: str | None
    role_inventory: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    forbidden_edge_count: int
    runtime_effective_bootstrap_edge_count: int
    migrator_runtime_edge_count: int

    def report(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "bootstrap_owner": self.bootstrap_owner,
            "bootstrap_system_grantor": self.bootstrap_system_grantor,
            "migrator_role": self.migrator_role,
            "role_inventory": list(self.role_inventory),
            "edges": list(self.edges),
            "edge_count": len(self.edges),
            "forbidden_edge_count": self.forbidden_edge_count,
            "runtime_effective_bootstrap_edge_count": (
                self.runtime_effective_bootstrap_edge_count
            ),
            "migrator_runtime_edge_count": self.migrator_runtime_edge_count,
        }


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


def assert_bootstrap_owner(
    connection: Connection[Any], *, deadline: datetime | None = None
) -> str:
    """Require a non-superuser CREATEROLE session outside runtime identities."""

    maximum = deadline or datetime.now(UTC) + timedelta(minutes=10)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname,rolcanlogin,rolsuper,rolcreaterole,"
            "rolvaliduntil IS NOT NULL,rolvaliduntil>clock_timestamp(),"
            "rolvaliduntil<=least(%s,clock_timestamp()+interval '10 minutes') "
            "FROM pg_catalog.pg_roles WHERE rolname=current_user",
            (maximum,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_OWNER_MISSING")
    owner = str(row[0])
    if (
        not bool(row[1])
        or bool(row[2])
        or not bool(row[3])
        or not bool(row[4])
        or not bool(row[5])
        or not bool(row[6])
        or owner in GROUP_ROLES
        or owner in RUNTIME_ROLE_GROUPS
    ):
        raise ChronosProductionError("CHRONOS_BOOTSTRAP_OWNER_UNSAFE")
    return owner


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


def _assert_role_has_no_smuggled_state(
    connection: Connection[Any], role: str
) -> None:
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


def _assert_role_has_no_ownership_or_settings(
    connection: Connection[Any], role: str
) -> None:
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
            "SELECT 'database' AS object_kind,d.datname AS object_name,"
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
            "UNION ALL SELECT 'default_acl',coalesce(n.nspname,'*')||':'||d.defaclobjtype,"
            "a.privilege_type,g.rolname,a.is_grantable "
            "FROM pg_catalog.pg_default_acl d LEFT JOIN pg_catalog.pg_namespace n "
            "ON n.oid=d.defaclnamespace CROSS JOIN LATERAL "
            "pg_catalog.aclexplode(d.defaclacl) a JOIN pg_catalog.pg_roles r "
            "ON r.oid=a.grantee JOIN pg_catalog.pg_roles g ON g.oid=a.grantor "
            "WHERE r.rolname=%s) acl ORDER BY 1,2,3,4,5",
            (role,) * 7,
        )
        rows = cursor.fetchall()
    return {
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]), bool(row[4]))
        for row in rows
    }


def _chronos_object_acl_rows(
    connection: Connection[Any], *, migrator_role: str
) -> set[tuple[str, str, str, str, str, bool]]:
    groups = list(GROUP_ROLES)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT object_kind,object_name,grantee_role,grantor_role,"
            "privilege_type,is_grantable FROM ("
            "SELECT 'schema' AS object_kind,n.nspname AS object_name,"
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
            "c.relname IN ('chronos_effect_authorities','chronos_effect_events',"
            "'chronos_effect_accounting') AND a.grantee<>c.relowner OR "
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
            "UNION ALL SELECT 'default_acl',coalesce(n.nspname,'*')||':'||d.defaclobjtype,"
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
                groups,
                migrator_role,
                [
                    "chronos_framed_sha256",
                    "chronos_effect_event_hash",
                    "chronos_reject_mutation",
                    "chronos_issue_effect_authority",
                    "chronos_claim_effect_authority",
                    "chronos_append_effect_event",
                    "chronos_get_effect_state",
                ],
                [
                    "chronos_effect_authorities",
                    "chronos_effect_events",
                    "chronos_effect_accounting",
                ],
                [
                    "chronos_effect_authorities",
                    "chronos_effect_events",
                    "chronos_effect_accounting",
                ],
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
    bootstrap_owner = grantor or assert_bootstrap_owner(connection)
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
    if (dormant and observed != base) or (
        not dormant and complete and observed != base | active
    ) or (
        not dormant and not complete and not observed <= base | active
    ):
        raise ChronosProductionError("CHRONOS_MIGRATOR_ACL_UNSAFE")


def _assert_migrator_ownership(
    connection: Connection[Any], *, role: str, revision: str
) -> None:
    with connection.cursor() as cursor:
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
                [
                    "chronos_effect_authorities",
                    "chronos_effect_events",
                    "chronos_effect_accounting",
                ],
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
        owned_functions = {
            (str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()
        }
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
                [
                    "chronos_effect_authorities",
                    "chronos_effect_events",
                    "chronos_effect_accounting",
                ],
                role,
                role,
            ),
        )
        unexpected_types = cursor.fetchall()
    expected_functions = {
        ("public", name, signature)
        for name, signature in CHRONOS_FUNCTION_SIGNATURES.items()
    }
    allow_objects = revision == "0014_chronos_control_plane_v2"
    if (
        base_unsafe is None
        or bool(base_unsafe[0])
        or unexpected_classes
        or unexpected_types
        or (allow_objects and owned_functions != expected_functions)
        or (not allow_objects and owned_functions)
    ):
        raise ChronosProductionError("CHRONOS_MIGRATOR_OWNERSHIP_UNSAFE")


def assert_post_migration_role_state(
    connection: Connection[Any],
    *,
    migrator_role: str,
    bootstrap_owner: str | None = None,
) -> None:
    """Require the exact 0014 role attributes, ownership and object ACLs."""

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
        if (
            window is None or not bool(window[0]) or not bool(window[1])
        ):
            raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_UNSAFE")
    for role in GROUP_ROLES:
        _assert_role_state(
            connection, role, can_login=False, inherit=True, marker=ROLE_MARKER
        )
        _assert_role_has_no_ownership_or_settings(connection, role)
    observed_acl: set[tuple[str, str, str, str, bool]] = set()
    for role in GROUP_ROLES:
        observed_acl.update(_direct_acl_rows(connection, role))
    # Include the grantee in the comparison by checking each role independently.
    per_role = {
        role: _direct_acl_rows(connection, role) for role in GROUP_ROLES
    }
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
    if _chronos_object_acl_rows(
        connection, migrator_role=migrator_role
    ) != expected_global:
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
        revision="0014_chronos_control_plane_v2",
    )


def _role_inventory(
    connection: Connection[Any],
    *,
    phase: str,
    bootstrap_owner: str,
    migrator_role: str | None,
    active_runtime: set[str],
) -> tuple[dict[str, Any], ...]:
    expected = set(GROUP_ROLES) | active_runtime | {bootstrap_owner}
    if migrator_role is not None:
        expected.add(migrator_role)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT oid,rolname,rolcanlogin,rolinherit,rolsuper,rolcreatedb,"
            "rolcreaterole,rolreplication,rolbypassrls,rolconfig,rolvaliduntil::text,"
            "pg_catalog.shobj_description(oid,'pg_authid') "
            "FROM pg_catalog.pg_roles WHERE rolname=ANY(%s) OR "
            "pg_catalog.shobj_description(oid,'pg_authid')=ANY(%s) "
            "ORDER BY rolname",
            (sorted(expected), [ROLE_MARKER, MIGRATOR_MARKER]),
        )
        rows = cursor.fetchall()
    if {str(row[1]) for row in rows} != expected:
        raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_MISMATCH")
    inventory: list[dict[str, Any]] = []
    for row in rows:
        name = str(row[1])
        marker = None if row[11] is None else str(row[11])
        is_owner = name == bootstrap_owner
        is_group = name in GROUP_ROLES
        is_runtime = name in active_runtime
        is_migrator = name == migrator_role
        expected_marker = (
            None if is_owner else MIGRATOR_MARKER if is_migrator else ROLE_MARKER
        )
        unsafe = any(bool(value) for value in (row[4], row[5], row[7], row[8]))
        if (
            unsafe
            or row[9] is not None
            or (not is_owner and marker != expected_marker)
            or bool(row[6]) is not is_owner
            or (is_group and (bool(row[2]) or not bool(row[3])))
            or (is_runtime and (not bool(row[2]) or bool(row[3])))
            or (is_migrator and bool(row[3]))
            or (is_owner and bool(row[3]))
            or (phase == "terminal" and is_owner and bool(row[2]))
        ):
            raise ChronosProductionError("CHRONOS_ROLE_INVENTORY_UNSAFE")
        inventory.append(
            {
                "oid": int(row[0]),
                "role": name,
                "can_login": bool(row[2]),
                "inherit": bool(row[3]),
                "createrole": bool(row[6]),
                "valid_until": row[10],
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
            "member.rolcanlogin "
            "FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
            "WHERE granted.rolname=ANY(%s) OR member.rolname=ANY(%s) "
            "OR member.rolname=%s OR granted.rolname=%s "
            "ORDER BY granted.rolname,member.rolname,grantor.rolname",
            (scope, scope, bootstrap_owner, bootstrap_owner),
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
        }
        for row in rows
    ]


def audit_role_edges(
    connection: Connection[Any],
    *,
    phase: str,
    bootstrap_owner: str,
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
    names = sorted(active_groups | active_runtime | active_migrator)
    inventory = _role_inventory(
        connection,
        phase=phase,
        bootstrap_owner=bootstrap_owner,
        migrator_role=migrator_role,
        active_runtime=active_runtime,
    )
    rows = _membership_rows(connection, names, bootstrap_owner)

    expected_admin_roles = active_groups | active_runtime | active_migrator
    candidates = {
        row["grantor_role"]
        for row in rows
        if row["member_role"] == bootstrap_owner
        and row["granted_role"] in expected_admin_roles
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
            and RUNTIME_ROLE_GROUPS.get(row["member_role"])
            == row["granted_role"]
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
        if is_functional:
            classification = "EXPECTED_RUNTIME_GROUP_EDGE"
            reason = "exact functional group inheritance without ADMIN or SET"
        elif is_migrator_admin:
            classification = "EXPECTED_MIGRATOR_ADMIN_EDGE"
            reason = "automatic PostgreSQL creator edge to offline bootstrap owner"
        elif is_bootstrap_admin:
            classification = "EXPECTED_BOOTSTRAP_ADMIN_EDGE"
            reason = "automatic PostgreSQL creator edge to offline bootstrap owner"
        else:
            forbidden += 1
        runtime_effective = bool(row["runtime_usage"] or row["runtime_set"])
        if (is_bootstrap_admin or is_migrator_admin) and runtime_effective:
            runtime_effective_bootstrap += 1
        if migrator_role is not None and (
            (row["granted_role"] == migrator_role and row["member_role"] in active_runtime)
            or (
                row["member_role"] == migrator_role
                and row["granted_role"] in active_runtime
            )
        ):
            migrator_runtime += 1
        classified.append(
            {
                **{key: value for key, value in row.items() if key != "runtime_usage"},
                "classification": classification,
                "runtime_effective": runtime_effective,
                "administratively_effective": bool(
                    row["admin_option"] and row["member_authenticatable"]
                ),
                "reason": reason,
            }
        )

    expected_count = {
        "groups": 4,
        "migrator": 5,
        "runtime_partial": 5 + 2 * len(active_runtime),
        "final": 11,
        "terminal": 11,
    }[phase]
    expected_functional = len(active_runtime)
    actual_functional = sum(
        edge["classification"] == "EXPECTED_RUNTIME_GROUP_EDGE"
        for edge in classified
    )
    if (
        len(classified) != expected_count
        or actual_functional != expected_functional
        or forbidden
        or runtime_effective_bootstrap
        or migrator_runtime
        or (
            phase == "terminal"
            and any(edge["administratively_effective"] for edge in classified)
        )
    ):
        raise ChronosProductionError("CHRONOS_ROLE_EDGE_AUDIT_FAILED")
    return RoleEdgeAudit(
        phase=phase,
        bootstrap_owner=bootstrap_owner,
        bootstrap_system_grantor=system_grantor,
        migrator_role=migrator_role,
        role_inventory=inventory,
        edges=tuple(classified),
        forbidden_edge_count=forbidden,
        runtime_effective_bootstrap_edge_count=runtime_effective_bootstrap,
        migrator_runtime_edge_count=migrator_runtime,
    )


def provision_chronos_group_roles(
    connection: Connection[Any],
    *,
    migrator_role: str | None = None,
) -> RoleEdgeAudit:
    """Create or adopt exact Chronos NOLOGIN groups as the bootstrap owner."""

    _configure_transaction(connection)
    bootstrap_owner = assert_bootstrap_owner(connection)
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
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(
                            sql.Identifier(role)
                        ),
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
    bootstrap_owner = assert_bootstrap_owner(connection)
    with connection.cursor() as cursor:
        state = _role_state(connection, role)
        if state is None:
            with _client_cursor(connection) as client_cursor:
                client_cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s "
                        "VALID UNTIL %s"
                    ).format(sql.Identifier(role)),
                    (password, valid_until),
                )
                client_cursor.execute(
                    sql.SQL("COMMENT ON ROLE {} IS %s").format(
                        sql.Identifier(role)
                    ),
                    (MIGRATOR_MARKER,),
                )
        else:
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
            previous_window = cursor.fetchone()
            if (
                bool(state[1])
                and (
                    previous_window is None
                    or not bool(previous_window[0])
                    or not bool(previous_window[1])
                )
            ):
                raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_UNSAFE")
            cursor.execute("SELECT version_num FROM public.alembic_version")
            revision_row = cursor.fetchone()
            if revision_row is None:
                raise ChronosProductionError("CHRONOS_MIGRATOR_REVISION_MISSING")
            _assert_migrator_acl(connection, role=role, complete=False)
            _assert_migrator_ownership(
                connection, role=role, revision=str(revision_row[0])
            )
            with _client_cursor(connection) as client_cursor:
                client_cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %s "
                        "VALID UNTIL %s"
                    ).format(sql.Identifier(role)),
                    (password, valid_until),
                )
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {} WITH GRANT OPTION").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL(
                "GRANT SELECT ON TABLE public.alembic_version TO {} "
                "WITH GRANT OPTION"
            ).format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL(
                "GRANT INSERT, UPDATE, DELETE ON TABLE public.alembic_version TO {}"
            ).format(sql.Identifier(role))
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


def disable_migrator(connection: Connection[Any], *, role: str) -> None:
    """Remove temporary grants and authentication from the persistent migrator."""

    _configure_transaction(connection)
    bootstrap_owner = assert_bootstrap_owner(connection)
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
        if (
            bool(state[1])
            and (
                window is None or not bool(window[0]) or not bool(window[1])
            )
        ):
            raise ChronosProductionError("CHRONOS_MIGRATOR_WINDOW_UNSAFE")
        cursor.execute("SELECT version_num FROM public.alembic_version")
        revision = cursor.fetchone()
        if revision is None:
            raise ChronosProductionError("CHRONOS_MIGRATOR_REVISION_MISSING")
        _assert_migrator_acl(connection, role=role, complete=False)
        _assert_migrator_ownership(
            connection, role=role, revision=str(revision[0])
        )
        cursor.execute(
            sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL(
                "REVOKE INSERT, UPDATE, DELETE ON TABLE "
                "public.alembic_version FROM {}"
            ).format(sql.Identifier(role))
        )
        with _client_cursor(connection) as client_cursor:
            client_cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD NULL"
                ).format(sql.Identifier(role))
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
    _assert_migrator_ownership(
        connection, role=role, revision=str(revision[0])
    )


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
    bootstrap_owner = assert_bootstrap_owner(connection)
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
                        sql.SQL("COMMENT ON ROLE {} IS %s").format(
                            sql.Identifier(login)
                        ),
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
                    raise ChronosProductionError(
                        "CHRONOS_RUNTIME_PROVIDER_IDENTITY_FORBIDDEN"
                    )
                with _client_cursor(connection) as client_cursor:
                    client_cursor.execute(
                        sql.SQL("ALTER ROLE {} PASSWORD %s").format(
                            sql.Identifier(login)
                        ),
                        (password,),
                    )
            _assert_role_has_no_smuggled_state(connection, login)
            cursor.execute(
                sql.SQL(
                    "GRANT {} TO {} WITH ADMIN FALSE, INHERIT TRUE, SET FALSE"
                ).format(sql.Identifier(group), sql.Identifier(login))
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


def terminalize_bootstrap_owner(connection: Connection[Any]) -> None:
    """Make the bootstrap owner dormant while retaining offline CREATEROLE."""

    _configure_transaction(connection)
    bootstrap_owner = assert_bootstrap_owner(connection)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_stat_activity "
            "WHERE usename=%s AND pid<>pg_catalog.pg_backend_pid()",
            (bootstrap_owner,),
        )
        row = cursor.fetchone()
        if row is None or int(row[0]) != 0:
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_SESSIONS_ACTIVE")
        with _client_cursor(connection) as client_cursor:
            client_cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} NOLOGIN CREATEROLE NOSUPERUSER NOCREATEDB "
                    "NOREPLICATION NOBYPASSRLS PASSWORD NULL"
                ).format(sql.Identifier(bootstrap_owner))
            )
        cursor.execute(
            sql.SQL("ALTER ROLE {} RESET ALL").format(
                sql.Identifier(bootstrap_owner)
            )
        )
    connection.commit()


def audit_terminal_lifecycle(
    connection: Connection[Any], *, bootstrap_owner: str, migrator_role: str
) -> RoleEdgeAudit:
    """Prove both privileged lifecycle identities are dormant and session-free."""

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
            "WHERE usename=ANY(%s)",
            ([bootstrap_owner, migrator_role],),
        )
        sessions = cursor.fetchone()
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
    ):
        raise ChronosProductionError("CHRONOS_LIFECYCLE_TERMINAL_STATE_UNSAFE")
    assert_migrator_disabled(
        connection, role=migrator_role, bootstrap_owner=bootstrap_owner
    )
    assert_post_migration_role_state(
        connection,
        migrator_role=migrator_role,
        bootstrap_owner=bootstrap_owner,
    )
    return audit_role_edges(
        connection,
        phase="terminal",
        bootstrap_owner=bootstrap_owner,
        migrator_role=migrator_role,
    )


__all__ = [
    "GROUP_ROLES",
    "MIGRATOR_MARKER",
    "ROLE_MARKER",
    "RUNTIME_ROLE_GROUPS",
    "RoleEdgeAudit",
    "assert_bootstrap_owner",
    "assert_migrator_disabled",
    "assert_post_migration_role_state",
    "assert_role_inventory_delta",
    "audit_terminal_lifecycle",
    "audit_role_edges",
    "disable_migrator",
    "provision_chronos_group_roles",
    "provision_migrator",
    "provision_runtime_logins",
    "role_inventory_hash",
    "role_inventory_snapshot",
    "stable_migrator_role",
    "terminalize_bootstrap_owner",
]
