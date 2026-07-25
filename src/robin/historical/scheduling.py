"""Planificateur adaptatif et protections du backfill historique."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class BackfillTelemetry:
    quota_remaining: int | None
    quota_reset_at: datetime | None = None
    reserve: int = 5_000
    mean_calls_per_task: float = 25.08
    mean_seconds_per_call: float = 0.146
    recent_error_rate: float = 0.0
    recent_429_count: int = 0
    storage_bytes: int = 0
    storage_warning_bytes: int = 750_000_000
    storage_pause_bytes: int = 900_000_000
    temporal_checks_passed: bool = True


@dataclass(frozen=True)
class AdaptiveBackfillPlan:
    mode: str
    max_calls: int
    max_tasks: int
    request_rate: float
    batch_size: int
    next_run_at: datetime
    stop_reason: str | None


def observed_throughput(
    *,
    calls: int,
    tasks: int,
    fixtures: int,
    rows: int,
    elapsed_seconds: float,
    compressed_bytes: int,
    payloads: int,
) -> dict[str, float]:
    safe_calls = max(calls, 1)
    safe_tasks = max(tasks, 1)
    safe_fixtures = max(fixtures, 1)
    return {
        "calls_per_task": calls / safe_tasks,
        "calls_per_fixture": calls / safe_fixtures,
        "seconds_per_call": elapsed_seconds / safe_calls,
        "seconds_per_task": elapsed_seconds / safe_tasks,
        "rows_per_call": rows / safe_calls,
        "bytes_per_call": compressed_bytes / safe_calls,
        "payloads_per_task": payloads / safe_tasks,
    }


def accelerated_safe_plan(
    telemetry: BackfillTelemetry,
    *,
    now: datetime | None = None,
    daily_target: int = 30_000,
    run_interval_hours: int = 2,
    max_duration_minutes: int = 110,
) -> AdaptiveBackfillPlan:
    current = now or datetime.now(UTC)
    next_run = current + timedelta(hours=run_interval_hours)
    stop_reason: str | None = None
    if telemetry.recent_429_count:
        stop_reason = "HTTP_429_CIRCUIT_OPEN"
    elif telemetry.recent_error_rate > 0.05:
        stop_reason = "ERROR_RATE_ABOVE_5_PERCENT"
    elif telemetry.storage_bytes >= telemetry.storage_pause_bytes:
        stop_reason = "STORAGE_PAUSE_THRESHOLD"
    elif not telemetry.temporal_checks_passed:
        stop_reason = "TEMPORAL_QUALITY_CRITICAL"
    elif (
        telemetry.quota_remaining is not None
        and telemetry.quota_remaining <= telemetry.reserve
    ):
        stop_reason = "QUOTA_PROTECTED"
    if stop_reason:
        return AdaptiveBackfillPlan(
            "PAUSED",
            0,
            0,
            0.0,
            0,
            next_run,
            stop_reason,
        )

    runs_per_day = max(1, 24 // run_interval_hours)
    per_run_target = math.ceil(daily_target / runs_per_day)
    quota_budget = (
        max(0, telemetry.quota_remaining - telemetry.reserve)
        if telemetry.quota_remaining is not None
        else min(per_run_target, 500)
    )
    time_budget = int(
        max_duration_minutes * 60 / max(telemetry.mean_seconds_per_call, 0.05)
    )
    max_calls = min(per_run_target, quota_budget, time_budget)
    mean_calls = max(telemetry.mean_calls_per_task, 1.0)
    max_tasks = max(1, math.floor(max_calls / mean_calls)) if max_calls else 0
    request_rate = min(8.0, max(1.0, max_calls / (max_duration_minutes * 60)))
    batch_size = min(500, max(25, max_tasks))
    return AdaptiveBackfillPlan(
        "ACCELERATED_SAFE",
        max_calls,
        max_tasks,
        request_rate,
        batch_size,
        next_run,
        None,
    )
