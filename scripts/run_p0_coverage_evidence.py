"""Run the pinned P0 coverage evidence ladder without provider or write access."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from robin.historical_deep.coverage_evidence import (
    ZERO_EFFECTS,
    PinnedInventoryReader,
    aggregate_stage,
    build_partition_checkpoint,
    build_partition_plan,
    freeze_selection,
    load_authority,
    measure_partition,
    validate_predecessor,
    validate_selection,
    validate_stage_attempt,
)
from robin.historical_deep.normalization import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}_MUST_BE_A_MAPPING")
    return value


def _read_json(path: Path, *, label: str) -> Mapping[str, object]:
    def reject_duplicate_pairs(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"{label}_DUPLICATE_JSON_KEY")
            output[key] = value
        return output

    def reject_constant(_value: str) -> None:
        raise ValueError(f"{label}_NON_FINITE_JSON")

    try:
        return _mapping(
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            ),
            label=label,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label}_INVALID") from error


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError(f"P0_OUTPUT_ALREADY_EXISTS_WITH_DIFFERENT_CONTENT:{path}") from None


def _signed(value: Mapping[str, object], *, field: str) -> Mapping[str, object]:
    result = dict(value)
    result[field] = canonical_sha256(value)
    return result


def _assert_runtime_safety(environment: Mapping[str, str]) -> None:
    if environment.get("API_FOOTBALL_KEY"):
        raise RuntimeError("API_FOOTBALL_KEY_MUST_NOT_BE_MOUNTED")
    if environment.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL_MUST_NOT_BE_MOUNTED")
    expected = {
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "ODDS_API_CREDITS_ALLOWED": "0",
        "REMOTE_SQL_READS_ALLOWED": "0",
        "REMOTE_SQL_WRITES_ALLOWED": "0",
        "R2_WRITES_ALLOWED": "0",
        "R2_DELETES_ALLOWED": "0",
        "PURCHASES_ALLOWED": "0",
        "DEPLOYMENTS_ALLOWED": "0",
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
    }
    for name, value in expected.items():
        observed = environment.get(name)
        if observed not in (None, "", value):
            raise RuntimeError(f"P0_RUNTIME_LOCK_INVALID:{name}")


def _read_cost(reader: PinnedInventoryReader) -> Mapping[str, object]:
    telemetry = reader.telemetry
    return {
        "logical_gets": telemetry.bootstrap_requested + telemetry.evidence_gets,
        "physical_http_requests": "UNKNOWN_NOT_OBSERVED",
        "stored_bytes": (telemetry.bootstrap_stored_bytes + telemetry.evidence_stored_bytes),
        "logical_bytes": (
            telemetry.bootstrap_logical_bytes
            + telemetry.receipt_bytes
            + telemetry.payload_logical_bytes
        ),
    }


def _process_peak_rss_bytes() -> int | str:
    status_path = Path("/proc/self/status")
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                parts = line.split()
                if len(parts) == 3 and parts[2] == "kB" and parts[1].isdecimal():
                    return int(parts[1]) * 1024
    except OSError:
        pass
    return "UNKNOWN_NOT_OBSERVED"


def _runtime_resources(*, started_at: float) -> Mapping[str, object]:
    elapsed = max(0.0, time.perf_counter() - started_at)
    peak_rss = _process_peak_rss_bytes()
    return {
        "measurement_elapsed_seconds": round(elapsed, 6),
        "process_peak_rss_bytes": peak_rss,
        "process_peak_rss_source": (
            "LINUX_PROC_STATUS_VMHWM" if isinstance(peak_rss, int) else "UNKNOWN_NOT_OBSERVED"
        ),
        "signed_memory_limit_bytes": None,
        "memory_budget_gate": "UNKNOWN_NO_SIGNED_LIMIT",
    }


def _freeze(args: argparse.Namespace) -> int:
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    validate_predecessor(authority)
    validate_stage_attempt(
        authority,
        operation="freeze",
        attempt_slot=args.attempt_slot,
    )
    reader = PinnedInventoryReader.from_environment(
        os.environ,
        source_config=authority.source_config,
    )
    inventory = reader.fetch_inventory_once()
    selection = freeze_selection(
        authority,
        inventory=inventory,
        reader=reader,
        code_revision=args.code_revision,
        attempt_slot=args.attempt_slot,
    )
    regenerated = freeze_selection(
        authority,
        inventory=inventory,
        reader=reader,
        code_revision=args.code_revision,
        attempt_slot=args.attempt_slot,
    )
    if selection != regenerated:
        raise RuntimeError("P0_SELECTION_REGENERATION_DIVERGED")
    output = Path(args.output_directory)
    _write_json(output / "selection-manifest.json", selection)
    freeze_receipt = _signed(
        {
            "schema_version": "p0-coverage-freeze-receipt-v1",
            "stage": args.stage,
            "selection_sha256": selection["selection_sha256"],
            "inventory_sha256": inventory.manifest_sha256,
            "code_revision": args.code_revision,
            "attempt_slot": args.attempt_slot,
            "failed_freeze_conservative_charge": selection["failed_freeze_conservative_charge"],
            "partition_count": selection["partition_count"],
            "deterministic_regeneration_check": True,
            "fixture_selection": _mapping(
                selection.get("fixture_selection"),
                label="P0_FREEZE_FIXTURE_SELECTION",
            ),
            "status": "FROZEN_SELECTION_ONLY_NO_CALCULATION",
            "effects": dict(ZERO_EFFECTS),
        },
        field="freeze_receipt_sha256",
    )
    _write_json(output / "freeze-receipt.json", freeze_receipt)
    cost = _signed(
        {
            "schema_version": "p0-coverage-freeze-cost-v1",
            "stage": args.stage,
            "selection_sha256": selection["selection_sha256"],
            "attempt_slot": args.attempt_slot,
            "failed_freeze_conservative_charge": selection["failed_freeze_conservative_charge"],
            "reads": _read_cost(reader),
            "telemetry": reader.telemetry.as_dict(),
            "quota": "UNKNOWN_NOT_OBSERVED",
            "monetary_cost": "UNKNOWN_NOT_OBSERVED",
            "effects": dict(ZERO_EFFECTS),
        },
        field="cost_sha256",
    )
    _write_json(output / "cost-report.json", cost)
    return 0


def _plan(args: argparse.Namespace) -> int:
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    selection = _read_json(Path(args.selection), label="P0_COMMITTED_SELECTION")
    plan = build_partition_plan(selection, authority=authority)
    _write_json(Path(args.output), plan)
    return 0


def _preflight(args: argparse.Namespace) -> int:
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    validate_predecessor(authority)
    validate_stage_attempt(
        authority,
        operation=args.operation,
        attempt_slot=args.attempt_slot,
    )
    return 0


def _measure(args: argparse.Namespace) -> int:
    started_at = time.perf_counter()
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    validate_stage_attempt(
        authority,
        operation="measure",
        attempt_slot=args.attempt_slot,
    )
    selection = _read_json(Path(args.selection), label="P0_COMMITTED_SELECTION")
    # This binding is intentionally checked before credentials initialize a client.
    validate_selection(selection, authority=authority, stage=args.stage)
    reader = PinnedInventoryReader.from_environment(
        os.environ,
        source_config=authority.source_config,
    )
    inventory = reader.fetch_inventory_once()
    receipt, counts = measure_partition(
        authority,
        selection=selection,
        partition_id=args.partition_id,
        inventory=inventory,
        reader=reader,
        code_revision=args.code_revision,
        attempt_slot=args.attempt_slot,
    )
    regenerated_receipt, regenerated_counts = measure_partition(
        authority,
        selection=selection,
        partition_id=args.partition_id,
        inventory=inventory,
        reader=reader,
        code_revision=args.code_revision,
        attempt_slot=args.attempt_slot,
    )
    if receipt != regenerated_receipt or counts != regenerated_counts:
        raise RuntimeError("P0_MEASUREMENT_REGENERATION_DIVERGED")
    output = Path(args.output_directory)
    _write_json(output / "partition-receipt.json", receipt)
    _write_json(output / "family-counts.json", counts)
    cost = _signed(
        {
            "schema_version": "p0-coverage-partition-cost-v1",
            "stage": args.stage,
            "partition_id": args.partition_id,
            "attempt_slot": args.attempt_slot,
            "selection_sha256": selection["selection_sha256"],
            "reads": _read_cost(reader),
            "resources": _runtime_resources(started_at=started_at),
            "telemetry": reader.telemetry.as_dict(),
            "quota": "UNKNOWN_NOT_OBSERVED",
            "monetary_cost": "UNKNOWN_NOT_OBSERVED",
            "effects": dict(ZERO_EFFECTS),
        },
        field="cost_sha256",
    )
    _write_json(output / "cost-report.json", cost)
    return 0


def _aggregate(args: argparse.Namespace) -> int:
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    selection = _read_json(Path(args.selection), label="P0_COMMITTED_SELECTION")
    stage, feed, gate, cost = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=Path(args.shards_directory),
        attempt_slot=args.attempt_slot,
    )
    regenerated = aggregate_stage(
        authority,
        selection=selection,
        shards_directory=Path(args.shards_directory),
        attempt_slot=args.attempt_slot,
    )
    if (stage, feed, gate, cost) != regenerated:
        raise RuntimeError("P0_AGGREGATE_REGENERATION_DIVERGED")
    output = Path(args.output_directory)
    _write_json(output / "stage-receipt.json", stage)
    _write_json(output / "coverage-feed.json", feed)
    _write_json(output / "gate-report.json", gate)
    _write_json(output / "cost-report.json", cost)
    return 0


def _checkpoint(args: argparse.Namespace) -> int:
    _assert_runtime_safety(os.environ)
    authority = load_authority(ROOT, stage=args.stage)
    selection = _read_json(Path(args.selection), label="P0_COMMITTED_SELECTION")
    output_bindings: Mapping[str, object] | None = None
    if args.status == "COMPLETED":
        measurement_directory = Path(args.measurement_directory)
        receipt = _read_json(
            measurement_directory / "partition-receipt.json",
            label="P0_CHECKPOINT_PARTITION_RECEIPT",
        )
        counts = _read_json(
            measurement_directory / "family-counts.json",
            label="P0_CHECKPOINT_FAMILY_COUNTS",
        )
        cost = _read_json(
            measurement_directory / "cost-report.json",
            label="P0_CHECKPOINT_COST",
        )
        output_bindings = {
            "partition_receipt_sha256": receipt.get("partition_receipt_sha256"),
            "family_counts_sha256": counts.get("counts_sha256"),
            "cost_sha256": cost.get("cost_sha256"),
        }
    checkpoint = build_partition_checkpoint(
        authority,
        selection=selection,
        partition_id=args.partition_id,
        code_revision=args.code_revision,
        attempt_slot=args.attempt_slot,
        status=args.status,
        elapsed_seconds=args.elapsed_seconds,
        output_bindings=output_bindings,
        failure_code=args.failure_code,
        github_run_id=os.environ.get("GITHUB_RUN_ID", "LOCAL_RUN"),
        github_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
    )
    _write_json(Path(args.output), checkpoint)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "freeze", "plan", "measure", "aggregate", "checkpoint"):
        command = commands.add_parser(name)
        command.add_argument(
            "--stage",
            choices=("E1A", "E1B", "E2", "E3A", "E3B", "E4"),
            required=True,
        )
    freeze = commands.choices["freeze"]
    freeze.add_argument("--attempt-slot", type=int, choices=(1, 2), required=True)
    freeze.add_argument("--code-revision", required=True)
    freeze.add_argument("--output-directory", required=True)

    plan = commands.choices["plan"]
    plan.add_argument("--selection", required=True)
    plan.add_argument("--output", required=True)

    measure = commands.choices["measure"]
    measure.add_argument("--attempt-slot", type=int, choices=(1, 2), required=True)
    measure.add_argument("--selection", required=True)
    measure.add_argument("--partition-id", required=True)
    measure.add_argument("--code-revision", required=True)
    measure.add_argument("--output-directory", required=True)

    aggregate = commands.choices["aggregate"]
    aggregate.add_argument("--attempt-slot", type=int, choices=(1, 2), required=True)
    aggregate.add_argument("--selection", required=True)
    aggregate.add_argument("--shards-directory", required=True)
    aggregate.add_argument("--output-directory", required=True)

    preflight = commands.choices["preflight"]
    preflight.add_argument("--operation", choices=("freeze", "measure"), required=True)
    preflight.add_argument("--attempt-slot", type=int, choices=(1, 2), required=True)

    checkpoint = commands.choices["checkpoint"]
    checkpoint.add_argument("--selection", required=True)
    checkpoint.add_argument("--partition-id", required=True)
    checkpoint.add_argument("--code-revision", required=True)
    checkpoint.add_argument("--attempt-slot", type=int, choices=(1, 2), required=True)
    checkpoint.add_argument(
        "--status",
        choices=("STARTED", "COMPLETED", "FAILED"),
        required=True,
    )
    checkpoint.add_argument("--elapsed-seconds", type=float, required=True)
    checkpoint.add_argument("--measurement-directory", default=".")
    checkpoint.add_argument("--failure-code")
    checkpoint.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {
        "preflight": _preflight,
        "freeze": _freeze,
        "plan": _plan,
        "measure": _measure,
        "aggregate": _aggregate,
        "checkpoint": _checkpoint,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
