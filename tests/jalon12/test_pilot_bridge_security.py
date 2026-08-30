from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
LEGACY_CI = WORKFLOWS / "ci.yml"
SAFE_CI = WORKFLOWS / "ci-safe-v2.yml"
HOLD = ROOT / "scripts" / "check_chronos_github_hold_v3.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_secret_backed_pilot_bridge_is_absent_from_both_ci_definitions() -> None:
    for path in (LEGACY_CI, SAFE_CI):
        content = _text(path)
        assert "jalon12-pilot:" not in content
        assert "[run-j12-pilot]" not in content
        assert "[run-j12-replay-only]" not in content
        assert "${{ secrets." not in content


def test_legacy_ci_workflow_id_is_required_to_remain_manually_disabled() -> None:
    hold = _text(HOLD)
    assert 'LEGACY_CI_WORKFLOW_PATH = ".github/workflows/ci.yml"' in hold
    assert 'legacy_ci_workflow.get("state") != "disabled_manually"' in hold
    assert '"workflow_id": int(legacy_ci_workflow["id"])' in hold
    assert "CHRONOS_LEGACY_CI_NOT_QUARANTINED" in hold


def test_safe_ci_uses_a_distinct_workflow_path_and_read_only_permissions() -> None:
    safe = yaml.safe_load(_text(SAFE_CI))
    assert safe["name"] == "00 - Qualite continue SAFE V2"
    assert safe["permissions"] == {"contents": "read"}
    assert set(safe[True]) == {"workflow_dispatch", "pull_request", "push"}
    assert safe[True]["push"]["branches"] == ["main"]


def test_safe_ci_is_equivalent_to_the_sanitized_legacy_copy() -> None:
    legacy = yaml.safe_load(_text(LEGACY_CI))
    safe = yaml.safe_load(_text(SAFE_CI))
    legacy["name"] = safe["name"]
    assert safe == legacy


def test_safe_ci_has_no_secret_or_production_environment_surface() -> None:
    content = _text(SAFE_CI)
    assert "${{ secrets." not in content
    assert "chronos-control-plane-production" not in content


def test_hold_uses_only_safe_ci_for_exact_head_and_post_merge_proof() -> None:
    hold = _text(HOLD)
    assert 'SAFE_CI_WORKFLOW_PATH = ".github/workflows/ci-safe-v2.yml"' in hold
    assert "actions/workflows/ci-safe-v2.yml/runs" in hold
    assert '"workflow_path": SAFE_CI_WORKFLOW_PATH' in hold
    assert 'item.get("run_attempt") == 1' in hold
