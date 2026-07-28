from __future__ import annotations

import json
from pathlib import Path

from robin.prospective_observatory.contracts import CaptureFamily

ROOT = Path(__file__).resolve().parents[2]


def _snapshot() -> dict[str, object]:
    return json.loads(
        (ROOT / "cockpit" / "app" / "cockpit-data.json").read_text(
            encoding="utf-8"
        )
    )


def test_presentation_registry_is_complete_and_canonical() -> None:
    snapshot = _snapshot()
    observatory = snapshot["prospectiveObservatory"]
    assert isinstance(observatory, dict)
    fixtures = observatory["fixtures"]
    windows = observatory["windows"]
    assert isinstance(fixtures, dict)
    assert isinstance(windows, dict)
    registry = fixtures["registry"]
    window_registry = windows["registry"]
    assert isinstance(registry, list)
    assert isinstance(window_registry, list)
    fixture_ids = {
        str(item["fixture_id"])
        for item in registry
        if isinstance(item, dict) and item.get("cancelled") is False
    }
    assert len(fixture_ids) == fixtures["tracked"]
    assert all(
        isinstance(item, dict)
        and item["canonical_key"] == item["fixture_id"]
        and item["home_team_id"] != item["away_team_id"]
        for item in registry
    )
    assert all(
        isinstance(item, dict)
        and item["fixture_id"] in fixture_ids
        and item["active"] is True
        and item["family"] in {family.value for family in CaptureFamily}
        for item in window_registry
    )
    assert len(window_registry) == windows["planned"]


def test_snapshot_bankroll_comes_from_versioned_policy_and_ledger() -> None:
    snapshot = _snapshot()
    policy = json.loads(
        (ROOT / "configs" / "shadow_simulation_v1.json").read_text(
            encoding="utf-8"
        )
    )
    pattern = snapshot["patternResearch"]
    assert isinstance(pattern, dict)
    bankroll = pattern["bankroll"]
    assert isinstance(bankroll, dict)
    assert bankroll["initialUnits"] == policy["initial_bankroll_units"]
    assert bankroll["policySource"] == "configs/shadow_simulation_v1.json"
    assert bankroll["currentUnits"] == bankroll["curve"][-1]


def test_operational_values_are_absent_from_frontend_sources() -> None:
    forbidden = {
        "30314975830",
        "2469e57ec4b2ef2849f9e707f63843033ec026e6",
        "api-football:1552733",
        "api-football:1552732",
        "2026-08-21T18:45:00",
        "2026-07-31T18:45:00",
        "04395a33b7584d33a4413fb61dba41c3e7c4f83ef2e2e07fd2b16b0d116745c6",
    }
    roots = (
        ROOT / "cockpit" / "app" / "components",
        ROOT / "cockpit" / "app" / "lib",
        ROOT / "cockpit" / "app" / "i18n",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in roots
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )
    assert all(value not in source for value in forbidden)


def test_snapshot_generator_exposes_provenance_without_raw_payloads() -> None:
    snapshot = _snapshot()
    observatory = snapshot["prospectiveObservatory"]
    assert isinstance(observatory, dict)
    source = observatory["source"]
    invariants = observatory["invariants"]
    assert isinstance(source, dict)
    assert source["run_id"]
    assert source["revision"]
    assert source["workflow"]
    assert isinstance(invariants, dict)
    assert invariants["raw_payloads_in_git"] == 0
    assert invariants["postgresql_payload_body_rows"] == 0
