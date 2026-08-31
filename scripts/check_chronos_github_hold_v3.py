"""Verify the live GitHub workflow hold without exposing token material."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess  # nosec B404 - fixed Python child bounds one HTTP GET.
import sys
import time
from pathlib import Path
from typing import Any, cast

import requests

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_START_SHA,
    EXPECTED_REPOSITORY,
    ChronosProductionError,
    require_sha,
)

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PROVIDER_BRANCH = "codex/jalon-12-prospective-deep-data-observatory"
LEGACY_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
SAFE_CI_WORKFLOW_PATH = ".github/workflows/ci-safe-v2.yml"
PRODUCTION_ENVIRONMENT = "chronos-control-plane-production"
AUTHORIZED_PROTECTED_WORKFLOWS = frozenset(
    {
        SAFE_CI_WORKFLOW_PATH,
        ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml",
        ".github/workflows/chronos-controlled-go-durable-seal-v1.yml",
        ".github/workflows/chronos-production-bootstrap-v3.yml",
        ".github/workflows/data-torrent-live-v1.yml",
    }
)
RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS = frozenset(
    {
        ".github/workflows/chronos-neon-branch-identity-v2.yml",
        ".github/workflows/chronos-identity-seal-v2.yml",
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        ".github/workflows/data-torrent-live-v2.yml",
    }
)
RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS = frozenset(
    {
        ".github/workflows/chronos-neon-controlled-idle-wake-readonly-v1.yml",
        ".github/workflows/chronos-controlled-go-durable-seal-v1.yml",
        ".github/workflows/chronos-production-bootstrap-v3.yml",
        ".github/workflows/data-torrent-live-v1.yml",
        ".github/workflows/chronos-neon-branch-identity-v2.yml",
        ".github/workflows/chronos-identity-seal-v2.yml",
        ".github/workflows/chronos-production-bootstrap-v4.yml",
        ".github/workflows/data-torrent-live-v2.yml",
    }
)
RISK_MARKERS = (
    "secrets.DATABASE_URL",
    "secrets.NEON_",
    "secrets.CHRONOS_",
    "secrets.R2_",
    "secrets.API_FOOTBALL_KEY",
    "secrets.ODDS_API_KEY",
    "schedule:",
    "workflow_run:",
    "repository_dispatch:",
)
_MAX_GITHUB_BODY_BYTES = 2 * 1024 * 1024
GITHUB_GET_TOTAL_TIMEOUT_SECONDS = 6.0


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_CONTEXT:{name}")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON key")
        document[key] = value
    return document


def _effect_timeout(
    effect_deadline_epoch: float | None, *, maximum: float
) -> float:
    if effect_deadline_epoch is None:
        return maximum
    if (
        isinstance(effect_deadline_epoch, bool)
        or not isinstance(effect_deadline_epoch, (int, float))
        or not math.isfinite(float(effect_deadline_epoch))
    ):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_EFFECT_DEADLINE_INVALID")
    remaining = float(effect_deadline_epoch) - time.time()
    if remaining <= 0:
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_EFFECT_DEADLINE_EXCEEDED")
    return min(maximum, remaining)


def _github_get_direct(
    path: str,
    token: str,
    *,
    effect_deadline_epoch: float | None = None,
) -> dict[str, Any]:
    """Perform one GET in the disposable bounded child process only."""

    session = requests.Session()
    session.trust_env = False
    response: requests.Response | None = None
    try:
        remaining = _effect_timeout(effect_deadline_epoch, maximum=4.0)
        response = session.get(
            "https://api.github.com" + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
            },
            timeout=(min(2.0, remaining), min(2.0, remaining)),
            allow_redirects=False,
            stream=True,
        )
        if 300 <= response.status_code < 400:
            raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_REDIRECT_REFUSED")
        if not 200 <= response.status_code < 300:
            raise ChronosProductionError(f"CHRONOS_GITHUB_HOLD_API_HTTP_{response.status_code}")
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID") from None
            if declared_length < 0 or declared_length > _MAX_GITHUB_BODY_BYTES:
                raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_RESPONSE_TOO_LARGE")
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not isinstance(chunk, bytes):
                raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
            body.extend(chunk)
            if len(body) > _MAX_GITHUB_BODY_BYTES:
                raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_RESPONSE_TOO_LARGE")
    except requests.RequestException:
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_UNAVAILABLE") from None
    finally:
        if response is not None:
            response.close()
        session.close()
    try:
        document = json.loads(bytes(body), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID") from None
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
    return cast(dict[str, Any], document)


def _github_get(
    path: str,
    token: str,
    *,
    effect_deadline_epoch: float | None = None,
) -> dict[str, Any]:
    """Bound launch, DNS, TLS, headers, and body by killing a disposable child."""

    if (
        not path.startswith("/repos/")
        or any(character in path for character in ("\r", "\n", "\x00"))
        or not token
        or len(token.encode("utf-8")) > 2_048
    ):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
    timeout = _effect_timeout(
        effect_deadline_epoch,
        maximum=GITHUB_GET_TOTAL_TIMEOUT_SECONDS,
    )
    try:
        completed = subprocess.run(  # nosec B603 - fixed interpreter/script and bounded path.
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--bounded-get-child",
                path,
                "" if effect_deadline_epoch is None else repr(float(effect_deadline_epoch)),
            ],
            input=token.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_UNAVAILABLE") from None
    if not completed.stdout or len(completed.stdout) > _MAX_GITHUB_BODY_BYTES:
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
    try:
        document = json.loads(completed.stdout, object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, ValueError):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID") from None
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
    return cast(dict[str, Any], document)


def _recovery_v2_workflow_quarantine(
    workflows: list[dict[str, Any]],
    *,
    allow_new_workflows_active: bool = False,
) -> list[dict[str, Any]]:
    observed: dict[str, dict[str, Any]] = {}
    for workflow in workflows:
        path = str(workflow.get("path", "")).removeprefix("/")
        if path not in RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS:
            continue
        if path in observed:
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_WORKFLOW_INVENTORY_INVALID")
        observed[path] = workflow
    if set(observed) != RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS:
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_WORKFLOW_INVENTORY_INVALID")
    for path, item in observed.items():
        allowed_states = (
            {"active", "disabled_manually"}
            if allow_new_workflows_active and path in RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS
            else {"disabled_manually"}
        )
        if (
            item.get("state") not in allowed_states
            or type(item.get("id")) is not int
            or int(item["id"]) <= 0
        ):
            raise ChronosProductionError("CHRONOS_RECOVERY_V2_WORKFLOW_NOT_QUIESCENT")
    return [
        {
            "workflow_id": int(observed[path]["id"]),
            "workflow_path": path,
            "state": str(observed[path]["state"]),
        }
        for path in sorted(observed)
    ]


def verify_no_concurrent_runs(
    *,
    repository: str,
    token: str,
    current_run_id: int = 0,
    effect_deadline_epoch: float | None = None,
) -> dict[str, int]:
    """Use five bounded inventories to refuse every other nonterminal run."""

    if repository != EXPECTED_REPOSITORY or type(current_run_id) is not int or current_run_id < 0:
        raise ChronosProductionError("CHRONOS_GITHUB_RUN_ID_INVALID")
    statuses = ("requested", "waiting", "pending", "queued", "in_progress")
    active_runs: list[dict[str, Any]] = []
    nonterminal_run_counts = {status: 0 for status in statuses}
    observed_run_ids: set[int] = set()
    for status in statuses:
        runs_document = _github_get(
            f"/repos/{repository}/actions/runs?status={status}&per_page=100",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        raw_runs = runs_document.get("workflow_runs", [])
        if (
            not isinstance(raw_runs, list)
            or type(runs_document.get("total_count")) is not int
            or runs_document["total_count"] != len(raw_runs)
            or len(raw_runs) > 100
            or any(not isinstance(item, dict) for item in raw_runs)
        ):
            raise ChronosProductionError("CHRONOS_GITHUB_RUNS_INVENTORY_TRUNCATED")
        for item in raw_runs:
            run_id = item.get("id")
            if (
                type(run_id) is not int
                or run_id <= 0
                or item.get("status") != status
                or run_id in observed_run_ids
            ):
                raise ChronosProductionError("CHRONOS_GITHUB_RUNS_INVENTORY_INVALID")
            observed_run_ids.add(run_id)
            if run_id != current_run_id:
                active_runs.append(item)
                nonterminal_run_counts[status] += 1
    if active_runs:
        raise ChronosProductionError("CHRONOS_CONCURRENT_RUN_PRESENT")
    return nonterminal_run_counts


def _require_exact_recovery_v2_final_ci_inventory(
    raw_ci_runs: list[Any],
    *,
    expected_ci_sha: str,
    expected_run_id: int | None,
) -> None:
    if (
        len(raw_ci_runs) != 1
        or expected_run_id is None
        or not isinstance(raw_ci_runs[0], dict)
        or raw_ci_runs[0].get("id") != expected_run_id
        or raw_ci_runs[0].get("head_sha") != expected_ci_sha
        or raw_ci_runs[0].get("head_branch") != "main"
        or raw_ci_runs[0].get("event") != "push"
        or raw_ci_runs[0].get("status") != "completed"
        or raw_ci_runs[0].get("conclusion") != "success"
        or raw_ci_runs[0].get("run_attempt") != 1
    ):
        raise ChronosProductionError("CHRONOS_POST_MERGE_CI_INVALID")


def verify_hold(
    *,
    required_successful_ci_sha: str | None = None,
    recovery_v2: bool = False,
    repository_override: str | None = None,
    token_override: str | None = None,
    current_run_id: int | None = None,
    recovery_v2_quarantine_precondition: bool = False,
    recovery_v2_provider_precondition: bool = False,
    expected_successful_ci_run_id: int | None = None,
    expected_legacy_branch_sha: str | None = None,
    require_recovery_v2_final_witness: bool = False,
    effect_deadline_epoch: float | None = None,
) -> dict[str, Any]:
    repository = repository_override or _required("GITHUB_REPOSITORY")
    if repository != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    token = token_override or _required("GITHUB_TOKEN")
    if current_run_id is None:
        raw_run_id = _required("GITHUB_RUN_ID")
        if re.fullmatch(r"[1-9][0-9]{0,17}", raw_run_id) is None:
            raise ChronosProductionError("CHRONOS_GITHUB_RUN_ID_INVALID")
        run_id = int(raw_run_id)
    else:
        run_id = current_run_id
    if type(run_id) is not int or run_id < 0:
        raise ChronosProductionError("CHRONOS_GITHUB_RUN_ID_INVALID")
    if (
        (recovery_v2_quarantine_precondition or recovery_v2_provider_precondition)
        and not recovery_v2
    ) or (recovery_v2_quarantine_precondition and recovery_v2_provider_precondition):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_QUARANTINE_MODE_INVALID")
    if (
        (expected_successful_ci_run_id is not None or expected_legacy_branch_sha is not None)
        and not recovery_v2
    ) or (require_recovery_v2_final_witness and not recovery_v2):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_FINAL_HOLD_MODE_INVALID")
    if expected_successful_ci_run_id is not None and (
        type(expected_successful_ci_run_id) is not int or expected_successful_ci_run_id <= 0
    ):
        raise ChronosProductionError("CHRONOS_RECOVERY_V2_FINAL_HOLD_MODE_INVALID")
    workflows_document = _github_get(
        f"/repos/{repository}/actions/workflows?per_page=100",
        token,
        effect_deadline_epoch=effect_deadline_epoch,
    )
    raw_workflows = workflows_document.get("workflows", [])
    if not isinstance(raw_workflows, list):
        raise ChronosProductionError("CHRONOS_GITHUB_WORKFLOWS_INVALID")
    if recovery_v2 and (
        type(workflows_document.get("total_count")) is not int
        or workflows_document["total_count"] != len(raw_workflows)
        or len(raw_workflows) > 100
        or any(not isinstance(item, dict) for item in raw_workflows)
    ):
        raise ChronosProductionError("CHRONOS_GITHUB_WORKFLOWS_INVENTORY_TRUNCATED")
    workflows = [item for item in raw_workflows if isinstance(item, dict)]
    recovery_v2_quarantine = (
        _recovery_v2_workflow_quarantine(
            workflows,
            allow_new_workflows_active=(
                recovery_v2_quarantine_precondition or recovery_v2_provider_precondition
            ),
        )
        if recovery_v2
        else None
    )
    legacy_ci_workflow = _github_get(
        f"/repos/{repository}/actions/workflows/ci.yml",
        token,
        effect_deadline_epoch=effect_deadline_epoch,
    )
    if (
        str(legacy_ci_workflow.get("path", "")).removeprefix("/") != LEGACY_CI_WORKFLOW_PATH
        or legacy_ci_workflow.get("state") != "disabled_manually"
        or type(legacy_ci_workflow.get("id")) is not int
        or int(legacy_ci_workflow["id"]) <= 0
    ):
        raise ChronosProductionError("CHRONOS_LEGACY_CI_NOT_QUARANTINED")
    environment = _github_get(
        f"/repos/{repository}/environments/{PRODUCTION_ENVIRONMENT}",
        token,
        effect_deadline_epoch=effect_deadline_epoch,
    )
    deployment_policy = environment.get("deployment_branch_policy")
    environment_policies = _github_get(
        f"/repos/{repository}/environments/{PRODUCTION_ENVIRONMENT}/deployment-branch-policies",
        token,
        effect_deadline_epoch=effect_deadline_epoch,
    )
    branch_policies = environment_policies.get("branch_policies")
    if (
        environment.get("name") != PRODUCTION_ENVIRONMENT
        or environment.get("can_admins_bypass") is not False
        or deployment_policy != {"protected_branches": False, "custom_branch_policies": True}
        or environment_policies.get("total_count") != 1
        or not isinstance(branch_policies, list)
        or len(branch_policies) != 1
        or not isinstance(branch_policies[0], dict)
        or branch_policies[0].get("name") != "main"
        or branch_policies[0].get("type") != "branch"
    ):
        raise ChronosProductionError("CHRONOS_PRODUCTION_ENVIRONMENT_POLICY_INVALID")
    active = [item for item in workflows if item.get("state") == "active"]
    disabled = [item for item in workflows if item.get("state") != "active"]
    unauthorized: list[dict[str, Any]] = []
    for workflow in active:
        raw_path = str(workflow.get("path", ""))
        path = raw_path.removeprefix("/")
        if (
            recovery_v2_quarantine_precondition or recovery_v2_provider_precondition
        ) and path in RECOVERY_V2_NEW_PRODUCTION_WORKFLOWS:
            continue
        if path in AUTHORIZED_PROTECTED_WORKFLOWS:
            continue
        local = ROOT / path
        if not local.is_file():
            unauthorized.append(
                {
                    "path": path,
                    "risk_markers": ["LOCAL_WORKFLOW_DEFINITION_MISSING"],
                    "state": "active",
                }
            )
            continue
        content = local.read_text(encoding="utf-8")
        markers = [marker for marker in RISK_MARKERS if marker in content]
        if markers:
            unauthorized.append({"path": path, "risk_markers": markers, "state": "active"})
    nonterminal_run_counts = verify_no_concurrent_runs(
        repository=repository,
        token=token,
        current_run_id=run_id,
        effect_deadline_epoch=effect_deadline_epoch,
    )
    if unauthorized:
        raise ChronosProductionError("CHRONOS_UNAUTHORIZED_ACTIVE_WORKFLOW")
    post_merge_ci: dict[str, Any] | None = None
    recovery_v2_scope_guard: dict[str, Any] | None = None
    recovery_v2_final_witness: dict[str, Any] | None = None
    legacy_secret_branch_sha: str | None = None
    if required_successful_ci_sha is not None:
        expected_ci_sha = require_sha(
            required_successful_ci_sha,
            field="required_successful_ci_sha",
        )
        ci_runs_document = _github_get(
            f"/repos/{repository}/actions/workflows/ci-safe-v2.yml/runs"
            f"?branch=main&status=completed&head_sha={expected_ci_sha}&per_page=100",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        raw_ci_runs = ci_runs_document.get("workflow_runs", [])
        if not isinstance(raw_ci_runs, list):
            raise ChronosProductionError("CHRONOS_POST_MERGE_CI_INVALID")
        if recovery_v2 and (
            type(ci_runs_document.get("total_count")) is not int
            or ci_runs_document["total_count"] != len(raw_ci_runs)
            or len(raw_ci_runs) > 100
            or any(not isinstance(item, dict) for item in raw_ci_runs)
        ):
            raise ChronosProductionError("CHRONOS_POST_MERGE_CI_INVENTORY_TRUNCATED")
        if require_recovery_v2_final_witness:
            _require_exact_recovery_v2_final_ci_inventory(
                raw_ci_runs,
                expected_ci_sha=expected_ci_sha,
                expected_run_id=expected_successful_ci_run_id,
            )
        successful = [
            item
            for item in raw_ci_runs
            if isinstance(item, dict)
            and item.get("head_sha") == expected_ci_sha
            and item.get("head_branch") == "main"
            and item.get("event") == "push"
            and item.get("status") == "completed"
            and item.get("conclusion") == "success"
            and type(item.get("run_attempt")) is int
            and item.get("run_attempt") == 1
        ]
        if expected_successful_ci_run_id is not None:
            successful = [
                item for item in successful if item.get("id") == expected_successful_ci_run_id
            ]
        if not successful:
            raise ChronosProductionError("CHRONOS_POST_MERGE_CI_NOT_PROVEN")
        selected = max(successful, key=lambda item: int(item.get("id", 0)))
        selected_run_id = int(selected.get("id", 0))
        if recovery_v2:
            jobs_document = _github_get(
                f"/repos/{repository}/actions/runs/{selected_run_id}/jobs?per_page=100",
                token,
                effect_deadline_epoch=effect_deadline_epoch,
            )
            raw_jobs = jobs_document.get("jobs")
            if (
                not isinstance(raw_jobs, list)
                or type(jobs_document.get("total_count")) is not int
                or jobs_document["total_count"] != len(raw_jobs)
                or len(raw_jobs) > 100
                or any(not isinstance(item, dict) for item in raw_jobs)
            ):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_SCOPE_JOB_INVALID")
            scope_jobs = [
                cast(dict[str, Any], item)
                for item in raw_jobs
                if item.get("name") == "Recovery V2 — scope guard exact"
            ]
            if (
                len(scope_jobs) != 1
                or scope_jobs[0].get("run_id") != selected_run_id
                or scope_jobs[0].get("head_sha") != expected_ci_sha
                or scope_jobs[0].get("status") != "completed"
                or scope_jobs[0].get("conclusion") != "success"
            ):
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_SCOPE_JOB_INVALID")
            recovery_v2_scope_guard = {
                "job_id": int(scope_jobs[0].get("id", 0)),
                "name": "Recovery V2 — scope guard exact",
                "run_id": selected_run_id,
                "head_sha": expected_ci_sha,
                "status": "completed",
                "conclusion": "success",
            }
            if recovery_v2_scope_guard["job_id"] <= 0:
                raise ChronosProductionError("CHRONOS_RECOVERY_V2_SCOPE_JOB_INVALID")
            if require_recovery_v2_final_witness:
                witness_jobs = [
                    cast(dict[str, Any], item)
                    for item in raw_jobs
                    if item.get("name") == "Recovery V2 — final gate witness"
                ]
                if (
                    len(witness_jobs) != 1
                    or witness_jobs[0].get("run_id") != selected_run_id
                    or witness_jobs[0].get("head_sha") != expected_ci_sha
                    or witness_jobs[0].get("status") != "completed"
                    or witness_jobs[0].get("conclusion") != "success"
                    or type(witness_jobs[0].get("id")) is not int
                    or int(witness_jobs[0]["id"]) <= 0
                    or not isinstance(witness_jobs[0].get("completed_at"), str)
                ):
                    raise ChronosProductionError(
                        "CHRONOS_RECOVERY_V2_FINAL_WITNESS_JOB_INVALID"
                    )
                recovery_v2_final_witness = {
                    "job_id": int(witness_jobs[0]["id"]),
                    "name": "Recovery V2 — final gate witness",
                    "run_id": selected_run_id,
                    "head_sha": expected_ci_sha,
                    "status": "completed",
                    "conclusion": "success",
                    "completed_at": witness_jobs[0]["completed_at"],
                }
        post_merge_ci = {
            "workflow_path": SAFE_CI_WORKFLOW_PATH,
            "run_id": selected_run_id,
            "run_attempt": int(selected.get("run_attempt", 0)),
            "head_sha": expected_ci_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        if require_recovery_v2_final_witness:
            if not isinstance(selected.get("created_at"), str) or not isinstance(
                selected.get("updated_at"), str
            ):
                raise ChronosProductionError("CHRONOS_POST_MERGE_CI_INVALID")
            post_merge_ci.update(
                {
                    "created_at": selected["created_at"],
                    "updated_at": selected["updated_at"],
                }
            )
        legacy_ref = _github_get(
            f"/repos/{repository}/git/ref/heads/{LEGACY_PROVIDER_BRANCH}",
            token,
            effect_deadline_epoch=effect_deadline_epoch,
        )
        legacy_object = legacy_ref.get("object")
        expected_legacy_sha = expected_legacy_branch_sha or (
            DATA_TORRENT_RECOVERY_V2_START_SHA
            if recovery_v2_provider_precondition
            else expected_ci_sha
        )
        expected_legacy_sha = require_sha(
            expected_legacy_sha,
            field="expected_legacy_branch_sha",
        )
        if (
            legacy_ref.get("ref") != f"refs/heads/{LEGACY_PROVIDER_BRANCH}"
            or not isinstance(legacy_object, dict)
            or legacy_object.get("type") != "commit"
            or legacy_object.get("sha") != expected_legacy_sha
        ):
            raise ChronosProductionError("CHRONOS_LEGACY_SECRET_BRANCH_NOT_NEUTRALIZED")
        legacy_secret_branch_sha = expected_legacy_sha
    result = {
        "schema_version": "chronos-production-workflow-hold-live-v3",
        "verdict": "WORKFLOW_HOLD_ESTABLISHED",
        "active_after": len(active),
        "disabled_after": len(disabled),
        "queued_after": 0,
        "in_progress_after": 0,
        "nonterminal_run_counts": nonterminal_run_counts,
        "current_run_excluded": run_id,
        "unauthorized_active_workflows": [],
        "post_merge_ci": post_merge_ci,
        "recovery_v2_scope_guard": recovery_v2_scope_guard,
        "legacy_secret_branch_sha": legacy_secret_branch_sha,
        "legacy_ci_workflow_quarantine": {
            "workflow_id": int(legacy_ci_workflow["id"]),
            "workflow_path": LEGACY_CI_WORKFLOW_PATH,
            "state": "disabled_manually",
        },
        "recovery_v2_production_workflow_quarantine": recovery_v2_quarantine,
        "production_environment_policy": {
            "environment": PRODUCTION_ENVIRONMENT,
            "can_admins_bypass": False,
            "protected_branches": False,
            "custom_branch_policies": True,
            "allowed_branches": ["main"],
        },
        "provider_calls": 0,
        "r2_operations": 0,
    }
    if require_recovery_v2_final_witness:
        result["recovery_v2_final_witness"] = recovery_v2_final_witness
    return result


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "--bounded-get-child":
        token_bytes = sys.stdin.buffer.read(2_049)
        if not token_bytes or len(token_bytes) > 2_048:
            raise SystemExit(1)
        try:
            token = token_bytes.decode("utf-8")
            effect_deadline_epoch = None if sys.argv[3] == "" else float(sys.argv[3])
            document = _github_get_direct(
                sys.argv[2],
                token,
                effect_deadline_epoch=effect_deadline_epoch,
            )
        except Exception:
            raise SystemExit(1) from None
        sys.stdout.buffer.write(
            json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--required-successful-ci-sha")
    parser.add_argument("--recovery-v2", action="store_true")
    args = parser.parse_args()
    try:
        raw_deadline = os.getenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH")
        if args.recovery_v2 and raw_deadline is None:
            raise ChronosProductionError("CHRONOS_GITHUB_HOLD_EFFECT_DEADLINE_INVALID")
        effect_deadline_epoch = None if raw_deadline is None else float(raw_deadline)
        if raw_deadline is not None:
            _effect_timeout(effect_deadline_epoch, maximum=4.0)
        result = verify_hold(
            required_successful_ci_sha=args.required_successful_ci_sha,
            recovery_v2=args.recovery_v2,
            effect_deadline_epoch=effect_deadline_epoch,
        )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, ChronosProductionError)
            else ("CHRONOS_GITHUB_HOLD_FAILED")
        )
        print(f"CHRONOS_GITHUB_HOLD_FAILED:{code}")
        raise SystemExit(1) from None
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("CHRONOS_GITHUB_HOLD_PASS")


if __name__ == "__main__":
    main()
