from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_codex_heads_keep_at_least_one_ci_validation_route() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]

    push_branches = triggers.get("push", {}).get("branches", [])
    push_codex = "codex/**" in push_branches

    pull_request = triggers.get("pull_request")
    pull_request_synchronize = not isinstance(pull_request, dict) or (
        "synchronize" in pull_request.get("types", [])
    )

    workflow_dispatch = "workflow_dispatch" in triggers

    assert push_codex or pull_request_synchronize or workflow_dispatch


def test_pr_heads_do_not_schedule_duplicate_push_and_pull_request_suites() -> None:
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    push_codex = "codex/**" in triggers.get("push", {}).get("branches", [])
    pull_request = triggers.get("pull_request")
    pull_request_synchronize = not isinstance(pull_request, dict) or (
        "synchronize" in pull_request.get("types", [])
    )

    assert not (push_codex and pull_request_synchronize)
    assert pull_request_synchronize
    assert "workflow_dispatch" in triggers
