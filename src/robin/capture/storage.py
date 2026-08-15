"""Content-addressed local storage with immutable metadata and raw TTL deletion."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast
from uuid import uuid4

from robin.capture.contracts import (
    AdmissionStatus,
    CaptureBudget,
    CaptureManifest,
    InternalRetentionPolicy,
    NormalizedMarketObservation,
    OfflineReplayResult,
    RawPayloadReceipt,
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
)
from robin.capture.normalization import (
    normalize_payload,
    normalized_jsonl_bytes,
    snapshot_id_for_observation_rows,
)

_SYNCHRONIZED_PATH_MARKERS = frozenset(
    {"onedrive", "dropbox", "google drive", "googledrive", "icloud", "icloud drive"}
)


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
            os.fsync(stream.fileno())
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            getattr(msvcrt, "locking")(stream.fileno(), getattr(msvcrt, "LK_LOCK"), 1)
        else:
            import fcntl

            getattr(fcntl, "flock")(stream.fileno(), getattr(fcntl, "LOCK_EX"))
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                getattr(msvcrt, "locking")(
                    stream.fileno(), getattr(msvcrt, "LK_UNLCK"), 1
                )
            else:
                import fcntl

                getattr(fcntl, "flock")(stream.fileno(), getattr(fcntl, "LOCK_UN"))


class CaptureStorageError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_inside_git(path: Path) -> bool:
    candidate = path.resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / ".git").exists():
            return True
    return False


def _is_synchronized(path: Path) -> bool:
    for part in path.resolve().parts:
        normalized = part.casefold()
        if any(
            normalized == marker
            or normalized.startswith(f"{marker} ")
            or normalized.startswith(f"{marker}-")
            for marker in _SYNCHRONIZED_PATH_MARKERS
        ):
            return True
    return False


def validate_capture_workspace(path: Path) -> Path:
    resolved = path.resolve()
    if _is_inside_git(resolved):
        raise CaptureStorageError("CAPTURE_WORKSPACE_IN_GIT")
    if _is_synchronized(resolved):
        raise CaptureStorageError("CAPTURE_WORKSPACE_SYNCHRONIZED")
    return resolved


class CaptureStore:
    """A local, content-addressed capture store that never accepts a Git path."""

    def __init__(
        self,
        root: Path,
        retention_policy: InternalRetentionPolicy | None,
        *,
        approved_local_root: Path | None,
    ) -> None:
        if retention_policy is None:
            raise CaptureStorageError("CAPTURE_RETENTION_POLICY_REQUIRED")
        if approved_local_root is None:
            raise CaptureStorageError("CAPTURE_LOCAL_ROOT_APPROVAL_REQUIRED")
        if root.resolve() != approved_local_root.resolve():
            raise CaptureStorageError("CAPTURE_LOCAL_ROOT_APPROVAL_MISMATCH")
        self.policy = retention_policy
        self.root = validate_capture_workspace(root)
        for relative in (
            "raw/sha256",
            "receipts",
            "normalized",
            "manifests",
            "quarantine",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.deletion_ledger = self.root / "deletion-ledger.jsonl"
        self.budget_ledger = self.root / "budget-ledger.jsonl"
        self._budget_lock_path = self.root / ".budget-ledger.lock"
        self._ttl_lock_path = self.root / ".ttl-enforcement.lock"
        self._deletion_ledger_lock_path = self.root / ".deletion-ledger.lock"
        self._deletion_ledger_lock = Lock()

    @contextmanager
    def capture_transaction(self) -> Iterator[None]:
        """Serialize receipt/raw finalization with TTL scans across processes."""
        with _exclusive_file_lock(self._ttl_lock_path):
            yield

    def reserve_budget(
        self,
        budget: CaptureBudget,
        *,
        requests: int,
        credits: int,
        consume: bool,
    ) -> CaptureBudget:
        with _exclusive_file_lock(self._budget_lock_path):
            current = budget
            previous_entry_sha256: str | None = None
            previous_used_requests = 0
            previous_used_credits = 0
            if self.budget_ledger.exists():
                try:
                    entries = [
                        cast(dict[str, Any], json.loads(line))
                        for line in self.budget_ledger.read_bytes().splitlines()
                    ]
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_INVALID") from None
                for entry in entries:
                    if set(entry) != {
                        "action",
                        "entry_sha256",
                        "maximum_credits",
                        "maximum_requests",
                        "previous_entry_sha256",
                        "prior_used_credits",
                        "prior_used_requests",
                        "reserved_credits",
                        "reserved_requests",
                        "used_credits",
                        "used_requests",
                    }:
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_INVALID")
                    entry_sha256 = entry.get("entry_sha256")
                    if not isinstance(entry_sha256, str):
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_INVALID")
                    identity = {
                        key: value
                        for key, value in entry.items()
                        if key != "entry_sha256"
                    }
                    if canonical_sha256(identity) != entry_sha256:
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_HASH_MISMATCH")
                    if entry.get("previous_entry_sha256") != previous_entry_sha256:
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_CHAIN_MISMATCH")
                    if entry.get("action") != "CAPTURE_BUDGET_RESERVATION":
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_INVALID")
                    if (
                        entry.get("maximum_requests") != budget.maximum_requests
                        or entry.get("maximum_credits") != budget.maximum_credits
                    ):
                        raise CaptureStorageError(
                            "CAPTURE_BUDGET_CONFIGURATION_MISMATCH"
                        )
                    used_requests = entry.get("used_requests")
                    used_credits = entry.get("used_credits")
                    prior_used_requests = entry.get("prior_used_requests")
                    prior_used_credits = entry.get("prior_used_credits")
                    reserved_requests = entry.get("reserved_requests")
                    reserved_credits = entry.get("reserved_credits")
                    integer_fields = (
                        used_requests,
                        used_credits,
                        prior_used_requests,
                        prior_used_credits,
                        reserved_requests,
                        reserved_credits,
                    )
                    if any(
                        isinstance(value, bool) or not isinstance(value, int)
                        for value in integer_fields
                    ):
                        raise CaptureStorageError("CAPTURE_BUDGET_LEDGER_INVALID")
                    validated_used_requests = cast(int, used_requests)
                    validated_used_credits = cast(int, used_credits)
                    validated_prior_requests = cast(int, prior_used_requests)
                    validated_prior_credits = cast(int, prior_used_credits)
                    validated_reserved_requests = cast(int, reserved_requests)
                    validated_reserved_credits = cast(int, reserved_credits)
                    if (
                        validated_prior_requests != previous_used_requests
                        or validated_prior_credits != previous_used_credits
                        or validated_reserved_requests <= 0
                        or validated_reserved_credits < 0
                        or validated_used_requests
                        != validated_prior_requests + validated_reserved_requests
                        or validated_used_credits
                        != validated_prior_credits + validated_reserved_credits
                    ):
                        raise CaptureStorageError(
                            "CAPTURE_BUDGET_LEDGER_TRANSITION_INVALID"
                        )
                    current = CaptureBudget(
                        maximum_requests=budget.maximum_requests,
                        maximum_credits=budget.maximum_credits,
                        used_requests=validated_used_requests,
                        used_credits=validated_used_credits,
                    )
                    previous_entry_sha256 = entry_sha256
                    previous_used_requests = validated_used_requests
                    previous_used_credits = validated_used_credits
            reserved = current.reserve(requests=requests, credits=credits)
            if not consume:
                return reserved
            if previous_entry_sha256 is None and (
                current.used_requests != 0 or current.used_credits != 0
            ):
                raise CaptureStorageError(
                    "CAPTURE_BUDGET_INITIAL_USAGE_MUST_BE_ZERO"
                )
            identity = {
                "action": "CAPTURE_BUDGET_RESERVATION",
                "maximum_credits": reserved.maximum_credits,
                "maximum_requests": reserved.maximum_requests,
                "previous_entry_sha256": previous_entry_sha256,
                "prior_used_credits": current.used_credits,
                "prior_used_requests": current.used_requests,
                "reserved_credits": credits,
                "reserved_requests": requests,
                "used_credits": reserved.used_credits,
                "used_requests": reserved.used_requests,
            }
            entry = {
                "entry_sha256": canonical_sha256(identity),
                **identity,
            }
            with self.budget_ledger.open("ab") as stream:
                stream.write(canonical_json_bytes(entry) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            return reserved

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise CaptureStorageError("CAPTURE_STORAGE_KEY_INVALID")
        return candidate

    def _write_immutable(self, key: str, payload: bytes) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != payload:
                raise CaptureStorageError("CAPTURE_STORAGE_COLLISION")
            return
        temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != payload:
                    raise CaptureStorageError("CAPTURE_STORAGE_COLLISION") from None
        finally:
            temporary.unlink(missing_ok=True)

    def store_raw(self, payload: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(payload).hexdigest()
        key = f"raw/sha256/{digest[:2]}/{digest}.bin"
        self._write_immutable(key, payload)
        return digest, key

    def store_receipt(self, receipt: RawPayloadReceipt) -> str:
        key = f"receipts/{receipt.receipt_id}.json"
        payload = canonical_json_bytes(receipt.model_dump(mode="json")) + b"\n"
        self._write_immutable(key, payload)
        return key

    def store_quarantine(self, receipt: RawPayloadReceipt) -> str:
        if receipt.rejection_code is None:
            raise CaptureStorageError("CAPTURE_QUARANTINE_REASON_REQUIRED")
        record = {
            "receipt_id": receipt.receipt_id,
            "payload_sha256": receipt.payload_sha256,
            "payload_byte_length": receipt.payload_byte_length,
            "reason": receipt.rejection_code,
            "raw_storage_key": receipt.raw_storage_key,
        }
        key = f"quarantine/{receipt.receipt_id}.json"
        self._write_immutable(key, canonical_json_bytes(record) + b"\n")
        return key

    def store_normalized(
        self,
        *,
        snapshot_id: str,
        payload: bytes,
    ) -> str:
        key = f"normalized/{snapshot_id}.jsonl"
        self._write_immutable(key, payload)
        return key

    def store_manifest(self, manifest: CaptureManifest) -> str:
        key = f"manifests/{manifest.snapshot_id}.json"
        payload = canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
        self._write_immutable(key, payload)
        return key

    def load_receipt(self, receipt_id: str) -> RawPayloadReceipt:
        path = self._path(f"receipts/{receipt_id}.json")
        receipt = RawPayloadReceipt.model_validate_json(path.read_bytes())
        if receipt.receipt_id != receipt_id:
            raise CaptureStorageError("CAPTURE_RECEIPT_PATH_IDENTITY_MISMATCH")
        if receipt.intake_receipt_id is not None:
            intake_path = self._path(f"receipts/{receipt.intake_receipt_id}.json")
            try:
                intake = RawPayloadReceipt.model_validate_json(intake_path.read_bytes())
            except FileNotFoundError:
                raise CaptureStorageError("CAPTURE_INTAKE_RECEIPT_MISSING") from None
            if (
                intake.receipt_id != receipt.intake_receipt_id
                or intake.admission_status is not AdmissionStatus.INTAKE_PENDING
                or intake.intake_receipt_id is not None
                or intake.request_fingerprint_sha256
                != receipt.request_fingerprint_sha256
                or intake.payload_sha256 != receipt.payload_sha256
                or intake.payload_byte_length != receipt.payload_byte_length
                or intake.http_status != receipt.http_status
                or intake.robin_first_observed_at != receipt.robin_first_observed_at
                or intake.robin_ingested_at != receipt.robin_ingested_at
                or intake.raw_expires_at != receipt.raw_expires_at
                or intake.raw_storage_key != receipt.raw_storage_key
            ):
                raise CaptureStorageError("CAPTURE_INTAKE_RECEIPT_LINK_MISMATCH")
        return receipt

    def load_manifest(self, snapshot_id: str) -> CaptureManifest:
        path = self._path(f"manifests/{snapshot_id}.json")
        manifest = CaptureManifest.model_validate_json(path.read_bytes())
        if manifest.snapshot_id != snapshot_id:
            raise CaptureStorageError("CAPTURE_MANIFEST_PATH_IDENTITY_MISMATCH")
        receipt = self.load_receipt(manifest.receipt_id)
        if (
            receipt.request_fingerprint_sha256
            != manifest.request_fingerprint_sha256
            or receipt.payload_sha256 != manifest.raw_payload_sha256
            or receipt.schema_fingerprint_sha256
            != manifest.schema_fingerprint.schema_sha256
            or manifest.captured_at != receipt.robin_ingested_at
        ):
            raise CaptureStorageError("CAPTURE_MANIFEST_RECEIPT_LINK_MISMATCH")
        normalized = self._path(manifest.normalized_storage_key).read_bytes()
        if hashlib.sha256(normalized).hexdigest() != manifest.normalized_sha256:
            raise CaptureStorageError("CAPTURE_NORMALIZED_HASH_MISMATCH")
        try:
            observations = tuple(
                NormalizedMarketObservation.model_validate_json(line)
                for line in normalized.splitlines()
                if line
            )
        except (ValueError, TypeError):
            raise CaptureStorageError("CAPTURE_NORMALIZED_RECORD_INVALID") from None
        if len(observations) != manifest.observation_count:
            raise CaptureStorageError("CAPTURE_OBSERVATION_COUNT_MISMATCH")
        if any(
            observation.snapshot_id != manifest.snapshot_id
            or observation.receipt_id != receipt.receipt_id
            or observation.payload_sha256 != receipt.payload_sha256
            for observation in observations
        ):
            raise CaptureStorageError("CAPTURE_NORMALIZED_PROVENANCE_LINK_MISMATCH")
        return manifest

    def load_raw(self, receipt: RawPayloadReceipt) -> bytes:
        if receipt.raw_storage_key is None:
            raise CaptureStorageError("CAPTURE_RAW_PAYLOAD_NOT_RETAINED")
        try:
            payload = self._path(receipt.raw_storage_key).read_bytes()
        except FileNotFoundError:
            raise CaptureStorageError("CAPTURE_RAW_PAYLOAD_NOT_RETAINED") from None
        if hashlib.sha256(payload).hexdigest() != receipt.payload_sha256:
            raise CaptureStorageError("CAPTURE_RAW_HASH_MISMATCH")
        return payload

    def replay(self, snapshot_id: str) -> OfflineReplayResult:
        manifest = self.load_manifest(snapshot_id)
        receipt = self.load_receipt(manifest.receipt_id)
        raw = self.load_raw(receipt)
        # load_raw verifies the raw SHA-256 before JSON decoding or normalization.
        from robin.capture.normalization import decode_json_payload

        decoded = decode_json_payload(raw)
        schema, observations = normalize_payload(
            decoded,
            receipt=receipt,
            mappings=manifest.fixture_mappings,
        )
        replayed = normalized_jsonl_bytes(observations)
        expected = self._path(manifest.normalized_storage_key).read_bytes()
        replayed_sha256 = hashlib.sha256(replayed).hexdigest()
        byte_identical = replayed == expected
        replayed_snapshot_id = (
            observations[0].snapshot_id
            if observations
            else snapshot_id_for_observation_rows(
                receipt_id=receipt.receipt_id,
                schema_fingerprint_sha256=schema.schema_sha256,
                mappings=manifest.fixture_mappings,
                observations=(),
            )
        )
        deterministic = (
            byte_identical
            and replayed_snapshot_id == manifest.snapshot_id
            and replayed_sha256 == manifest.normalized_sha256
            and schema.schema_sha256 == manifest.schema_fingerprint.schema_sha256
            and len(observations) == manifest.observation_count
            and receipt.request_fingerprint_sha256
            == manifest.request_fingerprint_sha256
            and receipt.payload_sha256 == manifest.raw_payload_sha256
        )
        if not deterministic:
            raise CaptureStorageError("CAPTURE_REPLAY_NOT_DETERMINISTIC")
        return OfflineReplayResult(
            snapshot_id=manifest.snapshot_id,
            receipt_id=receipt.receipt_id,
            raw_payload_sha256=receipt.payload_sha256,
            normalized_sha256=replayed_sha256,
            observation_count=len(observations),
            byte_identical=True,
            deterministic=True,
        )

    def _append_deletion_record(self, record: dict[str, object]) -> None:
        record_id = canonical_sha256(record)
        with self._deletion_ledger_lock, _exclusive_file_lock(
            self._deletion_ledger_lock_path
        ):
            previous_entry_sha256: str | None = None
            if self.deletion_ledger.exists():
                for existing in self.deletion_ledger.read_bytes().splitlines():
                    parsed = cast(dict[str, Any], json.loads(existing))
                    entry_sha256 = parsed.get("entry_sha256")
                    if not isinstance(entry_sha256, str):
                        raise CaptureStorageError("CAPTURE_DELETION_LEDGER_INVALID")
                    identity = {
                        key: value
                        for key, value in parsed.items()
                        if key != "entry_sha256"
                    }
                    if canonical_sha256(identity) != entry_sha256:
                        raise CaptureStorageError("CAPTURE_DELETION_LEDGER_HASH_MISMATCH")
                    if parsed.get("previous_entry_sha256") != previous_entry_sha256:
                        raise CaptureStorageError("CAPTURE_DELETION_LEDGER_CHAIN_MISMATCH")
                    if parsed.get("record_id") == record_id:
                        if any(parsed.get(key) != value for key, value in record.items()):
                            raise CaptureStorageError("CAPTURE_DELETION_LEDGER_COLLISION")
                        return
                    previous_entry_sha256 = entry_sha256
            identity = {
                "record_id": record_id,
                "previous_entry_sha256": previous_entry_sha256,
                **record,
            }
            material = {
                "entry_sha256": canonical_sha256(identity),
                **identity,
            }
            line = canonical_json_bytes(material) + b"\n"
            with self.deletion_ledger.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())

    def enforce_raw_ttl(self, *, now: datetime) -> tuple[str, ...]:
        with _exclusive_file_lock(self._ttl_lock_path):
            return self._enforce_raw_ttl(now=now)

    def _enforce_raw_ttl(self, *, now: datetime) -> tuple[str, ...]:
        checked_at = ensure_utc(now, field="ttl_checked_at")
        receipts = [
            RawPayloadReceipt.model_validate_json(path.read_bytes())
            for path in sorted((self.root / "receipts").glob("*.json"))
        ]
        active_hashes = {
            receipt.payload_sha256
            for receipt in receipts
            if receipt.raw_storage_key is not None and receipt.raw_expires_at > checked_at
        }
        deleted: list[str] = []
        for receipt in receipts:
            if (
                receipt.raw_storage_key is None
                or receipt.raw_expires_at > checked_at
                or receipt.payload_sha256 in active_hashes
            ):
                continue
            raw_path = self._path(receipt.raw_storage_key)
            if not raw_path.exists():
                self._append_deletion_record(
                    {
                        "action": "RAW_TTL_ABSENCE_CONFIRMED",
                        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
                        "payload_sha256": receipt.payload_sha256,
                        "raw_storage_key": receipt.raw_storage_key,
                        "retained_receipt_id": receipt.receipt_id,
                    }
                )
                continue
            if hashlib.sha256(raw_path.read_bytes()).hexdigest() != receipt.payload_sha256:
                raise CaptureStorageError("CAPTURE_RAW_HASH_MISMATCH")
            self._append_deletion_record(
                {
                    "action": "RAW_TTL_DELETION_INTENT",
                    "planned_at": checked_at.isoformat().replace("+00:00", "Z"),
                    "payload_sha256": receipt.payload_sha256,
                    "raw_storage_key": receipt.raw_storage_key,
                    "retained_receipt_id": receipt.receipt_id,
                }
            )
            raw_path.unlink()
            self._append_deletion_record(
                {
                    "action": "RAW_TTL_DELETION_COMMITTED",
                    "deleted_at": checked_at.isoformat().replace("+00:00", "Z"),
                    "payload_sha256": receipt.payload_sha256,
                    "raw_storage_key": receipt.raw_storage_key,
                    "retained_receipt_id": receipt.receipt_id,
                }
            )
            deleted.append(receipt.payload_sha256)
        return tuple(sorted(set(deleted)))
