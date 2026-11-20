"""Finite profile383717 E2, independent of every existing collector grant."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import expanded_olbg_authority as authority
from .collector import robots_policy
from .connectors import Journal, Response, canonical, read_events
from .olbg import admit_facts, extract_profile
from .olbg_campaign import rules_digest
from .olbg_store import read_bundle
from .recurring import instant

PROFILE = "https://www.olbg.com/tipsters/tips/383717"
URLS = ["https://www.olbg.com/robots.txt", "https://www.olbg.com/use", PROFILE]
MISSION = "ROBIN-OLBG-EXPANDED383717-20261120"
TASK = "Robin-Tipsters-OLBG-Expanded383717-20261120"


def validate(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(__file__).resolve().parents[3]
    p = json.loads((directory / "plan.json").read_bytes())
    m = json.loads((directory / "manifest.json").read_bytes())
    grant = json.loads((directory / "authorization.json").read_bytes())
    required = {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    if (
        set(m) != required
        or m["maximum_stage"] != "E2"
        or m["authorized_stages"] != ["E1", "E2"]
        or sha256(canonical(p)).hexdigest() != authority.APPROVED_PLAN_SHA256
        or sha256(canonical(m)).hexdigest() != authority.APPROVED_MANIFEST_SHA256
        or m["source_hash"] != authority.APPROVED_PLAN_SHA256
        or m["mission_id"] != MISSION
        or p["id"] != MISSION
        or p["taskName"] != TASK
        or p["urls"] != URLS
        or p["scope"] != "LOCAL_PERSONAL_NONCOMMERCIAL"
        or p["priorGET"] != 0
        or p["requestsMax"] != 9
        or m["external_effects"] != {"https_get_max": 9, "per_source_max": 9}
        or m["time_budget"] != {"seconds": 600, "per_slot_seconds": 150}
        or grant["planSha256"] != authority.APPROVED_PLAN_SHA256
        or grant["manifestSha256"] != authority.APPROVED_MANIFEST_SHA256
        or set(grant["keys"]) != {"C0", "C1", "C4"}
        or grant["e1Sha256"] != authority.E1_SHA256
    ):
        raise ValueError("exact expanded-author authority absent")
    ledger = [
        json.loads(line)
        for line in (root / "reports/council/decision-ledger.jsonl").read_bytes().splitlines()
    ]
    records = [
        r
        for r in ledger
        if r["decision_id"] == grant["decisionId"] and r["decision"] == "PASS_AND_HOLD"
    ]
    if len(records) != 1:
        raise ValueError("expanded-author decision absent")
    c = records[0]["context"]
    if (
        set(c["keys"]) != {"C0", "C1", "C4"}
        or c["plan_sha256"] != authority.APPROVED_PLAN_SHA256
        or c["manifest_sha256"] != authority.APPROVED_MANIFEST_SHA256
        or c["mission_id"] != MISSION
        or c["expires_at"] != m["expires_at"]
    ):
        raise ValueError("expanded-author decision mismatch")
    for path, h in p["codePins"].items():
        if sha256((root / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() != h:
            raise ValueError("expanded execution pin changed")
    if p["parserSha256"] != p["codePins"]["src/robin/source_observatory/olbg.py"]:
        raise ValueError("expanded parser anchor mismatch")
    e1dir = root / "cockpit/.ci/tipsters-source-expansion-20261120-v2"
    seed = read_bundle(e1dir / f"observations-{authority.E1_SHA256}.json", authority.E1_SHA256)
    calendar = root / "cockpit/.ci/tipsters-calendar-official-20261120/calendar-projection.json"
    if (
        sha256(calendar.read_bytes()).hexdigest() != authority.CALENDAR_SHA256
        or p["calendarSha256"] != authority.CALENDAR_SHA256
        or p["fixtures"] != seed["fixtures"]
        or len(p["fixtures"]) != 1
        or len(p["slots"]) != 2
        or p["slots"] != sorted(set(p["slots"]))
        or any(
            instant(s) <= instant(p["notBefore"]) or instant(s) >= instant(m["expires_at"])
            for s in p["slots"]
        )
        or instant(m["expires_at"]) >= instant(p["fixtures"][0]["kickoff"])
    ):
        raise ValueError("expanded temporal scope")
    return p, m


def run_slot(
    directory: Path,
    *,
    get: Callable[..., Response],
    canary: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan, mission = validate(directory)
    now = clock()
    if now < instant(plan["notBefore"]) or now >= instant(mission["expires_at"]):
        return {"state": "outside_window", "requests": 0}
    due = [s for s in plan["slots"] if 0 <= (now - instant(s)).total_seconds() <= 180]
    if not canary and len(due) != 1:
        return {"state": "not_due", "requests": 0}
    slot = "manual_canary" if canary else due[0]
    lock = directory / "campaign.lock"
    try:
        lock.open("x").close()
    except FileExistsError:
        return {"state": "blocked_lock", "requests": 0}
    try:
        journal = Journal(directory, mission, now=clock)
        if any(e["kind"] == "CAMPAIGN_HALTED" for e in journal.events):
            return {"state": "halted", "requests": 0}
        if any(e["kind"] == "PUBLIC_SLOT_STARTED" and e["slot"] == slot for e in journal.events):
            return {"state": "already_started", "requests": 0}
        if sum(e["kind"] == "RUN_STARTED" for e in journal.events) != sum(
            e["kind"] == "RUN_FINISHED" for e in journal.events
        ):
            journal.append("CAMPAIGN_HALTED", reason="unfinished prior run")
            return {"state": "halted", "requests": 0}
        journal.append("RUN_STARTED", slot=slot)
        journal.append("PUBLIC_SLOT_STARTED", slot=slot)
        before = sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events)
        deadline = now + timedelta(seconds=150)
        rules = ""
        picks = []
        try:
            for index, url in enumerate(URLS):
                if index:
                    allowed, delay = robots_policy(rules, url)
                    if not allowed or delay > 30:
                        raise ValueError("robots denied")
                    sleep(max(2, delay))
                left = min(
                    12,
                    journal.remaining_seconds(),
                    (deadline - clock()).total_seconds(),
                    (instant(mission["expires_at"]) - clock()).total_seconds(),
                )
                if left <= 0:
                    raise ValueError("slot deadline exhausted")
                reservation = journal.reserve("SRC_014", url)
                left = min(
                    12,
                    journal.remaining_seconds(),
                    (deadline - clock()).total_seconds(),
                    (instant(mission["expires_at"]) - clock()).total_seconds(),
                )
                if left <= 0:
                    raise ValueError("deadline expired after reservation")
                response = get(url, ca_sha256=plan["caSha256"], timeout=left)
                observed = clock()
                digest = sha256(response.body).hexdigest()
                journal.append(
                    "REQUEST_FINISHED",
                    sourceId="SRC_014",
                    url=url,
                    httpStatus=response.status,
                    responseSha256=digest,
                    reservation=reservation,
                )
                if (
                    response.status != 200
                    or response.location
                    or any(
                        b in response.body.lower()
                        for b in (b"cf-chl-", b"captcha challenge", b"verify you are human")
                    )
                ):
                    raise ValueError("source HTTP/challenge/redirect")
                if index == 0:
                    rules = response.body.decode("utf-8", "strict")
                    if (
                        response.content_type.split(";")[0].strip().lower() != "text/plain"
                        or "\x00" in rules
                        or re.search(r"(?i)<(?:!doctype|html|script|body)\b|captcha", rules)
                    ):
                        raise ValueError("invalid robots document")
                elif index == 1:
                    if rules_digest(response.body) != plan["rulesSha256"]:
                        raise ValueError("legal terms changed")
                    journal.append(
                        "RULES_VERIFIED", rulesSha256=plan["rulesSha256"], responseSha256=digest
                    )
                else:
                    facts = extract_profile(response.body, 383717)
                    picks = admit_facts(
                        facts,
                        PROFILE,
                        observed,
                        plan["fixtures"],
                        response_sha=digest,
                        parser_sha=plan["parserSha256"],
                        calendar_sha=plan["calendarSha256"],
                    )
            if not picks:
                raise ValueError("no admissible personal choice")
            bundle = {
                "schemaVersion": "robin-native-tipsters-v1",
                "missionId": MISSION,
                "claimId": "DATA.SOURCE_OBSERVATORY.EXPANDED.OLBG.E2.20261120",
                "fixtures": plan["fixtures"],
                "picks": picks,
            }
            raw = canonical(bundle) + b"\n"
            h = sha256(raw).hexdigest()
            path = directory / f"observations-{h}.json"
            with path.open("xb") as f:
                f.write(raw)
            read_bundle(path, h)
            journal.append(
                "PUBLIC_COLLECTION_ACCEPTED",
                slot=slot,
                observationFile=path.name,
                observationSha256=h,
                count=len(picks),
            )
            journal.append("PUBLIC_SLOT_FINISHED", slot=slot, count=len(picks))
            result = {"state": "collected", "count": len(picks), "bundleSha256": h}
        except Exception as error:
            journal.append(
                "CAMPAIGN_HALTED",
                slot=slot,
                reasonType=type(error).__name__,
                reason=str(error)[:140],
            )
            result = {"state": "halted", "count": 0, "reasonType": type(error).__name__}
        journal.append("RUN_FINISHED", slot=slot)
        result["requests"] = sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events) - before
        return result
    finally:
        lock.unlink()


def read_state(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    try:
        p, m = validate(directory)
        events = read_events(directory / "events.jsonl")
        bundles = []
        slots = set()
        reservations = [e for e in events if e["kind"] == "REQUEST_RESERVED"]
        if len(reservations) > 9 or any(
            e["sourceId"] != "SRC_014" or e["url"] not in URLS for e in reservations
        ):
            raise ValueError("expanded request scope")
        for i, e in enumerate(events):
            if e["kind"] != "PUBLIC_COLLECTION_ACCEPTED":
                continue
            slot = e["slot"]
            h = e["observationSha256"]
            if (
                slot in slots
                or slot not in ["manual_canary", *p["slots"]]
                or e["observationFile"] != f"observations-{h}.json"
            ):
                raise ValueError("expanded receipt scope")
            bundle = read_bundle(directory / e["observationFile"], h)
            starts = [
                j
                for j, x in enumerate(events[:i])
                if x["kind"] == "PUBLIC_SLOT_STARTED" and x.get("slot") == slot
            ]
            if (
                len(starts) != 1
                or bundle["fixtures"] != p["fixtures"]
                or bundle["missionId"] != MISSION
                or len(bundle["picks"]) != e["count"]
            ):
                raise ValueError("expanded receipt attribution")
            window = events[starts[0] : i]
            reserved = [x for x in window if x["kind"] == "REQUEST_RESERVED"]
            if [x["url"] for x in reserved] != URLS or any(
                not any(
                    x["kind"] == "REQUEST_FINISHED"
                    and x.get("url") == r["url"]
                    and x.get("reservation") == r["hash"]
                    and x.get("httpStatus") == 200
                    for x in window
                )
                for r in reserved
            ):
                raise ValueError("expanded three-route receipt")
            if not any(
                x["kind"] == "RULES_VERIFIED" and x.get("rulesSha256") == p["rulesSha256"]
                for x in window
            ):
                raise ValueError("expanded legal receipt")
            for pick in bundle["picks"]:
                if (
                    pick["authorUrl"] != PROFILE
                    or pick["parserSha256"] != p["parserSha256"]
                    or pick["calendarSha256"] != p["calendarSha256"]
                    or not any(
                        x["kind"] == "REQUEST_FINISHED"
                        and x.get("url") == PROFILE
                        and x.get("httpStatus") == 200
                        and x.get("responseSha256") == pick["responseSha256"]
                        for x in window
                    )
                ):
                    raise ValueError("expanded source receipt mismatch")
            if (
                sum(
                    x["kind"] == "PUBLIC_SLOT_FINISHED"
                    and x.get("slot") == slot
                    and x.get("count") == e["count"]
                    for x in events[i + 1 :]
                )
                != 1
            ):
                raise ValueError("unfinished expanded slot")
            slots.add(slot)
            bundles.append(bundle)
        complete = sum(e["kind"] == "PUBLIC_SLOT_FINISHED" for e in events) == len(slots) and sum(
            e["kind"] == "RUN_STARTED" for e in events
        ) == sum(e["kind"] == "RUN_FINISHED" for e in events)
        expired = datetime.now(UTC) >= instant(m["expires_at"])
        halted = any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
        active = bool(
            slots
            and complete
            and not expired
            and not halted
            and not (directory / "campaign.lock").exists()
        )
        return (
            {
                "state": "expired"
                if expired
                else "halted"
                if halted
                else "collecting"
                if active
                else "prepared",
                "taskName": TASK,
                "requests": sum(e["kind"] == "REQUEST_RESERVED" for e in events),
                "requestsMax": 9,
                "successfulSlots": len(slots),
                "slots": 3,
                "scheduledSlots": p["slots"],
                "startsAt": p["notBefore"],
                "expiresAt": m["expires_at"],
                "profileUrl": PROFILE,
            },
            bundles,
            active,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return {"state": "unavailable", "taskName": TASK}, [], False
