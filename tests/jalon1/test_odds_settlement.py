from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from robin.betting.settlement import MatchResult, settle_market
from robin.domain.enums import (
    FixtureStatus,
    MarketScope,
    MarketType,
    QuotePhase,
    Selection,
    SettlementOutcome,
)
from robin.domain.odds import BookmakerQuoteContract, MarketKey, OddsSnapshot
from robin.providers.mock_odds import MockOddsProvider


def market(market_type: MarketType, selection: Selection, line: str | None = None) -> MarketKey:
    return MarketKey(
        fixture_id="fixture-1",
        market_type=market_type,
        market_scope=MarketScope.MATCH,
        selection=selection,
        line_value=Decimal(line) if line is not None else None,
        period="FULL_TIME",
        settlement_rule_version="1.0",
    )


@pytest.mark.parametrize(
    ("key", "score", "expected"),
    [
        (market(MarketType.ONE_X_TWO, Selection.HOME), (2, 1), SettlementOutcome.WON),
        (
            market(MarketType.DOUBLE_CHANCE, Selection.DRAW_OR_AWAY),
            (1, 1),
            SettlementOutcome.WON,
        ),
        (
            market(MarketType.TOTAL_GOALS, Selection.OVER, "2.5"),
            (2, 1),
            SettlementOutcome.WON,
        ),
        (
            market(MarketType.BOTH_TEAMS_TO_SCORE, Selection.NO),
            (2, 0),
            SettlementOutcome.WON,
        ),
    ],
)
def test_reglement_marches_initiaux(
    key: MarketKey,
    score: tuple[int, int],
    expected: SettlementOutcome,
) -> None:
    settlement = settle_market(
        key,
        MatchResult(
            status=FixtureStatus.FINISHED,
            home_goals=score[0],
            away_goals=score[1],
        ),
        odds_decimal=Decimal("1.90"),
    )
    assert settlement.outcome == expected
    assert settlement.profit_per_unit == Decimal("0.90")


def test_report_annulation_push_et_correction_versionnee() -> None:
    total = market(MarketType.TOTAL_GOALS, Selection.OVER, "3")
    void = settle_market(
        total,
        MatchResult(status=FixtureStatus.POSTPONED),
        odds_decimal=Decimal("2.0"),
    )
    push = settle_market(
        total,
        MatchResult(
            status=FixtureStatus.FINISHED,
            home_goals=2,
            away_goals=1,
            result_version=1,
        ),
        odds_decimal=Decimal("2.0"),
    )
    corrected = settle_market(
        total,
        MatchResult(
            status=FixtureStatus.FINISHED,
            home_goals=3,
            away_goals=1,
            result_version=2,
        ),
        odds_decimal=Decimal("2.0"),
    )

    assert void.outcome == SettlementOutcome.VOID
    assert push.outcome == SettlementOutcome.PUSH
    assert corrected.outcome == SettlementOutcome.WON
    assert corrected.result_version == 2


def test_opportunite_est_unique_et_quotes_bookmaker_restent_distinctes() -> None:
    observed = datetime(2026, 8, 1, 10, tzinfo=UTC)
    key = market(MarketType.BOTH_TEAMS_TO_SCORE, Selection.YES)
    quotes = tuple(
        BookmakerQuoteContract(
            market=key,
            bookmaker_id=bookmaker,
            odds_decimal=price,
            observed_at=observed,
            phase=QuotePhase.INTERMEDIATE,
            source_observation_id=f"raw-{bookmaker}",
            bookmaker_rule_version="2026.1",
        )
        for bookmaker, price in (
            ("pinnacle", Decimal("1.85")),
            ("winamax", Decimal("1.90")),
        )
    )
    snapshot = OddsSnapshot(
        provider="mock",
        provider_fixture_id="external-42",
        fixture_id="fixture-1",
        fixture_kickoff_at=observed + timedelta(days=1),
        fixture_kickoff_local="2026-08-02T12:00:00+02:00",
        observed_at=observed,
        ingested_at=observed + timedelta(seconds=1),
        phase=QuotePhase.INTERMEDIATE,
        quotes=quotes,
    )

    assert len({quote.market.business_key() for quote in quotes}) == 1
    assert len({quote.bookmaker_id for quote in quotes}) == 2
    assert MockOddsProvider([snapshot]).get_odds() == (snapshot,)


def test_snapshot_duplique_ou_horodatage_incoherent_est_refuse() -> None:
    observed = datetime(2026, 8, 1, 10, tzinfo=UTC)
    quote = BookmakerQuoteContract(
        market=market(MarketType.ONE_X_TWO, Selection.HOME),
        bookmaker_id="pinnacle",
        odds_decimal=Decimal("2.0"),
        observed_at=observed,
        phase=QuotePhase.OPENING,
        source_observation_id="raw-1",
        bookmaker_rule_version="1",
    )
    with pytest.raises(ValidationError):
        OddsSnapshot(
            provider="mock",
            provider_fixture_id="42",
            fixture_id="fixture-1",
            fixture_kickoff_at=observed + timedelta(days=1),
            fixture_kickoff_local="2026-08-02T12:00:00+02:00",
            observed_at=observed,
            ingested_at=observed - timedelta(seconds=1),
            phase=QuotePhase.OPENING,
            quotes=(quote, quote),
        )

