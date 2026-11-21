"""Current source-access overlay; the immutable initial assessment is preserved."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

APPROVED_TECHNICAL_SHA256 = "3f9c399ff659657d7f226ca5a96cb165cd39291240e880692a49a68047616085"


def apply_technical_access(base: dict[str, Any], path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 500_000 or sha256(raw).hexdigest() != expected_sha:
        raise ValueError("technical access hash")
    report = json.loads(raw)
    if report.get("schemaVersion") != "robin-source-technical-access-v1":
        raise ValueError("technical access schema")
    data = deepcopy(base)
    access = {r["platform"]: r for r in report["platforms"]}
    if len(access) != len(report["platforms"]) or set(access) - {
        "OLBG",
        "NotBetting",
        "Kicktipp",
        "Stavka.tv",
        "Telegram",
    }:
        raise ValueError("technical platform scope")
    fields = [
        "label",
        "reason",
        "requiredAccess",
        "ownerAction",
        "observedAt",
        "status",
        "evidenceRefs",
    ]
    for scope in data["qualification"]["platforms"]:
        if scope["platform"] in access:
            scope["initialAssessment"] = deepcopy(scope)
            scope.update({k: access[scope["platform"]][k] for k in fields})
            scope["technicalClaimId"] = report["claimId"]
    for row in data["candidates"]:
        q = row.get("qualification")
        if not q or row["platform"] not in access:
            continue
        q["initialAssessment"] = {k: q.get(k) for k in fields + ["profileVisited"]}
        q.update({k: access[row["platform"]][k] for k in fields})
        q["technicalClaimId"] = report["claimId"]
        if q["personallyProven"]:
            q.update(
                label="Choix personnels observés avant match",
                profileVisited=True,
                requiredAccess="Aucun compte pour les choix personnels prouvés de ce profil ; usage privé local uniquement.",
            )
    data["qualification"]["technicalClaimId"] = report["claimId"]
    return data
