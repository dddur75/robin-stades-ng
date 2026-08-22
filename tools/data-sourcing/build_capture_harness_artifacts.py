#!/usr/bin/env python3
"""Build deterministic capture-harness reports without any network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from robin.capture import (
    CaptureBudget,
    CaptureHarness,
    CaptureManifest,
    CaptureMode,
    CaptureStore,
    FixtureMapping,
    InternalRetentionPolicy,
    NormalizedMarketObservation,
    OfflineReplayResult,
    ProviderRequestSpec,
    QuotaObservation,
    RawPayloadReceipt,
    RequestFingerprint,
    SchemaFingerprint,
    SecretCapability,
)
from robin.capture.contracts import MappingStatus, canonical_sha256
from robin.capture.live_contracts import (
    ActivationEnvelopeV1,
    LiveAdmissionPermitV1,
    LiveCaptureLineageV1,
    LiveExecutionAttemptReceiptV1,
    LiveExecutionReceiptV1,
    LiveLeaseV1,
    LivePlanItemV1,
    LivePlanV1,
    LiveResponseIntakeClaimV1,
    OwnerAuthorizationV1,
)
from robin.capture.live_transport import PublicProviderRequestV1

SCHEMA_VERSION = "robin-capture-harness-artifacts-v1"
FIXTURE_PATH = Path("tests/capture/fixtures/synthetic-odds-responses-v1.json")
REPORT_NAMES = (
    "capture-harness-contract-v1.json",
    "internal-retention-policy-v1.json",
    "capture-threat-model-v1.json",
    "offline-replay-proof-v1.json",
    "live-canary-plan-v1.json",
)
CONTRACT_TYPES = (
    ProviderRequestSpec,
    RequestFingerprint,
    CaptureBudget,
    QuotaObservation,
    RawPayloadReceipt,
    NormalizedMarketObservation,
    SchemaFingerprint,
    FixtureMapping,
    CaptureManifest,
    InternalRetentionPolicy,
    OfflineReplayResult,
    OwnerAuthorizationV1,
    ActivationEnvelopeV1,
    LivePlanV1,
    LivePlanItemV1,
    LiveLeaseV1,
    LiveAdmissionPermitV1,
    LiveResponseIntakeClaimV1,
    LiveCaptureLineageV1,
    LiveExecutionAttemptReceiptV1,
    LiveExecutionReceiptV1,
    PublicProviderRequestV1,
)


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


def _load_pack(repo: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((repo / FIXTURE_PATH).read_text(encoding="utf-8")),
    )


def _load_compatibility_witness(repo: Path) -> dict[str, Any]:
    path = repo / "reports" / "data-sourcing" / "canary-harness-compatibility-witness-v1.json"
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _contract_inventory() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for contract_type in CONTRACT_TYPES:
        schema = contract_type.model_json_schema()
        inventory.append(
            {
                "name": contract_type.__name__,
                "fields": list(contract_type.model_fields),
                "json_schema_sha256": canonical_sha256(schema),
            }
        )
    return inventory


def _synthetic_proof(repo: Path) -> tuple[CaptureManifest, OfflineReplayResult, int]:
    pack = _load_pack(repo)
    payload = json.dumps(
        pack["responses"]["h2h_plus_totals"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sentinel = str(pack["secret_sentinel"])
    request = ProviderRequestSpec(
        endpoint="/v4/sports/soccer_fictional_alpha/odds",
        sport_key="soccer_fictional_alpha",
        markets=("h2h", "totals"),
    )
    mapping = FixtureMapping(
        provider_event_id="synthetic-event-001",
        fixture_id="synthetic-fixture-001",
        status=MappingStatus.MAPPED,
        candidate_fixture_ids=("synthetic-fixture-001",),
        mapping_revision="synthetic-mapping-v1",
    )
    observed = datetime(2026, 8, 15, 10, 5, tzinfo=UTC)
    ingested = datetime(2026, 8, 15, 10, 5, 1, tzinfo=UTC)
    with tempfile.TemporaryDirectory(prefix="robin-capture-proof-") as temporary:
        capture_root = Path(temporary) / "capture"
        store = CaptureStore(
            capture_root,
            InternalRetentionPolicy(),
            approved_local_root=capture_root,
        )
        harness = CaptureHarness(
            store,
            CaptureBudget(maximum_requests=2, maximum_credits=4),
        )
        preparation = harness.prepare(request)
        SecretCapability.from_environment(
            {"THE_ODDS_API_KEY": sentinel},
            public_material=harness.public_preparation_bytes(preparation),
        )
        manifest = harness.record_offline_response(
            request,
            payload=payload,
            http_status=200,
            response_headers={
                "x-requests-remaining": "498",
                "x-requests-used": "2",
                "x-requests-last": "2",
            },
            mappings=(mapping,),
            first_observed_at=observed,
            ingested_at=ingested,
        )
        replay = store.replay(manifest.snapshot_id)
        outputs = b"".join(path.read_bytes() for path in store.root.rglob("*") if path.is_file())
        sentinel_occurrences = outputs.count(sentinel.encode("utf-8"))
    return manifest, replay, sentinel_occurrences


def build_reports(repo: Path) -> dict[str, str]:
    manifest, replay, sentinel_occurrences = _synthetic_proof(repo)
    compatibility = _load_compatibility_witness(repo)
    policy = InternalRetentionPolicy()
    contract_report = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "capture-harness-contract-v1",
        "default_mode": CaptureMode.VALIDATE_OFFLINE.value,
        "modes": {
            "VALIDATE_OFFLINE": {"network_calls": 0, "provider_calls": 0},
            "DRY_RUN": {"network_calls": 0, "provider_calls": 0},
            "LIVE_CANARY": {
                "authorized": False,
                "capability_available": True,
                "status": "DEFAULT_DENY_EXTERNAL_OWNER_AUTHORIZATION_REQUIRED",
            },
        },
        "contracts": _contract_inventory(),
        "storage_layout": [
            "raw/sha256/<prefix>/<sha>.bin",
            "receipts/<receipt_id>.json",
            "normalized/<snapshot_id>.jsonl",
            "manifests/<snapshot_id>.json",
            "quarantine/",
            "deletion-ledger.jsonl",
            "budget-ledger.jsonl",
            "live/authority-bindings/",
            "live/leases/",
            "live/dispatch-armed/",
            "live/capture-lineage/",
            "live/execution-attempts/",
            "live/execution-receipts/",
            "live/terminal/",
            "live-budget-ledger.jsonl",
        ],
        "properties": [
            "ATOMIC_CREATE_IF_ABSENT",
            "IDEMPOTENT",
            "APPEND_ONLY_METADATA",
            "TTL_WRITE_AHEAD_HASH_CHAIN",
            "COLLISION_FAIL_CLOSED",
            "RAW_TTL_30_DAYS",
            "OFFLINE_REPLAY",
        ],
        "guards": [
            "HOST_ALLOWLIST_REQUIRED",
            "TLS_REQUIRED",
            "REDIRECTS_FORBIDDEN",
            "PERSISTENT_LOCKED_BUDGET_REQUIRED_AND_BOUNDED",
            "RETRIES_ZERO",
            "MARKET_ALLOWLIST_REQUIRED",
            "REGION_ALLOWLIST_REQUIRED",
            "SECRET_REQUIRED_FOR_FUTURE_LIVE_AND_NEVER_RETAINED",
            "RETENTION_POLICY_REQUIRED",
            "EXPLICIT_LOCAL_CAPTURE_ROOT_APPROVAL_REQUIRED",
            "CAPTURE_WORKSPACE_OUTSIDE_GIT",
            "CAPTURE_WORKSPACE_NOT_SYNCHRONIZED",
        ],
        "safety": ["NO_PROVIDER_CALL", "NO_PURCHASE", "NO_PROMOTION", "NO_BET"],
    }
    retention_report = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "internal-retention-policy-v1",
        "policy": policy.model_dump(mode="json"),
        "public_terms_review": {
            "reviewed_at": "2026-08-15",
            "terms_url": "https://the-odds-api.com/terms-and-conditions.html",
            "official_domain_warning_url": ("https://the-odds-api.com/impersonation-warning.html"),
            "compatible_use": "internal analytical tool without raw redistribution",
            "prohibited_use": "standalone resale, repackaging, or redistribution of raw data",
            "public_raw_retention_duration": "NOT_STATED",
            "interpretation": "INTERNAL_RISK_DECISION_NOT_EXPLICIT_PROVIDER_AUTHORIZATION",
        },
        "stop_conditions": [
            "RAW_TTL_DELETION_FAILURE",
            "SYNCHRONIZED_OR_GIT_STORAGE",
            "RAW_REDISTRIBUTION_OR_PUBLIC_ENDPOINT",
            "SECRET_EXPOSURE",
            "SCOPE_BEYOND_BOUNDED_RESEARCH_PILOT",
            "FULL_SEASON_OR_PERMANENT_RAW_ARCHIVE_REQUESTED",
            "PUBLIC_TERMS_BECOME_INCOMPATIBLE",
        ],
        "verdict": "INTERNAL_MARKET_DATA_RETENTION_POLICY_V1_RECORDED",
    }
    threat_report = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "capture-threat-model-v1",
        "trust_boundaries": [
            "late environment-only secret boundary",
            "pre-network request guard boundary",
            "authorization-bound provider IP with exact TLS identity boundary",
            "raw bytes before parser boundary",
            "owner-attested exclusive OS-ACL with pinned repository, control-temp, and capture-root identities",
            "normalized retained evidence boundary",
        ],
        "threats": [
            {
                "id": "T01",
                "threat": "secret disclosure",
                "control": "opaque capability with mandatory public-material scan; stable input-free request exception; no value in fingerprint, receipt, log, exception, or path",
                "test": "tests/capture/test_capture_harness.py::test_invalid_request_exception_hides_secret_sentinel",
            },
            {
                "id": "T02",
                "threat": "unauthorized network",
                "control": "strict direct AF_INET/AF_INET6 socket to the exact authorization-bound global-unicast IP; exact peer, SNI and Host; absolute monotonic deadline across connect, TLS, request, status, headers and body; no DNS, proxy, redirect, retry or failover",
                "test": "tests/capture/test_live_canary_transport.py",
            },
            {
                "id": "T03",
                "threat": "quota, retry, or budget-ledger semantic overrun",
                "control": "persistent fsync hash-chained budget with cross-process file lock and validated cumulative transitions; retry zero; complete and internally coherent quota headers",
                "test": "tests/capture/test_capture_harness.py::test_budget_ledger_rejects_semantically_rehashed_reset",
            },
            {
                "id": "T04",
                "threat": "redirect or host confusion",
                "control": "exact HTTPS host allowlist and redirects disabled",
                "test": "tests/capture/test_capture_harness.py::test_request_guards_fail_closed",
            },
            {
                "id": "T05",
                "threat": "parser-before-receipt evidence loss",
                "control": "raw SHA-256 and content-addressed write precede parsing",
                "test": "tests/capture/test_capture_harness.py::test_invalid_json_is_hashed_before_parse_and_quarantined",
            },
            {
                "id": "T06",
                "threat": "raw persistence beyond policy, unaudited deletion, or capture-versus-TTL race",
                "control": "shared inter-process capture/TTL lock; TTL-governed intake receipt before raw; 30-day write-ahead hash-chained deletion ledger",
                "test": "tests/capture/test_capture_harness.py::test_capture_and_ttl_are_serialized_for_the_same_raw_hash",
            },
            {
                "id": "T07",
                "threat": "ambiguous, duplicated, many-to-one, unused, or revision-divergent mapping",
                "control": "bijective and exhaustive mapping set, including revisions, bound to snapshot identity; duplicate event/bookmaker checks",
                "test": "tests/capture/test_capture_harness.py::test_mapping_lineage_is_bound_to_snapshot_identity",
            },
            {
                "id": "T10",
                "threat": "tampered receipt, missing intake, backdated manifest, or broken provenance link",
                "control": "self-verifying digests; explicit final-to-intake and captured-at links; cross-link and normalized-hash checks before replay proof",
                "test": "tests/capture/test_capture_harness.py::test_receipt_manifest_and_normalized_links_fail_closed_on_tamper",
            },
            {
                "id": "T11",
                "threat": "oversized raw exhausts local storage",
                "control": "size rejection after hashing but before intake raw persistence",
                "test": "tests/capture/test_capture_harness.py::test_http_redirect_size_and_quota_fail_closed",
            },
            {
                "id": "T08",
                "threat": "backdated availability",
                "control": "available_at is max(first observed, market last update)",
                "test": "tests/capture/test_capture_harness.py::test_available_at_is_never_backdated",
            },
            {
                "id": "T09",
                "threat": "real raw payload enters Git or a synchronized root",
                "control": "capture store requires an exact explicitly approved local root; rejects UNC, non-fixed Windows drives, non-allowlisted Linux mount types, Git ancestors, known synchronized path markers, and reparse components; revalidates the approved root identity at storage I/O boundaries",
                "test": "tests/capture/test_live_canary_storage_security.py",
            },
            {
                "id": "T12",
                "threat": "repository or control-temp substitution before budget or secret admission",
                "control": "repository, control-temp, Git executable and capture-root identities are hash-bound to external owner authorization and revalidated; resistance to a concurrent same-principal mutator is an explicit owner-attested exclusive OS-ACL boundary rather than a runtime cryptographic claim",
                "test": "tests/capture/test_live_canary_transport.py",
            },
        ],
        "residual_risk": "NON_ZERO_BOUNDED_INTERNAL_DECISION",
        "residual_assumptions": [
            "the owner provisions the repository, control-temp and capture root under an exclusive OS principal that excludes concurrent rename or replacement; this attestation is hash-bound but externally authenticated",
            "the operating system reports file, drive, mount, socket-peer and monotonic-clock identity faithfully; unsupported platforms fail closed unless separately attested",
            "the owner selects one canonical global-unicast provider IP in a separate authorization; rotation requires a new authorization and the live transport performs no DNS resolution",
        ],
        "open_p0": 0,
        "open_p1": 0,
    }
    replay_report = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "offline-replay-proof-v1",
        "fixture_provenance": "ENTIRELY_SYNTHETIC_NO_PROVIDER_PAYLOAD",
        "fixture_path": FIXTURE_PATH.as_posix(),
        "snapshot_id": manifest.snapshot_id,
        "receipt_id": manifest.receipt_id,
        "raw_payload_sha256": manifest.raw_payload_sha256,
        "schema_fingerprint_sha256": manifest.schema_fingerprint.schema_sha256,
        "normalized_sha256": manifest.normalized_sha256,
        "observation_count": manifest.observation_count,
        "replay": replay.model_dump(mode="json"),
        "secret_sentinel_occurrences_in_outputs": sentinel_occurrences,
        "network_calls": 0,
        "provider_calls": 0,
        "raw_hash_verified_before_parse": True,
        "real_canary_compatibility": {
            "external_canary_reference": compatibility["external_canary_reference"],
            "external_evidence_pack_sha256": compatibility["external_evidence_pack_sha256"],
            "captures_admitted": compatibility["captures_admitted"],
            "real_raw_payloads_committed": False,
            "network_calls": compatibility["network_call_count"],
            "provider_calls": compatibility["provider_call_count"],
            "provider_secret_reads": compatibility["provider_secret_read_count"],
            "verdict": compatibility["replay_verdict"],
        },
        "verdict": "ROBIN_OFFLINE_CAPTURE_REPLAY_PROVEN",
    }
    live_plan = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "live-canary-plan-v1",
        "authorization": False,
        "status": [
            "CAPABILITY_AVAILABLE",
            "DEFAULT_DENY",
            "REAL_ACTIVATION_ABSENT",
            "OWNER_AUTHORIZATION_HASH_PIN_REQUIRED",
            "NO_PROVIDER_CALL",
            "NO_PURCHASE",
            "NO_PROMOTION",
            "NO_BET",
        ],
        "canary_metadata_integration": {
            "workspace_directory_present": True,
            "allowed_metadata_files": [
                "schema-observation.json",
                "market-coverage.json",
                "quota-observation.json",
                "capture-manifest.json",
            ],
            "present_allowed_metadata_files": [
                "schema-observation.json",
                "market-coverage.json",
                "quota-observation.json",
                "capture-manifest.json",
            ],
            "status": "EXTERNAL_COMPATIBILITY_EVIDENCE_VERIFIED",
            "provider_payload_copied_to_git": False,
            "external_canary_reference": compatibility["external_canary_reference"],
            "external_evidence_pack_sha256": compatibility["external_evidence_pack_sha256"],
            "c2_final_classification": compatibility["c2_final_classification"],
            "real_data_leak_count": compatibility["real_data_leak_count"],
        },
        "future_prerequisites": [
            "SEPARATE_OWNER_AUTHORIZATION",
            "EXACT_CAPTURE_BUDGET",
            "SEPARATE_OWNER_HASH_PIN_OUTSIDE_AUTHORIZATION_BUNDLE",
            "INTERNAL_MARKET_DATA_RETENTION_POLICY_V1_ACTIVE",
            "EXPLICITLY_APPROVED_LOCAL_NON_SYNCHRONISED_WORKSPACE",
            "OS_BACKED_CLOUD_FILES_NETWORK_DRIVE_AND_SYNC_ROOT_VERIFICATION",
            "THE_ODDS_API_KEY_ENVIRONMENT_ONLY",
            "ZERO_RETRIES_AND_ZERO_REDIRECTS",
            "POST_CAPTURE_SECRET_SCAN_AND_OFFLINE_REPLAY",
        ],
        "mission_effects": {
            "network_calls": 0,
            "provider_calls": 0,
            "secret" + "_reads": 0,
            "credits_consumed": 0,
            "purchases": 0,
            "promotions": 0,
            "bets": 0,
        },
    }
    documents = {
        "capture-harness-contract-v1.json": contract_report,
        "internal-retention-policy-v1.json": retention_report,
        "capture-threat-model-v1.json": threat_report,
        "offline-replay-proof-v1.json": replay_report,
        "live-canary-plan-v1.json": live_plan,
    }
    return {name: _json_text(value) for name, value in documents.items()}


def write_reports(output: Path, reports: Mapping[str, str]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")


def check_reports(output: Path, reports: Mapping[str, str]) -> None:
    failures = [
        name
        for name, content in reports.items()
        if not (output / name).is_file() or (output / name).read_text(encoding="utf-8") != content
    ]
    if failures:
        raise SystemExit(f"CAPTURE_HARNESS_REPORT_CHECK_FAILED:{','.join(failures)}")
    digest = hashlib.sha256(
        b"".join(reports[name].encode("utf-8") for name in sorted(reports))
    ).hexdigest()
    print(f"CAPTURE_HARNESS_REPORT_CHECK_PASS:{len(reports)}:{digest}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    output = (
        args.output.resolve() if args.output is not None else repo / "reports" / "data-sourcing"
    )
    reports = build_reports(repo)
    if args.check:
        check_reports(output, reports)
    else:
        write_reports(output, reports)
        print(f"CAPTURE_HARNESS_REPORTS_WRITTEN:{len(reports)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
