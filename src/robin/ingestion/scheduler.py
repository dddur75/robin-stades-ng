"""Planification quota-aware des fenêtres de collecte prospectives."""

from __future__ import annotations

from collections.abc import Mapping
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


class WindowStatus(StrEnum):
    PENDING = "PENDING"
    DUE = "DUE"
    COLLECTED = "COLLECTED"
    COLLECTED_LATE = "COLLECTED_LATE"
    NO_MARKET_AVAILABLE = "NO_MARKET_AVAILABLE"
    PROVIDER_EMPTY = "PROVIDER_EMPTY"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MISSED_RECOVERABLE = "MISSED_RECOVERABLE"
    MISSED_FINAL = "MISSED_FINAL"
    SKIPPED_QUOTA = "SKIPPED_QUOTA"
    CANCELLED_FIXTURE = "CANCELLED_FIXTURE"


class BudgetLevel(StrEnum):
    NORMAL = "NORMAL"
    CONSERVATIVE = "CONSERVATIVE"
    CRITICAL_RESERVE = "CRITICAL_RESERVE"
    COLLECTION_PAUSED = "COLLECTION_PAUSED"


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


class SchedulerWindowState(BaseModel):
    model_config = ConfigDict(frozen=True)

    fixture_id: str
    window: CollectionWindow
    scheduled_for: datetime
    acceptable_from: datetime
    acceptable_until: datetime
    status: WindowStatus
    last_attempt_at: datetime | None = None
    attempt_count: int = 0
    observation_received: bool = False
    market_available: bool | None = None
    provider_status: str | None = None


class BudgetState(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: BudgetLevel
    credits_used_today: int
    credits_used_month: int
    forecast_month_end: int
    operational_ceiling: int
    provider_remaining: int
    reserve_credits: int
    credits_near_kickoff_reserved: int
    explanation: str


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


def window_states(
    fixtures: tuple[FixtureCandidate, ...],
    *,
    now: datetime,
    known: Mapping[tuple[str, CollectionWindow], SchedulerWindowState] | None = None,
    early_tolerance: timedelta = timedelta(minutes=20),
    recovery_margin: timedelta = timedelta(hours=2),
) -> tuple[SchedulerWindowState, ...]:
    current = require_utc(now, "now")
    existing = known or {}
    values: list[SchedulerWindowState] = []
    for fixture in fixtures:
        kickoff = require_utc(fixture.kickoff_at, "kickoff_at")
        for window, offset in WINDOW_TARGETS.items():
            key = (fixture.provider_fixture_id, window)
            if key in existing and existing[key].status in {
                WindowStatus.COLLECTED,
                WindowStatus.COLLECTED_LATE,
                WindowStatus.NO_MARKET_AVAILABLE,
                WindowStatus.MISSED_FINAL,
                WindowStatus.SKIPPED_QUOTA,
                WindowStatus.CANCELLED_FIXTURE,
            }:
                values.append(existing[key])
                continue
            target = kickoff - offset
            acceptable_from = target - early_tolerance
            acceptable_until = target + recovery_margin
            if not fixture.active_scope:
                status = WindowStatus.CANCELLED_FIXTURE
            elif current < acceptable_from:
                status = WindowStatus.PENDING
            elif current <= target + early_tolerance:
                status = WindowStatus.DUE
            elif current <= acceptable_until:
                status = WindowStatus.MISSED_RECOVERABLE
            else:
                status = WindowStatus.MISSED_FINAL
            previous = existing.get(key)
            values.append(
                SchedulerWindowState(
                    fixture_id=fixture.provider_fixture_id,
                    window=window,
                    scheduled_for=target,
                    acceptable_from=acceptable_from,
                    acceptable_until=acceptable_until,
                    status=status,
                    last_attempt_at=previous.last_attempt_at if previous else None,
                    attempt_count=previous.attempt_count if previous else 0,
                    observation_received=(
                        previous.observation_received if previous else False
                    ),
                    market_available=previous.market_available if previous else None,
                    provider_status=previous.provider_status if previous else None,
                )
            )
    return tuple(values)


def quota_budget(
    *,
    credits_used_today: int,
    credits_used_month: int,
    provider_remaining: int,
    operational_ceiling: int = 1_000,
    reserve_credits: int = 4_000,
    forecast_month_end: int | None = None,
    credits_near_kickoff_reserved: int = 80,
) -> BudgetState:
    forecast = forecast_month_end if forecast_month_end is not None else credits_used_month
    operational_left = max(0, operational_ceiling - credits_used_month)
    provider_above_reserve = max(0, provider_remaining - reserve_credits)
    usable = min(operational_left, provider_above_reserve)
    if operational_left <= 0 or provider_remaining <= reserve_credits:
        level = BudgetLevel.COLLECTION_PAUSED
        explanation = "plafond opérationnel ou réserve fournisseur atteint"
    elif usable <= credits_near_kickoff_reserved:
        level = BudgetLevel.CRITICAL_RESERVE
        explanation = "crédits réservés uniquement aux fixtures imminentes"
    elif forecast >= int(operational_ceiling * 0.8):
        level = BudgetLevel.CONSERVATIVE
        explanation = "prévision mensuelle supérieure à 80 % du plafond"
    else:
        level = BudgetLevel.NORMAL
        explanation = "toutes les fenêtres éligibles restent autorisées"
    return BudgetState(
        level=level,
        credits_used_today=credits_used_today,
        credits_used_month=credits_used_month,
        forecast_month_end=forecast,
        operational_ceiling=operational_ceiling,
        provider_remaining=provider_remaining,
        reserve_credits=reserve_credits,
        credits_near_kickoff_reserved=credits_near_kickoff_reserved,
        explanation=explanation,
    )


def adaptive_plan(
    states: tuple[SchedulerWindowState, ...],
    *,
    fixtures: Mapping[str, FixtureCandidate],
    budget: BudgetState,
    credits_per_snapshot: int = 2,
) -> tuple[CollectionTask, ...]:
    eligible = [
        state
        for state in states
        if state.status in {WindowStatus.DUE, WindowStatus.MISSED_RECOVERABLE}
    ]
    protected = {
        CollectionWindow.H3,
        CollectionWindow.H1,
        CollectionWindow.M30,
        CollectionWindow.M10,
    }
    if budget.level == BudgetLevel.COLLECTION_PAUSED:
        return ()
    if budget.level == BudgetLevel.CONSERVATIVE:
        eligible = [state for state in eligible if state.window in protected]
    if budget.level == BudgetLevel.CRITICAL_RESERVE:
        eligible = [
            state
            for state in eligible
            if state.window in {CollectionWindow.H1, CollectionWindow.M30, CollectionWindow.M10}
        ]
    usable = min(
        max(0, budget.operational_ceiling - budget.credits_used_month),
        max(0, budget.provider_remaining - budget.reserve_credits),
    )
    affordable = usable // credits_per_snapshot
    tasks = [
        CollectionTask(
            provider_fixture_id=state.fixture_id,
            window=state.window,
            kickoff_at=fixtures[state.fixture_id].kickoff_at,
            priority=max(
                0,
                int(
                    (
                        require_utc(fixtures[state.fixture_id].kickoff_at, "kickoff_at")
                        - require_utc(state.scheduled_for, "scheduled_for")
                    ).total_seconds()
                ),
            ),
            estimated_credits=credits_per_snapshot,
        )
        for state in eligible
        if state.fixture_id in fixtures
    ]
    tasks.sort(
        key=lambda task: (
            require_utc(task.kickoff_at, "kickoff_at"),
            0 if task.window in protected else 1,
            task.provider_fixture_id,
        )
    )
    return tuple(tasks[:affordable])


def record_window_result(
    state: SchedulerWindowState,
    *,
    attempted_at: datetime,
    provider_status: str,
    observation_received: bool,
    market_available: bool | None,
) -> SchedulerWindowState:
    current = require_utc(attempted_at, "attempted_at")
    if observation_received and market_available:
        status = (
            WindowStatus.COLLECTED_LATE
            if current > state.scheduled_for + timedelta(minutes=20)
            else WindowStatus.COLLECTED
        )
    elif provider_status == "FAILED":
        status = WindowStatus.PROVIDER_FAILED
    elif provider_status == "EMPTY":
        status = WindowStatus.PROVIDER_EMPTY
    elif market_available is False:
        status = WindowStatus.NO_MARKET_AVAILABLE
    else:
        status = WindowStatus.PROVIDER_EMPTY
    return state.model_copy(
        update={
            "status": status,
            "last_attempt_at": current,
            "attempt_count": state.attempt_count + 1,
            "observation_received": observation_received,
            "market_available": market_available,
            "provider_status": provider_status,
        }
    )


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
