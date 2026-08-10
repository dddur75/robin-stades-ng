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


def test_windows_producer_precedes_linux_consumers() -> None:
    jobs = load("ci.yml")["jobs"]  # type: ignore[index]
    producer = jobs["frozen-evidence-windows"]  # type: ignore[index]
    assert producer["runs-on"] == "windows-latest"
    assert jobs["chronos-postgresql-profiles"]["needs"] == "frozen-evidence-windows"  # type: ignore[index]
    assert set(jobs["tests"]["needs"]) == {  # type: ignore[index]
        "frozen-evidence-windows",
        "chronos-postgresql-profiles",
    }
    assert set(jobs["visual-regression"]["needs"]) == {  # type: ignore[index]
        "frozen-evidence-windows",
        "tests",
    }


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
    assert "needs.chronos-postgresql-profiles.result" in serialized
    assert serialized.count('= "success"') == 2


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
    for job_name in ("frozen-evidence-windows", "tests", "visual-regression"):
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
        for line in (ROOT / "requirements-chronos-canary.lock").read_text(
            encoding="utf-8"
        ).splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lock_lines) == 27
    assert all("==" in line and "--hash=sha256:" in line for line in lock_lines)
    assert 'requires = ["setuptools==84.0.0"]' in (
        ROOT / "pyproject.toml"
    ).read_text(encoding="utf-8")


def test_chronos_postgres_services_are_digest_pinned() -> None:
    expected = (
        "postgres:16.14-alpine@sha256:"
        "57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
    )
    canonical = load("ci.yml")["jobs"]["tests"]  # type: ignore[index]
    specialized = load("chronos-bootstrap-ci-v3.yml")["jobs"]["tests"]  # type: ignore[index]
    assert canonical["services"]["postgres"]["image"] == expected  # type: ignore[index]
    assert specialized["services"]["postgres"]["image"] == expected  # type: ignore[index]
