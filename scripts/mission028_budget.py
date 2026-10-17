"""Atomic preflight allowance shared by mission028 collection and resumption."""
from datetime import UTC

from scripts.run_mission028 import PREFIX

DETAIL_CAP = 129750  # 200 calendars + 50 statuses leave at most 130000 calls/day.
TOTAL_CODE = "MISSION028_TOTAL_BUDGET_REACHED"
def reserve_status(store, now):
    if len(tuple(store.iter_keys(f"{PREFIX}/status-slots/"))) >= 925:
        raise RuntimeError(TOTAL_CODE)
    prefix = f"{PREFIX}/status-slots/{now.astimezone(UTC).date().isoformat()}/"
    for slot in range(49):  # Plus the original census proof: at most 50/day.
        if store.put_if_absent(f"{prefix}{slot:02d}", b'{}'):
            return
    raise RuntimeError("MISSION028_DAILY_BUDGET_REACHED")
