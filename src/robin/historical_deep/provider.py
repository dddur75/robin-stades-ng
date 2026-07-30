"""Bounded and secret-safe API-Football client for the deep harvest."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol, cast
from urllib.parse import urlsplit

import requests

from robin.historical_deep.contracts import FrozenContract, ProviderStatus
from robin.historical_deep.quota import QuotaController

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
_SAFE_RESPONSE_HEADERS = frozenset(
    {
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-requests-limit",
        "x-ratelimit-requests-remaining",
        "x-ratelimit-requests-reset",
        "x-ratelimit-rps-limit",
        "x-ratelimit-reset",
        "x-rate-limit-limit",
        "x-rate-limit-remaining",
        "x-rate-limit-requests-limit",
        "x-rate-limit-requests-remaining",
        "x-rate-limit-requests-reset",
        "x-rate-limit-rps-limit",
        "x-rate-limit-reset",
        "x-requests-per-minute",
        "x-requests-per-second",
    }
)
_SENSITIVE_NAMES = frozenset(
    {
        "api-key",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "x-apisports-key",
    }
)


class ProviderError(RuntimeError):
    """Base class whose messages never include response bodies or credentials."""


class ProviderStatusError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    """Raised for rejected credentials without retaining provider details."""


class ProviderRateLimitError(ProviderError):
    pass


class ProviderTransportError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class CircuitOpenError(ProviderError):
    pass


class ResponseLike(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def json(self) -> object: ...


class Transport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: int,
    ) -> ResponseLike: ...


class RequestsTransport:
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: int,
    ) -> ResponseLike:
        return cast(
            ResponseLike,
            requests.get(
                url,
                params=dict(params),  # type: ignore[arg-type]
                headers=dict(headers),
                timeout=timeout,
            ),
        )


class ProviderResponse(FrozenContract):
    provider: str = "api-football"
    endpoint: str
    params: dict[str, str | int | float | bool | None]
    payload: object
    http_status: int
    headers: dict[str, str]
    requested_at: datetime
    received_at: datetime
    attempts: int


def _integer_header(headers: Mapping[str, str], *names: str) -> int | None:
    lowered = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value is None:
            continue
        try:
            parsed = int(float(value))
        except ValueError:
            continue
        if parsed >= 0:
            return parsed
    return None


def _sanitize_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).casefold(): str(value)
        for key, value in headers.items()
        if str(key).casefold() in _SAFE_RESPONSE_HEADERS
    }


def _canonical_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    parsed = urlsplit(value)
    if (
        not value
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("API_FOOTBALL_ENDPOINT_MUST_BE_RELATIVE_WITHOUT_QUERY")
    normalized = "/" + value.strip("/")
    if normalized == "/" or ".." in normalized.split("/"):
        raise ValueError("API_FOOTBALL_ENDPOINT_INVALID")
    return normalized


def _safe_params(
    params: Mapping[str, object] | None,
) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for raw_name, value in (params or {}).items():
        name = str(raw_name).strip()
        if not name or name.casefold() in _SENSITIVE_NAMES:
            raise ValueError("API_FOOTBALL_SENSITIVE_QUERY_PARAMETER_FORBIDDEN")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise TypeError("API_FOOTBALL_QUERY_PARAMETERS_MUST_BE_SCALARS")
        result[name] = value
    return dict(sorted(result.items()))


class ApiFootballDeepClient:
    """API-Football client with protected quota, retries and circuit breaking."""

    def __init__(
        self,
        *,
        api_key: str,
        quota: QuotaController | None = None,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_retries: int = 3,
        circuit_failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 60.0,
        timeout_seconds: int = 30,
        status_ttl_seconds: int = 300,
    ) -> None:
        credential = api_key.strip()
        if not credential:
            raise ValueError("API_FOOTBALL_KEY_REQUIRED")
        if not 0 <= max_retries <= 3:
            raise ValueError("API_FOOTBALL_MAX_RETRIES_MUST_NOT_EXCEED_THREE")
        if circuit_failure_threshold < 1 or circuit_cooldown_seconds < 0:
            raise ValueError("API_FOOTBALL_CIRCUIT_CONFIGURATION_INVALID")
        if timeout_seconds < 1 or status_ttl_seconds < 1:
            raise ValueError("API_FOOTBALL_TIMEOUT_INVALID")

        self._api_key = credential
        self.quota = quota
        self._transport = transport or RequestsTransport()
        self._sleeper = sleeper
        self._jitter = jitter
        self._clock = clock
        self._now = now
        self._max_retries = max_retries
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_cooldown_seconds = circuit_cooldown_seconds
        self._timeout_seconds = timeout_seconds
        self._status_ttl_seconds = status_ttl_seconds
        self._consecutive_failures = 0
        self._circuit_opened_at: float | None = None
        self._last_unbudgeted_request_at: float | None = None

    def _assert_circuit_closed(self) -> None:
        if self._circuit_opened_at is None:
            return
        if self._clock() - self._circuit_opened_at < self._circuit_cooldown_seconds:
            raise CircuitOpenError("API_FOOTBALL_CIRCUIT_OPEN")
        self._circuit_opened_at = None
        self._consecutive_failures = 0

    def assert_transport_available(self) -> None:
        self._assert_circuit_closed()

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_failure_threshold:
            self._circuit_opened_at = self._clock()

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_opened_at = None

    def _before_transport(self, *, require_quota: bool) -> None:
        self._assert_circuit_closed()
        if self.quota is not None:
            if require_quota:
                self.quota.before_request()
            else:
                self.quota.before_status_refresh()
            return
        if require_quota:
            raise ProviderStatusError("API_FOOTBALL_STATUS_PROOF_REQUIRED")
        now = self._clock()
        if self._last_unbudgeted_request_at is not None:
            delay = 0.125 - (now - self._last_unbudgeted_request_at)
            if delay > 0:
                self._sleeper(delay)
                now = self._clock()
        self._last_unbudgeted_request_at = now

    def _retry_delay(self, retry_number: int, headers: Mapping[str, str]) -> float:
        jitter = float(self._jitter())
        if jitter < 0:
            raise ValueError("API_FOOTBALL_RETRY_JITTER_MUST_BE_NON_NEGATIVE")
        retry_after = _integer_header(headers, "retry-after") or 0
        return max(float(retry_after), float(2**retry_number) + jitter)

    def _request(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None,
        require_quota: bool,
    ) -> ProviderResponse:
        normalized_endpoint = _canonical_endpoint(endpoint)
        safe_params = _safe_params(params)
        url = f"{API_FOOTBALL_BASE_URL}{normalized_endpoint}"
        requested_at = self._now()
        attempts = 0

        for attempt in range(self._max_retries + 1):
            self._before_transport(require_quota=require_quota)
            attempts += 1
            try:
                response = self._transport.get(
                    url,
                    params=safe_params,
                    headers={
                        "accept": "application/json",
                        "x-apisports-key": self._api_key,
                    },
                    timeout=self._timeout_seconds,
                )
            except Exception:
                if attempt >= self._max_retries:
                    self._record_failure()
                    raise ProviderTransportError(
                        "API_FOOTBALL_TRANSPORT_FAILED"
                    ) from None
                self._sleeper(self._retry_delay(attempt, {}))
                continue

            sanitized_headers = _sanitize_headers(response.headers)
            if self.quota is not None:
                self.quota.observe_headers(sanitized_headers)
            if response.status_code in (401, 403):
                self._record_failure()
                raise ProviderAuthenticationError(
                    "API_FOOTBALL_AUTHENTICATION_FAILED"
                )
            if response.status_code == 429:
                if attempt >= self._max_retries:
                    self._record_failure()
                    raise ProviderRateLimitError(
                        "API_FOOTBALL_RATE_LIMIT_RETRY_EXHAUSTED"
                    )
                self._sleeper(self._retry_delay(attempt, sanitized_headers))
                continue
            if response.status_code >= 500:
                if attempt >= self._max_retries:
                    self._record_failure()
                    raise ProviderTransportError(
                        f"API_FOOTBALL_HTTP_{response.status_code}"
                    )
                self._sleeper(self._retry_delay(attempt, sanitized_headers))
                continue
            if response.status_code >= 400:
                self._record_failure()
                raise ProviderResponseError(
                    f"API_FOOTBALL_HTTP_{response.status_code}"
                )

            try:
                payload = response.json()
            except Exception:
                self._record_failure()
                raise ProviderResponseError("API_FOOTBALL_JSON_INVALID") from None
            if isinstance(payload, Mapping) and payload.get("errors"):
                self._record_failure()
                raise ProviderResponseError("API_FOOTBALL_RESPONSE_ERRORS")
            received_at = self._now()
            self._record_success()
            return ProviderResponse(
                endpoint=normalized_endpoint,
                params=safe_params,
                payload=payload,
                http_status=response.status_code,
                headers=sanitized_headers,
                requested_at=requested_at,
                received_at=received_at,
                attempts=attempts,
            )

        raise ProviderTransportError("API_FOOTBALL_RETRY_STATE_INVALID")

    @staticmethod
    def _reset_at(
        headers: Mapping[str, str],
        *,
        received_at: datetime,
    ) -> datetime | None:
        lowered = {str(key).casefold(): str(value).strip() for key, value in headers.items()}
        raw = next(
            (
                lowered[name]
                for name in (
                    "x-ratelimit-requests-reset",
                    "x-rate-limit-requests-reset",
                    "x-ratelimit-reset",
                    "x-rate-limit-reset",
                )
                if name in lowered
            ),
            None,
        )
        if raw is None:
            return None
        try:
            numeric = float(raw)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(UTC)
        if numeric < 0:
            return None
        reset_at = (
            datetime.fromtimestamp(numeric, tz=UTC)
            if numeric >= 1_000_000_000
            else received_at + timedelta(seconds=numeric)
        )
        return reset_at if reset_at > received_at else None

    def _parse_status(
        self,
        response: ProviderResponse,
    ) -> ProviderStatus:
        payload = response.payload
        if not isinstance(payload, Mapping):
            raise ProviderStatusError("API_FOOTBALL_STATUS_PAYLOAD_INVALID")
        raw_status = payload.get("response")
        if isinstance(raw_status, list):
            raw_status = raw_status[0] if len(raw_status) == 1 else None
        if not isinstance(raw_status, Mapping):
            raise ProviderStatusError("API_FOOTBALL_STATUS_RESPONSE_MISSING")
        subscription = raw_status.get("subscription")
        requests_status = raw_status.get("requests")
        if not isinstance(subscription, Mapping) or not isinstance(
            requests_status,
            Mapping,
        ):
            raise ProviderStatusError("API_FOOTBALL_STATUS_FIELDS_MISSING")

        plan = subscription.get("plan")
        active = subscription.get("active")
        subscription_end_raw = subscription.get("end")
        daily_limit_raw = requests_status.get("limit_day")
        daily_used_raw = requests_status.get("current")
        if (
            plan != "Mega"
            or active is not True
            or isinstance(daily_limit_raw, bool)
            or not isinstance(daily_limit_raw, (int, float))
            or isinstance(daily_used_raw, bool)
            or not isinstance(daily_used_raw, (int, float))
            or not isinstance(subscription_end_raw, str)
        ):
            raise ProviderStatusError("API_FOOTBALL_MEGA_ACTIVE_REQUIRED")
        try:
            subscription_end = datetime.fromisoformat(
                subscription_end_raw.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ProviderStatusError(
                "API_FOOTBALL_SUBSCRIPTION_END_INVALID"
            ) from exc
        if subscription_end.tzinfo is None or subscription_end.utcoffset() is None:
            subscription_end = subscription_end.replace(tzinfo=UTC)
        else:
            subscription_end = subscription_end.astimezone(UTC)
        daily_limit = int(daily_limit_raw)
        daily_used = int(daily_used_raw)
        header_limit = _integer_header(
            response.headers,
            "x-ratelimit-requests-limit",
            "x-rate-limit-requests-limit",
        )
        header_remaining = _integer_header(
            response.headers,
            "x-ratelimit-requests-remaining",
            "x-rate-limit-requests-remaining",
        )
        if header_limit is not None:
            daily_limit = header_limit
        daily_remaining = (
            min(header_remaining, daily_limit)
            if header_remaining is not None
            else max(0, daily_limit - daily_used)
        )
        per_second = _integer_header(
            response.headers,
            "x-ratelimit-rps-limit",
            "x-rate-limit-rps-limit",
            "x-requests-per-second",
        )
        per_minute = _integer_header(
            response.headers,
            "x-ratelimit-limit",
            "x-rate-limit-limit",
            "x-ratelimit-minute-limit",
            "x-requests-per-minute",
        )
        per_minute_remaining = _integer_header(
            response.headers,
            "x-ratelimit-remaining",
            "x-rate-limit-remaining",
        )
        reset_at = self._reset_at(
            response.headers,
            received_at=response.received_at,
        )
        try:
            return ProviderStatus(
                plan="Mega",
                active=True,
                daily_limit=daily_limit,
                daily_used=min(
                    max(daily_used, daily_limit - daily_remaining),
                    daily_limit,
                ),
                daily_remaining=daily_remaining,
                requests_per_second=min(8, max(1, per_second or 8)),
                requests_per_minute=min(480, max(1, per_minute or 480)),
                requests_per_minute_remaining=min(
                    per_minute_remaining,
                    min(480, max(1, per_minute or 480)),
                )
                if per_minute_remaining is not None
                else min(480, max(1, per_minute or 480)),
                checked_at=response.received_at,
                expires_at=response.received_at
                + timedelta(seconds=self._status_ttl_seconds),
                subscription_end=subscription_end,
                next_quota_reset=reset_at,
                rate_limit_reset_at=reset_at,
                header_daily_limit=header_limit,
                header_daily_remaining=header_remaining,
                header_minute_limit=per_minute,
                header_minute_remaining=per_minute_remaining,
                sanitized_headers=response.headers,
            )
        except ValueError as exc:
            raise ProviderStatusError("API_FOOTBALL_STATUS_INVALID") from exc

    def get_status(self) -> ProviderStatus:
        """Call GET /status and retain only the sanitized Mega/quota proof."""

        response = self._request(
            "/status",
            params={},
            require_quota=False,
        )
        status = self._parse_status(response)
        if self.quota is None:
            self.quota = QuotaController(
                status,
                sleeper=self._sleeper,
                clock=self._clock,
                now=self._now,
            )
        else:
            self.quota.replace_status(status)
        return status

    def get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> ProviderResponse:
        return self._request(
            endpoint,
            params=params,
            require_quota=True,
        )
