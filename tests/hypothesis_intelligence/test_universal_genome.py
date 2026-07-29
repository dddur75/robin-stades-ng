from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin.hypothesis_intelligence.competition_identity import (
    resolve_competition,
    resolve_provider_competition,
    same_competition,
)
from robin.hypothesis_intelligence.contracts import canonical_sha256
from robin.hypothesis_intelligence.grammar import (
    GraphEdge,
    GraphNode,
    GraphPattern,
    HypothesisExpression,
    MaterializationDisposition,
    Operator,
    Predicate,
    ScientificStatus,
    immediate_parent_fingerprints,
    make_tree_node,
)
from robin.hypothesis_intelligence.hierarchical_validation import (
    compare_child_to_parent,
    hierarchical_gatekeeping,
    leakage_audit,
    validate_observation_cutoff,
    validate_train_test_boundary,
)
from robin.hypothesis_intelligence.ontology import (
    FAMILY_SEEDS,
    PROPERTY_BY_ID,
    PROPERTY_UNIVERSE,
    RELATION_CATALOG,
    TRANSFORMATION_CATALOG,
    AvailabilityStatus,
    source_field_audit,
)
from robin.hypothesis_intelligence.prospective import evaluate_fixture, freeze_top_three
from robin.hypothesis_intelligence.universal_engines import (
    AiProposalCompiler,
    AprioriEngine,
    BeamSearchEngine,
    DiscoveryBudget,
    GeneticProgrammingEngine,
    GraphPatternMiningEngine,
    MonteCarloTreeSearchEngine,
    ResidualMiningEngine,
    RulePathEngine,
    SubgroupDiscoveryEngine,
    SymbolicRegressionEngine,
    TemporalMotifEngine,
    UniversalTreeExplorer,
)
from tests.hypothesis_intelligence.test_factory import _top_records

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "hypothesis-genome"


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _expression(*predicates: Predicate) -> HypothesisExpression:
    return HypothesisExpression(
        entity_scope="TEAM_FIXTURE",
        context=("PRE_MATCH",),
        predicates=predicates,
        relation="INTERACTS_WITH",
        temporal_window="MATCHES_5",
        cutoff="H-2",
        target="MATCH_RESULT",
        market=None,
        price_contract=None,
    )


def test_competition_identity_resolves_liga_aliases_and_scoped_provider_ids() -> None:
    assert same_competition("La Liga", "Liga")
    assert same_competition("SP1", "api-football:140")
    assert (
        resolve_provider_competition(
            "API_FOOTBALL",
            "140",
        ).canonical_competition_key
        == "api-football:140"
    )
    with pytest.raises(ValueError, match="UNKNOWN_COMPETITION_IDENTITY"):
        resolve_competition("140")
    with pytest.raises(ValueError, match="UNKNOWN_COMPETITION_IDENTITY"):
        same_competition("Championat imaginaire", "Liga")


def test_live_liga_fixture_matches_historical_la_liga_and_unknown_fails_closed() -> None:
    contract = freeze_top_three(_top_records())[0]
    cutoff = datetime(2026, 8, 15, 17, 55, tzinfo=UTC)
    common = {
        "fixture_id": "fixture-liga-alias",
        "market": "h2h",
        "selection": "AWAY",
        "cutoff_name": "NEAR_KICKOFF",
        "cutoff_at": cutoff,
        "kickoff_at": cutoff + timedelta(minutes=5),
        "observed_at": cutoff - timedelta(minutes=1),
        "odds": 2.2,
        "margin": 0.05,
        "bookmaker_scope": ("CONFIGURED_EU_BOOKMAKERS",),
        "conditions_snapshot": {"fixture_status": "SCHEDULED"},
        "code_revision": "a" * 40,
    }
    liga = evaluate_fixture(contract, competition="Liga", **common)
    assert liga.status.value == "ELIGIBLE_FROZEN"
    unknown = evaluate_fixture(
        contract,
        competition="Unknown League",
        **common,
    )
    assert unknown.status_reason == "UNKNOWN_COMPETITION_IDENTITY"


def test_property_universe_is_explicit_native_weather_and_source_closed() -> None:
    assert len(PROPERTY_UNIVERSE) >= 480
    assert len(FAMILY_SEEDS) == 28
    assert len(RELATION_CATALOG) >= 40
    assert len(TRANSFORMATION_CATALOG) >= 30
    assert len({item.property_id for item in PROPERTY_UNIVERSE}) == len(PROPERTY_UNIVERSE)
    required_fields = {
        "property_id",
        "display_name_fr",
        "display_name_en",
        "description_fr",
        "family",
        "subfamily",
        "tags",
        "subtags",
        "entity",
        "data_type",
        "unit",
        "source",
        "source_field",
        "raw_or_derived",
        "derivation_contract",
        "availability_time",
        "valid_cutoffs",
        "temporal_gate",
        "quality_gate",
        "missingness_policy",
        "allowed_operators",
        "allowed_relations",
        "allowed_targets",
        "version",
        "observation_type",
        "physical_dimension",
        "source_schema_hash",
        "event_time_field",
        "published_at_field",
        "provider_updated_at_field",
        "observed_at_field",
        "ingested_at_field",
        "valid_from_field",
        "valid_to_field",
    }
    assert required_fields <= set(PROPERTY_UNIVERSE[0].__dataclass_fields__)
    weather = [item for item in PROPERTY_UNIVERSE if item.family == "WEATHER"]
    assert len(weather) >= 20
    assert {item.availability_status for item in weather} == {AvailabilityStatus.DATA_GATE_BLOCKED}
    audit = source_field_audit()
    assert audit["unclassified_source_fields"] == 0
    assert audit["source_fields"] == audit["classified_source_fields"]


def test_recursive_dsl_is_typed_order_invariant_and_has_multi_parent_dag() -> None:
    first = Predicate(
        "football:strength_form:elo",
        Operator.GE,
        5.0,
    )
    second = Predicate(
        "football:calendar_fatigue:rest_days",
        Operator.LE,
        3.0,
    )
    third = Predicate(
        "football:market:market_margin",
        Operator.LE,
        0.08,
    )
    left = _expression(first, second, third)
    right = _expression(third, first, second)
    assert left.semantic_fingerprint == right.semantic_fingerprint
    assert left.depth == 3
    assert len(immediate_parent_fingerprints(left)) == 3
    node = make_tree_node(
        left,
        tree_id="test-tree",
        generator_seed_id="test-seed",
        generation_engine="test",
        generation_round=3,
        disposition=MaterializationDisposition.MATERIALIZED,
    )
    assert len(node.parent_ids) == 3
    assert node.parent_node_id == node.parent_ids[0]
    assert node.scientific_status is ScientificStatus.NOT_TESTED


def test_graph_pattern_and_unknown_foot_are_fail_closed() -> None:
    graph = GraphPattern(
        nodes=(
            GraphNode("n1", "PLAYER", "winger"),
            GraphNode("n2", "PLAYER", "fullback"),
        ),
        edges=(GraphEdge("winger", "DIRECTLY_OPPOSES", "fullback"),),
    )
    assert len(graph.fingerprint) == 64
    with pytest.raises(ValueError, match="GRAPH_PATTERN_EDGE_BINDING_UNKNOWN"):
        GraphPattern(
            nodes=(GraphNode("n1", "PLAYER", "winger"),),
            edges=(GraphEdge("winger", "DIRECTLY_OPPOSES", "unknown"),),
        )
    foot = PROPERTY_BY_ID["football:player:preferred_foot"]
    assert foot.availability_status is AvailabilityStatus.DATA_GATE_BLOCKED
    assert foot.missingness_policy == "MISSING_NOT_ZERO"


def test_lazy_tree_is_budgeted_replayable_blocked_pruned_and_long_tail() -> None:
    predicates = (
        Predicate("football:strength_form:elo", Operator.GE, 0.0),
        Predicate(
            "football:calendar_fatigue:rest_days",
            Operator.LT,
            0.0,
            learned_on="LOGICAL_NEGATIVE_CONTROL",
        ),
        Predicate("football:weather:temperature", Operator.GE, 30.0),
        Predicate("football:data_quality:missingness", Operator.GE, 0.25),
    )
    expressions = list(
        __import__(
            "robin.hypothesis_intelligence.universal_engines",
            fromlist=["TypedEnumerationEngine"],
        )
        .TypedEnumerationEngine()
        .iter_expressions(
            predicates,
            maximum_depth=3,
        )
    )
    support = {
        expression.semantic_fingerprint: (
            0
            if any(
                predicate.learned_on == "LOGICAL_NEGATIVE_CONTROL"
                for predicate in expression.predicates
            )
            else 100
        )
        for expression in expressions
        if all(
            PROPERTY_BY_ID[predicate.property_id].availability_status
            is not AvailabilityStatus.DATA_GATE_BLOCKED
            and predicate.property_id != "football:data_quality:missingness"
            for predicate in expression.predicates
        )
    }
    budget = DiscoveryBudget(
        maximum_materialized_nodes=12,
        maximum_evaluated_nodes=2,
        maximum_depth=3,
    )
    explorer = UniversalTreeExplorer()
    kwargs = {
        "budget": budget,
        "support_by_fingerprint": support,
        "ontology_hash": "a" * 64,
        "campaign_hash": "b" * 64,
        "data_hash": "c" * 64,
        "code_hash": "d" * 64,
    }
    first = explorer.explore(predicates, **kwargs)
    second = explorer.explore(predicates, **kwargs)
    assert first.replay_hash == second.replay_hash
    assert first.blocked > 0
    assert first.pruned > 0
    assert first.long_tail > 0
    assert first.compute_deferred > 0
    assert all(
        node.scientific_status is ScientificStatus.NOT_TESTED
        for node in first.nodes
        if node.materialization_disposition is MaterializationDisposition.COMPUTE_DEFERRED
    )


def test_all_generation_engines_execute_real_deterministic_operations() -> None:
    transactions = (
        frozenset({"A", "B"}),
        frozenset({"A", "C"}),
        frozenset({"A", "B"}),
    )
    apriori = AprioriEngine().mine(
        transactions,
        minimum_support=2,
        maximum_depth=2,
    )
    assert (("A",), 3) in apriori
    assert (("A", "B"), 2) in apriori

    subgroups = SubgroupDiscoveryEngine().discover(
        ("home", "away", "home"),
        (1.0, 0.0, 1.0),
    )
    assert {item.label for item in subgroups} == {"home", "away"}

    fitted = RulePathEngine().fit_predicate(
        "football:strength_form:form",
        (0.1, 0.3, 0.2),
    )
    assert fitted.learned_on == "TRAIN_ONLY"
    symbolic = SymbolicRegressionEngine().fit(
        {
            "a": (1.0, 2.0, 3.0),
            "b": (3.0, 2.0, 1.0),
        },
        (0.0, 0.5, 1.0),
    )
    assert symbolic.operation == "DIFFERENCE"
    mutated = GeneticProgrammingEngine().mutate(fitted, seed=7)
    assert mutated.fingerprint != fitted.fingerprint
    crossed = GeneticProgrammingEngine().crossover(
        _expression(fitted),
        _expression(mutated),
    )
    assert crossed.depth == 2
    choice = MonteCarloTreeSearchEngine().choose(
        {"left": (0.1, 0.2), "right": (0.3,)},
        parent_visits=3,
    )
    assert choice.action in {"left", "right"}
    residuals = ResidualMiningEngine().discover(
        {"feature": (0.0, 1.0, 2.0)},
        outcomes=(0.0, 1.0, 1.0),
        baselines=(0.1, 0.4, 0.7),
    )
    assert residuals[0].support == 3
    motifs = TemporalMotifEngine().mine(
        (("A", "B", "A"), ("A", "B", "C")),
        motif_length=2,
    )
    assert motifs[0] == (("A", "B"), 2)

    graph = GraphPattern(
        nodes=(
            GraphNode("n1", "PLAYER", "a"),
            GraphNode("n2", "PLAYER", "b"),
        ),
        edges=(GraphEdge("a", "PLAYS_WITH", "b"),),
    )
    assert GraphPatternMiningEngine().mine(graph) == (("a", 1), ("b", 1))
    compiled = AiProposalCompiler().compile(
        {
            "predicates": [
                {
                    "property_id": "football:weather:wind_speed",
                    "operator": "GE",
                    "value": 10.0,
                }
            ]
        }
    )
    assert compiled.predicates[0].learned_on == ("AI_PROPOSED_NO_NUMERIC_EVIDENCE")

    candidates = (
        make_tree_node(
            _expression(fitted),
            tree_id="beam",
            generator_seed_id="seed",
            generation_engine="beam",
            generation_round=1,
            disposition=MaterializationDisposition.EXECUTED,
            support=100,
        ),
        make_tree_node(
            _expression(mutated),
            tree_id="beam",
            generator_seed_id="seed",
            generation_engine="beam",
            generation_round=1,
            disposition=MaterializationDisposition.EXECUTED,
            support=10,
        ),
    )
    assert BeamSearchEngine().select(candidates, beam_width=1)[0].support == 100


def test_train_only_temporal_weather_and_leakage_guards() -> None:
    validate_train_test_boundary(
        train_end=datetime(2024, 12, 31, tzinfo=UTC),
        test_start=datetime(2025, 1, 1, tzinfo=UTC),
        threshold_learned_from="TRAIN_ONLY",
    )
    with pytest.raises(ValueError, match="DERIVED_THRESHOLD_MUST_BE_TRAIN_ONLY"):
        validate_train_test_boundary(
            train_end=datetime(2024, 12, 31, tzinfo=UTC),
            test_start=datetime(2025, 1, 1, tzinfo=UTC),
            threshold_learned_from="FULL_DATASET",
        )
    cutoff = datetime(2026, 8, 1, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="ACTUAL_TARGET_WEATHER"):
        validate_observation_cutoff(
            observed_at=cutoff,
            cutoff_at=cutoff,
            source_kind="ACTUAL_WEATHER_FOR_TARGET_MATCH",
        )
    audit = leakage_audit(("elo", "home_goals", "future_odds"))
    assert audit["passed"] is False
    assert audit["rejected_features"] == ["future_odds", "home_goals"]


def test_hierarchical_validation_is_paired_and_never_auto_validates() -> None:
    metrics = compare_child_to_parent(
        child_id="child",
        parent_id="parent",
        outcomes=(1, 0, 1, 0),
        child_probabilities=(0.8, 0.2, 0.7, 0.3),
        parent_probabilities=(0.6, 0.4, 0.6, 0.4),
        market_probabilities=(0.55, 0.45, 0.55, 0.45),
        child_returns=None,
        parent_returns=None,
        parent_support=10,
        child_depth=2,
        stability_change=0.1,
        concentration_change=-0.1,
    )
    assert metrics.paired_support == 4
    assert metrics.incremental_log_loss > 0
    assert metrics.incremental_roi is None
    decisions = hierarchical_gatekeeping(
        p_values={"parent": 0.001, "child": 0.002},
        parent_by_child={"parent": None, "child": "parent"},
        family_by_node={"parent": "team", "child": "team"},
    )
    assert decisions["parent"]["gate_open_for_children"] is True
    assert decisions["child"]["parent_gate_open"] is True
    assert decisions["child"]["gate_open_for_children"] is True
    assert decisions["child"]["automatic_validation"] is False


def test_dashboard_contracts_are_bounded_french_and_have_no_validated_strategy() -> None:
    expected = {
        "hypothesis-universe-summary.json",
        "hypothesis-family-catalog.json",
        "hypothesis-tags-catalog.json",
        "hypothesis-facets.json",
        "hypothesis-tree-root-index.json",
        "hypothesis-global-rankings.json",
        "hypothesis-rankings-by-competition.json",
        "hypothesis-rankings-by-family.json",
        "hypothesis-status-funnel.json",
        "hypothesis-live-activity.json",
        "hypothesis-glossary-fr.json",
    }
    assert expected <= {path.name for path in REPORTS.glob("*.json")}
    rankings = _json(REPORTS / "hypothesis-global-rankings.json")
    assert rankings["strategies_validees"] == []
    assert "Meilleur signal historique brut" in json.dumps(
        rankings,
        ensure_ascii=False,
    )
    universe = _json(REPORTS / "hypothesis-universe-summary.json")
    assert universe["theoretical_universe_size"] == "COUNTABLY_INFINITE"
    assert universe["verdict"] == "HYPOTHESIS_UNIVERSE_SYMBOLICALLY_COMPLETE"
    pilot = _json(REPORTS / "universal-cache-only-pilot.json")
    funnel = _json(REPORTS / "hypothesis-status-funnel.json")
    assert sum(funnel["counts"].values()) == pilot["counts"]["rules_generated"]
    assert funnel["counts"]["COMPUTE_DEFERRED"] == pilot["counts"]["rules_compute_deferred"]
    assert pilot["replay_identical"] is True
    assert pilot["provider_calls"] == pilot["real_bets"] == 0
    assert max(path.stat().st_size for path in REPORTS.glob("*.json")) < 300_000


def test_git_footprint_contains_no_detailed_700_rule_pages() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "cockpit/public/hypotheses", "artifacts"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert all(not (ROOT / path).exists() for path in tracked)
    cockpit_data = (ROOT / "cockpit" / "app" / "cockpit-data.json").read_text("utf-8")
    assert cockpit_data.count('"ruleHash"') <= 3


def test_corrective_freeze_v2_has_exact_non_backdated_git_provenance() -> None:
    payload = _json(REPORTS / "prospective-freeze-provenance-v2.json")
    assert payload["status"] == "ACTIVE_CORRECTIVE_V2"
    source_revision = str(payload["source_code_revision"])
    source_tree_hash = str(payload["source_tree_hash"])
    assert (
        subprocess.run(
            ["git", "show", "-s", "--format=%T", source_revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == source_tree_hash
    )
    generator_paths = (
        "scripts/build_universal_hypothesis_genome.py",
        "src/robin/hypothesis_intelligence/competition_identity.py",
        "src/robin/hypothesis_intelligence/contracts.py",
        "src/robin/hypothesis_intelligence/freeze_v2.py",
        "src/robin/hypothesis_intelligence/grammar.py",
        "src/robin/hypothesis_intelligence/prospective.py",
        "src/robin/hypothesis_intelligence/registry.py",
        "src/robin/hypothesis_intelligence/universal_engines.py",
    )
    blobs = {
        path: subprocess.run(
            ["git", "rev-parse", f"{source_revision}:{path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for path in generator_paths
    }
    assert canonical_sha256(blobs) == payload["generator_hash"]
    source_committed_at = datetime.fromisoformat(
        subprocess.run(
            ["git", "show", "-s", "--format=%cI", source_revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    assert datetime.fromisoformat(str(payload["frozen_at"])) > source_committed_at
    contracts = payload["contracts"]
    assert isinstance(contracts, list) and len(contracts) == 3
    for contract in contracts:
        assert contract["source_code_revision"] == source_revision
        assert contract["source_tree_hash"] == source_tree_hash
        assert contract["generator_hash"] == payload["generator_hash"]
        assert contract["contract_version"] == "2.0.0"
        assert contract["supersedes"].endswith(":1.0.0")
        assert contract["promotion_locked"] is True
