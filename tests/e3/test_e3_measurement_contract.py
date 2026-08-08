from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
E3A = ROOT / "reports/evidence/e3a"
E3B = ROOT / "reports/evidence/e3b"
SCRIPT = ROOT / "scripts/run_p0_e3_capability_scale.py"


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _event(
    *, fixture_id: int, elapsed: int, event_type: str, detail: str
) -> dict[str, object]:
    return {
        "provider_fixture_id": fixture_id,
        "provider_team_id": 10,
        "data": {
            "assist": {"id": None},
            "comments": None,
            "detail": detail,
            "player": {"id": 20},
            "team": {"id": 10},
            "time": {"elapsed": elapsed, "extra": None},
            "type": event_type,
        },
    }


def test_event_identity_collapses_provider_order_but_preserves_semantics() -> None:
    classify = runpy.run_path(str(SCRIPT))["_event_classification"]
    result = classify(
        [
            _event(fixture_id=1, elapsed=60, event_type="subst", detail="Substitution 1"),
            _event(fixture_id=1, elapsed=60, event_type="subst", detail="Substitution 2"),
            _event(fixture_id=2, elapsed=70, event_type="Card", detail="Yellow Card"),
            _event(fixture_id=2, elapsed=70, event_type="Card", detail="Red Card"),
        ]
    )
    assert result == {
        "exact_repetitions": 1,
        "factual_signature_groups": 2,
        "provider_order_only_groups_collapsed": 1,
        "scientific_fact_count": 3,
        "semantic_multi_event_groups": 1,
        "unclassifiable_groups": 0,
    }


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
    assert rows["CALENDAR"]["e3a_status"] == "BLOCKED_BY_TEMPORALITY"
    assert matrix["strict_capabilities_ready"] == []
    assert matrix["passed_capabilities"] == sorted(
        ["TEAM", "PLAYER", "LINEUP", "FORMATION", "EVENTS", "DISCIPLINE_GENERIC"]
    )
    assert rows["TEAM_STATISTICS"]["expected"] == 11_088
    assert rows["TEAM_STATISTICS"]["received"] == 10_510
    assert rows["TEAM_STATISTICS"]["unknown"] == 578
    assert rows["TEAM_STATISTICS"]["null_value_count"] == 578
    assert rows["TEAM_STATISTICS"]["e3a_status"] == "MEASURED_PARTIAL"
    assert rows["PLAYER"]["expected"] == rows["PLAYER"]["lineup_slot_denominator"]
    assert rows["PLAYER"]["expected"] == rows["PLAYER"]["received"] == 12_297
    assert rows["EVENTS"]["expected"] == rows["EVENTS"]["received"] == 308
    assert rows["EVENTS"]["event_classification"] == {
        "exact_repetitions": 332,
        "factual_signature_groups": 5008,
        "provider_order_only_groups_collapsed": 39,
        "scientific_fact_count": 5032,
        "semantic_multi_event_groups": 24,
        "unclassifiable_groups": 0,
    }
    assert rows["DISCIPLINE_GENERIC"]["expected"] == 308
    assert rows["DISCIPLINE_GENERIC"]["received"] == 298
    assert rows["DISCIPLINE_GENERIC"]["empty_valid"] == 10
    assert calendar["promotion"] == "DENIED_NO_REAL_KNOWN_AT"
    assert calendar["unknown_coerced_to_false"] == 0
    assert all(row["unknown_count"] == 308 for row in calendar["features"])


def test_e3b_uses_weighted_denominators_and_localizes_one_gap() -> None:
    measurement = _read(E3B / "e3b-measurement-v1.json")
    comparison = _read(E3B / "e3b-league-comparison-v1.json")
    aggregates = {row["capability_id"]: row for row in measurement["weighted_aggregates"]}
    assert measurement["fixture_count"] == 1756
    assert len(measurement["league_rows"]) == 30
    assert aggregates["TEAM"]["expected"] == aggregates["TEAM"]["received"] == 3512
    assert "TEAM_STATISTICS" not in aggregates
    assert aggregates["PLAYER"]["expected"] == aggregates["PLAYER"]["received"] == 74_407
    assert aggregates["LINEUP"]["expected"] == 3512
    assert aggregates["LINEUP"]["received"] == 3510
    assert aggregates["LINEUP"]["invalid"] == 2
    assert aggregates["LINEUP"]["contradictory_duplicates"] == 0
    serie_a = next(row for row in comparison["rows"] if row["competition"] == "Serie A")
    assert serie_a["local_partial_capabilities"] == ["LINEUP"]
    serie_a_lineup = next(
        row
        for row in measurement["league_rows"]
        if row["competition"] == "Serie A" and row["capability_id"] == "LINEUP"
    )
    assert serie_a_lineup["affected_lineups"] == 2
    assert serie_a_lineup["lineup_player_role_conflicts"] == 4
    assert serie_a_lineup["invalid"] == 2
    assert serie_a_lineup["contradictory_duplicates"] == 0
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
