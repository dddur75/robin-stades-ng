"""Contrat canonique des marchés et snapshots de cotes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robin.domain.enums import (
    MarketScope,
    MarketType,
    QuotePhase,
    Selection,
)
from robin.domain.temporal import require_utc


class MarketKey(BaseModel):
    """Clé bookmaker-agnostique d'une opportunité."""

    model_config = ConfigDict(frozen=True)

    fixture_id: str = Field(min_length=1)
    market_type: MarketType
    market_scope: MarketScope = MarketScope.MATCH
    selection: Selection
    line_value: Decimal | None = None
    period: str = "FULL_TIME"
    settlement_rule_version: str = "1.0"

    @model_validator(mode="after")
    def validate_line(self) -> MarketKey:
        requires_line = self.market_type == MarketType.TOTAL_GOALS
        if requires_line and self.line_value is None:
            raise ValueError("un total exige line_value")
        if not requires_line and self.line_value is not None:
            raise ValueError("line_value est interdite pour ce marché")
        return self

    def business_key(self) -> tuple[str, str, str, str, str | None, str, str]:
        return (
            self.fixture_id,
            self.market_type.value,
            self.market_scope.value,
            self.selection.value,
            str(self.line_value) if self.line_value is not None else None,
            self.period,
            self.settlement_rule_version,
        )


class BookmakerQuoteContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    market: MarketKey
    bookmaker_id: str = Field(min_length=1)
    odds_decimal: Decimal = Field(gt=Decimal("1.0"))
    observed_at: datetime
    phase: QuotePhase
    source_observation_id: str = Field(min_length=1)
    bookmaker_rule_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_time(self) -> BookmakerQuoteContract:
        object.__setattr__(
            self,
            "observed_at",
            require_utc(self.observed_at, "observed_at"),
        )
        return self

    def idempotency_key(self) -> tuple[object, ...]:
        return (
            *self.market.business_key(),
            self.bookmaker_id,
            self.observed_at.isoformat(),
            str(self.odds_decimal),
        )


class OddsSnapshot(BaseModel):
    """Envelope prospective indépendante de l'API fournisseur."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(min_length=1)
    provider_fixture_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    fixture_kickoff_at: datetime
    fixture_kickoff_local: str = Field(min_length=1)
    observed_at: datetime
    ingested_at: datetime
    phase: QuotePhase
    quotes: tuple[BookmakerQuoteContract, ...]
    schema_version: str = "1"

    @model_validator(mode="after")
    def validate_times(self) -> OddsSnapshot:
        kickoff = require_utc(self.fixture_kickoff_at, "fixture_kickoff_at")
        observed = require_utc(self.observed_at, "observed_at")
        ingested = require_utc(self.ingested_at, "ingested_at")
        if observed > ingested:
            raise ValueError("observed_at ne peut pas suivre ingested_at")
        object.__setattr__(self, "fixture_kickoff_at", kickoff)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "ingested_at", ingested)
        if any(quote.observed_at != observed for quote in self.quotes):
            raise ValueError("toutes les cotes doivent partager l'instant du snapshot")
        keys = [quote.idempotency_key() for quote in self.quotes]
        if len(keys) != len(set(keys)):
            raise ValueError("snapshot contenant une cotation dupliquée")
        return self

