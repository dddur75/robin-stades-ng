from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
JALON11_WORKFLOWS = (
    "deep-feature-audit.yml",
    "deep-feature-build.yml",
    "matchup-campaign.yml",
    "matchup-validation.yml",
    "prospective-watchlist-build.yml",
    "shadow-candidate-decision.yml",
)


def _workflow(name: str) -> str:
    return (WORKFLOW_ROOT / name).read_text(encoding="utf-8")


def test_manual_jalon11_workflows_keep_zero_cost_and_fail_closed_locks() -> None:
    required = (
        'API_FOOTBALL_CALLS_ALLOWED: "0"',
        'ODDS_API_CREDITS_ALLOWED: "0"',
        'STORAGE_PAUSED: "true"',
        'P3_P4_PAUSED: "true"',
        'PRODUCTION_LOCKED: "true"',
        'REAL_BETS: "false"',
        'NO_BET_DEFAULT: "true"',
        'SOCIAL_PUBLISHING_ENABLED: "false"',
        'DEMO_MODE_ENABLED: "false"',
        "cancel-in-progress: false",
    )
    for name in JALON11_WORKFLOWS:
        workflow = _workflow(name)
        assert "workflow_dispatch:" in workflow
        assert all(value in workflow for value in required)


def test_watchlist_and_decision_workflows_use_the_canonical_engine_contract() -> None:
    watchlist = _workflow("prospective-watchlist-build.yml")
    decision = _workflow("shadow-candidate-decision.yml")

    assert "run_deep_football.py watchlist" in watchlist
    assert 'campaign["promotion"]["watchlist"] == 0' in watchlist
    assert 'campaign["promotion"]["shadow_candidates"] == 0' in watchlist
    assert 'campaign["provider_calls"] == 0' in watchlist
    assert 'campaign["odds_api_credits"] == 0' in watchlist
    assert 'watchlist["schema_version"] == "deep-football-watchlist-v1"' in watchlist
    assert 'watchlist["campaign_result_hash"] == campaign["result_hash"]' in watchlist
    assert "prospective-watchlist.json" in watchlist

    assert "run_deep_football.py decision" in decision
    assert "shadow-candidate-decision.json" in decision
    assert "deep-football-shadow-decision-v1" in decision
    assert "artifacts/shadow-candidate-decision/decision.json" not in decision
    assert (
        'decision["decisions"] == promotion["decisions"] == 0'
        in decision
    )
    assert (
        'decision["stake_units"] == promotion["stake_units"] == 0'
        in decision
    )
    assert (
        'decision["provider_calls"] == campaign["provider_calls"] == 0'
        in decision
    )
    assert '== campaign["odds_api_credits"]' in decision
    assert 'promotion["shadow_bankroll"] == 1000.0' in decision
    assert 'decision["real_bets"] is campaign["real_bets"] is False' in decision


def test_deep_feature_build_checks_primary_inference_fidelity_in_postgresql() -> None:
    build = _workflow("deep-feature-build.yml")

    assert "1.0.0-amendment-1" in build
    assert "CORRECTIVE_PROTOCOL_AMENDMENT" in build
    assert "python -m pip install boto3" in build
    assert "frozen_before_results" in build
    assert "conservative_p = max(" in build
    assert "tested_model_evaluations" in build
    assert "diagnostic_model_evaluations" in build
    assert "blocked_owner_evaluations" in build
    assert "legacy_numeric_equivalent_evaluations" in build
    assert "numeric_evidence_contract" in build
    assert "persisted_campaign_result_hashes" in build
    assert "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE" in build


def test_one_shot_orchestrator_is_explicit_sequential_and_branch_bounded() -> None:
    orchestrator = _workflow("jalon11-operational-one-shot.yml")

    assert "codex/jalon-11-deep-football-matchups" in orchestrator
    assert "[run-j11-operational]" in orchestrator
    assert "cancel-in-progress: false" in orchestrator
    assert "uses: ./.github/workflows/deep-feature-audit.yml" in orchestrator
    assert "uses: ./.github/workflows/deep-feature-build.yml" in orchestrator
    assert "needs: audit" in orchestrator
    assert "needs: build" in orchestrator
    assert "needs: campaign" in orchestrator
    assert "needs: validation" in orchestrator
    assert "needs: watchlist" in orchestrator
