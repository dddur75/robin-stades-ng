"""CLV 2026-27 papier : lecture locale uniquement, aucun fournisseur ni stockage distant."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from scipy.stats import t  # type: ignore[import-untyped]

from robin.domain.enums import MarketScope, MarketType, QuotePhase, Selection
from robin.domain.odds import OddsSnapshot, stable_internal_id
from robin.domain.temporal import require_utc
from robin.providers.the_odds_api import parse_odds_snapshot

FR_BOOKS = ("betclic_fr", "winamax_fr", "unibet_fr", "pmu_fr", "netbet_fr")
BOOKS = {stable_internal_id("bookmaker", "the-odds-api", b): b
         for b in (*FR_BOOKS, "pinnacle")}
ISSUES = {Selection.HOME: "1", Selection.DRAW: "N", Selection.AWAY: "2"}
Row = dict[str, Any]
DETAIL_FIELDS = ("match", "issue", "book", "horizon", "price", "clv", "late",
                 "p_fair_close", "observed_at", "close_at", "status")
SUMMARY_FIELDS = ("book", "band", "horizon", "n", "mean_clv", "ci95_low", "ci95_high")


def probability_band(p: float) -> str:
    return "<30%" if p < .3 else "30-45%" if p < .45 else "45-60%" if p < .6 else ">=60%"


def calculate(snapshots: list[OddsSnapshot], day: date, *, as_of: datetime) -> list[Row]:
    """Nearest horizons (earlier on ties); closing is the last complete pre-kickoff 1N2."""
    as_of = require_utc(as_of, "as_of")
    fixtures: dict[str, list[OddsSnapshot]] = defaultdict(list)
    for s in snapshots:
        if s.observed_at >= s.fixture_kickoff_at or s.ingested_at >= s.fixture_kickoff_at:
            continue
        if s.fixture_kickoff_at.date() == day:
            fixtures[s.fixture_id].append(s)
    result: list[Row] = []
    for fixture, values in sorted(fixtures.items()):
        kickoffs = {s.fixture_kickoff_at for s in values}
        if len(kickoffs) != 1:
            raise ValueError("conflicting fixture kickoff")
        kickoff = values[0].fixture_kickoff_at
        if kickoff > as_of:
            continue
        prices: dict[str, dict[datetime, dict[str, float]]] = defaultdict(dict)
        for s in values:
            for q in s.quotes:
                m = q.market
                if (m.fixture_id != fixture or m.market_type != MarketType.ONE_X_TWO
                        or m.market_scope != MarketScope.MATCH or m.period != "FULL_TIME"
                        or m.selection not in ISSUES):
                    continue
                book = BOOKS.get(q.bookmaker_id, q.bookmaker_id)
                if book not in (*FR_BOOKS, "pinnacle"):
                    continue
                quote_price = float(q.odds_decimal)
                if not math.isfinite(quote_price):
                    raise ValueError("non-finite price")
                market = prices[book].setdefault(s.observed_at, {})
                issue = ISSUES[m.selection]
                if issue in market and market[issue] != quote_price:
                    raise ValueError("conflicting duplicate price")
                market[issue] = quote_price
        pin = {at: p for at, p in prices.get("pinnacle", {}).items() if len(p) == 3}
        close = max(pin) if pin else None
        fair = {i: (1 / p) / sum(1 / v for v in pin[close].values())
                for i, p in pin[close].items()} if close else {}

        def nearest(times: Iterable[datetime], hours: int) -> datetime | None:
            target = kickoff - timedelta(hours=hours)
            return min(times, key=lambda at: (abs(at - target), at), default=None)

        p2 = nearest(pin, 2)
        for book in sorted(set(prices) & set(FR_BOOKS)):
            for issue in ("1", "N", "2"):
                quotes = {at: p[issue] for at, p in prices[book].items() if issue in p}
                openings = {at: p[issue] for at, p in prices.get("pinnacle", {}).items()
                            if issue in p}
                p48 = nearest(openings, 48)
                for horizon in (48, 24, 2):
                    at = nearest(quotes, horizon)
                    price = quotes[at] if at else None
                    clv = price * fair[issue] - 1 if price and fair else None
                    late = None
                    if price and p48 and p2:
                        p_fair_2 = (1 / pin[p2][issue]) / sum(1 / v for v in pin[p2].values())
                        late = (horizon == 2
                                and abs(pin[p2][issue] / openings[p48] - 1) >= .05 - 1e-12
                                and price * p_fair_2 - 1 >= .02 - 1e-12)
                    result.append(dict(zip(DETAIL_FIELDS, (
                        fixture, issue, book, horizon, price, clv, late, fair.get(issue),
                        at.isoformat() if at else None, close.isoformat() if close else None,
                        "OK" if clv is not None else "MISSING_PRICE_OR_CLOSE",
                    ), strict=True)))
    return result


def summarize(rows: list[Row]) -> list[Row]:
    groups: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    for row in rows:
        if row["clv"] is not None:
            groups[row["book"], probability_band(row["p_fair_close"]), row["horizon"]].append(
                row["clv"])
    result = []
    for (book, band, horizon), values in sorted(groups.items()):
        n, avg = len(values), mean(values)
        half = float(t.ppf(.975, n - 1)) * stdev(values) / math.sqrt(n) if n > 1 else None
        result.append(dict(zip(SUMMARY_FIELDS, (book, band, horizon, n, avg,
                      avg - half if half is not None else None,
                      avg + half if half is not None else None), strict=True)))
    return result


def load(paths: list[Path]) -> list[OddsSnapshot]:
    """Accept JsonlSnapshotStore or normalized recurring_real_data JSON reports."""
    snapshots: list[OddsSnapshot] = []
    for path in paths:
        if path.suffix == ".jsonl":
            snapshots.extend(OddsSnapshot.model_validate_json(line)
                             for line in path.read_text("utf-8").splitlines() if line.strip())
            continue
        events: dict[tuple[str, str], Row] = {}
        for r in json.loads(path.read_text("utf-8"))["rows"]:
            if r["market_key"] != "h2h" or r.get("point") is not None:
                continue
            observed = require_utc(datetime.fromisoformat(r["capture_time_utc"]), "capture")
            source = require_utc(datetime.fromisoformat(r["source_timestamp_utc"]), "source")
            kickoff = require_utc(datetime.fromisoformat(r["kickoff_utc"]), "kickoff")
            if source > observed or source >= kickoff or observed >= kickoff:
                continue
            event = events.setdefault((r["event_id"], observed.isoformat()), {
                "id": r["event_id"], "home_team": r["home_team"], "away_team": r["away_team"],
                "commence_time": r["kickoff_utc"], "bookmakers": {},
            })
            if any(event[k] != r[v] for k, v in (
                ("home_team", "home_team"), ("away_team", "away_team"),
                ("commence_time", "kickoff_utc"),
            )):
                raise ValueError("conflicting fixture metadata")
            outcomes = event["bookmakers"].setdefault(r["bookmaker_key"], [])
            outcome = {"name": r["outcome"], "price": r["price"]}
            if outcome not in outcomes:
                outcomes.append(outcome)
        for (_, observed_text), event in events.items():
            event["bookmakers"] = [{"key": book, "markets": [{"key": "h2h", "outcomes": o}]}
                                   for book, o in event["bookmakers"].items()]
            observed = datetime.fromisoformat(observed_text)
            snapshots.append(parse_odds_snapshot(
                event, observed_at=observed, ingested_at=observed,
                raw_observation_id="local-normalized-report", phase=QuotePhase.INTERMEDIATE))
    return snapshots


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="jour UTC des matchs")
    parser.add_argument("--output", type=Path, required=True, help="répertoire local des CSV")
    parser.add_argument("sources", nargs="+", type=Path, help="historiques JSONL ou rapports JSON locaux")
    args = parser.parse_args(argv)
    rows = calculate(load(args.sources), args.date, as_of=datetime.now(UTC))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, fields, data in (("clv", DETAIL_FIELDS, rows),
                               ("summary", SUMMARY_FIELDS, summarize(rows))):
        with (args.output / f"{args.date}-{name}.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: "'" + v if isinstance(v, str)
                              and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                              for k, v in row.items()} for row in data)


if __name__ == "__main__":
    main()
