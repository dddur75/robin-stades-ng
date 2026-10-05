"""Self-contained operational dashboard for verified Robin observations."""

from __future__ import annotations

import csv
import html
import io
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from robin.capture.contracts import CaptureContractError, ensure_utc
from robin.capture.real_data_result import MARKETS, SPORT_KEYS
from robin.capture.recurring_real_data import RECURRING_CLAIM_IDS, SEED_CLAIM_IDS

FRESHNESS_LIMIT_SECONDS = 3 * 60 * 60
_PUBLIC_ACCOUNTING_FIELDS = (
    "rolling_24h_requests",
    "rolling_24h_credits",
    "rolling_30d_requests",
    "rolling_30d_credits",
    "lifetime_requests",
    "lifetime_credits",
    "provider_remaining_floor",
)
_ROW_FIELDS = (
    "slot_start_utc",
    "sport_key",
    "capture_time_utc",
    "source_timestamp_utc",
    "event_id",
    "match",
    "kickoff_utc",
    "bookmaker_key",
    "bookmaker",
    "market_key",
    "outcome",
    "point",
    "price",
    "quota_remaining",
)
_PUBLIC_CSV_FIELDS = _ROW_FIELDS + ("branch_status",)
_ALLOWED_CLAIM_IDS = frozenset((*RECURRING_CLAIM_IDS, *SEED_CLAIM_IDS))


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("DASHBOARD_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ensure_utc(parsed, field="dashboard_time")
    except (CaptureContractError, ValueError):
        raise ValueError("DASHBOARD_TIME_INVALID") from None


def _iso_z(value: datetime) -> str:
    return ensure_utc(value, field="dashboard_generated_at").isoformat().replace("+00:00", "Z")


def _rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = report.get("rows")
    if not isinstance(raw, list):
        raise ValueError("DASHBOARD_ROWS_INVALID")
    result: list[Mapping[str, object]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("DASHBOARD_ROWS_INVALID")
        result.append(cast(Mapping[str, object], row))
    return result


def _branches(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = report.get("branches")
    if not isinstance(raw, list):
        raise ValueError("DASHBOARD_BRANCHES_INVALID")
    result: list[Mapping[str, object]] = []
    for branch in raw:
        if not isinstance(branch, dict):
            raise ValueError("DASHBOARD_BRANCHES_INVALID")
        result.append(cast(Mapping[str, object], branch))
    return result


def _claim_ids(report: Mapping[str, object]) -> list[str]:
    raw = report.get("claim_ids")
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, str) or item not in _ALLOWED_CLAIM_IDS for item in raw)
    ):
        raise ValueError("DASHBOARD_CLAIM_IDS_INVALID")
    return cast(list[str], raw)


def _freshness(report: Mapping[str, object], generated_at: datetime) -> dict[str, object]:
    raw = report.get("capture_times_utc")
    captures = [] if not isinstance(raw, list) else [_utc(value) for value in raw]
    if not captures:
        return {
            "status": "UNAVAILABLE",
            "latest_capture_time_utc": None,
            "age_seconds": None,
            "freshness_limit_seconds": FRESHNESS_LIMIT_SECONDS,
        }
    latest = max(captures)
    age = max(0, int((generated_at - latest).total_seconds()))
    return {
        "status": "FRESH" if age <= FRESHNESS_LIMIT_SECONDS else "STALE",
        "latest_capture_time_utc": _iso_z(latest),
        "age_seconds": age,
        "freshness_limit_seconds": FRESHNESS_LIMIT_SECONDS,
    }


def _collection_health(status: object) -> str:
    if not isinstance(status, str):
        return "UNKNOWN"
    return {
        "REAL_DATA_COMPLETE": "HEALTHY",
        "REAL_DATA_PARTIAL": "PARTIAL",
        "REAL_DATA_FAILED": "FAILED",
    }.get(status, "UNKNOWN")


def _market_availability(branches: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = {"missing": 0, "duplicated": 0, "legacy_unknown": 0}
    mapping = {
        "RESULT_MARKET_MISSING": "missing",
        "RESULT_MARKET_DUPLICATED": "duplicated",
        "RESULT_MARKET_MISSING_OR_DUPLICATED": "legacy_unknown",
    }
    for branch in branches:
        limitations = branch.get("limitations")
        if not isinstance(limitations, list):
            continue
        for limitation in limitations:
            if not isinstance(limitation, dict):
                continue
            code = limitation.get("code")
            bucket = mapping.get(code) if isinstance(code, str) else None
            if bucket is not None:
                counts[bucket] += 1
    return counts


def _coverage(
    rows: Sequence[Mapping[str, object]], branches: Sequence[Mapping[str, object]]
) -> dict[str, dict[str, dict[str, object]]]:
    observed: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    eligible: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for row in rows:
        sport = row.get("sport_key")
        market = row.get("market_key")
        event = row.get("event_id")
        bookmaker = row.get("bookmaker_key")
        if all(isinstance(value, str) for value in (sport, market, event, bookmaker)):
            key = (cast(str, sport), cast(str, market))
            group = (cast(str, event), cast(str, bookmaker))
            observed[key].add(group)
            eligible[key].add(group)
    for branch in branches:
        sport = branch.get("sport_key")
        limitations = branch.get("limitations")
        if not isinstance(sport, str) or not isinstance(limitations, list):
            continue
        for limitation in limitations:
            if not isinstance(limitation, dict):
                continue
            market = limitation.get("market_key")
            event = limitation.get("event_id")
            bookmaker = limitation.get("bookmaker_key")
            if all(isinstance(value, str) for value in (market, event, bookmaker)):
                eligible[(sport, cast(str, market))].add((cast(str, event), cast(str, bookmaker)))
    result: dict[str, dict[str, dict[str, object]]] = {}
    for sport in SPORT_KEYS:
        result[sport] = {}
        for market in MARKETS:
            numerator = len(observed[(sport, market)])
            denominator = len(eligible[(sport, market)])
            result[sport][market] = {
                "observed_offer_groups": numerator,
                "eligible_bookmaker_event_groups": denominator,
                "ratio": round(numerator / denominator, 4) if denominator else None,
            }
    return result


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("DASHBOARD_QUANTILE_EMPTY")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def _price_distribution(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        market = row.get("market_key")
        outcome = row.get("outcome")
        price = row.get("price")
        if (
            isinstance(market, str)
            and isinstance(outcome, str)
            and isinstance(price, (int, float))
            and not isinstance(price, bool)
            and math.isfinite(float(price))
        ):
            grouped[(market, outcome)].append(float(price))
    result = []
    for (market, outcome), values in sorted(grouped.items()):
        result.append(
            {
                "market_key": market,
                "outcome": outcome,
                "count": len(values),
                "minimum": round(min(values), 6),
                "p25": round(_quantile(values, 0.25), 6),
                "median": round(_quantile(values, 0.5), 6),
                "p75": round(_quantile(values, 0.75), 6),
                "maximum": round(max(values), 6),
            }
        )
    return result


def _offer_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("sport_key"),
        row.get("event_id"),
        row.get("bookmaker_key"),
        row.get("market_key"),
        row.get("outcome"),
        row.get("point"),
    )


def _valid_offer_identity(row: Mapping[str, object]) -> tuple[object, ...] | None:
    required = (
        row.get("sport_key"),
        row.get("event_id"),
        row.get("bookmaker_key"),
        row.get("market_key"),
        row.get("outcome"),
    )
    if any(not isinstance(value, str) or not value.strip() for value in required):
        return None
    market = cast(str, row["market_key"])
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
    else:
        return None
    return _offer_identity(row)


def _valid_price(row: Mapping[str, object]) -> float | None:
    price = row.get("price")
    if (
        not isinstance(price, (int, float))
        or isinstance(price, bool)
        or not math.isfinite(float(price))
        or float(price) <= 0
    ):
        return None
    return float(price)


def _comparison_row(
    *,
    current: Mapping[str, object] | None,
    previous: Mapping[str, object] | None,
) -> dict[str, object]:
    source = current if current is not None else previous
    if source is None:
        raise ValueError("DASHBOARD_COMPARISON_ROW_EMPTY")
    result = {
        field: source.get(field)
        for field in (
            "sport_key",
            "event_id",
            "match",
            "kickoff_utc",
            "bookmaker_key",
            "bookmaker",
            "market_key",
            "outcome",
            "point",
        )
    }
    if previous is not None:
        result |= {
            "previous_slot_start_utc": previous.get("slot_start_utc"),
            "previous_capture_time_utc": previous.get("capture_time_utc"),
            "previous_source_timestamp_utc": previous.get("source_timestamp_utc"),
            "previous_price": _valid_price(previous),
        }
    if current is not None:
        result |= {
            "current_slot_start_utc": current.get("slot_start_utc"),
            "current_capture_time_utc": current.get("capture_time_utc"),
            "current_source_timestamp_utc": current.get("source_timestamp_utc"),
            "current_price": _valid_price(current),
        }
    return result


def _excluded_row(row: Mapping[str, object], *, side: str, reason: str) -> dict[str, object]:
    return {
        "side": side,
        "reason": reason,
        "sport_key": row.get("sport_key"),
        "event_id": row.get("event_id"),
        "bookmaker_key": row.get("bookmaker_key"),
        "market_key": row.get("market_key"),
        "outcome": row.get("outcome"),
        "point": row.get("point"),
    }


def _branch_times(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, list[datetime]], set[str]]:
    result: dict[str, list[datetime]] = defaultdict(list)
    invalid: set[str] = set()
    for row in rows:
        sport = row.get("sport_key")
        if not isinstance(sport, str) or not sport:
            continue
        try:
            result[sport].append(_utc(row.get("capture_time_utc")))
        except ValueError:
            invalid.add(sport)
    return result, invalid


def _movement_breakdown(
    matched_offers: Sequence[Mapping[str, object]], *, field: str
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in matched_offers:
        key = row.get(field)
        if isinstance(key, str):
            grouped[key].append(row)
    result: list[dict[str, object]] = []
    for key, rows in sorted(grouped.items()):
        deltas = [abs(float(cast(float, row["delta"]))) for row in rows]
        changed = sum(row["direction"] != "UNCHANGED" for row in rows)
        result.append(
            {
                "key": key,
                "matched_offer_count": len(rows),
                "distinct_match_count": len({row.get("event_id") for row in rows}),
                "changed_offer_count": changed,
                "changed_proportion": round(changed / len(rows), 6),
                "up_count": sum(row["direction"] == "UP" for row in rows),
                "down_count": sum(row["direction"] == "DOWN" for row in rows),
                "unchanged_count": sum(row["direction"] == "UNCHANGED" for row in rows),
                "mean_absolute_delta": round(sum(deltas) / len(deltas), 6),
            }
        )
    return result


def compare_acquisitions(
    current: Sequence[Mapping[str, object]], previous: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Compare two normalized acquisitions without hiding ambiguous observations."""

    current_times, current_time_invalid = _branch_times(current)
    previous_times, previous_time_invalid = _branch_times(previous)
    shared_sports = set(current_times) & set(previous_times)
    invalid_time_sports = (current_time_invalid | previous_time_invalid) & (
        {str(row.get("sport_key")) for row in current}
        | {str(row.get("sport_key")) for row in previous}
    )
    non_forward_sports = {
        sport for sport in shared_sports if min(current_times[sport]) <= max(previous_times[sport])
    }

    indexed: dict[str, dict[tuple[object, ...], list[Mapping[str, object]]]] = {
        "current": defaultdict(list),
        "previous": defaultdict(list),
    }
    excluded: list[dict[str, object]] = []
    excluded_identities: set[tuple[object, ...]] = set()
    for side, rows in (("current", current), ("previous", previous)):
        for row in rows:
            sport = row.get("sport_key")
            if sport in invalid_time_sports:
                identity = _offer_identity(row)
                excluded_identities.add(identity)
                excluded.append(_excluded_row(row, side=side, reason="BRANCH_TIME_INVALID"))
                continue
            if sport in non_forward_sports:
                identity = _offer_identity(row)
                excluded_identities.add(identity)
                excluded.append(_excluded_row(row, side=side, reason="NON_FORWARD_BRANCH_TIME"))
                continue
            identity = _valid_offer_identity(row)
            if identity is None:
                excluded.append(_excluded_row(row, side=side, reason="INVALID_OFFER_IDENTITY"))
                continue
            indexed[side][identity].append(row)

    all_identities = set(indexed["current"]) | set(indexed["previous"])
    matched_offers: list[dict[str, object]] = []
    appeared_offers: list[dict[str, object]] = []
    not_observed_offers: list[dict[str, object]] = []
    for identity in sorted(all_identities, key=repr):
        current_rows = indexed["current"].get(identity, [])
        previous_rows = indexed["previous"].get(identity, [])
        combined = [("current", row) for row in current_rows] + [
            ("previous", row) for row in previous_rows
        ]
        if len(current_rows) > 1 or len(previous_rows) > 1:
            excluded_identities.add(identity)
            excluded.extend(
                _excluded_row(row, side=side, reason="DUPLICATE_OFFER_IDENTITY")
                for side, row in combined
            )
            continue
        if any(_valid_price(row) is None for _, row in combined):
            excluded_identities.add(identity)
            excluded.extend(
                _excluded_row(row, side=side, reason="INVALID_PRICE") for side, row in combined
            )
            continue
        if current_rows and previous_rows:
            current_row = current_rows[0]
            previous_row = previous_rows[0]
            current_price = cast(float, _valid_price(current_row))
            previous_price = cast(float, _valid_price(previous_row))
            delta = round(current_price - previous_price, 6)
            direction = "UP" if delta > 0 else "DOWN" if delta < 0 else "UNCHANGED"
            matched_offers.append(
                _comparison_row(current=current_row, previous=previous_row)
                | {"delta": delta, "direction": direction}
            )
        elif current_rows:
            appeared_offers.append(_comparison_row(current=current_rows[0], previous=None))
        elif previous_rows:
            not_observed_offers.append(_comparison_row(current=None, previous=previous_rows[0]))

    matched_offers.sort(
        key=lambda item: (
            -abs(float(cast(float, item["delta"]))),
            repr(_offer_identity(item)),
        )
    )
    appeared_offers.sort(key=lambda item: repr(_offer_identity(item)))
    not_observed_offers.sort(key=lambda item: repr(_offer_identity(item)))
    absolute_deltas = [abs(float(cast(float, row["delta"]))) for row in matched_offers]
    changed = sum(row["direction"] != "UNCHANGED" for row in matched_offers)
    unchanged = len(matched_offers) - changed
    reason_counts: dict[str, int] = defaultdict(int)
    for row in excluded:
        reason_counts[cast(str, row["reason"])] += 1
    return {
        "matched_offer_count": len(matched_offers),
        "changed_offer_count": changed,
        "unchanged_offer_count": unchanged,
        "appeared_offer_count": len(appeared_offers),
        "not_observed_offer_count": len(not_observed_offers),
        "unmatched_current_count": len(appeared_offers),
        "unmatched_previous_count": len(not_observed_offers),
        "excluded_row_count": len(excluded),
        "excluded_identity_count": len(excluded_identities),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "changed_proportion": round(changed / len(matched_offers), 6) if matched_offers else None,
        "direction_counts": {
            "UP": sum(row["direction"] == "UP" for row in matched_offers),
            "DOWN": sum(row["direction"] == "DOWN" for row in matched_offers),
            "UNCHANGED": unchanged,
        },
        "mean_absolute_delta": round(sum(absolute_deltas) / len(absolute_deltas), 6)
        if absolute_deltas
        else None,
        "median_absolute_delta": round(_quantile(absolute_deltas, 0.5), 6)
        if absolute_deltas
        else None,
        "maximum_absolute_delta": round(max(absolute_deltas), 6) if absolute_deltas else None,
        "matched_offers": matched_offers,
        "appeared_offers": appeared_offers,
        "not_observed_offers": not_observed_offers,
        "excluded_rows": excluded,
        "changes": [row for row in matched_offers if row["direction"] != "UNCHANGED"],
        "breakdowns": {
            "league": _movement_breakdown(matched_offers, field="sport_key"),
            "bookmaker": _movement_breakdown(matched_offers, field="bookmaker_key"),
            "market": _movement_breakdown(matched_offers, field="market_key"),
        },
    }


def _price_movement(
    current: Sequence[Mapping[str, object]], previous: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    return compare_acquisitions(current, previous)


def _explorer_rows(comparison: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for field, status in (
        ("matched_offers", "MATCHED"),
        ("appeared_offers", "APPEARED"),
        ("not_observed_offers", "NOT_OBSERVED"),
    ):
        raw_rows = comparison.get(field)
        if not isinstance(raw_rows, list):
            continue
        for raw_row in raw_rows:
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)
            if status == "MATCHED":
                row["comparison_status"] = (
                    "MATCHED_UNCHANGED"
                    if row.get("direction") == "UNCHANGED"
                    else "MATCHED_CHANGED"
                )
            else:
                row["comparison_status"] = status
                row["direction"] = status
                row["delta"] = None
            result.append(row)
    return result


def _incidents(branches: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result = []
    for branch in branches:
        diagnostic = branch.get("diagnostic")
        if isinstance(diagnostic, dict):
            result.append(
                {"sport_key": branch.get("sport_key")}
                | {
                    key: diagnostic.get(key)
                    for key in (
                        "stage",
                        "code",
                        "exception_class",
                        "errno",
                        "http_status",
                    )
                    if diagnostic.get(key) is not None
                }
            )
    return result


def build_dashboard_snapshot(
    current_report: Mapping[str, object],
    *,
    previous_report: Mapping[str, object] | None,
    generated_at: datetime,
) -> dict[str, object]:
    """Build source-backed operational and descriptive dashboard state."""

    now = ensure_utc(generated_at, field="dashboard_generated_at")
    current_rows = _rows(current_report)
    current_branches = _branches(current_report)
    previous_rows = _rows(previous_report) if previous_report is not None else []
    carry_forward = (
        current_report.get("status") == "REAL_DATA_FAILED"
        and not current_rows
        and bool(previous_rows)
    )
    data_report = (
        previous_report if carry_forward and previous_report is not None else current_report
    )
    data_rows = previous_rows if carry_forward else current_rows
    data_branches = _branches(data_report)
    status_by_sport = {
        cast(str, branch["sport_key"]): str(branch.get("status", "UNKNOWN"))
        for branch in data_branches
        if isinstance(branch.get("sport_key"), str)
    }
    display_rows = [
        {field: row.get(field) for field in _ROW_FIELDS}
        | {
            "branch_status": (
                "STALE"
                if carry_forward
                else status_by_sport.get(str(row.get("sport_key")), "UNKNOWN")
            )
        }
        for row in data_rows
    ]
    accounting = current_report.get("accounting")
    if not isinstance(accounting, dict):
        accounting = {}
    freshness = _freshness(data_report, now)
    if carry_forward:
        freshness["status"] = "STALE"
    provenance_reports = [current_report, data_report]
    if not carry_forward and previous_report is not None:
        provenance_reports.append(previous_report)
    claim_ids = list(
        dict.fromkeys(claim_id for report in provenance_reports for claim_id in _claim_ids(report))
    )
    comparison = (
        _price_movement(data_rows, [])
        if carry_forward
        else _price_movement(current_rows, previous_rows)
    )
    return {
        "schema_version": "robin-real-data-explorer-v2",
        "mission_id": current_report.get("mission_id"),
        "claim_ids": claim_ids,
        "repository_sha": current_report.get("repository_sha"),
        "github_run_id": current_report.get("github_run_id"),
        "slot_start_utc": current_report.get("slot_start_utc"),
        "data_slot_start_utc": data_report.get("slot_start_utc"),
        "data_role": "CARRY_FORWARD_STALE" if carry_forward else "CURRENT",
        "generated_at_utc": _iso_z(now),
        "collection_health": _collection_health(current_report.get("status")),
        "freshness": freshness,
        "market_availability": _market_availability(data_branches),
        "coverage": _coverage(data_rows, data_branches),
        "price_distribution": _price_distribution(data_rows),
        "price_movement": comparison,
        "explorer_rows": _explorer_rows(comparison),
        "incidents": _incidents(current_branches),
        "accounting": {
            field: accounting[field] for field in _PUBLIC_ACCOUNTING_FIELDS if field in accounting
        },
        "summary": {
            "row_count": len(data_rows),
            "match_count": len({row.get("event_id") for row in data_rows}),
            "bookmaker_count": len({row.get("bookmaker_key") for row in data_rows}),
            "validated_capture_count": current_report.get("validated_capture_count", 0),
            "incomplete_branch_count": current_report.get("incomplete_branch_count", 0),
        },
        "rows": display_rows,
        "scientific_notice": "Aucun edge n’est validé ; exploration descriptive uniquement.",
    }


def build_explorer_snapshot(
    current_snapshot: Mapping[str, object],
    previous_snapshot: Mapping[str, object],
    *,
    generated_at: datetime,
) -> dict[str, object]:
    """Project two verified public snapshots into the explorer model."""

    comparison = compare_acquisitions(_rows(current_snapshot), _rows(previous_snapshot))
    current_claims = current_snapshot.get("claim_ids")
    previous_claims = previous_snapshot.get("claim_ids")
    claim_ids = list(
        dict.fromkeys(
            str(value)
            for values in (current_claims, previous_claims)
            if isinstance(values, list)
            for value in values
        )
    )
    result = dict(current_snapshot)
    result.update(
        {
            "schema_version": "robin-real-data-explorer-v2",
            "generated_at_utc": _iso_z(generated_at),
            "claim_ids": claim_ids,
            "price_movement": comparison,
            "explorer_rows": _explorer_rows(comparison),
            "comparison_acquisitions": {
                "previous": {
                    "slot_start_utc": previous_snapshot.get("data_slot_start_utc")
                    or previous_snapshot.get("slot_start_utc"),
                    "github_run_id": previous_snapshot.get("github_run_id"),
                    "generated_at_utc": previous_snapshot.get("generated_at_utc"),
                },
                "current": {
                    "slot_start_utc": current_snapshot.get("data_slot_start_utc")
                    or current_snapshot.get("slot_start_utc"),
                    "github_run_id": current_snapshot.get("github_run_id"),
                    "generated_at_utc": current_snapshot.get("generated_at_utc"),
                },
            },
        }
    )
    return result


def _safe_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _incident_markup(incidents: object) -> str:
    if not isinstance(incidents, list) or not incidents:
        return '<p class="empty-inline">Aucun incident de collecte sur ce créneau.</p>'
    items = []
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        code = html.escape(str(incident.get("code", "INCIDENT_INCONNU")))
        sport = html.escape(str(incident.get("sport_key", "branche inconnue")))
        stage = html.escape(str(incident.get("stage", "étape inconnue")))
        details = []
        for key in ("exception_class", "errno", "http_status"):
            if incident.get(key) is not None:
                details.append(f"{key}={html.escape(str(incident[key]))}")
        suffix = f" · {' · '.join(details)}" if details else ""
        items.append(f"<li><strong>{code}</strong><span>{sport} · {stage}{suffix}</span></li>")
    return f'<ul class="incident-list">{"".join(items)}</ul>'


def render_dashboard_html(
    snapshot: Mapping[str, object], *, csv_filename: str = "robin-real-data.csv"
) -> bytes:
    """Render a responsive dashboard whose table DOM is capped to one page."""

    payload = _safe_json(snapshot)
    health = html.escape(str(snapshot.get("collection_health", "UNKNOWN")))
    freshness_raw = snapshot.get("freshness")
    freshness = freshness_raw if isinstance(freshness_raw, dict) else {}
    freshness_status = html.escape(str(freshness.get("status", "UNAVAILABLE")))
    latest_capture = html.escape(str(freshness.get("latest_capture_time_utc") or "—"))
    slot = html.escape(str(snapshot.get("slot_start_utc") or "—"))
    generated = html.escape(str(snapshot.get("generated_at_utc") or "—"))
    summary_raw = snapshot.get("summary")
    summary = summary_raw if isinstance(summary_raw, dict) else {}
    accounting_raw = snapshot.get("accounting")
    accounting = accounting_raw if isinstance(accounting_raw, dict) else {}
    availability_raw = snapshot.get("market_availability")
    availability = availability_raw if isinstance(availability_raw, dict) else {}
    csv_link = html.escape(csv_filename, quote=True)
    incidents = _incident_markup(snapshot.get("incidents"))
    notice = html.escape(str(snapshot.get("scientific_notice", "")))
    claim_ids = " · ".join(html.escape(item) for item in _claim_ids(snapshot))
    data_slot = html.escape(str(snapshot.get("data_slot_start_utc") or "—"))
    carry_forward_notice = (
        '<p class="notice">Dernières observations utilisables conservées '
        f"depuis le créneau {data_slot} ; elles sont affichées comme anciennes "
        "pendant l’incident courant.</p>"
        if snapshot.get("data_role") == "CARRY_FORWARD_STALE"
        else ""
    )
    document = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Robin — Observatoire réel</title>
<style>
:root{{--ink:#17212b;--muted:#66717d;--paper:#f5f3ee;--card:#fff;--line:#dedad0;--navy:#183b56;--teal:#177e75;--amber:#b06a16;--red:#a53b32;--shadow:0 12px 32px rgba(28,38,47,.08)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}header{{padding:28px clamp(18px,4vw,54px);background:linear-gradient(120deg,#102f45,#1d5963);color:#fff}}header p{{margin:.35rem 0 0;color:#d7e9ea}}main{{max-width:1500px;margin:auto;padding:24px clamp(14px,3vw,42px) 48px}}h1{{font:700 clamp(25px,4vw,42px)/1.1 Georgia,serif;margin:0}}h2{{font:700 21px/1.25 Georgia,serif;margin:0 0 16px}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:12px;font-weight:700;color:#bee1dd}}.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}}.card,.panel{{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}}.card{{padding:17px}}.card small{{display:block;color:var(--muted);margin-bottom:7px}}.metric{{font-size:24px;font-weight:750}}.metric.tight{{font-size:17px}}.sub{{font-size:12px;color:var(--muted);margin-top:4px}}.panel{{padding:20px;margin:18px 0}}.status{{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:5px 10px;background:#e6f3ef;color:#0f665e;font-size:12px;font-weight:800}}.status.PARTIAL,.status.STALE{{background:#fff1dc;color:#8a5310}}.status.FAILED,.status.UNAVAILABLE{{background:#fde7e4;color:#8f2f28}}.controls{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin-bottom:14px}}.controls .wide{{grid-column:span 2}}input,select,button{{width:100%;min-height:42px;border:1px solid #c8c5bc;border-radius:9px;background:#fff;color:var(--ink);padding:9px 11px;font:inherit}}button{{cursor:pointer;font-weight:700}}button:hover{{border-color:var(--teal);color:var(--teal)}}button:disabled{{cursor:not-allowed;opacity:.45}}.actions{{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 14px}}.actions button{{width:auto}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:10px}}table{{width:100%;border-collapse:collapse;white-space:nowrap}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid #ece9e2}}th{{position:sticky;top:0;background:#f3f0e9;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}tbody tr:hover{{background:#f6fbfa}}.pagination{{display:flex;align-items:center;justify-content:flex-end;gap:10px;margin-top:12px}}.pagination button{{width:auto}}.empty{{display:none;text-align:center;padding:30px;color:var(--muted)}}.empty-inline{{color:var(--muted)}}.split{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.incident-list{{list-style:none;padding:0;margin:0;display:grid;gap:8px}}.incident-list li{{display:flex;flex-direction:column;padding:10px 12px;border-left:4px solid var(--red);background:#fff7f5}}.incident-list span{{color:var(--muted);font-size:13px}}.notice{{border-left:4px solid var(--navy);padding:12px 15px;background:#eef4f7;font-weight:650}}.stats-list{{display:grid;gap:8px}}.stats-row{{display:grid;grid-template-columns:1.2fr repeat(5,.7fr);gap:8px;padding:8px 0;border-bottom:1px solid #eee;font-variant-numeric:tabular-nums}}.stats-row span:not(:first-child){{text-align:right}}.label{{color:var(--muted);font-size:12px}}code{{font:12px ui-monospace,SFMono-Regular,Consolas,monospace}}@media(max-width:1050px){{.grid{{grid-template-columns:repeat(2,1fr)}}.controls .wide{{grid-column:span 1}}.split{{grid-template-columns:1fr}}}}@media(max-width:620px){{header{{padding:22px 18px}}main{{padding:15px 10px 36px}}.grid,.controls{{grid-template-columns:1fr}}.card,.panel{{border-radius:10px}}.metric{{font-size:21px}}.actions button{{width:100%}}}}@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important}}}}
</style>
</head>
<body>
<header><div class="eyebrow">Laboratoire personnel · données réellement reçues</div><h1>Robin, observatoire des cotes</h1><p>État opérationnel, fraîcheur, couverture et exploration descriptive — sans promesse d’edge.</p></header>
<main>
<section class="grid" aria-label="État du système">
 <div class="card"><small>Collecte</small><div class="metric tight"><span class="status {health}">{health}</span></div><div class="sub">Panne de collecte distincte d’un marché absent</div></div>
 <div class="card"><small>Fraîcheur</small><div class="metric tight"><span id="freshness-status" class="status {freshness_status}">{freshness_status}</span></div><div id="freshness-detail" class="sub">Dernière capture : {latest_capture}</div></div>
 <div class="card"><small>Observations</small><div class="metric">{int(summary.get("row_count", 0)):,}</div><div class="sub">{int(summary.get("match_count", 0))} matchs · {int(summary.get("bookmaker_count", 0))} bookmakers</div></div>
 <div class="card"><small>Consommation glissante 24 h</small><div class="metric">{int(accounting.get("rolling_24h_requests", 0))} / 140</div><div class="sub">{int(accounting.get("rolling_24h_credits", 0))} / 280 crédits réservés</div></div>
</section>
<section class="grid" aria-label="Disponibilité des marchés">
 <div class="card"><small>Captures vérifiées</small><div class="metric">{int(summary.get("validated_capture_count", 0))}</div><div class="sub">Créneau {slot}</div></div>
 <div class="card"><small>Marché absent</small><div class="metric">{int(availability.get("missing", 0))}</div><div class="sub">Absence bookmaker, pas panne</div></div>
 <div class="card"><small>Marché dupliqué</small><div class="metric">{int(availability.get("duplicated", 0))}</div><div class="sub">Réponse ambiguë explicitement isolée</div></div>
 <div class="card"><small>Limite historique indéterminée</small><div class="metric">{int(availability.get("legacy_unknown", 0))}</div><div class="sub">Ancien code préservé, non reclassé</div></div>
</section>
{carry_forward_notice}
<p class="notice">{notice}</p>
<section class="panel" aria-labelledby="observations-title">
 <h2 id="observations-title">Explorer et comparer deux acquisitions</h2>
 <div id="movement-summary" class="notice" aria-live="polite"></div>
 <div class="controls">
  <input id="search" class="wide" type="search" placeholder="Équipe, match, bookmaker, issue…" aria-label="Rechercher">
  <select id="league-filter" aria-label="Filtrer par ligue"><option value="">Toutes les ligues</option></select>
  <select id="market-filter" aria-label="Filtrer par marché"><option value="">Tous les marchés</option></select>
  <select id="bookmaker-filter" aria-label="Filtrer par bookmaker"><option value="">Tous les bookmakers</option></select>
  <select id="capture-filter" aria-label="Filtrer par acquisition"><option value="comparison">Deux acquisitions</option><option value="current">Acquisition récente</option><option value="previous">Acquisition précédente</option></select>
  <select id="status-filter" aria-label="Filtrer par état"><option value="">Tous les mouvements</option></select>
  <input id="odds-min" type="number" min="0" step="0.01" placeholder="Cote min" aria-label="Cote minimale">
  <input id="odds-max" type="number" min="0" step="0.01" placeholder="Cote max" aria-label="Cote maximale">
  <input id="delta-min" type="number" step="0.01" placeholder="Variation min" aria-label="Variation minimale">
  <input id="delta-max" type="number" step="0.01" placeholder="Variation max" aria-label="Variation maximale">
  <select id="sort-field" aria-label="Trier par"><option value="abs_delta">Variation absolue</option><option value="delta">Variation signée</option><option value="current_price">Cote récente</option><option value="previous_price">Cote précédente</option><option value="kickoff_utc">Coup d'envoi</option><option value="match">Match</option></select>
  <select id="sort-direction" aria-label="Ordre du tri"><option value="desc">Décroissant</option><option value="asc">Croissant</option></select>
  <button id="reset-filters" type="button">Réinitialiser</button>
 </div>
 <form id="export-form" class="actions" method="post"><input id="export-content" name="content" type="hidden"><button id="export-filtered-csv" type="submit" formaction="/export.csv">Exporter la sélection CSV</button><button id="export-filtered-json" type="submit" formaction="/export.json">Exporter la sélection JSON</button></form>
 <div id="visible-summary" class="sub" aria-live="polite"></div>
 <div class="table-wrap"><table><thead><tr><th>Match</th><th>Coup d'envoi UTC</th><th>Ligue</th><th>Bookmaker</th><th>Marché</th><th>Issue</th><th>Seuil</th><th>Capture précédente</th><th>Ancienne cote</th><th>Capture récente</th><th>Nouvelle cote</th><th>Delta</th><th>État</th></tr></thead><tbody id="rows-body"></tbody></table><div id="empty-state" class="empty">Aucune observation ne correspond aux filtres.</div></div>
 <div class="pagination"><button id="previous-page" type="button">Précédent</button><span id="page-label">Page 1</span><button id="next-page" type="button">Suivant</button></div>
 <p><a href="{csv_link}" download>CSV source complet</a> · Les boutons exportent toutes les lignes filtrées, pas seulement la page · Heures affichées en UTC · Généré {generated}</p>
 <details><summary>Provenance des métriques</summary><code>{claim_ids}</code></details>
</section>
<section class="split">
 <article class="panel"><h2>Incidents</h2>{incidents}</article>
 <article class="panel"><h2>Limites de comparaison</h2><div id="comparison-limits" class="stats-list"></div></article>
</section>
<details class="panel"><summary><strong>Dispersion descriptive des cotes</strong></summary><div class="label">Minimum · P25 · médiane · P75 · maximum, par marché et issue</div><div id="distribution-list" class="stats-list"></div></details>
</main>
<script>
const DATA = {payload};
const PAGE_SIZE = 100;
const LOADED_RUN_ID = String(DATA.github_run_id??"");
const FILTER_STORAGE_KEY = "robin-explorer-filters-v1";
const SOURCE_ROWS = (DATA.explorer_rows||[]).map(row=>({{...row,_search:[row.match,row.bookmaker,row.outcome,row.event_id].map(value=>value??"").join(" ").toLocaleLowerCase("fr")}}));
const EXPORT_FIELDS = ["comparison_status","sport_key","event_id","match","kickoff_utc","bookmaker_key","bookmaker","market_key","outcome","point","previous_slot_start_utc","previous_capture_time_utc","previous_source_timestamp_utc","previous_price","current_slot_start_utc","current_capture_time_utc","current_source_timestamp_utc","current_price","delta","direction"];
let filtered = SOURCE_ROWS.slice();
let page = 0;
const byId = id => document.getElementById(id);
const escapeText = value => value === null || value === undefined ? "—" : String(value);
function refreshFreshness(nowMs=Date.now()) {{
 const state=DATA.freshness||{{}}, capture=state.latest_capture_time_utc, parsed=Date.parse(capture||"");
 const limit=Number(state.freshness_limit_seconds)||10800, badge=byId("freshness-status"), detail=byId("freshness-detail");
 let status="UNAVAILABLE", age=null;
 if(Number.isFinite(parsed)) {{ age=Math.max(0,Math.floor((nowMs-parsed)/1000)); status=(DATA.data_role==="CARRY_FORWARD_STALE"||age>limit)?"STALE":"FRESH"; }}
 badge.className=`status ${{status}}`; badge.textContent=status;
 detail.textContent=capture ? `Dernière capture : ${{capture}} · âge ${{Math.floor(age/60)}} min` : "Dernière capture : —";
}}
refreshFreshness();
function saveFilterState() {{
 try {{ sessionStorage.setItem(FILTER_STORAGE_KEY,JSON.stringify(Object.fromEntries(FILTER_IDS.map(id=>[id,byId(id).value])))); }} catch(_error) {{ /* storage can be disabled */ }}
}}
function restoreFilterState() {{
 try {{ const saved=JSON.parse(sessionStorage.getItem(FILTER_STORAGE_KEY)||"null"); if(saved&&typeof saved==="object") FILTER_IDS.forEach(id=>{{if(typeof saved[id]==="string") byId(id).value=saved[id];}}); sessionStorage.removeItem(FILTER_STORAGE_KEY); }} catch(_error) {{ /* ignore invalid local state */ }}
}}
async function pollForNewRun() {{
 if(location.pathname.startsWith("/history/")) return;
 try {{
  const response=await fetch("/status.json",{{cache:"no-store",credentials:"omit"}}); if(!response.ok) return;
  const status=await response.json(), current=String(status.current_run_id??"");
  if(current&&LOADED_RUN_ID&&current!==LOADED_RUN_ID) {{ saveFilterState(); location.reload(); }}
 }} catch(_error) {{ /* keep the verified view while the local service recovers */ }}
}}
setInterval(()=>{{refreshFreshness();void pollForNewRun();}},60000);
function addOptions(id, values) {{ const select=byId(id); [...new Set(values.filter(Boolean))].sort().forEach(value=>{{ const option=document.createElement("option"); option.value=value; option.textContent=value; select.appendChild(option); }}); }}
addOptions("league-filter", SOURCE_ROWS.map(row=>row.sport_key));
addOptions("market-filter", SOURCE_ROWS.map(row=>row.market_key));
addOptions("bookmaker-filter", SOURCE_ROWS.map(row=>row.bookmaker));
addOptions("status-filter", SOURCE_ROWS.map(row=>row.comparison_status));
function optionalNumber(id) {{ const value=byId(id).value; return value===""?null:Number(value); }}
function selectRows() {{
 const query=byId("search").value.trim().toLocaleLowerCase("fr"), league=byId("league-filter").value, market=byId("market-filter").value, bookmaker=byId("bookmaker-filter").value, capture=byId("capture-filter").value, status=byId("status-filter").value;
 const oddsMin=optionalNumber("odds-min"), oddsMax=optionalNumber("odds-max"), deltaMin=optionalNumber("delta-min"), deltaMax=optionalNumber("delta-max");
 filtered=SOURCE_ROWS.filter(row=>{{
  const hasCurrent=row.current_price!==null&&row.current_price!==undefined, hasPrevious=row.previous_price!==null&&row.previous_price!==undefined;
  const captureMatch=capture==="current"?hasCurrent:capture==="previous"?hasPrevious:true;
  const odds=capture==="previous"?row.previous_price:(hasCurrent?row.current_price:row.previous_price), delta=row.delta;
  return (!query||row._search.includes(query))&&(!league||row.sport_key===league)&&(!market||row.market_key===market)&&(!bookmaker||row.bookmaker===bookmaker)&&captureMatch&&(!status||row.comparison_status===status)&&(oddsMin===null||Number(odds)>=oddsMin)&&(oddsMax===null||Number(odds)<=oddsMax)&&(deltaMin===null||(delta!==null&&delta!==undefined&&Number(delta)>=deltaMin))&&(deltaMax===null||(delta!==null&&delta!==undefined&&Number(delta)<=deltaMax));
 }});
 const field=byId("sort-field").value, direction=byId("sort-direction").value==="asc"?1:-1;
 filtered.sort((a,b)=>{{
  let av=field==="abs_delta"?(a.delta===null||a.delta===undefined?null:Math.abs(Number(a.delta))):a[field], bv=field==="abs_delta"?(b.delta===null||b.delta===undefined?null:Math.abs(Number(b.delta))):b[field];
  if(av===null||av===undefined) return 1; if(bv===null||bv===undefined) return -1;
  if(typeof av==="number"&&typeof bv==="number") return direction*(av-bv);
  return direction*String(av).localeCompare(String(bv),"fr");
 }});
 page=0; renderRows();
}}
function renderRows() {{
 const body=byId("rows-body"); body.replaceChildren(); const start=page*PAGE_SIZE; const visible=filtered.slice(start,start+PAGE_SIZE);
 visible.forEach(row=>{{ const tr=document.createElement("tr"); [row.match,row.kickoff_utc,row.sport_key,row.bookmaker,row.market_key,row.outcome,row.point,row.previous_capture_time_utc,row.previous_price,row.current_capture_time_utc,row.current_price,row.delta,row.comparison_status].forEach(value=>{{const td=document.createElement("td");td.textContent=escapeText(value);tr.appendChild(td);}}); body.appendChild(tr); }});
 const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE)); byId("empty-state").style.display=filtered.length?"none":"block"; byId("previous-page").disabled=page===0; byId("next-page").disabled=page>=pages-1; byId("page-label").textContent=`Page ${{page+1}} / ${{pages}}`;
 const matches=new Set(filtered.map(row=>row.event_id)).size, books=new Set(filtered.map(row=>row.bookmaker_key)).size, captures=new Set(filtered.flatMap(row=>[row.previous_slot_start_utc,row.current_slot_start_utc]).filter(Boolean)).size; byId("visible-summary").textContent=`${{filtered.length.toLocaleString("fr-FR")}} offres sélectionnées · ${{matches}} matchs · ${{books}} bookmakers · ${{captures}} acquisitions`;
}}
function csvCell(value) {{ let text=value===null||value===undefined?"":String(value); if(/^[=+@\\t\\r-]/.test(text)) text="'"+text; return `"${{text.replaceAll('"','""')}}"`; }}
function exportFilteredCsv() {{ const exportRows=filtered.slice(); const lines=[EXPORT_FIELDS.join(","),...exportRows.map(row=>EXPORT_FIELDS.map(field=>csvCell(row[field])).join(","))]; byId("export-content").value=lines.join("\\n")+"\\n"; }}
function exportFilteredJson() {{ const exportRows=filtered.slice(); byId("export-content").value=JSON.stringify({{schema_version:"robin-filtered-selection-v1",generated_at_utc:DATA.generated_at_utc,claim_ids:DATA.claim_ids,filters:{{search:byId("search").value,league:byId("league-filter").value,market:byId("market-filter").value,bookmaker:byId("bookmaker-filter").value,capture:byId("capture-filter").value,status:byId("status-filter").value}},row_count:exportRows.length,rows:exportRows.map(row=>Object.fromEntries(EXPORT_FIELDS.map(field=>[field,row[field]??null]))) }},null,2); }}
const FILTER_IDS=["search","league-filter","market-filter","bookmaker-filter","capture-filter","status-filter","odds-min","odds-max","delta-min","delta-max","sort-field","sort-direction"];
restoreFilterState();
FILTER_IDS.forEach(id=>byId(id).addEventListener(["search","odds-min","odds-max","delta-min","delta-max"].includes(id)?"input":"change",selectRows));
byId("reset-filters").addEventListener("click",()=>{{FILTER_IDS.forEach(id=>byId(id).value="");byId("capture-filter").value="comparison";byId("sort-field").value="abs_delta";byId("sort-direction").value="desc";selectRows();}});
[["export-filtered-csv",exportFilteredCsv],["export-filtered-json",exportFilteredJson]].forEach(([id,prepare])=>{{byId(id).addEventListener("pointerdown",prepare);byId(id).addEventListener("focus",prepare);}});
byId("previous-page").addEventListener("click",()=>{{if(page>0){{page--;renderRows();}}}}); byId("next-page").addEventListener("click",()=>{{if((page+1)*PAGE_SIZE<filtered.length){{page++;renderRows();}}}});
const distribution=byId("distribution-list"); DATA.price_distribution.forEach(item=>{{const row=document.createElement("div");row.className="stats-row";[`${{item.market_key}} · ${{item.outcome}} (${{item.count}})`,item.minimum,item.p25,item.median,item.p75,item.maximum].forEach(value=>{{const span=document.createElement("span");span.textContent=value;row.appendChild(span);}});distribution.appendChild(row);}}); if(!DATA.price_distribution.length) distribution.textContent="Distribution indisponible : aucune cote vérifiée.";
const movement=DATA.price_movement, movementBox=byId("movement-summary"); movementBox.textContent=`${{movement.matched_offer_count}} offres appariées · ${{movement.changed_offer_count}} changements · ${{movement.unchanged_offer_count}} inchangées · ${{movement.unmatched_current_count}} nouvelles/non appariées`; if(!movement.matched_offer_count) movementBox.textContent += " — comparaison indisponible sans créneau précédent compatible.";
if(DATA.comparison_acquisitions) {{ const acquisition=byId("capture-filter"); acquisition.options[1].textContent=`Acquisition récente · ${{DATA.comparison_acquisitions.current.slot_start_utc??"date inconnue"}}`; acquisition.options[2].textContent=`Acquisition précédente · ${{DATA.comparison_acquisitions.previous.slot_start_utc??"date inconnue"}}`; }}
byId("comparison-limits").textContent=`${{movement.appeared_offer_count??movement.unmatched_current_count}} apparues · ${{movement.not_observed_offer_count??0}} non observées à nouveau · ${{movement.excluded_row_count??0}} lignes exclues. Une absence signifie non observée dans cette acquisition, pas retrait prouvé chez le bookmaker.`;
selectRows();
</script>
</body></html>"""
    return document.encode("utf-8")


def render_dashboard_csv(snapshot: Mapping[str, object]) -> bytes:
    """Render the normalized public rows with spreadsheet-formula hardening."""

    raw_rows = snapshot.get("rows")
    if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
        raise ValueError("DASHBOARD_ROWS_INVALID")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=_PUBLIC_CSV_FIELDS,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for raw_row in raw_rows:
        row = cast(dict[str, object], raw_row)
        writer.writerow(
            {
                field: (
                    f"'{value}"
                    if isinstance(value := row.get(field), str) and value and value[0] in "=+-@\t\r"
                    else value
                )
                for field in _PUBLIC_CSV_FIELDS
            }
        )
    return stream.getvalue().encode("utf-8")


__all__ = [
    "build_dashboard_snapshot",
    "build_explorer_snapshot",
    "compare_acquisitions",
    "render_dashboard_csv",
    "render_dashboard_html",
]
