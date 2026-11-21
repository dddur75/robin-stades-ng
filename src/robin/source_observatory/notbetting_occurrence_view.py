"""Expose accepted bounded occurrences locally without replacing older evidence."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .connectors import canonical
from .notbetting_occurrences import qualify_frozen_journals
from .recurring import instant

CANARY_ID = "notbetting-tip:e112cc31-2939-4cd2-b65e-e20bd61e050e"
DIRECTORY = "cockpit/.ci/notbetting-closed-occurrences-e1-20261121"
BUNDLE = "observations-d5ff1f820b637839b699e492718a43787dcf9e42dd4aeafa4f324ae81ab28e42.json"
BUNDLE_SHA = "d5ff1f820b637839b699e492718a43787dcf9e42dd4aeafa4f324ae81ab28e42"
REPORT = "reports/source_observatory/TIPSTERS-NOTBETTING-CLOSED-OCCURRENCES-E1-DATA-20261121.json"
REPORT_SHA = "4f28e51553e9a69279c83dcd7a5eecb9f8a7e7e3e8a22922d2d5b9d02c86c7e0"
QUALIFIER_SHA = "ab5314bba43a5624bfd40a570dda90092f930ee00841b04fcd9dfcbbb57fcf99"


def merge_occurrences(base: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    existing = {p["id"]: p for p in data["picks"]}
    fixtures = {f["id"]: f for f in data["fixtures"]}
    if (
        len(existing) != len(data["picks"])
        or len(fixtures) != len(data["fixtures"])
        or CANARY_ID not in existing
    ):
        raise ValueError("unique complete original declarations required")
    for row in bundle["picks"]:
        if (
            row.get("evidenceScope") != "CLOSED_NATIVE_OCCURRENCE_ONLY"
            or row.get("sourceWalkTruncated") is not True
            or row.get("sourceTraversalComplete") is not False
            or row.get("canonicalQualification") is not False
            or row.get("globalVariantConsistency") != "NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS"
            or any(
                row.get(k) is not False
                for k in (
                    "performanceEvaluationAllowed",
                    "settlementAllowed",
                    "marketInterpretationAllowed",
                )
            )
        ):
            raise ValueError("bounded quality and scientific prohibitions required")
        old = existing.get(row["id"])
        if old is not None:
            if any(
                old.get(k) != row[k]
                for k in (
                    "sourceId",
                    "sourceTipId",
                    "authorId",
                    "fixtureId",
                    "kickoff",
                    "selection",
                )
            ) or any(
                old.get("sourceFields", {}).get(k) != row["sourceFields"].get(k)
                for k in ("id", "event", "pick", "competition", "date", "tipsterId")
            ):
                raise ValueError("existing declaration conflict; never overwrite")
            if row["id"] != CANARY_ID and old != row:
                raise ValueError("existing bounded occurrence conflict")
        else:
            existing[row["id"]] = deepcopy(row)
    for fixture in bundle["fixtures"]:
        if fixture["id"] in fixtures and canonical(fixtures[fixture["id"]]) != canonical(fixture):
            raise ValueError("official fixture overwrite refused")
        fixtures[fixture["id"]] = deepcopy(fixture)
    data.update(
        picks=list(existing.values()),
        fixtures=list(fixtures.values()),
        distinctPicks=len(existing),
        authorCount=len({p["authorId"] for p in existing.values()}),
    )
    data["claimIds"] = list(dict.fromkeys([*data.get("claimIds", []), bundle["claimId"]]))
    clocks = [r["lastObservedAt"] for r in bundle["picks"]]
    if data.get("sourceObservedThrough"):
        clocks.append(data["sourceObservedThrough"])
    data["sourceObservedThrough"] = max(clocks, key=instant)
    generated = [bundle["qualifiedAt"]]
    if data.get("generatedAt"):
        generated.append(data["generatedAt"])
    data["generatedAt"] = max(generated, key=instant)
    data["notbettingClosedOccurrences"] = dict(
        state="bounded_declarations_qualified",
        claimId=bundle["claimId"],
        qualifiedAt=bundle["qualifiedAt"],
        nativeDeclarations=len(bundle["picks"]),
        nativeObservations=sum(r["observationCount"] for r in bundle["picks"]),
        additionalDeclarations=sum(r["id"] != CANARY_ID for r in bundle["picks"]),
        sourceTraversalComplete=False,
        canonicalQualification=False,
        globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
        recurringAuthority=False,
        observations={r["id"]: deepcopy(r["observations"]) for r in bundle["picks"]},
    )
    return data


def add_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        raw = (root / REPORT).read_bytes()
        if sha256(raw).hexdigest() != REPORT_SHA:
            raise ValueError("four-key data acceptance changed")
        report = json.loads(raw)
        if report["bundleSha256"] != BUNDLE_SHA or report["qualifierSha256"] != QUALIFIER_SHA:
            raise ValueError("data acceptance binding")
        if (
            sha256(
                (root / "src/robin/source_observatory/notbetting_occurrences.py")
                .read_bytes()
                .replace(b"\r\n", b"\n")
            ).hexdigest()
            != QUALIFIER_SHA
        ):
            raise ValueError("qualifier changed")
        raw = (root / DIRECTORY / BUNDLE).read_bytes()
        if sha256(raw).hexdigest() != BUNDLE_SHA:
            raise ValueError("accepted occurrence bundle changed")
        bundle = json.loads(raw)
        source = [
            (root / p).read_bytes()
            for p in (
                "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl",
                "cockpit/.ci/notbetting-recurring-e2v4-20261121/events.jsonl",
            )
        ]
        if qualify_frozen_journals(source, bundle["fixtures"]) != bundle["picks"]:
            raise ValueError("bounded occurrence reconstruction")
        return merge_occurrences(base, bundle)
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["notbettingClosedOccurrences"] = dict(state="unavailable", recurringAuthority=False)
        return data
