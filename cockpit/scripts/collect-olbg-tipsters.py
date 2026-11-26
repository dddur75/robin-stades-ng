"""One explicit legacy or opaque OLBG slot; no task or automatic authority."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from robin.source_observatory.olbg_campaign import run_olbg_slot, validate_olbg_campaign


def finite_context(directory: Path, approval: dict[str, str]):
    """Validate existing E1 and the single real finite E2 permission; no grant writer."""
    import os
    import sys
    from datetime import UTC, datetime
    from types import ModuleType

    from robin.source_observatory.olbg_opaque_campaign import (
        _read_bounded,
        source_guard,
        validate_campaign,
    )

    directory = directory.resolve(strict=True)
    root = Path(__file__).resolve().parents[2]
    if not directory.is_relative_to(root / "cockpit" / ".ci"):
        raise PermissionError("FINITE_DIRECTORY")
    plan, mission = validate_campaign(directory, approval)
    source_guard(directory, approval, datetime.now(UTC))

    def load(record, name):
        raw = _read_bounded(Path(record["path"]), 65536)
        if sha256(raw).hexdigest() != record["sha256"]:
            raise PermissionError("FINITE_CODE_PIN")
        module = ModuleType(name)
        module.__file__ = record["path"]
        # Only the manifest-pinned local module whose SHA-256 was verified above.
        exec(compile(raw, record["path"], "exec"), vars(module))  # nosec B102
        return module

    policy = load(plan["sourceRuntimeBinding"]["policy"], "finite_campaign_policy")
    if policy.POLICY_PROFILE != "FINITE_CAMPAIGN_PREAUTHORIZED_SLOTS_V3":
        raise PermissionError("FINITE_POLICY_PROFILE")
    sd = json.loads(_read_bounded(directory / "authorization.json", 32768))
    ledger = _read_bounded(Path(plan["sourceRuntimeBinding"]["ledgerPath"]), 16_000_000)
    end = policy.validate(sd, ledger, plan, mission, datetime.now(UTC))
    if Path(sys.executable).resolve() != Path(plan["python"]["path"]).resolve():
        raise PermissionError("FINITE_PYTHON")
    if (
        sha256(_read_bounded(Path(sys.executable), 2_000_000)).hexdigest()
        != plan["python"]["sha256"]
    ):
        raise PermissionError("FINITE_PYTHON_PIN")
    for k, v in {
        "STORAGE_PAUSED": "true",
        "P3_P4_PAUSED": "true",
        "PRODUCTION_LOCKED": "true",
        "REAL_BETS": "false",
        "NO_BET_DEFAULT": "true",
        "PROMOTION_LOCKED": "true",
        "SOCIAL_PUBLISHING_ENABLED": "false",
        "DEMO_MODE_ENABLED": "false",
        "API_FOOTBALL_CALLS_ALLOWED": "0",
    }.items():
        os.environ[k] = v
    return directory, plan, mission, sd, policy, end, load


def owned_opaque_slot(
    directory: Path, approval: dict[str, str], approval_path: Path, approval_sha: str
):
    """Consume one already authorized slot under the existing owned Windows Job."""
    import os
    import sys
    import time
    from datetime import UTC, datetime

    from robin.source_observatory.connectors import read_events

    root_start = time.monotonic()
    directory, plan, mission, sd, policy, end, load = finite_context(directory, approval)

    def save(name, value):
        with (directory / name).open("xb") as stream:
            stream.write(policy.canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def halt():
        if not (directory / "campaign-halt.json").exists():
            save(
                "campaign-halt.json",
                dict(status="HALTED", reason="CONTROL_OR_SOURCE_FAILURE", retry=False),
            )

    if (directory / "campaign-halt.json").exists():
        raise PermissionError("CAMPAIGN_HALTED")
    now = datetime.now(UTC)
    due = [s for s in plan["slots"] if 0 <= (now - policy.stamp(s)).total_seconds() <= 180]
    if len(due) != 1:
        return dict(state="not_due", requests=0)
    slot = due[0]
    token = sha256(slot.encode()).hexdigest()
    result_path = directory / ("slot-result-" + token + ".json")
    if result_path.exists():
        value = json.loads(result_path.read_bytes())
        if value.get("state") != "succeeded":
            halt()
            raise PermissionError("CLOSED_SLOT_FAILURE")
        return dict(state="already_finished", requests=0)
    lock = directory / ".execution.lock"
    with lock.open("x", encoding="utf8") as stream:
        stream.write(slot)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        for fixed in plan["slots"]:
            old = sha256(fixed.encode()).hexdigest()
            if (directory / ("slot-job-" + old + ".json")).exists() and not (
                directory / ("slot-result-" + old + ".json")
            ).exists():
                raise PermissionError("UNFINISHED_PRIOR_JOB")
        if (directory / "campaign.lock").exists():
            raise PermissionError("UNFINISHED_SOURCE_RUN")
        origin = time.monotonic()
        launch = dict(
            slot=slot,
            missionId=plan["id"],
            parentPID=os.getpid(),
            originMonotonic=origin,
            campaignAuthorizationSHA256=approval["authorizationSHA256"],
            startedAtUTC=datetime.now(UTC).isoformat(),
            executionOnly=True,
        )
        policy.validate(
            sd,
            Path(plan["sourceRuntimeBinding"]["ledgerPath"]).read_bytes(),
            plan,
            mission,
            datetime.now(UTC),
            slot_run=launch,
        )
        save("slot-job-" + token + ".json", launch)  # reservation, never a Council grant/opinion
        owner = load(plan["sourceRuntimeBinding"]["outer"], "finite_owned_job")
        argv = [
            sys.executable,
            "-S",
            "-X",
            "utf8",
            "-B",
            str(Path(__file__).resolve()),
            "--directory",
            str(directory),
            "--opaque",
            "--approval",
            str(approval_path.resolve()),
            "--approval-sha",
            approval_sha,
            "--execute",
        ]
        job = owner.hard_job(argv, started=origin)
        if time.monotonic() - root_start >= 70:
            raise TimeoutError("ROOT_DEADLINE")
        events = read_events(directory / "events.jsonl")
        accepted = [
            e for e in events if e["kind"] == "PUBLIC_COLLECTION_ACCEPTED" and e.get("slot") == slot
        ]
        finished = [
            e for e in events if e["kind"] == "PUBLIC_SLOT_FINISHED" and e.get("slot") == slot
        ]
        passed = (
            job["exit"] == 0
            and job["timedOut"] is False
            and job["subtreeKillConfirmed"] is True
            and len(accepted) == len(finished) == 1
        )
        if passed:
            item = accepted[0]
            file = directory / item["observationFile"]
            passed = (
                file.parent == directory
                and file.name.startswith("observations-")
                and file.stat().st_size <= 131072
                and sha256(file.read_bytes()).hexdigest() == item["observationSha256"]
            )
        pending = [
            e for e in events if e["kind"] == "PUBLIC_FACTS_RETAINED" and e.get("slot") == slot
        ]
        result = dict(
            state="succeeded" if passed else "halted",
            slot=slot,
            job=job,
            pendingCount=pending[0]["count"] if len(pending) == 1 else None,
            pendingSHA256=pending[0]["observationSha256"] if len(pending) == 1 else None,
            picks=accepted[0]["count"] if passed else None,
            observationSHA256=accepted[0]["observationSha256"] if passed else None,
            sourceReady=False,
            APP=0,
            retry=False,
            RootElapsedSeconds=time.monotonic() - root_start,
        )
        save("slot-result-" + token + ".json", result)
        if not passed:
            halt()
        return result
    except Exception:
        halt()
        raise
    finally:
        lock.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--opaque", action="store_true")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--approval-sha")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--owned", action="store_true")
    parser.add_argument("--campaign-preflight", action="store_true")
    args = parser.parse_args(argv)
    if not args.opaque:
        if (
            args.approval is not None
            or args.approval_sha is not None
            or args.execute
            or args.owned
            or args.campaign_preflight
        ):
            parser.error("Opaque options require --opaque")
        if args.validate_only:
            validate_olbg_campaign(args.directory)
            result = dict(state="validated", requests=0)
        else:
            result = run_olbg_slot(args.directory)
    else:
        if args.approval is None or args.approval_sha is None:
            parser.error("Opaque mode requires --approval and --approval-sha")
        if args.execute and args.validate_only:
            parser.error("Choose --execute or --validate-only")
        with args.approval.open("rb") as stream:
            raw = stream.read(32769)
        if not 0 < len(raw) <= 32768 or sha256(raw).hexdigest() != args.approval_sha:
            raise PermissionError("CAMPAIGN_APPROVAL_PIN")
        from robin.source_observatory.olbg_opaque_campaign import (
            run_opaque_slot,
            validate_campaign,
        )

        approval = json.loads(raw)
        validate_campaign(args.directory, approval)
        if (
            args.owned
            and (not args.execute or args.campaign_preflight)
            or args.campaign_preflight
            and (args.execute or args.validate_only)
        ):
            parser.error("Owned execution and campaign preflight are separate opaque actions")
        if args.campaign_preflight:
            finite_context(args.directory, approval)
            result = dict(state="CAMPAIGN_PREFLIGHT", requests=0)
        elif args.owned:
            try:
                result = owned_opaque_slot(
                    args.directory, approval, args.approval, args.approval_sha
                )
            except Exception:
                print(json.dumps(dict(state="PARTIAL_FAIL_CLOSED", requests=None, retry=False)))
                return 1
            if result["state"] == "halted":
                print(json.dumps(result))
                return 1
        else:
            result = (
                run_opaque_slot(args.directory, approval=approval)
                if args.execute
                else dict(state="VALIDATED_ONLY", requests=0)
            )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
