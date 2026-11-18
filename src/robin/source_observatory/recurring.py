"""Bounded recurring Forecast Record observations, independent of frozen J12."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .collector import robots_policy
from .connectors import Journal, Response, canonical, public_get, read_events, stamp

HOST = "https://forecastrecord.com"
INDEX = HOST + "/football/matches/europe/france/index.json"
TERMS = HOST + "/api/index.json"
ROBOTS = HOST + "/robots.txt"
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+/ -]{0,159}")
PIN_PATHS = [
    "cockpit/scripts/tipsters-recurring.py",
    "cockpit/scripts/tipsters-recurring-task.ps1",
    "cockpit/scripts/tipsters-recurring-tick.ps1",
    *(
        "src/robin/source_observatory/" + name
        for name in [
            "recurring.py",
            "connectors.py",
            "collector.py",
            "public_formats.py",
            "extractor.py",
            "models.py",
            "schema_validation.py",
        ]
    ),
]


def code_pins(root: Path) -> dict[str, str]:
    return {
        p: sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in PIN_PATHS
    }


def close_campaign(directory: Path, *, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if current < instant(manifest["expires_at"]):
        raise ValueError("closure before expiry")
    lock = directory / "recurring.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(stamp(current))
    try:
        journal = Journal(directory, manifest)
        if not any(e["kind"] == "CAMPAIGN_CLOSED" for e in journal.events):
            journal.append("CAMPAIGN_CLOSED", providerRequests=0)
    finally:
        lock.unlink()


def instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("explicit timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("timezone required")
    return result.astimezone(UTC)


def number(value: Any, *, odds: bool = False) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
        if not d.is_finite() or abs(d) > 100000 or odds and d <= 1:
            return None
        return format(d, "f")
    except InvalidOperation:
        return None


def origin_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 1500 or any(ord(c) <= 32 for c in value):
        return None
    p = urlsplit(value)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        return None
    query = []
    for key, item in parse_qsl(p.query):
        if re.search("token|secret|password|api.?key|session|authorization", key, re.I):
            return None
        if not re.match("utm_|fbclid|gclid", key, re.I):
            query.append((key, item))
    if p.hostname.removeprefix("www.") in {"youtube.com", "m.youtube.com"} and p.path == "/watch":
        if not any(k == "v" and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", v) for k, v in query):
            return None
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def event_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("event URL missing")
    url = urljoin(HOST, value)
    p = urlsplit(url)
    if p.netloc != "forecastrecord.com" or p.scheme != "https" or p.query or p.fragment:
        raise ValueError("event URL outside provider")
    path = p.path.removesuffix("index.json")
    if not re.fullmatch(r"/football/matches/[a-z0-9-]+/", path):
        raise ValueError("non-event URL")
    return HOST + path + "index.json"


def project_forecasts(data: dict[str, Any], url: str, observed: datetime) -> list[dict[str, Any]]:
    if event_url(data.get("canonical")) != event_url(url):
        raise ValueError("event canonical identity mismatch")
    if data.get("schema_version") != "2.0" or data.get("page_type") != "event":
        raise ValueError("provider schema changed")
    event = data.get("event") or {}
    kickoff = instant(event.get("starts_at"))
    identifier = event.get("id")
    if (
        not isinstance(identifier, str)
        or not identifier
        or event.get("competition_name") != "Ligue 1"
        or event.get("status") != "scheduled"
        or event.get("condition") != "scheduled"
        or event.get("postponement")
        or observed >= kickoff
        or data.get("restrictions", {}).get("name_withdrawn")
    ):
        return []
    picks = []
    for item in data.get("evidence_items", []):
        source, authorship, claim = (
            item.get("source_info") or {},
            item.get("authorship") or {},
            item.get("author_claim") or {},
        )
        author = authorship.get("forecaster")
        publisher = authorship.get("publisher") or source.get("publisher")
        if (
            item.get("withdrawn") is not False
            or item.get("late_publication")
            or source.get("material_removed")
            or source.get("authorship") == "channel_consensus"
            or authorship.get("excluded_from_individual_summaries")
            or authorship.get("automated")
            or authorship.get("forecaster_named_in_text") is not True
            or item.get("origin") != "recorded_before_kickoff"
            or item.get("status") != "recognised"
            or not isinstance(author, str)
            or not author.strip()
            or len(author) > 160
        ):
            continue
        detected_value = (item.get("dates") or {}).get("detected_at") or item.get("detected_at")
        try:
            detected = instant(detected_value)
            published = instant(item["published_at"]) if item.get("published_at") else None
        except ValueError:
            continue
        if (
            detected > observed
            or detected >= kickoff
            or published
            and (published > observed or published >= kickoff)
        ):
            continue
        reference = origin_url(source.get("url") or item.get("url"))
        pick_id, market, selection = (
            item.get("observation_id"),
            claim.get("market_key"),
            claim.get("choice_key"),
        )
        if not reference or any(
            not isinstance(v, str) or not TOKEN.fullmatch(v) for v in (pick_id, market, selection)
        ):
            continue
        author_id = (
            "forecaster:"
            + sha256(
                canonical([urlsplit(reference).hostname, publisher, author.strip()])
            ).hexdigest()
        )
        picks.append(
            dict(
                id=sha256(canonical([identifier, pick_id])).hexdigest(),
                providerId=pick_id,
                fixtureId=identifier,
                fixtureLabel=event.get("name") or identifier,
                kickoff=stamp(kickoff),
                authorId=author_id,
                attributionBasis="declared",
                attributionRole="individual_forecaster_declared",
                humanIdentityVerified=False,
                sourceUrl=reference,
                providerUrl=url,
                market=market,
                selection=selection,
                line=number(claim.get("line")),
                period=claim.get("period") if isinstance(claim.get("period"), str) else None,
                declaredOdds=number(claim.get("author_odds"), odds=True),
                publishedAt=stamp(published) if published else None,
                detectedAt=stamp(detected),
                observedAt=stamp(observed),
            )
        )
    return list({p["id"]: p for p in picks}.values())


def discover(data: dict[str, Any]) -> list[str]:
    if (
        data.get("schema_version") != "2.0"
        or data.get("catalog", {}).get("contract_version") != "1"
    ):
        raise ValueError("catalog schema changed")
    urls = []
    for group in data["catalog"]["groups"]:
        if group.get("title") == "France · Ligue 1":
            for item in group.get("items", []):
                urls.append(event_url(item.get("url")))
    return sorted(set(urls))[:30]


def terms_allowed(data: dict[str, Any]) -> bool:
    if data.get("schema_version") != "2.0" or data.get("page_type") != "api":
        return False
    free = [
        p
        for p in data.get("plans", [])
        if p.get("display_name") == "Public" and p.get("status") == "available"
    ]
    rules = " ".join(
        str(b.get("body", ""))
        for b in data.get("text_blocks", [])
        if b.get("heading") == "Rules of use"
    )
    return bool(
        free
        and free[0].get("requests_per_month", 0) >= 1000
        and free[0].get("limit_per_minute", 0) >= 10
        and "Attribution to the source page is required" in rules
        and "what we license is the measurement" in rules
    )


def plan_hash(plan: dict[str, Any]) -> str:
    return sha256(canonical(plan)).hexdigest()


def validate_package(
    directory: Path, *, execute: bool, pins: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((directory / "manifest.json").read_bytes())
    plan = json.loads((directory / "plan.json").read_bytes())
    if (
        manifest["mission_id"] != plan["id"]
        or manifest["source_hash"] != plan["sourceHash"]
        or manifest["expires_at"] != plan["expiresAt"]
        or manifest["maximum_stage"] != "E2"
        or plan["indexUrl"] != INDEX
        or plan["maxEventsPerSlot"] not in {1, 2, 3}
        or plan["dueWindowSeconds"] not in range(30, 181)
    ):
        raise ValueError("invalid campaign bounds")
    slots = [instant(s) for s in plan["slots"]]
    if (
        not slots
        or slots != sorted(set(slots))
        or slots[0] != instant(plan["startsAt"])
        or slots[-1] >= instant(plan["expiresAt"])
        or len(slots) > 168
        or any(
            datetime(2026, 11, 26, 7, 40, tzinfo=UTC) <= s < datetime(2026, 11, 29, 20, tzinfo=UTC)
            for s in slots
        )
    ):
        raise ValueError("invalid slots or J12 overlap")
    authority_path = directory / "authorization.json"
    if execute:
        if plan["codePins"] != pins or not authority_path.exists():
            raise ValueError("authorization or code pins missing")
        authority = json.loads(authority_path.read_bytes())
        if (
            authority.get("decision") != "AUTHORIZED"
            or not authority.get("decisionReference")
            or authority.get("planSha256") != plan_hash(plan)
            or authority.get("manifestSha256")
            != sha256((directory / "manifest.json").read_bytes()).hexdigest()
        ):
            raise ValueError("authorization mismatch")
    return manifest, plan


def execute_slot(
    directory: Path,
    *,
    pins: dict[str, str],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    get: Callable[[str], Response] = public_get,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    manifest, plan = validate_package(directory, execute=True, pins=pins)
    observed = now()
    if observed >= instant(plan["expiresAt"]):
        return "closed"
    due = [
        s
        for s in plan["slots"]
        if 0 <= (observed - instant(s)).total_seconds() < plan["dueWindowSeconds"]
    ]
    if len(due) != 1:
        return "no_due_slot"
    lock = directory / "recurring.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(stamp(observed))
    try:
        j = Journal(directory, manifest, now=now)
        if any(r["kind"] == "CAMPAIGN_HALTED" for r in j.events):
            return "halted"
        slot = due[0]
        if any(r["kind"] == "SLOT_STARTED" and r["slot"] == slot for r in j.events):
            return "already_claimed"
        j.append("SLOT_STARTED", slot=slot, planSha256=plan_hash(plan))
        j.append("RUN_STARTED", slot=slot)
        rules: str | None = None

        def fetch(url: str) -> Response:
            if url not in {ROBOTS, TERMS, INDEX}:
                event_url(url)
            if now() >= min(
                instant(plan["expiresAt"]),
                instant(slot) + timedelta(seconds=plan["dueWindowSeconds"]),
            ):
                raise ValueError("slot request window ended")
            if rules is not None:
                allowed, delay = robots_policy(rules, url)
                if not allowed or delay > 30:
                    raise ValueError("robots denied or delay unsupported")
            else:
                delay = 0
            previous = next(
                (e for e in reversed(j.events) if e["kind"] == "REQUEST_RESERVED"), None
            )
            if previous:
                wait = max(7.0, delay) - (now() - instant(previous["at"])).total_seconds()
                if wait > 0:
                    sleep(wait)
            if now() >= min(
                instant(plan["expiresAt"]),
                instant(slot) + timedelta(seconds=plan["dueWindowSeconds"]),
            ):
                raise ValueError("slot expired after pacing")
            reservation = j.reserve("FORECAST_RECORD", url)
            try:
                remaining = min(
                    j.remaining_seconds(),
                    (instant(plan["expiresAt"]) - now()).total_seconds(),
                    (
                        instant(slot) + timedelta(seconds=plan["dueWindowSeconds"]) - now()
                    ).total_seconds(),
                )
                if remaining <= 0:
                    raise ValueError("request window exhausted")
                response = (
                    public_get(url, timeout=min(40, remaining)) if get is public_get else get(url)
                )
            except (OSError, ValueError) as exc:
                j.append(
                    "REQUEST_FAILED",
                    reservation=reservation,
                    sourceId="FORECAST_RECORD",
                    url=url,
                    errorType=type(exc).__name__,
                    slot=slot,
                )
                raise
            j.append(
                "REQUEST_FINISHED",
                reservation=reservation,
                sourceId="FORECAST_RECORD",
                url=url,
                httpStatus=response.status,
                bytes=len(response.body),
                responseSha256=sha256(response.body).hexdigest(),
                slot=slot,
            )
            if response.status != 200:
                if response.status in {401, 403, 429}:
                    j.append(
                        "CAMPAIGN_HALTED", slot=slot, reason=f"provider_http_{response.status}"
                    )
                raise ValueError("provider response not 200")
            if now() >= min(
                instant(plan["expiresAt"]),
                instant(slot) + timedelta(seconds=plan["dueWindowSeconds"]),
            ):
                raise ValueError("response after authorized window")
            return response

        try:
            rules = fetch(ROBOTS).body.decode("utf-8-sig")
            if not terms_allowed(json.loads(fetch(TERMS).body)):
                raise ValueError("terms or free quota changed")
            catalog = json.loads(fetch(INDEX).body)
            urls = discover(catalog)
            labels = {
                event_url(item["url"]): item["name"]
                for group in catalog["catalog"]["groups"]
                if group.get("title") == "France · Ligue 1"
                for item in group.get("items", [])
            }
            offset = plan["slots"].index(slot) % max(1, len(urls))
            selected = (urls[offset:] + urls[:offset])[: plan["maxEventsPerSlot"]]
            personal_count = 0
            for url in selected:
                response = fetch(url)
                body = json.loads(response.body)
                captured = now()
                picks = project_forecasts(body, url, captured)
                personal_count += len(picks)
                event = body.get("event") or {}
                earlier = next(
                    (e for e in j.events if e["kind"] == "FORECAST_VISIT" and e["url"] == url), None
                )
                if earlier and (
                    earlier["eventId"] != event.get("id")
                    or earlier["kickoff"] != event.get("starts_at")
                ):
                    j.append("EVENT_CHANGED", slot=slot, url=url, priorReceiptHash=earlier["hash"])
                    raise ValueError("event identity or schedule changed")
                j.append(
                    "FORECAST_VISIT",
                    slot=slot,
                    url=url,
                    observedAt=stamp(captured),
                    eventId=event.get("id"),
                    kickoff=event.get("starts_at"),
                    label=labels.get(url) or event.get("name") or event.get("id"),
                    responseSha256=sha256(response.body).hexdigest(),
                    withdrawnEvent=bool(body.get("restrictions", {}).get("name_withdrawn")),
                    eventStatus=event.get("status"),
                    picks=picks,
                )
            if not personal_count:
                j.append(
                    "CAMPAIGN_HALTED",
                    slot=slot,
                    reason="required_individual_attribution_missing",
                    decision="FAIL_AND_STOP",
                )
            j.append("SLOT_FINISHED", slot=slot, outcome="succeeded")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            j.append("SLOT_FINISHED", slot=slot, outcome="failed", errorType=type(exc).__name__)
            finishes = [e for e in j.events if e["kind"] == "SLOT_FINISHED"]
            if len(finishes) >= 2 and all(e["outcome"] == "failed" for e in finishes[-2:]):
                j.append(
                    "CAMPAIGN_HALTED",
                    slot=slot,
                    reason="two_consecutive_failures",
                    decision="FAIL_AND_REDESIGN",
                )
        finally:
            j.append("RUN_FINISHED", slot=slot)
        return "recorded"
    finally:
        lock.unlink()


def snapshot(directory: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    manifest, plan = validate_package(directory, execute=False, pins={})
    events = read_events(directory / "events.jsonl")
    visits = [e for e in events if e["kind"] == "FORECAST_VISIT"]
    seed: dict[str, Any] = {}
    if plan.get("seedFileSha256"):
        seed_raw = (directory / "seed.json").read_bytes()
        if sha256(seed_raw).hexdigest() != plan["seedFileSha256"]:
            raise ValueError("seed evidence fingerprint mismatch")
        seed = json.loads(seed_raw)
    picks: dict[str, dict[str, Any]] = {
        p["id"]: p
        for p in seed.get("picks", [])
        if p.get("attributionRole") == "individual_forecaster_declared"
    }
    fixtures: dict[str, dict[str, Any]] = {f["id"]: f for f in seed.get("fixtures", [])}
    for visit in visits:
        if visit.get("eventId") and visit.get("kickoff"):
            fixtures[visit["eventId"]] = dict(
                id=visit["eventId"], label=visit["label"], kickoff=visit["kickoff"]
            )
        for p in visit["picks"]:
            # Older observations remain immutable; a publisher or document byline
            # is not proof that a person made this particular prediction.
            if p.get("attributionRole") != "individual_forecaster_declared":
                continue
            if not instant(p["detectedAt"]) <= instant(p["observedAt"]) < instant(p["kickoff"]):
                raise ValueError("prematch evidence inconsistent")
            version = dict(
                observedAt=p["observedAt"],
                detectedAt=p["detectedAt"],
                publishedAt=p["publishedAt"],
                market=p["market"],
                selection=p["selection"],
                period=p["period"],
                line=p["line"],
                odds=p["declaredOdds"],
                sourceUrl=p["sourceUrl"],
            )
            if p["id"] not in picks:
                picks[p["id"]] = dict(
                    id=p["id"],
                    providerId=p["providerId"],
                    fixtureId=p["fixtureId"],
                    authorId=p["authorId"],
                    attributionBasis="declared",
                    attributionRole="individual_forecaster_declared",
                    firstSeenAt=p["observedAt"],
                    lastSeenAt=p["observedAt"],
                    versions=[version],
                )
            else:
                target = picks[p["id"]]
                target["lastSeenAt"] = p["observedAt"]
                previous = target["versions"][-1]
                if {k: v for k, v in previous.items() if k != "observedAt"} != {
                    k: v for k, v in version.items() if k != "observedAt"
                }:
                    target["versions"].append(version)
    tipsters = []
    historical_count = len(picks)
    unresolved_ids = {
        p["id"]
        for v in visits
        for p in v["picks"]
        if p.get("attributionRole") != "individual_forecaster_declared"
    }
    latest = {v["eventId"]: v for v in visits if v.get("eventId")}
    picks = {
        key: p
        for key, p in picks.items()
        if not latest.get(p["fixtureId"], {}).get("withdrawnEvent")
        and (
            latest.get(p["fixtureId"], {}).get("eventStatus") != "scheduled"
            or key in {i["id"] for i in latest[p["fixtureId"]]["picks"]}
        )
    }
    for author_id in sorted({p["authorId"] for p in picks.values()}):
        author_picks = [p for p in picks.values() if p["authorId"] == author_id]
        tipsters.append(
            dict(
                id=author_id,
                label="Attribution " + author_id[-12:],
                attributionBasis="declared",
                picks=len(author_picks),
                fixtureIds=sorted({p["fixtureId"] for p in author_picks}),
                firstSeenAt=min(p["firstSeenAt"] for p in author_picks),
                lastSeenAt=max(p["lastSeenAt"] for p in author_picks),
            )
        )
    starts = {e["slot"] for e in events if e["kind"] == "SLOT_STARTED"}
    finishes = {e["slot"]: e["outcome"] for e in events if e["kind"] == "SLOT_FINISHED"}
    slots = [
        dict(
            slot=s,
            fixtureId="",
            observedAt=None,
            picks=None,
            status="succeeded"
            if finishes.get(s) == "succeeded"
            else "failed"
            if s in finishes
            else "interrupted"
            if s in starts and current >= instant(s) + timedelta(seconds=plan["dueWindowSeconds"])
            else "running"
            if s in starts
            else "missed"
            if current >= instant(s) + timedelta(seconds=plan["dueWindowSeconds"])
            else "planned",
        )
        for s in plan["slots"]
    ]
    head = events[-1]["hash"] if events else None
    return dict(
        status="ok",
        schemaVersion="robin-tipsters-pilot-v1",
        generatedAt=stamp(current),
        phase="closed"
        if current >= instant(plan.get("captureUntil", plan["expiresAt"]))
        else "scheduled"
        if current < instant(plan["startsAt"])
        else "collecting",
        source="Forecast Record · mesures attribuées",
        missionId=plan["id"],
        startsAt=plan["startsAt"],
        expiresAt=plan["expiresAt"],
        requestsMax=manifest["external_effects"]["https_get_max"],
        plannedSlots=len(slots),
        plannedVisits=len(slots) * plan["maxEventsPerSlot"],
        journalPresent=bool(events),
        journalHead=head,
        counts={
            k: sum(s["status"] == k for s in slots)
            for k in ["planned", "running", "succeeded", "failed", "missed", "interrupted"]
        },
        requestCount=sum(e["kind"] == "REQUEST_RESERVED" for e in events),
        distinctPicks=len(picks),
        lastObservationAt=visits[-1]["observedAt"] if visits else seed.get("lastObservationAt"),
        technicalVerdict="PENDING"
        if current < instant(plan.get("captureUntil", plan["expiresAt"]))
        else "PASS_AND_HOLD"
        if picks
        and any(v["picks"] for v in visits)
        and all(s["status"] == "succeeded" for s in slots)
        else "PARTIAL",
        dossierVerdict="PARTIAL",
        fixtures=list(fixtures.values()),
        visits=slots,
        tipsters=tipsters,
        picks=list(picks.values()),
        evidence=dict(
            claimId="ENG.SOURCE_OBSERVATORY.RECURRING.20261118",
            planSha256=plan_hash(plan),
            journalHeadSha256=head,
            method="Individual provider attribution; detected and locally observed before kickoff; no identity certification",
        ),
        authorizationPresent=(directory / "authorization.json").exists(),
        unresolvedAttributions=len(unresolved_ids) + seed.get("unresolvedAttributions", 0),
        transportVerdict="PASS_AND_HOLD"
        if all(s["status"] == "succeeded" for s in slots) and slots
        else "PARTIAL",
        historicalPickCount=historical_count,
        withdrawnPickCount=historical_count - len(picks),
        seedEvidence=seed.get("evidence"),
        halted=any(e["kind"] == "CAMPAIGN_HALTED" for e in events),
    )
