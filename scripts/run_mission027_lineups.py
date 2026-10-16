"""Bound the existing collector to the immutable mission 027 lineup whitelist."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from robin.historical.normalization import normalize_records
from robin.historical.storage import PartitionedParquetStore
from robin.historical_deep.adapters import R2ObjectStore, assert_safety_locks
from robin.historical_deep.collector import HistoricalDeepCollector
from robin.historical_deep.contracts import ProviderStatus
from robin.historical_deep.provider import ApiFootballDeepClient
from robin.historical_deep.quota import QuotaController
from robin.historical_deep.storage import R2FirstRepository
from scripts.check_api_football_status import StatusTransport

DIGEST = "4e471c16b27b3ce5deaa8602795eb687f4e812975265d720c5697d4ce6bd288c"
LEAGUES = {"Premier-League": 39, "La-Liga": 140, "Serie-A": 135, "Bundesliga": 78}
PREFIX = "historical-deep-data/schema-v1/_control/mission-027"
OUTPUT = Path("artifacts/historical-deep/mission027")


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
    return len(records) == 2 and len({r.get("team", {}).get("id") for r in records}) == 2 and all(
        r.get("team", {}).get("id") and r.get("formation") and len(r.get("startXI", [])) == 11
        and len({p.get("player", {}).get("id") for p in r["startXI"]}) == 11
        and all(p.get("player", {}).get("id") for p in r["startXI"])
        for r in records
    )


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
    transport = StatusTransport()
    store = quota = None
    try:
        assert_safety_locks(os.environ)
        config = json.loads(Path("configs/execution/mission027-targets.json").read_text())
        groups = config["groups"]
        validate_targets(groups)  # Validate all seasons and IDs before any storage or HTTP.
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
                if transport.calls >= 8000 or quota.status.daily_remaining <= 5000:
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
        receipt["complete_fraction"] = receipt["complete_matches"] / 7228
        receipt["status"] = "COMPLETE" if receipt["complete_fraction"] >= .95 and not (
            receipt["uncertain_reservations"]
        ) else "PARTIAL"
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
