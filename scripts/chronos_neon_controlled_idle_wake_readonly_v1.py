"""One-shot Neon idle wake followed by a bounded read-only database preflight.

This authority is intentionally separate from the historical V4 preflight.  It
permits at most one direct PostgreSQL connection attempt after project, branch,
endpoint, DSN, GitHub quiescence, and Scale-to-Zero checks have all succeeded.
It never calls a mutating Neon API and never executes writable SQL.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import scripts.chronos_neon_pure_readonly_preflight_v4 as base
from robin.chronos_production import EXPECTED_REF, EXPECTED_REPOSITORY

REPORT_SCHEMA = "chronos-neon-controlled-idle-wake-readonly-v1"
WORKFLOW_FILE = "chronos-neon-controlled-idle-wake-readonly-v1.yml"
MAXIMUM_PREFLIGHT_WALL_CLOCK_SECONDS = 120
DEFAULT_SUSPEND_TIMEOUT_SECONDS = 300


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
        if self.endpoint_pre_wake_state == "idle":
            self.compute_wake_events = 1
            self.wake_verdict = "CONTROLLED_NEON_READONLY_WAKE_EXECUTED_ONCE"
        else:
            self.wake_verdict = "CONTROLLED_NEON_READONLY_WAKE_NOT_REQUIRED"


def _scale_to_zero_contract(neon: base.NeonObservation) -> tuple[str, int]:
    timeout = neon.suspend_timeout_seconds
    if timeout == -1:
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_return_to_idle_not_proven",
        )
    if timeout == 0:
        classification = "DEFAULT_SCALE_TO_ZERO"
        effective_timeout = DEFAULT_SUSPEND_TIMEOUT_SECONDS
    elif 60 <= timeout <= 604_800:
        classification = "FINITE_SCALE_TO_ZERO"
        effective_timeout = timeout
    else:
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_return_to_idle_not_proven",
        )
    if MAXIMUM_PREFLIGHT_WALL_CLOCK_SECONDS * 5 > effective_timeout * 2:
        raise base.PreflightNoGo(
            "COMPUTE_RETURN_TO_IDLE_NOT_PROVEN",
            "compute_wake_window_insufficient",
        )
    return classification, effective_timeout


def _validate_readonly_connection_contract(
    startup_options: str,
    sql_statements: tuple[str, ...],
) -> None:
    required = (
        "default_transaction_read_only=on",
        "statement_timeout=15000",
        "lock_timeout=3000",
    )
    if not all(option in startup_options for option in required):
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
    if (
        database.lifecycle_admin_can_login
        and (database.lifecycle_admin_superuser or database.lifecycle_admin_createrole)
    ):
        return "BOOTSTRAP_AUTHORITY_CAPABILITIES_PARTIAL"
    return "BOOTSTRAP_AUTHORITY_INSUFFICIENT"


def _recovery_verdict(
    *, purchase_required: bool, recovery_feasible: bool
) -> str:
    if purchase_required:
        return "PURCHASE_REQUIRED"
    if recovery_feasible:
        return "NEON_RECOVERY_BRANCH_CREATION_FEASIBLE"
    return "NEON_RECOVERY_BRANCH_CREATION_BLOCKED"


def _decision_gate(checks: base.GateChecks) -> str | None:
    ordered = (
        (not checks.project_identity_verified, "project_identity_not_proven"),
        (not checks.production_branch_verified, "production_branch_not_proven"),
        (not checks.direct_endpoint_verified, "direct_endpoint_not_proven"),
        (not checks.ssl_verified, "ssl_not_proven"),
        (not checks.expected_revision_verified, "unexpected_database_revision"),
        (not checks.bootstrap_authority_plausible, "bootstrap_authority_insufficient"),
        (checks.purchase_required, "purchase_required"),
        (not checks.recovery_branch_feasible, "recovery_branch_not_feasible"),
        (not checks.github_queue_empty, "github_actions_queue_not_empty"),
        (not checks.github_in_progress_empty, "github_actions_in_progress_not_empty"),
        (not checks.github_dispatch_unique, "exact_main_dispatch_not_unique"),
    )
    return next((gate for failed, gate in ordered if failed), None)


def _lifecycle_payload(audit: ConnectionWakeAudit) -> dict[str, object]:
    payload = asdict(audit)
    payload.update(
        {
            "maximum_preflight_wall_clock_seconds": (
                MAXIMUM_PREFLIGHT_WALL_CLOCK_SECONDS
            ),
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
) -> dict[str, object]:
    wake_events = audit.compute_wake_events
    wake_certainty = "OBSERVED"
    reason = error.reason
    gate = error.gate
    incomplete_attempt = (
        audit.connection_attempt_count == 1 and not audit.connection_succeeded
    )
    if incomplete_attempt:
        wake_events = 1 if audit.endpoint_pre_wake_state == "idle" else 0
        wake_certainty = (
            "CONSERVATIVE_UPPER_BOUND_AFTER_SINGLE_CONNECTION_ATTEMPT"
            if audit.endpoint_pre_wake_state == "idle"
            else "PRE_WAKE_STATE_ALREADY_ACTIVE"
        )
        if audit.endpoint_pre_wake_state == "idle":
            reason = "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
            gate = "single_connection_attempt_did_not_complete"
    report = base._no_go_report(
        reason,
        gate,
        dsn_security_profile=error.dsn_security_profile,
        sanitized_evidence=error.sanitized_evidence,
    )
    lifecycle = _lifecycle_payload(audit)
    lifecycle["compute_wake_events"] = wake_events
    if incomplete_attempt:
        lifecycle["wake_verdict"] = (
            "COMPUTE_WAKE_OR_CONNECTION_ATTEMPT_INDETERMINATE"
            if audit.endpoint_pre_wake_state == "idle"
            else "CONTROLLED_NEON_READONLY_WAKE_NOT_REQUIRED"
        )
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
        }
    )
    effects = report["effects"]
    if not isinstance(effects, dict):
        raise RuntimeError("INVALID_EFFECTS_REPORT")
    effects["compute_wake_events"] = wake_events
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
    postgresql["sql_read_count"] = max(0, database.sql_statement_count - 2)
    effects = report["effects"]
    if not isinstance(effects, dict):
        raise RuntimeError("INVALID_EFFECTS_REPORT")
    effects["compute_wake_events"] = audit.compute_wake_events
    return report


def run_preflight() -> dict[str, object]:
    audit = ConnectionWakeAudit()
    repository = base._required_context("GITHUB_REPOSITORY")
    git_ref = base._required_context("GITHUB_REF")
    main_sha = base._required_context("GITHUB_SHA")
    run_attempt = base._required_context("GITHUB_RUN_ATTEMPT")
    run_id = int(base._required_context("GITHUB_RUN_ID"))
    if repository != EXPECTED_REPOSITORY or git_ref != EXPECTED_REF:
        raise base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_source_not_exact_main"
        )
    if base._HEX_SHA.fullmatch(main_sha) is None:
        raise base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "github_main_sha_invalid"
        )
    if run_attempt != "1":
        raise base.PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "workflow_rerun_forbidden"
        )
    queue_count, in_progress_count, dispatch_count = base._github_actions_state(
        repository,
        run_id,
        main_sha,
        workflow_file=WORKFLOW_FILE,
    )
    if dispatch_count != 1:
        raise base.PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "exact_main_dispatch_not_unique"
        )
    if queue_count != 0 or in_progress_count != 0:
        raise base.PreflightNoGo(
            "RECOVERY_BRANCH_NOT_FEASIBLE", "github_actions_not_quiescent"
        )
    if os.getenv("NEON_PROJECT_ID", "").strip():
        raise base.PreflightNoGo(
            "NEON_PROJECT_IDENTITY_AMBIGUOUS", "neon_project_id_must_remain_absent"
        )
    api_key = base._required_context("NEON_API_KEY")
    database_url = base._required_context("NEON_BOOTSTRAP_DATABASE_URL")
    _, target = base._validated_psycopg_url(database_url)
    dsn_security_profile = base._target_dsn_security_profile(target)
    try:
        client = base.NeonReadOnlyClient(api_key)
        neon = base._resolve_neon_identity(client, target, allow_idle=True)
        audit.endpoint_pre_wake_state = neon.endpoint_state
        audit.identity_complete_before_wake = (
            neon.identity_verdict == "POSITIVE_PROJECT_OWNERSHIP_WITNESS_PROVEN"
            and neon.branch_default
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
        _validate_readonly_connection_contract(
            base.READONLY_STARTUP_OPTIONS,
            base.SQL_STATEMENTS,
        )
        try:
            database = base._inspect_database(
                database_url,
                before_connect=audit.before_connect,
                after_connect=audit.after_connect,
            )
        except base.PreflightNoGo as error:
            evidence = base._sanitized_neon(neon)
            evidence["lifecycle"] = _lifecycle_payload(audit)
            raise base.PreflightNoGo(
                error.reason,
                error.gate,
                dsn_security_profile=dsn_security_profile,
                sanitized_evidence=evidence,
            ) from None
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
            and database.statement_timeout_ms == base.EXPECTED_STATEMENT_TIMEOUT_MS
            and database.lock_timeout_ms == base.EXPECTED_LOCK_TIMEOUT_MS
            and database.sql_statement_count <= base.MAX_SQL_STATEMENTS
        )
        checks = base.GateChecks(
            secrets_present=True,
            project_identity_verified=True,
            production_branch_verified=neon.branch_default,
            direct_endpoint_verified=sql_safety,
            ssl_verified=database.ssl,
            expected_revision_verified=(
                database.revision_count == 1
                and database.revision == base.EXPECTED_REVISION
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
            )
        return _controlled_no_go_report(error, audit)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_preflight()
    except base.PreflightNoGo as error:
        report = _controlled_no_go_report(error, ConnectionWakeAudit())
    base._write_report(args.report, report)


if __name__ == "__main__":
    main()
