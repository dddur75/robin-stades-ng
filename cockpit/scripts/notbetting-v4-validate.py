"""Read-only package validation; registration requires the four-role canary receipt."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from robin.source_observatory.notbetting_recurring_v4 import validate_package

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--plan-sha256", required=True)
p.add_argument("--registration", action="store_true")
a = p.parse_args()
try:
    now = datetime.now(UTC)
    packet = validate_package(
        Path(__file__).resolve().parents[2],
        a.directory,
        a.plan_sha256,
        now=now,
        registration=a.registration,
    )
    plan = packet["plan"]
    if a.registration and now >= datetime.fromisoformat(plan["slots"][0].replace("Z", "+00:00")):
        raise ValueError("registration window closed")
    print(
        json.dumps(
            dict(
                state="validated",
                active=False,
                taskName=plan["taskName"],
                slots=plan["slots"],
                expiresAt=plan["expiresAt"],
                planSha256=a.plan_sha256,
            )
        )
    )
except (OSError, ValueError, KeyError, TypeError):
    print(json.dumps(dict(state="refused", active=False)))
    raise SystemExit(2) from None
