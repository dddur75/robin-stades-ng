"""Read-only, partial access assessment; original source proofs stay immutable."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

APPROVED_NT_FOLLOWUP_SHA256 = "63c510318b84028c027d0a27f8634cc8341e4b72e97e38cb5f468c797b2ddadc"
FIELDS = (
    "label",
    "reason",
    "requiredAccess",
    "ownerAction",
    "observedAt",
    "status",
    "evidenceRefs",
)


def apply_followup_access(base: dict[str, Any], path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 500_000 or sha256(raw).hexdigest() != expected_sha:
        raise ValueError("follow-up access hash")
    report = json.loads(raw)
    if not isinstance(report, dict):
        raise ValueError("follow-up report object")
    rows = report.get("platforms", [])
    if report.get("schemaVersion") != "robin-nt-qualification-v1" or not report.get("claimId"):
        raise ValueError("follow-up access schema")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("follow-up platform rows")
    access = {row["platform"]: row for row in rows}
    if len(rows) != 2 or set(access) != {"NotBetting", "Telegram"}:
        raise ValueError("follow-up platform scope")
    for row in rows:
        if any(not isinstance(row.get(k), str) or not row[k] for k in FIELDS[:-1]):
            raise ValueError("follow-up access fields")
        if (
            not isinstance(row.get("evidenceRefs"), list)
            or not row["evidenceRefs"]
            or not all(isinstance(x, str) for x in row["evidenceRefs"])
        ):
            raise ValueError("follow-up evidence references")
    data = deepcopy(base)
    qualification = data["qualification"]
    claim_id = report["claimId"]
    claims = list(qualification.get("technicalClaimIds", []))
    for value in [qualification.get("technicalClaimId"), claim_id]:
        if value and value not in claims:
            claims.append(value)
    qualification["technicalClaimIds"] = claims
    qualification["followupOverlayState"] = "ok"

    def apply(item: dict[str, Any], platform: str) -> None:
        if platform not in access or item.get("technicalClaimId") == claim_id:
            return
        previous = {
            k: deepcopy(item[k])
            for k in (*FIELDS, "profileVisited", "technicalClaimId")
            if k in item
        }
        if "initialAssessment" not in item:
            item["initialAssessment"] = deepcopy(previous)
        item["previousTechnicalAssessment"] = previous
        item.update({k: deepcopy(access[platform][k]) for k in FIELDS})
        item["technicalClaimId"] = claim_id

    for item in qualification.get("platforms", []):
        apply(item, item["platform"])
    for row in data["candidates"]:
        if row.get("qualification"):
            apply(row["qualification"], row["platform"])
    return data
