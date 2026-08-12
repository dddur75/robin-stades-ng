"""Run the bounded exact-key E2 sample without provider, SQL or writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from robin.historical_deep.coverage_evidence import (
    PinnedInventoryReader,
    canonical_journal_suffix,
)
from robin.historical_deep.e2_sample import (
    REPORT_FILENAMES,
    build_reports,
    finalize_reports,
    mapping,
    reconcile_report_summaries,
    render_json,
    sequence,
    validate_reports,
)

ROOT = Path(__file__).resolve().parents[1]
SELECTION = Path("reports/evidence/e2/e2-selection-manifest-v1.json")


def _read(path: Path) -> Mapping[str, Any]:
    return mapping(json.loads(path.read_text(encoding="utf-8")), str(path))


def _safety(environment: Mapping[str, str]) -> None:
    if any(environment.get(name) for name in ("API_FOOTBALL_KEY", "DATABASE_URL", "ODDS_API_KEY")):
        raise RuntimeError("E2_FORBIDDEN_SECRET_MOUNTED")
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
            raise RuntimeError(f"E2_RUNTIME_LOCK_INVALID:{name}")


def _require_ready(root: Path, selection_hash: str) -> None:
    ready = [
        record
        for record in canonical_journal_suffix(root)
        if record.get("record_type") == "DECISION"
        and record.get("decision") == "PASS_AND_SCALE"
        and mapping(record.get("context", {}), "E2_DECISION_CONTEXT").get(
            "selection_state"
        )
        == "E2_SELECTION_READY"
        and mapping(record.get("context", {}), "E2_DECISION_CONTEXT").get(
            "selection_hash"
        )
        == selection_hash
    ]
    if not ready:
        raise RuntimeError("E2_SELECTION_DECISION_MISSING")
    if len(ready) != 1:
        raise RuntimeError("E2_SELECTION_DECISION_NOT_UNIQUE")
    reviewers = set(
        sequence(
            mapping(ready[0]["context"], "E2_DECISION_CONTEXT")["reviewed_by"],
            "E2_REVIEWERS",
        )
    )
    if not {"DP6", "C2", "DP5"} <= reviewers:
        raise RuntimeError("E2_SELECTION_REVIEW_KEYS_MISSING")


def _validate(root: Path, require_decision: bool) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    mission = _read(root / "configs/execution/p0-e2-capability-sample-v1.json")
    selection = _read(root / SELECTION)
    fixtures = [mapping(item, "E2_FIXTURE") for item in sequence(selection["fixtures"], "E2_FIXTURES")]
    if mission.get("stage") != "E2" or selection.get("stage") != "E2":
        raise ValueError("E2_STAGE_INVALID")
    if len(fixtures) != 100 or len({item["fixture_id"] for item in fixtures}) != 100:
        raise ValueError("E2_SCOPE_INVALID")
    if int(mission["r2_get_budget"]) > 300 or int(mission["r2_byte_budget"]) > 50_000_000:
        raise ValueError("E2_BUDGET_INVALID")
    if require_decision:
        _require_ready(root, str(selection["selection_hash"]))
    return mission, selection


def _inventory_pins(selection: Mapping[str, Any], by_id: Mapping[str, object]) -> None:
    fields = {
        "payload_key": "allowed_payload_key",
        "payload_sha256": "payload_hash",
        "logical_bytes": "logical_bytes",
        "stored_bytes": "stored_bytes",
        "receipt_key": "allowed_receipt_key",
        "receipt_hash": "receipt_hash",
        "task_id": "task_id",
    }
    for raw in sequence(selection["fixtures"], "E2_FIXTURES"):
        selected = mapping(raw, "E2_FIXTURE")
        entry = by_id.get(str(selected["object_id"]))
        if entry is None:
            raise ValueError("E2_OBJECT_NOT_IN_INVENTORY")
        if any(getattr(entry, field) != selected[target] for field, target in fields.items()):
            raise ValueError(f"E2_OBJECT_PIN_MISMATCH:{selected['fixture_id']}")


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _measure(root: Path, output: Path) -> None:
    _safety(os.environ)
    mission, selection = _validate(root, True)
    source_config = _read(root / "configs/data/p0-coverage-source-config-v1.json")
    e1b = _read(root / "reports/evidence/e1b/e1b-measurement-v1.json")
    started = time.perf_counter()
    reader = PinnedInventoryReader.from_environment(os.environ, source_config=source_config)
    inventory = reader.fetch_inventory_once()
    _inventory_pins(selection, inventory.by_id)
    payloads: dict[int, object] = {}
    receipts: dict[int, Mapping[str, Any]] = {}
    for raw in sequence(selection["fixtures"], "E2_FIXTURES"):
        fixture = mapping(raw, "E2_FIXTURE")
        fixture_id = int(fixture["fixture_id"])
        pair = reader.fetch_pair(str(fixture["object_id"]))
        payloads[fixture_id] = pair.payload
        receipts[fixture_id] = pair.receipt.model_dump(mode="json")
    elapsed = round(time.perf_counter() - started, 6)
    telemetry = reader.telemetry
    logical_gets = telemetry.bootstrap_requested + telemetry.evidence_gets
    network_bytes = telemetry.bootstrap_stored_bytes + telemetry.receipt_bytes + telemetry.payload_stored_bytes
    if logical_gets > int(mission["r2_get_budget"]):
        raise RuntimeError("E2_GET_BUDGET_EXCEEDED")
    if network_bytes > int(mission["r2_byte_budget"]):
        raise RuntimeError("E2_BYTE_BUDGET_EXCEEDED")
    if telemetry.bootstrap_requested != 1 or telemetry.receipt_failed or telemetry.payload_failed:
        raise RuntimeError("E2_EXACT_GET_ACCOUNTING_INVALID")
    flat_telemetry = {
        "bootstrap_requested": telemetry.bootstrap_requested,
        "logical_gets": logical_gets,
        "network_bytes": network_bytes,
        "payload_requested": telemetry.payload_requested,
        "receipt_requested": telemetry.receipt_requested,
    }
    runtime = {"duration_seconds": elapsed, "github_minutes": "UNKNOWN_NOT_OBSERVED", "run_id": os.environ.get("GITHUB_RUN_ID", "LOCAL")}
    first_values = build_reports(selection, e1b, payloads, receipts, flat_telemetry, runtime)
    second_values = build_reports(selection, e1b, payloads, receipts, flat_telemetry, runtime)
    validate_reports(first_values)
    validate_reports(second_values)
    first = finalize_reports(first_values)
    second = finalize_reports(second_values)
    if first != second:
        raise RuntimeError("E2_REPLAY_NOT_BYTE_IDENTICAL")
    for name, payload in first.items():
        _write(output / REPORT_FILENAMES[name], payload)


def _validate_output(root: Path, reports_root: Path) -> None:
    _, selection = _validate(root, True)
    reports = {
        name: _read(reports_root / filename)
        for name, filename in REPORT_FILENAMES.items()
        if name != "replay_verification"
    }
    validate_reports(reports)
    replay = _read(reports_root / REPORT_FILENAMES["replay_verification"])
    if replay.get("replay_identical") is not True or replay.get("selection_hash") != selection["selection_hash"]:
        raise ValueError("E2_REPLAY_INVALID")
    hashes = mapping(replay["all_report_hashes"], "E2_REPORT_HASHES")
    for name, report in reports.items():
        if hashes.get(name) != hashlib.sha256(render_json(report)).hexdigest():
            raise ValueError(f"E2_REPORT_HASH_MISMATCH:{name}")


def _reconcile_output(root: Path, reports_root: Path, output: Path) -> None:
    _validate(root, True)
    reports = {
        name: _read(reports_root / filename)
        for name, filename in REPORT_FILENAMES.items()
        if name != "replay_verification"
    }
    corrected = reconcile_report_summaries(reports)
    validate_reports(corrected)
    for name, payload in finalize_reports(corrected).items():
        _write(output / REPORT_FILENAMES[name], payload)


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
    reconcile = commands.add_parser("reconcile-output")
    reconcile.add_argument("--reports-root", type=Path, required=True)
    reconcile.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "validate":
        _validate(root, args.require_decision)
        print("E2_SELECTION_VALID")
    elif args.command == "measure":
        _measure(root, args.output.resolve())
        print("E2_MEASUREMENT_COMPLETE")
    elif args.command == "validate-output":
        _validate_output(root, args.reports_root.resolve())
        print("E2_OUTPUT_VALID")
    else:
        _reconcile_output(root, args.reports_root.resolve(), args.output.resolve())
        print("E2_OUTPUT_RECONCILED")


if __name__ == "__main__":
    main()
