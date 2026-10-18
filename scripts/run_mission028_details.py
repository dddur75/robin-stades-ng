"""Mission 028 details: bounded parallel attempts, no recall after restart."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock, local
from types import SimpleNamespace

import pyarrow.parquet as pq
import requests

from robin.historical.normalization import normalize_records
from robin.historical.storage import PartitionedParquetStore
from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import (
    ApiFootballDeepClient,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import R2FirstRepository
from scripts import run_mission028 as census
from scripts.mission028_budget import DETAIL_CAP, RunBudget, reserve_status
from scripts.mission028_performance import MeasuredStore, RateGate, Timings
from scripts.mission028_resume import BUDGET_CODES, WORKERS, checkpoint
from scripts.run_mission028 import DIGEST, LEAGUES, PREFIX, Transport, load_targets, season_start

OUTPUT = Path("artifacts/historical-deep/mission028-details")
MAPPING = Path("configs/execution/mission028-mapping.csv")
MANIFEST = Path("configs/execution/mission028-mapping.json")
THREADS = 4
def halt_path():
    return OUTPUT / f".halt-{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
def require(condition, reason, error=ValueError):
    if not condition:
        raise error(reason)
def load_mapping(path=MAPPING, manifest=MANIFEST):
    original = load_targets()
    proof, raw = json.loads(Path(manifest).read_text()), Path(path).read_bytes()
    require(proof["source_sha256"] == DIGEST and hashlib.sha256(raw).hexdigest() == proof["mapping_sha256"], "MISSION028_MAPPING_HASH_MISMATCH")
    table = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    require(len(table) == len(original), "MISSION028_MAPPING_POPULATION_CHANGED")
    selected = []
    for number, (row, source) in enumerate(zip(table, original, strict=True), 1):
        require(all(row.get(k) == v for k, v in source.items()) and int(row["source_row"]) == number, "MISSION028_MAPPING_SOURCE_CHANGED")
        require(int(row["season"]) == season_start(source["saison_fd"]) and int(row["league_id"]) in census.provider_league_ids(row["ligue_fd"], int(row["season"])), "MISSION028_MAPPING_SCOPE_INVALID")
        if row["fixture_id"]:
            row["fixture_id"] = int(row["fixture_id"])
            require(row["fixture_id"] > 0 and row["reason"] == "MATCHED", "MISSION028_MAPPING_ID_INVALID")
            selected.append(row)
    require(selected and len(selected) <= 61000 and len({r["fixture_id"] for r in selected}) == len(selected), "MISSION028_MAPPING_DUPLICATE_OR_OVERSIZED")
    return selected
class DaySlots:
    """Atomic shared allowance: 129,750 details + 200 calendars + 50 statuses/day."""
    def __init__(self, store, now, worker=0, stride=WORKERS, budget=None):
        require(worker in range(stride), "MISSION028_WORKER_INVALID")
        self.stride, self.budget = stride, budget
        self.store, self.day = store, now.astimezone(UTC).date().isoformat()
        self.prefix = f"{PREFIX}/daily/{self.day}/"
        slots = [int(k.rsplit("/", 1)[1]) for k in store.iter_keys(self.prefix)]
        self.next_slot = max((slot for slot in slots if slot % stride == worker), default=worker - stride) + stride
    def reserve(self, now, remaining):
        require(now.astimezone(UTC).date().isoformat() == self.day, "MISSION028_DAY_ENDED", RuntimeError)
        require(remaining > 5000, "MISSION028_RESERVE_REACHED", RuntimeError)
        if self.budget:
            self.budget.take()
        while self.next_slot < DETAIL_CAP:
            key = f"{self.prefix}{self.next_slot:05d}"
            self.next_slot += self.stride
            if self.store.put_if_absent(key, b'{"reserved":true}'):
                return
        raise RuntimeError("MISSION028_DAILY_BUDGET_REACHED")
def once(collector, store, slots, request, now, remaining):
    task = collector._make_task(**request, identity=None)
    if collector.repository.receipt_for(task) is not None:
        return collector._collect(**request)
    key = f"{PREFIX}/details/{request['family']}/{request['params']['fixture']}.json"
    if store.get_object(key) is not None:
        return None
    slots.reserve(now, remaining)
    if not store.put_if_absent(key, b'{"reserved":true}'):
        return None
    return collector._collect(**request)
def complete(family, records):
    try:
        if len(records) != 2 or len({r["team"]["id"] for r in records}) != 2:
            return False
        if not all(r["team"]["id"] for r in records):
            return False
        if family == "statistics":
            return all(any(s.get("value") is not None for s in r["statistics"]) for r in records)
        return all(isinstance(r["formation"], str) and r["formation"].strip()
            and len(r["startXI"]) == 11 and len({p["player"]["id"] for p in r["startXI"]}) == 11
            and all(p["player"]["id"] for p in r["startXI"]) for r in records)
    except (KeyError, TypeError, AttributeError):
        return False
class PacedTransport(Transport):
    time_slice_ended = False
    def __init__(self, deadline, gate_path=None, timings=None):
        super().__init__(deadline)
        self.timings = timings or Timings()
        self.gate = RateGate(gate_path or OUTPUT / '.pace.sqlite3')
    def check_deadline(self):
        if datetime.now(UTC) >= self.deadline:
            self.time_slice_ended = True
            raise RuntimeError("MISSION028_TIME_SLICE_ENDED")
        require(not halt_path().exists(), 'MISSION028_STOP_REQUESTED', RuntimeError)
    def wait(self, delay):
        self.check_deadline()
        time.sleep(min(delay, max(0, (self.deadline - datetime.now(UTC)).total_seconds())))
        self.check_deadline()
    def get(self, url, **kwargs):
        self.check_deadline()
        self.timings.call('rate_wait', self.gate.acquire)
        self.check_deadline()  # Admission may have waited; never call after cutoff.
        self.calls += 1
        return self.timings.call('provider_http', requests.get, url, allow_redirects=False, timeout=kwargs.pop('timeout', 10), **kwargs)
class RetryClient(ApiFootballDeepClient):
    attempts = 0
    def _before_transport(self, *, require_quota):
        self._transport.check_deadline()
        super()._before_transport(require_quota=require_quota)
        if self.attempts:  # once() has already durably reserved the first attempt.
            self.slots.reserve(datetime.now(UTC), self.quota.status.daily_remaining)
        self.attempts += 1
def preflight():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    receipt = dict(status="PARTIAL", status_calls=0, source_sha256=DIGEST)
    store = None
    try:
        load_mapping()  # No storage or provider call before validating the frozen mapping.
        assert_safety_locks(os.environ)
        store, now = R2ObjectStore(os.environ), datetime.now(UTC)
        binding = Path(MANIFEST).read_bytes()
        key = f"{PREFIX}/mapping-manifest.json"
        require(store.put_if_absent(key, binding) or store.get_object(key) == binding, "MISSION028_MAPPING_ALREADY_BOUND", RuntimeError)
        proofs = [ProviderStatus.model_validate_json(store.get_object(k))
                  for k in store.iter_keys(f"{PREFIX}/preflight/")]
        fresh = [p for p in proofs if p.checked_at.date() == now.date() and p.checked_at <= now
                 and p.status_expires_at - now >= timedelta(minutes=100)]  # 95 + startup margin.
        if fresh:
            status = max(fresh, key=lambda p: p.checked_at)
        else:
            reserve_status(store, now)
            receipt["status_calls"] = 1
            client = ApiFootballDeepClient(api_key=os.environ["API_FOOTBALL_KEY"], max_retries=0,
                transport=Transport(now + timedelta(minutes=1)), status_ttl_seconds=7200)
            status = client.get_status()
            store.put_if_absent(f"{PREFIX}/preflight/{os.environ['GITHUB_RUN_ID']}.json",
                                status.model_dump_json().encode())
        (OUTPUT / "preflight.json").write_text(status.model_dump_json())
        receipt.update(status="PASS", checked_at=status.checked_at.isoformat(), quota_remaining=status.daily_remaining)
    except Exception as error:
        receipt["reason_class"] = type(error).__name__
        if str(error) in BUDGET_CODES:
            receipt["reason_code"] = str(error)
    checkpoint(store, receipt, datetime.now(UTC), os.environ.get("GITHUB_SHA", "local"))
    (OUTPUT / "preflight-public-receipt.json").write_text(json.dumps(receipt) + "\n")
    if store:
        store.put_if_absent(f"{PREFIX}/runs/{os.environ.get('GITHUB_RUN_ID', 'local')}/preflight-public-receipt.json", (json.dumps(receipt) + "\n").encode())
    return 0 if receipt["status"] == "PASS" else 2
def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    worker, family = int(os.environ["MISSION028_WORKER"]), os.environ["MISSION028_FAMILY"]
    receipt = dict(status="PARTIAL", worker=worker, family=family, calls=0, complete_matches=0, partitions=[], missing=[], source_sha256=DIGEST, daily_cap=130000, daily_reserve=5000)
    transport = store = quota = None
    pool, contexts, called, fatal = None, [], set(), []
    state, creation_lock = local(), Lock()
    receipt['request_errors'] = []
    timings = Timings()
    try:
        require(worker in range(WORKERS) and family in ("lineups", "statistics"), "MISSION028_WORKER_OR_FAMILY_INVALID")
        mapping = load_mapping()
        provider_by_fixture = {r["fixture_id"]: int(r["league_id"]) for r in mapping}
        selected = [r for r in mapping if sorted(LEAGUES).index(r["ligue_fd"]) % WORKERS == worker]
        ids = sorted(r["fixture_id"] for r in selected)
        receipt.update(target_count=len(ids), fixture_ids_sha256=hashlib.sha256(
            "".join(f"{i}\n" for i in ids).encode()).hexdigest())
        assert_safety_locks(os.environ)
        store, now = MeasuredStore(R2ObjectStore(os.environ), timings), datetime.now(UTC)
        proof = ProviderStatus.model_validate_json((OUTPUT / "preflight.json").read_bytes())
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        require(proof.checked_at.date() == now.date() and proof.checked_at <= now and proof.status_expires_at - now >= timedelta(minutes=1), "MISSION028_PREFLIGHT_EXPIRED", RuntimeError)
        transport = PacedTransport(min(midnight, proof.status_expires_at, now + timedelta(minutes=95)), timings=timings)
        quota = QuotaController(proof)
        def fetch(fixture):
            try:
                transport.check_deadline()
                if not hasattr(state, 'context'):
                    with creation_lock:
                        c = SimpleNamespace(store=MeasuredStore(store.store, timings), quota=QuotaController(proof),
                            transport=PacedTransport(transport.deadline, timings=timings))
                        c.slots = DaySlots(c.store, now, worker + WORKERS * len(contexts), WORKERS * THREADS,
                            RunBudget(OUTPUT / '.budget.sqlite3', os.environ['GITHUB_RUN_ID'], c.store, now, proof.daily_remaining))
                        c.client = RetryClient(api_key=os.environ['API_FOOTBALL_KEY'], quota=c.quota, transport=c.transport,
                            max_retries=3, circuit_cooldown_seconds=0, timeout_seconds=10, sleeper=c.transport.wait, jitter=lambda: 0.)
                        c.client.slots = c.slots
                        c.collector = HistoricalDeepCollector(c.client, R2FirstRepository(c.store), source_commit=os.environ['GITHUB_SHA'])
                        for method, stage in [('receipt_for', 'receipt_for'), ('load_receipt', 'receipt_for'), ('capture', 'capture_r2')]:
                            timings.wrap(c.collector.repository, method, stage)
                        timings.wrap(c.slots, 'reserve', 'day_slots_reserve')
                        contexts.append(c)
                        state.context = c
                c = state.context
                c.transport.check_deadline()
                c.client.attempts, before = 0, c.transport.calls
                request = dict(phase='mission028', competition=provider_by_fixture[fixture], season=season,
                    family=family, endpoint=f'/fixtures/{family}', params=dict(fixture=fixture))
                try:
                    return fixture, once(c.collector, c.store, c.slots, request, datetime.now(UTC), c.quota.status.daily_remaining)
                except (ProviderTransportError, ProviderResponseError, ProviderRateLimitError) as error:
                    c.transport.check_deadline()
                    receipt['request_errors'].append(dict(fixture=fixture, reason_class=type(error).__name__))
                    return fixture, None
                finally:
                    if c.transport.calls > before:
                        called.add(fixture)
            except Exception as error:
                if str(error) != 'MISSION028_STOP_REQUESTED':
                    fatal.append(error)
                halt_path().touch()
                raise
        pool, groups = ThreadPoolExecutor(max_workers=THREADS), defaultdict(list)
        parquet = PartitionedParquetStore(OUTPUT / "historical/parquet")
        timings.wrap(parquet, 'write_records', 'write_parquet')
        receipt["quota_low"] = quota.status.daily_remaining
        for row in selected:
            groups[row["ligue_fd"], int(row["season"])].append(row["fixture_id"])
        for (code, season), fixtures in sorted(groups.items()):
            path = parquet.partition_path(competition=code, season=season, entity_type=family, dataset_version="api-football-v3")
            key = f"{PREFIX}/projection/{path.relative_to(OUTPUT.resolve()).as_posix()}"
            saved, rows, projected = store.get_object(key), [], defaultdict(list)
            if saved is not None:
                rows = pq.ParquetFile(io.BytesIO(saved)).read().to_pylist()
                for row in rows:
                    require(row["provider_fixture_id"] in fixtures and row["season"] == season and row["availability_status"] == "POST_MATCH_ONLY" and row["competition_id"] == provider_by_fixture[row["provider_fixture_id"]], "MISSION028_PROJECTION_SCOPE_INVALID")
                    projected[row["provider_fixture_id"]].append(json.loads(row["payload"]))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(saved)
            results = ((f, None) for f in fixtures) if saved is not None else pool.map(fetch, fixtures)
            for fixture, call in results:
                transport.check_deadline()
                if saved is not None:
                    records = projected[fixture]
                else:
                    records = call.records if call else []
                    if call:
                        rows.extend(normalize_records(f"fixtures/{family}", records, competition_id=provider_by_fixture[fixture], season=season, ingestion_run_id="mission-028", raw_payload_hash=call.payload_sha256,
                            request_params=dict(fixture=fixture), observed_at=call.received_at))
                receipt["complete_matches"] += int(complete(family, records))
                if not complete(family, records):
                    receipt["missing"].append(fixture)
                receipt["quota_low"] = min([receipt["quota_low"], *(c.quota.status.daily_remaining for c in contexts)])
            if saved is None:
                parquet.write_records(rows, competition=code, season=season, entity_type=family, dataset_version="api-football-v3")
            body = path.read_bytes()
            require(store.put_if_absent(key, body) or store.get_object(key) == body, "MISSION028_PROJECTION_CONFLICT", RuntimeError)
            receipt["partitions"].append(dict(path=path.relative_to(OUTPUT.resolve()).as_posix(),
                sha256=hashlib.sha256(body).hexdigest(), r2_key=key, rows=len(rows)))
            print(f"Mission 028 {family}: {code} {season}; calls={sum(c.transport.calls for c in contexts)}", flush=True)
        receipt["complete_fraction"] = receipt["complete_matches"] / len(ids) if ids else 1
        receipt["status"] = "COMPLETE" if receipt["complete_fraction"] >= (.95 if family == "lineups" else .90) else "PARTIAL"
    except Exception as error:
        error = fatal[0] if fatal else error
        halt_path().touch()
        receipt["reason_class"] = type(error).__name__
        if str(error) in BUDGET_CODES | {'MISSION028_STOP_REQUESTED'}:
            receipt["reason_code"] = str(error)
        if str(error) == "MISSION028_TIME_SLICE_ENDED":
            receipt.update(reason_class="TimeSliceEnded", reason_code="MISSION028_TIME_SLICE_ENDED")
    if pool:
        pool.shutdown(wait=True, cancel_futures=True)
    receipt.update(calls=sum(c.transport.calls for c in contexts), distinct_matches_called=len(called),
                   quota_remaining=min((c.quota.status.daily_remaining for c in contexts), default=None), run_id=os.environ["GITHUB_RUN_ID"], timings=timings.summary())
    body = (json.dumps(receipt, indent=2) + "\n").encode()
    name = f"worker-{worker}-{family}-public-receipt.json"
    (OUTPUT / name).write_bytes(body)
    if store:
        checkpoint(store, receipt, datetime.now(UTC), os.environ["GITHUB_SHA"], transport.deadline if transport else None)
        store.put_if_absent(f"{PREFIX}/runs/{receipt['run_id']}/{name}", body)
    normal = receipt.get("reason_code") in BUDGET_CODES | {"MISSION028_TIME_SLICE_ENDED", "MISSION028_STOP_REQUESTED"} or receipt.get("reason_class") in ("QuotaExhaustedError", "QuotaStatusExpiredError")
    return 2 if "reason_class" in receipt and not normal else 0
if __name__ == "__main__":
    raise SystemExit(preflight() if "--preflight" in sys.argv else main())
