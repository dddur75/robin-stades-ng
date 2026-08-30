"""Verify the live GitHub workflow hold without exposing token material."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

import requests

from robin.chronos_production import (
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


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise ChronosProductionError(f"CHRONOS_MISSING_CONTEXT:{name}")
    return value


def _github_get(path: str, token: str) -> dict[str, Any]:
    try:
        response = requests.get(
            "https://api.github.com" + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
    except requests.RequestException:
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_UNAVAILABLE") from None
    if not 200 <= response.status_code < 300:
        raise ChronosProductionError(f"CHRONOS_GITHUB_HOLD_API_HTTP_{response.status_code}")
    try:
        document = response.json()
    except ValueError:
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID") from None
    if not isinstance(document, dict):
        raise ChronosProductionError("CHRONOS_GITHUB_HOLD_API_INVALID")
    return cast(dict[str, Any], document)


def verify_hold(*, required_successful_ci_sha: str | None = None) -> dict[str, Any]:
    repository = _required("GITHUB_REPOSITORY")
    if repository != EXPECTED_REPOSITORY:
        raise ChronosProductionError("CHRONOS_REPOSITORY_MISMATCH")
    token = _required("GITHUB_TOKEN")
    run_id = int(_required("GITHUB_RUN_ID"))
    workflows_document = _github_get(f"/repos/{repository}/actions/workflows?per_page=100", token)
    raw_workflows = workflows_document.get("workflows", [])
    if not isinstance(raw_workflows, list):
        raise ChronosProductionError("CHRONOS_GITHUB_WORKFLOWS_INVALID")
    workflows = [item for item in raw_workflows if isinstance(item, dict)]
    legacy_ci_workflow = _github_get(
        f"/repos/{repository}/actions/workflows/ci.yml",
        token,
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
    )
    deployment_policy = environment.get("deployment_branch_policy")
    environment_policies = _github_get(
        f"/repos/{repository}/environments/{PRODUCTION_ENVIRONMENT}/deployment-branch-policies",
        token,
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
        if path in AUTHORIZED_PROTECTED_WORKFLOWS:
            continue
        local = ROOT / path
        if not local.is_file():
            continue
        content = local.read_text(encoding="utf-8")
        markers = [marker for marker in RISK_MARKERS if marker in content]
        if markers:
            unauthorized.append({"path": path, "risk_markers": markers, "state": "active"})
    active_runs: list[dict[str, Any]] = []
    for status in ("queued", "in_progress"):
        runs_document = _github_get(
            f"/repos/{repository}/actions/runs?status={status}&per_page=100", token
        )
        raw_runs = runs_document.get("workflow_runs", [])
        if not isinstance(raw_runs, list):
            raise ChronosProductionError("CHRONOS_GITHUB_RUNS_INVALID")
        for item in raw_runs:
            if not isinstance(item, dict) or int(item.get("id", 0)) == run_id:
                continue
            active_runs.append(
                {
                    "run_id": int(item.get("id", 0)),
                    "status": str(item.get("status", status)),
                    "workflow_id": int(item.get("workflow_id", 0)),
                }
            )
    if unauthorized:
        raise ChronosProductionError("CHRONOS_UNAUTHORIZED_ACTIVE_WORKFLOW")
    if active_runs:
        raise ChronosProductionError("CHRONOS_CONCURRENT_RUN_PRESENT")
    post_merge_ci: dict[str, Any] | None = None
    legacy_secret_branch_sha: str | None = None
    if required_successful_ci_sha is not None:
        expected_ci_sha = require_sha(
            required_successful_ci_sha,
            field="required_successful_ci_sha",
        )
        ci_runs_document = _github_get(
            f"/repos/{repository}/actions/workflows/ci-safe-v2.yml/runs"
            "?branch=main&status=completed&per_page=100",
            token,
        )
        raw_ci_runs = ci_runs_document.get("workflow_runs", [])
        if not isinstance(raw_ci_runs, list):
            raise ChronosProductionError("CHRONOS_POST_MERGE_CI_INVALID")
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
        if not successful:
            raise ChronosProductionError("CHRONOS_POST_MERGE_CI_NOT_PROVEN")
        selected = max(successful, key=lambda item: int(item.get("id", 0)))
        post_merge_ci = {
            "workflow_path": SAFE_CI_WORKFLOW_PATH,
            "run_id": int(selected.get("id", 0)),
            "run_attempt": int(selected.get("run_attempt", 0)),
            "head_sha": expected_ci_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        legacy_ref = _github_get(
            f"/repos/{repository}/git/ref/heads/{LEGACY_PROVIDER_BRANCH}",
            token,
        )
        legacy_object = legacy_ref.get("object")
        if (
            legacy_ref.get("ref") != f"refs/heads/{LEGACY_PROVIDER_BRANCH}"
            or not isinstance(legacy_object, dict)
            or legacy_object.get("type") != "commit"
            or legacy_object.get("sha") != expected_ci_sha
        ):
            raise ChronosProductionError("CHRONOS_LEGACY_SECRET_BRANCH_NOT_NEUTRALIZED")
        legacy_secret_branch_sha = expected_ci_sha
    return {
        "schema_version": "chronos-production-workflow-hold-live-v3",
        "verdict": "WORKFLOW_HOLD_ESTABLISHED",
        "active_after": len(active),
        "disabled_after": len(disabled),
        "queued_after": 0,
        "in_progress_after": 0,
        "current_run_excluded": run_id,
        "unauthorized_active_workflows": [],
        "post_merge_ci": post_merge_ci,
        "legacy_secret_branch_sha": legacy_secret_branch_sha,
        "legacy_ci_workflow_quarantine": {
            "workflow_id": int(legacy_ci_workflow["id"]),
            "workflow_path": LEGACY_CI_WORKFLOW_PATH,
            "state": "disabled_manually",
        },
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--required-successful-ci-sha")
    args = parser.parse_args()
    try:
        result = verify_hold(
            required_successful_ci_sha=args.required_successful_ci_sha,
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
