from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from robin.patterns.ledger import EvidenceLedger
from robin.patterns.temporal import LeakageError
from scripts.run_shadow_pattern_decisions import main as run_decisions

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
        assert "group: shadow-state" in text
        assert "historical-state-restore" in text
        assert "ODDS_API_KEY" not in text
        assert "API_FOOTBALL_KEY" not in text
        assert "historical-state-persist" not in text
        assert "durable-shadow" in text
        assert "ROBIN_DATABASE_URL" in text
        assert "shadow-candidate-registry.json" in text
        assert "campaign-summary.json" not in text.split(
            "Publier uniquement le registre compact des candidats",
            maxsplit=1,
        )[-1]
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
    assert "NO_SETTLEMENT_DUE" in settlement
    assert "schedule:" not in decisions
    assert "schedule:" not in settlement
    assert "NO_LIVE_SHADOW_CANDIDATE" in decisions
    assert "shadow-candidate-registry.json" in decisions


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


def test_ci_replays_frozen_jalon10_on_windows_before_linux_checks() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text("utf-8"))
    jobs = workflow["jobs"]
    evidence_job = jobs["hypothesis-evidence-inputs"]
    tests_job = jobs["tests"]
    visual_job = jobs["visual-regression"]

    assert evidence_job["runs-on"] == "windows-latest"
    assert tests_job["runs-on"] == "ubuntu-latest"
    assert tests_job["needs"] == "hypothesis-evidence-inputs"
    assert visual_job["needs"] == ["hypothesis-evidence-inputs", "tests"]

    evidence_commands = "\n".join(
        str(step.get("run", "")) for step in evidence_job["steps"]
    )
    assert "423fb7e77ba52286b660956161f02f8a2c1be7f8..HEAD" in evidence_commands
    assert "5c85cf20b932df44dca8665de00e52e3f1e02236" in evidence_commands
    assert "JALON_10_EXPECTED_30_PARTITIONS" in evidence_commands
    assert "--replay" in evidence_commands
    assert "FULL_CAMPAIGN_SHA256" in evidence_commands
    assert "REGISTRY_SHA256" in evidence_commands

    upload_step = next(
        step
        for step in evidence_job["steps"]
        if step.get("uses") == "actions/upload-artifact@v4"
    )
    artifact_name = (
        "hypothesis-evidence-campaign-inputs-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert upload_step["with"]["name"] == artifact_name
    assert set(upload_step["with"]["path"].splitlines()) == {
        ".ci/hypothesis-j10/campaign-summary.json",
        ".ci/hypothesis-j10/hypothesis-registry.jsonl",
        ".ci/hypothesis-j10/replay.json",
    }
    for consumer_job in (tests_job, visual_job):
        download_step = next(
            step
            for step in consumer_job["steps"]
            if step.get("uses") == "actions/download-artifact@v4"
        )
        assert download_step["with"] == {
            "name": artifact_name,
            "path": ".ci/hypothesis-j10",
        }


def test_runner_decisions_parse_json_point_in_time_et_fixture_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = {
        "provider_calls": 0,
        "real_bets": False,
        "no_bet_default": True,
        "production_status": "PRODUCTION_LOCKED",
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "candidate_count": 1,
        "config": {"live_market_point_in_time": True},
        "hypotheses": [
            {
                "status": "LIVE_SHADOW_CANDIDATE",
                "market": "1X2_HOME",
                "selection": "HOME",
                "rule_hash": "a" * 64,
                "conditions": [
                    {
                        "feature": "competition",
                        "operator": "EQ",
                        "value": "Ligue 1",
                        "source": "API_FOOTBALL_FIXTURE",
                        "available_at": "FIXTURE_PUBLICATION",
                    }
                ],
            }
        ],
    }
    fixtures = [
        {
            "fixture_id": "odds-api-uuid-1",
            "competition": "Ligue 1",
            "kickoff_at": "2026-08-01T12:00:00+00:00",
            "observed_at": "2026-08-01T09:00:00+00:00",
            "odds_home": 2.0,
            "odds_source": "POINT_IN_TIME_CACHE",
            "dataset_hash": "b" * 64,
        }
    ]
    campaign_path = tmp_path / "candidates.json"
    fixtures_path = tmp_path / "fixtures.json"
    ledger_path = tmp_path / "ledger.jsonl"
    output_path = tmp_path / "report.json"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_shadow_pattern_decisions.py",
            "--campaign",
            str(campaign_path),
            "--fixtures",
            str(fixtures_path),
            "--ledger",
            str(ledger_path),
            "--output",
            str(output_path),
            "--code-revision",
            "abc123",
            "--published-at",
            "2026-08-01T10:00:00+00:00",
        ],
    )

    run_decisions()

    audit = EvidenceLedger(ledger_path).audit()
    record = json.loads(ledger_path.read_text("utf-8"))
    assert audit["decisions"] == 1
    assert record["fixture_id"] == "odds-api-uuid-1"
    assert record["decision"] == "BET"


def test_runner_refuse_condition_historique_marquee_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign = {
        "provider_calls": 0,
        "real_bets": False,
        "no_bet_default": True,
        "production_status": "PRODUCTION_LOCKED",
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "candidate_count": 1,
        "config": {"live_market_point_in_time": True},
        "hypotheses": [
            {
                "status": "LIVE_SHADOW_CANDIDATE",
                "market": "1X2_HOME",
                "selection": "HOME",
                "rule_hash": "a" * 64,
                "conditions": [
                    {
                        "feature": "odds_home",
                        "operator": "GE",
                        "value": 1.5,
                        "source": "FOOTBALL_DATA",
                        "available_at": "HISTORICAL_PRICE_CATEGORY",
                    }
                ],
            }
        ],
    }
    campaign_path = tmp_path / "candidates.json"
    fixtures_path = tmp_path / "fixtures.json"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    fixtures_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_shadow_pattern_decisions.py",
            "--campaign",
            str(campaign_path),
            "--fixtures",
            str(fixtures_path),
            "--ledger",
            str(tmp_path / "ledger.jsonl"),
            "--output",
            str(tmp_path / "report.json"),
            "--code-revision",
            "abc123",
        ],
    )

    with pytest.raises(LeakageError, match="FEATURE_NOT_LIVE_POINT_IN_TIME"):
        run_decisions()
