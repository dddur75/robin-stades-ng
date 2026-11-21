"""Finite private OLBG group workload; Council records authority, Windows runs it."""

from __future__ import annotations

import http.client
import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .collector import robots_policy
from .connectors import Journal, Response, canonical, public_get, read_events
from .olbg import admit_facts, extract_profile
from .opaque_choices import build_opaque_choices, merge_distinct_choices
from .recurring import instant

ROOT = Path(__file__).resolve().parents[3]


def require(value: Any, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def validate_packet(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from .roster_campaign_authority import MANIFEST_SHA256, PLAN_SHA256

    plan = json.loads((directory / "plan-v2.json").read_bytes())
    mission = json.loads((directory / "manifest-v2.json").read_bytes())
    require(
        sha256(canonical(plan)).hexdigest() == PLAN_SHA256
        and sha256(canonical(mission)).hexdigest() == MANIFEST_SHA256,
        "exact roster recurrence packet",
    )
    require(
        set(mission)
        == {
            "mission_id",
            "authorized_stages",
            "maximum_stage",
            "external_effects",
            "compute_budget",
            "time_budget",
            "source_hash",
            "expires_at",
        }
        and mission["mission_id"] == plan["id"]
        and mission["source_hash"] == PLAN_SHA256
        and mission["authorized_stages"] == ["E1", "E2"]
        and mission["maximum_stage"] == "E2",
        "eight-field bounded mission",
    )
    require(
        mission["external_effects"] == {"https_get_max": 133, "per_source_max": 133}
        and mission["time_budget"] == {"seconds": 600}
        and mission["compute_budget"] == {"workers": 1},
        "fixed total GET and active time",
    )
    require(
        sha256(canonical(plan["pool"])).hexdigest()
        == "6ad9d08edd24bf0d69e34ec772d34f6dd4ce9d5b272d9817e8d3be62128e520f"
        and len(plan["pool"]) == 42
        and not {104214, 648433, 669088, 158}.intersection(plan["pool"]),
        "exact42 future-compatible authors without existing jobs",
    )
    require(
        len(plan["canaryAuthors"]) == 3
        and set(plan["canaryAuthors"]) <= set(plan["pool"])
        and plan["requestMax"] == 4 + 3 * 43 == 133,
        "one3-profile canary plus three42-profile passes",
    )
    require(
        plan["slots"] == ["2026-11-20T23:05:00Z", "2026-11-21T05:05:00Z", "2026-11-21T11:05:00Z"]
        and mission["expires_at"] == "2026-11-21T11:15:00Z",
        "exact temporary slots",
    )
    require(
        sha256(canonical(plan["fixtures"])).hexdigest() == plan["calendarSha256"],
        "canonical calendar hash",
    )
    future = [f for f in plan["fixtures"] if instant(f["kickoff"]) > instant(mission["expires_at"])]
    require(
        future
        and min(instant(f["kickoff"]) for f in future)
        >= instant(mission["expires_at"]) + timedelta(minutes=75),
        "expiry before canonical future fixtures",
    )
    for path, digest in plan["codePins"].items():
        require(
            sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest,
            "recurrence execution pin",
        )
    for item in plan["reusedEvidence"]:
        require(
            sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"],
            "recurrence reused source proof",
        )
    decisions = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl").read_bytes().splitlines()
    ]
    keys = [r for r in decisions if r["decision_id"] == plan["decisionId"]]
    require(
        len(keys) == 1
        and keys[0]["decision"] == "PASS_AND_HOLD"
        and set(keys[0]["context"]["keys"]) == {"C0", "C1", "C4"}
        and keys[0]["context"]["plan_sha256"] == PLAN_SHA256
        and keys[0]["context"]["manifest_sha256"] == MANIFEST_SHA256,
        "independent exact recurrence keys",
    )
    return plan, mission


def validate_registration(directory: Path, *, for_install: bool = False) -> dict[str, Any]:
    plan, mission = validate_packet(directory)
    receipt: dict[str, Any] = json.loads((directory / "canary-recette.json").read_bytes())
    events = read_events(directory / "events.jsonl")
    require(
        receipt["status"] == "PASS"
        and receipt["taskRegistrationAuthorized"] is True
        and receipt["planSha256"] == mission["source_hash"]
        and receipt["canaryHeadHash"]
        in {e["hash"] for e in events if e["kind"] == "RUN_FINISHED" and e["slot"] == "CANARY"},
        "independently accepted actual canary",
    )
    decisions = [
        json.loads(line)
        for line in (ROOT / "reports/council/decision-ledger.jsonl").read_bytes().splitlines()
    ]
    keys = [r for r in decisions if r["decision_id"] == plan["registrationDecisionId"]]
    require(
        len(keys) == 1
        and keys[0]["hash"] == receipt["decisionRecordHash"]
        and keys[0]["decision"] == "PASS_AND_HOLD"
        and set(keys[0]["context"]["keys"]) == {"C0", "C1", "C2", "C4"},
        "native registration independent keys",
    )
    require(
        keys[0]["context"]["plan_sha256"] == mission["source_hash"]
        and keys[0]["context"]["canary_head_hash"] == receipt["canaryHeadHash"],
        "registration exact canary and plan",
    )
    endpoint = next(e["sequence"] for e in events if e["hash"] == receipt["canaryHeadHash"])
    prefix = events[:endpoint]
    require(_completed(prefix) == ["CANARY"], "one closed canary prefix")
    prepared = [e for e in prefix if e["kind"] == "PROFILE_OBSERVATIONS_PREPARED"]
    require(
        [e["authorId"] for e in prepared] == plan["canaryAuthors"]
        and all(e["count"] > 0 for e in prepared)
        and sum(e["kind"] == "REQUEST_RESERVED" for e in prefix) == 4
        and sum(e["kind"] == "REQUEST_FINISHED" for e in prefix) == 4
        and not any(e["kind"] == "PROFILE_STOPPED" for e in prefix),
        "four real GETs and three proven canary authors",
    )
    _observations(directory, plan, prefix)
    if for_install:
        require(
            events == prefix and not (directory / "busy.lock").exists(),
            "registration only at exact closed current canary head",
        )
    return receipt


def _completed(events: list[dict[str, Any]]) -> list[str]:
    starts = [e["slot"] for e in events if e["kind"] == "RUN_STARTED"]
    finishes = [e["slot"] for e in events if e["kind"] == "RUN_FINISHED"]
    require(
        starts == finishes
        and len(starts) == len(set(starts))
        and not any(e["kind"] == "CAMPAIGN_HALTED" for e in events),
        "halted, duplicate or orphan group run",
    )
    return finishes


def _choices(
    source: dict[str, Any], plan: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profile = source["profiles"][0]
    request = profile["request"]
    wins = admit_facts(
        profile["facts"],
        request["url"],
        instant(request["observedAt"]),
        plan["fixtures"],
        response_sha=request["responseSha256"],
        parser_sha=plan["parserSha256"],
        calendar_sha=plan["calendarSha256"],
    )
    typed_football = {
        f["tipid"]
        for f in profile["facts"]["records"]
        if type(f.get("vc_sport_id")) is int and f["vc_sport_id"] == 1
    }
    wins = [p for p in wins if p["sourceTipId"] in typed_football]
    known = {p["sourceTipId"] for p in wins}
    opaque_ids = []
    for fact in profile["facts"]["records"]:
        tid = fact.get("tipid")
        if tid in known or tid not in typed_football:
            continue
        try:
            build_opaque_choices(source, [tid], parser_sha=plan["parserSha256"])
        except (ValueError, TypeError, KeyError):
            continue
        opaque_ids.append(tid)
    return wins, build_opaque_choices(source, opaque_ids, parser_sha=plan["parserSha256"])


def _contract(pick: dict[str, Any]) -> bytes:
    fields = pick.get("sourceFields", {})
    return canonical(
        dict(
            core={
                k: pick[k]
                for k in (
                    "authorId",
                    "sourceTipId",
                    "sourceEventId",
                    "fixtureId",
                    "selection",
                    "market",
                    "sourceMarketLabel",
                    "sourceBetType",
                    "kickoff",
                    "sourceEventLocalText",
                )
                if k in pick
            },
            literal={
                k: fields[k]
                for k in ("hcap", "hcap_market", "market", "winew", "event_datetime")
                if k in fields
            },
        )
    )


def _observations(
    directory: Path, plan: dict[str, Any], events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    completed = {e["slot"]: e for e in events if e["kind"] == "RUN_FINISHED"}
    starts = {e["slot"]: e for e in events if e["kind"] == "RUN_STARTED"}
    reservations = {e["hash"]: e for e in events if e["kind"] == "REQUEST_RESERVED"}
    picks: list[dict[str, Any]] = []
    observed = []
    for event in events:
        if event["kind"] != "PROFILE_OBSERVATIONS_PREPARED" or event["slot"] not in completed:
            continue
        path = directory / f"profile-{event['observationSha256']}.json"
        require(path.stat().st_size <= 2_000_000, "group observation bound")
        raw = path.read_bytes()
        require(sha256(raw).hexdigest() == event["observationSha256"], "group observation hash")
        value = json.loads(raw)
        source = value["source"]
        request = source["profiles"][0]["request"]
        author = event["authorId"]
        require(
            author in plan["pool"]
            and source["profiles"][0]["facts"]["authorId"] == author
            and request["url"] == f"https://www.olbg.com/tipsters/tips/{author}"
            and request["observedAt"] == event["observedAt"]
            and request["responseSha256"] == event["responseSha256"]
            and canonical(source["fixtures"]) == canonical(plan["fixtures"])
            and source["calendarSha256"] == plan["calendarSha256"],
            "group exact owner/calendar/clock",
        )
        matches = [
            r
            for r in events
            if r["kind"] == "REQUEST_FINISHED"
            and r.get("slot") == event["slot"]
            and canonical({k: r[k] for k in request}) == canonical(request)
        ]
        require(len(matches) == 1, "one exact source response")
        response = matches[0]
        reservation = reservations.get(response["reservation"])
        if reservation is None:
            raise ValueError("source reservation absent")
        require(
            reservation is not None
            and reservation["url"] == request["url"]
            and reservation["sourceId"] == "SRC_014"
            and starts[event["slot"]]["sequence"]
            < reservation["sequence"]
            < response["sequence"]
            < event["sequence"]
            < completed[event["slot"]]["sequence"],
            "source reservation response observation same closed run",
        )
        require(
            request["status"] == 200
            and request["contentType"].split(";")[0].strip().lower()
            in ("text/html", "application/xhtml+xml"),
            "observed source HTTP status/MIME",
        )
        run_start, run_finish = starts[event["slot"]], completed[event["slot"]]
        require(
            instant(run_start["at"])
            <= instant(reservation["at"])
            <= instant(request["observedAt"])
            <= instant(response["at"])
            <= instant(event["at"])
            <= instant(run_finish["at"]),
            "source clock interval inside actual run",
        )
        if event["slot"] == "CANARY":
            require(
                instant(plan["canaryNotBefore"]) <= instant(run_start["at"])
                and instant(run_finish["at"]) <= instant(plan["canaryExpires"]),
                "observed canary window",
            )
        else:
            require(
                event["slot"] in plan["slots"]
                and instant(event["slot"])
                <= instant(run_start["at"])
                < instant(event["slot"]) + timedelta(minutes=2),
                "observed scheduled start window",
            )
        require(
            instant(run_finish["at"]) <= instant(plan.get("expiresAt", "2026-11-21T11:15:00Z"))
            and instant(run_finish["at"]) <= instant(run_start["at"]) + timedelta(seconds=170),
            "observed mission/pass deadline",
        )
        wins, opaque = _choices(source, plan)
        require(
            canonical(wins) == canonical(value["native"])
            and canonical(opaque) == canonical(value["opaque"])
            and event["count"] == len(wins) + len(opaque),
            "literal source facts and count",
        )
        picks = merge_distinct_choices(picks, [*wins, *opaque])
        observed.append(event["observedAt"])
    return picks, observed


def run_slot(
    directory: Path,
    *,
    canary: bool = False,
    get: Callable[..., Response] = public_get,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan, mission = validate_packet(directory)
    require(
        not any(k in os.environ for k in ("SSLKEYLOGFILE", "SSL_CERT_FILE", "SSL_CERT_DIR")),
        "external TLS configuration",
    )
    require(clock() < instant(mission["expires_at"]), "group mission expired")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "busy.lock").open("x"):
        pass
    try:
        journal = Journal(directory, mission, now=clock)
        completed = _completed(journal.events)
        if canary:
            require(
                not completed
                and instant(plan["canaryNotBefore"]) <= clock() < instant(plan["canaryExpires"]),
                "canary once in exact window",
            )
            slot = "CANARY"
        else:
            validate_registration(directory)
            index = len(completed) - 1
            require(
                completed[:1] == ["CANARY"] and 0 <= index < len(plan["slots"]),
                "future slot after accepted canary",
            )
            slot = plan["slots"][index]
            if clock() >= instant(slot) + timedelta(minutes=2):
                journal.append("CAMPAIGN_HALTED", slot=slot, reason="MISSED_SLOT_NO_CATCHUP")
            require(
                instant(slot) <= clock() < instant(slot) + timedelta(minutes=2),
                "missed slot; no catchup",
            )
        with (directory / ("slot-" + ("canary" if canary else str(index)) + ".lock")).open("x"):
            pass
        inactive = {e["authorId"] for e in journal.events if e["kind"] == "PROFILE_STOPPED"}
        closed_picks, _ = _observations(directory, plan, journal.events)
        authors = [
            a for a in (plan["canaryAuthors"] if canary else plan["pool"]) if a not in inactive
        ]
        require(authors, "no eligible active author")
        journal.append("RUN_STARTED", slot=slot)
        started = time.monotonic()
        previous_start: float | None = None
        observed = []
        failure = False

        def left() -> float:
            remaining = min(
                journal.remaining_seconds() - 15,
                150 - (time.monotonic() - started),
                (instant(mission["expires_at"]) - clock()).total_seconds() - 10,
                (instant(plan["canaryExpires"]) - clock()).total_seconds()
                if canary
                else float("inf"),
            )
            require(remaining > 0, "group cumulative/pass finalization budget")
            return remaining

        def fetch(url: str) -> tuple[Response, dict[str, Any]]:
            nonlocal previous_start
            left()
            reservation = journal.reserve("SRC_014", url)
            timeout = min(12, left())
            previous_start = time.monotonic()
            response = get(url, timeout=timeout)
            request = dict(
                url=url,
                observedAt=clock().isoformat(),
                status=response.status,
                responseSha256=sha256(response.body).hexdigest(),
                bytes=len(response.body),
                contentType=response.content_type,
            )
            journal.append(
                "REQUEST_FINISHED",
                sourceId="SRC_014",
                reservation=reservation,
                slot=slot,
                **request,
            )
            left()
            return response, request

        try:
            robots, _ = fetch("https://www.olbg.com/robots.txt")
            require(robots.status in (200, 404, 410), "robots refusal")
            rules = robots.body.decode("utf-8", "strict") if robots.status == 200 else ""
            require(
                robots.status != 200
                or robots.content_type.split(";")[0].strip().lower() == "text/plain",
                "robots MIME",
            )
            require(
                not re.search(
                    r"<|\x00|captcha|verify you are human|access denied|just a moment", rules, re.I
                ),
                "robots content/challenge",
            )
            for author in authors:
                url = f"https://www.olbg.com/tipsters/tips/{author}"
                allowed, delay = robots_policy(rules, url)
                require(allowed and 0 <= delay <= 5, "robots route/delay")
                if previous_start is not None:
                    pause = max(0, max(3.0, delay) - (time.monotonic() - previous_start))
                    require(left() > pause, "polite wait budget")
                    sleep(pause)
                response, request = fetch(url)
                require(
                    response.status == 200
                    and response.content_type.split(";")[0].strip().lower()
                    in ("text/html", "application/xhtml+xml"),
                    "profile status/MIME refusal; no redirects",
                )
                headings = re.findall(
                    r"<(?:title|h1)(?:\s[^>]*)?>(.*?)</(?:title|h1)>",
                    response.body.decode("utf-8", "replace"),
                    re.I | re.S,
                )
                require(
                    not re.search(
                        r"just a moment|verify (?:you are|that you are) human|access denied|checking your browser",
                        " ".join(headings),
                        re.I,
                    ),
                    "rendered source challenge",
                )
                facts = extract_profile(response.body, expected_author_id=author)
                require(facts["mode"] == "current", "personal owner/current scope")
                require(
                    isinstance(facts["authorLabel"], str) and 0 < len(facts["authorLabel"]) <= 80,
                    "bounded personal pseudonym",
                )
                if len(facts["records"]) > 100:
                    journal.append(
                        "PROFILE_STOPPED",
                        slot=slot,
                        authorId=author,
                        reason="inventory_exceeds100_no_truncation",
                    )
                    inactive.add(author)
                    continue
                source = dict(
                    profiles=[dict(request=request, facts=facts)],
                    fixtures=plan["fixtures"],
                    calendarSha256=plan["calendarSha256"],
                )
                wins, opaque = _choices(source, plan)
                prior = {
                    p["id"]: p
                    for p in [*plan.get("priorAcceptedPicks", []), *closed_picks]
                    if p["authorId"] == f"olbg:{author}"
                }
                contradictory = any(
                    p["id"] in prior and _contract(p) != _contract(prior[p["id"]])
                    for p in [*wins, *opaque]
                )
                if contradictory:
                    journal.append(
                        "PROFILE_STOPPED",
                        slot=slot,
                        authorId=author,
                        reason="source_contract_changed_requires_independent_review",
                    )
                    inactive.add(author)
                    continue
                if not wins and not opaque:
                    journal.append(
                        "PROFILE_STOPPED",
                        slot=slot,
                        authorId=author,
                        reason="no_admissible_current_pre_match_choice_no_restart",
                    )
                    inactive.add(author)
                    continue
                value = dict(
                    schemaVersion="robin-roster-slot-profile-v1",
                    claimId=plan["claimId"],
                    source=source,
                    native=wins,
                    opaque=opaque,
                )
                encoded = canonical(value) + b"\n"
                digest = sha256(encoded).hexdigest()
                with (directory / f"profile-{digest}.json").open("xb") as stream:
                    stream.write(encoded)
                journal.append(
                    "PROFILE_OBSERVATIONS_PREPARED",
                    slot=slot,
                    authorId=author,
                    observedAt=request["observedAt"],
                    observationSha256=digest,
                    count=len(wins) + len(opaque),
                    responseSha256=request["responseSha256"],
                )
                observed.append(author)
                left()
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RecursionError,
            http.client.HTTPException,
        ) as error:
            failure = True
            journal.append("CAMPAIGN_HALTED", slot=slot, reason=type(error).__name__)
        # Reservations are counted by interval because Journal.reserve owns their schema.
        start_sequence = next(
            e["sequence"]
            for e in journal.events
            if e["kind"] == "RUN_STARTED" and e["slot"] == slot
        )
        requests = sum(
            e["kind"] == "REQUEST_RESERVED" and e["sequence"] > start_sequence
            for e in journal.events
        )
        journal.append(
            "RUN_FINISHED",
            slot=slot,
            requests=requests,
            activeMilliseconds=int((time.monotonic() - started) * 1000),
        )
        return dict(
            state="halted"
            if failure
            else "prepared_pending_canary_review"
            if canary
            else "collecting",
            slot=slot,
            requests=requests,
            observedAuthors=observed,
            activeAuthors=[a for a in plan["pool"] if a not in inactive],
        )
    finally:
        (directory / "busy.lock").unlink()


def read_campaign(directory: Path, *, now: datetime | None = None) -> tuple[dict[str, Any], bool]:
    plan, mission = validate_packet(directory)
    validate_registration(directory)
    events = read_events(directory / "events.jsonl")
    completed = [e["slot"] for e in events if e["kind"] == "RUN_FINISHED"]
    halted = any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
    busy = (directory / "busy.lock").exists()
    inactive = {e["authorId"] for e in events if e["kind"] == "PROFILE_STOPPED"}
    picks, observations = _observations(directory, plan, events)
    current = now or datetime.now(UTC)
    starts = [e["slot"] for e in events if e["kind"] == "RUN_STARTED"]
    expected = ["CANARY", *plan["slots"]]
    if (
        starts != expected[: len(starts)]
        or completed != starts[: len(completed)]
        or len(starts) not in (len(completed), len(completed) + 1)
        or (starts != completed and not busy)
    ):
        halted = True
    if (
        1 <= len(completed) < 4
        and current >= instant(plan["slots"][len(completed) - 1]) + timedelta(minutes=2)
        and plan["slots"][len(completed) - 1] not in starts
    ):
        halted = True
    active = [a for a in plan["pool"] if a not in inactive]
    halted = halted or not active
    operational = (
        not halted
        and not busy
        and bool(active)
        and current < instant(mission["expires_at"])
        and len(completed) < 4
    )
    state = (
        "halted"
        if halted
        else "checking"
        if busy
        else "collecting"
        if operational
        else "completed"
        if len(completed) == 4
        else "expired"
    )
    campaign = dict(
        state=state,
        successfulSlots=sum(
            s not in {e.get("slot") for e in events if e["kind"] == "CAMPAIGN_HALTED"}
            for s in completed
        ),
        slots=4,
        requests=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
        requestsMax=133,
        startsAt=plan["slots"][0],
        expiresAt=mission["expires_at"],
        campaignId=plan["id"],
        authorIds=[f"olbg:{a}" for a in active],
        lastObservedAt=max(observations, key=instant) if observations else None,
        profileCount=len(active),
    )
    return dict(
        picks=picks,
        fixtures=plan["fixtures"],
        claimId=plan["claimId"],
        generatedAt=max(observations, key=instant) if observations else plan["canaryNotBefore"],
        rosterCampaign=campaign,
    ), operational
