"""Run the bounded exact-key E1B canary without provider, SQL or write access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from robin.historical_deep.coverage_evidence import PinnedInventoryReader
from robin.historical_deep.e1b_canary import (
    REPORT_FILENAMES,
    build_reports,
    file_sha256_lf,
    finalize_reports,
    mapping,
    read_json,
    require_selection_ready,
    sequence,
    validate_contracts,
    validate_reports,
)

ROOT = Path(__file__).resolve().parents[1]
SELECTION = Path("reports/evidence/e1b/e1b-selection-manifest-v1.json")


def _safety(environment: Mapping[str, str]) -> None:
    if any(environment.get(name) for name in ("API_FOOTBALL_KEY", "DATABASE_URL", "ODDS_API_KEY")):
        raise RuntimeError("E1B_FORBIDDEN_SECRET_MOUNTED")
    exact = {
        "API_FOOTBALL_CALLS_ALLOWED": "0",
        "ODDS_CREDITS_ALLOWED": "0",
        "REMOTE_SQL_ALLOWED": "0",
        "R2_LIST_ALLOWED": "0",
        "R2_HEAD_ALLOWED": "0",
        "R2_WRITES_ALLOWED": "0",
        "R2_DELETES_ALLOWED": "0",
        "DEPLOYMENT_ALLOWED": "0",
        "PUBLICATION_ALLOWED": "0",
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
    }
    for name, expected in exact.items():
        if environment.get(name) not in (None, "", expected):
            raise RuntimeError(f"E1B_RUNTIME_LOCK_INVALID:{name}")


def _validate(root: Path, require_decision: bool) -> str:
    validate_contracts(root)
    selection_hash = file_sha256_lf(root / SELECTION)
    if require_decision:
        require_selection_ready(root, selection_hash)
    return selection_hash


def _inventory_pins(selection: Mapping[str, Any], by_id: Mapping[str, object]) -> None:
    fields = (
        "payload_key", "payload_sha256", "stored_sha256", "logical_bytes",
        "stored_bytes", "receipt_id", "receipt_key", "receipt_hash",
    )
    for raw in sequence(selection["source_objects"], "E1B_OBJECTS"):
        selected = mapping(raw, "E1B_OBJECT")
        object_id = str(selected["object_id"])
        item = by_id.get(object_id)
        if item is None:
            raise ValueError("E1B_OBJECT_NOT_IN_INVENTORY")
        if any(getattr(item, field) != selected[field] for field in fields):
            raise ValueError(f"E1B_OBJECT_PIN_MISMATCH:{object_id}")


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes().replace(b"\r\n", b"\n") != payload:
        raise RuntimeError(f"E1B_OUTPUT_DRIFT:{path}")
    path.write_bytes(payload)


def _measure(root: Path, output: Path) -> None:
    _safety(os.environ)
    mission, selection = validate_contracts(root)
    selection_hash = file_sha256_lf(root / SELECTION)
    require_selection_ready(root, selection_hash)
    source_config = read_json(root / "configs/data/p0-coverage-source-config-v1.json")
    contract = read_json(root / "configs/data/capability-scoped-evidence-ladder-v2.json")
    started = time.perf_counter()
    reader = PinnedInventoryReader.from_environment(
        os.environ,
        source_config=source_config,
    )
    inventory = reader.fetch_inventory_once()
    _inventory_pins(selection, inventory.by_id)
    payloads: dict[str, object] = {}
    receipts: dict[str, Mapping[str, Any]] = {}
    for raw in sequence(selection["source_objects"], "E1B_OBJECTS"):
        object_id = str(mapping(raw, "E1B_OBJECT")["object_id"])
        pair = reader.fetch_pair(object_id)
        payloads[object_id] = pair.payload
        receipts[object_id] = pair.receipt.model_dump(mode="json")
    elapsed = round(time.perf_counter() - started, 6)
    telemetry = reader.telemetry.as_dict()
    if (
        reader.telemetry.bootstrap_requested != 1
        or reader.telemetry.evidence_gets != 20
        or reader.telemetry.bootstrap_failed
        or reader.telemetry.receipt_failed
        or reader.telemetry.payload_failed
    ):
        raise RuntimeError("E1B_EXACT_GET_ACCOUNTING_INVALID")
    bytes_read = (
        reader.telemetry.bootstrap_stored_bytes
        + reader.telemetry.receipt_bytes
        + reader.telemetry.payload_stored_bytes
    )
    if bytes_read > int(mission["r2_byte_budget"]):
        raise RuntimeError("E1B_BYTE_BUDGET_EXCEEDED")
    runtime = {
        "duration_seconds": elapsed,
        "github_minutes": "UNKNOWN_NOT_OBSERVED",
        "run_id": os.environ.get("GITHUB_RUN_ID", "LOCAL"),
    }
    args = (mission, selection, contract, payloads, receipts, telemetry, runtime, selection_hash)
    first_values = build_reports(*args)
    second_values = build_reports(*args)
    validate_reports(first_values)
    validate_reports(second_values)
    first = finalize_reports(first_values)
    second = finalize_reports(second_values)
    if first != second:
        raise RuntimeError("E1B_REPLAY_NOT_BYTE_IDENTICAL")
    for name, payload in first.items():
        _write(output / REPORT_FILENAMES[name], payload)


def _validate_output(root: Path, reports_root: Path) -> None:
    selection_hash = _validate(root, True)
    reports = {
        name: read_json(reports_root / filename)
        for name, filename in REPORT_FILENAMES.items()
        if name != "replay_verification"
    }
    validate_reports(reports)
    replay = read_json(reports_root / REPORT_FILENAMES["replay_verification"])
    if replay.get("replay_identical") is not True or replay.get("selection_hash") != selection_hash:
        raise ValueError("E1B_REPLAY_INVALID")
    expected = mapping(replay["all_report_hashes"], "E1B_HASHES")
    for name, value in reports.items():
        payload = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode()
        if expected.get(name) != hashlib.sha256(payload).hexdigest():
            raise ValueError(f"E1B_REPORT_HASH_MISMATCH:{name}")
    costs = mapping(reports["costs"], "E1B_COSTS")
    if costs["logical_gets"] != 21 or costs["objects_read"] != 21:
        raise ValueError("E1B_GET_TOTAL_INVALID")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--require-decision", action="store_true")
    measure = commands.add_parser("measure")
    measure.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("validate-output")
    check.add_argument("--reports-root", type=Path, required=True)
    values = parser.parse_args()
    root = values.root.resolve()
    if values.command == "validate":
        print(f"E1B_SELECTION_VALID:{_validate(root, values.require_decision)}")
    elif values.command == "measure":
        _measure(root, values.output.resolve())
        print("E1B_MEASUREMENT_COMPLETE")
    else:
        _validate_output(root, values.reports_root.resolve())
        print("E1B_OUTPUT_VALID")


if __name__ == "__main__":
    main()
