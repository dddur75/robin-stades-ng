"""Read bounded recurring evidence without changing original declarations or grants."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import notbetting_occurrence_campaign as campaign
from . import notbetting_recurring_v4 as frozen
from .recurring import instant

PLAN_SHA = "b3416214560ba160cb91694b0be004a282b57cd4a47b2436e43667ce55d15406"
TASK_DECISION = "RCV3-20261121-NOTBETTING-OCCURRENCE-SINGLE-WINDOWS-TASK-AUTHORIZED"
TASK_DECISION_SHA = "4cdcf78b2d776b3b8bf0f4e09f73aab729ffe2aea95d94292f12bdd071b55a96"
CLAIM = "DATA.SOURCE_OBSERVATORY.NOTBETTING.OCCURRENCE.CANARY.20261121"


def campaign_summary(
    events: list[dict[str, Any]],
    pending: str | None,
    now: datetime,
    windows_proven: bool,
    *,
    halted: bool = False,
) -> dict[str, Any]:
    if not windows_proven:
        raise ValueError("separate Windows authority absent")
    completed = {e["slot"] for e in campaign._completed_passes(events, pending_slot=pending)}
    state = "scheduled"
    if halted or any(e["kind"] == "CAMPAIGN_HALTED" for e in events):
        state = "halted"
    elif now >= instant(campaign.EXPIRY):
        state = "expired"
    elif pending is not None:
        state = "blocked_lock"
    elif set(campaign.SLOTS) <= completed:
        state = "completed"
    elif any(
        now > instant(s) + timedelta(minutes=2) and s not in completed for s in campaign.SLOTS
    ):
        state = "missed_slot"
    return dict(
        state=state,
        startsAt=campaign.SLOTS[0],
        expiresAt=campaign.EXPIRY,
        slots=len(campaign.SLOTS),
        successfulSlots=len(completed.intersection(campaign.SLOTS)),
        requests=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
        requestsMax=8,
        sourceTraversalComplete=False,
        canonicalQualification=False,
        recurringAuthority=False,
    )


def add_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    directory = root / campaign.DIRECTORY
    now = datetime.now(UTC)
    try:
        data = campaign.read_view(root, directory, PLAN_SHA, now=now, base=base)
        data["claimIds"] = list(dict.fromkeys([*data.get("claimIds", []), CLAIM]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        data = deepcopy(base)
        data["notbettingOccurrenceCampaign"] = dict(state="unavailable")
        return data
    try:
        grant = json.loads((directory / "task-authorization.json").read_bytes())
        record = frozen._ledger_record(root, TASK_DECISION, TASK_DECISION_SHA)
        proven = (
            grant["decisionId"] == TASK_DECISION
            and grant["decisionHash"] == TASK_DECISION_SHA
            and grant["planSha256"] == PLAN_SHA
            and grant["keys"] == ["C0", "C1", "C2", "C4"]
            and grant["kind"] == "TASK_REGISTRATION_SEPARATE"
            and record["decision"] == "PASS_AND_HOLD"
            and record["context"]
            == {k: v for k, v in grant.items() if k not in {"decisionHash", "decisionId"}}
        )
        events, pending = campaign._stable_snapshot(directory, PLAN_SHA)
        data["notbettingOccurrenceCampaign"] = campaign_summary(
            events, pending, now, proven, halted=(directory / "halt.flag").exists()
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        data["notbettingOccurrenceCampaign"] = dict(state="unavailable")
    return data
