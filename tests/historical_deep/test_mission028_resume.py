from datetime import UTC, datetime, timedelta

import pytest

from robin.historical_deep.storage import InMemoryObjectStore
from scripts.mission028_resume import checkpoint, choose, reserve_status
from scripts.run_mission028 import PREFIX

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def test_selects_statistics_after_all_terminal_lineup_workers_and_stops_when_done():
    store = InMemoryObjectStore()
    assert choose(store, NOW, "rev", 0) == ("READY", "lineups")
    for family in ("lineups", "statistics"):
        for worker in range(16):
            # Terminal means every target attempted; partial coverage remains explicit.
            checkpoint(store, dict(family=family, worker=worker, status="PARTIAL"), NOW, "rev")
        assert choose(store, NOW, "rev", 0) == (("READY", "statistics") if family == "lineups" else ("DONE", "none"))


def test_shared_daily_limit_waits_for_next_utc_day():
    store = InMemoryObjectStore()
    checkpoint(store, dict(family="lineups", worker=0, reason_class="RuntimeError",
        reason_code="MISSION028_DAILY_BUDGET_REACHED"), NOW, "rev", NOW + timedelta(hours=1))
    assert choose(store, NOW, "rev", 0) == ("BUDGET", "none")
    assert choose(store, NOW + timedelta(days=1), "rev", 0) == ("READY", "lineups")


def test_lease_expiration_can_resume_but_unexpected_error_pauses_that_code_revision():
    store = InMemoryObjectStore()
    receipt = dict(family="lineups", worker=0, reason_class="ProviderTransportError")
    checkpoint(store, receipt, NOW, "rev", NOW - timedelta(seconds=1))
    assert choose(store, NOW, "rev", 0) == ("READY", "lineups")
    checkpoint(store, receipt, NOW, "rev", NOW + timedelta(hours=1))
    assert choose(store, NOW, "rev", 0) == ("PAUSED", "none")
    assert choose(store, NOW, "fixed-rev", 0) == ("READY", "lineups")


def test_atomic_slot_ceiling_and_continuation_bound_stop_without_provider_calls():
    store = InMemoryObjectStore()
    assert choose(store, NOW, "rev", 20) == ("HOLD", "none")
    for i in range(69750):
        store.put_if_absent(f"{PREFIX}/daily/2026-10-17/{i:05d}", b"{}")
    assert choose(store, NOW, "rev", 0) == ("BUDGET", "none")


def test_status_requests_have_atomic_daily_headroom_and_reset_at_midnight():
    store = InMemoryObjectStore()
    for _ in range(49):
        reserve_status(store, NOW)
    with pytest.raises(RuntimeError, match="DAILY_BUDGET"):
        reserve_status(store, NOW)
    reserve_status(store, NOW + timedelta(days=1))


def test_dispatch_is_bounded_and_only_for_ready_frozen_targets(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from scripts import mission028_resume as run
    from scripts import run_mission028_details as details
    store, calls = InMemoryObjectStore(), []
    monkeypatch.setattr(details, "load_mapping", lambda: [])
    monkeypatch.setattr(run, "R2ObjectStore", lambda env: store)
    monkeypatch.setattr(run.sys, "argv", ["resume", "--dispatch"])
    for key, value in dict(GITHUB_SHA="rev", GITHUB_OUTPUT=str(tmp_path / "out"),
        GITHUB_REPOSITORY="test/repo", GITHUB_REF_NAME="task", GH_TOKEN=str(tmp_path)).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(run.requests, "post", lambda url, **kw: calls.append((url, kw)) or SimpleNamespace(status_code=204))
    assert run.main() == 0 and len(calls) == 1
    assert calls[0][1]["json"]["inputs"]["cycle"] == 1
    assert calls[0][1]["json"]["ref"] == "task" and calls[0][1]["allow_redirects"] is False
    checkpoint(store, dict(reason_class="Unexpected"), NOW, "rev")
    assert run.main() == 0 and len(calls) == 1


def test_total_status_headroom_is_bounded_across_days():
    store = InMemoryObjectStore()
    for i in range(925):
        store.put_if_absent(f"{PREFIX}/status-slots/old/{i}", b"{}")
    with pytest.raises(RuntimeError, match="TOTAL_BUDGET"):
        reserve_status(store, NOW)
    checkpoint(store, dict(reason_class="RuntimeError", reason_code="MISSION028_TOTAL_BUDGET_REACHED"), NOW, "rev")
    assert choose(store, NOW + timedelta(days=1), "rev", 0) == ("BUDGET", "none")


def test_daily_resume_keeps_provider_and_dispatch_permissions_in_separate_jobs():
    from pathlib import Path

    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/mission028-daily.yml").read_text())
    jobs = workflow["jobs"]
    assert workflow["permissions"] == {"contents": "read"}
    assert jobs["collect"]["uses"].endswith("/71-historical-deep-fixture-bundle-harvest.yml")
    assert "API_FOOTBALL_KEY" in jobs["collect"]["secrets"]
    for name in ("plan", "continue"):
        assert "API_FOOTBALL_KEY" not in jobs[name]["env"]
    assert jobs["continue"]["permissions"] == {"contents": "read", "actions": "write"}
    assert jobs["continue"]["steps"][-1]["run"].startswith("gh workflow disable mission028-daily.yml ")
