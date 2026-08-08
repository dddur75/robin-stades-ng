from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E3A = ROOT / "reports/evidence/e3a"
E3B = ROOT / "reports/evidence/e3b"


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_e3a_preserves_unknown_and_opens_only_reconstructed_capabilities() -> None:
    measurement = _read(E3A / "e3a-measurement-v1.json")
    matrix = _read(E3A / "e3a-capability-matrix-v1.json")
    calendar = _read(E3A / "e3a-calendar-asof-v1.json")
    rows = {row["capability_id"]: row for row in measurement["rows"]}
    assert measurement["competition"] == "Ligue 1"
    assert measurement["fixture_count"] == 308
    assert rows["CALENDAR"]["expected"] == 308 * 17
    assert rows["CALENDAR"]["received"] == 0
    assert rows["CALENDAR"]["unknown"] == 308 * 17
    assert rows["CALENDAR"]["e3a_status"] == "BLOCKED_BY_SOURCE"
    assert matrix["strict_capabilities_ready"] == []
    assert matrix["passed_capabilities"] == sorted(
        ["TEAM", "PLAYER", "LINEUP", "FORMATION", "EVENTS", "TEAM_STATISTICS", "DISCIPLINE_GENERIC"]
    )
    assert calendar["promotion"] == "DENIED_NO_REAL_KNOWN_AT"
    assert calendar["unknown_coerced_to_false"] == 0
    assert all(row["unknown_count"] == 308 for row in calendar["features"])


def test_e3b_uses_weighted_denominators_and_localizes_two_gaps() -> None:
    measurement = _read(E3B / "e3b-measurement-v1.json")
    comparison = _read(E3B / "e3b-league-comparison-v1.json")
    aggregates = {row["capability_id"]: row for row in measurement["weighted_aggregates"]}
    assert measurement["fixture_count"] == 1756
    assert len(measurement["league_rows"]) == 35
    assert aggregates["TEAM"]["expected"] == aggregates["TEAM"]["received"] == 3512
    assert aggregates["TEAM_STATISTICS"]["expected"] == 63216
    assert aggregates["TEAM_STATISTICS"]["received"] == 63180
    assert aggregates["TEAM_STATISTICS"]["e3b_status"] == "E3B_MEASURED_PARTIAL"
    assert aggregates["LINEUP"]["invalid"] == 4
    assert aggregates["LINEUP"]["contradictory_duplicates"] == 4
    serie_a = next(row for row in comparison["rows"] if row["competition"] == "Serie A")
    assert serie_a["local_partial_capabilities"] == ["LINEUP", "TEAM_STATISTICS"]
    assert next(row for row in comparison["rows"] if row["competition"] == "Ligue 1")[
        "source_reused_without_redownload"
    ] is True


def test_replay_hashes_match_and_costs_remain_zero_external_effect() -> None:
    for root, prefix in ((E3A, "e3a"), (E3B, "e3b")):
        replay = _read(root / f"{prefix}-replay-v1.json")
        assert replay["replay_identical"] is True
        assert replay["additional_network_reads"] == 0
        for stem, expected in replay["all_report_hashes"].items():
            path = root / f"{stem}.json"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        costs = _read(root / f"{prefix}-costs-v1.json")
        for field in ("r2_logical_gets", "r2_bytes", "provider_calls", "odds_credits", "sql_queries"):
            assert costs[field] == 0


def test_detailed_fixture_ids_exist_only_in_e3a_selection_manifest() -> None:
    for root in (E3A, E3B):
        for path in root.glob("*.json"):
            if path.name == "e3a-selection-manifest-v1.json":
                continue
            text = path.read_text(encoding="utf-8")
            assert '"fixture_ids"' not in text
            assert '"allowed_r2_keys"' not in text

