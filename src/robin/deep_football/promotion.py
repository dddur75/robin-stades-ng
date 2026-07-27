"""Seventeen conjunctive promotion gates; missing evidence always fails."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from robin.deep_football.contracts import PatternStatus

PROMOTION_CRITERIA = (
    "data_gate_ready",
    "no_leakage",
    "preregistered_support",
    "three_eligible_periods",
    "stable_direction",
    "positive_last_fold",
    "family_bh_passed",
    "global_control_passed",
    "permutation_passed",
    "bootstrap_lower_coherent",
    "concentration_passed",
    "incremental_score_vs_market_positive",
    "historical_roi_not_artificial",
    "rule_interpretable",
    "live_information_available",
    "live_market_exact_observed_at",
    "decision_reproducible_before_kickoff",
)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promoted: bool
    status: PatternStatus
    failed_criteria: tuple[str, ...]


def evaluate_promotion(
    evidence: Mapping[str, object],
) -> PromotionDecision:
    failed = tuple(
        criterion
        for criterion in PROMOTION_CRITERIA
        if evidence.get(criterion) is not True
    )
    live_only_gates = {
        "live_market_exact_observed_at",
        "decision_reproducible_before_kickoff",
    }
    historical_science_passed = not (set(failed) - live_only_gates)
    return PromotionDecision(
        promoted=not failed,
        status=(
            PatternStatus.LIVE_SHADOW_CANDIDATE
            if not failed
            else PatternStatus.PROSPECTIVE_WATCHLIST
            if historical_science_passed
            else PatternStatus.REJECTED
        ),
        failed_criteria=failed,
    )
