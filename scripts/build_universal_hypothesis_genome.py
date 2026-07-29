"""Build bounded Universal Football Hypothesis Genome V2 contracts cache-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import tracemalloc
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from robin.hypothesis_intelligence.campaigns import CAMPAIGNS, campaign_catalog
from robin.hypothesis_intelligence.competition_identity import competition_catalog
from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.freeze_v2 import (
    FreezeProvenance,
    freeze_top_three_v2,
)
from robin.hypothesis_intelligence.grammar import (
    GraphEdge,
    GraphNode,
    GraphPattern,
    Operator,
    Predicate,
)
from robin.hypothesis_intelligence.ontology import (
    DAY_WINDOWS,
    FAMILY_SEEDS,
    MATCH_WINDOWS,
    PROPERTY_BY_ID,
    PROPERTY_UNIVERSE,
    PROPERTY_UNIVERSE_ID,
    RELATION_CATALOG,
    TRANSFORMATION_CATALOG,
    property_universe_hash,
    source_field_audit,
)
from robin.hypothesis_intelligence.registry import (
    J10_REGISTRY_SHA256,
    import_j10_registry,
    load_jsonl,
)
from robin.hypothesis_intelligence.universal_engines import (
    AiProposalCompiler,
    AprioriEngine,
    DiscoveryBudget,
    GeneticProgrammingEngine,
    GraphPatternMiningEngine,
    MonteCarloTreeSearchEngine,
    ResidualMiningEngine,
    RulePathEngine,
    SubgroupDiscoveryEngine,
    SymbolicRegressionEngine,
    TemporalMotifEngine,
    TypedEnumerationEngine,
    UniversalTreeExplorer,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "hypothesis-genome"
DEFAULT_ARTIFACT_OUTPUT = ROOT / "artifacts" / "hypothesis-genome"
J10_REGISTRY = ROOT / ".ci" / "hypothesis-j10" / "hypothesis-registry.jsonl"
J10_CAMPAIGN = ROOT / "reports" / "pattern-research" / "campaign-summary.json"
J11_CAMPAIGN = ROOT / "reports" / "jalon11" / "campaign-summary.json"
J11_FEATURES = ROOT / "reports" / "jalon11" / "feature-contract-v2.json"
J11_COVERAGE = ROOT / "reports" / "jalon11" / "coverage-matrix.json"


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return payload


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pilot_predicates() -> tuple[Predicate, ...]:
    return (
        Predicate(
            "football:strength_form:elo",
            Operator.GE,
            0.0,
            transform="DIFFERENCE",
            window="CURRENT",
            learned_on="FIXED_DIAGNOSTIC",
        ),
        Predicate(
            "football:strength_form:form",
            Operator.GE,
            0.5,
            transform="ROLLING_MEAN",
            window="MATCHES_5",
            learned_on="TRAIN_ONLY",
        ),
        Predicate(
            "football:attack:goals_scored",
            Operator.GE,
            1.0,
            transform="ROLLING_MEAN",
            window="MATCHES_5",
            learned_on="TRAIN_ONLY",
        ),
        Predicate(
            "football:defence:goals_conceded",
            Operator.GE,
            1.0,
            transform="ROLLING_MEAN",
            window="MATCHES_5",
            learned_on="TRAIN_ONLY",
        ),
        Predicate(
            "football:calendar_fatigue:rest_days",
            Operator.LE,
            3.0,
            learned_on="FIXED_DIAGNOSTIC",
        ),
        Predicate(
            "football:calendar_fatigue:rest_days",
            Operator.LT,
            0.0,
            learned_on="LOGICAL_NEGATIVE_CONTROL",
        ),
        Predicate(
            "football:market:market_margin",
            Operator.LE,
            0.08,
            learned_on="FIXED_HISTORICAL_PRICE_CLASS",
        ),
        Predicate(
            "football:data_quality:missingness",
            Operator.GE,
            0.25,
            learned_on="SYMBOLIC_LONG_TAIL_TEMPLATE",
        ),
        Predicate(
            "football:formation_structure:formation",
            Operator.EQ,
            "4-3-3",
            learned_on="SYMBOLIC_TEMPLATE_ONLY",
        ),
        Predicate(
            "football:discipline_referee:suspension_threat",
            Operator.EQ,
            True,
            learned_on="SYMBOLIC_TEMPLATE_ONLY",
        ),
        Predicate(
            "football:player:preferred_foot",
            Operator.EQ,
            "LEFT",
            learned_on="SYMBOLIC_TEMPLATE_ONLY_NEVER_INFER",
        ),
        Predicate(
            "football:weather:crosswind_component",
            Operator.GE,
            10.0,
            learned_on="SYMBOLIC_TEMPLATE_ONLY",
        ),
        Predicate(
            "football:travel_logistics:consecutive_away_matches",
            Operator.GE,
            3.0,
            learned_on="SYMBOLIC_TEMPLATE_ONLY",
        ),
    )


def _support_map(
    predicates: tuple[Predicate, ...],
    *,
    team_rows: int,
    market_rows: int,
) -> dict[str, int]:
    output: dict[str, int] = {}
    enumerator = TypedEnumerationEngine()
    for expression in enumerator.iter_expressions(predicates, maximum_depth=4):
        property_ids = {predicate.property_id for predicate in expression.predicates}
        if any(
            PROPERTY_BY_ID[property_id].availability_status.value == "DATA_GATE_BLOCKED"
            for property_id in property_ids
        ):
            continue
        if any(
            predicate.learned_on == "LOGICAL_NEGATIVE_CONTROL"
            for predicate in expression.predicates
        ):
            output[expression.semantic_fingerprint] = 0
            continue
        if "football:data_quality:missingness" in property_ids:
            continue
        support = (
            min(team_rows, market_rows)
            if "football:market:market_margin" in property_ids
            else team_rows
        )
        output[expression.semantic_fingerprint] = support
    return output


def _engine_proofs(j10: dict[str, Any], j11: dict[str, Any]) -> dict[str, object]:
    top = j10["top_exploratory_walk_forward_results"]
    folds = j11["folds"]
    transactions = [
        frozenset(
            {
                str(item["market"]),
                str(item["selection"]),
                str(item["competition"]),
            }
        )
        for item in top
    ]
    apriori = AprioriEngine().mine(
        transactions,
        minimum_support=1,
        maximum_depth=3,
    )
    groups = [str(item["competition"]) for item in top]
    targets = [float(item["roi"]) for item in top]
    subgroups = SubgroupDiscoveryEngine().discover(groups, targets)
    fold_matches = [float(item["matches"]) for item in folds]
    primary_deltas = [float(item["primary_delta_log_loss"]) for item in folds]
    boosting_deltas = [float(item["incremental_boosting_delta_log_loss"]) for item in folds]
    fitted = RulePathEngine().fit_predicate(
        "football:strength_form:form",
        primary_deltas[:3],
    )
    symbolic = SymbolicRegressionEngine().fit(
        {
            "football:match_competition:season": [float(item["season"]) for item in folds],
            "football:data_quality:coverage_bias": fold_matches,
            "football:strength_form:form": boosting_deltas,
        },
        primary_deltas,
    )
    mutated = GeneticProgrammingEngine().mutate(fitted, seed=20260729)
    mcts = MonteCarloTreeSearchEngine().choose(
        {
            "TEAM_PLUS_MARKET": primary_deltas,
            "BOOSTING": boosting_deltas,
        },
        parent_visits=len(folds) * 2,
    )
    residuals = ResidualMiningEngine().discover(
        {"football:data_quality:coverage_bias": fold_matches},
        outcomes=boosting_deltas,
        baselines=primary_deltas,
    )
    motifs = TemporalMotifEngine().mine(
        [[str(item["season"]), "EVALUATED", "NEXT_SEASON"] for item in folds],
        motif_length=2,
    )
    graph = GraphPattern(
        nodes=(
            GraphNode("n1", "PLAYER", "winger"),
            GraphNode("n2", "PLAYER", "fullback"),
            GraphNode("n3", "TEAM", "defence"),
        ),
        edges=(
            GraphEdge("winger", "DIRECTLY_OPPOSES", "fullback"),
            GraphEdge("fullback", "PLAYS_WITH", "defence"),
        ),
    )
    graph_motifs = GraphPatternMiningEngine().mine(graph)
    ai_expression = AiProposalCompiler().compile(
        {
            "predicates": [
                {
                    "property_id": "football:weather:crosswind_component",
                    "operator": "GE",
                    "value": 10.0,
                },
                {
                    "property_id": "football:goalkeeper:aerial_claims",
                    "operator": "LE",
                    "value": 0.5,
                },
            ],
            "target": "EVENT_COUNT",
        }
    )
    return {
        "schema_version": "universal-engine-proof-v1",
        "typed_enumeration": {
            "version": TypedEnumerationEngine.engine_version,
            "input_predicates": len(_pilot_predicates()),
        },
        "apriori": {
            "version": AprioriEngine.engine_version,
            "frequent_itemsets": len(apriori),
            "result_hash": canonical_sha256(apriori),
        },
        "beam_search": {
            "version": "hierarchical-beam-v2",
            "score_policy": "SUPPORT_QUALITY_COMPLEXITY;ROI_NOT_USED",
        },
        "subgroup_discovery": {
            "version": SubgroupDiscoveryEngine.engine_version,
            "subgroups": len(subgroups),
            "result_hash": canonical_sha256([asdict(item) for item in subgroups]),
        },
        "rule_paths": {
            "version": RulePathEngine.engine_version,
            "predicate_hash": fitted.fingerprint,
            "threshold_learned_from": fitted.learned_on,
        },
        "symbolic_regression": {
            "version": SymbolicRegressionEngine.engine_version,
            "term": asdict(symbolic),
        },
        "genetic_programming": {
            "version": GeneticProgrammingEngine.engine_version,
            "mutated_predicate_hash": mutated.fingerprint,
            "seed": 20260729,
        },
        "mcts": {
            "version": MonteCarloTreeSearchEngine.engine_version,
            "choice": asdict(mcts),
        },
        "residual_mining": {
            "version": ResidualMiningEngine.engine_version,
            "signals": [asdict(item) for item in residuals],
        },
        "temporal_motifs": {
            "version": TemporalMotifEngine.engine_version,
            "motifs": len(motifs),
            "result_hash": canonical_sha256(motifs),
        },
        "graph_patterns": {
            "version": GraphPatternMiningEngine.engine_version,
            "graph_hash": graph.fingerprint,
            "motifs": graph_motifs,
        },
        "ai_compiler": {
            "version": AiProposalCompiler.engine_version,
            "expression_hash": ai_expression.semantic_fingerprint,
            "numbers_generated": 0,
            "promotion_allowed": False,
        },
    }


def _node_projection(node: object) -> dict[str, object]:
    if not hasattr(node, "expression"):
        raise TypeError("HYPOTHESIS_TREE_NODE_REQUIRED")
    expression = node.expression
    first = PROPERTY_BY_ID[expression.predicates[0].property_id]
    return {
        "node_id": node.node_id,
        "parent_id": node.parent_node_id,
        "parent_ids": list(node.parent_ids),
        "children_count": 0,
        "family": first.family,
        "subfamily": first.subfamily,
        "tags": list(first.tags),
        "display_rule_fr": " et ".join(
            PROPERTY_BY_ID[predicate.property_id].display_name_fr
            for predicate in expression.predicates
        ),
        "technical_rule": expression.canonical_payload(),
        "support": node.support,
        "status": node.scientific_status.value,
        "materialization_disposition": node.materialization_disposition.value,
        "historical_metrics": None,
        "prospective_metrics": None,
        "data_gates": [
            PROPERTY_BY_ID[predicate.property_id].availability_status.value
            for predicate in expression.predicates
        ],
        "rankings": None,
        "payload_hash": node.payload_hash,
    }


def build(
    output: Path,
    artifact_output: Path,
    *,
    source_code_revision: str | None,
    source_tree_hash: str | None,
    generator_hash: str | None,
    frozen_at: datetime | None,
) -> dict[str, object]:
    j10 = _read(J10_CAMPAIGN)
    j11 = _read(J11_CAMPAIGN)
    features = _read(J11_FEATURES)
    coverage = _read(J11_COVERAGE)
    predicates = _pilot_predicates()
    budget = DiscoveryBudget(
        maximum_materialized_nodes=180,
        maximum_evaluated_nodes=80,
        checkpoint_frequency=25,
        beam_width=16,
        expansion_batch_size=32,
        maximum_depth=4,
    )
    support = _support_map(
        predicates,
        team_rows=int(j11["sample"]["paired_evaluation_rows"]),
        market_rows=int(j10["counts"]["fixtures_matched"]),
    )
    ontology_hash = property_universe_hash()
    campaign_hash = next(
        campaign.campaign_hash
        for campaign in CAMPAIGNS
        if campaign.campaign_id == "LONG_TAIL_FOOTBALL_TREE_V1"
    )
    data_hash = canonical_sha256(
        {
            "j10": j10["result_hash"],
            "j11": j11["result_hash"],
            "features": features["dataset_hash"],
            "coverage": _sha256(J11_COVERAGE),
        }
    )
    code_hash = generator_hash or canonical_sha256({"status": "PENDING_SOURCE_COMMIT"})
    explorer = UniversalTreeExplorer()
    tracemalloc.start()
    started = time.perf_counter()
    first = explorer.explore(
        predicates,
        budget=budget,
        support_by_fingerprint=support,
        ontology_hash=ontology_hash,
        campaign_hash=campaign_hash,
        data_hash=data_hash,
        code_hash=code_hash,
    )
    second = explorer.explore(
        predicates,
        budget=budget,
        support_by_fingerprint=support,
        ontology_hash=ontology_hash,
        campaign_hash=campaign_hash,
        data_hash=data_hash,
        code_hash=code_hash,
    )
    compute_seconds = time.perf_counter() - started
    _, peak_heap_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if first.replay_hash != second.replay_hash:
        raise ValueError("UNIVERSAL_GENOME_REPLAY_MISMATCH")

    node_rows = [_node_projection(node) for node in first.nodes]
    page_size = 50
    page_manifest: list[dict[str, object]] = []
    page_root = artifact_output / "hypothesis-tree-node-pages"
    for start in range(0, len(node_rows), page_size):
        page = start // page_size + 1
        payload = {
            "schema_version": "hypothesis-tree-node-page-v1",
            "page": page,
            "page_size": page_size,
            "total": len(node_rows),
            "items": node_rows[start : start + page_size],
        }
        path = page_root / f"page-{page:03d}.json"
        _write(path, payload)
        page_manifest.append(
            {
                "page": page,
                "records": len(payload["items"]),
                "artifact_path": (f"hypothesis-tree-node-pages/page-{page:03d}.json"),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )

    family_catalog = [
        {
            "family": seed.family,
            "display_name_fr": seed.display_fr,
            "entities": [seed.entity],
            "property_count": len(seed.properties),
            "availability_status": seed.availability.value,
            "blocking_reason": seed.blocking_reason,
        }
        for seed in FAMILY_SEEDS
    ]
    tags_catalog = {
        "schema_version": "hypothesis-tags-catalog-v1",
        "origins": {
            "MACHINE_DISCOVERED": "Découverte de Robin",
            "OWNER_PROPOSED": "Proposition de David",
            "MODEL_DISCOVERED": "Découverte d’un modèle",
            "LITERATURE_PROPOSED": "Recherche externe",
            "AI_PROPOSED": "Proposition compilée par IA",
        },
        "families": [
            {
                "id": item["family"],
                "label_fr": item["display_name_fr"],
            }
            for item in family_catalog
        ],
        "subfamilies": sorted({item.subfamily for item in PROPERTY_UNIVERSE}),
        "public_language": "fr",
    }
    status_counts = {
        "EXECUTED": first.executed,
        "PRUNED": first.pruned,
        "DATA_GATE_BLOCKED": first.blocked,
        "COMPUTE_DEFERRED": first.compute_deferred,
        "LONG_TAIL_WATCHLIST": first.long_tail,
    }
    if sum(status_counts.values()) != first.generated:
        raise RuntimeError("STATUS_FUNNEL_DOES_NOT_RECONCILE_WITH_GENERATED_TOTAL")
    universe_summary = {
        "schema_version": "hypothesis-universe-summary-v2",
        "universe_id": PROPERTY_UNIVERSE_ID,
        "verdict": "HYPOTHESIS_UNIVERSE_SYMBOLICALLY_COMPLETE",
        "completeness_scope": (
            "CLOSURE_OF_THE_VERSIONED_V1_PROPERTY_RELATION_TRANSFORMATION "
            "CATALOGUE;NOT_A_CLAIM_TO_ALL_POSSIBLE_FOOTBALL_IDEAS"
        ),
        "theoretical_universe_size": "COUNTABLY_INFINITE",
        "theoretical_formula": (
            "recursive_typed_expressions(properties, transforms, windows, "
            "relations, targets, optional_markets, unbounded_scientific_depth)"
        ),
        "symbolic_templates": len(PROPERTY_UNIVERSE),
        "property_families": len(FAMILY_SEEDS),
        "properties": len(PROPERTY_UNIVERSE),
        "relations": len(RELATION_CATALOG),
        "transformations": len(TRANSFORMATION_CATALOG),
        "match_windows": list(MATCH_WINDOWS),
        "day_windows": list(DAY_WINDOWS),
        "technical_depth_default": budget.maximum_depth,
        "scientific_depth_limit": None,
        "materialized_candidates": first.materialized,
        "executed_candidates": first.executed,
        "pruned_candidates": first.pruned,
        "data_gate_blocked_candidates": first.blocked,
        "compute_deferred_candidates": first.compute_deferred,
        "long_tail_candidates": first.long_tail,
        "prospectively_frozen_candidates": 3,
        "ontology_hash": ontology_hash,
        "campaign_hash": campaign_hash,
        "data_hash": data_hash,
    }
    pilot = {
        "schema_version": "universal-cache-only-pilot-v1",
        "mode": "CACHE_ONLY",
        "source": {
            "legacy_matches": {
                "rows": 36_423,
                "columns": 27,
                "leagues": 9,
                "seasons": 11,
                "raw_provenance": "ABSENT",
            },
            "five_league_market_rows": int(j10["counts"]["fixtures_matched"]),
            "team_feature_rows": int(j11["sample"]["paired_evaluation_rows"]),
            "team_features": int(features["defined"]),
            "strictly_pre_kickoff_feature_boundaries": int(
                coverage["feature_boundary_strictly_before_rows"]
            ),
        },
        "availability": {
            "force_form": "DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC",
            "attack_defence": "PARTIAL_GOALS_ONLY",
            "calendar": "PARTIAL_REST_AND_CONGESTION",
            "travel": "DATA_GATE_BLOCKED_REAL_LOGISTICS",
            "market": "HISTORICAL_RESEARCH_ONLY_NO_EXACT_INTRADAY_TIMESTAMP",
            "formation": "DATA_GATE_BLOCKED_BY_TEMPORALITY",
            "discipline": "DATA_GATE_BLOCKED_BY_TEMPORALITY",
            "players": "DATA_GATE_BLOCKED_BY_TEMPORALITY",
            "weather": "DATA_GATE_BLOCKED_NO_FREE_LICENSED_ARCHIVE",
        },
        "model_diagnostic": {
            "team_plus_market_delta_log_loss": float(
                j11["models"]["B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL"]["delta_log_loss"]
            ),
            "global_q_value": float(j11["statistics"]["global_q"]),
            "validated_strategy": False,
        },
        "counts": {
            "rules_generated": first.generated,
            "rules_materialized": first.materialized,
            "rules_executed": first.executed,
            "rules_pruned": first.pruned,
            "rules_blocked": first.blocked,
            "rules_compute_deferred": first.compute_deferred,
            "long_tail_candidates": first.long_tail,
            "parents_expanded": first.parents_expanded,
            "maximum_depth_reached": first.maximum_depth_reached,
        },
        "budget": asdict(budget),
        "compute": {
            "compute_time_seconds": round(compute_seconds, 6),
            "python_heap_peak_bytes": peak_heap_bytes,
            "memory_measurement": "PYTHON_HEAP_TRACEMALLOC_NOT_PROCESS_RSS",
        },
        "checkpoint_hash": first.checkpoint.checkpoint_hash,
        "replay_hash": first.replay_hash,
        "replay_identical": True,
        "provider_calls": 0,
        "api_football_calls": 0,
        "odds_api_credits": 0,
        "paid_weather_calls": 0,
        "real_bets": 0,
        "social_publications": 0,
        "automatic_promotions": 0,
    }
    top = j10["top_exploratory_walk_forward_results"]
    raw_ranking = [
        {
            "rank": index,
            "label_fr": "Meilleur signal historique brut",
            "hypothesis_id": f"J10-M00{index}",
            "competition": item["competition"],
            "family": "MARKET",
            "historical_support": item["bets"],
            "historical_roi": item["roi"],
            "q_value": item["q_value"],
            "status": "NON_VALIDÉ_APRÈS_CORRECTION",
        }
        for index, item in enumerate(top, start=1)
    ]
    rankings = {
        "schema_version": "hypothesis-global-rankings-v1",
        "meilleurs_signaux_historiques_bruts": raw_ranking,
        "meilleures_priorites_exploratoires": raw_ranking,
        "meilleures_observations_prospectives": [],
        "strategies_validees": [],
        "longue_traine_a_surveiller": [
            row for row in node_rows if row["materialization_disposition"] == "LONG_TAIL_WATCHLIST"
        ][:10],
        "warning_fr": (
            "Un signal historique ou une priorité exploratoire n’est pas une stratégie validée."
        ),
    }
    by_competition = {
        "schema_version": "hypothesis-rankings-by-competition-v1",
        "competitions": {
            competition: {
                "meilleurs_signaux_historiques_bruts": [
                    item for item in raw_ranking if item["competition"] == competition
                ],
                "strategies_validees": [],
            }
            for competition in sorted({str(item["competition"]) for item in raw_ranking})
        },
    }
    by_family = {
        "schema_version": "hypothesis-rankings-by-family-v1",
        "families": {
            item["family"]: {
                "label_fr": item["display_name_fr"],
                "meilleurs_signaux_historiques_bruts": (
                    raw_ranking if item["family"] == "MARKET" else []
                ),
                "strategies_validees": [],
            }
            for item in family_catalog
        },
    }
    freeze_payload: dict[str, object] = {
        "schema_version": "prospective-freeze-provenance-v2",
        "status": "PENDING_SOURCE_COMMIT",
        "legacy_v1": {
            "source_code_revision": ("0057e1caf57bd4d6084ab456f7ee386fff728c2c"),
            "provenance_complete": False,
            "active": False,
            "reason": "SUPERSEDED_BY_CORRECTIVE_V2",
        },
        "contracts": [],
    }
    if all(
        value is not None
        for value in (
            source_code_revision,
            source_tree_hash,
            generator_hash,
            frozen_at,
        )
    ):
        registry_bytes_hash = _sha256(J10_REGISTRY)
        if registry_bytes_hash != J10_REGISTRY_SHA256:
            raise ValueError("J10_REGISTRY_HASH_MISMATCH")
        records = import_j10_registry(load_jsonl(J10_REGISTRY), j10)
        provenance = FreezeProvenance(
            source_code_revision=str(source_code_revision),
            source_tree_hash=str(source_tree_hash),
            registry_hash=registry_bytes_hash,
            generator_hash=str(generator_hash),
            frozen_at=frozen_at,
        )
        contracts = freeze_top_three_v2(records, provenance)
        freeze_payload = {
            "schema_version": "prospective-freeze-provenance-v2",
            "status": "ACTIVE_CORRECTIVE_V2",
            "legacy_v1": freeze_payload["legacy_v1"],
            "source_code_revision": provenance.source_code_revision,
            "source_tree_hash": provenance.source_tree_hash,
            "registry_hash": provenance.registry_hash,
            "generator_hash": provenance.generator_hash,
            "frozen_at": provenance.frozen_at.isoformat(),
            "contracts": [
                {
                    **asdict(contract),
                    "frozen_at": contract.frozen_at.isoformat(),
                    "primary_price": asdict(contract.primary_price),
                    "secondary_price": asdict(contract.secondary_price),
                    "contract_hash": contract.contract_hash,
                }
                for contract in contracts
            ],
        }

    source_audit = source_field_audit()
    if source_audit["unclassified_source_fields"] != 0:
        raise ValueError("UNCLASSIFIED_SOURCE_FIELDS_REMAIN")
    facets = {
        "schema_version": "hypothesis-facets-v1",
        "origins": tags_catalog["origins"],
        "families": {item["family"]: item["property_count"] for item in family_catalog},
        "campaigns": len(CAMPAIGNS),
        "statuses": status_counts,
        "tree_depths": sorted({node.depth for node in first.nodes}),
        "cutoffs": ["H-24", "H-2", "NEAR_KICKOFF", "POST_LINEUP"],
        "sources": sorted({item.source for item in PROPERTY_UNIVERSE}),
        "markets": sorted({market for campaign in CAMPAIGNS for market in campaign.markets}),
    }
    root_nodes = [row for row in node_rows if row["parent_id"] is None]
    root_index = {
        "schema_version": "hypothesis-tree-root-index-v1",
        "tree_id": "UNIVERSAL_FOOTBALL_TREE_V1",
        "roots": root_nodes,
        "node_count": len(node_rows),
        "page_size": page_size,
        "detail_pages_storage": "BUILD_ARTIFACT_NOT_GIT",
        "page_manifest": page_manifest,
        "replay_hash": first.replay_hash,
    }
    family_tree_index = {
        "schema_version": "hypothesis-family-tree-index-v1",
        "families": {
            family["family"]: {
                "label_fr": family["display_name_fr"],
                "root_node_ids": [
                    row["node_id"] for row in root_nodes if row["family"] == family["family"]
                ],
            }
            for family in family_catalog
        },
    }
    glossary = {
        "schema_version": "hypothesis-glossary-fr-v1",
        "Validation chronologique glissante": "Walk-forward",
        "Baisse maximale de la bankroll simulée": "Drawdown",
        "Variable analysée": "Feature",
        "Condition de disponibilité": "Gate",
        "Correction du risque de faux positifs": "FDR",
        "Risque de faux positif après correction": "q-value",
        "note": "Les termes techniques originaux sont réservés à la Vue Expert.",
    }
    live_activity = {
        "schema_version": "hypothesis-live-activity-v1",
        "hypothesis_observations": 0,
        "prospective_settlements": 0,
        "real_predictions": 0,
        "real_training_runs": 0,
        "real_bets": 0,
        "last_activity": None,
    }
    security = {
        "STORAGE_PAUSED": True,
        "P3_P4_PAUSED": True,
        "PRODUCTION_LOCKED": True,
        "REAL_BETS": False,
        "NO_BET_DEFAULT": True,
        "PROMOTION_LOCKED": True,
        "SOCIAL_PUBLISHING_ENABLED": False,
        "DEMO_MODE_ENABLED": False,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "paid_weather_calls": 0,
    }
    outputs: dict[str, object] = {
        "hypothesis-universe-summary.json": universe_summary,
        "hypothesis-family-catalog.json": {
            "schema_version": "hypothesis-family-catalog-v1",
            "items": family_catalog,
            "catalog_hash": canonical_sha256(family_catalog),
        },
        "hypothesis-tags-catalog.json": tags_catalog,
        "hypothesis-facets.json": facets,
        "hypothesis-tree-root-index.json": root_index,
        "hypothesis-family-tree-index.json": family_tree_index,
        "hypothesis-global-rankings.json": rankings,
        "hypothesis-rankings-by-competition.json": by_competition,
        "hypothesis-rankings-by-family.json": by_family,
        "hypothesis-status-funnel.json": {
            "schema_version": "hypothesis-status-funnel-v1",
            "counts": status_counts,
            "scientific_rejections": 0,
            "validated_strategies": 0,
        },
        "hypothesis-live-activity.json": live_activity,
        "hypothesis-glossary-fr.json": glossary,
        "competition-identity-catalog.json": {
            "schema_version": "competition-identity-catalog-v1",
            "items": competition_catalog(),
        },
        "source-field-audit.json": source_audit,
        "campaign-catalog.json": {
            "schema_version": "hypothesis-campaign-catalog-v1",
            "items": campaign_catalog(),
        },
        "engine-proof.json": _engine_proofs(j10, j11),
        "universal-cache-only-pilot.json": pilot,
        "prospective-freeze-provenance-v2.json": freeze_payload,
        "security-locks.json": security,
    }
    manifest: list[dict[str, object]] = []
    for filename, payload in outputs.items():
        path = output / filename
        _write(path, payload)
        manifest.append(
            {
                "file": filename,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest_payload = {
        "schema_version": "hypothesis-dashboard-contract-manifest-v2",
        "files": sorted(manifest, key=lambda item: str(item["file"])),
        "detail_pages": page_manifest,
        "detail_pages_storage": "BUILD_ARTIFACT_NOT_GIT",
        "provider_calls": 0,
        "real_bets": 0,
    }
    _write(output / "manifest.json", manifest_payload)
    return {
        "universe": universe_summary,
        "pilot": pilot,
        "manifest": manifest_payload,
        "security": security,
        "preview": {
            "title": "Génome universel des hypothèses",
            "symbolicStatus": "Univers symboliquement complet",
            "properties": len(PROPERTY_UNIVERSE),
            "families": len(FAMILY_SEEDS),
            "relations": len(RELATION_CATALOG),
            "materialized": first.materialized,
            "executed": first.executed,
            "blocked": first.blocked,
            "deferred": first.compute_deferred,
            "validatedStrategies": 0,
            "replayIdentical": True,
            "artifactPages": len(page_manifest),
            "warning": (
                "Complétude de la grammaire et du catalogue V1, sans stratégie "
                "validée ni promesse de performance."
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--artifact-output",
        type=Path,
        default=DEFAULT_ARTIFACT_OUTPUT,
    )
    parser.add_argument("--source-code-revision")
    parser.add_argument("--source-tree-hash")
    parser.add_argument("--generator-hash")
    parser.add_argument("--frozen-at")
    parser.add_argument("--preview-output", type=Path)
    args = parser.parse_args()
    frozen_at = (
        datetime.fromisoformat(args.frozen_at.replace("Z", "+00:00")) if args.frozen_at else None
    )
    result = build(
        args.output.resolve(),
        args.artifact_output.resolve(),
        source_code_revision=args.source_code_revision,
        source_tree_hash=args.source_tree_hash,
        generator_hash=args.generator_hash,
        frozen_at=frozen_at,
    )
    if args.preview_output is not None:
        _write(args.preview_output.resolve(), result["preview"])
    print(
        json.dumps(
            {
                "properties": result["preview"]["properties"],
                "families": result["preview"]["families"],
                "provider_calls": 0,
                "real_bets": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
