"""One-shot Neon idle wake followed by a bounded read-only database preflight.

This authority is intentionally separate from the historical V4 preflight.  It
permits at most one direct PostgreSQL connection attempt after project, branch,
endpoint, DSN, GitHub quiescence, and Scale-to-Zero checks have all succeeded.
It never calls a mutating Neon API and never executes writable SQL.
"""

from __future__ import annotations

import argparse
import math
import os
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import scripts.chronos_neon_pure_readonly_preflight_v4 as base
from robin.chronos_production import (
    DATA_TORRENT_ONE_SHOT_NOT_BEFORE,
    EXPECTED_BEFORE_REVISIONS,
    EXPECTED_REF,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    DirectPostgresTarget,
    validate_data_torrent_authority,
)

REPORT_SCHEMA = "chronos-neon-controlled-idle-wake-readonly-v1"
WORKFLOW_FILE = "chronos-neon-controlled-idle-wake-readonly-v1.yml"
MAXIMUM_PREFLIGHT_WALL_CLOCK_SECONDS = 120
DEFAULT_SUSPEND_TIMEOUT_SECONDS = 300
MINIMUM_SUSPEND_TIMEOUT_SECONDS = 300


@dataclass(slots=True)
class ConnectionWakeAudit:
    endpoint_pre_wake_state: str = "NOT_OBSERVED"
    scale_to_zero_classification: str = "UNPROVEN"
    configured_suspend_timeout_seconds: int | None = None
    effective_suspend_timeout_seconds: int | None = None
    identity_complete_before_wake: bool = False
    connection_attempt_count: int = 0
    connection_succeeded: bool = False
    compute_wake_events: int = 0
    compute_wake_events_observed: int = 0
    wake_verdict: str = "CONTROLLED_NEON_READONLY_WAKE_NOT_AUTHORIZED"

    def before_connect(self) -> None:
        if self.connection_attempt_count != 0:
            raise base.PreflightNoGo(
                "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE",
                "production_postgresql_connection_attempt_not_unique",
            )
        self.connection_attempt_count = 1

    def after_connect(self) -> None:
        self.connection_succeeded = True
        self.compute_wake_events = 1
        if self.endpoint_pre_wake_state == "idle":
            self.compute_wake_events_observed = 1
            self.wake_verdict = "CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE"
        else:
            self.wake_verdict = "COMPUTE_WAKE_UPPER_BOUND_ONE_FROM_ACTIVE_SNAPSHOT"


def _scale_to_zero_contract(neon: base.NeonObservation) -> tuple[str, int]:
    if (
        neon.autoscaling_limit_max_cu is None
        or not math.isfinite(neon.autoscaling_limit_max_cu)
        or neon.autoscaling_limit_max_cu < 0.25
    ):
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "autoscaling_limit_contract_invalid",
        )
    timeout = neon.suspend_timeout_seconds
    if timeout == -1:
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_return_to_idle_not_proven",
        )
    if timeout == 0:
        classification = "DEFAULT_SCALE_TO_ZERO"
        effective_timeout = DEFAULT_SUSPEND_TIMEOUT_SECONDS
    elif MINIMUM_SUSPEND_TIMEOUT_SECONDS <= timeout <= 604_800:
        classification = "FINITE_SCALE_TO_ZERO"
        effective_timeout = timeout
    else:
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_return_to_idle_not_proven",
        )
    return classification, effective_timeout


def _validate_readonly_connection_contract(
    startup_options: str,
    sql_statements: tuple[str, ...],
) -> None:
    expected = {
        "default_transaction_read_only": "on",
        "statement_timeout": "15000",
        "lock_timeout": "3000",
        "search_path": "pg_catalog",
    }
    try:
        tokens = shlex.split(startup_options, posix=True)
    except ValueError:
        tokens = []
    observed: dict[str, str] = {}
    if len(tokens) % 2 != 0:
        observed = {}
    else:
        for flag, assignment in zip(tokens[::2], tokens[1::2], strict=True):
            key, separator, value = assignment.partition("=")
            if flag != "-c" or separator != "=" or key in observed:
                observed = {}
                break
            observed[key] = value
    if observed != expected:
        raise base.PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "startup_options_required",
        )
    if not sql_statements or sql_statements[0] != "BEGIN READ ONLY":
        raise base.PreflightNoGo(
            "DIRECT_ENDPOINT_NOT_PROVEN",
            "first_sql_not_begin_read_only",
        )


def _bootstrap_authority_verdict(database: base.DatabaseObservation) -> str:
    if base._bootstrap_authority_plausible(database):
        return "BOOTSTRAP_AUTHORITY_CAPABILITIES_PROVEN"
    if database.lifecycle_admin_can_login and (
        database.lifecycle_admin_superuser or database.lifecycle_admin_createrole
    ):
        return "BOOTSTRAP_AUTHORITY_CAPABILITIES_PARTIAL"
    return "BOOTSTRAP_AUTHORITY_INSUFFICIENT"


def _recovery_verdict(*, purchase_required: bool, recovery_feasible: bool) -> str:
    if purchase_required:
        return "PURCHASE_REQUIRED"
    if recovery_feasible:
        return "NEON_RECOVERY_BRANCH_CREATION_FEASIBLE"
    return "NEON_RECOVERY_BRANCH_CREATION_BLOCKED"


def _database_target_proven(
    database: base.DatabaseObservation,
    target: DirectPostgresTarget,
    expected_postgresql_major: int,
) -> bool:
    return (
        database.database_name == target.database
        and database.session_user == target.username
        and database.current_user == database.session_user
        and database.postgresql_version_num // 10000 == expected_postgresql_major
    )


def _decision_gate(checks: base.GateChecks) -> str | None:
    return base.failed_gate(checks)


def _lifecycle_payload(audit: ConnectionWakeAudit) -> dict[str, object]:
    payload = asdict(audit)
    payload.update(
        {
            "maximum_preflight_wall_clock_seconds": (MAXIMUM_PREFLIGHT_WALL_CLOCK_SECONDS),
            "post_preflight_endpoint_state": "NOT_POLLED",
            "automatic_return_to_idle": (
                "CONFIGURATION_PROVEN_NOT_WAITED_FOR"
                if audit.scale_to_zero_classification
                in {"FINITE_SCALE_TO_ZERO", "DEFAULT_SCALE_TO_ZERO"}
                else "UNPROVEN"
            ),
        }
    )
    return payload


def _controlled_no_go_report(
    error: base.PreflightNoGo,
    audit: ConnectionWakeAudit,
    *,
    authority_window_dispatch_count: int = 0,
    queue_count: int = 100,
    in_progress_count: int = 100,
    dispatch_count: int = 100,
) -> dict[str, object]:
    wake_events = audit.compute_wake_events
    wake_certainty = "OBSERVED"
    reason = error.reason
    gate = error.gate
    incomplete_attempt = audit.connection_attempt_count == 1 and not audit.connection_succeeded
    if incomplete_attempt:
        wake_events = 1
        wake_certainty = "CONSERVATIVE_UPPER_BOUND_AFTER_SINGLE_CONNECTION_ATTEMPT"
        reason = "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
        gate = "single_connection_attempt_did_not_complete"
    report = base._no_go_report(
        reason,
        gate,
        dsn_security_profile=error.dsn_security_profile,
        sanitized_evidence=error.sanitized_evidence,
        sanitized_postgresql_evidence=error.sanitized_postgresql_evidence,
    )
    lifecycle = _lifecycle_payload(audit)
    lifecycle["compute_wake_events"] = wake_events
    if incomplete_attempt:
        lifecycle["wake_verdict"] = "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
    report.update(
        {
            "schema_version": REPORT_SCHEMA,
            "architecture_verdict": "NEON_IDENTITY_AND_ENDPOINT_STATE_DECOUPLED",
            "wake_model": "CONNECTION_TRIGGERED_READONLY_WAKE",
            "control_plane_start_api_used": False,
            "database_verdict": "CHRONOS_NEON_DATABASE_READONLY_PREFLIGHT_NOT_PROVEN",
            "global_verdict": "CHRONOS_NEON_CONTROLLED_WAKE_OR_PREFLIGHT_PARTIAL",
            "lifecycle": lifecycle,
            "connection_attempt_count": audit.connection_attempt_count,
            "compute_wake_events": wake_events,
            "compute_wake_certainty": wake_certainty,
            "recovery_verdict": (
                "PURCHASE_REQUIRED"
                if reason == "PURCHASE_REQUIRED"
                else "NEON_RECOVERY_BRANCH_CREATION_BLOCKED"
            ),
            "purchase_required": reason == "PURCHASE_REQUIRED",
        }
    )
    effects = report["effects"]
    if not isinstance(effects, dict):
        raise RuntimeError("INVALID_EFFECTS_REPORT")
    effects["compute_wake_events"] = wake_events
    effects["postgresql_connection_attempts"] = audit.connection_attempt_count
    effects["postgresql_retries"] = 0
    for key, value in error.effect_counts.items():
        effects[key] = value
    raw_run_id = os.getenv("GITHUB_RUN_ID", "0")
    current_run = int(raw_run_id) if raw_run_id.isascii() and raw_run_id.isdigit() else 0
    if current_run == 0:
        source = report.get("source")
        if isinstance(source, dict):
            source["run_id"] = "UNKNOWN"
    report["github_actions"] = {
        "queued": queue_count,
        "in_progress": in_progress_count,
        "current_run_excluded": current_run,
        "exact_main_dispatch_count": dispatch_count,
        "authority_window_dispatch_count": authority_window_dispatch_count,
    }
    return report


def _controlled_success_report(
    *,
    checks: base.GateChecks,
    decision: base.GateDecision,
    neon: base.NeonObservation,
    database: base.DatabaseObservation,
    queue_count: int,
    in_progress_count: int,
    dispatch_count: int,
    authority_window_dispatch_count: int,
    dsn_security_profile: Mapping[str, object],
    audit: ConnectionWakeAudit,
    purchase_required: bool,
    recovery_feasible: bool,
) -> dict[str, object]:
    report = base._report(
        checks=checks,
        decision=decision,
        neon=neon,
        database=database,
        queue_count=queue_count,
        in_progress_count=in_progress_count,
        dispatch_count=dispatch_count,
        dsn_security_profile=dsn_security_profile,
    )
    report.update(
        {
            "schema_version": REPORT_SCHEMA,
            "architecture_verdict": "NEON_IDENTITY_AND_ENDPOINT_STATE_DECOUPLED",
            "wake_model": "CONNECTION_TRIGGERED_READONLY_WAKE",
            "control_plane_start_api_used": False,
            "database_verdict": (
                "CHRONOS_NEON_DATABASE_READONLY_PREFLIGHT_PROVEN"
                if decision.verdict == base.GO_VERDICT
                else "CHRONOS_NEON_DATABASE_READONLY_PREFLIGHT_NOT_PROVEN"
            ),
            "global_verdict": (
                "CHRONOS_NEON_CONTROLLED_WAKE_AND_READONLY_PREFLIGHT_CLOSED"
                if decision.verdict == base.GO_VERDICT
                else "CHRONOS_NEON_CONTROLLED_WAKE_OR_PREFLIGHT_PARTIAL"
            ),
            "failed_gate": _decision_gate(checks),
            "lifecycle": _lifecycle_payload(audit),
            "connection_attempt_count": audit.connection_attempt_count,
            "compute_wake_events": audit.compute_wake_events,
            "compute_wake_certainty": (
                "OBSERVED_IDLE_TO_CONNECTED"
                if audit.compute_wake_events_observed == 1
                else "CONSERVATIVE_UPPER_BOUND_FROM_ACTIVE_SNAPSHOT"
            ),
            "bootstrap_authority_verdict": _bootstrap_authority_verdict(database),
            "recovery_verdict": _recovery_verdict(
                purchase_required=purchase_required,
                recovery_feasible=recovery_feasible,
            ),
            "purchase_required": purchase_required,
        }
    )
    postgresql = report["postgresql"]
    if not isinstance(postgresql, dict):
        raise RuntimeError("INVALID_POSTGRESQL_REPORT")
    postgresql["connection_attempt_count"] = audit.connection_attempt_count
    postgresql["sql_read_count"] = database.sql_read_count
    effects = report["effects"]
    if not isinstance(effects, dict):
        raise RuntimeError("INVALID_EFFECTS_REPORT")
    effects["compute_wake_events"] = audit.compute_wake_events
    effects["postgresql_connection_attempts"] = audit.connection_attempt_count
    effects["postgresql_retries"] = 0
    github = report["github_actions"]
    if not isinstance(github, dict):
        raise RuntimeError("INVALID_GITHUB_REPORT")
    github["authority_window_dispatch_count"] = authority_window_dispatch_count
    return report


def _conservative_technical_failure_report(gate: str) -> dict[str, object]:
    """Represent an unobserved late failure without asserting false zero effects."""

    audit = ConnectionWakeAudit(
        connection_attempt_count=1,
        connection_succeeded=True,
        compute_wake_events=1,
    )
    report = _controlled_no_go_report(
        base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS",
            gate,
            effect_counts={
                "neon_get_count": base.MAX_NEON_GETS,
                "postgresql_connection_attempts": 1,
                "postgresql_connection_successes": 1,
                "postgresql_retries": 0,
                "sql_statement_count": base.MAX_SQL_STATEMENTS,
                "sql_statement_completed_count": base.MAX_SQL_STATEMENTS,
                "sql_read_attempt_count": base.MAX_SQL_STATEMENTS,
                "sql_read_count": base.MAX_SQL_STATEMENTS,
                "sql_write_count": 0,
                "begin_read_only_attempted": 1,
                "begin_read_only_completed": 1,
                "rollback_attempted": 1,
                "rollback_completed": 1,
            },
        ),
        audit,
    )
    report["effect_counter_certainty"] = "CONSERVATIVE_UPPER_BOUNDS_ONLY"
    report["compute_wake_certainty"] = "CONSERVATIVE_UPPER_BOUND_AFTER_UNOBSERVED_EXIT"
    lifecycle = report["lifecycle"]
    if isinstance(lifecycle, dict):
        lifecycle["wake_verdict"] = "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
    return report


def run_preflight() -> dict[str, object]:
    audit = ConnectionWakeAudit()
    authority_window_dispatch_count = 0
    queue_count = 100
    in_progress_count = 100
    dispatch_count = 100
    try:
        validate_data_torrent_authority()
    except ChronosProductionError:
        raise base.PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "mission_authority_inactive"
        ) from None
    repository = base._required_context("GITHUB_REPOSITORY")
    git_ref = base._required_context("GITHUB_REF")
    main_sha = base._required_context("GITHUB_SHA")
    run_attempt = base._required_context("GITHUB_RUN_ATTEMPT")
    run_id = base._positive_integer_context("GITHUB_RUN_ID")
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise base.PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_source_not_exact_main")
    if base._HEX_SHA.fullmatch(main_sha) is None:
        raise base.PreflightNoGo("NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_sha_invalid")
    if run_attempt != "1":
        raise base.PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "workflow_rerun_forbidden")
    queue_count, in_progress_count, dispatch_count = base._github_actions_state(
        repository,
        run_id,
        main_sha,
        workflow_file=WORKFLOW_FILE,
    )
    if dispatch_count != 1:
        raise base.PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "exact_main_dispatch_not_unique")
    if queue_count != 0 or in_progress_count != 0:
        raise base.PreflightNoGo("RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_not_quiescent")
    authority_window_dispatch_count = base._github_authority_window_dispatch_count(
        repository,
        run_id,
        main_sha,
        workflow_file=WORKFLOW_FILE,
        not_before=DATA_TORRENT_ONE_SHOT_NOT_BEFORE,
    )
    if authority_window_dispatch_count != 1:
        raise base.PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "authority_window_dispatch_not_unique"
        )
    if os.getenv("NEON_PROJECT_ID", "").strip():
        raise base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_project_id_must_remain_absent"
        )
    api_key = base._required_sensitive_context("NEON_API_KEY")
    database_url = base._required_context("NEON_BOOTSTRAP_DATABASE_URL")
    _, target = base._validated_psycopg_url(database_url)
    dsn_security_profile = base._target_dsn_security_profile(target)
    try:
        base._reject_libpq_environment()
        client = base.NeonReadOnlyClient(api_key)
        neon = base._resolve_neon_identity(client, target, allow_idle=True)
        try:
            audit.endpoint_pre_wake_state = neon.endpoint_state
            audit.identity_complete_before_wake = (
                neon.identity_verdict == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
                and neon.branch_default
                and neon.project_inventory_exhaustive
            )
            classification, effective_timeout = _scale_to_zero_contract(neon)
            audit.scale_to_zero_classification = classification
            audit.configured_suspend_timeout_seconds = neon.suspend_timeout_seconds
            audit.effective_suspend_timeout_seconds = effective_timeout
            if not audit.identity_complete_before_wake:
                raise base.PreflightNoGo(
                    "NEON_PROJECT_IDENTITY_AMBIGUOUS",
                    "identity_incomplete_before_connection",
                )
            if not neon.branch_capacity_proven:
                raise base.PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE", "branch_capacity_ambiguous"
                )
            if neon.owner_branch_count + 1 > neon.branch_limit:
                raise base.PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE", "branch_capacity_exhausted"
                )
            purchase_required = not neon.bill_free_branch_capacity_proven
            if purchase_required:
                raise base.PreflightNoGo("PURCHASE_REQUIRED", "purchase_required")
            recovery_feasible = (
                neon.history_retention_seconds > 0
                and neon.branch_id != ""
                and neon.branch_state == "ready"
            )
            if not recovery_feasible:
                raise base.PreflightNoGo(
                    "RECOVERY_BRANCH_NOT_FEASIBLE", "recovery_branch_not_feasible"
                )
            _validate_readonly_connection_contract(
                base.READONLY_STARTUP_OPTIONS,
                base.SQL_STATEMENTS,
            )
        except base.PreflightNoGo as error:
            raise base.PreflightNoGo(
                error.reason,
                error.gate,
                dsn_security_profile=dsn_security_profile,
                sanitized_evidence=error.sanitized_evidence or base._sanitized_neon(neon),
                sanitized_postgresql_evidence=(error.sanitized_postgresql_evidence),
                effect_counts=error.effect_counts,
            ) from None
        inspection_audit = base.DatabaseInspectionAudit()
        try:
            database = base._inspect_database(
                database_url,
                expected_postgresql_major=neon.postgresql_major,
                expected_revisions=EXPECTED_BEFORE_REVISIONS,
                before_connect=audit.before_connect,
                after_connect=audit.after_connect,
                inspection_audit=inspection_audit,
            )
        except base.PreflightNoGo as error:
            evidence = base._sanitized_neon(neon)
            raise base.PreflightNoGo(
                error.reason,
                error.gate,
                dsn_security_profile=dsn_security_profile,
                sanitized_evidence=evidence,
                sanitized_postgresql_evidence=(error.sanitized_postgresql_evidence),
                effect_counts=error.effect_counts,
            ) from None
        sql_safety = (
            database.default_transaction_read_only
            and database.transaction_read_only
            and database.statement_timeout_ms == base.EXPECTED_STATEMENT_TIMEOUT_MS
            and database.lock_timeout_ms == base.EXPECTED_LOCK_TIMEOUT_MS
            and database.sql_statement_count <= base.MAX_SQL_STATEMENTS
            and _database_target_proven(
                database,
                target,
                neon.postgresql_major,
            )
        )
        checks = base.GateChecks(
            secrets_present=True,
            project_identity_verified=True,
            production_branch_verified=neon.branch_default,
            direct_endpoint_verified=sql_safety,
            ssl_verified=database.ssl,
            expected_revision_verified=(
                database.revision_count == 1 and database.revision in EXPECTED_BEFORE_REVISIONS
            ),
            bootstrap_authority_plausible=base._bootstrap_authority_plausible(database),
            recovery_branch_feasible=recovery_feasible,
            purchase_required=purchase_required,
            github_queue_empty=queue_count == 0,
            github_in_progress_empty=in_progress_count == 0,
            github_dispatch_unique=dispatch_count == 1,
        )
        decision = base.evaluate_checks(checks)
        return _controlled_success_report(
            checks=checks,
            decision=decision,
            neon=neon,
            database=database,
            queue_count=queue_count,
            in_progress_count=in_progress_count,
            dispatch_count=dispatch_count,
            authority_window_dispatch_count=authority_window_dispatch_count,
            dsn_security_profile=dsn_security_profile,
            audit=audit,
            purchase_required=purchase_required,
            recovery_feasible=recovery_feasible,
        )
    except base.PreflightNoGo as error:
        if error.dsn_security_profile is None:
            error = base.PreflightNoGo(
                error.reason,
                error.gate,
                dsn_security_profile=dsn_security_profile,
                sanitized_evidence=error.sanitized_evidence,
                sanitized_postgresql_evidence=(error.sanitized_postgresql_evidence),
                effect_counts=error.effect_counts,
            )
        return _controlled_no_go_report(
            error,
            audit,
            authority_window_dispatch_count=authority_window_dispatch_count,
            queue_count=queue_count,
            in_progress_count=in_progress_count,
            dispatch_count=dispatch_count,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_preflight()
    except base.PreflightNoGo as error:
        report = _controlled_no_go_report(error, ConnectionWakeAudit())
    except Exception:
        report = _conservative_technical_failure_report("unexpected_sanitized_failure")
    try:
        base._write_report(args.report, report)
    except Exception:
        fallback = _conservative_technical_failure_report("report_serialization_or_write_failure")
        base._write_report(args.report, fallback)
        report = fallback
    print(str(report["verdict"]))


if __name__ == "__main__":
    main()
