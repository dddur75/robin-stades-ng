"""Exact-key, two-GET diagnostic for E2 fixture 1208603."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, TypeAlias

from robin.historical_deep.normalization import canonical_json_bytes
from robin.historical_deep.storage import HarvestReceipt

JsonMapping: TypeAlias = Mapping[str, Any]
RootCause: TypeAlias = Literal[
    "MISSING_SOURCE_ROW",
    "DUPLICATE_PLAYER_ID",
    "PLAYER_ID_ALIAS",
    "TEAM_ASSIGNMENT_MISMATCH",
    "HOME_AWAY_ROLE_MISMATCH",
    "SCHEMA_VARIANT",
    "NULL_IDENTITY",
    "NORMALIZER_BUG",
    "GRAIN_DEFINITION_MISMATCH",
    "PROVIDER_INCONSISTENCY",
    "UNRESOLVED_WITH_AVAILABLE_EVIDENCE",
]


class GetObjectClient(Protocol):
    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, object]: ...


def _mapping(value: object, label: str) -> JsonMapping:
    if not isinstance(value, Mapping):
        raise TypeError(label)
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(label)
    return value


def _read_bounded(
    client: GetObjectClient,
    *,
    bucket: str,
    key: str,
    limit: int,
) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    length = response.get("ContentLength")
    if length is not None and (isinstance(length, bool) or not isinstance(length, int) or length > limit):
        raise ValueError("E2_DIAGNOSTIC_CONTENT_LENGTH_INVALID")
    body = response.get("Body")
    read = getattr(body, "read", None)
    if not callable(read):
        raise ValueError("E2_DIAGNOSTIC_BODY_INVALID")
    try:
        value = read(limit + 1)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    if not isinstance(value, bytes) or len(value) > limit:
        raise ValueError("E2_DIAGNOSTIC_BYTE_BUDGET_EXCEEDED")
    return value


def _decompress_bounded(stored: bytes, *, limit: int) -> bytes:
    with gzip.GzipFile(fileobj=io.BytesIO(stored), mode="rb") as archive:
        logical = archive.read(limit + 1)
    if len(logical) > limit:
        raise ValueError("E2_DIAGNOSTIC_LOGICAL_BYTE_BUDGET_EXCEEDED")
    return logical


def fetch_exact_pair(
    client: GetObjectClient,
    *,
    bucket: str,
    contract: JsonMapping,
) -> tuple[JsonMapping, object, dict[str, int]]:
    """Read only the receipt and payload keys pinned by the committed contract."""

    budgets = _mapping(contract.get("budgets"), "E2_DIAGNOSTIC_BUDGETS")
    if budgets != {
        "r2_get_max": 2,
        "r2_bytes_max": 5_000_000,
        "r2_list": 0,
        "r2_head": 0,
        "r2_writes": 0,
        "r2_deletes": 0,
        "provider_calls": 0,
        "remote_sql": 0,
        "odds_credits": 0,
    }:
        raise ValueError("E2_DIAGNOSTIC_BUDGET_CONTRACT_INVALID")
    receipt_raw = _read_bounded(
        client,
        bucket=bucket,
        key=str(contract["receipt_key"]),
        limit=262_144,
    )
    receipt_value = _mapping(json.loads(receipt_raw), "E2_DIAGNOSTIC_RECEIPT")
    if canonical_json_bytes(receipt_value) != receipt_raw:
        raise ValueError("E2_DIAGNOSTIC_RECEIPT_NOT_CANONICAL")
    receipt = HarvestReceipt.model_validate(receipt_value)
    if (
        receipt.receipt_hash != contract["receipt_hash"]
        or receipt.receipt_key != contract["receipt_key"]
        or receipt.payload_key != contract["payload_key"]
        or receipt.payload_sha256 != contract["payload_hash"]
        or receipt.stored_sha256 != contract["stored_hash"]
        or receipt.stored_bytes != contract["stored_bytes"]
        or receipt.payload_bytes != contract["logical_bytes"]
    ):
        raise ValueError("E2_DIAGNOSTIC_RECEIPT_PIN_MISMATCH")
    stored_limit = int(contract["stored_bytes"])
    stored = _read_bounded(
        client,
        bucket=bucket,
        key=str(contract["payload_key"]),
        limit=stored_limit,
    )
    if (
        len(stored) != stored_limit
        or hashlib.sha256(stored).hexdigest() != contract["stored_hash"]
    ):
        raise ValueError("E2_DIAGNOSTIC_STORED_PAYLOAD_MISMATCH")
    logical = _decompress_bounded(stored, limit=int(contract["logical_bytes"]))
    if (
        len(logical) != contract["logical_bytes"]
        or hashlib.sha256(logical).hexdigest() != contract["payload_hash"]
    ):
        raise ValueError("E2_DIAGNOSTIC_LOGICAL_PAYLOAD_MISMATCH")
    payload = json.loads(logical)
    if canonical_json_bytes(payload) != logical:
        raise ValueError("E2_DIAGNOSTIC_PAYLOAD_NOT_CANONICAL")
    total = len(receipt_raw) + len(stored)
    if total > int(budgets["r2_bytes_max"]):
        raise ValueError("E2_DIAGNOSTIC_TOTAL_BYTE_BUDGET_EXCEEDED")
    return receipt_value, payload, {"r2_gets": 2, "network_bytes": total, "logical_bytes": len(logical)}


def _fixture_record(payload: object, fixture_id: int) -> JsonMapping:
    root = _mapping(payload, "E2_DIAGNOSTIC_PAYLOAD")
    matches = []
    for raw in _sequence(root.get("response", []), "E2_DIAGNOSTIC_RESPONSE"):
        record = _mapping(raw, "E2_DIAGNOSTIC_RECORD")
        fixture = _mapping(record.get("fixture", {}), "E2_DIAGNOSTIC_FIXTURE")
        if fixture.get("id") == fixture_id:
            matches.append(record)
    if len(matches) != 1:
        raise ValueError("E2_DIAGNOSTIC_FIXTURE_CARDINALITY_INVALID")
    return matches[0]


def _identity_rows(record: JsonMapping) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    lineup_rows: list[dict[str, object]] = []
    for raw_lineup in _sequence(record.get("lineups", []), "E2_DIAGNOSTIC_LINEUPS"):
        lineup = _mapping(raw_lineup, "E2_DIAGNOSTIC_LINEUP")
        team = _mapping(lineup.get("team", {}), "E2_DIAGNOSTIC_LINEUP_TEAM")
        for bucket_name in ("startXI", "substitutes"):
            for raw_player in _sequence(lineup.get(bucket_name, []), "E2_DIAGNOSTIC_PLAYERS"):
                wrapper = _mapping(raw_player, "E2_DIAGNOSTIC_LINEUP_PLAYER")
                player = _mapping(wrapper.get("player", {}), "E2_DIAGNOSTIC_PLAYER")
                lineup_rows.append(
                    {"player_id": player.get("id"), "team_id": team.get("id"), "bucket": bucket_name}
                )
    statistic_rows: list[dict[str, object]] = []
    for raw_team in _sequence(record.get("players", []), "E2_DIAGNOSTIC_PLAYER_BUCKETS"):
        team_bucket = _mapping(raw_team, "E2_DIAGNOSTIC_PLAYER_BUCKET")
        team = _mapping(team_bucket.get("team", {}), "E2_DIAGNOSTIC_STATS_TEAM")
        for raw_player in _sequence(team_bucket.get("players", []), "E2_DIAGNOSTIC_STATS_ROWS"):
            wrapper = _mapping(raw_player, "E2_DIAGNOSTIC_STATS_ROW")
            player = _mapping(wrapper.get("player", {}), "E2_DIAGNOSTIC_STATS_PLAYER")
            statistic_rows.append({"player_id": player.get("id"), "team_id": team.get("id")})
    return lineup_rows, statistic_rows


def _valid_ids(rows: Sequence[JsonMapping]) -> tuple[set[int], list[object], list[int]]:
    ids: list[int] = []
    invalid: list[object] = []
    for row in rows:
        value = row.get("player_id")
        if isinstance(value, int) and not isinstance(value, bool):
            ids.append(value)
        else:
            invalid.append(value)
    duplicate_ids = sorted(player_id for player_id, count in Counter(ids).items() if count > 1)
    return set(ids), invalid, duplicate_ids


def _normalize_path_component(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _leaf_type(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "NUMBER"
    if isinstance(value, str):
        return "STRING"
    return type(value).__name__.upper()


def _walk_paths(value: object, path: str, rows: dict[str, list[object]]) -> None:
    if isinstance(value, Mapping):
        if not value:
            rows[path].append({})
        for key, child in value.items():
            _walk_paths(child, f"{path}.{key}", rows)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if not value:
            rows[f"{path}[*]"].append([])
        for child in value:
            _walk_paths(child, f"{path}[*]", rows)
    else:
        rows[path].append(value)


def _path_mapping(path: str) -> tuple[str, str | None, str, str]:
    normalized = _normalize_path_component(path)
    identity_fragments = (".fixture.id", ".team.id", ".player.id")
    if any(fragment in normalized for fragment in identity_fragments):
        return "IDENTITY_ONLY", "provider_identity", "OBSERVED_AT", "identity and grain key"
    if ".lineups[*].formation" in normalized:
        return "MAPPED", "FORMATION", "OBSERVED_AT", "E2 formation input"
    if ".lineups[*].startxi" in normalized or ".lineups[*].substitutes" in normalized:
        return "MAPPED", "LINEUP", "OBSERVED_AT", "E2 lineup input"
    if ".players[*].players[*].statistics" in normalized:
        return "UNMAPPED_FIELD", None, "POST_MATCH_ONLY", "not mapped by the E2 identity measure"
    if ".events" in normalized or ".statistics" in normalized or ".score" in normalized:
        return "POST_MATCH_ONLY", None, "POST_MATCH_ONLY", "outside this identity-only diagnostic"
    if normalized.endswith(".name") or normalized.endswith(".logo") or normalized.endswith(".photo"):
        return "IGNORED_WITH_REASON", None, "OBSERVED_AT", "display metadata not retained"
    return "UNMAPPED_FIELD", None, "UNKNOWN", "not used by the bounded E2 identity measure"


def field_path_census(record: JsonMapping, fixture_id: int) -> dict[str, object]:
    rows: dict[str, list[object]] = defaultdict(list)
    _walk_paths(record, "$.response[fixture]", rows)
    values = []
    for path, observations in sorted(rows.items()):
        status, property_name, temporal_class, reason = _path_mapping(path)
        values.append(
            {
                "json_path": path,
                "data_type": "|".join(sorted({_leaf_type(item) for item in observations})),
                "observed_count": len(observations),
                "null_count": sum(item is None for item in observations),
                "mapped_status": status,
                "mapped_property": property_name,
                "temporal_class": temporal_class,
                "reason": reason,
            }
        )
    return {
        "schema_version": "e2-1208603-field-path-census-v1",
        "fixture_id": fixture_id,
        "scope": "ONE_FIXTURE_ONLY_NO_PROVIDER_GENERALIZATION",
        "rows": values,
    }


def _root_cause(
    *,
    lineup_ids: set[int],
    statistic_ids: set[int],
    lineup_invalid: Sequence[object],
    statistic_invalid: Sequence[object],
    duplicates: Sequence[int],
    lineup_rows: Sequence[JsonMapping],
    statistic_rows: Sequence[JsonMapping],
) -> RootCause:
    if lineup_invalid or statistic_invalid:
        return "NULL_IDENTITY"
    if duplicates:
        return "DUPLICATE_PLAYER_ID"
    mismatched_teams = {
        int(row["player_id"])
        for row in statistic_rows
        if isinstance(row.get("player_id"), int)
        and any(
            candidate.get("player_id") == row.get("player_id")
            and candidate.get("team_id") != row.get("team_id")
            for candidate in lineup_rows
        )
    }
    if mismatched_teams:
        return "TEAM_ASSIGNMENT_MISMATCH"
    missing = lineup_ids - statistic_ids
    extra = statistic_ids - lineup_ids
    if missing and extra:
        return "PROVIDER_INCONSISTENCY"
    if missing:
        return "MISSING_SOURCE_ROW"
    if extra:
        return "GRAIN_DEFINITION_MISMATCH"
    return "UNRESOLVED_WITH_AVAILABLE_EVIDENCE"


def diagnose_payload(payload: object, *, fixture_id: int, source_hashes: JsonMapping) -> tuple[dict[str, object], dict[str, object]]:
    record = _fixture_record(payload, fixture_id)
    lineup_rows, statistic_rows = _identity_rows(record)
    lineup_ids, lineup_invalid, lineup_duplicates = _valid_ids(lineup_rows)
    statistic_ids, statistic_invalid, statistic_duplicates = _valid_ids(statistic_rows)
    duplicates = sorted(set(lineup_duplicates + statistic_duplicates))
    root_cause = _root_cause(
        lineup_ids=lineup_ids,
        statistic_ids=statistic_ids,
        lineup_invalid=lineup_invalid,
        statistic_invalid=statistic_invalid,
        duplicates=duplicates,
        lineup_rows=lineup_rows,
        statistic_rows=statistic_rows,
    )
    census = field_path_census(record, fixture_id)
    census_rows = _sequence(census["rows"], "E2_DIAGNOSTIC_CENSUS")
    unmapped = [
        str(_mapping(row, "E2_DIAGNOSTIC_CENSUS_ROW")["json_path"])
        for row in census_rows
        if _mapping(row, "E2_DIAGNOSTIC_CENSUS_ROW")["mapped_status"] == "UNMAPPED_FIELD"
    ]
    missing = sorted(lineup_ids - statistic_ids)
    extra = sorted(statistic_ids - lineup_ids)
    code_fix_required = root_cause in {
        "PLAYER_ID_ALIAS",
        "TEAM_ASSIGNMENT_MISMATCH",
        "HOME_AWAY_ROLE_MISMATCH",
        "SCHEMA_VARIANT",
        "NORMALIZER_BUG",
    }
    report = {
        "schema_version": "e2-player-statistics-1208603-diagnostic-v1",
        "fixture_id": fixture_id,
        "source_hashes": dict(source_hashes),
        "expected_grain": "one row per (fixture_id, provider_player_id) from frozen lineup identity",
        "observed_grain": {
            "lineup_rows": len(lineup_rows),
            "lineup_unique_player_ids": len(lineup_ids),
            "player_statistics_rows": len(statistic_rows),
            "player_statistics_unique_ids": len(statistic_ids),
            "intersection": len(lineup_ids & statistic_ids),
        },
        "missing_identity": missing,
        "unexpected_identity": extra,
        "duplicated_identity": duplicates,
        "schema_paths": [
            "$.response[fixture].lineups[*].{startXI,substitutes}[*].player.id",
            "$.response[fixture].players[*].players[*].player.id",
        ],
        "unmapped_paths": unmapped,
        "root_cause": root_cause,
        "code_fix_required": code_fix_required,
        "source_fix_possible": False,
        "unknown_policy": "missing_player_stat_row = UNKNOWN",
        "scientific_effect": "Historical E2 remains 40 expected, 39 received, 1 UNKNOWN and 1 invalid; no row is invented.",
        "recommended_status": (
            "PLAYER_STATISTICS_E2_CORRECTED_VIEW"
            if code_fix_required
            else "PLAYER_STATISTICS_E2_MEASURED_PARTIAL"
        ),
    }
    return report, census
