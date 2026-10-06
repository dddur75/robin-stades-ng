from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/prospective-deep-scheduler.yml"
GENERATION = "4c150973fc3d486e3738f80716019839ac2c4126644849d336e267e6929e6d87"


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
    assert jobs["watchdog"]["permissions"] == {"actions": "write"}
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
    watchdog = jobs["watchdog"]["steps"][0]
    assert "inputs[sequence]=1" in bootstrap["run"]
    assert '[[ "$GITHUB_ACTOR" == "dddur75" ]]' in bootstrap["run"]
    assert '[[ "$GITHUB_ACTOR" == "github-actions[bot]" ]]' in relay["run"]
    assert '[[ "$SEQUENCE" == "2" ]]' in relay["run"]
    assert '[[ "$SEQUENCE" == "1" ]]' in relay["run"]
    assert "next_sequence" in relay["run"]
    assert "dispatches" in relay["run"]
    assert "actions/runs/$PARENT_RUN_ID/jobs" in relay["run"]
    assert '.name == "relay" and .conclusion == "success"' in relay["run"]
    assert '[[ "$CHAIN_ID" == "$PARENT_RUN_ID" ]]' in relay["run"]
    assert "robin-$MODE-bootstrap-$GENERATION-0-0" in relay["run"]
    assert "robin-watchdog-schedule-none-$PARENT_RUN_ID-0" in relay["run"]
    assert "previous_sequence" in relay["run"]
    assert "robin-$MODE-relay-$GENERATION-$CHAIN_ID-$previous_sequence" in relay["run"]
    assert '.head_sha <<<"$parent"' in relay["run"]
    assert '.run_attempt <<<"$parent"' in relay["run"]
    assert "dispatches" in watchdog["run"]
    assert 'prefix "robin-collect-relay-$EXPECTED_GENERATION-"' in watchdog["run"]
    assert '.status == "requested"' in bootstrap["run"]
    assert '.status == "requested"' in watchdog["run"]
    for step in (bootstrap, relay, watchdog):
        assert "successor_title=" in step["run"]
        assert "existing_count=" in step["run"]
        assert '[[ "$existing_count" == "0" ]]' in step["run"]
        assert "observed_count=" in step["run"]
        assert '[[ "$observed_count" == "1" ]]' in step["run"]
        assert "for _ in {1..30}" in step["run"]
        assert "secrets." not in yaml.safe_dump(step)
    assert relay["run"].index('[[ "$observed_count" == "1" ]]') < relay["run"].index(
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
        "watchdog": jobs["watchdog"]["steps"][0],
        "relay": next(step for step in jobs["relay"]["steps"] if step.get("id") == "relay"),
    }

    for job_name, step in control_steps.items():
        command = step["run"]
        assert "read_gh_json()" in command, job_name
        assert "for attempt in 1 2 3" in command, job_name
        assert 'payload="$(gh api "$endpoint")"' in command, job_name
        assert "jq -e ." in command, job_name
        assert "GitHub API JSON read failed after 3 attempts" in command, job_name
        assert "gh api --jq" not in command, job_name
        assert command.count("gh api ") == 2, job_name
        assert command.count("gh api --method POST --silent") == 1, job_name
        assert "dispatch_exit=0" in command, job_name
        assert "|| dispatch_exit=$?" in command, job_name
        assert "reconciling exact successor title without retry" in command, job_name
        assert command.index("gh api --method POST --silent") < command.index(
            '[[ "$observed_count" == "1" ]]'
        )
        assert command.index("dispatch_exit=0") < command.index("gh api --method POST --silent")


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
    watchdog_command = workflow["jobs"]["watchdog"]["steps"][0]["run"]
    assert "EXPECTED_EXPIRES_AT" in workflow["jobs"]["watchdog"]["steps"][0]["env"]
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


def test_capture_gates_exact_main_authority_and_retired_provider_routes() -> None:
    workflow = _workflow()
    gate = next(step for step in workflow["jobs"]["capture"]["steps"] if step.get("id") == "gate")
    command = gate["run"]
    assert "current_main_sha" in command
    assert '[[ "$GITHUB_SHA" == "$current_main_sha" ]]' in command
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
