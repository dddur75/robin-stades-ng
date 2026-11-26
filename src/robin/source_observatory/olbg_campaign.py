"""One-profile OLBG collection with independently approved finite authority."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .collector import robots_policy
from .connectors import Journal, Response, canonical, public_get
from .forum_tipsters import _walk
from .olbg import admit_facts, extract_profile
from .olbg_authority import APPROVED_MANIFEST_SHA256, APPROVED_PLAN_SHA256
from .public_formats import _Node, _Tree, decode_document
from .recurring import instant

PINS = [
    "src/robin/source_observatory/" + p + ".py"
    for p in [
        "olbg_campaign",
        "olbg",
        "candidate_forums",
        "connectors",
        "collector",
        "forum_tipsters",
        "public_formats",
        "recurring",
    ]
] + [
    "cockpit/scripts/collect-olbg-tipsters.py",
    "cockpit/scripts/olbg-tipsters-tick.ps1",
    "cockpit/scripts/register-olbg-tipsters-task.ps1",
]
HOST = "https://www.olbg.com/"


def legal_document(body: bytes) -> str:
    tree = _Tree()
    tree.feed(decode_document(body))
    mains = [
        n
        for n in _walk(tree.root)
        if n.tag == "main" or "use-static-page" in (n.attrs.get("class") or "").split()
    ]
    if len(mains) != 1:
        raise ValueError("unique legal main absent")

    def content(node: _Node) -> str:
        if node.tag in {"script", "style", "head", "template"}:
            return ""
        return " ".join(content(c) if isinstance(c, _Node) else c for c in node.children)

    text = " ".join(content(mains[0]).split())
    if not all(
        re.search(r"(?<![\d.])" + marker + r"\s", text)
        for marker in [r"1\.", r"7\.1", r"9\.2", r"17\.4"]
    ):
        raise ValueError("complete legal sections absent")
    return text


def rules_digest(body: bytes) -> str:
    text = legal_document(body)
    return sha256(text.encode()).hexdigest()


def validate_olbg_campaign(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads((directory / "plan.json").read_bytes())
    mission = json.loads((directory / "manifest.json").read_bytes())
    grant = json.loads((directory / "authorization.json").read_bytes())
    if (
        not isinstance(plan, dict)
        or not isinstance(mission, dict)
        or not isinstance(grant, dict)
        or sha256(canonical(plan)).hexdigest() != APPROVED_PLAN_SHA256
        or sha256(canonical(mission)).hexdigest() != APPROVED_MANIFEST_SHA256
    ):
        raise ValueError("independent source approval missing or changed")
    hashes = [
        plan.get(k)
        for k in (
            "rulesSha256",
            "e1EvidenceSha256",
            "calendarEvidenceSha256",
            "calendarSha256",
            "parserSha256",
        )
    ]
    pins = plan.get("codePins")
    if not isinstance(pins, dict):
        raise ValueError("SHA-256 execution pins required")
    hashes.extend(pins.values())
    hashes.extend(
        [mission.get("source_hash"), grant.get("planSha256"), grant.get("manifestSha256")]
    )
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in hashes
    ):
        raise ValueError("SHA-256 must contain exactly 64 lowercase hexadecimal characters")
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
        set(mission) != required
        or mission["maximum_stage"] != "E2"
        or mission["authorized_stages"] != ["E1", "E2"]
        or mission["source_hash"] != sha256(canonical(plan)).hexdigest()
        or grant.get("planSha256") != mission["source_hash"]
        or grant.get("manifestSha256") != sha256(canonical(mission)).hexdigest()
        or grant.get("ownerMessage") != plan["ownerMessage"]
        or mission["mission_id"] != plan["id"]
        or plan["scope"] != "LOCAL_PERSONAL_NONCOMMERCIAL"
        or plan["sourceId"] != "SRC_014"
        or plan["endpoint"] != HOST + "tipsters/tips/648433"
        or plan["robotsUrl"] != HOST + "robots.txt"
        or plan["termsUrl"] != HOST + "use"
        or len(plan["slots"]) != 12
        or len(set(plan["slots"])) != 12
        or plan.get("priorGET") != 0
        or plan.get("sharedGETCeiling") != 36
        or mission["external_effects"] != {"https_get_max": 36, "per_source_max": 36}
        or set(plan["codePins"]) != set(PINS)
        or plan["calendarSha256"] != sha256(canonical(plan["fixtures"])).hexdigest()
    ):
        raise ValueError("invalid exact source authorization")
    root = Path(__file__).resolve().parents[3]
    for name, expected in plan["codePins"].items():
        if sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError("execution code changed")
    if plan["parserSha256"] != plan["codePins"]["src/robin/source_observatory/olbg.py"]:
        raise ValueError("parser proof mismatch")
    slots = [instant(s) for s in plan["slots"]]
    if slots != sorted(slots) or any(s >= instant(mission["expires_at"]) for s in slots):
        raise ValueError("invalid slots")
    return plan, mission


def run_olbg_slot(
    directory: Path,
    *,
    now: datetime | None = None,
    get: Callable[..., Response] = public_get,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    plan, mission = validate_olbg_campaign(directory)
    current = now or clock()
    if current >= instant(mission["expires_at"]):
        return dict(state="expired", requests=0)
    due = [s for s in plan["slots"] if 0 <= (current - instant(s)).total_seconds() <= 180]
    if len(due) != 1:
        return dict(state="not_due", requests=0)
    slot = due[0]
    lock = directory / "campaign.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(slot)
    try:
        journal = Journal(directory, mission, now=clock)
        if any(e["kind"] == "CAMPAIGN_HALTED" for e in journal.events):
            return dict(state="halted", requests=0)
        if any(e["kind"] == "PUBLIC_SLOT_STARTED" and e["slot"] == slot for e in journal.events):
            return dict(state="already_started", requests=0)
        if sum(e["kind"] == "RUN_STARTED" for e in journal.events) != sum(
            e["kind"] == "RUN_FINISHED" for e in journal.events
        ):
            journal.append("CAMPAIGN_HALTED", slot=slot, reason="unfinished prior run")
            return dict(state="halted", requests=0)
        journal.append("RUN_STARTED", slot=slot)
        journal.append("PUBLIC_SLOT_STARTED", slot=slot)
        before = sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events)
        deadline = current + timedelta(seconds=210)
        rules = ""
        picks = []
        try:
            for url in [plan["robotsUrl"], plan["termsUrl"], plan["endpoint"]]:
                allowed, delay = robots_policy(rules, url)
                if not allowed or delay > 30:
                    raise ValueError("robots denied")
                remaining = min(journal.remaining_seconds(), (deadline - clock()).total_seconds())
                if remaining <= max(2, delay) + 1:
                    raise ValueError("slot deadline exhausted")
                sleep(max(2, delay))
                timeout = min(
                    12.0, journal.remaining_seconds(), (deadline - clock()).total_seconds()
                )
                if timeout <= 0:
                    raise ValueError("slot deadline exhausted")
                reservation = journal.reserve("SRC_014", url)
                response = get(url, timeout=timeout)
                observed = clock()
                if observed >= deadline:
                    raise ValueError("slot deadline exceeded")
                digest = sha256(response.body).hexdigest()
                journal.append(
                    "REQUEST_FINISHED",
                    sourceId="SRC_014",
                    url=url,
                    reservation=reservation,
                    httpStatus=response.status,
                    responseSha256=digest,
                )
                if url == plan["robotsUrl"] and response.status == 404:
                    journal.append(
                        "ROBOTS_ABSENCE_OBSERVED", policy="RFC9309-2.3.1.3", httpStatus=404
                    )
                    continue
                if response.status != 200:
                    raise ValueError("source access refused")
                if url == plan["robotsUrl"]:
                    rules = decode_document(response.body)
                    if "<" in rules or "\x00" in rules:
                        raise ValueError("invalid robots document")
                elif url == plan["termsUrl"]:
                    if rules_digest(response.body) != plan["rulesSha256"]:
                        raise ValueError("terms changed")
                else:
                    picks = admit_facts(
                        extract_profile(response.body, 648433),
                        url,
                        observed,
                        plan["fixtures"],
                        response_sha=digest,
                        parser_sha=plan["parserSha256"],
                        calendar_sha=plan["calendarSha256"],
                    )
                    journal.append(
                        "PUBLIC_PICKS_QUALIFIED",
                        sourceId="SRC_014",
                        responseSha256=digest,
                        parserSha256=plan["parserSha256"],
                        calendarSha256=plan["calendarSha256"],
                        count=len(picks),
                    )
            if not picks:
                raise ValueError("no admissible personal pick")
            data = dict(
                schemaVersion="robin-native-tipsters-v1",
                missionId=plan["id"],
                claimId=plan["claimId"],
                fixtures=plan["fixtures"],
                picks=picks,
                parserSha256=plan["parserSha256"],
                calendarSha256=plan["calendarSha256"],
                generatedAt=clock().isoformat(),
                recurring=True,
            )
            raw = canonical(data) + b"\n"
            digest = sha256(raw).hexdigest()
            filename = "observations-" + digest + ".json"
            with (directory / filename).open("xb") as stream:
                stream.write(raw)
            journal.append(
                "PUBLIC_COLLECTION_ACCEPTED",
                observationFile=filename,
                observationSha256=digest,
                count=len(picks),
                authors=len({p["authorId"] for p in picks}),
                slot=slot,
            )
            journal.append("PUBLIC_SLOT_FINISHED", slot=slot, count=len(picks))
            return dict(
                state="succeeded",
                picks=len(picks),
                requests=sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events) - before,
            )
        except Exception as exc:
            journal.append("CAMPAIGN_HALTED", slot=slot, reason=type(exc).__name__)
            raise
        finally:
            journal.append("RUN_FINISHED", slot=slot)
    finally:
        lock.unlink()
