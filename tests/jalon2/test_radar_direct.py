"""Contemporaneous fair: complete triplets, inclusive 15m, no closing-price leak."""

import runpy
from datetime import timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FIXTURE = runpy.run_path(str(HERE / "test_clv.py"))
RADAR = runpy.run_path(str(HERE.parents[1] / "scripts/radar_hebdo.py"))


def direct_module():
    import importlib

    return importlib.import_module("robin.radar_direct")


def sample():
    ko = FIXTURE["KICKOFF"]
    history = [
        FIXTURE["snapshot"](48, (2, 4, 4), 2.2),
        FIXTURE["snapshot"](24, (2, 4, 4), 2.2),
        FIXTURE["snapshot"](2, (2, 4, 4), 2.2),
        FIXTURE["snapshot"](0.1, (2.5, 4, 4), 2.2),
    ]
    from robin import clv

    rows = [
        {**r, "day": str(ko.date()), "kind": "standard"}
        for r in clv.calculate(history, ko.date(), as_of=ko)
    ]
    return rows, history


def test_direct_fair_does_not_use_future_close_and_deduplicates():
    rows, snapshots = sample()
    result = direct_module().enrich(rows, snapshots)
    home = [r for r in result if r["issue"] == "1"]
    assert [r["ev_direct"] for r in home] == pytest.approx([0.1] * 3)
    assert all(r["clv"] < 0 for r in home)
    selected = RADAR["first_crossings"](result, metric="ev_direct")
    assert len(selected) == 3
    assert [r["horizon"] for r in selected] == [48, 48, 48]
    table = RADAR["confirmation_table"](selected)
    assert "0 / 1" in table and "0.0%" in table


@pytest.mark.parametrize("minutes,expected", [(-15, 0.1), (15, 0.1), (-15.01, None), (15.01, None)])
def test_fifteen_minute_window_is_inclusive(minutes, expected):
    rows, _ = sample()
    fr = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 48)
    pin = FIXTURE["snapshot"](48 - minutes / 60, (2, 4, 4))
    enriched = direct_module().enrich([fr], [pin])[0]
    if expected is None:
        assert enriched["ev_direct"] is None
    else:
        assert enriched["ev_direct"] == pytest.approx(expected)
        assert enriched["pin_direct_gap_minutes"] == pytest.approx(minutes)


def test_tie_earlier_complete_triplet_only_and_conflicts_fail_closed():
    rows, _ = sample()
    fr = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 48)
    earlier = FIXTURE["snapshot"](48 + 10 / 60, (2, 4, 4))
    later = FIXTURE["snapshot"](48 - 10 / 60, (3, 4, 4))
    module = direct_module()
    assert module.enrich([fr], [later, earlier])[0]["ev_direct"] == pytest.approx(0.1)
    assert module.enrich([fr], [FIXTURE["snapshot"](48, (2, 4))])[0]["ev_direct"] is None
    conflict = FIXTURE["snapshot"](48 + 10 / 60, (3, 4, 4))
    assert module.enrich([fr], [earlier, conflict])[0]["direct_status"] == "CONFLICTING_PINNACLE"


def test_post_kickoff_and_late_ingestion_rejected():
    rows, _ = sample()
    fr = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 2)
    fr = {**fr, "observed_at": (FIXTURE["KICKOFF"] - timedelta(minutes=5)).isoformat()}
    bad = FIXTURE["snapshot"](0, (2, 4, 4))
    late = FIXTURE["snapshot"](5 / 60, (2, 4, 4)).model_copy(
        update={"ingested_at": FIXTURE["KICKOFF"] + timedelta(seconds=1)}
    )
    assert direct_module().enrich([fr], [bad, late])[0]["ev_direct"] is None


def test_missing_snapshots_are_unknown_not_negative_or_confirmed():
    rows, _ = sample()
    enriched = direct_module().enrich(rows, [])
    assert all(r["ev_direct"] is None for r in enriched)
    assert RADAR["first_crossings"](enriched, metric="ev_direct") == []
    assert "N/C" in RADAR["confirmation_table"]([])


def test_reports_include_direct_comparison_confirmation_and_missing_coverage(tmp_path):
    import json

    payload = runpy.run_path(str(HERE / "test_clv_cumul.py"))["normalized"]()
    stock = tmp_path / "stock"
    stock.mkdir()
    (stock / "robin-real-data.json").write_text(json.dumps(payload))
    out = tmp_path / "out"
    RADAR["main"](["--stock", str(stock), "--through", "2026-10-19", "--output", str(out)])
    for filename in ("RADAR.md", "SEMAINE-2026-42.md"):
        text = (out / filename).read_text()
        assert "EV_direct" in text
        assert "Confirmation" in text
        assert "100.0%" in text
        assert "Bande p juste" in text
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    RADAR["main"](["--stock", str(stock), "--through", "2026-10-19", "--output", str(out)])
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    assert (out / "PREMIERS-FRANCHISSEMENTS-DIRECT.csv").exists()
    assert json.loads((out / "SOURCES.json").read_text())["direct_reference"]["files"]


def test_confirmation_missing_close_is_explicit_and_threshold_specific():
    r = dict(book="betclic_fr", threshold=0.02, clv=None)
    text = RADAR["confirmation_table"]([r])
    assert "| betclic_fr | ≥2% | 1 | 0 / 0 | 1 | N/C |" in text


def test_delayed_ingestion_is_not_available_in_fifteen_minute_window():
    rows, _ = sample()
    fr = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 48)
    pin = FIXTURE["snapshot"](48, (2, 4, 4))
    delayed = pin.model_copy(update={"ingested_at": pin.observed_at + timedelta(minutes=16)})
    assert direct_module().enrich([fr], [delayed])[0]["ev_direct"] is None


def test_manual_boost_uses_live_reference_at_manual_timestamp():
    rows, snapshots = sample()
    fr = next(r for r in rows if r["issue"] == "1" and r["horizon"] == 48)
    boost = {
        **fr,
        "kind": "boost",
        "horizon": "MANUEL",
        "price": 2.4,
        "clv": 2.4 * fr["p_fair_close"] - 1,
    }
    result = direct_module().enrich([boost], snapshots)[0]
    assert result["ev_direct"] == pytest.approx(0.2)
    assert result["pin_direct_gap_minutes"] == 0


def test_confirmation_uses_price_at_each_direct_threshold_first_crossing():
    from robin import clv

    ko = FIXTURE["KICKOFF"]
    history = [
        FIXTURE["snapshot"](h, (2, 4, 4), price) for h, price in ((48, 2.01), (24, 2.04), (2, 2.1))
    ]
    history.append(FIXTURE["snapshot"](0.1, (2.04, 4, 4)))
    rows = [
        {**r, "day": str(ko.date()), "kind": "standard"}
        for r in clv.calculate(history, ko.date(), as_of=ko)
    ]
    selected = RADAR["first_crossings"](direct_module().enrich(rows, history), metric="ev_direct")
    home = [r for r in selected if r["issue"] == "1"]
    assert [r["horizon"] for r in home] == [48, 24, 2]
    assert [r["clv"] > 0 for r in home] == [False, True, True]


def test_reference_kickoff_must_match_frozen_clv_metadata():
    rows, snapshots = sample()
    changed = [
        s.model_copy(update={"fixture_kickoff_at": s.fixture_kickoff_at + timedelta(hours=1)})
        for s in snapshots
    ]
    result = direct_module().enrich(rows, changed)
    assert all(
        r["ev_direct"] is None and r["direct_status"] == "CONFLICTING_PINNACLE" for r in result
    )
