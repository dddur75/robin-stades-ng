from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from robin.domain.enums import DataAvailability, DataOrigin
from robin.historical.features import (
    assert_temporal_integrity,
    build_team_feature_rows,
)
from robin.historical.modeling import backtest_fixed_stake, train_elo_baseline
from robin.historical.normalization import normalize_records
from robin.historical.orchestrator import (
    build_backfill_plan,
    quota_decision,
    select_validated_competition,
)
from robin.historical.pagination import iterate_pages
from robin.historical.storage import GzipPayloadBackend, PartitionedParquetStore
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import ProviderResult, QuotaState
from robin.storage.database import build_engine
from robin.storage.models import Base
from scripts.build_cockpit_snapshot import (
    build_player_readiness,
    sanitize_public_snapshot,
)
from scripts.manage_historical_state import append_state, restore_state, verify_state
from scripts.run_historical_pipeline import (
    batched_rows,
    build_observed_forecast,
    command_persist,
    command_pilot,
)


def result(
    page: int,
    total: int,
    records: list[dict[str, Any]],
    *,
    payload_hash: str | None = None,
    remaining: int = 1000,
    availability: DataAvailability | None = None,
) -> ProviderResult:
    now = datetime.now(UTC)
    return ProviderResult(
        provider="api-football",
        endpoint="players",
        availability=availability
        or (DataAvailability.PRESENT if records else DataAvailability.ABSENT),
        records=tuple(records),
        observed_at=now,
        received_at=now,
        origin=DataOrigin.LIVE_SOURCE,
        raw_payload_hash=payload_hash or f"{page:064d}",
        raw_observation_id=f"raw-{page}",
        quota=QuotaState(remaining=remaining, limit=10000),
        http_status=200,
        paging_current=page,
        paging_total=total,
    )


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self.headers = {"x-ratelimit-requests-remaining": "9000"}
        self.content = json.dumps(payload).encode()
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get(self, _: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(dict(kwargs["params"]))
        page = int(kwargs["params"].get("page", 1))
        return FakeResponse(
            {
                "paging": {"current": page, "total": 1},
                "response": [{"player": {"id": 1}}],
            }
        )


def test_adaptateur_api_football_pilote_les_identifiants_reels() -> None:
    transport = RecordingTransport()
    provider = ApiFootballProvider(
        api_key="secret-test",
        season=2025,
        league_id=61,
        transport=transport,
    )
    provider.get_players(team_id=85, page=3)
    provider.get_lineups(fixture_id=123)
    provider.get_team_statistics(team_id=85, date="2025-03-01")
    assert transport.calls == [
        {"season": 2025, "page": 3, "team": 85},
        {"fixture": 123},
        {"league": 61, "season": 2025, "team": 85, "date": "2025-03-01"},
    ]
    assert "secret-test" not in json.dumps(transport.calls)


def test_erreur_metier_http_200_est_un_echec_sans_fuite() -> None:
    class ErrorTransport:
        def get(self, *_: Any, **__: Any) -> FakeResponse:
            return FakeResponse(
                {
                    "errors": {"season": "combinaison invalide"},
                    "paging": {"current": 1, "total": 1},
                    "response": [],
                }
            )

    provider = ApiFootballProvider(
        api_key="secret-invalid",
        transport=ErrorTransport(),
    )
    response = provider.get_competitions(search="Ligue 1", season=2025)
    assert response.availability == DataAvailability.ERROR
    assert response.message == "provider_response_errors"
    assert "secret-invalid" not in response.model_dump_json()


def test_pagination_une_et_plusieurs_pages(tmp_path: Path) -> None:
    calls: list[int] = []

    def fetch(page: int) -> ProviderResult:
        calls.append(page)
        return result(page, 3, [{"id": page}])

    outcome = iterate_pages(
        endpoint="players",
        parameters_hash="x",
        fetch_page=fetch,
        checkpoint_path=tmp_path / "checkpoint.json",
    )
    assert outcome.manifest.status == "COMPLETED"
    assert [record["id"] for record in outcome.records] == [1, 2, 3]
    assert calls == [1, 2, 3]

    replay_calls: list[int] = []
    replay = iterate_pages(
        endpoint="players",
        parameters_hash="x",
        fetch_page=lambda page: replay_calls.append(page) or result(page, 1, []),
        checkpoint_path=tmp_path / "checkpoint.json",
    )
    assert replay.manifest.replayed
    assert replay_calls == []


def test_pagination_page_vide_finale_et_intermediaire(tmp_path: Path) -> None:
    final = iterate_pages(
        endpoint="players",
        parameters_hash="final",
        fetch_page=lambda page: result(page, 2, [{"id": 1}] if page == 1 else []),
        checkpoint_path=tmp_path / "final.json",
    )
    assert final.manifest.status == "COMPLETED"
    partial = iterate_pages(
        endpoint="players",
        parameters_hash="partial",
        fetch_page=lambda page: result(page, 3, [{"id": 1}] if page == 1 else []),
        checkpoint_path=tmp_path / "partial.json",
    )
    assert partial.manifest.status == "PARTIAL"
    assert partial.manifest.error_code == "EMPTY_INTERMEDIATE_PAGE"


def test_pagination_detecte_page_dupliquee_et_incoherente(tmp_path: Path) -> None:
    duplicate = iterate_pages(
        endpoint="players",
        parameters_hash="duplicate",
        fetch_page=lambda page: result(
            page,
            2,
            [{"id": page}],
            payload_hash="a" * 64,
        ),
        checkpoint_path=tmp_path / "duplicate.json",
    )
    assert duplicate.manifest.error_code == "DUPLICATE_PAGE_PAYLOAD"
    inconsistent = iterate_pages(
        endpoint="players",
        parameters_hash="bad",
        fetch_page=lambda _: result(2, 1, [{"id": 1}]),
        checkpoint_path=tmp_path / "bad.json",
    )
    assert inconsistent.manifest.error_code == "INCONSISTENT_PAGINATION"
    permanent = iterate_pages(
        endpoint="players",
        parameters_hash="permanent",
        fetch_page=lambda page: result(
            page,
            1,
            [],
            availability=DataAvailability.ERROR,
        ).model_copy(update={"http_status": 403}),
        checkpoint_path=tmp_path / "permanent.json",
    )
    assert permanent.manifest.status == "FAILED"
    assert permanent.manifest.error_code == "HTTP_403"


def test_pagination_reprise_erreur_temporaire_et_quota(tmp_path: Path) -> None:
    attempts = 0

    def transient(page: int) -> ProviderResult:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.ConnectionError("temporaire")
        return result(page, 1, [{"id": 1}])

    # Le callback de production convertit les erreurs réseau en erreur fournisseur.
    from robin.providers.contracts import TransientProviderError

    def converted(page: int) -> ProviderResult:
        try:
            return transient(page)
        except requests.ConnectionError as exc:
            raise TransientProviderError("temporaire") from exc

    first = iterate_pages(
        endpoint="players",
        parameters_hash="resume",
        fetch_page=converted,
        checkpoint_path=tmp_path / "resume.json",
    )
    assert first.manifest.status == "RETRYABLE"
    second = iterate_pages(
        endpoint="players",
        parameters_hash="resume",
        fetch_page=converted,
        checkpoint_path=tmp_path / "resume.json",
    )
    assert second.manifest.status == "COMPLETED"
    paused = iterate_pages(
        endpoint="players",
        parameters_hash="quota",
        fetch_page=lambda page: result(page, 2, [{"id": page}], remaining=10),
        checkpoint_path=tmp_path / "quota.json",
        quota_reserve=10,
    )
    assert paused.manifest.status == "PAUSED_QUOTA"


def test_stockage_gzip_et_parquet_sont_idempotents(tmp_path: Path) -> None:
    backend = GzipPayloadBackend(tmp_path / "raw")
    payload = b'{"response":[{"id":1}]}'
    key = f"{__import__('hashlib').sha256(payload).hexdigest()}.bin"
    location = backend.put_if_absent(key, payload)
    assert location.endswith(".gz")
    assert backend.read(location) == payload

    store = PartitionedParquetStore(tmp_path / "parquet")
    first = store.write_records(
        [{"id": 1, "missing": None, "nested": {"x": 1}}],
        competition="Ligue 1",
        season=2025,
        entity_type="players",
        dataset_version="v1",
    )
    second = store.write_records(
        [{"id": 1, "missing": None, "nested": {"x": 1}}],
        competition="Ligue 1",
        season=2025,
        entity_type="players",
        dataset_version="v1",
    )
    assert first["inserted"] == 1
    assert second["inserted"] == 0
    assert second["duplicates_avoided"] == 1
    assert store.validate() == []


def test_pont_historique_verifie_hash_et_restaure(tmp_path: Path) -> None:
    state = tmp_path / "state"
    registry = tmp_path / "registry"
    raw = b'{"response":[{"id":61}]}'
    digest = hashlib.sha256(raw).hexdigest()
    payload = state / "raw" / "payloads" / digest[:2] / f"{digest}.bin.gz"
    payload.parent.mkdir(parents=True)
    import gzip

    payload.write_bytes(gzip.compress(raw, mtime=0))
    first = append_state(state, registry)
    second = append_state(state, registry)
    assert first["copied"] == 1
    assert second["unchanged"] == 1
    assert verify_state(registry)["status"] == "VERIFIED"
    destination = tmp_path / "restored"
    assert restore_state(registry, destination)["files"] == 1
    assert (destination / payload.relative_to(state)).read_bytes() == payload.read_bytes()


def test_normalisation_ne_transforme_pas_absence_en_zero() -> None:
    rows = normalize_records(
        "players",
        [{"player": {"id": 7, "name": "A"}, "statistics": [{"goals": None}]}],
        competition_id=61,
        season=2025,
        ingestion_run_id="run",
        raw_payload_hash="a" * 64,
    )
    assert rows[0]["availability_status"] == "POINT_IN_TIME_SAFE"
    assert rows[0]["payload"]["statistics"][0]["goals"] is None  # type: ignore[index]


def test_features_nutilisent_jamais_le_resultat_du_match_cible() -> None:
    base = [
        {
            "match_id": "m1",
            "league": "F1",
            "season": "2024-25",
            "date": "2024-08-01T18:00:00+00:00",
            "home": "Paris",
            "away": "Lyon",
            "fthg": 1,
            "ftag": 0,
        },
        {
            "match_id": "m2",
            "league": "F1",
            "season": "2024-25",
            "date": "2024-08-08T18:00:00+00:00",
            "home": "Paris",
            "away": "Lyon",
            "fthg": 2,
            "ftag": 2,
        },
    ]
    changed = [{**base[0], "fthg": 9, "ftag": 9}, base[1]]
    original_rows = build_team_feature_rows(base)
    changed_rows = build_team_feature_rows(changed)
    assert original_rows[0]["home_elo"] == changed_rows[0]["home_elo"]
    assert original_rows[0]["home_form_5"] == changed_rows[0]["home_form_5"]
    assert original_rows[1]["home_elo"] != changed_rows[1]["home_elo"]
    assert_temporal_integrity(original_rows)


def test_saison_oos_ne_regle_pas_les_parametres_du_modele() -> None:
    rows = build_team_feature_rows(
        [
            {
                "match_id": f"m-{season}",
                "league": "F1",
                "season": f"{season}-{str(season + 1)[-2:]}",
                "date": f"{season}-08-01T18:00:00+00:00",
                "home": "A",
                "away": "B",
                "fthg": season % 3,
                "ftag": (season + 1) % 3,
                "psh": 2.0,
                "psd": 3.2,
                "psa": 3.8,
            }
            for season in range(2018, 2026)
        ]
    )
    first = train_elo_baseline(rows, dataset_hash="fixed")
    mutated = [
        {
            **row,
            "target_home_goals": 20 if int(row["season"]) >= 2024 else row["target_home_goals"],
        }
        for row in rows
    ]
    second = train_elo_baseline(mutated, dataset_hash="fixed")
    assert first["parameters"] == second["parameters"]
    assert first["artifact_hash"] == second["artifact_hash"]
    assert first["discovery_metrics"] == second["discovery_metrics"]


def test_backtest_reste_verrouille_et_plan_priorise_ligue_1() -> None:
    rows = build_team_feature_rows(
        [
            {
                "match_id": "m",
                "league": "F1",
                "season": "2024-25",
                "date": "2024-08-01T18:00:00+00:00",
                "home": "A",
                "away": "B",
                "fthg": 1,
                "ftag": 0,
                "psh": 3.0,
                "psd": 3.0,
                "psa": 3.0,
            }
        ]
    )
    assert backtest_fixed_stake(rows)["production_status"] == "PRODUCTION_LOCKED"
    plan = build_backfill_plan({"Ligue 1": 61, "Premier League": 39})
    assert plan[0].competition_id == 61
    assert quota_decision(
        1000,
        requested_calls=500,
        reserve=100,
        accelerated=True,
    ).callable_budget == 500


def test_identifiant_competition_est_valide_par_reponse_fournisseur() -> None:
    records = (
        {
            "league": {"id": 61, "name": "Ligue 1"},
            "country": {"name": "France"},
        },
    )
    assert select_validated_competition(
        records,
        expected_name="Ligue 1",
        expected_country="France",
    ) == (61, records[0])


def test_parquet_preserve_none(tmp_path: Path) -> None:
    path = tmp_path / "value.parquet"
    pd.DataFrame([{"value": None}, {"value": 1.0}]).to_parquet(path)
    restored = pd.read_parquet(path)
    assert pd.isna(restored.iloc[0]["value"])


def test_workflows_jalon5_sont_valides_et_secrets_absents_du_frontend() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = {
        "api-football-coverage.yml",
        "historical-backfill.yml",
        "historical-quality.yml",
        "feature-factory.yml",
        "model-training.yml",
        "historical-backtesting.yml",
        "cockpit-refresh.yml",
    }
    workflows = root / ".github" / "workflows"
    assert expected <= {path.name for path in workflows.glob("*.yml")}
    for name in expected:
        payload = yaml.safe_load((workflows / name).read_text("utf-8"))
        assert isinstance(payload, dict)
        assert "jobs" in payload
    backfill_workflow = (workflows / "historical-backfill.yml").read_text("utf-8")
    assert "first-batch" not in backfill_workflow
    assert "if [ ! -f data/historical/tasks/backfill-plan.json ]" in backfill_workflow
    frontend = "\n".join(
        path.read_text("utf-8")
        for path in (root / "cockpit").rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx", ".json"}
    )
    assert "API_FOOTBALL_KEY" not in frontend
    assert "DATABASE_URL" not in frontend
    assert "ODDS_API_KEY" not in frontend


def test_preuve_postgresql_est_publiee_apres_la_synchronisation() -> None:
    root = Path(__file__).resolve().parents[2]
    action = (
        root / ".github" / "actions" / "historical-state-persist" / "action.yml"
    ).read_text("utf-8")
    sync = action.index("name: Synchroniser PostgreSQL")
    proof = action.index("name: Publier l'accusé PostgreSQL durable")
    assert sync < proof
    assert "steps.postgresql.outcome == 'success'" in action
    assert "historical/proofs/postgresql.json" in action


def test_upsert_neon_est_decoupe_sous_la_limite_psycopg() -> None:
    rows = [{"task_id": str(index)} for index in range(2_501)]
    batches = batched_rows(rows)
    assert [len(batch) for batch in batches] == [1_000, 1_000, 501]
    assert [row for batch in batches for row in batch] == rows


def test_snapshot_public_ne_divulgue_pas_les_chemins_de_runner() -> None:
    value = {
        "path": (
            "/home/runner/work/repository/data/historical/parquet/"
            "competition=Ligue-1/part.parquet"
        )
    }
    assert sanitize_public_snapshot(value) == {
        "path": "historical/parquet/competition=Ligue-1/part.parquet"
    }


def test_prevision_et_readiness_reposent_sur_letat_courant(
    tmp_path: Path,
) -> None:
    state = tmp_path / "historical"
    run_path = state / "runs" / "pilot-ligue-1-2025.json"
    run_path.parent.mkdir(parents=True)
    run_path.write_text(
        json.dumps(
            {
                "started_at": "2026-07-25T07:00:00+00:00",
                "finished_at": "2026-07-25T07:01:40+00:00",
                "provider_calls": 100,
                "fixtures": 20,
                "normalized_rows": 800,
                "raw_compressed_bytes": 100_000,
            }
        ),
        encoding="utf-8",
    )
    plan_path = state / "tasks" / "backfill-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {"status": "READY", "priority": "A", "estimated_calls": 1},
                    {"status": "READY", "priority": "A", "estimated_calls": 1},
                    {"status": "READY", "priority": "B", "estimated_calls": 2},
                ]
            }
        ),
        encoding="utf-8",
    )
    forecast = build_observed_forecast(state)
    assert forecast["estimated_calls_full_scope"] == 4
    assert forecast["eta_priority_a_days"] == 0.0
    assert forecast["eta_priority_b_days"] == 0.0
    readiness = build_player_readiness(state, {"status": "PASSED"}, forecast)
    assert len(readiness["families"]) == 12
    assert readiness["status"] == "BLOCKED_BY_COVERAGE"


def test_persistance_compte_une_table_sans_colonne_id(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'historical.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    state = tmp_path / "state"
    tasks = build_backfill_plan({"Ligue 1": 61})
    plan_path = state / "tasks" / "backfill-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps({"tasks": [task.model_dump(mode="json") for task in tasks]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    command_persist(argparse.Namespace(state=state))
    proof = json.loads((state / "proofs" / "postgresql.json").read_text("utf-8"))
    assert proof["status"] == "POSTGRESQL_CONNECTED"
    assert proof["table_counts"]["historical_backfill_tasks"] == len(tasks)


def test_persistance_enregistre_le_lot_courant_et_reste_idempotente(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'historical-runs.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    state = tmp_path / "state"
    plan_path = state / "tasks" / "backfill-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps(
            {
                "tasks": [],
                "last_run_id": "run-current",
                "last_run_started_at": "2026-07-25T07:50:13+00:00",
                "last_run_at": "2026-07-25T07:51:52+00:00",
                "provider_calls": 99,
                "normalized_rows_this_run": 1597,
                "quota_remaining": 149895,
                "status": "HISTORICAL_BACKFILL_ACTIVE",
                "stopped_reason": None,
                "scheduler": {"mode": "ACCELERATED_SAFE"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    command_persist(argparse.Namespace(state=state))
    command_persist(argparse.Namespace(state=state))
    proof = json.loads((state / "proofs" / "postgresql.json").read_text("utf-8"))
    assert proof["table_counts"]["historical_ingestion_runs"] == 1
    assert proof["rows_inserted"] == 0
    assert proof["rows_updated"] == 1


def test_replay_pilote_ne_rappelle_pas_le_fournisseur(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    state = tmp_path / "state"
    summary = state / "runs" / "pilot-ligue-1-2025.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        json.dumps(
            {
                "status": "HISTORICAL_PILOT_VERIFIED",
                "run_id": "live-run",
                "finished_at": "2026-07-24T22:11:34+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    command_pilot(
        argparse.Namespace(
            state=state,
            force=False,
            run_id="replay-run",
            max_calls=1_500,
            quota_reserve=100,
        )
    )
    proof = json.loads((state / "proofs" / "pilot-replay.json").read_text("utf-8"))
    assert proof["status"] == "PILOT_REPLAY_VERIFIED"
    assert proof["provider_calls"] == 0
    assert proof["quota_consumed"] == 0
    assert proof["business_rows_inserted"] == 0
