"""Validate by default. Explicit execution still requires exact Council authority."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from robin.source_observatory.notbetting_recurring_v4 import (
    SLOTS,
    execute_pass,
    validate_package,
)
from robin.source_observatory.recurring import instant

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--plan-sha256", required=True)
p.add_argument("--slot", default="auto")
p.add_argument("--execute", action="store_true")
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
try:
    packet = validate_package(root, a.directory, a.plan_sha256, now=datetime.now(UTC))
    if a.execute:
        slot = a.slot
        if slot == "auto":
            matches = [
                s
                for s in SLOTS
                if instant(s) <= datetime.now(UTC) < instant(s) + timedelta(seconds=120)
            ]
            if len(matches) != 1:
                raise ValueError("no current slot; catch-up forbidden")
            slot = matches[0]
        result = execute_pass(root, a.directory, a.plan_sha256, slot)
        print(json.dumps(result))
        raise SystemExit(
            0 if result["state"] in {"completed", "duplicate", "canary_pending_review"} else 2
        )
    print(json.dumps(dict(state="validated_only", active=False)))
except (OSError, ValueError, KeyError, TypeError):
    print(json.dumps(dict(state="refused", active=False)))
    raise SystemExit(2) from None
