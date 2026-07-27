from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from robin.deep_football.models import (
    devig_1x2,
    flat_stake_roi,
    paired_score,
)
from robin.deep_football.statistics import (
    concentration_report,
    family_and_global_bh,
    impossible_outcome_control,
    leave_one_group_out_direction,
    strict_cluster_p_value,
)
from robin.patterns.statistics import permutation_test

KICKOFF = datetime(2026, 7, 27, 18, tzinfo=UTC).isoformat()


def _prediction(
    fixture_id: str,
    probabilities: tuple[float, float, float],
    *,
    outcome: str = "HOME",
) -> dict[str, object]:
    return {
        "competition": "Ligue 1",
        "fixture_id": fixture_id,
        "kickoff_at": KICKOFF,
        "research_mode": "PRE_LINEUP",
        "feature_cutoff": "2026-07-27T17:00:00+00:00",
        "market_source": "FOOTBALL_DATA",
        "market_record_hash": "a" * 64,
        "p_home": probabilities[0],
        "p_draw": probabilities[1],
        "p_away": probabilities[2],
        "outcome": outcome,
    }


def _difference_in_means(
    values: Sequence[float],
    labels: Sequence[int],
) -> float:
    positive = [value for value, label in zip(values, labels, strict=True) if label]
    negative = [
        value
        for value, label in zip(values, labels, strict=True)
        if not label
    ]
    return statistics.fmean(positive) - statistics.fmean(negative)


def test_devigged_market_probabilities_are_valid_and_sum_to_one() -> None:
    probabilities = devig_1x2(2.0, 3.5, 4.0)
    assert sum(probabilities) == pytest.approx(1.0)
    assert all(0.0 < value < 1.0 for value in probabilities)
    assert probabilities[0] > probabilities[1] > probabilities[2]


@pytest.mark.parametrize(
    "odds",
    [
        (1.0, 3.0, 4.0),
        (2.0, math.inf, 4.0),
        (2.0, 3.0, math.nan),
    ],
)
def test_devig_rejects_invalid_odds(
    odds: tuple[float, float, float],
) -> None:
    with pytest.raises(ValueError, match="INVALID_1X2_ODDS"):
        devig_1x2(*odds)


def test_paired_score_reports_incremental_log_loss_and_brier() -> None:
    reference = [
        _prediction("fixture-1", (0.40, 0.30, 0.30)),
        _prediction("fixture-2", (0.30, 0.30, 0.40), outcome="AWAY"),
    ]
    challenger = [
        _prediction("fixture-2", (0.15, 0.15, 0.70), outcome="AWAY"),
        _prediction("fixture-1", (0.70, 0.20, 0.10)),
    ]
    score = paired_score(reference, challenger)

    assert score.matches == 2
    assert score.delta_log_loss < 0.0
    assert score.delta_brier < 0.0
    assert score.challenger_log_loss < score.reference_log_loss
    assert score.challenger_brier < score.reference_brier


def test_paired_scoring_rejects_outcome_or_probability_corruption() -> None:
    reference = [_prediction("fixture-1", (0.40, 0.30, 0.30))]
    with pytest.raises(ValueError, match="PAIRED_OUTCOME_MISMATCH"):
        paired_score(
            reference,
            [_prediction("fixture-1", (0.40, 0.30, 0.30), outcome="AWAY")],
        )
    with pytest.raises(ValueError, match="INVALID_PROBABILITY_VECTOR"):
        paired_score(
            reference,
            [_prediction("fixture-1", (0.80, 0.30, -0.10))],
        )
    with pytest.raises(ValueError, match="PAIRED_SAMPLE_EMPTY"):
        paired_score([], [])


def test_flat_stake_roi_uses_only_observed_settled_prices() -> None:
    result = flat_stake_roi(
        [2.0, 3.0, None, 1.8],
        [True, False, True, None],
    )
    assert result == {
        "bets": 2,
        "profit_units": 0.0,
        "roi": 0.0,
    }
    assert flat_stake_roi([None], [None]) == {
        "bets": 0,
        "profit_units": 0.0,
        "roi": 0.0,
    }


def test_flat_stake_roi_rejects_simulated_or_misaligned_prices() -> None:
    with pytest.raises(ValueError, match="ROI_LENGTH_MISMATCH"):
        flat_stake_roi([2.0], [True, False])
    with pytest.raises(ValueError, match="ROI_REQUIRES_OBSERVED_VALID_ODDS"):
        flat_stake_roi([1.0], [True])


def test_bh_is_applied_per_family_and_globally_with_blocked_tests_retained() -> None:
    correction = family_and_global_bh(
        [
            {
                "hypothesis_id": "H11-001",
                "family": "ABSENCE",
                "eligible": True,
                "p_value": 0.001,
            },
            {
                "hypothesis_id": "H11-002",
                "family": "FORMATION",
                "eligible": True,
                "p_value": 0.02,
            },
            {
                "hypothesis_id": "H11-003",
                "family": "FORMATION",
                "eligible": False,
                "p_value": None,
            },
        ]
    )

    assert correction.ordered_hypotheses == (
        "H11-001",
        "H11-002",
        "H11-003",
    )
    assert set(correction.family_results) == {"ABSENCE", "FORMATION"}
    assert correction.family_q_values["H11-003"] == 1.0
    assert correction.global_q_values["H11-003"] == 1.0
    assert correction.global_result.hypotheses == 3
    assert correction.global_result.rejected == (True, True, False)


def test_bh_rejects_non_finite_or_out_of_range_p_values() -> None:
    with pytest.raises(ValueError, match="INVALID_P_VALUE"):
        family_and_global_bh(
            [
                {
                    "hypothesis_id": "H11-001",
                    "family": "ABSENCE",
                    "eligible": True,
                    "p_value": 1.1,
                }
            ]
        )


def test_cluster_inference_fails_closed_below_preregistered_cluster_count() -> None:
    values = [0.1] * 29
    groups = [f"week-{index}" for index in range(29)]
    assert strict_cluster_p_value(values, groups, minimum_clusters=30) == 1.0


def test_cluster_inference_is_deterministic_with_enough_clusters() -> None:
    values = [0.5 + (index % 5) * 0.1 for index in range(40)]
    groups = [f"week-{index}" for index in range(40)]
    first = strict_cluster_p_value(values, groups, minimum_clusters=30)
    second = strict_cluster_p_value(values, groups, minimum_clusters=30)
    assert first == second
    assert 0.0 <= first <= 1.0


def test_cluster_inference_rejects_misalignment_and_missing_keys() -> None:
    with pytest.raises(ValueError, match="CLUSTER_LENGTH_MISMATCH"):
        strict_cluster_p_value([1.0], ["a", "b"])
    with pytest.raises(ValueError, match="CLUSTER_KEY_MISSING"):
        strict_cluster_p_value([1.0], [""])


def test_leave_one_team_out_requires_direction_in_every_exclusion() -> None:
    stable = leave_one_group_out_direction(
        [1.0, 1.5, 0.5],
        ["A", "B", "C"],
    )
    fragile = leave_one_group_out_direction(
        [10.0, -1.0, -1.0],
        ["A", "B", "C"],
    )
    assert stable["direction_preserved"] is True
    assert stable["groups"] == 3
    assert fragile["direction_preserved"] is False
    assert fragile["estimates"]["A"] == -1.0


def test_leave_one_team_out_rejects_empty_or_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="LEAVE_ONE_GROUP_INPUT_INVALID"):
        leave_one_group_out_direction([], [])
    with pytest.raises(ValueError, match="LEAVE_ONE_GROUP_INPUT_INVALID"):
        leave_one_group_out_direction([1.0], ["A", "B"])


def test_concentration_reports_team_season_league_and_match_dominance() -> None:
    report = concentration_report(
        [10.0, 1.0, 1.0, -2.0],
        ["A", "B", "C", "D"],
        ["2024", "2024", "2025", "2025"],
        ["L1", "L1", "PL", "PL"],
    )
    assert report["positive_profit_units"] == 12.0
    assert report["top_team_share"] == pytest.approx(10 / 12)
    assert report["top_three_team_share"] == 1.0
    assert report["top_season_share"] == pytest.approx(11 / 12)
    assert report["top_league_share"] == pytest.approx(11 / 12)
    assert report["top_ten_match_share"] == 1.0


def test_concentration_rejects_misaligned_dimensions() -> None:
    with pytest.raises(ValueError, match="CONCENTRATION_LENGTH_MISMATCH"):
        concentration_report([1.0], ["A"], ["2025"], ["L1", "PL"])


def test_permutation_control_is_deterministic_and_finite_sample_corrected() -> None:
    values = [float(index) for index in range(20)]
    labels = [0] * 10 + [1] * 10
    first = permutation_test(
        values,
        labels,
        _difference_in_means,
        permutations=100,
        seed=11,
    )
    replay = permutation_test(
        values,
        labels,
        _difference_in_means,
        permutations=100,
        seed=11,
    )
    assert first == replay
    assert first.p_value >= 1 / 101
    assert first.permutations == 100
    assert first.observed_statistic > 0.0


def test_permutation_control_rejects_an_unpermutable_label_vector() -> None:
    with pytest.raises(ValueError, match="LABELS_NOT_PERMUTABLE"):
        permutation_test(
            [1.0, 2.0],
            [1, 1],
            _difference_in_means,
            permutations=100,
        )


def test_impossible_condition_control_evaluates_the_paired_sample() -> None:
    rows = [
        _prediction("fixture-1", (0.50, 0.30, 0.20)),
        _prediction(
            "fixture-2",
            (0.20, 0.30, 0.50),
            outcome="AWAY",
        ),
    ]
    assert impossible_outcome_control(rows) == {
        "status": "EXECUTED_ZERO_SUPPORT_NO_PROMOTION",
        "support": 0,
        "rows_examined": 2,
        "predicate": "OUTCOME_IS_HOME_AND_AWAY",
        "promotion_eligible": False,
    }
