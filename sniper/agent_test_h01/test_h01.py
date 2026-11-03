"""Twenty-match, hand-calculated fixture: no source downloads needed."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest


def engine():
    spec = importlib.util.spec_from_file_location(
        "h01", Path(__file__).with_name("backtest_h01.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def matches():
    # A wins at home, B loses away. Venue-opposite matches must not reset form.
    rows = [
        ("A", "X", "H", 2.0), ("Y", "B", "H", 2.0),
        ("A", "X", "H", 2.0), ("Y", "B", "H", 2.0),
        ("A", "B", "H", 2.0),  # only TWO previous per venue: no bet
        ("X", "A", "H", 2.0), ("B", "Y", "H", 2.0),
        ("A", "B", "H", 1.40),  # bet +0.40, lower inclusive boundary
        ("A", "B", "D", 3.00),  # bet -1, upper boundary; draw breaks both
        ("A", "B", "H", 2.0),  # no bet after draw
        ("A", "B", "H", 2.0), ("A", "B", "H", 2.0),
        ("A", "B", "H", 1.39),  # odds below range; still updates form
        ("A", "B", "H", 3.01),  # odds above range
        ("A", "B", "H", None),  # missing odds; still updates form
        ("A", "B", "H", 2.00),  # bet +1
        ("A", "B", "A", 2.50),  # bet -1; away win breaks form
        ("A", "B", "H", 2.0),
        ("A", "B", "H", 2.0), ("A", "B", "H", 2.0),
    ]
    frame = pd.DataFrame(rows, columns=["HomeTeam", "AwayTeam", "FTR", "B365H"])
    frame["Date"] = pd.date_range("2020-09-01", periods=20).strftime("%d/%m/%Y")
    frame["season"] = "2021"
    frame["league"] = "E0"
    return frame


def test_three_previous_matches_venue_and_inclusive_odds(matches):
    bets = engine().select_bets(matches)
    assert [bet["date"] for bet in bets] == [
        "2020-09-08", "2020-09-09", "2020-09-16", "2020-09-17"
    ]
    assert [bet["gain"] for bet in bets] == [0.4, -1.0, 1.0, -1.0]


def test_fixed_stake_roi_and_drawdown_including_initial_zero(matches):
    module = engine()
    summary = module.summarize(module.select_bets(matches))
    assert summary == {
        "bets": 4, "win_rate_pct": 50.0, "roi_pct": -15.0,
        "profit_units": -0.6, "max_drawdown_units": 1.0, "average_odds": 2.225,
    }
    assert module.summarize([{"gain": -1, "odds": 2}])["max_drawdown_units"] == 1
    assert module.summarize([])["bets"] == 0
    assert module.summarize([])["roi_pct"] is None


@pytest.mark.parametrize("partition", ["season", "league"])
def test_form_never_crosses_season_or_league(matches, partition):
    matches.loc[7:, partition] = "2122" if partition == "season" else "F1"
    assert [b["date"] for b in engine().select_bets(matches)] == [
        "2020-09-16", "2020-09-17"
    ]


def test_input_order_and_future_results_do_not_change_earlier_signals(matches):
    module = engine()
    expected = module.select_bets(matches)
    assert module.select_bets(matches.iloc[::-1]) == expected
    matches.loc[17:, "FTR"] = "D"
    assert module.select_bets(matches) == expected
