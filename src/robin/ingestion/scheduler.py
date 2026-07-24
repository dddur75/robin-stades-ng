"""Planification quota-aware des fenêtres de collecte prospectives."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from robin.domain.temporal import require_utc


class CollectionWindow(StrEnum):
    D7 = "J-7"
    D3 = "J-3"
    D1 = "J-1"
    H12 = "H-12"
    H6 = "H-6"
    H3 = "H-3"
    H1 = "H-1"
    M30 = "H-0:30"
    M10 = "H-0:10"


WINDOW_TARGETS = {
    CollectionWindow.D7: timedelta(days=7),
    CollectionWindow.D3: timedelta(days=3),
    CollectionWindow.D1: timedelta(days=1),
    CollectionWindow.H12: timedelta(hours=12),
    CollectionWindow.H6: timedelta(hours=6),
    CollectionWindow.H3: timedelta(hours=3),
    CollectionWindow.H1: timedelta(hours=1),
    CollectionWindow.M30: timedelta(minutes=30),
    CollectionWindow.M10: timedelta(minutes=10),
}


class FixtureCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_fixture_id: str
    kickoff_at: datetime
    active_scope: bool = True


class CollectionTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_fixture_id: str
    window: CollectionWindow
    kickoff_at: datetime
    priority: int
    estimated_credits: int


def due_window(
    kickoff_at: datetime,
    *,
    now: datetime,
    tolerance: timedelta = timedelta(minutes=20),
) -> CollectionWindow | None:
    kickoff = require_utc(kickoff_at, "kickoff_at")
    current = require_utc(now, "now")
    remaining = kickoff - current
    if remaining < timedelta(0):
        return None
    matches = [
        (abs(remaining - target), window)
        for window, target in WINDOW_TARGETS.items()
        if abs(remaining - target) <= tolerance
    ]
    return min(matches, default=(timedelta.max, None))[1]


def plan_collection(
    fixtures: tuple[FixtureCandidate, ...],
    *,
    now: datetime,
    collected: set[tuple[str, CollectionWindow]],
    quota_remaining: int,
    credits_per_snapshot: int = 2,
    reserve_credits: int = 0,
    quota_used: int = 0,
    monthly_operational_ceiling: int | None = None,
) -> tuple[CollectionTask, ...]:
    tasks: list[CollectionTask] = []
    for fixture in fixtures:
        if not fixture.active_scope:
            continue
        window = due_window(fixture.kickoff_at, now=now)
        if window is None or (fixture.provider_fixture_id, window) in collected:
            continue
        proximity = int(
            (require_utc(fixture.kickoff_at, "kickoff_at") - require_utc(now, "now"))
            .total_seconds()
        )
        tasks.append(
            CollectionTask(
                provider_fixture_id=fixture.provider_fixture_id,
                window=window,
                kickoff_at=fixture.kickoff_at,
                priority=max(0, proximity),
                estimated_credits=credits_per_snapshot,
            )
        )
    tasks.sort(key=lambda task: (task.priority, task.provider_fixture_id))
    provider_affordable = max(
        0,
        (quota_remaining - reserve_credits) // credits_per_snapshot,
    )
    if monthly_operational_ceiling is None:
        operational_affordable = provider_affordable
    else:
        operational_affordable = max(
            0,
            (monthly_operational_ceiling - quota_used) // credits_per_snapshot,
        )
    affordable = min(provider_affordable, operational_affordable)
    return tuple(tasks[:affordable])
