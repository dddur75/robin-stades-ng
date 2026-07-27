from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    "pattern-discovery.yml",
    "pattern-validation.yml",
    "shadow-pattern-decisions.yml",
    "pattern-settlement.yml",
    "public-ledger-build.yml",
)


def test_all_pattern_workflows_are_valid_bounded_and_isolated() -> None:
    for filename in WORKFLOWS:
        path = ROOT / ".github" / "workflows" / filename
        text = path.read_text("utf-8")
        assert yaml.safe_load(text)
        assert "timeout-minutes:" in text
        assert "REAL_BETS: \"true\"" not in text
        assert "SOCIAL_PUBLISHING_ENABLED: \"true\"" not in text
    discovery = (
        ROOT / ".github" / "workflows" / "pattern-discovery.yml"
    ).read_text("utf-8")
    validation = (
        ROOT / ".github" / "workflows" / "pattern-validation.yml"
    ).read_text("utf-8")
    for text in (discovery, validation):
        assert "group: pattern-research-state" in text
        assert "historical-state-restore" in text
        assert "ODDS_API_KEY" not in text
        assert "API_FOOTBALL_KEY" not in text
        assert "historical-state-persist" not in text
        assert "durable-shadow" not in text
    assert "--replay" in validation


def test_shadow_workflows_preserve_shadow_isolation_and_fail_closed() -> None:
    decisions = (
        ROOT / ".github" / "workflows" / "shadow-pattern-decisions.yml"
    ).read_text("utf-8")
    settlement = (
        ROOT / ".github" / "workflows" / "pattern-settlement.yml"
    ).read_text("utf-8")
    for text in (decisions, settlement):
        assert "group: shadow-state" in text
        assert "historical-data" not in text
        assert "historical-state" not in text
        assert "ODDS_API_KEY" not in text
        assert "API_FOOTBALL_KEY" not in text
        assert "durable-shadow" in text
    assert "NO_BET_DATA_UNAVAILABLE" in decisions
    assert "NO_SETTLEMENT_DUE" in settlement


def test_preregistered_config_and_social_files_are_locked() -> None:
    config = json.loads(
        (ROOT / "configs" / "pattern-research-v1.json").read_text("utf-8")
    )
    assert config["provider_calls_allowed"] == 0
    assert config["live_market_point_in_time"] is False
    assert config["social_publishing_enabled"] is False
    assert config["minimum_bets"] == 80
    assert config["minimum_seasons"] == 3
    assert config["fdr_alpha"] == 0.05
    for path in (ROOT / "social_exports").glob("*.json"):
        payload = json.loads(path.read_text("utf-8"))
        assert payload["publishing_enabled"] is False
        assert payload["negative_results_included"] is True


def test_ci_includes_jalon10_migrations_and_secret_scan() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    assert "tests/jalon10" in text
    assert "pattern_definitions" in text
    assert "experiment_registry" in text
    assert "scripts/check_no_secrets.py" in text
