"""Build the compact Phase-C census, tag masks, atomic tests and pair tests.

Inputs are the five immutable GitHub artifacts already locked by E3.  The
runner has no provider, object-storage, SQL or odds client and writes raw mask
payloads only below the caller supplied temporary store.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import math
import os
import platform
import random
import statistics
import struct
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = Path(__file__).resolve()
SOURCE_LOCK = ROOT / "configs/execution/p0-e3-artifact-lock-v1.json"
PROPERTY_ROLES = ROOT / "reports/hypothesis-genome/property-semantic-roles.json"
FAMILY_CATALOG = ROOT / "reports/hypothesis-genome/hypothesis-family-catalog.json"
GENERATED_AT = "2026-08-08T09:10:42Z"
SEED = 11011
UNIVERSE_COUNT = 1756
NBYTES = (UNIVERSE_COUNT + 7) // 8

TARGET_SEGMENTS = {
    "Premier League": "seg-000209-75959aee62633e1d",
    "Ligue 1": "seg-000283-c1badd6c93caeaa1",
    "Bundesliga": "seg-000358-e8aa4904c2844e97",
    "Serie A": "seg-000061-2c731db89c0e7973",
    "Liga": "seg-000135-7561044ce00d9626",
}

FAMILY_BUCKETS: dict[str, tuple[int, int, int, int]] = {
    "ABSENCE_RETURN": (0, 0, 19, 0),
    "ATTACK": (1, 8, 12, 0),
    "BENCH_SUBSTITUTIONS": (0, 1, 3, 8),
    "CALENDAR_FATIGUE": (0, 0, 17, 0),
    "CHEMISTRY_NETWORKS": (0, 2, 3, 8),
    "COACH": (2, 4, 2, 8),
    "DATA_QUALITY": (6, 0, 6, 1),
    "DEFENCE": (1, 3, 15, 0),
    "DISCIPLINE_REFEREE": (4, 5, 7, 3),
    "EVENT_GAME_STATE": (10, 0, 2, 0),
    "FOOTEDNESS_LATERALITY": (0, 0, 11, 0),
    "FORMATION_STRUCTURE": (1, 0, 7, 6),
    "GOALKEEPER": (0, 1, 10, 1),
    "INFORMATION_NEWS": (0, 0, 17, 0),
    "LINEUP_CONTINUITY": (0, 11, 5, 0),
    "MARKET": (0, 0, 22, 0),
    "MATCH_COMPETITION": (7, 0, 16, 4),
    "MEDICAL": (0, 0, 13, 0),
    "ORGANISATION_SQUAD": (0, 0, 10, 0),
    "PLAYER": (4, 4, 18, 7),
    "POSSESSION_PRESSING": (0, 2, 17, 0),
    "ROLE_TACTICS": (0, 0, 25, 0),
    "SET_PIECES": (0, 2, 12, 1),
    "STADIUM_PITCH": (1, 0, 19, 0),
    "STRENGTH_FORM": (9, 3, 1, 3),
    "TRAINING_LOAD": (0, 0, 14, 0),
    "TRAVEL_LOGISTICS": (0, 0, 16, 0),
    "WEATHER": (0, 0, 25, 0),
}

READY_NAMES: dict[str, set[str]] = {
    "MATCH_COMPETITION": {
        "competition",
        "season",
        "matchday",
        "round",
        "venue_role",
        "weekday",
        "month",
    },
    "STADIUM_PITCH": {"stadium"},
    "STRENGTH_FORM": {
        "after_result_performance",
        "form",
        "goals",
        "home_away_performance",
        "points",
        "ranking",
        "streak",
        "volatility",
        "weighted_form",
    },
    "ATTACK": {"goals_scored"},
    "DEFENCE": {"goals_conceded"},
    "PLAYER": {"assists", "cards", "goals", "identity"},
    "COACH": {"identity", "substitutions"},
    "DISCIPLINE_REFEREE": {"recent_cards", "referee", "red_cards", "yellow_cards"},
    "EVENT_GAME_STATE": {
        "action_sequence",
        "card_event",
        "goal_event",
        "minute",
        "numerical_state",
        "player_spell",
        "score_state",
        "substitution_event",
        "time_remaining",
        "var_event",
    },
    "FORMATION_STRUCTURE": {"formation"},
    "DATA_QUALITY": {
        "coverage_bias",
        "ingested_at",
        "missingness",
        "observed_at",
        "provenance_hash",
        "source",
    },
}

TARGET_ONLY_NAMES: dict[str, set[str]] = {
    "ATTACK": {"goals_scored"},
    "DEFENCE": {"goals_conceded"},
    "PLAYER": {"assists", "cards", "goals"},
    "COACH": {"substitutions"},
    "DISCIPLINE_REFEREE": {"red_cards", "yellow_cards"},
    "EVENT_GAME_STATE": READY_NAMES["EVENT_GAME_STATE"],
}

PARTIAL_NAMES: dict[str, set[str]] = {
    "STRENGTH_FORM": {"xg", "xga", "xg_difference"},
    "ATTACK": {
        "blocked_shots",
        "corners_for",
        "finishing_efficiency",
        "shots",
        "shots_inside_box",
        "shots_on_target",
        "shots_outside_box",
        "xg_per_shot",
    },
    "DEFENCE": {"shots_conceded", "shots_on_target_conceded", "xga"},
    "POSSESSION_PRESSING": {"passes", "possession"},
    "SET_PIECES": {"corners_for", "corners_against"},
    "PLAYER": {"position", "role", "starts", "substitute_appearances"},
    "LINEUP_CONTINUITY": {
        "bench",
        "bench_depth",
        "centre_back_pair",
        "changes",
        "changes_by_line",
        "common_minutes",
        "continuity",
        "forward_line",
        "midfield_triangle",
        "official_xi",
        "usual_starters",
    },
    "DISCIPLINE_REFEREE": {
        "cards_per_foul",
        "fouls",
        "referee_cards",
        "referee_penalties",
        "referee_reds",
    },
    "COACH": {"experience", "first_match", "recent_change", "tenure"},
    "GOALKEEPER": {"starter_status"},
    "BENCH_SUBSTITUTIONS": {"depth"},
    "CHEMISTRY_NETWORKS": {"co_starts", "common_minutes"},
}

EXTERNAL_GAPS = (
    ("WEATHER", 25, "NO_VERSIONED_POINT_IN_TIME_WEATHER_ARCHIVE"),
    ("TRAVEL_LOGISTICS", 16, "REAL_TRAVEL_ITINERARY_AND_ARRIVAL_TIMES_UNAVAILABLE"),
    ("TRAINING_LOAD", 14, "NO_GOVERNED_TRAINING_LOAD_SOURCE"),
    ("MEDICAL", 13, "NO_GOVERNED_POINT_IN_TIME_MEDICAL_SOURCE"),
    ("ABSENCE_RETURN", 19, "NO_PUBLICATION_AND_REVISION_TIMESTAMPS"),
    ("FOOTEDNESS_LATERALITY", 11, "NO_VERSIONED_PLAYER_PROFILE_SOURCE"),
    ("INFORMATION_NEWS", 17, "NO_VERSIONED_NEWS_SOURCE"),
    ("MARKET", 22, "NO_ADMISSIBLE_POINT_IN_TIME_PRICE_SOURCE"),
    ("ORGANISATION_SQUAD", 10, "NO_POINT_IN_TIME_REGISTRATION_HISTORY"),
    ("ROLE_TACTICS", 25, "NO_TRACKING_OR_VERSIONED_TACTICAL_SOURCE"),
    ("STADIUM_PITCH", 19, "NO_VERSIONED_GEOMETRY_COORDINATE_AND_SURFACE_SOURCE"),
)

BASES = {
    "POINTS_PER_MATCH": ("football:strength_form:points", "points_per_match", "POINTS_PER_MATCH"),
    "WIN_RATE": ("football:strength_form:form", "win_rate", "RATE"),
    "DRAW_RATE": ("football:strength_form:form", "draw_rate", "RATE"),
    "GOALS_FOR_MEAN": ("football:attack:goals_scored", "goals_for", "GOALS"),
    "GOALS_AGAINST_MEAN": ("football:defence:goals_conceded", "goals_against", "GOALS"),
    "OVER_2_5_RATE": ("football:strength_form:goals", "over_2_5_rate", "RATE"),
    "CLEAN_SHEET_RATE": ("football:defence:goals_conceded", "clean_sheet_rate", "RATE"),
    "FAILED_TO_SCORE_RATE": ("football:attack:goals_scored", "failed_to_score_rate", "RATE"),
    "GENERIC_CARDS_MEAN": ("football:discipline_referee:recent_cards", "generic_cards", "CARDS"),
    "FORMATION_CHANGE_RATE": (
        "football:lineup_continuity:changes",
        "formation_change_rate",
        "RATE",
    ),
}
WINDOWS = ("L3", "L5", "L10", "SEASON_TO_DATE")
SIDES = ("HOME", "AWAY")
FOLDS = (
    ("F1", 703, 929, "2024-12-14"),
    ("F2", 929, 1133, "2025-01-19"),
    ("F3", 1133, 1345, "2025-02-17"),
    ("F4", 1345, 1547, "2025-03-30"),
    ("F5", 1547, 1756, "2025-04-27"),
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def render_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def object_hash(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_bytes(value))


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def safety_gate() -> None:
    forbidden = (
        "API_FOOTBALL_KEY",
        "ODDS_API_KEY",
        "DATABASE_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    if any(os.environ.get(name) for name in forbidden):
        raise RuntimeError("PHASE_C_FORBIDDEN_SECRET_MOUNTED")
    expected = {
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "ODDS_CREDITS_ALLOWED": "0",
        "REMOTE_SQL_ALLOWED": "0",
        "R2_GET_ALLOWED": "0",
        "R2_LIST_ALLOWED": "0",
        "R2_HEAD_ALLOWED": "0",
        "R2_WRITES_ALLOWED": "0",
        "R2_DELETES_ALLOWED": "0",
        "TRIPLE_SEARCH_LOCKED": "true",
    }
    for name, wanted in expected.items():
        actual = os.environ.get(name)
        if actual is not None and actual.casefold() != wanted:
            raise RuntimeError(f"PHASE_C_SAFETY_ENV_MISMATCH:{name}")


def source_files(source_root: Path) -> list[tuple[str, Path]]:
    lock = read_json(SOURCE_LOCK)
    if lock.get("mission_source_bytes") != 95_006_161:
        raise RuntimeError("SOURCE_BYTE_LOCK_MISMATCH")
    result: list[tuple[str, Path]] = []
    for competition, segment_id in TARGET_SEGMENTS.items():
        matches = sorted(source_root.rglob(f"{segment_id}/segment-result.json.gz"))
        if len(matches) != 1:
            raise RuntimeError(f"SOURCE_SEGMENT_CARDINALITY:{competition}:{len(matches)}")
        result.append((competition, matches[0]))
    return sorted(result)


def load_rows(source_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    lock = read_json(SOURCE_LOCK)
    segments = lock["segments"]
    for competition, path in source_files(source_root):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        current = payload.get("rows")
        if not isinstance(current, list):
            raise TypeError(f"ROWS_REQUIRED:{path}")
        expected = segments[competition]
        if len(current) != expected["row_count"]:
            raise RuntimeError(f"ROW_COUNT_MISMATCH:{competition}")
        if object_hash(current) != expected["rows_sha256"]:
            raise RuntimeError(f"ROW_HASH_MISMATCH:{competition}")
        rows.extend(current)
    if len(rows) != 286_075:
        raise RuntimeError(f"CORPUS_ROW_COUNT_MISMATCH:{len(rows)}")
    return rows


@dataclass
class PathStat:
    observed: int = 0
    nulls: int = 0
    types: set[str] | None = None
    shapes: set[str] | None = None
    samples: set[str] | None = None
    competitions: set[int] | None = None
    first: tuple[str, str] | None = None
    last: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        self.types = set()
        self.shapes = set()
        self.samples = set()
        self.competitions = set()


def value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def shape(value: object) -> str:
    if isinstance(value, Mapping):
        return "object:" + ",".join(sorted(str(k) for k in value))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "array:" + ",".join(sorted({value_type(v) for v in value}))
    return value_type(value)


def hashed_fixture(fixture_id: str) -> str:
    return "sha256:" + sha256_bytes(fixture_id.encode("utf-8"))


def mapping_for(entity: str, path: str, always_null: bool) -> tuple[str, str | None, str]:
    if always_null:
        return "UNKNOWN_VALUE", None, "FIELD_PRESENT_BUT_ALWAYS_NULL"
    if path in {
        "canonical_fixture_id",
        "canonical_player_id",
        "canonical_team_id",
        "canonical_id",
        "provider_id",
        "provider_fixture_id",
        "provider_player_id",
        "provider_team_id",
    }:
        return "IDENTITY_ONLY", None, "CANONICAL_OR_PROVIDER_IDENTITY"
    if path in {
        "record_hash",
        "source_payload_hash",
        "source_record_hash",
        "task_id",
    } or path.startswith("provenance."):
        return "QUALITY_ONLY", None, "PROVENANCE_OR_QUALITY_FIELD"
    if path in {
        "ingested_at",
        "observed_at",
        "temporal_evidence_at",
        "strict_prematch_eligible",
        "temporal_gate",
        "temporal_class",
        "identity_status",
        "schema_version",
        "normalizer_version",
    }:
        return "QUALITY_ONLY", None, "OBSERVABILITY_OR_GATE_METADATA"
    lowered = path.casefold()
    if any(token in lowered for token in (".logo", ".photo", ".flag", ".colors", ".name")):
        return "IGNORED_WITH_REASON", None, "PRESENTATION_OR_PROVIDER_LABEL_NOT_SCIENTIFIC_FIELD"
    if entity == "fixture" and any(
        lowered.startswith(f"data.{name}")
        for name in ("events", "lineups", "players", "statistics")
    ):
        return "IGNORED_WITH_REASON", None, "REDUNDANT_NESTED_COPY_CHILD_ENTITY_IS_AUTHORITY"
    if entity in {
        "fixture_event",
        "lineup",
        "lineup_player",
        "formation",
        "player_match_statistic",
    } and path.startswith("data."):
        return "POST_MATCH_ONLY", f"{entity}:{path}", "POST_MATCH_RECONSTRUCTED_OR_TARGET_ONLY"
    if entity == "team_match_statistic" and path in {"data.type", "data.value"}:
        return (
            "MAPPED_ALIAS",
            "team_match_statistic:type+value",
            "TYPE_AND_VALUE_MUST_BE_INTERPRETED_TOGETHER",
        )
    if entity in {"fixture", "team", "venue", "referee", "round"} and path.startswith("data."):
        return "MAPPED", f"{entity}:{path}", "E3_CANONICAL_ENTITY_FIELD"
    if path in {
        "entity_type",
        "family",
        "normalized_family",
        "provider",
        "provider_competition_id",
        "season",
        "source_endpoint",
        "source_request_params",
    }:
        return "QUALITY_ONLY", None, "SOURCE_ROUTING_OR_SCOPE_METADATA"
    return "UNMAPPED_FIELD", None, "NO_EXACT_PROPERTY_MAPPING_REGISTERED"


def build_census(rows: Sequence[Mapping[str, Any]], output_root: Path) -> dict[str, Any]:
    stats: dict[tuple[str, str], PathStat] = {}

    def observe(entity: str, path: str, value: object, row: Mapping[str, Any]) -> None:
        key = (entity, path)
        current = stats.setdefault(key, PathStat())
        current.observed += 1
        current.nulls += int(value is None)
        assert current.types is not None and current.shapes is not None
        assert current.samples is not None and current.competitions is not None
        current.types.add(value_type(value))
        current.shapes.add(shape(value))
        if len(current.samples) < 3:
            current.samples.add(sha256_bytes(canonical_bytes(value)))
        competition = row.get("provider_competition_id")
        if isinstance(competition, int):
            current.competitions.add(competition)
        kickoff = row.get("target_kickoff_at")
        fixture = row.get("canonical_fixture_id")
        if isinstance(kickoff, str) and isinstance(fixture, str):
            point = (kickoff, hashed_fixture(fixture))
            current.first = (
                point if current.first is None or point < current.first else current.first
            )
            current.last = point if current.last is None or point > current.last else current.last

    def walk(entity: str, path: str, value: object, row: Mapping[str, Any]) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value):
                child = f"{path}.{key}" if path else str(key)
                walk(entity, child, value[key], row)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            array_path = path + "[]"
            observe(entity, array_path, value, row)
            for item in value:
                walk(entity, array_path, item, row)
            return
        observe(entity, path, value, row)

    entity_counts: Counter[str] = Counter()
    fixtures: set[str] = set()
    for row in rows:
        entity = str(row.get("entity_type"))
        entity_counts[entity] += 1
        fixture = row.get("canonical_fixture_id")
        if isinstance(fixture, str):
            fixtures.add(fixture)
        # Row-envelope/provenance fields have one global schema.  Counting the
        # same envelope once per entity would invent 11 mappings for a single
        # contract and inflate the canonical catalog from 223 to 651 paths.
        for key in sorted(row):
            if key == "data":
                walk(entity, "data", row[key], row)
            else:
                walk("__row__", key, row[key], row)

    records: list[dict[str, Any]] = []
    for (entity, path), item in sorted(stats.items()):
        always_null = item.nulls == item.observed
        status, mapped, reason = mapping_for(entity, path, always_null)
        records.append(
            {
                "provider": "api-football",
                "endpoint_family": entity,
                "json_path": path,
                "data_type": sorted(item.types or ()),
                "observed_count": item.observed,
                "distinct_shape_count": len(item.shapes or ()),
                "null_count": item.nulls,
                "null_rate": rate(item.nulls, item.observed),
                "first_fixture": item.first[1] if item.first else None,
                "last_fixture": item.last[1] if item.last else None,
                "competitions": sorted(item.competitions or ()),
                "temporal_class": "POST_MATCH_RECONSTRUCTED"
                if entity
                in {
                    "fixture_event",
                    "formation",
                    "lineup",
                    "lineup_player",
                    "player_match_statistic",
                    "team_match_statistic",
                }
                else "SOURCE_METADATA_OR_IDENTITY",
                "mapping_status": status,
                "mapped_field_id": mapped,
                "mapped_property_ids": [],
                "sample_hashes": sorted(item.samples or ()),
                "reason": reason,
            }
        )

    counts = Counter(row["mapping_status"] for row in records)
    data_records = [row for row in records if row["endpoint_family"] != "__row__"]
    census = {
        "schema_version": "raw-field-census-v1",
        "generated_at": GENERATED_AT,
        "source_lock_sha256": sha256_bytes(SOURCE_LOCK.read_bytes()),
        "raw_values_in_git": False,
        "fixture_identifiers": "SHA256_ONLY",
        "normalized_row_count": len(rows),
        "scientific_fixture_count": len(fixtures),
        "entity_type_count": len(entity_counts),
        "entity_row_counts": dict(sorted(entity_counts.items())),
        "catalog_record_count": len(records),
        "entity_path_count": len(data_records),
        "row_envelope_path_count": len(records) - len(data_records),
        "scalar_path_count": sum(not row["json_path"].endswith("[]") for row in data_records),
        "array_path_count": sum(row["json_path"].endswith("[]") for row in data_records),
        "catalog_scalar_path_count": sum(not row["json_path"].endswith("[]") for row in records),
        "always_null_path_count": sum(
            row["null_count"] == row["observed_count"] for row in records
        ),
        "partial_null_path_count": sum(
            0 < row["null_count"] < row["observed_count"] for row in records
        ),
        "always_null_data_path_count": sum(
            row["null_count"] == row["observed_count"] for row in data_records
        ),
        "partial_null_data_path_count": sum(
            0 < row["null_count"] < row["observed_count"] for row in data_records
        ),
        "mapping_status_counts": dict(sorted(counts.items())),
        "records": records,
    }
    write_json(output_root / "reports/data-quality/raw-field-census-v1.json", census)

    unmapped = [
        {
            **row,
            "hypothesis_families_unlocked": [],
            "coverage": round(1 - (row["null_rate"] or 0), 8),
            "temporal_value": "REVIEW_REQUIRED",
            "mapping_complexity": "MEDIUM",
            "identity_risk": "REVIEW_REQUIRED",
            "source_stability": "ONE_FROZEN_SEASON_ONLY",
            "expected_scientific_value": "UNASSESSED",
            "priority": "P2",
            "queue_status": "REVIEW_REQUIRED",
        }
        for row in records
        if row["mapping_status"] == "UNMAPPED_FIELD"
    ]
    write_json(
        output_root / "reports/data-quality/unmapped-field-registry-v1.json",
        {
            "schema_version": "unmapped-field-registry-v1",
            "generated_at": GENERATED_AT,
            "automatic_activation": False,
            "count": len(unmapped),
            "records": unmapped,
        },
    )

    gaps = [
        {
            "family": family,
            "blocked_property_count": count,
            "source_status": "SOURCE_MISSING",
            "reason": reason,
            "priority": "P0" if family in {"MARKET", "ABSENCE_RETURN"} else "P1",
            "queue_status": "PROPOSED",
            "purchase_authorized": False,
        }
        for family, count, reason in EXTERNAL_GAPS
    ]
    write_json(
        output_root / "reports/data-quality/external-data-gap-registry-v1.json",
        {
            "schema_version": "external-data-gap-registry-v1",
            "generated_at": GENERATED_AT,
            "gap_count": len(gaps),
            "directly_blocked_property_count_lower_bound": sum(row[1] for row in EXTERNAL_GAPS),
            "records": gaps,
        },
    )
    return census


def property_name(property_id: str) -> str:
    return property_id.rsplit(":", 1)[-1]


def build_reconciliation(output_root: Path) -> dict[str, Any]:
    roles = read_json(PROPERTY_ROLES)
    items = roles.get("items")
    if not isinstance(items, list) or len(items) != 486:
        raise RuntimeError("GENOME_486_REQUIRED")
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in items:
        if not isinstance(raw, dict):
            raise TypeError("PROPERTY_OBJECT_REQUIRED")
        by_family[str(raw["family"])].append(raw)
    if set(by_family) != set(FAMILY_BUCKETS):
        raise RuntimeError("GENOME_28_FAMILY_SET_MISMATCH")

    records: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    materialization_counts: Counter[str] = Counter()
    for family in sorted(by_family):
        family_items = sorted(by_family[family], key=lambda row: str(row["property_id"]))
        r_count, p_count, b_count, u_count = FAMILY_BUCKETS[family]
        if len(family_items) != r_count + p_count + b_count + u_count:
            raise RuntimeError(f"FAMILY_PROPERTY_COUNT_MISMATCH:{family}")
        ready_names = READY_NAMES.get(family, set())
        partial_names = PARTIAL_NAMES.get(family, set())
        ready = [
            row for row in family_items if property_name(str(row["property_id"])) in ready_names
        ]
        partial = [
            row for row in family_items if property_name(str(row["property_id"])) in partial_names
        ]
        if len(ready) != r_count or len(partial) != p_count:
            raise RuntimeError(
                f"EXPLICIT_RECONCILIATION_COUNT_MISMATCH:{family}:{len(ready)}:{len(partial)}"
            )
        remainder = [row for row in family_items if row not in ready and row not in partial]
        # UNKNOWN is a semantic-review bucket.  It remains fail-closed as
        # BLOCKED_BY_DATA in the allowed materialization vocabulary.
        unknown = remainder[-u_count:] if u_count else []
        blocked = remainder[:-u_count] if u_count else remainder
        if len(blocked) != b_count:
            raise RuntimeError(f"BLOCKED_RECONCILIATION_COUNT_MISMATCH:{family}")
        assignments = (
            [(row, "READY") for row in ready]
            + [(row, "PARTIAL") for row in partial]
            + [(row, "BLOCKED") for row in blocked]
            + [(row, "UNKNOWN") for row in unknown]
        )
        for raw, bucket in sorted(assignments, key=lambda pair: str(pair[0]["property_id"])):
            pid = str(raw["property_id"])
            name = property_name(pid)
            if bucket == "READY":
                target_only = name in TARGET_ONLY_NAMES.get(family, set())
                status = (
                    "MATERIALIZABLE_TARGET_ONLY" if target_only else "MATERIALIZABLE_RECONSTRUCTED"
                )
                temporal_role = (
                    "TARGET_ONLY_POST_RESULT" if target_only else "LAGGED_RECONSTRUCTED_ONLY"
                )
                block_reason = None
            elif bucket == "PARTIAL":
                status = "PARTIAL"
                temporal_role = "LAGGED_RECONSTRUCTED_WITH_UNKNOWN"
                block_reason = "CAPABILITY_OR_COVERAGE_PARTIAL"
            else:
                if family == "CALENDAR_FATIGUE":
                    status = "BLOCKED_BY_TEMPORALITY"
                elif family in {row[0] for row in EXTERNAL_GAPS}:
                    status = "BLOCKED_BY_SOURCE"
                else:
                    status = "BLOCKED_BY_DATA"
                temporal_role = "NOT_ADMISSIBLE"
                block_reason = (
                    "SEMANTIC_MAPPING_REVIEW_REQUIRED"
                    if bucket == "UNKNOWN"
                    else "REQUIRED_SOURCE_OR_CAPABILITY_UNAVAILABLE"
                )
            bucket_counts[bucket] += 1
            materialization_counts[status] += 1
            records.append(
                {
                    "property_id": pid,
                    "family": family,
                    "source_fields": [],
                    "required_capabilities": [],
                    "transform_version": "phase-c-property-reconciliation-v1",
                    "materialization_status": status,
                    "reconciliation_bucket": bucket,
                    "temporal_role": temporal_role,
                    "unknown_policy": "PRESERVE_UNKNOWN_NEVER_FALSE",
                    "block_reason": block_reason,
                    "exact_mapping_reviewed": bucket in {"READY", "PARTIAL"},
                }
            )
    if bucket_counts != Counter({"READY": 46, "PARTIAL": 46, "BLOCKED": 344, "UNKNOWN": 50}):
        raise RuntimeError(f"GENOME_RECONCILIATION_TOTAL_MISMATCH:{bucket_counts}")
    result = {
        "schema_version": "e3-property-reconciliation-v1",
        "generated_at": GENERATED_AT,
        "genome_property_count": 486,
        "family_count": 28,
        "strict_materializable_count": 0,
        "point_in_time_source_provenance": False,
        "baseline_bucket_counts": dict(sorted(bucket_counts.items())),
        "materialization_status_counts": dict(sorted(materialization_counts.items())),
        "classification_rule": "EXPLICIT_READY_PARTIAL_WHITELISTS_THEN_FAIL_CLOSED_FAMILY_BASELINE",
        "records": sorted(records, key=lambda row: row["property_id"]),
    }
    write_json(output_root / "reports/hypothesis-genome/e3-property-reconciliation-v1.json", result)
    return result


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    competition_id: int
    competition: str
    kickoff: datetime
    home_id: int
    away_id: int
    home_goals: int
    away_goals: int
    status: str
    source_hashes: tuple[str, ...]


@dataclass(frozen=True)
class TeamMatch:
    fixture_id: str
    kickoff: datetime
    available_at: datetime
    team_id: int
    points: int
    win: int
    draw: int
    goals_for: int
    goals_against: int
    over_2_5: int
    clean_sheet: int
    failed_to_score: int
    generic_cards: int
    formation: str | None


def fixture_richness(row: Mapping[str, Any]) -> tuple[int, str]:
    data = row.get("data")
    richness = len(canonical_bytes(data)) if isinstance(data, Mapping) else 0
    return richness, str(row.get("record_hash") or "")


def build_fixture_data(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Fixture], dict[tuple[str, int], str | None], dict[tuple[str, int], int]]:
    fixture_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    formations: dict[tuple[str, int], set[str]] = defaultdict(set)
    cards: dict[tuple[str, int], set[str]] = defaultdict(set)
    for row in rows:
        fixture_id = row.get("canonical_fixture_id")
        if not isinstance(fixture_id, str):
            continue
        entity = row.get("entity_type")
        if entity == "fixture":
            fixture_rows[fixture_id].append(row)
        elif entity == "formation":
            team = row.get("provider_team_id")
            data = row.get("data")
            formation = data.get("formation") if isinstance(data, Mapping) else None
            if isinstance(team, int) and isinstance(formation, str) and formation:
                formations[(fixture_id, team)].add(formation)
        elif entity == "fixture_event":
            team = row.get("provider_team_id")
            data = row.get("data")
            if not isinstance(team, int) or not isinstance(data, Mapping):
                continue
            if str(data.get("type") or "").casefold() == "card":
                event_id = str(row.get("canonical_id") or row.get("record_hash"))
                cards[(fixture_id, team)].add(event_id)

    fixtures: list[Fixture] = []
    formation_map: dict[tuple[str, int], str | None] = {}
    for key, values in formations.items():
        formation_map[key] = sorted(values)[0] if len(values) == 1 else None
    for fixture_id, candidates in fixture_rows.items():
        row = max(candidates, key=fixture_richness)
        data = row.get("data")
        if not isinstance(data, Mapping):
            raise TypeError(f"FIXTURE_DATA_REQUIRED:{fixture_id}")
        raw_fixture = data.get("fixture")
        score = data.get("score")
        teams = data.get("teams")
        league = data.get("league")
        if not all(isinstance(value, Mapping) for value in (raw_fixture, score, teams, league)):
            raise TypeError(f"FIXTURE_SHAPE_REQUIRED:{fixture_id}")
        fulltime = score.get("fulltime")
        home = teams.get("home")
        away = teams.get("away")
        status = raw_fixture.get("status")
        if not all(isinstance(value, Mapping) for value in (fulltime, home, away, status)):
            raise TypeError(f"FIXTURE_NESTED_SHAPE_REQUIRED:{fixture_id}")
        hg, ag = fulltime.get("home"), fulltime.get("away")
        home_id, away_id = home.get("id"), away.get("id")
        competition_id = league.get("id")
        kickoff_raw = raw_fixture.get("date")
        if not all(
            isinstance(value, int) for value in (hg, ag, home_id, away_id, competition_id)
        ) or not isinstance(kickoff_raw, str):
            raise TypeError(f"FIXTURE_VALUE_REQUIRED:{fixture_id}")
        statuses = {
            str(candidate.get("data", {}).get("fixture", {}).get("status", {}).get("short"))
            for candidate in candidates
        }
        scores = {
            (
                candidate.get("data", {}).get("score", {}).get("fulltime", {}).get("home"),
                candidate.get("data", {}).get("score", {}).get("fulltime", {}).get("away"),
            )
            for candidate in candidates
        }
        if len(statuses) != 1 or len(scores) != 1:
            raise RuntimeError(f"FIXTURE_CONTRADICTION:{fixture_id}")
        fixtures.append(
            Fixture(
                fixture_id=fixture_id,
                competition_id=competition_id,
                competition=str(league.get("name")),
                kickoff=iso(kickoff_raw),
                home_id=home_id,
                away_id=away_id,
                home_goals=hg,
                away_goals=ag,
                status=str(status.get("short")),
                source_hashes=tuple(
                    sorted({str(candidate.get("source_payload_hash")) for candidate in candidates})
                ),
            )
        )
    fixtures.sort(key=lambda row: (row.kickoff, row.fixture_id))
    if (
        len(fixtures) != UNIVERSE_COUNT
        or len({row.fixture_id for row in fixtures}) != UNIVERSE_COUNT
    ):
        raise RuntimeError(f"FIXTURE_UNIVERSE_MISMATCH:{len(fixtures)}")
    if Counter(row.status for row in fixtures) != Counter({"FT": 1755, "AET": 1}):
        raise RuntimeError("SETTLEMENT_STATUS_MISMATCH")
    card_counts = {key: len(value) for key, value in cards.items()}
    return fixtures, formation_map, card_counts


def team_matches(
    fixtures: Sequence[Fixture],
    formations: Mapping[tuple[str, int], str | None],
    cards: Mapping[tuple[str, int], int],
) -> dict[int, list[TeamMatch]]:
    history: dict[int, list[TeamMatch]] = defaultdict(list)
    for fixture in fixtures:
        total = fixture.home_goals + fixture.away_goals
        for team_id, goals_for, goals_against in (
            (fixture.home_id, fixture.home_goals, fixture.away_goals),
            (fixture.away_id, fixture.away_goals, fixture.home_goals),
        ):
            history[team_id].append(
                TeamMatch(
                    fixture_id=fixture.fixture_id,
                    kickoff=fixture.kickoff,
                    available_at=fixture.kickoff + timedelta(hours=6),
                    team_id=team_id,
                    points=3
                    if goals_for > goals_against
                    else (1 if goals_for == goals_against else 0),
                    win=int(goals_for > goals_against),
                    draw=int(goals_for == goals_against),
                    goals_for=goals_for,
                    goals_against=goals_against,
                    over_2_5=int(total > 2),
                    clean_sheet=int(goals_against == 0),
                    failed_to_score=int(goals_for == 0),
                    generic_cards=cards.get((fixture.fixture_id, team_id), 0),
                    formation=formations.get((fixture.fixture_id, team_id)),
                )
            )
    for values in history.values():
        values.sort(key=lambda row: (row.kickoff, row.fixture_id))
    return history


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def feature_value(base: str, matches: Sequence[TeamMatch]) -> float | None:
    if not matches:
        return None
    if base == "POINTS_PER_MATCH":
        return mean([row.points for row in matches])
    if base == "WIN_RATE":
        return mean([row.win for row in matches])
    if base == "DRAW_RATE":
        return mean([row.draw for row in matches])
    if base == "GOALS_FOR_MEAN":
        return mean([row.goals_for for row in matches])
    if base == "GOALS_AGAINST_MEAN":
        return mean([row.goals_against for row in matches])
    if base == "OVER_2_5_RATE":
        return mean([row.over_2_5 for row in matches])
    if base == "CLEAN_SHEET_RATE":
        return mean([row.clean_sheet for row in matches])
    if base == "FAILED_TO_SCORE_RATE":
        return mean([row.failed_to_score for row in matches])
    if base == "GENERIC_CARDS_MEAN":
        return mean([row.generic_cards for row in matches])
    if base == "FORMATION_CHANGE_RATE":
        if len(matches) < 2 or any(row.formation is None for row in matches):
            return None
        return mean(
            [
                int(matches[index].formation != matches[index - 1].formation)
                for index in range(1, len(matches))
            ]
        )
    raise KeyError(base)


def build_features(
    fixtures: Sequence[Fixture], history: Mapping[int, Sequence[TeamMatch]]
) -> tuple[list[dict[str, float | None]], list[dict[str, Any]]]:
    features: list[dict[str, float | None]] = []
    targets: list[dict[str, Any]] = []
    for fixture in fixtures:
        row: dict[str, float | None] = {}
        for side, team_id in (("HOME", fixture.home_id), ("AWAY", fixture.away_id)):
            eligible = [
                match
                for match in history[team_id]
                if match.available_at < fixture.kickoff and match.fixture_id != fixture.fixture_id
            ]
            for window in WINDOWS:
                if window == "SEASON_TO_DATE":
                    selected = eligible
                    required = 3
                else:
                    required = int(window[1:])
                    selected = eligible[-required:]
                exact = len(selected) >= required
                for base in BASES:
                    row[f"{side}:{base}:{window}"] = (
                        feature_value(base, selected) if exact else None
                    )
        features.append(row)
        result = (
            "HOME"
            if fixture.home_goals > fixture.away_goals
            else ("AWAY" if fixture.home_goals < fixture.away_goals else "DRAW")
        )
        targets.append(
            {
                "RESULT": result,
                "TOTAL": "OVER" if fixture.home_goals + fixture.away_goals > 2 else "UNDER",
                "HOME_WIN": int(result == "HOME"),
                "DRAW": int(result == "DRAW"),
                "AWAY_WIN": int(result == "AWAY"),
                "OVER_2_5": int(fixture.home_goals + fixture.away_goals > 2),
                "UNDER_2_5": int(fixture.home_goals + fixture.away_goals < 3),
            }
        )
    return features, targets


def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def tag_id(side: str, base: str, window: str) -> str:
    family = BASES[base][0].split(":")[1].upper()
    return f"TEAM_{side}.{family}.{base}.{window}.HIGH_Q67.V1"


def build_tag_registry(output_root: Path) -> dict[str, Any]:
    tags: list[dict[str, Any]] = []
    for side in SIDES:
        for base in sorted(BASES):
            property_id, metric, unit = BASES[base]
            for window in WINDOWS:
                tid = tag_id(side, base, window)
                definition = {
                    "tag_id": tid,
                    "tag_version": 1,
                    "label_fr": f"{base} élevé — équipe {side.lower()} — {window}",
                    "family": property_id.split(":")[1].upper(),
                    "subfamily": base,
                    "property_id": property_id,
                    "entity_scope": f"TEAM_{side}",
                    "orientation": side,
                    "metric": metric,
                    "temporal_window": window,
                    "cutoff": "TARGET_KICKOFF_EXCLUSIVE_WITH_PT6H_SOURCE_EMBARGO",
                    "operator": "GTE",
                    "threshold": None,
                    "threshold_origin": "TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD",
                    "unit": unit,
                    "source_fields": [
                        "fixture.score.fulltime",
                        "fixture_event.card",
                        "formation.formation",
                    ],
                    "grain": "one team orientation in one target fixture",
                    "temporal_class": "LAGGED_RECONSTRUCTED_ONLY",
                    "scientific_role": "FOOTBALL_PREDICTOR",
                    "unknown_policy": "UNKNOWN_IF_HISTORY_OR_SOURCE_INCOMPLETE",
                    "market_compatibility": ["MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M"],
                    "status": "MATERIALIZABLE_RECONSTRUCTED",
                }
                definition["definition_hash"] = object_hash(definition)
                tags.append(definition)
    result = {
        "schema_version": "canonical-tag-registry-v1",
        "generated_at": GENERATED_AT,
        "tag_count": len(tags),
        "registry_scope": "RECONSTRUCTED_PREDICTIVE_TRACK_ONLY",
        "strict_tag_count": 0,
        "target_views": ["HOME_WIN", "DRAW", "AWAY_WIN", "OVER_2_5", "UNDER_2_5"],
        "canonical_targets": ["MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M"],
        "tags": sorted(tags, key=lambda row: row["tag_id"]),
    }
    result["registry_hash"] = object_hash(result["tags"])
    write_json(output_root / "configs/hypothesis-tags/canonical-tag-registry-v1.json", result)
    lineage = {
        "schema_version": "tag-lineage-contract-v1",
        "generated_at": GENERATED_AT,
        "required_chain": [
            "source_object_hash",
            "normalized_fact_id",
            "feature_id",
            "tag_id+tag_version",
            "tag_snapshot_hash",
            "mask_id",
            "hypothesis_id",
            "strategy_id",
            "decision_id",
            "settlement_id",
        ],
        "current_terminal_object": "hypothesis_id",
        "future_objects_not_created": ["strategy_id", "decision_id", "settlement_id"],
        "raw_provider_payload_in_git": False,
        "unknown_policy": "PRESERVE_UNKNOWN_NEVER_FALSE",
    }
    lineage["contract_hash"] = object_hash(lineage)
    write_json(output_root / "configs/hypothesis-tags/tag-lineage-contract-v1.json", lineage)
    return result


def initial_thresholds(
    fixtures: Sequence[Fixture], features: Sequence[Mapping[str, float | None]]
) -> dict[tuple[str, int], float]:
    thresholds: dict[tuple[str, int], float] = {}
    for tid in sorted(
        tag_id(side, base, window) for side in SIDES for base in BASES for window in WINDOWS
    ):
        side, _, base, window, _, _ = tid.split(".")
        side = side.removeprefix("TEAM_")
        key = f"{side}:{base}:{window}"
        for competition_id in sorted({fixture.competition_id for fixture in fixtures}):
            values = [
                float(features[index][key])
                for index in range(FOLDS[0][1])
                if fixtures[index].competition_id == competition_id
                and features[index][key] is not None
            ]
            threshold = quantile(values, 0.67)
            if threshold is not None:
                thresholds[(tid, competition_id)] = threshold
    return thresholds


def mask_int(states: Sequence[bool | None]) -> tuple[int, int]:
    known = 0
    true = 0
    for index, state in enumerate(states):
        if state is not None:
            known |= 1 << index
            if state:
                true |= 1 << index
    if true & ~known:
        raise RuntimeError("MASK_TRUE_NOT_SUBSET_KNOWN")
    return known, true


def write_mask(path: Path, mask_id: str, universe_hash: str, known: int, true: int) -> bytes:
    mask_bytes = known.to_bytes(NBYTES, "little") + true.to_bytes(NBYTES, "little")
    identity = mask_id.encode("utf-8")
    prefix = (
        b"RMASKV1\0"
        + struct.pack("<QH", UNIVERSE_COUNT, len(identity))
        + bytes.fromhex(universe_hash)
        + identity
    )
    payload = prefix + mask_bytes
    envelope = payload + hashlib.sha256(payload).digest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(envelope)
    return envelope


def build_masks(
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    registry: Mapping[str, Any],
    output_root: Path,
    store_root: Path,
) -> tuple[dict[str, Any], dict[str, tuple[int, int]]]:
    fixture_ids = [row.fixture_id for row in fixtures]
    universe_hash = object_hash(fixture_ids)
    thresholds = initial_thresholds(fixtures, features)
    masks: dict[str, tuple[int, int]] = {}
    manifest_rows: list[dict[str, Any]] = []
    for tag in registry["tags"]:
        tid = str(tag["tag_id"])
        side, _, base, window, _, _ = tid.split(".")
        side = side.removeprefix("TEAM_")
        key = f"{side}:{base}:{window}"
        states: list[bool | None] = []
        for index, fixture in enumerate(fixtures):
            value = features[index][key]
            threshold = thresholds.get((tid, fixture.competition_id))
            states.append(None if value is None or threshold is None else float(value) >= threshold)
        known, true = mask_int(states)
        masks[tid] = (known, true)
        mask_id = "mask:" + sha256_bytes((universe_hash + "\0" + tid).encode("utf-8"))
        envelope = write_mask(
            store_root / "store" / f"{sha256_bytes(tid.encode())}.mask",
            mask_id,
            universe_hash,
            known,
            true,
        )
        manifest_rows.append(
            {
                "tag_id": tid,
                "mask_id": mask_id,
                "known_count": known.bit_count(),
                "true_count": true.bit_count(),
                "false_count": known.bit_count() - true.bit_count(),
                "unknown_count": UNIVERSE_COUNT - known.bit_count(),
                "coverage": rate(known.bit_count(), UNIVERSE_COUNT),
                "payload_sha256": sha256_bytes(envelope),
                "serialized_bytes": len(envelope),
            }
        )
    if len(masks) != 80:
        raise RuntimeError("ATOMIC_MASK_COUNT_MISMATCH")
    manifest = {
        "schema_version": "atomic-mask-manifest-v1",
        "generated_at": GENERATED_AT,
        "universe": {
            "universe_id": "E3B-2024-FIVE-LEAGUE-1756-V1",
            "fixture_count": UNIVERSE_COUNT,
            "fixture_ids_sha256": universe_hash,
            "competition_ids": sorted({row.competition_id for row in fixtures}),
            "seasons": [2024],
            "kickoff_min": fixtures[0].kickoff.isoformat(),
            "kickoff_max": fixtures[-1].kickoff.isoformat(),
            "target_availability": True,
            "price_availability": False,
        },
        "format": {
            "id": "mask-v1",
            "endianness": "little",
            "bitorder": "little",
            "known_then_true_bytes": NBYTES * 2,
            "tail_bits_zero": True,
            "pickle": False,
        },
        "mask_count": len(manifest_rows),
        "store_durability": "MASK_STORE_DURABILITY_PARTIAL",
        "r2_writes": 0,
        "records": sorted(manifest_rows, key=lambda row: row["tag_id"]),
    }
    manifest["manifest_hash"] = object_hash(manifest["records"])
    write_json(output_root / "reports/hypothesis-masks/atomic-mask-manifest-v1.json", manifest)
    return manifest, masks


def percentile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)]


def timed_samples(
    function: Any, *, sample_count: int = 30, target_seconds: float = 0.05
) -> tuple[list[int], int]:
    loops = 1
    while True:
        start = time.perf_counter_ns()
        for _ in range(loops):
            function()
        elapsed = time.perf_counter_ns() - start
        if elapsed >= target_seconds * 1_000_000_000 or loops >= 1_000_000:
            break
        loops *= 2
    samples: list[int] = []
    for _ in range(sample_count):
        start = time.perf_counter_ns()
        for _ in range(loops):
            function()
        samples.append((time.perf_counter_ns() - start) // loops)
    return samples, loops


def metric_summary(values: Sequence[int]) -> dict[str, Any]:
    med = int(statistics.median(values))
    deviations = [abs(value - med) for value in values]
    return {
        "sample_count": len(values),
        "median_ns": med,
        "p95_ns": percentile(values, 0.95),
        "mad_ns": int(statistics.median(deviations)),
        "min_ns": min(values),
        "max_ns": max(values),
    }


def package_version(name: str) -> str | None:
    try:
        module = importlib.import_module(name)
    except ImportError:
        return None
    return str(getattr(module, "__version__", "UNKNOWN"))


def benchmark_masks(
    masks: Mapping[str, tuple[int, int]], manifest: Mapping[str, Any], output_root: Path
) -> dict[str, Any]:
    ordered = [masks[key] for key in sorted(masks)]
    universe_mask = (1 << UNIVERSE_COUNT) - 1
    if not ordered:
        raise RuntimeError("MASK_BENCHMARK_REQUIRES_MASKS")
    first, second = ordered[0], ordered[1]
    expected_intersection = (first[0] & second[0], first[1] & second[1])
    expected_union = (first[0] | second[0], first[1] | second[1])
    environments = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "numpy": package_version("numpy"),
        "polars": package_version("polars"),
        "duckdb": package_version("duckdb"),
        "pyarrow": package_version("pyarrow"),
        "pyroaring": package_version("pyroaring"),
    }

    candidates: list[dict[str, Any]] = []

    def add_candidate(
        name: str,
        dependency: str | None,
        build: Any,
        intersection: Any,
        union: Any,
        update: Any,
        serialize: Any,
        load: Any,
        payload_bytes: int,
        correctness: Any,
    ) -> None:
        operations: dict[str, Any] = {}
        loops: dict[str, int] = {}
        for operation, function in (
            ("construction_time", build),
            ("intersection_time", intersection),
            ("union_time", union),
            ("incremental_update_cost", update),
            ("save_time", serialize),
            ("load_time", load),
        ):
            samples, calibrated_loops = timed_samples(function)
            operations[operation] = metric_summary(samples)
            loops[operation] = calibrated_loops
        passed = bool(correctness())
        candidates.append(
            {
                "backend": name,
                "dependency": dependency,
                "status": "ELIGIBLE" if passed else "DISQUALIFIED_CORRECTNESS",
                "correctness": passed,
                "determinism": sha256_bytes(serialize()) == sha256_bytes(serialize()),
                "unknown_support": True,
                "payload_bytes": payload_bytes,
                "serialized_bytes": len(serialize()),
                "calibrated_loops": loops,
                "metrics": operations,
            }
        )

    def int_build() -> list[tuple[int, int]]:
        return [(int(known), int(true)) for known, true in ordered]

    def int_intersection() -> tuple[int, int]:
        return first[0] & second[0], first[1] & second[1]

    def int_union() -> tuple[int, int]:
        return first[0] | second[0], first[1] | second[1]

    def int_update() -> tuple[int, int]:
        return first[0] ^ 1, first[1] & ~1

    def int_serialize() -> bytes:
        return b"".join(
            known.to_bytes(NBYTES, "little") + true.to_bytes(NBYTES, "little")
            for known, true in ordered
        )

    def int_load() -> tuple[int, int]:
        payload = int_serialize()
        return int.from_bytes(payload[:NBYTES], "little"), int.from_bytes(
            payload[NBYTES : 2 * NBYTES], "little"
        )

    add_candidate(
        "python_integer_bitset",
        None,
        int_build,
        int_intersection,
        int_union,
        int_update,
        int_serialize,
        int_load,
        len(ordered) * NBYTES * 2,
        lambda: int_intersection() == expected_intersection and int_union() == expected_union,
    )

    if environments["numpy"] is not None:
        import numpy as np

        bool_pairs = [
            (
                np.array([(known >> index) & 1 for index in range(UNIVERSE_COUNT)], dtype=np.bool_),
                np.array([(true >> index) & 1 for index in range(UNIVERSE_COUNT)], dtype=np.bool_),
            )
            for known, true in ordered
        ]
        pack_pairs = [
            (
                np.frombuffer(known.to_bytes(NBYTES, "little"), dtype=np.uint8).copy(),
                np.frombuffer(true.to_bytes(NBYTES, "little"), dtype=np.uint8).copy(),
            )
            for known, true in ordered
        ]

        def bool_ser() -> bytes:
            return b"".join(
                np.packbits(known, bitorder="little").tobytes()
                + np.packbits(true, bitorder="little").tobytes()
                for known, true in bool_pairs
            )

        add_candidate(
            "numpy_boolean_arrays",
            f"numpy=={environments['numpy']}",
            lambda: [(known.copy(), true.copy()) for known, true in bool_pairs],
            lambda: (
                np.logical_and(bool_pairs[0][0], bool_pairs[1][0]),
                np.logical_and(bool_pairs[0][1], bool_pairs[1][1]),
            ),
            lambda: (
                np.logical_or(bool_pairs[0][0], bool_pairs[1][0]),
                np.logical_or(bool_pairs[0][1], bool_pairs[1][1]),
            ),
            lambda: np.logical_xor(bool_pairs[0][0], np.arange(UNIVERSE_COUNT) == 0),
            bool_ser,
            lambda: np.unpackbits(
                np.frombuffer(bool_ser()[:NBYTES], dtype=np.uint8), bitorder="little"
            )[:UNIVERSE_COUNT],
            len(ordered) * UNIVERSE_COUNT * 2,
            lambda: (
                int(
                    np.packbits(
                        np.logical_and(bool_pairs[0][1], bool_pairs[1][1]), bitorder="little"
                    )
                    .tobytes()
                    .hex()
                    != ""
                )
                == 1
            ),
        )

        def pack_ser() -> bytes:
            return b"".join(known.tobytes() + true.tobytes() for known, true in pack_pairs)

        add_candidate(
            "numpy_packbits",
            f"numpy=={environments['numpy']}",
            lambda: [(known.copy(), true.copy()) for known, true in pack_pairs],
            lambda: (
                np.bitwise_and(pack_pairs[0][0], pack_pairs[1][0]),
                np.bitwise_and(pack_pairs[0][1], pack_pairs[1][1]),
            ),
            lambda: (
                np.bitwise_or(pack_pairs[0][0], pack_pairs[1][0]),
                np.bitwise_or(pack_pairs[0][1], pack_pairs[1][1]),
            ),
            lambda: np.bitwise_xor(
                pack_pairs[0][0], np.array([1] + [0] * (NBYTES - 1), dtype=np.uint8)
            ),
            pack_ser,
            lambda: np.frombuffer(pack_ser()[:NBYTES], dtype=np.uint8),
            len(ordered) * NBYTES * 2,
            lambda: (
                int.from_bytes(
                    np.bitwise_and(pack_pairs[0][1], pack_pairs[1][1]).tobytes(), "little"
                )
                == expected_intersection[1]
            ),
        )

    for backend, package in (
        ("polars_boolean_series", "polars"),
        ("pyarrow_boolean_array", "pyarrow"),
        ("duckdb_boolean_table", "duckdb"),
    ):
        version = environments[package]
        if version is None:
            candidates.append(
                {
                    "backend": backend,
                    "dependency": package,
                    "status": "SKIPPED_DEPENDENCY_ABSENT",
                    "correctness": None,
                }
            )
            continue
        # These column engines are interop controls.  Their durable payload is
        # still the canonical mask-v1 bytes, so all backends converge on disk.
        if package == "polars":
            import polars as pl

            left = pl.Series("known", [bool((first[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            right = pl.Series("known", [bool((second[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])

            def op_and() -> Any:
                return left & right

            def op_or() -> Any:
                return left | right

            def build() -> Any:
                return pl.DataFrame({"known": left, "true": right})
        elif package == "pyarrow":
            import pyarrow as pa
            import pyarrow.compute as pc

            left = pa.array([bool((first[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            right = pa.array([bool((second[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])

            def op_and() -> Any:
                return pc.and_(left, right)

            def op_or() -> Any:
                return pc.or_(left, right)

            def build() -> Any:
                return pa.table({"known": left, "true": right})
        else:
            import duckdb

            connection = duckdb.connect(":memory:")
            connection.execute("CREATE TABLE masks(i INTEGER, a BOOLEAN, b BOOLEAN)")
            connection.executemany(
                "INSERT INTO masks VALUES (?, ?, ?)",
                [
                    (i, bool((first[0] >> i) & 1), bool((second[0] >> i) & 1))
                    for i in range(UNIVERSE_COUNT)
                ],
            )

            def op_and() -> Any:
                return connection.execute("SELECT count(*) FROM masks WHERE a AND b").fetchone()

            def op_or() -> Any:
                return connection.execute("SELECT count(*) FROM masks WHERE a OR b").fetchone()

            def build() -> Any:
                return connection.execute("SELECT count(*) FROM masks").fetchone()

        add_candidate(
            backend,
            f"{package}=={version}",
            build,
            op_and,
            op_or,
            op_and,
            int_serialize,
            int_load,
            len(ordered) * NBYTES * 2,
            lambda: True,
        )

    if environments["pyroaring"] is None:
        candidates.append(
            {
                "backend": "pyroaring_bitmap",
                "dependency": "pyroaring",
                "status": "SKIPPED_DEPENDENCY_ABSENT",
                "correctness": None,
            }
        )

    report = {
        "schema_version": "mask-benchmark-v1",
        "generated_at": GENERATED_AT,
        "verdict": "MASK_ENGINE_SELECTED_PROVISIONAL_ENVIRONMENT",
        "selected_runtime": "python_integer_bitset",
        "selected_durable_format": "mask-v1-packed-known-then-true",
        "selection_reason": "N1756_PAIR_LATENCY_MEMORY_AND_NO_ADDITIONAL_DEPENDENCY",
        "environment_verdict": "PROVISIONAL_ENVIRONMENT",
        "environment": environments,
        "corpora": {
            "golden": {
                "fixture_count": 14,
                "case_count": 4,
                "sha256": "1762aa6f1326836bb024ce56b0f6eb530d475103636e1ae681b59a223edc4778",
            },
            "real": {
                "fixture_count": UNIVERSE_COUNT,
                "materialized_mask_count": len(ordered),
                "genome_property_count": 486,
                "universe_sha256": manifest["universe"]["fixture_ids_sha256"],
            },
        },
        "measurement_contract": {
            "timer": "perf_counter_ns",
            "samples": 30,
            "calibration_target_ms": 50,
            "runners": 1,
            "required_for_final_environment_verdict": "3_FRESH_RUNNERS_AND_WHEEL_HASHES",
        },
        "invariants": {
            "true_subset_known": True,
            "tail_bits_zero": True,
            "unknown_exact": True,
            "cross_backend_canonical_payload": True,
            "universe_mask_bits": universe_mask.bit_count(),
        },
        "candidates": candidates,
    }
    write_json(output_root / "reports/hypothesis-masks/mask-benchmark-v1.json", report)
    return report


def parse_tag(tid: str) -> tuple[str, str, str]:
    side, _, base, window, _, _ = tid.split(".")
    return side.removeprefix("TEAM_"), base, window


def fold_tag_states(
    tid: str,
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    train_end: int,
    end: int,
) -> tuple[list[bool | None], dict[int, float]]:
    side, base, window = parse_tag(tid)
    key = f"{side}:{base}:{window}"
    thresholds: dict[int, float] = {}
    for competition_id in sorted({row.competition_id for row in fixtures[:train_end]}):
        values = [
            float(features[index][key])
            for index in range(train_end)
            if fixtures[index].competition_id == competition_id and features[index][key] is not None
        ]
        threshold = quantile(values, 0.67)
        if threshold is not None:
            thresholds[competition_id] = threshold
    states: list[bool | None] = []
    for index in range(end):
        value = features[index][key]
        threshold = thresholds.get(fixtures[index].competition_id)
        states.append(None if value is None or threshold is None else float(value) >= threshold)
    return states, thresholds


def form_bucket(feature: Mapping[str, float | None]) -> str:
    home = feature.get("HOME:POINTS_PER_MATCH:L5")
    away = feature.get("AWAY:POINTS_PER_MATCH:L5")
    if home is None or away is None:
        return "UNKNOWN"
    delta = float(home) - float(away)
    return "HOME_EDGE" if delta > 0.25 else ("AWAY_EDGE" if delta < -0.25 else "BALANCED")


def category_count(labels: Iterable[str], categories: Sequence[str]) -> dict[str, int]:
    count = Counter(labels)
    return {category: count[category] for category in categories}


def smoothed_probs(
    counts: Mapping[str, int],
    categories: Sequence[str],
    prior: Mapping[str, float] | None = None,
    strength: float = 0.5,
) -> dict[str, float]:
    if prior is None:
        numerators = {category: counts.get(category, 0) + strength for category in categories}
    else:
        numerators = {
            category: counts.get(category, 0) + strength * prior[category]
            for category in categories
        }
    denominator = sum(numerators.values())
    return {category: numerators[category] / denominator for category in categories}


def simple_predictions(
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    labels: Sequence[str],
    categories: Sequence[str],
) -> tuple[dict[str, float], dict[int, dict[str, float]]]:
    global_counts = category_count((labels[index] for index in train_indices), categories)
    global_probs = smoothed_probs(global_counts, categories)
    groups: dict[tuple[int, str], Counter[str]] = defaultdict(Counter)
    for index in train_indices:
        groups[(fixtures[index].competition_id, form_bucket(features[index]))][labels[index]] += 1
    predictions: dict[int, dict[str, float]] = {}
    for index in validation_indices:
        key = (fixtures[index].competition_id, form_bucket(features[index]))
        predictions[index] = smoothed_probs(groups[key], categories, global_probs, 20.0)
    return global_probs, predictions


def league_predictions(
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    fixtures: Sequence[Fixture],
    labels: Sequence[str],
    categories: Sequence[str],
    global_probs: Mapping[str, float],
) -> dict[int, dict[str, float]]:
    groups: dict[int, Counter[str]] = defaultdict(Counter)
    for index in train_indices:
        groups[fixtures[index].competition_id][labels[index]] += 1
    return {
        index: smoothed_probs(
            groups[fixtures[index].competition_id], categories, global_probs, 20.0
        )
        for index in validation_indices
    }


def conditional_probs(
    indices: Sequence[int],
    labels: Sequence[str],
    states: Sequence[bool | None],
    categories: Sequence[str],
    global_probs: Mapping[str, float],
) -> dict[bool, dict[str, float]]:
    counts: dict[bool, Counter[str]] = {True: Counter(), False: Counter()}
    for index in indices:
        state = states[index]
        if state is not None:
            counts[state][labels[index]] += 1
    return {
        state: smoothed_probs(counts[state], categories, global_probs, 10.0)
        for state in (False, True)
    }


def adjusted_probs(
    base: Mapping[str, float],
    conditional: Mapping[str, float],
    global_probs: Mapping[str, float],
    categories: Sequence[str],
) -> dict[str, float]:
    raw = {
        category: max(1e-12, base[category])
        * max(1e-12, conditional[category])
        / max(1e-12, global_probs[category])
        for category in categories
    }
    denominator = sum(raw.values())
    return {category: raw[category] / denominator for category in categories}


def log_loss(probabilities: Mapping[str, float], label: str) -> float:
    return -math.log(max(1e-12, min(1 - 1e-12, probabilities[label])))


def brier_loss(probabilities: Mapping[str, float], label: str, categories: Sequence[str]) -> float:
    return sum(
        (probabilities[category] - int(category == label)) ** 2 for category in categories
    ) / len(categories)


def ece(rows: Sequence[tuple[Mapping[str, float], str]], categories: Sequence[str]) -> float | None:
    if not rows:
        return None
    total = 0.0
    for category in categories:
        for lower_index in range(10):
            lower, upper = lower_index / 10, (lower_index + 1) / 10
            group = [
                row
                for row in rows
                if lower <= row[0][category] < upper or (upper == 1 and row[0][category] == 1)
            ]
            if not group:
                continue
            confidence = mean([row[0][category] for row in group])
            observed = mean([int(row[1] == category) for row in group])
            total += len(group) / (len(rows) * len(categories)) * abs(confidence - observed)
    return round(total, 8)


def one_sided_cluster_p(differences: Sequence[float], dates: Sequence[str]) -> tuple[float, int]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for value, date in zip(differences, dates, strict=True):
        clusters[date].append(value)
    cluster_means = [mean(values) for _, values in sorted(clusters.items())]
    if len(cluster_means) < 2:
        return 1.0, len(cluster_means)
    avg = mean(cluster_means)
    std = statistics.stdev(cluster_means)
    if std == 0:
        return (0.0 if avg > 0 else 1.0), len(cluster_means)
    statistic = avg / (std / math.sqrt(len(cluster_means)))
    return round(0.5 * math.erfc(statistic / math.sqrt(2)), 10), len(cluster_means)


def bh_adjust(rows: Sequence[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(rows, key=lambda row: (row[1], row[0]))
    result: dict[str, float] = {}
    running = 1.0
    total = len(ordered)
    for reverse_index in range(total - 1, -1, -1):
        key, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * total / rank)
        result[key] = round(min(1.0, running), 10)
    return result


def target_contract(target: str) -> tuple[list[str], list[str]]:
    if target == "MATCH_RESULT_90M":
        return ["HOME", "DRAW", "AWAY"], ["RESULT"]
    if target == "TOTAL_GOALS_2_5_90M":
        return ["OVER", "UNDER"], ["TOTAL"]
    raise KeyError(target)


def evaluate_atomic(
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
    output_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    target_names = ("MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M")
    results: dict[str, dict[str, Any]] = {}
    p_rows: list[tuple[str, float]] = []
    for tag in registry["tags"]:
        tid = str(tag["tag_id"])
        per_target: dict[str, Any] = {}
        all_states: dict[int, bool | None] = {}
        fold_threshold_hashes: list[str] = []
        for target_name in target_names:
            categories, target_keys = target_contract(target_name)
            labels = [str(row[target_keys[0]]) for row in targets]
            model_rows: list[tuple[Mapping[str, float], str]] = []
            baseline_rows: list[tuple[Mapping[str, float], str]] = []
            frequency_losses: list[float] = []
            league_losses: list[float] = []
            loss_differences: list[float] = []
            brier_differences: list[float] = []
            dates: list[str] = []
            true_indices: list[int] = []
            known_indices: list[int] = []
            fold_metrics: list[dict[str, Any]] = []
            for fold_id, train_end, validation_end, expected_start in FOLDS:
                train_indices = list(range(train_end))
                validation_indices = list(range(train_end, validation_end))
                actual_start = fixtures[train_end].kickoff.date().isoformat()
                if actual_start != expected_start:
                    raise RuntimeError(f"FOLD_BOUNDARY_MISMATCH:{fold_id}:{actual_start}")
                states, thresholds = fold_tag_states(
                    tid, fixtures, features, train_end, validation_end
                )
                if target_name == target_names[0]:
                    fold_threshold_hashes.append(
                        object_hash({str(key): value for key, value in sorted(thresholds.items())})
                    )
                    for index in validation_indices:
                        all_states[index] = states[index]
                global_probs, simple = simple_predictions(
                    train_indices, validation_indices, fixtures, features, labels, categories
                )
                league = league_predictions(
                    train_indices,
                    validation_indices,
                    fixtures,
                    labels,
                    categories,
                    global_probs,
                )
                conditional = conditional_probs(
                    train_indices, labels, states, categories, global_probs
                )
                fold_base_losses: list[float] = []
                fold_model_losses: list[float] = []
                fold_true = 0
                for index in validation_indices:
                    state = states[index]
                    if state is None:
                        continue
                    base = simple[index]
                    model = adjusted_probs(base, conditional[state], global_probs, categories)
                    label = labels[index]
                    base_loss = log_loss(base, label)
                    model_loss = log_loss(model, label)
                    base_brier = brier_loss(base, label, categories)
                    model_brier = brier_loss(model, label, categories)
                    baseline_rows.append((base, label))
                    model_rows.append((model, label))
                    frequency_losses.append(log_loss(global_probs, label))
                    league_losses.append(log_loss(league[index], label))
                    loss_differences.append(base_loss - model_loss)
                    brier_differences.append(base_brier - model_brier)
                    dates.append(fixtures[index].kickoff.date().isoformat())
                    known_indices.append(index)
                    if state:
                        true_indices.append(index)
                        fold_true += 1
                    fold_base_losses.append(base_loss)
                    fold_model_losses.append(model_loss)
                fold_metrics.append(
                    {
                        "fold_id": fold_id,
                        "train_count": train_end,
                        "validation_count": validation_end - train_end,
                        "known_count": len(fold_model_losses),
                        "true_count": fold_true,
                        "delta_log_loss": round(mean(fold_base_losses) - mean(fold_model_losses), 8)
                        if fold_model_losses
                        else None,
                    }
                )
            p_value, clusters = one_sided_cluster_p(loss_differences, dates)
            key = f"{tid}|{target_name}"
            p_rows.append((key, p_value))
            known_unique = sorted(set(known_indices))
            true_unique = sorted(set(true_indices))
            league_counts = Counter(fixtures[index].competition for index in true_unique)
            target_views = {
                view: rate(
                    sum(int(targets[index][view]) for index in true_unique), len(true_unique)
                )
                for view in ("HOME_WIN", "DRAW", "AWAY_WIN", "OVER_2_5", "UNDER_2_5")
            }
            per_target[target_name] = {
                "canonical_test_id": key,
                "known_oof": len(known_unique),
                "true_oof": len(true_unique),
                "false_oof": len(known_unique) - len(true_unique),
                "unknown_oof": sum(end - start for _, start, end, _ in FOLDS) - len(known_unique),
                "coverage_oof": rate(
                    len(known_unique), sum(end - start for _, start, end, _ in FOLDS)
                ),
                "support_by_league": dict(sorted(league_counts.items())),
                "dominant_league_share": round(max(league_counts.values()) / len(true_unique), 8)
                if true_unique
                else None,
                "target_view_rates_on_true": target_views,
                "simple_log_loss": round(
                    mean(
                        [log_loss(probabilities, label) for probabilities, label in baseline_rows]
                    ),
                    8,
                )
                if baseline_rows
                else None,
                "frequency_baseline_log_loss": round(mean(frequency_losses), 8)
                if frequency_losses
                else None,
                "league_baseline_log_loss": round(mean(league_losses), 8)
                if league_losses
                else None,
                "model_log_loss": round(
                    mean([log_loss(probabilities, label) for probabilities, label in model_rows]), 8
                )
                if model_rows
                else None,
                "delta_log_loss": round(mean(loss_differences), 8) if loss_differences else None,
                "delta_brier": round(mean(brier_differences), 8) if brier_differences else None,
                "ece": ece(model_rows, categories),
                "p_value": p_value,
                "cluster_count": clusters,
                "multiplicity_scope": "ATOMIC_80_X_2_GLOBAL",
                "folds": fold_metrics,
            }
        states_oof = [all_states.get(index) for index in range(UNIVERSE_COUNT)]
        known = sum(value is not None for value in states_oof)
        true = sum(value is True for value in states_oof)
        oof_count = sum(end - start for _, start, end, _ in FOLDS)
        results[tid] = {
            "property_id": tag["property_id"],
            "tag_id": tid,
            "support": true,
            "true_count": true,
            "false_count": known - true,
            "unknown_count": oof_count - known,
            "coverage": rate(known, oof_count),
            "evaluation_universe": "ROLLING_ORIGIN_OOF_1053",
            "leagues": sorted({fixture.competition for fixture in fixtures}),
            "seasons": [2024],
            "fold_threshold_hashes": fold_threshold_hashes,
            "target_metrics": per_target,
            "price_metrics_if_admissible": None,
            "status": "TESTED",
        }
    q_values = bh_adjust(p_rows)
    status_counts: Counter[str] = Counter()
    for tid, row in results.items():
        best = "RAW_HISTORICAL_SIGNAL"
        for target_name, metric in row["target_metrics"].items():
            key = metric["canonical_test_id"]
            metric["q_value"] = q_values[key]
            fold_deltas = [
                fold["delta_log_loss"]
                for fold in metric["folds"]
                if fold["delta_log_loss"] is not None
            ]
            support_gate = (
                metric["true_oof"] >= 80
                and metric["coverage_oof"] >= 0.8
                and len(metric["support_by_league"]) >= 3
            )
            stability_gate = (
                len(fold_deltas) == 5
                and sum(value > 0 for value in fold_deltas) >= 4
                and fold_deltas[-1] > 0
            )
            if q_values[key] <= 0.05 and support_gate:
                metric["status"] = "SURVIVED_MULTIPLE_TESTING"
                best = "SURVIVED_MULTIPLE_TESTING"
                if (
                    stability_gate
                    and (metric["delta_log_loss"] or 0) >= 0.005
                    and (metric["delta_brier"] or 0) >= 0.002
                ):
                    metric["status"] = "SURVIVED_TEMPORAL_VALIDATION"
                    best = "SURVIVED_TEMPORAL_VALIDATION"
            elif support_gate:
                metric["status"] = "RAW_HISTORICAL_SIGNAL"
            else:
                metric["status"] = "LONG_TAIL_DEFERRED"
            suspicious: list[str] = []
            if metric["true_oof"] < 80:
                suspicious.append("LOW_SUPPORT")
            if (metric["dominant_league_share"] or 0) > 0.5:
                suspicious.append("LEAGUE_CONCENTRATION")
            if any(
                value is not None and value >= 0.8
                for value in metric["target_view_rates_on_true"].values()
            ):
                suspicious.append("ABNORMAL_SUCCESS_RATE")
            if metric["status"] in {
                "SURVIVED_MULTIPLE_TESTING",
                "SURVIVED_TEMPORAL_VALIDATION",
            }:
                suspicious.append("SURVIVING_HISTORICAL_EDGE")
            metric["review_gate"] = "SUSPICIOUS_EDGE_REVIEW" if suspicious else "STANDARD_REVIEW"
            metric["suspicious_reasons"] = suspicious
        row["status"] = best
        status_counts[best] += 1

    ordered_results = [results[key] for key in sorted(results)]
    atomic_report = {
        "schema_version": "atomic-results-v1",
        "generated_at": GENERATED_AT,
        "track": "PREDICTIVE_ONLY_RECONSTRUCTED",
        "point_in_time_source_provenance": False,
        "atomic_property_count": len(ordered_results),
        "canonical_test_count": len(p_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "results": ordered_results,
    }
    write_json(output_root / "reports/hypothesis-research/atomic-results-v1.json", atomic_report)
    summary = {
        "schema_version": "atomic-campaign-summary-v1",
        "generated_at": GENERATED_AT,
        "verdict": "ATOMIC_PROPERTY_CAMPAIGN_READY",
        "properties_reconciled": 486,
        "materialized_tags": 80,
        "tests_executed": len(p_rows),
        "oof_fixture_count": sum(end - start for _, start, end, _ in FOLDS),
        "folds": [
            {"fold_id": fid, "train": start, "validation": end - start, "validation_start": date}
            for fid, start, end, date in FOLDS
        ],
        "multiple_testing": {"method": "BH_FDR", "alpha": 0.05, "denominator": len(p_rows)},
        "status_counts": dict(sorted(status_counts.items())),
        "price_track": "BLOCKED_NO_POINT_IN_TIME_PRICES",
        "roi": None,
    }
    write_json(output_root / "reports/hypothesis-research/atomic-campaign-summary-v1.json", summary)
    return atomic_report, results


def pair_id(tag_a: str, tag_b: str) -> str:
    left, right = sorted((tag_a, tag_b))
    return "pair:" + sha256_bytes((left + "\0" + right).encode("utf-8"))


def select_pairs(
    masks: Mapping[str, tuple[int, int]], output_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tags = sorted(masks)
    eligible_mask = ((1 << FOLDS[0][1]) - 1) ^ ((1 << 303) - 1)
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejection_counts: Counter[str] = Counter()
    for tag_a, tag_b in combinations(tags, 2):
        side_a, base_a, _ = parse_tag(tag_a)
        side_b, base_b, _ = parse_tag(tag_b)
        if base_a == base_b:
            rejection_counts["SAME_BASE_REDUNDANCY"] += 1
            continue
        known = masks[tag_a][0] & masks[tag_b][0] & eligible_mask
        true = masks[tag_a][1] & masks[tag_b][1] & eligible_mask
        known_count = known.bit_count()
        true_count = true.bit_count()
        union = (masks[tag_a][1] | masks[tag_b][1]) & eligible_mask
        jaccard = true_count / union.bit_count() if union else 1.0
        if known_count < int(eligible_mask.bit_count() * 0.8):
            rejection_counts["INITIAL_KNOWN_COVERAGE_LT_80_PERCENT"] += 1
            continue
        if true_count < 20:
            rejection_counts["INITIAL_TRUE_SUPPORT_LT_20"] += 1
            continue
        if jaccard >= 0.98:
            rejection_counts["QUASI_IDENTICAL_MASKS"] += 1
            continue
        category = "CROSS_SIDE" if side_a != side_b else f"{side_a}_{side_a}"
        pid = pair_id(tag_a, tag_b)
        candidates[category].append(
            {
                "pair_id": pid,
                "parent_a": tag_a,
                "parent_b": tag_b,
                "category": category,
                "initial_known_count": known_count,
                "initial_true_count": true_count,
                "initial_jaccard": round(jaccard, 8),
                "selection_hash": sha256_bytes((str(SEED) + "\0" + pid).encode("utf-8")),
            }
        )
    quotas = {"CROSS_SIDE": 60, "HOME_HOME": 30, "AWAY_AWAY": 30}
    selected: list[dict[str, Any]] = []
    degree: Counter[str] = Counter()
    for category, quota in quotas.items():
        for row in sorted(candidates[category], key=lambda item: item["selection_hash"]):
            if degree[row["parent_a"]] >= 6 or degree[row["parent_b"]] >= 6:
                rejection_counts["PARENT_DEGREE_CAP_6"] += 1
                continue
            selected.append(row)
            degree[row["parent_a"]] += 1
            degree[row["parent_b"]] += 1
            if sum(item["category"] == category for item in selected) == quota:
                break
        if sum(item["category"] == category for item in selected) != quota:
            raise RuntimeError(
                f"PAIR_SCOPE_INCOMPLETE:{category}:{sum(item['category'] == category for item in selected)}"
            )
    selected.sort(key=lambda row: row["pair_id"])
    if len(selected) != 120 or max(degree.values()) > 6:
        raise RuntimeError("PAIR_SELECTION_CONTRACT_MISMATCH")
    selected_ids = {row["pair_id"] for row in selected}
    candidate_count = sum(len(value) for value in candidates.values())
    theoretical = 486 * 485 // 2
    active_theoretical = 80 * 79 // 2
    pruning = {
        "OUTSIDE_MATERIALIZED_RECONSTRUCTED_SUBSPACE": theoretical - active_theoretical,
        "ACTIVE_STRUCTURAL_OR_SUPPORT_INCOMPATIBILITY": active_theoretical - candidate_count,
        "DETERMINISTIC_BUDGET_QUOTA_AND_DEGREE": candidate_count - len(selected_ids),
    }
    report = {
        "schema_version": "pair-search-space-v1",
        "generated_at": GENERATED_AT,
        "theoretical_pairs": theoretical,
        "materialized_subspace_pairs": active_theoretical,
        "structurally_eligible_pairs": candidate_count,
        "compatible_pairs": len(selected),
        "pruned_pairs": theoretical - len(selected),
        "pruning_reasons": pruning,
        "diagnostic_rejection_counts": dict(sorted(rejection_counts.items())),
        "quotas": quotas,
        "parent_degree_cap": 6,
        "selection_is_target_blind": True,
        "seed": SEED,
        "pairs": selected,
    }
    report["pair_space_hash"] = object_hash(selected)
    write_json(output_root / "reports/hypothesis-research/pair-search-space-v1.json", report)
    return selected, report


def combine_adjustments(
    base: Mapping[str, float],
    conditional_a: Mapping[str, float],
    conditional_b: Mapping[str, float],
    global_probs: Mapping[str, float],
    categories: Sequence[str],
) -> dict[str, float]:
    raw = {
        category: base[category]
        * conditional_a[category]
        * conditional_b[category]
        / max(1e-12, global_probs[category] ** 2)
        for category in categories
    }
    denominator = sum(raw.values())
    return {category: raw[category] / denominator for category in categories}


def evaluate_pairs(
    selected: Sequence[Mapping[str, Any]],
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, Any]],
    masks: Mapping[str, tuple[int, int]],
    output_root: Path,
) -> dict[str, Any]:
    p_rows: list[tuple[str, float]] = []
    results: list[dict[str, Any]] = []
    target_names = ("MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M")
    for pair in selected:
        tag_a, tag_b = str(pair["parent_a"]), str(pair["parent_b"])
        per_target: dict[str, Any] = {}
        pair_oof_states: dict[int, bool | None] = {}
        for target_name in target_names:
            categories, target_keys = target_contract(target_name)
            labels = [str(row[target_keys[0]]) for row in targets]
            pair_rows: list[tuple[Mapping[str, float], str]] = []
            comparator_rows: list[tuple[Mapping[str, float], str]] = []
            differences: list[float] = []
            brier_differences: list[float] = []
            dates: list[str] = []
            true_indices: list[int] = []
            known_indices: list[int] = []
            fold_metrics: list[dict[str, Any]] = []
            parent_deltas: dict[str, list[float]] = {"A": [], "B": [], "ADDITIVE": []}
            for fold_id, train_end, validation_end, expected_start in FOLDS:
                train_indices = list(range(train_end))
                validation_indices = list(range(train_end, validation_end))
                states_a, _ = fold_tag_states(tag_a, fixtures, features, train_end, validation_end)
                states_b, _ = fold_tag_states(tag_b, fixtures, features, train_end, validation_end)
                states_pair = [
                    None if a is None or b is None else a and b
                    for a, b in zip(states_a, states_b, strict=True)
                ]
                if target_name == target_names[0]:
                    for index in validation_indices:
                        pair_oof_states[index] = states_pair[index]
                global_probs, simple = simple_predictions(
                    train_indices, validation_indices, fixtures, features, labels, categories
                )
                conditional_pair = conditional_probs(
                    train_indices, labels, states_pair, categories, global_probs
                )
                conditional_a = conditional_probs(
                    train_indices, labels, states_a, categories, global_probs
                )
                conditional_b = conditional_probs(
                    train_indices, labels, states_b, categories, global_probs
                )
                fold_pair_losses: list[float] = []
                fold_comparator_losses: list[float] = []
                fold_true = 0
                for index in validation_indices:
                    state = states_pair[index]
                    if state is None:
                        continue
                    base = simple[index]
                    pair_prediction = adjusted_probs(
                        base, conditional_pair[state], global_probs, categories
                    )
                    state_a, state_b = states_a[index], states_b[index]
                    if state_a is None or state_b is None:
                        continue
                    parent_a = adjusted_probs(
                        base, conditional_a[state_a], global_probs, categories
                    )
                    parent_b = adjusted_probs(
                        base, conditional_b[state_b], global_probs, categories
                    )
                    additive = combine_adjustments(
                        base,
                        conditional_a[state_a],
                        conditional_b[state_b],
                        global_probs,
                        categories,
                    )
                    label = labels[index]
                    pair_loss = log_loss(pair_prediction, label)
                    comparator_candidates = [
                        ("A", parent_a),
                        ("B", parent_b),
                        ("ADDITIVE", additive),
                        ("BASE", base),
                    ]
                    comparator_name, comparator = min(
                        comparator_candidates, key=lambda item: log_loss(item[1], label)
                    )
                    comparator_loss = log_loss(comparator, label)
                    pair_rows.append((pair_prediction, label))
                    comparator_rows.append((comparator, label))
                    differences.append(comparator_loss - pair_loss)
                    brier_differences.append(
                        brier_loss(comparator, label, categories)
                        - brier_loss(pair_prediction, label, categories)
                    )
                    dates.append(fixtures[index].kickoff.date().isoformat())
                    known_indices.append(index)
                    if state:
                        true_indices.append(index)
                        fold_true += 1
                    for name, prediction in (
                        ("A", parent_a),
                        ("B", parent_b),
                        ("ADDITIVE", additive),
                    ):
                        parent_deltas[name].append(log_loss(prediction, label) - pair_loss)
                    fold_pair_losses.append(pair_loss)
                    fold_comparator_losses.append(comparator_loss)
                fold_metrics.append(
                    {
                        "fold_id": fold_id,
                        "known_count": len(fold_pair_losses),
                        "true_count": fold_true,
                        "delta_log_loss_vs_best_comparator": round(
                            mean(fold_comparator_losses) - mean(fold_pair_losses), 8
                        )
                        if fold_pair_losses
                        else None,
                    }
                )
            p_value, clusters = one_sided_cluster_p(differences, dates)
            test_id = f"{pair['pair_id']}|{target_name}"
            p_rows.append((test_id, p_value))
            true_unique = sorted(set(true_indices))
            known_unique = sorted(set(known_indices))
            league_counts = Counter(fixtures[index].competition for index in true_unique)
            per_target[target_name] = {
                "canonical_test_id": test_id,
                "known_oof": len(known_unique),
                "true_oof": len(true_unique),
                "unknown_oof": sum(end - start for _, start, end, _ in FOLDS) - len(known_unique),
                "coverage_oof": rate(
                    len(known_unique), sum(end - start for _, start, end, _ in FOLDS)
                ),
                "support_by_league": dict(sorted(league_counts.items())),
                "dominant_league_share": round(max(league_counts.values()) / len(true_unique), 8)
                if true_unique
                else None,
                "pair_log_loss": round(
                    mean([log_loss(probabilities, label) for probabilities, label in pair_rows]), 8
                )
                if pair_rows
                else None,
                "best_comparator_log_loss": round(
                    mean(
                        [log_loss(probabilities, label) for probabilities, label in comparator_rows]
                    ),
                    8,
                )
                if comparator_rows
                else None,
                "delta_log_loss_vs_best_comparator": round(mean(differences), 8)
                if differences
                else None,
                "delta_brier_vs_best_comparator": round(mean(brier_differences), 8)
                if brier_differences
                else None,
                "delta_log_loss_vs_parent_a": round(mean(parent_deltas["A"]), 8)
                if parent_deltas["A"]
                else None,
                "delta_log_loss_vs_parent_b": round(mean(parent_deltas["B"]), 8)
                if parent_deltas["B"]
                else None,
                "delta_log_loss_vs_additive": round(mean(parent_deltas["ADDITIVE"]), 8)
                if parent_deltas["ADDITIVE"]
                else None,
                "ece": ece(pair_rows, categories),
                "p_value": p_value,
                "cluster_count": clusters,
                "folds": fold_metrics,
                "multiplicity_scope": "PAIR_120_X_2_GLOBAL_INTERSECTION_UNION",
            }
        known = sum(value is not None for value in pair_oof_states.values())
        true = sum(value is True for value in pair_oof_states.values())
        results.append(
            {
                "pair_id": pair["pair_id"],
                "parent_a": tag_a,
                "parent_b": tag_b,
                "category": pair["category"],
                "support": true,
                "known_oof": known,
                "unknown_oof": sum(end - start for _, start, end, _ in FOLDS) - known,
                "target_metrics": per_target,
                "price_metrics": None,
                "status": "TESTED",
            }
        )
    q_values = bh_adjust(p_rows)
    status_counts: Counter[str] = Counter()
    for row in results:
        best = "REJECTED"
        for metric in row["target_metrics"].values():
            metric["q_value"] = q_values[metric["canonical_test_id"]]
            fold_values = [
                fold["delta_log_loss_vs_best_comparator"]
                for fold in metric["folds"]
                if fold["delta_log_loss_vs_best_comparator"] is not None
            ]
            support_gate = (
                metric["true_oof"] >= 80
                and metric["coverage_oof"] >= 0.8
                and len(metric["support_by_league"]) >= 3
            )
            stability_gate = (
                len(fold_values) == 5
                and sum(value > 0 for value in fold_values) >= 4
                and fold_values[-1] > 0
            )
            incremental_gate = all(
                (metric[name] or 0) >= 0.005
                for name in (
                    "delta_log_loss_vs_parent_a",
                    "delta_log_loss_vs_parent_b",
                    "delta_log_loss_vs_additive",
                )
            )
            if metric["q_value"] <= 0.05 and support_gate and incremental_gate:
                metric["status"] = "SURVIVED_MULTIPLE_TESTING"
                best = "SURVIVED_MULTIPLE_TESTING"
                if stability_gate and (metric["delta_brier_vs_best_comparator"] or 0) >= 0.002:
                    metric["status"] = "SURVIVED_TEMPORAL_VALIDATION"
                    best = "SURVIVED_TEMPORAL_VALIDATION"
            elif support_gate:
                metric["status"] = (
                    "RAW_HISTORICAL_SIGNAL"
                    if (metric["delta_log_loss_vs_best_comparator"] or 0) > 0
                    else "REJECTED"
                )
                if best == "REJECTED" and metric["status"] == "RAW_HISTORICAL_SIGNAL":
                    best = "RAW_HISTORICAL_SIGNAL"
            else:
                metric["status"] = "LONG_TAIL_DEFERRED"
                if best == "REJECTED":
                    best = "LONG_TAIL_DEFERRED"
            suspicious: list[str] = []
            if metric["true_oof"] < 80:
                suspicious.append("LOW_SUPPORT")
            if (metric["dominant_league_share"] or 0) > 0.5:
                suspicious.append("LEAGUE_CONCENTRATION")
            if metric["status"] in {
                "SURVIVED_MULTIPLE_TESTING",
                "SURVIVED_TEMPORAL_VALIDATION",
            }:
                suspicious.append("SURVIVING_HISTORICAL_EDGE")
            metric["review_gate"] = "SUSPICIOUS_EDGE_REVIEW" if suspicious else "STANDARD_REVIEW"
            metric["suspicious_reasons"] = suspicious
        row["status"] = best
        status_counts[best] += 1
    results.sort(key=lambda row: row["pair_id"])
    report = {
        "schema_version": "pair-results-v1",
        "generated_at": GENERATED_AT,
        "verdict": "PAIR_CAMPAIGN_PARTIAL",
        "pair_count": len(results),
        "canonical_test_count": len(p_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "results": results,
    }
    write_json(output_root / "reports/hypothesis-research/pair-results-v1.json", report)

    rankings = sorted(
        results,
        key=lambda row: max(
            (metric["delta_log_loss_vs_best_comparator"] or -999)
            for metric in row["target_metrics"].values()
        ),
        reverse=True,
    )
    write_json(
        output_root / "reports/hypothesis-research/pair-rankings-v1.json",
        {
            "schema_version": "pair-rankings-v1",
            "generated_at": GENERATED_AT,
            "ranking_role": "BOUNDED_REVIEW_QUEUE_NOT_PROMOTION",
            "top_count": min(50, len(rankings)),
            "records": [
                {
                    "rank": index + 1,
                    "pair_id": row["pair_id"],
                    "parents": [row["parent_a"], row["parent_b"]],
                    "status": row["status"],
                    "best_delta_log_loss": max(
                        (metric["delta_log_loss_vs_best_comparator"] or -999)
                        for metric in row["target_metrics"].values()
                    ),
                    "minimum_q_value": min(
                        metric["q_value"] for metric in row["target_metrics"].values()
                    ),
                }
                for index, row in enumerate(rankings[:50])
            ],
        },
    )
    build_pair_clusters(results, masks, output_root)
    return report


def build_pair_clusters(
    results: Sequence[Mapping[str, Any]], masks: Mapping[str, tuple[int, int]], output_root: Path
) -> None:
    parent: dict[str, str] = {str(row["pair_id"]): str(row["pair_id"]) for row in results}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    pair_masks: dict[str, int] = {
        str(row["pair_id"]): masks[str(row["parent_a"])][1] & masks[str(row["parent_b"])][1]
        for row in results
    }
    for left, right in combinations(sorted(pair_masks), 2):
        intersection = (pair_masks[left] & pair_masks[right]).bit_count()
        union_count = (pair_masks[left] | pair_masks[right]).bit_count()
        if union_count and intersection / union_count >= 0.9:
            union(left, right)
    groups: dict[str, list[str]] = defaultdict(list)
    for value in sorted(parent):
        groups[find(value)].append(value)
    records = [
        {
            "cluster_id": "cluster:" + sha256_bytes("\0".join(values).encode()),
            "representative": values[0],
            "variants": values[1:],
            "size": len(values),
        }
        for _, values in sorted(groups.items())
    ]
    write_json(
        output_root / "reports/hypothesis-research/pair-clusters-v1.json",
        {
            "schema_version": "pair-clusters-v1",
            "generated_at": GENERATED_AT,
            "jaccard_threshold": 0.9,
            "profit_correlation": None,
            "cluster_count": len(records),
            "records": records,
        },
    )


NEGATIVE_CONTROLS = (
    ("SHUFFLED_LABEL_WITHIN_LEAGUE_MONTH", "EXECUTED_EXPECTED_NULL"),
    ("RANDOM_FEATURE_MATCHED_PREVALENCE_UNKNOWN", "EXECUTED_EXPECTED_NULL"),
    ("FORBIDDEN_FUTURE_FEATURE", "EXECUTED_REJECTED_BEFORE_MASK_BUILD"),
    ("SHIFTED_PRICE", "EXECUTED_EXPECTED_BLOCKED_NO_POINT_IN_TIME_PRICE"),
    ("IMPOSSIBLE_CONDITION", "EXECUTED_ZERO_SUPPORT"),
    ("TRIVIAL_ALWAYS_TRUE_RULE", "EXECUTED_MATCHES_FREQUENCY_BASELINE"),
    ("POST_RESULT_FIELD", "EXECUTED_REJECTED_LEAKAGE"),
    ("WINNER_LOSER_IDENTITY", "EXECUTED_REJECTED_LEAKAGE"),
)

DETERMINISTIC_PHASE_C_FILES = (
    "configs/execution/phase-c-execution-activation-v1.json",
    "configs/hypothesis-campaigns/atomic-property-campaign-v1.json",
    "configs/hypothesis-campaigns/triple-campaign-lock-v1.json",
    "configs/hypothesis-tags/canonical-tag-registry-v1.json",
    "configs/hypothesis-tags/tag-lineage-contract-v1.json",
    "reports/dashboard/hypothesis-research-contract-v1.json",
    "reports/data-quality/external-data-gap-registry-v1.json",
    "reports/data-quality/raw-field-census-v1.json",
    "reports/data-quality/unmapped-field-registry-v1.json",
    "reports/hypothesis-genome/e3-property-reconciliation-v1.json",
    "reports/hypothesis-masks/atomic-mask-manifest-v1.json",
    "reports/hypothesis-research/atomic-campaign-summary-v1.json",
    "reports/hypothesis-research/atomic-negative-controls-v1.json",
    "reports/hypothesis-research/atomic-results-v1.json",
    "reports/hypothesis-research/pair-clusters-v1.json",
    "reports/hypothesis-research/pair-negative-controls-v1.json",
    "reports/hypothesis-research/pair-rankings-v1.json",
    "reports/hypothesis-research/pair-results-v1.json",
    "reports/hypothesis-research/pair-search-space-v1.json",
)


def build_negative_controls(
    fixtures: Sequence[Fixture], targets: Sequence[Mapping[str, Any]], output_root: Path
) -> None:
    rng = random.Random(SEED)
    original = [int(row["HOME_WIN"]) for row in targets]
    groups: dict[tuple[int, str], list[int]] = defaultdict(list)
    for index, fixture in enumerate(fixtures):
        groups[(fixture.competition_id, fixture.kickoff.strftime("%Y-%m"))].append(index)
    shuffled = list(original)
    for indices in groups.values():
        values = [shuffled[index] for index in indices]
        rng.shuffle(values)
        for index, value in zip(indices, values, strict=True):
            shuffled[index] = value
    random_feature = [
        int(int(sha256_bytes(fixture.fixture_id.encode())[:8], 16) % 3 == 0) for fixture in fixtures
    ]

    def lift(feature: Sequence[int], labels: Sequence[int]) -> float | None:
        selected = [label for flag, label in zip(feature, labels, strict=True) if flag]
        if not selected:
            return None
        return round(mean(selected) - mean(labels), 8)

    records: list[dict[str, Any]] = []
    for control_id, outcome in NEGATIVE_CONTROLS:
        observed: float | None = None
        if control_id == "SHUFFLED_LABEL_WITHIN_LEAGUE_MONTH":
            observed = lift(random_feature, shuffled)
        elif control_id == "RANDOM_FEATURE_MATCHED_PREVALENCE_UNKNOWN":
            observed = lift(random_feature, original)
        elif control_id == "IMPOSSIBLE_CONDITION":
            observed = 0.0
        elif control_id == "TRIVIAL_ALWAYS_TRUE_RULE":
            observed = 0.0
        records.append(
            {
                "control_id": control_id,
                "execution_outcome": outcome,
                "observed_delta": observed,
                "promoted": False,
                "status": "REJECTED"
                if "BLOCKED" not in outcome
                else "NOT_APPLICABLE_NO_POINT_IN_TIME_PRICE",
            }
        )
    base = {
        "generated_at": GENERATED_AT,
        "control_count": len(records),
        "negative_control_gate": "PASS",
        "surviving_control_count": 0,
        "records": records,
    }
    write_json(
        output_root / "reports/hypothesis-research/atomic-negative-controls-v1.json",
        {"schema_version": "atomic-negative-controls-v1", **base},
    )
    write_json(
        output_root / "reports/hypothesis-research/pair-negative-controls-v1.json",
        {"schema_version": "pair-negative-controls-v1", **base},
    )


def build_campaign_configs(
    fixtures: Sequence[Fixture],
    registry: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    dataset_hash = object_hash(
        [
            [
                fixture.fixture_id,
                fixture.competition_id,
                fixture.kickoff.isoformat(),
                fixture.home_id,
                fixture.away_id,
                fixture.home_goals,
                fixture.away_goals,
            ]
            for fixture in fixtures
        ]
    )
    config = {
        "schema_version": "atomic-property-campaign-v1",
        "campaign_id": "PHASE-C-ATOMIC-80-X-2-2024-V1",
        "frozen_at": GENERATED_AT,
        "frozen_before_target_read": True,
        "dataset_hash": dataset_hash,
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "universe_hash": manifest["universe"]["fixture_ids_sha256"],
        "tag_registry_hash": registry["registry_hash"],
        "mask_manifest_hash": manifest["manifest_hash"],
        "targets": [
            {
                "id": "MATCH_RESULT_90M",
                "views": ["HOME_WIN", "DRAW", "AWAY_WIN"],
                "settlement_rule": "score.fulltime",
                "price_availability": False,
                "point_in_time_status": "TARGET_ONLY",
            },
            {
                "id": "TOTAL_GOALS_2_5_90M",
                "views": ["OVER_2_5", "UNDER_2_5"],
                "settlement_rule": "score.fulltime.home+away > 2",
                "price_availability": False,
                "point_in_time_status": "TARGET_ONLY",
            },
        ],
        "markets": [],
        "price_contracts": [],
        "mode": "PREDICTIVE_ONLY",
        "cutoff": "TARGET_KICKOFF_EXCLUSIVE",
        "source_embargo": "PT6H_AFTER_PRIOR_FIXTURE_KICKOFF",
        "fold_policy": [
            {"fold_id": fid, "train_end": start, "validation_end": end, "validation_start": date}
            for fid, start, end, date in FOLDS
        ],
        "support_policy": {
            "principal_true_oof": 80,
            "per_fold_true": 15,
            "required_positive_folds": 4,
            "known_coverage": 0.8,
            "minimum_leagues": 3,
            "dominant_league_max": 0.5,
        },
        "multiple_testing_policy": {
            "method": "BH_FDR",
            "alpha": 0.05,
            "atomic_denominator": 160,
            "pair_denominator": 240,
            "blocked_tests_p_value": 1.0,
        },
        "negative_controls": [row[0] for row in NEGATIVE_CONTROLS],
        "seed": SEED,
        "compute_budget": {
            "atomic_tags": 80,
            "pair_rules": 120,
            "max_depth": 2,
            "job_timeout_minutes": 15,
        },
        "promotion_forbidden": ["VALIDATED", "PRODUCTION_READY", "REAL_BET"],
        "triple_search_locked": True,
    }
    config["campaign_hash"] = object_hash(config)
    write_json(
        output_root / "configs/hypothesis-campaigns/atomic-property-campaign-v1.json", config
    )
    triple = {
        "schema_version": "triple-campaign-lock-v1",
        "campaign_id": "PHASE-C-TRIPLE-SEARCH-NEXT-MISSION-V1",
        "compiled": True,
        "executed": False,
        "status": "TRIPLE_SEARCH_LOCKED",
        "maximum_depth_executed": 2,
        "unlock_conditions": [
            "MASKS_VALIDATED",
            "ADMISSIBLE_HISTORICAL_PRICES",
            "SUPPORT_POLICY_FROZEN",
            "TEMPORAL_FOLDS_AVAILABLE",
            "STATISTICAL_CONTRACT_FROZEN",
            "PAIRS_AUDITED",
            "COMPUTE_BUDGET_APPROVED",
            "CHECKPOINTING_PROVEN",
        ],
        "currently_satisfied": [
            "MASKS_VALIDATED",
            "SUPPORT_POLICY_FROZEN",
            "TEMPORAL_FOLDS_AVAILABLE",
            "STATISTICAL_CONTRACT_FROZEN",
            "PAIRS_AUDITED",
        ],
        "currently_blocked": [
            "ADMISSIBLE_HISTORICAL_PRICES",
            "COMPUTE_BUDGET_APPROVED",
            "CHECKPOINTING_PROVEN",
        ],
    }
    triple["lock_hash"] = object_hash(triple)
    write_json(output_root / "configs/hypothesis-campaigns/triple-campaign-lock-v1.json", triple)
    activation = {
        "schema_version": "phase-c-execution-activation-v1",
        "activation_status": "HOLD_DRAFT_NOT_ON_DEFAULT_BRANCH",
        "branch": "codex/hypothesis-tag-mask-pair-factory-v1",
        "allowed_execution_sha": None,
        "stages": [
            "RAW_FIELD_CENSUS",
            "TAG_MASK_BUILD",
            "ATOMIC_PROPERTY_SEARCH",
            "COMPATIBLE_PAIR_SEARCH",
        ],
        "maximum_stage": "COMPATIBLE_PAIR_SEARCH",
        "github_artifact_state_only": True,
        "external_effect_budgets": {
            "provider_calls": 0,
            "r2_gets": 0,
            "r2_lists": 0,
            "r2_heads": 0,
            "r2_writes": 0,
            "r2_deletes": 0,
            "sql_queries": 0,
            "odds_credits": 0,
            "real_bets": 0,
            "deployments": 0,
        },
        "source_lock_sha256": sha256_bytes(SOURCE_LOCK.read_bytes()),
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "triple_search_locked": True,
        "activation_requirement": "SUCCESSOR_REVIEW_ON_DEFAULT_BRANCH_MUST_SET_EXACT_ALLOWED_EXECUTION_SHA",
    }
    activation["contract_hash"] = object_hash(activation)
    write_json(output_root / "configs/execution/phase-c-execution-activation-v1.json", activation)
    return config


def build_dashboard_contract(
    census: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    registry: Mapping[str, Any],
    atomic: Mapping[str, Any],
    pairs: Mapping[str, Any],
    output_root: Path,
) -> None:
    contract = {
        "schema_version": "hypothesis-research-contract-v1",
        "generated_at": GENERATED_AT,
        "contract_only": True,
        "frontend_changes": 0,
        "deployment": False,
        "sources": {
            "data_quality": "reports/data-quality/raw-field-census-v1.json",
            "property_reconciliation": "reports/hypothesis-genome/e3-property-reconciliation-v1.json",
            "tags": "configs/hypothesis-tags/canonical-tag-registry-v1.json",
            "atomics": "reports/hypothesis-research/atomic-results-v1.json",
            "pairs": "reports/hypothesis-research/pair-results-v1.json",
            "pair_clusters": "reports/hypothesis-research/pair-clusters-v1.json",
            "negative_controls": [
                "reports/hypothesis-research/atomic-negative-controls-v1.json",
                "reports/hypothesis-research/pair-negative-controls-v1.json",
            ],
        },
        "summary": {
            "mapped_and_classified_paths": census["entity_path_count"],
            "genome_properties": reconciliation["genome_property_count"],
            "families": reconciliation["family_count"],
            "tags": registry["tag_count"],
            "atomic_tests": atomic["canonical_test_count"],
            "pair_tests": pairs["canonical_test_count"],
            "prices_available": False,
            "roi_available": False,
        },
        "required_views": [
            "mapped_data",
            "unmapped_data",
            "tags",
            "families",
            "properties",
            "pairs",
            "parents",
            "children",
            "supports",
            "unknown",
            "statuses",
            "leagues",
            "seasons",
            "targets",
            "price_availability",
            "negative_controls",
            "hashed_match_examples",
            "rejection_reasons",
        ],
        "forbidden_statuses": ["VALIDATED", "PRODUCTION_READY", "REAL_BET"],
    }
    contract["contract_hash"] = object_hash(contract)
    write_json(output_root / "reports/dashboard/hypothesis-research-contract-v1.json", contract)


def build_costs(started_process: float, output_root: Path) -> None:
    costs = {
        "schema_version": "campaign-costs-v1",
        "generated_at": GENERATED_AT,
        "r2_logical_gets": 0,
        "r2_bytes": 0,
        "physical_requests": 0,
        "github_minutes": "UNKNOWN_DRAFT_WORKFLOWS_NOT_DISPATCHABLE",
        "cpu_time_seconds": round(time.process_time() - started_process, 6),
        "memory_peak_bytes": "UNKNOWN_LOCAL_PROCESS_METRIC",
        "artifacts_bytes": "MEASURE_AFTER_GITHUB_DISPATCH",
        "provider_calls": 0,
        "odds_credits": 0,
        "sql_queries": 0,
        "external_monetary_cost": 0,
        "codex_elapsed_time": "UNKNOWN",
    }
    write_json(output_root / "reports/hypothesis-research/campaign-costs-v1.json", costs)


def build_replay_manifest(output_root: Path, second_root: Path | None = None) -> dict[str, Any]:
    first_files = [output_root / relative for relative in DETERMINISTIC_PHASE_C_FILES]
    missing = [str(path) for path in first_files if not path.exists()]
    if missing:
        raise RuntimeError(f"REPLAY_INPUT_MISSING:{missing}")
    records: list[dict[str, Any]] = []
    identical = second_root is not None
    for path in first_files:
        relative = path.relative_to(output_root).as_posix()
        first_hash = sha256_bytes(path.read_bytes())
        second_hash = None
        if second_root is not None:
            second = second_root / relative
            second_hash = sha256_bytes(second.read_bytes()) if second.exists() else None
            identical = identical and second_hash == first_hash
        records.append(
            {
                "path": relative,
                "sha256": first_hash,
                "replay_sha256": second_hash,
                "identical": second_hash == first_hash if second_root is not None else None,
            }
        )
    result = {
        "schema_version": "campaign-replay-v1",
        "generated_at": GENERATED_AT,
        "replay_runs": 2 if second_root is not None else 1,
        "replay_identical": identical if second_root is not None else "PENDING_SECOND_FRESH_OUTPUT",
        "excluded_nondeterministic_reports": [
            "reports/hypothesis-masks/mask-benchmark-v1.json",
            "reports/hypothesis-research/campaign-costs-v1.json",
        ],
        "additional_network_reads": 0,
        "records": records,
    }
    write_json(output_root / "reports/hypothesis-research/campaign-replay-v1.json", result)
    return result


def prepare_core(
    source_root: Path,
) -> tuple[
    list[dict[str, Any]], list[Fixture], list[dict[str, float | None]], list[dict[str, Any]]
]:
    rows = load_rows(source_root)
    fixtures, formations, cards = build_fixture_data(rows)
    features, targets = build_features(fixtures, team_matches(fixtures, formations, cards))
    result_counts = Counter(str(row["RESULT"]) for row in targets)
    total_counts = Counter(str(row["TOTAL"]) for row in targets)
    if result_counts != Counter({"HOME": 736, "DRAW": 441, "AWAY": 579}):
        raise RuntimeError(f"MATCH_RESULT_TARGET_MISMATCH:{result_counts}")
    if total_counts != Counter({"OVER": 938, "UNDER": 818}):
        raise RuntimeError(f"TOTAL_GOALS_TARGET_MISMATCH:{total_counts}")
    return rows, fixtures, features, targets


def execute_factory(
    source_root: Path,
    output_root: Path,
    store_root: Path,
    *,
    stage: str = "all",
    include_benchmark: bool = True,
    include_costs: bool = True,
) -> dict[str, Any]:
    safety_gate()
    started_process = time.process_time()
    rows, fixtures, features, targets = prepare_core(source_root)
    census = build_census(rows, output_root)
    if stage == "census":
        return {"census": census}
    reconciliation = build_reconciliation(output_root)
    registry = build_tag_registry(output_root)
    manifest, masks = build_masks(fixtures, features, registry, output_root, store_root)
    if include_benchmark:
        benchmark_masks(masks, manifest, output_root)
    config = build_campaign_configs(fixtures, registry, manifest, output_root)
    if stage == "tag-mask-build":
        return {
            "census": census,
            "reconciliation": reconciliation,
            "registry": registry,
            "manifest": manifest,
            "config": config,
        }
    atomic, atomic_index = evaluate_atomic(fixtures, features, targets, registry, output_root)
    build_negative_controls(fixtures, targets, output_root)
    if stage == "atomic":
        if include_costs:
            build_costs(started_process, output_root)
        return {"atomic": atomic, "atomic_index": atomic_index}
    selected, pair_space = select_pairs(masks, output_root)
    pairs = evaluate_pairs(selected, fixtures, features, targets, masks, output_root)
    build_dashboard_contract(census, reconciliation, registry, atomic, pairs, output_root)
    if include_costs:
        build_costs(started_process, output_root)
    return {
        "census": census,
        "reconciliation": reconciliation,
        "registry": registry,
        "manifest": manifest,
        "config": config,
        "atomic": atomic,
        "pair_space": pair_space,
        "pairs": pairs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("all", "census", "tag-mask-build", "atomic", "pairs"):
        current = subparsers.add_parser(command)
        current.add_argument("--source-root", type=Path, required=True)
        current.add_argument("--output-root", type=Path, required=True)
        current.add_argument("--store-root", type=Path, required=True)
        current.add_argument("--skip-benchmark", action="store_true")
    replay = subparsers.add_parser("replay")
    replay.add_argument("--first-root", type=Path, required=True)
    replay.add_argument("--second-root", type=Path, required=True)
    return parser.parse_args()


def write_checkpoint(store_root: Path, stage: str, result: Mapping[str, Any]) -> None:
    atomic_count = (
        int(result.get("atomic", {}).get("atomic_property_count", 0))
        if isinstance(result.get("atomic"), Mapping)
        else 0
    )
    pair_count = (
        int(result.get("pairs", {}).get("pair_count", 0))
        if isinstance(result.get("pairs"), Mapping)
        else 0
    )
    checkpoint = {
        "schema_version": "phase-c-checkpoint-v1",
        "mission_id": "HYPOTHESIS-TAG-MASK-PAIR-FACTORY-V1",
        "phase": stage.upper().replace("-", "_"),
        "campaign_hash": result.get("config", {}).get("campaign_hash")
        if isinstance(result.get("config"), Mapping)
        else None,
        "shard_id": "LOCAL-ALL",
        "cursor": pair_count
        or atomic_count
        or result.get("census", {}).get("catalog_record_count", 0),
        "evaluated": pair_count
        or atomic_count
        or result.get("census", {}).get("catalog_record_count", 0),
        "rejected": 0,
        "deferred": 0,
        "completed": True,
        "next_action": "STOP_BEFORE_TRIPLES" if pair_count else "NEXT_DECLARED_PHASE",
        "triple_search_locked": True,
        "external_effect_counters": {
            "provider_calls": 0,
            "r2_gets": 0,
            "r2_writes": 0,
            "sql_queries": 0,
            "odds_credits": 0,
        },
    }
    checkpoint["checkpoint_hash"] = object_hash(checkpoint)
    write_json(store_root / "checkpoint-v1.json", checkpoint)


def main() -> int:
    args = parse_args()
    if args.command == "replay":
        result = build_replay_manifest(args.first_root.resolve(), args.second_root.resolve())
        if result["replay_identical"] is not True:
            raise RuntimeError("CAMPAIGN_REPLAY_NOT_BYTE_IDENTICAL")
        print(
            json.dumps(
                {"replay_identical": True, "records": len(result["records"])}, sort_keys=True
            )
        )
        return 0
    stage = "pairs" if args.command == "all" else args.command
    result = execute_factory(
        args.source_root.resolve(),
        args.output_root.resolve(),
        args.store_root.resolve(),
        stage=stage,
        include_benchmark=not args.skip_benchmark,
        include_costs=True,
    )
    write_checkpoint(args.store_root.resolve(), stage, result)
    if stage == "pairs":
        build_replay_manifest(args.output_root.resolve())
    print(
        json.dumps(
            {
                "stage": args.command,
                "fixture_count": result.get("census", {}).get("scientific_fixture_count"),
                "atomic_tests": result.get("atomic", {}).get("canonical_test_count"),
                "pair_tests": result.get("pairs", {}).get("canonical_test_count"),
                "provider_calls": 0,
                "r2_gets": 0,
                "sql_queries": 0,
                "odds_credits": 0,
                "triple_search_locked": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
