"""Contrats publics, fail-closed et sans démo de l'Observatoire Jalon 12."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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


def valid_report_invariants() -> dict[str, object]:
    return {
        "storage_paused": True,
        "p3_p4_paused": True,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
    }


def operation_report(
    command: str,
    observatory: dict[str, object],
    *,
    generated_at: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    generated_at = generated_at or datetime.now(UTC).isoformat()
    snapshot = deepcopy(observatory)
    snapshot.setdefault("generated_at", generated_at)
    report: dict[str, object] = {
        "schema_version": "prospective-observatory-operation-v1",
        "command": command,
        "generated_at": generated_at,
        "policy_sha256": build_cockpit_snapshot.canonical_sha256(
            read_json(POLICY)
        ),
        "observatory": snapshot,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "deletions": 0,
        "raw_payloads_in_git": 0,
    }
    if extra:
        report.update(extra)
    report["report_sha256"] = build_cockpit_snapshot.canonical_sha256(report)
    return report


def reseal(report: dict[str, object]) -> None:
    report.pop("report_sha256", None)
    report["report_sha256"] = build_cockpit_snapshot.canonical_sha256(report)


def merge_test_dicts(
    base: dict[str, object],
    update: dict[str, object],
) -> dict[str, object]:
    merged = deepcopy(base)
    for key, value in update.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_test_dicts(current, value)
        else:
            merged[key] = value
    return merged


def write_gate_report(
    root: Path,
    observatory: dict[str, object],
    *,
    generated_at: str | None = None,
    envelope_updates: dict[str, object] | None = None,
) -> None:
    fixtures = observatory.get("fixtures", {})
    tracked = (
        fixtures.get("tracked", 0)
        if isinstance(fixtures, dict)
        else 0
    )
    assert isinstance(tracked, int)
    default_reason = "NO_PROSPECTIVE_OBSERVATION" if tracked else "NO_FIXTURE"
    defaults: dict[str, object] = {
        "gates": {
            "by_name": {
                name: {
                    "status": "BLOCKED_BY_COVERAGE",
                    "passed": 0,
                    "total": tracked,
                    "reason": default_reason,
                }
                for name in (
                    "PROSPECTIVE_PLAYER_GATE",
                    "PROSPECTIVE_INJURY_GATE",
                    "PROSPECTIVE_LINEUP_GATE",
                    "PROSPECTIVE_FORMATION_GATE",
                    "PROSPECTIVE_MARKET_GATE",
                )
            }
        },
        "temporal": {
            "before_cutoff": 0,
            "late": 0,
            "rejected": 0,
            "gates": tracked * 5,
        },
    }
    merged_observatory = merge_test_dicts(defaults, observatory)
    captures = merged_observatory.get("captures", {})
    receipts = (
        captures.get("hashes", 0)
        if isinstance(captures, dict)
        else 0
    )
    assert isinstance(receipts, int)
    ledger = merged_observatory.get("ledger", {})
    ledger_events = (
        ledger.get("events", 0)
        if isinstance(ledger, dict)
        else 0
    )
    assert isinstance(ledger_events, int)
    report = operation_report(
        "gate-report",
        merged_observatory,
        generated_at=generated_at,
        extra={
            "receipts": receipts,
            "ledger_events": ledger_events,
            "capture_set_sha256": build_cockpit_snapshot.canonical_sha256(
                [f"synthetic-receipt-{index}" for index in range(receipts)]
            ),
            "capture_provenance": {
                "live_provider_receipts": receipts,
                "cache_test_receipts": 0,
                "unverified_receipts": 0,
                "provider_calls_recorded": int(receipts > 0),
            },
        },
    )
    if envelope_updates:
        report.update(envelope_updates)
        reseal(report)
    (root / "gate-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )


def valid_replay_report() -> dict[str, object]:
    return operation_report(
        "replay-audit",
        {
            "r2": {
                "bytes": 1_100_000_000,
                "deletions": 0,
                "lag": 0,
                "objects_added": 3,
                "recovery_objects": 1,
                "recovery_bytes": 112_345_679,
                "replay_status": "R2_REPLAY_VERIFIED",
                "verified": 3,
            },
            "postgresql": {
                "duplicates_avoided": 1,
                "inserts": 1,
                "migration": "0009_jalon12_observatory",
                "payload_body_rows": 0,
                "reconstruction_status": "RECONSTRUCTIBLE_FROM_R2",
                "tables": 12,
            },
        },
        extra={
            "status": "R2_REPLAY_VERIFIED",
            "complete_replay": True,
            "selection_truncated": False,
            "provider_calls": 0,
            "odds_api_credits": 0,
            "hash_mismatches": 0,
            "data_loss": 0,
            "second_pass_inserts": 0,
            "second_pass_duplicates": 1,
            "payloads_replayed": 1,
            "fixtures_reconstructed": 1,
            "fixture_ids_expected": 1,
            "objects_examined": 3,
            "physical_unique_objects": 3,
            "physical_unique_bytes": 1_100_000_000,
            "physical_payload_objects": 1,
            "physical_payload_bytes": 600_000_000,
            "physical_receipt_objects": 1,
            "physical_receipt_bytes": 387_654_321,
            "physical_recovery_objects": 1,
            "physical_recovery_bytes": 112_345_679,
            "logical_references": 1,
            "logical_payload_bytes_read": 600_000_000,
            "logical_receipt_bytes_read": 387_654_321,
            "logical_bytes_read": 987_654_321,
            "namespace_verified": True,
            "dataset_hash": "a" * 64,
            "capture_set_sha256": "b" * 64,
        },
    )


def set_nested(value: dict[str, Any], path: str, replacement: object) -> None:
    parts = path.split(".")
    target = value
    for part in parts[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[parts[-1]] = replacement


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


@pytest.mark.parametrize(
    "mutations",
    [
        (("provider_calls", 1),),
        (
            ("objects_examined", -1),
            ("payloads_replayed", -1),
            ("second_pass_duplicates", -1),
            ("fixtures_reconstructed", -1),
            ("fixture_ids_expected", -1),
            ("observatory.r2.verified", -1),
            ("observatory.postgresql.duplicates_avoided", -1),
        ),
        (("observatory.r2.bytes", -1),),
        (("physical_recovery_objects", 0),),
        (("physical_recovery_bytes", 0),),
        (("observatory.r2.recovery_objects", 0),),
        (("observatory.r2.recovery_bytes", 0),),
        (
            ("payloads_replayed", 99),
            ("second_pass_duplicates", 99),
            ("observatory.postgresql.duplicates_avoided", 99),
        ),
        (
            ("fixtures_reconstructed", 99),
            ("fixture_ids_expected", 99),
        ),
        (("dataset_hash", "0" * 64),),
        (("observatory.postgresql.duplicates_avoided", 99),),
        (("observatory.postgresql.inserts", 2),),
    ],
)
def test_cockpit_accepts_valid_replay_then_rejects_single_guard_mutations(
    tmp_path: Path,
    mutations: tuple[tuple[str, object], ...],
) -> None:
    report_path = tmp_path / "r2-replay-audit.json"
    valid = valid_replay_report()
    report_path.write_text(json.dumps(valid), encoding="utf-8")
    accepted_snapshot = read_json(COMPACT)
    build_cockpit_snapshot.merge_verified_replay_evidence(
        accepted_snapshot,
        report_root=tmp_path,
    )
    assert accepted_snapshot["r2"]["verified"] == 3
    assert accepted_snapshot["r2"]["bytes"] == 1_100_000_000
    assert accepted_snapshot["r2"]["objects_added"] == 3
    assert accepted_snapshot["r2"]["recovery_objects"] == 1
    assert accepted_snapshot["r2"]["recovery_bytes"] == 112_345_679
    assert accepted_snapshot["postgresql"]["duplicates_avoided"] == 1

    invalid = deepcopy(valid)
    for path, replacement in mutations:
        set_nested(invalid, path, replacement)
    reseal(invalid)
    report_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(RuntimeError, match="preuve replay Jalon 12 refusée"):
        build_cockpit_snapshot.merge_verified_replay_evidence(
            read_json(COMPACT),
            report_root=tmp_path,
        )


def test_replay_must_match_gate_capture_set(
    tmp_path: Path,
) -> None:
    report = valid_replay_report()
    (tmp_path / "r2-replay-audit.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="preuve replay Jalon 12 refusée"):
        build_cockpit_snapshot.merge_verified_replay_evidence(
            read_json(COMPACT),
            report_root=tmp_path,
            expected_capture_set_sha256="c" * 64,
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("storage_paused", False),
        ("p3_p4_paused", False),
        ("external_social_networks_connected", True),
        ("raw_payloads_in_git", 1),
        ("postgresql_payload_body_rows", 1),
        ("unexpected_invariant", True),
    ],
)
def test_gate_report_rejects_any_invariant_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    key: str,
    value: object,
) -> None:
    invariants = valid_report_invariants()
    invariants[key] = value
    write_gate_report(
        tmp_path,
        {"invariants": invariants},
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="invariants incomplets"):
        build_cockpit_snapshot.build_prospective_observatory()


@pytest.mark.parametrize(
    "field",
    ["unexpected_identity", "unexpected_raw_payload"],
)
def test_gate_report_rejects_sensitive_unknown_public_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            field: {"value": "must-not-be-public"},
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="champ public Jalon 12 interdit"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_projects_only_allowlisted_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kickoff_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "operational_diagnostic": "ignored-by-public-projection",
            "fixtures": {
                "tracked": 1,
                "windows_planned": 1,
                "windows_due": 0,
                "next": [
                    {
                        "fixture_id": "api-football:1",
                        "home": 10,
                        "away": 20,
                        "kickoff_at": kickoff_at,
                        "competition": "Ligue 1",
                        "status": "REGISTERED",
                    }
                ],
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    assert "operational_diagnostic" not in snapshot
    assert snapshot["fixtures"]["next"] == [
        {
            "fixture_id": "api-football:1",
            "home": "10",
            "away": "20",
            "kickoff_at": kickoff_at,
            "competition": "Ligue 1",
            "status": "REGISTERED",
        }
    ]


def test_fixture_preview_rejects_identity_expansion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "fixtures": {
                "next": [
                    {
                        "fixture_id": "api-football:1",
                        "home": 10,
                        "away": 20,
                        "kickoff_at": "2026-07-28T18:00:00+00:00",
                        "competition": "Ligue 1",
                        "status": "REGISTERED",
                        "player_identity": "forbidden",
                    }
                ]
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="champ d'aperçu public"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_cannot_claim_replay_or_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "r2": {
                "bytes": 999_999_999,
                "deletions": 0,
                "lag": 999,
                "objects_added": 999,
                "recovery_objects": 999,
                "recovery_bytes": 999_999_999,
                "replay_status": "R2_REPLAY_VERIFIED",
                "verified": 999,
            },
            "postgresql": {
                "duplicates_avoided": 999,
                "reconstruction_status": "RECONSTRUCTIBLE_FROM_R2",
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    assert snapshot["r2"] == {
        "namespace": "prospective-deep-data/schema-v1",
        "objects_added": 0,
        "bytes": 0,
        "recovery_objects": 0,
        "recovery_bytes": 0,
        "verified": 0,
        "lag": 0,
        "deletions": 0,
        "replay_status": "NOT_RUN_NO_CAPTURE",
    }
    assert snapshot["postgresql"]["duplicates_avoided"] == 0
    assert snapshot["postgresql"]["reconstruction_status"] == "NOT_RUN_NO_CAPTURE"


@pytest.mark.parametrize(
    ("field", "spoofed"),
    [
        ("status", "R2_REPLAY_VERIFIED"),
        ("origin", "LIVE_PROSPECTIVE_CAPTURE"),
    ],
)
def test_gate_report_cannot_spoof_public_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    spoofed: str,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            field: spoofed,
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    assert snapshot[field] != spoofed
    assert snapshot["status"] == "GATES_BLOCKED_BY_COVERAGE"
    assert snapshot["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"


def test_fixture_preview_rejects_scalar_smuggling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "fixtures": {
                "next": [
                    {
                        "fixture_id": "api-football:1",
                        "home": "SYNTHETIC_SENSITIVE_IDENTITY",
                        "away": 20,
                        "kickoff_at": "2026-07-28T18:00:00+00:00",
                        "competition": "Ligue 1",
                        "status": "REGISTERED",
                    }
                ]
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="fixture d'aperçu Jalon 12 invalide"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_fixture_preview_rejects_same_team(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "fixtures": {
                "tracked": 1,
                "next": [
                    {
                        "fixture_id": "api-football:1",
                        "home": 10,
                        "away": 10,
                        "kickoff_at": "2026-07-28T18:00:00+00:00",
                        "competition": "Ligue 1",
                        "status": "REGISTERED",
                    }
                ],
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="fixture d'aperçu Jalon 12 invalide"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_fixture_preview_rejects_past_kickoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    generated_at = datetime.now(UTC)
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "fixtures": {
                "tracked": 1,
                "next": [
                    {
                        "fixture_id": "api-football:1",
                        "home": 10,
                        "away": 20,
                        "kickoff_at": (
                            generated_at
                            - timedelta(days=1)
                        ).isoformat(),
                        "competition": "Ligue 1",
                        "status": "REGISTERED",
                    }
                ],
            },
        },
        generated_at=generated_at.isoformat(),
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="kickoff d'aperçu Jalon 12 hors horizon"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_rejects_hash_only_live_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "captures": {"hashes": 1},
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="compteur de capture Jalon 12"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_rejects_receipt_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture_counters = {
        "due": 0,
        "attempted": 0,
        "captured": 1,
        "empty": 0,
        "missed": 0,
        "invalid": 0,
        "bytes": 123,
        "hashes": 1,
    }
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "captures": {
                **{key: value for key, value in fixture_counters.items() if key != "due"},
                "by_family": {"FIXTURE": fixture_counters},
            },
        },
        envelope_updates={"receipts": 0},
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="preuves de capture Jalon 12"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_rejects_impossible_gate_aggregate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "gates": {
                "by_name": {
                    "PROSPECTIVE_PLAYER_GATE": {
                        "status": "PASSED",
                        "passed": 2,
                        "total": 1,
                        "reason": "FORGED",
                    }
                }
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="agrégat de gate Jalon 12"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_rejects_invalid_ledger_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "ledger": {
                "events": 1,
                "head_hash": "SYNTHETIC_SENSITIVE_IDENTITY",
            },
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="ledger Jalon 12 incohérent"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_cannot_override_temporal_truth_rule(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(
        tmp_path,
        {
            "invariants": valid_report_invariants(),
            "temporal": {"truth_rule": "SYNTHETIC_SECRET_RULE"},
        },
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    assert (
        snapshot["temporal"]["truth_rule"]
        == "response_received_at < cutoff_at < kickoff_at"
    )


@pytest.mark.parametrize(
    "envelope_updates",
    [
        {"command": "pilot-mock"},
        {"policy_sha256": "0" * 64},
        {"real_bets": True},
        {"raw_payloads_in_git": 1},
    ],
)
def test_gate_report_rejects_wrong_authenticated_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    envelope_updates: dict[str, object],
) -> None:
    write_gate_report(
        tmp_path,
        {"invariants": valid_report_invariants()},
        envelope_updates=envelope_updates,
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="enveloppe opérationnelle Jalon 12"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_gate_report_rejects_tampered_or_future_freshness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_gate_report(tmp_path, {"invariants": valid_report_invariants()})
    path = tmp_path / "gate-report.json"
    tampered = read_json(path)
    observatory = tampered["observatory"]
    assert isinstance(observatory, dict)
    observatory["status"] = "R2_REPLAY_VERIFIED"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="enveloppe opérationnelle Jalon 12"):
        build_cockpit_snapshot.build_prospective_observatory()

    write_gate_report(
        tmp_path,
        {"invariants": valid_report_invariants()},
        generated_at="9999-12-31T23:59:59+00:00",
    )
    with pytest.raises(RuntimeError, match="horodatage opérationnel Jalon 12 futur"):
        build_cockpit_snapshot.build_prospective_observatory()


def test_pilot_mock_is_never_ingested_as_live(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pilot = operation_report(
        "pilot-mock",
        {
            "invariants": valid_report_invariants(),
            "captures": {"hashes": 1},
            "origin": "LIVE_PROSPECTIVE_CAPTURE",
        },
        extra={"publishable_as_live": False},
    )
    (tmp_path / "pilot-report.json").write_text(
        json.dumps(pilot),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROSPECTIVE_REPORT_ROOT", str(tmp_path))
    snapshot = build_cockpit_snapshot.build_prospective_observatory()
    assert snapshot["origin"] == "NO_PROSPECTIVE_CAPTURE_YET"
    assert snapshot["captures"]["hashes"] == 0


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
