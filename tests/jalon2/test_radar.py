"""Paper radar: thresholds, unique first crossings and pre-kickoff boosts."""

import csv
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin import clv

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/radar_hebdo.py"
FIXTURE = runpy.run_path(str(Path(__file__).with_name("test_clv.py")))


def radar():
    assert SCRIPT.exists(), "weekly radar is missing"
    return runpy.run_path(str(SCRIPT))


def rows():
    kickoff = FIXTURE["KICKOFF"]
    history = [FIXTURE["snapshot"](h, (2, 4, 4), p) for h, p in ((48, 2.01), (24, 2.04), (2, 2.10))]
    return [
        {**r, "day": kickoff.date().isoformat(), "kind": "standard"}
        for r in clv.calculate(history, kickoff.date(), as_of=kickoff)
    ]


def test_first_crossing_is_unique_for_each_threshold():
    api = radar()
    selected = api["first_crossings"](rows() + rows())
    home = [r for r in selected if r["issue"] == "1"]
    assert [(r["threshold"], r["horizon"]) for r in home] == [(0, 48), (0.02, 24), (0.05, 2)]
    summary = api["statistics"](home)
    assert [r["n"] for r in summary] == [1, 1, 1]
    assert [r["gain_10"] for r in summary] == pytest.approx([0.05, 0.2, 0.5])
    assert all(r["issue"] == "1" for r in selected)  # zero EV excluded


def test_synthetic_post_kickoff_prices_do_not_change_radar():
    api = radar()
    kickoff = FIXTURE["KICKOFF"]
    clean = FIXTURE["history"]()
    poisoned = clean + [
        FIXTURE["snapshot"](0, (1.01, 90, 90), 90),
        FIXTURE["snapshot"](-1, (90, 90, 1.01), 90),
    ]

    def evaluate(history):
        return api["first_crossings"](
            [
                {**r, "day": "2026-10-18", "kind": "standard"}
                for r in clv.calculate(history, kickoff.date(), as_of=kickoff)
            ]
        )

    assert evaluate(poisoned) == evaluate(clean)


def test_manual_boost_known_ev_and_max_stake(tmp_path):
    api = radar()
    path = tmp_path / "boost.csv"
    home = next(r for r in rows() if r["issue"] == "1")
    date = (FIXTURE["KICKOFF"] - timedelta(hours=3)).isoformat()
    path.write_text(
        f"date,book,match,issue,cote_boostee,mise_max\n{date},betclic_fr,{home['match']},1,2.4,5\n"
    )
    boosts = api["load_boosts"](path, rows())
    assert len(boosts) == 1
    assert boosts[0]["clv"] == pytest.approx(0.2)
    assert boosts[0]["gain_10_eligible"] is False
    assert boosts[0]["gain_capped"] == pytest.approx(1)
    path.write_text(path.read_text().replace(date, FIXTURE["KICKOFF"].isoformat()))
    with pytest.raises(ValueError, match="kickoff"):
        api["load_boosts"](path, rows())


@pytest.mark.parametrize("bad", ["nan", "inf", "1", "-2"])
def test_invalid_boost_price_fails_closed(tmp_path, bad):
    api = radar()
    home = rows()[0]
    path = tmp_path / "boost.csv"
    path.write_text(
        "date,book,match,issue,cote_boostee,mise_max\n"
        f"2026-10-17T12:00:00Z,betclic_fr,{home['match']},1,{bad},10\n"
    )
    with pytest.raises(ValueError):
        api["load_boosts"](path, rows())


def test_weekly_cli_reproducible_and_no_triple_count(tmp_path):
    api = radar()
    source = tmp_path / "clv"
    source.mkdir()
    with (source / "2026-10-18-clv.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=clv.DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows({k: r[k] for k in clv.DETAIL_FIELDS} for r in rows())
    out = tmp_path / "out"
    argv = ["--clv-dir", str(source), "--through", "2026-10-19", "--output", str(out)]
    api["main"](argv)
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    api["main"](argv)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    assert b"\r" not in before["DETAIL-HORIZONS.csv"]
    assert "SEMAINE-2026-42.md" in before
    assert "| betclic_fr | 1 | 1 | 1 |" in before["RADAR.md"].decode()
    assert datetime.fromisoformat("2026-10-19").replace(tzinfo=UTC).isocalendar().week == 43


def test_local_stock_reuses_clv_engine_and_audits_market_labels(tmp_path):
    import json

    api = radar()
    payload = runpy.run_path(str(Path(__file__).with_name("test_clv_cumul.py")))["normalized"]()
    payload["rows"].append({**payload["rows"][0], "market_key": "super cote"})
    stock = tmp_path / "stock"
    stock.mkdir()
    (stock / "robin-real-data.json").write_text(json.dumps(payload))
    out = tmp_path / "out"
    api["main"](["--stock", str(stock), "--through", "2026-10-19", "--output", str(out)])
    audit = json.loads((out / "SOURCES.json").read_text())["boost_audit"]
    assert audit["normalized_rows_inspected"] == 19
    assert audit["boost_label_rows"] == 1
    report = (out / "RADAR.md").read_text()
    assert "| betclic_fr | 1 | 1 | 1 |" in report
    assert "1.00 €" in report


def test_exported_post_kickoff_price_is_rejected(tmp_path):
    api = radar()
    row = rows()[0]
    row["observed_at"] = FIXTURE["KICKOFF"].isoformat()
    with (tmp_path / "2026-10-18-clv.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=clv.DETAIL_FIELDS)
        writer.writeheader()
        writer.writerow({k: row[k] for k in clv.DETAIL_FIELDS})
    with pytest.raises(ValueError, match="kickoff"):
        api["load_details"](tmp_path, FIXTURE["KICKOFF"].date())


def test_boost_and_standard_do_not_count_same_selection_twice(tmp_path):
    api = radar()
    data = rows()
    home = data[0]
    path = tmp_path / "boost.csv"
    path.write_text(
        "date,book,match,issue,cote_boostee,mise_max\n"
        f"2026-10-17T12:00:00Z,betclic_fr,{home['match']},1,2.4,10\n"
    )
    selected = api["first_crossings"](data + api["load_boosts"](path, data))
    assert len(selected) == 3
    assert [r["kind"] for r in selected] == ["standard", "boost", "boost"]
    assert [r["clv"] for r in selected] == pytest.approx([0.005, 0.2, 0.2])


def test_frozen_baseline_survives_source_artifact_retention(tmp_path):
    import json

    api = radar()
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    with (baseline / "2026-10-18-clv.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=clv.DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows({k: r[k] for k in clv.DETAIL_FIELDS} for r in rows())
    stock = tmp_path / "stock"
    stock.mkdir()
    payload = runpy.run_path(str(Path(__file__).with_name("test_clv_cumul.py")))["normalized"](
        "2026-10-19"
    )
    (stock / "robin-real-data.json").write_text(json.dumps(payload))
    out = tmp_path / "out"
    api["main"](
        [
            "--stock",
            str(stock),
            "--baseline",
            str(baseline),
            "--through",
            "2026-10-19",
            "--output",
            str(out),
        ]
    )
    with (out / "DETAIL-HORIZONS.csv").open() as stream:
        assert {r["day"] for r in csv.DictReader(stream)} == {"2026-10-18", "2026-10-19"}
