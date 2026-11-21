"""Draft bounded NotBetting E2 executor and offline projection; no implicit authority."""

from __future__ import annotations

import http.client
import ipaddress
import json
import math
import os
import queue
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .collector import USER_AGENT, robots_policy
from .connectors import Journal, Response, canonical, read_events, stamp
from .notbetting_collection import _load as load_e1
from .public_formats import _Node, _Tree, check_declarations, decode_document
from .recurring import instant

SOURCE = "https://notbetting.com/en/tipsters-league/picks"
ROBOTS = "https://notbetting.com/robots.txt"
OWNER = "67766b69-620e-48f8-b395-5d7fadfc2679"
CANARY_ID = "e112cc31-2939-4cd2-b65e-e20bd61e050e"
TASK_NAME = "Robin-Tipsters-NotBetting-ELIMAGAR-E2V4-20261121"
PACKET_DIRECTORY = "cockpit/.ci/notbetting-recurring-e2v4-20261121"
PARENT_CALENDAR_SHA = "2feb3b728d9fd64cec95f4f8b7f4376f5e550441eae8b4e96f7edd0fd1bea8e8"
LEGAL_SHA = "d74a26c5d2b6ceedf663a52eda4aa18c84694b257a14970f17ab3f179c48967a"
PRIOR_PINS = {
    "cockpit/.ci/linked-choice-routes-v2-20261121/events.jsonl": "b730f3de7ec59e6d4d1b7c3e63c74d5f718d74ce899fd92728ec9df0ae6502e8",
    "cockpit/.ci/notbetting-collective-capacity-20261121/events.jsonl": "e032c6eb32babbda146bf02610c4a245b693a0b31becc011195510a53ceb4162",
    "cockpit/.ci/notbetting-prospective-0130-v2-20261121/events.jsonl": "09377b3f1f40a50ab28ad1e0819c5041f7eb963a82dd35cd7d505e9f0540999a",
    "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl": "3e7269678e799b65000ec70d028e02c227ab4a7ecb2c32821915e38eb1765a35",
}
PIN_PATHS = (
    "src/robin/source_observatory/notbetting_recurring_v4.py",
    "src/robin/source_observatory/notbetting_collection.py",
    "src/robin/source_observatory/connectors.py",
    "src/robin/source_observatory/collector.py",
    "src/robin/source_observatory/public_formats.py",
    "src/robin/source_observatory/recurring.py",
    "cockpit/scripts/notbetting-v4-collect.py",
    "cockpit/scripts/notbetting-v4-validate.py",
    "cockpit/scripts/notbetting-v4-read.py",
    "cockpit/scripts/notbetting-v4-tick.ps1",
    "cockpit/scripts/notbetting-v4-register.ps1",
    "cockpit/scripts/notbetting-v4-readstate.ps1",
)
SLOTS = [f"2026-11-21T{hour:02}:00:00Z" for hour in (5, 7, 9, 11)]
EXPIRY = "2026-11-21T11:15:00Z"
UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")
HASH = re.compile(r"[a-f0-9]{64}")
SKIP = re.compile(
    r"stats|statistics|recommend|suggest|reco|analysis|description|biography|contact", re.I
)
GATES = ("requiresSubscription", "requiresPayment", "requiresAuthentication", "paywall")


def _hash(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def _bytes(path: Path, maximum: int = 2_000_000) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("local artifact bound")
    return value


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise ValueError("local object required")
    return value


def _private(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("relative repository path required")
    return path


def code_pins(root: Path) -> dict[str, str]:
    return {
        name: sha256(_bytes(_private(root, name)).replace(b"\r\n", b"\n")).hexdigest()
        for name in PIN_PATHS
    }


def baseline_choices(root: Path) -> list[dict[str, Any]]:
    return list(load_e1(root)["picks"])


def _transport_environment() -> None:
    if any(key in os.environ for key in ("SSLKEYLOGFILE", "SSL_CERT_FILE", "SSL_CERT_DIR")):
        raise ValueError("TLS environment override refused")


def draft_plan(fixtures: list[dict[str, Any]], *, canary_at: str) -> dict[str, Any]:
    """Template only. Pins and approval must be supplied by the independent Council."""
    return dict(
        schemaVersion="robin-notbetting-recurring-e2-v4",
        ownerUuid=OWNER,
        username="ELIMAGAR",
        sourceUrl=SOURCE,
        robotsUrl=ROBOTS,
        taskName=TASK_NAME,
        packetDirectory=PACKET_DIRECTORY,
        fixtures=deepcopy(fixtures),
        parentCalendar={},
        legal={},
        codePins={},
        priorReceiptPins=dict(PRIOR_PINS),
        priorGetCount=9,
        priorMilliseconds=19812,
        requestMax=10,
        familyGetMax=19,
        familyTimeMilliseconds=600000,
        newTimeMilliseconds=580188,
        slots=list(SLOTS),
        canaryAt=canary_at,
        expiresAt=EXPIRY,
        slotWindowSeconds=120,
        passSeconds=100,
        timeoutSeconds=12,
        finalizationSeconds=5,
        spacingSeconds=3,
        maxPicks=20,
        maxWitnesses=3,
    )


def mission_for(plan: dict[str, Any]) -> dict[str, Any]:
    return dict(
        mission_id="NOTBETTING_ELIMAGAR_E2V4_SCALAR_CORRECTION_20261121",
        authorized_stages=["E1", "E2"],
        maximum_stage="E2",
        external_effects={"https_get_max": 10, "per_source_max": 10, "urls": [ROBOTS, SOURCE]},
        compute_budget=10,
        time_budget=580.188,
        source_hash=_hash(plan),
        expires_at=EXPIRY,
    )


def _ledger_record(root: Path, identifier: str, digest: str) -> dict[str, Any]:
    previous = "0" * 64
    found: dict[str, Any] | None = None
    for line in _bytes(root / "reports/council/decision-ledger.jsonl", 16_000_000).splitlines():
        record = json.loads(line)
        body = {k: v for k, v in record.items() if k != "hash"}
        if record.get("previous_hash") != previous or _hash(body) != record.get("hash"):
            raise ValueError("Council ledger chain")
        previous = record["hash"]
        if record.get("decision_id") == identifier:
            if found is not None or record["hash"] != digest:
                raise ValueError("Council decision identity")
            found = record
    if found is None:
        raise ValueError("Council decision absent")
    return found


def validate_package(
    root: Path,
    directory: Path,
    expected_sha: str,
    *,
    now: datetime,
    registration: bool = False,
    historical: bool = False,
) -> dict[str, Any]:
    """Read-only, fail closed. Validation never creates a packet or grants authority."""
    if directory.resolve() != _private(root, PACKET_DIRECTORY):
        raise ValueError("canonical packet directory required")
    if not historical:
        _transport_environment()
    plan, mission, approval = (
        _json(directory / n) for n in ("plan.json", "mission.json", "approval.json")
    )
    if not HASH.fullmatch(expected_sha) or _hash(plan) != expected_sha:
        raise ValueError("plan hash")
    template = draft_plan(plan["fixtures"], canary_at=plan["canaryAt"])
    for key in ("parentCalendar", "legal", "codePins"):
        template[key] = plan[key]
    if plan != template or mission != mission_for(plan):
        raise ValueError("immutable plan or manifest")
    if plan["codePins"] != code_pins(root):
        raise ValueError("code pin drift")
    if now.tzinfo is None or (not historical and now >= instant(EXPIRY)):
        raise ValueError("authority expired")
    canary_at = instant(plan["canaryAt"])
    if (
        plan["canaryAt"] != "2026-11-21T04:35:00Z"
        or canary_at.date() != instant(SLOTS[0]).date()
        or canary_at + timedelta(seconds=120) >= instant(SLOTS[0])
    ):
        raise ValueError("distinct prospective canary window")
    parent_pin = plan["parentCalendar"]
    parent_raw = _bytes(_private(root, parent_pin["path"]))
    parent = json.loads(parent_raw)["fixtures"]
    if (
        sha256(parent_raw).hexdigest() != parent_pin["sha256"]
        or _hash(parent) != PARENT_CALENDAR_SHA
    ):
        raise ValueError("parent calendar pin")
    selected = [f for f in parent if f["id"].startswith("epl-")]
    if (
        len(parent) != 14
        or len(selected) != 5
        or canonical(selected) != canonical(plan["fixtures"])
    ):
        raise ValueError("five Premier League fixtures required")
    legal = plan["legal"]
    if (
        legal["sha256"] != LEGAL_SHA
        or sha256(_bytes(_private(root, legal["path"]))).hexdigest() != LEGAL_SHA
        or legal["observedAt"] != "2026-11-20T16:15:14.330276Z"
        or instant(EXPIRY) - instant(legal["observedAt"]) > timedelta(hours=24)
    ):
        raise ValueError("dated legal proof")
    if plan["priorReceiptPins"] != PRIOR_PINS:
        raise ValueError("family receipt pins")
    for path, digest in PRIOR_PINS.items():
        if sha256(_bytes(_private(root, path))).hexdigest() != digest:
            raise ValueError("family receipt changed")
    record = _ledger_record(root, approval["decisionId"], approval["decisionHash"])
    context = record["context"]
    if (
        record["record_type"] != "DECISION"
        or record["decision"] != "PASS_AND_SCALE"
        or context.get("scaleDecision") != "SCALE_APPROVED"
        or context.get("keys") != ["C0", "C1", "C4"]
        or context.get("planSha256") != expected_sha
        or context.get("manifestSha256") != _hash(mission)
        or approval.get("planSha256") != expected_sha
        or approval.get("manifestSha256") != _hash(mission)
    ):
        raise ValueError("exact scale authority absent")
    baseline = baseline_choices(root)
    if registration:
        validate_canary(root, directory, expected_sha)
        if read_companion(directory)["halted"]:
            raise ValueError("halted campaign")
    return dict(plan=plan, mission=mission, baseline=baseline)


def validate_canary(root: Path, directory: Path, plan_sha: str) -> None:
    acceptance = _json(directory / "canary-acceptance.json")
    record = _ledger_record(root, acceptance["decisionId"], acceptance["decisionHash"])
    events = read_events(directory / "events.jsonl")
    accepted = [e for e in events if e["kind"] == "PASS_FINISHED" and e.get("slot") == "canary"]
    context = {k: v for k, v in acceptance.items() if k != "decisionHash"}
    if (
        len(accepted) != 1
        or context.get("planSha256") != plan_sha
        or context.get("keys") != ["C0", "C1", "C2", "C4"]
        or context.get("canaryEventHash") != accepted[0]["hash"]
        or record["record_type"] != "DECISION"
        or record["decision"] != "PASS_AND_HOLD"
        or record["context"] != context
    ):
        raise ValueError("four-key canary acceptance absent")


def decode_capture(body: bytes, content_type: str) -> dict[str, Any]:
    """Decode bounded Next Flight JSON fragments without JavaScript execution."""
    if len(body) > 4_000_000 or "html" not in content_type.lower():
        raise ValueError("NotBetting body bound/type")
    text = decode_document(body, content_type)
    check_declarations(text)
    if re.search(
        r"cf-chl-|/challenge-platform/|<title[^>]*>\s*(Just a moment|Access denied)", text, re.I
    ):
        raise ValueError("source challenge")
    tree = _Tree()
    tree.feed(text)
    tree.close()
    decoder = json.JSONDecoder()
    fragments: list[str] = []
    documents: dict[str, Any] = {}
    imports: set[str] = set()
    nodes = [tree.root]
    while nodes:
        node = nodes.pop()
        nodes.extend(c for c in reversed(node.children) if isinstance(c, _Node))
        if node.tag != "script" or "src" in node.attrs:
            continue
        script = "".join(c for c in node.children if isinstance(c, str))
        media = (node.attrs.get("type") or "").split(";")[0].strip().lower()
        if node.attrs.get("id") == "__NEXT_DATA__":
            if media != "application/json":
                continue
            value = json.loads(script)
            if "next_data" in documents and documents["next_data"] != value:
                raise ValueError("contradictory Next data document")
            documents["next_data"] = value
            continue
        if media not in {"", "text/javascript", "application/javascript"}:
            continue
        remainder = script.strip()
        local_fragments: list[str] = []
        while remainder:
            prefix = re.match(
                r"(?:self\.__next_f\.push|\(self\.__next_f=self\.__next_f\|\|\[\]\)\.push)\(\s*",
                remainder,
            )
            if not prefix:
                local_fragments = []
                break
            value, size = decoder.raw_decode(remainder[prefix.end() :])
            tail = remainder[prefix.end() + size :]
            suffix = re.match(r"\s*\)\s*;?\s*", tail)
            if not suffix:
                local_fragments = []
                break
            remainder = tail[suffix.end() :]
            if (
                isinstance(value, list)
                and len(value) == 2
                and value[0] == 1
                and isinstance(value[1], str)
            ):
                local_fragments.append(value[1])
        fragments.extend(local_fragments)
        if len(fragments) > 4096:
            raise ValueError("Flight fragment bound")
    stream = "".join(fragments)
    if len(stream) > 4_000_000:
        raise ValueError("Flight byte bound")
    for line in stream.splitlines():
        match = re.fullmatch(r"([a-f0-9]+):(.*)", line, re.I)
        if not match:
            continue
        key = match[1].lower()
        payload = match[2]
        is_import = payload.startswith("I")
        try:
            value, end = decoder.raw_decode(payload[1:] if is_import else payload)
        except ValueError:
            continue  # Unsupported records cannot satisfy a reachable data reference.
        if (payload[1:] if is_import else payload)[end:].strip():
            continue
        if is_import:
            if not isinstance(value, list) or key in documents:
                raise ValueError("invalid or contradictory Flight import")
            imports.add(key)
            continue
        if key in imports:
            raise ValueError("contradictory Flight import/data document")
        if key in documents and documents[key] != value:
            raise ValueError("contradictory Flight document")
        documents[key] = value
    if imports:
        documents["__flight_import_ids"] = sorted(imports)
    return documents


def _plain(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 160
        and not re.search(r"[\x00-\x1f]|https?://|@|\+?\d[\d ()-]{8,}\d", value)
    )


def _identity(row: dict[str, Any]) -> bytes:
    fields = row["sourceFields"]
    return canonical(
        [
            row["sourceTipId"],
            fields["tipsterId"],
            fields["event"],
            fields["date"],
            row["selection"],
            fields.get("competition"),
        ]
    )


def retain_prior_unaccepted_clock(row: dict[str, Any], events: list[dict[str, Any]]) -> None:
    """Reuse an exact version's observation clock, never its rejected admission."""
    matches = []
    for event in events:
        if event.get("kind") != "PASS_REJECTED":
            continue
        for prior in event.get("projection", {}).get("picks", []):
            fields = prior["sourceFields"]
            closed = [
                fields.get(k)
                for k in (
                    "tipsterId",
                    "tipster.user.id",
                    "tipster.user.tipster.id",
                    "tipster.user.tipster.userId",
                )
            ] == [OWNER] * 4 and fields.get("tipster.user.username") == "ELIMAGAR"
            if (
                closed
                and _identity(prior) == _identity(row)
                and instant(prior["observedAt"]) < instant(row["observedAt"])
            ):
                matches.append((prior, event["hash"]))
    if matches:
        prior, event_hash = min(matches, key=lambda pair: instant(pair[0]["observedAt"]))
        path = "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl"
        row.update(
            firstSeenAt=prior["observedAt"],
            priorUnacceptedObservedAt=prior["observedAt"],
            priorUnacceptedObservation=dict(
                path=path, sha256=PRIOR_PINS[path], eventHash=event_hash
            ),
        )


def qualify_documents(
    documents: dict[str, Any],
    fixtures: list[dict[str, Any]],
    observed: datetime,
    *,
    response_sha: str,
    parser_sha: str,
    known: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Own closed records only. Newly observed IDs require no historical comparison."""
    if not HASH.fullmatch(response_sha) or not HASH.fullmatch(parser_sha):
        raise ValueError("capture provenance hash")
    result: dict[str, Any] = dict(
        status="qualified",
        reason="",
        picks=[],
        witnesses=[],
        omittedAdmissible=0,
        omittedWitnesses=0,
        excludedOtherOwners=0,
        reasons=[],
        traversalComplete=True,
        visitedNodes=0,
        depthBoundHit=False,
        walkBoundHit=False,
        witnessSampleLimited=False,
    )
    seen: dict[str, bytes] = {}
    owned: set[str] = set()
    conflicts: set[str] = set()
    invalid_ids: set[str] = set()
    known_ids = {p["sourceTipId"]: p for p in known or []}
    visited = 0

    def reject(reason: str) -> None:
        if reason not in result["reasons"]:
            result["reasons"].append(reason)
        result.update(status="partial", reason=result["reasons"][0])

    def resolve(value: Any, chain: tuple[str, ...] = ()) -> Any:
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        key = value.removeprefix("$").removeprefix("@").removeprefix("L")
        if key not in documents or key in chain or len(chain) >= 12:
            raise ValueError("unresolved local reference")
        return resolve(documents[key], (*chain, key))

    def witness(identifier: str, reason: str) -> None:
        if len(result["witnesses"]) < 3:
            result["witnesses"].append(dict(sourceTipId=identifier, reason=reason, admitted=False))
        else:
            result["omittedWitnesses"] += 1

    def examine(row: dict[str, Any]) -> None:
        identifier = row.get("id")
        if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
            return
        try:
            tipster = resolve(row.get("tipster"))
            user = resolve(tipster["user"])
            back = resolve(user["tipster"])
            ids = [row.get("tipsterId"), user.get("id"), back.get("id"), back.get("userId")]
        except (ValueError, TypeError, KeyError):
            invalid_ids.add(identifier)
            if row.get("tipsterId") == OWNER:
                owned.add(identifier)
                witness(identifier, "closed_owner_absent")
            return
        if identifier in known_ids:
            literal_identity = canonical(
                [
                    identifier,
                    row.get("tipsterId"),
                    row.get("event"),
                    row.get("date"),
                    row.get("pick"),
                    row.get("competition"),
                ]
            )
            if (
                literal_identity != _identity(known_ids[identifier])
                or ids != [OWNER] * 4
                or user.get("username") != "ELIMAGAR"
            ):
                conflicts.add(identifier)
        signature = canonical(
            [row.get(k) for k in ("event", "pick", "date", "competition")]
            + ids
            + [user.get("username")]
        )
        if OWNER in ids:
            owned.add(identifier)
        if identifier in seen:
            if seen[identifier] != signature:
                conflicts.add(identifier)
            return
        seen[identifier] = signature
        if OWNER not in ids:
            result["excludedOtherOwners"] += 1
            return
        if ids != [OWNER] * 4 or user.get("username") != "ELIMAGAR":
            witness(identifier, "owner_mismatch")
            return
        if any(not _plain(row.get(k)) for k in ("event", "pick", "competition")):
            witness(identifier, "literal_fields_absent")
            return
        names = re.split(r"\s+[-–]\s+", row["event"])
        matches = [
            f
            for f in fixtures
            if len(names) == 2
            and names[0].strip().casefold() in {a.casefold() for a in f["homeAliases"]}
            and names[1].strip().casefold() in {a.casefold() for a in f["awayAliases"]}
        ]
        reason = "calendar_absent_or_ambiguous"
        if row["competition"].strip() == "Premier League" and len(matches) == 1:
            try:
                date_matches = instant(row.get("date")) == instant(matches[0]["kickoff"])
            except (ValueError, TypeError):
                date_matches = False
            reason = "native_date_mismatch" if not date_matches else ""
            if date_matches and observed >= instant(matches[0]["kickoff"]):
                reason = "post_kickoff"
        if reason:
            witness(identifier, reason)
            return
        fixture = matches[0]
        literal = {k: row[k] for k in ("id", "event", "pick", "competition", "date", "tipsterId")}
        literal.update(
            {
                "tipster.user.id": ids[1],
                "tipster.user.tipster.id": ids[2],
                "tipster.user.tipster.userId": ids[3],
                "tipster.user.username": "ELIMAGAR",
            }
        )
        if isinstance(row.get("createdAt"), str) and len(row["createdAt"]) <= 80:
            try:
                instant(row["createdAt"])
                literal["createdAt"] = row["createdAt"]
            except ValueError:
                pass
        pick = dict(
            id="notbetting-tip:" + identifier,
            sourceId="NotBetting",
            sourceTipId=identifier,
            authorId="public:" + sha256(("notbetting:" + OWNER).encode()).hexdigest(),
            authorLabel="ELIMAGAR",
            authorUrl=SOURCE,
            sourceUrl=SOURCE,
            fixtureId=fixture["id"],
            fixtureLabel=fixture["label"],
            kickoff=fixture["kickoff"],
            selection=row["pick"],
            market="source_native_opaque",
            sourceFields=literal,
            marketLabel="Choix publié (marché source non interprété)",
            publishedAt=None,
            publishedCivilDate=None,
            firstSeenAt=stamp(observed),
            observedAt=stamp(observed),
            temporalEvidenceFirstObservedAt=stamp(observed),
            responseSha256=response_sha,
            parserSha256=parser_sha,
            calendarSha256=_hash(fixtures),
            sourceRecordFingerprint=_hash(literal),
            performanceEvaluationAllowed=False,
            settlementAllowed=False,
            marketInterpretationAllowed=False,
            versions=[dict(selection=row["pick"], observedAt=stamp(observed))],
            versionCount=1,
        )
        if len(result["picks"]) < 20:
            result["picks"].append(pick)
        else:
            result["omittedAdmissible"] += 1

    def walk(value: Any, depth: int = 0, chain: tuple[str, ...] = ()) -> None:
        nonlocal visited
        visited += 1
        if visited > 150000:
            result["walkBoundHit"] = True
            reject("walk_bound")
        if depth > 40:
            result["depthBoundHit"] = True
            reject("depth_bound")
        if visited > 150000 or depth > 40:
            result["traversalComplete"] = False
            return
        if isinstance(value, str) and value.startswith("$"):
            # React 19 Flight scalar/element markers carry no traversable model.
            if (
                value == "$"
                or value.startswith(("$$", "$S", "$D", "$n"))
                or value
                in {"$I", "$-I", "$-0", "$N", "$u", "$undefined", "$Infinity", "$-Infinity", "$NaN"}
            ):
                return
            reference = value[2:] if value[1:2] in "L@hQWBKZiP" else value[1:]
            key = reference.split(":", 1)[0]
            if not re.fullmatch(r"[a-f0-9]+", key):
                reason = "unsupported_data_reference"
            elif key in chain:
                reason = "cyclic_data_reference"
            elif key in documents:
                # Walking the whole referenced document is conservative for path refs.
                walk(documents[key], depth + 1, (*chain, key))
                return
            elif key in documents.get("__flight_import_ids", []):
                return  # Explicit inert I-record; never execute the imported module.
            else:
                reason = "unresolved_data_reference"
            result["traversalComplete"] = False
            reject(reason)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1, chain)
        elif isinstance(value, dict):
            if (
                value.get("isReco") is True
                or value.get("isLocked") is True
                or any(value.get(k) is True for k in GATES)
                or value.get("access")
                in {"paid", "subscription_required", "authentication_required"}
            ):
                return
            if any(
                isinstance(value.get(k), str) and SKIP.search(value[k])
                for k in ("type", "kind", "__typename")
            ):
                return
            known_id = isinstance(value.get("id"), str) and value["id"] in known_ids
            if ("pick" in value and "event" in value) or known_id:
                examine(value)
            for key, item in value.items():
                if not SKIP.search(key) and key not in {"tipster", "user"}:
                    walk(item, depth + 1, chain)

    for root in ("0", "next_data"):
        if root in documents:
            walk(documents[root])
    if (conflicts | invalid_ids).intersection(owned | set(known_ids)):
        reject("contradictory_id")
        result["picks"] = []
    result["visitedNodes"] = visited
    result["witnessSampleLimited"] = result["omittedWitnesses"] > 0
    if result["omittedAdmissible"]:
        reject("retention_limit")
    if not result["picks"]:
        reject("no_admissible_choice")
    return result


def public_get(url: str, *, timeout: float = 12.0) -> Response:
    """Isolated 4M+sentinel transport. DNS participates in the total deadline."""
    _transport_environment()
    if url not in {SOURCE, ROBOTS} or not 0 < timeout <= 12:
        raise ValueError("exact NotBetting transport scope")
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("NotBetting total deadline")
        return value

    resolved: queue.Queue[Any] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            resolved.put(socket.getaddrinfo("notbetting.com", 443, type=socket.SOCK_STREAM))
        except OSError as exc:
            resolved.put(exc)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = resolved.get(timeout=remaining())
    except queue.Empty as exc:
        raise TimeoutError("NotBetting DNS deadline") from exc
    if isinstance(addresses, OSError):
        raise addresses
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise ValueError("non-public DNS result")
    family, socktype, protocol, _, address = addresses[0]
    sock = socket.socket(family, socktype, protocol)
    connection = http.client.HTTPConnection("notbetting.com", 443, timeout=timeout)
    active = [sock]

    def interrupt() -> None:
        try:
            active[0].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        active[0].close()

    guard = threading.Timer(remaining(), interrupt)
    guard.daemon = True
    guard.start()
    try:
        sock.settimeout(remaining())
        sock.connect(address)
        sock.settimeout(remaining())
        context = ssl.create_default_context()
        sock.settimeout(remaining())
        secured = context.wrap_socket(
            sock, server_hostname="notbetting.com", do_handshake_on_connect=False
        )
        connection.sock = secured
        active[0] = secured
        secured.settimeout(remaining())
        secured.do_handshake()
        secured.settimeout(remaining())
        connection.request(
            "GET",
            url.removeprefix("https://notbetting.com"),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        active[0].settimeout(remaining())
        response = connection.getresponse()
        if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
            raise ValueError("compressed response refused")
        body = bytearray()
        maximum = 4_000_000 if url == SOURCE else 64_000
        if response.status == 200:
            while len(body) <= maximum:
                active[0].settimeout(remaining())
                chunk = response.read1(min(65536, maximum + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > maximum:
                raise ValueError("isolated body bound exceeded")
        remaining()
        return Response(
            response.status,
            bytes(body),
            response.getheader("Content-Type", ""),
            response.getheader("Location"),
        )
    finally:
        guard.cancel()
        connection.close()
        sock.close()


def _same_or_merge(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    if _identity(old) != _identity(new):
        raise ValueError("contradictory retained choice")
    value = deepcopy(old)
    value["lastObservedAt"] = max(
        [
            row[key]
            for row in (old, new)
            for key in ("observedAt", "lastObservedAt")
            if row.get(key)
        ],
        key=instant,
    )
    return value


def read_companion(directory: Path) -> dict[str, Any]:
    """Replay only bounded structured journal facts, including after a halt."""
    if not (directory / "events.jsonl").is_file():
        raise ValueError("structured source proof absent")
    events = read_events(directory / "events.jsonl")
    picks: dict[str, dict[str, Any]] = {}
    fixtures: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["kind"] != "PASS_FINISHED":
            continue
        for row in event["picks"]:
            prior = picks.get(row["id"])
            picks[row["id"]] = _same_or_merge(prior, row) if prior else deepcopy(row)
        for fixture in event["fixtures"]:
            if fixture["id"] in fixtures and fixtures[fixture["id"]] != fixture:
                raise ValueError("retained fixture conflict")
            fixtures[fixture["id"]] = fixture
    return dict(
        picks=list(picks.values()),
        fixtures=list(fixtures.values()),
        claimId="DATA.NOTBETTING.E2V4.DRAFT.REQUIRES_COUNCIL_BINDING",
        halted=(directory / "halt.flag").exists()
        or any(e["kind"] == "CAMPAIGN_HALTED" for e in events),
    )


def merge_view(base: dict[str, Any], companion: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    rows = {p["id"]: p for p in data["picks"]}
    for row in companion["picks"]:
        rows[row["id"]] = (
            _same_or_merge(rows[row["id"]], row) if row["id"] in rows else deepcopy(row)
        )
    fixtures = {f["id"]: f for f in data.get("fixtures", [])}
    for fixture in companion["fixtures"]:
        if fixture["id"] in fixtures and canonical(fixtures[fixture["id"]]) != canonical(fixture):
            raise ValueError("fixture overwrite forbidden")
        fixtures[fixture["id"]] = fixture
    data.update(
        picks=list(rows.values()),
        fixtures=list(fixtures.values()),
        distinctPicks=len(rows),
        authorCount=len({p["authorId"] for p in rows.values()}),
    )
    data["claimIds"] = list(dict.fromkeys([*data.get("claimIds", []), companion["claimId"]]))
    clocks = [p[k] for p in rows.values() for k in ("observedAt", "lastObservedAt") if p.get(k)]
    if data.get("sourceObservedThrough"):
        clocks.append(data["sourceObservedThrough"])
    if clocks:
        data["sourceObservedThrough"] = max(clocks, key=instant)
    return data


def read_view(
    root: Path,
    directory: Path,
    plan_sha: str,
    *,
    now: datetime,
    native_verified: bool = False,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        validate_package(root, directory, plan_sha, now=now, historical=True)
        validate_canary(root, directory, plan_sha)
        companion = read_companion(directory)
        data = merge_view(base, companion) if base is not None else companion
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return dict(
            deepcopy(base) if base is not None else dict(picks=[], fixtures=[]),
            state="unavailable",
            active=False,
            recurringAuthority=False,
        )
    active = False
    try:
        validate_package(root, directory, plan_sha, now=now, registration=True)
        active = native_verified and not companion["halted"]
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        pass
    return dict(data, active=active, recurringAuthority=active)


def execute_pass(
    root: Path,
    directory: Path,
    plan_sha: str,
    slot: str,
    *,
    get: Callable[..., Response] = public_get,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """External Windows/Codex caller executes one named pass; no scheduler or retry."""
    begun = monotonic()
    packet = validate_package(root, directory, plan_sha, now=now())
    plan = packet["plan"]
    if slot != "canary":
        if slot not in SLOTS:
            raise ValueError("slot outside immutable plan")
        try:
            validate_canary(root, directory, plan_sha)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("canary not accepted") from exc
    start = instant(plan["canaryAt"] if slot == "canary" else slot)
    busy = directory / "busy.lock"
    try:
        lock = busy.open("x", encoding="utf-8")
    except FileExistsError:
        # A contender never appends using a stale journal head while the owner writes.
        try:
            with (directory / "halt.flag").open("xb") as halt_stream:
                halt_stream.write(b"busy_or_orphan_lock\n")
                halt_stream.flush()
                os.fsync(halt_stream.fileno())
        except FileExistsError:
            pass
        return dict(state="halted", active=False)
    try:
        journal = Journal(directory, packet["mission"], now=now)
    except BaseException:
        lock.close()
        busy.unlink()
        raise
    elapsed_before = max([e.get("elapsedMilliseconds", 0) for e in journal.events], default=0)

    def elapsed() -> int:
        # Charge a fixed five-second finalization reserve, including final fsync/cleanup.
        return elapsed_before + 5000 + math.ceil(max(0.0, monotonic() - begun) * 1000)

    def guard(required_seconds: int = 5) -> None:
        _transport_environment()
        if (directory / "halt.flag").exists():
            raise ValueError("busy_or_orphan_lock")
        current = now()
        if current < start or current >= start + timedelta(seconds=120):
            raise ValueError("missed or expired slot")
        remaining = min(
            (instant(EXPIRY) - current).total_seconds(),
            (start + timedelta(seconds=120) - current).total_seconds(),
            100 - (monotonic() - begun),
            (580188 - elapsed()) / 1000,
        )
        if remaining <= required_seconds:
            raise ValueError("expiry or cumulative time budget")

    def guard_request(*, reserved: bool = False) -> None:
        guard(17)
        reservations = sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events)
        if not reserved and reservations >= 10:
            raise ValueError("family request budget")

    try:
        if (directory / "halt.flag").exists() or any(
            e["kind"] == "CAMPAIGN_HALTED" for e in journal.events
        ):
            return dict(state="halted", active=False)
        if any(e["kind"] == "PASS_FINISHED" and e["slot"] == slot for e in journal.events):
            return dict(state="duplicate", active=False)
        lock.write(str(os.getpid()))
        lock.flush()
        os.fsync(lock.fileno())
        slot_lock = directory / ("slot-" + sha256(slot.encode()).hexdigest() + ".lock")
        with slot_lock.open("x", encoding="utf-8") as stream:
            stream.write(plan_sha)
            stream.flush()
            os.fsync(stream.fileno())
        for earlier in SLOTS:
            if (
                slot != "canary"
                and instant(earlier) < start
                and not any(
                    e["kind"] == "PASS_FINISHED" and e["slot"] == earlier for e in journal.events
                )
            ):
                raise ValueError("earlier slot missed; catch-up forbidden")
        guard()
        journal.append("PASS_STARTED", slot=slot, elapsedMilliseconds=elapsed())
        guard()

        def request(url: str) -> Response:
            guard_request()
            journal.append("REQUEST_RESERVED", slot=slot, url=url, elapsedMilliseconds=elapsed())
            # fsync may cross a boundary. Reservation remains charged even when no GET follows.
            guard_request(reserved=True)
            request_started = monotonic()
            result = get(url, timeout=12.0)
            if monotonic() - request_started >= 12:
                raise TimeoutError("request total deadline")
            guard()
            if result.status != 200 or result.location:
                raise ValueError("source refusal or redirect")
            journal.append(
                "REQUEST_FINISHED",
                slot=slot,
                url=url,
                status=result.status,
                responseSha256=sha256(result.body).hexdigest(),
                elapsedMilliseconds=elapsed(),
            )
            guard()
            return result

        robots = request(ROBOTS)
        robots_text = robots.body.decode("utf-8", errors="strict")
        if (
            robots.content_type.split(";")[0].strip().lower() != "text/plain"
            or len(robots.body) > 64000
            or re.search(r"[<\x00]|captcha|challenge|cf-chl", robots_text, re.I)
        ):
            raise ValueError("robots technical document refused")
        allowed, delay = robots_policy(robots_text, SOURCE)
        if not allowed or not math.isfinite(delay) or not 0 <= delay <= 30:
            raise ValueError("robots refusal or incompatible pacing")
        sleep(max(3, delay))
        guard()
        content = request(SOURCE)
        observed = now()
        known = {p["id"]: p for p in [*packet["baseline"], *read_companion(directory)["picks"]]}
        projected = qualify_documents(
            decode_capture(content.body, content.content_type),
            plan["fixtures"],
            observed,
            response_sha=sha256(content.body).hexdigest(),
            parser_sha=plan["codePins"][PIN_PATHS[0]],
            known=list(known.values()),
        )
        del content
        guard()
        if projected["status"] != "qualified" or not projected["traversalComplete"]:
            journal.append(
                "PASS_REJECTED", slot=slot, projection=projected, elapsedMilliseconds=elapsed()
            )
            raise ValueError(projected["reason"])
        if slot == "canary" and CANARY_ID not in {p["sourceTipId"] for p in projected["picks"]}:
            raise ValueError("canary must reobserve E1 choice")
        prior_path = "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl"
        prior_raw = _bytes(root / prior_path)
        if sha256(prior_raw).hexdigest() != PRIOR_PINS[prior_path]:
            raise ValueError("prior rejected observation journal changed")
        prior_events = [json.loads(line) for line in prior_raw.splitlines()]
        for row in projected["picks"]:
            if row["id"] in known:
                _same_or_merge(known[row["id"]], row)
                row["firstSeenAt"] = known[row["id"]]["firstSeenAt"]
                row["temporalEvidenceFirstObservedAt"] = known[row["id"]].get(
                    "temporalEvidenceFirstObservedAt", known[row["id"]]["observedAt"]
                )
            else:
                retain_prior_unaccepted_clock(row, prior_events)
        event = journal.append(
            "PASS_FINISHED",
            slot=slot,
            picks=projected["picks"],
            witnesses=projected["witnesses"],
            fixtures=plan["fixtures"],
            omittedAdmissible=projected["omittedAdmissible"],
            omittedWitnesses=projected["omittedWitnesses"],
            projectionAudit={
                k: projected[k]
                for k in (
                    "reasons",
                    "traversalComplete",
                    "visitedNodes",
                    "depthBoundHit",
                    "walkBoundHit",
                    "witnessSampleLimited",
                )
            },
            newChoices=sum(p["id"] not in known for p in projected["picks"]),
            elapsedMilliseconds=elapsed(),
        )
        guard()
        return dict(
            state="canary_pending_review" if slot == "canary" else "completed",
            newChoices=event["newChoices"],
            eventHash=event["hash"],
            active=False,
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        http.client.HTTPException,
    ) as exc:
        # Only local literal guard messages are retained. Transport errors may contain addresses.
        reason = str(exc)[:100] if type(exc) is ValueError else type(exc).__name__
        event = journal.append(
            "CAMPAIGN_HALTED", reason=reason, slot=slot, elapsedMilliseconds=elapsed(), active=False
        )
        return dict(state="halted", active=False, eventHash=event["hash"])
    finally:
        lock.close()
        busy.unlink()  # Only the busy lock created by this call. Slot locks remain permanent.
