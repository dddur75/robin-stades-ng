from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import build_cockpit_snapshot


def test_matchup_snapshot_preserves_campaign_and_preregistration_proof() -> None:
    matchup = build_cockpit_snapshot.build_matchup_lab()

    assert matchup["results"]["campaign"] == "11A"
    assert (
        matchup["results"]["status"]
        == "DESCRIPTIVE_RETROSPECTIVE_DIAGNOSTIC"
    )
    hypotheses = matchup["experiments"]["ownerHypotheses"]
    assert len(hypotheses) == 8
    assert all(item["frozenBeforeResults"] is True for item in hypotheses)
    assert all(item["minimumSupport"] >= 80 for item in hypotheses)
    assert all(item["cutoff"] != "UNSPECIFIED" for item in hypotheses)
    assert all(len(item["preregistrationHash"]) == 64 for item in hypotheses)
    assert matchup["promotion"]["criteria"] == [
        {"name": "DEEP_DATA_GATES", "passed": False}
    ]


def test_matchup_only_refresh_preserves_other_cockpit_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "cockpit-data.json"
    output_hash = tmp_path / "cockpit-data.sha256"
    original = {
        "generatedAt": "2026-01-01T00:00:00+00:00",
        "deepData": {"criticalClosure": {"status": "JALON_9"}},
        "patternResearch": {"verdict": "JALON_10_NO_ROBUST_PATTERN"},
        "matchupLab": {"verdict": "STALE"},
    }
    output.write_text(
        json.dumps(original, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(build_cockpit_snapshot, "OUTPUT", output)
    monkeypatch.setattr(build_cockpit_snapshot, "OUTPUT_HASH", output_hash)
    monkeypatch.setattr(
        build_cockpit_snapshot,
        "build_matchup_lab",
        lambda: {"verdict": "JALON_11_BLOCKED_BY_DATA_GATES"},
    )
    monkeypatch.setenv("COCKPIT_MATCHUP_ONLY", "1")

    build_cockpit_snapshot.main()

    refreshed = json.loads(output.read_text(encoding="utf-8"))
    assert refreshed["deepData"] == original["deepData"]
    assert refreshed["patternResearch"] == original["patternResearch"]
    assert refreshed["matchupLab"] == {
        "verdict": "JALON_11_BLOCKED_BY_DATA_GATES"
    }
    assert refreshed["generatedAt"] != original["generatedAt"]
    assert output_hash.read_text(encoding="ascii").strip() == hashlib.sha256(
        output.read_bytes()
    ).hexdigest()
