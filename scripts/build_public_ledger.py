"""Auditer la chaîne append-only avant toute construction Robin Live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.patterns.ledger import EvidenceLedger


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = EvidenceLedger(args.ledger).audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit))


if __name__ == "__main__":
    main()
