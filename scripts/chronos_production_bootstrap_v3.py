"""Protected manual bootstrap for Neon Chronos revision 0014.

The CLI prints only stable status codes. Secret-bearing failures are reduced to
sanitized codes and never include response bodies, SQL parameters, or URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import psycopg
import requests
from psycopg import Connection

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
from robin.chronos_role_lifecycle import (
    GROUP_ROLES,
    MIGRATOR_MARKER,
    assert_bootstrap_owner,
    assert_migrator_disabled,
    assert_post_migration_role_state,
    audit_role_edges,
    audit_terminal_lifecycle,
    disable_migrator,
    provision_chronos_group_roles,
    provision_migrator,
    provision_runtime_logins,
    role_inventory_hash,
    stable_migrator_role,
    terminalize_bootstrap_owner,
)

NEON_API = "https://console.neon.tech/api/v2"
EXPECTED_TABLES = ("chronos_effect_authorities", "chronos_effect_events")
EXPECTED_GROUPS = GROUP_ROLES
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
_NEON_ALLOWED_ROUTES = (
    re.compile(r"^GET /projects\?limit=100$"),
    re.compile(r"^GET /projects/[^/?]+$"),
    re.compile(r"^GET /projects/[^/?]+/branches\?limit=100$"),
    re.compile(r"^GET /projects/[^/?]+/branches/[^/?]+$"),
    re.compile(r"^GET /projects/[^/?]+/endpoints$"),
    re.compile(r"^POST /projects/[^/?]+/branches$"),
)


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
        route = f"{method.upper()} {path}"
        if not any(pattern.fullmatch(route) for pattern in _NEON_ALLOWED_ROUTES):
            raise ChronosProductionError("CHRONOS_NEON_ROUTE_FORBIDDEN")
        try:
            response = self._session.request(
                method.upper(),
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
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        preflight_role_inventory_hash = role_inventory_hash(connection)
    if database["current_revision"] not in {
        EXPECTED_BEFORE_REVISION,
        EXPECTED_AFTER_REVISION,
    }:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    if database["current_revision"] == EXPECTED_AFTER_REVISION:
        _assert_post_migration(database)
        migrator_role = stable_migrator_role(identity.production_branch_id)
        existing_runtime = {
            str(row["rolname"])
            for row in cast(list[dict[str, Any]], database["roles"])
            if str(row["rolname"]) in {login for login, _, _ in SCOPED_LOGINS}
        }
        resume_phase = (
            "final"
            if len(existing_runtime) == len(SCOPED_LOGINS)
            else "runtime_partial"
            if existing_runtime
            else "migrator"
        )
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            bootstrap_owner = assert_bootstrap_owner(connection)
            assert_post_migration_role_state(
                connection,
                migrator_role=migrator_role,
                bootstrap_owner=bootstrap_owner,
            )
            audit_role_edges(
                connection,
                phase=resume_phase,
                bootstrap_owner=bootstrap_owner,
                migrator_role=migrator_role,
                runtime_roles=sorted(existing_runtime),
            )
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
        "role_inventory_hash": preflight_role_inventory_hash,
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
    artifact_created_at = _utc_now()
    artifact: dict[str, Any] = {
        "schema_version": "chronos-preflight-artifact-v3",
        "main_sha": main_sha,
        "workflow_sha": workflow_sha,
        "project_id": identity.project_id,
        "production_branch_id": identity.production_branch_id,
        "current_revision": database["current_revision"],
        "role_inventory_hash": preflight_role_inventory_hash,
        "recovery_branch_id": recovery["recovery_branch_id"],
        "golden_gate": "CHRONOS_MIGRATION_READY",
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "sslmode": target.sslmode,
        "created_at": _timestamp(artifact_created_at),
        "expires_at": _timestamp(artifact_created_at + timedelta(hours=1)),
        "preflight_run_id": _required_public("GITHUB_RUN_ID"),
        "preflight_run_attempt": _required_public("GITHUB_RUN_ATTEMPT"),
    }
    artifact["preflight_hash"] = preflight_hash(artifact)
    signed = sign_document(artifact, api_key)
    _write_json(report_dir / "chronos-preflight-artifact-v3.json", signed)
    return preflight_report


def _preflight_expiry(artifact: Mapping[str, Any]) -> datetime:
    value = artifact.get("expires_at")
    if not isinstance(value, str):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_EXPIRY_MISSING")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_EXPIRY_INVALID") from None
    if expiry <= _utc_now():
        raise ChronosProductionError("CHRONOS_PREFLIGHT_EXPIRED")
    return expiry


def _runtime_accounts() -> list[tuple[str, str, str]]:
    return [
        (login, group, _required(secret_name))
        for login, group, secret_name in SCOPED_LOGINS
    ]


def _assert_migrator_disabled(
    database_url: str, role: str, bootstrap_owner: str
) -> None:
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        assert_migrator_disabled(
            connection, role=role, bootstrap_owner=bootstrap_owner
        )


_ALEMBIC_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PGSSLROOTCERT",
    "PYTHONPATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TMP",
    "TMPDIR",
    "TEMP",
    "TZ",
    "VIRTUAL_ENV",
)
_ALEMBIC_PGOPTIONS = (
    "-c statement_timeout=300000 "
    "-c idle_session_timeout=60000 "
    "-c idle_in_transaction_session_timeout=60000"
)


def _alembic_environment(database_url: str) -> dict[str, str]:
    environment = {
        name: value
        for name in _ALEMBIC_ENV_ALLOWLIST
        if (value := os.getenv(name)) is not None
    }
    environment["ROBIN_DATABASE_URL"] = database_url
    environment["PGOPTIONS"] = _ALEMBIC_PGOPTIONS
    return environment


def _attempt_cleanup_steps(steps: Sequence[Callable[[], None]]) -> None:
    errors: list[Exception] = []
    for step in steps:
        try:
            step()
        except Exception as error:
            errors.append(error)
    if errors:
        raise ChronosProductionError("CHRONOS_LIFECYCLE_CLEANUP_FAILED") from errors[0]


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
    preflight_expiry = _preflight_expiry(artifact)
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
        current_revision=str(artifact.get("current_revision", "")),
    )
    before = inspect_database(database_url)
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        migrate_role_inventory_hash = role_inventory_hash(connection)
    if artifact.get("role_inventory_hash") != migrate_role_inventory_hash:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_ROLE_INVENTORY_MISMATCH")
    if before["current_revision"] not in {
        EXPECTED_BEFORE_REVISION,
        EXPECTED_AFTER_REVISION,
    }:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    if artifact.get("current_revision") != before["current_revision"]:
        raise ChronosProductionError("CHRONOS_PREFLIGHT_REVISION_MISMATCH")
    migrator_role = stable_migrator_role(identity.production_branch_id)
    migrator_password = secrets.token_urlsafe(48)
    with psycopg.connect(database_url, connect_timeout=10) as connection:
        bootstrap_owner = assert_bootstrap_owner(
            connection, deadline=preflight_expiry
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s)",
                (migrator_role,),
            )
            role_exists = cursor.fetchone()
    migrator_exists = bool(role_exists and role_exists[0])
    group_audit: dict[str, Any] | None = None
    migrator_audit: dict[str, Any] | None = None
    final_audit: dict[str, Any] | None = None
    dispatches = 0
    return_code: int | None = 0
    outcome = "MIGRATION_RESUMED"
    after = before
    migrator_disabled = False
    owner_terminalized = False
    try:
        if before["current_revision"] == EXPECTED_BEFORE_REVISION:
            with psycopg.connect(database_url, connect_timeout=10) as connection:
                provisioned_groups = provision_chronos_group_roles(
                    connection, migrator_role=migrator_role
                )
                group_audit = provisioned_groups.report()
                runtime_at_start = {
                    str(row["role"])
                    for row in provisioned_groups.role_inventory
                    if str(row["role"]) in {login for login, _, _ in SCOPED_LOGINS}
                }
                migration_audit_phase = (
                    provisioned_groups.phase
                    if provisioned_groups.phase in {"final", "runtime_partial"}
                    else "migrator"
                )
                migrator_valid_until = min(
                    preflight_expiry,
                    _utc_now() + timedelta(minutes=6),
                )
                provisioned_migrator = provision_migrator(
                    connection,
                    role=migrator_role,
                    password=migrator_password,
                    valid_until=migrator_valid_until,
                    pinned_system_grantor=(
                        provisioned_groups.bootstrap_system_grantor
                    ),
                    audit_phase=migration_audit_phase,
                    runtime_roles=sorted(runtime_at_start),
                )
                migrator_audit = provisioned_migrator.report()
            migrator_exists = True
            migrator_url = build_scoped_database_url(
                target,
                username=migrator_role,
                password=migrator_password,
            )
            process_environment = _alembic_environment(migrator_url)
            dispatches = 1
            try:
                completed = subprocess.run(  # nosec B603
                    [sys.executable, "-m", "alembic", "upgrade", MIGRATION_TARGET],
                    env=process_environment,
                    check=False,
                    capture_output=True,
                    text=False,
                    timeout=300,
                )
                return_code = completed.returncode
            except subprocess.TimeoutExpired:
                return_code = None
            finally:
                process_environment.pop("ROBIN_DATABASE_URL", None)
                with psycopg.connect(
                    database_url, connect_timeout=10
                ) as connection:
                    disable_migrator(connection, role=migrator_role)
                migrator_disabled = True
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
                raise ChronosProductionError(outcome)
            with psycopg.connect(database_url, connect_timeout=10) as connection:
                assert_post_migration_role_state(
                    connection,
                    migrator_role=migrator_role,
                    bootstrap_owner=bootstrap_owner,
                )
        else:
            _assert_post_migration(before)
            existing_runtime = {
                str(row["rolname"])
                for row in cast(list[dict[str, Any]], before["roles"])
                if str(row["rolname"])
                in {login for login, _, _ in SCOPED_LOGINS}
            }
            resume_phase = (
                "final"
                if len(existing_runtime) == len(SCOPED_LOGINS)
                else "runtime_partial"
                if existing_runtime
                else "migrator"
            )
            with psycopg.connect(database_url, connect_timeout=10) as connection:
                assert_bootstrap_owner(connection, deadline=preflight_expiry)
                disable_migrator(connection, role=migrator_role)
                migrator_disabled = True
                assert_post_migration_role_state(
                    connection,
                    migrator_role=migrator_role,
                    bootstrap_owner=bootstrap_owner,
                )
                resumed = audit_role_edges(
                    connection,
                    phase=resume_phase,
                    bootstrap_owner=bootstrap_owner,
                    migrator_role=migrator_role,
                    runtime_roles=sorted(existing_runtime),
                )
                migrator_audit = resumed.report()

        _assert_migrator_disabled(
            database_url, migrator_role, bootstrap_owner
        )
        pinned_grantor = str(
            (migrator_audit or {}).get("bootstrap_system_grantor", "")
        )
        if not pinned_grantor:
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_GRANTOR_MISSING")
        runtime_accounts = _runtime_accounts()
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            provisioned_runtime = provision_runtime_logins(
                connection,
                accounts=runtime_accounts,
                migrator_role=migrator_role,
                pinned_system_grantor=pinned_grantor,
            )
            final_audit = provisioned_runtime.report()
        final = inspect_database(database_url)
        _assert_post_migration(final)
        _assert_migrator_disabled(
            database_url, migrator_role, bootstrap_owner
        )
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            terminalize_bootstrap_owner(connection)
        owner_terminalized = True
        reader_login, _, reader_password = runtime_accounts[2]
        reader_url = build_scoped_database_url(
            target, username=reader_login, password=reader_password
        )
        with psycopg.connect(reader_url, connect_timeout=10) as connection:
            terminal_audit = audit_terminal_lifecycle(
                connection,
                bootstrap_owner=bootstrap_owner,
                migrator_role=migrator_role,
            ).report()
        _write_json(
            report_dir / "chronos-role-edge-matrix-v1.json",
            {
                "schema_version": "chronos-role-edge-matrix-v1",
                "verdict": "BIDIRECTIONAL_ROLE_EDGE_AUDIT_READY",
                "migration_cycle": "NOT_RUN_IN_PRODUCTION_ACTIVATION",
                "password_state": {
                    "bootstrap_owner": "CLEARED_BY_COMMITTED_ALTER_ROLE",
                    "migrator": "CLEARED_BY_COMMITTED_ALTER_ROLE",
                    "catalog_visibility": "PG_AUTHID_SUPERUSER_ONLY",
                },
                "phases": [
                    report
                    for report in (
                        group_audit,
                        migrator_audit,
                        final_audit,
                        terminal_audit,
                    )
                    if report is not None
                ],
                "edges": terminal_audit["edges"],
                "edge_count": terminal_audit["edge_count"],
                "forbidden_edge_count": terminal_audit[
                    "forbidden_edge_count"
                ],
                "runtime_effective_bootstrap_edge_count": terminal_audit[
                    "runtime_effective_bootstrap_edge_count"
                ],
                "migrator_runtime_edge_count": terminal_audit[
                    "migrator_runtime_edge_count"
                ],
            },
        )
    except Exception:
        cleanup_steps: list[Callable[[], None]] = []
        if migrator_exists and not migrator_disabled:
            def cleanup_migrator() -> None:
                with psycopg.connect(database_url, connect_timeout=10) as connection:
                    disable_migrator(connection, role=migrator_role)

            cleanup_steps.append(cleanup_migrator)
        if not owner_terminalized:
            def cleanup_owner() -> None:
                with psycopg.connect(database_url, connect_timeout=10) as connection:
                    terminalize_bootstrap_owner(connection)

            cleanup_steps.append(cleanup_owner)
        _attempt_cleanup_steps(cleanup_steps)
        raise
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
        "role_edge_matrix": "chronos-role-edge-matrix-v1.json",
        "forbidden_membership": 0,
        "migrator_runtime_membership": 0,
        "runtime_effective_bootstrap_edge": 0,
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
    with psycopg.connect(urls["reader"], connect_timeout=10) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname FROM pg_catalog.pg_roles "
                "WHERE pg_catalog.shobj_description(oid,'pg_authid')=%s",
                (MIGRATOR_MARKER,),
            )
            migrators = [str(row[0]) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT DISTINCT member.rolname "
                "FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE granted.rolname=ANY(%s) AND m.admin_option "
                "AND NOT m.inherit_option AND NOT m.set_option",
                (list(GROUP_ROLES),),
            )
            owners = [str(row[0]) for row in cursor.fetchall()]
        if len(migrators) != 1 or len(owners) != 1:
            raise ChronosProductionError("CHRONOS_VERIFY_ROLE_LIFECYCLE_AMBIGUOUS")
        edge_audit = audit_terminal_lifecycle(
            connection,
            bootstrap_owner=owners[0],
            migrator_role=migrators[0],
        )
    _write_json(
        report_dir / "chronos-role-edge-matrix-v1.json",
        {
            "schema_version": "chronos-role-edge-matrix-v1",
            "verdict": "BIDIRECTIONAL_ROLE_EDGE_AUDIT_READY",
            **edge_audit.report(),
        },
    )
    result = {
        "schema_version": "chronos-production-verify-v3",
        "verdict": "CHRONOS_SCOPED_IDENTITIES_READY",
        "revision": EXPECTED_AFTER_REVISION,
        "identities": reports,
        "business_data_modified": False,
        "forbidden_membership": edge_audit.forbidden_edge_count,
        "migrator_runtime_membership": edge_audit.migrator_runtime_edge_count,
        "runtime_effective_bootstrap_edge": (
            edge_audit.runtime_effective_bootstrap_edge_count
        ),
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
