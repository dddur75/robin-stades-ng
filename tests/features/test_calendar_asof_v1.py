from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from robin.features.calendar_asof import build_calendar_features, render_calendar_result

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "tests/fixtures/calendar/calendar-strict-asof-golden-pack-v1.json"


def load_pack() -> dict[str, object]:
    return json.loads(PACK.read_text(encoding="utf-8"))


def run_case(case: dict[str, object]) -> dict[str, object]:
    pack = load_pack()
    cutoff = datetime.fromisoformat(str(case["cutoff"]).replace("Z", "+00:00"))
    fixtures = pack["fixtures"]
    assert isinstance(fixtures, list)
    return build_calendar_features(
        fixtures,
        target_fixture_id=int(pack["target_fixture_id"]),
        cutoff=cutoff,
        catalog_complete_at_cutoff=bool(case["catalog_complete_at_cutoff"]),
    )


def test_golden_pack_is_bounded_and_byte_identical() -> None:
    pack = load_pack()
    fixtures = pack["fixtures"]
    cases = pack["cases"]
    assert isinstance(fixtures, list) and 8 <= len(fixtures) <= 15
    assert isinstance(cases, list) and len(cases) == 3
    for raw in cases:
        assert isinstance(raw, dict)
        first = render_calendar_result(run_case(raw))
        second = render_calendar_result(run_case(raw))
        assert first == second
        assert hashlib.sha256(first).hexdigest() == raw["expected_sha256"]


def test_cutoff_blocks_late_finish_postponement_and_future_arrival() -> None:
    pack = load_pack()
    before = run_case(pack["cases"][0])  # type: ignore[index]
    after = run_case(pack["cases"][1])  # type: ignore[index]
    before_load = before["load_counts"]
    after_load = after["load_counts"]
    assert isinstance(before_load, dict) and isinstance(after_load, dict)
    assert before_load["PLAYED_LOAD"] != before_load["SCHEDULED_LOAD"]
    assert before_load != after_load
    assert before["cutoff"] == "2025-01-20T12:00:00+00:00"
    assert after["cutoff"] == "2025-01-22T12:00:00+00:00"


def test_postponed_cancelled_abandoned_rescheduled_and_double_fixture() -> None:
    pack = load_pack()
    result = run_case(pack["cases"][0])  # type: ignore[index]
    load = result["load_counts"]
    assert isinstance(load, dict)
    scheduled = load["SCHEDULED_LOAD"]
    played = load["PLAYED_LOAD"]
    assert isinstance(scheduled, dict) and isinstance(played, dict)
    assert scheduled["HOME"]["14"] > played["HOME"]["14"]  # type: ignore[index]
    assert played["HOME"]["28"] >= 4  # type: ignore[index]


def test_true_false_and_unknown_are_first_class_values() -> None:
    pack = load_pack()
    complete = run_case(pack["cases"][0])  # type: ignore[index]
    incomplete = run_case(pack["cases"][2])  # type: ignore[index]
    complete_features = complete["features"]
    incomplete_features = incomplete["features"]
    assert isinstance(complete_features, dict) and isinstance(incomplete_features, dict)
    assert complete_features["THIRD_CONSECUTIVE_AWAY_AWAY"] == "TRUE"
    assert complete_features["THIRD_CONSECUTIVE_AWAY_HOME"] == "FALSE"
    assert set(incomplete_features.values()) == {"UNKNOWN"}


def test_future_unknown_fixture_does_not_leak_before_cutoff() -> None:
    pack = load_pack()
    before = run_case(pack["cases"][0])  # type: ignore[index]
    fixtures = pack["fixtures"]
    assert isinstance(fixtures, list)
    without_late = [item for item in fixtures if item["fixture_id"] != 1012]
    cutoff = datetime.fromisoformat("2025-01-20T12:00:00+00:00")
    replay = build_calendar_features(
        without_late,
        target_fixture_id=1200,
        cutoff=cutoff,
        catalog_complete_at_cutoff=True,
    )
    assert render_calendar_result(before) == render_calendar_result(replay)


def test_target_unknown_at_cutoff_fails_closed() -> None:
    pack = load_pack()
    fixtures = pack["fixtures"]
    assert isinstance(fixtures, list)
    result = build_calendar_features(
        fixtures,
        target_fixture_id=1200,
        cutoff=datetime.fromisoformat("2024-12-01T00:00:00+00:00"),
        catalog_complete_at_cutoff=True,
    )
    assert result["status"] == "TARGET_NOT_KNOWN_AS_OF"
    assert set(result["features"].values()) == {"UNKNOWN"}  # type: ignore[union-attr]
