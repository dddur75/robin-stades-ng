from __future__ import annotations

import copy
import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import robin.data_torrent.runtime as runtime
from robin.data_torrent.contracts import TorrentBudgets, load_torrent_config
from robin.data_torrent.durability import CountingR2Store
from robin.data_torrent.live_call_graph import (
    LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2,
    LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2,
    render_live_postgresql_call_graph_v2,
    validate_live_postgresql_call_graph_v2,
)
from robin.data_torrent.normalization import NormalizedBatch
from robin.prospective_observatory.chronos_control_plane import (
    ConditionalPutOutcome,
    ConditionalPutResult,
    ObservedObject,
)

MAIN_SHA = "a" * 40
IDENTITY_RUN_ID = "123"


class _Store:
    def __init__(
        self,
        *,
        data: bytes,
        metadata: dict[str, str],
        error: Exception | None = None,
    ) -> None:
        self.data = data
        self.metadata = metadata
        self.error = error
        self.get_calls = 0

    def get_object(self, _key: str) -> ObservedObject:
        self.get_calls += 1
        if self.error is not None:
            raise self.error
        return ObservedObject(data=self.data, metadata=self.metadata)


def _budgets() -> TorrentBudgets:
    return TorrentBudgets(
        official_physical_reads_max=50,
        odds_provider_requests_max=5,
        odds_credits_max=1000,
        automatic_retries=0,
        r2_puts_max=2,
        r2_gets_max=1,
        r2_lists_max=0,
        r2_deletes_max=0,
    )


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: str = "account-a",
    bucket: str = "bucket-a",
) -> tuple[dict[str, str], dict[str, Any], bytes, dict[str, str]]:
    payload = b'{"schema_version":"neon-branch-identity-go-v2"}\n'
    identity_path = tmp_path / runtime.RECOVERY_V2_IDENTITY_ARTIFACT_PATH
    identity_path.parent.mkdir(parents=True)
    identity_path.write_bytes(payload)
    payload_sha = hashlib.sha256(payload).hexdigest()
    store_sha = hashlib.sha256(f"{account}\x00{bucket}".encode()).hexdigest()
    metadata = {
        "schema": "neon-branch-identity-go-v2",
        "sha256": payload_sha,
        "main_sha": MAIN_SHA,
        "identity_run_id": IDENTITY_RUN_ID,
        "artifact_id": "456",
        "archive_sha256": "b" * 64,
        "store_identity_sha256": store_sha,
    }
    binding = {
        "run_id": IDENTITY_RUN_ID,
        "payload_sha256": payload_sha,
        "durable_object_key": "data-torrent-recovery-v2/control-plane/identity.json",
        "durable_metadata": metadata,
        "store_identity_sha256": store_sha,
    }
    seal = {
        "identity_go": binding,
        "effects": {"r2_puts": 1, "r2_gets": 1, "r2_objects_created": 1},
    }
    proof = {"main_sha": MAIN_SHA, "identity_seal": seal}
    environment = {
        "DATA_TORRENT_IDENTITY_ARTIFACT": runtime.RECOVERY_V2_IDENTITY_ARTIFACT_PATH,
        "R2_ACCOUNT_ID": account,
        "R2_BUCKET_NAME": bucket,
    }
    monkeypatch.setattr(
        runtime,
        "validate_neon_branch_identity_go_v2",
        lambda _value, **_kwargs: {"source": {"run_id": IDENTITY_RUN_ID}},
    )
    monkeypatch.setattr(runtime, "validate_identity_seal_v2", lambda value, **_kwargs: value)
    return environment, proof, payload, metadata


def _counting(store: _Store) -> CountingR2Store:
    return CountingR2Store(  # type: ignore[arg-type]
        store,
        _budgets(),
        authority_validator=lambda: None,
    )


def test_live_reads_exact_seal_once_before_any_other_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, proof, payload, metadata = _fixture(tmp_path, monkeypatch)
    base = _Store(data=payload, metadata=metadata)
    store = _counting(base)
    assert (
        runtime._validate_live_identity_seal_readback_v2(
            repository_root=tmp_path,
            environment=environment,
            proof=proof,
            r2_store=store,
        )
        == proof["identity_seal"]
    )
    assert store.gets == base.get_calls == 1
    with pytest.raises(RuntimeError, match="R2_GET_BUDGET_EXCEEDED"):
        store.get_object("second-get-forbidden")
    assert base.get_calls == 1


def test_live_rejects_different_injected_store_before_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, proof, payload, metadata = _fixture(tmp_path, monkeypatch)
    environment["R2_BUCKET_NAME"] = "bucket-b"
    base = _Store(data=payload, metadata=metadata)
    with pytest.raises(runtime.DataTorrentRuntimeError, match="SEAL_V2_MISMATCH"):
        runtime._validate_live_identity_seal_readback_v2(
            repository_root=tmp_path,
            environment=environment,
            proof=proof,
            r2_store=_counting(base),
        )
    assert base.get_calls == 0


@pytest.mark.parametrize("mismatch", ["bytes", "metadata", "sha"])
def test_live_rejects_seal_readback_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    environment, proof, payload, metadata = _fixture(tmp_path, monkeypatch)
    observed_payload = payload + b"drift" if mismatch == "bytes" else payload
    observed_metadata = {**metadata, "schema": "drift"} if mismatch == "metadata" else metadata
    if mismatch == "sha":
        proof["identity_seal"]["identity_go"]["payload_sha256"] = "c" * 64
    base = _Store(data=observed_payload, metadata=observed_metadata)
    with pytest.raises(runtime.DataTorrentRuntimeError, match="MISMATCH"):
        runtime._validate_live_identity_seal_readback_v2(
            repository_root=tmp_path,
            environment=environment,
            proof=proof,
            r2_store=_counting(base),
        )
    assert base.get_calls <= 1


def test_ambiguous_get_consumes_budget_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, proof, payload, metadata = _fixture(tmp_path, monkeypatch)
    base = _Store(data=payload, metadata=metadata, error=RuntimeError("ambiguous"))
    store = _counting(base)
    with pytest.raises(runtime.DataTorrentRuntimeError, match="GET_AMBIGUOUS"):
        runtime._validate_live_identity_seal_readback_v2(
            repository_root=tmp_path,
            environment=environment,
            proof=proof,
            r2_store=store,
        )
    assert store.gets == base.get_calls == 1
    with pytest.raises(RuntimeError, match="R2_GET_BUDGET_EXCEEDED"):
        store.get_object("retry")
    assert base.get_calls == 1


def test_missing_seal_object_consumes_budget_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment, proof, payload, metadata = _fixture(tmp_path, monkeypatch)
    base = _Store(data=payload, metadata=metadata)

    def missing(_key: str) -> None:
        base.get_calls += 1
        return None

    monkeypatch.setattr(base, "get_object", missing)
    store = _counting(base)
    with pytest.raises(runtime.DataTorrentRuntimeError, match="READBACK_MISMATCH"):
        runtime._validate_live_identity_seal_readback_v2(
            repository_root=tmp_path,
            environment=environment,
            proof=proof,
            r2_store=store,
        )
    assert store.gets == base.get_calls == 1
    with pytest.raises(RuntimeError, match="R2_GET_BUDGET_EXCEEDED"):
        store.get_object("retry")
    assert base.get_calls == 1


def test_v2_r2_totals_and_postgresql_bound_are_exactly_materialized() -> None:
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        proof = {
            "identity_seal": {"effects": {"r2_puts": 1, "r2_gets": 1, "r2_objects_created": 1}}
        }
        assert runtime._mission_r2_counters(
            proof=proof,
            live_counters={"puts": 2, "gets": 1, "lists": 0, "deletes": 0},
            live_objects=2,
        ) == {"puts": 3, "gets": 3, "lists": 0, "deletes": 0, "objects": 3, "overwrites": 0}
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)
    effects = runtime.LiveRuntimeEffects(
        postgresql_connection_attempts_maximum=(
            runtime.LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2
        )
    )
    for _ in range(runtime.LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2):
        effects.begin_function_call(mutating=False)
    with pytest.raises(runtime.DataTorrentRuntimeError, match="CONNECTION_BUDGET_EXCEEDED"):
        effects.begin_read_transaction()


def test_live_failure_effect_receipt_counts_returned_ambiguous_r2_put() -> None:
    class AmbiguousStore:
        def put_if_absent(
            self,
            _key: str,
            _data: bytes,
            *,
            metadata: dict[str, str],
            on_dispatch: Any,
        ) -> ConditionalPutResult:
            del metadata
            on_dispatch()
            return ConditionalPutResult(ConditionalPutOutcome.AMBIGUOUS)

    store = CountingR2Store(  # type: ignore[arg-type]
        AmbiguousStore(),
        _budgets(),
        authority_validator=lambda: None,
    )
    result = store.put_if_absent("key", b"payload", metadata={}, on_dispatch=lambda: None)
    assert result.outcome is ConditionalPutOutcome.AMBIGUOUS
    receipt = runtime.LiveRuntimeEffects(r2_store=store).snapshot()
    assert receipt["r2"]["puts_attempted"] == 1
    assert receipt["r2"]["put_outcomes_ambiguous_upper_bound"] == 1


def test_v2_config_requires_exactly_one_hundred_replay_iterations(tmp_path: Path) -> None:
    source = Path("configs/data/torrent-live-v2.json")
    document = json.loads(source.read_text(encoding="utf-8"))
    assert load_torrent_config(source).replay_multiplier == 100
    for multiplier in (99, 101):
        document["replay"]["multiplier"] = multiplier
        candidate = tmp_path / f"config-{multiplier}.json"
        candidate.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(ValueError, match="CONFIG_BOUNDS_INVALID"):
            load_torrent_config(candidate)


def test_live_call_order_places_seal_before_postgresql_and_providers() -> None:
    source = inspect.getsource(runtime._execute_data_torrent)
    seal = source.index("_validate_live_identity_seal_readback_v2")
    database = source.index('authority_url = _required(env, "CHRONOS_AUTHORITY_DATABASE_URL")')
    official = source.index("capture_official_sources(")
    odds = source.index("capture_odds_sources(")
    assert seal < database < official < odds
    assert "require_created=_contract().require_created" in source
    assert "require_created=True" in source


def test_live_postgresql_call_graph_is_generated_and_bounded() -> None:
    root = Path.cwd()
    document = validate_live_postgresql_call_graph_v2(root)
    derived = document["derived"]
    assert LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_NOMINAL_V2 == 51
    assert LIVE_POSTGRESQL_CONNECTION_ATTEMPTS_UPPER_BOUND_V2 == 53
    assert derived == {
        "direct_read_connections": 6,
        "function_read_connections_nominal": 4,
        "function_read_transition_fallback_connections_maximum": 2,
        "mutating_function_connections": 41,
        "postgresql_connection_attempts_nominal": 51,
        "postgresql_connection_attempts_maximum": 53,
        "first_refused_attempt": 54,
        "automatic_retries": 0,
    }
    path = root / "configs/execution/data-torrent-live-v2-postgresql-call-graph.json"
    assert path.read_bytes() == render_live_postgresql_call_graph_v2()


def test_v2_replay_executes_exactly_one_hundred_iterations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = b'{"record_id":"one"}\n'
    batch = NormalizedBatch(
        records=({"record_id": "one"},),
        rejects=(),
        coverage=(),
        raw_events_observed=1,
        raw_events_accounted=1,
        silent_drops=0,
        logical_duplicates=0,
        temporal_leakage=0,
        canonical_dataset_sha256=hashlib.sha256(canonical).hexdigest(),
        canonical_dataset_bytes=canonical,
        rejects_bytes=b"",
    )
    calls = 0

    def replay_once(**_arguments: Any) -> tuple[NormalizedBatch, int]:
        nonlocal calls
        calls += 1
        return batch, 7

    monkeypatch.setattr(runtime, "_replay_archive_once", replay_once)
    config = replace(
        load_torrent_config(Path("configs/data/torrent-live-v2.json")), minimum_throughput_ratio=0.0
    )
    started = datetime(2026, 8, 30, tzinfo=UTC)
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        measurement = runtime._measure_replay(
            config=config,
            raw_archive=b"retained-durable-bytes",
            raw_archive_sha256="a" * 64,
            league_names={},
            team_aliases={},
            run_identity="run",
            claim_identity="claim",
            anchor=started,
            reconciliation_observed_at=started,
            original=batch,
            capture_started=started,
            capture_ended=started + timedelta(seconds=1),
            counter_snapshot=lambda: {"all_external_effects": 0},
            normalized_durable_binding={"terminal_event": "CREATED_CONFIRMED"},
        )
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)
    assert calls == 100
    assert measurement.report["replay"]["iterations_completed"] == 100
    assert measurement.report["external_effects_delta"] == {"all_external_effects": 0}
    fingerprint = runtime._normalized_batch_fingerprint(batch)
    assert measurement.report["input"]["normalized_batch_fingerprint"] == fingerprint
    assert measurement.report["measurement"]["unique_normalized_batch_fingerprints"] == [
        fingerprint
    ]


def test_v2_replay_rejects_reject_reason_drift_with_unchanged_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = b'{"record_id":"one"}\n'
    batch = NormalizedBatch(
        records=({"record_id": "one"},),
        rejects=(),
        coverage=(),
        raw_events_observed=1,
        raw_events_accounted=1,
        silent_drops=0,
        logical_duplicates=0,
        temporal_leakage=0,
        canonical_dataset_sha256=hashlib.sha256(canonical).hexdigest(),
        canonical_dataset_bytes=canonical,
        rejects_bytes=b"",
    )
    reject = {"response_id": "one", "reason": "MUTATED_REASON"}
    drifted = replace(
        batch,
        rejects=(reject,),
        rejects_bytes=runtime.canonical_json_bytes(reject) + b"\n",
    )
    calls = 0

    def replay_once(**_arguments: Any) -> tuple[NormalizedBatch, int]:
        nonlocal calls
        calls += 1
        return (drifted if calls == 50 else batch), 7

    monkeypatch.setattr(runtime, "_replay_archive_once", replay_once)
    config = replace(
        load_torrent_config(Path("configs/data/torrent-live-v2.json")),
        minimum_throughput_ratio=0.0,
    )
    started = datetime(2026, 8, 30, tzinfo=UTC)
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        with pytest.raises(
            runtime.DataTorrentRuntimeError, match="DATA_TORRENT_REPLAY_BATCH_DRIFT"
        ):
            runtime._measure_replay(
                config=config,
                raw_archive=b"retained-durable-bytes",
                raw_archive_sha256="a" * 64,
                league_names={},
                team_aliases={},
                run_identity="run",
                claim_identity="claim",
                anchor=started,
                reconciliation_observed_at=started,
                original=batch,
                capture_started=started,
                capture_ended=started + timedelta(seconds=1),
                counter_snapshot=lambda: {"all_external_effects": 0},
                normalized_durable_binding={"terminal_event": "CREATED_CONFIRMED"},
            )
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)
    assert calls == 50


def test_v2_terminal_verifier_performs_no_additional_replay_iteration() -> None:
    source = inspect.getsource(runtime._verify_terminal_artifact_semantics_v2)
    assert "_replay_archive_once" not in source
    assert "range(" not in source


def _replay_arithmetic_case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = b'{"record_id":"one"}\n'
    batch = NormalizedBatch(
        records=({"record_id": "one"},),
        rejects=(),
        coverage=(),
        raw_events_observed=1,
        raw_events_accounted=1,
        silent_drops=0,
        logical_duplicates=0,
        temporal_leakage=0,
        canonical_dataset_sha256=hashlib.sha256(canonical).hexdigest(),
        canonical_dataset_bytes=canonical,
        rejects_bytes=b"",
    )
    monkeypatch.setattr(runtime, "_replay_archive_once", lambda **_kwargs: (batch, 7))
    config = replace(
        load_torrent_config(Path("configs/data/torrent-live-v2.json")),
        minimum_throughput_ratio=0.0,
    )
    started = datetime(2026, 8, 30, tzinfo=UTC)
    ended = started + timedelta(seconds=1)
    binding = {"terminal_event": "CREATED_CONFIRMED"}
    measurement = runtime._measure_replay(
        config=config,
        raw_archive=b"retained-durable-bytes",
        raw_archive_sha256="a" * 64,
        league_names={},
        team_aliases={},
        run_identity="run",
        claim_identity="claim",
        anchor=started,
        reconciliation_observed_at=started,
        original=batch,
        capture_started=started,
        capture_ended=ended,
        counter_snapshot=lambda: {
            "official_reads": 0,
            "odds_dns_resolutions": 0,
            "odds_provider_dispatches": 0,
            "odds_credits": 0,
            "r2_puts": 0,
            "r2_gets": 0,
            "r2_lists": 0,
            "r2_deletes": 0,
            "postgresql_read_transactions": 0,
            "postgresql_function_reads": 0,
            "postgresql_mutating_function_calls": 0,
        },
        normalized_durable_binding=binding,
    )
    measurement.report["cross_run_loser_contract_proof"] = {"proof": "post-merge"}
    measurement.report["chronos_release_chain_proof"] = {"proof": "chronos"}
    arguments: dict[str, Any] = {
        "config": config,
        "raw_archive_sha256": "a" * 64,
        "raw_bytes_per_iteration": 7,
        "normalized_binding": binding,
        "canonical_dataset_sha256": batch.canonical_dataset_sha256,
        "normalized_batch_fingerprint": runtime._normalized_batch_fingerprint(batch),
        "normalized_records_per_iteration": 1,
        "rejected_records_per_iteration": 0,
        "logical_duplicates": 0,
        "silent_losses": 0,
        "capture_started": started,
        "capture_ended": ended,
    }
    return measurement.report, arguments


def test_v2_replay_arithmetic_accepts_exact_measured_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        replay, arguments = _replay_arithmetic_case(monkeypatch)
        verified = runtime._verify_replay_arithmetic_v2(replay=replay, **arguments)
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)
    assert verified["minimum_ratio"] == replay["throughput"]["minimum_ratio"]
    assert replay["input"]["replay_source"] == (
        "LOCALLY_RETAINED_RAW_ARCHIVE_BYTES_AFTER_RAW_AND_NORMALIZED_CREATED_CONFIRMED"
    )


@pytest.mark.parametrize(
    ("section", "key", "mutation"),
    [
        ("measurement", "records_per_second", "increment"),
        ("measurement", "p95_latency_ms", "negative"),
        ("measurement", "peak_memory_bytes", "below_baseline"),
        ("measurement", "rejects", "increment"),
        ("acceptance", "throughput_pass", "delete"),
        ("acceptance", "throughput_pass", "false"),
        ("external_effects_delta", "official_reads", "increment"),
    ],
)
def test_v2_replay_arithmetic_rejects_each_mutated_predicate(
    section: str,
    key: str,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = runtime._RUNTIME_CONTRACT.set(runtime._V2_RUNTIME_CONTRACT)
    try:
        valid, arguments = _replay_arithmetic_case(monkeypatch)
        replay = copy.deepcopy(valid)
        target = replay[section]
        if mutation == "delete":
            del target[key]
        elif mutation == "increment":
            target[key] += 1
        elif mutation == "negative":
            target[key] = -1.0
        elif mutation == "below_baseline":
            target[key] = target["baseline_rss_bytes"] - 1
        elif mutation == "false":
            target[key] = False
        else:
            raise AssertionError(mutation)
        with pytest.raises(
            runtime.DataTorrentRuntimeError,
            match="DATA_TORRENT_TERMINAL_SEMANTIC_QA_FAILED",
        ):
            runtime._verify_replay_arithmetic_v2(replay=replay, **arguments)
    finally:
        runtime._RUNTIME_CONTRACT.reset(token)
