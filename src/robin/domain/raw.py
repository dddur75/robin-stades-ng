"""Métadonnées d'une observation brute append-only."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robin.domain.temporal import require_utc


class RawObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    request_parameters: dict[str, object]
    requested_at: datetime
    received_at: datetime
    http_status: int = Field(ge=100, le=599)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_version: str = Field(min_length=1)
    ingestion_run_id: str = Field(min_length=1)
    raw_payload_location: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_times(self) -> RawObservation:
        requested = require_utc(self.requested_at, "requested_at")
        received = require_utc(self.received_at, "received_at")
        if received < requested:
            raise ValueError("received_at ne peut pas précéder requested_at")
        object.__setattr__(self, "requested_at", requested)
        object.__setattr__(self, "received_at", received)
        return self
