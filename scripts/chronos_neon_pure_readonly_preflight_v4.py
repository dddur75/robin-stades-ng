"""Pure read-only Neon and PostgreSQL preflight for a future Chronos migration.

The command emits a sanitized report. It never creates a Neon resource, never
executes Alembic, and never submits SQL outside an explicitly read-only
transaction. Expected NO-GO outcomes are successful observations, not retries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlparse

import psycopg
import requests
from psycopg.rows import dict_row

from robin.chronos_production import (
    EXPECTED_BEFORE_REVISION,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    DirectPostgresTarget,
    validate_direct_postgres_url,
)

NEON_API = "https://console.neon.tech/api/v2"
EXPECTED_REVISION = EXPECTED_BEFORE_REVISION
REPORT_SCHEMA = "chronos-neon-pure-readonly-preflight-v4"
GO_VERDICT = "CHRONOS_NEON_MIGRATION_READY_FOR_SEPARATE_AUTHORIZATION"
NO_GO_VERDICT = "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"
MAX_NEON_GETS = 25
MAX_PROJECT_SCAN = 11
MAX_BRANCH_PAGE = 10_000
MAX_SQL_STATEMENTS = 25
EXPECTED_STATEMENT_TIMEOUT_MS = 15_000
EXPECTED_LOCK_TIMEOUT_MS = 3_000
BOOTSTRAP_AUTHORITY = "chronos_bootstrap_authority"

NO_GO_REASONS = frozenset(
    {
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        "DIRECT_ENDPOINT_NOT_PROVEN",
        "UNEXPECTED_DATABASE_REVISION",
        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        "RECOVERY_BRANCH_NOT_FEASIBLE",
        "PURCHASE_REQUIRED",
        "SECRET_MISSING",
    }
)

SQL_STATEMENTS: tuple[str, ...] = (
    "BEGIN READ ONLY",
    "SHOW default_transaction_read_only",
    "SHOW transaction_read_only",
    "SHOW statement_timeout",
    "SHOW lock_timeout",
    "SELECT current_database(), session_user, current_user, "
    "current_setting('server_version')",
    "SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid=pg_catalog.pg_backend_pid()",
    "SELECT version_num FROM public.alembic_version ORDER BY version_num",
    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
    "rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
    "WHERE rolname=current_user",
    "SELECT count(*) = 1 AS visible FROM pg_catalog.pg_authid "
    "WHERE rolname=current_user",
    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
    "rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
    "WHERE rolname LIKE 'chronos_%' ORDER BY rolname",
    "SELECT granted.rolname AS granted_role, member.rolname AS member_role, "
    "grantor.rolname AS grantor_role, m.admin_option "
    "FROM pg_catalog.pg_auth_members m "
    "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
    "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
    "JOIN pg_catalog.pg_roles grantor ON grantor.oid=m.grantor "
    "WHERE granted.rolname LIKE 'chronos_%' "
    "OR member.rolname LIKE 'chronos_%' ORDER BY 1,2,3",
    "SELECT 'relation' AS object_type, n.nspname AS schema_name, "
    "c.relname AS object_name FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
    "WHERE n.nspname='public' AND c.relname LIKE 'chronos_%' "
    "UNION ALL SELECT 'function', n.nspname, p.proname "
    "FROM pg_catalog.pg_proc p "
    "JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
    "WHERE n.nspname='public' AND p.proname LIKE 'chronos_%' "
    "ORDER BY 1,2,3",
    "ROLLBACK",
)

_SAFE_ID = re.compile(r"^[a-z0-9-]{1,60}$")
_HEX_SHA = re.compile(r"^[0-9a-f]{40}$")


class JsonGetSession(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: int,
        allow_redirects: bool,
    ) -> requests.Response: ...


@dataclass(frozen=True, slots=True)
class GateChecks:
    secrets_present: bool
    project_identity_verified: bool
    production_branch_verified: bool
    direct_endpoint_verified: bool
    ssl_verified: bool
    expected_revision_verified: bool
    bootstrap_authority_plausible: bool
    recovery_branch_feasible: bool
    purchase_required: bool
    github_queue_empty: bool
    github_in_progress_empty: bool
    github_dispatch_unique: bool


@dataclass(frozen=True, slots=True)
class GateDecision:
    verdict: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class NeonObservation:
    project_id: str
    project_name: str
    region: str
    branch_id: str
    branch_name: str
    branch_default: bool
    branch_parent_id: str | None
    endpoint_id: str
    endpoint_host: str
    endpoint_state: str
    branch_state: str
    owner_branch_count: int
    branch_limit: int
    history_retention_seconds: int
    api_get_count: int


@dataclass(frozen=True, slots=True)
class DatabaseObservation:
    database_name: str
    session_user: str
    current_user: str
    postgresql_version: str
    ssl: bool
    revision: str
    revision_count: int
    default_transaction_read_only: bool
    transaction_read_only: bool
    statement_timeout_ms: int
    lock_timeout_ms: int
    lifecycle_admin_can_login: bool
    lifecycle_admin_superuser: bool
    lifecycle_admin_createrole: bool
    privileged_catalog_visible: bool
    chronos_roles: tuple[dict[str, object], ...]
    chronos_memberships: tuple[dict[str, object], ...]
    chronos_objects: tuple[dict[str, object], ...]
    sql_statement_count: int


class PreflightNoGo(RuntimeError):
    """Sanitized expected refusal with an approved reason code."""

    def __init__(
        self,
        reason: str,
        gate: str,
        *,
        dsn_security_profile: Mapping[str, object] | None = None,
    ) -> None:
        if reason not in NO_GO_REASONS:
            raise ValueError("INVALID_NO_GO_REASON")
        super().__init__(reason)
        self.reason = reason
        self.gate = gate
        self.dsn_security_profile = dsn_security_profile


def evaluate_checks(checks: GateChecks) -> GateDecision:
    """Apply the approved deterministic GO/NO-GO priority."""

    priority = (
        (not checks.secrets_present, "SECRET_MISSING"),
        (not checks.project_identity_verified, "NEON_PROJECT_IDENTITY_AMBIGUOUS"),
        (not checks.production_branch_verified, "NEON_PRODUCTION_BRANCH_AMBIGUOUS"),
        (
            not checks.direct_endpoint_verified or not checks.ssl_verified,
            "DIRECT_ENDPOINT_NOT_PROVEN",
        ),
        (not checks.expected_revision_verified, "UNEXPECTED_DATABASE_REVISION"),
        (
            not checks.bootstrap_authority_plausible,
            "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        ),
        (checks.purchase_required, "PURCHASE_REQUIRED"),
        (
            not checks.recovery_branch_feasible
            or not checks.github_queue_empty
            or not checks.github_in_progress_empty
            or not checks.github_dispatch_unique,
            "RECOVERY_BRANCH_NOT_FEASIBLE",
        ),
    )
    for failed, reason in priority:
        if failed:
            return GateDecision(NO_GO_VERDICT, reason)
    return GateDecision(GO_VERDICT, None)


def _required_context(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise PreflightNoGo("SECRET_MISSING", f"missing:{name}")
    return value


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_identifier(value: object) -> str:
    identifier = str(value)
    if _SAFE_ID.fullmatch(identifier) is None:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "unsafe_identifier")
    return identifier


def _dict_list(document: Mapping[str, Any], key: str, reason: str) -> list[dict[str, Any]]:
    value = document.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise PreflightNoGo(reason, f"invalid_neon_response:{key}")
    return [cast(dict[str, Any], item) for item in value]


class NeonReadOnlyClient:
    """GET-only Neon API client with a hard request ceiling and no retries."""

    def __init__(
        self,
        api_key: str,
        *,
        session: JsonGetSession | None = None,
    ) -> None:
        if not api_key:
            raise PreflightNoGo("SECRET_MISSING", "missing:NEON_API_KEY")
        self._api_key = api_key
        self._session = session or requests.Session()
        self.get_count = 0

    def get(self, path: str) -> dict[str, Any]:
        if not path.startswith("/projects") or ".." in path:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_route_forbidden"
            )
        if self.get_count >= MAX_NEON_GETS:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_get_budget_exhausted"
            )
        self.get_count += 1
        try:
            response = self._session.get(
                NEON_API + path,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_unavailable"
            ) from None
        if not 200 <= response.status_code < 300:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                f"neon_api_http_{response.status_code}",
            )
        try:
            document = response.json()
        except ValueError:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_invalid_json"
            ) from None
        if not isinstance(document, dict):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_invalid_document"
            )
        return cast(dict[str, Any], document)


def _project_details(document: Mapping[str, Any]) -> dict[str, Any]:
    project = document.get("project")
    if not isinstance(project, dict):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_details_missing"
        )
    return cast(dict[str, Any], project)


def _candidate_projects(client: NeonReadOnlyClient) -> list[dict[str, Any]]:
    configured = os.getenv("NEON_PROJECT_ID", "").strip()
    document = client.get(f"/projects?limit={MAX_PROJECT_SCAN + 1}")
    projects = _dict_list(document, "projects", "NEON_PROJECT_IDENTITY_AMBIGUOUS")
    if not projects or len(projects) > MAX_PROJECT_SCAN:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_scan_not_unique_bounded"
        )
    unavailable = document.get("unavailable", [])
    if not isinstance(unavailable, list) or unavailable:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_inventory_incomplete"
        )
    pagination = document.get("pagination")
    if pagination is not None:
        if not isinstance(pagination, dict) or any(pagination.values()):
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_inventory_paginated"
            )
    owner_ids = {str(project.get("owner_id", "")) for project in projects}
    if len(owner_ids) != 1 or "" in owner_ids:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_owner_scope_ambiguous"
        )
    if configured:
        project_id = _safe_identifier(configured)
        if sum(str(project.get("id", "")) == project_id for project in projects) != 1:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS", "configured_project_not_in_inventory"
            )
    return projects


def _branch_state(branch: Mapping[str, Any]) -> str:
    return str(branch.get("current_state", branch.get("state", ""))).lower()


def _complete_branch_page(document: Mapping[str, Any], count: int) -> bool:
    pagination = document.get("pagination")
    if pagination is None:
        return count < MAX_BRANCH_PAGE
    if not isinstance(pagination, dict):
        return False
    next_cursor = pagination.get("next")
    if next_cursor not in (None, ""):
        return False
    return count < MAX_BRANCH_PAGE


def _bounded_int(
    value: object,
    *,
    minimum: int,
    reason: str,
    gate: str,
) -> int:
    if isinstance(value, bool):
        raise PreflightNoGo(reason, gate)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdecimal():
        parsed = int(value)
    else:
        raise PreflightNoGo(reason, gate)
    if parsed < minimum:
        raise PreflightNoGo(reason, gate)
    return parsed


def _resolve_neon_identity(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
) -> NeonObservation:
    matches: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    projects = _candidate_projects(client)
    owner_branch_count = 0
    for project in projects:
        project_id = _safe_identifier(project.get("id", ""))
        branches = _dict_list(
            branches_document := client.get(
                f"/projects/{project_id}/branches?limit={MAX_BRANCH_PAGE}"
            ),
            "branches",
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        )
        if not _complete_branch_page(branches_document, len(branches)):
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE", "branch_inventory_truncated"
            )
        owner_branch_count += len(branches)
        endpoints = _dict_list(
            client.get(f"/projects/{project_id}/endpoints"),
            "endpoints",
            "DIRECT_ENDPOINT_NOT_PROVEN",
        )
        branches_by_id = {
            str(branch.get("id", "")): branch
            for branch in branches
            if isinstance(branch.get("id"), str)
        }
        for endpoint in endpoints:
            host = str(endpoint.get("host", "")).lower()
            if host != target.host:
                continue
            branch = branches_by_id.get(str(endpoint.get("branch_id", "")))
            if branch is not None:
                matches.append((project, branch, endpoint))
    if len(matches) != 1:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "dsn_endpoint_match_not_unique"
        )
    project, branch, endpoint = matches[0]
    project_id = _safe_identifier(project.get("id", ""))
    configured = os.getenv("NEON_PROJECT_ID", "").strip()
    if configured and configured != project_id:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "configured_project_mismatch"
        )
    detailed = _project_details(client.get(f"/projects/{project_id}"))
    branch_id = _safe_identifier(branch.get("id", ""))
    endpoint_id = _safe_identifier(endpoint.get("id", ""))
    endpoint_host = str(endpoint.get("host", "")).lower()
    branch_name = str(branch.get("name", ""))
    branch_default = bool(branch.get("default", branch.get("primary", False)))
    project_name = str(detailed.get("name", ""))
    endpoint_state = str(endpoint.get("current_state", "")).lower()
    branch_state = _branch_state(branch)
    direct = (
        endpoint_host == target.host
        and endpoint_host.endswith(".neon.tech")
        and "pooler" not in endpoint_host
        and str(endpoint.get("type", "")) == "read_write"
        and endpoint_state == "active"
        and not bool(endpoint.get("disabled", False))
    )
    if not direct:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "endpoint_not_direct")
    if branch_state not in {"active", "ready"}:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS", "production_branch_not_ready"
        )
    if not branch_default:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS", "dsn_branch_is_not_default"
        )
    if str(detailed.get("owner_id", "")) != str(project.get("owner_id", "")):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_owner_detail_mismatch"
        )
    owner = detailed.get("owner")
    if not isinstance(owner, dict):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "branch_limit_contract_missing"
        )
    branch_limit = _bounded_int(
        owner.get("branches_limit"),
        minimum=1,
        reason="RECOVERY_BRANCH_NOT_FEASIBLE",
        gate="branch_limit_contract_invalid",
    )
    history_retention_seconds = _bounded_int(
        detailed.get("history_retention_seconds"),
        minimum=0,
        reason="RECOVERY_BRANCH_NOT_FEASIBLE",
        gate="history_retention_contract_invalid",
    )
    parent = branch.get("parent_id")
    parent_id = str(parent) if isinstance(parent, str) and parent else None
    region = str(endpoint.get("region_id", detailed.get("region_id", "")))
    return NeonObservation(
        project_id=project_id,
        project_name=project_name,
        region=region,
        branch_id=branch_id,
        branch_name=branch_name,
        branch_default=branch_default,
        branch_parent_id=parent_id,
        endpoint_id=endpoint_id,
        endpoint_host=endpoint_host,
        endpoint_state=endpoint_state,
        branch_state=branch_state,
        owner_branch_count=owner_branch_count,
        branch_limit=branch_limit,
        history_retention_seconds=history_retention_seconds,
        api_get_count=client.get_count,
    )


def _milliseconds(value: object) -> int:
    text = str(value).strip().lower()
    units = (("ms", 1), ("s", 1_000), ("min", 60_000))
    for suffix, multiplier in units:
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return int(float(number) * multiplier)
            except ValueError:
                break
    raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "timeout_setting_invalid")


def _validated_psycopg_url(database_url: str) -> tuple[str, DirectPostgresTarget]:
    """Return a psycopg DSN accepted by the shared canonical validator."""

    try:
        target = validate_direct_postgres_url(database_url)
    except ChronosProductionError as error:
        parameter_gates = {
            "CHRONOS_DATABASE_URL_PARAMETERS_FORBIDDEN",
            "CHRONOS_CHANNEL_BINDING_REQUIRED",
        }
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            (
                "database_url_parameters_forbidden"
                if str(error) in parameter_gates
                else "direct_database_url_invalid"
            ),
            dsn_security_profile=_invalid_dsn_security_profile(database_url),
        ) from None
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return normalized, target


def _target_dsn_security_profile(
    target: DirectPostgresTarget,
) -> dict[str, object]:
    query_keys = ["sslmode"]
    if target.channel_binding is not None:
        query_keys.append("channel_binding")
    return {
        "contract_verdict": "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT",
        "query_keys": sorted(query_keys),
        "sslmode": target.sslmode,
        "channel_binding": target.channel_binding,
        "unexpected_parameter_count": 0,
        "unexpected_parameter_name_hashes": [],
    }


def _invalid_dsn_security_profile(database_url: str) -> dict[str, object]:
    """Describe only reviewed keys; hash every unreviewed query-key name."""

    try:
        parsed = urlparse(database_url)
        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
    except (TypeError, UnicodeError, ValueError):
        return {
            "contract_verdict": (
                "NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"
            ),
            "query_parse": "INVALID",
            "unexpected_parameter_count": 0,
            "unexpected_parameter_name_hashes": [],
        }
    reviewed_keys = frozenset({"sslmode", "channel_binding"})
    unexpected = [key for key, _ in query_items if key not in reviewed_keys]
    profile: dict[str, object] = {
        "contract_verdict": (
            "NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"
        ),
        "reviewed_query_keys": sorted(
            {key for key, _ in query_items if key in reviewed_keys}
        ),
        "unexpected_parameter_count": len(unexpected),
        "unexpected_parameter_name_hashes": sorted(
            _fingerprint(key) for key in unexpected
        ),
    }
    values: dict[str, list[str]] = {}
    for key, value in query_items:
        if key in reviewed_keys:
            values.setdefault(key, []).append(value)
    ssl_values = values.get("sslmode", [])
    if len(ssl_values) == 1 and ssl_values[0] in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        profile["sslmode"] = ssl_values[0]
    binding_values = values.get("channel_binding", [])
    if len(binding_values) == 1 and binding_values[0] == "require":
        profile["channel_binding"] = "require"
    return profile


def _one(cursor: psycopg.Cursor[dict[str, Any]]) -> dict[str, Any]:
    row = cursor.fetchone()
    if row is None:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "postgresql_row_missing")
    return row


def _read_revisions(
    cursor: psycopg.Cursor[dict[str, Any]],
) -> tuple[str, ...]:
    try:
        cursor.execute(SQL_STATEMENTS[7])
        return tuple(str(row["version_num"]) for row in cursor.fetchall())
    except Exception:
        raise PreflightNoGo(
            "UNEXPECTED_DATABASE_REVISION", "alembic_revision_unavailable"
        ) from None


def _read_authority_inventory(
    cursor: psycopg.Cursor[dict[str, Any]],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    try:
        cursor.execute(SQL_STATEMENTS[8])
        lifecycle_admin = _one(cursor)
        cursor.execute(SQL_STATEMENTS[9])
        catalog = _one(cursor)
        cursor.execute(SQL_STATEMENTS[10])
        roles = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        cursor.execute(SQL_STATEMENTS[11])
        memberships = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        cursor.execute(SQL_STATEMENTS[12])
        objects = tuple(cast(dict[str, object], row) for row in cursor.fetchall())
        return lifecycle_admin, catalog, roles, memberships, objects
    except Exception:
        raise PreflightNoGo(
            "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
            "bootstrap_authority_inspection_failed",
        ) from None


def _inspect_database(database_url: str) -> DatabaseObservation:
    statement_count = 0
    safe_database_url, _ = _validated_psycopg_url(database_url)
    try:
        with psycopg.connect(
            safe_database_url,
            connect_timeout=10,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=15000 -c lock_timeout=3000"
            ),
            row_factory=dict_row,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(SQL_STATEMENTS[0])
                statement_count += 1
                cursor.execute(SQL_STATEMENTS[1])
                statement_count += 1
                default_read_only = str(_one(cursor)["default_transaction_read_only"])
                cursor.execute(SQL_STATEMENTS[2])
                statement_count += 1
                transaction_read_only = str(_one(cursor)["transaction_read_only"])
                cursor.execute(SQL_STATEMENTS[3])
                statement_count += 1
                statement_timeout = next(iter(_one(cursor).values()))
                cursor.execute(SQL_STATEMENTS[4])
                statement_count += 1
                lock_timeout = next(iter(_one(cursor).values()))
                cursor.execute(SQL_STATEMENTS[5])
                statement_count += 1
                identity = _one(cursor)
                cursor.execute(SQL_STATEMENTS[6])
                statement_count += 1
                ssl_row = _one(cursor)
                revisions = _read_revisions(cursor)
                statement_count += 1
                (
                    lifecycle_admin,
                    catalog,
                    roles,
                    memberships,
                    objects,
                ) = _read_authority_inventory(cursor)
                statement_count += 5
                cursor.execute(SQL_STATEMENTS[13])
                statement_count += 1
    except PreflightNoGo:
        raise
    except Exception:
        raise PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN", "postgresql_readonly_inspection_failed"
        ) from None
    if statement_count > MAX_SQL_STATEMENTS:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "sql_budget_exhausted")
    return DatabaseObservation(
        database_name=str(identity["current_database"]),
        session_user=str(identity["session_user"]),
        current_user=str(identity["current_user"]),
        postgresql_version=str(identity["current_setting"]),
        ssl=bool(ssl_row["ssl"]),
        revision=revisions[0] if len(revisions) == 1 else "NOT_SINGLETON",
        revision_count=len(revisions),
        default_transaction_read_only=default_read_only == "on",
        transaction_read_only=transaction_read_only == "on",
        statement_timeout_ms=_milliseconds(statement_timeout),
        lock_timeout_ms=_milliseconds(lock_timeout),
        lifecycle_admin_can_login=bool(lifecycle_admin["rolcanlogin"]),
        lifecycle_admin_superuser=bool(lifecycle_admin["rolsuper"]),
        lifecycle_admin_createrole=bool(lifecycle_admin["rolcreaterole"]),
        privileged_catalog_visible=bool(catalog["visible"]),
        chronos_roles=roles,
        chronos_memberships=memberships,
        chronos_objects=objects,
        sql_statement_count=statement_count,
    )


def _github_get(path: str) -> dict[str, Any]:
    try:
        response = requests.get(
            "https://api.github.com" + path,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
    except requests.RequestException:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_unavailable"
        ) from None
    if not 200 <= response.status_code < 300:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE",
            f"github_actions_http_{response.status_code}",
        )
    try:
        document = response.json()
    except ValueError:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_invalid"
        ) from None
    if not isinstance(document, dict):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_invalid"
        )
    return cast(dict[str, Any], document)


def _github_actions_state(
    repository: str,
    run_id: int,
    main_sha: str,
) -> tuple[int, int, int]:
    counts: dict[str, int] = {}
    for status in ("queued", "in_progress"):
        document = _github_get(
            f"/repos/{repository}/actions/runs?status={status}&per_page=100"
        )
        runs = document.get("workflow_runs")
        if not isinstance(runs, list):
            raise PreflightNoGo(
                "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_runs_invalid"
            )
        counts[status] = sum(
            1
            for run in runs
            if isinstance(run, dict) and int(run.get("id", 0)) != run_id
        )
    dispatches = _github_get(
        f"/repos/{repository}/actions/workflows/"
        "chronos-neon-pure-readonly-preflight-v4.yml/runs"
        "?event=workflow_dispatch&per_page=100"
    )
    runs = dispatches.get("workflow_runs")
    if not isinstance(runs, list):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_dispatch_history_invalid"
        )
    exact_dispatches = [
        run
        for run in runs
        if isinstance(run, dict) and str(run.get("head_sha", "")) == main_sha
    ]
    if not any(int(run.get("id", 0)) == run_id for run in exact_dispatches):
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "current_dispatch_not_observed"
        )
    return counts["queued"], counts["in_progress"], len(exact_dispatches)


def _bootstrap_authority_plausible(database: DatabaseObservation) -> bool:
    current_user = database.current_user
    forbidden = current_user == BOOTSTRAP_AUTHORITY or current_user.startswith(
        ("chronos_", "chronos_bootstrap_executor_")
    )
    return (
        database.session_user == current_user
        and database.lifecycle_admin_can_login
        and (
            database.lifecycle_admin_superuser
            or database.lifecycle_admin_createrole
        )
        and database.privileged_catalog_visible
        and not forbidden
    )


def _sanitize_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    identity_keys: frozenset[str],
) -> list[dict[str, object]]:
    sanitized: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = {}
        for key, value in row.items():
            if key in identity_keys:
                item[f"{key}_sha256"] = _fingerprint(str(value))
            else:
                item[key] = value
        sanitized.append(item)
    return sanitized


def _sanitized_neon(neon: NeonObservation) -> dict[str, object]:
    return {
        "project_id_sha256": _fingerprint(neon.project_id),
        "project_name_sha256": _fingerprint(neon.project_name),
        "region": neon.region,
        "production_branch_id_sha256": _fingerprint(neon.branch_id),
        "production_branch_name_sha256": _fingerprint(neon.branch_name),
        "production_branch_default": neon.branch_default,
        "production_branch_parent_id_sha256": (
            _fingerprint(neon.branch_parent_id)
            if neon.branch_parent_id is not None
            else None
        ),
        "recovery_parent_id_sha256": _fingerprint(neon.branch_id),
        "endpoint_id_sha256": _fingerprint(neon.endpoint_id),
        "endpoint_host_sha256": _fingerprint(neon.endpoint_host),
        "endpoint_state": neon.endpoint_state,
        "branch_state": neon.branch_state,
        "owner_branch_count": neon.owner_branch_count,
        "branch_limit": neon.branch_limit,
        "history_retention_seconds": neon.history_retention_seconds,
        "api_get_count": neon.api_get_count,
        "api_post_count": 0,
        "api_put_count": 0,
        "api_patch_count": 0,
        "api_delete_count": 0,
    }


def _report(
    *,
    checks: GateChecks,
    decision: GateDecision,
    neon: NeonObservation,
    database: DatabaseObservation,
    queue_count: int,
    in_progress_count: int,
    dispatch_count: int,
    dsn_security_profile: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "source": {
            "repository": EXPECTED_REPOSITORY,
            "ref": EXPECTED_REF,
            "main_sha": os.environ["GITHUB_SHA"],
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        },
        "verdict": decision.verdict,
        "reason": decision.reason,
        "dsn_contract_verdict": (
            "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"
        ),
        "dsn_security_profile": dict(dsn_security_profile),
        "checks": asdict(checks),
        "neon": _sanitized_neon(neon),
        "postgresql": {
            "database_name_sha256": _fingerprint(database.database_name),
            "postgresql_version": database.postgresql_version,
            "current_revision": database.revision,
            "revision_count": database.revision_count,
            "ssl_verified": database.ssl,
            "default_transaction_read_only": database.default_transaction_read_only,
            "transaction_read_only": database.transaction_read_only,
            "statement_timeout_ms": database.statement_timeout_ms,
            "lock_timeout_ms": database.lock_timeout_ms,
            "lifecycle_admin_sha256": _fingerprint(database.current_user),
            "bootstrap_authority_plausible": _bootstrap_authority_plausible(
                database
            ),
            "existing_chronos_roles": _sanitize_rows(
                database.chronos_roles,
                identity_keys=frozenset({"rolname"}),
            ),
            "existing_chronos_memberships": _sanitize_rows(
                database.chronos_memberships,
                identity_keys=frozenset(
                    {"granted_role", "member_role", "grantor_role"}
                ),
            ),
            "existing_chronos_objects": _sanitize_rows(
                database.chronos_objects,
                identity_keys=frozenset({"schema_name", "object_name"}),
            ),
            "sql_statement_count": database.sql_statement_count,
            "sql_write_count": 0,
        },
        "github_actions": {
            "queued": queue_count,
            "in_progress": in_progress_count,
            "current_run_excluded": int(os.environ["GITHUB_RUN_ID"]),
            "exact_main_dispatch_count": dispatch_count,
        },
        "effects": {
            "neon_mutations": 0,
            "production_sql_writes": 0,
            "recovery_branch_creations": 0,
            "role_creations": 0,
            "migration_0014": 0,
            "r2_operations": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
        },
    }


def _no_go_report(
    reason: str,
    gate: str,
    *,
    dsn_security_profile: Mapping[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "source": {
            "repository": os.getenv("GITHUB_REPOSITORY", "UNKNOWN"),
            "ref": os.getenv("GITHUB_REF", "UNKNOWN"),
            "main_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
            "run_id": os.getenv("GITHUB_RUN_ID", "UNKNOWN"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "UNKNOWN"),
        },
        "verdict": NO_GO_VERDICT,
        "reason": reason,
        "failed_gate": gate,
        "effects": {
            "neon_mutations": 0,
            "production_sql_writes": 0,
            "recovery_branch_creations": 0,
            "role_creations": 0,
            "migration_0014": 0,
            "r2_operations": 0,
            "provider_calls": 0,
            "purchases": 0,
            "sensitive_values_exposed": 0,
        },
    }
    if dsn_security_profile is not None:
        report["dsn_security_profile"] = dict(dsn_security_profile)
        report["dsn_contract_verdict"] = dsn_security_profile.get(
            "contract_verdict",
            "NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT",
        )
    return report


def run_preflight() -> dict[str, object]:
    repository = _required_context("GITHUB_REPOSITORY")
    git_ref = _required_context("GITHUB_REF")
    main_sha = _required_context("GITHUB_SHA")
    run_attempt = _required_context("GITHUB_RUN_ATTEMPT")
    run_id = int(_required_context("GITHUB_RUN_ID"))
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_source_not_exact_main"
        )
    if _HEX_SHA.fullmatch(main_sha) is None:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_sha_invalid"
        )
    if run_attempt != "1":
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "workflow_rerun_forbidden"
        )
    queue_count, in_progress_count, dispatch_count = _github_actions_state(
        repository,
        run_id,
        main_sha,
    )
    if dispatch_count != 1:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "exact_main_dispatch_not_unique"
        )
    if queue_count != 0 or in_progress_count != 0:
        raise PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_not_quiescent"
        )
    api_key = _required_context("NEON_API_KEY")
    database_url = _required_context("NEON_BOOTSTRAP_DATABASE_URL")
    _, target = _validated_psycopg_url(database_url)
    dsn_security_profile = _target_dsn_security_profile(target)
    try:
        client = NeonReadOnlyClient(api_key)
        neon = _resolve_neon_identity(client, target)
        database = _inspect_database(database_url)
        purchase_required = neon.owner_branch_count + 1 > neon.branch_limit
        recovery_feasible = (
            neon.history_retention_seconds > 0
            and neon.branch_id != ""
            and neon.branch_state in {"active", "ready"}
            and not purchase_required
        )
        sql_safety = (
            database.default_transaction_read_only
            and database.transaction_read_only
            and database.statement_timeout_ms == EXPECTED_STATEMENT_TIMEOUT_MS
            and database.lock_timeout_ms == EXPECTED_LOCK_TIMEOUT_MS
            and database.sql_statement_count <= MAX_SQL_STATEMENTS
        )
        checks = GateChecks(
            secrets_present=True,
            project_identity_verified=True,
            production_branch_verified=True,
            direct_endpoint_verified=sql_safety,
            ssl_verified=database.ssl,
            expected_revision_verified=(
                database.revision_count == 1
                and database.revision == EXPECTED_REVISION
            ),
            bootstrap_authority_plausible=_bootstrap_authority_plausible(database),
            recovery_branch_feasible=recovery_feasible,
            purchase_required=purchase_required,
            github_queue_empty=queue_count == 0,
            github_in_progress_empty=in_progress_count == 0,
            github_dispatch_unique=dispatch_count == 1,
        )
        decision = evaluate_checks(checks)
        return _report(
            checks=checks,
            decision=decision,
            neon=neon,
            database=database,
            queue_count=queue_count,
            in_progress_count=in_progress_count,
            dispatch_count=dispatch_count,
            dsn_security_profile=dsn_security_profile,
        )
    except PreflightNoGo as error:
        raise PreflightNoGo(
            error.reason,
            error.gate,
            dsn_security_profile=dsn_security_profile,
        ) from None


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_preflight()
    except PreflightNoGo as error:
        report = _no_go_report(
            error.reason,
            error.gate,
            dsn_security_profile=error.dsn_security_profile,
        )
    except Exception:
        report = _no_go_report(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "unexpected_sanitized_failure"
        )
    _write_report(args.report, report)
    print(str(report["verdict"]))


if __name__ == "__main__":
    main()
