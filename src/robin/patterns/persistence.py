"""Persistance idempotente des registres compacts de recherche."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from robin.storage.models import (
    BankrollEventModel,
    EvidenceLedgerModel,
    ExperimentRegistryModel,
    PatternDecisionRecordModel,
    PatternDefinitionModel,
    PatternEvaluationModel,
    PatternRunModel,
    PatternSettlementModel,
)


def _identifier(namespace: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:{namespace}:{value}"))


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


def _config_time(payload: dict[str, Any]) -> datetime:
    config = payload.get("config", {})
    raw = str(config.get("preregistered_at", ""))
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("PREREGISTRATION_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _ledger_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("LEDGER_UTC_TIMESTAMP_REQUIRED")
    return parsed.astimezone(UTC)


def _validate_result_hash(payload: dict[str, Any]) -> str:
    claimed = str(payload["result_hash"])
    stable = {
        key: value
        for key, value in payload.items()
        if key not in {"checkpoint", "result_hash", "verdict"}
    }
    calculated = hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()
    if claimed != calculated:
        raise ValueError("PATTERN_CAMPAIGN_RESULT_HASH_MISMATCH")
    return claimed


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

    result_hash = _validate_result_hash(payload)
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
            definition_version = f"1.0.0+{result_hash[:12]}"
            definition_id = _identifier(
                "pattern-definition",
                f"{rule_digest}:{definition_version}",
            )
            definition_payload = {
                "market": hypothesis["market"],
                "selection": hypothesis["selection"],
                "conditions": hypothesis["conditions"],
                "feature_cutoff": str(config["feature_cutoff"]),
                "odds_type": str(config["odds_type"]),
            }
            definition_expected: dict[str, object] = {
                "pattern_id": f"PTRN-{rule_digest[:16].upper()}",
                "pattern_version": definition_version,
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
        experiment_version = f"1.0.0+{result_hash[:12]}"
        experiment_id = _identifier(
            "experiment",
            f"{preregistration_hash}:{experiment_version}",
        )
        experiment_expected: dict[str, object] = {
            "experiment_id": "JALON10-FIRST-CACHE-ONLY-CAMPAIGN",
            "experiment_version": experiment_version,
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


def persist_evidence_ledger(
    engine: Engine,
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Projeter le ledger durable vers les tables Jalon 10 sans mutation."""

    ordered = sorted(
        records,
        key=lambda item: int(str(item["_ledger_sequence_no"])),
    )
    inserted = {
        "decisions": 0,
        "settlements": 0,
        "bankroll_events": 0,
        "evidence_records": 0,
    }
    decision_ids: dict[str, str] = {}
    with Session(engine) as session, session.begin():
        for wrapped in ordered:
            raw = wrapped.get("pattern_ledger_record")
            if not isinstance(raw, Mapping):
                raise ValueError("PATTERN_LEDGER_RECORD_MISSING")
            record = dict(raw)
            sequence_no = int(str(wrapped["_ledger_sequence_no"]))
            record_type = str(record["record_type"])
            decision_model_id: str | None = None
            settlement_model_id: str | None = None
            if record_type == "DECISION":
                decision_id = str(record["decision_id"])
                decision_model_id = _identifier(
                    "pattern-decision",
                    decision_id,
                )
                decision_expected: dict[str, object] = {
                    "decision_id": decision_id,
                    "idempotency_key": str(record["record_hash"]),
                    "pattern_definition_id": None,
                    "pattern_run_id": None,
                    "published_at": _ledger_time(record["published_at"]),
                    "cutoff_at": _ledger_time(record["cutoff_at"]),
                    "fixture_id": str(record["fixture_id"]),
                    "competition": str(record["competition"]),
                    "kickoff_at": _ledger_time(record["kickoff_at"]),
                    "market": str(record["market"]),
                    "selection": str(record["selection"]),
                    "odds": (
                        float(record["odds"])
                        if record.get("odds") is not None
                        else None
                    ),
                    "odds_source": str(record["odds_source"]),
                    "decision": str(record["decision"]),
                    "stake_units": float(record["stake_units"]),
                    "shadow_bankroll_before": float(
                        record["shadow_bankroll_before"]
                    ),
                    "status": str(record["status"]),
                    "code_revision": str(record["code_revision"]),
                    "dataset_hash": str(record["dataset_hash"]),
                    "payload": record,
                    "append_only": True,
                    "simulation": True,
                }
                inserted["decisions"] += int(
                    _add_or_verify(
                        session,
                        PatternDecisionRecordModel,
                        decision_model_id,
                        PatternDecisionRecordModel(
                            id=decision_model_id,
                            **decision_expected,
                        ),
                        decision_expected,
                    )
                )
                decision_ids[decision_id] = decision_model_id
            elif record_type == "SETTLEMENT":
                decision_id = str(record["decision_id"])
                decision_model_id = decision_ids.get(
                    decision_id,
                    _identifier("pattern-decision", decision_id),
                )
                settlement_id = str(record["settlement_id"])
                settlement_model_id = _identifier(
                    "pattern-settlement",
                    settlement_id,
                )
                settlement_expected: dict[str, object] = {
                    "settlement_id": settlement_id,
                    "idempotency_key": str(record["record_hash"]),
                    "pattern_decision_id": decision_model_id,
                    "settled_at": _ledger_time(record["settled_at"]),
                    "result": str(record["result"]),
                    "profit_units": float(record["profit_units"]),
                    "shadow_bankroll_after": float(
                        record["shadow_bankroll_after"]
                    ),
                    "payload": record,
                    "append_only": True,
                    "simulation": True,
                }
                inserted["settlements"] += int(
                    _add_or_verify(
                        session,
                        PatternSettlementModel,
                        settlement_model_id,
                        PatternSettlementModel(
                            id=settlement_model_id,
                            **settlement_expected,
                        ),
                        settlement_expected,
                    )
                )
                bankroll_id = _identifier(
                    "pattern-bankroll-event",
                    settlement_id,
                )
                profit = float(record["profit_units"])
                bankroll_after = float(record["shadow_bankroll_after"])
                bankroll_expected: dict[str, object] = {
                    "event_id": f"BANKROLL-{settlement_id}",
                    "idempotency_key": f"bankroll:{record['record_hash']}",
                    "event_type": "SETTLEMENT",
                    "pattern_decision_id": decision_model_id,
                    "pattern_settlement_id": settlement_model_id,
                    "occurred_at": _ledger_time(record["settled_at"]),
                    "amount_units": profit,
                    "balance_before": bankroll_after - profit,
                    "balance_after": bankroll_after,
                    "payload": record,
                    "append_only": True,
                    "simulation": True,
                }
                inserted["bankroll_events"] += int(
                    _add_or_verify(
                        session,
                        BankrollEventModel,
                        bankroll_id,
                        BankrollEventModel(
                            id=bankroll_id,
                            **bankroll_expected,
                        ),
                        bankroll_expected,
                    )
                )
            else:
                raise ValueError("UNKNOWN_LEDGER_RECORD")

            evidence_id = _identifier(
                "evidence-ledger",
                str(record["record_hash"]),
            )
            evidence_expected: dict[str, object] = {
                "record_id": str(record["record_hash"]),
                "idempotency_key": str(record["record_hash"]),
                "sequence_no": sequence_no,
                "record_type": record_type,
                "pattern_decision_id": decision_model_id,
                "pattern_settlement_id": settlement_model_id,
                "previous_record_hash": str(record["previous_record_hash"]),
                "record_hash": str(record["record_hash"]),
                "payload": record,
                "recorded_at": _ledger_time(
                    record.get("published_at") or record.get("settled_at")
                ),
                "append_only": True,
                "simulation": True,
            }
            inserted["evidence_records"] += int(
                _add_or_verify(
                    session,
                    EvidenceLedgerModel,
                    evidence_id,
                    EvidenceLedgerModel(
                        id=evidence_id,
                        **evidence_expected,
                    ),
                    evidence_expected,
                )
            )
    examined = len(ordered)
    return {
        "status": "PATTERN_EVIDENCE_LEDGER_PERSISTED",
        "records_examined": examined,
        "inserted": inserted,
        "duplicates_avoided": {
            "evidence_records": examined - inserted["evidence_records"],
        },
    }
