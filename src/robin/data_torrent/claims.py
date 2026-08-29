"""PostgreSQL-backed cross-run claims and terminal torrent batch receipts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from robin.prospective_observatory.chronos_control_plane import (
    GitHubRunIdentity,
    PostgresFunctionClient,
)


def _required_text(value: str, *, field: str, maximum: int) -> str:
    if not value or value.strip() != value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"DATA_TORRENT_{field.upper()}_INVALID")
    return value


def _required_hash(value: str, *, field: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"DATA_TORRENT_{field.upper()}_INVALID") from None
    return value


def _framed_sha256(*parts: object) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
    return digest.hexdigest()


def derive_opportunity_id(*, opportunity_kind: str, canonical_key: str) -> str:
    """Derive the logical identity without any execution/run identity."""

    _required_text(opportunity_kind, field="opportunity_kind", maximum=96)
    _required_text(canonical_key, field="canonical_key", maximum=1024)
    return _framed_sha256(
        "data-torrent-opportunity-v1",
        opportunity_kind,
        canonical_key,
    )


@dataclass(frozen=True, slots=True)
class DataTorrentOpportunity:
    opportunity_kind: str
    canonical_key: str

    def __post_init__(self) -> None:
        _required_text(self.opportunity_kind, field="opportunity_kind", maximum=96)
        _required_text(self.canonical_key, field="canonical_key", maximum=1024)

    @property
    def opportunity_id(self) -> str:
        return derive_opportunity_id(
            opportunity_kind=self.opportunity_kind,
            canonical_key=self.canonical_key,
        )


@dataclass(frozen=True, slots=True)
class OpportunityClaimReceipt:
    opportunity_id: str
    acquired_now: bool
    winner_authority_id: str
    winner_github_run_id: int
    winner_github_run_attempt: int
    db_claimed_at: datetime
    postgres_server_epoch: datetime
    claim_receipt_hash: str

    def __post_init__(self) -> None:
        _required_hash(self.opportunity_id, field="opportunity_id")
        _required_text(self.winner_authority_id, field="authority_id", maximum=96)
        if self.winner_github_run_id <= 0 or self.winner_github_run_attempt <= 0:
            raise ValueError("DATA_TORRENT_WINNER_RUN_IDENTITY_INVALID")
        if (
            self.db_claimed_at.tzinfo is None
            or self.db_claimed_at.utcoffset() is None
            or self.postgres_server_epoch.tzinfo is None
            or self.postgres_server_epoch.utcoffset() is None
        ):
            raise ValueError("DATA_TORRENT_CLAIM_TIME_INVALID")
        _required_hash(self.claim_receipt_hash, field="claim_receipt_hash")


@dataclass(frozen=True, slots=True)
class TorrentBatchReceipt:
    opportunity_id: str
    created_now: bool
    db_recorded_at: datetime
    postgres_server_epoch: datetime
    record_hash: str

    def __post_init__(self) -> None:
        _required_hash(self.opportunity_id, field="opportunity_id")
        _required_hash(self.record_hash, field="record_hash")
        if (
            self.db_recorded_at.tzinfo is None
            or self.db_recorded_at.utcoffset() is None
            or self.postgres_server_epoch.tzinfo is None
            or self.postgres_server_epoch.utcoffset() is None
        ):
            raise ValueError("DATA_TORRENT_BATCH_TIME_INVALID")


@dataclass(frozen=True, slots=True)
class ExternalEffectPermitReceipt:
    operation_id: str
    effect_family: Literal["OFFICIAL", "ODDS"]
    effect_sequence: int
    request_hash: str
    max_official_reads: int
    max_odds_requests: int
    max_odds_credits: int
    created_now: bool
    db_permitted_at: datetime
    postgres_server_epoch: datetime
    permit_hash: str

    def __post_init__(self) -> None:
        _required_hash(self.operation_id, field="operation_id")
        _required_hash(self.request_hash, field="request_hash")
        _required_hash(self.permit_hash, field="permit_hash")
        if (
            self.effect_family not in {"OFFICIAL", "ODDS"}
            or type(self.effect_sequence) is not int
            or self.effect_sequence <= 0
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.max_official_reads,
                    self.max_odds_requests,
                    self.max_odds_credits,
                )
            )
            or (
                self.effect_family == "OFFICIAL"
                and (
                    self.max_official_reads <= 0
                    or self.max_odds_requests != 0
                    or self.max_odds_credits != 0
                )
            )
            or (
                self.effect_family == "ODDS"
                and (
                    self.max_official_reads != 0
                    or self.max_odds_requests != 1
                    or self.max_odds_credits <= 0
                )
            )
            or self.db_permitted_at.tzinfo is None
            or self.db_permitted_at.utcoffset() is None
            or self.postgres_server_epoch.tzinfo is None
            or self.postgres_server_epoch.utcoffset() is None
        ):
            raise ValueError("DATA_TORRENT_EXTERNAL_EFFECT_TIME_INVALID")


@dataclass(frozen=True, slots=True)
class ExternalEffectEventReceipt:
    operation_id: str
    event_seq: int
    event_type: str
    actual_official_reads: int
    actual_odds_requests: int
    actual_odds_credits: int
    db_recorded_at: datetime
    postgres_server_epoch: datetime
    previous_event_hash: str
    event_hash: str

    def __post_init__(self) -> None:
        _required_hash(self.operation_id, field="operation_id")
        _required_hash(self.previous_event_hash, field="previous_event_hash")
        _required_hash(self.event_hash, field="event_hash")
        if (
            self.event_seq not in {1, 2}
            or min(
                self.actual_official_reads,
                self.actual_odds_requests,
                self.actual_odds_credits,
            )
            < 0
        ):
            raise ValueError("DATA_TORRENT_EXTERNAL_EFFECT_EVENT_INVALID")
        if (
            self.db_recorded_at.tzinfo is None
            or self.db_recorded_at.utcoffset() is None
            or self.postgres_server_epoch.tzinfo is None
            or self.postgres_server_epoch.utcoffset() is None
        ):
            raise ValueError("DATA_TORRENT_EXTERNAL_EFFECT_TIME_INVALID")


class PostgresExternalEffectLedger:
    """Durably permit and reconcile official/provider effects."""

    def __init__(self, client: PostgresFunctionClient) -> None:
        self._client = client

    @staticmethod
    def _event(row: dict[str, object] | Any) -> ExternalEffectEventReceipt:
        return ExternalEffectEventReceipt(
            operation_id=cast(str, row["operation_id"]),
            event_seq=cast(int, row["event_seq"]),
            event_type=cast(str, row["event_type"]),
            actual_official_reads=cast(int, row["actual_official_reads"]),
            actual_odds_requests=cast(int, row["actual_odds_requests"]),
            actual_odds_credits=cast(int, row["actual_odds_credits"]),
            db_recorded_at=cast(datetime, row["db_recorded_at"]),
            postgres_server_epoch=cast(datetime, row["postgres_server_epoch"]),
            previous_event_hash=cast(str, row["previous_event_hash"]),
            event_hash=cast(str, row["event_hash"]),
        )

    def reserve(
        self,
        *,
        opportunity_id: str,
        effect_family: Literal["OFFICIAL", "ODDS"],
        effect_sequence: int,
        request_hash: str,
        max_official_reads: int,
        max_odds_requests: int,
        max_odds_credits: int,
        identity: GitHubRunIdentity,
        generation_token: str,
    ) -> ExternalEffectPermitReceipt:
        _required_hash(opportunity_id, field="opportunity_id")
        _required_hash(request_hash, field="request_hash")
        _required_hash(generation_token, field="generation_token")
        row = self._client.fetch_one(
            "SELECT * FROM public.chronos_reserve_torrent_external_effect("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                opportunity_id,
                effect_family,
                effect_sequence,
                request_hash,
                max_official_reads,
                max_odds_requests,
                max_odds_credits,
                identity.github_run_id,
                identity.github_run_attempt,
                identity.github_sha,
                bytes.fromhex(generation_token),
            ),
        )
        return ExternalEffectPermitReceipt(
            operation_id=cast(str, row["operation_id"]),
            effect_family=effect_family,
            effect_sequence=effect_sequence,
            request_hash=request_hash,
            max_official_reads=max_official_reads,
            max_odds_requests=max_odds_requests,
            max_odds_credits=max_odds_credits,
            created_now=cast(bool, row["created_now"]),
            db_permitted_at=cast(datetime, row["db_permitted_at"]),
            postgres_server_epoch=cast(datetime, row["postgres_server_epoch"]),
            permit_hash=cast(str, row["permit_hash"]),
        )

    def append(
        self,
        *,
        operation_id: str,
        event_type: Literal[
            "DISPATCHED",
            "CONFIRMED",
            "FAILED_BEFORE_DISPATCH",
            "FAILED_AFTER_DISPATCH",
            "AMBIGUOUS",
        ],
        actual_official_reads: int,
        actual_odds_requests: int,
        actual_odds_credits: int,
        identity: GitHubRunIdentity,
        generation_token: str,
    ) -> ExternalEffectEventReceipt:
        _required_hash(operation_id, field="operation_id")
        _required_hash(generation_token, field="generation_token")
        row = self._client.fetch_one(
            "SELECT * FROM public.chronos_append_torrent_external_effect("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                operation_id,
                event_type,
                actual_official_reads,
                actual_odds_requests,
                actual_odds_credits,
                identity.github_run_id,
                identity.github_run_attempt,
                identity.github_sha,
                bytes.fromhex(generation_token),
            ),
        )
        return self._event(row)


class PostgresOpportunityClaimer:
    """Acquire one logical opportunity before any official/provider read."""

    def __init__(self, client: PostgresFunctionClient) -> None:
        self._client = client

    def claim(
        self,
        *,
        authority_id: str,
        mission_id: str,
        identity: GitHubRunIdentity,
        generation_token: str,
        opportunity: DataTorrentOpportunity,
        code_revision: str,
    ) -> OpportunityClaimReceipt:
        _required_hash(generation_token, field="generation_token")
        if code_revision != identity.github_sha:
            raise ValueError("DATA_TORRENT_CODE_REVISION_MISMATCH")
        row = self._client.fetch_one(
            "SELECT * FROM public.chronos_claim_opportunity("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                authority_id,
                mission_id,
                identity.github_run_id,
                identity.github_run_attempt,
                identity.github_sha,
                identity.github_workflow_ref,
                identity.github_workflow_sha,
                identity.github_repository,
                identity.github_ref,
                bytes.fromhex(generation_token),
                opportunity.opportunity_id,
                opportunity.opportunity_kind,
                opportunity.canonical_key,
                code_revision,
            ),
        )
        return OpportunityClaimReceipt(
            opportunity_id=cast(str, row["opportunity_id"]),
            acquired_now=cast(bool, row["acquired_now"]),
            winner_authority_id=cast(str, row["winner_authority_id"]),
            winner_github_run_id=cast(int, row["winner_github_run_id"]),
            winner_github_run_attempt=cast(int, row["winner_github_run_attempt"]),
            db_claimed_at=cast(datetime, row["db_claimed_at"]),
            postgres_server_epoch=cast(datetime, row["postgres_server_epoch"]),
            claim_receipt_hash=cast(str, row["claim_receipt_hash"]),
        )


class PostgresTorrentBatchRecorder:
    """Record only a fully durable, fully accepted torrent batch."""

    def __init__(self, client: PostgresFunctionClient) -> None:
        self._client = client

    @staticmethod
    def _json(document: dict[str, Any] | list[dict[str, Any]]) -> str:
        return json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    def record(
        self,
        *,
        opportunity_id: str,
        raw_operation_id: str,
        raw_object_key: str,
        raw_object_sha256: str,
        normalized_operation_id: str,
        normalized_object_key: str,
        normalized_object_sha256: str,
        canonical_dataset_sha256: str,
        manifest: dict[str, Any],
        raw_index: dict[str, Any],
        normalized_index: dict[str, Any],
        quality_report: dict[str, Any],
        coverage_matrix: list[dict[str, Any]],
        official_physical_reads: int,
        odds_provider_requests: int,
        odds_credits_used: int,
        raw_responses: int,
        raw_bytes: int,
        normalized_records: int,
        rejected_records: int,
        silent_drops: int,
        logical_duplicates: int,
        temporal_leakage: int,
        replay_multiplier: int,
        replay_equivalent_records: int,
        replay_records_per_second: float,
        replay_bytes_per_second: float,
        replay_p50_latency_ms: float,
        replay_p95_latency_ms: float,
        replay_peak_memory_bytes: int,
        normal_required_records_per_second: float,
        normal_required_bytes_per_second: float,
        throughput_ratio: float,
        idempotent_replay: bool,
        r2_puts: int,
        r2_gets: int,
        r2_lists: int,
        r2_deletes: int,
        r2_objects: int,
        automatic_retries: int,
        unaccounted_external_effects: int,
        qa_acceptance_percent: int,
        p0: int,
        p1: int,
        p2: int,
        open_threads: int,
        edge_promotions: int,
        bet_calls: int,
        data_torrent_ready: bool,
        identity: GitHubRunIdentity,
        generation_token: str,
    ) -> TorrentBatchReceipt:
        for value, field in (
            (opportunity_id, "opportunity_id"),
            (raw_operation_id, "raw_operation_id"),
            (raw_object_sha256, "raw_object_sha256"),
            (normalized_operation_id, "normalized_operation_id"),
            (normalized_object_sha256, "normalized_object_sha256"),
            (canonical_dataset_sha256, "canonical_dataset_sha256"),
            (generation_token, "generation_token"),
        ):
            _required_hash(value, field=field)
        if not all(
            math.isfinite(value)
            for value in (
                replay_records_per_second,
                replay_bytes_per_second,
                replay_p50_latency_ms,
                replay_p95_latency_ms,
                normal_required_records_per_second,
                normal_required_bytes_per_second,
                throughput_ratio,
            )
        ):
            raise ValueError("DATA_TORRENT_REPLAY_THROUGHPUT_INVALID")
        placeholders = ["%s"] * 53
        for index in range(8, 13):
            placeholders[index] = "%s::jsonb"
        # The only dynamic fragments are the fixed count/type of DB-API placeholders.
        row = self._client.fetch_one(
            "SELECT * FROM public.chronos_record_torrent_batch("  # nosec B608
            + ",".join(placeholders)
            + ")",
            (
                opportunity_id,
                raw_operation_id,
                raw_object_key,
                raw_object_sha256,
                normalized_operation_id,
                normalized_object_key,
                normalized_object_sha256,
                canonical_dataset_sha256,
                self._json(manifest),
                self._json(raw_index),
                self._json(normalized_index),
                self._json(quality_report),
                self._json(coverage_matrix),
                official_physical_reads,
                odds_provider_requests,
                odds_credits_used,
                raw_responses,
                raw_bytes,
                normalized_records,
                rejected_records,
                silent_drops,
                logical_duplicates,
                temporal_leakage,
                replay_multiplier,
                replay_equivalent_records,
                replay_records_per_second,
                replay_bytes_per_second,
                replay_p50_latency_ms,
                replay_p95_latency_ms,
                replay_peak_memory_bytes,
                normal_required_records_per_second,
                normal_required_bytes_per_second,
                throughput_ratio,
                idempotent_replay,
                r2_puts,
                r2_gets,
                r2_lists,
                r2_deletes,
                r2_objects,
                automatic_retries,
                unaccounted_external_effects,
                qa_acceptance_percent,
                p0,
                p1,
                p2,
                open_threads,
                edge_promotions,
                bet_calls,
                data_torrent_ready,
                identity.github_run_id,
                identity.github_run_attempt,
                identity.github_sha,
                bytes.fromhex(generation_token),
            ),
        )
        return TorrentBatchReceipt(
            opportunity_id=cast(str, row["opportunity_id"]),
            created_now=cast(bool, row["created_now"]),
            db_recorded_at=cast(datetime, row["db_recorded_at"]),
            postgres_server_epoch=cast(datetime, row["postgres_server_epoch"]),
            record_hash=cast(str, row["record_hash"]),
        )


__all__ = [
    "DataTorrentOpportunity",
    "ExternalEffectEventReceipt",
    "ExternalEffectPermitReceipt",
    "OpportunityClaimReceipt",
    "PostgresOpportunityClaimer",
    "PostgresExternalEffectLedger",
    "PostgresTorrentBatchRecorder",
    "TorrentBatchReceipt",
    "derive_opportunity_id",
]
