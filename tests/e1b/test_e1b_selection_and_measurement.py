from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from robin.historical_deep.e1b_canary import (
    build_reports,
    finalize_reports,
    read_json,
    validate_contracts,
    validate_reports,
)

ROOT = Path(__file__).resolve().parents[2]


def test_committed_selection_contract_is_bounded_and_valid() -> None:
    mission, selection = validate_contracts(ROOT)

    assert mission["fixture_count"] == 10
    assert mission["r2_get_budget"] == 2000
    assert len(selection["fixtures"]) == 10
    assert len(selection["source_objects"]) == 10
    assert selection["budgets"]["planned_logical_gets_total"] == 21


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda value: value["fixtures"].pop(), "CARDINALITY"),
        (
            lambda value: value["fixtures"][0].__setitem__("competition_id", 999),
            "LEAGUE_BALANCE",
        ),
        (
            lambda value: value["fixtures"][0]["allowed_r2_keys"].__setitem__(
                0, "historical-deep-data/schema-v1/drift"
            ),
            "KEY_ALLOWLIST",
        ),
        (lambda value: value["fixtures"][0]["payload_hashes"].pop(), "PAYLOAD_HASHES"),
        (
            lambda value: value["budgets"].__setitem__("provider_calls", 1),
            "BUDGET",
        ),
    ],
)
def test_selection_validation_fails_closed(
    tmp_path: Path, mutation: Any, error: str
) -> None:
    for relative in (
        "configs/execution/p0-e1b-five-league-canary-v1.json",
        "configs/data/capability-scoped-evidence-ladder-v2.json",
        "configs/data/football-grain-catalog-v1.json",
        "reports/preflight/p0-capability-launch-readiness-v1.json",
        "reports/evidence/e1b/e1b-selection-manifest-v1.json",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    selection_path = tmp_path / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    selection = copy.deepcopy(read_json(selection_path))
    mutation(selection)
    import json

    selection_path.write_text(
        json.dumps(selection, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error):
        validate_contracts(tmp_path)


def _fixture(
    fixture_id: int,
    kickoff: str,
    home_id: int,
    away_id: int,
    *,
    rich: bool,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fixture": {"id": fixture_id, "date": kickoff},
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
    }
    if not rich:
        return record
    record["lineups"] = [
        {
            "team": {"id": team_id},
            "formation": "4-3-3",
            "startXI": [
                {"player": {"id": team_id * 100 + slot, "name": f"P{team_id}-{slot}"}}
                for slot in range(1, 12)
            ],
            "substitutes": [],
        }
        for team_id in (home_id, away_id)
    ]
    record["events"] = [{"type": "Card", "detail": "Yellow Card"}]
    record["statistics"] = [
        {"team": {"id": team_id}, "statistics": [{"type": "Shots", "value": 7}]}
        for team_id in (home_id, away_id)
    ]
    record["players"] = [
        {
            "team": {"id": team_id},
            "players": [
                {"player": {"id": team_id * 100 + slot, "name": f"P{team_id}-{slot}"}}
                for slot in range(1, 12)
            ],
        }
        for team_id in (home_id, away_id)
    ]
    return record


def _synthetic_inputs() -> tuple[
    dict[str, object], dict[str, dict[str, Any]], dict[str, Any]
]:
    selection = read_json(
        ROOT / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    )
    payloads: dict[str, object] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for source in selection["source_objects"]:
        competition_id = int(source["competition_id"])
        chosen = [
            item
            for item in selection["fixtures"]
            if int(item["competition_id"]) == competition_id
        ]
        team_ids = sorted(
            {
                int(team_id)
                for item in chosen
                for team_id in (item["home_team_id"], item["away_team_id"])
            }
        )
        prior = _fixture(
            9_000_000 + competition_id,
            "2024-08-01T12:00:00+00:00",
            team_ids[0],
            team_ids[1],
            rich=True,
        )
        current = [
            _fixture(
                int(item["fixture_id"]),
                str(item["kickoff_utc"]),
                int(item["home_team_id"]),
                int(item["away_team_id"]),
                rich=source["source_role"] == "DETAIL",
            )
            for item in chosen
        ]
        payloads[str(source["object_id"])] = {"response": [prior, *current]}
        receipts[str(source["object_id"])] = {
            "receipt_hash": source["receipt_hash"],
            "received_at": "2025-01-01T00:00:00Z",
            "completed_at": "2025-01-01T00:00:01Z",
        }
    telemetry = {
        "logical_gets": {
            "bootstrap": {"requested": 1},
            "receipt": {"requested": 10},
            "payload": {"requested": 10},
            "evidence_total": 20,
        },
        "bytes": {
            "bootstrap_stored": 1000,
            "receipt": 2000,
            "payload_stored": 3000,
        },
    }
    return payloads, receipts, telemetry


def test_synthetic_five_league_measurement_is_deterministic_and_scoped() -> None:
    mission = read_json(ROOT / "configs/execution/p0-e1b-five-league-canary-v1.json")
    selection = read_json(
        ROOT / "reports/evidence/e1b/e1b-selection-manifest-v1.json"
    )
    contract = read_json(ROOT / "configs/data/capability-scoped-evidence-ladder-v2.json")
    payloads, receipts, telemetry = _synthetic_inputs()
    kwargs = {
        "mission": mission,
        "selection": selection,
        "contract": contract,
        "payloads": payloads,
        "receipts": receipts,
        "telemetry": telemetry,
        "runtime": {"duration_seconds": 1.0, "github_minutes": "UNKNOWN"},
        "selection_hash": "a" * 64,
    }

    first = build_reports(**kwargs)
    second = build_reports(**kwargs)
    validate_reports(first)

    assert finalize_reports(first) == finalize_reports(second)
    assert len(first["measurement"]["measurements"]) == 90
    assert first["measurement"]["absence_cause_exact_status"] == "STOPPED_LOCAL_CAMPAIGN"
    assert first["measurement"]["ready_strict_declared"] == 0
    assert first["measurement"]["ready_reconstructed_declared"] == 0
    team = next(
        item
        for item in first["measurement"]["weighted_capability_aggregates"]
        if item["capability_id"] == "TEAM"
    )
    assert team["coverage_rate_weighted"] == 1.0
    assert "TEAM" in first["measurement"]["e2_candidates"]
    assert first["unknown_profile"]["canonical_value"] == "UNKNOWN"
    assert all(
        value == 0 for value in first["unknown_profile"]["implicit_coercions"].values()
    )


def test_runner_never_uses_bucket_listing_head_or_mutation() -> None:
    source = (
        ROOT / "scripts/run_p0_e1b_five_league_canary.py"
    ).read_text(encoding="utf-8")

    for forbidden in ("list_objects", "head_object", "put_object", "delete_object"):
        assert forbidden not in source
