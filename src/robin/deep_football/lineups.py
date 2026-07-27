"""Separated PRE_LINEUP and POST_LINEUP semantics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from robin.deep_football.contracts import ResearchMode


@dataclass(frozen=True, slots=True)
class LineupObservation:
    fixture_id: str
    team_id: str
    player_ids: tuple[str, ...]
    observed_at: datetime
    kickoff_at: datetime
    formation_raw: str | None
    complete: bool


def validate_lineup(
    lineup: LineupObservation,
    *,
    mode: ResearchMode,
    cutoff: datetime,
) -> None:
    if mode == ResearchMode.PRE_LINEUP:
        raise ValueError("CONFIRMED_LINEUP_FORBIDDEN_IN_PRE_LINEUP_MODE")
    if lineup.observed_at >= cutoff or lineup.observed_at >= lineup.kickoff_at:
        raise ValueError("LINEUP_NOT_AVAILABLE_AT_CUTOFF")
    if not lineup.complete:
        raise ValueError("LINEUP_INCOMPLETE")
    if len(lineup.player_ids) != 11 or len(set(lineup.player_ids)) != 11:
        raise ValueError("LINEUP_MUST_HAVE_ELEVEN_UNIQUE_STARTERS")


def lineup_continuity(
    current_players: Iterable[str],
    previous_players: Iterable[str],
) -> float | None:
    current = tuple(current_players)
    previous = tuple(previous_players)
    if len(current) != 11 or len(set(current)) != 11:
        return None
    if len(previous) != 11 or len(set(previous)) != 11:
        return None
    return len(set(current) & set(previous)) / 11


def centre_back_pair_continuity(
    current_pair: Iterable[str],
    previous_pair: Iterable[str],
) -> str:
    current = tuple(current_pair)
    previous = tuple(previous_pair)
    if len(current) != 2 or len(previous) != 2:
        return "UNKNOWN"
    retained = len(set(current) & set(previous))
    return (
        "SAME_PAIR"
        if retained == 2
        else "ONE_NEW_CENTRE_BACK"
        if retained == 1
        else "TWO_NEW_CENTRE_BACKS"
    )


def observed_centre_backs(
    players: Iterable[dict[str, object]],
    *,
    expected_back_line: int,
) -> tuple[str, ...]:
    """Use observed lineup grid slots; do not infer centre-backs from names."""

    if expected_back_line not in {3, 4, 5}:
        raise ValueError("BACK_LINE_SIZE_INVALID")
    defenders: list[tuple[int, str]] = []
    for item in players:
        player_id = item.get("player_id")
        position = item.get("position")
        grid = item.get("grid")
        if (
            player_id is None
            or position != "D"
            or not isinstance(grid, str)
            or ":" not in grid
        ):
            continue
        line, slot = grid.split(":", 1)
        if line != "2":
            continue
        try:
            defenders.append((int(slot), str(player_id)))
        except ValueError as exc:
            raise ValueError("LINEUP_GRID_INVALID") from exc
    defenders.sort()
    if len(defenders) != expected_back_line:
        raise ValueError("FORMATION_DEFENDER_COUNT_MISMATCH")
    # The two most central ordered slots are retained; for odd back lines the
    # middle defender and its nearest left neighbour form the frozen pair.
    middle = len(defenders) // 2
    central_indices = (
        (middle - 1, middle)
        if len(defenders) % 2 == 0
        else (middle - 1, middle)
    )
    return tuple(defenders[index][1] for index in central_indices)
