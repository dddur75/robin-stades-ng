from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

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


def test_segmented_replay_reducer_and_second_pass_are_idempotent(tmp_path) -> None:
    store = InMemoryObjectStore()
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
