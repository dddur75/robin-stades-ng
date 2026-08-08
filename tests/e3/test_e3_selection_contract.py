from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_e3a_selection_is_complete_deterministic_and_exact_key_only() -> None:
    selection = _read("reports/evidence/e3a/e3a-selection-manifest-v1.json")
    fixtures = selection["fixture_ids"]
    assert isinstance(fixtures, list)
    assert fixtures == sorted(set(fixtures))
    assert len(fixtures) == selection["expected_fixture_count"] == 308
    assert selection["eligible_fixture_count"] == 308
    assert selection["excluded_fixture_count"] == 0
    assert len(selection["allowed_r2_keys"]) == 19
    assert len(selection["payload_hashes"]) == 19
    assert len(selection["receipt_hashes"]) == 19
    without_hash = {key: value for key, value in selection.items() if key != "selection_hash"}
    canonical = json.dumps(
        without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert selection["selection_hash"] == hashlib.sha256(canonical).hexdigest()


def test_e3_manifest_and_workflow_are_manual_secret_free_and_bounded() -> None:
    mission = _read("configs/execution/p0-e3-capability-scale-v1.json")
    lock = _read("configs/execution/p0-e3-artifact-lock-v1.json")
    workflow = (ROOT / ".github/workflows/85-p0-e3-capability-scale.yml").read_text(
        encoding="utf-8"
    )
    assert mission["authorized_stages"] == ["E3A", "E3B"]
    assert mission["maximum_stage"] == "E3B"
    assert lock["selected_e3a_competition"] == "Ligue 1"
    assert lock["mission_source_bytes"] == 95_006_161
    assert lock["mission_source_byte_limit"] == 100_000_000
    assert "workflow_dispatch:" in workflow
    assert "push:" not in workflow
    assert "schedule:" not in workflow
    assert "cancel-in-progress: false" in workflow
    for secret in ("API_FOOTBALL_KEY", "DATABASE_URL", "ODDS_API_KEY", "R2_SECRET"):
        assert secret not in workflow


def test_e3_runner_has_no_provider_or_object_storage_client() -> None:
    runner = (ROOT / "scripts/run_p0_e3_capability_scale.py").read_text(encoding="utf-8")
    for forbidden in ("boto3", "botocore", "requests.get", "list_objects", "head_object"):
        assert forbidden not in runner
    assert "GITHUB_ARTIFACT_EXACT_ID" in runner
    assert "UNKNOWN_PRESERVED" in runner

