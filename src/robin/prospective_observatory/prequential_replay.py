"""Deterministic provider-free replay of the prequential SQL projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, cast

from robin.prospective_observatory.contracts import canonical_sha256


@dataclass(frozen=True, slots=True)
class PrequentialReplayResult:
    status: str
    dataset_hash: str
    feature_snapshots: int
    model_versions: int
    predictions: int
    settlements: int
    scores: int
    metric_snapshots: int
    training_runs: int
    ledger_events: int
    ledger_head_hash: str
    provider_calls: int = 0


def _rows(
    value: Mapping[str, Iterable[Mapping[str, object]]],
    table: str,
) -> tuple[dict[str, object], ...]:
    rows = tuple(dict(row) for row in value.get(table, ()))
    if table == "prequential_ledger_events":
        return tuple(
            sorted(
                rows,
                key=lambda row: int(cast(str | int, row["sequence_no"])),
            )
        )
    return tuple(sorted(rows, key=lambda row: str(row["id"])))


def _verify_ledger(events: tuple[dict[str, object], ...]) -> str:
    previous_hash = "0" * 64
    for sequence, event in enumerate(events):
        sequence_no = int(cast(str | int, event["sequence_no"]))
        if sequence_no != sequence:
            raise ValueError("PREQUENTIAL_REPLAY_LEDGER_SEQUENCE_INVALID")
        if str(event["previous_hash"]) != previous_hash:
            raise ValueError("PREQUENTIAL_REPLAY_LEDGER_CHAIN_INVALID")
        body = {
            "event_id": event["event_id"],
            "sequence_no": sequence_no,
            "kind": event["kind"],
            "recorded_at": str(event["recorded_at"]),
            "stream_key": event["stream_key"],
            "fixture_id": event.get("fixture_id"),
            "model_id": event.get("model_id"),
            "model_version": event.get("model_version"),
            "evidence_hashes": event["evidence_hashes"],
            "details": event["details"],
            "previous_hash": event["previous_hash"],
            "production_status": event["production_status"],
            "real_bets": bool(event["real_bets"]),
            "promoted": bool(event["promoted"]),
        }
        record_hash = canonical_sha256(body)
        if (
            record_hash != str(event["record_hash"])
            or str(event["production_status"]) != "PRODUCTION_LOCKED"
            or bool(event["real_bets"])
            or bool(event["promoted"])
        ):
            raise ValueError("PREQUENTIAL_REPLAY_LEDGER_HASH_INVALID")
        previous_hash = record_hash
    return previous_hash


def _verify_temporal(rows: Mapping[str, tuple[dict[str, object], ...]]) -> None:
    for prediction in rows["prequential_predictions"]:
        if str(prediction["status"]) != "FROZEN":
            continue
        predicted = datetime.fromisoformat(str(prediction["predicted_at"]))
        cutoff = datetime.fromisoformat(str(prediction["cutoff_at"]))
        kickoff = datetime.fromisoformat(str(prediction["kickoff_at"]))
        if not predicted <= cutoff < kickoff:
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_LEAKAGE")
    settlements = {
        str(row["settlement_id"]): row
        for row in rows["prequential_fixture_settlements"]
    }
    for run in rows["prequential_training_runs"]:
        cutoff = datetime.fromisoformat(str(run["training_cutoff"]))
        settlement_ids = run.get("settlement_ids", [])
        if not isinstance(settlement_ids, list):
            raise ValueError("PREQUENTIAL_REPLAY_TRAINING_MANIFEST_INVALID")
        for settlement_id in settlement_ids:
            settlement = settlements.get(str(settlement_id))
            if settlement is None:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_SETTLEMENT_MISSING"
                )
            settled_at = datetime.fromisoformat(str(settlement["settled_at"]))
            if settled_at >= cutoff:
                raise ValueError("PREQUENTIAL_REPLAY_TRAINING_LEAKAGE")


def replay_prequential_rows(
    value: Mapping[str, Iterable[Mapping[str, object]]],
) -> PrequentialReplayResult:
    table_names = (
        "prequential_feature_snapshots",
        "prequential_model_versions",
        "prequential_predictions",
        "prequential_fixture_settlements",
        "prequential_prediction_scores",
        "prequential_metric_snapshots",
        "prequential_training_runs",
        "prequential_ledger_events",
    )
    rows = {table: _rows(value, table) for table in table_names}
    _verify_temporal(rows)
    head_hash = _verify_ledger(rows["prequential_ledger_events"])
    canonical_rows = {
        table: list(table_rows)
        for table, table_rows in rows.items()
    }
    return PrequentialReplayResult(
        status="PREQUENTIAL_REPLAY_IDENTICAL",
        dataset_hash=canonical_sha256(canonical_rows),
        feature_snapshots=len(rows["prequential_feature_snapshots"]),
        model_versions=len(rows["prequential_model_versions"]),
        predictions=len(rows["prequential_predictions"]),
        settlements=len(rows["prequential_fixture_settlements"]),
        scores=len(rows["prequential_prediction_scores"]),
        metric_snapshots=len(rows["prequential_metric_snapshots"]),
        training_runs=len(rows["prequential_training_runs"]),
        ledger_events=len(rows["prequential_ledger_events"]),
        ledger_head_hash=head_hash,
    )


__all__ = ["PrequentialReplayResult", "replay_prequential_rows"]
