import json
from copy import deepcopy
from datetime import datetime

import pytest

from robin.source_observatory import notbetting_occurrence_live_view as view


def test_campaign_never_reports_programming_without_separate_windows_proof():
    with pytest.raises(ValueError, match="Windows"):
        view.campaign_summary([], None, datetime.fromisoformat("2026-11-21T06:00:00+00:00"), False)


@pytest.mark.parametrize(
    ("stamp", "pending", "extra", "expected"),
    [
        ("06:00", None, [], "scheduled"),
        ("07:03", None, [], "missed_slot"),
        ("06:00", "canary", [], "blocked_lock"),
        ("12:00", None, [], "expired"),
        ("06:00", None, [{"kind": "CAMPAIGN_HALTED"}], "halted"),
    ],
)
def test_campaign_clock_owner_and_failures_take_priority(stamp, pending, extra, expected):
    event = {"kind": "PASS_COMPLETED", "slot": "canary"}
    result = view.campaign_summary(
        [event, *extra], pending, datetime.fromisoformat(f"2026-11-21T{stamp}:00+00:00"), True
    )
    assert result["state"] == expected
    assert result["canonicalQualification"] is False
    assert result["sourceTraversalComplete"] is False
    assert result["successfulSlots"] == 0


def test_unavailable_companion_preserves_all_base_evidence(tmp_path):
    base = {"picks": [{"id": "old", "observedAt": "original"}], "claimIds": ["OLD"]}
    original = deepcopy(base)
    result = view.add_public(base, tmp_path)
    assert base == original and result["picks"] == original["picks"]
    assert result["claimIds"] == ["OLD"]
    assert result["notbettingOccurrenceCampaign"]["state"] == "unavailable"


def test_malformed_owner_lock_retains_the_base(tmp_path, monkeypatch):
    def malformed(*args, **kwargs):
        raise AttributeError("malformed owner")

    monkeypatch.setattr(view.campaign, "read_view", malformed)
    base = {"picks": [{"id": "preserved"}]}
    assert view.add_public(base, tmp_path)["picks"] == base["picks"]


def test_durable_halt_without_journal_failure_still_stops_programming():
    value = view.campaign_summary(
        [], None, datetime.fromisoformat("2026-11-21T06:00:00+00:00"), True, halted=True
    )
    assert value["state"] == "halted"


def test_flag_only_stop_preserves_history_and_overrides_a_ready_schedule(tmp_path, monkeypatch):
    directory = tmp_path / view.campaign.DIRECTORY
    directory.mkdir(parents=True)
    grant = dict(
        decisionId=view.TASK_DECISION,
        decisionHash=view.TASK_DECISION_SHA,
        planSha256=view.PLAN_SHA,
        keys=["C0", "C1", "C2", "C4"],
        kind="TASK_REGISTRATION_SEPARATE",
    )
    (directory / "task-authorization.json").write_text(json.dumps(grant))
    (directory / "halt.flag").touch()
    context = {k: v for k, v in grant.items() if k not in {"decisionId", "decisionHash"}}
    monkeypatch.setattr(
        view.frozen, "_ledger_record", lambda *args: dict(decision="PASS_AND_HOLD", context=context)
    )
    monkeypatch.setattr(view.campaign, "_stable_snapshot", lambda *args: ([], None))
    monkeypatch.setattr(view.campaign, "read_view", lambda *args, base, **kwargs: deepcopy(base))
    base = dict(picks=[dict(id="preserved", firstSeenAt="original")], claimIds=["OLD"])
    result = view.add_public(base, tmp_path)
    assert result["picks"] == base["picks"]
    assert result["notbettingOccurrenceCampaign"]["state"] == "halted"
