from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import inspect

from robin.ingestion.scheduler import (
    BudgetLevel,
    BudgetState,
    CollectionWindow,
    FixtureCandidate,
    SchedulerWindowState,
    WindowStatus,
    adaptive_plan,
    quota_budget,
    record_window_result,
    window_states,
)
from robin.operations.burn_in import (
    AlertSeverity,
    HealthStatus,
    IncidentJournal,
    compute_daily_metrics,
    render_daily_report,
    render_weekly_report,
)
from robin.storage.database import build_engine
from robin.storage.durable import (
    DurableRecord,
    DurableRegistry,
    content_hash,
    read_bundle,
    stable_id,
    write_bundle,
)
from robin.storage.durable_schema import JALON4_TABLES
from scripts.manage_durable_registry import (
    acknowledge,
    append_bridge,
    replay_to_directory,
    stage,
    verify_registry,
)
from scripts.run_shadow_pipeline import pre_match_shadow

NOW = datetime(2026, 7, 24, 12, tzinfo=UTC)


def sample_record(kind: str = "quality_runs") -> DurableRecord:
    payload: dict[str, object] = {"status": "PASSED", "check": "durable"}
    return DurableRecord(
        kind=kind,
        business_key="sample",
        payload=payload,
        provider="internal",
        observed_at=NOW,
        ingested_at=NOW,
        source_run_id="run-1",
    )


def durable_registry() -> DurableRegistry:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    return DurableRegistry(engine, initialize=True)


def minimal_state(root: Path) -> Path:
    state = root / "state"
    (state / "runs").mkdir(parents=True)
    (state / "fixtures").mkdir()
    (state / "raw" / "observations" / "2026" / "07" / "24").mkdir(parents=True)
    payload = b'{"events":[{"id":"fixture-1"}]}'
    payload_hash = __import__("hashlib").sha256(payload).hexdigest()
    payload_path = state / "raw" / "payloads" / payload_hash[:2] / f"{payload_hash}.bin"
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(payload)
    run = {
        "run_id": "fixtures-123",
        "pipeline": "collect-fixtures",
        "status": "WORKFLOW_SUCCESS_LIVE_DATA",
        "started_at": NOW.isoformat(),
        "finished_at": NOW.isoformat(),
        "provider": "the-odds-api",
        "quota_used": 8,
        "quota_remaining": 19_992,
    }
    (state / "runs" / "fixtures-123.json").write_text(json.dumps(run), "utf-8")
    fixtures = [
        {
            "id": "fixture-1",
            "commence_time": "2026-08-21T18:45:00Z",
            "home_team": "Marseille",
            "away_team": "Strasbourg",
            "sport_title": "Ligue 1",
            "origin": "LIVE SOURCE",
            "collected_at": NOW.isoformat(),
        }
    ]
    (state / "fixtures" / "latest.json").write_text(json.dumps(fixtures), "utf-8")
    observation = {
        "observation_id": "obs-1",
        "provider": "the-odds-api",
        "endpoint": "/events",
        "received_at": NOW.isoformat(),
        "payload_hash": payload_hash,
        "schema_version": "v4",
        "raw_payload_location": f"{payload_hash[:2]}/{payload_hash}.bin",
    }
    observation_path = (
        state / "raw" / "observations" / "2026" / "07" / "24" / "obs-1.json"
    )
    observation_path.write_text(json.dumps(observation), "utf-8")
    return state


def test_schema_contient_les_tables_jalon4() -> None:
    expected = {
        "ingestion_runs",
        "raw_payloads",
        "provider_requests",
        "provider_entity_mappings",
        "bookmakers",
        "markets",
        "odds_snapshots",
        "prediction_runs",
        "predictions",
        "candidate_bets",
        "rejected_bets",
        "shadow_bets",
        "settlements",
        "quality_runs",
        "quality_results",
        "pipeline_incidents",
        "quota_usage",
        "scheduler_windows",
        "burn_in_daily_metrics",
    }
    assert expected <= JALON4_TABLES


def test_schema_cree_indexes_et_contraintes() -> None:
    registry = durable_registry()
    tables = set(inspect(registry.engine).get_table_names())
    assert JALON4_TABLES <= tables
    assert inspect(registry.engine).get_unique_constraints("raw_payloads")
    assert inspect(registry.engine).get_indexes("scheduler_windows")


def test_run_idempotent() -> None:
    registry = durable_registry()
    kwargs = dict(
        run_id="run-1",
        pipeline_name="test",
        started_at=NOW,
        status="PASSED",
        source_version="abc",
        backend="SQLITE",
    )
    assert registry.ensure_run(**kwargs)
    assert not registry.ensure_run(**kwargs)


def test_record_id_et_hash_stables() -> None:
    left = sample_record()
    right = sample_record()
    assert left.hash == right.hash
    assert left.record_id == right.record_id
    assert len(left.hash) == 64


def test_json_canonique_independant_ordre() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_append_exact_idempotent() -> None:
    registry = durable_registry()
    registry.ensure_run(
        run_id="run-1",
        pipeline_name="test",
        started_at=NOW,
        status="PASSED",
        source_version="abc",
        backend="SQLITE",
    )
    assert registry.append(sample_record())
    assert not registry.append(sample_record())


def test_append_version_modifiee_cree_nouvelle_ligne() -> None:
    registry = durable_registry()
    registry.ensure_run(
        run_id="run-1",
        pipeline_name="test",
        started_at=NOW,
        status="PASSED",
        source_version="abc",
        backend="SQLITE",
    )
    first = sample_record()
    second = DurableRecord(
        **{**first.__dict__, "payload": {"status": "WARNING", "check": "durable"}}
    )
    assert registry.append(first)
    assert registry.append(second)


def test_payload_brut_deduplique_par_hash() -> None:
    registry = durable_registry()
    kwargs = dict(
        payload_hash="a" * 64,
        provider="provider",
        object_location="aa/a.bin.gz",
        byte_size=12,
        observed_at=NOW,
        schema_version="v1",
    )
    assert registry.append_raw_payload(**kwargs)
    assert not registry.append_raw_payload(**kwargs)


def test_bundle_comprime_lisible(tmp_path: Path) -> None:
    path = tmp_path / "bundle.json.gz"
    manifest = write_bundle(
        path,
        run={"run_id": "run-1", "started_at": NOW.isoformat()},
        records=[sample_record()],
    )
    assert manifest["records"] == 1
    assert read_bundle(path)["schema_version"] == "shadow-bundle-v1"


def test_bundle_reproductible(tmp_path: Path) -> None:
    one = tmp_path / "one.gz"
    two = tmp_path / "two.gz"
    kwargs = dict(
        run={"run_id": "run-1", "started_at": NOW.isoformat()},
        records=[sample_record()],
    )
    write_bundle(one, **kwargs)
    write_bundle(two, **kwargs)
    assert one.read_bytes() == two.read_bytes()


def test_stage_capture_payload_et_fixture(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    result = stage(state, tmp_path / "outbox", "123")
    assert result["status"] == "DURABLE_WRITE_STAGED"
    assert result["objects"] == 1
    assert int(result["records"]) >= 3


def test_stage_detecte_payload_corrompu(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    payload = next((state / "raw" / "payloads").rglob("*.bin"))
    payload.write_bytes(b"corrompu")
    with pytest.raises(RuntimeError, match="hash brut invalide"):
        stage(state, tmp_path / "outbox", "123")


def test_bridge_append_et_verifie(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    outbox = tmp_path / "outbox"
    stage(state, outbox, "123")
    result = append_bridge(outbox, tmp_path / "registry")
    assert result["bundles_appended"] == 1
    assert verify_registry(tmp_path / "registry")["status"] == "PASSED"


def test_bridge_second_append_est_idempotent(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    outbox = tmp_path / "outbox"
    registry = tmp_path / "registry"
    stage(state, outbox, "123")
    append_bridge(outbox, registry)
    result = append_bridge(outbox, registry)
    assert result["bundles_appended"] == 0
    assert result["duplicates"] == 1


def test_verification_detecte_bundle_absent(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    outbox = tmp_path / "outbox"
    registry = tmp_path / "registry"
    stage(state, outbox, "123")
    append_bridge(outbox, registry)
    next((registry / "bundles").rglob("*.json.gz")).unlink()
    result = verify_registry(registry)
    assert result["status"] == "FAILED"
    assert result["errors"]


def test_replay_sans_appel_ni_quota(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    outbox = tmp_path / "outbox"
    registry = tmp_path / "registry"
    stage(state, outbox, "123")
    append_bridge(outbox, registry)
    result = replay_to_directory(registry, tmp_path / "replay")
    assert result["status"] == "REPLAY_CONFIRMED"
    assert result["provider_calls"] == 0
    assert result["quota_consumed"] == 0


def test_replay_restaure_octets_originaux(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    original = next((state / "raw" / "payloads").rglob("*.bin")).read_bytes()
    outbox = tmp_path / "outbox"
    registry = tmp_path / "registry"
    stage(state, outbox, "123")
    append_bridge(outbox, registry)
    replay_to_directory(registry, tmp_path / "replay")
    restored = next((tmp_path / "replay" / "raw").rglob("*.bin")).read_bytes()
    assert restored == original


def test_acknowledgement_stockage(tmp_path: Path) -> None:
    ack = acknowledge(tmp_path, backend="GIT_DATA_BRIDGE", commit="abc")
    assert ack["status"] == "DURABLE_WRITE_CONFIRMED"
    assert json.loads((tmp_path / "durable" / "last-ack.json").read_text())["commit"] == "abc"


@pytest.mark.parametrize(
    ("delta", "status"),
    [
        (timedelta(days=8), WindowStatus.PENDING),
        (timedelta(days=7), WindowStatus.DUE),
        (timedelta(days=7) - timedelta(hours=1), WindowStatus.MISSED_RECOVERABLE),
        (timedelta(days=7) - timedelta(hours=3), WindowStatus.MISSED_FINAL),
    ],
)
def test_statut_fenetre_selon_retard(delta: timedelta, status: WindowStatus) -> None:
    fixture = FixtureCandidate(provider_fixture_id="f", kickoff_at=NOW + delta)
    d7 = next(
        item
        for item in window_states((fixture,), now=NOW)
        if item.window == CollectionWindow.D7
    )
    assert d7.status == status


def test_fixture_annulee() -> None:
    fixture = FixtureCandidate(
        provider_fixture_id="f",
        kickoff_at=NOW + timedelta(days=7),
        active_scope=False,
    )
    assert {
        item.status for item in window_states((fixture,), now=NOW)
    } == {WindowStatus.CANCELLED_FIXTURE}


@pytest.mark.parametrize(
    ("used", "remaining", "forecast", "expected"),
    [
        (10, 19_000, 720, BudgetLevel.NORMAL),
        (100, 19_000, 900, BudgetLevel.CONSERVATIVE),
        (930, 4_100, 950, BudgetLevel.CRITICAL_RESERVE),
        (1_000, 19_000, 1_000, BudgetLevel.COLLECTION_PAUSED),
        (10, 4_000, 720, BudgetLevel.COLLECTION_PAUSED),
    ],
)
def test_niveaux_budget(
    used: int,
    remaining: int,
    forecast: int,
    expected: BudgetLevel,
) -> None:
    value = quota_budget(
        credits_used_today=used,
        credits_used_month=used,
        provider_remaining=remaining,
        forecast_month_end=forecast,
    )
    assert value.level == expected


def due_state(window: CollectionWindow) -> SchedulerWindowState:
    target = NOW
    return SchedulerWindowState(
        fixture_id="f",
        window=window,
        scheduled_for=target,
        acceptable_from=target - timedelta(minutes=20),
        acceptable_until=target + timedelta(hours=2),
        status=WindowStatus.DUE,
    )


def budget(level: BudgetLevel) -> BudgetState:
    return BudgetState(
        level=level,
        credits_used_today=0,
        credits_used_month=0,
        forecast_month_end=0,
        operational_ceiling=1_000,
        provider_remaining=20_000,
        reserve_credits=4_000,
        credits_near_kickoff_reserved=80,
        explanation="test",
    )


def test_plan_normal_conserve_fenetre_lointaine() -> None:
    fixture = FixtureCandidate(provider_fixture_id="f", kickoff_at=NOW + timedelta(days=7))
    tasks = adaptive_plan(
        (due_state(CollectionWindow.D7),),
        fixtures={"f": fixture},
        budget=budget(BudgetLevel.NORMAL),
    )
    assert tasks[0].window == CollectionWindow.D7


def test_plan_conservatif_protege_fenetres_proches() -> None:
    fixture = FixtureCandidate(provider_fixture_id="f", kickoff_at=NOW + timedelta(hours=3))
    tasks = adaptive_plan(
        (due_state(CollectionWindow.D7), due_state(CollectionWindow.H3)),
        fixtures={"f": fixture},
        budget=budget(BudgetLevel.CONSERVATIVE),
    )
    assert [task.window for task in tasks] == [CollectionWindow.H3]


def test_plan_critical_limite_h1_et_closing() -> None:
    fixture = FixtureCandidate(provider_fixture_id="f", kickoff_at=NOW + timedelta(hours=1))
    tasks = adaptive_plan(
        (due_state(CollectionWindow.H3), due_state(CollectionWindow.H1)),
        fixtures={"f": fixture},
        budget=budget(BudgetLevel.CRITICAL_RESERVE),
    )
    assert [task.window for task in tasks] == [CollectionWindow.H1]


def test_plan_pause_ne_fait_aucun_appel() -> None:
    fixture = FixtureCandidate(provider_fixture_id="f", kickoff_at=NOW)
    assert adaptive_plan(
        (due_state(CollectionWindow.M10),),
        fixtures={"f": fixture},
        budget=budget(BudgetLevel.COLLECTION_PAUSED),
    ) == ()


@pytest.mark.parametrize(
    ("provider_status", "received", "market", "expected"),
    [
        ("SUCCESS", True, True, WindowStatus.COLLECTED),
        ("FAILED", False, None, WindowStatus.PROVIDER_FAILED),
        ("EMPTY", False, None, WindowStatus.PROVIDER_EMPTY),
        ("SUCCESS", False, False, WindowStatus.NO_MARKET_AVAILABLE),
    ],
)
def test_resultat_fenetre_explique_absence(
    provider_status: str,
    received: bool,
    market: bool | None,
    expected: WindowStatus,
) -> None:
    state = due_state(CollectionWindow.H1)
    result = record_window_result(
        state,
        attempted_at=NOW,
        provider_status=provider_status,
        observation_received=received,
        market_available=market,
    )
    assert result.status == expected
    assert result.attempt_count == 1


def test_resultat_tardif() -> None:
    state = due_state(CollectionWindow.H1)
    result = record_window_result(
        state,
        attempted_at=NOW + timedelta(hours=1),
        provider_status="SUCCESS",
        observation_received=True,
        market_available=True,
    )
    assert result.status == WindowStatus.COLLECTED_LATE


def metric_kwargs() -> dict[str, object]:
    return {
        "metric_date": date(2026, 7, 24),
        "runs": [{"status": "PASSED"}] * 3,
        "fixtures": 9,
        "snapshots": 2,
        "windows": [{"status": "COLLECTED"}] * 3,
        "predictions": 1,
        "decisions": 1,
        "settlements": 0,
        "raw_observations": 3,
        "provenance_complete": 3,
        "duplicates": 0,
        "silent_losses": 0,
        "quota_used": 8,
        "quota_remaining": 19_992,
        "quota_limit": 20_000,
    }


def test_slo_healthy() -> None:
    metrics = compute_daily_metrics(**metric_kwargs())  # type: ignore[arg-type]
    assert metrics["health_status"] == HealthStatus.HEALTHY


def test_slo_perte_silencieuse_critique() -> None:
    kwargs = metric_kwargs()
    kwargs["silent_losses"] = 1
    metrics = compute_daily_metrics(**kwargs)  # type: ignore[arg-type]
    assert metrics["health_status"] == HealthStatus.CRITICAL
    assert "SILENT_DATA_LOSS" in metrics["slo_breaches"]


def test_slo_observation_insuffisante() -> None:
    kwargs = metric_kwargs()
    kwargs["runs"] = [{"status": "PASSED"}]
    kwargs["windows"] = []
    metrics = compute_daily_metrics(**kwargs)  # type: ignore[arg-type]
    assert metrics["health_status"] == HealthStatus.INSUFFICIENT_OBSERVATION


def test_slo_quota_degrade() -> None:
    kwargs = metric_kwargs()
    kwargs["quota_remaining"] = 3_000
    metrics = compute_daily_metrics(**kwargs)  # type: ignore[arg-type]
    assert "QUOTA_RESERVE" in metrics["slo_breaches"]


def test_incident_sans_spam(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path / "incidents.jsonl")
    kwargs = dict(
        code="STORAGE_DOWN",
        severity=AlertSeverity.CRITICAL,
        cause="test",
        impact="test",
    )
    assert journal.open(**kwargs)
    assert not journal.open(**kwargs)
    assert len(journal.read_all()) == 1


def test_incident_resolution_versionnee(tmp_path: Path) -> None:
    journal = IncidentJournal(tmp_path / "incidents.jsonl")
    journal.open(
        code="STORAGE_DOWN",
        severity=AlertSeverity.CRITICAL,
        cause="test",
        impact="test",
    )
    assert journal.resolve(code="STORAGE_DOWN", correction="replay")
    assert journal.read_all()[-1]["status"] == "RESOLVED"


def test_rapport_quotidien_interdit_conclusion() -> None:
    report = render_daily_report(compute_daily_metrics(**metric_kwargs()))  # type: ignore[arg-type]
    assert "AUCUNE CONCLUSION STATISTIQUE" in report
    assert "PRODUCTION_LOCKED" in report


def test_rapport_hebdomadaire_interdit_conclusion() -> None:
    metrics = compute_daily_metrics(**metric_kwargs())  # type: ignore[arg-type]
    report = render_weekly_report([metrics])
    assert "AUCUNE CONCLUSION STATISTIQUE" in report


def test_prediction_bloquee_sans_stockage_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = minimal_state(tmp_path)
    monkeypatch.setenv("DURABLE_STORAGE_REQUIRED", "true")
    summary = pre_match_shadow(state, mock=False)
    blocked = json.loads((state / "predictions" / "blocked.json").read_text())
    assert summary["predictions"] == 0
    assert blocked[0]["reason"] == "DURABLE_STORAGE_UNAVAILABLE"


def test_configuration_reste_verrouillee_et_durable() -> None:
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "configs" / "shadow_v1.yaml").read_text())
    assert config["real_bets_enabled"] is False
    assert config["persistence"]["durable_storage_required"] is True
    assert config["persistence"]["data_branch"] == "shadow-data"
    assert config["burn_in"]["statistical_observation"] == "descriptive_only"


def test_workflows_utilisent_double_ecriture() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (
        "collect-fixtures.yml",
        "collect-odds.yml",
        "pre-match-shadow.yml",
        "post-match-settlement.yml",
        "daily-health.yml",
    ):
        text = (root / ".github" / "workflows" / name).read_text()
        assert "./.github/actions/durable-shadow" in text
        assert "contents: write" in text
        assert "DATABASE_URL" in text


def test_diagnostic_manuel_est_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / ".github" / "workflows" / "shadow-diagnostics.yml").read_text()
    assert "workflow_dispatch" in text
    assert "contents: read" in text
    assert "shadow_diagnostics.py" in text
    assert "ODDS_API_KEY" in text
    assert "API_FOOTBALL_KEY" in text


def test_objet_compresse_est_bien_gzip(tmp_path: Path) -> None:
    state = minimal_state(tmp_path)
    outbox = tmp_path / "outbox"
    stage(state, outbox, "123")
    object_path = next((outbox / "objects").rglob("*.bin.gz"))
    with gzip.open(object_path, "rb") as stream:
        assert stream.read().startswith(b"{")


def test_stable_id_uuid_deterministe() -> None:
    assert stable_id("fixture", "1") == stable_id("fixture", "1")
    assert stable_id("fixture", "1") != stable_id("fixture", "2")
