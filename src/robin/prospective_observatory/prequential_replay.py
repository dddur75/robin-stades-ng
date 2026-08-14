"""Deterministic provider-free replay of the prequential SQL projections."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, cast

from robin.market_math import devig_probabilities as kernel_devig_probabilities
from robin.market_math import kernel_versions
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    FeatureSnapshotRegistry,
    feature_snapshot_record_id,
)
from robin.prospective_observatory.prequential_contracts import (
    CutoffName,
    FeatureSnapshot,
    FixtureResultStatus,
    FixtureSettlementRecord,
    FrozenPredictionRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionScore,
    PredictionStatus,
    VerifiedFixtureResult,
    complete_injuries_feature,
    complete_lineup_feature,
    durable_required_feature_gates,
    feature_fixture_kickoff,
    feature_team_ids,
    prediction_record_id,
    score_record_id,
    settlement_record_id,
)
from robin.prospective_observatory.prequential_metrics import (
    score_prediction,
    segmented_metrics,
)
from robin.prospective_observatory.prequential_settlement import (
    SettlementRegistry,
)


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


def _timestamp(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_UTC_REQUIRED")
    return parsed


def _snapshot_hash_payload(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "fixture_record_id": snapshot["fixture_record_id"],
        "fixture_id": snapshot["fixture_id"],
        "competition": snapshot["competition"],
        "market": snapshot["market"],
        "cutoff_name": snapshot["cutoff_name"],
        "cutoff_at": snapshot["cutoff_at"],
        "created_at": snapshot["created_at"],
        "feature_contract_version": snapshot["feature_contract_version"],
        "feature_contract_hash": snapshot["feature_contract_hash"],
        "values": snapshot["values"],
        "missingness": snapshot["missingness"],
        "provenance": snapshot["provenance"],
        "quality": snapshot["quality"],
        "code_revision": snapshot["code_revision"],
        "supersedes_id": snapshot.get("supersedes_id"),
        "status": snapshot["status"],
    }


def _float_mapping(value: object, *, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_INVALID")
    output: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_INVALID")
        output[str(key)] = float(item)
    return output


def _optional_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_INVALID")
    return float(value)


def _verify_record_hashes(
    rows: Mapping[str, tuple[dict[str, object], ...]],
) -> tuple[
    dict[tuple[str, str], ModelVersion],
    dict[str, FrozenPredictionRecord],
    dict[str, FixtureSettlementRecord],
    dict[str, PredictionScore],
]:
    model_rows_by_id: dict[str, dict[str, object]] = {}
    model_objects: dict[tuple[str, str], ModelVersion] = {}
    for row in rows["prequential_model_versions"]:
        row_id = str(row["id"])
        if row_id in model_rows_by_id:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_VERSION_DUPLICATE")
        model_rows_by_id[row_id] = row
    for row_id, row in model_rows_by_id.items():
        parent_id = row.get("parent_version_id")
        parent_version: str | None = None
        if parent_id is not None:
            parent = model_rows_by_id.get(str(parent_id))
            if parent is None:
                raise ValueError("PREQUENTIAL_REPLAY_PARENT_MODEL_MISSING")
            if str(parent["model_id"]) != str(row["model_id"]):
                raise ValueError("PREQUENTIAL_REPLAY_PARENT_MODEL_MISMATCH")
            parent_version = str(parent["model_version"])
        try:
            model = ModelVersion(
                model_id=str(row["model_id"]),
                scope=ModelScope(str(row["scope"])),
                role=ModelRole(str(row["role"])),
                version=str(row["model_version"]),
                artifact_sha256=str(row["artifact_sha256"]),
                created_at=_timestamp(row["created_at"], field="model_created_at"),
                training_cutoff=(
                    _timestamp(
                        row["training_cutoff"],
                        field="model_training_cutoff",
                    )
                    if row.get("training_cutoff") is not None
                    else None
                ),
                feature_contract_hash=str(row["feature_contract_hash"]),
                code_revision=str(row["code_revision"]),
                status=ModelStatus(str(row["status"])),
                artifact_r2_key=(
                    str(row["artifact_r2_key"])
                    if row.get("artifact_r2_key") is not None
                    else None
                ),
                parent_version=parent_version,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_PAYLOAD_INVALID") from error
        if str(row.get("registry_hash", "")) != model.registry_hash:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_REGISTRY_HASH_INVALID")
        if row_id != f"model-{model.registry_hash}":
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_ROW_ID_INVALID")
        model_objects[(model.model_id, model.version)] = model

    prediction_ids: set[str] = set()
    prediction_objects: dict[str, FrozenPredictionRecord] = {}
    for row in rows["prequential_predictions"]:
        prediction_id = str(row["prediction_id"])
        if prediction_id in prediction_ids:
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_DUPLICATE")
        prediction_ids.add(prediction_id)
        market_probabilities_raw = row.get("market_probabilities")
        try:
            prediction = FrozenPredictionRecord(
                prediction_id=prediction_id,
                fixture_record_id=str(row["fixture_record_id"]),
                fixture_id=str(row["fixture_id"]),
                competition=str(row["competition"]),
                market=PredictionMarket(str(row["market"])),
                cutoff_name=CutoffName(str(row["cutoff_name"])),
                cutoff_at=_timestamp(row["cutoff_at"], field="prediction_cutoff_at"),
                kickoff_at=_timestamp(
                    row["kickoff_at"],
                    field="prediction_kickoff_at",
                ),
                predicted_at=_timestamp(
                    row["predicted_at"],
                    field="prediction_predicted_at",
                ),
                model_id=str(row["model_id"]),
                model_version=str(row["model_version"]),
                feature_snapshot_id=(
                    str(row["feature_snapshot_id"])
                    if row.get("feature_snapshot_id") is not None
                    else None
                ),
                probabilities=_float_mapping(
                    row["probabilities"],
                    field="prediction_probabilities",
                ),
                market_probabilities=(
                    _float_mapping(
                        market_probabilities_raw,
                        field="prediction_market_probabilities",
                    )
                    if market_probabilities_raw is not None
                    else None
                ),
                odds_snapshot_id=(
                    str(row["odds_snapshot_id"])
                    if row.get("odds_snapshot_id") is not None
                    else None
                ),
                code_revision=str(row["code_revision"]),
                status=PredictionStatus(str(row["status"])),
                rejection_reason=(
                    str(row["rejection_reason"])
                    if row.get("rejection_reason") is not None
                    else None
                ),
                **kernel_versions("PROPORTIONAL"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_PAYLOAD_INVALID") from error
        persisted_payload_hash = str(row.get("payload_hash", ""))
        if persisted_payload_hash != prediction.computed_payload_hash:
            if persisted_payload_hash == prediction.legacy_payload_hash:
                # The legacy identity intentionally omits the scientific
                # kernel lineage fields.  It remains readable for explicit
                # compatibility/invalidation workflows, but it cannot support
                # an exact causal replay verdict.
                raise ValueError(
                    "PREQUENTIAL_REPLAY_PREDICTION_SCIENTIFIC_LINEAGE_UNPROVEN"
                )
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_HASH_INVALID")
        if (
            prediction_id
            != prediction_record_id(
                fixture_record_id=prediction.fixture_record_id,
                cutoff_name=prediction.cutoff_name,
                market=prediction.market,
                model_id=prediction.model_id,
                model_version=prediction.model_version,
            )
            or str(row.get("id", "")) != prediction_id
        ):
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_ID_INVALID")
        prediction_objects[prediction_id] = prediction

    settlement_ids: set[str] = set()
    settlement_objects: dict[str, FixtureSettlementRecord] = {}
    for row in rows["prequential_fixture_settlements"]:
        settlement_id = str(row["settlement_id"])
        if settlement_id in settlement_ids:
            raise ValueError("PREQUENTIAL_REPLAY_SETTLEMENT_DUPLICATE")
        settlement_ids.add(settlement_id)
        try:
            result = VerifiedFixtureResult(
                fixture_record_id=str(row["fixture_record_id"]),
                fixture_id=str(row["fixture_id"]),
                competition=str(row["competition"]),
                kickoff_at=_timestamp(
                    row["kickoff_at"],
                    field="settlement_kickoff_at",
                ),
                status=FixtureResultStatus(str(row["result_status"])),
                verified_at=_timestamp(
                    row["verified_at"],
                    field="settlement_verified_at",
                ),
                home_goals=(
                    int(cast(int | str, row["home_goals"]))
                    if row.get("home_goals") is not None
                    else None
                ),
                away_goals=(
                    int(cast(int | str, row["away_goals"]))
                    if row.get("away_goals") is not None
                    else None
                ),
                result_version=int(cast(int | str, row["result_version"])),
                source_hash=str(row["source_hash"]),
            )
            settlement = FixtureSettlementRecord(
                settlement_id=settlement_id,
                result=result,
                settled_at=_timestamp(
                    row["settled_at"],
                    field="settlement_settled_at",
                ),
                effective_status=PredictionStatus(str(row["effective_status"])),
                supersedes_id=(
                    str(row["supersedes_id"])
                    if row.get("supersedes_id") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_SETTLEMENT_PAYLOAD_INVALID") from error
        if str(row.get("result_hash", "")) != result.result_hash:
            raise ValueError("PREQUENTIAL_REPLAY_RESULT_HASH_INVALID")
        if str(row.get("settlement_hash", "")) != settlement.settlement_hash:
            raise ValueError("PREQUENTIAL_REPLAY_SETTLEMENT_HASH_INVALID")
        if (
            settlement_id
            != settlement_record_id(
                settlement.result,
                supersedes_id=settlement.supersedes_id,
            )
            or str(row.get("id", "")) != settlement_id
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SETTLEMENT_ID_INVALID")
        settlement_objects[settlement_id] = settlement

    score_ids: set[str] = set()
    score_objects: dict[str, PredictionScore] = {}
    for row in rows["prequential_prediction_scores"]:
        score_id = str(row["score_id"])
        if score_id in score_ids:
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_DUPLICATE")
        score_ids.add(score_id)
        accurate = row.get("accurate")
        if not isinstance(accurate, bool):
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_ACCURATE_INVALID")
        try:
            score = PredictionScore(
                score_id=score_id,
                prediction_id=str(row["prediction_id"]),
                settlement_id=str(row["settlement_id"]),
                fixture_id=str(row["fixture_id"]),
                competition=str(row["competition"]),
                market=PredictionMarket(str(row["market"])),
                cutoff_name=CutoffName(str(row["cutoff_name"])),
                model_id=str(row["model_id"]),
                model_version=str(row["model_version"]),
                scored_at=_timestamp(row["scored_at"], field="score_scored_at"),
                outcome=str(row["outcome"]),
                log_loss=float(cast(int | float | str, row["log_loss"])),
                brier_score=float(cast(int | float | str, row["brier_score"])),
                accurate=accurate,
                reference_log_loss_delta=_optional_float(
                    row.get("reference_log_loss_delta"),
                    field="score_reference_log_loss_delta",
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_PAYLOAD_INVALID") from error
        if str(row.get("score_hash", "")) != score.score_hash:
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_HASH_INVALID")
        if (
            score_id
            != score_record_id(
                prediction_id=score.prediction_id,
                settlement_id=score.settlement_id,
            )
            or str(row.get("id", "")) != score_id
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_ID_INVALID")
        score_objects[score_id] = score

    metric_ids: set[str] = set()
    for row in rows["prequential_metric_snapshots"]:
        metric_id = str(row["metric_snapshot_id"])
        if metric_id in metric_ids:
            raise ValueError("PREQUENTIAL_REPLAY_METRIC_DUPLICATE")
        metric_ids.add(metric_id)
        try:
            measured_at = _timestamp(
                row["measured_at"],
                field="metric_measured_at",
            )
            metrics = {
                "support": int(cast(int | str, row["support"])),
                "log_loss": _optional_float(
                    row.get("log_loss"),
                    field="metric_log_loss",
                ),
                "brier_score": _optional_float(
                    row.get("brier_score"),
                    field="metric_brier_score",
                ),
                "calibration_error": _optional_float(
                    row.get("calibration_error"),
                    field="metric_calibration_error",
                ),
                "accuracy_descriptive": _optional_float(
                    row.get("accuracy_descriptive"),
                    field="metric_accuracy_descriptive",
                ),
                "coverage": float(cast(int | float | str, row["coverage"])),
                "missingness": _optional_float(
                    row.get("missingness"),
                    field="metric_missingness",
                ),
                "reference_log_loss_delta": _optional_float(
                    row.get("reference_log_loss_delta"),
                    field="metric_reference_log_loss_delta",
                ),
            }
            payload = {
                "competition": str(row["competition"]),
                "market": str(row["market"]),
                "cutoff": str(row["cutoff_name"]),
                "model_id": str(row["model_id"]),
                "model_version": str(row["model_version"]),
                "month": str(row["month"]),
                "measured_at": measured_at.isoformat(),
                "metrics": metrics,
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_METRIC_PAYLOAD_INVALID") from error
        metric_hash = canonical_sha256(payload)
        if str(row.get("metric_hash", "")) != metric_hash:
            raise ValueError("PREQUENTIAL_REPLAY_METRIC_HASH_INVALID")
        if metric_id != f"metric-{metric_hash}" or str(row["id"]) != metric_id:
            raise ValueError("PREQUENTIAL_REPLAY_METRIC_ROW_ID_INVALID")
    return (
        model_objects,
        prediction_objects,
        settlement_objects,
        score_objects,
    )


def _verify_lineage(
    rows: Mapping[str, tuple[dict[str, object], ...]],
    *,
    model_objects: Mapping[tuple[str, str], ModelVersion],
    prediction_objects: Mapping[str, FrozenPredictionRecord],
    settlement_objects: Mapping[str, FixtureSettlementRecord],
    score_objects: Mapping[str, PredictionScore],
) -> None:
    ledger_events = rows["prequential_ledger_events"]
    durable_rows_present = any(
        rows[table]
        for table in (
            "prequential_feature_snapshots",
            "prequential_predictions",
            "prequential_fixture_settlements",
            "prequential_prediction_scores",
        )
    )
    if durable_rows_present and not ledger_events:
        raise ValueError("PREQUENTIAL_REPLAY_LEDGER_EVIDENCE_MISSING")

    def require_ledger_evidence(
        *,
        kind: str,
        evidence_hash: str,
        fixture_id: str,
        model_id: str | None = None,
        model_version: str | None = None,
    ) -> None:
        matches = tuple(
            event
            for event in ledger_events
            if str(event.get("kind")) == kind
            and str(event.get("fixture_id")) == fixture_id
            and (model_id is None or str(event.get("model_id")) == model_id)
            and (
                model_version is None
                or str(event.get("model_version")) == model_version
            )
            and isinstance(event.get("evidence_hashes"), list)
            and evidence_hash in cast(list[object], event["evidence_hashes"])
        )
        if len(matches) != 1:
            raise ValueError("PREQUENTIAL_REPLAY_LEDGER_EVIDENCE_MISMATCH")

    models: dict[tuple[str, str], dict[str, object]] = {}
    for model in rows["prequential_model_versions"]:
        key = (str(model["model_id"]), str(model["model_version"]))
        if key in models:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_VERSION_DUPLICATE")
        models[key] = model

    snapshots: dict[str, dict[str, object]] = {}
    snapshot_objects: list[FeatureSnapshot] = []
    for snapshot in rows["prequential_feature_snapshots"]:
        snapshot_id = str(snapshot["snapshot_id"])
        if snapshot_id in snapshots:
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_DUPLICATE")
        if canonical_sha256(_snapshot_hash_payload(snapshot)) != str(
            snapshot["snapshot_hash"]
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_HASH_INVALID")
        values = snapshot.get("values")
        missingness = snapshot.get("missingness")
        provenance = snapshot.get("provenance")
        quality = snapshot.get("quality")
        if not all(
            isinstance(value, Mapping)
            for value in (values, missingness, provenance, quality)
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_SHAPE_INVALID")
        expected_snapshot_id = feature_snapshot_record_id(
            fixture_record_id=str(snapshot["fixture_record_id"]),
            fixture_id=str(snapshot["fixture_id"]),
            market=PredictionMarket(str(snapshot["market"])),
            cutoff_name=CutoffName(str(snapshot["cutoff_name"])),
            cutoff_at=_timestamp(
                snapshot["cutoff_at"],
                field="snapshot_cutoff_at",
            ),
            feature_contract_version=str(snapshot["feature_contract_version"]),
            feature_contract_hash=str(snapshot["feature_contract_hash"]),
            values=cast(Mapping[str, object], values),
            missingness=cast(Mapping[str, bool], missingness),
            provenance=cast(Mapping[str, object], provenance),
            quality=cast(Mapping[str, object], quality),
            supersedes_id=(
                str(snapshot["supersedes_id"])
                if snapshot.get("supersedes_id") is not None
                else None
            ),
        )
        if (
            snapshot_id != expected_snapshot_id
            or str(snapshot.get("id", "")) != snapshot_id
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_ID_INVALID")
        try:
            snapshot_objects.append(
                FeatureSnapshot(
                    snapshot_id=snapshot_id,
                    fixture_record_id=str(snapshot["fixture_record_id"]),
                    fixture_id=str(snapshot["fixture_id"]),
                    competition=str(snapshot["competition"]),
                    market=PredictionMarket(str(snapshot["market"])),
                    cutoff_name=CutoffName(str(snapshot["cutoff_name"])),
                    cutoff_at=_timestamp(
                        snapshot["cutoff_at"],
                        field="snapshot_cutoff_at",
                    ),
                    created_at=_timestamp(
                        snapshot["created_at"],
                        field="snapshot_created_at",
                    ),
                    feature_contract_version=str(
                        snapshot["feature_contract_version"]
                    ),
                    feature_contract_hash=str(snapshot["feature_contract_hash"]),
                    values=dict(cast(Mapping[str, object], values)),
                    missingness=dict(cast(Mapping[str, bool], missingness)),
                    provenance={
                        str(key): dict(value)
                        for key, value in cast(
                            Mapping[str, object], provenance
                        ).items()
                        if isinstance(value, Mapping)
                    },
                    quality=dict(cast(Mapping[str, object], quality)),
                    code_revision=str(snapshot["code_revision"]),
                    r2_manifest_key=str(snapshot["r2_manifest_key"]),
                    supersedes_id=(
                        str(snapshot["supersedes_id"])
                        if snapshot.get("supersedes_id") is not None
                        else None
                    ),
                    status=str(snapshot["status"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_PAYLOAD_INVALID"
            ) from error
        if _timestamp(snapshot["created_at"], field="snapshot_created_at") > _timestamp(
            snapshot["cutoff_at"],
            field="snapshot_cutoff_at",
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_LEAKAGE")
        snapshots[snapshot_id] = snapshot
        require_ledger_evidence(
            kind="FEATURE_SNAPSHOT_FROZEN",
            evidence_hash=str(snapshot["snapshot_hash"]),
            fixture_id=str(snapshot["fixture_id"]),
        )

    snapshot_registry = FeatureSnapshotRegistry()
    pending_snapshots = list(snapshot_objects)
    while pending_snapshots:
        progressed = False
        for candidate in sorted(
            tuple(pending_snapshots),
            key=lambda value: (value.created_at, value.snapshot_id),
        ):
            if (
                candidate.supersedes_id is not None
                and snapshot_registry.get(candidate.supersedes_id) is None
            ):
                continue
            try:
                snapshot_registry.append(candidate)
            except ValueError as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_CHAIN_INVALID"
                ) from error
            pending_snapshots.remove(candidate)
            progressed = True
        if not progressed:
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_CHAIN_INVALID")

    settlement_registry = SettlementRegistry()
    scores_by_settlement: dict[str, list[PredictionScore]] = {}
    for score in score_objects.values():
        scores_by_settlement.setdefault(score.settlement_id, []).append(score)
    for settlement in sorted(
        settlement_objects.values(),
        key=lambda value: (
            value.result.fixture_record_id,
            value.result.result_version,
            value.settled_at,
            value.settlement_id,
        ),
    ):
        settlement_registry.restore(
            settlement,
            tuple(scores_by_settlement.get(settlement.settlement_id, ())),
        )

    frozen_by_record: dict[str, list[dict[str, object]]] = {}
    predictions = {
        str(prediction["prediction_id"]): prediction
        for prediction in rows["prequential_predictions"]
    }
    for prediction in rows["prequential_predictions"]:
        require_ledger_evidence(
            kind=(
                "PREDICTION_FROZEN"
                if str(prediction["status"]) == "FROZEN"
                else "PREDICTION_REJECTED"
            ),
            evidence_hash=str(prediction["payload_hash"]),
            fixture_id=str(prediction["fixture_id"]),
            model_id=str(prediction["model_id"]),
            model_version=str(prediction["model_version"]),
        )
        if str(prediction["status"]) != "FROZEN":
            continue
        selected_model = models.get(
            (str(prediction["model_id"]), str(prediction["model_version"]))
        )
        if selected_model is None:
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_MODEL_MISSING")
        if str(prediction.get("model_version_id")) != str(selected_model["id"]):
            raise ValueError("PREQUENTIAL_REPLAY_PREDICTION_MODEL_EDGE_MISMATCH")
        predicted_at = _timestamp(
            prediction["predicted_at"],
            field="prediction_predicted_at",
        )
        if _timestamp(
            selected_model["created_at"],
            field="model_created_at",
        ) > predicted_at:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_AFTER_PREDICTION")
        training_cutoff = selected_model.get("training_cutoff")
        if training_cutoff is not None and _timestamp(
            training_cutoff,
            field="model_training_cutoff",
        ) > predicted_at:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_TRAINING_AFTER_PREDICTION")
        selected_snapshot = snapshots.get(
            str(prediction.get("feature_snapshot_id"))
        )
        if selected_snapshot is None:
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_MISSING")
        if _timestamp(
            selected_snapshot["created_at"],
            field="snapshot_created_at",
        ) > predicted_at:
            raise ValueError(
                "PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_AFTER_PREDICTION"
            )
        exact_fields = (
            "fixture_record_id",
            "fixture_id",
            "competition",
            "market",
            "cutoff_name",
        )
        if any(
            str(selected_snapshot[field]) != str(prediction[field])
            for field in exact_fields
        ) or _timestamp(
            selected_snapshot["cutoff_at"],
            field="snapshot_cutoff_at",
        ) != _timestamp(
            prediction["cutoff_at"],
            field="prediction_cutoff_at",
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_LINEAGE_MISMATCH")
        if str(selected_model["feature_contract_hash"]) != str(
            selected_snapshot["feature_contract_hash"]
        ):
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_CONTRACT_MISMATCH")
        snapshot_values = selected_snapshot.get("values")
        snapshot_missingness = selected_snapshot.get("missingness")
        snapshot_provenance = selected_snapshot.get("provenance")
        if (
            not isinstance(snapshot_values, Mapping)
            or not isinstance(snapshot_missingness, Mapping)
            or not isinstance(snapshot_provenance, Mapping)
        ):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_LINEAGE_MISSING")
        team_values = snapshot_values.get("team")
        if (
            snapshot_missingness.get("team") is not False
            or not isinstance(team_values, Mapping)
            or feature_team_ids(team_values) is None
            or feature_fixture_kickoff(team_values)
            != _timestamp(
                prediction["kickoff_at"],
                field="prediction_kickoff_at",
            )
            or team_values.get("competition") != prediction.get("competition")
            or not str(team_values.get("provider", "")).strip()
            or not str(team_values.get("provider_fixture_id", "")).strip()
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_FIXTURE_PROJECTION_MISMATCH"
            )
        snapshot_quality = selected_snapshot.get("quality")
        try:
            optional_gates = durable_required_feature_gates(snapshot_quality)
        except ValueError as error:
            raise ValueError(
                "PREQUENTIAL_REPLAY_REQUIRED_GATE_CONTRACT_INVALID"
            ) from error
        for gate in optional_gates:
            if snapshot_missingness.get(gate) is not False:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_REQUIRED_GATE_PROJECTION_MISSING"
                )
            value = snapshot_values.get(gate)
            valid = (
                complete_injuries_feature(value)
                if gate == "injuries"
                else complete_lineup_feature(
                    value,
                    expected_team_ids=feature_team_ids(team_values) or ("", ""),
                )
            )
            if not valid:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_REQUIRED_GATE_PROJECTION_INVALID"
                )
        market_values = snapshot_values.get("market")
        market_provenance = snapshot_provenance.get("market")
        if not isinstance(market_values, Mapping) or not isinstance(
            market_provenance, Mapping
        ):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_LINEAGE_MISSING")
        if str(prediction.get("odds_snapshot_id")) != str(
            market_provenance.get("odds_snapshot_id")
        ):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_SNAPSHOT_EDGE_MISMATCH")
        decimal_odds = market_values.get("decimal_odds")
        if not isinstance(decimal_odds, Mapping):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_VALUES_MISSING")
        expected_labels = (
            ("HOME", "DRAW", "AWAY")
            if str(prediction["market"]) == PredictionMarket.ONE_X_TWO.value
            else ("OVER", "UNDER")
        )
        if set(decimal_odds) != set(expected_labels):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_VALUES_MISMATCH")
        try:
            devig = kernel_devig_probabilities(
                [decimal_odds[label] for label in expected_labels],
                method="PROPORTIONAL",
                outcome_labels=expected_labels,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_VALUES_MISMATCH") from error
        prediction_object = prediction_objects[str(prediction["prediction_id"])]
        expected_market_probabilities = dict(
            zip(expected_labels, devig.fair_probabilities, strict=True)
        )
        if prediction_object.market_probabilities is None or any(
            not math.isclose(
                prediction_object.market_probabilities.get(label, math.nan),
                expected_probability,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            for label, expected_probability in expected_market_probabilities.items()
        ):
            raise ValueError("PREQUENTIAL_REPLAY_ODDS_PROBABILITY_MISMATCH")
        selected_model_object = model_objects[
            (prediction_object.model_id, prediction_object.model_version)
        ]
        if (
            selected_model_object.role is ModelRole.REFERENCE
            and prediction_object.probabilities
            != prediction_object.market_probabilities
        ):
            raise ValueError("PREQUENTIAL_REPLAY_REFERENCE_PROBABILITY_MISMATCH")
        frozen_by_record.setdefault(
            str(prediction["fixture_record_id"]),
            [],
        ).append(prediction)

    settlements = {
        str(settlement_row["settlement_id"]): settlement_row
        for settlement_row in rows["prequential_fixture_settlements"]
    }
    for settlement_row in rows["prequential_fixture_settlements"]:
        require_ledger_evidence(
            kind="FIXTURE_SETTLED",
            evidence_hash=str(settlement_row["settlement_hash"]),
            fixture_id=str(settlement_row["fixture_id"]),
        )
        matching = frozen_by_record.get(
            str(settlement_row["fixture_record_id"]),
            [],
        )
        if not matching or any(
            str(prediction["fixture_id"]) != str(settlement_row["fixture_id"])
            or str(prediction["competition"])
            != str(settlement_row["competition"])
            or _timestamp(
                prediction["kickoff_at"],
                field="prediction_kickoff_at",
            )
            != _timestamp(
                settlement_row["kickoff_at"],
                field="settlement_kickoff_at",
            )
            for prediction in matching
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SETTLEMENT_PREDICTION_MISSING")
    for score_row in rows["prequential_prediction_scores"]:
        require_ledger_evidence(
            kind="PREDICTION_SCORED",
            evidence_hash=str(score_row["score_hash"]),
            fixture_id=str(score_row["fixture_id"]),
            model_id=str(score_row["model_id"]),
            model_version=str(score_row["model_version"]),
        )
        score_prediction_row = predictions.get(str(score_row["prediction_id"]))
        score_settlement = settlements.get(str(score_row["settlement_id"]))
        if score_prediction_row is None or score_settlement is None:
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_LINEAGE_MISSING")
        if str(score_prediction_row["fixture_record_id"]) != str(
            score_settlement["fixture_record_id"]
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_LINEAGE_MISMATCH")
        exact_score_fields = (
            "fixture_id",
            "competition",
            "market",
            "cutoff_name",
            "model_id",
            "model_version",
        )
        if any(
            str(score_row[field]) != str(score_prediction_row[field])
            for field in exact_score_fields
        ) or any(
            str(score_row[field]) != str(score_settlement[field])
            for field in ("fixture_id", "competition")
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_PROJECTION_MISMATCH")
        prediction_object = prediction_objects[str(score_row["prediction_id"])]
        settlement_object = settlement_objects[str(score_row["settlement_id"])]
        score_object = score_objects[str(score_row["score_id"])]
        if score_object.scored_at != settlement_object.settled_at:
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_TIME_MISMATCH")
        recomputed_score = score_prediction(
            prediction_object,
            settlement_object,
            scored_at=settlement_object.settled_at,
            score_id=score_object.score_id,
        )
        if recomputed_score is None or (
            score_object.outcome != recomputed_score.outcome
            or not math.isclose(
                score_object.log_loss,
                recomputed_score.log_loss,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or not math.isclose(
                score_object.brier_score,
                recomputed_score.brier_score,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
            or score_object.accurate is not recomputed_score.accurate
        ):
            raise ValueError("PREQUENTIAL_REPLAY_SCORE_SEMANTICS_MISMATCH")

    reference_losses: dict[tuple[str, str, str], float] = {}
    for score_object in score_objects.values():
        if score_object.model_id.startswith("reference-"):
            reference_key = (
                score_object.settlement_id,
                score_object.market.value,
                score_object.cutoff_name.value,
            )
            previous = reference_losses.setdefault(
                reference_key,
                score_object.log_loss,
            )
            if not math.isclose(
                previous,
                score_object.log_loss,
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                raise ValueError("PREQUENTIAL_REPLAY_REFERENCE_SCORE_AMBIGUOUS")
    for score_object in score_objects.values():
        reference_key = (
            score_object.settlement_id,
            score_object.market.value,
            score_object.cutoff_name.value,
        )
        reference_loss = reference_losses.get(reference_key)
        expected_delta = (
            None
            if score_object.model_id.startswith("reference-")
            or reference_loss is None
            else score_object.log_loss - reference_loss
        )
        if (
            (expected_delta is None)
            != (score_object.reference_log_loss_delta is None)
            or expected_delta is not None
            and not math.isclose(
                score_object.reference_log_loss_delta or 0.0,
                expected_delta,
                rel_tol=0.0,
                abs_tol=1e-15,
            )
        ):
            raise ValueError("PREQUENTIAL_REPLAY_REFERENCE_DELTA_MISMATCH")

    for metric in rows["prequential_metric_snapshots"]:
        measured_at = _timestamp(metric["measured_at"], field="metric_measured_at")
        eligible_predictions = tuple(
            prediction
            for prediction in prediction_objects.values()
            if prediction.predicted_at <= measured_at
        )
        eligible_prediction_ids = {
            prediction.prediction_id for prediction in eligible_predictions
        }
        eligible_scores = tuple(
            score
            for score in score_objects.values()
            if score.scored_at <= measured_at
            and score.prediction_id in eligible_prediction_ids
        )
        missingness_by_prediction: dict[str, Mapping[str, bool]] = {}
        for metric_prediction in eligible_predictions:
            selected_snapshot = snapshots.get(
                str(metric_prediction.feature_snapshot_id)
            )
            missingness = (
                selected_snapshot.get("missingness", {})
                if selected_snapshot is not None
                else {}
            )
            if not isinstance(missingness, Mapping):
                raise ValueError("PREQUENTIAL_REPLAY_METRIC_MISSINGNESS_INVALID")
            missingness_by_prediction[metric_prediction.prediction_id] = {
                str(key): bool(value) for key, value in missingness.items()
            }
        expected_segments = segmented_metrics(
            predictions=eligible_predictions,
            scores=eligible_scores,
            missingness_by_prediction=missingness_by_prediction,
        )
        metric_key = (
            str(metric["competition"]),
            str(metric["market"]),
            str(metric["cutoff_name"]),
            str(metric["model_id"]),
            str(metric["model_version"]),
            str(metric["month"]),
        )
        expected_segment = next(
            (
                segment
                for segment in expected_segments
                if (
                    str(segment["competition"]),
                    str(segment["market"]),
                    str(segment["cutoff"]),
                    str(segment["model_id"]),
                    str(segment["model_version"]),
                    str(segment["month"]),
                )
                == metric_key
            ),
            None,
        )
        if expected_segment is None or not isinstance(
            expected_segment.get("metrics"), Mapping
        ):
            raise ValueError("PREQUENTIAL_REPLAY_METRIC_SEGMENT_MISSING")
        expected_metrics = cast(
            Mapping[str, object], expected_segment["metrics"]
        )
        actual_metrics: dict[str, object] = {
            "support": int(cast(str | int, metric["support"])),
            "log_loss": metric.get("log_loss"),
            "brier_score": metric.get("brier_score"),
            "calibration_error": metric.get("calibration_error"),
            "accuracy_descriptive": metric.get("accuracy_descriptive"),
            "coverage": metric.get("coverage"),
            "missingness": metric.get("missingness"),
            "reference_log_loss_delta": metric.get("reference_log_loss_delta"),
        }
        for field, expected_value in expected_metrics.items():
            actual_value = actual_metrics.get(field)
            if expected_value is None or actual_value is None:
                if expected_value is not actual_value:
                    raise ValueError("PREQUENTIAL_REPLAY_METRIC_SEMANTICS_MISMATCH")
            elif isinstance(expected_value, int) and not isinstance(
                expected_value, bool
            ):
                if int(cast(str | int, actual_value)) != expected_value:
                    raise ValueError("PREQUENTIAL_REPLAY_METRIC_SEMANTICS_MISMATCH")
            elif not math.isclose(
                float(cast(str | int | float, actual_value)),
                float(cast(str | int | float, expected_value)),
                rel_tol=0.0,
                abs_tol=1e-15,
            ):
                raise ValueError("PREQUENTIAL_REPLAY_METRIC_SEMANTICS_MISMATCH")


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
    (
        model_objects,
        prediction_objects,
        settlement_objects,
        score_objects,
    ) = _verify_record_hashes(rows)
    _verify_lineage(
        rows,
        model_objects=model_objects,
        prediction_objects=prediction_objects,
        settlement_objects=settlement_objects,
        score_objects=score_objects,
    )
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
