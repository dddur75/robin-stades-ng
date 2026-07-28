"""Contrats typés communs aux fournisseurs réels et simulés."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from robin.domain.enums import DataAvailability, DataOrigin


class QuotaState(BaseModel):
    model_config = ConfigDict(frozen=True)

    used: int | None = None
    remaining: int | None = None
    limit: int | None = None
    last_cost: int | None = None


class ProviderResult(BaseModel):
    """Distingue une réponse vide valide d'une erreur fournisseur."""

    model_config = ConfigDict(frozen=True)

    provider: str
    endpoint: str
    availability: DataAvailability
    records: tuple[dict[str, Any], ...] = ()
    observed_at: datetime
    origin: DataOrigin
    raw_observation_id: str | None = None
    raw_payload_hash: str | None = None
    # Parsed response envelope retained only for an immediate R2-first sink.
    # It is excluded from repr/serialization so reports and logs cannot
    # accidentally duplicate a potentially large provider body.
    raw_payload: Any | None = Field(default=None, exclude=True, repr=False)
    quota: QuotaState = Field(default_factory=QuotaState)
    http_status: int | None = None
    requested_at: datetime | None = None
    received_at: datetime | None = None
    paging_current: int = 1
    paging_total: int = 1
    message: str | None = None


class ProviderCallError(RuntimeError):
    pass


class MissingCredentialError(ProviderCallError):
    pass


class RateLimitError(ProviderCallError):
    pass


class TransientProviderError(ProviderCallError):
    pass


class CircuitOpenError(TransientProviderError):
    """A provider call rejected locally before the HTTP transport is reached."""

    pass
