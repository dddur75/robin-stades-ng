"""Bounded cache-only walk-forward pilot for historical-deep evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from random import Random
from typing import Final

from robin.historical_deep.replay import canonical_sha256
from robin.market_math import (
    DevigMethod,
    kernel_versions,
    performance_summary,
)


class BacktestMode(StrEnum):
    STRICT_PREMATCH = "STRICT_PREMATCH"
    RECONSTRUCTED_POST_LINEUP = "RECONSTRUCTED_POST_LINEUP"
    DESCRIPTIVE_POST_MATCH = "DESCRIPTIVE_POST_MATCH"


BACKTEST_MODES: Final = tuple(mode.value for mode in BacktestMode)
_DATASET_MODE: Final = {
    "TEAM_PREMATCH_STRICT": BacktestMode.STRICT_PREMATCH.value,
    "PLAYER_PREMATCH_STRICT": BacktestMode.STRICT_PREMATCH.value,
    "LINEUP_HISTORY_PREMATCH_STRICT": BacktestMode.STRICT_PREMATCH.value,
    "TARGET_POST_LINEUP_RECONSTRUCTED": (
        BacktestMode.RECONSTRUCTED_POST_LINEUP.value
    ),
    "INJURY_INTERVAL_RECONSTRUCTED": (
        BacktestMode.RECONSTRUCTED_POST_LINEUP.value
    ),
    "POST_MATCH_DESCRIPTIVE": BacktestMode.DESCRIPTIVE_POST_MATCH.value,
}


def _datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"BACKTEST_{field.upper()}_INVALID") from exc
    else:
        raise ValueError(f"BACKTEST_{field.upper()}_REQUIRED")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"BACKTEST_{field.upper()}_UTC_REQUIRED")
    return result.astimezone(UTC)


def _mode(row: Mapping[str, object]) -> str:
    value = row.get("research_mode", row.get("mode"))
    if value is None:
        value = _DATASET_MODE.get(str(row.get("dataset_name", "")))
    mode = str(value or "")
    if mode not in BACKTEST_MODES:
        raise ValueError(f"BACKTEST_MODE_REQUIRED:{mode}")
    return mode


def _float(
    row: Mapping[str, object],
    fields: Sequence[str],
    *,
    required: bool,
) -> float | None:
    value = next(
        (row[field] for field in fields if row.get(field) not in (None, "")),
        None,
    )
    if value is None:
        if required:
            raise ValueError(f"BACKTEST_FIELD_REQUIRED:{fields[0]}")
        return None
    if isinstance(value, bool):
        if required:
            raise ValueError(f"BACKTEST_FIELD_INVALID:{fields[0]}")
        return None
    try:
        result = float(str(value))
    except ValueError as exc:
        raise ValueError(f"BACKTEST_FIELD_INVALID:{fields[0]}") from exc
    if not math.isfinite(result):
        raise ValueError(f"BACKTEST_FIELD_NON_FINITE:{fields[0]}")
    return result


def _number(value: object, *, field: str) -> float:
    try:
        return float(str(value))
    except ValueError as exc:
        raise ValueError(f"BACKTEST_FIELD_INVALID:{field}") from exc


def _integer(value: object, *, field: str) -> int:
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValueError(f"BACKTEST_FIELD_INVALID:{field}") from exc


def _score(row: Mapping[str, object]) -> float:
    result = _float(
        row,
        ("model_probability", "predicted_probability", "score", "probability"),
        required=True,
    )
    if result is None:
        raise RuntimeError("BACKTEST_REQUIRED_MODEL_PROBABILITY_MISSING")
    if not 0.0 <= result <= 1.0:
        raise ValueError("BACKTEST_MODEL_PROBABILITY_OUTSIDE_UNIT_INTERVAL")
    return result


def _target(row: Mapping[str, object]) -> int:
    value = row.get("target", row.get("outcome", row.get("won")))
    if isinstance(value, bool):
        return int(value)
    if value in {0, 1, "0", "1"}:
        return int(value)
    if isinstance(value, str):
        normalized = value.upper()
        if normalized in {"WIN", "WON", "YES", "POSITIVE", "HOME"}:
            return 1
        if normalized in {"LOSS", "LOST", "NO", "NEGATIVE", "NOT_HOME"}:
            return 0
    raise ValueError("BACKTEST_BINARY_TARGET_REQUIRED")


def _market_probability(row: Mapping[str, object]) -> float | None:
    probability = _float(
        row,
        ("market_probability", "baseline_probability"),
        required=False,
    )
    if probability is not None:
        if not 0.0 < probability < 1.0:
            raise ValueError("BACKTEST_MARKET_PROBABILITY_OUTSIDE_OPEN_UNIT_INTERVAL")
        return probability
    return None


def _odds(row: Mapping[str, object]) -> float | None:
    odds = _float(row, ("odds", "market_odds"), required=False)
    if odds is None:
        return None
    if odds <= 1.0:
        raise ValueError("BACKTEST_MARKET_ODDS_INVALID")
    return odds


def _period(row: Mapping[str, object]) -> str:
    value = row.get("period", row.get("season", row.get("fold")))
    if value in (None, ""):
        raise ValueError("BACKTEST_WALK_FORWARD_PERIOD_REQUIRED")
    return str(value)


def _kickoff(row: Mapping[str, object]) -> datetime:
    value = row.get("target_fixture_kickoff", row.get("kickoff_at"))
    return _datetime(value, field="target_fixture_kickoff")


def _fixture_id(row: Mapping[str, object]) -> str:
    value = row.get("target_fixture_id", row.get("fixture_id"))
    if value in (None, ""):
        raise ValueError("BACKTEST_FIXTURE_ID_REQUIRED")
    return str(value)


def _validate_cache_only(rows: Sequence[Mapping[str, object]]) -> None:
    for row in rows:
        provider_calls = row.get("provider_calls", 0)
        if provider_calls not in (None, 0, "0"):
            raise ValueError("BACKTEST_PROVIDER_CALL_FORBIDDEN")
        if str(row.get("source_mode", "")).upper() in {
            "LIVE_PROVIDER",
            "PROVIDER",
            "API",
        }:
            raise ValueError("BACKTEST_CACHE_ONLY_SOURCE_REQUIRED")
        if (
            _mode(row) != BacktestMode.DESCRIPTIVE_POST_MATCH.value
            and _market_probability(row) is None
        ):
            raise ValueError(
                f"BACKTEST_MARKET_BASELINE_REQUIRED:{_fixture_id(row)}"
            )
        cutoff = row.get(
            "max_feature_source_kickoff",
            row.get("feature_source_kickoff"),
        )
        if (
            _mode(row) == BacktestMode.STRICT_PREMATCH.value
            and cutoff not in (None, "")
            and _datetime(cutoff, field="feature_source_kickoff") >= _kickoff(row)
        ):
            raise ValueError(
                f"BACKTEST_STRICT_PREMATCH_LEAKAGE:{_fixture_id(row)}"
            )


def _profit(row: Mapping[str, object], *, threshold: float) -> float | None:
    if _score(row) < threshold:
        return None
    odds = _odds(row)
    if odds is None:
        return None
    return odds - 1.0 if _target(row) == 1 else -1.0


def select_threshold_train_only(
    training_rows: Sequence[Mapping[str, object]],
    *,
    candidates: Sequence[float] = (0.50, 0.55, 0.60, 0.65),
) -> dict[str, object]:
    if not training_rows:
        raise ValueError("BACKTEST_TRAINING_ROWS_REQUIRED")
    normalized = tuple(sorted(set(float(value) for value in candidates)))
    if not normalized or any(not 0.0 < value < 1.0 for value in normalized):
        raise ValueError("BACKTEST_THRESHOLD_CANDIDATES_INVALID")
    evaluations: list[dict[str, object]] = []
    for threshold in normalized:
        profits = [
            profit
            for row in training_rows
            if (profit := _profit(row, threshold=threshold)) is not None
        ]
        selected = [row for row in training_rows if _score(row) >= threshold]
        accuracy = (
            sum(_target(row) == 1 for row in selected) / len(selected)
            if selected
            else None
        )
        objective = (
            sum(profits) / len(profits)
            if profits
            else (accuracy - 0.5 if accuracy is not None else float("-inf"))
        )
        evaluations.append(
            {
                "threshold": threshold,
                "observations": len(selected),
                "bets": len(profits),
                "train_profit": sum(profits),
                "train_accuracy": accuracy,
                "objective": objective,
            }
        )
    eligible = [item for item in evaluations if item["observations"]]
    if not eligible:
        selected_threshold = normalized[0]
    else:
        selected_threshold = _number(
            max(
                eligible,
                key=lambda item: (
                    _number(item["objective"], field="objective"),
                    _integer(item["observations"], field="observations"),
                    -_number(item["threshold"], field="threshold"),
                ),
            )["threshold"],
            field="threshold",
        )
    return {
        "threshold": selected_threshold,
        "selection_policy": "TRAIN_ONLY",
        "candidates": evaluations,
        "training_rows": len(training_rows),
        "training_hash": canonical_sha256(list(training_rows)),
    }


def _binary_scores(
    rows: Sequence[Mapping[str, object]],
    *,
    probability_getter: object,
) -> dict[str, float | int | None]:
    if not rows:
        return {
            "rows": 0,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
        }
    probabilities: list[float] = []
    targets: list[int] = []
    for row in rows:
        if callable(probability_getter):
            raw = probability_getter(row)
        else:
            raw = None
        if raw is None:
            continue
        probability = float(raw)
        if not 0.0 < probability < 1.0:
            probability = min(max(probability, 1e-12), 1.0 - 1e-12)
        probabilities.append(probability)
        targets.append(_target(row))
    if not probabilities:
        return {
            "rows": 0,
            "accuracy": None,
            "brier": None,
            "log_loss": None,
        }
    accuracy = sum(
        (probability >= 0.5) == bool(target)
        for probability, target in zip(probabilities, targets, strict=True)
    ) / len(probabilities)
    brier = sum(
        (probability - target) ** 2
        for probability, target in zip(probabilities, targets, strict=True)
    ) / len(probabilities)
    log_loss = -sum(
        target * math.log(probability)
        + (1 - target) * math.log(1.0 - probability)
        for probability, target in zip(probabilities, targets, strict=True)
    ) / len(probabilities)
    return {
        "rows": len(probabilities),
        "accuracy": accuracy,
        "brier": brier,
        "log_loss": log_loss,
    }


def grouped_bootstrap(
    values: Sequence[float],
    groups: Sequence[str],
    *,
    iterations: int = 2_000,
    seed: int = 42,
) -> dict[str, object]:
    if len(values) != len(groups):
        raise ValueError("GROUPED_BOOTSTRAP_LENGTH_MISMATCH")
    if iterations <= 0:
        raise ValueError("GROUPED_BOOTSTRAP_ITERATIONS_MUST_BE_POSITIVE")
    grouped: dict[str, list[float]] = defaultdict(list)
    for value, group in zip(values, groups, strict=True):
        if not math.isfinite(value):
            raise ValueError("GROUPED_BOOTSTRAP_VALUE_NON_FINITE")
        grouped[str(group)].append(float(value))
    if not grouped:
        return {
            "groups": 0,
            "iterations": iterations,
            "mean": None,
            "ci_low": None,
            "ci_high": None,
            "method": "GROUPED_BOOTSTRAP",
        }
    names = sorted(grouped)
    # Deterministic research resampling, never a security or credential primitive.
    rng = Random(seed)  # nosec B311
    estimates: list[float] = []
    for _ in range(iterations):
        sampled = [rng.choice(names) for _ in names]
        values_sample = [
            value
            for group in sampled
            for value in grouped[group]
        ]
        estimates.append(sum(values_sample) / len(values_sample))
    estimates.sort()

    def quantile(probability: float) -> float:
        position = probability * (len(estimates) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return estimates[lower]
        weight = position - lower
        return estimates[lower] * (1.0 - weight) + estimates[upper] * weight

    observed = [value for values_group in grouped.values() for value in values_group]
    return {
        "groups": len(grouped),
        "iterations": iterations,
        "mean": sum(observed) / len(observed),
        "ci_low": quantile(0.025),
        "ci_high": quantile(0.975),
        "method": "GROUPED_BOOTSTRAP",
    }


def benjamini_hochberg(
    p_values: Mapping[str, float | None],
) -> dict[str, float | None]:
    valid: list[tuple[str, float]] = []
    output: dict[str, float | None] = {key: None for key in p_values}
    for key, value in p_values.items():
        if value is None:
            continue
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError(f"FDR_P_VALUE_INVALID:{key}")
        valid.append((key, numeric))
    valid.sort(key=lambda item: (item[1], item[0]))
    total = len(valid)
    running = 1.0
    for rank in range(total, 0, -1):
        key, value = valid[rank - 1]
        running = min(running, value * total / rank)
        output[key] = min(running, 1.0)
    return output


def _group_p_value(profits: Sequence[float], groups: Sequence[str]) -> float | None:
    totals: dict[str, float] = defaultdict(float)
    for profit, group in zip(profits, groups, strict=True):
        totals[group] += profit
    values = list(totals.values())
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    standard_error = math.sqrt(variance / len(values))
    if standard_error == 0.0:
        return 0.0 if mean > 0.0 else 1.0
    z_score = mean / standard_error
    return 0.5 * math.erfc(z_score / math.sqrt(2.0))


def concentration_audit(
    profits: Sequence[float],
    groups: Sequence[str],
) -> dict[str, object]:
    if len(profits) != len(groups):
        raise ValueError("CONCENTRATION_LENGTH_MISMATCH")
    absolute_by_group: dict[str, float] = defaultdict(float)
    for profit, group in zip(profits, groups, strict=True):
        absolute_by_group[str(group)] += abs(float(profit))
    total = sum(absolute_by_group.values())
    shares = {
        group: value / total if total else 0.0
        for group, value in sorted(absolute_by_group.items())
    }
    top_share = max(shares.values(), default=None)
    return {
        "groups": len(shares),
        "top_group_share": top_share,
        "herfindahl_index": sum(share**2 for share in shares.values()),
        "concentrated": top_share is not None and top_share > 0.50,
        "shares": shares,
    }


def _negative_control(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if len(rows) < 2:
        return {
            "method": "DETERMINISTIC_TARGET_ROTATION",
            "rows": len(rows),
            "status": "INSUFFICIENT_SAMPLE",
            "accuracy": None,
        }
    ordered = sorted(rows, key=lambda row: (_kickoff(row), _fixture_id(row)))
    targets = [_target(row) for row in ordered]
    rotated = targets[1:] + targets[:1]
    accuracy = sum(
        (_score(row) >= 0.5) == bool(target)
        for row, target in zip(ordered, rotated, strict=True)
    ) / len(ordered)
    return {
        "method": "DETERMINISTIC_TARGET_ROTATION",
        "rows": len(ordered),
        "status": "COMPUTED",
        "accuracy": accuracy,
    }


def _fold_result(
    training: Sequence[Mapping[str, object]],
    testing: Sequence[Mapping[str, object]],
    *,
    period: str,
    threshold_candidates: Sequence[float],
    devig_method: DevigMethod | str,
) -> dict[str, object]:
    threshold_evidence = select_threshold_train_only(
        training,
        candidates=threshold_candidates,
    )
    threshold = _number(threshold_evidence["threshold"], field="threshold")
    details: list[dict[str, object]] = []
    profits: list[float] = []
    groups: list[str] = []
    for row in sorted(testing, key=lambda item: (_kickoff(item), _fixture_id(item))):
        profit = _profit(row, threshold=threshold)
        group = f"{row.get('competition', 'UNKNOWN')}|{_period(row)}"
        if profit is not None:
            profits.append(profit)
            groups.append(group)
        details.append(
            {
                "fixture_id": _fixture_id(row),
                "kickoff_at": _kickoff(row).isoformat(),
                "score": _score(row),
                "threshold": threshold,
                "selected": profit is not None,
                "stake_units": 1.0 if profit is not None else None,
                "profit": profit,
                "bootstrap_group": group,
                "target": _target(row),
                "market_probability": _market_probability(row),
            }
        )
    model_scores = _binary_scores(testing, probability_getter=_score)
    market_scores = _binary_scores(
        testing,
        probability_getter=_market_probability,
    )
    train_max = max(_kickoff(row) for row in training)
    test_min = min(_kickoff(row) for row in testing)
    if train_max >= test_min:
        raise ValueError(f"BACKTEST_WALK_FORWARD_OVERLAP:{period}")
    bootstrap = grouped_bootstrap(profits, groups) if profits else grouped_bootstrap((), ())
    performance = performance_summary(
        starting_bankroll_units=100.0,
        stakes=[1.0 for _ in profits],
        profits=profits,
    )
    return {
        "test_period": period,
        "train_rows": len(training),
        "test_rows": len(testing),
        "train_max_kickoff": train_max.isoformat(),
        "test_min_kickoff": test_min.isoformat(),
        "temporal_order_verified": True,
        "threshold": threshold,
        "threshold_evidence": threshold_evidence,
        "model": model_scores,
        "market_baseline": market_scores,
        **performance,
        **kernel_versions(devig_method),
        "grouped_bootstrap": bootstrap,
        "grouped_p_value": _group_p_value(profits, groups) if profits else None,
        "concentration": concentration_audit(profits, groups),
        "negative_control": _negative_control(testing),
        "details": details,
    }


def run_cache_only_backtest(
    rows: Sequence[Mapping[str, object]],
    *,
    devig_method: DevigMethod | str,
    threshold_candidates: Sequence[float] = (0.50, 0.55, 0.60, 0.65),
    minimum_train_periods: int = 1,
) -> dict[str, object]:
    """Run separated walk-forward pilots; never return a promotion decision."""

    if minimum_train_periods <= 0:
        raise ValueError("BACKTEST_MINIMUM_TRAIN_PERIODS_MUST_BE_POSITIVE")
    _validate_cache_only(rows)
    by_mode: dict[str, list[Mapping[str, object]]] = {
        mode: [] for mode in BACKTEST_MODES
    }
    for row in rows:
        by_mode[_mode(row)].append(row)
    mode_results: dict[str, dict[str, object]] = {}
    p_values: dict[str, float | None] = {}
    for mode in BACKTEST_MODES:
        scoped = sorted(
            by_mode[mode],
            key=lambda row: (_kickoff(row), _fixture_id(row)),
        )
        if mode == BacktestMode.DESCRIPTIVE_POST_MATCH.value:
            mode_results[mode] = {
                "mode": mode,
                "rows": len(scoped),
                "predictive_evaluation": False,
                "reason": "POST_MATCH_DATA_DESCRIPTIVE_ONLY",
                "folds": [],
                "promotion": "NO_PROMOTION",
            }
            p_values[mode] = None
            continue
        periods = sorted(
            {_period(row) for row in scoped},
            key=lambda period: min(
                _kickoff(row) for row in scoped if _period(row) == period
            ),
        )
        folds: list[dict[str, object]] = []
        for position, period in enumerate(periods):
            if position < minimum_train_periods:
                continue
            testing = [row for row in scoped if _period(row) == period]
            test_min = min(_kickoff(row) for row in testing)
            training = [
                row
                for row in scoped
                if _period(row) in set(periods[:position])
                and _kickoff(row) < test_min
            ]
            if not training:
                continue
            folds.append(
                _fold_result(
                    training,
                    testing,
                    period=period,
                    threshold_candidates=threshold_candidates,
                    devig_method=devig_method,
                )
            )
        all_profits: list[float] = []
        all_groups: list[str] = []
        mode_p_values: list[float] = []
        for fold in folds:
            details_value = fold.get("details")
            if not isinstance(details_value, list):
                raise ValueError("BACKTEST_FOLD_DETAILS_INVALID")
            for detail_value in details_value:
                if not isinstance(detail_value, Mapping):
                    raise ValueError("BACKTEST_FOLD_DETAIL_INVALID")
                profit_value = detail_value.get("profit")
                if profit_value is None:
                    continue
                all_profits.append(_number(profit_value, field="profit"))
                all_groups.append(str(detail_value.get("bootstrap_group", "UNKNOWN")))
            p_value = fold.get("grouped_p_value")
            if p_value is not None:
                mode_p_values.append(_number(p_value, field="grouped_p_value"))
        combined_p = (
            min(min(mode_p_values) * len(mode_p_values), 1.0)
            if mode_p_values
            else None
        )
        p_values[mode] = combined_p
        performance = performance_summary(
            starting_bankroll_units=100.0,
            stakes=[1.0 for _ in all_profits],
            profits=all_profits,
        )
        mode_results[mode] = {
            "mode": mode,
            "rows": len(scoped),
            "predictive_evaluation": True,
            "folds": folds,
            "walk_forward": True,
            "threshold_policy": "TRAIN_ONLY",
            "market_baseline_required": True,
            **performance,
            **kernel_versions(devig_method),
            "grouped_bootstrap": (
                grouped_bootstrap(all_profits, all_groups)
                if all_profits
                else grouped_bootstrap((), ())
            ),
            "concentration": concentration_audit(all_profits, all_groups),
            "negative_controls": [
                fold["negative_control"] for fold in folds
            ],
            "raw_p_value": combined_p,
            "promotion": "NO_PROMOTION",
        }
    adjusted = benjamini_hochberg(p_values)
    for mode, q_value in adjusted.items():
        mode_results[mode]["fdr_method"] = "BENJAMINI_HOCHBERG"
        mode_results[mode]["fdr_q_value"] = q_value
    return {
        "schema_version": "historical-deep-cache-only-backtest-v1",
        "cache_only": True,
        "provider_calls": 0,
        "provider_credits": 0,
        "dataset_hash": canonical_sha256(list(rows)),
        "modes": mode_results,
        "mode_separation_verified": True,
        "multiple_testing_method": "BENJAMINI_HOCHBERG",
        "promotion": "NO_PROMOTION",
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        **kernel_versions(devig_method),
    }


run_backtest_pilot = run_cache_only_backtest
