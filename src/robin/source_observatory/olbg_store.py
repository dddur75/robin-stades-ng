"""Read native choices independently from the immutable score-only collector."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import olbg_authority
from .connectors import read_events
from .olbg_campaign import validate_olbg_campaign
from .qualification_view import merge_sro_collection
from .recurring import instant


def read_bundle(path: Path, expected_sha: str) -> dict[str, Any]:
    if path.stat().st_size > 2_000_000:
        raise ValueError("native bundle size")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha:
        raise ValueError("native bundle hash")
    v = json.loads(raw)
    if (
        not isinstance(v, dict)
        or v.get("schemaVersion") != "robin-native-tipsters-v1"
        or not isinstance(v.get("picks"), list)
        or len(v["picks"]) > 100
    ):
        raise ValueError("native schema")
    fixtures = {f["id"]: f for f in v["fixtures"]}
    seen = set()
    for p in v["picks"]:
        if not isinstance(p, dict):
            raise ValueError("native row")
        author = re.fullmatch(
            r"https://www\.olbg\.com/tipsters/tips/([0-9]+)", p.get("authorUrl", "")
        )
        fixture = fixtures.get(p.get("fixtureId"))
        if (
            not author
            or p.get("sourceUrl") != p["authorUrl"]
            or p.get("authorId") != "olbg:" + author[1]
            or p.get("sourceId") != "SRC_014"
            or type(p.get("sourceTipId")) is not int
            or p["sourceTipId"] <= 0
            or type(p.get("sourceEventId")) is not int
            or p["sourceEventId"] <= 0
            or p.get("id") != f"olbg-tip:{p.get('sourceTipId')}"
            or p["id"] in seen
        ):
            raise ValueError("native attribution")
        seen.add(p["id"])
        if (
            not fixture
            or p.get("kickoff") != fixture["kickoff"]
            or instant(p["observedAt"]) >= instant(p["kickoff"])
        ):
            raise ValueError("native timing")
        if (
            p.get("market") != "source_native"
            or p.get("sourceMarketLabel") != ""
            or p.get("sourceBetType") != "Win"
            or p.get("performanceEvaluationAllowed") is not False
            or p.get("sourceEventTimezone") is not None
            or p.get("publishedAt") is not None
            or p.get("publishedCivilDate") is not None
        ):
            raise ValueError("false native normalization")
        if not isinstance(p.get("selection"), str) or not 0 < len(p["selection"]) <= 120:
            raise ValueError("native selection")
        if any(
            re.fullmatch(r"[a-f0-9]{64}", p.get(k, "")) is None
            for k in ["responseSha256", "parserSha256", "calendarSha256"]
        ):
            raise ValueError("native provenance")
    v["authorCount"] = len({p["authorId"] for p in v["picks"]})
    v["distinctPicks"] = len(v["picks"])
    return v


def read_olbg_companion(
    seed: dict[str, Any], seed_dir: Path, campaign_dir: Path
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    data = deepcopy(seed)
    personal = None
    try:
        h = olbg_authority.APPROVED_E1_SHA256
        personal = read_bundle(seed_dir / ("observations-" + h + ".json"), h)
        data = merge_sro_collection(data, personal)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        data["olbgE1State"] = "unavailable"
    try:
        plan, mission = validate_olbg_campaign(campaign_dir)
        events = read_events(campaign_dir / "events.jsonl")
        current = personal
        verified_slots: set[str] = set()
        for index, e in enumerate(events):
            if e["kind"] != "PUBLIC_COLLECTION_ACCEPTED":
                continue
            name = e["observationFile"]
            h = e["observationSha256"]
            if name != "observations-" + h + ".json":
                raise ValueError("invalid observation name")
            bundle = read_bundle(campaign_dir / name, h)
            starts = [
                i
                for i, x in enumerate(events[:index])
                if x["kind"] == "PUBLIC_SLOT_STARTED" and x.get("slot") == e.get("slot")
            ]
            if len(starts) != 1 or e.get("slot") not in plan["slots"]:
                raise ValueError("native slot start absent")
            if e["slot"] in verified_slots:
                raise ValueError("duplicate accepted slot")
            slot_events = events[starts[0] : index]
            qualified = [
                x
                for x in slot_events
                if x["kind"] == "PUBLIC_PICKS_QUALIFIED"
                and x.get("sourceId") == "SRC_014"
                and x.get("parserSha256") == plan["parserSha256"]
                and x.get("calendarSha256") == plan["calendarSha256"]
                and x.get("count") == e["count"]
            ]
            finished = [
                x
                for x in events[index + 1 :]
                if x["kind"] == "PUBLIC_SLOT_FINISHED"
                and x.get("slot") == e.get("slot")
                and x.get("count") == e["count"]
            ]
            if len(qualified) != 1 or len(finished) != 1:
                raise ValueError("native slot qualification absent")
            q = qualified[0]
            if not any(
                x["kind"] == "REQUEST_FINISHED"
                and x.get("sourceId") == "SRC_014"
                and x.get("url") == plan["endpoint"]
                and x.get("httpStatus") == 200
                and x.get("responseSha256") == q["responseSha256"]
                for x in slot_events
            ):
                raise ValueError("native source GET absent")
            if (
                bundle["missionId"] != plan["id"]
                or bundle["fixtures"] != plan["fixtures"]
                or len(bundle["picks"]) != e["count"]
                or any(
                    p["authorUrl"] != plan["endpoint"]
                    or p["parserSha256"] != plan["parserSha256"]
                    or p["calendarSha256"] != plan["calendarSha256"]
                    or p["responseSha256"] != q["responseSha256"]
                    for p in bundle["picks"]
                )
            ):
                raise ValueError("native receipt mismatch")
            verified_slots.add(e["slot"])
            current = merge_sro_collection(current, bundle) if current else bundle
        completed = [e.get("slot") for e in events if e["kind"] == "PUBLIC_SLOT_FINISHED"]
        if len(completed) != len(verified_slots) or set(completed) != verified_slots:
            raise ValueError("orphan completed slot")
        if current:
            personal = current
            data = merge_sro_collection(data, current)
        success = len(verified_slots)
        halted = any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
        expired = datetime.now(UTC) >= instant(mission["expires_at"])
        locked = (campaign_dir / "campaign.lock").exists()
        state = (
            "expired"
            if expired
            else "halted"
            if halted
            else "blocked_lock"
            if locked
            else "collecting"
            if success
            else "scheduled"
        )
        data["olbgCampaign"] = dict(
            state=state,
            successfulSlots=success,
            requests=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
            requestsMax=36,
            slots=len(plan["slots"]),
            startsAt=plan["slots"][0],
            expiresAt=mission["expires_at"],
        )
        return (
            data,
            personal,
            bool(success and personal and not halted and not expired and not locked),
        )
    except OSError:
        data["olbgCampaign"] = dict(state="awaiting_preparation")
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        data["olbgCampaign"] = dict(state="invalid_package")
    return data, personal, False
