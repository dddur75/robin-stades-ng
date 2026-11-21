"""Read the separately authorized SRO successor; never reopen historical grants."""

import json
import re
import subprocess  # nosec B404
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any

CAMPAIGN_ID = "ROBIN-SRO-NEXT3-20261121"
CANARY_CLAIM = "DATA.SOURCE_OBSERVATORY.SRO.CANARY.R2.REOBSERVED.20261121"
ALGORITHM_CLAIM = "ENG.SOURCE_OBSERVATORY.SRO.NEXT3.E2.ALGORITHM.20261121"
PACKET = Path(
    "C:/Users/ddura/.codex/worktrees/robin-roster-successor-e1/Robin V3/"
    "cockpit/.ci/sro-next3-e2-r2-20261121"
)
PYTHON = Path("C:/Users/ddura/AppData/Local/Python/pythoncore-3.12-64/python.exe")
PYTHON_SHA256 = "4d6f5f81a4bca11191c4c7c6b43632694d0a4ce74e068619d8fdc161d469859a"
CONFIG = "cockpit/.ci/sro-next-bridge-20261121/config.json"
OWNER_URLS = frozenset(
    f"https://forum.stade-rennais-online.com/profile.php?id={owner}"
    for owner in (13380, 13604, 14868, 15220, 15388, 15772, 15921, 16361)
)


def owner_id(url: str) -> str:
    raw = json.dumps(["SRC_039", url], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


OWNER_IDS = frozenset(map(owner_id, OWNER_URLS))
ERRORS = (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def _instant(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("SRO successor time shape")
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.utcoffset() is None:
        raise ValueError("SRO successor timezone missing")
    return at


def _validate(observed: dict[str, Any], operational: bool) -> None:
    campaign = observed["sroNextCampaign"]
    if (
        type(operational) is not bool
        or observed["claimId"] != ALGORITHM_CLAIM
        or campaign["campaignId"] != CAMPAIGN_ID
        or campaign["governingAlgorithmClaimId"] != ALGORITHM_CLAIM
        or campaign["canaryClaimId"] != CANARY_CLAIM
        or campaign["state"] not in {
            "scheduled", "collecting", "completed", "expired", "halted",
            "missed_slot", "blocked_lock", "invalid_package",
        }
        or (operational and campaign["state"] not in {"scheduled", "collecting"})
        or campaign["futureReceiptReview"] not in {"PENDING", "CONTRACT_VALIDATED"}
        or type(campaign.get("allowFutureSuccessfulSlots")) is not bool
        or campaign["allowFutureSuccessfulSlots"] != (campaign["futureReceiptReview"] == "CONTRACT_VALIDATED")
        or _instant(campaign["startsAt"]) != _instant("2026-11-21T20:00:00Z")
        or _instant(campaign["expiresAt"]) != _instant("2026-11-22T08:10:00Z")
    ):
        raise ValueError("SRO successor campaign identity/state")
    for key, expected in {
        "slots": 3, "requestsMax": 9, "priorFamilyGET": 42,
        "familyGETMax": 51, "canaryRequests": 3, "canaryReobservations": 55,
    }.items():
        if type(campaign[key]) is not int or campaign[key] != expected:
            raise ValueError("SRO successor family budget")
    for key, maximum in (("requests", 9), ("successfulSlots", 3)):
        if type(campaign[key]) is not int or not 0 <= campaign[key] <= maximum:
            raise ValueError("SRO successor counter")
    if type(campaign.get("pendingFutureChoices")) is not int or campaign["pendingFutureChoices"] < 0:
        raise ValueError("SRO successor pending counter")
    for key in ("nativeXmlSha256", "canaryReceiptSHA256"):
        if not isinstance(campaign[key], str) or not re.fullmatch("[0-9a-f]{64}", campaign[key]):
            raise ValueError("SRO successor receipt/XML pin")
    for key in ("authorIds", "poolAuthorIds"):
        values = campaign[key]
        if not isinstance(values, list) or len(values) != len(set(values)):
            raise ValueError("SRO successor owner shape")
        if (set(values) != OWNER_IDS if key == "poolAuthorIds" else not set(values) <= OWNER_IDS):
            raise ValueError("SRO successor owner scope")
    _instant(campaign["canaryObservedAt"])
    if not isinstance(observed["fixtures"], list) or not isinstance(observed["picks"], list):
        raise ValueError("SRO successor fact shape")
    fixtures = {f["id"]: f for f in observed["fixtures"]}
    if len(fixtures) != len(observed["fixtures"]) or len(observed["picks"]) > 2_000:
        raise ValueError("SRO successor fact bound")
    seen = set()
    for pick in observed["picks"]:
        if (
            pick["id"] in seen
            or pick["sourceId"] != "SRC_039"
            or pick["authorUrl"] not in OWNER_URLS
            or pick["authorId"] != owner_id(pick["authorUrl"])
            or pick["fixtureId"] not in fixtures
            or _instant(pick["kickoff"]) != _instant(fixtures[pick["fixtureId"]]["kickoff"])
            or _instant(pick["firstSeenAt"]) > _instant(pick["observedAt"])
            or _instant(pick["observedAt"]) >= _instant(pick["kickoff"])
            or _instant(pick["lastSeenAt"]) < _instant(pick["observedAt"])
            or _instant(pick["lastSeenAt"]) >= _instant(pick["kickoff"])
        ):
            raise ValueError("SRO successor fact attribution/timing")
        seen.add(pick["id"])


def _read(root: Path, deadline: float | None = None) -> tuple[dict[str, Any], bool] | None:
    path = root / CONFIG
    if not path.exists():
        return None
    if path.stat().st_size > 8_192:
        raise ValueError("SRO successor config bound")
    config = json.loads(path.read_bytes())
    pins = (
        "readerSha256", "sourceDecisionSha256", "privacyDecisionSha256",
        "scaleDecisionSha256", "taskDecisionSha256", "dataDecisionSha256", "nativeXmlSha256",
    )
    if set(config) != {"directory", *pins}:
        raise ValueError("SRO successor config shape")
    if Path(config["directory"]).resolve() != (PACKET / "runtime").resolve():
        raise ValueError("SRO successor directory")
    for key in pins:
        if not isinstance(config[key], str) or not re.fullmatch("[0-9a-f]{64}", config[key]):
            raise ValueError("SRO successor pin")
    reader = PACKET / "read.py"
    if reader.stat().st_size > 100_000 or sha256(reader.read_bytes()).hexdigest() != config["readerSha256"]:
        raise ValueError("SRO successor reader pin")
    if sha256(PYTHON.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise ValueError("SRO successor isolated Python pin")
    remaining = min(5.0, deadline - monotonic() - 0.3) if deadline is not None else 5.0
    if remaining <= 0:
        raise TimeoutError("parent reader budget exhausted")
    command = [str(PYTHON), "-I", "-S", "-B", str(reader), "--directory", config["directory"]]
    for name in ("source", "privacy", "scale", "task", "data"):
        command.extend([f"--{name}-decision-sha256", config[f"{name}DecisionSha256"]])
    result = subprocess.run(  # nosec B603
        command, capture_output=True, text=True, encoding="utf-8", timeout=remaining,
        check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if len(result.stdout) > 4_000_000:
        raise ValueError("SRO successor projection bound")
    value = json.loads(result.stdout)
    observed, operational = value["observed"], value["operational"]
    _validate(observed, operational)
    if observed["sroNextCampaign"]["nativeXmlSha256"] != config["nativeXmlSha256"]:
        raise ValueError("SRO successor native XML binding")
    if deadline is not None and monotonic() > deadline:
        raise TimeoutError("SRO successor parent budget exceeded")
    return observed, operational


def _merge(previous: list[dict[str, Any]], observed: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    campaign = observed["sroNextCampaign"]
    combined = {p["id"]: deepcopy(p) for p in previous}
    if len(combined) != len(previous):
        raise ValueError("SRO historical duplicate identity")
    updates: dict[str, dict[str, Any]] = {}
    for pick in observed["picks"]:
        old = combined.get(pick["id"])
        if old is None:
            if campaign["futureReceiptReview"] == "CONTRACT_VALIDATED":
                receipt = _future_receipt(pick, campaign)
                combined[pick["id"]] = deepcopy(pick)
                updates[pick["id"]] = dict(
                    lastSeenAt=pick["lastSeenAt"], claimId=ALGORITHM_CLAIM,
                    receiptSHA256=receipt["receiptSHA256"], receiptLineage=[deepcopy(receipt)],
                )
            continue
        if {k: v for k, v in old.items() if k != "lastSeenAt"} != {
            k: v for k, v in pick.items() if k != "lastSeenAt"
        }:
            raise ValueError("SRO successor contradicts complete historical fact")
        latest = pick["lastSeenAt"]
        if _instant(latest) > _instant(old.get("lastSeenAt", old["observedAt"])):
            is_canary = (
                pick["id"] in campaign.get("canaryPickIds", [])
                and _instant(latest) <= _instant(campaign["canaryObservedAt"])
            )
            if is_canary or campaign["futureReceiptReview"] == "CONTRACT_VALIDATED":
                receipt = {} if is_canary else _future_receipt(pick, campaign)
                updates[pick["id"]] = dict(
                    lastSeenAt=latest,
                    claimId=CANARY_CLAIM if is_canary else ALGORITHM_CLAIM,
                    receiptSHA256=campaign["canaryReceiptSHA256"] if is_canary else receipt["receiptSHA256"],
                    receiptLineage=[] if is_canary else [deepcopy(receipt)],
                )
    return list(combined.values()), updates


def _future_receipt(pick: dict[str, Any], campaign: dict[str, Any]) -> dict[str, Any]:
    lineage = campaign.get("receiptLineage", [])
    if not isinstance(lineage, list):
        raise ValueError("SRO future receipt lineage shape")
    for row in lineage:
        if not isinstance(row, dict) or not isinstance(row.get("pickIds", []), list):
            raise ValueError("SRO future receipt entry shape")
    receipts: list[dict[str, Any]] = [
        row for row in lineage
        if pick["id"] in row.get("pickIds", [])
        and row.get("futureReceiptReview") == "CONTRACT_VALIDATED"
        and _instant(row["observedAt"]) >= _instant(pick["lastSeenAt"])
    ]
    if not receipts:
        raise ValueError("SRO future fact receipt absent")
    receipt = max(receipts, key=lambda row: _instant(row["observedAt"]))
    for key in ("candidateSHA256", "receiptSHA256", "captureJournalPrefixSHA256", "captureJournalHead"):
        if not isinstance(receipt[key], str) or not re.fullmatch("[0-9a-f]{64}", receipt[key]):
            raise ValueError("SRO future fact receipt pin")
    return receipt


def _closed_candidates(base: dict[str, Any], state: str) -> dict[str, Any]:
    data = deepcopy(base)
    for row in [*data.get("candidates", []), *data.get("rosterAssessments", [])]:
        q = row.get("qualification")
        if isinstance(q, dict) and ("sroNextCampaignId" in q or "sroNextAuthorUrl" in q):
            row["collectionEnabled"] = False
    data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
    data.setdefault("qualification", {})["sroNextState"] = state
    return data


def add_sro_next_public(
    base: dict[str, Any], root: Path, *, deadline: float | None = None
) -> dict[str, Any]:
    try:
        result = _read(root, deadline=deadline)
        if result is None:
            return deepcopy(base)
        observed, operational = result
        _validate(observed, operational)
        picks, updates = _merge(base["picks"], observed)
        data = deepcopy(base)
        data.update(picks=picks, distinctPicks=len(picks),
                    authorCount=len({p["authorId"] for p in picks}),
                    sroNextCampaign=deepcopy(observed["sroNextCampaign"]))
        data["claimIds"] = list(dict.fromkeys([*base.get("claimIds", [base["claimId"]]), CANARY_CLAIM]))
        data["sroNextCompanion"] = dict(
            claimId=CANARY_CLAIM, scope="55_canary_reobservations_no_new_choices",
            updates=updates, governingAlgorithmClaimId=ALGORITHM_CLAIM,
            pendingNewPickCount=max(
                observed["sroNextCampaign"]["pendingFutureChoices"],
                sum(p["id"] not in {old["id"] for old in picks} for p in observed["picks"]),
            ),
        )
        return data
    except ERRORS:
        data = deepcopy(base)
        data["sroNextCampaign"] = dict(state="unavailable")
        return data


def add_sro_next_candidates(
    base: dict[str, Any], root: Path, *, deadline: float | None = None
) -> dict[str, Any]:
    try:
        result = _read(root, deadline=deadline)
        if result is None:
            return _closed_candidates(base, "not_configured")
        observed, operational = result
        _validate(observed, operational)
        if base.get("qualification", {}).get("status") != "ok":
            raise ValueError("SRO base qualification unavailable")
        historical: dict[str, dict[str, Any]] = {}
        incoming_ids = {pick["id"] for pick in observed["picks"]}
        rows = [*base.get("candidates", []), *base.get("rosterAssessments", [])]
        for row in rows:
            q = row.get("qualification")
            for pick in q.get("picks", []) if isinstance(q, dict) else []:
                if pick["id"] not in incoming_ids:
                    continue
                if pick["id"] in historical and historical[pick["id"]] != pick:
                    raise ValueError("SRO conflicting candidate history")
                historical[pick["id"]] = pick
        _, updates = _merge(list(historical.values()), observed)
        data = _closed_candidates(base, "ok")
        active = set(observed["sroNextCampaign"]["authorIds"])
        for row in [*data.get("candidates", []), *data.get("rosterAssessments", [])]:
            q = row.get("qualification")
            url = row.get("sourceUrl")
            if not isinstance(q, dict) or q.get("sourceId") != "SRC_039" or url not in OWNER_URLS:
                continue
            if any(
                p.get("sourceId") != "SRC_039" or p.get("authorUrl") != url
                or p.get("authorId") != owner_id(url)
                for p in q.get("picks", [])
            ):
                raise ValueError("SRO candidate contains another owner's fact")
            additions = [p for p in observed["picks"] if p["authorUrl"] == url and (
                p["id"] in historical or observed["sroNextCampaign"]["futureReceiptReview"] == "CONTRACT_VALIDATED"
            )]
            personal = {p["id"]: deepcopy(p) for p in q.get("picks", [])}
            for pick in additions:
                personal.setdefault(pick["id"], deepcopy(pick))
            q.update(
                picks=list(personal.values()), personallyProven=bool(personal),
                sroNextCampaignId=CAMPAIGN_ID, sroNextAuthorUrl=url,
                sroNextCampaign=deepcopy(observed["sroNextCampaign"]),
                sroNextCompanion=dict(updates={k: v for k, v in updates.items() if k in personal}),
            )
            row["collectionEnabled"] = bool(operational and owner_id(url) in active and personal)
        data["qualification"]["sroNextCampaignId"] = CAMPAIGN_ID
        data["enabledCount"] = sum(bool(r.get("collectionEnabled")) for r in data.get("candidates", []))
        return data
    except ERRORS:
        return _closed_candidates(base, "unavailable")

