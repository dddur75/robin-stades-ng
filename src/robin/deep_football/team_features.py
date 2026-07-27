"""Strictly chronological team and calendar features."""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TeamMatch:
    fixture_id: str
    kickoff_at: datetime
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int


@dataclass(frozen=True, slots=True)
class CoachObservation:
    team_id: str
    coach_id: str
    effective_from: datetime
    observed_at: datetime


def coach_tenure_before(
    observations: Iterable[CoachObservation],
    prior_team_matches: Iterable[TeamMatch],
    *,
    team_id: str,
    target_kickoff: datetime,
) -> dict[str, object]:
    eligible = sorted(
        (
            item
            for item in observations
            if item.team_id == team_id
            and item.effective_from < target_kickoff
            and item.observed_at < target_kickoff
        ),
        key=lambda item: (item.effective_from, item.coach_id),
    )
    if not eligible:
        return {
            "coach_id": None,
            "matches_since_change": None,
            "recent_change": None,
        }
    current = eligible[-1]
    matches = sum(
        match.kickoff_at < target_kickoff
        and match.kickoff_at >= current.effective_from
        and team_id in {match.home_team, match.away_team}
        for match in prior_team_matches
    )
    return {
        "coach_id": current.coach_id,
        "matches_since_change": matches,
        "recent_change": matches <= 5,
    }


def _mean(values: Iterable[float]) -> float | None:
    normalized = tuple(values)
    return statistics.fmean(normalized) if normalized else None


def build_team_prematch_features(
    matches: Iterable[TeamMatch],
    *,
    windows: tuple[int, ...] = (3, 5, 10),
) -> list[dict[str, object]]:
    """Build each row before appending the target fixture to any history."""

    if tuple(sorted(set(windows))) != windows or any(window <= 0 for window in windows):
        raise ValueError("TEAM_WINDOWS_MUST_BE_SORTED_POSITIVE_UNIQUE")
    histories: dict[str, deque[tuple[datetime, int, int, int]]] = defaultdict(
        lambda: deque(maxlen=max(windows))
    )
    output: list[dict[str, object]] = []
    ordered = sorted(matches, key=lambda match: (match.kickoff_at, match.fixture_id))
    seen: set[str] = set()
    for match in ordered:
        if match.fixture_id in seen:
            raise ValueError("DUPLICATE_FIXTURE")
        seen.add(match.fixture_id)
        home_history = histories[match.home_team]
        away_history = histories[match.away_team]
        if any(
            history and history[-1][0] >= match.kickoff_at
            for history in (home_history, away_history)
        ):
            raise ValueError("TEAM_HISTORY_NOT_STRICTLY_BEFORE_TARGET")
        row: dict[str, object] = {
            "fixture_id": match.fixture_id,
            "kickoff_at": match.kickoff_at.isoformat(),
            "home_team": match.home_team,
            "away_team": match.away_team,
            "feature_cutoff": "STRICTLY_BEFORE_TARGET_KICKOFF",
        }
        for side, history in (("home", home_history), ("away", away_history)):
            previous_at = history[-1][0] if history else None
            row[f"{side}_rest_days"] = (
                (match.kickoff_at - previous_at).total_seconds() / 86_400
                if previous_at is not None
                else None
            )
            row[f"{side}_matches_7d"] = sum(
                0 < (match.kickoff_at - item[0]).total_seconds() <= 7 * 86_400
                for item in history
            )
            row[f"{side}_matches_14d"] = sum(
                0 < (match.kickoff_at - item[0]).total_seconds() <= 14 * 86_400
                for item in history
            )
            row[f"{side}_matches_21d"] = sum(
                0 < (match.kickoff_at - item[0]).total_seconds() <= 21 * 86_400
                for item in history
            )
            for window in windows:
                sample = list(history)[-window:]
                row[f"{side}_points_{window}"] = (
                    sum(item[1] for item in sample) if sample else None
                )
                row[f"{side}_goals_for_{window}"] = _mean(
                    item[2] for item in sample
                )
                row[f"{side}_goals_against_{window}"] = _mean(
                    item[3] for item in sample
                )
        output.append(row)
        home_points = 3 if match.home_goals > match.away_goals else (
            1 if match.home_goals == match.away_goals else 0
        )
        away_points = 3 if match.away_goals > match.home_goals else (
            1 if match.home_goals == match.away_goals else 0
        )
        home_history.append(
            (match.kickoff_at, home_points, match.home_goals, match.away_goals)
        )
        away_history.append(
            (match.kickoff_at, away_points, match.away_goals, match.home_goals)
        )
    return output
