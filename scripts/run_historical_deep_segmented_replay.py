#!/usr/bin/env python3
"""Run the provider-free continuation audit and segmented R2 replay."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from robin.historical_deep.adapters import (
    assert_safety_locks,
    build_object_store,
    validate_r2_round_trip,
)
from robin.historical_deep.contracts import load_campaign_contract
from robin.historical_deep.runtime import DurableRuntimeLedger
from robin.historical_deep.segmented_replay import (
    RunnerShutdownRecovered,
    audit_and_reconcile,
    build_replay_inventory,
    build_segment_batches,
    reduce_segments,
    replay_segment,
    validate_inventory,
)
from robin.historical_deep.storage import R2FirstRepository

SENTINEL_KEY = "historical-deep-data/schema-v1/_control/segmented-replay-sentinel.json"
DEFAULT_PARENT = "30622258001:1"
DEFAULT_PURPOSE = "P0_CLOSURE_AND_SHARDED_REPLAY"
DEFAULT_CONTINUATION = "p0-closure-30622258001-1"


def _run_token(environment: dict[str, str], explicit: str | None) -> str:
    if explicit:
        return explicit
    run_id = environment.get("GITHUB_RUN_ID", "LOCAL")
    attempt = environment.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{run_id}:{attempt}"


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("SEGMENTED_REPLAY_JSON_OBJECT_REQUIRED")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/historical-deep-data-harvest-v1.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/historical-deep"))
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--code-revision", default="UNSPECIFIED")
    parser.add_argument("--run-token")
    parser.add_argument("--continuation-id", default=DEFAULT_CONTINUATION)
    parser.add_argument("--continuation-of", default=DEFAULT_PARENT)
    parser.add_argument("--run-purpose", default=DEFAULT_PURPOSE)
    commands = parser.add_subparsers(dest="command", required=True)

    audit = commands.add_parser("audit")
    audit.add_argument("--stale-heartbeat-minutes", type=int, default=15)

    inventory = commands.add_parser("inventory")
    inventory.add_argument("--max-objects", type=int, default=250)
    inventory.add_argument("--max-logical-bytes", type=int, default=75 * 1024 * 1024)
    inventory.add_argument("--max-estimated-seconds", type=float, default=600.0)
    inventory.add_argument("--estimated-seconds-per-object", type=float, default=2.4)
    inventory.add_argument("--github-output", type=Path)

    segment = commands.add_parser("segment")
    segment.add_argument("--inventory", type=Path, required=True)
    segment.add_argument("--segment-id", required=True)
    segment.add_argument("--pass-id", type=int, choices=(1, 2), required=True)

    segment_batch = commands.add_parser("segment-batch")
    segment_batch.add_argument("--inventory", type=Path, required=True)
    segment_batch.add_argument("--segment-ids-json", required=True)
    segment_batch.add_argument("--pass-id", type=int, choices=(1, 2), required=True)

    reduce = commands.add_parser("reduce")
    reduce.add_argument("--inventory", type=Path, required=True)
    reduce.add_argument("--segments-root", type=Path, required=True)
    reduce.add_argument("--pass-id", type=int, choices=(1, 2), required=True)
    reduce.add_argument("--idempotent", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    environment = dict(os.environ)
    assert_safety_locks(environment)
    contract = load_campaign_contract(args.config)
    store = build_object_store(environment, cache_root=args.cache_root)
    validate_r2_round_trip(store, key=SENTINEL_KEY)
    repository = R2FirstRepository(store, namespace=contract.storage.namespace)
    ledger = DurableRuntimeLedger(store, campaign_id=contract.campaign_id)
    run_token = _run_token(environment, args.run_token)
    now = datetime.now(UTC)
    args.output.mkdir(parents=True, exist_ok=True)

    if args.command == "audit":
        result = audit_and_reconcile(
            repository,
            ledger,
            continuation_id=args.continuation_id,
            continuation_of=args.continuation_of,
            run_purpose=args.run_purpose,
            code_revision=args.code_revision,
            run_token=run_token,
            now=now,
            stale_heartbeat_minutes=args.stale_heartbeat_minutes,
        )
        _write_json(args.output / "continuation-audit.json", result)
        return 0
    if args.command == "inventory":
        result = build_replay_inventory(
            ledger,
            continuation_id=args.continuation_id,
            continuation_of=args.continuation_of,
            run_purpose=args.run_purpose,
            code_revision=args.code_revision,
            run_token=run_token,
            now=now,
            max_objects=args.max_objects,
            max_logical_bytes=args.max_logical_bytes,
            max_estimated_seconds=args.max_estimated_seconds,
            estimated_seconds_per_object=args.estimated_seconds_per_object,
        )
        _write_json(args.output / "replay-inventory.json", result)
        if args.github_output is not None:
            segments = result.get("segments")
            if not isinstance(segments, list) or not all(
                isinstance(item, dict) and isinstance(item.get("segment_id"), str)
                for item in segments
            ):
                raise ValueError("SEGMENTED_REPLAY_SEGMENT_OUTPUT_INVALID")
            segment_ids = [str(item["segment_id"]) for item in segments]
            segment_batches = build_segment_batches(segment_ids)
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"segment_ids={json.dumps(segment_ids, separators=(',', ':'))}\n")
                stream.write(
                    "segment_batches="
                    + json.dumps(segment_batches, separators=(",", ":"))
                    + "\n"
                )
                stream.write(f"inventory_sha256={result['manifest_sha256']}\n")
                stream.write(f"segments_expected={len(segment_ids)}\n")
        return 0
    if args.command in {"segment", "segment-batch"}:
        inventory = _load_json(args.inventory)
        validate_inventory(inventory)
        if args.command == "segment":
            segment_ids = [args.segment_id]
        else:
            raw_segment_ids = json.loads(args.segment_ids_json)
            if not isinstance(raw_segment_ids, list) or not all(
                isinstance(item, str) for item in raw_segment_ids
            ):
                raise ValueError("SEGMENTED_REPLAY_BATCH_IDS_INVALID")
            segment_ids = raw_segment_ids
        for segment_id in segment_ids:
            try:
                replay_segment(
                    ledger,
                    inventory=inventory,
                    segment_id=segment_id,
                    pass_id=args.pass_id,
                    output_dir=args.output / segment_id,
                )
            except RunnerShutdownRecovered:
                _write_json(
                    args.output / segment_id / "runner-shutdown.json",
                    {
                        "status": "STALE_RETRYABLE",
                        "event": "RUNNER_SHUTDOWN_RECOVERED",
                        "segment_id": segment_id,
                        "pass_id": args.pass_id,
                        "provider_calls": 0,
                    },
                )
                return 75
        return 0
    if args.command == "reduce":
        inventory = _load_json(args.inventory)
        result = reduce_segments(
            ledger,
            inventory=inventory,
            segments_root=args.segments_root,
            pass_id=args.pass_id,
            idempotent=args.idempotent,
            code_revision=args.code_revision,
            run_token=run_token,
            now=now,
        )
        name = "replay-idempotence.json" if args.idempotent else "replay-reducer.json"
        _write_json(args.output / name, result)
        github_output = environment.get("GITHUB_OUTPUT")
        if github_output:
            with Path(github_output).open("a", encoding="utf-8") as stream:
                stream.write(f"status={result['status']}\n")
                stream.write(f"global_hash={result['global_hash']}\n")
                stream.write(
                    "gates="
                    + json.dumps(result["gates"], separators=(",", ":"))
                    + "\n"
                )
        return 0
    raise AssertionError("SEGMENTED_REPLAY_COMMAND_UNREACHABLE")


def main() -> int:
    try:
        return run()
    except Exception as error:  # fail-closed CLI boundary
        print(f"SEGMENTED_REPLAY_FAILED:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
