from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import robin.data_torrent.runtime as runtime_module
from robin.capture.live_transport import LiveTransportResponse
from robin.data_torrent.claims import (
    ExternalEffectEventReceipt,
    ExternalEffectPermitReceipt,
)
from robin.data_torrent.contracts import (
    RawResponseEnvelope,
    canonical_json_bytes,
    load_torrent_config,
)
from robin.data_torrent.durability import DurableObjectReceipt, DurableObjectUploadError
from robin.data_torrent.runtime import (
    DataTorrentRuntimeError,
    RuntimeIdentity,
    _assert_recorded_batch_binding,
    _assert_source_effect_lineage,
    _durabilize_partial_capture,
    _partial_raw_put_authorized,
    execute_data_torrent,
)
from robin.data_torrent.sources import (
    ExternalEffectTrace,
    SourceCaptureProgress,
    SourceEffectCounters,
    capture_odds_sources,
    capture_official_sources,
)
from robin.prospective_observatory.chronos_control_plane import (
    EffectEventType,
    GitHubRunIdentity,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "data" / "torrent-live-v1.json"
NOW = datetime(2026, 8, 29, 12, tzinfo=UTC)


def test_official_adapter_validation_precedes_provider_and_raw_put() -> None:
    source = inspect.getsource(execute_data_torrent)
    parse_at = source.index("evidences, horizon = _select_evidence(")
    alias_validation_at = source.index("validate_official_team_aliases(")
    odds_at = source.index("odds = capture_odds_sources(")
    raw_put_at = source.index('role="RAW"')
    assert parse_at < alias_validation_at < odds_at < raw_put_at
    assert "EnvironmentSecretReader" not in source[:odds_at]
    capture_source = inspect.getsource(capture_official_sources)
    assert "physical_index == len(physical) - 1" not in capture_source
    assert "classification_receipt.raw_sha256" in capture_source
    assert "response.requested_url == league.official_source.url" in capture_source
    assert '"maximum_supporting_reads"' in capture_source
    assert '"selection_horizon_expires_at_utc"' in capture_source


def _hex(value: int) -> str:
    return f"{value:064x}"


def _effect_pair(
    *,
    family: str,
    sequence: int,
    sport_key: str,
) -> tuple[RawResponseEnvelope, ExternalEffectTrace]:
    global_sequence = sequence if family == "OFFICIAL" else sequence + 5
    operation_id = _hex(100 + global_sequence)
    permit_hash = _hex(200 + global_sequence)
    dispatch_hash = _hex(300 + global_sequence)
    confirmation_hash = _hex(400 + global_sequence)
    request_contract = {
        "schema_version": f"robin-data-torrent-{family.casefold()}-request-v1",
        "method": "GET",
        "sanitized_endpoint": f"https://example.invalid/{sport_key}/{family.casefold()}",
        "sport_key": sport_key,
        "automatic_retries": 0,
    }
    provider = family == "ODDS"
    permit = ExternalEffectPermitReceipt(
        operation_id=operation_id,
        effect_family=family,  # type: ignore[arg-type]
        effect_sequence=sequence,
        request_hash=hashlib.sha256(canonical_json_bytes(request_contract)).hexdigest(),
        max_official_reads=0 if provider else 6,
        max_odds_requests=1 if provider else 0,
        max_odds_credits=200 if provider else 0,
        created_now=True,
        db_permitted_at=NOW,
        postgres_server_epoch=NOW,
        permit_hash=permit_hash,
    )
    dispatched = ExternalEffectEventReceipt(
        operation_id=operation_id,
        event_seq=1,
        event_type="DISPATCHED",
        actual_official_reads=0,
        actual_odds_requests=0,
        actual_odds_credits=0,
        db_recorded_at=NOW,
        postgres_server_epoch=NOW,
        previous_event_hash="0" * 64,
        event_hash=dispatch_hash,
    )
    terminal = ExternalEffectEventReceipt(
        operation_id=operation_id,
        event_seq=2,
        event_type="CONFIRMED",
        actual_official_reads=0 if provider else 1,
        actual_odds_requests=1 if provider else 0,
        actual_odds_credits=1 if provider else 0,
        db_recorded_at=NOW,
        postgres_server_epoch=NOW,
        previous_event_hash=dispatch_hash,
        event_hash=confirmation_hash,
    )
    raw_request_contract = (
        request_contract
        if provider
        else {
            **request_contract,
            "physical_response_index": 0,
            "logical_request_endpoint": request_contract["sanitized_endpoint"],
        }
    )
    response = RawResponseEnvelope(
        response_id=_hex(500 + global_sequence),
        family=family,  # type: ignore[arg-type]
        sport_key=sport_key,
        source=str(request_contract["sanitized_endpoint"]),
        request_contract=raw_request_contract,
        retrieved_at_utc=NOW,
        http_status=200,
        content_type="application/json",
        response_headers={"content-type": "application/json"},
        body=b"{}",
        run_identity="github:dddur75/robin-stades-ng:99:1:" + "1" * 40,
        claim_identity="2" * 64,
        response_sequence=global_sequence,
        external_effect_sequence=sequence,
        external_operation_id=operation_id,
        permit_hash=permit_hash,
        dispatch_event_hash=dispatch_hash,
        confirmation_event_hash=confirmation_hash,
        provider_requests=int(provider),
        provider_credits=int(provider),
    )
    return response, ExternalEffectTrace(
        family=family,
        sport_key=sport_key,
        request_contract=request_contract,
        permit=permit,
        dispatched=dispatched,
        terminal=terminal,
    )


def _complete_lineage() -> tuple[
    tuple[RawResponseEnvelope, ...],
    tuple[ExternalEffectTrace, ...],
]:
    config = load_torrent_config(CONFIG)
    pairs = [
        _effect_pair(family=family, sequence=sequence, sport_key=league.sport_key)
        for family in ("OFFICIAL", "ODDS")
        for sequence, league in enumerate(config.leagues, start=1)
    ]
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


def test_source_effect_lineage_reconstructs_all_ten_permits_and_contracts() -> None:
    responses, traces = _complete_lineage()
    _assert_source_effect_lineage(raw_responses=responses, effects=traces)
    serialized = traces[0].to_json()["permit"]
    assert serialized == {
        "operation_id": _hex(101),
        "effect_family": "OFFICIAL",
        "effect_sequence": 1,
        "request_hash": traces[0].permit.request_hash,
        "max_official_reads": 6,
        "max_odds_requests": 0,
        "max_odds_credits": 0,
        "created_now": True,
        "db_permitted_at": "2026-08-29T12:00:00Z",
        "postgres_server_epoch": "2026-08-29T12:00:00Z",
        "permit_hash": _hex(201),
    }


@pytest.mark.parametrize(
    "corrupt",
    (
        "request_contract",
        "raw_request_contract",
        "permit_hash",
        "confirmation_hash",
        "external_sequence",
        "provider_credits",
    ),
)
def test_source_effect_lineage_fails_closed_on_any_unbound_evidence(corrupt: str) -> None:
    responses, traces = _complete_lineage()
    if corrupt == "request_contract":
        traces = (
            replace(traces[0], request_contract={**traces[0].request_contract, "method": "POST"}),
            *traces[1:],
        )
    else:
        response_index = 5 if corrupt == "provider_credits" else 0
        target = responses[response_index]
        if corrupt == "raw_request_contract":
            corrupted = replace(
                target,
                request_contract={**target.request_contract, "method": "POST"},
            )
        elif corrupt == "permit_hash":
            corrupted = replace(target, permit_hash=_hex(999))
        elif corrupt == "confirmation_hash":
            corrupted = replace(target, confirmation_event_hash=_hex(999))
        elif corrupt == "external_sequence":
            corrupted = replace(target, external_effect_sequence=2)
        else:
            corrupted = replace(target, provider_credits=0)
        responses = (
            *responses[:response_index],
            corrupted,
            *responses[response_index + 1 :],
        )
    with pytest.raises(
        DataTorrentRuntimeError,
        match="DATA_TORRENT_EXTERNAL_EFFECT_LINEAGE_INVALID",
    ):
        _assert_source_effect_lineage(raw_responses=responses, effects=traces)


def test_partial_capture_persists_all_raw_bytes_dns_counters_and_provider_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses, traces = _complete_lineage()
    captured_members: dict[str, bytes] = {}
    written_artifacts: dict[str, bytes] = {}

    def archive(members: dict[str, bytes]) -> bytes:
        captured_members.update(members)
        return b"immutable-partial-archive"

    receipt = DurableObjectReceipt(
        role="PARTIAL_RAW",
        object_key="data-torrent/v1/test/partial-raw.tar.gz",
        object_bytes=25,
        object_sha256=_hex(900),
        operation_id=_hex(901),
        authority_id=_hex(902),
        authority_receipt_hash=_hex(903),
        terminal_event="CREATED_CONFIRMED",
        terminal_event_hash=_hex(904),
        etag="etag",
        events=(),
    )
    monkeypatch.setattr(runtime_module, "deterministic_tar_gz", archive)
    monkeypatch.setattr(
        runtime_module,
        "upload_immutable_object",
        lambda **_values: receipt,
    )
    monkeypatch.setattr(
        runtime_module,
        "write_artifacts",
        lambda _path, artifacts: written_artifacts.update(artifacts),
    )

    class Store:
        def counters(self) -> dict[str, int]:
            return {"puts": 1, "gets": 0, "lists": 0, "deletes": 0}

    github = GitHubRunIdentity(
        github_run_id=99,
        github_run_attempt=1,
        github_sha="1" * 40,
        github_workflow_ref=(
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        github_workflow_sha="1" * 40,
        github_repository="dddur75/robin-stades-ng",
        github_ref="refs/heads/main",
    )
    provider_receipt = {
        "schema_version": "robin-data-torrent-provider-credit-receipt-v1",
        "provider_requests": 5,
        "credits_used": 10,
        "dns_resolutions": 5,
    }
    counters = {
        "official_reads": 5,
        "odds_dns_resolutions": 5,
        "odds_provider_dispatches": 5,
        "odds_credits": 10,
    }
    _durabilize_partial_capture(
        raw_responses=responses,
        errors=({"sport_key": "ALL", "code": "LINEAGE_INVALID"},),
        effects=traces,
        opportunity_id="2" * 64,
        identity=RuntimeIdentity(
            github=github,
            workflow_path=".github/workflows/data-torrent-live-v1.yml",
            workflow_file_sha256="3" * 64,
            runner_os="Linux",
            runner_arch="X64",
            post_merge_ci_sha="1" * 40,
        ),
        generation_token="4" * 64,
        issuer=object(),  # type: ignore[arg-type]
        effect_ledger=object(),  # type: ignore[arg-type]
        r2_store=Store(),  # type: ignore[arg-type]
        output_dir=tmp_path / "partial",
        environment={},
        source_effect_counters=counters,
        provider_receipt=provider_receipt,
    )
    failure = json.loads(captured_members["failure/partial-capture-v1.json"])
    assert failure["source_effect_counters"] == counters
    assert failure["provider_receipt"] == provider_receipt
    assert len(failure["responses"]) == len(responses)
    assert len(failure["external_effects"]) == len(traces)
    assert {name for name in captured_members if name.startswith("responses/")} == {
        f"responses/{item.response_sequence:03d}-{item.response_id}.bin" for item in responses
    }
    persisted = json.loads(written_artifacts["torrent-partial-capture-receipt-v1.json"])
    assert persisted["partial_raw_object"]["terminal_event"] == "CREATED_CONFIRMED"
    attempt = json.loads(written_artifacts["torrent-partial-capture-attempt-v1.json"])
    assert attempt["recovery_status"] == "R2_UPLOAD_PENDING_NO_RETRY_AUTHORIZED"
    assert len(attempt["raw_payload_inventory"]) == len(responses)


def test_partial_capture_emits_sanitized_receipt_before_archive_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses, traces = _complete_lineage()
    written: dict[str, bytes] = {}
    monkeypatch.setattr(
        runtime_module,
        "write_artifacts",
        lambda _path, artifacts: written.update(artifacts),
    )
    monkeypatch.setattr(
        runtime_module,
        "deterministic_tar_gz",
        lambda _members: (_ for _ in ()).throw(RuntimeError("synthetic archive failure")),
    )

    class Store:
        def counters(self) -> dict[str, int]:
            return {"puts": 0, "gets": 0, "lists": 0, "deletes": 0}

    github = GitHubRunIdentity(
        github_run_id=99,
        github_run_attempt=1,
        github_sha="1" * 40,
        github_workflow_ref=(
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        github_workflow_sha="1" * 40,
        github_repository="dddur75/robin-stades-ng",
        github_ref="refs/heads/main",
    )
    with pytest.raises(RuntimeError, match="synthetic archive failure"):
        _durabilize_partial_capture(
            raw_responses=responses,
            errors=({"sport_key": "ALL", "code": "SYNTHETIC_FAILURE"},),
            effects=traces,
            opportunity_id="2" * 64,
            identity=RuntimeIdentity(
                github=github,
                workflow_path=".github/workflows/data-torrent-live-v1.yml",
                workflow_file_sha256="3" * 64,
                runner_os="Linux",
                runner_arch="X64",
                post_merge_ci_sha="1" * 40,
            ),
            generation_token="4" * 64,
            issuer=object(),  # type: ignore[arg-type]
            effect_ledger=object(),  # type: ignore[arg-type]
            r2_store=Store(),  # type: ignore[arg-type]
            output_dir=tmp_path / "partial",
            environment={},
            source_effect_counters={},
            provider_receipt=None,
        )
    assert set(written) == {"torrent-partial-capture-attempt-v1.json"}


def test_unconfirmed_raw_put_emits_receipt_without_second_r2_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses, traces = _complete_lineage()
    written: dict[str, bytes] = {}
    upload_calls = 0

    def forbidden_upload(**_values: object) -> None:
        nonlocal upload_calls
        upload_calls += 1
        raise AssertionError("second R2 PUT forbidden")

    monkeypatch.setattr(runtime_module, "upload_immutable_object", forbidden_upload)
    monkeypatch.setattr(
        runtime_module,
        "write_artifacts",
        lambda _path, artifacts: written.update(artifacts),
    )

    class Store:
        def counters(self) -> dict[str, int]:
            return {"puts": 1, "gets": 0, "lists": 0, "deletes": 0}

    github = GitHubRunIdentity(
        github_run_id=99,
        github_run_attempt=1,
        github_sha="1" * 40,
        github_workflow_ref=(
            "dddur75/robin-stades-ng/.github/workflows/data-torrent-live-v1.yml@refs/heads/main"
        ),
        github_workflow_sha="1" * 40,
        github_repository="dddur75/robin-stades-ng",
        github_ref="refs/heads/main",
    )
    receipt = _durabilize_partial_capture(
        raw_responses=responses,
        errors=({"sport_key": "ALL", "code": "RAW_R2_UNCONFIRMED"},),
        effects=traces,
        opportunity_id="2" * 64,
        identity=RuntimeIdentity(
            github=github,
            workflow_path=".github/workflows/data-torrent-live-v1.yml",
            workflow_file_sha256="3" * 64,
            runner_os="Linux",
            runner_arch="X64",
            post_merge_ci_sha="1" * 40,
        ),
        generation_token="4" * 64,
        issuer=object(),  # type: ignore[arg-type]
        effect_ledger=object(),  # type: ignore[arg-type]
        r2_store=Store(),  # type: ignore[arg-type]
        output_dir=tmp_path / "partial",
        environment={},
        source_effect_counters={},
        provider_receipt=None,
        allow_r2_upload=False,
        recovery_status="RAW_R2_OUTCOME_UNCONFIRMED_NO_RETRY_AUTHORIZED",
    )
    assert receipt is None
    assert upload_calls == 0
    assert set(written) == {"torrent-partial-capture-attempt-v1.json"}
    attempt = json.loads(written["torrent-partial-capture-attempt-v1.json"])
    assert attempt["recovery_status"] == "RAW_R2_OUTCOME_UNCONFIRMED_NO_RETRY_AUTHORIZED"
    assert attempt["r2_counters"]["puts"] == 1


def test_partial_raw_put_authority_distinguishes_predispatch_from_ambiguous() -> None:
    before_dispatch = DurableObjectUploadError(
        "failed before dispatch",
        put_permit_consumed=False,
        terminal_event=EffectEventType.FAILED_BEFORE_DISPATCH,
        operation_id=_hex(860),
    )
    ambiguous = DurableObjectUploadError(
        "outcome pending",
        put_permit_consumed=True,
        terminal_event=EffectEventType.PUT_COMMITTED_ACTUAL_PENDING,
        operation_id=_hex(861),
    )
    assert _partial_raw_put_authorized(error=before_dispatch, r2_puts=1) is True
    assert _partial_raw_put_authorized(error=ambiguous, r2_puts=1) is False
    assert _partial_raw_put_authorized(error=ambiguous, r2_puts=0) is False
    assert _partial_raw_put_authorized(error=RuntimeError("no reservation"), r2_puts=0)
    assert not _partial_raw_put_authorized(error=RuntimeError("unknown"), r2_puts=1)


def test_batch_reader_readback_binds_both_r2_terminals() -> None:
    raw = DurableObjectReceipt(
        role="RAW",
        object_key="data-torrent/v1/test/raw.tar.gz",
        object_bytes=10,
        object_sha256=_hex(870),
        operation_id=_hex(871),
        authority_id=_hex(872),
        authority_receipt_hash=_hex(873),
        terminal_event="CREATED_CONFIRMED",
        terminal_event_hash=_hex(874),
        etag="raw-etag",
        events=(),
    )
    normalized = replace(
        raw,
        role="NORMALIZED_EVIDENCE",
        object_key="data-torrent/v1/test/normalized.tar.gz",
        object_sha256=_hex(875),
        operation_id=_hex(876),
        terminal_event="PREEXISTING_CONFIRMED",
        terminal_event_hash=_hex(877),
    )
    github = GitHubRunIdentity(
        github_run_id=99,
        github_run_attempt=1,
        github_sha="1" * 40,
        github_workflow_ref="owner/repo/.github/workflows/data.yml@refs/heads/main",
        github_workflow_sha="1" * 40,
        github_repository="owner/repo",
        github_ref="refs/heads/main",
    )
    identity = RuntimeIdentity(
        github=github,
        workflow_path=".github/workflows/data-torrent-live-v1.yml",
        workflow_file_sha256="2" * 64,
        runner_os="Linux",
        runner_arch="X64",
        post_merge_ci_sha="1" * 40,
    )
    opportunity_id = "3" * 64
    record_hash = "4" * 64
    canonical_hash = "5" * 64
    expected_counts = {"r2_puts": 2, "r2_gets": 0, "r2_objects": 2}
    row: dict[str, object] = {
        "opportunity_id": opportunity_id,
        "raw_operation_id": raw.operation_id,
        "raw_object_key": raw.object_key,
        "raw_object_sha256": raw.object_sha256,
        "raw_terminal_event_type": raw.terminal_event,
        "raw_terminal_event_hash": raw.terminal_event_hash,
        "normalized_operation_id": normalized.operation_id,
        "normalized_object_key": normalized.object_key,
        "normalized_object_sha256": normalized.object_sha256,
        "normalized_terminal_event_type": normalized.terminal_event,
        "normalized_terminal_event_hash": normalized.terminal_event_hash,
        "canonical_dataset_sha256": canonical_hash,
        "github_run_id": 99,
        "github_run_attempt": 1,
        "code_revision": "1" * 40,
        "record_hash": record_hash,
        "qa_acceptance_percent": 100,
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "open_threads": 0,
        "edge_promotions": 0,
        "bet_calls": 0,
        "data_torrent_ready": True,
        **expected_counts,
    }

    class Result:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def mappings(self) -> Result:
            return self

        def one_or_none(self) -> dict[str, object]:
            return self.value

    class Connection:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def execute(self, *_args: object, **_kwargs: object) -> Result:
            return Result(self.value)

    class Engine:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def connect(self) -> Connection:
            return Connection(self.value)

    _assert_recorded_batch_binding(
        reader_engine=Engine(row),
        opportunity_id=opportunity_id,
        raw_object=raw,
        normalized_object=normalized,
        canonical_dataset_sha256=canonical_hash,
        record_hash=record_hash,
        identity=identity,
        expected_counts=expected_counts,
    )
    tampered = {**row, "raw_terminal_event_hash": "f" * 64}
    with pytest.raises(DataTorrentRuntimeError, match="DATA_TORRENT_BATCH_READBACK_MISMATCH"):
        _assert_recorded_batch_binding(
            reader_engine=Engine(tampered),
            opportunity_id=opportunity_id,
            raw_object=raw,
            normalized_object=normalized,
            canonical_dataset_sha256=canonical_hash,
            record_hash=record_hash,
            identity=identity,
            expected_counts=expected_counts,
        )


def test_ambiguous_provider_dispatch_is_counted_as_one_external_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ledger:
        def __init__(self) -> None:
            self.dispatch_hash = _hex(700)

        def reserve(self, **values: object) -> ExternalEffectPermitReceipt:
            return ExternalEffectPermitReceipt(
                operation_id=_hex(600),
                effect_family="ODDS",
                effect_sequence=cast(int, values["effect_sequence"]),
                request_hash=str(values["request_hash"]),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                created_now=True,
                db_permitted_at=NOW,
                postgres_server_epoch=NOW,
                permit_hash=_hex(601),
            )

        def append(self, **values: object) -> ExternalEffectEventReceipt:
            event_type = str(values["event_type"])
            sequence = 1 if event_type == "DISPATCHED" else 2
            return ExternalEffectEventReceipt(
                operation_id=str(values["operation_id"]),
                event_seq=sequence,
                event_type=event_type,
                actual_official_reads=cast(int, values["actual_official_reads"]),
                actual_odds_requests=cast(int, values["actual_odds_requests"]),
                actual_odds_credits=cast(int, values["actual_odds_credits"]),
                db_recorded_at=NOW,
                postgres_server_epoch=NOW,
                previous_event_hash="0" * 64 if sequence == 1 else self.dispatch_hash,
                event_hash=self.dispatch_hash if sequence == 1 else _hex(701),
            )

    class AmbiguousTransport:
        def __init__(self, **values: object) -> None:
            self.on_dispatch = values.get("on_dispatch")

        def preflight(self, _request: object) -> None:
            pass

        def dispatch(self, _request: object, *, api_key: str) -> None:
            assert api_key == "provider_token_123456"
            assert callable(self.on_dispatch)
            self.on_dispatch()
            raise RuntimeError("NETWORK_OUTCOME_AMBIGUOUS")

    monkeypatch.setattr(
        "robin.data_torrent.sources._resolve_provider_address",
        lambda: "93.184.216.34",
    )
    monkeypatch.setattr(
        "robin.data_torrent.sources.StrictHttpsTransport",
        AmbiguousTransport,
    )
    counters = SourceEffectCounters()
    capture = capture_odds_sources(
        config=load_torrent_config(CONFIG),
        ledger=Ledger(),  # type: ignore[arg-type]
        opportunity_id="2" * 64,
        identity=GitHubRunIdentity(
            github_run_id=99,
            github_run_attempt=1,
            github_sha="1" * 40,
            github_workflow_ref="owner/repo/.github/workflows/data.yml@refs/heads/main",
            github_workflow_sha="1" * 40,
            github_repository="owner/repo",
            github_ref="refs/heads/main",
        ),
        generation_token="3" * 64,
        environment={"THE_ODDS_API_KEY": "provider_token_123456"},
        response_sequence_start=5,
        counters=counters,
        clock=lambda: NOW,
    )
    assert capture.provider_requests == 1
    assert capture.effects[0].terminal.event_type == "AMBIGUOUS"
    assert capture.effects[0].terminal.actual_odds_requests == 1
    assert capture.effects[0].terminal.actual_odds_credits == 200
    assert capture.provider_receipt["provider_requests"] == 1
    assert capture.provider_receipt["credits_used"] == 200
    assert capture.provider_receipt["credit_anomalies"] == [
        {
            "sport_key": "soccer_spain_la_liga",
            "state": "OUTCOME_UNKNOWN_NO_VALID_CREDIT_HEADER",
            "accounted_credits": 200,
        }
    ]
    assert counters.snapshot()["odds_provider_dispatches"] == 1


def test_response_journal_retains_complete_body_before_spool_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = SourceCaptureProgress(spool_directory=tmp_path / "spool")
    monkeypatch.setattr(
        "robin.data_torrent.sources.os.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    with pytest.raises(OSError, match="disk unavailable"):
        progress.observe(
            family="ODDS",
            sport_key="soccer_epl",
            source="https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
            retrieved_at_utc=NOW,
            http_status=200,
            content_type="application/json",
            response_headers={"x-requests-last": "1"},
            body=b'{"complete":true}',
            external_effect_sequence=1,
            external_operation_id=_hex(850),
            permit_hash=_hex(851),
            dispatch_event_hash=_hex(852),
        )
    assert len(progress.observed_responses) == 1
    assert progress.observed_responses[0].body == b'{"complete":true}'
    assert progress.observed_responses[0].sha256 == hashlib.sha256(b'{"complete":true}').hexdigest()


def test_dns_attempt_is_dispatched_and_counted_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Ledger:
        def reserve(self, **values: object) -> ExternalEffectPermitReceipt:
            return ExternalEffectPermitReceipt(
                operation_id=_hex(710),
                effect_family="ODDS",
                effect_sequence=cast(int, values["effect_sequence"]),
                request_hash=str(values["request_hash"]),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                created_now=True,
                db_permitted_at=NOW,
                postgres_server_epoch=NOW,
                permit_hash=_hex(711),
            )

        def append(self, **values: object) -> ExternalEffectEventReceipt:
            event_type = str(values["event_type"])
            events.append(event_type)
            sequence = len(events)
            return ExternalEffectEventReceipt(
                operation_id=str(values["operation_id"]),
                event_seq=sequence,
                event_type=event_type,
                actual_official_reads=cast(int, values["actual_official_reads"]),
                actual_odds_requests=cast(int, values["actual_odds_requests"]),
                actual_odds_credits=cast(int, values["actual_odds_credits"]),
                db_recorded_at=NOW,
                postgres_server_epoch=NOW,
                previous_event_hash="0" * 64 if sequence == 1 else _hex(712),
                event_hash=_hex(712 + sequence - 1),
            )

    def fail_dns() -> str:
        assert events == ["DISPATCHED"]
        raise RuntimeError("DATA_TORRENT_PROVIDER_DNS_FAILED")

    monkeypatch.setattr("robin.data_torrent.sources._resolve_provider_address", fail_dns)
    counters = SourceEffectCounters()
    capture = capture_odds_sources(
        config=load_torrent_config(CONFIG),
        ledger=Ledger(),  # type: ignore[arg-type]
        opportunity_id="2" * 64,
        identity=GitHubRunIdentity(
            github_run_id=99,
            github_run_attempt=1,
            github_sha="1" * 40,
            github_workflow_ref="owner/repo/.github/workflows/data.yml@refs/heads/main",
            github_workflow_sha="1" * 40,
            github_repository="owner/repo",
            github_ref="refs/heads/main",
        ),
        generation_token="3" * 64,
        environment={"THE_ODDS_API_KEY": "provider_token_123456"},
        response_sequence_start=5,
        counters=counters,
        clock=lambda: NOW,
    )
    assert events == ["DISPATCHED", "AMBIGUOUS"]
    assert capture.provider_requests == 0
    assert capture.dns_resolutions == 1
    assert capture.effects[0].terminal.event_type == "AMBIGUOUS"
    assert counters.snapshot() == {
        "official_reads": 0,
        "odds_dns_resolutions": 1,
        "odds_provider_dispatches": 0,
        "odds_credits": 0,
    }


def test_reported_provider_credit_survives_later_ambiguous_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ledger:
        def __init__(self) -> None:
            self.dispatch_hash = _hex(800)

        def reserve(self, **values: object) -> ExternalEffectPermitReceipt:
            return ExternalEffectPermitReceipt(
                operation_id=_hex(801),
                effect_family="ODDS",
                effect_sequence=cast(int, values["effect_sequence"]),
                request_hash=str(values["request_hash"]),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                created_now=True,
                db_permitted_at=NOW,
                postgres_server_epoch=NOW,
                permit_hash=_hex(802),
            )

        def append(self, **values: object) -> ExternalEffectEventReceipt:
            event_type = str(values["event_type"])
            sequence = 1 if event_type == "DISPATCHED" else 2
            return ExternalEffectEventReceipt(
                operation_id=str(values["operation_id"]),
                event_seq=sequence,
                event_type=event_type,
                actual_official_reads=cast(int, values["actual_official_reads"]),
                actual_odds_requests=cast(int, values["actual_odds_requests"]),
                actual_odds_credits=cast(int, values["actual_odds_credits"]),
                db_recorded_at=NOW,
                postgres_server_epoch=NOW,
                previous_event_hash="0" * 64 if sequence == 1 else self.dispatch_hash,
                event_hash=self.dispatch_hash if sequence == 1 else _hex(803),
            )

    class CreditHeaderTransport:
        def __init__(self, **values: object) -> None:
            self.on_dispatch = values.get("on_dispatch")
            self.on_response = values.get("on_response")

        def preflight(self, _request: object) -> None:
            pass

        def dispatch(self, _request: object, *, api_key: str) -> LiveTransportResponse:
            assert api_key == "provider_token_123456"
            assert callable(self.on_dispatch)
            self.on_dispatch()
            response = LiveTransportResponse(
                http_status=200,
                headers={
                    "x-requests-last": "7",
                    "x-requests-used": "invalid",
                    "x-requests-remaining": "993",
                },
                payload=b"[]",
                first_observed_at_utc=NOW,
            )
            assert callable(self.on_response)
            self.on_response(response, True)
            return response

    monkeypatch.setattr(
        "robin.data_torrent.sources._resolve_provider_address",
        lambda: "93.184.216.34",
    )
    monkeypatch.setattr(
        "robin.data_torrent.sources.StrictHttpsTransport",
        CreditHeaderTransport,
    )
    counters = SourceEffectCounters()
    capture = capture_odds_sources(
        config=load_torrent_config(CONFIG),
        ledger=Ledger(),  # type: ignore[arg-type]
        opportunity_id="2" * 64,
        identity=GitHubRunIdentity(
            github_run_id=99,
            github_run_attempt=1,
            github_sha="1" * 40,
            github_workflow_ref="owner/repo/.github/workflows/data.yml@refs/heads/main",
            github_workflow_sha="1" * 40,
            github_repository="owner/repo",
            github_ref="refs/heads/main",
        ),
        generation_token="3" * 64,
        environment={"THE_ODDS_API_KEY": "provider_token_123456"},
        response_sequence_start=5,
        counters=counters,
        clock=lambda: NOW,
    )
    assert capture.effects[0].terminal.event_type == "AMBIGUOUS"
    assert capture.effects[0].terminal.actual_odds_credits == 7
    assert capture.raw_responses[0].provider_credits == 7
    assert capture.credits_used == 7
    assert capture.provider_receipt["credits_used"] == 7
    assert capture.provider_receipt["dns_resolutions"] == 1
    assert counters.snapshot() == {
        "official_reads": 0,
        "odds_dns_resolutions": 1,
        "odds_provider_dispatches": 1,
        "odds_credits": 7,
    }


@pytest.mark.parametrize(
    ("last_header", "expected_state"),
    (("invalid", "UNKNOWN_MALFORMED"), ("201", "OVER_AUTHORIZED_LIMIT")),
)
def test_unknown_provider_credit_is_conservatively_accounted_at_cap(
    monkeypatch: pytest.MonkeyPatch,
    last_header: str,
    expected_state: str,
) -> None:
    class Ledger:
        def reserve(self, **values: object) -> ExternalEffectPermitReceipt:
            return ExternalEffectPermitReceipt(
                operation_id=_hex(820),
                effect_family="ODDS",
                effect_sequence=cast(int, values["effect_sequence"]),
                request_hash=str(values["request_hash"]),
                max_official_reads=0,
                max_odds_requests=1,
                max_odds_credits=200,
                created_now=True,
                db_permitted_at=NOW,
                postgres_server_epoch=NOW,
                permit_hash=_hex(821),
            )

        def append(self, **values: object) -> ExternalEffectEventReceipt:
            event_type = str(values["event_type"])
            sequence = 1 if event_type == "DISPATCHED" else 2
            return ExternalEffectEventReceipt(
                operation_id=str(values["operation_id"]),
                event_seq=sequence,
                event_type=event_type,
                actual_official_reads=cast(int, values["actual_official_reads"]),
                actual_odds_requests=cast(int, values["actual_odds_requests"]),
                actual_odds_credits=cast(int, values["actual_odds_credits"]),
                db_recorded_at=NOW,
                postgres_server_epoch=NOW,
                previous_event_hash="0" * 64 if sequence == 1 else _hex(822),
                event_hash=_hex(822 + sequence - 1),
            )

    class CreditHeaderTransport:
        def __init__(self, **values: object) -> None:
            self.on_dispatch = values.get("on_dispatch")
            self.on_response = values.get("on_response")

        def preflight(self, _request: object) -> None:
            pass

        def dispatch(self, _request: object, *, api_key: str) -> LiveTransportResponse:
            assert api_key == "provider_token_123456"
            assert callable(self.on_dispatch)
            self.on_dispatch()
            response = LiveTransportResponse(
                http_status=200,
                headers={
                    "x-requests-last": last_header,
                    "x-requests-used": "1000",
                    "x-requests-remaining": "1000",
                },
                payload=b"[]",
                first_observed_at_utc=NOW,
            )
            assert callable(self.on_response)
            self.on_response(response, True)
            return response

    monkeypatch.setattr(
        "robin.data_torrent.sources._resolve_provider_address",
        lambda: "93.184.216.34",
    )
    monkeypatch.setattr(
        "robin.data_torrent.sources.StrictHttpsTransport",
        CreditHeaderTransport,
    )
    counters = SourceEffectCounters()
    capture = capture_odds_sources(
        config=load_torrent_config(CONFIG),
        ledger=Ledger(),  # type: ignore[arg-type]
        opportunity_id="2" * 64,
        identity=GitHubRunIdentity(
            github_run_id=99,
            github_run_attempt=1,
            github_sha="1" * 40,
            github_workflow_ref="owner/repo/.github/workflows/data.yml@refs/heads/main",
            github_workflow_sha="1" * 40,
            github_repository="owner/repo",
            github_ref="refs/heads/main",
        ),
        generation_token="3" * 64,
        environment={"THE_ODDS_API_KEY": "provider_token_123456"},
        response_sequence_start=5,
        counters=counters,
        clock=lambda: NOW,
    )
    terminal = capture.effects[0].terminal
    assert terminal.event_type == "AMBIGUOUS"
    assert terminal.actual_odds_requests == 1
    assert terminal.actual_odds_credits == 200
    assert capture.raw_responses[0].provider_credits == 200
    assert capture.credits_used == 200
    assert capture.provider_receipt["credits_used"] == 200
    assert capture.provider_receipt["credit_accounting"] == ("CONSERVATIVE_MAXIMUM_AMBIGUOUS")
    assert capture.provider_receipt["credit_anomalies"][0]["state"] == expected_state
    assert counters.odds_credits == 200
