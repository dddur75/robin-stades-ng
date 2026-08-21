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
        assert 'REAL_BETS: "true"' not in text
        assert 'SOCIAL_PUBLISHING_ENABLED: "true"' not in text
    discovery = (ROOT / ".github" / "workflows" / "pattern-discovery.yml").read_text("utf-8")
    validation = (ROOT / ".github" / "workflows" / "pattern-validation.yml").read_text("utf-8")
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
        assert (
            "campaign-summary.json"
            not in text.split(
                "Publier uniquement le registre compact des candidats",
                maxsplit=1,
            )[-1]
        )
    assert "--replay" in validation


def test_shadow_workflows_preserve_shadow_isolation_and_fail_closed() -> None:
    decisions = (ROOT / ".github" / "workflows" / "shadow-pattern-decisions.yml").read_text("utf-8")
    settlement = (ROOT / ".github" / "workflows" / "pattern-settlement.yml").read_text("utf-8")
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
    config = json.loads((ROOT / "configs" / "pattern-research-v1.json").read_text("utf-8"))
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


def test_bounded_live_canary_ubuntu_job_pins_required_quality_gates() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text("utf-8"))
    job = workflow["jobs"]["bounded-live-canary-ubuntu"]

    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 12
    assert job["permissions"] == {"contents": "read"}
    assert "env" not in job

    checkout, setup_python = job["steps"][:2]
    assert checkout == {
        "uses": "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "with": {
            "persist-credentials": False,
            "ref": "${{ github.event.pull_request.head.sha || github.sha }}",
        },
    }
    assert setup_python["uses"] == ("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065")
    assert setup_python["with"]["python-version"] == "3.12.10"

    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    assert steps["Vérifier les artifacts synthétiques bornés"]["run"].splitlines() == [
        "python tools/data-sourcing/build_capture_harness_artifacts.py --check",
        "python tools/data-sourcing/build_bounded_live_canary_artifacts.py --check",
    ]

    required_python_paths = (
        "src/robin/capture",
        "tools/data-sourcing/build_capture_harness_artifacts.py",
        "tools/data-sourcing/build_bounded_live_canary_artifacts.py",
        "tools/data-sourcing/run_bounded_live_canary_v1.py",
    )
    ruff_paths = (
        *required_python_paths[:1],
        "tests/capture",
        "tests/council/test_bounded_live_canary_governance.py",
        "tests/jalon10/test_workflows_and_guards.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
        *required_python_paths[1:],
    )
    format_paths = (
        *required_python_paths[:1],
        "tests/capture",
        "tests/council/test_bounded_live_canary_governance.py",
        *required_python_paths[1:],
    )
    quality_commands = {
        "ruff": steps["Vérifier Ruff sur la capacité bornée"]["run"],
        "format": steps["Vérifier le format Ruff de la capacité bornée"]["run"],
        "mypy": steps["Vérifier le typage strict de la capacité bornée"]["run"],
        "bandit": steps["Auditer la sécurité statique de la capacité bornée"]["run"],
    }
    assert quality_commands["ruff"].split() == [
        "python",
        "-m",
        "ruff",
        "check",
        *ruff_paths,
    ]
    assert quality_commands["format"].split() == [
        "python",
        "-m",
        "ruff",
        "format",
        "--check",
        *format_paths,
    ]
    assert quality_commands["mypy"].split() == [
        "python",
        "-m",
        "mypy",
        "--strict",
        *required_python_paths,
    ]
    assert quality_commands["bandit"].split() == [
        "python",
        "-m",
        "bandit",
        "-q",
        "-r",
        *required_python_paths,
    ]

    assert steps["Refuser les secrets et chemins locaux suivis"]["run"].splitlines() == [
        "python scripts/check_no_secrets.py",
        "python scripts/check_no_tracked_absolute_paths.py",
    ]
    schema_validation = steps["Valider les JSON YAML et schémas bornés"]["run"]
    for required_contract in (
        "yaml.safe_load",
        "Draft202012Validator.check_schema",
        "OwnerAuthorizationV1.model_validate",
        "ActivationEnvelopeV1.model_validate",
        "LivePlanV1.model_validate",
        "ProviderRequestSpec.model_validate",
        "FixtureMapping.model_validate",
        'report["contract_schemas"] == expected_schema_hashes',
    ):
        assert required_contract in schema_validation
    for required_json in (
        "configs/agents/agent-report-schema-v3.json",
        "configs/agents/mission-activation-matrix-v3.json",
        "configs/execution/bounded-multi-league-live-canary-capability-v1.json",
        "reports/data-sourcing/bounded-live-canary-capability-v1.json",
        "reports/data-sourcing/capture-harness-contract-v1.json",
        "reports/data-sourcing/capture-threat-model-v1.json",
        "reports/data-sourcing/internal-retention-policy-v1.json",
        "reports/data-sourcing/live-canary-plan-v1.json",
        "reports/data-sourcing/offline-replay-proof-v1.json",
        "tests/capture/fixtures/bounded-live-canary-v1-golden-pack.json",
    ):
        assert required_json in schema_validation

    real_data_scan = steps["Refuser toute donnée réelle dans les artifacts synthétiques"]["run"]
    for required_guard in (
        "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD_NO_REAL_AUTHORITY",
        "forbidden_payload_keys",
        "assert_no_provider_payload(pack)",
        "assert_no_provider_payload(report)",
        'mapping["provider_event_id"].startswith("synthetic-")',
        'report["real_authorization_status"] == "NOT_CREATED"',
        'report["real_activation_status"] == "NOT_CREATED"',
        'report["real_batch_status"] == "NOT_EXECUTED"',
        'report["real_snapshot_status"] == "NOT_CREATED"',
        "assert report[zero_field] == 0",
    ):
        assert required_guard in real_data_scan

    test_command = steps["Compiler et tester la capacité et ses gardes de livraison"]["run"]
    for required_test_path in (
        "tests/capture",
        "tests/council/test_bounded_live_canary_governance.py",
        "tests/council/test_robin_council_os_v3.py",
        "tests/jalon10/test_workflows_and_guards.py",
        "tests/portability/test_chronos_portable_ci_contract.py",
    ):
        assert required_test_path in test_command
    assert "${{ secrets." not in yaml.safe_dump(job)


def test_ci_repository_wide_tests_job_preserves_exact_timeout_and_scope() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text("utf-8"))

    assert "tests" in workflow["jobs"]
    tests_job = workflow["jobs"]["tests"]
    assert tests_job["timeout-minutes"] == 40
    assert set(tests_job["needs"]) == {
        "bounded-live-canary-ubuntu",
        "bounded-live-canary-windows",
        "frozen-evidence-windows",
        "chronos-postgresql-profiles",
        "chronos-end-to-end-live-path-replay",
        "chronos-residual-fault-matrix",
        "chronos-exact-workflow-entrypoint",
        "historical-authority-workflows-disabled",
    }

    steps_by_name = {step["name"]: step for step in tests_job["steps"] if "name" in step}
    assert steps_by_name["Installer les dependances"]["run"].splitlines() == [
        "python -m pip install -r requirements.txt",
        "python -m pip install --no-deps -e .",
    ]
    assert steps_by_name["Executer les tests"]["run"] == "python -m pytest -q"

    pytest_commands = "\n".join(
        str(step.get("run", ""))
        for step in tests_job["steps"]
        if "python -m pytest -q" in str(step.get("run", ""))
    )
    for required_test_path in (
        "tests/chronos/test_chronos_postgresql_v2.py",
        "tests/jalon4",
        "tests/jalon5",
        "tests/jalon6",
        "tests/jalon7",
        "tests/jalon8",
        "tests/jalon9",
        "tests/jalon14",
    ):
        assert required_test_path in pytest_commands


def test_ci_replays_frozen_jalon10_on_windows_before_linux_checks() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text("utf-8"))
    jobs = workflow["jobs"]
    evidence_job = jobs["frozen-evidence-windows"]
    tests_job = jobs["tests"]
    visual_job = jobs["visual-regression"]

    assert evidence_job["runs-on"] == "windows-latest"
    assert tests_job["runs-on"] == "ubuntu-latest"
    expected_test_needs = {
        "bounded-live-canary-ubuntu",
        "bounded-live-canary-windows",
        "frozen-evidence-windows",
        "chronos-postgresql-profiles",
        "chronos-end-to-end-live-path-replay",
        "chronos-residual-fault-matrix",
        "chronos-exact-workflow-entrypoint",
        "historical-authority-workflows-disabled",
    }
    assert len(tests_job["needs"]) == len(expected_test_needs)
    assert set(tests_job["needs"]) == expected_test_needs
    assert set(visual_job["needs"]) == {"frozen-evidence-windows", "tests"}

    evidence_commands = "\n".join(str(step.get("run", "")) for step in evidence_job["steps"])
    assert "423fb7e77ba52286b660956161f02f8a2c1be7f8..HEAD" in evidence_commands
    assert "5c85cf20b932df44dca8665de00e52e3f1e02236" in evidence_commands
    assert "JALON_10_EXPECTED_30_PARTITIONS" in evidence_commands
    assert "--replay" in evidence_commands
    assert "COMPACT_CAMPAIGN_SHA256" in evidence_commands
    assert "FULL_CAMPAIGN_SHA256" in evidence_commands
    assert "REGISTRY_SHA256" in evidence_commands

    upload_steps = {
        step["with"]["name"]: step["with"]
        for step in evidence_job["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    }
    artifact_name = (
        "hypothesis-evidence-campaign-inputs-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    compact_artifact_name = (
        "hypothesis-evidence-compact-campaign-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert set(upload_steps[artifact_name]["path"].splitlines()) == {
        ".ci/hypothesis-j10/campaign-summary.json",
        ".ci/hypothesis-j10/hypothesis-registry.jsonl",
        ".ci/hypothesis-j10/replay.json",
    }
    assert upload_steps[compact_artifact_name]["path"] == (
        "reports/pattern-research/campaign-summary.json"
    )
    for consumer_job in (tests_job, visual_job):
        download_steps = {
            step["with"]["name"]: step["with"]
            for step in consumer_job["steps"]
            if str(step.get("uses", "")).startswith("actions/download-artifact@")
        }
        assert download_steps[artifact_name] == {
            "name": artifact_name,
            "path": ".ci/hypothesis-j10",
        }
        assert download_steps[compact_artifact_name] == {
            "name": compact_artifact_name,
            "path": "reports/pattern-research",
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
