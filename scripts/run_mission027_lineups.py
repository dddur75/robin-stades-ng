"""Bound the existing collector to the immutable mission 027 lineup whitelist."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from robin.historical.normalization import normalize_records
from robin.historical.storage import PartitionedParquetStore
from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import ApiFootballDeepClient
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import (
    HarvestReceipt,
    R2FirstRepository,
    TaskVersion,
    receipt_key,
    version_key,
)

DIGEST = "4e471c16b27b3ce5deaa8602795eb687f4e812975265d720c5697d4ce6bd288c"
LEAGUES = {"Premier-League": 39, "La-Liga": 140, "Serie-A": 135, "Bundesliga": 78}
PREFIX = "historical-deep-data/schema-v1/_control/mission-027"
OUTPUT = Path("artifacts/historical-deep/mission027")


class LineupTransport:
    calls = 0
    next_at = 0.0
    deadline = None

    def get(self, url, **kwargs):
        time.sleep(max(0.0, self.next_at - time.monotonic()))
        if self.deadline is not None and datetime.now(UTC) >= self.deadline:
            raise RuntimeError("ORIGINAL_QUOTA_DAY_ENDED")
        self.next_at = time.monotonic() + 0.5  # Four isolated workers: <=8 rps total.
        self.calls += 1
        return requests.get(url, allow_redirects=False, **kwargs)


class CachedStore:
    """Cache immutable reads; every conditional write still reaches R2."""
    def __init__(self, store):
        self.store, self.cache = store, {}

    def get_object(self, key):
        if key not in self.cache:
            self.cache[key] = self.store.get_object(key)
        return self.cache[key]

    def put_if_absent(self, key, data):
        created = self.store.put_if_absent(key, data)
        self.cache.pop(key, None)
        if created:
            self.cache[key] = data
        return created

    def iter_keys(self, prefix):
        return self.store.iter_keys(prefix)


class ReceiptBoundary:
    """Expose the collector's minimal receipt/payload/capture interface."""
    def __init__(self, repository):
        self.receipt_for = repository.receipt_for
        self.payload_for = repository.payload_for
        self.capture = repository.capture


def validate_targets(groups):
    assert len(groups) == 20
    assert {(g["competition"], g["season"]) for g in groups} == {
        (league, season) for league in LEAGUES for season in range(2020, 2025)
    }
    ids = [i for g in groups for i in g["fixture_ids"]]
    assert all(type(i) is int and i > 0 for i in ids)
    assert len(ids) == len(set(ids)) == 7228
    assert hashlib.sha256("".join(f"{i}\n" for i in sorted(ids)).encode()).hexdigest() == DIGEST


def complete(records):
    try:
        return len(records) == 2 and len({r.get("team", {}).get("id") for r in records}) == 2 and all(
            r.get("team", {}).get("id") and isinstance(r.get("formation"), str) and r["formation"].strip()
            and len(r.get("startXI", [])) == 11
            and len({p.get("player", {}).get("id") for p in r["startXI"]}) == 11
            and all(p.get("player", {}).get("id") for p in r["startXI"])
            for r in records
        )
    except (AttributeError, KeyError, TypeError):
        return False


def collect_once(collector, store, request):
    task = collector._make_task(**request, identity=None)
    marker = f"{PREFIX}/fixture={request['params']['fixture']}.json"
    if not store.put_if_absent(marker, b'{"reserved":true}'):
        if collector.repository.receipt_for(task) is None:
            return None  # Crash or failed response: never issue the request again.
    return collector._collect(**request)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_version": "mission-027-lineups-public-receipt-v1", "status": "PARTIAL",
               "preflight_run_id": "38960293874", "max_calls": 8000, "daily_reserve": 5000,
               "status_calls_new": 0, "lineup_calls": 0, "distinct_matches_called": 0,
               "target_count": 7228, "fixture_ids_sha256": DIGEST, "complete_matches": 0,
               "matches_without_response": [], "uncertain_reservations": [], "partitions": []}
    transport = LineupTransport()
    store = quota = None
    try:
        assert_safety_locks(os.environ)
        config = json.loads(Path("configs/execution/mission027-targets.json").read_text())
        groups = config["groups"]
        validate_targets(groups)  # Validate all seasons and IDs before any storage or HTTP.
        if "--progress" in sys.argv:
            probe = R2ObjectStore(os.environ)
            keys = tuple(probe.iter_keys(f"{PREFIX}/fixture="))
            reserved = {int(key.rsplit("=", 1)[1].split(".")[0]) for key in keys}
            assert reserved <= {i for g in groups for i in g["fixture_ids"]}
            progress = {"status": "OBSERVED", "reserved_targets": len(reserved),
                        "target_count": 7228, "status_calls": 0, "lineup_calls": 0,
                        "raw_payload_reads": 0, "r2_writes": 0,
                        "calls_by_source_commit": {}, "api_seconds_by_source_commit": {},
                        "missing_legacy_receipts": [],
                        "receipt_metadata_reads": 0,
                        "observed_at": datetime.now(UTC).isoformat()}
            legacy = next(g for g in groups if (g["competition"], g["season"]) == ("Premier-League", 2020))
            for fixture in reserved.intersection(legacy["fixture_ids"]):
                request = dict(phase="lineups_only", competition=39, season=2020,
                               family="lineups", endpoint="/fixtures/lineups", params={"fixture": fixture})
                task = HistoricalDeepCollector(None)._make_task(**request, identity=None)
                raw = probe.get_object(receipt_key(task))
                progress["receipt_metadata_reads"] += 1
                if raw is None:
                    version = probe.get_object(version_key(task))
                    progress["receipt_metadata_reads"] += 1
                    saved = TaskVersion.model_validate_json(version).receipt if version else None
                else:
                    saved = HarvestReceipt.model_validate_json(raw)
                if saved is None:
                    progress["missing_legacy_receipts"].append(fixture)
                    continue
                assert saved.task_hash == task.task_hash
                counts = progress["calls_by_source_commit"]
                counts[saved.source_commit] = counts.get(saved.source_commit, 0) + saved.provider_calls
                times = progress["api_seconds_by_source_commit"]
                times[saved.source_commit] = times.get(saved.source_commit, 0) + (saved.received_at - saved.requested_at).total_seconds()
            (OUTPUT / "progress.json").write_text(json.dumps(progress) + "\n")
            print(json.dumps(progress), flush=True)
            return 0
        scope = os.environ.get("MISSION027_COMPETITION", "all")
        assert scope in LEAGUES  # Only four workers can spend; all is observation-only.
        groups = [g for g in groups if g["competition"] == scope]
        scoped_ids = [i for g in groups for i in g["fixture_ids"]]
        receipt.update(scope=scope, phase_target_count=7228, phase_fixture_ids_sha256=DIGEST,
                       target_count=len(scoped_ids), fixture_ids_sha256=hashlib.sha256(
                           "".join(f"{i}\n" for i in sorted(scoped_ids)).encode()).hexdigest())
        raw = Path("artifacts/mission027-preflight/status-public-receipt.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == config["status_receipt_sha256"]
        proof = json.loads(raw)
        assert proof["status"] == "PASS" and proof["status_calls"] == 1
        checked = datetime.fromisoformat(proof["checked_at"])
        # Reuse the original key proof only until its original UTC quota reset.
        # Every response refreshes quota headers; never refresh /status.
        status = ProviderStatus(plan="Mega", active=True, checked_at=checked,
            expires_at=checked.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1),
            subscription_end=proof["subscription_end"], daily_limit=proof["daily_limit"],
            daily_used=proof["daily_limit"] - proof["quota_remaining"],
            daily_remaining=proof["quota_remaining"])
        assert status.is_fresh(datetime.now(UTC))
        transport.deadline = status.status_expires_at
        quota = QuotaController(status)
        client = ApiFootballDeepClient(api_key=os.environ["API_FOOTBALL_KEY"], quota=quota,
                                       max_retries=0, transport=transport)
        store = CachedStore(R2ObjectStore(os.environ))
        collector = HistoricalDeepCollector(client, ReceiptBoundary(R2FirstRepository(store)),
            source_commit=os.environ["GITHUB_SHA"])
        parquet = PartitionedParquetStore(OUTPUT / "historical/parquet")
        for group in groups:
            rows = []
            league, season = group["competition"], group["season"]
            for fixture in group["fixture_ids"]:
                if datetime.now(UTC) >= transport.deadline or transport.calls >= 8000 or quota.status.daily_remaining <= 5000:
                    raise RuntimeError("MISSION_BUDGET_REACHED")
                request = dict(phase="lineups_only", competition=LEAGUES[league], season=season,
                    family="lineups", endpoint="/fixtures/lineups", params={"fixture": fixture})
                before = transport.calls
                try:
                    call = collect_once(collector, store, request)
                finally:
                    receipt["distinct_matches_called"] += transport.calls - before
                if call is None:
                    receipt["uncertain_reservations"].append(fixture)
                    receipt["matches_without_response"].append(fixture)
                    continue
                if not call.records:
                    receipt["matches_without_response"].append(fixture)
                receipt["complete_matches"] += int(complete(call.records))
                rows.extend(normalize_records("fixtures/lineups", call.records,
                    competition_id=LEAGUES[league], season=season,
                    ingestion_run_id="mission-027-status-38960293874",
                    raw_payload_hash=call.payload_sha256, request_params={"fixture": fixture},
                    observed_at=call.received_at))
            partition = parquet.write_records(rows, competition=league, season=season,
                entity_type="lineups", dataset_version="api-football-v3")
            path = Path(partition["path"])
            key = f"{PREFIX}/projection/{path.relative_to(OUTPUT.resolve()).as_posix()}"
            if not store.put_if_absent(key, path.read_bytes()):
                assert store.get_object(key) == path.read_bytes()
            receipt["partitions"].append({**partition, "r2_key": key})
            print(f"Mission 027: {league} {season}; calls={transport.calls}", flush=True)
        receipt["quota_remaining"] = quota.status.daily_remaining
        receipt["complete_fraction"] = receipt["complete_matches"] / receipt["target_count"]
        receipt["status"] = "COMPLETE" if receipt["complete_fraction"] >= .95 else "PARTIAL"
    except Exception as error:
        receipt["reason_class"] = type(error).__name__  # No response body or secret.
    receipt["lineup_calls"] = transport.calls
    receipt["quota_remaining"] = quota.status.daily_remaining if quota is not None else None
    receipt["run_id"] = os.environ["GITHUB_RUN_ID"]
    payload = (json.dumps(receipt, indent=2) + "\n").encode()
    (OUTPUT / "public-receipt.json").write_bytes(payload)
    if store is not None:
        store.put_if_absent(f"{PREFIX}/runs/{receipt['run_id']}/public-receipt.json", payload)
    return 0 if receipt["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
