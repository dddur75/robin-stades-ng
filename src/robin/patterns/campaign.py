"""Campagne scientifique cache-only du Jalon 10."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from robin.patterns.contracts import (
    ConditionOperator,
    PatternCondition,
    PatternStatus,
    canonical_conditions,
)
from robin.patterns.engine import (
    Rule,
    apply_rule,
    canonical_selection_ids,
    dominated_by_simpler_rule,
    market_won,
    observed_odds,
)
from robin.patterns.search_space import generate_rules
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
from robin.patterns.temporal import (
    LeakageError,
    adversarial_leakage_scan,
    validate_conditions,
)


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    schema_version: str = "pattern-campaign-v1.1-review-hardening"
    seed: int = 10_010
    minimum_bets: int = 80
    minimum_seasons: int = 3
    minimum_fold_bets: int = 15
    minimum_positive_fold_ratio: float = 0.67
    fdr_alpha: float = 0.05
    bootstrap_iterations: int = 1_000
    bootstrap_candidates_limit: int = 40
    permutation_candidates_limit: int = 5
    exposed_stability_competitions: tuple[str, ...] = ("Bundesliga", "Serie A")
    live_market_point_in_time: bool = False
    feature_cutoff: str = "HISTORICAL_PRICE_CATEGORY_NO_EXACT_CUTOFF"
    odds_type: str = "HISTORICAL_CLOSING_OR_PRE_CLOSING_MARKET"
    provider_calls_allowed: int = 0
    social_publishing_enabled: bool = False
    preregistered_at: str = "2026-07-27T00:00:00+00:00"


def _difference_in_means(
    values: Sequence[float],
    labels: Sequence[int],
) -> float:
    selected = [
        value
        for value, label in zip(values, labels, strict=True)
        if label == 1
    ]
    other = [
        value
        for value, label in zip(values, labels, strict=True)
        if label == 0
    ]
    if not selected or not other:
        return 0.0
    return statistics.fmean(selected) - statistics.fmean(other)


def _rule_observations(
    rows: Sequence[Mapping[str, object]],
    rule: Rule,
) -> tuple[list[float], list[bool], list[str], list[int], list[float]]:
    profits: list[float] = []
    outcomes: list[bool] = []
    groups: list[str] = []
    seasons: list[int] = []
    odds_values: list[float] = []
    for row in apply_rule(rows, rule):
        odds = observed_odds(row, rule.market)
        won = market_won(row, rule.market)
        season = row.get("season")
        if odds is None or won is None or isinstance(season, bool):
            continue
        try:
            normalized_season = int(str(season))
        except ValueError:
            continue
        profits.append(odds - 1.0 if won else -1.0)
        outcomes.append(won)
        groups.append(str(row.get("match_date") or row.get("fixture_id")))
        seasons.append(normalized_season)
        odds_values.append(odds)
    return profits, outcomes, groups, seasons, odds_values


def _walk_forward_evidence(
    *,
    profits: Sequence[float],
    seasons: Sequence[int],
    minimum_fold_bets: int,
    minimum_positive_fold_ratio: float,
) -> dict[str, object]:
    try:
        folds = walk_forward_splits(seasons, minimum_train_periods=2)
    except ValueError:
        return {
            "folds": [],
            "eligible_folds": 0,
            "positive_folds": 0,
            "positive_ratio": 0.0,
            "survived": False,
        }
    evidence: list[dict[str, object]] = []
    for fold in folds:
        test_returns = [profits[index] for index in fold.test_indices]
        if len(test_returns) < minimum_fold_bets:
            continue
        roi = statistics.fmean(test_returns)
        evidence.append(
            {
                "test_period": fold.test_period,
                "bets": len(test_returns),
                "roi": roi,
                "positive": roi > 0.0,
                "train_periods": list(fold.train_periods),
            }
        )
    positives = sum(bool(fold["positive"]) for fold in evidence)
    ratio = positives / len(evidence) if evidence else 0.0
    survived = (
        len(evidence) >= 2
        and ratio >= minimum_positive_fold_ratio
        and bool(evidence[-1]["positive"])
    )
    return {
        "folds": evidence,
        "eligible_folds": len(evidence),
        "positive_folds": positives,
        "positive_ratio": ratio,
        "survived": survived,
    }


def _exposed_league_stability_evidence(
    rows: Sequence[Mapping[str, object]],
    rule: Rule,
    *,
    competitions: Sequence[str],
    minimum_bets: int,
) -> dict[str, object]:
    """Mesurer une stabilité descriptive, jamais une validation indépendante."""

    if any(condition.feature == "competition" for condition in rule.conditions):
        return {
            "eligible": False,
            "reason": "COMPETITION_SPECIFIC_RULE",
            "survived": False,
            "competitions": [],
            "independent": False,
            "evidence_scope": "DISCOVERY_EXPOSED",
        }
    results: list[dict[str, object]] = []
    for competition in competitions:
        subset = [
            row for row in rows if str(row.get("competition")) == competition
        ]
        profits, _, _, _, _ = _rule_observations(subset, rule)
        results.append(
            {
                "competition": competition,
                "bets": len(profits),
                "roi": statistics.fmean(profits) if profits else None,
                "positive": len(profits) >= minimum_bets
                and statistics.fmean(profits) > 0.0,
            }
        )
    return {
        "eligible": True,
        "competitions": results,
        "survived": bool(results) and all(bool(item["positive"]) for item in results),
        "independent": False,
        "evidence_scope": "DISCOVERY_EXPOSED",
        "reason": "EXPOSED_LEAGUE_STABILITY_ONLY",
    }


def _dataset_hash(rows: Sequence[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(
        rows,
        key=lambda item: (
            str(item.get("competition")),
            str(item.get("season")),
            str(item.get("fixture_id")),
        ),
    ):
        payload = json.dumps(
            dict(row),
            default=str,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(payload)
        digest.update(b"\n")
    return digest.hexdigest()


def _stratified_label_shuffle(
    rows: Sequence[Mapping[str, object]],
    *,
    market: str,
    seed: int,
) -> tuple[list[float], list[bool], int, list[str]]:
    """Mélange sans casser la relation structurelle entre prix et fréquence."""

    odds_values: list[float] = []
    outcomes: list[bool] = []
    cluster_groups: list[str] = []
    strata: dict[tuple[str, str, int], list[int]] = {}
    for row in rows:
        odds = observed_odds(row, market)
        won = market_won(row, market)
        if odds is None or won is None:
            continue
        position = len(odds_values)
        odds_values.append(odds)
        outcomes.append(won)
        cluster_groups.append(str(row.get("match_date") or row.get("fixture_id")))
        key = (
            str(row.get("competition")),
            str(row.get("season")),
            int(odds / 0.25),
        )
        strata.setdefault(key, []).append(position)
    shuffled = list(outcomes)
    for offset, key in enumerate(sorted(strata)):
        positions = strata[key]
        labels = shuffle_labels(
            [outcomes[position] for position in positions],
            seed=seed + offset,
        )
        for position, label in zip(positions, labels, strict=True):
            shuffled[position] = label
    return odds_values, shuffled, len(strata), cluster_groups


def _validate_fixture_alignment(
    expected_fixture_ids: Sequence[str],
    observed_fixture_ids: Sequence[str],
) -> None:
    """Fail closed when market prices are joined to another fixture."""

    if len(expected_fixture_ids) != len(observed_fixture_ids) or any(
        expected != observed
        for expected, observed in zip(
            expected_fixture_ids,
            observed_fixture_ids,
            strict=True,
        )
    ):
        raise LeakageError("FIXTURE_ODDS_JOIN_MISMATCH")


def _rejected_condition(
    feature: str,
    *,
    source: str = "ADVERSARIAL_NEGATIVE_CONTROL",
) -> tuple[bool, str | None]:
    """Execute the temporal registry against an intentionally invalid feature."""

    condition = PatternCondition(
        feature=feature,
        operator=ConditionOperator.EQ,
        value="CONTROL",
        source=source,
        available_at="AFTER_KICKOFF_OR_UNKNOWN",
    )
    try:
        validate_conditions([condition], market="1X2_HOME")
    except LeakageError as exc:
        return True, str(exc)
    return False, None


def _concentration_evidence(
    rows: Sequence[Mapping[str, object]],
    rule: Rule,
) -> dict[str, object]:
    """Measure available concentration dimensions and keep the V1 gate closed."""

    selected = [
        row
        for row in apply_rule(rows, rule)
        if observed_odds(row, rule.market) is not None
    ]
    bookmaker_field = (
        "bookmaker_totals" if rule.market.startswith("TOTAL_") else "bookmaker_1x2"
    )
    bookmaker_values = [
        str(row[bookmaker_field])
        for row in selected
        if row.get(bookmaker_field) not in (None, "")
    ]
    team_values = [
        str(team)
        for row in selected
        for team in (row.get("home_team_id"), row.get("away_team_id"))
        if team not in (None, "")
    ]
    season_values = [
        str(row["season"])
        for row in selected
        if row.get("season") not in (None, "")
    ]
    complete_bookmakers = len(bookmaker_values) == len(selected)
    complete_teams = len(team_values) == len(selected) * 2
    measured = bool(selected) and complete_bookmakers and complete_teams
    return {
        "selected_fixtures": len(selected),
        "bookmaker_field": bookmaker_field,
        "bookmaker_values_present": len(bookmaker_values),
        "distinct_bookmakers": len(set(bookmaker_values)),
        "team_values_present": len(team_values),
        "distinct_teams": len(set(team_values)),
        "distinct_seasons": len(set(season_values)),
        "measured": measured,
        "passed": False,
        "reason": (
            "V1_CONCENTRATION_THRESHOLDS_NOT_PREREGISTERED"
            if measured
            else "TEAM_OR_BOOKMAKER_CONCENTRATION_NOT_MEASURABLE"
        ),
    }


def _historical_promotion_gate_passes(
    evaluation: Mapping[str, object],
    *,
    alpha: float,
) -> bool:
    """Apply every V1 promotion gate; missing evidence always fails closed."""

    metrics = evaluation.get("metrics")
    bootstrap = evaluation.get("bootstrap")
    permutation = evaluation.get("permutation")
    concentration = evaluation.get("concentration")
    return (
        isinstance(metrics, Mapping)
        and float(metrics.get("roi", 0.0)) > 0.0
        and float(str(evaluation.get("q_value", 1.0))) <= alpha
        and isinstance(bootstrap, Mapping)
        and float(bootstrap.get("lower", 0.0)) > 0.0
        and isinstance(permutation, Mapping)
        and int(permutation.get("permutations", 0)) >= 100
        and float(permutation.get("p_value", 1.0)) <= alpha
        and isinstance(concentration, Mapping)
        and concentration.get("passed") is True
    )


def run_campaign(
    rows: Sequence[Mapping[str, object]],
    *,
    code_revision: str,
    config: CampaignConfig | None = None,
) -> dict[str, object]:
    """Exécute toutes les hypothèses préenregistrées et conserve les négatives."""

    active_config = config or CampaignConfig()
    if active_config.provider_calls_allowed != 0:
        raise ValueError("PATTERN_CAMPAIGN_MUST_BE_CACHE_ONLY")
    if active_config.social_publishing_enabled:
        raise ValueError("SOCIAL_PUBLISHING_MUST_REMAIN_DISABLED")
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("kickoff_at") or row.get("match_date")),
            str(row.get("fixture_id")),
        ),
    )
    dataset_hash = _dataset_hash(ordered_rows)
    rules = generate_rules(ordered_rows)
    evaluations: list[dict[str, Any]] = []
    raw_series: dict[str, tuple[list[float], list[str], list[int], list[float]]] = {}
    for rule in rules:
        try:
            profits, outcomes, groups, seasons, odds_values = _rule_observations(
                ordered_rows, rule
            )
        except LeakageError:
            evaluations.append(
                {
                    "rule_hash": rule.digest,
                    "market": rule.market,
                    "selection": rule.selection,
                    "conditions": canonical_conditions(list(rule.conditions)),
                    "status": PatternStatus.LEAKAGE_REJECTED.value,
                    "p_value": 1.0,
                    "q_value": 1.0,
                }
            )
            continue
        support = assess_support(
            len(profits),
            [str(season) for season in seasons],
            minimum_observations=active_config.minimum_bets,
            minimum_groups=active_config.minimum_seasons,
        )
        financial_metrics = (
            flat_stake_metrics(odds_values, outcomes)
            if odds_values
            else None
        )
        perfect = (
            detect_perfect_performance(financial_metrics)
            if financial_metrics is not None
            else None
        )
        p_value = (
            clustered_positive_mean_p_value(profits, groups)
            if support.sufficient and perfect is not None and not perfect.suspicious
            else 1.0
        )
        status = (
            PatternStatus.DISCOVERED.value
            if support.sufficient
            else PatternStatus.INSUFFICIENT_SUPPORT.value
        )
        evaluation: dict[str, Any] = {
            "rule_hash": rule.digest,
            "market": rule.market,
            "selection": rule.selection,
            "conditions": canonical_conditions(list(rule.conditions)),
            "condition_count": len(rule.conditions),
            "status": status,
            "evidence_scope": "DISCOVERY_EXPOSED",
            "support": asdict(support),
            "metrics": (
                asdict(financial_metrics)
                if financial_metrics is not None
                else None
            ),
            "perfect_performance": asdict(perfect) if perfect is not None else None,
            "p_value": p_value,
            "q_value": 1.0,
            "bootstrap": None,
            "walk_forward": None,
            "exposed_league_stability": None,
            "permutation": None,
            "concentration": None,
            "live_point_in_time_usable": False,
        }
        evaluations.append(evaluation)
        raw_series[rule.digest] = (profits, groups, seasons, odds_values)

    fdr = benjamini_hochberg(
        [float(evaluation["p_value"]) for evaluation in evaluations],
        alpha=active_config.fdr_alpha,
    )
    for evaluation, q_value in zip(evaluations, fdr.q_values, strict=True):
        evaluation["q_value"] = q_value

    bootstrap_targets = sorted(
        (
            evaluation
            for evaluation in evaluations
            if evaluation["status"] == PatternStatus.DISCOVERED.value
            and isinstance(evaluation.get("metrics"), dict)
            and float(evaluation["metrics"]["roi"]) > 0.0
        ),
        key=lambda item: (
            float(item["q_value"]),
            -float(item["metrics"]["roi"]),
            str(item["rule_hash"]),
        ),
    )[: active_config.bootstrap_candidates_limit]

    rule_by_hash = {rule.digest: rule for rule in rules}
    for evaluation in bootstrap_targets:
        digest = str(evaluation["rule_hash"])
        profits, groups, seasons, _ = raw_series[digest]
        if len(set(groups)) >= 2:
            evaluation["bootstrap"] = asdict(
                grouped_bootstrap_mean(
                    profits,
                    groups,
                    iterations=active_config.bootstrap_iterations,
                    seed=active_config.seed,
                )
            )
        evaluation["walk_forward"] = _walk_forward_evidence(
            profits=profits,
            seasons=seasons,
            minimum_fold_bets=active_config.minimum_fold_bets,
            minimum_positive_fold_ratio=active_config.minimum_positive_fold_ratio,
        )
        evaluation["exposed_league_stability"] = _exposed_league_stability_evidence(
            ordered_rows,
            rule_by_hash[digest],
            competitions=active_config.exposed_stability_competitions,
            minimum_bets=max(20, active_config.minimum_bets // 2),
        )
        evaluation["concentration"] = _concentration_evidence(
            ordered_rows,
            rule_by_hash[digest],
        )

    permutation_targets = bootstrap_targets[: active_config.permutation_candidates_limit]
    for offset, evaluation in enumerate(permutation_targets):
        digest = str(evaluation["rule_hash"])
        rule = rule_by_hash[digest]
        all_market_returns: list[float] = []
        selection_labels: list[int] = []
        selected_ids = canonical_selection_ids(ordered_rows, rule)
        for row in ordered_rows:
            odds = observed_odds(row, rule.market)
            won = market_won(row, rule.market)
            if odds is None or won is None:
                continue
            all_market_returns.append(odds - 1.0 if won else -1.0)
            selection_labels.append(
                1 if str(row.get("fixture_id")) in selected_ids else 0
            )
        if (
            len(set(selection_labels)) == 2
            and len(all_market_returns) == len(selection_labels)
        ):
            evaluation["permutation"] = asdict(
                permutation_test(
                    all_market_returns,
                    selection_labels,
                    _difference_in_means,
                    permutations=100,
                    seed=active_config.seed + offset,
                )
            )

    accepted_simple: list[tuple[Rule, float, frozenset[str]]] = []
    for evaluation in sorted(
        evaluations,
        key=lambda item: (
            int(item.get("condition_count", 99)),
            str(item["rule_hash"]),
        ),
    ):
        metrics_payload = evaluation.get("metrics")
        walk_forward = evaluation.get("walk_forward")
        exposed_stability = evaluation.get("exposed_league_stability")
        permutation = evaluation.get("permutation")
        if not isinstance(metrics_payload, dict):
            continue
        rule = rule_by_hash[str(evaluation["rule_hash"])]
        roi = float(metrics_payload["roi"])
        ids = canonical_selection_ids(ordered_rows, rule)
        dominated = dominated_by_simpler_rule(
            candidate=rule,
            candidate_roi=roi,
            candidate_ids=ids,
            accepted=accepted_simple,
        )
        if dominated is not None:
            evaluation["status"] = PatternStatus.DOMINATED.value
            continue
        walk_forward_survivor = (
            isinstance(walk_forward, dict) and bool(walk_forward["survived"])
        )
        permutation_survivor = (
            isinstance(permutation, dict)
            and int(permutation.get("permutations", 0)) >= 100
            and float(permutation.get("p_value", 1.0)) <= active_config.fdr_alpha
        )
        evaluation["permutation_gate_passed"] = permutation_survivor
        concentration = evaluation.get("concentration")
        evaluation["concentration_gate_passed"] = (
            isinstance(concentration, dict)
            and concentration.get("passed") is True
        )
        if _historical_promotion_gate_passes(
            evaluation,
            alpha=active_config.fdr_alpha,
        ):
            evaluation["status"] = PatternStatus.HISTORICAL_CANDIDATE.value
            accepted_simple.append((rule, roi, ids))
        if (
            evaluation["status"] == PatternStatus.HISTORICAL_CANDIDATE.value
            and walk_forward_survivor
        ):
            # The rule was ranked on the full exposed corpus. These folds are
            # descriptive stability evidence, not nested OOS selection.
            evaluation["exposed_temporal_stability_passed"] = True
        # Le contrôle par ligue réutilise le corpus exposé. Il ne peut donc
        # jamais attribuer EXTERNAL_LEAGUE_SURVIVOR.
        if isinstance(exposed_stability, dict):
            evaluation["exposed_league_stability_passed"] = bool(
                exposed_stability.get("survived")
            )
        # Le gate live reste fermé : SOURCE_PRICE_CLASS_ONLY n'a pas
        # d'observed_at exact et ses conditions ne sont pas live-compatibles.
        if (
            evaluation["status"] == PatternStatus.EXTERNAL_LEAGUE_SURVIVOR.value
            and active_config.live_market_point_in_time
        ):
            try:
                validate_conditions(
                    rule.conditions,
                    market=rule.market,
                    require_live_usable=True,
                )
            except LeakageError:
                evaluation["live_point_in_time_usable"] = False
            else:
                evaluation["status"] = PatternStatus.LIVE_SHADOW_CANDIDATE.value
                evaluation["live_point_in_time_usable"] = True

    (
        base_odds,
        shuffled_outcomes,
        shuffled_strata,
        shuffled_groups,
    ) = _stratified_label_shuffle(
        ordered_rows,
        market="1X2_HOME",
        seed=active_config.seed,
    )
    shuffled_metrics = (
        flat_stake_metrics(base_odds, shuffled_outcomes)
        if base_odds
        else None
    )
    shuffled_returns = [
        odds - 1.0 if won else -1.0
        for odds, won in zip(base_odds, shuffled_outcomes, strict=True)
    ]
    shuffled_p_value = (
        clustered_positive_mean_p_value(shuffled_returns, shuffled_groups)
        if shuffled_returns
        else 1.0
    )
    shuffled_false_edge = (
        shuffled_metrics is not None
        and shuffled_metrics.roi > 0.0
        and shuffled_p_value <= active_config.fdr_alpha
    )
    trivial_outcomes: list[bool] = []
    trivial_odds: list[float] = []
    trivial_groups: list[str] = []
    for row in ordered_rows:
        odds = observed_odds(row, "1X2_HOME")
        won = market_won(row, "1X2_HOME")
        if odds is not None and won is not None:
            trivial_odds.append(odds)
            trivial_outcomes.append(won)
            trivial_groups.append(
                str(row.get("match_date") or row.get("fixture_id"))
            )
    trivial_metrics = (
        flat_stake_metrics(trivial_odds, trivial_outcomes)
        if trivial_odds
        else None
    )
    trivial_returns = [
        odds - 1.0 if won else -1.0
        for odds, won in zip(trivial_odds, trivial_outcomes, strict=True)
    ]
    trivial_p_value = (
        clustered_positive_mean_p_value(trivial_returns, trivial_groups)
        if trivial_returns
        else 1.0
    )
    trivial_false_edge = (
        trivial_metrics is not None
        and trivial_metrics.roi > 0.0
        and trivial_p_value <= active_config.fdr_alpha
    )

    leakage_features = ("winner_rank", "loser_aces", "home_goals", "future_odds")
    leakage_results = {
        feature: _rejected_condition(feature)
        for feature in leakage_features
    }
    random_rejected, random_reason = _rejected_condition("random_feature")
    post_result_rejected, post_result_reason = _rejected_condition("home_goals")

    eligible_fixture_ids = [
        str(row.get("fixture_id"))
        for row in ordered_rows
        if observed_odds(row, "1X2_HOME") is not None
    ]
    shifted_fixture_ids = (
        eligible_fixture_ids[1:] + eligible_fixture_ids[:1]
        if len(eligible_fixture_ids) > 1
        else list(eligible_fixture_ids)
    )
    shifted_rejected = False
    shifted_reason: str | None = None
    try:
        _validate_fixture_alignment(eligible_fixture_ids, shifted_fixture_ids)
    except LeakageError as exc:
        shifted_rejected = True
        shifted_reason = str(exc)

    impossible_condition = PatternCondition(
        feature="season",
        operator=ConditionOperator.EQ,
        value="__IMPOSSIBLE_SEASON__",
        source="API_FOOTBALL_FIXTURE",
        available_at="FIXTURE_PUBLICATION",
    )
    impossible_rule = Rule(
        market="1X2_HOME",
        selection="HOME",
        conditions=(impossible_condition,),
    )
    impossible_selected = len(apply_rule(ordered_rows, impossible_rule))
    negative_controls = {
        "winner_loser_leakage": {
            "executed": True,
            "rejected_columns": adversarial_leakage_scan(leakage_features),
            "rejection_reasons": {
                feature: reason
                for feature, (rejected, reason) in leakage_results.items()
                if rejected and reason is not None
            },
            "promoted": False,
            "passed": all(rejected for rejected, _ in leakage_results.values()),
        },
        "shuffled_labels": {
            "executed": True,
            "method": "STRATIFIED_BY_COMPETITION_SEASON_ODDS_BAND",
            "strata": shuffled_strata,
            "metrics": asdict(shuffled_metrics) if shuffled_metrics is not None else None,
            "p_value": shuffled_p_value,
            "status": PatternStatus.REJECTED.value,
            "rejection_reason": "PREREGISTERED_NEGATIVE_CONTROL",
            "promoted": False,
            "passed": not shuffled_false_edge,
        },
        "shifted_odds": {
            "executed": True,
            "status": PatternStatus.LEAKAGE_REJECTED.value,
            "rejection_reason": shifted_reason,
            "promoted": False,
            "passed": shifted_rejected,
        },
        "random_feature": {
            "executed": True,
            "status": PatternStatus.REJECTED.value,
            "rejection_reason": random_reason,
            "promoted": False,
            "passed": random_rejected,
        },
        "trivial_market_rule": {
            "executed": True,
            "description": "BET_HOME_ON_EVERY_ELIGIBLE_FIXTURE",
            "metrics": asdict(trivial_metrics) if trivial_metrics is not None else None,
            "p_value": trivial_p_value,
            "status": PatternStatus.REJECTED.value,
            "rejection_reason": "PREREGISTERED_NEGATIVE_CONTROL",
            "promoted": False,
            "passed": not trivial_false_edge,
        },
        "impossible_condition": {
            "executed": True,
            "selected": impossible_selected,
            "promoted": False,
            "passed": impossible_selected == 0,
        },
        "post_result_pattern": {
            "executed": True,
            "status": PatternStatus.LEAKAGE_REJECTED.value,
            "rejection_reason": post_result_reason,
            "promoted": False,
            "passed": post_result_rejected,
        },
    }
    counts = {
        "hypotheses_generated": len(rules),
        "hypotheses_executed": len(evaluations),
        "leakage_rejected": sum(
            item["status"] == PatternStatus.LEAKAGE_REJECTED.value
            for item in evaluations
        ),
        "support_rejected": sum(
            item["status"] == PatternStatus.INSUFFICIENT_SUPPORT.value
            for item in evaluations
        ),
        "raw_positive": sum(
            isinstance(item.get("metrics"), dict)
            and float(item["metrics"]["roi"]) > 0.0
            for item in evaluations
        ),
        "fdr_survivors": sum(
            float(item["q_value"]) <= active_config.fdr_alpha
            for item in evaluations
        ),
        "walk_forward_survivors": sum(
            isinstance(item.get("walk_forward"), dict)
            and bool(item["walk_forward"]["survived"])
            for item in evaluations
        ),
        "external_league_survivors": sum(
            item["status"] == PatternStatus.EXTERNAL_LEAGUE_SURVIVOR.value
            for item in evaluations
        ),
        "exposed_league_stability_survivors": sum(
            isinstance(item.get("exposed_league_stability"), dict)
            and bool(item["exposed_league_stability"].get("survived"))
            for item in evaluations
        ),
        "shadow_candidates": sum(
            item["status"] == PatternStatus.LIVE_SHADOW_CANDIDATE.value
            for item in evaluations
        ),
        "negative_controls": len(negative_controls),
        "negative_controls_passed": sum(
            isinstance(control, dict) and control.get("passed") is True
            for control in negative_controls.values()
        ),
    }
    stable_payload: dict[str, object] = {
        "schema_version": active_config.schema_version,
        "config": asdict(active_config),
        "p_value_method": "ONE_SIDED_CLUSTER_ROBUST_CR1_BY_MATCH_DATE",
        "multiple_testing_method": "BENJAMINI_HOCHBERG_FULL_FROZEN_FAMILY",
        "multiple_testing_dependence_caveat": (
            "OVERLAPPING_RULES_NOT_PROVEN_INDEPENDENT_OR_PRDS;"
            "PROMOTION_REMAINS_FAIL_CLOSED"
        ),
        "code_revision": code_revision,
        "dataset_hashes": [dataset_hash],
        "data_classification": "DISCOVERY_EXPOSED",
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "scope_subverdict": (
            "NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE"
        ),
        "counts": counts,
        "negative_controls": negative_controls,
        "hypotheses": evaluations,
    }
    result_hash = hashlib.sha256(
        json.dumps(
            stable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        **stable_payload,
        "result_hash": result_hash,
        "checkpoint": {
            "status": "COMPLETE",
            "rules_completed": len(evaluations),
            "last_rule_hash": (
                str(evaluations[-1]["rule_hash"]) if evaluations else None
            ),
            "result_hash": result_hash,
        },
        "verdict": (
            "JALON_10_SCIENTIFIC_VALIDATION_FAILED"
            if counts["negative_controls_passed"] != counts["negative_controls"]
            else (
                "JALON_10_NO_ROBUST_PATTERN_FOUND"
                if counts["shadow_candidates"] == 0
                else "JALON_10_PATTERN_ENGINE_READY"
            )
        ),
    }
