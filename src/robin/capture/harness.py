"""Fail-closed orchestration for offline validation and future canary captures."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Literal

from pydantic import Field

from robin.capture.contracts import (
    SECRET_ENV_NAME,
    AdmissionStatus,
    CaptureBudget,
    CaptureManifest,
    CaptureMode,
    FixtureMapping,
    FrozenContract,
    JsonValue,
    NormalizedMarketObservation,
    ProviderRequestSpec,
    QuotaObservation,
    RawPayloadReceipt,
    RequestFingerprint,
    SchemaFingerprint,
    canonical_json_bytes,
    ensure_utc,
)
from robin.capture.normalization import (
    CaptureValidationError,
    decode_json_payload,
    normalize_payload,
    normalized_jsonl_bytes,
    schema_fingerprint,
    snapshot_id_for_observation_rows,
)
from robin.capture.storage import CaptureStore

LIVE_CANARY_AUTHORIZED = False
DEFAULT_CAPTURE_MODE = CaptureMode.VALIDATE_OFFLINE


class CaptureGuardError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CaptureRejected(RuntimeError):
    def __init__(self, code: str, *, receipt_id: str, payload_sha256: str) -> None:
        self.code = code
        self.receipt_id = receipt_id
        self.payload_sha256 = payload_sha256
        super().__init__(code)


class SecretCapability(FrozenContract):
    """Proof that a secret exists without retaining its value."""

    source_environment_variable: Literal["THE_ODDS_API_KEY"] = "THE_ODDS_API_KEY"
    present: Literal[True] = True
    exposure_checked: Literal[True] = True
    secret_value_retained: Literal[False] = False

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        public_material: bytes,
    ) -> SecretCapability:
        if not public_material:
            raise CaptureGuardError("CAPTURE_PUBLIC_MATERIAL_REQUIRED")
        secret = environment.get(SECRET_ENV_NAME)
        if secret is None or not secret.strip():
            raise CaptureGuardError("CAPTURE_SECRET_MISSING")
        encoded = secret.encode("utf-8")
        if encoded in public_material:
            raise CaptureGuardError("CAPTURE_SECRET_EXPOSABLE")
        return cls()


class CapturePreparation(FrozenContract):
    mode: Literal["VALIDATE_OFFLINE", "DRY_RUN"]
    fingerprint: RequestFingerprint
    reserved_budget: CaptureBudget
    estimated_requests: int = Field(gt=0)
    estimated_credits: int = Field(ge=0)
    network_calls: Literal[0] = 0
    provider_calls: Literal[0] = 0
    secret_reads: Literal[0] = 0


@dataclass(frozen=True, slots=True)
class _ReceiptMaterial:
    intake_receipt_id: str | None
    request_fingerprint_sha256: str
    payload_sha256: str
    payload_byte_length: int
    http_status: int
    robin_first_observed_at: datetime
    robin_ingested_at: datetime
    raw_storage_key: str | None
    schema_fingerprint_sha256: str | None
    admission_status: AdmissionStatus
    rejection_code: str | None


def _safe_integer_header(headers: Mapping[str, str], name: str) -> int | None:
    normalized = {key.casefold(): value for key, value in headers.items()}
    value = normalized.get(name)
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise CaptureValidationError("CAPTURE_QUOTA_HEADERS_INVALID")
    parsed = int(value)
    if parsed < 0:
        raise CaptureValidationError("CAPTURE_QUOTA_HEADERS_INVALID")
    return parsed


def _quota_observation(
    headers: Mapping[str, str],
    *,
    observed_at: datetime,
    estimated_credits: int,
) -> QuotaObservation:
    quota = QuotaObservation(
        requests_remaining=_safe_integer_header(headers, "x-requests-remaining"),
        requests_used=_safe_integer_header(headers, "x-requests-used"),
        requests_last=_safe_integer_header(headers, "x-requests-last"),
        observed_at=observed_at,
    )
    if None in (
        quota.requests_remaining,
        quota.requests_used,
        quota.requests_last,
    ):
        raise CaptureValidationError("CAPTURE_QUOTA_HEADERS_MISSING")
    if quota.requests_last is not None and quota.requests_last != estimated_credits:
        raise CaptureValidationError("CAPTURE_QUOTA_RECONCILIATION_FAILED")
    if (
        quota.requests_used is not None
        and quota.requests_last is not None
        and quota.requests_used < quota.requests_last
    ):
        raise CaptureValidationError("CAPTURE_QUOTA_RECONCILIATION_FAILED")
    return quota


def _build_receipt(
    material: _ReceiptMaterial,
    *,
    quota: QuotaObservation | None,
) -> RawPayloadReceipt:
    return RawPayloadReceipt.issue(
        intake_receipt_id=material.intake_receipt_id,
        request_fingerprint_sha256=material.request_fingerprint_sha256,
        payload_sha256=material.payload_sha256,
        payload_byte_length=material.payload_byte_length,
        http_status=material.http_status,
        quota=quota,
        robin_first_observed_at=material.robin_first_observed_at,
        robin_ingested_at=material.robin_ingested_at,
        available_at=material.robin_first_observed_at,
        raw_expires_at=material.robin_first_observed_at + timedelta(days=30),
        raw_storage_key=material.raw_storage_key,
        schema_fingerprint_sha256=material.schema_fingerprint_sha256,
        admission_status=material.admission_status,
        rejection_code=material.rejection_code,
    )


class CaptureHarness:
    """Offline capture recorder; it intentionally contains no network transport."""

    def __init__(
        self,
        store: CaptureStore,
        budget: CaptureBudget | None,
        *,
        maximum_payload_bytes: int = 1_048_576,
    ) -> None:
        if budget is None:
            raise CaptureGuardError("CAPTURE_BUDGET_REQUIRED")
        if maximum_payload_bytes <= 0:
            raise CaptureGuardError("CAPTURE_PAYLOAD_LIMIT_INVALID")
        self.store = store
        self._budget = budget
        self._budget_lock = Lock()
        self.maximum_payload_bytes = maximum_payload_bytes

    @property
    def current_budget(self) -> CaptureBudget:
        return self._budget

    def prepare(
        self,
        request: ProviderRequestSpec,
        *,
        mode: CaptureMode | str = DEFAULT_CAPTURE_MODE,
    ) -> CapturePreparation:
        return self._prepare(request, mode=mode, consume_budget=False)

    def _prepare(
        self,
        request: ProviderRequestSpec,
        *,
        mode: CaptureMode | str,
        consume_budget: bool,
    ) -> CapturePreparation:
        try:
            validated_mode = CaptureMode(mode)
        except ValueError:
            raise CaptureGuardError("CAPTURE_MODE_INVALID") from None
        if validated_mode is CaptureMode.LIVE_CANARY:
            # This gate deliberately runs before any environment or secret read.
            raise CaptureGuardError("ROBIN_LIVE_CANARY_DISABLED_NOT_AUTHORIZED")
        estimated_requests = 1
        credits = len(request.markets)
        with self._budget_lock:
            try:
                reserved = self.store.reserve_budget(
                    self._budget,
                    requests=estimated_requests,
                    credits=credits,
                    consume=consume_budget,
                )
            except ValueError as exc:
                raise CaptureGuardError(str(exc)) from None
            if consume_budget:
                self._budget = reserved
        prepared_mode: Literal["VALIDATE_OFFLINE", "DRY_RUN"] = (
            "DRY_RUN"
            if validated_mode is CaptureMode.DRY_RUN
            else "VALIDATE_OFFLINE"
        )
        return CapturePreparation(
            mode=prepared_mode,
            fingerprint=RequestFingerprint.create(request),
            reserved_budget=reserved,
            estimated_requests=estimated_requests,
            estimated_credits=credits,
        )

    def record_offline_response(
        self,
        request: ProviderRequestSpec,
        *,
        payload: bytes,
        http_status: int,
        response_headers: Mapping[str, str],
        mappings: tuple[FixtureMapping, ...],
        first_observed_at: datetime,
        ingested_at: datetime,
    ) -> CaptureManifest:
        with self.store.capture_transaction():
            return self._record_offline_response_locked(
                request,
                payload=payload,
                http_status=http_status,
                response_headers=response_headers,
                mappings=mappings,
                first_observed_at=first_observed_at,
                ingested_at=ingested_at,
            )

    def _record_offline_response_locked(
        self,
        request: ProviderRequestSpec,
        *,
        payload: bytes,
        http_status: int,
        response_headers: Mapping[str, str],
        mappings: tuple[FixtureMapping, ...],
        first_observed_at: datetime,
        ingested_at: datetime,
    ) -> CaptureManifest:
        preparation = self._prepare(
            request,
            mode=CaptureMode.VALIDATE_OFFLINE,
            consume_budget=True,
        )
        observed = ensure_utc(first_observed_at, field="first_observed_at")
        ingested = ensure_utc(ingested_at, field="ingested_at")
        if ingested < observed:
            raise CaptureGuardError("CAPTURE_INGESTED_BEFORE_OBSERVED")
        if not 100 <= http_status <= 599:
            raise CaptureGuardError("CAPTURE_HTTP_STATUS_INVALID")

        # A provisional TTL-governed receipt is durable before raw bytes are written.
        # The raw SHA-256 and content-addressed write still precede all parsing.
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        if len(payload) > self.maximum_payload_bytes:
            oversized_material = _ReceiptMaterial(
                intake_receipt_id=None,
                request_fingerprint_sha256=preparation.fingerprint.request_sha256,
                payload_sha256=payload_sha256,
                payload_byte_length=len(payload),
                http_status=http_status,
                robin_first_observed_at=observed,
                robin_ingested_at=ingested,
                raw_storage_key=None,
                schema_fingerprint_sha256=None,
                admission_status=AdmissionStatus.QUARANTINED,
                rejection_code="CAPTURE_PAYLOAD_TOO_LARGE",
            )
            oversized_receipt = _build_receipt(oversized_material, quota=None)
            self.store.store_receipt(oversized_receipt)
            self.store.store_quarantine(oversized_receipt)
            raise CaptureRejected(
                "CAPTURE_PAYLOAD_TOO_LARGE",
                receipt_id=oversized_receipt.receipt_id,
                payload_sha256=payload_sha256,
            )
        expected_raw_key = (
            f"raw/sha256/{payload_sha256[:2]}/{payload_sha256}.bin"
        )
        intake_material = _ReceiptMaterial(
            intake_receipt_id=None,
            request_fingerprint_sha256=preparation.fingerprint.request_sha256,
            payload_sha256=payload_sha256,
            payload_byte_length=len(payload),
            http_status=http_status,
            robin_first_observed_at=observed,
            robin_ingested_at=ingested,
            raw_storage_key=expected_raw_key,
            schema_fingerprint_sha256=None,
            admission_status=AdmissionStatus.INTAKE_PENDING,
            rejection_code=None,
        )
        intake_receipt = _build_receipt(intake_material, quota=None)
        self.store.store_receipt(intake_receipt)
        stored_sha256, raw_storage_key = self.store.store_raw(payload)
        if stored_sha256 != payload_sha256 or raw_storage_key != expected_raw_key:
            raise CaptureGuardError("CAPTURE_RAW_HASH_MISMATCH")

        rejection_code: str | None = None
        decoded: JsonValue | None = None
        schema: SchemaFingerprint | None = None
        quota: QuotaObservation | None = None
        normalized: tuple[NormalizedMarketObservation, ...] = ()
        lowered_headers = {key.casefold(): value for key, value in response_headers.items()}

        if 300 <= http_status <= 399 or "location" in lowered_headers:
            rejection_code = "CAPTURE_REDIRECT_FORBIDDEN"
        elif http_status != 200:
            rejection_code = "CAPTURE_HTTP_STATUS_REJECTED"
        else:
            try:
                quota = _quota_observation(
                    response_headers,
                    observed_at=ingested,
                    estimated_credits=preparation.estimated_credits,
                )
                decoded = decode_json_payload(payload)
                schema = schema_fingerprint(decoded)
            except CaptureValidationError as exc:
                rejection_code = exc.code

        admitted_material = _ReceiptMaterial(
            intake_receipt_id=intake_receipt.receipt_id,
            request_fingerprint_sha256=preparation.fingerprint.request_sha256,
            payload_sha256=payload_sha256,
            payload_byte_length=len(payload),
            http_status=http_status,
            robin_first_observed_at=observed,
            robin_ingested_at=ingested,
            raw_storage_key=raw_storage_key,
            schema_fingerprint_sha256=(schema.schema_sha256 if schema is not None else None),
            admission_status=AdmissionStatus.ADMITTED,
            rejection_code=None,
        )
        admitted_receipt = _build_receipt(admitted_material, quota=quota)

        if rejection_code is None and decoded is not None:
            try:
                schema, normalized = normalize_payload(
                    decoded,
                    receipt=admitted_receipt,
                    mappings=mappings,
                )
            except CaptureValidationError as exc:
                rejection_code = exc.code

        if rejection_code is not None:
            rejected_material = _ReceiptMaterial(
                intake_receipt_id=intake_receipt.receipt_id,
                request_fingerprint_sha256=preparation.fingerprint.request_sha256,
                payload_sha256=payload_sha256,
                payload_byte_length=len(payload),
                http_status=http_status,
                robin_first_observed_at=observed,
                robin_ingested_at=ingested,
                raw_storage_key=raw_storage_key,
                schema_fingerprint_sha256=(schema.schema_sha256 if schema is not None else None),
                admission_status=AdmissionStatus.QUARANTINED,
                rejection_code=rejection_code,
            )
            rejected_receipt = _build_receipt(rejected_material, quota=quota)
            self.store.store_receipt(rejected_receipt)
            self.store.store_quarantine(rejected_receipt)
            raise CaptureRejected(
                rejection_code,
                receipt_id=rejected_receipt.receipt_id,
                payload_sha256=payload_sha256,
            )

        if schema is None:
            raise CaptureGuardError("CAPTURE_SCHEMA_FINGERPRINT_MISSING")
        normalized_bytes = normalized_jsonl_bytes(normalized)
        normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
        snapshot_id = (
            normalized[0].snapshot_id
            if normalized
            else snapshot_id_for_observation_rows(
                receipt_id=admitted_receipt.receipt_id,
                schema_fingerprint_sha256=schema.schema_sha256,
                mappings=mappings,
                observations=(),
            )
        )
        normalized_key = self.store.store_normalized(
            snapshot_id=snapshot_id,
            payload=normalized_bytes,
        )
        manifest = CaptureManifest.issue(
            snapshot_id=snapshot_id,
            receipt_id=admitted_receipt.receipt_id,
            request_fingerprint_sha256=preparation.fingerprint.request_sha256,
            raw_payload_sha256=payload_sha256,
            schema_fingerprint=schema,
            fixture_mappings=mappings,
            observation_count=len(normalized),
            normalized_sha256=normalized_sha256,
            normalized_storage_key=normalized_key,
            captured_at=ingested,
        )
        self.store.store_receipt(admitted_receipt)
        self.store.store_manifest(manifest)
        return manifest

    @staticmethod
    def public_preparation_bytes(preparation: CapturePreparation) -> bytes:
        return canonical_json_bytes(preparation.model_dump(mode="json"))
