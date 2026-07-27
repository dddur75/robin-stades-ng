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


def usual_starter_before(
    appearances: Iterable[PlayerAppearance],
    *,
    player_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
    window: int = 8,
    minimum_starts: int = 4,
) -> bool | None:
    previous = prior_appearances(
        appearances,
        player_id=player_id,
        target_fixture_id=target_fixture_id,
        target_kickoff=target_kickoff,
        count=window,
    )
    if len(previous) < minimum_starts or any(
        item.started is None for item in previous
    ):
        return None
    return sum(item.started is True for item in previous) >= minimum_starts


def baseline_centre_back_before(
    appearances: Iterable[PlayerAppearance],
    *,
    player_id: str,
    target_fixture_id: str,
    target_kickoff: datetime,
) -> bool | None:
    previous = prior_appearances(
        appearances,
        player_id=player_id,
        target_fixture_id=target_fixture_id,
        target_kickoff=target_kickoff,
        count=8,
    )
    if not previous or any(item.position is None for item in previous):
        return None
    centre_back_appearances = [
        item
        for item in previous
        if item.position is not None
        and item.position.strip().casefold()
        in {"centre-back", "center-back", "central defender", "cb"}
    ]
    if len(centre_back_appearances) < 4:
        return False
    return sum(item.started is True for item in centre_back_appearances) >= 4
