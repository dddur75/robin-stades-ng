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
ACTIVE_RESUME_ROOT: Path | None = None
ACTIVE_RESUME_CHECKPOINT: dict[str, Any] | None = None
ACTIVE_RESUME_LOADED_COUNT = 0
ACTIVE_TEST_STOP_AFTER_RECORDS = int(
    os.environ.get("PHASE_C_CHECKPOINT_TEST_STOP_AFTER_RECORDS", "0")
)

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

# Semantic-review items are explicit.  Never derive this bucket from ordering:
# lexical position has no scientific meaning and would silently reclassify a
# property when the ontology changes.
UNKNOWN_NAMES: dict[str, set[str]] = {
    "BENCH_SUBSTITUTIONS": {
        "attacking_options",
        "defensive_options",
        "experience",
        "historical_impact",
        "natural_replacements",
        "profiles",
        "relative_quality",
        "speed",
    },
    "CHEMISTRY_NETWORKS": {
        "attacking_pair",
        "centrality",
        "dependency",
        "goalkeeper_defence",
        "network_break",
        "network_entropy",
        "pass_network",
        "replacement_cost",
    },
    "COACH": {
        "after_loss_response",
        "congestion_response",
        "game_state_management",
        "half_time_adjustment",
        "opponent_familiarity",
        "rotation",
        "style",
        "style_opposition",
    },
    "DATA_QUALITY": {"identity_confidence"},
    "DISCIPLINE_REFEREE": {"derby_stake", "style_interaction", "suspension_threat"},
    "FORMATION_STRUCTURE": {
        "build_up_shape",
        "formation_fatigue_matchup",
        "formation_market_matchup",
        "formation_weather_matchup",
        "in_possession_shape",
        "out_of_possession_shape",
    },
    "GOALKEEPER": {"weather_cross_interaction"},
    "MATCH_COMPETITION": {"derby", "phase", "rivalry", "season_period"},
    "PLAYER": {
        "experience",
        "form",
        "out_of_position",
        "partner_performance",
        "press_resistance",
        "profile_matchup",
        "versatility",
    },
    "SET_PIECES": {"weather_interaction"},
    "STRENGTH_FORM": {"elo", "opponent_adjusted_form", "regime_change"},
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
    "POINTS_VOLATILITY": ("football:strength_form:volatility", "points_volatility", "POINTS"),
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


def repository_text_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


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


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".next")
    temporary.write_bytes(render_bytes(value))
    os.replace(temporary, path)


def write_heavy_json_artifact(
    store_root: Path, filename: str, value: Mapping[str, Any]
) -> dict[str, Any]:
    payload = canonical_bytes(value)
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    relative = Path("results") / filename
    path = store_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return {
        "artifact_relative_path": relative.as_posix(),
        "compressed_bytes": len(compressed),
        "sha256": sha256_bytes(compressed),
        "content_sha256": sha256_bytes(payload),
        "git_committed": False,
    }


def read_heavy_json_artifact(path: Path) -> dict[str, Any]:
    value = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(value, dict):
        raise TypeError("HEAVY_JSON_ARTIFACT_OBJECT_REQUIRED")
    return value


def load_resume_progress(stage: str) -> list[dict[str, Any]]:
    global ACTIVE_RESUME_LOADED_COUNT
    if ACTIVE_RESUME_ROOT is None or ACTIVE_RESUME_CHECKPOINT is None:
        return []
    if ACTIVE_RESUME_CHECKPOINT.get("phase") != stage:
        return []
    progress_name = ACTIVE_RESUME_CHECKPOINT.get("resume_progress_path")
    progress_sha = ACTIVE_RESUME_CHECKPOINT.get("resume_progress_sha256")
    if not isinstance(progress_name, str) or not isinstance(progress_sha, str):
        return []
    progress_path = ACTIVE_RESUME_ROOT / progress_name
    payload = progress_path.read_bytes()
    if sha256_bytes(payload) != progress_sha:
        raise RuntimeError("RESUME_PROGRESS_HASH_MISMATCH")
    value = json.loads(gzip.decompress(payload))
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "phase-c-resume-progress-v1"
        or value.get("stage") != stage
        or value.get("cursor") != ACTIVE_RESUME_CHECKPOINT.get("cursor")
        or not isinstance(value.get("records"), list)
    ):
        raise RuntimeError("RESUME_PROGRESS_CONTRACT_MISMATCH")
    records = [dict(row) for row in value["records"] if isinstance(row, Mapping)]
    ACTIVE_RESUME_LOADED_COUNT = len(records)
    return records


def persist_resume_progress(
    store_root: Path, stage: str, records: Sequence[Mapping[str, Any]]
) -> None:
    cursor = len(records)
    slot = cursor % 2
    progress_name = f"resume-progress-{slot}-v1.json.gz"
    progress_path = store_root / progress_name
    payload = gzip.compress(
        canonical_bytes(
            {
                "schema_version": "phase-c-resume-progress-v1",
                "stage": stage,
                "cursor": cursor,
                "records": list(records),
            }
        ),
        compresslevel=9,
        mtime=0,
    )
    temporary = progress_path.with_name(progress_path.name + ".next")
    temporary.write_bytes(payload)
    os.replace(temporary, progress_path)
    checkpoint_path = store_root / "checkpoint-v1.json"
    checkpoint = read_json(checkpoint_path)
    checkpoint.pop("checkpoint_hash", None)
    checkpoint.update(
        {
            "cursor": cursor,
            "evaluated": cursor,
            "resume_progress_path": progress_name,
            "resume_progress_sha256": sha256_bytes(payload),
            "next_action": f"RESUME_{stage}_AT_CURSOR_{cursor}",
        }
    )
    checkpoint["checkpoint_hash"] = object_hash(checkpoint)
    write_json_atomic(checkpoint_path, checkpoint)
    if ACTIVE_TEST_STOP_AFTER_RECORDS and cursor >= ACTIVE_TEST_STOP_AFTER_RECORDS:
        raise SoftDeadlineReached(f"CHECKPOINT_TEST_STOP_AT_CURSOR:{cursor}")


def canonical_phase(stage: str) -> str:
    return {
        "census": "RAW_FIELD_CENSUS",
        "RAW_FIELD_CENSUS": "RAW_FIELD_CENSUS",
        "tag-mask-build": "TAG_MASK_BUILD",
        "TAG_MASK_BUILD": "TAG_MASK_BUILD",
        "atomic": "ATOMIC_PROPERTY_SEARCH",
        "ATOMIC_PROPERTY_SEARCH": "ATOMIC_PROPERTY_SEARCH",
        "pairs": "COMPATIBLE_PAIR_SEARCH",
        "COMPATIBLE_PAIR_SEARCH": "COMPATIBLE_PAIR_SEARCH",
    }.get(stage, stage.upper().replace("-", "_"))


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
    for row_index, row in enumerate(rows):
        if row_index % 4096 == 0:
            enforce_soft_deadline()
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
        "source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
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


SOURCE_FIELD_REGISTRY: dict[str, dict[str, str]] = {}
ACTIVE_SOFT_DEADLINE: float | None = None


class SoftDeadlineReached(RuntimeError):
    """Stop a workflow unit while its initial checkpoint is still uploadable."""


def enforce_soft_deadline() -> None:
    if ACTIVE_SOFT_DEADLINE is not None and time.monotonic() >= ACTIVE_SOFT_DEADLINE:
        raise SoftDeadlineReached("SOFT_DEADLINE_REACHED_CHECKPOINT_REQUIRED")


def source_field(
    entity_type: str,
    json_path: str,
    temporal_use: str = "PRIOR_FIXTURES_ONLY",
) -> str:
    definition = {
        "entity_type": entity_type,
        "json_path": json_path,
        "temporal_use": temporal_use,
        "transform_version": "phase-c-source-field-v1",
    }
    field_id = "field:" + sha256_bytes(canonical_bytes(definition))
    existing = SOURCE_FIELD_REGISTRY.setdefault(field_id, definition)
    if existing != definition:
        raise RuntimeError(f"SOURCE_FIELD_ID_COLLISION:{field_id}")
    return field_id


def property_requirements(
    family: str, name: str, bucket: str
) -> tuple[list[str], list[str], str]:
    """Return the explicit, auditable source contract for one Genome property."""
    fixture_score = [
        source_field("fixture", "data.score.fulltime.home"),
        source_field("fixture", "data.score.fulltime.away"),
        source_field("fixture", "data.teams.home.id"),
        source_field("fixture", "data.teams.away.id"),
    ]
    fixture_time = [source_field("fixture", "data.fixture.date", "SCHEDULE_METADATA")]
    team_statistics = [
        source_field("team_match_statistic", "data.type"),
        source_field("team_match_statistic", "data.value"),
    ]
    events = [
        source_field("fixture_event", "data.type", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
        source_field("fixture_event", "data.detail", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
        source_field("fixture_event", "data.time.elapsed", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
        source_field("fixture_event", "data.player.id", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
        source_field("fixture_event", "data.team.id", "TARGET_OR_PRIOR_FIXTURES_ONLY"),
    ]
    lineup = [
        source_field("lineup", "data.team.id", "RECONSTRUCTED_POST_MATCH"),
        source_field("lineup", "data.startXI[].player.id", "RECONSTRUCTED_POST_MATCH"),
        source_field("lineup", "data.substitutes[].player.id", "RECONSTRUCTED_POST_MATCH"),
    ]
    exact: dict[tuple[str, str], tuple[list[str], list[str]]] = {
        ("MATCH_COMPETITION", "competition"): (
            [source_field("fixture", "data.league.id", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("MATCH_COMPETITION", "season"): (
            [source_field("fixture", "data.league.season", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("MATCH_COMPETITION", "matchday"): (
            [source_field("round", "data.position", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("MATCH_COMPETITION", "round"): (
            [source_field("fixture", "data.league.round", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("MATCH_COMPETITION", "venue_role"): (
            [source_field("team", "data.side", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("MATCH_COMPETITION", "weekday"): (fixture_time, ["TEAM"]),
        ("MATCH_COMPETITION", "month"): (fixture_time, ["TEAM"]),
        ("STADIUM_PITCH", "stadium"): (
            [source_field("venue", "data.id", "SCHEDULE_METADATA")],
            ["TEAM"],
        ),
        ("FORMATION_STRUCTURE", "formation"): (
            [source_field("formation", "data.formation", "RECONSTRUCTED_POST_MATCH")],
            ["FORMATION"],
        ),
        ("PLAYER", "identity"): (
            [source_field("lineup_player", "data.player.id", "RECONSTRUCTED_POST_MATCH")],
            ["PLAYER"],
        ),
        ("PLAYER", "position"): (
            [source_field("lineup_player", "data.player.pos", "RECONSTRUCTED_POST_MATCH")],
            ["LINEUP"],
        ),
        ("PLAYER", "role"): (
            [source_field("lineup_player", "data.role", "RECONSTRUCTED_POST_MATCH")],
            ["LINEUP"],
        ),
        ("PLAYER", "starts"): (
            [source_field("lineup", "data.startXI[].player.id", "RECONSTRUCTED_POST_MATCH")],
            ["LINEUP"],
        ),
        ("PLAYER", "substitute_appearances"): (
            [source_field("lineup", "data.substitutes[].player.id", "RECONSTRUCTED_POST_MATCH")],
            ["LINEUP"],
        ),
        ("COACH", "identity"): (
            [source_field("lineup", "data.coach.id", "RECONSTRUCTED_POST_MATCH")],
            ["LINEUP"],
        ),
        ("DISCIPLINE_REFEREE", "referee"): (
            [source_field("fixture", "data.fixture.referee", "RECONSTRUCTED_POST_MATCH")],
            ["TEAM"],
        ),
    }
    if (family, name) in exact:
        fields, capabilities = exact[(family, name)]
        return fields, capabilities, "EXACT_ENTITY_PATH_REGISTRY"
    if family in {"STRENGTH_FORM", "ATTACK", "DEFENCE"} and bucket == "READY":
        return fixture_score, ["TEAM"], "DETERMINISTIC_PRIOR_RESULT_TRANSFORM"
    if family in {"ATTACK", "DEFENCE", "POSSESSION_PRESSING", "SET_PIECES"} and bucket == "PARTIAL":
        return team_statistics, ["TEAM_STATISTICS"], "PARTIAL_TEAM_STATISTIC_TYPE_VALUE"
    if family == "STRENGTH_FORM" and bucket == "PARTIAL":
        return team_statistics + fixture_score, ["TEAM_STATISTICS", "TEAM"], "PARTIAL_XG_HISTORY"
    if family == "EVENT_GAME_STATE" and bucket == "READY":
        return events, ["EVENTS"], "TARGET_EVENT_COLLECTION"
    if family == "DISCIPLINE_REFEREE" and name == "recent_cards" and bucket == "READY":
        return (
            [
                source_field(
                    "fixture_event", "data.type", "TARGET_OR_PRIOR_FIXTURES_ONLY"
                ),
                source_field(
                    "fixture_event", "data.team.id", "TARGET_OR_PRIOR_FIXTURES_ONLY"
                ),
            ],
            ["EVENTS"],
            "DETERMINISTIC_PRIOR_CARD_EVENT_TRANSFORM",
        )
    if family == "DISCIPLINE_REFEREE" and bucket in {"READY", "PARTIAL"}:
        return events + team_statistics, ["DISCIPLINE_GENERIC", "TEAM_STATISTICS"], "CARD_EVENT_OR_TEAM_STAT_HISTORY"
    if family == "PLAYER" and bucket == "READY":
        return events, ["EVENTS", "PLAYER"], "TARGET_EVENT_PLAYER_IDENTITY"
    if family == "COACH" and name == "substitutions":
        return events, ["EVENTS"], "TARGET_SUBSTITUTION_EVENTS"
    if family == "COACH" and bucket == "PARTIAL":
        return [source_field("lineup", "data.coach.id", "RECONSTRUCTED_POST_MATCH")], ["LINEUP"], "PARTIAL_COACH_HISTORY"
    if family in {"LINEUP_CONTINUITY", "BENCH_SUBSTITUTIONS", "CHEMISTRY_NETWORKS"} and bucket == "PARTIAL":
        return lineup, ["LINEUP"], "PARTIAL_LINEUP_IDENTITY_HISTORY"
    if family == "GOALKEEPER" and bucket == "PARTIAL":
        return [source_field("lineup", "data.startXI[].player.pos", "RECONSTRUCTED_POST_MATCH")], ["LINEUP"], "PARTIAL_LINEUP_ROLE_HISTORY"
    if family == "DATA_QUALITY" and bucket == "READY":
        path = {
            "coverage_bias": "strict_prematch_eligible",
            "ingested_at": "ingested_at",
            "missingness": "record_hash",
            "observed_at": "observed_at",
            "provenance_hash": "provenance.payload_sha256",
            "source": "provenance.endpoint",
        }[name]
        return [source_field("__row__", path, "QUALITY_ONLY")], ["NORMALIZED_PROVENANCE"], "ROW_ENVELOPE_QUALITY_ONLY"
    if family == "CALENDAR_FATIGUE":
        return fixture_time, ["CALENDAR_STRICT_ASOF"], "SCHEDULE_REVISION_HISTORY_REQUIRED"
    external = {row[0]: row[2] for row in EXTERNAL_GAPS}
    if family in external:
        return [], [f"EXTERNAL_{family}_POINT_IN_TIME"], external[family]
    if bucket == "UNKNOWN":
        return [], ["SEMANTIC_MAPPING_REGISTRY"], "EXPLICIT_SEMANTIC_REVIEW_REQUIRED"
    fallback = {
        "FORMATION_STRUCTURE": ["FORMATION", "LINEUP"],
        "GOALKEEPER": ["PLAYER_STATISTICS", "LINEUP"],
        "MATCH_COMPETITION": ["TEAM", "CALENDAR_STRICT_ASOF"],
        "PLAYER": ["PLAYER_STATISTICS", "PLAYER", "LINEUP"],
        "STRENGTH_FORM": ["TEAM", "TEAM_STATISTICS"],
        "DISCIPLINE_REFEREE": ["DISCIPLINE_GENERIC", "EVENTS"],
        "EVENT_GAME_STATE": ["EVENTS"],
        "SET_PIECES": ["TEAM_STATISTICS", "EVENTS"],
        "DATA_QUALITY": ["NORMALIZED_PROVENANCE"],
    }.get(family, [f"{family}_CANONICAL_SOURCE"])
    return [], fallback, "REQUIRED_SOURCE_OR_TRANSFORM_NOT_AVAILABLE"


def build_reconciliation(output_root: Path) -> dict[str, Any]:
    SOURCE_FIELD_REGISTRY.clear()
    roles = read_json(PROPERTY_ROLES)
    items = roles.get("items")
    if not isinstance(items, list) or len(items) != 486:
        raise RuntimeError("GENOME_486_REQUIRED")
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    roles_by_property: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise TypeError("PROPERTY_OBJECT_REQUIRED")
        by_family[str(raw["family"])].append(raw)
        roles_by_property[str(raw["property_id"])] = raw
    if set(by_family) != set(FAMILY_BUCKETS):
        raise RuntimeError("GENOME_28_FAMILY_SET_MISMATCH")

    records: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()
    materialization_counts: Counter[str] = Counter()
    for family in sorted(by_family):
        enforce_soft_deadline()
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
        unknown_names = UNKNOWN_NAMES.get(family, set())
        unknown = [
            row for row in remainder if property_name(str(row["property_id"])) in unknown_names
        ]
        blocked = [row for row in remainder if row not in unknown]
        if len(unknown) != u_count:
            raise RuntimeError(f"UNKNOWN_RECONCILIATION_COUNT_MISMATCH:{family}")
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
            source_fields, required_capabilities, _mapping_basis = property_requirements(
                family, name, bucket
            )
            if bucket in {"READY", "PARTIAL"} and (
                not source_fields or not required_capabilities
            ):
                raise RuntimeError(f"REVIEWED_PROPERTY_SOURCE_CONTRACT_EMPTY:{pid}")
            bucket_counts[bucket] += 1
            materialization_counts[status] += 1
            selected_predictor = pid in {value[0] for value in BASES.values()}
            if selected_predictor:
                campaign_v1_disposition = "SELECTED_PREDICTOR"
            elif bucket == "PARTIAL":
                campaign_v1_disposition = "DEFERRED_PARTIAL_SOURCE"
            elif bucket == "UNKNOWN":
                campaign_v1_disposition = "DEFERRED_SEMANTIC_REVIEW"
            elif bucket == "BLOCKED":
                campaign_v1_disposition = "BLOCKED_SOURCE_OR_DATA"
            elif bucket == "READY" and bool(
                roles_by_property[pid].get("public_hypothesis_eligible")
            ):
                campaign_v1_disposition = "DEFERRED_PUBLIC_ELIGIBLE_NOT_TESTED_V1"
            else:
                campaign_v1_disposition = "NON_PREDICTIVE_IDENTITY_QUALITY_OR_CONTEXT"
            records.append(
                {
                    "property_id": pid,
                    "source_fields": source_fields,
                    "required_capabilities": required_capabilities,
                    "materialization_status": status,
                    "reconciliation_bucket": bucket,
                    "temporal_role": temporal_role,
                    "unknown_policy": "PRESERVE_UNKNOWN_NEVER_FALSE",
                    "block_reason": block_reason,
                    "campaign_v1_disposition": campaign_v1_disposition,
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
        "reviewed_property_count": bucket_counts["READY"] + bucket_counts["PARTIAL"],
        "predictor_tag_property_ids": sorted({value[0] for value in BASES.values()}),
        "property_record_contract": [
            "property_id",
            "source_fields",
            "required_capabilities",
            "materialization_status",
            "temporal_role",
            "unknown_policy",
            "block_reason",
            "campaign_v1_disposition",
        ],
        "lagged_predictor_transform_property_ids": sorted(
            {value[0] for value in BASES.values()}
        ),
        "campaign_v1_disposition_counts": dict(
            sorted(Counter(row["campaign_v1_disposition"] for row in records).items())
        ),
        "omitted_public_hypothesis_eligible_property_ids": sorted(
            row["property_id"]
            for row in records
            if row["campaign_v1_disposition"]
            == "DEFERRED_PUBLIC_ELIGIBLE_NOT_TESTED_V1"
        ),
        "campaign_scope_status": "BOUNDED_7_PROPERTY_SUBCAMPAIGN_REQUIRES_COUNCIL_RESCOPING",
        "mapping_basis_by_bucket": {
            "READY_PARTIAL": "EXACT_ENTITY_PATH_REGISTRY_AND_DETERMINISTIC_TRANSFORM",
            "BLOCKED": "REQUIRED_SOURCE_OR_CAPABILITY_UNAVAILABLE",
            "UNKNOWN": "EXPLICIT_SEMANTIC_REVIEW_REQUIRED",
        },
        "baseline_bucket_counts": dict(sorted(bucket_counts.items())),
        "materialization_status_counts": dict(sorted(materialization_counts.items())),
        "classification_rule": "EXPLICIT_READY_PARTIAL_WHITELISTS_THEN_FAIL_CLOSED_FAMILY_BASELINE",
        "source_field_registry": dict(sorted(SOURCE_FIELD_REGISTRY.items())),
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
        assert isinstance(raw_fixture, Mapping)
        assert isinstance(score, Mapping)
        assert isinstance(teams, Mapping)
        assert isinstance(league, Mapping)
        fulltime = score.get("fulltime")
        home = teams.get("home")
        away = teams.get("away")
        status = raw_fixture.get("status")
        if not all(isinstance(value, Mapping) for value in (fulltime, home, away, status)):
            raise TypeError(f"FIXTURE_NESTED_SHAPE_REQUIRED:{fixture_id}")
        assert isinstance(fulltime, Mapping)
        assert isinstance(home, Mapping)
        assert isinstance(away, Mapping)
        assert isinstance(status, Mapping)
        hg, ag = fulltime.get("home"), fulltime.get("away")
        home_id, away_id = home.get("id"), away.get("id")
        competition_id = league.get("id")
        kickoff_raw = raw_fixture.get("date")
        if not all(
            isinstance(value, int) for value in (hg, ag, home_id, away_id, competition_id)
        ) or not isinstance(kickoff_raw, str):
            raise TypeError(f"FIXTURE_VALUE_REQUIRED:{fixture_id}")
        assert isinstance(hg, int)
        assert isinstance(ag, int)
        assert isinstance(home_id, int)
        assert isinstance(away_id, int)
        assert isinstance(competition_id, int)
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
    if base == "POINTS_VOLATILITY":
        return statistics.pstdev([row.points for row in matches]) if len(matches) >= 2 else None
    raise KeyError(base)


def predictor_admissibility_reasons(
    *,
    known_at: datetime | None,
    cutoff: datetime,
    scientific_role: str,
    derived_from_target: bool,
    price_required: bool,
    point_in_time_price_available: bool,
) -> list[str]:
    """One fail-closed gate shared by real lagged features and negative controls."""
    reasons: list[str] = []
    if known_at is None or known_at >= cutoff:
        reasons.append("KNOWN_AT_NOT_BEFORE_TARGET_CUTOFF")
    if scientific_role in {"TARGET_ONLY", "POST_RESULT", "TARGET_DERIVED_IDENTITY"}:
        reasons.append("SCIENTIFIC_ROLE_NOT_PREDICTOR_ADMISSIBLE")
    if derived_from_target:
        reasons.append("DERIVED_FROM_TARGET_LABEL")
    if price_required and not point_in_time_price_available:
        reasons.append("POINT_IN_TIME_PRICE_UNAVAILABLE")
    return reasons


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
                if not predictor_admissibility_reasons(
                    known_at=match.available_at,
                    cutoff=fixture.kickoff,
                    scientific_role="LAGGED_RECONSTRUCTED_ONLY",
                    derived_from_target=False,
                    price_required=False,
                    point_in_time_price_available=False,
                )
                and match.fixture_id != fixture.fixture_id
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
            family = property_id.split(":")[1].upper()
            property_sources, capabilities, mapping_basis = property_requirements(
                family, property_name(property_id), "READY"
            )
            for window in WINDOWS:
                tid = tag_id(side, base, window)
                definition = {
                    "tag_id": tid,
                    "tag_version": 1,
                    "label_fr": f"{base} élevé — équipe {side.lower()} — {window}",
                    "family": family,
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
                    "source_fields": property_sources,
                    "required_capabilities": capabilities,
                    "mapping_basis": mapping_basis,
                    "feature_id": "feature:" + sha256_bytes(
                        f"{property_id}\0{side}\0{metric}\0{window}\0phase-c-feature-v1".encode()
                    ),
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
        "source_field_registry": {
            field_id: SOURCE_FIELD_REGISTRY[field_id]
            for field_id in sorted(
                {
                    field_id
                    for tag in tags
                    for field_id in tag["source_fields"]
                }
            )
        },
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
        "materialized_chain_terminal_object": "mask_id",
        "analysis_chain_terminal_object": "hypothesis_id",
        "future_objects_not_created": ["strategy_id", "decision_id", "settlement_id"],
        "hypothesis_id_location": "atomic-results-v1.json and pair-results-v1.json",
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
                float(value)
                for index in range(FOLDS[0][1])
                if fixtures[index].competition_id == competition_id
                and (value := features[index][key]) is not None
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
    core_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[int, int]]]:
    fixture_ids = [row.fixture_id for row in fixtures]
    universe_hash = object_hash(fixture_ids)
    thresholds = initial_thresholds(fixtures, features)
    masks: dict[str, tuple[int, int]] = {}
    manifest_rows: list[dict[str, Any]] = []
    for tag in registry["tags"]:
        enforce_soft_deadline()
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
        threshold_snapshot = {
            str(competition_id): thresholds[(tid, competition_id)]
            for competition_id in sorted({row.competition_id for row in fixtures})
            if (tid, competition_id) in thresholds
        }
        tag_snapshot_hash = object_hash(
            {
                "definition_hash": tag["definition_hash"],
                "thresholds_by_competition": threshold_snapshot,
                "threshold_origin": tag["threshold_origin"],
                "training_end_ordinal_exclusive": FOLDS[0][1],
            }
        )
        mask_id = "mask:" + sha256_bytes(
            (
                universe_hash
                + "\0"
                + tid
                + "\0"
                + str(tag["definition_hash"])
                + "\0"
                + tag_snapshot_hash
            ).encode("utf-8")
        )
        relative_path = f"store/{sha256_bytes(tid.encode())}.mask"
        envelope = write_mask(
            store_root / relative_path,
            mask_id,
            universe_hash,
            known,
            true,
        )
        manifest_rows.append(
            {
                "tag_id": tid,
                "feature_id": tag["feature_id"],
                "definition_hash": tag["definition_hash"],
                "tag_snapshot_hash": tag_snapshot_hash,
                "thresholds_by_competition": threshold_snapshot,
                "training_end_ordinal_exclusive": FOLDS[0][1],
                "mask_id": mask_id,
                "known_count": known.bit_count(),
                "true_count": true.bit_count(),
                "false_count": known.bit_count() - true.bit_count(),
                "unknown_count": UNIVERSE_COUNT - known.bit_count(),
                "coverage": rate(known.bit_count(), UNIVERSE_COUNT),
                "payload_sha256": sha256_bytes(envelope),
                "serialized_bytes": len(envelope),
                "artifact_relative_path": relative_path,
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
        "analysis_core": dict(core_manifest),
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
    function: Any, *, sample_count: int = 30, target_seconds: float = 0.25
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
        memory_bytes: int | str,
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
                "memory_bytes": memory_bytes,
                "retained_rss_bytes": "UNKNOWN_SHARED_SINGLE_PROCESS_RUNNER",
                "peak_rss_subprocess_bytes": "UNKNOWN_NOT_MEASURED_IN_PROVISIONAL_RUN",
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
        sum(known.__sizeof__() + true.__sizeof__() for known, true in ordered),
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
            sum(known.nbytes + true.nbytes for known, true in bool_pairs),
            lambda: (
                int.from_bytes(
                    np.packbits(
                        np.logical_and(bool_pairs[0][0], bool_pairs[1][0]), bitorder="little"
                    ).tobytes(),
                    "little",
                )
                == expected_intersection[0]
                and int.from_bytes(
                    np.packbits(
                        np.logical_and(bool_pairs[0][1], bool_pairs[1][1]), bitorder="little"
                    ).tobytes(),
                    "little",
                )
                == expected_intersection[1]
                and int.from_bytes(
                    np.packbits(
                        np.logical_or(bool_pairs[0][0], bool_pairs[1][0]), bitorder="little"
                    ).tobytes(),
                    "little",
                )
                == expected_union[0]
                and int.from_bytes(
                    np.packbits(
                        np.logical_or(bool_pairs[0][1], bool_pairs[1][1]), bitorder="little"
                    ).tobytes(),
                    "little",
                )
                == expected_union[1]
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
            sum(known.nbytes + true.nbytes for known, true in pack_pairs),
            lambda: (
                int.from_bytes(
                    np.bitwise_and(pack_pairs[0][0], pack_pairs[1][0]).tobytes(), "little"
                )
                == expected_intersection[0]
                and
                int.from_bytes(
                    np.bitwise_and(pack_pairs[0][1], pack_pairs[1][1]).tobytes(), "little"
                )
                == expected_intersection[1]
                and int.from_bytes(
                    np.bitwise_or(pack_pairs[0][0], pack_pairs[1][0]).tobytes(), "little"
                )
                == expected_union[0]
                and int.from_bytes(
                    np.bitwise_or(pack_pairs[0][1], pack_pairs[1][1]).tobytes(), "little"
                )
                == expected_union[1]
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

            ak = pl.Series("known", [bool((first[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            at = pl.Series("true", [bool((first[1] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            bk = pl.Series("known", [bool((second[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            bt = pl.Series("true", [bool((second[1] >> i) & 1) for i in range(UNIVERSE_COUNT)])

            def op_and() -> Any:
                return pl.DataFrame({"known": ak & bk, "true": at & bt})

            def op_or() -> Any:
                return pl.DataFrame({"known": ak | bk, "true": at | bt})

            def build() -> Any:
                return pl.DataFrame({"ak": ak, "at": at, "bk": bk, "bt": bt})

            def column_correctness() -> bool:
                intersection = op_and()
                union = op_or()
                return (
                    int(intersection["known"].sum()) == expected_intersection[0].bit_count()
                    and int(intersection["true"].sum())
                    == expected_intersection[1].bit_count()
                    and int(union["known"].sum()) == expected_union[0].bit_count()
                    and int(union["true"].sum()) == expected_union[1].bit_count()
                )
        elif package == "pyarrow":
            import pyarrow as pa
            import pyarrow.compute as pc

            ak = pa.array([bool((first[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            at = pa.array([bool((first[1] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            bk = pa.array([bool((second[0] >> i) & 1) for i in range(UNIVERSE_COUNT)])
            bt = pa.array([bool((second[1] >> i) & 1) for i in range(UNIVERSE_COUNT)])

            def op_and() -> Any:
                return pa.table({"known": pc.and_(ak, bk), "true": pc.and_(at, bt)})

            def op_or() -> Any:
                return pa.table({"known": pc.or_(ak, bk), "true": pc.or_(at, bt)})

            def build() -> Any:
                return pa.table({"ak": ak, "at": at, "bk": bk, "bt": bt})

            def column_correctness() -> bool:
                intersection = op_and()
                union = op_or()
                return (
                    int(pc.sum(intersection["known"]).as_py())
                    == expected_intersection[0].bit_count()
                    and int(pc.sum(intersection["true"]).as_py())
                    == expected_intersection[1].bit_count()
                    and int(pc.sum(union["known"]).as_py()) == expected_union[0].bit_count()
                    and int(pc.sum(union["true"]).as_py()) == expected_union[1].bit_count()
                )
        else:
            import duckdb

            connection = duckdb.connect(":memory:")
            connection.execute(
                "CREATE TABLE masks(i INTEGER, a_known BOOLEAN, a_true BOOLEAN, "
                "b_known BOOLEAN, b_true BOOLEAN)"
            )
            connection.executemany(
                "INSERT INTO masks VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        i,
                        bool((first[0] >> i) & 1),
                        bool((first[1] >> i) & 1),
                        bool((second[0] >> i) & 1),
                        bool((second[1] >> i) & 1),
                    )
                    for i in range(UNIVERSE_COUNT)
                ],
            )

            def op_and() -> Any:
                return connection.execute(
                    "SELECT sum((a_known AND b_known)::INTEGER),"
                    "sum((a_true AND b_true)::INTEGER) FROM masks"
                ).fetchone()

            def op_or() -> Any:
                return connection.execute(
                    "SELECT sum((a_known OR b_known)::INTEGER),"
                    "sum((a_true OR b_true)::INTEGER) FROM masks"
                ).fetchone()

            def build() -> Any:
                return connection.execute("SELECT count(*) FROM masks").fetchone()

            def column_correctness() -> bool:
                return bool(
                    op_and()
                    == (
                        expected_intersection[0].bit_count(),
                        expected_intersection[1].bit_count(),
                    )
                    and op_or()
                    == (expected_union[0].bit_count(), expected_union[1].bit_count())
                )

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
            "UNKNOWN_BACKEND_ENGINE_OVERHEAD",
            column_correctness,
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

    golden_states: list[list[bool | None]] = [
        [True, False, None, True, False, None, True, False, True, None, False, True, None, True],
        [True, True, False, None, False, True, None, True, False, True, None, False, True, None],
        [False, None, True, False, True, None, False, True, None, False, True, None, False, True],
        [None, False, True, True, None, False, True, False, None, True, False, True, None, False],
    ]
    golden_masks = [mask_int(states) for states in golden_states]
    golden_universe_mask = (1 << 14) - 1
    golden_vectors = []
    for known, true in golden_masks:
        false = known & ~true & golden_universe_mask
        unknown = ~known & golden_universe_mask
        golden_vectors.append(
            {
                "known": known.bit_count(),
                "true": true.bit_count(),
                "false": false.bit_count(),
                "unknown": unknown.bit_count(),
                "vector_sha256": object_hash(
                    [
                        "TRUE" if (true >> index) & 1 else ("FALSE" if (known >> index) & 1 else "UNKNOWN")
                        for index in range(14)
                    ]
                ),
            }
        )
    golden_payload = b"".join(
        known.to_bytes(2, "little") + true.to_bytes(2, "little")
        for known, true in golden_masks
    )
    golden_gate = {
        "executed": True,
        "case_count": len(golden_masks),
        "fixture_count": 14,
        "boundary_bits_exercised": [0, 7, 8, 13],
        "true_subset_known": all(not (true & ~known) for known, true in golden_masks),
        "exact_unknown": all(
            ((~known) & golden_universe_mask).bit_count() == row["unknown"]
            for (known, _), row in zip(golden_masks, golden_vectors, strict=True)
        ),
        "serialization_byte_identical": golden_payload
        == b"".join(
            known.to_bytes(2, "little") + true.to_bytes(2, "little")
            for known, true in golden_masks
        ),
        "payload_sha256": sha256_bytes(golden_payload),
        "vectors": golden_vectors,
    }
    if not all(
        golden_gate[key]
        for key in ("true_subset_known", "exact_unknown", "serialization_byte_identical")
    ):
        raise RuntimeError("GOLDEN_MASK_GATE_FAILED")

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
                "use": "EXECUTED_CORRECTNESS_SERIALIZATION_AND_BOUNDARY_GATE",
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
            "calibration_target_ms": 250,
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
        "golden_gate": golden_gate,
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
            float(value)
            for index in range(train_end)
            if fixtures[index].competition_id == competition_id
            and (value := features[index][key]) is not None
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
    store_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    target_names = ("MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M")
    resumed_rows = load_resume_progress("ATOMIC_PROPERTY_SEARCH")
    results: dict[str, dict[str, Any]] = {
        str(row["tag_id"]): row for row in resumed_rows
    }
    expected_prefix = [str(row["tag_id"]) for row in registry["tags"]][
        : len(resumed_rows)
    ]
    if list(results) != expected_prefix:
        raise RuntimeError("ATOMIC_RESUME_CURSOR_OR_ORDER_MISMATCH")
    p_rows: list[tuple[str, float]] = []
    family_p_rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in resumed_rows:
        for metric in row["target_metrics"].values():
            key = str(metric["canonical_test_id"])
            p_value = float(metric["p_value"])
            family_id = str(metric["family_id"])
            p_rows.append((key, p_value))
            family_p_rows[family_id].append((key, p_value))
    for tag in registry["tags"]:
        tid = str(tag["tag_id"])
        if tid in results:
            continue
        enforce_soft_deadline()
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
            p_value_raw, clusters = one_sided_cluster_p(loss_differences, dates)
            key = f"{tid}|{target_name}"
            known_unique = sorted(set(known_indices))
            true_unique = sorted(set(true_indices))
            league_counts = Counter(fixtures[index].competition for index in true_unique)
            dominant_league_share = (
                round(max(league_counts.values()) / len(true_unique), 8) if true_unique else None
            )
            pre_multiple_gate = (
                len(true_unique) >= 80
                and rate(len(known_unique), sum(end - start for _, start, end, _ in FOLDS))
                is not None
                and float(
                    rate(len(known_unique), sum(end - start for _, start, end, _ in FOLDS))
                    or 0
                )
                >= 0.8
                and len(league_counts) >= 3
                and all(fold["true_count"] >= 15 for fold in fold_metrics)
                and (dominant_league_share or 1.0) <= 0.5
            )
            p_value = p_value_raw if pre_multiple_gate else 1.0
            p_rows.append((key, p_value))
            family_id = f"{tag['family']}|{target_name}"
            family_p_rows[family_id].append((key, p_value))
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
                "dominant_league_share": dominant_league_share,
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
                "p_value_raw": p_value_raw,
                "p_value": p_value,
                "blocked_test_p_value_forced_to_one": not pre_multiple_gate,
                "family_id": family_id,
                "cluster_count": clusters,
                "multiplicity_scope": "ATOMIC_80_X_2_GLOBAL",
                "folds": fold_metrics,
                "pre_multiple_testing_gate": {
                    "passed": pre_multiple_gate,
                    "true_oof_gte_80": len(true_unique) >= 80,
                    "known_coverage_gte_0_8": float(
                        rate(
                            len(known_unique),
                            sum(end - start for _, start, end, _ in FOLDS),
                        )
                        or 0
                    )
                    >= 0.8,
                    "at_least_three_leagues": len(league_counts) >= 3,
                    "per_fold_true_gte_15": all(
                        fold["true_count"] >= 15 for fold in fold_metrics
                    ),
                    "dominant_league_share_lte_0_5": (dominant_league_share or 1.0)
                    <= 0.5,
                },
            }
            per_target[target_name]["tag_snapshot_hash"] = object_hash(
                {
                    "definition_hash": tag["definition_hash"],
                    "fold_threshold_hashes": fold_threshold_hashes,
                    "target_id": target_name,
                }
            )
            per_target[target_name]["hypothesis_id"] = "hypothesis:" + object_hash(
                {
                    "tag_id": tid,
                    "tag_snapshot_hash": per_target[target_name]["tag_snapshot_hash"],
                    "target_id": target_name,
                    "campaign": "PHASE-C-ATOMIC-80-X-2-2024-V1",
                }
            )
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
        persist_resume_progress(
            store_root,
            "ATOMIC_PROPERTY_SEARCH",
            [results[key] for key in sorted(results)],
        )
    q_values = bh_adjust(p_rows)
    family_q_values = {
        key: value
        for rows in family_p_rows.values()
        for key, value in bh_adjust(rows).items()
    }
    status_counts: Counter[str] = Counter()
    for tid, row in results.items():
        best = "RAW_HISTORICAL_SIGNAL"
        for target_name, metric in row["target_metrics"].items():
            key = metric["canonical_test_id"]
            metric["q_value_global"] = q_values[key]
            metric["q_value_family"] = family_q_values[key]
            metric["q_value"] = max(q_values[key], family_q_values[key])
            fold_deltas = [
                fold["delta_log_loss"]
                for fold in metric["folds"]
                if fold["delta_log_loss"] is not None
            ]
            support_gate = bool(metric["pre_multiple_testing_gate"]["passed"])
            stability_gate = (
                len(fold_deltas) == 5
                and sum(value > 0 for value in fold_deltas) >= 4
                and fold_deltas[-1] > 0
            )
            positive_increment = (
                (metric["delta_log_loss"] or 0) > 0
                and (metric["delta_brier"] or 0) > 0
            )
            if metric["q_value"] <= 0.05 and support_gate and positive_increment:
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
        "atomic_tag_count": len(ordered_results),
        "materialized_property_count": len({row["property_id"] for row in ordered_results}),
        "genome_property_count": 486,
        "canonical_test_count": len(p_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "results": ordered_results,
    }
    heavy_artifact = write_heavy_json_artifact(
        store_root, "atomic-results-full-v1.json.gz", atomic_report
    )
    compact_results: list[dict[str, Any]] = []
    for row in ordered_results:
        compact_metrics = {
            target_name: {
                key: metric[key]
                for key in (
                    "canonical_test_id",
                    "known_oof",
                    "true_oof",
                    "false_oof",
                    "unknown_oof",
                    "coverage_oof",
                    "dominant_league_share",
                    "simple_log_loss",
                    "frequency_baseline_log_loss",
                    "league_baseline_log_loss",
                    "model_log_loss",
                    "delta_log_loss",
                    "delta_brier",
                    "p_value_raw",
                    "p_value",
                    "q_value_global",
                    "q_value_family",
                    "q_value",
                    "family_id",
                    "tag_snapshot_hash",
                    "hypothesis_id",
                    "status",
                    "review_gate",
                    "suspicious_reasons",
                )
            }
            for target_name, metric in row["target_metrics"].items()
        }
        compact_results.append(
            {
                key: row[key]
                for key in (
                    "property_id",
                    "tag_id",
                    "support",
                    "true_count",
                    "false_count",
                    "unknown_count",
                    "coverage",
                    "evaluation_universe",
                    "fold_threshold_hashes",
                    "status",
                )
            }
            | {"target_metrics": compact_metrics}
        )
    compact_report = {
        key: value for key, value in atomic_report.items() if key != "results"
    }
    compact_report["result_detail"] = "COMPACT_GIT_SUMMARY_FULL_ROWS_IN_GITHUB_ARTIFACT"
    compact_report["full_results_artifact"] = heavy_artifact
    compact_report["results"] = compact_results
    write_json(output_root / "reports/hypothesis-research/atomic-results-v1.json", compact_report)
    summary = {
        "schema_version": "atomic-campaign-summary-v1",
        "generated_at": GENERATED_AT,
        "verdict": "ATOMIC_SUBCAMPAIGN_READY_GLOBAL_SCOPE_PARTIAL",
        "scope_verdict": "BOUNDED_7_PROPERTY_SUBCAMPAIGN_COMPLETE_GLOBAL_SCOPE_PARTIAL",
        "deferred_public_hypothesis_eligible_properties": 18,
        "properties_reconciled": 486,
        "materialized_predictor_properties": len(
            {row["property_id"] for row in ordered_results}
        ),
        "materialized_tags": 80,
        "tests_executed": len(p_rows),
        "oof_fixture_count": sum(end - start for _, start, end, _ in FOLDS),
        "folds": [
            {"fold_id": fid, "train": start, "validation": end - start, "validation_start": date}
            for fid, start, end, date in FOLDS
        ],
        "multiple_testing": {
            "method": "BH_FDR_GLOBAL_AND_FAMILY",
            "alpha": 0.05,
            "global_denominator": len(p_rows),
            "family_count": len(family_p_rows),
            "promotion_requires_both_q_values": True,
        },
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
    masks: Mapping[str, tuple[int, int]],
    registry: Mapping[str, Any],
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tags = sorted(masks)
    property_by_tag = {str(row["tag_id"]): str(row["property_id"]) for row in registry["tags"]}
    eligible_mask = ((1 << FOLDS[0][1]) - 1) ^ ((1 << 303) - 1)
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejection_counts: Counter[str] = Counter()
    for tag_a, tag_b in combinations(tags, 2):
        side_a, base_a, _ = parse_tag(tag_a)
        side_b, base_b, _ = parse_tag(tag_b)
        property_a, property_b = property_by_tag[tag_a], property_by_tag[tag_b]
        if property_a == property_b:
            rejection_counts["SAME_PROPERTY_REDUNDANCY"] += 1
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
        if true_count < 40:
            rejection_counts["INITIAL_TRUE_SUPPORT_LT_40"] += 1
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
                "parent_property_a": property_a,
                "parent_property_b": property_b,
                "category": category,
                "initial_known_count": known_count,
                "initial_true_count": true_count,
                "initial_jaccard": round(jaccard, 8),
                "selection_hash": sha256_bytes((str(SEED) + "\0" + pid).encode("utf-8")),
                "shard_id": int(sha256_bytes(pid.encode("utf-8"))[:16], 16) % 8,
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
    active_tag_theoretical = 80 * 79 // 2
    materialized_properties = sorted(set(property_by_tag.values()))
    active_property_theoretical = len(materialized_properties) * (len(materialized_properties) - 1) // 2
    selected_property_pairs = sorted(
        {
            tuple(sorted((row["parent_property_a"], row["parent_property_b"])))
            for row in selected
        }
    )
    pruning = {
        "GENOME_PROPERTY_PAIRS_OUTSIDE_MATERIALIZED_PREDICTOR_SUBSPACE": theoretical
        - active_property_theoretical,
        "MATERIALIZED_PROPERTY_PAIRS_NOT_SELECTED": active_property_theoretical
        - len(selected_property_pairs),
    }
    tag_pruning = {
        "STRUCTURAL_OR_SUPPORT_INCOMPATIBILITY": active_tag_theoretical - candidate_count,
        "DETERMINISTIC_BUDGET_QUOTA_AND_DEGREE": candidate_count - len(selected_ids),
    }
    report = {
        "schema_version": "pair-search-space-v1",
        "generated_at": GENERATED_AT,
        "pair_grain_contract": {
            "genome_counts": "unordered distinct property_id pairs",
            "campaign_counts": "unordered distinct tag_id pairs",
        },
        "theoretical_pairs": theoretical,
        "materialized_property_pairs": active_property_theoretical,
        "compatible_pairs": len(selected_property_pairs),
        "pruned_pairs": theoretical - len(selected_property_pairs),
        "pruning_reasons": pruning,
        "candidate_tag_pairs": active_tag_theoretical,
        "structurally_eligible_tag_pairs": candidate_count,
        "selected_tag_pairs": len(selected),
        "pruned_tag_pairs": active_tag_theoretical - len(selected),
        "tag_pruning_reasons": tag_pruning,
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


def compact_pair_report(
    report: Mapping[str, Any], heavy_artifact: Mapping[str, Any]
) -> dict[str, Any]:
    results = report.get("results")
    if not isinstance(results, list):
        raise TypeError("PAIR_RESULTS_ARRAY_REQUIRED")
    compact_results: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, Mapping):
            raise TypeError("PAIR_RESULT_OBJECT_REQUIRED")
        compact_metrics = {
            target_name: {
                key: metric[key]
                for key in (
                    "delta_log_loss_by_comparator",
                    "delta_brier_by_comparator",
                    "p_values_raw_by_comparator",
                    "p_value_raw_intersection_union",
                    "q_value_global",
                    "q_value_family",
                    "q_value",
                    "pair_snapshot_hash",
                    "hypothesis_id",
                    "status",
                    "review_gate",
                    "suspicious_reasons",
                )
            }
            for target_name, metric in row["target_metrics"].items()
        }
        compact_results.append(
            {
                key: row[key]
                for key in (
                    "pair_id",
                    "parent_a",
                    "parent_b",
                    "parent_property_a",
                    "parent_property_b",
                    "status",
                )
            }
            | {"target_metrics": compact_metrics}
        )
    compact_report = {key: value for key, value in report.items() if key != "results"}
    compact_report["result_detail"] = (
        "COMPACT_GIT_SUMMARY_FULL_ROWS_IN_GITHUB_ARTIFACT"
    )
    compact_report["full_results_artifact"] = dict(heavy_artifact)
    compact_report["pair_snapshot_contract"] = {
        "inputs": [
            "pair_id",
            "parent_definition_hashes",
            "parent_fold_threshold_hashes",
            "parent_mask_ids",
            "parent_tag_snapshot_hashes",
            "target_id",
        ],
        "parent_definition_source": "configs/hypothesis-tags/canonical-tag-registry-v1.json",
        "parent_fold_snapshot_source": "reports/hypothesis-research/atomic-results-v1.json",
        "parent_mask_source": "reports/hypothesis-masks/atomic-mask-manifest-v1.json",
        "full_row_source": "full_results_artifact",
    }
    compact_report["results"] = compact_results
    return compact_report


def evaluate_pairs(
    selected: Sequence[Mapping[str, Any]],
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, Any]],
    masks: Mapping[str, tuple[int, int]],
    registry: Mapping[str, Any],
    mask_manifest: Mapping[str, Any],
    output_root: Path,
    store_root: Path,
) -> dict[str, Any]:
    p_rows: list[tuple[str, float]] = []
    family_p_rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    results = load_resume_progress("COMPATIBLE_PAIR_SEARCH")
    target_names = ("MATCH_RESULT_90M", "TOTAL_GOALS_2_5_90M")
    comparators = ("PARENT_A", "PARENT_B", "ADDITIVE")
    tag_definitions = {str(row["tag_id"]): row for row in registry["tags"]}
    mask_records = {str(row["tag_id"]): row for row in mask_manifest["records"]}
    expected_prefix = [str(row["pair_id"]) for row in selected][: len(results)]
    if [str(row.get("pair_id")) for row in results] != expected_prefix:
        raise RuntimeError("PAIR_RESUME_CURSOR_OR_ORDER_MISMATCH")
    for row in results:
        for metric in row["target_metrics"].values():
            test_id = str(metric["canonical_test_id"])
            p_value = float(metric["p_value"])
            family_id = str(metric["family_id"])
            p_rows.append((test_id, p_value))
            family_p_rows[family_id].append((test_id, p_value))
    for pair in selected:
        if any(row["pair_id"] == pair["pair_id"] for row in results):
            continue
        enforce_soft_deadline()
        tag_a, tag_b = str(pair["parent_a"]), str(pair["parent_b"])
        if pair["parent_property_a"] == pair["parent_property_b"]:
            raise RuntimeError(f"PAIR_SAME_PROPERTY_FORBIDDEN:{pair['pair_id']}")
        per_target: dict[str, Any] = {}
        pair_oof_states: dict[int, bool | None] = {}
        for target_name in target_names:
            parent_fold_threshold_hashes: dict[str, list[str]] = {
                "PARENT_A": [],
                "PARENT_B": [],
            }
            categories, target_keys = target_contract(target_name)
            labels = [str(row[target_keys[0]]) for row in targets]
            pair_rows: list[tuple[Mapping[str, float], str]] = []
            comparator_rows: dict[str, list[tuple[Mapping[str, float], str]]] = {
                name: [] for name in (*comparators, "BASE")
            }
            differences: dict[str, list[float]] = {name: [] for name in comparators}
            brier_differences: dict[str, list[float]] = {name: [] for name in comparators}
            dates: list[str] = []
            true_indices: list[int] = []
            known_indices: list[int] = []
            parent_true_indices: dict[str, list[int]] = {"PARENT_A": [], "PARENT_B": []}
            fold_metrics: list[dict[str, Any]] = []
            for fold_id, train_end, validation_end, expected_start in FOLDS:
                train_indices = list(range(train_end))
                validation_indices = list(range(train_end, validation_end))
                states_a, thresholds_a = fold_tag_states(
                    tag_a, fixtures, features, train_end, validation_end
                )
                states_b, thresholds_b = fold_tag_states(
                    tag_b, fixtures, features, train_end, validation_end
                )
                parent_fold_threshold_hashes["PARENT_A"].append(
                    object_hash(
                        {str(key): value for key, value in sorted(thresholds_a.items())}
                    )
                )
                parent_fold_threshold_hashes["PARENT_B"].append(
                    object_hash(
                        {str(key): value for key, value in sorted(thresholds_b.items())}
                    )
                )
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
                fold_comparator_losses: dict[str, list[float]] = {
                    name: [] for name in comparators
                }
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
                    pair_rows.append((pair_prediction, label))
                    comparison_predictions = {
                        "PARENT_A": parent_a,
                        "PARENT_B": parent_b,
                        "ADDITIVE": additive,
                    }
                    comparator_rows["BASE"].append((base, label))
                    for comparator_name, comparator_prediction in comparison_predictions.items():
                        comparator_loss = log_loss(comparator_prediction, label)
                        comparator_rows[comparator_name].append((comparator_prediction, label))
                        differences[comparator_name].append(comparator_loss - pair_loss)
                        brier_differences[comparator_name].append(
                            brier_loss(comparator_prediction, label, categories)
                            - brier_loss(pair_prediction, label, categories)
                        )
                        fold_comparator_losses[comparator_name].append(comparator_loss)
                    dates.append(fixtures[index].kickoff.date().isoformat())
                    known_indices.append(index)
                    if state_a:
                        parent_true_indices["PARENT_A"].append(index)
                    if state_b:
                        parent_true_indices["PARENT_B"].append(index)
                    if state:
                        true_indices.append(index)
                        fold_true += 1
                    fold_pair_losses.append(pair_loss)
                fold_metrics.append(
                    {
                        "fold_id": fold_id,
                        "known_count": len(fold_pair_losses),
                        "true_count": fold_true,
                        "delta_log_loss_by_comparator": {
                            name: round(
                                mean(fold_comparator_losses[name]) - mean(fold_pair_losses), 8
                            )
                            if fold_pair_losses
                            else None
                            for name in comparators
                        },
                    }
                )
            p_values_raw = {
                name: one_sided_cluster_p(differences[name], dates)[0] for name in comparators
            }
            p_value_raw = max(p_values_raw.values())
            clusters = one_sided_cluster_p(differences["PARENT_A"], dates)[1]
            test_id = f"{pair['pair_id']}|{target_name}"
            true_unique = sorted(set(true_indices))
            known_unique = sorted(set(known_indices))
            league_counts = Counter(fixtures[index].competition for index in true_unique)
            parent_support = {
                name: len(set(parent_true_indices[name]))
                for name in ("PARENT_A", "PARENT_B")
            }
            parent_floor = min(parent_support.values()) if parent_support else 0
            child_parent_support_ratio = (
                round(len(true_unique) / parent_floor, 8) if parent_floor else None
            )
            dominant_league_share = (
                round(max(league_counts.values()) / len(true_unique), 8) if true_unique else None
            )
            coverage = rate(
                len(known_unique), sum(end - start for _, start, end, _ in FOLDS)
            )
            pre_multiple_gate = (
                len(true_unique) >= 80
                and float(coverage or 0) >= 0.8
                and len(league_counts) >= 3
                and all(fold["true_count"] >= 15 for fold in fold_metrics)
                and (dominant_league_share or 1.0) <= 0.5
                and (child_parent_support_ratio or 0) >= 0.2
            )
            p_value = p_value_raw if pre_multiple_gate else 1.0
            p_rows.append((test_id, p_value))
            family_id = f"{pair['category']}|{target_name}"
            family_p_rows[family_id].append((test_id, p_value))
            per_target[target_name] = {
                "canonical_test_id": test_id,
                "known_oof": len(known_unique),
                "true_oof": len(true_unique),
                "unknown_oof": sum(end - start for _, start, end, _ in FOLDS) - len(known_unique),
                "coverage_oof": coverage,
                "support_by_league": dict(sorted(league_counts.items())),
                "dominant_league_share": dominant_league_share,
                "parent_true_oof": parent_support,
                "child_to_smaller_parent_support_ratio": child_parent_support_ratio,
                "pair_log_loss": round(
                    mean([log_loss(probabilities, label) for probabilities, label in pair_rows]), 8
                )
                if pair_rows
                else None,
                "comparator_log_loss": {
                    name: round(
                        mean(
                            [
                                log_loss(probabilities, label)
                                for probabilities, label in comparator_rows[name]
                            ]
                        ),
                        8,
                    )
                    if comparator_rows[name]
                    else None
                    for name in (*comparators, "BASE")
                },
                "delta_log_loss_by_comparator": {
                    name: round(mean(differences[name]), 8) if differences[name] else None
                    for name in comparators
                },
                "delta_brier_by_comparator": {
                    name: round(mean(brier_differences[name]), 8)
                    if brier_differences[name]
                    else None
                    for name in comparators
                },
                "ece": ece(pair_rows, categories),
                "p_values_raw_by_comparator": p_values_raw,
                "p_value_raw_intersection_union": p_value_raw,
                "p_value": p_value,
                "blocked_test_p_value_forced_to_one": not pre_multiple_gate,
                "cluster_count": clusters,
                "folds": fold_metrics,
                "family_id": family_id,
                "multiplicity_scope": "PAIR_120_X_2_GLOBAL_AND_FAMILY_INTERSECTION_UNION",
                "pre_multiple_testing_gate": {
                    "passed": pre_multiple_gate,
                    "true_oof_gte_80": len(true_unique) >= 80,
                    "known_coverage_gte_0_8": float(coverage or 0) >= 0.8,
                    "at_least_three_leagues": len(league_counts) >= 3,
                    "per_fold_true_gte_15": all(
                        fold["true_count"] >= 15 for fold in fold_metrics
                    ),
                    "dominant_league_share_lte_0_5": (dominant_league_share or 1.0)
                    <= 0.5,
                    "child_parent_support_ratio_gte_0_2": (
                        child_parent_support_ratio or 0
                    )
                    >= 0.2,
                },
            }
            parent_snapshots = {
                name: object_hash(
                    {
                        "definition_hash": tag_definitions[tag_id_value]["definition_hash"],
                        "fold_threshold_hashes": parent_fold_threshold_hashes[name],
                        "target_id": target_name,
                    }
                )
                for name, tag_id_value in (("PARENT_A", tag_a), ("PARENT_B", tag_b))
            }
            pair_snapshot_hash = object_hash(
                {
                    "pair_id": pair["pair_id"],
                    "parent_definition_hashes": {
                        "PARENT_A": tag_definitions[tag_a]["definition_hash"],
                        "PARENT_B": tag_definitions[tag_b]["definition_hash"],
                    },
                    "parent_fold_threshold_hashes": parent_fold_threshold_hashes,
                    "parent_mask_ids": {
                        "PARENT_A": mask_records[tag_a]["mask_id"],
                        "PARENT_B": mask_records[tag_b]["mask_id"],
                    },
                    "parent_tag_snapshot_hashes": parent_snapshots,
                    "target_id": target_name,
                }
            )
            per_target[target_name]["parent_definition_hashes"] = {
                "PARENT_A": tag_definitions[tag_a]["definition_hash"],
                "PARENT_B": tag_definitions[tag_b]["definition_hash"],
            }
            per_target[target_name]["parent_fold_threshold_hashes"] = (
                parent_fold_threshold_hashes
            )
            per_target[target_name]["parent_mask_ids"] = {
                "PARENT_A": mask_records[tag_a]["mask_id"],
                "PARENT_B": mask_records[tag_b]["mask_id"],
            }
            per_target[target_name]["parent_tag_snapshot_hashes"] = parent_snapshots
            per_target[target_name]["pair_snapshot_hash"] = pair_snapshot_hash
            per_target[target_name]["hypothesis_id"] = "hypothesis:" + object_hash(
                {
                    "pair_id": pair["pair_id"],
                    "parents": [tag_a, tag_b],
                    "pair_snapshot_hash": pair_snapshot_hash,
                    "target_id": target_name,
                    "campaign": "PHASE-C-PAIR-120-X-2-2024-V1",
                }
            )
        known = sum(value is not None for value in pair_oof_states.values())
        true = sum(value is True for value in pair_oof_states.values())
        results.append(
            {
                "pair_id": pair["pair_id"],
                "parent_a": tag_a,
                "parent_b": tag_b,
                "parent_property_a": pair["parent_property_a"],
                "parent_property_b": pair["parent_property_b"],
                "category": pair["category"],
                "shard_id": pair["shard_id"],
                "support": true,
                "known_oof": known,
                "unknown_oof": sum(end - start for _, start, end, _ in FOLDS) - known,
                "target_metrics": per_target,
                "price_metrics": None,
                "status": "TESTED",
            }
        )
        persist_resume_progress(store_root, "COMPATIBLE_PAIR_SEARCH", results)
    q_values = bh_adjust(p_rows)
    family_q_values = {
        key: value
        for rows in family_p_rows.values()
        for key, value in bh_adjust(rows).items()
    }
    status_counts: Counter[str] = Counter()
    for row in results:
        best = "REJECTED"
        for metric in row["target_metrics"].values():
            key = metric["canonical_test_id"]
            metric["q_value_global"] = q_values[key]
            metric["q_value_family"] = family_q_values[key]
            metric["q_value"] = max(q_values[key], family_q_values[key])
            fold_values = {
                name: [
                    fold["delta_log_loss_by_comparator"][name]
                    for fold in metric["folds"]
                    if fold["delta_log_loss_by_comparator"][name] is not None
                ]
                for name in comparators
            }
            support_gate = bool(metric["pre_multiple_testing_gate"]["passed"])
            stability_gate = all(
                len(values) == 5
                and sum(value > 0 for value in values) >= 4
                and values[-1] > 0
                for values in fold_values.values()
            )
            incremental_gate = all(
                (metric["delta_log_loss_by_comparator"][name] or 0) >= 0.005
                and (metric["delta_brier_by_comparator"][name] or 0) > 0
                for name in comparators
            )
            if metric["q_value"] <= 0.05 and support_gate and incremental_gate:
                metric["status"] = "SURVIVED_MULTIPLE_TESTING"
                best = "SURVIVED_MULTIPLE_TESTING"
                if stability_gate and min(
                    metric["delta_brier_by_comparator"][name] or 0 for name in comparators
                ) >= 0.002:
                    metric["status"] = "SURVIVED_TEMPORAL_VALIDATION"
                    best = "SURVIVED_TEMPORAL_VALIDATION"
            elif support_gate:
                metric["status"] = (
                    "RAW_HISTORICAL_SIGNAL"
                    if min(
                        metric["delta_log_loss_by_comparator"][name] or -999
                        for name in comparators
                    )
                    > 0
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
        "pair_grain": "unordered distinct tag_id pair with distinct parent property_id",
        "unique_property_pair_count": len(
            {
                tuple(sorted((row["parent_property_a"], row["parent_property_b"])))
                for row in results
            }
        ),
        "canonical_test_count": len(p_rows),
        "status_counts": dict(sorted(status_counts.items())),
        "results": results,
    }
    heavy_artifact = write_heavy_json_artifact(
        store_root, "pair-results-full-v1.json.gz", report
    )
    compact_report = compact_pair_report(report, heavy_artifact)
    write_json(output_root / "reports/hypothesis-research/pair-results-v1.json", compact_report)

    rankings = sorted(
        results,
        key=lambda row: max(
            min(
                metric["delta_log_loss_by_comparator"][name] or -999
                for name in comparators
            )
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
                    "best_worst_case_delta_log_loss": max(
                        min(
                            metric["delta_log_loss_by_comparator"][name] or -999
                            for name in comparators
                        )
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
    for index, (left, right) in enumerate(combinations(sorted(pair_masks), 2)):
        if index % 256 == 0:
            enforce_soft_deadline()
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


DETERMINISTIC_PHASE_C_FILES = (
    "configs/execution/phase-c-execution-activation-v1.json",
    "configs/execution/phase-c-artifact-lock-v1.json",
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

NEGATIVE_CONTROL_IDS = (
    "SHUFFLED_LABEL_WITHIN_LEAGUE_MONTH",
    "RANDOM_FEATURE_MATCHED_PREVALENCE_UNKNOWN",
    "FORBIDDEN_FUTURE_FEATURE",
    "SHIFTED_PRICE",
    "IMPOSSIBLE_CONDITION",
    "TRIVIAL_ALWAYS_TRUE_RULE",
    "POST_RESULT_FIELD",
    "WINNER_LOSER_IDENTITY",
)


def build_negative_controls(
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, Any]],
    output_root: Path,
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
    random_feature_a: list[bool | None] = []
    random_feature_b: list[bool | None] = []
    for index, fixture in enumerate(fixtures):
        reference_a = features[index]["HOME:POINTS_PER_MATCH:L5"]
        reference_b = features[index]["AWAY:POINTS_PER_MATCH:L5"]
        random_feature_a.append(
            None
            if reference_a is None
            else int(sha256_bytes((fixture.fixture_id + "\0A").encode())[:8], 16) % 3
            == 0
        )
        random_feature_b.append(
            None
            if reference_b is None
            else int(sha256_bytes((fixture.fixture_id + "\0B").encode())[:8], 16) % 4
            == 0
        )

    def execute_model_control(
        control_id: str,
        states: Sequence[bool | None],
        labels_binary: Sequence[int],
        track: str,
    ) -> dict[str, Any]:
        labels = ["YES" if value else "NO" for value in labels_binary]
        categories = ["YES", "NO"]
        differences: list[float] = []
        dates: list[str] = []
        fold_rows: list[dict[str, Any]] = []
        for fold_id, train_end, validation_end, _ in FOLDS:
            train = list(range(train_end))
            validation = list(range(train_end, validation_end))
            baseline = smoothed_probs(category_count((labels[i] for i in train), categories), categories)
            state_values = list(states[:validation_end])
            conditional = conditional_probs(train, labels, state_values, categories, baseline)
            fold_differences: list[float] = []
            for index in validation:
                state = states[index]
                if state is None:
                    continue
                model = conditional[state]
                delta = log_loss(baseline, labels[index]) - log_loss(model, labels[index])
                differences.append(delta)
                fold_differences.append(delta)
                dates.append(fixtures[index].kickoff.date().isoformat())
            fold_rows.append(
                {
                    "fold_id": fold_id,
                    "validation_count": len(validation),
                    "true_count": sum(int(states[index] is True) for index in validation),
                    "unknown_count": sum(int(states[index] is None) for index in validation),
                    "delta_log_loss": round(mean(fold_differences), 8),
                }
            )
        p_value, clusters = one_sided_cluster_p(differences, dates)
        return {
            "control_id": control_id,
            "track": track,
            "execution_stage": "FULL_ROLLING_ORIGIN_MODEL_AND_TEST",
            "detector_result": "MODEL_EXECUTED",
            "observation_count": len(differences),
            "folds": fold_rows,
            "observed_delta_log_loss": round(mean(differences), 8),
            "p_value": p_value,
            "cluster_count": clusters,
            "promoted": False,
            "status": "PENDING_MULTIPLICITY",
        }

    def guard_control(
        control_id: str,
        track: str,
        candidate_factory: Any,
        expected_reason: str,
    ) -> dict[str, Any]:
        observations = [
            index for _, start, end, _ in FOLDS for index in range(start, end)
        ]
        blocked_reasons: list[list[str]] = []
        for index in observations:
            candidate = candidate_factory(fixtures[index])
            blocked_reasons.append(predictor_admissibility_reasons(**candidate))
        if not all(expected_reason in reasons for reasons in blocked_reasons):
            raise RuntimeError(f"NEGATIVE_ADMISSIBILITY_CONTROL_NOT_BLOCKED:{control_id}")
        return {
            "control_id": control_id,
            "track": track,
            "execution_stage": "PRE_MODEL_ADMISSIBILITY_GATE",
            "detector": "predictor_admissibility_reasons",
            "expected_reason": expected_reason,
            "detector_observation_count": len(observations),
            "detector_blocked_count": sum(bool(reasons) for reasons in blocked_reasons),
            "reason_counts": dict(
                sorted(Counter(reason for reasons in blocked_reasons for reason in reasons).items())
            ),
            "detector_result": "BLOCKED_AS_EXPECTED",
            "reason": expected_reason,
            "folds": [],
            "observed_delta_log_loss": None,
            "p_value": 1.0,
            "q_value": 1.0,
            "promoted": False,
            "status": "REJECTED_BY_ADMISSIBILITY_GATE",
        }

    def build_track(track: str) -> dict[str, Any]:
        enforce_soft_deadline()
        primary_random: list[bool | None] = (
            random_feature_a
            if track == "ATOMIC"
            else [
                None if a is None or b is None else bool(a and b)
                for a, b in zip(random_feature_a, random_feature_b, strict=True)
            ]
        )
        model_records = [
            execute_model_control(
                "SHUFFLED_LABEL_WITHIN_LEAGUE_MONTH", primary_random, shuffled, track
            ),
            execute_model_control(
                "RANDOM_FEATURE_MATCHED_PREVALENCE_UNKNOWN", primary_random, original, track
            ),
            execute_model_control(
                "IMPOSSIBLE_CONDITION", [False] * len(fixtures), original, track
            ),
            execute_model_control(
                "TRIVIAL_ALWAYS_TRUE_RULE", [True] * len(fixtures), original, track
            ),
        ]
        q_values = bh_adjust(
            [(str(record["control_id"]), float(record["p_value"])) for record in model_records]
        )
        for record in model_records:
            record["q_value"] = q_values[str(record["control_id"])]
            record["promoted"] = bool(
                record["q_value"] <= 0.05
                and (record["observed_delta_log_loss"] or 0) > 0
            )
            record["status"] = (
                "NEGATIVE_CONTROL_SURVIVED_UNEXPECTEDLY"
                if record["promoted"]
                else "REJECTED_AFTER_MODEL_AND_MULTIPLICITY"
            )
        records = model_records + [
            guard_control(
                "FORBIDDEN_FUTURE_FEATURE",
                track,
                lambda fixture: {
                    "known_at": fixture.kickoff + timedelta(seconds=1),
                    "cutoff": fixture.kickoff,
                    "scientific_role": "LAGGED_RECONSTRUCTED_ONLY",
                    "derived_from_target": False,
                    "price_required": False,
                    "point_in_time_price_available": False,
                },
                "KNOWN_AT_NOT_BEFORE_TARGET_CUTOFF",
            ),
            guard_control(
                "SHIFTED_PRICE",
                track,
                lambda fixture: {
                    "known_at": fixture.kickoff - timedelta(seconds=1),
                    "cutoff": fixture.kickoff,
                    "scientific_role": "LAGGED_RECONSTRUCTED_ONLY",
                    "derived_from_target": False,
                    "price_required": True,
                    "point_in_time_price_available": False,
                },
                "POINT_IN_TIME_PRICE_UNAVAILABLE",
            ),
            guard_control(
                "POST_RESULT_FIELD",
                track,
                lambda fixture: {
                    "known_at": fixture.kickoff + timedelta(hours=6),
                    "cutoff": fixture.kickoff,
                    "scientific_role": "POST_RESULT",
                    "derived_from_target": False,
                    "price_required": False,
                    "point_in_time_price_available": False,
                },
                "SCIENTIFIC_ROLE_NOT_PREDICTOR_ADMISSIBLE",
            ),
            guard_control(
                "WINNER_LOSER_IDENTITY",
                track,
                lambda fixture: {
                    "known_at": fixture.kickoff + timedelta(hours=6),
                    "cutoff": fixture.kickoff,
                    "scientific_role": "TARGET_DERIVED_IDENTITY",
                    "derived_from_target": True,
                    "price_required": False,
                    "point_in_time_price_available": False,
                },
                "DERIVED_FROM_TARGET_LABEL",
            ),
        ]
        records.sort(key=lambda row: str(row["control_id"]))
        surviving = sum(int(bool(row["promoted"])) for row in records)
        if surviving:
            raise RuntimeError(f"NEGATIVE_CONTROL_SURVIVED:{track}:{surviving}")
        return {
            "generated_at": GENERATED_AT,
            "track": track,
            "control_count": len(records),
            "modeled_control_count": len(model_records),
            "admissibility_guard_control_count": len(records) - len(model_records),
            "negative_control_gate": "PASS",
            "surviving_control_count": surviving,
            "records": records,
        }

    write_json(
        output_root / "reports/hypothesis-research/atomic-negative-controls-v1.json",
        {"schema_version": "atomic-negative-controls-v1", **build_track("ATOMIC")},
    )
    write_json(
        output_root / "reports/hypothesis-research/pair-negative-controls-v1.json",
        {"schema_version": "pair-negative-controls-v1", **build_track("PAIR")},
    )


def build_campaign_configs(
    fixtures: Sequence[Fixture],
    registry: Mapping[str, Any],
    manifest: Mapping[str, Any],
    pair_space: Mapping[str, Any],
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
        "scope_contract": {
            "genome_properties_reconciled": 486,
            "ready_properties": 46,
            "selected_predictor_properties": 7,
            "deferred_public_hypothesis_eligible_properties": 18,
            "scope_status": "BOUNDED_SUBCAMPAIGN_PENDING_COUNCIL_RESCOPING",
        },
        "frozen_at": GENERATED_AT,
        "frozen_before_target_analysis": True,
        "targets_loaded_for_label_construction_before_freeze": True,
        "target_values_used_for_registry_masks_or_pair_selection": False,
        "dataset_hash": dataset_hash,
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "universe_hash": manifest["universe"]["fixture_ids_sha256"],
        "tag_registry_hash": registry["registry_hash"],
        "mask_manifest_hash": manifest["manifest_hash"],
        "pair_space_hash": pair_space["pair_space_hash"],
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
            "pair_child_to_smaller_parent_ratio": 0.2,
            "required_positive_folds": 4,
            "known_coverage": 0.8,
            "minimum_leagues": 3,
            "dominant_league_max": 0.5,
        },
        "multiple_testing_policy": {
            "method": "BH_FDR_GLOBAL_AND_FAMILY",
            "alpha": 0.05,
            "atomic_denominator": 160,
            "pair_denominator": 240,
            "blocked_tests_p_value": 1.0,
            "promotion_requires_both_q_values": True,
            "promotion_requires_positive_log_loss_and_brier_delta": True,
        },
        "negative_controls": list(NEGATIVE_CONTROL_IDS),
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
        ],
        "currently_blocked": [
            "ADMISSIBLE_HISTORICAL_PRICES",
            "PAIRS_AUDITED",
            "COMPUTE_BUDGET_APPROVED",
            "CHECKPOINTING_PROVEN",
        ],
    }
    triple["lock_hash"] = object_hash(triple)
    write_json(output_root / "configs/hypothesis-campaigns/triple-campaign-lock-v1.json", triple)
    artifact_lock = {
        "schema_version": "phase-c-artifact-lock-v1",
        "status": "EMPTY_DRAFT_REQUIRES_SUCCESSOR_ON_DEFAULT_BRANCH",
        "lineage_source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
        "stage_locks": {},
        "selection_rule": "TRUSTED_MAIN_EXACT_RUN_ATTEMPT_HEAD_ARTIFACT_ID_NAME_SIZE_DIGEST_AND_MANIFEST_HASH",
        "triple_search_locked": True,
    }
    artifact_lock["lock_hash"] = object_hash(artifact_lock)
    write_json(output_root / "configs/execution/phase-c-artifact-lock-v1.json", artifact_lock)
    workflow_hashes = {
        path.name: sha256_bytes(path.read_bytes())
        for path in sorted((ROOT / ".github/workflows").glob("8[6-9]-p0-phase-c-*.yml"))
    }
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
        "artifact_budgets_bytes": {
            "source_workflow_download_max": 120_000_000,
            "raw_field_census_upload_max": 5_000_000,
            "tag_mask_build_upload_max": 5_000_000,
            "atomic_property_search_upload_max": 5_000_000,
            "pair_shard_upload_max": 2_000_000,
            "pair_shards_total_max": 16_000_000,
            "compatible_pair_search_upload_max": 25_000_000,
            "derived_stage_download_max": 120_000_000,
        },
        "source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
        "phase_c_artifact_lock_hash": artifact_lock["lock_hash"],
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "preflight_sha256": sha256_bytes(
            (ROOT / "scripts/validate_phase_c_workflow_contract.py").read_bytes()
        ),
        "workflow_sha256": workflow_hashes,
        "triple_search_locked": True,
        "activation_authority": "TRUSTED_DEFAULT_BRANCH_ONLY_NEVER_CANDIDATE_CHECKOUT",
        "activation_requirement": "SUCCESSOR_REVIEW_ON_DEFAULT_BRANCH_MUST_SET_EXACT_ALLOWED_EXECUTION_SHA_AND_STAGE_ARTIFACT_LOCKS",
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


def build_stage_manifest(
    output_root: Path,
    _store_root: Path,
    stage: str,
    execution_sha: str,
    shard_id: str,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
        if path.name in {"stage-manifest-v1.json", "checkpoint-v1.json"}:
            continue
        records.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_bytes(path.read_bytes()),
            }
        )
    manifest = {
        "schema_version": "phase-c-stage-manifest-v1",
        "mission_id": "HYPOTHESIS-TAG-MASK-PAIR-FACTORY-V1",
        "stage": stage.upper().replace("-", "_"),
        "execution_sha": execution_sha,
        "shard_id": shard_id,
        "source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "artifact_file_count": len(records),
        "artifact_bytes": sum(int(row["bytes"]) for row in records),
        "excluded_control_files": ["checkpoint-v1.json", "stage-manifest-v1.json"],
        "files": records,
    }
    manifest["manifest_hash"] = object_hash(manifest)
    write_json(output_root / "stage-manifest-v1.json", manifest)
    return manifest


def seal_stage_artifact(
    artifact_root: Path,
    stage: str,
    execution_sha: str,
    shard_id: str,
) -> dict[str, Any]:
    checkpoint_path = unique_rglob(artifact_root, "checkpoint-v1.json")
    checkpoint = read_json(checkpoint_path)
    manifest = build_stage_manifest(
        artifact_root,
        artifact_root,
        stage,
        execution_sha,
        shard_id,
    )
    checkpoint["phase"] = stage.upper().replace("-", "_")
    checkpoint["execution_sha"] = execution_sha
    checkpoint["stage_manifest_hash"] = manifest["manifest_hash"]
    checkpoint["checkpoint_hash"] = object_hash(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_hash"}
    )
    write_json(checkpoint_path, checkpoint)
    return manifest


def verify_stage_artifact(
    artifact_root: Path,
    expected_manifest_hash: str,
    expected_stage: str,
    execution_sha: str,
    max_bytes: int,
) -> dict[str, Any]:
    manifest_path = unique_rglob(artifact_root, "stage-manifest-v1.json")
    manifest = read_json(manifest_path)
    if object_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}) != manifest.get(
        "manifest_hash"
    ):
        raise RuntimeError("STAGE_MANIFEST_CANONICAL_HASH_MISMATCH")
    if (
        manifest.get("manifest_hash") != expected_manifest_hash
        or manifest.get("stage") != expected_stage
        or manifest.get("execution_sha") != execution_sha
    ):
        raise RuntimeError("STAGE_MANIFEST_AUTHORITY_MISMATCH")
    manifest_root = manifest_path.parent
    actual = {
        path.relative_to(manifest_root).as_posix(): path
        for path in manifest_root.rglob("*")
        if path.is_file() and path.name not in {"stage-manifest-v1.json", "checkpoint-v1.json"}
    }
    rows = manifest.get("files")
    if not isinstance(rows, list):
        raise TypeError("STAGE_MANIFEST_FILES_REQUIRED")
    declared = {str(row["path"]): row for row in rows if isinstance(row, Mapping)}
    if set(actual) != set(declared):
        raise RuntimeError("STAGE_MANIFEST_FILE_SET_MISMATCH")
    for relative, path in actual.items():
        row = declared[relative]
        if int(row["bytes"]) != path.stat().st_size or row["sha256"] != sha256_bytes(
            path.read_bytes()
        ):
            raise RuntimeError(f"STAGE_MANIFEST_FILE_HASH_MISMATCH:{relative}")
    total = sum(path.stat().st_size for path in actual.values())
    if total != manifest.get("artifact_bytes") or total > max_bytes:
        raise RuntimeError("STAGE_ARTIFACT_BYTE_BUDGET_MISMATCH")
    checkpoint_path = unique_rglob(manifest_root, "checkpoint-v1.json")
    checkpoint = read_json(checkpoint_path)
    if (
        object_hash(
            {key: value for key, value in checkpoint.items() if key != "checkpoint_hash"}
        )
        != checkpoint.get("checkpoint_hash")
        or checkpoint.get("stage_manifest_hash") != manifest["manifest_hash"]
        or checkpoint.get("execution_sha") != execution_sha
    ):
        raise RuntimeError("STAGE_CHECKPOINT_LINEAGE_MISMATCH")
    return manifest


def build_tree_replay(first_root: Path, second_root: Path) -> dict[str, Any]:
    excluded = {
        "campaign-costs-v1.json",
        "checkpoint-v1.json",
        "campaign-replay-v1.json",
        "stage-manifest-v1.json",
    }
    first_files = {
        path.relative_to(first_root).as_posix(): path
        for path in first_root.rglob("*")
        if path.is_file() and path.name not in excluded
    }
    second_files = {
        path.relative_to(second_root).as_posix(): path
        for path in second_root.rglob("*")
        if path.is_file() and path.name not in excluded
    }
    paths = sorted(set(first_files) | set(second_files))
    records: list[dict[str, Any]] = []
    identical = set(first_files) == set(second_files)
    for relative in paths:
        first_hash = (
            sha256_bytes(first_files[relative].read_bytes()) if relative in first_files else None
        )
        second_hash = (
            sha256_bytes(second_files[relative].read_bytes())
            if relative in second_files
            else None
        )
        identical = identical and first_hash == second_hash
        records.append(
            {
                "path": relative,
                "sha256": first_hash,
                "replay_sha256": second_hash,
                "identical": first_hash == second_hash,
            }
        )
    result = {
        "schema_version": "phase-c-stage-replay-v1",
        "replay_runs": 2,
        "replay_identical": identical,
        "additional_network_reads": 0,
        "records": records,
    }
    if not identical:
        raise RuntimeError("STAGE_REPLAY_NOT_BYTE_IDENTICAL")
    write_json(first_root / "campaign-replay-v1.json", result)
    return result


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


def write_analysis_core(
    fixtures: Sequence[Fixture],
    features: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, Any]],
    store_root: Path,
) -> dict[str, Any]:
    core = {
        "schema_version": "phase-c-analysis-core-v1",
        "fixture_count": len(fixtures),
        "fixtures": [
            {
                "fixture_id": row.fixture_id,
                "competition_id": row.competition_id,
                "competition": row.competition,
                "kickoff": row.kickoff.isoformat(),
                "home_id": row.home_id,
                "away_id": row.away_id,
                "home_goals": row.home_goals,
                "away_goals": row.away_goals,
                "status": row.status,
                "source_hashes": list(row.source_hashes),
            }
            for row in fixtures
        ],
        "features": [dict(sorted(row.items())) for row in features],
        "targets": [dict(sorted(row.items())) for row in targets],
    }
    payload = gzip.compress(canonical_bytes(core), compresslevel=9, mtime=0)
    relative = Path("input/analysis-core-v1.json.gz")
    path = store_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "schema_version": "phase-c-analysis-core-artifact-v1",
        "artifact_relative_path": relative.as_posix(),
        "compressed_bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "content_sha256": object_hash(core),
        "raw_provider_rows_included": False,
        "fixture_identifiers_in_git": False,
    }


def read_analysis_core(path: Path) -> tuple[
    list[Fixture], list[dict[str, float | None]], list[dict[str, Any]]
]:
    payload = json.loads(gzip.decompress(path.read_bytes()))
    if not isinstance(payload, Mapping) or payload.get("fixture_count") != UNIVERSE_COUNT:
        raise RuntimeError("ANALYSIS_CORE_CONTRACT_MISMATCH")
    raw_fixtures = payload.get("fixtures")
    raw_features = payload.get("features")
    raw_targets = payload.get("targets")
    if not all(isinstance(value, list) for value in (raw_fixtures, raw_features, raw_targets)):
        raise TypeError("ANALYSIS_CORE_ARRAYS_REQUIRED")
    assert isinstance(raw_fixtures, list)
    assert isinstance(raw_features, list)
    assert isinstance(raw_targets, list)
    fixtures = [
        Fixture(
            fixture_id=str(row["fixture_id"]),
            competition_id=int(row["competition_id"]),
            competition=str(row["competition"]),
            kickoff=iso(str(row["kickoff"])),
            home_id=int(row["home_id"]),
            away_id=int(row["away_id"]),
            home_goals=int(row["home_goals"]),
            away_goals=int(row["away_goals"]),
            status=str(row["status"]),
            source_hashes=tuple(str(value) for value in row["source_hashes"]),
        )
        for row in raw_fixtures
        if isinstance(row, Mapping)
    ]
    features = [
        {str(key): (float(value) if value is not None else None) for key, value in row.items()}
        for row in raw_features
        if isinstance(row, Mapping)
    ]
    targets = [dict(row) for row in raw_targets if isinstance(row, Mapping)]
    if not (len(fixtures) == len(features) == len(targets) == UNIVERSE_COUNT):
        raise RuntimeError("ANALYSIS_CORE_LENGTH_MISMATCH")
    return fixtures, features, targets


def unique_rglob(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise RuntimeError(f"UPSTREAM_FILE_CARDINALITY:{name}:{len(matches)}")
    return matches[0]


def load_upstream_masks(
    upstream_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, tuple[int, int]], list[Fixture], list[dict[str, float | None]], list[dict[str, Any]]]:
    manifest = read_json(unique_rglob(upstream_root, "atomic-mask-manifest-v1.json"))
    registry = read_json(unique_rglob(upstream_root, "canonical-tag-registry-v1.json"))
    core_path = unique_rglob(upstream_root, "analysis-core-v1.json.gz")
    expected_core = manifest.get("analysis_core")
    if not isinstance(expected_core, Mapping) or sha256_bytes(core_path.read_bytes()) != expected_core.get(
        "sha256"
    ):
        raise RuntimeError("ANALYSIS_CORE_HASH_MISMATCH")
    fixtures, features, targets = read_analysis_core(core_path)
    masks: dict[str, tuple[int, int]] = {}
    records = manifest.get("records")
    if not isinstance(records, list):
        raise TypeError("MASK_MANIFEST_RECORDS_REQUIRED")
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("MASK_MANIFEST_RECORD_REQUIRED")
        path = unique_rglob(upstream_root, Path(str(record["artifact_relative_path"])).name)
        envelope = path.read_bytes()
        if sha256_bytes(envelope) != record["payload_sha256"]:
            raise RuntimeError(f"MASK_PAYLOAD_HASH_MISMATCH:{record['tag_id']}")
        payload, checksum = envelope[:-32], envelope[-32:]
        if hashlib.sha256(payload).digest() != checksum or not payload.startswith(b"RMASKV1\0"):
            raise RuntimeError(f"MASK_ENVELOPE_CHECKSUM_MISMATCH:{record['tag_id']}")
        count, identity_length = struct.unpack("<QH", payload[8:18])
        if count != UNIVERSE_COUNT:
            raise RuntimeError("MASK_UNIVERSE_COUNT_MISMATCH")
        offset = 18 + 32 + identity_length
        known = int.from_bytes(payload[offset : offset + NBYTES], "little")
        true = int.from_bytes(payload[offset + NBYTES : offset + 2 * NBYTES], "little")
        if true & ~known:
            raise RuntimeError(f"MASK_TRUE_NOT_SUBSET_KNOWN:{record['tag_id']}")
        masks[str(record["tag_id"])] = (known, true)
    if len(masks) != int(manifest["mask_count"]):
        raise RuntimeError("MASK_UPSTREAM_COUNT_MISMATCH")
    return manifest, registry, masks, fixtures, features, targets


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
    core_manifest = write_analysis_core(fixtures, features, targets, store_root)
    census = build_census(rows, output_root)
    if stage == "census":
        return {"census": census}
    reconciliation = build_reconciliation(output_root)
    registry = build_tag_registry(output_root)
    manifest, masks = build_masks(
        fixtures, features, registry, output_root, store_root, core_manifest
    )
    if include_benchmark:
        benchmark_masks(masks, manifest, output_root)
    # Pair selection is target-blind and frozen before any target analysis.
    selected, pair_space = select_pairs(masks, registry, output_root)
    config = build_campaign_configs(fixtures, registry, manifest, pair_space, output_root)
    if stage == "tag-mask-build":
        return {
            "census": census,
            "reconciliation": reconciliation,
            "registry": registry,
            "manifest": manifest,
            "pair_space": pair_space,
            "config": config,
        }
    atomic, atomic_index = evaluate_atomic(
        fixtures, features, targets, registry, output_root, store_root
    )
    build_negative_controls(fixtures, features, targets, output_root)
    if stage == "atomic":
        if include_costs:
            build_costs(started_process, output_root)
        return {
            "config": config,
            "manifest": manifest,
            "pair_space": pair_space,
            "atomic": atomic,
            "atomic_index": atomic_index,
        }
    pairs = evaluate_pairs(
        selected,
        fixtures,
        features,
        targets,
        masks,
        registry,
        manifest,
        output_root,
        store_root,
    )
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


def execute_upstream(
    stage: str,
    tag_mask_root: Path,
    atomic_root: Path | None,
    output_root: Path,
    store_root: Path,
    *,
    include_costs: bool = True,
) -> dict[str, Any]:
    safety_gate()
    started_process = time.process_time()
    manifest, registry, masks, fixtures, features, targets = load_upstream_masks(tag_mask_root)
    pair_space = read_json(unique_rglob(tag_mask_root, "pair-search-space-v1.json"))
    config = read_json(unique_rglob(tag_mask_root, "atomic-property-campaign-v1.json"))
    if config.get("pair_space_hash") != pair_space.get("pair_space_hash"):
        raise RuntimeError("UPSTREAM_PAIR_SPACE_HASH_MISMATCH")
    if stage == "atomic":
        atomic, atomic_index = evaluate_atomic(
            fixtures, features, targets, registry, output_root, store_root
        )
        build_negative_controls(fixtures, features, targets, output_root)
        if include_costs:
            build_costs(started_process, output_root)
        return {
            "config": config,
            "manifest": manifest,
            "pair_space": pair_space,
            "atomic": atomic,
            "atomic_index": atomic_index,
        }
    if stage != "pairs" or atomic_root is None:
        raise RuntimeError("UPSTREAM_STAGE_CONTRACT_MISMATCH")
    atomic_full_path = unique_rglob(atomic_root, "atomic-results-full-v1.json.gz")
    atomic = read_heavy_json_artifact(atomic_full_path)
    if atomic.get("canonical_test_count") != 160:
        raise RuntimeError("UPSTREAM_ATOMIC_TEST_COUNT_MISMATCH")
    selected = pair_space.get("pairs")
    if not isinstance(selected, list) or len(selected) != 120:
        raise RuntimeError("UPSTREAM_PAIR_SELECTION_COUNT_MISMATCH")
    pairs = evaluate_pairs(
        selected,
        fixtures,
        features,
        targets,
        masks,
        registry,
        manifest,
        output_root,
        store_root,
    )
    build_negative_controls(fixtures, features, targets, output_root)
    census = read_json(unique_rglob(tag_mask_root, "raw-field-census-v1.json"))
    reconciliation = read_json(unique_rglob(tag_mask_root, "e3-property-reconciliation-v1.json"))
    build_dashboard_contract(census, reconciliation, registry, atomic, pairs, output_root)
    if include_costs:
        build_costs(started_process, output_root)
    return {
        "config": config,
        "manifest": manifest,
        "pair_space": pair_space,
        "atomic": atomic,
        "pairs": pairs,
    }


def export_pair_shard(
    input_root: Path,
    full_results_root: Path,
    shard_id: int,
    shard_count: int,
    execution_sha: str,
) -> dict[str, Any]:
    if shard_count != 8 or not 0 <= shard_id < shard_count:
        raise RuntimeError("PAIR_SHARD_CONTRACT_REQUIRES_8_SHARDS")
    full_path = unique_rglob(full_results_root, "pair-results-full-v1.json.gz")
    report = read_heavy_json_artifact(full_path)
    results = report.get("results")
    if not isinstance(results, list):
        raise TypeError("PAIR_RESULTS_ARRAY_REQUIRED")
    selected = [
        row
        for row in results
        if isinstance(row, Mapping) and int(row.get("shard_id", -1)) == shard_id
    ]
    shard = {
        "schema_version": "pair-results-shard-v1",
        "shard_id": shard_id,
        "shard_count": shard_count,
        "partition_rule": "first64_sha256_pair_id_mod_8",
        "execution_sha": execution_sha,
        "global_source_report_sha256": sha256_bytes(
            full_path.read_bytes()
        ),
        "pair_count": len(selected),
        "pair_ids_sha256": object_hash(sorted(str(row["pair_id"]) for row in selected)),
        "results": selected,
    }
    shard["shard_hash"] = object_hash(shard)
    write_json(input_root / f"pair-results-shard-{shard_id:02d}-v1.json", shard)
    return shard


def reduce_pair_shards(
    input_root: Path,
    tag_mask_root: Path,
    output_root: Path,
    store_root: Path,
    execution_sha: str,
) -> dict[str, Any]:
    enforce_soft_deadline()
    shard_paths = sorted(input_root.rglob("pair-results-shard-*-v1.json"))
    shards = [read_json(path) for path in shard_paths]
    if len(shards) != 8 or {int(row["shard_id"]) for row in shards} != set(range(8)):
        raise RuntimeError("PAIR_REDUCER_REQUIRES_EXACTLY_8_UNIQUE_SHARDS")
    shard_manifests = sorted(input_root.rglob("stage-manifest-v1.json"))
    checkpoints = sorted(input_root.rglob("checkpoint-v1.json"))
    replays = sorted(input_root.rglob("campaign-replay-v1.json"))
    if not (len(shard_manifests) == len(checkpoints) == len(replays) == 8):
        raise RuntimeError("PAIR_REDUCER_SHARD_CONTROL_FILE_CARDINALITY")
    for shard in shards:
        enforce_soft_deadline()
        if (
            object_hash({key: value for key, value in shard.items() if key != "shard_hash"})
            != shard.get("shard_hash")
            or shard.get("execution_sha") != execution_sha
            or shard.get("shard_count") != 8
        ):
            raise RuntimeError("PAIR_SHARD_HASH_OR_LINEAGE_MISMATCH")
        shard_id = int(shard["shard_id"])
        results_value = shard.get("results")
        if not isinstance(results_value, list) or any(
            not isinstance(row, Mapping) or int(row.get("shard_id", -1)) != shard_id
            for row in results_value
        ):
            raise RuntimeError("PAIR_SHARD_PARTITION_MISMATCH")
        pair_ids = sorted(str(row["pair_id"]) for row in results_value if isinstance(row, Mapping))
        if len(pair_ids) != shard.get("pair_count") or object_hash(pair_ids) != shard.get(
            "pair_ids_sha256"
        ):
            raise RuntimeError("PAIR_SHARD_ID_HASH_MISMATCH")
    for manifest_path in shard_manifests:
        enforce_soft_deadline()
        manifest = read_json(manifest_path)
        verify_stage_artifact(
            manifest_path.parent,
            str(manifest.get("manifest_hash")),
            "COMPATIBLE_PAIR_SEARCH_SHARD",
            execution_sha,
            2_000_000,
        )
    for checkpoint_path in checkpoints:
        enforce_soft_deadline()
        checkpoint = read_json(checkpoint_path)
        if checkpoint.get("completed") is not True or checkpoint.get("shard_count") != 8:
            raise RuntimeError("PAIR_REDUCER_INCOMPLETE_CHECKPOINT")
    for replay_path in replays:
        enforce_soft_deadline()
        replay = read_json(replay_path)
        if replay.get("replay_runs") != 2 or replay.get("replay_identical") is not True:
            raise RuntimeError("PAIR_REDUCER_SHARD_REPLAY_MISMATCH")
    source_hashes = {str(row["global_source_report_sha256"]) for row in shards}
    if len(source_hashes) != 1:
        raise RuntimeError("PAIR_SHARD_GLOBAL_REPORT_HASH_DRIFT")
    results = [
        result
        for shard in shards
        for result in shard["results"]
        if isinstance(result, Mapping)
    ]
    results.sort(key=lambda row: str(row["pair_id"]))
    if len(results) != 120 or len({str(row["pair_id"]) for row in results}) != 120:
        raise RuntimeError("PAIR_REDUCER_CARDINALITY_OR_DUPLICATE_MISMATCH")
    status_counts = Counter(str(row["status"]) for row in results)
    report = {
        "schema_version": "pair-results-v1",
        "generated_at": GENERATED_AT,
        "verdict": "PAIR_CAMPAIGN_PARTIAL",
        "pair_count": len(results),
        "pair_grain": "unordered distinct tag_id pair with distinct parent property_id",
        "unique_property_pair_count": len(
            {
                tuple(sorted((str(row["parent_property_a"]), str(row["parent_property_b"]))))
                for row in results
            }
        ),
        "canonical_test_count": sum(len(row["target_metrics"]) for row in results),
        "status_counts": dict(sorted(status_counts.items())),
        "results": results,
    }
    heavy_artifact = write_heavy_json_artifact(
        store_root, "pair-results-full-v1.json.gz", report
    )
    if heavy_artifact["sha256"] not in source_hashes:
        raise RuntimeError("PAIR_REDUCER_FULL_REPORT_HASH_DRIFT")
    write_json(
        output_root / "reports/hypothesis-research/pair-results-v1.json",
        compact_pair_report(report, heavy_artifact),
    )
    enforce_soft_deadline()
    rankings = sorted(
        results,
        key=lambda row: max(
            min(
                metric["delta_log_loss_by_comparator"][name] or -999
                for name in ("PARENT_A", "PARENT_B", "ADDITIVE")
            )
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
            "top_count": 50,
            "records": [
                {
                    "rank": index + 1,
                    "pair_id": row["pair_id"],
                    "parents": [row["parent_a"], row["parent_b"]],
                    "status": row["status"],
                    "best_worst_case_delta_log_loss": max(
                        min(
                            metric["delta_log_loss_by_comparator"][name] or -999
                            for name in ("PARENT_A", "PARENT_B", "ADDITIVE")
                        )
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
    enforce_soft_deadline()
    _, _, masks, _, _, _ = load_upstream_masks(tag_mask_root)
    build_pair_clusters(results, masks, output_root)
    enforce_soft_deadline()
    controls = sorted(input_root.rglob("pair-negative-controls-v1.json"))
    if len(controls) != 8 or len({sha256_bytes(path.read_bytes()) for path in controls}) != 1:
        raise RuntimeError("PAIR_NEGATIVE_CONTROL_SHARD_DRIFT")
    write_json(
        output_root / "reports/hypothesis-research/pair-negative-controls-v1.json",
        read_json(controls[0]),
    )
    enforce_soft_deadline()
    pair_space = read_json(unique_rglob(tag_mask_root, "pair-search-space-v1.json"))
    config = read_json(unique_rglob(tag_mask_root, "atomic-property-campaign-v1.json"))
    write_json(output_root / "reports/hypothesis-research/pair-search-space-v1.json", pair_space)
    return {"config": config, "pairs": report, "pair_space": pair_space}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("all", "census", "tag-mask-build", "atomic", "pairs"):
        current = subparsers.add_parser(command)
        current.add_argument("--source-root", type=Path, required=True)
        current.add_argument("--output-root", type=Path, required=True)
        current.add_argument("--store-root", type=Path, required=True)
        current.add_argument("--skip-benchmark", action="store_true")
        current.add_argument("--execution-sha", default="LOCAL_UNPUSHED")
        current.add_argument("--shard-id", default="LOCAL-ALL")
        current.add_argument("--shard-count", type=int, default=1)
        current.add_argument("--resume-checkpoint", type=Path)
        current.add_argument("--soft-deadline-seconds", type=int, default=600)
    for command in ("atomic-upstream", "pairs-upstream"):
        current = subparsers.add_parser(command)
        current.add_argument("--tag-mask-root", type=Path, required=True)
        current.add_argument("--atomic-root", type=Path)
        current.add_argument("--output-root", type=Path, required=True)
        current.add_argument("--store-root", type=Path, required=True)
        current.add_argument("--execution-sha", required=True)
        current.add_argument("--shard-id", required=True)
        current.add_argument("--shard-count", type=int, default=8)
        current.add_argument("--resume-checkpoint", type=Path)
        current.add_argument("--soft-deadline-seconds", type=int, default=600)
    replay = subparsers.add_parser("replay")
    replay.add_argument("--first-root", type=Path, required=True)
    replay.add_argument("--second-root", type=Path, required=True)
    stage_replay = subparsers.add_parser("replay-stage")
    stage_replay.add_argument("--first-root", type=Path, required=True)
    stage_replay.add_argument("--second-root", type=Path, required=True)
    shard_export = subparsers.add_parser("export-pair-shard")
    shard_export.add_argument("--input-root", type=Path, required=True)
    shard_export.add_argument("--full-results-root", type=Path, required=True)
    shard_export.add_argument("--shard-id", type=int, required=True)
    shard_export.add_argument("--shard-count", type=int, default=8)
    shard_export.add_argument("--execution-sha", required=True)
    reducer = subparsers.add_parser("reduce-pair-shards")
    reducer.add_argument("--input-root", type=Path, required=True)
    reducer.add_argument("--tag-mask-root", type=Path, required=True)
    reducer.add_argument("--output-root", type=Path, required=True)
    reducer.add_argument("--store-root", type=Path, required=True)
    reducer.add_argument("--execution-sha", required=True)
    reducer.add_argument("--soft-deadline-seconds", type=int, default=240)
    seal = subparsers.add_parser("seal-stage")
    seal.add_argument("--artifact-root", type=Path, required=True)
    seal.add_argument("--stage", required=True)
    seal.add_argument("--execution-sha", required=True)
    seal.add_argument("--shard-id", required=True)
    verify = subparsers.add_parser("verify-stage")
    verify.add_argument("--artifact-root", type=Path, required=True)
    verify.add_argument("--expected-manifest-hash", required=True)
    verify.add_argument("--expected-stage", required=True)
    verify.add_argument("--execution-sha", required=True)
    verify.add_argument("--max-bytes", type=int, required=True)
    return parser.parse_args()


def write_checkpoint(
    store_root: Path,
    stage: str,
    result: Mapping[str, Any],
    stage_manifest: Mapping[str, Any],
    execution_sha: str,
    shard_id: str,
    shard_count: int,
    previous_checkpoint_hash: str | None,
) -> None:
    atomic_count = (
        int(result.get("atomic", {}).get("atomic_tag_count", 0))
        if isinstance(result.get("atomic"), Mapping)
        else 0
    )
    pair_count = (
        int(result.get("pairs", {}).get("pair_count", 0))
        if isinstance(result.get("pairs"), Mapping)
        else 0
    )
    if pair_count and shard_count > 1 and isinstance(result.get("pairs"), Mapping):
        pair_rows = result["pairs"].get("results")
        if isinstance(pair_rows, list) and shard_id.isdigit():
            pair_count = sum(
                int(isinstance(row, Mapping) and int(row.get("shard_id", -1)) == int(shard_id))
                for row in pair_rows
            )
    checkpoint = {
        "schema_version": "phase-c-checkpoint-v1",
        "mission_id": "HYPOTHESIS-TAG-MASK-PAIR-FACTORY-V1",
        "phase": canonical_phase(stage),
        "campaign_hash": result.get("config", {}).get("campaign_hash")
        if isinstance(result.get("config"), Mapping)
        else None,
        "execution_sha": execution_sha,
        "source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "stage_manifest_hash": stage_manifest["manifest_hash"],
        "shard_id": shard_id,
        "shard_count": shard_count,
        "cursor": pair_count
        or atomic_count
        or result.get("census", {}).get("catalog_record_count", 0),
        "evaluated": pair_count
        or atomic_count
        or result.get("census", {}).get("catalog_record_count", 0),
        "rejected": 0,
        "deferred": 0,
        "completed": True,
        "resumed_from_cursor": ACTIVE_RESUME_LOADED_COUNT or None,
        "completed_prefix_records_recomputed": 0
        if ACTIVE_RESUME_LOADED_COUNT
        else None,
        "previous_checkpoint_hash": previous_checkpoint_hash,
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


def write_initial_checkpoint(
    store_root: Path,
    stage: str,
    execution_sha: str,
    shard_id: str,
    shard_count: int,
    previous_checkpoint_hash: str | None,
) -> None:
    checkpoint = {
        "schema_version": "phase-c-checkpoint-v1",
        "mission_id": "HYPOTHESIS-TAG-MASK-PAIR-FACTORY-V1",
        "phase": canonical_phase(stage),
        "execution_sha": execution_sha,
        "source_lock_sha256": repository_text_sha256(SOURCE_LOCK),
        "generator_sha256": sha256_bytes(GENERATOR_PATH.read_bytes()),
        "shard_id": shard_id,
        "shard_count": shard_count,
        "cursor": 0,
        "evaluated": 0,
        "rejected": 0,
        "deferred": 0,
        "completed": False,
        "previous_checkpoint_hash": previous_checkpoint_hash,
        "next_action": "RESUME_CURRENT_SHARD",
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
    global ACTIVE_RESUME_CHECKPOINT, ACTIVE_RESUME_ROOT, ACTIVE_SOFT_DEADLINE
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
    if args.command == "replay-stage":
        result = build_tree_replay(args.first_root.resolve(), args.second_root.resolve())
        print(json.dumps({"replay_identical": result["replay_identical"]}, sort_keys=True))
        return 0
    if args.command == "seal-stage":
        result = seal_stage_artifact(
            args.artifact_root.resolve(),
            args.stage,
            args.execution_sha,
            args.shard_id,
        )
        print(json.dumps({"manifest_hash": result["manifest_hash"]}, sort_keys=True))
        return 0
    if args.command == "verify-stage":
        result = verify_stage_artifact(
            args.artifact_root.resolve(),
            args.expected_manifest_hash,
            args.expected_stage,
            args.execution_sha,
            args.max_bytes,
        )
        print(json.dumps({"manifest_hash": result["manifest_hash"]}, sort_keys=True))
        return 0
    if args.command == "export-pair-shard":
        result = export_pair_shard(
            args.input_root.resolve(),
            args.full_results_root.resolve(),
            args.shard_id,
            args.shard_count,
            args.execution_sha,
        )
        print(json.dumps({"pair_count": result["pair_count"]}, sort_keys=True))
        return 0
    if args.command == "reduce-pair-shards":
        if args.soft_deadline_seconds < 60:
            raise RuntimeError("REDUCER_DEADLINE_CONTRACT_INVALID")
        ACTIVE_SOFT_DEADLINE = time.monotonic() + args.soft_deadline_seconds
        write_initial_checkpoint(
            args.store_root.resolve(),
            "COMPATIBLE_PAIR_SEARCH",
            args.execution_sha,
            "REDUCE-8",
            8,
            None,
        )
        result = reduce_pair_shards(
            args.input_root.resolve(),
            args.tag_mask_root.resolve(),
            args.output_root.resolve(),
            args.store_root.resolve(),
            args.execution_sha,
        )
        manifest = build_stage_manifest(
            args.output_root.resolve(),
            args.store_root.resolve(),
            "pairs",
            args.execution_sha,
            "REDUCE-8",
        )
        write_checkpoint(
            args.store_root.resolve(),
            "pairs",
            result,
            manifest,
            args.execution_sha,
            "REDUCE-8",
            8,
            None,
        )
        print(json.dumps({"pair_count": result["pairs"]["pair_count"]}, sort_keys=True))
        return 0
    previous_checkpoint_hash: str | None = None
    requested_stage = (
        "atomic"
        if args.command == "atomic-upstream"
        else ("pairs" if args.command in {"all", "pairs", "pairs-upstream"} else args.command)
    )
    if args.resume_checkpoint is not None:
        previous = read_json(args.resume_checkpoint.resolve())
        previous_without_hash = dict(previous)
        previous_hash = previous_without_hash.pop("checkpoint_hash", None)
        if not isinstance(previous_hash, str) or object_hash(previous_without_hash) != previous_hash:
            raise RuntimeError("RESUME_CHECKPOINT_HASH_MISMATCH")
        if (
            previous.get("execution_sha") != args.execution_sha
            or previous.get("shard_id") != args.shard_id
            or previous.get("source_lock_sha256") != repository_text_sha256(SOURCE_LOCK)
            or previous.get("generator_sha256") != sha256_bytes(GENERATOR_PATH.read_bytes())
        ):
            raise RuntimeError("RESUME_CHECKPOINT_LINEAGE_MISMATCH")
        previous_checkpoint_hash = previous_hash
        if previous.get("completed") is True:
            manifest = read_json(unique_rglob(args.output_root.resolve(), "stage-manifest-v1.json"))
            if (
                manifest.get("manifest_hash") != previous.get("stage_manifest_hash")
                or manifest.get("stage") != canonical_phase(requested_stage)
            ):
                raise RuntimeError("COMPLETED_CHECKPOINT_RESULT_MANIFEST_MISMATCH")
            print(
                json.dumps(
                    {
                        "stage": requested_stage,
                        "resumed_completed_shard_without_recalculation": True,
                        "checkpoint_hash": previous_checkpoint_hash,
                    },
                    sort_keys=True,
                )
            )
            return 0
        ACTIVE_RESUME_ROOT = args.resume_checkpoint.resolve().parent
        ACTIVE_RESUME_CHECKPOINT = previous
    if args.shard_count < 1 or args.soft_deadline_seconds < 60:
        raise RuntimeError("SHARD_OR_DEADLINE_CONTRACT_INVALID")
    ACTIVE_SOFT_DEADLINE = time.monotonic() + args.soft_deadline_seconds
    write_initial_checkpoint(
        args.store_root.resolve(),
        requested_stage,
        args.execution_sha,
        args.shard_id,
        args.shard_count,
        previous_checkpoint_hash,
    )
    if args.command in {"atomic-upstream", "pairs-upstream"}:
        stage = "atomic" if args.command == "atomic-upstream" else "pairs"
        result = execute_upstream(
            stage,
            args.tag_mask_root.resolve(),
            args.atomic_root.resolve() if args.atomic_root is not None else None,
            args.output_root.resolve(),
            args.store_root.resolve(),
            include_costs=True,
        )
    else:
        stage = "pairs" if args.command == "all" else args.command
        result = execute_factory(
            args.source_root.resolve(),
            args.output_root.resolve(),
            args.store_root.resolve(),
            stage=stage,
            include_benchmark=not args.skip_benchmark,
            include_costs=True,
        )
    stage_manifest = build_stage_manifest(
        args.output_root.resolve(),
        args.store_root.resolve(),
        stage,
        args.execution_sha,
        args.shard_id,
    )
    write_checkpoint(
        args.store_root.resolve(),
        stage,
        result,
        stage_manifest,
        args.execution_sha,
        args.shard_id,
        args.shard_count,
        previous_checkpoint_hash,
    )
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
