"""Read two approved bounded occurrences without replacing the PL provenance."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import notbetting_bundes_collection as qualifier
from .connectors import canonical
from .recurring import instant

CLAIM = "DATA.SOURCE_OBSERVATORY.NOTBETTING.BUNDES.BOUNDED.OCCURRENCES.20261121"
REPORT = "reports/source_observatory/TIPSTERS-NOTBETTING-BUNDES-BOUNDED-DATA-20261121.json"
REPORT_SHA = "815d266b7427cbfa95b85681c22b8975a50570487a35c299a42dc1c4d5d8c41d"
DIRECTORY = "cockpit/.ci/official-doc-research-20261121/bundes"
SOURCE = "cockpit/.ci/notbetting-prospective-0130-v2-20261121"


def _read(path: Path) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(200001)
    if len(value) > 200000:
        raise ValueError("bounded occurrence artifact size")
    return value


def _load(root: Path) -> dict[str, Any]:
    report_raw = _read(root / REPORT)
    if sha256(report_raw).hexdigest() != REPORT_SHA:
        raise ValueError("approved bounded report hash")
    report = json.loads(report_raw)
    if report["claimId"] != CLAIM or report["admissionScope"] != "BOUNDED_OCCURRENCES_ONLY":
        raise ValueError("bounded claim scope")
    module_raw = _read(root / "src/robin/source_observatory/notbetting_bundes_collection.py")
    if sha256(module_raw.replace(b"\r\n", b"\n")).hexdigest() != report["qualifierCodeSha256"]:
        raise ValueError("qualifier code pin")
    bundle_path = (root / report["bundlePath"]).resolve()
    if not bundle_path.is_relative_to((root / DIRECTORY).resolve()):
        raise ValueError("private bounded bundle path")
    bundle_raw = _read(bundle_path)
    if sha256(bundle_raw).hexdigest() != report["bundleSha256"]:
        raise ValueError("bounded bundle hash")
    bundle: dict[str, Any] = json.loads(bundle_raw)
    if bundle["claimId"] != CLAIM or bundle["qualifierCodeSha256"] != report["qualifierCodeSha256"]:
        raise ValueError("bounded bundle lineage")
    if sha256(_read(root / SOURCE / "events.jsonl")).hexdigest() != report["sourceJournalSha256"]:
        raise ValueError("frozen source journal")
    if (
        sha256(_read(root / DIRECTORY / "calendar-projection.json")).hexdigest()
        != report["calendarProjectionSha256"]
    ):
        raise ValueError("official calendar projection")
    for name, evidence in zip(
        ("open-fixtures-result.json", "open-pdf-result.json"), qualifier.EVIDENCE, strict=True
    ):
        raw = _read(root / DIRECTORY / name)
        if sha256(raw).hexdigest() != evidence["toolResultJsonSha256"]:
            raise ValueError("official rendered evidence pin")
    expected = qualifier.qualify_frozen_bundes(
        _read(root / SOURCE / "result.json"),
        bundle["fixtures"],
        parser_sha=report["nativeParserSha256"],
    )
    if canonical(bundle["picks"]) != canonical(expected):
        raise ValueError("bounded source derivation changed")
    return bundle


def merge_bounded(base: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    rows = bundle["picks"]
    if (
        bundle["claimId"] != CLAIM
        or bundle["admissionScope"] != "BOUNDED_OCCURRENCES_ONLY"
        or len(rows) != 2
        or any(
            p.get("sourceWalkTruncated") is not True
            or p.get("canonicalQualification") is not False
            or p.get("sourceTraversalComplete") is not False
            or p.get("evidenceScope") != "CLOSED_NATIVE_OCCURRENCE_ONLY"
            or p.get("globalVariantConsistency") != "NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS"
            for p in rows
        )
    ):
        raise ValueError("bounded occurrence quality required")
    data = deepcopy(base)
    prior_rows = {p["id"]: p for p in data["picks"]}
    for row in rows:
        prior = prior_rows.get(row["id"])
        if prior is not None and canonical(prior) != canonical(row):
            raise ValueError("existing choice conflict")
        if prior is None:
            data["picks"].append(deepcopy(row))
            prior_rows[row["id"]] = row
    prior_fixtures = {f["id"]: f for f in data.get("fixtures", [])}
    for fixture in bundle["fixtures"]:
        prior = prior_fixtures.get(fixture["id"])
        if prior is not None and canonical(prior) != canonical(fixture):
            raise ValueError("existing fixture conflict")
        if prior is None:
            data.setdefault("fixtures", []).append(deepcopy(fixture))
            prior_fixtures[fixture["id"]] = fixture
    data["claimIds"] = list(dict.fromkeys([*data.get("claimIds", []), CLAIM]))
    data["distinctPicks"] = len(data["picks"])
    data["authorCount"] = len({p["authorId"] for p in data["picks"]})
    data["generatedAt"] = max([data["generatedAt"], bundle["qualifiedAt"]], key=instant)
    clocks = [p["observedAt"] for p in rows]
    if data.get("sourceObservedThrough"):
        clocks.append(data["sourceObservedThrough"])
    data["sourceObservedThrough"] = max(clocks, key=instant)
    data["notbettingBundesOccurrences"] = dict(
        state="bounded_occurrences_qualified",
        claimId=CLAIM,
        nativeOccurrences=2,
        admissionScope="BOUNDED_OCCURRENCES_ONLY",
        sourceWalkTruncated=True,
        sourceTraversalComplete=False,
        canonicalQualification=False,
        globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
        recurringAuthority=False,
    )
    return data


def add_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        return merge_bounded(base, _load(root))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        data = deepcopy(base)
        data["notbettingBundesOccurrences"] = dict(
            state="unavailable", canonicalQualification=False, recurringAuthority=False
        )
        return data
