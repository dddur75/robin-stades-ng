"""Jalon 11 statistical controls layered on the shared Jalon 10 primitives."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from robin.patterns.statistics import (
    MultipleTestingResult,
    benjamini_hochberg,
    clustered_positive_mean_p_value,
)


@dataclass(frozen=True, slots=True)
class FamilyCorrection:
    family_results: dict[str, MultipleTestingResult]
    global_result: MultipleTestingResult
    ordered_hypotheses: tuple[str, ...]
    family_q_values: dict[str, float]
    global_q_values: dict[str, float]


def impossible_outcome_control(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate a zero-support categorical impossibility over every row."""

    support = sum(
        1
        for row in rows
        if str(row.get("outcome")) == "HOME"
        and str(row.get("outcome")) == "AWAY"
    )
    return {
        "status": (
            "EXECUTED_ZERO_SUPPORT_NO_PROMOTION"
            if support == 0
            else "FAILED_IMPOSSIBLE_CONDITION_NONZERO"
        ),
        "support": support,
        "rows_examined": len(rows),
        "predicate": "OUTCOME_IS_HOME_AND_AWAY",
        "promotion_eligible": False,
    }


def family_and_global_bh(
    hypotheses: Sequence[Mapping[str, object]],
    *,
    alpha: float = 0.05,
) -> FamilyCorrection:
    """Include blocked hypotheses as p=1 in their preregistered families."""

    ordered = sorted(
        hypotheses,
        key=lambda item: (str(item.get("family")), str(item.get("hypothesis_id"))),
    )
    identifiers: list[str] = []
    p_values: list[float] = []
    by_family: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for hypothesis in ordered:
        identifier = str(hypothesis.get("hypothesis_id"))
        family = str(hypothesis.get("family"))
        raw = hypothesis.get("p_value")
        eligible = hypothesis.get("eligible") is True
        p_value = float(str(raw)) if eligible and raw is not None else 1.0
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError(f"INVALID_P_VALUE:{identifier}")
        identifiers.append(identifier)
        p_values.append(p_value)
        by_family[family].append((identifier, p_value))
    family_results: dict[str, MultipleTestingResult] = {}
    family_q_values: dict[str, float] = {}
    for family, values in sorted(by_family.items()):
        result = benjamini_hochberg(
            [p_value for _, p_value in values],
            alpha=alpha,
        )
        family_results[family] = result
        family_q_values.update(
            {
                identifier: q_value
                for (identifier, _), q_value in zip(
                    values,
                    result.q_values,
                    strict=True,
                )
            }
        )
    global_result = benjamini_hochberg(p_values, alpha=alpha)
    return FamilyCorrection(
        family_results=family_results,
        global_result=global_result,
        ordered_hypotheses=tuple(identifiers),
        family_q_values=family_q_values,
        global_q_values=dict(
            zip(identifiers, global_result.q_values, strict=True)
        ),
    )


def strict_cluster_p_value(
    values: Sequence[float],
    groups: Sequence[str],
    *,
    minimum_clusters: int = 30,
) -> float:
    if len(values) != len(groups):
        raise ValueError("CLUSTER_LENGTH_MISMATCH")
    normalized_groups = tuple(str(group).strip() for group in groups)
    if any(not group for group in normalized_groups):
        raise ValueError("CLUSTER_KEY_MISSING")
    if len(set(normalized_groups)) < minimum_clusters:
        return 1.0
    return clustered_positive_mean_p_value(values, normalized_groups)


def concentration_report(
    returns: Sequence[float],
    teams: Sequence[str],
    seasons: Sequence[str],
    leagues: Sequence[str],
) -> dict[str, object]:
    lengths = {len(returns), len(teams), len(seasons), len(leagues)}
    if len(lengths) != 1:
        raise ValueError("CONCENTRATION_LENGTH_MISMATCH")
    positive_total = sum(max(value, 0.0) for value in returns)

    def shares(groups: Sequence[str]) -> list[float]:
        by_group: dict[str, float] = defaultdict(float)
        for group, value in zip(groups, returns, strict=True):
            by_group[str(group)] += max(value, 0.0)
        if positive_total <= 0.0:
            return [0.0 for _ in by_group]
        return sorted(
            (value / positive_total for value in by_group.values()),
            reverse=True,
        )

    team_shares = shares(teams)
    season_shares = shares(seasons)
    league_shares = shares(leagues)
    match_shares = sorted(
        (
            max(value, 0.0) / positive_total if positive_total > 0.0 else 0.0
            for value in returns
        ),
        reverse=True,
    )
    return {
        "positive_profit_units": positive_total,
        "top_team_share": team_shares[0] if team_shares else 0.0,
        "top_three_team_share": sum(team_shares[:3]),
        "top_season_share": season_shares[0] if season_shares else 0.0,
        "top_league_share": league_shares[0] if league_shares else 0.0,
        "top_ten_match_share": sum(match_shares[:10]),
    }


def leave_one_group_out_direction(
    values: Sequence[float],
    groups: Sequence[str],
) -> dict[str, object]:
    if len(values) != len(groups) or not values:
        raise ValueError("LEAVE_ONE_GROUP_INPUT_INVALID")
    unique = sorted(set(groups))
    estimates: dict[str, float] = {}
    for excluded in unique:
        retained = [
            value
            for value, group in zip(values, groups, strict=True)
            if group != excluded
        ]
        estimates[excluded] = sum(retained) / len(retained) if retained else 0.0
    return {
        "groups": len(unique),
        "estimates": estimates,
        "direction_preserved": bool(estimates)
        and all(value > 0.0 for value in estimates.values()),
    }
