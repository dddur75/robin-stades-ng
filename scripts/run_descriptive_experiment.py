#!/usr/bin/env python3
"""Run Robin's bounded descriptive experiment on two verified artifacts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from robin.capture.descriptive_experiment import (  # noqa: E402
    build_experiment_report,
    load_verified_bundle,
    write_report,
)
from robin.capture.real_data_dashboard import compare_acquisitions  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Recalculate the frozen Robin descriptive pair independently"
    )
    result.add_argument("--previous", required=True, type=Path)
    result.add_argument("--current", required=True, type=Path)
    result.add_argument("--output", required=True, type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    previous = load_verified_bundle(arguments.previous)
    current = load_verified_bundle(arguments.current)
    previous_rows = cast(list[Mapping[str, object]], previous.report["rows"])
    current_rows = cast(list[Mapping[str, object]], current.report["rows"])
    shared_reference = compare_acquisitions(current_rows, previous_rows)
    report = build_experiment_report(
        previous,
        current,
        shared_reference=shared_reference,
    )
    write_report(arguments.output, report)
    print(
        "DESCRIPTIVE_EXPERIMENT_WRITTEN "
        f"matched={report['result']['matched_offer_count']} "
        f"changed={report['result']['changed_offer_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
