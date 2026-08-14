"""Validate and score Robin data-source inventories without network access.

The command deliberately operates on local files only.  Acquisition, authentication,
and production activation are outside this mission.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

WEIGHTS: dict[str, int] = {
    "temporal_proof": 20,
    "scientific_value": 20,
    "coverage": 15,
    "stability": 10,
    "quality": 10,
    "legality_licence": 10,
    "cost": 5,
    "maintenance": 5,
    "integration": 5,
}

LEGAL_VETO_STATUSES = {
    "CONTRADICTORY",
    "CUSTOM_CONTRACT",
    "HIGH_RISK_CONDITIONAL",
    "NONCOMMERCIAL_RESTRICTED",
    "PARTIAL",
    "PROHIBITED_FOR_USE_CASE",
    "RESTRICTED",
    "UNCLEAR",
    "UNCLEAR_CONDITIONAL",
    "UNKNOWN",
}

REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "name",
    "publisher",
    "official_url",
    "access_type",
    "licence_terms",
    "commercial_use",
    "history_available",
    "league_coverage",
    "season_coverage",
    "frequency",
    "latency",
    "timestamps_provided",
    "raw_payload_retention",
    "stable_identifiers",
    "quality",
    "schema_change_risk",
    "initial_cost",
    "monthly_cost",
    "api_limits",
    "human_maintenance",
    "scientific_value",
    "source_class",
    "family_coverage",
    "scores",
    "score_rationales",
}


class InventoryError(ValueError):
    """Raised when an inventory violates the source-scoring contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def score_source(source: Mapping[str, Any]) -> int:
    """Validate one candidate and return its weighted score out of 100."""
    missing = sorted(REQUIRED_SOURCE_FIELDS - source.keys())
    if missing:
        raise InventoryError(f"{source.get('source_id', '<unknown>')}: missing {missing}")

    source_class = source["source_class"]
    if source_class not in {"A", "B", "C", "D"}:
        raise InventoryError(f"{source['source_id']}: source_class must be A, B, C, or D")

    licence_terms = source["licence_terms"]
    if not isinstance(licence_terms, Mapping):
        raise InventoryError(f"{source['source_id']}: licence_terms must be an object")
    licence_status = licence_terms.get("status")
    if not isinstance(licence_status, str) or not licence_status:
        raise InventoryError(f"{source['source_id']}: licence_terms.status is required")
    if licence_status in LEGAL_VETO_STATUSES and source_class != "D":
        raise InventoryError(
            f"{source['source_id']}: licence status {licence_status} requires class D"
        )

    scores = source["scores"]
    rationales = source["score_rationales"]
    if not isinstance(scores, Mapping) or set(scores) != set(WEIGHTS):
        raise InventoryError(f"{source['source_id']}: scores must contain the nine criteria")
    if not isinstance(rationales, Mapping) or set(rationales) != set(WEIGHTS):
        raise InventoryError(
            f"{source['source_id']}: score_rationales must contain the nine criteria"
        )

    total = 0
    for criterion, maximum in WEIGHTS.items():
        value = scores[criterion]
        if isinstance(value, bool) or not isinstance(value, int):
            raise InventoryError(f"{source['source_id']}: {criterion} must be an integer")
        if not 0 <= value <= maximum:
            raise InventoryError(
                f"{source['source_id']}: {criterion}={value} is outside 0..{maximum}"
            )
        rationale = rationales[criterion]
        if not isinstance(rationale, str) or not rationale.strip():
            raise InventoryError(f"{source['source_id']}: {criterion} needs a rationale")
        total += value
    return total


def build_scorecard(inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic global, historical, prospective, and exclusion rankings."""
    raw_sources = inventory.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes)):
        raise InventoryError("inventory.sources must be an array")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, Mapping):
            raise InventoryError("each source must be an object")
        source_id = raw_source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise InventoryError("each source_id must be a non-empty string")
        if source_id in seen:
            raise InventoryError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        total = score_source(raw_source)
        rows.append(
            {
                "source_id": source_id,
                "name": raw_source["name"],
                "source_class": raw_source["source_class"],
                "total": total,
                "scores": dict(raw_source["scores"]),
                "score_rationales": dict(raw_source["score_rationales"]),
            }
        )

    ranked = sorted(rows, key=lambda row: (-row["total"], row["source_id"]))
    admissible = [row for row in ranked if row["source_class"] != "D"]
    historical = [row for row in ranked if row["source_class"] in {"A", "B"}]
    prospective = [row for row in ranked if row["source_class"] == "C"]
    exclusions = [row for row in ranked if row["source_class"] == "D"]
    return {
        "schema_version": "1.0.0",
        "generated_from": inventory.get("inventory_id"),
        "source_inventory_fingerprint": hashlib.sha256(
            _canonical_json(inventory).encode("utf-8")
        ).hexdigest(),
        "source_count": len(ranked),
        "costs_verified_at": inventory.get("costs_verified_at"),
        "class_counts": {
            source_class: sum(row["source_class"] == source_class for row in ranked)
            for source_class in ("A", "B", "C", "D")
        },
        "weights": WEIGHTS,
        "scoring_method": "sum of nine bounded integer criteria; deterministic tie-break by source_id",
        "hard_gate": "Class D remains excluded regardless of numerical score.",
        "ranked_sources": ranked,
        "top_5_global": admissible[:5],
        "top_3_historical": historical[:3],
        "top_3_prospective": prospective[:3],
        "excluded_sources": exclusions,
    }


def _csv_profile(path: Path) -> tuple[int, list[dict[str, str]], str | None, str | None]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        rows = list(reader)
    schema = [{"name": field, "type": "string"} for field in fields]
    event_field = next((field for field in ("Date", "date", "utcDate") if field in fields), None)
    raw_events = [row[event_field] for row in rows if event_field and row.get(event_field)]
    events = [_normalise_event_time(value) for value in raw_events]
    return len(rows), schema, (min(events) if events else None), (max(events) if events else None)


def _normalise_event_time(value: str) -> str:
    """Normalise common public-dataset dates before min/max comparisons."""
    for date_format in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, date_format)
        except ValueError:
            continue
        return parsed.isoformat(timespec="seconds") if "T" in value else parsed.date().isoformat()
    return value


def _json_profile(path: Path) -> tuple[int, list[dict[str, str]], str | None, str | None]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        rows = [payload]
    keys = sorted({str(key) for row in rows if isinstance(row, dict) for key in row})
    schema = [{"name": key, "type": "json"} for key in keys]
    candidates = ("match_date", "date", "utcDate", "match_available", "match_updated")
    event_field = next((field for field in candidates if field in keys), None)
    events = [
        str(row[event_field])
        for row in rows
        if event_field and isinstance(row, dict) and row.get(event_field) is not None
    ]
    return len(rows), schema, (min(events) if events else None), (max(events) if events else None)


def profile_sample(
    path: Path,
    *,
    source_id: str,
    request_url: str,
    downloaded_at: str,
    status_http: int,
    licence_note: str,
) -> dict[str, Any]:
    """Produce a receipt-like profile for a small already-downloaded public sample."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        row_count, schema, first_event, last_event = _csv_profile(path)
    elif suffix == ".json":
        row_count, schema, first_event, last_event = _json_profile(path)
    else:
        raise InventoryError(f"unsupported sample format: {suffix}")
    payload = path.read_bytes()
    return {
        "source_id": source_id,
        "downloaded_at": downloaded_at,
        "request_url": request_url,
        "status_http": status_http,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "schema_fingerprint": hashlib.sha256(_canonical_json(schema).encode()).hexdigest(),
        "row_count": row_count,
        "first_event": first_event,
        "last_event": last_event,
        "licence_note": licence_note,
    }


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InventoryError(f"{path}: expected a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    score = subparsers.add_parser("score", help="validate an inventory and write its scorecard")
    score.add_argument("--inventory", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)

    profile = subparsers.add_parser("profile-sample", help="profile a local CSV or JSON sample")
    profile.add_argument("--path", type=Path, required=True)
    profile.add_argument("--source-id", required=True)
    profile.add_argument("--request-url", required=True)
    profile.add_argument("--downloaded-at", required=True)
    profile.add_argument("--status-http", type=int, required=True)
    profile.add_argument("--licence-note", required=True)
    profile.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "score":
        _write_json(args.output, build_scorecard(_read_json(args.inventory)))
        return 0
    receipt = profile_sample(
        args.path,
        source_id=args.source_id,
        request_url=args.request_url,
        downloaded_at=args.downloaded_at,
        status_http=args.status_http,
        licence_note=args.licence_note,
    )
    if args.output:
        _write_json(args.output, receipt)
    else:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
