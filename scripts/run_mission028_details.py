"""Mission 028 details: four bounded workers, one durable call per fixture/family."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from robin.historical.normalization import normalize_records
from robin.historical.storage import PartitionedParquetStore
from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import ApiFootballDeepClient
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import R2FirstRepository
from scripts import run_mission028 as census
from scripts.mission028_budget import DETAIL_CAP, reserve_status
from scripts.run_mission028 import DIGEST, LEAGUES, PREFIX, Transport, load_targets, season_start

OUTPUT = Path("artifacts/historical-deep/mission028-details")
MAPPING = Path("configs/execution/mission028-mapping.csv")
MANIFEST = Path("configs/execution/mission028-mapping.json")
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
    """Atomic shared allowance: 69,750 details + 200 calendars + 50 statuses/day."""
    def __init__(self, store, now):
        self.store, self.day = store, now.astimezone(UTC).date().isoformat()
        self.prefix = f"{PREFIX}/daily/{self.day}/"
        slots = [int(k.rsplit("/", 1)[1]) for k in store.iter_keys(self.prefix)]
        self.next_slot = max(slots, default=-1) + 1
    def reserve(self, now, remaining):
        require(now.astimezone(UTC).date().isoformat() == self.day, "MISSION028_DAY_ENDED", RuntimeError)
        require(remaining > 5000, "MISSION028_RESERVE_REACHED", RuntimeError)
        while self.next_slot < DETAIL_CAP:
            key = f"{self.prefix}{self.next_slot:05d}"
            self.next_slot += 1
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
    next_at = 0.0
    def get(self, url, **kwargs):
        time.sleep(max(0, self.next_at - time.monotonic()))
        self.next_at = time.monotonic() + .5  # Exactly four workflow workers: <=8 rps.
        return super().get(url, **kwargs)
def preflight():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    receipt = dict(status="PARTIAL", status_calls=0, source_sha256=DIGEST)
    try:
        load_mapping()  # No storage or provider call before validating the frozen mapping.
        assert_safety_locks(os.environ)
        store, now = R2ObjectStore(os.environ), datetime.now(UTC)
        binding = Path(MANIFEST).read_bytes()
        key = f"{PREFIX}/mapping-manifest.json"
        require(store.put_if_absent(key, binding) or store.get_object(key) == binding, "MISSION028_MAPPING_ALREADY_BOUND", RuntimeError)
        proofs = [ProviderStatus.model_validate_json(store.get_object(k))
                  for k in store.iter_keys(f"{PREFIX}/preflight/")]
        fresh = [p for p in proofs if p.checked_at.date() == now.date()
                 and timedelta(0) <= now - p.checked_at < timedelta(minutes=110)]
        if fresh:
            status = max(fresh, key=lambda p: p.checked_at)
        else:
            reserve_status(store, now)
            receipt["status_calls"] = 1
            client = ApiFootballDeepClient(api_key=os.environ["API_FOOTBALL_KEY"], max_retries=0, transport=Transport(now + timedelta(minutes=1)), status_ttl_seconds=6600)
            status = client.get_status()
            store.put_if_absent(f"{PREFIX}/preflight/{os.environ['GITHUB_RUN_ID']}.json", status.model_dump_json().encode())
        (OUTPUT / "preflight.json").write_text(status.model_dump_json())
        receipt.update(status="PASS", checked_at=status.checked_at.isoformat(), quota_remaining=status.daily_remaining)
    except Exception as error:
        receipt["reason_class"] = type(error).__name__
    (OUTPUT / "preflight-public-receipt.json").write_text(json.dumps(receipt) + "\n")
    return 0 if receipt["status"] == "PASS" else 2
def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    worker, family = int(os.environ["MISSION028_WORKER"]), os.environ["MISSION028_FAMILY"]
    receipt = dict(status="PARTIAL", worker=worker, family=family, calls=0, complete_matches=0, partitions=[], missing=[], source_sha256=DIGEST, daily_cap=70000, daily_reserve=5000)
    transport = store = quota = None
    try:
        require(worker in range(4) and family in ("lineups", "statistics"), "MISSION028_WORKER_OR_FAMILY_INVALID")
        mapping = load_mapping()
        provider_by_fixture = {r["fixture_id"]: int(r["league_id"]) for r in mapping}
        selected = [r for r in mapping if sorted(LEAGUES).index(r["ligue_fd"]) % 4 == worker]
        ids = sorted(r["fixture_id"] for r in selected)
        receipt.update(target_count=len(ids), fixture_ids_sha256=hashlib.sha256(
            "".join(f"{i}\n" for i in ids).encode()).hexdigest())
        assert_safety_locks(os.environ)
        store, now = R2ObjectStore(os.environ), datetime.now(UTC)
        proof = ProviderStatus.model_validate_json((OUTPUT / "preflight.json").read_bytes())
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        require(proof.checked_at.date() == now.date() and timedelta(0) <= now - proof.checked_at < timedelta(minutes=110), "MISSION028_PREFLIGHT_EXPIRED", RuntimeError)
        transport = PacedTransport(min(midnight, proof.checked_at + timedelta(minutes=110), now + timedelta(minutes=95)))
        quota = QuotaController(proof)
        client = ApiFootballDeepClient(api_key=os.environ["API_FOOTBALL_KEY"], quota=quota, transport=transport, max_retries=0)
        collector = HistoricalDeepCollector(client, R2FirstRepository(store), source_commit=os.environ["GITHUB_SHA"])
        slots, groups = DaySlots(store, now), defaultdict(list)
        parquet = PartitionedParquetStore(OUTPUT / "historical/parquet")
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
            for fixture in fixtures:
                if saved is not None:
                    records = projected[fixture]
                else:
                    request = dict(phase="mission028", competition=provider_by_fixture[fixture], season=season, family=family, endpoint=f"/fixtures/{family}", params=dict(fixture=fixture))
                    call = once(collector, store, slots, request, datetime.now(UTC), quota.status.daily_remaining)
                    records = call.records if call else []
                    if call:
                        rows.extend(normalize_records(f"fixtures/{family}", records, competition_id=provider_by_fixture[fixture], season=season, ingestion_run_id="mission-028", raw_payload_hash=call.payload_sha256,
                            request_params=dict(fixture=fixture), observed_at=call.received_at))
                receipt["complete_matches"] += int(complete(family, records))
                if not complete(family, records):
                    receipt["missing"].append(fixture)
                receipt["quota_low"] = min(receipt["quota_low"], quota.status.daily_remaining)
            if saved is None:
                parquet.write_records(rows, competition=code, season=season, entity_type=family, dataset_version="api-football-v3")
            body = path.read_bytes()
            require(store.put_if_absent(key, body) or store.get_object(key) == body, "MISSION028_PROJECTION_CONFLICT", RuntimeError)
            receipt["partitions"].append(dict(path=path.relative_to(OUTPUT.resolve()).as_posix(),
                sha256=hashlib.sha256(body).hexdigest(), r2_key=key, rows=len(rows)))
            print(f"Mission 028 {family}: {code} {season}; calls={transport.calls}", flush=True)
        receipt["complete_fraction"] = receipt["complete_matches"] / len(ids) if ids else 1
        receipt["status"] = "COMPLETE" if receipt["complete_fraction"] >= (.95 if family == "lineups" else .90) else "PARTIAL"
    except Exception as error:
        receipt["reason_class"] = type(error).__name__
    receipt.update(calls=transport.calls if transport else 0, distinct_matches_called=transport.calls if transport else 0,
                   quota_remaining=quota.status.daily_remaining if quota else None, run_id=os.environ["GITHUB_RUN_ID"])
    body = (json.dumps(receipt, indent=2) + "\n").encode()
    name = f"worker-{worker}-{family}-public-receipt.json"
    (OUTPUT / name).write_bytes(body)
    if store:
        store.put_if_absent(f"{PREFIX}/runs/{receipt['run_id']}/{name}", body)
    return 0 if receipt["status"] == "COMPLETE" else 2
if __name__ == "__main__":
    raise SystemExit(preflight() if "--preflight" in sys.argv else main())
