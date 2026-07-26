from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from robin.historical.canonical import (
    CanonicalScope,
    CompetitionFormat,
    canonicalize_fixtures,
    validate_canonical_cardinality,
)
from robin.historical.normalization import normalize_records
from robin.historical.quality import (
    historical_quality_report,
    repair_raw_hash_provenance,
)
from robin.historical.scheduling import (
    BackfillTelemetry,
    accelerated_safe_plan,
)
from robin.historical.storage import HistoricalBundleStore, PartitionedParquetStore
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import RateLimitError, TransientProviderError
from scripts.manage_historical_state import append_state, restore_state, verify_state
from scripts.run_historical_pipeline import command_features


def fixture(
    provider_id: int,
    *,
    home_id: int = 1,
    away_id: int = 2,
    round_name: str = "Regular Season - 1",
    status: str = "FT",
    kickoff: str = "2025-08-01T18:00:00+00:00",
) -> dict[str, Any]:
    return {
        "internal_id": f"internal-{provider_id}",
        "observed_at": "2026-07-24T22:00:00+00:00",
        "payload": {
            "fixture": {
                "id": provider_id,
                "date": kickoff,
                "status": {"short": status},
            },
            "league": {"id": 61, "season": 2025, "round": round_name},
            "teams": {
                "home": {"id": home_id, "name": f"Team {home_id}"},
                "away": {"id": away_id, "name": f"Team {away_id}"},
            },
        },
    }


def classify(records: list[dict[str, Any]]) -> list[dict[str, object]]:
    return canonicalize_fixtures(
        records,
        competition_id=61,
        season=2025,
        competition_format=CompetitionFormat(team_count=18),
    )


def test_canonicalisation_reports_doublons_report_annulation_et_playoffs() -> None:
    rows = classify(
        [
            fixture(1),
            fixture(2, kickoff="2025-08-02T18:00:00+00:00"),
            fixture(3, home_id=3, away_id=4, status="CANC"),
            fixture(
                4,
                home_id=19,
                away_id=20,
                round_name="Relegation round - Quarter-finals",
            ),
            fixture(5, home_id=21, away_id=22, round_name="Final"),
        ]
    )
    assert [row["canonical_scope"] for row in rows] == [
        CanonicalScope.REGULAR_SEASON_CANONICAL,
        CanonicalScope.RESCHEDULED_VERSION,
        CanonicalScope.CANCELLED,
        CanonicalScope.RELEGATION_PLAYOFF,
        CanonicalScope.RELEGATION_PLAYOFF,
    ]
    duplicate = classify([fixture(10), fixture(10)])
    assert duplicate[1]["canonical_scope"] == CanonicalScope.DUPLICATE_FIXTURE


def test_changement_identifiant_et_equipe_hors_phase_sont_exclus() -> None:
    rows = classify(
        [
            fixture(1),
            fixture(99),
            fixture(
                100,
                home_id=999,
                away_id=2,
                round_name="Relegation round - Quarter-finals",
            ),
        ]
    )
    assert rows[1]["canonical_scope"] == CanonicalScope.DUPLICATE_FIXTURE
    assert rows[2]["home_team_id"] == 999
    assert rows[2]["exclusion_reason"] == CanonicalScope.RELEGATION_PLAYOFF


def season_rows(team_count: int) -> list[dict[str, object]]:
    records: list[dict[str, Any]] = []
    provider_id = 1
    for home_id in range(1, team_count + 1):
        for away_id in range(1, team_count + 1):
            if home_id == away_id:
                continue
            records.append(
                fixture(
                    provider_id,
                    home_id=home_id,
                    away_id=away_id,
                    round_name=f"Regular Season - {provider_id}",
                )
            )
            provider_id += 1
    return canonicalize_fixtures(
        records,
        competition_id=61,
        season=2025,
        competition_format=CompetitionFormat(team_count=team_count),
    )


@pytest.mark.parametrize(("teams", "fixtures"), [(18, 306), (20, 380)])
def test_cardinalite_depend_du_format_de_saison(teams: int, fixtures: int) -> None:
    rows = season_rows(teams)
    result = validate_canonical_cardinality(rows, CompetitionFormat(team_count=teams))
    assert result["status"] == "PASSED"
    assert result["canonical_fixtures"] == fixtures


def test_feature_factory_bloquee_si_cardinalite_incoherente(tmp_path: Path) -> None:
    audit = tmp_path / "audits" / "ligue1-2025-canonicalization.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(json.dumps({"status": "FAILED"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="CANONICAL_CARDINALITY"):
        command_features(argparse.Namespace(state=tmp_path))


def test_plan_accelerated_safe_protege_quota_erreurs_429_et_stockage() -> None:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    active = accelerated_safe_plan(
        BackfillTelemetry(quota_remaining=148_439),
        now=now,
    )
    assert active.mode == "ACCELERATED_SAFE"
    assert 0 < active.max_calls <= 2_500
    assert active.max_tasks > 0
    assert active.next_run_at > now
    expanded = accelerated_safe_plan(
        BackfillTelemetry(
            quota_remaining=148_439,
            mean_calls_per_task=1.0,
            mean_seconds_per_call=1.0,
        ),
        now=now,
    )
    assert expanded.max_calls == 2_500
    assert expanded.max_tasks == 2_500
    assert accelerated_safe_plan(
        BackfillTelemetry(quota_remaining=5_000),
        now=now,
    ).stop_reason == "QUOTA_PROTECTED"
    assert accelerated_safe_plan(
        BackfillTelemetry(quota_remaining=100_000, recent_error_rate=0.051),
        now=now,
    ).stop_reason == "ERROR_RATE_ABOVE_5_PERCENT"
    assert accelerated_safe_plan(
        BackfillTelemetry(quota_remaining=100_000, recent_429_count=1),
        now=now,
    ).stop_reason == "HTTP_429_CIRCUIT_OPEN"
    assert accelerated_safe_plan(
        BackfillTelemetry(quota_remaining=100_000, storage_bytes=900_000_000),
        now=now,
    ).stop_reason == "STORAGE_PAUSE_THRESHOLD"


def test_bundle_compacte_verifie_et_rejoue_individuellement(tmp_path: Path) -> None:
    state = tmp_path / "state"
    first = state / "raw" / "payloads" / "aa" / "first.json.gz"
    second = state / "raw" / "observations" / "second.json"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    bundle = HistoricalBundleStore(state)
    manifest = bundle.create_bundle(
        [first, second],
        run_id="run-1",
        competition="Ligue 1",
        season=2025,
        endpoint="fixtures",
        remove_sources=True,
    )
    manifest_path = state / str(manifest["archive"]).replace(
        ".tar.gz",
        ".manifest.json",
    )
    assert not first.exists()
    assert bundle.verify_bundle(manifest_path)["files"] == 2
    assert bundle.replay_file(manifest_path, "raw/observations/second.json") == b"second"


def test_pont_migre_les_bundles_sans_perte_et_les_restaure(tmp_path: Path) -> None:
    state = tmp_path / "state"
    source = state / "raw" / "observations" / "one.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"payload")
    HistoricalBundleStore(state).create_bundle(
        [source],
        run_id="run-1",
        competition="Ligue 1",
        season=2025,
        endpoint="fixtures",
        remove_sources=True,
    )
    registry = tmp_path / "registry"
    append_state(state, registry)
    assert verify_state(registry)["status"] == "VERIFIED"
    restored = tmp_path / "restored"
    proof = restore_state(registry, restored)
    assert proof["bundle_files_replayed"] == 1
    assert (restored / "raw" / "observations" / "one.json").read_bytes() == b"payload"


def test_repare_la_provenance_depuis_le_cache_sans_appel_fournisseur(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    record = {
        "fixture": {"id": 7},
        "time": {"elapsed": 10},
        "comments": None,
    }
    raw = json.dumps({"response": [record]}, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    payload = state / "raw" / "payloads" / digest[:2] / f"{digest}.bin.gz"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(gzip.compress(raw, mtime=0))
    observation = state / "raw" / "observations" / "observation.json"
    observation.parent.mkdir(parents=True)
    observation.write_text(
        json.dumps(
            {
                "observation_id": "observation",
                "provider": "api-football",
                "endpoint": "fixtures/events",
                "request_parameters": {"fixture": 7},
                "requested_at": "2026-07-25T08:00:00+00:00",
                "received_at": "2026-07-25T08:00:01+00:00",
                "http_status": 200,
                "payload_hash": digest,
                "schema_version": "j2-v1",
                "ingestion_run_id": "run-1",
                "raw_payload_location": f"{digest[:2]}/{digest}.bin.gz",
            }
        ),
        encoding="utf-8",
    )
    rows = normalize_records(
        "fixtures/events",
        [record],
        competition_id=61,
        season=2025,
        ingestion_run_id="run-1",
        raw_payload_hash=None,
        observed_at=datetime(2026, 7, 25, 8, 0, 1, tzinfo=UTC),
    )
    store = PartitionedParquetStore(state / "parquet")
    result = store.write_records(
        rows,
        competition="Ligue 1",
        season=2025,
        entity_type="fixture_events",
        dataset_version="api-football-v3",
    )
    audit = state / "audits" / "ligue1-2025-canonicalization.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "status": "PASSED",
                "canonical_fixtures": 306,
                "expected_fixtures": 306,
            }
        ),
        encoding="utf-8",
    )

    repair = repair_raw_hash_provenance(state)
    assert repair == {
        "status": "REPAIRED",
        "provider_calls": 0,
        "quota_consumed": 0,
        "files_rewritten": 1,
        "rows_repaired": 1,
        "rows_unresolved": 0,
        "rows_ambiguous": 0,
    }
    restored = pd.read_parquet(result["path"])
    assert restored.iloc[0]["raw_payload_hash"] == digest
    assert json.loads(restored.iloc[0]["payload"])["comments"] is None
    quality = historical_quality_report(state)
    assert quality["status"] == "PASSED"
    assert quality["provenance_rows"] == 1


def test_provenance_ignores_external_market_partitions(tmp_path: Path) -> None:
    state = tmp_path / "historical"
    external = PartitionedParquetStore(state / "parquet").write_records(
        [
            {
                "provider": "football-data",
                "fixture_id": 42,
                "odds_home": 2.0,
                "quality_status": "OBSERVED",
            }
        ],
        competition="Ligue 1",
        season=2024,
        entity_type="historical_market",
        dataset_version="historical_market_v1",
    )
    external_path = Path(str(external["path"]))
    before = external_path.read_bytes()
    audit = state / "audits" / "ligue1-2025-canonicalization.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "status": "PASSED",
                "canonical_fixtures": 306,
                "expected_fixtures": 306,
            }
        ),
        encoding="utf-8",
    )

    repair = repair_raw_hash_provenance(state)
    quality = historical_quality_report(state)

    assert repair["status"] == "REPAIRED"
    assert repair["rows_unresolved"] == 0
    assert repair["files_rewritten"] == 0
    assert quality["status"] == "PASSED"
    assert quality["parquet_partitions"] == 0
    assert quality["normalized_rows"] == 0
    assert external_path.read_bytes() == before


def test_quality_accepts_empty_api_partition_without_record_schema(
    tmp_path: Path,
) -> None:
    state = tmp_path / "historical"
    path = (
        state
        / "parquet"
        / "competition=Ligue-1"
        / "season=2024"
        / "entity_type=injuries"
        / "dataset_version=api-football-v3"
        / "part-00000.parquet"
    )
    path.parent.mkdir(parents=True)
    pd.DataFrame().to_parquet(path, index=False)
    audit = state / "audits" / "ligue1-2025-canonicalization.json"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps(
            {
                "status": "PASSED",
                "canonical_fixtures": 306,
                "expected_fixtures": 306,
            }
        ),
        encoding="utf-8",
    )

    quality = historical_quality_report(state)

    assert quality["status"] == "PASSED"
    assert quality["parquet_partitions"] == 1
    assert quality["normalized_rows"] == 0
    assert quality["failures"] == []


class ErrorResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status
        self.headers: dict[str, str] = {}
        self.content = b"{}"

    def json(self) -> dict[str, object]:
        return {}


class ErrorTransport:
    def __init__(self, status: int) -> None:
        self.status = status
        self.calls = 0

    def get(self, *_: Any, **__: Any) -> ErrorResponse:
        self.calls += 1
        return ErrorResponse(self.status)


def test_http_429_backoff_jitter_et_circuit_breaker() -> None:
    transport = ErrorTransport(429)
    sleeps: list[float] = []
    provider = ApiFootballProvider(
        api_key="not-a-real-secret",
        transport=transport,
        sleeper=sleeps.append,
        randomizer=lambda: 0.25,
        max_retries=1,
        circuit_failure_threshold=1,
    )
    with pytest.raises(RateLimitError):
        provider.get_status()
    assert sleeps == [1.25]
    with pytest.raises(TransientProviderError, match="circuit_open"):
        provider.get_status()
    assert transport.calls == 2


def test_workflows_isolent_live_et_historique_et_retry_git_est_borne() -> None:
    root = Path(__file__).resolve().parents[2]
    historical = {
        "api-football-coverage.yml",
        "historical-backfill.yml",
        "historical-quality.yml",
        "feature-factory.yml",
        "model-training.yml",
        "historical-backtesting.yml",
        "cockpit-refresh.yml",
    }
    for name in historical:
        workflow = yaml.safe_load(
            (root / ".github" / "workflows" / name).read_text("utf-8")
        )
        assert workflow["concurrency"]["group"] == "historical-state"
        assert workflow["concurrency"]["cancel-in-progress"] is False
    coverage = yaml.safe_load(
        (root / ".github" / "workflows" / "api-football-coverage.yml").read_text(
            "utf-8"
        )
    )
    assert "push" not in coverage[True]
    for name in ("collect-fixtures.yml", "collect-odds.yml", "daily-health.yml"):
        workflow = yaml.safe_load(
            (root / ".github" / "workflows" / name).read_text("utf-8")
        )
        assert workflow["concurrency"]["group"] == "shadow-state"
    restore = (
        root / ".github" / "actions" / "historical-state-restore" / "action.yml"
    ).read_text("utf-8")
    persist = (
        root / ".github" / "actions" / "historical-state-persist" / "action.yml"
    ).read_text("utf-8")
    assert "ref: historical-data" in restore
    assert "HEAD:historical-data" in persist
    assert "for attempt in 1 2 3" in persist
    assert "git rebase origin/historical-data" in persist
    backfill = (
        root / ".github" / "workflows" / "historical-backfill.yml"
    ).read_text("utf-8")
    quality = (
        root / ".github" / "workflows" / "historical-quality.yml"
    ).read_text("utf-8")
    cockpit = (
        root / ".github" / "workflows" / "cockpit-refresh.yml"
    ).read_text("utf-8")
    assert "repair-provenance" in backfill
    assert "repair-provenance" in quality
    assert "COCKPIT_BUILD_SUCCESS" in cockpit
    assert "COCKPIT_ARTIFACT_PUBLISHED" in cockpit
    assert "deployment[\"private\"]" in cockpit
    assert "deployment_version=" in cockpit
    assert "current_backfill_run_id=" in cockpit
    assert "cockpit/app/cockpit-data.json" in cockpit
