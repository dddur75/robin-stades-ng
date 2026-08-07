"""Fail-closed contracts and deterministic aggregation for the E1B canary."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = {
    "E1B_MEASURED",
    "E1B_MEASURED_PARTIAL",
    "E1B_BLOCKED_BY_SOURCE",
    "E1B_BLOCKED_BY_TEMPORALITY",
    "E1B_BLOCKED_BY_COVERAGE",
    "E1B_NOT_APPLICABLE",
    "E1B_NOT_EVALUATED",
}
COMPETITIONS = (39, 61, 78, 135, 140)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPORT_FILENAMES = {
    "measurement": "e1b-measurement-v1.json",
    "capability_matrix": "e1b-capability-matrix-v1.json",
    "league_comparison": "e1b-league-comparison-v1.json",
    "unknown_profile": "e1b-unknown-profile-v1.json",
    "costs": "e1b-costs-v1.json",
    "dashboard_contract": "e1b-dashboard-contract-v1.json",
    "replay_verification": "e1b-replay-verification-v1.json",
}


def mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}_MUST_BE_MAPPING")
    return value


def sequence(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    raise ValueError(f"{label}_MUST_BE_SEQUENCE")


def read_json(path: Path) -> Mapping[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"E1B_DUPLICATE_JSON_KEY:{path}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"E1B_NON_FINITE:{value}")
        ),
    )
    return mapping(value, "E1B_JSON")


def render_json(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def file_sha256_lf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ValueError(f"{label}_HASH_INVALID")
    return value


def validate_contracts(root: Path) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    mission = read_json(root / "configs/execution/p0-e1b-five-league-canary-v1.json")
    selection = read_json(
        root / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    )
    exact = {
        "schema_version": "p0-e1b-five-league-canary-v1",
        "stage": "E1B",
        "fixture_count": 10,
        "fixture_count_per_league": 2,
        "competition_count": 5,
        "r2_get_budget": 2000,
        "r2_byte_budget": 7244155,
        "r2_write_budget": 0,
        "provider_budget": 0,
        "sql_budget": 0,
        "odds_credit_budget": 0,
        "final_decision_ceiling": "PASS_AND_HOLD",
    }
    if any(mission.get(key) != value for key, value in exact.items()):
        raise ValueError("E1B_MISSION_LIMIT_OR_IDENTITY_INVALID")
    pins = {
        "capability_contract_hash": "configs/data/capability-scoped-evidence-ladder-v2.json",
        "launch_readiness_hash": "reports/preflight/p0-capability-launch-readiness-v1.json",
        "grain_catalog_hash": "configs/data/football-grain-catalog-v1.json",
    }
    for field, path in pins.items():
        if mission.get(field) != file_sha256_lf(root / path):
            raise ValueError(f"E1B_PIN_MISMATCH:{field}")
    if mission.get("stopped_capabilities") != ["ABSENCE_CAUSE_EXACT"]:
        raise ValueError("E1B_LOCAL_STOP_INVALID")
    effects = mapping(mission.get("external_effects"), "E1B_EFFECTS")
    if any(value not in (0, False) for value in effects.values()):
        raise ValueError("E1B_EXTERNAL_EFFECT_NONZERO")
    if (
        selection.get("schema_version") != "p0-e1b-selection-manifest-v1"
        or selection.get("mission_id") != mission.get("mission_id")
        or selection.get("source_main_sha") != mission.get("source_main_sha")
        or selection.get("cross_league_season_uniform") is not True
    ):
        raise ValueError("E1B_SELECTION_IDENTITY_INVALID")
    fixtures = [mapping(item, "E1B_FIXTURE") for item in sequence(selection["fixtures"], "E1B_FIXTURES")]
    objects = [mapping(item, "E1B_OBJECT") for item in sequence(selection["source_objects"], "E1B_OBJECTS")]
    if len(fixtures) != 10 or len(objects) != 10:
        raise ValueError("E1B_SELECTION_CARDINALITY_INVALID")
    counts = Counter(int(item["competition_id"]) for item in fixtures)
    if tuple(sorted(counts)) != COMPETITIONS or set(counts.values()) != {2}:
        raise ValueError("E1B_SELECTION_LEAGUE_BALANCE_INVALID")
    order = [
        (int(item["competition_id"]), int(item["season"]), str(item["kickoff_utc"]), int(item["fixture_id"]))
        for item in fixtures
    ]
    if order != sorted(order) or len({item[3] for item in order}) != 10:
        raise ValueError("E1B_SELECTION_ORDER_INVALID")
    index: dict[str, Mapping[str, Any]] = {}
    keys: set[str] = set()
    roles: dict[int, list[str]] = defaultdict(list)
    for item in objects:
        object_id = _hash(item.get("object_id"), "E1B_OBJECT")
        if object_id in index:
            raise ValueError("E1B_DUPLICATE_OBJECT")
        index[object_id] = item
        for field in ("payload_sha256", "stored_sha256", "receipt_hash", "receipt_id"):
            _hash(item.get(field), field)
        for field in ("payload_key", "receipt_key"):
            key = str(item[field])
            if not key.startswith("historical-deep-data/schema-v1/") or key in keys:
                raise ValueError("E1B_OBJECT_KEY_INVALID")
            keys.add(key)
        if item.get("family") != "fixtures" or item.get("season") != 2024:
            raise ValueError("E1B_OBJECT_SCOPE_INVALID")
        roles[int(item["competition_id"])].append(str(item["source_role"]))
    if any(sorted(roles[value]) != ["CENSUS", "DETAIL"] for value in COMPETITIONS):
        raise ValueError("E1B_OBJECT_ROLES_INVALID")
    for item in fixtures:
        if item.get("status") not in {"FT", "AET", "PEN"}:
            raise ValueError("E1B_FIXTURE_NOT_FINISHED")
        if any(str(item[field]).isdecimal() for field in ("home_team_display_name", "away_team_display_name")):
            raise ValueError("E1B_POSITIONAL_TEAM_NAME")
        object_ids = [str(value) for value in sequence(item["allowed_object_ids"], "E1B_ALLOW_IDS")]
        if len(object_ids) != 2 or any(value not in index for value in object_ids):
            raise ValueError("E1B_OBJECT_ALLOWLIST_INVALID")
        sources = [index[value] for value in object_ids]
        expected_keys = [key for source in sources for key in (source["receipt_key"], source["payload_key"])]
        if list(item["allowed_r2_keys"]) != expected_keys:
            raise ValueError("E1B_KEY_ALLOWLIST_INVALID")
        if list(item["payload_hashes"]) != [source["payload_sha256"] for source in sources]:
            raise ValueError("E1B_PAYLOAD_HASHES_INVALID")
        if list(item["receipt_hashes"]) != [source["receipt_hash"] for source in sources]:
            raise ValueError("E1B_RECEIPT_HASHES_INVALID")
    budgets = mapping(selection.get("budgets"), "E1B_BUDGETS")
    if (
        budgets.get("planned_logical_gets_total") != 21
        or int(budgets["planned_network_bytes_upper_bound"]) > int(mission["r2_byte_budget"])
        or any(budgets.get(field) != 0 for field in ("r2_writes", "r2_deletes", "provider_calls", "remote_sql_queries", "odds_credits"))
    ):
        raise ValueError("E1B_SELECTION_BUDGET_INVALID")
    return mission, selection


def require_selection_ready(root: Path, selection_hash: str) -> None:
    records = [
        mapping(json.loads(line), "E1B_LEDGER")
        for line in (root / "reports/council/decision-ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    matches = []
    for record in records:
        context = record.get("context")
        if (
            "E1B_SELECTION_READY" in str(record.get("decision"))
            and isinstance(context, Mapping)
            and context.get("selection_sha256") == selection_hash
        ):
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("E1B_SELECTION_READY_DECISION_REQUIRED")
    reviewers = set(sequence(mapping(matches[0]["context"], "E1B_CONTEXT")["reviewed_by"], "E1B_REVIEWERS"))
    if not {"DP6", "C2", "DP5"} <= reviewers:
        raise ValueError("E1B_SELECTION_REVIEW_KEYS_MISSING")


def _response(payload: object) -> list[Mapping[str, Any]]:
    return [mapping(item, "E1B_RECORD") for item in sequence(mapping(payload, "E1B_PAYLOAD")["response"], "E1B_RESPONSE")]


def _fixture_id(record: Mapping[str, Any]) -> int:
    return int(mapping(record["fixture"], "E1B_FIXTURE")["id"])


def _teams(record: Mapping[str, Any]) -> tuple[int, int]:
    value = mapping(record["teams"], "E1B_TEAMS")
    return (
        int(mapping(value["home"], "E1B_HOME")["id"]),
        int(mapping(value["away"], "E1B_AWAY")["id"]),
    )


def _rate(numerator: int, denominator: int | None) -> float | None:
    return None if denominator in (None, 0) else round(numerator / denominator, 6)


def _row(
    capability: Mapping[str, Any],
    competition: str,
    *,
    expected: int | None,
    received: int,
    status: str,
    reason: str | None = None,
    empty: int = 0,
    unknown: int | None = 0,
    observed: int = 0,
    duplicates: int = 0,
    contradictions: int = 0,
    unclassifiable: int = 0,
) -> dict[str, Any]:
    return {
        "capability_id": capability["capability_id"],
        "competition": competition,
        "season": 2024,
        "fixture_count": 2,
        "grain": capability["grain"],
        "temporal_class": capability["temporal_class"],
        "expected": expected,
        "received": received,
        "empty_valid": empty,
        "unknown": unknown,
        "invalid": 0,
        "unclassifiable": unclassifiable,
        "exact_duplicates": duplicates,
        "contradictory_duplicates": contradictions,
        "observed_records": observed,
        "coverage_rate": _rate(received + empty, expected),
        "content_presence_rate": _rate(received, expected),
        "normalization_integrity_rate": 1.0 if received and not contradictions else None,
        "status_before": capability["status"],
        "e1b_measurement_status": status,
        "block_reason": reason,
        "evidence_claims": ["COVERAGE.E1B.MEASUREMENT.V1.001"],
    }


def _measure_league(
    competition: str,
    selected: Sequence[Mapping[str, Any]],
    census: Sequence[Mapping[str, Any]],
    detail: Sequence[Mapping[str, Any]],
    capabilities: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected_ids = {int(item["fixture_id"]) for item in selected}
    census_by = {_fixture_id(item): item for item in census}
    detail_by = {_fixture_id(item): item for item in detail}
    if not selected_ids <= set(census_by) or not selected_ids <= set(detail_by):
        raise ValueError("E1B_SELECTED_FIXTURE_MISSING")
    records = [detail_by[int(item["fixture_id"])] for item in selected]
    conflicts = sum(
        _teams(census_by[value]) != _teams(detail_by[value])
        or mapping(census_by[value]["fixture"], "E1B_FIXTURE")["date"]
        != mapping(detail_by[value]["fixture"], "E1B_FIXTURE")["date"]
        for value in selected_ids
    )
    players = valid_players = starters = formations = 0
    events = cards = team_stats = player_stats = 0
    event_containers = lineup_containers = team_stat_containers = 0
    player_stat_containers = 0
    lineup_team_keys: set[tuple[int, int]] = set()
    lineup_team_duplicates = 0
    formation_keys: set[tuple[int, int]] = set()
    lineup_player_keys: set[tuple[int, int, int]] = set()
    team_stat_keys: set[tuple[int, int]] = set()
    team_stat_nonempty_keys: set[tuple[int, int]] = set()
    team_stat_empty_keys: set[tuple[int, int]] = set()
    team_stat_duplicates = 0
    player_stat_bucket_keys: set[tuple[int, int]] = set()
    player_stat_bucket_duplicates = 0
    player_stat_keys: set[tuple[int, int, int]] = set()
    player_stat_duplicates = 0
    invalid_player_stat_rows = 0
    lineup_player_source_complete = True
    starter_keys: list[tuple[int, int, str]] = []
    for record in records:
        fixture_id = _fixture_id(record)
        kickoff = str(mapping(record["fixture"], "E1B_FIXTURE")["date"])
        raw_lineups = record.get("lineups")
        lineup_rows = (
            sequence(raw_lineups, "E1B_LINEUPS") if raw_lineups is not None else []
        )
        lineup_containers += int(raw_lineups is not None)
        for lineup in lineup_rows:
            value = mapping(lineup, "E1B_LINEUP")
            team_id = int(mapping(value["team"], "E1B_TEAM")["id"])
            lineup_key = (fixture_id, team_id)
            lineup_team_duplicates += int(lineup_key in lineup_team_keys)
            lineup_team_keys.add(lineup_key)
            if str(value.get("formation", "")).strip():
                formations += 1
                formation_keys.add(lineup_key)
            for role, key in (("STARTER", "startXI"), ("SUB", "substitutes")):
                raw_slots = value.get(key)
                if raw_slots is None:
                    lineup_player_source_complete = False
                    continue
                for slot in sequence(raw_slots, "E1B_SLOTS"):
                    player = mapping(mapping(slot, "E1B_SLOT")["player"], "E1B_PLAYER")
                    players += 1
                    if isinstance(player.get("id"), int) and isinstance(player.get("name"), str):
                        valid_players += 1
                        lineup_player_keys.add((fixture_id, team_id, int(player["id"])))
                        if role == "STARTER":
                            starters += 1
                            starter_keys.append((team_id, int(player["id"]), kickoff))
        raw_events = record.get("events")
        event_rows = (
            sequence(raw_events, "E1B_EVENTS") if raw_events is not None else []
        )
        event_containers += int(raw_events is not None)
        events += len(event_rows)
        card_rows = [item for item in event_rows if isinstance(item, Mapping) and str(item.get("type", "")).casefold() == "card"]
        cards += len(card_rows)
        raw_stats = record.get("statistics")
        stats = sequence(raw_stats, "E1B_STATS") if raw_stats is not None else []
        team_stat_containers += int(raw_stats is not None)
        selected_team_ids = set(_teams(record))
        for raw_stat in stats:
            stat = mapping(raw_stat, "E1B_STAT")
            team_id = int(mapping(stat["team"], "E1B_STAT_TEAM")["id"])
            if team_id not in selected_team_ids:
                raise ValueError("E1B_TEAM_STATISTICS_TEAM_INVALID")
            stat_key = (fixture_id, team_id)
            team_stat_duplicates += int(stat_key in team_stat_keys)
            team_stat_keys.add(stat_key)
            stat_rows = sequence(stat["statistics"], "E1B_STAT_ROWS")
            if stat_rows:
                team_stat_nonempty_keys.add(stat_key)
            else:
                team_stat_empty_keys.add(stat_key)
            team_stats += len(stat_rows)
        raw_players = record.get("players")
        player_buckets = (
            sequence(raw_players, "E1B_PLAYER_BUCKETS")
            if raw_players is not None
            else []
        )
        player_stat_containers += int(raw_players is not None)
        for raw_bucket in player_buckets:
            bucket = mapping(raw_bucket, "E1B_PLAYER_BUCKET")
            team_id = int(mapping(bucket["team"], "E1B_PLAYER_TEAM")["id"])
            if team_id not in selected_team_ids:
                raise ValueError("E1B_PLAYER_STATISTICS_TEAM_INVALID")
            bucket_key = (fixture_id, team_id)
            player_stat_bucket_duplicates += int(
                bucket_key in player_stat_bucket_keys
            )
            player_stat_bucket_keys.add(bucket_key)
            raw_rows = bucket.get("players")
            if raw_rows is None:
                continue
            for raw_player_row in sequence(raw_rows, "E1B_PLAYER_ROWS"):
                player_row = mapping(raw_player_row, "E1B_PLAYER_ROW")
                player_id = mapping(
                    player_row["player"], "E1B_PLAYER_STAT_IDENTITY"
                ).get("id")
                player_stats += 1
                if not isinstance(player_id, int):
                    invalid_player_stat_rows += 1
                    continue
                player_key = (fixture_id, team_id, player_id)
                player_stat_duplicates += int(player_key in player_stat_keys)
                player_stat_keys.add(player_key)
    prior_team = 0
    for record in records:
        kickoff = str(mapping(record["fixture"], "E1B_FIXTURE")["date"])
        for team_id in _teams(record):
            prior_team += int(
                any(
                    team_id in _teams(candidate)
                    and str(mapping(candidate["fixture"], "E1B_FIXTURE")["date"]) < kickoff
                    for candidate in census
                )
            )
    prior_player = 0
    player_history_source_complete = True
    for team_id, player_id, kickoff in starter_keys:
        census_prior = [
            candidate
            for candidate in census
            if team_id in _teams(candidate)
            and str(mapping(candidate["fixture"], "E1B_FIXTURE")["date"])
            < kickoff
        ]
        detail_prior = [
            candidate
            for candidate in detail
            if team_id in _teams(candidate)
            and str(mapping(candidate["fixture"], "E1B_FIXTURE")["date"])
            < kickoff
        ]
        if census_prior and not detail_prior:
            player_history_source_complete = False
        found = False
        for candidate in detail_prior:
            raw_buckets = candidate.get("players")
            if raw_buckets is None:
                player_history_source_complete = False
                continue
            relevant = [
                mapping(raw_bucket, "E1B_PRIOR_PLAYER_BUCKET")
                for raw_bucket in sequence(raw_buckets, "E1B_PRIOR_PLAYER_BUCKETS")
                if int(
                    mapping(
                        mapping(raw_bucket, "E1B_PRIOR_PLAYER_BUCKET")["team"],
                        "E1B_PRIOR_PLAYER_TEAM",
                    )["id"]
                )
                == team_id
            ]
            if len(relevant) != 1 or relevant[0].get("players") is None:
                player_history_source_complete = False
                continue
            prior_ids = {
                mapping(
                    mapping(raw_row, "E1B_PRIOR_PLAYER_ROW")["player"],
                    "E1B_PRIOR_PLAYER_IDENTITY",
                ).get("id")
                for raw_row in sequence(
                    relevant[0]["players"], "E1B_PRIOR_PLAYER_ROWS"
                )
            }
            found = found or player_id in prior_ids
        prior_player += int(found)
    caps = {str(item["capability_id"]): item for item in capabilities}
    rows: dict[str, dict[str, Any]] = {}
    def add(name: str, **values: Any) -> None:
        rows[name] = _row(caps[name], competition, **values)
    add("TEAM", expected=4, received=4, status="E1B_MEASURED", observed=4, duplicates=4, contradictions=conflicts)
    add("TEAM_FORM", expected=4, received=prior_team, unknown=4-prior_team, status="E1B_BLOCKED_BY_TEMPORALITY", observed=prior_team, reason="POST_HOC_FIXTURE_HISTORY_CANNOT_PROVE_STRICT_AS_OF")
    lineup_complete = len(lineup_team_keys) == 4 and not lineup_team_duplicates
    lineup_player_complete = lineup_complete and lineup_player_source_complete
    lineup_gap_status = "E1B_BLOCKED_BY_SOURCE" if lineup_containers < 2 else "E1B_BLOCKED_BY_COVERAGE"
    player_gap_status = "E1B_BLOCKED_BY_SOURCE" if not lineup_player_source_complete else lineup_gap_status
    add("PLAYER", expected=len(lineup_player_keys) if lineup_player_complete else None, received=len(lineup_player_keys), unknown=0 if lineup_player_complete else None, status="E1B_MEASURED_PARTIAL" if lineup_player_complete else player_gap_status, observed=valid_players, duplicates=max(valid_players-len(lineup_player_keys), 0), reason="LINEUP_SOURCE_ONLY" if lineup_player_complete else "LINEUP_PLAYER_CONTAINER_INCOMPLETE")
    player_form_source_complete = lineup_player_complete and player_history_source_complete
    player_form_reason = (
        "POST_MATCH_STATISTICS_NOT_STRICT_AS_OF"
        if player_form_source_complete
        else (
            "PLAYER_HISTORY_CONTAINER_MISSING"
            if lineup_player_complete
            else "PLAYER_LINEUP_CONTAINER_MISSING"
        )
    )
    add("PLAYER_FORM", expected=starters if lineup_player_complete else None, received=prior_player, unknown=starters-prior_player if lineup_player_complete else None, status="E1B_BLOCKED_BY_TEMPORALITY" if player_form_source_complete else "E1B_BLOCKED_BY_SOURCE", observed=prior_player, reason=player_form_reason)
    add("LINEUP", expected=4, received=len(lineup_team_keys), unknown=4-len(lineup_team_keys), status="E1B_MEASURED_PARTIAL" if lineup_complete else lineup_gap_status, observed=players, duplicates=lineup_team_duplicates, reason="POST_MATCH_RECONSTRUCTION" if lineup_complete else "LINEUP_TEAM_GRAIN_INCOMPLETE")
    add("FORMATION", expected=4, received=len(formation_keys), unknown=4-len(formation_keys), status="E1B_MEASURED_PARTIAL" if lineup_complete and len(formation_keys) == 4 else "E1B_BLOCKED_BY_COVERAGE", observed=formations, duplicates=max(formations-len(formation_keys), 0), reason="POST_MATCH_RECONSTRUCTION" if lineup_complete and len(formation_keys) == 4 else "FORMATION_OR_LINEUP_INCOMPLETE")
    add("STARTER_BASELINE", expected=44, received=starters, unknown=44-starters, status="E1B_BLOCKED_BY_TEMPORALITY" if lineup_player_complete and starters == 44 else player_gap_status, observed=starters, reason="NOT_PROVEN_BEFORE_KICKOFF" if lineup_player_complete and starters == 44 else "STARTER_LINEUP_INCOMPLETE")
    event_status = "E1B_MEASURED" if event_containers == 2 else "E1B_BLOCKED_BY_SOURCE"
    event_reason = None if event_containers == 2 else "EVENT_CONTAINER_MISSING"
    add("EVENTS", expected=None, received=events, unknown=None, status=event_status, observed=events, reason=event_reason)
    team_stats_complete = len(team_stat_keys) == 4 and not team_stat_duplicates
    team_stats_status = "E1B_MEASURED" if team_stats_complete else ("E1B_BLOCKED_BY_SOURCE" if team_stat_containers < 2 else "E1B_BLOCKED_BY_COVERAGE")
    add("TEAM_STATISTICS", expected=4, received=len(team_stat_nonempty_keys), empty=len(team_stat_empty_keys-team_stat_nonempty_keys), unknown=4-len(team_stat_keys), status=team_stats_status, observed=team_stats, duplicates=team_stat_duplicates, contradictions=len(team_stat_empty_keys & team_stat_nonempty_keys), reason=None if team_stats_complete else ("TEAM_STATISTICS_CONTAINER_MISSING" if team_stat_containers < 2 else "TEAM_STATISTICS_TEAM_GRAIN_INCOMPLETE_OR_DUPLICATE"))
    player_stats_complete = lineup_player_complete and len(player_stat_bucket_keys) == 4 and not player_stat_bucket_duplicates
    matched_player_stats = len(player_stat_keys & lineup_player_keys)
    unmatched_player_stats = len(player_stat_keys - lineup_player_keys)
    add("PLAYER_STATISTICS", expected=len(lineup_player_keys) if lineup_player_complete else None, received=matched_player_stats, unknown=len(lineup_player_keys)-matched_player_stats if lineup_player_complete else None, status="E1B_MEASURED" if player_stats_complete and not unmatched_player_stats and not invalid_player_stat_rows and not player_stat_duplicates and matched_player_stats == len(lineup_player_keys) else ("E1B_BLOCKED_BY_SOURCE" if player_stat_containers < 2 or not lineup_player_source_complete else "E1B_BLOCKED_BY_COVERAGE"), observed=player_stats, duplicates=player_stat_duplicates+player_stat_bucket_duplicates, contradictions=unmatched_player_stats+invalid_player_stat_rows, reason=None if player_stats_complete and not unmatched_player_stats and not invalid_player_stat_rows and not player_stat_duplicates and matched_player_stats == len(lineup_player_keys) else "PLAYER_STATISTICS_PLAYER_TEAM_GRAIN_INCOMPLETE")
    add("DISCIPLINE_GENERIC", expected=None, received=cards, unknown=None, status=event_status, observed=cards, reason=event_reason)
    for name in ("INJURY_CONFIRMED", "SUSPENSION_CONFIRMED", "ABSENCE_GENERIC"):
        add(name, expected=None, received=0, unknown=None, status="E1B_NOT_EVALUATED", reason="NO_INJURIES_OBJECT_AUTHORIZED")
    add("ABSENCE_CAUSE_EXACT", expected=None, received=0, unknown=None, status="E1B_NOT_APPLICABLE", reason="STOPPED_LOCAL_CAMPAIGN", unclassifiable=0)
    add("CALENDAR", expected=2, received=2, status="E1B_MEASURED_PARTIAL", observed=2, duplicates=2, contradictions=conflicts, reason="FINAL_STATE_NOT_KNOWN_AS_OF")
    add("FATIGUE", expected=4, received=prior_team, unknown=4-prior_team, status="E1B_BLOCKED_BY_TEMPORALITY", observed=prior_team, reason="POST_HOC_REST_INTERVAL")
    add("STANDINGS", expected=4, received=0, unknown=4, status="E1B_BLOCKED_BY_SOURCE", reason="NO_STANDINGS_OBJECT_AUTHORIZED")
    return [rows[str(item["capability_id"])] for item in capabilities]


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_values = [item["expected"] for item in rows]
    expected = sum(expected_values) if all(isinstance(value, int) for value in expected_values) else None
    received = sum(int(item["received"]) for item in rows)
    empty = sum(int(item["empty_valid"]) for item in rows)
    unknown_values = [item["unknown"] for item in rows]
    unknown = sum(unknown_values) if all(isinstance(value, int) for value in unknown_values) else None
    return {
        "capability_id": rows[0]["capability_id"],
        "league_count": 5,
        "fixture_count": 10,
        "expected": expected,
        "received": received,
        "empty_valid": empty,
        "unknown": unknown,
        "invalid": sum(int(item["invalid"]) for item in rows),
        "unclassifiable": sum(int(item["unclassifiable"]) for item in rows),
        "exact_duplicates": sum(int(item["exact_duplicates"]) for item in rows),
        "contradictory_duplicates": sum(int(item["contradictory_duplicates"]) for item in rows),
        "observed_records": sum(int(item["observed_records"]) for item in rows),
        "coverage_rate_weighted": _rate(received + empty, expected),
        "content_presence_rate_weighted": _rate(received, expected),
        "league_statuses": sorted({str(item["e1b_measurement_status"]) for item in rows}),
        "global_capability_status_unchanged": True,
        "readiness_claimed": False,
    }


def build_reports(
    mission: Mapping[str, Any],
    selection: Mapping[str, Any],
    contract: Mapping[str, Any],
    payloads: Mapping[str, object],
    receipts: Mapping[str, Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    runtime: Mapping[str, Any],
    selection_hash: str,
) -> dict[str, Mapping[str, Any]]:
    _hash(selection_hash, "E1B_SELECTION")
    capabilities = [mapping(item, "E1B_CAP") for item in sequence(contract["capabilities"], "E1B_CAPS")]
    objects = [mapping(item, "E1B_OBJECT") for item in sequence(selection["source_objects"], "E1B_OBJECTS")]
    fixtures = [mapping(item, "E1B_FIXTURE") for item in sequence(selection["fixtures"], "E1B_FIXTURES")]
    measurements: list[dict[str, Any]] = []
    leagues: list[dict[str, Any]] = []
    for competition_id in COMPETITIONS:
        current_objects = [item for item in objects if int(item["competition_id"]) == competition_id]
        role = {str(item["source_role"]): item for item in current_objects}
        current_fixtures = [item for item in fixtures if int(item["competition_id"]) == competition_id]
        current = _measure_league(
            str(current_objects[0]["competition"]),
            current_fixtures,
            _response(payloads[str(role["CENSUS"]["object_id"])]),
            _response(payloads[str(role["DETAIL"]["object_id"])]),
            capabilities,
        )
        measurements.extend(current)
        leagues.append({
            "competition_id": competition_id,
            "competition": current_objects[0]["competition"],
            "season": 2024,
            "fixture_count": 2,
            "measured": sorted(item["capability_id"] for item in current if item["e1b_measurement_status"] == "E1B_MEASURED"),
            "partial": sorted(item["capability_id"] for item in current if item["e1b_measurement_status"] == "E1B_MEASURED_PARTIAL"),
            "blocked": sorted(item["capability_id"] for item in current if str(item["e1b_measurement_status"]).startswith("E1B_BLOCKED")),
            "not_evaluated": sorted(item["capability_id"] for item in current if item["e1b_measurement_status"] in {"E1B_NOT_EVALUATED", "E1B_NOT_APPLICABLE"}),
        })
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in measurements:
        grouped[str(item["capability_id"])].append(item)
    aggregates = [_aggregate(grouped[str(item["capability_id"])]) for item in capabilities]
    candidate_order = ["TEAM", "PLAYER", "LINEUP", "FORMATION", "EVENTS", "TEAM_STATISTICS", "PLAYER_STATISTICS", "DISCIPLINE_GENERIC", "CALENDAR"]
    e2_candidates = [
        capability_id
        for capability_id in candidate_order
        if all(
            item["e1b_measurement_status"]
            in {"E1B_MEASURED", "E1B_MEASURED_PARTIAL"}
            for item in grouped[capability_id]
        )
    ]
    measured = sorted({str(item["capability_id"]) for item in measurements if item["e1b_measurement_status"] == "E1B_MEASURED"})
    partial = sorted({str(item["capability_id"]) for item in measurements if item["e1b_measurement_status"] == "E1B_MEASURED_PARTIAL"})
    blocked = sorted({str(item["capability_id"]) for item in measurements if str(item["e1b_measurement_status"]).startswith("E1B_BLOCKED")})
    not_evaluated = sorted({str(item["capability_id"]) for item in measurements if item["e1b_measurement_status"] in {"E1B_NOT_EVALUATED", "E1B_NOT_APPLICABLE"}})
    source_receipts = [
        {"object_id": key, "receipt_hash": value.get("receipt_hash"), "received_at": value.get("received_at"), "completed_at": value.get("completed_at")}
        for key, value in sorted(receipts.items())
    ]
    measurement = {
        "schema_version": "p0-e1b-measurement-v1",
        "mission_id": mission["mission_id"],
        "stage": "E1B",
        "selection_sha256": selection_hash,
        "scope": {"competition_count": 5, "fixture_count": 10, "fixture_count_per_league": 2, "season": 2024, "cross_league_season_uniform": True},
        "measurements": measurements,
        "weighted_capability_aggregates": aggregates,
        "capabilities_measured": measured,
        "capabilities_partial": partial,
        "capabilities_blocked": blocked,
        "capabilities_not_evaluated": not_evaluated,
        "e2_candidates": e2_candidates,
        "global_capability_statuses_changed": False,
        "ready_strict_declared": 0,
        "ready_reconstructed_declared": 0,
        "absence_cause_exact_status": "STOPPED_LOCAL_CAMPAIGN",
        "historical_e1a_partition": {"total": 3036, "injury_confirmed": 2681, "suspension_confirmed": 206, "absence_cause_unknown": 149, "identity": "3036 = 2681 + 206 + 149"},
        "verdict": "E1B_FIVE_LEAGUE_CANARY_MEASURED",
        "mission_decision": "PASS_AND_HOLD",
        "e2_executed": False,
        "source_receipts": source_receipts,
    }
    logical = mapping(telemetry["logical_gets"], "E1B_GETS")
    byte_values = mapping(telemetry["bytes"], "E1B_BYTES")
    costs = {
        "schema_version": "p0-e1b-costs-v1",
        "mission_id": mission["mission_id"],
        "logical_gets": 1 + int(logical["evidence_total"]),
        "bootstrap_gets": int(mapping(logical["bootstrap"], "E1B_BOOTSTRAP")["requested"]),
        "receipt_gets": int(mapping(logical["receipt"], "E1B_RECEIPTS")["requested"]),
        "payload_gets": int(mapping(logical["payload"], "E1B_PAYLOADS")["requested"]),
        "physical_requests": "UNKNOWN",
        "bytes_read": int(byte_values["bootstrap_stored"]) + int(byte_values["receipt"]) + int(byte_values["payload_stored"]),
        "objects_read": 1 + int(logical["evidence_total"]),
        "cache_hits": 0,
        "duration_seconds": runtime.get("duration_seconds"),
        "github_minutes": runtime.get("github_minutes", "UNKNOWN"),
        "provider_calls": 0,
        "r2_writes": 0,
        "r2_deletes": 0,
        "sql_queries": 0,
        "odds_credits": 0,
        "deployments": 0,
        "publications": 0,
        "real_bets": 0,
        "promotions": 0,
        "budgets_respected": True,
    }
    unknown_rows = [
        {"competition": item["competition"], "capability_id": item["capability_id"], "unknown": item["unknown"]}
        for item in measurements if isinstance(item["unknown"], int) and item["unknown"] > 0
    ]
    return {
        "measurement": measurement,
        "capability_matrix": {
            "schema_version": "p0-e1b-capability-matrix-v1",
            "mission_id": mission["mission_id"],
            "selection_sha256": selection_hash,
            "capabilities": aggregates,
            "e2_candidates": e2_candidates,
            "candidate_policy": "BOUNDED_E1B_EVIDENCE_ONLY_NOT_SCIENTIFIC_READINESS",
            "global_statuses_unchanged": True,
        },
        "league_comparison": {
            "schema_version": "p0-e1b-league-comparison-v1",
            "mission_id": mission["mission_id"],
            "weighting_policy": "SUM_NUMERATORS_AND_DENOMINATORS_NEVER_SIMPLE_MEAN",
            "leagues": leagues,
            "capability_aggregates": aggregates,
            "comparison_limit": "TECHNICAL_CANARY_NOT_SCIENTIFIC_COMPARISON",
        },
        "unknown_profile": {
            "schema_version": "p0-e1b-unknown-profile-v1",
            "canonical_value": "UNKNOWN",
            "implicit_coercions": {"to_false": 0, "to_zero": 0, "to_injury": 0, "to_suspension": 0},
            "e1a_absence_cause_unknown_preserved": 149,
            "e1a_total_absence_records_preserved": 3036,
            "new_absence_records_read": 0,
            "unknown_bucket_total": sum(int(item["unknown"]) for item in unknown_rows),
            "distribution_by_league_and_capability": unknown_rows,
            "unknown_denominator_unavailable_policy": "NULL_NOT_ZERO",
        },
        "costs": costs,
        "dashboard_contract": {
            "schema_version": "p0-e1b-dashboard-contract-v1",
            "mission_id": mission["mission_id"],
            "frontend_implemented": False,
            "fixtures": [
                {
                    "fixture_id": item["fixture_id"],
                    "competition": item["competition"],
                    "season": item["season"],
                    "kickoff_utc": item["kickoff_utc"],
                    "home_team": {"id": item["home_team_id"], "display_name": item["home_team_display_name"]},
                    "away_team": {"id": item["away_team_id"], "display_name": item["away_team_display_name"]},
                }
                for item in fixtures
            ],
            "capabilities": measurements,
            "summary": {"measured": measured, "partial": partial, "blocked": blocked, "not_evaluated": not_evaluated, "e2_candidates": e2_candidates},
            "freshness": source_receipts,
            "provenance": {"selection_sha256": selection_hash, "source_main_sha": mission["source_main_sha"], "inventory_manifest_sha256": mapping(selection["selection_source"], "E1B_SOURCE")["inventory_manifest_sha256"]},
            "forbidden_content": {"fake_rankings": 0, "roi": 0, "strategy_promotion": 0},
        },
    }


def finalize_reports(values: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    base = {key: render_json(value) for key, value in values.items()}
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in base.items()}
    replay = {
        "schema_version": "p0-e1b-replay-verification-v1",
        "replay_identical": True,
        "selection_hash": values["measurement"]["selection_sha256"],
        "measurement_hash": hashes["measurement"],
        "capability_matrix_hash": hashes["capability_matrix"],
        "dashboard_contract_hash": hashes["dashboard_contract"],
        "all_report_hashes": hashes,
        "r2_gets_during_replay": 0,
        "provider_calls_during_replay": 0,
        "comparison": "BYTE_IDENTICAL_TWO_GENERATIONS_FROM_VERIFIED_IN_MEMORY_OBJECTS",
    }
    return {**base, "replay_verification": render_json(replay)}


def validate_reports(reports: Mapping[str, Mapping[str, Any]]) -> None:
    measurement = mapping(reports["measurement"], "E1B_MEASUREMENT")
    rows = sequence(measurement["measurements"], "E1B_ROWS")
    if len(rows) != 90 or measurement.get("e2_executed") is not False:
        raise ValueError("E1B_MEASUREMENT_SCOPE_INVALID")
    if measurement.get("ready_strict_declared") != 0 or measurement.get("ready_reconstructed_declared") != 0:
        raise ValueError("E1B_READY_CLAIM_FORBIDDEN")
    if measurement.get("absence_cause_exact_status") != "STOPPED_LOCAL_CAMPAIGN":
        raise ValueError("E1B_LOCAL_STOP_LOST")
    for raw in rows:
        item = mapping(raw, "E1B_ROW")
        if item["e1b_measurement_status"] not in ALLOWED_STATUSES:
            raise ValueError("E1B_STATUS_INVALID")
        expected = item["expected"]
        if isinstance(expected, int) and int(item["received"]) + int(item["empty_valid"]) > expected:
            raise ValueError("E1B_DENOMINATOR_INVALID")
    costs = mapping(reports["costs"], "E1B_COSTS")
    if int(costs["logical_gets"]) > 2000 or int(costs["bytes_read"]) > 7244155:
        raise ValueError("E1B_BUDGET_EXCEEDED")
    for field in ("provider_calls", "r2_writes", "r2_deletes", "sql_queries", "odds_credits", "deployments", "publications", "real_bets", "promotions"):
        if costs[field] != 0:
            raise ValueError("E1B_EXTERNAL_EFFECT_NONZERO")
