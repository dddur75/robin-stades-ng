"""Dynamic provider quota and dual-window request throttling."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from robin.historical_deep.contracts import ProviderStatus, QuotaBudget

_MAX_MINUTE_RESET_WAIT_SECONDS = 60.0
_MINUTE_RESET_HEADERS = (
    "x-ratelimit-reset",
    "x-rate-limit-reset",
    "retry-after",
)


class QuotaExhaustedError(RuntimeError):
    """Raised before transport when the protected mission budget is exhausted."""


class QuotaStatusExpiredError(QuotaExhaustedError):
    """Raised when a stale GET /status proof would otherwise authorize a call."""


def _integer_header(headers: Mapping[str, str], *names: str) -> int | None:
    lowered = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    for name in names:
        raw = lowered.get(name.casefold())
        if raw is None:
            continue
        try:
            parsed = int(float(raw))
        except ValueError:
            continue
        if parsed >= 0:
            return parsed
    return None


def _minute_reset_at(
    headers: Mapping[str, str],
    *,
    observed_at: datetime,
) -> tuple[bool, datetime | None]:
    lowered = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    raw = next(
        (lowered[name] for name in _MINUTE_RESET_HEADERS if name in lowered),
        None,
    )
    if raw is None:
        return False, None
    try:
        numeric = float(raw)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (OverflowError, TypeError, ValueError):
            return True, None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return True, None
        reset_at = parsed.astimezone(UTC)
    else:
        if not math.isfinite(numeric) or numeric < 0:
            return True, None
        try:
            reset_at = (
                datetime.fromtimestamp(numeric, tz=UTC)
                if numeric >= 1_000_000_000
                else observed_at + timedelta(seconds=numeric)
            )
        except (OverflowError, OSError, ValueError):
            return True, None
    return True, reset_at if reset_at > observed_at else None


class QuotaController:
    """Owns the dynamic daily budget and the 8 rps / 480 rpm ceilings."""

    def __init__(
        self,
        status: ProviderStatus,
        *,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        initial_mission_used: int = 0,
        initial_mission_cap: int | None = None,
    ) -> None:
        if initial_mission_used < 0:
            raise ValueError("QUOTA_INITIAL_MISSION_USED_MUST_BE_NON_NEGATIVE")
        initial_budget = QuotaBudget.from_status(status)
        if initial_mission_cap is not None and not 0 <= initial_mission_cap <= 100000:
            raise ValueError("QUOTA_INITIAL_MISSION_CAP_INVALID")
        self._status = status
        self._mission_used = initial_mission_used
        self._mission_cap = (
            initial_budget.mission_cap
            if initial_mission_cap is None
            else initial_mission_cap
        )
        self._requests_per_second = status.requests_per_second
        self._requests_per_minute = status.requests_per_minute
        self._sleeper = sleeper
        self._clock = clock
        self._now = now
        self._last_request_at: float | None = None
        self._minute_requests: deque[float] = deque()

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @property
    def budget(self) -> QuotaBudget:
        status = ProviderStatus(
            provider=self._status.provider,
            plan=self._status.plan,
            active=self._status.active,
            daily_limit=self._status.daily_limit,
            daily_used=self._status.daily_used,
            daily_remaining=self._status.daily_remaining,
            requests_per_second=self._requests_per_second,
            requests_per_minute=self._requests_per_minute,
            checked_at=self._status.checked_at,
            expires_at=self._status.expires_at,
            rate_limit_reset_at=self._status.rate_limit_reset_at,
            source_endpoint=self._status.source_endpoint,
        )
        return QuotaBudget.from_status(
            status,
            mission_used=self._mission_used,
            mission_cap=self._mission_cap,
        )

    @property
    def requests_per_second(self) -> int:
        return self._requests_per_second

    @property
    def requests_per_minute(self) -> int:
        return self._requests_per_minute

    @property
    def mission_used(self) -> int:
        return self._mission_used

    @property
    def mission_cap(self) -> int:
        return self._mission_cap

    def can_reserve(self, calls: int = 1) -> bool:
        if calls < 1:
            raise ValueError("QUOTA_CALLS_MUST_BE_POSITIVE")
        return calls <= self.budget.mission_remaining

    def reserve_calls(self, calls: int = 1) -> QuotaBudget:
        """Atomically consume mission allowance before making billable calls."""

        if not self.can_reserve(calls):
            raise QuotaExhaustedError("API_FOOTBALL_PROTECTED_QUOTA_EXHAUSTED")
        self._mission_used += calls
        return self.budget

    def _wait_for_provider_minute_window(self) -> None:
        if self._status.per_minute_remaining > 0:
            return
        reset_at = self._status.rate_limit_reset_at
        if reset_at is None:
            raise QuotaExhaustedError(
                "API_FOOTBALL_MINUTE_QUOTA_EXHAUSTED_RESET_UNKNOWN"
            )
        delay = (reset_at - self._now()).total_seconds()
        if delay > _MAX_MINUTE_RESET_WAIT_SECONDS:
            raise QuotaExhaustedError(
                "API_FOOTBALL_MINUTE_QUOTA_RESET_WAIT_EXCEEDS_BOUND"
            )
        if delay > 0:
            self._sleeper(delay)
            if self._now() < reset_at:
                raise QuotaExhaustedError(
                    "API_FOOTBALL_MINUTE_QUOTA_RESET_NOT_REACHED"
                )
        self._status = self._status.model_copy(
            update={
                "requests_per_minute_remaining": self._requests_per_minute,
            }
        )

    def _consume_provider_minute_slot(self) -> None:
        remaining = self._status.per_minute_remaining
        if remaining < 1:
            raise QuotaExhaustedError(
                "API_FOOTBALL_MINUTE_QUOTA_EXHAUSTED"
            )
        self._status = self._status.model_copy(
            update={"requests_per_minute_remaining": remaining - 1}
        )

    def _wait_for_rate_slot(self) -> None:
        now = self._clock()
        delay = 0.0
        if self._last_request_at is not None:
            delay = max(delay, (1.0 / self._requests_per_second) - (now - self._last_request_at))

        while self._minute_requests and now - self._minute_requests[0] >= 60.0:
            self._minute_requests.popleft()
        if len(self._minute_requests) >= self._requests_per_minute:
            delay = max(delay, 60.0 - (now - self._minute_requests[0]))

        if delay > 0:
            self._sleeper(delay)
            now = self._clock()
            while self._minute_requests and now - self._minute_requests[0] >= 60.0:
                self._minute_requests.popleft()
        self._last_request_at = now
        self._minute_requests.append(now)

    def before_request(self) -> QuotaBudget:
        """Throttle and reserve one call before transport."""

        if not self._status.is_fresh(self._now()):
            raise QuotaStatusExpiredError("API_FOOTBALL_STATUS_PROOF_EXPIRED")
        self._wait_for_provider_minute_window()
        self._wait_for_rate_slot()
        if not self._status.is_fresh(self._now()):
            raise QuotaStatusExpiredError("API_FOOTBALL_STATUS_PROOF_EXPIRED")
        budget = self.reserve_calls(1)
        self._consume_provider_minute_slot()
        return budget

    acquire = before_request

    def before_status_refresh(self) -> QuotaBudget:
        """Allow only GET /status to refresh an expired provider proof."""

        self._wait_for_provider_minute_window()
        self._wait_for_rate_slot()
        budget = self.reserve_calls(1)
        self._consume_provider_minute_slot()
        return budget

    def observe_headers(self, headers: Mapping[str, str]) -> QuotaBudget:
        """Refresh daily allowance and rate ceilings from sanitized headers."""

        daily_limit = _integer_header(
            headers,
            "x-ratelimit-requests-limit",
            "x-rate-limit-requests-limit",
        )
        daily_remaining = _integer_header(
            headers,
            "x-ratelimit-requests-remaining",
            "x-rate-limit-requests-remaining",
        )
        per_second = _integer_header(
            headers,
            "x-ratelimit-rps-limit",
            "x-rate-limit-rps-limit",
            "x-requests-per-second",
        )
        per_minute = _integer_header(
            headers,
            "x-ratelimit-limit",
            "x-rate-limit-limit",
            "x-ratelimit-minute-limit",
            "x-requests-per-minute",
        )
        per_minute_remaining = _integer_header(
            headers,
            "x-ratelimit-remaining",
            "x-rate-limit-remaining",
        )
        observed_at = self._now()
        reset_header_present, observed_reset_at = _minute_reset_at(
            headers,
            observed_at=observed_at,
        )
        if all(
            value is None
            for value in (
                daily_limit,
                daily_remaining,
                per_second,
                per_minute,
                per_minute_remaining,
            )
        ) and not reset_header_present:
            return self.budget

        new_daily_limit = daily_limit or self._status.daily_limit
        new_daily_remaining = (
            min(daily_remaining, new_daily_limit)
            if daily_remaining is not None
            else self._status.daily_remaining
        )
        inferred_used = max(
            self._status.daily_used,
            new_daily_limit - new_daily_remaining,
        )
        self._requests_per_second = min(8, max(1, per_second or self._requests_per_second))
        self._requests_per_minute = min(
            480,
            max(1, per_minute or self._requests_per_minute),
        )
        self._status = ProviderStatus(
            provider="api-football",
            plan="Mega",
            active=True,
            daily_limit=new_daily_limit,
            daily_used=min(inferred_used, new_daily_limit),
            daily_remaining=new_daily_remaining,
            requests_per_second=self._requests_per_second,
            requests_per_minute=self._requests_per_minute,
            requests_per_minute_remaining=min(
                per_minute_remaining,
                self._requests_per_minute,
            )
            if per_minute_remaining is not None
            else self._status.requests_per_minute_remaining,
            checked_at=observed_at,
            expires_at=observed_at
            + (self._status.status_expires_at - self._status.checked_at),
            subscription_end=self._status.subscription_end,
            days_remaining=(
                max(
                    0,
                    (
                        self._status.subscription_end.date()
                        - observed_at.date()
                    ).days,
                )
                if self._status.subscription_end is not None
                else None
            ),
            next_quota_reset=self._status.next_quota_reset,
            rate_limit_reset_at=(
                observed_reset_at
                if reset_header_present
                else (
                    None
                    if per_minute_remaining == 0
                    else self._status.rate_limit_reset_at
                )
            ),
            header_daily_limit=daily_limit,
            header_daily_remaining=daily_remaining,
            header_minute_limit=per_minute,
            header_minute_remaining=per_minute_remaining,
            sanitized_headers={
                str(key).casefold(): str(value) for key, value in headers.items()
            },
            source_endpoint="/status",
        )
        return self.budget

    def replace_status(self, status: ProviderStatus) -> QuotaBudget:
        """Refresh the provider proof while preserving mission consumption."""

        self._status = status
        self._requests_per_second = min(8, status.requests_per_second)
        self._requests_per_minute = min(480, status.requests_per_minute)
        return self.budget
