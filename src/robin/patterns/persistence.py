"""Persistance idempotente des registres compacts de recherche."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from robin.storage.models import (
    ExperimentRegistryModel,
    PatternDefinitionModel,
    PatternEvaluationModel,
    PatternRunModel,
)


def _identifier(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:{namespace}:{value}"))


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _config_time(payload: dict[str, Any]) -> datetime:
    config = payload.get("config", {})
    raw = str(config.get("preregistered_at", ""))
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("PREREGISTRATION_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _add_or_verify(
    session: Session,
    model_type: type[Any],
    identity: str,
    instance: Any,
    expected: dict[str, object],
) -> bool:
    existing = session.get(model_type, identity)
    if existing is None:
        session.add(instance)
        return True
    actual = {key: getattr(existing, key) for key in expected}
    if _canonical(actual) != _canonical(expected):
        raise ValueError(f"IMMUTABLE_PATTERN_PERSISTENCE_CONFLICT:{identity}")
    return False


def persist_campaign(engine: Engine, payload: dict[str, Any]) -> dict[str, object]:
    """Insère ou vérifie un replay; aucune mise à jour silencieuse n'est admise."""

    result_hash = str(payload["result_hash"])
    dataset_hash = str(payload["dataset_hashes"][0])
    registered_at = _config_time(payload)
    config = dict(payload["config"])
    counts = dict(payload["counts"])
    hypotheses: list[dict[str, Any]] = list(payload["hypotheses"])
    run_id = _identifier("pattern-run", result_hash)
    run_expected: dict[str, object] = {
        "idempotency_key": result_hash,
        "run_type": "CACHE_ONLY_DISCOVERY_VALIDATION",
        "seed": int(config["seed"]),
        "code_revision": str(payload["code_revision"]),
        "configuration": config,
        "dataset_hashes": list(payload["dataset_hashes"]),
        "environment": {
            "provider_calls": 0,
            "odds_api_credits": 0,
            "storage_paused": True,
        },
        "status": "COMPLETE",
        "rules_generated": int(counts["hypotheses_generated"]),
        "rules_executed": int(counts["hypotheses_executed"]),
        "rules_rejected": int(counts["leakage_rejected"])
        + int(counts["support_rejected"]),
        "cost_units": 0.0,
        "checkpoint": dict(payload["checkpoint"]),
        "simulation": True,
    }
    inserted = {"runs": 0, "definitions": 0, "evaluations": 0, "experiments": 0}
    with Session(engine) as session, session.begin():
        run = PatternRunModel(
            id=run_id,
            started_at=registered_at,
            finished_at=registered_at,
            **run_expected,
        )
        inserted["runs"] += int(
            _add_or_verify(
                session,
                PatternRunModel,
                run_id,
                run,
                run_expected,
            )
        )
        for hypothesis in hypotheses:
            rule_digest = str(hypothesis["rule_hash"])
            definition_id = _identifier("pattern-definition", rule_digest)
            definition_payload = {
                "market": hypothesis["market"],
                "selection": hypothesis["selection"],
                "conditions": hypothesis["conditions"],
                "feature_cutoff": "T_MINUS_60_MINUTES",
                "odds_type": "HISTORICAL_CLOSING_MARKET",
            }
            definition_expected: dict[str, object] = {
                "pattern_id": f"PTRN-{rule_digest[:16].upper()}",
                "pattern_version": "1.0.0",
                "rule_hash": rule_digest,
                "sport": "football",
                "market": str(hypothesis["market"]),
                "selection": str(hypothesis["selection"]),
                "status": str(hypothesis["status"]),
                "evidence_scope": str(hypothesis["evidence_scope"]),
                "definition": definition_payload,
                "code_revision": str(payload["code_revision"]),
                "dataset_hashes": list(payload["dataset_hashes"]),
                "supersedes_id": None,
            }
            definition = PatternDefinitionModel(
                id=definition_id,
                created_at=registered_at,
                **definition_expected,
            )
            inserted["definitions"] += int(
                _add_or_verify(
                    session,
                    PatternDefinitionModel,
                    definition_id,
                    definition,
                    definition_expected,
                )
            )
            evaluation_id = _identifier(
                "pattern-evaluation",
                f"{result_hash}:{rule_digest}",
            )
            evaluation_expected: dict[str, object] = {
                "pattern_definition_id": definition_id,
                "pattern_run_id": run_id,
                "evaluation_scope": str(hypothesis["evidence_scope"]),
                "fold_key": "AGGREGATE_AND_EXPOSED_WALK_FORWARD",
                "support": int(
                    dict(hypothesis.get("support") or {}).get("observations", 0)
                ),
                "metrics": hypothesis,
                "p_value": float(hypothesis["p_value"]),
                "q_value": float(hypothesis["q_value"]),
                "status": str(hypothesis["status"]),
                "dataset_hash": dataset_hash,
                "simulation": True,
            }
            evaluation = PatternEvaluationModel(
                id=evaluation_id,
                evaluated_at=registered_at,
                **evaluation_expected,
            )
            inserted["evaluations"] += int(
                _add_or_verify(
                    session,
                    PatternEvaluationModel,
                    evaluation_id,
                    evaluation,
                    evaluation_expected,
                )
            )
        preregistration_hash = hashlib.sha256(
            _canonical(config).encode("utf-8")
        ).hexdigest()
        experiment_id = _identifier("experiment", preregistration_hash)
        experiment_expected: dict[str, object] = {
            "experiment_id": "JALON10-FIRST-CACHE-ONLY-CAMPAIGN",
            "experiment_version": "1.0.0",
            "preregistration_hash": preregistration_hash,
            "hypothesis": (
                "Des règles simples équipe/marché peuvent-elles survivre aux "
                "contrôles sur historique exposé sans être appelées validées ?"
            ),
            "protocol": config,
            "dataset_scope": {
                "classification": payload["data_classification"],
                "dataset_hashes": payload["dataset_hashes"],
            },
            "status": str(payload["verdict"]),
            "code_revision": str(payload["code_revision"]),
            "pattern_definition_id": None,
            "supersedes_id": None,
            "simulation": True,
        }
        experiment = ExperimentRegistryModel(
            id=experiment_id,
            registered_at=registered_at,
            frozen_at=registered_at,
            **experiment_expected,
        )
        inserted["experiments"] += int(
            _add_or_verify(
                session,
                ExperimentRegistryModel,
                experiment_id,
                experiment,
                experiment_expected,
            )
        )
    return {
        "status": "PATTERN_CAMPAIGN_PERSISTED",
        "inserted": inserted,
        "replayed": {
            key: (
                (1 if key in {"runs", "experiments"} else len(hypotheses))
                - value
            )
            for key, value in inserted.items()
        },
        "provider_calls": 0,
        "result_hash": result_hash,
    }
