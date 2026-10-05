from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import threading
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import robin.capture.real_data_explorer as explorer_module
from robin.capture.real_data_dashboard import (
    build_dashboard_snapshot,
    render_dashboard_csv,
    render_dashboard_html,
)
from robin.capture.real_data_explorer import (
    AtomicExplorerStore,
    BundleValidationError,
    DownloadedArtifact,
    ExplorerRefreshController,
    GhArtifactClient,
    make_server,
    run_refresh_loop,
    validate_source_bundle,
)
from robin.capture.recurring_real_data import RECURRING_CLAIM_IDS

NOW = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
_REAL_SOCKET = socket.socket
_REAL_CREATE_CONNECTION = socket.create_connection
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_GETHOSTBYADDR = socket.gethostbyaddr


def _private_report(*, run_id: int, slot: datetime, price: float) -> dict[str, object]:
    slot_text = slot.isoformat().replace("+00:00", "Z")
    captured = (slot + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    return {
        "mission_id": "ROBIN_AUTONOMOUS_LAB_20261004",
        "claim_ids": list(RECURRING_CLAIM_IDS),
        "repository_sha": "a" * 40,
        "github_run_id": str(run_id),
        "slot_start_utc": slot_text,
        "generated_at_utc": captured,
        "status": "REAL_DATA_PARTIAL",
        "branches": [
            {
                "sport_key": "soccer_epl",
                "status": "PARTIAL",
                "row_count": 1,
                "limitations": [],
                "diagnostic": None,
            }
        ],
        "rows": [
            {
                "slot_start_utc": slot_text,
                "sport_key": "soccer_epl",
                "capture_time_utc": captured,
                "source_timestamp_utc": captured,
                "event_id": "event-1",
                "match": "Arsenal — Leeds United",
                "kickoff_utc": "2026-10-10T11:30:00Z",
                "bookmaker_key": "book-a",
                "bookmaker": "Book A",
                "market_key": "h2h",
                "outcome": "Arsenal",
                "point": None,
                "price": price,
                "quota_remaining": 19_900,
            }
        ],
        "validated_capture_count": 1,
        "incomplete_branch_count": 0,
        "capture_times_utc": [captured],
        "accounting": {
            "rolling_24h_requests": 5,
            "rolling_24h_credits": 10,
            "rolling_30d_requests": 5,
            "rolling_30d_credits": 10,
            "lifetime_requests": 5,
            "lifetime_credits": 10,
        },
    }


def _bundle(
    root: Path,
    *,
    run_id: int,
    slot: datetime,
    price: float,
    delivery_run_id: int | None = None,
) -> Path:
    root.mkdir(parents=True)
    snapshot = build_dashboard_snapshot(
        _private_report(run_id=run_id, slot=slot, price=price),
        previous_report=None,
        generated_at=slot + timedelta(minutes=11),
    )
    normalized = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    csv_payload = render_dashboard_csv(snapshot)
    html_payload = render_dashboard_html(snapshot, csv_filename="robin-real-data.csv")
    (root / "robin-real-data.json").write_bytes(normalized)
    (root / "robin-real-data.csv").write_bytes(csv_payload)
    (root / "robin-real-data.html").write_bytes(html_payload)
    receipt = {
        "schema_version": "robin-autonomous-lab-public-receipt-v1",
        "mission_id": "ROBIN_AUTONOMOUS_LAB_20261004",
        "github_run_id": str(run_id),
        "delivery_github_run_id": str(delivery_run_id or run_id),
        "slot_start_utc": slot.isoformat().replace("+00:00", "Z"),
        "normalized_json_sha256": hashlib.sha256(normalized).hexdigest(),
        "csv_sha256": hashlib.sha256(csv_payload).hexdigest(),
        "html_sha256": hashlib.sha256(html_payload).hexdigest(),
    }
    (root / "public-receipt.json").write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    return root


def test_source_bundle_rejects_corruption_and_unknown_schema(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0)
    assert validate_source_bundle(source).run_id == "10"
    (source / "robin-real-data.csv").write_text("corrupted", encoding="utf-8")

    with pytest.raises(BundleValidationError, match="SOURCE_HASH_MISMATCH"):
        validate_source_bundle(source)


@pytest.mark.parametrize(
    ("receipt_field", "value", "error"),
    [
        ("mission_id", "OTHER_MISSION", "SOURCE_MISSION_MISMATCH"),
        ("github_run_id", "99", "SOURCE_ORIGIN_RUN_MISMATCH"),
        ("slot_start_utc", "2026-10-05T15:00:00Z", "SOURCE_SLOT_MISMATCH"),
    ],
)
def test_source_bundle_binds_receipt_identities_to_snapshot(
    tmp_path: Path, receipt_field: str, value: str, error: str
) -> None:
    source = _bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0)
    receipt_path = source / "public-receipt.json"
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt[receipt_field] = value
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    with pytest.raises(BundleValidationError, match=error):
        validate_source_bundle(source)


def test_source_bundle_binds_download_run_and_rejects_carry_forward(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "10", run_id=10, slot=NOW, price=2.0)
    with pytest.raises(BundleValidationError, match="SOURCE_DELIVERY_RUN_MISMATCH"):
        validate_source_bundle(source, expected_delivery_run_id="11")

    snapshot_path = source / "robin-real-data.json"
    snapshot = json.loads(snapshot_path.read_text("utf-8"))
    snapshot["data_role"] = "CARRY_FORWARD_STALE"
    normalized = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    snapshot_path.write_bytes(normalized)
    receipt_path = source / "public-receipt.json"
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["normalized_json_sha256"] = hashlib.sha256(normalized).hexdigest()
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    with pytest.raises(BundleValidationError, match="SOURCE_CARRY_FORWARD_STALE"):
        validate_source_bundle(source, expected_delivery_run_id="10")


def test_atomic_publish_keeps_last_known_good_after_interrupted_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    first = _bundle(tmp_path / "first", run_id=10, slot=NOW, price=2.0)
    second = _bundle(tmp_path / "second", run_id=11, slot=NOW + timedelta(hours=2), price=2.2)
    store.publish(first)
    pointer_before = store.current_pointer()

    monkeypatch.setattr(store, "_switch_pointer", lambda _pointer: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        store.publish(second)

    assert store.current_pointer() == pointer_before
    assert store.read_public("robin-real-data.json")["github_run_id"] == "10"


def test_late_artifact_cannot_replace_latest_and_history_stays_pinned(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    older = _bundle(tmp_path / "older", run_id=10, slot=NOW, price=2.0)
    newer = _bundle(tmp_path / "newer", run_id=11, slot=NOW + timedelta(hours=2), price=2.2)
    store.publish(older)
    old_html = store.read_public_bytes("robin-real-data.html", run_id="10")
    store.publish(newer)

    with pytest.raises(BundleValidationError, match="LATE_ARTIFACT"):
        store.publish(older)

    assert store.current_pointer()["run_id"] == "11"
    assert store.read_public_bytes("robin-real-data.html", run_id="10") == old_html
    current = store.read_public("robin-real-data.json")
    assert current["price_movement"]["changed_offer_count"] == 1


def test_legacy_history_is_republished_with_current_renderer_without_moving_latest(
    tmp_path: Path,
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    older = _bundle(tmp_path / "older", run_id=10, slot=NOW, price=2.0)
    newer = _bundle(tmp_path / "newer", run_id=11, slot=NOW + timedelta(hours=2), price=2.2)
    store.publish(older)
    historical_json = store.read_public_bytes("robin-real-data.json", run_id="10")
    store.publish(newer)
    older_root = store.versions / "run-10-view-v10"
    legacy_root = store.versions / "run-10-view-v2"
    older_root.rename(legacy_root)
    legacy_manifest_path = legacy_root / "manifest.json"
    legacy_manifest = json.loads(legacy_manifest_path.read_text("utf-8"))
    legacy_manifest["renderer_revision"] = "v2"
    legacy_manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")
    pointer_before = store.current_pointer()

    historical_html = store.read_public_bytes("robin-real-data.html", run_id="10")

    assert b'id="new-run-notice"' in historical_html
    assert store.read_public_bytes("robin-real-data.json", run_id="10") == historical_json
    assert store.current_pointer() == pointer_before
    assert (store.versions / "run-10-view-v10").is_dir()


def test_local_manifest_is_verified_after_restart_and_before_every_read(tmp_path: Path) -> None:
    root = tmp_path / "store"
    store = AtomicExplorerStore(root, clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0))
    version = store.current_pointer()["version"]
    public_csv = root / "versions" / version / "public" / "robin-real-data.csv"
    public_csv.write_text("corrupted", encoding="utf-8")

    restarted = AtomicExplorerStore(root, clock=lambda: NOW)
    with pytest.raises(BundleValidationError, match="LOCAL_VERSION_HASH_MISMATCH"):
        restarted.read_public_bytes("robin-real-data.csv")
    assert restarted.status()["last_error_code"] == "LOCAL_VERSION_HASH_MISMATCH"


def test_renderer_revision_rebuild_preserves_existing_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "older", run_id=9, slot=NOW - timedelta(hours=2), price=2.0))
    current_source = _bundle(tmp_path / "current", run_id=10, slot=NOW, price=2.2)
    store.publish(current_source)
    before = store.read_public("robin-real-data.json")
    before_json = store.read_public_bytes("robin-real-data.json")
    before_html_sha = hashlib.sha256(store.read_public_bytes("robin-real-data.html")).hexdigest()
    before_receipt_sha = store.current_pointer()["source_receipt_sha256"]
    pointer_path = store.pointer_path
    pointer = json.loads(pointer_path.read_text("utf-8"))
    version_root = store.versions / pointer["version"]
    manifest_path = version_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    legacy_root = store.versions / "run-10"
    version_root.rename(legacy_root)
    manifest_path = legacy_root / "manifest.json"
    pointer["version"] = "run-10"
    pointer.pop("renderer_revision")
    manifest.pop("renderer_revision")
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original_renderer = explorer_module.render_dashboard_html
    monkeypatch.setattr(explorer_module, "LOCAL_RENDERER_REVISION", "v7")
    monkeypatch.setattr(
        explorer_module,
        "render_dashboard_html",
        lambda snapshot, *, csv_filename: (
            original_renderer(snapshot, csv_filename=csv_filename) + b"\n"
        ),
    )

    rebuilt = store.publish(current_source)
    after = store.read_public("robin-real-data.json")

    assert rebuilt["renderer_revision"] == "v7"
    assert rebuilt["version"].endswith("-view-v7")
    assert after["price_movement"] == before["price_movement"]
    assert len(after["explorer_rows"]) == len(before["explorer_rows"])
    assert store.read_public_bytes("robin-real-data.json") == before_json
    assert store.current_pointer()["source_receipt_sha256"] == before_receipt_sha
    assert hashlib.sha256(store.read_public_bytes("robin-real-data.html")).hexdigest() != (
        before_html_sha
    )


@pytest.mark.parametrize("renderer_current", [True, False])
def test_same_origin_semantic_change_is_rejected_without_moving_the_pointer(
    tmp_path: Path,
    renderer_current: bool,
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    original = _bundle(tmp_path / "original", run_id=10, slot=NOW, price=2.0)
    changed = _bundle(tmp_path / "changed", run_id=10, slot=NOW, price=2.0)
    changed_json_path = changed / "robin-real-data.json"
    changed_snapshot = json.loads(changed_json_path.read_text("utf-8"))
    changed_snapshot["coverage"] = {"semantic_change": True}
    changed_json = (
        json.dumps(
            changed_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    changed_json_path.write_bytes(changed_json)
    changed_receipt_path = changed / "public-receipt.json"
    changed_receipt = json.loads(changed_receipt_path.read_text("utf-8"))
    changed_receipt["normalized_json_sha256"] = hashlib.sha256(changed_json).hexdigest()
    changed_receipt_path.write_text(json.dumps(changed_receipt), encoding="utf-8")
    store.publish(original)
    if not renderer_current:
        pointer = json.loads(store.pointer_path.read_text("utf-8"))
        current_root = store.versions / pointer["version"]
        legacy_root = store.versions / "run-10-view-v2"
        current_root.rename(legacy_root)
        manifest_path = legacy_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8"))
        manifest["renderer_revision"] = "v2"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pointer["renderer_revision"] = "v2"
        pointer["version"] = legacy_root.name
        store.pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    pointer_before = store.current_pointer()
    json_before = store.read_public_bytes("robin-real-data.json")

    with pytest.raises(BundleValidationError, match="LOCAL_SOURCE_IDENTITY_COLLISION"):
        store.publish(changed)

    assert store.current_pointer() == pointer_before
    assert store.read_public_bytes("robin-real-data.json") == json_before


def test_same_origin_relay_may_refresh_derived_movement_without_changing_acquisition(
    tmp_path: Path,
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    original = _bundle(tmp_path / "original", run_id=10, slot=NOW, price=2.0)
    relay = _bundle(
        tmp_path / "relay",
        run_id=10,
        delivery_run_id=11,
        slot=NOW,
        price=2.0,
    )
    relay_json_path = relay / "robin-real-data.json"
    relay_snapshot = json.loads(relay_json_path.read_text("utf-8"))
    relay_snapshot["price_movement"] = {
        "matched_offer_count": 0,
        "changed_offer_count": 0,
        "changes": [],
        "unmatched_current_count": 1,
    }
    relay_json = (
        json.dumps(
            relay_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    relay_json_path.write_bytes(relay_json)
    relay_receipt_path = relay / "public-receipt.json"
    relay_receipt = json.loads(relay_receipt_path.read_text("utf-8"))
    relay_receipt["normalized_json_sha256"] = hashlib.sha256(relay_json).hexdigest()
    relay_receipt_path.write_text(json.dumps(relay_receipt), encoding="utf-8")
    original_pointer = store.publish(original)
    original_public = store.read_public_bytes("robin-real-data.json")

    relayed_pointer = store.publish(relay)

    assert relayed_pointer == original_pointer
    assert store.current_pointer() == original_pointer
    assert store.read_public_bytes("robin-real-data.json") == original_public
    assert store.status()["last_delivery_run_id"] == "11"
    assert store.status()["last_error_code"] is None


def test_refresh_migrates_cached_renderer_before_github_failure(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    source = _bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0)
    store.publish(source)
    pointer = json.loads(store.pointer_path.read_text("utf-8"))
    current_root = store.versions / pointer["version"]
    legacy_root = store.versions / "run-10-view-v2"
    current_root.rename(legacy_root)
    manifest_path = legacy_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["renderer_revision"] = "v2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    pointer["renderer_revision"] = "v2"
    pointer["version"] = legacy_root.name
    store.pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    controller = ExplorerRefreshController(store, _FailingClient(), clock=lambda: NOW)

    assert controller.refresh_once() is True

    migrated = store.current_pointer()
    assert migrated is not None
    assert migrated["renderer_revision"] == "v10"
    assert migrated["version"] == "run-10-view-v10"
    assert b"local-refresh-status" in store.read_public_bytes("robin-real-data.html")
    assert store.status()["last_error_code"] == "GITHUB_AUTH_REQUIRED"


def test_history_render_of_current_legacy_run_does_not_block_pointer_migration(
    tmp_path: Path,
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    source = _bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0)
    store.publish(source)
    pointer = json.loads(store.pointer_path.read_text("utf-8"))
    current_root = store.versions / pointer["version"]
    legacy_root = store.versions / "run-10-view-v2"
    current_root.rename(legacy_root)
    manifest_path = legacy_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["renderer_revision"] = "v2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    pointer["renderer_revision"] = "v2"
    pointer["version"] = legacy_root.name
    store.pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    frozen_json = store.read_public_bytes("robin-real-data.json", run_id="10")
    assert (store.versions / "run-10-view-v10").is_dir()
    controller = ExplorerRefreshController(store, _FailingClient(), clock=lambda: NOW)

    assert controller.refresh_once() is True

    migrated = store.current_pointer()
    assert migrated is not None
    assert migrated["renderer_revision"] == "v10"
    assert migrated["version"] == "run-10-view-v10"
    assert store.read_public_bytes("robin-real-data.json") == frozen_json
    assert store.status()["last_error_code"] == "GITHUB_AUTH_REQUIRED"


class _FailingClient:
    def download_candidates(
        self, _destination: Path, *, current_delivery_run_id: str | None = None
    ) -> list[Path]:
        assert current_delivery_run_id == "10"
        raise BundleValidationError("GITHUB_AUTH_REQUIRED")


def test_auth_failure_updates_sanitized_status_without_dropping_view(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0))
    controller = ExplorerRefreshController(store, _FailingClient(), clock=lambda: NOW)

    assert controller.refresh_once() is False

    assert store.current_pointer()["run_id"] == "10"
    status = store.status()
    assert status["last_error_code"] == "GITHUB_AUTH_REQUIRED"
    assert "token" not in json.dumps(status).casefold()
    assert "secret" not in json.dumps(status).casefold()


class _OSFailingClient:
    def download_candidates(
        self, _destination: Path, *, current_delivery_run_id: str | None = None
    ) -> list[Path]:
        raise OSError("sensitive local path")


def test_os_failure_is_sanitized_without_stopping_last_known_good(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0))
    controller = ExplorerRefreshController(store, _OSFailingClient(), clock=lambda: NOW)

    assert controller.refresh_once() is False
    assert store.read_public("robin-real-data.json")["github_run_id"] == "10"
    assert store.status()["last_error_code"] == "LOCAL_IO_FAILURE"


def test_failed_gh_artifact_download_is_not_treated_as_healthy(tmp_path: Path) -> None:
    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["gh", "api"] and command[-1].endswith(
            "runs?status=completed&per_page=6"
        ):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"workflow_runs": [{"id": 11, "conclusion": "success"}]}),
                stderr="",
            )
        if command[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "artifacts": [
                            {
                                "name": "robin-autonomous-lab-11",
                                "expired": False,
                            }
                        ]
                    }
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="artifact expired")

    client = GhArtifactClient(repository="owner/repo", workflow_id="42", runner=runner)

    with pytest.raises(BundleValidationError, match="GITHUB_ARTIFACT_DOWNLOAD_FAILED"):
        client.download_candidates(tmp_path / "downloads", current_delivery_run_id="10")


def test_refresh_loop_survives_unexpected_failure_and_records_sanitized_code() -> None:
    class Controller:
        calls = 0
        failures: list[str] = []

        def refresh_once(self) -> bool:
            self.calls += 1
            raise RuntimeError("secret should never reach status")

        def record_failure(self, code: str) -> None:
            self.failures.append(code)

    class StopAfterOne:
        calls = 0

        def wait(self, _seconds: float) -> bool:
            self.calls += 1
            return self.calls > 1

    controller = Controller()
    run_refresh_loop(controller, StopAfterOne(), 0.01)

    assert controller.calls == 1
    assert controller.failures == ["REFRESH_UNEXPECTED_FAILURE"]


def test_refresh_loop_can_refresh_immediately_without_waiting() -> None:
    class Controller:
        calls = 0

        def refresh_once(self) -> bool:
            self.calls += 1
            return True

        def record_failure(self, _code: str) -> None:
            raise AssertionError("no failure expected")

    class AlreadyStopped:
        def wait(self, _seconds: float) -> bool:
            return True

    controller = Controller()
    run_refresh_loop(controller, AlreadyStopped(), 300, refresh_immediately=True)

    assert controller.calls == 1


def test_service_runner_serves_cache_before_background_refresh() -> None:
    runner = (ROOT / "scripts" / "run_real_data_explorer.py").read_text(encoding="utf-8")

    synchronous_refresh = "if arguments.refresh_once:\n        changed = controller.refresh_once()"
    assert synchronous_refresh in runner
    assert runner.index(synchronous_refresh) < runner.index("server = make_server")
    empty_cache_refresh = "if store.current_pointer() is None:\n        controller.refresh_once()"
    assert empty_cache_refresh in runner
    assert runner.index(empty_cache_refresh) < runner.index("server = make_server")
    assert 'kwargs={"refresh_immediately": True}' in runner


def test_replayed_origin_advances_delivery_cursor_without_redownload(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "initial", run_id=10, slot=NOW, price=2.0))
    replay = _bundle(
        tmp_path / "11",
        run_id=10,
        delivery_run_id=11,
        slot=NOW,
        price=2.0,
    )

    class Client:
        seen: list[str | None] = []

        def download_candidates(
            self, _destination: Path, *, current_delivery_run_id: str | None = None
        ) -> list[DownloadedArtifact]:
            self.seen.append(current_delivery_run_id)
            return [DownloadedArtifact(replay, "11")] if len(self.seen) == 1 else []

    client = Client()
    controller = ExplorerRefreshController(store, client, clock=lambda: NOW)
    assert controller.refresh_once() is False
    assert store.status()["last_delivery_run_id"] == "11"

    controller.record_failure("GITHUB_READ_TIMEOUT")
    assert store.status()["last_delivery_run_id"] == "11"
    assert controller.refresh_once() is False
    assert client.seen == ["10", "11"]
    assert store.status()["last_delivery_run_id"] == "11"


def test_empty_cache_skips_carry_forward_but_keeps_sticky_degraded_status(
    tmp_path: Path,
) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    valid = _bundle(tmp_path / "10", run_id=10, slot=NOW, price=2.0)
    stale = _bundle(
        tmp_path / "11",
        run_id=10,
        delivery_run_id=11,
        slot=NOW,
        price=2.0,
    )
    snapshot_path = stale / "robin-real-data.json"
    snapshot = json.loads(snapshot_path.read_text("utf-8"))
    snapshot["data_role"] = "CARRY_FORWARD_STALE"
    normalized = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    snapshot_path.write_bytes(normalized)
    receipt_path = stale / "public-receipt.json"
    receipt = json.loads(receipt_path.read_text("utf-8"))
    receipt["normalized_json_sha256"] = hashlib.sha256(normalized).hexdigest()
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")

    class Client:
        calls = 0

        def download_candidates(
            self, _destination: Path, *, current_delivery_run_id: str | None = None
        ) -> list[DownloadedArtifact]:
            self.calls += 1
            if self.calls == 1:
                assert current_delivery_run_id is None
                return [DownloadedArtifact(stale, "11"), DownloadedArtifact(valid, "10")]
            assert current_delivery_run_id == "11"
            return []

    controller = ExplorerRefreshController(store, Client(), clock=lambda: NOW)
    assert controller.refresh_once() is True
    assert store.read_public("robin-real-data.json")["github_run_id"] == "10"
    assert store.status()["last_error_code"] == "SOURCE_CARRY_FORWARD_STALE"
    assert controller.refresh_once() is False
    assert store.status()["last_error_code"] == "SOURCE_CARRY_FORWARD_STALE"


def test_browser_bundle_has_no_github_credentials_or_receipt_route(tmp_path: Path) -> None:
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "source", run_id=10, slot=NOW, price=2.0))

    public = b"\n".join(
        store.read_public_bytes(name) for name in ("robin-real-data.html", "robin-real-data.json")
    ).lower()

    assert b"gh_token" not in public
    assert b"github_token" not in public
    assert b"public-receipt.json" not in public


def test_http_server_serves_latest_pinned_status_and_exact_posted_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This server is hard-bound to 127.0.0.1. Restore the process socket only for
    # this explicit loopback integration test; the autouse capture guard remains
    # active for every other test and still reports any unapproved attempt.
    monkeypatch.setattr(socket, "socket", _REAL_SOCKET)
    monkeypatch.setattr(socket, "create_connection", _REAL_CREATE_CONNECTION)
    monkeypatch.setattr(socket, "getaddrinfo", _REAL_GETADDRINFO)
    monkeypatch.setattr(socket, "gethostbyaddr", _REAL_GETHOSTBYADDR)
    store = AtomicExplorerStore(tmp_path / "store", clock=lambda: NOW)
    store.publish(_bundle(tmp_path / "older", run_id=10, slot=NOW, price=2.0))
    store.publish(
        _bundle(
            tmp_path / "newer",
            run_id=11,
            slot=NOW + timedelta(hours=2),
            price=2.2,
        )
    )
    server = make_server(store, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        latest = json.loads(urllib.request.urlopen(f"{base}/robin-real-data.json").read())
        pinned = json.loads(
            urllib.request.urlopen(f"{base}/history/10/robin-real-data.json").read()
        )
        status = json.loads(urllib.request.urlopen(f"{base}/status.json").read())
        assert latest["github_run_id"] == "11"
        assert pinned["github_run_id"] == "10"
        assert status["current_run_id"] == "11"

        content = "comparison_status,match\nMATCHED_CHANGED,Arsenal — Leeds United\n"
        request = urllib.request.Request(
            f"{base}/export.csv",
            data=urllib.parse.urlencode({"content": content}).encode(),
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            assert response.headers["Content-Disposition"] == (
                'attachment; filename="robin-selection.csv"'
            )
            assert response.read().decode() == content

        json_content = json.dumps(
            {
                "schema_version": "robin-filtered-selection-v1",
                "row_count": 1,
                "rows": [{"comparison_status": "MATCHED_CHANGED"}],
            }
        )
        json_request = urllib.request.Request(
            f"{base}/export.json",
            data=urllib.parse.urlencode({"content": json_content}).encode(),
            method="POST",
        )
        with urllib.request.urlopen(json_request) as response:
            assert response.headers["Content-Type"] == "application/json; charset=utf-8"
            assert response.headers["Content-Disposition"] == (
                'attachment; filename="robin-selection.json"'
            )
            assert json.loads(response.read())["row_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_windows_launcher_is_hidden_durable_and_local_only() -> None:
    installer = (ROOT / "scripts/install_real_data_explorer.ps1").read_text("utf-8")
    runner = (ROOT / "scripts/run_real_data_explorer.py").read_text("utf-8")

    assert "pythonw.exe" in installer
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "StartWhenAvailable" in installer
    assert "Register-ScheduledTask" in installer
    assert "StartupShortcut" in installer
    assert "WScript.Shell" in installer
    assert "Start-Process" in installer
    assert "-WindowStyle Hidden" in installer
    assert "--refresh-seconds" in installer
    assert "127.0.0.1" not in installer or "http://127.0.0.1" in installer
    assert "GhArtifactClient" in runner
    assert "make_server" in runner
    assert "GH_TOKEN" not in runner
    assert "GITHUB_TOKEN" not in runner


def test_runbook_covers_open_filter_export_stop_resume_and_fail_closed_errors() -> None:
    runbook = (ROOT / "RUNBOOK.md").read_text("utf-8")

    for phrase in (
        "http://127.0.0.1:4173/robin-real-data.html",
        "Exporter la sélection CSV",
        "Réinitialiser",
        "Stop-ScheduledTask",
        "Start-ScheduledTask",
        "GITHUB_AUTH_REQUIRED",
        "SOURCE_HASH_MISMATCH",
        "LATE_ARTIFACT",
    ):
        assert phrase in runbook
