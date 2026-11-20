"""Accepted individual inventories, separate from source scheduling and activation."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .olbg_store import read_bundle
from .opaque_choices import merge_distinct_choices, read_opaque_bundle
from .recurring import instant

# Replaced only after the exact independent data receipt has been accepted.
APPROVED_ROSTER_REPORT_SHA256 = "06a239f82e03d7378c25b344501243805e66cfe256654fee42027d3059b011a6"


def _check_choices(previous_picks: list[dict[str, Any]], additional: list[dict[str, Any]]) -> None:
    previous = {p["id"]: p for p in previous_picks}
    for pick in additional:
        old = previous.get(pick["id"])
        if old and any(
            old.get(k) != pick.get(k)
            for k in ("sourceId", "authorId", "sourceTipId", "fixtureId", "selection", "market")
        ):
            raise ValueError("roster source identity contradicts preserved choice")


def merge_roster_public(
    base: dict[str, Any],
    assessment: dict[str, Any],
    picks: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> dict[str, Any]:
    data = deepcopy(base)
    _check_choices(base["picks"], picks)
    data["picks"] = merge_distinct_choices(base["picks"], picks)
    by_id = {f["id"]: f for f in base.get("fixtures", [])}
    for fixture in fixtures:
        existing = by_id.get(fixture["id"])
        if existing and instant(existing["kickoff"]) != instant(fixture["kickoff"]):
            raise ValueError("roster fixture conflicts with preserved history")
        by_id.setdefault(fixture["id"], fixture)
    data["fixtures"] = list(by_id.values())
    data["distinctPicks"] = len(data["picks"])
    data["authorCount"] = len({p["authorId"] for p in data["picks"]})
    data["claimIds"] = list(
        dict.fromkeys([*base.get("claimIds", [base["claimId"]]), assessment["claimId"]])
    )
    dates = [
        assessment["qualifiedAt"],
        base.get("generatedAt"),
        *[p.get("observedAt") for p in data["picks"]],
    ]
    data["generatedAt"] = max((d for d in dates if d), key=instant)
    observed = [p["observedAt"] for p in data["picks"] if p.get("observedAt")]
    if observed:
        data["sourceObservedThrough"] = max(observed, key=instant)
    data["rosterCollection"] = dict(
        state="accepted_individual_proofs",
        claimId=assessment["claimId"],
        rosterCount=assessment["rosterCount"],
        inventoriedCount=assessment["inventoriedCount"],
        recurrenceAuthorized=False,
    )
    return data


def merge_roster_candidates(
    base: dict[str, Any], assessment: dict[str, Any], picks: list[dict[str, Any]]
) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["rosterCollectionState"] = "unavailable"
        return data
    cases = {r["profile"]["candidateId"]: r for r in assessment["profiles"]}
    documentary = []
    for case in assessment["profiles"]:
        source = case["profile"]
        personal = [
            p
            for p in picks
            if p["authorUrl"] == source["sourceUrl"]
            and p["authorId"] == f"olbg:{source['authorId']}"
        ]
        qualification = dict(
            personallyProven=bool(personal),
            profileVisited=True,
            observedAt=case["observedAt"],
            rosterObservedAt=case["observedAt"],
            rosterClaimId=assessment["claimId"],
            nativeAuthorId=f"olbg:{source['authorId']}",
            label="Choix personnels observés avant match"
            if personal
            else "Inventaire personnel daté ; aucun choix admis",
            reason="Les faits individuels sont séparés de la collecte récurrente. Les autres rencontres ou marchés restent non qualifiés.",
            requiredAccess="Aucun compte ou achat requis pour cette observation publique.",
            ownerAction="Cette acquisition ponctuelle ne crée pas de tâche ni d’autorité récurrente.",
            nativeFactCount=case["facts"],
            omittedRecords=case["omittedRecords"],
            picks=personal,
        )
        documentary.append(
            dict(
                recordId=source["recordId"],
                candidateId=source["candidateId"],
                sheet=source["sheet"],
                row=source["row"],
                sourceUrl=source["sourceUrl"],
                qualification=qualification,
                collectionEnabled=False,
            )
        )
    for row in data.get("candidates", []):
        case = cases.get(row.get("id"))
        if case is None:
            continue
        source = case["profile"]
        if (
            row.get("sourceUrl") != source["sourceUrl"]
            or row.get("origin", {}).get("sheet") != source["sheet"]
            or row.get("origin", {}).get("row") != source["row"]
        ):
            continue
        q = row.get("qualification")
        if not isinstance(q, dict):
            continue
        overlay = next(r["qualification"] for r in documentary if r["candidateId"] == row["id"])
        _check_choices(q.get("picks", []), overlay["picks"])
        merged = merge_distinct_choices(q.get("picks", []), overlay["picks"])
        row["qualification"] = dict(
            q,
            **{k: v for k, v in overlay.items() if k not in ("picks", "personallyProven")},
            picks=merged,
            personallyProven=bool(merged),
        )
        if merged:
            row["qualification"]["label"] = "Choix personnels observés avant match"
        old_observed = q.get("observedAt")
        if old_observed and instant(old_observed) > instant(overlay["observedAt"]):
            row["qualification"]["observedAt"] = old_observed
        admitted = {
            (p.get("authorUrl"), p.get("sourceTipId"))
            for p in merged
            if p.get("authorUrl") == row["sourceUrl"]
        }
        if isinstance(q.get("unadmittedFacts"), list):
            row["qualification"]["unadmittedFacts"] = [
                fact
                for fact in q["unadmittedFacts"]
                if (fact.get("sourceUrl"), fact.get("sourceTipId")) not in admitted
            ]
        # Acquisition never sets collectionEnabled; native task gates retain authority.
    data["rosterAssessments"] = documentary
    data["qualification"].update(
        rosterCollectionState="ok",
        rosterClaimId=assessment["claimId"],
        qualifiedCount=sum(
            bool(r.get("qualification", {}).get("personallyProven"))
            for r in data.get("candidates", [])
        ),
    )
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
    return data


def _read_checked(path: Path, expected: str, ceiling: int) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(ceiling + 1)
    if len(raw) > ceiling or sha256(raw).hexdigest() != expected:
        raise ValueError("roster accepted evidence hash or bound")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("roster accepted evidence shape")
    return value


def _load(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    report = _read_checked(
        root / "reports/source_observatory/TIPSTERS-OLBG-CURRENT138-CORRECTED-DATA-20261120.json",
        APPROVED_ROSTER_REPORT_SHA256,
        100_000,
    )
    directory = root / "cockpit/.ci/olbg-current138-residual-20261120"
    assessment = _read_checked(
        directory / "accepted-assessment.json", report["assessmentSha256"], 500_000
    )
    if assessment["claimId"] != report["dataClaimId"] or assessment["inventoriedCount"] != len(
        assessment["profiles"]
    ):
        raise ValueError("roster receipt scope")
    picks = []
    fixtures: dict[str, dict[str, Any]] = {}
    for row in assessment["profiles"]:
        owner = row["profile"]["authorId"]
        native_sha, opaque_sha, source_sha = (
            row["nativeSha256"],
            row["opaqueSha256"],
            row["sourceSha256"],
        )
        win = read_bundle(directory / f"proposed-native-{owner}-{native_sha}.json", native_sha)
        opaque = read_opaque_bundle(
            directory / f"proposed-opaque-{owner}-{opaque_sha}.json",
            opaque_sha,
            directory / f"source-profile-{owner}-{source_sha}.json",
            source_sha,
        )
        if win["claimId"] != assessment["claimId"] or opaque["claimId"] != assessment["claimId"]:
            raise ValueError("roster bundle claim")
        for bundle in (win, opaque):
            if any(
                p["authorId"] != f"olbg:{owner}" or p["authorUrl"] != row["profile"]["sourceUrl"]
                for p in bundle["picks"]
            ):
                raise ValueError("roster bundle owner")
            picks.extend(bundle["picks"])
            fixtures.update({f["id"]: f for f in bundle["fixtures"]})
    if len({p["id"] for p in picks}) != len(picks):
        raise ValueError("roster duplicate source identity")
    return assessment, picks, list(fixtures.values())


def add_roster_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        assessment, picks, fixtures = _load(root)
        return merge_roster_public(base, assessment, picks, fixtures)
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["rosterCollection"] = dict(state="unavailable", recurrenceAuthorized=False)
        return data


def add_roster_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        assessment, picks, _ = _load(root)
        return merge_roster_candidates(base, assessment, picks)
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["rosterCollectionState"] = "unavailable"
        return data
