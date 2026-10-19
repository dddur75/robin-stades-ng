import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin import clv
from robin.domain.enums import QuotePhase
from robin.providers.the_odds_api import parse_odds_snapshot

KICKOFF = datetime(2026, 10, 18, 20, tzinfo=UTC)
DAY = KICKOFF.date()


def snapshot(hours: float, pin: tuple[float, ...], fr: float = 2.2):
    event = {
        "id": "synthetic", "home_team": "Home", "away_team": "Away",
        "commence_time": KICKOFF.isoformat(),
        "bookmakers": [{"key": book, "markets": [{"key": "h2h", "outcomes": [
            {"name": name, "price": price}
            for name, price in zip(("Home", "Draw", "Away"), prices)
        ]}]} for book, prices in (("pinnacle", pin), ("betclic_fr", (fr, 4, 4)))],
    }
    observed = KICKOFF - timedelta(hours=hours)
    return parse_odds_snapshot(event, observed_at=observed, ingested_at=observed,
                               raw_observation_id="synthetic", phase=QuotePhase.INTERMEDIATE)


def history():
    return [snapshot(48, (2.5, 4, 4)), snapshot(24, (2.2, 4, 4)),
            snapshot(2, (2, 4, 4)), snapshot(.1, (1.8, 3.6, 3.6))]


def test_known_clv_lag_and_summary():
    rows = clv.calculate(history(), DAY, as_of=KICKOFF)
    home = [r for r in rows if r["book"] == "betclic_fr" and r["issue"] == "1"]
    assert len(home) == 3
    assert [r["clv"] for r in home] == pytest.approx([.1] * 3)
    assert [r["late"] for r in home] == [False, False, True]
    assert all(r["p_fair_close"] == .5 for r in home)
    doubled = home + [{**r, "clv": .3} for r in home]
    summary = clv.summarize(doubled)
    assert len(summary) == 3
    assert all(r["n"] == 2 and r["mean_clv"] == pytest.approx(.2) for r in summary)
    assert summary[0]["ci95_low"] == pytest.approx(.2 - 12.706204736 * .1)
    assert clv.summarize(home)[0]["ci95_low"] is None


def test_post_kickoff_and_late_ingestion_never_change_results():
    expected = clv.calculate(history(), DAY, as_of=KICKOFF)
    poisoned = history() + [snapshot(0, (1.01, 90, 90), 90), snapshot(-1, (90, 90, 1.01), 90)]
    late = snapshot(1, (90, 90, 1.01), 90).model_copy(
        update={"ingested_at": KICKOFF + timedelta(seconds=1)})
    assert clv.calculate(poisoned + [late], DAY, as_of=KICKOFF) == expected
    assert clv.calculate(history(), DAY, as_of=KICKOFF - timedelta(seconds=1)) == []


def test_nearest_tie_prefers_earlier_and_missing_close_is_explicit():
    rows = clv.calculate([snapshot(49, (2, 4, 4), 2.1),
                          snapshot(47, (2, 4, 4), 2.3)], DAY, as_of=KICKOFF)
    row = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 48)
    assert row["price"] == 2.1
    partial = snapshot(48, (2, 4))
    rows = clv.calculate([partial], DAY, as_of=KICKOFF)
    assert all(r["clv"] is None and r["late"] is None for r in rows)
    assert clv.summarize(rows) == []
    with pytest.raises(ValueError, match="kickoff"):
        clv.calculate(history() + [partial.model_copy(
            update={"fixture_kickoff_at": KICKOFF + timedelta(hours=1)})], DAY, as_of=KICKOFF)


@pytest.mark.parametrize("p,band", [(.299, "<30%"), (.3, "30-45%"),
                                  (.45, "45-60%"), (.6, ">=60%")])
def test_probability_boundaries(p, band):
    assert clv.probability_band(p) == band


def test_offline_cli_reads_existing_jsonl_and_writes_daily_csv(tmp_path: Path):
    source = tmp_path / "odds-snapshots.jsonl"
    source.write_text("\n".join(s.model_dump_json() for s in history()), encoding="utf-8")
    clv.main(["--date", DAY.isoformat(), "--output", str(tmp_path / "out"), str(source)])
    with (tmp_path / "out" / f"{DAY}-clv.csv").open() as stream:
        assert len(list(csv.DictReader(stream))) == 9
    source.write_text(source.read_text().replace(history()[0].fixture_id, "=1+1"))
    clv.main(["--date", DAY.isoformat(), "--output", str(tmp_path / "out"), str(source)])
    with (tmp_path / "out" / f"{DAY}-clv.csv").open() as stream:
        assert next(csv.DictReader(stream))["match"] == "'=1+1"
    report = tmp_path / "existing.json"
    report.write_text(json.dumps({"rows": [{
        "event_id": "synthetic", "home_team": "Home", "away_team": "Away",
        "kickoff_utc": KICKOFF.isoformat(), "capture_time_utc": KICKOFF.isoformat(),
        "source_timestamp_utc": KICKOFF.isoformat(), "market_key": "h2h",
        "bookmaker_key": "betclic_fr", "outcome": "Home", "point": None, "price": 2.2,
    }]}), encoding="utf-8")
    assert clv.calculate(clv.load([report]), DAY, as_of=KICKOFF) == []


@pytest.mark.parametrize("opening,fr,late", [(2.1, 2.2, False),
    (2 / .95, 2.04, True), (2.5, 2.039, False), (2 / 1.05, 2.2, True)])
def test_lag_thresholds(opening, fr, late):
    rows = clv.calculate([snapshot(48, (opening, 4, 4)), snapshot(2, (2, 4, 4), fr)],
                         DAY, as_of=KICKOFF)
    assert next(r["late"] for r in rows if r["issue"] == "1" and r["horizon"] == 2) is late


def test_partial_pinnacle_opening_still_supplies_issue_movement():
    rows = clv.calculate([snapshot(48, (2.5,)), snapshot(2, (2, 4, 4))], DAY, as_of=KICKOFF)
    assert next(r["late"] for r in rows if r["issue"] == "1" and r["horizon"] == 2) is True


def test_normalized_report_reuses_model_and_rejects_conflicts(tmp_path: Path):
    rows = []
    for s in history():
        for q in s.quotes:
            rows.append(dict(event_id="synthetic", home_team="Home", away_team="Away",
                kickoff_utc=KICKOFF.isoformat(), capture_time_utc=s.observed_at.isoformat(),
                source_timestamp_utc=s.observed_at.isoformat(), market_key="h2h", point=None,
                bookmaker_key=clv.BOOKS[q.bookmaker_id], price=float(q.odds_decimal),
                outcome={"HOME": "Home", "DRAW": "Draw", "AWAY": "Away"}[q.market.selection]))
    path = tmp_path / "normalized.json"
    path.write_text(json.dumps({"rows": rows + rows}), encoding="utf-8")
    assert clv.calculate(clv.load([path]), DAY, as_of=KICKOFF) == clv.calculate(
        history(), DAY, as_of=KICKOFF)
    path.write_text(json.dumps({"rows": rows + [{**rows[0], "kickoff_utc":
        (KICKOFF + timedelta(hours=1)).isoformat()}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        clv.load([path])


def test_single_three_hour_quote_does_not_fill_distant_horizons():
    rows = clv.calculate([snapshot(3, (2, 4, 4))], DAY, as_of=KICKOFF)
    assert all(r["status"] == "MISSING_HORIZON" and r["price"] is None
               and r["gap_minutes"] is None for r in rows if r["horizon"] != 2)
    assert all(r["status"] == "OK" and r["gap_minutes"] == -60
               and r["close_gap_minutes"] == 180 for r in rows if r["horizon"] == 2)


def test_late_requires_nearby_pinnacle_opening():
    rows = clv.calculate([snapshot(48, ()), snapshot(2, (2, 4, 4))], DAY, as_of=KICKOFF)
    assert all(r["late"] is None for r in rows)
