from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED_CONTEXTS = {
    "Historical Deep — contrat cache-only",
    "Jalon 10 - entrees de preuve gelees",
    "tests",
    "Robin Experience — preuves visuelles",
}


def load(name: str) -> dict[str, object]:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_only_canonical_workflow_publishes_required_contexts() -> None:
    canonical = load("ci.yml")
    specialized = load("chronos-bootstrap-ci-v3.yml")
    canonical_names = {
        str(job.get("name", job_id))
        for job_id, job in canonical["jobs"].items()  # type: ignore[union-attr]
    }
    specialized_names = {
        str(job.get("name", job_id))
        for job_id, job in specialized["jobs"].items()  # type: ignore[union-attr]
    }
    assert REQUIRED_CONTEXTS <= canonical_names
    assert not (REQUIRED_CONTEXTS & specialized_names)
    assert "tests (${{ matrix.admin-profile }})" in specialized_names

    historical = canonical["jobs"]["historical-deep-quality"]  # type: ignore[index]
    historical_checkout = historical["steps"][0]  # type: ignore[index]
    assert historical_checkout["uses"] == (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    )
    assert historical_checkout["with"] == {
        "persist-credentials": False,
        "ref": "${{ github.event.pull_request.head.sha || github.sha }}",
    }
    historical_commands = "\n".join(
        str(step.get("run", ""))
        for step in historical["steps"]  # type: ignore[index]
    )
    assert "git checkout" not in historical_commands

    exact_entrypoint = canonical["jobs"]["chronos-exact-workflow-entrypoint"]  # type: ignore[index]
    exact_commands = "\n".join(
        str(step.get("run", ""))
        for step in exact_entrypoint["steps"]  # type: ignore[index]
    )
    assert "test_exact_module_command_with_malformed_run_id_still_writes_report" in exact_commands
    assert all("env" not in step for step in exact_entrypoint["steps"])  # type: ignore[index]


def test_windows_producer_precedes_linux_consumers() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    producer = jobs["frozen-evidence-windows"]  # type: ignore[index]
    assert producer["runs-on"] == "windows-latest"
    assert jobs["chronos-postgresql-profiles"]["needs"] == "frozen-evidence-windows"  # type: ignore[index]
    assert set(jobs["tests"]["needs"]) == {  # type: ignore[index]
        "bounded-live-canary-ubuntu",
        "bounded-live-canary-windows",
        "frozen-evidence-windows",
        "chronos-postgresql-profiles",
        "chronos-end-to-end-live-path-replay",
        "chronos-residual-fault-matrix",
        "chronos-exact-workflow-entrypoint",
        "historical-authority-workflows-disabled",
    }
    assert set(jobs["visual-regression"]["needs"]) == {  # type: ignore[index]
        "frozen-evidence-windows",
        "tests",
    }


def test_bounded_live_canary_windows_job_proves_storage_link_semantics() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    job = jobs["bounded-live-canary-windows"]  # type: ignore[index]

    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] == 12
    assert job["permissions"] == {"contents": "read"}
    assert job["env"] == {"ROBIN_REQUIRE_WINDOWS_STORAGE_LINKS": "1"}
    assert all(
        step.get("shell") == "pwsh"
        for step in job["steps"]  # type: ignore[index]
        if "run" in step
    )
    assert all("continue-on-error" not in step for step in job["steps"])  # type: ignore[index]

    checkout, setup_python = job["steps"][:2]  # type: ignore[index]
    assert checkout["uses"] == ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262")
    assert checkout["with"] == {
        "persist-credentials": False,
        "ref": "${{ github.event.pull_request.head.sha || github.sha }}",
    }
    assert setup_python["uses"] == ("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065")
    assert setup_python["with"]["python-version"] == "3.12.10"

    steps = {
        step["name"]: step
        for step in job["steps"]
        if "name" in step  # type: ignore[index]
    }
    assert steps["Vérifier les artifacts synthétiques bornés"]["run"].splitlines() == [
        "python tools/data-sourcing/build_capture_harness_artifacts.py --check",
        "python tools/data-sourcing/build_bounded_live_canary_artifacts.py --check",
    ]

    proof = steps["Prouver les junctions et hardlinks Windows"]["run"]
    for required_guard in (
        "$env:RUNNER_TEMP",
        "WINDOWS_RUNNER_TEMP_REQUIRED",
        "github.run_id",
        "github.run_attempt",
        "WINDOWS_FS_PROOF_ROOT_OUTSIDE_RUNNER_TEMP",
        "WINDOWS_FS_PROOF_ROOT_ALREADY_EXISTS",
        "New-Item -ItemType Junction",
        "[IO.FileAttributes]::ReparsePoint",
        "WINDOWS_JUNCTION_REPARSE_PROOF_FAILED",
        "New-Item -ItemType HardLink",
        "a.st_ino == b.st_ino",
        "a.st_nlink >= 2",
        "Remove-Item -LiteralPath $proofRoot -Recurse -Force",
    ):
        assert required_guard in proof
    assert proof.index("WINDOWS_FS_PROOF_ROOT_OUTSIDE_RUNNER_TEMP") < proof.index(
        "New-Item -ItemType Directory -Path $proofRoot"
    )
    assert proof.index("New-Item -ItemType Junction") < proof.index(
        "[IO.FileAttributes]::ReparsePoint"
    )
    assert proof.index("New-Item -ItemType HardLink") < proof.index("a.st_ino == b.st_ino")

    capture_test = steps["Compiler et tester la capacité bornée"]["run"]
    assert "python -m pytest -q tests/capture" in capture_test
    assert "${{ secrets." not in yaml.safe_dump(job)


def test_manifest_producer_and_consumers_share_available_exact_python() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    for job_name in ("frozen-evidence-windows", "tests", "visual-regression"):
        setup_steps = [
            step
            for step in jobs[job_name]["steps"]  # type: ignore[index]
            if str(step.get("uses", "")).startswith("actions/setup-python@")
        ]
        assert len(setup_steps) == 1
        assert setup_steps[0]["with"]["python-version"] == "3.12.10"


def test_exact_tests_gate_is_fail_closed_on_every_prerequisite() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    exact_tests = jobs["tests"]  # type: ignore[index]
    assert exact_tests["if"] == "${{ always() }}"
    serialized = yaml.safe_dump(exact_tests)
    assert "needs.frozen-evidence-windows.result" in serialized
    assert "needs.bounded-live-canary-ubuntu.result" in serialized
    assert "needs.bounded-live-canary-windows.result" in serialized
    assert "needs.chronos-postgresql-profiles.result" in serialized
    assert "needs.chronos-end-to-end-live-path-replay.result" in serialized
    assert "needs.chronos-residual-fault-matrix.result" in serialized
    assert "needs.chronos-exact-workflow-entrypoint.result" in serialized
    assert "needs.historical-authority-workflows-disabled.result" in serialized
    assert serialized.count('= "success"') == 8


def test_historical_authority_workflow_boundary_is_exact_and_fail_closed() -> None:
    job = load("ci.yml")["jobs"]["historical-authority-workflows-disabled"]  # type: ignore[index]
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    serialized = yaml.safe_dump(job)
    assert "disabled_manually" in serialized
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])  # type: ignore[index]
    for workflow_id, path in {
        319920551: ".github/workflows/historical-backfill.yml",
        327137040: ".github/workflows/79-historical-deep-night-controller.yml",
        327137044: ".github/workflows/81-historical-deep-coverage-proof-export.yml",
        329278452: ".github/workflows/82-p0-e1b-five-league-canary.yml",
        329420317: ".github/workflows/83-p0-e2-capability-sample.yml",
    }.items():
        assert f"assert_disabled {workflow_id} {path}" in commands
    assert "actions/workflows/${workflow_id}" in commands


def test_specialized_profiles_are_reusable_or_manual_only() -> None:
    specialized = load("chronos-bootstrap-ci-v3.yml")
    triggers = specialized.get("on", specialized.get(True))
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_call", "workflow_dispatch"}


def assert_external_actions_are_sha_pinned(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str) and not child.startswith("./"):
                assert len(child.rsplit("@", 1)[1]) == 40
            assert_external_actions_are_sha_pinned(child)
    elif isinstance(value, list):
        for child in value:
            assert_external_actions_are_sha_pinned(child)


def test_cleanroom_workflow_actions_are_sha_pinned() -> None:
    canonical_jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    for job_name in (
        "bounded-live-canary-ubuntu",
        "bounded-live-canary-windows",
        "historical-deep-quality",
        "frozen-evidence-windows",
        "tests",
        "visual-regression",
    ):
        assert_external_actions_are_sha_pinned(canonical_jobs[job_name])  # type: ignore[index]
    assert_external_actions_are_sha_pinned(load("chronos-bootstrap-ci-v3.yml"))
    assert_external_actions_are_sha_pinned(load("chronos-provider-free-canary-v3.yml"))


def test_linux_never_regenerates_frozen_parquet() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    for job_name in ("tests", "visual-regression"):
        commands = "\n".join(
            str(step.get("run", ""))
            for step in jobs[job_name]["steps"]  # type: ignore[index]
        )
        assert "build_hypothesis_evidence.py --git-blobs" not in commands
        assert "frozen_evidence_manifest.py verify" in commands
        for required in (
            "--expected-tree-sha",
            "--input",
            "--generator",
            "--dependency-lock",
        ):
            assert required in commands


def test_artifact_jobs_have_no_external_production_secrets() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    for job_name in ("frozen-evidence-windows", "tests", "visual-regression"):
        serialized = yaml.safe_dump(jobs[job_name])  # type: ignore[index]
        for forbidden in (
            "NEON_API_KEY",
            "NEON_BOOTSTRAP_DATABASE_URL",
            "R2_",
            "API_FOOTBALL",
            "ODDS_API_KEY",
        ):
            assert forbidden not in serialized


def test_evidence_writer_dependency_is_exactly_pinned() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "requirements-evidence.lock").read_text(encoding="utf-8")
    assert "pyarrow==25.0.0" in requirements
    assert '"pyarrow==25.0.0"' in pyproject
    assert "pyarrow==25.0.0" in lock
    assert lock.count("--hash=sha256:") == 6
    producer = yaml.safe_dump(load("ci.yml")["jobs"]["frozen-evidence-windows"])  # type: ignore[index]
    assert "--require-hashes -r requirements-evidence.lock" in producer


def test_production_canary_supply_chain_is_immutable() -> None:
    canary = load("chronos-provider-free-canary-v3.yml")["jobs"]["canary"]  # type: ignore[index]
    serialized = yaml.safe_dump(canary)
    assert "requirements-chronos-canary.lock" in serialized
    assert "--require-hashes" in serialized
    assert "--only-binary=:all:" in serialized
    assert "requirements.txt" not in serialized
    assert "pip install --no-deps -e ." not in serialized
    assert "PYTHONPATH" in serialized
    lock_lines = [
        line
        for line in (ROOT / "requirements-chronos-canary.lock")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lock_lines) == 27
    assert all("==" in line and "--hash=sha256:" in line for line in lock_lines)
    assert 'requires = ["setuptools==84.0.0"]' in (ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_chronos_postgres_services_are_digest_pinned() -> None:
    expected = (
        "postgres:16.14-alpine@sha256:"
        "57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
    )
    canonical = load("ci.yml")["jobs"]["tests"]  # type: ignore[index]
    specialized = load("chronos-bootstrap-ci-v3.yml")["jobs"]["tests"]  # type: ignore[index]
    assert canonical["services"]["postgres"]["image"] == expected  # type: ignore[index]
    assert specialized["services"]["postgres"]["image"] == expected  # type: ignore[index]
