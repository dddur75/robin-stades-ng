"""Offline closed native declarations; incomplete page traversal stays incomplete."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any

from .connectors import canonical
from .notbetting_collection import SOURCE_URL, _plain
from .recurring import instant

OWNER = "67766b69-620e-48f8-b395-5d7fadfc2679"
OWNER_KEYS = (
    "tipsterId",
    "tipster.user.id",
    "tipster.user.tipster.id",
    "tipster.user.tipster.userId",
)
FIELDS = {"id", "event", "pick", "competition", "date", "tipster.user.username", *OWNER_KEYS}
HASH = re.compile(r"[a-f0-9]{64}")
UUID = re.compile(r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}")
CALENDAR_SHA = "0300af3100c210e86528c01bc67318cc6dd67311b0fa35edc4ba046587227fb5"
JOURNALS = {
    "3e7269678e799b65000ec70d028e02c227ab4a7ecb2c32821915e38eb1765a35": "0c2a36858d527a7847f9ecdfbfef73fdddb873670cdbeed3c6bfab7eb1f199ae",
    "986192f8cfb8ef2225fc9b738b0294e6c9d2309af159d6502c7833da50c0eeea": "1ef22506963e4bccd323da76ccfd8d48e534f30c238ac0ee7450ac732e27ac64",
}


def build_occurrences(
    captures: list[dict[str, Any]], fixtures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Require two independent concordant retained observations, not page completeness."""
    if len(captures) != 2 or len({(c["journalSha256"], c["eventHash"]) for c in captures}) != 2:
        raise ValueError("two independent retained captures required")
    grouped: dict[str, dict[str, Any]] = {}
    for capture in sorted(captures, key=lambda c: instant(c["observedAt"])):
        if (
            capture["sourceUrl"] != SOURCE_URL
            or not capture["reasons"]
            or not 0 < len(capture["rows"]) <= 20
        ):
            raise ValueError("bounded native capture scope")
        if any(
            not isinstance(capture.get(k), str) or HASH.fullmatch(capture[k]) is None
            for k in ("responseSha256", "parserSha256", "journalSha256", "eventHash")
        ):
            raise ValueError("complete capture provenance required")
        local: set[str] = set()
        for row in capture["rows"]:
            fields = row["sourceFields"]
            if not FIELDS <= set(fields) or set(fields) - FIELDS - {"createdAt"}:
                raise ValueError("closed native fields required")
            identifier = fields["id"]
            if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
                raise ValueError("native UUID")
            if (
                any(fields[k] != OWNER for k in OWNER_KEYS)
                or fields["tipster.user.username"] != "ELIMAGAR"
            ):
                raise ValueError("closed native owner required")
            if fields["competition"] != "Premier League" or any(
                not _plain(fields[k]) for k in ("event", "pick", "competition")
            ):
                raise ValueError("native literal competition or choice")
            fingerprint = sha256(canonical(fields)).hexdigest()
            if (
                fingerprint != row["sourceRecordFingerprint"]
                or row["observedAt"] != capture["observedAt"]
            ):
                raise ValueError("own capture clock and native fingerprint")
            names = re.split(r"\s+[-–]\s+", fields["event"])
            matches = [
                f
                for f in fixtures
                if len(names) == 2
                and names[0].strip().casefold() in {a.casefold() for a in f["homeAliases"]}
                and names[1].strip().casefold() in {a.casefold() for a in f["awayAliases"]}
            ]
            if (
                len(matches) != 1
                or instant(fields["date"]) != instant(matches[0]["kickoff"])
                or instant(capture["observedAt"]) >= instant(matches[0]["kickoff"])
            ):
                raise ValueError("unambiguous oriented official fixture and strict pre-KO clock")
            fixture = matches[0]
            prior = grouped.get(identifier)
            if prior is not None and prior["sourceRecordFingerprint"] != fingerprint:
                raise ValueError("encountered contradictory native version; no winner")
            if identifier in local:
                continue
            local.add(identifier)
            observation = {
                k: deepcopy(capture[k])
                for k in (
                    "observedAt",
                    "responseSha256",
                    "parserSha256",
                    "journalSha256",
                    "eventHash",
                    "reasons",
                )
            }
            if prior is None:
                prior = dict(
                    id="notbetting-tip:" + identifier,
                    sourceId="NotBetting",
                    sourceTipId=identifier,
                    authorId="public:" + sha256(("notbetting:" + OWNER).encode()).hexdigest(),
                    authorLabel="ELIMAGAR",
                    authorUrl=SOURCE_URL,
                    sourceUrl=SOURCE_URL,
                    fixtureId=fixture["id"],
                    fixtureLabel=fixture["label"],
                    kickoff=fixture["kickoff"],
                    selection=fields["pick"],
                    sourceFields=deepcopy(fields),
                    sourceRecordFingerprint=fingerprint,
                    market="source_native_opaque",
                    marketLabel="Choix publié (marché source non interprété)",
                    publishedAt=None,
                    publishedCivilDate=None,
                    firstSeenAt=capture["observedAt"],
                    observedAt=capture["observedAt"],
                    lastObservedAt=capture["observedAt"],
                    temporalEvidenceFirstObservedAt=capture["observedAt"],
                    responseSha256=capture["responseSha256"],
                    parserSha256=capture["parserSha256"],
                    evidenceScope="CLOSED_NATIVE_OCCURRENCE_ONLY",
                    sourceWalkTruncated=True,
                    sourceTraversalComplete=False,
                    globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
                    canonicalQualification=False,
                    performanceEvaluationAllowed=False,
                    settlementAllowed=False,
                    marketInterpretationAllowed=False,
                    calendarSha256=sha256(canonical(fixtures)).hexdigest(),
                    observations=[],
                    observationCount=0,
                    versions=[dict(selection=fields["pick"], observedAt=capture["observedAt"])],
                    versionCount=1,
                )
                grouped[identifier] = prior
            prior["observations"].append(observation)
            prior["observationCount"] += 1
            prior["lastObservedAt"] = capture["observedAt"]
    result = [row for row in grouped.values() if row["observationCount"] == 2]
    if not result:
        raise ValueError("no independently corroborated retained declaration")
    return result


def qualify_frozen_journals(
    raws: list[bytes], fixtures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Exact E1 offline entrypoint. Neither source experiment is reclassified."""
    if (
        len(raws) != 2
        or {sha256(raw).hexdigest() for raw in raws} != set(JOURNALS)
        or sha256(canonical(fixtures)).hexdigest() != CALENDAR_SHA
    ):
        raise ValueError("exact frozen captures and official calendar required")
    captures = []
    for raw in raws:
        digest = sha256(raw).hexdigest()
        events = []
        previous = "0" * 64
        for index, line in enumerate(raw.splitlines(keepends=True)):
            event = json.loads(line)
            body = {k: v for k, v in event.items() if k != "hash"}
            if (
                event["hash"] != sha256(canonical(body)).hexdigest()
                or event["previousHash"] != previous
                or event["sequence"] != index + 1
                or line != canonical(event) + b"\n"
            ):
                raise ValueError("source journal integrity")
            events.append(event)
            previous = event["hash"]
        rejected = [e for e in events if e["kind"] == "PASS_REJECTED"]
        received = [
            e
            for e in events
            if e["kind"] == "REQUEST_FINISHED"
            and e.get("url") == SOURCE_URL
            and e.get("status") == 200
        ]
        if (
            len(rejected) != 1
            or len(received) != 1
            or events[-1]["kind"] != "CAMPAIGN_HALTED"
            or any(e["kind"] == "PASS_FINISHED" for e in events)
        ):
            raise ValueError("exact rejected source experiment required")
        projection = rejected[0]["projection"]
        rows = projection["picks"]
        if not rows or any(
            p["responseSha256"] != received[0]["responseSha256"]
            or p["parserSha256"] != JOURNALS[digest]
            for p in rows
        ):
            raise ValueError("retained row capture or executor mismatch")
        captures.append(
            dict(
                sourceUrl=SOURCE_URL,
                observedAt=rows[0]["observedAt"],
                responseSha256=received[0]["responseSha256"],
                parserSha256=JOURNALS[digest],
                journalSha256=digest,
                eventHash=rejected[0]["hash"],
                reasons=projection.get("reasons")
                or [projection["reason"], "SOURCE_TRAVERSAL_DIAGNOSTICS_NOT_RETAINED"],
                rows=rows,
            )
        )
    return build_occurrences(captures, fixtures)
