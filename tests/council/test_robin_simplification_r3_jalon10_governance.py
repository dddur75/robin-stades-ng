from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISSION_ID = "ROBIN_SIMPLIFICATION_R3_JALON10_20261005"
MANIFEST = ROOT / "configs/execution/robin-simplification-r3-jalon10-20261005.json"
SOURCE = ROOT / "configs/execution/robin-simplification-r3-jalon10-source.md"
SOURCE_SHA256 = "6471afcc91aaa20a55fe61f1d686ef869cd841f90d2afee2e4070a7a59cb92dc"


def _json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _lf_sha256(path: Path) -> str:
    source = path.read_bytes().replace(b"\r\n", b"\n").removesuffix(b"\n")
    return hashlib.sha256(source).hexdigest()


def test_r3_jalon10_addendum_is_exact_bounded_and_provider_free() -> None:
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
    assert manifest["compute_budget"] == 5_000
    assert manifest["time_budget"] == 604_800
    assert manifest["expires_at"] == "2026-11-03T23:59:59Z"
    assert manifest["source_hash"] == SOURCE_SHA256 == _lf_sha256(SOURCE)
    assert manifest["external_effects"] == [
        "READ_PINNED_HISTORICAL_GIT_BLOBS_ONLY",
        "READ_VERIFIED_LOCAL_FROZEN_EVIDENCE_ONLY",
        "WRITE_LOCAL_NON_REGRESSION_ARTIFACTS_ONLY",
        "PROVIDER_HTTP_REQUESTS_0;PROVIDER_CREDITS_0;R2_WRITES_0;R2_DELETES_0",
        "PURCHASES_0;REAL_BETS_0;PROMOTIONS_0;SOCIAL_PUBLICATIONS_0;BACKFILLS_0",
    ]


def test_r3_jalon10_addendum_has_one_writer_and_exact_paths() -> None:
    matrix = _json("configs/agents/mission-activation-matrix-v3.json")
    mission = matrix["missions"][MISSION_ID]
    assert mission["writer"] == "C0"
    assert mission["agents"] == ["C0", "C2", "DP6", "A2"]
    assert mission["scale_ceiling"] == "E4"
    assert mission["allowed_paths"] == [
        ".github/workflows/ci-safe-v2.yml",
        "configs/agents/agent-report-schema-v3.json",
        "configs/agents/mission-activation-matrix-v3.json",
        "configs/execution/robin-simplification-r3-jalon10-20261005.json",
        "configs/execution/robin-simplification-r3-jalon10-source.md",
        "docs/pattern-research/JALON-10-NON-REGRESSION-R3.md",
        "docs/superpowers/plans/2026-10-05-robin-simplification-exploration.md",
        "docs/superpowers/specs/2026-10-05-robin-simplification-exploration-design.md",
        "reports/council/decision-ledger.jsonl",
        "reports/council/robin-simplification-r3-jalon10-a2-operations-v1.json",
        "reports/council/robin-simplification-r3-jalon10-c2-qa-v1.json",
        "reports/council/robin-simplification-r3-jalon10-dp6-science-v1.json",
        "reports/council/robin-simplification-r3-jalon10-final-review-v1.json",
        "reports/evidence/evidence-graph.json",
        "reports/hypothesis-evidence/r3-jalon10-non-regression.json",
        "scripts/run_jalon10_non_regression.py",
        "src/robin/hypothesis_evidence/non_regression.py",
        "tests/council/test_robin_simplification_r3_jalon10_governance.py",
        "tests/council/test_robin_council_os_v3.py",
        "tests/hypothesis_evidence/test_jalon10_non_regression.py",
    ]

    schema = _json("configs/agents/agent-report-schema-v3.json")
    assert MISSION_ID in schema["properties"]["mission_id"]["enum"]
