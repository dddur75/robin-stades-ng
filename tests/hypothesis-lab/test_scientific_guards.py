from __future__ import annotations

import copy
import math
import statistics
from typing import Any

import pytest


def _rehash(document: dict[str, Any], builder: dict[str, Any]) -> None:
    document.pop("content_sha256", None)
    document["content_sha256"] = builder["sha256_json"](document)


def _rehash_experiment(experiment: dict[str, Any], builder: dict[str, Any]) -> None:
    experiment.pop("protocol_hash", None)
    experiment["protocol_hash"] = builder["sha256_json"](experiment)


def _rehash_power_design(power_design: dict[str, Any], builder: dict[str, Any]) -> None:
    power_design.pop("design_contract_hash", None)
    power_design["design_contract_hash"] = builder["sha256_json"](power_design)


def test_de_vig_is_explicit_and_never_aggregated(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    allowed = {
        (
            "PROPORTIONAL",
            "PROPORTIONAL_COMPLETE_MARKET_V1",
            "265d91ae91f793523180d617a3cbcd90ee95ac483d7fdbfcaa3547868e076684",
        ),
        (
            "SHIN",
            "LEGACY_SHIN_VAGUE1_V1",
            "3ff94a3daf36b0995717522ed3605bf0754d799705df028414043587b7375367",
        ),
    }
    for hypothesis in hypotheses:
        protocol = hypothesis["devig_protocol"]
        assert protocol["authority_status"] == "DEVIG_PROTOCOL_CONFLICT"
        assert protocol["branch_results_aggregated"] is False
        assert len(protocol["branches"]) == 2
        declared_markets = set(hypothesis["market"])
        assert all(
            {component["market"] for component in branch["components"]} == declared_markets
            for branch in protocol["branches"]
        )
        components = [
            component
            for branch in protocol["branches"]
            for component in branch["components"]
            if component["market"] == "1X2"
        ]
        assert {
            (
                component["devig_method"],
                component["devig_version"],
                component["devig_definition_hash"],
            )
            for component in components
        } == allowed


def test_score_recomputes_and_excludes_historical_roi(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    scorecard = artifacts["hypothesis-priority-scorecard-v1.json"]
    weights = {
        "mechanistic_plausibility": 15,
        "data_availability": 15,
        "point_in_time_provability": 20,
        "statistical_power": 10,
        "originality": 10,
        "cross_league_stability": 10,
        "falsifiability": 10,
        "compute_cost": 5,
        "strategic_value": 5,
    }
    for entry in scorecard["entries"]:
        assert entry["total"] == sum(entry["components"].values())
        assert all(
            0 <= entry["components"][key] <= maximum for key, maximum in weights.items()
        )
        assert entry["historical_roi_used"] is False


def test_score_rank_validator_is_not_hard_coded_to_112(
    builder: dict[str, Any],
) -> None:
    entries = [{"score_rank": index} for index in range(1, 112)]
    builder["_validate_score_rank_sequence"](entries, 111)
    entries[-1]["score_rank"] = 112
    with pytest.raises(ValueError, match="score ranks are not contiguous"):
        builder["_validate_score_rank_sequence"](entries, 111)


def test_point_in_time_contract_and_data_blockers(
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    blocked = []
    for hypothesis in hypotheses:
        point_in_time = hypothesis["point_in_time"]
        expected_cutoff = builder["_predictor_cutoff_for"](
            hypothesis["concept_key"]
        )
        assert point_in_time["event_at"]["availability_proof"] is False
        assert point_in_time["available_at"]["required"] is True
        assert point_in_time["cutoff_at"]["cutoff_id"] == expected_cutoff["cutoff_id"]
        assert point_in_time["cutoff_at"]["legacy_alias"] == expected_cutoff[
            "legacy_alias"
        ]
        assert point_in_time["cutoff_at"]["rule"] == expected_cutoff["rule"]
        assert hypothesis["temporal_cutoff"]["cutoff_id"] == expected_cutoff[
            "cutoff_id"
        ]
        assert hypothesis["estimand_signature"]["cutoff_class"] == expected_cutoff[
            "cutoff_class"
        ]
        assert point_in_time["historical_evidence_status"] == "POINT_IN_TIME_NOT_PROVEN"
        labels = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] == "LABEL"
        ]
        predictors = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] in {"FEATURE", "ODDS", "METADATA"}
        ]
        targets = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] == "TARGET"
        ]
        assert len(labels) == 1
        assert labels[0]["eligible_as_pre_cutoff_predictor"] is False
        assert labels[0]["result_available_at_required"] is True
        assert labels[0]["settlement_receipt_required"] is True
        assert all(row["analysis_usage"] == "PRE_CUTOFF_PREDICTOR" for row in predictors)
        assert all(row["eligible_as_pre_cutoff_predictor"] is True for row in predictors)
        assert all(row["eligible_as_pre_cutoff_predictor"] is False for row in targets)
        assert all(
            row["temporal_admissibility"]
            == "cutoff_at < available_at <= target_window_end and robin_ingested_at <= target_window_end"
            for row in targets
        )
        if targets:
            target_contract = builder["POST_CUTOFF_TARGETS"][hypothesis["concept_key"]]
            assert len(targets) == 1
            assert targets[0]["analysis_usage"] == "PRIMARY_MODEL_OUTCOME"
            assert labels[0]["analysis_usage"] == "SECONDARY_METRIC_LABEL_ONLY"
            assert point_in_time["post_cutoff_target_receipt_fields_required"] == list(
                builder["TARGET_RECEIPT_FIELDS"]
            )
            assert (
                hypothesis["estimand_signature"]["outcome_construct"]
                == target_contract["outcome_construct"]
            )
            assert hypothesis["primary_metric"] == target_contract["primary_metric"]
            assert "Primary model outcome:" in hypothesis["operational_definition"]["outcome"]
            assert "settled fixture label is separate" in hypothesis[
                "operational_definition"
            ]["outcome"]
            if hypothesis["concept_key"] == "bookmaker_deviation_reversion":
                assert point_in_time["cutoff_at"]["cutoff_id"] == "H24"
                assert point_in_time["post_cutoff_target_admissibility"][
                    "target_window_id"
                ] == "H2"
                assert (
                    hypothesis["estimand_signature"]["target_horizon"]
                    == "POST_CUTOFF_PREMATCH_H2_TARGET_WINDOW"
                )
                assert (
                    hypothesis["estimand_signature"]["outcome_construct"]
                    == "RECEIPT_BACKED_H2_BOOKMAKER_DEVIATION_TARGET"
                )
        else:
            assert labels[0]["analysis_usage"] == "PRIMARY_OR_SECONDARY_SETTLED_OUTCOME"
            assert point_in_time["post_cutoff_target_receipt_fields_required"] == []
        assert {
            "append future row",
            "change future value",
            "delete future row",
            "reorder future rows",
            "receive retroactive correction after cutoff",
        } == set(point_in_time["future_mutation_test"]["mutations"])
        if point_in_time["prospective_observability_status"] == (
            "DATA_NOT_PROSPECTIVELY_OBSERVABLE"
        ):
            blocked.append(hypothesis)
            assert hypothesis["status"]["lifecycle_status"] == "DATA_GATE_BLOCKED"
            assert any(
                dependency["snapshot_resolution"] == "SOURCE_CONTRACT_ABSENT"
                for dependency in hypothesis["data_dependencies"]
            )
    assert len(blocked) == 5
    assert sum(
        dependency["role"] == "TARGET"
        for hypothesis in hypotheses
        for dependency in hypothesis["data_dependencies"]
    ) == 3


def test_negative_controls_cover_all_required_failure_modes(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    plan = artifacts["negative-control-plan-v1.json"]
    categories = {control["category"] for control in plan["controls"]}
    assert {
        "PERMUTED_LABELS",
        "TEMPORALLY_SHIFTED_FEATURE",
        "MECHANISM_FREE_VARIABLE",
        "SYNTHETIC_CALIBRATED_NO_SIGNAL_MARKET",
    } <= categories
    assert all(control["execution_status"] == "NOT_RUN" for control in plan["controls"])
    assert plan["factory_wide_control_ids"] == [
        "RDS-NC-V1-005",
        "RDS-NC-V1-006",
        "RDS-NC-V1-008",
    ]
    for control in plan["controls"]:
        if control["control_type"] == "DETERMINISTIC_GUARD":
            assert control["replicate_seeds"] == []
            assert (
                control["frozen_alarm_rule"]
                == "ANY_SINGLE_GUARD_VIOLATION_STOPS_THE_FACTORY"
            )
        else:
            assert len(control["replicate_seeds"]) == 20
            assert len(set(control["replicate_seeds"])) == 20
            assert (
                control["frozen_alarm_rule"]
                == "AT_LEAST_4_OF_20_SEEDED_REPLICATES_CROSS_Q_AND_EFFECT_FLOOR"
            )


def test_falsification_bounds_are_logically_directional(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    positive = next(
        row
        for row in hypotheses
        if row["falsification_contract"]["claim_type"] == "SIGNED_MINIMUM"
        and row["falsification_contract"]["orientation"] == "POSITIVE"
    )["falsification_contract"]
    negative = next(
        row
        for row in hypotheses
        if row["falsification_contract"]["claim_type"] == "SIGNED_MINIMUM"
        and row["falsification_contract"]["orientation"] == "NEGATIVE"
    )["falsification_contract"]
    unsigned = next(
        row
        for row in hypotheses
        if row["falsification_contract"]["claim_type"] == "ABSOLUTE_MINIMUM"
    )["falsification_contract"]

    positive_delta = positive["minimum_effect"]
    assert builder["classify_interval"](positive, 0.30, 0.40, 0.01) == "SUPPORTED"
    assert (
        builder["classify_interval"](
            positive, -0.10, positive_delta - 0.01, 0.01
        )
        == "FALSIFIED"
    )
    assert (
        builder["classify_interval"](
            positive, positive_delta - 0.01, positive_delta + 0.01, 0.01
        )
        == "INCONCLUSIVE"
    )
    assert (
        builder["classify_interval"](
            positive, positive_delta, positive_delta + 0.05, 0.01
        )
        == "SUPPORTED"
    )
    assert (
        builder["classify_interval"](
            positive, positive_delta - 0.05, positive_delta, 0.01
        )
        == "INCONCLUSIVE"
    )
    negative_delta = negative["minimum_effect"]
    assert (
        builder["classify_interval"](
            negative, -negative_delta - 0.10, -negative_delta - 0.01, 0.01
        )
        == "SUPPORTED"
    )
    unsigned_delta = unsigned["minimum_effect"]
    assert (
        builder["classify_interval"](
            unsigned, -unsigned_delta / 2, unsigned_delta / 2, 0.01
        )
        == "FALSIFIED"
    )
    assert (
        builder["classify_interval"](
            unsigned, -unsigned_delta * 2, unsigned_delta * 2, 0.01
        )
        == "INCONCLUSIVE"
    )

    for hypothesis in hypotheses:
        contract = hypothesis["falsification_contract"]
        if contract["claim_type"] != "SIGNED_MINIMUM":
            continue
        delta = contract["minimum_effect"]
        opposite = (
            (-2 * delta, -1.5 * delta)
            if contract["orientation"] == "POSITIVE"
            else (1.5 * delta, 2 * delta)
        )
        assert builder["classify_interval"](contract, *opposite, 0.01) == "FALSIFIED"


def test_direction_semantics_are_exhaustively_typed(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    assert sum(
        row["falsification_contract"]["claim_type"] == "SIGNED_MINIMUM"
        for row in hypotheses
    ) == 71
    assert sum(
        row["falsification_contract"]["claim_type"] == "ABSOLUTE_MINIMUM"
        for row in hypotheses
    ) == 41
    for hypothesis in hypotheses:
        direction = hypothesis["expected_effect"]["direction"]
        contract = hypothesis["falsification_contract"]
        if direction in builder["TWO_SIDED_DIRECTION_CODES"]:
            assert (contract["claim_type"], contract["orientation"]) == (
                "ABSOLUTE_MINIMUM",
                "UNSIGNED",
            )
        else:
            assert contract["claim_type"] == "SIGNED_MINIMUM"
            assert contract["orientation"] in {"POSITIVE", "NEGATIVE"}


def test_first_25_models_targets_and_power_designs_are_frozen(
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    report = artifacts["first-25-experiment-protocols-v1.json"]
    for experiment in report["experiments"]:
        model = experiment["operational_definition"]["model"]
        assert model["estimator_family"]
        assert model["error_distribution"]
        assert model["variance_model"]
        assert model["standardization"]
        assert model["outcome_transformation"]
        assert model["power_design_class"]
        assert model["power_design_matrix_class"]
        assert not model["primary_parameter"].startswith("joint_")
        power = experiment["model_specific_power_design"]
        assert power["status"] == "PREDECLARED_MODEL_SPECIFIC_POWER_DESIGN_NOT_RUN"
        assert power["estimated_power"] is None
        assert power["selected_eligible_units"] is None
        assert power["sporting_results_used"] is False
        assert (
            power["formula_test_mapping"]["scalar_primary_contrast"]
            == model["primary_parameter"]
        )
        assert power["formula_test_mapping"]["model_formula"] == model["formula"]
        assert power["simulator"]["version"] == builder["POWER_SIMULATOR_VERSION"]
        assert power["signed_design_alternatives"]
        matrix = power["data_generating_process"]["design_matrix"]
        assert matrix["design_class"] == model["power_design_matrix_class"]
        assert len(matrix["primary_contrast"]["weights"]) == len(matrix["columns"])
        assert any(matrix["primary_contrast"]["weights"])
        assert power["decision_algorithm"]["branch_results_aggregated"] is False
        assert power["candidate_eligible_units"] == sorted(
            power["candidate_eligible_units"]
        )


def test_power_math_and_branch_decision_are_executable(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    assert builder["benjamini_hochberg_q_values"]([0.01, 0.04, 0.03]) == pytest.approx(
        [0.03, 0.04, 0.04]
    )
    assert builder["wilson_lower_bound"](8000, 10000) < 0.80
    assert builder["wilson_lower_bound"](8200, 10000) > 0.80
    latent_seed = builder["derive_power_latent_seed"](202608140001, 1000, 7)
    assert latent_seed == builder["derive_power_latent_seed"](
        202608140001, 1000, 7
    )
    assert builder["derive_power_branch_transform_seed"](
        latent_seed, "DEVIG-PROP"
    ) != builder["derive_power_branch_transform_seed"](
        latent_seed, "DEVIG-SHIN"
    )

    experiment = artifacts["first-25-experiment-protocols-v1.json"]["experiments"][0]
    design = experiment["model_specific_power_design"]
    contract = design["test_mapping"]["classification_contract"]
    delta = contract["minimum_effect"]
    if contract["orientation"] == "NEGATIVE":
        supported_interval = (-3 * delta, -2 * delta)
        opposite_interval = (2 * delta, 3 * delta)
    else:
        supported_interval = (2 * delta, 3 * delta)
        opposite_interval = (-3 * delta, -2 * delta)
    branch_results = [
        {
            "branch_id": branch_id,
            "p_value": 1e-12,
            "ci95_lower_bound": supported_interval[0],
            "ci95_upper_bound": supported_interval[1],
        }
        for branch_id in design["decision_algorithm"]["branch_ids"]
    ]
    family_nulls = [1.0] * (
        design["decision_algorithm"]["family_primary_test_count"] - len(branch_results)
    )
    global_nulls = [1.0] * (
        design["decision_algorithm"]["global_primary_test_count"]
        - design["decision_algorithm"]["family_primary_test_count"]
    )
    assert builder["evaluate_power_replicate"](
        design, branch_results, family_nulls, global_nulls
    )
    branch_results[0]["ci95_lower_bound"] = opposite_interval[0]
    branch_results[0]["ci95_upper_bound"] = opposite_interval[1]
    assert not builder["evaluate_power_replicate"](
        design, branch_results, family_nulls, global_nulls
    )


def test_power_generation_fit_and_full_run_smoke_every_design_class(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    experiments = artifacts["first-25-experiment-protocols-v1.json"]["experiments"]
    representative_by_class: dict[str, dict[str, Any]] = {}
    matrix_classes = set()
    team_fixture_orders = {11, 12, 13, 17, 18, 19, 20, 21, 22}
    for experiment in experiments:
        design = experiment["model_specific_power_design"]
        representative_by_class.setdefault(design["design_method"], experiment)
        alternative = design["signed_design_alternatives"][0]
        matrix = design["data_generating_process"]["design_matrix"]
        matrix_classes.add(matrix["design_class"])
        expansion = matrix["observation_expansion"]
        expected_axes = (
            {"BOOKMAKER": 5}
            if experiment["portfolio_order"] == 6
            else {"TEAM": 2, "HALF": 2}
            if experiment["portfolio_order"] == 18
            else {"TEAM": 2}
            if experiment["portfolio_order"] in team_fixture_orders
            else {"FIXTURE": 1}
        )
        assert expansion["axis_cardinalities"] == expected_axes
        assert expansion["rows_per_fixture"] == math.prod(expected_axes.values())
        assert design["data_generating_process"]["cluster_process"][
            "mean_cluster_size"
        ] == expansion["rows_per_fixture"]
        assert all(
            candidate % expansion["rows_per_fixture"] == 0
            for candidate in design["candidate_eligible_units"]
        )
        assert {
            f"league_season_ls{number}" for number in range(2, 9)
        } <= {column["name"] for column in matrix["columns"]}
        base_smoke_n = max(160, len(matrix["columns"]) * 12)
        smoke_n = (
            math.ceil(base_smoke_n / expansion["rows_per_fixture"])
            * expansion["rows_per_fixture"]
        )
        latent_seed = builder["derive_power_latent_seed"](
            design["master_seed"], smoke_n, 0
        )
        sample = builder["generate_power_sample"](
            design, smoke_n, alternative, latent_seed
        )
        if expansion["rows_per_fixture"] > 1:
            with pytest.raises(ValueError, match="complete fixture clusters"):
                builder["generate_power_sample"](
                    design, smoke_n - 1, alternative, latent_seed
                )
        assert len(sample[0]) == smoke_n
        rows, common_outcomes, cluster_ids = sample
        column_index = {
            column["name"]: position
            for position, column in enumerate(matrix["columns"])
        }
        rows_by_cluster: dict[int, list[list[float]]] = {}
        outcomes_by_cluster: dict[int, list[float]] = {}
        for row, outcome, cluster_id in zip(
            rows, common_outcomes, cluster_ids, strict=True
        ):
            rows_by_cluster.setdefault(cluster_id, []).append(row)
            outcomes_by_cluster.setdefault(cluster_id, []).append(outcome)
        for column_name in matrix["fixture_invariant_columns"]:
            position = column_index[column_name]
            assert all(
                len({row[position] for row in cluster_rows}) == 1
                for cluster_rows in rows_by_cluster.values()
            )
        league_season_columns = {
            column["name"]
            for column in matrix["columns"]
            if column["name"].startswith("league_season_")
        }
        assert league_season_columns <= set(matrix["fixture_invariant_columns"])
        if matrix["within_fixture_columns"]:
            within_positions = [
                column_index[name] for name in matrix["within_fixture_columns"]
            ]
            full_clusters = [
                cluster_rows
                for cluster_rows in rows_by_cluster.values()
                if len(cluster_rows)
                == matrix["observation_expansion"]["rows_per_fixture"]
            ]
            assert full_clusters
            assert all(
                len(
                    {
                        tuple(row[position] for position in within_positions)
                        for row in cluster_rows
                    }
                )
                > 1
                for cluster_rows in full_clusters
            )
        if experiment["portfolio_order"] == 6:
            assert expansion["row_order"] == "BOOKMAKER_WITHIN_FIXTURE"
            postprocessing = design["data_generating_process"][
                "outcome_postprocessing"
            ]
            assert postprocessing["common_outcome_rule"] == "FIXTURE_MEDIAN_ZERO"
            assert postprocessing["branch_outcome_rule"] == "FIXTURE_MEDIAN_ZERO"
            assert all(
                statistics.median(cluster_outcomes)
                == pytest.approx(0.0, abs=1e-12)
                for cluster_outcomes in outcomes_by_cluster.values()
            )
            deviation_latent = next(
                row
                for row in matrix["latent_variables"]
                if row["name"] == "book_deviation_H24_z"
            )
            assert deviation_latent["normalization"] == (
                "ZERO_SUM_ZERO_MEDIAN_UNIT_ROOT_MEAN_SQUARE"
            )
            deviation_position = column_index["book_deviation_H24_z"]
            book_positions = [
                column_index[f"book_b{number}"] for number in range(2, 6)
            ]
            for cluster_rows in rows_by_cluster.values():
                deviations = [row[deviation_position] for row in cluster_rows]
                assert len(cluster_rows) == 5
                assert len(set(deviations)) == 5
                assert statistics.median(deviations) == pytest.approx(0.0, abs=1e-12)
                assert sum(deviations) == pytest.approx(0.0, abs=1e-12)
                assert sum(value * value for value in deviations) / 5 == pytest.approx(
                    1.0, abs=1e-12
                )
                assert len(
                    {
                        tuple(row[position] for position in book_positions)
                        for row in cluster_rows
                    }
                ) == 5
        elif experiment["portfolio_order"] == 18:
            assert expansion["row_order"] == "TEAM_THEN_HALF_WITHIN_FIXTURE"
            venue_position = column_index["venue_home"]
            half_position = column_index["second_half"]
            congested_position = column_index["congested"]
            strength_position = column_index["strength_z"]
            interaction_position = column_index["congested_x_second_half"]
            for cluster_rows in rows_by_cluster.values():
                assert [row[venue_position] for row in cluster_rows] == [1, 1, 0, 0]
                assert [row[half_position] for row in cluster_rows] == [0, 1, 0, 1]
                assert cluster_rows[0][congested_position] == cluster_rows[1][
                    congested_position
                ]
                assert cluster_rows[2][congested_position] == cluster_rows[3][
                    congested_position
                ]
                assert cluster_rows[0][strength_position] == cluster_rows[1][
                    strength_position
                ]
                assert cluster_rows[2][strength_position] == cluster_rows[3][
                    strength_position
                ]
                assert [row[interaction_position] for row in cluster_rows] == [
                    row[congested_position] * row[half_position]
                    for row in cluster_rows
                ]
        elif experiment["portfolio_order"] in team_fixture_orders:
            assert expansion["row_order"] == "TEAM_WITHIN_FIXTURE"
            venue_position = column_index["venue_home"]
            for cluster_rows in rows_by_cluster.values():
                assert [row[venue_position] for row in cluster_rows] == [1, 0]
                if experiment["portfolio_order"] == 17:
                    position = column_index["rest_differential_z"]
                    assert cluster_rows[0][position] == pytest.approx(
                        -cluster_rows[1][position]
                    )
                if experiment["portfolio_order"] == 22:
                    position = column_index["strength_gap_z"]
                    assert cluster_rows[0][position] == pytest.approx(
                        -cluster_rows[1][position]
                    )
        else:
            assert expansion["row_order"] == "FIXTURE_SINGLE_ROW"
        if experiment["portfolio_order"] != 6:
            assert (
                design["data_generating_process"]["outcome_postprocessing"][
                    "common_outcome_rule"
                ]
                == "NONE"
            )
        branch_transform_seeds = {
            branch_id: builder["derive_power_branch_transform_seed"](
                latent_seed, branch_id
            )
            for branch_id in design["decision_algorithm"]["branch_ids"]
        }
        if experiment["portfolio_order"] == 6:
            for branch_seed in branch_transform_seeds.values():
                branch_outcomes = builder["transform_power_branch_outcomes"](
                    design, sample, branch_seed
                )
                branch_by_cluster: dict[int, list[float]] = {}
                for outcome, cluster_id in zip(
                    branch_outcomes, cluster_ids, strict=True
                ):
                    branch_by_cluster.setdefault(cluster_id, []).append(outcome)
                assert all(
                    statistics.median(cluster_outcomes)
                    == pytest.approx(0.0, abs=1e-12)
                    for cluster_outcomes in branch_by_cluster.values()
                )
        branch_results = [
            builder["fit_power_branch"](
                design,
                sample,
                branch_id,
                branch_transform_seeds[branch_id],
            )
            for branch_id in design["decision_algorithm"]["branch_ids"]
        ]
        assert [row["branch_id"] for row in branch_results] == design[
            "decision_algorithm"
        ]["branch_ids"]
        assert all(0 <= row["p_value"] <= 1 for row in branch_results)

    assert matrix_classes == {
        "ADJUSTED_INTERCEPT",
        "AUTOREGRESSIVE_SLOPE_MINUS_ONE",
        "BINARY_MAIN_EFFECT",
        "CATEGORICAL_THREE_LEVEL_CONTRAST",
        "CONTINUOUS_SLOPE",
        "FROZEN_SPLINE_CONTRAST",
        "JOINT_BINARY_INTERACTION",
        "MUTUALLY_EXCLUSIVE_BINARY_CONTRAST",
        "PAIRED_DIFFERENCE_INTERCEPT",
    }
    assert set(representative_by_class) == set(
        builder["_power_simulator_definition"]()["supported_design_classes"]
    )
    for experiment in representative_by_class.values():
        design = experiment["model_specific_power_design"]
        alternative = design["signed_design_alternatives"][0]
        matrix = design["data_generating_process"]["design_matrix"]
        base_smoke_n = max(160, len(matrix["columns"]) * 12)
        rows_per_fixture = matrix["observation_expansion"]["rows_per_fixture"]
        smoke_n = math.ceil(base_smoke_n / rows_per_fixture) * rows_per_fixture
        first_run = builder["run_power_simulation"](design, smoke_n, alternative, 2)
        second_run = builder["run_power_simulation"](design, smoke_n, alternative, 2)
        assert first_run == second_run
        assert first_run["replicates"] == 2


def test_first_25_are_stratum_selected_and_operationally_frozen(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    selected = [row for row in hypotheses if row["first_portfolio_candidate"]]
    experiments = artifacts["first-25-experiment-protocols-v1.json"]["experiments"]
    assert len(selected) == 25
    assert {row["portfolio_stratum_id"] for row in selected} == {
        row["stratum_id"] for row in builder["PORTFOLIO_STRATA"]
    }
    assert [row["portfolio_order"] for row in experiments] == list(range(1, 26))
    assert all(
        row["operational_definition"]["state"]
        == "PORTFOLIO_PROTOCOL_OPERATIONALLY_FROZEN"
        for row in experiments
    )
    assert all(row["thresholds"]["operational_thresholds"] for row in experiments)


def test_exp006_final_centered_contrast_recovers_signed_alternative(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    experiment = next(
        row
        for row in artifacts["first-25-experiment-protocols-v1.json"]["experiments"]
        if row["portfolio_order"] == 6
    )
    design = experiment["model_specific_power_design"]
    generation = design["data_generating_process"]["coefficient_generation"]
    assert generation["injection_space"] == "FINAL_POSTPROCESSED_OUTCOME_CONTRAST"
    assert generation["calibration_rule"] == (
        "PRIMARY_EXPOSURE_HAS_ZERO_SUM_ZERO_MEDIAN_UNIT_RMS_WITHIN_FIXTURE;"
        "FIXTURE_MEDIAN_CENTERING_IS_ORTHOGONAL_TO_PRIMARY_CONTRAST"
    )
    alternative = design["signed_design_alternatives"][0]
    eligible_units = 25_000
    latent_seed = builder["derive_power_latent_seed"](
        design["master_seed"], eligible_units, 777
    )
    sample = builder["generate_power_sample"](
        design, eligible_units, alternative, latent_seed
    )

    common_design = copy.deepcopy(design)
    common_design["data_generating_process"]["branch_transform"][
        "standardized_measurement_noise_sd"
    ] = 0.0
    branch_ids = design["decision_algorithm"]["branch_ids"]
    common_result = builder["fit_power_branch"](
        common_design, sample, branch_ids[0], 1
    )
    branch_results = [
        builder["fit_power_branch"](
            design,
            sample,
            branch_id,
            builder["derive_power_branch_transform_seed"](latent_seed, branch_id),
        )
        for branch_id in branch_ids
    ]
    for result in [common_result, *branch_results]:
        fitted_contrast = (
            result["ci95_lower_bound"] + result["ci95_upper_bound"]
        ) / 2
        assert fitted_contrast == pytest.approx(alternative, abs=0.02)


def test_validator_rejects_branch_aggregation(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    universe["hypotheses"][0]["devig_protocol"]["branch_results_aggregated"] = True
    _rehash(universe, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)

def test_validator_rejects_duplicate_semantic_core(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    universe["hypotheses"][1]["semantic_core_hash"] = universe["hypotheses"][0][
        "semantic_core_hash"
    ]
    _rehash(universe, builder)
    with pytest.raises(ValueError, match="duplicate semantic core"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_external_effect(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    universe["external_effects"]["provider_calls"] = 1
    _rehash(universe, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)


@pytest.mark.parametrize(
    "mutation",
    ["mismatched_version", "altered_hash"],
)
def test_validator_rejects_noncanonical_devig_triples(
    mutation: str,
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    component = universe["hypotheses"][0]["devig_protocol"]["branches"][0][
        "components"
    ][0]
    if mutation == "mismatched_version":
        component["devig_version"] = "LEGACY_SHIN_VAGUE1_V1"
    else:
        component["devig_definition_hash"] = "0" * 64
    _rehash(universe, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)


@pytest.mark.parametrize("field", ["derivation", "receipt_fields"])
def test_validator_rejects_pit_contract_drift(
    field: str,
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    point_in_time = universe["hypotheses"][0]["point_in_time"]
    if field == "derivation":
        point_in_time["available_at"]["derivation"] = "event_at"
    else:
        point_in_time["predictor_receipt_fields_required"] = ["bogus"]
    _rehash(universe, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_settled_label_as_predictor(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    universe = tampered["hypothesis-universe-v1.json"]
    hypothesis = universe["hypotheses"][0]
    label = next(
        row for row in hypothesis["data_dependencies"] if row["role"] == "LABEL"
    )
    predictor_copy = copy.deepcopy(label)
    predictor_copy.update(
            {
                "role": "ODDS",
                "analysis_usage": "PRE_CUTOFF_PREDICTOR",
                "temporal_admissibility": (
                "available_at <= cutoff_at and robin_ingested_at <= cutoff_at"
            ),
            "eligible_as_pre_cutoff_predictor": True,
            "result_available_at_required": False,
            "settlement_receipt_required": False,
        }
    )
    hypothesis["data_dependencies"].insert(0, predictor_copy)
    hypothesis["point_in_time"]["predictor_receipt_backed_sources_required"].insert(
        0, predictor_copy["dataset"]
    )
    _rehash(universe, builder)
    with pytest.raises(ValueError, match="settled outcomes cannot be pre-cutoff predictors"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_negative_score_component(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    scorecard = tampered["hypothesis-priority-scorecard-v1.json"]
    entry = scorecard["entries"][0]
    entry["components"]["strategic_value"] = -1
    entry["total"] = sum(entry["components"].values())
    _rehash(scorecard, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)


@pytest.mark.parametrize("target", ["scorecard", "experiment"])
def test_validator_rejects_unknown_hypothesis_ids(
    target: str,
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    tampered = copy.deepcopy(artifacts)
    unknown_id = "RDS-HYP-V1-0000000000000000"
    if target == "scorecard":
        report = tampered["hypothesis-priority-scorecard-v1.json"]
        report["entries"][0]["hypothesis_id"] = unknown_id
    else:
        report = tampered["first-25-experiment-protocols-v1.json"]
        experiment = report["experiments"][0]
        experiment["hypothesis_id"] = unknown_id
        _rehash_experiment(experiment, builder)
    _rehash(report, builder)
    with pytest.raises(ValueError):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_broken_candidate_cluster_partition(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["hypothesis-deduplication-v1.json"]
    cluster = report["clusters"][0]
    cluster["candidate_ids"][0] = cluster["candidate_ids"][1]
    _rehash(report, builder)
    with pytest.raises(ValueError, match="clusters must partition"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_candidate_semantic_hash_drift(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["hypothesis-deduplication-v1.json"]
    report["candidates"][0]["semantic_core_hash"] = "0" * 64
    _rehash(report, builder)
    with pytest.raises(ValueError, match="candidate semantic core"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_score_order_drift(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["hypothesis-priority-scorecard-v1.json"]
    report["entries"][0], report["entries"][1] = report["entries"][1], report["entries"][0]
    _rehash(report, builder)
    with pytest.raises(ValueError, match="scorecard order"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_family_quota_drift(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["hypothesis-priority-scorecard-v1.json"]
    quotas = report["selection_policy"]["family_quotas"]
    keys = list(quotas)
    quotas[keys[0]] += 1
    quotas[keys[1]] -= 1
    _rehash(report, builder)
    with pytest.raises(ValueError, match="family quotas"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_experiment_devig_drift(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["first-25-experiment-protocols-v1.json"]
    experiment = report["experiments"][0]
    experiment["devig_protocol"]["selection_rule"] += ";TAMPERED"
    _rehash_experiment(experiment, builder)
    _rehash(report, builder)
    with pytest.raises(ValueError, match="de-vig protocol does not match"):
        builder["validate_artifacts"](tampered)


def test_validator_rejects_experiment_order_drift(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["first-25-experiment-protocols-v1.json"]
    report["experiments"][0], report["experiments"][1] = (
        report["experiments"][1],
        report["experiments"][0],
    )
    _rehash(report, builder)
    with pytest.raises(ValueError, match="experiment order"):
        builder["validate_artifacts"](tampered)


@pytest.mark.parametrize(
    "mutation",
    [
        "model_formula",
        "signed_alternative",
        "binary_prevalence",
        "contrast_vector",
        "joint_cell_probabilities",
        "cluster_icc",
        "fdr_algorithm",
        "simulator_definition",
        "simulator_hash",
        "latent_scope",
        "bookmaker_axis_count",
        "bookmaker_normalization",
        "within_repeat_rows",
        "partial_fixture_candidate",
        "half_interaction",
        "missing_league_fixed_effect",
        "outcome_centering",
    ],
)
def test_validator_rejects_coherently_rehashed_power_contract_drift(
    mutation: str,
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    tampered = copy.deepcopy(artifacts)
    report = tampered["first-25-experiment-protocols-v1.json"]
    experiment = report["experiments"][0]
    if mutation in {"binary_prevalence", "contrast_vector"}:
        experiment = next(
            row
            for row in report["experiments"]
            if row["operational_definition"]["model"]["power_design_matrix_class"]
            == "BINARY_MAIN_EFFECT"
        )
    elif mutation == "joint_cell_probabilities":
        experiment = next(
            row
            for row in report["experiments"]
            if row["operational_definition"]["model"]["power_design_matrix_class"]
            == "JOINT_BINARY_INTERACTION"
        )
    power = experiment["model_specific_power_design"]
    if mutation == "model_formula":
        power["formula_test_mapping"]["model_formula"] += " + forbidden_post_freeze_term"
    elif mutation == "signed_alternative":
        power["signed_design_alternatives"][0] *= 1.10
    elif mutation == "binary_prevalence":
        latent = next(
            row
            for row in power["data_generating_process"]["design_matrix"][
                "latent_variables"
            ]
            if row["distribution"] == "BERNOULLI"
        )
        latent["prevalence"] = 0.30
    elif mutation == "contrast_vector":
        power["data_generating_process"]["design_matrix"]["primary_contrast"][
            "weights"
        ][1] *= 1.10
    elif mutation == "joint_cell_probabilities":
        latent = power["data_generating_process"]["design_matrix"][
            "latent_variables"
        ][0]
        latent["probabilities"][0] -= 0.01
        latent["probabilities"][1] += 0.01
    elif mutation == "bookmaker_axis_count":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 6
        )
        power = experiment["model_specific_power_design"]
        expansion = power["data_generating_process"]["design_matrix"][
            "observation_expansion"
        ]
        expansion["axis_cardinalities"]["BOOKMAKER"] = 4
        expansion["rows_per_fixture"] = 4
        power["data_generating_process"]["cluster_process"]["mean_cluster_size"] = 4
    elif mutation == "bookmaker_normalization":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 6
        )
        power = experiment["model_specific_power_design"]
        latent = next(
            row
            for row in power["data_generating_process"]["design_matrix"][
                "latent_variables"
            ]
            if row["name"] == "book_deviation_H24_z"
        )
        latent.pop("normalization")
    elif mutation == "within_repeat_rows":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 18
        )
        power = experiment["model_specific_power_design"]
        latent = next(
            row
            for row in power["data_generating_process"]["design_matrix"][
                "latent_variables"
            ]
            if row["name"] == "congested"
        )
        latent["repeat_rows"] = 1
    elif mutation == "partial_fixture_candidate":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 18
        )
        power = experiment["model_specific_power_design"]
        power["candidate_eligible_units"][0] += 1
    elif mutation == "half_interaction":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 18
        )
        power = experiment["model_specific_power_design"]
        interaction = next(
            row
            for row in power["data_generating_process"]["design_matrix"]["columns"]
            if row["name"] == "congested_x_second_half"
        )
        interaction["expression"]["variables"] = ["congested", "venue_home"]
    elif mutation == "missing_league_fixed_effect":
        matrix = power["data_generating_process"]["design_matrix"]
        position = next(
            index
            for index, row in enumerate(matrix["columns"])
            if row["name"] == "league_season_ls8"
        )
        matrix["columns"].pop(position)
        matrix["primary_contrast"]["weights"].pop(position)
        matrix["fixture_invariant_columns"].remove("league_season_ls8")
    elif mutation == "outcome_centering":
        experiment = next(
            row for row in report["experiments"] if row["portfolio_order"] == 6
        )
        power = experiment["model_specific_power_design"]
        postprocessing = power["data_generating_process"]["outcome_postprocessing"]
        postprocessing.update(
            {
                "outcome_construct": "DECLARED_TRANSFORMED_OUTCOME",
                "common_outcome_rule": "NONE",
                "branch_outcome_rule": "NONE",
                "random_intercept_effect": "COMMON_SHIFT_RETAINED",
            }
        )
        power["data_generating_process"]["cluster_process"][
            "random_intercept_postprocessing"
        ] = "RETAINED_IN_TRANSFORMED_OUTCOME"
    elif mutation == "latent_scope":
        latent = next(
            row
            for row in power["data_generating_process"]["design_matrix"][
                "latent_variables"
            ]
            if row["scope"] == "FIXTURE"
        )
        latent["scope"] = "WITHIN_FIXTURE"
    elif mutation == "cluster_icc":
        power["data_generating_process"]["cluster_process"][
            "intraclass_correlation"
        ] = 0.10
    elif mutation == "fdr_algorithm":
        power["decision_algorithm"]["reported_q_value"] = "family_q_only"
    elif mutation == "simulator_definition":
        definition = power["simulator"]["definition"]
        definition["algorithm_steps"].append("silently aggregate de-vig branches")
        power["simulator"]["definition_hash"] = builder["sha256_json"](definition)
    else:
        power["simulator"]["definition_hash"] = "0" * 64
    _rehash_power_design(power, builder)
    _rehash_experiment(experiment, builder)
    _rehash(report, builder)
    with pytest.raises(Exception):
        builder["validate_artifacts"](tampered)
