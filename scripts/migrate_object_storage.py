"""Migration progressive vers un stockage S3/R2, sans suppression de source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.historical.object_storage_migration import run_migration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-files", type=int, default=25)
    args = parser.parse_args()
    report = run_migration(
        state=args.state,
        execute=args.execute,
        max_files=args.max_files,
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
