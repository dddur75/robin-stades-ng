"""Corrective V2 freeze with complete, non-backdated Git provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from robin.hypothesis_intelligence.contracts import (
    SHA256_LENGTH,
    HypothesisRecord,
    PriceContract,
    canonical_sha256,
    utc,
)
from robin.hypothesis_intelligence.prospective import _price
from robin.hypothesis_intelligence.registry import J10_TOP_IDS


@dataclass(frozen=True, slots=True)
class FreezeProvenance:
    source_code_revision: str
    source_tree_hash: str
    registry_hash: str
    generator_hash: str
    frozen_at: datetime

    def __post_init__(self) -> None:
        utc(self.frozen_at, field_name="frozen_at")
        if (
            len(self.source_code_revision) != 40
            or len(self.source_tree_hash) != 40
            or len(self.registry_hash) != SHA256_LENGTH
            or len(self.generator_hash) != SHA256_LENGTH
        ):
            raise ValueError("FREEZE_PROVENANCE_INVALID")


@dataclass(frozen=True, slots=True)
class ProspectiveHypothesisContractV2:
    contract_id: str
    contract_version: str
    hypothesis_id: str
    hypothesis_version: str
    source_code_revision: str
    source_tree_hash: str
    registry_hash: str
    rule_hash: str
    price_contract_hash: str
    generator_hash: str
    frozen_at: datetime
    primary_price: PriceContract
    secondary_price: PriceContract
    eligibility_contract: str
    supersedes: str
    promotion_locked: bool = True

    def __post_init__(self) -> None:
        utc(self.frozen_at, field_name="frozen_at")
        lengths = (
            len(self.source_code_revision) == 40,
            len(self.source_tree_hash) == 40,
            len(self.registry_hash) == 64,
            len(self.rule_hash) == 64,
            len(self.price_contract_hash) == 64,
            len(self.generator_hash) == 64,
        )
        if (
            not all(lengths)
            or self.contract_version != "2.0.0"
            or not self.supersedes.endswith(":1.0.0")
            or not self.promotion_locked
        ):
            raise ValueError("PROSPECTIVE_HYPOTHESIS_CONTRACT_V2_INVALID")

    @property
    def contract_hash(self) -> str:
        payload = asdict(self)
        payload["frozen_at"] = self.frozen_at.isoformat()
        return canonical_sha256(payload)


def combined_price_contract_hash(
    primary: PriceContract,
    secondary: PriceContract,
) -> str:
    return canonical_sha256(
        {
            "primary": {
                **asdict(primary),
                "contract_hash": primary.contract_hash,
            },
            "secondary": {
                **asdict(secondary),
                "contract_hash": secondary.contract_hash,
            },
        }
    )


def freeze_top_three_v2(
    records: tuple[HypothesisRecord, ...],
    provenance: FreezeProvenance,
) -> tuple[ProspectiveHypothesisContractV2, ...]:
    selected = {item.hypothesis_id: item for item in records}
    expected = tuple(J10_TOP_IDS.values())
    if any(identifier not in selected for identifier in expected):
        raise ValueError("J10_TOP_THREE_NOT_AVAILABLE")
    contracts: list[ProspectiveHypothesisContractV2] = []
    for identifier in expected:
        record = selected[identifier]
        primary = _price(record, "NEAR_KICKOFF")
        secondary = _price(record, "H-2")
        contracts.append(
            ProspectiveHypothesisContractV2(
                contract_id=f"{identifier}:2.0.0",
                contract_version="2.0.0",
                hypothesis_id=identifier,
                hypothesis_version="1.0.0",
                source_code_revision=provenance.source_code_revision,
                source_tree_hash=provenance.source_tree_hash,
                registry_hash=provenance.registry_hash,
                rule_hash=record.rule_hash,
                price_contract_hash=combined_price_contract_hash(
                    primary,
                    secondary,
                ),
                generator_hash=provenance.generator_hash,
                frozen_at=provenance.frozen_at,
                primary_price=primary,
                secondary_price=secondary,
                eligibility_contract=(
                    "CANONICAL_COMPETITION_IDENTITY;"
                    "STRICT_PRICE_AND_TEMPORAL_GATES;"
                    "FAIL_CLOSED_UNKNOWN_IDENTITY"
                ),
                supersedes=f"{identifier}:1.0.0",
            )
        )
    return tuple(contracts)


__all__ = [
    "FreezeProvenance",
    "ProspectiveHypothesisContractV2",
    "combined_price_contract_hash",
    "freeze_top_three_v2",
]
