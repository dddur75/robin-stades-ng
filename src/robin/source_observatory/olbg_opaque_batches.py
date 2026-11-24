"""Receipt-driven opaque campaign reader; old seed files are never rewritten."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from robin.source_observatory.connectors import canonical, read_events
from robin.source_observatory.opaque_choices import build_opaque_choices
from robin.source_observatory.recurring import instant

from .olbg_opaque_campaign import SCHEMA, validate_campaign

IDENTITY = ("id", "sourceId", "authorId", "sourceTipId", "sourceEventId",
            "fixtureId", "kickoff", "sourceUrl", "authorUrl", "market", "calendarSha256")
VERSION_FIELDS = ("selection", "sourceMarketLabel", "sourceBetType", "sourceFields")


def merge_versions(
    previous: list[dict[str, Any]], additional: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = deepcopy(previous)
    by_key = {(p["sourceId"], p["authorId"], p["sourceTipId"]): p for p in result}
    ids = {p["id"]: k for k, p in by_key.items()}
    if len(ids) != len(result) or len(by_key) != len(result):
        raise ValueError("PRIOR_DUPLICATE_IDENTITY")
    for value in result + additional:
        first = instant(value.get("firstSeenAt", value["observedAt"]))
        observed = instant(value["observedAt"])
        last = instant(value.get("lastSeenAt", value["observedAt"]))
        if not first <= observed <= last < instant(value["kickoff"]):
            raise ValueError("TEMPORAL_ORDER")
    for incoming in additional:
        p = deepcopy(incoming)
        key = (p["sourceId"], p["authorId"], p["sourceTipId"])
        old = by_key.get(key)
        if p["id"] in ids and ids[p["id"]] != key:
            raise ValueError("ID_CONFLICT")
        if old is None:
            p["lastSeenAt"] = p["observedAt"]
            p["observationVersions"] = [{k: deepcopy(p[k]) for k in
                                        (*VERSION_FIELDS, "observedAt", "responseSha256")}]
            result.append(p)
            by_key[key], ids[p["id"]] = p, key
            continue
        if any(canonical(old.get(k)) != canonical(p.get(k)) for k in IDENTITY):
            raise ValueError("IMMUTABLE_IDENTITY_CONFLICT")
        if instant(p.get("firstSeenAt", p["observedAt"])) < instant(
                old.get("firstSeenAt", old["observedAt"])):
            raise ValueError("UNSUPPORTED_BACKFILL")
        prior_seen = old.get("lastSeenAt", old["observedAt"])
        if instant(p["observedAt"]) < instant(prior_seen):
            raise ValueError("OBSERVATION_ORDER")
        if instant(p["observedAt"]) >= instant(p["kickoff"]):
            raise ValueError("AFTER_KICKOFF")
        if instant(p["observedAt"]) == instant(prior_seen):
            if any(canonical(old.get(k)) != canonical(p.get(k)) for k in
                   (*VERSION_FIELDS, "responseSha256")):
                raise ValueError("SAME_INSTANT_CONFLICT")
            continue
        # The displayed fields/SHA and observedAt are the current observation.
        # Only firstSeenAt retains the earliest accepted sighting.
        first = old.get("firstSeenAt", old["observedAt"])
        observations = deepcopy(old.get("observationVersions", [
            {k: deepcopy(old[k]) for k in (*VERSION_FIELDS, "observedAt", "responseSha256")}]))
        observations.append({k: deepcopy(p[k]) for k in
                             (*VERSION_FIELDS, "observedAt", "responseSha256")})
        versions = deepcopy(old["versions"])
        if old["selection"] != p["selection"]:
            versions.append({"selection": p["selection"], "observedAt": p["observedAt"]})
        old.update(p)
        old.update(firstSeenAt=first, observedAt=p["observedAt"], lastSeenAt=p["observedAt"],
                   versions=versions, versionCount=len(versions),
                   observationVersions=observations)
    return result


def read_campaign(
    directory: Path, approval: dict[str, str] | None
) -> dict[str, Any]:
    plan, mission = validate_campaign(directory, approval)
    events = read_events(directory / "events.jsonl")
    starts = [e for e in events if e["kind"] == "PUBLIC_SLOT_STARTED"]
    finishes = [e for e in events if e["kind"] == "PUBLIC_SLOT_FINISHED"]
    accepted = [e for e in events if e["kind"] == "PUBLIC_COLLECTION_ACCEPTED"]
    if (len({e["slot"] for e in starts}) != len(starts)
            or {e["slot"] for e in starts} != {e["slot"] for e in finishes}
            or {e["slot"] for e in starts} != {e["slot"] for e in accepted}
            or len(accepted) != len(finishes)
            or len({e["slot"] for e in accepted}) != len(accepted)):
        raise ValueError("ORPHAN_OR_DUPLICATE_SLOT")
    if not accepted:
        raise ValueError("CAMPAIGN_WAITING_NO_ACCEPTED_BATCH")
    picks: list[dict[str, Any]] = []
    batches = []
    for receipt in accepted:
        slot = receipt["slot"]
        ss = [e for e in starts if e["slot"] == slot]
        ff = [e for e in finishes if e["slot"] == slot]
        if (slot not in plan["slots"] or len(ss) != 1 or len(ff) != 1
                or not ss[0]["sequence"] < receipt["sequence"] < ff[0]["sequence"]
                or ff[0]["count"] != receipt["count"]):
            raise ValueError("SLOT_RECEIPT")
        segment = events[ss[0]["sequence"]:receipt["sequence"] - 1]
        q = [e for e in segment if e["kind"] == "PUBLIC_PICKS_QUALIFIED"]
        requests = [e for e in segment if e["kind"] == "REQUEST_FINISHED"
                    and e["sourceId"] == "SRC_014" and e["url"] == plan["endpoint"]
                    and e["httpStatus"] == 200]
        if len(q) != 1 or len(requests) != 1:
            raise ValueError("SOURCE_RECEIPT")
        proof = q[0]
        if (proof["responseSha256"] != requests[0]["responseSha256"]
                or proof["parserSha256"] != plan["parserSha256"]
                or proof["calendarSha256"] != plan["calendarSha256"]
                or proof["count"] != receipt["count"]):
            raise ValueError("QUALIFICATION_RECEIPT")
        digest = receipt["observationSha256"]
        if (not isinstance(digest, str) or re.fullmatch("[a-f0-9]{64}", digest) is None
                or receipt["observationFile"] != "observations-" + digest + ".json"):
            raise ValueError("BATCH_NAME")
        with (directory / receipt["observationFile"]).open("rb") as stream:
            raw = stream.read(131073)
        if not 0 < len(raw) <= 131072 or sha256(raw).hexdigest() != digest:
            raise ValueError("BATCH_PIN")
        batch = json.loads(raw)
        if (batch["schemaVersion"] != SCHEMA or batch["missionId"] != plan["id"]
                or batch["claimId"] != plan["claimId"]
                or batch["calendarSha256"] != plan["calendarSha256"]
                or batch["source"]["fixtures"] != plan["fixtures"]
                or batch["source"]["calendarSha256"] != plan["calendarSha256"]
                or batch["sourceReady"] is not False or batch["applicationAdmissions"] != 0
                or batch["parserSha256"] != plan["parserSha256"]
                or batch["builderSha256"] != plan["builderSha256"]):
            raise ValueError("BATCH_SCOPE")
        profiles = batch["source"]["profiles"]
        if len(profiles) != 1 or profiles[0]["request"]["responseSha256"] != proof["responseSha256"]:
            raise ValueError("PROFILE_PROOF")
        expected = build_opaque_choices(batch["source"], batch["acceptedSourceTipIds"],
                                        parser_sha=plan["parserSha256"])
        if (canonical(expected) != canonical(batch["picks"])
                or len(expected) != receipt["count"] or not 0 < len(expected) <= 20
                or any(p["authorId"] != "olbg:648433"
                       or p["sourceUrl"] != plan["endpoint"] for p in expected)):
            raise ValueError("OPAQUE_RECOMPUTATION")
        picks = merge_versions(picks, expected)
        batches.append({"sha256": digest, "slot": slot, "count": len(expected)})
    if {e["slot"] for e in finishes} != {e["slot"] for e in accepted}:
        raise ValueError("ORPHAN_FINISH")
    # Incomplete/crashed run is unavailable, even if a payload file exists.
    if len([e for e in events if e["kind"] == "RUN_STARTED"]) != len(
            [e for e in events if e["kind"] == "RUN_FINISHED"]):
        raise ValueError("UNFINISHED_RUN")
    return {"picks": picks, "fixtures": plan["fixtures"], "claimId": plan["claimId"],
            "calendarSha256": plan["calendarSha256"], "batches": batches,
            "missionId": mission["mission_id"], "sourceReady": False,
            "recurringCollectionActive": False, "applicationAdmissions": 0}
