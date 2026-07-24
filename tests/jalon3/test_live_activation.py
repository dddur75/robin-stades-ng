from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from robin.domain.enums import QuotePhase
from robin.ingestion.scheduler import FixtureCandidate, plan_collection
from robin.ingestion.snapshot_store import JsonlSnapshotStore
from robin.operations.activation import (
    WORKFLOW_FAILED,
    WORKFLOW_PARTIAL,
    WORKFLOW_SUCCESS_LIVE_DATA,
    WORKFLOW_SUCCESS_NO_DATA,
    audit_secret_presence,
    forecast_monthly_quota,
    normalized_market_probabilities,
    workflow_outcome,
)
from robin.providers.the_odds_api import parse_odds_snapshot
from scripts.manage_shadow_state import (
    CrossHostSafeRedirectHandler,
    prune_state_artifacts,
    restore_latest_state,
    safe_extract_zip,
    select_latest_state,
)
from scripts.run_shadow_pipeline import (
    post_match_settlement,
    pre_match_shadow,
    write_json,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def queued_opener(*payloads: bytes) -> Any:
    queue = list(payloads)

    def open_request(_: object) -> FakeResponse:
        return FakeResponse(queue.pop(0))

    return open_request


def zip_payload(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return stream.getvalue()


def test_audit_secret_present_ne_retourne_que_booleen() -> None:
    result = audit_secret_presence({"ODDS_API_KEY": "super-secret"}, ["ODDS_API_KEY"])
    assert result == {"ODDS_API_KEY": True}
    assert "super-secret" not in repr(result)


def test_audit_secret_absent_est_explicite() -> None:
    result = audit_secret_presence({}, ["ODDS_API_KEY", "API_FOOTBALL_KEY"])
    assert result == {"ODDS_API_KEY": False, "API_FOOTBALL_KEY": False}


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"authenticated": True, "records_received": 1, "records_persisted": 1},
            WORKFLOW_SUCCESS_LIVE_DATA,
        ),
        (
            {"authenticated": True, "records_received": 0, "records_persisted": 0},
            WORKFLOW_SUCCESS_NO_DATA,
        ),
        (
            {"authenticated": False, "records_received": 0, "records_persisted": 0},
            WORKFLOW_PARTIAL,
        ),
        (
            {
                "authenticated": True,
                "records_received": 0,
                "records_persisted": 0,
                "failed": True,
            },
            WORKFLOW_FAILED,
        ),
    ],
)
def test_statut_workflow_distingue_resultat(
    arguments: dict[str, Any],
    expected: str,
) -> None:
    assert workflow_outcome(**arguments) == expected


def test_baseline_marche_est_deviggee() -> None:
    values = normalized_market_probabilities([2.0], [4.0], [4.0])
    assert values == pytest.approx((0.5, 0.25, 0.25))
    assert sum(values or ()) == pytest.approx(1)


@pytest.mark.parametrize(
    "prices",
    [
        ([], [3.0], [4.0]),
        ([1.0], [3.0], [4.0]),
    ],
)
def test_baseline_marche_refuse_source_incomplete(
    prices: tuple[list[float], list[float], list[float]],
) -> None:
    assert normalized_market_probabilities(*prices) is None


def test_quota_neuf_fenetres_garde_au_moins_20_pourcent() -> None:
    forecast = forecast_monthly_quota(matches_per_month=40)
    assert forecast.forecast_credits == 720
    assert forecast.reserve_credits == 4_000
    assert forecast.headroom_credits > 0
    assert forecast.strategy == "NINE_WINDOWS_WITH_20_PERCENT_RESERVE"


def test_quota_degrade_sur_fenetres_proches_si_depassement() -> None:
    forecast = forecast_monthly_quota(matches_per_month=1_000)
    assert forecast.headroom_credits < 0
    assert forecast.strategy == "ADAPTIVE_NEAREST_WINDOWS"


def test_quota_refuse_reserve_invalide() -> None:
    with pytest.raises(ValueError, match="reserve_pct"):
        forecast_monthly_quota(matches_per_month=40, reserve_pct=1.0)


def test_planificateur_respecte_reserve_fournisseur() -> None:
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    fixtures = (
        FixtureCandidate(
            provider_fixture_id="f1",
            kickoff_at=now + timedelta(hours=1),
        ),
    )
    assert plan_collection(
        fixtures,
        now=now,
        collected=set(),
        quota_remaining=4_001,
        reserve_credits=4_000,
    ) == ()


def test_planificateur_respecte_plafond_operationnel() -> None:
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    fixtures = (
        FixtureCandidate(
            provider_fixture_id="f1",
            kickoff_at=now + timedelta(hours=1),
        ),
    )
    assert plan_collection(
        fixtures,
        now=now,
        collected=set(),
        quota_remaining=20_000,
        quota_used=1_000,
        monthly_operational_ceiling=1_000,
    ) == ()


def test_selection_etat_ignore_run_courant() -> None:
    artifacts = [
        {
            "id": 1,
            "name": "shadow-state-1",
            "created_at": "2026-07-24T10:00:00Z",
            "workflow_run": {"id": 1},
        },
        {
            "id": 2,
            "name": "shadow-state-2",
            "created_at": "2026-07-24T11:00:00Z",
            "workflow_run": {"id": 2},
        },
    ]
    assert select_latest_state(artifacts, current_run_id="2")["id"] == 1


def test_redirection_externe_supprime_authentification() -> None:
    handler = CrossHostSafeRedirectHandler()
    request = urllib.request.Request(
        "https://api.github.com/repos/owner/repo/actions/artifacts/1/zip",
        headers={"Authorization": "Bearer secret"},
    )
    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://signed-storage.example/state.zip",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None


def test_extraction_artifact_restaure_fichiers(tmp_path: Path) -> None:
    restored = safe_extract_zip(
        zip_payload({"fixtures/latest.json": b"[]", "runs/a.json": b"{}"}),
        tmp_path,
    )
    assert restored == 2
    assert (tmp_path / "fixtures" / "latest.json").read_bytes() == b"[]"


def test_extraction_artifact_refuse_traversee(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="interdit"):
        safe_extract_zip(zip_payload({"../escape.txt": b"x"}), tmp_path)


def test_restauration_absente_est_non_bloquante(tmp_path: Path) -> None:
    opener = queued_opener(json.dumps({"artifacts": []}).encode())
    result = restore_latest_state(
        repository="owner/repo",
        token="token",
        destination=tmp_path,
        opener=opener,
    )
    assert result["status"] == "STATE_NOT_FOUND"
    assert result["files_restored"] == 0


def test_restauration_inter_runner_conserve_hash(tmp_path: Path) -> None:
    state = zip_payload(
        {
            "raw/observations/a.json": json.dumps(
                {"observation_id": "a", "payload_hash": "hash-constant"}
            ).encode()
        }
    )
    listing = {
        "artifacts": [
            {
                "id": 42,
                "name": "shadow-state-42",
                "created_at": "2026-07-24T11:00:00Z",
                "expired": False,
                "archive_download_url": "https://example.test/state.zip",
                "workflow_run": {"id": 42},
            }
        ]
    }
    opener = queued_opener(json.dumps(listing).encode(), state)
    result = restore_latest_state(
        repository="owner/repo",
        token="token",
        destination=tmp_path,
        current_run_id="43",
        opener=opener,
    )
    restored = json.loads(
        (tmp_path / "raw" / "observations" / "a.json").read_text()
    )
    assert result["status"] == "STATE_RESTORED"
    assert restored["payload_hash"] == "hash-constant"


def test_prune_attend_visibilite_artifact_courant() -> None:
    listing = {
        "artifacts": [
            {
                "id": 1,
                "name": "shadow-state-1",
                "created_at": "2026-07-24T10:00:00Z",
                "expired": False,
            }
        ]
    }
    result = prune_state_artifacts(
        repository="owner/repo",
        token="token",
        current_artifact_name="shadow-state-2",
        opener=queued_opener(json.dumps(listing).encode()),
    )
    assert result["status"] == "PRUNE_DEFERRED"
    assert result["deleted"] == 0


def sample_event() -> dict[str, object]:
    return {
        "id": "event-1",
        "commence_time": "2030-08-21T18:45:00Z",
        "home_team": "Marseille",
        "away_team": "Strasbourg",
        "bookmakers": [
            {
                "key": "book-a",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Marseille", "price": 2.0},
                            {"name": "Draw", "price": 3.5},
                            {"name": "Strasbourg", "price": 4.0},
                        ],
                    }
                ],
            }
        ],
    }


def test_snapshot_payload_identique_est_dedoublonne(tmp_path: Path) -> None:
    observed = datetime(2026, 7, 24, 12, tzinfo=UTC)
    first = parse_odds_snapshot(
        sample_event(),
        observed_at=observed,
        ingested_at=observed,
        raw_observation_id="raw-1",
        phase=QuotePhase.INTERMEDIATE,
    )
    second = parse_odds_snapshot(
        sample_event(),
        observed_at=observed + timedelta(seconds=10),
        ingested_at=observed + timedelta(seconds=10),
        raw_observation_id="raw-2",
        phase=QuotePhase.INTERMEDIATE,
    )
    store = JsonlSnapshotStore(tmp_path)
    assert store.append(first, source_payload_hash="same-hash")
    assert not store.append(second, source_payload_hash="same-hash")
    assert len(store.read_all()) == 1


def prepare_live_state(output: Path) -> None:
    write_json(
        output / "fixtures" / "latest.json",
        [
            {
                "id": "event-1",
                "sport_title": "Ligue 1 - France",
                "commence_time": "2030-08-21T18:45:00Z",
                "home_team": "Marseille",
                "away_team": "Strasbourg",
                "origin": "LIVE SOURCE",
            },
            {
                "id": "event-2",
                "sport_title": "Ligue 1 - France",
                "commence_time": "2030-08-22T18:45:00Z",
                "home_team": "Lille",
                "away_team": "Rennes",
                "origin": "LIVE SOURCE",
            },
        ],
    )
    observed = datetime(2026, 7, 24, 12, tzinfo=UTC)
    snapshot = parse_odds_snapshot(
        sample_event(),
        observed_at=observed,
        ingested_at=observed,
        raw_observation_id="raw-1",
        phase=QuotePhase.INTERMEDIATE,
    )
    JsonlSnapshotStore(output / "odds").append(
        snapshot,
        source_payload_hash="payload-hash",
    )


def test_prediction_live_est_market_baseline_et_non_legacy(tmp_path: Path) -> None:
    prepare_live_state(tmp_path)
    summary = pre_match_shadow(tmp_path, mock=False)
    predictions = json.loads(
        (tmp_path / "predictions" / "latest.json").read_text("utf-8")
    )
    blocked = json.loads(
        (tmp_path / "predictions" / "blocked.json").read_text("utf-8")
    )
    assert summary["predictions"] == 1
    assert summary["predictions_blocked"] == 1
    assert predictions[0]["model_name"] == "MARKET_BASELINE_ONLY"
    assert predictions[0]["origin"] == "LIVE SOURCE"
    assert predictions[0]["provenance"]["sports_history"] == "NOT_USED"
    assert blocked[0]["reason"] == "MISSING_ODDS"


def test_prediction_et_decision_live_sont_idempotentes(tmp_path: Path) -> None:
    prepare_live_state(tmp_path)
    first = pre_match_shadow(tmp_path, mock=False)
    second = pre_match_shadow(tmp_path, mock=False)
    assert first["predictions_created"] == 1
    assert second["predictions_created"] == 0
    assert second["decisions_created"] == 0
    assert len(
        (tmp_path / "predictions" / "history.jsonl").read_text().splitlines()
    ) == 1
    assert len(
        (tmp_path / "decisions" / "shadow-decisions.jsonl")
        .read_text()
        .splitlines()
    ) == 1


def test_settlement_sans_decision_eligible_ne_consomme_aucun_appel(
    tmp_path: Path,
) -> None:
    result = post_match_settlement(tmp_path, mock=False)
    assert result["status"] == WORKFLOW_SUCCESS_NO_DATA
    assert result["calls_consumed"] == 0
    assert result["eligible_decisions"] == 0


def test_configuration_live_reste_verrouillee() -> None:
    root = Path(__file__).resolve().parents[2]
    config = yaml.safe_load((root / "configs" / "shadow_v1.yaml").read_text())
    assert config["real_bets_enabled"] is False
    assert config["persistence"]["backend"] == "GITHUB_ARTIFACT_EXPLICIT_RESTORE"
    assert config["quota"]["reserve_pct"] >= 20
    assert len(config["collection_windows"]) == 9


def test_workflows_partagent_un_verrou_de_persistance() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in (
        "collect-fixtures.yml",
        "collect-odds.yml",
        "pre-match-shadow.yml",
        "post-match-settlement.yml",
        "daily-health.yml",
    ):
        content = (root / ".github" / "workflows" / name).read_text()
        assert "group: shadow-state" in content
        assert "actions/cache@" not in content
        assert "manage_shadow_state.py restore" in content


def test_artefacts_temporaires_sont_ignores() -> None:
    root = Path(__file__).resolve().parents[2]
    ignore = (root / ".gitignore").read_text()
    for pattern in ("*.pid", "*.out", "*.err", ".ci/", "data/shadow/"):
        assert pattern in ignore
