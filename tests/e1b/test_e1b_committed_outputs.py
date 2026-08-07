from __future__ import annotations

import hashlib
from pathlib import Path

from robin.historical_deep.e1b_canary import (
    REPORT_FILENAMES,
    mapping,
    read_json,
    sequence,
    validate_reports,
)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports/evidence/e1b"


def test_committed_e1b_reports_are_valid_and_replay_bound() -> None:
    reports = {
        name: read_json(REPORTS / filename)
        for name, filename in REPORT_FILENAMES.items()
        if name != "replay_verification"
    }
    validate_reports(reports)
    replay = read_json(REPORTS / REPORT_FILENAMES["replay_verification"])
    hashes = mapping(replay["all_report_hashes"], "E1B_REPORT_HASHES")

    assert replay["replay_identical"] is True
    assert replay["r2_gets_during_replay"] == 0
    for name in reports:
        payload = (REPORTS / REPORT_FILENAMES[name]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == hashes[name]


def test_e1a_unknowns_are_not_projected_into_e1b_league_rows() -> None:
    measurement = read_json(REPORTS / "e1b-measurement-v1.json")
    exact_rows = [
        mapping(item, "E1B_EXACT_ROW")
        for item in sequence(measurement["measurements"], "E1B_ROWS")
        if mapping(item, "E1B_ROW")["capability_id"] == "ABSENCE_CAUSE_EXACT"
    ]
    exact_aggregate = next(
        mapping(item, "E1B_EXACT_AGGREGATE")
        for item in sequence(
            measurement["weighted_capability_aggregates"], "E1B_AGGREGATES"
        )
        if mapping(item, "E1B_AGGREGATE")["capability_id"]
        == "ABSENCE_CAUSE_EXACT"
    )

    assert len(exact_rows) == 5
    assert all(item["unclassifiable"] == 0 for item in exact_rows)
    assert exact_aggregate["unclassifiable"] == 0
    assert measurement["historical_e1a_partition"] == {
        "absence_cause_unknown": 149,
        "identity": "3036 = 2681 + 206 + 149",
        "injury_confirmed": 2681,
        "suspension_confirmed": 206,
        "total": 3036,
    }


def test_committed_costs_and_hold_boundary_are_exact() -> None:
    measurement = read_json(REPORTS / "e1b-measurement-v1.json")
    costs = read_json(REPORTS / "e1b-costs-v1.json")

    assert costs["logical_gets"] == 21
    assert costs["bytes_read"] == 1_107_479
    assert costs["provider_calls"] == 0
    assert costs["r2_writes"] == 0
    assert costs["sql_queries"] == 0
    assert measurement["mission_decision"] == "PASS_AND_HOLD"
    assert measurement["e2_executed"] is False
    assert measurement["ready_strict_declared"] == 0
    assert measurement["ready_reconstructed_declared"] == 0
