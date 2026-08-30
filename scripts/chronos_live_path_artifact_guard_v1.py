"""Recover one sanitized Chronos live-path artifact after any workflow failure."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import parse_qsl, unquote, urlparse

REPORT_SCHEMA = "chronos-neon-controlled-idle-wake-readonly-v1"
PURE_REPORT_SCHEMA = "chronos-neon-pure-readonly-preflight-v4"
GO_VERDICT = "CHRONOS_NEON_MIGRATION_READY_FOR_SEPARATE_AUTHORIZATION"
NO_GO_VERDICT = "CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED"
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\dZ$"
)
_POSTGRESQL_VERSION = re.compile(r"^16\d{4}$")
_SAFE_NEON_HOST = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.neon\.tech$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")
_LIBPQ_ENVIRONMENT = re.compile(r"^PG[A-Z0-9_]+$")
_SAFE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_SAFE_QUERY_KEYS = frozenset({"sslmode", "channel_binding"})
_MAX_REPORT_BYTES = 1_048_576
_MINIMUM_CONTROLLED_SUSPEND_TIMEOUT_SECONDS = 300
_ZERO_EFFECTS = (
    "neon_mutations",
    "production_sql_writes",
    "recovery_branch_creations",
    "role_creations",
    "migration_0014",
    "r2_operations",
    "provider_calls",
    "purchases",
    "sensitive_values_exposed",
    "sql_write_count",
    "postgresql_retries",
)


class _DuplicateJsonKey(ValueError):
    """Raised when an artifact contains an ambiguous JSON object."""


@dataclass(frozen=True, slots=True)
class _DirectPostgresTarget:
    host: str
    port: int
    database: str
    username: str
    sslmode: str
    channel_binding: str


def _libpq_environment_variable_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                name.upper()
                for name in os.environ
                if _LIBPQ_ENVIRONMENT.fullmatch(name.upper()) is not None
            }
        )
    )


def _validated_direct_postgres_url(value: str) -> _DirectPostgresTarget | None:
    """Mirror the canonical DSN contract using only the Python stdlib."""

    if not isinstance(value, str) or not value.startswith("postgresql://"):
        return None
    if _INVALID_PERCENT_ESCAPE.search(value) is not None:
        return None
    try:
        parsed = urlparse(value)
        parsed_port = parsed.port
        port = 5432 if parsed_port is None else parsed_port
        username = unquote(parsed.username or "", errors="strict")
        password = unquote(parsed.password or "", errors="strict")
        database = unquote(parsed.path.removeprefix("/"), errors="strict")
        query_items = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
        )
        raw_query_keys: list[str] = []
        for field in parsed.query.split("&"):
            if field.count("=") != 1:
                return None
            raw_query_keys.append(field.partition("=")[0])
    except (TypeError, UnicodeError, ValueError):
        return None
    if parsed.scheme != "postgresql" or parsed.params or parsed.fragment:
        return None
    if ";" in parsed.path or parsed.netloc.count("@") != 1:
        return None
    raw_userinfo, _, _ = parsed.netloc.partition("@")
    if raw_userinfo.count(":") != 1:
        return None
    raw_host = parsed.hostname or ""
    host = raw_host.lower()
    if (
        not host
        or host == "localhost"
        or host.endswith(".localhost")
        or "%" in raw_host
        or _SAFE_NEON_HOST.fullmatch(host) is None
        or host.split(".", 1)[0].endswith("-pooler")
        or port != 5432
        or not username
        or len(password) < 8
        or not database
        or "/" in database
        or any(key not in _SAFE_QUERY_KEYS for key in raw_query_keys)
    ):
        return None
    query: dict[str, str] = {}
    for key, item in query_items:
        if key not in _SAFE_QUERY_KEYS or not item or key in query:
            return None
        query[key] = item
    if set(query) != _SAFE_QUERY_KEYS:
        return None
    sslmode = query["sslmode"]
    channel_binding = query["channel_binding"]
    if sslmode not in _SAFE_SSL_MODES or channel_binding != "require":
        return None
    return _DirectPostgresTarget(
        host=host,
        port=port,
        database=database,
        username=username,
        sslmode=sslmode,
        channel_binding=channel_binding,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateJsonKey(key)
        document[key] = value
    return document


_EFFECT_MAXIMUMS = {
    "neon_get_count": 25,
    "postgresql_connection_attempts": 1,
    "postgresql_connection_successes": 1,
    "compute_wake_events": 1,
    "sql_statement_count": 25,
    "sql_statement_completed_count": 25,
    "sql_read_attempt_count": 25,
    "sql_read_count": 25,
    "begin_read_only_attempted": 1,
    "begin_read_only_completed": 1,
    "rollback_attempted": 1,
    "rollback_completed": 1,
}
_EFFECT_KEYS = frozenset((*_ZERO_EFFECTS, *_EFFECT_MAXIMUMS))
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "observed_at",
        "source",
        "verdict",
        "reason",
        "failed_gate",
        "dsn_contract_verdict",
        "dsn_security_profile",
        "checks",
        "neon",
        "postgresql",
        "github_actions",
        "effects",
        "architecture_verdict",
        "wake_model",
        "control_plane_start_api_used",
        "database_verdict",
        "global_verdict",
        "lifecycle",
        "connection_attempt_count",
        "compute_wake_events",
        "compute_wake_certainty",
        "effect_counter_certainty",
        "bootstrap_authority_verdict",
        "recovery_verdict",
        "purchase_required",
    }
)
_COMMON_GO_KEYS = frozenset(
    {
        "schema_version",
        "observed_at",
        "source",
        "verdict",
        "reason",
        "failed_gate",
        "effect_counter_certainty",
        "dsn_contract_verdict",
        "dsn_security_profile",
        "checks",
        "neon",
        "postgresql",
        "github_actions",
        "effects",
    }
)
_CONTROLLED_GO_KEYS = _COMMON_GO_KEYS | frozenset(
    {
        "architecture_verdict",
        "wake_model",
        "control_plane_start_api_used",
        "database_verdict",
        "global_verdict",
        "lifecycle",
        "connection_attempt_count",
        "compute_wake_events",
        "compute_wake_certainty",
        "bootstrap_authority_verdict",
        "recovery_verdict",
        "purchase_required",
    }
)
_NO_GO_BASE_KEYS = frozenset(
    {
        "schema_version",
        "observed_at",
        "source",
        "verdict",
        "reason",
        "failed_gate",
        "effect_counter_certainty",
        "effects",
    }
)
_CONTROLLED_NO_GO_KEYS = _NO_GO_BASE_KEYS | frozenset(
    {
        "architecture_verdict",
        "wake_model",
        "control_plane_start_api_used",
        "database_verdict",
        "global_verdict",
        "lifecycle",
        "connection_attempt_count",
        "compute_wake_events",
        "compute_wake_certainty",
        "recovery_verdict",
        "purchase_required",
        "github_actions",
    }
)
_CONTROLLED_FALLBACK_KEYS = _NO_GO_BASE_KEYS | frozenset(
    {
        "global_verdict",
        "connection_attempt_count",
        "compute_wake_events",
        "compute_wake_certainty",
    }
)
_SOURCE_KEYS = frozenset({"repository", "ref", "main_sha", "run_id", "run_attempt"})
_CHECK_KEYS = frozenset(
    {
        "secrets_present",
        "project_identity_verified",
        "production_branch_verified",
        "direct_endpoint_verified",
        "ssl_verified",
        "expected_revision_verified",
        "bootstrap_authority_plausible",
        "recovery_branch_feasible",
        "purchase_required",
        "github_queue_empty",
        "github_in_progress_empty",
        "github_dispatch_unique",
    }
)
_RAW_IDENTITY_KEYS = frozenset(
    {
        "api_key",
        "password",
        "dsn",
        "url",
        "uri",
        "host",
        "hostname",
        "cursor",
        "next",
        "previous",
        "project_id",
        "branch_id",
        "endpoint_id",
        "database_name",
        "session_user",
        "current_user",
        "username",
        "userinfo",
    }
)
_NEON_HOST = re.compile(r"(?i)(?:[a-z0-9-]+\.)+neon\.tech")
_HEX_SHA = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TECHNICAL_FAILURE_GATES = frozenset(
    {
        "artifact_guard_recovered_missing_or_invalid_report",
        "report_serialization_or_write_failure",
        "unexpected_sanitized_failure",
    }
)
_NO_GO_REASON_VALUES = frozenset(
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
        "USER_KEY_ORGANIZATION_CAPACITY_UNPROVEN",
        "PURCHASE_REQUIRED",
        "SECRET_MISSING",
    }
)
_NO_GO_GATE_VALUES = frozenset(
    {
        "account_branch_limit_contradiction",
        "alembic_revision_unavailable",
        "alembic_target_changed_before_lock",
        "alembic_target_not_plain_permanent_table",
        "artifact_guard_recovered_missing_or_invalid_report",
        "autoscaling_limit_contract_invalid",
        "billing_plan_contract_invalid",
        "billing_plan_subscription_contradiction",
        "bootstrap_authority_capabilities_insufficient",
        "bootstrap_authority_inspection_failed",
        "bootstrap_authority_insufficient",
        "branch_capacity_ambiguous",
        "branch_capacity_exhausted",
        "branch_count_contract_invalid",
        "branch_count_inventory_contradiction",
        "branch_default_contract_invalid",
        "branch_endpoint_confirmation_mismatch",
        "branch_inventory_truncated",
        "branch_limit_contract_invalid",
        "branch_limit_contract_missing",
        "branch_parent_contract_invalid",
        "branch_project_mismatch",
        "branch_relationship_missing",
        "chronos_postgresql_version_not_certified",
        "compute_return_to_idle_not_proven",
        "configured_project_endpoint_missing",
        "configured_project_endpoint_not_unique",
        "configured_project_invalid",
        "configured_project_not_accessible",
        "configured_project_owner_scope_mismatch",
        "configured_organization_scope_mismatch",
        "current_dispatch_not_observed",
        "database_url_parameters_forbidden",
        "default_branch_not_unique",
        "default_transaction_read_only_not_enforced",
        "direct_database_url_invalid",
        "direct_endpoint_not_proven",
        "dsn_branch_is_not_default",
        "dsn_endpoint_match_missing",
        "endpoint_detail_branch_mismatch",
        "endpoint_detail_disabled",
        "endpoint_detail_host_mismatch",
        "endpoint_detail_id_mismatch",
        "endpoint_detail_invalid",
        "endpoint_detail_missing",
        "endpoint_detail_not_active",
        "endpoint_detail_pooled",
        "endpoint_detail_project_mismatch",
        "endpoint_detail_state_invalid",
        "endpoint_detail_transitioning",
        "endpoint_detail_type_mismatch",
        "endpoint_inventory_pagination_ambiguous",
        "endpoint_not_direct",
        "endpoint_state_contract_invalid",
        "endpoint_state_unsupported",
        "exact_main_dispatch_not_unique",
        "authority_window_dispatch_not_unique",
        "existing_chronos_memberships_unsafe",
        "existing_chronos_objects_unsafe",
        "existing_chronos_roles_unsafe",
        "first_sql_not_begin_read_only",
        "github_actions_in_progress_not_empty",
        "github_actions_not_quiescent",
        "github_actions_queue_not_empty",
        "github_actions_runs_invalid",
        "github_actions_state_invalid",
        "github_actions_state_unavailable",
        "github_dispatch_history_invalid",
        "github_authority_dispatch_history_invalid",
        "github_authority_window_invalid",
        "github_main_sha_invalid",
        "github_main_ref_invalid",
        "github_main_ref_mismatch",
        "github_source_not_exact_main",
        "current_authority_dispatch_not_observed",
        "history_retention_contract_invalid",
        "identity_incomplete_before_connection",
        "libpq_environment_forbidden",
        "lifecycle_admin_role_forbidden",
        "lock_timeout_not_enforced",
        "mission_authority_inactive",
        "neon_api_credential_scope_unsupported",
        "neon_api_invalid_document",
        "neon_api_invalid_json",
        "neon_api_non_finite_or_non_json_value",
        "neon_api_unavailable",
        "neon_auth_scope_invalid",
        "neon_get_budget_exhausted",
        "neon_owner_scope_identity_mismatch",
        "neon_project_id_must_remain_absent",
        "neon_route_forbidden",
        "personal_api_key_owner_capacity_unproven",
        "positive_endpoint_candidate_invalid",
        "positive_endpoint_match_not_unique",
        "positive_endpoint_owner_scope_mismatch",
        "postgresql_connection_close_failed",
        "postgresql_identity_contract_invalid",
        "postgresql_major_version_mismatch",
        "postgresql_readonly_inspection_failed",
        "postgresql_row_missing",
        "postgresql_target_identity_mismatch",
        "postgresql_version_contract_invalid",
        "privileged_catalog_not_visible",
        "production_branch_not_proven",
        "production_branch_not_ready",
        "production_branch_parent_invalid",
        "production_branch_parent_unexpected",
        "production_branch_state_missing",
        "production_branch_transitioning",
        "production_postgresql_connection_attempt_not_unique",
        "project_cursor_cycle",
        "project_detail_id_or_owner_mismatch",
        "project_details_missing",
        "project_endpoint_region_mismatch",
        "project_identity_discovery_budget_exceeded",
        "project_identity_not_proven",
        "project_inventory_duplicate_id",
        "project_inventory_incomplete",
        "project_pagination_invalid",
        "project_permission_insufficient_for_recovery",
        "project_postgresql_version_contract_invalid",
        "project_postgresql_version_unsupported",
        "project_scoped_api_key_owner_capacity_unproven",
        "purchase_required",
        "purchase_requirement_ambiguous",
        "recovery_branch_not_feasible",
        "report_serialization_or_write_failure",
        "search_path_not_enforced",
        "single_connection_attempt_did_not_complete",
        "sensitive_value_too_short",
        "sql_budget_exhausted",
        "ssl_not_proven",
        "startup_options_required",
        "statement_timeout_not_enforced",
        "subscription_type_contract_missing",
        "suspend_timeout_contract_invalid",
        "target_project_branch_count_not_proven",
        "timeout_setting_invalid",
        "transaction_read_only_not_enforced",
        "unexpected_database_revision",
        "unexpected_sanitized_failure",
        "unsafe_identifier",
        "user_organization_scope_ambiguous",
        "workflow_rerun_forbidden",
    }
)
_MISSING_GATE = re.compile(
    r"^missing:(?:GITHUB_REPOSITORY|GITHUB_REF|GITHUB_SHA|"
    r"GITHUB_RUN_ATTEMPT|GITHUB_RUN_ID|GITHUB_TOKEN|NEON_API_KEY|"
    r"NEON_BOOTSTRAP_DATABASE_URL)$"
)
_INVALID_GATE = re.compile(r"^invalid:GITHUB_(?:RUN_ID|RUN_ATTEMPT)$")
_HTTP_GATE = re.compile(r"^(?:github_actions|neon_api)_http_[1-5]\d{2}$")
_INVALID_NEON_RESPONSE_GATE = re.compile(
    r"^invalid_neon_response:(?:projects|branches|endpoints|organizations|members)$"
)

# A preserved NO-GO is evidence, not merely a document with bounded counters.
# Keep the producer's reachable reason/gate pairs closed and attach each pair to
# the last phase it can have reached.  This prevents a stale or forged report
# from claiming, for example, that PostgreSQL ran after a missing-secret gate.
_PHASE_ALL_ZERO = "ALL_ZERO"
_PHASE_NEON = "NEON"
_PHASE_POSTGRESQL = "POSTGRESQL"
_PHASE_TECHNICAL = "TECHNICAL"

_ALL_ZERO_GATES_BY_REASON: dict[str, frozenset[str]] = {
    "SECRET_MISSING": frozenset({"sensitive_value_too_short"}),
    "NEON_PROJECT_IDENTITY_AMBIGUOUS": frozenset(
        {
            "github_source_not_exact_main",
            "github_main_sha_invalid",
            "github_main_ref_mismatch",
            "neon_project_id_must_remain_absent",
        }
    ),
    "RECOVERY_BRANCH_NOT_FEASIBLE": frozenset(
        {
            "workflow_rerun_forbidden",
            "github_actions_state_unavailable",
            "github_actions_state_invalid",
            "github_main_ref_invalid",
            "github_actions_runs_invalid",
            "github_dispatch_history_invalid",
            "current_dispatch_not_observed",
            "exact_main_dispatch_not_unique",
            "github_actions_not_quiescent",
        }
    ),
    "DIRECT_ENDPOINT_NOT_PROVEN": frozenset(
        {
            "direct_database_url_invalid",
            "database_url_parameters_forbidden",
            "libpq_environment_forbidden",
        }
    ),
}

_NEON_GATES_BY_REASON: dict[str, frozenset[str]] = {
    "NEON_PROJECT_IDENTITY_AMBIGUOUS": frozenset(
        {
            "neon_route_forbidden",
            "neon_get_budget_exhausted",
            "neon_api_unavailable",
            "neon_api_invalid_json",
            "neon_api_invalid_document",
            "neon_api_non_finite_or_non_json_value",
            "unsafe_identifier",
            "project_details_missing",
            "project_pagination_invalid",
            "project_inventory_incomplete",
            "project_inventory_duplicate_id",
            "project_identity_discovery_budget_exceeded",
            "project_cursor_cycle",
            "endpoint_inventory_pagination_ambiguous",
            "positive_endpoint_candidate_invalid",
            "positive_endpoint_match_not_unique",
            "endpoint_detail_invalid",
            "endpoint_detail_missing",
            "endpoint_detail_state_invalid",
            "endpoint_detail_id_mismatch",
            "endpoint_detail_project_mismatch",
            "endpoint_detail_branch_mismatch",
            "endpoint_detail_host_mismatch",
            "endpoint_detail_type_mismatch",
            "endpoint_detail_not_active",
            "endpoint_detail_disabled",
            "endpoint_detail_pooled",
            "endpoint_detail_transitioning",
            "configured_organization_scope_mismatch",
            "neon_auth_scope_invalid",
            "neon_owner_scope_identity_mismatch",
            "user_organization_scope_ambiguous",
            "neon_api_credential_scope_unsupported",
            "configured_project_invalid",
            "configured_project_not_accessible",
            "configured_project_endpoint_missing",
            "configured_project_endpoint_not_unique",
            "project_detail_id_or_owner_mismatch",
            "project_endpoint_region_mismatch",
            "branch_endpoint_confirmation_mismatch",
            "branch_relationship_missing",
            "branch_project_mismatch",
            "dsn_endpoint_match_missing",
            "identity_incomplete_before_connection",
            "branch_parent_contract_invalid",
            "production_branch_parent_invalid",
        }
    ),
    "NEON_PRODUCTION_BRANCH_AMBIGUOUS": frozenset(
        {
            "branch_inventory_truncated",
            "branch_default_contract_invalid",
            "branch_project_mismatch",
            "default_branch_not_unique",
            "production_branch_state_missing",
            "production_branch_transitioning",
            "production_branch_not_ready",
            "dsn_branch_is_not_default",
            "production_branch_parent_unexpected",
        }
    ),
    "ENDPOINT_STATE_UNSUPPORTED": frozenset({"endpoint_state_unsupported"}),
    "DIRECT_ENDPOINT_NOT_PROVEN": frozenset(
        {
            "endpoint_state_contract_invalid",
            "endpoint_not_direct",
            "project_postgresql_version_contract_invalid",
            "project_postgresql_version_unsupported",
            "chronos_postgresql_version_not_certified",
            "startup_options_required",
            "first_sql_not_begin_read_only",
        }
    ),
    "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN": frozenset(
        {
            "autoscaling_limit_contract_invalid",
            "suspend_timeout_contract_invalid",
            "compute_return_to_idle_not_proven",
        }
    ),
    "RECOVERY_BRANCH_NOT_FEASIBLE": frozenset(
        {
            "project_scoped_api_key_owner_capacity_unproven",
            "personal_api_key_owner_capacity_unproven",
            "branch_count_contract_invalid",
            "branch_limit_contract_missing",
            "branch_limit_contract_invalid",
            "subscription_type_contract_missing",
            "purchase_requirement_ambiguous",
            "billing_plan_subscription_contradiction",
            "target_project_branch_count_not_proven",
            "branch_count_inventory_contradiction",
            "account_branch_limit_contradiction",
            "project_permission_insufficient_for_recovery",
            "history_retention_contract_invalid",
            "branch_capacity_ambiguous",
            "branch_capacity_exhausted",
            "recovery_branch_not_feasible",
        }
    ),
    "PURCHASE_REQUIRED": frozenset({"purchase_required"}),
}

_POSTGRESQL_GATES_BY_REASON: dict[str, frozenset[str]] = {
    "DIRECT_ENDPOINT_NOT_PROVEN": frozenset(
        {
            "postgresql_readonly_inspection_failed",
            "postgresql_row_missing",
            "timeout_setting_invalid",
            "default_transaction_read_only_not_enforced",
            "transaction_read_only_not_enforced",
            "statement_timeout_not_enforced",
            "lock_timeout_not_enforced",
            "search_path_not_enforced",
            "postgresql_identity_contract_invalid",
            "postgresql_version_contract_invalid",
            "postgresql_target_identity_mismatch",
            "postgresql_major_version_mismatch",
            "ssl_not_proven",
            "postgresql_connection_close_failed",
            "sql_budget_exhausted",
        }
    ),
    "UNEXPECTED_DATABASE_REVISION": frozenset(
        {
            "alembic_target_not_plain_permanent_table",
            "alembic_target_changed_before_lock",
            "alembic_revision_unavailable",
            "unexpected_database_revision",
        }
    ),
    "BOOTSTRAP_AUTHORITY_INSUFFICIENT": frozenset(
        {
            "lifecycle_admin_role_forbidden",
            "bootstrap_authority_capabilities_insufficient",
            "bootstrap_authority_inspection_failed",
            "privileged_catalog_not_visible",
            "existing_chronos_roles_unsafe",
            "existing_chronos_memberships_unsafe",
            "existing_chronos_objects_unsafe",
        }
    ),
    "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE": frozenset(
        {
            "single_connection_attempt_did_not_complete",
            "production_postgresql_connection_attempt_not_unique",
        }
    ),
}

_FULL_NEON_NO_GO_GATES = frozenset(
    {
        "branch_capacity_ambiguous",
        "branch_capacity_exhausted",
        "purchase_required",
        "recovery_branch_not_feasible",
        "identity_incomplete_before_connection",
        "startup_options_required",
        "first_sql_not_begin_read_only",
        "compute_return_to_idle_not_proven",
    }
)

_POSTGRESQL_EFFECT_KEYS = frozenset(
    {
        "postgresql_connection_attempts",
        "postgresql_connection_successes",
        "sql_statement_count",
        "sql_statement_completed_count",
        "sql_read_attempt_count",
        "sql_read_count",
        "begin_read_only_attempted",
        "begin_read_only_completed",
        "rollback_attempted",
        "rollback_completed",
    }
)
_READONLY_READ_ORDINALS = frozenset({1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16})
_DSN_PROFILE_KEYS = frozenset(
    {
        "contract_verdict",
        "query_keys",
        "reviewed_query_keys",
        "query_parse",
        "sslmode",
        "channel_binding",
        "port",
        "ambient_libpq_environment_count",
        "unexpected_parameter_count",
        "unexpected_parameter_name_hashes",
    }
)
_NEON_GO_KEYS = frozenset(
    {
        "identity_path",
        "identity_proof_mode",
        "project_identity_verdict",
        "neon_project_identity_verdict",
        "project_inventory_exhaustive",
        "project_pages_read",
        "projects_observed",
        "endpoint_projects_inspected",
        "endpoint_inventory_reads",
        "endpoint_detail_reads",
        "project_detail_reads",
        "branch_pages_read",
        "branch_endpoint_reads",
        "cursor_continuation_requested",
        "cursor_cycle_encountered",
        "positive_witness_checks",
        "project_id_sha256",
        "project_name_sha256",
        "region",
        "production_branch_id_sha256",
        "production_branch_name_sha256",
        "production_branch_default",
        "production_branch_parent_id_sha256",
        "recovery_parent_id_sha256",
        "owner_id_sha256",
        "endpoint_id_sha256",
        "endpoint_host_sha256",
        "endpoint_state",
        "suspend_timeout_seconds",
        "branch_state",
        "owner_branch_count",
        "branch_limit",
        "branch_capacity_proven",
        "bill_free_branch_capacity_proven",
        "owner_scope_verdict",
        "branch_count_reads",
        "subscription_type",
        "billing_plan",
        "target_project_branch_count",
        "history_retention_seconds",
        "postgresql_major",
        "autoscaling_limit_max_cu",
        "api_get_count",
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
    }
)
_NEON_EVIDENCE_KEYS = _NEON_GO_KEYS | frozenset(
    {
        "project_identity_verdict",
        "project_id_sha256",
        "endpoint_id_sha256",
        "branch_id_sha256",
        "owner_scope_proven",
        "libpq_environment_variable_count",
        "libpq_environment_name_hashes",
    }
)
_IDENTITY_AUDIT_REQUIRED_KEYS = frozenset(
    {
        "identity_path",
        "identity_proof_mode",
        "project_identity_verdict",
        "project_pages_read",
        "projects_observed",
        "endpoint_projects_inspected",
        "project_inventory_exhaustive",
        "endpoint_detail_reads",
        "project_detail_reads",
        "branch_pages_read",
        "branch_endpoint_reads",
        "cursor_continuation_requested",
        "cursor_cycle_encountered",
        "positive_witness_checks",
        "owner_scope_verdict",
        "owner_scope_proven",
        "branch_count_reads",
        "api_get_count",
    }
)
_POSTGRESQL_GO_KEYS = frozenset(
    {
        "database_name_sha256",
        "postgresql_version",
        "postgresql_version_num",
        "database_target_verified",
        "principal_target_verified",
        "current_revision",
        "revision_count",
        "ssl_verified",
        "default_transaction_read_only",
        "transaction_read_only",
        "statement_timeout_ms",
        "lock_timeout_ms",
        "lifecycle_admin_sha256",
        "bootstrap_authority_plausible",
        "bootstrap_targets_valid",
        "bootstrap_grantable_capabilities",
        "chronos_inventory_classification",
        "existing_chronos_roles",
        "existing_chronos_memberships",
        "existing_chronos_objects",
        "sql_statement_count",
        "sql_statement_completed_count",
        "sql_read_attempt_count",
        "sql_read_count",
        "sql_write_count",
        "begin_read_only_attempted",
        "begin_read_only_completed",
        "rollback_attempted",
        "rollback_completed",
    }
)
_POSTGRESQL_NO_GO_KEYS = frozenset(
    {
        "connection_established",
        "connection_close_completed",
        "default_transaction_read_only",
        "transaction_read_only",
        "statement_timeout_ms",
        "lock_timeout_ms",
        "search_path_pg_catalog",
        "database_target_verified",
        "principal_target_verified",
        "postgresql_version_num",
        "postgresql_major_verified",
        "ssl_verified",
        "alembic_target_safe",
        "revision_class",
        "revision_count",
        "bootstrap_authority_capabilities_proven",
        "privileged_catalog_visible",
        "chronos_roles_clean",
        "chronos_memberships_clean",
        "chronos_objects_clean",
        "inspection_failure_class",
    }
)
_GITHUB_KEYS = frozenset(
    {
        "queued",
        "in_progress",
        "current_run_excluded",
        "exact_main_dispatch_count",
        "authority_window_dispatch_count",
    }
)
_LIFECYCLE_KEYS = frozenset(
    {
        "endpoint_pre_wake_state",
        "scale_to_zero_classification",
        "configured_suspend_timeout_seconds",
        "effective_suspend_timeout_seconds",
        "identity_complete_before_wake",
        "connection_attempt_count",
        "connection_succeeded",
        "compute_wake_events",
        "compute_wake_events_observed",
        "wake_verdict",
        "maximum_preflight_wall_clock_seconds",
        "post_preflight_endpoint_state",
        "automatic_return_to_idle",
    }
)
_POSITIVE_WITNESSES = (
    "EXACT_DSN_HOST_MATCH",
    "PROJECT_SCOPED_ENDPOINT_INVENTORY",
    "ENDPOINT_DETAIL_CONCORDANT",
    "PROJECT_DETAIL_CONCORDANT",
    "DEFAULT_BRANCH_RELATIONSHIP_CONCORDANT",
    "BRANCH_ENDPOINT_CONCORDANT",
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_no_go_gate(value: str) -> bool:
    return (
        value in _NO_GO_GATE_VALUES
        or _MISSING_GATE.fullmatch(value) is not None
        or _INVALID_GATE.fullmatch(value) is not None
        or _HTTP_GATE.fullmatch(value) is not None
        or _INVALID_NEON_RESPONSE_GATE.fullmatch(value) is not None
    )


def _validated_environment_target() -> _DirectPostgresTarget | None:
    api_key = os.getenv("NEON_API_KEY", "")
    github_token = os.getenv("GITHUB_TOKEN", "")
    database_url = os.getenv("NEON_BOOTSTRAP_DATABASE_URL", "")
    if not api_key or not github_token or not database_url or _libpq_environment_variable_names():
        return None
    return _validated_direct_postgres_url(database_url)


def _bounded_counter(effects: Mapping[str, object], key: str, maximum: int) -> bool:
    if key not in effects:
        return False
    value = effects[key]
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _sensitive_values() -> tuple[str, ...]:
    values: set[str] = set()
    for name in ("GITHUB_TOKEN", "NEON_API_KEY", "NEON_PROJECT_ID", "NEON_ORG_ID"):
        value = os.getenv(name, "")
        if value:
            values.add(value)
            normalized = value.strip()
            if normalized:
                values.add(normalized)
    database_url = os.getenv("NEON_BOOTSTRAP_DATABASE_URL", "")
    if database_url:
        values.add(database_url)
        try:
            parsed = urlparse(database_url)
            # Only credentials are secrets. Host, database and user identities
            # are excluded structurally by the report schema and fingerprints;
            # substring-scanning short benign identities could otherwise make
            # the guard reject its own fixed fallback vocabulary.
            components = (parsed.password,)
            for component in components:
                if component:
                    values.add(component)
                    values.add(unquote(component))
        except (TypeError, UnicodeError, ValueError):
            # The complete malformed value remains forbidden even when its
            # components cannot safely be parsed.
            pass
    return tuple(sorted((value for value in values if value), key=len, reverse=True))


def _sensitive_values_are_scannable(values: tuple[str, ...]) -> bool:
    """Require enough literal entropy to distinguish leaks from digest vocabulary."""

    return all(len(value) >= 8 for value in values)


def _contains_raw_identity(
    value: object,
    *,
    key: str | None = None,
    sensitive_values: tuple[str, ...] | None = None,
) -> bool:
    secrets = _sensitive_values() if sensitive_values is None else sensitive_values
    if key is not None:
        normalized = key.lower()
        if not normalized.endswith("_sha256") and normalized in _RAW_IDENTITY_KEYS:
            return True
        if ("secret" in normalized or "password" in normalized) and normalized not in {
            "secrets_present",
            "sensitive_values_exposed",
        }:
            return True
        if "cursor" in normalized and normalized not in {
            "cursor_continuation_requested",
            "cursor_cycle_encountered",
        }:
            return True
    if isinstance(value, dict):
        return any(
            not isinstance(nested_key, str)
            or _contains_raw_identity(
                nested_value,
                key=nested_key,
                sensitive_values=secrets,
            )
            for nested_key, nested_value in value.items()
        )
    if isinstance(value, list):
        return any(
            _contains_raw_identity(
                item,
                key=key,
                sensitive_values=secrets,
            )
            for item in value
        )
    if isinstance(value, str):
        normalized = "" if key is None else key.lower()
        secret_scannable_field = (
            normalized.endswith("_sha256")
            or normalized.endswith("_hashes")
            or normalized in {"region", "observed_at", "postgresql_version"}
        )
        return (
            "postgresql://" in value.lower()
            or "postgresql+psycopg://" in value.lower()
            or _NEON_HOST.search(value) is not None
            or (secret_scannable_field and any(secret in value for secret in secrets))
        )
    return False


def _expected_source() -> dict[str, str]:
    run_id = os.getenv("GITHUB_RUN_ID", "UNKNOWN")
    if not run_id.isascii() or not run_id.isdigit() or int(run_id) < 1:
        run_id = "UNKNOWN"
    return {
        "repository": os.getenv("GITHUB_REPOSITORY", "UNKNOWN"),
        "ref": os.getenv("GITHUB_REF", "UNKNOWN"),
        "main_sha": os.getenv("GITHUB_SHA", "UNKNOWN"),
        "run_id": run_id,
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "UNKNOWN"),
    }


def _valid_source(value: object, *, go: bool) -> bool:
    if not isinstance(value, dict) or set(value) != _SOURCE_KEYS:
        return False
    if not all(isinstance(item, str) and item for item in value.values()):
        return False
    source = cast(dict[str, str], value)
    if source != _expected_source():
        return False
    if not go:
        return True
    return (
        source["repository"] == "dddur75/robin-stades-ng"
        and source["ref"] == "refs/heads/main"
        and _HEX_SHA.fullmatch(source["main_sha"]) is not None
        and source["run_id"].isdecimal()
        and int(source["run_id"]) > 0
        and source["run_attempt"] == "1"
    )


def _exact_int(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _nonnegative_int(value: object, *, maximum: int | None = None) -> bool:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return False
    return maximum is None or value <= maximum


def _valid_fingerprint(value: object, *, nullable: bool = False) -> bool:
    return (nullable and value is None) or (
        isinstance(value, str) and _FINGERPRINT.fullmatch(value) is not None
    )


def _valid_dsn_profile(value: object, *, go: bool) -> bool:
    if not isinstance(value, dict) or not set(value) <= _DSN_PROFILE_KEYS:
        return False
    profile = cast(dict[str, object], value)
    for key in ("query_keys", "reviewed_query_keys"):
        if key in profile:
            keys = profile[key]
            if not isinstance(keys, list) or not all(
                item in {"sslmode", "channel_binding"} for item in keys
            ):
                return False
    hashes = profile.get("unexpected_parameter_name_hashes", [])
    if not isinstance(hashes, list) or not all(_valid_fingerprint(item) for item in hashes):
        return False
    if go:
        return (
            set(profile)
            == {
                "contract_verdict",
                "query_keys",
                "sslmode",
                "channel_binding",
                "port",
                "ambient_libpq_environment_count",
                "unexpected_parameter_count",
                "unexpected_parameter_name_hashes",
            }
            and profile["contract_verdict"] == "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"
            and profile["query_keys"] == ["channel_binding", "sslmode"]
            and profile["sslmode"] in {"require", "verify-ca", "verify-full"}
            and profile["channel_binding"] == "require"
            and _exact_int(profile["port"], 5432)
            and _exact_int(profile["ambient_libpq_environment_count"], 0)
            and _exact_int(profile["unexpected_parameter_count"], 0)
            and profile["unexpected_parameter_name_hashes"] == []
        )
    if profile.get("contract_verdict") not in {
        "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT",
        "NEON_BOOTSTRAP_DSN_STILL_OUTSIDE_REVIEWED_CONTRACT",
    }:
        return False
    if "query_parse" in profile and profile["query_parse"] != "INVALID":
        return False
    if "sslmode" in profile and profile["sslmode"] not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        return False
    if "channel_binding" in profile and profile["channel_binding"] != "require":
        return False
    for key in (
        "port",
        "ambient_libpq_environment_count",
        "unexpected_parameter_count",
    ):
        if key in profile and not _nonnegative_int(profile[key]):
            return False
    return True


def _valid_neon_evidence(value: object) -> bool:
    if not isinstance(value, dict) or not set(value) <= _NEON_EVIDENCE_KEYS:
        return False
    evidence = cast(dict[str, object], value)
    mutation_count_keys = (
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
    )
    if any(key in evidence and not _exact_int(evidence[key], 0) for key in mutation_count_keys):
        return False
    boolean_keys = {
        "project_inventory_exhaustive",
        "cursor_continuation_requested",
        "cursor_cycle_encountered",
        "production_branch_default",
        "branch_capacity_proven",
        "bill_free_branch_capacity_proven",
        "owner_scope_proven",
    }
    integer_keys = {
        "project_pages_read",
        "projects_observed",
        "endpoint_projects_inspected",
        "endpoint_inventory_reads",
        "endpoint_detail_reads",
        "project_detail_reads",
        "branch_pages_read",
        "branch_endpoint_reads",
        "owner_branch_count",
        "branch_limit",
        "branch_count_reads",
        "target_project_branch_count",
        "history_retention_seconds",
        "postgresql_major",
        "api_get_count",
        "api_post_count",
        "api_put_count",
        "api_patch_count",
        "api_delete_count",
        "libpq_environment_variable_count",
    }
    enum_values = {
        "identity_path": {
            "POSITIVE_ENDPOINT_WITNESS",
            "CONFIGURED_PROJECT_ID",
            "BOUNDED_DISCOVERY",
        },
        "identity_proof_mode": {
            "POSITIVE_OWNERSHIP",
            "CONFIGURED_PROJECT_ID",
            "BOUNDED_DISCOVERY",
        },
        "project_identity_verdict": {
            "NEON_PROJECT_IDENTITY_NOT_PROVEN",
            "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN",
            "CONFIGURED_PROJECT_IDENTITY_PROVEN",
        },
        "neon_project_identity_verdict": {"NEON_PROJECT_IDENTITY_PROVEN"},
        "endpoint_state": {"active", "idle"},
        "branch_state": {"ready"},
        "owner_scope_verdict": {
            "OWNER_SCOPE_NOT_PROVEN",
            "ORGANIZATION_WIDE_API_KEY",
            "USER_KEY_SINGLE_ORGANIZATION_PROVEN",
            "USER_KEY_ORGANIZATION_CAPACITY_UNPROVEN",
            "PERSONAL_ADMIN_ORGANIZATION_PROVEN",
            "PROJECT_SCOPED_ORGANIZATION_KEY",
        },
        "subscription_type": {
            "UNKNOWN",
            "free_v2",
            "free_v3",
            "launch",
            "launch_v3",
            "scale",
            "scale_v3",
        },
        "billing_plan": {"free", "launch", "scale"},
    }
    for key, item in evidence.items():
        if key.endswith("_sha256") and not _valid_fingerprint(item, nullable=True):
            return False
        if key.endswith("_hashes") and (
            not isinstance(item, list) or not all(_valid_fingerprint(entry) for entry in item)
        ):
            return False
        if key in boolean_keys and not isinstance(item, bool):
            return False
        if key in integer_keys and not _nonnegative_int(item):
            return False
        if key == "suspend_timeout_seconds" and (
            not isinstance(item, int) or isinstance(item, bool) or item < -1
        ):
            return False
        if key == "autoscaling_limit_max_cu" and (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
            or float(item) < 0.25
        ):
            return False
        if key in enum_values and item not in enum_values[key]:
            return False
        if key == "region" and not _valid_fingerprint(item):
            return False
        if isinstance(item, dict):
            return False
        if isinstance(item, list):
            if not all(isinstance(entry, str) for entry in item):
                return False
            if key == "positive_witness_checks" and any(
                entry not in _POSITIVE_WITNESSES for entry in item
            ):
                return False
        if isinstance(item, float) and (item != item or item in {float("inf"), float("-inf")}):
            return False
    return True


def _valid_neon_phase_evidence(value: object, *, allow_zero_get: bool) -> bool:
    if not _valid_neon_evidence(value) or not isinstance(value, dict):
        return False
    evidence = cast(dict[str, object], value)
    if set(evidence) == _NEON_GO_KEYS:
        return _nonnegative_int(evidence["api_get_count"], maximum=25) and (
            allow_zero_get or cast(int, evidence["api_get_count"]) > 0
        )
    if not _IDENTITY_AUDIT_REQUIRED_KEYS <= set(evidence):
        return False
    api_get_count = evidence["api_get_count"]
    return (
        _nonnegative_int(api_get_count, maximum=25)
        and (allow_zero_get or cast(int, api_get_count) > 0)
        and evidence["project_identity_verdict"] == "NEON_PROJECT_IDENTITY_NOT_PROVEN"
        and evidence["identity_path"]
        in {
            "POSITIVE_ENDPOINT_WITNESS",
            "CONFIGURED_PROJECT_ID",
            "BOUNDED_DISCOVERY",
        }
        and evidence["identity_proof_mode"]
        == (
            "POSITIVE_OWNERSHIP"
            if evidence["identity_path"] == "POSITIVE_ENDPOINT_WITNESS"
            else evidence["identity_path"]
        )
    )


def _valid_neon_evidence_shape_for_gate(
    gate: str,
    value: Mapping[str, object],
) -> bool:
    is_full_observation = set(value) == _NEON_GO_KEYS
    return (gate in _FULL_NEON_NO_GO_GATES) is is_full_observation


def _valid_neon_terminal(gate: str, evidence: Mapping[str, object]) -> bool:
    if gate == "identity_incomplete_before_connection":
        return not (
            evidence.get("project_identity_verdict")
            in {
                "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN",
                "CONFIGURED_PROJECT_IDENTITY_PROVEN",
            }
            and evidence.get("production_branch_default") is True
            and evidence.get("project_inventory_exhaustive") is True
        )
    if gate == "branch_capacity_ambiguous":
        return evidence.get("branch_capacity_proven") is False
    if gate == "branch_capacity_exhausted":
        owner_count = evidence.get("owner_branch_count")
        branch_limit = evidence.get("branch_limit")
        return (
            isinstance(owner_count, int)
            and not isinstance(owner_count, bool)
            and isinstance(branch_limit, int)
            and not isinstance(branch_limit, bool)
            and evidence.get("branch_capacity_proven") is True
            and owner_count + 1 > branch_limit
        )
    if gate == "purchase_required":
        return evidence.get("bill_free_branch_capacity_proven") is False
    if gate == "recovery_branch_not_feasible":
        return evidence.get("history_retention_seconds") == 0
    if gate == "compute_return_to_idle_not_proven":
        timeout = evidence.get("suspend_timeout_seconds")
        return isinstance(timeout, int) and not isinstance(timeout, bool) and timeout == -1
    return True


def _valid_neon_go(value: object, *, controlled: bool) -> bool:
    if not isinstance(value, dict) or set(value) != _NEON_GO_KEYS:
        return False
    neon = cast(dict[str, object], value)
    if not _valid_neon_evidence(neon):
        return False
    fingerprints = (
        "project_id_sha256",
        "project_name_sha256",
        "production_branch_id_sha256",
        "production_branch_name_sha256",
        "recovery_parent_id_sha256",
        "owner_id_sha256",
        "endpoint_id_sha256",
        "endpoint_host_sha256",
    )
    if not all(_valid_fingerprint(neon[key]) for key in fingerprints):
        return False
    identity_fingerprints = {
        cast(str, neon[key])
        for key in (
            "project_id_sha256",
            "production_branch_id_sha256",
            "endpoint_id_sha256",
            "endpoint_host_sha256",
        )
    }
    if len(identity_fingerprints) != 4:
        return False
    if neon["production_branch_parent_id_sha256"] is not None:
        return False
    positive_identity = (
        neon["identity_path"] == "POSITIVE_ENDPOINT_WITNESS"
        and neon["identity_proof_mode"] == "POSITIVE_OWNERSHIP"
        and neon["project_identity_verdict"] == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
        and neon["positive_witness_checks"] == list(_POSITIVE_WITNESSES)
    )
    configured_identity = (
        not controlled
        and neon["identity_path"] == "CONFIGURED_PROJECT_ID"
        and neon["identity_proof_mode"] == "CONFIGURED_PROJECT_ID"
        and neon["project_identity_verdict"] == "CONFIGURED_PROJECT_IDENTITY_PROVEN"
        and neon["positive_witness_checks"] == list(_POSITIVE_WITNESSES)
    )
    configured_project_id = os.getenv("NEON_PROJECT_ID", "").strip()
    configured_binding = (
        bool(configured_project_id)
        and configured_identity
        and hmac.compare_digest(
            cast(str, neon["project_id_sha256"]),
            _fingerprint(configured_project_id),
        )
    )
    identity_path_bound = (
        positive_identity
        if controlled
        else (configured_binding if configured_project_id else positive_identity)
    )
    configured_organization_id = os.getenv("NEON_ORG_ID", "").strip()
    organization_binding = not configured_organization_id or hmac.compare_digest(
        cast(str, neon["owner_id_sha256"]),
        _fingerprint(configured_organization_id),
    )
    allowances = {"free": 10, "launch": 10, "scale": 25}
    subscription_plan = {
        "free_v2": "free",
        "free_v3": "free",
        "launch": "launch",
        "launch_v3": "launch",
        "scale": "scale",
        "scale_v3": "scale",
    }
    subscription = cast(str, neon["subscription_type"])
    billing_plan = cast(str, neon["billing_plan"])
    structured_get_count = sum(
        cast(int, neon[key])
        for key in (
            "project_pages_read",
            "endpoint_inventory_reads",
            "endpoint_detail_reads",
            "project_detail_reads",
            "branch_pages_read",
            "branch_endpoint_reads",
            "branch_count_reads",
        )
    )
    owner_scope_get_count = cast(int, neon["api_get_count"]) - structured_get_count
    owner_scope_get_count_valid = (
        owner_scope_get_count == 2
        if neon["owner_scope_verdict"] == "ORGANIZATION_WIDE_API_KEY"
        else 4 <= owner_scope_get_count <= 6
    )
    return (
        identity_path_bound
        and organization_binding
        and neon["neon_project_identity_verdict"] == "NEON_PROJECT_IDENTITY_PROVEN"
        and neon["project_inventory_exhaustive"] is True
        and neon["production_branch_default"] is True
        and neon["recovery_parent_id_sha256"] == neon["production_branch_id_sha256"]
        and neon["branch_state"] == "ready"
        and (
            neon["endpoint_state"] in {"active", "idle"}
            if controlled
            else neon["endpoint_state"] == "active"
        )
        and neon["branch_capacity_proven"] is True
        and neon["bill_free_branch_capacity_proven"] is True
        and neon["owner_scope_verdict"]
        in {
            "ORGANIZATION_WIDE_API_KEY",
            "PERSONAL_ADMIN_ORGANIZATION_PROVEN",
        }
        and neon["cursor_cycle_encountered"] is False
        and neon["cursor_continuation_requested"]
        is (cast(int, neon["project_pages_read"]) > 1 or cast(int, neon["branch_pages_read"]) > 1)
        and _nonnegative_int(neon["projects_observed"])
        and cast(int, neon["projects_observed"]) > 0
        and _nonnegative_int(neon["project_pages_read"])
        and 0 < cast(int, neon["project_pages_read"]) <= 3
        and cast(int, neon["projects_observed"]) <= cast(int, neon["project_pages_read"]) * 400
        and _nonnegative_int(neon["endpoint_projects_inspected"])
        and cast(int, neon["endpoint_projects_inspected"]) > 0
        and (
            cast(int, neon["endpoint_projects_inspected"]) == cast(int, neon["projects_observed"])
            if positive_identity
            else _exact_int(neon["endpoint_projects_inspected"], 1)
        )
        and neon["endpoint_inventory_reads"] == neon["endpoint_projects_inspected"]
        and _exact_int(neon["project_detail_reads"], 1)
        and _nonnegative_int(neon["branch_pages_read"])
        and 0 < cast(int, neon["branch_pages_read"]) <= 3
        and (positive_identity or configured_identity)
        and _exact_int(neon["endpoint_detail_reads"], 1)
        and _exact_int(neon["branch_endpoint_reads"], 1)
        and _nonnegative_int(neon["branch_count_reads"])
        and _exact_int(
            neon["branch_count_reads"],
            cast(int, neon["projects_observed"]),
        )
        and _nonnegative_int(neon["api_get_count"], maximum=25)
        and owner_scope_get_count_valid
        and all(
            _exact_int(neon[key], 0)
            for key in (
                "api_post_count",
                "api_put_count",
                "api_patch_count",
                "api_delete_count",
            )
        )
        and _nonnegative_int(neon["owner_branch_count"])
        and _nonnegative_int(neon["target_project_branch_count"])
        and cast(int, neon["target_project_branch_count"]) > 0
        and cast(int, neon["owner_branch_count"]) >= cast(int, neon["target_project_branch_count"])
        and billing_plan in allowances
        and (subscription == "UNKNOWN" or subscription_plan.get(subscription) == billing_plan)
        and _nonnegative_int(neon["branch_limit"])
        and cast(int, neon["branch_limit"]) > cast(int, neon["owner_branch_count"])
        and cast(int, neon["target_project_branch_count"]) + 1 <= allowances[billing_plan]
        and _nonnegative_int(neon["history_retention_seconds"])
        and cast(int, neon["history_retention_seconds"]) > 0
        and neon["postgresql_major"] == 16
    )


def _valid_postgresql_go(value: object, *, controlled: bool) -> bool:
    expected_keys = _POSTGRESQL_GO_KEYS | (
        frozenset({"connection_attempt_count"}) if controlled else frozenset()
    )
    if not isinstance(value, dict) or set(value) != expected_keys:
        return False
    pg = cast(dict[str, object], value)
    capabilities = [
        "schema_usage_grantable",
        "schema_create_grantable",
        "table_select_grantable",
        "table_insert_grantable",
        "table_update_grantable",
        "table_delete_grantable",
        "authority_role_memberships_clean",
    ]
    return (
        _valid_fingerprint(pg["database_name_sha256"])
        and _valid_fingerprint(pg["lifecycle_admin_sha256"])
        and isinstance(pg["postgresql_version"], str)
        and _POSTGRESQL_VERSION.fullmatch(pg["postgresql_version"]) is not None
        and _nonnegative_int(pg["postgresql_version_num"])
        and 160_000 <= cast(int, pg["postgresql_version_num"]) < 170_000
        and pg["database_target_verified"] is True
        and pg["principal_target_verified"] is True
        and pg["current_revision"]
        in (
            {
                "0013_historical_evidence_index",
                "0014_chronos_control_plane_v2",
            }
            if controlled
            else {"0013_historical_evidence_index"}
        )
        and _exact_int(pg["revision_count"], 1)
        and pg["ssl_verified"] is True
        and pg["default_transaction_read_only"] is True
        and pg["transaction_read_only"] is True
        and _exact_int(pg["statement_timeout_ms"], 15_000)
        and _exact_int(pg["lock_timeout_ms"], 3_000)
        and pg["bootstrap_authority_plausible"] is True
        and pg["bootstrap_targets_valid"] is True
        and pg["bootstrap_grantable_capabilities"] == capabilities
        and pg["chronos_inventory_classification"] == "ABSENT"
        and pg["existing_chronos_roles"] == []
        and pg["existing_chronos_memberships"] == []
        and pg["existing_chronos_objects"] == []
        and _exact_int(pg["sql_statement_count"], 18)
        and _exact_int(pg["sql_statement_completed_count"], 18)
        and _exact_int(pg["sql_read_attempt_count"], 15)
        and _exact_int(pg["sql_read_count"], 15)
        and _exact_int(pg["sql_write_count"], 0)
        and all(
            _exact_int(pg[key], 1)
            for key in (
                "begin_read_only_attempted",
                "begin_read_only_completed",
                "rollback_attempted",
                "rollback_completed",
            )
        )
        and (not controlled or _exact_int(pg["connection_attempt_count"], 1))
    )


def _valid_postgresql_no_go(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _POSTGRESQL_NO_GO_KEYS:
        return False
    pg = cast(dict[str, object], value)
    nullable_booleans = (
        "connection_close_completed",
        "default_transaction_read_only",
        "transaction_read_only",
        "search_path_pg_catalog",
        "database_target_verified",
        "principal_target_verified",
        "postgresql_major_verified",
        "ssl_verified",
        "alembic_target_safe",
        "bootstrap_authority_capabilities_proven",
        "privileged_catalog_visible",
        "chronos_roles_clean",
        "chronos_memberships_clean",
        "chronos_objects_clean",
    )
    nullable_integers = (
        ("statement_timeout_ms", 86_400_000),
        ("lock_timeout_ms", 86_400_000),
        ("postgresql_version_num", 1_000_000),
        ("revision_count", 1_000_000),
    )
    return (
        isinstance(pg["connection_established"], bool)
        and all(pg[key] is None or isinstance(pg[key], bool) for key in nullable_booleans)
        and all(
            pg[key] is None or _nonnegative_int(pg[key], maximum=maximum)
            for key, maximum in nullable_integers
        )
        and pg["revision_class"]
        in {
            "NOT_OBSERVED",
            "0012_universal_genome_v2",
            "0013_historical_evidence_index",
            "0014_chronos_control_plane_v2",
            "OTHER_OR_NON_SINGLETON",
        }
        and pg["inspection_failure_class"]
        in {
            "NOT_OBSERVED",
            "CONNECTION_EXCEPTION",
            "CONTROL_FLOW_EXCEPTION",
            "SQL_EXECUTION_EXCEPTION",
            "RESULT_PROCESSING_EXCEPTION",
            "ROLLBACK_EXCEPTION",
            "CLOSE_EXCEPTION",
        }
        and (
            (pg["revision_count"] is None and pg["revision_class"] == "NOT_OBSERVED")
            or (pg["revision_count"] is not None and pg["revision_class"] != "NOT_OBSERVED")
        )
    )


def _valid_github(
    value: object,
    source: Mapping[str, object],
    *,
    controlled: bool,
) -> bool:
    expected_keys = (
        _GITHUB_KEYS if controlled else _GITHUB_KEYS - {"authority_window_dispatch_count"}
    )
    return (
        isinstance(value, dict)
        and set(value) == expected_keys
        and _exact_int(value.get("queued"), 0)
        and _exact_int(value.get("in_progress"), 0)
        and _exact_int(value.get("exact_main_dispatch_count"), 1)
        and (not controlled or _exact_int(value.get("authority_window_dispatch_count"), 1))
        and _exact_int(value.get("current_run_excluded"), int(str(source["run_id"])))
    )


def _valid_lifecycle(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _LIFECYCLE_KEYS:
        return False
    lifecycle = cast(dict[str, object], value)
    state = lifecycle["endpoint_pre_wake_state"]
    observed = 1 if state == "idle" else 0
    expected_wake = (
        "CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE"
        if state == "idle"
        else "COMPUTE_WAKE_UPPER_BOUND_ONE_FROM_ACTIVE_SNAPSHOT"
    )
    return (
        state in {"active", "idle"}
        and lifecycle["scale_to_zero_classification"]
        in {"FINITE_SCALE_TO_ZERO", "DEFAULT_SCALE_TO_ZERO"}
        and _nonnegative_int(lifecycle["configured_suspend_timeout_seconds"])
        and _nonnegative_int(lifecycle["effective_suspend_timeout_seconds"])
        and lifecycle["identity_complete_before_wake"] is True
        and _exact_int(lifecycle["connection_attempt_count"], 1)
        and lifecycle["connection_succeeded"] is True
        and _exact_int(lifecycle["compute_wake_events"], 1)
        and _exact_int(lifecycle["compute_wake_events_observed"], observed)
        and lifecycle["wake_verdict"] == expected_wake
        and _exact_int(lifecycle["maximum_preflight_wall_clock_seconds"], 120)
        and lifecycle["post_preflight_endpoint_state"] == "NOT_POLLED"
        and lifecycle["automatic_return_to_idle"] == "CONFIGURATION_PROVEN_NOT_WAITED_FOR"
    )


def _valid_controlled_lifecycle_bindings(
    report: Mapping[str, object],
    neon: Mapping[str, object],
) -> bool:
    lifecycle = report.get("lifecycle")
    if not isinstance(lifecycle, dict):
        return False
    state = neon["endpoint_state"]
    configured = neon["suspend_timeout_seconds"]
    if lifecycle.get("endpoint_pre_wake_state") != state or (
        lifecycle.get("configured_suspend_timeout_seconds") != configured
    ):
        return False
    if configured == 0:
        timeout_bound = (
            lifecycle.get("scale_to_zero_classification") == "DEFAULT_SCALE_TO_ZERO"
            and lifecycle.get("effective_suspend_timeout_seconds") == 300
        )
    else:
        timeout_bound = (
            isinstance(configured, int)
            and not isinstance(configured, bool)
            and _MINIMUM_CONTROLLED_SUSPEND_TIMEOUT_SECONDS <= configured <= 604_800
            and lifecycle.get("scale_to_zero_classification") == "FINITE_SCALE_TO_ZERO"
            and lifecycle.get("effective_suspend_timeout_seconds") == configured
        )
    expected_certainty = (
        "OBSERVED_IDLE_TO_CONNECTED"
        if state == "idle"
        else "CONSERVATIVE_UPPER_BOUND_FROM_ACTIVE_SNAPSHOT"
    )
    return timeout_bound and report.get("compute_wake_certainty") == expected_certainty


def _valid_environment_bindings(
    report: Mapping[str, object],
    *,
    controlled: bool,
) -> bool:
    target = _validated_environment_target()
    if target is None:
        return False
    profile = report.get("dsn_security_profile")
    neon = report.get("neon")
    postgresql = report.get("postgresql")
    if (
        not isinstance(profile, dict)
        or not isinstance(neon, dict)
        or not isinstance(postgresql, dict)
    ):
        return False
    bindings = (
        (cast(str, neon.get("endpoint_host_sha256")), _fingerprint(target.host)),
        (
            cast(str, postgresql.get("database_name_sha256")),
            _fingerprint(target.database),
        ),
        (
            cast(str, postgresql.get("lifecycle_admin_sha256")),
            _fingerprint(target.username),
        ),
    )
    configured_project_id = os.getenv("NEON_PROJECT_ID", "").strip()
    project_binding = (
        controlled
        or not configured_project_id
        or hmac.compare_digest(
            cast(str, neon.get("project_id_sha256")),
            _fingerprint(configured_project_id),
        )
    )
    return (
        all(
            isinstance(observed, str) and hmac.compare_digest(observed, expected)
            for observed, expected in bindings
        )
        and profile.get("sslmode") == target.sslmode
        and profile.get("channel_binding") == target.channel_binding
        and profile.get("port") == target.port
        and project_binding
    )


def _valid_no_go_lifecycle(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _LIFECYCLE_KEYS:
        return False
    lifecycle = cast(dict[str, object], value)
    attempts = lifecycle["connection_attempt_count"]
    wake_events = lifecycle["compute_wake_events"]
    observed_wakes = lifecycle["compute_wake_events_observed"]
    return (
        lifecycle["endpoint_pre_wake_state"] in {"NOT_OBSERVED", "active", "idle"}
        and lifecycle["scale_to_zero_classification"]
        in {"UNPROVEN", "FINITE_SCALE_TO_ZERO", "DEFAULT_SCALE_TO_ZERO"}
        and (
            lifecycle["configured_suspend_timeout_seconds"] is None
            or (
                isinstance(lifecycle["configured_suspend_timeout_seconds"], int)
                and not isinstance(lifecycle["configured_suspend_timeout_seconds"], bool)
                and lifecycle["configured_suspend_timeout_seconds"] >= -1
            )
        )
        and (
            lifecycle["effective_suspend_timeout_seconds"] is None
            or (
                isinstance(lifecycle["effective_suspend_timeout_seconds"], int)
                and not isinstance(lifecycle["effective_suspend_timeout_seconds"], bool)
                and lifecycle["effective_suspend_timeout_seconds"] >= -1
            )
        )
        and isinstance(lifecycle["identity_complete_before_wake"], bool)
        and _nonnegative_int(attempts, maximum=1)
        and isinstance(lifecycle["connection_succeeded"], bool)
        and (not lifecycle["connection_succeeded"] or attempts == 1)
        and _nonnegative_int(wake_events, maximum=1)
        and _nonnegative_int(observed_wakes, maximum=1)
        and cast(int, observed_wakes) <= cast(int, wake_events)
        and lifecycle["wake_verdict"]
        in {
            "CONTROLLED_NEON_READONLY_WAKE_NOT_AUTHORIZED",
            "CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE",
            "COMPUTE_WAKE_UPPER_BOUND_ONE_FROM_ACTIVE_SNAPSHOT",
            "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
        }
        and _exact_int(lifecycle["maximum_preflight_wall_clock_seconds"], 120)
        and lifecycle["post_preflight_endpoint_state"] == "NOT_POLLED"
        and lifecycle["automatic_return_to_idle"]
        in {"UNPROVEN", "CONFIGURATION_PROVEN_NOT_WAITED_FOR"}
    )


def _valid_no_go_github(value: object, source: Mapping[str, object]) -> bool:
    source_run_id = str(source["run_id"])
    if source_run_id == "UNKNOWN":
        expected_excluded_run_id = 0
    elif source_run_id.isascii() and source_run_id.isdigit():
        expected_excluded_run_id = int(source_run_id)
    else:
        return False
    return (
        isinstance(value, dict)
        and set(value) == _GITHUB_KEYS
        and _nonnegative_int(value.get("queued"), maximum=100)
        and _nonnegative_int(value.get("in_progress"), maximum=100)
        and _nonnegative_int(value.get("exact_main_dispatch_count"), maximum=100)
        and _nonnegative_int(value.get("authority_window_dispatch_count"), maximum=100)
        and _exact_int(value.get("current_run_excluded"), expected_excluded_run_id)
    )


def _valid_effects(value: object, *, controlled: bool = True) -> bool:
    expected_keys = _EFFECT_KEYS if controlled else _EFFECT_KEYS - {"compute_wake_events"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        return False
    effects = cast(dict[str, object], value)
    if any(not _exact_int(effects[key], 0) for key in _ZERO_EFFECTS):
        return False
    if any(
        not _bounded_counter(effects, key, maximum)
        for key, maximum in _EFFECT_MAXIMUMS.items()
        if key in expected_keys
    ):
        return False
    return (
        cast(int, effects["neon_get_count"]) <= 25
        and cast(int, effects["postgresql_connection_successes"])
        <= cast(int, effects["postgresql_connection_attempts"])
        and cast(int, effects["sql_statement_completed_count"])
        <= cast(int, effects["sql_statement_count"])
        and cast(int, effects["sql_read_count"])
        <= cast(int, effects["sql_read_attempt_count"])
        <= cast(int, effects["sql_statement_count"])
        and cast(int, effects["begin_read_only_completed"])
        <= cast(int, effects["begin_read_only_attempted"])
        and cast(int, effects["rollback_completed"]) <= cast(int, effects["rollback_attempted"])
    )


def _no_go_phase(reason: str, gate: str, *, controlled: bool) -> str | None:
    if gate in _TECHNICAL_FAILURE_GATES:
        return _PHASE_TECHNICAL if reason == "NEON_PROJECT_IDENTITY_AMBIGUOUS" else None
    if reason == "SECRET_MISSING" and _MISSING_GATE.fullmatch(gate) is not None:
        return _PHASE_ALL_ZERO
    if reason == "RECOVERY_BRANCH_NOT_FEASIBLE" and gate == "invalid:GITHUB_RUN_ID":
        return _PHASE_ALL_ZERO
    if (
        reason == "RECOVERY_BRANCH_NOT_FEASIBLE"
        and gate.startswith("github_actions_http_")
        and _HTTP_GATE.fullmatch(gate) is not None
    ):
        return _PHASE_ALL_ZERO
    if (
        reason == "NEON_PROJECT_IDENTITY_AMBIGUOUS"
        and gate.startswith("neon_api_http_")
        and _HTTP_GATE.fullmatch(gate) is not None
    ):
        return _PHASE_NEON
    if _INVALID_NEON_RESPONSE_GATE.fullmatch(gate) is not None:
        if reason == "NEON_PROJECT_IDENTITY_AMBIGUOUS" and gate != (
            "invalid_neon_response:members"
        ):
            return _PHASE_NEON
        if reason == "RECOVERY_BRANCH_NOT_FEASIBLE" and gate == ("invalid_neon_response:members"):
            return _PHASE_NEON
        return None
    if gate in _ALL_ZERO_GATES_BY_REASON.get(reason, frozenset()):
        if gate == "neon_project_id_must_remain_absent" and not controlled:
            return None
        return _PHASE_ALL_ZERO
    if gate in _NEON_GATES_BY_REASON.get(reason, frozenset()):
        if (
            gate
            in {
                "identity_incomplete_before_connection",
                "startup_options_required",
                "first_sql_not_begin_read_only",
                "compute_return_to_idle_not_proven",
            }
            and not controlled
        ):
            return None
        return _PHASE_NEON
    if gate in _POSTGRESQL_GATES_BY_REASON.get(reason, frozenset()):
        if reason == "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE" and not controlled:
            return None
        return _PHASE_POSTGRESQL
    return None


def _all_zero_effects(effects: Mapping[str, object], *, controlled: bool) -> bool:
    keys = set(_POSTGRESQL_EFFECT_KEYS) | {"neon_get_count"}
    if controlled:
        keys.add("compute_wake_events")
    return all(_exact_int(effects[key], 0) for key in keys)


def _valid_libpq_no_go_evidence(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "libpq_environment_variable_count",
        "libpq_environment_name_hashes",
    }:
        return False
    count = value["libpq_environment_variable_count"]
    hashes = value["libpq_environment_name_hashes"]
    return (
        _nonnegative_int(count, maximum=100)
        and cast(int, count) > 0
        and isinstance(hashes, list)
        and len(hashes) == count
        and all(_valid_fingerprint(entry) for entry in hashes)
        and len(set(cast(list[str], hashes))) == len(hashes)
    )


def _valid_technical_effects(
    effects: Mapping[str, object],
    *,
    controlled: bool,
    skipped: bool,
) -> bool:
    expected = {
        "neon_get_count": 0 if skipped else 25,
        "postgresql_connection_attempts": 0 if skipped else 1,
        "postgresql_connection_successes": 0 if skipped else 1,
        "sql_statement_count": 0 if skipped else 25,
        "sql_statement_completed_count": 0 if skipped else 25,
        "sql_read_attempt_count": 0 if skipped else 25,
        "sql_read_count": 0 if skipped else 25,
        "begin_read_only_attempted": 0 if skipped else 1,
        "begin_read_only_completed": 0 if skipped else 1,
        "rollback_attempted": 0 if skipped else 1,
        "rollback_completed": 0 if skipped else 1,
    }
    if controlled:
        expected["compute_wake_events"] = 0 if skipped else 1
    return all(_exact_int(effects[key], value) for key, value in expected.items())


def _valid_sql_ledger_prefix(effects: Mapping[str, object]) -> tuple[int, int] | None:
    attempted = cast(int, effects["sql_statement_count"])
    completed = cast(int, effects["sql_statement_completed_count"])
    rollback_attempted = cast(int, effects["rollback_attempted"])
    rollback_completed = cast(int, effects["rollback_completed"])
    main_attempted = attempted - rollback_attempted
    main_completed = completed - rollback_completed
    if (
        main_attempted < 0
        or main_attempted > 17
        or main_completed < 0
        or main_completed > main_attempted
        or main_attempted - main_completed > 1
        or rollback_attempted not in {0, 1}
        or rollback_completed not in {0, 1}
        or rollback_completed > rollback_attempted
    ):
        return None
    begin_attempted = 1 if main_attempted >= 1 else 0
    begin_completed = 1 if main_completed >= 1 else 0
    if (
        not _exact_int(effects["begin_read_only_attempted"], begin_attempted)
        or not _exact_int(effects["begin_read_only_completed"], begin_completed)
        or (begin_completed == 1 and rollback_attempted != 1)
        or (begin_completed == 0 and rollback_attempted != 0)
    ):
        return None
    expected_read_attempts = sum(
        ordinal in _READONLY_READ_ORDINALS for ordinal in range(main_attempted)
    )
    expected_read_completed = sum(
        ordinal in _READONLY_READ_ORDINALS for ordinal in range(main_completed)
    )
    if not _exact_int(effects["sql_read_attempt_count"], expected_read_attempts) or not _exact_int(
        effects["sql_read_count"], expected_read_completed
    ):
        return None
    return main_attempted, main_completed


def _postgresql_evidence_groups(
    partial_pg: Mapping[str, object],
    *,
    controlled: bool,
) -> tuple[tuple[int, tuple[str, ...], bool], ...]:
    version_num = partial_pg["postgresql_version_num"]
    identity_passed = (
        partial_pg["database_target_verified"] is True
        and partial_pg["principal_target_verified"] is True
        and isinstance(version_num, int)
        and not isinstance(version_num, bool)
        and 160_000 <= version_num < 170_000
        and partial_pg["postgresql_major_verified"] is True
    )
    accepted_revisions = (
        {
            "0013_historical_evidence_index",
            "0014_chronos_control_plane_v2",
        }
        if controlled
        else {"0013_historical_evidence_index"}
    )
    revision_passed = partial_pg["revision_class"] in accepted_revisions and _exact_int(
        partial_pg["revision_count"], 1
    )
    return (
        (
            1,
            ("default_transaction_read_only",),
            partial_pg["default_transaction_read_only"] is True,
        ),
        (2, ("transaction_read_only",), partial_pg["transaction_read_only"] is True),
        (3, ("statement_timeout_ms",), _exact_int(partial_pg["statement_timeout_ms"], 15_000)),
        (4, ("lock_timeout_ms",), _exact_int(partial_pg["lock_timeout_ms"], 3_000)),
        (5, ("search_path_pg_catalog",), partial_pg["search_path_pg_catalog"] is True),
        (
            6,
            (
                "database_target_verified",
                "principal_target_verified",
                "postgresql_version_num",
                "postgresql_major_verified",
            ),
            identity_passed,
        ),
        (7, ("ssl_verified",), partial_pg["ssl_verified"] is True),
        (8, ("alembic_target_safe",), partial_pg["alembic_target_safe"] is True),
        (11, ("revision_class", "revision_count"), revision_passed),
        (
            12,
            ("bootstrap_authority_capabilities_proven",),
            partial_pg["bootstrap_authority_capabilities_proven"] is True,
        ),
        (13, ("privileged_catalog_visible",), partial_pg["privileged_catalog_visible"] is True),
        (14, ("chronos_roles_clean",), partial_pg["chronos_roles_clean"] is True),
        (15, ("chronos_memberships_clean",), partial_pg["chronos_memberships_clean"] is True),
        (16, ("chronos_objects_clean",), partial_pg["chronos_objects_clean"] is True),
    )


def _valid_postgresql_prefix_evidence(
    partial_pg: Mapping[str, object],
    *,
    gate: str,
    main_attempted: int,
    main_completed: int,
    controlled: bool,
) -> bool:
    last_completed_ordinal = main_completed - 1
    for ordinal, keys, passed in _postgresql_evidence_groups(
        partial_pg,
        controlled=controlled,
    ):
        observed = (
            partial_pg["revision_count"] is not None
            if ordinal == 11
            else any(partial_pg[key] is not None for key in keys)
        )
        failed_privileged_catalog_probe = (
            gate == "privileged_catalog_not_visible"
            and ordinal == 13
            and main_attempted == 14
            and main_completed == 13
            and partial_pg["privileged_catalog_visible"] is False
        )
        if ordinal >= main_completed and observed and not failed_privileged_catalog_probe:
            return False
        if ordinal < last_completed_ordinal and not passed:
            return False
        if ordinal == 6:
            identity_values = [partial_pg[key] for key in keys]
            if any(value is not None for value in identity_values) and any(
                value is None for value in identity_values
            ):
                return False
    return True


def _valid_postgresql_terminal(
    reason: str,
    gate: str,
    partial_pg: Mapping[str, object],
    effects: Mapping[str, object],
    *,
    main_attempted: int,
    main_completed: int,
    controlled: bool,
) -> bool:
    if gate == "single_connection_attempt_did_not_complete":
        return (
            partial_pg["connection_established"] is False
            and partial_pg["inspection_failure_class"] == "CONNECTION_EXCEPTION"
            and main_attempted == 0
            and main_completed == 0
        )
    if partial_pg["connection_established"] is not True:
        return (
            gate == "postgresql_readonly_inspection_failed"
            and partial_pg["inspection_failure_class"] == "CONNECTION_EXCEPTION"
            and main_attempted == 0
            and main_completed == 0
        )
    if gate == "postgresql_readonly_inspection_failed":
        failure_class = partial_pg["inspection_failure_class"]
        return (
            (
                failure_class == "CONNECTION_EXCEPTION"
                and main_attempted == 0
                and main_completed == 0
            )
            or (
                failure_class == "CONTROL_FLOW_EXCEPTION"
                and (
                    (main_attempted == 0 and main_completed == 0)
                    or (
                        main_attempted == 17
                        and main_completed == 17
                        and effects["rollback_completed"] == 1
                        and all(
                            passed
                            for _ordinal, _keys, passed in _postgresql_evidence_groups(
                                partial_pg,
                                controlled=controlled,
                            )
                        )
                    )
                )
            )
            or (failure_class == "SQL_EXECUTION_EXCEPTION" and main_attempted == main_completed + 1)
            or (
                failure_class == "RESULT_PROCESSING_EXCEPTION"
                and main_attempted == main_completed
                and main_completed > 1
                and (
                    (main_completed == 11 and partial_pg["alembic_target_safe"] is True)
                    or any(
                        ordinal == main_completed - 1
                        and all(partial_pg[key] is None for key in keys)
                        for ordinal, keys, _passed in _postgresql_evidence_groups(
                            partial_pg,
                            controlled=controlled,
                        )
                    )
                )
            )
            or (
                failure_class == "ROLLBACK_EXCEPTION"
                and main_attempted == 17
                and main_completed == 17
                and effects["rollback_attempted"] == 1
                and effects["rollback_completed"] == 0
                and all(
                    passed
                    for _ordinal, _keys, passed in _postgresql_evidence_groups(
                        partial_pg,
                        controlled=controlled,
                    )
                )
            )
        )
    if gate == "postgresql_row_missing":
        terminal_group_unobserved = main_completed == 11 or any(
            ordinal == main_completed - 1 and all(partial_pg[key] is None for key in keys)
            for ordinal, keys, _passed in _postgresql_evidence_groups(
                partial_pg,
                controlled=controlled,
            )
        )
        return (
            partial_pg["inspection_failure_class"] == "NOT_OBSERVED"
            and main_attempted == main_completed
            and main_completed > 1
            and main_completed - 1 in {1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 13}
            and terminal_group_unobserved
        )
    if gate == "timeout_setting_invalid":
        timeout_key = "statement_timeout_ms" if main_completed == 4 else "lock_timeout_ms"
        return (
            partial_pg["inspection_failure_class"] == "NOT_OBSERVED"
            and main_attempted == main_completed
            and main_completed in {4, 5}
            and partial_pg[timeout_key] is None
        )

    exact_terminal: dict[str, int] = {
        "default_transaction_read_only_not_enforced": 1,
        "transaction_read_only_not_enforced": 2,
        "statement_timeout_not_enforced": 3,
        "lock_timeout_not_enforced": 4,
        "search_path_not_enforced": 5,
        "postgresql_identity_contract_invalid": 6,
        "postgresql_version_contract_invalid": 6,
        "postgresql_target_identity_mismatch": 6,
        "postgresql_major_version_mismatch": 6,
        "lifecycle_admin_role_forbidden": 6,
        "ssl_not_proven": 7,
        "alembic_target_not_plain_permanent_table": 8,
        "alembic_target_changed_before_lock": 10,
        "unexpected_database_revision": 11,
        "bootstrap_authority_capabilities_insufficient": 12,
        "privileged_catalog_not_visible": 13,
        "existing_chronos_roles_unsafe": 14,
        "existing_chronos_memberships_unsafe": 15,
        "existing_chronos_objects_unsafe": 16,
    }
    if gate == "alembic_revision_unavailable":
        return (
            partial_pg["inspection_failure_class"]
            in {"NOT_OBSERVED", "SQL_EXECUTION_EXCEPTION", "RESULT_PROCESSING_EXCEPTION"}
            and main_attempted == 12
            and main_completed in {11, 12}
            and partial_pg["revision_count"] is None
            and partial_pg["revision_class"] == "NOT_OBSERVED"
        )
    if gate == "postgresql_connection_close_failed":
        return (
            partial_pg["inspection_failure_class"] == "CLOSE_EXCEPTION"
            and main_attempted == 17
            and main_completed == 17
            and effects["rollback_completed"] == 1
            and partial_pg["connection_close_completed"] is False
            and all(
                passed
                for _ordinal, _keys, passed in _postgresql_evidence_groups(
                    partial_pg,
                    controlled=controlled,
                )
            )
        )
    terminal = exact_terminal.get(gate)
    expected_completed = (
        {terminal, terminal + 1}
        if gate == "privileged_catalog_not_visible" and terminal is not None
        else ({terminal + 1} if terminal is not None else set())
    )
    if (
        terminal is None
        or main_attempted != terminal + 1
        or main_completed not in expected_completed
    ):
        return False
    expected_failure_class = (
        "SQL_EXECUTION_EXCEPTION"
        if gate == "privileged_catalog_not_visible" and main_completed == terminal
        else "NOT_OBSERVED"
    )
    if partial_pg["inspection_failure_class"] != expected_failure_class:
        return False
    terminal_checks: dict[str, bool] = {
        "default_transaction_read_only_not_enforced": partial_pg["default_transaction_read_only"]
        is False,
        "transaction_read_only_not_enforced": partial_pg["transaction_read_only"] is False,
        "statement_timeout_not_enforced": partial_pg["statement_timeout_ms"] not in {None, 15_000},
        "lock_timeout_not_enforced": partial_pg["lock_timeout_ms"] not in {None, 3_000},
        "search_path_not_enforced": partial_pg["search_path_pg_catalog"] is False,
        "postgresql_identity_contract_invalid": partial_pg["database_target_verified"] is None,
        "postgresql_version_contract_invalid": partial_pg["postgresql_version_num"] is None,
        "postgresql_target_identity_mismatch": (
            partial_pg["database_target_verified"] is False
            or partial_pg["principal_target_verified"] is False
        ),
        "postgresql_major_version_mismatch": partial_pg["postgresql_major_verified"] is False,
        "lifecycle_admin_role_forbidden": (
            partial_pg["database_target_verified"] is True
            and partial_pg["principal_target_verified"] is True
            and partial_pg["postgresql_major_verified"] is True
        ),
        "ssl_not_proven": partial_pg["ssl_verified"] is False,
        "alembic_target_not_plain_permanent_table": partial_pg["alembic_target_safe"] is False,
        "alembic_target_changed_before_lock": partial_pg["alembic_target_safe"] is True,
        "unexpected_database_revision": not (
            partial_pg["revision_class"]
            in (
                {
                    "0013_historical_evidence_index",
                    "0014_chronos_control_plane_v2",
                }
                if controlled
                else {"0013_historical_evidence_index"}
            )
            and _exact_int(partial_pg["revision_count"], 1)
        ),
        "bootstrap_authority_capabilities_insufficient": partial_pg[
            "bootstrap_authority_capabilities_proven"
        ]
        is False,
        "privileged_catalog_not_visible": partial_pg["privileged_catalog_visible"] is False,
        "existing_chronos_roles_unsafe": partial_pg["chronos_roles_clean"] is False,
        "existing_chronos_memberships_unsafe": partial_pg["chronos_memberships_clean"] is False,
        "existing_chronos_objects_unsafe": partial_pg["chronos_objects_clean"] is False,
    }
    return terminal_checks.get(gate, False)


def _valid_no_go_report_shape(
    report: Mapping[str, object],
    *,
    controlled: bool,
    effects: Mapping[str, object],
) -> bool:
    keys = set(report)
    optional: set[str] = set()
    if "dsn_security_profile" in report or "dsn_contract_verdict" in report:
        optional.update({"dsn_security_profile", "dsn_contract_verdict"})
    if "neon" in report:
        optional.add("neon")
    if "postgresql" in report:
        optional.add("postgresql")
    if controlled:
        if "lifecycle" in report:
            if keys != set(_CONTROLLED_NO_GO_KEYS) | optional:
                return False
        elif keys != set(_CONTROLLED_FALLBACK_KEYS):
            return False
    elif keys != set(_NO_GO_BASE_KEYS) | optional:
        return False

    reason = report.get("reason")
    gate = report.get("failed_gate")
    certainty = report.get("effect_counter_certainty")
    if (
        not isinstance(reason, str)
        or not isinstance(gate, str)
        or reason not in _NO_GO_REASON_VALUES
        or not _valid_no_go_gate(gate)
        or certainty
        not in {
            "OBSERVED",
            "CONSERVATIVE_UPPER_BOUNDS_ONLY",
            "OBSERVED_ZERO_LIVE_STEP_SKIPPED",
        }
    ):
        return False
    phase = _no_go_phase(reason, gate, controlled=controlled)
    if phase is None:
        return False
    if gate in _TECHNICAL_FAILURE_GATES and certainty not in {
        "CONSERVATIVE_UPPER_BOUNDS_ONLY",
        "OBSERVED_ZERO_LIVE_STEP_SKIPPED",
    }:
        return False
    if phase == _PHASE_TECHNICAL:
        skipped = certainty == "OBSERVED_ZERO_LIVE_STEP_SKIPPED"
        if (
            (gate != "artifact_guard_recovered_missing_or_invalid_report" and skipped)
            or "neon" in report
            or "postgresql" in report
            or "dsn_security_profile" in report
            or not _valid_technical_effects(
                effects,
                controlled=controlled,
                skipped=skipped,
            )
        ):
            return False
    elif certainty != "OBSERVED":
        return False
    elif phase == _PHASE_ALL_ZERO:
        if (
            "postgresql" in report
            or not _all_zero_effects(effects, controlled=controlled)
            or (
                "neon" in report
                and not (
                    reason == "DIRECT_ENDPOINT_NOT_PROVEN"
                    and gate == "libpq_environment_forbidden"
                    and _valid_libpq_no_go_evidence(report["neon"])
                )
            )
        ):
            return False
    elif phase == _PHASE_NEON:
        pre_get_without_audit = (
            gate == "configured_project_invalid"
            and not controlled
            and "neon" not in report
            and effects["neon_get_count"] == 0
        )
        allow_zero_get = gate in {
            "configured_project_invalid",
            "configured_organization_scope_mismatch",
        }
        if (
            "postgresql" in report
            or any(effects[key] != 0 for key in _POSTGRESQL_EFFECT_KEYS)
            or (controlled and effects["compute_wake_events"] != 0)
            or (
                not pre_get_without_audit
                and (
                    "neon" not in report
                    or not _valid_neon_phase_evidence(
                        report["neon"],
                        allow_zero_get=allow_zero_get,
                    )
                )
            )
        ):
            return False
        if "neon" in report:
            neon_phase = cast(dict[str, object], report["neon"])
            if not _valid_neon_evidence_shape_for_gate(gate, neon_phase):
                return False
            if not _valid_neon_terminal(gate, neon_phase):
                return False
    elif phase == _PHASE_POSTGRESQL:
        if (
            "postgresql" not in report
            or "neon" not in report
            or not _valid_neon_go(report["neon"], controlled=controlled)
        ):
            return False
    if "dsn_security_profile" in report:
        profile = report["dsn_security_profile"]
        if (
            not isinstance(profile, dict)
            or report.get("dsn_contract_verdict") != profile.get("contract_verdict")
            or not _valid_dsn_profile(profile, go=False)
        ):
            return False
    if "neon" in report and not _valid_neon_evidence(report["neon"]):
        return False
    if "neon" in report:
        neon_evidence = cast(dict[str, object], report["neon"])
        observed_gets = neon_evidence.get("api_get_count")
        if observed_gets is not None and effects["neon_get_count"] != observed_gets:
            return False
    elif certainty == "OBSERVED" and effects["neon_get_count"] != 0:
        return False
    if "postgresql" in report:
        postgresql = report["postgresql"]
        if not _valid_postgresql_no_go(postgresql):
            return False
        partial_pg = cast(dict[str, object], postgresql)
        connection_established = cast(bool, partial_pg["connection_established"])
        if effects["postgresql_connection_attempts"] != 1 or effects[
            "postgresql_connection_successes"
        ] != (1 if connection_established else 0):
            return False
        if not connection_established:
            if (
                any(
                    effects[key] != 0
                    for key in (
                        "sql_statement_count",
                        "sql_statement_completed_count",
                        "sql_read_attempt_count",
                        "sql_read_count",
                        "begin_read_only_attempted",
                        "begin_read_only_completed",
                        "rollback_attempted",
                        "rollback_completed",
                    )
                )
                or any(
                    partial_pg[key] is not None
                    for key in _POSTGRESQL_NO_GO_KEYS
                    - {
                        "connection_established",
                        "connection_close_completed",
                        "revision_class",
                        "inspection_failure_class",
                    }
                )
                or partial_pg["connection_close_completed"] is not None
            ):
                return False
        else:
            if not isinstance(partial_pg["connection_close_completed"], bool):
                return False
            version_num = partial_pg["postgresql_version_num"]
            major_verified = partial_pg["postgresql_major_verified"]
            if version_num is not None and major_verified is not (
                160_000 <= cast(int, version_num) < 170_000
            ):
                return False
        ledger_prefix = _valid_sql_ledger_prefix(effects)
        if ledger_prefix is None:
            return False
        main_attempted, main_completed = ledger_prefix
        if not _valid_postgresql_prefix_evidence(
            partial_pg,
            gate=gate,
            main_attempted=main_attempted,
            main_completed=main_completed,
            controlled=controlled,
        ) or not _valid_postgresql_terminal(
            reason,
            gate,
            partial_pg,
            effects,
            main_attempted=main_attempted,
            main_completed=main_completed,
            controlled=controlled,
        ):
            return False
    if not controlled:
        return True
    if "lifecycle" in report:
        source = report.get("source")
        if not isinstance(source, dict) or not _valid_no_go_github(
            report.get("github_actions"), source
        ):
            return False
    if (
        report.get("global_verdict") != "CHRONOS_NEON_CONTROLLED_WAKE_OR_PREFLIGHT_PARTIAL"
        or report.get("connection_attempt_count") != effects["postgresql_connection_attempts"]
        or report.get("compute_wake_events") != effects["compute_wake_events"]
        or report.get("compute_wake_certainty")
        not in {
            "OBSERVED",
            "OBSERVED_ZERO_LIVE_STEP_SKIPPED",
            "CONSERVATIVE_UPPER_BOUND_AFTER_SINGLE_CONNECTION_ATTEMPT",
            "CONSERVATIVE_UPPER_BOUND_AFTER_UNOBSERVED_EXIT",
        }
    ):
        return False
    if "lifecycle" not in report:
        return gate == "artifact_guard_recovered_missing_or_invalid_report"
    lifecycle = report["lifecycle"]
    if not _valid_no_go_lifecycle(lifecycle):
        return False
    typed_lifecycle = cast(dict[str, object], lifecycle)
    if phase in {_PHASE_ALL_ZERO, _PHASE_NEON} and (
        typed_lifecycle["connection_attempt_count"] != 0
        or typed_lifecycle["connection_succeeded"] is not False
        or typed_lifecycle["compute_wake_events"] != 0
    ):
        return False
    if phase == _PHASE_POSTGRESQL and (
        typed_lifecycle["connection_attempt_count"] != effects["postgresql_connection_attempts"]
        or typed_lifecycle["connection_succeeded"]
        is not (effects["postgresql_connection_successes"] == 1)
        or typed_lifecycle["compute_wake_events"] != effects["compute_wake_events"]
    ):
        return False
    if phase == _PHASE_TECHNICAL and (
        typed_lifecycle["connection_attempt_count"] != 1
        or typed_lifecycle["connection_succeeded"] is not True
        or typed_lifecycle["compute_wake_events"] != 1
    ):
        return False
    return (
        report.get("architecture_verdict") == "NEON_IDENTITY_AND_ENDPOINT_STATE_DECOUPLED"
        and report.get("wake_model") == "CONNECTION_TRIGGERED_READONLY_WAKE"
        and report.get("control_plane_start_api_used") is False
        and report.get("database_verdict") == "CHRONOS_NEON_DATABASE_READONLY_PREFLIGHT_NOT_PROVEN"
        and report.get("recovery_verdict")
        in {
            "PURCHASE_REQUIRED",
            "NEON_RECOVERY_BRANCH_CREATION_BLOCKED",
        }
        and isinstance(report.get("purchase_required"), bool)
        and (report.get("purchase_required") is True) == (reason == "PURCHASE_REQUIRED")
    )


def _valid_report(
    document: object,
    *,
    report_schema: str = REPORT_SCHEMA,
    live_outcome: str = "success",
    scan_sensitive_values: bool = True,
) -> bool:
    if not isinstance(document, dict):
        return False
    report = cast(dict[str, object], document)
    if not set(report) <= _TOP_LEVEL_KEYS:
        return False
    if report_schema not in {REPORT_SCHEMA, PURE_REPORT_SCHEMA}:
        return False
    controlled = report_schema == REPORT_SCHEMA
    if report.get("schema_version") != report_schema:
        return False
    if (
        not isinstance(report.get("observed_at"), str)
        or _UTC_TIMESTAMP.fullmatch(cast(str, report["observed_at"])) is None
    ):
        return False
    verdict = report.get("verdict")
    if verdict not in {GO_VERDICT, NO_GO_VERDICT}:
        return False
    go = verdict == GO_VERDICT
    if live_outcome != "success":
        return False
    if not _valid_source(report.get("source"), go=go):
        return False
    effects = report.get("effects")
    if not _valid_effects(effects, controlled=controlled):
        return False
    typed_effects = cast(dict[str, object], effects)
    if (
        controlled
        and "connection_attempt_count" in report
        and (
            report.get("connection_attempt_count")
            != typed_effects["postgresql_connection_attempts"]
        )
    ):
        return False
    if (
        controlled
        and "compute_wake_events" in report
        and (report.get("compute_wake_events") != typed_effects["compute_wake_events"])
    ):
        return False
    if not go:
        if not _valid_no_go_report_shape(
            report,
            controlled=controlled,
            effects=typed_effects,
        ):
            return False
    else:
        expected_keys = _CONTROLLED_GO_KEYS if controlled else _COMMON_GO_KEYS
        if set(report) != expected_keys:
            return False
        checks = report["checks"]
        if not isinstance(checks, dict) or set(checks) != _CHECK_KEYS:
            return False
        if any(value is not (key != "purchase_required") for key, value in checks.items()):
            return False
        postgresql = report["postgresql"]
        neon = report["neon"]
        github = report["github_actions"]
        lifecycle = report.get("lifecycle")
        if not _valid_postgresql_go(postgresql, controlled=controlled):
            return False
        if not _valid_neon_go(neon, controlled=controlled):
            return False
        if not _valid_environment_bindings(report, controlled=controlled):
            return False
        source = cast(dict[str, object], report["source"])
        if not _valid_github(github, source, controlled=controlled):
            return False
        if controlled and (
            not _valid_lifecycle(lifecycle)
            or not _valid_controlled_lifecycle_bindings(
                report,
                cast(dict[str, object], neon),
            )
        ):
            return False
        typed_postgresql = cast(dict[str, object], postgresql)
        typed_neon = cast(dict[str, object], neon)
        expected_effects: dict[str, int] = {
            "neon_get_count": cast(int, typed_neon["api_get_count"]),
            "postgresql_connection_attempts": 1,
            "postgresql_connection_successes": 1,
            "sql_statement_count": 18,
            "sql_statement_completed_count": 18,
            "sql_read_attempt_count": 15,
            "sql_read_count": 15,
            "begin_read_only_attempted": 1,
            "begin_read_only_completed": 1,
            "rollback_attempted": 1,
            "rollback_completed": 1,
        }
        if controlled:
            expected_effects["compute_wake_events"] = 1
        if any(
            not _exact_int(typed_effects[key], value) for key, value in expected_effects.items()
        ):
            return False
        if any(not _exact_int(typed_effects[key], 0) for key in _ZERO_EFFECTS):
            return False
        if not _valid_dsn_profile(report["dsn_security_profile"], go=True) or (
            report.get("dsn_contract_verdict")
            != "NEON_BOOTSTRAP_DSN_MATCHES_CURRENT_SECURE_CONTRACT"
        ):
            return False
        if not (
            report.get("reason") is None
            and report.get("failed_gate") is None
            and report.get("effect_counter_certainty") == "OBSERVED"
            and cast(int, typed_postgresql["postgresql_version_num"]) // 10000
            == typed_neon["postgresql_major"]
            and typed_postgresql["postgresql_version"]
            == str(typed_postgresql["postgresql_version_num"])
        ):
            return False
        if controlled and not (
            report.get("purchase_required") is False
            and report.get("architecture_verdict") == "NEON_IDENTITY_AND_ENDPOINT_STATE_DECOUPLED"
            and report.get("wake_model") == "CONNECTION_TRIGGERED_READONLY_WAKE"
            and report.get("control_plane_start_api_used") is False
            and report.get("database_verdict") == "CHRONOS_NEON_DATABASE_READONLY_PREFLIGHT_PROVEN"
            and report.get("global_verdict")
            == "CHRONOS_NEON_CONTROLLED_WAKE_AND_READONLY_PREFLIGHT_CLOSED"
            and report.get("bootstrap_authority_verdict")
            == "BOOTSTRAP_AUTHORITY_CAPABILITIES_PROVEN"
            and report.get("recovery_verdict") == "NEON_RECOVERY_BRANCH_CREATION_FEASIBLE"
            and _exact_int(report.get("connection_attempt_count"), 1)
            and _exact_int(report.get("compute_wake_events"), 1)
            and report.get("compute_wake_certainty")
            in {
                "OBSERVED_IDLE_TO_CONNECTED",
                "CONSERVATIVE_UPPER_BOUND_FROM_ACTIVE_SNAPSHOT",
            }
        ):
            return False
    sensitive_values = _sensitive_values()
    if scan_sensitive_values and (
        not _sensitive_values_are_scannable(sensitive_values)
        or _contains_raw_identity(report, sensitive_values=sensitive_values)
    ):
        return False
    return True


def _fallback_report(
    *,
    report_schema: str = REPORT_SCHEMA,
    live_outcome: str = "success",
) -> dict[str, object]:
    controlled = report_schema == REPORT_SCHEMA
    skipped = live_outcome == "skipped"
    upper = 0 if skipped else 1
    sql_upper = 0 if skipped else 25
    certainty = "OBSERVED_ZERO_LIVE_STEP_SKIPPED" if skipped else "CONSERVATIVE_UPPER_BOUNDS_ONLY"
    effects: dict[str, object] = {
        "neon_get_count": 0 if skipped else 25,
        "neon_mutations": 0,
        "production_sql_writes": 0,
        "recovery_branch_creations": 0,
        "role_creations": 0,
        "migration_0014": 0,
        "r2_operations": 0,
        "provider_calls": 0,
        "purchases": 0,
        "sensitive_values_exposed": 0,
        "postgresql_connection_attempts": upper,
        "postgresql_connection_successes": upper,
        "postgresql_retries": 0,
        "sql_statement_count": sql_upper,
        "sql_statement_completed_count": sql_upper,
        "sql_read_attempt_count": sql_upper,
        "sql_read_count": sql_upper,
        "sql_write_count": 0,
        "begin_read_only_attempted": upper,
        "begin_read_only_completed": upper,
        "rollback_attempted": upper,
        "rollback_completed": upper,
    }
    if controlled:
        effects["compute_wake_events"] = upper
    report: dict[str, object] = {
        "schema_version": report_schema,
        "observed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": _expected_source(),
        "verdict": NO_GO_VERDICT,
        "reason": "NEON_PROJECT_IDENTITY_AMBIGUOUS",
        "failed_gate": "artifact_guard_recovered_missing_or_invalid_report",
        "effect_counter_certainty": certainty,
        "effects": effects,
    }
    if controlled:
        report.update(
            {
                "global_verdict": "CHRONOS_NEON_CONTROLLED_WAKE_OR_PREFLIGHT_PARTIAL",
                "connection_attempt_count": upper,
                "compute_wake_events": upper,
                "compute_wake_certainty": (
                    "OBSERVED_ZERO_LIVE_STEP_SKIPPED"
                    if skipped
                    else "CONSERVATIVE_UPPER_BOUND_AFTER_UNOBSERVED_EXIT"
                ),
            }
        )
    return report


def ensure_artifact(
    path: Path,
    *,
    report_schema: str = REPORT_SCHEMA,
    live_outcome: str = "success",
) -> bool:
    """Return True when an existing report was valid, else atomically replace it."""

    try:
        with path.open("rb") as report_file:
            raw_payload = report_file.read(_MAX_REPORT_BYTES + 1)
        if len(raw_payload) > _MAX_REPORT_BYTES:
            raise ValueError("artifact_report_too_large")
        document = json.loads(
            raw_payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        RecursionError,
        _DuplicateJsonKey,
    ):
        document = None
    try:
        valid_existing_report = _valid_report(
            document,
            report_schema=report_schema,
            live_outcome=live_outcome,
        )
    except Exception:  # noqa: BLE001 - untrusted JSON validation must be total
        # Validation consumes an untrusted JSON tree. Any unexpected type or
        # nesting failure must recover to the closed fallback, never abort the
        # artifact step after a live attempt.
        valid_existing_report = False
    if valid_existing_report:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    fallback = _fallback_report(
        report_schema=report_schema,
        live_outcome=live_outcome,
    )
    if not _valid_report(
        fallback,
        report_schema=report_schema,
        live_outcome="success",
        scan_sensitive_values=False,
    ):
        raise RuntimeError("CHRONOS_ARTIFACT_FALLBACK_INVALID")
    payload = json.dumps(fallback, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--schema",
        choices=(REPORT_SCHEMA, PURE_REPORT_SCHEMA),
        default=REPORT_SCHEMA,
    )
    parser.add_argument(
        "--live-outcome",
        choices=("success", "failure", "cancelled", "skipped", "unknown"),
        default="unknown",
    )
    args = parser.parse_args()
    preserved = ensure_artifact(
        args.report,
        report_schema=args.schema,
        live_outcome=args.live_outcome,
    )
    print("CHRONOS_ARTIFACT_VALID" if preserved else "CHRONOS_ARTIFACT_RECOVERED")


if __name__ == "__main__":
    main()
