from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts import check_database_revision as revision_guard
from scripts.check_database_revision import DatabaseMigrationRequired

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
EXPECTED = "0013_historical_evidence_index"
GUARD = f"scripts/check_database_revision.py --expected {EXPECTED}"
MIGRATION_PATHS = (
    "api-football-coverage.yml",
    "collect-fixtures.yml",
    "collect-odds.yml",
    "critical-gate-backfill.yml",
    "daily-health.yml",
    "deep-feature-build.yml",
    "external-validation.yml",
    "feature-factory.yml",
    "historical-backfill.yml",
    "historical-backtesting.yml",
    "historical-market-ingestion.yml",
    "historical-market-quality.yml",
    "historical-quality.yml",
    "jalon11-operational-one-shot.yml",
    "market-model-validation.yml",
    "model-training.yml",
    "pattern-discovery.yml",
    "pattern-settlement.yml",
    "pattern-validation.yml",
    "post-match-settlement.yml",
    "pre-match-shadow.yml",
    "prequential-prediction.yml",
    "prequential-settlement.yml",
    "prequential-training.yml",
    "prospective-deep-scheduler.yml",
    "prospective-fixture-registry.yml",
    "prospective-gate-report.yml",
    "prospective-lineup-capture.yml",
    "prospective-odds-capture.yml",
    "prospective-player-capture.yml",
    "prospective-r2-replay-audit.yml",
    "shadow-pattern-decisions.yml",
    "strategy-lab-v4.yml",
)


def test_revision_guard_allows_only_one_exact_expected_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        revision_guard,
        "current_revisions",
        lambda _database_url: (EXPECTED,),
    )
    revision_guard.require_database_revision("postgresql://masked", EXPECTED)


@pytest.mark.parametrize(
    "revisions",
    [(), ("0012_hypothesis_universe",), (EXPECTED, EXPECTED)],
)
def test_revision_guard_fails_closed_without_mutating(
    monkeypatch: pytest.MonkeyPatch,
    revisions: tuple[str, ...],
) -> None:
    monkeypatch.setattr(
        revision_guard,
        "current_revisions",
        lambda _database_url: revisions,
    )
    with pytest.raises(DatabaseMigrationRequired, match="DATABASE_MIGRATION_REQUIRED"):
        revision_guard.require_database_revision("postgresql://masked", EXPECTED)


def test_revision_guard_rejects_sqlite_without_creating_a_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "must-not-exist.db"
    with pytest.raises(DatabaseMigrationRequired, match="DATABASE_MIGRATION_REQUIRED"):
        revision_guard.require_database_revision(
            f"sqlite+pysqlite:///{database.as_posix()}", EXPECTED
        )
    assert not database.exists()


def test_ordinary_workflows_and_composite_actions_cannot_migrate() -> None:
    ci = (WORKFLOW_ROOT / "ci.yml").read_text(encoding="utf-8")
    ordinary_workflows = [
        path
        for pattern in ("*.yml", "*.yaml")
        for path in WORKFLOW_ROOT.glob(pattern)
        if path.name not in {"ci.yml", "chronos-bootstrap-ci-v3.yml"}
    ]
    composite_actions = list((ROOT / ".github" / "actions").glob("*/action.yml"))
    for path in ordinary_workflows + composite_actions:
        content = path.read_text(encoding="utf-8")
        assert "alembic upgrade" not in content, path
        assert "alembic downgrade" not in content, path
        assert "neon_bootstrap.py" not in content, path
        assert "MIGRATOR_DATABASE_URL" not in content, path
    assert "alembic upgrade head" not in ci
    assert ci.count("run_chronos_role_lifecycle_ci_v1.py") == 1
    assert "postgresql+psycopg://robin:robin_ci@localhost" in ci
    assert GUARD in ci
    bootstrap_ci = (WORKFLOW_ROOT / "chronos-bootstrap-ci-v3.yml").read_text(
        encoding="utf-8"
    )
    assert "alembic upgrade head" not in bootstrap_ci
    assert (
        bootstrap_ci.count(
            "run: python scripts/run_chronos_role_lifecycle_ci_v1.py"
        )
        == 1
    )
    assert "postgresql+psycopg://robin:robin_ci@localhost" in bootstrap_ci
    bootstrap = (ROOT / "scripts" / "neon_bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "command.upgrade" not in bootstrap
    assert "command.downgrade" not in bootstrap
    assert "alembic_config" not in bootstrap


def _steps(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    first_job = next(iter(document["jobs"].values()))
    return first_job.get("steps", [])


def _guard_position(steps: list[dict[str, Any]]) -> int:
    for index, step in enumerate(steps):
        if step.get("uses") == "./.github/actions/database-revision-guard":
            return index
        if "scripts/check_database_revision.py" in str(step.get("run", "")):
            return index
    raise AssertionError("DATABASE_REVISION_GUARD_MISSING")


def test_every_known_migration_path_is_guarded_before_workload() -> None:
    durable = (
        ROOT / ".github" / "actions" / "durable-shadow" / "action.yml"
    ).read_text(encoding="utf-8")
    historical = (
        ROOT / ".github" / "actions" / "historical-state-persist" / "action.yml"
    ).read_text(encoding="utf-8")
    assert GUARD in durable
    assert GUARD in historical
    for name in MIGRATION_PATHS:
        if name == "jalon11-operational-one-shot.yml":
            content = (WORKFLOW_ROOT / name).read_text(encoding="utf-8")
            assert "./.github/workflows/deep-feature-build.yml" in content
            continue
        steps = _steps(WORKFLOW_ROOT / name)
        guard = _guard_position(steps)
        external_effect_markers = (
            "secrets.API_FOOTBALL_KEY",
            "secrets.ODDS_API_KEY",
            "secrets.R2_ACCESS_KEY_ID",
            "ROBIN_DATABASE_URL",
            "./.github/actions/durable-shadow",
            "./.github/actions/historical-state-persist",
        )
        effects = [
            index
            for index, step in enumerate(steps)
            if index != guard
            if any(
                marker
                in str(
                    {
                        key: step.get(key)
                        for key in ("env", "run", "uses", "with")
                    }
                )
                for marker in external_effect_markers
            )
        ]
        assert effects, name
        assert guard < min(effects), name


def test_composite_action_revision_failures_are_not_continuable() -> None:
    for name in ("durable-shadow", "historical-state-persist"):
        path = ROOT / ".github" / "actions" / name / "action.yml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        guard_steps = [
            step
            for step in document["runs"]["steps"]
            if "scripts/check_database_revision.py" in str(step.get("run", ""))
        ]
        assert len(guard_steps) == 1
        assert "continue-on-error" not in guard_steps[0]


def test_secondary_pattern_jobs_depend_on_the_guarded_primary_job() -> None:
    expected_needs = {
        "pattern-discovery.yml": "discover",
        "pattern-validation.yml": "validate",
    }
    for name, primary_job in expected_needs.items():
        document = yaml.safe_load(
            (WORKFLOW_ROOT / name).read_text(encoding="utf-8")
        )
        primary_steps = document["jobs"][primary_job]["steps"]
        _guard_position(primary_steps)
        secondary = document["jobs"]["publish-candidate-registry"]
        assert secondary["needs"] == primary_job
