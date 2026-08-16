from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from robin.data_snapshot.profiling import (
    _capture_coverage,
    _capture_rows,
    _readiness,
    _selected_fixture_mapping_counts,
    _temporal_report,
    profile_batch,
)
from robin.data_snapshot.source import VerifiedBatch, VerifiedCapture

ROOT = Path(__file__).parents[2]
PROTOCOLS = ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json"
READINESS_MATRIX = ROOT / "reports" / "data-sourcing" / "experiment-data-window-matrix-v1.json"
HASH = "a" * 64


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _capture(
    *,
    first_observed_at: datetime,
    raw_payload: list[dict[str, Any]] | None = None,
    technical_available_at: list[datetime] | None = None,
) -> VerifiedCapture:
    rows = tuple(
        {
            "available_at": _utc(value),
            "fixture_id": "fixture-1",
            "provider_event_id": "event-1",
        }
        for value in (technical_available_at or [])
    )
    return VerifiedCapture(
        label="C0",
        receipt_id=HASH,
        receipt_file_sha256=HASH,
        raw_payload_sha256=HASH,
        raw_payload_size=1,
        request_fingerprint_sha256=HASH,
        schema_fingerprint_sha256=HASH,
        first_observed_at=_utc(first_observed_at),
        ingested_at=_utc(first_observed_at + timedelta(seconds=1)),
        available_at=_utc(first_observed_at),
        delete_after=_utc(first_observed_at + timedelta(days=30)),
        normalized_source_sha256=HASH if technical_available_at is not None else None,
        quota={},
        mapping_statuses=("FIXTURE_MAPPING_PROVEN",),
        mapping_revision="test-mapping-v1",
        fixture_mappings=(
            {
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
                "status": "FIXTURE_MAPPING_PROVEN",
            },
        ),
        raw_payload=raw_payload or [],
        source_normalized_rows=rows,
        technical_harness_contract_verified=technical_available_at is not None,
    )


def _batch(
    captures: tuple[VerifiedCapture, ...],
    selected_fixtures: tuple[dict[str, Any], ...],
    *,
    capture_windows: tuple[dict[str, Any], ...] = (),
) -> VerifiedBatch:
    reference = datetime(2026, 1, 3, 12, tzinfo=UTC)
    return VerifiedBatch(
        batch_id="TEST_BATCH",
        finalized_at=_utc(reference),
        source_manifest_sha256=HASH,
        source_manifest_logical_path="capture-manifest.json",
        source_manifest={},
        finalized_marker_sha256=HASH,
        sha256sums_sha256=HASH,
        inventory=(),
        captures=captures,
        capture_windows=capture_windows,
        selected_fixtures=selected_fixtures,
        retention_policy_sha256=HASH,
        capture_code_revision="test",
        capture_harness_version="test",
        leak_tokens={},
        network_attempts=0,
        secret_reads=0,
        stable_observation_seconds=300,
    )


def _target_report(
    window: str,
    *,
    first_observed_at: datetime,
    technical_available_at: list[datetime],
    earliest: datetime,
    latest: datetime,
    kickoff: datetime,
) -> dict[str, Any]:
    capture = _capture(
        first_observed_at=first_observed_at,
        technical_available_at=technical_available_at,
    )
    capture = replace(
        capture,
        raw_payload=[{"commence_time": _utc(kickoff), "id": "event-1"}],
    )
    batch = VerifiedBatch(
        batch_id="TEST_BATCH",
        finalized_at=_utc(kickoff),
        source_manifest_sha256=HASH,
        source_manifest_logical_path="capture-manifest.json",
        source_manifest={},
        finalized_marker_sha256=HASH,
        sha256sums_sha256=HASH,
        inventory=(),
        captures=(capture,),
        capture_windows=(
            {
                "capture_label": "C0",
                "earliest_admissible": _utc(earliest),
                "fixture_id": "fixture-1",
                "kickoff": _utc(kickoff),
                "latest_admissible": _utc(latest),
                "temporal_role": "TARGET",
                "window_id": window,
            },
        ),
        selected_fixtures=({"fixture_id": "fixture-1"},),
        retention_policy_sha256=HASH,
        capture_code_revision="test",
        capture_harness_version="test",
        leak_tokens={},
        network_attempts=0,
        secret_reads=0,
        stable_observation_seconds=300,
    )
    report, _ = _temporal_report(batch)
    return cast(dict[str, Any], report["entries"][0])


@pytest.mark.parametrize(
    ("window", "predictor_hours", "target_hours"),
    (("H1", 2, 1), ("H2", 24, 2)),
)
def test_target_h1_h2_are_role_bound_to_the_pr57_cutoff_and_technical_row_max(
    window: str, predictor_hours: int, target_hours: int
) -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    predictor_cutoff = kickoff - timedelta(hours=predictor_hours)
    target_nominal = kickoff - timedelta(hours=target_hours)
    target_end = target_nominal + timedelta(minutes=5)
    observed = target_nominal - timedelta(minutes=5)
    earliest = target_nominal - timedelta(minutes=15)

    valid = _target_report(
        window,
        first_observed_at=observed,
        technical_available_at=[observed, target_nominal],
        earliest=earliest,
        latest=target_end,
        kickoff=kickoff,
    )
    assert valid["status"] == "WINDOW_VALID"
    assert valid["availability_source"] == "TECHNICAL_NORMALIZED_ROWS"
    assert valid["available_at"] == _utc(target_nominal)
    assert valid["normalized_row_available_at_max"] == _utc(target_nominal)
    assert valid["target_predictor_cutoff_at"] == _utc(predictor_cutoff)
    assert valid["target_window_end_at"] == _utc(target_end)

    at_predictor_cutoff = _target_report(
        window,
        first_observed_at=predictor_cutoff,
        technical_available_at=[predictor_cutoff],
        earliest=predictor_cutoff,
        latest=target_end,
        kickoff=kickoff,
    )
    assert at_predictor_cutoff["status"] == "WINDOW_MISSED"
    assert (
        at_predictor_cutoff["window_contract_issue"]
        == "TARGET_AVAILABLE_AT_OUTSIDE_ROLE_BOUND_WINDOW"
    )

    late_row = target_end + timedelta(minutes=1)
    late = _target_report(
        window,
        first_observed_at=observed,
        technical_available_at=[observed, late_row],
        earliest=earliest,
        latest=target_end,
        kickoff=kickoff,
    )
    assert late["status"] == "WINDOW_MISSED"
    assert late["available_at"] == _utc(late_row)
    assert late["normalized_row_available_at_max"] == _utc(late_row)


def _market_capture(
    h2h_outcomes: list[dict[str, Any]],
    totals_outcomes: list[dict[str, Any]],
    *,
    bookmaker_count: int = 1,
) -> VerifiedCapture:
    observed = datetime(2026, 1, 1, tzinfo=UTC)
    last_update = _utc(observed - timedelta(seconds=1))
    raw_payload = [
        {
            "away_team": "Away",
            "bookmakers": [
                {
                    "key": f"bookmaker-{index + 1}",
                    "last_update": last_update,
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": last_update,
                            "outcomes": h2h_outcomes,
                        },
                        {
                            "key": "totals",
                            "last_update": last_update,
                            "outcomes": totals_outcomes,
                        },
                    ],
                }
                for index in range(bookmaker_count)
            ],
            "home_team": "Home",
            "id": "event-1",
        }
    ]
    return _capture(first_observed_at=observed, raw_payload=raw_payload)


def _coverage_tokens(
    h2h_outcomes: list[dict[str, Any]], totals_outcomes: list[dict[str, Any]]
) -> tuple[dict[str, Any], set[str]]:
    capture = _market_capture(h2h_outcomes, totals_outcomes, bookmaker_count=5)
    rows, duplicates = _capture_rows(capture)
    coverage, _, _, _, contract_markets = _capture_coverage(capture, rows, duplicates)
    return coverage, contract_markets


def test_contract_market_coverage_requires_exact_cardinality_and_totals_2_5() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    coverage, tokens = _coverage_tokens(exact_h2h, exact_totals)
    assert tokens == {"h2h", "totals:2.5"}
    assert coverage["h2h_completeness"]["numerator"] == 5
    assert coverage["totals_completeness"]["numerator"] == 5

    extra_h2h = [*exact_h2h, {"name": "Other", "price": 9.0}]
    extra_total = [*exact_totals, {"name": "Push", "point": 2.5, "price": 9.0}]
    coverage, tokens = _coverage_tokens(extra_h2h, extra_total)
    assert tokens == set()
    assert coverage["outcome_cardinality"] == {"h2h": {"4": 5}, "totals": {"3": 5}}

    wrong_line = [
        {"name": "Over", "point": 3.5, "price": 1.9},
        {"name": "Under", "point": 3.5, "price": 2.0},
    ]
    coverage, tokens = _coverage_tokens(exact_h2h, wrong_line)
    assert tokens == {"h2h"}
    assert coverage["line_consistency"]["numerator"] == 5
    assert coverage["totals_completeness"]["numerator"] == 0


def test_h2h_contract_token_requires_five_complete_bookmakers_per_fixture() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]

    one_bookmaker = _market_capture(exact_h2h, exact_totals, bookmaker_count=1)
    rows, duplicates = _capture_rows(one_bookmaker)
    _, _, _, _, one_bookmaker_tokens = _capture_coverage(one_bookmaker, rows, duplicates)
    assert "h2h" not in one_bookmaker_tokens
    assert "totals:2.5" in one_bookmaker_tokens

    five_bookmakers = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    rows, duplicates = _capture_rows(five_bookmakers)
    _, _, _, _, five_bookmaker_tokens = _capture_coverage(five_bookmakers, rows, duplicates)
    assert "h2h" in five_bookmaker_tokens


def test_contract_market_tokens_require_complete_scoped_timestamps() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]

    def tokens(capture: VerifiedCapture) -> set[str]:
        rows, duplicates = _capture_rows(capture)
        return _capture_coverage(capture, rows, duplicates)[4]

    valid = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    assert tokens(valid) == {"h2h", "totals:2.5"}

    missing_bookmaker_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    missing_bookmaker_event = cast(list[dict[str, Any]], missing_bookmaker_timestamp.raw_payload)[0]
    cast(list[dict[str, Any]], missing_bookmaker_event["bookmakers"])[0].pop("last_update")
    assert tokens(missing_bookmaker_timestamp) == set()

    invalid_bookmaker_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    invalid_bookmaker_event = cast(list[dict[str, Any]], invalid_bookmaker_timestamp.raw_payload)[0]
    cast(list[dict[str, Any]], invalid_bookmaker_event["bookmakers"])[0]["last_update"] = (
        "not-a-timestamp"
    )
    assert tokens(invalid_bookmaker_timestamp) == set()

    missing_h2h_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    missing_h2h_event = cast(list[dict[str, Any]], missing_h2h_timestamp.raw_payload)[0]
    missing_h2h_market = cast(
        list[dict[str, Any]],
        cast(list[dict[str, Any]], missing_h2h_event["bookmakers"])[0]["markets"],
    )[0]
    missing_h2h_market.pop("last_update")
    assert tokens(missing_h2h_timestamp) == {"totals:2.5"}

    invalid_h2h_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    invalid_h2h_event = cast(list[dict[str, Any]], invalid_h2h_timestamp.raw_payload)[0]
    invalid_h2h_market = cast(
        list[dict[str, Any]],
        cast(list[dict[str, Any]], invalid_h2h_event["bookmakers"])[0]["markets"],
    )[0]
    invalid_h2h_market["last_update"] = "not-a-timestamp"
    valid_rows, valid_duplicates = _capture_rows(valid)
    invalid_h2h_tokens = _capture_coverage(invalid_h2h_timestamp, valid_rows, valid_duplicates)[4]
    assert invalid_h2h_tokens == {"totals:2.5"}

    missing_totals_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    missing_totals_event = cast(list[dict[str, Any]], missing_totals_timestamp.raw_payload)[0]
    missing_totals_market = cast(
        list[dict[str, Any]],
        cast(list[dict[str, Any]], missing_totals_event["bookmakers"])[0]["markets"],
    )[1]
    missing_totals_market.pop("last_update")
    assert tokens(missing_totals_timestamp) == {"h2h"}

    invalid_totals_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    invalid_totals_event = cast(list[dict[str, Any]], invalid_totals_timestamp.raw_payload)[0]
    invalid_totals_market = cast(
        list[dict[str, Any]],
        cast(list[dict[str, Any]], invalid_totals_event["bookmakers"])[0]["markets"],
    )[1]
    invalid_totals_market["last_update"] = "not-a-timestamp"
    invalid_totals_tokens = _capture_coverage(
        invalid_totals_timestamp, valid_rows, valid_duplicates
    )[4]
    assert invalid_totals_tokens == {"h2h"}

    unrelated_missing_timestamp = _market_capture(exact_h2h, exact_totals, bookmaker_count=5)
    unrelated_event = cast(list[dict[str, Any]], unrelated_missing_timestamp.raw_payload)[0]
    for bookmaker in cast(list[dict[str, Any]], unrelated_event["bookmakers"]):
        cast(list[dict[str, Any]], bookmaker["markets"]).append(
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "Home", "point": -1.5, "price": 1.9},
                    {"name": "Away", "point": 1.5, "price": 2.0},
                ],
            }
        )
    assert tokens(unrelated_missing_timestamp) == {"h2h", "totals:2.5"}


def test_contract_market_token_requires_complete_coverage_not_one_passing_object() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    capture = _market_capture(exact_h2h, exact_totals)
    event = cast(list[dict[str, Any]], capture.raw_payload)[0]
    first_bookmaker = cast(list[dict[str, Any]], event["bookmakers"])[0]
    incomplete = json.loads(json.dumps(first_bookmaker))
    incomplete["key"] = "bookmaker-incomplete"
    incomplete["markets"][0]["outcomes"].pop()
    event["bookmakers"].append(incomplete)
    rows, duplicates = _capture_rows(capture)
    coverage, _, _, _, contract_markets = _capture_coverage(capture, rows, duplicates)
    assert coverage["h2h_completeness"]["numerator"] == 1
    assert coverage["h2h_completeness"]["denominator"] == 2
    assert "h2h" not in contract_markets
    assert "totals:2.5" in contract_markets


def test_event_without_bookmaker_blocks_every_contract_market_token() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    capture = _market_capture(exact_h2h, exact_totals)
    raw = cast(list[dict[str, Any]], capture.raw_payload)
    raw.append(
        {
            "away_team": "Away without bookmaker",
            "bookmakers": [],
            "home_team": "Home without bookmaker",
            "id": "event-without-bookmaker",
        }
    )
    rows, duplicates = _capture_rows(capture)
    coverage, _, _, _, contract_markets = _capture_coverage(capture, rows, duplicates)
    assert coverage["event_count"] == 2
    assert coverage["event_bookmaker_occurrence_count"] == 1
    assert contract_markets == set()


def _mapped_capture(label: str, mappings: list[dict[str, Any]]) -> VerifiedCapture:
    base = _capture(first_observed_at=datetime(2026, 1, 1, tzinfo=UTC))
    return replace(
        base,
        label=label,
        fixture_mappings=tuple(mappings),
        mapping_statuses=tuple(sorted({str(mapping["status"]) for mapping in mappings})),
    )


def test_role_bound_windows_require_the_exact_selected_fixture_set() -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    observed = kickoff - timedelta(hours=2, minutes=5)
    selected = tuple(
        {"fixture_id": f"selected-{index}", "provider_event_id": f"selected-provider-{index}"}
        for index in range(5)
    )
    mappings = [
        {
            "fixture_id": fixture_id,
            "provider_event_id": provider_event_id,
            "status": "FIXTURE_MAPPING_PROVEN",
        }
        for fixture_id, provider_event_id in [
            *((f"selected-{index}", f"selected-provider-{index}") for index in range(5)),
            *((f"foreign-{index}", f"foreign-provider-{index}") for index in range(5)),
        ]
    ]
    capture = replace(
        _mapped_capture("C0", mappings),
        first_observed_at=_utc(observed),
        ingested_at=_utc(observed + timedelta(seconds=1)),
        available_at=_utc(observed),
        delete_after=_utc(observed + timedelta(days=30)),
    )

    def windows(prefix: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "capture_label": "C0",
                "earliest_admissible": _utc(kickoff - timedelta(hours=2, minutes=15)),
                "fixture_id": f"{prefix}-{index}",
                "kickoff": _utc(kickoff),
                "latest_admissible": _utc(kickoff - timedelta(hours=2)),
                "temporal_role": "PREDICTOR",
                "window_id": "H2",
            }
            for index in range(5)
        )

    normalized_rows = {
        "C0": [
            {"available_at": _utc(observed), "provider_event_id": mapping["provider_event_id"]}
            for mapping in mappings
        ]
    }
    foreign_batch = _batch((capture,), selected, capture_windows=windows("foreign"))
    report, roles = _temporal_report(foreign_batch, normalized_rows)
    assert report["status_counts"] == {"WINDOW_VALID": 5}
    assert roles == ()

    selected_batch = replace(foreign_batch, capture_windows=windows("selected"))
    _, roles = _temporal_report(selected_batch, normalized_rows)
    assert roles == ("PREDICTOR:H2",)


def test_cross_capture_mapping_conflict_blocks_selected_window_and_role() -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    observed = kickoff - timedelta(hours=2, minutes=5)
    selected = tuple(
        {"fixture_id": f"fixture-{index}", "provider_event_id": f"event-{index}"}
        for index in range(1, 6)
    )
    mappings = [
        {
            "fixture_id": f"fixture-{index}",
            "provider_event_id": f"event-{index}",
            "status": "FIXTURE_MAPPING_PROVEN",
        }
        for index in range(1, 6)
    ]

    def timed(capture: VerifiedCapture) -> VerifiedCapture:
        return replace(
            capture,
            first_observed_at=_utc(observed),
            ingested_at=_utc(observed + timedelta(seconds=1)),
            available_at=_utc(observed),
            delete_after=_utc(observed + timedelta(days=30)),
        )

    first = timed(_mapped_capture("C0", mappings))
    second = replace(
        timed(
            _mapped_capture(
                "C1",
                [
                    {
                        "fixture_id": "fixture-1",
                        "provider_event_id": "event-other",
                        "status": "FIXTURE_MAPPING_PROVEN",
                    }
                ],
            )
        ),
        receipt_id="b" * 64,
    )
    windows = tuple(
        {
            "capture_label": "C0",
            "earliest_admissible": _utc(kickoff - timedelta(hours=2, minutes=15)),
            "fixture_id": f"fixture-{index}",
            "kickoff": _utc(kickoff),
            "latest_admissible": _utc(kickoff - timedelta(hours=2)),
            "temporal_role": "PREDICTOR",
            "window_id": "H2",
        }
        for index in range(1, 6)
    )
    rows = {
        "C0": [
            {"available_at": _utc(observed), "provider_event_id": f"event-{index}"}
            for index in range(1, 6)
        ]
    }
    batch = _batch((first, second), selected, capture_windows=windows)
    report, roles = _temporal_report(batch, rows)
    assert _selected_fixture_mapping_counts(batch) == {
        "FIXTURE_MAPPING_CONFLICT": 1,
        "FIXTURE_MAPPING_PROVEN": 4,
    }
    assert report["status_counts"] == {
        "WINDOW_MAPPING_AMBIGUOUS": 1,
        "WINDOW_VALID": 4,
    }
    conflicted = cast(dict[str, Any], report["entries"][0])
    assert conflicted["mapping_status"] == "FIXTURE_MAPPING_CONFLICT"
    assert conflicted["window_contract_issue"] == "BATCH_WIDE_SELECTED_MAPPING_NOT_PROVEN"
    assert roles == ()


def test_unproven_mapping_cannot_validate_or_cover_a_window() -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    observed = kickoff - timedelta(hours=2, minutes=5)
    capture = replace(
        _mapped_capture(
            "C0",
            [
                {
                    "fixture_id": "fixture-1",
                    "provider_event_id": "event-1",
                    "status": "FIXTURE_MAPPING_UNPROVEN",
                }
            ],
        ),
        first_observed_at=_utc(observed),
        ingested_at=_utc(observed + timedelta(seconds=1)),
        available_at=_utc(observed),
        delete_after=_utc(observed + timedelta(days=30)),
    )
    window = {
        "capture_label": "C0",
        "earliest_admissible": _utc(kickoff - timedelta(hours=2, minutes=15)),
        "fixture_id": "fixture-1",
        "kickoff": _utc(kickoff),
        "latest_admissible": _utc(kickoff - timedelta(hours=2)),
        "temporal_role": "PREDICTOR",
        "window_id": "H2",
    }
    batch = _batch(
        (capture,),
        ({"fixture_id": "fixture-1", "provider_event_id": "event-1"},),
        capture_windows=(window,),
    )
    report, roles = _temporal_report(
        batch,
        {"C0": [{"available_at": _utc(observed), "provider_event_id": "event-1"}]},
    )
    entry = cast(dict[str, Any], report["entries"][0])
    assert entry["mapping_status"] == "FIXTURE_MAPPING_UNPROVEN"
    assert entry["status"] == "WINDOW_MAPPING_AMBIGUOUS"
    assert roles == ()


def test_technical_rows_require_exact_pair_and_reject_relevant_contradiction() -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    observed = kickoff - timedelta(hours=2, minutes=5)
    capture = replace(
        _mapped_capture(
            "C0",
            [
                {
                    "fixture_id": "fixture-1",
                    "provider_event_id": "event-1",
                    "status": "FIXTURE_MAPPING_PROVEN",
                }
            ],
        ),
        first_observed_at=_utc(observed),
        ingested_at=_utc(observed + timedelta(seconds=1)),
        available_at=_utc(observed),
        delete_after=_utc(observed + timedelta(days=30)),
        normalized_source_sha256=HASH,
        raw_payload=[{"commence_time": _utc(kickoff), "id": "event-1"}],
        technical_harness_contract_verified=True,
    )
    window = {
        "capture_label": "C0",
        "earliest_admissible": _utc(kickoff - timedelta(hours=2, minutes=15)),
        "fixture_id": "fixture-1",
        "kickoff": _utc(kickoff),
        "latest_admissible": _utc(kickoff - timedelta(hours=2)),
        "temporal_role": "PREDICTOR",
        "window_id": "H2",
    }

    def temporal_entry(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], tuple[str, ...]]:
        technical_capture = replace(capture, source_normalized_rows=rows)
        batch = _batch(
            (technical_capture,),
            ({"fixture_id": "fixture-1", "provider_event_id": "event-1"},),
            capture_windows=(window,),
        )
        report, roles = _temporal_report(batch)
        return cast(dict[str, Any], report["entries"][0]), roles

    wrong_pair, wrong_roles = temporal_entry(
        (
            {
                "available_at": _utc(observed),
                "fixture_id": "fixture-1",
                "provider_event_id": "wrong-event",
            },
        )
    )
    assert wrong_pair["status"] == "WINDOW_RECEIPT_INVALID"
    assert wrong_pair["window_contract_issue"] == "TECHNICAL_NORMALIZED_ROWS_NOT_FIXTURE_BOUND"
    assert wrong_roles == ()

    exact_pair, exact_roles = temporal_entry(
        (
            {
                "available_at": _utc(observed),
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
            },
        )
    )
    assert exact_pair["status"] == "WINDOW_VALID"
    assert exact_roles == ("PREDICTOR:H2",)

    contradictory, contradictory_roles = temporal_entry(
        (
            {
                "available_at": _utc(observed),
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
            },
            {
                "available_at": _utc(observed),
                "fixture_id": "fixture-1",
                "provider_event_id": "wrong-event",
            },
        )
    )
    assert contradictory["status"] == "WINDOW_RECEIPT_INVALID"
    assert contradictory_roles == ()


def test_technical_window_requires_unique_raw_event_with_matching_kickoff() -> None:
    kickoff = datetime(2026, 1, 3, 12, tzinfo=UTC)
    observed = kickoff - timedelta(hours=2, minutes=5)
    capture = replace(
        _mapped_capture(
            "C0",
            [
                {
                    "fixture_id": "fixture-1",
                    "provider_event_id": "event-1",
                    "status": "FIXTURE_MAPPING_PROVEN",
                }
            ],
        ),
        first_observed_at=_utc(observed),
        ingested_at=_utc(observed + timedelta(seconds=1)),
        available_at=_utc(observed),
        delete_after=_utc(observed + timedelta(days=30)),
        normalized_source_sha256=HASH,
        source_normalized_rows=(
            {
                "available_at": _utc(observed),
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
            },
        ),
        technical_harness_contract_verified=True,
    )
    window = {
        "capture_label": "C0",
        "earliest_admissible": _utc(kickoff - timedelta(hours=2, minutes=15)),
        "fixture_id": "fixture-1",
        "kickoff": _utc(kickoff),
        "latest_admissible": _utc(kickoff - timedelta(hours=2)),
        "temporal_role": "PREDICTOR",
        "window_id": "H2",
    }

    def temporal_entry(
        raw_events: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        technical_capture = replace(capture, raw_payload=raw_events)
        batch = _batch(
            (technical_capture,),
            ({"fixture_id": "fixture-1", "provider_event_id": "event-1"},),
            capture_windows=(window,),
        )
        report, roles = _temporal_report(batch)
        return cast(dict[str, Any], report["entries"][0]), roles

    exact, exact_roles = temporal_entry([{"commence_time": _utc(kickoff), "id": "event-1"}])
    assert exact["status"] == "WINDOW_VALID"
    assert exact_roles == ("PREDICTOR:H2",)

    mismatch, mismatch_roles = temporal_entry(
        [{"commence_time": _utc(kickoff + timedelta(days=1)), "id": "event-1"}]
    )
    assert mismatch["status"] == "WINDOW_RECEIPT_INVALID"
    assert mismatch["window_contract_issue"] == "TECHNICAL_RAW_EVENT_KICKOFF_NOT_FIXTURE_BOUND"
    assert mismatch_roles == ()

    duplicate, duplicate_roles = temporal_entry(
        [
            {"commence_time": _utc(kickoff), "id": "event-1"},
            {"commence_time": _utc(kickoff), "id": "event-1"},
        ]
    )
    assert duplicate["status"] == "WINDOW_RECEIPT_INVALID"
    assert duplicate_roles == ()


def test_selected_fixture_mapping_counts_are_cross_capture_and_fail_closed() -> None:
    selections = tuple(
        {"fixture_id": f"fixture-{index}", "provider_event_id": f"event-{index}"}
        for index in range(1, 5)
    )
    first = _mapped_capture(
        "C0",
        [
            {
                "fixture_id": f"fixture-{index}",
                "provider_event_id": f"event-{index}",
                "status": "FIXTURE_MAPPING_PROVEN" if index < 4 else "FIXTURE_MAPPING_UNPROVEN",
            }
            for index in range(1, 5)
        ],
    )
    second = _mapped_capture(
        "C1",
        [
            {
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
                "status": "FIXTURE_MAPPING_PROVEN",
            },
            {
                # Same selected fixture, different provider identity: conflict
                # even though this individual row claims PROVEN.
                "fixture_id": "fixture-2",
                "provider_event_id": "event-other",
                "status": "FIXTURE_MAPPING_PROVEN",
            },
            {
                "fixture_id": "fixture-3",
                "provider_event_id": "event-3",
                "status": "FIXTURE_MAPPING_AMBIGUOUS",
            },
            {
                # An unselected conflict must not inflate selected-fixture counts.
                "fixture_id": "fixture-99",
                "provider_event_id": "event-99",
                "status": "FIXTURE_MAPPING_CONFLICT",
            },
        ],
    )
    batch = _batch((first, second), selections)
    counts = _selected_fixture_mapping_counts(batch)
    assert counts == {
        "FIXTURE_MAPPING_AMBIGUOUS": 1,
        "FIXTURE_MAPPING_CONFLICT": 1,
        "FIXTURE_MAPPING_PROVEN": 1,
        "FIXTURE_MAPPING_UNPROVEN": 1,
    }
    assert counts["FIXTURE_MAPPING_PROVEN"] <= sum(counts.values()) == len(selections)
    assert _selected_fixture_mapping_counts(_batch((first, second), ())) == {}


def test_profile_denominators_count_selected_mappings_and_materialized_partition_rows() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    capture = _market_capture(exact_h2h, exact_totals)
    batch = _batch((capture,), ({"fixture_id": "fixture-1"},))
    result = profile_batch(
        batch,
        json.loads(PROTOCOLS.read_text(encoding="utf-8")),
        json.loads(READINESS_MATRIX.read_text(encoding="utf-8")),
    )
    partition_rows = sum(content.count(b"\n") for content in result.normalized_partitions.values())
    assert result.denominators["normalized_observation_count"] == partition_rows == 5
    assert result.denominators["selected_fixture_count"] == 1
    assert result.denominators["uniquely_mapped_fixture_count"] == 1
    assert result.quality_report["mapping_status_counts"] == {"FIXTURE_MAPPING_PROVEN": 1}


def test_profile_zero_proven_mapping_closes_data_gate_and_candidates() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    capture = replace(
        _market_capture(exact_h2h, exact_totals),
        fixture_mappings=(
            {
                "fixture_id": "fixture-1",
                "provider_event_id": "event-1",
                "status": "FIXTURE_MAPPING_UNPROVEN",
            },
        ),
        mapping_statuses=("FIXTURE_MAPPING_UNPROVEN",),
    )
    result = profile_batch(
        _batch((capture,), ({"fixture_id": "fixture-1"},)),
        json.loads(PROTOCOLS.read_text(encoding="utf-8")),
        json.loads(READINESS_MATRIX.read_text(encoding="utf-8")),
    )

    assert result.schema_report["overall_classification"] == "NO_SCHEMA_DRIFT"
    assert result.observed_fixture_count == 0
    assert result.data_gate_blocked is True
    assert result.accumulation_report["candidate_count"] == 0
    assert result.accumulation_report["candidates"] == []
    assert result.accumulation_report["verdict"] == ("DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE")


def test_profile_breaking_schema_drift_closes_data_gate_with_proven_mapping() -> None:
    exact_h2h = [
        {"name": "Home", "price": 2.1},
        {"name": "Draw", "price": 3.2},
        {"name": "Away", "price": 3.4},
    ]
    exact_totals = [
        {"name": "Over", "point": 2.5, "price": 1.9},
        {"name": "Under", "point": 2.5, "price": 2.0},
    ]
    first = _market_capture(exact_h2h, exact_totals)
    second = replace(
        _market_capture(exact_h2h, exact_totals),
        label="C1",
        receipt_id="b" * 64,
    )
    first_event = cast(list[dict[str, Any]], first.raw_payload)[0]
    second_event = cast(list[dict[str, Any]], second.raw_payload)[0]
    first_event["schema_drift_witness"] = "text"
    second_event["schema_drift_witness"] = 1
    result = profile_batch(
        _batch((first, second), ({"fixture_id": "fixture-1"},)),
        json.loads(PROTOCOLS.read_text(encoding="utf-8")),
        json.loads(READINESS_MATRIX.read_text(encoding="utf-8")),
    )

    assert result.schema_report["overall_classification"] == "BREAKING_SCHEMA_DRIFT"
    assert result.observed_fixture_count == 1
    assert result.data_gate_blocked is True
    assert result.accumulation_report["candidate_count"] == 0
    assert result.accumulation_report["candidates"] == []


def _readiness_outputs(
    observed_markets: set[str],
    *,
    data_gate_blocked: bool,
    observed_windows: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    protocols = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
    matrix = json.loads(READINESS_MATRIX.read_text(encoding="utf-8"))
    return _readiness(
        protocols,
        matrix,
        pipeline_observed_fixture_count=5,
        observed_windows=(
            observed_windows
            if observed_windows is not None
            else (
                "PREDICTOR:H24",
                "PREDICTOR:H12",
                "PREDICTOR:H6",
                "PREDICTOR:H2",
                "TARGET:H2",
                "TARGET:H1",
            )
        ),
        observed_markets=observed_markets,
        data_gate_blocked=data_gate_blocked,
    )


def _readiness_rows(observed_markets: set[str]) -> dict[str, dict[str, Any]]:
    readiness, _ = _readiness_outputs(observed_markets, data_gate_blocked=False)
    return {row["experiment_id"]: row for row in readiness["protocols"]}


def test_data_gate_blocks_accumulation_candidates_and_substantial_capture_claim() -> None:
    readiness, accumulation = _readiness_outputs({"h2h", "totals:2.5"}, data_gate_blocked=True)

    assert accumulation["candidate_count"] == 0
    assert accumulation["candidates"] == []
    assert accumulation["meaning"] == "DATA_GATE_BLOCKED_NO_SUBSTANTIAL_CAPTURE_CLAIM"
    assert accumulation["verdict"] == "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE"
    assert accumulation["economic_or_performance_ranking_used"] is False
    assert "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE" in readiness["verdicts"]
    assert readiness["performance_selection_used"] is False
    assert all(
        row["status"] not in {"ACCUMULATION_STARTED", "EXECUTABLE"}
        for row in readiness["protocols"]
    )
    assert "PIPELINE_CAN_CAPTURE_A_SUBSTANTIAL_PART" not in json.dumps(
        {"accumulation": accumulation, "readiness": readiness},
        sort_keys=True,
    )


def test_open_data_gate_keeps_five_data_distance_candidates_without_performance() -> None:
    readiness, accumulation = _readiness_outputs({"h2h", "totals:2.5"}, data_gate_blocked=False)

    assert accumulation["candidate_count"] == 5
    assert [candidate["experiment_id"] for candidate in accumulation["candidates"]] == [
        "RDS-EXP-V1-001",
        "RDS-EXP-V1-002",
        "RDS-EXP-V1-003",
        "RDS-EXP-V1-004",
        "RDS-EXP-V1-007",
    ]
    assert accumulation["meaning"] == (
        "PIPELINE_CAN_CAPTURE_A_SUBSTANTIAL_PART_OF_REQUIRED_DATA_ONLY"
    )
    assert accumulation["verdict"] == "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED"
    assert accumulation["economic_or_performance_ranking_used"] is False
    assert readiness["performance_selection_used"] is False
    assert "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE" not in readiness["verdicts"]
    for candidate in accumulation["candidates"]:
        assert candidate["selection_basis"] == [
            "single h2h predictor window",
            "shared capture with sibling protocols",
            "shortest contract distance without enriched sporting source",
        ]


@pytest.mark.parametrize("observed_markets", [set(), {"totals:2.5"}])
def test_accumulation_gate_requires_common_complete_h2h(
    observed_markets: set[str],
) -> None:
    readiness, accumulation = _readiness_outputs(
        observed_markets,
        data_gate_blocked=False,
        observed_windows=("PREDICTOR:H2",),
    )

    assert accumulation["candidate_count"] == 0
    assert accumulation["candidates"] == []
    assert accumulation["verdict"] == "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE"
    assert "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE" in readiness["verdicts"]


def test_accumulation_gate_requires_common_role_bound_predictor_h2() -> None:
    readiness, accumulation = _readiness_outputs(
        {"h2h"},
        data_gate_blocked=False,
        observed_windows=("PREDICTOR:H24", "TARGET:H1"),
    )

    assert accumulation["candidate_count"] == 0
    assert accumulation["candidates"] == []
    assert accumulation["verdict"] == "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE"
    assert "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE" in readiness["verdicts"]


def test_accumulation_gate_opens_with_h2h_and_role_bound_predictor_h2_without_totals() -> None:
    readiness, accumulation = _readiness_outputs(
        {"h2h"},
        data_gate_blocked=False,
        observed_windows=("PREDICTOR:H2",),
    )

    assert accumulation["candidate_count"] == 5
    assert len(accumulation["candidates"]) == 5
    assert accumulation["verdict"] == "FIRST_ACCUMULATION_CANDIDATES_IDENTIFIED"
    assert "DATA_GATE_BLOCKED_NO_ACCUMULATION_CANDIDATE" not in readiness["verdicts"]


def test_exp009_intermediate_windows_remain_unfrozen_and_exp010_design_gate_wins() -> None:
    rows = _readiness_rows({"h2h", "totals:2.5"})
    exp009 = rows["RDS-EXP-V1-009"]
    assert exp009["required_window_roles"] == ["PREDICTOR:H2", "PREDICTOR:H24"]
    assert "PREDICTOR:H12" not in exp009["required_window_roles"]
    assert "PREDICTOR:H6" not in exp009["required_window_roles"]
    assert exp009["minimum_snapshot_contract"]["predictor_snapshots"] == 4
    assert exp009["unfrozen_intermediate_predictor_windows"] == {
        "count": 2,
        "names": [],
        "status": "NOT_FROZEN_PROTOCOL_SUCCESSOR_REQUIRED",
    }
    assert exp009["status"] == "PROTOCOL_SUCCESSOR_REQUIRED"

    exp010 = rows["RDS-EXP-V1-010"]
    assert exp010["status"] == "DATA_GATE_BLOCKED"
    assert any(
        "EXP010_RECEIPT_TIME_VS_MARKET_LAST_UPDATE_CLOCK_SEMANTICS" in gate
        for gate in exp010["blocking_gates"]
    )

    without_exact_total = _readiness_rows({"h2h", "totals"})
    exp023 = without_exact_total["RDS-EXP-V1-023"]
    assert "totals:2.5" in exp023["next_required_accumulation"]["missing_markets"]
    assert "MISSING_MARKET:totals:2.5" in exp023["blocking_gates"]


def test_readiness_rows_preserve_full_matrix_contracts_labels_holdout_and_supersedes() -> None:
    rows = _readiness_rows({"h2h", "totals:2.5"})
    matrix = json.loads(READINESS_MATRIX.read_text(encoding="utf-8"))
    protocols = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
    matrix_row = next(
        row for row in matrix["experiments"] if row["experiment_id"] == "RDS-EXP-V1-005"
    )
    protocol = next(
        row for row in protocols["experiments"] if row["experiment_id"] == "RDS-EXP-V1-005"
    )
    readiness = rows["RDS-EXP-V1-005"]
    for field in (
        "bookmaker_grain",
        "labels",
        "league_grain",
        "maximum_staleness",
        "metadata",
        "minimum_snapshots",
        "predictor_cutoff",
        "receipt_requirements",
        "settlement_requirements",
        "target_window",
    ):
        assert readiness[field] == matrix_row[field]
    assert readiness["required_labels"] == matrix_row["labels"]
    assert readiness["holdout_contract"] == {
        "holdout": protocol["holdout"],
        "league_holdout": protocol["league_holdout"],
        "season_holdout": protocol["season_holdout"],
        "walk_forward": protocol["walk_forward"],
    }
    assert "supersedes_receipt_id" in readiness["required_source_receipts"]
