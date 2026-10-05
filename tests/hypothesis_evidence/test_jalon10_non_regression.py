from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from robin.hypothesis_evidence.non_regression import (
    AGGREGATE_UNITS_ABS_TOLERANCE,
    PER_BET_ABS_TOLERANCE,
    ROI_ABS_TOLERANCE,
    NonRegressionMismatch,
    compare_detailed_rows,
    recalculate_metrics,
    witness_rules,
)

ROOT = Path(__file__).resolve().parents[2]
TOP_THREE = ROOT / "reports/hypothesis-evidence/top-3.json"
NON_REGRESSION_REPORT = ROOT / "reports/hypothesis-evidence/r3-jalon10-non-regression.json"


def _rows() -> list[dict[str, object]]:
    return [
        {
            "hypothesis_id": "J10-M999",
            "rule_hash": "a" * 64,
            "occurrence_index": 1,
            "canonical_match_id": "api-football:10",
            "fixture_id": "10",
            "kickoff_at": "2020-01-01T12:00:00+00:00",
            "competition": "Test League",
            "season": 2020,
            "home_team_id": "1",
            "away_team_id": "2",
            "home_team_name": "Home",
            "away_team_name": "Away",
            "home_goals": 0,
            "away_goals": 1,
            "market": "1X2_AWAY",
            "selection": "AWAY",
            "price_class": "HISTORICAL_CLOSING_MARKET",
            "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
            "observed_odds": 2.25,
            "market_margin": 0.05,
            "stake_units": 1.0,
            "won": True,
            "lost": False,
            "void": False,
            "gross_return_units": 2.25,
            "profit_units": 1.25,
            "cumulative_profit_units": 1.25,
            "membership_hash": "b" * 64,
            "source_row_hash": "c" * 64,
        },
        {
            "hypothesis_id": "J10-M999",
            "rule_hash": "a" * 64,
            "occurrence_index": 2,
            "canonical_match_id": "api-football:11",
            "fixture_id": "11",
            "kickoff_at": "2020-01-02T12:00:00+00:00",
            "competition": "Test League",
            "season": 2020,
            "home_team_id": "3",
            "away_team_id": "4",
            "home_team_name": "Other Home",
            "away_team_name": "Other Away",
            "home_goals": 2,
            "away_goals": 0,
            "market": "1X2_AWAY",
            "selection": "AWAY",
            "price_class": "HISTORICAL_CLOSING_MARKET",
            "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
            "observed_odds": 1.9,
            "market_margin": 0.04,
            "stake_units": 1.0,
            "won": False,
            "lost": True,
            "void": False,
            "gross_return_units": 0.0,
            "profit_units": -1.0,
            "cumulative_profit_units": 0.25,
            "membership_hash": "d" * 64,
            "source_row_hash": "e" * 64,
        },
    ]


def test_witness_catalog_is_exactly_the_three_frozen_rules() -> None:
    payload = json.loads(TOP_THREE.read_text(encoding="utf-8"))
    rules = witness_rules(payload)

    assert [item.hypothesis_id for item in rules] == [
        "J10-M001",
        "J10-M002",
        "J10-M003",
    ]
    assert [item.rule.digest for item in rules] == [
        "293f3a6d5e635389abc272e8b6579b5e95df58836cd2e1355737df96c52f4867",
        "a82c917853baf22ec85eea189eb2efde72022b0271e1e0eadffb2f851d0623a2",
        "561b8a16908ab9bb8cb477c77af343779d20485d959b40ea7ed2a2e60535ec20",
    ]
    assert sum(item.expected_bets for item in rules) == 865
    assert all(item.expected_q_value == 1.0 for item in rules)
    assert all(
        item.expected_status == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING" for item in rules
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("canonical_match_id", "api-football:999"),
        ("kickoff_at", "2020-01-01T12:00:01+00:00"),
        ("observed_odds", 2.24),
        ("won", False),
        ("lost", True),
        ("profit_units", -1.0),
        ("cumulative_profit_units", 0.24),
        ("source_row_hash", "f" * 64),
    ],
)
def test_detailed_comparison_fails_closed_on_any_material_delta(
    field: str,
    replacement: object,
) -> None:
    baseline = _rows()
    replay = deepcopy(baseline)
    replay[0][field] = replacement

    with pytest.raises(NonRegressionMismatch, match=field):
        compare_detailed_rows(baseline, replay)


def test_tolerances_only_cover_float64_noise() -> None:
    baseline = _rows()
    replay = deepcopy(baseline)
    replay[0]["observed_odds"] = 2.25 + PER_BET_ABS_TOLERANCE / 2
    replay[0]["profit_units"] = 1.25 + PER_BET_ABS_TOLERANCE / 2
    replay[0]["cumulative_profit_units"] = 1.25 + AGGREGATE_UNITS_ABS_TOLERANCE / 2

    result = compare_detailed_rows(baseline, replay)

    assert result["rows_compared"] == 2
    assert result["unexplained_delta_count"] == 0
    assert result["maximum_absolute_deltas"]["observed_odds"] <= 1e-12
    assert PER_BET_ABS_TOLERANCE == 1e-12
    assert AGGREGATE_UNITS_ABS_TOLERANCE == 1e-9
    assert ROI_ABS_TOLERANCE == 1e-12


def test_metrics_use_unit_stake_internal_values_and_chronological_drawdown() -> None:
    metrics = recalculate_metrics(_rows())

    assert metrics == {
        "bets": 2,
        "wins": 1,
        "losses": 1,
        "voids": 0,
        "total_staked_units": 2.0,
        "profit_units": 0.25,
        "roi": 0.125,
        "maximum_drawdown_units": 1.0,
    }


def test_duplicate_or_out_of_order_identity_is_rejected() -> None:
    baseline = _rows()
    duplicate = deepcopy(baseline)
    duplicate[1]["canonical_match_id"] = duplicate[0]["canonical_match_id"]
    with pytest.raises(NonRegressionMismatch, match="duplicate"):
        compare_detailed_rows(baseline, duplicate)

    reversed_rows = list(reversed(deepcopy(baseline)))
    with pytest.raises(NonRegressionMismatch, match="occurrence_index"):
        compare_detailed_rows(baseline, reversed_rows)


def test_tracked_report_freezes_internal_witness_results() -> None:
    report = json.loads(NON_REGRESSION_REPORT.read_text(encoding="utf-8"))

    assert report["equivalence_status"] == "PASS"
    assert report["rows_compared"] == 865
    assert report["unique_fixtures_compared"] == 863
    assert report["comparison"]["unexplained_delta_count"] == 0
    assert set(report["comparison"]["maximum_absolute_deltas"].values()) == {0.0}
    assert (
        report["detailed_artifacts"]["baseline"]["sha256"]
        == (report["detailed_artifacts"]["replay"]["sha256"])
    )
    assert report["tolerances"] == {
        "relative": 0.0,
        "per_bet_absolute": 1e-12,
        "aggregate_units_absolute": 1e-9,
        "roi_absolute": 1e-12,
        "justification": (
            "Bounds cover binary64 addition noise over at most 363 bets and "
            "remain far below the report precision of 0.01 unit."
        ),
    }
    assert [item["metrics"] for item in report["witnesses"]] == [
        {
            "bets": 261,
            "wins": 135,
            "losses": 126,
            "voids": 0,
            "total_staked_units": 261.0,
            "profit_units": 43.43,
            "roi": 0.1663984674329502,
            "maximum_drawdown_units": 9.269999999999982,
        },
        {
            "bets": 363,
            "wins": 136,
            "losses": 227,
            "voids": 0,
            "total_staked_units": 363.0,
            "profit_units": 57.88,
            "roi": 0.1594490358126722,
            "maximum_drawdown_units": 19.519999999999868,
        },
        {
            "bets": 241,
            "wins": 154,
            "losses": 87,
            "voids": 0,
            "total_staked_units": 241.0,
            "profit_units": 33.42,
            "roi": 0.1386721991701245,
            "maximum_drawdown_units": 7.220000000000027,
        },
    ]
    assert report["explained_legacy_bug_corrections"] == []
    assert report["unexplained_deltas"] == []
    assert report["scientific_verdict"] == "JALON_10_NO_ROBUST_PATTERN_FOUND"
    assert report["scientific_verdict_changed"] is False
    assert report["search_reopened"] is False
    assert all(item["q_value"] == 1.0 for item in report["witnesses"])
    assert all(
        item["status"] == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
        for item in report["witnesses"]
    )
    assert set(report["external_effects"].values()) == {0}


def test_safe_workflow_replays_and_byte_verifies_the_three_witnesses() -> None:
    workflow = (ROOT / ".github/workflows/ci-safe-v2.yml").read_text(encoding="utf-8")

    assert "jalon10-r3-non-regression-windows:" in workflow
    assert 'name: "Jalon 10 - trois temoins R3 bornes"' in workflow
    assert "needs: frozen-evidence-windows" in workflow
    assert "Restaurer les entrees Jalon 10 verifiees" in workflow
    assert "Restaurer les Parquet canoniques" in workflow
    r3_job = workflow.split("  jalon10-r3-non-regression-windows:", maxsplit=1)[1]
    r3_job = r3_job.split("\n  chronos-postgresql-profiles:", maxsplit=1)[0]
    assert "run_pattern_campaign.py" not in r3_job
    assert "build_hypothesis_evidence.py" not in r3_job
    assert "python scripts/run_jalon10_non_regression.py `" in workflow
    assert "--output-root artifacts/r3-jalon10-non-regression `" in workflow
    assert "--report .ci/r3-jalon10-non-regression.json `" in workflow
    assert "--verify-report reports/hypothesis-evidence/r3-jalon10-non-regression.json" in workflow
    assert "JALON10_R3_NON_REGRESSION_RESULT" in workflow


def test_cli_refuses_detailed_output_at_repository_root() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_jalon10_non_regression.py"),
            "--output-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "DETAILED_OUTPUT_MUST_REMAIN_UNDER_IGNORED_ARTIFACTS" in result.stderr


def test_cli_refuses_to_overwrite_its_reference_report() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_jalon10_non_regression.py"),
            "--report",
            str(NON_REGRESSION_REPORT),
            "--verify-report",
            str(NON_REGRESSION_REPORT.parent / "." / NON_REGRESSION_REPORT.name),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "GENERATED_REPORT_MUST_NOT_OVERWRITE_REFERENCE" in result.stderr


def test_cli_refuses_hardlink_alias_of_reference_report(tmp_path: Path) -> None:
    reference = tmp_path / "reference.json"
    generated = tmp_path / "generated.json"
    reference.write_text("{}\n", encoding="utf-8")
    os.link(reference, generated)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_jalon10_non_regression.py"),
            "--output-root",
            str(tmp_path / "details"),
            "--report",
            str(generated),
            "--verify-report",
            str(reference),
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "GENERATED_REPORT_MUST_NOT_OVERWRITE_REFERENCE" in result.stderr
