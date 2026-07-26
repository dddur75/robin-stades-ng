"""Répliquer le delta historique vers R2 sans bloquer la source Git durable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.historical.object_storage_migration import run_continuous_replication


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--circuit-breaker-failures", type=int, default=3)
    args = parser.parse_args()
    report = run_continuous_replication(
        state=args.state,
        max_files=args.max_files,
        max_retries=args.max_retries,
        circuit_breaker_failures=args.circuit_breaker_failures,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    errors = report["errors"]
    if not isinstance(errors, int):
        raise TypeError("INVALID_R2_REPLICATION_ERROR_COUNT")
    if errors > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
