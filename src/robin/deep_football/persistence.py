"""Projection idempotente des preuves compactes Jalon 11.

Les observations lourdes restent dans le Parquet répliqué vers R2. Cette
projection ne persiste que les contrats, gates, hypothèses et évaluations
nécessaires à l'audit scientifique.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from robin.deep_football.contracts import (
    SCIENTIFIC_FLOAT_CONTRACT_VERSION,
    canonical_hash,
    normalize_scientific_evidence,
    scientific_evidence_hash,
)
from robin.deep_football.matchups import owner_hypotheses
from robin.storage.models import (
    CoverageGateModel,
    DeepFeatureDefinitionModel,
    MatchupEvaluationModel,
    MatchupHypothesisModel,
)

ModelT = TypeVar(
    "ModelT",
    DeepFeatureDefinitionModel,
    CoverageGateModel,
    MatchupHypothesisModel,
    MatchupEvaluationModel,
)

DATASET_VERSION = "deep-football-team-prematch-v2"
FEATURE_VERSION = "1.0.0"
GATE_VERSION = "1.0.0"
HYPOTHESIS_VERSION = "1.0.0"
TEAM_HYPOTHESIS_VERSION = "1.0.0-amendment-1"
FROZEN_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
PROTOCOL_AMENDMENT_HASH = "37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa"
PROTOCOL_AMENDMENT_SOURCE_COMMIT = "64d600afa5ada11468900c9ca5a758eeab814c1e"
PROTOCOL_AMENDMENT_PUBLISHED_AT = datetime(
    2026,
    7,
    27,
    14,
    6,
    15,
    tzinfo=UTC,
)
AUTHORITATIVE_EVIDENCE_SOURCE_COMMIT = "bff3c672c279a94ed97e5a7de0ce0d9b9c56883e"
AUTHORITATIVE_EVIDENCE_PUBLISHED_AT = datetime(
    2026,
    7,
    27,
    14,
    17,
    17,
    tzinfo=UTC,
)
LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES = frozenset(
    {
        # First Linux persistence on run 30277990260.  A repeated calculation
        # changed only three last-bit float representations (max 6.94e-18).
        # This exact allowlist bridges that immutable row to the normalized
        # scientific hash without broadening replay equivalence.
        "cbd0dfde77b7603c818a662652d92389fa400175bd941e7a0525fd6b0d3fe9a4",
    }
)
EVALUATION_SCIENTIFIC_FLOAT_FIELDS = frozenset(
    {
        "effect",
        "p_value",
        "q_value_family",
        "q_value_global",
    }
)


def _identifier(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:j11:{namespace}:{value}"))


def _canonical(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, datetime):
            normalized = item.replace(tzinfo=UTC) if item.tzinfo is None else item.astimezone(UTC)
            return normalized.isoformat()
        return str(item)

    return json.dumps(
        value,
        default=default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _team_evaluation_hash(
    *,
    model_key: str,
    metrics: Mapping[str, object],
    dataset_hash: str,
    legacy: bool = False,
) -> str:
    hash_function = _legacy_hash_metrics if legacy else _hash_metrics
    return hash_function(
        {
            "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
            "model_key": model_key,
            "metrics": metrics,
            "dataset_hash": dataset_hash,
        }
    )


def _metrics_without_derived_campaign_hash(
    metrics: Mapping[str, object],
) -> tuple[dict[str, object], str]:
    normalized = normalize_scientific_evidence(dict(metrics))
    if not isinstance(normalized, dict):
        raise TypeError("JALON11_EVALUATION_METRICS_OBJECT_REQUIRED")
    authoritative = normalized.get("authoritative_evidence")
    if not isinstance(authoritative, dict):
        raise ValueError("JALON11_AUTHORITATIVE_EVIDENCE_REQUIRED")
    campaign_result_hash = authoritative.get("campaign_result_hash")
    if not isinstance(campaign_result_hash, str):
        raise ValueError("JALON11_CAMPAIGN_RESULT_HASH_REQUIRED")
    normalized_authoritative = dict(authoritative)
    normalized_authoritative.pop("campaign_result_hash")
    normalized["authoritative_evidence"] = normalized_authoritative
    return normalized, campaign_result_hash


def _is_known_legacy_numeric_evaluation_replay(
    existing: MatchupEvaluationModel,
    expected: Mapping[str, object],
    mismatches: set[str],
) -> bool:
    if not mismatches:
        return False
    if existing.model_key == "NOT_RUN_DATA_GATE":
        return False
    expected_metrics = expected.get("metrics")
    expected_evaluation_hash = expected.get("evaluation_hash")
    expected_idempotency_key = expected.get("idempotency_key")
    expected_dataset_hash = expected.get("dataset_hash")
    if (
        not isinstance(expected_metrics, dict)
        or not isinstance(expected_evaluation_hash, str)
        or not isinstance(expected_idempotency_key, str)
        or not isinstance(expected_dataset_hash, str)
    ):
        return False
    existing_metrics = existing.metrics
    if not isinstance(existing_metrics, dict):
        return False
    try:
        normalized_existing, existing_campaign_hash = _metrics_without_derived_campaign_hash(
            existing_metrics
        )
        normalized_expected, expected_campaign_hash = _metrics_without_derived_campaign_hash(
            expected_metrics
        )
    except (TypeError, ValueError):
        return False
    if existing_campaign_hash not in LEGACY_NUMERIC_CAMPAIGN_RESULT_HASHES:
        return False
    if existing_campaign_hash == expected_campaign_hash:
        return False
    if _canonical(normalized_existing) != _canonical(normalized_expected):
        return False
    for field, expected_value in expected.items():
        if field in {
            "code_revision",
            "evaluation_hash",
            "idempotency_key",
            "metrics",
        }:
            continue
        existing_value = getattr(existing, field)
        if field in EVALUATION_SCIENTIFIC_FLOAT_FIELDS:
            try:
                existing_value = normalize_scientific_evidence(existing_value)
                expected_value = normalize_scientific_evidence(expected_value)
            except (TypeError, ValueError):
                return False
        if _canonical(existing_value) != _canonical(expected_value):
            return False
    if (
        existing.idempotency_key != f"j11:evaluation:{existing.evaluation_hash}"
        or expected_idempotency_key != f"j11:evaluation:{expected_evaluation_hash}"
    ):
        return False
    if existing.evaluation_hash != _team_evaluation_hash(
        model_key=existing.model_key,
        metrics=existing_metrics,
        dataset_hash=existing.dataset_hash,
        legacy=True,
    ):
        return False
    return expected_evaluation_hash == _team_evaluation_hash(
        model_key=existing.model_key,
        metrics=expected_metrics,
        dataset_hash=expected_dataset_hash,
    )


def _add_or_verify(
    session: Session,
    model_type: type[ModelT],
    identifier: str,
    model: ModelT,
    expected: Mapping[str, object],
    *,
    legacy_numeric_replays: list[str] | None = None,
) -> bool:
    existing = session.scalar(select(model_type).where(model_type.id == identifier))
    if existing is None:
        session.add(model)
        return True
    # ``code_revision`` records the commit which created the immutable row.  It
    # is provenance, not scientific identity: the content/dataset/evaluation
    # hashes already carry that identity.  A replay from a later merge commit
    # must therefore preserve the creator revision instead of treating it as a
    # mutation or inserting a duplicate.
    mismatches = {
        field
        for field, value in expected.items()
        if field != "code_revision"
        if _canonical(getattr(existing, field)) != _canonical(value)
    }
    if mismatches:
        if isinstance(existing, MatchupEvaluationModel) and (
            _is_known_legacy_numeric_evaluation_replay(
                existing,
                expected,
                mismatches,
            )
        ):
            if legacy_numeric_replays is not None:
                legacy_numeric_replays.append(identifier)
            return False
        raise ValueError(
            "JALON11_IMMUTABLE_REPLAY_MISMATCH:"
            + model_type.__tablename__
            + ":"
            + ",".join(sorted(mismatches))
        )
    return False


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JALON11_OBJECT_REQUIRED:{path.name}")
    return value


def _require_mapping(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"JALON11_MAPPING_REQUIRED:{name}")
    return value


def _require_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"JALON11_LIST_REQUIRED:{name}")
    return value


def _as_float(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"JALON11_NUMBER_REQUIRED:{name}")
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            pass
    raise ValueError(f"JALON11_NUMBER_REQUIRED:{name}")


def _as_int(value: object, *, name: str) -> int:
    number = _as_float(value, name=name)
    if not number.is_integer():
        raise ValueError(f"JALON11_INTEGER_REQUIRED:{name}")
    return int(number)


def _validated_protocol_amendment(
    value: Mapping[str, object],
    *,
    source_commit: str,
    published_at: datetime,
) -> tuple[dict[str, object], datetime]:
    amendment = json.loads(_canonical(dict(value)))
    if not isinstance(amendment, dict):
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_OBJECT_REQUIRED")
    if canonical_hash(amendment) != PROTOCOL_AMENDMENT_HASH:
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_HASH_MISMATCH")
    if source_commit != PROTOCOL_AMENDMENT_SOURCE_COMMIT:
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_SOURCE_COMMIT_MISMATCH")
    if published_at.tzinfo is None:
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_TIMEZONE_REQUIRED")
    normalized_published_at = published_at.astimezone(UTC)
    if normalized_published_at != PROTOCOL_AMENDMENT_PUBLISHED_AT:
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_PUBLISHED_AT_MISMATCH")
    expected = {
        "schema_version": "deep-football-scientific-contract-v1-amendment-1",
        "amends": "deep-football-scientific-contract-v1",
        "status": "CORRECTIVE_PROTOCOL_AMENDMENT",
        "recorded_before_authoritative_incremental_run": True,
        "prior_team_only_diagnostics_seen": True,
        "scope_effect": ("METHODOLOGICAL_CORRECTION_ONLY_NO_THRESHOLD_OR_OUTCOME_SELECTION"),
        "provider_calls_allowed": 0,
        "odds_api_credits_allowed": 0,
        "production_status": "PRODUCTION_LOCKED",
    }
    for field, expected_value in expected.items():
        if amendment.get(field) != expected_value:
            raise ValueError(f"JALON11_PROTOCOL_AMENDMENT_INVALID:{field}")
    temporal_gate = _require_mapping(
        amendment.get("temporal_gate"),
        name="protocol_amendment.temporal_gate",
    )
    if (
        temporal_gate.get("TEAM_GATE") != "PARTIAL"
        or temporal_gate.get("promotion_eligible") is not False
    ):
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_TEAM_GATE_INVALID")
    primary = _require_mapping(
        amendment.get("primary_inference"),
        name="protocol_amendment.primary_inference",
    )
    expected_primary = {
        "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
        "reference": "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
        "challenger": "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL",
        "features": "MARKET_LOG_ODDS_PLUS_FROZEN_TEAM_FEATURES",
        "model_selection_on_test": False,
        "paired_fixtures_required": True,
        "expected_direction": "DELTA_LOG_LOSS_LT_ZERO",
        "promotion_eligible": False,
    }
    if primary != expected_primary:
        raise ValueError("JALON11_PROTOCOL_AMENDMENT_PRIMARY_INVALID")
    return amendment, normalized_published_at


def _feature_family(feature: str) -> str:
    if feature.startswith("elo_"):
        return "TEAM_STRENGTH"
    if "rest" in feature:
        return "CALENDAR"
    return "TEAM_FORM"


def _feature_contract(feature: str) -> dict[str, object]:
    window = next(
        (int(token) for token in feature.split("_") if token.isdigit()),
        0,
    )
    return {
        "feature_name": feature,
        "feature_version": FEATURE_VERSION,
        "entity": "TEAM_FIXTURE",
        "source": "CACHE_ONLY_API_FOOTBALL_AND_FOOTBALL_DATA",
        "available_at": "PRE_MATCH",
        "cutoff_policy": "STRICTLY_BEFORE_TARGET_KICKOFF",
        "lookback": {
            "type": "MATCHES" if window else "RATING_STATE",
            "count": window,
        },
        "missing_policy": "MISSING_NOT_ZERO",
        "unit": "MODEL_INPUT",
        "allowed_markets": ["1X2"],
        "allowed_research_modes": ["PRE_LINEUP"],
        "quality_gate": "TEAM_GATE",
        "leakage_tests": [
            "TARGET_FIXTURE_EXCLUDED",
            "STRICT_INPUT_CUTOFF",
            "TARGET_COLUMN_ALLOWLIST",
        ],
        "provenance": {
            "provider": "HISTORICAL_CACHE",
            "source_field": feature,
        },
        "dataset_version": DATASET_VERSION,
    }


def _usable_coverage(
    gate: str,
    row: Mapping[str, object],
) -> float:
    if gate in {"TEAM_GATE", "MARKET_GATE"}:
        return _as_float(
            row.get("team_coverage", 0.0),
            name="team_coverage",
        )
    return 0.0


def _cutoff_class(gate: str) -> str:
    if gate == "TEAM_GATE":
        return "TARGET_KICKOFF_EXCLUSIVE_BOUNDARY_PARTIAL"
    if gate == "MARKET_GATE":
        return "HISTORICAL_PREMATCH_RESEARCH"
    return "UNPROVEN_PREMATCH_OR_POST_MATCH_ONLY"


def _hash_metrics(value: Mapping[str, object]) -> str:
    return scientific_evidence_hash(dict(value))


def _legacy_hash_metrics(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def persist_deep_football_evidence(
    engine: Engine,
    artifact_dir: Path,
    *,
    code_revision: str,
    protocol_amendment: Mapping[str, object],
    protocol_amendment_source_commit: str,
    protocol_amendment_published_at: datetime,
) -> dict[str, object]:
    """Persister puis vérifier les preuves compactes sans aucune mutation."""

    amendment, amendment_published_at = _validated_protocol_amendment(
        protocol_amendment,
        source_commit=protocol_amendment_source_commit,
        published_at=protocol_amendment_published_at,
    )
    audit = _read_json(artifact_dir / "audit-summary.json")
    manifest = _read_json(artifact_dir / "dataset-manifest.json")
    campaign = _read_json(artifact_dir / "campaign-11a-summary.json")
    if (
        _as_int(
            audit.get("provider_calls", -1),
            name="provider_calls",
        )
        != 0
    ):
        raise ValueError("JALON11_PROVIDER_CALLS_MUST_BE_ZERO")
    if (
        _as_int(
            audit.get("odds_api_credits", -1),
            name="odds_api_credits",
        )
        != 0
    ):
        raise ValueError("JALON11_ODDS_CREDITS_MUST_BE_ZERO")
    if campaign.get("production_status") != "PRODUCTION_LOCKED":
        raise ValueError("JALON11_PRODUCTION_MUST_REMAIN_LOCKED")
    if campaign.get("numeric_evidence_contract") != SCIENTIFIC_FLOAT_CONTRACT_VERSION:
        raise ValueError("JALON11_NUMERIC_EVIDENCE_CONTRACT_MISMATCH")
    campaign_result_hash = campaign.get("result_hash")
    if not isinstance(campaign_result_hash, str) or len(campaign_result_hash) != 64:
        raise ValueError("JALON11_CAMPAIGN_RESULT_HASH_INVALID")
    campaign_hashable = dict(campaign)
    campaign_hashable.pop("result_hash")
    if scientific_evidence_hash(campaign_hashable) != campaign_result_hash:
        raise ValueError("JALON11_CAMPAIGN_RESULT_HASH_MISMATCH")
    dataset_hash = str(manifest["dataset_hash"])
    if len(dataset_hash) != 64:
        raise ValueError("JALON11_DATASET_HASH_INVALID")
    features = [str(value) for value in _require_list(manifest.get("features"), name="features")]
    gates = _require_mapping(audit.get("gates"), name="gates")
    matrix = _require_list(
        audit.get("coverage_matrix"),
        name="coverage_matrix",
    )
    inserted = {
        "feature_definitions": 0,
        "coverage_gates": 0,
        "hypotheses": 0,
        "evaluations": 0,
    }
    examined = dict(inserted)
    legacy_numeric_replays: list[str] = []
    with Session(engine) as session, session.begin():
        for feature in features:
            contract = _feature_contract(feature)
            definition_hash = canonical_hash(contract)
            identifier = _identifier(
                "feature",
                f"{feature}:{FEATURE_VERSION}:{dataset_hash}",
            )
            expected: dict[str, object] = {
                "feature_id": feature,
                "feature_version": FEATURE_VERSION,
                "feature_family": _feature_family(feature),
                "entity_level": "TEAM_FIXTURE",
                "cutoff_policy": "STRICTLY_BEFORE_TARGET_KICKOFF",
                "contract": contract,
                "definition_hash": definition_hash,
                "dataset_version": DATASET_VERSION,
                "dataset_hash": dataset_hash,
                "code_revision": code_revision,
                "created_at": FROZEN_AT,
                "supersedes_id": None,
                "append_only": True,
                "simulation": True,
            }
            examined["feature_definitions"] += 1
            inserted["feature_definitions"] += int(
                _add_or_verify(
                    session,
                    DeepFeatureDefinitionModel,
                    identifier,
                    DeepFeatureDefinitionModel(id=identifier, **expected),
                    expected,
                )
            )

        for raw_row in matrix:
            row = _require_mapping(raw_row, name="coverage_matrix_row")
            competition = str(row["competition"])
            season = str(row["season"])
            for gate, raw_gate_evidence in sorted(gates.items()):
                gate_evidence = _require_mapping(
                    raw_gate_evidence,
                    name=f"gate:{gate}",
                )
                status = str(gate_evidence["status"])
                evidence = {
                    "reasons": gate_evidence.get("reasons", []),
                    "raw_coverage": row,
                    "usable_point_in_time_coverage": _usable_coverage(
                        gate,
                        row,
                    ),
                }
                evidence_hash = canonical_hash(evidence)
                identifier = _identifier(
                    "gate",
                    f"{gate}:{GATE_VERSION}:{competition}:{season}:"
                    f"{_cutoff_class(gate)}:{dataset_hash}",
                )
                expected = {
                    "idempotency_key": (f"j11:gate:{gate}:{competition}:{season}:{dataset_hash}"),
                    "gate_key": gate,
                    "gate_version": GATE_VERSION,
                    "competition": competition,
                    "season": season,
                    "feature_family": gate.removesuffix("_GATE"),
                    "cutoff_class": _cutoff_class(gate),
                    "status": status,
                    "coverage": _usable_coverage(gate, row),
                    "quality_score": (1.0 if status == "READY" else 0.0),
                    "evidence": evidence,
                    "evidence_hash": evidence_hash,
                    "dataset_version": DATASET_VERSION,
                    "dataset_hash": dataset_hash,
                    "code_revision": code_revision,
                    "evaluated_at": AUTHORITATIVE_EVIDENCE_PUBLISHED_AT,
                    "append_only": True,
                    "simulation": True,
                }
                examined["coverage_gates"] += 1
                inserted["coverage_gates"] += int(
                    _add_or_verify(
                        session,
                        CoverageGateModel,
                        identifier,
                        CoverageGateModel(id=identifier, **expected),
                        expected,
                    )
                )
        hypotheses = list(owner_hypotheses())
        team_protocol: dict[str, object] = {
            "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
            "title": "Market-adjusted Team and Calendar Diagnostic",
            "mechanism": "Team and calendar information may add value beyond a train-only recalibration of de-vigged 1X2.",
            "expected_direction": "DELTA_LOG_LOSS_LT_ZERO",
            "markets": ["1X2"],
            "cutoff": "PRE_LINEUP",
            "required_gates": ["TEAM_GATE", "MARKET_GATE"],
            "minimum_support": 80,
            "statistical_family": "team",
            "negative_control": "SHUFFLED_LABELS_STRATIFIED",
            "rejection_criterion": "DELTA_LOG_LOSS_GTE_ZERO_OR_GLOBAL_Q_GT_0_05",
            "frozen_before_results": False,
            "recorded_before_authoritative_incremental_run": True,
            "prior_team_only_diagnostics_seen": True,
            "promotion_eligible": False,
            "protocol_amendment": amendment,
            "protocol_amendment_hash": PROTOCOL_AMENDMENT_HASH,
            "protocol_amendment_source_commit": (protocol_amendment_source_commit),
            "protocol_amendment_published_at": (amendment_published_at.isoformat()),
        }
        hypothesis_payloads: list[dict[str, object]] = [
            item.model_dump(mode="json") for item in hypotheses
        ]
        hypothesis_payloads.append(team_protocol)
        hypothesis_model_ids: dict[str, str] = {}
        for protocol in hypothesis_payloads:
            hypothesis_key = str(protocol["hypothesis_id"])
            hypothesis_version = (
                TEAM_HYPOTHESIS_VERSION
                if hypothesis_key == "H11-A-TEAM-INCREMENTAL"
                else HYPOTHESIS_VERSION
            )
            preregistration_hash = canonical_hash(protocol)
            identifier = _identifier(
                "hypothesis",
                f"{hypothesis_key}:{hypothesis_version}:{dataset_hash}",
            )
            required_gates = [
                str(value)
                for value in _require_list(
                    protocol["required_gates"],
                    name=f"required_gates:{hypothesis_key}",
                )
            ]
            if hypothesis_key == "H11-A-TEAM-INCREMENTAL":
                status = "DATA_GATE_BLOCKED"
                family = "team"
                registered_at = amendment_published_at
                supersedes_id = session.scalar(
                    select(MatchupHypothesisModel.id)
                    .where(
                        MatchupHypothesisModel.hypothesis_id == hypothesis_key,
                        MatchupHypothesisModel.id != identifier,
                    )
                    .order_by(MatchupHypothesisModel.frozen_at.desc())
                    .limit(1)
                )
            else:
                status = "DATA_GATE_BLOCKED"
                family = str(protocol["statistical_family"])
                registered_at = FROZEN_AT
                supersedes_id = None
            expected = {
                "hypothesis_id": hypothesis_key,
                "hypothesis_version": hypothesis_version,
                "title": str(protocol["title"]),
                "family": family,
                "hypothesis": str(protocol["mechanism"]),
                "protocol": protocol,
                "required_gates": required_gates,
                "status": status,
                "preregistration_hash": preregistration_hash,
                "dataset_version": DATASET_VERSION,
                "dataset_hash": dataset_hash,
                "code_revision": code_revision,
                "registered_at": registered_at,
                "frozen_at": registered_at,
                "supersedes_id": supersedes_id,
                "append_only": True,
                "simulation": True,
            }
            examined["hypotheses"] += 1
            inserted["hypotheses"] += int(
                _add_or_verify(
                    session,
                    MatchupHypothesisModel,
                    identifier,
                    MatchupHypothesisModel(id=identifier, **expected),
                    expected,
                )
            )
            hypothesis_model_ids[hypothesis_key] = identifier

        for item in hypotheses:
            eligibility = next(
                value
                for value in _require_list(
                    audit["owner_hypotheses"],
                    name="owner_hypotheses",
                )
                if isinstance(value, dict) and str(value.get("hypothesis_id")) == item.hypothesis_id
            )
            eligibility_map = _require_mapping(
                eligibility,
                name=f"eligibility:{item.hypothesis_id}",
            )
            metrics: dict[str, object] = {
                "blocking_gates": eligibility_map.get(
                    "blocking_gates",
                    [],
                ),
                "eligible": False,
                "executed": False,
                "provider_calls": 0,
                "odds_api_credits": 0,
            }
            evaluation_hash = _hash_metrics(
                {
                    "hypothesis_id": item.hypothesis_id,
                    "metrics": metrics,
                    "dataset_hash": dataset_hash,
                }
            )
            identifier = _identifier(
                "evaluation",
                f"{item.hypothesis_id}:DATA_GATE:{dataset_hash}",
            )
            expected = {
                "idempotency_key": f"j11:evaluation:{evaluation_hash}",
                "hypothesis_id": hypothesis_model_ids[item.hypothesis_id],
                "coverage_gate_id": None,
                "evaluation_scope": "DATA_GATE",
                "fold_key": "NOT_RUN",
                "model_key": "NOT_RUN_DATA_GATE",
                "market": ",".join(item.markets),
                "support": 0,
                "effect": None,
                "metrics": metrics,
                "p_value": None,
                "q_value_family": None,
                "q_value_global": None,
                "status": "DATA_GATE_BLOCKED",
                "paired_sample_hash": dataset_hash,
                "dataset_version": DATASET_VERSION,
                "dataset_hash": dataset_hash,
                "evaluation_hash": evaluation_hash,
                "code_revision": code_revision,
                "evaluated_at": AUTHORITATIVE_EVIDENCE_PUBLISHED_AT,
                "append_only": True,
                "simulation": True,
            }
            examined["evaluations"] += 1
            inserted["evaluations"] += int(
                _add_or_verify(
                    session,
                    MatchupEvaluationModel,
                    identifier,
                    MatchupEvaluationModel(id=identifier, **expected),
                    expected,
                    legacy_numeric_replays=legacy_numeric_replays,
                )
            )

        model_results = _require_mapping(
            campaign["models"],
            name="campaign.models",
        )
        statistics = _require_mapping(
            campaign["statistics"],
            name="campaign.statistics",
        )
        primary_model_key = str(model_results.get("primary_for_inference", ""))
        expected_primary_model = str(
            _require_mapping(
                amendment["primary_inference"],
                name="protocol_amendment.primary_inference",
            )["challenger"]
        )
        if primary_model_key != expected_primary_model:
            raise ValueError("JALON11_PRIMARY_MODEL_AMENDMENT_MISMATCH")
        cr1_p = _as_float(
            statistics["cr1_one_sided_p"],
            name="cr1_one_sided_p",
        )
        sign_flip_p = _as_float(
            statistics["sign_flip_p"],
            name="sign_flip_p",
        )
        conservative_primary_p = max(cr1_p, sign_flip_p)
        support = _as_int(
            campaign["paired_1x2_rows"],
            name="paired_1x2_rows",
        )
        model_keys = tuple(
            model_key
            for model_key in (
                "B1_TEAM_ONLY_REGULARIZED_MULTINOMIAL",
                "B1_TEAM_ONLY_BOUNDED_GRADIENT_BOOSTING",
                "B1_TEAM_ONLY_POISSON",
                "B1_TEAM_ONLY_DIXON_COLES",
                "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL",
                "B1_MARKET_PLUS_TEAM_BOUNDED_GRADIENT_BOOSTING",
            )
            if model_key in model_results
        )
        if primary_model_key not in model_keys:
            raise ValueError("JALON11_PRIMARY_MODEL_RESULT_REQUIRED")
        for model_key in model_keys:
            is_primary = model_key == primary_model_key
            metrics = _require_mapping(
                model_results[model_key],
                name=f"campaign.models.{model_key}",
            )
            delta_log_loss = _as_float(
                metrics["delta_log_loss"],
                name=f"{model_key}.delta_log_loss",
            )
            evaluation_payload: dict[str, object] = {
                "model": metrics,
                "market_baseline": model_results[str(metrics.get("reference", "B0_MARKET"))],
                "statistics": statistics if is_primary else None,
                "folds": campaign["folds"],
                "promotion": campaign["promotion"],
                "provider_calls": 0,
                "odds_api_credits": 0,
                "authoritative_evidence": {
                    "source_commit": AUTHORITATIVE_EVIDENCE_SOURCE_COMMIT,
                    "published_at": (AUTHORITATIVE_EVIDENCE_PUBLISHED_AT.isoformat()),
                    "campaign_result_hash": campaign["result_hash"],
                    "dataset_hash": dataset_hash,
                },
                "inference": {
                    "eligible": is_primary,
                    "multiplicity_included": is_primary,
                    "p_value_rule": (
                        "MAX_CR1_AND_SIGN_FLIP" if is_primary else "NOT_TESTED_DIAGNOSTIC"
                    ),
                    "promotion_eligible": False,
                },
            }
            evaluation_hash = _hash_metrics(
                {
                    "hypothesis_id": "H11-A-TEAM-INCREMENTAL",
                    "model_key": model_key,
                    "metrics": evaluation_payload,
                    "dataset_hash": dataset_hash,
                }
            )
            identifier = _identifier(
                "evaluation",
                f"H11-A-TEAM-INCREMENTAL:{TEAM_HYPOTHESIS_VERSION}:{model_key}:{dataset_hash}",
            )
            expected = {
                "idempotency_key": f"j11:evaluation:{evaluation_hash}",
                "hypothesis_id": hypothesis_model_ids["H11-A-TEAM-INCREMENTAL"],
                "coverage_gate_id": None,
                "evaluation_scope": "EXPANDING_WALK_FORWARD_2022_2025",
                "fold_key": "2022-2025",
                "model_key": model_key,
                "market": "1X2",
                "support": support,
                "effect": -delta_log_loss,
                "metrics": evaluation_payload,
                "p_value": conservative_primary_p if is_primary else None,
                "q_value_family": (
                    _as_float(
                        statistics["family_q"],
                        name="family_q",
                    )
                    if is_primary
                    else None
                ),
                "q_value_global": (
                    _as_float(
                        statistics["global_q"],
                        name="global_q",
                    )
                    if is_primary
                    else None
                ),
                "status": (
                    "DOMINATED"
                    if is_primary and delta_log_loss >= 0.0
                    else "DATA_GATE_BLOCKED"
                    if is_primary
                    else "POST_CONTRACT_DIAGNOSTIC_NON_PROMOTABLE"
                ),
                "paired_sample_hash": dataset_hash,
                "dataset_version": DATASET_VERSION,
                "dataset_hash": dataset_hash,
                "evaluation_hash": evaluation_hash,
                "code_revision": code_revision,
                "evaluated_at": AUTHORITATIVE_EVIDENCE_PUBLISHED_AT,
                "append_only": True,
                "simulation": True,
            }
            examined["evaluations"] += 1
            inserted["evaluations"] += int(
                _add_or_verify(
                    session,
                    MatchupEvaluationModel,
                    identifier,
                    MatchupEvaluationModel(id=identifier, **expected),
                    expected,
                    legacy_numeric_replays=legacy_numeric_replays,
                )
            )

    return {
        "status": "JALON11_COMPACT_EVIDENCE_PERSISTED",
        "dataset_hash": dataset_hash,
        "campaign_result_hash": str(campaign["result_hash"]),
        "examined": examined,
        "inserted": inserted,
        "duplicates_avoided": {key: examined[key] - inserted[key] for key in examined},
        "legacy_numeric_equivalent_evaluations": len(legacy_numeric_replays),
        "heavy_observations_location": "R2_PARQUET",
        "feature_observations_inserted": 0,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
