from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from robin.deep_football.campaigns import campaign_manifest
from robin.deep_football.contracts import (
    DataGateStatus,
    DatasetContract,
    FeatureContract,
    PatternStatus,
    ResearchMode,
)
from robin.deep_football.coverage import (
    PLAYER_THRESHOLD,
    CoverageEvidence,
    assess_gate,
    evaluate_gate_registry,
)
from robin.deep_football.matchups import (
    evaluate_hypothesis_eligibility,
    owner_hypotheses,
)
from robin.deep_football.promotion import (
    PROMOTION_CRITERIA,
    evaluate_promotion,
)
from robin.deep_football.public_evidence import (
    EvidenceEventKind,
    PublicEvidenceLedgerV2,
)

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def _coverage(
    season: int,
    *,
    covered: int = 95,
    expected: int = 100,
    identity: float | None = 1.0,
    minutes: bool | None = True,
    cutoff: bool = True,
    quality: str = "PASSED",
) -> CoverageEvidence:
    return CoverageEvidence(
        competition="Ligue 1",
        season=season,
        family="PLAYER",
        fixtures_expected=expected,
        fixtures_covered=covered,
        identity_rate=identity,
        minutes_coherent=minutes,
        cutoff_proven=cutoff,
        source="API_FOOTBALL_CACHE",
        quality_status=quality,
    )


def _feature_contract() -> FeatureContract:
    return FeatureContract(
        feature_name="player_goals_last_3_appearances",
        feature_version="2.0.0",
        entity="PLAYER_FIXTURE",
        source="API_FOOTBALL_CACHE",
        available_at="PRE_MATCH",
        lookback={"type": "APPEARANCES", "count": 3},
        unit="goals",
        allowed_markets=["1X2", "OVER_2_5"],
        allowed_research_modes=[ResearchMode.PRE_LINEUP],
        quality_gate="PLAYER_FORM_GATE",
        leakage_tests=["TARGET_FIXTURE_EXCLUDED", "STRICT_INPUT_CUTOFF"],
        provenance={
            "provider": "API_FOOTBALL",
            "source_field": "fixture_events.Goal",
        },
    )


def _dataset_contract(**updates: object) -> DatasetContract:
    payload: dict[str, object] = {
        "dataset_name": "player-pre-lineup-v2",
        "dataset_version": "2.0.0",
        "mode": ResearchMode.PRE_LINEUP,
        "cutoff_policy": "STRICTLY_BEFORE_TARGET_KICKOFF",
        "feature_contract_hashes": ["a" * 64],
        "source_hashes": ["b" * 64],
        "row_count": 100,
        "fixture_count": 100,
        "coverage": {"Ligue 1:2025": 0.95},
        "missingness": {"goals": 0.10},
        "exclusions": {"insufficient_history": 5},
        "leakage_audit": {"passed": True, "violations": 0},
    }
    payload.update(updates)
    return DatasetContract.model_validate(payload)


def _all_promotion_evidence() -> dict[str, bool]:
    return {criterion: True for criterion in PROMOTION_CRITERIA}


def test_feature_contract_is_versioned_hashed_and_fail_closed() -> None:
    contract = _feature_contract()
    replay = _feature_contract()
    assert contract.contract_hash == replay.contract_hash
    assert len(contract.contract_hash) == 64
    assert contract.missing_policy == "MISSING_NOT_ZERO"
    assert contract.cutoff_policy == "STRICTLY_BEFORE_TARGET_KICKOFF"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "missing_policy",
            "ZERO_IMPUTATION",
            "DEEP_FEATURE_MISSING_POLICY_MUST_PRESERVE_MISSING",
        ),
        (
            "cutoff_policy",
            "AT_OR_BEFORE_KICKOFF",
            "DEEP_FEATURE_CUTOFF_MUST_BE_STRICT",
        ),
        ("leakage_tests", [], "DEEP_FEATURE_LEAKAGE_TESTS_REQUIRED"),
        ("provenance", {}, "DEEP_FEATURE_PROVENANCE_REQUIRED"),
    ],
)
def test_feature_contract_rejects_unsafe_variants(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _feature_contract().model_dump()
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        FeatureContract.model_validate(payload)


def test_dataset_contract_hashes_replay_and_keeps_production_locked() -> None:
    dataset = _dataset_contract()
    assert dataset.dataset_hash == _dataset_contract().dataset_hash
    assert len(dataset.dataset_hash) == 64
    assert dataset.production_status == "PRODUCTION_LOCKED"
    assert dataset.demo_mode_enabled is False


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"demo_mode_enabled": True}, "DEMO_DATASET_FORBIDDEN"),
        ({"production_status": "PRODUCTION_READY"}, "PRODUCTION_MUST_REMAIN_LOCKED"),
        ({"leakage_audit": {"passed": False}}, "DATASET_LEAKAGE_AUDIT_REQUIRED"),
        ({"cutoff_policy": "NON_STRICT"}, "DATASET_CUTOFF_NOT_STRICT"),
    ],
)
def test_dataset_contract_rejects_demo_unlocked_or_leaky_data(
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _dataset_contract(**updates)


def test_coverage_gate_is_ready_only_with_three_complete_seasons() -> None:
    assessment = assess_gate(
        "PLAYER_GATE",
        [_coverage(2023), _coverage(2024), _coverage(2025)],
        PLAYER_THRESHOLD,
    )
    assert assessment.ready is True
    assert assessment.status == DataGateStatus.READY
    assert assessment.eligible_seasons == (2023, 2024, 2025)
    assert assessment.reasons == ()


def test_coverage_gate_fails_temporality_before_identity_or_coverage() -> None:
    evidence = [
        _coverage(2023),
        _coverage(2024, cutoff=False),
        _coverage(2025),
    ]
    assessment = assess_gate("PLAYER_GATE", evidence, PLAYER_THRESHOLD)
    assert assessment.status == DataGateStatus.BLOCKED_BY_TEMPORALITY
    assert assessment.eligible_seasons == ()
    assert assessment.reasons == ("CUTOFF_UNPROVEN:2024",)


def test_coverage_gate_fails_identity_and_preserves_reason() -> None:
    evidence = [
        _coverage(2023),
        _coverage(2024, identity=0.98),
        _coverage(2025),
    ]
    assessment = assess_gate("PLAYER_GATE", evidence, PLAYER_THRESHOLD)
    assert assessment.status == DataGateStatus.BLOCKED_BY_IDENTITY
    assert assessment.reasons == ("IDENTITY_BELOW_THRESHOLD:2024",)


def test_coverage_gate_is_partial_when_only_two_seasons_qualify() -> None:
    evidence = [
        _coverage(2023),
        _coverage(2024),
        _coverage(2025, covered=40),
    ]
    assessment = assess_gate("PLAYER_GATE", evidence, PLAYER_THRESHOLD)
    assert assessment.status == DataGateStatus.PARTIAL
    assert assessment.eligible_seasons == (2023, 2024)
    assert assessment.reasons == (
        "ELIGIBLE_SEASONS:2",
        "MINIMUM_SEASONS:3",
    )


def test_gate_registry_always_emits_every_preregistered_gate() -> None:
    registry = evaluate_gate_registry({})
    assert set(registry) == {
        "PLAYER_GATE",
        "LINEUP_GATE",
        "ABSENCE_GATE",
        "FORMATION_GATE",
        "FOOTEDNESS_GATE",
        "PLAYER_FORM_GATE",
        "STARTER_BASELINE_GATE",
    }
    assert all(
        assessment.status == DataGateStatus.BLOCKED_BY_COVERAGE
        for assessment in registry.values()
    )


def test_owner_hypotheses_are_exactly_h11_001_to_h11_008_and_frozen() -> None:
    hypotheses = owner_hypotheses()
    assert tuple(item.hypothesis_id for item in hypotheses) == tuple(
        f"H11-{index:03d}" for index in range(1, 9)
    )
    assert all(item.frozen_before_results for item in hypotheses)
    assert len({item.preregistration_hash for item in hypotheses}) == 8
    assert all(item.minimum_support >= 80 for item in hypotheses)


def test_h11_absence_and_footedness_hypotheses_fail_their_data_gates() -> None:
    by_id = {item.hypothesis_id: item for item in owner_hypotheses()}
    common_ready = {
        "PLAYER_FORM_GATE": DataGateStatus.READY,
        "STARTER_BASELINE_GATE": DataGateStatus.READY,
        "LINEUP_GATE": DataGateStatus.READY,
    }
    h001 = evaluate_hypothesis_eligibility(
        by_id["H11-001"],
        {
            **common_ready,
            "ABSENCE_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
        },
    )
    h003 = evaluate_hypothesis_eligibility(
        by_id["H11-003"],
        {
            **common_ready,
            "FOOTEDNESS_GATE": DataGateStatus.BLOCKED_BY_COVERAGE,
        },
    )
    assert h001.status == PatternStatus.DATA_GATE_BLOCKED
    assert h001.blocking_gates == ("ABSENCE_GATE",)
    assert h003.status == PatternStatus.DATA_GATE_BLOCKED
    assert h003.blocking_gates == ("FOOTEDNESS_GATE",)


def test_h11_formation_hypothesis_is_eligible_only_when_every_gate_is_ready() -> None:
    h002 = owner_hypotheses()[1]
    eligible = evaluate_hypothesis_eligibility(
        h002,
        {
            "LINEUP_GATE": DataGateStatus.READY,
            "FORMATION_GATE": DataGateStatus.READY,
        },
    )
    blocked = evaluate_hypothesis_eligibility(
        h002,
        {
            "LINEUP_GATE": DataGateStatus.READY,
            "FORMATION_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
        },
    )
    assert eligible.eligible is True
    assert eligible.status == PatternStatus.DISCOVERED
    assert blocked.eligible is False
    assert blocked.blocking_gates == ("FORMATION_GATE",)


def test_campaign_routing_is_cache_only_bounded_and_fail_closed() -> None:
    manifests = campaign_manifest(
        {
            "TEAM_GATE": DataGateStatus.READY,
            "MARKET_GATE": DataGateStatus.READY,
            "PLAYER_GATE": DataGateStatus.READY,
            "PLAYER_FORM_GATE": DataGateStatus.READY,
            "ABSENCE_GATE": DataGateStatus.BLOCKED_BY_TEMPORALITY,
        }
    )
    by_id = {str(item["campaign_id"]): item for item in manifests}
    assert by_id["11A"]["status"] == "ELIGIBLE"
    assert by_id["11B"]["status"] == "DATA_GATE_BLOCKED"
    assert by_id["11B"]["blocking_gates"] == ["ABSENCE_GATE"]
    assert by_id["11F"]["status"] == "ELIGIBLE"
    assert all(item["cache_only"] is True for item in manifests)
    assert all(item["provider_calls_allowed"] == 0 for item in manifests)
    assert all(item["odds_api_credits_allowed"] == 0 for item in manifests)


def test_every_campaign_keeps_production_social_demo_and_real_bets_locked() -> None:
    manifests = campaign_manifest({})
    assert all(
        item["production_status"] == "PRODUCTION_LOCKED"
        and item["real_bets"] is False
        and item["no_bet_default"] is True
        and item["social_publishing_enabled"] is False
        and item["demo_mode_enabled"] is False
        for item in manifests
    )


def test_promotion_requires_all_seventeen_conjunctive_gates() -> None:
    decision = evaluate_promotion(_all_promotion_evidence())
    assert len(PROMOTION_CRITERIA) == 17
    assert decision.promoted is True
    assert decision.status == PatternStatus.LIVE_SHADOW_CANDIDATE
    assert decision.failed_criteria == ()


def test_missing_market_timestamp_fails_closed_to_watchlist_not_candidate() -> None:
    evidence = _all_promotion_evidence()
    evidence["live_market_exact_observed_at"] = False
    decision = evaluate_promotion(evidence)
    assert decision.promoted is False
    assert decision.status == PatternStatus.PROSPECTIVE_WATCHLIST
    assert decision.failed_criteria == ("live_market_exact_observed_at",)


def test_leakage_or_failed_data_gate_is_rejected_not_watchlisted() -> None:
    evidence = _all_promotion_evidence()
    evidence["no_leakage"] = False
    decision = evaluate_promotion(evidence)
    assert decision.promoted is False
    assert decision.status == PatternStatus.REJECTED
    assert "no_leakage" in decision.failed_criteria


def test_failed_historical_science_is_rejected_not_watchlisted() -> None:
    evidence = _all_promotion_evidence()
    evidence["incremental_score_vs_market_positive"] = False
    decision = evaluate_promotion(evidence)
    assert decision.promoted is False
    assert decision.status == PatternStatus.REJECTED
    assert decision.failed_criteria == (
        "incremental_score_vs_market_positive",
    )


def test_public_ledger_has_all_seven_event_kinds_and_a_verified_hash_chain() -> None:
    assert {kind.value for kind in EvidenceEventKind} == {
        "HYPOTHESIS_REGISTERED",
        "DATA_GATE_EVALUATED",
        "PATTERN_REJECTED",
        "PATTERN_PROMOTED_TO_WATCHLIST",
        "PATTERN_PROMOTED_TO_SHADOW_CANDIDATE",
        "SHADOW_DECISION",
        "SETTLEMENT",
    }
    ledger = PublicEvidenceLedgerV2()
    first = ledger.append(
        event_kind=EvidenceEventKind.HYPOTHESIS_REGISTERED,
        code_revision="revision-1",
        dataset_hashes=("a" * 64,),
        status="REGISTERED",
        reason="preregistered",
        recorded_at=NOW,
    )
    second = ledger.append(
        event_kind=EvidenceEventKind.DATA_GATE_EVALUATED,
        code_revision="revision-1",
        dataset_hashes=("a" * 64,),
        status="BLOCKED_BY_TEMPORALITY",
        reason="cutoff absent",
        recorded_at=NOW,
    )
    assert first.sequence_no == 0
    assert first.previous_hash == "0" * 64
    assert second.sequence_no == 1
    assert second.previous_hash == first.record_hash
    assert ledger.audit() == {
        "status": "HASH_CHAIN_VERIFIED",
        "events": 2,
        "head_hash": second.record_hash,
    }


def test_public_ledger_audit_detects_tampering() -> None:
    ledger = PublicEvidenceLedgerV2()
    event = ledger.append(
        event_kind=EvidenceEventKind.PATTERN_REJECTED,
        code_revision="revision-1",
        dataset_hashes=("a" * 64,),
        status="REJECTED",
        reason="multiplicity",
        recorded_at=NOW,
    )
    ledger._events[0] = replace(event, reason="tampered")  # noqa: SLF001
    audit = ledger.audit()
    assert audit["status"] == "HASH_CHAIN_INVALID"
    assert audit["failed_sequence"] == 0


def test_public_ledger_write_is_append_only_and_replayable(
    tmp_path: Path,
) -> None:
    ledger = PublicEvidenceLedgerV2()
    ledger.append(
        event_kind=EvidenceEventKind.PATTERN_PROMOTED_TO_WATCHLIST,
        code_revision="revision-1",
        dataset_hashes=("a" * 64,),
        status="PROSPECTIVE_WATCHLIST",
        reason="historical evidence only",
        payload={"bets": 0, "stake_units": 0, "bankroll_units": 1_000},
        recorded_at=NOW,
    )
    path = tmp_path / "public-ledger-v2.jsonl"
    ledger.write_jsonl(path)
    rows = [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
    ]
    assert rows[0]["event_kind"] == "PATTERN_PROMOTED_TO_WATCHLIST"
    assert rows[0]["payload"] == {
        "bankroll_units": 1_000,
        "bets": 0,
        "stake_units": 0,
    }
    with pytest.raises(
        FileExistsError,
        match="PUBLIC_EVIDENCE_LEDGER_APPEND_ONLY",
    ):
        ledger.write_jsonl(path)


def test_empty_public_ledger_is_a_valid_genesis_chain() -> None:
    assert PublicEvidenceLedgerV2().audit() == {
        "status": "HASH_CHAIN_VERIFIED",
        "events": 0,
        "head_hash": "0" * 64,
    }
