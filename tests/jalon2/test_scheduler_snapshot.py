from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from robin.domain.enums import MarketScope, MarketType, QuotePhase, Selection
from robin.domain.odds import BookmakerQuoteContract, MarketKey, OddsSnapshot
from robin.ingestion.scheduler import (
    WINDOW_TARGETS,
    CollectionWindow,
    FixtureCandidate,
    due_window,
    plan_collection,
)
from robin.ingestion.snapshot_store import JsonlSnapshotStore

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(("window", "target"), list(WINDOW_TARGETS.items()))
def test_chaque_fenetre_recommandee_est_planifiable(
    window: CollectionWindow,
    target: timedelta,
) -> None:
    assert due_window(NOW + target, now=NOW) == window


def test_hors_fenetre_match_passe_et_timestamp_naif_sont_refuses() -> None:
    assert due_window(NOW + timedelta(hours=5), now=NOW) is None
    assert due_window(NOW - timedelta(minutes=1), now=NOW) is None
    with pytest.raises(ValueError, match="fuseau"):
        due_window(datetime(2026, 8, 2), now=NOW)


def test_plan_priorise_proximite_dedoublonne_et_respecte_quota() -> None:
    fixtures = (
        FixtureCandidate(provider_fixture_id="far", kickoff_at=NOW + timedelta(days=1)),
        FixtureCandidate(provider_fixture_id="near", kickoff_at=NOW + timedelta(hours=1)),
    )
    collected = {("near", CollectionWindow.H1)}
    tasks = plan_collection(
        fixtures,
        now=NOW,
        collected=collected,
        quota_remaining=2,
    )
    assert [task.provider_fixture_id for task in tasks] == ["far"]
    assert plan_collection(
        fixtures,
        now=NOW,
        collected=set(),
        quota_remaining=0,
    ) == ()


def sample_snapshot(observed: datetime) -> OddsSnapshot:
    market = MarketKey(
        fixture_id="fixture-1",
        market_type=MarketType.ONE_X_TWO,
        market_scope=MarketScope.MATCH,
        selection=Selection.HOME,
    )
    quote = BookmakerQuoteContract(
        market=market,
        bookmaker_id="bookmaker-1",
        odds_decimal=Decimal("2.1"),
        observed_at=observed,
        phase=QuotePhase.INTERMEDIATE,
        source_observation_id="raw-1",
        bookmaker_rule_version="1",
    )
    return OddsSnapshot(
        provider="fixture",
        provider_fixture_id="provider-1",
        fixture_id="fixture-1",
        fixture_kickoff_at=NOW + timedelta(days=1),
        fixture_kickoff_local="2026-08-02T14:00:00+02:00",
        observed_at=observed,
        ingested_at=observed,
        phase=QuotePhase.INTERMEDIATE,
        quotes=(quote,),
    )


def test_store_snapshot_est_append_only_et_idempotent(tmp_path: Path) -> None:
    store = JsonlSnapshotStore(tmp_path)
    first = sample_snapshot(NOW)
    later = sample_snapshot(NOW + timedelta(minutes=10))
    assert store.append(first)
    assert not store.append(first)
    assert store.append(later)
    assert len(store.read_all()) == 2
    assert first.snapshot_id != later.snapshot_id
