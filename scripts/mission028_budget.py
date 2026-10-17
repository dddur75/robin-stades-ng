"""Atomic preflight allowance shared by mission028 collection and resumption."""
import sqlite3
from datetime import UTC

from scripts.run_mission028 import PREFIX

DETAIL_CAP = 129750  # 200 calendars + 50 statuses leave at most 130000 calls/day.
TOTAL_CODE = "MISSION028_TOTAL_BUDGET_REACHED"
class RunBudget:
    """Local shared allowance; every debit must precede its durable day slot."""
    def __init__(self, path, run_id, store, now, remaining):
        self.connection, self.run_id = sqlite3.connect(path, timeout=120), run_id
        self.connection.execute('CREATE TABLE IF NOT EXISTS budget (run TEXT PRIMARY KEY, remaining INTEGER, reason TEXT)')
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            if self.connection.execute('SELECT 1 FROM budget WHERE run=?', (run_id,)).fetchone() is None:
                keys = tuple(store.iter_keys(f'{PREFIX}/daily/'))  # Once per run, before any call.
                total = 122200 - 200 - 926 - len(keys)
                provider = remaining - 5000 - sum(k.startswith(f'{PREFIX}/daily/{now.astimezone(UTC).date()}/') for k in keys)
                self.connection.execute('INSERT INTO budget VALUES (?, ?, ?)', (run_id, min(total, provider),
                    TOTAL_CODE if total <= provider else 'MISSION028_RESERVE_REACHED'))
    def take(self):
        with self.connection:
            self.connection.execute('BEGIN IMMEDIATE')
            remaining, reason = self.connection.execute('SELECT remaining, reason FROM budget WHERE run=?', (self.run_id,)).fetchone()
            if remaining <= 0:
                raise RuntimeError(reason)
            self.connection.execute('UPDATE budget SET remaining=remaining-1 WHERE run=?', (self.run_id,))

def reserve_status(store, now):
    if len(tuple(store.iter_keys(f"{PREFIX}/status-slots/"))) >= 925:
        raise RuntimeError(TOTAL_CODE)
    prefix = f"{PREFIX}/status-slots/{now.astimezone(UTC).date().isoformat()}/"
    for slot in range(49):  # Plus the original census proof: at most 50/day.
        if store.put_if_absent(f"{prefix}{slot:02d}", b'{}'):
            return
    raise RuntimeError("MISSION028_DAILY_BUDGET_REACHED")
