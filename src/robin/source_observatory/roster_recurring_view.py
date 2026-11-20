"""Read the accepted group separately from historical inventory and native state."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from .opaque_choices import merge_distinct_choices
from .recurring import instant
from .roster_campaign import _contract, read_campaign, validate_packet

DIRECTORY = "cockpit/.ci/olbg-roster-recurring-20261120"
CAMPAIGN_ID = "ROBIN-OLBG-ROSTER42-E2V2-20261120"


def merge_group_public(base: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(base)
    _check(base["picks"], observed["picks"])
    data["picks"] = merge_distinct_choices(base["picks"], observed["picks"])
    data["distinctPicks"] = len(data["picks"])
    data["authorCount"] = len({p["authorId"] for p in data["picks"]})
    data["claimIds"] = list(
        dict.fromkeys([*base.get("claimIds", [base["claimId"]]), observed["claimId"]])
    )
    data["generatedAt"] = max(base["generatedAt"], observed["generatedAt"], key=instant)
    source_times = [
        p["observedAt"] for p in [*base["picks"], *observed["picks"]] if p.get("observedAt")
    ]
    source_times.extend(
        t
        for t in (
            base.get("sourceObservedThrough"),
            observed["rosterCampaign"].get("lastObservedAt"),
        )
        if t
    )
    if source_times:
        data["sourceObservedThrough"] = max(source_times, key=instant)
    data["rosterCampaign"] = deepcopy(observed["rosterCampaign"])
    return data


def _check(previous: list[dict[str, Any]], additional: list[dict[str, Any]]) -> None:
    by_id = {p["id"]: p for p in previous}
    if any(p["id"] in by_id and _contract(p) != _contract(by_id[p["id"]]) for p in additional):
        raise ValueError("group observation contradicts a preserved source contract")


def _revoke(data: dict[str, Any]) -> None:
    for row in [*data.get("candidates", []), *data.get("rosterAssessments", [])]:
        q = row.get("qualification")
        if isinstance(q, dict) and q.get("rosterCampaignId") == CAMPAIGN_ID:
            row["collectionEnabled"] = False
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))


def merge_group_candidates(
    base: dict[str, Any], observed: dict[str, Any], operational: bool
) -> dict[str, Any]:
    data = deepcopy(base)
    _revoke(data)
    if data.get("qualification", {}).get("status") != "ok":
        data.setdefault("qualification", {})["rosterRecurringState"] = "unavailable"
        return data
    campaign = observed["rosterCampaign"]
    active = set(campaign["authorIds"])
    members = (
        active | set(campaign.get("poolAuthorIds", [])) | {p["authorId"] for p in observed["picks"]}
    )
    cases = {c["candidateId"]: c for c in data.get("rosterAssessments", [])}

    def decorate(q: dict[str, Any], source_url: str) -> bool:
        author = "olbg:" + source_url.rsplit("/", 1)[-1]
        if author not in members:
            return False
        additions = [
            p for p in observed["picks"] if p["authorUrl"] == source_url and p["authorId"] == author
        ]
        _check(q.get("picks", []), additions)
        q["picks"] = merge_distinct_choices(q.get("picks", []), additions)
        q.update(
            rosterCampaignId=campaign["campaignId"],
            rosterAuthorUrl=source_url,
            sourceId="SRC_014",
            rosterCampaign=deepcopy(campaign),
            personallyProven=bool(q["picks"]),
            ownerAction="Collecte personnelle récurrente bornée de ce groupe ; l’état Windows est vérifié séparément.",
        )
        admitted = {(p["authorUrl"], p.get("sourceTipId")) for p in q["picks"]}
        if isinstance(q.get("unadmittedFacts"), list):
            q["unadmittedFacts"] = [
                f
                for f in q["unadmittedFacts"]
                if (f.get("sourceUrl"), f.get("sourceTipId")) not in admitted
            ]
        return bool(operational and author in active and q["picks"])

    for row in data.get("candidates", []):
        case = cases.get(row["id"])
        if (
            case is None
            or row["sourceUrl"] != case["sourceUrl"]
            or row["origin"]["sheet"] != case["sheet"]
            or row["origin"]["row"] != case["row"]
            or not isinstance(row.get("qualification"), dict)
        ):
            continue
        if row["qualification"].get("rosterCampaignId") == campaign["campaignId"]:
            row["collectionEnabled"] = False
        if "olbg:" + row["sourceUrl"].rsplit("/", 1)[-1] in members:
            row["collectionEnabled"] = decorate(row["qualification"], row["sourceUrl"])
    for case in data.get("rosterAssessments", []):
        if case["qualification"].get("rosterCampaignId") == campaign["campaignId"]:
            case["collectionEnabled"] = False
        if "olbg:" + case["sourceUrl"].rsplit("/", 1)[-1] in members:
            case["collectionEnabled"] = decorate(case["qualification"], case["sourceUrl"])
    data["qualification"].update(
        rosterRecurringState="ok",
        rosterCampaignId=campaign["campaignId"],
        qualifiedCount=sum(
            bool(r.get("qualification", {}).get("personallyProven"))
            for r in data.get("candidates", [])
        ),
    )
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
    return data


def add_group_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        observed, _ = read_campaign(root / DIRECTORY)
        plan, _ = validate_packet(root / DIRECTORY)
        observed["rosterCampaign"]["poolAuthorIds"] = [f"olbg:{a}" for a in plan["pool"]]
        return merge_group_public(base, observed)
    except (OSError, ValueError, TypeError, KeyError):
        data = deepcopy(base)
        data["rosterCampaign"] = dict(state="unavailable")
        return data


def add_group_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        observed, operational = read_campaign(root / DIRECTORY)
        plan, _ = validate_packet(root / DIRECTORY)
        observed["rosterCampaign"]["poolAuthorIds"] = [f"olbg:{a}" for a in plan["pool"]]
        return merge_group_candidates(base, observed, operational)
    except (OSError, ValueError, TypeError, KeyError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["rosterRecurringState"] = "unavailable"
        _revoke(data)
        return data
