from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _ci() -> str:
    return CI.read_text(encoding="utf-8")


def _pilot_job() -> str:
    return _ci().split("\n  jalon12-pilot:", maxsplit=1)[1]


def test_pilot_bridge_is_exact_branch_marker_and_post_ci_only() -> None:
    pilot = _pilot_job()
    assert "needs: tests" in pilot
    assert (
        "refs/heads/codex/jalon-12-prospective-deep-data-observatory"
        in pilot
    )
    assert "[run-j12-pilot]" in pilot
    assert "github.event_name == 'push'" in pilot


def test_pilot_bridge_cannot_be_cancelled_or_rerun_after_provider_calls() -> None:
    document = _ci()
    pilot = _pilot_job()
    assert "'quality-jalon12-pilot'" in document
    assert "cancel-in-progress: false" in pilot
    assert 'GITHUB_RUN_ATTEMPT}" != "1"' in pilot


def test_pilot_secrets_are_step_scoped_and_absent_from_frontend_steps() -> None:
    pilot = _pilot_job()
    job_env, steps = pilot.split("\n    steps:", maxsplit=1)
    assert "secrets." not in job_env
    frontend = steps.split(
        "- name: Construire le snapshot prospectif Robin Live",
        maxsplit=1,
    )[1]
    assert "secrets." not in frontend


def test_pilot_network_calls_are_one_shot_and_due_only() -> None:
    pilot = _pilot_job()
    assert pilot.count("--max-attempts 1") >= 3
    assert "Capturer seulement les fenetres actuellement dues" in pilot
    assert "--estimate-file" in pilot


def test_pilot_replay_has_zero_provider_credentials_and_compact_artifact() -> None:
    pilot = _pilot_job()
    replay = pilot.split(
        "- name: Rejouer R2 sans fournisseur et evaluer les gates",
        maxsplit=1,
    )[1]
    replay_step, remainder = replay.split(
        "- name: Construire le snapshot prospectif Robin Live",
        maxsplit=1,
    )
    assert 'API_FOOTBALL_KEY: ""' in replay_step
    assert 'ODDS_API_KEY: ""' in replay_step
    assert 'API_FOOTBALL_CALLS_ALLOWED: "0"' in replay_step
    artifact = remainder.split("uses: actions/upload-artifact@v4", maxsplit=1)[1]
    assert "artifacts/prospective-observatory/*.json" in artifact
    assert "payload" not in artifact.casefold()
