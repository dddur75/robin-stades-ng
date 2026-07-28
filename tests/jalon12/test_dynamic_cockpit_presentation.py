from __future__ import annotations

import json
import re
from pathlib import Path

from robin.prospective_observatory.contracts import (
    CaptureFamily,
    canonical_sha256,
)

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


def test_frontend_has_no_manual_team_identity_mapping() -> None:
    forbidden_patterns = (
        r'["\']81["\']\s*:\s*["\']Marseille',
        r'["\']95["\']\s*:\s*["\']Strasbourg',
        r"\bteamNamesByProviderId\b",
        r"\bproviderFixtures\b",
    )
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
    assert all(
        re.search(pattern, source, flags=re.IGNORECASE) is None
        for pattern in forbidden_patterns
    )


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


def test_real_snapshot_has_two_verified_identities_per_fixture() -> None:
    snapshot = _snapshot()
    observatory = snapshot["prospectiveObservatory"]
    assert isinstance(observatory, dict)
    fixtures = observatory["fixtures"]
    assert isinstance(fixtures, dict)
    registry = fixtures["registry"]
    assert isinstance(registry, list)
    assert len(registry) == fixtures["tracked"]
    assert all(
        isinstance(fixture, dict)
        and isinstance(fixture["home_name"], str)
        and isinstance(fixture["away_name"], str)
        and fixture["home_identity_status"] == "VERIFIED"
        and fixture["away_identity_status"] == "VERIFIED"
        and fixture["home_identity_provenance"]["source"]
        == "R2_FIXTURE_PAYLOAD"
        and fixture["away_identity_provenance"]["source"]
        == "R2_FIXTURE_PAYLOAD"
        for fixture in registry
    )
    identity_registry = fixtures["identity_registry"]
    assert isinstance(identity_registry, dict)
    expected_team_slots = len(registry) * 2
    assert identity_registry["team_slots_expected"] == expected_team_slots
    assert identity_registry["team_slots_resolved"] == expected_team_slots


def test_committed_team_identity_provenance_is_verified_and_provider_free() -> None:
    report = json.loads(
        (
            ROOT / "reports" / "ux" / "team-identity-provenance.json"
        ).read_text(encoding="utf-8")
    )
    report_hash = report.pop("report_sha256")
    assert canonical_sha256(report) == report_hash
    snapshot = _snapshot()
    observatory = snapshot["prospectiveObservatory"]
    assert isinstance(observatory, dict)
    fixtures = observatory["fixtures"]
    assert isinstance(fixtures, dict)
    registry = fixtures["registry"]
    identity_registry = fixtures["identity_registry"]
    assert isinstance(registry, list)
    assert isinstance(identity_registry, dict)
    fixture_count = len(registry)
    expected_team_slots = fixture_count * 2
    assert report["coverage"] == {
        "fixtures_expected": fixture_count,
        "fixtures_resolved": fixture_count,
        "team_slots_expected": expected_team_slots,
        "team_slots_resolved": expected_team_slots,
        "team_slots_unresolved": 0,
        "percentage": 100.0,
    }
    assert identity_registry["team_slots_expected"] == expected_team_slots
    assert identity_registry["team_slots_resolved"] == expected_team_slots
    assert report["provider_usage"] == {
        "api_football_calls": 0,
        "odds_api_credits": 0,
    }
    assert report["reads"]["r2"]["writes"] == 0
    assert report["reads"]["postgresql"]["writes"] == 0
    assert len(report["identities"]) == expected_team_slots
    assert all(
        identity["receipt_verified"] is True
        and identity["identity_status"] == "VERIFIED"
        and identity["source"] == "R2_FIXTURE_PAYLOAD"
        and all(identity["postgresql_projection"].values())
        for identity in report["identities"]
    )


def test_public_presentation_contains_no_numeric_team_fallback() -> None:
    presentation = json.loads(
        (ROOT / "cockpit" / "app" / "cockpit-presentation.json").read_text(
            encoding="utf-8"
        )
    )
    matches = presentation["matches"]
    snapshot = _snapshot()
    observatory = snapshot["prospectiveObservatory"]
    assert isinstance(observatory, dict)
    fixtures = observatory["fixtures"]
    assert isinstance(fixtures, dict)
    assert len(matches) == fixtures["tracked"]
    assert all(
        re.fullmatch(r"Équipe\s+\d+", match[side]) is None
        for match in matches
        for side in ("home", "away")
    )
