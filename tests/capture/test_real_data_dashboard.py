from __future__ import annotations

from datetime import UTC, datetime, timedelta

from robin.capture.real_data_dashboard import (
    build_dashboard_snapshot,
    compare_acquisitions,
    render_dashboard_html,
)
from robin.capture.recurring_real_data import RECURRING_CLAIM_IDS, SEED_CLAIM_IDS

NOW = datetime(2026, 10, 4, 13, 0, tzinfo=UTC)


def _row(
    *,
    sport: str = "soccer_epl",
    event: str = "event-1",
    bookmaker: str = "book-a",
    market: str = "h2h",
    outcome: str = "Home",
    price: float = 2.0,
    point: float | None = None,
    capture: datetime = NOW - timedelta(hours=1),
) -> dict[str, object]:
    return {
        "slot_start_utc": "2026-10-04T12:00:00Z",
        "sport_key": sport,
        "sport_title": sport,
        "capture_time_utc": capture.isoformat().replace("+00:00", "Z"),
        "source_timestamp_utc": (capture - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
        "event_id": event,
        "match": "Home — Away",
        "kickoff_utc": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "bookmaker_key": bookmaker,
        "bookmaker": bookmaker,
        "market_key": market,
        "outcome": outcome,
        "point": point,
        "price": price,
        "quota_remaining": 19_900,
    }


def _report(
    *,
    rows: list[dict[str, object]] | None = None,
    capture: datetime = NOW - timedelta(hours=1),
    status: str = "REAL_DATA_COMPLETE",
    diagnostic: dict[str, object] | None = None,
    limitations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    observed_rows = rows if rows is not None else [_row(capture=capture)]
    branch_status = "INCOMPLETE" if diagnostic else "COMPLETE"
    return {
        "schema_version": "robin-autonomous-lab-private-report-v1",
        "mission_id": "ROBIN_AUTONOMOUS_LAB_20261004",
        "repository_sha": "a" * 40,
        "github_run_id": "40000000001",
        "claim_ids": list(RECURRING_CLAIM_IDS),
        "slot_start_utc": "2026-10-04T12:00:00Z",
        "generated_at_utc": capture.isoformat().replace("+00:00", "Z"),
        "status": status,
        "branches": [
            {
                "sport_key": "soccer_epl",
                "status": branch_status,
                "capture_time_utc": capture.isoformat().replace("+00:00", "Z"),
                "limitations": limitations or [],
                "diagnostic": diagnostic,
                "market_branch_coverage": {"h2h": 1, "totals": 0},
            }
        ],
        "rows": observed_rows,
        "row_count": len(observed_rows),
        "validated_capture_count": 1 if observed_rows else 0,
        "incomplete_branch_count": int(diagnostic is not None),
        "capture_times_utc": [capture.isoformat().replace("+00:00", "Z")] if observed_rows else [],
        "source_timestamp_min_utc": observed_rows[0]["source_timestamp_utc"]
        if observed_rows
        else None,
        "source_timestamp_max_utc": observed_rows[-1]["source_timestamp_utc"]
        if observed_rows
        else None,
        "match_count": len({row["event_id"] for row in observed_rows}),
        "bookmaker_count": len({row["bookmaker_key"] for row in observed_rows}),
        "market_branch_coverage": {"h2h": 1, "totals": 0},
        "market_outcome_row_counts": {
            "h2h": sum(row["market_key"] == "h2h" for row in observed_rows),
            "totals": sum(row["market_key"] == "totals" for row in observed_rows),
        },
        "market_limitation_counts": {
            "RESULT_MARKET_MISSING": sum(
                item.get("code") == "RESULT_MARKET_MISSING" for item in (limitations or [])
            ),
            "RESULT_MARKET_DUPLICATED": sum(
                item.get("code") == "RESULT_MARKET_DUPLICATED" for item in (limitations or [])
            ),
            "RESULT_MARKET_MISSING_OR_DUPLICATED": sum(
                item.get("code") == "RESULT_MARKET_MISSING_OR_DUPLICATED"
                for item in (limitations or [])
            ),
        },
        "provider_requests_new": 5,
        "provider_requests_reserved": 5,
        "provider_credits_reserved": 10,
        "accounting": {
            "rolling_24h_requests": 21,
            "rolling_24h_credits": 44,
            "rolling_30d_requests": 21,
            "rolling_30d_credits": 44,
            "lifetime_requests": 21,
            "lifetime_credits": 44,
            "provider_remaining_floor": 19_959,
        },
        "effect_accounting": {
            "automatic_retries": 0,
            "purchases": 0,
            "real_bets": 0,
            "backfills": 0,
            "promotions": 0,
        },
        "scientific_status": "DESCRIPTIVE_ONLY_NO_EDGE_VALIDATED",
    }


def test_freshness_collection_health_and_market_availability_are_separate() -> None:
    limitations = [
        {
            "code": "RESULT_MARKET_MISSING",
            "event_id": "event-1",
            "bookmaker_key": "book-a",
            "market_key": "totals",
        },
        {
            "code": "RESULT_MARKET_DUPLICATED",
            "event_id": "event-2",
            "bookmaker_key": "book-b",
            "market_key": "h2h",
        },
        {
            "code": "RESULT_MARKET_MISSING_OR_DUPLICATED",
            "event_id": "legacy",
            "bookmaker_key": "book-c",
            "market_key": "totals",
        },
    ]
    snapshot = build_dashboard_snapshot(
        _report(status="REAL_DATA_PARTIAL", limitations=limitations),
        previous_report=None,
        generated_at=NOW,
    )
    assert snapshot["claim_ids"] == list(RECURRING_CLAIM_IDS)
    assert snapshot["collection_health"] == "PARTIAL"
    assert snapshot["freshness"]["status"] == "FRESH"
    assert snapshot["market_availability"] == {
        "missing": 1,
        "duplicated": 1,
        "legacy_unknown": 1,
    }


def test_old_capture_is_stale_and_empty_capture_is_unavailable() -> None:
    stale = build_dashboard_snapshot(
        _report(capture=NOW - timedelta(hours=3, seconds=1)),
        previous_report=None,
        generated_at=NOW,
    )
    unavailable = build_dashboard_snapshot(
        _report(rows=[], status="REAL_DATA_FAILED"),
        previous_report=None,
        generated_at=NOW,
    )
    assert stale["freshness"]["status"] == "STALE"
    assert stale["freshness"]["age_seconds"] == 10_801
    assert unavailable["freshness"] == {
        "status": "UNAVAILABLE",
        "latest_capture_time_utc": None,
        "age_seconds": None,
        "freshness_limit_seconds": 10_800,
    }
    assert unavailable["collection_health"] == "FAILED"


def test_failed_current_slot_carries_last_usable_rows_as_explicitly_stale() -> None:
    previous = _report(capture=NOW - timedelta(hours=2))
    previous["slot_start_utc"] = "2026-10-04T10:00:00Z"
    failed = _report(
        rows=[],
        capture=NOW,
        status="REAL_DATA_FAILED",
        diagnostic={
            "stage": "DNS_RESOLUTION",
            "code": "RECURRING_DNS_RESOLUTION_FAILED",
            "exception_class": "RecurringError",
        },
    )
    snapshot = build_dashboard_snapshot(
        failed,
        previous_report=previous,
        generated_at=NOW,
    )
    assert snapshot["collection_health"] == "FAILED"
    assert snapshot["data_role"] == "CARRY_FORWARD_STALE"
    assert snapshot["data_slot_start_utc"] == "2026-10-04T10:00:00Z"
    assert snapshot["freshness"]["status"] == "STALE"
    assert len(snapshot["rows"]) == 1
    assert snapshot["rows"][0]["branch_status"] == "STALE"
    assert snapshot["incidents"][0]["code"] == "RECURRING_DNS_RESOLUTION_FAILED"
    rendered = render_dashboard_html(snapshot).decode("utf-8")
    assert "Dernières observations utilisables conservées" in rendered


def test_verified_empty_current_slot_never_carries_older_rows() -> None:
    current = _report(rows=[], status="REAL_DATA_COMPLETE", capture=NOW)
    current["validated_capture_count"] = 1
    current["capture_times_utc"] = [NOW.isoformat().replace("+00:00", "Z")]
    snapshot = build_dashboard_snapshot(
        current,
        previous_report=_report(capture=NOW - timedelta(hours=2)),
        generated_at=NOW,
    )
    assert snapshot["collection_health"] == "HEALTHY"
    assert snapshot["freshness"]["status"] == "FRESH"
    assert snapshot["data_role"] == "CURRENT"
    assert snapshot["rows"] == []


def test_coverage_has_explicit_offer_group_denominators() -> None:
    rows = [
        _row(event="event-1", market="h2h", outcome="Home"),
        _row(event="event-1", market="h2h", outcome="Draw"),
        _row(event="event-1", market="h2h", outcome="Away"),
        _row(event="event-1", market="totals", outcome="Over", point=2.5),
        _row(event="event-1", market="totals", outcome="Under", point=2.5),
        _row(event="event-2", market="h2h", outcome="Home"),
    ]
    limitations = [
        {
            "code": "RESULT_MARKET_MISSING",
            "event_id": "event-2",
            "bookmaker_key": "book-a",
            "market_key": "totals",
        }
    ]
    snapshot = build_dashboard_snapshot(
        _report(rows=rows, limitations=limitations),
        previous_report=None,
        generated_at=NOW,
    )
    coverage = snapshot["coverage"]
    assert coverage["soccer_epl"]["h2h"] == {
        "observed_offer_groups": 2,
        "eligible_bookmaker_event_groups": 2,
        "ratio": 1.0,
    }
    assert coverage["soccer_epl"]["totals"] == {
        "observed_offer_groups": 1,
        "eligible_bookmaker_event_groups": 2,
        "ratio": 0.5,
    }


def test_price_quantiles_are_hand_checked_and_grouped() -> None:
    rows = [
        _row(outcome="Home", price=1.0, event="event-1"),
        _row(outcome="Home", price=2.0, event="event-2"),
        _row(outcome="Home", price=3.0, event="event-3"),
        _row(outcome="Home", price=4.0, event="event-4"),
    ]
    snapshot = build_dashboard_snapshot(_report(rows=rows), previous_report=None, generated_at=NOW)
    distribution = snapshot["price_distribution"][0]
    assert distribution == {
        "market_key": "h2h",
        "outcome": "Home",
        "count": 4,
        "minimum": 1.0,
        "p25": 1.75,
        "median": 2.5,
        "p75": 3.25,
        "maximum": 4.0,
    }


def test_matched_offer_movements_do_not_invent_unmatched_changes() -> None:
    previous_capture = NOW - timedelta(hours=2)
    current_capture = NOW - timedelta(hours=1)
    previous = [
        _row(event="event-1", price=2.0, capture=previous_capture),
        _row(event="event-2", price=3.0, capture=previous_capture),
    ]
    current = [
        _row(event="event-1", price=2.2, capture=current_capture),
        _row(event="event-2", price=3.0, capture=current_capture),
        _row(event="event-3", price=9.0, capture=current_capture),
    ]
    previous_report = _report(rows=previous)
    previous_report["claim_ids"] = list(SEED_CLAIM_IDS)
    snapshot = build_dashboard_snapshot(
        _report(rows=current), previous_report=previous_report, generated_at=NOW
    )
    movement = snapshot["price_movement"]
    assert movement["matched_offer_count"] == 2
    assert movement["changed_offer_count"] == 1
    assert movement["unchanged_offer_count"] == 1
    assert movement["unmatched_current_count"] == 1
    assert movement["changes"][0]["delta"] == 0.2
    assert snapshot["claim_ids"] == [*RECURRING_CLAIM_IDS, *SEED_CLAIM_IDS]


def test_comparison_uses_exact_h2h_and_totals_offer_identities() -> None:
    previous_capture = NOW - timedelta(hours=2)
    current_capture = NOW - timedelta(hours=1)
    previous = [
        _row(event="event-1", market="h2h", outcome="Home", price=2.0, capture=previous_capture),
        _row(
            event="event-1",
            market="totals",
            outcome="Over",
            point=2.5,
            price=1.9,
            capture=previous_capture,
        ),
        _row(
            event="event-1",
            market="totals",
            outcome="Under",
            point=2.5,
            price=1.8,
            capture=previous_capture,
        ),
    ]
    current = [
        _row(event="event-1", market="h2h", outcome="Home", price=2.1, capture=current_capture),
        _row(
            event="event-1",
            market="totals",
            outcome="Over",
            point=2.5,
            price=1.85,
            capture=current_capture,
        ),
        _row(
            event="event-1",
            market="totals",
            outcome="Over",
            point=3.5,
            price=2.4,
            capture=current_capture,
        ),
    ]

    comparison = compare_acquisitions(current, previous)

    assert comparison["matched_offer_count"] == 2
    assert comparison["changed_offer_count"] == 2
    assert comparison["appeared_offer_count"] == 1
    assert comparison["not_observed_offer_count"] == 1
    assert comparison["excluded_row_count"] == 0
    assert comparison["changed_proportion"] == 1.0
    assert {row["point"] for row in comparison["matched_offers"]} == {None, 2.5}
    assert comparison["appeared_offers"][0]["point"] == 3.5
    assert comparison["not_observed_offers"][0]["outcome"] == "Under"


def test_comparison_excludes_duplicates_invalid_prices_and_unordered_branches() -> None:
    previous_capture = NOW - timedelta(hours=2)
    current_capture = NOW - timedelta(hours=1)
    duplicate = _row(event="duplicate", price=2.0, capture=previous_capture)
    previous = [
        duplicate,
        dict(duplicate),
        _row(event="invalid", price=2.0, capture=previous_capture),
        _row(
            sport="soccer_france_ligue_one",
            event="unordered",
            price=2.0,
            capture=current_capture,
        ),
    ]
    current = [
        _row(event="duplicate", price=2.1, capture=current_capture),
        _row(event="invalid", price=float("nan"), capture=current_capture),
        _row(
            sport="soccer_france_ligue_one",
            event="unordered",
            price=2.2,
            capture=previous_capture,
        ),
    ]

    comparison = compare_acquisitions(current, previous)

    assert comparison["matched_offer_count"] == 0
    assert comparison["appeared_offer_count"] == 0
    assert comparison["not_observed_offer_count"] == 0
    assert comparison["excluded_row_count"] == 7
    assert comparison["excluded_identity_count"] == 3
    assert comparison["exclusion_reason_counts"] == {
        "DUPLICATE_OFFER_IDENTITY": 3,
        "INVALID_PRICE": 2,
        "NON_FORWARD_BRANCH_TIME": 2,
    }


def test_comparison_reports_direction_amplitude_and_breakdowns() -> None:
    previous_capture = NOW - timedelta(hours=2)
    current_capture = NOW - timedelta(hours=1)
    previous = [
        _row(event="event-1", bookmaker="book-a", price=2.0, capture=previous_capture),
        _row(event="event-2", bookmaker="book-a", price=3.0, capture=previous_capture),
        _row(
            event="event-2",
            bookmaker="book-b",
            market="totals",
            outcome="Over",
            point=2.5,
            price=1.8,
            capture=previous_capture,
        ),
    ]
    current = [
        _row(event="event-1", bookmaker="book-a", price=2.2, capture=current_capture),
        _row(event="event-2", bookmaker="book-a", price=2.9, capture=current_capture),
        _row(
            event="event-2",
            bookmaker="book-b",
            market="totals",
            outcome="Over",
            point=2.5,
            price=1.8,
            capture=current_capture,
        ),
    ]

    comparison = compare_acquisitions(current, previous)

    assert comparison["direction_counts"] == {"UP": 1, "DOWN": 1, "UNCHANGED": 1}
    assert comparison["mean_absolute_delta"] == 0.1
    assert comparison["median_absolute_delta"] == 0.1
    assert comparison["maximum_absolute_delta"] == 0.2
    assert comparison["breakdowns"]["league"] == [
        {
            "key": "soccer_epl",
            "matched_offer_count": 3,
            "distinct_match_count": 2,
            "changed_offer_count": 2,
            "changed_proportion": 0.666667,
            "up_count": 1,
            "down_count": 1,
            "unchanged_count": 1,
            "mean_absolute_delta": 0.1,
        }
    ]
    assert [item["key"] for item in comparison["breakdowns"]["bookmaker"]] == [
        "book-a",
        "book-b",
    ]
    assert [item["key"] for item in comparison["breakdowns"]["market"]] == [
        "h2h",
        "totals",
    ]


def test_html_is_self_contained_paginated_searchable_and_safe() -> None:
    malicious = _row()
    malicious["match"] = "</script><img src=x onerror=alert(1)>"
    snapshot = build_dashboard_snapshot(
        _report(rows=[malicious]), previous_report=None, generated_at=NOW
    )
    rendered = render_dashboard_html(snapshot, csv_filename="robin-real-data.csv")
    html = rendered.decode("utf-8")
    assert "<script src=" not in html
    assert 'id="search"' in html
    assert 'id="league-filter"' in html
    assert 'id="market-filter"' in html
    assert "Provenance des métriques" in html
    assert RECURRING_CLAIM_IDS[0] in html
    assert 'id="bookmaker-filter"' in html
    assert 'id="status-filter"' in html
    assert 'id="reset-filters"' in html
    assert 'id="previous-page"' in html
    assert 'id="next-page"' in html
    assert 'id="freshness-status"' in html
    assert 'id="freshness-detail"' in html
    assert "function refreshFreshness" in html
    assert "Date.now()" in html
    assert "freshness_limit_seconds" in html
    assert "setInterval(refreshFreshness,60000)" in html
    assert 'href="robin-real-data.csv"' in html
    assert "const PAGE_SIZE = 100" in html
    assert "Aucun edge n’est validé" in html
    assert "Heures affichées en UTC" in html
    assert "</script><img" not in html
    escaped_closing_script = "\\u003c" + "/script" + "\\u003e"
    assert escaped_closing_script in html
    assert html.count("<tbody") == 1
    assert html.count("<tr") < 20


def test_partial_incident_and_empty_filter_state_are_visible() -> None:
    snapshot = build_dashboard_snapshot(
        _report(
            status="REAL_DATA_PARTIAL",
            diagnostic={
                "stage": "BODY_READ",
                "code": "LIVE_TRANSPORT_DISPATCH_FAILED",
                "exception_class": "OSError",
                "errno": 9,
                "http_status": 200,
            },
        ),
        previous_report=None,
        generated_at=NOW,
    )
    html = render_dashboard_html(snapshot).decode("utf-8")
    assert "LIVE_TRANSPORT_DISPATCH_FAILED" in html
    assert "Aucune observation ne correspond aux filtres" in html
    assert "Panne de collecte" in html
    assert "Marché absent" in html
