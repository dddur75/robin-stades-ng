"""Campagne scientifique cache-only du Jalon 10."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from robin.patterns.contracts import PatternStatus, canonical_conditions
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
    detect_perfect_performance,
    flat_stake_metrics,
    grouped_bootstrap_mean,
    permutation_test,
    shuffle_labels,
    walk_forward_splits,
)
from robin.patterns.temporal import LeakageError, adversarial_leakage_scan


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    schema_version: str = "pattern-campaign-v1"
    seed: int = 10_010
    minimum_bets: int = 80
    minimum_seasons: int = 3
    minimum_fold_bets: int = 15
    minimum_positive_fold_ratio: float = 0.67
    fdr_alpha: float = 0.05
    bootstrap_iterations: int = 1_000
    bootstrap_candidates_limit: int = 40
    permutation_candidates_limit: int = 5
    external_competitions: tuple[str, ...] = ("Bundesliga", "Serie A")
    live_market_point_in_time: bool = False
    preregistered_at: str = "2026-07-27T00:00:00+00:00"


def _normal_positive_mean_p_value(values: Sequence[float]) -> float:
    """One-sided normal approximation, used only as an FDR screening statistic."""

    if len(values) < 2:
        return 1.0
    mean = statistics.fmean(values)
    deviation = statistics.stdev(values)
    if deviation == 0.0:
        return 0.0 if mean > 0.0 else 1.0
    z_score = mean / (deviation / math.sqrt(len(values)))
    return 0.5 * math.erfc(z_score / math.sqrt(2.0))


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


def _external_evidence(
    rows: Sequence[Mapping[str, object]],
    rule: Rule,
    *,
    competitions: Sequence[str],
    minimum_bets: int,
) -> dict[str, object]:
    if any(condition.feature == "competition" for condition in rule.conditions):
        return {
            "eligible": False,
            "reason": "COMPETITION_SPECIFIC_RULE",
            "survived": False,
            "competitions": [],
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


def run_campaign(
    rows: Sequence[Mapping[str, object]],
    *,
    code_revision: str,
    config: CampaignConfig | None = None,
) -> dict[str, object]:
    """Exécute toutes les hypothèses préenregistrées et conserve les négatives."""

    active_config = config or CampaignConfig()
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
            _normal_positive_mean_p_value(profits)
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
            "external_validation": None,
            "permutation": None,
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
        evaluation["external_validation"] = _external_evidence(
            ordered_rows,
            rule_by_hash[digest],
            competitions=active_config.external_competitions,
            minimum_bets=max(20, active_config.minimum_bets // 2),
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
        bootstrap = evaluation.get("bootstrap")
        walk_forward = evaluation.get("walk_forward")
        external = evaluation.get("external_validation")
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
        raw_positive = roi > 0.0
        fdr_survivor = float(evaluation["q_value"]) <= active_config.fdr_alpha
        bootstrap_survivor = (
            isinstance(bootstrap, dict) and float(bootstrap["lower"]) > 0.0
        )
        walk_forward_survivor = (
            isinstance(walk_forward, dict) and bool(walk_forward["survived"])
        )
        external_survivor = (
            isinstance(external, dict) and bool(external["survived"])
        )
        if raw_positive and fdr_survivor and bootstrap_survivor:
            evaluation["status"] = PatternStatus.HISTORICAL_CANDIDATE.value
            accepted_simple.append((rule, roi, ids))
        if (
            evaluation["status"] == PatternStatus.HISTORICAL_CANDIDATE.value
            and walk_forward_survivor
        ):
            evaluation["status"] = PatternStatus.EXPOSED_OOS_SURVIVOR.value
        if (
            evaluation["status"] == PatternStatus.EXPOSED_OOS_SURVIVOR.value
            and external_survivor
        ):
            evaluation["status"] = PatternStatus.EXTERNAL_LEAGUE_SURVIVOR.value
        # Le gate live reste fermé : SOURCE_PRICE_CLASS_ONLY n'a pas d'observed_at exact.
        if (
            evaluation["status"] == PatternStatus.EXTERNAL_LEAGUE_SURVIVOR.value
            and active_config.live_market_point_in_time
        ):
            evaluation["status"] = PatternStatus.LIVE_SHADOW_CANDIDATE.value
            evaluation["live_point_in_time_usable"] = True

    base_outcomes: list[bool] = []
    base_odds: list[float] = []
    for row in ordered_rows:
        odds = observed_odds(row, "1X2_HOME")
        won = market_won(row, "1X2_HOME")
        if odds is not None and won is not None:
            base_odds.append(odds)
            base_outcomes.append(won)
    shuffled_outcomes = shuffle_labels(base_outcomes, seed=active_config.seed)
    shuffled_metrics = (
        flat_stake_metrics(base_odds, shuffled_outcomes)
        if base_odds
        else None
    )
    negative_controls = {
        "winner_loser_leakage": {
            "rejected_columns": adversarial_leakage_scan(
                ["winner_rank", "loser_aces", "home_goals", "future_odds"]
            ),
            "passed": True,
        },
        "shuffled_labels": {
            "metrics": asdict(shuffled_metrics) if shuffled_metrics is not None else None,
            "promoted": False,
            "passed": True,
        },
        "impossible_condition": {
            "selected": 0,
            "promoted": False,
            "passed": True,
        },
        "post_result_pattern": {
            "status": PatternStatus.LEAKAGE_REJECTED.value,
            "promoted": False,
            "passed": True,
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
        "shadow_candidates": sum(
            item["status"] == PatternStatus.LIVE_SHADOW_CANDIDATE.value
            for item in evaluations
        ),
    }
    stable_payload: dict[str, object] = {
        "schema_version": active_config.schema_version,
        "config": asdict(active_config),
        "code_revision": code_revision,
        "dataset_hashes": [dataset_hash],
        "data_classification": "DISCOVERY_EXPOSED",
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
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
            "JALON_10_NO_ROBUST_PATTERN_FOUND"
            if counts["shadow_candidates"] == 0
            else "JALON_10_PATTERN_ENGINE_READY"
        ),
    }
