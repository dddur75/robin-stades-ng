"""Jalon 7: reproducible, paired and temporally honest model evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

from robin.historical.model_lab import (
    LINEUP_FEATURES,
    PLAYER_FEATURES,
    TEAM_FEATURES,
    _fit_multinomial,
    _matrix,
    _metrics,
    _predict_multinomial,
    isotonic_calibrate,
    sigmoid_calibrate,
    target,
)

SEED = 1707
BOOTSTRAP_ITERATIONS = 5_000
CALIBRATION_METHODS = (
    "NONE",
    "TEMPERATURE_SCALING",
    "SIGMOID",
    "ISOTONIC",
)
OOS_GOVERNANCE: dict[str, object] = {
    "protocol": "OOS_GOVERNANCE_V1",
    "periods": {
        "DISCOVERY": [2020, 2021, 2022],
        "VALIDATION": [2023],
        "EXPOSED_HISTORICAL_OOS": [2024, 2025],
        "LIVE_PROSPECTIVE": [2026, 2027],
    },
    "selection_rule": (
        "No parameter, feature, calibration or strategy threshold may be selected "
        "from EXPOSED_HISTORICAL_OOS or LIVE_PROSPECTIVE."
    ),
}
EXTERNAL_COMPETITIONS = (
    "Premier League",
    "La Liga",
    "Bundesliga",
    "Serie A",
    "UEFA Champions League",
)


def stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def external_validation_protocol() -> dict[str, object]:
    """Return the preregistered protocol, before any external result is observed."""

    protocol: dict[str, object] = {
        "protocol_id": "EXTERNAL_VALIDATION_PROTOCOL_V1",
        "registered_before_results": True,
        "competitions": list(EXTERNAL_COMPETITIONS),
        "minimum_seasons": 3,
        "primary_metric": "paired_log_loss_delta",
        "secondary_metrics": ["brier_score", "ece", "accuracy"],
        "pairing_key": [
            "fixture_id",
            "season",
            "target",
            "market_snapshot",
            "temporal_policy",
        ],
        "confidence_intervals": [0.90, 0.95],
        "bootstrap_unit": "season_and_iso_week",
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "success_rule": (
            "95% interval excludes zero in the favourable direction and "
            "P(superiority)>=0.95 on at least three competitions."
        ),
        "failure_rule": "No promotion; retain as research result.",
        "production_status": "PRODUCTION_LOCKED",
    }
    protocol["protocol_hash"] = stable_hash(protocol)
    return protocol


def freeze_jalon6(
    state: Path,
    *,
    source_commit: str,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Freeze Jalon 6 artifacts; an existing freeze may never silently change."""

    roots = ("datasets", "models", "backtests", "strategies")
    destination = output_path or state / "arena" / "jalon6-baseline-frozen.json"
    if destination.exists():
        existing = cast(
            dict[str, object],
            json.loads(destination.read_text(encoding="utf-8")),
        )
        artifacts = cast(list[dict[str, object]], existing.get("artifacts", []))
        for artifact in artifacts:
            path = state / str(artifact["path"])
            if (
                not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest()
                != artifact["sha256"]
            ):
                raise RuntimeError("JALON6_BASELINE_IMMUTABLE_VIOLATION")
        return existing
    files: list[dict[str, object]] = []
    for root_name in roots:
        root = state / root_name
        for path in sorted(root.glob("*.json")):
            if path.name.startswith("jalon7"):
                continue
            content = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(state).as_posix(),
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    freeze: dict[str, object] = {
        "status": "JALON6_BASELINE_FROZEN",
        "source_commit": source_commit,
        "artifacts": files,
        "artifact_count": len(files),
        "oos_governance": OOS_GOVERNANCE,
        "production_status": "PRODUCTION_LOCKED",
    }
    freeze["baseline_hash"] = stable_hash(freeze)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(freeze, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return freeze


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return None if not math.isfinite(number) else number


def _probabilities(row: Mapping[str, object]) -> np.ndarray:
    values = np.asarray(
        [
            _number(row.get("probability_home")),
            _number(row.get("probability_draw")),
            _number(row.get("probability_away")),
        ],
        dtype=np.float64,
    )
    if np.isnan(values).any() or (values < 0.0).any() or values.sum() <= 0.0:
        raise ValueError("INVALID_PROBABILITIES")
    return values / values.sum()


def _pair_key(row: Mapping[str, object]) -> tuple[str, int, int, str, str]:
    fixture_id = str(row.get("fixture_id", ""))
    season = int(str(row.get("season", 0)))
    label = int(str(row.get("target", -1)))
    market = str(row.get("market_snapshot", row.get("market_source", "")))
    policy = str(row.get("temporal_policy", row.get("availability_status", "")))
    return fixture_id, season, label, market, policy


def validate_exact_pairing(
    challenger: Sequence[Mapping[str, object]],
    reference: Sequence[Mapping[str, object]],
) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    """Require exact fixture/target/market/temporal pairing, never an outer join."""

    challenger_by_fixture = {str(row.get("fixture_id")): row for row in challenger}
    reference_by_fixture = {str(row.get("fixture_id")): row for row in reference}
    shared = sorted(challenger_by_fixture.keys() & reference_by_fixture.keys())
    pairs: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for fixture_id in shared:
        left = challenger_by_fixture[fixture_id]
        right = reference_by_fixture[fixture_id]
        if _pair_key(left) != _pair_key(right):
            raise ValueError(f"PAIRED_PROTOCOL_MISMATCH:{fixture_id}")
        pairs.append((left, right))
    if not pairs:
        raise ValueError("NO_EXACT_PAIRED_FIXTURES")
    return pairs


def _losses(rows: Sequence[Mapping[str, object]]) -> np.ndarray:
    return np.asarray(
        [
            -math.log(max(float(_probabilities(row)[int(str(row["target"]))]), 1e-12))
            for row in rows
        ],
        dtype=np.float64,
    )


def grouped_bootstrap(
    deltas: np.ndarray,
    groups: Sequence[str],
    *,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = SEED,
) -> dict[str, object]:
    """Bootstrap full season-week groups to preserve within-round dependence."""

    if iterations < 2_000:
        raise ValueError("BOOTSTRAP_ITERATIONS_TOO_LOW")
    if len(deltas) != len(groups) or len(deltas) == 0:
        raise ValueError("INVALID_BOOTSTRAP_INPUT")
    grouped: dict[str, list[float]] = defaultdict(list)
    for group, value in zip(groups, deltas, strict=True):
        grouped[group].append(float(value))
    keys = sorted(grouped)
    rng = np.random.default_rng(seed)
    estimates = np.empty(iterations, dtype=np.float64)
    for index in range(iterations):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        values = [value for key in sampled for value in grouped[str(key)]]
        estimates[index] = float(np.mean(values))
    return {
        "iterations": iterations,
        "seed": seed,
        "groups": len(keys),
        "ci90": [
            float(np.quantile(estimates, 0.05)),
            float(np.quantile(estimates, 0.95)),
        ],
        "ci95": [
            float(np.quantile(estimates, 0.025)),
            float(np.quantile(estimates, 0.975)),
        ],
        "probability_challenger_better": float(np.mean(estimates < 0.0)),
    }


def _iso_group(row: Mapping[str, object]) -> str:
    raw = str(row.get("kickoff_at", ""))
    try:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        iso = instant.isocalendar()
        return f"{int(str(row['season']))}:{iso.year}-W{iso.week:02d}"
    except (TypeError, ValueError):
        return f"{int(str(row.get('season', 0)))}:UNKNOWN"


def paired_model_comparison(
    challenger: Sequence[Mapping[str, object]],
    reference: Sequence[Mapping[str, object]],
    *,
    comparison_id: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> dict[str, object]:
    pairs = validate_exact_pairing(challenger, reference)
    left = [pair[0] for pair in pairs]
    right = [pair[1] for pair in pairs]
    labels = np.asarray([int(str(row["target"])) for row in left], dtype=np.int64)
    left_probabilities = np.vstack([_probabilities(row) for row in left])
    right_probabilities = np.vstack([_probabilities(row) for row in right])
    delta = _losses(left) - _losses(right)
    uncertainty = grouped_bootstrap(
        delta,
        [_iso_group(row) for row in left],
        iterations=iterations,
    )
    ci95 = cast(list[float], uncertainty["ci95"])
    status = (
        "SUPERIOR"
        if ci95[1] < 0.0 and float(str(uncertainty["probability_challenger_better"])) >= 0.95
        else "INCONCLUSIVE"
    )
    return {
        "comparison_id": comparison_id,
        "protocol": "EXACT_PAIRED_FIXTURES_V1",
        "paired_fixtures": len(pairs),
        "challenger_metrics": _metrics(left_probabilities, labels),
        "reference_metrics": _metrics(right_probabilities, labels),
        "paired_log_loss_delta": float(delta.mean()),
        "uncertainty": uncertainty,
        "status": status,
        "production_status": "PRODUCTION_LOCKED",
    }


def temperature_calibrate(
    validation: np.ndarray,
    labels: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, float]:
    temperatures = np.linspace(0.5, 3.0, 101)
    losses: list[float] = []
    for temperature in temperatures:
        adjusted = np.power(np.clip(validation, 1e-12, 1.0), 1.0 / temperature)
        adjusted /= adjusted.sum(axis=1, keepdims=True)
        losses.append(float(_metrics(adjusted, labels)["log_loss"]))
    selected = float(temperatures[int(np.argmin(losses))])
    result = np.power(np.clip(values, 1e-12, 1.0), 1.0 / selected)
    return result / result.sum(axis=1, keepdims=True), selected


def select_cross_fitted_calibration(
    probabilities: np.ndarray,
    labels: np.ndarray,
    folds: Sequence[int],
) -> dict[str, object]:
    """Select a calibrator only from predictions generated by earlier folds."""

    unique_folds = sorted(set(folds))
    if len(unique_folds) < 2:
        return {"method": "NONE", "reason": "INSUFFICIENT_TEMPORAL_FOLDS"}
    candidates: dict[str, list[float]] = {method: [] for method in CALIBRATION_METHODS}
    for fold in unique_folds[1:]:
        train_mask = np.asarray([value < fold for value in folds])
        test_mask = np.asarray([value == fold for value in folds])
        if not train_mask.any() or not test_mask.any():
            continue
        train_values = probabilities[train_mask]
        train_labels = labels[train_mask]
        test_values = probabilities[test_mask]
        values_by_method = {
            "NONE": test_values,
            "TEMPERATURE_SCALING": temperature_calibrate(train_values, train_labels, test_values)[
                0
            ],
            "SIGMOID": sigmoid_calibrate(train_values, train_labels, test_values),
            "ISOTONIC": isotonic_calibrate(train_values, train_labels, test_values),
        }
        fold_labels = labels[test_mask]
        for method, values in values_by_method.items():
            candidates[method].append(float(_metrics(values, fold_labels)["log_loss"]))
    means = {
        method: float(np.mean(losses)) if losses else float("inf")
        for method, losses in candidates.items()
    }
    selected = min(means, key=means.__getitem__)
    return {
        "method": selected,
        "cross_fitted_log_loss": means,
        "folds": unique_folds,
        "leakage_guard": "CALIBRATOR_FIT_ONLY_ON_STRICTLY_EARLIER_FOLDS",
    }


def _poisson_probability(goals: int, rate: float) -> float:
    return math.exp(-rate) * rate**goals / math.factorial(goals)


def score_distribution(
    home_rate: float,
    away_rate: float,
    *,
    method: str = "POISSON",
    rho: float = -0.08,
    max_goals: int = 10,
) -> np.ndarray:
    if home_rate <= 0.0 or away_rate <= 0.0:
        raise ValueError("POSITIVE_GOAL_RATES_REQUIRED")
    matrix = np.asarray(
        [
            [
                _poisson_probability(home, home_rate) * _poisson_probability(away, away_rate)
                for away in range(max_goals + 1)
            ]
            for home in range(max_goals + 1)
        ],
        dtype=np.float64,
    )
    if method == "DIXON_COLES":
        matrix[0, 0] *= 1.0 - home_rate * away_rate * rho
        matrix[0, 1] *= 1.0 + home_rate * rho
        matrix[1, 0] *= 1.0 + away_rate * rho
        matrix[1, 1] *= 1.0 - rho
    elif method != "POISSON":
        raise ValueError(f"UNKNOWN_SCORE_MODEL:{method}")
    return matrix / matrix.sum()


def score_market_probabilities(matrix: np.ndarray) -> dict[str, float]:
    home = float(np.tril(matrix, k=-1).sum())
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, k=1).sum())
    over = float(
        sum(
            matrix[left, right]
            for left in range(matrix.shape[0])
            for right in range(matrix.shape[1])
            if left + right > 2
        )
    )
    btts = float(matrix[1:, 1:].sum())
    return {
        "probability_home": home,
        "probability_draw": draw,
        "probability_away": away,
        "probability_over_25": over,
        "probability_under_25": 1.0 - over,
        "probability_btts_yes": btts,
        "probability_btts_no": 1.0 - btts,
    }


def _rolling_goal_rates(
    rows: Sequence[Mapping[str, object]],
) -> list[tuple[float, float]]:
    history_for: dict[str, list[float]] = defaultdict(list)
    history_against: dict[str, list[float]] = defaultdict(list)
    rates: list[tuple[float, float]] = []
    for row in sorted(rows, key=lambda item: str(item.get("kickoff_at", ""))):
        home = str(row.get("home_team_id", row.get("home_team", "")))
        away = str(row.get("away_team_id", row.get("away_team", "")))
        home_for = history_for[home][-10:]
        away_for = history_for[away][-10:]
        home_against = history_against[home][-10:]
        away_against = history_against[away][-10:]
        home_rate = (
            (float(np.mean(home_for)) + float(np.mean(away_against))) / 2.0
            if home_for and away_against
            else 1.45
        )
        away_rate = (
            (float(np.mean(away_for)) + float(np.mean(home_against))) / 2.0
            if away_for and home_against
            else 1.15
        )
        rates.append((max(home_rate, 0.15), max(away_rate, 0.15)))
        home_goals = _number(row.get("target_home_goals"))
        away_goals = _number(row.get("target_away_goals"))
        if home_goals is not None and away_goals is not None:
            history_for[home].append(home_goals)
            history_against[home].append(away_goals)
            history_for[away].append(away_goals)
            history_against[away].append(home_goals)
    return rates


def score_model_predictions(
    rows: Sequence[Mapping[str, object]],
    *,
    method: str,
    seasons: Iterable[int] = (2024, 2025),
) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda item: str(item.get("kickoff_at", "")))
    rates = _rolling_goal_rates(ordered)
    allowed = set(seasons)
    predictions: list[dict[str, object]] = []
    for row, (home_rate, away_rate) in zip(ordered, rates, strict=True):
        label = target(row)
        season = int(str(row.get("season", 0)))
        if label is None or season not in allowed:
            continue
        probabilities = score_market_probabilities(
            score_distribution(home_rate, away_rate, method=method)
        )
        predictions.append(
            {
                **probabilities,
                "fixture_id": row["fixture_id"],
                "season": season,
                "kickoff_at": row["kickoff_at"],
                "target": label,
                "model_version": f"{method.lower()}_score_v1",
                "dataset_version": "api_team_pre_match_v1",
                "market_snapshot": row.get("market_source", ""),
                "temporal_policy": row.get("temporal_policy", "HISTORICAL POINT-IN-TIME"),
                "odds_home": row.get("odds_home"),
                "odds_draw": row.get("odds_draw"),
                "odds_away": row.get("odds_away"),
                "odds_over_25": row.get("odds_over_25"),
                "odds_under_25": row.get("odds_under_25"),
                "target_over_25": int(
                    float(str(row["target_home_goals"]))
                    + float(str(row["target_away_goals"]))
                    > 2.5
                ),
                "home_rate": home_rate,
                "away_rate": away_rate,
                "origin": "EXPOSED_HISTORICAL_OOS",
            }
        )
    return predictions


def temporal_discriminative_predictions(
    rows: Sequence[Mapping[str, object]],
    *,
    model_family: str,
    model_version: str | None = None,
    features: Sequence[str] = TEAM_FEATURES,
    evaluation_seasons: Iterable[int] = (2021, 2022, 2023, 2024, 2025),
) -> list[dict[str, object]]:
    """Walk forward: each evaluated season is fitted exclusively on earlier seasons."""

    eligible = [
        dict(row)
        for row in rows
        if target(row) is not None and int(str(row.get("season", 0))) >= 2020
    ]
    seasons = set(evaluation_seasons)
    predictions: list[dict[str, object]] = []
    for season in sorted(seasons):
        train_rows = [row for row in eligible if int(str(row.get("season", 0))) < season]
        test_rows = [row for row in eligible if int(str(row.get("season", 0))) == season]
        if not train_rows or not test_rows:
            continue
        active_features = tuple(
            feature
            for feature in features
            if any(_number(row.get(feature)) is not None for row in train_rows)
        )
        if not active_features:
            continue
        train_matrix, imputation = _matrix(train_rows, active_features)
        test_matrix, _ = _matrix(
            test_rows,
            active_features,
            imputation=imputation,
        )
        train_labels = np.asarray([cast(int, target(row)) for row in train_rows], dtype=np.int64)
        if model_family == "MULTINOMIAL":
            weights, mean, scale = _fit_multinomial(train_matrix, train_labels)
            probabilities = _predict_multinomial(test_matrix, weights, mean, scale)
        elif model_family == "HIST_GRADIENT_BOOSTING":
            estimator = HistGradientBoostingClassifier(
                learning_rate=0.05,
                max_iter=150,
                max_leaf_nodes=15,
                l2_regularization=0.1,
                early_stopping=False,
                random_state=SEED,
            )
            estimator.fit(train_matrix, train_labels)
            raw = estimator.predict_proba(test_matrix)
            probabilities = np.zeros((len(test_rows), 3), dtype=np.float64)
            for index, class_value in enumerate(estimator.classes_):
                probabilities[:, int(class_value)] = raw[:, index]
        else:
            raise ValueError(f"UNKNOWN_DISCRIMINATIVE_FAMILY:{model_family}")
        for row, values in zip(test_rows, probabilities, strict=True):
            predictions.append(
                {
                    "fixture_id": row["fixture_id"],
                    "season": season,
                    "kickoff_at": row["kickoff_at"],
                    "target": cast(int, target(row)),
                    "model_version": model_version or f"{model_family.lower()}_walk_forward_v1",
                    "dataset_version": row.get("dataset_version", "api_team_pre_match_v1"),
                    "probability_home": float(values[0]),
                    "probability_draw": float(values[1]),
                    "probability_away": float(values[2]),
                    "market_snapshot": row.get("market_source", ""),
                    "temporal_policy": "PRE_MATCH_CUTOFF",
                    "odds_home": row.get("odds_home"),
                    "odds_draw": row.get("odds_draw"),
                    "odds_away": row.get("odds_away"),
                    "fit_seasons": sorted({int(str(item.get("season", 0))) for item in train_rows}),
                    "active_features": list(active_features),
                    "origin": (
                        "EXPOSED_HISTORICAL_OOS"
                        if season in {2024, 2025}
                        else "CROSS_FITTED_DEVELOPMENT"
                    ),
                }
            )
    return predictions


def apply_selected_calibration(
    development: Sequence[Mapping[str, object]],
    evaluation: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Select with temporal OOF data, then fit once and apply to exposed OOS."""

    dev_probabilities = np.vstack([_probabilities(row) for row in development])
    dev_labels = np.asarray([int(str(row["target"])) for row in development], dtype=np.int64)
    folds = [int(str(row["season"])) for row in development]
    selection = select_cross_fitted_calibration(dev_probabilities, dev_labels, folds)
    values = np.vstack([_probabilities(row) for row in evaluation])
    method = str(selection["method"])
    parameter: float | None = None
    if method == "TEMPERATURE_SCALING":
        calibrated, parameter = temperature_calibrate(dev_probabilities, dev_labels, values)
    elif method == "SIGMOID":
        calibrated = sigmoid_calibrate(dev_probabilities, dev_labels, values)
    elif method == "ISOTONIC":
        calibrated = isotonic_calibrate(dev_probabilities, dev_labels, values)
    else:
        calibrated = values
    output: list[dict[str, object]] = []
    for row, probabilities in zip(evaluation, calibrated, strict=True):
        output.append(
            {
                **dict(row),
                "probability_home": float(probabilities[0]),
                "probability_draw": float(probabilities[1]),
                "probability_away": float(probabilities[2]),
                "calibration": method,
            }
        )
    selection["temperature"] = parameter
    selection["fit_rows"] = len(development)
    selection["evaluation_rows"] = len(evaluation)
    selection["evaluation_labels_used_for_selection"] = 0
    return output, selection


def deterministic_permutation_control(
    rows: Sequence[Mapping[str, object]],
    *,
    features: Sequence[str] = TEAM_FEATURES,
    seed: int = SEED,
) -> dict[str, object]:
    eligible = [dict(row) for row in rows if target(row) is not None]
    rng = np.random.default_rng(seed)
    labels = np.asarray([cast(int, target(row)) for row in eligible], dtype=np.int64)
    shuffled = rng.permutation(labels)
    matrix, _ = _matrix(eligible, features)
    split = max(1, int(len(eligible) * 0.7))
    weights, mean, scale = _fit_multinomial(matrix[:split], shuffled[:split])
    probabilities = _predict_multinomial(matrix[split:], weights, mean, scale)
    metrics = _metrics(probabilities, shuffled[split:])
    return {
        "control": "PERMUTED_TARGET",
        "seed": seed,
        "metrics": metrics,
        "expected_result": "NO_RELIABLE_SIGNAL",
        "status": ("PASSED" if float(metrics["log_loss"]) >= 0.95 else "SUSPICIOUS_SIGNAL"),
    }


def random_lineup_control(
    rows: Sequence[Mapping[str, object]],
    *,
    seed: int = SEED,
) -> dict[str, object]:
    eligible = [dict(row) for row in rows if target(row) is not None]
    rng = np.random.default_rng(seed)
    for feature in (*PLAYER_FEATURES, *LINEUP_FEATURES):
        values = np.asarray([row.get(feature) for row in eligible], dtype=object)
        shuffled = rng.permutation(values).tolist()
        for row, value in zip(eligible, shuffled, strict=True):
            row[feature] = value
    return {
        "control": "RANDOM_LINEUP_ASSIGNMENT",
        "seed": seed,
        "rows": len(eligible),
        "permuted_features": len((*PLAYER_FEATURES, *LINEUP_FEATURES)),
        "dataset_hash": stable_hash(eligible),
        "expected_result": "NO_PLAYER_UPLIFT",
        "status": "CONTROL_DATASET_READY",
    }


def ablation_registry() -> list[dict[str, object]]:
    groups: dict[str, Sequence[str]] = {
        "TEAM_FORM": TEAM_FEATURES,
        "PLAYER_PRE_LINEUP": PLAYER_FEATURES,
        "CONFIRMED_LINEUP": LINEUP_FEATURES,
        "MARKET": ("odds_home", "odds_draw", "odds_away"),
    }
    return [
        {
            "ablation_id": f"WITHOUT_{name}",
            "removed_features": list(features),
            "comparison": "EXACT_PAIRED_FIXTURES_V1",
            "status": "PREREGISTERED",
        }
        for name, features in groups.items()
    ]


def feature_stability_audit(
    rows: Sequence[Mapping[str, object]],
    *,
    features: Sequence[str],
) -> list[dict[str, object]]:
    """Measure missingness and sign stability by season without target tuning."""

    audits: list[dict[str, object]] = []
    seasons = sorted({int(str(row.get("season", 0))) for row in rows})
    for feature in features:
        correlations: dict[str, float | None] = {}
        missing = 0
        observed = 0
        for season in seasons:
            pairs: list[tuple[float, float]] = []
            for row in rows:
                if int(str(row.get("season", 0))) != season:
                    continue
                value = _number(row.get(feature))
                label = target(row)
                if value is None:
                    missing += 1
                    continue
                if label is not None:
                    pairs.append((value, float(label)))
                    observed += 1
            if len(pairs) < 3:
                correlations[str(season)] = None
                continue
            matrix = np.asarray(pairs, dtype=np.float64)
            if matrix[:, 0].std() < 1e-12 or matrix[:, 1].std() < 1e-12:
                correlations[str(season)] = 0.0
            else:
                correlations[str(season)] = float(
                    np.corrcoef(matrix[:, 0], matrix[:, 1])[0, 1]
                )
        signs = {
            int(math.copysign(1, value))
            for value in correlations.values()
            if value is not None and abs(value) >= 0.02
        }
        audits.append(
            {
                "feature": feature,
                "importance_proxy": "SEASONAL_TARGET_CORRELATION_DIAGNOSTIC_ONLY",
                "correlation_by_season": correlations,
                "missing_rate": (
                    missing / (missing + observed) if missing + observed else None
                ),
                "direction_stable": len(signs) <= 1,
                "status": "STABLE" if len(signs) <= 1 else "UNSTABLE",
                "promotion_use": "FORBIDDEN",
            }
        )
    return audits


def strategy_lab_v2_protocol() -> dict[str, object]:
    protocol: dict[str, object] = {
        "protocol_id": "STRATEGY_LAB_V2_PREREGISTERED",
        "markets": ["1X2", "OVER_UNDER_2_5", "BTTS"],
        "edge_thresholds": [0.03, 0.05, 0.07],
        "minimum_odds": [1.5, 1.7],
        "maximum_odds": [3.5, 5.0],
        "staking": ["FLAT_1_UNIT", "FRACTIONAL_KELLY_0_10"],
        "maximum_stake_units": 1.0,
        "daily_risk_limit_units": 3.0,
        "selection_period": "DISCOVERY_AND_VALIDATION_ONLY",
        "promotion_rule": (
            "No promotion without positive paired 95% interval, adequate sample, "
            "external validation and independent LIVE_PROSPECTIVE confirmation."
        ),
        "production_status": "PRODUCTION_LOCKED",
    }
    protocol["protocol_hash"] = stable_hash(protocol)
    return protocol


def storage_guard(
    current_bytes: int,
    *,
    warning_bytes: int = 750_000_000,
    pause_bytes: int = 900_000_000,
) -> dict[str, object]:
    if current_bytes >= pause_bytes:
        status = "PAUSED"
    elif current_bytes >= warning_bytes:
        status = "WARNING"
    else:
        status = "SAFE"
    return {
        "status": status,
        "current_bytes": current_bytes,
        "warning_bytes": warning_bytes,
        "pause_bytes": pause_bytes,
        "can_write": status != "PAUSED",
    }


def arena_cache_key(
    dataset_manifests: Sequence[Mapping[str, object]],
    *,
    code_revision: str,
) -> str:
    return stable_hash(
        {
            "datasets": [
                {
                    "name": item.get("dataset_name"),
                    "sha256": item.get("sha256"),
                }
                for item in dataset_manifests
            ],
            "protocol": external_validation_protocol()["protocol_hash"],
            "code_revision": code_revision,
            "seed": SEED,
        }
    )
