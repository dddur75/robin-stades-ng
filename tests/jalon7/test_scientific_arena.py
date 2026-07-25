from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from robin.historical.scientific_arena import (
    BOOTSTRAP_ITERATIONS,
    CALIBRATION_METHODS,
    OOS_GOVERNANCE,
    ablation_registry,
    apply_selected_calibration,
    arena_cache_key,
    external_validation_protocol,
    feature_stability_audit,
    freeze_jalon6,
    grouped_bootstrap,
    paired_model_comparison,
    random_lineup_control,
    score_distribution,
    score_market_probabilities,
    select_cross_fitted_calibration,
    stable_hash,
    storage_guard,
    strategy_lab_v2_protocol,
    temperature_calibrate,
    validate_exact_pairing,
)


def prediction(
    fixture_id: int,
    probabilities: tuple[float, float, float],
    *,
    season: int = 2024,
    target: int = 0,
    policy: str = "PRE_MATCH_CUTOFF",
) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "season": season,
        "target": target,
        "kickoff_at": f"{season}-03-{fixture_id:02d}T20:00:00+00:00",
        "probability_home": probabilities[0],
        "probability_draw": probabilities[1],
        "probability_away": probabilities[2],
        "market_snapshot": "CLOSING",
        "temporal_policy": policy,
    }


def test_oos_governance_keeps_exposed_and_live_out_of_selection() -> None:
    periods = OOS_GOVERNANCE["periods"]
    assert isinstance(periods, dict)
    assert periods["DISCOVERY"] == [2020, 2021, 2022]
    assert periods["VALIDATION"] == [2023]
    assert periods["EXPOSED_HISTORICAL_OOS"] == [2024, 2025]
    assert periods["LIVE_PROSPECTIVE"] == [2026, 2027]


def test_external_protocol_is_preregistered_and_hashed() -> None:
    protocol = external_validation_protocol()
    assert protocol["protocol_id"] == "EXTERNAL_VALIDATION_PROTOCOL_V1"
    assert protocol["registered_before_results"] is True
    assert protocol["bootstrap_iterations"] >= 2_000
    assert len(str(protocol["protocol_hash"])) == 64


def test_exact_pairing_rejects_temporal_policy_mismatch() -> None:
    left = [prediction(1, (0.6, 0.2, 0.2))]
    right = [prediction(1, (0.5, 0.3, 0.2), policy="POST_LINEUP")]
    with pytest.raises(ValueError, match="PAIRED_PROTOCOL_MISMATCH"):
        validate_exact_pairing(left, right)


def test_exact_pairing_uses_only_shared_fixtures() -> None:
    left = [
        prediction(1, (0.6, 0.2, 0.2)),
        prediction(2, (0.6, 0.2, 0.2)),
    ]
    right = [prediction(1, (0.5, 0.3, 0.2))]
    assert len(validate_exact_pairing(left, right)) == 1


def test_grouped_bootstrap_is_deterministic_and_large() -> None:
    deltas = np.asarray([-0.1, -0.2, 0.05, -0.3])
    groups = ["2024-W01", "2024-W01", "2024-W02", "2025-W01"]
    first = grouped_bootstrap(deltas, groups, iterations=2_000)
    second = grouped_bootstrap(deltas, groups, iterations=2_000)
    assert first == second
    assert first["groups"] == 3
    assert len(first["ci90"]) == 2
    assert len(first["ci95"]) == 2


def test_grouped_bootstrap_refuses_small_cosmetic_run() -> None:
    with pytest.raises(ValueError, match="TOO_LOW"):
        grouped_bootstrap(np.asarray([0.1]), ["one"], iterations=100)


def test_paired_comparison_reports_superiority_probability() -> None:
    challenger = [prediction(index, (0.8, 0.1, 0.1)) for index in range(1, 13)]
    reference = [prediction(index, (0.4, 0.3, 0.3)) for index in range(1, 13)]
    result = paired_model_comparison(
        challenger,
        reference,
        comparison_id="A_VS_B",
        iterations=2_000,
    )
    assert result["paired_fixtures"] == 12
    assert result["paired_log_loss_delta"] < 0
    assert result["uncertainty"]["probability_challenger_better"] == 1.0


def test_temperature_scaling_preserves_probability_simplex() -> None:
    values = np.asarray([[0.8, 0.1, 0.1], [0.2, 0.3, 0.5]])
    labels = np.asarray([0, 2])
    calibrated, temperature = temperature_calibrate(values, labels, values)
    assert 0.5 <= temperature <= 3.0
    np.testing.assert_allclose(calibrated.sum(axis=1), np.ones(2))


def test_cross_fit_calibration_exposes_all_methods_and_guard() -> None:
    probabilities = np.asarray(
        [
            [0.7, 0.2, 0.1],
            [0.2, 0.6, 0.2],
            [0.6, 0.2, 0.2],
            [0.2, 0.3, 0.5],
            [0.7, 0.2, 0.1],
            [0.2, 0.6, 0.2],
        ]
    )
    labels = np.asarray([0, 1, 0, 2, 0, 1])
    selection = select_cross_fitted_calibration(
        probabilities, labels, [2021, 2021, 2022, 2022, 2023, 2023]
    )
    assert set(selection["cross_fitted_log_loss"]) == set(CALIBRATION_METHODS)
    assert "STRICTLY_EARLIER" in str(selection["leakage_guard"])


def test_apply_calibration_never_uses_evaluation_labels_for_selection() -> None:
    development = [
        prediction(1, (0.7, 0.2, 0.1), season=2021),
        prediction(2, (0.2, 0.6, 0.2), season=2021, target=1),
        prediction(3, (0.6, 0.3, 0.1), season=2022),
        prediction(4, (0.1, 0.2, 0.7), season=2022, target=2),
    ]
    evaluation = [prediction(5, (0.5, 0.3, 0.2), season=2024)]
    output, audit = apply_selected_calibration(development, evaluation)
    assert len(output) == 1
    assert audit["evaluation_labels_used_for_selection"] == 0


@pytest.mark.parametrize("method", ["POISSON", "DIXON_COLES"])
def test_score_models_produce_normalized_distribution(method: str) -> None:
    matrix = score_distribution(1.5, 1.1, method=method)
    assert matrix.sum() == pytest.approx(1.0)
    markets = score_market_probabilities(matrix)
    assert (
        markets["probability_home"] + markets["probability_draw"] + markets["probability_away"]
    ) == pytest.approx(1.0)
    assert markets["probability_over_25"] + markets["probability_under_25"] == pytest.approx(1.0)
    assert markets["probability_btts_yes"] + markets["probability_btts_no"] == pytest.approx(1.0)


def test_dixon_coles_changes_low_scores() -> None:
    poisson = score_distribution(1.4, 1.0, method="POISSON")
    dixon_coles = score_distribution(1.4, 1.0, method="DIXON_COLES")
    assert dixon_coles[0, 0] != pytest.approx(poisson[0, 0])


def test_random_lineup_control_is_reproducible() -> None:
    rows = [
        {
            "fixture_id": index,
            "target_home_goals": 1,
            "target_away_goals": 0,
            "home_expected_starting_xi_strength": index,
        }
        for index in range(5)
    ]
    assert random_lineup_control(rows) == random_lineup_control(rows)


def test_ablation_registry_removes_semantic_groups() -> None:
    registry = ablation_registry()
    assert {item["ablation_id"] for item in registry} == {
        "WITHOUT_TEAM_FORM",
        "WITHOUT_PLAYER_PRE_LINEUP",
        "WITHOUT_CONFIRMED_LINEUP",
        "WITHOUT_MARKET",
    }


def test_feature_stability_is_diagnostic_and_never_promotional() -> None:
    rows = [
        {
            "season": season,
            "target_home_goals": 1 if index % 2 else 0,
            "target_away_goals": 0 if index % 2 else 1,
            "elo_difference": float(index),
        }
        for season in (2020, 2021)
        for index in range(6)
    ]
    audit = feature_stability_audit(rows, features=("elo_difference",))
    assert audit[0]["importance_proxy"].endswith("DIAGNOSTIC_ONLY")
    assert audit[0]["promotion_use"] == "FORBIDDEN"
    assert set(audit[0]["correlation_by_season"]) == {"2020", "2021"}


def test_strategy_protocol_is_bounded_and_locked() -> None:
    protocol = strategy_lab_v2_protocol()
    assert protocol["protocol_id"] == "STRATEGY_LAB_V2_PREREGISTERED"
    assert protocol["production_status"] == "PRODUCTION_LOCKED"
    assert max(protocol["edge_thresholds"]) <= 0.07
    assert protocol["maximum_stake_units"] == 1.0


@pytest.mark.parametrize(
    ("size", "expected", "can_write"),
    [
        (200_000_000, "SAFE", True),
        (750_000_000, "WARNING", True),
        (900_000_000, "PAUSED", False),
    ],
)
def test_storage_guard(size: int, expected: str, can_write: bool) -> None:
    result = storage_guard(size)
    assert result["status"] == expected
    assert result["can_write"] is can_write


def test_cache_key_changes_with_dataset_or_revision() -> None:
    manifest = [{"dataset_name": "team", "sha256": "abc"}]
    first = arena_cache_key(manifest, code_revision="one")
    assert first == arena_cache_key(manifest, code_revision="one")
    assert first != arena_cache_key(manifest, code_revision="two")


def test_freeze_is_immutable(tmp_path: Path) -> None:
    state = tmp_path / "state"
    (state / "models").mkdir(parents=True)
    (state / "models" / "model.json").write_text('{"model":"v1"}', encoding="utf-8")
    output = state / "arena" / "freeze.json"
    first = freeze_jalon6(state, source_commit="abc", output_path=output)
    assert first["status"] == "JALON6_BASELINE_FROZEN"
    assert json.loads(output.read_text(encoding="utf-8"))["baseline_hash"] == first["baseline_hash"]
    (state / "models" / "model.json").write_text('{"model":"changed"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="IMMUTABLE"):
        freeze_jalon6(state, source_commit="abc", output_path=output)


def test_stable_hash_ignores_mapping_order() -> None:
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})


def test_default_bootstrap_is_thousands() -> None:
    assert BOOTSTRAP_ITERATIONS >= 2_000
