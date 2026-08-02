from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
CONFIG = ROOT / "configs" / "historical-deep-data-harvest-v1.json"
PHASE_FILES = {
    number: next(WORKFLOWS.glob(f"{number}-historical-deep-*.yml"))
    for number in range(70, 79)
}
SHARD_FILES = tuple(sorted(WORKFLOWS.glob("74[a-d]-historical-deep-*.yml")))
CONTROLLER = WORKFLOWS / "79-historical-deep-night-controller.yml"
DIAGNOSTIC = WORKFLOWS / "80-historical-deep-replay-diagnostic.yml"
BOOTSTRAP = WORKFLOWS / "historical-backfill.yml"
CI = WORKFLOWS / "ci.yml"

R2_SECRETS = {
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
}
PROVIDER_SECRETS = {"API_FOOTBALL_KEY", *R2_SECRETS}
SAFETY_ENV = {
    "STORAGE_PAUSED": "true",
    "P3_P4_PAUSED": "true",
    "PRODUCTION_LOCKED": "true",
    "REAL_BETS": "false",
    "NO_BET_DEFAULT": "true",
    "PROMOTION_LOCKED": "true",
    "SOCIAL_PUBLISHING_ENABLED": "false",
    "DEMO_MODE_ENABLED": "false",
    "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": "false",
    "THE_ODDS_API_HISTORICAL_CREDITS": "false",
}
PROVIDER_JOBS = (
    "census",
    "fixture-p0-a",
    "fixture-p0-b",
    "fixture-p0-c",
    "players-p0-a",
    "players-p0-b",
    "injuries-p0",
    "fixture-p1",
    "players-p1",
    "injuries-p1",
    "fixture-p2",
    "players-p2",
    "injuries-p2",
)
OFFLINE_JOBS = (
    "replay-current",
    "replay-p0",
    "quality-p0",
    "replay-p1",
    "quality-p1",
    "replay-final",
    "quality-final",
    "features",
    "backtest",
    "report",
    "coverage-proof",
)


def _load(path: Path) -> tuple[str, dict[str, object]]:
    text = path.read_text("utf-8")
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict)
    return text, loaded


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def _sequence(value: object) -> Sequence[object]:
    assert isinstance(value, Sequence)
    assert not isinstance(value, (str, bytes))
    return value


def _workflow_call(workflow: Mapping[str, object]) -> Mapping[str, object]:
    # PyYAML follows YAML 1.1 and may parse the plain key "on" as True.
    triggers = workflow.get("on", workflow.get(True))
    return _mapping(_mapping(triggers)["workflow_call"])


def _only_job(workflow: Mapping[str, object]) -> Mapping[str, object]:
    jobs = _mapping(workflow["jobs"])
    assert len(jobs) == 1
    return _mapping(next(iter(jobs.values())))


def _steps(job: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(step) for step in _sequence(job["steps"]))


def test_all_historical_deep_yaml_and_json_contracts_parse() -> None:
    files = [*PHASE_FILES.values(), *SHARD_FILES, CONTROLLER, DIAGNOSTIC, BOOTSTRAP, CI]
    assert len(set(files)) == 17
    for path in files:
        _, workflow = _load(path)
        assert _mapping(workflow["jobs"])
    contract = json.loads(CONFIG.read_text("utf-8"))
    assert contract["schema_version"] == "historical-deep-data-harvest-v1"
    assert contract["storage"]["mode"] == "R2_FIRST_APPEND_ONLY"
    assert contract["storage"]["raw_payloads_in_git"] is False
    assert contract["storage"]["deletions_allowed"] is False


def test_full_corpus_reducers_have_a_usable_timeout_budget() -> None:
    reducer_jobs = (
        (WORKFLOWS / "74c-historical-deep-projection-reducer.yml", "reducer"),
        (WORKFLOWS / "74d-historical-deep-idempotent-replay.yml", "idempotence"),
    )
    for path, job_name in reducer_jobs:
        _, workflow = _load(path)
        job = _mapping(_mapping(workflow["jobs"])[job_name])
        assert 90 <= int(str(job["timeout-minutes"])) <= 110


def test_full_corpus_reducers_use_cross_attempt_artifact_listing() -> None:
    reducers = (
        (WORKFLOWS / "74c-historical-deep-projection-reducer.yml", "reducer"),
        (WORKFLOWS / "74d-historical-deep-idempotent-replay.yml", "idempotence"),
    )
    for path, job_name in reducers:
        _, workflow = _load(path)
        assert workflow["permissions"] == {"actions": "read", "contents": "read"}
        job = _mapping(_mapping(workflow["jobs"])[job_name])
        pattern_download = next(
            step
            for step in _steps(job)
            if step.get("uses") == "actions/download-artifact@v4"
            and "pattern" in _mapping(step["with"])
        )
        download_with = _mapping(pattern_download["with"])
        assert download_with["github-token"] == "${{ github.token }}"
        assert download_with["repository"] == "${{ github.repository }}"
        assert download_with["run-id"] == "${{ github.run_id }}"

    for path in (BOOTSTRAP, CONTROLLER, PHASE_FILES[74]):
        _, workflow = _load(path)
        assert _mapping(workflow["permissions"])["actions"] == "read"


def test_workflows_70_to_78_are_bounded_serialized_and_fail_closed() -> None:
    for number, path in PHASE_FILES.items():
        text, workflow = _load(path)
        expected_permissions = {"contents": "read"}
        if number == 74:
            expected_permissions["actions"] = "read"
        assert workflow["permissions"] == expected_permissions
        assert workflow["concurrency"] == {
            "group": "historical-deep-r2-state",
            "cancel-in-progress": False,
        }
        if number == 74:
            jobs = _mapping(workflow["jobs"])
            assert tuple(jobs) == (
                "inventory",
                "replay-segments",
                "reducer",
                "idempotence",
                "diagnostic",
            )
            assert all(
                str(_mapping(jobs[name])["uses"]).startswith(
                    "./.github/workflows/74"
                )
                for name in ("inventory", "replay-segments", "reducer", "idempotence")
            )
            assert _mapping(jobs["diagnostic"])["uses"] == (
                "./.github/workflows/80-historical-deep-replay-diagnostic.yml"
            )
            assert all(
                _mapping(jobs[name])["if"] == "${{ inputs.diagnostic_task_id == '' }}"
                for name in ("inventory", "replay-segments", "reducer", "idempotence")
            )
            assert _mapping(jobs["diagnostic"])["if"] == (
                "${{ inputs.diagnostic_task_id != '' }}"
            )
            assert "API_FOOTBALL_KEY" not in text
            continue
        job = _only_job(workflow)
        assert 90 <= int(str(job["timeout-minutes"])) <= 110
        env = _mapping(job["env"])
        assert all(env.get(name) == value for name, value in SAFETY_ENV.items())
        assert "historical-state-persist" not in text
        assert "DATABASE_URL" not in text
        assert "ODDS_API_KEY" not in text
        assert "contents: write" not in text

        steps = _steps(job)
        checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
        assert _mapping(checkout["with"])["persist-credentials"] is False
        upload = next(
            step for step in steps if step.get("uses") == "actions/upload-artifact@v4"
        )
        upload_with = _mapping(upload["with"])
        assert upload["if"] == "always()"
        assert upload_with["if-no-files-found"] == "error"
        assert upload_with["retention-days"] == 90
        artifact_name = str(upload_with["name"])
        assert "${{ github.run_id }}" in artifact_name
        assert "${{ github.run_attempt }}" in artifact_name

        if number >= 74:
            assert env["API_FOOTBALL_CALLS_ALLOWED"] == "0"
            assert env["ODDS_API_CREDITS_ALLOWED"] == "0"


def test_only_collection_workflows_receive_provider_secret() -> None:
    for number, path in PHASE_FILES.items():
        text, workflow = _load(path)
        call = _workflow_call(workflow)
        declared = set(_mapping(call["secrets"]))
        expected = PROVIDER_SECRETS if number <= 73 else R2_SECRETS
        assert declared == expected
        if number == 74:
            assert "API_FOOTBALL_KEY" not in text
            assert all(
                set(_mapping(_mapping(job)["secrets"])) == R2_SECRETS
                for job in _mapping(workflow["jobs"]).values()
            )
            continue
        job = _only_job(workflow)
        assert not set(_mapping(job["env"])) & PROVIDER_SECRETS
        runner_step = next(
            step
            for step in _steps(job)
            if "scripts/run_historical_deep_harvest.py" in str(step.get("run", ""))
        )
        assert set(_mapping(runner_step["env"])) == expected
        if number <= 73:
            assert "API_FOOTBALL_KEY" in text
            assert "--max-calls" in text
            assert "--max-duration-minutes" in text
        else:
            assert "API_FOOTBALL_KEY" not in text
            assert "inputs.execute" not in text


def test_replay_diagnostic_is_provider_free_structural_and_serialized() -> None:
    text, workflow = _load(DIAGNOSTIC)
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "historical-deep-r2-diagnostic",
        "cancel-in-progress": False,
    }
    job = _only_job(workflow)
    env = _mapping(job["env"])
    assert all(env.get(name) == value for name, value in SAFETY_ENV.items())
    assert env["API_FOOTBALL_CALLS_ALLOWED"] == "0"
    assert env["ODDS_API_CREDITS_ALLOWED"] == "0"
    assert "API_FOOTBALL_KEY" not in text
    assert "DATABASE_URL" not in text
    call = _workflow_call(workflow)
    assert set(_mapping(call["secrets"])) == R2_SECRETS
    steps = _steps(job)
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
    assert _mapping(checkout["with"])["persist-credentials"] is False
    upload = next(
        step for step in steps if step.get("uses") == "actions/upload-artifact@v4"
    )
    assert upload["if"] == "always()"
    assert _mapping(upload["with"])["retention-days"] == 90
    runner = "\n".join(str(step.get("run", "")) for step in steps)
    assert " diagnose " in f" {runner} "
    assert "--task-id" in runner


def test_controller_has_p0_p1_p2_order_and_a_global_call_cap() -> None:
    text, controller = _load(CONTROLLER)
    assert controller["permissions"] == {"actions": "read", "contents": "read"}
    assert controller["concurrency"] == {
        "group": "historical-deep-night-controller",
        "cancel-in-progress": False,
    }
    assert "secrets: inherit" not in text
    jobs = _mapping(controller["jobs"])
    expected_chain = (
        ("census", "replay-current"),
        ("players-p0-a", "census"),
        ("players-p0-b", "players-p0-a"),
        ("fixture-p0-a", "players-p0-b"),
        ("fixture-p0-b", "fixture-p0-a"),
        ("fixture-p0-c", "fixture-p0-b"),
        ("injuries-p0", "fixture-p0-c"),
        ("replay-p0", "injuries-p0"),
        ("quality-p0", "replay-p0"),
        ("fixture-p1", ("injuries-p0", "quality-p0")),
        ("players-p1", "fixture-p1"),
        ("injuries-p1", "players-p1"),
        ("replay-p1", "injuries-p1"),
        ("quality-p1", "replay-p1"),
        ("fixture-p2", ("injuries-p1", "quality-p1")),
        ("players-p2", "fixture-p2"),
        ("injuries-p2", "players-p2"),
        ("replay-final", ("replay-current", "injuries-p2")),
        ("quality-final", "replay-final"),
        ("features", "quality-final"),
        ("backtest", "features"),
        ("report", ("replay-current", "backtest")),
        ("coverage-proof", "report"),
    )
    for job_name, prerequisite in expected_chain:
        actual = _mapping(jobs[job_name])["needs"]
        if isinstance(prerequisite, tuple):
            assert tuple(_sequence(actual)) == prerequisite
        else:
            assert actual == prerequisite
    for job_name in ("fixture-p2", "players-p2", "injuries-p2"):
        assert _mapping(_mapping(jobs[job_name])["with"])["priority"] == "P2"

    mission_call_cap = json.loads(CONFIG.read_text("utf-8"))["quota"][
        "mission_call_cap"
    ]
    total_calls = sum(
        int(str(_mapping(_mapping(jobs[name])["with"])["max_calls"]))
        for name in PROVIDER_JOBS
    )
    assert total_calls == 90_000
    assert total_calls <= mission_call_cap
    assert all(
        int(str(_mapping(_mapping(jobs[name])["with"])["max_duration_minutes"]))
        == 75
        for name in PROVIDER_JOBS
    )
    for name in PROVIDER_JOBS[1:]:
        condition = str(_mapping(jobs[name])["if"])
        assert "provider_stop" in condition
        assert "always()" in condition
    for name, quality_job in (
        ("fixture-p1", "quality-p0"),
        ("fixture-p2", "quality-p1"),
        ("features", "quality-final"),
    ):
        condition = str(_mapping(jobs[name])["if"])
        assert f"needs['{quality_job}'].outputs.status == 'COMPLETE'" in condition
    replay_final_condition = str(_mapping(jobs["replay-final"])["if"])
    assert "always()" in replay_final_condition
    assert "needs['replay-current'].result == 'success'" in replay_final_condition
    report_condition = str(_mapping(jobs["report"])["if"])
    assert "always()" in report_condition
    assert "needs['replay-current'].result == 'success'" in report_condition
    coverage_proof = _mapping(jobs["coverage-proof"])
    coverage_inputs = _mapping(coverage_proof["with"])
    assert coverage_inputs["source_code_revision"] == "${{ github.sha }}"
    assert coverage_inputs["source_run_token"] == (
        "${{ format('{0}:{1}', github.run_id, github.run_attempt) }}"
    )
    coverage_condition = str(coverage_proof["if"])
    assert "inputs.execute" in coverage_condition
    assert "needs.report.result == 'success'" in coverage_condition


def test_controller_passes_least_privilege_secrets() -> None:
    _, controller = _load(CONTROLLER)
    jobs = _mapping(controller["jobs"])
    for name in PROVIDER_JOBS:
        assert set(_mapping(_mapping(jobs[name])["secrets"])) == PROVIDER_SECRETS
    for name in OFFLINE_JOBS:
        assert set(_mapping(_mapping(jobs[name])["secrets"])) == R2_SECRETS


def test_repeated_collection_slices_have_unique_artifact_names() -> None:
    _, controller = _load(CONTROLLER)
    jobs = _mapping(controller["jobs"])
    reusable_numbers = (71, 72, 73, 74, 75)
    for number in reusable_numbers:
        _, workflow = _load(PHASE_FILES[number])
        call_inputs = _mapping(_workflow_call(workflow)["inputs"])
        assert _mapping(call_inputs["slice_id"]) == {
            "type": "string",
            "default": "standalone",
        }
        if number == 74:
            assert _mapping(call_inputs["continuation_of"])["default"] == (
                "30622258001:1"
            )
            continue
        upload = next(
            step
            for step in _steps(_only_job(workflow))
            if step.get("uses") == "actions/upload-artifact@v4"
        )
        artifact_name = str(_mapping(upload["with"])["name"])
        assert "${{ inputs.slice_id }}" in artifact_name

    for job_name, job_value in jobs.items():
        job = _mapping(job_value)
        workflow_path = str(job.get("uses", ""))
        if any(
            f"/{number}-historical-deep-" in workflow_path
            for number in reusable_numbers
        ):
            slice_id = _mapping(job["with"])["slice_id"]
            if job_name == "replay-current":
                assert slice_id == "current-r2-gate"
            else:
                assert slice_id == job_name

    _, quality_workflow = _load(PHASE_FILES[75])
    quality_call = _workflow_call(quality_workflow)
    assert set(_mapping(quality_call["outputs"])) == {"status"}
    quality_job = _only_job(quality_workflow)
    assert _mapping(quality_job["outputs"])["status"] == (
        "${{ steps.outcome.outputs.status }}"
    )


def test_branch_bootstrap_never_runs_legacy_persistence_or_inherits_secrets() -> None:
    text, workflow = _load(BOOTSTRAP)
    jobs = _mapping(workflow["jobs"])
    backfill = _mapping(jobs["backfill"])
    assert "inputs.priority != 'HISTORICAL_DEEP_V1'" in str(backfill["if"])
    assert "inputs.priority != 'HISTORICAL_DEEP_DIAGNOSTIC'" in str(backfill["if"])
    bootstrap = _mapping(jobs["historical-deep-night"])
    assert str(bootstrap["uses"]).endswith(
        "79-historical-deep-night-controller.yml"
    )
    assert _mapping(bootstrap["with"])["execute"] is True
    assert set(_mapping(bootstrap["secrets"])) == PROVIDER_SECRETS
    assert "secrets: inherit" not in text
    bootstrap_text = text[text.index("  historical-deep-night:") :]
    assert "DATABASE_URL" not in bootstrap_text
    assert "historical-state-persist" not in bootstrap_text
    diagnostic = _mapping(jobs["historical-deep-diagnostic"])
    assert diagnostic["uses"] == "./.github/workflows/74-historical-deep-replay.yml"
    assert set(_mapping(diagnostic["secrets"])) == R2_SECRETS
    diagnostic_inputs = _mapping(diagnostic["with"])
    assert diagnostic_inputs["continuation_of"] == "30622258001:1"
    assert diagnostic_inputs["run_purpose"] == "P0_CLOSURE_AND_SHARDED_REPLAY"
    assert diagnostic_inputs["diagnostic_task_id"] == "${{ inputs.endpoint }}"
    diagnostic_text = text[text.index("  historical-deep-diagnostic:") :]
    assert "API_FOOTBALL_KEY" not in diagnostic_text


def test_ci_has_an_isolated_strict_historical_deep_gate() -> None:
    _, workflow = _load(CI)
    job = _mapping(_mapping(workflow["jobs"])["historical-deep-quality"])
    assert job["permissions"] == {"contents": "read"}
    assert int(str(job["timeout-minutes"])) <= 20
    steps = _steps(job)
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
    assert _mapping(checkout["with"])["persist-credentials"] is False
    commands = "\n".join(str(step.get("run", "")) for step in steps)
    required_commands = (
        "python -m pytest -q tests/historical_deep",
        "python -m ruff check",
        "python -m mypy --strict",
        "python -m bandit -q -r",
        "python -m compileall -q",
        "src/robin/historical_deep",
        "tests/historical_deep",
        "scripts/run_historical_deep_harvest.py",
        "configs/historical-deep-data-harvest-v1.json",
        ".github/workflows",
        "python scripts/check_no_secrets.py",
        "python -m pip check",
    )
    assert all(command in commands for command in required_commands)
    assert "${{ secrets." not in commands
    runner = "scripts/run_historical_deep_harvest.py"
    for command_prefix in (
        "python -m ruff check",
        "python -m mypy --strict",
        "python -m bandit -q -r",
        "python -m compileall -q",
    ):
        command = next(
            str(step.get("run", ""))
            for step in steps
            if str(step.get("run", "")).startswith(command_prefix)
        )
        assert runner in command


def test_campaign_quota_and_safety_contract_is_fail_closed() -> None:
    contract = json.loads(CONFIG.read_text("utf-8"))
    assert contract["quota"]["mandatory_reserve_minimum"] == 20_000
    assert contract["quota"]["mandatory_reserve_fraction"] == 0.2
    assert contract["quota"]["mission_call_cap"] == 90_000
    assert contract["quota"]["checkpoint_max_calls"] == 250
    assert contract["quota"]["checkpoint_max_minutes"] == 5
    assert contract["safety"] == {
        "STORAGE_PAUSED": True,
        "P3_P4_PAUSED": True,
        "PRODUCTION_LOCKED": True,
        "REAL_BETS": False,
        "NO_BET_DEFAULT": True,
        "PROMOTION_LOCKED": True,
        "SOCIAL_PUBLISHING_ENABLED": False,
        "DEMO_MODE_ENABLED": False,
        "POSTGRESQL_PRODUCTION_DESTRUCTIVE_WRITES": False,
        "THE_ODDS_API_HISTORICAL_CREDITS": False,
    }
