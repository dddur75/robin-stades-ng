from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FixtureResultStatus,
    FixtureSettlementRecord,
    PredictionMarket,
    PredictionStatus,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_storage import (
    InMemoryArtifactStore,
    PrequentialArtifactRepository,
)
from robin.providers.contracts import ProviderResult
from robin.storage.database import build_engine
from robin.storage.prequential_models import PrequentialTrainingRunModel
from robin.storage.prospective_models import ProspectiveFixtureModel
from scripts.build_cockpit_snapshot import build_prequential_learning
from scripts.run_prequential_learning_factory import (
    REQUIRED_GUARDS,
    _collect_result,
    _config,
    _last_successful_training,
    _training_parent_model,
    _verified_result_from_record,
    _verify_runtime_guards,
    run_status,
    run_synthetic_pilot,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 29, 12, tzinfo=UTC)


class _ResultProvider:
    def __init__(self, *, received_at: datetime = NOW) -> None:
        self.calls = 0
        self.received_at = received_at

    def get_fixtures(self, *, fixture_id: int) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            provider="api-football",
            endpoint="/fixtures",
            availability=DataAvailability.PRESENT,
            records=(
                {
                    "fixture": {"id": fixture_id, "status": {"short": "FT"}},
                    "goals": {"home": 2, "away": 1},
                },
            ),
            observed_at=self.received_at,
            received_at=self.received_at,
            requested_at=self.received_at - timedelta(seconds=1),
            origin=DataOrigin.LIVE_SOURCE,
            http_status=200,
        )


def test_future_result_observation_cannot_throttle_past_provider_attempt() -> None:
    fixture = ProspectiveFixtureModel(
        id="fixture-record-future-observation",
        idempotency_key="fixture:future-observation",
        fixture_id="api-football:future-observation",
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

    def collect(*, with_future_artifact: bool) -> tuple[str, int, int]:
        repository = PrequentialArtifactRepository(InMemoryArtifactStore())
        if with_future_artifact:
            future_observation = repository.put_manifest(
                "result-observations",
                {
                    "schema_version": "prequential-result-observation-v1",
                    "provider": "api-football",
                    "fixture_id": fixture.fixture_id,
                    "fixture_record_id": fixture.id,
                    "provider_fixture_id": fixture.provider_fixture_id,
                    "attempt": 1,
                    "observed_at": (NOW + timedelta(hours=1)).isoformat(),
                    "availability": DataAvailability.PRESENT.value,
                    "http_status": 200,
                    "record": None,
                    "provider_calls": 1,
                },
            )
            future_guard = repository.put_manifest(
                "provider-call-guards",
                {
                    "schema_version": "prequential-provider-call-guard-v1",
                    "fixture_id": fixture.fixture_id,
                    "fixture_record_id": fixture.id,
                    "provider_fixture_id": fixture.provider_fixture_id,
                    "attempt": 1,
                    "operation": "VERIFY_FINAL_RESULT",
                    "guard_id": canonical_sha256(
                        {
                            "fixture_id": fixture.fixture_id,
                            "fixture_record_id": fixture.id,
                            "provider_fixture_id": fixture.provider_fixture_id,
                            "attempt": 1,
                            "operation": "VERIFY_FINAL_RESULT",
                        }
                    ),
                    "guarded_at": (NOW + timedelta(hours=1)).isoformat(),
                },
            )
            repository.put_manifest(
                "provider-call-completions",
                {
                    "schema_version": (
                        "prequential-provider-call-completion-v1"
                    ),
                    "guard_sha256": future_guard.sha256,
                    "observation_sha256": future_observation.sha256,
                    "fixture_id": fixture.fixture_id,
                    "fixture_record_id": fixture.id,
                    "attempt": 1,
                    "completed_at": (NOW + timedelta(hours=1)).isoformat(),
                },
            )
        provider = _ResultProvider()
        result, calls = _collect_result(
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
            fixture=fixture,
            now=NOW,
        )
        assert result is not None
        return result.result_hash, calls, provider.calls

    assert collect(with_future_artifact=False) == collect(
        with_future_artifact=True
    )


def test_future_duplicate_completion_cannot_poison_past_retry() -> None:
    fixture = ProspectiveFixtureModel(
        id="fixture-record-future-completion",
        idempotency_key="fixture:future-completion",
        fixture_id="api-football:future-completion",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=NOW - timedelta(hours=8),
        provider="api-football",
        provider_fixture_id="456",
        registered_at=NOW - timedelta(days=1),
        registry_hash="a" * 64,
        code_revision="test-revision",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )

    def collect(
        *,
        include_exact_completion: bool = True,
        duplicate_completion_at: datetime | None = None,
    ) -> tuple[str, int, int]:
        repository = PrequentialArtifactRepository(InMemoryArtifactStore())
        guard_identity = {
            "fixture_id": fixture.fixture_id,
            "fixture_record_id": fixture.id,
            "provider_fixture_id": fixture.provider_fixture_id,
            "attempt": 1,
            "operation": "VERIFY_FINAL_RESULT",
        }
        guard = repository.put_manifest(
            "provider-call-guards",
            {
                "schema_version": "prequential-provider-call-guard-v1",
                **guard_identity,
                "guard_id": canonical_sha256(guard_identity),
                "guarded_at": (NOW - timedelta(seconds=1)).isoformat(),
            },
        )
        observation = repository.put_manifest(
            "result-observations",
            {
                "schema_version": "prequential-result-observation-v1",
                "provider": "api-football",
                "fixture_id": fixture.fixture_id,
                "fixture_record_id": fixture.id,
                "provider_fixture_id": fixture.provider_fixture_id,
                "attempt": 1,
                "observed_at": NOW.isoformat(),
                "availability": DataAvailability.PRESENT.value,
                "http_status": 200,
                "record": {
                    "fixture": {
                        "id": int(fixture.provider_fixture_id),
                        "status": {"short": "FT"},
                    },
                    "goals": {"home": 2, "away": 1},
                },
                "provider_calls": 1,
            },
        )
        completion = {
            "schema_version": "prequential-provider-call-completion-v1",
            "guard_sha256": guard.sha256,
            "observation_sha256": observation.sha256,
            "fixture_id": fixture.fixture_id,
            "fixture_record_id": fixture.id,
            "attempt": 1,
            "completed_at": NOW.isoformat(),
        }
        if include_exact_completion:
            repository.put_manifest("provider-call-completions", completion)
        if duplicate_completion_at is not None:
            repository.put_manifest(
                "provider-call-completions",
                {
                    **completion,
                    "completed_at": duplicate_completion_at.isoformat(),
                },
            )
        provider = _ResultProvider(received_at=NOW + timedelta(hours=7))
        result, calls = _collect_result(
            repository=repository,
            provider=provider,  # type: ignore[arg-type]
            fixture=fixture,
            now=NOW + timedelta(hours=7),
        )
        assert result is not None
        return result.result_hash, calls, provider.calls

    assert collect() == collect(
        duplicate_completion_at=NOW + timedelta(hours=8)
    )
    with pytest.raises(
        RuntimeError,
        match="PREQUENTIAL_PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED",
    ):
        collect(
            include_exact_completion=False,
            duplicate_completion_at=NOW + timedelta(hours=6),
        )


@pytest.mark.parametrize(
    ("provider_status", "score_expected"),
    (("FT", True), ("CANC", False)),
)
def test_settlement_uses_provider_completion_time_for_scores_and_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_status: str,
    score_expected: bool,
) -> None:
    import scripts.run_prequential_learning_factory as runner

    received_at = NOW + timedelta(seconds=1)
    fixture = ProspectiveFixtureModel(
        id="fixture-record-delayed-result",
        idempotency_key="fixture:delayed-result",
        fixture_id="api-football:delayed-result",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=NOW - timedelta(hours=4),
        provider="api-football",
        provider_fixture_id="789",
        registered_at=NOW - timedelta(days=1),
        registry_hash="a" * 64,
        code_revision="test-revision",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )

    class DelayedProvider:
        def get_fixtures(self, *, fixture_id: int) -> ProviderResult:
            return ProviderResult(
                provider="api-football",
                endpoint="/fixtures",
                availability=DataAvailability.PRESENT,
                records=(
                    {
                        "fixture": {
                            "id": fixture_id,
                            "status": {"short": provider_status},
                        },
                        "goals": {"home": 2, "away": 1},
                    },
                ),
                observed_at=received_at,
                received_at=received_at,
                requested_at=NOW,
                origin=DataOrigin.LIVE_SOURCE,
                http_status=200,
            )

    prediction = SimpleNamespace(
        fixture_record_id=fixture.id,
        feature_snapshot_id=None,
        prediction_id="prediction-delayed-result",
        status=PredictionStatus.FROZEN,
    )
    score = SimpleNamespace(scored_at=received_at)
    captured: dict[str, datetime] = {}
    settlement_state = SimpleNamespace(settlements=(), scores=())

    class Factory:
        predictions = SimpleNamespace(predictions=(prediction,))
        settlements = settlement_state
        features = SimpleNamespace(get=lambda _snapshot_id: None)
        ledger = SimpleNamespace(events=(), audit=lambda: {"status": "VERIFIED"})

        def settle(
            self,
            result: VerifiedFixtureResult,
            *,
            settled_at: datetime,
        ):
            captured["settled_at"] = settled_at
            scores = (score,) if score_expected else ()
            settlement_state.scores = scores
            return SimpleNamespace(result=result), scores, True

    class SQL:
        def append_settlement(self, _settlement: object) -> bool:
            return True

        def append_scores(self, scores: tuple[object, ...]) -> int:
            return len(scores)

        def append_metric_snapshot(
            self,
            _metric: object,
            *,
            measured_at: datetime,
        ) -> bool:
            captured["measured_at"] = measured_at
            return True

        def append_events(self, _events: tuple[object, ...]) -> int:
            return 0

        def counts(self) -> dict[str, int]:
            return {}

    repository = PrequentialArtifactRepository(InMemoryArtifactStore())
    sql = SQL()
    monkeypatch.setattr(runner, "PrequentialSQLRepository", lambda _engine: sql)
    monkeypatch.setattr(runner, "_restore_factory", lambda *_args, **_kwargs: Factory())
    monkeypatch.setattr(runner, "_fixture_records", lambda *_args, **_kwargs: (fixture,))
    monkeypatch.setattr(
        runner,
        "segmented_metrics",
        lambda **_kwargs: ({},) if score_expected else (),
    )
    report = runner.run_settle(
        engine=object(),  # type: ignore[arg-type]
        artifacts=repository,
        config={"feature_contract": {"version": "test-v1"}},
        output=tmp_path,
        now=NOW,
        code_revision="test-revision",
        provider=DelayedProvider(),  # type: ignore[arg-type]
    )
    assert report["settlements_inserted"] == 1
    assert report["scores_inserted"] == int(score_expected)
    expected = {"settled_at": received_at}
    if score_expected:
        expected["measured_at"] = received_at
    assert captured == expected


def test_run_forecast_uses_execution_time_as_information_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import scripts.run_prequential_learning_factory as runner

    fixture = ProspectiveFixtureModel(
        id="fixture-record-open-window",
        idempotency_key="fixture:open-window",
        fixture_id="api-football:open-window",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=NOW + timedelta(minutes=130),
        provider="api-football",
        provider_fixture_id="987",
        registered_at=NOW - timedelta(days=1),
        registry_hash="a" * 64,
        code_revision="test-revision",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )
    captured: dict[str, list[datetime]] = {
        "gates": [],
        "models": [],
        "odds": [],
    }

    class SQL:
        def append_prediction(self, _prediction: object) -> bool:
            return True

        def append_events(self, _events: tuple[object, ...]) -> int:
            return 0

        def counts(self) -> dict[str, int]:
            return {}

    factory = SimpleNamespace(
        features=SimpleNamespace(snapshots=()),
        predictions=SimpleNamespace(predictions=()),
        ledger=SimpleNamespace(events=(), audit=lambda: {"status": "VERIFIED"}),
        forecast=lambda **_kwargs: SimpleNamespace(
            status=PredictionStatus.REJECTED_MISSING_GATE
        ),
    )
    model = SimpleNamespace(model_id="reference-global", version="v1")
    monkeypatch.setattr(runner, "PrequentialSQLRepository", lambda _engine: SQL())
    monkeypatch.setattr(
        runner,
        "_restore_factory",
        lambda *_args, **_kwargs: factory,
    )
    monkeypatch.setattr(
        runner,
        "_latest_fixtures",
        lambda *_args, **_kwargs: (fixture,),
    )

    def latest_gates(*_args: object, cutoff_at: datetime, **_kwargs: object):
        captured["gates"].append(cutoff_at)
        return {}

    def odds_evidence(*_args: object, cutoff_at: datetime, **_kwargs: object):
        captured["odds"].append(cutoff_at)
        return None

    def current_models(*_args: object, at: datetime, **_kwargs: object):
        captured["models"].append(at)
        return (model,)

    monkeypatch.setattr(runner, "_latest_gates", latest_gates)
    monkeypatch.setattr(runner, "_odds_evidence", odds_evidence)
    monkeypatch.setattr(runner, "_current_models", current_models)
    monkeypatch.setattr(
        runner,
        "_challenger_probabilities",
        lambda *_args, **_kwargs: None,
    )
    report = runner.run_forecast(
        engine=object(),  # type: ignore[arg-type]
        artifacts=PrequentialArtifactRepository(InMemoryArtifactStore()),
        config=_config(ROOT / "configs" / "prequential_learning_v1.json"),
        output=tmp_path,
        now=NOW,
        code_revision="test-revision",
        identities={},
    )
    assert report["cutoffs_due"] == 1
    assert captured == {
        "gates": [NOW],
        "models": [NOW],
        "odds": [NOW, NOW],
    }


def test_run_forecast_retry_skips_existing_prediction_before_new_odds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import scripts.run_prequential_learning_factory as runner

    fixture = ProspectiveFixtureModel(
        id="fixture-record-retry",
        idempotency_key="fixture:retry",
        fixture_id="api-football:retry",
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="home",
        away_team_id="away",
        kickoff_at=NOW + timedelta(minutes=130),
        provider="api-football",
        provider_fixture_id="988",
        registered_at=NOW - timedelta(days=1),
        registry_hash="a" * 64,
        code_revision="test-revision",
        cancelled=False,
        kickoff_reliable=True,
        append_only=True,
    )
    model = SimpleNamespace(model_id="reference-global", version="v1")
    existing = tuple(
        SimpleNamespace(
            fixture_record_id=fixture.id,
            cutoff_name=CutoffName.H_2,
            market=market,
            model_id=model.model_id,
            model_version=model.version,
        )
        for market in PredictionMarket
    )

    class SQL:
        def append_events(self, _events: tuple[object, ...]) -> int:
            return 0

        def counts(self) -> dict[str, int]:
            return {}

    factory = SimpleNamespace(
        features=SimpleNamespace(snapshots=()),
        predictions=SimpleNamespace(predictions=existing),
        ledger=SimpleNamespace(events=(), audit=lambda: {"status": "VERIFIED"}),
    )
    monkeypatch.setattr(runner, "PrequentialSQLRepository", lambda _engine: SQL())
    monkeypatch.setattr(runner, "_restore_factory", lambda *_args, **_kwargs: factory)
    monkeypatch.setattr(runner, "_latest_fixtures", lambda *_args, **_kwargs: (fixture,))
    monkeypatch.setattr(runner, "_current_models", lambda *_args, **_kwargs: (model,))
    monkeypatch.setattr(
        runner,
        "_latest_gates",
        lambda *_args, **_kwargs: pytest.fail("retry re-read mutable gates"),
    )
    monkeypatch.setattr(
        runner,
        "_odds_evidence",
        lambda *_args, **_kwargs: pytest.fail("retry re-read mutable odds"),
    )
    report = runner.run_forecast(
        engine=object(),  # type: ignore[arg-type]
        artifacts=PrequentialArtifactRepository(InMemoryArtifactStore()),
        config=_config(ROOT / "configs" / "prequential_learning_v1.json"),
        output=tmp_path,
        now=NOW,
        code_revision="test-revision",
        identities={},
    )
    assert report["cutoffs_due"] == 1
    assert report["feature_snapshots_inserted"] == 0
    assert report["predictions_frozen"] == 0
    assert report["predictions_rejected"] == 0


def _alembic(url: str) -> Config:
    value = Config(str(ROOT / "alembic.ini"))
    value.set_main_option("script_location", str(ROOT / "migrations"))
    value.set_main_option("sqlalchemy.url", url)
    return value


def test_training_asof_ignores_future_model_and_successful_run(
    tmp_path: Path,
) -> None:
    model_id = "challenger-global_five_leagues"
    current = SimpleNamespace(
        model_id=model_id,
        version="untrained-v1",
        created_at=NOW - timedelta(days=2),
        training_cutoff=None,
    )
    future = SimpleNamespace(
        model_id=model_id,
        version="future-model",
        created_at=NOW + timedelta(days=1),
        training_cutoff=NOW + timedelta(days=1),
    )
    baseline_factory = SimpleNamespace(models={"current": current})
    mutated_factory = SimpleNamespace(
        models={"current": current, "future": future}
    )
    assert _training_parent_model(
        baseline_factory,  # type: ignore[arg-type]
        model_id=model_id,
        as_of=NOW,
    ) is current
    assert _training_parent_model(
        mutated_factory,  # type: ignore[arg-type]
        model_id=model_id,
        as_of=NOW,
    ) is current

    database = tmp_path / "training-asof.db"
    url = f"sqlite+pysqlite:///{database.as_posix()}"
    command.upgrade(_alembic(url), "head")
    engine = build_engine(url)

    def training_row(
        identifier: str,
        finished_at: datetime,
    ) -> PrequentialTrainingRunModel:
        return PrequentialTrainingRunModel(
            id=identifier,
            training_run_id=identifier,
            model_id=model_id,
            previous_model_version="untrained-v1",
            next_model_version=f"model-{identifier}",
            status="CHALLENGER_VERSION_CREATED",
            started_at=finished_at,
            finished_at=finished_at,
            training_cutoff=finished_at,
            eligible_fixtures=30,
            represented_leagues=2,
            dataset_manifest_hash=None,
            dataset_manifest_r2_key=None,
            artifact_sha256=None,
            artifact_r2_key=None,
            fixture_ids=[],
            settlement_ids=[],
            competitions=[],
            feature_snapshot_ids=[],
            hyperparameters={},
            training_metrics={},
            code_revision="test-revision",
            promotion_status="PROMOTION_LOCKED",
            append_only=True,
        )

    past_finished = NOW - timedelta(days=2)
    with Session(engine) as session:
        session.add(training_row("training-past", past_finished))
        session.commit()
    assert _last_successful_training(engine, model_id, as_of=NOW) == past_finished
    with Session(engine) as session:
        session.add(
            training_row("training-future", NOW + timedelta(days=1))
        )
        session.commit()
    assert _last_successful_training(engine, model_id, as_of=NOW) == past_finished


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
            "group": "prospective-deep-state",
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


def test_prequential_cli_direct_entrypoint_imports_without_package_wrapper() -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_prequential_learning_factory.py"),
            "--help",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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
