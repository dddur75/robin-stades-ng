from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep

import pytest

from robin.historical_deep.contracts import (
    CompetitionSpec,
    DataFamily,
    HarvestTask,
    TaskStatus,
    TemporalClass,
)
from robin.historical_deep.runtime import DurableRuntimeLedger
from robin.historical_deep.segmented_replay import (
    audit_and_reconcile,
    build_replay_inventory,
    build_segment_batches,
    diagnose_inventory_task,
    reduce_segments,
    replay_segment,
)
from robin.historical_deep.storage import InMemoryObjectStore, R2FirstRepository

NOW = datetime(2026, 7, 31, 15, 0, tzinfo=UTC)
COMPETITION = CompetitionSpec(
    canonical_key="api-football:61",
    name="Ligue 1",
    provider_league_id=61,
)


class CountingObjectStore(InMemoryObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.iter_keys_calls = 0
        self.get_object_calls = 0
        self.parallel_probe_enabled = False
        self.active_gets = 0
        self.max_active_gets = 0
        self.get_lock = Lock()

    def get_object(self, key: str) -> bytes | None:
        self.get_object_calls += 1
        if not self.parallel_probe_enabled:
            return super().get_object(key)
        with self.get_lock:
            self.active_gets += 1
            self.max_active_gets = max(self.max_active_gets, self.active_gets)
        try:
            sleep(0.002)
            return super().get_object(key)
        finally:
            with self.get_lock:
                self.active_gets -= 1

    def iter_keys(self, prefix: str) -> Iterable[str]:
        self.iter_keys_calls += 1
        return super().iter_keys(prefix)


def _task(*, fixture_id: int) -> HarvestTask:
    return HarvestTask.create(
        campaign_id="historical-deep-data-harvest-v1",
        competition=COMPETITION,
        season=2025,
        family=DataFamily.FIXTURES,
        endpoint="/fixtures",
        temporal_class=TemporalClass.POST_MATCH_ONLY,
        params={"ids": str(fixture_id), "league": 61, "season": 2025},
    )


def _payload(fixture_id: int) -> dict[str, object]:
    return {
        "response": [
            {
                "fixture": {
                    "id": fixture_id,
                    "date": f"2025-08-{fixture_id:02d}T19:00:00+00:00",
                    "venue": {"id": 10, "name": "Stade", "city": "Paris"},
                    "referee": "Referee, FR",
                    "status": {"short": "FT"},
                },
                "league": {"id": 61, "season": 2025, "round": "Round 1"},
                "teams": {
                    "home": {"id": 1, "name": "Home"},
                    "away": {"id": 2, "name": "Away"},
                },
                "goals": {"home": 1, "away": 0},
                "score": {"fulltime": {"home": 1, "away": 0}},
            }
        ]
    }


def _coverage_task() -> HarvestTask:
    return HarvestTask.create(
        campaign_id="historical-deep-data-harvest-v1",
        competition=COMPETITION,
        season=2025,
        family=DataFamily.FIXTURES,
        endpoint="/leagues",
        temporal_class=TemporalClass.POST_MATCH_ONLY,
        params={"id": 61, "season": 2025},
    )


def _coverage_payload() -> dict[str, object]:
    return {
        "response": [
            {
                "league": {"id": 61, "name": "Ligue 1"},
                "country": {"name": "France"},
                "seasons": [
                    {
                        "year": 2025,
                        "coverage": {"fixtures": {"events": True}},
                    }
                ],
            }
        ]
    }


def _journal_running(
    repository: R2FirstRepository,
    task: HarvestTask,
    *,
    started_at: datetime,
) -> None:
    repository.record_task_attempt(
        task=task,
        attempt_number=1,
        status=TaskStatus.PENDING,
        started_at=started_at,
        recorded_at=started_at,
    )
    repository.record_task_attempt(
        task=task,
        attempt_number=1,
        status=TaskStatus.RUNNING,
        started_at=started_at,
        recorded_at=started_at,
    )


def test_audit_reconciles_receipts_stale_running_and_failed_without_provider() -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    for fixture_id in (1, 2):
        task = _task(fixture_id=fixture_id)
        repository.capture(
            task=task,
            payload=_payload(fixture_id),
            requested_at=NOW - timedelta(minutes=40),
            received_at=NOW - timedelta(minutes=39),
            source_commit="test",
        )
    stale = _task(fixture_id=3)
    _journal_running(repository, stale, started_at=NOW - timedelta(minutes=30))
    failed = _task(fixture_id=4)
    _journal_running(repository, failed, started_at=NOW - timedelta(minutes=20))
    repository.record_task_attempt(
        task=failed,
        attempt_number=1,
        status=TaskStatus.FAILED,
        started_at=NOW - timedelta(minutes=20),
        recorded_at=NOW - timedelta(minutes=19),
        attempts=1,
        provider_calls=1,
        error=RuntimeError("API_FOOTBALL_TRANSPORT_FAILED"),
    )

    audit = audit_and_reconcile(
        repository,
        ledger,
        continuation_id="continuation-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
    )

    assert audit["tasks_total"] == 4
    assert audit["tasks_complete"] == 2
    assert audit["tasks_retryable"] == 1
    assert audit["tasks_pending"] == 1
    assert audit["tasks_failed"] == 0
    assert audit["tasks_running_stale"] == 0
    assert audit["stale_tasks_recovered"] == 1
    assert audit["tasks_reset_pending"] == 1
    assert audit["tasks_recalled"] == 0


def test_audit_object_store_scans_are_bounded_by_passes_not_tasks() -> None:
    store = CountingObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    for fixture_id in range(1, 41):
        task = _task(fixture_id=fixture_id)
        captured = repository.capture(
            task=task,
            payload=_payload(fixture_id),
            requested_at=NOW - timedelta(minutes=40),
            received_at=NOW - timedelta(minutes=39),
            source_commit="test",
        )
        _journal_running(
            repository,
            task,
            started_at=NOW - timedelta(minutes=40),
        )
        repository.record_task_attempt(
            task=task,
            attempt_number=1,
            status=TaskStatus.COMPLETE,
            started_at=NOW - timedelta(minutes=40),
            recorded_at=NOW - timedelta(minutes=39),
            attempts=1,
            provider_calls=1,
            payload_hash=captured.receipt.payload_sha256,
            r2_key=captured.receipt.payload_key,
            rows_normalized=captured.receipt.rows_normalized,
            rows_received=captured.receipt.rows_normalized,
        )

    store.iter_keys_calls = 0
    store.get_object_calls = 0
    store.parallel_probe_enabled = True
    audit = audit_and_reconcile(
        repository,
        ledger,
        continuation_id="continuation-scan-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
    )

    assert audit["tasks_complete"] == 40
    assert audit["write_ahead_receipts_verified"] == 0
    assert store.iter_keys_calls <= 12
    assert store.get_object_calls <= 85
    assert store.max_active_gets >= 2

    store.max_active_gets = 0
    inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-scan-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
    )
    assert inventory["objects_expected"] == 40
    assert store.max_active_gets >= 2


def test_segment_batches_preserve_all_segments_below_github_matrix_limit() -> None:
    segment_ids = [f"seg-{index:06d}-abcdef0123456789" for index in range(371)]

    batches = build_segment_batches(segment_ids)

    assert len(batches) == 186
    assert all(
        len(json.loads(batch["segment_ids_json"])) <= 2 for batch in batches
    )
    assert [
        segment_id
        for batch in batches
        for segment_id in json.loads(batch["segment_ids_json"])
    ] == segment_ids
    oversized = [f"seg-{index:06d}-fedcba9876543210" for index in range(513)]
    with pytest.raises(ValueError, match="REPLAY_SEGMENT_MATRIX_LIMIT_EXCEEDED"):
        build_segment_batches(oversized)


def test_replay_verifies_league_census_without_projecting_fixture_rows(
    tmp_path,
) -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    repository.capture(
        task=_coverage_task(),
        payload=_coverage_payload(),
        requested_at=NOW - timedelta(minutes=2),
        received_at=NOW - timedelta(minutes=1),
        source_commit="test",
    )
    inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-census-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
    )

    result = replay_segment(
        ledger,
        inventory=inventory,
        segment_id=inventory["segments"][0]["segment_id"],
        pass_id=1,
        output_dir=tmp_path / "census",
    )

    assert result["manifest"]["objects_verified"] == 1
    assert result["manifest"]["row_count"] == 0
    assert len(result["entries"]) == 1
    assert result["rows"] == []
    assert ledger.normalized_records() == ([], ())


def test_replay_diagnostic_emits_structure_and_error_without_raw_values(
    tmp_path,
) -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    task = _task(fixture_id=9)
    secret_value = "DO_NOT_EMIT_RAW_PROVIDER_VALUE"
    repository.capture(
        task=task,
        payload={
            "api_secret": secret_value,
            "response": [
                {
                    "fixture": {"id": None, "token": secret_value},
                    "note": secret_value,
                }
            ],
        },
        requested_at=NOW - timedelta(minutes=2),
        received_at=NOW - timedelta(minutes=1),
        source_commit="test",
    )
    inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-diagnostic-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
    )

    diagnostic = diagnose_inventory_task(
        ledger,
        inventory=inventory,
        task_id=task.task_id,
    )

    assert diagnostic["normalization_status"] == "NORMALIZATION_ERROR_IDENTIFIED"
    assert diagnostic["normalization_error"] == "FIXTURE_PROVIDER_ID_REQUIRED"
    assert diagnostic["receipt_time_order_valid"] is True
    assert diagnostic["provider_calls"] == 0
    assert diagnostic["raw_values_emitted"] is False
    shape = diagnostic["payload_shape"]
    assert shape["records"] == 1
    assert shape["integer_fixture_ids"] == 0
    assert shape["first_invalid_fixture_index"] == 0
    assert shape["top_level_keys"] == {
        "total": 2,
        "safe": ["response"],
        "redacted": 1,
    }
    assert shape["first_invalid_fixture_keys"] == {
        "total": 2,
        "safe": ["id"],
        "redacted": 1,
    }
    assert secret_value not in json.dumps(diagnostic, sort_keys=True)
    with pytest.raises(
        ValueError,
        match=(
            rf"REPLAY_NORMALIZATION_FAILED:{task.task_id}:"
            r"FIXTURE_PROVIDER_ID_REQUIRED"
        ),
    ):
        replay_segment(
            ledger,
            inventory=inventory,
            segment_id=inventory["segments"][0]["segment_id"],
            pass_id=1,
            output_dir=tmp_path / "diagnostic-failure",
        )


def test_replay_diagnostic_identifies_only_null_venue_without_raw_values(
    tmp_path,
) -> None:
    store = InMemoryObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    task = _task(fixture_id=9)
    repository.capture(
        task=task,
        payload={
            "response": [
                {
                    "fixture": {
                        "id": 9,
                        "venue": {"id": None, "name": None, "city": None},
                    }
                }
            ]
        },
        requested_at=NOW - timedelta(minutes=2),
        received_at=NOW - timedelta(minutes=1),
        source_commit="test",
    )
    inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-diagnostic-venue-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="101:1",
        now=NOW,
    )

    diagnostic = diagnose_inventory_task(
        ledger,
        inventory=inventory,
        task_id=task.task_id,
    )

    assert diagnostic["normalization_error"] == "MISSING_IDENTITY:venue"
    shape = diagnostic["payload_shape"]
    assert shape["nested_venue_mappings"] == 1
    assert shape["venue_provider_identities"] == 0
    assert shape["venue_derived_identities"] == 0
    assert shape["venue_unidentifiable"] == 1
    assert shape["venue_unidentifiable_all_null_or_empty"] == 1
    assert shape["first_unidentifiable_venue_index"] == 0
    assert shape["first_unidentifiable_venue_keys"] == {
        "total": 3,
        "safe": ["city", "id", "name"],
        "redacted": 0,
    }


def test_segmented_replay_reducer_and_second_pass_are_idempotent(tmp_path) -> None:
    store = CountingObjectStore()
    repository = R2FirstRepository(store)
    ledger = DurableRuntimeLedger(store)
    for fixture_id in (1, 2):
        repository.capture(
            task=_task(fixture_id=fixture_id),
            payload=_payload(fixture_id),
            requested_at=NOW - timedelta(minutes=40),
            received_at=NOW - timedelta(minutes=39),
            source_commit="test",
        )
    inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:1",
        now=NOW,
        max_objects=1,
    )
    assert inventory["objects_expected"] == 2
    assert inventory["segments_expected"] == 2
    retried_inventory = build_replay_inventory(
        ledger,
        continuation_id="continuation-test",
        continuation_of="30622258001:1",
        run_purpose="P0_CLOSURE_AND_SHARDED_REPLAY",
        code_revision="test-revision",
        run_token="100:2",
        now=NOW + timedelta(hours=1),
        max_objects=1,
    )
    assert retried_inventory["manifest_sha256"] == inventory["manifest_sha256"]

    store.parallel_probe_enabled = True
    store.max_active_gets = 0
    for pass_id in (1, 2):
        pass_root = tmp_path / f"pass-{pass_id}"
        for definition in inventory["segments"]:
            replay_segment(
                ledger,
                inventory=inventory,
                segment_id=definition["segment_id"],
                pass_id=pass_id,
                output_dir=pass_root / definition["segment_id"],
            )
        report = reduce_segments(
            ledger,
            inventory=inventory,
            segments_root=pass_root,
            pass_id=pass_id,
            idempotent=pass_id == 2,
            code_revision="test-revision",
            run_token="100:1",
            now=NOW + timedelta(minutes=pass_id),
        )
        if pass_id == 1:
            first = report
            assert report["status"] == "REPLAY_REDUCED"
            assert report["new_inserts"] == report["rows"]
            replay_proof = ledger.latest_value("replay")
            assert isinstance(replay_proof, dict)
            assert all(
                set(entry)
                == {
                    "receipt_id",
                    "payload_key",
                    "payload_sha256",
                    "projection_sha256",
                }
                for entry in replay_proof["entries"]
            )
            assert report["gates"] == [
                "CURRENT_R2_REPLAY_VERIFIED",
                "CURRENT_PROJECTION_RECONSTRUCTED",
            ]
        else:
            assert report["status"] == "SECOND_PASS_IDEMPOTENT"
            assert report["new_inserts"] == 0
            assert report["duplicates_avoided"] == report["rows"]
            assert report["global_hash"] == first["global_hash"]
            assert "CURRENT_SECOND_PASS_IDEMPOTENT" in report["gates"]
            assert report["provider_calls"] == 0
    assert store.max_active_gets >= 2
