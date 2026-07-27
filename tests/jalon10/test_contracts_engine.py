from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from robin.patterns.contracts import (
    ConditionOperator,
    EvidenceScope,
    PatternCondition,
    PatternDefinition,
    PatternStatus,
    pattern_id_from_hash,
    rule_hash,
)
from robin.patterns.engine import (
    Rule,
    apply_rule,
    dominated_by_simpler_rule,
    fixed_stake_metrics,
    jaccard_similarity,
    observed_odds,
)
from robin.patterns.search_space import generate_rules
from robin.patterns.temporal import (
    LeakageError,
    adversarial_leakage_scan,
    rolling_history_before_target,
    validate_conditions,
    validate_observation_cutoff,
)


def condition(
    feature: str,
    operator: ConditionOperator = ConditionOperator.EQ,
    value: object = "Ligue 1",
) -> PatternCondition:
    return PatternCondition(
        feature=feature,
        operator=operator,
        value=value,
        source="TEST_SOURCE",
        available_at="T_MINUS_60_MINUTES",
    )


def test_historical_evidence_can_never_be_called_validated() -> None:
    digest = rule_hash(
        market="1X2_HOME",
        selection="HOME",
        conditions=[condition("competition")],
    )
    with pytest.raises(ValidationError, match="HISTORICAL_EVIDENCE_CANNOT_VALIDATE"):
        PatternDefinition(
            pattern_id=pattern_id_from_hash(digest),
            competition_scope=["Ligue 1"],
            market="1X2_HOME",
            selection_definition="HOME",
            conditions=[condition("competition")],
            feature_cutoff="T_MINUS_60_MINUTES",
            odds_type="HISTORICAL_CLOSING_MARKET",
            discovery_scope={"preregistered": True},
            validation_scope={},
            status=PatternStatus.VALIDATED,
            evidence_scope=EvidenceScope.EXPOSED_HISTORICAL_OOS,
            code_revision="abc",
            dataset_hashes=["hash"],
            rule_hash=digest,
        )


def test_four_conditions_require_preregistration() -> None:
    conditions = [
        condition("competition"),
        condition("season", value=2024),
        condition("price_type", value="HISTORICAL_CLOSING_MARKET"),
        condition("market_margin_1x2", ConditionOperator.LE, 0.08),
    ]
    digest = rule_hash(
        market="1X2_HOME",
        selection="HOME",
        conditions=conditions,
    )
    with pytest.raises(ValidationError, match="PREREGISTRATION"):
        PatternDefinition(
            pattern_id=pattern_id_from_hash(digest),
            competition_scope=["Ligue 1"],
            market="1X2_HOME",
            selection_definition="HOME",
            conditions=conditions,
            feature_cutoff="T_MINUS_60_MINUTES",
            odds_type="HISTORICAL_CLOSING_MARKET",
            discovery_scope={},
            validation_scope={},
            code_revision="abc",
            dataset_hashes=["hash"],
            rule_hash=digest,
        )


def test_winner_loser_and_target_fields_fail_closed() -> None:
    assert adversarial_leakage_scan(
        ["winner_rank", "loser_aces", "home_goals", "future_odds"]
    ) == ["future_odds", "home_goals", "loser_aces", "winner_rank"]
    with pytest.raises(LeakageError, match="LEAKAGE_REJECTED"):
        validate_conditions([condition("winner_rank")], market="1X2_HOME")
    with pytest.raises(LeakageError, match="UNKNOWN_FEATURE"):
        validate_conditions([condition("random_feature")], market="1X2_HOME")


def test_rolling_history_excludes_target_and_future() -> None:
    target = datetime(2025, 1, 2, tzinfo=UTC)
    rows = [
        {"fixture": "past", "at": target - timedelta(days=1)},
        {"fixture": "target", "at": target},
        {"fixture": "future", "at": target + timedelta(days=1)},
    ]
    history = rolling_history_before_target(
        rows,
        target_time=target,
        time_field="at",
    )
    assert [row["fixture"] for row in history] == ["past"]


def test_observation_after_cutoff_is_rejected() -> None:
    cutoff = datetime(2025, 1, 1, 12, tzinfo=UTC)
    with pytest.raises(LeakageError, match="ODDS_AFTER_CUTOFF"):
        validate_observation_cutoff(
            {"observed_at": cutoff + timedelta(seconds=1)},
            cutoff_at=cutoff,
        )


def market_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "fixture_id": 1,
        "competition": "Ligue 1",
        "season": 2024,
        "match_date": "2025-01-01",
        "home_goals": 2,
        "away_goals": 0,
        "odds_home": 2.0,
        "odds_draw": 3.2,
        "odds_away": 4.0,
        "odds_over_25": 2.0,
        "odds_under_25": 1.9,
        "market_margin_1x2": 0.0625,
        "market_margin_totals": 0.026,
        "price_type": "HISTORICAL_CLOSING_MARKET",
        "totals_price_type": "HISTORICAL_CLOSING_MARKET",
        "observed_time_status": "SOURCE_PRICE_CLASS_ONLY",
    }
    row.update(overrides)
    return row


def test_roi_uses_only_observed_prices_and_positive_overround() -> None:
    row = market_row()
    assert observed_odds(row, "1X2_HOME") == 2.0
    assert observed_odds(market_row(market_margin_1x2=-0.07), "1X2_HOME") is None
    assert observed_odds(market_row(odds_home=None), "1X2_HOME") is None
    assert (
        observed_odds(
            market_row(observed_time_status="EXACT_BUT_UNSUPPORTED"),
            "1X2_HOME",
        )
        is None
    )
    metrics = fixed_stake_metrics([1.0, -1.0, -1.0], [2.0, 2.0, 2.0])
    assert metrics.turnover_units == 3.0
    assert metrics.profit_units == -1.0
    assert metrics.roi == pytest.approx(-1 / 3)
    assert metrics.max_drawdown_units == 2.0


def test_rule_hash_is_order_independent_and_tennis_fields_never_generated() -> None:
    first = condition("competition")
    second = condition(
        "market_margin_1x2",
        ConditionOperator.LE,
        0.08,
    )
    left = Rule("1X2_HOME", "HOME", (first, second))
    right = Rule("1X2_HOME", "HOME", (second, first))
    assert left.digest == right.digest
    rules = generate_rules([market_row()])
    assert rules
    assert not any(
        any(
            condition.feature.startswith(("winner_", "loser_", "w_", "l_"))
            for condition in rule.conditions
        )
        for rule in rules
    )


def test_deduplication_prefers_a_sufficient_simple_rule() -> None:
    simple = Rule(
        "1X2_HOME",
        "HOME",
        (condition("competition"),),
    )
    complex_rule = Rule(
        "1X2_HOME",
        "HOME",
        (
            condition("competition"),
            condition("market_margin_1x2", ConditionOperator.LE, 0.08),
        ),
    )
    assert jaccard_similarity(["1", "2"], ["1", "2", "3"]) == pytest.approx(2 / 3)
    assert (
        dominated_by_simpler_rule(
            candidate=complex_rule,
            candidate_roi=0.025,
            candidate_ids={"1", "2", "3"},
            accepted=[(simple, 0.02, {"1", "2", "3"})],
        )
        == "DOMINATED"
    )
    selected = apply_rule([market_row(), market_row(competition="Serie A")], simple)
    assert len(selected) == 1
