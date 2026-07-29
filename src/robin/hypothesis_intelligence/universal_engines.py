"""Deterministic, bounded engines for the universal hypothesis grammar."""

from __future__ import annotations

import itertools
import math
import random
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterator, Mapping, Sequence

from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.grammar import (
    GraphPattern,
    HypothesisExpression,
    HypothesisTreeNode,
    MaterializationDisposition,
    Operator,
    Predicate,
    PruningReason,
    ScientificStatus,
    make_tree_node,
)
from robin.hypothesis_intelligence.ontology import (
    PROPERTY_BY_ID,
    AvailabilityStatus,
)

NumericRow = Mapping[str, float]


@dataclass(frozen=True, slots=True)
class DiscoveryBudget:
    wall_clock_budget_seconds: float = 30.0
    memory_budget_bytes: int = 536_870_912
    maximum_materialized_nodes: int = 5_000
    maximum_evaluated_nodes: int = 2_000
    checkpoint_frequency: int = 100
    beam_width: int = 32
    expansion_batch_size: int = 128
    maximum_depth: int = 6

    def __post_init__(self) -> None:
        if (
            self.wall_clock_budget_seconds <= 0
            or self.memory_budget_bytes <= 0
            or self.maximum_materialized_nodes <= 0
            or self.maximum_evaluated_nodes <= 0
            or self.checkpoint_frequency <= 0
            or self.beam_width <= 0
            or self.expansion_batch_size <= 0
            or self.maximum_depth <= 0
        ):
            raise ValueError("UNIVERSAL_DISCOVERY_BUDGET_INVALID")


@dataclass(frozen=True, slots=True)
class GenerationCheckpoint:
    frontier: tuple[str, ...]
    seen_fingerprints: tuple[str, ...]
    random_seed: int
    random_draws: int
    ontology_hash: str
    campaign_hash: str
    data_hash: str
    code_hash: str
    generated: int
    materialized: int
    evaluated: int

    @property
    def checkpoint_hash(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True, slots=True)
class GenerationResult:
    nodes: tuple[HypothesisTreeNode, ...]
    generated: int
    materialized: int
    executed: int
    pruned: int
    blocked: int
    compute_deferred: int
    long_tail: int
    parents_expanded: int
    maximum_depth_reached: int
    checkpoint: GenerationCheckpoint

    @property
    def replay_hash(self) -> str:
        return canonical_sha256(
            [
                {
                    "node_id": node.node_id,
                    "payload_hash": node.payload_hash,
                    "disposition": node.materialization_disposition.value,
                    "scientific_status": node.scientific_status.value,
                }
                for node in self.nodes
            ]
        )


def _expression(
    predicates: tuple[Predicate, ...],
    *,
    target: str = "MATCH_RESULT",
    market: str | None = None,
    price_contract: str | None = None,
    graph_pattern: GraphPattern | None = None,
) -> HypothesisExpression:
    return HypothesisExpression(
        entity_scope="TEAM_FIXTURE",
        context=("PRE_MATCH",),
        predicates=predicates,
        relation="INTERACTS_WITH",
        temporal_window="AS_OF_CUTOFF",
        cutoff="H-2",
        target=target,
        market=market,
        price_contract=price_contract,
        graph_pattern=graph_pattern,
    )


class TypedEnumerationEngine:
    engine_version = "typed-enumeration-v2"

    def iter_expressions(
        self,
        predicates: Sequence[Predicate],
        *,
        maximum_depth: int,
    ) -> Iterator[HypothesisExpression]:
        if maximum_depth < 1:
            raise ValueError("ENUMERATION_DEPTH_MUST_BE_POSITIVE")
        canonical = sorted(predicates, key=lambda item: item.fingerprint)
        for depth in range(1, min(maximum_depth, len(canonical)) + 1):
            for combination in itertools.combinations(canonical, depth):
                yield _expression(combination)


class AprioriEngine:
    engine_version = "apriori-v2"

    def mine(
        self,
        transactions: Sequence[frozenset[str]],
        *,
        minimum_support: int,
        maximum_depth: int,
    ) -> tuple[tuple[tuple[str, ...], int], ...]:
        if minimum_support < 1 or maximum_depth < 1:
            raise ValueError("APRIORI_CONFIGURATION_INVALID")
        singletons = sorted(set().union(*transactions) if transactions else set())
        previous: set[tuple[str, ...]] = {(item,) for item in singletons}
        output: list[tuple[tuple[str, ...], int]] = []
        for depth in range(1, maximum_depth + 1):
            frequent: set[tuple[str, ...]] = set()
            for candidate in sorted(previous):
                support = sum(set(candidate) <= transaction for transaction in transactions)
                if support >= minimum_support:
                    frequent.add(candidate)
                    output.append((candidate, support))
            if not frequent:
                break
            joined: set[tuple[str, ...]] = set()
            frequent_list = sorted(frequent)
            for left, right in itertools.combinations(frequent_list, 2):
                candidate = tuple(sorted(set(left) | set(right)))
                if len(candidate) != depth + 1:
                    continue
                if all(
                    tuple(subset) in frequent for subset in itertools.combinations(candidate, depth)
                ):
                    joined.add(candidate)
            previous = joined
        return tuple(output)


class BeamSearchEngine:
    engine_version = "hierarchical-beam-v2"

    def select(
        self,
        candidates: Sequence[HypothesisTreeNode],
        *,
        beam_width: int,
    ) -> tuple[HypothesisTreeNode, ...]:
        def score(node: HypothesisTreeNode) -> tuple[float, str]:
            support = float(node.support or 0)
            quality = sum(
                PROPERTY_BY_ID[predicate.property_id].availability_status
                is not AvailabilityStatus.DATA_GATE_BLOCKED
                for predicate in node.expression.predicates
            )
            complexity_cost = node.depth * math.log2(node.depth + 1)
            priority = math.log1p(support) + quality - complexity_cost
            return (-priority, node.node_id)

        return tuple(sorted(candidates, key=score)[:beam_width])


@dataclass(frozen=True, slots=True)
class Subgroup:
    label: str
    support: int
    mean_target: float
    reference_mean: float
    weighted_relative_accuracy: float


class SubgroupDiscoveryEngine:
    engine_version = "subgroup-wracc-v2"

    def discover(
        self,
        groups: Sequence[str],
        targets: Sequence[float],
    ) -> tuple[Subgroup, ...]:
        if len(groups) != len(targets) or not targets:
            raise ValueError("SUBGROUP_INPUT_INVALID")
        reference = statistics.fmean(targets)
        output: list[Subgroup] = []
        for label in sorted(set(groups)):
            values = [
                target for group, target in zip(groups, targets, strict=True) if group == label
            ]
            mean = statistics.fmean(values)
            weight = len(values) / len(targets)
            output.append(
                Subgroup(
                    label=label,
                    support=len(values),
                    mean_target=mean,
                    reference_mean=reference,
                    weighted_relative_accuracy=weight * (mean - reference),
                )
            )
        return tuple(
            sorted(
                output,
                key=lambda item: (-abs(item.weighted_relative_accuracy), item.label),
            )
        )


class RulePathEngine:
    engine_version = "train-only-rule-path-v2"

    def fit_predicate(
        self,
        property_id: str,
        training_values: Sequence[float],
    ) -> Predicate:
        if not training_values:
            raise ValueError("RULE_PATH_TRAINING_VALUES_REQUIRED")
        threshold = statistics.median(training_values)
        return Predicate(
            property_id=property_id,
            operator=Operator.GE,
            value=float(threshold),
            transform="TREE_PATH_THRESHOLD",
            window="TRAIN_WINDOW",
            learned_on="TRAIN_ONLY",
        )


@dataclass(frozen=True, slots=True)
class SymbolicTerm:
    left_property: str
    operation: str
    right_property: str
    score: float
    complexity_cost: float


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if left_scale == 0 or right_scale == 0:
        return 0.0
    return numerator / (left_scale * right_scale)


class SymbolicRegressionEngine:
    engine_version = "symbolic-regression-v2"

    def fit(
        self,
        features: Mapping[str, Sequence[float]],
        target: Sequence[float],
    ) -> SymbolicTerm:
        best: SymbolicTerm | None = None
        for left, right in itertools.combinations(sorted(features), 2):
            left_values = features[left]
            right_values = features[right]
            if len(left_values) != len(target) or len(right_values) != len(target):
                raise ValueError("SYMBOLIC_REGRESSION_ROW_MISMATCH")
            combined = [
                left_value - right_value
                for left_value, right_value in zip(
                    left_values,
                    right_values,
                    strict=True,
                )
            ]
            raw_score = abs(_pearson(combined, target))
            candidate = SymbolicTerm(
                left_property=left,
                operation="DIFFERENCE",
                right_property=right,
                score=raw_score - 0.02,
                complexity_cost=0.02,
            )
            if best is None or (candidate.score, left, right) > (
                best.score,
                best.left_property,
                best.right_property,
            ):
                best = candidate
        if best is None:
            raise ValueError("SYMBOLIC_REGRESSION_REQUIRES_TWO_FEATURES")
        return best


class GeneticProgrammingEngine:
    engine_version = "genetic-programming-v2"

    def mutate(
        self,
        predicate: Predicate,
        *,
        seed: int,
    ) -> Predicate:
        if not isinstance(predicate.value, int | float):
            raise ValueError("GENETIC_MUTATION_REQUIRES_NUMERIC_PREDICATE")
        # Deterministic scientific replay only; no security token is produced here.
        generator = random.Random(seed)  # nosec B311
        step = generator.choice((-1.0, -0.5, 0.5, 1.0))
        return Predicate(
            property_id=predicate.property_id,
            operator=predicate.operator,
            value=float(predicate.value) + step,
            transform=f"{predicate.transform}:MUTATION",
            window=predicate.window,
            relation=predicate.relation,
            binding=predicate.binding,
            learned_on=predicate.learned_on,
        )

    def crossover(
        self,
        left: HypothesisExpression,
        right: HypothesisExpression,
    ) -> HypothesisExpression:
        predicates = {
            predicate.fingerprint: predicate for predicate in (*left.predicates, *right.predicates)
        }
        return _expression(tuple(predicates[key] for key in sorted(predicates)))


@dataclass(frozen=True, slots=True)
class MctsChoice:
    action: str
    visits: int
    mean_reward: float
    ucb_score: float


class MonteCarloTreeSearchEngine:
    engine_version = "mcts-ucb-v2"

    def choose(
        self,
        rewards: Mapping[str, Sequence[float]],
        *,
        parent_visits: int,
    ) -> MctsChoice:
        if parent_visits < 1 or not rewards:
            raise ValueError("MCTS_STATE_INVALID")
        choices: list[MctsChoice] = []
        for action in sorted(rewards):
            values = rewards[action]
            if not values:
                score = math.inf
                mean = 0.0
                visits = 0
            else:
                visits = len(values)
                mean = statistics.fmean(values)
                score = mean + math.sqrt(2 * math.log(parent_visits) / visits)
            choices.append(MctsChoice(action, visits, mean, score))
        return max(choices, key=lambda item: (item.ucb_score, item.action))


@dataclass(frozen=True, slots=True)
class ResidualSignal:
    property_id: str
    correlation: float
    support: int


class ResidualMiningEngine:
    engine_version = "residual-mining-v2"

    def discover(
        self,
        features: Mapping[str, Sequence[float]],
        outcomes: Sequence[float],
        baselines: Sequence[float],
    ) -> tuple[ResidualSignal, ...]:
        if len(outcomes) != len(baselines):
            raise ValueError("RESIDUAL_BASELINE_ROW_MISMATCH")
        residuals = [
            outcome - baseline for outcome, baseline in zip(outcomes, baselines, strict=True)
        ]
        return tuple(
            sorted(
                (
                    ResidualSignal(
                        property_id=property_id,
                        correlation=_pearson(values, residuals),
                        support=len(values),
                    )
                    for property_id, values in features.items()
                    if len(values) == len(residuals)
                ),
                key=lambda item: (-abs(item.correlation), item.property_id),
            )
        )


class TemporalMotifEngine:
    engine_version = "temporal-motif-v2"

    def mine(
        self,
        sequences: Sequence[Sequence[str]],
        *,
        motif_length: int,
    ) -> tuple[tuple[tuple[str, ...], int], ...]:
        if motif_length < 1:
            raise ValueError("TEMPORAL_MOTIF_LENGTH_INVALID")
        counts: Counter[tuple[str, ...]] = Counter()
        for sequence in sequences:
            for index in range(len(sequence) - motif_length + 1):
                counts[tuple(sequence[index : index + motif_length])] += 1
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class GraphPatternMiningEngine:
    engine_version = "graph-pattern-v2"

    def mine(
        self,
        graph: GraphPattern,
    ) -> tuple[tuple[str, int], ...]:
        degrees: Counter[str] = Counter()
        for edge in graph.edges:
            degrees[edge.source_binding] += 1
            degrees[edge.target_binding] += 1
        return tuple(sorted(degrees.items(), key=lambda item: (-item[1], item[0])))


class AiProposalCompiler:
    engine_version = "ai-proposal-compiler-v2"

    def compile(
        self,
        proposal: Mapping[str, object],
    ) -> HypothesisExpression:
        raw_predicates = proposal.get("predicates")
        if not isinstance(raw_predicates, list):
            raise ValueError("AI_PROPOSAL_PREDICATES_REQUIRED")
        predicates: list[Predicate] = []
        for raw in raw_predicates:
            if not isinstance(raw, dict):
                raise ValueError("AI_PROPOSAL_PREDICATE_INVALID")
            property_id = raw.get("property_id")
            operator = raw.get("operator")
            value = raw.get("value")
            if not isinstance(property_id, str) or not isinstance(operator, str):
                raise ValueError("AI_PROPOSAL_PREDICATE_INVALID")
            if not isinstance(value, bool | int | float | str):
                raise ValueError("AI_PROPOSAL_VALUE_MUST_BE_TYPED_SCALAR")
            predicates.append(
                Predicate(
                    property_id=property_id,
                    operator=Operator(operator),
                    value=value,
                    learned_on="AI_PROPOSED_NO_NUMERIC_EVIDENCE",
                )
            )
        target = proposal.get("target", "MATCH_RESULT")
        if not isinstance(target, str):
            raise ValueError("AI_PROPOSAL_TARGET_INVALID")
        return _expression(tuple(predicates), target=target)


class UniversalTreeExplorer:
    engine_version = "universal-tree-explorer-v2"

    def explore(
        self,
        predicates: Sequence[Predicate],
        *,
        budget: DiscoveryBudget,
        support_by_fingerprint: Mapping[str, int],
        ontology_hash: str,
        campaign_hash: str,
        data_hash: str,
        code_hash: str,
        random_seed: int = 20260729,
    ) -> GenerationResult:
        enumerator = TypedEnumerationEngine()
        nodes: list[HypothesisTreeNode] = []
        generated = 0
        materialized = 0
        executed = 0
        pruned = 0
        blocked = 0
        compute_deferred = 0
        long_tail = 0
        maximum_depth_reached = 0
        frontier: list[str] = []
        seen: set[str] = set()

        for expression in enumerator.iter_expressions(
            predicates,
            maximum_depth=budget.maximum_depth,
        ):
            generated += 1
            fingerprint = expression.semantic_fingerprint
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            maximum_depth_reached = max(maximum_depth_reached, expression.depth)
            if materialized >= budget.maximum_materialized_nodes:
                frontier.append(fingerprint)
                compute_deferred += 1
                continue
            materialized += 1
            definitions = [
                PROPERTY_BY_ID[predicate.property_id] for predicate in expression.predicates
            ]
            support = support_by_fingerprint.get(fingerprint)
            if any(
                definition.availability_status is AvailabilityStatus.DATA_GATE_BLOCKED
                for definition in definitions
            ):
                disposition = MaterializationDisposition.DATA_GATE_BLOCKED
                pruning_reason = PruningReason.DATA_GATE_BLOCKED
                blocked += 1
            elif support == 0:
                disposition = MaterializationDisposition.PRUNED
                pruning_reason = PruningReason.ZERO_SUPPORT
                pruned += 1
            elif support is None:
                disposition = MaterializationDisposition.LONG_TAIL_WATCHLIST
                pruning_reason = PruningReason.LONG_TAIL_WATCHLIST
                long_tail += 1
            elif support is not None and support < 30:
                disposition = MaterializationDisposition.LONG_TAIL_WATCHLIST
                pruning_reason = PruningReason.LONG_TAIL_WATCHLIST
                long_tail += 1
            elif executed >= budget.maximum_evaluated_nodes:
                disposition = MaterializationDisposition.COMPUTE_DEFERRED
                pruning_reason = PruningReason.COMPUTE_DEFERRED
                compute_deferred += 1
            else:
                disposition = MaterializationDisposition.EXECUTED
                pruning_reason = None
                executed += 1
            nodes.append(
                make_tree_node(
                    expression,
                    tree_id="UNIVERSAL_FOOTBALL_TREE_V1",
                    generator_seed_id=f"seed-{random_seed}",
                    generation_engine=self.engine_version,
                    generation_round=expression.depth,
                    disposition=disposition,
                    scientific_status=ScientificStatus.NOT_TESTED,
                    pruning_reason=pruning_reason,
                    support=support,
                )
            )
        checkpoint = GenerationCheckpoint(
            frontier=tuple(sorted(frontier)),
            seen_fingerprints=tuple(sorted(seen)),
            random_seed=random_seed,
            random_draws=0,
            ontology_hash=ontology_hash,
            campaign_hash=campaign_hash,
            data_hash=data_hash,
            code_hash=code_hash,
            generated=generated,
            materialized=materialized,
            evaluated=executed,
        )
        return GenerationResult(
            nodes=tuple(nodes),
            generated=generated,
            materialized=materialized,
            executed=executed,
            pruned=pruned,
            blocked=blocked,
            compute_deferred=compute_deferred,
            long_tail=long_tail,
            parents_expanded=sum(node.depth < maximum_depth_reached for node in nodes),
            maximum_depth_reached=maximum_depth_reached,
            checkpoint=checkpoint,
        )


__all__ = [
    "AiProposalCompiler",
    "AprioriEngine",
    "BeamSearchEngine",
    "DiscoveryBudget",
    "GenerationCheckpoint",
    "GenerationResult",
    "GeneticProgrammingEngine",
    "GraphPatternMiningEngine",
    "MctsChoice",
    "MonteCarloTreeSearchEngine",
    "ResidualMiningEngine",
    "ResidualSignal",
    "RulePathEngine",
    "Subgroup",
    "SubgroupDiscoveryEngine",
    "SymbolicRegressionEngine",
    "SymbolicTerm",
    "TemporalMotifEngine",
    "TypedEnumerationEngine",
    "UniversalTreeExplorer",
]
