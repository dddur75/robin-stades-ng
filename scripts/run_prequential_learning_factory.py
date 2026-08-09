"""Operational CLI for the five-league prequential learning factory.

The normal commands are fail-closed and use PostgreSQL plus append-only R2.
The synthetic pilot is explicitly isolated below the selected output directory
and never writes to the operational database or calls a provider.
"""

from __future__ import annotations

import argparse
import json
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
from robin.prospective_observatory.contracts import canonical_sha256
from robin.prospective_observatory.feature_snapshots import (
    FEATURE_FAMILIES,
    freeze_feature_snapshot,
)
from robin.prospective_observatory.prequential_contracts import (
    FIVE_LEAGUE_NAMES,
    PROMOTION_LOCKED,
    CutoffName,
    FixtureResultStatus,
    FixtureSettlementRecord,
    ModelRole,
    ModelScope,
    ModelStatus,
    ModelVersion,
    PredictionMarket,
    PredictionStatus,
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
from robin.prospective_observatory.prequential_storage import (
    DirectoryArtifactStore,
    PrequentialArtifactRepository,
    R2ArtifactStore,
)
from robin.prospective_observatory.prequential_training import (
    challenger_probabilities_from_artifact,
)
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import ProviderResult
from robin.storage.database import build_engine
from robin.storage.prequential_models import PrequentialTrainingRunModel
from robin.storage.prospective_models import (
    ProspectiveFixtureModel,
    ProspectiveOddsSnapshotModel,
    TemporalDataGateModel,
)

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
    "TRIPLE_SEARCH_LOCKED": "true",
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


def _utc(value: datetime) -> datetime:
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


def _latest_fixtures(engine: Engine) -> tuple[ProspectiveFixtureModel, ...]:
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(ProspectiveFixtureModel).order_by(
                    ProspectiveFixtureModel.registered_at,
                    ProspectiveFixtureModel.id,
                )
            )
        )
    latest: dict[str, ProspectiveFixtureModel] = {}
    for row in rows:
        latest[row.fixture_id] = row
    return tuple(
        sorted(
            (
                row
                for row in latest.values()
                if not row.cancelled and row.kickoff_reliable
            ),
            key=lambda row: (_utc(row.kickoff_at), row.fixture_id),
        )
    )


def _canonical_selection(
    *,
    market: PredictionMarket,
    selection: str,
    identity: FixtureIdentity | None,
) -> str | None:
    folded = selection.strip().casefold()
    if market is PredictionMarket.OVER_UNDER_2_5:
        if folded == "over":
            return "OVER"
        if folded == "under":
            return "UNDER"
        return None
    if folded in {"draw", "tie", "x"}:
        return "DRAW"
    if identity is None:
        return None
    if folded == identity.home_name.casefold():
        return "HOME"
    if folded == identity.away_name.casefold():
        return "AWAY"
    return None


def _odds_evidence(
    engine: Engine,
    *,
    fixture_id: str,
    market: PredictionMarket,
    cutoff_at: datetime,
    identity: FixtureIdentity | None,
) -> OddsEvidence | None:
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(ProspectiveOddsSnapshotModel).where(
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
    for row in rows:
        canonical = _canonical_selection(
            market=market,
            selection=row.selection,
            identity=identity,
        )
        if canonical is None:
            continue
        groups[(row.receipt_id, row.bookmaker, _utc(row.observed_at))][
            canonical
        ] = row
    expected = (
        {"HOME", "DRAW", "AWAY"}
        if market is PredictionMarket.ONE_X_TWO
        else {"OVER", "UNDER"}
    )
    candidates: list[OddsEvidence] = []
    for (receipt_id, bookmaker, observed_at), values in groups.items():
        if set(values) != expected:
            continue
        candidates.append(
            OddsEvidence(
                decimal_odds={
                    selection: values[selection].odds
                    for selection in sorted(expected)
                },
                observed_at=observed_at,
                snapshot_id="odds-" + canonical_sha256(
                    {
                        "receipt_id": receipt_id,
                        "bookmaker": bookmaker,
                        "market": market.value,
                        "rows": {
                            selection: values[selection].snapshot_hash
                            for selection in sorted(expected)
                        },
                    }
                ),
                bookmaker=bookmaker,
                margin=max(row.margin for row in values.values()),
            )
        )
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda value: (
            value.observed_at,
            -value.margin,
            value.bookmaker,
        ),
    )


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
        key=lambda value: (_utc(value.evaluated_at), value.id),
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
        "source": "prospective_odds_snapshots",
        "odds_snapshot_id": odds.snapshot_id,
        "observed_at": odds.observed_at.isoformat(),
        "cutoff_at": cutoff_at.isoformat(),
    }
    registered_at = _utc(fixture.registered_at)
    if registered_at <= cutoff_at:
        values["team"] = {
            "home_team_id": fixture.home_team_id,
            "away_team_id": fixture.away_team_id,
        }
        availability["team"] = True
        provenance["team"] = {
            "source": "prospective_fixtures",
            "registry_hash": fixture.registry_hash,
            "observed_at": registered_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
        }
    gate_by_family = {
        "players": "PROSPECTIVE_PLAYER_GATE",
        "injuries": "PROSPECTIVE_INJURY_GATE",
        "lineup": "PROSPECTIVE_LINEUP_GATE",
        "formation": "PROSPECTIVE_FORMATION_GATE",
    }
    for family, gate_name in gate_by_family.items():
        gate = gates.get(gate_name)
        if gate is None or gate.status != "PASSED":
            continue
        observed_at = _utc(gate.evaluated_at)
        values[family] = {
            "gate": gate_name,
            "coverage": gate.coverage,
            "evidence_hash": gate.evidence_hash,
        }
        availability[family] = True
        provenance[family] = {
            "source": "temporal_data_gates",
            "gate": gate_name,
            "observed_at": observed_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
        }
    quality: dict[str, object] = {
        "market": "PASSED",
        "fixture": "PASSED" if availability["team"] else "BLOCKED_BY_TEMPORALITY",
        "gates": {
            name: gate.status
            for name, gate in sorted(gates.items())
        },
    }
    return values, availability, provenance, quality


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
    factory = PrequentialLearningFactory(
        artifact_repository=artifacts,
        models=models,
    )
    for snapshot in sql.load_snapshots():
        factory.features.append(snapshot)
    for prediction in sql.load_predictions():
        factory.predictions.append(prediction)
    scores = sql.load_scores()
    by_settlement: dict[str, list[Any]] = defaultdict(list)
    for score in scores:
        by_settlement[score.settlement_id].append(score)
    for settlement in sql.load_settlements():
        factory.settlements.restore(
            settlement,
            tuple(by_settlement.get(settlement.settlement_id, [])),
        )
    for event in sql.load_events():
        factory.ledger.restore(event)
    return factory


def _current_models(
    factory: PrequentialLearningFactory,
    *,
    competition: str,
    at: datetime,
) -> tuple[ModelVersion, ...]:
    current: dict[str, ModelVersion] = {}
    for model in factory.models.values():
        if model.created_at > at:
            continue
        expected = FIVE_LEAGUE_NAMES.get(model.scope)
        if expected is not None and expected != competition:
            continue
        previous = current.get(model.model_id)
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
    for fixture in _latest_fixtures(engine):
        kickoff_at = _utc(fixture.kickoff_at)
        for cutoff_name, cutoff_at, opens_at in _cutoff_windows(
            config,
            kickoff_at=kickoff_at,
        ):
            if not opens_at <= now <= cutoff_at:
                continue
            due_cutoffs += 1
            gates = _latest_gates(
                engine,
                fixture_id=fixture.fixture_id,
                cutoff_at=cutoff_at,
            )
            for market in PredictionMarket:
                odds = _odds_evidence(
                    engine,
                    fixture_id=fixture.fixture_id,
                    market=market,
                    cutoff_at=cutoff_at,
                    identity=identities.get(fixture.fixture_id),
                )
                snapshot_id: str | None = None
                if odds is not None and _utc(fixture.registered_at) <= cutoff_at:
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
                for model in _current_models(
                    factory,
                    competition=fixture.competition,
                    at=now,
                ):
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
                            "fixture": _utc(fixture.registered_at) <= cutoff_at
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
            "source": "POSTGRESQL_POINT_IN_TIME_ONLY",
            "fixtures_tracked": len(_latest_fixtures(engine)),
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
            kickoff_at=_utc(fixture.kickoff_at),
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
            kickoff_at=_utc(fixture.kickoff_at),
            status=status,
            verified_at=verified_at,
            result_version=result_version,
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
    observations = [
        value
        for value in _artifact_values(repository, "result-observations")
        if value.get("fixture_id") == fixture.fixture_id
    ]
    if observations:
        latest_observed = max(
            datetime.fromisoformat(str(value["observed_at"]))
            for value in observations
        )
        if now - _utc(latest_observed) < timedelta(hours=6):
            return None, 0
    attempt = len(observations) + 1
    if attempt > 5:
        return None, 0
    guard = repository.put_manifest(
        "provider-call-guards",
        {
            "schema_version": "prequential-provider-call-guard-v1",
            "fixture_id": fixture.fixture_id,
            "provider_fixture_id": fixture.provider_fixture_id,
            "attempt": attempt,
            "operation": "VERIFY_FINAL_RESULT",
        },
    )
    if not guard.inserted:
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
            "guard_sha256": guard.sha256,
            "observation_sha256": stored.sha256,
            "fixture_id": fixture.fixture_id,
            "attempt": attempt,
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
    frozen_fixture_ids = {
        prediction.fixture_id
        for prediction in predictions
        if prediction.status is PredictionStatus.FROZEN
    }
    latest_settlements: dict[str, FixtureSettlementRecord] = {}
    for settlement in factory.settlements.settlements:
        latest_settlements[settlement.result.fixture_id] = settlement
    eligible = sorted(
        [
        fixture
        for fixture in _latest_fixtures(engine)
        if fixture.fixture_id in frozen_fixture_ids
        and _utc(fixture.kickoff_at) + timedelta(minutes=90) < now
        and (
            fixture.fixture_id not in latest_settlements
            or latest_settlements[fixture.fixture_id].effective_status
            is PredictionStatus.SETTLED
        )
        ],
        key=lambda fixture: (_utc(fixture.kickoff_at), fixture.fixture_id),
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
            latest_settlement=latest_settlements.get(fixture.fixture_id),
        )
        provider_calls += calls
        if result is None:
            continue
        settlement, scores, created = factory.settle(result, settled_at=now)
        if not created:
            continue
        sql.append_settlement(settlement)
        scores_inserted += sql.append_scores(scores)
        inserted += 1
        latest_settlements[fixture.fixture_id] = settlement
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
        for row in metric_rows:
            sql.append_metric_snapshot(row, measured_at=now)
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


def _last_successful_training(engine: Engine, model_id: str) -> datetime | None:
    with Session(engine) as session:
        rows = tuple(
            session.scalars(
                select(PrequentialTrainingRunModel).where(
                    PrequentialTrainingRunModel.model_id == model_id,
                    PrequentialTrainingRunModel.status
                    == "CHALLENGER_VERSION_CREATED",
                )
            )
        )
    if not rows:
        return None
    return max(_utc(row.finished_at) for row in rows)


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
    candidates = [
        model
        for model in factory.models.values()
        if model.model_id == "challenger-global_five_leagues"
    ]
    if not candidates:
        raise RuntimeError("PREQUENTIAL_GLOBAL_CHALLENGER_MISSING")
    previous = max(
        candidates,
        key=lambda model: (model.created_at, model.version),
    )
    first_event = len(factory.ledger.events)
    decision = factory.train(
        model_id=previous.model_id,
        previous_version=previous.version,
        training_cutoff=now,
        code_revision=code_revision,
        last_training_at=_last_successful_training(engine, previous.model_id),
    )
    if decision.next_model is not None:
        sql.append_model(decision.next_model)
    training_run_id = "training-" + canonical_sha256(
        {
            "model_id": previous.model_id,
            "previous_version": previous.version,
            "training_cutoff": now.isoformat(),
            "status": decision.status,
            "manifest": (
                decision.manifest.manifest_hash
                if decision.manifest is not None
                else None
            ),
        }
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


def run_replay(
    *,
    engine: Engine,
    output: Path,
    now: datetime,
) -> dict[str, object]:
    sql = PrequentialSQLRepository(engine)
    first = replay_prequential_rows(sql.replay_rows())
    second = replay_prequential_rows(sql.replay_rows())
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
    for fixture in _latest_fixtures(engine):
        for cutoff_name, cutoff_at, opens_at in _cutoff_windows(
            config,
            kickoff_at=_utc(fixture.kickoff_at),
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
            "fixtures_tracked": len(_latest_fixtures(engine)),
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
    contract: Mapping[str, object],
    code_revision: str,
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
    values["team"] = {"home_team_id": "synthetic-home", "away_team_id": "synthetic-away"}
    availability["team"] = True
    observed_at = cutoff_at - timedelta(minutes=5)
    provenance = {
        family: {
            "source": "SYNTHETIC_MECHANICS_ONLY",
            "observed_at": observed_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
        }
        for family in ("market", "team")
    }
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
                snapshot_id = _synthetic_snapshot(
                    factory=factory,
                    repository=repository,
                    fixture_id=fixture_id,
                    fixture_record_id=fixture_record_id,
                    competition=competition,
                    market=market,
                    cutoff_name=cutoff_name,
                    cutoff_at=cutoff_at,
                    contract=contract,
                    code_revision="synthetic-pilot-v1",
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
                    odds_snapshot_id=f"synthetic-odds-{index}-{market.value}",
                    challenger_probabilities=None,
                    code_revision="synthetic-pilot-v1",
                )
                if prediction.status is not PredictionStatus.FROZEN:
                    raise RuntimeError("SYNTHETIC_PREDICTION_NOT_FROZEN")
        result = VerifiedFixtureResult(
            fixture_record_id=fixture_record_id,
            fixture_id=fixture_id,
            competition=competition,
            kickoff_at=kickoff_at,
            status=FixtureResultStatus.FINISHED,
            verified_at=kickoff_at + timedelta(hours=2),
            home_goals=index % 4,
            away_goals=(index + 1) % 3,
            source_hash=canonical_sha256(
                {"fixture_id": fixture_id, "source": "SYNTHETIC"}
            ),
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
        report = run_replay(engine=engine, output=output, now=now)
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
