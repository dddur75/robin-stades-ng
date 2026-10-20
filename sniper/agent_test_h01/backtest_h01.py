"""Standalone H01; only previous league matches in the same season count."""
from collections import defaultdict, deque
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SEASONS = ("2021", "2122", "2223", "2324", "2425")
LEAGUES = ("E0", "F1", "D1", "I1", "SP1")
REQUIRED = {"Date", "HomeTeam", "AwayTeam", "FTR", "B365H"}


def validate(frame):
    """Fail explicitly rather than silently excluding malformed source rows."""
    if not REQUIRED.issubset(frame.columns) or frame.empty:
        raise ValueError("Empty CSV or missing required columns")
    if frame[["Date", "HomeTeam", "AwayTeam", "FTR"]].isna().any().any():
        raise ValueError("Missing match identity or result")
    if not frame["FTR"].isin(["H", "D", "A"]).all():
        raise ValueError("Invalid or unsettled match result")
    if frame.duplicated(["HomeTeam", "AwayTeam"]).any():
        raise ValueError("Duplicate fixture within league-season")
    pd.to_datetime(frame["Date"], format="mixed", dayfirst=True, errors="raise")


def select_bets(matches):
    frame = matches.copy()
    frame["date"] = pd.to_datetime(frame["Date"], format="mixed", dayfirst=True)
    # A date is the information cutoff. Same-day results never feed each other.
    frame = frame.sort_values(["date", "league", "HomeTeam", "AwayTeam", "season"])
    home_form = defaultdict(lambda: deque(maxlen=3))
    away_form = defaultdict(lambda: deque(maxlen=3))
    bets = []
    for date, day in frame.groupby("date", sort=True):
        for row in day.to_dict("records"):
            home_key = (row["season"], row["league"], row["HomeTeam"])
            away_key = (row["season"], row["league"], row["AwayTeam"])
            odds = pd.to_numeric(row["B365H"], errors="coerce")
            if (list(home_form[home_key]) == [True] * 3
                    and list(away_form[away_key]) == [True] * 3
                    and pd.notna(odds) and 1.40 <= odds <= 3.00):
                gain = Decimal(str(odds)) - 1 if row["FTR"] == "H" else Decimal(-1)
                bets.append({
                    "date": date.strftime("%Y-%m-%d"), "season": row["season"],
                    "league": row["league"], "home_team": row["HomeTeam"],
                    "away_team": row["AwayTeam"], "odds": float(odds),
                    "result": row["FTR"], "gain": float(gain),
                })
        for row in day.to_dict("records"):
            key = (row["season"], row["league"])
            home_form[(*key, row["HomeTeam"])].append(row["FTR"] == "H")
            away_form[(*key, row["AwayTeam"])].append(row["FTR"] == "H")
    return bets


def summarize(bets):
    profit = peak = drawdown = Decimal(0)
    for bet in bets:
        profit += Decimal(str(bet["gain"]))
        peak = max(peak, profit)
        drawdown = max(drawdown, peak - profit)
    count = len(bets)
    return {
        "bets": count,
        "win_rate_pct": round(100 * sum(b["gain"] > 0 for b in bets) / count, 8)
        if count else None,
        "roi_pct": round(float(100 * profit / count), 8) if count else None,
        "profit_units": float(profit), "max_drawdown_units": float(drawdown),
        "average_odds": round(float(sum((Decimal(str(b["odds"])) for b in bets),
                                       Decimal(0)) / count), 8) if count else None,
    }


def main():
    frames, sources = [], []
    for season in SEASONS:
        for league in LEAGUES:
            name = f"{season}_{league}.csv"
            path = ROOT / "data" / name
            frame = pd.read_csv(path, encoding="utf-8-sig")
            validate(frame)
            if "Div" not in frame or not frame["Div"].eq(league).all():
                raise ValueError(f"Wrong league in {name}")
            dates = pd.to_datetime(frame["Date"], format="mixed", dayfirst=True)
            start = pd.Timestamp(2000 + int(season[:2]), 7, 1)
            end = pd.Timestamp(2000 + int(season[2:]), 7, 1)
            if not ((dates >= start) & (dates < end)).all():
                raise ValueError(f"Wrong season in {name}")
            frames.append(frame.assign(season=season, league=league))
            sources.append({"file": f"data/{name}", "rows": len(frame),
                            # Git may translate CRLF on checkout; hash canonical LF.
                            "sha256_lf": hashlib.sha256(
                                path.read_bytes().replace(b"\r\n", b"\n")
                            ).hexdigest(),
                            "url": f"https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"})
    bets = select_bets(pd.concat(frames, ignore_index=True))
    result = {
        "hypothesis": "H01 agent test; not pre-registered", "stake_units": 1,
        "order": "date, league, home_team, away_team, season; same-day results excluded",
        "total": summarize(bets),
        "by_season": {season: summarize([b for b in bets if b["season"] == season])
                      for season in SEASONS},
        "sources": sources, "bets": bets,
    }
    output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    (ROOT / "results.json").write_bytes(output.encode("utf-8"))
    print(json.dumps({"total": result["total"], "by_season": result["by_season"]}, indent=2))


if __name__ == "__main__":
    main()
