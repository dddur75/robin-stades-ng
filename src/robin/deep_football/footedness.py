"""Observed footedness only; heuristic completion is forbidden."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FootednessObservation:
    player_id: str
    foot: str | None
    source: str | None
    source_field: str | None


def observed_foot(observation: FootednessObservation) -> str | None:
    if observation.source is None or observation.source_field is None:
        return None
    value = observation.foot.strip().upper() if observation.foot else None
    return value if value in {"LEFT", "RIGHT", "BOTH"} else None


def footedness_coverage(
    observations: Iterable[FootednessObservation],
    relevant_player_ids: Iterable[str],
) -> float:
    relevant = set(relevant_player_ids)
    if not relevant:
        return 0.0
    by_player = {
        observation.player_id: observed_foot(observation)
        for observation in observations
        if observation.player_id in relevant
    }
    return sum(by_player.get(player_id) is not None for player_id in relevant) / len(
        relevant
    )


def infer_foot_from_position(*, position: str) -> str:
    del position
    raise ValueError("FOOTEDNESS_HEURISTIC_INFERENCE_FORBIDDEN")
