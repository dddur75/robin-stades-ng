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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlparse

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
PROJECT_PAGE_LIMIT = 400
MAX_PROJECT_PAGES = 3
MAX_BRANCH_PAGES = 3
MAX_BRANCH_PAGE = 10_000
POSITIVE_WITNESS_GET_RESERVE = 1 + 1 + MAX_BRANCH_PAGES + 1
MAX_PROJECTS_FOR_ENDPOINT_DISCOVERY = (
    MAX_NEON_GETS - MAX_PROJECT_PAGES - POSITIVE_WITNESS_GET_RESERVE
)
MAX_PROJECT_ITEMS = MAX_PROJECTS_FOR_ENDPOINT_DISCOVERY
MAX_BRANCH_ITEMS = MAX_BRANCH_PAGE * MAX_BRANCH_PAGES
MAX_SQL_STATEMENTS = 25
EXPECTED_STATEMENT_TIMEOUT_MS = 15_000
EXPECTED_LOCK_TIMEOUT_MS = 3_000
BOOTSTRAP_AUTHORITY = "chronos_bootstrap_authority"
READONLY_STARTUP_OPTIONS = (
    "-c default_transaction_read_only=on "
    "-c statement_timeout=15000 -c lock_timeout=3000"
)

NO_GO_REASONS = frozenset(
    {
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        "DIRECT_ENDPOINT_NOT_PROVEN",
        "UNEXPECTED_DATABASE_REVISION",
        "BOOTSTRAP_AUTHORITY_INSUFFICIENT",
        "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
        "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
        "ENDPOINT_STATE_UNSUPPORTED",
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
    "SELECT current_database(), session_user, current_user, current_setting('server_version')",
    "SELECT ssl FROM pg_catalog.pg_stat_ssl WHERE pid=pg_catalog.pg_backend_pid()",
    "SELECT version_num FROM public.alembic_version ORDER BY version_num",
    "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
    "rolreplication, rolbypassrls FROM pg_catalog.pg_roles "
    "WHERE rolname=current_user",
    "SELECT count(*) = 1 AS visible FROM pg_catalog.pg_authid WHERE rolname=current_user",
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
    identity_path: str
    identity_verdict: str
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
    project_pages_read: int
    projects_observed: int
    endpoint_projects_inspected: int
    api_get_count: int
    suspend_timeout_seconds: int = -1
    project_inventory_exhaustive: bool = False
    endpoint_detail_reads: int = 0
    project_detail_reads: int = 0
    branch_pages_read: int = 0
    branch_endpoint_reads: int = 0
    cursor_continuation_requested: bool = False
    cursor_cycle_encountered: bool = False
    positive_witness_checks: tuple[str, ...] = ()


@dataclass(slots=True)
class IdentityAudit:
    identity_path: str
    project_pages_read: int = 0
    projects_observed: int = 0
    endpoint_projects_inspected: int = 0
    project_id: str | None = None
    endpoint_id: str | None = None
    branch_id: str | None = None
    project_inventory_exhaustive: bool = False
    endpoint_detail_reads: int = 0
    project_detail_reads: int = 0
    branch_pages_read: int = 0
    branch_endpoint_reads: int = 0
    cursor_continuation_requested: bool = False
    cursor_cycle_encountered: bool = False
    positive_witness_checks: list[str] = field(default_factory=list)
    project_cursor_fingerprints: set[str] = field(default_factory=set)
    branch_cursor_fingerprints: set[str] = field(default_factory=set)

    def sanitized(self, *, api_get_count: int, gate: str | None = None) -> dict[str, object]:
        evidence: dict[str, object] = {
            "identity_path": self.identity_path,
            "identity_proof_mode": (
                "POSITIVE_OWNERSHIP"
                if self.identity_path == "POSITIVE_ENDPOINT_WITNESS"
                else self.identity_path
            ),
            "project_identity_verdict": "NEON_PROJECT_IDENTITY_NOT_PROVEN",
            "project_pages_read": self.project_pages_read,
            "projects_observed": self.projects_observed,
            "endpoint_projects_inspected": self.endpoint_projects_inspected,
            "project_inventory_exhaustive": self.project_inventory_exhaustive,
            "endpoint_detail_reads": self.endpoint_detail_reads,
            "project_detail_reads": self.project_detail_reads,
            "branch_pages_read": self.branch_pages_read,
            "branch_endpoint_reads": self.branch_endpoint_reads,
            "cursor_continuation_requested": self.cursor_continuation_requested,
            "cursor_cycle_encountered": self.cursor_cycle_encountered,
            "positive_witness_checks": list(self.positive_witness_checks),
            "api_get_count": api_get_count,
        }
        if self.project_id is not None:
            evidence["project_id_sha256"] = _fingerprint(self.project_id)
        if self.endpoint_id is not None:
            evidence["endpoint_id_sha256"] = _fingerprint(self.endpoint_id)
        if self.branch_id is not None:
            evidence["branch_id_sha256"] = _fingerprint(self.branch_id)
        return evidence


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
        sanitized_evidence: Mapping[str, object] | None = None,
    ) -> None:
        if reason not in NO_GO_REASONS:
            raise ValueError("INVALID_NO_GO_REASON")
        super().__init__(reason)
        self.reason = reason
        self.gate = gate
        self.dsn_security_profile = dsn_security_profile
        self.sanitized_evidence = sanitized_evidence


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


def _safe_identifier(value: object, *, gate: str = "unsafe_identifier") -> str:
    identifier = str(value)
    if _SAFE_ID.fullmatch(identifier) is None:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
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

    def require_get_budget(self, required: int, gate: str) -> None:
        """Prove that a complete planned suffix still fits before a GET."""

        if required < 1 or self.get_count + required > MAX_NEON_GETS:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)

    def get(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/projects") or ".." in path or "?" in path or "#" in path:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_route_forbidden")
        if self.get_count >= MAX_NEON_GETS:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_get_budget_exhausted")
        self.get_count += 1
        request_url = NEON_API + path
        if query:
            request_url += "?" + urlencode(query, doseq=False, safe="")
        try:
            response = self._session.get(
                request_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_unavailable") from None
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
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_api_invalid_document")
        return cast(dict[str, Any], document)


def _project_details(document: Mapping[str, Any]) -> dict[str, Any]:
    project = document.get("project")
    if not isinstance(project, dict):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_details_missing")
    return cast(dict[str, Any], project)


def _branch_state(branch: Mapping[str, Any]) -> str:
    return str(branch.get("current_state", branch.get("state", ""))).lower()


def _project_page_cursor(document: Mapping[str, Any]) -> str | None:
    """Parse the List projects Pagination contract (`pagination.cursor`)."""

    if "pagination" not in document:
        return None
    pagination = document["pagination"]
    if not isinstance(pagination, dict) or set(pagination) != {"cursor"}:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
    cursor = pagination.get("cursor")
    if not isinstance(cursor, str) or not cursor:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
    return cursor


def _list_projects_bounded(
    client: NeonReadOnlyClient,
    audit: IdentityAudit,
) -> list[dict[str, Any]]:
    """Enumerate a complete project inventory without partial endpoint scans."""

    projects: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    while True:
        if audit.project_pages_read >= MAX_PROJECT_PAGES:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
        client.require_get_budget(
            1 + len(projects) + 1 + MAX_BRANCH_PAGES,
            "project_identity_discovery_budget_exceeded",
        )
        query: dict[str, object] = {"limit": PROJECT_PAGE_LIMIT}
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get("/projects", query=query)
        audit.project_pages_read += 1
        page = _dict_list(
            document,
            "projects",
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        )
        unavailable = document.get("unavailable_project_ids", [])
        if not isinstance(unavailable, list) or unavailable:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_inventory_incomplete")
        page_ids: list[str] = []
        for project in page:
            project_id = _safe_identifier(project.get("id", ""), gate="project_pagination_invalid")
            owner_id = project.get("owner_id")
            if not isinstance(owner_id, str) or not owner_id:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_inventory_incomplete",
                )
            page_ids.append(project_id)
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        if page_fingerprint in seen_pages:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_pagination_invalid")
        seen_pages.add(page_fingerprint)
        for project, project_id in zip(page, page_ids, strict=True):
            if project_id in seen_ids:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_inventory_duplicate_id",
                )
            seen_ids.add(project_id)
            projects.append(project)
        audit.projects_observed = len(projects)
        if len(projects) > MAX_PROJECT_ITEMS:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_identity_discovery_budget_exceeded",
            )
        next_cursor = _project_page_cursor(document)
        if next_cursor is None:
            break
        cursor_fingerprint = _fingerprint(next_cursor)
        if cursor_fingerprint in audit.project_cursor_fingerprints:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_cursor_cycle")
        audit.project_cursor_fingerprints.add(cursor_fingerprint)
        if len(projects) >= MAX_PROJECT_ITEMS:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_identity_discovery_budget_exceeded",
            )
        cursor = next_cursor
    owner_ids = {str(project["owner_id"]) for project in projects}
    if len(owner_ids) > 1:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "project_inventory_incomplete")
    client.require_get_budget(
        len(projects) + 1 + MAX_BRANCH_PAGES,
        "project_identity_discovery_budget_exceeded",
    )
    return projects


def _branch_page_cursor(
    document: Mapping[str, Any],
    audit: IdentityAudit,
) -> str | None:
    """Parse only the List branches CursorPagination (`pagination.next`)."""

    if "pagination" not in document:
        return None
    pagination = document["pagination"]
    allowed = {"next", "sort_by", "sort_order"}
    if not isinstance(pagination, dict) or not set(pagination) <= allowed:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    if pagination.get("sort_by", "updated_at") != "updated_at":
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    if pagination.get("sort_order", "asc") != "asc":
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    if "next" not in pagination:
        return None
    cursor = pagination["next"]
    if not isinstance(cursor, str) or not cursor:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    fingerprint = _fingerprint(cursor)
    if fingerprint in audit.branch_cursor_fingerprints:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
    audit.branch_cursor_fingerprints.add(fingerprint)
    return cursor


def _list_branches_bounded(
    client: NeonReadOnlyClient,
    project_id: str,
    audit: IdentityAudit,
    *,
    reserve_after: int,
) -> list[dict[str, Any]]:
    branches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    pages = 0
    while True:
        if pages >= MAX_BRANCH_PAGES:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        client.require_get_budget(1 + reserve_after, "neon_get_budget_exhausted")
        query: dict[str, object] = {
            "limit": MAX_BRANCH_PAGE,
            "sort_by": "updated_at",
            "sort_order": "asc",
            "include_deleted": "false",
        }
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get(f"/projects/{project_id}/branches", query=query)
        pages += 1
        audit.branch_pages_read += 1
        page = _dict_list(
            document,
            "branches",
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
        )
        page_ids = [
            _safe_identifier(branch.get("id", ""), gate="branch_inventory_truncated")
            for branch in page
        ]
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        if page_fingerprint in seen_pages:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        seen_pages.add(page_fingerprint)
        for branch, branch_id in zip(page, page_ids, strict=True):
            if branch_id in seen_ids:
                raise PreflightNoGo(
                    "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
                    "branch_inventory_truncated",
                )
            seen_ids.add(branch_id)
            branches.append(branch)
        if len(branches) > MAX_BRANCH_ITEMS:
            raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "branch_inventory_truncated")
        cursor = _branch_page_cursor(document, audit)
        if cursor is None:
            return branches


def _validated_project_detail(
    document: Mapping[str, Any],
    project_id: str,
    *,
    expected_owner_id: str | None,
    gate: str,
) -> dict[str, Any]:
    project = _project_details(document)
    if str(project.get("id", "")) != project_id:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    owner_id = project.get("owner_id")
    owner = project.get("owner")
    if (
        not isinstance(owner_id, str)
        or not owner_id
        or not isinstance(owner, dict)
        or (expected_owner_id is not None and owner_id != expected_owner_id)
    ):
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return project


def _project_endpoints(
    document: Mapping[str, Any],
    project_id: str,
    *,
    gate: str,
) -> list[dict[str, Any]]:
    endpoints = _dict_list(
        document,
        "endpoints",
        "NEON_PROJECT_IDENTITY_AMBIGUOUS",
    )
    for endpoint in endpoints:
        _safe_identifier(endpoint.get("id", ""), gate=gate)
        _safe_identifier(endpoint.get("branch_id", ""), gate=gate)
        if str(endpoint.get("project_id", "")) != project_id:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
        if not isinstance(endpoint.get("host"), str):
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return endpoints


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


def _positive_endpoint_candidate(
    endpoint: Mapping[str, Any],
    *,
    project_id: str,
    target: DirectPostgresTarget,
) -> bool:
    """Return an exact scoped candidate, failing closed on an invalid exact match."""

    endpoint_host = str(endpoint.get("host", "")).lower()
    if endpoint_host != target.host:
        return False
    valid = (
        str(endpoint.get("project_id", "")) == project_id
        and str(endpoint.get("type", "")) == "read_write"
        and endpoint.get("pooler_enabled") is False
        and "pooler" not in endpoint_host
        and endpoint.get("disabled") is False
    )
    if not valid:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "positive_endpoint_candidate_invalid",
        )
    return True


def _progressive_positive_candidate(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Inspect each page's project endpoints before requesting another page."""

    seen_ids: set[str] = set()
    seen_pages: set[str] = set()
    cursor: str | None = None
    while True:
        if audit.project_pages_read >= MAX_PROJECT_PAGES:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_pagination_invalid",
            )
        client.require_get_budget(
            1 + POSITIVE_WITNESS_GET_RESERVE,
            "project_identity_discovery_budget_exceeded",
        )
        query: dict[str, object] = {"limit": PROJECT_PAGE_LIMIT}
        if cursor is not None:
            query["cursor"] = cursor
        document = client.get("/projects", query=query)
        audit.project_pages_read += 1
        page = _dict_list(
            document,
            "projects",
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        )
        unavailable = document.get("unavailable_project_ids", [])
        if not isinstance(unavailable, list) or unavailable:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_inventory_incomplete",
            )
        page_ids: list[str] = []
        page_seen_ids: set[str] = set()
        for project in page:
            project_id = _safe_identifier(
                project.get("id", ""), gate="project_pagination_invalid"
            )
            _safe_identifier(
                project.get("owner_id", ""), gate="project_inventory_incomplete"
            )
            if project_id in seen_ids or project_id in page_seen_ids:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_inventory_duplicate_id",
                )
            page_ids.append(project_id)
            page_seen_ids.add(project_id)
        page_fingerprint = _fingerprint("\x00".join(page_ids))
        repeated_page = page_fingerprint in seen_pages
        seen_ids.update(page_ids)
        audit.projects_observed = len(seen_ids)
        if audit.projects_observed > MAX_PROJECT_ITEMS:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_identity_discovery_budget_exceeded",
            )
        next_cursor = _project_page_cursor(document)
        matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for index, (project, project_id) in enumerate(zip(page, page_ids, strict=True)):
            remaining_on_page = len(page) - index
            client.require_get_budget(
                remaining_on_page + POSITIVE_WITNESS_GET_RESERVE,
                "project_identity_discovery_budget_exceeded",
            )
            endpoints = _project_endpoints(
                client.get(f"/projects/{project_id}/endpoints"),
                project_id,
                gate="project_inventory_incomplete",
            )
            audit.endpoint_projects_inspected += 1
            for endpoint in endpoints:
                if _positive_endpoint_candidate(
                    endpoint,
                    project_id=project_id,
                    target=target,
                ):
                    matches.append((project, endpoint))
                    if len(matches) > 1:
                        raise PreflightNoGo(
                            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                            "positive_endpoint_match_not_unique",
                        )
        if matches:
            return matches[0]
        if next_cursor is None:
            if repeated_page:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "project_pagination_invalid",
                )
            seen_pages.add(page_fingerprint)
            audit.project_inventory_exhaustive = True
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "dsn_endpoint_match_missing",
            )
        cursor_fingerprint = _fingerprint(next_cursor)
        if cursor_fingerprint in audit.project_cursor_fingerprints:
            audit.cursor_cycle_encountered = True
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_cursor_cycle",
            )
        if repeated_page:
            raise PreflightNoGo(
                "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                "project_pagination_invalid",
            )
        seen_pages.add(page_fingerprint)
        audit.project_cursor_fingerprints.add(cursor_fingerprint)
        audit.cursor_continuation_requested = True
        cursor = next_cursor


def _endpoint_detail(
    document: Mapping[str, Any],
    *,
    project_id: str,
    candidate: Mapping[str, Any],
    target: DirectPostgresTarget,
    allow_idle: bool = False,
) -> dict[str, Any]:
    endpoint = document.get("endpoint")
    if not isinstance(endpoint, dict):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "endpoint_detail_missing",
        )
    detailed = cast(dict[str, Any], endpoint)
    _safe_identifier(detailed.get("id", ""), gate="endpoint_detail_invalid")
    _safe_identifier(detailed.get("project_id", ""), gate="endpoint_detail_invalid")
    _safe_identifier(detailed.get("branch_id", ""), gate="endpoint_detail_invalid")
    if not isinstance(detailed.get("host"), str):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "endpoint_detail_invalid",
        )
    accepted_states = {"active", "idle"} if allow_idle else {"active"}
    current_state = str(detailed.get("current_state", "")).lower()
    pending_state = detailed.get("pending_state")
    if allow_idle and current_state not in accepted_states:
        raise PreflightNoGo(
            "ENDPOINT_STATE_UNSUPPORTED",
            "endpoint_state_unsupported",
        )
    comparisons = (
        (detailed.get("id") == candidate.get("id"), "endpoint_detail_id_mismatch"),
        (
            detailed.get("project_id") == project_id,
            "endpoint_detail_project_mismatch",
        ),
        (
            detailed.get("branch_id") == candidate.get("branch_id"),
            "endpoint_detail_branch_mismatch",
        ),
        (
            str(detailed.get("host", "")).lower() == target.host,
            "endpoint_detail_host_mismatch",
        ),
        (detailed.get("type") == "read_write", "endpoint_detail_type_mismatch"),
        (current_state in accepted_states, "endpoint_detail_not_active"),
        (detailed.get("disabled") is False, "endpoint_detail_disabled"),
        (detailed.get("pooler_enabled") is False, "endpoint_detail_pooled"),
        (
            pending_state in (None, current_state),
            "endpoint_detail_transitioning",
        ),
    )
    for passed, gate in comparisons:
        if not passed:
            raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    return detailed


def _positive_ownership_witness(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
    project_summary: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allow_idle: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    project_id = _safe_identifier(
        project_summary.get("id", ""), gate="project_pagination_invalid"
    )
    endpoint_id = _safe_identifier(
        candidate.get("id", ""), gate="positive_endpoint_candidate_invalid"
    )
    branch_id = _safe_identifier(
        candidate.get("branch_id", ""), gate="positive_endpoint_candidate_invalid"
    )
    client.require_get_budget(
        POSITIVE_WITNESS_GET_RESERVE,
        "project_identity_discovery_budget_exceeded",
    )
    endpoint_document = client.get(f"/projects/{project_id}/endpoints/{endpoint_id}")
    audit.endpoint_detail_reads += 1
    detailed_endpoint = _endpoint_detail(
        endpoint_document,
        project_id=project_id,
        candidate=candidate,
        target=target,
        allow_idle=allow_idle,
    )
    audit.positive_witness_checks.append("ENDPOINT_DETAIL_CONCORDANT")

    project_document = client.get(f"/projects/{project_id}")
    audit.project_detail_reads += 1
    detailed_project = _validated_project_detail(
        project_document,
        project_id,
        expected_owner_id=str(project_summary["owner_id"]),
        gate="project_detail_id_or_owner_mismatch",
    )
    audit.positive_witness_checks.append("PROJECT_DETAIL_CONCORDANT")

    branches = _list_branches_bounded(
        client,
        project_id,
        audit,
        reserve_after=1,
    )
    branch_matches = [branch for branch in branches if branch.get("id") == branch_id]
    if len(branch_matches) != 1:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_relationship_missing",
        )
    branch = branch_matches[0]
    if str(branch.get("project_id", "")) != project_id:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_project_mismatch",
        )
    if branch.get("default") is not True:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "dsn_branch_is_not_default",
        )
    if _branch_state(branch) not in {"active", "ready"}:
        raise PreflightNoGo(
            "NEON_PRODUCTION_BRANCH_AMBIGUOUS",
            "production_branch_not_ready",
        )
    audit.positive_witness_checks.append("DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT")

    branch_endpoint_document = client.get(
        f"/projects/{project_id}/branches/{branch_id}/endpoints"
    )
    audit.branch_endpoint_reads += 1
    branch_endpoints = _project_endpoints(
        branch_endpoint_document,
        project_id,
        gate="branch_endpoint_confirmation_mismatch",
    )
    confirmations = [item for item in branch_endpoints if item.get("id") == endpoint_id]
    if len(confirmations) != 1:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_endpoint_confirmation_mismatch",
        )
    confirmation = confirmations[0]
    if (
        confirmation.get("branch_id") != branch_id
        or str(confirmation.get("host", "")).lower() != target.host
        or confirmation.get("type") != "read_write"
        or confirmation.get("disabled") is not False
        or confirmation.get("pooler_enabled") is not False
    ):
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "branch_endpoint_confirmation_mismatch",
        )
    audit.positive_witness_checks.append("BRANCH_ENDPOINT_CONCORDANT")
    return detailed_project, branches, detailed_endpoint


def _resolve_neon_identity(
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    *,
    allow_idle: bool = False,
) -> NeonObservation:
    configured = os.getenv("NEON_PROJECT_ID", "").strip()
    audit = IdentityAudit(
        identity_path=("CONFIGURED_PROJECT_ID" if configured else "BOUNDED_DISCOVERY")
    )
    try:
        if configured:
            project_id = _safe_identifier(
                configured,
                gate="configured_project_invalid",
            )
            audit.project_id = project_id
            client.require_get_budget(
                1 + MAX_BRANCH_PAGES + 1,
                "neon_get_budget_exhausted",
            )
            try:
                project_document = client.get(f"/projects/{project_id}")
                audit.project_detail_reads += 1
                detailed = _validated_project_detail(
                    project_document,
                    project_id,
                    expected_owner_id=None,
                    gate="configured_project_not_accessible",
                )
            except PreflightNoGo as error:
                if error.gate == "configured_project_invalid":
                    raise
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_not_accessible",
                ) from None
            audit.projects_observed = 1
            branches = _list_branches_bounded(
                client,
                project_id,
                audit,
                reserve_after=1,
            )
            client.require_get_budget(1, "neon_get_budget_exhausted")
            endpoints = _project_endpoints(
                client.get(f"/projects/{project_id}/endpoints"),
                project_id,
                gate="configured_project_endpoint_missing",
            )
            audit.endpoint_projects_inspected = 1
            matches = [
                endpoint for endpoint in endpoints if str(endpoint["host"]).lower() == target.host
            ]
            if not matches:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_endpoint_missing",
                )
            if len(matches) != 1:
                raise PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "configured_project_endpoint_not_unique",
                )
            endpoint = matches[0]
            identity_verdict = "CONFIGURED_PROJECT_IDENTITY_PROVEN"
        else:
            audit.identity_path = "POSITIVE_ENDPOINT_WITNESS"
            project, candidate = _progressive_positive_candidate(client, target, audit)
            audit.project_id = _safe_identifier(project.get("id", ""))
            audit.endpoint_id = _safe_identifier(candidate.get("id", ""))
            audit.branch_id = _safe_identifier(candidate.get("branch_id", ""))
            audit.positive_witness_checks.extend(
                [
                    "EXACT_DSN_HOST_MATCH",
                    "PROJECT_SCOPED_ENDPOINT_INVENTORY",
                ]
            )
            detailed, branches, endpoint = _positive_ownership_witness(
                client,
                target,
                audit,
                project,
                candidate,
                allow_idle=allow_idle,
            )
            identity_verdict = "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
        return _finalize_neon_identity(
            client=client,
            target=target,
            audit=audit,
            identity_verdict=identity_verdict,
            detailed=detailed,
            branches=branches,
            endpoint=endpoint,
            allow_idle=allow_idle,
        )
    except PreflightNoGo as error:
        if error.sanitized_evidence is not None:
            raise
        raise PreflightNoGo(
            error.reason,
            error.gate,
            sanitized_evidence=audit.sanitized(
                api_get_count=client.get_count,
                gate=error.gate,
            ),
        ) from None


def _finalize_neon_identity(
    *,
    client: NeonReadOnlyClient,
    target: DirectPostgresTarget,
    audit: IdentityAudit,
    identity_verdict: str,
    detailed: Mapping[str, Any],
    branches: Sequence[Mapping[str, Any]],
    endpoint: Mapping[str, Any],
    allow_idle: bool = False,
) -> NeonObservation:
    project_id = _safe_identifier(detailed.get("id", ""))
    branches_by_id = {
        str(branch.get("id", "")): branch
        for branch in branches
        if isinstance(branch.get("id"), str)
    }
    branch = branches_by_id.get(str(endpoint.get("branch_id", "")))
    if branch is None:
        gate = (
            "configured_project_endpoint_missing"
            if audit.identity_path == "CONFIGURED_PROJECT_ID"
            else "dsn_endpoint_match_missing"
        )
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", gate)
    branch_id = _safe_identifier(branch.get("id", ""))
    endpoint_id = _safe_identifier(endpoint.get("id", ""))
    audit.project_id = project_id
    audit.branch_id = branch_id
    audit.endpoint_id = endpoint_id
    endpoint_host = str(endpoint.get("host", "")).lower()
    branch_name = str(branch.get("name", ""))
    branch_default = bool(branch.get("default", branch.get("primary", False)))
    project_name = str(detailed.get("name", ""))
    endpoint_state = str(endpoint.get("current_state", "")).lower()
    branch_state = _branch_state(branch)
    accepted_states = {"active", "idle"} if allow_idle else {"active"}
    pending_state = endpoint.get("pending_state")
    if allow_idle and endpoint_state not in accepted_states:
        raise PreflightNoGo(
            "ENDPOINT_STATE_UNSUPPORTED",
            "endpoint_state_unsupported",
        )
    endpoint_execution_state_accepted = endpoint_state == "active" or (
        allow_idle and endpoint_state == "idle"
    )
    direct = (
        endpoint_host == target.host
        and endpoint_host.endswith(".neon.tech")
        and "pooler" not in endpoint_host
        and str(endpoint.get("type", "")) == "read_write"
        and endpoint_execution_state_accepted
        and endpoint.get("pooler_enabled") is False
        and endpoint.get("disabled") is False
        and pending_state in (None, endpoint_state)
        and str(endpoint.get("project_id", "")) == project_id
    )
    if not direct:
        raise PreflightNoGo("DIRECT_ENDPOINT_NOT_PROVEN", "endpoint_not_direct")
    if branch_state not in {"active", "ready"}:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "production_branch_not_ready")
    if not branch_default:
        raise PreflightNoGo("NEON_PRODUCTION_BRANCH_AMBIGUOUS", "dsn_branch_is_not_default")
    owner = detailed.get("owner")
    if not isinstance(owner, dict):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "branch_limit_contract_missing")
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
    project_region = str(detailed.get("region_id", ""))
    endpoint_region = str(endpoint.get("region_id", ""))
    if project_region and endpoint_region and project_region != endpoint_region:
        raise PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            "project_endpoint_region_mismatch",
        )
    suspend_timeout = endpoint.get("suspend_timeout_seconds")
    if allow_idle:
        if isinstance(suspend_timeout, bool) or not isinstance(suspend_timeout, int):
            raise PreflightNoGo(
                "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
                "suspend_timeout_contract_invalid",
            )
        if suspend_timeout < -1 or suspend_timeout > 604_800 or 0 < suspend_timeout < 60:
            raise PreflightNoGo(
                "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
                "suspend_timeout_contract_invalid",
            )
    elif isinstance(suspend_timeout, bool) or not isinstance(suspend_timeout, int):
        suspend_timeout = -1
    return NeonObservation(
        identity_path=audit.identity_path,
        identity_verdict=identity_verdict,
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
        suspend_timeout_seconds=suspend_timeout,
        branch_state=branch_state,
        owner_branch_count=len(branches),
        branch_limit=branch_limit,
        history_retention_seconds=history_retention_seconds,
        project_pages_read=audit.project_pages_read,
        projects_observed=audit.projects_observed,
        endpoint_projects_inspected=audit.endpoint_projects_inspected,
        api_get_count=client.get_count,
        project_inventory_exhaustive=audit.project_inventory_exhaustive,
        endpoint_detail_reads=audit.endpoint_detail_reads,
        project_detail_reads=audit.project_detail_reads,
        branch_pages_read=audit.branch_pages_read,
        branch_endpoint_reads=audit.branch_endpoint_reads,
        cursor_continuation_requested=audit.cursor_continuation_requested,
        cursor_cycle_encountered=audit.cursor_cycle_encountered,
        positive_witness_checks=tuple(audit.positive_witness_checks),
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
            "contract_verdict": ("NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"),
            "query_parse": "INVALID",
            "unexpected_parameter_count": 0,
            "unexpected_parameter_name_hashes": [],
        }
    reviewed_keys = frozenset({"sslmode", "channel_binding"})
    unexpected = [key for key, _ in query_items if key not in reviewed_keys]
    profile: dict[str, object] = {
        "contract_verdict": ("NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT"),
        "reviewed_query_keys": sorted({key for key, _ in query_items if key in reviewed_keys}),
        "unexpected_parameter_count": len(unexpected),
        "unexpected_parameter_name_hashes": sorted(_fingerprint(key) for key in unexpected),
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


def _inspect_database(
    database_url: str,
    *,
    before_connect: Callable[[], None] | None = None,
    after_connect: Callable[[], None] | None = None,
) -> DatabaseObservation:
    statement_count = 0
    safe_database_url, _ = _validated_psycopg_url(database_url)
    try:
        if before_connect is not None:
            before_connect()
        with psycopg.connect(
            safe_database_url,
            connect_timeout=10,
            options=READONLY_STARTUP_OPTIONS,
            row_factory=dict_row,
        ) as connection:
            if after_connect is not None:
                after_connect()
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
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_state_invalid")
    return cast(dict[str, Any], document)


def _github_actions_state(
    repository: str,
    run_id: int,
    main_sha: str,
    *,
    workflow_file: str = "chronos-neon-pure-readonly-preflight-v4.yml",
) -> tuple[int, int, int]:
    counts: dict[str, int] = {}
    for status in ("queued", "in_progress"):
        document = _github_get(f"/repos/{repository}/actions/runs?status={status}&per_page=100")
        runs = document.get("workflow_runs")
        if not isinstance(runs, list):
            raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_runs_invalid")
        counts[status] = sum(
            1 for run in runs if isinstance(run, dict) and int(run.get("id", 0)) != run_id
        )
    dispatches = _github_get(
        f"/repos/{repository}/actions/workflows/"
        f"{workflow_file}/runs"
        "?event=workflow_dispatch&per_page=100"
    )
    runs = dispatches.get("workflow_runs")
    if not isinstance(runs, list):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_dispatch_history_invalid")
    exact_dispatches = [
        run for run in runs if isinstance(run, dict) and str(run.get("head_sha", "")) == main_sha
    ]
    if not any(int(run.get("id", 0)) == run_id for run in exact_dispatches):
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "current_dispatch_not_observed")
    return counts["queued"], counts["in_progress"], len(exact_dispatches)


def _bootstrap_authority_plausible(database: DatabaseObservation) -> bool:
    current_user = database.current_user
    forbidden = current_user == BOOTSTRAP_AUTHORITY or current_user.startswith(
        ("chronos_", "chronos_bootstrap_executor_")
    )
    return (
        database.session_user == current_user
        and database.lifecycle_admin_can_login
        and (database.lifecycle_admin_superuser or database.lifecycle_admin_createrole)
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
    positive = neon.identity_verdict == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
    return {
        "identity_path": neon.identity_path,
        "identity_proof_mode": "POSITIVE_OWNERSHIP" if positive else neon.identity_path,
        "project_identity_verdict": neon.identity_verdict,
        "neon_project_identity_verdict": "NEON_PROJECT_IDENTITY_PROVEN",
        "project_inventory_exhaustive": neon.project_inventory_exhaustive,
        "project_pages_read": neon.project_pages_read,
        "projects_observed": neon.projects_observed,
        "endpoint_projects_inspected": neon.endpoint_projects_inspected,
        "endpoint_inventory_reads": neon.endpoint_projects_inspected,
        "endpoint_detail_reads": neon.endpoint_detail_reads,
        "project_detail_reads": neon.project_detail_reads,
        "branch_pages_read": neon.branch_pages_read,
        "branch_endpoint_reads": neon.branch_endpoint_reads,
        "cursor_continuation_requested": neon.cursor_continuation_requested,
        "cursor_cycle_encountered": neon.cursor_cycle_encountered,
        "positive_witness_checks": list(neon.positive_witness_checks),
        "project_id_sha256": _fingerprint(neon.project_id),
        "project_name_sha256": _fingerprint(neon.project_name),
        "region": neon.region,
        "production_branch_id_sha256": _fingerprint(neon.branch_id),
        "production_branch_name_sha256": _fingerprint(neon.branch_name),
        "production_branch_default": neon.branch_default,
        "production_branch_parent_id_sha256": (
            _fingerprint(neon.branch_parent_id) if neon.branch_parent_id is not None else None
        ),
        "recovery_parent_id_sha256": _fingerprint(neon.branch_id),
        "endpoint_id_sha256": _fingerprint(neon.endpoint_id),
        "endpoint_host_sha256": _fingerprint(neon.endpoint_host),
        "endpoint_state": neon.endpoint_state,
        "suspend_timeout_seconds": neon.suspend_timeout_seconds,
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
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": {
            "repository": EXPECTED_REPOSITORY,
            "ref": EXPECTED_REF,
            "main_sha": os.environ["GITHUB_SHA"],
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        },
        "verdict": decision.verdict,
        "reason": decision.reason,
        "dsn_contract_verdict": ("NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"),
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
            "bootstrap_authority_plausible": _bootstrap_authority_plausible(database),
            "existing_chronos_roles": _sanitize_rows(
                database.chronos_roles,
                identity_keys=frozenset({"rolname"}),
            ),
            "existing_chronos_memberships": _sanitize_rows(
                database.chronos_memberships,
                identity_keys=frozenset({"granted_role", "member_role", "grantor_role"}),
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
    sanitized_evidence: Mapping[str, object] | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": REPORT_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
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
    if sanitized_evidence is not None:
        report["neon"] = dict(sanitized_evidence)
    return report


def run_preflight() -> dict[str, object]:
    repository = _required_context("GITHUB_REPOSITORY")
    git_ref = _required_context("GITHUB_REF")
    main_sha = _required_context("GITHUB_SHA")
    run_attempt = _required_context("GITHUB_RUN_ATTEMPT")
    run_id = int(_required_context("GITHUB_RUN_ID"))
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_source_not_exact_main")
    if _HEX_SHA.fullmatch(main_sha) is None:
        raise PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_sha_invalid")
    if run_attempt != "1":
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "workflow_rerun_forbidden")
    queue_count, in_progress_count, dispatch_count = _github_actions_state(
        repository,
        run_id,
        main_sha,
    )
    if dispatch_count != 1:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "exact_main_dispatch_not_unique")
    if queue_count != 0 or in_progress_count != 0:
        raise PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_not_quiescent")
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
                database.revision_count == 1 and database.revision == EXPECTED_REVISION
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
            sanitized_evidence=error.sanitized_evidence,
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
            sanitized_evidence=error.sanitized_evidence,
        )
    except Exception:
        report = _no_go_report("NEON_PROJECT_IDENTITY_AMBIGUOUS", "unexpected_sanitized_failure")
    _write_report(args.report, report)
    print(str(report["verdict"]))


if __name__ == "__main__":
    main()
