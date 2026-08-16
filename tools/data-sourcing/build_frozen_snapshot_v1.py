#!/usr/bin/env python3
"""Build or verify one terminal receipt-backed snapshot without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from robin.data_snapshot.contracts import (  # noqa: E402
    EXPECTED_BATCH_ID,
    SYNTHETIC_BATCH_ID,
)
from robin.data_snapshot.freeze import build_frozen_snapshot  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--protocols",
        type=Path,
        default=ROOT / "reports" / "hypothesis-lab" / "first-25-experiment-protocols-v1.json",
    )
    parser.add_argument(
        "--readiness-matrix",
        type=Path,
        default=ROOT / "reports" / "data-sourcing" / "experiment-data-window-matrix-v1.json",
    )
    parser.add_argument("--reports-output", type=Path, required=True)
    parser.add_argument("--observation-seconds", type=int, default=300)
    parser.add_argument("--reproducibility-run", action="store_true")
    parser.add_argument(
        "--synthetic-contract",
        action="store_true",
        help="Validate only the exact synthetic contract fixture; never a real batch.",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_frozen_snapshot(
        source_root=args.source,
        output_root=args.output_root,
        protocols_path=args.protocols,
        readiness_matrix_path=args.readiness_matrix,
        reports_output=args.reports_output,
        observation_seconds=args.observation_seconds,
        reproducibility_run=args.reproducibility_run,
        check=args.check,
        expected_batch_id=(SYNTHETIC_BATCH_ID if args.synthetic_contract else EXPECTED_BATCH_ID),
        test_only_allow_short_observation=args.synthetic_contract,
    )
    print(
        json.dumps(
            {
                "check_only": result.check_only,
                "manifest_sha256": result.manifest_sha256,
                "network_calls": result.network_calls,
                "provider_calls": result.provider_calls,
                "real_market_data_leak_count": result.real_market_data_leak_count,
                "secret_reads": result.secret_reads,
                "snapshot_id": result.snapshot_id,
                "verdicts": list(result.verdicts),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
