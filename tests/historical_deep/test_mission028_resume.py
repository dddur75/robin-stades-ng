from datetime import UTC, datetime, timedelta

import pytest

from robin.historical_deep.storage import InMemoryObjectStore
from scripts.mission028_budget import reserve_status
from scripts.mission028_resume import checkpoint, choose
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
    receipt = dict(family="lineups", worker=0, reason_class="ProviderAuthenticationError")
    checkpoint(store, dict(receipt, reason_code="MISSION028_TIME_SLICE_ENDED"), NOW, "rev", NOW - timedelta(seconds=1))
    assert choose(store, NOW, "rev", 0) == ("READY", "lineups")
    checkpoint(store, receipt, NOW, "rev", NOW - timedelta(seconds=1))
    assert choose(store, NOW, "rev", 0) == ("PAUSED", "none")
    assert choose(store, NOW, "fixed-rev", 0) == ("READY", "lineups")


def test_atomic_slot_ceiling_and_continuation_bound_stop_without_provider_calls():
    store = InMemoryObjectStore()
    assert choose(store, NOW, "rev", 20) == ("HOLD", "none")
    for i in range(129749):
        store.put_if_absent(f"{PREFIX}/daily/2026-10-17/{i:05d}", b"{}")
    assert choose(store, NOW, "rev", 0) == ("READY", "lineups")
    store.put_if_absent(f"{PREFIX}/daily/2026-10-17/129749", b"{}")
    assert choose(store, NOW, "rev", 0) == ("BUDGET", "none")


def test_status_requests_have_atomic_daily_headroom_and_reset_at_midnight():
    store = InMemoryObjectStore()
    for _ in range(49):
        reserve_status(store, NOW)
    with pytest.raises(RuntimeError, match="DAILY_BUDGET"):
        reserve_status(store, NOW)
    reserve_status(store, NOW + timedelta(days=1))


@pytest.mark.parametrize("state,family", [("READY", "lineups"), ("READY", "statistics"),
    ("DONE", "none"), ("BUDGET", "none"), ("PAUSED", "none"), ("HOLD", "none")])
def test_resume_entrypoint_only_emits_state_without_network_dispatch(monkeypatch, tmp_path, state, family):
    from scripts import mission028_resume as run
    from scripts import run_mission028_details as details
    events, store = [], InMemoryObjectStore()
    monkeypatch.setattr(details, "load_mapping", lambda: events.append("mapping"))
    monkeypatch.setattr(run, "R2ObjectStore", lambda env: events.append("state") or store)
    monkeypatch.setattr(run, "choose", lambda *args: (state, family))
    monkeypatch.setattr("requests.post", lambda *args, **kwargs: pytest.fail("no GitHub dispatch"))
    monkeypatch.setenv("GITHUB_SHA", "rev")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert run.main() == 0 and events == ["mapping", "state"]
    assert (tmp_path / "out").read_text() == f"state={state}\nfamily={family}\n"


def test_total_status_headroom_is_bounded_across_days():
    store = InMemoryObjectStore()
    for i in range(925):
        store.put_if_absent(f"{PREFIX}/status-slots/old/{i}", b"{}")
    with pytest.raises(RuntimeError, match="TOTAL_BUDGET"):
        reserve_status(store, NOW)
    checkpoint(store, dict(reason_class="RuntimeError", reason_code="MISSION028_TOTAL_BUDGET_REACHED"), NOW, "rev")
    assert choose(store, NOW + timedelta(days=1), "rev", 0) == ("BUDGET", "none")


def test_resume_uses_only_workflow71_with_unchanged_read_permissions():
    from pathlib import Path

    import yaml

    path = Path(".github/workflows/71-historical-deep-fixture-bundle-harvest.yml")
    workflow = yaml.safe_load(path.read_text())
    assert not Path(".github/workflows/mission028-daily.yml").exists()
    assert not Path(".github/actions/mission028-state").exists()
    assert workflow["permissions"] == {"actions": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "${{ inputs.mission028_progress && 'mission-028-progress' || inputs.progress_only && 'mission-027-progress' || inputs.lineups_only && format('mission-027-lineups-{0}', inputs.competition) || 'historical-deep-r2-state' }}",
        "cancel-in-progress": False,
    }
    assert (workflow.get("on", workflow.get(True)))["schedule"] == [{"cron": "17 */2 * * *"}]
    assert list(workflow["jobs"]) == ["fixture-bundles"]
    job = workflow["jobs"]["fixture-bundles"]
    assert job['permissions'] == {'actions': 'read', 'contents': 'write'}
    publisher = next(s for s in job['steps'] if s.get('run') == 'python -m scripts.publish_mission029')
    assert publisher['env']['GH_TOKEN'] == '${{ github.token }}'
    assert "steps.mission029.outcome == 'success'" in publisher['if']
    assert all('GH_TOKEN' not in s.get('env', {}) for s in job['steps'] if s is not publisher)
    plan = next(step for step in job["steps"] if step.get("id") == "resume")
    assert plan["run"] == "python -m scripts.mission028_resume"
    assert "API_FOOTBALL_KEY" not in plan["env"]
    source = Path("scripts/mission028_resume.py").read_text() + path.read_text()
    assert 'GH_TOKEN' not in plan['env']
    assert all(token not in source for token in ("--dispatch", "actions: write", "requests.post", "workflow disable"))
