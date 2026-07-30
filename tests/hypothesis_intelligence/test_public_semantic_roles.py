from __future__ import annotations

import json
from pathlib import Path

from robin.hypothesis_intelligence.grammar import (
    HypothesisExpression,
    Operator,
    Predicate,
)
from robin.hypothesis_intelligence.ontology import (
    PROPERTY_BY_ID,
    PROPERTY_UNIVERSE,
    PUBLIC_HYPOTHESIS_SEMANTIC_ROLES,
    SemanticRole,
    property_universe_hash,
)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "hypothesis-genome"


def _json(name: str) -> dict[str, object]:
    payload = json.loads((REPORTS / name).read_text("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _expression(predicate: Predicate) -> HypothesisExpression:
    return HypothesisExpression(
        entity_scope="TEAM_FIXTURE",
        context=("PRE_MATCH",),
        predicates=(predicate,),
        relation="APPLIES_TO",
        temporal_window="CURRENT",
        cutoff="H-2",
        target="MATCH_RESULT",
        market=None,
        price_contract=None,
    )


def test_every_property_has_an_explicit_total_semantic_role() -> None:
    assert len(PROPERTY_UNIVERSE) == 486
    assert all(isinstance(item.semantic_role, SemanticRole) for item in PROPERTY_UNIVERSE)
    assert property_universe_hash() == (
        "69cca06408ab6bbea3e16f5c5252c505c6bd4175b533c7e0d08283a6036ba186"
    )


def test_quality_availability_and_provenance_are_classified_exactly() -> None:
    expected = {
        "football:data_quality:missingness": SemanticRole.DATA_QUALITY_METADATA,
        "football:data_quality:identity_confidence": SemanticRole.DATA_QUALITY_METADATA,
        "football:data_quality:coverage_bias": SemanticRole.DATA_QUALITY_METADATA,
        "football:data_quality:schema_change": SemanticRole.DATA_QUALITY_METADATA,
        "football:data_quality:observed_at": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:published_at": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:provider_updated_at": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:ingested_at": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:valid_from": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:valid_to": SemanticRole.AVAILABILITY_METADATA,
        "football:data_quality:source": SemanticRole.PROVENANCE_METADATA,
        "football:data_quality:source_schema_hash": SemanticRole.PROVENANCE_METADATA,
        "football:data_quality:provenance_hash": SemanticRole.PROVENANCE_METADATA,
    }
    assert {
        property_id: PROPERTY_BY_ID[property_id].semantic_role
        for property_id in expected
    } == expected
    assert not (
        {
            item.semantic_role
            for item in PROPERTY_UNIVERSE
            if item.family == "DATA_QUALITY"
        }
        & PUBLIC_HYPOTHESIS_SEMANTIC_ROLES
    )


def test_metadata_and_negative_controls_fail_closed_for_public_hypotheses() -> None:
    football = _expression(
        Predicate("football:strength_form:elo", Operator.GE, 0.0)
    )
    metadata = _expression(
        Predicate("football:data_quality:missingness", Operator.GE, 0.25)
    )
    negative_control = _expression(
        Predicate(
            "football:calendar_fatigue:rest_days",
            Operator.LT,
            0.0,
            learned_on="LOGICAL_NEGATIVE_CONTROL",
        )
    )
    assert football.public_hypothesis_eligible is True
    assert metadata.public_hypothesis_eligible is False
    assert negative_control.semantic_roles == (SemanticRole.NEGATIVE_CONTROL,)
    assert negative_control.public_hypothesis_eligible is False


def test_generated_public_contracts_contain_no_false_hypothesis() -> None:
    roles = _json("property-semantic-roles.json")
    assert roles["classification_complete"] is True
    assert roles["property_count"] == len(PROPERTY_UNIVERSE)

    family_catalog = _json("hypothesis-family-catalog.json")
    quality_family = next(
        item
        for item in family_catalog["items"]
        if item["family"] == "DATA_QUALITY"
    )
    assert quality_family["public_hypothesis_eligible"] is False
    assert quality_family["workspace_path"] == "/expert/qualite-donnees"

    rankings = _json("hypothesis-global-rankings.json")
    assert rankings["longue_traine_a_surveiller"] == []
    public_text = json.dumps(
        {
            "rankings": rankings,
            "trees": _json("hypothesis-tree-root-index.json"),
            "families": _json("hypothesis-family-tree-index.json"),
        },
        ensure_ascii=False,
    ).casefold()
    assert "valeur manquante" not in public_text
    assert "data_quality" not in public_text
    assert "logical_negative_control" not in public_text

    workspace = _json("hypothesis-data-quality-workspace.json")
    assert workspace["public_hypothesis_surface"] is False
    assert workspace["workspace_path"] == "/expert/qualite-donnees"
    assert workspace["provider_calls"] == workspace["live_writes"] == 0
