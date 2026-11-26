"""Bounded positive declarations, with explicit unknown global variant consistency."""

from __future__ import annotations

import http.client
import math
import os
import re
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import notbetting_occurrence_view as accepted
from . import notbetting_recurring_v4 as frozen
from .collector import robots_policy
from .connectors import Journal, Response, canonical, read_events
from .notbetting_collection import _plain
from .notbetting_occurrences import (
    FIELDS,
    OWNER,
    OWNER_KEYS,
    build_occurrences,
    qualify_frozen_journals,
)
from .recurring import instant

DIRECTORY = "cockpit/.ci/notbetting-occurrence-campaign-20261121"
TASK_NAME = "Robin-Tipsters-NotBetting-Occurrences-E2-20261121"
CANARY_IDS = ("e112cc31-2939-4cd2-b65e-e20bd61e050e", "b168b629-22df-497b-9e32-ded520a72a01")
SLOTS = [f"2026-11-21T{hour:02}:00:00Z" for hour in (7, 9, 11)]
CANARY_AT, EXPIRY = "2026-11-21T05:40:00Z", "2026-11-21T11:15:00Z"
EXPECTED = {"unresolved_data_reference", "depth_bound", "cyclic_data_reference"}
PREFIX_SCOPE = "IMMUTABLE_PREFIX_THROUGH_CAPTURE_EVENT"
PIN_PATHS = (
    "src/robin/source_observatory/notbetting_occurrence_campaign.py",
    "src/robin/source_observatory/notbetting_occurrences.py",
    "src/robin/source_observatory/notbetting_occurrence_view.py",
    "src/robin/source_observatory/notbetting_recurring_v4.py",
    "src/robin/source_observatory/connectors.py",
    "src/robin/source_observatory/collector.py",
    "src/robin/source_observatory/public_formats.py",
    "src/robin/source_observatory/recurring.py",
    "src/robin/source_observatory/notbetting_collection.py",
    *(
        "cockpit/scripts/notbetting-occurrence-" + name
        for name in (
            "collect.py",
            "validate.py",
            "read.py",
            "tick.ps1",
            "register.ps1",
            "readstate.ps1",
        )
    ),
)
PRIOR_PINS = dict(
    frozen.PRIOR_PINS,
    **{
        "cockpit/.ci/notbetting-recurring-e2v4-20261121/events.jsonl": "986192f8cfb8ef2225fc9b738b0294e6c9d2309af159d6502c7833da50c0eeea"
    },
)


def code_pins(root: Path) -> dict[str, str]:
    return {
        p: sha256(frozen._bytes(frozen._private(root, p)).replace(b"\r\n", b"\n")).hexdigest()
        for p in PIN_PATHS
    }


def load_baseline(root: Path) -> dict[str, Any]:
    report_raw = frozen._bytes(root / accepted.REPORT)
    raw = frozen._bytes(root / accepted.DIRECTORY / accepted.BUNDLE)
    if (
        sha256(report_raw).hexdigest() != accepted.REPORT_SHA
        or sha256(raw).hexdigest() != accepted.BUNDLE_SHA
        or sha256(frozen._bytes(root / PIN_PATHS[1]).replace(b"\r\n", b"\n")).hexdigest()
        != accepted.QUALIFIER_SHA
    ):
        raise ValueError("accepted E1 anchors")
    bundle = frozen._json(root / accepted.DIRECTORY / accepted.BUNDLE)
    paths = (
        "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl",
        "cockpit/.ci/notbetting-recurring-e2v4-20261121/events.jsonl",
    )
    if (
        qualify_frozen_journals([frozen._bytes(root / p) for p in paths], bundle["fixtures"])
        != bundle["picks"]
    ):
        raise ValueError("accepted E1 reconstruction")
    return bundle


def draft_plan(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(
        workload="POSITIVE_CLOSED_DECLARATIONS_NONCANONICAL",
        packetDirectory=DIRECTORY,
        taskName=TASK_NAME,
        sourceUrl=frozen.SOURCE,
        robotsUrl=frozen.ROBOTS,
        fixtures=deepcopy(fixtures),
        priorReceiptPins=dict(PRIOR_PINS),
        priorGetCount=11,
        priorMilliseconds=29062,
        requestMax=8,
        newTimeMilliseconds=570938,
        familyGetMax=19,
        familyTimeMilliseconds=600000,
        canaryAt=CANARY_AT,
        slots=list(SLOTS),
        expiresAt=EXPIRY,
        codePins={},
        legal={},
    )


def mission_for(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(
        mission_id="NOTBETTING_CLOSED_OCCURRENCE_E2_20261121",
        authorized_stages=["E1", "E2"],
        maximum_stage="E2",
        external_effects={
            "https_get_max": 8,
            "per_source_max": 8,
            "urls": [frozen.ROBOTS, frozen.SOURCE],
        },
        compute_budget=8,
        time_budget=570.938,
        source_hash=frozen._hash(plan),
        expires_at=EXPIRY,
    )


def validate_package(
    root: Path,
    directory: Path,
    digest: str,
    *,
    now: datetime,
    registration: bool = False,
    historical: bool = False,
) -> dict[str, Any]:
    if directory.resolve() != frozen._private(root, DIRECTORY):
        raise ValueError("canonical packet directory")
    if not historical:
        frozen._transport_environment()
    plan, mission, approval = (
        frozen._json(directory / n) for n in ("plan.json", "mission.json", "approval.json")
    )
    baseline = load_baseline(root)
    expected = draft_plan(baseline["fixtures"])
    expected.update(codePins=code_pins(root), legal=plan["legal"])
    if plan != expected or frozen._hash(plan) != digest or mission != mission_for(plan):
        raise ValueError("exact immutable packet")
    if not historical and now >= instant(EXPIRY):
        raise ValueError("expired authority")
    for p, h in PRIOR_PINS.items():
        if sha256(frozen._bytes(root / p)).hexdigest() != h:
            raise ValueError("prior debt anchor")
    legal = plan["legal"]
    if (
        legal["sha256"] != frozen.LEGAL_SHA
        or legal["observedAt"] != "2026-11-20T16:15:14.330276Z"
        or sha256(frozen._bytes(frozen._private(root, legal["path"]))).hexdigest()
        != frozen.LEGAL_SHA
        or instant(EXPIRY) - instant(legal["observedAt"]) > timedelta(hours=24)
    ):
        raise ValueError("dated legal proof")
    record = frozen._ledger_record(root, approval["decisionId"], approval["decisionHash"])
    if (
        record["record_type"] != "DECISION"
        or record["decision"] != "PASS_AND_SCALE"
        or record["context"]
        != dict(
            planSha256=digest,
            manifestSha256=frozen._hash(mission),
            keys=["C0", "C1", "C4"],
            scaleDecision="SCALE_APPROVED",
            workload=plan["workload"],
        )
    ):
        raise ValueError("exact three-key workload authority")
    if registration:
        validate_canary(root, directory, digest)
        grant = frozen._json(directory / "task-authorization.json")
        decision = frozen._ledger_record(root, grant["decisionId"], grant["decisionHash"])
        events = read_events(directory / "events.jsonl")
        canary = [e for e in events if e["kind"] == "CAPTURE_COMMITTED" and e["slot"] == "canary"]
        if (
            len(canary) != 1
            or grant["canaryEventHash"] != canary[0]["hash"]
            or grant["planSha256"] != digest
            or decision["decision"] != "PASS_AND_HOLD"
            or decision["context"]
            != {k: v for k, v in grant.items() if k not in {"decisionHash", "decisionId"}}
            or grant["keys"] != ["C0", "C1", "C2", "C4"]
            or grant["kind"] != "TASK_REGISTRATION_SEPARATE"
        ):
            raise ValueError("separate four-key task authorization")
    return dict(plan=plan, mission=mission, baseline=baseline)


def _locked_slot(directory: Path, digest: str) -> str | None:
    path = directory / "busy.lock"
    if not path.exists():
        return None
    owner = frozen._json(path)
    if owner.get("planSha256") != digest or owner.get("slot") not in ["canary", *SLOTS]:
        raise ValueError("unidentified unfinished owner")
    return str(owner["slot"])


def _completed_passes(
    events: list[dict[str, Any]], *, pending_slot: str | None = None
) -> list[dict[str, Any]]:
    invalidated = {e.get("slot") for e in events if e["kind"] == "CAMPAIGN_HALTED"}
    if pending_slot is not None:
        invalidated.add(pending_slot)
    return [e for e in events if e["kind"] == "PASS_COMPLETED" and e.get("slot") not in invalidated]


def _stable_snapshot(directory: Path, digest: str) -> tuple[list[dict[str, Any]], str | None]:
    events = read_events(directory / "events.jsonl")
    pending = _locked_slot(directory, digest)
    after = read_events(directory / "events.jsonl")
    if (events[-1]["hash"] if events else None) != (after[-1]["hash"] if after else None):
        raise ValueError("transient journal snapshot changed")
    return events, pending


def validate_canary(root: Path, directory: Path, digest: str, *, live: bool = True) -> None:
    proof = frozen._json(directory / "canary-acceptance.json")
    record = frozen._ledger_record(root, proof["decisionId"], proof["decisionHash"])
    events, pending_slot = _stable_snapshot(directory, digest)
    canary = [e for e in events if e["kind"] == "CAPTURE_COMMITTED" and e["slot"] == "canary"]
    if (
        len(canary) != 1
        or proof["planSha256"] != digest
        or proof["canaryEventHash"] != canary[0]["hash"]
        or proof["keys"] != ["C0", "C1", "C2", "C4"]
        or record["record_type"] != "DECISION"
        or record["decision"] != "PASS_AND_HOLD"
        or record["context"]
        != {k: v for k, v in proof.items() if k not in {"decisionId", "decisionHash"}}
    ):
        raise ValueError("exact four-key canary acceptance")
    finished = [
        e
        for e in _completed_passes(events, pending_slot=pending_slot)
        if e["slot"] == "canary" and e["captureEventHash"] == canary[0]["hash"]
    ]
    if len(finished) != 1:
        raise ValueError("canary completion absent")
    capture = read_capture(directory, canary[0], digest)
    if not set(CANARY_IDS) <= {p["sourceTipId"] for p in capture["rows"]}:
        raise ValueError("canary baseline reobservation")
    if live and (
        any(e["kind"] == "CAMPAIGN_HALTED" for e in events)
        or any((directory / p).exists() for p in ("halt.flag", "busy.lock"))
    ):
        raise ValueError("halted workload")


def _row(row: dict[str, Any], fixtures: list[dict[str, Any]], observed: datetime) -> None:
    fields = row["sourceFields"]
    if (
        not FIELDS <= set(fields)
        or set(fields) - FIELDS - {"createdAt"}
        or not frozen.UUID.fullmatch(fields["id"])
        or any(fields[k] != OWNER for k in OWNER_KEYS)
        or fields["tipster.user.username"] != "ELIMAGAR"
        or fields["competition"] != "Premier League"
        or any(not _plain(fields[k]) for k in ("event", "pick", "competition"))
        or row["sourceRecordFingerprint"] != frozen._hash(fields)
        or row["selection"] != fields["pick"]
        or instant(row["observedAt"]) != observed
    ):
        raise ValueError("independent closed native row validation")
    names = re.split(r"\s+[-–]\s+", fields["event"])
    matched = [
        f
        for f in fixtures
        if len(names) == 2
        and names[0].casefold() in {a.casefold() for a in f["homeAliases"]}
        and names[1].casefold() in {a.casefold() for a in f["awayAliases"]}
    ]
    if (
        len(matched) != 1
        or instant(fields["date"]) != instant(matched[0]["kickoff"])
        or observed >= instant(matched[0]["kickoff"])
    ):
        raise ValueError("own date and oriented pre-KO fixture")
    if (
        row["id"] != "notbetting-tip:" + fields["id"]
        or row["sourceTipId"] != fields["id"]
        or row["sourceId"] != "NotBetting"
        or row["fixtureId"] != matched[0]["id"]
        or instant(row["kickoff"]) != instant(matched[0]["kickoff"])
        or row["authorId"] != "public:" + sha256(("notbetting:" + OWNER).encode()).hexdigest()
        or any(
            row.get(k) is not False
            for k in (
                "performanceEvaluationAllowed",
                "settlementAllowed",
                "marketInterpretationAllowed",
            )
        )
    ):
        raise ValueError("native row identity or scientific restrictions")


def validate_projection(
    value: dict[str, Any], fixtures: list[dict[str, Any]], observed: datetime
) -> list[dict[str, Any]]:
    if (
        set(value["reasons"]) - EXPECTED
        or value["walkBoundHit"]
        or value["omittedAdmissible"]
        or not 0 < len(value["picks"]) <= 20
        or len({p["id"] for p in value["picks"]}) != len(value["picks"])
    ):
        raise ValueError("fatal bounded projection")
    for row in value["picks"]:
        _row(row, fixtures, observed)
    return deepcopy(value["picks"])


def add_observation(
    state: dict[str, Any],
    row: dict[str, Any],
    observation: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> None:
    _row(row, fixtures, instant(observation["observedAt"]))
    entry = state.setdefault(
        row["id"], dict(row=deepcopy(row), observations=[], state="PENDING_NONCANONICAL")
    )
    if entry["row"]["sourceRecordFingerprint"] != row["sourceRecordFingerprint"]:
        raise ValueError("native conflict veto")
    observations = entry["observations"]
    if any(
        (o["journalSha256"], o["eventHash"])
        == (observation["journalSha256"], observation["eventHash"])
        for o in observations
    ):
        return
    if observations and instant(observation["observedAt"]) <= instant(
        observations[-1]["observedAt"]
    ):
        raise ValueError("distinct increasing temporal captures required")
    observations.append(deepcopy(observation))
    if len(observations) >= 2:
        captures = [
            dict(
                o,
                sourceUrl=frozen.SOURCE,
                reasons=o["reasons"] or ["scope:CLOSED_NATIVE_OCCURRENCE_ONLY"],
                rows=[dict(row, observedAt=o["observedAt"])],
            )
            for o in (observations[0], observations[-1])
        ]
        declaration = build_occurrences(captures, fixtures)[0]
        declaration.update(observations=deepcopy(observations), observationCount=len(observations))
        entry.update(state="DECLARED_NONCANONICAL", declaration=declaration)


def _write(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_capture(directory: Path, committed: dict[str, Any], digest: str) -> dict[str, Any]:
    receipt_raw = frozen._bytes(frozen._private(directory, committed["receiptFile"]))
    if (
        committed["receiptFile"] != "receipt-" + committed["receiptSha256"] + ".json"
        or sha256(receipt_raw).hexdigest() != committed["receiptSha256"]
    ):
        raise ValueError("capture receipt hash")
    receipt = frozen._json(directory / committed["receiptFile"])
    prefix_path = frozen._private(directory, receipt["prefixFile"])
    prefix = frozen._bytes(prefix_path)
    events = read_events(prefix_path)
    event = events[-1]
    if (
        committed not in read_events(directory / "events.jsonl")
        or receipt["scope"] != PREFIX_SCOPE
        or receipt["planSha256"] != digest
        or receipt["planSha256"] != event["planSha256"]
        or receipt["planSha256"] != committed["planSha256"]
        or event["slot"] != committed["slot"]
        or receipt["prefixFile"] != "prefix-" + event["hash"] + ".jsonl"
        or len(prefix) != receipt["rawLength"]
        or sha256(prefix).hexdigest() != receipt["prefixSha256"]
        or event["hash"] != receipt["headHash"]
        or event["sequence"] != receipt["sequence"]
        or event["kind"] != "CAPTURE_CLOSED"
        or not frozen._bytes(directory / "events.jsonl").startswith(prefix)
    ):
        raise ValueError("actual immutable journal prefix")
    received = [
        e
        for e in events
        if e["kind"] == "REQUEST_FINISHED"
        and e.get("url") == frozen.SOURCE
        and e.get("slot") == event["slot"]
        and e.get("status") == 200
    ]
    if (
        len(received) != 1
        or received[0]["responseSha256"] != event["responseSha256"]
        or received[0]["parserSha256"] != event["parserSha256"]
    ):
        raise ValueError("closed capture source response binding")
    observation = dict(
        observedAt=event["observedAt"],
        responseSha256=event["responseSha256"],
        parserSha256=event["parserSha256"],
        journalSha256=receipt["prefixSha256"],
        eventHash=event["hash"],
        journalHashScope=PREFIX_SCOPE,
        captureReceiptSha256=committed["receiptSha256"],
        reasons=event["diagnostics"]["reasons"],
    )
    return dict(rows=event["rows"], observation=observation, planSha256=receipt["planSha256"])


def read_state(
    root: Path, directory: Path, digest: str, *, include_unfinished: bool = False
) -> dict[str, Any]:
    baseline = load_baseline(root)
    state: dict[str, Any] = {}
    for row in baseline["picks"]:
        for observation in row["observations"]:
            add_observation(
                state,
                dict(row, observedAt=observation["observedAt"]),
                observation,
                baseline["fixtures"],
            )
    if include_unfinished:
        events, pending_slot = read_events(directory / "events.jsonl"), None
    else:
        events, pending_slot = _stable_snapshot(directory, digest)
    completed = {
        e["captureEventHash"] for e in _completed_passes(events, pending_slot=pending_slot)
    }
    for event in events:
        if event["kind"] == "CAPTURE_COMMITTED":
            if not include_unfinished and event["hash"] not in completed:
                continue
            capture = read_capture(directory, event, digest)
            for row in capture["rows"]:
                add_observation(state, row, capture["observation"], baseline["fixtures"])
    return state


def read_view(
    root: Path, directory: Path, digest: str, *, now: datetime, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    validate_package(root, directory, digest, now=now, historical=True)
    validate_canary(root, directory, digest, live=False)
    state = read_state(root, directory, digest)
    return merge_view(base, state) if base is not None else dict(state=state, active=False)


def merge_view(base: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    rows = {p["id"]: p for p in data["picks"]}
    updates = {}
    for identifier, entry in state.items():
        if entry["state"] != "DECLARED_NONCANONICAL":
            continue
        declaration = entry["declaration"]
        if identifier in rows:
            if any(
                rows[identifier].get(k) != declaration[k]
                for k in ("selection", "fixtureId", "kickoff", "authorId")
            ):
                raise ValueError("existing E1 identity conflict")
        else:
            rows[identifier] = deepcopy(declaration)
        updates[identifier] = dict(
            lastObservedAt=declaration["lastObservedAt"], observations=entry["observations"]
        )
    clocks = [v["lastObservedAt"] for v in updates.values()] + (
        [data["sourceObservedThrough"]] if data.get("sourceObservedThrough") else []
    )
    data.update(
        picks=list(rows.values()),
        distinctPicks=len(rows),
        notbettingOccurrenceCompanion=dict(
            updates=deepcopy(updates),
            pending=sum(v["state"] == "PENDING_NONCANONICAL" for v in state.values()),
            active=False,
        ),
    )
    if clocks:
        data["sourceObservedThrough"] = max(clocks, key=instant)
        data["generatedAt"] = max(
            [*clocks, *([data["generatedAt"]] if data.get("generatedAt") else [])], key=instant
        )
    data["authorCount"] = len({p["authorId"] for p in rows.values()})
    return data


def execute_pass(
    root: Path,
    directory: Path,
    digest: str,
    slot: str,
    *,
    get: Callable[..., Response] = frozen.public_get,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    begun = monotonic()
    packet = validate_package(root, directory, digest, now=now(), registration=slot != "canary")
    if slot not in ["canary", *SLOTS]:
        raise ValueError("fixed slot required")
    start = instant(CANARY_AT if slot == "canary" else slot)
    try:
        lock = (directory / "busy.lock").open("xb")
    except FileExistsError:
        if not (directory / "halt.flag").exists():
            _write(directory / "halt.flag", b"busy_or_orphan\n")
        return dict(state="halted", active=False)
    journal: Journal | None = None
    try:
        lock.write(canonical(dict(planSha256=digest, slot=slot)) + b"\n")
        lock.flush()
        os.fsync(lock.fileno())
        journal = Journal(directory, packet["mission"], now=now)
        if (directory / "halt.flag").exists() or any(
            e["kind"] == "CAMPAIGN_HALTED" for e in journal.events
        ):
            return dict(state="halted", active=False)
        if any(e["slot"] == slot for e in _completed_passes(journal.events)):
            return dict(state="duplicate", active=False)
        previous = max((e.get("elapsedMilliseconds", 0) for e in journal.events), default=0)

        def elapsed() -> int:
            return previous + 5000 + math.ceil((monotonic() - begun) * 1000)

        def guard(required: int = 5) -> None:
            frozen._transport_environment()
            current = now()
            if (
                (directory / "halt.flag").exists()
                or current < start
                or min(
                    (instant(EXPIRY) - current).total_seconds(),
                    (start + timedelta(seconds=120) - current).total_seconds(),
                    100 - monotonic() + begun,
                    (570938 - elapsed()) / 1000,
                )
                <= required
            ):
                raise ValueError("window or durable time guard")

        _write(directory / ("slot-" + sha256(slot.encode()).hexdigest() + ".lock"), digest.encode())
        if any(
            instant(s) < start
            and not any(e["slot"] == s for e in _completed_passes(journal.events))
            for s in SLOTS
        ):
            raise ValueError("missed predecessor")
        guard()
        journal.append("PASS_STARTED", slot=slot, elapsedMilliseconds=elapsed())

        def request(url: str) -> Response:
            guard(17)
            if journal is None:
                raise ValueError("journal unavailable")
            if sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events) >= 8:
                raise ValueError("new request budget")
            journal.append("REQUEST_RESERVED", slot=slot, url=url, elapsedMilliseconds=elapsed())
            guard(17)
            before = monotonic()
            response = get(url, timeout=12.0)
            guard()
            if monotonic() - before >= 12 or response.status != 200 or response.location:
                raise ValueError("transport refused")
            journal.append(
                "REQUEST_FINISHED",
                slot=slot,
                url=url,
                status=200,
                parserSha256=packet["plan"]["codePins"][PIN_PATHS[3]],
                responseSha256=sha256(response.body).hexdigest(),
                elapsedMilliseconds=elapsed(),
            )
            guard()
            return response

        robots = request(frozen.ROBOTS)
        text = robots.body.decode("utf-8", errors="strict")
        if (
            robots.content_type.split(";")[0].strip().lower() != "text/plain"
            or len(robots.body) > 64000
            or re.search(r"[<\x00]|captcha|challenge|cf-chl", text, re.I)
        ):
            raise ValueError("robots technical document")
        allowed, delay = robots_policy(text, frozen.SOURCE)
        if not allowed or not math.isfinite(delay) or not 0 <= delay <= 30:
            raise ValueError("robots refusal")
        sleep(max(3, delay))
        guard()
        response = request(frozen.SOURCE)
        observed = now()
        state = read_state(root, directory, digest)
        projected = frozen.qualify_documents(
            frozen.decode_capture(response.body, response.content_type),
            packet["plan"]["fixtures"],
            observed,
            response_sha=sha256(response.body).hexdigest(),
            parser_sha=packet["plan"]["codePins"][PIN_PATHS[3]],
            known=[v["row"] for v in state.values()],
        )
        guard()
        journal.append(
            "PROJECTION_ASSESSED",
            slot=slot,
            diagnostics={
                k: projected[k]
                for k in (
                    "reasons",
                    "traversalComplete",
                    "visitedNodes",
                    "depthBoundHit",
                    "walkBoundHit",
                    "omittedAdmissible",
                    "omittedWitnesses",
                )
                if k in projected
            },
            retainedRows=len(projected["picks"]),
            elapsedMilliseconds=elapsed(),
        )
        guard()
        rows = validate_projection(projected, packet["plan"]["fixtures"], observed)
        if slot == "canary" and not set(CANARY_IDS) <= {p["sourceTipId"] for p in rows}:
            raise ValueError("both accepted baseline IDs must be reobserved")
        for row in rows:
            if (
                row["id"] in state
                and state[row["id"]]["row"]["sourceRecordFingerprint"]
                != row["sourceRecordFingerprint"]
            ):
                raise ValueError("encountered native conflict")
        guard()
        event = journal.append(
            "CAPTURE_CLOSED",
            slot=slot,
            planSha256=digest,
            rows=rows,
            observedAt=observed.isoformat(),
            diagnostics={k: v for k, v in projected.items() if k != "picks"},
            responseSha256=sha256(response.body).hexdigest(),
            parserSha256=packet["plan"]["codePins"][PIN_PATHS[3]],
            elapsedMilliseconds=elapsed(),
        )
        del response
        prefix = b"".join(canonical(e) + b"\n" for e in journal.events)
        prefix_name = "prefix-" + event["hash"] + ".jsonl"
        _write(directory / prefix_name, prefix)
        receipt = (
            canonical(
                dict(
                    scope=PREFIX_SCOPE,
                    prefixFile=prefix_name,
                    prefixSha256=sha256(prefix).hexdigest(),
                    rawLength=len(prefix),
                    headHash=event["hash"],
                    sequence=event["sequence"],
                    planSha256=digest,
                )
            )
            + b"\n"
        )
        receipt_sha = sha256(receipt).hexdigest()
        name = "receipt-" + receipt_sha + ".json"
        _write(directory / name, receipt)
        guard()
        committed = journal.append(
            "CAPTURE_COMMITTED",
            slot=slot,
            planSha256=digest,
            receiptFile=name,
            receiptSha256=receipt_sha,
            elapsedMilliseconds=elapsed(),
        )
        read_state(root, directory, digest, include_unfinished=True)
        guard()
        journal.append(
            "PASS_COMPLETED",
            slot=slot,
            captureEventHash=committed["hash"],
            elapsedMilliseconds=elapsed(),
        )
        guard()
        return dict(
            state="canary_pending_review" if slot == "canary" else "completed",
            eventHash=committed["hash"],
            active=False,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        http.client.HTTPException,
    ) as exc:
        if journal is not None:
            journal.append(
                "CAMPAIGN_HALTED",
                reason=type(exc).__name__,
                slot=slot,
                elapsedMilliseconds=elapsed(),
                active=False,
            )
        return dict(state="halted", active=False)
    finally:
        lock.close()
        (directory / "busy.lock").unlink()
