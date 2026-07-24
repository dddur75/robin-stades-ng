"""Contrats de résolution d'identité sans rapprochement définitif par le nom."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robin.domain.enums import EntityType, MappingStatus, ReviewStatus
from robin.domain.temporal import require_utc


class ProviderIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_type: EntityType
    provider_name: str = Field(min_length=1)
    provider_entity_id: str = Field(min_length=1)
    observed_name: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    mapping_status: MappingStatus = MappingStatus.CONFIRMED
    mapping_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    mapping_method: str = Field(default="provider_id", min_length=1)
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED

    @model_validator(mode="after")
    def validate_validity(self) -> ProviderIdentity:
        start = require_utc(self.valid_from, "valid_from")
        object.__setattr__(self, "valid_from", start)
        if self.valid_to is not None:
            end = require_utc(self.valid_to, "valid_to")
            if end <= start:
                raise ValueError("valid_to doit suivre valid_from")
            object.__setattr__(self, "valid_to", end)
        return self

