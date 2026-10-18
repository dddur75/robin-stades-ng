"""Workflow 71 admission: immutable R2 slots, including uncertain HTTP attempts."""
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from threading import RLock
from typing import Any

from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.storage import ObjectStore

PREFIX = 'historical-deep-data/schema-v1/_control/workflow-71'
OLD = 'historical-deep-data/schema-v1/_control/mission-028'


class Admission:
    def __init__(self, store: ObjectStore, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.store, self.clock, self.lock = store, clock, RLock()
        self.day = clock().astimezone(UTC).date()
        self.indices: dict[str, int] = {}
        self.proof: dict[str, Any] | None = None
        self.legacy_status = len(tuple(store.iter_keys(f'{OLD}/status-slots/')))
        # Old 027 markers have no date: charge all of them conservatively today.
        self.legacy = sum(len(tuple(store.iter_keys(p))) for p in (
            f'{OLD}/daily/{self.day}/', f'{OLD}/status-slots/{self.day}/',
            f'{OLD}/requests/',
            'historical-deep-data/schema-v1/_control/mission-027/fixture='))

    def index(self, prefix: str) -> int:
        if prefix not in self.indices:
            self.indices[prefix] = max((int(k.rsplit('/', 1)[1])
                for k in self.store.iter_keys(prefix)), default=-1) + 1
        return self.indices[prefix]

    def take(self, prefix: str, cap: int, ceiling: int | None = None) -> int:
        while self.index(prefix) < cap:
            number = self.indices[prefix]
            if ceiling is not None and number >= ceiling:
                raise RuntimeError('W71_PROVIDER_RESERVE')
            self.indices[prefix] += 1
            if self.store.put_if_absent(f'{prefix}{number:06d}', b'{}'):
                return number
        raise RuntimeError('W71_LIMIT_REACHED')

    def reserve(self, endpoint: str, *, mission: bool = False, remaining: int | None = None) -> None:
        with self.lock:
            if self.clock().astimezone(UTC).date() != self.day:
                raise RuntimeError('W71_DAY_ENDED')
            status = endpoint == '/status'
            if status:
                self.take(f'{PREFIX}/statuses/total/', 925 - self.legacy_status)
                prior = len(tuple(self.store.iter_keys(f'{OLD}/status-slots/{self.day}/')))
                self.take(f'{PREFIX}/statuses/{self.day}/', 49 - prior)
                lease = f'{PREFIX}/status-refresh/{self.day}/{int(self.clock().timestamp()) // 6600}'
                if not self.store.put_if_absent(lease, b'{}'):
                    raise RuntimeError('W71_STATUS_PENDING')
            daily = f'{PREFIX}/daily/{self.day}/'
            proof = self.proof or dict(remaining=remaining or 0, baseline=-self.legacy)
            ceiling = None if status else proof['baseline'] + proof['remaining'] - 5000
            self.before_status = self.take(daily, 130000 - self.legacy, ceiling)
            if mission:
                self.take(f'{PREFIX}/mission029/', 240000)

    def cached_status(self) -> dict[str, Any] | None:
        now = self.clock().astimezone(UTC)
        proofs = [json.loads(self.store.get_object(k) or b'null')
            for k in self.store.iter_keys(f'{PREFIX}/proofs/{now.date()}/')]
        fresh = [p for p in proofs if timedelta(0) <= now - datetime.fromisoformat(
            p['checked_at']) < timedelta(minutes=110)]
        if not fresh:
            return None
        self.proof = max(fresh, key=lambda p: p['checked_at'])
        return dict(self.proof['status'])

    def remember(self, status: ProviderStatus) -> None:
        self.proof = dict(checked_at=status.checked_at.isoformat(),
            remaining=status.daily_remaining, baseline=-self.legacy,
            status=status.model_dump(mode='json'))
        self.store.put_if_absent(f'{PREFIX}/proofs/{self.day}/{status.checked_at.isoformat()}',
            json.dumps(self.proof).encode())


@cache
def workflow_budget() -> Admission:
    from robin.historical_deep.adapters import R2ObjectStore
    return Admission(R2ObjectStore(os.environ))
