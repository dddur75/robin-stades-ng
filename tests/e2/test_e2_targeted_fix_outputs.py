from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_historical_e2_measurement_is_unchanged() -> None:
    payload = (ROOT / "reports/evidence/e2/e2-measurement-v1.json").read_bytes()
    assert hashlib.sha256(payload.replace(b"\r\n", b"\n")).hexdigest() == (
        "b18c42f62453c72514ad3a9ad388a55eb1f504d9d2b11a0371fd94b417d9be15"
    )


def test_exact_diagnostic_confirms_source_partial_without_code_fix() -> None:
    report = load("reports/evidence/e2/e2-player-statistics-1208603-diagnostic-v1.json")
    assert report["fixture_id"] == 1208603
    assert report["root_cause"] == "PROVIDER_INCONSISTENCY"
    assert report["missing_identity"] == [405681]
    assert report["unexpected_identity"] == [496425]
    assert report["duplicated_identity"] == []
    assert report["code_fix_required"] is False
    assert report["recommended_status"] == "PLAYER_STATISTICS_E2_MEASURED_PARTIAL"
    hashes = report["source_hashes"]
    assert isinstance(hashes, dict)
    assert hashes["r2_gets"] == 2
    assert hashes["network_bytes"] == 73476


def test_one_fixture_census_is_sanitized_and_bounded() -> None:
    census = load("reports/evidence/e2/e2-1208603-field-path-census-v1.json")
    assert census["scope"] == "ONE_FIXTURE_ONLY_NO_PROVIDER_GENERALIZATION"
    rows = census["rows"]
    assert isinstance(rows, list) and len(rows) == 120
    allowed = {
        "MAPPED",
        "MAPPED_ALIAS",
        "DERIVED",
        "UNMAPPED_FIELD",
        "UNKNOWN_VALUE",
        "IDENTITY_ONLY",
        "POST_MATCH_ONLY",
        "IGNORED_WITH_REASON",
    }
    assert {row["mapped_status"] for row in rows} <= allowed
    assert all("value" not in row for row in rows)


def test_launch_set_is_additive_and_stops_before_e3a() -> None:
    launch = load("reports/e3a/e3a-launch-candidate-set-v1.json")
    assert launch["e3a_executed"] is False
    assert launch["e3b_executed"] is False
    assert launch["masks_built"] is False
    assert launch["e3a_blocked"] == ["PLAYER_STATISTICS"]
    candidates = launch["e3a_candidates"]
    assert isinstance(candidates, list)
    assert set(candidates) == {
        "TEAM",
        "PLAYER",
        "LINEUP",
        "FORMATION",
        "EVENTS",
        "TEAM_STATISTICS",
        "DISCIPLINE_GENERIC",
        "CALENDAR",
    }
    rows = {row["capability_id"]: row for row in launch["rows"]}
    assert rows["TEAM"]["scientific_role"] == "IDENTITY_ONLY"
    assert rows["PLAYER"]["scientific_role"] == "IDENTITY_ONLY"
    assert rows["LINEUP"]["scientific_role"] == "RECONSTRUCTED_DESCRIPTIVE_ONLY"
    assert rows["FORMATION"]["scientific_role"] == "RECONSTRUCTED_DESCRIPTIVE_ONLY"
    for capability in ("EVENTS", "TEAM_STATISTICS", "DISCIPLINE_GENERIC"):
        assert rows[capability]["scientific_role"] == "LAGGABLE_POST_MATCH_SOURCE"
        assert rows[capability]["same_match_predictor_allowed"] is False
    assert rows["CALENDAR"]["scientific_role"] == "STRICT_PREDICTOR_SOURCE"
    assert rows["PLAYER_STATISTICS"]["scientific_role"] == "BLOCKED"


def test_pr34_audit_keeps_required_granular_evidence() -> None:
    audit = load("reports/closure/pr34-size-and-duplication-audit-v1.json")
    assert audit["recommendation"] == "NO_COMPACTION_REQUIRED"
    assert audit["detailed_fixture_arrays"] == [
        {
            "file": "reports/evidence/e2/e2-selection-manifest-v1.json",
            "json_path": "$.fixtures",
            "rows": 100,
            "authoritative": True,
        }
    ]
    assert audit["duplicated_fixture_arrays"] == []
    assert audit["raw_payload_files"] == []
    assert audit["temporary_files"] == []


def test_e3_bootstrap_is_manual_dormant_and_secret_free() -> None:
    workflow = (
        ROOT / ".github/workflows/85-p0-e3-capability-scale.yml"
    ).read_text(encoding="utf-8")
    trigger = workflow.split("permissions:", maxsplit=1)[0]
    assert "workflow_dispatch:" in trigger
    assert "push:" not in trigger
    assert "pull_request:" not in trigger
    assert "schedule:" not in trigger
    assert "secrets." not in workflow
    assert "R2_GET_ALLOWED: \"0\"" in workflow
    assert "TRIPLE_SEARCH_LOCKED: \"true\"" in workflow
    assert "cancel-in-progress: false" in workflow
    for action in (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        assert action in workflow
