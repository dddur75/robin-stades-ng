"""Décisions shadow reproductibles, candidates comme rejetées."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from robin.market_math import (
    DevigInputError,
    DevigMethod,
    devig_probabilities,
    kernel_versions,
)
from robin.temporal.lineage import (
    TEMPORAL_CONTRACT_VERSION,
    parse_utc,
)

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
    decision_business_key: str
    decision_input_hash: str
    legacy_decision_id: str
    supersedes_decision_id: str | None = None
    fixture_id: str
    market_key: str
    selection: str
    odds_decimal: float | None
    model_probability: float
    fair_probability: float | None
    edge: float | None
    scientific_kernel_version: str
    devig_method: str
    devig_effective_method: str | None
    devig_fallback_reason: str | None
    devig_version: str
    devig_definition_hash: str
    roi_definition_version: str
    turnover_definition_version: str
    yield_definition_version: str
    decision_threshold_version: str
    staking_version: str
    settlement_version: str
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
    cutoff_at: datetime | None = None
    feature_lineage_hash: str | None = None
    odds_receipt_id: str | None = None
    odds_available_at: datetime | None = None
    model_registry_hash: str | None = None
    model_available_at: datetime | None = None
    temporal_contract_version: str = TEMPORAL_CONTRACT_VERSION
    point_in_time_status: str = "POINT_IN_TIME_NOT_PROVEN"


def decide_shadow_bet(
    *,
    fixture_id: str,
    market_key: str,
    selection: str,
    market_odds: Mapping[str, float] | None,
    model_probability: float,
    devig_method: DevigMethod | str,
    strategy_version: str,
    quality_ok: bool,
    stale: bool = False,
    model_disagreement: bool = False,
    exposure_ok: bool = True,
    min_edge: float = 0.04,
    bankroll: float = 1000.0,
    origin: str = "DEMO DATA",
    prediction_id: str | None = None,
    cutoff_at: datetime | None = None,
    feature_lineage_hash: str | None = None,
    odds_receipt_id: str | None = None,
    odds_available_at: datetime | None = None,
    model_registry_hash: str | None = None,
    model_available_at: datetime | None = None,
    temporal_contract_version: str = TEMPORAL_CONTRACT_VERSION,
    point_in_time_status: str = "POINT_IN_TIME_NOT_PROVEN",
    decided_at: datetime | None = None,
) -> ShadowDecision:
    if (
        not math.isfinite(model_probability)
        or model_probability < 0.0
        or model_probability > 1.0
    ):
        raise ValueError("SHADOW_MODEL_PROBABILITY_INVALID")
    if not math.isfinite(min_edge) or not 0.0 <= min_edge <= 1.0:
        raise ValueError("SHADOW_EDGE_THRESHOLD_INVALID")
    if not math.isfinite(bankroll) or bankroll < 0.0:
        raise ValueError("SHADOW_BANKROLL_INVALID")
    decision_time = parse_utc(decided_at or datetime.now(UTC), field="decided_at")
    # Scalar hashes/timestamps, and even content-addressed in-memory dataclasses,
    # do not prove that the referenced evidence exists in an append-only receipt
    # repository.  Shadow has no repository binding yet, so promotion remains
    # fail-closed regardless of a caller's self-declared temporal status.
    effective_point_in_time_status = "POINT_IN_TIME_NOT_PROVEN"
    normalized_cutoff = (
        parse_utc(cutoff_at, field="cutoff_at") if cutoff_at is not None else None
    )
    normalized_odds_available = (
        parse_utc(odds_available_at, field="odds_available_at")
        if odds_available_at is not None
        else None
    )
    normalized_model_available = (
        parse_utc(model_available_at, field="model_available_at")
        if model_available_at is not None
        else None
    )
    reasons: list[RejectionCode] = []
    version_metadata = kernel_versions(devig_method)
    expected = (
        ("HOME", "DRAW", "AWAY")
        if market_key == "1X2"
        else ("OVER", "UNDER")
        if market_key == "OVER_UNDER_2_5"
        else ()
    )
    if not expected:
        raise ValueError(f"SHADOW_MARKET_UNKNOWN:{market_key}")
    if selection not in expected:
        raise ValueError("SHADOW_SELECTION_NOT_IN_MARKET")
    odds_decimal: float | None = None
    fair_probability: float | None = None
    devig_effective_method: str | None = None
    devig_fallback_reason: str | None = None
    if market_odds is None:
        reasons.append(RejectionCode.MISSING_ODDS)
    else:
        if set(market_odds) != set(expected):
            raise DevigInputError("DEVIG_MARKET_OUTCOMES_INCOMPLETE")
        devig = devig_probabilities(
            [market_odds[label] for label in expected],
            method=devig_method,
            outcome_labels=expected,
        )
        selected_index = expected.index(selection)
        odds_decimal = devig.input_odds[selected_index]
        fair_probability = devig.fair_probabilities[selected_index]
        devig_effective_method = devig.effective_method.value
        devig_fallback_reason = devig.fallback_reason
    edge = (
        model_probability - fair_probability
        if fair_probability is not None
        else None
    )
    if not quality_ok:
        reasons.append(RejectionCode.QUALITY_BLOCKED)
    reasons.append(RejectionCode.INSUFFICIENT_DATA)
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
    if accepted and stake <= 0.0:
        reasons.append(RejectionCode.EXPOSURE_LIMIT)
        accepted = False
        stake = 0.0
    legacy_key = "|".join(
        (
            fixture_id,
            market_key,
            selection,
            strategy_version,
            f"{odds_decimal}",
            f"{model_probability:.8f}",
        )
    )
    legacy_decision_id = str(uuid5(DECISION_NAMESPACE, legacy_key))
    business_payload = {
        "fixture_id": fixture_id,
        "market_key": market_key,
        "selection": selection,
        "strategy_version": strategy_version,
        "prediction_id": prediction_id,
        "legacy_key": legacy_key if prediction_id is None else None,
    }
    decision_business_key = hashlib.sha256(
        json.dumps(
            business_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    decision_input = {
        **business_payload,
        "market_odds": (
            {label: market_odds[label] for label in expected}
            if market_odds is not None
            else None
        ),
        "model_probability": model_probability,
        "devig_method": version_metadata["devig_method"],
        "devig_version": version_metadata["devig_version"],
        "devig_definition_hash": version_metadata["devig_definition_hash"],
        "quality_ok": quality_ok,
        "stale": stale,
        "model_disagreement": model_disagreement,
        "exposure_ok": exposure_ok,
        "min_edge": min_edge,
        "bankroll": bankroll,
        "origin": origin,
        "temporal_lineage": {
            "requested_point_in_time_status": point_in_time_status,
            "effective_point_in_time_status": effective_point_in_time_status,
            "cutoff_at": (
                normalized_cutoff.isoformat() if normalized_cutoff is not None else None
            ),
            "feature_lineage_hash": feature_lineage_hash,
            "odds_receipt_id": odds_receipt_id,
            "odds_available_at": (
                normalized_odds_available.isoformat()
                if normalized_odds_available is not None
                else None
            ),
            "model_registry_hash": model_registry_hash,
            "model_available_at": (
                normalized_model_available.isoformat()
                if normalized_model_available is not None
                else None
            ),
            "temporal_contract_version": temporal_contract_version,
            "repository_verified": False,
        },
    }
    decision_input_hash = hashlib.sha256(
        json.dumps(
            decision_input,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ShadowDecision(
        decision_id=str(uuid5(DECISION_NAMESPACE, decision_input_hash)),
        decision_business_key=decision_business_key,
        decision_input_hash=decision_input_hash,
        legacy_decision_id=legacy_decision_id,
        fixture_id=fixture_id,
        market_key=market_key,
        selection=selection,
        odds_decimal=odds_decimal,
        model_probability=model_probability,
        fair_probability=fair_probability,
        devig_effective_method=devig_effective_method,
        devig_fallback_reason=devig_fallback_reason,
        edge=edge,
        **version_metadata,
        strategy_version=strategy_version,
        quality_status="PASSED" if quality_ok else "BLOCKED",
        uncertainty_status="DISAGREEMENT" if model_disagreement else "NORMAL",
        suggested_stake=stake,
        accepted=accepted,
        primary_reason=reasons[0] if reasons else None,
        secondary_reasons=tuple(reasons[1:]),
        decided_at=decision_time,
        simulation=True,
        origin=origin,
        prediction_id=prediction_id,
        cutoff_at=normalized_cutoff,
        feature_lineage_hash=feature_lineage_hash,
        odds_receipt_id=odds_receipt_id,
        odds_available_at=normalized_odds_available,
        model_registry_hash=model_registry_hash,
        model_available_at=normalized_model_available,
        temporal_contract_version=temporal_contract_version,
        point_in_time_status=effective_point_in_time_status,
    )


class DecisionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: ShadowDecision) -> bool:
        rows = self.read_all()
        for item in rows:
            if item.get("decision_id") != decision.decision_id:
                continue
            stored = dict(item)
            candidate = decision.model_dump(mode="json")
            for payload in (stored, candidate):
                payload.pop("decided_at", None)
                payload.pop("supersedes_decision_id", None)
            if stored != candidate:
                raise ValueError("SHADOW_DECISION_IDEMPOTENCY_CONFLICT")
            return False
        effective = self._effective(rows)
        predecessor = next(
            (
                item
                for item in reversed(effective)
                if item.get("decision_business_key")
                == decision.decision_business_key
                or item.get("decision_id") == decision.legacy_decision_id
            ),
            None,
        )
        payload = decision.model_dump(mode="json")
        if predecessor is not None:
            payload["supersedes_decision_id"] = predecessor["decision_id"]
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
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

    @staticmethod
    def _effective(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        superseded = {
            str(item["supersedes_decision_id"])
            for item in rows
            if item.get("supersedes_decision_id")
        }
        return [
            item
            for item in rows
            if str(item.get("decision_id")) not in superseded
        ]

    def read_effective(self) -> list[dict[str, object]]:
        """Return logical current decisions while preserving all journal rows."""

        return self._effective(self.read_all())
