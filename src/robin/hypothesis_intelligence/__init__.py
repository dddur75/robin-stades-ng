"""Hypothesis Intelligence Factory V1 public surface."""

from robin.hypothesis_intelligence.competition_identity import (
    CompetitionIdentity,
    resolve_competition,
    same_competition,
)
from robin.hypothesis_intelligence.contracts import (
    HypothesisEventKind,
    HypothesisObservation,
    HypothesisOrigin,
    HypothesisRecord,
    HypothesisSettlement,
    HypothesisStatus,
    ObservationStatus,
    PriceContract,
    ProspectiveHypothesisContract,
)
from robin.hypothesis_intelligence.engines import (
    DiscoveryEngine,
    ProspectiveObservationEngine,
    ValidationEngine,
)
from robin.hypothesis_intelligence.freeze_v2 import (
    FreezeProvenance,
    ProspectiveHypothesisContractV2,
    freeze_top_three_v2,
)
from robin.hypothesis_intelligence.grammar import (
    GraphPattern,
    HypothesisExpression,
    HypothesisTreeNode,
    MaterializationDisposition,
    Operator,
    Predicate,
    ScientificStatus,
)
from robin.hypothesis_intelligence.ledger import HypothesisLedger
from robin.hypothesis_intelligence.ontology import (
    PROPERTY_UNIVERSE,
    PropertyDefinition,
)
from robin.hypothesis_intelligence.prospective import (
    HypothesisSettlementRegistry,
    evaluate_fixture,
    freeze_top_three,
)
from robin.hypothesis_intelligence.registry import (
    import_j10_registry,
    owner_registry,
    rank_hypotheses,
)
from robin.hypothesis_intelligence.universal_engines import (
    DiscoveryBudget,
    UniversalTreeExplorer,
)

__all__ = [
    "DiscoveryEngine",
    "DiscoveryBudget",
    "CompetitionIdentity",
    "FreezeProvenance",
    "GraphPattern",
    "HypothesisEventKind",
    "HypothesisLedger",
    "HypothesisObservation",
    "HypothesisOrigin",
    "HypothesisRecord",
    "HypothesisExpression",
    "HypothesisTreeNode",
    "HypothesisSettlement",
    "HypothesisSettlementRegistry",
    "HypothesisStatus",
    "ObservationStatus",
    "Operator",
    "PROPERTY_UNIVERSE",
    "Predicate",
    "PriceContract",
    "ProspectiveHypothesisContract",
    "ProspectiveHypothesisContractV2",
    "ProspectiveObservationEngine",
    "ValidationEngine",
    "MaterializationDisposition",
    "PropertyDefinition",
    "ScientificStatus",
    "UniversalTreeExplorer",
    "evaluate_fixture",
    "freeze_top_three",
    "freeze_top_three_v2",
    "import_j10_registry",
    "owner_registry",
    "rank_hypotheses",
    "resolve_competition",
    "same_competition",
]
