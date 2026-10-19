"""Export existing normalized Git data; all remote/provider/DB protocols denied."""

import argparse
import json
from pathlib import Path

from robin.prematch.export import export_snapshot
from robin.prematch.sources import load_snapshot, load_targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--source-ref", required=True, help="Immutable historical-data commit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = load_snapshot(args.repository, args.source_ref)
    report = export_snapshot(snapshot, load_targets(args.repository), args.output)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
