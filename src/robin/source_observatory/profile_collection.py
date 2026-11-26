"""Overlay one exact campaign without changing prior grants or observations."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from .profile_campaign import read_campaign
from .qualification_view import merge_sro_collection
from .recurring import instant

DIRECTORY = "cockpit/.ci/olbg-hepter-e2v2-20261120"


def add_profile_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        observed, _ = read_campaign(root / DIRECTORY)
        data = merge_sro_collection(base, observed) if observed.get("picks") else deepcopy(base)
        data["profileCampaign"] = observed["profileCampaign"]
        dates = [d for d in [base.get("generatedAt"), data.get("generatedAt")] if d]
        if dates:
            data["generatedAt"] = max(dates, key=instant)
        times = [p["observedAt"] for p in data.get("picks", []) if p.get("observedAt")]
        if times:
            data["sourceObservedThrough"] = max(times, key=instant)
        return data
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["profileCampaign"] = {"state": "unavailable"}
        return data


def add_profile_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    data = deepcopy(base)
    try:
        observed, operational = read_campaign(root / DIRECTORY)
        state = observed["profileCampaign"]
        for row in data.get("candidates", []):
            if (
                row.get("sourceUrl") != "https://www.olbg.com/tipsters/tips/669088"
                or row.get("origin", {}).get("sheet") != "Catalogue"
                or row.get("origin", {}).get("row") != 70
                or not isinstance(row.get("qualification"), dict)
            ):
                continue
            q = row["qualification"]
            if observed.get("picks"):
                merged = merge_sro_collection(
                    dict(picks=q.get("picks", []), claimId=q.get("familyClaimId", "PREVIOUS")),
                    observed,
                )
                q["picks"] = merged["picks"]
                q["personallyProven"] = True
            q.update(
                profileCampaignId=state["campaignId"],
                profileAuthorUrl=state["authorUrl"],
                profileCampaign=state,
                sourceId="SRC_014",
                ownerAction="Campagne personnelle bornée de ce profil uniquement ; état Windows vérifié séparément.",
            )
            row["collectionEnabled"] = bool(operational and observed.get("picks"))
        data.setdefault("qualification", {})["profileCollectionState"] = "ok"
    except (OSError, ValueError, KeyError, TypeError):
        data.setdefault("qualification", {})["profileCollectionState"] = "unavailable"
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
    data.setdefault("qualification", {})["qualifiedCount"] = sum(
        bool(r.get("qualification", {}).get("personallyProven")) for r in data.get("candidates", [])
    )
    return data
