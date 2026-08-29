"""Single-attempt official and odds capture behind durable external-effect permits."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from robin.capture.live_contracts import validate_provider_ip_address
from robin.capture.live_transport import (
    EnvironmentSecretReader,
    PublicProviderRequestV1,
    StrictHttpsTransport,
)
from robin.capture.official_schedule_sources import (
    LIGUE1_CALENDAR_JSON_V1,
    BuiltinHttpsOfficialScheduleFetcher,
    OfficialFetchResult,
    OfficialPhysicalResponse,
    OfficialScheduleSourceError,
    fetch_official_schedule_source,
)
from robin.data_torrent.claims import (
    ExternalEffectEventReceipt,
    ExternalEffectPermitReceipt,
    PostgresExternalEffectLedger,
)
from robin.data_torrent.contracts import (
    RawResponseEnvelope,
    TorrentConfig,
    canonical_json_bytes,
    utc_text,
)
from robin.prospective_observatory.chronos_control_plane import GitHubRunIdentity

PROVIDER_HOST = "api.the-odds-api.com"


@dataclass(slots=True)
class SourceEffectCounters:
    official_physical_reads: int = 0
    odds_dns_resolutions: int = 0
    odds_provider_dispatches: int = 0
    odds_credits: int = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "official_reads": self.official_physical_reads,
            "odds_dns_resolutions": self.odds_dns_resolutions,
            "odds_provider_dispatches": self.odds_provider_dispatches,
            "odds_credits": self.odds_credits,
        }


@dataclass(frozen=True, slots=True)
class ExternalEffectTrace:
    family: str
    sport_key: str
    request_contract: dict[str, Any]
    permit: ExternalEffectPermitReceipt
    dispatched: ExternalEffectEventReceipt
    terminal: ExternalEffectEventReceipt

    def to_json(self) -> dict[str, Any]:
        document = asdict(self)
        for section in ("permit", "dispatched", "terminal"):
            for field in (
                "db_permitted_at",
                "db_recorded_at",
                "postgres_server_epoch",
            ):
                value = document[section].get(field)
                if isinstance(value, datetime):
                    document[section][field] = utc_text(value)
        return document


@dataclass(frozen=True, slots=True)
class ObservedSourceResponse:
    observation_id: str
    observation_sequence: int
    family: str
    sport_key: str
    source: str
    retrieved_at_utc: datetime
    http_status: int
    content_type: str
    response_headers: dict[str, str]
    body: bytes
    external_effect_sequence: int
    external_operation_id: str
    permit_hash: str
    dispatch_event_hash: str
    spool_name: str | None
    body_complete: bool

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def index_entry(self, *, archive_path: str) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observation_sequence": self.observation_sequence,
            "family": self.family,
            "sport_key": self.sport_key,
            "source": self.source,
            "retrieved_at_utc": self.retrieved_at_utc.isoformat().replace("+00:00", "Z"),
            "http_status": self.http_status,
            "content_type": self.content_type,
            "response_headers": self.response_headers,
            "raw_bytes": len(self.body),
            "raw_sha256": self.sha256,
            "external_effect_sequence": self.external_effect_sequence,
            "external_operation_id": self.external_operation_id,
            "permit_hash": self.permit_hash,
            "dispatch_event_hash": self.dispatch_event_hash,
            "terminal_binding": "UNAVAILABLE_AT_RESPONSE_BOUNDARY",
            "body_complete": self.body_complete,
            "spool_name": self.spool_name,
            "archive_path": archive_path,
        }


@dataclass(slots=True)
class SourceCaptureProgress:
    """Immediate response-boundary spool shared across source families."""

    spool_directory: Path | None = None
    observed_responses: list[ObservedSourceResponse] = dataclass_field(default_factory=list)
    raw_responses: list[RawResponseEnvelope] = dataclass_field(default_factory=list)
    effects: list[ExternalEffectTrace] = dataclass_field(default_factory=list)
    active_effects: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)

    def begin_effect(
        self,
        *,
        family: str,
        sport_key: str,
        request_contract: dict[str, Any],
        permit: ExternalEffectPermitReceipt,
        dispatched: ExternalEffectEventReceipt,
    ) -> None:
        permit_document = asdict(permit)
        dispatched_document = asdict(dispatched)
        for document in (permit_document, dispatched_document):
            for name, value in tuple(document.items()):
                if isinstance(value, datetime):
                    document[name] = utc_text(value)
        if permit.operation_id in self.active_effects:
            raise RuntimeError("DATA_TORRENT_DUPLICATE_ACTIVE_EFFECT")
        self.active_effects[permit.operation_id] = {
            "family": family,
            "sport_key": sport_key,
            "request_contract": request_contract,
            "permit": permit_document,
            "dispatched": dispatched_document,
            "terminal": "UNAVAILABLE_AFTER_DISPATCH",
        }

    def complete_effect(self, trace: ExternalEffectTrace) -> None:
        if self.active_effects.pop(trace.permit.operation_id, None) is None:
            raise RuntimeError("DATA_TORRENT_ACTIVE_EFFECT_MISSING")
        self.effects.append(trace)

    def observe(
        self,
        *,
        family: str,
        sport_key: str,
        source: str,
        retrieved_at_utc: datetime,
        http_status: int,
        content_type: str,
        response_headers: dict[str, str],
        body: bytes,
        external_effect_sequence: int,
        external_operation_id: str,
        permit_hash: str,
        dispatch_event_hash: str,
        body_complete: bool = True,
    ) -> None:
        sequence = len(self.observed_responses) + 1
        body_hash = hashlib.sha256(body).hexdigest()
        observation_id = hashlib.sha256(
            canonical_json_bytes(
                {
                    "family": family,
                    "sport_key": sport_key,
                    "sequence": sequence,
                    "raw_sha256": body_hash,
                    "operation_id": external_operation_id,
                }
            )
        ).hexdigest()
        spool_name = (
            f"{sequence:03d}-{observation_id}.bin" if self.spool_directory is not None else None
        )
        observation = ObservedSourceResponse(
            observation_id=observation_id,
            observation_sequence=sequence,
            family=family,
            sport_key=sport_key,
            source=source,
            retrieved_at_utc=retrieved_at_utc,
            http_status=http_status,
            content_type=content_type or "UNKNOWN",
            response_headers=response_headers,
            body=body,
            external_effect_sequence=external_effect_sequence,
            external_operation_id=external_operation_id,
            permit_hash=permit_hash,
            dispatch_event_hash=dispatch_event_hash,
            spool_name=spool_name,
            body_complete=body_complete,
        )
        # Own the complete transport response in memory before any filesystem
        # operation can fail. The outer runtime can then emit a sanitized
        # recovery receipt and attempt one partial archive without losing bytes.
        self.observed_responses.append(observation)
        if self.spool_directory is not None:
            self.spool_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.spool_directory.is_symlink() or not self.spool_directory.is_dir():
                raise RuntimeError("DATA_TORRENT_RAW_SPOOL_INVALID")
            if spool_name is None:
                raise RuntimeError("DATA_TORRENT_RAW_SPOOL_NAME_MISSING")
            path = self.spool_directory / spool_name
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise


@dataclass(frozen=True, slots=True)
class OfficialCapture:
    results: dict[str, OfficialFetchResult]
    raw_responses: tuple[RawResponseEnvelope, ...]
    receipts: tuple[dict[str, Any], ...]
    effects: tuple[ExternalEffectTrace, ...]
    physical_reads: int
    errors: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class OddsCapture:
    raw_responses: tuple[RawResponseEnvelope, ...]
    effects: tuple[ExternalEffectTrace, ...]
    provider_receipt: dict[str, Any]
    provider_requests: int
    credits_used: int
    dns_resolutions: int
    errors: tuple[dict[str, str], ...]


def _response_id(
    *,
    family: str,
    sport_key: str,
    sequence: int,
    body: bytes,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "family": family,
                "sport_key": sport_key,
                "sequence": sequence,
                "raw_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    ).hexdigest()


def _request_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def _run_identity_text(identity: GitHubRunIdentity) -> str:
    return (
        f"github:{identity.github_repository}:{identity.github_run_id}:"
        f"{identity.github_run_attempt}:{identity.github_sha}"
    )


def capture_official_sources(
    *,
    config: TorrentConfig,
    ledger: PostgresExternalEffectLedger,
    opportunity_id: str,
    identity: GitHubRunIdentity,
    generation_token: str,
    counters: SourceEffectCounters,
    anchor: datetime,
    progress: SourceCaptureProgress | None = None,
    clock: Any = lambda: datetime.now(UTC),
) -> OfficialCapture:
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("DATA_TORRENT_OFFICIAL_ANCHOR_INVALID")
    anchor_utc = anchor.astimezone(UTC)
    maximum_expires = anchor_utc + timedelta(days=config.fallback_horizon_days)
    results: dict[str, OfficialFetchResult] = {}
    envelopes: list[RawResponseEnvelope] = []
    receipts: list[dict[str, Any]] = []
    effects: list[ExternalEffectTrace] = []
    errors: list[dict[str, str]] = []
    global_response_sequence = 0
    run_text = _run_identity_text(identity)
    for logical_sequence, league in enumerate(config.leagues, start=1):
        maximum_reads = 12 if league.sport_key == "soccer_spain_la_liga" else 6
        maximum_redirects = 0 if league.official_source.adapter == LIGUE1_CALENDAR_JSON_V1 else 5
        request_contract: dict[str, Any] = {
            "schema_version": "robin-data-torrent-official-request-v1",
            "method": "GET",
            "sanitized_endpoint": league.official_source.url,
            "sport_key": league.sport_key,
            "adapter_revision": league.official_source.adapter,
            "timeout_seconds": 45,
            "maximum_redirects": maximum_redirects,
            "maximum_supporting_reads": maximum_reads - 1,
            "maximum_physical_reads": maximum_reads,
            "selection_horizon_not_before_utc": utc_text(anchor_utc),
            "selection_horizon_expires_at_utc": utc_text(maximum_expires),
            "automatic_retries": 0,
            "certificate_verification_required": True,
        }
        permit = ledger.reserve(
            opportunity_id=opportunity_id,
            effect_family="OFFICIAL",
            effect_sequence=logical_sequence,
            request_hash=_request_hash(request_contract),
            max_official_reads=maximum_reads,
            max_odds_requests=0,
            max_odds_credits=0,
            identity=identity,
            generation_token=generation_token,
        )
        dispatched = ledger.append(
            operation_id=permit.operation_id,
            event_type="DISPATCHED",
            actual_official_reads=0,
            actual_odds_requests=0,
            actual_odds_credits=0,
            identity=identity,
            generation_token=generation_token,
        )
        if progress is not None:
            progress.begin_effect(
                family="OFFICIAL",
                sport_key=league.sport_key,
                request_contract=request_contract,
                permit=permit,
                dispatched=dispatched,
            )
        physical: list[OfficialPhysicalResponse] = []
        attempted_reads = 0

        def observe_official_dispatch(_url: str) -> None:
            nonlocal attempted_reads
            attempted_reads += 1
            counters.official_physical_reads += 1

        def observe_official_response(response: OfficialPhysicalResponse) -> None:
            physical.append(response)
            if progress is not None:
                progress.observe(
                    family="OFFICIAL_PHYSICAL",
                    sport_key=league.sport_key,
                    source=response.requested_url,
                    retrieved_at_utc=response.observed_at_utc,
                    http_status=response.status_code,
                    content_type=response.content_type,
                    response_headers=dict(response.response_headers),
                    body=response.body,
                    external_effect_sequence=logical_sequence,
                    external_operation_id=permit.operation_id,
                    permit_hash=permit.permit_hash,
                    dispatch_event_hash=dispatched.event_hash,
                )

        def observe_partial_official_response(response: OfficialPhysicalResponse) -> None:
            if progress is not None:
                progress.observe(
                    family="OFFICIAL_PARTIAL",
                    sport_key=league.sport_key,
                    source=response.requested_url,
                    retrieved_at_utc=response.observed_at_utc,
                    http_status=response.status_code,
                    content_type=response.content_type,
                    response_headers=dict(response.response_headers),
                    body=response.body,
                    external_effect_sequence=logical_sequence,
                    external_operation_id=permit.operation_id,
                    permit_hash=permit.permit_hash,
                    dispatch_event_hash=dispatched.event_hash,
                    body_complete=False,
                )

        fetcher = BuiltinHttpsOfficialScheduleFetcher(
            clock=clock,
            on_dispatch=observe_official_dispatch,
            on_response=observe_official_response,
            on_partial_response=observe_partial_official_response,
            horizon_not_before_utc=anchor_utc,
            horizon_expires_at_utc=maximum_expires,
        )
        result: OfficialFetchResult | None = None
        classification_receipt: Any | None = None
        error_code: str | None = None
        try:
            result = fetch_official_schedule_source(
                league.official_source,
                fetcher=fetcher,
                clock=clock,
            )
        except OfficialScheduleSourceError as error:
            error_code = error.code
            if error.receipt is not None:
                classification_receipt = error.receipt
                receipts.append(cast(dict[str, Any], error.receipt.to_json()))
        else:
            classification_receipt = result.receipt
            results[league.sport_key] = result
            receipts.append(cast(dict[str, Any], result.receipt.to_json()))
        primary_indexes = tuple(
            index
            for index, response in enumerate(physical)
            if (
                classification_receipt is not None
                and response.requested_url == classification_receipt.final_url
                and response.status_code == classification_receipt.http_status
                and len(response.body) == classification_receipt.byte_count
                and hashlib.sha256(response.body).hexdigest() == classification_receipt.raw_sha256
            )
            or (
                classification_receipt is None
                and response.requested_url == league.official_source.url
            )
        )
        if (
            not primary_indexes
            and result is None
            and league.official_source.adapter == LIGUE1_CALENDAR_JSON_V1
        ):
            primary_indexes = tuple(
                index
                for index, response in enumerate(physical)
                if response.requested_url == league.official_source.url
            )
        if result is not None and len(primary_indexes) != 1:
            error_code = "OFFICIAL_PRIMARY_PHYSICAL_RESPONSE_INVALID"
            results.pop(league.sport_key, None)
        if not physical or error_code == "OFFICIAL_SOURCE_NETWORK_FAILED":
            terminal = ledger.append(
                operation_id=permit.operation_id,
                event_type="AMBIGUOUS",
                actual_official_reads=attempted_reads,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=generation_token,
            )
        else:
            terminal = ledger.append(
                operation_id=permit.operation_id,
                event_type="CONFIRMED",
                actual_official_reads=attempted_reads,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=generation_token,
            )
        trace = ExternalEffectTrace(
            family="OFFICIAL",
            sport_key=league.sport_key,
            request_contract=request_contract,
            permit=permit,
            dispatched=dispatched,
            terminal=terminal,
        )
        effects.append(trace)
        if progress is not None:
            progress.complete_effect(trace)
        for physical_index, response in enumerate(physical):
            global_response_sequence += 1
            is_main = len(primary_indexes) == 1 and physical_index == primary_indexes[0]
            family = "OFFICIAL" if is_main else "OFFICIAL_SUPPORTING"
            disposition = "ACCEPTED" if error_code is None else "REJECTED"
            physical_request_contract = {
                **request_contract,
                "sanitized_endpoint": response.requested_url,
                "physical_response_index": physical_index,
                "logical_request_endpoint": league.official_source.url,
            }
            envelope = RawResponseEnvelope(
                response_id=_response_id(
                    family=family,
                    sport_key=league.sport_key,
                    sequence=global_response_sequence,
                    body=response.body,
                ),
                family=cast(Any, family),
                sport_key=league.sport_key,
                source=response.requested_url,
                request_contract=physical_request_contract,
                retrieved_at_utc=(
                    result.receipt.observed_at_utc
                    if is_main and result is not None
                    else response.observed_at_utc
                ),
                http_status=response.status_code,
                content_type=response.content_type or "UNKNOWN",
                response_headers=dict(response.response_headers),
                body=response.body,
                run_identity=run_text,
                claim_identity=opportunity_id,
                response_sequence=global_response_sequence,
                external_effect_sequence=logical_sequence,
                external_operation_id=permit.operation_id,
                permit_hash=permit.permit_hash,
                dispatch_event_hash=dispatched.event_hash,
                confirmation_event_hash=terminal.event_hash,
                disposition=disposition,
                rejection_reason=error_code,
            )
            envelopes.append(envelope)
            if progress is not None:
                progress.raw_responses.append(envelope)
        if error_code is not None:
            errors.append({"sport_key": league.sport_key, "code": error_code})
        if error_code is not None:
            break
    return OfficialCapture(
        results=results,
        raw_responses=tuple(envelopes),
        receipts=tuple(receipts),
        effects=tuple(effects),
        physical_reads=sum(item.terminal.actual_official_reads for item in effects),
        errors=tuple(errors),
    )


def _resolve_provider_address() -> str:
    candidates: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for item in socket.getaddrinfo(
        PROVIDER_HOST,
        443,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
    ):
        try:
            address = ipaddress.ip_address(str(item[4][0]))
            validate_provider_ip_address(str(address))
        except (IndexError, TypeError, ValueError):
            continue
        candidates.add(address)
    if not candidates:
        raise RuntimeError("DATA_TORRENT_PROVIDER_DNS_NO_PUBLIC_ADDRESS")
    return str(sorted(candidates, key=lambda value: (value.version, int(value)))[0])


def _header_int(headers: dict[str, str], name: str, *, maximum: int) -> int:
    value = headers.get(name, "")
    if not value.isascii() or not value.isdigit():
        raise ValueError("DATA_TORRENT_PROVIDER_CREDIT_HEADER_INVALID")
    parsed = int(value)
    if not 0 <= parsed <= maximum:
        raise ValueError("DATA_TORRENT_PROVIDER_CREDIT_HEADER_INVALID")
    return parsed


def _provider_credit_charge(
    headers: dict[str, str],
    *,
    maximum: int,
) -> tuple[int, dict[str, int | str]]:
    """Return an exact debit or conservatively charge the authorized maximum."""

    value = headers.get("x-requests-last", "")
    if value.isascii() and value.isdigit():
        parsed = int(value)
        if 0 <= parsed <= maximum:
            return parsed, {}
        return maximum, {
            "state": "OVER_AUTHORIZED_LIMIT",
            "observed_credits": parsed,
            "accounted_credits": maximum,
        }
    encoded = value.encode("utf-8", errors="replace")
    return maximum, {
        "state": "UNKNOWN_MALFORMED",
        "observed_value_bytes": len(encoded),
        "observed_value_sha256": hashlib.sha256(encoded).hexdigest(),
        "accounted_credits": maximum,
    }


def capture_odds_sources(
    *,
    config: TorrentConfig,
    ledger: PostgresExternalEffectLedger,
    opportunity_id: str,
    identity: GitHubRunIdentity,
    generation_token: str,
    environment: dict[str, str] | Any,
    response_sequence_start: int,
    counters: SourceEffectCounters,
    progress: SourceCaptureProgress | None = None,
    clock: Any = lambda: datetime.now(UTC),
) -> OddsCapture:
    run_text = _run_identity_text(identity)
    secret = EnvironmentSecretReader(environment).read()
    requests: list[dict[str, Any]] = []
    for league in config.leagues:
        request_contract: dict[str, Any] = {
            "schema_version": "robin-data-torrent-odds-request-v1",
            "method": "GET",
            "sanitized_endpoint": (f"https://{PROVIDER_HOST}/v4/sports/{league.sport_key}/odds"),
            "sport_key": league.sport_key,
            "region": config.region,
            "markets": list(config.markets),
            "odds_format": "decimal",
            "date_format": "iso",
            "timeout_seconds": 30,
            "maximum_redirects": 0,
            "automatic_retries": 0,
            "certificate_verification_required": True,
            "environment_proxy_allowed": False,
        }
        requests.append(request_contract)
    envelopes: list[RawResponseEnvelope] = []
    effects: list[ExternalEffectTrace] = []
    errors: list[dict[str, str]] = []
    credit_transitions: list[dict[str, int | str]] = []
    credit_anomalies: list[dict[str, int | str]] = []
    dns_resolutions = 0
    for logical_sequence, (league, request_contract) in enumerate(
        zip(config.leagues, requests, strict=True),
        start=1,
    ):
        permit = ledger.reserve(
            opportunity_id=opportunity_id,
            effect_family="ODDS",
            effect_sequence=logical_sequence,
            request_hash=_request_hash(request_contract),
            max_official_reads=0,
            max_odds_requests=1,
            max_odds_credits=200,
            identity=identity,
            generation_token=generation_token,
        )
        response = None
        provider_dispatched = False
        credits = 0
        credit_accounted = False
        response_observed = False
        observed_transport_response: Any | None = None
        error_code: str | None = None
        dispatched = ledger.append(
            operation_id=permit.operation_id,
            event_type="DISPATCHED",
            actual_official_reads=0,
            actual_odds_requests=0,
            actual_odds_credits=0,
            identity=identity,
            generation_token=generation_token,
        )
        if progress is not None:
            progress.begin_effect(
                family="ODDS",
                sport_key=league.sport_key,
                request_contract=request_contract,
                permit=permit,
                dispatched=dispatched,
            )
        # DNS is itself an external observation. Record the logical dispatch
        # durably first and count the attempt before entering the resolver.
        dns_resolutions += 1
        counters.odds_dns_resolutions += 1

        def observe_odds_response(
            observed_response: Any,
            body_complete: bool,
        ) -> None:
            nonlocal credit_accounted, credits, observed_transport_response, response_observed
            if response_observed:
                raise RuntimeError("DATA_TORRENT_PROVIDER_DUPLICATE_RESPONSE")
            response_observed = True
            observed_transport_response = observed_response
            observed_headers = dict(observed_response.headers)
            credits, credit_anomaly = _provider_credit_charge(
                observed_headers,
                maximum=permit.max_odds_credits,
            )
            counters.odds_credits += credits
            credit_accounted = True
            credit_error = bool(credit_anomaly)
            if credit_anomaly:
                credit_anomalies.append({"sport_key": league.sport_key, **credit_anomaly})
            else:
                try:
                    used_after = _header_int(
                        observed_headers,
                        "x-requests-used",
                        maximum=2**63 - 1,
                    )
                    remaining_after = _header_int(
                        observed_headers,
                        "x-requests-remaining",
                        maximum=2**63 - 1,
                    )
                    if used_after < credits:
                        raise ValueError("DATA_TORRENT_PROVIDER_CREDIT_HEADER_INVALID")
                except ValueError:
                    credit_error = True
                    credit_anomalies.append(
                        {
                            "sport_key": league.sport_key,
                            "state": "CONTROL_BALANCE_INVALID",
                            "accounted_credits": credits,
                        }
                    )
                else:
                    credit_transitions.append(
                        {
                            "sport_key": league.sport_key,
                            "used_before": used_after - credits,
                            "used_after": used_after,
                            "remaining_after": remaining_after,
                            "credits_used": credits,
                        }
                    )
            if progress is not None:
                progress.observe(
                    family="ODDS" if body_complete else "ODDS_PARTIAL",
                    sport_key=league.sport_key,
                    source=cast(str, request_contract["sanitized_endpoint"]),
                    retrieved_at_utc=observed_response.first_observed_at_utc,
                    http_status=observed_response.http_status,
                    content_type="UNKNOWN",
                    response_headers=dict(observed_response.headers),
                    body=observed_response.payload,
                    external_effect_sequence=logical_sequence,
                    external_operation_id=permit.operation_id,
                    permit_hash=permit.permit_hash,
                    dispatch_event_hash=dispatched.event_hash,
                    body_complete=body_complete,
                )
            if credit_error:
                raise ValueError("DATA_TORRENT_PROVIDER_CREDIT_HEADER_INVALID")

        def observe_provider_dispatch() -> None:
            nonlocal provider_dispatched
            if provider_dispatched:
                raise RuntimeError("DATA_TORRENT_PROVIDER_DUPLICATE_DISPATCH")
            counters.odds_provider_dispatches += 1
            provider_dispatched = True

        try:
            approved_ip = _resolve_provider_address()
            request = PublicProviderRequestV1(
                endpoint=f"/v4/sports/{league.sport_key}/odds",
                sport_key=league.sport_key,
                region="eu",
                markets=("h2h", "totals"),
                odds_format="decimal",
                date_format="iso",
                timeout_seconds=30,
                maximum_response_bytes=10_485_760,
                approved_provider_ip_address=approved_ip,
            )
            transport = StrictHttpsTransport(
                clock=clock,
                on_dispatch=observe_provider_dispatch,
                on_response=observe_odds_response,
            )
            transport.preflight(request)
        except Exception as error:
            error_code = str(error)
            terminal = ledger.append(
                operation_id=permit.operation_id,
                event_type="AMBIGUOUS",
                actual_official_reads=0,
                actual_odds_requests=0,
                actual_odds_credits=0,
                identity=identity,
                generation_token=generation_token,
            )
        else:
            try:
                response = transport.dispatch(request, api_key=secret)
                if not response_observed:
                    observe_odds_response(response, True)
                if response.http_status != 200:
                    error_code = "DATA_TORRENT_PROVIDER_HTTP_STATUS_INVALID"
            except Exception as error:
                error_code = str(error)
                if provider_dispatched and not credit_accounted:
                    credits = permit.max_odds_credits
                    counters.odds_credits += credits
                    credit_accounted = True
                    credit_anomalies.append(
                        {
                            "sport_key": league.sport_key,
                            "state": "OUTCOME_UNKNOWN_NO_VALID_CREDIT_HEADER",
                            "accounted_credits": credits,
                        }
                    )
                terminal = ledger.append(
                    operation_id=permit.operation_id,
                    event_type="AMBIGUOUS",
                    actual_official_reads=0,
                    actual_odds_requests=int(provider_dispatched),
                    actual_odds_credits=credits,
                    identity=identity,
                    generation_token=generation_token,
                )
            else:
                terminal = ledger.append(
                    operation_id=permit.operation_id,
                    event_type="CONFIRMED",
                    actual_official_reads=0,
                    actual_odds_requests=1,
                    actual_odds_credits=credits,
                    identity=identity,
                    generation_token=generation_token,
                )
        trace = ExternalEffectTrace(
            family="ODDS",
            sport_key=league.sport_key,
            request_contract=request_contract,
            permit=permit,
            dispatched=dispatched,
            terminal=terminal,
        )
        effects.append(trace)
        if progress is not None:
            progress.complete_effect(trace)
        captured_response = response if response is not None else observed_transport_response
        if captured_response is not None:
            sequence = response_sequence_start + config.leagues.index(league) + 1
            envelope = RawResponseEnvelope(
                response_id=_response_id(
                    family="ODDS",
                    sport_key=league.sport_key,
                    sequence=sequence,
                    body=captured_response.payload,
                ),
                family="ODDS",
                sport_key=league.sport_key,
                source=cast(str, request_contract["sanitized_endpoint"]),
                request_contract=request_contract,
                retrieved_at_utc=captured_response.first_observed_at_utc,
                http_status=captured_response.http_status,
                content_type="UNKNOWN",
                response_headers=dict(captured_response.headers),
                body=captured_response.payload,
                run_identity=run_text,
                claim_identity=opportunity_id,
                response_sequence=sequence,
                external_effect_sequence=logical_sequence,
                external_operation_id=permit.operation_id,
                permit_hash=permit.permit_hash,
                dispatch_event_hash=dispatched.event_hash,
                confirmation_event_hash=terminal.event_hash,
                provider_requests=1,
                provider_credits=terminal.actual_odds_credits,
                disposition="ACCEPTED" if error_code is None else "REJECTED",
                rejection_reason=error_code,
            )
            envelopes.append(envelope)
            if progress is not None:
                progress.raw_responses.append(envelope)
        if error_code is not None:
            errors.append({"sport_key": league.sport_key, "code": error_code})
            break
    del secret
    return OddsCapture(
        raw_responses=tuple(envelopes),
        effects=tuple(effects),
        provider_receipt={
            "schema_version": "robin-data-torrent-provider-credit-receipt-v1",
            "selection_mode": "FULL",
            "contracts_requested": [item.sport_key for item in config.leagues],
            "markets": list(config.markets),
            "credit_transitions": credit_transitions,
            "credit_accounting": (
                "EXACT" if not credit_anomalies else "CONSERVATIVE_MAXIMUM_AMBIGUOUS"
            ),
            "credit_anomalies": credit_anomalies,
            "automatic_retries": 0,
            "identical_snapshot_attempts": 1,
            "provider_requests": sum(item.terminal.actual_odds_requests for item in effects),
            "credits_used": sum(item.terminal.actual_odds_credits for item in effects),
            "dns_resolutions": dns_resolutions,
            "maximum_dns_resolutions": len(config.leagues),
            "maximum_credits": config.budgets.odds_credits_max,
            "errors": errors,
        },
        provider_requests=sum(item.terminal.actual_odds_requests for item in effects),
        credits_used=sum(item.terminal.actual_odds_credits for item in effects),
        dns_resolutions=dns_resolutions,
        errors=tuple(errors),
    )


__all__ = [
    "ExternalEffectTrace",
    "OddsCapture",
    "ObservedSourceResponse",
    "OfficialCapture",
    "SourceCaptureProgress",
    "SourceEffectCounters",
    "capture_odds_sources",
    "capture_official_sources",
]
