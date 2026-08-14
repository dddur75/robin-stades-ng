from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import pytest


def test_raw_formulations_have_no_encoding_placeholders(
    builder: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    candidates = artifacts["hypothesis-deduplication-v1.json"]["candidates"]
    broken_tokens = {
        "m?canistique",
        "r?futation",
        "gel?",
        "march?s",
        "synchronis?s",
        "r?sidu",
        "apr?s",
        "pr?enregistr?e",
    }
    assert all(
        not any(token in candidate["formulation"] for token in broken_tokens)
        for candidate in candidates
    )
    assert all(
        not any(token in value for token in broken_tokens)
        for family in builder["IDEAS"].values()
        for idea in family
        for value in (idea.title, idea.claim, idea.estimand_definition)
    )


def test_prior_art_references_resolve_to_frozen_repository_sources(
    builder: dict[str, Any],
) -> None:
    builder["_validate_prior_art_references"](builder["IDEAS"])
    first_family = next(iter(builder["IDEAS"].values()))
    tampered = replace(first_family[0], prior_art_refs=("J10_PRICE_BANDS",))
    with pytest.raises(ValueError, match="unresolved prior-art references"):
        builder["_validate_prior_art_references"]({"tampered": (tampered,)})


def test_every_raw_candidate_maps_once_after_clustering(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    universe = artifacts["hypothesis-universe-v1.json"]
    deduplication = artifacts["hypothesis-deduplication-v1.json"]
    known_ids = {item["hypothesis_id"] for item in universe["hypotheses"]}

    for candidate in deduplication["candidates"]:
        assert candidate["canonical_hypothesis_id"] in known_ids
        assert candidate["semantic_core_hash"] is not None


def test_three_persisted_lenses_deduplicate_to_seeded_estimands(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    deduplication = artifacts["hypothesis-deduplication-v1.json"]
    counts = deduplication["generation_counts"]
    retained = len(deduplication["clusters"])
    assert counts["candidate_formulations"] == 336
    assert counts["seeded_scientific_questions"] == 112
    assert counts["merged_equivalent_formulations"] == 336 - retained
    assert counts["rejected_formulations"] == 0
    assert counts["retained_semantic_cores"] == retained
    assert counts["threshold_only_hypotheses_retained"] == 0
    assert 80 <= retained <= 150
    assert sum(cluster["candidate_count"] for cluster in deduplication["clusters"]) == 336
    assert all(cluster["candidate_count"] % 3 == 0 for cluster in deduplication["clusters"])
    assert all(cluster["canonical_id_assigned_after_clustering"] for cluster in deduplication["clusters"])


def test_candidate_clusters_are_complete_bijective_evidence(
    builder: dict[str, Any], artifacts: dict[str, dict[str, Any]]
) -> None:
    universe = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    report = artifacts["hypothesis-deduplication-v1.json"]
    hypothesis_by_id = {item["hypothesis_id"]: item for item in universe}
    candidate_by_id = {item["candidate_id"]: item for item in report["candidates"]}
    clustered_ids = [
        candidate_id
        for cluster in report["clusters"]
        for candidate_id in cluster["candidate_ids"]
    ]

    assert len(clustered_ids) == len(set(clustered_ids)) == 336
    assert set(clustered_ids) == set(candidate_by_id)
    assert {row["canonical_hypothesis_id"] for row in report["clusters"]} == set(
        hypothesis_by_id
    )
    for cluster in report["clusters"]:
        canonical_id = cluster["canonical_hypothesis_id"]
        hypothesis = hypothesis_by_id[canonical_id]
        assert cluster["estimand_hash"] == builder["sha256_json"](
            cluster["estimand_signature"]
        )
        assert cluster["estimand_hash"] == hypothesis["estimand_hash"]
        assert cluster["assertion_hashes"] == [hypothesis["assertion_hash"]]
        for candidate_id in cluster["candidate_ids"]:
            candidate = candidate_by_id[candidate_id]
            assert candidate["canonical_hypothesis_id"] == canonical_id
            assert candidate["estimand_hash"] == cluster["estimand_hash"]
            assert candidate["normalized_formulation"] == builder["normalize_formulation"](
                candidate["formulation"]
            )


def test_semantic_and_protocol_identities_are_unique(
    artifacts: dict[str, dict[str, Any]],
) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    count = len(hypotheses)
    assert 80 <= count <= 150
    assert len({item["estimand_hash"] for item in hypotheses}) == count
    assert len({item["assertion_hash"] for item in hypotheses}) == count
    assert len({item["semantic_core_hash"] for item in hypotheses}) == count
    assert len({item["protocol_variant_hash"] for item in hypotheses}) == count
    assert [item["hypothesis_id"] for item in hypotheses] == sorted(
        item["hypothesis_id"] for item in hypotheses
    )


def test_estimand_signature_v2_excludes_identity_and_assertion_fields(
    builder: dict[str, Any],
) -> None:
    family, item = builder["_source_records"]()[0]
    baseline = builder["_estimand_signature"](family, item)
    mutated = replace(
        item,
        concept_key="identity_field_must_not_matter",
        title="Titre sans incidence sur la clé",
        claim="Prose sans incidence sur la clé.",
        expected_direction="ASSERTION_DIRECTION_MUST_NOT_MATTER",
    )
    assert builder["_estimand_signature"](family, mutated) == baseline
    assert builder["sha256_json"](builder["_estimand_signature"](family, mutated)) == (
        builder["sha256_json"](baseline)
    )


def test_semantic_discriminators_exist_only_for_true_base_collisions(
    builder: dict[str, Any],
) -> None:
    groups: dict[str, list[tuple[Any, Any]]] = {}
    for family, item in builder["_source_records"]():
        base_hash = builder["sha256_json"](
            builder["_base_estimand_signature"](family, item)
        )
        groups.setdefault(base_hash, []).append((family, item))
    collision_groups = [rows for rows in groups.values() if len(rows) > 1]
    assert len(collision_groups) == 11
    assert sum(len(rows) for rows in collision_groups) == 28
    for rows in groups.values():
        for _, item in rows:
            discriminator = item.estimand_projection.get("semantic_discriminator")
            if len(rows) == 1:
                assert discriminator is None
            else:
                builder["_validate_semantic_discriminator"](discriminator)


def test_missing_collision_discriminator_fails_closed(builder: dict[str, Any]) -> None:
    records = list(builder["_source_records"]())
    index = next(
        index
        for index, (_, item) in enumerate(records)
        if "semantic_discriminator" in item.estimand_projection
    )
    family, item = records[index]
    projection = copy.deepcopy(item.estimand_projection)
    del projection["semantic_discriminator"]
    records[index] = (family, replace(item, estimand_projection=projection))
    with pytest.raises(ValueError, match="semantic collision requires discriminators"):
        builder["build_artifacts"](records)


def test_each_seed_has_three_byte_identical_semantic_projections(
    builder: dict[str, Any],
) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in builder["RAW_CANDIDATES"]:
        groups.setdefault(candidate["seed_question_hash"], []).append(candidate)
    assert len(groups) == 112
    for rows in groups.values():
        assert len(rows) == 3
        assert len({builder["canonical_json"](row["structured_projection"]) for row in rows}) == 1
        assert {row["generation_lens"] for row in rows} == {
            "MECHANISM_FORMULATION",
            "OBSERVABLE_ESTIMAND_FORMULATION",
            "FALSIFICATION_FORMULATION",
        }


def test_all_required_topics_are_covered(artifacts: dict[str, dict[str, Any]]) -> None:
    hypotheses = artifacts["hypothesis-universe-v1.json"]["hypotheses"]
    tags = {tag for hypothesis in hypotheses for tag in hypothesis["topic_tags"]}
    required = {
        "pricing_1x2",
        "short_favourites",
        "long_outsiders",
        "draw_pricing",
        "overround",
        "bookmaker_dispersion",
        "odds_movements",
        "recent_form",
        "regression_to_mean",
        "goals_xg_overperformance",
        "clean_sheets",
        "home_away",
        "promoted_teams",
        "derbies",
        "fatigue",
        "rest",
        "congestion_calendar",
        "europe_before_after",
        "coach_change",
        "season_moment",
        "misleading_ranking",
        "difference_in_level",
        "interaction_1x2_over_under",
        "favourite_low_total",
        "outsider_high_total",
        "markets_unsynchronised",
        "volatility_regimes",
        "league_bias",
        "bookmaker_bias",
        "liquidity_bias",
    }
    assert required <= tags
