from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from robin.historical_deep.e2_sample import (
    CAPABILITIES,
    build_reports,
    canonical_hash,
    finalize_reports,
    validate_reports,
)

ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return value


def test_selection_scope_anchors_strata_and_hashes() -> None:
    selection = load("reports/evidence/e2/e2-selection-manifest-v1.json")
    fixtures = selection["fixtures"]
    assert len(fixtures) == len({item["fixture_id"] for item in fixtures}) == 100
    assert sum(item["is_e1b_anchor"] for item in fixtures) == 10
    assert selection["selection_hash"] == canonical_hash(fixtures)
    assert selection["anchor_hash"] == canonical_hash(
        [item for item in fixtures if item["is_e1b_anchor"]]
    )
    assert selection["new_fixture_hash"] == canonical_hash(
        [item for item in fixtures if not item["is_e1b_anchor"]]
    )
    by_league: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in fixtures:
        by_league[item["competition"]].append(item)
    assert len(by_league) == 5
    for rows in by_league.values():
        assert len(rows) == 20
        assert sum(item["is_e1b_anchor"] for item in rows) == 2
        assert sorted(item["temporal_stratum"] for item in rows if not item["is_e1b_anchor"]) == list(range(1, 19))
        assert len({team for item in rows for team in (item["home_team_id"], item["away_team_id"])}) >= 18


def test_e1b_anchors_preserve_exact_detail_sources() -> None:
    e1b = load("reports/evidence/e1b/e1b-selection-manifest-v1.json")
    e2 = load("reports/evidence/e2/e2-selection-manifest-v1.json")
    detail = {
        item["competition_id"]: item
        for item in e1b["source_objects"]
        if item["source_role"] == "DETAIL"
    }
    e1b_fixtures = {item["fixture_id"]: item for item in e1b["fixtures"]}
    anchors = [item for item in e2["fixtures"] if item["is_e1b_anchor"]]
    assert {item["fixture_id"] for item in anchors} == set(e1b_fixtures)
    competition_ids = {39: "Premier League", 61: "Ligue 1", 78: "Bundesliga", 135: "Serie A", 140: "Liga"}
    for item in anchors:
        competition_id = next(key for key, value in competition_ids.items() if value == item["competition"])
        source = detail[competition_id]
        assert item["allowed_receipt_key"] == source["receipt_key"]
        assert item["allowed_payload_key"] == source["payload_key"]
        assert item["receipt_hash"] == source["receipt_hash"]
        assert item["payload_hash"] == source["payload_sha256"]


def test_selection_gate_and_budgets_are_fail_closed() -> None:
    selection = load("reports/evidence/e2/e2-selection-manifest-v1.json")
    mission = load("configs/execution/p0-e2-capability-sample-v1.json")
    checks = selection["gate"]["mechanical_checks"]
    assert checks == {
        "ambiguous_identities": 0,
        "anchor_fixture_count": 10,
        "competition_count": 5,
        "duplicate_fixtures": 0,
        "fixture_count": 100,
        "missing_hashes": 0,
        "new_fixture_count": 90,
        "planned_bytes_within_budget": True,
        "planned_gets_within_budget": True,
        "provider_fallbacks": 0,
        "r2_head_methods_imported": 0,
        "r2_list_methods_imported": 0,
        "r2_write_or_delete_methods_imported": 0,
        "unlisted_keys": 0,
    }
    assert selection["budgets"]["planned_logical_gets_total"] == 201
    assert selection["budgets"]["planned_total_bytes_upper_bound"] <= 50_000_000
    assert mission["r2_get_budget"] == 300
    assert mission["r2_byte_budget"] == 50_000_000
    assert mission["provider_budget"] == mission["sql_budget"] == mission["r2_write_budget"] == 0


def test_selection_contains_no_absolute_paths_or_raw_payloads() -> None:
    text = (ROOT / "reports/evidence/e2/e2-selection-manifest-v1.json").read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "/Users/" not in text
    assert "/home/" not in text
    assert '"response"' not in text
    assert all(item["identity_status"] == "PROVIDER_ID_VERIFIED" for item in json.loads(text)["fixtures"])


def synthetic_payload(fixture_id: int, home: int, away: int) -> dict[str, Any]:
    def lineup(team: int, start: int) -> dict[str, Any]:
        return {
            "team": {"id": team},
            "formation": "4-3-3",
            "startXI": [{"player": {"id": start + index}} for index in range(11)],
            "substitutes": [],
        }

    players = [
        {"team": {"id": team}, "players": [{"player": {"id": start + index}, "statistics": [{}]} for index in range(11)]}
        for team, start in ((home, fixture_id * 100), (away, fixture_id * 100 + 20))
    ]
    return {
        "response": [
            {
                "fixture": {"id": fixture_id, "date": "2024-08-01T00:00:00+00:00", "status": {"short": "FT"}},
                "teams": {"home": {"id": home}, "away": {"id": away}},
                "lineups": [lineup(home, fixture_id * 100), lineup(away, fixture_id * 100 + 20)],
                "events": [],
                "statistics": [{"team": {"id": home}, "statistics": []}, {"team": {"id": away}, "statistics": []}],
                "players": players,
            }
        ]
    }


def test_synthetic_e2_reports_are_weighted_bounded_and_byte_identical() -> None:
    selection = load("reports/evidence/e2/e2-selection-manifest-v1.json")
    e1b = load("reports/evidence/e1b/e1b-measurement-v1.json")
    payloads = {
        item["fixture_id"]: synthetic_payload(item["fixture_id"], item["home_team_id"], item["away_team_id"])
        for item in selection["fixtures"]
    }
    receipts = {
        item["fixture_id"]: {"completed_at": "2026-08-01T00:00:00Z", "received_at": "2026-08-01T00:00:00Z"}
        for item in selection["fixtures"]
    }
    unique_sources = len({item["object_id"] for item in selection["fixtures"]})
    telemetry = {
        "bootstrap_requested": 1,
        "logical_gets": 1 + 2 * unique_sources,
        "network_bytes": 8_000_000,
        "payload_requested": unique_sources,
        "receipt_requested": unique_sources,
    }
    runtime = {"duration_seconds": 1.0, "github_minutes": "UNKNOWN_NOT_OBSERVED", "run_id": "SYNTHETIC"}
    first = build_reports(selection, e1b, payloads, receipts, telemetry, runtime)
    second = build_reports(selection, e1b, payloads, receipts, telemetry, runtime)
    validate_reports(first)
    validate_reports(second)
    assert finalize_reports(first) == finalize_reports(second)
    measurement = first["measurement"]
    assert len(measurement["measurements"]) == 45
    assert {item["capability_id"] for item in measurement["measurements"]} == set(CAPABILITIES)
    assert measurement["ready_strict_declared"] == measurement["ready_reconstructed_declared"] == []
    assert measurement["absence_cause_exact_status"] == "STOPPED_LOCAL_CAMPAIGN"
    assert measurement["historical_e1a_partition"]["identity"] == "3036 = 2681 + 206 + 149"
    assert first["e3a_candidate_set"]["e3a_executed"] is False
    assert first["e3a_candidate_set"]["masks_built"] is False


def test_global_rates_equal_weighted_counts_not_simple_league_assumptions() -> None:
    selection = load("reports/evidence/e2/e2-selection-manifest-v1.json")
    counts = Counter(item["competition"] for item in selection["fixtures"])
    assert counts == {"Premier League": 20, "Ligue 1": 20, "Bundesliga": 20, "Serie A": 20, "Liga": 20}
    assert hashlib.sha256(
        (json.dumps(selection, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    ).hexdigest() == hashlib.sha256(
        (ROOT / "reports/evidence/e2/e2-selection-manifest-v1.json").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
