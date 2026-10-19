"""Offline cumulative exports: selection, denominator and reproducibility."""
import csv
import json
import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "clv_cumul.py"


def normalized(day="2026-10-18", projected=False):
    rows = []
    for hour in ("2026-10-16T18:00:00Z", "2026-10-17T18:00:00Z", "2026-10-18T16:00:00Z"):
        for book, prices in (("pinnacle", (2, 4, 4)), ("betclic_fr", (2.2, 4, 4))):
            for team, price in zip(("Home", "Draw", "Away"), prices):
                row = dict(event_id="event", match="Home — Away", kickoff_utc=f"{day}T18:00:00Z",
                           capture_time_utc=hour, source_timestamp_utc=hour,
                           market_key="h2h", point=None, bookmaker_key=book,
                           outcome=team, price=price)
                if not projected:
                    row.update(home_team="Home", away_team="Away")
                rows.append(row)
    return {"rows": rows}


def test_loader_accepts_public_dashboard_projection_and_rejects_ambiguous_teams(tmp_path):
    path = tmp_path / "robin-real-data.json"
    path.write_text(json.dumps(normalized(projected=True)))
    loader = runpy.run_path(str(SCRIPT))["load_source"]
    assert len(loader(path)) == 3
    data = normalized(projected=True)
    data["rows"][0]["match"] = "Home — Ambiguous — Away"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="team"):
        loader(path)


def test_cumul_daily_duplicates_cutoff_and_reproducibility(tmp_path):
    assert SCRIPT.exists(), "cumulative command is missing"
    main = runpy.run_path(str(SCRIPT))["main"]
    stock = tmp_path / "stock"
    stock.mkdir()
    source = stock / "robin-real-data.json"
    source.write_text(json.dumps(normalized(projected=True)))
    (stock / "copy").mkdir()
    duplicate = stock / "copy" / "odds-snapshots.jsonl"
    duplicate.write_text("\n".join(s.model_dump_json() for s in runpy.run_path(str(SCRIPT))["load_source"](source)))
    future = stock / "future"
    future.mkdir()
    (future / "robin-real-data.json").write_text(json.dumps(normalized("2026-10-20")))
    out = tmp_path / "out"
    argv = ["--through", "2026-10-19", "--output", str(out), str(stock)]
    main(argv)
    details = list(csv.DictReader((out / "2026-10-18-clv.csv").open()))
    assert len(details) == 9  # repeated source must not inflate n
    assert not (out / "2026-10-20-clv.csv").exists()
    assert len(list(csv.DictReader((out / "2026-10-18-summary.csv").open()))) == 6
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    main(argv)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    assert "MISSING_HORIZON" in (out / "CUMUL.md").read_text()


def test_cumulative_missing_denominator_and_late_mean():
    assert SCRIPT.exists(), "cumulative command is missing"
    summarize = runpy.run_path(str(SCRIPT))["cumulative"]
    rows = [dict(book="betclic_fr", horizon=2, p_fair_close=.5, clv=value,
                 late=late, status=status) for value, late, status in
            ((.1, True, "OK"), (.3, False, "OK"), (None, None, "MISSING_HORIZON"))]
    row = next(r for r in summarize(rows) if r["book"] == "betclic_fr"
               and r["band"] == "45-60%" and r["horizon"] == 2)
    assert row["n"] == 2
    assert row["mean_clv"] == pytest.approx(.2)
    assert row["ci95_low"] == pytest.approx(.2 - 12.706204736 * .1)
    assert row["late_n"] == 1 and row["late_mean_clv"] == pytest.approx(.1)
    assert row["missing_horizon_share"] == pytest.approx(1 / 3)


def test_conflicting_kickoffs_are_reported_without_choosing_a_source(tmp_path):
    main = runpy.run_path(str(SCRIPT))["main"]
    source = tmp_path / "source.json"
    payload = normalized()
    extra = {**payload["rows"][0], "kickoff_utc": "2026-10-18T19:00:00Z",
             "capture_time_utc": "2026-10-17T19:00:00Z",
             "source_timestamp_utc": "2026-10-17T19:00:00Z"}
    payload["rows"].append(extra)
    source.write_text(json.dumps(payload))
    out = tmp_path / "out"
    main(["--through", "2026-10-19", "--output", str(out), str(source)])
    assert list(csv.DictReader((out / "2026-10-18-clv.csv").open())) == []
    exclusions = list(csv.DictReader((out / "EXCLUSIONS.csv").open()))
    assert len(exclusions) == 1
    assert exclusions[0]["reason"] == "conflicting fixture kickoff"
