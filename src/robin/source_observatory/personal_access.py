"""Source-specific personal-use assessment; never a collection grant."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .olbg_store import read_bundle
from .qualification_view import merge_sro_collection
from .recurring import instant

APPROVED_PERSONAL_SHA256 = "b26016a8af3d9d99679e7569dfd9a757ace21cdd553731df18ea6afe609044a1"
SCOPE = "LOCAL_PERSONAL_NONCOMMERCIAL_NO_REDISTRIBUTION"
FIELDS = (
    "label",
    "reason",
    "requiredAccess",
    "ownerAction",
    "observedAt",
    "status",
    "evidenceRefs",
)
PLATFORMS = {"Coteur", "Stavka.tv", "NotBetting", "Telegram", "Kicktipp"}


def _assessment(value: Any) -> None:
    if not isinstance(value, dict) or any(k not in value for k in FIELDS):
        raise ValueError("complete personal assessment required")
    if any(not isinstance(value[k], str) or not value[k] for k in FIELDS[:-1]):
        raise ValueError("personal assessment fields")
    refs = value["evidenceRefs"]
    if not isinstance(refs, list) or not refs or any(not isinstance(v, str) for v in refs):
        raise ValueError("personal source evidence required")


def apply_personal_access(base: dict[str, Any], path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 200_000 or sha256(raw).hexdigest() != expected_sha:
        raise ValueError("personal assessment hash")
    report = json.loads(raw)
    if (
        report.get("schemaVersion") != "robin-personal-access-v1"
        or report.get("scope") != SCOPE
        or not isinstance(report.get("claimId"), str)
        or not report["claimId"]
        or not isinstance(report.get("platforms"), list)
    ):
        raise ValueError("personal assessment scope/schema")
    rows = report["platforms"]
    access = {r["platform"]: r for r in rows}
    if len(access) != len(rows) or set(access) - PLATFORMS:
        raise ValueError("personal platform scope")
    for row in rows:
        _assessment(row)
        contests = row.get("contestAssessments", {})
        if not isinstance(contests, dict) or (contests and row["platform"] != "Kicktipp"):
            raise ValueError("contest assessment scope")
        for contest, value in contests.items():
            if re.fullmatch(r"[a-z0-9-]{1,64}", contest) is None:
                raise ValueError("unsafe contest")
            _assessment(value)
    data = deepcopy(base)
    qualification = data.setdefault("qualification", {})
    if qualification.get("status") != "ok":
        qualification["personalOverlayState"] = "unavailable"
        return data
    if qualification.get("personalClaimId") == report["claimId"]:
        return data
    for platform in qualification.get("platforms", []):
        row = access.get(platform["platform"])
        if row is None:
            continue
        platform.setdefault("previousPersonalAssessment", deepcopy(platform))
        platform.update({k: deepcopy(row[k]) for k in FIELDS})
        platform["personalClaimId"] = report["claimId"]
        if "contestAssessments" in row:
            platform["contestAssessments"] = deepcopy(row["contestAssessments"])
    for candidate in data.get("candidates", []):
        row = access.get(candidate["platform"])
        prior = candidate.get("qualification")
        if row is None or not isinstance(prior, dict):
            continue
        selected = row
        if candidate["platform"] == "Kicktipp":
            parsed = urlsplit(candidate.get("sourceUrl", ""))
            if parsed.hostname in {"www.kicktipp.fr", "www.kicktipp.de"}:
                contest = parsed.path.strip("/").split("/")[0]
                selected = row.get("contestAssessments", {}).get(contest, row)
        prior.setdefault("previousPersonalAssessment", {k: deepcopy(prior.get(k)) for k in FIELDS})
        was_proven = bool(prior.get("personallyProven"))
        for field in FIELDS:
            if was_proven and field in {"label", "reason"}:
                continue
            prior[field] = deepcopy(selected[field])
        prior["personalClaimId"] = report["claimId"]
    qualification.update(
        personalOverlayState="ok", personalClaimId=report["claimId"], personalUseScope=SCOPE
    )
    return data


def read_personal_access(base: dict[str, Any], path: Path, expected_sha: str) -> dict[str, Any]:
    try:
        return apply_personal_access(base, path, expected_sha)
    except (OSError, ValueError, TypeError, KeyError):
        data = deepcopy(base)
        data.setdefault("qualification", {})["personalOverlayState"] = "unavailable"
        return data


def merge_personal_public(base: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    data = merge_sro_collection(base, bundle)
    fixtures = {f["id"]: f for f in base.get("fixtures", [])}
    fixtures.update({f["id"]: f for f in bundle["fixtures"]})
    data["fixtures"] = list(fixtures.values())
    observed = [p["observedAt"] for p in data["picks"] if p.get("observedAt")]
    if observed:
        data["sourceObservedThrough"] = max(observed, key=instant)
    view_dates = [*observed, base.get("generatedAt"), bundle.get("qualifiedAt")]
    data["generatedAt"] = max((s for s in view_dates if s), key=instant)
    data["personalCollection"] = {
        "state": "historical_observations_qualified",
        "claimId": bundle["claimId"],
        "qualifiedAt": bundle["qualifiedAt"],
        "nativeChoices": len(bundle["picks"]),
        "newRecurringAuthority": False,
    }
    return data


def merge_personal_candidates(
    base: dict[str, Any], bundle: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    data = deepcopy(base)
    if data.get("qualification", {}).get("status") != "ok":
        return data
    for row in data.get("candidates", []):
        if (
            row.get("id") != identity["candidateId"]
            or row.get("sourceUrl") != identity["sourceUrl"]
            or row.get("origin", {}).get("sheet") != identity["sheet"]
            or row.get("origin", {}).get("row") != identity["row"]
        ):
            continue
        q = row.get("qualification")
        if not isinstance(q, dict):
            continue
        picks = {p["id"]: p for p in q.get("picks", [])}
        new = [p for p in bundle["picks"] if p["authorUrl"] == row["sourceUrl"]]
        picks.update({p["id"]: p for p in new})
        q.update(
            picks=list(picks.values()),
            personallyProven=bool(picks),
            personalCollectionClaimId=bundle["claimId"],
        )
        q.setdefault(
            "previousPersonalCollectionAssessment",
            {k: deepcopy(q.get(k)) for k in ("label", "reason", "ownerAction")},
        )
        q.update(
            label="Choix personnels observés avant match",
            reason=f"{len(picks)} choix natifs prouvés par les observations conservées et les calendriers officiels, dont les preuves complémentaires de cette phase personnelle.",
            ownerAction="Ces preuves n’activent aucune campagne. L’état des collectes et leurs dates d’expiration restent contrôlés séparément.",
        )
        admitted_ids = {p["sourceTipId"] for p in new}
        q["unadmittedFacts"] = [
            p for p in q.get("unadmittedFacts", []) if p.get("sourceTipId") not in admitted_ids
        ]
    data["qualification"]["qualifiedCount"] = sum(
        bool(r.get("qualification", {}).get("personallyProven")) for r in data["candidates"]
    )
    return data


def _load_personal(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = (root / "reports/source_observatory/TIPSTERS-PERSONAL-ACCESS-20261120.json").read_bytes()
    if len(raw) > 200_000 or sha256(raw).hexdigest() != APPROVED_PERSONAL_SHA256:
        raise ValueError("personal collection report hash")
    report = json.loads(raw)
    if report.get("scope") != SCOPE or report.get("schemaVersion") != "robin-personal-access-v1":
        raise ValueError("personal collection scope")
    digest = report["collection"]["bundleSha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise ValueError("personal collection bundle anchor")
    path = root / "cockpit/.ci/tipsters-personal-20261120" / f"observations-{digest}.json"
    bundle = read_bundle(path, digest)
    if bundle["claimId"] != report["collection"]["claimId"]:
        raise ValueError("personal collection claim")
    return report, bundle


def add_personal_public(base: dict[str, Any], root: Path) -> dict[str, Any]:
    try:
        _, bundle = _load_personal(root)
        return merge_personal_public(base, bundle)
    except (OSError, ValueError, KeyError, TypeError):
        data = deepcopy(base)
        data["personalCollection"] = {"state": "unavailable"}
        return data


def add_personal_candidates(base: dict[str, Any], root: Path) -> dict[str, Any]:
    report_path = root / "reports/source_observatory/TIPSTERS-PERSONAL-ACCESS-20261120.json"
    data = read_personal_access(base, report_path, APPROVED_PERSONAL_SHA256)
    try:
        report, bundle = _load_personal(root)
        return merge_personal_candidates(data, bundle, report["collection"]["candidateIdentity"])
    except (OSError, ValueError, KeyError, TypeError):
        data.setdefault("qualification", {})["personalCollectionState"] = "unavailable"
        return data
