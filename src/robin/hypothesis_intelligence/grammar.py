"""Typed recursive hypothesis DSL, graph patterns and derivation DAG."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TypeAlias

from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.ontology import (
    PROPERTY_BY_ID,
    PUBLIC_HYPOTHESIS_SEMANTIC_ROLES,
    PropertyDataType,
    PropertyDefinition,
    SemanticRole,
)


class Operator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"
    BETWEEN = "BETWEEN"
    IN = "IN"
    NOT_IN = "NOT_IN"
    COUNT = "COUNT"
    RATE = "RATE"
    DIFFERENCE = "DIFFERENCE"
    RATIO = "RATIO"
    TREND = "TREND"
    SEQUENCE = "SEQUENCE"
    INTERACTION = "INTERACTION"
    GRAPH_PATTERN = "GRAPH_PATTERN"


class LogicalOperator(StrEnum):
    ALL = "ALL"
    ANY = "ANY"
    NOT = "NOT"


class MaterializationDisposition(StrEnum):
    SYMBOLIC_TEMPLATE = "SYMBOLIC_TEMPLATE"
    MATERIALIZED = "MATERIALIZED"
    EXECUTED = "EXECUTED"
    PRUNED = "PRUNED"
    DATA_GATE_BLOCKED = "DATA_GATE_BLOCKED"
    COMPUTE_DEFERRED = "COMPUTE_DEFERRED"
    LONG_TAIL_WATCHLIST = "LONG_TAIL_WATCHLIST"


class ScientificStatus(StrEnum):
    NOT_TESTED = "NOT_TESTED"
    DISCOVERED = "DISCOVERED"
    EXPLORATORY_SIGNAL = "EXPLORATORY_SIGNAL"
    REJECTED = "REJECTED"
    PROSPECTIVE_FROZEN = "PROSPECTIVE_FROZEN"
    VALIDATED = "VALIDATED"


class PruningReason(StrEnum):
    SEMANTICALLY_INVALID = "SEMANTICALLY_INVALID"
    TEMPORALLY_INVALID = "TEMPORALLY_INVALID"
    DATA_GATE_BLOCKED = "DATA_GATE_BLOCKED"
    ZERO_SUPPORT = "ZERO_SUPPORT"
    SUPPORT_TOO_LOW_FOR_TESTING = "SUPPORT_TOO_LOW_FOR_TESTING"
    REDUNDANT_WITH_PARENT = "REDUNDANT_WITH_PARENT"
    DOMINATED_BY_SIMPLER_RULE = "DOMINATED_BY_SIMPLER_RULE"
    EXCESSIVE_MISSINGNESS = "EXCESSIVE_MISSINGNESS"
    TEAM_CONCENTRATED = "TEAM_CONCENTRATED"
    TIME_CONCENTRATED = "TIME_CONCENTRATED"
    COMPUTE_DEFERRED = "COMPUTE_DEFERRED"
    LONG_TAIL_WATCHLIST = "LONG_TAIL_WATCHLIST"


Scalar: TypeAlias = bool | int | float | str
PredicateValue: TypeAlias = Scalar | tuple[Scalar, ...]


def _normalise_integer_operator(
    operator: Operator,
    value: PredicateValue,
    property_definition: PropertyDefinition,
) -> tuple[Operator, PredicateValue]:
    if property_definition.data_type is PropertyDataType.INTEGER and isinstance(value, int):
        if operator is Operator.GT:
            return Operator.GE, value + 1
        if operator is Operator.LT:
            return Operator.LE, value - 1
    return operator, value


@dataclass(frozen=True, slots=True)
class Predicate:
    property_id: str
    operator: Operator
    value: PredicateValue
    transform: str = "RAW"
    window: str = "CURRENT"
    relation: str = "APPLIES_TO"
    binding: str = "subject"
    learned_on: str = "FIXED_OR_TRAIN_ONLY"

    def canonical_payload(self) -> dict[str, object]:
        definition = PROPERTY_BY_ID.get(self.property_id)
        if definition is None:
            raise ValueError(f"UNKNOWN_FOOTBALL_PROPERTY:{self.property_id}")
        if self.operator.value not in definition.allowed_operators:
            raise ValueError(
                f"OPERATOR_NOT_ALLOWED_FOR_PROPERTY:{self.property_id}:{self.operator.value}"
            )
        operator, value = _normalise_integer_operator(
            self.operator,
            self.value,
            definition,
        )
        if operator in {Operator.IN, Operator.NOT_IN} and isinstance(value, tuple):
            value = tuple(sorted(value, key=str))
        return {
            "property_id": self.property_id,
            "operator": operator.value,
            "value": value,
            "transform": self.transform,
            "window": self.window,
            "relation": self.relation,
            "binding": self.binding,
            "learned_on": self.learned_on,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(self.canonical_payload())

    @property
    def semantic_role(self) -> SemanticRole:
        if self.learned_on == "LOGICAL_NEGATIVE_CONTROL":
            return SemanticRole.NEGATIVE_CONTROL
        definition = PROPERTY_BY_ID.get(self.property_id)
        if definition is None:
            raise ValueError(f"UNKNOWN_FOOTBALL_PROPERTY:{self.property_id}")
        return definition.semantic_role

    @property
    def public_hypothesis_eligible(self) -> bool:
        return self.semantic_role in PUBLIC_HYPOTHESIS_SEMANTIC_ROLES


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    entity_type: str
    binding: str


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source_binding: str
    relation: str
    target_binding: str
    valid_at: str = "AS_OF_CUTOFF"


@dataclass(frozen=True, slots=True)
class GraphPattern:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def __post_init__(self) -> None:
        bindings = {item.binding for item in self.nodes}
        if len(bindings) != len(self.nodes):
            raise ValueError("GRAPH_PATTERN_BINDING_COLLISION")
        if any(
            edge.source_binding not in bindings or edge.target_binding not in bindings
            for edge in self.edges
        ):
            raise ValueError("GRAPH_PATTERN_EDGE_BINDING_UNKNOWN")

    @property
    def fingerprint(self) -> str:
        return canonical_sha256(
            {
                "nodes": sorted(
                    (asdict(node) for node in self.nodes),
                    key=lambda item: str(item["binding"]),
                ),
                "edges": sorted(
                    (asdict(edge) for edge in self.edges),
                    key=lambda item: (
                        str(item["source_binding"]),
                        str(item["relation"]),
                        str(item["target_binding"]),
                    ),
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class HypothesisExpression:
    entity_scope: str
    context: tuple[str, ...]
    predicates: tuple[Predicate, ...]
    relation: str
    temporal_window: str
    cutoff: str
    target: str
    market: str | None
    price_contract: str | None
    logical_operator: LogicalOperator = LogicalOperator.ALL
    graph_pattern: GraphPattern | None = None

    def __post_init__(self) -> None:
        if not self.predicates and self.graph_pattern is None:
            raise ValueError("HYPOTHESIS_EXPRESSION_REQUIRES_CONTENT")
        if self.market is not None and self.price_contract is None:
            raise ValueError("MARKET_HYPOTHESIS_REQUIRES_PRICE_CONTRACT")
        if self.cutoff not in {
            "H-24",
            "H-2",
            "NEAR_KICKOFF",
            "POST_LINEUP",
        }:
            raise ValueError(f"UNKNOWN_HYPOTHESIS_CUTOFF:{self.cutoff}")
        for predicate in self.predicates:
            definition = PROPERTY_BY_ID.get(predicate.property_id)
            if definition is None:
                raise ValueError(f"UNKNOWN_FOOTBALL_PROPERTY:{predicate.property_id}")
            if self.target not in definition.allowed_targets:
                raise ValueError(
                    f"TARGET_NOT_ALLOWED_FOR_PROPERTY:{predicate.property_id}:{self.target}"
                )
            predicate.canonical_payload()

    @property
    def depth(self) -> int:
        return len(self.predicates) + int(self.graph_pattern is not None)

    def canonical_payload(self) -> dict[str, object]:
        predicate_payloads = [predicate.canonical_payload() for predicate in self.predicates]
        if self.logical_operator in {
            LogicalOperator.ALL,
            LogicalOperator.ANY,
        }:
            predicate_payloads.sort(key=lambda payload: canonical_sha256(payload))
        return {
            "entity_scope": self.entity_scope,
            "context": tuple(sorted(set(self.context))),
            "predicates": predicate_payloads,
            "relation": self.relation,
            "temporal_window": self.temporal_window,
            "cutoff": self.cutoff,
            "target": self.target,
            "market": self.market,
            "price_contract": self.price_contract,
            "logical_operator": self.logical_operator.value,
            "graph_pattern": (
                self.graph_pattern.fingerprint if self.graph_pattern is not None else None
            ),
        }

    @property
    def semantic_fingerprint(self) -> str:
        return canonical_sha256(self.canonical_payload())

    @property
    def semantic_roles(self) -> tuple[SemanticRole, ...]:
        return tuple(predicate.semantic_role for predicate in self.predicates)

    @property
    def public_hypothesis_eligible(self) -> bool:
        """Admit only substantive football predicates; unknown roles fail closed."""

        return bool(self.predicates) and all(
            role in PUBLIC_HYPOTHESIS_SEMANTIC_ROLES for role in self.semantic_roles
        )

    def require_public_hypothesis(self) -> None:
        if not self.public_hypothesis_eligible:
            roles = ",".join(role.value for role in self.semantic_roles) or "EMPTY"
            raise ValueError(f"PUBLIC_HYPOTHESIS_SEMANTIC_ROLE_FORBIDDEN:{roles}")


@dataclass(frozen=True, slots=True)
class HypothesisTreeNode:
    tree_id: str
    node_id: str
    parent_node_id: str | None
    parent_ids: tuple[str, ...]
    ancestor_ids: tuple[str, ...]
    depth: int
    generator_seed_id: str
    generation_engine: str
    generation_round: int
    added_condition: str | None
    removed_condition: str | None
    canonical_fingerprint: str
    expression: HypothesisExpression
    materialization_disposition: MaterializationDisposition
    scientific_status: ScientificStatus
    pruning_reason: PruningReason | None = None
    support: int | None = None

    def __post_init__(self) -> None:
        if self.depth != self.expression.depth:
            raise ValueError("HYPOTHESIS_TREE_DEPTH_MISMATCH")
        if self.canonical_fingerprint != self.expression.semantic_fingerprint:
            raise ValueError("HYPOTHESIS_TREE_FINGERPRINT_MISMATCH")
        if (
            self.materialization_disposition is MaterializationDisposition.PRUNED
            and self.pruning_reason is None
        ):
            raise ValueError("PRUNED_HYPOTHESIS_REQUIRES_REASON")
        if (
            self.materialization_disposition is MaterializationDisposition.COMPUTE_DEFERRED
            and self.scientific_status is not ScientificStatus.NOT_TESTED
        ):
            raise ValueError("COMPUTE_DEFERRED_IS_NOT_A_SCIENTIFIC_REJECTION")

    @property
    def payload_hash(self) -> str:
        payload = asdict(self)
        payload["materialization_disposition"] = self.materialization_disposition.value
        payload["scientific_status"] = self.scientific_status.value
        payload["pruning_reason"] = (
            self.pruning_reason.value if self.pruning_reason is not None else None
        )
        payload["expression"] = self.expression.canonical_payload()
        return canonical_sha256(payload)


def immediate_parent_fingerprints(
    expression: HypothesisExpression,
) -> tuple[str, ...]:
    if len(expression.predicates) <= 1:
        return ()
    fingerprints: list[str] = []
    for index in range(len(expression.predicates)):
        parent = HypothesisExpression(
            entity_scope=expression.entity_scope,
            context=expression.context,
            predicates=(expression.predicates[:index] + expression.predicates[index + 1 :]),
            relation=expression.relation,
            temporal_window=expression.temporal_window,
            cutoff=expression.cutoff,
            target=expression.target,
            market=expression.market,
            price_contract=expression.price_contract,
            logical_operator=expression.logical_operator,
            graph_pattern=expression.graph_pattern,
        )
        fingerprints.append(parent.semantic_fingerprint)
    return tuple(sorted(set(fingerprints)))


def make_tree_node(
    expression: HypothesisExpression,
    *,
    tree_id: str,
    generator_seed_id: str,
    generation_engine: str,
    generation_round: int,
    disposition: MaterializationDisposition,
    scientific_status: ScientificStatus = ScientificStatus.NOT_TESTED,
    pruning_reason: PruningReason | None = None,
    support: int | None = None,
) -> HypothesisTreeNode:
    parent_ids = tuple(
        f"hypothesis-node-{fingerprint}"
        for fingerprint in immediate_parent_fingerprints(expression)
    )
    parent_node_id = parent_ids[0] if parent_ids else None
    fingerprint = expression.semantic_fingerprint
    return HypothesisTreeNode(
        tree_id=tree_id,
        node_id=f"hypothesis-node-{fingerprint}",
        parent_node_id=parent_node_id,
        parent_ids=parent_ids,
        ancestor_ids=parent_ids,
        depth=expression.depth,
        generator_seed_id=generator_seed_id,
        generation_engine=generation_engine,
        generation_round=generation_round,
        added_condition=(expression.predicates[-1].fingerprint if expression.predicates else None),
        removed_condition=None,
        canonical_fingerprint=fingerprint,
        expression=expression,
        materialization_disposition=disposition,
        scientific_status=scientific_status,
        pruning_reason=pruning_reason,
        support=support,
    )


__all__ = [
    "GraphEdge",
    "GraphNode",
    "GraphPattern",
    "HypothesisExpression",
    "HypothesisTreeNode",
    "LogicalOperator",
    "MaterializationDisposition",
    "Operator",
    "Predicate",
    "PruningReason",
    "ScientificStatus",
    "immediate_parent_fingerprints",
    "make_tree_node",
]
