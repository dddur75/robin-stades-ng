#!/usr/bin/env python3
"""Render or check the frozen Recovery V2 LIVE PostgreSQL call graph."""

from __future__ import annotations

import argparse
from pathlib import Path

from robin.data_torrent.live_call_graph import (
    CALL_GRAPH_RELATIVE_PATH,
    render_live_postgresql_call_graph_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    target = repository_root / CALL_GRAPH_RELATIVE_PATH
    expected = render_live_postgresql_call_graph_v2()
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            raise SystemExit("DATA_TORRENT_LIVE_POSTGRESQL_CALL_GRAPH_DRIFT")
        return 0
    target.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
