"""Operational CLI for the five-league prequential learning factory.

The normal commands are fail-closed and use PostgreSQL plus append-only R2.
The synthetic pilot is explicitly isolated below the selected output directory
and never writes to the operational database or calls a provider.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from robin.domain.enums import DataAvailability
from robin.market_math import DevigInputError
from robin.market_math import devig_probabilities as kernel_devig
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureFamily,
    CaptureReceipt,
    canonical_sha256,
)
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    FeatureSnapshotRegistry,
    freeze_feature_snapshot,
    persist_source_receipt,
    verify_feature_snapshot_artifact,
)
from robin.prospective_observatory.prequential_contracts import (
    FIVE_LEAGUE_NAMES,
    PROMOTION_LOCKED,
    CutoffName,
    FeatureSnapshot,
    FixtureResultStatus,
    FixtureSettlementRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionStatus,
    TrainingDatasetManifest,
    VerifiedFixtureResult,
)
from robin.prospective_observatory.prequential_factory import (
    PrequentialLearningFactory,
    initial_model_versions,
)
from robin.prospective_observatory.prequential_metrics import segmented_metrics
from robin.prospective_observatory.prequential_persistence import (
    PrequentialSQLRepository,
)
from robin.prospective_observatory.prequential_replay import (
    replay_prequential_rows,
)
from robin.prospective_observatory.prequential_settlement import (
    SettlementRegistry,
    verify_result_observation_artifact,
)
from robin.prospective_observatory.prequential_storage import (
    ArtifactIntegrityError,
    DirectoryArtifactStore,
    PrequentialArtifactRepository,
    R2ArtifactStore,
)
from robin.prospective_observatory.prequential_training import (
    MINIMUM_NEW_FIXTURES,
    MINIMUM_REPRESENTED_LEAGUES,
    MINIMUM_TRAINING_INTERVAL,
    TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT,
    EligibleTrainingExample,
    challenger_model_version,
    challenger_probabilities_from_artifact,
    eligible_training_examples,
    training_manifest_record_id,
)
from robin.prospective_observatory.r2 import (
    ProspectiveR2Repository,
    operational_odds_replay_projection,
    project_odds_rows,
)
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import ProviderResult
from robin.storage.database import build_engine
from robin.storage.prequential_models import PrequentialTrainingRunModel
from robin.storage.prospective_models import (
    CaptureReceiptModel,
    CaptureWindowModel,
    ProspectiveFixtureModel,
    ProspectiveOddsSnapshotModel,
    ProspectivePayloadIndexModel,
    TemporalDataGateModel,
)
from robin.temporal.lineage import SourceReceipt, TemporalProofLevel, parse_utc

DEFAULT_CONFIG = Path("configs/prequential_learning_v1.json")
DEFAULT_OUTPUT = Path("artifacts/prequential-learning")
DEFAULT_IDENTITY_REPORT = Path("reports/ux/team-identity-provenance.json")
SAFE_CODE_REVISION = "local-uncommitted"
FINAL_PROVIDER_STATUSES = {"FT", "AET", "PEN"}
VOID_PROVIDER_STATUSES = {"CANC", "ABD", "AWD", "WO"}
REQUIRED_GUARDS = {
    "STORAGE_PAUSED": "true",
    "P3_P4_PAUSED": "true",
    "PRODUCTION_LOCKED": "true",
    "REAL_BETS": "false",
    "NO_BET_DEFAULT": "true",
    "PROMOTION_LOCKED": "true",
    "SOCIAL_PUBLISHING_ENABLED": "false",
    "DEMO_MODE_ENABLED": "false",
}


@dataclass(frozen=True, slots=True)
class FixtureIdentity:
    home_name: str
    away_name: str


@dataclass(frozen=True, slots=True)
class OddsEvidence:
    decimal_odds: dict[str, float]
    observed_at: datetime
    snapshot_id: str
    bookmaker: str
    margin: float
    receipt_id: str
    payload_sha256: str
    source_identity: str
    source_published_at: datetime | None
    robin_first_observed_at: datetime
    robin_ingested_at: datetime
    available_at: datetime
    window_id: str
    receipt_r2_key: str
    payload_r2_key: str
    source_receipt: SourceReceipt


def _select_odds_evidence(
    candidates: Sequence[OddsEvidence],
) -> OddsEvidence | None:
    if not candidates:
        return None
    latest_available = max(value.available_at for value in candidates)
    latest = [
        value for value in candidates if value.available_at == latest_available
    ]
    best_margin = min(value.margin for value in latest)
    winners = [value for value in latest if value.margin == best_margin]
    if len({value.snapshot_id for value in winners}) != 1:
        raise ValueError("PREQUENTIAL_ODDS_EVIDENCE_AMBIGUOUS")
    return winners[0]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("PREQUENTIAL_DATETIME_UTC_REQUIRED")
    return value.astimezone(UTC)


def _utc_db(value: datetime) -> datetime:
    """Restore UTC stripped only by the typed SQLAlchemy/SQLite adapter."""

    candidate = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return candidate.astimezone(UTC)


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("PREQUENTIAL_NOW_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _read_mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"PREQUENTIAL_JSON_OBJECT_REQUIRED:{path.name}")
    return cast(dict[str, object], value)


def _write_report(path: Path, value: Mapping[str, object]) -> dict[str, object]:
    report = dict(value)
    report.update(
        {
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "no_bet_default": True,
            "promotion_status": PROMOTION_LOCKED,
            "social_publishing_enabled": False,
            "demo_mode_enabled": False,
        }
    )
    report["report_sha256"] = canonical_sha256(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def _verify_runtime_guards(environment: Mapping[str, str]) -> None:
    mismatches = [
        name
        for name, expected in REQUIRED_GUARDS.items()
        if environment.get(name, "").strip().casefold() != expected
    ]
    if mismatches:
        raise RuntimeError(
            "PREQUENTIAL_RUNTIME_GUARDS_INVALID:" + ",".join(mismatches)
        )


def _config(path: Path) -> dict[str, object]:
    value = _read_mapping(path)
    if value.get("schema_version") != "prequential-learning-factory-v1":
        raise ValueError("PREQUENTIAL_CONFIG_SCHEMA_INVALID")
    markets = value.get("markets")
    scopes = value.get("model_scopes")
    if (
        markets != ["1X2", "OVER_UNDER_2_5"]
        or not isinstance(scopes, list)
        or set(str(item) for item in scopes) != {scope.value for scope in ModelScope}
    ):
        raise ValueError("PREQUENTIAL_CONFIG_SCOPE_INVALID")
    security = value.get("security")
    if not isinstance(security, Mapping) or security.get(
        "promotion_status"
    ) != PROMOTION_LOCKED:
        raise ValueError("PREQUENTIAL_CONFIG_SECURITY_INVALID")
    return value


def _feature_contract(config: Mapping[str, object]) -> dict[str, object]:
    value = config.get("feature_contract")
    if not isinstance(value, Mapping):
        raise ValueError("PREQUENTIAL_FEATURE_CONTRACT_MISSING")
    return dict(value)


def _code_revision(environment: Mapping[str, str]) -> str:
    value = environment.get("GITHUB_SHA", "").strip()
    return value if value else SAFE_CODE_REVISION


def _identity_map(path: Path) -> dict[str, FixtureIdentity]:
    if not path.is_file():
        return {}
    value = _read_mapping(path)
    rows = value.get("identities")
    if not isinstance(rows, list):
        raise ValueError("PREQUENTIAL_IDENTITY_REPORT_INVALID")
    sides: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or row.get("identity_status") != "VERIFIED"
            or row.get("receipt_verified") is not True
        ):
            continue
        fixture_id = str(row.get("fixture_id", "")).strip()
        side = str(row.get("side", "")).strip().casefold()
        display_name = str(row.get("display_name", "")).strip()
        if fixture_id and side in {"home", "away"} and display_name:
            sides[fixture_id][side] = display_name
    return {
        fixture_id: FixtureIdentity(
            home_name=values["home"],
            away_name=values["away"],
        )
        for fixture_id, values in sides.items()
        if set(values) == {"home", "away"}
    }


def _latest_fixtures(
    engine: Engine,
    *,
    as_of: datetime,
) -> tuple[ProspectiveFixtureModel, ...]:
    cutoff = _utc(as_of)
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(ProspectiveFixtureModel)
                .where(ProspectiveFixtureModel.registered_at <= cutoff)
                .order_by(
                    ProspectiveFixtureModel.registered_at,
                    ProspectiveFixtureModel.registry_hash,
                    ProspectiveFixtureModel.id,
                )
            )
        )
    versions: dict[str, list[ProspectiveFixtureModel]] = defaultdict(list)
    for row in rows:
        versions[row.fixture_id].append(row)
    latest: dict[str, ProspectiveFixtureModel] = {}
    for fixture_id, candidates in versions.items():
        latest_at = max(_utc_db(row.registered_at) for row in candidates)
        heads = [
            row
            for row in candidates
            if _utc_db(row.registered_at) == latest_at
        ]
        distinct = {(row.id, row.registry_hash) for row in heads}
        if len(distinct) != 1:
            raise ValueError(
                f"PREQUENTIAL_FIXTURE_VERSION_AMBIGUOUS:{fixture_id}"
            )
        latest[fixture_id] = heads[0]
    return tuple(
        sorted(
            (
                row
                for row in latest.values()
                if not row.cancelled and row.kickoff_reliable
            ),
            key=lambda row: (_utc_db(row.kickoff_at), row.fixture_id),
        )
    )


def _fixture_records(
    engine: Engine,
    *,
    fixture_record_ids: set[str],
    as_of: datetime,
) -> tuple[ProspectiveFixtureModel, ...]:
    if not fixture_record_ids:
        return ()
    cutoff = _utc(as_of)
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(ProspectiveFixtureModel).where(
                    ProspectiveFixtureModel.id.in_(fixture_record_ids),
                    ProspectiveFixtureModel.registered_at <= cutoff,
                )
            )
        )
    by_id = {row.id: row for row in rows}
    missing = sorted(fixture_record_ids - set(by_id))
    if missing:
        raise ValueError(
            "PREQUENTIAL_FIXTURE_RECORD_MISSING:" + ",".join(missing)
        )
    return tuple(
        sorted(
            (
                row
                for row in by_id.values()
                if not row.cancelled and row.kickoff_reliable
            ),
            key=lambda row: (_utc_db(row.kickoff_at), row.fixture_id, row.id),
        )
    )


def _canonical_selection(
    *,
    market: PredictionMarket,
    selection: str,
    identity: FixtureIdentity | None,
) -> str | None:
    # Identity reports are operational aids, not content-addressed temporal
    # evidence. They must never translate mutable team labels in a decision
    # path; only canonical projected labels are admissible here.
    del identity
    folded = selection.strip().casefold()
    if market is PredictionMarket.OVER_UNDER_2_5:
        if folded == "over":
            return "OVER"
        if folded == "under":
            return "UNDER"
        return None
    if folded == "draw":
        return "DRAW"
    if folded == "home":
        return "HOME"
    if folded == "away":
        return "AWAY"
    return None


def _odds_evidence(
    engine: Engine,
    *,
    fixture_record_id: str,
    fixture_id: str,
    market: PredictionMarket,
    cutoff_at: datetime,
    identity: FixtureIdentity | None,
    repository: ProspectiveR2Repository,
) -> OddsEvidence | None:
    with Session(engine) as session:
        rows = tuple(
            session.execute(
                select(
                    ProspectiveOddsSnapshotModel,
                    CaptureReceiptModel,
                    ProspectivePayloadIndexModel,
                    CaptureWindowModel,
                )
                .outerjoin(
                    CaptureReceiptModel,
                    ProspectiveOddsSnapshotModel.receipt_id
                    == CaptureReceiptModel.id,
                )
                .outerjoin(
                    ProspectivePayloadIndexModel,
                    ProspectivePayloadIndexModel.receipt_id
                    == CaptureReceiptModel.id,
                )
                .outerjoin(
                    CaptureWindowModel,
                    CaptureWindowModel.id
                    == CaptureReceiptModel.window_record_id,
                )
                .where(
                    ProspectiveOddsSnapshotModel.fixture_id == fixture_id,
                    ProspectiveOddsSnapshotModel.market == market.value,
                    ProspectiveOddsSnapshotModel.observed_at <= cutoff_at,
                )
            )
        )
    groups: dict[
        tuple[str, str, datetime],
        dict[str, ProspectiveOddsSnapshotModel],
    ] = defaultdict(dict)
    closure: dict[
        tuple[str, str, datetime],
        tuple[
            CaptureReceiptModel | None,
            ProspectivePayloadIndexModel | None,
            CaptureWindowModel | None,
        ],
    ] = {}
    invalid_group_keys: set[tuple[str, str, datetime]] = set()
    for row, receipt_row, index_row, window_row in rows:
        canonical = _canonical_selection(
            market=market,
            selection=row.selection,
            identity=identity,
        )
        if canonical is None:
            continue
        group_key = (row.receipt_id, row.bookmaker, _utc_db(row.observed_at))
        if canonical in groups[group_key]:
            invalid_group_keys.add(group_key)
            continue
        groups[group_key][canonical] = row
        metadata = (receipt_row, index_row, window_row)
        previous = closure.setdefault(group_key, metadata)
        if previous != metadata:
            raise ValueError("PREQUENTIAL_ODDS_RECEIPT_JOIN_AMBIGUOUS")
    expected = (
        {"HOME", "DRAW", "AWAY"}
        if market is PredictionMarket.ONE_X_TWO
        else {"OVER", "UNDER"}
    )
    candidates: list[OddsEvidence] = []
    for (receipt_id, bookmaker, observed_at), values in groups.items():
        group_key = (receipt_id, bookmaker, observed_at)
        if group_key in invalid_group_keys or set(values) != expected:
            continue
        receipt_row, index_row, window_row = closure[group_key]
        if receipt_row is None:
            raise ValueError("PREQUENTIAL_ODDS_RECEIPT_MISSING")
        # Exclude a candidate whose conservative availability is in the
        # future before requiring its index/window or reconstructing its
        # receipt.  Late materialisation must never poison an older valid
        # pre-cutoff selection.
        raw_availability_times = [
            _utc_db(receipt_row.requested_at),
            _utc_db(receipt_row.response_received_at),
            _utc_db(receipt_row.observed_at),
            _utc_db(receipt_row.materialized_at),
        ]
        if receipt_row.provider_updated_at is not None:
            raw_availability_times.append(
                _utc_db(receipt_row.provider_updated_at)
            )
        if index_row is not None:
            raw_availability_times.append(_utc_db(index_row.indexed_at))
        if any(value > cutoff_at for value in raw_availability_times):
            continue
        if index_row is None:
            raise ValueError("PREQUENTIAL_ODDS_PAYLOAD_INDEX_MISSING")
        if window_row is None:
            raise ValueError("PREQUENTIAL_ODDS_WINDOW_MISSING")
        receipt = CaptureReceipt(
            window_id=receipt_row.window_id,
            window_label=receipt_row.window_label,
            fixture_id=receipt_row.fixture_id,
            competition=receipt_row.competition,
            season=receipt_row.season,
            provider=receipt_row.provider,
            family=CaptureFamily(receipt_row.family),
            requested_at=_utc_db(receipt_row.requested_at),
            response_received_at=_utc_db(receipt_row.response_received_at),
            observed_at=_utc_db(receipt_row.observed_at),
            event_time=(
                _utc_db(receipt_row.event_time)
                if receipt_row.event_time is not None
                else None
            ),
            provider_updated_at=(
                _utc_db(receipt_row.provider_updated_at)
                if receipt_row.provider_updated_at is not None
                else None
            ),
            cutoff_at=_utc_db(receipt_row.cutoff_at),
            kickoff_at=_utc_db(receipt_row.kickoff_at),
            materialized_at=_utc_db(receipt_row.materialized_at),
            seconds_before_kickoff=receipt_row.seconds_before_kickoff,
            http_status=receipt_row.http_status,
            payload_sha256=receipt_row.payload_sha256,
            payload_bytes=receipt_row.payload_bytes,
            stored_bytes=receipt_row.stored_bytes,
            r2_key=receipt_row.r2_key,
            receipt_r2_key=receipt_row.receipt_r2_key,
            source_endpoint=receipt_row.source_endpoint,
            complete=receipt_row.complete,
            quality_status=AvailabilityStatus(receipt_row.quality_status),
            provider_calls=receipt_row.provider_calls,
            code_revision=receipt_row.code_revision,
        )
        if receipt.receipt_hash != receipt_row.receipt_hash:
            raise ValueError("PREQUENTIAL_ODDS_RECEIPT_HASH_MISMATCH")
        if (
            receipt.family is not CaptureFamily.ODDS
            or receipt.fixture_id != fixture_id
            or not receipt.complete
            or receipt.quality_status
            not in {AvailabilityStatus.CAPTURED, AvailabilityStatus.COMPLETE}
            or not receipt.temporally_admissible
            or receipt.window_id is None
            or window_row.id != receipt_row.window_record_id
            or window_row.window_id != receipt.window_id
            or window_row.fixture_record_id != fixture_record_id
            or window_row.fixture_id != fixture_id
            or window_row.family != CaptureFamily.ODDS.value
            or _utc_db(window_row.cutoff_at) != receipt.cutoff_at
            or _utc_db(window_row.kickoff_at) != receipt.kickoff_at
        ):
            raise ValueError("PREQUENTIAL_ODDS_TEMPORAL_CLOSURE_INVALID")
        if (
            index_row.receipt_id != receipt_row.id
            or index_row.fixture_id != fixture_id
            or index_row.family != CaptureFamily.ODDS.value
            or index_row.r2_key != receipt.r2_key
            or index_row.receipt_r2_key != receipt.receipt_r2_key
            or index_row.payload_sha256 != receipt.payload_sha256
            or index_row.payload_bytes != receipt.payload_bytes
            or index_row.stored_bytes != receipt.stored_bytes
            or _utc_db(index_row.observed_at) != receipt.observed_at
            or any(
                _utc_db(value.observed_at) != receipt.observed_at
                or _utc_db(value.cutoff_at) != receipt.cutoff_at
                for value in values.values()
            )
        ):
            raise ValueError("PREQUENTIAL_ODDS_PROJECTION_CLOSURE_INVALID")
        stored_capture = repository.read_capture(receipt.receipt_r2_key)
        if stored_capture.receipt != receipt:
            raise ValueError("PREQUENTIAL_ODDS_R2_RECEIPT_MISMATCH")
        try:
            raw_projection = operational_odds_replay_projection(
                receipt,
                stored_capture.payload,
            )
            projected_rows = tuple(
                row
                for row in project_odds_rows(receipt, raw_projection)
                if row["bookmaker"] == bookmaker
                and row["market"] == market.value
            )
        except (RuntimeError, TypeError, ValueError) as error:
            raise ValueError(
                "PREQUENTIAL_ODDS_RAW_PROJECTION_MISMATCH"
            ) from error

        def projection_identity(row: Mapping[str, object]) -> dict[str, object]:
            observed = row["observed_at"]
            cutoff = row["cutoff_at"]
            if not isinstance(observed, datetime) or not isinstance(
                cutoff,
                datetime,
            ):
                raise ValueError("PREQUENTIAL_ODDS_RAW_PROJECTION_MISMATCH")
            return {
                "id": row["id"],
                "receipt_id": row["receipt_id"],
                "fixture_id": row["fixture_id"],
                "bookmaker": row["bookmaker"],
                "market": row["market"],
                "selection": row["selection"],
                "odds": row["odds"],
                "margin": row["margin"],
                "observed_at": _utc_db(observed).isoformat(),
                "cutoff_at": _utc_db(cutoff).isoformat(),
                "fixture_match_status": row["fixture_match_status"],
                "snapshot_hash": row["snapshot_hash"],
                "code_revision": row["code_revision"],
                "append_only": row["append_only"],
            }

        actual_projection_rows = tuple(
            {
                "id": row.id,
                "receipt_id": row.receipt_id,
                "fixture_id": row.fixture_id,
                "bookmaker": row.bookmaker,
                "market": row.market,
                "selection": row.selection,
                "odds": row.odds,
                "margin": row.margin,
                "observed_at": _utc_db(row.observed_at).isoformat(),
                "cutoff_at": _utc_db(row.cutoff_at).isoformat(),
                "fixture_match_status": row.fixture_match_status,
                "snapshot_hash": row.snapshot_hash,
                "code_revision": row.code_revision,
                "append_only": row.append_only,
            }
            for row in values.values()
        )
        expected_projection_rows = tuple(
            projection_identity(row) for row in projected_rows
        )
        if sorted(
            actual_projection_rows,
            key=lambda row: str(row["selection"]),
        ) != sorted(
            expected_projection_rows,
            key=lambda row: str(row["selection"]),
        ):
            raise ValueError("PREQUENTIAL_ODDS_RAW_PROJECTION_MISMATCH")
        decimal_odds = {
            selection: values[selection].odds
            for selection in sorted(expected)
        }
        try:
            devig = kernel_devig(
                decimal_odds.values(),
                method="PROPORTIONAL",
                outcome_labels=tuple(decimal_odds),
            )
        except DevigInputError:
            continue
        stored_margins = tuple(row.margin for row in values.values())
        if (
            devig.overround <= 0.0
            or any(not math.isfinite(margin) for margin in stored_margins)
            or any(
                not math.isclose(
                    margin,
                    devig.overround,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                for margin in stored_margins
            )
        ):
            continue
        consumable_at = max(
            receipt.materialized_at,
            _utc_db(index_row.indexed_at),
        )
        conservative_available_at = max(
            value
            for value in (
                receipt.response_received_at,
                receipt.provider_updated_at,
            )
            if value is not None
        )
        if conservative_available_at > cutoff_at or consumable_at > cutoff_at:
            # This receipt belongs to the future relative to the decision.
            # It must not displace an older admissible candidate and turn a
            # reproducible past selection into an exception.
            continue
        feature_market_value = {
            "decimal_odds": decimal_odds,
            "bookmaker": bookmaker,
            "margin": devig.overround,
            "coverage": 1.0,
        }
        source_receipt = persist_source_receipt(
            PrequentialArtifactRepository(repository.store),
            source_name=receipt.provider,
            request_identity=receipt.receipt_hash,
            payload={
                "schema_version": "prequential-prospective-source-closure-v1",
                "fixture_id": receipt.fixture_id,
                "fixture_record_id": fixture_record_id,
                "raw_receipt_hash": receipt.receipt_hash,
                "raw_payload_sha256": receipt.payload_sha256,
                "raw_receipt_r2_key": receipt.receipt_r2_key,
                "raw_payload_r2_key": receipt.r2_key,
                "family": "market",
                "value": feature_market_value,
                "payload_index": {
                    "receipt_id": index_row.receipt_id,
                    "indexed_at": _utc_db(index_row.indexed_at).isoformat(),
                    "consumable_at": consumable_at.isoformat(),
                    "code_revision": index_row.code_revision,
                },
            },
            source_published_at=receipt.provider_updated_at,
            observed_at=receipt.response_received_at,
            ingested_at=consumable_at,
            code_revision=receipt.code_revision,
            availability_status=TemporalProofLevel.PROSPECTIVE_CAPTURED,
            event_at=receipt.event_time,
        )
        candidates.append(
            OddsEvidence(
                decimal_odds=decimal_odds,
                observed_at=observed_at,
                snapshot_id="odds-" + canonical_sha256(
                    {
                        "receipt_id": receipt.receipt_hash,
                        "bookmaker": bookmaker,
                        "market": market.value,
                        "rows": {
                            selection: values[selection].snapshot_hash
                            for selection in sorted(expected)
                        },
                    }
                ),
                bookmaker=bookmaker,
                margin=devig.overround,
                receipt_id=receipt.receipt_hash,
                payload_sha256=receipt.payload_sha256,
                source_identity=receipt.receipt_r2_key,
                source_published_at=receipt.provider_updated_at,
                robin_first_observed_at=receipt.response_received_at,
                robin_ingested_at=max(
                    receipt.materialized_at,
                    _utc_db(index_row.indexed_at),
                ),
                available_at=conservative_available_at,
                window_id=receipt.window_id,
                receipt_r2_key=receipt.receipt_r2_key,
                payload_r2_key=receipt.r2_key,
                source_receipt=source_receipt,
            )
        )
    return _select_odds_evidence(candidates)


def _latest_gates(
    engine: Engine,
    *,
    fixture_id: str,
    cutoff_at: datetime,
) -> dict[str, TemporalDataGateModel]:
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(TemporalDataGateModel).where(
                    TemporalDataGateModel.fixture_id == fixture_id,
                    TemporalDataGateModel.evaluated_at <= cutoff_at,
                )
            )
        )
    latest: dict[str, TemporalDataGateModel] = {}
    for row in sorted(
        rows,
        key=lambda value: (_utc_db(value.evaluated_at), value.id),
    ):
        latest[row.gate_name] = row
    return latest


def _cutoff_windows(
    config: Mapping[str, object],
    *,
    kickoff_at: datetime,
) -> tuple[tuple[CutoffName, datetime, datetime], ...]:
    cutoffs = config.get("cutoffs")
    if not isinstance(cutoffs, Mapping):
        raise ValueError("PREQUENTIAL_CUTOFF_CONFIG_INVALID")
    rows: list[tuple[CutoffName, datetime, datetime]] = []
    for cutoff_name in CutoffName:
        policy = cutoffs.get(cutoff_name.value)
        if not isinstance(policy, Mapping):
            raise ValueError("PREQUENTIAL_CUTOFF_CONFIG_INVALID")
        before = policy.get("before_kickoff_minutes")
        opens = policy.get("opens_before_kickoff_minutes")
        if not isinstance(before, int) or before < 1:
            raise ValueError("PREQUENTIAL_CUTOFF_CONFIG_INVALID")
        if not isinstance(opens, int):
            opens = before + (30 if cutoff_name is CutoffName.H_2 else 14)
        if opens <= before:
            raise ValueError("PREQUENTIAL_CUTOFF_WINDOW_INVALID")
        rows.append(
            (
                cutoff_name,
                kickoff_at - timedelta(minutes=before),
                kickoff_at - timedelta(minutes=opens),
            )
        )
    return tuple(rows)


def _feature_inputs(
    *,
    fixture: ProspectiveFixtureModel,
    market: PredictionMarket,
    cutoff_at: datetime,
    odds: OddsEvidence,
    gates: Mapping[str, TemporalDataGateModel],
) -> tuple[
    dict[str, object],
    dict[str, bool],
    dict[str, dict[str, object]],
    dict[str, object],
]:
    # TemporalDataGate rows currently lack repository-backed source receipts.
    # They remain diagnostic SQL projections and cannot enter a frozen
    # snapshot's values, quality hash or decision identity.
    del gates
    values: dict[str, object] = {family: None for family in FEATURE_FAMILIES}
    availability = {family: False for family in FEATURE_FAMILIES}
    provenance: dict[str, dict[str, object]] = {}
    values["market"] = {
        "decimal_odds": odds.decimal_odds,
        "bookmaker": odds.bookmaker,
        "margin": odds.margin,
        "coverage": 1.0,
    }
    availability["market"] = True
    provenance["market"] = {
        **odds.source_receipt.as_dict(),
        "source": "prospective_odds_snapshots",
        "source_identity": odds.source_receipt.storage_identity,
        "capture_receipt_id": odds.receipt_id,
        "odds_snapshot_id": odds.snapshot_id,
        "window_id": odds.window_id,
        "receipt_r2_key": odds.receipt_r2_key,
        "payload_r2_key": odds.payload_r2_key,
        "observed_at": (
            odds.source_receipt.robin_first_observed_at.isoformat()
        ),
        "cutoff_at": cutoff_at.isoformat(),
    }
    registered_at = _utc_db(fixture.registered_at)
    quality: dict[str, object] = {
        "market": "PASSED",
        "fixture": (
            "TEMPORAL_RECEIPT_NOT_PROVEN"
            if registered_at <= cutoff_at
            else "BLOCKED_BY_TEMPORALITY"
        ),
        "gates": {},
        "gate_feature_status": "TEMPORAL_RECEIPT_NOT_PROVEN",
    }
    return values, availability, provenance, quality


def _replay_state_fingerprint(
    rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> str:
    """Order-independent identity for one append-only SQL state snapshot."""

    return canonical_sha256(
        {
            table: sorted(
                (dict(row) for row in table_rows),
                key=canonical_sha256,
            )
            for table, table_rows in sorted(rows.items())
        }
    )


def _restore_factory(
    sql: PrequentialSQLRepository,
    artifacts: PrequentialArtifactRepository,
    *,
    now: datetime,
    feature_contract_hash: str,
    code_revision: str,
) -> PrequentialLearningFactory:
    models = sql.load_models()
    if not models:
        models = initial_model_versions(
            created_at=now,
            feature_contract_hash=feature_contract_hash,
            code_revision=code_revision,
        )
        for model in models:
            sql.append_model(model)
    # Every operational consumer (forecast, settlement, metrics and training)
    # restores through this boundary.  Verify the complete durable causal
    # graph before any row can become live in a registry: content hashes alone
    # do not prove prediction probabilities, scores, targets or ledger edges.
    replay_rows = sql.replay_rows()
    replay_fingerprint = _replay_state_fingerprint(replay_rows)
    _verify_replay_artifacts(artifacts=artifacts, rows=replay_rows)
    replay_prequential_rows(replay_rows)
    snapshots = sql.load_snapshots()
    predictions = sql.load_predictions()
    scores = sql.load_scores()
    settlements = sql.load_settlements()
    events = sql.load_events()

    def durable_hashes(
        table: str,
        *,
        identity_field: str,
        hash_field: str,
    ) -> dict[str, str]:
        output: dict[str, str] = {}
        for row in replay_rows.get(table, ()):
            identity = str(row.get(identity_field, ""))
            digest = str(row.get(hash_field, ""))
            if not identity or identity in output:
                raise ValueError("PREQUENTIAL_RESTORE_VERIFIED_ROW_SET_INVALID")
            output[identity] = digest
        return output

    loaded_hashes = {
        "prequential_model_versions": {
            f"model-{model.registry_hash}": model.registry_hash
            for model in models
        },
        "prequential_feature_snapshots": {
            snapshot.snapshot_id: snapshot.snapshot_hash
            for snapshot in snapshots
        },
        "prequential_predictions": {
            prediction.prediction_id: prediction.payload_hash
            for prediction in predictions
        },
        "prequential_fixture_settlements": {
            settlement.settlement_id: settlement.settlement_hash
            for settlement in settlements
        },
        "prequential_prediction_scores": {
            score.score_id: score.score_hash for score in scores
        },
        "prequential_ledger_events": {
            event.event_id: event.event_hash for event in events
        },
    }
    expected_hashes = {
        "prequential_model_versions": durable_hashes(
            "prequential_model_versions",
            identity_field="id",
            hash_field="registry_hash",
        ),
        "prequential_feature_snapshots": durable_hashes(
            "prequential_feature_snapshots",
            identity_field="snapshot_id",
            hash_field="snapshot_hash",
        ),
        "prequential_predictions": durable_hashes(
            "prequential_predictions",
            identity_field="prediction_id",
            hash_field="payload_hash",
        ),
        "prequential_fixture_settlements": durable_hashes(
            "prequential_fixture_settlements",
            identity_field="settlement_id",
            hash_field="settlement_hash",
        ),
        "prequential_prediction_scores": durable_hashes(
            "prequential_prediction_scores",
            identity_field="score_id",
            hash_field="score_hash",
        ),
        "prequential_ledger_events": durable_hashes(
            "prequential_ledger_events",
            identity_field="event_id",
            hash_field="record_hash",
        ),
    }
    if loaded_hashes != expected_hashes:
        raise ValueError("PREQUENTIAL_RESTORE_VERIFIED_ROW_SET_MISMATCH")
    factory = PrequentialLearningFactory(
        artifact_repository=artifacts,
        models=models,
        devig_method="PROPORTIONAL",
    )
    for snapshot in snapshots:
        verify_feature_snapshot_artifact(artifacts, snapshot)
        factory.features.append(snapshot)
    for prediction in predictions:
        factory.predictions.append(prediction)
    by_settlement: dict[str, list[Any]] = defaultdict(list)
    for score in scores:
        by_settlement[score.settlement_id].append(score)
    for settlement in settlements:
        verify_result_observation_artifact(artifacts, settlement.result)
        factory.settlements.restore(
            settlement,
            tuple(by_settlement.get(settlement.settlement_id, [])),
        )
    for event in events:
        factory.ledger.restore(event)
    # Rows are append-only in every supported database.  A second exact fence
    # therefore detects any concurrent append between the verified snapshot
    # and the per-table reconstruction, instead of returning a mixed state.
    if _replay_state_fingerprint(sql.replay_rows()) != replay_fingerprint:
        raise ValueError("PREQUENTIAL_RESTORE_STATE_CHANGED_DURING_LOAD")
    return factory


def _current_models(
    factory: PrequentialLearningFactory,
    *,
    competition: str,
    at: datetime,
    feature_contract_hash: str,
) -> tuple[ModelVersion, ...]:
    current: dict[str, ModelVersion] = {}
    for model in factory.models.values():
        if model.created_at > at or model.feature_contract_hash != feature_contract_hash:
            continue
        expected = FIVE_LEAGUE_NAMES.get(model.scope)
        if expected is not None and expected != competition:
            continue
        previous = current.get(model.model_id)
        if (
            previous is not None
            and previous.created_at == model.created_at
            and previous.version != model.version
        ):
            raise ValueError("PREQUENTIAL_MODEL_HEAD_AMBIGUOUS")
        if previous is None or (model.created_at, model.version) > (
            previous.created_at,
            previous.version,
        ):
            current[model.model_id] = model
    return tuple(sorted(current.values(), key=lambda value: value.model_id))


def _challenger_probabilities(
    repository: PrequentialArtifactRepository,
    model: ModelVersion,
    market: PredictionMarket,
) -> dict[str, float] | None:
    if (
        model.role is not ModelRole.CHALLENGER
        or model.status is not ModelStatus.ACTIVE
        or model.artifact_r2_key is None
    ):
        return None
    raw = repository.read_verified(
        model.artifact_r2_key,
        model.artifact_sha256,
    )
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("PREQUENTIAL_CHALLENGER_ARTIFACT_INVALID")
    return challenger_probabilities_from_artifact(value, market)


def run_forecast(
    *,
    engine: Engine,
    artifacts: PrequentialArtifactRepository,
    config: Mapping[str, object],
    output: Path,
    now: datetime,
    code_revision: str,
    identities: Mapping[str, FixtureIdentity],
) -> dict[str, object]:
    # The identity report is not content-addressed receipt evidence. Retain
    # the API for compatibility, but keep it outside forecast semantics.
    del identities
    contract = _feature_contract(config)
    contract_hash = canonical_sha256(contract)
    sql = PrequentialSQLRepository(engine)
    factory = _restore_factory(
        sql,
        artifacts,
        now=now,
        feature_contract_hash=contract_hash,
        code_revision=code_revision,
    )
    first_event = len(factory.ledger.events)
    due_cutoffs = 0
    frozen = 0
    rejected = 0
    snapshots_inserted = 0
    fixtures = _latest_fixtures(engine, as_of=now)
    evidence_repository = ProspectiveR2Repository(artifacts.store)
    persisted_prediction_keys = {
        (
            prediction.fixture_record_id,
            prediction.cutoff_name,
            prediction.market,
            prediction.model_id,
            prediction.model_version,
        )
        for prediction in factory.predictions.predictions
    }
    for fixture in fixtures:
        kickoff_at = _utc_db(fixture.kickoff_at)
        for cutoff_name, cutoff_at, opens_at in _cutoff_windows(
            config,
            kickoff_at=kickoff_at,
        ):
            if not opens_at <= now <= cutoff_at:
                continue
            due_cutoffs += 1
            decision_as_of = min(now, cutoff_at)
            models = _current_models(
                factory,
                competition=fixture.competition,
                at=decision_as_of,
                feature_contract_hash=contract_hash,
            )
            gates: Mapping[str, TemporalDataGateModel] | None = None
            for market in PredictionMarket:
                pending_models = tuple(
                    model
                    for model in models
                    if (
                        fixture.id,
                        cutoff_name,
                        market,
                        model.model_id,
                        model.version,
                    )
                    not in persisted_prediction_keys
                )
                if not pending_models:
                    # The immutable business decision already exists.  A
                    # retry must return it without observing later gates,
                    # odds, feature rows, or wall-clock availability.
                    continue
                if gates is None:
                    gates = _latest_gates(
                        engine,
                        fixture_id=fixture.fixture_id,
                        cutoff_at=decision_as_of,
                    )
                odds = _odds_evidence(
                    engine,
                    fixture_record_id=fixture.id,
                    fixture_id=fixture.fixture_id,
                    market=market,
                    cutoff_at=decision_as_of,
                    identity=None,
                    repository=evidence_repository,
                )
                snapshot_id: str | None = None
                if (
                    odds is not None
                    and _utc_db(fixture.registered_at) <= decision_as_of
                ):
                    values, availability, provenance, quality = _feature_inputs(
                        fixture=fixture,
                        market=market,
                        cutoff_at=cutoff_at,
                        odds=odds,
                        gates=gates,
                    )
                    before = len(factory.features.snapshots)
                    snapshot = freeze_feature_snapshot(
                        repository=artifacts,
                        registry=factory.features,
                        fixture_record_id=fixture.id,
                        fixture_id=fixture.fixture_id,
                        competition=fixture.competition,
                        market=market,
                        cutoff_name=cutoff_name,
                        cutoff_at=cutoff_at,
                        created_at=now,
                        feature_contract_version=str(
                            contract.get("version", "prequential-features-v1")
                        ),
                        feature_contract=contract,
                        values=values,
                        availability=availability,
                        provenance=provenance,
                        quality=quality,
                        code_revision=code_revision,
                    )
                    factory.register_snapshot(snapshot)
                    sql.append_snapshot(snapshot)
                    snapshots_inserted += int(
                        len(factory.features.snapshots) > before
                    )
                    snapshot_id = snapshot.snapshot_id
                for model in pending_models:
                    prediction = factory.forecast(
                        fixture_record_id=fixture.id,
                        fixture_id=fixture.fixture_id,
                        competition=fixture.competition,
                        market=market,
                        cutoff_name=cutoff_name,
                        cutoff_at=cutoff_at,
                        kickoff_at=kickoff_at,
                        predicted_at=now,
                        model_id=model.model_id,
                        model_version=model.version,
                        feature_snapshot_id=snapshot_id,
                        gate_statuses={
                            "fixture": (
                                _utc_db(fixture.registered_at)
                                <= decision_as_of
                            )
                        },
                        required_gates=("fixture",),
                        decimal_odds=(
                            odds.decimal_odds if odds is not None else None
                        ),
                        odds_snapshot_id=(
                            odds.snapshot_id if odds is not None else None
                        ),
                        challenger_probabilities=_challenger_probabilities(
                            artifacts,
                            model,
                            market,
                        ),
                        code_revision=code_revision,
                    )
                    persisted_prediction_keys.add(
                        (
                            fixture.id,
                            cutoff_name,
                            market,
                            model.model_id,
                            model.version,
                        )
                    )
                    if sql.append_prediction(prediction):
                        if prediction.status is PredictionStatus.FROZEN:
                            frozen += 1
                        else:
                            rejected += 1
    new_events = factory.ledger.events[first_event:]
    sql.append_events(new_events)
    return _write_report(
        output / "forecast-report.json",
        {
            "schema_version": "prequential-forecast-report-v1",
            "generated_at": now.isoformat(),
            "source": "POSTGRESQL_ASOF_PROJECTION_WITH_R2_MARKET_RECEIPT",
            "fixtures_tracked": len(fixtures),
            "cutoffs_due": due_cutoffs,
            "feature_snapshots_inserted": snapshots_inserted,
            "predictions_frozen": frozen,
            "predictions_rejected": rejected,
            "provider_calls": 0,
            "odds_api_credits": 0,
            "counts": sql.counts(),
            "ledger": factory.ledger.audit(),
        },
    )


def _artifact_values(
    repository: PrequentialArtifactRepository,
    kind: str,
) -> tuple[dict[str, object], ...]:
    prefix = f"{repository.namespace}/{kind}/"
    values: list[dict[str, object]] = []
    for key in repository.store.iter_keys(prefix):
        raw = repository.store.get_object(key)
        if raw is None:
            raise RuntimeError("PREQUENTIAL_ARTIFACT_DISAPPEARED")
        digest = key.rsplit("/", 1)[-1].split(".", 1)[0]
        if canonical_sha256(json.loads(raw)) != digest:
            raise RuntimeError("PREQUENTIAL_ARTIFACT_HASH_INVALID")
        value = json.loads(raw)
        if isinstance(value, dict):
            values.append(cast(dict[str, object], value))
    return tuple(values)


def _provider_result_record(
    result: ProviderResult,
    provider_fixture_id: str,
) -> Mapping[str, object] | None:
    matches = [
        row
        for row in result.records
        if isinstance(row.get("fixture"), Mapping)
        and str(cast(Mapping[str, object], row["fixture"]).get("id"))
        == provider_fixture_id
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _verified_result_from_record(
    *,
    fixture: ProspectiveFixtureModel,
    record: Mapping[str, object],
    verified_at: datetime,
    source_hash: str,
    latest_settlement: FixtureSettlementRecord | None = None,
) -> VerifiedFixtureResult | None:
    fixture_value = record.get("fixture")
    goals = record.get("goals")
    if not isinstance(fixture_value, Mapping):
        return None
    status_value = fixture_value.get("status")
    if not isinstance(status_value, Mapping):
        return None
    short = str(status_value.get("short", "")).strip().upper()
    if short in FINAL_PROVIDER_STATUSES:
        if not isinstance(goals, Mapping):
            return None
        home = goals.get("home")
        away = goals.get("away")
        if not isinstance(home, int) or not isinstance(away, int):
            return None
        if (
            latest_settlement is not None
            and latest_settlement.result.home_goals == home
            and latest_settlement.result.away_goals == away
        ):
            return None
        status = FixtureResultStatus.FINISHED
        result_version = 1
        if latest_settlement is not None:
            status = FixtureResultStatus.CORRECTED
            result_version = latest_settlement.result.result_version + 1
        return VerifiedFixtureResult(
            fixture_record_id=fixture.id,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            kickoff_at=_utc_db(fixture.kickoff_at),
            status=status,
            verified_at=verified_at,
            home_goals=home,
            away_goals=away,
            result_version=result_version,
            source_hash=source_hash,
        )
    if short in VOID_PROVIDER_STATUSES:
        if latest_settlement is not None:
            return None
        status = (
            FixtureResultStatus.ABANDONED
            if short == "ABD"
            else FixtureResultStatus.CANCELLED
        )
        return VerifiedFixtureResult(
            fixture_record_id=fixture.id,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            kickoff_at=_utc_db(fixture.kickoff_at),
            status=status,
            verified_at=verified_at,
            result_version=1,
            source_hash=source_hash,
        )
    return None


def _collect_result(
    *,
    repository: PrequentialArtifactRepository,
    provider: ApiFootballProvider,
    fixture: ProspectiveFixtureModel,
    now: datetime,
    latest_settlement: FixtureSettlementRecord | None = None,
) -> tuple[VerifiedFixtureResult | None, int]:
    def guard_id(attempt: int) -> str:
        return canonical_sha256(
            {
                "fixture_id": fixture.fixture_id,
                "fixture_record_id": fixture.id,
                "provider_fixture_id": fixture.provider_fixture_id,
                "attempt": attempt,
                "operation": "VERIFY_FINAL_RESULT",
            }
        )

    guard_values = _artifact_values(repository, "provider-call-guards")
    guards_by_hash = {
        canonical_sha256(value): value
        for value in guard_values
        if value.get("schema_version")
        == "prequential-provider-call-guard-v1"
    }
    completions_by_observation: dict[str, list[dict[str, object]]] = defaultdict(list)
    for completion in _artifact_values(repository, "provider-call-completions"):
        observation_hash = completion.get("observation_sha256")
        if (
            completion.get("schema_version")
            == "prequential-provider-call-completion-v1"
            and isinstance(observation_hash, str)
        ):
            completions_by_observation[observation_hash].append(completion)
    observations: list[tuple[int, datetime]] = []
    for value in _artifact_values(repository, "result-observations"):
        if (
            value.get("schema_version")
            != "prequential-result-observation-v1"
            or value.get("fixture_id") != fixture.fixture_id
            or value.get("fixture_record_id") != fixture.id
            or value.get("provider_fixture_id") != fixture.provider_fixture_id
            or value.get("provider_calls") != 1
        ):
            continue
        attempt_raw = value.get("attempt")
        try:
            observed_at = parse_utc(
                str(value.get("observed_at")),
                field="result_observation_observed_at",
            )
        except (TypeError, ValueError):
            continue
        # A future object is outside this decision's information set.  Exclude
        # it before validating any other metadata so it cannot throttle or
        # otherwise perturb the present settlement attempt.
        if observed_at > now:
            continue
        if (
            not isinstance(attempt_raw, int)
            or isinstance(attempt_raw, bool)
            or not 1 <= attempt_raw <= 5
            or value.get("availability")
            not in {availability.value for availability in DataAvailability}
        ):
            continue
        observation_hash = canonical_sha256(value)
        completions = completions_by_observation.get(observation_hash, [])
        matching_completions: list[tuple[dict[str, object], datetime]] = []
        for completion in completions:
            if (
                completion.get("fixture_id") != fixture.fixture_id
                or completion.get("fixture_record_id") != fixture.id
                or completion.get("attempt") != attempt_raw
            ):
                continue
            try:
                candidate_completed_at = parse_utc(
                    str(completion.get("completed_at")),
                    field="result_completion_completed_at",
                )
            except (TypeError, ValueError):
                continue
            if (
                candidate_completed_at == observed_at
                and candidate_completed_at <= now
            ):
                matching_completions.append(
                    (completion, candidate_completed_at)
                )
        if len(matching_completions) != 1:
            continue
        completion, completed_at = matching_completions[0]
        guard_hash = completion.get("guard_sha256")
        guard = guards_by_hash.get(str(guard_hash))
        try:
            guarded_at = parse_utc(
                str(guard.get("guarded_at") if guard is not None else None),
                field="result_guard_guarded_at",
            )
        except (TypeError, ValueError):
            continue
        if (
            guard is None
            or guard.get("guard_id") != guard_id(attempt_raw)
            or guard.get("fixture_id") != fixture.fixture_id
            or guard.get("fixture_record_id") != fixture.id
            or guard.get("provider_fixture_id") != fixture.provider_fixture_id
            or guard.get("attempt") != attempt_raw
            or guard.get("operation") != "VERIFY_FINAL_RESULT"
            or guarded_at > observed_at
            or observed_at != completed_at
            or guarded_at > now
            or completed_at > now
        ):
            continue
        observations.append((attempt_raw, observed_at))
    attempts = [attempt for attempt, _observed_at in observations]
    if len(attempts) != len(set(attempts)):
        raise RuntimeError("PREQUENTIAL_RESULT_OBSERVATION_ATTEMPT_AMBIGUOUS")
    if observations:
        latest_observed = max(
            observed_at for _attempt, observed_at in observations
        )
        if now - latest_observed < timedelta(hours=6):
            return None, 0
    attempt = max(attempts, default=0) + 1
    if attempt > 5:
        return None, 0
    unresolved_guards: list[dict[str, object]] = []
    for value in guard_values:
        if (
            value.get("schema_version")
            != "prequential-provider-call-guard-v1"
            or value.get("guard_id") != guard_id(attempt)
            or value.get("fixture_id") != fixture.fixture_id
            or value.get("fixture_record_id") != fixture.id
            or value.get("provider_fixture_id") != fixture.provider_fixture_id
            or value.get("attempt") != attempt
            or value.get("operation") != "VERIFY_FINAL_RESULT"
        ):
            continue
        try:
            guarded_at = parse_utc(
                str(value.get("guarded_at")),
                field="result_guard_guarded_at",
            )
        except (TypeError, ValueError):
            continue
        if guarded_at <= now:
            unresolved_guards.append(value)
    if unresolved_guards:
        raise RuntimeError(
            "PREQUENTIAL_PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED:"
            f"{fixture.fixture_id}:{attempt}"
        )
    stored_guard = repository.put_manifest(
        "provider-call-guards",
        {
            "schema_version": "prequential-provider-call-guard-v1",
            "fixture_id": fixture.fixture_id,
            "fixture_record_id": fixture.id,
            "provider_fixture_id": fixture.provider_fixture_id,
            "attempt": attempt,
            "operation": "VERIFY_FINAL_RESULT",
            "guard_id": guard_id(attempt),
            "guarded_at": now.isoformat(),
        },
    )
    if not stored_guard.inserted:
        raise RuntimeError(
            "PREQUENTIAL_PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED:"
            f"{fixture.fixture_id}:{attempt}"
        )
    result = provider.get_fixtures(
        fixture_id=int(fixture.provider_fixture_id)
    )
    observed_at = _utc(result.received_at or result.observed_at)
    record = _provider_result_record(result, fixture.provider_fixture_id)
    observation = {
        "schema_version": "prequential-result-observation-v1",
        "provider": fixture.provider,
        "fixture_id": fixture.fixture_id,
        "fixture_record_id": fixture.id,
        "provider_fixture_id": fixture.provider_fixture_id,
        "attempt": attempt,
        "observed_at": observed_at.isoformat(),
        "availability": result.availability.value,
        "http_status": result.http_status,
        "record": dict(record) if record is not None else None,
        "provider_calls": 1,
    }
    stored = repository.put_manifest("result-observations", observation)
    repository.put_manifest(
        "provider-call-completions",
        {
            "schema_version": "prequential-provider-call-completion-v1",
            "guard_sha256": stored_guard.sha256,
            "observation_sha256": stored.sha256,
            "fixture_id": fixture.fixture_id,
            "fixture_record_id": fixture.id,
            "attempt": attempt,
            "completed_at": observed_at.isoformat(),
        },
    )
    if (
        result.availability is not DataAvailability.PRESENT
        or record is None
    ):
        return None, 1
    return (
        _verified_result_from_record(
            fixture=fixture,
            record=record,
            verified_at=observed_at,
            source_hash=stored.sha256,
            latest_settlement=latest_settlement,
        ),
        1,
    )


def run_settle(
    *,
    engine: Engine,
    artifacts: PrequentialArtifactRepository,
    config: Mapping[str, object],
    output: Path,
    now: datetime,
    code_revision: str,
    provider: ApiFootballProvider | None,
) -> dict[str, object]:
    contract_hash = canonical_sha256(_feature_contract(config))
    sql = PrequentialSQLRepository(engine)
    factory = _restore_factory(
        sql,
        artifacts,
        now=now,
        feature_contract_hash=contract_hash,
        code_revision=code_revision,
    )
    predictions = factory.predictions.predictions
    frozen_fixture_record_ids = {
        prediction.fixture_record_id
        for prediction in predictions
        if prediction.status is PredictionStatus.FROZEN
    }
    latest_settlements: dict[str, FixtureSettlementRecord] = {}
    for settlement in factory.settlements.settlements:
        latest_settlements[settlement.result.fixture_record_id] = settlement
    eligible = sorted(
        [
        fixture
        for fixture in _fixture_records(
            engine,
            fixture_record_ids=frozen_fixture_record_ids,
            as_of=now,
        )
        if _utc_db(fixture.kickoff_at) + timedelta(minutes=90) < now
        and (
            fixture.id not in latest_settlements
            or latest_settlements[fixture.id].effective_status
            is PredictionStatus.SETTLED
        )
        ],
        key=lambda fixture: (_utc_db(fixture.kickoff_at), fixture.fixture_id),
    )
    settlement_policy = config.get("settlement")
    max_calls = 10
    if isinstance(settlement_policy, Mapping):
        candidate = settlement_policy.get("max_provider_calls_per_run")
        if isinstance(candidate, int) and candidate >= 0:
            max_calls = candidate
    first_event = len(factory.ledger.events)
    provider_calls = 0
    inserted = 0
    scores_inserted = 0
    for fixture in eligible:
        if provider is None or provider_calls >= max_calls:
            break
        result, calls = _collect_result(
            repository=artifacts,
            provider=provider,
            fixture=fixture,
            now=now,
            latest_settlement=latest_settlements.get(fixture.id),
        )
        provider_calls += calls
        if result is None:
            continue
        settlement, scores, created = factory.settle(
            result,
            settled_at=max(now, result.verified_at),
        )
        if not created:
            continue
        sql.append_settlement(settlement)
        scores_inserted += sql.append_scores(scores)
        inserted += 1
        latest_settlements[fixture.id] = settlement
    if inserted:
        missingness_by_prediction: dict[str, Mapping[str, bool]] = {}
        for prediction in factory.predictions.predictions:
            if prediction.feature_snapshot_id is None:
                missingness_by_prediction[prediction.prediction_id] = {}
                continue
            snapshot = factory.features.get(prediction.feature_snapshot_id)
            missingness_by_prediction[prediction.prediction_id] = (
                snapshot.missingness if snapshot is not None else {}
            )
        metric_rows = segmented_metrics(
            predictions=factory.predictions.predictions,
            scores=factory.settlements.scores,
            missingness_by_prediction=missingness_by_prediction,
        )
        measured_at = max(
            (now, *(score.scored_at for score in factory.settlements.scores))
        )
        for row in metric_rows:
            sql.append_metric_snapshot(row, measured_at=measured_at)
    sql.append_events(factory.ledger.events[first_event:])
    return _write_report(
        output / "settlement-report.json",
        {
            "schema_version": "prequential-settlement-report-v1",
            "generated_at": now.isoformat(),
            "eligible_fixtures": len(eligible),
            "settlements_inserted": inserted,
            "scores_inserted": scores_inserted,
            "provider_calls": provider_calls,
            "odds_api_credits": 0,
            "counts": sql.counts(),
            "ledger": factory.ledger.audit(),
        },
    )


def _last_successful_training(
    engine: Engine,
    model_id: str,
    *,
    as_of: datetime,
) -> datetime | None:
    cutoff = _utc(as_of)
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(PrequentialTrainingRunModel).where(
                    PrequentialTrainingRunModel.model_id == model_id,
                    PrequentialTrainingRunModel.status
                    == "CHALLENGER_VERSION_CREATED",
                    PrequentialTrainingRunModel.finished_at <= cutoff,
                )
            )
        )
    if not rows:
        return None
    return max(_utc_db(row.finished_at) for row in rows)


def _training_parent_model(
    factory: PrequentialLearningFactory,
    *,
    model_id: str,
    as_of: datetime,
) -> ModelVersion:
    cutoff = _utc(as_of)
    candidates = [
        model
        for model in factory.models.values()
        if model.model_id == model_id
        and model.created_at <= cutoff
        and (
            model.training_cutoff is None
            or model.training_cutoff <= cutoff
        )
    ]
    if not candidates:
        raise RuntimeError("PREQUENTIAL_GLOBAL_CHALLENGER_MISSING")
    latest_created = max(model.created_at for model in candidates)
    heads = [model for model in candidates if model.created_at == latest_created]
    if len({model.version for model in heads}) != 1:
        raise ValueError("PREQUENTIAL_TRAINING_PARENT_AMBIGUOUS")
    return heads[0]


def _training_run_id(
    *,
    model_id: str,
    previous_version: str,
    training_cutoff: datetime,
    status: str,
    manifest_hash: str | None,
    code_revision: str,
) -> str:
    cutoff = parse_utc(training_cutoff.isoformat(), field="training_cutoff")
    return "training-" + canonical_sha256(
        {
            "model_id": model_id,
            "previous_version": previous_version,
            "training_cutoff": cutoff.isoformat(),
            "status": status,
            "manifest": manifest_hash,
            "code_revision": code_revision,
        }
    )


def run_train(
    *,
    engine: Engine,
    artifacts: PrequentialArtifactRepository,
    config: Mapping[str, object],
    output: Path,
    now: datetime,
    code_revision: str,
) -> dict[str, object]:
    contract_hash = canonical_sha256(_feature_contract(config))
    sql = PrequentialSQLRepository(engine)
    factory = _restore_factory(
        sql,
        artifacts,
        now=now,
        feature_contract_hash=contract_hash,
        code_revision=code_revision,
    )
    previous = _training_parent_model(
        factory,
        model_id="challenger-global_five_leagues",
        as_of=now,
    )
    first_event = len(factory.ledger.events)
    decision = factory.train(
        model_id=previous.model_id,
        previous_version=previous.version,
        training_cutoff=now,
        code_revision=code_revision,
        last_training_at=_last_successful_training(
            engine,
            previous.model_id,
            as_of=now,
        ),
    )
    if decision.next_model is not None:
        sql.append_model(decision.next_model)
    training_run_id = _training_run_id(
        model_id=previous.model_id,
        previous_version=previous.version,
        training_cutoff=now,
        status=decision.status,
        manifest_hash=(
            decision.manifest.manifest_hash
            if decision.manifest is not None
            else None
        ),
        code_revision=code_revision,
    )
    sql.append_training_decision(
        training_run_id=training_run_id,
        model_id=previous.model_id,
        previous_version=previous.version,
        decision=decision,
        started_at=now,
        finished_at=now,
        code_revision=code_revision,
    )
    sql.append_events(factory.ledger.events[first_event:])
    return _write_report(
        output / "training-report.json",
        {
            "schema_version": "prequential-training-report-v1",
            "generated_at": now.isoformat(),
            "status": decision.status,
            "eligible_fixtures": decision.eligible_fixtures,
            "represented_leagues": decision.represented_leagues,
            "previous_version": previous.version,
            "next_version": (
                decision.next_model.version
                if decision.next_model is not None
                else None
            ),
            "manifest_hash": (
                decision.manifest.manifest_hash
                if decision.manifest is not None
                else None
            ),
            "reference_status": "REFERENCE_UNCHANGED",
            "provider_calls": 0,
            "odds_api_credits": 0,
            "counts": sql.counts(),
            "ledger": factory.ledger.audit(),
        },
    )


def _manifest_string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"PREQUENTIAL_REPLAY_{field.upper()}_INVALID")
    return tuple(value)


def _verify_replay_artifacts(
    *,
    artifacts: PrequentialArtifactRepository,
    rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    def unique_rows(
        table: str,
        key: str,
    ) -> dict[str, Mapping[str, object]]:
        output: dict[str, Mapping[str, object]] = {}
        for item in rows.get(table, ()):
            identity = str(item.get(key, ""))
            if not identity or identity in output:
                raise ValueError(
                    f"PREQUENTIAL_REPLAY_{table.upper()}_{key.upper()}_INVALID"
                )
            output[identity] = item
        return output

    model_rows: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in rows.get("prequential_model_versions", ()):
        model_key = (str(row["model_id"]), str(row["model_version"]))
        if not all(model_key) or model_key in model_rows:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_VERSION_DUPLICATE")
        model_rows[model_key] = row
    for model_key, row in model_rows.items():
        try:
            scope = ModelScope(str(row["scope"]))
            role = ModelRole(str(row["role"]))
            created_at = parse_utc(
                str(row["created_at"]),
                field="replay_model_created_at",
            )
            roots = initial_model_versions(
                created_at=created_at,
                feature_contract_hash=str(row["feature_contract_hash"]),
                code_revision=str(row["code_revision"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_ROOT_INVALID") from error
        expected_root = next(
            model
            for model in roots
            if model.scope is scope and model.role is role
        )
        if model_key[0] != expected_root.model_id:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_SCOPE_ID_MISMATCH")
        is_root = model_key[1] == expected_root.version
        if role is ModelRole.REFERENCE or is_root:
            if (
                not is_root
                or str(row.get("artifact_sha256"))
                != expected_root.artifact_sha256
                or row.get("artifact_r2_key") is not None
                or row.get("training_cutoff") is not None
                or row.get("parent_version_id") is not None
                or str(row.get("status")) != expected_root.status.value
            ):
                raise ValueError("PREQUENTIAL_REPLAY_MODEL_ROOT_INVALID")
        elif (
            role is not ModelRole.CHALLENGER
            or str(row.get("status")) != ModelStatus.ACTIVE.value
            or row.get("parent_version_id") is None
            or row.get("training_cutoff") is None
            or row.get("artifact_r2_key") is None
        ):
            raise ValueError("PREQUENTIAL_REPLAY_CHALLENGER_VERSION_INVALID")
    model_rows_by_record_id: dict[str, tuple[tuple[str, str], Mapping[str, object]]] = {}
    for model_key, row in model_rows.items():
        record_id = str(row.get("id", ""))
        if not record_id or record_id in model_rows_by_record_id:
            raise ValueError("PREQUENTIAL_REPLAY_MODEL_RECORD_ID_INVALID")
        model_rows_by_record_id[record_id] = (model_key, row)
    children_by_parent: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for model_key, row in model_rows.items():
        if str(row.get("role")) != ModelRole.CHALLENGER.value:
            continue
        parent_id_raw = row.get("parent_version_id")
        if parent_id_raw is None:
            continue
        parent = model_rows_by_record_id.get(str(parent_id_raw))
        if parent is None or parent[0][0] != model_key[0]:
            raise ValueError("PREQUENTIAL_REPLAY_CHALLENGER_PARENT_INVALID")
        parent_created_at = parse_utc(
            str(parent[1].get("created_at")),
            field="challenger_parent_created_at",
        )
        child_created_at = parse_utc(
            str(row.get("created_at")),
            field="challenger_child_created_at",
        )
        if parent_created_at >= child_created_at:
            raise ValueError("PREQUENTIAL_REPLAY_CHALLENGER_CHAIN_TIME_INVALID")
        children_by_parent[(model_key[0], str(parent_id_raw))].append(model_key)
    if any(len(children) != 1 for children in children_by_parent.values()):
        raise ValueError("PREQUENTIAL_REPLAY_CHALLENGER_MODEL_CHAIN_FORK")
    settlement_rows = unique_rows(
        "prequential_fixture_settlements",
        "settlement_id",
    )
    snapshot_rows = unique_rows(
        "prequential_feature_snapshots",
        "snapshot_id",
    )
    ledger_rows = tuple(rows.get("prequential_ledger_events", ()))
    replay_snapshots: tuple[FeatureSnapshot, ...] = tuple(
        FeatureSnapshot(
            snapshot_id=snapshot_id,
            fixture_record_id=str(item["fixture_record_id"]),
            fixture_id=str(item["fixture_id"]),
            competition=str(item["competition"]),
            market=PredictionMarket(str(item["market"])),
            cutoff_name=CutoffName(str(item["cutoff_name"])),
            cutoff_at=parse_utc(
                str(item["cutoff_at"]),
                field="replay_snapshot_cutoff_at",
            ),
            created_at=parse_utc(
                str(item["created_at"]),
                field="replay_snapshot_created_at",
            ),
            feature_contract_version=str(item["feature_contract_version"]),
            feature_contract_hash=str(item["feature_contract_hash"]),
            values=cast(dict[str, object], item["values"]),
            missingness=cast(dict[str, bool], item["missingness"]),
            provenance=cast(dict[str, dict[str, object]], item["provenance"]),
            quality=cast(dict[str, object], item["quality"]),
            code_revision=str(item["code_revision"]),
            r2_manifest_key=str(item["r2_manifest_key"]),
            supersedes_id=(
                str(item["supersedes_id"])
                if item.get("supersedes_id") is not None
                else None
            ),
            status=str(item["status"]),
        )
        for snapshot_id, item in snapshot_rows.items()
    )
    snapshot_chain = FeatureSnapshotRegistry()
    pending_snapshots = list(replay_snapshots)
    while pending_snapshots:
        progressed = False
        for candidate in sorted(
            tuple(pending_snapshots),
            key=lambda value: (value.created_at, value.snapshot_id),
        ):
            if (
                candidate.supersedes_id is not None
                and snapshot_chain.get(candidate.supersedes_id) is None
            ):
                continue
            try:
                snapshot_chain.append(candidate)
            except ValueError as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_CHAIN_INVALID"
                ) from error
            pending_snapshots.remove(candidate)
            progressed = True
        if not progressed:
            raise ValueError("PREQUENTIAL_REPLAY_FEATURE_SNAPSHOT_CHAIN_INVALID")
    replay_settlements: tuple[FixtureSettlementRecord, ...] = tuple(
        FixtureSettlementRecord(
            settlement_id=settlement_id,
            result=VerifiedFixtureResult(
                fixture_record_id=str(item["fixture_record_id"]),
                fixture_id=str(item["fixture_id"]),
                competition=str(item["competition"]),
                kickoff_at=parse_utc(
                    str(item["kickoff_at"]),
                    field="replay_settlement_kickoff_at",
                ),
                status=FixtureResultStatus(str(item["result_status"])),
                verified_at=parse_utc(
                    str(item["verified_at"]),
                    field="replay_settlement_verified_at",
                ),
                home_goals=(
                    int(cast(int | str, item["home_goals"]))
                    if item.get("home_goals") is not None
                    else None
                ),
                away_goals=(
                    int(cast(int | str, item["away_goals"]))
                    if item.get("away_goals") is not None
                    else None
                ),
                result_version=int(cast(int | str, item["result_version"])),
                source_hash=str(item["source_hash"]),
            ),
            settled_at=parse_utc(
                str(item["settled_at"]),
                field="replay_settlement_settled_at",
            ),
            effective_status=PredictionStatus(str(item["effective_status"])),
            supersedes_id=(
                str(item["supersedes_id"])
                if item.get("supersedes_id") is not None
                else None
            ),
        )
        for settlement_id, item in settlement_rows.items()
    )
    settlement_chain = SettlementRegistry()
    for settlement in sorted(
        replay_settlements,
        key=lambda value: (
            value.result.fixture_record_id,
            value.result.result_version,
            value.settled_at,
            value.settlement_id,
        ),
    ):
        settlement_chain.restore(settlement)

    replay_snapshots_by_id = {
        snapshot.snapshot_id: snapshot for snapshot in replay_snapshots
    }
    for settlement in replay_settlements:
        result = settlement.result
        try:
            result_provider_identity = verify_result_observation_artifact(
                artifacts,
                result,
            )
        except ValueError as error:
            detail = str(error)
            if detail.startswith("PREQUENTIAL_"):
                detail = detail.removeprefix("PREQUENTIAL_")
            raise ValueError(f"PREQUENTIAL_REPLAY_{detail}") from error
        expected_provider_identities: set[tuple[str, str]] = set()
        for prediction_row in rows.get("prequential_predictions", ()):
            if (
                str(prediction_row.get("status"))
                != PredictionStatus.FROZEN.value
                or str(prediction_row.get("fixture_record_id"))
                != result.fixture_record_id
                or str(prediction_row.get("fixture_id")) != result.fixture_id
            ):
                continue
            snapshot = replay_snapshots_by_id.get(
                str(prediction_row.get("feature_snapshot_id"))
            )
            team_projection = (
                snapshot.values.get("team") if snapshot is not None else None
            )
            if not isinstance(team_projection, Mapping):
                continue
            provider = str(team_projection.get("provider", "")).strip()
            provider_fixture_id = str(
                team_projection.get("provider_fixture_id", "")
            ).strip()
            if provider and provider_fixture_id:
                expected_provider_identities.add(
                    (provider, provider_fixture_id)
                )
        if (
            expected_provider_identities
            and expected_provider_identities != {result_provider_identity}
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_RESULT_FIXTURE_IDENTITY_MISMATCH"
            )
        observation_key = (
            f"{artifacts.namespace}/result-observations/"
            f"{result.source_hash}.json"
        )
        try:
            raw_observation = artifacts.read_verified(
                observation_key,
                result.source_hash,
            )
            observation = json.loads(raw_observation)
        except (
            ArtifactIntegrityError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise ValueError(
                "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_BYTES_INVALID"
            ) from error
        if not isinstance(observation, dict) or observation.get(
            "schema_version"
        ) != "prequential-result-observation-v1":
            raise ValueError(
                "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_BODY_INVALID"
            )
        record = observation.get("record")
        provider_fixture_id = str(observation.get("provider_fixture_id", ""))
        if (
            observation.get("fixture_id") != result.fixture_id
            or observation.get("fixture_record_id") != result.fixture_record_id
            or observation.get("availability") != DataAvailability.PRESENT.value
            or observation.get("provider_calls")
            != (
                0
                if observation.get("origin") == "SYNTHETIC_MECHANICS_ONLY"
                else 1
            )
            or (
                observation.get("origin") == "SYNTHETIC_MECHANICS_ONLY"
                and (
                    not result.fixture_id.startswith("synthetic:")
                    or not result.fixture_record_id.startswith("synthetic-record-")
                )
            )
            or not isinstance(record, Mapping)
            or parse_utc(
                str(observation.get("observed_at")),
                field="result_observation_observed_at",
            )
            != result.verified_at
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_PROJECTION_MISMATCH"
            )
        fixture_value = record.get("fixture")
        goals = record.get("goals")
        if not isinstance(fixture_value, Mapping) or str(
            fixture_value.get("id", "")
        ) != provider_fixture_id:
            raise ValueError(
                "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_PROJECTION_MISMATCH"
            )
        status_value = fixture_value.get("status")
        short = (
            str(status_value.get("short", "")).strip().upper()
            if isinstance(status_value, Mapping)
            else ""
        )
        if short in FINAL_PROVIDER_STATUSES:
            expected_statuses = {
                FixtureResultStatus.FINISHED,
                FixtureResultStatus.CORRECTED,
            }
            if (
                result.status not in expected_statuses
                or not isinstance(goals, Mapping)
                or goals.get("home") != result.home_goals
                or goals.get("away") != result.away_goals
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_PROJECTION_MISMATCH"
                )
        else:
            expected_void_status = (
                FixtureResultStatus.ABANDONED
                if short == "ABD"
                else FixtureResultStatus.CANCELLED
                if short in VOID_PROVIDER_STATUSES
                else None
            )
            if expected_void_status is None or result.status is not expected_void_status:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_RESULT_OBSERVATION_PROJECTION_MISMATCH"
                )

    def require_training_event(
        *,
        kind: str,
        model_id: str,
        model_version: str,
        evidence_hashes: tuple[str, ...],
        recorded_at: datetime,
    ) -> None:
        matches = tuple(
            event
            for event in ledger_rows
            if str(event.get("kind")) == kind
            and str(event.get("model_id")) == model_id
            and str(event.get("model_version")) == model_version
            and parse_utc(
                str(event.get("recorded_at")),
                field="training_event_recorded_at",
            )
            == recorded_at
            and isinstance(event.get("evidence_hashes"), list)
            and tuple(
                str(value)
                for value in cast(list[object], event["evidence_hashes"])
            )
            == evidence_hashes
        )
        if len(matches) != 1:
            raise ValueError("PREQUENTIAL_REPLAY_TRAINING_LEDGER_EDGE_MISMATCH")

    verified_active_challenger_links: dict[tuple[str, str], int] = defaultdict(int)
    training_decision_keys: set[tuple[str, datetime]] = set()
    for row in rows.get("prequential_training_runs", ()):
        manifest: TrainingDatasetManifest | None = None
        previous_model_row: Mapping[str, object] | None = None
        expected_examples: tuple[EligibleTrainingExample, ...] = ()
        expected_outcome_counts: dict[str, dict[str, int]] = {}
        expected_fixture_count = 0
        expected_example_count = 0
        expected_competitions: tuple[str, ...] = ()
        model_id = str(row.get("model_id"))
        previous_version = str(row.get("previous_model_version"))
        code_revision = str(row.get("code_revision", ""))
        if not code_revision:
            raise ValueError("PREQUENTIAL_REPLAY_TRAINING_CODE_REVISION_INVALID")
        training_cutoff = parse_utc(
            str(row.get("training_cutoff")),
            field="training_run_cutoff",
        )
        training_decision_key = (model_id, training_cutoff)
        if training_decision_key in training_decision_keys:
            raise ValueError("PREQUENTIAL_REPLAY_TRAINING_HEAD_AMBIGUOUS")
        training_decision_keys.add(training_decision_key)
        manifest_hash_raw = row.get("dataset_manifest_hash")
        manifest_key_raw = row.get("dataset_manifest_r2_key")
        has_manifest = manifest_hash_raw is not None or manifest_key_raw is not None
        if (manifest_hash_raw is None) != (manifest_key_raw is None):
            raise ValueError(
                "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_REFERENCE_INVALID"
            )
        if has_manifest:
            manifest_hash = str(manifest_hash_raw)
            manifest_key = str(manifest_key_raw)
            prefix = f"{artifacts.namespace}/training-manifests/"
            filename = manifest_key.rsplit("/", 1)[-1]
            if (
                not manifest_key.startswith(prefix)
                or not filename.endswith(".json")
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_KEY_INVALID"
                )
            storage_sha256 = filename.removesuffix(".json")
            try:
                raw = artifacts.read_verified(manifest_key, storage_sha256)
            except ArtifactIntegrityError as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_BYTES_INVALID"
                ) from error
            try:
                body = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_JSON_INVALID"
                ) from error
            if not isinstance(body, dict) or body.get("schema_version") != (
                "prequential-training-dataset-v1"
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_BODY_INVALID"
                )
            hyperparameters = body.get("hyperparameters")
            training_metrics = body.get("training_metrics")
            if not isinstance(hyperparameters, dict) or not isinstance(
                training_metrics,
                dict,
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_BODY_INVALID"
                )
            if hyperparameters != {
                "family": "EMPIRICAL_REGULARIZED_CHALLENGER_V1",
                "smoothing": 1.0,
            }:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_HYPERPARAMETERS_MISMATCH"
                )
            try:
                manifest = TrainingDatasetManifest(
                    manifest_id=str(body["manifest_id"]),
                    created_at=parse_utc(
                        str(body["created_at"]),
                        field="training_manifest_created_at",
                    ),
                    training_cutoff=parse_utc(
                        str(body["training_cutoff"]),
                        field="training_manifest_cutoff",
                    ),
                    fixture_ids=_manifest_string_tuple(
                        body.get("fixture_ids"),
                        field="training_manifest_fixture_ids",
                    ),
                    settlement_ids=_manifest_string_tuple(
                        body.get("settlement_ids"),
                        field="training_manifest_settlement_ids",
                    ),
                    competitions=_manifest_string_tuple(
                        body.get("competitions"),
                        field="training_manifest_competitions",
                    ),
                    feature_snapshot_ids=_manifest_string_tuple(
                        body.get("feature_snapshot_ids"),
                        field="training_manifest_feature_snapshot_ids",
                    ),
                    feature_contract_hash=str(body["feature_contract_hash"]),
                    hyperparameters=hyperparameters,
                    code_revision=str(body["code_revision"]),
                    r2_key=manifest_key,
                    training_metrics=training_metrics,
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_BODY_INVALID"
                ) from error
            expected_body = {
                "schema_version": "prequential-training-dataset-v1",
                **manifest.as_dict(include_storage=False),
            }
            if body != expected_body or manifest.manifest_hash != manifest_hash:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_HASH_INVALID"
                )
            previous_model_row = model_rows.get((model_id, previous_version))
            if previous_model_row is None:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PREVIOUS_MODEL_MISSING"
                )
            try:
                previous_scope = ModelScope(str(previous_model_row["scope"]))
            except (KeyError, ValueError) as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PREVIOUS_MODEL_INVALID"
                ) from error
            if (
                str(previous_model_row.get("role")) != ModelRole.CHALLENGER.value
                or str(previous_model_row.get("feature_contract_hash"))
                != manifest.feature_contract_hash
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PREVIOUS_MODEL_INVALID"
                )
            previous_created_at = parse_utc(
                str(previous_model_row.get("created_at")),
                field="training_previous_model_created_at",
            )
            previous_cutoff_raw = previous_model_row.get("training_cutoff")
            previous_cutoff = (
                parse_utc(
                    str(previous_cutoff_raw),
                    field="training_previous_model_cutoff",
                )
                if previous_cutoff_raw is not None
                else None
            )
            if previous_created_at > manifest.training_cutoff or (
                previous_cutoff is not None
                and previous_cutoff > manifest.training_cutoff
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_PARENT_MODEL_AFTER_TRAINING_CUTOFF"
                )

            expected_examples = eligible_training_examples(
                settlements=replay_settlements,
                snapshots=replay_snapshots,
                training_cutoff=manifest.training_cutoff,
                required_feature_contract_hash=manifest.feature_contract_hash,
            )
            expected_competition = FIVE_LEAGUE_NAMES.get(previous_scope)
            if expected_competition is not None:
                expected_examples = tuple(
                    example
                    for example in expected_examples
                    if example.competition == expected_competition
                )
            fixture_head_by_id = {
                example.fixture_id: example for example in expected_examples
            }
            fixture_examples = tuple(
                fixture_head_by_id[fixture_id]
                for fixture_id in sorted(fixture_head_by_id)
            )
            expected_fixture_ids = tuple(
                example.fixture_id for example in fixture_examples
            )
            expected_settlement_ids = tuple(
                example.settlement_id for example in fixture_examples
            )
            expected_snapshot_ids = tuple(
                example.snapshot_id for example in expected_examples
            )
            expected_competitions = tuple(
                sorted({example.competition for example in expected_examples})
            )
            if (
                manifest.fixture_ids != expected_fixture_ids
                or manifest.settlement_ids != expected_settlement_ids
                or manifest.feature_snapshot_ids != expected_snapshot_ids
                or manifest.competitions != expected_competitions
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_SELECTION_MISMATCH"
                )
            expected_manifest_id = training_manifest_record_id(
                previous_model_registry_hash=str(
                    previous_model_row.get("registry_hash")
                ),
                training_cutoff=manifest.training_cutoff,
                examples=expected_examples,
            )
            if manifest.manifest_id != expected_manifest_id:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_ID_MISMATCH"
                )
            expected_outcome_counts = {}
            for example in expected_examples:
                market_counts = expected_outcome_counts.setdefault(
                    example.market,
                    {},
                )
                market_counts[example.outcome] = (
                    market_counts.get(example.outcome, 0) + 1
                )
            expected_fixture_count = len(fixture_examples)
            expected_example_count = len(expected_examples)
            expected_training_metrics = {
                "fixtures": expected_fixture_count,
                "examples": expected_example_count,
                "represented_leagues": len(expected_competitions),
                "outcomes_by_market": {
                    market: dict(sorted(counts.items()))
                    for market, counts in sorted(
                        expected_outcome_counts.items()
                    )
                },
            }
            if training_metrics != expected_training_metrics:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_METRICS_MISMATCH"
                )
            projected = (
                _manifest_string_tuple(
                    row.get("fixture_ids"),
                    field="training_run_fixture_ids",
                )
                == manifest.fixture_ids
                and _manifest_string_tuple(
                    row.get("settlement_ids"),
                    field="training_run_settlement_ids",
                )
                == manifest.settlement_ids
                and _manifest_string_tuple(
                    row.get("competitions"),
                    field="training_run_competitions",
                )
                == manifest.competitions
                and _manifest_string_tuple(
                    row.get("feature_snapshot_ids"),
                    field="training_run_feature_snapshot_ids",
                )
                == manifest.feature_snapshot_ids
                and row.get("hyperparameters") == hyperparameters
                and row.get("training_metrics") == training_metrics
                and str(row.get("code_revision")) == manifest.code_revision
                and parse_utc(
                    str(row.get("training_cutoff")),
                    field="training_run_cutoff",
                )
                == manifest.training_cutoff
                and parse_utc(
                    str(row.get("finished_at")),
                    field="training_run_finished_at",
                )
                == manifest.created_at
            )
            if not projected:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_PROJECTION_MISMATCH"
                )
            newly_eligible = tuple(
                example
                for example in expected_examples
                if previous_cutoff is None
                or example.settled_at > previous_cutoff
            )
            new_fixture_ids = {
                example.fixture_id for example in newly_eligible
            }
            new_competitions = {
                example.competition for example in newly_eligible
            }
            if (
                str(row.get("status")) != "CHALLENGER_VERSION_CREATED"
                or int(cast(int | str, row.get("eligible_fixtures")))
                != len(new_fixture_ids)
                or int(cast(int | str, row.get("represented_leagues")))
                != len(new_competitions)
                or len(new_fixture_ids) < MINIMUM_NEW_FIXTURES
                or len(new_competitions) < MINIMUM_REPRESENTED_LEAGUES
                or row.get("promotion_status") != PROMOTION_LOCKED
                or parse_utc(
                    str(row.get("started_at")),
                    field="training_run_started_at",
                )
                != manifest.training_cutoff
                or parse_utc(
                    str(row.get("finished_at")),
                    field="training_run_finished_at",
                )
                != manifest.training_cutoff
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_DECISION_MISMATCH"
                )
        else:
            if any(
                row.get(field) not in (None, [], {})
                for field in (
                    "fixture_ids",
                    "settlement_ids",
                    "competitions",
                    "feature_snapshot_ids",
                    "hyperparameters",
                    "training_metrics",
                )
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PROJECTION_WITHOUT_MANIFEST"
                )
            previous_model_row = model_rows.get((model_id, previous_version))
            if previous_model_row is None or str(
                previous_model_row.get("role")
            ) != ModelRole.CHALLENGER.value:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PREVIOUS_MODEL_INVALID"
                )
            try:
                previous_scope = ModelScope(str(previous_model_row["scope"]))
            except (KeyError, ValueError) as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_PREVIOUS_MODEL_INVALID"
                ) from error
            previous_created_at = parse_utc(
                str(previous_model_row.get("created_at")),
                field="training_previous_model_created_at",
            )
            previous_cutoff_raw = previous_model_row.get("training_cutoff")
            previous_cutoff = (
                parse_utc(
                    str(previous_cutoff_raw),
                    field="training_previous_model_cutoff",
                )
                if previous_cutoff_raw is not None
                else None
            )
            if previous_created_at > training_cutoff or (
                previous_cutoff is not None
                and previous_cutoff > training_cutoff
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_PARENT_MODEL_AFTER_TRAINING_CUTOFF"
                )
            if (
                row.get("next_model_version") is not None
                or row.get("promotion_status") != PROMOTION_LOCKED
                or parse_utc(
                    str(row.get("started_at")),
                    field="training_run_started_at",
                )
                != training_cutoff
                or parse_utc(
                    str(row.get("finished_at")),
                    field="training_run_finished_at",
                )
                != training_cutoff
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_DEFERRED_TRAINING_PROJECTION_MISMATCH"
                )
            successful_before = tuple(
                parse_utc(
                    str(candidate.get("finished_at")),
                    field="previous_training_finished_at",
                )
                for candidate in rows.get("prequential_training_runs", ())
                if candidate is not row
                and str(candidate.get("model_id")) == model_id
                and str(candidate.get("status"))
                == "CHALLENGER_VERSION_CREATED"
                and parse_utc(
                    str(candidate.get("finished_at")),
                    field="previous_training_finished_at",
                )
                < training_cutoff
            )
            last_successful_at = max(successful_before, default=None)
            if last_successful_at is not None and (
                training_cutoff - last_successful_at
                < MINIMUM_TRAINING_INTERVAL
            ):
                expected_status = "TRAINING_DEFERRED_FREQUENCY_LIMIT"
                expected_fixtures = 0
                expected_leagues = 0
                expected_reason = "ONE_TRAINING_PER_DAY_MAXIMUM"
            else:
                expected_examples = eligible_training_examples(
                    settlements=replay_settlements,
                    snapshots=replay_snapshots,
                    training_cutoff=training_cutoff,
                    required_feature_contract_hash=str(
                        previous_model_row["feature_contract_hash"]
                    ),
                )
                expected_competition = FIVE_LEAGUE_NAMES.get(previous_scope)
                if expected_competition is not None:
                    expected_examples = tuple(
                        example
                        for example in expected_examples
                        if example.competition == expected_competition
                    )
                newly_eligible = tuple(
                    example
                    for example in expected_examples
                    if previous_cutoff is None
                    or example.settled_at > previous_cutoff
                )
                expected_fixtures = len(
                    {example.fixture_id for example in newly_eligible}
                )
                expected_leagues = len(
                    {example.competition for example in newly_eligible}
                )
                if (
                    expected_fixtures >= MINIMUM_NEW_FIXTURES
                    and expected_leagues >= MINIMUM_REPRESENTED_LEAGUES
                ):
                    raise ValueError(
                        "PREQUENTIAL_REPLAY_TRAINING_MANIFEST_REQUIRED"
                    )
                expected_status = TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT
                expected_reason = (
                    f"MINIMUM_{MINIMUM_NEW_FIXTURES}_FIXTURES_"
                    f"AND_{MINIMUM_REPRESENTED_LEAGUES}_LEAGUES_REQUIRED"
                )
            if (
                str(row.get("status")) != expected_status
                or int(cast(int | str, row.get("eligible_fixtures")))
                != expected_fixtures
                or int(cast(int | str, row.get("represented_leagues")))
                != expected_leagues
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_DEFERRED_TRAINING_DECISION_MISMATCH"
                )
            deferred_evidence = canonical_sha256(
                {
                    "status": expected_status,
                    "eligible": expected_fixtures,
                    "leagues": expected_leagues,
                    "reason": expected_reason,
                    "model_id": model_id,
                    "previous_version": previous_version,
                    "training_cutoff": training_cutoff.isoformat(),
                    "code_revision": code_revision,
                }
            )
            deferred_events = tuple(
                event
                for event in ledger_rows
                if str(event.get("kind")) == "TRAINING_DEFERRED"
                and str(event.get("model_id")) == model_id
                and str(event.get("model_version")) == previous_version
                and parse_utc(
                    str(event.get("recorded_at")),
                    field="training_event_recorded_at",
                )
                == training_cutoff
                and event.get("evidence_hashes") == [deferred_evidence]
                and event.get("details") == {"status": expected_status}
            )
            if len(deferred_events) != 1:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_TRAINING_LEDGER_EDGE_MISMATCH"
                )

        expected_training_run_id = _training_run_id(
            model_id=model_id,
            previous_version=previous_version,
            training_cutoff=training_cutoff,
            status=str(row.get("status")),
            manifest_hash=(str(manifest_hash_raw) if has_manifest else None),
            code_revision=code_revision,
        )
        if (
            row.get("training_run_id") != expected_training_run_id
            or row.get("id") != expected_training_run_id
        ):
            raise ValueError("PREQUENTIAL_REPLAY_TRAINING_RUN_ID_MISMATCH")

        artifact_sha_raw = row.get("artifact_sha256")
        artifact_key_raw = row.get("artifact_r2_key")
        if (artifact_sha_raw is None) != (artifact_key_raw is None):
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_REFERENCE_INVALID"
            )
        if artifact_sha_raw is None:
            continue
        if not has_manifest:
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_WITHOUT_TRAINING_MANIFEST"
            )
        artifact_sha = str(artifact_sha_raw)
        artifact_key = str(artifact_key_raw)
        if not artifact_key.startswith(
            f"{artifacts.namespace}/challenger-models/"
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_KEY_INVALID"
            )
        try:
            artifact_raw = artifacts.read_verified(artifact_key, artifact_sha)
        except ArtifactIntegrityError as error:
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_BYTES_INVALID"
            ) from error
        try:
            artifact_body = json.loads(artifact_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_JSON_INVALID"
            ) from error
        if manifest is None or previous_model_row is None:
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_WITHOUT_TRAINING_MANIFEST"
            )
        expected_artifact_body = {
            "schema_version": "prequential-challenger-artifact-v1",
            "training_manifest_hash": manifest.manifest_hash,
            "training_cutoff": manifest.training_cutoff.isoformat(),
            "counts_by_market": {
                market: dict(sorted(counts.items()))
                for market, counts in sorted(expected_outcome_counts.items())
            },
            "support_fixtures": expected_fixture_count,
            "support_examples": expected_example_count,
            "competitions": list(expected_competitions),
            "promotion_status": PROMOTION_LOCKED,
        }
        if not isinstance(artifact_body, dict) or artifact_body != (
            expected_artifact_body
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_ARTIFACT_BODY_INVALID"
            )
        next_version = row.get("next_model_version")
        if (
            not isinstance(next_version, str)
            or next_version
            != challenger_model_version(
                training_cutoff=manifest.training_cutoff,
                artifact_sha256=artifact_sha,
            )
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_MODEL_ARTIFACT_MISMATCH"
            )
        model_row = model_rows.get((str(row["model_id"]), next_version))
        training_cutoff = manifest.training_cutoff
        if model_row is None or (
            model_row.get("artifact_sha256") != artifact_sha
            or model_row.get("artifact_r2_key") != artifact_key
            or str(model_row.get("scope"))
            != str(previous_model_row.get("scope"))
            or str(model_row.get("role")) != ModelRole.CHALLENGER.value
            or str(model_row.get("status")) != ModelStatus.ACTIVE.value
            or str(model_row.get("parent_version_id"))
            != str(previous_model_row.get("id"))
            or parse_utc(
                str(model_row.get("created_at")),
                field="challenger_model_created_at",
            )
            != training_cutoff
            or parse_utc(
                str(model_row.get("training_cutoff")),
                field="challenger_model_training_cutoff",
            )
            != training_cutoff
            or str(model_row.get("feature_contract_hash"))
            != manifest.feature_contract_hash
            or str(model_row.get("code_revision")) != manifest.code_revision
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_CHALLENGER_MODEL_ARTIFACT_MISMATCH"
            )
        next_registry_hash = str(model_row.get("registry_hash"))
        require_training_event(
            kind="CHALLENGER_TRAINING_STARTED",
            model_id=str(row["model_id"]),
            model_version=str(row["previous_model_version"]),
            evidence_hashes=(str(manifest_hash_raw),),
            recorded_at=training_cutoff,
        )
        require_training_event(
            kind="CHALLENGER_VERSION_CREATED",
            model_id=str(row["model_id"]),
            model_version=str(next_version),
            evidence_hashes=(str(manifest_hash_raw), next_registry_hash),
            recorded_at=training_cutoff,
        )
        require_training_event(
            kind="PROMOTION_BLOCKED",
            model_id=str(row["model_id"]),
            model_version=str(next_version),
            evidence_hashes=(next_registry_hash,),
            recorded_at=training_cutoff,
        )
        verified_active_challenger_links[(str(row["model_id"]), next_version)] += 1
        for prediction_row in rows.get("prequential_predictions", ()):
            if (
                str(prediction_row.get("status")) != "FROZEN"
                or str(prediction_row.get("model_id")) != str(row["model_id"])
                or str(prediction_row.get("model_version"))
                != str(next_version)
            ):
                continue
            try:
                expected_probabilities = challenger_probabilities_from_artifact(
                    artifact_body,
                    PredictionMarket(str(prediction_row.get("market"))),
                )
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "PREQUENTIAL_REPLAY_CHALLENGER_PROBABILITY_INVALID"
                ) from error
            actual_probabilities = prediction_row.get("probabilities")
            if not isinstance(actual_probabilities, Mapping) or any(
                not isinstance(actual_probabilities.get(label), (int, float))
                or not math.isclose(
                    float(cast(int | float, actual_probabilities[label])),
                    probability,
                    rel_tol=0.0,
                    abs_tol=1e-15,
                )
                for label, probability in expected_probabilities.items()
            ):
                raise ValueError(
                    "PREQUENTIAL_REPLAY_CHALLENGER_PROBABILITY_MISMATCH"
                )

    for model_key, model_row in model_rows.items():
        if (
            str(model_row.get("role")) == ModelRole.CHALLENGER.value
            and str(model_row.get("status")) == ModelStatus.ACTIVE.value
            and verified_active_challenger_links.get(model_key, 0) != 1
        ):
            raise ValueError(
                "PREQUENTIAL_REPLAY_ACTIVE_CHALLENGER_TRAINING_EDGE_MISSING"
            )


def run_replay(
    *,
    engine: Engine,
    artifacts: PrequentialArtifactRepository,
    output: Path,
    now: datetime,
) -> dict[str, object]:
    sql = PrequentialSQLRepository(engine)
    for snapshot in sql.load_snapshots():
        verify_feature_snapshot_artifact(artifacts, snapshot)
    first_rows = sql.replay_rows()
    _verify_replay_artifacts(artifacts=artifacts, rows=first_rows)
    first = replay_prequential_rows(first_rows)
    second_rows = sql.replay_rows()
    _verify_replay_artifacts(artifacts=artifacts, rows=second_rows)
    second = replay_prequential_rows(second_rows)
    if first != second:
        raise RuntimeError("PREQUENTIAL_REPLAY_NOT_IDEMPOTENT")
    return _write_report(
        output / "replay-report.json",
        {
            "schema_version": "prequential-replay-report-v1",
            "generated_at": now.isoformat(),
            **asdict(first),
            "second_pass_identical": True,
            "api_football_calls": 0,
            "odds_api_credits": 0,
        },
    )


def run_status(
    *,
    engine: Engine,
    config: Mapping[str, object],
    output: Path,
    now: datetime,
) -> dict[str, object]:
    sql = PrequentialSQLRepository(engine)
    models = sql.load_models()
    predictions = sql.load_predictions()
    settlements = sql.load_settlements()
    scores = sql.load_scores()
    events = sql.load_events()
    replay_rows = sql.replay_rows()
    replay = replay_prequential_rows(replay_rows)
    counts = sql.counts()
    due = 0
    upcoming: list[dict[str, object]] = []
    fixtures = _latest_fixtures(engine, as_of=now)
    for fixture in fixtures:
        for cutoff_name, cutoff_at, opens_at in _cutoff_windows(
            config,
            kickoff_at=_utc_db(fixture.kickoff_at),
        ):
            if opens_at <= now <= cutoff_at:
                due += 1
            if cutoff_at > now:
                upcoming.append(
                    {
                        "fixture_id": fixture.fixture_id,
                        "competition": fixture.competition,
                        "cutoff": cutoff_name.value,
                        "cutoff_at": cutoff_at.isoformat(),
                    }
                )
    next_training = None
    successful = [
        model.training_cutoff
        for model in models
        if model.role is ModelRole.CHALLENGER
        and model.training_cutoff is not None
    ]
    if successful:
        successful_dates = [value for value in successful if value is not None]
        next_training = (
            max(successful_dates) + timedelta(days=1)
        ).isoformat()
    upcoming_sorted = sorted(
        upcoming,
        key=lambda value: str(value["cutoff_at"]),
    )
    training_rows = replay_rows["prequential_training_runs"]
    successful_training_rows = [
        row
        for row in training_rows
        if row.get("status") == "CHALLENGER_VERSION_CREATED"
    ]
    latest_training = (
        max(
            successful_training_rows,
            key=lambda row: str(row.get("finished_at", "")),
        )
        if successful_training_rows
        else None
    )

    def model_row(model: ModelVersion) -> dict[str, object]:
        return {
            "model_id": model.model_id,
            "scope": model.scope.value,
            "role": model.role.value,
            "version": model.version,
            "status": model.status.value,
            "created_at": model.created_at.isoformat(),
            "training_cutoff": (
                model.training_cutoff.isoformat()
                if model.training_cutoff is not None
                else None
            ),
            "feature_contract_hash": model.feature_contract_hash,
            "artifact_sha256": model.artifact_sha256,
            "code_revision": model.code_revision,
        }

    global_reference = next(
        (
            model
            for model in reversed(models)
            if model.role is ModelRole.REFERENCE
            and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
        ),
        None,
    )
    global_challenger = next(
        (
            model
            for model in reversed(models)
            if model.role is ModelRole.CHALLENGER
            and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
        ),
        None,
    )
    primary_keys = {
        (model.model_id, model.version)
        for model in (global_reference, global_challenger)
        if model is not None
    }
    settled_fixture_ids = {
        settlement.result.fixture_id
        for settlement in settlements
        if settlement.effective_status is PredictionStatus.SETTLED
    }
    next_cutoff = upcoming_sorted[0] if upcoming_sorted else None
    live_status = {
        "schema_version": "prequential-learning-status-v1",
        "generated_at": now.isoformat(),
        "verdict": "PREQUENTIAL_LEARNING_FACTORY_READY",
        "origin": "POSTGRESQL_REAL_PREQUENTIAL_STATE",
        "markets": list(cast(Sequence[str], config.get("markets", ()))),
        "cutoffs": list(cast(Mapping[str, object], config["cutoffs"]).keys()),
        "predictions": {
            "frozen": sum(
                prediction.status is PredictionStatus.FROZEN
                for prediction in predictions
            ),
            "rejected": sum(
                prediction.status is not PredictionStatus.FROZEN
                for prediction in predictions
            ),
            "settled": len({score.prediction_id for score in scores}),
            "next_due_at": (
                next_cutoff["cutoff_at"]
                if next_cutoff is not None
                else None
            ),
            "next_prediction": (
                {
                    **next_cutoff,
                    "cutoff_name": next_cutoff["cutoff"],
                    "status": "NOT_DUE",
                }
                if next_cutoff is not None
                else None
            ),
            "items": [
                {
                    **prediction.as_dict(),
                    "feature_snapshot_hash": None,
                }
                for prediction in predictions[-100:]
            ],
        },
        "settlements": {
            "fixtures": len(settled_fixture_ids),
            "scored": len(scores),
            "items": [
                {
                    "settlement_id": settlement.settlement_id,
                    "fixture_id": settlement.result.fixture_id,
                    "competition": settlement.result.competition,
                    "status": settlement.effective_status.value,
                    "result_version": settlement.result.result_version,
                    "settled_at": settlement.settled_at.isoformat(),
                    "settlement_hash": settlement.settlement_hash,
                }
                for settlement in settlements[-100:]
            ],
        },
        "training": {
            "eligible_fixtures": len(settled_fixture_ids),
            "new_support": len(settled_fixture_ids),
            "represented_leagues": len(
                {
                    settlement.result.competition
                    for settlement in settlements
                    if settlement.effective_status is PredictionStatus.SETTLED
                }
            ),
            "minimum_fixtures": 30,
            "minimum_leagues": 2,
            "next_status": (
                "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT"
                if len(settled_fixture_ids) < 30
                else "TRAINING_SUPPORT_AVAILABLE"
            ),
            "next_possible_at": next_training,
            "last_training_at": (
                latest_training.get("finished_at")
                if latest_training is not None
                else None
            ),
            "runs": counts["training_runs"],
            "last_version": (
                latest_training.get("next_model_version")
                if latest_training is not None
                else None
            ),
            "manifests": [
                {
                    "manifest_id": row.get("training_run_id"),
                    "model_id": row.get("model_id"),
                    "model_version": row.get("next_model_version"),
                    "created_at": row.get("finished_at"),
                    "fixture_count": len(
                        cast(list[object], row.get("fixture_ids", []))
                    ),
                    "leagues": row.get("competitions", []),
                    "dataset_sha256": row.get("dataset_manifest_hash"),
                    "artifact_sha256": row.get("artifact_sha256"),
                    "status": row.get("status"),
                }
                for row in training_rows[-50:]
            ],
        },
        "models": {
            "reference": (
                model_row(global_reference)
                if global_reference is not None
                else None
            ),
            "challenger": (
                model_row(global_challenger)
                if global_challenger is not None
                else None
            ),
            "scopes": [
                model_row(model)
                for model in models
                if (model.model_id, model.version) not in primary_keys
            ],
            "active_count": sum(model.frozen for model in models),
        },
        "performance": {
            "by_league": [],
            "reference_vs_challenger": None,
        },
        "promotion_status": PROMOTION_LOCKED,
        "promotion_authorized": False,
        "security": {
            "production_locked": True,
            "real_bets": False,
            "no_bet_default": True,
            "social_publishing_enabled": False,
        },
        "expert": {
            "ledger_events": len(events),
            "ledger_head_hash": replay.ledger_head_hash,
            "ledger_status": "PREQUENTIAL_LEDGER_VERIFIED",
            "recent_events": [
                {
                    "sequence_no": event.sequence_no,
                    "kind": event.kind.value,
                    "recorded_at": event.recorded_at.isoformat(),
                    "fixture_id": event.fixture_id,
                    "model_id": event.model_id,
                    "model_version": event.model_version,
                    "event_hash": event.event_hash,
                    "previous_hash": event.previous_hash,
                }
                for event in events[-50:]
            ],
            "latest_manifest_hash": (
                latest_training.get("dataset_manifest_hash")
                if latest_training is not None
                else None
            ),
        },
        "provider_calls": 0,
        "odds_api_credits": 0,
    }
    _write_report(output / "status.json", live_status)
    return _write_report(
        output / "status-report.json",
        {
            "schema_version": "prequential-status-report-v1",
            "generated_at": now.isoformat(),
            "status": "PREQUENTIAL_LEARNING_FACTORY_READY",
            "fixtures_tracked": len(fixtures),
            "cutoffs_due": due,
            "next_cutoffs": upcoming_sorted[:20],
            "predictions_real": sum(
                prediction.status is PredictionStatus.FROZEN
                for prediction in predictions
            ),
            "prediction_rejections": sum(
                prediction.status is not PredictionStatus.FROZEN
                for prediction in predictions
            ),
            "settlements_real": len(settlements),
            "training_support": len(
                {
                    settlement.result.fixture_id
                    for settlement in settlements
                    if settlement.effective_status is PredictionStatus.SETTLED
                }
            ),
            "models": [
                {
                    "model_id": model.model_id,
                    "scope": model.scope.value,
                    "role": model.role.value,
                    "version": model.version,
                    "status": model.status.value,
                    "registry_hash": model.registry_hash,
                }
                for model in models
            ],
            "next_training_at": next_training,
            "counts": counts,
            "provider_calls": 0,
            "odds_api_credits": 0,
        },
    )


def _synthetic_snapshot(
    *,
    factory: PrequentialLearningFactory,
    repository: PrequentialArtifactRepository,
    fixture_id: str,
    fixture_record_id: str,
    competition: str,
    market: PredictionMarket,
    cutoff_name: CutoffName,
    cutoff_at: datetime,
    kickoff_at: datetime,
    contract: Mapping[str, object],
    code_revision: str,
    odds_snapshot_id: str,
) -> str:
    values: dict[str, object] = {
        family: None for family in FEATURE_FAMILIES
    }
    availability = {family: False for family in FEATURE_FAMILIES}
    values["market"] = {
        "decimal_odds": (
            {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4}
            if market is PredictionMarket.ONE_X_TWO
            else {"OVER": 1.95, "UNDER": 1.95}
        ),
        "source": "SYNTHETIC_MECHANICS_ONLY",
    }
    availability["market"] = True
    values["team"] = {
        "home_team_id": "synthetic-home",
        "away_team_id": "synthetic-away",
        "kickoff_at": kickoff_at.isoformat(),
        "competition": competition,
        "provider": "SYNTHETIC_MECHANICS_ONLY",
        "provider_fixture_id": fixture_id,
    }
    availability["team"] = True
    observed_at = cutoff_at - timedelta(minutes=5)
    provenance: dict[str, dict[str, object]] = {}
    for family in ("market", "team"):
        receipt = persist_source_receipt(
            repository,
            source_name="SYNTHETIC_MECHANICS_ONLY",
            request_identity=(
                f"synthetic:{fixture_record_id}:{market.value}:"
                f"{cutoff_name.value}:{family}"
            ),
            payload={
                "fixture_id": fixture_id,
                "fixture_record_id": fixture_record_id,
                "family": family,
                "value": values[family],
            },
            observed_at=observed_at,
            ingested_at=observed_at,
            code_revision=code_revision,
        )
        provenance[family] = {
            **receipt.as_dict(),
            "source": receipt.source_name,
            "source_identity": receipt.storage_identity,
            "observed_at": receipt.robin_first_observed_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
        }
    provenance["market"]["odds_snapshot_id"] = odds_snapshot_id
    snapshot = freeze_feature_snapshot(
        repository=repository,
        registry=factory.features,
        fixture_record_id=fixture_record_id,
        fixture_id=fixture_id,
        competition=competition,
        market=market,
        cutoff_name=cutoff_name,
        cutoff_at=cutoff_at,
        created_at=observed_at,
        feature_contract_version=str(
            contract.get("version", "prequential-features-v1")
        ),
        feature_contract=contract,
        values=values,
        availability=availability,
        provenance=provenance,
        quality={"source": "SYNTHETIC_MECHANICS_ONLY"},
        code_revision=code_revision,
    )
    factory.register_snapshot(snapshot)
    return snapshot.snapshot_id


def run_synthetic_pilot(
    *,
    config: Mapping[str, object],
    output: Path,
    now: datetime,
) -> dict[str, object]:
    pilot_root = output / "synthetic-pilot"
    repository = PrequentialArtifactRepository(
        DirectoryArtifactStore(pilot_root / "objects")
    )
    contract = _feature_contract(config)
    models = initial_model_versions(
        created_at=now - timedelta(days=90),
        feature_contract_hash=canonical_sha256(contract),
        code_revision="synthetic-pilot-v1",
    )
    factory = PrequentialLearningFactory(
        artifact_repository=repository,
        models=models,
        devig_method="PROPORTIONAL",
    )
    reference = next(
        model
        for model in models
        if model.role is ModelRole.REFERENCE
        and model.scope is ModelScope.GLOBAL_FIVE_LEAGUES
    )
    competitions = ("Ligue 1", "Premier League")
    idempotent_settlements = 0
    for index in range(30):
        competition = competitions[index % len(competitions)]
        fixture_id = f"synthetic:fixture:{index:02d}"
        fixture_record_id = f"synthetic-record-{index:02d}"
        kickoff_at = now - timedelta(days=60 - index)
        for market in PredictionMarket:
            for cutoff_name, minutes in (
                (CutoffName.H_2, 120),
                (CutoffName.NEAR_KICKOFF, 1),
            ):
                cutoff_at = kickoff_at - timedelta(minutes=minutes)
                odds_snapshot_id = f"synthetic-odds-{index}-{market.value}"
                snapshot_id = _synthetic_snapshot(
                    factory=factory,
                    repository=repository,
                    fixture_id=fixture_id,
                    fixture_record_id=fixture_record_id,
                    competition=competition,
                    market=market,
                    cutoff_name=cutoff_name,
                    cutoff_at=cutoff_at,
                    kickoff_at=kickoff_at,
                    contract=contract,
                    code_revision="synthetic-pilot-v1",
                    odds_snapshot_id=odds_snapshot_id,
                )
                odds = (
                    {"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4}
                    if market is PredictionMarket.ONE_X_TWO
                    else {"OVER": 1.95, "UNDER": 1.95}
                )
                prediction = factory.forecast(
                    fixture_record_id=fixture_record_id,
                    fixture_id=fixture_id,
                    competition=competition,
                    market=market,
                    cutoff_name=cutoff_name,
                    cutoff_at=cutoff_at,
                    kickoff_at=kickoff_at,
                    predicted_at=cutoff_at - timedelta(minutes=5),
                    model_id=reference.model_id,
                    model_version=reference.version,
                    feature_snapshot_id=snapshot_id,
                    gate_statuses={"fixture": True},
                    required_gates=("fixture",),
                    decimal_odds=odds,
                    odds_snapshot_id=odds_snapshot_id,
                    challenger_probabilities=None,
                    code_revision="synthetic-pilot-v1",
                )
                if prediction.status is not PredictionStatus.FROZEN:
                    raise RuntimeError("SYNTHETIC_PREDICTION_NOT_FROZEN")
        result_observation = repository.put_manifest(
            "result-observations",
            {
                "schema_version": "prequential-result-observation-v1",
                "origin": "SYNTHETIC_MECHANICS_ONLY",
                "provider": "SYNTHETIC_MECHANICS_ONLY",
                "fixture_id": fixture_id,
                "fixture_record_id": fixture_record_id,
                "provider_fixture_id": fixture_id,
                "attempt": 1,
                "observed_at": (kickoff_at + timedelta(hours=2)).isoformat(),
                "availability": "PRESENT",
                "http_status": 200,
                "record": {
                    "fixture": {
                        "id": fixture_id,
                        "status": {"short": "FT"},
                    },
                    "goals": {
                        "home": index % 4,
                        "away": (index + 1) % 3,
                    },
                },
                "provider_calls": 0,
            },
        )
        result = VerifiedFixtureResult(
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition=competition,
            kickoff_at=kickoff_at,
            status=FixtureResultStatus.FINISHED,
            verified_at=kickoff_at + timedelta(hours=2),
            home_goals=index % 4,
            away_goals=(index + 1) % 3,
            source_hash=result_observation.sha256,
        )
        factory.settle(result, settled_at=kickoff_at + timedelta(hours=2))
        _settlement, _scores, inserted = factory.settle(
            result,
            settled_at=kickoff_at + timedelta(hours=2),
        )
        idempotent_settlements += int(not inserted)
    decision = factory.train(
        model_id="challenger-global_five_leagues",
        previous_version="untrained-v1",
        training_cutoff=now,
        code_revision="synthetic-pilot-v1",
    )
    if decision.next_model is None or decision.manifest is None:
        raise RuntimeError("SYNTHETIC_TRAINING_MECHANICS_FAILED")
    late = factory.forecast(
        fixture_record_id="synthetic-record-late",
        fixture_id="synthetic:fixture:late",
        competition="Ligue 1",
        market=PredictionMarket.ONE_X_TWO,
        cutoff_name=CutoffName.H_2,
        cutoff_at=now - timedelta(hours=2),
        kickoff_at=now + timedelta(hours=1),
        predicted_at=now,
        model_id=reference.model_id,
        model_version=reference.version,
        feature_snapshot_id=None,
        gate_statuses={"fixture": True},
        required_gates=("fixture",),
        decimal_odds={"HOME": 2.2, "DRAW": 3.3, "AWAY": 3.4},
        odds_snapshot_id="synthetic-odds-late",
        challenger_probabilities=None,
        code_revision="synthetic-pilot-v1",
    )
    report = _write_report(
        pilot_root / "pilot-report.json",
        {
            "schema_version": "prequential-synthetic-pilot-v1",
            "generated_at": now.isoformat(),
            "origin": "SYNTHETIC_MECHANICS_ONLY",
            "prospective_evidence": False,
            "synthetic_fixtures": 30,
            "synthetic_predictions_frozen": sum(
                prediction.status is PredictionStatus.FROZEN
                for prediction in factory.predictions.predictions
            ),
            "synthetic_settlements": len(factory.settlements.settlements),
            "synthetic_scores": len(factory.settlements.scores),
            "idempotent_settlement_retries": idempotent_settlements,
            "late_prediction_status": late.status.value,
            "training_status": decision.status,
            "training_support": decision.eligible_fixtures,
            "represented_leagues": decision.represented_leagues,
            "challenger_version": decision.next_model.version,
            "reference_unchanged": reference.version,
            "real_predictions": 0,
            "real_settlements": 0,
            "real_training_runs": 0,
            "provider_calls": 0,
            "odds_api_credits": 0,
            "ledger": factory.ledger.audit(),
            "artifact_inventory": repository.inventory(),
        },
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("forecast", "settle", "train", "replay", "status", "pilot"):
        child = subparsers.add_parser(command)
        child.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        child.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
        child.add_argument("--now")
        child.add_argument("--identity-report", type=Path, default=DEFAULT_IDENTITY_REPORT)
        child.add_argument("--database-url")
        if command == "pilot":
            child.add_argument("--synthetic", action="store_true")
    return parser


def _operational_artifacts(environment: Mapping[str, str]) -> PrequentialArtifactRepository:
    return PrequentialArtifactRepository(R2ArtifactStore(environment))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _config(args.config)
    now = _parse_now(args.now)
    output = cast(Path, args.output)
    if args.command == "pilot":
        if not bool(args.synthetic):
            raise RuntimeError("PREQUENTIAL_SYNTHETIC_FLAG_REQUIRED")
        report = run_synthetic_pilot(config=config, output=output, now=now)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    _verify_runtime_guards(os.environ)
    database_url = args.database_url or os.getenv("ROBIN_DATABASE_URL")
    if not database_url:
        raise RuntimeError("PREQUENTIAL_DATABASE_URL_REQUIRED")
    engine = build_engine(database_url)
    code_revision = _code_revision(os.environ)
    if args.command == "status":
        report = run_status(
            engine=engine,
            config=config,
            output=output,
            now=now,
        )
    elif args.command == "replay":
        report = run_replay(
            engine=engine,
            artifacts=_operational_artifacts(os.environ),
            output=output,
            now=now,
        )
    else:
        artifacts = _operational_artifacts(os.environ)
        if args.command == "forecast":
            report = run_forecast(
                engine=engine,
                artifacts=artifacts,
                config=config,
                output=output,
                now=now,
                code_revision=code_revision,
                identities=_identity_map(args.identity_report),
            )
        elif args.command == "settle":
            allowed = int(os.getenv("API_FOOTBALL_CALLS_ALLOWED", "0"))
            provider = (
                ApiFootballProvider(api_key=os.getenv("API_FOOTBALL_KEY"))
                if allowed > 0
                else None
            )
            report = run_settle(
                engine=engine,
                artifacts=artifacts,
                config=config,
                output=output,
                now=now,
                code_revision=code_revision,
                provider=provider,
            )
            calls = report.get("provider_calls")
            if not isinstance(calls, int):
                raise RuntimeError("PREQUENTIAL_PROVIDER_CALL_REPORT_INVALID")
            if calls > allowed:
                raise RuntimeError("PREQUENTIAL_PROVIDER_CALL_BUDGET_EXCEEDED")
        else:
            report = run_train(
                engine=engine,
                artifacts=artifacts,
                config=config,
                output=output,
                now=now,
                code_revision=code_revision,
            )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
