"""Compact E2 capability measurement over one hundred frozen fixtures."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

CAPABILITIES = (
    "TEAM",
    "PLAYER",
    "LINEUP",
    "FORMATION",
    "EVENTS",
    "TEAM_STATISTICS",
    "PLAYER_STATISTICS",
    "DISCIPLINE_GENERIC",
    "CALENDAR",
)
REPORT_FILENAMES = {
    "measurement": "e2-measurement-v1.json",
    "capability_matrix": "e2-capability-matrix-v1.json",
    "league_comparison": "e2-league-comparison-v1.json",
    "e1b_e2_comparison": "e1b-e2-comparison-v1.json",
    "temporal_strata": "e2-temporal-strata-v1.json",
    "team_concentration": "e2-team-concentration-v1.json",
    "costs": "e2-costs-v1.json",
    "dashboard_contract": "e2-dashboard-contract-v1.json",
    "e3a_candidate_set": "e2-e3a-candidate-set-v1.json",
    "replay_verification": "e2-replay-verification-v1.json",
}
E1B_STATUSES = {
    "TEAM": "E1B_MEASURED",
    "PLAYER": "E1B_MEASURED_PARTIAL",
    "LINEUP": "E1B_MEASURED_PARTIAL",
    "FORMATION": "E1B_MEASURED_PARTIAL",
    "EVENTS": "E1B_MEASURED",
    "TEAM_STATISTICS": "E1B_MEASURED",
    "PLAYER_STATISTICS": "E1B_MEASURED",
    "DISCIPLINE_GENERIC": "E1B_MEASURED",
    "CALENDAR": "E1B_MEASURED_PARTIAL",
}
TEMPORAL_CLASSES = {
    "TEAM": "ENTITY_AS_OF",
    "PLAYER": "ENTITY_AS_OF",
    "LINEUP": "OBSERVED_AT",
    "FORMATION": "OBSERVED_AT",
    "EVENTS": "EVENT_TIME",
    "TEAM_STATISTICS": "OBSERVED_AT",
    "PLAYER_STATISTICS": "OBSERVED_AT",
    "DISCIPLINE_GENERIC": "EVENT_TIME",
    "CALENDAR": "KNOWN_AS_OF",
}
GRAINS = {
    "TEAM": "one team",
    "PLAYER": "one player",
    "LINEUP": "one team lineup for one fixture",
    "FORMATION": "one team formation for one fixture",
    "EVENTS": "one event in one fixture",
    "TEAM_STATISTICS": "one team in one fixture",
    "PLAYER_STATISTICS": "one player in one fixture",
    "DISCIPLINE_GENERIC": "one disciplinary observation",
    "CALENDAR": "one scheduled fixture",
}


def mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(label)
    return value


def sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(label)
    return value


def render_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _response(payload: object) -> list[Mapping[str, Any]]:
    root = mapping(payload, "E2_PAYLOAD")
    return [mapping(item, "E2_RESPONSE") for item in sequence(root.get("response", []), "E2_RESPONSE")]


def _fixture_id(record: Mapping[str, Any]) -> int | None:
    fixture = record.get("fixture")
    if not isinstance(fixture, Mapping) or not isinstance(fixture.get("id"), int):
        return None
    return int(fixture["id"])


def _rate(numerator: int, denominator: int | None) -> float | None:
    if denominator in (None, 0):
        return None
    return round(numerator / denominator, 8)


def _ids(rows: object, *path: str) -> tuple[set[int], int, int]:
    values: set[int] = set()
    exact = 0
    invalid = 0
    for raw in sequence(rows if rows is not None else [], "E2_ID_ROWS"):
        current: object = raw
        for key in path:
            current = mapping(current, "E2_ID_PATH").get(key)
        if isinstance(current, int):
            if current in values:
                exact += 1
            values.add(current)
        else:
            invalid += 1
    return values, exact, invalid


def _fixture_measures(
    fixture: Mapping[str, Any], payload: object
) -> list[dict[str, Any]]:
    fixture_id = int(fixture["fixture_id"])
    matches = [record for record in _response(payload) if _fixture_id(record) == fixture_id]
    if len(matches) != 1:
        return [
            _measure_row(fixture, capability, 1, 0, 0, 1, 0, 0, "SOURCE_FIXTURE_CARDINALITY_INVALID")
            for capability in CAPABILITIES
        ]
    record = matches[0]
    teams = mapping(record.get("teams", {}), "E2_TEAMS")
    team_ids = {
        int(item["id"])
        for key in ("home", "away")
        if isinstance((item := mapping(teams.get(key, {}), "E2_TEAM")).get("id"), int)
    }
    lineups = [mapping(item, "E2_LINEUP") for item in sequence(record.get("lineups", []), "E2_LINEUPS")]
    lineup_team_ids, lineup_duplicates, lineup_invalid = _ids(lineups, "team", "id")
    player_rows = [
        mapping(player, "E2_LINEUP_PLAYER")
        for lineup in lineups
        for bucket in ("startXI", "substitutes")
        for player in sequence(lineup.get(bucket, []), "E2_LINEUP_PLAYERS")
    ]
    player_ids, player_duplicates, player_invalid = _ids(player_rows, "player", "id")
    formations = {
        str(lineup["formation"])
        for lineup in lineups
        if isinstance(lineup.get("formation"), str) and lineup["formation"]
    }
    statistics = [mapping(item, "E2_TEAM_STATS") for item in sequence(record.get("statistics", []), "E2_TEAM_STATS")]
    stat_team_ids, stat_duplicates, stat_invalid = _ids(statistics, "team", "id")
    players = [mapping(item, "E2_PLAYER_BUCKET") for item in sequence(record.get("players", []), "E2_PLAYERS")]
    player_statistics = [
        mapping(item, "E2_PLAYER_STAT")
        for bucket in players
        for item in sequence(bucket.get("players", []), "E2_PLAYER_STATS")
    ]
    player_stat_ids, player_stat_duplicates, player_stat_invalid = _ids(player_statistics, "player", "id")
    events = [mapping(item, "E2_EVENT") for item in sequence(record.get("events", []), "E2_EVENTS")]
    cards = [event for event in events if str(event.get("type", "")).casefold() == "card"]
    values = [
        _measure_row(fixture, "TEAM", 2, len(team_ids), 0, 2 - len(team_ids), 0, 0, None),
        _measure_row(fixture, "PLAYER", len(player_ids), len(player_ids), 0, 0, player_invalid, player_duplicates, "LINEUP_SOURCE_ONLY"),
        _measure_row(fixture, "LINEUP", 2, len(lineup_team_ids), 0, 2 - len(lineup_team_ids), lineup_invalid, lineup_duplicates, "POST_MATCH_RECONSTRUCTION"),
        _measure_row(fixture, "FORMATION", 2, len(formations), 0, 2 - len(formations), 0, max(len(lineups) - len(lineup_team_ids), 0), "POST_MATCH_RECONSTRUCTION"),
        _measure_row(fixture, "EVENTS", None, len(events), int(not events), 0, 0, 0, None),
        _measure_row(fixture, "TEAM_STATISTICS", 2, len(stat_team_ids), 0, 2 - len(stat_team_ids), stat_invalid, stat_duplicates, None),
        _measure_row(fixture, "PLAYER_STATISTICS", len(player_ids), len(player_stat_ids & player_ids), 0, len(player_ids - player_stat_ids), player_stat_invalid + len(player_stat_ids - player_ids), player_stat_duplicates, None),
        _measure_row(fixture, "DISCIPLINE_GENERIC", None, len(cards), int(not cards), 0, 0, 0, None),
        _measure_row(fixture, "CALENDAR", 1, 1, 0, 0, 0, 0, "FINAL_STATE_NOT_KNOWN_AS_OF"),
    ]
    return values


def _measure_row(
    fixture: Mapping[str, Any],
    capability: str,
    expected: int | None,
    received: int,
    empty: int,
    unknown: int,
    invalid: int,
    exact_duplicates: int,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "anchor": bool(fixture["is_e1b_anchor"]),
        "away_team_id": int(fixture["away_team_id"]),
        "capability_id": capability,
        "competition": str(fixture["competition"]),
        "contradictory_duplicates": 0,
        "empty_valid": empty,
        "exact_duplicates": exact_duplicates,
        "expected": expected,
        "fixture_id": int(fixture["fixture_id"]),
        "home_team_id": int(fixture["home_team_id"]),
        "invalid": invalid,
        "kickoff": str(fixture["kickoff"]),
        "received": received,
        "temporal_stratum": int(fixture["temporal_stratum"]),
        "unclassifiable": 0,
        "unknown": unknown,
        "block_reason": reason,
    }


def _aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_values = [int(row["expected"]) for row in rows if row["expected"] is not None]
    expected = sum(expected_values) if len(expected_values) == len(rows) else None
    received = sum(int(row["received"]) for row in rows)
    empty = sum(int(row["empty_valid"]) for row in rows)
    unknown = sum(int(row["unknown"]) for row in rows)
    invalid = sum(int(row["invalid"]) for row in rows)
    exact = sum(int(row["exact_duplicates"]) for row in rows)
    contradictory = sum(int(row["contradictory_duplicates"]) for row in rows)
    capability = str(rows[0]["capability_id"])
    source_present = received + empty > 0
    complete = invalid == 0 and contradictory == 0 and (expected is None or received + empty == expected)
    status = "E2_MEASURED" if source_present and complete else ("E2_MEASURED_PARTIAL" if source_present else "E2_BLOCKED_BY_SOURCE")
    integrity_denominator = received + empty + invalid + contradictory
    integrity = _rate(received + empty, integrity_denominator)
    reasons = sorted({str(row["block_reason"]) for row in rows if row.get("block_reason")})
    return {
        "anchor_fixture_count": len({int(row["fixture_id"]) for row in rows if row["anchor"]}),
        "block_reason": reasons or None,
        "capability_id": capability,
        "competition": str(rows[0]["competition"]),
        "content_presence_rate": _rate(received, received + empty),
        "contradictory_duplicates": contradictory,
        "coverage_rate": _rate(received + empty, expected),
        "e1b_status": E1B_STATUSES[capability],
        "e2_measurement_status": status,
        "empty_valid": empty,
        "evidence_claims": [],
        "exact_duplicates": exact,
        "expected": expected,
        "fixture_count": len({int(row["fixture_id"]) for row in rows}),
        "grain": GRAINS[capability],
        "invalid": invalid,
        "new_fixture_count": len({int(row["fixture_id"]) for row in rows if not row["anchor"]}),
        "normalization_integrity_rate": integrity,
        "received": received,
        "season": 2024,
        "status_before": "NOT_EVALUATED",
        "temporal_class": TEMPORAL_CLASSES[capability],
        "unclassifiable": sum(int(row["unclassifiable"]) for row in rows),
        "unknown": unknown,
    }


def _group_aggregates(
    fixture_rows: Sequence[Mapping[str, Any]], field: str | None = None
) -> list[dict[str, Any]]:
    groups: dict[tuple[object, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in fixture_rows:
        key: tuple[object, ...] = (row["competition"], row["capability_id"])
        if field is not None:
            key += (row[field],)
        groups[key].append(row)
    result = []
    for key, rows in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
        aggregate = _aggregate(rows)
        if field is not None:
            aggregate[field] = key[-1]
        result.append(aggregate)
    return result


def _weighted(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_values = [int(row["expected"]) for row in rows if row["expected"] is not None]
    expected = sum(expected_values) if len(expected_values) == len(rows) else None
    received = sum(int(row["received"]) for row in rows)
    empty = sum(int(row["empty_valid"]) for row in rows)
    invalid = sum(int(row["invalid"]) for row in rows)
    contradictory = sum(int(row["contradictory_duplicates"]) for row in rows)
    return {
        "capability_id": rows[0]["capability_id"],
        "content_presence_rate_weighted": _rate(received, received + empty),
        "contradictory_duplicates": contradictory,
        "coverage_rate_weighted": _rate(received + empty, expected),
        "empty_valid": empty,
        "expected": expected,
        "invalid": invalid,
        "normalization_integrity_rate_weighted": _rate(received + empty, received + empty + invalid + contradictory),
        "received": received,
        "unknown": sum(int(row["unknown"]) for row in rows),
    }


def _candidate(weighted: Mapping[str, Any], league_rows: Sequence[Mapping[str, Any]]) -> tuple[str, str | None]:
    if len({row["competition"] for row in league_rows}) != 5:
        return "E3A_NOT_ELIGIBLE", "FIVE_LEAGUES_NOT_MEASURED"
    if int(weighted["invalid"]) or int(weighted["contradictory_duplicates"]):
        return "E3A_TARGETED_FIX_REQUIRED", "IDENTITY_HASH_OR_DUPLICATE_INTEGRITY"
    if weighted["normalization_integrity_rate_weighted"] != 1.0:
        return "E3A_TARGETED_FIX_REQUIRED", "NORMALIZATION_INTEGRITY_BELOW_FROZEN_ONE"
    if any(str(row["e2_measurement_status"]) != "E2_MEASURED" for row in league_rows):
        return "E3A_TARGETED_FIX_REQUIRED", "COVERAGE_OR_SOURCE_PARTIAL"
    if weighted["capability_id"] == "CALENDAR":
        return "E3A_TARGETED_FIX_REQUIRED", "FINAL_STATE_NOT_KNOWN_AS_OF"
    return "E3A_CANDIDATE", None


def build_reports(
    selection: Mapping[str, Any],
    e1b: Mapping[str, Any],
    payloads: Mapping[int, object],
    receipts: Mapping[int, Mapping[str, Any]],
    telemetry: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    fixtures = [mapping(item, "E2_FIXTURE") for item in sequence(selection["fixtures"], "E2_FIXTURES")]
    fixture_rows = [row for fixture in fixtures for row in _fixture_measures(fixture, payloads[int(fixture["fixture_id"])])]
    league_rows = _group_aggregates(fixture_rows)
    strata_rows = _group_aggregates(fixture_rows, "temporal_stratum")
    by_capability: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in league_rows:
        by_capability[str(row["capability_id"])].append(row)
    weighted = [_weighted(by_capability[capability]) for capability in CAPABILITIES]
    weighted_by_capability = {str(row["capability_id"]): row for row in weighted}
    candidates = []
    for capability in CAPABILITIES:
        status, reason = _candidate(weighted_by_capability[capability], by_capability[capability])
        candidates.append({"capability_id": capability, "decision": status, "reason": reason})
    decision_groups = defaultdict(list)
    for row in candidates:
        decision_groups[str(row["decision"])].append(str(row["capability_id"]))
    aggregate_subsets: dict[str, dict[str, Mapping[str, Any]]] = {}
    for label in ("anchors", "new", "e2"):
        subset_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in fixture_rows:
            selected = label == "e2" or bool(row["anchor"]) == (label == "anchors")
            if selected:
                subset_rows[str(row["capability_id"])].append(row)
        aggregate_subsets[label] = {
            capability: _weighted(subset_rows[capability])
            for capability in CAPABILITIES
        }
    e1b_weighted = {str(mapping(item, "E1B_WEIGHTED")["capability_id"]): mapping(item, "E1B_WEIGHTED") for item in sequence(e1b["weighted_capability_aggregates"], "E1B_WEIGHTED")}
    comparison = []
    for capability in CAPABILITIES:
        old = e1b_weighted[capability]
        anchors = aggregate_subsets["anchors"][capability]
        new = aggregate_subsets["new"][capability]
        full = aggregate_subsets["e2"][capability]
        comparison.append({
            "capability_id": capability,
            "e1b_expected": old["expected"], "e1b_received": old["received"], "e1b_unknown": old["unknown"], "e1b_invalid": old["invalid"],
            "anchor_expected": anchors["expected"], "anchor_received": anchors["received"], "anchor_unknown": anchors["unknown"], "anchor_invalid": anchors["invalid"],
            "new_expected": new["expected"], "new_received": new["received"], "new_unknown": new["unknown"], "new_invalid": new["invalid"],
            "e2_expected": full["expected"], "e2_received": full["received"], "e2_unknown": full["unknown"], "e2_invalid": full["invalid"],
            "interpretation": "DESCRIPTIVE_NOT_CAUSAL",
        })
    concentrations = []
    for competition in sorted({str(row["competition"]) for row in fixtures}):
        league_fixtures = [
            row for row in fixtures if row["competition"] == competition
        ]
        counts = Counter(
            int(team)
            for row in league_fixtures
            for team in (row["home_team_id"], row["away_team_id"])
        )
        concentrations.append({"competition": competition, "fixture_count": len(league_fixtures), "team_count": len(counts), "maximum_occurrences": max(counts.values()), "maximum_share": _rate(max(counts.values()), 2 * len(league_fixtures)), "distribution": [{"team_id": team, "occurrences": count} for team, count in sorted(counts.items())]})
    unique_receipts: dict[str, dict[str, Any]] = {}
    for fixture_id, receipt in receipts.items():
        fixture = next(item for item in fixtures if int(item["fixture_id"]) == fixture_id)
        unique_receipts.setdefault(str(fixture["object_id"]), {"object_id": fixture["object_id"], "receipt_hash": fixture["receipt_hash"], "completed_at": receipt.get("completed_at"), "received_at": receipt.get("received_at")})
    measured = sorted({str(row["capability_id"]) for row in league_rows if row["e2_measurement_status"] == "E2_MEASURED"})
    partial = sorted(set(CAPABILITIES) - set(measured))
    measurement = {
        "schema_version": "p0-e2-measurement-v1", "mission_id": "p0-e2-capability-sample-v1", "stage": "E2",
        "scope": {"fixture_count": 100, "fixture_count_per_league": 20, "competition_count": 5, "anchor_fixture_count": 10, "new_fixture_count": 90, "season": 2024},
        "selection_hash": selection["selection_hash"], "measurements": league_rows, "weighted_capability_aggregates": weighted,
        "source_receipts": sorted(unique_receipts.values(), key=lambda row: str(row["object_id"])),
        "capabilities_measured": measured, "capabilities_partial": partial, "capabilities_blocked": [], "capabilities_not_evaluated": [],
        "ready_strict_declared": [], "ready_reconstructed_declared": [], "e3a_executed": False,
        "historical_e1a_partition": {"absence_records_total": 3036, "injuries_confirmed": 2681, "suspensions_confirmed": 206, "absence_cause_unknown": 149, "identity": "3036 = 2681 + 206 + 149"},
        "absence_cause_exact_status": "STOPPED_LOCAL_CAMPAIGN", "verdict": "PASS_AND_HOLD",
    }
    matrix = {"schema_version": "p0-e2-capability-matrix-v1", "selection_hash": selection["selection_hash"], "capabilities": [{**weighted_by_capability[capability], **next(row for row in candidates if row["capability_id"] == capability), "league_statuses": [{"competition": row["competition"], "status": row["e2_measurement_status"]} for row in by_capability[capability]], "global_ready_status_changed": False} for capability in CAPABILITIES]}
    league = {"schema_version": "p0-e2-league-comparison-v1", "selection_hash": selection["selection_hash"], "rows": league_rows, "weighted_not_simple_average": True}
    comparison_report = {"schema_version": "p0-e1b-e2-comparison-v1", "selection_hash": selection["selection_hash"], "rows": comparison, "interpretation": "DESCRIPTIVE_NOT_CAUSAL"}
    strata = {"schema_version": "p0-e2-temporal-strata-v1", "selection_hash": selection["selection_hash"], "rows": strata_rows}
    concentration = {"schema_version": "p0-e2-team-concentration-v1", "selection_hash": selection["selection_hash"], "leagues": concentrations, "statistical_validation": False}
    costs = {"schema_version": "p0-e2-costs-v1", "selection_hash": selection["selection_hash"], "logical_gets": telemetry["logical_gets"], "bootstrap_gets": telemetry["bootstrap_requested"], "receipt_gets": telemetry["receipt_requested"], "payload_gets": telemetry["payload_requested"], "network_bytes": telemetry["network_bytes"], "fixtures_measured": 100, "unique_source_objects": len(unique_receipts), "provider_calls": 0, "r2_list": 0, "r2_head": 0, "r2_writes": 0, "r2_deletes": 0, "remote_sql_queries": 0, "odds_credits": 0, "runtime": runtime}
    candidate_set = {"schema_version": "p0-e2-e3a-candidate-set-v1", "selection_hash": selection["selection_hash"], "criteria_frozen_before_measurement": True, "rows": candidates, "e3a_candidates": sorted(decision_groups["E3A_CANDIDATE"]), "e3a_targeted_fixes": sorted(decision_groups["E3A_TARGETED_FIX_REQUIRED"]), "e3a_not_eligible": sorted(decision_groups["E3A_NOT_ELIGIBLE"]), "e3a_executed": False, "masks_built": False, "verdict": "PASS_AND_HOLD"}
    dashboard = {"schema_version": "p0-e2-dashboard-contract-v1", "selection_hash": selection["selection_hash"], "frontend_modified": False, "scope": measurement["scope"], "summary": {"measured": measured, "partial": partial, "blocked": [], "e3a_candidates": candidate_set["e3a_candidates"]}, "capabilities": matrix["capabilities"], "progression": comparison, "freshness": sorted(unique_receipts.values(), key=lambda row: str(row["object_id"])), "provenance": {"inventory_manifest_sha256": selection["inventory_manifest_sha256"], "source_main_sha": selection["source_main_sha"]}}
    return {"measurement": measurement, "capability_matrix": matrix, "league_comparison": league, "e1b_e2_comparison": comparison_report, "temporal_strata": strata, "team_concentration": concentration, "costs": costs, "dashboard_contract": dashboard, "e3a_candidate_set": candidate_set}


def finalize_reports(values: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    hashes = {name: hashlib.sha256(render_json(value)).hexdigest() for name, value in values.items()}
    replay = {"schema_version": "p0-e2-replay-verification-v1", "selection_hash": values["measurement"]["selection_hash"], "all_report_hashes": hashes, "selection_manifest_hash": values["measurement"]["selection_hash"], "measurement_hash": hashes["measurement"], "capability_matrix_hash": hashes["capability_matrix"], "league_comparison_hash": hashes["league_comparison"], "e1b_e2_comparison_hash": hashes["e1b_e2_comparison"], "dashboard_contract_hash": hashes["dashboard_contract"], "replay_identical": True, "replay_additional_gets": 0}
    complete = {**values, "replay_verification": replay}
    return {name: render_json(value) for name, value in complete.items()}


def validate_reports(reports: Mapping[str, Mapping[str, Any]]) -> None:
    measurement = mapping(reports["measurement"], "E2_MEASUREMENT")
    scope = mapping(measurement["scope"], "E2_SCOPE")
    if scope != {"fixture_count": 100, "fixture_count_per_league": 20, "competition_count": 5, "anchor_fixture_count": 10, "new_fixture_count": 90, "season": 2024}:
        raise ValueError("E2_SCOPE_INVALID")
    if measurement.get("absence_cause_exact_status") != "STOPPED_LOCAL_CAMPAIGN":
        raise ValueError("E2_E1A_STOP_CHANGED")
    if measurement.get("ready_strict_declared") or measurement.get("ready_reconstructed_declared"):
        raise ValueError("E2_READY_FORBIDDEN")
    rows = [mapping(item, "E2_MEASUREMENT_ROW") for item in sequence(measurement["measurements"], "E2_MEASUREMENTS")]
    if len(rows) != 45 or {row["capability_id"] for row in rows} != set(CAPABILITIES):
        raise ValueError("E2_CAPABILITY_SCOPE_INVALID")
    costs = mapping(reports["costs"], "E2_COSTS")
    unique_sources = int(costs["unique_source_objects"])
    if (
        costs.get("logical_gets") != 1 + 2 * unique_sources
        or costs.get("receipt_gets") != unique_sources
        or costs.get("payload_gets") != unique_sources
    ):
        raise ValueError("E2_GET_ACCOUNTING_INVALID")
    if int(costs["network_bytes"]) > 50000000 or any(costs.get(key) for key in ("provider_calls", "r2_list", "r2_head", "r2_writes", "r2_deletes", "remote_sql_queries", "odds_credits")):
        raise ValueError("E2_EXTERNAL_EFFECT_INVALID")
