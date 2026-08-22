#!/usr/bin/env python3
"""Build deterministic, synthetic-only live-canary capability artifacts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from robin.capture import (
    LIVE_ALLOWED_MARKET_SETS,
    LIVE_ALLOWED_MARKETS,
    LIVE_ALLOWED_REGION,
    LIVE_ALLOWED_SPORT_KEYS,
    LIVE_CAPABILITY_VERSION,
    LIVE_MISSION_ID,
    ActivationEnvelopeV1,
    FixtureMapping,
    LiveAdmissionPermitV1,
    LiveCaptureLineageV1,
    LiveExecutionAttemptReceiptV1,
    LiveExecutionReceiptV1,
    LiveLeaseV1,
    LivePlanItemV1,
    LivePlanV1,
    LiveResponseIntakeClaimV1,
    OwnerAuthorizationV1,
    ProviderRequestSpec,
    PublicProviderRequestV1,
    RequestFingerprint,
    fixture_mappings_sha256,
)
from robin.capture.contracts import MappingStatus, canonical_sha256

GOLDEN_PATH = Path("tests/capture/fixtures/bounded-live-canary-v1-golden-pack.json")
REPORT_PATH = Path("reports/data-sourcing/bounded-live-canary-capability-v1.json")
SYNTHETIC_SHA = "a" * 40
SYNTHETIC_ROOT_FINGERPRINT = "b" * 64
SYNTHETIC_GIT_EXECUTABLE_SHA256 = "c" * 64
SYNTHETIC_REPOSITORY_ROOT_FINGERPRINT = "d" * 64
SYNTHETIC_CONTROL_TEMP_ROOT_FINGERPRINT = "e" * 64
SYNTHETIC_PROVIDER_IP_ADDRESS = "1.1.1.1"
BASE = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
CAPABILITY_REPORT_CLAIM_ID = "GOV.BOUNDED_LIVE_CANARY.CAPABILITY.REPORT.V1.001"
NON_EXECUTION_CLAIM_ID = "SCIENCE.BOUNDED_LIVE_CANARY.NON_EXECUTION.V1.001"
ZERO_EFFECTS_CLAIM_ID = "SECURITY.BOUNDED_LIVE_CANARY.ZERO_EFFECTS.V1.001"
ZERO_REAL_EFFECTS = 0


def _json_text(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def build_golden_pack() -> dict[str, Any]:
    request = ProviderRequestSpec(
        endpoint="/v4/sports/soccer_spain_la_liga/odds",
        sport_key="soccer_spain_la_liga",
        markets=("h2h", "totals"),
    )
    mapping = FixtureMapping(
        provider_event_id="synthetic-live-event-001",
        fixture_id="synthetic-live-fixture-001",
        status=MappingStatus.MAPPED,
        candidate_fixture_ids=("synthetic-live-fixture-001",),
        mapping_revision="synthetic-live-mapping-v1",
    )
    mappings = (mapping,)
    authorization = OwnerAuthorizationV1.issue(
        authorization_id="synthetic-owner-authorization-golden-001",
        authorized_main_sha=SYNTHETIC_SHA,
        issued_at_utc=BASE - timedelta(hours=1),
        not_before_utc=BASE - timedelta(minutes=30),
        expires_at_utc=BASE + timedelta(hours=1),
        allowed_sport_keys=LIVE_ALLOWED_SPORT_KEYS,
        allowed_market_sets=LIVE_ALLOWED_MARKET_SETS,
        maximum_http_calls=1,
        maximum_credits=2,
        maximum_plan_items=1,
        approved_capture_root_fingerprint=SYNTHETIC_ROOT_FINGERPRINT,
        approved_repository_root_fingerprint=SYNTHETIC_REPOSITORY_ROOT_FINGERPRINT,
        approved_control_temp_root_fingerprint=SYNTHETIC_CONTROL_TEMP_ROOT_FINGERPRINT,
        approved_git_executable_sha256=SYNTHETIC_GIT_EXECUTABLE_SHA256,
        approved_provider_ip_address=SYNTHETIC_PROVIDER_IP_ADDRESS,
        authorization_nonce="synthetic-owner-authorization-nonce-golden-001",
    )
    activation_material = {
        "activation_id": "synthetic-activation-golden-001",
        "authorization_id": authorization.authorization_id,
        "authorization_hash": authorization.canonical_authorization_hash,
        "repository_sha": SYNTHETIC_SHA,
        "sport_key": request.sport_key,
        "region": request.region,
        "markets": request.markets,
        "not_before_utc": BASE,
        "expires_at_utc": BASE + timedelta(minutes=10),
        "maximum_http_calls": 1,
        "maximum_credits": 2,
        "activation_nonce": "synthetic-activation-nonce-golden-001",
    }
    activation_scope = ActivationEnvelopeV1.issue(
        plan_sha256="0" * 64,
        **activation_material,
    )
    item = LivePlanItemV1.issue(
        item_id="synthetic-live-item-golden-001",
        plan_id="synthetic-live-plan-golden-001",
        sequence=1,
        sport_key=request.sport_key,
        region=request.region,
        markets=request.markets,
        provider_request_fingerprint=RequestFingerprint.create(request).request_sha256,
        fixture_mappings_sha256=fixture_mappings_sha256(mappings),
        not_before_utc=BASE,
        expires_at_utc=BASE + timedelta(minutes=10),
        maximum_credits=2,
        purpose="ENTIRELY_SYNTHETIC_CAPABILITY_CONTRACT_PROOF",
        window_label="SYNTHETIC_GOLDEN_WINDOW_001",
    )
    plan = LivePlanV1.issue(
        plan_id=item.plan_id,
        activation_id=activation_scope.activation_id,
        activation_hash=activation_scope.activation_scope_sha256,
        repository_sha=SYNTHETIC_SHA,
        created_at_utc=BASE,
        expires_at_utc=BASE + timedelta(minutes=10),
        items=(item,),
        maximum_http_calls=1,
        maximum_credits=2,
    )
    activation = ActivationEnvelopeV1.issue(
        plan_sha256=plan.canonical_plan_hash,
        **activation_material,
    )
    return {
        "schema_version": "robin-bounded-live-canary-golden-pack-v1",
        "provenance": "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD_NO_REAL_AUTHORITY",
        "repository_sha_is_synthetic": True,
        "capture_root_fingerprint_is_synthetic": True,
        "authorization": authorization.model_dump(mode="json"),
        "activation": activation.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "request": request.model_dump(mode="json"),
        "fixture_mappings": [mapping.model_dump(mode="json")],
        "expected": {
            "activation_scope_sha256": activation.activation_scope_sha256,
            "authorization_hash": authorization.canonical_authorization_hash,
            "item_hash": item.canonical_item_hash,
            "plan_hash": plan.canonical_plan_hash,
            "request_fingerprint_sha256": RequestFingerprint.create(request).request_sha256,
        },
        "mission_effects": {
            "provider_calls": 0,
            "provider_dns_calls": 0,
            "real_secret_reads": ZERO_REAL_EFFECTS,
            "purchases": 0,
            "promotions": 0,
            "bets": 0,
        },
    }


def build_report(pack: dict[str, Any]) -> dict[str, Any]:
    contract_types = (
        OwnerAuthorizationV1,
        ActivationEnvelopeV1,
        LivePlanV1,
        LivePlanItemV1,
        LiveAdmissionPermitV1,
        LiveResponseIntakeClaimV1,
        LiveCaptureLineageV1,
        LiveExecutionAttemptReceiptV1,
        LiveLeaseV1,
        LiveExecutionReceiptV1,
        PublicProviderRequestV1,
    )
    return {
        "schema_version": "robin-bounded-live-canary-capability-report-v1",
        "artifact": "bounded-live-canary-capability-v1",
        "mission_id": LIVE_MISSION_ID,
        "capability_version": LIVE_CAPABILITY_VERSION,
        "capability_status": "IMPLEMENTED_SYNTHETICALLY_TESTED_NO_REAL_ACTIVATION",
        "claim_ids": {
            "capability_contract": CAPABILITY_REPORT_CLAIM_ID,
            "non_execution_state": NON_EXECUTION_CLAIM_ID,
            "zero_external_effects": ZERO_EFFECTS_CLAIM_ID,
        },
        "default_state": "DEFAULT_DENY",
        "real_authorization_present": False,
        "real_authorization_status": "NOT_CREATED",
        "real_activation_present": False,
        "real_activation_status": "NOT_CREATED",
        "real_batch_status": "NOT_EXECUTED",
        "real_capture_count": 0,
        "real_snapshot_status": "NOT_CREATED",
        "real_snapshot_count": 0,
        "experiment_readiness_status": "NOT_ASSESSED_ON_REAL_DATA",
        "real_executable_experiment_count": 0,
        "accumulation_candidates": [],
        "network_calls": 0,
        "network_calls_scope": (
            "PROVIDER_AND_PROVIDER_DNS_ONLY_AUTHORIZED_GIT_GITHUB_DELIVERY_EXCLUDED"
        ),
        "real_provider_calls": 0,
        "real_provider_dns_calls": 0,
        "real_secret_reads": ZERO_REAL_EFFECTS,
        "purchases": 0,
        "promotions": 0,
        "bets": 0,
        "sport_allowlist": list(LIVE_ALLOWED_SPORT_KEYS),
        "region_policy": LIVE_ALLOWED_REGION,
        "market_policy": [list(value) for value in LIVE_ALLOWED_MARKET_SETS],
        "allowed_markets": list(LIVE_ALLOWED_MARKETS),
        "hash_dag": [
            "OWNER_AUTHORIZATION_HASH",
            "ACTIVATION_SCOPE_SHA256_WITHOUT_PLAN",
            "PLAN_HASH_BINDS_ACTIVATION_SCOPE",
            "FINAL_ACTIVATION_HASH_BINDS_PLAN_HASH",
        ],
        "contract_schemas": {
            contract_type.__name__: canonical_sha256(contract_type.model_json_schema())
            for contract_type in contract_types
        },
        "golden_pack_path": GOLDEN_PATH.as_posix(),
        "golden_pack_sha256": canonical_sha256(pack),
        "storage_policy": "OUTSIDE_GIT_LOCAL_NON_SYNCHRONISED_CONTENT_ADDRESSED_TTL_GOVERNED",
        "storage_layout": [
            "live/authority-bindings",
            "live/leases",
            "live/budget-events",
            "live/dispatch-armed",
            "live/admission-consumed",
            "live/admission-consumed-anchors",
            "live/dispatch-started",
            "live/dispatch-started-anchors",
            "live/response-intake-claimed",
            "live/response-intake-anchors",
            "live/capture-lineage",
            "live/execution-attempts",
            "live/execution-receipts",
            "live/terminal",
        ],
        "provider_network_policy": (
            "OWNER_APPROVED_CANONICAL_GLOBAL_IP_DIRECT_SOCKET_NO_DNS_EXACT_PEER_TLS_SNI_HOST"
        ),
        "local_execution_boundary": ("OWNER_ATTESTED_EXCLUSIVE_OS_ACL_NO_CONCURRENT_MUTATOR"),
        "external_owner_authenticity_boundary": (
            "EXTERNALLY_VERIFIED_NOT_CRYPTOGRAPHICALLY_PROVEN"
        ),
        "next_required_external_action": (
            "SEPARATE_OWNER_AUTHORIZATION_BOUND_TO_FINAL_MERGED_MAIN_SHA"
        ),
        "automatic_activation": False,
        "promotion": False,
        "bet": False,
    }


def write_artifacts(repo: Path, documents: Mapping[Path, object]) -> None:
    for relative, document in documents.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_text(document), encoding="utf-8", newline="\n")


def check_artifacts(repo: Path, documents: Mapping[Path, object]) -> None:
    failures = [
        relative.as_posix()
        for relative, document in documents.items()
        if not (repo / relative).is_file()
        or (repo / relative).read_text(encoding="utf-8") != _json_text(document)
    ]
    if failures:
        raise SystemExit(f"BOUNDED_LIVE_CANARY_ARTIFACT_CHECK_FAILED:{','.join(failures)}")
    print(
        "BOUNDED_LIVE_CANARY_ARTIFACT_CHECK_PASS:"
        f"{len(documents)}:{canonical_sha256({str(k): v for k, v in documents.items()})}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    pack = build_golden_pack()
    documents: dict[Path, object] = {
        GOLDEN_PATH: pack,
        REPORT_PATH: build_report(pack),
    }
    if args.check:
        check_artifacts(repo, documents)
    else:
        write_artifacts(repo, documents)
        print(f"BOUNDED_LIVE_CANARY_ARTIFACTS_WRITTEN:{len(documents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
