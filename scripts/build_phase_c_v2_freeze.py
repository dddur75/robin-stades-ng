"""Build the target-blind Phase C V2 property and tag freeze.

This script never opens target labels or source payloads.  It preserves every
V1 tag object and adds the pre-registered V2 historical-lag transforms only.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
V1_REGISTRY = ROOT / "configs/hypothesis-tags/canonical-tag-registry-v1.json"
PROPERTY_CONTRACT = ROOT / "configs/hypothesis-tags/predictor-property-contract-v2.json"
V2_REGISTRY = ROOT / "configs/hypothesis-tags/canonical-tag-registry-v2.json"
PROPERTY_REPORT = ROOT / "reports/hypothesis-genome/predictor-eligible-property-set-v2.json"
FROZEN_AT = "2026-08-08T20:30:00Z"
SIDES = ("AWAY", "HOME")
WINDOWS = ("L10", "L3", "L5", "SEASON_TO_DATE")
FORMATIONS = ("3_4_3", "3_5_2", "4_1_4_1", "4_2_3_1", "4_3_3", "4_4_2", "5_3_2", "5_4_1")
RESULTS = ("DRAW", "LOSS", "WIN")

FIELD_SPECS: dict[str, dict[str, str]] = {
    "fixture.date": {"entity_type": "fixture", "json_path": "data.fixture.date", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture.status.short": {"entity_type": "fixture", "json_path": "data.fixture.status.short", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "score.fulltime.home": {"entity_type": "fixture", "json_path": "data.score.fulltime.home", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "score.fulltime.away": {"entity_type": "fixture", "json_path": "data.score.fulltime.away", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "teams.home.id": {"entity_type": "fixture", "json_path": "data.teams.home.id", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "teams.away.id": {"entity_type": "fixture", "json_path": "data.teams.away.id", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.type": {"entity_type": "fixture_event", "json_path": "data.type", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.detail": {"entity_type": "fixture_event", "json_path": "data.detail", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.time.elapsed": {"entity_type": "fixture_event", "json_path": "data.time.elapsed", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.time.extra": {"entity_type": "fixture_event", "json_path": "data.time.extra", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.team.id": {"entity_type": "fixture_event", "json_path": "data.team.id", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.player.id": {"entity_type": "fixture_event", "json_path": "data.player.id", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.assist.id": {"entity_type": "fixture_event", "json_path": "data.assist.id", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "fixture_event.data.comments": {"entity_type": "fixture_event", "json_path": "data.comments", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
    "formation.data.formation": {"entity_type": "formation", "json_path": "data.formation", "temporal_use": "PRIOR_FIXTURES_ONLY", "transform_version": "phase-c-source-field-v2"},
}

TRANSFORM_SPECS: dict[str, dict[str, object]] = {
    "PRIOR_SUBSTITUTIONS_MEAN": {"formula": "MEAN(DISTINCT_SCIENTIFIC_SUBSTITUTION_FACT_COUNT_PER_PRIOR_FIXTURE)", "windows": list(WINDOWS), "minimum_history": {"fixed_windows": "EXACT_N", "season_to_date": 3}, "source_status": "ALL_INSPECTED_COLLECTIONS_KNOWN", "unknown_policy": "UNKNOWN_ON_MISSING_INVALID_OR_UNCLASSIFIABLE_EVENT_COLLECTION"},
    "PRIOR_YELLOW_CARDS_MEAN": {"formula": "MEAN(YELLOW_OR_SECOND_YELLOW_SCIENTIFIC_FACT_COUNT_PER_PRIOR_FIXTURE)", "windows": list(WINDOWS), "minimum_history": {"fixed_windows": "EXACT_N", "season_to_date": 3}, "second_yellow_policy": "COUNTS_AS_YELLOW_AND_DISMISSAL", "unknown_policy": "UNKNOWN_ON_MISSING_INVALID_OR_UNCLASSIFIABLE_CARD_DETAIL"},
    "PRIOR_DISMISSALS_MEAN": {"formula": "MEAN(RED_OR_SECOND_YELLOW_SCIENTIFIC_FACT_COUNT_PER_PRIOR_FIXTURE)", "windows": list(WINDOWS), "minimum_history": {"fixed_windows": "EXACT_N", "season_to_date": 3}, "operator": "GT_0_FIXED", "second_yellow_policy": "COUNTS_AS_YELLOW_AND_DISMISSAL", "unknown_policy": "UNKNOWN_ON_MISSING_INVALID_OR_UNCLASSIFIABLE_CARD_DETAIL"},
    "LAST_PRIOR_FORMATION": {"formula": "FORMATION_OF_IMMEDIATELY_PRECEDING_ADMISSIBLE_FIXTURE_NO_SKIP_BACK", "window": "LAST1", "categories": [value.replace("_", "-") for value in FORMATIONS], "known_other_policy": "ALL_SELECTED_CATEGORY_TAGS_FALSE", "unknown_policy": "ALL_TAGS_UNKNOWN_IF_MISSING_OR_AMBIGUOUS"},
    "AFTER_RESULT_POINTS_PER_MATCH": {"formula": "MEAN(POINTS_OF_DESTINATION_MATCH_FOR_CONSECUTIVE_PRIOR_TRANSITIONS_WHERE_SOURCE_RESULT_EQUALS_CATEGORY)", "categories": list(RESULTS), "minimum_transition_count": 3, "latest_prior_gate": "CATEGORY_MISMATCH_IS_FALSE;CATEGORY_MATCH_WITH_LOW_SUPPORT_IS_UNKNOWN", "target_transition_forbidden": True, "unknown_policy": "NO_BRIDGE_ACROSS_UNKNOWN_MATCH"},
    "SAME_ORIENTATION_POINTS_PER_MATCH": {"formula": "MEAN(PRIOR_POINTS_WHERE_PRIOR_SIDE_EQUALS_TARGET_SIDE)", "windows": list(WINDOWS), "minimum_history": {"fixed_windows": "EXACT_N", "season_to_date": 3}, "unknown_policy": "UNKNOWN_IF_REQUIRED_HISTORY_INCOMPLETE"},
    "RECONSTRUCTED_TABLE_STRENGTH_PERCENTILE": {"formula": "ONE_MINUS_MIDRANK_MINUS_ONE_OVER_N_MINUS_ONE", "ranking_keys": ["POINTS_DESC", "GOAL_DIFFERENCE_DESC", "GOALS_FOR_DESC"], "residual_tie_policy": "SHARED_MIDRANK_NEVER_PROVIDER_ID", "participant_universe": "TEAMS_SEEN_BEFORE_CUTOFF", "minimum_team_matches": 3, "minimum_participants": 2, "same_kickoff_excluded": True},
    "CURRENT_RESULT_STREAK": {"formula": "CONSECUTIVE_CATEGORY_RESULT_COUNT_ENDING_AT_LATEST_PRIOR_ADMISSIBLE_FIXTURE", "categories": list(RESULTS), "threshold": 2, "unknown_policy": "UNKNOWN_IF_NO_PRIOR_HISTORY"},
    "WEIGHTED_POINTS_HALF_LIFE_5": {"formula": "SUM(POINTS_I*2**(-AGE_I/5))/SUM(2**(-AGE_I/5))", "age_unit": "MATCH_ORDINAL_NEWEST_ZERO", "half_life": 5, "windows": list(WINDOWS), "minimum_history": {"fixed_windows": "EXACT_N", "season_to_date": 3}, "unknown_policy": "UNKNOWN_IF_REQUIRED_HISTORY_INCOMPLETE"},
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def object_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def v2_source_field_registry() -> dict[str, dict[str, str]]:
    return {
        f"field:{object_hash(spec)}": dict(spec)
        for _, spec in sorted(FIELD_SPECS.items())
    }


def source_field_ids(paths: list[str]) -> list[str]:
    result: list[str] = []
    for path in paths:
        if path not in FIELD_SPECS:
            raise RuntimeError(f"V2_SOURCE_FIELD_PATH_UNREGISTERED:{path}")
        result.append(f"field:{object_hash(FIELD_SPECS[path])}")
    return result


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        canonical_bytes(value)
        if compact
        else json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    )
    path.write_bytes(payload + b"\n")


def property_row(
    property_id: str,
    *,
    disposition: str,
    raw_role: str,
    tag_count: int,
    source_fields: list[str],
    transform_ids: list[str],
    previous_defer_reason: str | None = None,
    block_reason: str | None = None,
) -> dict[str, Any]:
    family = property_id.split(":")[1]
    return {
        "property_id": property_id,
        "family": family,
        "disposition": disposition,
        "raw_scientific_role": raw_role,
        "transform_scientific_role": (
            "PREDICTOR_ELIGIBLE_HISTORICAL_LAGGED"
            if disposition in {"SELECTED_V1", "SELECTED_V2"}
            else "NOT_MATERIALIZED_V2"
        ),
        "proof_ceiling": "HISTORICAL_RECONSTRUCTED_ONLY",
        "strict_point_in_time": False,
        "provider_known_at_provenance": False,
        "grain": "one team orientation in one target fixture",
        "source_fields": source_fields,
        "transform_ids": transform_ids,
        "tag_count": tag_count,
        "cutoff": "PRIOR_FIXTURE_AVAILABLE_PROXY_AT_STRICTLY_BEFORE_TARGET_KICKOFF",
        "source_embargo": "PT6H_AFTER_PRIOR_FIXTURE_KICKOFF",
        "unknown_policy": "UNKNOWN_IF_REQUIRED_HISTORY_SOURCE_OR_CLASSIFICATION_INCOMPLETE",
        "previous_defer_reason": previous_defer_reason,
        "block_reason": block_reason,
    }


def properties() -> list[dict[str, Any]]:
    score = source_field_ids(["fixture.date", "fixture.status.short", "score.fulltime.home", "score.fulltime.away", "teams.home.id", "teams.away.id"])
    events = source_field_ids(["fixture_event.data.type", "fixture_event.data.detail", "fixture_event.data.time.elapsed", "fixture_event.data.time.extra", "fixture_event.data.team.id", "fixture_event.data.player.id", "fixture_event.data.assist.id", "fixture_event.data.comments"])
    rows = [
        property_row("football:attack:goals_scored", disposition="SELECTED_V1", raw_role="TARGET_ONLY_POST_RESULT", tag_count=16, source_fields=score, transform_ids=["PRIOR_FAILED_TO_SCORE_RATE", "PRIOR_GOALS_FOR_MEAN"]),
        property_row("football:defence:goals_conceded", disposition="SELECTED_V1", raw_role="TARGET_ONLY_POST_RESULT", tag_count=16, source_fields=score, transform_ids=["PRIOR_CLEAN_SHEET_RATE", "PRIOR_GOALS_AGAINST_MEAN"]),
        property_row("football:discipline_referee:recent_cards", disposition="SELECTED_V1", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=events, transform_ids=["PRIOR_GENERIC_CARD_MEAN"]),
        property_row("football:strength_form:form", disposition="SELECTED_V1", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=16, source_fields=score, transform_ids=["PRIOR_WIN_RATE", "PRIOR_DRAW_RATE"]),
        property_row("football:strength_form:goals", disposition="SELECTED_V1", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=score, transform_ids=["PRIOR_TOTAL_GOALS_MEAN"]),
        property_row("football:strength_form:points", disposition="SELECTED_V1", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=score, transform_ids=["PRIOR_POINTS_PER_MATCH"]),
        property_row("football:strength_form:volatility", disposition="SELECTED_V1", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=score, transform_ids=["PRIOR_POINTS_STDDEV"]),
        property_row("football:coach:substitutions", disposition="SELECTED_V2", raw_role="TARGET_ONLY_POST_RESULT", tag_count=8, source_fields=events, transform_ids=["PRIOR_SUBSTITUTIONS_MEAN"], previous_defer_reason="FORMULA_AND_DURABLE_SOURCE_NOT_FROZEN_V1"),
        property_row("football:discipline_referee:yellow_cards", disposition="SELECTED_V2", raw_role="TARGET_ONLY_POST_RESULT", tag_count=8, source_fields=events, transform_ids=["PRIOR_YELLOW_CARDS_MEAN"], previous_defer_reason="COLOURED_CARD_SOURCE_AUTHORITY_NOT_FROZEN_V1"),
        property_row("football:discipline_referee:red_cards", disposition="SELECTED_V2", raw_role="TARGET_ONLY_POST_RESULT", tag_count=8, source_fields=events, transform_ids=["PRIOR_DISMISSALS_MEAN"], previous_defer_reason="COLOURED_CARD_SOURCE_AUTHORITY_NOT_FROZEN_V1"),
        property_row("football:formation_structure:formation", disposition="SELECTED_V2", raw_role="RECONSTRUCTED_POST_MATCH", tag_count=16, source_fields=source_field_ids(["formation.data.formation"]), transform_ids=["LAST_PRIOR_FORMATION"], previous_defer_reason="FORMATION_ONTOLOGY_NOT_FROZEN_V1"),
        property_row("football:strength_form:after_result_performance", disposition="SELECTED_V2", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=6, source_fields=score, transform_ids=["AFTER_RESULT_POINTS_PER_MATCH"], previous_defer_reason="TRANSITION_FORMULA_NOT_FROZEN_V1"),
        property_row("football:strength_form:home_away_performance", disposition="SELECTED_V2", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=score, transform_ids=["SAME_ORIENTATION_POINTS_PER_MATCH"], previous_defer_reason="ORIENTATION_FORMULA_NOT_FROZEN_V1"),
        property_row("football:strength_form:ranking", disposition="SELECTED_V2", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=2, source_fields=score, transform_ids=["RECONSTRUCTED_TABLE_STRENGTH_PERCENTILE"], previous_defer_reason="RANKING_FORMULA_NOT_FROZEN_V1"),
        property_row("football:strength_form:streak", disposition="SELECTED_V2", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=6, source_fields=score, transform_ids=["CURRENT_RESULT_STREAK"], previous_defer_reason="STREAK_FORMULA_NOT_FROZEN_V1"),
        property_row("football:strength_form:weighted_form", disposition="SELECTED_V2", raw_role="LAGGED_RECONSTRUCTED_ONLY", tag_count=8, source_fields=score, transform_ids=["WEIGHTED_POINTS_HALF_LIFE_5"], previous_defer_reason="WEIGHTING_FORMULA_NOT_FROZEN_V1"),
    ]
    blocked = {
        "football:match_competition:matchday": "BLOCKED_BY_TEMPORALITY_NO_REVISION_KNOWN_AT",
        "football:match_competition:month": "BLOCKED_BY_TEMPORALITY_NO_REVISION_KNOWN_AT",
        "football:match_competition:round": "BLOCKED_BY_TEMPORALITY_NO_REVISION_KNOWN_AT",
        "football:match_competition:season": "RECONSTRUCTED_CONTEXT_CONSTANT_NOT_PREDICTOR",
        "football:match_competition:venue_role": "IDENTITY_ORIENTATION_ALREADY_ENCODED",
        "football:match_competition:weekday": "BLOCKED_BY_TEMPORALITY_NO_REVISION_KNOWN_AT",
        "football:player:assists": "BLOCKED_BY_GRAIN_NO_PLAYER_POPULATION_AT_CUTOFF",
        "football:player:cards": "BLOCKED_BY_GRAIN_NO_PLAYER_POPULATION_AT_CUTOFF",
        "football:player:goals": "BLOCKED_BY_GRAIN_NO_PLAYER_POPULATION_AT_CUTOFF",
    }
    for property_id, reason in blocked.items():
        rows.append(property_row(property_id, disposition="BLOCKED_V2", raw_role="TARGET_ONLY_OR_RECONSTRUCTED_CONTEXT", tag_count=0, source_fields=[], transform_ids=[], previous_defer_reason="DEFERRED_PUBLIC_ELIGIBLE_NOT_TESTED_V1", block_reason=reason))
    return sorted(rows, key=lambda row: str(row["property_id"]))


def new_tag(
    *, tag_id: str, property_id: str, family: str, side: str, metric: str,
    window: str, operator: str, threshold_origin: str, unit: str,
    transform_id: str, source_fields: list[str], category_value: str | None = None,
) -> dict[str, Any]:
    if transform_id not in TRANSFORM_SPECS:
        raise RuntimeError(f"V2_TRANSFORM_SPEC_REQUIRED:{transform_id}")
    if family in {"COACH", "DISCIPLINE_REFEREE"}:
        mapping_basis = "DETERMINISTIC_PRIOR_EVENT_TRANSFORM"
        raw_role = "TARGET_ONLY_POST_RESULT"
        required_capabilities = ["EVENTS"]
    elif family == "FORMATION_STRUCTURE":
        mapping_basis = "DETERMINISTIC_PRIOR_FORMATION_TRANSFORM"
        raw_role = "RECONSTRUCTED_POST_MATCH"
        required_capabilities = ["FORMATION"]
    else:
        mapping_basis = "DETERMINISTIC_PRIOR_RESULT_TRANSFORM"
        raw_role = "LAGGED_RECONSTRUCTED_ONLY"
        required_capabilities = ["TEAM"]
    definition: dict[str, Any] = {
        "cutoff": "TARGET_KICKOFF_EXCLUSIVE_WITH_PT6H_SOURCE_EMBARGO",
        "entity_scope": f"TEAM_{side}",
        "family": family,
        "grain": "one team orientation in one target fixture",
        "label_fr": tag_id,
        "mapping_basis": mapping_basis,
        "market_compatibility": ["MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M"],
        "metric": metric,
        "operator": operator,
        "orientation": side,
        "property_id": property_id,
        "required_capabilities": required_capabilities,
        "scientific_role": "FOOTBALL_PREDICTOR",
        "source_fields": source_fields,
        "status": "MATERIALIZABLE_RECONSTRUCTED",
        "subfamily": metric.upper(),
        "tag_id": tag_id,
        "tag_version": 2,
        "temporal_class": "LAGGED_RECONSTRUCTED_ONLY",
        "temporal_window": window,
        "threshold": 0 if threshold_origin == "FIXED_ZERO" else (2 if threshold_origin == "FIXED_TWO" else None),
        "threshold_origin": threshold_origin,
        "transform_id": transform_id,
        "transform_spec_hash": object_hash(TRANSFORM_SPECS[transform_id]),
        "unit": unit,
        "unknown_policy": "UNKNOWN_IF_REQUIRED_HISTORY_SOURCE_OR_CLASSIFICATION_INCOMPLETE",
        "raw_scientific_role": raw_role,
        "transform_scientific_role": "PREDICTOR_ELIGIBLE_HISTORICAL_LAGGED",
        "proof_ceiling": "HISTORICAL_RECONSTRUCTED_ONLY",
        "category_value": category_value,
    }
    definition_hash = object_hash(definition)
    return {
        **definition,
        "definition_hash": definition_hash,
        "feature_id": f"feature:{object_hash({'definition_hash': definition_hash})}",
    }


def new_tags() -> list[dict[str, Any]]:
    event_fields = source_field_ids(["fixture_event.data.type", "fixture_event.data.detail", "fixture_event.data.time.elapsed", "fixture_event.data.time.extra", "fixture_event.data.team.id", "fixture_event.data.player.id", "fixture_event.data.assist.id", "fixture_event.data.comments"])
    score_fields = source_field_ids(["fixture.date", "fixture.status.short", "score.fulltime.home", "score.fulltime.away", "teams.home.id", "teams.away.id"])
    rows: list[dict[str, Any]] = []
    for side in SIDES:
        for window in WINDOWS:
            rows.append(new_tag(tag_id=f"TEAM_{side}.COACH.SUBSTITUTIONS_MEAN.{window}.HIGH_Q67.V2", property_id="football:coach:substitutions", family="COACH", side=side, metric="substitutions_mean", window=window, operator="GTE", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="COUNT_PER_FIXTURE", transform_id="PRIOR_SUBSTITUTIONS_MEAN", source_fields=event_fields))
            rows.append(new_tag(tag_id=f"TEAM_{side}.DISCIPLINE_REFEREE.YELLOW_CARDS_MEAN.{window}.HIGH_Q67.V2", property_id="football:discipline_referee:yellow_cards", family="DISCIPLINE_REFEREE", side=side, metric="yellow_cards_mean", window=window, operator="GTE", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="COUNT_PER_FIXTURE", transform_id="PRIOR_YELLOW_CARDS_MEAN", source_fields=event_fields))
            rows.append(new_tag(tag_id=f"TEAM_{side}.DISCIPLINE_REFEREE.DISMISSALS_MEAN.{window}.GT_0.V2", property_id="football:discipline_referee:red_cards", family="DISCIPLINE_REFEREE", side=side, metric="dismissals_mean", window=window, operator="GT", threshold_origin="FIXED_ZERO", unit="COUNT_PER_FIXTURE", transform_id="PRIOR_DISMISSALS_MEAN", source_fields=event_fields))
            rows.append(new_tag(tag_id=f"TEAM_{side}.STRENGTH_FORM.SAME_ORIENTATION_POINTS_PER_MATCH.{window}.HIGH_Q67.V2", property_id="football:strength_form:home_away_performance", family="STRENGTH_FORM", side=side, metric="same_orientation_points_per_match", window=window, operator="GTE", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="POINTS_PER_MATCH", transform_id="SAME_ORIENTATION_POINTS_PER_MATCH", source_fields=score_fields))
            rows.append(new_tag(tag_id=f"TEAM_{side}.STRENGTH_FORM.WEIGHTED_POINTS_HL5.{window}.HIGH_Q67.V2", property_id="football:strength_form:weighted_form", family="STRENGTH_FORM", side=side, metric="weighted_points_hl5", window=window, operator="GTE", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="POINTS_PER_MATCH", transform_id="WEIGHTED_POINTS_HALF_LIFE_5", source_fields=score_fields))
        for formation in FORMATIONS:
            rows.append(new_tag(tag_id=f"TEAM_{side}.FORMATION_STRUCTURE.LAST_PRIOR_FORMATION.LAST1.EQ_F_{formation}.V2", property_id="football:formation_structure:formation", family="FORMATION_STRUCTURE", side=side, metric="last_prior_formation", window="LAST1", operator="EQ", threshold_origin="ONTOLOGY_FIXED", unit="CATEGORY", transform_id="LAST_PRIOR_FORMATION", source_fields=source_field_ids(["formation.data.formation"]), category_value=formation.replace("_", "-")))
        for result in RESULTS:
            rows.append(new_tag(tag_id=f"TEAM_{side}.STRENGTH_FORM.AFTER_{result}_POINTS_PER_MATCH.STD_MIN3_TRANSITIONS.HIGH_Q67.V2", property_id="football:strength_form:after_result_performance", family="STRENGTH_FORM", side=side, metric=f"after_{result.casefold()}_points_per_match", window="STD_MIN3_TRANSITIONS", operator="GTE_IF_LATEST_PRIOR_OUTCOME_MATCHES", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="POINTS_PER_MATCH", transform_id="AFTER_RESULT_POINTS_PER_MATCH", source_fields=score_fields, category_value=result))
            rows.append(new_tag(tag_id=f"TEAM_{side}.STRENGTH_FORM.CURRENT_{result}_STREAK.CURRENT.GTE_2.V2", property_id="football:strength_form:streak", family="STRENGTH_FORM", side=side, metric=f"current_{result.casefold()}_streak", window="CURRENT", operator="GTE", threshold_origin="FIXED_TWO", unit="FIXTURES", transform_id="CURRENT_RESULT_STREAK", source_fields=score_fields, category_value=result))
        rows.append(new_tag(tag_id=f"TEAM_{side}.STRENGTH_FORM.RECONSTRUCTED_TABLE_STRENGTH_PERCENTILE.SEASON_TO_DATE.HIGH_Q67.V2", property_id="football:strength_form:ranking", family="STRENGTH_FORM", side=side, metric="reconstructed_table_strength_percentile", window="SEASON_TO_DATE", operator="GTE", threshold_origin="TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD", unit="PERCENTILE", transform_id="RECONSTRUCTED_TABLE_STRENGTH_PERCENTILE", source_fields=score_fields))
    rows.sort(key=lambda row: str(row["tag_id"]))
    if len(rows) != 70 or len({row["tag_id"] for row in rows}) != 70:
        raise RuntimeError("V2_NEW_TAG_COUNT_MISMATCH")
    if {len(str(row["tag_id"]).split(".")) for row in rows} != {6}:
        raise RuntimeError("V2_TAG_SEGMENT_COUNT_MISMATCH")
    return rows


def main() -> None:
    v1 = read_json(V1_REGISTRY)
    legacy = v1.get("tags")
    if not isinstance(legacy, list) or len(legacy) != 80:
        raise RuntimeError("V1_TAGS_REQUIRED")
    property_rows = properties()
    selected = [row for row in property_rows if row["disposition"] in {"SELECTED_V1", "SELECTED_V2"}]
    if len(property_rows) != 25 or len(selected) != 16 or sum(int(row["tag_count"]) for row in selected) != 150:
        raise RuntimeError("V2_PROPERTY_SCOPE_MISMATCH")
    contract = {
        "schema_version": "predictor-property-contract-v2", "frozen_at": FROZEN_AT,
        "contract_scope": "TARGET_BLIND_HISTORICAL_RECONSTRUCTED_ONLY",
        "candidate_property_count": 25, "selected_property_count": 16,
        "selected_v1_property_count": 7, "selected_v2_property_count": 9,
        "blocked_candidate_count": 9, "strict_property_count": 0,
        "point_in_time_source_provenance": False, "target_kickoff_exclusive": True,
        "source_embargo": "PT6H",
        "transform_registry": TRANSFORM_SPECS,
        "transform_registry_hash": object_hash(TRANSFORM_SPECS),
        "properties": property_rows,
    }
    contract["contract_hash"] = object_hash(contract)
    tags = [dict(row) for row in legacy] + new_tags()
    tags.sort(key=lambda row: str(row["tag_id"]))
    if len(tags) != 150 or len({str(row["tag_id"]) for row in tags}) != 150:
        raise RuntimeError("V2_CUMULATIVE_TAG_COUNT_MISMATCH")
    if Counter(str(row["property_id"]) for row in tags) != Counter({str(row["property_id"]): int(row["tag_count"]) for row in selected}):
        raise RuntimeError("V2_PROPERTY_TAG_DISTRIBUTION_MISMATCH")
    source_registry = dict(v1["source_field_registry"])
    source_registry.update(v2_source_field_registry())
    unresolved = {
        str(field_id)
        for row in tags
        if int(row.get("tag_version", 0)) == 2
        for field_id in row["source_fields"]
        if field_id not in source_registry
    }
    if unresolved:
        raise RuntimeError(f"V2_SOURCE_FIELD_FOREIGN_KEY_MISMATCH:{sorted(unresolved)}")
    registry = {
        "schema_version": "canonical-tag-registry-v2", "generated_at": FROZEN_AT,
        "registry_scope": "CUMULATIVE_TARGET_BLIND_HISTORICAL_RECONSTRUCTED_ONLY",
        "legacy_registry_hash": v1["registry_hash"], "legacy_tag_count": 80,
        "new_tag_count": 70, "tag_count": 150, "strict_tag_count": 0,
        "property_contract_hash": contract["contract_hash"],
        "canonical_targets": list(v1["canonical_targets"]),
        "target_views": list(v1["target_views"]),
        "source_field_registry": source_registry,
        "source_field_registry_hash": object_hash(source_registry),
        "transform_registry_hash": contract["transform_registry_hash"],
        "tags": tags,
    }
    registry["registry_hash"] = object_hash(tags)
    report = {
        "schema_version": "predictor-eligible-property-set-v2", "frozen_at": FROZEN_AT,
        "genome_property_count": 486, "genome_family_count": 28,
        "reconciliation": {"READY": 46, "PARTIAL": 46, "BLOCKED": 344, "UNKNOWN": 50},
        "candidate_property_count": 25, "selected_property_count": 16,
        "selected_v1_property_count": 7, "selected_v2_property_count": 9,
        "blocked_candidate_count": 9, "cumulative_tag_count": 150,
        "atomic_test_count": 300, "theoretical_tag_pair_count": 11175,
        "strict_property_count": 0, "point_in_time_source_provenance": False,
        "property_contract_hash": contract["contract_hash"],
        "records": property_rows,
    }
    report["property_set_hash"] = object_hash(property_rows)
    write_json(PROPERTY_CONTRACT, contract)
    write_json(V2_REGISTRY, registry, compact=True)
    write_json(PROPERTY_REPORT, report)


if __name__ == "__main__":
    main()
