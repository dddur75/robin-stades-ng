from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]


def _workflow_steps(value: object) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "steps" and isinstance(child, list):
                steps.extend(step for step in child if isinstance(step, dict))
            steps.extend(_workflow_steps(child))
    elif isinstance(value, list):
        for child in value:
            steps.extend(_workflow_steps(child))
    return steps


def test_recovery_v2_workflow_inputs_are_never_interpolated_in_shell_source() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    paths = (
        workflow_root / "chronos-neon-branch-identity-v2.yml",
        workflow_root / "chronos-identity-seal-v2.yml",
        workflow_root / "chronos-production-bootstrap-v4.yml",
        workflow_root / "data-torrent-live-v2.yml",
    )
    for path in paths:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in _workflow_steps(workflow):
            command = step.get("run")
            if isinstance(command, str):
                assert "${{ inputs." not in command, (path.name, step.get("name"))


def test_linux_ci_proves_the_exact_runtime_lock_before_the_full_suite() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci-safe-v2.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["tests"]["steps"]
    lock_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Valider le lock data torrent Linux avant tout effet reel"
    )
    install_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Installer les dependances"
    )
    assert lock_index < install_index
    command = " ".join(steps[lock_index]["run"].split())
    assert "--dry-run" not in command
    assert "--ignore-installed" not in command
    assert command.startswith("python -m pip install --only-binary=:all: --require-hashes")
    assert "-r requirements-data-torrent.lock" in command
    assert (
        "import boto3, psycopg, pypdf, requests, robin.data_torrent.runtime, sqlalchemy" in command
    )


def test_safe_ci_is_a_secret_free_copy_of_the_quarantined_legacy_definition() -> None:
    workflow_root = ROOT / ".github" / "workflows"
    legacy_text = (workflow_root / "ci.yml").read_text(encoding="utf-8")
    safe_text = (workflow_root / "ci-safe-v2.yml").read_text(encoding="utf-8")
    assert "${{ secrets." not in legacy_text
    assert "${{ secrets." not in safe_text
    legacy = yaml.safe_load(legacy_text)
    safe = yaml.safe_load(safe_text)
    assert safe["name"] == "00 - Qualite continue SAFE V2"
    legacy["name"] = safe["name"]
    scope_job = safe["jobs"].pop("data-torrent-recovery-v2-scope-guard")
    tests_job = safe["jobs"]["tests"]
    assert tests_job["if"] == "${{ !cancelled() }}"
    assert tests_job["needs"][0] == "data-torrent-recovery-v2-scope-guard"
    tests_job["needs"].remove("data-torrent-recovery-v2-scope-guard")
    tests_job["if"] = legacy["jobs"]["tests"]["if"]
    prerequisite_step = tests_job["steps"][0]
    scope_result = prerequisite_step["env"].pop("DATA_TORRENT_RECOVERY_V2_SCOPE_RESULT")
    assert scope_result == "${{ needs.data-torrent-recovery-v2-scope-guard.result }}"
    skipped_gate = (
        'test "$DATA_TORRENT_RECOVERY_V2_SCOPE_RESULT" = "success" || '
        'test "$DATA_TORRENT_RECOVERY_V2_SCOPE_RESULT" = "skipped"'
    )
    assert prerequisite_step["run"].splitlines()[-1] == skipped_gate
    prerequisite_step["run"] = "\n".join(prerequisite_step["run"].splitlines()[:-1]) + "\n"
    recovery_scope_step = next(
        step
        for step in tests_job["steps"]
        if step.get("name") == "Exiger le scope guard sur chaque run Recovery V2"
    )
    assert recovery_scope_step["run"] == (
        'test "$DATA_TORRENT_RECOVERY_V2_SCOPE_RESULT" = "success"\n'
        'if [ "$DATA_TORRENT_RECOVERY_V2_PHASE" = "PR_C" ]; then\n'
        '  test "$DATA_TORRENT_RECOVERY_V2_TERMINAL_CANDIDATE_COMPLETE" = "true"\n'
        "fi\n"
    )
    tests_job["steps"].remove(recovery_scope_step)
    recovery_step = next(
        step
        for step in tests_job["steps"]
        if step.get("name") == "Valider statiquement Recovery V2"
    )
    tests_job["steps"].remove(recovery_step)
    final_witness_job = safe["jobs"].pop(
        "data-torrent-recovery-v2-final-gate-witness"
    )
    assert safe == legacy
    typing_step = next(
        step for step in safe["jobs"]["tests"]["steps"] if step.get("name") == "Typage strict"
    )
    typing_command = " ".join(typing_step["run"].split())
    assert (
        "python -m mypy --strict --explicit-package-bases "
        "scripts/build_hypothesis_evidence.py" in typing_command
    )
    recovery_command = " ".join(recovery_step["run"].split())
    required_entrypoints = {
        "scripts/build_data_torrent_live_call_graph_v2.py",
        "scripts/check_data_torrent_recovery_v2_scope.py",
        "scripts/chronos_live_path_artifact_guard_v2.py",
        "scripts/chronos_neon_branch_identity_v2.py",
        "scripts/chronos_production_recovery_v2.py",
        "scripts/dispatch_data_torrent_recovery_v2_stage.py",
        "scripts/github_release_attestation_v2.py",
        "scripts/install_chronos_runtime_bindings_v2.py",
        "scripts/materialize_data_torrent_recovery_v2_delivery_evidence.py",
        "scripts/materialize_data_torrent_recovery_v2_terminal_evidence.py",
        "scripts/run_data_torrent_v2.py",
        "scripts/seal_chronos_identity_go_v2.py",
    }
    assert "python -m mypy --strict --explicit-package-bases" in recovery_command
    assert "python -m bandit -q -r" in recovery_command
    assert all(path in recovery_command for path in required_entrypoints)
    scope_condition = " ".join(scope_job["if"].split())
    assert "github.head_ref == 'codex/data-torrent-recovery-v2'" in scope_condition
    for slot in ("A", "B", "C"):
        assert (
            "github.event.head_commit.message == "
            f"'[DATA_TORRENT_RECOVERY_V2] PR-{slot}'"
        ) in scope_condition
    assert "startsWith" not in scope_condition
    assert scope_job["permissions"] == {"contents": "read"}
    assert final_witness_job["permissions"] == {}
