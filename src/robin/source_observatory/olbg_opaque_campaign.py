"""Private proposal. The native transport remains unavailable until separate binding."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

from robin.source_observatory.connectors import Journal, Response, canonical, public_get
from robin.source_observatory.olbg import extract_profile
from robin.source_observatory.olbg_campaign import rules_digest
from robin.source_observatory.olbg_robots_policy import (
    REASONS as ROBOTS_REASON_CODES,
)
from robin.source_observatory.olbg_robots_policy import (
    RobotsPolicyError,
)
from robin.source_observatory.olbg_robots_policy import (
    policy as olbg_robots_policy,
)
from robin.source_observatory.opaque_choices import build_opaque_choices
from robin.source_observatory.recurring import instant

APPROVAL: dict[str, str] | None = None
ENDPOINT = "https://www.olbg.com/tipsters/tips/648433"
SCHEMA = "robin-olbg-opaque-campaign-batch-v1"


def _profile_id(plan: dict[str, Any]) -> int:
    profile_id = plan.get("profileId", 648433)
    if (
        type(profile_id) is not int
        or profile_id <= 0
        or plan.get("endpoint") != f"https://www.olbg.com/tipsters/tips/{profile_id}"
    ):
        raise ValueError("CAMPAIGN_PROFILE_SCOPE")
    return profile_id


STOP_CODES = {
    "ROBOTS_BOOTSTRAP_SCOPE": "ROBOTS_BOOTSTRAP_SCOPE",
    "robots denied": "ROBOTS_POLICY_DENIED",
    "slot deadline exhausted": "SLOT_DEADLINE_EXHAUSTED",
    "slot deadline exceeded": "SLOT_DEADLINE_EXCEEDED",
    "source access refused": "SOURCE_HTTP_REFUSED",
    "terms changed": "TERMS_CHANGED",
    "no admissible personal pick": "ZERO_ELIGIBLE",
    "PROFILE_CAPTURE_ABSENT": "PROFILE_CAPTURE_ABSENT",
    "OPAQUE_BATCH_CAP": "OPAQUE_BATCH_CAP",
    "SYNTH_TRANSPORT_REQUIRED": "SYNTH_TRANSPORT_REQUIRED",
    "unsupported robots user-agent": "ROBOTS_POLICY_UNSUPPORTED_AGENT",
    "unsupported robots delay": "ROBOTS_POLICY_UNSUPPORTED_DELAY",
    "ROBOTS_BODY_TYPE_OR_CAP": "ROBOTS_BODY_TYPE_OR_CAP",
    "ROBOTS_UTF8_INVALID": "ROBOTS_UTF8_INVALID",
    "ROBOTS_CONTROL_INVALID": "ROBOTS_CONTROL_INVALID",
    "ROBOTS_ACTIVE_HTML": "ROBOTS_ACTIVE_HTML",
}


def closed_stop_reason(error: Exception) -> str:
    """Compare only known local messages; never echo exception arguments."""
    if type(error) is RobotsPolicyError:
        reason = error.reason
        if type(reason) is str and reason in ROBOTS_REASON_CODES:
            return "ROBOTS_POLICY_" + reason
        return "ROBOTS_POLICY_UNPROVEN"
    if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str:
        return STOP_CODES.get(error.args[0], "BUSINESS_UNPROVEN")
    return "BUSINESS_UNPROVEN"


def robots_rules_document(body: bytes) -> str:
    """RFC9309 comment handling only; this is not a complete REP validator."""
    if type(body) is not bytes or len(body) > 65536:
        raise ValueError("ROBOTS_BODY_TYPE_OR_CAP")
    try:
        text = body.decode("utf-8-sig", "strict")
    except UnicodeDecodeError:
        raise ValueError("ROBOTS_UTF8_INVALID") from None
    if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise ValueError("ROBOTS_CONTROL_INVALID")
    # Preserve active directives; ignore only the RFC # comment suffix of each line.
    rules = "\n".join(line.partition("#")[0] for line in re.split(r"\r\n|\r|\n", text))
    if "<" in rules:
        raise ValueError("ROBOTS_ACTIVE_HTML")
    return rules


def denied_get(*_args: Any, **_kwargs: Any) -> Response:
    raise PermissionError("SOURCE_DEFAULT_DENY")


def _read_bounded(path: Path, cap: int) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    if not 0 < len(raw) <= cap:
        raise ValueError("CAMPAIGN_SIZE")
    return raw


def validate_campaign(
    directory: Path, approval: dict[str, str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if approval is None:
        raise PermissionError("CAMPAIGN_APPROVAL_REQUIRED")
    plan_raw = _read_bounded(directory / "plan.json", 65536)
    mf_raw = _read_bounded(directory / "manifest.json", 16384)
    if len(plan_raw) > 65536 or len(mf_raw) > 16384:
        raise ValueError("CAMPAIGN_SIZE")
    plan, mission = json.loads(plan_raw), json.loads(mf_raw)
    if (
        sha256(plan_raw).hexdigest() != approval["planSHA256"]
        or sha256(mf_raw).hexdigest() != approval["manifestSHA256"]
    ):
        raise ValueError("CAMPAIGN_PIN")
    required = {
        "mission_id",
        "authorized_stages",
        "maximum_stage",
        "external_effects",
        "compute_budget",
        "time_budget",
        "source_hash",
        "expires_at",
    }
    if (
        set(mission) != required
        or mission["maximum_stage"] != "E2"
        or mission["authorized_stages"] != ["E1", "E2"]
        or mission["source_hash"] != sha256(canonical(plan)).hexdigest()
        or mission["mission_id"] != plan["id"]
    ):
        raise ValueError("CAMPAIGN_TUPLE")
    slots = plan["slots"]
    if (
        not isinstance(slots, list)
        or not 1 <= len(slots) <= 12
        or len(set(slots)) != len(slots)
        or slots != sorted(slots)
        or any(instant(s) >= instant(mission["expires_at"]) for s in slots)
    ):
        raise ValueError("CAMPAIGN_SLOTS")
    _profile_id(plan)
    if (
        plan["robotsUrl"] != "https://www.olbg.com/robots.txt"
        or plan["termsUrl"] != "https://www.olbg.com/use"
        or plan["zeroEligiblePolicy"] != "HALT"
        or not 1 <= len(plan["fixtures"]) <= 32
        or plan["calendarSha256"] != sha256(canonical(plan["fixtures"])).hexdigest()
        or mission["external_effects"]
        != {"https_get_max": len(slots) * 3, "per_source_max": len(slots) * 3}
    ):
        raise ValueError("CAMPAIGN_SCOPE")
    for key in ("parserSha256", "builderSha256", "rulesSha256"):
        if re.fullmatch("[a-f0-9]{64}", plan[key]) is None:
            raise ValueError("CAMPAIGN_CODE_PIN")
    # Future binding owns these absolute code paths; never resolve provider imports.
    for value in plan["codePins"]:
        raw = Path(value["path"]).read_bytes()
        if sha256(raw).hexdigest() != value["sha256"]:
            raise ValueError("CAMPAIGN_CODE_CHANGED")
    parser = next(x for x in plan["codePins"] if x["role"] == "parser")
    builder = next(x for x in plan["codePins"] if x["role"] == "builder")
    if parser["sha256"] != plan["parserSha256"] or builder["sha256"] != plan["builderSha256"]:
        raise ValueError("CAMPAIGN_PARSER_BINDING")
    for function, role in ((extract_profile, "parser"), (build_opaque_choices, "builder")):
        binding = next(x for x in plan["codePins"] if x["role"] == role)
        if Path(binding["path"]).resolve() != Path(function.__code__.co_filename).resolve():
            raise ValueError("LOADED_CODE_ORIGIN")
    return plan, mission


def project_profile(
    facts: dict[str, Any], plan: dict[str, Any], observed: datetime, response_sha: str
) -> dict[str, Any]:
    profile_id = _profile_id(plan)
    if type(facts.get("authorId")) is not int or facts["authorId"] != profile_id:
        raise ValueError("CAMPAIGN_PERSONAL_AUTHOR_MISMATCH")
    if len(facts["records"]) > 20:
        raise ValueError("OPAQUE_RECORD_CAP")
    source = {
        "profiles": [
            {
                "facts": facts,
                "request": {
                    "url": plan["endpoint"],
                    "observedAt": observed.isoformat(),
                    "responseSha256": response_sha,
                },
            }
        ],
        "fixtures": plan["fixtures"],
        "calendarSha256": plan["calendarSha256"],
    }
    accepted: list[int] = []
    for native in facts["records"]:
        tid = native.get("tipid")
        if type(tid) is not int or tid in accepted:
            raise ValueError("OPAQUE_TIP_ID")
        try:
            build_opaque_choices(source, [tid], parser_sha=plan["parserSha256"])
        except ValueError:
            continue
        accepted.append(tid)
    picks = build_opaque_choices(source, accepted, parser_sha=plan["parserSha256"])
    if not picks:
        raise ValueError("ZERO_ELIGIBLE_HALT")
    return {
        "schemaVersion": SCHEMA,
        "missionId": plan["id"],
        "claimId": plan["claimId"],
        "source": source,
        "acceptedSourceTipIds": accepted,
        "picks": picks,
        "parserSha256": plan["parserSha256"],
        "builderSha256": plan["builderSha256"],
        "calendarSha256": plan["calendarSha256"],
        "sourceReady": False,
        "applicationAdmissions": 0,
        "recurrence": True,
    }


def _save_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def source_guard(directory: Path, approval: dict[str, str], now: datetime) -> None:
    """Campaign approval is the explicit finite SOURCE grant, never a per-batch grant."""
    plan, mission = validate_campaign(directory, approval)
    raw = _read_bounded(directory / "authorization.json", 32768)
    if len(raw) > 32768 or sha256(raw).hexdigest() != approval["authorizationSHA256"]:
        raise PermissionError("SOURCE_APPROVAL_PIN")
    grant = json.loads(raw)
    if (
        grant.get("planSha256") != sha256(canonical(plan)).hexdigest()
        or grant.get("manifestSha256") != sha256(canonical(mission)).hexdigest()
        or grant.get("ownerMessage") != plan.get("ownerMessage")
        or not isinstance(plan.get("ownerMessage"), str)
        or plan.get("scope") != "LOCAL_PERSONAL_NONCOMMERCIAL"
        or plan.get("sourceId") != "SRC_014"
        or grant.get("keys") != ["C0", "C1", "C3", "C4"]
        or grant.get("sourceAllowed") is not True
        or grant.get("rulesSha256") != plan["rulesSha256"]
        or not instant(grant["authorizedAt"]) <= now < instant(grant["expiresAt"])
        or now >= instant(mission["expires_at"])
        or instant(grant["termsApprovedAt"]) > now
    ):
        raise PermissionError("SOURCE_AUTHORITY")
    # The real legacy transport is pinned and callable, not an implementation stub.
    transport = next(x for x in plan["codePins"] if x["role"] == "transport")
    if (
        Path(transport["path"]).resolve() != Path(public_get.__code__.co_filename).resolve()
        or transport["sha256"] != approval["transportSHA256"]
    ):
        raise PermissionError("SOURCE_TRANSPORT_PIN")


def bind_source_runtime(
    directory: Path,
    plan: dict[str, Any],
    mission: dict[str, Any],
    approval: dict[str, str],
) -> Any:
    """Mandatory future ROOT SOURCE binding; no legacy-grant-only activation.

    Its pinned bind_source must validate the current real policy/live ledger,
    effective full-80 window and framing guards for every native effect.
    No implementation or proof of that SOURCE binding is supplied here.
    """
    record = plan.get("sourceRuntime")
    if (
        type(record) is not dict
        or set(record) != {"path", "sha256"}
        or record.get("sha256") != approval.get("sourceRuntimeSHA256")
        or not isinstance(record.get("sha256"), str)
        or re.fullmatch("[a-f0-9]{64}", record["sha256"]) is None
    ):
        raise PermissionError("CURRENT_SOURCE_RUNTIME_REQUIRED")
    raw = _read_bounded(Path(record["path"]), 65536)
    if sha256(raw).hexdigest() != record["sha256"]:
        raise PermissionError("CURRENT_SOURCE_RUNTIME_PIN")
    module = ModuleType("olbg_pinned_current_source_runtime")
    module.__file__ = record["path"]
    # Execute only approved local runtime bytes SHA-256 checked above.
    exec(compile(raw, record["path"], "exec"), vars(module))  # nosec B102
    runtime = module.bind_source(
        directory=directory,
        plan=plan,
        mission=mission,
        approval=approval,
        legacy_get=public_get,
    )
    if (
        not callable(getattr(runtime, "guard", None))
        or not callable(getattr(runtime, "get", None))
        or runtime.guard("source-runtime-bound") is not True
    ):
        raise PermissionError("CURRENT_SOURCE_RUNTIME_REFUSED")
    return runtime


def run_opaque_slot(
    directory: Path,
    *,
    approval: dict[str, str] | None = None,
    synthetic_only: bool = False,
    now: datetime | None = None,
    get: Callable[..., Response] = public_get,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    plan, mission = validate_campaign(directory, approval)
    if approval is None:
        raise PermissionError("CAMPAIGN_APPROVAL_REQUIRED")
    native_runtime = None
    if synthetic_only is not True:
        source_guard(directory, approval, clock())
        native_runtime = bind_source_runtime(directory, plan, mission, approval)
        if get is not public_get:
            raise PermissionError("UNAPPROVED_NATIVE_TRANSPORT")
        get = native_runtime.get
    wall_start, mono_start = clock(), time.monotonic()

    def guard() -> None:
        observed = clock()
        if (
            observed < wall_start
            or observed >= instant(mission["expires_at"])
            or time.monotonic() - mono_start >= 210
        ):
            raise TimeoutError("CAMPAIGN_DEADLINE")
        if synthetic_only is not True:
            source_guard(directory, approval, observed)
            if native_runtime is None or native_runtime.guard("full-source-campaign") is not True:
                raise PermissionError("CURRENT_SOURCE_RUNTIME_REFUSED")

    guard()
    current = now or clock()
    if current >= instant(mission["expires_at"]):
        return dict(state="expired", requests=0)
    due = [s for s in plan["slots"] if 0 <= (current - instant(s)).total_seconds() <= 180]
    if len(due) != 1:
        return dict(state="not_due", requests=0)
    slot = due[0]
    lock = directory / "campaign.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(slot)
    try:
        journal = Journal(directory, mission, now=clock)
        if any(e["kind"] == "CAMPAIGN_HALTED" for e in journal.events):
            return dict(state="halted", requests=0)
        if any(e["kind"] == "PUBLIC_SLOT_STARTED" and e["slot"] == slot for e in journal.events):
            return dict(state="already_started", requests=0)
        if sum(e["kind"] == "RUN_STARTED" for e in journal.events) != sum(
            e["kind"] == "RUN_FINISHED" for e in journal.events
        ):
            journal.append("CAMPAIGN_HALTED", slot=slot, reason="unfinished prior run")
            return dict(state="halted", requests=0)
        journal.append("RUN_STARTED", slot=slot)
        journal.append("PUBLIC_SLOT_STARTED", slot=slot)
        before = sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events)
        deadline = current + timedelta(seconds=210)
        rules = ""
        robots_state = "UNOBSERVED"
        picks = []
        snapshot = None
        try:
            for url in [plan["robotsUrl"], plan["termsUrl"], plan["endpoint"]]:
                if robots_state == "UNOBSERVED":
                    if url != plan["robotsUrl"]:
                        raise ValueError("ROBOTS_BOOTSTRAP_SCOPE")
                    allowed, delay = True, 0.0
                elif robots_state == "ABSENT_404":
                    allowed, delay = True, 0.0
                elif robots_state == "PRESENT_200":
                    allowed, delay = olbg_robots_policy(
                        rules.encode("utf-8"),
                        url,
                        "RobinSourceObservatory",
                        max_delay_seconds=60,
                        max_bytes=65536,
                    )
                else:
                    raise ValueError("ROBOTS_BOOTSTRAP_SCOPE")
                if not allowed or delay > 30:
                    raise ValueError("robots denied")
                remaining = min(journal.remaining_seconds(), (deadline - clock()).total_seconds())
                if remaining <= max(2, delay) + 1:
                    raise ValueError("slot deadline exhausted")
                sleep(max(2, delay))
                timeout = min(
                    12.0, journal.remaining_seconds(), (deadline - clock()).total_seconds()
                )
                if timeout <= 0:
                    raise ValueError("slot deadline exhausted")
                guard()
                reservation = journal.reserve("SRC_014", url)
                guard()
                if synthetic_only is True and get is public_get:
                    raise PermissionError("SYNTH_TRANSPORT_REQUIRED")
                response = get(url, timeout=timeout)
                guard()
                observed = clock()
                if observed >= deadline:
                    raise ValueError("slot deadline exceeded")
                digest = sha256(response.body).hexdigest()
                journal.append(
                    "REQUEST_FINISHED",
                    sourceId="SRC_014",
                    url=url,
                    reservation=reservation,
                    httpStatus=response.status,
                    responseSha256=digest,
                )
                if url == plan["robotsUrl"] and response.status == 404:
                    journal.append(
                        "ROBOTS_ABSENCE_OBSERVED", policy="RFC9309-2.3.1.3", httpStatus=404
                    )
                    robots_state = "ABSENT_404"
                    continue
                if response.status != 200:
                    raise ValueError("source access refused")
                if url == plan["robotsUrl"]:
                    rules = robots_rules_document(response.body)
                    robots_state = "PRESENT_200"
                elif url == plan["termsUrl"]:
                    if rules_digest(response.body) != plan["rulesSha256"]:
                        raise ValueError("terms changed")
                else:
                    facts = extract_profile(response.body, _profile_id(plan))
                    native_count = len(facts["records"])
                    facts = dict(facts, records=facts["records"][:20])
                    pending = dict(
                        schemaVersion="OLBG_UNADMITTED_FACTS_V1",
                        missionId=plan["id"],
                        slot=slot,
                        observedAt=observed.isoformat(),
                        sourceURL=url,
                        responseSHA256=digest,
                        parserSHA256=plan["parserSha256"],
                        sourceRecordCount=native_count,
                        omittedRecords=native_count - len(facts["records"]),
                        facts=facts,
                        applicationAdmissions=0,
                        sourceReady=False,
                    )
                    pending_raw = canonical(pending) + b"\n"
                    if len(pending_raw) > 131072:
                        raise ValueError("OPAQUE_BATCH_CAP")
                    pending_name = "unadmitted-facts-" + sha256(pending_raw).hexdigest() + ".json"
                    guard()
                    _save_exclusive(directory / pending_name, pending_raw)
                    guard()
                    journal.append(
                        "PUBLIC_FACTS_RETAINED",
                        slot=slot,
                        observationFile=pending_name,
                        observationSha256=sha256(pending_raw).hexdigest(),
                        count=len(facts["records"]),
                        sourceRecordCount=native_count,
                        omittedRecords=native_count - len(facts["records"]),
                    )
                    snapshot = project_profile(facts, plan, observed, digest)
                    picks = snapshot["picks"]
                    journal.append(
                        "PUBLIC_PICKS_QUALIFIED",
                        sourceId="SRC_014",
                        responseSha256=digest,
                        parserSha256=plan["parserSha256"],
                        calendarSha256=plan["calendarSha256"],
                        count=len(picks),
                    )
            if not picks:
                raise ValueError("no admissible personal pick")
            if snapshot is None:
                raise ValueError("PROFILE_CAPTURE_ABSENT")
            data = snapshot
            raw = canonical(data) + b"\n"
            digest = sha256(raw).hexdigest()
            filename = "observations-" + digest + ".json"
            if len(raw) > 131072:
                raise ValueError("OPAQUE_BATCH_CAP")
            guard()
            _save_exclusive(directory / filename, raw)
            guard()
            guard()
            journal.append(
                "PUBLIC_COLLECTION_ACCEPTED",
                observationFile=filename,
                observationSha256=digest,
                count=len(picks),
                authors=len({p["authorId"] for p in picks}),
                slot=slot,
            )
            guard()
            journal.append("PUBLIC_SLOT_FINISHED", slot=slot, count=len(picks))
            guard()
            return dict(
                state="succeeded",
                picks=len(picks),
                requests=sum(e["kind"] == "REQUEST_RESERVED" for e in journal.events) - before,
            )
        except Exception as exc:
            journal.append(
                "CAMPAIGN_HALTED",
                slot=slot,
                reason=type(exc).__name__,
                reasonCode=closed_stop_reason(exc),
            )
            raise
        finally:
            journal.append("RUN_FINISHED", slot=slot)
            guard()
    finally:
        lock.unlink()
