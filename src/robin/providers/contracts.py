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
    quota: QuotaState = Field(default_factory=QuotaState)
    message: str | None = None


class ProviderCallError(RuntimeError):
    pass


class MissingCredentialError(ProviderCallError):
    pass


class RateLimitError(ProviderCallError):
    pass


class TransientProviderError(ProviderCallError):
    pass
