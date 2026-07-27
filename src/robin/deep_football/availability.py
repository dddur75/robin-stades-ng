"""Point-in-time absence evidence; non-selection is never an absence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AbsenceObservation:
    player_id: str
    team_id: str
    observed_at: datetime
    unavailable_from: datetime | None
    unavailable_until: datetime | None
    source: str
    reason: str | None
    identity_confidence: float


def absence_known_before(
    observation: AbsenceObservation,
    *,
    cutoff: datetime,
) -> bool:
    if observation.observed_at >= cutoff:
        return False
    if observation.identity_confidence < 0.99:
        return False
    if observation.unavailable_from is None:
        return False
    if observation.unavailable_from >= cutoff:
        return False
    return (
        observation.unavailable_until is None
        or observation.unavailable_until >= cutoff
    )


def count_unavailable_roles(
    observations: Iterable[AbsenceObservation],
    baseline_roles: Mapping[str, str],
    *,
    team_id: str,
    cutoff: datetime,
) -> dict[str, int]:
    counts = {"CENTRE_BACK": 0, "GOALKEEPER": 0, "OTHER": 0}
    seen: set[str] = set()
    for observation in observations:
        if (
            observation.team_id != team_id
            or observation.player_id in seen
            or not absence_known_before(observation, cutoff=cutoff)
        ):
            continue
        seen.add(observation.player_id)
        role = baseline_roles.get(observation.player_id)
        if role == "CENTRE_BACK":
            counts["CENTRE_BACK"] += 1
        elif role == "GOALKEEPER":
            counts["GOALKEEPER"] += 1
        else:
            counts["OTHER"] += 1
    return counts


def infer_absence_from_non_selection(*, selected: bool) -> bool:
    del selected
    raise ValueError("NON_SELECTION_CANNOT_DEFINE_ABSENCE")
