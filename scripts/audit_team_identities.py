"""Read existing R2/Neon evidence and emit a compact team-identity audit."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import bindparam, create_engine, text

from robin.historical.object_storage_migration import create_r2_client
from robin.prospective_observatory.contracts import CaptureFamily, canonical_sha256
from robin.prospective_observatory.r2 import (
    R2_NAMESPACE,
    ProspectiveR2Repository,
)
from robin.prospective_observatory.team_identities import (
    TeamIdentityEvidence,
    build_team_identity_registry,
    extract_team_identity_evidence,
    fixture_identity_scope_sha256,
)

ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyR2Store:
    """S3 adapter whose write surface always fails closed."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        self.client, self.bucket = create_r2_client(environment)
        self.list_requests = 0
        self.get_requests = 0
        self.bytes_read = 0

    @staticmethod
    def _missing(error: ClientError) -> bool:
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    def get_object(self, key: str) -> bytes | None:
        self.get_requests += 1
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._missing(error):
                return None
            raise
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise RuntimeError("R2_BODY_INVALID")
        payload = body.read()
        if not isinstance(payload, bytes):
            raise RuntimeError("R2_BODY_INVALID")
        self.bytes_read += len(payload)
        return payload

    def put_if_absent(self, key: str, data: bytes) -> bool:
        del key, data
        raise RuntimeError("TEAM_IDENTITY_AUDIT_R2_READ_ONLY")

    def iter_keys(self, prefix: str) -> Iterable[str]:
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if token is not None:
                kwargs["ContinuationToken"] = token
            self.list_requests += 1
            response = cast(Any, self.client).list_objects_v2(**kwargs)
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RuntimeError("R2_LIST_RESPONSE_INVALID")
            for item in contents:
                if isinstance(item, Mapping) and isinstance(item.get("Key"), str):
                    yield str(item["Key"])
            if not bool(response.get("IsTruncated")):
                return
            candidate = response.get("NextContinuationToken")
            if not isinstance(candidate, str) or not candidate:
                raise RuntimeError("R2_LIST_CURSOR_MISSING")
            token = candidate


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("TEAM_IDENTITY_SNAPSHOT_INVALID")
    return cast(dict[str, object], value)


def _active_fixtures(snapshot: Mapping[str, object]) -> list[dict[str, object]]:
    observatory = snapshot.get("prospectiveObservatory")
    if not isinstance(observatory, Mapping):
        raise RuntimeError("TEAM_IDENTITY_OBSERVATORY_MISSING")
    fixtures = observatory.get("fixtures")
    registry = fixtures.get("registry") if isinstance(fixtures, Mapping) else None
    if not isinstance(registry, list):
        raise RuntimeError("TEAM_IDENTITY_FIXTURE_REGISTRY_MISSING")
    active: list[dict[str, object]] = []
    for value in registry:
        if not isinstance(value, dict):
            raise RuntimeError("TEAM_IDENTITY_FIXTURE_INVALID")
        status = str(value.get("status", "REGISTERED"))
        if value.get("cancelled") is True or status in {
            "CANCELLED",
            "CANCELED",
            "TOMBSTONED",
            "DELETED",
        }:
            continue
        active.append(dict(value))
    if not active:
        raise RuntimeError("TEAM_IDENTITY_FIXTURE_SCOPE_EMPTY")
    return sorted(active, key=lambda item: str(item.get("fixture_id", "")))


def _safe_segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("R2_KEY_SEGMENT_INVALID")
    return quote(value, safe="-_.~")


def _candidate_receipt_keys(
    store: ReadOnlyR2Store,
    fixtures: list[dict[str, object]],
) -> tuple[str, ...]:
    fixture_ids = {str(fixture["fixture_id"]) for fixture in fixtures}
    competitions = {str(fixture["competition"]) for fixture in fixtures}
    keys: set[str] = set()
    for competition in sorted(competitions):
        prefix = (
            f"{R2_NAMESPACE}/schema-v1/"
            f"competition={_safe_segment(competition)}/"
        )
        for key in store.iter_keys(prefix):
            if "/family=FIXTURE/" not in key or "/receipt-" not in key:
                continue
            if not key.endswith(".json"):
                continue
            if any(
                f"/fixture={_safe_segment(fixture_id)}/" in key
                for fixture_id in fixture_ids
            ):
                keys.add(key)
    return tuple(sorted(keys))


def _postgresql_projection(
    database_url: str,
    *,
    evidence: list[TeamIdentityEvidence],
    fixtures: list[dict[str, object]],
) -> tuple[dict[str, dict[str, bool]], dict[str, int]]:
    receipt_ids = sorted({item.source_receipt_id for item in evidence})
    fixture_ids = sorted({str(item["fixture_id"]) for item in fixtures})
    receipt_query = text(
        """
        SELECT
          cr.receipt_hash,
          cr.fixture_id,
          cr.provider,
          cr.family,
          cr.payload_sha256,
          cr.r2_key,
          cr.receipt_r2_key,
          pi.payload_sha256 AS index_payload_sha256,
          pi.r2_key AS index_r2_key,
          pi.receipt_r2_key AS index_receipt_r2_key
        FROM capture_receipts AS cr
        LEFT JOIN prospective_payload_index AS pi ON pi.receipt_id = cr.id
        WHERE cr.receipt_hash IN :receipt_ids
        """
    ).bindparams(bindparam("receipt_ids", expanding=True))
    fixture_query = text(
        """
        SELECT
          fixture_id,
          provider,
          provider_fixture_id,
          home_team_id,
          away_team_id,
          competition,
          season
        FROM prospective_fixtures
        WHERE fixture_id IN :fixture_ids
        """
    ).bindparams(bindparam("fixture_ids", expanding=True))
    engine = create_engine(database_url)
    rows_read = 0
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                receipt_rows = list(
                    connection.execute(
                        receipt_query,
                        {"receipt_ids": receipt_ids},
                    ).mappings()
                )
                fixture_rows = list(
                    connection.execute(
                        fixture_query,
                        {"fixture_ids": fixture_ids},
                    ).mappings()
                )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    rows_read = len(receipt_rows) + len(fixture_rows)

    receipt_by_id = {str(row["receipt_hash"]): row for row in receipt_rows}
    fixture_set = {
        (
            str(row["fixture_id"]),
            str(row["provider"]),
            str(row["provider_fixture_id"]),
            str(row["home_team_id"]),
            str(row["away_team_id"]),
            str(row["competition"]),
            str(row["season"]),
        )
        for row in fixture_rows
    }
    fixtures_by_id = {str(fixture["fixture_id"]): fixture for fixture in fixtures}
    seasons_by_fixture = {
        item.fixture_id: item.season
        for item in evidence
    }
    projection: dict[str, dict[str, bool]] = {}
    for item in evidence:
        receipt_row = receipt_by_id.get(item.source_receipt_id)
        fixture = fixtures_by_id[item.fixture_id]
        receipt_verified = bool(
            receipt_row
            and str(receipt_row["fixture_id"]) == item.fixture_id
            and str(receipt_row["provider"]) == item.provider
            and str(receipt_row["family"]) == CaptureFamily.FIXTURE.value
            and str(receipt_row["payload_sha256"])
            == item.source_payload_sha256
            and str(receipt_row["r2_key"]) == item.source_payload_r2_key
            and str(receipt_row["receipt_r2_key"])
            == item.source_receipt_r2_key
        )
        index_verified = bool(
            receipt_row
            and str(receipt_row["index_payload_sha256"])
            == item.source_payload_sha256
            and str(receipt_row["index_r2_key"])
            == item.source_payload_r2_key
            and str(receipt_row["index_receipt_r2_key"])
            == item.source_receipt_r2_key
        )
        fixture_verified = (
            (
                item.fixture_id,
                str(fixture["provider"]),
                str(fixture["provider_fixture_id"]),
                str(fixture["home_team_id"]),
                str(fixture["away_team_id"]),
                str(fixture["competition"]),
                seasons_by_fixture[item.fixture_id],
            )
            in fixture_set
        )
        projection[item.source_receipt_id] = {
            "capture_receipt_verified": receipt_verified,
            "payload_index_verified": index_verified,
            "fixture_projection_verified": fixture_verified,
        }
    return projection, {
        "transactions": 1,
        "read_queries": 2,
        "rows_read": rows_read,
        "writes": 0,
    }


def build_report(
    snapshot_path: Path,
    *,
    database_url: str,
    environment: Mapping[str, str],
) -> dict[str, object]:
    snapshot = _read_json(snapshot_path)
    fixtures = _active_fixtures(snapshot)
    store = ReadOnlyR2Store(environment)
    repository = ProspectiveR2Repository(store)
    evidence: list[TeamIdentityEvidence] = []
    for receipt_key in _candidate_receipt_keys(store, fixtures):
        capture = repository.read_capture(receipt_key)
        if capture.receipt.fixture_id not in {
            str(item["fixture_id"]) for item in fixtures
        }:
            continue
        evidence.extend(extract_team_identity_evidence(capture))

    latest: dict[tuple[str, str], TeamIdentityEvidence] = {}
    for item in sorted(
        evidence,
        key=lambda value: (
            value.captured_at,
            value.source_receipt_id,
            value.side,
        ),
    ):
        latest[(item.fixture_id, item.side)] = item
    selected: list[TeamIdentityEvidence] = []
    unresolved: list[dict[str, str]] = []
    for fixture in fixtures:
        fixture_id = str(fixture["fixture_id"])
        for side in ("home", "away"):
            selected_item = latest.get((fixture_id, side))
            expected_team_id = str(fixture[f"{side}_team_id"])
            if (
                selected_item is None
                or selected_item.provider_team_id != expected_team_id
            ):
                unresolved.append(
                    {
                        "fixture_id": fixture_id,
                        "side": side,
                        "provider_team_id": expected_team_id,
                        "reason": "VERIFIED_FIXTURE_IDENTITY_NOT_FOUND",
                    }
                )
            else:
                selected.append(selected_item)

    projection, postgresql_reads = _postgresql_projection(
        database_url,
        evidence=selected,
        fixtures=fixtures,
    )
    identities = []
    for item in sorted(
        selected,
        key=lambda value: (value.fixture_id, value.side),
    ):
        public = item.public_dict()
        public["postgresql_projection"] = projection[item.source_receipt_id]
        identities.append(public)
    registry = build_team_identity_registry(selected)
    fixture_slots = len(fixtures) * 2
    selected_slots = {(item.fixture_id, item.side) for item in selected}
    resolved_fixtures = sum(
        all(
            (str(fixture["fixture_id"]), side) in selected_slots
            for side in ("home", "away")
        )
        for fixture in fixtures
    )
    generated_at = datetime.now(UTC)
    report: dict[str, object] = {
        "schema_version": "team-identity-provenance-v1",
        "generated_at": generated_at.isoformat(),
        "source": "EXISTING_VERIFIED_R2_FIXTURE_CAPTURES",
        "source_priority": [
            "R2_FIXTURE_PAYLOAD",
            "VERIFIED_RECEIPT",
            "POSTGRESQL_PROJECTION",
            "DURABLE_IDENTITY_REGISTRY",
        ],
        "fixture_scope_sha256": fixture_identity_scope_sha256(fixtures),
        "coverage": {
            "fixtures_expected": len(fixtures),
            "fixtures_resolved": resolved_fixtures,
            "team_slots_expected": fixture_slots,
            "team_slots_resolved": len(selected),
            "team_slots_unresolved": len(unresolved),
            "percentage": round(
                (len(selected) / fixture_slots) * 100 if fixture_slots else 0,
                3,
            ),
        },
        "identities": identities,
        "unresolved": unresolved,
        "registry": registry.public_dict(),
        "registry_sha256": registry.sha256,
        "reads": {
            "r2": {
                "list_requests": store.list_requests,
                "get_requests": store.get_requests,
                "bytes_read": store.bytes_read,
                "receipt_objects_read": store.get_requests // 2,
                "payload_objects_read": store.get_requests // 2,
                "writes": 0,
            },
            "postgresql": postgresql_reads,
        },
        "provider_usage": {
            "api_football_calls": 0,
            "odds_api_credits": 0,
        },
        "invariants": {
            "r2_read_only": True,
            "postgresql_read_only": True,
            "raw_payloads_in_report": 0,
            "signed_urls_in_report": 0,
            "secrets_in_report": 0,
            "football_observation_times_mutated": False,
            "provider_calls": 0,
            "odds_credits": 0,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=ROOT / "cockpit" / "app" / "cockpit-data.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "ux" / "team-identity-provenance.json",
    )
    parser.add_argument("--require-complete", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    database_url = os.getenv("ROBIN_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("TEAM_IDENTITY_DATABASE_URL_MISSING")
    report = build_report(
        args.snapshot,
        database_url=database_url,
        environment=os.environ,
    )
    coverage = cast(dict[str, Any], report["coverage"])
    if args.require_complete and (
        coverage["fixtures_expected"] != coverage["fixtures_resolved"]
        or coverage["team_slots_expected"] != coverage["team_slots_resolved"]
    ):
        raise RuntimeError("TEAM_IDENTITY_COVERAGE_INCOMPLETE")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "TEAM_IDENTITY_AUDIT_COMPLETE "
        f"fixtures={coverage['fixtures_resolved']}/{coverage['fixtures_expected']} "
        f"teams={coverage['team_slots_resolved']}/{coverage['team_slots_expected']}"
    )


if __name__ == "__main__":
    main()
