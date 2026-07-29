from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin.hypothesis_intelligence.contracts import (
    HypothesisEventKind,
    HypothesisOrigin,
    HypothesisRecord,
    HypothesisStatus,
    ObservationStatus,
    canonical_sha256,
    validate_transition,
)
from robin.hypothesis_intelligence.ledger import HypothesisLedger
from robin.hypothesis_intelligence.prospective import (
    FREEZE_CODE_REVISION,
    FROZEN_AT,
    HypothesisSettlementRegistry,
    evaluate_fixture,
    freeze_top_three,
)
from robin.hypothesis_intelligence.registry import (
    J10_REGISTRY_SHA256,
    J10_RESULT_HASH,
    J10_TOP_IDS,
    owner_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "hypothesis-intelligence"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text("utf-8"))
    assert isinstance(value, dict)
    return value


def _record(
    hypothesis_id: str,
    *,
    competition: str,
    selection: str,
    odds_band: tuple[float, float],
    rule_hash: str,
) -> HypothesisRecord:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    conditions: tuple[dict[str, object], ...] = (
        {
            "feature": "competition",
            "operator": "EQ",
            "value": competition,
        },
        {
            "feature": f"odds_{selection.lower()}",
            "operator": "BETWEEN",
            "value": list(odds_band),
        },
        {
            "feature": "market_margin_1x2",
            "operator": "LE",
            "value": 0.06,
        },
    )
    return HypothesisRecord(
        hypothesis_id=hypothesis_id,
        hypothesis_version="1.0.0",
        origin=HypothesisOrigin.MACHINE_DISCOVERED,
        title=hypothesis_id,
        description="Signal exploratoire non validé.",
        mechanism="Association historique à répliquer sans modification.",
        family="1X2",
        competition_scope=(competition,),
        market=f"1X2_{selection}",
        selection=selection,
        conditions=conditions,
        price_contract={
            "odds_band": list(odds_band),
            "maximum_margin": 0.06,
            "exact_observed_at": False,
        },
        discovery_dataset="j10-registry",
        discovery_run_id="jalon10-cache-only-20260727",
        discovery_code_revision="423fb7e77ba52286b660956161f02f8a2c1be7f8",
        discovery_timestamp=now,
        historical_support=100,
        historical_profit=10.0,
        historical_roi=0.1,
        historical_confidence_interval=(0.0, 0.2),
        historical_p_value=0.01,
        historical_q_value=1.0,
        historical_walk_forward={"positive_folds": 3, "eligible_folds": 3},
        historical_drawdown=5.0,
        historical_cross_league_stability={"survived": False},
        team_concentration={"passed": True},
        time_concentration={"passed": True},
        negative_controls=("PERMUTED_OUTCOMES",),
        required_data_gates=("ODDS_GATE",),
        current_data_gates={"ODDS_GATE": "READY"},
        status=HypothesisStatus.EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING,
        status_reason="FDR_REJECTED",
        preregistered_at=None,
        preregistration_hash=None,
        prospective_start_at=None,
        minimum_prospective_support=80,
        promotion_locked=True,
        created_at=now,
        supersedes=None,
        rule_hash=rule_hash,
        canonical_fingerprint=canonical_sha256(
            {
                "competition": competition,
                "selection": selection,
                "odds_band": odds_band,
            }
        ),
    )


def _top_records() -> tuple[HypothesisRecord, ...]:
    by_hash = {identifier: rule_hash for rule_hash, identifier in J10_TOP_IDS.items()}
    return (
        _record(
            "J10-M001",
            competition="La Liga",
            selection="AWAY",
            odds_band=(2.0, 2.5),
            rule_hash=by_hash["J10-M001"],
        ),
        _record(
            "J10-M002",
            competition="Serie A",
            selection="DRAW",
            odds_band=(2.5, 3.25),
            rule_hash=by_hash["J10-M002"],
        ),
        _record(
            "J10-M003",
            competition="Serie A",
            selection="AWAY",
            odds_band=(1.6, 2.0),
            rule_hash=by_hash["J10-M003"],
        ),
    )


def _observation(
    contract_index: int = 0,
    **overrides: object,
):
    contract = freeze_top_three(_top_records())[contract_index]
    cutoff = datetime(2026, 8, 15, 17, 55, tzinfo=UTC)
    values: dict[str, object] = {
        "fixture_id": "fixture-2026-001",
        "competition": "La Liga" if contract_index == 0 else "Serie A",
        "market": "h2h",
        "selection": "AWAY" if contract_index != 1 else "DRAW",
        "cutoff_name": "NEAR_KICKOFF",
        "cutoff_at": cutoff,
        "kickoff_at": cutoff + timedelta(minutes=5),
        "observed_at": cutoff - timedelta(minutes=1),
        "odds": 2.2 if contract_index == 0 else 2.8,
        "margin": 0.05,
        "bookmaker_scope": ("CONFIGURED_EU_BOOKMAKERS",),
        "conditions_snapshot": {"fixture_status": "SCHEDULED"},
        "code_revision": FREEZE_CODE_REVISION,
    }
    values.update(overrides)
    return evaluate_fixture(contract, **values)  # type: ignore[arg-type]


def test_committed_registry_is_complete_bounded_unique_and_replayable() -> None:
    summary = _json(REPORTS / "registry-summary.json")
    counts = summary["counts"]
    source = summary["source"]
    assert isinstance(counts, dict)
    assert isinstance(source, dict)
    assert counts == {
        "canonical_rules": 700,
        "duplicates": 0,
        "families": 5,
        "machine_discovered": 700,
        "origins": {"MACHINE_DISCOVERED": 700},
        "owners": 8,
        "prospective_frozen": 3,
        "registry_sha256": J10_REGISTRY_SHA256,
        "result_hash": J10_RESULT_HASH,
        "statuses": {
            "DATA_GATE_BLOCKED": 167,
            "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING": 533,
        },
        "total": 700,
    }
    assert source["provider_calls"] == source["odds_api_credits"] == 0
    assert source["replay_identical"] is True

    index = _json(REPORTS / "registry-index.json")
    pages = index["pages"]
    assert isinstance(pages, list)
    assert index["total"] == 700
    assert index["page_size"] == 50
    assert len(pages) == 14
    assert sum(int(item["records"]) for item in pages) == 700
    assert all(str(item["artifact_path"]).startswith("j10-expert-pages/") for item in pages)
    assert not list((ROOT / "cockpit" / "public" / "hypotheses").glob("*.json"))


@pytest.mark.parametrize(
    (
        "hypothesis_id",
        "support",
        "profit",
        "roi",
        "confidence_interval",
        "positive_folds",
        "eligible_folds",
    ),
    (
        ("J10-M001", 261, 43.43, 0.1663984674329502, (0.0336086841, 0.3077026223), 4, 4),
        ("J10-M002", 363, 57.88, 0.1594490358126722, (0.0042719415, 0.3139338275), 4, 4),
        ("J10-M003", 241, 33.42, 0.1386721991701245, (0.0249139949, 0.2427021281), 3, 3),
    ),
)
def test_top_three_metrics_are_exact_and_never_claim_future_performance(
    hypothesis_id: str,
    support: int,
    profit: float,
    roi: float,
    confidence_interval: tuple[float, float],
    positive_folds: int,
    eligible_folds: int,
) -> None:
    report = _json(REPORTS / "top-machine-discoveries.json")
    report_items = report["items"]
    assert isinstance(report_items, list)
    item = next(value for value in report_items if value["hypothesis_id"] == hypothesis_id)
    assert item["origin"] == "MACHINE_DISCOVERED"
    assert item["status"] == "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
    assert item["historical_support"] == support
    assert item["historical_profit_units"] == pytest.approx(profit)
    assert item["historical_roi"] == pytest.approx(roi)
    assert item["historical_confidence_interval"] == pytest.approx(confidence_interval)
    assert item["historical_q_value"] == 1.0
    assert item["historical_walk_forward"]["positive_folds"] == positive_folds
    assert item["historical_walk_forward"]["eligible_folds"] == eligible_folds
    assert item["warning"] == (
        "Ce résultat historique ne constitue pas une prévision de performance future."
    )
    assert len(item["rule_hash"]) == len(item["payload_hash"]) == 64


def test_owner_hypotheses_are_explicitly_separate_from_machine_discoveries() -> None:
    owners = owner_registry()
    assert tuple(item.hypothesis_id for item in owners) == tuple(
        f"H11-{index:03d}" for index in range(1, 9)
    )
    assert {item.origin for item in owners} == {HypothesisOrigin.OWNER_PROPOSED}
    assert {item.status for item in owners} == {HypothesisStatus.DATA_GATE_BLOCKED}
    assert all(item.required_data_gates for item in owners)
    assert all(item.historical_roi is None for item in owners)


def test_top_three_freeze_is_stable_immutable_and_promotion_locked() -> None:
    first = freeze_top_three(_top_records())
    second = freeze_top_three(_top_records())
    assert first == second
    assert tuple(item.hypothesis_id for item in first) == (
        "J10-M001",
        "J10-M002",
        "J10-M003",
    )
    assert all(item.frozen_at == FROZEN_AT for item in first)
    assert all(item.code_revision == FREEZE_CODE_REVISION for item in first)
    assert all(item.source_registry_hash == J10_REGISTRY_SHA256 for item in first)
    assert all(item.primary_price.cutoff_name == "NEAR_KICKOFF" for item in first)
    assert all(item.secondary_price.cutoff_name == "H-2" for item in first)
    assert all(item.minimum_descriptive_support == 30 for item in first)
    assert all(item.minimum_exploratory_support == 80 for item in first)
    assert all(item.minimum_seasons == 1 and item.promotion_locked for item in first)
    assert [item.contract_hash for item in first] == [item.contract_hash for item in second]
    with pytest.raises(AttributeError):
        first[0].promotion_locked = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "status", "reason"),
    (
        ({}, ObservationStatus.ELIGIBLE_FROZEN, "ALL_FROZEN_CONDITIONS_SATISFIED"),
        (
            {"competition": "Serie A"},
            ObservationStatus.NOT_ELIGIBLE,
            "COMPETITION_MISMATCH",
        ),
        (
            {"selection": "HOME"},
            ObservationStatus.NOT_ELIGIBLE,
            "MARKET_OR_SELECTION_MISMATCH",
        ),
        (
            {"odds": 1.99},
            ObservationStatus.NOT_ELIGIBLE,
            "ODDS_OUTSIDE_FROZEN_BAND",
        ),
        (
            {"margin": 0.061},
            ObservationStatus.NOT_ELIGIBLE,
            "MARGIN_ABOVE_FROZEN_MAXIMUM",
        ),
        (
            {"odds": None},
            ObservationStatus.REJECTED_MISSING_PRICE,
            "PRICE_OR_MARGIN_MISSING",
        ),
        (
            {
                "observed_at": datetime(2026, 8, 15, 17, 56, tzinfo=UTC),
            },
            ObservationStatus.REJECTED_LATE,
            "OBSERVED_AFTER_CUTOFF",
        ),
        (
            {"conditions_snapshot": {"fixture_status": "POSTPONED"}},
            ObservationStatus.VOID,
            "FIXTURE_POSTPONED",
        ),
        (
            {"cutoff_name": "H-1"},
            ObservationStatus.NOT_ELIGIBLE,
            "CUTOFF_NAME_MISMATCH",
        ),
    ),
)
def test_eligibility_fails_closed(
    overrides: dict[str, object],
    status: ObservationStatus,
    reason: str,
) -> None:
    observation = _observation(**overrides)
    assert observation.status is status
    assert observation.status_reason == reason


def test_settlement_is_shadow_only_idempotent_and_versioned_on_correction() -> None:
    registry = HypothesisSettlementRegistry()
    settled_at = datetime(2026, 8, 15, 21, tzinfo=UTC)

    win, inserted = registry.settle(
        _observation(),
        result_status="FINAL",
        home_goals=0,
        away_goals=1,
        result_version=1,
        settled_at=settled_at,
    )
    assert inserted is True
    assert win.profit_units == pytest.approx(1.2)
    assert win.metrics == {
        "shadow_units": 1,
        "prospective_only": 1,
        "historical_metrics_merged": 0,
    }
    replay, inserted = registry.settle(
        _observation(),
        result_status="FINAL",
        home_goals=0,
        away_goals=1,
        result_version=1,
        settled_at=settled_at,
    )
    assert inserted is False
    assert replay == win

    corrected, inserted = registry.settle(
        _observation(),
        result_status="FINAL",
        home_goals=2,
        away_goals=0,
        result_version=2,
        settled_at=settled_at + timedelta(minutes=5),
    )
    assert inserted is True
    assert corrected.profit_units == -1
    assert corrected.supersedes == win.settlement_id

    draw, _ = HypothesisSettlementRegistry().settle(
        _observation(1),
        result_status="FINAL",
        home_goals=1,
        away_goals=1,
        result_version=1,
        settled_at=settled_at,
    )
    assert draw.profit_units == pytest.approx(1.8)

    void, _ = HypothesisSettlementRegistry().settle(
        _observation(),
        result_status="VOID",
        home_goals=None,
        away_goals=None,
        result_version=1,
        settled_at=settled_at,
    )
    assert void.profit_units == 0


def test_ledger_is_hash_chained_and_automatic_validation_is_forbidden() -> None:
    ledger = HypothesisLedger()
    first = ledger.append(
        kind=HypothesisEventKind.HYPOTHESIS_IMPORTED,
        recorded_at=FROZEN_AT,
        code_revision=FREEZE_CODE_REVISION,
        hypothesis_id="J10-M001",
        evidence_hashes=("a" * 64,),
        details={"origin": "MACHINE_DISCOVERED"},
    )
    second = ledger.append(
        kind=HypothesisEventKind.HYPOTHESIS_PROSPECTIVE_FROZEN,
        recorded_at=FROZEN_AT,
        code_revision=FREEZE_CODE_REVISION,
        hypothesis_id="J10-M001",
        evidence_hashes=("b" * 64,),
        details={"promotion_locked": True},
    )
    assert second.previous_hash == first.event_hash
    assert ledger.audit() == {
        "events": 2,
        "head_hash": second.event_hash,
        "valid": True,
        "automatic_validation_events": 0,
    }
    with pytest.raises(ValueError, match="AUTOMATIC_HYPOTHESIS_VALIDATION_FORBIDDEN"):
        ledger.append(
            kind=HypothesisEventKind.HYPOTHESIS_VALIDATED,
            recorded_at=FROZEN_AT,
            code_revision=FREEZE_CODE_REVISION,
            hypothesis_id="J10-M001",
            evidence_hashes=("c" * 64,),
            details={},
        )
    with pytest.raises(ValueError, match="AUTOMATIC_HYPOTHESIS_VALIDATION_FORBIDDEN"):
        validate_transition(
            HypothesisStatus.SHADOW_ELIGIBLE,
            HypothesisStatus.VALIDATED,
        )
    validate_transition(
        HypothesisStatus.SHADOW_ELIGIBLE,
        HypothesisStatus.VALIDATED,
        automatic=False,
    )


def test_cockpit_exposes_real_state_and_no_synthetic_observations() -> None:
    cockpit = _json(ROOT / "cockpit" / "app" / "cockpit-data.json")
    intelligence = cockpit["hypothesisIntelligence"]
    assert isinstance(intelligence, dict)
    assert intelligence["liveState"] == {
        "fixturesVerified": 116,
        "hypothesisObservations": 0,
        "realPredictions": 0,
        "realSettlements": 0,
        "realTrainingRuns": 0,
    }
    assert intelligence["registry"]["total"] == 700
    assert len(intelligence["machineDiscoveries"]) == 3
    assert len(intelligence["ownerHypotheses"]) == 8
    assert all(
        item["settledObservations"] == item["eligibleMatches"] == 0
        for item in intelligence["prospectiveObservations"]
    )
    security = intelligence["security"]
    assert security == {
        "demoModeEnabled": False,
        "noBetDefault": True,
        "oddsApiCredits": 0,
        "p3P4Paused": True,
        "productionStatus": "PRODUCTION_LOCKED",
        "promotionLocked": True,
        "providerCalls": 0,
        "r2Deletions": 0,
        "realBets": False,
        "socialPublishingEnabled": False,
        "storagePaused": True,
    }
