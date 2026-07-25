from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import polars as pl
import pytest

from robin.backtesting.v3 import (
    StrategyParameters,
    devig_probabilities,
    run_backtest,
    strategy_sensitivity,
)
from robin.historical.model_lab import (
    TEAM_FEATURES,
    isotonic_calibrate,
    sigmoid_calibrate,
    train_temporal_model,
    validate_tuning_periods,
)


def _model_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    fixture_id = 0
    for season in range(2020, 2026):
        for index in range(45):
            fixture_id += 1
            difference = float((index % 9) * 25 - 100)
            home_goals = 2 if difference > 20 else 1
            away_goals = 2 if difference < -20 else 0
            row: dict[str, object] = {
                "fixture_id": fixture_id,
                "competition": "Ligue 1",
                "season": season,
                "kickoff_at": f"{season}-09-{index % 28 + 1:02d}T18:00:00Z",
                "target_home_goals": home_goals,
                "target_away_goals": away_goals,
                "odds_home": 2.2,
                "odds_draw": 3.2,
                "odds_away": 3.4,
            }
            for feature in TEAM_FEATURES:
                row[feature] = difference if "elo" in feature else float(index % 5)
            rows.append(row)
    return rows


def test_oos_cannot_tune_parameters() -> None:
    with pytest.raises(ValueError, match="OOS_BLIND_VIOLATION"):
        validate_tuning_periods((2020, 2024), (2024, 2025))


def test_temporal_model_and_calibration_are_reproducible() -> None:
    first, predictions = train_temporal_model(
        _model_rows(),
        model_name="test_model",
        dataset_name="api_team_pre_match_v1",
        features=TEAM_FEATURES,
    )
    second, _ = train_temporal_model(
        _model_rows(),
        model_name="test_model",
        dataset_name="api_team_pre_match_v1",
        features=TEAM_FEATURES,
    )
    assert first["artifact_hash"] == second["artifact_hash"]
    assert first["selected_calibration"] in {"none", "sigmoid", "isotonic"}
    assert first["oos_metrics"]["matches"] == 90
    assert {prediction["season"] for prediction in predictions} == {2024, 2025}


def test_calibrators_return_valid_probability_simplexes() -> None:
    validation = np.array(
        [[0.7, 0.2, 0.1], [0.2, 0.5, 0.3], [0.1, 0.2, 0.7]] * 8
    )
    labels = np.array([0, 1, 2] * 8)
    for calibrated in (
        sigmoid_calibrate(validation, labels, validation),
        isotonic_calibrate(validation, labels, validation),
    ):
        assert np.allclose(calibrated.sum(axis=1), 1.0)
        assert np.all((calibrated >= 0.0) & (calibrated <= 1.0))


def test_devig_margin_is_removed() -> None:
    probabilities = devig_probabilities([2.0, 3.2, 4.0])
    assert sum(value for value in probabilities if value is not None) == pytest.approx(1.0)


def test_strategy_lab_is_oos_only_and_multiple_testing_aware() -> None:
    predictions = [
        {
            "fixture_id": index,
            "kickoff_at": f"2025-01-{index:02d}T18:00:00Z",
            "model_version": "model_v1",
            "probability_home": 0.62,
            "probability_draw": 0.2,
            "probability_away": 0.18,
            "odds_home": 2.0,
            "odds_draw": 3.5,
            "odds_away": 4.0,
            "target": 0 if index % 2 else 2,
            "origin": "OOS HISTORICAL",
        }
        for index in range(1, 21)
    ]
    results = strategy_sensitivity(predictions, model_version="model_v1")
    assert len(results) == 3
    assert all(result["multiple_testing_method"] == "BONFERRONI" for result in results)
    assert all(result["status"] in {"INCONCLUSIVE", "REJECTED"} for result in results)
    assert all(result["production_status"] == "PRODUCTION_LOCKED" for result in results)


def test_backtest_rejects_mixed_historical_and_live_segments() -> None:
    with pytest.raises(ValueError, match="BACKTEST_SEGMENT_MIXED"):
        run_backtest(
            [
                {
                    "fixture_id": 1,
                    "kickoff_at": "2025-01-01T18:00:00Z",
                    "probability_home": 0.6,
                    "probability_draw": 0.2,
                    "probability_away": 0.2,
                    "odds_home": 2.0,
                    "odds_draw": 3.0,
                    "odds_away": 4.0,
                    "target": 0,
                    "origin": "LIVE_SHADOW",
                }
            ],
            StrategyParameters("guard", "1X2", 0.01),
        )


def test_parquet_is_readable_by_pandas_duckdb_and_polars(tmp_path: Path) -> None:
    path = tmp_path / "compatibility.parquet"
    pd.DataFrame([{"fixture_id": 1, "value": 2.5}]).to_parquet(path, index=False)
    assert pd.read_parquet(path).loc[0, "fixture_id"] == 1
    assert duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{path.as_posix()}')"
    ).fetchone() == (1,)
    assert pl.read_parquet(path).height == 1
