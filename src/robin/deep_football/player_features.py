"""Player form and starter baselines built from prior appearances only."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PlayerAppearance:
    fixture_id: str
    player_id: str
    team_id: str
    kickoff_at: datetime
    minutes: int | None
    started: bool | None
    goals: int | None
    assists: int | None
    shots: int | None
    observed_at: datetime
    position: str | None


@dataclass(frozen=True, slots=True)
class PriorTeamFixture:
    """One fixture in the explicit eight-match team lookback."""

    fixture_id: str
    kickoff_at: datetime


_STARTER_BASELINE_WINDOW = 8
_CENTRE_BACK_POSITIONS = {
    "centre-back",
    "center-back",
    "central defender",
    "cb",
}


def prior_appearances(
    appearances: Iterable[PlayerAppearance],
    *,
    player_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
    count: int,
) -> tuple[PlayerAppearance, ...]:
    if count <= 0:
        raise ValueError("APPEARANCE_LOOKBACK_MUST_BE_POSITIVE")
    eligible = [
        appearance
        for appearance in appearances
        if appearance.player_id == player_id
        and appearance.fixture_id != target_fixture_id
        and appearance.kickoff_at < target_kickoff
        and appearance.observed_at < target_kickoff
        and (appearance.minutes or 0) > 0
    ]
    eligible.sort(key=lambda item: (item.kickoff_at, item.fixture_id))
    return tuple(eligible[-count:])


def player_form_before(
    appearances: Iterable[PlayerAppearance],
    *,
    player_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
    count: int = 3,
) -> dict[str, object]:
    previous = prior_appearances(
        appearances,
        player_id=player_id,
        target_fixture_id=target_fixture_id,
        target_kickoff=target_kickoff,
        count=count,
    )
    sufficient = len(previous) >= count

    def total(field: str) -> int | None:
        values = [getattr(item, field) for item in previous]
        return (
            sum(int(value) for value in values if value is not None)
            if values and all(value is not None for value in values)
            else None
        )

    goals = total("goals")
    assists = total("assists")
    return {
        "player_id": player_id,
        "appearances": len(previous),
        "history_status": (
            "SUFFICIENT_HISTORY" if sufficient else "INSUFFICIENT_HISTORY"
        ),
        "minutes": total("minutes"),
        "starts": (
            sum(item.started is True for item in previous)
            if previous and all(item.started is not None for item in previous)
            else None
        ),
        "goals": goals,
        "assists": assists,
        "goal_involvements": (
            goals + assists
            if goals is not None and assists is not None
            else None
        ),
        "shots": total("shots"),
        "cutoff": target_kickoff.isoformat(),
        "target_fixture_excluded": True,
    }


def _complete_team_fixture_window(
    appearances: Iterable[PlayerAppearance],
    *,
    team_fixtures: Iterable[PriorTeamFixture],
    player_id: str,
    target_team_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
) -> tuple[PlayerAppearance, ...] | None:
    """Return one complete, point-in-time roster observation per prior fixture."""

    fixtures = tuple(team_fixtures)
    if len(fixtures) != _STARTER_BASELINE_WINDOW:
        return None

    fixture_ids = {fixture.fixture_id for fixture in fixtures}
    if (
        len(fixture_ids) != _STARTER_BASELINE_WINDOW
        or any(not fixture.fixture_id.strip() for fixture in fixtures)
        or any(
            fixture.fixture_id == target_fixture_id
            or fixture.kickoff_at >= target_kickoff
            for fixture in fixtures
        )
    ):
        return None

    observations_by_fixture: dict[str, PlayerAppearance] = {}
    for appearance in appearances:
        if (
            appearance.player_id != player_id
            or appearance.fixture_id not in fixture_ids
        ):
            continue
        if appearance.fixture_id in observations_by_fixture:
            return None
        observations_by_fixture[appearance.fixture_id] = appearance

    if set(observations_by_fixture) != fixture_ids:
        return None

    complete: list[PlayerAppearance] = []
    for fixture in sorted(
        fixtures,
        key=lambda item: (item.kickoff_at, item.fixture_id),
    ):
        observation = observations_by_fixture[fixture.fixture_id]
        if (
            observation.team_id != target_team_id
            or observation.kickoff_at != fixture.kickoff_at
            or observation.kickoff_at >= target_kickoff
            or observation.observed_at >= target_kickoff
            or observation.minutes is None
            or observation.minutes < 0
            or observation.started is None
            or observation.position is None
            or not observation.position.strip()
            or (observation.minutes == 0 and observation.started)
        ):
            return None
        complete.append(observation)
    return tuple(complete)


def usual_starter_before(
    appearances: Iterable[PlayerAppearance],
    *,
    team_fixtures: Iterable[PriorTeamFixture],
    player_id: str,
    target_team_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
    minimum_starts: int = 4,
) -> bool | None:
    if not 0 < minimum_starts <= _STARTER_BASELINE_WINDOW:
        raise ValueError("STARTER_THRESHOLD_OUTSIDE_TEAM_WINDOW")
    previous = _complete_team_fixture_window(
        appearances,
        team_fixtures=team_fixtures,
        player_id=player_id,
        target_team_id=target_team_id,
        target_fixture_id=target_fixture_id,
        target_kickoff=target_kickoff,
    )
    if previous is None:
        return None
    return sum(item.started is True for item in previous) >= minimum_starts


def baseline_centre_back_before(
    appearances: Iterable[PlayerAppearance],
    *,
    team_fixtures: Iterable[PriorTeamFixture],
    player_id: str,
    target_team_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
) -> bool | None:
    previous = _complete_team_fixture_window(
        appearances,
        team_fixtures=team_fixtures,
        player_id=player_id,
        target_team_id=target_team_id,
        target_fixture_id=target_fixture_id,
        target_kickoff=target_kickoff,
    )
    if previous is None:
        return None
    centre_back_starts = [
        item
        for item in previous
        if item.started
        and item.position is not None
        and item.position.strip().casefold() in _CENTRE_BACK_POSITIONS
    ]
    return len(centre_back_starts) >= 4
