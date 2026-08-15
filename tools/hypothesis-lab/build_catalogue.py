"""Build and validate the Robin Hypothesis Lab V1 design artefacts.

This module is deliberately design-only.  It does not open a provider connection,
query a database, read R2, execute a backtest, or calculate a sporting result.  It
turns frozen research questions into protocols and exposes synthetic-only power tools.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

BASE_REVISION = "6cb8de636890959bd2ddb7e1c791a2eb04ee8763"
CATALOGUE_VERSION = "ROBIN_HYPOTHESIS_CATALOGUE_V1"
POWER_SIMULATOR_VERSION = "ROBIN_HYPOTHESIS_POWER_SIMULATOR_V1"
FIXTURE_SYMMETRIC_NORMALIZATION = "ZERO_SUM_ZERO_MEDIAN_UNIT_ROOT_MEAN_SQUARE"
TRUTH_KERNEL_VERSION = "ROBIN_SCIENTIFIC_TRUTH_KERNEL_V1"
PIT_CONTRACT_VERSION = "robin-point-in-time-lineage-v1"
STATUS_LABELS = ("EXPLORATORY", "UNVALIDATED", "NO_PROMOTION", "NO_BET")
REPORT_FILENAMES = (
    "hypothesis-universe-v1.json",
    "hypothesis-family-map-v1.json",
    "hypothesis-deduplication-v1.json",
    "hypothesis-priority-scorecard-v1.json",
    "first-25-experiment-protocols-v1.json",
    "negative-control-plan-v1.json",
)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "reports" / "hypothesis-lab"
SCHEMA_PATH = Path(__file__).with_name("hypothesis-lab-artifact-schema-v1.json")

CONTENT_HASH_ALGORITHM = "SHA256_CANONICAL_JSON_EXCLUDING_CONTENT_SHA256"
RECEIPT_FIELDS = (
    "receipt_id",
    "source_name",
    "request_identity",
    "payload_sha256",
    "source_published_at",
    "robin_first_observed_at",
    "robin_ingested_at",
    "capture_code_revision",
    "storage_identity",
    "availability_status",
    "supersedes_receipt_id",
)
LABEL_RECEIPT_FIELDS = (*RECEIPT_FIELDS, "result_available_at", "settlement_receipt_at")
TARGET_RECEIPT_FIELDS = (*RECEIPT_FIELDS, "target_window_id", "target_window_end")
PIT_AVAILABLE_AT_DERIVATION = "max(trusted source_published_at, robin_first_observed_at)"
PIT_PREDICTOR_ADMISSIBILITY = (
    "available_at <= cutoff_at and robin_ingested_at <= cutoff_at"
)
PIT_LABEL_ADMISSIBILITY = (
    "result_available_at >= event_at and settlement_receipt_at >= result_available_at"
)
PIT_TARGET_ADMISSIBILITY = (
    "cutoff_at < available_at <= target_window_end and robin_ingested_at <= target_window_end"
)
PIT_FORBIDDEN_BEFORE_CUTOFF = (
    "current fixture result and settlement",
    "current fixture post-match xG, shots, cards and events",
    "any source payload first received after cutoff_at",
    "any corrected or newer provider version first received after cutoff_at",
    "any model or calibration artifact created after predicted_at",
)
PIT_FUTURE_MUTATIONS = (
    "append future row",
    "change future value",
    "delete future row",
    "reorder future rows",
    "receive retroactive correction after cutoff",
)
OUTCOME_LABEL_DATASET = "append-only settled current-fixture outcome labels"
DEFAULT_PREDICTOR_CUTOFF: dict[str, str] = {
    "cutoff_id": "H2",
    "legacy_alias": "H-2",
    "rule": "kickoff_at - PT2H",
    "cutoff_class": "H2_PREMATCH",
}
POST_CUTOFF_TARGETS: dict[str, dict[str, Any]] = {
    "dispersion_to_later_consensus": {
        "dataset": "receipt-backed complete 1X2 snapshots at declared H1 target window",
        "outcome_construct": "RECEIPT_BACKED_H1_1X2_DISPERSION_TARGET",
        "primary_metric": "dispersion_H1_minus_dispersion_H2",
        "target_window_id": "H1",
        "target_window_end_rule": "kickoff_at - PT1H + PT5M",
    },
    "one_x_two_total_incoherence": {
        "dataset": (
            "receipt-backed synchronized 1X2 and total snapshots at declared H1 target window"
        ),
        "outcome_construct": "RECEIPT_BACKED_H1_CROSS_MARKET_ALIGNMENT_TARGET",
        "primary_metric": "later_alignment_H1_coefficient",
        "target_window_id": "H1",
        "target_window_end_rule": "kickoff_at - PT1H + PT5M",
    },
    "bookmaker_deviation_reversion": {
        "dataset": (
            "receipt-backed complete bookmaker 1X2 snapshots at declared H2 target window"
        ),
        "outcome_construct": "RECEIPT_BACKED_H2_BOOKMAKER_DEVIATION_TARGET",
        "primary_metric": "rho_minus_one",
        "target_window_id": "H2",
        "target_window_end_rule": "kickoff_at - PT2H + PT5M",
        "predictor_cutoff": {
            "cutoff_id": "H24",
            "legacy_alias": "H-24",
            "rule": "kickoff_at - PT24H",
            "cutoff_class": "H24_PREMATCH",
        },
    },
}

ZERO_EXTERNAL_EFFECTS: dict[str, int] = {
    "provider_calls": 0,
    "neon_api_calls": 0,
    "production_postgresql_connections": 0,
    "production_sql_reads": 0,
    "production_sql_writes": 0,
    "r2_operations": 0,
    "live_workflow_dispatches": 0,
    "purchases": 0,
    "real_bets": 0,
    "promotions": 0,
    "social_publications": 0,
}

DEVIG_PROPORTIONAL = {
    "devig_method": "PROPORTIONAL",
    "devig_version": "PROPORTIONAL_COMPLETE_MARKET_V1",
    "devig_definition_hash": (
        "265d91ae91f793523180d617a3cbcd90ee95ac483d7fdbfcaa3547868e076684"
    ),
}
DEVIG_SHIN = {
    "devig_method": "SHIN",
    "devig_version": "LEGACY_SHIN_VAGUE1_V1",
    "devig_definition_hash": (
        "3ff94a3daf36b0995717522ed3605bf0754d799705df028414043587b7375367"
    ),
}

SCORE_WEIGHTS: dict[str, int] = {
    "mechanistic_plausibility": 15,
    "data_availability": 15,
    "point_in_time_provability": 20,
    "statistical_power": 10,
    "originality": 10,
    "cross_league_stability": 10,
    "falsifiability": 10,
    "compute_cost": 5,
    "strategic_value": 5,
}

# Exact two-sided assertions. Every other expected-direction code is directional and must
# carry a signed axis; this prevents an opposite-sign effect from supporting the prose claim.
TWO_SIDED_DIRECTION_CODES = {
    "ADJUSTED_FORM_COEFFICIENT_NON_ZERO",
    "AWAY_FAVOURITE_COHORT_INTERACTION_NON_ZERO",
    "AWAY_FAVOURITE_HIGH_TOTAL_VARIANCE_DIFFERS",
    "AWAY_SHORT_FAVOURITE_RESIDUAL_DIFFERS",
    "BOOKMAKER_OUTCOME_INTERACTION_NON_ZERO",
    "BTTS_COHERENCE_RESIDUAL_NON_ZERO",
    "CALIBRATION_ERROR_VARIES_WITH_ENTROPY",
    "COACH_CHANGE_MEAN_SHIFT_NON_ZERO",
    "CONSECUTIVE_AWAY_INTERACTION_NON_ZERO",
    "CONSENSUS_ESTIMATOR_CALIBRATION_DIFFERS",
    "CROSS_MARKET_MARGIN_COMPONENT_NON_ZERO",
    "DRAW_AND_FAVOURITE_DISPERSION_EFFECTS_DIFFER",
    "FAVOURITE_LABEL_DISCONTINUITY_NON_ZERO",
    "HOLIDAY_PERIOD_INCREMENT_NON_ZERO",
    "HOME_ADVANTAGE_VARIES_BY_SEASON_PHASE",
    "HOME_AWAY_RESIDUAL_DIFFERENCE_NON_ZERO",
    "HOME_MODERATES_FAVOURITE_LOW_TOTAL_INTERACTION",
    "LATE_MOVEMENT_RESIDUAL_VARIANCE_DIFFERS",
    "LEAGUE_STRENGTH_INTERCEPTS_NON_ZERO",
    "LONG_REST_NONLINEARITY_NON_ZERO",
    "MATHEMATICAL_OBJECTIVE_INTERACTION_NON_ZERO",
    "MISSINGNESS_DEPENDS_ON_MARKET_STATE",
    "ONE_X_TWO_HANDICAP_MISMATCH_RESIDUAL_NON_ZERO",
    "OUTCOME_ENTROPY_MODERATES_TOTAL_VOLATILITY",
    "PIECEWISE_CALIBRATION_SLOPE_CHANGE",
    "POSTPONEMENT_COMPRESSION_EFFECT_NON_ZERO",
    "PROMOTED_ADAPTATION_DIFFERS_BY_VENUE",
    "PROMOTED_PAIR_UNCERTAINTY_DIFFERS",
    "RANK_SPACING_COEFFICIENT_NON_ZERO",
    "RECEIPTED_NEWS_JUMP_DIFFERS",
    "RELEGATION_DISTANCE_VARIANCE_EFFECT_NON_ZERO",
    "RESIDUAL_DEPENDS_ON_REMAINDER_ALLOCATION",
    "SHORTENING_AND_DRIFT_EFFECTS_DIFFER",
    "SOURCE_OUTCOME_OF_MASS_TRANSFER_MATTERS",
    "STRENGTH_GAP_CURVATURE_NON_ZERO",
    "STRENGTH_GAP_HOME_INTERACTION_NON_ZERO",
    "STRENGTH_UNCERTAINTY_HAS_SEASON_PHASE_BREAK",
    "TOTAL_AND_FAVOURITE_COMOVEMENT_INTERACTION_NON_ZERO",
    "TRAVEL_DISTANCE_MODERATES_AWAY_EFFECT",
    "VENUE_SPECIFIC_FORM_COEFFICIENT_NON_ZERO",
    "XG_TREND_MODERATES_SCORING_STREAK",
}


@dataclass(frozen=True)
class IdeaSpec:
    concept_key: str
    title: str
    claim: str
    expected_direction: str
    topic_tags: tuple[str, ...]
    claim_type: str
    orientation: str
    effect_scale: str
    estimand_definition: str
    interval_method: str
    estimand_projection: dict[str, Any]
    extra_variables: tuple[str, ...] = ()
    prior_art_refs: tuple[str, ...] = ()
    observability_status: str = "PROSPECTIVE_CAPTURE_REQUIRED"
    observability_reason: str = "RECEIPT_BACKED_CAPTURE_NOT_YET_MATERIALIZED"


@dataclass(frozen=True)
class FamilySpec:
    family_id: str
    label: str
    purpose: str
    quota: int
    first_portfolio_quota: int
    markets: tuple[str, ...]
    population: str
    unit_of_analysis: str
    mechanism_class: str
    assumed_mechanism: str
    base_variables: tuple[str, ...]
    required_datasets: tuple[str, ...]
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    minimum_sample: int
    minimum_effect_size: float
    adversarial_slices: tuple[str, ...]
    compute_cost: str
    estimated_cpu_hours: float
    estimated_human_hours: float
    main_risk: str
    score_profile: tuple[int, int, int, int, int, int, int, int, int]


SOURCE_PATH = Path(__file__).with_name("catalogue-source-v1.json")
RAW_CANDIDATE_SOURCE_PATH = Path(__file__).with_name("raw-candidates-v1.json")
PORTFOLIO_SOURCE_PATH = Path(__file__).with_name("portfolio-strata-v1.json")
PRIOR_ART_SOURCE_PATHS = (
    REPO_ROOT / "docs" / "registre_hypotheses_v1.yaml",
    REPO_ROOT / "docs" / "hypothesis-intelligence" / "PROSPECTIVE-HYPOTHESIS-PROTOCOL.md",
    REPO_ROOT / "configs" / "deep-football-v1.json",
    REPO_ROOT / "reports" / "hypothesis-genome" / "property-semantic-roles.json",
)


def _markdown_fragment(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _validate_prior_art_references(ideas: dict[str, tuple[IdeaSpec, ...]]) -> None:
    source_text = {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in PRIOR_ART_SOURCE_PATHS
    }
    unresolved: set[str] = set()
    for item in (idea for family_ideas in ideas.values() for idea in family_ideas):
        for reference in item.prior_art_refs:
            if "#" in reference:
                relative_path, fragment = reference.split("#", maxsplit=1)
                text = source_text.get(relative_path)
                headings = (
                    {
                        _markdown_fragment(line.lstrip("# "))
                        for line in text.splitlines()
                        if line.startswith("#")
                    }
                    if text is not None
                    else set()
                )
                if fragment not in headings:
                    unresolved.add(reference)
                continue
            token_pattern = re.compile(
                rf"(?<![A-Za-z0-9_-]){re.escape(reference)}(?![A-Za-z0-9_-])"
            )
            if not any(token_pattern.search(text) for text in source_text.values()):
                unresolved.add(reference)
    if unresolved:
        raise ValueError(
            "unresolved prior-art references: " + ", ".join(sorted(unresolved))
        )

def _load_catalogue_source() -> tuple[
    tuple[FamilySpec, ...],
    dict[str, tuple[IdeaSpec, ...]],
    tuple[dict[str, Any], ...],
]:
    raw: dict[str, Any] = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "robin-hypothesis-catalogue-source-v1":
        raise ValueError("unexpected catalogue source schema")
    if raw.get("immutable_base_revision") != BASE_REVISION:
        raise ValueError("catalogue source base revision drift")
    if tuple(raw.get("status_labels", ())) != STATUS_LABELS:
        raise ValueError("catalogue source safety labels changed")

    families: list[FamilySpec] = []
    ideas: dict[str, tuple[IdeaSpec, ...]] = {}
    for raw_family in raw["families"]:
        family_row = dict(raw_family)
        raw_ideas = family_row.pop("ideas")
        for key in (
            "markets",
            "base_variables",
            "required_datasets",
            "secondary_metrics",
            "adversarial_slices",
            "score_profile",
        ):
            family_row[key] = tuple(family_row[key])
        family = FamilySpec(**family_row)
        family_ideas_rows = []
        for item in raw_ideas:
            item_row = dict(item)
            item_row.pop("priority", None)  # Legacy author nomination; never used for ranking/selection.
            item_row["topic_tags"] = tuple(item_row["topic_tags"])
            item_row["extra_variables"] = tuple(item_row["extra_variables"])
            item_row["prior_art_refs"] = tuple(item_row["prior_art_refs"])
            family_ideas_rows.append(IdeaSpec(**item_row))
        family_ideas = tuple(family_ideas_rows)
        families.append(family)
        ideas[family.family_id] = family_ideas

    _validate_prior_art_references(ideas)
    controls = tuple(dict(control) for control in raw["negative_controls"])
    if len(families) != 8 or sum(len(value) for value in ideas.values()) != 112:
        raise ValueError("catalogue source count drift")
    if len(controls) != 9:
        raise ValueError("negative-control source count drift")
    return tuple(families), ideas, controls


FAMILIES, IDEAS, NEGATIVE_CONTROLS = _load_catalogue_source()
SOURCE_SHA256 = hashlib.sha256(
    SOURCE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
).hexdigest()
RAW_CANDIDATE_SOURCE_SHA256 = hashlib.sha256(
    RAW_CANDIDATE_SOURCE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
).hexdigest() if RAW_CANDIDATE_SOURCE_PATH.exists() else "0" * 64
PORTFOLIO_SOURCE_SHA256 = hashlib.sha256(
    PORTFOLIO_SOURCE_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
).hexdigest() if PORTFOLIO_SOURCE_PATH.exists() else "0" * 64


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used for every identity hash."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def render_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def normalize_formulation(value: str) -> str:
    """Normalize prose for audit display; structural hashes never depend on prose alone."""

    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = normalized.lower()
    replacements = {
        "favourite": "favori",
        "favorite": "favori",
        "home": "domicile",
        "away": "exterieur",
        "draw": "nul",
        "odds": "cote",
        "cotes": "cote",
    }
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return " ".join(replacements.get(token, token) for token in tokens)


def _verified_source_document(path: Path, schema_version: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != schema_version:
        raise ValueError(f"unexpected source schema: {path.name}")
    if document.get("immutable_base_revision") != BASE_REVISION:
        raise ValueError(f"source base revision drift: {path.name}")
    if tuple(document.get("status_labels", ())) != STATUS_LABELS:
        raise ValueError(f"source safety labels changed: {path.name}")
    declared_hash = document.get("content_sha256")
    hash_input = copy.deepcopy(document)
    hash_input.pop("content_sha256", None)
    if declared_hash != sha256_json(hash_input):
        raise ValueError(f"source content hash mismatch: {path.name}")
    return document


def _load_raw_candidate_source() -> tuple[dict[str, Any], ...]:
    document = _verified_source_document(
        RAW_CANDIDATE_SOURCE_PATH, "robin-raw-candidates-v1"
    )
    candidates = tuple(dict(candidate) for candidate in document["candidates"])
    if document.get("seed_question_count") != 112 or len(candidates) != 336:
        raise ValueError("raw candidate count drift")
    if document.get("canonical_hypothesis_ids_present") is not False:
        raise ValueError("raw candidates must precede canonical hypothesis assignment")
    if document.get("threshold_sweep_used_to_inflate_count") is not False:
        raise ValueError("threshold sweeps cannot inflate the candidate count")
    if document.get("sporting_results_used") is not False:
        raise ValueError("sporting results cannot generate candidates")

    lenses = set(document["generation_lenses"])
    source_by_seed = {
        sha256_json({"title": item.title, "claim": item.claim}): item
        for family in FAMILIES
        for item in IDEAS[family.family_id]
    }
    if len(source_by_seed) != document["seed_question_count"]:
        raise ValueError("seed-question source hashes are not unique")
    seen_ids: set[str] = set()
    seed_groups: dict[str, list[dict[str, Any]]] = {}
    estimand_groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        identity_input = copy.deepcopy(candidate)
        del identity_input["candidate_id"]
        expected_id = f"RDS-RAW-V1-{sha256_json(identity_input)[:16].upper()}"
        if candidate_id != expected_id or candidate_id in seen_ids:
            raise ValueError("raw candidate identity drift")
        seen_ids.add(candidate_id)
        if candidate["state"] != "RAW_UNADJUDICATED":
            raise ValueError("raw candidate was prematurely adjudicated")
        if candidate["generation_lens"] not in lenses:
            raise ValueError("unknown candidate-generation lens")
        seed_groups.setdefault(candidate["seed_question_hash"], []).append(candidate)
        estimand_hash = sha256_json(candidate["structured_projection"])
        estimand_groups.setdefault(estimand_hash, []).append(candidate)
    if len(seed_groups) != document["seed_question_count"]:
        raise ValueError("raw seed-question lineage count drift")
    if set(seed_groups) != set(source_by_seed):
        raise ValueError("raw seed-question lineage does not reproduce the catalogue source")
    for seed_hash, group in seed_groups.items():
        if len(group) != 3 or {row["generation_lens"] for row in group} != lenses:
            raise ValueError("each seeded question must have exactly three declared lenses")
        source_item = source_by_seed[seed_hash]
        for row in group:
            if (
                row["structured_projection"] != source_item.estimand_projection
                or row["asserted_direction"] != source_item.expected_direction
                or row["claim_type"] != source_item.claim_type
                or row["orientation"] != source_item.orientation
            ):
                raise ValueError("raw seed assertion or estimand drifted from its frozen source")
    if not 80 <= len(estimand_groups) <= 150:
        raise ValueError("raw semantic clustering must yield 80..150 estimands")
    for group in estimand_groups.values():
        assertions = {
            (row["asserted_direction"], row["claim_type"], row["orientation"])
            for row in group
        }
        if len(assertions) != 1:
            raise ValueError("assertion conflict inside an estimand cluster")
    return candidates


def _load_portfolio_source() -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    document = _verified_source_document(PORTFOLIO_SOURCE_PATH, "robin-portfolio-strata-v1")
    strata = tuple(dict(stratum) for stratum in document["strata"])
    if document.get("portfolio_size") != 25 or len(strata) != 25:
        raise ValueError("portfolio source must freeze exactly 25 strata")
    if document.get("selection_flags_from_catalogue_used") is not False:
        raise ValueError("portfolio selection cannot use author nomination flags")
    if document.get("historical_roi_used") is not False:
        raise ValueError("portfolio selection cannot use historical ROI")
    if [row["portfolio_order"] for row in strata] != list(range(1, 26)):
        raise ValueError("portfolio stratum order drift")
    if len({row["stratum_id"] for row in strata}) != 25:
        raise ValueError("portfolio stratum IDs are not unique")
    return dict(document["common_operational_rules"]), strata


RAW_CANDIDATES = _load_raw_candidate_source()
PORTFOLIO_COMMON_RULES, PORTFOLIO_STRATA = _load_portfolio_source()


def _family_by_id() -> dict[str, FamilySpec]:
    return {family.family_id: family for family in FAMILIES}


def _source_records() -> tuple[tuple[FamilySpec, IdeaSpec], ...]:
    records: list[tuple[FamilySpec, IdeaSpec]] = []
    for family in FAMILIES:
        records.extend((family, item) for item in IDEAS[family.family_id])
    return tuple(records)


def _markets_for(family: FamilySpec, item: IdeaSpec) -> tuple[str, ...]:
    if family.family_id == "FAMILY_CROSS_MARKET":
        if item.concept_key == "one_x_two_btts_coherence":
            return ("1X2", "BTTS")
        if item.concept_key == "one_x_two_handicap_coherence":
            return ("1X2", "ASIAN_HANDICAP")
        return ("1X2", "OVER_UNDER_2_5")
    if "interaction_1x2_over_under" in item.topic_tags or "markets_unsynchronised" in item.topic_tags:
        return ("1X2", "OVER_UNDER_2_5")
    return ("1X2",)


def _required_datasets_for(family: FamilySpec, item: IdeaSpec) -> tuple[str, ...]:
    markets = _markets_for(family, item)
    if family.family_id == "FAMILY_CROSS_MARKET":
        market_sources = {
            "OVER_UNDER_2_5": "same-cutoff receipt-backed total snapshots",
            "BTTS": "same-cutoff receipt-backed BTTS snapshots",
            "ASIAN_HANDICAP": "same-cutoff receipt-backed handicap snapshots",
        }
        return (
            "same-cutoff receipt-backed 1X2 snapshots",
            *(market_sources[market] for market in markets if market != "1X2"),
            "append-only settled outcomes",
        )
    if family.family_id == "FAMILY_VENUE_COHORT":
        market_source = (
            "receipt-backed 1X2 and total snapshots"
            if "OVER_UNDER_2_5" in markets
            else "receipt-backed complete 1X2 snapshots"
        )
        return (*family.required_datasets[:3], market_source)
    return family.required_datasets


def _predictor_datasets_for(family: FamilySpec, item: IdeaSpec) -> tuple[str, ...]:
    predictors = []
    for dataset in _required_datasets_for(family, item):
        tokens = dataset.lower().replace("-", " ").split()
        if "settled" in tokens and any(token.startswith("outcome") for token in tokens):
            continue
        predictors.append(dataset)
    return tuple(predictors)


def _predictor_cutoff_for(concept_key: str) -> dict[str, str]:
    target = POST_CUTOFF_TARGETS.get(concept_key)
    return dict(
        target.get("predictor_cutoff", DEFAULT_PREDICTOR_CUTOFF)
        if target
        else DEFAULT_PREDICTOR_CUTOFF
    )


def _all_datasets_for(family: FamilySpec, item: IdeaSpec) -> tuple[str, ...]:
    predictors = list(_predictor_datasets_for(family, item))
    if item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
        predictors.append(item.observability_reason)
    target = POST_CUTOFF_TARGETS.get(item.concept_key)
    targets = (target["dataset"],) if target else ()
    return (*predictors, *targets, OUTCOME_LABEL_DATASET)


def _predictor_role(dataset: str) -> str:
    normalized = dataset.lower()
    if any(
        token in normalized
        for token in ("1x2", "bookmaker snapshot", "market snapshot", "total snapshot", "btts snapshot", "handicap snapshot")
    ):
        return "ODDS"
    if any(
        token in normalized
        for token in ("registry", "fixture identity", "snapshot clock", "venue coordinates")
    ):
        return "METADATA"
    return "FEATURE"


def _estimand_signature(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    signature = copy.deepcopy(item.estimand_projection)
    predictor_cutoff = _predictor_cutoff_for(item.concept_key)
    expected_contract = {
        "market_set": list(_markets_for(family, item)),
        "population_scope": family.population,
        "unit_of_analysis": family.unit_of_analysis,
        "effect_scale": item.effect_scale,
        "cutoff_class": predictor_cutoff["cutoff_class"],
    }
    for field, expected in expected_contract.items():
        if signature.get(field) != expected:
            raise ValueError(f"estimand projection drift: {item.concept_key}:{field}")
    return signature


def _base_estimand_signature(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    signature = _estimand_signature(family, item)
    signature.pop("semantic_discriminator", None)
    return signature


def _validate_semantic_discriminator(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"transform", "comparator"}:
        raise ValueError("semantic discriminator must contain transform and comparator ASTs")
    for node_name in ("transform", "comparator"):
        node = value[node_name]
        if not isinstance(node, dict) or set(node) != {"operator", "operands", "qualifiers"}:
            raise ValueError("semantic discriminator node is not an operator/operand AST")
        if not isinstance(node["operator"], str) or not re.fullmatch(
            r"[A-Z][A-Z0-9_]*", node["operator"]
        ):
            raise ValueError("semantic discriminator operator is not canonical")
        if (
            not isinstance(node["operands"], list)
            or not node["operands"]
            or not all(isinstance(token, str) and token for token in node["operands"])
            or not isinstance(node["qualifiers"], list)
            or not all(isinstance(token, str) and token for token in node["qualifiers"])
        ):
            raise ValueError("semantic discriminator operands or qualifiers are invalid")


def _semantic_core(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    estimand_hash = sha256_json(_estimand_signature(family, item))
    return {
        "estimand_hash": estimand_hash,
        "expected_direction": item.expected_direction,
        "claim_type": item.claim_type,
        "orientation": item.orientation,
    }


def _canonical_devig_protocol(markets: Sequence[str]) -> dict[str, Any]:
    markets = tuple(markets)
    binary_components = [
        {"market": market, **DEVIG_PROPORTIONAL} for market in markets if market != "1X2"
    ]
    branches = [
        {
            "branch_id": "BRANCH_1X2_PROPORTIONAL",
            "components": [{"market": "1X2", **DEVIG_PROPORTIONAL}, *binary_components],
        },
        {
            "branch_id": "BRANCH_1X2_SHIN",
            "components": [{"market": "1X2", **DEVIG_SHIN}, *binary_components],
        },
    ]
    return {
        "authority_status": "DEVIG_PROTOCOL_CONFLICT",
        "mode": "PARALLEL_NON_AGGREGATED_BRANCHES",
        "branches": branches,
        "branch_results_aggregated": False,
        "selection_rule": "FROZEN_EX_ANTE;NEVER_SELECT_A_BRANCH_FROM_OBSERVED_RESULTS",
        "missing_method_policy": "FAIL_CLOSED",
        "two_outcome_rule": (
            "Use PROPORTIONAL only for the two-outcome total component; a SHIN request would be "
            "proportional-equivalent and is not counted as an independent branch."
        ),
    }


def _devig_protocol(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    return _canonical_devig_protocol(_markets_for(family, item))


def _score(family: FamilySpec, item: IdeaSpec) -> dict[str, int]:
    scores = dict(zip(SCORE_WEIGHTS, family.score_profile, strict=True))
    if len(_markets_for(family, item)) > 1:
        scores["data_availability"] -= 1
        scores["point_in_time_provability"] -= 1
        scores["originality"] = min(SCORE_WEIGHTS["originality"], scores["originality"] + 1)
        scores["compute_cost"] = max(0, scores["compute_cost"] - 1)
    if {"derbies", "promoted_teams", "coach_change"} & set(item.topic_tags):
        scores["statistical_power"] = max(0, scores["statistical_power"] - 1)
    if {"regression_to_mean", "rest", "overround"} & set(item.topic_tags):
        scores["mechanistic_plausibility"] = min(
            SCORE_WEIGHTS["mechanistic_plausibility"], scores["mechanistic_plausibility"] + 1
        )
    if "league_bias" in item.topic_tags:
        scores["cross_league_stability"] = max(0, scores["cross_league_stability"] - 1)
    if item.extra_variables:
        scores["data_availability"] = max(0, scores["data_availability"] - 1)
        scores["point_in_time_provability"] = max(
            0, scores["point_in_time_provability"] - 1
        )
    if item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
        scores["data_availability"] = min(scores["data_availability"], 3)
        scores["point_in_time_provability"] = min(scores["point_in_time_provability"], 2)
    return scores


def _score_rationale_codes(family: FamilySpec, item: IdeaSpec) -> list[str]:
    codes = ["FAMILY_BASELINE_RUBRIC"]
    if len(_markets_for(family, item)) > 1:
        codes.append("CROSS_MARKET_DATA_PIT_AND_COMPUTE_PENALTY_ORIGINALITY_CREDIT")
    if {"derbies", "promoted_teams", "coach_change"} & set(item.topic_tags):
        codes.append("RARE_COHORT_POWER_PENALTY")
    if {"regression_to_mean", "rest", "overround"} & set(item.topic_tags):
        codes.append("DIRECT_MECHANISM_CREDIT")
    if "league_bias" in item.topic_tags:
        codes.append("CROSS_LEAGUE_TRANSFER_PENALTY")
    if item.extra_variables:
        codes.append("EXTRA_SOURCE_DATA_AND_PIT_PENALTY")
    if item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
        codes.append("MISSING_SOURCE_CONTRACT_CAP")
    return codes


def _point_in_time_contract(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    target = POST_CUTOFF_TARGETS.get(item.concept_key)
    predictor_cutoff = _predictor_cutoff_for(item.concept_key)
    predictor_sources = list(_predictor_datasets_for(family, item))
    if item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
        predictor_sources.append(item.observability_reason)
    return {
        "contract_version": PIT_CONTRACT_VERSION,
        "event_at": {
            "fixture": "kickoff_at",
            "covariates": "business event time from the source payload",
            "availability_proof": False,
        },
        "available_at": {
            "required": True,
            "derivation": PIT_AVAILABLE_AT_DERIVATION,
            "event_at_substitution_forbidden": True,
        },
        "cutoff_at": {
            "cutoff_id": predictor_cutoff["cutoff_id"],
            "legacy_alias": predictor_cutoff["legacy_alias"],
            "rule": predictor_cutoff["rule"],
            "admissibility": PIT_PREDICTOR_ADMISSIBILITY,
            "boundary_equality_allowed": True,
        },
        "predictor_receipt_backed_sources_required": predictor_sources,
        "post_cutoff_target_receipt_backed_sources_required": (
            [target["dataset"]] if target else []
        ),
        "post_cutoff_target_admissibility": (
            {
                "rule": PIT_TARGET_ADMISSIBILITY,
                "target_window_id": target["target_window_id"],
                "target_window_end_rule": target["target_window_end_rule"],
                "eligible_as_pre_cutoff_predictor": False,
            }
            if target
            else None
        ),
        "post_cutoff_target_receipt_fields_required": (
            list(TARGET_RECEIPT_FIELDS) if target else []
        ),
        "label_receipt_backed_sources_required": [OUTCOME_LABEL_DATASET],
        "predictor_receipt_fields_required": list(RECEIPT_FIELDS),
        "label_receipt_fields_required": list(LABEL_RECEIPT_FIELDS),
        "label_admissibility": PIT_LABEL_ADMISSIBILITY,
        "historical_evidence_status": "POINT_IN_TIME_NOT_PROVEN",
        "prospective_observability_status": item.observability_status,
        "prospective_observability_reason": item.observability_reason,
        "data_forbidden_before_cutoff": list(PIT_FORBIDDEN_BEFORE_CUTOFF),
        "future_mutation_test": {
            "mutations": list(PIT_FUTURE_MUTATIONS),
            "required_invariant": (
                "eligibility hash, feature snapshot hash and protocol decision for every earlier "
                "cutoff remain byte-identical"
            ),
            "failure_policy": "FAIL_CLOSED_POINT_IN_TIME_INPUT_NOT_PROVEN",
        },
    }


def _data_dependencies(family: FamilySpec, item: IdeaSpec) -> list[dict[str, Any]]:
    dependencies = []
    for dataset in _predictor_datasets_for(family, item):
        dependencies.append(
            {
                "dataset": dataset,
                "role": _predictor_role(dataset),
                "analysis_usage": "PRE_CUTOFF_PREDICTOR",
                "receipt_backed": True,
                "snapshot_resolution": "NOT_YET_MATERIALIZED",
                "historical_point_in_time_status": "POINT_IN_TIME_NOT_PROVEN",
                "required_before_execution": True,
                "temporal_admissibility": PIT_PREDICTOR_ADMISSIBILITY,
                "eligible_as_pre_cutoff_predictor": True,
                "result_available_at_required": False,
                "settlement_receipt_required": False,
            }
        )
    dependencies.append(
        {
            "dataset": OUTCOME_LABEL_DATASET,
            "role": "LABEL",
            "analysis_usage": (
                "SECONDARY_METRIC_LABEL_ONLY"
                if item.concept_key in POST_CUTOFF_TARGETS
                else "PRIMARY_OR_SECONDARY_SETTLED_OUTCOME"
            ),
            "receipt_backed": True,
            "snapshot_resolution": "NOT_YET_MATERIALIZED",
            "historical_point_in_time_status": "POINT_IN_TIME_NOT_PROVEN",
            "required_before_execution": True,
            "temporal_admissibility": PIT_LABEL_ADMISSIBILITY,
            "eligible_as_pre_cutoff_predictor": False,
            "result_available_at_required": True,
            "settlement_receipt_required": True,
        }
    )
    target = POST_CUTOFF_TARGETS.get(item.concept_key)
    if target:
        dependencies.append(
            {
                "dataset": target["dataset"],
                "role": "TARGET",
                "analysis_usage": "PRIMARY_MODEL_OUTCOME",
                "receipt_backed": True,
                "snapshot_resolution": "NOT_YET_MATERIALIZED",
                "historical_point_in_time_status": "POINT_IN_TIME_NOT_PROVEN",
                "required_before_execution": True,
                "temporal_admissibility": PIT_TARGET_ADMISSIBILITY,
                "eligible_as_pre_cutoff_predictor": False,
                "result_available_at_required": False,
                "settlement_receipt_required": False,
            }
        )
    if item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
        dependencies.append(
            {
                "dataset": item.observability_reason,
                "role": "FEATURE",
                "analysis_usage": "PRE_CUTOFF_PREDICTOR",
                "receipt_backed": True,
                "snapshot_resolution": "SOURCE_CONTRACT_ABSENT",
                "historical_point_in_time_status": "POINT_IN_TIME_NOT_PROVEN",
                "required_before_execution": True,
                "temporal_admissibility": PIT_PREDICTOR_ADMISSIBILITY,
                "eligible_as_pre_cutoff_predictor": True,
                "result_available_at_required": False,
                "settlement_receipt_required": False,
            }
        )
    return dependencies


def _falsification_contract(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    delta = family.minimum_effect_size
    common = {
        "claim_type": item.claim_type,
        "orientation": item.orientation,
        "estimand_definition": item.estimand_definition,
        "effect_scale": item.effect_scale,
        "minimum_effect": delta,
        "confidence_level": 0.95,
        "interval_method": item.interval_method,
        "target_q": 0.05,
        "boundary_equality_rule": (
            "support_bound_equality_included;falsification_bound_equality_inconclusive"
        ),
        "invalidity_rule": (
            "Missing minimum sample, invalid PIT proof, a negative-control alarm or invalid "
            "de-vig execution yields BLOCKED_OR_INVALID, never support or falsification."
        ),
        "branch_rule": "classify each de-vig branch separately; never average or pick the better branch",
    }
    if item.claim_type == "SIGNED_MINIMUM" and item.orientation == "POSITIVE":
        common.update(
            {
                "supported_inequality": f"ci95_lower_bound >= {delta} and q_value <= 0.05",
                "falsified_inequality": f"ci95_upper_bound < {delta}",
                "inconclusive_inequality": (
                    f"ci95_lower_bound < {delta} <= ci95_upper_bound"
                ),
            }
        )
    elif item.claim_type == "SIGNED_MINIMUM" and item.orientation == "NEGATIVE":
        common.update(
            {
                "supported_inequality": f"ci95_upper_bound <= -{delta} and q_value <= 0.05",
                "falsified_inequality": f"ci95_lower_bound > -{delta}",
                "inconclusive_inequality": (
                    f"ci95_lower_bound <= -{delta} < ci95_upper_bound"
                ),
            }
        )
    elif item.claim_type == "ABSOLUTE_MINIMUM" and item.orientation == "UNSIGNED":
        common.update(
            {
                "supported_inequality": (
                    f"(ci95_lower_bound >= {delta} or ci95_upper_bound <= -{delta}) "
                    "and q_value <= 0.05"
                ),
                "falsified_inequality": (
                    f"ci95_lower_bound > -{delta} and ci95_upper_bound < {delta}"
                ),
                "inconclusive_inequality": "all other valid interval configurations",
            }
        )
    else:
        raise ValueError(f"invalid structured claim contract: {item.concept_key}")
    return common


def classify_interval(
    contract: dict[str, Any], lower_bound: float, upper_bound: float, q_value: float
) -> str:
    """Classify a synthetic interval under the frozen, result-agnostic decision semantics."""

    if lower_bound > upper_bound or not 0 <= q_value <= 1:
        raise ValueError("invalid interval or q-value")
    delta = float(contract["minimum_effect"])
    claim_type = contract["claim_type"]
    orientation = contract["orientation"]
    if claim_type == "SIGNED_MINIMUM" and orientation == "POSITIVE":
        if lower_bound >= delta and q_value <= contract["target_q"]:
            return "SUPPORTED"
        if upper_bound < delta:
            return "FALSIFIED"
        return "INCONCLUSIVE"
    if claim_type == "SIGNED_MINIMUM" and orientation == "NEGATIVE":
        if upper_bound <= -delta and q_value <= contract["target_q"]:
            return "SUPPORTED"
        if lower_bound > -delta:
            return "FALSIFIED"
        return "INCONCLUSIVE"
    if claim_type == "ABSOLUTE_MINIMUM" and orientation == "UNSIGNED":
        if (lower_bound >= delta or upper_bound <= -delta) and q_value <= contract["target_q"]:
            return "SUPPORTED"
        if lower_bound > -delta and upper_bound < delta:
            return "FALSIFIED"
        return "INCONCLUSIVE"
    raise ValueError("unsupported claim contract")


def benjamini_hochberg_q_values(p_values: Sequence[float]) -> list[float]:
    """Return deterministic BH adjusted q-values in the original order."""

    if not p_values or any(not 0 <= value <= 1 for value in p_values):
        raise ValueError("BH requires one or more p-values in [0,1]")
    ordered = sorted(enumerate(p_values), key=lambda value: (value[1], value[0]))
    adjusted = [1.0] * len(ordered)
    running = 1.0
    for reverse_index in range(len(ordered) - 1, -1, -1):
        _, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * len(ordered) / rank, 1.0)
        adjusted[reverse_index] = running
    result = [1.0] * len(ordered)
    for sorted_index, (original_index, _) in enumerate(ordered):
        result[original_index] = adjusted[sorted_index]
    return result


def wilson_lower_bound(successes: int, trials: int) -> float:
    """Return the frozen two-sided 95% Wilson lower confidence bound."""

    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("invalid binomial counts")
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1 + z**2 / trials
    centre = proportion + z**2 / (2 * trials)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / trials + z**2 / (4 * trials**2)
    )
    return (centre - margin) / denominator


def _seed_from_parts(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def derive_power_latent_seed(
    master_seed: int, eligible_units: int, replicate_index: int
) -> int:
    """Derive the common latent-fixture seed shared by all de-vig branches."""

    return _seed_from_parts("LATENT", master_seed, eligible_units, replicate_index)


def derive_power_branch_transform_seed(latent_seed: int, branch_id: str) -> int:
    """Derive only the branch-specific transform seed from a common latent draw."""

    return _seed_from_parts("BRANCH_TRANSFORM", latent_seed, branch_id)


def derive_power_replicate_seed(
    master_seed: int, eligible_units: int, replicate_index: int, branch_id: str
) -> int:
    """Compatibility wrapper returning the branch transform seed."""

    latent_seed = derive_power_latent_seed(master_seed, eligible_units, replicate_index)
    return derive_power_branch_transform_seed(latent_seed, branch_id)


class _HashCounterRng:
    """Small deterministic SHA-256 counter PRNG with Box-Muller normal draws."""

    def __init__(self, seed: int) -> None:
        self._seed = seed.to_bytes(8, "big", signed=False)
        self._counter = 0
        self._spare_normal: float | None = None

    def uniform(self) -> float:
        counter = self._counter.to_bytes(16, "big", signed=False)
        self._counter += 1
        integer = int.from_bytes(hashlib.sha256(self._seed + counter).digest()[:8], "big")
        return (integer + 0.5) / 2**64

    def normal(self) -> float:
        if self._spare_normal is not None:
            value = self._spare_normal
            self._spare_normal = None
            return value
        first = max(self.uniform(), 2**-64)
        second = self.uniform()
        radius = math.sqrt(-2.0 * math.log(first))
        angle = 2.0 * math.pi * second
        self._spare_normal = radius * math.sin(angle)
        return radius * math.cos(angle)


def _draw_categorical(
    rng: _HashCounterRng, levels: Sequence[str], probabilities: Sequence[float]
) -> str:
    if len(levels) != len(probabilities) or not levels:
        raise ValueError("categorical DGP levels/probabilities drift")
    if not math.isclose(sum(probabilities), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("categorical DGP probabilities must sum to one")
    draw = rng.uniform()
    cumulative = 0.0
    for level, probability in zip(levels, probabilities, strict=True):
        cumulative += probability
        if draw <= cumulative:
            return level
    return levels[-1]


def _draw_latent_value(
    variable: dict[str, Any], rng: _HashCounterRng, scope_index: int
) -> float | str:
    distribution = variable["distribution"]
    if distribution in {
        "STANDARD_NORMAL",
        "FIXTURE_SYMMETRIC_STANDARD_NORMAL_ORDER_STATISTICS",
        "PAIRED_OPPOSITE_STANDARD_NORMAL",
    }:
        return rng.normal()
    if distribution == "BERNOULLI":
        return float(rng.uniform() <= float(variable["prevalence"]))
    if distribution == "CATEGORICAL":
        return _draw_categorical(rng, variable["levels"], variable["probabilities"])
    if distribution == "BALANCED_CATEGORICAL":
        levels = variable["levels"]
        block_size = int(variable["block_size"])
        return str(levels[(scope_index // block_size) % len(levels)])
    if distribution == "ALTERNATING_BINARY":
        return float(scope_index % 2)
    if distribution == "HOME_AWAY_BINARY":
        return float(scope_index % 2 == 0)
    raise ValueError("unsupported latent-variable distribution")


def _generate_latent_values(
    matrix_contract: dict[str, Any],
    rng: _HashCounterRng,
    scope_index: int,
    scope: str,
) -> dict[str, float | str]:
    return {
        variable["name"]: _draw_latent_value(variable, rng, scope_index)
        for variable in matrix_contract["latent_variables"]
        if variable["scope"] == scope
    }


def _generate_within_fixture_values(
    matrix_contract: dict[str, Any],
    rng: _HashCounterRng,
    within_fixture_index: int,
    cache: dict[tuple[str, int], float | str],
) -> dict[str, float | str]:
    values: dict[str, float | str] = {}
    rows_per_fixture = int(matrix_contract["observation_expansion"]["rows_per_fixture"])
    for variable in matrix_contract["latent_variables"]:
        if variable["scope"] != "WITHIN_FIXTURE":
            continue
        repeat_rows = int(variable["repeat_rows"])
        if rows_per_fixture % repeat_rows:
            raise ValueError("within-fixture latent repeat does not divide fixture rows")
        group_index = within_fixture_index // repeat_rows
        cache_key = (variable["name"], group_index)
        if variable["distribution"] == "PAIRED_OPPOSITE_STANDARD_NORMAL":
            if group_index not in {0, 1}:
                raise ValueError("paired-opposite latent requires exactly two groups")
            base_key = (variable["name"], 0)
            if base_key not in cache:
                cache[base_key] = rng.normal()
            values[variable["name"]] = (
                cache[base_key]
                if group_index == 0
                else -float(cache[base_key])
            )
            continue
        if cache_key not in cache:
            cache[cache_key] = _draw_latent_value(variable, rng, group_index)
        values[variable["name"]] = cache[cache_key]
    return values


def _center_fixture_latents(
    matrix_contract: dict[str, Any], latent_rows: list[dict[str, float | str]]
) -> None:
    for variable in matrix_contract["latent_variables"]:
        if (
            variable["distribution"]
            != "FIXTURE_SYMMETRIC_STANDARD_NORMAL_ORDER_STATISTICS"
        ):
            continue
        if variable.get("normalization") != FIXTURE_SYMMETRIC_NORMALIZATION:
            raise ValueError("symmetric bookmaker normalization contract drift")
        name = variable["name"]
        if len(latent_rows) != 5:
            raise ValueError("symmetric bookmaker deviation requires exactly five books")
        raw_values = [float(row[name]) for row in latent_rows]
        ordered_positions = sorted(range(5), key=raw_values.__getitem__)
        ordered_values = [raw_values[position] for position in ordered_positions]
        center = ordered_values[2]
        inner_magnitude = (
            abs(ordered_values[1] - center) + abs(ordered_values[3] - center)
        ) / 2
        outer_magnitude = max(
            inner_magnitude,
            (
                abs(ordered_values[0] - center)
                + abs(ordered_values[4] - center)
            )
            / 2,
        )
        symmetric_values = [
            -outer_magnitude,
            -inner_magnitude,
            0.0,
            inner_magnitude,
            outer_magnitude,
        ]
        root_mean_square = math.sqrt(
            sum(value * value for value in symmetric_values) / len(symmetric_values)
        )
        if root_mean_square < 1e-12:
            raise ValueError("symmetric bookmaker deviation has zero variance")
        symmetric_values = [value / root_mean_square for value in symmetric_values]
        for position, value in zip(
            ordered_positions, symmetric_values, strict=True
        ):
            latent_rows[position][name] = value


def _apply_power_outcome_postprocessing(
    design: dict[str, Any],
    outcomes: Sequence[float],
    cluster_ids: Sequence[int],
    stage: str,
) -> list[float]:
    contract = design["data_generating_process"]["outcome_postprocessing"]
    rule_key = {
        "COMMON_GENERATION": "common_outcome_rule",
        "BRANCH_TRANSFORM": "branch_outcome_rule",
    }.get(stage)
    if rule_key is None:
        raise ValueError("unsupported power outcome postprocessing stage")
    rule = contract[rule_key]
    transformed = [float(value) for value in outcomes]
    if rule == "NONE":
        return transformed
    if rule != "FIXTURE_MEDIAN_ZERO":
        raise ValueError("unsupported power outcome postprocessing rule")
    positions_by_cluster: dict[int, list[int]] = {}
    for position, cluster_id in enumerate(cluster_ids):
        positions_by_cluster.setdefault(cluster_id, []).append(position)
    for positions in positions_by_cluster.values():
        center = statistics.median(transformed[position] for position in positions)
        for position in positions:
            transformed[position] -= center
    return transformed


def _evaluate_matrix_expression(
    expression: dict[str, Any], latent_values: dict[str, float | str]
) -> float:
    operator = expression["operator"]
    if operator == "CONSTANT":
        return float(expression["value"])
    if operator == "IDENTITY":
        return float(latent_values[expression["variable"]])
    if operator == "LEVEL_IS":
        return float(latent_values[expression["variable"]] == expression["level"])
    if operator == "LEVEL_IN":
        return float(latent_values[expression["variable"]] in expression["levels"])
    if operator == "HINGE":
        value = float(latent_values[expression["variable"]])
        return max(value - float(expression["knot"]), 0.0)
    if operator == "PRODUCT":
        return math.prod(float(latent_values[name]) for name in expression["variables"])
    raise ValueError("unsupported design-matrix expression")


def generate_power_sample(
    design: dict[str, Any],
    eligible_units: int,
    alternative: float,
    latent_seed: int,
) -> tuple[list[list[float]], list[float], list[int]]:
    """Generate one complete common-latent synthetic sample from the frozen matrix DGP."""

    matrix_contract = design["data_generating_process"]["design_matrix"]
    column_count = len(matrix_contract["columns"])
    if eligible_units <= column_count + 2:
        raise ValueError("power smoke sample is too small for the frozen design matrix")
    contrast = matrix_contract["primary_contrast"]
    weights = [float(value) for value in contrast["weights"]]
    target_parameter = alternative + float(contrast["null_value"])
    squared_norm = sum(weight * weight for weight in weights)
    if squared_norm <= 0:
        raise ValueError("power contrast vector is empty")
    coefficients = [target_parameter * weight / squared_norm for weight in weights]
    for index, weight in enumerate(weights):
        if weight == 0 and matrix_contract["columns"][index]["name"] != "intercept":
            coefficients[index] = (0.05, -0.05, 0.10)[index % 3]

    rng = _HashCounterRng(latent_seed)
    cluster_size = int(
        design["data_generating_process"]["cluster_process"]["mean_cluster_size"]
    )
    expansion_cluster_size = int(matrix_contract["observation_expansion"]["rows_per_fixture"])
    if cluster_size != expansion_cluster_size:
        raise ValueError("fixture expansion and cluster-process sizes disagree")
    if eligible_units % cluster_size:
        raise ValueError("eligible units must contain complete fixture clusters")
    random_intercept_sd = math.sqrt(
        float(
            design["data_generating_process"]["cluster_process"][
                "random_intercept_variance"
            ]
        )
    )
    error_sd = math.sqrt(
        float(
            design["data_generating_process"]["cluster_process"][
                "idiosyncratic_error_variance"
            ]
        )
    )
    rows: list[list[float]] = []
    outcomes: list[float] = []
    cluster_ids: list[int] = []
    fixture_count = eligible_units // cluster_size
    for cluster_id in range(fixture_count):
        cluster_intercept = random_intercept_sd * rng.normal()
        fixture_values = _generate_latent_values(
            matrix_contract, rng, cluster_id, "FIXTURE"
        )
        within_fixture_cache: dict[tuple[str, int], float | str] = {}
        latent_rows = [
            {
                **fixture_values,
                **_generate_within_fixture_values(
                    matrix_contract,
                    rng,
                    within_fixture_index,
                    within_fixture_cache,
                ),
            }
            for within_fixture_index in range(cluster_size)
        ]
        _center_fixture_latents(matrix_contract, latent_rows)
        for latent_values in latent_rows:
            row = [
                _evaluate_matrix_expression(column["expression"], latent_values)
                for column in matrix_contract["columns"]
            ]
            mean = sum(
                value * coefficient
                for value, coefficient in zip(row, coefficients, strict=True)
            )
            rows.append(row)
            outcomes.append(mean + cluster_intercept + error_sd * rng.normal())
            cluster_ids.append(cluster_id)
    outcomes = _apply_power_outcome_postprocessing(
        design, outcomes, cluster_ids, "COMMON_GENERATION"
    )
    return rows, outcomes, cluster_ids


def _invert_matrix(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    size = len(matrix)
    augmented = [
        [*map(float, row), *[float(index == column) for column in range(size)]]
        for index, row in enumerate(matrix)
    ]
    for pivot_index in range(size):
        pivot_row = max(
            range(pivot_index, size),
            key=lambda row_index: abs(augmented[row_index][pivot_index]),
        )
        if abs(augmented[pivot_row][pivot_index]) < 1e-10:
            raise ValueError("power design matrix is rank deficient")
        augmented[pivot_index], augmented[pivot_row] = (
            augmented[pivot_row],
            augmented[pivot_index],
        )
        pivot = augmented[pivot_index][pivot_index]
        augmented[pivot_index] = [value / pivot for value in augmented[pivot_index]]
        for row_index in range(size):
            if row_index == pivot_index:
                continue
            factor = augmented[row_index][pivot_index]
            augmented[row_index] = [
                value - factor * pivot_value
                for value, pivot_value in zip(
                    augmented[row_index], augmented[pivot_index], strict=True
                )
            ]
    return [row[size:] for row in augmented]


def _matrix_multiply(
    left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]
) -> list[list[float]]:
    right_columns = list(zip(*right, strict=True))
    return [
        [sum(a * b for a, b in zip(row, column, strict=True)) for column in right_columns]
        for row in left
    ]


def transform_power_branch_outcomes(
    design: dict[str, Any],
    sample: tuple[list[list[float]], list[float], list[int]],
    branch_transform_seed: int,
) -> list[float]:
    """Apply branch-only measurement noise and the frozen response construction."""

    _, common_outcomes, cluster_ids = sample
    branch_rng = _HashCounterRng(branch_transform_seed)
    noise_sd = float(
        design["data_generating_process"]["branch_transform"][
            "standardized_measurement_noise_sd"
        ]
    )
    noisy_outcomes = [
        value + noise_sd * branch_rng.normal() for value in common_outcomes
    ]
    return _apply_power_outcome_postprocessing(
        design, noisy_outcomes, cluster_ids, "BRANCH_TRANSFORM"
    )


def fit_power_branch(
    design: dict[str, Any],
    sample: tuple[list[list[float]], list[float], list[int]],
    branch_id: str,
    branch_transform_seed: int,
) -> dict[str, float | str]:
    """Fit the frozen OLS contrast with a fixture-cluster sandwich covariance."""

    rows, _, cluster_ids = sample
    outcomes = transform_power_branch_outcomes(
        design, sample, branch_transform_seed
    )
    row_count = len(rows)
    column_count = len(rows[0])
    xtx = [[0.0 for _ in range(column_count)] for _ in range(column_count)]
    xty = [0.0 for _ in range(column_count)]
    for row, outcome in zip(rows, outcomes, strict=True):
        for left_index, left_value in enumerate(row):
            xty[left_index] += left_value * outcome
            for right_index, right_value in enumerate(row):
                xtx[left_index][right_index] += left_value * right_value
    bread = _invert_matrix(xtx)
    coefficients = [
        sum(value * response for value, response in zip(row, xty, strict=True))
        for row in bread
    ]
    residuals = [
        outcome - sum(value * coefficient for value, coefficient in zip(row, coefficients, strict=True))
        for row, outcome in zip(rows, outcomes, strict=True)
    ]
    cluster_scores: dict[int, list[float]] = {}
    for row, residual, cluster_id in zip(rows, residuals, cluster_ids, strict=True):
        score = cluster_scores.setdefault(cluster_id, [0.0] * column_count)
        for index, value in enumerate(row):
            score[index] += value * residual
    meat = [[0.0 for _ in range(column_count)] for _ in range(column_count)]
    for score in cluster_scores.values():
        for left_index, left_value in enumerate(score):
            for right_index, right_value in enumerate(score):
                meat[left_index][right_index] += left_value * right_value
    covariance = _matrix_multiply(_matrix_multiply(bread, meat), bread)
    cluster_count = len(cluster_scores)
    correction = (cluster_count / (cluster_count - 1)) * (
        (row_count - 1) / (row_count - column_count)
    )
    covariance = [[value * correction for value in row] for row in covariance]
    contrast = design["data_generating_process"]["design_matrix"]["primary_contrast"]
    weights = [float(value) for value in contrast["weights"]]
    estimate = (
        sum(weight * coefficient for weight, coefficient in zip(weights, coefficients, strict=True))
        - float(contrast["null_value"])
    )
    variance = sum(
        weights[left_index] * covariance[left_index][right_index] * weights[right_index]
        for left_index in range(column_count)
        for right_index in range(column_count)
    )
    standard_error = math.sqrt(max(variance, 1e-15))
    z_score = estimate / standard_error
    p_value = math.erfc(abs(z_score) / math.sqrt(2.0))
    critical = 1.959963984540054
    return {
        "branch_id": branch_id,
        "p_value": p_value,
        "ci95_lower_bound": estimate - critical * standard_error,
        "ci95_upper_bound": estimate + critical * standard_error,
    }


def evaluate_power_replicate(
    design: dict[str, Any],
    branch_results: Sequence[dict[str, float | str]],
    family_null_p_values: Sequence[float],
    global_null_p_values: Sequence[float],
) -> bool:
    """Apply the frozen branch, BH and interval-support rule to one synthetic replicate."""

    decision = design["decision_algorithm"]
    branch_ids = decision["branch_ids"]
    if [row["branch_id"] for row in branch_results] != branch_ids:
        raise ValueError("power replicate branch order drift")
    family_test_count = int(decision["family_primary_test_count"])
    global_test_count = int(decision["global_primary_test_count"])
    if len(family_null_p_values) != family_test_count - len(branch_results):
        raise ValueError("family null companion count drift")
    if len(global_null_p_values) != global_test_count - family_test_count:
        raise ValueError("global null companion count drift")
    focal_p_values = [float(row["p_value"]) for row in branch_results]
    family_p_values = [*focal_p_values, *family_null_p_values]
    global_p_values = [*family_p_values, *global_null_p_values]
    family_q_values = benjamini_hochberg_q_values(family_p_values)
    global_q_values = benjamini_hochberg_q_values(global_p_values)
    contract = design["test_mapping"]["classification_contract"]
    classifications = []
    for index, row in enumerate(branch_results):
        reported_q = max(family_q_values[index], global_q_values[index])
        classifications.append(
            classify_interval(
                contract,
                float(row["ci95_lower_bound"]),
                float(row["ci95_upper_bound"]),
                reported_q,
            )
        )
    return all(value == "SUPPORTED" for value in classifications)


def run_power_replicate(
    design: dict[str, Any],
    eligible_units: int,
    alternative: float,
    replicate_index: int,
) -> bool:
    """Generate, fit and decide one complete synthetic nonaggregated replicate."""

    latent_seed = derive_power_latent_seed(
        int(design["master_seed"]), eligible_units, replicate_index
    )
    sample = generate_power_sample(design, eligible_units, alternative, latent_seed)
    decision = design["decision_algorithm"]
    branch_results = [
        fit_power_branch(
            design,
            sample,
            branch_id,
            derive_power_branch_transform_seed(latent_seed, branch_id),
        )
        for branch_id in decision["branch_ids"]
    ]
    family_null_count = int(decision["family_primary_test_count"]) - len(
        branch_results
    )
    global_null_count = int(decision["global_primary_test_count"]) - int(
        decision["family_primary_test_count"]
    )
    family_rng = _HashCounterRng(_seed_from_parts("FAMILY_NULLS", latent_seed))
    global_rng = _HashCounterRng(_seed_from_parts("GLOBAL_NULLS", latent_seed))
    return evaluate_power_replicate(
        design,
        branch_results,
        [family_rng.uniform() for _ in range(family_null_count)],
        [global_rng.uniform() for _ in range(global_null_count)],
    )


def run_power_simulation(
    design: dict[str, Any],
    eligible_units: int,
    alternative: float,
    replicate_count: int,
) -> dict[str, float | int]:
    """Run the frozen design-only simulation; this function never reads sporting data."""

    if replicate_count <= 0:
        raise ValueError("power simulation requires at least one replicate")
    successes = sum(
        run_power_replicate(design, eligible_units, alternative, replicate_index)
        for replicate_index in range(replicate_count)
    )
    return {
        "eligible_units": eligible_units,
        "alternative": alternative,
        "successes": successes,
        "replicates": replicate_count,
        "estimated_power": successes / replicate_count,
        "wilson_lower_bound_95": wilson_lower_bound(successes, replicate_count),
    }


def _minimum_sample_contract(family: FamilySpec) -> dict[str, Any]:
    independent_base_n = math.ceil(
        2 * (1.959963984540054 + 0.8416212335729143) ** 2 / family.minimum_effect_size**2
    )
    intraclass_correlation = 0.05
    mean_cluster_size = 4
    design_effect = 1 + (mean_cluster_size - 1) * intraclass_correlation
    holdout_multiplier = 1 / (1 - 0.20)
    multiplicity_multiplier = 1.15
    adversarial_slice_multiplier = 1.25
    inflated_n = math.ceil(
        independent_base_n
        * design_effect
        * holdout_multiplier
        * multiplicity_multiplier
        * adversarial_slice_multiplier
    )
    return {
        "eligible_units": max(family.minimum_sample, inflated_n),
        "sample_status": "CONSERVATIVE_PLANNING_FLOOR_NOT_A_POWER_DEMONSTRATION",
        "family_floor_before_recalculation": family.minimum_sample,
        "independent_base_n": independent_base_n,
        "inflated_planning_n": inflated_n,
        "reference_normal_approximation_power": 0.80,
        "reference_power_is_demonstrated": False,
        "model_specific_power_required_before_execution": True,
        "model_specific_power_acceptance_gate": (
            "deterministic design simulation at the frozen scalar MDE must estimate power >=0.80; "
            "otherwise increase eligible_units and freeze a new protocol version"
        ),
        "sample_size_may_only_increase_after_design_simulation": True,
        "two_sided_alpha_before_fdr": 0.05,
        "standardized_outcome_variance": 1.0,
        "intraclass_correlation": intraclass_correlation,
        "mean_cluster_size": mean_cluster_size,
        "design_effect": design_effect,
        "holdout_fraction": 0.20,
        "holdout_multiplier": holdout_multiplier,
        "multiplicity_multiplier": multiplicity_multiplier,
        "adversarial_slice_multiplier": adversarial_slice_multiplier,
        "cluster_unit": "fixture",
        "base_formula": "2*(z_0.975+z_0.80)^2/standardized_effect^2",
        "inflation_formula": (
            "ceil(base_n * (1+(mean_cluster_size-1)*ICC) * 1/(1-holdout) "
            "* multiplicity_multiplier * adversarial_slice_multiplier)"
        ),
        "sizing_basis": (
            "conservative standardized-effect planning floor only; no observed sporting result "
            "and no claim of attained model-specific power"
        ),
        "pilot_recalculation_rule": (
            "A separately authorized E1 may increase n from frozen prevalence/variance/ICC inputs; "
            "it may not lower the MDE or inspect a holdout."
        ),
    }


def _catalogue_operational_definition(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    return {
        "state": "CATALOGUE_CORE_FROZEN_PORTFOLIO_PARAMETERS_NOT_ASSIGNED",
        "semantic_feature_projection": {
            "base_features": copy.deepcopy(item.estimand_projection["base_features"]),
            "moderators": copy.deepcopy(item.estimand_projection["moderators"]),
            "semantic_discriminator": copy.deepcopy(
                item.estimand_projection.get("semantic_discriminator")
            ),
        },
        "required_variables": sorted(set(family.base_variables + item.extra_variables)),
        "execution_gate": (
            "NOT_EXECUTABLE until a versioned protocol variant freezes cutpoints, windows, model "
            "formula and boundary equality without inspecting results."
        ),
    }


def _build_hypothesis(family: FamilySpec, item: IdeaSpec) -> dict[str, Any]:
    semantic_core = _semantic_core(family, item)
    semantic_hash = sha256_json(semantic_core)
    estimand_hash = semantic_core["estimand_hash"]
    devig_protocol = _devig_protocol(family, item)
    falsification_contract = _falsification_contract(family, item)
    operational_definition = _catalogue_operational_definition(family, item)
    predictor_cutoff = _predictor_cutoff_for(item.concept_key)
    protocol_variant = {
        "semantic_core_hash": semantic_hash,
        "devig_protocol": devig_protocol,
        "falsification_contract": falsification_contract,
        "operational_definition": operational_definition,
        "minimum_effect_size": family.minimum_effect_size,
        "minimum_sample": _minimum_sample_contract(family),
        "cutoff": predictor_cutoff["cutoff_id"],
        "correction": "BH_FAMILY_AND_GLOBAL_MAX_Q_0_05",
        "protocol_version": "HYPOTHESIS_PROTOCOL_V1",
    }
    blocked = item.observability_status == "DATA_NOT_PROSPECTIVELY_OBSERVABLE"
    post_cutoff_target = POST_CUTOFF_TARGETS.get(item.concept_key)
    scores = _score(family, item)
    return {
        "hypothesis_id": f"RDS-HYP-V1-{semantic_hash[:16].upper()}",
        "estimand_hash": estimand_hash,
        "estimand_signature": _estimand_signature(family, item),
        "assertion_hash": semantic_hash,
        "semantic_core_hash": semantic_hash,
        "protocol_variant_hash": sha256_json(protocol_variant),
        "concept_key": item.concept_key,
        "title": item.title,
        "intuition": item.claim,
        "assumed_causal_mechanism": family.assumed_mechanism,
        "market": list(_markets_for(family, item)),
        "population": family.population,
        "unit_of_analysis": family.unit_of_analysis,
        "required_variables": sorted(set(family.base_variables + item.extra_variables)),
        "required_data": list(_all_datasets_for(family, item)),
        "temporal_cutoff": {
            "cutoff_id": predictor_cutoff["cutoff_id"],
            "cutoff_at_rule": predictor_cutoff["rule"],
            "predictor_inputs_rule": PIT_PREDICTOR_ADMISSIBILITY,
            "post_cutoff_target_rule": (
                PIT_TARGET_ADMISSIBILITY if post_cutoff_target else None
            ),
            "label_rule": PIT_LABEL_ADMISSIBILITY,
        },
        "devig_protocol": devig_protocol,
        "truth_kernel_version": TRUTH_KERNEL_VERSION,
        "eligibility_condition": [
            family.population,
            "all predictor receipts resolve to immutable payload bytes",
            "all predictor dependencies satisfy available_at <= cutoff_at",
            "labels are excluded from eligibility/features and require post-event settlement receipts",
            "all named markets are complete and labels are unique",
            "no current-fixture outcome-derived covariate is present",
            (
                "data gate remains closed until a source contract exists"
                if blocked
                else "prospective snapshot is content-addressed before execution"
            ),
        ],
        "null_hypothesis": (
            f"The preregistered coefficient for {item.concept_key} equals zero after declared "
            "covariates and cluster structure."
        ),
        "expected_effect": {
            "direction": item.expected_direction,
            "minimum_relevant_standardized_effect": family.minimum_effect_size,
            "historical_result_used": False,
        },
        "primary_metric": (
            post_cutoff_target["primary_metric"]
            if post_cutoff_target
            else family.primary_metric
        ),
        "secondary_metrics": (
            [family.primary_metric, *family.secondary_metrics]
            if post_cutoff_target
            else list(family.secondary_metrics)
        ),
        "minimum_sample_size": _minimum_sample_contract(family),
        "multiplicity_family": family.family_id,
        "statistical_correction": {
            "within_family": "BENJAMINI_HOCHBERG_FDR",
            "global_campaign": "BENJAMINI_HOCHBERG_FDR",
            "reported_q_value": "max(family_q, global_q)",
            "target_q": 0.05,
            "blocked_test_p_value": 1.0,
        },
        "holdout": {
            "type": "CONTIGUOUS_TEMPORAL",
            "rule": "final 20% of eligible event_at within each league-season",
            "sealed_before_fit": True,
        },
        "walk_forward": {
            "type": "EXPANDING_WINDOW",
            "rule": "fit on prior periods, score the next sealed quarter-season, never refit inside a scored block",
        },
        "league_holdout": {
            "rule": "leave one declared league out; report each league separately",
            "aggregation_for_decision": "FORBIDDEN",
        },
        "season_holdout": {
            "rule": "latest fully receipt-backed season remains sealed until all choices are frozen",
            "reuse_after_inspection": "FORBIDDEN",
        },
        "adversarial_slices": list(family.adversarial_slices),
        "falsification_contract": falsification_contract,
        "falsification_criterion": falsification_contract["falsified_inequality"],
        "abandonment_criterion": (
            "Stop when receipt coverage is below 80%, a future-mutation invariant fails, two "
            "independent protocol redesigns fail for the same reason, or the required source is "
            "not prospectively observable."
        ),
        "compute_cost": {
            "class": family.compute_cost,
            "estimated_cpu_hours": family.estimated_cpu_hours,
            "bounded_first_stage": "E1: 10 fixtures, one league-season, maximum 5 minutes",
        },
        "data_dependencies": _data_dependencies(family, item),
        "point_in_time": _point_in_time_contract(family, item),
        "operational_definition": operational_definition,
        "topic_tags": list(item.topic_tags),
        "prior_art_refs": [
            "docs/registre_hypotheses_v1.yaml",
            "reports/hypothesis-genome/hypothesis-universe-summary.json",
            *item.prior_art_refs,
        ],
        "prior_art_usage": "IDENTITY_AND_SCOPE_ONLY_NO_RESULT_IMPORT",
        "portfolio_stratum_id": None,
        "portfolio_order": None,
        "first_portfolio_candidate": False,
        "priority_score_preview": {
            "components": scores,
            "total": sum(scores.values()),
            "rationale_codes": _score_rationale_codes(family, item),
            "historical_roi_used": False,
        },
        "status": {
            "lifecycle_status": "DATA_GATE_BLOCKED" if blocked else "DISCOVERED",
            "scientific_status": "NOT_TESTED",
            "research_status": "EXPLORATORY",
            "validation_status": "UNVALIDATED",
            "promotion_status": "NO_PROMOTION",
            "betting_status": "NO_BET",
            "status_reason": item.observability_reason,
        },
    }


def _build_hypotheses(
    source_records: Sequence[tuple[FamilySpec, IdeaSpec]],
) -> list[dict[str, Any]]:
    base_groups: dict[str, list[tuple[FamilySpec, IdeaSpec]]] = {}
    for family, item in source_records:
        base_hash = sha256_json(_base_estimand_signature(family, item))
        base_groups.setdefault(base_hash, []).append((family, item))
    for grouped_records in base_groups.values():
        if len(grouped_records) == 1:
            if "semantic_discriminator" in grouped_records[0][1].estimand_projection:
                raise ValueError("singleton estimand cannot carry a semantic discriminator")
            continue
        for _, item in grouped_records:
            discriminator = item.estimand_projection.get("semantic_discriminator")
            if discriminator is None:
                members = ",".join(sorted(row.concept_key for _, row in grouped_records))
                raise ValueError(f"semantic collision requires discriminators: {members}")
            _validate_semantic_discriminator(discriminator)

    records_by_estimand: dict[str, list[tuple[FamilySpec, IdeaSpec]]] = {}
    for family, item in source_records:
        estimand_hash = sha256_json(_estimand_signature(family, item))
        records_by_estimand.setdefault(estimand_hash, []).append((family, item))
    record_by_estimand: dict[str, tuple[FamilySpec, IdeaSpec]] = {}
    for estimand_hash, grouped_records in records_by_estimand.items():
        assertions = {
            (item.expected_direction, item.claim_type, item.orientation)
            for _, item in grouped_records
        }
        families = {family.family_id for family, _ in grouped_records}
        if len(assertions) != 1 or len(families) != 1:
            raise ValueError("contradictory or cross-family duplicate estimand")
        record_by_estimand[estimand_hash] = sorted(
            grouped_records, key=lambda value: value[1].concept_key
        )[0]
    raw_estimands = {
        sha256_json(candidate["structured_projection"]) for candidate in RAW_CANDIDATES
    }
    if set(record_by_estimand) != raw_estimands:
        raise ValueError("raw candidate clusters do not resolve exactly to catalogue detail records")
    if not 80 <= len(record_by_estimand) <= 150:
        raise ValueError("semantic clustering must retain 80..150 distinct estimands")

    hypotheses = [
        _build_hypothesis(*record_by_estimand[estimand_hash])
        for estimand_hash in sorted(raw_estimands)
    ]
    _apply_portfolio_selection(hypotheses)
    hypotheses.sort(key=lambda value: value["hypothesis_id"])
    for ordinal, hypothesis in enumerate(hypotheses, start=1):
        hypothesis["catalogue_ordinal"] = ordinal
    return hypotheses


def _protocol_variant_payload(hypothesis: dict[str, Any]) -> dict[str, Any]:
    return {
        "semantic_core_hash": hypothesis["semantic_core_hash"],
        "devig_protocol": hypothesis["devig_protocol"],
        "falsification_contract": hypothesis["falsification_contract"],
        "operational_definition": hypothesis["operational_definition"],
        "minimum_effect_size": hypothesis["expected_effect"][
            "minimum_relevant_standardized_effect"
        ],
        "minimum_sample": hypothesis["minimum_sample_size"],
        "cutoff": hypothesis["temporal_cutoff"]["cutoff_id"],
        "correction": "BH_FAMILY_AND_GLOBAL_MAX_Q_0_05",
        "protocol_version": "HYPOTHESIS_PROTOCOL_V1",
    }


def _portfolio_ranking_key(hypothesis: dict[str, Any]) -> tuple[Any, ...]:
    components = hypothesis["priority_score_preview"]["components"]
    return (
        hypothesis["status"]["lifecycle_status"] == "DATA_GATE_BLOCKED",
        -hypothesis["priority_score_preview"]["total"],
        -components["point_in_time_provability"],
        -components["falsifiability"],
        -components["statistical_power"],
        hypothesis["compute_cost"]["estimated_cpu_hours"],
        hypothesis["estimand_hash"],
    )


def _apply_portfolio_selection(hypotheses: list[dict[str, Any]]) -> None:
    selected_ids: set[str] = set()
    for stratum in PORTFOLIO_STRATA:
        required_tags = set(stratum["required_topic_tags"])
        eligible = [
            hypothesis
            for hypothesis in hypotheses
            if hypothesis["hypothesis_id"] not in selected_ids
            and hypothesis["multiplicity_family"] == stratum["family_id"]
            and hypothesis["expected_effect"]["direction"]
            == stratum["required_expected_direction"]
            and required_tags.issubset(hypothesis["topic_tags"])
        ]
        if not eligible:
            raise ValueError(f"portfolio stratum has no eligible hypothesis: {stratum['stratum_id']}")
        chosen = sorted(eligible, key=_portfolio_ranking_key)[0]
        blocked = chosen["status"]["lifecycle_status"] == "DATA_GATE_BLOCKED"
        if blocked and not stratum["blocked_fallback_allowed"]:
            raise ValueError(f"portfolio stratum only resolves to blocked data: {stratum['stratum_id']}")
        chosen["first_portfolio_candidate"] = True
        chosen["portfolio_stratum_id"] = stratum["stratum_id"]
        chosen["portfolio_order"] = stratum["portfolio_order"]
        chosen["operational_definition"] = {
            "state": "PORTFOLIO_PROTOCOL_OPERATIONALLY_FROZEN",
            "common_rules": copy.deepcopy(PORTFOLIO_COMMON_RULES),
            **copy.deepcopy(stratum["operational_definition"]),
        }
        chosen["portfolio_selection_evidence"] = {
            "stratum_id": stratum["stratum_id"],
            "required_topic_tags": sorted(required_tags),
            "required_expected_direction": stratum["required_expected_direction"],
            "ranking_key": list(_portfolio_ranking_key(chosen)),
            "eligible_candidate_count": len(eligible),
            "blocked_fallback": blocked,
            "legacy_priority_flag_used": False,
            "historical_roi_used": False,
        }
        selected_ids.add(chosen["hypothesis_id"])

    if len(selected_ids) != 25:
        raise ValueError("portfolio selection must resolve exactly 25 strata")
    for hypothesis in hypotheses:
        if not hypothesis["first_portfolio_candidate"]:
            hypothesis["portfolio_selection_evidence"] = None
        hypothesis["protocol_variant_hash"] = sha256_json(
            _protocol_variant_payload(hypothesis)
        )


def _build_deduplication(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    hypothesis_by_estimand = {hypothesis["estimand_hash"]: hypothesis for hypothesis in hypotheses}
    raw_groups: dict[str, list[dict[str, Any]]] = {}
    for raw_candidate in RAW_CANDIDATES:
        estimand_hash = sha256_json(raw_candidate["structured_projection"])
        raw_groups.setdefault(estimand_hash, []).append(raw_candidate)

    candidates: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    lens_order = {
        "MECHANISM_FORMULATION": 0,
        "OBSERVABLE_ESTIMAND_FORMULATION": 1,
        "FALSIFICATION_FORMULATION": 2,
    }
    for estimand_hash, raw_group in sorted(raw_groups.items()):
        hypothesis = hypothesis_by_estimand[estimand_hash]
        ordered_group = sorted(
            raw_group,
            key=lambda row: (lens_order[row["generation_lens"]], row["candidate_id"]),
        )
        representative_id = ordered_group[0]["candidate_id"]
        candidate_ids = []
        for raw_candidate in ordered_group:
            candidate_ids.append(raw_candidate["candidate_id"])
            is_representative = raw_candidate["candidate_id"] == representative_id
            candidates.append(
                {
                    "candidate_id": raw_candidate["candidate_id"],
                    "seed_question_hash": raw_candidate["seed_question_hash"],
                    "generation_lens": raw_candidate["generation_lens"],
                    "formulation": raw_candidate["formulation"],
                    "normalized_formulation": normalize_formulation(
                        raw_candidate["formulation"]
                    ),
                    "decision": (
                        "RETAINED_CLUSTER_REPRESENTATIVE"
                        if is_representative
                        else "MERGED_EQUIVALENT_FORMULATION"
                    ),
                    "reason": (
                        "FIRST_FROZEN_LENS_AFTER_ESTIMAND_CLUSTERING"
                        if is_representative
                        else "SAME_STRUCTURED_ESTIMAND_AND_ASSERTION"
                    ),
                    "canonical_hypothesis_id": hypothesis["hypothesis_id"],
                    "estimand_hash": estimand_hash,
                    "assertion_hash": hypothesis["assertion_hash"],
                    "semantic_core_hash": hypothesis["semantic_core_hash"],
                }
            )
        cluster_rows.append(
            {
                "estimand_hash": estimand_hash,
                "estimand_signature": copy.deepcopy(ordered_group[0]["structured_projection"]),
                "assertion_hashes": [hypothesis["assertion_hash"]],
                "canonical_hypothesis_id": hypothesis["hypothesis_id"],
                "representative_candidate_id": representative_id,
                "candidate_ids": sorted(candidate_ids),
                "candidate_count": len(candidate_ids),
                "seed_question_hashes": sorted(
                    {row["seed_question_hash"] for row in ordered_group}
                ),
                "generation_lenses": sorted(
                    {row["generation_lens"] for row in ordered_group}
                ),
                "adjudication": "SEMANTICALLY_EQUIVALENT_FORMULATIONS_ONE_FROZEN_ESTIMAND",
                "canonical_id_assigned_after_clustering": True,
            }
        )

    candidates.sort(key=lambda value: value["candidate_id"])
    cluster_rows.sort(key=lambda value: value["estimand_hash"])
    return {
        "schema_version": "robin-hypothesis-deduplication-v1",
        "report_id": "hypothesis-deduplication-v1",
        "generation_counts": {
            "candidate_formulations": len(candidates),
            "seeded_scientific_questions": 112,
            "retained_semantic_cores": len(hypotheses),
            "merged_equivalent_formulations": len(candidates) - len(hypotheses),
            "rejected_formulations": 0,
            "threshold_only_hypotheses_retained": 0,
        },
        "normalization": {
            "text": "Unicode NFKD, lowercase, punctuation removal, frozen synonym map",
            "cluster_key": (
                "ESTIMAND_SIGNATURE_V2: SHA-256 of market/population/unit, semantic feature tags, "
                "moderators, target and timing; structured transform/comparator AST only for true "
                "base-signature collisions"
            ),
            "excluded_from_cluster_key": [
                "candidate_id",
                "seed_question_hash",
                "formulation prose",
                "canonical hypothesis identity",
                "catalogue concept_key",
                "title and claim prose",
                "expected direction, claim type and orientation",
                "portfolio selection",
                "numeric protocol thresholds",
            ],
            "normalized_formulation_use": (
                "audit exact/trivial wording collisions; never override structured-estimand clustering"
            ),
        },
        "identity_policy": {
            "estimand_hash": "SHA-256 canonical JSON of observable structured projection",
            "assertion_hash": "SHA-256 of estimand hash plus frozen assertion semantics",
            "protocol_variant_hash": "SHA-256 canonical JSON including thresholds, cutoff and de-vig versions",
            "canonical_id_timing": "assigned only after raw clustering and assertion adjudication",
            "contradictory_duplicate_policy": "FAIL_CLOSED",
        },
        "candidates": candidates,
        "clusters": cluster_rows,
    }


def _build_family_map(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    families = []
    for family in FAMILIES:
        members = sorted(
            hypothesis["hypothesis_id"]
            for hypothesis in hypotheses
            if hypothesis["multiplicity_family"] == family.family_id
        )
        families.append(
            {
                "family_id": family.family_id,
                "label": family.label,
                "purpose": family.purpose,
                "hypothesis_count": len(members),
                "hypothesis_ids": members,
                "maximum_primary_tests": len(members) * 2,
                "branch_count_per_hypothesis": 2,
                "correction": {
                    "method": "BENJAMINI_HOCHBERG_FDR",
                    "target_q": 0.05,
                    "global_guard": "reported_q=max(family_q,global_q)",
                    "blocked_test_p_value": 1.0,
                },
                "protocol_freeze": (
                    "Freeze semantic core, sample rule, cutoff, branch definitions and exclusions "
                    "before materializing any analysis snapshot."
                ),
                "promotion_rule": "NO_PROMOTION_ALWAYS",
                "research_stage_rule": (
                    "Only a separately authorized immediate next research stage may be considered; "
                    "family reassignment after observation is forbidden."
                ),
            }
        )
    return {
        "schema_version": "robin-hypothesis-family-map-v1",
        "report_id": "hypothesis-family-map-v1",
        "family_assignment_rule": (
            "Assign the primary causal exposure to exactly one family; moderators remain slices "
            "unless their interaction is the estimand."
        ),
        "global_multiplicity": {
            "maximum_hypotheses": len(hypotheses),
            "maximum_primary_tests": len(hypotheses) * 2,
            "within_family_method": "BENJAMINI_HOCHBERG_FDR",
            "campaign_method": "BENJAMINI_HOCHBERG_FDR",
            "target_q": 0.05,
            "reported_q_value": "max(family_q,global_q)",
            "devig_branches_aggregated": False,
            "freeze_before_execution": True,
        },
        "families": families,
    }


def _build_scorecard(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for hypothesis in hypotheses:
        components = copy.deepcopy(hypothesis["priority_score_preview"]["components"])
        entries.append(
            {
                "hypothesis_id": hypothesis["hypothesis_id"],
                "multiplicity_family": hypothesis["multiplicity_family"],
                "components": components,
                "total": sum(components.values()),
                "rationale_codes": copy.deepcopy(
                    hypothesis["priority_score_preview"]["rationale_codes"]
                ),
                "selected_for_first_25": hypothesis["first_portfolio_candidate"],
                "selection_note": (
                    "Selected by frozen family quota, mechanism breadth, falsifiability and "
                    "prospective data plan; current data gates still apply."
                    if hypothesis["first_portfolio_candidate"]
                    else "Retained in the catalogue but outside the first frozen portfolio."
                ),
                "historical_roi_used": False,
            }
        )
    entries.sort(
        key=lambda value: (
            -value["total"],
            -value["components"]["point_in_time_provability"],
            -value["components"]["falsifiability"],
            value["hypothesis_id"],
        )
    )
    for rank, entry in enumerate(entries, start=1):
        entry["score_rank"] = rank
    return {
        "schema_version": "robin-hypothesis-priority-scorecard-v1",
        "report_id": "hypothesis-priority-scorecard-v1",
        "rubric": {
            criterion: {"maximum": maximum, "historical_roi_allowed": False}
            for criterion, maximum in SCORE_WEIGHTS.items()
        },
        "selection_policy": {
            "selected_count": sum(bool(entry["selected_for_first_25"]) for entry in entries),
            "family_quotas": {
                family.family_id: family.first_portfolio_quota for family in FAMILIES
            },
            "portfolio_source": "tools/hypothesis-lab/portfolio-strata-v1.json",
            "stratum_rule": "select exactly one operationally complete hypothesis per frozen stratum",
            "within_stratum_tie_break": (
                "nonblocked, total score, PIT, falsifiability, power, CPU cost, estimand hash"
            ),
            "scorecard_order": "total, PIT, falsifiability, hypothesis_id",
            "blocked_data_policy": (
                "A scientifically important blocked protocol may remain in the design portfolio, "
                "but cannot execute until its source contract is proven."
            ),
            "historical_roi_used": False,
        },
        "entries": entries,
    }


def _validate_score_rank_sequence(
    entries: Sequence[dict[str, Any]], hypothesis_count: int
) -> None:
    if [entry["score_rank"] for entry in entries] != list(
        range(1, hypothesis_count + 1)
    ):
        raise ValueError("score ranks are not contiguous")


def _status_object() -> dict[str, str]:
    return {
        "research_status": "EXPLORATORY",
        "validation_status": "UNVALIDATED",
        "promotion_status": "NO_PROMOTION",
        "betting_status": "NO_BET",
    }


def _build_negative_control_plan() -> dict[str, Any]:
    controls = []
    for control in NEGATIVE_CONTROLS:
        row = copy.deepcopy(control)
        row.update(
            {
                "execution_status": "NOT_RUN",
                "assignment_scope": (
                    "FACTORY_WIDE"
                    if row["control_id"] in {"RDS-NC-V1-005", "RDS-NC-V1-006", "RDS-NC-V1-008"}
                    else "EXPERIMENT_PROTOCOL"
                ),
                "frozen_alarm_rule": (
                    "ANY_SINGLE_GUARD_VIOLATION_STOPS_THE_FACTORY"
                    if row["control_type"] == "DETERMINISTIC_GUARD"
                    else "AT_LEAST_4_OF_20_SEEDED_REPLICATES_CROSS_Q_AND_EFFECT_FLOOR"
                ),
                "devig_rule": (
                    "When prices are involved, run PROPORTIONAL and SHIN 1X2 branches separately; "
                    "never aggregate."
                ),
                "point_in_time_rule": "The same H2 receipt and future-mutation guards apply.",
                "status": _status_object(),
            }
        )
        controls.append(row)
    return {
        "schema_version": "robin-negative-control-plan-v1",
        "report_id": "negative-control-plan-v1",
        "control_count": len(controls),
        "required_categories": [
            "PERMUTED_LABELS",
            "TEMPORALLY_SHIFTED_FEATURE",
            "MECHANISM_FREE_VARIABLE",
            "SYNTHETIC_CALIBRATED_NO_SIGNAL_MARKET",
        ],
        "controls": controls,
        "factory_stop_rules": [
            "Stop on any single violation emitted by a deterministic guard.",
            "Stop if at least 4 of 20 frozen seeded replicates of a stochastic control cross both q<=0.05 and the same effect floor.",
            "Investigate code, multiplicity and temporal lineage before any new substantive test.",
        ],
        "factory_wide_control_ids": ["RDS-NC-V1-005", "RDS-NC-V1-006", "RDS-NC-V1-008"],
        "execution_authority": "PLAN_ONLY_NOT_AUTHORIZED_TO_RUN",
    }


def _experiment_order(hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [hypothesis for hypothesis in hypotheses if hypothesis["first_portfolio_candidate"]]
    selected.sort(key=lambda hypothesis: hypothesis["portfolio_order"])
    return selected


def _control_ids_for_experiment(index: int, hypothesis: dict[str, Any]) -> list[str]:
    controls = {"RDS-NC-V1-001", "RDS-NC-V1-004", "RDS-NC-V1-009"}
    if hypothesis["multiplicity_family"] in {
        "FAMILY_MARKET_DYNAMICS",
        "FAMILY_SCHEDULE_FATIGUE",
        "FAMILY_TEAM_STATE_RANKING",
    }:
        controls.add("RDS-NC-V1-002")
    if index % 2 == 0:
        controls.add("RDS-NC-V1-003")
    if index % 5 == 0:
        controls.add("RDS-NC-V1-007")
    return sorted(controls)


def _power_simulator_definition() -> dict[str, Any]:
    return {
        "version": POWER_SIMULATOR_VERSION,
        "numeric_policy": "IEEE754_BINARY64_CANONICAL_JSON_NO_NAN",
        "supported_design_classes": [
            "AUTOREGRESSIVE_SLOPE_MONTE_CARLO",
            "CLUSTERED_LINEAR_SCALAR_CONTRAST_MONTE_CARLO",
            "FROZEN_SPLINE_SCALAR_CONTRAST_MONTE_CARLO",
            "LOG_VARIANCE_SCALAR_CONTRAST_MONTE_CARLO",
            "PAIRED_CLUSTERED_GAUSSIAN_MONTE_CARLO",
        ],
        "entrypoints": {
            "latent_seed": "derive_power_latent_seed",
            "branch_transform_seed": "derive_power_branch_transform_seed",
            "generate": "generate_power_sample",
            "branch_outcome_transform": "transform_power_branch_outcomes",
            "fit": "fit_power_branch",
            "replicate": "run_power_replicate",
            "simulation": "run_power_simulation",
            "multiplicity": "benjamini_hochberg_q_values",
            "branch_decision": "evaluate_power_replicate",
            "power_lower_bound": "wilson_lower_bound",
        },
        "algorithm_steps": [
            "for each candidate n and replicate derive one common latent-fixture seed",
            "draw fixture-scoped latents once, expand complete declared axis products with repeat-row caches, apply declared within-fixture centering and normalization, and reject partial fixtures",
            "inject each signed scalar alternative through the exact contrast vector",
            "derive separate branch-transform seeds, add branch noise, and reapply the declared outcome construction without redrawing fixtures",
            "fit OLS on the declared transformed response and exact matrix",
            "compute the fixture-cluster robust sandwich covariance and scalar contrast",
            "compute a two-sided Wald p-value and 95% interval per branch",
            "generate frozen independent uniform null companions for remaining family/global tests",
            "apply BH separately to family and global p-value vectors",
            "use max(family_q,global_q) and classify_interval for each branch",
            "count success only when every nonaggregated de-vig branch is SUPPORTED",
            "select the first n whose 95% Wilson lower bound is at least 0.80 for every alternative",
        ],
    }


def _power_matrix_contract(
    index: int, matrix_class: str, primary_parameter: str
) -> dict[str, Any]:
    expected_classes = {
        1: "CATEGORICAL_THREE_LEVEL_CONTRAST",
        2: "ADJUSTED_INTERCEPT",
        3: "ADJUSTED_INTERCEPT",
        4: "CONTINUOUS_SLOPE",
        5: "ADJUSTED_INTERCEPT",
        6: "AUTOREGRESSIVE_SLOPE_MINUS_ONE",
        7: "BINARY_MAIN_EFFECT",
        8: "PAIRED_DIFFERENCE_INTERCEPT",
        9: "BINARY_MAIN_EFFECT",
        10: "BINARY_MAIN_EFFECT",
        11: "CONTINUOUS_SLOPE",
        12: "BINARY_MAIN_EFFECT",
        13: "BINARY_MAIN_EFFECT",
        14: "CONTINUOUS_SLOPE",
        15: "BINARY_MAIN_EFFECT",
        16: "JOINT_BINARY_INTERACTION",
        17: "CONTINUOUS_SLOPE",
        18: "JOINT_BINARY_INTERACTION",
        19: "MUTUALLY_EXCLUSIVE_BINARY_CONTRAST",
        20: "BINARY_MAIN_EFFECT",
        21: "CONTINUOUS_SLOPE",
        22: "FROZEN_SPLINE_CONTRAST",
        23: "CONTINUOUS_SLOPE",
        24: "JOINT_BINARY_INTERACTION",
        25: "JOINT_BINARY_INTERACTION",
    }
    if expected_classes.get(index) != matrix_class:
        raise ValueError("power design matrix class does not match portfolio order")

    latent_variables: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = [
        {
            "name": "intercept",
            "expression": {"operator": "CONSTANT", "value": 1.0},
        }
    ]
    contrast_by_name: dict[str, float] = {}
    contrast_null_value = 0.0
    team_fixture_indices = {11, 12, 13, 17, 18, 19, 20, 21, 22}
    if index == 6:
        rows_per_fixture = 5
        row_order = "BOOKMAKER_WITHIN_FIXTURE"
        axis_cardinalities = {"BOOKMAKER": 5}
    elif index == 18:
        rows_per_fixture = 4
        row_order = "TEAM_THEN_HALF_WITHIN_FIXTURE"
        axis_cardinalities = {"TEAM": 2, "HALF": 2}
    elif index in team_fixture_indices:
        rows_per_fixture = 2
        row_order = "TEAM_WITHIN_FIXTURE"
        axis_cardinalities = {"TEAM": 2}
    else:
        rows_per_fixture = 1
        row_order = "FIXTURE_SINGLE_ROW"
        axis_cardinalities = {"FIXTURE": 1}
    team_repeat_rows = 2 if index == 18 else 1

    def scoped_fields(scope: str, repeat_rows: int) -> dict[str, Any]:
        fields: dict[str, Any] = {"scope": scope}
        if scope == "WITHIN_FIXTURE":
            fields["repeat_rows"] = repeat_rows
        return fields

    def add_normal(
        name: str,
        contrast_weight: float = 0.0,
        scope: str = "FIXTURE",
        repeat_rows: int = 1,
        distribution: str = "STANDARD_NORMAL",
        normalization: str | None = None,
    ) -> None:
        variable: dict[str, Any] = {
            "name": name,
            "distribution": distribution,
            **scoped_fields(scope, repeat_rows),
        }
        if normalization is not None:
            variable["normalization"] = normalization
        latent_variables.append(variable)
        columns.append(
            {
                "name": name,
                "expression": {"operator": "IDENTITY", "variable": name},
            }
        )
        if contrast_weight:
            contrast_by_name[name] = contrast_weight

    def add_binary(
        name: str,
        prevalence: float,
        contrast_weight: float = 0.0,
        scope: str = "FIXTURE",
        repeat_rows: int = 1,
    ) -> None:
        latent_variables.append(
            {
                "name": name,
                "distribution": "BERNOULLI",
                **scoped_fields(scope, repeat_rows),
                "prevalence": prevalence,
            }
        )
        columns.append(
            {
                "name": name,
                "expression": {"operator": "IDENTITY", "variable": name},
            }
        )
        if contrast_weight:
            contrast_by_name[name] = contrast_weight

    def add_categorical(
        name: str,
        levels: list[str],
        probabilities: list[float],
        dummy_levels: list[str],
        scope: str = "FIXTURE",
        repeat_rows: int = 1,
    ) -> None:
        latent_variables.append(
            {
                "name": name,
                "distribution": "CATEGORICAL",
                **scoped_fields(scope, repeat_rows),
                "levels": levels,
                "probabilities": probabilities,
            }
        )
        columns.extend(
            {
                "name": f"{name}_{level.lower()}",
                "expression": {
                    "operator": "LEVEL_IS",
                    "variable": name,
                    "level": level,
                },
            }
            for level in dummy_levels
        )

    def add_balanced_categorical(
        name: str,
        levels: list[str],
        block_size: int = 1,
        scope: str = "FIXTURE",
        repeat_rows: int = 1,
    ) -> None:
        latent_variables.append(
            {
                "name": name,
                "distribution": "BALANCED_CATEGORICAL",
                **scoped_fields(scope, repeat_rows),
                "levels": levels,
                "block_size": block_size,
            }
        )
        columns.extend(
            {
                "name": f"{name}_{level.lower()}",
                "expression": {
                    "operator": "LEVEL_IS",
                    "variable": name,
                    "level": level,
                },
            }
            for level in levels[1:]
        )

    def add_alternating_binary(
        name: str, scope: str = "WITHIN_FIXTURE", repeat_rows: int = 1
    ) -> None:
        latent_variables.append(
            {
                "name": name,
                "distribution": "ALTERNATING_BINARY",
                **scoped_fields(scope, repeat_rows),
            }
        )
        columns.append(
            {
                "name": name,
                "expression": {"operator": "IDENTITY", "variable": name},
            }
        )

    def add_home_away_binary(name: str, repeat_rows: int) -> None:
        latent_variables.append(
            {
                "name": name,
                "distribution": "HOME_AWAY_BINARY",
                **scoped_fields("WITHIN_FIXTURE", repeat_rows),
            }
        )
        columns.append(
            {
                "name": name,
                "expression": {"operator": "IDENTITY", "variable": name},
            }
        )

    def add_joint_interaction(
        cell_name: str, first_name: str, second_name: str, interaction_name: str
    ) -> None:
        latent_variables.append(
            {
                "name": cell_name,
                "distribution": "CATEGORICAL",
                "scope": "FIXTURE",
                "levels": ["00", "10", "01", "11"],
                "probabilities": [0.5625, 0.1875, 0.1875, 0.0625],
            }
        )
        columns.extend(
            [
                {
                    "name": first_name,
                    "expression": {
                        "operator": "LEVEL_IN",
                        "variable": cell_name,
                        "levels": ["10", "11"],
                    },
                },
                {
                    "name": second_name,
                    "expression": {
                        "operator": "LEVEL_IN",
                        "variable": cell_name,
                        "levels": ["01", "11"],
                    },
                },
                {
                    "name": interaction_name,
                    "expression": {
                        "operator": "LEVEL_IS",
                        "variable": cell_name,
                        "level": "11",
                    },
                },
            ]
        )
        contrast_by_name[interaction_name] = 1.0

    if index == 1:
        add_categorical(
            "outcome_class", ["AWAY", "HOME", "DRAW"], [0.28, 0.45, 0.27], ["HOME", "DRAW"]
        )
        contrast_by_name.update({"outcome_class_home": -0.5, "outcome_class_draw": 1.0})
    elif index in {2, 3, 5, 8}:
        contrast_by_name["intercept"] = 1.0
    elif index == 4:
        add_normal("overround_z", 1.0)
    elif index == 6:
        add_normal(
            "book_deviation_H24_z",
            1.0,
            scope="WITHIN_FIXTURE",
            distribution="FIXTURE_SYMMETRIC_STANDARD_NORMAL_ORDER_STATISTICS",
            normalization=FIXTURE_SYMMETRIC_NORMALIZATION,
        )
        contrast_null_value = 1.0
    elif index == 7:
        add_binary("low_coverage", 0.25, 1.0)
    elif index == 9:
        add_binary("high_volatility", 0.25, 1.0)
    elif index == 10:
        add_binary("misaligned", 0.25, 1.0)
    elif index == 11:
        add_normal(
            "adjusted_recent_form_z", 1.0, scope="WITHIN_FIXTURE", repeat_rows=1
        )
    elif index == 12:
        add_binary(
            "overperformance", 0.25, 1.0, scope="WITHIN_FIXTURE", repeat_rows=1
        )
    elif index == 13:
        add_binary(
            "unsupported_clean_sheet",
            0.25,
            1.0,
            scope="WITHIN_FIXTURE",
            repeat_rows=1,
        )
    elif index == 14:
        add_normal("same_venue_ewma_minus_all_venue_ewma_z", 1.0)
    elif index == 15:
        add_binary("promoted_early", 0.25, 1.0)
    elif index == 16:
        add_joint_interaction(
            "derby_low_total_cell", "derby", "low_total", "derby_x_low_total"
        )
    elif index == 17:
        add_normal(
            "rest_differential_z",
            1.0,
            scope="WITHIN_FIXTURE",
            repeat_rows=1,
            distribution="PAIRED_OPPOSITE_STANDARD_NORMAL",
        )
    elif index == 18:
        add_binary(
            "congested",
            0.25,
            scope="WITHIN_FIXTURE",
            repeat_rows=team_repeat_rows,
        )
        add_alternating_binary("second_half")
        columns.extend(
            [
                {
                    "name": "congested_x_second_half",
                    "expression": {
                        "operator": "PRODUCT",
                        "variables": ["congested", "second_half"],
                    },
                },
            ]
        )
        contrast_by_name["congested_x_second_half"] = 1.0
    elif index == 19:
        add_categorical(
            "europe_timing",
            ["NONE", "POST", "PRE"],
            [0.50, 0.25, 0.25],
            ["POST", "PRE"],
            scope="WITHIN_FIXTURE",
            repeat_rows=1,
        )
        contrast_by_name.update({"europe_timing_post": 1.0, "europe_timing_pre": -1.0})
    elif index == 20:
        add_binary(
            "post_coach_change", 0.25, 1.0, scope="WITHIN_FIXTURE", repeat_rows=1
        )
    elif index == 21:
        add_normal(
            "overranking_gap_z", 1.0, scope="WITHIN_FIXTURE", repeat_rows=1
        )
    elif index == 22:
        add_normal(
            "strength_gap_z",
            scope="WITHIN_FIXTURE",
            repeat_rows=1,
            distribution="PAIRED_OPPOSITE_STANDARD_NORMAL",
        )
        for knot, suffix in zip(
            (-2.0, -1.0, 0.0, 1.0, 2.0), ("m2", "m1", "0", "p1", "p2"), strict=True
        ):
            name = f"strength_gap_hinge_{suffix}"
            columns.append(
                {
                    "name": name,
                    "expression": {
                        "operator": "HINGE",
                        "variable": "strength_gap_z",
                        "knot": knot,
                    },
                }
            )
        contrast_by_name.update(
            {
                "strength_gap_hinge_m2": 2.0,
                "strength_gap_hinge_m1": 1.5,
                "strength_gap_hinge_0": 1.0,
                "strength_gap_hinge_p1": 0.5,
            }
        )
    elif index == 23:
        add_normal("cross_market_incoherence_H2_z", 1.0)
    elif index == 24:
        add_joint_interaction(
            "short_favourite_low_total_cell",
            "short_favourite",
            "low_total",
            "short_favourite_x_low_total",
        )
    elif index == 25:
        add_joint_interaction(
            "long_outsider_high_total_cell",
            "long_outsider",
            "high_total",
            "long_outsider_x_high_total",
        )
    else:
        raise ValueError("unknown portfolio order for power design matrix")

    normal_adjustments = {
        1: ["probability_bin_z"],
        5: ["dispersion_H2_z"],
        11: ["long_term_strength_z"],
        12: ["strength_z"],
        13: ["strength_z"],
        14: ["strength_z"],
        16: ["strength_z"],
        17: ["strength_z"],
        18: ["strength_z"],
        19: ["rest_z", "strength_z"],
        20: ["strength_z"],
        21: ["strength_z"],
    }
    for adjustment in normal_adjustments.get(index, []):
        if index in team_fixture_indices:
            add_normal(
                adjustment,
                scope="WITHIN_FIXTURE",
                repeat_rows=team_repeat_rows,
            )
        else:
            add_normal(adjustment)
    if index in {4, 7}:
        add_categorical(
            "adjustment_outcome", ["AWAY", "HOME", "DRAW"], [0.28, 0.45, 0.27], ["HOME", "DRAW"]
        )
    if index == 6:
        add_balanced_categorical(
            "book",
            ["B1", "B2", "B3", "B4", "B5"],
            scope="WITHIN_FIXTURE",
        )
    if index in team_fixture_indices:
        add_home_away_binary("venue_home", team_repeat_rows)
    add_balanced_categorical(
        "league_season", [f"LS{number}" for number in range(1, 9)]
    )

    weights = [contrast_by_name.get(column["name"], 0.0) for column in columns]
    if not any(weights):
        raise ValueError("power design matrix has no primary contrast")
    if math.prod(axis_cardinalities.values()) != rows_per_fixture:
        raise ValueError("fixture rows do not equal the declared axis product")
    for variable in latent_variables:
        if variable["scope"] == "WITHIN_FIXTURE" and (
            rows_per_fixture % int(variable["repeat_rows"])
        ):
            raise ValueError("within-fixture repeat does not divide the axis product")
    scope_by_latent = {
        variable["name"]: variable["scope"] for variable in latent_variables
    }

    def expression_latent_names(expression: dict[str, Any]) -> list[str]:
        if expression["operator"] == "CONSTANT":
            return []
        if expression["operator"] == "PRODUCT":
            return list(expression["variables"])
        return [expression["variable"]]

    fixture_invariant_columns: list[str] = []
    within_fixture_columns: list[str] = []
    for column in columns:
        latent_names = expression_latent_names(column["expression"])
        if all(scope_by_latent[name] == "FIXTURE" for name in latent_names):
            fixture_invariant_columns.append(column["name"])
        else:
            within_fixture_columns.append(column["name"])
    fixture_latent_names = [
        variable["name"]
        for variable in latent_variables
        if variable["scope"] == "FIXTURE"
    ]
    within_fixture_latent_names = [
        variable["name"]
        for variable in latent_variables
        if variable["scope"] == "WITHIN_FIXTURE"
    ]
    return {
        "design_class": matrix_class,
        "latent_variables": latent_variables,
        "columns": columns,
        "fixture_invariant_columns": fixture_invariant_columns,
        "within_fixture_columns": within_fixture_columns,
        "observation_expansion": {
            "cluster_unit": "fixture",
            "rows_per_fixture": rows_per_fixture,
            "row_order": row_order,
            "axis_cardinalities": axis_cardinalities,
            "fixture_latent_policy": "DRAW_ONCE_AND_CACHE_PER_FIXTURE",
            "within_fixture_latent_policy": (
                "CACHE_BY_DECLARED_REPEAT_ROWS_THEN_SEQUENCE"
            ),
            "fixture_latent_variables": fixture_latent_names,
            "within_fixture_latent_variables": within_fixture_latent_names,
        },
        "primary_contrast": {
            "parameter_name": primary_parameter,
            "weights": weights,
            "null_value": contrast_null_value,
        },
        "rank_policy": "FAIL_CLOSED_IF_XTX_NOT_FULL_RANK",
        "reference_level_policy": "FIRST_DECLARED_LEVEL_IS_REFERENCE",
    }


def _power_design_for_experiment(
    index: int,
    hypothesis: dict[str, Any],
    family_primary_test_count: int,
    global_primary_test_count: int,
) -> dict[str, Any]:
    model = hypothesis["operational_definition"]["model"]
    floor = int(hypothesis["minimum_sample_size"]["eligible_units"])
    contract = hypothesis["falsification_contract"]
    delta = float(hypothesis["expected_effect"]["minimum_relevant_standardized_effect"])
    alternatives = (
        [delta]
        if contract["orientation"] == "POSITIVE"
        else [-delta]
        if contract["orientation"] == "NEGATIVE"
        else [-delta, delta]
    )
    matrix_contract = _power_matrix_contract(
        index, model["power_design_matrix_class"], model["primary_parameter"]
    )
    rows_per_fixture = int(matrix_contract["observation_expansion"]["rows_per_fixture"])

    def round_up_to_complete_fixture(value: int) -> int:
        return math.ceil(value / rows_per_fixture) * rows_per_fixture

    candidate_sizes = sorted(
        {
            round_up_to_complete_fixture(value)
            for value in (
                floor,
                math.ceil(floor * 1.25),
                math.ceil(floor * 1.5),
                math.ceil(floor * 2),
            )
        }
    )
    fixture_median_outcome = index == 6
    simulator_definition = _power_simulator_definition()
    design: dict[str, Any] = {
        "status": "PREDECLARED_MODEL_SPECIFIC_POWER_DESIGN_NOT_RUN",
        "sporting_results_used": False,
        "design_method": model["power_design_class"],
        "simulator": {
            "version": POWER_SIMULATOR_VERSION,
            "definition_hash": sha256_json(simulator_definition),
            "definition": simulator_definition,
        },
        "formula_test_mapping": {
            "model_formula": model["formula"],
            "link": model["link"],
            "estimator_family": model["estimator_family"],
            "error_distribution": model["error_distribution"],
            "variance_model": model["variance_model"],
            "outcome_transformation": model["outcome_transformation"],
            "standardization": model["standardization"],
            "scalar_primary_contrast": model["primary_parameter"],
            "test_statistic": "TWO_SIDED_CLUSTER_ROBUST_WALD_SCALAR_CONTRAST",
        },
        "signed_design_alternatives": alternatives,
        "data_generating_process": {
            "design_matrix": matrix_contract,
            "coefficient_generation": {
                "primary_rule": (
                    "beta_primary=(alternative+contrast_null_value)*contrast/"
                    "dot(contrast,contrast)"
                ),
                "adjustment_rule": "cycle fixed coefficients [0.05,-0.05,0.10]",
                "contrast_identity": (
                    "population_OLS_contrast(final_fixture_centered_outcome)-"
                    "contrast_null_value=alternative"
                    if fixture_median_outcome
                    else "dot(primary_contrast_weights,beta)-"
                    "contrast_null_value=alternative"
                ),
                "injection_space": (
                    "FINAL_POSTPROCESSED_OUTCOME_CONTRAST"
                    if fixture_median_outcome
                    else "RAW_LINEAR_PREDICTOR"
                ),
                "calibration_rule": (
                    "PRIMARY_EXPOSURE_HAS_ZERO_SUM_ZERO_MEDIAN_UNIT_RMS_WITHIN_FIXTURE;"
                    "FIXTURE_MEDIAN_CENTERING_IS_ORTHOGONAL_TO_PRIMARY_CONTRAST"
                    if fixture_median_outcome
                    else "IDENTITY_NO_OUTCOME_POSTPROCESSING"
                ),
            },
            "cluster_process": {
                "cluster_unit": "fixture",
                "allocation_rule": "complete fixture clusters only; partial fixtures fail closed",
                "mean_cluster_size": rows_per_fixture,
                "intraclass_correlation": 0.05,
                "random_intercept_variance": 0.05,
                "idiosyncratic_error_variance": 0.95,
                "random_intercept_postprocessing": (
                    "CANCELLED_EXACTLY_BY_FIXTURE_MEDIAN_CENTERING"
                    if fixture_median_outcome
                    else "RETAINED_IN_TRANSFORMED_OUTCOME"
                ),
            },
            "outcome_equation": (
                "transformed_Y=X@beta(alternative,contrast,null_value)+"
                "fixture_random_intercept+epsilon"
            ),
            "outcome_postprocessing": {
                "outcome_construct": (
                    "BOOK_DEVIATION_FROM_SAME_FIXTURE_MEDIAN"
                    if fixture_median_outcome
                    else "DECLARED_TRANSFORMED_OUTCOME"
                ),
                "common_outcome_rule": (
                    "FIXTURE_MEDIAN_ZERO" if fixture_median_outcome else "NONE"
                ),
                "branch_outcome_rule": (
                    "FIXTURE_MEDIAN_ZERO" if fixture_median_outcome else "NONE"
                ),
                "branch_application_order": "AFTER_BRANCH_MEASUREMENT_NOISE",
                "random_intercept_effect": (
                    "COMMON_SHIFT_CANCELS_EXACTLY"
                    if fixture_median_outcome
                    else "COMMON_SHIFT_RETAINED"
                ),
            },
            "effect_injection_parameter": model["primary_parameter"],
            "effect_values": alternatives,
            "null_value": matrix_contract["primary_contrast"]["null_value"],
            "branch_transform": {
                "latent_fixture_rows_shared": True,
                "standardized_measurement_noise_sd": 0.02,
                "seed_scope": "BRANCH_TRANSFORM_ONLY",
            },
            "missingness": "NONE",
            "holdout_generation": "independent final 20 percent with unchanged DGP",
        },
        "test_mapping": {
            "interval_method": contract["interval_method"],
            "confidence_level": 0.95,
            "raw_p_value": "two-sided Wald p-value for scalar primary contrast",
            "classification_contract": {
                "claim_type": contract["claim_type"],
                "orientation": contract["orientation"],
                "minimum_effect": contract["minimum_effect"],
                "target_q": contract["target_q"],
            },
        },
        "decision_algorithm": {
            "branch_ids": [
                branch["branch_id"] for branch in hypothesis["devig_protocol"]["branches"]
            ],
            "branch_latent_draw_policy": "COMMON_LATENT_FIXTURES_SEPARATE_DEVIG_TRANSFORMS",
            "branch_results_aggregated": False,
            "family_primary_test_count": family_primary_test_count,
            "global_primary_test_count": global_primary_test_count,
            "null_companion_p_value_dgp": "INDEPENDENT_UNIFORM_0_1",
            "family_correction": "BENJAMINI_HOCHBERG_STEP_UP",
            "global_correction": "BENJAMINI_HOCHBERG_STEP_UP",
            "reported_q_value": "max(family_q,global_q)",
            "replicate_success": "EVERY_DECLARED_DEVIG_BRANCH_CLASSIFIED_SUPPORTED",
            "negative_control_alarm_policy": "ANY_ALARM_INVALIDATES_THE_DESIGN_REPLICATE",
        },
        "target_power": 0.80,
        "power_interval": "TWO_SIDED_95_PERCENT_WILSON_BINOMIAL",
        "simulation_replicates_per_candidate_n": 10000,
        "prng": "SHA256_COUNTER_BOX_MULLER_V1",
        "seed_derivation": {
            "common_latent": "first_64_bits(SHA256('LATENT'|master_seed|n|replicate_index))",
            "branch_transform": (
                "first_64_bits(SHA256('BRANCH_TRANSFORM'|latent_seed|branch_id))"
            ),
        },
        "master_seed": 202608140000 + index,
        "candidate_eligible_units": candidate_sizes,
        "acceptance_rule": (
            "choose the smallest n whose 95% Wilson lower power bound is >=0.80 for every "
            "signed_design_alternative; never reduce the planning floor"
        ),
        "execution_gate": (
            "simulation must be run and hash-pinned in a separately authorized design-only step "
            "before any sporting-data fit"
        ),
        "selected_eligible_units": None,
        "estimated_power": None,
    }
    hash_input = copy.deepcopy(design)
    design["design_contract_hash"] = sha256_json(hash_input)
    return design


def _build_experiments(hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    family_primary_test_counts = {
        family.family_id: sum(
            len(hypothesis["devig_protocol"]["branches"])
            for hypothesis in hypotheses
            if hypothesis["multiplicity_family"] == family.family_id
        )
        for family in FAMILIES
    }
    global_primary_test_count = sum(
        len(hypothesis["devig_protocol"]["branches"])
        for hypothesis in hypotheses
    )
    experiments = []
    for index, hypothesis in enumerate(_experiment_order(hypotheses), start=1):
        family = _family_by_id()[hypothesis["multiplicity_family"]]
        experiment: dict[str, Any] = {
            "experiment_id": f"RDS-EXP-V1-{index:03d}",
            "hypothesis_id": hypothesis["hypothesis_id"],
            "title": hypothesis["title"],
            "multiplicity_family": hypothesis["multiplicity_family"],
            "portfolio_stratum_id": hypothesis["portfolio_stratum_id"],
            "portfolio_order": hypothesis["portfolio_order"],
            "protocol_frozen": True,
            "freeze_status": "FROZEN_BEFORE_EXECUTION",
            "execution_status": "NOT_RUN",
            "execution_authority": "NOT_AUTHORIZED_IN_THIS_MISSION",
            "dataset_required": {
                "dependencies": copy.deepcopy(hypothesis["data_dependencies"]),
                "point_in_time_contract": PIT_CONTRACT_VERSION,
                "current_resolution": hypothesis["status"]["status_reason"],
            },
            "expected_snapshot_id": {
                "resolution_status": "NOT_YET_MATERIALIZED",
                "snapshot_kind": "HYPOTHESIS_LAB_POINT_IN_TIME_DATASET",
                "snapshot_schema_version": "hypothesis-lab-dataset-snapshot-v1",
                "required_native_identity": (
                    "Bind predictor, post-cutoff target and label native snapshot IDs independently "
                    "when they exist, and always bind each canonical dataset sha256 before execution."
                ),
                "predictor_snapshot_identity_required": True,
                "post_cutoff_target_snapshot_identity_required": bool(
                    hypothesis["point_in_time"][
                        "post_cutoff_target_receipt_backed_sources_required"
                    ]
                ),
                "label_snapshot_identity_required": True,
                "predictor_target_and_label_snapshots_must_be_distinct": True,
                "fabricated_placeholder_hash_forbidden": True,
            },
            "devig_protocol": copy.deepcopy(hypothesis["devig_protocol"]),
            "operational_definition": copy.deepcopy(hypothesis["operational_definition"]),
            "falsification_contract": copy.deepcopy(hypothesis["falsification_contract"]),
            "thresholds": {
                "minimum_relevant_standardized_effect": family.minimum_effect_size,
                "operational_thresholds": copy.deepcopy(
                    hypothesis["operational_definition"]["frozen_thresholds"]
                ),
                "family_fdr_q": 0.05,
                "global_fdr_q": 0.05,
                "confidence_level": 0.95,
                "threshold_search_after_freeze": "FORBIDDEN",
            },
            "minimum_sample": copy.deepcopy(hypothesis["minimum_sample_size"]),
            "model_specific_power_design": _power_design_for_experiment(
                index,
                hypothesis,
                family_primary_test_counts[hypothesis["multiplicity_family"]],
                global_primary_test_count,
            ),
            "holdout": copy.deepcopy(hypothesis["holdout"]),
            "walk_forward": copy.deepcopy(hypothesis["walk_forward"]),
            "league_holdout": copy.deepcopy(hypothesis["league_holdout"]),
            "season_holdout": copy.deepcopy(hypothesis["season_holdout"]),
            "go_no_go": {
                "GO": (
                    "Only continue to the next separately authorized research stage when sample, "
                    "receipt lineage, future-mutation invariance, effect floor, family/global q, "
                    "both separate de-vig branches and all negative controls satisfy the frozen protocol."
                ),
                "NO_GO": (
                    "Falsify or redesign when the declared direction/effect floor fails on the "
                    "season holdout, either de-vig branch contradicts it, a negative control alarms, "
                    "or any PIT proof is missing."
                ),
                "external_action": "NO_PROMOTION_NO_BET",
            },
            "compute_budget": {
                "estimated_cpu_hours": family.estimated_cpu_hours,
                "E1_dry_run": "10 fixtures, one league-season, <=5 wall-clock minutes",
                "full_inferential_run": "NOT_AUTHORIZED_IN_THIS_MISSION",
            },
            "human_time_hours": family.estimated_human_hours,
            "main_risk": family.main_risk,
            "negative_control_ids": _control_ids_for_experiment(index, hypothesis),
            "point_in_time": copy.deepcopy(hypothesis["point_in_time"]),
            "status": _status_object(),
        }
        protocol_hash_payload = copy.deepcopy(experiment)
        experiment["protocol_hash"] = sha256_json(protocol_hash_payload)
        experiments.append(experiment)
    return {
        "schema_version": "robin-first-25-experiment-protocols-v1",
        "report_id": "first-25-experiment-protocols-v1",
        "portfolio_size": len(experiments),
        "family_distribution": {
            family.family_id: sum(
                experiment["multiplicity_family"] == family.family_id
                for experiment in experiments
            )
            for family in FAMILIES
        },
        "protocol_state": "FROZEN_DESIGN_NOT_RUN",
        "experiments": experiments,
    }


def _envelope(report: dict[str, Any]) -> dict[str, Any]:
    document = copy.deepcopy(report)
    document.update(
        {
            "catalogue_version": CATALOGUE_VERSION,
            "immutable_base_revision": BASE_REVISION,
            "truth_kernel_version": TRUTH_KERNEL_VERSION,
            "point_in_time_contract_version": PIT_CONTRACT_VERSION,
            "status_labels": list(STATUS_LABELS),
            "status": _status_object(),
            "external_effects": copy.deepcopy(ZERO_EXTERNAL_EFFECTS),
            "content_hash_algorithm": CONTENT_HASH_ALGORITHM,
            "reproducibility": {
                "builder": "tools/hypothesis-lab/build_catalogue.py",
                "command": "python tools/hypothesis-lab/build_catalogue.py --check",
                "source": "tools/hypothesis-lab/catalogue-source-v1.json",
                "source_sha256": SOURCE_SHA256,
                "raw_candidate_source": "tools/hypothesis-lab/raw-candidates-v1.json",
                "raw_candidate_source_sha256": RAW_CANDIDATE_SOURCE_SHA256,
                "portfolio_source": "tools/hypothesis-lab/portfolio-strata-v1.json",
                "portfolio_source_sha256": PORTFOLIO_SOURCE_SHA256,
                "deterministic": True,
                "wall_clock_timestamp_included": False,
            },
        }
    )
    document["content_sha256"] = sha256_json(document)
    return document


def build_artifacts(
    source_records: Sequence[tuple[FamilySpec, IdeaSpec]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build all six reports in memory without touching the filesystem."""

    records = tuple(source_records) if source_records is not None else _source_records()
    hypotheses = _build_hypotheses(records)
    universe = {
        "schema_version": "robin-hypothesis-universe-v1",
        "report_id": "hypothesis-universe-v1",
        "scope": "DESIGN_ONLY_NO_SPORTING_RESULT",
        "candidate_generation": {
            "generated_formulations": 336,
            "seeded_scientific_questions": 112,
            "retained_distinct_hypotheses": len(hypotheses),
            "generation_lenses": [
                "MECHANISM_FORMULATION",
                "OBSERVABLE_ESTIMAND_FORMULATION",
                "FALSIFICATION_FORMULATION",
            ],
            "generation_policy": "THREE_DECLARED_LENSES_PER_SEEDED_SCIENTIFIC_QUESTION",
            "raw_registry": "tools/hypothesis-lab/raw-candidates-v1.json",
            "canonical_ids_assigned_after_clustering": True,
            "threshold_sweep_used_to_inflate_count": False,
        },
        "source_contracts": [
            "docs/scientific/ROBIN-SCIENTIFIC-TRUTH-KERNEL-V1.md",
            "reports/scientific-truth/devig-canonicalization-v1.json",
            "docs/scientific/ROBIN-POINT-IN-TIME-LINEAGE-V1.md",
            "reports/temporal-lineage/temporal-contract-v1.json",
            "configs/experiments/scale-policy-v3.json",
        ],
        "hypotheses": hypotheses,
    }
    reports = {
        "hypothesis-universe-v1.json": universe,
        "hypothesis-family-map-v1.json": _build_family_map(hypotheses),
        "hypothesis-deduplication-v1.json": _build_deduplication(hypotheses),
        "hypothesis-priority-scorecard-v1.json": _build_scorecard(hypotheses),
        "first-25-experiment-protocols-v1.json": _build_experiments(hypotheses),
        "negative-control-plan-v1.json": _build_negative_control_plan(),
    }
    return {filename: _envelope(report) for filename, report in reports.items()}


def _walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for nested in value.values():
            yield from _walk_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_values(nested)


def validate_artifacts(artifacts: dict[str, dict[str, Any]]) -> None:
    """Fail closed on every scientific and structural invariant in the brief."""

    if tuple(sorted(artifacts)) != tuple(sorted(REPORT_FILENAMES)):
        raise ValueError("unexpected report set")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for filename, document in artifacts.items():
        validator.validate(document)
        content_sha256 = document["content_sha256"]
        hash_input = copy.deepcopy(document)
        del hash_input["content_sha256"]
        if content_sha256 != sha256_json(hash_input):
            raise ValueError(f"content hash mismatch: {filename}")
        if tuple(document["status_labels"]) != STATUS_LABELS:
            raise ValueError(f"missing safety labels: {filename}")
        if document["external_effects"] != ZERO_EXTERNAL_EFFECTS:
            raise ValueError(f"external effect is non-zero: {filename}")

    universe = artifacts["hypothesis-universe-v1.json"]
    hypotheses = universe["hypotheses"]
    if not 80 <= len(hypotheses) <= 150:
        raise ValueError("canonical hypothesis count must remain within 80..150")
    if len({item["hypothesis_id"] for item in hypotheses}) != len(hypotheses):
        raise ValueError("duplicate hypothesis_id")
    if len({item["semantic_core_hash"] for item in hypotheses}) != len(hypotheses):
        raise ValueError("duplicate semantic core")
    if len({item["estimand_hash"] for item in hypotheses}) != len(hypotheses):
        raise ValueError("duplicate estimand")
    if hypotheses != sorted(hypotheses, key=lambda value: value["hypothesis_id"]):
        raise ValueError("hypotheses are not deterministically sorted")
    for hypothesis in hypotheses:
        if hypothesis["truth_kernel_version"] != TRUTH_KERNEL_VERSION:
            raise ValueError("truth kernel version missing")
        if hypothesis["estimand_hash"] != sha256_json(hypothesis["estimand_signature"]):
            raise ValueError("estimand hash does not match its structured signature")
        signature = hypothesis["estimand_signature"]
        required_semantic_fields = {
            "signature_version",
            "market_set",
            "population_scope",
            "unit_of_analysis",
            "base_features",
            "moderators",
            "outcome_construct",
            "target_horizon",
            "effect_scale",
            "cutoff_class",
        }
        if set(signature) not in (
            required_semantic_fields,
            required_semantic_fields | {"semantic_discriminator"},
        ) or signature["signature_version"] != "ESTIMAND_SIGNATURE_V2":
            raise ValueError("estimand signature is not the compositional semantic contract")
        forbidden_identity_surrogates = {
            hypothesis["concept_key"],
            hypothesis["concept_key"].upper(),
            hypothesis["title"],
            hypothesis["expected_effect"]["direction"],
        }
        if any(
            value in forbidden_identity_surrogates
            for value in _walk_values(signature)
            if isinstance(value, str)
        ):
            raise ValueError("estimand signature contains an identity surrogate")
        assertion_payload = {
            "estimand_hash": hypothesis["estimand_hash"],
            "expected_direction": hypothesis["expected_effect"]["direction"],
            "claim_type": hypothesis["falsification_contract"]["claim_type"],
            "orientation": hypothesis["falsification_contract"]["orientation"],
        }
        if hypothesis["assertion_hash"] != sha256_json(assertion_payload):
            raise ValueError("assertion hash does not match the structured claim")
        if hypothesis["semantic_core_hash"] != hypothesis["assertion_hash"]:
            raise ValueError("semantic core must alias the frozen assertion hash")
        expected_direction = hypothesis["expected_effect"]["direction"]
        falsification = hypothesis["falsification_contract"]
        if expected_direction in TWO_SIDED_DIRECTION_CODES:
            if (
                falsification["claim_type"] != "ABSOLUTE_MINIMUM"
                or falsification["orientation"] != "UNSIGNED"
            ):
                raise ValueError("two-sided assertion lost its absolute contract")
        elif (
            falsification["claim_type"] != "SIGNED_MINIMUM"
            or falsification["orientation"] not in {"POSITIVE", "NEGATIVE"}
        ):
            raise ValueError("directional assertion is not bound to a signed axis")
        if falsification["claim_type"] == "SIGNED_MINIMUM":
            delta = float(falsification["minimum_effect"])
            opposite_interval = (
                (-2 * delta, -1.5 * delta)
                if falsification["orientation"] == "POSITIVE"
                else (1.5 * delta, 2 * delta)
            )
            if (
                classify_interval(falsification, *opposite_interval, 0.01)
                != "FALSIFIED"
            ):
                raise ValueError("opposite-sign interval can support a directional assertion")
        expected_hypothesis_id = (
            f"RDS-HYP-V1-{hypothesis['assertion_hash'][:16].upper()}"
        )
        if hypothesis["hypothesis_id"] != expected_hypothesis_id:
            raise ValueError("hypothesis identity was not assigned from the assertion hash")
        if hypothesis["protocol_variant_hash"] != sha256_json(
            _protocol_variant_payload(hypothesis)
        ):
            raise ValueError("protocol variant hash drift")
        sample = hypothesis["minimum_sample_size"]
        if (
            sample["sample_status"]
            != "CONSERVATIVE_PLANNING_FLOOR_NOT_A_POWER_DEMONSTRATION"
            or sample["reference_power_is_demonstrated"] is not False
            or sample["model_specific_power_required_before_execution"] is not True
            or "planning_outcome_prevalence" in sample
        ):
            raise ValueError("planning floor is misrepresented as demonstrated power")
        if hypothesis["devig_protocol"] != _canonical_devig_protocol(hypothesis["market"]):
            raise ValueError("de-vig protocol is not the exact canonical market contract")
        point_in_time = hypothesis["point_in_time"]
        expected_predictor_cutoff = _predictor_cutoff_for(hypothesis["concept_key"])
        if point_in_time["available_at"] != {
            "required": True,
            "derivation": PIT_AVAILABLE_AT_DERIVATION,
            "event_at_substitution_forbidden": True,
        }:
            raise ValueError("available_at contract drift")
        if point_in_time["cutoff_at"] != {
            "cutoff_id": expected_predictor_cutoff["cutoff_id"],
            "legacy_alias": expected_predictor_cutoff["legacy_alias"],
            "rule": expected_predictor_cutoff["rule"],
            "admissibility": PIT_PREDICTOR_ADMISSIBILITY,
            "boundary_equality_allowed": True,
        }:
            raise ValueError("predictor cutoff contract drift")
        if hypothesis["temporal_cutoff"] != {
            "cutoff_id": expected_predictor_cutoff["cutoff_id"],
            "cutoff_at_rule": expected_predictor_cutoff["rule"],
            "predictor_inputs_rule": PIT_PREDICTOR_ADMISSIBILITY,
            "post_cutoff_target_rule": (
                PIT_TARGET_ADMISSIBILITY
                if hypothesis["concept_key"] in POST_CUTOFF_TARGETS
                else None
            ),
            "label_rule": PIT_LABEL_ADMISSIBILITY,
        }:
            raise ValueError("hypothesis temporal cutoff drift")
        if signature["cutoff_class"] != expected_predictor_cutoff["cutoff_class"]:
            raise ValueError("estimand cutoff class drift")
        if point_in_time["cutoff_at"]["admissibility"] != PIT_PREDICTOR_ADMISSIBILITY:
            raise ValueError("predictor cutoff admissibility drift")
        if tuple(point_in_time["predictor_receipt_fields_required"]) != RECEIPT_FIELDS:
            raise ValueError("predictor receipt fields drift")
        if tuple(point_in_time["label_receipt_fields_required"]) != LABEL_RECEIPT_FIELDS:
            raise ValueError("label receipt fields drift")
        if tuple(point_in_time["data_forbidden_before_cutoff"]) != PIT_FORBIDDEN_BEFORE_CUTOFF:
            raise ValueError("forbidden pre-cutoff data contract drift")
        if tuple(point_in_time["future_mutation_test"]["mutations"]) != PIT_FUTURE_MUTATIONS:
            raise ValueError("future mutation contract drift")
        if not hypothesis["data_dependencies"]:
            raise ValueError("data dependencies are required")
        predictor_dependencies = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] in {"FEATURE", "ODDS", "METADATA"}
        ]
        target_dependencies = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] == "TARGET"
        ]
        label_dependencies = [
            dependency
            for dependency in hypothesis["data_dependencies"]
            if dependency["role"] == "LABEL"
        ]
        if len(label_dependencies) != 1 or label_dependencies[0]["dataset"] != OUTCOME_LABEL_DATASET:
            raise ValueError("exactly one canonical label dependency is required")
        if any(
            "settled" in dependency["dataset"].lower()
            and "outcome" in dependency["dataset"].lower()
            for dependency in predictor_dependencies
        ):
            raise ValueError("settled outcomes cannot be pre-cutoff predictors")
        if [dependency["dataset"] for dependency in predictor_dependencies] != point_in_time[
            "predictor_receipt_backed_sources_required"
        ]:
            raise ValueError("PIT predictor sources do not match dependency roles")
        if point_in_time["label_receipt_backed_sources_required"] != [OUTCOME_LABEL_DATASET]:
            raise ValueError("PIT label source drift")
        expected_target = POST_CUTOFF_TARGETS.get(hypothesis["concept_key"])
        expected_target_sources = [expected_target["dataset"]] if expected_target else []
        if [row["dataset"] for row in target_dependencies] != expected_target_sources:
            raise ValueError("post-cutoff target dependency drift")
        if point_in_time["post_cutoff_target_receipt_backed_sources_required"] != (
            expected_target_sources
        ):
            raise ValueError("post-cutoff target PIT source drift")
        if expected_target:
            if len(target_dependencies) != 1:
                raise ValueError("exactly one declared post-cutoff target is required")
            target_dependency = target_dependencies[0]
            if (
                target_dependency["temporal_admissibility"] != PIT_TARGET_ADMISSIBILITY
                or target_dependency["eligible_as_pre_cutoff_predictor"] is not False
                or point_in_time["post_cutoff_target_admissibility"]
                != {
                    "rule": PIT_TARGET_ADMISSIBILITY,
                    "target_window_id": expected_target["target_window_id"],
                    "target_window_end_rule": expected_target["target_window_end_rule"],
                    "eligible_as_pre_cutoff_predictor": False,
                }
            ):
                raise ValueError("post-cutoff target is not isolated from predictors")
            if point_in_time["post_cutoff_target_receipt_fields_required"] != list(
                TARGET_RECEIPT_FIELDS
            ):
                raise ValueError("post-cutoff target receipt fields drift")
            if signature["outcome_construct"] != expected_target["outcome_construct"]:
                raise ValueError("estimand signature does not identify the primary target")
            if hypothesis["primary_metric"] != expected_target["primary_metric"]:
                raise ValueError("primary metric does not identify the target response")
            if target_dependencies[0]["analysis_usage"] != "PRIMARY_MODEL_OUTCOME":
                raise ValueError("post-cutoff target is not the primary model outcome")
            if label_dependencies[0]["analysis_usage"] != "SECONDARY_METRIC_LABEL_ONLY":
                raise ValueError("settled label is not isolated to secondary metrics")
        elif point_in_time["post_cutoff_target_admissibility"] is not None:
            raise ValueError("unexpected post-cutoff target contract")
        elif point_in_time["post_cutoff_target_receipt_fields_required"]:
            raise ValueError("unexpected post-cutoff target receipt fields")
        elif signature["outcome_construct"] != "SETTLED_CURRENT_FIXTURE_OUTCOME":
            raise ValueError("non-target estimand outcome construct drift")
        for dependency in predictor_dependencies:
            if dependency["temporal_admissibility"] != PIT_PREDICTOR_ADMISSIBILITY:
                raise ValueError("predictor dependency does not use the canonical cutoff rule")
            if dependency["eligible_as_pre_cutoff_predictor"] is not True:
                raise ValueError("predictor dependency eligibility drift")
        label_dependency = label_dependencies[0]
        if (
            label_dependency["temporal_admissibility"] != PIT_LABEL_ADMISSIBILITY
            or label_dependency["eligible_as_pre_cutoff_predictor"] is not False
            or label_dependency["result_available_at_required"] is not True
            or label_dependency["settlement_receipt_required"] is not True
        ):
            raise ValueError("label lineage is not post-event and settlement-backed")
        absent_source = any(
            dependency["snapshot_resolution"] == "SOURCE_CONTRACT_ABSENT"
            for dependency in predictor_dependencies
        )
        if absent_source != (
            hypothesis["status"]["lifecycle_status"] == "DATA_GATE_BLOCKED"
            and point_in_time["prospective_observability_status"]
            == "DATA_NOT_PROSPECTIVELY_OBSERVABLE"
        ):
            raise ValueError("source-contract absence does not fail closed")
        if hypothesis["status"]["status_reason"] == "DATA_NOT_PROSPECTIVELY_OBSERVABLE":
            raise ValueError("reason must explain, not repeat, the status")

    family_map = artifacts["hypothesis-family-map-v1.json"]
    if len(family_map["families"]) != 8:
        raise ValueError("exactly eight multiplicity families are required")
    if sum(family["hypothesis_count"] for family in family_map["families"]) != len(
        hypotheses
    ):
        raise ValueError("family counts do not resolve")
    if sum(
        family["maximum_primary_tests"] for family in family_map["families"]
    ) != 2 * len(hypotheses):
        raise ValueError("maximum primary test count must be twice the hypothesis count")
    family_members = [
        hypothesis_id
        for family in family_map["families"]
        for hypothesis_id in family["hypothesis_ids"]
    ]
    if sorted(family_members) != sorted(item["hypothesis_id"] for item in hypotheses):
        raise ValueError("each hypothesis must resolve to exactly one family")

    deduplication = artifacts["hypothesis-deduplication-v1.json"]
    candidates = deduplication["candidates"]
    if not 200 <= len(candidates) <= 500 or len(candidates) != 336:
        raise ValueError("candidate count must be exactly 336 and within 200..500")
    if len({candidate["candidate_id"] for candidate in candidates}) != len(candidates):
        raise ValueError("candidate IDs are not unique")
    if deduplication["generation_counts"] != {
        "candidate_formulations": 336,
        "seeded_scientific_questions": 112,
        "merged_equivalent_formulations": 336 - len(hypotheses),
        "rejected_formulations": 0,
        "retained_semantic_cores": len(hypotheses),
        "threshold_only_hypotheses_retained": 0,
    }:
        raise ValueError("deduplication accounting changed")
    known_ids = {item["hypothesis_id"] for item in hypotheses}
    hypothesis_by_id = {item["hypothesis_id"]: item for item in hypotheses}
    candidate_by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
    for candidate in candidates:
        canonical_id = candidate["canonical_hypothesis_id"]
        if canonical_id not in known_ids:
            raise ValueError("candidate does not resolve to a hypothesis")
        hypothesis = hypothesis_by_id[canonical_id]
        if candidate["estimand_hash"] != hypothesis["estimand_hash"]:
            raise ValueError("candidate estimand hash does not match its hypothesis")
        if candidate["assertion_hash"] != hypothesis["assertion_hash"]:
            raise ValueError("candidate assertion hash does not match its hypothesis")
        if candidate["semantic_core_hash"] != hypothesis["semantic_core_hash"]:
            raise ValueError("candidate semantic core does not match its hypothesis")
        if candidate["normalized_formulation"] != normalize_formulation(candidate["formulation"]):
            raise ValueError("candidate prose normalization drift")

    clustered_ids = [
        candidate_id
        for cluster in deduplication["clusters"]
        for candidate_id in cluster["candidate_ids"]
    ]
    if len(clustered_ids) != len(set(clustered_ids)) or set(clustered_ids) != set(candidate_by_id):
        raise ValueError("clusters must partition every raw candidate exactly once")
    if len(deduplication["clusters"]) != len(hypotheses):
        raise ValueError("deduplication clusters must equal the hypothesis universe")
    if {cluster["canonical_hypothesis_id"] for cluster in deduplication["clusters"]} != known_ids:
        raise ValueError("clusters must resolve bijectively to the hypothesis universe")
    for cluster in deduplication["clusters"]:
        canonical_id = cluster["canonical_hypothesis_id"]
        hypothesis = hypothesis_by_id[canonical_id]
        if cluster["estimand_hash"] != sha256_json(cluster["estimand_signature"]):
            raise ValueError("cluster estimand signature hash drift")
        if cluster["estimand_hash"] != hypothesis["estimand_hash"]:
            raise ValueError("cluster estimand does not match its hypothesis")
        if cluster["assertion_hashes"] != [hypothesis["assertion_hash"]]:
            raise ValueError("cluster assertion adjudication drift")
        if cluster["candidate_count"] != len(cluster["candidate_ids"]):
            raise ValueError("cluster candidate count mismatch")
        if cluster["seed_question_hashes"] != sorted(
            {
                candidate_by_id[candidate_id]["seed_question_hash"]
                for candidate_id in cluster["candidate_ids"]
            }
        ):
            raise ValueError("cluster seed-question lineage drift")
        if cluster["representative_candidate_id"] not in cluster["candidate_ids"]:
            raise ValueError("cluster representative is not a member")
        for candidate_id in cluster["candidate_ids"]:
            candidate = candidate_by_id[candidate_id]
            if candidate["canonical_hypothesis_id"] != canonical_id:
                raise ValueError("cluster member points to another hypothesis")
            if candidate["estimand_hash"] != cluster["estimand_hash"]:
                raise ValueError("cluster member estimand mismatch")

    raw_candidate_by_id = {row["candidate_id"]: row for row in RAW_CANDIDATES}
    if set(raw_candidate_by_id) != set(candidate_by_id):
        raise ValueError("deduplication report does not reproduce the frozen raw registry")
    for candidate_id, candidate in candidate_by_id.items():
        raw_candidate = raw_candidate_by_id[candidate_id]
        if (
            candidate["formulation"] != raw_candidate["formulation"]
            or candidate["generation_lens"] != raw_candidate["generation_lens"]
            or candidate["seed_question_hash"] != raw_candidate["seed_question_hash"]
            or candidate["estimand_hash"]
            != sha256_json(raw_candidate["structured_projection"])
        ):
            raise ValueError("candidate report drifted from the frozen raw registry")

    scorecard = artifacts["hypothesis-priority-scorecard-v1.json"]
    if scorecard["selection_policy"]["selected_count"] != 25:
        raise ValueError("scorecard must select exactly 25")
    score_ids = [entry["hypothesis_id"] for entry in scorecard["entries"]]
    if len(score_ids) != len(set(score_ids)) or set(score_ids) != known_ids:
        raise ValueError("scorecard hypothesis IDs must resolve exactly once to the universe")
    for entry in scorecard["entries"]:
        if set(entry["components"]) != set(SCORE_WEIGHTS):
            raise ValueError("score component set changed")
        if entry["total"] != sum(entry["components"].values()):
            raise ValueError("score total mismatch")
        if any(
            not 0 <= entry["components"][key] <= SCORE_WEIGHTS[key]
            for key in SCORE_WEIGHTS
        ):
            raise ValueError("score exceeds rubric")
        if entry["historical_roi_used"] is not False:
            raise ValueError("historical ROI cannot enter priority")
    expected_score_order = sorted(
        scorecard["entries"],
        key=lambda entry: (
            -entry["total"],
            -entry["components"]["point_in_time_provability"],
            -entry["components"]["falsifiability"],
            entry["hypothesis_id"],
        ),
    )
    if scorecard["entries"] != expected_score_order:
        raise ValueError("scorecard order does not follow the declared deterministic policy")
    _validate_score_rank_sequence(scorecard["entries"], len(hypotheses))
    expected_quotas = {
        family.family_id: family.first_portfolio_quota for family in FAMILIES
    }
    if scorecard["selection_policy"]["family_quotas"] != expected_quotas:
        raise ValueError("family quotas do not reproduce the frozen portfolio source")
    selected_entries = [
        entry for entry in scorecard["entries"] if entry["selected_for_first_25"]
    ]
    if {
        family_id: sum(entry["multiplicity_family"] == family_id for entry in selected_entries)
        for family_id in expected_quotas
    } != expected_quotas:
        raise ValueError("selected score entries violate family quotas")
    selected_hypotheses = [
        hypothesis for hypothesis in hypotheses if hypothesis["first_portfolio_candidate"]
    ]
    if {entry["hypothesis_id"] for entry in selected_entries} != {
        hypothesis["hypothesis_id"] for hypothesis in selected_hypotheses
    }:
        raise ValueError("scorecard selection does not match the hypothesis universe")
    stratum_ids = {stratum["stratum_id"] for stratum in PORTFOLIO_STRATA}
    if {hypothesis["portfolio_stratum_id"] for hypothesis in selected_hypotheses} != stratum_ids:
        raise ValueError("portfolio selection does not resolve every frozen stratum")

    experiments = artifacts["first-25-experiment-protocols-v1.json"]
    if experiments["portfolio_size"] != 25 or len(experiments["experiments"]) != 25:
        raise ValueError("first portfolio must contain exactly 25 experiments")
    if set(experiments["family_distribution"]) != {family.family_id for family in FAMILIES}:
        raise ValueError("first portfolio does not cover every family")
    if experiments["family_distribution"] != {
        family.family_id: family.first_portfolio_quota for family in FAMILIES
    }:
        raise ValueError("experiment family distribution violates frozen quotas")
    experiment_ids = [experiment["experiment_id"] for experiment in experiments["experiments"]]
    experiment_hypothesis_ids = [
        experiment["hypothesis_id"] for experiment in experiments["experiments"]
    ]
    selected_ids = {
        entry["hypothesis_id"]
        for entry in scorecard["entries"]
        if entry["selected_for_first_25"]
    }
    if len(experiment_ids) != len(set(experiment_ids)):
        raise ValueError("experiment IDs must be unique")
    if len(experiment_hypothesis_ids) != len(set(experiment_hypothesis_ids)):
        raise ValueError("first portfolio repeats a hypothesis")
    if set(experiment_hypothesis_ids) != selected_ids:
        raise ValueError("experiment hypotheses must equal the frozen scorecard selection")
    expected_experiment_hypothesis_ids = [
        hypothesis["hypothesis_id"] for hypothesis in _experiment_order(hypotheses)
    ]
    if experiment_hypothesis_ids != expected_experiment_hypothesis_ids:
        raise ValueError("experiment order does not reproduce the frozen stratum order")
    if experiment_ids != [f"RDS-EXP-V1-{index:03d}" for index in range(1, 26)]:
        raise ValueError("experiment IDs do not reproduce the frozen order")
    hypothesis_family = {
        hypothesis["hypothesis_id"]: hypothesis["multiplicity_family"]
        for hypothesis in hypotheses
    }
    hypothesis_by_id = {hypothesis["hypothesis_id"]: hypothesis for hypothesis in hypotheses}
    family_primary_test_counts = {
        family.family_id: sum(
            len(hypothesis["devig_protocol"]["branches"])
            for hypothesis in hypotheses
            if hypothesis["multiplicity_family"] == family.family_id
        )
        for family in FAMILIES
    }
    global_primary_test_count = sum(
        len(hypothesis["devig_protocol"]["branches"])
        for hypothesis in hypotheses
    )
    for experiment in experiments["experiments"]:
        if experiment["hypothesis_id"] not in known_ids:
            raise ValueError("experiment hypothesis does not resolve to the universe")
        if experiment["multiplicity_family"] != hypothesis_family[experiment["hypothesis_id"]]:
            raise ValueError("experiment family does not match its hypothesis")
        hypothesis = hypothesis_by_id[experiment["hypothesis_id"]]
        if experiment["portfolio_stratum_id"] != hypothesis["portfolio_stratum_id"]:
            raise ValueError("experiment stratum does not match its hypothesis")
        if experiment["portfolio_order"] != hypothesis["portfolio_order"]:
            raise ValueError("experiment portfolio order does not match its hypothesis")
        if experiment["devig_protocol"] != hypothesis["devig_protocol"]:
            raise ValueError("experiment de-vig protocol does not match its hypothesis")
        if experiment["operational_definition"] != hypothesis["operational_definition"]:
            raise ValueError("experiment operational definition does not match its hypothesis")
        model = experiment["operational_definition"]["model"]
        required_model_fields = {
            "cluster",
            "fixed_effects",
            "formula",
            "link",
            "primary_parameter",
            "estimator_family",
            "error_distribution",
            "variance_model",
            "standardization",
            "outcome_transformation",
            "power_design_class",
            "power_design_matrix_class",
        }
        if set(model) != required_model_fields:
            raise ValueError("experiment model is not estimator-complete")
        if not model["primary_parameter"] or model["primary_parameter"].startswith("joint_"):
            raise ValueError("experiment primary contrast must be a frozen scalar")
        power_design = experiment["model_specific_power_design"]
        if power_design != _power_design_for_experiment(
            experiment["portfolio_order"],
            hypothesis,
            family_primary_test_counts[hypothesis["multiplicity_family"]],
            global_primary_test_count,
        ):
            raise ValueError("model-specific power design drift")
        matrix_contract = power_design["data_generating_process"]["design_matrix"]
        expansion = matrix_contract["observation_expansion"]
        rows_per_fixture = int(expansion["rows_per_fixture"])
        if math.prod(expansion["axis_cardinalities"].values()) != rows_per_fixture:
            raise ValueError("power fixture axis product drift")
        if power_design["data_generating_process"]["cluster_process"][
            "mean_cluster_size"
        ] != rows_per_fixture:
            raise ValueError("power cluster grain drift")
        if any(
            int(candidate_size) % rows_per_fixture
            for candidate_size in power_design["candidate_eligible_units"]
        ):
            raise ValueError("partial fixture candidate size")
        column_names = {column["name"] for column in matrix_contract["columns"]}
        if "league_season" in model["fixed_effects"] and {
            f"league_season_ls{number}" for number in range(2, 9)
        } - column_names:
            raise ValueError("declared league-season fixed effect missing from power matrix")
        portfolio_order = int(experiment["portfolio_order"])
        team_fixture_orders = {11, 12, 13, 17, 18, 19, 20, 21, 22}
        expected_axes = (
            {"BOOKMAKER": 5}
            if portfolio_order == 6
            else {"TEAM": 2, "HALF": 2}
            if portfolio_order == 18
            else {"TEAM": 2}
            if portfolio_order in team_fixture_orders
            else {"FIXTURE": 1}
        )
        if expansion["axis_cardinalities"] != expected_axes:
            raise ValueError("power observation grain does not match the frozen unit")
        postprocessing = power_design["data_generating_process"][
            "outcome_postprocessing"
        ]
        expected_outcome_rule = (
            "FIXTURE_MEDIAN_ZERO" if portfolio_order == 6 else "NONE"
        )
        if (
            postprocessing["common_outcome_rule"] != expected_outcome_rule
            or postprocessing["branch_outcome_rule"] != expected_outcome_rule
        ):
            raise ValueError("power outcome construction does not match the estimand")
        simulator = power_design["simulator"]
        simulator_definition = _power_simulator_definition()
        if (
            simulator["definition"] != simulator_definition
            or simulator["definition_hash"] != sha256_json(simulator_definition)
        ):
            raise ValueError("power simulator definition hash mismatch")
        power_hash_input = copy.deepcopy(power_design)
        power_contract_hash = power_hash_input.pop("design_contract_hash")
        if power_contract_hash != sha256_json(power_hash_input):
            raise ValueError("power design contract hash mismatch")
        if (
            power_design["status"]
            != "PREDECLARED_MODEL_SPECIFIC_POWER_DESIGN_NOT_RUN"
            or power_design["estimated_power"] is not None
            or power_design["selected_eligible_units"] is not None
            or power_design["sporting_results_used"] is not False
        ):
            raise ValueError("power design was executed or populated without authority")
        if experiment["falsification_contract"] != hypothesis["falsification_contract"]:
            raise ValueError("experiment falsification contract does not match its hypothesis")
        if experiment["dataset_required"]["dependencies"] != hypothesis["data_dependencies"]:
            raise ValueError("experiment dependencies do not match its hypothesis")
        if experiment["point_in_time"] != hypothesis["point_in_time"]:
            raise ValueError("experiment PIT contract does not match its hypothesis")
        if experiment["execution_status"] != "NOT_RUN":
            raise ValueError("experiment execution is forbidden")
        if experiment["expected_snapshot_id"]["resolution_status"] != "NOT_YET_MATERIALIZED":
            raise ValueError("snapshot identity must not be fabricated")
        if experiment["devig_protocol"]["branch_results_aggregated"] is not False:
            raise ValueError("experiment de-vig branches are aggregated")
        hash_input = copy.deepcopy(experiment)
        protocol_hash = hash_input.pop("protocol_hash")
        if protocol_hash != sha256_json(hash_input):
            raise ValueError("experiment protocol hash mismatch")

    negative_controls = artifacts["negative-control-plan-v1.json"]
    if negative_controls["control_count"] != 9 or len(negative_controls["controls"]) != 9:
        raise ValueError("negative-control count must be nine")
    categories = {control["category"] for control in negative_controls["controls"]}
    if not set(negative_controls["required_categories"]).issubset(categories):
        raise ValueError("negative-control category missing")
    expected_factory_controls = {"RDS-NC-V1-005", "RDS-NC-V1-006", "RDS-NC-V1-008"}
    if set(negative_controls["factory_wide_control_ids"]) != expected_factory_controls:
        raise ValueError("factory-wide negative-control assignment drift")
    control_by_id = {
        control["control_id"]: control for control in negative_controls["controls"]
    }
    if set(control_by_id) != {f"RDS-NC-V1-{index:03d}" for index in range(1, 10)}:
        raise ValueError("negative-control IDs must be exactly 001..009")
    for control_id, control in control_by_id.items():
        expected_scope = (
            "FACTORY_WIDE" if control_id in expected_factory_controls else "EXPERIMENT_PROTOCOL"
        )
        if control["assignment_scope"] != expected_scope:
            raise ValueError("negative-control assignment scope drift")
        expected_alarm = (
            "ANY_SINGLE_GUARD_VIOLATION_STOPS_THE_FACTORY"
            if control["control_type"] == "DETERMINISTIC_GUARD"
            else "AT_LEAST_4_OF_20_SEEDED_REPLICATES_CROSS_Q_AND_EFFECT_FLOOR"
        )
        if control["frozen_alarm_rule"] != expected_alarm:
            raise ValueError("negative-control alarm rule is not numerically frozen")
        if control["control_type"] == "STOCHASTIC_REPLICATE":
            seeds = control["replicate_seeds"]
            if len(seeds) != 20 or len(set(seeds)) != 20:
                raise ValueError("stochastic negative control must freeze 20 unique seeds")
        elif control["replicate_seeds"]:
            raise ValueError("deterministic guard cannot declare stochastic replicates")
    assigned_experiment_controls = {
        control_id
        for experiment in experiments["experiments"]
        for control_id in experiment["negative_control_ids"]
    }
    if assigned_experiment_controls | expected_factory_controls != set(control_by_id):
        raise ValueError("negative controls are neither experiment-assigned nor factory-wide")

    forbidden_statuses = {
        "PROFIT" + "ABLE",
        "ED" + "GE",
        "SURV" + "IVOR",
        "ROB" + "UST",
        "VALI" + "DATED",
        "PROMOT" + "ABLE",
    }
    absolute_path_pattern = re.compile(
        r"(?:[A-Za-z]:[\\/]|"
        + "/"
        + "Users/|"
        + "/"
        + "home/|"
        + "/"
        + "mnt/)"
    )
    for filename, document in artifacts.items():
        for value in _walk_values(document):
            if isinstance(value, str) and value in forbidden_statuses:
                raise ValueError(f"forbidden scientific status in {filename}: {value}")
            if isinstance(value, str) and absolute_path_pattern.search(value):
                raise ValueError(f"absolute path in {filename}")

    if artifacts != build_artifacts():
        raise ValueError("artefacts do not reproduce the three frozen source registries")


def write_artifacts(
    artifacts: dict[str, dict[str, Any]], output_dir: Path = DEFAULT_OUTPUT_DIR
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, document in artifacts.items():
        (output_dir / filename).write_bytes(render_json(document))


def check_artifacts(
    artifacts: dict[str, dict[str, Any]], output_dir: Path = DEFAULT_OUTPUT_DIR
) -> None:
    actual_files = tuple(sorted(path.name for path in output_dir.glob("*.json")))
    if actual_files != tuple(sorted(REPORT_FILENAMES)):
        raise ValueError(f"unexpected committed report set: {actual_files}")
    for filename, document in artifacts.items():
        expected = render_json(document)
        actual = (output_dir / filename).read_bytes().replace(b"\r\n", b"\n")
        if actual != expected:
            raise ValueError(f"stale generated report: {filename}")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the six deterministic reports")
    mode.add_argument("--check", action="store_true", help="validate and compare committed bytes")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    artifacts = build_artifacts()
    validate_artifacts(artifacts)
    if args.write:
        write_artifacts(artifacts, args.output_dir)
    else:
        check_artifacts(artifacts, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
