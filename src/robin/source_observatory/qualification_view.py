"""Read a hash-anchored assessment and join only admitted personal facts."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .recurring import instant

APPROVED_ASSESSMENT_SHA = "074e27982610ee4252b9035112b016e53bc5627865feed2d81a4c7a65e6a9fb2"


def apply_qualification(
    base: dict[str, Any],
    directory: Path,
    *,
    expected_sha256: str,
    public_data: dict[str, Any] | None = None,
    operational: bool = False,
    operational_by_source: dict[str, bool] | None = None,
) -> dict[str, Any]:
    raw = (directory / "assessment.json").read_bytes()
    if len(raw) > 2_000_000 or sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("qualification hash mismatch")
    assessment = json.loads(raw)
    entries = {r["id"]: r for r in assessment["candidates"]}
    platforms = {p["platform"]: p for p in assessment["platforms"]}
    if (
        assessment["schemaVersion"] != "robin-candidate-qualification-v1"
        or assessment["registrySha256"] != base["receipt"]["registrySha256"]
        or len(entries) != len(assessment["candidates"])
        or set(entries) != {r["id"] for r in base["candidates"]}
        or set(platforms) != {r["platform"] for r in base["candidates"]}
    ):
        raise ValueError("qualification provenance/count mismatch")
    data = deepcopy(base)
    picks = (public_data or {}).get("picks", [])
    source_states = (
        operational_by_source if operational_by_source is not None else {"SRC_039": operational}
    )
    source_ids = {"Stade Rennais Online": "SRC_039", "OLBG": "SRC_014"}
    qualified = 0
    for row in data["candidates"]:
        scope = platforms[row["platform"]]
        source_id = source_ids.get(row["platform"])
        personal = [
            p
            for p in picks
            if source_id is not None
            and p.get("sourceId") == source_id
            and p.get("authorUrl") == row["sourceUrl"]
            and instant(p["observedAt"]) < instant(p["kickoff"])
        ]
        enabled = bool(personal and source_states.get(source_id or "", False))
        qualified += bool(personal)
        row["collectionEnabled"] = enabled
        row["qualification"] = dict(
            scope,
            **entries[row["id"]],
            label="Choix personnels observés avant match" if personal else scope["label"],
            personallyProven=bool(personal),
            sourceId=source_id,
            picks=deepcopy(personal),
        )
    data["enabledCount"] = sum(r["collectionEnabled"] for r in data["candidates"])
    data["qualification"] = dict(
        status="ok",
        claimId=assessment["claimId"],
        assessedCount=len(entries),
        platformCount=len(platforms),
        qualifiedCount=qualified,
        observedAt=assessment.get("observedAt"),
        platforms=list(platforms.values()),
        sourceOperational=operational,
        operationalBySource=source_states,
    )
    return data


def merge_sro_collection(seed: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(seed)
    combined = {p["id"]: p for p in data["picks"]}
    for pick in deepcopy(active["picks"]):
        previous = combined.get(pick["id"])
        if previous:
            versions = deepcopy(previous.get("versions", []))
            known = {(v["selection"], v["observedAt"]) for v in versions}
            for version in pick.get("versions", []):
                key = (version["selection"], version["observedAt"])
                if key not in known and (
                    not versions
                    or (
                        instant(version["observedAt"]) > instant(versions[-1]["observedAt"])
                        and version["selection"] != versions[-1]["selection"]
                    )
                ):
                    versions.append(version)
                    known.add(key)
            pick.update(
                firstSeenAt=previous.get("firstSeenAt", previous.get("observedAt")),
                versions=versions,
                versionCount=len(versions),
            )
        combined[pick["id"]] = pick
    data.update(
        picks=list(combined.values()),
        distinctPicks=len(combined),
        authorCount=len({p["authorId"] for p in combined.values()}),
        recurring=bool(data.get("recurring") or active.get("recurring")),
        generatedAt=active.get("generatedAt", data.get("generatedAt")),
    )
    data["claimIds"] = list(
        dict.fromkeys([*data.get("claimIds", [data["claimId"]]), active["claimId"]])
    )
    return data


def read_sro_e1(directory: Path) -> dict[str, Any]:
    from .sro_authority import APPROVED_E1_SHA256

    raw = (directory / ("observations-" + APPROVED_E1_SHA256 + ".json")).read_bytes()
    if len(raw) > 2_000_000 or sha256(raw).hexdigest() != APPROVED_E1_SHA256:
        raise ValueError("independent E1 observation mismatch")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data["schemaVersion"] != "robin-public-tipsters-v1"
        or not isinstance(data["picks"], list)
    ):
        raise ValueError("invalid E1 observation")
    for p in data["picks"]:
        p.update(
            firstSeenAt=p["observedAt"],
            lastSeenAt=p["observedAt"],
            versions=[dict(selection=p["selection"], observedAt=p["observedAt"])],
            versionCount=1,
        )
    return data


def read_sro_companion(
    seed: dict[str, Any], directory: Path
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    from datetime import UTC, datetime

    from .connectors import read_events
    from .public_collection import read_collection
    from .sro_campaign import validate_sro_campaign

    data = deepcopy(seed)
    personal = None
    try:
        personal = read_sro_e1(directory.parent / "tipsters-qualification317-rfc404-20261119")
        data = merge_sro_collection(data, personal)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        data["sroE1State"] = "unavailable"
    try:
        plan, mission = validate_sro_campaign(directory)
        events = read_events(directory / "events.jsonl")
        halted = any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
        expired = datetime.now(UTC) >= instant(mission["expires_at"])
        accepted = any(e["kind"] == "PUBLIC_COLLECTION_ACCEPTED" for e in events)
        active = read_collection(directory) if accepted else None
        if active:
            personal = merge_sro_collection(personal, active) if personal else active
            data = merge_sro_collection(data, active)
        successful = sum(e["kind"] == "PUBLIC_SLOT_FINISHED" for e in events)
        locked = (directory / "campaign.lock").exists()
        operational = bool(successful and not halted and not expired and not locked)
        data["sroCampaign"] = dict(
            state="expired"
            if expired
            else "halted"
            if halted
            else "blocked_lock"
            if locked
            else "collecting"
            if successful
            else "scheduled",
            startsAt=plan["slots"][0],
            expiresAt=mission["expires_at"],
            slots=len(plan["slots"]),
            successfulSlots=successful,
            requests=sum(e["kind"] == "REQUEST_RESERVED" for e in events) + plan["priorGET"],
            requestsMax=plan["sharedGETCeiling"],
            priorRequests=plan["priorGET"],
            currentRequests=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
            currentRequestsMax=mission["external_effects"]["https_get_max"],
        )
        return data, personal, operational
    except OSError:
        data["sroCampaign"] = dict(state="awaiting_preparation")
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        data["sroCampaign"] = dict(state="invalid_package")
    return data, personal, False
