"""Transport HTTP testable avec reprise, quotas et archivage brut."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import requests

from robin.domain.enums import DataAvailability, DataOrigin
from robin.ingestion.raw_store import LocalRawStore
from robin.providers.contracts import (
    CircuitOpenError,
    ProviderResult,
    QuotaState,
    RateLimitError,
    TransientProviderError,
)


class ResponseLike(Protocol):
    status_code: int
    content: bytes
    headers: Mapping[str, str]

    def json(self) -> Any: ...


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
                params=cast(Any, dict(params)),
                headers=dict(headers),
                timeout=timeout,
            ),
        )


def _integer_header(headers: Mapping[str, str], *names: str) -> int | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


class JsonHttpProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        credential: str | None,
        credential_param: str | None = None,
        credential_header: str | None = None,
        raw_store: LocalRawStore | None = None,
        ingestion_run_id: str = "manual",
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        randomizer: Callable[[], float] = random.random,
        max_retries: int = 2,
        request_rate_per_second: float | None = None,
        circuit_failure_threshold: int = 3,
        circuit_cooldown_seconds: float = 60.0,
        offline: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self.credential = (credential or "").strip()
        self.credential_param = credential_param
        self.credential_header = credential_header
        self.raw_store = raw_store
        self.ingestion_run_id = ingestion_run_id
        self.transport = transport or RequestsTransport()
        self.sleeper = sleeper
        self.randomizer = randomizer
        self.max_retries = max_retries
        self.request_rate_per_second = request_rate_per_second
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self._consecutive_failures = 0
        self._circuit_opened_at: float | None = None
        self._last_request_at: float | None = None
        self.offline = offline

    def _wait_for_rate_limit(self) -> None:
        if not self.request_rate_per_second or self.request_rate_per_second <= 0:
            return
        now = time.monotonic()
        interval = 1.0 / self.request_rate_per_second
        if self._last_request_at is not None:
            delay = interval - (now - self._last_request_at)
            if delay > 0:
                self.sleeper(delay)
        self._last_request_at = time.monotonic()

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.circuit_failure_threshold:
            self._circuit_opened_at = time.monotonic()

    def _assert_circuit_closed(self) -> None:
        if self._circuit_opened_at is None:
            return
        if time.monotonic() - self._circuit_opened_at < self.circuit_cooldown_seconds:
            raise CircuitOpenError(f"{self.provider_name}: circuit_open")
        self._circuit_opened_at = None
        self._consecutive_failures = 0

    def assert_transport_available(self) -> None:
        """Fail before callers reserve quota when the local circuit is open."""

        self._assert_circuit_closed()

    def _request(
        self,
        endpoint: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> ProviderResult:
        now = datetime.now(UTC)
        if self.offline:
            return ProviderResult(
                provider=self.provider_name,
                endpoint=endpoint,
                availability=DataAvailability.ABSENT,
                observed_at=now,
                origin=DataOrigin.DEMO_DATA,
                message="mode hors ligne",
            )
        if not self.credential:
            return ProviderResult(
                provider=self.provider_name,
                endpoint=endpoint,
                availability=DataAvailability.ABSENT,
                observed_at=now,
                origin=DataOrigin.LIVE_SOURCE,
                message="credential_absent",
            )
        self._assert_circuit_closed()
        query = dict(params or {})
        headers: dict[str, str] = {"accept": "application/json"}
        if self.credential_param:
            query[self.credential_param] = self.credential
        if self.credential_header:
            headers[self.credential_header] = self.credential
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        response: ResponseLike | None = None
        requested_at = datetime.now(UTC)
        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()
            try:
                response = self.transport.get(
                    url,
                    params=query,
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException:
                if attempt == self.max_retries:
                    self._record_failure()
                    # A Requests exception may embed the full request URL. Some
                    # providers authenticate through a query parameter, so the
                    # original exception must never reach workflow logs.
                    raise TransientProviderError(
                        f"{self.provider_name}: transport_error"
                    ) from None
                self.sleeper(2**attempt + self.randomizer())
                continue
            if response.status_code == 429:
                if attempt == self.max_retries:
                    self._record_failure()
                    raise RateLimitError(f"{self.provider_name}: quota HTTP 429")
                self.sleeper(2**attempt + self.randomizer())
                continue
            if response.status_code >= 500:
                if attempt == self.max_retries:
                    self._record_failure()
                    raise TransientProviderError(
                        f"{self.provider_name}: HTTP {response.status_code}"
                    )
                self.sleeper(2**attempt + self.randomizer())
                continue
            break

        if response is None:
            self._record_failure()
            raise TransientProviderError(
                f"{self.provider_name}: aucune réponse après les reprises"
            )
        self._consecutive_failures = 0
        self._circuit_opened_at = None
        received_at = datetime.now(UTC)
        raw_id: str | None = None
        raw_payload_hash: str | None = None
        if self.raw_store is not None:
            observation = self.raw_store.store(
                provider=self.provider_name,
                endpoint=endpoint,
                request_parameters=query,
                requested_at=requested_at,
                received_at=received_at,
                http_status=response.status_code,
                payload=response.content,
                schema_version="j2-v1",
                ingestion_run_id=self.ingestion_run_id,
            )
            raw_id = observation.observation_id
            raw_payload_hash = observation.payload_hash

        quota = QuotaState(
            used=_integer_header(
                response.headers,
                "x-requests-used",
                "x-ratelimit-requests-current",
            ),
            remaining=_integer_header(
                response.headers,
                "x-requests-remaining",
                "x-ratelimit-requests-remaining",
            ),
            limit=_integer_header(
                response.headers,
                "x-ratelimit-requests-limit",
            ),
            last_cost=_integer_header(response.headers, "x-requests-last"),
        )
        if response.status_code >= 400:
            return ProviderResult(
                provider=self.provider_name,
                endpoint=endpoint,
                availability=DataAvailability.ERROR,
                observed_at=received_at,
                origin=DataOrigin.LIVE_SOURCE,
                raw_observation_id=raw_id,
                raw_payload_hash=raw_payload_hash,
                quota=quota,
                http_status=response.status_code,
                requested_at=requested_at,
                received_at=received_at,
                message=f"HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TransientProviderError("réponse JSON invalide") from exc
        if isinstance(payload, dict) and payload.get("errors"):
            return ProviderResult(
                provider=self.provider_name,
                endpoint=endpoint,
                availability=DataAvailability.ERROR,
                observed_at=received_at,
                origin=DataOrigin.LIVE_SOURCE,
                raw_observation_id=raw_id,
                raw_payload_hash=raw_payload_hash,
                quota=quota,
                http_status=response.status_code,
                requested_at=requested_at,
                received_at=received_at,
                message="provider_response_errors",
            )
        records: tuple[dict[str, Any], ...]
        paging_current = 1
        paging_total = 1
        if isinstance(payload, list):
            records = tuple(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            paging = payload.get("paging")
            if isinstance(paging, Mapping):
                try:
                    paging_current = int(paging.get("current", 1))
                    paging_total = int(paging.get("total", 1))
                except (TypeError, ValueError):
                    paging_current = 0
                    paging_total = 0
            response_records = payload.get("response")
            if isinstance(response_records, list):
                records = tuple(
                    item for item in response_records if isinstance(item, dict)
                )
            else:
                records = (payload,)
        else:
            records = ()
        return ProviderResult(
            provider=self.provider_name,
            endpoint=endpoint,
            availability=(
                DataAvailability.PRESENT if records else DataAvailability.ABSENT
            ),
            records=records,
            observed_at=received_at,
            origin=DataOrigin.LIVE_SOURCE,
            raw_observation_id=raw_id,
            raw_payload_hash=raw_payload_hash,
            raw_payload=payload,
            quota=quota,
            http_status=response.status_code,
            requested_at=requested_at,
            received_at=received_at,
            paging_current=paging_current,
            paging_total=paging_total,
            message=None if records else "réponse valide sans donnée",
        )
