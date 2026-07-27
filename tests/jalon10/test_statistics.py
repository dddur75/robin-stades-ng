from __future__ import annotations

from collections.abc import Sequence

import pytest

from robin.patterns.statistics import (
    assess_support,
    benjamini_hochberg,
    clustered_positive_mean_p_value,
    detect_perfect_performance,
    flat_stake_metrics,
    grouped_bootstrap_mean,
    permutation_test,
    shuffle_labels,
    walk_forward_splits,
)


def test_grouped_bootstrap_is_deterministic_and_preserves_groups() -> None:
    values = [1.0, 3.0, -1.0, 5.0, 2.0]
    groups = ["day-a", "day-a", "day-b", "day-c", "day-c"]
    first = grouped_bootstrap_mean(values, groups, iterations=1_000, seed=77)
    second = grouped_bootstrap_mean(values, groups, iterations=1_000, seed=77)

    assert first == second
    assert first.estimate == pytest.approx(2.0)
    assert first.groups == 3
    assert first.lower <= first.estimate <= first.upper


def test_grouped_bootstrap_rejects_cosmetic_or_ungrouped_runs() -> None:
    with pytest.raises(ValueError, match="ITERATIONS_TOO_LOW"):
        grouped_bootstrap_mean([1.0, 2.0], ["a", "b"], iterations=100)
    with pytest.raises(ValueError, match="MULTIPLE_GROUPS"):
        grouped_bootstrap_mean([1.0, 2.0], ["same", "same"], iterations=1_000)


def test_benjamini_hochberg_returns_monotone_q_values_in_original_order() -> None:
    result = benjamini_hochberg([0.01, 0.04, 0.03, 0.20], alpha=0.05)

    assert result.hypotheses == 4
    assert result.q_values == pytest.approx(
        (0.04, 0.0533333333, 0.0533333333, 0.20)
    )
    assert result.rejected == (True, False, False, False)


def test_benjamini_hochberg_handles_ties_and_rejects_invalid_p_values() -> None:
    tied = benjamini_hochberg([0.01, 0.01, 0.9])
    assert tied.q_values[0] == tied.q_values[1]
    with pytest.raises(ValueError, match="INVALID_P_VALUE"):
        benjamini_hochberg([0.1, float("nan")])


def test_benjamini_hochberg_q_values_are_monotone_in_p_value_order() -> None:
    p_values = [0.20, 0.001, 0.08, 0.04, 0.01, 0.50]
    result = benjamini_hochberg(p_values)
    ordered = sorted(
        zip(p_values, result.q_values, strict=True),
        key=lambda pair: pair[0],
    )

    assert all(
        left[1] <= right[1]
        for left, right in zip(ordered[:-1], ordered[1:], strict=True)
    )


def test_benjamini_hochberg_700_tests_with_minimum_near_0006_rejects_none() -> None:
    result = benjamini_hochberg([0.006276023299606921] + [1.0] * 699)

    assert result.hypotheses == 700
    assert min(result.q_values) == 1.0
    assert sum(result.rejected) == 0


def test_benjamini_hochberg_700_tests_rejects_an_extreme_p_value() -> None:
    result = benjamini_hochberg([1e-8] + [1.0] * 699)

    assert result.q_values[0] == pytest.approx(7e-6)
    assert result.rejected[0] is True
    assert sum(result.rejected) == 1


def test_clustered_positive_mean_p_value_uses_cr1_clusters() -> None:
    group_returns = [1.0] * 12 + [-1.0] * 8
    values = [
        value
        for group_return in group_returns
        for value in [group_return] * 5
    ]
    groups = [
        f"day-{group_index}"
        for group_index in range(len(group_returns))
        for _ in range(5)
    ]

    result = clustered_positive_mean_p_value(values, groups)

    assert result == pytest.approx(0.1867983187282179)
    assert result > 0.05


def test_clustered_positive_mean_p_value_is_invariant_to_cluster_replication() -> None:
    group_returns = [1.0] * 12 + [-1.0] * 8
    base_groups = [f"day-{index}" for index in range(len(group_returns))]
    replicated_values = [
        value
        for group_return in group_returns
        for value in [group_return] * 5
    ]
    replicated_groups = [
        group
        for group in base_groups
        for _ in range(5)
    ]

    base = clustered_positive_mean_p_value(group_returns, base_groups)
    replicated = clustered_positive_mean_p_value(
        replicated_values,
        replicated_groups,
    )
    reversed_order = clustered_positive_mean_p_value(
        list(reversed(replicated_values)),
        list(reversed(replicated_groups)),
    )

    assert replicated == pytest.approx(base)
    assert reversed_order == pytest.approx(base)


def test_clustered_positive_mean_p_value_fails_closed() -> None:
    assert clustered_positive_mean_p_value([1.0, -1.0], ["a", "b"]) == 1.0
    assert (
        clustered_positive_mean_p_value(
            [1.0, 1.0, 1.0],
            ["a", "b", "c"],
        )
        == 1.0
    )
    assert (
        clustered_positive_mean_p_value(
            [1e308, -1e308, 1e308, -1e308],
            ["a", "b", "c", "d"],
        )
        == 1.0
    )


def test_clustered_positive_mean_p_value_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="CLUSTERED_P_VALUE_LENGTH_MISMATCH"):
        clustered_positive_mean_p_value([1.0, -1.0, 0.5], ["a", "b"])


def test_walk_forward_training_is_always_strictly_earlier() -> None:
    periods = [2020, 2020, 2021, 2022, 2022, 2023]
    folds = walk_forward_splits(periods, minimum_train_periods=2)

    assert [fold.test_period for fold in folds] == [2022, 2023]
    assert folds[0].train_periods == (2020, 2021)
    assert folds[0].test_indices == (3, 4)
    assert all(max(fold.train_periods) < fold.test_period for fold in folds)
    assert all(
        periods[index] < fold.test_period
        for fold in folds
        for index in fold.train_indices
    )


def test_walk_forward_refuses_an_illusory_single_test_period() -> None:
    with pytest.raises(ValueError, match="INSUFFICIENT_TEMPORAL_PERIODS"):
        walk_forward_splits([2020, 2021], minimum_train_periods=2)


def test_label_shuffle_is_deterministic_and_preserves_the_multiset() -> None:
    labels = tuple(range(10))
    first = shuffle_labels(labels, seed=123)

    assert first == shuffle_labels(labels, seed=123)
    assert first != labels
    assert sorted(first) == list(labels)
    assert labels == tuple(range(10))


def test_permutation_control_is_deterministic_and_never_reports_zero_p() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 9.0, 10.0, 11.0, 12.0]
    labels = [0, 0, 0, 0, 1, 1, 1, 1]

    def difference_in_means(
        sample: Sequence[float],
        sample_labels: Sequence[int],
    ) -> float:
        left = [
            value
            for value, label in zip(sample, sample_labels, strict=True)
            if label == 0
        ]
        right = [
            value
            for value, label in zip(sample, sample_labels, strict=True)
            if label == 1
        ]
        return sum(right) / len(right) - sum(left) / len(left)

    first = permutation_test(
        values,
        labels,
        difference_in_means,
        permutations=500,
        seed=404,
    )
    second = permutation_test(
        values,
        labels,
        difference_in_means,
        permutations=500,
        seed=404,
    )

    assert first == second
    assert 0.0 < first.p_value < 0.05
    assert first.observed_statistic == pytest.approx(8.0)


def test_flat_stake_metrics_use_observed_odds_and_chronological_drawdown() -> None:
    metrics = flat_stake_metrics(
        [2.0, 3.0, 2.0, 2.0],
        [True, False, False, None],
        starting_bankroll_units=100.0,
    )

    assert metrics.bets == 4
    assert metrics.settled_bets == 3
    assert (metrics.wins, metrics.losses, metrics.voids) == (1, 2, 1)
    assert metrics.profit_units == pytest.approx(-1.0)
    assert metrics.roi == pytest.approx(-0.25)
    assert metrics.hit_rate == pytest.approx(1.0 / 3.0)
    assert metrics.average_odds == pytest.approx(2.25)
    assert metrics.median_odds == pytest.approx(2.0)
    assert metrics.max_drawdown_units == pytest.approx(2.0)
    assert metrics.max_losing_streak == 2
    assert metrics.profit_factor == pytest.approx(0.5)
    assert metrics.ending_bankroll_units == pytest.approx(99.0)


def test_flat_stake_metrics_reject_missing_or_invented_prices() -> None:
    with pytest.raises(ValueError, match="INVALID_OBSERVED_ODDS"):
        flat_stake_metrics([1.0], [True])
    with pytest.raises(ValueError, match="LENGTH_MISMATCH"):
        flat_stake_metrics([2.0], [True, False])


def test_support_gate_is_independent_from_performance() -> None:
    insufficient = assess_support(
        4,
        ["2024", "2024", "2025", "2025"],
        minimum_observations=10,
        minimum_groups=3,
    )
    sufficient = assess_support(
        4,
        ["a", "b", "c", "d"],
        minimum_observations=4,
        minimum_groups=3,
    )

    assert insufficient.status == "INSUFFICIENT_SUPPORT"
    assert insufficient.reasons == (
        "OBSERVATIONS_BELOW_MINIMUM",
        "GROUPS_BELOW_MINIMUM",
    )
    assert sufficient.status == "SUFFICIENT_SUPPORT"
    assert sufficient.reasons == ()


def test_perfect_performance_is_quarantined_for_red_team_review() -> None:
    perfect = flat_stake_metrics([2.0] * 12, [True] * 12)
    ordinary = flat_stake_metrics(
        [2.0, 2.0, 2.0, 2.0],
        [True, False, True, False],
    )

    perfect_check = detect_perfect_performance(perfect)
    ordinary_check = detect_perfect_performance(ordinary)
    assert perfect_check.suspicious is True
    assert perfect_check.status == "SUSPICIOUS_PERFECT_PERFORMANCE"
    assert "PERFECT_HIT_RATE" in perfect_check.reasons
    assert ordinary_check.suspicious is False
    assert ordinary_check.status == "PERFORMANCE_NOT_PERFECT"
