"""Read closed E2 facts; native authority remains false until separately verified."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from robin.source_observatory.notbetting_recurring import read_view

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--plan-sha256", required=True)
a = p.parse_args()
try:
    value = read_view(Path(__file__).resolve().parents[2], a.directory,
                      a.plan_sha256, now=datetime.now(UTC))
    print(json.dumps(value, ensure_ascii=False))
    if value.get("state") == "unavailable":
        raise SystemExit(2)
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    print(json.dumps(dict(state="unavailable", active=False, recurringAuthority=False)))
    raise SystemExit(2) from None
