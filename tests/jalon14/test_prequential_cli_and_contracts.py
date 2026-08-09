from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from robin.prospective_observatory.prequential_contracts import (
    FixtureResultStatus,
    FixtureSettlementRecord,
    PredictionStatus,
    VerifiedFixtureResult,
)
from robin.storage.database import build_engine
from robin.storage.prospective_models import ProspectiveFixtureModel
from scripts.build_cockpit_snapshot import build_prequential_learning
from scripts.run_prequential_learning_factory import (
    REQUIRED_GUARDS,
    _config,
    _verified_result_from_record,
    _verify_runtime_guards,
    run_status,
    run_synthetic_pilot,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


def _alembic(url: str) -> Config:
    value = Config(str(ROOT / "alembic.ini"))
    value.set_main_option("script_location", str(ROOT / "migrations"))
    value.set_main_option("sqlalchemy.url", url)
    return value


def test_synthetic_pilot_proves_mechanics_without_real_evidence(
    tmp_path: Path,
) -> None:
    config = _config(ROOT / "configs" / "prequential_learning_v1.json")
    first = run_synthetic_pilot(config=config, output=tmp_path, now=NOW)
    second = run_synthetic_pilot(config=config, output=tmp_path, now=NOW)
    assert first == second
    assert first["origin"] == "SYNTHETIC_MECHANICS_ONLY"
    assert first["prospective_evidence"] is False
    assert first["synthetic_fixtures"] == first["training_support"] == 30
    assert first["represented_leagues"] == 2
    assert first["idempotent_settlement_retries"] == 30
    assert first["late_prediction_status"] == "REJECTED_LATE"
    assert first["training_status"] == "CHALLENGER_VERSION_CREATED"
    assert first["real_predictions"] == first["real_settlements"] == 0
    assert first["provider_calls"] == first["odds_api_credits"] == 0
    assert first["promotion_status"] == "PROMOTION_LOCKED"


def test_status_reports_real_zero_state_and_next_cutoff(tmp_path: Path) -> None:
    database = tmp_path / "status.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic(url), "head")
    engine = build_engine(url)
    with Session(engine) as session, session.begin():
        session.add(
            ProspectiveFixtureModel(
                id="fixture-record-status",
                idempotency_key="fixture:status",
                fixture_id="api-football:status",
                competition="Ligue 1",
                season="2026",
                phase="Regular Season",
                home_team_id="home",
                away_team_id="away",
                kickoff_at=NOW + timedelta(hours=2),
                provider="api-football",
                provider_fixture_id="123",
                registered_at=NOW - timedelta(days=1),
                registry_hash="a" * 64,
                code_revision="test-revision",
                cancelled=False,
                kickoff_reliable=True,
                append_only=True,
            )
        )
    report = run_status(
        engine=engine,
        config=_config(ROOT / "configs" / "prequential_learning_v1.json"),
        output=tmp_path,
        now=NOW,
    )
    assert report["fixtures_tracked"] == 1
    assert report["cutoffs_due"] == 1
    assert report["predictions_real"] == 0
    assert report["settlements_real"] == 0
    assert report["training_support"] == 0
    assert report["provider_calls"] == report["odds_api_credits"] == 0
    live_status = json.loads((tmp_path / "status.json").read_text("utf-8"))
    assert live_status["schema_version"] == "prequential-learning-status-v1"
    assert live_status["origin"] == "POSTGRESQL_REAL_PREQUENTIAL_STATE"
    assert live_status["predictions"]["next_due_at"] == (
        NOW + timedelta(hours=1, minutes=59)
    ).isoformat()
    assert live_status["predictions"]["frozen"] == 0
    assert live_status["settlements"]["fixtures"] == 0
    assert live_status["training"]["runs"] == 0
    assert live_status["models"] == {
        "reference": None,
        "challenger": None,
        "scopes": [],
        "active_count": 0,
    }
    assert live_status["security"] == {
        "production_locked": True,
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
    }


def test_provider_score_correction_is_versioned_and_unchanged_score_is_noop() -> None:
    fixture = ProspectiveFixtureModel(
        id="fixture-record-correction",
        idempotency_key="fixture:correction",
        fixture_id="api-football:correction",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=NOW - timedelta(hours=4),
        provider="api-football",
        provider_fixture_id="456",
        registered_at=NOW - timedelta(days=1),
        registry_hash="a" * 64,
        code_revision="test-revision",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )
    initial_result = VerifiedFixtureResult(
        fixture_record_id=fixture.id,
        fixture_id=fixture.fixture_id,
        competition=fixture.competition,
        kickoff_at=fixture.kickoff_at,
        status=FixtureResultStatus.FINISHED,
        verified_at=NOW - timedelta(hours=1),
        home_goals=2,
        away_goals=1,
        source_hash="b" * 64,
    )
    initial_settlement = FixtureSettlementRecord(
        settlement_id="settlement-initial",
        result=initial_result,
        settled_at=NOW - timedelta(minutes=30),
        effective_status=PredictionStatus.SETTLED,
    )
    unchanged = {
        "fixture": {"id": 456, "status": {"short": "FT"}},
        "goals": {"home": 2, "away": 1},
    }
    assert (
        _verified_result_from_record(
            fixture=fixture,
            record=unchanged,
            verified_at=NOW,
            source_hash="c" * 64,
            latest_settlement=initial_settlement,
        )
        is None
    )
    corrected = _verified_result_from_record(
        fixture=fixture,
        record={
            "fixture": {"id": 456, "status": {"short": "FT"}},
            "goals": {"home": 3, "away": 1},
        },
        verified_at=NOW,
        source_hash="d" * 64,
        latest_settlement=initial_settlement,
    )
    assert corrected is not None
    assert corrected.status is FixtureResultStatus.CORRECTED
    assert corrected.result_version == 2
    assert corrected.home_goals == 3


def test_runtime_guards_fail_closed() -> None:
    _verify_runtime_guards(REQUIRED_GUARDS)
    unsafe = dict(REQUIRED_GUARDS)
    unsafe["REAL_BETS"] = "true"
    try:
        _verify_runtime_guards(unsafe)
    except RuntimeError as error:
        assert "REAL_BETS" in str(error)
    else:
        raise AssertionError("unsafe runtime guards accepted")


def test_cockpit_builder_reads_the_selected_operational_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ROOT / "reports" / "prequential-learning" / "status.json"
    monkeypatch.setenv("PREQUENTIAL_LEARNING_STATUS", str(path))
    status = build_prequential_learning()
    assert status["schema_version"] == "prequential-learning-status-v1"
    assert status["predictions"]["frozen"] == 0
    assert status["predictions"]["next_due_at"] == "2026-08-15T15:30:00+00:00"
    assert status["promotion_status"] == "PROMOTION_LOCKED"


def test_config_contains_only_two_markets_and_all_six_scopes() -> None:
    config = _config(ROOT / "configs" / "prequential_learning_v1.json")
    assert config["markets"] == ["1X2", "OVER_UNDER_2_5"]
    assert set(config["model_scopes"]) == {
        "GLOBAL_FIVE_LEAGUES",
        "LIGUE_1",
        "PREMIER_LEAGUE",
        "LIGA",
        "BUNDESLIGA",
        "SERIE_A",
    }
    assert config["security"] == {
        "production_locked": True,
        "real_bets": False,
        "no_bet_default": True,
        "promotion_status": "PROMOTION_LOCKED",
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
    }


def test_workflows_are_isolated_serial_and_never_cancel_in_progress() -> None:
    workflows = {
        name: yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
        for name in (
            "prequential-prediction.yml",
            "prequential-settlement.yml",
            "prequential-training.yml",
        )
    }
    for value in workflows.values():
        assert value["concurrency"] == {
            "group": "prequential-learning-state",
            "cancel-in-progress": False,
        }
        job = next(iter(value["jobs"].values()))
        assert job["env"]["PRODUCTION_LOCKED"] == "true"
        assert job["env"]["REAL_BETS"] == "false"
        assert job["env"]["PROMOTION_LOCKED"] == "true"
        assert job["env"]["SOCIAL_PUBLISHING_ENABLED"] == "false"
        assert job["env"]["DEMO_MODE_ENABLED"] == "false"
    prediction = workflows["prequential-prediction.yml"]
    assert prediction[True]["schedule"][0]["cron"] == "*/5 * * * *"
    settlement_job = workflows["prequential-settlement.yml"]["jobs"]["settle"]
    assert settlement_job["env"]["API_FOOTBALL_CALLS_ALLOWED"] == "10"
    assert settlement_job["env"]["ODDS_API_CREDITS_ALLOWED"] == "0"
    training_job = workflows["prequential-training.yml"]["jobs"]["train"]
    assert training_job["env"]["API_FOOTBALL_KEY"] == ""
    assert training_job["env"]["ODDS_API_KEY"] == ""


def test_workflows_reference_existing_cli_and_no_automatic_merge() -> None:
    cli = ROOT / "scripts" / "run_prequential_learning_factory.py"
    assert cli.is_file()
    for path in (ROOT / ".github" / "workflows").glob("prequential-*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "run_prequential_learning_factory.py" in text
        assert "cancel-in-progress: false" in text
        assert "git push" not in text
        assert "gh pr merge" not in text


def test_robin_experience_learning_page_is_french_expert_and_mobile() -> None:
    page = (
        ROOT
        / "cockpit"
        / "app"
        / "components"
        / "learning"
        / "learning-page.tsx"
    ).read_text(encoding="utf-8")
    route = (
        ROOT / "cockpit" / "app" / "apprentissage" / "page.tsx"
    ).read_text(encoding="utf-8")
    styles = (ROOT / "cockpit" / "app" / "globals.css").read_text(
        encoding="utf-8"
    )
    french = (ROOT / "cockpit" / "app" / "i18n" / "fr-FR.ts").read_text(
        encoding="utf-8"
    )
    assert "Apprentissage en direct" in french
    assert (
        "Robin apprend uniquement après les matchs, sans modifier les "
        "prédictions déjà publiées."
    ) in french
    assert "Vue essentielle" in french
    assert "Vue expert" in french
    assert "learning.promotion" in page
    assert "LearningPage" in route
    assert "@media" in styles


def test_documentation_declares_synthetic_isolation_and_real_zero_state() -> None:
    text = (
        ROOT
        / "docs"
        / "prequential-learning"
        / "PREQUENTIAL-LEARNING-FACTORY-V1.md"
    ).read_text(encoding="utf-8")
    assert "SYNTHETIC" in text.upper()
    assert "PROMOTION_LOCKED" in text
    assert "API_FOOTBALL_CALLS = 0" in text
    status = (ROOT / "PROJECT-STATUS.md").read_text(encoding="utf-8")
    assert "PREQUENTIAL_LEARNING_FACTORY_READY" in status
    assert "0 prédiction" in status


def test_json_reports_are_hashable_and_do_not_contain_secrets(tmp_path: Path) -> None:
    report = run_synthetic_pilot(
        config=_config(ROOT / "configs" / "prequential_learning_v1.json"),
        output=tmp_path,
        now=NOW,
    )
    stored = json.loads(
        (tmp_path / "synthetic-pilot" / "pilot-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == report
    encoded = json.dumps(stored)
    assert "API_FOOTBALL_KEY" not in encoded
    assert "R2_SECRET_ACCESS_KEY" not in encoded
