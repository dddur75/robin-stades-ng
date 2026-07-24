"""Écriture transactionnelle, bundles append-only et replay sans fournisseur."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine, insert, select, update

from robin.storage.database import transaction
from robin.storage.durable_schema import (
    REGISTRY_TABLES,
    ingestion_runs,
    metadata,
    raw_payloads,
)


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def stable_id(namespace: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"robin:{namespace}:{value}"))


@dataclass(frozen=True)
class DurableRecord:
    kind: str
    business_key: str
    payload: Mapping[str, object]
    provider: str
    observed_at: datetime
    ingested_at: datetime
    source_run_id: str
    schema_version: str = "shadow-durable-v1"
    provenance_status: str = "LIVE SOURCE"
    quality_status: str = "OBSERVED"

    @property
    def hash(self) -> str:
        return content_hash(self.payload)

    @property
    def record_id(self) -> str:
        return stable_id(self.kind, f"{self.business_key}:{self.hash}")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "business_key": self.business_key,
            "payload": dict(self.payload),
            "provider": self.provider,
            "observed_at": self.observed_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "source_run_id": self.source_run_id,
            "schema_version": self.schema_version,
            "provenance_status": self.provenance_status,
            "quality_status": self.quality_status,
            "content_hash": self.hash,
            "record_id": self.record_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DurableRecord:
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("payload durable invalide")
        return cls(
            kind=str(value["kind"]),
            business_key=str(value["business_key"]),
            payload={str(key): item for key, item in payload.items()},
            provider=str(value["provider"]),
            observed_at=datetime.fromisoformat(str(value["observed_at"])),
            ingested_at=datetime.fromisoformat(str(value["ingested_at"])),
            source_run_id=str(value["source_run_id"]),
            schema_version=str(value.get("schema_version", "shadow-durable-v1")),
            provenance_status=str(value.get("provenance_status", "LIVE SOURCE")),
            quality_status=str(value.get("quality_status", "OBSERVED")),
        )


class DurableRegistry:
    """Registre SQL compatible SQLite pour les tests et PostgreSQL en cible."""

    def __init__(self, engine: Engine, *, initialize: bool = False) -> None:
        self.engine = engine
        if initialize:
            metadata.create_all(engine)

    def ensure_run(
        self,
        *,
        run_id: str,
        pipeline_name: str,
        started_at: datetime,
        status: str,
        source_version: str,
        backend: str,
    ) -> bool:
        row = {
            "id": stable_id("ingestion-run", run_id),
            "idempotency_key": run_id,
            "pipeline_name": pipeline_name,
            "started_at": started_at,
            "finished_at": datetime.now(UTC),
            "status": status,
            "source_version": source_version,
            "durable_backend": backend,
            "durable_commit": None,
            "error_message": None,
        }
        with transaction(self.engine) as session:
            known = session.execute(
                select(ingestion_runs.c.id).where(
                    ingestion_runs.c.idempotency_key == run_id
                )
            ).scalar_one_or_none()
            if known is not None:
                return False
            session.execute(insert(ingestion_runs).values(**row))
        return True

    def append(self, record: DurableRecord) -> bool:
        if record.kind not in REGISTRY_TABLES:
            raise ValueError(f"type durable inconnu: {record.kind}")
        table = REGISTRY_TABLES[record.kind]
        values = _record_values(record)
        with transaction(self.engine) as session:
            existing = session.execute(
                select(table.c.id).where(table.c.id == record.record_id)
            ).scalar_one_or_none()
            if existing is not None:
                session.execute(
                    update(table)
                    .where(table.c.id == record.record_id)
                    .values(last_observed_at=record.observed_at)
                )
                return False
            session.execute(insert(table).values(**values))
        return True

    def append_many(self, records: Iterable[DurableRecord]) -> dict[str, int]:
        """Insérer un lot en conservant l'idempotence par identifiant stable."""
        grouped: dict[str, dict[str, DurableRecord]] = {}
        examined = 0
        for record in records:
            examined += 1
            if record.kind not in REGISTRY_TABLES:
                raise ValueError(f"type durable inconnu: {record.kind}")
            grouped.setdefault(record.kind, {})[record.record_id] = record

        inserted = 0
        with transaction(self.engine) as session:
            for kind, unique_records in grouped.items():
                table = REGISTRY_TABLES[kind]
                record_ids = tuple(unique_records)
                existing: set[str] = set()
                for offset in range(0, len(record_ids), 500):
                    existing.update(
                        str(value)
                        for value in session.execute(
                            select(table.c.id).where(
                                table.c.id.in_(record_ids[offset : offset + 500])
                            )
                        ).scalars()
                    )
                new_rows = [
                    _record_values(record)
                    for record_id, record in unique_records.items()
                    if record_id not in existing
                ]
                if new_rows:
                    session.execute(insert(table), new_rows)
                    inserted += len(new_rows)
        return {
            "examined": examined,
            "inserted": inserted,
            "duplicates": examined - inserted,
        }

    def append_raw_payload(
        self,
        *,
        payload_hash: str,
        provider: str,
        object_location: str,
        byte_size: int,
        observed_at: datetime,
        schema_version: str,
    ) -> bool:
        with transaction(self.engine) as session:
            known = session.execute(
                select(raw_payloads.c.id).where(
                    raw_payloads.c.content_hash == payload_hash
                )
            ).scalar_one_or_none()
            if known is not None:
                session.execute(
                    update(raw_payloads)
                    .where(raw_payloads.c.id == known)
                    .values(last_observed_at=observed_at)
                )
                return False
            session.execute(
                insert(raw_payloads).values(
                    id=stable_id("raw-payload", payload_hash),
                    content_hash=payload_hash,
                    provider=provider,
                    object_location=object_location,
                    byte_size=byte_size,
                    compression="gzip",
                    schema_version=schema_version,
                    created_at=observed_at,
                    last_observed_at=observed_at,
                )
            )
        return True

    def replay(self, bundle: Mapping[str, object]) -> dict[str, int]:
        run = bundle.get("run")
        if not isinstance(run, Mapping):
            raise ValueError("run absent du bundle")
        run_id = str(run["run_id"])
        self.ensure_run(
            run_id=run_id,
            pipeline_name=str(run.get("pipeline", "replay")),
            started_at=datetime.fromisoformat(str(run["started_at"])),
            status="REPLAYED",
            source_version=str(run.get("source_version", "unknown")),
            backend="POSTGRESQL",
        )
        inserted = duplicates = 0
        records = bundle.get("records", [])
        if not isinstance(records, list):
            raise ValueError("records invalides")
        for value in records:
            if not isinstance(value, Mapping):
                continue
            if self.append(DurableRecord.from_dict(value)):
                inserted += 1
            else:
                duplicates += 1
        return {"inserted": inserted, "duplicates": duplicates}


def _extra_values(kind: str, payload: Mapping[str, object]) -> dict[str, object]:
    fixture_id = str(payload.get("fixture_id") or payload.get("internal_fixture_id") or "")
    mapping: dict[str, dict[str, object]] = {
        "provider_requests": {
            "raw_payload_id": (
                stable_id("raw-payload", str(payload["payload_hash"]))
                if payload.get("payload_hash")
                else None
            ),
            "endpoint": str(payload.get("endpoint") or "unknown"),
            "http_status": _maybe_int(payload.get("http_status")),
            "quota_cost": _to_int(payload.get("quota_cost")),
        },
        "durable_fixtures": {
            "fixture_id": fixture_id or str(payload.get("id", "")),
            "kickoff_at": _maybe_datetime(payload.get("kickoff_at") or payload.get("commence_time")),
            "competition": payload.get("competition") or payload.get("sport_title"),
            "status": payload.get("status") or "SCHEDULED",
        },
        "provider_entity_mappings": {
            "internal_entity_id": str(payload.get("internal_entity_id") or fixture_id),
            "provider_entity_id": str(payload.get("provider_entity_id") or payload.get("id", "")),
            "entity_type": str(payload.get("entity_type") or "fixture"),
        },
        "bookmakers": {"bookmaker_id": str(payload.get("bookmaker_id") or payload.get("id", ""))},
        "markets": {
            "market_key": str(payload.get("market_key") or payload.get("market_type", "")),
            "market_type": str(payload.get("market_type") or "UNKNOWN"),
        },
        "odds_snapshots": {
            "fixture_id": fixture_id,
            "snapshot_id": str(payload.get("snapshot_id", "")),
            "market_type": str(payload.get("market_type") or "MULTI"),
        },
        "prediction_runs": {"model_version": str(payload.get("model_version") or "unknown")},
        "predictions": {
            "fixture_id": fixture_id,
            "prediction_id": str(payload.get("prediction_id", "")),
            "model_version": str(payload.get("model_version") or "unknown"),
        },
        "candidate_bets": {
            "fixture_id": fixture_id,
            "strategy_version": str(payload.get("strategy_version") or "unknown"),
        },
        "rejected_bets": {
            "fixture_id": fixture_id,
            "reason_code": str(payload.get("primary_reason") or payload.get("reason") or "UNKNOWN"),
        },
        "shadow_bets": {
            "fixture_id": fixture_id,
            "strategy_version": str(payload.get("strategy_version") or "unknown"),
            "stake": _to_float(payload.get("suggested_stake")),
            "simulation": True,
        },
        "settlements": {
            "fixture_id": fixture_id,
            "settlement_status": str(payload.get("status") or "PENDING"),
        },
        "quality_runs": {"overall_status": str(payload.get("status") or "UNKNOWN")},
        "quality_results": {
            "check_code": str(payload.get("check") or payload.get("check_code") or "UNKNOWN"),
            "check_status": str(payload.get("status") or "UNKNOWN"),
        },
        "pipeline_incidents": {
            "incident_code": str(payload.get("incident_code") or "UNKNOWN"),
            "severity": str(payload.get("severity") or "INFO"),
            "incident_status": str(payload.get("status") or "OPEN"),
        },
        "quota_usage": {
            "credits_used": _to_int(
                payload.get("credits_used") or payload.get("quota_used")
            ),
            "credits_remaining": _maybe_int(payload.get("credits_remaining") or payload.get("quota_remaining")),
            "budget_level": str(payload.get("budget_level") or "NORMAL"),
        },
        "scheduler_windows": {
            "fixture_id": fixture_id,
            "window_name": str(payload.get("window") or payload.get("window_name") or "UNKNOWN"),
            "scheduled_for": _required_datetime(payload.get("scheduled_for")),
            "acceptable_from": _required_datetime(payload.get("acceptable_from")),
            "acceptable_until": _required_datetime(payload.get("acceptable_until")),
            "last_attempt_at": _maybe_datetime(payload.get("last_attempt_at")),
            "attempt_count": _to_int(payload.get("attempt_count")),
            "window_status": str(payload.get("status") or payload.get("window_status") or "PENDING"),
            "observation_received": bool(payload.get("observation_received", False)),
            "market_available": payload.get("market_available"),
            "provider_status": payload.get("provider_status"),
        },
        "burn_in_daily_metrics": {
            "metric_date": (
                datetime.fromisoformat(str(payload["date"])).date()
                if payload.get("date")
                else datetime.now(UTC).date()
            ),
            "health_status": str(payload.get("health_status") or "INSUFFICIENT_OBSERVATION"),
            "coverage_rate": _to_float(payload.get("coverage_rate")),
            "workflow_success_rate": _to_float(
                payload.get("workflow_success_rate")
            ),
        },
    }
    return mapping.get(kind, {})


def _record_values(record: DurableRecord) -> dict[str, object]:
    values: dict[str, object] = {
        "id": record.record_id,
        "business_key": record.business_key,
        "content_hash": record.hash,
        "provider": record.provider,
        "observed_at": record.observed_at,
        "ingested_at": record.ingested_at,
        "schema_version": record.schema_version,
        "source_run_id": stable_id("ingestion-run", record.source_run_id),
        "provenance_status": record.provenance_status,
        "quality_status": record.quality_status,
        "payload": dict(record.payload),
        "created_at": record.ingested_at,
        "last_observed_at": record.observed_at,
    }
    values.update(_extra_values(record.kind, record.payload))
    return values


def _maybe_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _required_datetime(value: object) -> datetime:
    return _maybe_datetime(value) or datetime.now(UTC)


def _maybe_int(value: object) -> int | None:
    return None if value in (None, "") else _to_int(value)


def _to_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        return int(value)
    return 0


def _to_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def write_bundle(
    path: Path,
    *,
    run: Mapping[str, object],
    records: Iterable[DurableRecord],
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "shadow-bundle-v1",
        "run": dict(run),
        "records": [record.as_dict() for record in records],
    }
    encoded = canonical_json(payload)
    path.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    return {
        "bundle": path.name,
        "content_hash": hashlib.sha256(encoded).hexdigest(),
        "compressed_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "records": len(payload["records"]),
        "bytes": path.stat().st_size,
    }


def read_bundle(path: Path) -> dict[str, object]:
    with gzip.open(path, "rb") as stream:
        value = json.loads(stream.read())
    if not isinstance(value, dict):
        raise ValueError("bundle durable invalide")
    return value
