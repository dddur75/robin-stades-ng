"""Transport HTTP testable avec reprise, quotas et archivage brut."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import requests

from robin.domain.enums import DataAvailability, DataOrigin
from robin.ingestion.raw_store import LocalRawStore
from robin.providers.contracts import (
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
        max_retries: int = 2,
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
        self.max_retries = max_retries
        self.offline = offline

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
            try:
                response = self.transport.get(
                    url,
                    params=query,
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as exc:
                if attempt == self.max_retries:
                    raise TransientProviderError(str(exc)) from exc
                self.sleeper(2**attempt)
                continue
            if response.status_code == 429:
                if attempt == self.max_retries:
                    raise RateLimitError(f"{self.provider_name}: quota HTTP 429")
                self.sleeper(2**attempt)
                continue
            if response.status_code >= 500:
                if attempt == self.max_retries:
                    raise TransientProviderError(
                        f"{self.provider_name}: HTTP {response.status_code}"
                    )
                self.sleeper(2**attempt)
                continue
            break

        if response is None:
            raise TransientProviderError(
                f"{self.provider_name}: aucune réponse après les reprises"
            )
        received_at = datetime.now(UTC)
        raw_id: str | None = None
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
                quota=quota,
                message=f"HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise TransientProviderError("réponse JSON invalide") from exc
        records: tuple[dict[str, Any], ...]
        if isinstance(payload, list):
            records = tuple(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
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
            quota=quota,
            message=None if records else "réponse valide sans donnée",
        )
