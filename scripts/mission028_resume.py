"""Resume only the frozen mission 028, with durable terminal and stop markers."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from robin.historical_deep.adapters import R2ObjectStore
from scripts.mission028_budget import DETAIL_CAP, TOTAL_CODE
from scripts.run_mission028 import PREFIX

WORKERS = 16
BUDGET_CODES = {TOTAL_CODE, "MISSION028_DAILY_BUDGET_REACHED", "MISSION028_RESERVE_REACHED"}


def checkpoint(store, receipt, now, revision, deadline=None):
    if store is None:
        return
    if receipt.get("reason_code") == "MISSION028_TIME_SLICE_ENDED":
        return  # A completed time slice never marks the worker terminal.
    if "reason_class" not in receipt:
        if "family" not in receipt:
            return  # A successful preflight is not a completed family.
        key = f"{PREFIX}/terminal/{receipt['family']}/worker={receipt['worker']}.json"
    elif receipt.get("reason_code") == TOTAL_CODE:
        key = f"{PREFIX}/limits/total.json"
    elif receipt["reason_class"] in ("QuotaExhaustedError", "QuotaStatusExpiredError") or receipt.get("reason_code") in BUDGET_CODES:
        key = f"{PREFIX}/limits/{now.astimezone(UTC).date().isoformat()}.json"
    else:
        key = f"{PREFIX}/pause/{revision}/{receipt.get('family', 'preflight')}-{receipt.get('worker', 'all')}.json"
    store.put_if_absent(key, (json.dumps(receipt, sort_keys=True) + "\n").encode())


def choose(store, now, revision, cycle):
    if not 0 <= cycle <= 20:
        raise ValueError("MISSION028_CYCLE_INVALID")
    family = next((f for f in ("lineups", "statistics")
        if any(store.get_object(f"{PREFIX}/terminal/{f}/worker={w}.json") is None for w in range(WORKERS))), None)
    if family is None:
        return "DONE", "none"  # Collection exhausted; coverage still needs review.
    if any(store.iter_keys(f"{PREFIX}/pause/{revision}/")):
        return "PAUSED", "none"
    day = now.astimezone(UTC).date().isoformat()
    if store.get_object(f"{PREFIX}/limits/total.json") is not None:
        return "BUDGET", "none"
    if store.get_object(f"{PREFIX}/limits/{day}.json") is not None or len(tuple(store.iter_keys(f"{PREFIX}/daily/{day}/"))) >= DETAIL_CAP:
        return "BUDGET", "none"
    return ("HOLD", "none") if cycle == 20 else ("READY", family)


def main():
    from scripts.run_mission028_details import load_mapping

    load_mapping()  # Validate hashes, source rows and seasons before storage access.
    cycle = int(os.environ.get("MISSION028_CYCLE", "0"))
    state, family = choose(R2ObjectStore(os.environ), datetime.now(UTC), os.environ["GITHUB_SHA"], cycle)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"state={state}\nfamily={family}\n")
    print(json.dumps(dict(state=state, family=family, cycle=cycle)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
