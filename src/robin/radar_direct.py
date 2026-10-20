"""Local contemporaneous Pinnacle reference for paper price observations."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from robin import clv
from robin.domain.enums import MarketScope, MarketType
from robin.domain.odds import OddsSnapshot

Row = dict[str, Any]


@dataclass(frozen=True)
class Reference:
    observed_at: datetime
    ingested_at: datetime
    kickoff: datetime
    prices: dict[str, float]


def enrich(rows: list[Row], snapshots: Iterable[OddsSnapshot]) -> list[Row]:
    """Nearest complete pre-kickoff snapshot within ±15m, earlier on ties.

    Snapshot observation and ingestion must precede kickoff. Positive clock gaps
    (up to 15m after FR) are exported, never replaced by a future closing fair.
    Contradictory fixture metadata or Pinnacle prices quarantine the fixture.
    """
    references: dict[str, dict[datetime, Reference]] = defaultdict(dict)
    kickoffs: dict[str, set[datetime]] = defaultdict(set)
    prices_seen: dict[tuple[str, datetime, str], float] = {}
    conflicts: set[str] = set()
    for s in snapshots:
        if s.observed_at >= s.fixture_kickoff_at or s.ingested_at >= s.fixture_kickoff_at:
            continue
        fixture = s.fixture_id
        kickoffs[fixture].add(s.fixture_kickoff_at)
        prices: dict[str, float] = {}
        for q in s.quotes:
            m = q.market
            if (
                clv.BOOKS.get(q.bookmaker_id) != "pinnacle"
                or m.fixture_id != fixture
                or m.market_type != MarketType.ONE_X_TWO
                or m.market_scope != MarketScope.MATCH
                or m.period != "FULL_TIME"
                or m.selection not in clv.ISSUES
            ):
                continue
            issue, price = clv.ISSUES[m.selection], float(q.odds_decimal)
            if not math.isfinite(price) or price <= 1:
                conflicts.add(fixture)
                continue
            key = fixture, s.observed_at, issue
            if key in prices_seen and prices_seen[key] != price:
                conflicts.add(fixture)
            prices_seen[key] = price
            prices[issue] = price
        # Do not manufacture a complete snapshot by combining partial reports.
        if len(prices) == 3:
            existing = references[fixture].get(s.observed_at)
            ingested = min(existing.ingested_at, s.ingested_at) if existing else s.ingested_at
            references[fixture][s.observed_at] = Reference(
                s.observed_at, ingested, s.fixture_kickoff_at, prices
            )
    conflicts.update(fixture for fixture, values in kickoffs.items() if len(values) != 1)
    result = []
    for row in rows:
        r = {
            **row,
            "ev_direct": None,
            "p_fair_direct": None,
            "pin_direct_at": None,
            "pin_direct_gap_minutes": None,
            "direct_status": "MISSING_PINNACLE_15M",
        }
        fixture = r["match"]
        expected_kickoff = None
        if r.get("close_at") and r.get("close_gap_minutes") is not None:
            expected_kickoff = datetime.fromisoformat(r["close_at"]) + timedelta(
                minutes=float(r["close_gap_minutes"])
            )
        if fixture in conflicts or (
            expected_kickoff is not None
            and kickoffs.get(fixture)
            and expected_kickoff not in kickoffs[fixture]
        ):
            r["direct_status"] = "CONFLICTING_PINNACLE"
        elif not r.get("observed_at") or not r.get("price"):
            r["direct_status"] = "MISSING_FR_PRICE"
        else:
            observed = datetime.fromisoformat(r["observed_at"])
            candidates = [
                ref
                for ref in references.get(fixture, {}).values()
                if observed < ref.kickoff
                and abs(ref.observed_at - observed) <= timedelta(minutes=15)
                and ref.ingested_at <= observed + timedelta(minutes=15)
            ]
            ref = min(
                candidates,
                key=lambda ref: (abs(ref.observed_at - observed), ref.observed_at),
                default=None,
            )
            if ref is not None:
                p = (1 / ref.prices[r["issue"]]) / sum(1 / v for v in ref.prices.values())
                r.update(
                    ev_direct=float(r["price"]) * p - 1,
                    p_fair_direct=p,
                    pin_direct_at=ref.observed_at.isoformat(),
                    pin_direct_gap_minutes=(ref.observed_at - observed).total_seconds() / 60,
                    direct_status="OK",
                )
        result.append(r)
    return result
