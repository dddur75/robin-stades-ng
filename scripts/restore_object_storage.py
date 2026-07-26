"""Tester une restauration R2 représentative dans un répertoire temporaire vide."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.historical.object_storage_restore import run_representative_restore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    report = run_representative_restore(
        state=args.state,
        destination=args.destination,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] != "RESTORE_VERIFIED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
