"""Read a seed collection and a separately authorized campaign, without network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .connectors import read_events
from .public_campaign import validate_campaign
from .public_collection import read_collection
from .recurring import instant


def read_public_view(seed: Path, campaign: Path, *, now: datetime | None = None) -> dict[str, Any]:
    data = read_collection(seed)
    current = now or datetime.now(UTC)
    try:
        plan, manifest = validate_campaign(campaign)
    except OSError:
        data["campaign"] = {"state": "awaiting_authorization"}
        return data
    except (ValueError, KeyError, TypeError):
        data["campaign"] = {"state": "invalid_package"}
        return data
    try:
        return _compose(dict(data), campaign, plan, manifest, current)
    except (OSError, ValueError, KeyError, TypeError):
        data["campaign"] = {"state": "invalid_package"}
        return data


def _compose(
    data: dict[str, Any],
    campaign: Path,
    plan: dict[str, Any],
    manifest: dict[str, Any],
    current: datetime,
) -> dict[str, Any]:
    events = read_events(campaign / "events.jsonl")
    accepted = any(e["kind"] == "PUBLIC_COLLECTION_ACCEPTED" for e in events)
    halted = any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
    if accepted:
        active = read_collection(campaign)
        combined = {p["id"]: p for p in data["picks"]}
        for pick in active["picks"]:
            previous = combined.get(pick["id"])
            if previous:
                versions = list(previous.get("versions", []))
                for version in pick.get("versions", []):
                    if not versions or versions[-1]["selection"] != version["selection"]:
                        versions.append(version)
                pick = dict(
                    pick,
                    firstSeenAt=previous.get("firstSeenAt", previous["observedAt"]),
                    versions=versions,
                    versionCount=len(versions),
                )
            combined[pick["id"]] = pick
        data.update(
            picks=list(combined.values()),
            distinctPicks=len(combined),
            authorCount=len({p["authorId"] for p in combined.values()}),
            recurring=True,
        )
        data["generatedAt"] = active.get("generatedAt", data.get("generatedAt"))
        data["claimIds"] = list(dict.fromkeys([data["claimId"], active["claimId"]]))
    state = (
        "expired"
        if current >= instant(manifest["expires_at"])
        else "halted"
        if halted
        else "collecting"
        if events
        else "scheduled"
    )
    data["campaign"] = dict(
        state=state,
        taskName=plan["taskName"],
        startsAt=plan["startsAt"],
        expiresAt=manifest["expires_at"],
        slots=len(plan["slots"]),
        requestsMax=manifest["external_effects"]["https_get_max"],
        requests=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
        successfulSlots=sum(e["kind"] == "PUBLIC_SLOT_FINISHED" for e in events),
        journalHead=events[-1]["hash"] if events else None,
    )
    return data
