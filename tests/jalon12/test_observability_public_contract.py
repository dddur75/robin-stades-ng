"""Contrats publics, fail-closed et sans démo de l'Observatoire Jalon 12."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_cockpit_snapshot

ROOT = Path(__file__).resolve().parents[2]
COMPACT = ROOT / "reports" / "jalon12" / "observatory-snapshot.json"
POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
SOCIAL_EXPORTS = (
    "prospective_observatory_update.json",
    "data_capture_progress.json",
    "lineup_gate_update.json",
    "injury_gate_update.json",
)


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_compact_snapshot_is_sourced_from_policy_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    policy = read_json(POLICY)
    budgets = policy["provider_budgets"]
    assert isinstance(budgets, dict)

    assert snapshot["policy_source"] == "configs/prospective_observatory_v1.json"
    assert "\\" not in str(snapshot["policy_source"])
    assert snapshot["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"
    assert snapshot["status"] == "WAITING_FOR_FIRST_DUE_WINDOW"
    assert snapshot["decisions"] == 0
    assert snapshot["candidates"] == 0
    assert snapshot["providers"]["api_football_calls"] == 0
    assert snapshot["providers"]["odds_api_credits"] == 0
    assert snapshot["providers"]["budgets"] == {
        "api_football_max_total": budgets["api_football_max_calls_total"],
        "odds_api_max_total": budgets["odds_api_max_credits_total"],
    }
    assert snapshot["providers"]["reserves"] == {
        "api_football": budgets["api_football_provider_reserve"],
        "odds_api": budgets["odds_api_provider_reserve"],
        "odds_api_internal_safety": budgets[
            "odds_api_internal_safety_reserve"
        ],
        "odds_api_near_kickoff": budgets["odds_api_near_kickoff_reserve"],
    }
    assert snapshot["postgresql"]["migration"] == "0009_jalon12_observatory"
    assert snapshot["postgresql"]["payload_body_rows"] == 0
    assert snapshot["r2"]["deletions"] == 0
    assert len(snapshot["captures"]["by_family"]) == 9
    assert len(snapshot["gates"]["by_name"]) == 5
    assert len(snapshot["hypotheses"]) == 8
    assert all(item["frozen"] is True for item in snapshot["hypotheses"])
    assert all(
        item["status"] == "WAITING_FOR_OBSERVATIONS"
        for item in snapshot["hypotheses"]
    )
    invariants = snapshot["invariants"]
    assert invariants == {
        "storage_paused": True,
        "p3_p4_paused": True,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "external_social_networks_connected": False,
        "raw_payloads_in_git": 0,
        "postgresql_payload_body_rows": 0,
    }


def test_prospective_only_build_preserves_unrelated_cockpit_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "cockpit-data.json"
    output_hash = tmp_path / "cockpit-data.sha256"
    output.write_text(
        json.dumps({"sentinel": {"preserved": True}, "generatedAt": "old"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_cockpit_snapshot, "OUTPUT", output)
    monkeypatch.setattr(build_cockpit_snapshot, "OUTPUT_HASH", output_hash)
    monkeypatch.setenv("COCKPIT_PROSPECTIVE_ONLY", "1")
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path / "no-reports"))

    build_cockpit_snapshot.main()

    rebuilt = read_json(output)
    assert rebuilt["sentinel"] == {"preserved": True}
    observatory = rebuilt["prospectiveObservatory"]
    assert observatory["decisions"] == 0
    assert observatory["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"
    digest = output_hash.read_text(encoding="ascii").strip()
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_social_exports_are_static_disabled_and_decision_free() -> None:
    actual = {
        path.name
        for path in (ROOT / "social_exports").glob("*.json")
        if path.name in SOCIAL_EXPORTS
    }
    assert actual == set(SOCIAL_EXPORTS)
    for filename in SOCIAL_EXPORTS:
        export = read_json(ROOT / "social_exports" / filename)
        assert export["publishing_enabled"] is False
        assert export["external_networks_connected"] is False
        assert export["production_status"] == "PRODUCTION_LOCKED"
        assert export["real_bets"] is False
        assert export["demo_mode_enabled"] is False
        serialized = json.dumps(export, sort_keys=True).lower()
        assert "api_key" not in serialized
        assert "secret" not in serialized
        assert '"decision"' not in serialized


def test_public_snapshot_contains_no_demo_capture_or_bet_decision() -> None:
    snapshot = read_json(COMPACT)
    assert snapshot["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"
    assert snapshot["fixtures"]["tracked"] == 0
    assert snapshot["captures"]["captured"] == 0
    assert snapshot["decisions"] == 0
    assert snapshot["ledger"]["bet_decisions"] == 0
    assert snapshot["invariants"]["demo_mode_enabled"] is False
    assert snapshot["invariants"]["real_bets"] is False
    serialized = COMPACT.read_text(encoding="utf-8")
    assert "DATABASE_URL" not in serialized
    assert "API_FOOTBALL_KEY" not in serialized
    assert "ODDS_API_KEY" not in serialized
    assert "R2_SECRET_ACCESS_KEY" not in serialized
