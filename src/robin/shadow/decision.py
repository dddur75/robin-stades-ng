"""Décisions shadow reproductibles, candidates comme rejetées."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

DECISION_NAMESPACE = UUID("8e34b21f-b7e4-4b95-9f8a-8ae742bbf96f")


class RejectionCode(StrEnum):
    INSUFFICIENT_EDGE = "INSUFFICIENT_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"
    MISSING_ODDS = "MISSING_ODDS"
    MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
    UNCERTAINTY_TOO_HIGH = "UNCERTAINTY_TOO_HIGH"
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    DUPLICATE_OPPORTUNITY = "DUPLICATE_OPPORTUNITY"
    OUTSIDE_STRATEGY = "OUTSIDE_STRATEGY"
    LINEUP_REQUIRED = "LINEUP_REQUIRED"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"


class ShadowDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str
    fixture_id: str
    market_key: str
    selection: str
    odds_decimal: float | None
    model_probability: float
    implied_probability: float | None
    edge: float | None
    strategy_version: str
    quality_status: str
    uncertainty_status: str
    suggested_stake: float
    accepted: bool
    primary_reason: RejectionCode | None
    secondary_reasons: tuple[RejectionCode, ...] = ()
    decided_at: datetime
    simulation: bool = True
    origin: str = "DEMO DATA"
    prediction_id: str | None = None


def decide_shadow_bet(
    *,
    fixture_id: str,
    market_key: str,
    selection: str,
    odds_decimal: float | None,
    model_probability: float,
    strategy_version: str,
    quality_ok: bool,
    stale: bool = False,
    model_disagreement: bool = False,
    exposure_ok: bool = True,
    min_edge: float = 0.04,
    bankroll: float = 1000.0,
    origin: str = "DEMO DATA",
    prediction_id: str | None = None,
) -> ShadowDecision:
    reasons: list[RejectionCode] = []
    implied = 1.0 / odds_decimal if odds_decimal else None
    edge = model_probability - implied if implied is not None else None
    if odds_decimal is None:
        reasons.append(RejectionCode.MISSING_ODDS)
    if not quality_ok:
        reasons.append(RejectionCode.QUALITY_BLOCKED)
    if stale:
        reasons.append(RejectionCode.STALE_DATA)
    if model_disagreement:
        reasons.append(RejectionCode.MODEL_DISAGREEMENT)
    if not exposure_ok:
        reasons.append(RejectionCode.EXPOSURE_LIMIT)
    if edge is not None and edge < min_edge:
        reasons.append(RejectionCode.INSUFFICIENT_EDGE)
    accepted = not reasons
    stake = min(bankroll * 0.01, 10.0) if accepted else 0.0
    key = "|".join(
        (
            fixture_id,
            market_key,
            selection,
            strategy_version,
            f"{odds_decimal}",
            f"{model_probability:.8f}",
        )
    )
    return ShadowDecision(
        decision_id=str(uuid5(DECISION_NAMESPACE, key)),
        fixture_id=fixture_id,
        market_key=market_key,
        selection=selection,
        odds_decimal=odds_decimal,
        model_probability=model_probability,
        implied_probability=implied,
        edge=edge,
        strategy_version=strategy_version,
        quality_status="PASSED" if quality_ok else "BLOCKED",
        uncertainty_status="DISAGREEMENT" if model_disagreement else "NORMAL",
        suggested_stake=stake,
        accepted=accepted,
        primary_reason=reasons[0] if reasons else None,
        secondary_reasons=tuple(reasons[1:]),
        decided_at=datetime.now(UTC),
        simulation=True,
        origin=origin,
        prediction_id=prediction_id,
    )


class DecisionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: ShadowDecision) -> bool:
        known = {item["decision_id"] for item in self.read_all()}
        if decision.decision_id in known:
            return False
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(decision.model_dump_json())
            stream.write("\n")
        return True

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text("utf-8").splitlines()
            if line.strip()
        ]
