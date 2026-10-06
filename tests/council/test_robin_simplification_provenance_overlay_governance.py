from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_SIMPLIFICATION_PROVENANCE_OVERLAY_20261005"
MANIFEST = ROOT / "configs/execution/robin-simplification-provenance-overlay-20261005.json"


def _json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_overlay_is_immutable_zero_effect_and_does_not_reset_parent_runtime() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(manifest) == {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    assert manifest["mission_id"] == MISSION_ID
    assert manifest["authorized_stages"] == ["E1", "E2", "E3A", "E3B", "E4"]
    assert manifest["maximum_stage"] == "E4"
    assert manifest["source_hash"] == (
        "cba3fd7074ca102fb629c5e1b1507412f53bbd1a680cc6307e0043f4a1e46dd9"
    )
    effects = ";".join(manifest["external_effects"])
    assert "PARENT_ROBIN_AUTONOMOUS_LAB_RUNTIME_AUTHORITY_UNCHANGED" in effects
    for denied in (
        "PROVIDER_HTTP_REQUESTS_0",
        "PROVIDER_CREDITS_0",
        "R2_WRITES_0",
        "LIVE_WORKFLOW_DISPATCHES_0",
        "PURCHASES_0",
        "REAL_BETS_0",
        "PROMOTIONS_0",
        "SOCIAL_PUBLICATIONS_0",
        "BACKFILLS_0",
    ):
        assert denied in effects


def test_overlay_authorizes_only_the_minimal_provenance_change_and_controls() -> None:
    matrix = _json("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][MISSION_ID]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C1", "C2", "DP6", "A2"]
    assert mission["scale_ceiling"] == "E4"
    allowed = set(mission["allowed_paths"])
    assert {
        "src/robin/capture/recurring_real_data.py",
        "tests/capture/test_recurring_real_data.py",
        "configs/execution/robin-simplification-provenance-overlay-20261005.json",
        "tests/council/test_robin_simplification_provenance_overlay_governance.py",
        "configs/agents/mission-activation-matrix-v3.json",
        "configs/agents/agent-report-schema-v3.json",
        "tests/council/test_robin_council_os_v3.py",
        "reports/council/decision-ledger.jsonl",
    } <= allowed
    assert ".github/workflows/92-robin-autonomous-lab.yml" not in allowed
    assert "scripts/run_recurring_real_data.py" not in allowed
    assert mission["delivery_keys"] == {
        "architecture": ["C1"],
        "governance": ["C2"],
        "data": ["DP6"],
        "platform": ["A2"],
    }


def test_overlay_is_registered_in_agent_schema() -> None:
    schema = _json("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
