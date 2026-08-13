from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
from collections.abc import Sequence
from itertools import permutations
from pathlib import Path

import pytest

from moteur.devig import probas_justes
from robin.backtesting.v3 import StrategyParameters, run_backtest
from robin.market_math import (
    ROI_DEFINITION_VERSION,
    SCIENTIFIC_KERNEL_VERSION,
    TURNOVER_DEFINITION_VERSION,
    YIELD_DEFINITION_VERSION,
    DevigInputError,
    DevigMethodError,
    decide_market,
    devig_probabilities,
    method_definition_hash,
    method_version,
    performance_summary,
    settle_profit,
    stake_units,
)
from robin.operations.activation import normalized_market_probabilities
from robin.prospective_observatory.prequential_contracts import PredictionMarket
from robin.prospective_observatory.prequential_factory import (
    devig_probabilities as prequential_devig,
)
from robin.shadow.decision import decide_shadow_bet
from scripts import build_scientific_truth_reports_v1 as report_builder
from scripts.run_prospective_observatory import (
    _complete_positive_overround_market,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("method", "version", "definition_hash", "fair_probabilities"),
    [
        (
            "PROPORTIONAL",
            "PROPORTIONAL_COMPLETE_MARKET_V1",
            "265d91ae91f793523180d617a3cbcd90ee95ac483d7fdbfcaa3547868e076684",
            (0.47058823529411764, 0.29411764705882354, 0.23529411764705882),
        ),
        (
            "SHIN",
            "LEGACY_SHIN_VAGUE1_V1",
            "3ff94a3daf36b0995717522ed3605bf0754d799705df028414043587b7375367",
            (0.47694200268453446, 0.2922796053732824, 0.23077839194218305),
        ),
    ],
)
def test_devig_protocol_version_hash_and_golden_vector_are_frozen(
    method: str,
    version: str,
    definition_hash: str,
    fair_probabilities: tuple[float, float, float],
) -> None:
    result = devig_probabilities(
        (2.0, 3.2, 4.0),
        method=method,
        outcome_labels=("HOME", "DRAW", "AWAY"),
    )
    assert method_version(method) == version
    assert method_definition_hash(method) == definition_hash
    assert result.version == version
    assert result.definition_hash == definition_hash
    assert result.fair_probabilities == pytest.approx(fair_probabilities)


def _fixed_roi_row(*, fixture_id: int, target: int) -> dict[str, object]:
    return {
        "fixture_id": fixture_id,
        "kickoff_at": f"2025-01-{fixture_id:02d}T18:00:00Z",
        "probability_home": 0.80,
        "probability_draw": 0.10,
        "probability_away": 0.10,
        "odds_home": 3.0,
        "odds_draw": 3.0,
        "odds_away": 3.0,
        "target": target,
        "origin": "OOS HISTORICAL",
    }


def test_backtest_v3_roi_is_profit_over_actual_turnover() -> None:
    result = run_backtest(
        [
            _fixed_roi_row(fixture_id=1, target=0),
            _fixed_roi_row(fixture_id=2, target=2),
        ],
        StrategyParameters(
            name="fixed_turnover_truth",
            market="1X2",
            minimum_edge=0.01,
            staking="FIXED",
        ),
        devig_method="PROPORTIONAL",
    )

    assert result["profit_units"] == pytest.approx(1.0)
    assert result["roi"] == pytest.approx(0.5)
    assert result["turnover_units"] == pytest.approx(2.0)
    assert result["yield"] == result["roi"]
    assert result["profit_per_bet"] == pytest.approx(0.5)
    assert result["starting_bankroll_units"] == pytest.approx(100.0)
    assert result["ending_bankroll_units"] == pytest.approx(101.0)
    assert result["scientific_kernel_version"] == SCIENTIFIC_KERNEL_VERSION
    assert result["roi_definition_version"] == ROI_DEFINITION_VERSION
    assert result["turnover_definition_version"] == TURNOVER_DEFINITION_VERSION
    assert result["yield_definition_version"] == YIELD_DEFINITION_VERSION
    assert result["devig_method"] == "PROPORTIONAL"
    assert result["devig_version"] == "PROPORTIONAL_COMPLETE_MARKET_V1"


def _declared_method_decision(
    *,
    model_probabilities: Sequence[float],
    fair_probabilities: Sequence[float],
    threshold: float,
) -> tuple[bool, int]:
    edges = [
        model - fair
        for model, fair in zip(
            model_probabilities,
            fair_probabilities,
            strict=True,
        )
    ]
    selection = max(range(len(edges)), key=edges.__getitem__)
    return bool(edges[selection] >= threshold), selection


def test_same_market_and_same_declared_method_produce_same_decision_across_paths() -> None:
    declared_method = "PROPORTIONAL"
    odds = [2.0, 3.2, 4.0]
    model_probabilities = [0.60, 0.25, 0.15]
    threshold = 0.04
    legacy_fair = probas_justes(odds, methode=declared_method)
    assert legacy_fair is not None
    expected_bet, expected_selection = _declared_method_decision(
        model_probabilities=model_probabilities,
        fair_probabilities=legacy_fair,
        threshold=threshold,
    )

    result = run_backtest(
        [
            {
                "fixture_id": 3,
                "kickoff_at": "2025-02-01T18:00:00Z",
                "probability_home": model_probabilities[0],
                "probability_draw": model_probabilities[1],
                "probability_away": model_probabilities[2],
                "odds_home": odds[0],
                "odds_draw": odds[1],
                "odds_away": odds[2],
                "target": 0,
                "origin": "OOS HISTORICAL",
            }
        ],
        StrategyParameters("declared_method_parity", "1X2", threshold),
        devig_method=declared_method,
    )

    assert (result["bets"] == 1) is expected_bet
    if expected_bet:
        details = result["details"]
        assert isinstance(details, list)
        assert details[0]["selection"] == expected_selection
        assert details[0]["devig_method"] == declared_method


@pytest.mark.parametrize("method", ["PROPORTIONAL", "SHIN"])
@pytest.mark.parametrize(
    "odds",
    [
        (3.0, 3.0, 3.0),
        (1.50, 4.50, 7.00),
        (1.80, 3.50, 20.00),
        (3.0 / 1.02, 3.0 / 1.02, 3.0 / 1.02),
        (3.0 / 1.05, 3.0 / 1.05, 3.0 / 1.05),
        (3.0 / 1.08, 3.0 / 1.08, 3.0 / 1.08),
        (3.0 / 1.12, 3.0 / 1.12, 3.0 / 1.12),
    ],
)
def test_devig_properties_and_permutation_invariance(
    method: str,
    odds: tuple[float, ...],
) -> None:
    baseline = devig_probabilities(
        odds,
        method=method,
        outcome_labels=("HOME", "DRAW", "AWAY"),
    )
    assert all(math.isfinite(value) and value >= 0.0 for value in baseline.fair_probabilities)
    assert sum(baseline.fair_probabilities) == pytest.approx(1.0, abs=1e-12)
    assert baseline == devig_probabilities(
        odds,
        method=method,
        outcome_labels=("HOME", "DRAW", "AWAY"),
    )
    for order in permutations(range(3)):
        permuted = devig_probabilities(
            tuple(odds[index] for index in order),
            method=method,
            outcome_labels=tuple(("HOME", "DRAW", "AWAY")[index] for index in order),
        )
        restored = tuple(permuted.fair_probabilities[order.index(index)] for index in range(3))
        assert restored == pytest.approx(baseline.fair_probabilities, abs=1e-12)


@pytest.mark.parametrize(
    ("odds", "labels", "code"),
    [
        ([], None, "DEVIG_MARKET_EMPTY"),
        ([2.0], None, "DEVIG_MARKET_ONE_OUTCOME"),
        ([2.0, None], None, "DEVIG_ODDS_MISSING"),
        ([2.0, float("nan")], None, "DEVIG_ODDS_NOT_FINITE"),
        ([2.0, float("inf")], None, "DEVIG_ODDS_NOT_FINITE"),
        ([2.0, float("-inf")], None, "DEVIG_ODDS_NOT_FINITE"),
        ([2.0, 1.0], None, "DEVIG_ODDS_MUST_EXCEED_ONE"),
        ([2.0, 0.0], None, "DEVIG_ODDS_MUST_EXCEED_ONE"),
        ([2.0, -2.0], None, "DEVIG_ODDS_MUST_EXCEED_ONE"),
        ([2.0, 3.0], ("HOME", "HOME"), "DEVIG_OUTCOME_LABEL_DUPLICATE"),
        ([2.0, 3.0], ("HOME",), "DEVIG_OUTCOME_COUNT_MISMATCH"),
        ([2.0, 3.0], ("HOME", ""), "DEVIG_OUTCOME_LABEL_MISSING"),
    ],
)
def test_devig_invalid_inputs_have_one_fail_closed_contract(
    odds: list[float | None],
    labels: tuple[str, ...] | None,
    code: str,
) -> None:
    for method in ("PROPORTIONAL", "SHIN"):
        with pytest.raises(DevigInputError, match=code):
            devig_probabilities(odds, method=method, outcome_labels=labels)


def test_devig_method_is_required_and_unknown_values_never_fallback() -> None:
    with pytest.raises(TypeError):
        devig_probabilities([2.0, 2.0])  # type: ignore[call-arg]
    with pytest.raises(DevigMethodError, match="DEVIG_METHOD_UNKNOWN"):
        devig_probabilities([2.0, 2.0], method="PROPORTIONAL_TYPO")


def test_underround_and_extreme_overround_are_explicitly_reported() -> None:
    underround = devig_probabilities([4.0, 4.0, 4.0], method="PROPORTIONAL")
    extreme = devig_probabilities([1.01, 1.01, 1.01], method="SHIN")
    assert underround.overround < 0.0
    assert extreme.overround > 1.0
    assert underround.validation_status == extreme.validation_status == "VALID"
    assert extreme.effective_method.value == "SHIN"
    shin_two_way = devig_probabilities([1.9, 2.0], method="SHIN")
    assert shin_two_way.method.value == "SHIN"
    assert shin_two_way.effective_method.value == "PROPORTIONAL"
    assert shin_two_way.fallback_reason == ("SHIN_TWO_OUTCOME_PROPORTIONAL_EQUIVALENCE")


def test_performance_truth_uses_actual_stakes_without_rounding() -> None:
    summary = performance_summary(
        starting_bankroll_units=100.0,
        stakes=[2.0, 1.0, 3.0],
        profits=[4.0, -1.0, 0.0],
    )
    assert summary["turnover_units"] == 6.0
    assert summary["profit_units"] == 3.0
    assert summary["roi"] == 0.5
    assert summary["yield"] == 0.5
    assert summary["profit_per_bet"] == 1.0
    assert summary["ending_bankroll_units"] == 103.0


def test_zero_bets_has_zero_turnover_and_undefined_ratios() -> None:
    result = run_backtest(
        [_fixed_roi_row(fixture_id=4, target=0)],
        StrategyParameters("no_bet", "1X2", minimum_edge=0.99),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 0
    assert result["profit_units"] == 0.0
    assert result["turnover_units"] == 0.0
    assert result["roi"] is None
    assert result["yield"] is None
    assert result["profit_per_bet"] is None
    assert result["starting_bankroll_units"] == result["ending_bankroll_units"] == 100.0


def test_zero_stake_cap_never_creates_a_zero_turnover_bet() -> None:
    result = run_backtest(
        [_fixed_roi_row(fixture_id=8, target=0)],
        StrategyParameters(
            "zero_stake",
            "1X2",
            minimum_edge=0.01,
            stake_cap=0.0,
        ),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 0
    assert result["turnover_units"] == 0.0
    assert result["roi"] is None


def test_bankroll_ruin_stops_future_fixed_stakes_without_negative_balance() -> None:
    rows = [_fixed_roi_row(fixture_id=index, target=2) for index in range(1, 106)]
    for row in rows:
        row["kickoff_at"] = "2025-01-01T18:00:00Z"
    result = run_backtest(
        rows,
        StrategyParameters("ruin", "1X2", minimum_edge=0.01),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 100
    assert result["turnover_units"] == 100.0
    assert result["profit_units"] == -100.0
    assert result["ending_bankroll_units"] == 0.0


@pytest.mark.parametrize("target", [-1, 3, 999])
def test_backtest_rejects_corrupt_1x2_target(target: int) -> None:
    row = _fixed_roi_row(fixture_id=9, target=target)
    with pytest.raises(ValueError, match="BACKTEST_TARGET_OUT_OF_RANGE"):
        run_backtest(
            [row],
            StrategyParameters("bad-target", "1X2", minimum_edge=0.01),
            devig_method="PROPORTIONAL",
        )


def test_mixed_complete_and_incomplete_markets_are_audited_per_row() -> None:
    invalid = _fixed_roi_row(fixture_id=10, target=0)
    invalid["odds_draw"] = None
    result = run_backtest(
        [invalid, _fixed_roi_row(fixture_id=11, target=0)],
        StrategyParameters("mixed-market", "1X2", minimum_edge=0.01),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 1
    assert result["invalid_market_rows"] == 1
    assert result["invalid_market_reasons"] == {"DEVIG_ODDS_MISSING": 1}


def test_backtest_orders_kickoffs_by_utc_instant_not_iso_text() -> None:
    later_text_but_earlier_utc = _fixed_roi_row(fixture_id=12, target=0)
    later_text_but_earlier_utc["kickoff_at"] = "2025-01-01T00:30:00+01:00"
    later_utc = _fixed_roi_row(fixture_id=13, target=0)
    later_utc["kickoff_at"] = "2025-01-01T00:00:00Z"
    result = run_backtest(
        [later_utc, later_text_but_earlier_utc],
        StrategyParameters("utc-order", "1X2", minimum_edge=0.01),
        devig_method="PROPORTIONAL",
    )
    assert [item["fixture_id"] for item in result["details"]] == [12, 13]


def test_truth_kernel_rejects_ambiguous_or_incoherent_inputs() -> None:
    with pytest.raises(ValueError, match="DECISION_THRESHOLD_INVALID"):
        decide_market([2.0, 2.0], [0.5, 0.5], method="PROPORTIONAL", threshold=-0.1)
    with pytest.raises(ValueError, match="STAKING_INPUT_INVALID"):
        stake_units(
            probability=1.1,
            odds=2.0,
            bankroll_units=100.0,
            staking="FIXED",
            kelly_fraction=0.25,
            stake_cap_units=1.0,
        )
    with pytest.raises(TypeError, match="SETTLEMENT_WON_BOOLEAN_REQUIRED"):
        settle_profit(stake_units=1.0, odds=2.0, won="LOSS")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="PERFORMANCE_INPUT_INVALID"):
        performance_summary(
            starting_bankroll_units=100.0,
            stakes=[0.0],
            profits=[1.0],
        )


@pytest.mark.parametrize(
    ("staking", "stake_cap", "targets", "expected_stakes"),
    [
        ("FIXED", 0.4, (0, 2), (0.4, 0.4)),
        ("PROPORTIONAL", 5.0, (0, 2), (1.0, 1.02)),
        ("FRACTIONAL_KELLY", 2.0, (0, 2), (2.0, 2.0)),
    ],
)
def test_backtest_turnover_tracks_fixed_proportional_and_kelly_stakes(
    staking: str,
    stake_cap: float,
    targets: tuple[int, int],
    expected_stakes: tuple[float, float],
) -> None:
    result = run_backtest(
        [
            _fixed_roi_row(fixture_id=5, target=targets[0]),
            _fixed_roi_row(fixture_id=6, target=targets[1]),
        ],
        StrategyParameters(
            "staking_truth",
            "1X2",
            minimum_edge=0.01,
            staking=staking,
            stake_cap=stake_cap,
        ),
        devig_method="PROPORTIONAL",
    )
    details = result["details"]
    assert isinstance(details, list)
    assert [detail["stake"] for detail in details] == pytest.approx(expected_stakes)
    assert result["turnover_units"] == pytest.approx(sum(expected_stakes))
    assert result["turnover_units"] == pytest.approx(
        sum(float(detail["stake"]) for detail in details)
    )
    assert result["profit_units"] == pytest.approx(
        sum(float(detail["profit"]) for detail in details)
    )
    assert result["ending_bankroll_units"] == pytest.approx(
        float(result["starting_bankroll_units"]) + float(result["profit_units"])
    )
    assert result["roi"] == pytest.approx(
        float(result["profit_units"]) / float(result["turnover_units"])
    )


@pytest.mark.parametrize(
    ("odds", "model"),
    [
        ((1.20, 8.0, 20.0), (0.90, 0.07, 0.03)),
        ((15.0, 2.0, 2.4), (0.20, 0.45, 0.35)),
    ],
)
def test_short_and_long_odds_remain_finite_without_core_rounding(
    odds: tuple[float, float, float],
    model: tuple[float, float, float],
) -> None:
    result = run_backtest(
        [
            {
                "fixture_id": 7,
                "kickoff_at": "2025-03-01T18:00:00Z",
                "probability_home": model[0],
                "probability_draw": model[1],
                "probability_away": model[2],
                "odds_home": odds[0],
                "odds_draw": odds[1],
                "odds_away": odds[2],
                "target": 0,
                "origin": "OOS HISTORICAL",
            }
        ],
        StrategyParameters("odds_boundaries", "1X2", minimum_edge=0.0),
        devig_method="PROPORTIONAL",
    )
    assert result["bets"] == 1
    assert all(
        math.isfinite(float(result[field]))
        for field in ("profit_units", "turnover_units", "roi", "yield")
    )


@pytest.mark.parametrize("method", ["PROPORTIONAL", "SHIN"])
def test_declared_method_has_full_decision_and_settlement_parity(
    method: str,
) -> None:
    odds = (2.0, 3.2, 4.0)
    labels = ("HOME", "DRAW", "AWAY")
    model = (0.60, 0.25, 0.15)
    threshold = 0.04
    canonical = decide_market(
        odds,
        model,
        method=method,
        threshold=threshold,
        outcome_labels=labels,
    )
    legacy = probas_justes(odds, methode=method)
    activation = normalized_market_probabilities(
        [odds[0]],
        [odds[1]],
        [odds[2]],
        devig_method=method,
    )
    prequential, margin = prequential_devig(
        PredictionMarket.ONE_X_TWO,
        dict(zip(labels, odds, strict=True)),
        devig_method=method,
    )
    assert tuple(legacy) == pytest.approx(canonical.devig.fair_probabilities)
    assert activation == pytest.approx(canonical.devig.fair_probabilities)
    assert tuple(prequential[label] for label in labels) == pytest.approx(
        canonical.devig.fair_probabilities
    )
    assert margin == pytest.approx(canonical.devig.overround)

    shadow = decide_shadow_bet(
        fixture_id="parity-fixture",
        market_key="1X2",
        selection=canonical.selected_outcome,
        market_odds=dict(zip(labels, odds, strict=True)),
        model_probability=model[canonical.selected_index],
        devig_method=method,
        strategy_version="truth-kernel-parity-v1",
        quality_ok=True,
        min_edge=threshold,
        bankroll=100.0,
    )
    backtest = run_backtest(
        [
            {
                "fixture_id": "parity-fixture",
                "kickoff_at": "2025-04-01T18:00:00Z",
                "probability_home": model[0],
                "probability_draw": model[1],
                "probability_away": model[2],
                "odds_home": odds[0],
                "odds_draw": odds[1],
                "odds_away": odds[2],
                "target": canonical.selected_index,
                "origin": "OOS HISTORICAL",
            }
        ],
        StrategyParameters(
            "parity",
            "1X2",
            minimum_edge=threshold,
            staking="PROPORTIONAL",
            stake_cap=10.0,
        ),
        devig_method=method,
    )
    detail = backtest["details"][0]
    expected_profit = settle_profit(
        stake_units=shadow.suggested_stake,
        odds=odds[canonical.selected_index],
        won=True,
    )
    expected_performance = performance_summary(
        starting_bankroll_units=100.0,
        stakes=[shadow.suggested_stake],
        profits=[expected_profit],
    )
    assert shadow.accepted is canonical.accepted is True
    assert shadow.fair_probability == pytest.approx(
        canonical.devig.fair_probabilities[canonical.selected_index]
    )
    assert shadow.edge == pytest.approx(canonical.selected_edge)
    assert shadow.suggested_stake == pytest.approx(detail["stake"])
    assert detail["selection"] == canonical.selected_index
    assert detail["profit"] == pytest.approx(expected_profit)
    for field in ("profit_units", "turnover_units", "roi", "yield"):
        assert backtest[field] == pytest.approx(expected_performance[field])


def test_active_paths_do_not_reimplement_margin_removal_inline() -> None:
    guarded_functions = {
        "src/robin/backtesting/v3.py": {"run_backtest"},
        "src/robin/backtesting/oos.py": {"evaluate_walk_forward"},
        "src/robin/deep_football/models.py": {"devig_1x2"},
        "src/robin/historical/critical_closure.py": {"proportional_devig"},
        "src/robin/historical/dataset_factory.py": {"build_api_team_pre_match"},
        "src/robin/historical/external_validation.py": {"devig_market_odds"},
        "src/robin/historical/model_lab.py": {"_market_probabilities"},
        "src/robin/historical_deep/backtest.py": {"_market_probability"},
        "src/robin/modeling/reference.py": {"market_probabilities"},
        "src/robin/operations/activation.py": {"normalized_market_probabilities"},
        "src/robin/prospective_observatory/prequential_factory.py": {"devig_probabilities"},
        "src/robin/shadow/decision.py": {"decide_shadow_bet"},
        "scripts/run_historical_pipeline.py": {"_market_prediction_rows"},
        "scripts/run_historical_deep_harvest.py": {"build_cache_only_backtest_input"},
        "scripts/run_prospective_observatory.py": {"_odds_rows"},
    }
    violations: list[str] = []
    for relative, function_names in guarded_functions.items():
        tree = ast.parse((ROOT / relative).read_text("utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in function_names:
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.BinOp) or not isinstance(child.op, ast.Div):
                    continue
                numerator = child.left
                if (
                    isinstance(numerator, ast.Constant)
                    and isinstance(numerator.value, (int, float))
                    and float(numerator.value) == 1.0
                ):
                    violations.append(f"{relative}:{node.name}:{child.lineno}")
    assert violations == []


def test_prospective_projection_accepts_only_complete_positive_overround() -> None:
    complete = [
        {"name": "HOME", "price": 2.0},
        {"name": "DRAW", "price": 3.2},
        {"name": "AWAY", "price": 4.0},
    ]
    validated = _complete_positive_overround_market("h2h", complete)
    assert validated is not None
    outcomes, devig = validated
    assert outcomes == tuple(complete)
    assert devig.method.value == "PROPORTIONAL"
    assert devig.overround == pytest.approx(0.0625)

    assert (
        _complete_positive_overround_market(
            "h2h",
            [
                {"name": "HOME", "price": 3.0},
                {"name": "DRAW", "price": 4.0},
                {"name": "AWAY", "price": 5.0},
            ],
        )
        is None
    )
    assert _complete_positive_overround_market("h2h", complete[:2]) is None
    assert (
        _complete_positive_overround_market(
            "h2h",
            [complete[0], complete[0], complete[2]],
        )
        is None
    )


REPORT_FILES = {
    "scientific-truth-defect-inventory-v1.json",
    "roi-turnover-repair-v1.json",
    "yield-consumer-inventory-v1.json",
    "devig-implementation-inventory-v1.json",
    "devig-canonicalization-v1.json",
    "decision-path-trace-v1.json",
    "historical-truth-replay-v1.json",
    "historical-invalidation-ledger-v1.json",
}


def _report(name: str) -> dict[str, object]:
    value = json.loads((ROOT / "reports" / "scientific-truth" / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _pointer(document: object, pointer: str) -> object:
    current = document
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            assert isinstance(current, dict)
            current = current[token]
    return current


def _all_evidence_ids(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("evidence_ids"):
                assert isinstance(item, list)
                found.extend(str(evidence_id) for evidence_id in item)
            else:
                found.extend(_all_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_all_evidence_ids(item))
    return found


def test_scientific_truth_reports_have_one_deterministic_bounded_envelope() -> None:
    report_dir = ROOT / "reports" / "scientific-truth"
    assert {path.name for path in report_dir.glob("*.json")} == REPORT_FILES
    regenerated = report_builder._build_all()
    assert set(regenerated) == REPORT_FILES
    allowed_statuses = {"PROUVÉ", "PROBABLE", "HYPOTHÈSE", "NON VÉRIFIÉ"}
    for name in sorted(REPORT_FILES):
        stored = _report(name)
        assert stored == regenerated[name]
        assert stored["schema_version"] == "robin-scientific-truth-report-v1"
        assert stored["mission_id"] == "SCIENTIFIC_TRUTH_KERNEL"
        assert stored["scientific_kernel_version"] == SCIENTIFIC_KERNEL_VERSION
        assert stored["evidence_status"] in allowed_statuses
        assert stored["review_status"] == "PENDING_INDEPENDENT_REVIEW"
        assert stored["verified_by"] == []
        assert stored["audit_source"]["manifest_sha256"] == (
            report_builder.AUDIT_MANIFEST_SHA256
        )
        assert stored["loop54_source"]["manifest_sha256"] == (
            report_builder.LOOP54_MANIFEST_SHA256
        )
        assert stored["loop54_source"]["status"] == "SEALED_EXTERNAL_EVIDENCE_PACK"
        evidence_ids = _all_evidence_ids(stored)
        assert evidence_ids
        assert all(
            evidence_id.startswith(("AUDIT:", "LOOP54:", "LOOP54_REPORTS:"))
            for evidence_id in evidence_ids
        )
        assert stored["reproducibility"]["command_evidence_ids"] == [
            report_builder.LOOP54_REPORTS_EVIDENCE_ID
        ]
        assert stored["report_generation_receipt"] == {
            "namespace": "LOOP54_REPORTS",
            "evidence_id": report_builder.LOOP54_REPORTS_EVIDENCE_ID,
            "logical_root": report_builder.LOOP54_REPORTS_LOGICAL_PATH,
            "binding": "DETACHED_MANIFEST_CLAIM_IN_EVIDENCE_GRAPH",
        }
        generation_command = stored["reproducibility"]["generation_command"]
        assert "--audit-root" in generation_command
        assert "--loop54-root" in generation_command
        authority = stored["authority"]
        assert isinstance(authority, dict)
        assert authority["global_devig_authority"] == "CONFLICTING"
        assert authority["global_selected_method"] is None
        assert authority["roi_used_for_authority"] is False
        effects = stored["external_effects"]
        assert isinstance(effects, dict)
        assert effects and all(value == 0 for value in effects.values())
        content = {key: value for key, value in stored.items() if key != "content_sha256"}
        assert stored["content_sha256"] == _canonical_hash(content)
        assert stored["hash_policy"] == {
            "tracked_repository_text": "SHA256_GIT_CANONICAL_LF_BYTES",
            "external_evidence_pack_files": "SHA256_RAW_BYTES",
            "audited_windows_checkout_hashes_preserved_separately": True,
        }

    doc = (ROOT / "docs" / "scientific" / "ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1.md").read_text(
        encoding="utf-8"
    )
    assert "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL" in doc
    assert "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_READY" not in doc
    assert "TEMPORAL_VALIDITY_NOT_PROVEN" in doc


@pytest.mark.parametrize(
    "argv",
    [
        ["builder", "--audit-root", "audit", "--check"],
        ["builder", "--loop54-root", "loop54", "--check"],
    ],
)
def test_report_builder_requires_both_evidence_roots(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as caught:
        report_builder.main()
    assert caught.value.code == 2


def test_report_builder_hashes_repository_text_as_canonical_lf() -> None:
    for relative, expected in report_builder.REPOSITORY_INPUTS.items():
        path = ROOT / relative
        raw = path.read_bytes()
        assert report_builder._sha256_repository_file(path) == expected
        assert report_builder._sha256_bytes(raw.replace(b"\r\n", b"\n")) == expected


def test_historical_formula_replay_resolves_15_results_and_45_occurrences() -> None:
    replay = _report("historical-truth-replay-v1.json")
    assert replay["replay_type"] == ("FORMULA_REPLAY_FROM_STORED_PROFIT_AND_FIXED_STAKE_BET_COUNT")
    results = replay["results"]
    assert isinstance(results, list)
    assert len(results) == 15
    assert len({item["logical_result_id"] for item in results}) == 15
    source_documents = {
        "cockpit/app/cockpit-data.json": json.loads(
            (ROOT / "cockpit" / "app" / "cockpit-data.json").read_text("utf-8")
        ),
        "cockpit/app/cockpit-expert-data.json": json.loads(
            (ROOT / "cockpit" / "app" / "cockpit-expert-data.json").read_text("utf-8")
        ),
    }
    occurrence_ids: set[str] = set()
    projection_hashes: set[str] = set()
    for result in results:
        projection_hashes.add(result["source_projection_sha256"])
        assert result["original"]["devig_method"] == "UNKNOWN"
        assert result["original"]["scientific_kernel_version"] is None
        assert result["original"]["scientific_identity_status"] == (
            "LEGACY_UNVERSIONED_NOT_CANONICAL"
        )
        assert result["calculation_basis"] == "SUMMARY_FIXED_1U_INFERENCE"
        assert result["branches"]["C"]["evidence_status"] == "NON VÉRIFIÉ"
        assert result["branches"]["D1"]["evidence_status"] == "NON VÉRIFIÉ"
        assert result["branches"]["D2"]["evidence_status"] == "NON VÉRIFIÉ"
        assert result["branches"]["B"]["turnover_units"] == pytest.approx(
            result["original"]["bets"]
        )
        assert result["branches"]["B"]["roi"] == pytest.approx(
            result["original"]["profit_units"] / result["original"]["bets"]
        )
        assert result["branches"]["B"]["yield"] == pytest.approx(result["branches"]["B"]["roi"])
        occurrences = result["source_occurrences"]
        assert len(occurrences) == 3
        assert [item["relation"] for item in occurrences] == [
            "PRIMARY_SOURCE_OCCURRENCE",
            "COPY_OF",
            "COPY_OF",
        ]
        for occurrence in occurrences:
            occurrence_ids.add(occurrence["occurrence_id"])
            assert occurrence["source_artifact_hash_representation"] == (
                "GIT_CANONICAL_LF"
            )
            assert occurrence["audited_checkout_artifact_sha256"] == (
                report_builder.AUDITED_CHECKOUT_INPUTS[occurrence["repo_path"]]
            )
            source = source_documents[occurrence["repo_path"]]
            object_value = _pointer(source, occurrence["json_pointer"])
            assert occurrence["source_object_sha256"] == _canonical_hash(object_value)
            projected = report_builder._source_projection(object_value)
            assert _canonical_hash(projected) == result["source_projection_sha256"]
    assert len(occurrence_ids) == 45
    assert len(projection_hashes) == 15
    summary = replay["summary"]
    assert summary["decision_replayed_logical_results"] == 0
    assert summary["devig_replayed_logical_results"] == 0
    assert summary["maximum_absolute_roi_change"] == pytest.approx(0.04577382258550142)
    assert replay["multiplicity"]["tests"] == 7480
    assert replay["multiplicity"]["survivors"] == 0
    assert replay["multiplicity"]["machine_q_values"] == [1.0, 1.0, 1.0]
    assert replay["multiplicity"]["promotion"] is False
    assert replay["temporal"]["surfaces"] == 72
    assert replay["temporal"]["proven_surfaces"] == 0


def test_historical_invalidation_ledger_is_append_only_and_hash_chained() -> None:
    ledger = _report("historical-invalidation-ledger-v1.json")
    records = ledger["records"]
    assert isinstance(records, list)
    assert len(records) == 165
    relations = {relation: 0 for relation in ledger["allowed_relations"]}
    previous = "0" * 64
    for sequence, record in enumerate(records, 1):
        assert record["sequence"] == sequence
        assert record["previous_record_hash"] == previous
        body = {key: value for key, value in record.items() if key != "record_hash"}
        assert record["record_hash"] == _canonical_hash(body)
        previous = record["record_hash"]
        relations[record["relation"]] += 1
        assert record["replacement"]["repo_path"] == (
            "reports/scientific-truth/historical-truth-replay-v1.json"
        )
    assert previous == ledger["chain_tip"]
    assert relations == {
        "SUPERSEDED_BY": 45,
        "COPY_OF": 30,
        "INVALIDATED_BY_ROI_DEFINITION": 45,
        "INVALIDATED_BY_DEVIG_METHOD": 0,
        "TEMPORAL_VALIDITY_NOT_PROVEN": 45,
    }
    assert ledger["counts"]["source_artifacts_rewritten"] == 0
    assert ledger["counts"]["stored_yield_fields_invalidated"] == 0


def test_devig_inventory_and_authority_never_select_by_historical_performance() -> None:
    inventory = _report("devig-implementation-inventory-v1.json")
    assert inventory["implementation_count"] == 15
    implementations = inventory["implementations"]
    assert len({item["implementation_id"] for item in implementations}) == 15
    assert any(
        item["implementation_id"] == "shadow_raw_implied_not_devig"
        and item["audit_method"] == "RAW_IMPLIED_NOT_DEVIG"
        for item in implementations
    )
    canonicalization = _report("devig-canonicalization-v1.json")
    resolution = canonicalization["protocol_resolution"]
    assert resolution["verdict"] == "DEVIG_PROTOCOL_CONFLICT"
    assert resolution["canonical_method"] is None
    assert resolution["canonical_version"] is None
    assert resolution["roi_used_for_authority"] is False
    assert canonicalization["sensitivity_evidence"]["selection_use"] == (
        "SENSITIVITY_ONLY_NOT_AUTHORITY"
    )
    chronos = next(
        item
        for item in canonicalization["scope_resolution"]
        if item["scope"] == "CHRONOS_CANARY_POINT_IN_TIME_COMPLETE_SAME_RECEIPT"
    )
    assert chronos["status"] == "UNIQUE"


def test_defect_inventory_has_no_open_p0_or_p1_and_preserves_partial_limits() -> None:
    inventory = _report("scientific-truth-defect-inventory-v1.json")
    assert inventory["counts"]["open_p0"] == 0
    assert inventory["counts"]["open_p1"] == 0
    assert inventory["counts"]["essential_p2_open"] == 3
    unresolved = [item for item in inventory["defects"] if not item["resolved"]]
    assert {item["status"] for item in unresolved} == {
        "NOT_IN_SCOPE",
        "REPLAY_REQUIRED",
    }
    assert any(
        verdict["verdict"] == "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1_PARTIAL"
        for verdict in inventory["verdicts"]
    )
