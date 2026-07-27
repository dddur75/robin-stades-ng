from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
WORKFLOWS = (
    "prospective-fixture-registry.yml",
    "prospective-deep-scheduler.yml",
    "prospective-player-capture.yml",
    "prospective-lineup-capture.yml",
    "prospective-odds-capture.yml",
    "prospective-r2-replay-audit.yml",
    "prospective-gate-report.yml",
)
CAPTURE_WORKFLOWS = (
    "prospective-player-capture.yml",
    "prospective-lineup-capture.yml",
    "prospective-odds-capture.yml",
)


def _workflow(name: str) -> str:
    return (WORKFLOW_ROOT / name).read_text(encoding="utf-8")


def test_all_prospective_workflows_are_isolated_fail_closed_and_append_only() -> None:
    required = (
        "group: prospective-deep-state",
        "cancel-in-progress: false",
        'PROSPECTIVE_POLICY: "configs/prospective_observatory_v1.json"',
        'STORAGE_PAUSED: "true"',
        'P3_P4_PAUSED: "true"',
        'PRODUCTION_LOCKED: "true"',
        'REAL_BETS: "false"',
        'NO_BET_DEFAULT: "true"',
        'SOCIAL_PUBLISHING_ENABLED: "false"',
        'DEMO_MODE_ENABLED: "false"',
        "contents: read",
    )
    forbidden = (
        "historical-state",
        "shadow-state",
        "data/historical",
        "historical-data",
        "delete-object",
        "delete_object",
        "contents: write",
    )
    for name in WORKFLOWS:
        workflow = _workflow(name)
        assert "workflow_dispatch:" in workflow
        assert all(value in workflow for value in required), name
        assert all(value not in workflow.casefold() for value in forbidden), name
        assert '--policy "$PROSPECTIVE_POLICY"' in workflow
        assert "alembic upgrade head" in workflow
        assert 'alembic current | grep -q "0009"' in workflow


def test_central_policy_owns_provider_caps_reserves_and_markets() -> None:
    policy = json.loads(
        (ROOT / "configs" / "prospective_observatory_v1.json").read_text(
            encoding="utf-8"
        )
    )
    budgets = policy["provider_budgets"]
    assert budgets == {
        "api_football_max_calls_total": 5000,
        "odds_api_max_credits_total": 250,
        "odds_api_internal_safety_reserve": 2,
        "api_football_provider_reserve": 5000,
        "odds_api_provider_reserve": 4000,
        "odds_api_near_kickoff_reserve": 80,
    }
    assert policy["markets"] == ["1X2", "OVER_UNDER_2_5"]


def test_programmed_frequency_is_never_more_frequent_than_hourly() -> None:
    for name in WORKFLOWS:
        workflow = _workflow(name)
        crons = re.findall(r'cron:\s*"([^"]+)"', workflow)
        assert crons, name
        for cron in crons:
            minute, hour, *_ = cron.split()
            assert not minute.startswith("*/"), (name, cron)
            assert hour == "*" or hour.isdigit(), (name, cron)


def test_capture_workflows_estimate_before_explicit_bounded_execution() -> None:
    for name in CAPTURE_WORKFLOWS:
        workflow = _workflow(name)
        estimate = workflow.index("--estimate")
        execute = workflow.index("--execute")
        assert estimate < execute
        assert "--estimate-file" in workflow
        # Each hourly run performs one physical request. Up to three durable
        # hourly attempts are allowed while the original window stays open.
        assert "--max-attempts 3" in workflow
        assert "github.event_name == 'schedule' || inputs.execute" in workflow
        assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in workflow
        assert "R2_BUCKET_NAME: ${{ secrets.R2_BUCKET_NAME }}" in workflow
        assert "ROBIN_DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
        assert "alembic upgrade head" in workflow


def test_fixture_registry_is_dynamic_bounded_and_persisted_r2_first() -> None:
    workflow = _workflow("prospective-fixture-registry.yml")
    assert "--competition \"Ligue 1\"" in workflow
    assert '--policy "$PROSPECTIVE_POLICY"' in workflow
    assert workflow.index("--estimate") < workflow.index("--execute")
    assert "API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}" in workflow
    assert "R2_ACCOUNT_ID: ${{ secrets.R2_ACCOUNT_ID }}" in workflow
    assert "ROBIN_DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
    assert "alembic upgrade head" in workflow


def test_odds_scope_and_zero_cost_replay_are_explicit() -> None:
    odds = _workflow("prospective-odds-capture.yml")
    replay = _workflow("prospective-r2-replay-audit.yml")
    gates = _workflow("prospective-gate-report.yml")

    assert '--policy "$PROSPECTIVE_POLICY"' in odds
    assert "ODDS_API_KEY: ${{ secrets.ODDS_API_KEY }}" in odds
    assert "--max-objects" not in replay
    assert "Rejouer intégralement R2 sans fournisseur" in replay
    for workflow in (replay, gates):
        assert 'API_FOOTBALL_CALLS_ALLOWED: "0"' in workflow
        assert 'ODDS_API_CREDITS_ALLOWED: "0"' in workflow
        assert "API_FOOTBALL_KEY" not in workflow
        assert "ODDS_API_KEY" not in workflow


def test_workflows_publish_only_compact_json_reports() -> None:
    for name in WORKFLOWS:
        workflow = _workflow(name)
        assert "artifacts/prospective-observatory/*.json" in workflow
        assert "payload-" not in workflow
        assert ".json.gz" not in workflow
        assert "retention-days: 90" in workflow


def test_gate_workflow_preserves_ledger_and_refreshes_robin_live_artifact() -> None:
    workflow = _workflow("prospective-gate-report.yml")
    assert "artifacts/prospective-observatory/*.jsonl" in workflow
    assert 'COCKPIT_PROSPECTIVE_ONLY: "1"' in workflow
    assert (
        'PROSPECTIVE_REPORT_ROOT: "artifacts/prospective-observatory"'
        in workflow
    )
    assert "python scripts/build_cockpit_snapshot.py" in workflow
    assert "pnpm test" in workflow
    assert "cockpit/app/cockpit-data.sha256" in workflow
