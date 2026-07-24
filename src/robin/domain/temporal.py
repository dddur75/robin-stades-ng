"""Contrats temporels empêchant l'utilisation silencieuse du futur."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robin.domain.enums import QualityStatus


def require_utc(value: datetime, field_name: str) -> datetime:
    """Refuser les instants naïfs et normaliser les instants conscients en UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} doit inclure un fuseau horaire")
    return value.astimezone(UTC)


class TemporalInstants(BaseModel):
    """Instants distincts d'un événement et de ses observations."""

    model_config = ConfigDict(frozen=True)

    fixture_created_at: datetime
    fixture_kickoff_at: datetime
    data_observed_at: datetime
    data_ingested_at: datetime
    prediction_generated_at: datetime | None = None
    odds_observed_at: datetime | None = None
    lineup_confirmed_at: datetime | None = None
    result_confirmed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_order(self) -> TemporalInstants:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_utc(value, name))
        if self.data_observed_at > self.data_ingested_at:
            raise ValueError("data_observed_at ne peut pas suivre data_ingested_at")
        if (
            self.prediction_generated_at is not None
            and self.data_observed_at >= self.prediction_generated_at
        ):
            raise ValueError("une prédiction exige des données strictement antérieures")
        if (
            self.odds_observed_at is not None
            and self.prediction_generated_at is not None
            and self.odds_observed_at > self.prediction_generated_at
        ):
            raise ValueError("une cote future ne peut pas alimenter une prédiction")
        if (
            self.result_confirmed_at is not None
            and self.result_confirmed_at < self.fixture_kickoff_at
        ):
            raise ValueError("un résultat confirmé ne peut pas précéder le coup d'envoi")
        return self


class FeatureRecord(BaseModel):
    """Valeur de feature versionnée et reproductible."""

    model_config = ConfigDict(frozen=True)

    feature_name: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    value: Any
    as_of_time: datetime
    calculated_at: datetime
    source_version: str = Field(min_length=1)
    feature_version: str = Field(min_length=1)
    quality_status: QualityStatus
    observation_times: tuple[datetime, ...] = ()

    @model_validator(mode="after")
    def validate_temporal_contract(self) -> FeatureRecord:
        as_of = require_utc(self.as_of_time, "as_of_time")
        calculated = require_utc(self.calculated_at, "calculated_at")
        object.__setattr__(self, "as_of_time", as_of)
        object.__setattr__(self, "calculated_at", calculated)
        if calculated < as_of:
            raise ValueError("calculated_at ne peut pas précéder as_of_time")
        normalized = tuple(
            require_utc(value, "observation_times") for value in self.observation_times
        )
        if any(value >= as_of for value in normalized):
            raise ValueError("toute observation doit être strictement antérieure à as_of_time")
        object.__setattr__(self, "observation_times", normalized)
        return self


def known_strictly_before(observed_at: datetime, as_of_time: datetime) -> bool:
    """Politique unique utilisée par les calculs point-in-time."""
    return require_utc(observed_at, "observed_at") < require_utc(as_of_time, "as_of_time")
