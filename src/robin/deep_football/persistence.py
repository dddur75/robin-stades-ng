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

from robin.deep_football.contracts import canonical_hash
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
FROZEN_AT = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _identifier(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:j11:{namespace}:{value}"))


def _canonical(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, datetime):
            normalized = (
                item.replace(tzinfo=UTC)
                if item.tzinfo is None
                else item.astimezone(UTC)
            )
            return normalized.isoformat()
        return str(item)

    return json.dumps(
        value,
        default=default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _add_or_verify(
    session: Session,
    model_type: type[ModelT],
    identifier: str,
    model: ModelT,
    expected: Mapping[str, object],
) -> bool:
    existing = session.scalar(
        select(model_type).where(model_type.id == identifier)
    )
    if existing is None:
        session.add(model)
        return True
    mismatches = [
        field
        for field, value in expected.items()
        if _canonical(getattr(existing, field)) != _canonical(value)
    ]
    if mismatches:
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


def _feature_family(feature: str) -> str:
    if feature.startswith("elo_"):
        return "TEAM_STRENGTH"
    if "rest" in feature:
        return "CALENDAR"
    return "TEAM_FORM"


def _feature_contract(feature: str) -> dict[str, object]:
    window = next(
        (
            int(token)
            for token in feature.split("_")
            if token.isdigit()
        ),
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
    if gate in {"TEAM_GATE", "MARKET_GATE"}:
        return "HISTORICAL_PREMATCH_RESEARCH"
    return "UNPROVEN_PREMATCH_OR_POST_MATCH_ONLY"


def _hash_metrics(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def persist_deep_football_evidence(
    engine: Engine,
    artifact_dir: Path,
    *,
    code_revision: str,
) -> dict[str, object]:
    """Persister puis vérifier les preuves compactes sans aucune mutation."""

    audit = _read_json(artifact_dir / "audit-summary.json")
    manifest = _read_json(artifact_dir / "dataset-manifest.json")
    campaign = _read_json(artifact_dir / "campaign-11a-summary.json")
    if _as_int(
        audit.get("provider_calls", -1),
        name="provider_calls",
    ) != 0:
        raise ValueError("JALON11_PROVIDER_CALLS_MUST_BE_ZERO")
    if _as_int(
        audit.get("odds_api_credits", -1),
        name="odds_api_credits",
    ) != 0:
        raise ValueError("JALON11_ODDS_CREDITS_MUST_BE_ZERO")
    if campaign.get("production_status") != "PRODUCTION_LOCKED":
        raise ValueError("JALON11_PRODUCTION_MUST_REMAIN_LOCKED")
    dataset_hash = str(manifest["dataset_hash"])
    if len(dataset_hash) != 64:
        raise ValueError("JALON11_DATASET_HASH_INVALID")
    features = [
        str(value)
        for value in _require_list(manifest.get("features"), name="features")
    ]
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
                    "idempotency_key": (
                        f"j11:gate:{gate}:{competition}:{season}:{dataset_hash}"
                    ),
                    "gate_key": gate,
                    "gate_version": GATE_VERSION,
                    "competition": competition,
                    "season": season,
                    "feature_family": gate.removesuffix("_GATE"),
                    "cutoff_class": _cutoff_class(gate),
                    "status": status,
                    "coverage": _usable_coverage(gate, row),
                    "quality_score": (
                        1.0 if status == "READY" else 0.0
                    ),
                    "evidence": evidence,
                    "evidence_hash": evidence_hash,
                    "dataset_version": DATASET_VERSION,
                    "dataset_hash": dataset_hash,
                    "code_revision": code_revision,
                    "evaluated_at": FROZEN_AT,
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
            "hypothesis_id": "H11-A-TEAM-CORE",
            "title": "Team and Calendar Deep Baseline",
            "mechanism": "Team and calendar information may add value beyond de-vigged 1X2.",
            "expected_direction": "LOWER_LOG_LOSS_THAN_MARKET",
            "markets": ["1X2"],
            "cutoff": "PRE_LINEUP",
            "required_gates": ["TEAM_GATE", "MARKET_GATE"],
            "minimum_support": 80,
            "statistical_family": "team",
            "negative_control": "SHUFFLED_LABELS",
            "rejection_criterion": "DELTA_LOG_LOSS_GTE_ZERO_OR_GLOBAL_Q_GT_0_05",
            "frozen_before_results": True,
        }
        hypothesis_payloads: list[dict[str, object]] = [
            item.model_dump(mode="json") for item in hypotheses
        ]
        hypothesis_payloads.append(team_protocol)
        hypothesis_model_ids: dict[str, str] = {}
        for protocol in hypothesis_payloads:
            hypothesis_key = str(protocol["hypothesis_id"])
            preregistration_hash = canonical_hash(protocol)
            identifier = _identifier(
                "hypothesis",
                f"{hypothesis_key}:{HYPOTHESIS_VERSION}:{dataset_hash}",
            )
            required_gates = [
                str(value)
                for value in _require_list(
                    protocol["required_gates"],
                    name=f"required_gates:{hypothesis_key}",
                )
            ]
            if hypothesis_key == "H11-A-TEAM-CORE":
                status = "DOMINATED"
                family = "team"
            else:
                status = "DATA_GATE_BLOCKED"
                family = str(protocol["statistical_family"])
            expected = {
                "hypothesis_id": hypothesis_key,
                "hypothesis_version": HYPOTHESIS_VERSION,
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
                "registered_at": FROZEN_AT,
                "frozen_at": FROZEN_AT,
                "supersedes_id": None,
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
                if isinstance(value, dict)
                and str(value.get("hypothesis_id")) == item.hypothesis_id
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
                "evaluated_at": FROZEN_AT,
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
        support = _as_int(
            campaign["paired_1x2_rows"],
            name="paired_1x2_rows",
        )
        for model_key in (
            "B1_REGULARIZED_MULTINOMIAL",
            "B1_BOUNDED_GRADIENT_BOOSTING",
        ):
            metrics = _require_mapping(
                model_results[model_key],
                name=f"campaign.models.{model_key}",
            )
            evaluation_payload: dict[str, object] = {
                "model": metrics,
                "market_baseline": model_results["B0_MARKET"],
                "statistics": statistics,
                "folds": campaign["folds"],
                "promotion": campaign["promotion"],
                "provider_calls": 0,
                "odds_api_credits": 0,
            }
            evaluation_hash = _hash_metrics(
                {
                    "hypothesis_id": "H11-A-TEAM-CORE",
                    "model_key": model_key,
                    "metrics": evaluation_payload,
                    "dataset_hash": dataset_hash,
                }
            )
            identifier = _identifier(
                "evaluation",
                f"H11-A-TEAM-CORE:{model_key}:{dataset_hash}",
            )
            expected = {
                "idempotency_key": f"j11:evaluation:{evaluation_hash}",
                "hypothesis_id": hypothesis_model_ids["H11-A-TEAM-CORE"],
                "coverage_gate_id": None,
                "evaluation_scope": "EXPANDING_WALK_FORWARD_2022_2025",
                "fold_key": "2022-2025",
                "model_key": model_key,
                "market": "1X2",
                "support": support,
                "effect": -_as_float(
                    metrics["delta_log_loss"],
                    name=f"{model_key}.delta_log_loss",
                ),
                "metrics": evaluation_payload,
                "p_value": _as_float(
                    statistics["sign_flip_p"],
                    name="sign_flip_p",
                ),
                "q_value_family": _as_float(
                    statistics["family_q"],
                    name="family_q",
                ),
                "q_value_global": _as_float(
                    statistics["global_q"],
                    name="global_q",
                ),
                "status": "DOMINATED",
                "paired_sample_hash": dataset_hash,
                "dataset_version": DATASET_VERSION,
                "dataset_hash": dataset_hash,
                "evaluation_hash": evaluation_hash,
                "code_revision": code_revision,
                "evaluated_at": FROZEN_AT,
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
                )
            )

    return {
        "status": "JALON11_COMPACT_EVIDENCE_PERSISTED",
        "dataset_hash": dataset_hash,
        "campaign_result_hash": str(campaign["result_hash"]),
        "examined": examined,
        "inserted": inserted,
        "duplicates_avoided": {
            key: examined[key] - inserted[key] for key in examined
        },
        "heavy_observations_location": "R2_PARQUET",
        "feature_observations_inserted": 0,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
