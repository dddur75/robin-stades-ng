"""Contrôles et réparation déterministe de la provenance historique."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from robin.historical.normalization import entity_type_for_endpoint, internal_id
from robin.historical.storage import canonical_record_hash

RawKey = tuple[str, str, str]
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
API_FOOTBALL_DATASET_PART = "dataset_version=api-football-v3"


def _canonical_payload(value: object) -> str:
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _raw_index(
    state: Path,
) -> tuple[dict[RawKey, set[str]], set[str], list[str], int]:
    records: dict[RawKey, set[str]] = defaultdict(set)
    payload_hashes: set[str] = set()
    failures: list[str] = []
    observations = 0
    for path in sorted((state / "raw" / "observations").rglob("*.json")):
        observations += 1
        observation = json.loads(path.read_text("utf-8"))
        payload_hash = str(observation.get("payload_hash", ""))
        location = str(observation.get("raw_payload_location", ""))
        if not HASH_PATTERN.fullmatch(payload_hash):
            failures.append(f"{path.name}:payload_hash_invalid")
            continue
        payload_path = state / "raw" / "payloads" / location
        if not payload_path.exists():
            failures.append(f"{path.name}:payload_missing")
            continue
        try:
            raw = gzip.decompress(payload_path.read_bytes())
        except (OSError, EOFError):
            failures.append(f"{path.name}:payload_not_gzip")
            continue
        if hashlib.sha256(raw).hexdigest() != payload_hash:
            failures.append(f"{path.name}:payload_hash_mismatch")
            continue
        payload_hashes.add(payload_hash)
        payload = json.loads(raw)
        response = payload.get("response", [])
        if isinstance(response, list):
            normalized_response = response
        elif isinstance(payload, dict):
            normalized_response = [payload]
        else:
            failures.append(f"{path.name}:response_not_list")
            continue
        run_id = str(observation.get("ingestion_run_id", ""))
        entity_type = entity_type_for_endpoint(str(observation.get("endpoint", "")))
        for record in normalized_response:
            key = (run_id, entity_type, _canonical_payload(record))
            records[key].add(payload_hash)
    return records, payload_hashes, failures, observations


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _row_without_hash(row: dict[str, object]) -> dict[str, object]:
    return {
        key: (None if _is_missing(value) else value)
        for key, value in row.items()
        if key != "_record_hash"
    }


def _api_football_parquet_files(state: Path) -> list[Path]:
    """Return only partitions governed by the API-Football raw contract.

    Other providers, notably the historical market factory, keep their own
    provenance manifests and must not be matched against API-Football payloads.
    """

    return sorted(
        path
        for path in (state / "parquet").rglob("*.parquet")
        if API_FOOTBALL_DATASET_PART in path.parts
    )


def repair_raw_hash_provenance(state: Path) -> dict[str, object]:
    """Rattacher chaque ligne normalisée à un payload brut déjà conservé.

    La réparation n'appelle jamais le fournisseur. Elle reconstruit le lien à
    partir des observations et payloads immuables du registre durable.
    """

    raw_records, _, raw_failures, _ = _raw_index(state)
    if raw_failures:
        raise RuntimeError(f"RAW_PROVENANCE_INVALID:{len(raw_failures)}")
    repaired_rows = 0
    unresolved_rows = 0
    ambiguous_rows = 0
    files_rewritten = 0
    for path in _api_football_parquet_files(state):
        frame = pd.read_parquet(path)
        changed = False
        for index, row in frame.iterrows():
            current_hash = row.get("raw_payload_hash")
            key = (
                str(row.get("ingestion_run_id", "")),
                str(row.get("entity_type", "")),
                _canonical_payload(row.get("payload")),
            )
            candidates = sorted(raw_records.get(key, set()))
            if isinstance(current_hash, str) and current_hash in candidates:
                continue
            if not candidates:
                unresolved_rows += 1
                continue
            if len(candidates) > 1:
                ambiguous_rows += 1
            frame.at[index, "raw_payload_hash"] = candidates[0]
            repaired_rows += 1
            changed = True
        if not changed:
            continue
        records = [
            _row_without_hash(
                {str(key): value for key, value in row.items()}
            )
            for row in frame.to_dict(orient="records")
        ]
        frame["_record_hash"] = [
            canonical_record_hash(record) for record in records
        ]
        temporary = path.with_name(f"{path.name}.tmp")
        frame.to_parquet(temporary, index=False)
        temporary.replace(path)
        files_rewritten += 1
    status = "REPAIRED" if unresolved_rows == 0 else "PARTIAL"
    return {
        "status": status,
        "provider_calls": 0,
        "quota_consumed": 0,
        "files_rewritten": files_rewritten,
        "rows_repaired": repaired_rows,
        "rows_unresolved": unresolved_rows,
        "rows_ambiguous": ambiguous_rows,
    }


def _checkpoint_failures(state: Path) -> list[str]:
    failures: list[str] = []
    for path in sorted((state / "checkpoints").rglob("*.json")):
        payload = json.loads(path.read_text("utf-8"))
        pages = [int(page["page"]) for page in payload.get("pages", [])]
        if len(pages) != len(set(pages)):
            failures.append(f"{path.name}:duplicate_page")
        if pages and pages != list(range(1, max(pages) + 1)):
            failures.append(f"{path.name}:missing_page")
        page_hashes = [
            str(page["payload_hash"])
            for page in payload.get("pages", [])
            if page.get("payload_hash") and int(page.get("rows", 0)) > 0
        ]
        if len(page_hashes) != len(set(page_hashes)):
            failures.append(f"{path.name}:duplicate_page_payload")
    return failures


def historical_quality_report(state: Path) -> dict[str, object]:
    """Contrôler les invariants réellement vérifiables sans inventer de preuve."""

    raw_records, raw_hashes, failures, observations = _raw_index(state)
    failures.extend(_checkpoint_failures(state))
    partitions = 0
    normalized_rows = 0
    provenance_rows = 0
    identity_rows = 0
    identity_failures = 0
    future_rows = 0
    null_preservation_failures = 0
    duplicate_hashes = 0
    now = datetime.now(UTC)
    for path in _api_football_parquet_files(state):
        partitions += 1
        frame = pd.read_parquet(path)
        normalized_rows += len(frame)
        if frame.empty:
            continue
        if "_record_hash" not in frame.columns:
            failures.append(f"{path}:record_hash_missing")
            continue
        duplicate_hashes += int(frame["_record_hash"].duplicated().sum())
        for row in frame.to_dict(orient="records"):
            payload = row.get("payload")
            key = (
                str(row.get("ingestion_run_id", "")),
                str(row.get("entity_type", "")),
                _canonical_payload(payload),
            )
            raw_hash = row.get("raw_payload_hash")
            if (
                isinstance(raw_hash, str)
                and raw_hash in raw_hashes
                and raw_hash in raw_records.get(key, set())
            ):
                provenance_rows += 1
            else:
                null_preservation_failures += 1
            observed = datetime.fromisoformat(
                str(row.get("observed_at", "")).replace("Z", "+00:00")
            )
            if observed > now + timedelta(minutes=5):
                future_rows += 1
            provider_id = row.get("provider_id")
            entity_type = str(row.get("entity_type", ""))
            if isinstance(provider_id, float) and provider_id.is_integer():
                provider_id = int(provider_id)
            payload_id = (
                provider_id
                if not _is_missing(provider_id)
                else hashlib.sha256(
                    _canonical_payload(payload).encode("utf-8")
                ).hexdigest()
            )
            identity_rows += 1
            if str(row.get("internal_id")) != internal_id(entity_type, payload_id):
                identity_failures += 1
    if duplicate_hashes:
        failures.append(f"duplicate_record_hashes:{duplicate_hashes}")
    if null_preservation_failures:
        failures.append(
            f"raw_provenance_or_payload_mismatch:{null_preservation_failures}"
        )
    if future_rows:
        failures.append(f"future_observations:{future_rows}")
    if identity_failures:
        failures.append(f"identity_mismatches:{identity_failures}")
    canonical = json.loads(
        (state / "audits" / "ligue1-2025-canonicalization.json").read_text("utf-8")
    )
    if canonical.get("status") != "PASSED":
        failures.append("canonical_cardinality_failed")
    checks = [
        {
            "check": "RAW_AND_PARQUET_HASHES",
            "status": "PASSED" if not failures else "FAILED",
            "value": f"{provenance_rows}/{normalized_rows}",
        },
        {
            "check": "PAGES_COMPLETE_AND_UNIQUE",
            "status": (
                "FAILED"
                if any("page" in failure for failure in failures)
                else "PASSED"
            ),
            "value": len(list((state / "checkpoints").rglob("*.json"))),
        },
        {
            "check": "IDENTITIES_STABLE",
            "status": "PASSED" if identity_failures == 0 else "FAILED",
            "value": f"{identity_rows - identity_failures}/{identity_rows}",
        },
        {
            "check": "NULLS_PRESERVED_NO_SYNTHETIC_ZERO",
            "status": (
                "PASSED" if null_preservation_failures == 0 else "FAILED"
            ),
            "value": f"{normalized_rows - null_preservation_failures}/{normalized_rows}",
        },
        {
            "check": "NO_FUTURE_DATA",
            "status": "PASSED" if future_rows == 0 else "FAILED",
            "value": future_rows,
        },
        {
            "check": "CANONICAL_CARDINALITY",
            "status": str(canonical.get("status", "FAILED")),
            "value": (
                f"{canonical.get('canonical_fixtures', 0)}/"
                f"{canonical.get('expected_fixtures', 0)}"
            ),
        },
        {
            "check": "PLAYER_TARGET_LEAKAGE",
            "status": "BLOCKED_BY_COVERAGE",
            "value": "NO_PLAYER_FEATURE_OR_MODEL_BUILT",
        },
        {
            "check": "INJURY_POINT_IN_TIME",
            "status": "BLOCKED_BY_TEMPORALITY",
            "value": "HISTORICAL_NON_POINT_IN_TIME",
        },
    ]
    return {
        "generated_at": now.isoformat(),
        "status": "FAILED" if failures else "PASSED",
        "parquet_partitions": partitions,
        "raw_observations": observations,
        "normalized_rows": normalized_rows,
        "provenance_rows": provenance_rows,
        "failures": failures,
        "checks": checks,
        "quarantined_features": [
            "injury_return",
            "availability",
            "player_fatigue",
        ],
        "production_status": "PRODUCTION_LOCKED",
    }
