"""Read immutable recurring/canary evidence; never authorize or perform network."""

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from robin.source_observatory.recurring import (
    code_pins,
    instant,
    plan_hash,
    snapshot,
    validate_package,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--campaign-directory", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign_directory
    authorized = (campaign / "authorization.json").exists()
    state = "preparing"
    if (campaign / "plan.json").exists():
        try:
            _, checked = validate_package(
                campaign, execute=authorized, pins=code_pins(Path(__file__).resolve().parents[2])
            )
            if checked["codePins"] != code_pins(Path(__file__).resolve().parents[2]):
                raise ValueError("stale code")
            state = (
                "expired"
                if datetime.now(UTC) >= instant(checked["expiresAt"])
                else "authorized"
                if authorized
                else "awaiting_authorization"
            )
        except (OSError, ValueError, KeyError, TypeError):
            state = "invalid_package"
        authorized = authorized and state in {"authorized", "expired"}
    active = campaign if authorized else args.directory
    view = snapshot(active)
    view["qualificationVerdict"] = snapshot(args.directory)["technicalVerdict"]
    if (campaign / "plan.json").exists():
        plan = json.loads((campaign / "plan.json").read_bytes())
        manifest = json.loads((campaign / "manifest.json").read_bytes())
        view["campaign"] = dict(
            state=state,
            personalCollectionProven=plan.get("personalCollectionProven", False),
            id=plan["id"],
            startsAt=plan["startsAt"],
            expiresAt=plan["expiresAt"],
            slots=len(plan["slots"]),
            intervalMinutes=plan["intervalSeconds"] // 60,
            requestsMax=manifest["external_effects"]["https_get_max"],
            taskName=manifest["external_effects"]["scheduled_task"],
            authorizationText=plan["authorizationText"]
            if state == "awaiting_authorization"
            else None,
            manifestSha256=sha256((campaign / "manifest.json").read_bytes()).hexdigest(),
            planSha256=plan_hash(plan),
        )
    else:
        view["campaign"] = dict(state="preparing")
    print(json.dumps(view, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                dict(
                    status="unavailable",
                    message="Les preuves de récurrence ne sont pas disponibles.",
                )
            )
        )
