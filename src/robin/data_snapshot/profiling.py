"""Deterministic quality, temporal, schema and experiment-readiness profiling."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from robin.data_snapshot.contracts import (
    PROTOCOL_SOURCE_SHA256,
    READINESS_MATRIX_CANONICAL_SHA256,
    READINESS_STATUSES,
    SYNTHETIC_BATCH_ID,
    JsonObject,
    JsonValue,
    SnapshotValidationError,
    canonical_json_bytes,
    canonical_sha256,
    parse_utc,
    pseudonym,
    require_array,
    require_object,
    sha256_bytes,
    utc_text,
)
from robin.data_snapshot.source import VerifiedBatch, VerifiedCapture

_WINDOW_TOKEN = re.compile(r"\bH(?:24|12|6|2|1)\b")
_ENRICHED_GATE_FRAGMENTS = (
    "XG_XGA",
    "STRENGTH_SOURCE",
    "VERSIONED_VENUE",
    "MULTI_COMPETITION",
    "COACH_EFFECTIVE_AT",
    "COACH_CLAIM",
    "REGISTRIES_NOT_MATERIALIZED",
)
_CANDIDATE_IDS = (
    "RDS-EXP-V1-001",
    "RDS-EXP-V1-002",
    "RDS-EXP-V1-003",
    "RDS-EXP-V1-004",
    "RDS-EXP-V1-007",
)
_ACCUMULATION_REQUIRED_MARKET = "h2h"
_ACCUMULATION_REQUIRED_WINDOW_ROLE = "PREDICTOR:H2"
_ACCUMULATION_MINIMUM_COMPLETE_BOOKMAKERS = 5


def _delivery_status(*, synthetic_contract: bool) -> JsonObject:
    """Separate tooling proof from the unavailable real-data evidence lane."""

    return {
        "real_data_status": "NOT_AVAILABLE" if synthetic_contract else "AVAILABLE",
        "synthetic_validation_status": "PASS",
        "tooling_status": "OFFLINE_DRAFT_READY",
    }


@dataclass(frozen=True, slots=True)
class ProfileResult:
    normalized_partitions: dict[str, bytes]
    receipt_index: JsonObject
    quality_report: JsonObject
    schema_report: JsonObject
    temporal_report: JsonObject
    readiness_report: JsonObject
    accumulation_report: JsonObject
    denominators: JsonObject
    observed_fixture_count: int
    observed_valid_windows: tuple[str, ...]
    data_gate_blocked: bool


def _decimal(value: object, *, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SnapshotValidationError(code)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        raise SnapshotValidationError(code) from None
    if not parsed.is_finite() or parsed <= 0:
        raise SnapshotValidationError(code)
    return parsed


def _schema_paths(value: JsonValue, path: str = "$") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        result.add(f"{path}:object")
        for key, child in value.items():
            result.update(_schema_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        result.add(f"{path}:array")
        for child in value:
            result.update(_schema_paths(child, f"{path}[*]"))
    elif value is None:
        result.add(f"{path}:null")
    elif isinstance(value, bool):
        result.add(f"{path}:boolean")
    elif isinstance(value, (int, float)):
        result.add(f"{path}:number")
    else:
        result.add(f"{path}:string")
    return result


def _available_at(capture: VerifiedCapture, market: dict[str, Any]) -> str:
    first = parse_utc(capture.first_observed_at, code="CAPTURE_FIRST_OBSERVED_INVALID")
    value = market.get("last_update")
    if value is None:
        return utc_text(first)
    updated = parse_utc(value, code="CAPTURE_MARKET_TIMESTAMP_INVALID")
    return utc_text(max(first, updated))


def _capture_rows(capture: VerifiedCapture) -> tuple[list[JsonObject], int]:
    rows: dict[tuple[str, ...], JsonObject] = {}
    duplicate_count = 0
    events = require_array(capture.raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY")
    for event_value in events:
        event = require_object(event_value, code="CAPTURE_EVENT_INVALID")
        event_id = event.get("id")
        home = event.get("home_team")
        away = event.get("away_team")
        if not all(isinstance(value, str) and value for value in (event_id, home, away)):
            raise SnapshotValidationError("CAPTURE_EVENT_IDENTITY_INVALID")
        event_id_text = cast(str, event_id)
        bookmakers = require_array(event.get("bookmakers"), code="CAPTURE_BOOKMAKERS_INVALID")
        seen_bookmakers: set[str] = set()
        for bookmaker_value in bookmakers:
            bookmaker = require_object(bookmaker_value, code="CAPTURE_BOOKMAKER_INVALID")
            bookmaker_key = bookmaker.get("key")
            if not isinstance(bookmaker_key, str) or not bookmaker_key:
                raise SnapshotValidationError("CAPTURE_BOOKMAKER_IDENTITY_INVALID")
            if bookmaker_key in seen_bookmakers:
                raise SnapshotValidationError("CAPTURE_DUPLICATE_BOOKMAKER")
            seen_bookmakers.add(bookmaker_key)
            markets = require_array(bookmaker.get("markets"), code="CAPTURE_MARKETS_INVALID")
            seen_markets: set[str] = set()
            for market_value in markets:
                market = require_object(market_value, code="CAPTURE_MARKET_INVALID")
                market_key = market.get("key")
                if not isinstance(market_key, str) or not market_key:
                    raise SnapshotValidationError("CAPTURE_MARKET_KEY_INVALID")
                if market_key in seen_markets:
                    raise SnapshotValidationError("CAPTURE_DUPLICATE_MARKET")
                seen_markets.add(market_key)
                outcomes = require_array(market.get("outcomes"), code="CAPTURE_OUTCOMES_INVALID")
                for outcome_value in outcomes:
                    outcome = require_object(outcome_value, code="CAPTURE_OUTCOME_INVALID")
                    name = outcome.get("name")
                    if not isinstance(name, str) or not name:
                        raise SnapshotValidationError("CAPTURE_OUTCOME_NAME_INVALID")
                    price = _decimal(outcome.get("price"), code="CAPTURE_OUTCOME_PRICE_INVALID")
                    point_value = outcome.get("point")
                    point = str(point_value) if point_value is not None else None
                    row: JsonObject = {
                        "available_at": _available_at(capture, market),
                        "away_team": cast(str, away),
                        "bookmaker_key": bookmaker_key,
                        "capture_label": capture.label,
                        "commence_time": event.get("commence_time"),
                        "fixture_mapping_statuses": list(capture.mapping_statuses),
                        "home_team": cast(str, home),
                        "mapping_revision": capture.mapping_revision,
                        "market_key": market_key,
                        "market_last_update": market.get("last_update"),
                        "outcome_name": name,
                        "outcome_point": point,
                        "outcome_price": str(price),
                        "provider_event_id": event_id_text,
                        "raw_payload_sha256": capture.raw_payload_sha256,
                        "receipt_id": capture.receipt_id,
                        "sport_key": event.get("sport_key"),
                    }
                    key = (
                        capture.label,
                        event_id_text,
                        bookmaker_key,
                        market_key,
                        name,
                        point or "",
                    )
                    existing = rows.get(key)
                    if existing is not None:
                        if canonical_json_bytes(existing) != canonical_json_bytes(row):
                            raise SnapshotValidationError("CAPTURE_DUPLICATE_OBSERVATION_CONFLICT")
                        duplicate_count += 1
                        continue
                    rows[key] = row
    return [rows[key] for key in sorted(rows)], duplicate_count


def _ratio(numerator: int, denominator: int, grain: str) -> JsonObject:
    return {
        "denominator": denominator,
        "grain": grain,
        "numerator": numerator,
        "ratio": numerator / denominator if denominator else None,
    }


def _capture_coverage(
    capture: VerifiedCapture, rows: list[JsonObject], duplicate_count: int
) -> tuple[JsonObject, set[str], set[str], set[str], set[str]]:
    events = require_array(capture.raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY")
    event_ids: set[str] = set()
    bookmaker_ids: set[str] = set()
    event_bookmaker_count = 0
    market_objects: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    complete: Counter[str] = Counter()
    market_timestamp_present = 0
    market_timestamp_present_by_market: Counter[str] = Counter()
    bookmaker_timestamp_present = 0
    totals_line_consistent = 0
    duplicate_outcome_identity_count = 0
    invalid_timestamp_count = 0
    outcome_cardinality: dict[str, Counter[int]] = defaultdict(Counter)
    event_without_bookmaker_count = 0
    complete_h2h_bookmakers_by_event: dict[str, set[str]] = defaultdict(set)
    for event_value in events:
        event = require_object(event_value, code="CAPTURE_EVENT_INVALID")
        event_id = str(event["id"])
        event_ids.add(event_id)
        home = str(event["home_team"])
        away = str(event["away_team"])
        bookmakers = require_array(event.get("bookmakers"), code="CAPTURE_BOOKMAKERS_INVALID")
        if not bookmakers:
            event_without_bookmaker_count += 1
        for bookmaker_value in bookmakers:
            bookmaker = require_object(bookmaker_value, code="CAPTURE_BOOKMAKER_INVALID")
            bookmaker_key = str(bookmaker["key"])
            event_bookmaker_count += 1
            bookmaker_ids.add(bookmaker_key)
            bookmaker_update = bookmaker.get("last_update")
            if bookmaker_update is not None:
                try:
                    parse_utc(bookmaker_update, code="BOOKMAKER_LAST_UPDATE_INVALID")
                except SnapshotValidationError:
                    invalid_timestamp_count += 1
                else:
                    bookmaker_timestamp_present += 1
            for market_value in require_array(
                bookmaker.get("markets"), code="CAPTURE_MARKETS_INVALID"
            ):
                market = require_object(market_value, code="CAPTURE_MARKET_INVALID")
                market_key = str(market["key"])
                market_objects[market_key] += 1
                market_update = market.get("last_update")
                if market_update is not None:
                    try:
                        parse_utc(market_update, code="MARKET_LAST_UPDATE_INVALID")
                    except SnapshotValidationError:
                        invalid_timestamp_count += 1
                    else:
                        market_timestamp_present += 1
                        market_timestamp_present_by_market[market_key] += 1
                outcomes = [
                    require_object(item, code="CAPTURE_OUTCOME_INVALID")
                    for item in require_array(
                        market.get("outcomes"), code="CAPTURE_OUTCOMES_INVALID"
                    )
                ]
                seen_outcome_identities: set[tuple[str, str]] = set()
                for outcome in outcomes:
                    identity = (str(outcome.get("name")), str(outcome.get("point")))
                    if identity in seen_outcome_identities:
                        duplicate_outcome_identity_count += 1
                    seen_outcome_identities.add(identity)
                outcome_counts[market_key] += len(outcomes)
                outcome_cardinality[market_key][len(outcomes)] += 1
                names = {str(item.get("name")) for item in outcomes}
                if (
                    market_key == "h2h"
                    and len(outcomes) == 3
                    and names == {home, away, "Draw"}
                    and all(item.get("point") is None for item in outcomes)
                ):
                    complete[market_key] += 1
                    complete_h2h_bookmakers_by_event[event_id].add(bookmaker_key)
                if market_key == "totals" and len(outcomes) == 2 and names == {"Over", "Under"}:
                    point_values = [item.get("point") for item in outcomes]
                    try:
                        points = {
                            Decimal(str(value)) for value in point_values if value is not None
                        }
                    except InvalidOperation:
                        points = set()
                    if (
                        all(value is not None for value in point_values)
                        and len(points) == 1
                        and all(point.is_finite() for point in points)
                    ):
                        totals_line_consistent += 1
                        if points == {Decimal("2.5")}:
                            complete[market_key] += 1
    timestamp_denominator = sum(market_objects.values())
    normalized_rows = len(rows)
    h2h_bookmaker_floor_satisfied = bool(event_ids) and all(
        len(complete_h2h_bookmakers_by_event[event_id]) >= _ACCUMULATION_MINIMUM_COMPLETE_BOOKMAKERS
        for event_id in event_ids
    )
    contract_markets = {
        *(
            ("h2h",)
            if event_without_bookmaker_count == 0
            and bookmaker_timestamp_present == event_bookmaker_count
            and market_timestamp_present_by_market["h2h"] == market_objects["h2h"]
            and complete["h2h"] == event_bookmaker_count > 0
            and h2h_bookmaker_floor_satisfied
            else ()
        ),
        *(
            ("totals:2.5",)
            if event_without_bookmaker_count == 0
            and bookmaker_timestamp_present == event_bookmaker_count
            and market_timestamp_present_by_market["totals"] == market_objects["totals"]
            and complete["totals"] == event_bookmaker_count > 0
            else ()
        ),
    }
    report: JsonObject = {
        "bookmaker_continuity_identity_count": len(bookmaker_ids),
        "bookmaker_timestamp_coverage": _ratio(
            bookmaker_timestamp_present,
            event_bookmaker_count,
            "event×bookmaker×capture",
        ),
        "capture_label": capture.label,
        "contract_market_tokens": sorted(contract_markets),
        "duplicate_bookmaker_identity_count": 0,
        "duplicate_market_identity_count": 0,
        "duplicate_observation_count": duplicate_count,
        "duplicate_outcome_identity_count": duplicate_outcome_identity_count,
        "duplicate_provider_event_identity_count": len(events) - len(event_ids),
        "event_bookmaker_occurrence_count": event_bookmaker_count,
        "event_count": len(events),
        "h2h_completeness": _ratio(complete["h2h"], market_objects["h2h"], "h2h market object"),
        "h2h_presence": _ratio(
            market_objects["h2h"],
            event_bookmaker_count,
            "event×bookmaker×capture",
        ),
        "line_consistency": _ratio(
            totals_line_consistent,
            market_objects["totals"],
            "totals market object",
        ),
        "market_object_counts": dict(sorted(market_objects.items())),
        "market_timestamp_coverage": _ratio(
            market_timestamp_present,
            timestamp_denominator,
            "market object",
        ),
        "missingness": {
            "bookmaker_timestamp_missing": event_bookmaker_count - bookmaker_timestamp_present,
            "invalid_timestamp_count": invalid_timestamp_count,
            "market_timestamp_missing": timestamp_denominator - market_timestamp_present,
            "totals_market_missing": event_bookmaker_count - market_objects["totals"],
        },
        "normalized_observation_count": normalized_rows,
        "outcome_cardinality": {
            market: {str(key): value for key, value in sorted(counts.items())}
            for market, counts in sorted(outcome_cardinality.items())
        },
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "receipt_proof": {
            "raw_hash_verified_before_parse": True,
            "receipt_id": capture.receipt_id,
        },
        "totals_completeness": _ratio(
            complete["totals"], market_objects["totals"], "totals market object"
        ),
        "totals_presence": _ratio(
            market_objects["totals"],
            event_bookmaker_count,
            "event×bookmaker×capture",
        ),
        "unique_bookmaker_count": len(bookmaker_ids),
        "unique_provider_event_count": len(event_ids),
    }
    return report, event_ids, bookmaker_ids, set(market_objects), contract_markets


def _schema_report(
    batch: VerifiedBatch,
    event_sets: dict[str, set[str]],
    bookmaker_sets: dict[str, set[str]],
    market_sets: dict[str, set[str]],
) -> JsonObject:
    captures: list[JsonObject] = []
    path_sets: dict[str, set[str]] = {}
    outcome_structures: dict[str, str] = {}
    quota_fields: dict[str, set[str]] = {}
    for capture in batch.captures:
        paths = _schema_paths(capture.raw_payload)
        path_sets[capture.label] = paths
        structure: Counter[str] = Counter()
        for event_value in require_array(capture.raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY"):
            event = require_object(event_value, code="CAPTURE_EVENT_INVALID")
            for bookmaker_value in require_array(
                event.get("bookmakers"), code="CAPTURE_BOOKMAKERS_INVALID"
            ):
                bookmaker = require_object(bookmaker_value, code="CAPTURE_BOOKMAKER_INVALID")
                for market_value in require_array(
                    bookmaker.get("markets"), code="CAPTURE_MARKETS_INVALID"
                ):
                    market = require_object(market_value, code="CAPTURE_MARKET_INVALID")
                    outcomes = require_array(
                        market.get("outcomes"), code="CAPTURE_OUTCOMES_INVALID"
                    )
                    structure[f"{market.get('key')}:{len(outcomes)}"] += 1
        outcome_structures[capture.label] = canonical_sha256(dict(sorted(structure.items())))
        quota_fields[capture.label] = set(capture.quota)
        captures.append(
            {
                "capture_label": capture.label,
                "field_path_and_type_count": len(paths),
                "outcome_structure_sha256": outcome_structures[capture.label],
                "provider_schema_fingerprint_sha256": capture.schema_fingerprint_sha256,
                "quota_header_fields": sorted(quota_fields[capture.label]),
                "structural_schema_fingerprint_sha256": canonical_sha256(sorted(paths)),
            }
        )
    labels = sorted(path_sets)
    classifications: list[str] = []
    pairwise: list[JsonObject] = []
    for index, left_label in enumerate(labels):
        for right_label in labels[index + 1 :]:
            left = path_sets[left_label]
            right = path_sets[right_label]
            left_types_mutable: dict[str, set[str]] = defaultdict(set)
            right_types_mutable: dict[str, set[str]] = defaultdict(set)
            for item in left:
                path, _, value_type = item.rpartition(":")
                left_types_mutable[path].add(value_type)
            for item in right:
                path, _, value_type = item.rpartition(":")
                right_types_mutable[path].add(value_type)
            left_types = {
                path: frozenset(value_types) for path, value_types in left_types_mutable.items()
            }
            right_types = {
                path: frozenset(value_types) for path, value_types in right_types_mutable.items()
            }
            common_paths = set(left_types) & set(right_types)
            type_break = any(left_types[path] != right_types[path] for path in common_paths)
            outcome_structure_changed = (
                outcome_structures[left_label] != outcome_structures[right_label]
            )
            quota_header_fields_changed = quota_fields[left_label] != quota_fields[right_label]
            if type_break:
                classification = "BREAKING_SCHEMA_DRIFT"
            elif left != right or quota_header_fields_changed:
                classification = "COMPATIBLE_OPTIONAL_DRIFT"
            elif (
                event_sets[left_label] != event_sets[right_label]
                or bookmaker_sets[left_label] != bookmaker_sets[right_label]
                or market_sets[left_label] != market_sets[right_label]
                or outcome_structure_changed
            ):
                classification = "COVERAGE_DRIFT_ONLY"
            else:
                classification = "NO_SCHEMA_DRIFT"
            classifications.append(classification)
            pairwise.append(
                {
                    "bookmaker_continuity": _ratio(
                        len(bookmaker_sets[left_label] & bookmaker_sets[right_label]),
                        len(bookmaker_sets[left_label] | bookmaker_sets[right_label]),
                        "unique bookmaker identity across capture pair",
                    ),
                    "classification": classification,
                    "event_continuity": _ratio(
                        len(event_sets[left_label] & event_sets[right_label]),
                        len(event_sets[left_label] | event_sets[right_label]),
                        "unique provider event across capture pair",
                    ),
                    "left_capture": left_label,
                    "market_set_changed": market_sets[left_label] != market_sets[right_label],
                    "optional_field_path_delta_count": len(left ^ right),
                    "outcome_structure_changed": outcome_structure_changed,
                    "quota_header_fields_changed": quota_header_fields_changed,
                    "right_capture": right_label,
                }
            )
    severity = {
        "BREAKING_SCHEMA_DRIFT": 3,
        "COMPATIBLE_OPTIONAL_DRIFT": 2,
        "COVERAGE_DRIFT_ONLY": 1,
        "NO_SCHEMA_DRIFT": 0,
    }
    overall = max(classifications or ["NO_SCHEMA_DRIFT"], key=severity.__getitem__)
    return {
        "artifact": "five-canary-schema-drift-v1",
        "capture_count": len(batch.captures),
        "captures": captures,
        "claim_id": "DATA.FROZEN_SNAPSHOT.SCHEMA_DRIFT.V1.001",
        "overall_classification": overall,
        "pairwise_comparisons": pairwise,
        "provider_event_ids_committed": False,
        "real_bookmaker_identities_committed": False,
        "schema_version": "robin-five-canary-schema-drift-v1",
        "verdict": (
            "FROZEN_SNAPSHOT_SYNTHETIC_SCHEMA_CONTRACT_VALIDATED"
            if batch.batch_id == SYNTHETIC_BATCH_ID
            else "REAL_MARKET_SCHEMA_DRIFT_CLASSIFIED"
        ),
        **_delivery_status(synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID),
    }


def _temporal_alias(entry: Mapping[str, Any], names: tuple[str, ...]) -> str | None:
    declared = [entry[name] for name in names if name in entry and entry[name] is not None]
    if not declared:
        return None
    if any(not isinstance(value, str) or not value for value in declared):
        raise SnapshotValidationError("TEMPORAL_WINDOW_ALIAS_CONFLICT")
    if any(value != declared[0] for value in declared[1:]):
        raise SnapshotValidationError("TEMPORAL_WINDOW_ALIAS_CONFLICT")
    return cast(str, declared[0])


def _window_label(entry: dict[str, Any]) -> str | None:
    value = _temporal_alias(entry, ("window_id", "claimed_window", "window"))
    return str(value).upper() if isinstance(value, str) and value else None


def _selected_fixture_groups(
    selections: tuple[JsonObject, ...],
) -> dict[str, dict[str, set[str]]]:
    grouped: dict[str, dict[str, set[str]]] = {}
    for selection in selections:
        fixture_value = selection.get("fixture_id")
        fixture_id = fixture_value if isinstance(fixture_value, str) and fixture_value else None
        provider_value = next(
            (
                selection[name]
                for name in ("provider_event_id", "event_id", "id")
                if isinstance(selection.get(name), str) and selection.get(name)
            ),
            None,
        )
        provider_event_id = str(provider_value) if provider_value is not None else None
        key = (
            f"fixture:{fixture_id}"
            if fixture_id is not None
            else f"provider:{provider_event_id}"
            if provider_event_id is not None
            else "selection:"
            + canonical_sha256(
                {key: value for key, value in selection.items() if key != "selection_index"}
            )
        )
        group = grouped.setdefault(key, {"fixture_ids": set(), "provider_event_ids": set()})
        if fixture_id is not None:
            group["fixture_ids"].add(fixture_id)
        if provider_event_id is not None:
            group["provider_event_ids"].add(provider_event_id)
    return grouped


def _selected_fixture_key(
    selected_groups: dict[str, dict[str, set[str]]],
    entry: JsonObject,
    fixture_mapping: JsonObject | None,
) -> str | None:
    mapped_fixture = fixture_mapping.get("fixture_id") if fixture_mapping is not None else None
    if mapped_fixture is None:
        mapped_fixture = entry.get("fixture_id")
    mapped_provider = (
        fixture_mapping.get("provider_event_id") if fixture_mapping is not None else None
    )
    if mapped_provider is None:
        mapped_provider = next(
            (entry[name] for name in ("provider_event_id", "event_id") if entry.get(name)),
            None,
        )
    fixture_id = str(mapped_fixture) if mapped_fixture is not None else None
    provider_event_id = str(mapped_provider) if mapped_provider is not None else None
    matches = [
        key
        for key, identities in selected_groups.items()
        if (identities["fixture_ids"] or identities["provider_event_ids"])
        and (
            not identities["fixture_ids"]
            or fixture_id is not None
            and fixture_id in identities["fixture_ids"]
        )
        and (
            not identities["provider_event_ids"]
            or provider_event_id is not None
            and provider_event_id in identities["provider_event_ids"]
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _selected_fixture_mapping_statuses(batch: VerifiedBatch) -> dict[str, str]:
    """Resolve one fail-closed mapping status per selected fixture across the batch."""

    grouped = _selected_fixture_groups(batch.selected_fixtures)
    mappings = [mapping for capture in batch.captures for mapping in capture.fixture_mappings]
    resolved: dict[str, str] = {}
    for selection_key, selection in grouped.items():
        declared_fixtures = selection["fixture_ids"]
        declared_providers = selection["provider_event_ids"]
        initially_related = [
            mapping
            for mapping in mappings
            if (
                mapping.get("fixture_id") is not None
                and str(mapping["fixture_id"]) in declared_fixtures
            )
            or str(mapping.get("provider_event_id")) in declared_providers
        ]
        inferred_fixtures = {
            str(mapping["fixture_id"])
            for mapping in initially_related
            if mapping.get("fixture_id") is not None
        }
        inferred_providers = {
            str(mapping["provider_event_id"])
            for mapping in initially_related
            if mapping.get("provider_event_id") is not None
        }
        expected_fixtures = declared_fixtures or inferred_fixtures
        expected_providers = declared_providers or inferred_providers
        related = [
            mapping
            for mapping in mappings
            if (
                mapping.get("fixture_id") is not None
                and str(mapping["fixture_id"]) in expected_fixtures
            )
            or str(mapping.get("provider_event_id")) in expected_providers
        ]
        statuses = {str(mapping.get("status")) for mapping in related}
        relation_conflict = any(
            (
                mapping.get("fixture_id") is not None
                and str(mapping["fixture_id"]) not in expected_fixtures
                and str(mapping.get("provider_event_id")) in expected_providers
            )
            or (
                mapping.get("provider_event_id") is not None
                and str(mapping["provider_event_id"]) not in expected_providers
                and str(mapping.get("fixture_id")) in expected_fixtures
            )
            for mapping in related
        )
        pair_conflict = (
            len(inferred_fixtures) > 1
            or len(inferred_providers) > 1
            or bool(declared_fixtures and inferred_fixtures - declared_fixtures)
            or bool(declared_providers and inferred_providers - declared_providers)
        )
        selection_conflict = len(declared_fixtures) > 1 or len(declared_providers) > 1
        if (
            selection_conflict
            or pair_conflict
            or relation_conflict
            or "FIXTURE_MAPPING_CONFLICT" in statuses
        ):
            status = "FIXTURE_MAPPING_CONFLICT"
        elif "FIXTURE_MAPPING_AMBIGUOUS" in statuses:
            status = "FIXTURE_MAPPING_AMBIGUOUS"
        elif (
            related
            and statuses == {"FIXTURE_MAPPING_PROVEN"}
            and all(
                mapping.get("fixture_id") is not None
                and mapping.get("provider_event_id") is not None
                and str(mapping["fixture_id"]) in expected_fixtures
                and str(mapping["provider_event_id"]) in expected_providers
                for mapping in related
            )
        ):
            status = "FIXTURE_MAPPING_PROVEN"
        else:
            status = "FIXTURE_MAPPING_UNPROVEN"
        resolved[selection_key] = status
    return resolved


def _technical_raw_kickoff_bound(
    receipt: VerifiedCapture,
    fixture_mapping: JsonObject | None,
    kickoff: object,
) -> bool:
    """Require one exact raw provider event whose kickoff equals the claimed window kickoff."""

    if not receipt.technical_harness_contract_verified:
        return True
    if fixture_mapping is None:
        return False
    fixture_id = fixture_mapping.get("fixture_id")
    provider_event_id = fixture_mapping.get("provider_event_id")
    if fixture_id is None or provider_event_id is None or kickoff is None:
        return False
    events = require_array(receipt.raw_payload, code="CAPTURE_RAW_ROOT_NOT_ARRAY")
    matches = [
        require_object(event, code="CAPTURE_EVENT_INVALID")
        for event in events
        if isinstance(event, dict) and str(event.get("id")) == str(provider_event_id)
    ]
    if len(matches) != 1 or matches[0].get("commence_time") is None:
        return False
    try:
        claimed = parse_utc(kickoff, code="TEMPORAL_KICKOFF_INVALID")
        observed = parse_utc(matches[0]["commence_time"], code="TEMPORAL_RAW_KICKOFF_INVALID")
    except SnapshotValidationError:
        return False
    return claimed == observed


def _effective_market_available_at(
    receipt: VerifiedCapture,
    fixture_identity: object,
    fixture_mapping: JsonObject | None,
    generated_rows: list[JsonObject],
) -> tuple[datetime, datetime | None, int, str, bool]:
    """Return the conservative availability clock for one fixture in one receipt."""

    receipt_available = parse_utc(receipt.available_at, code="TEMPORAL_AVAILABLE_AT_INVALID")
    technical = receipt.technical_harness_contract_verified
    if technical:
        expected_fixture = (
            fixture_mapping.get("fixture_id") if fixture_mapping is not None else None
        )
        expected_provider = (
            fixture_mapping.get("provider_event_id") if fixture_mapping is not None else None
        )
        if expected_fixture is None or expected_provider is None:
            return receipt_available, None, 0, "TECHNICAL_NORMALIZED_ROWS", False
        fixture_id = str(expected_fixture)
        provider_event_id = str(expected_provider)
        relevant_rows = [
            row
            for row in receipt.source_normalized_rows
            if str(row.get("fixture_id")) == fixture_id
            or str(row.get("provider_event_id")) == provider_event_id
        ]
        matching_rows = [
            row
            for row in relevant_rows
            if str(row.get("fixture_id")) == fixture_id
            and str(row.get("provider_event_id")) == provider_event_id
        ]
        if len(matching_rows) != len(relevant_rows) or not matching_rows:
            return (
                receipt_available,
                None,
                len(relevant_rows),
                "TECHNICAL_NORMALIZED_ROWS",
                False,
            )
    else:
        fixture_identities = {str(fixture_identity)}
        if fixture_mapping is not None:
            fixture_identities.update(
                str(value)
                for value in (
                    fixture_mapping.get("fixture_id"),
                    fixture_mapping.get("provider_event_id"),
                )
                if value is not None
            )
        matching_rows = [
            row
            for row in generated_rows
            if fixture_identities
            & {
                str(row[key])
                for key in ("fixture_id", "provider_event_id", "event_id")
                if row.get(key) is not None
            }
        ]
    row_available = [
        parse_utc(row.get("available_at"), code="TEMPORAL_ROW_AVAILABLE_AT_INVALID")
        for row in matching_rows
        if row.get("available_at") is not None
    ]
    if technical and len(row_available) != len(matching_rows):
        return receipt_available, None, len(matching_rows), "TECHNICAL_NORMALIZED_ROWS", False
    if technical and not row_available:
        return receipt_available, None, 0, "TECHNICAL_NORMALIZED_ROWS", False
    row_max = max(row_available) if row_available else None
    effective = max(receipt_available, row_max) if row_max is not None else receipt_available
    source = (
        "TECHNICAL_NORMALIZED_ROWS"
        if technical
        else ("PROFILE_NORMALIZED_ROWS" if row_max is not None else "RECEIPT")
    )
    return effective, row_max, len(matching_rows), source, True


def _temporal_report(
    batch: VerifiedBatch,
    rows_by_capture: dict[str, list[JsonObject]] | None = None,
) -> tuple[JsonObject, tuple[str, ...]]:
    receipts = {capture.label: capture for capture in batch.captures}
    selected_groups = _selected_fixture_groups(batch.selected_fixtures)
    selected_fixture_keys = set(selected_groups)
    selected_mapping_statuses = _selected_fixture_mapping_statuses(batch)
    entries: list[JsonObject] = []
    valid_window_fixtures: dict[str, set[str]] = defaultdict(set)
    source_windows = batch.capture_windows
    if not source_windows:
        source_windows = tuple(
            {
                "capture_label": capture.label,
                **(
                    {"window_id": capture.label}
                    if _WINDOW_TOKEN.fullmatch(capture.label.upper())
                    else {}
                ),
            }
            for capture in batch.captures
        )
    receipt_use: Counter[str] = Counter()
    seen_window_requirements: set[tuple[str, str, str, str]] = set()
    for raw_entry in source_windows:
        entry = raw_entry
        capture_label_value = _temporal_alias(
            entry,
            ("capture_label", "capture_code", "capture", "label"),
        )
        capture_label = str(capture_label_value) if capture_label_value is not None else ""
        receipt = receipts.get(capture_label)
        receipt_claim = _temporal_alias(
            entry,
            ("receipt_id", "capture_receipt_id", "receipt"),
        )
        receipt_binding_conflict = receipt_claim is not None and (
            receipt is None or receipt.receipt_id != receipt_claim
        )
        window = _window_label(entry)
        role_value = entry.get("temporal_role")
        temporal_role = str(role_value).upper() if isinstance(role_value, str) else "UNSPECIFIED"
        fixture_claim = _temporal_alias(
            entry,
            ("fixture_id", "selected_fixture_id"),
        )
        provider_claim = _temporal_alias(
            entry,
            ("provider_event_id", "event_id"),
        )
        fixture_identity = fixture_claim or provider_claim or f"{capture_label}:{window or 'NA'}"
        if fixture_claim is not None and window is not None:
            requirement_identity = (
                capture_label,
                fixture_claim,
                temporal_role,
                window,
            )
            if requirement_identity in seen_window_requirements:
                raise SnapshotValidationError("TEMPORAL_WINDOW_IDENTITY_DUPLICATED")
            seen_window_requirements.add(requirement_identity)
        mapping_candidates = (
            [
                mapping
                for mapping in receipt.fixture_mappings
                if (fixture_claim is None or mapping.get("fixture_id") == fixture_claim)
                and (provider_claim is None or mapping.get("provider_event_id") == provider_claim)
            ]
            if receipt is not None and (fixture_claim is not None or provider_claim is not None)
            else []
        )
        fixture_mapping = mapping_candidates[0] if len(mapping_candidates) == 1 else None
        mapping_pair_conflict = (
            fixture_claim is not None and provider_claim is not None and fixture_mapping is None
        )
        receipt_mapping_status = (
            "FIXTURE_MAPPING_UNPROVEN"
            if fixture_mapping is None
            else str(fixture_mapping["status"])
        )
        selected_key = _selected_fixture_key(selected_groups, entry, fixture_mapping)
        mapping_status = (
            selected_mapping_statuses[selected_key]
            if selected_key is not None
            else receipt_mapping_status
        )
        earliest_value = _temporal_alias(
            entry,
            ("earliest_admissible", "window_start", "start"),
        )
        latest_value = _temporal_alias(
            entry,
            ("latest_admissible", "window_end", "end"),
        )
        kickoff = _temporal_alias(
            entry,
            ("kickoff", "kickoff_at", "commence_time"),
        )
        status: str
        observed: datetime | None = None
        earliest: datetime | None = None
        latest: datetime | None = None
        ingested: datetime | None = None
        available: datetime | None = None
        normalized_available_max: datetime | None = None
        normalized_row_count = 0
        availability_source: str | None = None
        window_contract_issue: str | None = None
        if receipt_binding_conflict:
            status = "WINDOW_RECEIPT_INVALID"
            window_contract_issue = "WINDOW_RECEIPT_BINDING_MISMATCH"
        elif receipt is None:
            status = "WINDOW_RECEIPT_INVALID"
        elif mapping_pair_conflict:
            status = "WINDOW_RECEIPT_INVALID"
            window_contract_issue = "WINDOW_FIXTURE_PROVIDER_PAIR_CONFLICT"
        elif mapping_status != "FIXTURE_MAPPING_PROVEN":
            status = "WINDOW_MAPPING_AMBIGUOUS"
            if selected_key is not None and mapping_status != receipt_mapping_status:
                window_contract_issue = "BATCH_WIDE_SELECTED_MAPPING_NOT_PROVEN"
        elif not _technical_raw_kickoff_bound(receipt, fixture_mapping, kickoff):
            status = "WINDOW_RECEIPT_INVALID"
            window_contract_issue = "TECHNICAL_RAW_EVENT_KICKOFF_NOT_FIXTURE_BOUND"
        elif earliest_value is None or latest_value is None or window is None:
            status = "WINDOW_NOT_APPLICABLE"
        else:
            observed = parse_utc(receipt.first_observed_at, code="TEMPORAL_OBSERVED_AT_INVALID")
            (
                available,
                normalized_available_max,
                normalized_row_count,
                availability_source,
                normalized_rows_bound,
            ) = _effective_market_available_at(
                receipt,
                fixture_identity,
                fixture_mapping,
                (rows_by_capture or {}).get(capture_label, []),
            )
            ingested = parse_utc(receipt.ingested_at, code="TEMPORAL_INGESTED_AT_INVALID")
            earliest = parse_utc(earliest_value, code="TEMPORAL_WINDOW_START_INVALID")
            latest = parse_utc(latest_value, code="TEMPORAL_WINDOW_END_INVALID")
            if latest < earliest:
                raise SnapshotValidationError("TEMPORAL_WINDOW_ORDER_INVALID")
            if not normalized_rows_bound:
                status = "WINDOW_RECEIPT_INVALID"
                window_contract_issue = "TECHNICAL_NORMALIZED_ROWS_NOT_FIXTURE_BOUND"
            else:
                status = (
                    "WINDOW_VALID"
                    if earliest <= observed <= latest and available <= latest and ingested <= latest
                    else "WINDOW_MISSED"
                )
        staleness_seconds: int | None = None
        cutoff_staleness_seconds: int | None = None
        derived_cutoff: datetime | None = None
        target_predictor_cutoff: datetime | None = None
        target_window_end: datetime | None = None
        if observed is not None and kickoff is not None:
            kickoff_at = parse_utc(kickoff, code="TEMPORAL_KICKOFF_INVALID")
            staleness_seconds = int((kickoff_at - observed).total_seconds())
            if window in {"H24", "H12", "H6", "H2", "H1"}:
                derived_cutoff = kickoff_at - timedelta(hours=int(window[1:]))
                cutoff_staleness_seconds = int((derived_cutoff - observed).total_seconds())
                maximum_staleness_minutes = {"H24": 120, "H2": 15}.get(window)
                if temporal_role == "PREDICTOR" and maximum_staleness_minutes is not None:
                    expected_earliest = derived_cutoff - timedelta(
                        minutes=maximum_staleness_minutes
                    )
                    if earliest != expected_earliest or latest != derived_cutoff:
                        status = "WINDOW_MISSED"
                        window_contract_issue = "PREDICTOR_WINDOW_BOUNDS_DIVERGE"
                if temporal_role == "TARGET":
                    target_contract = {
                        "H1": (timedelta(hours=2), timedelta(hours=1)),
                        "H2": (timedelta(hours=24), timedelta(hours=2)),
                    }.get(window)
                    if target_contract is None:
                        status = "WINDOW_MISSED"
                        window_contract_issue = "TARGET_WINDOW_ROLE_UNSUPPORTED"
                    else:
                        predictor_offset, target_offset = target_contract
                        target_predictor_cutoff = kickoff_at - predictor_offset
                        target_window_end = kickoff_at - target_offset + timedelta(minutes=5)
                        if status != "WINDOW_RECEIPT_INVALID":
                            if (
                                earliest is None
                                or latest is None
                                or earliest < target_predictor_cutoff
                                or latest != target_window_end
                            ):
                                status = "WINDOW_MISSED"
                                window_contract_issue = "TARGET_WINDOW_BOUNDS_DIVERGE"
                            elif (
                                available is None
                                or available <= target_predictor_cutoff
                                or available > target_window_end
                            ):
                                status = "WINDOW_MISSED"
                                window_contract_issue = (
                                    "TARGET_AVAILABLE_AT_OUTSIDE_ROLE_BOUND_WINDOW"
                                )
                            elif ingested is None or ingested > target_window_end:
                                status = "WINDOW_MISSED"
                                window_contract_issue = "TARGET_INGESTED_AT_AFTER_WINDOW_END"
        if status == "WINDOW_VALID" and window is not None:
            if selected_key is not None:
                valid_window_fixtures[f"{temporal_role}:{window}"].add(selected_key)
        if receipt is not None and status == "WINDOW_VALID":
            receipt_use[receipt.receipt_id] += 1
        entries.append(
            {
                "availability_source": availability_source,
                "available_at": utc_text(available) if available is not None else None,
                "capture_label": capture_label,
                "claimed_window": window,
                "derived_cutoff_at": (
                    utc_text(derived_cutoff) if derived_cutoff is not None else None
                ),
                "earliest_admissible": utc_text(earliest) if earliest is not None else None,
                "fixture_pseudonym": pseudonym("fixture", str(fixture_identity)),
                "kickoff": kickoff,
                "latest_admissible": utc_text(latest) if latest is not None else None,
                "mapping_status": mapping_status,
                "normalized_row_available_at_max": (
                    utc_text(normalized_available_max)
                    if normalized_available_max is not None
                    else None
                ),
                "normalized_row_count": normalized_row_count,
                "receipt_proof": (
                    {
                        "receipt_id": receipt.receipt_id,
                        "raw_payload_sha256": receipt.raw_payload_sha256,
                    }
                    if receipt is not None
                    else None
                ),
                "robin_first_observed_at": (
                    receipt.first_observed_at if receipt is not None else None
                ),
                "robin_ingested_at": receipt.ingested_at if receipt is not None else None,
                "staleness_seconds_at_cutoff": cutoff_staleness_seconds,
                "staleness_seconds_before_kickoff": staleness_seconds,
                "status": status,
                "target_predictor_cutoff_at": (
                    utc_text(target_predictor_cutoff)
                    if target_predictor_cutoff is not None
                    else None
                ),
                "target_window_end_at": (
                    utc_text(target_window_end) if target_window_end is not None else None
                ),
                "temporal_role": temporal_role,
                "window_contract_issue": window_contract_issue,
            }
        )
    mutualized = sum(count - 1 for count in receipt_use.values() if count > 1)
    statuses = Counter(str(item["status"]) for item in entries)
    valid_windows = {
        window
        for window, fixtures in valid_window_fixtures.items()
        if selected_fixture_keys and fixtures == selected_fixture_keys
    }
    report: JsonObject = {
        "artifact": "five-canary-temporal-coverage-v1",
        "claim_id": "DATA.FROZEN_SNAPSHOT.TEMPORAL_COVERAGE.V1.001",
        "entries": entries,
        "mutualized_window_count": mutualized,
        "role_bound_valid_windows": sorted(valid_windows),
        "schema_version": "robin-five-canary-temporal-coverage-v1",
        "status_counts": dict(sorted(statuses.items())),
        "verdict": (
            "FROZEN_SNAPSHOT_SYNTHETIC_TEMPORAL_CONTRACT_VALIDATED"
            if batch.batch_id == SYNTHETIC_BATCH_ID
            else "REAL_TEMPORAL_WINDOW_COVERAGE_PROFILED"
        ),
        "window_claims_backdated": 0,
        **_delivery_status(synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID),
    }
    return report, tuple(sorted(valid_windows))


def _protocol_window_requirements(experiment: dict[str, Any]) -> tuple[str, ...]:
    predictors: set[str] = set()
    targets: set[str] = set()
    cutoff = experiment.get("predictor_cutoff")
    if isinstance(cutoff, dict):
        value = cast(dict[str, Any], cutoff).get("cutoff_id")
        if isinstance(value, str):
            predictors.add(value.upper())
    target = experiment.get("target_window")
    if isinstance(target, dict):
        value = cast(dict[str, Any], target).get("target_window_id")
        if isinstance(value, str):
            targets.add(value.upper())
    owner = experiment.get("predictors")
    if isinstance(owner, list):
        for item in owner:
            predictors.update(_WINDOW_TOKEN.findall(str(item)))
    owner = experiment.get("targets")
    if isinstance(owner, list):
        for item in owner:
            targets.update(_WINDOW_TOKEN.findall(str(item)))
    identifier = str(experiment.get("experiment_id"))
    if identifier in {"RDS-EXP-V1-006", "RDS-EXP-V1-008", "RDS-EXP-V1-010"}:
        predictors.add("H24")
    if identifier == "RDS-EXP-V1-009":
        # PR57 freezes four snapshots, but names only the H24 and H2 anchors.
        # The two intermediate windows require a protocol successor and must not
        # be silently materialized as H12/H6 requirements.
        predictors.update({"H24", "H2"})
    return tuple(
        sorted(
            {f"PREDICTOR:{window}" for window in predictors}
            | {f"TARGET:{window}" for window in targets}
        )
    )


def _minimum_bookmakers(experiment: dict[str, Any]) -> JsonValue:
    value = experiment.get("minimum_bookmakers", 5)
    return cast(JsonValue, value)


def _sample_floor(experiment: dict[str, Any]) -> int:
    value = experiment.get("minimum_sample")
    if not isinstance(value, dict):
        raise SnapshotValidationError("PROTOCOL_MINIMUM_SAMPLE_INVALID")
    eligible = cast(dict[str, Any], value).get("eligible_units")
    if not isinstance(eligible, int) or isinstance(eligible, bool) or eligible <= 0:
        raise SnapshotValidationError("PROTOCOL_MINIMUM_SAMPLE_INVALID")
    return eligible


def _substantial_accumulation_gate_blocked(
    *,
    upstream_data_gate_blocked: bool,
    observed_markets: set[str],
    observed_windows: tuple[str, ...],
) -> bool:
    """Require common contract evidence before claiming a substantial campaign."""

    return (
        upstream_data_gate_blocked
        or _ACCUMULATION_REQUIRED_MARKET not in observed_markets
        or _ACCUMULATION_REQUIRED_WINDOW_ROLE not in observed_windows
    )


def _readiness(
    protocols: JsonObject,
    readiness_matrix: JsonObject,
    *,
    pipeline_observed_fixture_count: int,
    observed_windows: tuple[str, ...],
    observed_markets: set[str],
    data_gate_blocked: bool,
    synthetic_contract: bool = False,
) -> tuple[JsonObject, JsonObject]:
    data_gate_blocked = _substantial_accumulation_gate_blocked(
        upstream_data_gate_blocked=data_gate_blocked,
        observed_markets=observed_markets,
        observed_windows=observed_windows,
    )
    reported_data_gate_blocked = data_gate_blocked or synthetic_contract
    protocol_material = {key: value for key, value in protocols.items() if key != "content_sha256"}
    actual_protocol_sha256 = canonical_sha256(protocol_material)
    if (
        protocols.get("content_sha256") != PROTOCOL_SOURCE_SHA256
        or actual_protocol_sha256 != PROTOCOL_SOURCE_SHA256
    ):
        raise SnapshotValidationError("PROTOCOL_SOURCE_HASH_MISMATCH")
    protocol_experiments = [
        require_object(item, code="PROTOCOL_ENTRY_INVALID")
        for item in require_array(protocols.get("experiments"), code="PROTOCOLS_INVALID")
    ]
    protocol_identifiers = [str(item.get("experiment_id")) for item in protocol_experiments]
    if len(protocol_experiments) != 25 or len(set(protocol_identifiers)) != 25:
        raise SnapshotValidationError("PROTOCOL_25_EXACTLY_ONCE_REQUIRED")
    protocol_by_identifier = {
        str(experiment["experiment_id"]): experiment for experiment in protocol_experiments
    }
    for experiment in protocol_experiments:
        declared_protocol_hash = experiment.get("protocol_hash")
        material = {key: value for key, value in experiment.items() if key != "protocol_hash"}
        if declared_protocol_hash != canonical_sha256(material):
            raise SnapshotValidationError("PROTOCOL_ENTRY_HASH_MISMATCH")
    if (
        readiness_matrix.get("source_protocol_sha256") != PROTOCOL_SOURCE_SHA256
        or canonical_sha256(readiness_matrix) != READINESS_MATRIX_CANONICAL_SHA256
    ):
        raise SnapshotValidationError("READINESS_MATRIX_SOURCE_HASH_MISMATCH")
    experiments = [
        require_object(item, code="READINESS_MATRIX_ENTRY_INVALID")
        for item in require_array(
            readiness_matrix.get("experiments"), code="READINESS_MATRIX_INVALID"
        )
    ]
    identifiers = [str(item.get("experiment_id")) for item in experiments]
    if (
        len(experiments) != 25
        or len(set(identifiers)) != 25
        or set(identifiers) != set(protocol_identifiers)
    ):
        raise SnapshotValidationError("PROTOCOL_25_EXACTLY_ONCE_REQUIRED")
    results: list[JsonObject] = []
    by_id: dict[str, JsonObject] = {}
    settlement_labels_available = False
    protocol_eligible_fixture_count = 0
    for experiment in sorted(experiments, key=lambda item: str(item["experiment_id"])):
        identifier = str(experiment["experiment_id"])
        frozen_protocol = protocol_by_identifier[identifier]
        if frozen_protocol.get("hypothesis_id") != experiment.get("hypothesis_id"):
            raise SnapshotValidationError("READINESS_MATRIX_PROTOCOL_BINDING_MISMATCH")
        markets = [str(value) for value in cast(list[Any], experiment.get("markets", []))]
        required_market_tokens = set(markets)
        required_window_roles = _protocol_window_requirements(experiment)
        required_windows = sorted({value.partition(":")[2] for value in required_window_roles})
        sample_floor = _sample_floor(experiment)
        current_gate = experiment.get("current_data_gate")
        gates: list[str] = []
        if isinstance(current_gate, dict):
            values = cast(dict[str, Any], current_gate).get("convergence_gates", [])
            if isinstance(values, list):
                gates.extend(
                    str(value)
                    for value in values
                    if str(value) != "NO_MATERIALIZED_RECEIPT_BACKED_CAPTURE"
                )
        missing_markets = sorted(required_market_tokens - observed_markets)
        missing_window_roles = sorted(set(required_window_roles) - set(observed_windows))
        totals_proof_missing = any(value.startswith("totals:") for value in required_market_tokens)
        enriched_missing = any(
            fragment in gate for gate in gates for fragment in _ENRICHED_GATE_FRAGMENTS
        )
        exp010_design_gate_blocked = identifier == "RDS-EXP-V1-010" and any(
            "EXP010_RECEIPT_TIME_VS_MARKET_LAST_UPDATE_CLOCK_SEMANTICS" in gate for gate in gates
        )
        if exp010_design_gate_blocked:
            status = "DATA_GATE_BLOCKED"
        elif any("PROTOCOL_SUCCESSOR_REQUIRED" in gate for gate in gates):
            status = "PROTOCOL_SUCCESSOR_REQUIRED"
        elif identifier == "RDS-EXP-V1-020" or any(
            "DATA_NOT_PROSPECTIVELY_OBSERVABLE" in gate or "NO_ADMISSIBLE_VERSIONED_COACH" in gate
            for gate in gates
        ):
            status = "DATA_GATE_BLOCKED"
        elif reported_data_gate_blocked:
            status = "DATA_GATE_BLOCKED"
        elif enriched_missing:
            status = "MISSING_ENRICHED_SOURCE"
        elif missing_markets:
            status = "MARKET_COVERAGE_PARTIAL"
        elif totals_proof_missing:
            status = "MARKET_COVERAGE_PARTIAL"
        elif missing_window_roles:
            status = "WINDOW_COVERAGE_PARTIAL"
        elif not settlement_labels_available:
            status = "MISSING_SETTLEMENT_LABEL_SOURCE"
        elif (
            protocol_eligible_fixture_count < sample_floor
        ):  # pragma: no cover - future label source
            status = "MINIMUM_SAMPLE_NOT_REACHED"
        else:  # pragma: no cover - execution remains unauthorized in this mission
            status = "ACCUMULATION_STARTED"
        if status not in READINESS_STATUSES or status == "EXECUTABLE":
            raise SnapshotValidationError("PROTOCOL_READINESS_STATUS_INVALID")
        blockers = [
            *gates,
            *(["REAL_DATA_NOT_AVAILABLE"] if synthetic_contract else []),
            *[f"MISSING_MARKET:{value}" for value in missing_markets],
            *[f"MISSING_WINDOW_ROLE:{value}" for value in missing_window_roles],
            *(["TOTALS_COVERAGE_TO_BE_PROVEN"] if totals_proof_missing else []),
            "BOOKMAKER_GRAIN_PROTOCOL_INTERSECTION_NOT_PROVEN",
            "PR57_ROLE_BOUND_RECEIPT_CONTRACT_NOT_SATISFIED",
            "MISSING_SETTLEMENT_LABEL_SOURCE",
            f"MINIMUM_SAMPLE_REMAINING:{sample_floor}",
            "HOLDOUT_NOT_SEALED",
            "MODEL_SPECIFIC_POWER_ACCEPTANCE_NOT_PROVEN",
            "EXECUTION_AUTHORITY_ABSENT",
        ]
        row: JsonObject = {
            "blocking_gates": sorted(set(blockers)),
            "bookmaker_grain": cast(JsonValue, experiment.get("bookmaker_grain")),
            "coverage_fraction": _ratio(
                protocol_eligible_fixture_count,
                sample_floor,
                "protocol-eligible fixture after all roles, sources and labels",
            ),
            "experiment_id": identifier,
            "holdout_contract": {
                "holdout": cast(JsonValue, frozen_protocol.get("holdout")),
                "league_holdout": cast(JsonValue, frozen_protocol.get("league_holdout")),
                "season_holdout": cast(JsonValue, frozen_protocol.get("season_holdout")),
                "walk_forward": cast(JsonValue, frozen_protocol.get("walk_forward")),
            },
            "labels": cast(JsonValue, experiment.get("labels")),
            "league_grain": cast(JsonValue, experiment.get("league_grain")),
            "maximum_staleness": cast(JsonValue, experiment.get("maximum_staleness")),
            "metadata": cast(JsonValue, experiment.get("metadata")),
            "minimum_sample_contract": cast(JsonValue, experiment.get("minimum_sample")),
            "minimum_snapshots": cast(JsonValue, experiment.get("minimum_snapshots")),
            "minimum_snapshot_contract": cast(JsonValue, experiment.get("minimum_snapshots")),
            "next_required_accumulation": {
                "fixtures_remaining": sample_floor,
                "missing_markets": missing_markets,
                "missing_window_roles": missing_window_roles,
                "missing_windows": sorted(
                    {value.partition(":")[2] for value in missing_window_roles}
                ),
                "settlement_label_source": "append-only settled current-fixture outcome labels",
            },
            "observed_fixtures": (0 if synthetic_contract else pipeline_observed_fixture_count),
            "observed_window_roles": [] if synthetic_contract else list(observed_windows),
            "observed_windows": (
                []
                if synthetic_contract
                else sorted({value.partition(":")[2] for value in observed_windows})
            ),
            "pipeline_observation_fraction": _ratio(
                min(pipeline_observed_fixture_count, sample_floor),
                sample_floor,
                "uniquely mapped captured fixture; not an eligible protocol sample",
            ),
            "predictor_cutoff": cast(JsonValue, experiment.get("predictor_cutoff")),
            "protocol_eligible_fixtures": protocol_eligible_fixture_count,
            "required_bookmaker_grain": {
                "minimum_complete_bookmakers": _minimum_bookmakers(experiment),
                "unit": "fixture×bookmaker×receipt",
            },
            "required_label_source": "append-only settled current-fixture outcome labels",
            "required_labels": cast(JsonValue, experiment.get("labels")),
            "required_markets": markets,
            "required_metadata": cast(JsonValue, experiment.get("metadata", [])),
            "required_source_receipts": [
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
            ],
            "receipt_requirements": cast(JsonValue, experiment.get("receipt_requirements")),
            "required_timestamps": [
                "source_published_at",
                "robin_first_observed_at",
                "robin_ingested_at",
                "available_at",
            ],
            "required_windows": list(required_windows),
            "required_window_roles": list(required_window_roles),
            "settlement_requirements": cast(JsonValue, experiment.get("settlement_requirements")),
            "status": status,
            "synthetic_contract_observed_fixtures": (
                pipeline_observed_fixture_count if synthetic_contract else 0
            ),
            "target_window": cast(JsonValue, experiment.get("target_window")),
        }
        if identifier == "RDS-EXP-V1-009":
            minimum_snapshots = cast(dict[str, Any], experiment.get("minimum_snapshots", {}))
            predictor_snapshot_count = minimum_snapshots.get("predictor_snapshots")
            named_predictor_count = sum(
                value.startswith("PREDICTOR:") for value in required_window_roles
            )
            row["unfrozen_intermediate_predictor_windows"] = {
                "count": (
                    predictor_snapshot_count - named_predictor_count
                    if isinstance(predictor_snapshot_count, int)
                    and not isinstance(predictor_snapshot_count, bool)
                    else None
                ),
                "names": [],
                "status": "NOT_FROZEN_PROTOCOL_SUCCESSOR_REQUIRED",
            }
        results.append(row)
        by_id[identifier] = row

    status_counts = Counter(str(item["status"]) for item in results)
    readiness_verdicts = ["ZERO_PREMATURE_EXPERIMENT_EXECUTION"]
    if synthetic_contract:
        readiness_verdicts.extend(
            [
                "FROZEN_SNAPSHOT_SYNTHETIC_READINESS_CLASSIFIER_VALIDATED",
                "NO_EXPERIMENT_READINESS_CLAIMED",
            ]
        )
    else:
        readiness_verdicts.append("ROBIN_FIRST_25_EXPERIMENT_READINESS_REASSESSED")
    if reported_data_gate_blocked:
        readiness_verdicts.append("DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE")
    readiness: JsonObject = {
        "artifact": "experiment-readiness-gate-v1",
        "claim_id": "SCIENCE.FROZEN_SNAPSHOT.READINESS.V1.001",
        "executable_protocol_count": 0,
        "execution_count": 0,
        "experiment_readiness_status": (
            "NOT_ASSESSED_ON_REAL_DATA" if synthetic_contract else "ASSESSED_ON_REAL_DATA"
        ),
        "performance_selection_used": False,
        "pipeline_observed_fixture_count": (
            0 if synthetic_contract else pipeline_observed_fixture_count
        ),
        "protocol_eligible_fixture_count": protocol_eligible_fixture_count,
        "protocol_count": len(results),
        "protocol_source_sha256": PROTOCOL_SOURCE_SHA256,
        "protocols": results,
        "real_executable_experiment_count": 0,
        "real_readiness_claimed": not synthetic_contract,
        "schema_version": "robin-experiment-readiness-gate-v1",
        "status_counts": dict(sorted(status_counts.items())),
        "verdicts": readiness_verdicts,
        **_delivery_status(synthetic_contract=synthetic_contract),
    }
    candidates: list[JsonObject] = []
    if not reported_data_gate_blocked:
        for identifier in _CANDIDATE_IDS:
            protocol = by_id[identifier]
            floor = cast(dict[str, Any], protocol["coverage_fraction"])["denominator"]
            if not isinstance(floor, int):
                raise SnapshotValidationError("PROTOCOL_MINIMUM_SAMPLE_INVALID")
            fixtures_remaining = floor
            additional_source = (
                "versioned bookmaker identity registry"
                if identifier == "RDS-EXP-V1-007"
                else "official receipt-backed fixture identity and kickoff authority"
            )
            candidates.append(
                {
                    "accumulation_duration": {
                        "status": "TO_BE_SIZED_IN_PROSPECTIVE_DATA_ACCUMULATION_CAMPAIGN_V1",
                        "required_inputs": [
                            "league",
                            "eligible fixtures per week",
                            "season cadence",
                        ],
                    },
                    "capture_cost": {
                        "campaign_cost_status": "TO_BE_SIZED_FROM_REQUEST_MARKET_REGION_PLAN",
                        "fixture_cost_assignment": "FORBIDDEN_FIXTURES_MAY_BE_MUTUALIZED_IN_ONE_REQUEST",
                        "provider_cost_grain": "request×sport×region×market selection",
                        "provider_purchase_authorized": False,
                    },
                    "estimated_fixtures_required": fixtures_remaining,
                    "experiment_id": identifier,
                    "label_source": "append-only settled current-fixture outcome labels",
                    "main_gate": cast(str, protocol["status"]),
                    "remaining_windows": cast(
                        dict[str, Any], protocol["next_required_accumulation"]
                    )["missing_windows"],
                    "selection_basis": [
                        "single h2h predictor window",
                        "shared capture with sibling protocols",
                        "shortest contract distance without enriched sporting source",
                    ],
                    "supplementary_source": additional_source,
                }
            )
    accumulation_meaning = (
        "DATA_GATE_BLOCKED_NO_SUBSTANTIAL_CAPTURE_CLAIM"
        if reported_data_gate_blocked
        else "PIPELINE_CAN_CAPTURE_A_SUBSTANTIAL_PART_OF_REQUIRED_DATA_ONLY"
    )
    accumulation_verdict = (
        (
            "ZERO_ACCUMULATION_CANDIDATES_WITH_CLOSED_DATA_GATE"
            if synthetic_contract
            else "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE"
        )
        if reported_data_gate_blocked
        else "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED"
    )
    accumulation: JsonObject = {
        "artifact": "first-accumulation-candidates-v1",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "claim_id": "SCIENCE.FROZEN_SNAPSHOT.ACCUMULATION.V1.001",
        "economic_or_performance_ranking_used": False,
        "meaning": accumulation_meaning,
        "not_a_claim_of": ["hypothesis plausibility", "validation", "promotion"],
        "real_accumulation_claimed": False,
        "schema_version": "robin-first-accumulation-candidates-v1",
        "verdict": accumulation_verdict,
        **_delivery_status(synthetic_contract=synthetic_contract),
    }
    return readiness, accumulation


def _selected_fixture_mapping_counts(batch: VerifiedBatch) -> Counter[str]:
    """Classify mappings once at the selected-fixture grain across all captures."""

    return Counter(_selected_fixture_mapping_statuses(batch).values())


def profile_batch(
    batch: VerifiedBatch, protocols: JsonObject, readiness_matrix: JsonObject
) -> ProfileResult:
    partitions: dict[str, bytes] = {}
    coverage_entries: list[JsonObject] = []
    event_sets: dict[str, set[str]] = {}
    bookmaker_sets: dict[str, set[str]] = {}
    market_sets: dict[str, set[str]] = {}
    contract_market_sets: dict[str, set[str]] = {}
    rows_by_capture: dict[str, list[JsonObject]] = {}
    duplicates = 0
    all_events: set[str] = set()
    all_bookmakers: set[str] = set()
    event_bookmaker_total = 0
    market_objects: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    normalized_total = 0
    for capture in batch.captures:
        rows, duplicate_count = _capture_rows(capture)
        rows_by_capture[capture.label] = rows
        duplicates += duplicate_count
        content = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
        partitions[f"normalized/{capture.label}.jsonl"] = content
        coverage, events, bookmakers, markets, contract_markets = _capture_coverage(
            capture, rows, duplicate_count
        )
        coverage_entries.append(coverage)
        event_sets[capture.label] = events
        bookmaker_sets[capture.label] = bookmakers
        market_sets[capture.label] = markets
        contract_market_sets[capture.label] = contract_markets
        all_events.update(events)
        all_bookmakers.update(bookmakers)
        event_bookmaker_total += cast(int, coverage["event_bookmaker_occurrence_count"])
        objects = cast(dict[str, Any], coverage["market_object_counts"])
        counts = cast(dict[str, Any], coverage["outcome_counts"])
        market_objects.update({str(key): int(value) for key, value in objects.items()})
        outcomes.update({str(key): int(value) for key, value in counts.items()})
        normalized_total += len(rows)

    temporal_report, observed_windows = _temporal_report(batch, rows_by_capture)
    schema_report = _schema_report(batch, event_sets, bookmaker_sets, market_sets)
    mapping_counts = _selected_fixture_mapping_counts(batch)
    selected_count = sum(mapping_counts.values())
    uniquely_mapped = mapping_counts["FIXTURE_MAPPING_PROVEN"]
    ambiguous = (
        mapping_counts["FIXTURE_MAPPING_AMBIGUOUS"] + mapping_counts["FIXTURE_MAPPING_CONFLICT"]
    )
    if uniquely_mapped > selected_count:  # pragma: no cover - construction invariant
        raise SnapshotValidationError("MAPPED_FIXTURE_COUNT_EXCEEDS_SELECTED_FIXTURES")
    materialized_partition_row_count = sum(content.count(b"\n") for content in partitions.values())
    if normalized_total != materialized_partition_row_count:  # pragma: no cover - invariant
        raise SnapshotValidationError("NORMALIZED_PARTITION_ROW_COUNT_MISMATCH")
    temporal_counts = cast(dict[str, Any], temporal_report["status_counts"])
    credits = sum(int(capture.quota.get("requests_last") or 0) for capture in batch.captures)
    denominators: JsonObject = {
        "HTTP_request_count": len(batch.captures),
        "ambiguous_fixture_count": ambiguous,
        "billable_request_count": len(batch.captures),
        "capture_window_count": len(cast(list[Any], temporal_report["entries"])),
        "credit_count": credits,
        "event_bookmaker_occurrence_count": event_bookmaker_total,
        "event_count": sum(len(values) for values in event_sets.values()),
        "h2h_market_object_count": market_objects["h2h"],
        "h2h_outcome_count": outcomes["h2h"],
        "missed_window_count": int(temporal_counts.get("WINDOW_MISSED", 0)),
        "mutualized_window_count": cast(int, temporal_report["mutualized_window_count"]),
        "normalized_observation_count": normalized_total,
        "raw_payload_count": len({capture.raw_payload_sha256 for capture in batch.captures}),
        "receipt_count": len(batch.captures),
        "satisfied_window_count": int(temporal_counts.get("WINDOW_VALID", 0)),
        "selected_fixture_count": selected_count,
        "totals_market_object_count": market_objects["totals"],
        "totals_outcome_count": outcomes["totals"],
        "unique_bookmaker_count": len(all_bookmakers),
        "uniquely_mapped_fixture_count": uniquely_mapped,
    }
    quality: JsonObject = {
        "artifact": "five-canary-batch-quality-summary-v1",
        "batch_id": batch.batch_id,
        "capture_quality": coverage_entries,
        "claim_id": "DATA.FROZEN_SNAPSHOT.QUALITY.V1.001",
        "denominator_grains": {
            "HTTP_request_count": "HTTP request",
            "ambiguous_fixture_count": "unique selected fixture",
            "billable_request_count": "billable provider request",
            "capture_window_count": "fixture×claimed window requirement",
            "credit_count": "provider credit",
            "event_bookmaker_occurrence_count": "event×bookmaker×capture",
            "event_count": "provider event×capture",
            "h2h_market_object_count": "h2h market object×capture",
            "h2h_outcome_count": "h2h outcome×capture",
            "missed_window_count": "fixture×claimed window requirement",
            "mutualized_window_count": "additional window served by an existing receipt",
            "normalized_observation_count": "deduplicated capture×event×bookmaker×market×outcome×point",
            "raw_payload_count": "distinct content-addressed raw payload",
            "receipt_count": "admitted final receipt",
            "satisfied_window_count": "fixture×claimed window requirement",
            "selected_fixture_count": "unique selected fixture",
            "totals_market_object_count": "totals market object×capture",
            "totals_outcome_count": "totals outcome×capture",
            "unique_bookmaker_count": "unique bookmaker identity across batch",
            "uniquely_mapped_fixture_count": "unique selected fixture",
        },
        "denominators": denominators,
        "duplicate_counts": {
            "bookmaker_identity": sum(
                cast(int, item["duplicate_bookmaker_identity_count"]) for item in coverage_entries
            ),
            "market_identity": sum(
                cast(int, item["duplicate_market_identity_count"]) for item in coverage_entries
            ),
            "observation": duplicates,
            "outcome_identity": sum(
                cast(int, item["duplicate_outcome_identity_count"]) for item in coverage_entries
            ),
            "provider_event_identity": sum(
                cast(int, item["duplicate_provider_event_identity_count"])
                for item in coverage_entries
            ),
            "raw_payload_reference": len(batch.captures)
            - len({capture.raw_payload_sha256 for capture in batch.captures}),
            "receipt_id": 0,
        },
        "duplicate_observation_count": duplicates,
        "mapping_status_counts": dict(sorted(mapping_counts.items())),
        "network_calls": batch.network_attempts,
        "provider_calls": 0,
        "quality_limits": [
            *(
                [
                    "SYNTHETIC_TOTALS_CONTRACT_VALIDATED",
                    "REAL_TOTALS_COVERAGE_NOT_ASSESSED",
                    "NO_REAL_DATA_GENERALIZATION_FROM_SYNTHETIC_FIXTURES",
                ]
                if batch.batch_id == SYNTHETIC_BATCH_ID
                else [
                    "TOTALS_REAL_COVERAGE_OBSERVED_BOUNDED",
                    "TOTALS_COVERAGE_TO_BE_PROVEN",
                    "NO_SEASONAL_GENERALIZATION_FROM_FIVE_CANARIES",
                ]
            ),
        ],
        "raw_hash_verified_before_parse_count": len(batch.captures),
        "schema_version": "robin-five-canary-batch-quality-v1",
        "secret_reads": batch.secret_reads,
        "verdict": (
            "FROZEN_SNAPSHOT_SYNTHETIC_QUALITY_CONTRACT_VALIDATED"
            if batch.batch_id == SYNTHETIC_BATCH_ID
            else "FIVE_CANARY_BATCH_QUALITY_PROFILED"
        ),
        "real_capture_count": 0 if batch.batch_id == SYNTHETIC_BATCH_ID else len(batch.captures),
        "synthetic_capture_count": (
            len(batch.captures) if batch.batch_id == SYNTHETIC_BATCH_ID else 0
        ),
        **_delivery_status(synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID),
    }
    observed_markets = (
        set.intersection(*contract_market_sets.values()) if contract_market_sets else set()
    )
    upstream_data_gate_blocked = (
        schema_report["overall_classification"] == "BREAKING_SCHEMA_DRIFT" or uniquely_mapped == 0
    )
    data_gate_blocked = _substantial_accumulation_gate_blocked(
        upstream_data_gate_blocked=upstream_data_gate_blocked,
        observed_markets=observed_markets,
        observed_windows=observed_windows,
    )
    readiness, accumulation = _readiness(
        protocols,
        readiness_matrix,
        pipeline_observed_fixture_count=uniquely_mapped,
        observed_windows=observed_windows,
        observed_markets=observed_markets,
        data_gate_blocked=data_gate_blocked,
        synthetic_contract=batch.batch_id == SYNTHETIC_BATCH_ID,
    )
    receipt_index: JsonObject = {
        "batch_id": batch.batch_id,
        "receipts": [
            {
                "capture_label": capture.label,
                "delete_after": capture.delete_after,
                "mapping_revision": capture.mapping_revision,
                "mapping_statuses": list(capture.mapping_statuses),
                "normalized_partition_sha256": sha256_bytes(
                    partitions[f"normalized/{capture.label}.jsonl"]
                ),
                "raw_payload_sha256": capture.raw_payload_sha256,
                "receipt_id": capture.receipt_id,
                "request_fingerprint_sha256": capture.request_fingerprint_sha256,
                "schema_fingerprint_sha256": capture.schema_fingerprint_sha256,
            }
            for capture in batch.captures
        ],
        "schema_version": "robin-frozen-snapshot-receipt-index-v1",
    }
    return ProfileResult(
        normalized_partitions=partitions,
        receipt_index=receipt_index,
        quality_report=quality,
        schema_report=schema_report,
        temporal_report=temporal_report,
        readiness_report=readiness,
        accumulation_report=accumulation,
        denominators=denominators,
        observed_fixture_count=uniquely_mapped,
        observed_valid_windows=observed_windows,
        data_gate_blocked=data_gate_blocked,
    )
