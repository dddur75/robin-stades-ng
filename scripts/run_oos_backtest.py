"""Recalculer les baselines hors échantillon du Jalon 2."""

from pathlib import Path

import pandas as pd

from robin.backtesting.oos import evaluate_walk_forward


def main() -> None:
    frame = pd.read_parquet("data/matches.parquet")
    results = evaluate_walk_forward(frame, devig_method="PROPORTIONAL")
    output = Path("rapports/jalon2")
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result.as_dict() for result in results]).to_json(
        output / "oos-results.json",
        orient="records",
        indent=2,
        force_ascii=False,
    )
    print(f"{len(results)} baselines évaluées")


if __name__ == "__main__":
    main()
