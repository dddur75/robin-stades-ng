"""Protected manual bootstrap for Neon Chronos revision 0014.

The CLI prints only stable status codes. Secret-bearing failures are reduced to
sanitized codes and never include response bodies, SQL parameters, or URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess  # nosec B404
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import psycopg
import requests
from psycopg import Connection, sql

from robin.chronos_production import (
    EXPECTED_AFTER_REVISION,
    EXPECTED_BEFORE_REVISION,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    MIGRATION_TARGET,
    SCOPED_LOGINS,
    ChronosProductionError,
    DirectPostgresTarget,
    assert_exact_preflight_binding,
    build_scoped_database_url,
    generation_hash,
    preflight_hash,
    require_sha,
    sign_document,
    validate_direct_postgres_url,
    verify_signed_document,
)

NEON_API = "https://console.neon.tech/api/v2"
EXPECTED_TABLES = ("chronos_effect_authorities", "chronos_effect_events")
EXPECTED_GROUPS = (
    "chronos_authority_executor",
    "chronos_reader",
    "chronos_runtime_writer",
    "chronos_test_writer",
)
EXPECTED_FUNCTIONS = (
    "chronos_append_effect_event",
    "chronos_claim_effect_authority",
    "chronos_effect_event_hash",
    "chronos_framed_sha256",
    "chronos_get_effect_state",
    "chronos_issue_effect_authority",
    "chronos_reject_mutation",
)
EXPECTED_TRIGGERS = (
    "trg_chronos_authorities_append_only",
    "trg_chronos_authorities_no_truncate",
    "trg_chronos_effect_events_fsm",
    "trg_chronos_events_append_only",
    "trg_chronos_events_no_truncate",
)
NO_VALUES_OBSERVED = False


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_SECRET:{name}")
    return value


def _required_public(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_CONTEXT:{name}")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | str | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_value(document), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _rows(connection: Connection[Any], statement: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(statement)
        names = [column.name for column in cursor.description or ()]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _scalar(connection: Connection[Any], statement: str) -> object:
    with connection.cursor() as cursor:
        cursor.execute(statement)
        row = cursor.fetchone()
    return None if row is None else row[0]


@dataclass(frozen=True, slots=True)
class NeonIdentity:
    project_id: str
    project_name: str
    production_branch_id: str
    production_branch_name: str
    endpoint_id: str
    endpoint_host: str
    region: str
    database_name: str


class NeonClient:
    """Small Neon API client whose exceptions never include response bodies."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ChronosProductionError("CHRONOS_NEON_API_KEY_MISSING")
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                NEON_API + path,
                json=payload,
                timeout=30,
            )
        except requests.RequestException:
            raise ChronosProductionError("CHRONOS_NEON_API_UNAVAILABLE") from None
        if not 200 <= response.status_code < 300:
            raise ChronosProductionError(
                f"CHRONOS_NEON_API_HTTP_{response.status_code}"
            )
        try:
            document = response.json()
        except ValueError:
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID") from None
        if not isinstance(document, dict):
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID")
        return cast(dict[str, Any], document)

    def projects(self) -> list[dict[str, Any]]:
        document = self.request("GET", "/projects?limit=100")
        projects = document.get("projects", [])
        if not isinstance(projects, list):
            raise ChronosProductionError("CHRONOS_NEON_PROJECT_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in projects if isinstance(item, dict)]

    def project(self, project_id: str) -> dict[str, Any]:
        document = self.request("GET", f"/projects/{project_id}")
        project = document.get("project")
        if not isinstance(project, dict):
            raise ChronosProductionError("CHRONOS_NEON_PROJECT_INVALID")
        return cast(dict[str, Any], project)

    def branches(self, project_id: str) -> list[dict[str, Any]]:
        document = self.request("GET", f"/projects/{project_id}/branches?limit=100")
        branches = document.get("branches", [])
        if not isinstance(branches, list):
            raise ChronosProductionError("CHRONOS_NEON_BRANCH_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in branches if isinstance(item, dict)]

    def endpoints(self, project_id: str) -> list[dict[str, Any]]:
        document = self.request("GET", f"/projects/{project_id}/endpoints")
        endpoints = document.get("endpoints", [])
        if not isinstance(endpoints, list):
            raise ChronosProductionError("CHRONOS_NEON_ENDPOINT_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in endpoints if isinstance(item, dict)]

    def create_recovery_branch(
        self,
        *,
        project_id: str,
        parent_branch_id: str,
        branch_name: str,
    ) -> dict[str, Any]:
        document = self.request(
            "POST",
            f"/projects/{project_id}/branches",
            payload={
                "branch": {
                    "name": branch_name,
                    "parent_id": parent_branch_id,
                }
            },
        )
        branch = document.get("branch")
        if not isinstance(branch, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_RESPONSE_INVALID")
        return cast(dict[str, Any], branch)

    def branch(self, project_id: str, branch_id: str) -> dict[str, Any]:
        document = self.request("GET", f"/projects/{project_id}/branches/{branch_id}")
        branch = document.get("branch")
        if not isinstance(branch, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_RESPONSE_INVALID")
        return cast(dict[str, Any], branch)


def resolve_neon_identity(
    client: NeonClient,
    target: DirectPostgresTarget,
) -> NeonIdentity:
    configured = os.getenv("NEON_PROJECT_ID", "")
    candidates = [client.project(configured)] if configured else client.projects()
    matches: list[NeonIdentity] = []
    for project in candidates:
        project_id = str(project.get("id", ""))
        if not project_id:
            continue
        branches = {str(item.get("id")): item for item in client.branches(project_id)}
        for endpoint in client.endpoints(project_id):
            host = str(endpoint.get("host", "")).lower()
            if host != target.host:
                continue
            if "pooler" in host:
                raise ChronosProductionError("CHRONOS_POOLED_ENDPOINT_FORBIDDEN")
            branch_id = str(endpoint.get("branch_id", ""))
            branch = branches.get(branch_id)
            if branch is None:
                continue
            branch_state = str(
                branch.get("current_state", branch.get("state", "ready"))
            ).lower()
            endpoint_state = str(endpoint.get("current_state", "active")).lower()
            if branch_state not in {"ready", "active"}:
                continue
            if endpoint_state not in {"active", "idle"}:
                continue
            matches.append(
                NeonIdentity(
                    project_id=project_id,
                    project_name=str(project.get("name", "")),
                    production_branch_id=branch_id,
                    production_branch_name=str(branch.get("name", "")),
                    endpoint_id=str(endpoint.get("id", "")),
                    endpoint_host=host,
                    region=str(
                        endpoint.get("region_id", project.get("region_id", ""))
                    ),
                    database_name=target.database,
                )
            )
    if len(matches) != 1:
        raise ChronosProductionError("NEON_PROJECT_IDENTITY_AMBIGUOUS")
    identity = matches[0]
    if configured and identity.project_id != configured:
        raise ChronosProductionError("NEON_PROJECT_IDENTITY_AMBIGUOUS")
    return identity


def create_recovery_point(
    client: NeonClient,
    identity: NeonIdentity,
) -> dict[str, Any]:
    compact = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    name = f"chronos-pre-0014-recovery-{compact}"
    branch = client.create_recovery_branch(
        project_id=identity.project_id,
        parent_branch_id=identity.production_branch_id,
        branch_name=name,
    )
    branch_id = str(branch.get("id", ""))
    if not branch_id:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_ID_MISSING")
    observed = branch
    for _ in range(12):
        state = str(observed.get("current_state", observed.get("state", "ready"))).lower()
        if state in {"ready", "active"}:
            break
        time.sleep(5)
        observed = client.branch(identity.project_id, branch_id)
    else:
        raise ChronosProductionError("NEON_RECOVERY_POINT_BLOCKED")
    if str(observed.get("parent_id", "")) != identity.production_branch_id:
        raise ChronosProductionError("CHRONOS_RECOVERY_PARENT_MISMATCH")
    if str(observed.get("name", name)) != name:
        raise ChronosProductionError("CHRONOS_RECOVERY_NAME_MISMATCH")
    return {
        "schema_version": "chronos-neon-recovery-point-v3",
        "verdict": "NEON_RECOVERY_POINT_READY",
        "recovery_branch_name": name,
        "recovery_branch_id": branch_id,
        "parent_branch_id": identity.production_branch_id,
        "created_at": observed.get("created_at"),
        "source_timestamp_or_lsn_if_available": observed.get(
            "parent_lsn", observed.get("parent_timestamp")
        ),
        "endpoint_created": False,
        "purchases": 0,
    }


def inspect_database(database_url: str) -> dict[str, Any]:
    target = validate_direct_postgres_url(database_url)
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        revision = _scalar(
            connection,
            "SELECT version_num FROM public.alembic_version",
        )
        tables = _rows(
            connection,
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname='public' AND tablename LIKE 'chronos_%' "
            "ORDER BY tablename",
        )
        functions = _rows(
            connection,
            "SELECT p.proname AS function_name, p.prosecdef AS security_definer, "
            "pg_catalog.pg_get_functiondef(p.oid) LIKE '%clock_timestamp()%' "
            "AS uses_clock_timestamp FROM pg_catalog.pg_proc p "
            "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname LIKE 'chronos_%' "
            "ORDER BY p.proname",
        )
        triggers = _rows(
            connection,
            "SELECT t.tgname AS trigger_name, c.relname AS table_name "
            "FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c "
            "ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname='public' "
            "AND t.tgname LIKE 'trg_chronos_%' AND NOT t.tgisinternal "
            "ORDER BY t.tgname",
        )
        roles = _rows(
            connection,
            "SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
            "rolreplication,rolbypassrls FROM pg_catalog.pg_roles "
            "WHERE rolname LIKE 'chronos_%' ORDER BY rolname",
        )
        memberships = _rows(
            connection,
            "SELECT granted.rolname AS granted_role, member.rolname AS member_role,"
            "m.admin_option FROM pg_catalog.pg_auth_members m "
            "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
            "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
            "WHERE granted.rolname LIKE 'chronos_%' "
            "OR member.rolname LIKE 'chronos_%' "
            "ORDER BY granted.rolname,member.rolname",
        )
        sessions = _rows(
            connection,
            "SELECT coalesce(state,'UNKNOWN') AS state,count(*) AS count "
            "FROM pg_catalog.pg_stat_activity WHERE datname=current_database() "
            "GROUP BY state ORDER BY state",
        )
        report = {
            "database_host": target.host,
            "database_port": target.port,
            "database_name": str(_scalar(connection, "SELECT current_database()")),
            "sslmode": target.sslmode,
            "postgresql_version": str(_scalar(connection, "SHOW server_version")),
            "current_user": str(_scalar(connection, "SELECT current_user")),
            "current_revision": None if revision is None else str(revision),
            "server_epoch": _scalar(
                connection, "SELECT pg_catalog.pg_postmaster_start_time()"
            ),
            "database_size_bytes": int(
                cast(int, _scalar(connection, "SELECT pg_database_size(current_database())"))
            ),
            "roles": roles,
            "memberships": memberships,
            "tables": tables,
            "functions": functions,
            "triggers": triggers,
            "sessions": sessions,
        }
    return cast(dict[str, Any], _json_value(report))


def _assert_post_migration(report: Mapping[str, Any]) -> None:
    if report.get("current_revision") != EXPECTED_AFTER_REVISION:
        raise ChronosProductionError("CHRONOS_MIGRATION_REVISION_MISMATCH")
    tables = {str(row["tablename"]) for row in cast(list[dict[str, Any]], report["tables"])}
    functions = {
        str(row["function_name"])
        for row in cast(list[dict[str, Any]], report["functions"])
    }
    triggers = {
        str(row["trigger_name"])
        for row in cast(list[dict[str, Any]], report["triggers"])
    }
    if tables != set(EXPECTED_TABLES):
        raise ChronosProductionError("CHRONOS_MIGRATION_TABLES_MISMATCH")
    if functions != set(EXPECTED_FUNCTIONS):
        raise ChronosProductionError("CHRONOS_MIGRATION_FUNCTIONS_MISMATCH")
    if triggers != set(EXPECTED_TRIGGERS):
        raise ChronosProductionError("CHRONOS_MIGRATION_TRIGGERS_MISMATCH")
    roles = {
        str(row["rolname"]): row
        for row in cast(list[dict[str, Any]], report["roles"])
        if str(row["rolname"]) in EXPECTED_GROUPS
    }
    if set(roles) != set(EXPECTED_GROUPS):
        raise ChronosProductionError("CHRONOS_MIGRATION_GROUP_ROLES_MISMATCH")
    unsafe = {
        "rolcanlogin",
        "rolsuper",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolbypassrls",
    }
    if any(bool(row[field]) for row in roles.values() for field in unsafe):
        raise ChronosProductionError("CHRONOS_MIGRATION_GROUP_ROLE_UNSAFE")


def _assert_hold() -> dict[str, Any]:
    path = Path(_required_public("CHRONOS_HOLD_REPORT"))
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_WORKFLOW_HOLD_REPORT_INVALID")
    if document.get("verdict") != "WORKFLOW_HOLD_ESTABLISHED":
        raise ChronosProductionError("CHRONOS_WORKFLOW_HOLD_REQUIRED")
    if document.get("queued_after") != 0 or document.get("in_progress_after") != 0:
        raise ChronosProductionError("CHRONOS_WORKFLOW_HOLD_REQUIRED")
    return cast(dict[str, Any], document)


def run_preflight(report_dir: Path) -> dict[str, Any]:
    api_key = _required("NEON_API_KEY")
    database_url = _required("NEON_BOOTSTRAP_DATABASE_URL")
    main_sha = require_sha(_required_public("GITHUB_SHA"), field="main_sha")
    workflow_sha = require_sha(
        _required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha"
    )
    if _required_public("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    if _required_public("GITHUB_REF") != EXPECTED_REF:
        raise ChronosProductionError("CHRONOS_REF_MISMATCH")
    expected_main = require_sha(
        _required_public("CHRONOS_EXPECTED_MAIN_SHA"), field="expected_main_sha"
    )
    if main_sha != expected_main:
        raise ChronosProductionError("CHRONOS_MAIN_SHA_MISMATCH")
    hold = _assert_hold()
    target = validate_direct_postgres_url(database_url)
    client = NeonClient(api_key)
    identity = resolve_neon_identity(client, target)
    recovery = create_recovery_point(client, identity)
    database = inspect_database(database_url)
    if database["current_revision"] != EXPECTED_BEFORE_REVISION:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    migration_file = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0014_chronos_control_plane_v2.py"
    )
    if not migration_file.is_file():
        raise ChronosProductionError("CHRONOS_MIGRATION_TARGET_MISSING")
    recovery_report = {
        **recovery,
        "project_id": identity.project_id,
        "production_branch_id": identity.production_branch_id,
    }
    _write_json(report_dir / "chronos-neon-recovery-point-v3.json", recovery_report)
    preflight_report = {
        "schema_version": "chronos-neon-preflight-v3",
        "observed_at": _timestamp(_utc_now()),
        "verdict": "CHRONOS_MIGRATION_READY",
        "project_identity": "NEON_PROJECT_IDENTITY_VERIFIED",
        "project_id": identity.project_id,
        "project_name": identity.project_name,
        "production_branch_id": identity.production_branch_id,
        "production_branch_name": identity.production_branch_name,
        "endpoint_id": identity.endpoint_id,
        "region": identity.region,
        "database": database,
        "recovery": recovery_report,
        "workflow_hold": {
            "verdict": hold.get("verdict"),
            "active_after": hold.get("active_after"),
            "disabled_after": hold.get("disabled_after"),
            "queued_after": hold.get("queued_after"),
            "in_progress_after": hold.get("in_progress_after"),
        },
        "secret_values_observed": NO_VALUES_OBSERVED,
        "provider_calls": 0,
        "r2_operations": 0,
        "purchases": 0,
    }
    _write_json(report_dir / "chronos-neon-preflight-v3.json", preflight_report)
    artifact: dict[str, Any] = {
        "schema_version": "chronos-preflight-artifact-v3",
        "main_sha": main_sha,
        "workflow_sha": workflow_sha,
        "project_id": identity.project_id,
        "production_branch_id": identity.production_branch_id,
        "current_revision": EXPECTED_BEFORE_REVISION,
        "recovery_branch_id": recovery["recovery_branch_id"],
        "golden_gate": "CHRONOS_MIGRATION_READY",
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "sslmode": target.sslmode,
        "created_at": _timestamp(_utc_now()),
        "preflight_run_id": _required_public("GITHUB_RUN_ID"),
        "preflight_run_attempt": _required_public("GITHUB_RUN_ATTEMPT"),
    }
    artifact["preflight_hash"] = preflight_hash(artifact)
    signed = sign_document(artifact, api_key)
    _write_json(report_dir / "chronos-preflight-artifact-v3.json", signed)
    return preflight_report


def _create_migrator(
    database_url: str,
    target: DirectPostgresTarget,
    run_id: str,
) -> tuple[str, str, str]:
    numeric = "".join(character for character in run_id if character.isdigit())
    if not numeric:
        raise ChronosProductionError("CHRONOS_RUN_ID_INVALID")
    role = f"chronos_migrator_v3_{numeric}"[:63]
    password = secrets.token_urlsafe(48)
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s", (role,)
            )
            if cursor.fetchone() is not None:
                raise ChronosProductionError("CHRONOS_MIGRATOR_ALREADY_EXISTS")
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB CREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD %s"
                ).format(sql.Identifier(role)),
                (password,),
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {} WITH GRANT OPTION").format(
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
                    "GRANT INSERT, UPDATE, DELETE ON TABLE "
                    "public.alembic_version TO {}"
                ).format(sql.Identifier(role))
            )
            cursor.execute(
                sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(role)),
                ("managed-by:chronos-production-bootstrap-v3",),
            )
    migrator_url = build_scoped_database_url(
        target,
        username=role,
        password=password,
    )
    return role, password, migrator_url


def _disable_migrator(database_url: str, role: str) -> None:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} NOLOGIN NOCREATEROLE NOCREATEDB NOSUPERUSER "
                    "NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role))
            )


def _create_scoped_logins(migrator_url: str) -> None:
    accounts = [
        (login, group, _required(secret_name))
        for login, group, secret_name in SCOPED_LOGINS
    ]
    with psycopg.connect(migrator_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            for login, group, password in accounts:
                cursor.execute(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s", (login,)
                )
                if cursor.fetchone() is not None:
                    raise ChronosProductionError(
                        "CHRONOS_SCOPED_LOGIN_ALREADY_EXISTS"
                    )
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS PASSWORD %s"
                    ).format(sql.Identifier(login)),
                    (password,),
                )
                cursor.execute(
                    sql.SQL("GRANT {} TO {}").format(
                        sql.Identifier(group), sql.Identifier(login)
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE {} FROM CURRENT_USER").format(
                        sql.Identifier(login)
                    )
                )
                cursor.execute(
                    sql.SQL("COMMENT ON ROLE {} IS %s").format(sql.Identifier(login)),
                    ("managed-by:chronos-production-bootstrap-v3",),
                )


def _verify_scoped_logins(database_url: str, migrator_role: str) -> None:
    expected = {login: group for login, group, _ in SCOPED_LOGINS}
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                "rolreplication,rolbypassrls FROM pg_catalog.pg_roles "
                "WHERE rolname = ANY(%s) ORDER BY rolname",
                (list(expected),),
            )
            role_rows = cursor.fetchall()
            if {str(row[0]) for row in role_rows} != set(expected):
                raise ChronosProductionError("CHRONOS_SCOPED_IDENTITIES_PARTIAL")
            if any(
                not bool(row[1]) or any(bool(value) for value in row[2:])
                for row in role_rows
            ):
                raise ChronosProductionError("CHRONOS_SCOPED_LOGIN_UNSAFE")
            cursor.execute(
                "SELECT member.rolname,granted.rolname FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE member.rolname = ANY(%s) ORDER BY member.rolname,granted.rolname",
                (list(expected),),
            )
            memberships = [(str(row[0]), str(row[1])) for row in cursor.fetchall()]
            if memberships != sorted(expected.items()):
                raise ChronosProductionError("CHRONOS_SCOPED_MEMBERSHIP_MISMATCH")
            if any(group == "chronos_test_writer" for _, group in memberships):
                raise ChronosProductionError("CHRONOS_TEST_WRITER_MEMBERSHIP_FORBIDDEN")
            cursor.execute(
                "SELECT rolcanlogin,rolcreaterole,rolsuper,rolcreatedb,rolreplication,"
                "rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=%s",
                (migrator_role,),
            )
            migrator = cursor.fetchone()
            if migrator is None or any(bool(value) for value in migrator):
                raise ChronosProductionError("CHRONOS_MIGRATOR_NOT_DISABLED")


def run_migrate(report_dir: Path, preflight_path: Path) -> dict[str, Any]:
    api_key = _required("NEON_API_KEY")
    database_url = _required("NEON_BOOTSTRAP_DATABASE_URL")
    target = validate_direct_postgres_url(database_url)
    main_sha = require_sha(_required_public("GITHUB_SHA"), field="main_sha")
    workflow_sha = require_sha(
        _required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha"
    )
    if _required_public("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    if _required_public("GITHUB_REF") != EXPECTED_REF:
        raise ChronosProductionError("CHRONOS_REF_MISMATCH")
    raw_artifact = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not isinstance(raw_artifact, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_ARTIFACT_INVALID")
    artifact = verify_signed_document(cast(dict[str, Any], raw_artifact), api_key)
    client = NeonClient(api_key)
    identity = resolve_neon_identity(client, target)
    recovery_branch_id = str(artifact.get("recovery_branch_id", ""))
    recovery = client.branch(identity.project_id, recovery_branch_id)
    if str(recovery.get("parent_id", "")) != identity.production_branch_id:
        raise ChronosProductionError("CHRONOS_RECOVERY_PARENT_MISMATCH")
    assert_exact_preflight_binding(
        artifact,
        main_sha=main_sha,
        workflow_sha=workflow_sha,
        project_id=identity.project_id,
        production_branch_id=identity.production_branch_id,
        recovery_branch_id=recovery_branch_id,
    )
    before = inspect_database(database_url)
    if before["current_revision"] != EXPECTED_BEFORE_REVISION:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    run_id = _required_public("GITHUB_RUN_ID")
    migrator_role, _migrator_password, migrator_url = _create_migrator(
        database_url, target, run_id
    )
    dispatches = 1
    process_environment = dict(os.environ)
    process_environment["ROBIN_DATABASE_URL"] = migrator_url
    try:
        completed = subprocess.run(  # nosec B603
            [sys.executable, "-m", "alembic", "upgrade", MIGRATION_TARGET],
            env=process_environment,
            check=False,
            capture_output=True,
            text=False,
            timeout=300,
        )
        return_code: int | None = completed.returncode
    except subprocess.TimeoutExpired:
        return_code = None
    finally:
        process_environment.pop("ROBIN_DATABASE_URL", None)
    after = inspect_database(database_url)
    outcome = "MIGRATION_OUTCOME_AMBIGUOUS"
    try:
        _assert_post_migration(after)
    except ChronosProductionError:
        if after.get("current_revision") == EXPECTED_BEFORE_REVISION:
            outcome = "MIGRATION_NOT_APPLIED"
    else:
        outcome = "MIGRATION_CONFIRMED"
    if outcome != "MIGRATION_CONFIRMED":
        _disable_migrator(database_url, migrator_role)
        report = {
            "schema_version": "chronos-neon-migration-v3",
            "verdict": (
                "NEON_CHRONOS_MIGRATION_BLOCKED"
                if outcome == "MIGRATION_NOT_APPLIED"
                else "NEON_CHRONOS_MIGRATION_AMBIGUOUS"
            ),
            "migration_outcome": outcome,
            "migration_dispatches": dispatches,
            "subprocess_return_code": return_code,
            "revision_before": before.get("current_revision"),
            "revision_after": after.get("current_revision"),
            "migrator_login": False,
            "provider_calls": 0,
            "r2_operations": 0,
        }
        _write_json(report_dir / "chronos-neon-migration-v3.json", report)
        raise ChronosProductionError(outcome)
    _create_scoped_logins(migrator_url)
    _disable_migrator(database_url, migrator_role)
    _verify_scoped_logins(database_url, migrator_role)
    final = inspect_database(database_url)
    _assert_post_migration(final)
    nonce = _required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE")
    output: dict[str, Any] = {
        "schema_version": "chronos-bootstrap-output-v3",
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "sslmode": target.sslmode,
        "authority_username": SCOPED_LOGINS[0][0],
        "runtime_username": SCOPED_LOGINS[1][0],
        "reader_username": SCOPED_LOGINS[2][0],
        "non_secret_generation_id": generation_hash(nonce)[:16],
        "generation_hash": generation_hash(nonce),
        "server_epoch": final["server_epoch"],
        "revision": EXPECTED_AFTER_REVISION,
        "migration_dispatches": dispatches,
        "migration_outcome": outcome,
        "project_id": identity.project_id,
        "production_branch_id": identity.production_branch_id,
        "recovery_branch_id": recovery_branch_id,
        "main_sha": main_sha,
        "workflow_sha": workflow_sha,
    }
    signed_output = sign_document(output, nonce)
    _write_json(report_dir / "chronos-bootstrap-output-v3.json", signed_output)
    report = {
        "schema_version": "chronos-neon-migration-v3",
        "verdict": "NEON_CHRONOS_0014_MIGRATED",
        "scoped_identities": "CHRONOS_SCOPED_IDENTITIES_READY",
        "migration_outcome": outcome,
        "migration_dispatches": dispatches,
        "subprocess_return_code": return_code,
        "revision_before": before.get("current_revision"),
        "revision_after": after.get("current_revision"),
        "server_epoch": final.get("server_epoch"),
        "tables": final.get("tables"),
        "functions": final.get("functions"),
        "triggers": final.get("triggers"),
        "roles": final.get("roles"),
        "memberships": final.get("memberships"),
        "migrator_role": migrator_role,
        "migrator_login": False,
        "migrator_createrole": False,
        "provider_calls": 0,
        "r2_operations": 0,
        "destructive_sql": 0,
    }
    _write_json(report_dir / "chronos-neon-migration-v3.json", report)
    return report


def run_verify(report_dir: Path) -> dict[str, Any]:
    urls = {
        "authority": _required("CHRONOS_AUTHORITY_DATABASE_URL"),
        "runtime": _required("CHRONOS_RUNTIME_DATABASE_URL"),
        "reader": _required("CHRONOS_READER_DATABASE_URL"),
    }
    reports: dict[str, Any] = {}
    for role, database_url in urls.items():
        target = validate_direct_postgres_url(database_url)
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            current_user = str(_scalar(connection, "SELECT current_user"))
            revision = (
                str(
                    _scalar(
                        connection,
                        "SELECT version_num FROM public.alembic_version",
                    )
                )
                if role == "reader"
                else None
            )
            epoch = _scalar(
                connection, "SELECT pg_catalog.pg_postmaster_start_time()"
            )
            memberships = _rows(
                connection,
                "SELECT granted.rolname AS granted_role "
                "FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE member.rolname=current_user ORDER BY granted.rolname",
            )
        reports[role] = {
            "database_host": target.host,
            "database_port": target.port,
            "database_name": target.database,
            "sslmode": target.sslmode,
            "current_user": current_user,
            "revision": revision,
            "server_epoch": epoch,
            "memberships": memberships,
        }
    reader_revision = reports["reader"]["revision"]
    if reader_revision != EXPECTED_AFTER_REVISION:
        raise ChronosProductionError("CHRONOS_VERIFY_REVISION_MISMATCH")
    for report in reports.values():
        report["revision"] = reader_revision
    expected_users = {
        "authority": SCOPED_LOGINS[0][0],
        "runtime": SCOPED_LOGINS[1][0],
        "reader": SCOPED_LOGINS[2][0],
    }
    for role, username in expected_users.items():
        if reports[role]["current_user"] != username:
            raise ChronosProductionError("CHRONOS_VERIFY_SCOPED_USER_MISMATCH")
        memberships = cast(list[dict[str, Any]], reports[role]["memberships"])
        expected_group = next(
            group for login, group, _ in SCOPED_LOGINS if login == username
        )
        if memberships != [{"granted_role": expected_group}]:
            raise ChronosProductionError("CHRONOS_VERIFY_MEMBERSHIP_MISMATCH")
    if len({str(report["server_epoch"]) for report in reports.values()}) != 1:
        raise ChronosProductionError("CHRONOS_VERIFY_SERVER_EPOCH_MISMATCH")
    result = {
        "schema_version": "chronos-production-verify-v3",
        "verdict": "CHRONOS_SCOPED_IDENTITIES_READY",
        "revision": EXPECTED_AFTER_REVISION,
        "identities": reports,
        "business_data_modified": False,
        "provider_calls": 0,
        "r2_operations": 0,
    }
    _write_json(report_dir / "chronos-production-verify-v3.json", result)
    return result


def _safe_failure(mode: str, error: Exception) -> dict[str, Any]:
    if isinstance(error, ChronosProductionError):
        code = str(error)
    else:
        code = "CHRONOS_PRODUCTION_BOOTSTRAP_FAILED"
    return {
        "schema_version": "chronos-production-bootstrap-failure-v3",
        "mode": mode,
        "status": "FAILED",
        "error_code": code,
        "secret_values_observed": NO_VALUES_OBSERVED,
        "provider_calls": 0,
        "odds_credits": 0,
        "r2_operations": 0,
        "purchases": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("PREFLIGHT", "MIGRATE", "VERIFY"), required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--preflight-artifact", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "PREFLIGHT":
            result = run_preflight(args.report_dir)
        elif args.mode == "MIGRATE":
            if args.preflight_artifact is None:
                raise ChronosProductionError("CHRONOS_PREFLIGHT_ARTIFACT_REQUIRED")
            result = run_migrate(args.report_dir, args.preflight_artifact)
        else:
            result = run_verify(args.report_dir)
    except Exception as error:
        failure = _safe_failure(args.mode, error)
        _write_json(args.report_dir / "chronos-bootstrap-failure-v3.json", failure)
        print(f"CHRONOS_BOOTSTRAP_{args.mode}_FAILED:{failure['error_code']}")
        raise SystemExit(1) from None
    print(f"CHRONOS_BOOTSTRAP_{args.mode}_PASS:{result['verdict']}")


if __name__ == "__main__":
    main()
