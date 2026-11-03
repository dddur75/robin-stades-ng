"""Fetch missing source snapshots; keep committed bytes for reproducible reruns."""
import importlib.util
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests


def main():
    root = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("h01", root / "backtest_h01.py")
    h01 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h01)
    data = root / "data"
    data.mkdir(exist_ok=True)
    with requests.Session() as session:
        for season in h01.SEASONS:
            for league in h01.LEAGUES:
                path = data / f"{season}_{league}.csv"
                if path.exists():
                    h01.validate(pd.read_csv(path, encoding="utf-8-sig"))
                    print(f"cached {path.name}")
                    continue
                url = f"https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
                response = session.get(url, timeout=(10, 60))
                response.raise_for_status()
                h01.validate(pd.read_csv(BytesIO(response.content), encoding="utf-8-sig"))
                temporary = path.with_suffix(".csv.tmp")
                temporary.write_bytes(response.content)
                temporary.replace(path)
                print(f"downloaded {path.name}")


if __name__ == "__main__":
    main()
