"""Contrats versionnés du pipeline historique."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CoverageStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    RETRYABLE = "RETRYABLE"
    FAILED = "FAILED"
    SKIPPED_UNAVAILABLE = "SKIPPED_UNAVAILABLE"
    SKIPPED_QUOTA = "SKIPPED_QUOTA"
    QUARANTINED = "QUARANTINED"


class QuotaMode(StrEnum):
    NORMAL = "NORMAL"
    ACCELERATED = "ACCELERATED"
    CONSERVATIVE = "CONSERVATIVE"
    CRITICAL_RESERVE = "CRITICAL_RESERVE"
    PAUSED = "PAUSED"


class AvailabilityStatus(StrEnum):
    POINT_IN_TIME_SAFE = "POINT_IN_TIME_SAFE"
    POST_MATCH_ONLY = "POST_MATCH_ONLY"
    HISTORICAL_NON_POINT_IN_TIME = "HISTORICAL_NON_POINT_IN_TIME"
    SIMULATED_AVAILABILITY = "SIMULATED_AVAILABILITY"
    UNKNOWN_AVAILABILITY = "UNKNOWN_AVAILABILITY"


class BackfillTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    provider: str = "api-football"
    competition_id: int
    season: int
    endpoint: str
    page: int = 1
    fixture_id: int | None = None
    team_id: int | None = None
    player_id: int | None = None
    priority: str = "A"
    estimated_calls: int = 1
    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = 0
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    completed_at: datetime | None = None
    rows_received: int = 0
    payload_hash: str | None = None
    error_code: str | None = None
    coverage_status: CoverageStatus = CoverageStatus.UNKNOWN


class CoverageObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    competition: str
    season: int
    endpoint: str
    provider_competition_id: int | None = None
    advertised_coverage: dict[str, bool | None] = Field(default_factory=dict)
    rows_received: int = 0
    pages: int = 0
    quota_consumed: int = 0
    raw_bytes: int = 0
    compressed_bytes: int = 0
    normalized_bytes: int = 0
    quality_status: str = "NOT_CHECKED"
    status: CoverageStatus = CoverageStatus.UNKNOWN
    last_checked_at: datetime | None = None
