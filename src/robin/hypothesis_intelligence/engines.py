"""Separated discovery, validation and prospective observation engines."""

from __future__ import annotations

from dataclasses import dataclass

from robin.hypothesis_intelligence.contracts import (
    HypothesisRecord,
    ProspectiveHypothesisContract,
)
from robin.hypothesis_intelligence.prospective import freeze_top_three
from robin.hypothesis_intelligence.registry import (
    Ranking,
    import_j10_registry,
    rank_hypotheses,
)


@dataclass(frozen=True, slots=True)
class DiscoveryEngine:
    engine_version: str = "hypothesis-discovery-v1"

    def import_campaign(
        self,
        rules: list[dict[str, object]],
        campaign: dict[str, object],
    ) -> tuple[HypothesisRecord, ...]:
        return import_j10_registry(rules, campaign)


@dataclass(frozen=True, slots=True)
class ValidationEngine:
    engine_version: str = "hypothesis-validation-v1"

    def rank(
        self,
        records: tuple[HypothesisRecord, ...],
    ) -> tuple[Ranking, ...]:
        return rank_hypotheses(records)

    def promote(self, _record: HypothesisRecord) -> None:
        raise ValueError("HYPOTHESIS_ENGINE_SELF_PROMOTION_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class ProspectiveObservationEngine:
    engine_version: str = "hypothesis-prospective-observation-v1"

    def freeze(
        self,
        records: tuple[HypothesisRecord, ...],
    ) -> tuple[ProspectiveHypothesisContract, ...]:
        return freeze_top_three(records)

    def validate(self, _contract: ProspectiveHypothesisContract) -> None:
        raise ValueError("AUTOMATIC_HYPOTHESIS_VALIDATION_FORBIDDEN")


__all__ = [
    "DiscoveryEngine",
    "ProspectiveObservationEngine",
    "ValidationEngine",
]
