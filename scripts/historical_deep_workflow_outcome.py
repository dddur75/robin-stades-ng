"""Expose a sanitized collection outcome to reusable GitHub workflows."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

_RESUMABLE_REASONS = {
    "JOB_PROVIDER_CALL_LIMIT_REACHED",
    "JOB_DURATION_LIMIT_REACHED",
}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def workflow_outcome(artifact: Mapping[str, object]) -> tuple[str, bool]:
    status = str(artifact.get("status", "FAILED")).upper()
    result = _mapping(artifact.get("result"))
    reason_value = result.get("reason", artifact.get("reason"))
    reason = str(reason_value) if reason_value is not None else None
    provider_stop = status in {"BLOCKED_PROVIDER", "FAILED"}
    if status == "PARTIAL" and reason not in {None, *_RESUMABLE_REASONS}:
        provider_stop = True
    if status not in {
        "COMPLETE",
        "PARTIAL",
        "BLOCKED_PROVIDER",
        "FAILED",
    }:
        provider_stop = True
    return status, provider_stop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    path = build_parser().parse_args(argv).artifact
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"status": "FAILED", "reason": "ARTIFACT_UNAVAILABLE"}
    status, provider_stop = workflow_outcome(_mapping(payload))
    print(f"status={status}")
    print(f"provider_stop={str(provider_stop).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
