"""Read-only projection of the authorized local tipsters pilot into cockpit data."""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HASH = re.compile(r"[0-9a-f]{64}")
DECIMAL = re.compile(r"-?\d{1,5}(?:\.\d{1,5})?")
MAX_JOURNAL_BYTES = 32_000_000
STATUSES = {"ok": "succeeded", "read_failed": "failed", "blocked_robots": "blocked",
            "skipped_delay_or_cutoff": "skipped"}


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timezone missing")
    return result.astimezone(timezone.utc)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def bounded_file(path: Path, maximum: int = MAX_JOURNAL_BYTES) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("file exceeds local projection limit")
    return value


def text(value: Any, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError("invalid text field")
    return value


def source_url(value: Any) -> str:
    url = urlsplit(text(value, 500))
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(ord(c) < 32 for c in value)):
        raise ValueError("invalid source reference")
    return url.geturl()


def optional_decimal(value: Any) -> str | None:
    if value is not None and (not isinstance(value, str) or DECIMAL.fullmatch(value) is None):
        raise ValueError("invalid decimal field")
    return value


def project(directory: Path, plan_digest: str, now: datetime) -> dict[str, Any]:
    raw_plan = bounded_file(directory / "plan.json", 500_000)
    if HASH.fullmatch(plan_digest) is None or sha256(raw_plan).hexdigest() != plan_digest:
        raise ValueError("plan fingerprint mismatch")
    plan = json.loads(raw_plan)
    manifest_raw = bounded_file(directory / "manifest.json", 500_000)
    manifest = json.loads(manifest_raw)
    authority = json.loads(bounded_file(directory / "autorisation.json", 500_000))
    pins_raw = bounded_file(directory / "empreintes.json", 500_000)
    pins = json.loads(pins_raw)
    if (authority["decision"] != "AUTHORIZED" or not authority["decision_reference"]
            or authority["manifest_sha256"] != sha256(manifest_raw).hexdigest()
            or manifest["source_hash"] != sha256(pins_raw).hexdigest()
            or pins["plan_sha256"] != plan_digest
            or manifest["mission_id"] != plan["id"]
            or authority["mission_id"] != plan["id"]
            or authority["requests_max"] != plan["requests_max"]
            or manifest["compute_budget"]["requests_max"] != plan["requests_max"]
            or manifest["expires_at"] != plan["expires_at"]):
        raise ValueError("pilot authorization mismatch")

    starts, expires = instant(plan["starts_at"]), instant(plan["expires_at"])
    fixtures = {f["id"]: f for f in plan["fixtures"]}
    slots = {s["at"]: s for s in plan["slots"]}
    expected = {(s["at"], f) for s in plan["slots"] for f in s["fixtures"]}
    if (len(fixtures) != len(plan["fixtures"]) or len(slots) != len(plan["slots"])
            or len(expected) + len(slots) != plan["requests_max"]
            or not 1 <= plan["due_window_seconds"] <= 180):
        raise ValueError("invalid pilot schedule")
    for slot, fixture in expected:
        if not starts <= instant(slot) < min(expires, instant(fixtures[fixture]["kickoff"])):
            raise ValueError("invalid fixture or time")

    journal = directory / "observations.jsonl"
    journal_present = journal.exists()
    raw = bounded_file(journal) if journal_present else b""
    if raw and not raw.endswith(b"\n"):
        return {"status": "updating", "message": "Le journal est en cours d’écriture."}
    previous = "0" * 64
    begun: dict[str, datetime] = {}
    ended: set[str] = set()
    visits: dict[tuple[str, str], dict[str, Any]] = {}
    picks: dict[tuple[str, str], dict[str, Any]] = {}
    for line in raw.splitlines(keepends=True):
        record = json.loads(line)
        digest = record.pop("hash")
        if (record["previous_hash"] != previous or sha256(canonical(record)).hexdigest() != digest
                or canonical(record | {"hash": digest}) + b"\n" != line
                or record["plan_sha256"] != plan_digest):
            raise ValueError("journal integrity or plan mismatch")
        previous = digest
        slot, kind = record["slot"], record["kind"]
        if slot not in slots or slot in ended:
            raise ValueError("unknown or closed journal slot")
        if kind == "slot_started":
            at = instant(record["at"])
            if (slot in begun or not timedelta(0) <= at - instant(slot)
                    < timedelta(seconds=plan["due_window_seconds"])):
                raise ValueError("duplicate or late slot start")
            if at > now:
                raise ValueError("future journal record")
            begun[slot] = at
            continue
        if slot not in begun:
            raise ValueError("journal slot has no start")
        if kind == "slot_finished":
            at = instant(record["at"])
            latest = max([begun[slot]] + [instant(visit["observed_at"])
                         for (visit_slot, _), visit in visits.items()
                         if visit_slot == slot and visit.get("observed_at") is not None])
            if not latest <= at <= now or any((slot, f) not in visits for f in slots[slot]["fixtures"]):
                raise ValueError("incomplete slot closure")
            ended.add(slot)
            continue
        key = (slot, record.get("fixture"))
        if kind != "visit" or key not in expected or key in visits or record["status"] not in STATUSES:
            raise ValueError("unexpected or duplicate visit")
        if record.get("observed_at") is not None:
            observed_at = instant(record["observed_at"])
            if not begun[slot] <= observed_at <= now:
                raise ValueError("invalid visit timestamp")
            record["observed_at"] = observed_at.isoformat()
        visits[key] = record
        if record["status"] != "ok":
            continue
        observed, kickoff = instant(record["observed_at"]), instant(fixtures[key[1]]["kickoff"])
        if (not begun[slot] <= observed < min(kickoff, expires) or observed > now
                or record["http_status"] != 200 or HASH.fullmatch(record["response_sha256"]) is None):
            raise ValueError("successful visit has no pre-match proof")
        in_visit: set[str] = set()
        for pick in record["picks"]:
            pick_id = text(pick["provider_observation_id"])
            if pick_id in in_visit:
                raise ValueError("duplicate pick in a single visit")
            in_visit.add(pick_id)
            author = pick.get("attribution_key", pick.get("author_key"))
            if (not isinstance(author, str) or HASH.fullmatch(author) is None
                    or (pick.get("author_key") and pick.get("attribution_key")
                        and pick["author_key"] != pick["attribution_key"])):
                raise ValueError("ambiguous attribution")
            detected = instant(pick["forecast_record_detected_at"])
            published = instant(pick["published_at"]) if pick["published_at"] is not None else None
            if detected > observed or detected >= kickoff or (published is not None and published > detected):
                raise ValueError("pick has no pre-match proof")
            attribution_basis = "publication" if "attribution_key" not in pick else "declared"
            author_id = sha256(canonical([attribution_basis, author])).hexdigest()
            version = {
                "observedAt": observed.isoformat(), "detectedAt": detected.isoformat(),
                "publishedAt": published.isoformat() if published else None,
                "market": text(pick["market"]), "selection": text(pick["selection"]),
                "period": text(pick["period"]) if pick["period"] is not None else None,
                "line": optional_decimal(pick["line"]), "odds": optional_decimal(pick["declared_odds"]),
                "sourceUrl": source_url(pick["source_url"]),
            }
            identity = (key[1], pick_id)
            if identity not in picks:
                picks[identity] = {"id": sha256(canonical(identity)).hexdigest(), "providerId": pick_id,
                                   "fixtureId": key[1], "authorId": author_id,
                                   "attributionBasis": attribution_basis,
                                   "firstSeenAt": observed.isoformat(), "lastSeenAt": observed.isoformat(),
                                   "versions": [version]}
            else:
                existing = picks[identity]
                if existing["authorId"] != author_id or observed < instant(existing["lastSeenAt"]):
                    raise ValueError("pick attribution or chronology changed")
                existing["lastSeenAt"] = observed.isoformat()
                if version | {"observedAt": None} != existing["versions"][-1] | {"observedAt": None}:
                    existing["versions"].append(version)

    visit_rows: list[dict[str, Any]] = []
    for slot, fixture in sorted(expected):
        record = visits.get((slot, fixture))
        status = "planned"
        if record:
            status = STATUSES[record["status"]]
        elif slot in begun:
            status = "running" if now - begun[slot] < timedelta(seconds=240) else "interrupted"
        elif now >= instant(slot) + timedelta(seconds=plan["due_window_seconds"]):
            status = "missed"
        visit_rows.append({"slot": slot, "fixtureId": fixture, "status": status,
                           "observedAt": record.get("observed_at") if record else None,
                           "picks": len(record.get("picks", [])) if record and record["status"] == "ok" else None})
    counts = Counter(row["status"] for row in visit_rows)
    authors: dict[str, dict[str, Any]] = {}
    for pick in picks.values():
        author = authors.setdefault(pick["authorId"], {
            "id": pick["authorId"], "label": f"Tipster {pick['authorId'][:12]}",
            "attributionBasis": pick["attributionBasis"], "picks": 0, "fixtureIds": set(),
            "firstSeenAt": pick["firstSeenAt"], "lastSeenAt": pick["lastSeenAt"],
        })
        author["picks"] += 1
        author["fixtureIds"].add(pick["fixtureId"])
        author["firstSeenAt"] = min(author["firstSeenAt"], pick["firstSeenAt"])
        author["lastSeenAt"] = max(author["lastSeenAt"], pick["lastSeenAt"])
    for author in authors.values():
        author["fixtureIds"] = sorted(author["fixtureIds"])
    head = previous if raw else None
    claim_id = "DATA.SOURCE_OBSERVATORY.J12.LOCAL_JOURNAL.V1"
    journal_claim_id = f"DATA.SOURCE_OBSERVATORY.J12.{head or plan_digest}"
    phase = "scheduled" if now < starts else "closed" if now >= expires else "collecting"
    complete = bool(head) and set(slots) == ended and counts["succeeded"] == len(expected) and bool(picks)
    verdict = "PASS_AND_HOLD" if phase == "closed" and complete else "PARTIAL" if phase == "closed" else "PENDING"
    return {
        "status": "ok", "schemaVersion": "robin-tipsters-pilot-v1", "generatedAt": now.isoformat(),
        "phase": phase, "source": "Forecast Record", "missionId": plan["id"],
        "startsAt": starts.isoformat(), "expiresAt": expires.isoformat(),
        "requestsMax": plan["requests_max"], "plannedSlots": len(slots), "plannedVisits": len(expected),
        "journalPresent": journal_present, "journalHead": head, "counts": dict(counts),
        "distinctPicks": len(picks) if counts["succeeded"] else None, "lastObservationAt": max(
            (row["observedAt"] for row in visit_rows if row["observedAt"]), default=None),
        "technicalVerdict": verdict, "dossierVerdict": "PARTIAL",
        "fixtures": [{"id": f["id"], "label": f["label"], "kickoff": f["kickoff"]} for f in fixtures.values()],
        "visits": visit_rows, "tipsters": sorted(authors.values(), key=lambda a: a["id"]),
        "picks": sorted(picks.values(), key=lambda p: (p["firstSeenAt"], p["id"])),
        "evidence": {"claimId": claim_id, "planSha256": plan_digest,
                     "journalClaimId": journal_claim_id, "journalHeadSha256": head,
                     "method": "sha256-chain-and-pre-match-validation"},
        "evidenceGraph": {"claims": [{"claim_id": journal_claim_id, "status": "PARTIAL",
                                      "hash": head or plan_digest, "scope": "LOCAL_PILOT_PROJECTION",
                                      "registration_claim_id": claim_id}]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-directory", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    args = parser.parse_args()
    try:
        result = project(args.pilot_directory, args.plan_sha256, datetime.now(timezone.utc))
    except FileNotFoundError:
        result = {"status": "unavailable", "message": "Le dossier autorisé du pilote est indisponible."}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        result = {"status": "invalid", "message": "Les preuves du pilote ne passent pas le contrôle d’intégrité."}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
