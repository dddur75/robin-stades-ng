from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from robin.historical.external_validation import (
    EXTERNAL_COMPETITIONS,
    PACKAGE_WAITING,
    PRODUCTION_STATUS,
    PROTOCOL_STATUS,
    assert_no_external_retuning,
    build_league_readiness,
    build_preseason_package,
    compare_predictions,
    devig_market_odds,
    exact_pairs,
    external_protocol_definition,
    lock_external_protocol,
    multi_league_bootstrap,
    profit_concentration,
    run_external_validation,
    standardize_by_competition,
    strategy_lab_v3_protocol,
    write_immutable_json,
)
from robin.historical.scientific_arena import storage_guard

ROOT = Path(__file__).resolve().parents[2]


def _write_partition(
    state: Path,
    *,
    competition: str,
    season: int,
    entity_type: str,
    rows: list[dict[str, object]],
) -> None:
    path = (
        state
        / "parquet"
        / f"competition={competition}"
        / f"season={season}"
        / f"entity_type={entity_type}"
        / "dataset_version=api-football-v3"
        / "part-00000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _fixture_row(
    *,
    competition: str,
    season: int,
    index: int,
) -> dict[str, object]:
    fixture_id = season * 10_000 + index
    home_id = index % 6 + 1
    away_id = (index + 2) % 6 + 1
    outcomes = ((2, 0), (1, 1), (0, 2))
    home_goals, away_goals = outcomes[index % len(outcomes)]
    payload = {
        "fixture": {
            "id": fixture_id,
            "date": f"{season}-08-{index + 1:02d}T18:00:00+00:00",
            "status": {"short": "FT"},
        },
        "league": {"name": competition, "season": season},
        "teams": {
            "home": {"id": home_id, "name": f"Home {home_id}"},
            "away": {"id": away_id, "name": f"Away {away_id}"},
        },
        "goals": {"home": home_goals, "away": away_goals},
    }
    return {
        "provider_id": fixture_id,
        "season": season,
        "payload": json.dumps(payload),
        "raw_payload_hash": f"hash-{competition}-{season}-{index}",
        "availability_status": "POINT_IN_TIME_SAFE",
    }


def _historical_state(tmp_path: Path) -> Path:
    state = tmp_path / "historical"
    competitions = {
        **{
            str(config["slug"]): competition
            for competition, config in EXTERNAL_COMPETITIONS.items()
        },
        "Ligue-1": "Ligue 1",
    }
    for slug, competition in competitions.items():
        for season in range(2019, 2026):
            fixtures = [
                _fixture_row(
                    competition=competition,
                    season=season,
                    index=index,
                )
                for index in range(12)
            ]
            _write_partition(
                state,
                competition=slug,
                season=season,
                entity_type="fixtures",
                rows=fixtures,
            )
            _write_partition(
                state,
                competition=slug,
                season=season,
                entity_type="teams",
                rows=[
                    {
                        "provider_id": team_id,
                        "season": season,
                        "payload": "{}",
                        "raw_payload_hash": f"team-{slug}-{season}-{team_id}",
                    }
                    for team_id in range(1, 7)
                ],
            )
    return state


def _prediction(
    fixture_id: str,
    *,
    probability_home: float,
    model_version: str,
) -> dict[str, object]:
    return {
        "competition": "Premier League",
        "fixture_id": fixture_id,
        "season": 2024,
        "kickoff_at": "2024-08-01T18:00:00+00:00",
        "target": 0,
        "model_version": model_version,
        "probability_home": probability_home,
        "probability_draw": (1.0 - probability_home) / 2.0,
        "probability_away": (1.0 - probability_home) / 2.0,
        "market_snapshot": "",
        "temporal_policy": "HISTORICAL_POINT_IN_TIME_PRE_MATCH",
    }


def test_protocol_is_complete_hashed_and_production_locked() -> None:
    protocol = external_protocol_definition()
    assert protocol["status"] == PROTOCOL_STATUS
    assert protocol["registered_before_results"] is True
    assert protocol["production_status"] == PRODUCTION_STATUS
    assert protocol["real_bets"] is False
    assert set(
        (
            "datasets",
            "features",
            "models",
            "parameters",
            "calibrations",
            "periods",
            "metrics",
            "comparisons",
            "decision_criteria",
        )
    ) <= protocol.keys()
    assert "target_home_goals" in protocol["features"]["forbidden"]  # type: ignore[index]


def test_protocol_is_locked_before_results_and_cannot_be_retuned(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    frozen = lock_external_protocol(
        state,
        source_commit="abc",
        frozen_at="2026-07-25T00:00:00+00:00",
    )
    replay = lock_external_protocol(
        state,
        source_commit="later-commit",
        frozen_at="2026-07-26T00:00:00+00:00",
    )
    assert replay["protocol_hash"] == frozen["protocol_hash"]
    parameters = frozen["parameters"]
    assert isinstance(parameters, dict)
    assert_no_external_retuning(frozen, parameters)
    with pytest.raises(RuntimeError, match="POST_EXTERNAL_RETUNING_FORBIDDEN"):
        assert_no_external_retuning(frozen, {**parameters, "learning_rate": 1.0})


def test_immutable_artifact_rejects_rewrite(tmp_path: Path) -> None:
    path = tmp_path / "package.json"
    write_immutable_json(path, {"version": 1, "REAL_BETS": False})
    with pytest.raises(RuntimeError, match="IMMUTABLE_ARTIFACT_REWRITE_FORBIDDEN"):
        write_immutable_json(path, {"version": 2, "REAL_BETS": False})


def test_multileague_gates_measure_only_observed_coverage(tmp_path: Path) -> None:
    state = _historical_state(tmp_path)
    readiness = build_league_readiness(state)
    competitions = readiness["competitions"]
    assert isinstance(competitions, list)
    assert len(competitions) == 5
    for item in competitions:
        gates = item["gates"]
        assert gates["TEAM_GATE"]["status"] == "READY"
        assert gates["PLAYER_GATE"]["status"] == "BLOCKED_BY_COVERAGE"
        assert gates["LINEUP_GATE"]["status"] == "BLOCKED_BY_COVERAGE"
        assert gates["MARKET_GATE"]["status"] == "UNAVAILABLE"
        assert gates["MARKET_GATE"]["invented_prices"] == 0
        assert gates["EXTERNAL_VALIDATION_GATE"]["status"] == "PARTIAL"


def test_standardization_is_per_competition_without_targets() -> None:
    train = [
        {"competition": "A", "elo_difference": 10.0, "target_home_goals": 99},
        {"competition": "A", "elo_difference": 20.0, "target_home_goals": -99},
        {"competition": "B", "elo_difference": 100.0, "target_home_goals": 1},
        {"competition": "B", "elo_difference": 200.0, "target_home_goals": 2},
    ]
    scaled = standardize_by_competition(
        train,
        train,
        features=("elo_difference",),
    )
    assert [round(float(row["elo_difference"]), 6) for row in scaled] == [
        -1.0,
        1.0,
        -1.0,
        1.0,
    ]


def test_exact_pairing_rejects_non_paired_samples() -> None:
    challenger = [_prediction("1", probability_home=0.7, model_version="a")]
    reference = [_prediction("2", probability_home=0.5, model_version="b")]
    with pytest.raises(ValueError, match="NO_EXACT_PAIRED_FIXTURES"):
        exact_pairs(challenger, reference)


def test_multileague_bootstrap_is_deterministic_and_grouped() -> None:
    deltas = [-0.1, -0.2, 0.1, 0.0] * 10
    groups = [f"league:{index // 2}" for index in range(len(deltas))]
    first = multi_league_bootstrap(deltas, groups, iterations=2_000)
    second = multi_league_bootstrap(deltas, groups, iterations=2_000)
    assert first == second
    assert first["groups"] == 20


def test_paired_comparison_exposes_uncertainty() -> None:
    challenger = [
        _prediction(str(index), probability_home=0.70, model_version="challenger")
        for index in range(30)
    ]
    reference = [
        _prediction(str(index), probability_home=0.40, model_version="reference")
        for index in range(30)
    ]
    result = compare_predictions(
        challenger,
        reference,
        comparison_id="TEST",
    )
    assert result["paired_fixtures"] == 30
    assert result["paired_log_loss_delta"] < 0
    assert result["uncertainty"]["iterations"] == 5_000  # type: ignore[index]


def test_market_devig_never_invents_missing_prices() -> None:
    assert devig_market_odds([2.0, 3.0, 4.0]) == pytest.approx(
        [0.4615384615, 0.3076923077, 0.2307692308]
    )
    assert devig_market_odds([2.0, None, 4.0]) == [None, None, None]


def test_profit_concentration_blocks_single_league_or_match() -> None:
    result = profit_concentration([10.0, 1.0, -2.0], ["PL", "Liga", "Serie A"])
    assert result["status"] == "CONCENTRATED"
    assert result["largest_group_positive_profit_share"] > 0.60


def test_strategy_v3_is_bounded_preregistered_and_locked() -> None:
    protocol = strategy_lab_v3_protocol()
    hypotheses = protocol["hypotheses"]
    assert isinstance(hypotheses, list)
    assert len(hypotheses) == protocol["maximum_hypotheses"]
    assert len(hypotheses) == 13
    assert protocol["real_bets"] is False
    assert protocol["production_status"] == PRODUCTION_STATUS


def test_preseason_package_waits_honestly_for_external_gates() -> None:
    package = build_preseason_package(
        protocol_hash="protocol",
        dataset_manifests=[
            {"dataset_version": "pl_team_pre_match_v1", "hash": "dataset"}
        ],
        comparisons=[],
        code_revision="commit",
        generated_at="2026-07-25T00:00:00+00:00",
        all_external_gates_ready=False,
    )
    assert package["status"] == PACKAGE_WAITING
    assert package["NO_BET_DEFAULT"] is True
    assert package["REAL_BETS"] is False
    assert package["PRODUCTION_LOCKED"] is True
    assert package["model_versions"] == []


def test_storage_warning_and_pause_are_not_bypassed() -> None:
    assert storage_guard(749_999_999)["status"] == "SAFE"
    assert storage_guard(750_000_000)["status"] == "WARNING"
    paused = storage_guard(900_000_000)
    assert paused["status"] == "PAUSED"
    assert paused["can_write"] is False


def test_full_external_run_is_cache_only_and_gate_honest(tmp_path: Path) -> None:
    state = _historical_state(tmp_path)
    result = run_external_validation(
        state,
        source_commit="jalon8-source",
        run_id="test-run",
        frozen_at="2026-07-25T00:00:00+00:00",
    )
    assert result["status"] == "WAITING_FOR_EXTERNAL_GATES"
    assert result["provider_calls"] == 0
    assert result["quota_consumed"] == 0
    assert result["real_bets"] is False
    assert result["production_status"] == PRODUCTION_STATUS
    assert len(result["datasets"]) == 5
    assert {
        item["dataset_version"]  # type: ignore[index]
        for item in result["datasets"]  # type: ignore[union-attr]
    } == {
        "pl_team_pre_match_v1",
        "laliga_team_pre_match_v1",
        "bundesliga_team_pre_match_v1",
        "seriea_team_pre_match_v1",
        "ucl_team_pre_match_v1",
    }
    models = result["models"]
    assert models["frozen_transfer"]["status"] == "FROZEN_TRANSFER_EVALUATED"  # type: ignore[index]
    assert models["league_specific"]["status"] == "LEAGUE_SPECIFIC_EVALUATED"  # type: ignore[index]
    assert models["pooled"]["status"] == "POOLED_MODEL_EVALUATED"  # type: ignore[index]
    assert len(result["leave_one_league_out"]) == 5  # type: ignore[arg-type]
    assert result["strategies"]["status"] == "NO_EXTERNAL_VALIDATED_EDGE"  # type: ignore[index]
    assert result["preseason_package"]["status"] == PACKAGE_WAITING  # type: ignore[index]
    assert all(
        item["external_labels_used_for_tuning"] == 0
        for path in (state / "external" / "predictions").rglob("*.parquet")
        for item in pd.read_parquet(path).to_dict(orient="records")
        if "external_labels_used_for_tuning" in item
    )


def test_workflow_is_isolated_cache_only_and_cockpit_triggered() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "external-validation.yml"
    ).read_text(encoding="utf-8")
    cockpit = (
        ROOT / ".github" / "workflows" / "cockpit-refresh.yml"
    ).read_text(encoding="utf-8")
    quality = (
        ROOT / ".github" / "workflows" / "historical-quality.yml"
    ).read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "group: historical-state" in workflow
    assert "run_external_validation.py" in workflow
    assert "API_FOOTBALL_KEY" not in workflow
    assert "ODDS_API_KEY" not in workflow
    assert "27 - Validation externe multi-ligues" in cockpit
    assert "run_external_validation" in quality
    assert "inputs.run_external_validation" in quality
    assert "!inputs.run_external_validation" in quality
    assert "tests/jalon8" in ci


def test_cockpit_exposes_external_gates_without_secrets() -> None:
    builder = (ROOT / "scripts" / "build_cockpit_snapshot.py").read_text(
        encoding="utf-8"
    )
    page = (ROOT / "cockpit" / "app" / "page.tsx").read_text(encoding="utf-8")
    for label in (
        "External Readiness",
        "League Transfer Matrix",
        "Leave-One-League-Out",
        "Player Generalization",
        "Strategy External Validation",
        "Preseason Package",
        "NO_BET_DEFAULT",
        "REAL_BETS",
    ):
        assert label in page
    assert '"externalValidation"' in builder
    assert "DATABASE_URL" not in page
    assert "API_FOOTBALL_KEY" not in page
