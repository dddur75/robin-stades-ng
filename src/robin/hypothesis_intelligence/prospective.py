"""Freeze, eligibility and idempotent shadow settlement."""

from __future__ import annotations

from datetime import UTC, datetime

from robin.hypothesis_intelligence.competition_identity import same_competition
from robin.hypothesis_intelligence.contracts import (
    HypothesisObservation,
    HypothesisRecord,
    HypothesisSettlement,
    ObservationStatus,
    PriceContract,
    ProspectiveHypothesisContract,
    canonical_sha256,
)
from robin.hypothesis_intelligence.registry import (
    J10_REGISTRY_SHA256,
    J10_TOP_IDS,
)

FROZEN_AT = datetime(2026, 7, 29, 13, 30, tzinfo=UTC)
FREEZE_CODE_REVISION = "0057e1caf57bd4d6084ab456f7ee386fff728c2c"


def _price(record: HypothesisRecord, cutoff: str) -> PriceContract:
    band = record.price_contract.get("odds_band")
    if not isinstance(band, list) or len(band) != 2:
        raise ValueError("TOP_MACHINE_ODDS_BAND_MISSING")
    maximum_margin = record.price_contract.get("maximum_margin")
    if not isinstance(maximum_margin, int | float):
        raise ValueError("TOP_MACHINE_MARGIN_MISSING")
    return PriceContract(
        provider="THE_ODDS_API",
        sport_key=(
            "soccer_spain_la_liga"
            if record.competition_scope == ("La Liga",)
            else "soccer_italy_serie_a"
        ),
        bookmaker_scope=("CONFIGURED_EU_BOOKMAKERS",),
        aggregation_method="MEDIAN_DECIMAL_ODDS_ACROSS_ELIGIBLE_BOOKMAKERS",
        de_vig_method="PROPORTIONAL_IMPLIED_PROBABILITY",
        market="h2h",
        selection=record.selection,
        minimum_odds=float(band[0]),
        maximum_odds=float(band[1]),
        maximum_margin=float(maximum_margin),
        cutoff_name=cutoff,
        cutoff_tolerance=("[-10m,+0m]" if cutoff == "NEAR_KICKOFF" else "[-15m,+15m]"),
        observed_at_rule="LATEST_OBSERVATION_NOT_AFTER_CUTOFF",
        kickoff_change_policy="RECOMPUTE_FUTURE_WINDOW_BEFORE_OPEN;NEVER_MUTATE_FROZEN_OBSERVATION",
        missing_price_policy="REJECTED_MISSING_PRICE",
        multiple_bookmaker_policy="FIXED_SCOPE_MEDIAN;NO_POST_RESULT_SELECTION",
        price_contract_version="prospective-price-v1",
    )


def freeze_top_three(
    records: tuple[HypothesisRecord, ...],
    *,
    frozen_at: datetime = FROZEN_AT,
    code_revision: str = FREEZE_CODE_REVISION,
) -> tuple[ProspectiveHypothesisContract, ...]:
    selected = {item.hypothesis_id: item for item in records}
    expected = tuple(J10_TOP_IDS.values())
    if any(identifier not in selected for identifier in expected):
        raise ValueError("J10_TOP_THREE_NOT_AVAILABLE")
    contracts: list[ProspectiveHypothesisContract] = []
    for identifier in expected:
        record = selected[identifier]
        contracts.append(
            ProspectiveHypothesisContract(
                contract_id=f"{identifier}:1.0.0",
                hypothesis_id=identifier,
                hypothesis_version="1.0.0",
                frozen_at=frozen_at,
                code_revision=code_revision,
                source_rule_hash=record.rule_hash,
                source_registry_hash=J10_REGISTRY_SHA256,
                primary_price=_price(record, "NEAR_KICKOFF"),
                secondary_price=_price(record, "H-2"),
            )
        )
    return tuple(contracts)


def evaluate_fixture(
    contract: ProspectiveHypothesisContract,
    *,
    fixture_id: str,
    competition: str,
    market: str,
    selection: str,
    cutoff_name: str,
    cutoff_at: datetime,
    kickoff_at: datetime,
    observed_at: datetime,
    odds: float | None,
    margin: float | None,
    bookmaker_scope: tuple[str, ...],
    conditions_snapshot: dict[str, object],
    code_revision: str,
) -> HypothesisObservation:
    cutoff_matches_primary = cutoff_name == contract.primary_price.cutoff_name
    cutoff_matches_secondary = cutoff_name == contract.secondary_price.cutoff_name
    price = contract.primary_price if cutoff_matches_primary else contract.secondary_price
    status = ObservationStatus.ELIGIBLE_FROZEN
    reason = "ALL_FROZEN_CONDITIONS_SATISFIED"
    fixture_status = str(conditions_snapshot.get("fixture_status", "")).upper()
    if fixture_status in {"POSTPONED", "CANCELLED", "ABANDONED"}:
        status, reason = ObservationStatus.VOID, f"FIXTURE_{fixture_status}"
    elif not cutoff_matches_primary and not cutoff_matches_secondary:
        status, reason = ObservationStatus.NOT_ELIGIBLE, "CUTOFF_NAME_MISMATCH"
    elif observed_at > cutoff_at:
        status, reason = ObservationStatus.REJECTED_LATE, "OBSERVED_AFTER_CUTOFF"
    elif odds is None or margin is None:
        status, reason = (
            ObservationStatus.REJECTED_MISSING_PRICE,
            "PRICE_OR_MARGIN_MISSING",
        )
    elif market != price.market or selection != price.selection:
        status, reason = ObservationStatus.NOT_ELIGIBLE, "MARKET_OR_SELECTION_MISMATCH"
    else:
        expected_competition = (
            "api-football:140" if "spain" in price.sport_key else "api-football:135"
        )
        try:
            competition_matches = same_competition(
                competition,
                expected_competition,
            )
        except ValueError:
            status, reason = (
                ObservationStatus.NOT_ELIGIBLE,
                "UNKNOWN_COMPETITION_IDENTITY",
            )
            competition_matches = True
        if not competition_matches:
            status, reason = (
                ObservationStatus.NOT_ELIGIBLE,
                "COMPETITION_MISMATCH",
            )
    if (
        status is ObservationStatus.ELIGIBLE_FROZEN
        and odds is not None
        and not price.minimum_odds <= odds <= price.maximum_odds
    ):
        status, reason = ObservationStatus.NOT_ELIGIBLE, "ODDS_OUTSIDE_FROZEN_BAND"
    elif (
        status is ObservationStatus.ELIGIBLE_FROZEN
        and margin is not None
        and margin > price.maximum_margin
    ):
        status, reason = ObservationStatus.NOT_ELIGIBLE, "MARGIN_ABOVE_FROZEN_MAXIMUM"
    identity = canonical_sha256(
        {
            "contract_id": contract.contract_id,
            "fixture_id": fixture_id,
            "cutoff_name": cutoff_name,
            "cutoff_at": cutoff_at.isoformat(),
        }
    )
    return HypothesisObservation(
        hypothesis_observation_id=f"hypothesis-observation-{identity}",
        hypothesis_id=contract.hypothesis_id,
        hypothesis_version=contract.hypothesis_version,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        selection=selection,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        kickoff_at=kickoff_at,
        observed_at=observed_at,
        odds=odds,
        margin=margin,
        bookmaker_scope=bookmaker_scope,
        conditions_snapshot=conditions_snapshot,
        status=status,
        status_reason=reason,
        code_revision=code_revision,
    )


class HypothesisSettlementRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, list[HypothesisSettlement]] = {}

    @property
    def settlements(self) -> tuple[HypothesisSettlement, ...]:
        return tuple(settlement for versions in self._versions.values() for settlement in versions)

    def settle(
        self,
        observation: HypothesisObservation,
        *,
        result_status: str,
        home_goals: int | None,
        away_goals: int | None,
        result_version: int,
        settled_at: datetime,
    ) -> tuple[HypothesisSettlement, bool]:
        if observation.status is not ObservationStatus.ELIGIBLE_FROZEN:
            raise ValueError("HYPOTHESIS_SETTLEMENT_REQUIRES_FROZEN_OBSERVATION")
        result_hash = canonical_sha256(
            {
                "fixture_id": observation.fixture_id,
                "result_status": result_status,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "result_version": result_version,
            }
        )
        versions = self._versions.setdefault(observation.hypothesis_observation_id, [])
        if versions and versions[-1].result_hash == result_hash:
            return versions[-1], False
        if versions and result_version <= versions[-1].result_version:
            raise ValueError("HYPOTHESIS_RESULT_VERSION_MUST_INCREASE")
        if result_status in {"VOID", "CANCELLED", "ABANDONED"}:
            profit = 0.0
        else:
            if home_goals is None or away_goals is None or observation.odds is None:
                raise ValueError("HYPOTHESIS_FINAL_SCORE_REQUIRED")
            won = (
                (observation.selection == "HOME" and home_goals > away_goals)
                or (observation.selection == "AWAY" and away_goals > home_goals)
                or (observation.selection == "DRAW" and home_goals == away_goals)
            )
            profit = observation.odds - 1 if won else -1.0
        settlement_id = "hypothesis-settlement-" + canonical_sha256(
            {
                "observation": observation.payload_hash,
                "result": result_hash,
            }
        )
        settlement = HypothesisSettlement(
            settlement_id=settlement_id,
            observation_id=observation.hypothesis_observation_id,
            fixture_id=observation.fixture_id,
            result_version=result_version,
            result_status=result_status,
            home_goals=home_goals,
            away_goals=away_goals,
            profit_units=round(profit, 6),
            settled_at=settled_at,
            result_hash=result_hash,
            supersedes=versions[-1].settlement_id if versions else None,
            metrics={
                "shadow_units": 1,
                "prospective_only": 1,
                "historical_metrics_merged": 0,
            },
        )
        versions.append(settlement)
        return settlement, True


__all__ = [
    "FREEZE_CODE_REVISION",
    "FROZEN_AT",
    "HypothesisSettlementRegistry",
    "evaluate_fixture",
    "freeze_top_three",
]
