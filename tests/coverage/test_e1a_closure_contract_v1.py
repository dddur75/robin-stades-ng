import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_json(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_terminal_architecture_two_evidence_is_byte_immutable() -> None:
    expected = {
        "reports/coverage/p0-evidence-ladder-stage-E1A-architecture-2-v1.json":
            "e878ccf344f17894f4766b4de65c48061d2db65b99529873448af7d8ba7088bd",
        "reports/coverage/p0-evidence-ladder-feed-E1A-architecture-2-v1.json":
            "852d5ffc4bcb3252e42ae89d6f813cf28d91a55ceeff39b830337b9a2682d88e",
        "reports/coverage/p0-evidence-ladder-gate-E1A-architecture-2-v1.json":
            "d7505f634374ec8961023a21987d7139dd3e13e46f677fa915812346a2722a9f",
        "reports/coverage/p0-evidence-ladder-cost-E1A-architecture-2-v1.json":
            "df09d124b409a46c5dc98c3886ded50722562f8738fef6ee95aac452109fb366",
    }
    for relative, digest in expected.items():
        # Git may materialize CRLF on Windows even though the immutable blob is LF.
        payload = (ROOT / relative).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(payload).hexdigest() == digest


def test_e1a_status_is_local_and_does_not_claim_global_readiness() -> None:
    status = load_json("reports/coverage/e1a-capability-scope-status-v1.json")
    statuses = set(status["statuses"])
    assert status["campaign"] == "E1A_ABSENCE_CAUSE_CLASSIFICATION"
    assert status["historical_verdict"] == "FAIL_AND_STOP"
    assert status["historical_verdict_scope"] == "LOCAL_CAMPAIGN_ONLY"
    assert "UNRELATED_CAPABILITIES_NOT_EVALUATED" in statuses
    assert "P0_GLOBAL_READINESS_NOT_DETERMINED_BY_E1A" in statuses
    assert status["not_executed_stages"] == ["E1B", "E2", "E3A", "E3B", "E4"]
    assert status["capability_interpretation"]["all_unrelated_capabilities"] == (
        "NOT_EVALUATED"
    )
    assert not statuses.intersection(status["forbidden_unproven_statuses"])


def test_unknown_profile_conserves_the_e1a_partition() -> None:
    profile = load_json("reports/coverage/e1a-unknown-profile-v1.json")
    signatures = profile["distribution_by_signature"]
    assert profile["canonical_category"] == "ABSENCE_CAUSE_UNKNOWN"
    assert profile["historical_source_label"] == "UNCLASSIFIABLE"
    assert profile["unknown_count"] == 149
    assert profile["total_absence_records"] == 3036
    assert profile["signature_count"] == len(signatures) == 17
    assert sum(item["count"] for item in signatures) == 149
    assert len({item["signature_sha256"] for item in signatures}) == 17
    assert 2681 + 206 + profile["unknown_count"] == profile["total_absence_records"]
    for dimension in ("team", "player", "position", "fixture", "date"):
        assert profile[f"distribution_by_{dimension}"]["status"] == (
            "NOT_AVAILABLE_IN_COMMITTED_EVIDENCE"
        )


def test_historical_handoff_cannot_restart_the_v1_campaign() -> None:
    brief = (ROOT / "NEXT-MISSION-BRIEF.md").read_text(encoding="utf-8")
    prompt = (ROOT / "NEXT-MISSION-PROMPT.md").read_text(encoding="utf-8")
    assert "troisième architecture" in brief
    assert "Ne lancer ni E1A" in prompt
    assert "capability-scoped-evidence-ladder-v2" in brief
    assert "capability-scoped-evidence-ladder-v2" in prompt
