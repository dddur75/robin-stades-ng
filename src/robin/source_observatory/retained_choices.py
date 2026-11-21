"""Add one independently accepted, immutable batch of retained observations."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .connectors import canonical
from .opaque_choices import build_opaque_choices, merge_distinct_choices
from .recurring import instant
from .roster_collection import _check_choices

DIRECTORY = "cockpit/.ci/olbg-six-offline-20261121"
ENVELOPE_SHA256 = "d14b954f9a50375de142d6a2f88513a0644369441ea9d205493b009564e6ff20"
CLAIM = "DATA.SOURCE_OBSERVATORY.OLBG.SIX.RETAINED.PREMATCH.20261121"
CONTEXTUAL_CLAIM = "DATA.SOURCE_OBSERVATORY.OLBG.TWO.CONTEXTS.PREMATCH.20261121"
NORWICH_CLAIM = "DATA.SOURCE_OBSERVATORY.OLBG.NORWICH.SEVEN.PREMATCH.20261121"
LIVERPOOL_CLAIM = "DATA.SOURCE_OBSERVATORY.OLBG.LIVERPOOL.ONE.RETAINED.PREMATCH.20261121"
NEW_FIXTURE_CLAIMS = frozenset((CONTEXTUAL_CLAIM, NORWICH_CLAIM, LIVERPOOL_CLAIM))
BATCHES = (
    (DIRECTORY, ENVELOPE_SHA256, CLAIM),
    (
        "cockpit/.ci/olbg-two-context-mappings-20261121",
        "62bb8ab9b093ee0fd9c14ae6a310a13f38b188bd3c0e955932d75c5aa473669e",
        CONTEXTUAL_CLAIM,
    ),
    (
        "cockpit/.ci/olbg-norwich-seven-20261121",
        "7dae5d0772fe90ecb6299fcb5f5e0ed2da7ca5e8353f14dcc1598d0bbab98402",
        NORWICH_CLAIM,
    ),
    (
        "cockpit/.ci/olbg-liverpool-one-20261121",
        "fe7e2204b4829935a43b33ac8e1c207ce2ba72f51c8cf7c4bac2600aae921bb0",
        LIVERPOOL_CLAIM,
    ),
    (
        "cockpit/.ci/olbg-norwich-one-20261121",
        "c9b76de6939a0fe277bc7971ee1e7d65ecb30e359a5e18fcc3eda581764ced53",
        "DATA.SOURCE_OBSERVATORY.OLBG.NORWICH.ONE.RETAINED.PREMATCH.20261121",
    ),
)


def _load(
    root: Path,
    directory: str = DIRECTORY,
    expected_sha: str = ENVELOPE_SHA256,
    expected_claim: str = CLAIM,
) -> dict[str, Any]:
    with (root / directory / "envelope.json").open("rb") as stream:
        raw = stream.read(100_001)
    if len(raw) > 100_000 or sha256(raw).hexdigest() != expected_sha:
        raise ValueError("retained admission hash or size")
    envelope: dict[str, Any] = json.loads(raw)
    if not isinstance(envelope, dict):
        raise ValueError("retained admission shape")
    source, bundle = envelope["source"], envelope["bundle"]
    if bundle["claimId"] != expected_claim or bundle["recurrence"] is not False:
        raise ValueError("retained admission scope")
    if sha256(canonical(source) + b"\n").hexdigest() != bundle["sourceResultSha256"]:
        raise ValueError("retained source hash")
    expected = build_opaque_choices(
        source, bundle["acceptedSourceTipIds"], parser_sha=bundle["lexicalParserSha256"]
    )
    if canonical(expected) != canonical(bundle["picks"]):
        raise ValueError("retained source derivation")
    return envelope


def merge_retained_public(base: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    _check_choices(base["picks"], bundle["picks"])
    fixtures = {f["id"]: f for f in base["fixtures"]}
    if bundle["claimId"] not in NEW_FIXTURE_CLAIMS and any(
        f["id"] not in fixtures for f in bundle["fixtures"]
    ):
        raise ValueError("historical retained fixture absent from base")
    if any(
        f["id"] in fixtures and instant(f["kickoff"]) != instant(fixtures[f["id"]]["kickoff"])
        for f in bundle["fixtures"]
    ):
        raise ValueError("retained fixture conflicts with history")
    data = deepcopy(base)
    for fixture in bundle["fixtures"]:
        fixtures.setdefault(fixture["id"], deepcopy(fixture))
    data["fixtures"] = list(fixtures.values())
    data["picks"] = merge_distinct_choices(base["picks"], bundle["picks"])
    data["distinctPicks"] = len(data["picks"])
    data["authorCount"] = len({p["authorId"] for p in data["picks"]})
    data["claimIds"] = list(
        dict.fromkeys([*base.get("claimIds", [base["claimId"]]), bundle["claimId"]])
    )
    data["generatedAt"] = max(base["generatedAt"], bundle["qualifiedAt"], key=instant)
    times = [p["observedAt"] for p in data["picks"] if p.get("observedAt")]
    if base.get("sourceObservedThrough"):
        times.append(base["sourceObservedThrough"])
    if times:
        data["sourceObservedThrough"] = max(times, key=instant)
    data["retainedCollection"] = dict(
        state="accepted_individual_proofs",
        claimId=bundle["claimId"],
        qualifiedAt=bundle["qualifiedAt"],
        recurrenceAuthorized=False,
    )
    return data


def add_retained_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    data = deepcopy(base)
    states = []
    for directory, digest, claim in BATCHES:
        try:
            data = merge_retained_public(data, _load(root, directory, digest, claim)["bundle"])
            states.append(dict(claimId=claim, state="accepted"))
        except (OSError, ValueError, KeyError, TypeError):
            states.append(dict(claimId=claim, state="unavailable"))
    data["retainedAdmissions"] = states
    if any(s["state"] == "unavailable" for s in states):
        data.setdefault("retainedCollection", dict(recurrenceAuthorized=False))["state"] = (
            "partial" if any(s["state"] == "accepted" for s in states) else "unavailable"
        )
    return data


def merge_retained_candidates(base: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["retainedCollectionState"] = "unavailable"
        return data
    bundle = envelope["bundle"]
    for identity in envelope["identities"]:
        picks = [
            p
            for p in bundle["picks"]
            if p["authorId"] == f"olbg:{identity['authorId']}"
            and p["authorUrl"] == identity["sourceUrl"]
        ]
        targets = [
            row
            for row in data.get("candidates", [])
            if row.get("id") == identity["candidateId"]
            and row.get("sourceUrl") == identity["sourceUrl"]
            and row.get("origin", {}).get("sheet") == identity["sheet"]
            and row.get("origin", {}).get("row") == identity["row"]
        ]
        targets += [
            row
            for row in data.get("rosterAssessments", [])
            if row.get("recordId") == identity["recordId"]
            and row.get("sourceUrl") == identity["sourceUrl"]
            and row.get("sheet") == identity["sheet"]
            and row.get("row") == identity["row"]
        ]
        for row in targets:
            q = row.get("qualification")
            if not isinstance(q, dict) or not picks:
                continue
            _check_choices(q.get("picks", []), picks)
            q["picks"] = merge_distinct_choices(q.get("picks", []), picks)
            q["retainedClaimIds"] = list(
                dict.fromkeys(
                    [
                        *q.get(
                            "retainedClaimIds",
                            [q["retainedClaimId"]] if q.get("retainedClaimId") else [],
                        ),
                        bundle["claimId"],
                    ]
                )
            )
            q.update(
                personallyProven=True,
                retainedClaimId=bundle["claimId"],
                retainedQualifiedAt=bundle["qualifiedAt"],
                label="Choix personnels observés avant match",
            )
            admitted = {p["sourceTipId"] for p in picks}
            q["unadmittedFacts"] = [
                f for f in q.get("unadmittedFacts", []) if f.get("sourceTipId") not in admitted
            ]
    data["qualification"]["qualifiedCount"] = sum(
        bool(r.get("qualification", {}).get("personallyProven")) for r in data.get("candidates", [])
    )
    data["qualification"]["retainedCollectionState"] = "ok"
    return data


def add_retained_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["retainedCollectionState"] = "unavailable"
        data["retainedAdmissions"] = [
            dict(claimId=claim, state="not_applied_base_unavailable") for _, _, claim in BATCHES
        ]
        return data
    states = []
    for directory, digest, claim in BATCHES:
        try:
            data = merge_retained_candidates(data, _load(root, directory, digest, claim))
            states.append(dict(claimId=claim, state="accepted"))
        except (OSError, ValueError, KeyError, TypeError):
            states.append(dict(claimId=claim, state="unavailable"))
    data["retainedAdmissions"] = states
    if any(s["state"] == "unavailable" for s in states):
        data.setdefault("qualification", {})["retainedCollectionState"] = (
            "partial" if any(s["state"] == "accepted" for s in states) else "unavailable"
        )
    return data
