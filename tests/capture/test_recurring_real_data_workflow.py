from __future__ import annotations

import hashlib
import runpy
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prospective-deep-scheduler.yml"
GENERATION = "4c150973fc3d486e3738f80716019839ac2c4126644849d336e267e6929e6d87"
CONTINUITY_HELPER = ROOT / "scripts/validate_robin_documentary_continuity.py"
SUCCESSOR_HELPER = ROOT / "scripts/reconcile_robin_relay_successor.py"


def _continuity() -> dict[str, object]:
    assert CONTINUITY_HELPER.is_file()
    return runpy.run_path(str(CONTINUITY_HELPER))


def _successor_control() -> dict[str, object]:
    assert SUCCESSOR_HELPER.is_file()
    return runpy.run_path(str(SUCCESSOR_HELPER))


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write(repository: Path, relative: str, content: str) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _commit(repository: Path, message: str, changes: dict[str, str]) -> str:
    for relative, content in changes.items():
        _write(repository, relative, content)
    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir(parents=True)
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Robin tests")
    _git(repository, "config", "user.email", "robin-tests@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    initial = _commit(
        repository,
        "initial",
        {
            "scripts/run_recurring_real_data.py": "print('runtime-v1')\n",
            "reports/evidence/robin-real-data-result-run-37153158456-public-receipt.json": "{}\n",
        },
    )
    return repository, initial


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _trigger(workflow: dict[str, object]) -> dict[str, object]:
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    return trigger


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_workflow_has_provider_free_bootstrap_relay_and_watchdog() -> None:
    workflow = _workflow()
    trigger = _trigger(workflow)
    assert set(trigger) == {"schedule", "workflow_dispatch"}
    assert trigger["schedule"] == [{"cron": "13 * * * *"}]
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"mode", "origin", "generation", "chain_id", "parent_run_id", "sequence"}
    assert inputs["mode"]["options"] == ["probe", "collect"]
    assert inputs["origin"]["options"] == ["bootstrap", "relay"]
    assert inputs["generation"]["default"] == GENERATION
    assert "inputs.generation" in workflow["run-name"]
    assert "inputs.origin" in workflow["run-name"]
    assert "inputs.chain_id" in workflow["run-name"]
    assert "inputs.sequence" in workflow["run-name"]
    assert workflow["permissions"] == {"contents": "read"}
    concurrency = workflow["concurrency"]
    assert "seed-control" in concurrency["group"]
    assert "github.actor == 'github-actions[bot]'" in concurrency["group"]
    assert "github.run_id" in concurrency["group"]
    assert concurrency["queue"] == "max"
    assert "cancel-in-progress" not in concurrency

    jobs = workflow["jobs"]
    assert set(jobs) == {"bootstrap", "watchdog", "relay", "capture"}
    for job_name in ("bootstrap", "relay"):
        assert jobs[job_name]["permissions"] == {
            "actions": "write",
            "contents": "read",
        }
    assert jobs["watchdog"]["permissions"] == {
        "actions": "write",
        "contents": "read",
    }
    assert jobs["capture"]["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
    assert jobs["relay"]["environment"] == "robin-autonomous-relay-v1"
    assert "github.actor == 'github-actions[bot]'" in jobs["relay"]["if"]
    assert jobs["capture"]["needs"] == "relay"
    assert "needs.relay.outputs.collect == 'true'" in jobs["capture"]["if"]


def test_relay_is_bounded_for_probe_and_arms_collect_successor_first() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    bootstrap = next(
        step
        for step in jobs["bootstrap"]["steps"]
        if "dispatch first automatic relay" in step.get("name", "")
    )
    relay = next(step for step in jobs["relay"]["steps"] if step.get("id") == "relay")
    watchdog = next(
        step
        for step in jobs["watchdog"]["steps"]
        if "Restart a missing relay" in step.get("name", "")
    )
    assert "--sequence 1" in bootstrap["run"]
    assert '[[ "$GITHUB_ACTOR" == "dddur75" ]]' in bootstrap["run"]
    assert '[[ "$GITHUB_ACTOR" == "github-actions[bot]" ]]' in relay["run"]
    assert '[[ "$SEQUENCE" == "2" ]]' in relay["run"]
    assert '[[ "$SEQUENCE" == "1" ]]' in relay["run"]
    assert "next_sequence" in relay["run"]
    assert "scripts/reconcile_robin_relay_successor.py" in relay["run"]
    assert "actions/runs/$PARENT_RUN_ID/jobs" in relay["run"]
    assert '.name == "relay" and .conclusion == "success"' in relay["run"]
    assert '[[ "$CHAIN_ID" == "$PARENT_RUN_ID" ]]' in relay["run"]
    assert "robin-$MODE-bootstrap-$GENERATION-0-0" in relay["run"]
    assert "robin-watchdog-schedule-none-$PARENT_RUN_ID-0" in relay["run"]
    assert "previous_sequence" in relay["run"]
    assert "robin-$MODE-relay-$GENERATION-$CHAIN_ID-$previous_sequence" in relay["run"]
    assert '.head_sha <<<"$parent"' in relay["run"]
    assert '.run_attempt <<<"$parent"' in relay["run"]
    assert "scripts/reconcile_robin_relay_successor.py" in watchdog["run"]
    assert '--active-prefix "robin-$MODE-relay-$GENERATION-"' in bootstrap["run"]
    assert '--active-prefix "robin-collect-relay-$EXPECTED_GENERATION-"' in watchdog["run"]
    assert _successor_control()["_ACTIVE_STATUSES"] == frozenset(
        {"queued", "in_progress", "requested", "waiting", "pending"}
    )
    for step in (bootstrap, relay, watchdog):
        assert "successor_title=" in step["run"]
        assert "scripts/reconcile_robin_relay_successor.py" in step["run"]
        assert "--successor-title" in step["run"]
        assert step["run"].count("validate_documentary_continuity()") == 1
        assert step["run"].index("validate_documentary_continuity()") < step["run"].index(
            'validate_documentary_continuity "$GITHUB_SHA"'
        )
        assert "secrets." not in yaml.safe_dump(step)
    assert relay["run"].index("scripts/reconcile_robin_relay_successor.py") < relay["run"].index(
        'echo "collect=true"'
    )


def test_control_plane_retries_only_json_gets_and_never_replays_dispatch() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    control_steps = {
        "bootstrap": next(
            step
            for step in jobs["bootstrap"]["steps"]
            if "dispatch first automatic relay" in step.get("name", "")
        ),
        "watchdog": next(
            step
            for step in jobs["watchdog"]["steps"]
            if "Restart a missing relay" in step.get("name", "")
        ),
        "relay": next(step for step in jobs["relay"]["steps"] if step.get("id") == "relay"),
    }

    for job_name, step in control_steps.items():
        command = step["run"]
        assert "read_gh_json()" in command, job_name
        assert "for attempt in 1 2 3" in command, job_name
        assert 'payload="$(timeout --kill-after=5s 20s gh api "$endpoint")"' in command, job_name
        assert "jq -e ." in command, job_name
        assert "GitHub API JSON read failed after 3 attempts" in command, job_name
        assert "gh api --jq" not in command, job_name
        assert command.count("gh api ") == 1, job_name
        assert "gh api --method POST --silent" not in command, job_name
        assert "scripts/reconcile_robin_relay_successor.py" in command, job_name
        assert command.count("scripts/reconcile_robin_relay_successor.py") == 1, job_name


def test_environment_timer_and_main_policy_are_fail_closed() -> None:
    workflow = _workflow()
    for job_name in ("bootstrap", "relay"):
        command = "\n".join(step.get("run", "") for step in workflow["jobs"][job_name]["steps"])
        assert "environments/robin-autonomous-relay-v1" in command
        assert 'expected_wait="1"' in command
        assert 'expected_wait="60"' in command
        assert "deployment_branch_policy.protected_branches" in command
        assert "deployment_branch_policy.custom_branch_policies" in command
        assert "deployment-branch-policies" in command
        assert '[.protection_rules[].type] | sort == ["branch_policy", "wait_timer"]' in command
        assert '.name == "main" and .type == "branch"' in command
        assert ".total_count == 1" in command
        assert "(.branch_policies | length) == 1" in command
    relay_command = "\n".join(step.get("run", "") for step in workflow["jobs"]["relay"]["steps"])
    assert "current_run_created_at" in relay_command
    assert "current_epoch - created_epoch >= expected_wait * 60" in relay_command
    assert "EXPECTED_EXPIRES_AT" in relay_command
    assert "current_epoch + 10800 <= expiry_epoch" in relay_command
    assert "current_epoch + 60 * 60 + 10800 <= expiry_epoch" in relay_command
    assert "current_epoch <= expiry_epoch" in relay_command
    watchdog_step = next(
        step
        for step in workflow["jobs"]["watchdog"]["steps"]
        if "Restart a missing relay" in step.get("name", "")
    )
    watchdog_command = watchdog_step["run"]
    assert "EXPECTED_EXPIRES_AT" in watchdog_step["env"]
    assert "current_epoch + 60 * 60 + 10800 <= expiry_epoch" in watchdog_command
    assert "environments/robin-autonomous-relay-v1" in watchdog_command
    assert '== "60"' in watchdog_command
    assert "deployment_branch_policy.protected_branches" in watchdog_command
    assert "deployment_branch_policy.custom_branch_policies" in watchdog_command
    assert "deployment-branch-policies" in watchdog_command
    assert (
        '[.protection_rules[].type] | sort == ["branch_policy", "wait_timer"]' in watchdog_command
    )
    assert ".total_count == 1" in watchdog_command
    assert "(.branch_policies | length) == 1" in watchdog_command


def test_capture_gates_documentary_main_continuity_and_retired_provider_routes() -> None:
    workflow = _workflow()
    gate = next(step for step in workflow["jobs"]["capture"]["steps"] if step.get("id") == "gate")
    command = gate["run"]
    assert "current_main_sha" in command
    assert "scripts/validate_robin_documentary_continuity.py" in command
    assert '--base "$GITHUB_SHA" --head "$current_main_sha"' in command
    assert '[[ "$GITHUB_SHA" == "$current_main_sha" ]]' not in command
    assert '[[ "$GITHUB_EVENT_NAME" == "workflow_dispatch" ]]' in command
    assert '[[ "$GITHUB_ACTOR" == "github-actions[bot]" ]]' in command
    assert "prospective-deep-scheduler.yml@refs/heads/main" in command
    assert "321915839" in command
    for workflow_id, path in {
        308531686: "03_archive.yml",
        319598077: "collect-fixtures.yml",
        319598078: "collect-odds.yml",
        319598079: "daily-health.yml",
        319598080: "post-match-settlement.yml",
        319598083: "pre-match-shadow.yml",
        319799017: "shadow-diagnostics.yml",
        321915844: "prospective-odds-capture.yml",
        345580923: "data-torrent-live-v1.yml",
        373855898: "90-reprise-collecte-pilot.yml",
        374107131: "91-robin-real-data-result.yml",
        374470410: "92-robin-autonomous-lab.yml",
    }.items():
        assert str(workflow_id) in command
        assert path in command
    assert "disabled_manually" in command
    assert "datetime.timedelta(hours=3) <= expires" in command

    paths = {
        "EXPECTED_MANIFEST_SHA256": "configs/execution/robin-autonomous-lab-20261004.json",
        "EXPECTED_SOURCE_SHA256": "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md",
        "EXPECTED_SCHEDULE_MANIFEST_SHA256": "configs/execution/robin-autonomous-lab-schedule-reliability-20261004.json",
        "EXPECTED_SCHEDULE_SOURCE_SHA256": "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-SCHEDULE-RELIABILITY-2026-10-04.md",
        "EXPECTED_ESTABLISHED_MANIFEST_SHA256": "configs/execution/robin-autonomous-lab-established-scheduler-20261004.json",
        "EXPECTED_ESTABLISHED_SOURCE_SHA256": "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-ESTABLISHED-SCHEDULER-2026-10-04.md",
        "EXPECTED_TRIGGER_MANIFEST_SHA256": "configs/execution/robin-autonomous-lab-trigger-recovery-v2-20261005.json",
        "EXPECTED_TRIGGER_SOURCE_SHA256": "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-V2-2026-10-05.md",
    }
    for environment_name, relative_path in paths.items():
        assert gate["env"][environment_name] == _lf_sha256(ROOT / relative_path)
    assert gate["env"]["EXPECTED_TRIGGER_MANIFEST_SHA256"] == GENERATION
    assert "set(trigger_manifest) == set(manifest)" in command

    revalidate = next(
        step
        for step in workflow["jobs"]["capture"]["steps"]
        if step.get("name") == "Revalidate documentary continuity immediately before collection"
    )
    assert "scripts/validate_robin_documentary_continuity.py" in revalidate["run"]
    assert '--base "$GITHUB_SHA" --head "$current_main_sha"' in revalidate["run"]


def test_relay_validates_parent_run_main_and_successor_as_separate_segments() -> None:
    workflow = _workflow()
    relay = next(step for step in workflow["jobs"]["relay"]["steps"] if step.get("id") == "relay")
    command = relay["run"]
    assert 'validate_documentary_continuity "$parent_sha" "$GITHUB_SHA"' in command
    assert 'validate_documentary_continuity "$GITHUB_SHA" "$current_main_sha"' in command
    assert 'validate_documentary_continuity "$GITHUB_SHA" "$successor_sha"' in command
    assert 'validate_documentary_continuity "$GITHUB_SHA" "$latest_main_sha"' in command
    assert 'validate_documentary_continuity "$successor_sha" "$latest_main_sha"' in command
    assert '.workflow_id <<<"$successor"' in command
    assert '.actor.login <<<"$successor"' in command
    assert '.run_attempt <<<"$successor"' in command
    assert command.index(
        'validate_documentary_continuity "$GITHUB_SHA" "$latest_main_sha"'
    ) < command.index('echo "collect=true"')
    assert all(
        step["with"]["fetch-depth"] == 0
        for job_name in ("bootstrap", "watchdog", "relay", "capture")
        for step in workflow["jobs"][job_name]["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    )


def test_gate_inventories_every_existing_provider_secret_route() -> None:
    expected = {
        "03_archive.yml",
        "collect-fixtures.yml",
        "collect-odds.yml",
        "daily-health.yml",
        "post-match-settlement.yml",
        "pre-match-shadow.yml",
        "shadow-diagnostics.yml",
        "prospective-odds-capture.yml",
        "data-torrent-live-v1.yml",
        "90-reprise-collecte-pilot.yml",
        "91-robin-real-data-result.yml",
        "92-robin-autonomous-lab.yml",
        "prospective-deep-scheduler.yml",
    }
    observed = {
        path.name
        for path in (ROOT / ".github/workflows").glob("*.yml")
        if "secrets.ODDS_API_KEY" in path.read_text(encoding="utf-8")
    }
    assert observed == expected


def test_workflow_scopes_secrets_and_uploads_only_normalized_delivery() -> None:
    workflow = _workflow()
    assert workflow["env"] == {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    steps = workflow["jobs"]["capture"]["steps"]
    capture = next(step for step in steps if step.get("id") == "capture")
    assert {name for name in capture["env"] if name.startswith("R2_")} == {
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
    }
    assert capture["env"]["THE_ODDS_API_KEY"] == "${{ secrets.ODDS_API_KEY }}"
    assert {name for name in capture["env"] if name.startswith("ROBIN_RELAY_")} == {
        "ROBIN_RELAY_MODE",
        "ROBIN_RELAY_ORIGIN",
        "ROBIN_RELAY_GENERATION",
        "ROBIN_RELAY_CHAIN_ID",
        "ROBIN_RELAY_PARENT_RUN_ID",
        "ROBIN_RELAY_SEQUENCE",
    }
    assert "scripts/run_recurring_real_data.py" in capture["run"]
    for job_name, job in workflow["jobs"].items():
        for step in job["steps"]:
            if job_name == "capture" and step is capture:
                continue
            serialized = yaml.safe_dump(step)
            assert "secrets.ODDS_API_KEY" not in serialized
            assert "secrets.R2_" not in serialized
    validate = next(step for step in steps if step.get("id") == "validate")
    assert validate["if"] == "${{ always() && !cancelled() }}"
    assert "RECURRING_NORMALIZED_FILE_SET_INVALID" in validate["run"]
    assert "raw_payload_base64" in validate["run"]
    assert "private_report_r2_status" in validate["run"]
    assert 'snapshot["schema_version"] == "robin-real-data-explorer-v2"' in validate["run"]
    assert "robin-real-data-dashboard-v1" not in validate["run"]
    upload = next(step for step in steps if step.get("id") == "upload")
    assert upload["with"]["path"] == "${{ runner.temp }}/robin-autonomous-lab"
    assert upload["with"]["retention-days"] == 30


def test_workflow_pins_actions_dependencies_and_preserves_terminal_outcome() -> None:
    workflow = _workflow()
    allowed = {
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    }
    uses = [
        step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
    ]
    assert uses and set(uses) == allowed
    steps = workflow["jobs"]["capture"]["steps"]
    install = next(step for step in steps if step.get("id") == "install")
    assert install["run"] == (
        "python -I -m pip install --only-binary=:all: --require-hashes "
        "-r requirements-data-torrent.lock"
    )
    terminal = next(step for step in steps if step.get("id") == "terminal")
    assert terminal["if"] == "${{ always() }}"
    assert "RECURRING_DELIVERY_INCOMPLETE" in terminal["run"]


def test_old_relay_accepts_pr96_documentary_merge_without_relabeling_sha(
    tmp_path: Path,
) -> None:
    repository, run_sha = _repository(tmp_path)
    main_sha = _commit(
        repository,
        "PR96-shaped documentary closure",
        {
            "reports/council/decision-ledger.jsonl": '{"decision":"PASS_AND_HOLD"}\n',
            "reports/council/robin-simplification-postrepair-final-c1-architecture-v1.json": "{}\n",
            "reports/council/robin-simplification-postrepair-final-c2-operations-v1.json": "{}\n",
            "reports/council/robin-simplification-postrepair-final-c4-performance-v1.json": "{}\n",
            "reports/evidence/evidence-graph.json": '{"claims":[]}\n',
            "reports/evidence/robin-simplification-postrepair-closure-20261006.json": "{}\n",
            "tests/council/test_robin_simplification_postrepair_closure.py": "def test_closure():\n    assert True\n",
        },
    )

    decision = _continuity()["evaluate_repository"](repository, run_sha, main_sha)

    assert decision["accepted"] is True
    assert decision["base_sha"] == run_sha
    assert decision["head_sha"] == main_sha
    assert decision["reason"] == "DOCUMENTARY_DESCENDANT"


@pytest.mark.parametrize(
    "protected_path",
    [
        ".github/workflows/prospective-deep-scheduler.yml",
        "scripts/run_recurring_real_data.py",
        "src/robin/capture/recurring_real_data.py",
        "requirements-data-torrent.lock",
        "configs/execution/robin-autonomous-lab-20261004.json",
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md",
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-SCHEDULE-RELIABILITY-2026-10-04.md",
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-ESTABLISHED-SCHEDULER-2026-10-04.md",
        "docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-TRIGGER-RECOVERY-V2-2026-10-05.md",
        "reports/evidence/robin-real-data-result-run-37153158456-public-receipt.json",
    ],
)
def test_documentary_continuity_rejects_runtime_or_authority(
    tmp_path: Path, protected_path: str
) -> None:
    repository, run_sha = _repository(tmp_path)
    main_sha = _commit(repository, "unsafe change", {protected_path: "changed\n"})

    decision = _continuity()["evaluate_repository"](repository, run_sha, main_sha)

    assert decision["accepted"] is False
    assert decision["reason"] == "NON_DOCUMENTARY_PATH"
    assert protected_path in decision["rejected_paths"]


def test_documentary_continuity_rejects_unknown_path_and_reverse_history(
    tmp_path: Path,
) -> None:
    repository, run_sha = _repository(tmp_path)
    main_sha = _commit(repository, "unknown surface", {"README.md": "changed\n"})
    evaluate = _continuity()["evaluate_repository"]

    unknown = evaluate(repository, run_sha, main_sha)
    reverse = evaluate(repository, main_sha, run_sha)

    assert unknown["accepted"] is False
    assert unknown["reason"] == "NON_DOCUMENTARY_PATH"
    assert reverse["accepted"] is False
    assert reverse["reason"] == "HEAD_NOT_DESCENDANT"


def test_parent_run_and_run_main_are_checked_as_two_distinct_segments(
    tmp_path: Path,
) -> None:
    repository, parent_sha = _repository(tmp_path)
    run_sha = _commit(
        repository,
        "temporary runtime mutation",
        {"scripts/run_recurring_real_data.py": "print('runtime-v2')\n"},
    )
    main_sha = _commit(
        repository,
        "runtime revert plus documentation",
        {
            "scripts/run_recurring_real_data.py": "print('runtime-v1')\n",
            "reports/council/review.json": "{}\n",
        },
    )
    evaluate = _continuity()["evaluate_repository"]

    collapsed = evaluate(repository, parent_sha, main_sha)
    parent_to_run = evaluate(repository, parent_sha, run_sha)
    run_to_main = evaluate(repository, run_sha, main_sha)

    assert collapsed["accepted"] is True
    assert parent_to_run["accepted"] is False
    assert run_to_main["accepted"] is False
    assert parent_to_run["reason"] == run_to_main["reason"] == "NON_DOCUMENTARY_PATH"


def test_documentary_continuity_rejects_protected_rename_even_into_reports(
    tmp_path: Path,
) -> None:
    repository, run_sha = _repository(tmp_path)
    _git(
        repository,
        "mv",
        "scripts/run_recurring_real_data.py",
        "reports/run_recurring_real_data.py",
    )
    _git(repository, "commit", "--quiet", "-m", "unsafe rename")
    main_sha = _git(repository, "rev-parse", "HEAD")

    decision = _continuity()["evaluate_repository"](repository, run_sha, main_sha)

    assert decision["accepted"] is False
    assert decision["reason"] == "NON_DOCUMENTARY_PATH"
    assert "scripts/run_recurring_real_data.py" in decision["rejected_paths"]


def test_documentary_continuity_rejects_mode_change_and_invalid_identity(
    tmp_path: Path,
) -> None:
    repository, initial_sha = _repository(tmp_path)
    run_sha = _commit(
        repository,
        "regular documentary file",
        {"reports/council/review.md": "review\n"},
    )
    _git(repository, "update-index", "--chmod=+x", "reports/council/review.md")
    _git(repository, "commit", "--quiet", "-m", "unsafe mode change")
    main_sha = _git(repository, "rev-parse", "HEAD")
    evaluate = _continuity()["evaluate_repository"]

    identical = evaluate(repository, initial_sha, initial_sha)
    mode_change = evaluate(repository, run_sha, main_sha)
    invalid = evaluate(repository, "not-a-sha", main_sha)

    assert identical["accepted"] is True
    assert identical["reason"] == "IDENTICAL_SHA"
    assert mode_change["accepted"] is False
    assert mode_change["reason"] == "NON_REGULAR_DOCUMENTARY_OBJECT"
    assert mode_change["rejected_paths"] == ["reports/council/review.md"]
    assert invalid["accepted"] is False
    assert invalid["reason"] == "GIT_INSPECTION_FAILED"


def test_documentary_continuity_rejects_shallow_symlink_gitlink_and_deletion(
    tmp_path: Path,
) -> None:
    evaluate = _continuity()["evaluate_repository"]

    deleted_repository, deleted_base = _repository(tmp_path / "deleted")
    (deleted_repository / "scripts/run_recurring_real_data.py").unlink()
    _git(deleted_repository, "add", "--all")
    _git(deleted_repository, "commit", "--quiet", "-m", "delete runtime")
    deleted_head = _git(deleted_repository, "rev-parse", "HEAD")
    deleted = evaluate(deleted_repository, deleted_base, deleted_head)

    object_repository, object_base = _repository(tmp_path / "objects")
    object_run = _commit(
        object_repository,
        "documentary target",
        {"reports/council/target.txt": "target\n"},
    )
    blob_sha = _git(
        object_repository,
        "rev-parse",
        f"{object_run}:reports/council/target.txt",
    )
    _git(
        object_repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"120000,{blob_sha},reports/council/link",
    )
    _git(object_repository, "commit", "--quiet", "-m", "symlink object")
    symlink_head = _git(object_repository, "rev-parse", "HEAD")
    symlink = evaluate(object_repository, object_run, symlink_head)

    _git(
        object_repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{object_base},reports/council/nested",
    )
    _git(object_repository, "commit", "--quiet", "-m", "gitlink object")
    gitlink_head = _git(object_repository, "rev-parse", "HEAD")
    gitlink = evaluate(object_repository, symlink_head, gitlink_head)

    (object_repository / ".git/shallow").write_text(
        f"{gitlink_head}\n", encoding="ascii", newline="\n"
    )
    shallow = evaluate(object_repository, gitlink_head, gitlink_head)

    assert deleted["accepted"] is False
    assert deleted["reason"] == "NON_DOCUMENTARY_PATH"
    assert symlink["accepted"] is False
    assert symlink["reason"] == "NON_REGULAR_DOCUMENTARY_OBJECT"
    assert gitlink["accepted"] is False
    assert gitlink["reason"] == "NON_REGULAR_DOCUMENTARY_OBJECT"
    assert shallow["accepted"] is False
    assert shallow["reason"] == "INCOMPLETE_HISTORY"


def test_successor_control_reconciles_ambiguous_post_without_replay() -> None:
    module = _successor_control()
    control_error = module["GitHubControlError"]
    calls: list[tuple[str, dict[str, str] | None]] = []
    successor = {
        "id": 456,
        "display_title": f"robin-collect-relay-{GENERATION}-123-2",
        "status": "waiting",
    }
    inventories = [
        {"workflow_runs": []},
        {"workflow_runs": [successor]},
    ]

    def api(method: str, endpoint: str, fields: dict[str, str] | None) -> dict[str, object] | None:
        assert endpoint.endswith(
            "/actions/workflows/321915839/runs?event=workflow_dispatch&per_page=100"
        ) or endpoint.endswith("/actions/workflows/prospective-deep-scheduler.yml/dispatches")
        calls.append((method, fields))
        if method == "POST":
            raise control_error("ambiguous dispatch result")
        return inventories.pop(0)

    result = module["reconcile_successor"](
        repository="dddur75/robin-stades-ng",
        mode="collect",
        generation=GENERATION,
        chain_id="123",
        parent_run_id="122",
        sequence=2,
        successor_title=successor["display_title"],
        active_prefix=None,
        api=api,
        sleeper=lambda _seconds: None,
    )

    posts = [fields for method, fields in calls if method == "POST"]
    assert result == {"skipped_active": False, "successor": successor}
    assert len(posts) == 1
    assert posts[0] == {
        "ref": "main",
        "inputs[mode]": "collect",
        "inputs[origin]": "relay",
        "inputs[generation]": GENERATION,
        "inputs[chain_id]": "123",
        "inputs[parent_run_id]": "122",
        "inputs[sequence]": "2",
    }


def test_successor_control_merges_every_inventory_page_before_deciding() -> None:
    module = _successor_control()
    active = {
        "id": 202,
        "display_title": f"robin-collect-relay-{GENERATION}-200-2",
        "status": "waiting",
    }

    merged = module["_merge_inventory_pages"](
        [
            {
                "total_count": 2,
                "workflow_runs": [
                    {
                        "id": 201,
                        "display_title": "unrelated-run",
                        "status": "completed",
                    }
                ],
            },
            {"total_count": 2, "workflow_runs": [active]},
        ]
    )

    posts = 0

    def api(
        method: str, _endpoint: str, _fields: dict[str, str] | None
    ) -> dict[str, object] | None:
        nonlocal posts
        if method == "POST":
            posts += 1
            return None
        return merged

    result = module["reconcile_successor"](
        repository="dddur75/robin-stades-ng",
        mode="collect",
        generation=GENERATION,
        chain_id="203",
        parent_run_id="203",
        sequence=1,
        successor_title=f"robin-collect-relay-{GENERATION}-203-1",
        active_prefix=f"robin-collect-relay-{GENERATION}-",
        api=api,
        sleeper=lambda _seconds: None,
    )

    assert result == {"skipped_active": True, "successor": None}
    assert posts == 0


def test_successor_control_requests_the_complete_paginated_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _successor_control()
    observed: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='[{"total_count":0,"workflow_runs":[]}]',
            stderr="",
        )

    monkeypatch.setattr(module["subprocess"], "run", run)
    result = module["_gh_api"](
        "GET",
        "repos/dddur75/robin-stades-ng/actions/workflows/321915839/runs",
        None,
    )

    assert result == {"total_count": 0, "workflow_runs": []}
    assert observed == [
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "repos/dddur75/robin-stades-ng/actions/workflows/321915839/runs",
        ]
    ]


@pytest.mark.parametrize(
    "pages",
    [
        [{"total_count": [], "workflow_runs": []}],
        [{"total_count": 1, "workflow_runs": [{"id": [], "status": "waiting"}]}],
        [
            {"total_count": 2, "workflow_runs": [{"id": 1}]},
            {"total_count": 1, "workflow_runs": [{"id": 2}]},
        ],
    ],
)
def test_successor_control_rejects_invalid_paginated_inventory(
    pages: object,
) -> None:
    module = _successor_control()
    with pytest.raises(module["GitHubControlError"]):
        module["_merge_inventory_pages"](pages)


def test_successor_control_bounds_failures_and_never_posts_twice() -> None:
    module = _successor_control()
    control_error = module["GitHubControlError"]

    for fail_after_post, expected_gets, expected_posts in (
        (False, 3, 0),
        (True, 4, 1),
    ):
        gets = 0
        posts = 0

        def api(
            method: str, _endpoint: str, _fields: dict[str, str] | None
        ) -> dict[str, object] | None:
            nonlocal gets, posts
            if method == "POST":
                posts += 1
                return None
            gets += 1
            if fail_after_post and gets == 1:
                return {"workflow_runs": []}
            raise control_error("control read failed")

        with pytest.raises(control_error):
            module["reconcile_successor"](
                repository="dddur75/robin-stades-ng",
                mode="collect",
                generation=GENERATION,
                chain_id="123",
                parent_run_id="122",
                sequence=2,
                successor_title=f"robin-collect-relay-{GENERATION}-123-2",
                active_prefix=None,
                api=api,
                sleeper=lambda _seconds: None,
            )
        assert gets == expected_gets
        assert posts == expected_posts


@pytest.mark.parametrize("first_seed", ["bootstrap", "watchdog"])
def test_successor_control_serialized_seeds_create_only_one_chain(first_seed: str) -> None:
    module = _successor_control()
    runs: list[dict[str, object]] = []
    posts = 0

    def api(method: str, _endpoint: str, fields: dict[str, str] | None) -> dict[str, object] | None:
        nonlocal posts
        if method == "POST":
            posts += 1
            assert fields is not None
            runs.append(
                {
                    "id": 900 + posts,
                    "display_title": (
                        "robin-collect-relay-"
                        f"{fields['inputs[generation]']}-{fields['inputs[chain_id]']}-1"
                    ),
                    "status": "waiting",
                }
            )
            return None
        return {"workflow_runs": list(runs)}

    seeds = {
        "bootstrap": ("1001", f"robin-collect-relay-{GENERATION}-1001-1"),
        "watchdog": ("1002", f"robin-collect-relay-{GENERATION}-1002-1"),
    }
    second_seed = "watchdog" if first_seed == "bootstrap" else "bootstrap"
    results = []
    for seed in (first_seed, second_seed):
        chain_id, title = seeds[seed]
        results.append(
            module["reconcile_successor"](
                repository="dddur75/robin-stades-ng",
                mode="collect",
                generation=GENERATION,
                chain_id=chain_id,
                parent_run_id=chain_id,
                sequence=1,
                successor_title=title,
                active_prefix=f"robin-collect-relay-{GENERATION}-",
                api=api,
                sleeper=lambda _seconds: None,
            )
        )

    assert posts == 1
    assert len(runs) == 1
    assert results[0]["skipped_active"] is False
    assert results[1] == {"skipped_active": True, "successor": None}


def test_successor_control_rejects_empty_or_duplicate_observation_after_one_post() -> None:
    module = _successor_control()
    control_error = module["GitHubControlError"]
    title = f"robin-collect-relay-{GENERATION}-123-2"

    for duplicate in (False, True):
        gets = 0
        posts = 0

        def api(
            method: str, _endpoint: str, _fields: dict[str, str] | None
        ) -> dict[str, object] | None:
            nonlocal gets, posts
            if method == "POST":
                posts += 1
                return None
            gets += 1
            if gets == 1 or not duplicate:
                return {"workflow_runs": []}
            return {
                "workflow_runs": [
                    {"id": 1, "display_title": title, "status": "waiting"},
                    {"id": 2, "display_title": title, "status": "waiting"},
                ]
            }

        with pytest.raises(control_error):
            module["reconcile_successor"](
                repository="dddur75/robin-stades-ng",
                mode="collect",
                generation=GENERATION,
                chain_id="123",
                parent_run_id="122",
                sequence=2,
                successor_title=title,
                active_prefix=None,
                api=api,
                sleeper=lambda _seconds: None,
            )
        assert posts == 1
        assert gets == (2 if duplicate else 31)
