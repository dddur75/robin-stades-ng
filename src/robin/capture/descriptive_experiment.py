"""Independent, bounded recalculation for the frozen Robin descriptive pair."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

MISSION_ID = "ROBIN_SIMPLIFICATION_EXPLORATION_20261005"
SOURCE_MISSION_ID = "ROBIN_AUTONOMOUS_LAB_20261004"
QUESTION = (
    "Quelles offres ont changé de prix entre ces deux acquisitions, et comment ces "
    "changements se répartissent-ils par ligue, bookmaker et marché ?"
)
IDENTITY_FIELDS = (
    "sport_key",
    "event_id",
    "bookmaker_key",
    "market_key",
    "outcome",
    "point",
)
_VALID_BRANCH_STATUSES = frozenset({"COMPLETE", "PARTIAL"})


class ExperimentInputError(ValueError):
    """Fail-closed validation error for a frozen experiment input."""


@dataclass(frozen=True, slots=True)
class VerifiedBundle:
    root: Path
    report: Mapping[str, object]
    receipt: Mapping[str, object]
    report_sha256: str


def _fail(code: str) -> None:
    raise ExperimentInputError(code)


def _parse_utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))
    except ValueError:
        _fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed


def _mapping(value: object, *, code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _fail(code)
    return cast(Mapping[str, object], value)


def _rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = report.get("rows")
    if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
        _fail("SOURCE_ROWS_INVALID")
    return cast(list[Mapping[str, object]], raw)


def _load_json_object(payload: bytes, *, code: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    return _mapping(parsed, code=code)


def load_verified_bundle(root: Path) -> VerifiedBundle:
    """Read one normalized artifact and bind its public receipt fail-closed."""

    receipt_path = root / "public-receipt.json"
    report_path = root / "robin-real-data.json"
    try:
        receipt_bytes = receipt_path.read_bytes()
        report_bytes = report_path.read_bytes()
    except OSError:
        _fail("SOURCE_FILE_MISSING")
    receipt = _load_json_object(receipt_bytes, code="SOURCE_RECEIPT_INVALID")
    report = _load_json_object(report_bytes, code="SOURCE_REPORT_INVALID")
    report_hash = hashlib.sha256(report_bytes).hexdigest()

    if receipt.get("schema_version") != "robin-autonomous-lab-public-receipt-v1":
        _fail("SOURCE_RECEIPT_SCHEMA_INVALID")
    if receipt.get("normalized_json_sha256") != report_hash:
        _fail("SOURCE_HASH_MISMATCH")
    if report.get("schema_version") != "robin-real-data-dashboard-v1":
        _fail("SOURCE_REPORT_SCHEMA_INVALID")
    if receipt.get("mission_id") != SOURCE_MISSION_ID:
        _fail("SOURCE_MISSION_INVALID")
    if report.get("mission_id") != SOURCE_MISSION_ID:
        _fail("SOURCE_MISSION_INVALID")
    if receipt.get("github_run_id") != report.get("github_run_id"):
        _fail("SOURCE_RUN_ID_MISMATCH")
    if receipt.get("slot_start_utc") != report.get("slot_start_utc"):
        _fail("SOURCE_SLOT_MISMATCH")
    if receipt.get("display_data_slot_start_utc") != report.get("data_slot_start_utc"):
        _fail("SOURCE_DISPLAY_SLOT_MISMATCH")
    if receipt.get("display_data_role") != "CURRENT" or report.get("data_role") != "CURRENT":
        _fail("SOURCE_NOT_CURRENT_ACQUISITION")
    if receipt.get("private_report_r2_status") != "VERIFIED":
        _fail("SOURCE_R2_READBACK_UNVERIFIED")
    if receipt.get("replayed_existing_slot") is not False:
        _fail("SOURCE_REPLAY_NOT_ACQUISITION")

    rows = _rows(report)
    summary = _mapping(report.get("summary"), code="SOURCE_SUMMARY_INVALID")
    if receipt.get("row_count") != len(rows) or summary.get("row_count") != len(rows):
        _fail("SOURCE_ROW_COUNT_MISMATCH")
    _parse_utc(report.get("slot_start_utc"), code="SOURCE_SLOT_INVALID")
    return VerifiedBundle(root=root, report=report, receipt=receipt, report_sha256=report_hash)


def _coverage_sports(bundle: VerifiedBundle) -> set[str]:
    coverage = _mapping(bundle.report.get("coverage"), code="SOURCE_COVERAGE_INVALID")
    return {
        key for key, value in coverage.items() if isinstance(key, str) and isinstance(value, dict)
    }


def _eligible_sports(bundle: VerifiedBundle) -> set[str]:
    rows = _rows(bundle.report)
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        sport = row.get("sport_key")
        if isinstance(sport, str):
            grouped[sport].append(row)
    eligible: set[str] = set()
    for sport in _coverage_sports(bundle):
        branch_rows = grouped.get(sport, [])
        if not branch_rows:
            continue
        if any(row.get("branch_status") not in _VALID_BRANCH_STATUSES for row in branch_rows):
            continue
        times: set[datetime] = set()
        try:
            for row in branch_rows:
                times.add(
                    _parse_utc(row.get("capture_time_utc"), code="SOURCE_CAPTURE_TIME_INVALID")
                )
        except ExperimentInputError:
            continue
        if len(times) == 1:
            eligible.add(sport)
    return eligible


def _identity(row: Mapping[str, object]) -> tuple[object, ...] | None:
    required = tuple(row.get(field) for field in IDENTITY_FIELDS[:-1])
    if any(not isinstance(value, str) or not value.strip() for value in required):
        return None
    market = cast(str, row.get("market_key"))
    point = row.get("point")
    if market == "h2h":
        if point is not None:
            return None
    elif market == "totals":
        if (
            not isinstance(point, (int, float))
            or isinstance(point, bool)
            or not math.isfinite(float(point))
        ):
            return None
        point = float(point)
    else:
        return None
    return (*required, point)


def _price(row: Mapping[str, object]) -> float | None:
    raw = row.get("price")
    if (
        not isinstance(raw, (int, float))
        or isinstance(raw, bool)
        or not math.isfinite(float(raw))
        or float(raw) <= 0
    ):
        return None
    return float(raw)


def _branch_times(bundle: VerifiedBundle, sport: str) -> list[datetime]:
    return [
        _parse_utc(row.get("capture_time_utc"), code="SOURCE_CAPTURE_TIME_INVALID")
        for row in _rows(bundle.report)
        if row.get("sport_key") == sport
    ]


def _breakdown(rows: Sequence[Mapping[str, object]], field: str) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        key = row.get(field)
        if isinstance(key, str):
            grouped[key].append(row)
    result: list[dict[str, object]] = []
    for key, group in sorted(grouped.items()):
        deltas = [abs(cast(float, row["delta"])) for row in group]
        changed = sum(row["direction"] != "UNCHANGED" for row in group)
        result.append(
            {
                "key": key,
                "matched_offer_count": len(group),
                "distinct_match_count": len({row.get("event_id") for row in group}),
                "changed_offer_count": changed,
                "changed_proportion": round(changed / len(group), 6),
                "up_count": sum(row["direction"] == "UP" for row in group),
                "down_count": sum(row["direction"] == "DOWN" for row in group),
                "unchanged_count": sum(row["direction"] == "UNCHANGED" for row in group),
                "mean_absolute_delta": round(sum(deltas) / len(deltas), 6),
            }
        )
    return result


def _sample(row: Mapping[str, object]) -> dict[str, object]:
    return {
        field: row.get(field)
        for field in (
            "sport_key",
            "event_id",
            "match",
            "bookmaker_key",
            "market_key",
            "outcome",
            "point",
            "previous_price",
            "current_price",
            "previous_slot_start_utc",
            "current_slot_start_utc",
            "previous_capture_time_utc",
            "current_capture_time_utc",
            "previous_source_timestamp_utc",
            "current_source_timestamp_utc",
            "delta",
            "direction",
        )
    }


def calculate_descriptive_experiment(
    previous: VerifiedBundle, current: VerifiedBundle
) -> dict[str, object]:
    """Recalculate movements without importing or calling the interface engine."""

    previous_slot = _parse_utc(previous.report.get("slot_start_utc"), code="SOURCE_SLOT_INVALID")
    current_slot = _parse_utc(current.report.get("slot_start_utc"), code="SOURCE_SLOT_INVALID")
    if current_slot <= previous_slot:
        _fail("ACQUISITION_ORDER_INVALID")
    if previous.report.get("github_run_id") == current.report.get("github_run_id"):
        _fail("ACQUISITIONS_NOT_DISTINCT")

    common = _eligible_sports(previous) & _eligible_sports(current)
    comparable_sports = {
        sport
        for sport in common
        if max(_branch_times(previous, sport)) < min(_branch_times(current, sport))
    }
    previous_rows = _rows(previous.report)
    current_rows = _rows(current.report)
    excluded: list[tuple[str, Mapping[str, object]]] = []
    grouped: dict[str, dict[tuple[object, ...], list[Mapping[str, object]]]] = {
        "previous": defaultdict(list),
        "current": defaultdict(list),
    }
    invalid_price_keys: set[tuple[object, ...]] = set()

    for side, rows in (("previous", previous_rows), ("current", current_rows)):
        for row in rows:
            if row.get("sport_key") not in comparable_sports:
                excluded.append(("BRANCH_NOT_COMPARABLE", row))
                continue
            key = _identity(row)
            if key is None:
                excluded.append(("INVALID_OFFER_IDENTITY", row))
                continue
            grouped[side][key].append(row)
            if _price(row) is None:
                invalid_price_keys.add(key)

    ambiguous_keys = {
        key for side in grouped.values() for key, rows in side.items() if len(rows) != 1
    }
    contaminated = ambiguous_keys | invalid_price_keys
    for key in contaminated:
        reason = "AMBIGUOUS_OFFER_IDENTITY" if key in ambiguous_keys else "INVALID_PRICE"
        for side_rows in grouped.values():
            excluded.extend((reason, row) for row in side_rows.pop(key, []))

    previous_by_key = grouped["previous"]
    current_by_key = grouped["current"]
    matched_rows: list[dict[str, object]] = []
    for key in sorted(previous_by_key.keys() & current_by_key.keys(), key=repr):
        before = previous_by_key[key][0]
        after = current_by_key[key][0]
        old_price = cast(float, _price(before))
        new_price = cast(float, _price(after))
        delta = round(new_price - old_price, 12)
        direction = "UNCHANGED"
        if not math.isclose(delta, 0.0, rel_tol=0.0, abs_tol=1e-12):
            direction = "UP" if delta > 0 else "DOWN"
        matched_rows.append(
            {
                "sport_key": after.get("sport_key"),
                "event_id": after.get("event_id"),
                "match": after.get("match"),
                "bookmaker_key": after.get("bookmaker_key"),
                "market_key": after.get("market_key"),
                "outcome": after.get("outcome"),
                "point": after.get("point"),
                "previous_price": old_price,
                "current_price": new_price,
                "previous_slot_start_utc": before.get("slot_start_utc"),
                "current_slot_start_utc": after.get("slot_start_utc"),
                "previous_capture_time_utc": before.get("capture_time_utc"),
                "current_capture_time_utc": after.get("capture_time_utc"),
                "previous_source_timestamp_utc": before.get("source_timestamp_utc"),
                "current_source_timestamp_utc": after.get("source_timestamp_utc"),
                "delta": delta,
                "direction": direction,
            }
        )

    appeared_keys = current_by_key.keys() - previous_by_key.keys()
    missing_keys = previous_by_key.keys() - current_by_key.keys()
    directions = Counter(cast(str, row["direction"]) for row in matched_rows)
    changed = directions["UP"] + directions["DOWN"]
    magnitudes = [abs(cast(float, row["delta"])) for row in matched_rows]
    samples = sorted(
        (row for row in matched_rows if row["direction"] != "UNCHANGED"),
        key=lambda row: (-abs(cast(float, row["delta"])), repr(_sample(row))),
    )[:12]
    reason_counts = Counter(reason for reason, _row in excluded)
    return {
        "matched_offer_count": len(matched_rows),
        "changed_offer_count": changed,
        "changed_proportion": round(changed / len(matched_rows), 6) if matched_rows else 0.0,
        "direction_counts": {
            "UP": directions["UP"],
            "DOWN": directions["DOWN"],
            "UNCHANGED": directions["UNCHANGED"],
        },
        "mean_absolute_delta": round(sum(magnitudes) / len(magnitudes), 6) if magnitudes else 0.0,
        "median_absolute_delta": round(statistics.median(magnitudes), 6) if magnitudes else 0.0,
        "maximum_absolute_delta": round(max(magnitudes), 6) if magnitudes else 0.0,
        "appeared_offer_count": len(appeared_keys),
        "not_observed_offer_count": len(missing_keys),
        "excluded_row_count": len(excluded),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "comparable_sport_keys": sorted(comparable_sports),
        "breakdowns": {
            "league": _breakdown(matched_rows, "sport_key"),
            "bookmaker": _breakdown(matched_rows, "bookmaker_key"),
            "market": _breakdown(matched_rows, "market_key"),
        },
        "source_samples": [_sample(row) for row in samples],
    }


def _input_summary(bundle: VerifiedBundle) -> dict[str, object]:
    canonical_receipt = (
        json.dumps(bundle.receipt, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return {
        "github_run_id": str(bundle.report["github_run_id"]),
        "slot_start_utc": bundle.report["slot_start_utc"],
        "repository_sha": bundle.report.get("repository_sha"),
        "normalized_json_sha256": bundle.report_sha256,
        "source_receipt_sha256": hashlib.sha256(canonical_receipt).hexdigest(),
        "receipt_hash_normalization": "CANONICAL_SORTED_JSON_WITH_LF",
        "row_count": len(_rows(bundle.report)),
        "validated_capture_count": bundle.receipt.get("validated_capture_count"),
        "private_report_r2_status": bundle.receipt.get("private_report_r2_status"),
        "replayed_existing_slot": bundle.receipt.get("replayed_existing_slot"),
    }


def _finding_sources(
    result: Mapping[str, object], key: str | None = None
) -> list[Mapping[str, object]]:
    samples = cast(list[Mapping[str, object]], result["source_samples"])
    if key is None:
        return samples[:3]
    filtered = [
        sample
        for sample in samples
        if key
        in {
            sample.get("sport_key"),
            sample.get("market_key"),
            sample.get("bookmaker_key"),
        }
    ]
    return filtered[:3] or samples[:1]


def _findings(
    result: Mapping[str, object], inputs: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    breakdowns = cast(Mapping[str, list[Mapping[str, object]]], result["breakdowns"])
    league = max(
        breakdowns["league"],
        key=lambda item: (cast(float, item["changed_proportion"]), cast(str, item["key"])),
    )
    market = max(
        breakdowns["market"],
        key=lambda item: (cast(int, item["changed_offer_count"]), cast(str, item["key"])),
    )
    capture_ids = [item["github_run_id"] for item in inputs]
    return [
        {
            "finding_id": "F1_OVERALL_MOVEMENT",
            "text": (
                f"{result['changed_offer_count']} offres sur {result['matched_offer_count']} "
                f"appariées ont changé ({100 * cast(float, result['changed_proportion']):.2f} %)."
            ),
            "captures": capture_ids,
            "perimeter": {
                "matched_offer_count": result["matched_offer_count"],
                "comparable_sport_keys": result["comparable_sport_keys"],
            },
            "source_rows": _finding_sources(result),
            "limitation": "Les offres d'un même match ou bookmaker ne sont pas indépendantes.",
        },
        {
            "finding_id": "F2_LEAGUE_CONCENTRATION",
            "text": (
                f"{league['key']} présente la plus forte proportion descriptive de "
                f"changements: {league['changed_offer_count']} sur "
                f"{league['matched_offer_count']} offres appariées."
            ),
            "captures": capture_ids,
            "perimeter": dict(league),
            "source_rows": _finding_sources(result, cast(str, league["key"])),
            "limitation": "Ce maximum observé ne constitue ni un classement prédictif ni un edge.",
        },
        {
            "finding_id": "F3_MARKET_DISTRIBUTION",
            "text": (
                f"Le marché {market['key']} concentre {market['changed_offer_count']} "
                f"changements sur {market['matched_offer_count']} offres appariées."
            ),
            "captures": capture_ids,
            "perimeter": dict(market),
            "source_rows": _finding_sources(result, cast(str, market["key"])),
            "limitation": "La comparaison est descriptive et ne mesure ni rentabilité ni causalité.",
        },
    ]


def build_experiment_report(
    previous: VerifiedBundle,
    current: VerifiedBundle,
    *,
    shared_reference: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = calculate_descriptive_experiment(previous, current)
    inputs = [_input_summary(previous), _input_summary(current)]
    keys = (
        "matched_offer_count",
        "changed_offer_count",
        "appeared_offer_count",
        "not_observed_offer_count",
        "excluded_row_count",
    )
    reconciled = shared_reference is not None and all(
        shared_reference.get(key) == result.get(key) for key in keys
    )
    breakdowns_reconciled = shared_reference is not None and shared_reference.get(
        "breakdowns"
    ) == result.get("breakdowns")
    shared_rows = shared_reference.get("matched_offers", []) if shared_reference is not None else []
    sample_fields = (
        "sport_key",
        "event_id",
        "bookmaker_key",
        "market_key",
        "outcome",
        "point",
        "previous_price",
        "current_price",
        "delta",
        "direction",
    )
    samples_reconciled = isinstance(shared_rows, list) and all(
        any(
            isinstance(shared_row, dict)
            and all(shared_row.get(field) == sample.get(field) for field in sample_fields)
            for shared_row in shared_rows
        )
        for sample in cast(list[Mapping[str, object]], result["source_samples"])
    )
    generated_at = (
        current.receipt.get("delivery_generated_at_utc")
        or current.report.get("generated_at_utc")
        or current.report["slot_start_utc"]
    )
    return {
        "schema_version": "robin-descriptive-experiment-v1",
        "mission_id": MISSION_ID,
        "question": QUESTION,
        "generated_at_utc": generated_at,
        "scientific_notice": "DESCRIPTIVE_EXPOSED_NO_EDGE_NO_CAUSALITY",
        "frozen_inputs": inputs,
        "comparison_contract": {
            "offer_identity_fields": list(IDENTITY_FIELDS),
            "variation_definition": "current_price - previous_price",
            "delta_precision_decimals": 12,
            "aggregate_precision_decimals": 6,
            "denominator": "exact unique offers observed in both ordered valid branches",
            "branch_rule": "same sport present, valid and strictly ordered in both acquisitions",
            "missing_rule": "not observed in the later acquisition; supplier withdrawal not inferred",
            "source_and_period_assumption": (
                "same authorized collector/provider and full-game market contract; these fields are "
                "not explicit in the normalized rows"
            ),
        },
        "result": result,
        "findings": _findings(result, inputs),
        "research_questions": [
            "Les proportions de mouvement diffèrent-elles de façon reproductible entre ligues sur des acquisitions futures indépendantes ?",
            "Les mouvements H2H et totals persistent-ils aux mêmes horizons sans sélectionner les fenêtres après observation ?",
        ],
        "limitations": [
            "The 08:00Z-10:00Z pair was exposed to exploration and cannot validate an edge.",
            "Provider identity, settlement period and branch acquisition start/end are not explicit in normalized rows.",
            "A missing offer means not observed in this valid acquisition, not proven supplier withdrawal.",
            "GitHub artifacts expire; immutable R2 readback remains the durable source attested by each receipt.",
        ],
        "qa": {
            "calculator": "src/robin/capture/descriptive_experiment.py",
            "independent_from_interface": True,
            "shared_totals_reconciled": reconciled,
            "shared_breakdowns_reconciled": breakdowns_reconciled,
            "source_samples_reconciled": samples_reconciled,
            "reconciled_fields": list(keys),
            "source_hashes_verified": True,
            "branch_order_verified": True,
            "source_sample_count": len(cast(list[object], result["source_samples"])),
        },
        "external_effects": {
            "provider_http_requests_new": 0,
            "provider_credits_new": 0,
            "r2_reads_new": 0,
            "r2_writes_new": 0,
        },
    }


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")
