import copy
from pathlib import Path

import pytest

from robin.governance.capability_evidence import (
    ALLOWED_STATUSES,
    CapabilityContractError,
    load_capability_contract,
    preserve_absence_cause,
    resolve_effective_statuses,
    validate_capability_contract,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs" / "data" / "capability-scoped-evidence-ladder-v2.json"
E1A_STATUS_PATH = ROOT / "reports" / "coverage" / "e1a-capability-scope-status-v1.json"
E1A_PROFILE_PATH = ROOT / "reports" / "coverage" / "e1a-unknown-profile-v1.json"


def load_contract() -> dict[str, object]:
    return load_capability_contract(CONTRACT_PATH)


def capability(document: dict[str, object], capability_id: str) -> dict[str, object]:
    return next(
        item
        for item in document["capabilities"]
        if item["capability_id"] == capability_id
    )


def synthetic_capability(
    capability_id: str,
    *,
    depends_on: list[str],
    requires_exact_absence_cause: bool,
) -> dict[str, object]:
    return {
        "capability_id": capability_id,
        "family": "synthetic_test_only",
        "source_family": "synthetic_test_only",
        "grain": "one synthetic observation",
        "temporal_class": "SYNTHETIC",
        "tested_scope": "NONE",
        "status": "NOT_EVALUATED",
        "depends_on": depends_on,
        "requires_exact_absence_cause": requires_exact_absence_cause,
        "allows_unknown": True,
        "unknown_policy": "INCLUDE_UNKNOWN_AS_UNKNOWN",
        "scale_authorized": False,
        "block_reason": "SYNTHETIC_DEPENDENCY_TEST",
        "evidence_claims": [],
    }


def test_contract_is_valid_and_uses_the_closed_status_vocabulary() -> None:
    document = load_contract()
    validate_capability_contract(document)
    assert set(document["allowed_statuses"]) == ALLOWED_STATUSES
    assert "READY" not in document["allowed_statuses"]
    assert len(document["capabilities"]) == 18


def test_e1a_stop_is_local_to_exact_cause() -> None:
    statuses = resolve_effective_statuses(load_contract())
    assert statuses["ABSENCE_CAUSE_EXACT"] == "STOPPED_LOCAL_CAMPAIGN"
    for capability_id in (
        "TEAM",
        "LINEUP",
        "FORMATION",
        "CALENDAR",
        "FATIGUE",
        "STANDINGS",
    ):
        assert statuses[capability_id] == "NOT_EVALUATED"


def test_contract_matches_committed_e1a_partition() -> None:
    status = load_capability_contract(E1A_STATUS_PATH)
    profile = load_capability_contract(E1A_PROFILE_PATH)
    assert status["campaign"] == "E1A_ABSENCE_CAUSE_CLASSIFICATION"
    assert status["historical_verdict_scope"] == "LOCAL_CAMPAIGN_ONLY"
    assert status["technical_cells"] == {"verified": 16, "expected": 16}
    assert status["absence_identity"] == {
        "total": profile["total_absence_records"],
        "injuries_confirmed": 2681,
        "suspensions_confirmed": 206,
        "absence_cause_unknown": profile["unknown_count"],
        "identity_exact": True,
    }
    assert profile["canonical_category"] == "ABSENCE_CAUSE_UNKNOWN"
    assert profile["signature_count"] == 17
    assert sum(item["count"] for item in profile["distribution_by_signature"]) == 149
    assert 2681 + 206 + profile["unknown_count"] == profile["total_absence_records"]


def test_exact_cause_dependents_are_blocked_but_independent_crosses_are_not() -> None:
    document = load_contract()
    document["capabilities"].extend(
        [
            synthetic_capability(
                "EXACT_CAUSE_CHILD",
                depends_on=["ABSENCE_CAUSE_EXACT"],
                requires_exact_absence_cause=True,
            ),
            synthetic_capability(
                "DEPENDENT_CROSS",
                depends_on=["TEAM", "ABSENCE_CAUSE_EXACT"],
                requires_exact_absence_cause=True,
            ),
            synthetic_capability(
                "INDEPENDENT_CROSS",
                depends_on=["TEAM", "CALENDAR"],
                requires_exact_absence_cause=False,
            ),
        ]
    )
    statuses = resolve_effective_statuses(document)
    assert statuses["EXACT_CAUSE_CHILD"] == "BLOCKED_BY_DEPENDENCY"
    assert statuses["DEPENDENT_CROSS"] == "BLOCKED_BY_DEPENDENCY"
    assert statuses["INDEPENDENT_CROSS"] == "NOT_EVALUATED"


def test_unknown_remains_a_first_class_value() -> None:
    assert preserve_absence_cause("ABSENCE_CAUSE_UNKNOWN") == "ABSENCE_CAUSE_UNKNOWN"
    with pytest.raises(CapabilityContractError, match="unsupported absence cause"):
        preserve_absence_cause("0")


def test_unmeasured_capabilities_never_claim_readiness_or_scale() -> None:
    document = load_contract()
    for item in document["capabilities"]:
        if item["tested_scope"] == "NONE":
            assert item["status"] == "NOT_EVALUATED"
            assert item["scale_authorized"] is False


@pytest.mark.parametrize("forbidden_status", ["READY", "READY_SOMETIMES"])
def test_ambiguous_or_unknown_ready_status_is_rejected(forbidden_status: str) -> None:
    document = load_contract()
    capability(document, "TEAM")["status"] = forbidden_status
    with pytest.raises(CapabilityContractError, match="forbidden status"):
        validate_capability_contract(document)


def test_scale_jump_is_rejected() -> None:
    document = load_contract()
    capability(document, "TEAM")["scale_authorized"] = True
    with pytest.raises(CapabilityContractError, match="cannot scale"):
        validate_capability_contract(document)


def test_untested_capability_cannot_claim_qualified_readiness() -> None:
    document = load_contract()
    item = capability(document, "TEAM")
    item["status"] = "READY_STRICT"
    item["scale_authorized"] = True
    with pytest.raises(CapabilityContractError, match="without tested scope and evidence"):
        validate_capability_contract(document)


def test_ready_capability_requires_ready_dependencies() -> None:
    document = load_contract()
    item = capability(document, "TEAM_FORM")
    item["tested_scope"] = "SYNTHETIC_PROVEN_SCOPE"
    item["status"] = "READY_STRICT"
    item["scale_authorized"] = True
    item["evidence_claims"] = ["SYNTHETIC.TEST.CLAIM"]
    with pytest.raises(CapabilityContractError, match="dependencies are ready"):
        validate_capability_contract(document)


def test_ready_capability_cannot_ignore_blocked_exact_cause() -> None:
    document = load_contract()
    item = synthetic_capability(
        "EXACT_CAUSE_READY_CHILD",
        depends_on=["ABSENCE_CAUSE_EXACT"],
        requires_exact_absence_cause=True,
    )
    item.update(
        tested_scope="SYNTHETIC_PROVEN_SCOPE",
        status="READY_STRICT",
        scale_authorized=True,
        evidence_claims=["SYNTHETIC.TEST.CLAIM"],
    )
    document["capabilities"].append(item)
    with pytest.raises(CapabilityContractError, match="dependencies are ready"):
        validate_capability_contract(document)


def test_external_effects_are_always_denied() -> None:
    document = load_contract()
    assert all(not value for value in document["external_effects"].values())
    tampered = copy.deepcopy(document)
    tampered["external_effects"]["r2_reads"] = 1
    with pytest.raises(CapabilityContractError, match="external effects"):
        validate_capability_contract(tampered)

    missing = copy.deepcopy(document)
    del missing["external_effects"]["r2_reads"]
    with pytest.raises(CapabilityContractError, match="closed required schema"):
        validate_capability_contract(missing)

    extra = copy.deepcopy(document)
    extra["external_effects"]["unknown_effect"] = 0
    with pytest.raises(CapabilityContractError, match="closed required schema"):
        validate_capability_contract(extra)


def test_exact_cause_dependency_must_be_explicit() -> None:
    document = load_contract()
    document["capabilities"].append(
        synthetic_capability(
            "HIDDEN_EXACT_DEPENDENCY",
            depends_on=["TEAM"],
            requires_exact_absence_cause=True,
        )
    )
    with pytest.raises(CapabilityContractError, match="without declaring the dependency"):
        validate_capability_contract(document)
