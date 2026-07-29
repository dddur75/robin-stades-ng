"""Hierarchical, paired and train-only validation primitives."""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Mapping, Sequence

from robin.hypothesis_intelligence.contracts import canonical_sha256


@dataclass(frozen=True, slots=True)
class HierarchicalMetrics:
    child_id: str
    parent_id: str
    paired_support: int
    incremental_information: float
    incremental_log_loss: float
    incremental_brier: float
    incremental_roi: float | None
    support_loss: int
    complexity_cost: float
    stability_change: float
    concentration_change: float
    market_reference: str
    baseline_reference: str

    @property
    def metrics_hash(self) -> str:
        return canonical_sha256(asdict(self))


def _clip_probability(value: float) -> float:
    return min(max(value, 1e-12), 1 - 1e-12)


def binary_log_loss(outcomes: Sequence[int], probabilities: Sequence[float]) -> float:
    if len(outcomes) != len(probabilities) or not outcomes:
        raise ValueError("LOG_LOSS_REQUIRES_PAIRED_NONEMPTY_INPUT")
    return -statistics.fmean(
        outcome * math.log(_clip_probability(probability))
        + (1 - outcome) * math.log(1 - _clip_probability(probability))
        for outcome, probability in zip(outcomes, probabilities, strict=True)
    )


def binary_brier(outcomes: Sequence[int], probabilities: Sequence[float]) -> float:
    if len(outcomes) != len(probabilities) or not outcomes:
        raise ValueError("BRIER_REQUIRES_PAIRED_NONEMPTY_INPUT")
    return statistics.fmean(
        (probability - outcome) ** 2
        for outcome, probability in zip(outcomes, probabilities, strict=True)
    )


def compare_child_to_parent(
    *,
    child_id: str,
    parent_id: str,
    outcomes: Sequence[int],
    child_probabilities: Sequence[float],
    parent_probabilities: Sequence[float],
    market_probabilities: Sequence[float],
    child_returns: Sequence[float] | None,
    parent_returns: Sequence[float] | None,
    parent_support: int,
    child_depth: int,
    stability_change: float,
    concentration_change: float,
) -> HierarchicalMetrics:
    lengths = {
        len(outcomes),
        len(child_probabilities),
        len(parent_probabilities),
        len(market_probabilities),
    }
    if len(lengths) != 1 or not outcomes:
        raise ValueError("HIERARCHICAL_VALIDATION_REQUIRES_PAIRED_ROWS")
    child_log_loss = binary_log_loss(outcomes, child_probabilities)
    parent_log_loss = binary_log_loss(outcomes, parent_probabilities)
    child_brier = binary_brier(outcomes, child_probabilities)
    parent_brier = binary_brier(outcomes, parent_probabilities)
    market_log_loss = binary_log_loss(outcomes, market_probabilities)
    incremental_roi: float | None = None
    if child_returns is not None or parent_returns is not None:
        if (
            child_returns is None
            or parent_returns is None
            or len(child_returns) != len(outcomes)
            or len(parent_returns) != len(outcomes)
        ):
            raise ValueError("ROI_COMPARISON_REQUIRES_PAIRED_REPRODUCIBLE_PRICES")
        incremental_roi = statistics.fmean(child_returns) - statistics.fmean(parent_returns)
    return HierarchicalMetrics(
        child_id=child_id,
        parent_id=parent_id,
        paired_support=len(outcomes),
        incremental_information=market_log_loss - child_log_loss,
        incremental_log_loss=parent_log_loss - child_log_loss,
        incremental_brier=parent_brier - child_brier,
        incremental_roi=incremental_roi,
        support_loss=max(0, parent_support - len(outcomes)),
        complexity_cost=child_depth * math.log2(child_depth + 1),
        stability_change=stability_change,
        concentration_change=concentration_change,
        market_reference="PAIRED_DEVIGGED_MARKET",
        baseline_reference=parent_id,
    )


def benjamini_hochberg(
    p_values: Mapping[str, float],
) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    previous = 1.0
    for reverse_index, (identifier, p_value) in enumerate(
        reversed(ordered),
        start=1,
    ):
        rank = count - reverse_index + 1
        q_value = min(previous, p_value * count / rank)
        adjusted[identifier] = min(1.0, q_value)
        previous = q_value
    return adjusted


def hierarchical_gatekeeping(
    *,
    p_values: Mapping[str, float],
    parent_by_child: Mapping[str, str | None],
    family_by_node: Mapping[str, str],
    alpha: float = 0.05,
) -> dict[str, dict[str, object]]:
    if not 0 < alpha < 1:
        raise ValueError("HIERARCHICAL_ALPHA_INVALID")
    family_members: dict[str, dict[str, float]] = {}
    for identifier, p_value in p_values.items():
        family_members.setdefault(family_by_node[identifier], {})[identifier] = p_value
    family_q = {
        identifier: q_value
        for values in family_members.values()
        for identifier, q_value in benjamini_hochberg(values).items()
    }
    global_q = benjamini_hochberg(p_values)
    output: dict[str, dict[str, object]] = {}
    visiting: set[str] = set()

    def resolve(identifier: str) -> dict[str, object]:
        if identifier in output:
            return output[identifier]
        if identifier in visiting:
            raise ValueError("HIERARCHICAL_PARENT_CYCLE")
        visiting.add(identifier)
        parent = parent_by_child.get(identifier)
        if parent is not None and parent not in p_values:
            raise ValueError(f"HIERARCHICAL_PARENT_UNKNOWN:{parent}")
        parent_open = parent is None or bool(resolve(parent)["gate_open_for_children"])
        rejected = parent_open and family_q[identifier] <= alpha and global_q[identifier] <= alpha
        decision: dict[str, object] = {
            "family_q_value": family_q[identifier],
            "global_q_value": global_q[identifier],
            "parent_gate_open": parent_open,
            "gate_open_for_children": rejected,
            "scientific_status": ("EXPLORATORY_SIGNAL" if rejected else "REJECTED"),
            "automatic_validation": False,
        }
        output[identifier] = decision
        visiting.remove(identifier)
        return decision

    for identifier in sorted(p_values):
        resolve(identifier)
    return output


def validate_train_test_boundary(
    *,
    train_end: datetime,
    test_start: datetime,
    threshold_learned_from: str,
) -> None:
    if train_end >= test_start:
        raise ValueError("TRAIN_TEST_TEMPORAL_LEAKAGE")
    if threshold_learned_from != "TRAIN_ONLY":
        raise ValueError("DERIVED_THRESHOLD_MUST_BE_TRAIN_ONLY")


def validate_observation_cutoff(
    *,
    observed_at: datetime,
    cutoff_at: datetime,
    source_kind: str,
) -> None:
    if observed_at > cutoff_at:
        raise ValueError(f"OBSERVATION_AFTER_CUTOFF:{source_kind}")
    if source_kind == "ACTUAL_WEATHER_FOR_TARGET_MATCH":
        raise ValueError("ACTUAL_TARGET_WEATHER_CANNOT_REPLACE_CUTOFF_FORECAST")


LEAKAGE_FIELDS = frozenset(
    {
        "home_goals",
        "away_goals",
        "full_time_result",
        "future_odds",
        "actual_weather_for_target_match",
        "post_match_lineup_revision",
        "target_match_events",
    }
)


def leakage_audit(feature_names: Sequence[str]) -> dict[str, object]:
    rejected = sorted(set(feature_names) & LEAKAGE_FIELDS)
    return {
        "tested_features": len(feature_names),
        "rejected_features": rejected,
        "passed": not rejected,
        "policy": "AS_OF_CUTOFF;TRAIN_ONLY_TRANSFORMS;FAIL_CLOSED",
    }


__all__ = [
    "HierarchicalMetrics",
    "LEAKAGE_FIELDS",
    "benjamini_hochberg",
    "binary_brier",
    "binary_log_loss",
    "compare_child_to_parent",
    "hierarchical_gatekeeping",
    "leakage_audit",
    "validate_observation_cutoff",
    "validate_train_test_boundary",
]
