"""Prepare, run or inspect a separately authorized recurring tipster campaign."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from robin.source_observatory.connectors import Journal, canonical
from robin.source_observatory.recurring import (
    INDEX,
    PIN_PATHS,
    close_campaign,
    execute_slot,
    plan_hash,
    snapshot,
    validate_package,
)
from robin.source_observatory.recurring import (
    code_pins as current_code_pins,
)

ROOT = Path(__file__).resolve().parents[2]


def code_pins() -> dict[str, str]:
    return current_code_pins(ROOT)


def prepare(directory: Path, *, canary: bool) -> None:
    seed = snapshot(ROOT / "cockpit/.ci/tipsters-recurrence") if not canary else None
    if seed is not None and seed["transportVerdict"] != "PASS_AND_HOLD":
        raise ValueError("real two-slot transport canary not accepted")
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    start = now + timedelta(seconds=5) if canary else datetime(2026, 11, 19, 7, tzinfo=UTC)
    interval, count = (240, 2) if canary else (7200, 84)
    expiry = start + timedelta(seconds=interval * count)
    manifest_path = directory / "manifest.json"
    if manifest_path.exists() and canary:
        manifest = json.loads(manifest_path.read_bytes())
        expiry = datetime.fromisoformat(manifest["expires_at"])
    else:
        manifest = dict(
            mission_id="TIPSTERS-RECURRING-20261119",
            authorized_stages=["E1", "E2"],
            maximum_stage="E2",
            external_effects=dict(
                https_get_max=504,
                per_source_max=504,
                source_original_gets=0,
                scheduled_task="Robin-Tipsters-Recurring-V1-20261119",
                raw_payload_storage=0,
                api_football=0,
                purchases=0,
            ),
            compute_budget=dict(max_bytes=2000000),
            time_budget=dict(seconds=84 * 300),
            source_hash=sha256(
                canonical(dict(index=INDEX, max_events=3, schema="2.0"))
            ).hexdigest(),
            expires_at=expiry.isoformat(),
        )
        with manifest_path.open("xb") as stream:
            stream.write(canonical(manifest) + b"\n")
    plan = dict(
        schemaVersion="robin-recurring-plan-v1",
        id=manifest["mission_id"],
        sourceHash=manifest["source_hash"],
        startsAt=start.isoformat(),
        expiresAt=manifest["expires_at"],
        captureUntil=min(expiry, start + timedelta(seconds=interval * count)).isoformat(),
        intervalSeconds=interval,
        slots=[(start + timedelta(seconds=interval * n)).isoformat() for n in range(count)],
        maxEventsPerSlot=3,
        dueWindowSeconds=180,
        indexUrl=INDEX,
        qualificationRequired="individual_forecaster_declared",
        personalCollectionProven=bool(seed and seed["distinctPicks"]),
        codePins=code_pins(),
        authorizationText="J’autorise la tâche Windows temporaire Robin-Tipsters-Recurring-V1-20261119 sur A9_Mega, "
        "du 19 novembre 2026 à 08 h au 26 novembre à 08 h, heure de Paris, toutes les deux heures, "
        "limitée à 504 GET Forecast Record, trois fiches Ligue 1 par créneau, sans achat, sans API-Football, "
        "sans requête aux sources originales et avec stockage local structuré uniquement. "
        "L’absence de pronostic personnel admissible arrête la campagne sans relance. Le pilote J12 reste distinct.",
    )
    if not canary:
        raw_seed = canonical(seed) + b"\n"
        with (directory / "seed.json").open("xb") as stream:
            stream.write(raw_seed)
        plan["seedFileSha256"] = sha256(raw_seed).hexdigest()
    with (directory / "plan.json").open("xb") as stream:
        stream.write(canonical(plan) + b"\n")
    for path in PIN_PATHS:
        target = directory / "tooling" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / path).read_bytes().replace(b"\r\n", b"\n"))
    Journal(directory, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--authorize-reference")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--check-authority", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.prepare:
        prepare(directory, canary=args.canary)
    if args.authorize_reference:
        plan = json.loads((directory / "plan.json").read_bytes())
        authority = dict(
            decision="AUTHORIZED",
            decisionReference=args.authorize_reference,
            planSha256=plan_hash(plan),
            manifestSha256=sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        )
        with (directory / "authorization.json").open("xb") as stream:
            stream.write(canonical(authority) + b"\n")
    if args.run:
        execute_slot(directory, pins=code_pins())
    if args.check_authority:
        validate_package(directory, execute=True, pins=code_pins())
    if args.close:
        close_campaign(directory)
    print(json.dumps(snapshot(directory), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            json.dumps(
                dict(
                    status="unavailable",
                    message="Campagne récurrente indisponible.",
                    errorType=type(exc).__name__,
                )
            )
        )
        sys.exit(1)
