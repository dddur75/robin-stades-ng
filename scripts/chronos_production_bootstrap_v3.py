"""Protected manual bootstrap for Neon Chronos revision 0015.

The CLI prints only stable status codes. Secret-bearing failures are reduced to
sanitized codes and never include response bodies, SQL parameters, or URLs.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import psycopg
import requests
from psycopg import Connection

from robin.chronos_alembic import run_fenced_alembic
from robin.chronos_production import (
    EXPECTED_AFTER_REVISION,
    EXPECTED_BEFORE_REVISIONS,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    MIGRATION_TARGET,
    SCOPED_LOGINS,
    ChronosProductionError,
    DirectPostgresTarget,
    assert_exact_preflight_binding,
    assert_production_safety_locks,
    build_scoped_database_url,
    connect_direct_postgres,
    generation_hash,
    preflight_hash,
    require_hash,
    require_sha,
    sign_document,
    validate_direct_postgres_url,
    verify_signed_document,
)
from robin.chronos_role_lifecycle import (
    BOOTSTRAP_AUTHORITY,
    BOOTSTRAP_EXECUTOR_PREFIX,
    GROUP_ROLES,
    MIGRATOR_MARKER,
    acquire_lifecycle_lock,
    assert_executor_cannot_create_role,
    assert_migrator_disabled,
    assert_permanent_bootstrap_authority,
    assert_post_migration_role_state,
    assert_privileged_catalog_visibility,
    audit_role_edges,
    audit_terminal_lifecycle,
    cleanup_bootstrap_executor,
    disable_migrator,
    provision_bootstrap_executor,
    provision_chronos_group_roles,
    provision_migrator,
    provision_runtime_logins,
    release_lifecycle_lock,
    reset_permanent_bootstrap_authority,
    role_inventory_hash,
    role_inventory_snapshot,
    set_permanent_bootstrap_authority,
    stable_migrator_role,
)
from scripts.chronos_neon_pure_readonly_preflight_v4 import (
    NeonObservation,
    PreflightNoGo,
    require_neon_recovery_feasibility,
    resolve_neon_identity_readonly,
)

NEON_API = "https://console.neon.tech/api/v2"
RECOVERY_BRANCH_PREFIX = "chronos-pre-0015-recovery-"
MAX_RECOVERY_BRANCHES = 2
EXPECTED_TABLES = (
    "chronos_effect_authorities",
    "chronos_effect_events",
    "chronos_opportunity_claims",
    "chronos_torrent_external_effect_permits",
    "chronos_torrent_external_effect_events",
    "chronos_torrent_batches",
)
EXPECTED_GROUPS = GROUP_ROLES
EXPECTED_VIEWS = (
    "chronos_effect_accounting",
    "chronos_opportunity_claim_audit",
    "chronos_torrent_batch_audit",
    "chronos_torrent_external_effect_audit",
)
EXPECTED_FUNCTIONS = (
    "chronos_append_effect_event",
    "chronos_claim_effect_authority",
    "chronos_effect_event_hash",
    "chronos_framed_sha256",
    "chronos_get_effect_state",
    "chronos_issue_effect_authority",
    "chronos_reject_mutation",
    "chronos_claim_opportunity",
    "chronos_reserve_torrent_external_effect",
    "chronos_append_torrent_external_effect",
    "chronos_record_torrent_batch",
    "chronos_reject_torrent_mutation",
)
EXPECTED_TRIGGERS = (
    "trg_chronos_authorities_append_only",
    "trg_chronos_authorities_no_truncate",
    "trg_chronos_events_append_only",
    "trg_chronos_events_no_truncate",
    "trg_chronos_opportunity_claims_append_only",
    "trg_chronos_opportunity_claims_no_truncate",
    "trg_chronos_torrent_batches_append_only",
    "trg_chronos_torrent_batches_no_truncate",
    "trg_chronos_torrent_external_effect_permits_append_only",
    "trg_chronos_torrent_external_effect_permits_no_truncate",
    "trg_chronos_torrent_external_effect_events_append_only",
    "trg_chronos_torrent_external_effect_events_no_truncate",
)


def _connect_direct(database_url: str) -> Connection[Any]:
    """Seal every production connection against ambient libpq overrides."""

    return connect_direct_postgres(database_url, connector=psycopg.connect)


NO_VALUES_OBSERVED = False
MAX_NEON_RESPONSE_BYTES = 1_000_000
_NEON_SAFE_IDENTIFIER = re.compile(r"^[a-z0-9-]{1,60}$")
_RECOVERY_BRANCH_NAME = re.compile(
    rf"^{re.escape(RECOVERY_BRANCH_PREFIX)}[0-9]{{8}}T[0-9]{{6}}Z$"
)
_NEON_ALLOWED_ROUTES = (
    re.compile(r"^GET /projects\?limit=100$"),
    re.compile(r"^GET /projects/[^/?]+$"),
    re.compile(r"^GET /projects/[^/?]+/branches\?limit=100$"),
    re.compile(r"^GET /projects/[^/?]+/branches/[^/?]+$"),
    re.compile(r"^GET /projects/[^/?]+/branches/[^/?]+/endpoints$"),
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
        json.dumps(_json_value(document), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
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


class _DuplicateJsonKey(ValueError):
    """Raised when a Neon response contains an ambiguous JSON object."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateJsonKey(key)
        document[key] = value
    return document


def _finite_json(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _finite_json(nested)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    return value is None or isinstance(value, (bool, int, str))


def _bounded_neon_response_bytes(response: requests.Response) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        if (
            not content_length.isascii()
            or not content_length.isdigit()
            or int(content_length) > MAX_NEON_RESPONSE_BYTES
        ):
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID")
    payload = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not isinstance(chunk, bytes):
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID")
        if not chunk:
            continue
        if len(payload) + len(chunk) > MAX_NEON_RESPONSE_BYTES:
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID")
        payload.extend(chunk)
    if not payload:
        raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID")
    return bytes(payload)


class NeonClient:
    """Small Neon API client whose exceptions never include response bodies."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ChronosProductionError("CHRONOS_NEON_API_KEY_MISSING")
        self._api_key = api_key
        self._session = requests.Session()
        self._session.trust_env = False

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
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=30,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            raise ChronosProductionError("CHRONOS_NEON_API_UNAVAILABLE") from None
        try:
            if not 200 <= response.status_code < 300:
                raise ChronosProductionError(
                    f"CHRONOS_NEON_API_HTTP_{response.status_code}"
                )
            raw_document = _bounded_neon_response_bytes(response)
        except requests.RequestException:
            raise ChronosProductionError("CHRONOS_NEON_API_UNAVAILABLE") from None
        finally:
            try:
                response.close()
            except requests.RequestException:
                pass
        try:
            document = json.loads(
                raw_document.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
            )
        except (RecursionError, UnicodeDecodeError, ValueError):
            raise ChronosProductionError("CHRONOS_NEON_API_RESPONSE_INVALID") from None
        if not isinstance(document, dict) or not _finite_json(document):
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
        if not isinstance(branches, list) or any(not isinstance(item, dict) for item in branches):
            raise ChronosProductionError("CHRONOS_NEON_BRANCH_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in branches]

    def endpoints(self, project_id: str) -> list[dict[str, Any]]:
        document = self.request("GET", f"/projects/{project_id}/endpoints")
        endpoints = document.get("endpoints")
        if not isinstance(endpoints, list) or any(
            not isinstance(item, dict) for item in endpoints
        ):
            raise ChronosProductionError("CHRONOS_NEON_ENDPOINT_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in endpoints]

    def branch_endpoints(
        self,
        project_id: str,
        branch_id: str,
    ) -> list[dict[str, Any]]:
        document = self.request(
            "GET",
            f"/projects/{project_id}/branches/{branch_id}/endpoints",
        )
        endpoints = document.get("endpoints")
        if not isinstance(endpoints, list) or any(
            not isinstance(item, dict) for item in endpoints
        ):
            raise ChronosProductionError("CHRONOS_NEON_ENDPOINT_LIST_INVALID")
        return [cast(dict[str, Any], item) for item in endpoints]

    def create_recovery_branch(
        self,
        *,
        project_id: str,
        parent_branch_id: str,
        branch_name: str,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/projects/{project_id}/branches",
            payload={
                "endpoints": [],
                "branch": {
                    "name": branch_name,
                    "parent_id": parent_branch_id,
                }
            },
        )

    def branch(self, project_id: str, branch_id: str) -> dict[str, Any]:
        document = self.request("GET", f"/projects/{project_id}/branches/{branch_id}")
        branch = document.get("branch")
        if not isinstance(branch, dict):
            raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_RESPONSE_INVALID")
        return cast(dict[str, Any], branch)


def resolve_neon_identity(
    api_key: str,
    target: DirectPostgresTarget,
) -> tuple[NeonIdentity, NeonObservation]:
    try:
        observed = resolve_neon_identity_readonly(
            api_key,
            target,
            allow_idle=True,
        )
    except PreflightNoGo as error:
        raise ChronosProductionError(f"{error.reason}:{error.gate}") from None
    return (
        NeonIdentity(
            project_id=observed.project_id,
            project_name=observed.project_name,
            production_branch_id=observed.branch_id,
            production_branch_name=observed.branch_name,
            endpoint_id=observed.endpoint_id,
            endpoint_host=observed.endpoint_host,
            region=observed.region,
            database_name=target.database,
        ),
        observed,
    )


def _assert_recovery_branch_observation(
    branch: Mapping[str, Any],
    identity: NeonIdentity,
    *,
    recovery_branch_id: str,
    expected_name: str | None,
    allow_transition: bool = False,
) -> None:
    name = branch.get("name")
    state = branch.get("current_state")
    pending_state = branch.get("pending_state")
    name_matches = (
        name == expected_name
        if expected_name is not None
        else isinstance(name, str) and name.startswith(RECOVERY_BRANCH_PREFIX)
    )
    state_matches = state == "ready" or (
        allow_transition and state in {"creating", "init"}
    )
    pending_state_matches = pending_state is None or (
        allow_transition
        and state != "ready"
        and isinstance(pending_state, str)
        and bool(pending_state)
    )
    if not (
        _NEON_SAFE_IDENTIFIER.fullmatch(recovery_branch_id) is not None
        and branch.get("id") == recovery_branch_id
        and branch.get("project_id") == identity.project_id
        and branch.get("parent_id") == identity.production_branch_id
        and name_matches
        and branch.get("default") is False
        and state_matches
        and pending_state_matches
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_OBSERVATION_INVALID")


def create_recovery_point(
    client: NeonClient,
    identity: NeonIdentity,
    *,
    expected_branch_count: int,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    if expected_branch_count < 1:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_COUNT_PROOF_INVALID")
    branch_inventory = client.branches(identity.project_id)
    branch_ids = [str(branch.get("id", "")) for branch in branch_inventory]
    structurally_valid = all(
        isinstance(branch.get("id"), str)
        and _NEON_SAFE_IDENTIFIER.fullmatch(str(branch["id"])) is not None
        and branch.get("project_id") == identity.project_id
        and isinstance(branch.get("name"), str)
        and bool(branch["name"])
        and isinstance(branch.get("default"), bool)
        and isinstance(branch.get("current_state"), str)
        and bool(branch["current_state"])
        and branch.get("pending_state") is None
        for branch in branch_inventory
    )
    default_ids = [
        str(branch.get("id", ""))
        for branch in branch_inventory
        if branch.get("default") is True
    ]
    production_ready = sum(
        branch.get("id") == identity.production_branch_id
        and branch.get("current_state") == "ready"
        for branch in branch_inventory
    ) == 1
    if (
        not structurally_valid
        or len(branch_inventory) != expected_branch_count
        or len(set(branch_ids)) != len(branch_ids)
        or branch_ids.count(identity.production_branch_id) != 1
        or default_ids != [identity.production_branch_id]
        or not production_ready
    ):
        raise ChronosProductionError(
            "CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE"
        )
    recovery_branches = [
        branch
        for branch in branch_inventory
        if str(branch.get("name", "")).startswith(RECOVERY_BRANCH_PREFIX)
    ]
    if len(recovery_branches) >= MAX_RECOVERY_BRANCHES:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_LIMIT_REACHED")
    if len(branch_inventory) >= 100:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_INVENTORY_INCOMPLETE")

    compact = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    name = f"{RECOVERY_BRANCH_PREFIX}{compact}"
    receipt: dict[str, Any] = {
        "schema_version": "chronos-neon-recovery-point-v3",
        "verdict": "NEON_RECOVERY_POINT_CREATE_OUTCOME_INDETERMINATE",
        "project_id": None,
        "requested_project_id": identity.project_id,
        "production_branch_id": identity.production_branch_id,
        "recovery_branch_name": None,
        "requested_recovery_branch_name": name,
        "recovery_branch_id": None,
        "parent_branch_id": None,
        "created_at": None,
        "source_timestamp_or_lsn_if_available": None,
        "recovery_branch_limit": MAX_RECOVERY_BRANCHES,
        "recovery_branch_count_before": len(recovery_branches),
        "recovery_branch_count_after": None,
        "create_request_dispatched": True,
        "create_response_observed": False,
        "create_outcome": "INDETERMINATE",
        "requested_endpoint_count": 0,
        "endpoint_count_in_create_response": None,
        "endpoint_count_after_readiness": None,
        "endpoint_created": None,
        "endpoint_absence_verified": False,
        "response_contract_verified": False,
        "readiness_verified": False,
        "purchases": 0,
    }
    if receipt_path is not None:
        _write_json(receipt_path, receipt)
    creation = client.create_recovery_branch(
        project_id=identity.project_id,
        parent_branch_id=identity.production_branch_id,
        branch_name=name,
    )
    branch_value = creation.get("branch")
    endpoints_value = creation.get("endpoints")
    branch = branch_value if isinstance(branch_value, dict) else {}
    endpoint_count = len(endpoints_value) if isinstance(endpoints_value, list) else None
    receipt.update(
        {
            "project_id": branch.get("project_id"),
            "recovery_branch_name": branch.get("name"),
            "recovery_branch_id": branch.get("id"),
            "parent_branch_id": branch.get("parent_id"),
            "created_at": branch.get("created_at"),
            "source_timestamp_or_lsn_if_available": branch.get(
                "parent_lsn", branch.get("parent_timestamp")
            ),
            "create_response_observed": True,
            "endpoint_count_in_create_response": endpoint_count,
            "endpoint_created": (
                bool(endpoint_count) if endpoint_count is not None else None
            ),
        }
    )
    if receipt_path is not None:
        _write_json(receipt_path, receipt)
    if not isinstance(branch_value, dict):
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_RESPONSE_INVALID")
    if not isinstance(endpoints_value, list) or any(
        not isinstance(item, dict) for item in endpoints_value
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_ENDPOINT_RESPONSE_INVALID")
    if endpoints_value:
        receipt.update(
            {
                "verdict": "NEON_RECOVERY_POINT_UNEXPECTED_ENDPOINT_CREATED",
                "create_outcome": "CREATED_WITH_UNEXPECTED_ENDPOINT",
            }
        )
        if receipt_path is not None:
            _write_json(receipt_path, receipt)
        raise ChronosProductionError("CHRONOS_RECOVERY_ENDPOINT_CREATED_UNEXPECTEDLY")
    branch_id = str(branch.get("id", ""))
    if not branch_id:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_ID_MISSING")
    known_branch_ids = {str(item.get("id", "")) for item in branch_inventory if item.get("id")}
    if branch_id == identity.production_branch_id or branch_id in known_branch_ids:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_ID_INVALID")
    _assert_recovery_branch_observation(
        branch,
        identity,
        recovery_branch_id=branch_id,
        expected_name=name,
        allow_transition=True,
    )
    receipt.update(
        {
            "verdict": "NEON_RECOVERY_POINT_CREATED_PENDING_VERIFICATION",
            "recovery_branch_id": branch_id,
            "recovery_branch_count_after": len(recovery_branches) + 1,
            "create_outcome": "CREATED",
            "response_contract_verified": True,
        }
    )
    if receipt_path is not None:
        _write_json(receipt_path, receipt)
    observed: dict[str, Any] = {}
    for attempt in range(12):
        observed = client.branch(identity.project_id, branch_id)
        _assert_recovery_branch_observation(
            observed,
            identity,
            recovery_branch_id=branch_id,
            expected_name=name,
            allow_transition=True,
        )
        if observed.get("current_state") == "ready":
            break
        if attempt < 11:
            time.sleep(5)
    else:
        raise ChronosProductionError("NEON_RECOVERY_POINT_BLOCKED")
    _assert_recovery_branch_observation(
        observed,
        identity,
        recovery_branch_id=branch_id,
        expected_name=name,
    )
    branch_endpoints = client.branch_endpoints(identity.project_id, branch_id)
    receipt.update(
        {
            "endpoint_count_after_readiness": len(branch_endpoints),
            "endpoint_created": bool(branch_endpoints),
        }
    )
    if branch_endpoints:
        receipt["verdict"] = "NEON_RECOVERY_POINT_UNEXPECTED_ENDPOINT_OBSERVED"
        if receipt_path is not None:
            _write_json(receipt_path, receipt)
        raise ChronosProductionError("CHRONOS_RECOVERY_ENDPOINT_CREATED_UNEXPECTEDLY")
    receipt = {
        **receipt,
        "verdict": "NEON_RECOVERY_POINT_READY",
        "parent_branch_id": identity.production_branch_id,
        "created_at": observed.get("created_at"),
        "source_timestamp_or_lsn_if_available": observed.get(
            "parent_lsn", observed.get("parent_timestamp")
        ),
        "endpoint_absence_verified": True,
        "readiness_verified": True,
    }
    if receipt_path is not None:
        _write_json(receipt_path, receipt)
    return receipt


def inspect_database(database_url: str) -> dict[str, Any]:
    target = validate_direct_postgres_url(database_url)
    with _connect_direct(database_url) as connection:
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
        views = _rows(
            connection,
            "SELECT viewname FROM pg_catalog.pg_views "
            "WHERE schemaname='public' AND viewname LIKE 'chronos_%' "
            "ORDER BY viewname",
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
            "server_epoch": _scalar(connection, "SELECT pg_catalog.pg_postmaster_start_time()"),
            "database_size_bytes": int(
                cast(int, _scalar(connection, "SELECT pg_database_size(current_database())"))
            ),
            "roles": roles,
            "memberships": memberships,
            "tables": tables,
            "views": views,
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
        str(row["function_name"]) for row in cast(list[dict[str, Any]], report["functions"])
    }
    views = {str(row["viewname"]) for row in cast(list[dict[str, Any]], report["views"])}
    triggers = {str(row["trigger_name"]) for row in cast(list[dict[str, Any]], report["triggers"])}
    if tables != set(EXPECTED_TABLES):
        raise ChronosProductionError("CHRONOS_MIGRATION_TABLES_MISMATCH")
    if views != set(EXPECTED_VIEWS):
        raise ChronosProductionError("CHRONOS_MIGRATION_VIEWS_MISMATCH")
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


def _assert_post_merge_ci_binding(hold: Mapping[str, Any], *, main_sha: str) -> dict[str, Any]:
    expected_sha = require_sha(
        _required_public("CHRONOS_POST_MERGE_CI_SHA"),
        field="post_merge_ci_sha",
    )
    if expected_sha != main_sha:
        raise ChronosProductionError("CHRONOS_POST_MERGE_CI_SHA_MISMATCH")
    proof = hold.get("post_merge_ci")
    if (
        not isinstance(proof, dict)
        or proof.get("workflow_path") != ".github/workflows/ci.yml"
        or type(proof.get("run_id")) is not int
        or proof.get("run_attempt") != 1
        or proof.get("head_sha") != main_sha
        or proof.get("head_branch") != "main"
        or proof.get("event") != "push"
        or proof.get("status") != "completed"
        or proof.get("conclusion") != "success"
    ):
        raise ChronosProductionError("CHRONOS_POST_MERGE_CI_NOT_PROVEN")
    return cast(dict[str, Any], proof)


def run_preflight(report_dir: Path) -> dict[str, Any]:
    assert_production_safety_locks(os.environ)
    if _required_public("GITHUB_RUN_ATTEMPT") != "1":
        raise ChronosProductionError("CHRONOS_RERUN_FORBIDDEN")
    report_dir.mkdir(parents=True, exist_ok=True)
    api_key = _required("NEON_API_KEY")
    database_url = _required("NEON_BOOTSTRAP_DATABASE_URL")
    main_sha = require_sha(_required_public("GITHUB_SHA"), field="main_sha")
    workflow_sha = require_sha(_required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha")
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
    post_merge_ci = _assert_post_merge_ci_binding(hold, main_sha=main_sha)
    target = validate_direct_postgres_url(database_url)
    identity, neon_observation = resolve_neon_identity(api_key, target)
    try:
        require_neon_recovery_feasibility(neon_observation)
    except PreflightNoGo as error:
        raise ChronosProductionError(f"{error.reason}:{error.gate}") from None
    client = NeonClient(api_key)
    with _connect_direct(database_url) as capability_connection:
        assert_privileged_catalog_visibility(capability_connection)
    recovery_report = create_recovery_point(
        client,
        identity,
        expected_branch_count=neon_observation.target_project_branch_count,
        receipt_path=report_dir / "chronos-neon-recovery-point-v3.json",
    )
    database = inspect_database(database_url)
    with _connect_direct(database_url) as connection:
        preflight_role_inventory_hash = role_inventory_hash(connection)
        preflight_role_inventory = role_inventory_snapshot(connection)
    if database["current_revision"] not in {
        *EXPECTED_BEFORE_REVISIONS,
        EXPECTED_AFTER_REVISION,
    }:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    if database["current_revision"] == EXPECTED_AFTER_REVISION:
        _assert_post_migration(database)
        migrator_role = stable_migrator_role(identity.production_branch_id)
        with _connect_direct(database_url) as connection:
            lifecycle_admin = str(_scalar(connection, "SELECT current_user"))
            audit_terminal_lifecycle(
                connection,
                bootstrap_owner=BOOTSTRAP_AUTHORITY,
                lifecycle_admin=lifecycle_admin,
                migrator_role=migrator_role,
            )
    migration_file = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0015_data_torrent_opportunity.py"
    )
    if not migration_file.is_file():
        raise ChronosProductionError("CHRONOS_MIGRATION_TARGET_MISSING")
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
        "role_inventory": {name: list(values) for name, values in preflight_role_inventory.items()},
        "recovery": recovery_report,
        "workflow_hold": {
            "verdict": hold.get("verdict"),
            "active_after": hold.get("active_after"),
            "disabled_after": hold.get("disabled_after"),
            "queued_after": hold.get("queued_after"),
            "in_progress_after": hold.get("in_progress_after"),
        },
        "post_merge_ci": post_merge_ci,
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
        "role_inventory": {name: list(values) for name, values in preflight_role_inventory.items()},
        "recovery_branch_id": recovery_report["recovery_branch_id"],
        "recovery_branch_name": recovery_report["recovery_branch_name"],
        "golden_gate": "CHRONOS_MIGRATION_READY",
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "sslmode": target.sslmode,
        "channel_binding": target.channel_binding,
        "created_at": _timestamp(artifact_created_at),
        "expires_at": _timestamp(artifact_created_at + timedelta(hours=1)),
        "preflight_run_id": _required_public("GITHUB_RUN_ID"),
        "preflight_run_attempt": _required_public("GITHUB_RUN_ATTEMPT"),
        "post_merge_ci_sha": post_merge_ci["head_sha"],
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


def _runtime_accounts(*, expected_target: DirectPostgresTarget) -> list[tuple[str, str, str]]:
    accounts: list[tuple[str, str, str]] = []
    for login, group, secret_name in SCOPED_LOGINS:
        database_url = _required(secret_name)
        target = validate_direct_postgres_url(database_url)
        if target.username != login:
            raise ChronosProductionError("CHRONOS_SCOPED_USER_MISMATCH")
        if (
            target.host,
            target.port,
            target.database,
            target.sslmode,
            target.channel_binding,
        ) != (
            expected_target.host,
            expected_target.port,
            expected_target.database,
            expected_target.sslmode,
            expected_target.channel_binding,
        ):
            raise ChronosProductionError("CHRONOS_SCOPED_DATABASE_TARGET_MISMATCH")
        password = unquote(urlparse(database_url).password or "")
        if len(password) < 32:
            raise ChronosProductionError("CHRONOS_SCOPED_PASSWORD_INVALID")
        accounts.append((login, group, password))
    return accounts


def _assert_resume_role_inventory(
    connection: Connection[Any],
    *,
    preflight_inventory: object,
    migrator_role: str,
) -> None:
    """Fence unrelated catalog drift while allowing exact managed crash residue."""

    if not isinstance(preflight_inventory, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_ROLE_INVENTORY_MISSING")
    baseline: dict[str, tuple[Any, ...]] = {}
    for raw_name, raw_state in preflight_inventory.items():
        if not isinstance(raw_name, str) or not isinstance(raw_state, list):
            raise ChronosProductionError("CHRONOS_PREFLIGHT_ROLE_INVENTORY_INVALID")
        baseline[raw_name] = tuple(raw_state)
    current = role_inventory_snapshot(connection)
    managed = {
        BOOTSTRAP_AUTHORITY,
        migrator_role,
        *GROUP_ROLES,
        *(login for login, _group, _secret in SCOPED_LOGINS),
    }
    for role in set(baseline) | set(current):
        if role in managed or role.startswith(BOOTSTRAP_EXECUTOR_PREFIX):
            continue
        if baseline.get(role) != current.get(role):
            raise ChronosProductionError("CHRONOS_PREFLIGHT_ROLE_INVENTORY_MISMATCH")


def _assert_migrator_disabled(database_url: str, role: str, bootstrap_owner: str) -> None:
    with _connect_direct(database_url) as connection:
        assert_migrator_disabled(connection, role=role, bootstrap_owner=bootstrap_owner)


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
    assert_production_safety_locks(os.environ)
    api_key = _required("NEON_API_KEY")
    database_url = _required("NEON_BOOTSTRAP_DATABASE_URL")
    target = validate_direct_postgres_url(database_url)
    runtime_accounts = _runtime_accounts(expected_target=target)
    nonce = require_hash(
        _required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
        field="generation_nonce",
    )
    main_sha = require_sha(_required_public("GITHUB_SHA"), field="main_sha")
    workflow_sha = require_sha(_required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha")
    if _required_public("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    if _required_public("GITHUB_REF") != EXPECTED_REF:
        raise ChronosProductionError("CHRONOS_REF_MISMATCH")
    if _required_public("GITHUB_RUN_ATTEMPT") != "1":
        raise ChronosProductionError("CHRONOS_RERUN_FORBIDDEN")
    migration_run_id = _required_public("GITHUB_RUN_ID")
    if not migration_run_id.isascii() or not migration_run_id.isdigit() or migration_run_id == "0":
        raise ChronosProductionError("CHRONOS_MIGRATION_RUN_ID_INVALID")
    hold = _assert_hold()
    post_merge_ci = _assert_post_merge_ci_binding(hold, main_sha=main_sha)
    raw_artifact = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not isinstance(raw_artifact, dict):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_ARTIFACT_INVALID")
    artifact = verify_signed_document(cast(dict[str, Any], raw_artifact), api_key)
    expected_preflight_run_id = _required_public("CHRONOS_EXPECTED_PREFLIGHT_RUN_ID")
    if (
        artifact.get("preflight_run_id") != expected_preflight_run_id
        or artifact.get("preflight_run_attempt") != "1"
        or artifact.get("post_merge_ci_sha") != post_merge_ci["head_sha"]
    ):
        raise ChronosProductionError("CHRONOS_PREFLIGHT_CAUSAL_BINDING_MISMATCH")
    preflight_expiry = _preflight_expiry(artifact)
    identity, _neon_observation = resolve_neon_identity(api_key, target)
    recovery_branch_id = str(artifact.get("recovery_branch_id", ""))
    if _NEON_SAFE_IDENTIFIER.fullmatch(recovery_branch_id) is None:
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_ID_INVALID")
    recovery_branch_name = artifact.get("recovery_branch_name")
    if (
        not isinstance(recovery_branch_name, str)
        or _RECOVERY_BRANCH_NAME.fullmatch(recovery_branch_name) is None
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_BRANCH_NAME_INVALID")
    assert_exact_preflight_binding(
        artifact,
        main_sha=main_sha,
        workflow_sha=workflow_sha,
        project_id=identity.project_id,
        production_branch_id=identity.production_branch_id,
        recovery_branch_id=recovery_branch_id,
        current_revision=str(artifact.get("current_revision", "")),
    )
    client = NeonClient(api_key)
    recovery = client.branch(identity.project_id, recovery_branch_id)
    _assert_recovery_branch_observation(
        recovery,
        identity,
        recovery_branch_id=recovery_branch_id,
        expected_name=recovery_branch_name,
    )
    prelock_observation = inspect_database(database_url)
    migrator_role = stable_migrator_role(identity.production_branch_id)
    if prelock_observation["current_revision"] not in {
        *EXPECTED_BEFORE_REVISIONS,
        EXPECTED_AFTER_REVISION,
    }:
        raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
    migrator_password = secrets.token_urlsafe(48)
    executor_password = secrets.token_urlsafe(48)
    executor_role = BOOTSTRAP_EXECUTOR_PREFIX + uuid.uuid4().hex[:16]
    executor_valid_until = min(
        preflight_expiry,
        _utc_now() + timedelta(minutes=9),
    )
    admin = _connect_direct(database_url)
    lock_held = False
    lease = None
    authority_connection: Connection[Any] | None = None
    migrator_exists = False
    group_audit: dict[str, Any] | None = None
    migrator_audit: dict[str, Any] | None = None
    final_audit: dict[str, Any] | None = None
    dispatches = 0
    return_code: int | None = 0
    outcome = "MIGRATION_RESUMED"
    before = prelock_observation
    after = before
    migrator_disabled = False
    try:
        assert_privileged_catalog_visibility(admin)
        acquire_lifecycle_lock(admin)
        lock_held = True
        before = inspect_database(database_url)
        migrate_role_inventory_hash = role_inventory_hash(admin)
        if artifact.get("role_inventory_hash") != migrate_role_inventory_hash:
            _assert_resume_role_inventory(
                admin,
                preflight_inventory=artifact.get("role_inventory"),
                migrator_role=migrator_role,
            )
        if before["current_revision"] not in {
            *EXPECTED_BEFORE_REVISIONS,
            EXPECTED_AFTER_REVISION,
        }:
            raise ChronosProductionError("UNEXPECTED_DATABASE_REVISION")
        revision_advanced_during_attempt = (
            artifact.get("current_revision") in EXPECTED_BEFORE_REVISIONS
            and before["current_revision"] == EXPECTED_AFTER_REVISION
        )
        if (
            artifact.get("current_revision") != before["current_revision"]
            and not revision_advanced_during_attempt
        ):
            raise ChronosProductionError("CHRONOS_PREFLIGHT_REVISION_MISMATCH")
        lease = provision_bootstrap_executor(
            admin,
            executor_role=executor_role,
            password=executor_password,
            valid_until=executor_valid_until,
            lifecycle_lock_held=True,
        )
        executor_url = build_scoped_database_url(
            target,
            username=lease.executor_role,
            password=executor_password,
        )
        authority_connection = _connect_direct(executor_url)
        assert_executor_cannot_create_role(
            authority_connection,
            probe_role="chronos_executor_pre_set_probe",
        )
        set_permanent_bootstrap_authority(authority_connection)
        bootstrap_owner = lease.authority
        with authority_connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=%s)",
                (migrator_role,),
            )
            role_exists = cursor.fetchone()
        migrator_exists = bool(role_exists and role_exists[0])
        if before["current_revision"] in EXPECTED_BEFORE_REVISIONS:
            provisioned_groups = provision_chronos_group_roles(
                authority_connection, migrator_role=migrator_role
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
            if migrator_exists:
                disable_migrator(authority_connection, role=migrator_role)
                migrator_disabled = True
            provisioned_migrator = provision_migrator(
                authority_connection,
                role=migrator_role,
                password=migrator_password,
                valid_until=migrator_valid_until,
                pinned_system_grantor=provisioned_groups.bootstrap_system_grantor,
                audit_phase=migration_audit_phase,
                runtime_roles=sorted(runtime_at_start),
            )
            migrator_audit = provisioned_migrator.report()
            migrator_exists = True
            migrator_disabled = False
            migrator_url = build_scoped_database_url(
                target,
                username=migrator_role,
                password=migrator_password,
            )
            with authority_connection.cursor() as cursor:
                cursor.execute("SELECT version_num FROM public.alembic_version")
                dispatch_revision_row = cursor.fetchone()
            if (
                dispatch_revision_row is None
                or str(dispatch_revision_row[0]) != before["current_revision"]
            ):
                raise ChronosProductionError("CHRONOS_LOCKED_REVISION_CHANGED")
            dispatches = 1
            try:
                run_fenced_alembic(migrator_url, MIGRATION_TARGET)
                return_code = 0
            finally:
                disable_migrator(authority_connection, role=migrator_role)
                migrator_disabled = True
            after = inspect_database(database_url)
            outcome = "MIGRATION_OUTCOME_AMBIGUOUS"
            try:
                _assert_post_migration(after)
            except ChronosProductionError:
                if after.get("current_revision") == before["current_revision"]:
                    outcome = "MIGRATION_NOT_APPLIED"
            else:
                outcome = "MIGRATION_CONFIRMED"
            if outcome != "MIGRATION_CONFIRMED":
                raise ChronosProductionError(outcome)
            assert_post_migration_role_state(
                authority_connection,
                migrator_role=migrator_role,
                bootstrap_owner=bootstrap_owner,
            )
        else:
            _assert_post_migration(before)
            existing_runtime = {
                str(row["rolname"])
                for row in cast(list[dict[str, Any]], before["roles"])
                if str(row["rolname"]) in {login for login, _, _ in SCOPED_LOGINS}
            }
            resume_phase = (
                "final"
                if len(existing_runtime) == len(SCOPED_LOGINS)
                else "runtime_partial"
                if existing_runtime
                else "migrator"
            )
            assert_permanent_bootstrap_authority(authority_connection)
            disable_migrator(authority_connection, role=migrator_role)
            migrator_disabled = True
            assert_post_migration_role_state(
                authority_connection,
                migrator_role=migrator_role,
                bootstrap_owner=bootstrap_owner,
            )
            resumed = audit_role_edges(
                authority_connection,
                phase=resume_phase,
                bootstrap_owner=bootstrap_owner,
                migrator_role=migrator_role,
                runtime_roles=sorted(existing_runtime),
            )
            migrator_audit = resumed.report()

        assert_migrator_disabled(
            authority_connection,
            role=migrator_role,
            bootstrap_owner=bootstrap_owner,
        )
        pinned_grantor = str((migrator_audit or {}).get("bootstrap_system_grantor", ""))
        if not pinned_grantor:
            raise ChronosProductionError("CHRONOS_BOOTSTRAP_GRANTOR_MISSING")
        provisioned_runtime = provision_runtime_logins(
            authority_connection,
            accounts=runtime_accounts,
            migrator_role=migrator_role,
            pinned_system_grantor=pinned_grantor,
        )
        final_audit = provisioned_runtime.report()
        final = inspect_database(database_url)
        _assert_post_migration(final)
        assert_migrator_disabled(
            authority_connection,
            role=migrator_role,
            bootstrap_owner=bootstrap_owner,
        )
        reset_permanent_bootstrap_authority(authority_connection)
        authority_connection.close()
        authority_connection = None
        cleanup_bootstrap_executor(
            admin,
            executor_role=lease.executor_role,
            authority=lease.authority,
            lifecycle_admin=lease.lifecycle_admin,
            lifecycle_admin_superuser=lease.lifecycle_admin_superuser,
        )
        terminal_audit = audit_terminal_lifecycle(
            admin,
            bootstrap_owner=bootstrap_owner,
            lifecycle_admin=lease.lifecycle_admin,
            migrator_role=migrator_role,
        ).report()
        release_lifecycle_lock(admin)
        lock_held = False
        admin.close()
        lease = None
        _write_json(
            report_dir / "chronos-role-edge-matrix-v1.json",
            {
                "schema_version": "chronos-role-edge-matrix-v1",
                "verdict": "BIDIRECTIONAL_ROLE_EDGE_AUDIT_READY",
                "migration_cycle": "NOT_RUN_IN_PRODUCTION_ACTIVATION",
                "password_state": {
                    "bootstrap_authority": "NEVER_LOGIN_PASSWORD_NULL",
                    "bootstrap_executor": "DELETED_BY_EXTERNAL_ADMIN",
                    "migrator": "CLEARED_BY_COMMITTED_ALTER_ROLE",
                    "catalog_visibility": "PG_AUTHID_ROLPASSWORD_SELECT_PROVEN",
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
                "forbidden_edge_count": terminal_audit["forbidden_edge_count"],
                "runtime_effective_bootstrap_edge_count": terminal_audit[
                    "runtime_effective_bootstrap_edge_count"
                ],
                "migrator_runtime_edge_count": terminal_audit["migrator_runtime_edge_count"],
            },
        )
    except Exception:
        cleanup_steps: list[Callable[[], None]] = []
        if authority_connection is not None and migrator_exists and not migrator_disabled:

            def cleanup_migrator() -> None:
                if authority_connection is not None:
                    disable_migrator(authority_connection, role=migrator_role)

            cleanup_steps.append(cleanup_migrator)
        if authority_connection is not None:
            cleanup_steps.append(authority_connection.close)
        if lease is not None:

            def cleanup_executor() -> None:
                cleanup_bootstrap_executor(
                    admin,
                    executor_role=lease.executor_role,
                    authority=lease.authority,
                    lifecycle_admin=lease.lifecycle_admin,
                    lifecycle_admin_superuser=lease.lifecycle_admin_superuser,
                )

            cleanup_steps.append(cleanup_executor)
        if lock_held:
            cleanup_steps.append(lambda: release_lifecycle_lock(admin))
        cleanup_steps.append(admin.close)
        _attempt_cleanup_steps(cleanup_steps)
        raise
    output: dict[str, Any] = {
        "schema_version": "chronos-bootstrap-output-v3",
        "database_host": target.host,
        "database_port": target.port,
        "database_name": target.database,
        "sslmode": target.sslmode,
        "channel_binding": target.channel_binding,
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
        "post_merge_ci_sha": post_merge_ci["head_sha"],
        "preflight_run_id": expected_preflight_run_id,
        "migration_run_id": migration_run_id,
        "migration_run_attempt": "1",
    }
    signed_output = sign_document(output, nonce)
    _write_json(report_dir / "chronos-bootstrap-output-v3.json", signed_output)
    report = {
        "schema_version": "chronos-neon-migration-v3",
        "verdict": "NEON_CHRONOS_0015_MIGRATED",
        "scoped_identities": "CHRONOS_SCOPED_IDENTITIES_READY",
        "migration_outcome": outcome,
        "migration_dispatches": dispatches,
        "migration_runner": "IN_PROCESS_FENCED_ALEMBIC",
        "in_process_return_code": return_code,
        "revision_before": before.get("current_revision"),
        "revision_after": after.get("current_revision"),
        "server_epoch": final.get("server_epoch"),
        "tables": final.get("tables"),
        "views": final.get("views"),
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


def run_verify(report_dir: Path, migration_path: Path) -> dict[str, Any]:
    assert_production_safety_locks(os.environ)
    nonce = require_hash(
        _required("CHRONOS_CONTROL_PLANE_GENERATION_NONCE"),
        field="generation_nonce",
    )
    main_sha = require_sha(_required_public("GITHUB_SHA"), field="main_sha")
    workflow_sha = require_sha(_required_public("GITHUB_WORKFLOW_SHA"), field="workflow_sha")
    if _required_public("GITHUB_REPOSITORY") != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    if _required_public("GITHUB_REF") != EXPECTED_REF:
        raise ChronosProductionError("CHRONOS_REF_MISMATCH")
    if _required_public("GITHUB_RUN_ATTEMPT") != "1":
        raise ChronosProductionError("CHRONOS_RERUN_FORBIDDEN")
    verify_run_id = _required_public("GITHUB_RUN_ID")
    expected_migration_run_id = _required_public("CHRONOS_EXPECTED_MIGRATION_RUN_ID")
    for run_id in (verify_run_id, expected_migration_run_id):
        if not run_id.isascii() or not run_id.isdigit() or run_id == "0":
            raise ChronosProductionError("CHRONOS_VERIFY_RUN_ID_INVALID")
    hold = _assert_hold()
    post_merge_ci = _assert_post_merge_ci_binding(hold, main_sha=main_sha)
    try:
        raw_migration = json.loads(migration_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ChronosProductionError("CHRONOS_MIGRATION_ARTIFACT_INVALID") from None
    if not isinstance(raw_migration, dict):
        raise ChronosProductionError("CHRONOS_MIGRATION_ARTIFACT_INVALID")
    migration = verify_signed_document(cast(dict[str, Any], raw_migration), nonce)
    if (
        migration.get("schema_version") != "chronos-bootstrap-output-v3"
        or migration.get("main_sha") != main_sha
        or migration.get("workflow_sha") != workflow_sha
        or migration.get("post_merge_ci_sha") != post_merge_ci["head_sha"]
        or migration.get("migration_run_id") != expected_migration_run_id
        or migration.get("migration_run_attempt") != "1"
        or migration.get("revision") != EXPECTED_AFTER_REVISION
        or migration.get("generation_hash") != generation_hash(nonce)
        or not isinstance(migration.get("preflight_run_id"), str)
    ):
        raise ChronosProductionError("CHRONOS_MIGRATION_CAUSAL_BINDING_MISMATCH")
    urls = {
        "authority": _required("CHRONOS_AUTHORITY_DATABASE_URL"),
        "runtime": _required("CHRONOS_RUNTIME_DATABASE_URL"),
        "reader": _required("CHRONOS_READER_DATABASE_URL"),
    }
    reports: dict[str, Any] = {}
    for role, database_url in urls.items():
        target = validate_direct_postgres_url(database_url)
        if (
            target.host != migration.get("database_host")
            or target.port != migration.get("database_port")
            or target.database != migration.get("database_name")
            or target.sslmode != migration.get("sslmode")
            or target.channel_binding != migration.get("channel_binding")
        ):
            raise ChronosProductionError("CHRONOS_VERIFY_DATABASE_TARGET_MISMATCH")
        with _connect_direct(database_url) as connection:
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
            epoch = _scalar(connection, "SELECT pg_catalog.pg_postmaster_start_time()")
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
            "channel_binding": target.channel_binding,
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
        expected_group = next(group for login, group, _ in SCOPED_LOGINS if login == username)
        if memberships != [{"granted_role": expected_group}]:
            raise ChronosProductionError("CHRONOS_VERIFY_MEMBERSHIP_MISMATCH")
    if len({str(report["server_epoch"]) for report in reports.values()}) != 1:
        raise ChronosProductionError("CHRONOS_VERIFY_SERVER_EPOCH_MISMATCH")
    with _connect_direct(urls["reader"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname,rolcanlogin,rolcreaterole FROM pg_catalog.pg_roles "
                "WHERE rolname=%s OR "
                "pg_catalog.shobj_description(oid,'pg_authid')=%s "
                "ORDER BY rolname",
                (BOOTSTRAP_AUTHORITY, MIGRATOR_MARKER),
            )
            lifecycle_roles = cursor.fetchall()
            cursor.execute(
                "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname LIKE %s",
                (BOOTSTRAP_EXECUTOR_PREFIX + "%",),
            )
            executor_row = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM pg_catalog.pg_auth_members m "
                "JOIN pg_catalog.pg_roles granted ON granted.oid=m.roleid "
                "JOIN pg_catalog.pg_roles member ON member.oid=m.member "
                "WHERE (granted.rolname LIKE %s OR member.rolname LIKE %s)",
                (BOOTSTRAP_EXECUTOR_PREFIX + "%", BOOTSTRAP_EXECUTOR_PREFIX + "%"),
            )
            membership_row = cursor.fetchone()
            cursor.execute(
                "SELECT count(*) FROM pg_catalog.pg_roles r "
                "WHERE r.rolname=ANY(%s) AND "
                "(pg_catalog.pg_has_role(r.rolname,%s,'USAGE') OR "
                "pg_catalog.pg_has_role(r.rolname,%s,'SET'))",
                (
                    [login for login, _group, _secret in SCOPED_LOGINS],
                    BOOTSTRAP_AUTHORITY,
                    BOOTSTRAP_AUTHORITY,
                ),
            )
            runtime_path_row = cursor.fetchone()
        if executor_row is None or membership_row is None or runtime_path_row is None:
            raise ChronosProductionError("CHRONOS_VERIFY_ROLE_LIFECYCLE_MISSING")
        executor_count = int(executor_row[0])
        executor_memberships = int(membership_row[0])
        runtime_authority_paths = int(runtime_path_row[0])
        authority_rows = [row for row in lifecycle_roles if str(row[0]) == BOOTSTRAP_AUTHORITY]
        migrator_rows = [row for row in lifecycle_roles if str(row[0]) != BOOTSTRAP_AUTHORITY]
        if (
            len(authority_rows) != 1
            or bool(authority_rows[0][1])
            or not bool(authority_rows[0][2])
            or len(migrator_rows) != 1
            or bool(migrator_rows[0][1])
            or bool(migrator_rows[0][2])
            or executor_count
            or executor_memberships
            or runtime_authority_paths
        ):
            raise ChronosProductionError("CHRONOS_VERIFY_ROLE_LIFECYCLE_UNSAFE")
    _write_json(
        report_dir / "chronos-role-edge-matrix-v1.json",
        {
            "schema_version": "chronos-role-edge-matrix-v1",
            "verdict": "SCOPED_RUNTIME_TERMINAL_AUDIT_READY",
            "bootstrap_authority": BOOTSTRAP_AUTHORITY,
            "migrator_role": str(migrator_rows[0][0]),
            "executor_role_count": executor_count,
            "executor_membership_count": executor_memberships,
            "runtime_to_authority_path_count": runtime_authority_paths,
        },
    )
    result = {
        "schema_version": "chronos-production-verify-v3",
        "verdict": "CHRONOS_SCOPED_IDENTITIES_READY",
        "revision": EXPECTED_AFTER_REVISION,
        "identities": reports,
        "business_data_modified": False,
        "forbidden_membership": 0,
        "migrator_runtime_membership": 0,
        "runtime_effective_bootstrap_edge": runtime_authority_paths,
        "provider_calls": 0,
        "r2_operations": 0,
        "main_sha": main_sha,
        "workflow_sha": workflow_sha,
        "post_merge_ci_sha": post_merge_ci["head_sha"],
        "generation_hash": generation_hash(nonce),
        "preflight_run_id": migration["preflight_run_id"],
        "migration_run_id": expected_migration_run_id,
        "migration_run_attempt": "1",
        "verify_run_id": verify_run_id,
        "verify_run_attempt": "1",
        "migration_output_signature_algorithm": "HMAC-SHA256",
    }
    normalized_result = cast(dict[str, Any], _json_value(result))
    signed_result = sign_document(normalized_result, nonce)
    _write_json(report_dir / "chronos-production-verify-v3.json", signed_result)
    return signed_result


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
    parser.add_argument("--migration-artifact", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "PREFLIGHT":
            result = run_preflight(args.report_dir)
        elif args.mode == "MIGRATE":
            if args.preflight_artifact is None:
                raise ChronosProductionError("CHRONOS_PREFLIGHT_ARTIFACT_REQUIRED")
            result = run_migrate(args.report_dir, args.preflight_artifact)
        else:
            if args.migration_artifact is None:
                raise ChronosProductionError("CHRONOS_MIGRATION_ARTIFACT_REQUIRED")
            result = run_verify(args.report_dir, args.migration_artifact)
    except Exception as error:
        failure = _safe_failure(args.mode, error)
        _write_json(args.report_dir / "chronos-bootstrap-failure-v3.json", failure)
        print(f"CHRONOS_BOOTSTRAP_{args.mode}_FAILED:{failure['error_code']}")
        raise SystemExit(1) from None
    print(f"CHRONOS_BOOTSTRAP_{args.mode}_PASS:{result['verdict']}")


if __name__ == "__main__":
    main()
