"""Model Lab déterministe : splits temporels, calibration et OOS aveugle."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import numpy as np

from robin.historical.features import TEMPORAL_VALIDITY_NOT_PROVEN
from robin.market_math import (
    DevigInputError,
    DevigMethod,
    devig_probabilities,
    kernel_versions,
)

TEAM_FEATURES = (
    "elo_difference",
    "home_form_5",
    "away_form_5",
    "home_goals_for_5",
    "away_goals_for_5",
    "home_goals_against_5",
    "away_goals_against_5",
    "home_rest_days",
    "away_rest_days",
    "home_shots_5",
    "away_shots_5",
    "home_shots_on_goal_5",
    "away_shots_on_goal_5",
    "home_possession_5",
    "away_possession_5",
)
PLAYER_FEATURES = (
    "home_expected_starting_xi_strength",
    "away_expected_starting_xi_strength",
    "home_expected_bench_strength",
    "away_expected_bench_strength",
    "home_expected_lineup_continuity",
    "away_expected_lineup_continuity",
    "home_expected_lineup_uncertainty",
    "away_expected_lineup_uncertainty",
)
LINEUP_FEATURES = (
    "home_confirmed_starting_xi_strength",
    "away_confirmed_starting_xi_strength",
    "home_confirmed_bench_strength",
    "away_confirmed_bench_strength",
    "home_confirmed_lineup_continuity",
    "away_confirmed_lineup_continuity",
    "home_difference_vs_expected",
    "away_difference_vs_expected",
)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def target(row: Mapping[str, object]) -> int | None:
    home = _number(row.get("target_home_goals"))
    away = _number(row.get("target_away_goals"))
    if home is None or away is None:
        return None
    return 0 if home > away else 1 if home == away else 2


def _required_target(row: Mapping[str, object]) -> int:
    value = target(row)
    if value is None:
        raise ValueError("TARGET_ABSENT")
    return value


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponential = np.exp(shifted)
    return cast(
        np.ndarray,
        exponential / exponential.sum(axis=1, keepdims=True),
    )


def _metrics(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, float | int]:
    if len(labels) == 0:
        return {
            "matches": 0,
            "log_loss": float("nan"),
            "brier_score": float("nan"),
            "ece": float("nan"),
        }
    selected = probabilities[np.arange(len(labels)), labels]
    log_loss = float(-np.log(np.clip(selected, 1e-12, 1.0)).mean())
    one_hot = np.eye(3)[labels]
    brier = float(np.square(probabilities - one_hot).sum(axis=1).mean() / 3.0)
    confidence = probabilities.max(axis=1)
    predicted = probabilities.argmax(axis=1)
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        mask = (confidence >= lower) & (confidence < lower + 0.1)
        if not mask.any():
            continue
        accuracy = float((predicted[mask] == labels[mask]).mean())
        ece += float(mask.mean()) * abs(accuracy - float(confidence[mask].mean()))
    return {
        "matches": len(labels),
        "log_loss": log_loss,
        "brier_score": brier,
        "ece": ece,
    }


def validate_tuning_periods(
    tuning_seasons: Iterable[int],
    oos_seasons: Iterable[int],
) -> None:
    overlap = set(tuning_seasons) & set(oos_seasons)
    if overlap:
        raise ValueError(f"OOS_BLIND_VIOLATION:{','.join(map(str, sorted(overlap)))}")


def _matrix(
    rows: Sequence[Mapping[str, object]],
    features: Sequence[str],
    *,
    imputation: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    def value(row: Mapping[str, object], feature: str) -> float:
        number = _number(row.get(feature))
        return np.nan if number is None else number

    matrix = np.asarray(
        [
            [value(row, feature) for feature in features]
            for row in rows
        ],
        dtype=np.float64,
    )
    if matrix.size == 0:
        return matrix.reshape((0, len(features))), np.zeros(len(features))
    if imputation is None:
        with np.errstate(all="ignore"):
            imputation = np.nanmedian(matrix, axis=0)
        imputation = np.where(np.isnan(imputation), 0.0, imputation)
    missing = np.where(np.isnan(matrix))
    matrix[missing] = np.take(imputation, missing[1])
    return matrix, imputation


def _fit_multinomial(
    matrix: np.ndarray,
    labels: np.ndarray,
    *,
    iterations: int = 300,
    learning_rate: float = 0.08,
    regularization: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale < 1e-9, 1.0, scale)
    standardized = (matrix - mean) / scale
    augmented = np.column_stack([np.ones(len(standardized)), standardized])
    weights = np.zeros((augmented.shape[1], 3), dtype=float)
    one_hot = np.eye(3)[labels]
    for _ in range(iterations):
        probabilities = _softmax(augmented @ weights)
        gradient = augmented.T @ (probabilities - one_hot) / len(labels)
        gradient[1:] += regularization * weights[1:]
        weights -= learning_rate * gradient
    return weights, mean, scale


def _predict_multinomial(
    matrix: np.ndarray,
    weights: np.ndarray,
    mean: np.ndarray,
    scale: np.ndarray,
) -> np.ndarray:
    standardized = (matrix - mean) / scale
    augmented = np.column_stack([np.ones(len(standardized)), standardized])
    return _softmax(augmented @ weights)


def _fit_sigmoid(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    design = np.column_stack([scores, np.ones(len(scores))])
    weights = np.array([1.0, 0.0])
    for _ in range(80):
        logits = np.clip(design @ weights, -30.0, 30.0)
        probability = 1.0 / (1.0 + np.exp(-logits))
        gradient = design.T @ (probability - labels) + 1e-4 * weights
        curvature = probability * (1.0 - probability)
        hessian = design.T @ (design * curvature[:, None]) + np.eye(2) * 1e-4
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.abs(step).max()) < 1e-8:
            break
    return float(weights[0]), float(weights[1])


def sigmoid_calibrate(
    validation: np.ndarray,
    labels: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    calibrated = np.zeros_like(values)
    for class_index in range(3):
        validation_scores = np.log(
            np.clip(validation[:, class_index], 1e-9, 1.0 - 1e-9)
            / np.clip(1.0 - validation[:, class_index], 1e-9, 1.0)
        )
        a, b = _fit_sigmoid(
            validation_scores,
            (labels == class_index).astype(float),
        )
        scores = np.log(
            np.clip(values[:, class_index], 1e-9, 1.0 - 1e-9)
            / np.clip(1.0 - values[:, class_index], 1e-9, 1.0)
        )
        calibrated[:, class_index] = 1.0 / (
            1.0 + np.exp(-np.clip(a * scores + b, -30.0, 30.0))
        )
    totals = calibrated.sum(axis=1, keepdims=True)
    return calibrated / np.where(totals == 0.0, 1.0, totals)


def _isotonic_blocks(
    scores: np.ndarray,
    labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(scores, kind="stable")
    sorted_scores = scores[order]
    sorted_labels = labels[order]
    blocks: list[list[float]] = [
        [float(score), float(score), float(label), 1.0]
        for score, label in zip(sorted_scores, sorted_labels, strict=True)
    ]
    index = 0
    while index < len(blocks) - 1:
        current_mean = blocks[index][2] / blocks[index][3]
        next_mean = blocks[index + 1][2] / blocks[index + 1][3]
        if current_mean <= next_mean:
            index += 1
            continue
        blocks[index] = [
            blocks[index][0],
            blocks[index + 1][1],
            blocks[index][2] + blocks[index + 1][2],
            blocks[index][3] + blocks[index + 1][3],
        ]
        del blocks[index + 1]
        index = max(index - 1, 0)
    thresholds = np.array([block[1] for block in blocks])
    outputs = np.array([block[2] / block[3] for block in blocks])
    return thresholds, outputs


def isotonic_calibrate(
    validation: np.ndarray,
    labels: np.ndarray,
    values: np.ndarray,
) -> np.ndarray:
    calibrated = np.zeros_like(values)
    for class_index in range(3):
        thresholds, outputs = _isotonic_blocks(
            validation[:, class_index],
            (labels == class_index).astype(float),
        )
        indices = np.searchsorted(
            thresholds,
            values[:, class_index],
            side="left",
        )
        calibrated[:, class_index] = outputs[np.clip(indices, 0, len(outputs) - 1)]
    totals = calibrated.sum(axis=1, keepdims=True)
    fallback = np.full_like(calibrated, 1.0 / 3.0)
    return cast(
        np.ndarray,
        np.divide(calibrated, totals, out=fallback, where=totals != 0.0),
    )


def _split_rows(
    rows: Iterable[Mapping[str, object]],
    seasons: Iterable[int],
) -> list[dict[str, object]]:
    allowed = set(seasons)
    return [
        dict(row)
        for row in rows
        if int(str(row["season"])) in allowed and target(row) is not None
    ]


def train_temporal_model(
    rows: list[dict[str, object]],
    *,
    model_name: str,
    dataset_name: str,
    features: tuple[str, ...],
    discovery: tuple[int, ...] = (2020, 2021, 2022),
    validation: tuple[int, ...] = (2023,),
    oos: tuple[int, ...] = (2024, 2025),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Ajuster sur Discovery, calibrer sur Validation, évaluer une fois sur OOS."""

    validate_tuning_periods((*discovery, *validation), oos)
    discovery_rows = _split_rows(rows, discovery)
    validation_rows = _split_rows(rows, validation)
    oos_rows = _split_rows(rows, oos)
    if not discovery_rows or not validation_rows or not oos_rows:
        return (
            {
                "model_name": model_name,
                "model_version": f"{model_name}_v1",
                "dataset": dataset_name,
                "status": "BLOCKED_BY_COVERAGE",
                "production_status": "PRODUCTION_LOCKED",
            },
            [],
        )
    discovery_matrix, imputation = _matrix(discovery_rows, features)
    validation_matrix, _ = _matrix(
        validation_rows,
        features,
        imputation=imputation,
    )
    oos_matrix, _ = _matrix(oos_rows, features, imputation=imputation)
    discovery_labels = np.asarray(
        [_required_target(row) for row in discovery_rows],
        dtype=np.int64,
    )
    validation_labels = np.asarray(
        [_required_target(row) for row in validation_rows],
        dtype=np.int64,
    )
    oos_labels = np.asarray(
        [_required_target(row) for row in oos_rows],
        dtype=np.int64,
    )
    weights, mean, scale = _fit_multinomial(discovery_matrix, discovery_labels)
    validation_raw = _predict_multinomial(validation_matrix, weights, mean, scale)
    oos_raw = _predict_multinomial(oos_matrix, weights, mean, scale)
    validation_candidates = {
        "none": validation_raw,
        "sigmoid": sigmoid_calibrate(
            validation_raw,
            validation_labels,
            validation_raw,
        ),
        "isotonic": isotonic_calibrate(
            validation_raw,
            validation_labels,
            validation_raw,
        ),
    }
    validation_metrics = {
        name: _metrics(probabilities, validation_labels)
        for name, probabilities in validation_candidates.items()
    }
    selected_calibration = min(
        validation_metrics,
        key=lambda name: float(validation_metrics[name]["log_loss"]),
    )
    oos_candidates = {
        "none": oos_raw,
        "sigmoid": sigmoid_calibrate(
            validation_raw,
            validation_labels,
            oos_raw,
        ),
        "isotonic": isotonic_calibrate(
            validation_raw,
            validation_labels,
            oos_raw,
        ),
    }
    selected_oos = oos_candidates[selected_calibration]
    artifact = {
        "features": features,
        "imputation": imputation.tolist(),
        "weights": weights.round(12).tolist(),
        "mean": mean.round(12).tolist(),
        "scale": scale.round(12).tolist(),
    }
    artifact_hash = hashlib.sha256(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest: dict[str, object] = {
        "model_name": model_name,
        "model_version": f"{model_name}_v1",
        "dataset": dataset_name,
        "features": list(features),
        "discovery_period": list(discovery),
        "validation_period": list(validation),
        "oos_period": list(oos),
        "missing_policy": "DISCOVERY_MEDIAN_IMPUTATION",
        "selection_period": "DISCOVERY_AND_VALIDATION_ONLY",
        "validation_calibration_metrics": validation_metrics,
        "selected_calibration": selected_calibration,
        "oos_metrics": _metrics(selected_oos, oos_labels),
        "performance_by_oos_season": {
            str(season): _metrics(
                selected_oos[
                    np.asarray(
                        [int(str(row["season"])) == season for row in oos_rows]
                    )
                ],
                oos_labels[
                    np.asarray(
                        [int(str(row["season"])) == season for row in oos_rows]
                    )
                ],
            )
            for season in oos
        },
        "artifact": artifact,
        "artifact_hash": artifact_hash,
        "trained_at": datetime.now(UTC).isoformat(),
        "status": "API_OOS_BACKTEST_READY",
        "production_status": "PRODUCTION_LOCKED",
    }
    predictions = [
        {
            "fixture_id": row["fixture_id"],
            "season": row["season"],
            "kickoff_at": row["kickoff_at"],
            "model_version": manifest["model_version"],
            "dataset_version": dataset_name,
            "probability_home": float(probabilities[0]),
            "probability_draw": float(probabilities[1]),
            "probability_away": float(probabilities[2]),
            "target": int(label),
            "odds_home": row.get("odds_home"),
            "odds_draw": row.get("odds_draw"),
            "odds_away": row.get("odds_away"),
            "odds_over_25": row.get("odds_over_25"),
            "odds_under_25": row.get("odds_under_25"),
            "origin": "OOS HISTORICAL",
            "availability_status": TEMPORAL_VALIDITY_NOT_PROVEN,
        }
        for row, probabilities, label in zip(
            oos_rows,
            selected_oos,
            oos_labels,
            strict=True,
        )
    ]
    return manifest, predictions


def _fixed_baseline(
    rows: list[dict[str, object]],
    *,
    model_name: str,
    probability_builder: Callable[
        [Mapping[str, object]],
        tuple[float, float, float] | None,
    ],
    validation: tuple[int, ...] = (2023,),
    oos: tuple[int, ...] = (2024, 2025),
) -> tuple[dict[str, object], list[dict[str, object]]]:
    validation_rows = _split_rows(rows, validation)
    oos_rows = _split_rows(rows, oos)
    validation_pairs = [
        (row, probability_builder(row))
        for row in validation_rows
    ]
    oos_pairs = [(row, probability_builder(row)) for row in oos_rows]
    validation_pairs = [
        (row, values)
        for row, values in validation_pairs
        if values is not None
    ]
    oos_pairs = [
        (row, values)
        for row, values in oos_pairs
        if values is not None
    ]
    if not validation_pairs or not oos_pairs:
        return (
            {
                "model_name": model_name,
                "model_version": f"{model_name}_v1",
                "dataset": "api_team_pre_match_v1",
                "status": "BLOCKED_BY_COVERAGE",
                "production_status": "PRODUCTION_LOCKED",
            },
            [],
        )
    validation_probabilities = np.asarray(
        [values for _, values in validation_pairs],
        dtype=np.float64,
    )
    oos_probabilities = np.asarray(
        [values for _, values in oos_pairs],
        dtype=np.float64,
    )
    validation_labels = np.asarray(
        [_required_target(row) for row, _ in validation_pairs],
        dtype=np.int64,
    )
    oos_labels = np.asarray(
        [_required_target(row) for row, _ in oos_pairs],
        dtype=np.int64,
    )
    candidates = {
        "none": validation_probabilities,
        "sigmoid": sigmoid_calibrate(
            validation_probabilities,
            validation_labels,
            validation_probabilities,
        ),
        "isotonic": isotonic_calibrate(
            validation_probabilities,
            validation_labels,
            validation_probabilities,
        ),
    }
    validation_metrics = {
        name: _metrics(values, validation_labels)
        for name, values in candidates.items()
    }
    selected = min(
        validation_metrics,
        key=lambda name: float(validation_metrics[name]["log_loss"]),
    )
    calibrated_oos = {
        "none": oos_probabilities,
        "sigmoid": sigmoid_calibrate(
            validation_probabilities,
            validation_labels,
            oos_probabilities,
        ),
        "isotonic": isotonic_calibrate(
            validation_probabilities,
            validation_labels,
            oos_probabilities,
        ),
    }[selected]
    artifact_hash = hashlib.sha256(
        f"{model_name}:{selected}:v1".encode()
    ).hexdigest()
    model: dict[str, object] = {
        "model_name": model_name,
        "model_version": f"{model_name}_v1",
        "dataset": "api_team_pre_match_v1",
        "validation_period": list(validation),
        "oos_period": list(oos),
        "validation_calibration_metrics": validation_metrics,
        "selected_calibration": selected,
        "oos_metrics": _metrics(calibrated_oos, oos_labels),
        "artifact_hash": artifact_hash,
        "trained_at": datetime.now(UTC).isoformat(),
        "status": "API_OOS_BACKTEST_READY",
        "production_status": "PRODUCTION_LOCKED",
    }
    predictions = [
        {
            "fixture_id": row["fixture_id"],
            "season": row["season"],
            "kickoff_at": row["kickoff_at"],
            "model_version": model["model_version"],
            "dataset_version": "api_team_pre_match_v1",
            "probability_home": float(probabilities[0]),
            "probability_draw": float(probabilities[1]),
            "probability_away": float(probabilities[2]),
            "target": int(label),
            "odds_home": row.get("odds_home"),
            "odds_draw": row.get("odds_draw"),
            "odds_away": row.get("odds_away"),
            "odds_over_25": row.get("odds_over_25"),
            "odds_under_25": row.get("odds_under_25"),
            "origin": "OOS HISTORICAL",
            "availability_status": TEMPORAL_VALIDITY_NOT_PROVEN,
        }
        for (row, _), probabilities, label in zip(
            oos_pairs,
            calibrated_oos,
            oos_labels,
            strict=True,
        )
    ]
    return model, predictions


def _elo_probabilities(row: Mapping[str, object]) -> tuple[float, float, float]:
    difference = _number(row.get("elo_difference")) or 0.0
    home_no_draw = 1.0 / (1.0 + 10.0 ** (-(difference + 60.0) / 400.0))
    draw = 0.26
    return (
        home_no_draw * (1.0 - draw),
        draw,
        (1.0 - home_no_draw) * (1.0 - draw),
    )


def _market_probabilities(
    row: Mapping[str, object],
    *,
    devig_method: DevigMethod | str,
) -> tuple[float, float, float] | None:
    prices = [
        _number(row.get("odds_home")),
        _number(row.get("odds_draw")),
        _number(row.get("odds_away")),
    ]
    try:
        result = devig_probabilities(
            prices,
            method=devig_method,
            outcome_labels=("HOME", "DRAW", "AWAY"),
        )
    except DevigInputError:
        return None
    home, draw, away = result.fair_probabilities
    return home, draw, away


def run_model_lab(
    datasets: Mapping[str, list[dict[str, object]]],
    *,
    devig_method: DevigMethod | str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    specifications = [
        (
            "api_team_multinomial",
            "api_team_pre_match_v1",
            TEAM_FEATURES,
        ),
        (
            "api_player_pre_lineup_multinomial",
            "api_player_pre_lineup_v1",
            (*TEAM_FEATURES, *PLAYER_FEATURES),
        ),
        (
            "api_post_lineup_simulated_multinomial",
            "api_post_lineup_simulated_v1",
            (*TEAM_FEATURES, *PLAYER_FEATURES, *LINEUP_FEATURES),
        ),
    ]
    models: list[dict[str, object]] = []
    predictions: list[dict[str, object]] = []
    team_rows = datasets.get("api_team_pre_match_v1", [])
    for model_name, builder in (
        ("api_elo", _elo_probabilities),
        (
            "market_devigged_baseline",
            lambda row: _market_probabilities(
                row,
                devig_method=devig_method,
            ),
        ),
    ):
        model, model_predictions = _fixed_baseline(
            team_rows,
            model_name=model_name,
            probability_builder=builder,
        )
        models.append(model)
        predictions.extend(model_predictions)
    for model_name, dataset_name, features in specifications:
        rows = datasets.get(dataset_name, [])
        if not rows:
            models.append(
                {
                    "model_name": model_name,
                    "model_version": f"{model_name}_v1",
                    "dataset": dataset_name,
                    "status": "BLOCKED_BY_COVERAGE",
                    "production_status": "PRODUCTION_LOCKED",
                }
            )
            continue
        model, model_predictions = train_temporal_model(
            rows,
            model_name=model_name,
            dataset_name=dataset_name,
            features=features,
        )
        models.append(model)
        predictions.extend(model_predictions)
    comparison_baseline = next(
        (
            model
            for model in models
            if model.get("model_version") == "api_team_multinomial_v1"
        ),
        None,
    )
    if comparison_baseline is not None:
        baseline_metrics = comparison_baseline.get("oos_metrics", {})
        if isinstance(baseline_metrics, Mapping):
            baseline_log_loss = _number(baseline_metrics.get("log_loss"))
            baseline_brier = _number(baseline_metrics.get("brier_score"))
            for model in models:
                metrics = model.get("oos_metrics", {})
                if not isinstance(metrics, Mapping):
                    continue
                log_loss = _number(metrics.get("log_loss"))
                brier = _number(metrics.get("brier_score"))
                model["incremental_vs_team"] = {
                    "log_loss_improvement": (
                        baseline_log_loss - log_loss
                        if baseline_log_loss is not None and log_loss is not None
                        else None
                    ),
                    "brier_improvement": (
                        baseline_brier - brier
                        if baseline_brier is not None and brier is not None
                        else None
                    ),
                    "decision": (
                        "RETAINED"
                        if baseline_log_loss is not None
                        and log_loss is not None
                        and baseline_brier is not None
                        and brier is not None
                        and log_loss < baseline_log_loss
                        and brier < baseline_brier
                        else "REJECTED"
                        if baseline_log_loss is not None
                        and log_loss is not None
                        and baseline_brier is not None
                        and brier is not None
                        and log_loss > baseline_log_loss
                        and brier > baseline_brier
                        else "INCONCLUSIVE"
                    ),
                }
    metadata = kernel_versions(devig_method)
    for result in (*models, *predictions):
        result.update(metadata)
    return models, predictions
