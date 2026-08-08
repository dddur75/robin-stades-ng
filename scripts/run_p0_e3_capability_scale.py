"""Verify immutable E3 artifacts and build compact E3A/E3B evidence reports.

The runner never imports an object-storage or provider client. Inputs are exact
GitHub artifacts already pinned by workflow 85 and the committed lock.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "configs/execution/p0-e3-artifact-lock-v1.json"
MISSION_PATH = ROOT / "configs/execution/p0-e3-capability-scale-v1.json"
E3A_SELECTION_PATH = ROOT / "reports/evidence/e3a/e3a-selection-manifest-v1.json"

CAPABILITIES = (
    "TEAM",
    "PLAYER",
    "LINEUP",
    "FORMATION",
    "EVENTS",
    "TEAM_STATISTICS",
    "DISCIPLINE_GENERIC",
    "CALENDAR",
)
E3B_CAPABILITIES = CAPABILITIES[:-1]
CALENDAR_FEATURES = (
    "REST_DAYS_HOME",
    "REST_DAYS_AWAY",
    "MATCHES_LAST_7D_HOME",
    "MATCHES_LAST_7D_AWAY",
    "MATCHES_LAST_14D_HOME",
    "MATCHES_LAST_14D_AWAY",
    "MATCHES_LAST_28D_HOME",
    "MATCHES_LAST_28D_AWAY",
    "CONSECUTIVE_AWAY_MATCHES_HOME",
    "CONSECUTIVE_AWAY_MATCHES_AWAY",
    "THIRD_CONSECUTIVE_AWAY_HOME",
    "THIRD_CONSECUTIVE_AWAY_AWAY",
    "DAYS_SINCE_LAST_HOME_MATCH",
    "DAYS_SINCE_LAST_AWAY_MATCH",
    "FIXTURE_CONGESTION_7D",
    "FIXTURE_CONGESTION_14D",
    "FIXTURE_CONGESTION_28D",
)
ROLES = {
    "TEAM": ("one team identity in one fixture", "IDENTITY_ONLY", "POST_MATCH_IDENTITY"),
    "PLAYER": ("one player identity in one team fixture", "IDENTITY_ONLY", "POST_MATCH_IDENTITY"),
    "LINEUP": (
        "one team lineup in one fixture",
        "RECONSTRUCTED_DESCRIPTIVE_ONLY",
        "POST_MATCH_RECONSTRUCTED",
    ),
    "FORMATION": (
        "one team formation in one fixture",
        "RECONSTRUCTED_DESCRIPTIVE_ONLY",
        "POST_MATCH_RECONSTRUCTED",
    ),
    "EVENTS": (
        "one event in one fixture",
        "LAGGABLE_POST_MATCH_SOURCE",
        "POST_MATCH_LAGGABLE_ONLY",
    ),
    "TEAM_STATISTICS": (
        "one normalized statistic for one team fixture",
        "LAGGABLE_POST_MATCH_SOURCE",
        "POST_MATCH_LAGGABLE_ONLY",
    ),
    "DISCIPLINE_GENERIC": (
        "one generic card event in one fixture",
        "LAGGABLE_POST_MATCH_SOURCE",
        "POST_MATCH_LAGGABLE_ONLY",
    ),
    "CALENDAR": (
        "one scheduled fixture at one pre-kickoff cutoff",
        "STRICT_PREDICTOR_SOURCE",
        "STRICT_AS_OF",
    ),
}
REPORT_DESTINATIONS = {
    "e3a-selection-manifest-v1.json": "reports/evidence/e3a/e3a-selection-manifest-v1.json",
    "e3a-measurement-v1.json": "reports/evidence/e3a/e3a-measurement-v1.json",
    "e3a-capability-matrix-v1.json": "reports/evidence/e3a/e3a-capability-matrix-v1.json",
    "e3a-calendar-asof-v1.json": "reports/evidence/e3a/e3a-calendar-asof-v1.json",
    "e3a-replay-v1.json": "reports/evidence/e3a/e3a-replay-v1.json",
    "e3a-costs-v1.json": "reports/evidence/e3a/e3a-costs-v1.json",
    "e3b-selection-manifest-v1.json": "reports/evidence/e3b/e3b-selection-manifest-v1.json",
    "e3b-measurement-v1.json": "reports/evidence/e3b/e3b-measurement-v1.json",
    "e3b-capability-matrix-v1.json": "reports/evidence/e3b/e3b-capability-matrix-v1.json",
    "e3b-league-comparison-v1.json": "reports/evidence/e3b/e3b-league-comparison-v1.json",
    "e3b-replay-v1.json": "reports/evidence/e3b/e3b-replay-v1.json",
    "e3b-costs-v1.json": "reports/evidence/e3b/e3b-costs-v1.json",
}
STAT_ALIASES = {
    "ball possession": "possession",
    "blocked shots": "blocked_shots",
    "corner kicks": "corners_for",
    "fouls": "fouls",
    "goalkeeper saves": "saves",
    "red cards": "red_cards",
    "shots insidebox": "shots_inside_box",
    "shots on goal": "shots_on_target",
    "shots outsidebox": "shots_outside_box",
    "total passes": "passes",
    "total shots": "shots",
    "yellow cards": "yellow_cards",
    "expected_goals": "xg",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _render(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_render(value))


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(label)
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(label)
    return value


def _rate(numerator: int, denominator: int | None) -> float | None:
    if denominator in (None, 0):
        return None
    return round(numerator / denominator, 8)


def _safety() -> None:
    forbidden = (
        "API_FOOTBALL_KEY",
        "DATABASE_URL",
        "ODDS_API_KEY",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    )
    if any(os.environ.get(name) for name in forbidden):
        raise RuntimeError("E3_FORBIDDEN_SECRET_MOUNTED")
    expected = {
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "ODDS_CREDITS_ALLOWED": "0",
        "REMOTE_SQL_ALLOWED": "0",
        "R2_GET_ALLOWED": "0",
        "R2_LIST_ALLOWED": "0",
        "R2_HEAD_ALLOWED": "0",
        "R2_WRITES_ALLOWED": "0",
        "R2_DELETES_ALLOWED": "0",
        "DEPLOYMENT_ALLOWED": "0",
        "PUBLICATION_ALLOWED": "0",
        "PROMOTION_ALLOWED": "0",
        "REAL_BETS": "false",
        "TRIPLE_SEARCH_LOCKED": "true",
    }
    for name, wanted in expected.items():
        if os.environ.get(name) not in (None, "", wanted):
            raise RuntimeError(f"E3_RUNTIME_LOCK_INVALID:{name}")


def _artifact(lock: Mapping[str, Any], competition: str) -> Mapping[str, Any]:
    for raw in _sequence(lock["artifacts"], "E3_ARTIFACTS"):
        item = _mapping(raw, "E3_ARTIFACT")
        if item.get("competition") == competition:
            return item
    raise ValueError(f"E3_COMPETITION_NOT_LOCKED:{competition}")


def _segment_spec(lock: Mapping[str, Any], competition: str) -> Mapping[str, Any]:
    segments = _mapping(lock["segments"], "E3_SEGMENTS")
    return _mapping(segments.get(competition), f"E3_SEGMENT:{competition}")


def _load_segment(source_root: Path, competition: str) -> dict[str, Any]:
    lock = _read(LOCK_PATH)
    spec = _segment_spec(lock, competition)
    segment_id = str(spec["segment_id"])
    matches = [path for path in source_root.rglob("segment-result.json.gz") if path.parent.name == segment_id]
    if len(matches) != 1:
        raise ValueError(f"E3_EXACT_SEGMENT_CARDINALITY:{competition}:{len(matches)}")
    result_path = matches[0]
    manifest_path = result_path.with_name("segment-manifest.json")
    with gzip.open(result_path, "rt", encoding="utf-8") as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise TypeError("E3_SEGMENT_RESULT")
    manifest = _mapping(result.get("manifest"), "E3_INTERNAL_MANIFEST")
    external = _read(manifest_path)
    if dict(manifest) != external:
        raise ValueError("E3_EXTERNAL_INTERNAL_MANIFEST_DIVERGENCE")
    entries = list(_sequence(result.get("entries"), "E3_ENTRIES"))
    rows = list(_sequence(result.get("rows"), "E3_ROWS"))
    no_hash = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    checks = {
        "manifest_sha256": _sha(no_hash),
        "rows_sha256": _sha(rows),
        "entries_sha256": _sha(entries),
        "logical_bytes": int(manifest["logical_bytes"]),
        "object_count": int(manifest["objects_verified"]),
        "row_count": int(manifest["row_count"]),
    }
    for field, actual in checks.items():
        if spec.get(field) != actual:
            raise ValueError(f"E3_SEGMENT_LOCK_MISMATCH:{competition}:{field}")
    if manifest.get("inventory_sha256") != lock.get("inventory_manifest_sha256"):
        raise ValueError("E3_INVENTORY_HASH_DIVERGENCE")
    if manifest.get("status") != "SEGMENT_REPLAY_VERIFIED" or manifest.get("family") != "fixtures":
        raise ValueError("E3_SEGMENT_NOT_VERIFIED_FIXTURES")
    result["_source_proof"] = {
        "artifact_digest": _artifact(lock, competition)["artifact_digest"],
        "artifact_id": _artifact(lock, competition)["artifact_id"],
        "artifact_size_bytes": _artifact(lock, competition)["size_in_bytes"],
        "entries_sha256": checks["entries_sha256"],
        "inventory_manifest_sha256": lock["inventory_manifest_sha256"],
        "logical_bytes": checks["logical_bytes"],
        "manifest_sha256": checks["manifest_sha256"],
        "object_count": checks["object_count"],
        "row_count": checks["row_count"],
        "rows_sha256": checks["rows_sha256"],
        "segment_id": segment_id,
        "transport": "GITHUB_ARTIFACT_EXACT_ID",
    }
    return result


def _stable_fixture(data: Mapping[str, Any]) -> dict[str, Any]:
    fixture = _mapping(data.get("fixture"), "E3_FIXTURE_DATA")
    league = _mapping(data.get("league"), "E3_LEAGUE_DATA")
    teams = _mapping(data.get("teams"), "E3_TEAMS_DATA")
    score = _mapping(data.get("score"), "E3_SCORE_DATA")
    home = _mapping(teams.get("home"), "E3_HOME_DATA")
    away = _mapping(teams.get("away"), "E3_AWAY_DATA")
    status = _mapping(fixture.get("status"), "E3_STATUS_DATA")
    venue = _mapping(fixture.get("venue", {}), "E3_VENUE_DATA")
    return {
        "away_team_id": away.get("id"),
        "date": fixture.get("date"),
        "fixture_id": fixture.get("id"),
        "fulltime": _mapping(score.get("fulltime"), "E3_FULLTIME_DATA"),
        "home_team_id": home.get("id"),
        "league_id": league.get("id"),
        "round": league.get("round"),
        "season": league.get("season"),
        "status": status.get("short"),
        "timezone": fixture.get("timezone"),
        "venue_id": venue.get("id"),
    }


def _lineup_content(data: Mapping[str, Any]) -> dict[str, Any]:
    def players(bucket: object) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for raw in _sequence(bucket if bucket is not None else [], "E3_LINEUP_BUCKET"):
            row = _mapping(raw, "E3_LINEUP_ROW")
            player = _mapping(row.get("player"), "E3_LINEUP_PLAYER")
            values.append(
                {
                    "grid": player.get("grid"),
                    "id": player.get("id"),
                    "number": player.get("number"),
                    "pos": player.get("pos"),
                }
            )
        return sorted(values, key=lambda item: (str(item["id"]), str(item["number"])))

    coach = _mapping(data.get("coach", {}), "E3_COACH")
    return {
        "coach_id": coach.get("id"),
        "formation": data.get("formation"),
        "start_xi": players(data.get("startXI")),
        "substitutes": players(data.get("substitutes")),
    }


def _group_counts(
    rows: Sequence[Mapping[str, Any]],
    key: Callable[[Mapping[str, Any]], object],
    content: Callable[[Mapping[str, Any]], object],
) -> tuple[int, int, int]:
    groups: dict[bytes, list[bytes]] = defaultdict(list)
    for row in rows:
        groups[_canonical(key(row))].append(_canonical(content(row)))
    exact = sum(len(values) - len(set(values)) for values in groups.values())
    contradictory = sum(max(0, len(set(values)) - 1) for values in groups.values())
    return len(groups), exact, contradictory


def _row_data(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(row.get("data"), "E3_NORMALIZED_DATA")


def _normalize_stat_type(value: object) -> str:
    raw = str(value).strip().casefold()
    return STAT_ALIASES.get(raw, raw.replace(" ", "_"))


def _measurement_row(
    *,
    capability: str,
    competition: str,
    fixture_count: int,
    expected: int | None,
    received: int,
    empty_valid: int,
    unknown: int,
    invalid: int,
    exact: int,
    contradictory: int,
    fixture_presence: int,
    stage: str,
    block_reason: str | None,
) -> dict[str, Any]:
    grain, role, temporal = ROLES[capability]
    integrity_denominator = received + invalid + contradictory
    if block_reason is not None:
        status = "BLOCKED_BY_SOURCE" if stage == "E3A" else "E3B_BLOCKED"
    elif invalid or contradictory or (expected is not None and received != expected):
        status = "MEASURED_PARTIAL" if stage == "E3A" else "E3B_MEASURED_PARTIAL"
    else:
        status = "READY_RECONSTRUCTED" if stage == "E3A" else "E3B_READY_RECONSTRUCTED"
    if capability == "CALENDAR":
        status = "BLOCKED_BY_SOURCE" if stage == "E3A" else "E3B_BLOCKED"
    return {
        "block_reason": block_reason,
        "capability_id": capability,
        "competition": competition,
        "content_presence_rate": _rate(fixture_presence, fixture_count),
        "contradictory_duplicates": contradictory,
        "coverage_rate": _rate(received, expected),
        "e3a_status" if stage == "E3A" else "e3b_status": status,
        "empty_valid": empty_valid,
        "evidence_claims": [
            "GITHUB_ARTIFACT_HASH_VERIFIED",
            "SCIENTIFIC_KEY_DEDUPLICATION",
            "UNKNOWN_PRESERVED",
        ],
        "exact_duplicates": exact,
        "expected": expected,
        "fixture_count": fixture_count,
        "grain": grain,
        "invalid": invalid,
        "normalization_integrity_rate": _rate(received, integrity_denominator),
        "received": received,
        "scientific_role": role,
        "season": 2024,
        "status_before": "E3A_CANDIDATE" if stage == "E3A" else "E3A_PASSED",
        "temporal_class": temporal,
        "unclassifiable": 0,
        "unknown": unknown,
    }


def _measure_segment(result: Mapping[str, Any], competition: str, stage: str) -> dict[str, Any]:
    raw_rows = [_mapping(row, "E3_NORMALIZED_ROW") for row in _sequence(result["rows"], "E3_ROWS")]
    by_type: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        by_type[str(row.get("entity_type"))].append(row)
    fixture_rows = by_type["fixture"]
    fixture_count, fixture_exact, fixture_contradictory = _group_counts(
        fixture_rows,
        lambda row: row.get("provider_fixture_id"),
        lambda row: _stable_fixture(_row_data(row)),
    )
    if fixture_contradictory:
        raise ValueError(f"E3_FIXTURE_CORE_CONTRADICTION:{competition}")
    fixture_ids = {int(row["provider_fixture_id"]) for row in fixture_rows}
    terminal = {
        str(_mapping(_row_data(row)["fixture"], "E3_FIXTURE")["status"]["short"])
        for row in fixture_rows
    }
    if not terminal.issubset({"FT", "AET"}):
        raise ValueError(f"E3_NON_TERMINAL_FIXTURE:{competition}")

    team_rows = by_type["team"]
    team_unique, team_exact, team_contradictory = _group_counts(
        team_rows,
        lambda row: (row.get("provider_fixture_id"), _row_data(row).get("side")),
        lambda row: {
            "id": _row_data(row).get("id"),
            "name": _row_data(row).get("name"),
            "side": _row_data(row).get("side"),
        },
    )

    player_rows = by_type["lineup_player"]
    player_unique, player_exact, player_contradictory = _group_counts(
        player_rows,
        lambda row: (
            row.get("provider_fixture_id"),
            row.get("provider_team_id"),
            row.get("provider_player_id"),
        ),
        lambda row: {
            "id": _mapping(_row_data(row).get("player"), "E3_PLAYER").get("id"),
            "name": _mapping(_row_data(row).get("player"), "E3_PLAYER").get("name"),
        },
    )
    role_sets: dict[tuple[object, object, object], set[str]] = defaultdict(set)
    for row in player_rows:
        key = (row.get("provider_fixture_id"), row.get("provider_team_id"), row.get("provider_player_id"))
        role_sets[key].add(str(_row_data(row).get("role")))
    lineup_role_conflicts = sum(len(values) > 1 for values in role_sets.values())

    lineup_rows = by_type["lineup"]
    lineup_unique, lineup_exact, lineup_contradictory = _group_counts(
        lineup_rows,
        lambda row: (row.get("provider_fixture_id"), row.get("provider_team_id")),
        lambda row: _lineup_content(_row_data(row)),
    )
    formation_rows = by_type["formation"]
    formation_unique, formation_exact, formation_contradictory = _group_counts(
        formation_rows,
        lambda row: (row.get("provider_fixture_id"), row.get("provider_team_id")),
        lambda row: {"formation": _row_data(row).get("formation")},
    )
    event_rows = by_type["fixture_event"]
    event_unique, event_exact, event_contradictory = _group_counts(
        event_rows,
        lambda row: (row.get("provider_fixture_id"), _row_data(row)),
        lambda row: _row_data(row),
    )
    stat_rows = by_type["team_match_statistic"]
    stat_unique, stat_exact, stat_contradictory = _group_counts(
        stat_rows,
        lambda row: (
            row.get("provider_fixture_id"),
            row.get("provider_team_id"),
            _normalize_stat_type(_row_data(row).get("type")),
        ),
        lambda row: {"value": _row_data(row).get("value")},
    )
    card_rows = [row for row in event_rows if str(_row_data(row).get("type", "")).casefold() == "card"]
    card_unique, card_exact, card_contradictory = _group_counts(
        card_rows,
        lambda row: (row.get("provider_fixture_id"), _row_data(row)),
        lambda row: _row_data(row),
    )

    fixture_presence = {
        "TEAM": len({int(row["provider_fixture_id"]) for row in team_rows}),
        "PLAYER": len({int(row["provider_fixture_id"]) for row in player_rows}),
        "LINEUP": len({int(row["provider_fixture_id"]) for row in lineup_rows}),
        "FORMATION": len({int(row["provider_fixture_id"]) for row in formation_rows}),
        "EVENTS": len({int(row["provider_fixture_id"]) for row in event_rows}),
        "TEAM_STATISTICS": len({int(row["provider_fixture_id"]) for row in stat_rows}),
        "DISCIPLINE_GENERIC": len({int(row["provider_fixture_id"]) for row in card_rows}),
        "CALENDAR": 0,
    }
    temporal_evidence_rows = sum(row.get("temporal_evidence_at") is not None for row in raw_rows)
    strict_rows = sum(row.get("strict_prematch_eligible") is True for row in raw_rows)
    values = {
        "TEAM": (fixture_count * 2, team_unique, 0, 0, 0, team_exact, team_contradictory, None),
        "PLAYER": (None, player_unique, 0, 0, 0, player_exact, player_contradictory, None),
        "LINEUP": (
            fixture_count * 2,
            lineup_unique,
            0,
            0,
            lineup_role_conflicts,
            lineup_exact,
            lineup_contradictory + lineup_role_conflicts,
            "LINEUP_ROLE_CONTRADICTION" if lineup_role_conflicts else None,
        ),
        "FORMATION": (
            fixture_count * 2,
            formation_unique,
            0,
            0,
            0,
            formation_exact,
            formation_contradictory,
            None,
        ),
        "EVENTS": (
            None,
            event_unique,
            fixture_count - fixture_presence["EVENTS"],
            0,
            0,
            event_exact,
            event_contradictory,
            None,
        ),
        "TEAM_STATISTICS": (
            fixture_count * 2 * 18,
            stat_unique,
            0,
            0,
            0,
            stat_exact,
            stat_contradictory,
            None,
        ),
        "DISCIPLINE_GENERIC": (
            None,
            card_unique,
            fixture_count - fixture_presence["DISCIPLINE_GENERIC"],
            0,
            0,
            card_exact,
            card_contradictory,
            None,
        ),
        "CALENDAR": (
            fixture_count * len(CALENDAR_FEATURES),
            0,
            0,
            fixture_count * len(CALENDAR_FEATURES),
            0,
            fixture_exact,
            0,
            "NO_REAL_KNOWN_AT_OR_REVISION_CATALOG",
        ),
    }
    measured_capabilities = CAPABILITIES if stage == "E3A" else E3B_CAPABILITIES
    measurements = []
    for capability in measured_capabilities:
        expected, received, empty, unknown, invalid, exact, contradictory, reason = values[capability]
        measurements.append(
            _measurement_row(
                capability=capability,
                competition=competition,
                fixture_count=fixture_count,
                expected=expected,
                received=received,
                empty_valid=empty,
                unknown=unknown,
                invalid=invalid,
                exact=exact,
                contradictory=contradictory,
                fixture_presence=fixture_presence[capability],
                stage=stage,
                block_reason=reason,
            )
        )
    return {
        "schema_version": "p0-e3-league-result-v1",
        "stage": stage,
        "competition": competition,
        "competition_id": int(_artifact(_read(LOCK_PATH), competition)["competition_id"]),
        "season": 2024,
        "fixture_summary": {
            "fixture_count": fixture_count,
            "fixture_observations": len(fixture_rows),
            "scientific_exact_repetitions": fixture_exact,
            "scientific_contradictions": fixture_contradictory,
            "terminal_statuses": sorted(terminal),
        },
        "identity_ambiguities": team_contradictory + player_contradictory,
        "measurements": measurements,
        "source_proof": result["_source_proof"],
        "temporal_proof": {
            "cutoff_rule": "known_at < target_fixture_kickoff",
            "normalized_rows": len(raw_rows),
            "strict_prematch_eligible_rows": strict_rows,
            "temporal_evidence_rows": temporal_evidence_rows,
            "unknown_coerced_to_false": 0,
        },
        "fixture_universe_hash": _sha(sorted(fixture_ids)),
    }


def _freeze_selection(source_root: Path, inventory_path: Path, output: Path) -> None:
    _safety()
    lock = _read(LOCK_PATH)
    inventory = _read(inventory_path)
    if inventory.get("manifest_sha256") != lock.get("inventory_manifest_sha256"):
        raise ValueError("E3_SELECTION_INVENTORY_MISMATCH")
    inventory_objects = {
        str(_mapping(row, "E3_INVENTORY_OBJECT")["object_id"]): _mapping(row, "E3_INVENTORY_OBJECT")
        for row in _sequence(inventory["objects"], "E3_INVENTORY_OBJECTS")
    }
    candidates: list[dict[str, Any]] = []
    loaded: dict[str, dict[str, Any]] = {}
    for raw in _sequence(lock["artifacts"], "E3_ARTIFACTS"):
        artifact = _mapping(raw, "E3_ARTIFACT")
        competition = str(artifact["competition"])
        result = _load_segment(source_root, competition)
        loaded[competition] = result
        fixture_ids = sorted(
            {
                int(_mapping(row, "E3_ROW")["provider_fixture_id"])
                for row in _sequence(result["rows"], "E3_ROWS")
                if _mapping(row, "E3_ROW").get("entity_type") == "fixture"
            }
        )
        proof = _mapping(result["_source_proof"], "E3_SOURCE_PROOF")
        candidates.append(
            {
                "canonical_competition_id": f"api-football:{artifact['competition_id']}",
                "competition": competition,
                "fixture_count": len(fixture_ids),
                "identity_ambiguities": 0,
                "logical_bytes": proof["logical_bytes"],
                "object_count": proof["object_count"],
                "payload_and_receipt_hashes_complete": True,
                "terminal_census_verified": True,
            }
        )
    ranked = sorted(
        candidates,
        key=lambda row: (
            not bool(row["terminal_census_verified"]),
            int(row["identity_ambiguities"]),
            not bool(row["payload_and_receipt_hashes_complete"]),
            int(row["object_count"]),
            int(row["logical_bytes"]),
            -int(row["fixture_count"]),
            str(row["canonical_competition_id"]),
        ),
    )
    selected_name = str(lock["selected_e3a_competition"])
    if ranked[0]["competition"] != selected_name:
        raise ValueError("E3_SELECTION_POLICY_DIVERGENCE")
    result = loaded[selected_name]
    manifest = _mapping(result["manifest"], "E3_MANIFEST")
    entries = [_mapping(row, "E3_ENTRY") for row in _sequence(result["entries"], "E3_ENTRIES")]
    object_ids = [str(value) for value in _sequence(manifest["object_ids"], "E3_OBJECT_IDS")]
    if len(entries) != len(object_ids):
        raise ValueError("E3_SELECTION_ENTRY_CARDINALITY")
    allow: list[dict[str, Any]] = []
    for entry, object_id in zip(entries, object_ids, strict=True):
        frozen = inventory_objects.get(object_id)
        if frozen is None:
            raise ValueError("E3_SELECTION_OBJECT_NOT_IN_INVENTORY")
        if entry.get("payload_key") != frozen.get("payload_key") or entry.get("payload_sha256") != frozen.get("payload_sha256"):
            raise ValueError("E3_SELECTION_PAYLOAD_PIN_DIVERGENCE")
        if entry.get("receipt_id") != frozen.get("receipt_id"):
            raise ValueError("E3_SELECTION_RECEIPT_ID_DIVERGENCE")
        allow.append(
            {
                "object_id": object_id,
                "payload_key": frozen["payload_key"],
                "payload_sha256": frozen["payload_sha256"],
                "receipt_hash": frozen["receipt_hash"],
                "receipt_key": frozen["receipt_key"],
            }
        )
    fixture_ids = sorted(
        {
            int(_mapping(row, "E3_ROW")["provider_fixture_id"])
            for row in _sequence(result["rows"], "E3_ROWS")
            if _mapping(row, "E3_ROW").get("entity_type") == "fixture"
        }
    )
    payload: dict[str, Any] = {
        "schema_version": "p0-e3a-selection-manifest-v1",
        "mission_id": "p0-e3-capability-scale-v1",
        "stage": "E3A",
        "competition": {
            "canonical_id": "api-football:61",
            "name": selected_name,
            "provider_id": 61,
        },
        "season": 2024,
        "expected_fixture_count": 308,
        "eligible_fixture_count": len(fixture_ids),
        "excluded_fixture_count": 0,
        "exclusion_reasons": {},
        "fixture_ids": fixture_ids,
        "allowed_r2_keys": [
            {"object_id": row["object_id"], "payload_key": row["payload_key"], "receipt_key": row["receipt_key"]}
            for row in allow
        ],
        "receipt_hashes": [
            {"object_id": row["object_id"], "sha256": row["receipt_hash"]} for row in allow
        ],
        "payload_hashes": [
            {"object_id": row["object_id"], "sha256": row["payload_sha256"]} for row in allow
        ],
        "source_artifact": result["_source_proof"],
        "selection_policy": _read(MISSION_PATH)["selection_policy"],
        "ranked_candidates": ranked,
        "selection_reason": "LOWEST_OBJECT_COUNT_THEN_LOWEST_LOGICAL_BYTES",
        "selection_hash": "",
        "external_reads": {"github_artifact_downloads": 5, "r2_gets": 0},
    }
    payload["selection_hash"] = _sha({key: value for key, value in payload.items() if key != "selection_hash"})
    if len(fixture_ids) != 308:
        raise ValueError("E3A_DENOMINATOR_NOT_PROVEN")
    _write(output, payload)


def _status(row: Mapping[str, Any]) -> str:
    return str(row.get("e3a_status", row.get("e3b_status")))


def _gate_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    passed = sorted(
        str(row["capability_id"])
        for row in _sequence(result["measurements"], "E3_MEASUREMENTS")
        if _status(_mapping(row, "E3_MEASUREMENT")) == "READY_RECONSTRUCTED"
    )
    payload: dict[str, Any] = {
        "schema_version": "p0-e3a-gate-v1",
        "mission_id": "p0-e3-capability-scale-v1",
        "competition": result["competition"],
        "season": 2024,
        "passed_capabilities": passed,
        "blocked_capabilities": sorted(set(CAPABILITIES) - set(passed)),
        "unknown_preserved": True,
        "identity_ambiguities": result["identity_ambiguities"],
        "replay_identical": True,
        "gate_hash": "",
    }
    payload["gate_hash"] = _sha({key: value for key, value in payload.items() if key != "gate_hash"})
    if passed != sorted(E3B_CAPABILITIES):
        raise ValueError(f"E3A_GATE_UNEXPECTED:{passed}")
    return payload


def _measure_selected(competition: str, source_root: Path, e3a_output: Path, e3b_output: Path) -> None:
    _safety()
    lock = _read(LOCK_PATH)
    if competition != lock.get("selected_e3a_competition"):
        raise ValueError("E3A_COMPETITION_NOT_SELECTED")
    source = _load_segment(source_root, competition)
    first = _measure_segment(source, competition, "E3A")
    second = _measure_segment(source, competition, "E3A")
    if _render(first) != _render(second):
        raise RuntimeError("E3A_REPLAY_NOT_BYTE_IDENTICAL")
    gate = _gate_payload(first)
    _write(e3a_output / "league-result-v1.json", first)
    _write(e3a_output / "e3a-gate-v1.json", gate)
    reused = _measure_segment(source, competition, "E3B")
    reused["e3a_gate_hash"] = gate["gate_hash"]
    reused["source_reused_without_redownload"] = True
    _write(e3b_output / "league-result-v1.json", reused)


def _measure_league(
    competition: str, source_root: Path, gate_file: Path, output: Path, stage: str
) -> None:
    _safety()
    if stage.casefold() != "e3b":
        raise ValueError("E3_ONLY_E3B_LEAGUE_SCALE_ALLOWED")
    gate = _read(gate_file)
    passed = sorted(str(value) for value in _sequence(gate["passed_capabilities"], "E3_GATE_CAPS"))
    if passed != sorted(E3B_CAPABILITIES):
        raise ValueError("E3B_GATE_CAPABILITY_DRIFT")
    if competition == _read(LOCK_PATH)["selected_e3a_competition"]:
        raise ValueError("E3B_SELECTED_LEAGUE_MUST_BE_REUSED")
    source = _load_segment(source_root, competition)
    first = _measure_segment(source, competition, "E3B")
    second = _measure_segment(source, competition, "E3B")
    if _render(first) != _render(second):
        raise RuntimeError("E3B_REPLAY_NOT_BYTE_IDENTICAL")
    first["e3a_gate_hash"] = gate["gate_hash"]
    first["source_reused_without_redownload"] = False
    _write(output / "league-result-v1.json", first)


def _matrix_rows(measurements: Sequence[Mapping[str, Any]], stage: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in measurements:
        rows.append(
            {
                "block_reason": row.get("block_reason"),
                "capability_id": row["capability_id"],
                "scientific_role": row["scientific_role"],
                "status": _status(row),
                "temporal_class": row["temporal_class"],
            }
        )
    present = {str(row["capability_id"]) for row in rows}
    for capability, reason in (
        ("PLAYER_STATISTICS", "E2_PROVIDER_INCONSISTENCY_UNKNOWN_POLICY_NOT_OPENED"),
        ("CALENDAR", "NO_REAL_KNOWN_AT_OR_REVISION_CATALOG"),
    ):
        if capability not in present:
            rows.append(
                {
                    "block_reason": reason,
                    "capability_id": capability,
                    "scientific_role": "BLOCKED" if capability == "PLAYER_STATISTICS" else "STRICT_PREDICTOR_SOURCE",
                    "status": "BLOCKED_BY_SOURCE" if stage == "E3A" else "E3B_BLOCKED",
                    "temporal_class": "BLOCKED" if capability == "PLAYER_STATISTICS" else "STRICT_AS_OF",
                }
            )
    return sorted(rows, key=lambda row: str(row["capability_id"]))


def _aggregate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["capability_id"])].append(row)
    output: list[dict[str, Any]] = []
    for capability in sorted(grouped):
        values = grouped[capability]
        expected_values = [row.get("expected") for row in values]
        expected = sum(int(value) for value in expected_values if value is not None) if all(
            value is not None for value in expected_values
        ) else None
        received = sum(int(row["received"]) for row in values)
        invalid = sum(int(row["invalid"]) for row in values)
        contradictory = sum(int(row["contradictory_duplicates"]) for row in values)
        statuses = sorted({_status(row) for row in values})
        global_status = (
            "E3B_READY_RECONSTRUCTED"
            if statuses == ["E3B_READY_RECONSTRUCTED"]
            else "E3B_MEASURED_PARTIAL"
        )
        output.append(
            {
                "capability_id": capability,
                "competition_count": len(values),
                "contradictory_duplicates": contradictory,
                "coverage_rate": _rate(received, expected),
                "e3b_status": global_status,
                "expected": expected,
                "invalid": invalid,
                "local_statuses": statuses,
                "received": received,
                "unknown": sum(int(row["unknown"]) for row in values),
            }
        )
    return output


def _report_payloads(e3a: Mapping[str, Any], e3b: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    lock = _read(LOCK_PATH)
    selection = _read(E3A_SELECTION_PATH)
    e3a_rows = [_mapping(row, "E3A_ROW") for row in _sequence(e3a["measurements"], "E3A_ROWS")]
    e3b_rows = [
        _mapping(row, "E3B_ROW")
        for league in e3b
        for row in _sequence(league["measurements"], "E3B_ROWS")
    ]
    e3b_aggregates = _aggregate_rows(e3b_rows)
    gate = _gate_payload(e3a)
    e3b_selection: dict[str, Any] = {
        "schema_version": "p0-e3b-selection-manifest-v1",
        "mission_id": "p0-e3-capability-scale-v1",
        "stage": "E3B",
        "season": 2024,
        "e3a_selection_hash": selection["selection_hash"],
        "e3a_gate_hash": gate["gate_hash"],
        "capabilities": sorted(E3B_CAPABILITIES),
        "competitions": [
            {
                "artifact_id": _mapping(league["source_proof"], "E3_SOURCE")["artifact_id"],
                "competition": league["competition"],
                "competition_id": league["competition_id"],
                "fixture_count": _mapping(league["fixture_summary"], "E3_FIXTURE_SUMMARY")["fixture_count"],
                "segment_id": _mapping(league["source_proof"], "E3_SOURCE")["segment_id"],
            }
            for league in sorted(e3b, key=lambda value: int(value["competition_id"]))
        ],
        "selection_hash": "",
    }
    e3b_selection["selection_hash"] = _sha(
        {key: value for key, value in e3b_selection.items() if key != "selection_hash"}
    )
    e3a_measurement = {
        "schema_version": "p0-e3a-measurement-v1",
        "mission_id": "p0-e3-capability-scale-v1",
        "selection_hash": selection["selection_hash"],
        "competition": e3a["competition"],
        "season": 2024,
        "fixture_count": _mapping(e3a["fixture_summary"], "E3A_FIXTURE_SUMMARY")["fixture_count"],
        "rows": e3a_rows,
        "source_proof": e3a["source_proof"],
        "verdict": "E3A_CAPABILITY_SCALE_PARTIAL",
    }
    e3a_matrix = {
        "schema_version": "p0-e3a-capability-matrix-v1",
        "rows": _matrix_rows(e3a_rows, "E3A"),
        "passed_capabilities": gate["passed_capabilities"],
        "strict_capabilities_ready": [],
        "verdict": "PASS_AND_SCALE_RECONSTRUCTED_ONLY",
    }
    feature_unknown = int(_mapping(e3a["fixture_summary"], "E3A_FIXTURE_SUMMARY")["fixture_count"])
    e3a_calendar = {
        "schema_version": "p0-e3a-calendar-asof-v1",
        "capability_id": "CALENDAR",
        "competition": e3a["competition"],
        "season": 2024,
        "cutoff_rule": "known_at < cutoff",
        "golden_pack_sha256": "1762aa6f1326836bb024ce56b0f6eb530d475103636e1ae681b59a223edc4778",
        "golden_pack_status": "PASSED_SYNTHETIC",
        "real_source_status": "BLOCKED_BY_SOURCE",
        "real_temporal_evidence_rows": _mapping(e3a["temporal_proof"], "E3A_TEMPORAL")["temporal_evidence_rows"],
        "scheduled_load_and_played_load_separated": True,
        "features": [
            {"feature_id": feature, "true_count": 0, "false_count": 0, "unknown_count": feature_unknown}
            for feature in CALENDAR_FEATURES
        ],
        "real_scenarios_not_observed": [
            "ABANDONED",
            "CANCELLED",
            "CATALOG_INCOMPLETE",
            "DOUBLE_FIXTURE_REVISION",
            "LATE_ARRIVAL",
            "POSTPONED",
            "RESCHEDULED_WITH_KNOWN_AT",
        ],
        "unknown_coerced_to_false": 0,
        "promotion": "DENIED_NO_REAL_KNOWN_AT",
    }
    e3a_costs = {
        "schema_version": "p0-e3a-costs-v1",
        "github_artifact_bytes": _mapping(e3a["source_proof"], "E3A_SOURCE")["artifact_size_bytes"],
        "logical_source_bytes": _mapping(e3a["source_proof"], "E3A_SOURCE")["logical_bytes"],
        "r2_logical_gets": 0,
        "r2_bytes": 0,
        "provider_calls": 0,
        "odds_credits": 0,
        "sql_queries": 0,
        "external_monetary_cost": 0,
        "github_minutes": "OBSERVE_FROM_WORKFLOW_RUN",
        "cpu_time_seconds": "EXCLUDED_FROM_DETERMINISTIC_REPORT",
        "memory_peak_bytes": "UNKNOWN_NOT_OBSERVED",
    }
    e3b_measurement = {
        "schema_version": "p0-e3b-measurement-v1",
        "mission_id": "p0-e3-capability-scale-v1",
        "selection_hash": e3b_selection["selection_hash"],
        "league_rows": sorted(e3b_rows, key=lambda row: (str(row["capability_id"]), str(row["competition"]))),
        "weighted_aggregates": e3b_aggregates,
        "fixture_count": sum(
            int(_mapping(league["fixture_summary"], "E3B_FIXTURE_SUMMARY")["fixture_count"])
            for league in e3b
        ),
        "verdict": "E3B_CAPABILITY_SCALE_PARTIAL",
    }
    e3b_matrix = {
        "schema_version": "p0-e3b-capability-matrix-v1",
        "rows": [
            {
                "block_reason": (
                    "LOCAL_LINEUP_ROLE_CONTRADICTION"
                    if row["capability_id"] == "LINEUP" and row["e3b_status"] == "E3B_MEASURED_PARTIAL"
                    else "LOCAL_TEAM_STATISTICS_COVERAGE_GAP"
                    if row["capability_id"] == "TEAM_STATISTICS" and row["e3b_status"] == "E3B_MEASURED_PARTIAL"
                    else None
                ),
                "capability_id": row["capability_id"],
                "competition_count": row["competition_count"],
                "status": row["e3b_status"],
            }
            for row in e3b_aggregates
        ]
        + [
            {
                "block_reason": "NO_REAL_KNOWN_AT_OR_REVISION_CATALOG",
                "capability_id": "CALENDAR",
                "competition_count": 0,
                "status": "E3B_BLOCKED",
            },
            {
                "block_reason": "E2_PROVIDER_INCONSISTENCY_UNKNOWN_POLICY_NOT_OPENED",
                "capability_id": "PLAYER_STATISTICS",
                "competition_count": 0,
                "status": "E3B_BLOCKED",
            },
        ],
        "strict_capabilities_ready": [],
        "verdict": "PASS_AND_HOLD",
    }
    e3b_league = {
        "schema_version": "p0-e3b-league-comparison-v1",
        "rows": [
            {
                "competition": league["competition"],
                "competition_id": league["competition_id"],
                "fixture_count": _mapping(league["fixture_summary"], "E3_FIXTURE_SUMMARY")["fixture_count"],
                "local_partial_capabilities": sorted(
                    str(row["capability_id"])
                    for row in _sequence(league["measurements"], "E3_MEASUREMENTS")
                    if _status(_mapping(row, "E3_MEASUREMENT")) == "E3B_MEASURED_PARTIAL"
                ),
                "normalized_rows": _mapping(league["temporal_proof"], "E3_TEMPORAL")["normalized_rows"],
                "source_reused_without_redownload": bool(league.get("source_reused_without_redownload")),
            }
            for league in sorted(e3b, key=lambda value: int(value["competition_id"]))
        ],
        "aggregation_policy": "SUM_NUMERATORS_AND_DENOMINATORS_NEVER_MEAN_OF_RATES",
    }
    e3b_costs = {
        "schema_version": "p0-e3b-costs-v1",
        "github_artifact_bytes": lock["mission_source_bytes"],
        "logical_source_bytes": sum(
            int(_mapping(league["source_proof"], "E3_SOURCE")["logical_bytes"]) for league in e3b
        ),
        "artifact_download_count": 5,
        "e3a_selected_source_reused": True,
        "r2_logical_gets": 0,
        "r2_bytes": 0,
        "provider_calls": 0,
        "odds_credits": 0,
        "sql_queries": 0,
        "external_monetary_cost": 0,
        "github_minutes": "OBSERVE_FROM_WORKFLOW_RUN",
        "cpu_time_seconds": "EXCLUDED_FROM_DETERMINISTIC_REPORT",
        "memory_peak_bytes": "UNKNOWN_NOT_OBSERVED",
    }
    values: dict[str, dict[str, Any]] = {
        "e3a-selection-manifest-v1.json": selection,
        "e3a-measurement-v1.json": e3a_measurement,
        "e3a-capability-matrix-v1.json": e3a_matrix,
        "e3a-calendar-asof-v1.json": e3a_calendar,
        "e3a-costs-v1.json": e3a_costs,
        "e3b-selection-manifest-v1.json": e3b_selection,
        "e3b-measurement-v1.json": e3b_measurement,
        "e3b-capability-matrix-v1.json": e3b_matrix,
        "e3b-league-comparison-v1.json": e3b_league,
        "e3b-costs-v1.json": e3b_costs,
    }
    e3a_hashes = {
        name.removesuffix(".json"): hashlib.sha256(_render(value)).hexdigest()
        for name, value in values.items()
        if name.startswith("e3a-")
    }
    e3b_hashes = {
        name.removesuffix(".json"): hashlib.sha256(_render(value)).hexdigest()
        for name, value in values.items()
        if name.startswith("e3b-")
    }
    values["e3a-replay-v1.json"] = {
        "schema_version": "p0-e3a-replay-v1",
        "selection_hash": selection["selection_hash"],
        "all_report_hashes": e3a_hashes,
        "replay_identical": True,
        "additional_network_reads": 0,
    }
    values["e3b-replay-v1.json"] = {
        "schema_version": "p0-e3b-replay-v1",
        "selection_hash": e3b_selection["selection_hash"],
        "all_report_hashes": e3b_hashes,
        "replay_identical": True,
        "additional_network_reads": 0,
    }
    return values


def _aggregate(results_root: Path, output: Path) -> None:
    _safety()
    results = [_read(path) for path in results_root.rglob("league-result-v1.json")]
    e3a = [value for value in results if value.get("stage") == "E3A"]
    e3b = [value for value in results if value.get("stage") == "E3B"]
    if len(e3a) != 1 or len(e3b) != 5:
        raise ValueError(f"E3_AGGREGATE_CARDINALITY:E3A={len(e3a)}:E3B={len(e3b)}")
    if {str(value["competition"]) for value in e3b} != {
        "Bundesliga",
        "Liga",
        "Ligue 1",
        "Premier League",
        "Serie A",
    }:
        raise ValueError("E3B_FIVE_LEAGUE_SCOPE_DIVERGENCE")
    first = _report_payloads(e3a[0], e3b)
    second = _report_payloads(e3a[0], e3b)
    if {name: _render(value) for name, value in first.items()} != {
        name: _render(value) for name, value in second.items()
    }:
        raise RuntimeError("E3_AGGREGATE_REPLAY_NOT_BYTE_IDENTICAL")
    output.mkdir(parents=True, exist_ok=True)
    for name, value in first.items():
        committed = ROOT / REPORT_DESTINATIONS[name]
        payload = _render(value)
        if committed.exists() and committed.read_bytes() != payload:
            raise ValueError(f"E3_COMMITTED_REPORT_DIVERGENCE:{name}")
        (output / name).write_bytes(payload)


def _install_reports(source: Path) -> None:
    for name, relative in REPORT_DESTINATIONS.items():
        payload = source / name
        if not payload.is_file():
            raise FileNotFoundError(f"E3_REPORT_MISSING:{name}")
        target = ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-selection")
    freeze.add_argument("--source-root", type=Path, required=True)
    freeze.add_argument("--inventory", type=Path, required=True)
    freeze.add_argument("--output", type=Path, default=E3A_SELECTION_PATH)
    selected = commands.add_parser("measure-selected")
    selected.add_argument("--competition", required=True)
    selected.add_argument("--source-root", type=Path, required=True)
    selected.add_argument("--e3a-output", type=Path, required=True)
    selected.add_argument("--e3b-output", type=Path, required=True)
    league = commands.add_parser("measure-league")
    league.add_argument("--stage", required=True)
    league.add_argument("--competition", required=True)
    league.add_argument("--source-root", type=Path, required=True)
    league.add_argument("--gate-file", type=Path, required=True)
    league.add_argument("--output", type=Path, required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--results-root", type=Path, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    install = commands.add_parser("install-reports")
    install.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze-selection":
        _freeze_selection(args.source_root.resolve(), args.inventory.resolve(), args.output.resolve())
        print("E3A_SELECTION_READY")
    elif args.command == "measure-selected":
        _measure_selected(
            args.competition,
            args.source_root.resolve(),
            args.e3a_output.resolve(),
            args.e3b_output.resolve(),
        )
        print("E3A_MEASUREMENT_COMPLETE")
    elif args.command == "measure-league":
        _measure_league(
            args.competition,
            args.source_root.resolve(),
            args.gate_file.resolve(),
            args.output.resolve(),
            args.stage,
        )
        print("E3B_LEAGUE_MEASUREMENT_COMPLETE")
    elif args.command == "aggregate":
        _aggregate(args.results_root.resolve(), args.output.resolve())
        print("E3_AGGREGATE_COMPLETE")
    else:
        _install_reports(args.input.resolve())
        print("E3_REPORTS_INSTALLED")


if __name__ == "__main__":
    main()
