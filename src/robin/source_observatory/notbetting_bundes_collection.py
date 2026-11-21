"""Offline qualification of two frozen Bundesliga witnesses. No execution authority."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any

from .connectors import canonical
from .notbetting_collection import HASH, SOURCE_URL, _plain
from .recurring import instant

OWNER = "67766b69-620e-48f8-b395-5d7fadfc2679"
TARGETS = ("b828798c-ee1a-471e-8b62-7d3bcc7d99ed", "4db13be9-ae44-4dc1-b8ee-ec059e049ee4")
SOURCE_RESULT_SHA256 = "a921b485b7c034fb04c2208b64f7e28044fd7e5040da7bbe0427556ff0c444a0"
EVIDENCE = (
    {
        "kind": "TOOL_RENDERED_TEXT_UTF8",
        "url": "https://products.bundesliga.com/fixtures",
        "toolResultJsonSha256": "00d2d8eb15dbb0b440bc23f14c03455b7bb6dce70af5de74ad70b6725d8a43e3",
        "renderedTextSha256": "b3a2560d6bc7101bcf84271cf62dd2aad148b23b9ea796e6a09061a94943828d",
    },
    {
        "kind": "TOOL_RENDERED_TEXT_UTF8",
        "url": "https://products.bundesliga.com/fixtures/export/pdf?league%5B0%5D=1d570dd9-b10b-44de-9f64-8c91e56bf168&matchday%5B0%5D=10&season=b2f90c16-d6ef-40b1-a974-e6b1bf102c2a",
        "toolResultJsonSha256": "a752fd5b88eb5d6df790b28231281f8c501c25b6181f89e1b89d24c54acbc440",
        "renderedTextSha256": "de1d15895b86a774baf0762d717fa763231f78f786feaadbafab3d46ab05ce38",
    },
)
OWNER_KEYS = (
    "tipsterId",
    "tipster.user.id",
    "tipster.user.tipster.id",
    "tipster.user.tipster.userId",
)
FIELD_KEYS = {"id", "event", "pick", "competition", "tipster.user.username", *OWNER_KEYS}


def bundes_fixtures() -> list[dict[str, Any]]:
    common = dict(
        competition="Bundesliga",
        season="2026/27",
        matchday=10,
        sourceTimezone="UTC",
        sourceUTCHeaderConfirmed=True,
        evidenceKind="TOOL_RENDERED_OFFICIAL_DOCUMENTS",
        evidenceUrl=EVIDENCE[1]["url"],
    )
    return [
        dict(
            common,
            id="bundes-20261121-frankfurt-hoffenheim",
            label="Eintracht Frankfurt – TSG Hoffenheim",
            homeAliases=["Eintracht Frankfurt"],
            awayAliases=["Hoffenheim", "TSG Hoffenheim"],
            kickoff="2026-11-21T14:30:00Z",
        ),
        dict(
            deepcopy(common),
            id="bundes-20261121-schalke-stuttgart",
            label="FC Schalke 04 – VfB Stuttgart",
            homeAliases=["Schalke 04", "FC Schalke 04"],
            awayAliases=["Stuttgart", "VfB Stuttgart"],
            kickoff="2026-11-21T17:30:00Z",
        ),
    ]


def build_bundes_choices(
    source: dict[str, Any], fixtures: list[dict[str, Any]], *, parser_sha: str
) -> list[dict[str, Any]]:
    """Pure derivation; the frozen entrypoint pins the original source bytes."""
    content = source["content"]
    if (
        source.get("sourceUrl") != SOURCE_URL
        or content.get("status") != 200
        or HASH.fullmatch(parser_sha) is None
        or HASH.fullmatch(content["responseSha256"]) is None
        or len(fixtures) != 2
        or len({f["id"] for f in fixtures}) != 2
    ):
        raise ValueError("exact frozen Bundesliga calendar or provenance required")
    expected = {f["id"]: f for f in bundes_fixtures()}
    for fixture in fixtures:
        template = expected.get(fixture["id"])
        if (
            template is None
            or fixture.get("sourceUTCHeaderConfirmed") is not True
            or any(fixture.get(k) != v for k, v in template.items())
        ):
            raise ValueError("official Bundesliga fixture scope")
    projection = content["projection"]
    if projection.get("walkTruncated") is not True:
        raise ValueError("this frozen derivation requires its explicit bounded-source scope")
    rows = []
    for identifier in TARGETS:
        records = [r for r in projection["records"] if r["nativeFields"].get("id") == identifier]
        comparisons = [c for c in source["targetComparison"] if c.get("id") == identifier]
        if (
            len(records) != 1
            or len(comparisons) != 1
            or identifier in projection["conflictingTargetIds"]
        ):
            raise ValueError("absent, duplicate or invalid native variant")
        record, comparison = records[0], comparisons[0]
        fields, times = record["nativeFields"], record["nativeTemporalFields"]
        fingerprint = sha256(
            canonical(
                dict(fields=fields, linkedOwner=record["linkedOwner"], nativeTemporalFields=times)
            )
        ).hexdigest()
        if (
            set(fields) != FIELD_KEYS
            or set(times) - {"date", "createdAt"}
            or any(fields[k] != OWNER for k in OWNER_KEYS)
            or fields["tipster.user.username"] != "ELIMAGAR"
            or record["linkedOwner"].get("tipsterId") != OWNER
            or record["linkedOwner"].get("tipster")
            != {
                k.removeprefix("tipster."): v for k, v in fields.items() if k.startswith("tipster.")
            }
            or fingerprint != record["sourceRecordFingerprint"]
            or any(not _plain(fields[k]) for k in ("event", "pick", "competition"))
            or fields["competition"].strip() != "Bundesliga"
            or comparison.get("samePreviouslyRetainedNativeFields") is not True
            or comparison.get("changedPreviouslyRetainedFieldNames") != []
            or comparison.get("firstSeenAt") != source["baselineObservedAt"]
            or comparison.get("newTemporalEvidenceObservedAt") != content["observedAt"]
        ):
            raise ValueError("closed native identity, fingerprint or comparison")
        names = re.split(r"\s+[-–]\s+", fields["event"])
        matches = [
            f
            for f in fixtures
            if len(names) == 2
            and names[0].strip().casefold() in {a.casefold() for a in f["homeAliases"]}
            and names[1].strip().casefold() in {a.casefold() for a in f["awayAliases"]}
        ]
        if len(matches) != 1:
            raise ValueError("absent, reversed or ambiguous fixture")
        fixture = matches[0]
        if (
            not isinstance(times.get("date"), str)
            or instant(times["date"]) != instant(fixture["kickoff"])
            or instant(content["observedAt"]) >= instant(fixture["kickoff"])
            or instant(source["baselineObservedAt"]) > instant(content["observedAt"])
        ):
            raise ValueError("own date or strict pre-match chronology")
        literal = {
            k: fields[k]
            for k in ("id", "event", "pick", "competition", *OWNER_KEYS, "tipster.user.username")
        }
        literal.update(times)
        rows.append(
            dict(
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
                market="source_native_opaque",
                marketLabel="Choix publié (marché source non interprété)",
                sourceMarketLabel=None,
                sourceBetType=None,
                sourceFields=literal,
                sourceEventLocalText=times["date"],
                sourceEventTimezone=None,
                publishedAt=None,
                publishedCivilDate=None,
                observedAt=content["observedAt"],
                firstSeenAt=source["baselineObservedAt"],
                temporalEvidenceFirstObservedAt=content["observedAt"],
                responseSha256=content["responseSha256"],
                parserSha256=parser_sha,
                sourceRecordFingerprint=fingerprint,
                calendarSha256=sha256(canonical(fixtures)).hexdigest(),
                calendarEvidence=deepcopy(list(EVIDENCE)),
                performanceEvaluationAllowed=False,
                settlementAllowed=False,
                marketInterpretationAllowed=False,
                versions=[dict(selection=fields["pick"], observedAt=content["observedAt"])],
                versionCount=1,
                evidenceScope="CLOSED_NATIVE_OCCURRENCE_ONLY",
                sourceWalkTruncated=True,
                sourceTraversalComplete=False,
                globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
                canonicalQualification=False,
            )
        )
    return rows


def qualify_frozen_bundes(
    raw: bytes, fixtures: list[dict[str, Any]], *, parser_sha: str
) -> list[dict[str, Any]]:
    """Verify the immutable E1 result bytes before the pure derivation."""
    if sha256(raw).hexdigest() != SOURCE_RESULT_SHA256:
        raise ValueError("frozen E1 result hash")
    return build_bundes_choices(json.loads(raw), fixtures, parser_sha=parser_sha)
