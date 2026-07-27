"""Contrats immuables et versionnés du Pattern Research Engine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PatternStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    LEAKAGE_REJECTED = "LEAKAGE_REJECTED"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    DUPLICATE = "DUPLICATE"
    DOMINATED = "DOMINATED"
    UNSTABLE = "UNSTABLE"
    MARKET_UNAVAILABLE = "MARKET_UNAVAILABLE"
    HISTORICAL_CANDIDATE = "HISTORICAL_CANDIDATE"
    EXPOSED_OOS_SURVIVOR = "EXPOSED_OOS_SURVIVOR"
    EXTERNAL_LEAGUE_SURVIVOR = "EXTERNAL_LEAGUE_SURVIVOR"
    LIVE_SHADOW_CANDIDATE = "LIVE_SHADOW_CANDIDATE"
    LIVE_SHADOW = "LIVE_SHADOW"
    PUBLIC_TEST = "PUBLIC_TEST"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class EvidenceScope(StrEnum):
    DISCOVERY_EXPOSED = "DISCOVERY_EXPOSED"
    EXPOSED_HISTORICAL_OOS = "EXPOSED_HISTORICAL_OOS"
    EXTERNAL_LEAGUE_VALIDATION = "EXTERNAL_LEAGUE_VALIDATION"
    LIVE_PROSPECTIVE = "LIVE_PROSPECTIVE"


class ConditionOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LE = "LE"
    GT = "GT"
    GE = "GE"
    BETWEEN = "BETWEEN"
    IN = "IN"


class PatternCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    operator: ConditionOperator
    value: Any
    source: str
    available_at: str

    def canonical(self) -> dict[str, object]:
        value = self.value
        if isinstance(value, set | tuple):
            value = sorted(value)
        if isinstance(value, list):
            value = sorted(value, key=str)
        return {
            "available_at": self.available_at,
            "feature": self.feature,
            "operator": self.operator.value,
            "source": self.source,
            "value": value,
        }


class PatternDefinition(BaseModel):
    """Définition complète; aucun statut VALIDATED issu du seul historique."""

    model_config = ConfigDict(frozen=True)

    pattern_id: str
    pattern_version: str = "1.0.0"
    sport: str = "football"
    competition_scope: list[str]
    market: str
    selection_definition: str
    conditions: list[PatternCondition]
    feature_cutoff: str
    odds_type: str
    discovery_scope: dict[str, object]
    validation_scope: dict[str, object]
    occurrences: int = 0
    bets: int = 0
    average_odds: float | None = None
    roi_flat_stake: float | None = None
    profit_units: float | None = None
    max_drawdown_units: float | None = None
    hit_rate: float | None = None
    clv: float | None = None
    confidence_interval: tuple[float, float] | None = None
    q_value: float | None = None
    stability: dict[str, object] = Field(default_factory=dict)
    status: PatternStatus = PatternStatus.DISCOVERED
    evidence_scope: EvidenceScope = EvidenceScope.DISCOVERY_EXPOSED
    code_revision: str
    dataset_hashes: list[str]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    supersedes: str | None = None
    rule_hash: str

    @model_validator(mode="after")
    def enforce_scientific_status(self) -> PatternDefinition:
        if (
            self.status == PatternStatus.VALIDATED
            and self.evidence_scope != EvidenceScope.LIVE_PROSPECTIVE
        ):
            raise ValueError("HISTORICAL_EVIDENCE_CANNOT_VALIDATE_PATTERN")
        if not 1 <= len(self.conditions) <= 4:
            raise ValueError("PATTERN_CONDITION_COUNT_OUT_OF_RANGE")
        if len(self.conditions) == 4 and not self.discovery_scope.get(
            "preregistered", False
        ):
            raise ValueError("FOUR_CONDITIONS_REQUIRE_PREREGISTRATION")
        return self


def canonical_conditions(
    conditions: list[PatternCondition],
) -> list[dict[str, object]]:
    return sorted(
        (condition.canonical() for condition in conditions),
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )


def rule_hash(
    *,
    market: str,
    selection: str,
    conditions: list[PatternCondition],
) -> str:
    payload = {
        "conditions": canonical_conditions(conditions),
        "market": market,
        "selection": selection,
        "sport": "football",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def pattern_id_from_hash(digest: str) -> str:
    return f"PTRN-{digest[:16].upper()}"
