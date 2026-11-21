"""Accepted profile-local observations, separate from activation and old grants."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from .olbg_store import read_bundle
from .opaque_choices import merge_distinct_choices, read_opaque_bundle
from .qualification_view import merge_sro_collection
from .recurring import instant

APPROVED_FAMILY_REPORT_SHA256 = "c003ff782950413777e973c263487f0bbc817db188bc9209eb36b290fc8d3c72"


def merge_family_public(
    base: dict[str, Any],
    win: dict[str, Any] | None,
    opaque: dict[str, Any] | None,
    *,
    qualified_at: str,
) -> dict[str, Any]:
    if win is None and opaque is None:
        data = deepcopy(base)
        data["familyCollection"] = dict(
            state="unavailable", nativeWinState="unavailable", opaqueState="unavailable"
        )
        return data
    data = merge_sro_collection(base, win) if win is not None else deepcopy(base)
    if opaque is not None:
        data["picks"] = merge_distinct_choices(data["picks"], opaque["picks"])
        data["claimIds"] = list(
            dict.fromkeys([*data.get("claimIds", [data["claimId"]]), opaque["claimId"]])
        )
    fixtures = {f["id"]: f for f in data.get("fixtures", [])}
    for bundle in (win, opaque):
        if bundle is not None:
            fixtures.update({f["id"]: f for f in bundle["fixtures"]})
    data.update(
        fixtures=list(fixtures.values()),
        distinctPicks=len(data["picks"]),
        authorCount=len({p["authorId"] for p in data["picks"]}),
    )
    observed = [p["observedAt"] for p in data["picks"] if p.get("observedAt")]
    if observed:
        data["sourceObservedThrough"] = max(observed, key=instant)
    dates = [*observed, base.get("generatedAt"), data.get("generatedAt"), qualified_at]
    data["generatedAt"] = max((d for d in dates if d), key=instant)
    data["familyCollection"] = dict(
        state="accepted_individual_proofs",
        qualifiedAt=qualified_at,
        nativeWinState="ok" if win is not None else "unavailable",
        opaqueState="ok" if opaque is not None else "unavailable",
        newRecurringAuthority=False,
    )
    return data


def merge_family_candidates(
    base: dict[str, Any],
    report: dict[str, Any],
    accepted: list[dict[str, Any]],
    content: dict[str, Any] | None,
) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["familyCollectionState"] = "unavailable"
        return data
    cases = {c["candidateId"]: c for c in report["profiles"]}
    for row in data.get("candidates", []):
        case = cases.get(row.get("id"))
        if (
            case is None
            or row.get("sourceUrl") != case["sourceUrl"]
            or row.get("origin", {}).get("sheet") != case["sheet"]
            or row.get("origin", {}).get("row") != case["row"]
        ):
            continue
        q = row.get("qualification")
        if not isinstance(q, dict):
            continue
        q = deepcopy(q)
        row["qualification"] = q
        q.setdefault("previousFamilyAssessment", deepcopy(q))
        additions = [p for p in accepted if p["authorUrl"] == row["sourceUrl"]]
        picks = merge_distinct_choices(q.get("picks", []), additions)
        q.update(
            profileVisited=True,
            personallyProven=bool(picks),
            picks=picks,
            familyClaimId=report["claimId"],
            observedAt=case["observedAt"],
            label="Choix personnels observés avant match"
            if picks
            else "Faits personnels lus ; qualification incomplète",
            reason="Les preuves individuelles disponibles sont séparées des faits encore non admis.",
            ownerAction="Cette acquisition ponctuelle ne crée aucune autorité récurrente.",
            requiredAccess="Aucun compte ou achat requis pour ces observations publiques individuelles.",
        )
        # Preserve every old activation flag; acquisition alone cannot turn one on.
        if content is not None:
            profiles = [p for p in content["profiles"] if p["request"]["url"] == row["sourceUrl"]]
            if len(profiles) == 1:
                source = profiles[0]
                admitted = {p.get("sourceTipId") for p in picks}
                q["unadmittedFacts"] = [
                    dict(
                        sourceTipId=f["tipid"],
                        fixtureLabel=f.get("eventname"),
                        selection=f.get("selection"),
                        marketLabel=f.get("market") or f.get("winew"),
                        sourceEventText=f.get("event_datetime"),
                        sourceUrl=row["sourceUrl"],
                        observedAt=source["request"]["observedAt"],
                        reason="Rencontre canonique ou qualification individuelle du marché incomplète ; aucun choix admis pour ce fait.",
                    )
                    for f in source["facts"]["records"]
                    if f.get("vc_sport_id") == 1 and f.get("tipid") not in admitted
                ]
    data["qualification"].update(
        familyCollectionState="ok",
        familyClaimId=report["claimId"],
        qualifiedCount=sum(
            bool(r.get("qualification", {}).get("personallyProven"))
            for r in data.get("candidates", [])
        ),
    )
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
    return data


def _load(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    raw = (root / "reports/source_observatory/TIPSTERS-OLBG-FAMILY-DATA-20261120.json").read_bytes()
    if len(raw) > 200_000 or sha256(raw).hexdigest() != APPROVED_FAMILY_REPORT_SHA256:
        raise ValueError("family report hash")
    report = json.loads(raw)
    if report.get("schemaVersion") != "robin-compatible-family-view-v1":
        raise ValueError("family report schema")
    for key in ("nativeWinBundleSha256", "opaqueBundleSha256", "sourceResultSha256"):
        if re.fullmatch("[a-f0-9]{64}", report[key]) is None:
            raise ValueError("family bundle anchor")
    directory = root / "cockpit/.ci/olbg-compatible-family-20261120"
    win = opaque = content = None
    try:
        h = report["nativeWinBundleSha256"]
        win = read_bundle(directory / f"observations-{h}.json", h)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    source = directory / "result-pending-review.json"
    try:
        h = report["sourceResultSha256"]
        raw = source.read_bytes()
        if len(raw) > 2_000_000 or sha256(raw).hexdigest() != h:
            raise ValueError("family structured source hash")
        content = json.loads(raw)
        h = report["opaqueBundleSha256"]
        opaque = read_opaque_bundle(
            directory / f"observations-opaque-{h}.json", h, source, report["sourceResultSha256"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return report, win, opaque, content


def add_family_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        report, win, opaque, _ = _load(root)
        return merge_family_public(base, win, opaque, qualified_at=report["qualifiedAt"])
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["familyCollection"] = dict(state="unavailable")
        return data


def add_family_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        report, win, opaque, content = _load(root)
        if win is None and opaque is None:
            raise ValueError("no family bundle available")
        accepted = [p for b in (win, opaque) if b is not None for p in b["picks"]]
        data = merge_family_candidates(base, report, accepted, content)
        data.setdefault("qualification", {}).update(
            familyNativeWinState="ok" if win is not None else "unavailable",
            familyOpaqueState="ok" if opaque is not None else "unavailable",
        )
        return data
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["familyCollectionState"] = "unavailable"
        return data
