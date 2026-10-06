from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from robin.capture.descriptive_experiment import (
    ExperimentInputError,
    calculate_descriptive_experiment,
    load_verified_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/experiments/robin-descriptive-20261005-0800-1000.json"


def _row(
    *,
    sport: str = "soccer_epl",
    event: str = "event-1",
    bookmaker: str = "book-a",
    market: str = "h2h",
    outcome: str = "Arsenal",
    point: float | None = None,
    price: float = 2.0,
    slot: str = "2026-10-05T08:00:00Z",
) -> dict[str, object]:
    return {
        "slot_start_utc": slot,
        "sport_key": sport,
        "capture_time_utc": slot.replace(":00:00Z", ":12:00Z"),
        "source_timestamp_utc": slot.replace(":00:00Z", ":11:00Z"),
        "event_id": event,
        "match": "Arsenal — Leeds United",
        "kickoff_utc": "2026-10-10T11:30:00Z",
        "bookmaker_key": bookmaker,
        "bookmaker": bookmaker,
        "market_key": market,
        "outcome": outcome,
        "point": point,
        "price": price,
        "branch_status": "PARTIAL",
    }


def _report(run_id: str, slot: str, rows: list[dict[str, object]]) -> dict[str, object]:
    sports = sorted({str(row["sport_key"]) for row in rows})
    return {
        "schema_version": "robin-real-data-dashboard-v1",
        "mission_id": "ROBIN_AUTONOMOUS_LAB_20261004",
        "github_run_id": run_id,
        "repository_sha": "a" * 40,
        "slot_start_utc": slot,
        "data_slot_start_utc": slot,
        "data_role": "CURRENT",
        "summary": {
            "row_count": len(rows),
            "match_count": len({row["event_id"] for row in rows}),
            "bookmaker_count": len({row["bookmaker_key"] for row in rows}),
            "validated_capture_count": len(sports),
            "incomplete_branch_count": 0,
        },
        "coverage": {sport: {"h2h": {}, "totals": {}} for sport in sports},
        "rows": rows,
    }


def _bundle(tmp_path: Path, report: dict[str, object]) -> Path:
    root = tmp_path / str(report["github_run_id"])
    root.mkdir(parents=True)
    payload = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (root / "robin-real-data.json").write_bytes(payload)
    receipt = {
        "schema_version": "robin-autonomous-lab-public-receipt-v1",
        "mission_id": report["mission_id"],
        "github_run_id": report["github_run_id"],
        "delivery_github_run_id": report["github_run_id"],
        "slot_start_utc": report["slot_start_utc"],
        "display_data_slot_start_utc": report["slot_start_utc"],
        "display_data_role": "CURRENT",
        "row_count": len(report["rows"]),
        "display_row_count": len(report["rows"]),
        "validated_capture_count": report["summary"]["validated_capture_count"],
        "incomplete_branch_count": 0,
        "normalized_json_sha256": hashlib.sha256(payload).hexdigest(),
        "private_report_r2_status": "VERIFIED",
        "replayed_existing_slot": False,
    }
    (root / "public-receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return root


def test_verified_bundle_rejects_hash_mismatch(tmp_path: Path) -> None:
    rows = [_row()]
    root = _bundle(tmp_path, _report("10", "2026-10-05T08:00:00Z", rows))
    (root / "robin-real-data.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ExperimentInputError, match="SOURCE_HASH_MISMATCH"):
        load_verified_bundle(root)


def test_independent_calculator_separates_prices_thresholds_and_missing_branches(
    tmp_path: Path,
) -> None:
    previous_rows = [
        _row(outcome="Arsenal", price=2.0),
        _row(outcome="Draw", price=3.0),
        _row(market="totals", outcome="Over", point=2.5, price=1.8),
        _row(market="totals", outcome="Over", point=3.5, price=2.4),
        _row(sport="soccer_france_ligue_one", event="event-2", price=1.5),
    ]
    current_rows = [
        _row(outcome="Arsenal", price=2.2, slot="2026-10-05T10:00:00Z"),
        _row(outcome="Draw", price=3.0, slot="2026-10-05T10:00:00Z"),
        _row(
            market="totals",
            outcome="Over",
            point=3.5,
            price=2.1,
            slot="2026-10-05T10:00:00Z",
        ),
        _row(
            market="totals",
            outcome="Under",
            point=2.5,
            price=2.0,
            slot="2026-10-05T10:00:00Z",
        ),
    ]
    previous = load_verified_bundle(
        _bundle(tmp_path, _report("10", "2026-10-05T08:00:00Z", previous_rows))
    )
    current = load_verified_bundle(
        _bundle(tmp_path, _report("11", "2026-10-05T10:00:00Z", current_rows))
    )

    result = calculate_descriptive_experiment(previous, current)

    assert result["matched_offer_count"] == 3
    assert result["changed_offer_count"] == 2
    assert result["direction_counts"] == {"UP": 1, "DOWN": 1, "UNCHANGED": 1}
    assert result["appeared_offer_count"] == 1
    assert result["not_observed_offer_count"] == 1
    assert result["excluded_row_count"] == 1
    assert result["exclusion_reason_counts"] == {"BRANCH_NOT_COMPARABLE": 1}
    assert result["comparable_sport_keys"] == ["soccer_epl"]
    assert result["breakdowns"]["market"] == [
        {
            "key": "h2h",
            "matched_offer_count": 2,
            "distinct_match_count": 1,
            "changed_offer_count": 1,
            "changed_proportion": 0.5,
            "up_count": 1,
            "down_count": 0,
            "unchanged_count": 1,
            "mean_absolute_delta": 0.1,
        },
        {
            "key": "totals",
            "matched_offer_count": 1,
            "distinct_match_count": 1,
            "changed_offer_count": 1,
            "changed_proportion": 1.0,
            "up_count": 0,
            "down_count": 1,
            "unchanged_count": 0,
            "mean_absolute_delta": 0.3,
        },
    ]


def test_independent_calculator_excludes_ambiguous_and_invalid_keys(tmp_path: Path) -> None:
    duplicated = _row(outcome="Arsenal", price=2.0)
    previous_rows = [duplicated, dict(duplicated), _row(outcome="Draw", price=0)]
    current_rows = [
        _row(outcome="Arsenal", price=2.2, slot="2026-10-05T10:00:00Z"),
        _row(outcome="Draw", price=3.0, slot="2026-10-05T10:00:00Z"),
    ]
    previous = load_verified_bundle(
        _bundle(tmp_path, _report("10", "2026-10-05T08:00:00Z", previous_rows))
    )
    current = load_verified_bundle(
        _bundle(tmp_path, _report("11", "2026-10-05T10:00:00Z", current_rows))
    )

    result = calculate_descriptive_experiment(previous, current)

    assert result["matched_offer_count"] == 0
    assert result["appeared_offer_count"] == 0
    assert result["not_observed_offer_count"] == 0
    assert result["excluded_row_count"] == 5
    assert result["exclusion_reason_counts"] == {
        "AMBIGUOUS_OFFER_IDENTITY": 3,
        "INVALID_PRICE": 2,
    }


def test_real_report_is_independent_reproducible_and_sourced() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    source = (ROOT / "src/robin/capture/descriptive_experiment.py").read_text("utf-8")

    assert "real_data_dashboard" not in source
    assert "compare_acquisitions" not in source
    assert report["schema_version"] == "robin-descriptive-experiment-v1"
    assert report["mission_id"] == "ROBIN_SIMPLIFICATION_EXPLORATION_20261005"
    assert [item["github_run_id"] for item in report["frozen_inputs"]] == [
        "37276237875",
        "37292740942",
    ]
    assert report["result"]["matched_offer_count"] == 7648
    assert report["result"]["changed_offer_count"] == 682
    assert report["result"]["changed_proportion"] == 0.089174
    assert report["result"]["appeared_offer_count"] == 6
    assert report["result"]["not_observed_offer_count"] == 83
    assert report["result"]["excluded_row_count"] == 0
    assert report["result"]["direction_counts"] == {
        "UP": 373,
        "DOWN": 309,
        "UNCHANGED": 6966,
    }
    assert len(report["findings"]) == 3
    assert all(item["source_rows"] and item["limitation"] for item in report["findings"])
    assert len(report["research_questions"]) <= 2
    assert report["qa"]["independent_from_interface"] is True
    assert report["qa"]["shared_totals_reconciled"] is True
    assert report["qa"]["shared_breakdowns_reconciled"] is True
    assert report["qa"]["source_samples_reconciled"] is True
    assert report["scientific_notice"] == "DESCRIPTIVE_EXPOSED_NO_EDGE_NO_CAUSALITY"


def test_cli_reproduces_a_verified_pair(tmp_path: Path) -> None:
    previous = _bundle(
        tmp_path / "previous",
        _report("10", "2026-10-05T08:00:00Z", [_row()]),
    )
    current = _bundle(
        tmp_path / "current",
        _report(
            "11",
            "2026-10-05T10:00:00Z",
            [_row(price=2.2, slot="2026-10-05T10:00:00Z")],
        ),
    )
    output = tmp_path / "report.json"

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_descriptive_experiment.py"),
            "--previous",
            str(previous),
            "--current",
            str(current),
            "--output",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )

    assert json.loads(output.read_text("utf-8"))["schema_version"] == (
        "robin-descriptive-experiment-v1"
    )
