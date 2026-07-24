"""Gérer le pont append-only shadow-data et le replay PostgreSQL."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from robin.storage.database import build_engine
from robin.storage.durable import (
    DurableRecord,
    DurableRegistry,
    read_bundle,
    write_bundle,
)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        value
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def iso(value: object, fallback: datetime) -> datetime:
    if value in (None, ""):
        return fallback
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def latest_run(state: Path, current_run_id: str | None) -> dict[str, object]:
    runs = [
        value
        for path in sorted((state / "runs").glob("*.json"))
        for value in [read_json(path, {})]
        if isinstance(value, dict)
    ]
    if current_run_id:
        matching = [
            run
            for run in runs
            if current_run_id in str(run.get("run_id", ""))
        ]
        if matching:
            return matching[-1]
        if runs:
            now = datetime.now(UTC).isoformat()
            return {
                **runs[-1],
                "run_id": f"checkpoint-{current_run_id}",
                "pipeline": "durable-checkpoint",
                "upstream_run_id": runs[-1].get("run_id"),
                "started_at": now,
                "finished_at": now,
                "status": "DURABLE_WRITE_STAGED",
            }
    if not runs:
        now = datetime.now(UTC).isoformat()
        return {
            "run_id": f"manual-{current_run_id or now}",
            "pipeline": "manual-stage",
            "started_at": now,
            "finished_at": now,
            "status": "DURABLE_WRITE_STAGED",
        }
    return runs[-1]


def record(
    kind: str,
    business_key: str,
    payload: Mapping[str, object],
    *,
    run_id: str,
    observed_at: datetime,
    provider: str = "internal",
    quality: str = "OBSERVED",
    provenance: str = "LIVE SOURCE",
) -> DurableRecord:
    return DurableRecord(
        kind=kind,
        business_key=business_key,
        payload=payload,
        provider=provider,
        observed_at=observed_at,
        ingested_at=datetime.now(UTC),
        source_run_id=run_id,
        quality_status=quality,
        provenance_status=provenance,
    )


def state_records(state: Path, run: Mapping[str, object]) -> list[DurableRecord]:
    now = iso(run.get("finished_at"), datetime.now(UTC))
    run_id = str(run["run_id"])
    records: list[DurableRecord] = []
    for observation_path in sorted(
        (state / "raw" / "observations").rglob("*.json")
    ):
        observation = read_json(observation_path, {})
        if not isinstance(observation, dict):
            continue
        observation_id = str(
            observation.get("observation_id")
            or observation.get("id")
            or observation_path.stem
        )
        records.append(
            record(
                "provider_requests",
                observation_id,
                observation,
                run_id=run_id,
                observed_at=iso(observation.get("received_at"), now),
                provider=str(observation.get("provider", "unknown")),
            )
        )
    fixtures = read_json(state / "fixtures" / "latest.json", [])
    for item in fixtures if isinstance(fixtures, list) else []:
        if not isinstance(item, dict):
            continue
        fixture_key = str(item.get("id"))
        records.append(
            record(
                "durable_fixtures",
                fixture_key,
                item,
                run_id=run_id,
                observed_at=iso(item.get("collected_at"), now),
                provider="the-odds-api",
                provenance=str(item.get("origin", "LIVE SOURCE")),
            )
        )
        records.append(
            record(
                "provider_entity_mappings",
                f"fixture:the-odds-api:{fixture_key}",
                {
                    "internal_entity_id": item.get("internal_fixture_id", fixture_key),
                    "provider_entity_id": fixture_key,
                    "entity_type": "fixture",
                },
                run_id=run_id,
                observed_at=now,
                provider="the-odds-api",
            )
        )
    for item in _all_snapshots(state / "odds"):
        snapshot_id = str(item.get("snapshot_id"))
        records.append(
            record(
                "odds_snapshots",
                snapshot_id,
                item,
                run_id=run_id,
                observed_at=iso(item.get("observed_at"), now),
                provider=str(item.get("provider", "the-odds-api")),
            )
        )
        quotes = item.get("quotes", [])
        for quote in quotes if isinstance(quotes, list) else []:
            if not isinstance(quote, dict):
                continue
            bookmaker_id = str(quote.get("bookmaker_id", "unknown"))
            records.append(
                record(
                    "bookmakers",
                    bookmaker_id,
                    {"bookmaker_id": bookmaker_id},
                    run_id=run_id,
                    observed_at=now,
                    provider="the-odds-api",
                )
            )
            market = quote.get("market", {})
            if isinstance(market, dict):
                market_key = ":".join(
                    str(market.get(key, ""))
                    for key in ("market_type", "selection", "line_value")
                )
                records.append(
                    record(
                        "markets",
                        market_key,
                        {
                            "market_key": market_key,
                            "market_type": market.get("market_type", "UNKNOWN"),
                        },
                        run_id=run_id,
                        observed_at=now,
                        provider="the-odds-api",
                    )
                )
    for item in read_jsonl(state / "predictions" / "history.jsonl"):
        prediction_id = str(item.get("prediction_id"))
        records.append(
            record(
                "predictions",
                prediction_id,
                item,
                run_id=run_id,
                observed_at=iso(item.get("generated_at"), now),
                provenance=str(item.get("origin", "LIVE SOURCE")),
            )
        )
    for item in read_jsonl(state / "decisions" / "shadow-decisions.jsonl"):
        decision_id = str(item.get("decision_id"))
        records.append(
            record(
                "candidate_bets",
                decision_id,
                item,
                run_id=run_id,
                observed_at=iso(item.get("decided_at"), now),
                provenance=str(item.get("origin", "LIVE SOURCE")),
            )
        )
        target = "shadow_bets" if item.get("accepted") is True else "rejected_bets"
        records.append(
            record(
                target,
                decision_id,
                item,
                run_id=run_id,
                observed_at=iso(item.get("decided_at"), now),
                provenance=str(item.get("origin", "LIVE SOURCE")),
            )
        )
    blocked = read_json(state / "predictions" / "blocked.json", [])
    for item in blocked if isinstance(blocked, list) else []:
        if not isinstance(item, dict):
            continue
        key = f"{item.get('fixture_id')}:{item.get('reason')}"
        records.append(
            record(
                "rejected_bets",
                key,
                item,
                run_id=run_id,
                observed_at=now,
                quality="BLOCKED",
                provenance=str(item.get("origin", "NO OUTPUT")),
            )
        )
    for item in read_jsonl(state / "scheduler" / "windows.jsonl"):
        key = f"{item.get('fixture_id')}:{item.get('window')}"
        records.append(
            record(
                "scheduler_windows",
                key,
                item,
                run_id=run_id,
                observed_at=now,
                provider=str(item.get("provider", "the-odds-api")),
                quality=str(item.get("quality_status", "OBSERVED")),
            )
        )
    health = read_json(state / "health" / "latest.json", {})
    if isinstance(health, dict) and health:
        records.append(
            record(
                "quality_runs",
                str(health.get("generated_at", run_id)),
                health,
                run_id=run_id,
                observed_at=iso(health.get("generated_at"), now),
                quality=str(health.get("status", "UNKNOWN")),
            )
        )
    records.append(
        record(
            "quota_usage",
            run_id,
            {
                "quota_used": run.get("quota_used", 0),
                "quota_remaining": run.get("quota_remaining"),
                "budget_level": run.get("budget_level", "NORMAL"),
            },
            run_id=run_id,
            observed_at=now,
            provider=str(run.get("provider", "internal")),
        )
    )
    for item in read_jsonl(state / "burn-in" / "daily.jsonl"):
        records.append(
            record(
                "burn_in_daily_metrics",
                str(item.get("date")),
                item,
                run_id=run_id,
                observed_at=now,
                quality=str(item.get("health_status", "INSUFFICIENT_OBSERVATION")),
            )
        )
    for item in read_jsonl(state / "incidents" / "history.jsonl"):
        records.append(
            record(
                "pipeline_incidents",
                str(item.get("incident_id") or item.get("incident_code")),
                item,
                run_id=run_id,
                observed_at=iso(item.get("started_at"), now),
                quality=str(item.get("severity", "INFO")),
            )
        )
    return records


def _all_snapshots(root: Path) -> Iterable[dict[str, object]]:
    for path in sorted(root.rglob("odds-snapshots.jsonl")):
        yield from read_jsonl(path)


def stage(state: Path, outbox: Path, current_run_id: str | None) -> dict[str, object]:
    run = latest_run(state, current_run_id)
    run_id = str(run["run_id"])
    started_at = run.get("started_at") or run.get("finished_at") or datetime.now(UTC).isoformat()
    run = {
        **run,
        "run_id": run_id,
        "started_at": started_at,
        "source_version": os.getenv("GITHUB_SHA", "local"),
        "durable_status": "DURABLE_WRITE_STAGED",
    }
    partition = iso(run.get("finished_at"), datetime.now(UTC)).strftime("%Y/%m/%d")
    bundle_path = outbox / "bundles" / partition / f"{run_id}.json.gz"
    manifest = write_bundle(
        bundle_path,
        run=run,
        records=state_records(state, run),
    )
    objects: list[dict[str, object]] = []
    raw_root = state / "raw"
    for observation_path in sorted((raw_root / "observations").rglob("*.json")):
        observation = read_json(observation_path, {})
        if not isinstance(observation, dict):
            continue
        payload_hash = str(observation.get("payload_hash", ""))
        location = str(observation.get("raw_payload_location", ""))
        payload_path = raw_root / "payloads" / location
        if not payload_hash or not payload_path.exists():
            continue
        if hashlib.sha256(payload_path.read_bytes()).hexdigest() != payload_hash:
            raise RuntimeError(f"hash brut invalide: {payload_hash}")
        object_path = outbox / "objects" / payload_hash[:2] / f"{payload_hash}.bin.gz"
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            with gzip.open(object_path, "wb", compresslevel=9) as stream:
                stream.write(payload_path.read_bytes())
        objects.append(
            {
                "content_hash": payload_hash,
                "provider": observation.get("provider"),
                "schema_version": observation.get("schema_version"),
                "observed_at": observation.get("received_at"),
                "relative_path": object_path.relative_to(outbox).as_posix(),
                "bytes": payload_path.stat().st_size,
            }
        )
    manifest["objects"] = objects
    manifest["run_id"] = run_id
    manifest_path = bundle_path.with_suffix("").with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "DURABLE_WRITE_STAGED",
        "run_id": run_id,
        "bundle": bundle_path.as_posix(),
        "records": manifest["records"],
        "objects": len(objects),
    }


def append_bridge(outbox: Path, registry: Path) -> dict[str, object]:
    registry.mkdir(parents=True, exist_ok=True)
    index_path = registry / "manifests" / "index.jsonl"
    known = {
        str(item.get("compressed_hash"))
        for item in read_jsonl(index_path)
    }
    appended = objects_added = duplicates = 0
    index_path.parent.mkdir(parents=True, exist_ok=True)
    for manifest_path in sorted(outbox.rglob("*.manifest.json")):
        manifest = read_json(manifest_path, {})
        if not isinstance(manifest, dict):
            continue
        compressed_hash = str(manifest["compressed_hash"])
        bundle_candidates = list(manifest_path.parent.glob(f"{manifest['run_id']}.json.gz"))
        if len(bundle_candidates) != 1:
            raise RuntimeError(f"bundle introuvable pour {manifest_path}")
        bundle_path = bundle_candidates[0]
        if hashlib.sha256(bundle_path.read_bytes()).hexdigest() != compressed_hash:
            raise RuntimeError("hash compressé du bundle invalide")
        if compressed_hash in known:
            duplicates += 1
            continue
        relative = bundle_path.relative_to(outbox)
        target = registry / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle_path, target)
        for object_meta in manifest.get("objects", []):
            if not isinstance(object_meta, dict):
                continue
            source = outbox / str(object_meta["relative_path"])
            destination = registry / str(object_meta["relative_path"])
            if destination.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            objects_added += 1
        manifest["registry_bundle"] = relative.as_posix()
        with index_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
        known.add(compressed_hash)
        appended += 1
    return {
        "status": "DURABLE_BRIDGE_CONFIRMED",
        "bundles_appended": appended,
        "duplicates": duplicates,
        "objects_added": objects_added,
    }


def verify_registry(registry: Path) -> dict[str, object]:
    manifests = read_jsonl(registry / "manifests" / "index.jsonl")
    bundles = objects = 0
    errors: list[str] = []
    for manifest in manifests:
        bundle = registry / str(manifest.get("registry_bundle", ""))
        if not bundle.exists():
            errors.append(f"bundle absent: {bundle}")
            continue
        if hashlib.sha256(bundle.read_bytes()).hexdigest() != manifest.get("compressed_hash"):
            errors.append(f"bundle corrompu: {bundle}")
            continue
        read_bundle(bundle)
        bundles += 1
        for object_meta in manifest.get("objects", []):
            if not isinstance(object_meta, dict):
                continue
            path = registry / str(object_meta["relative_path"])
            if not path.exists():
                errors.append(f"objet absent: {path}")
                continue
            with gzip.open(path, "rb") as stream:
                raw = stream.read()
            if hashlib.sha256(raw).hexdigest() != object_meta["content_hash"]:
                errors.append(f"objet corrompu: {path}")
                continue
            objects += 1
    return {
        "status": "PASSED" if not errors else "FAILED",
        "bundles": bundles,
        "objects_verified": objects,
        "errors": errors,
    }


def persist(outbox: Path, database_url: str) -> dict[str, int]:
    engine = build_engine(database_url)
    registry = DurableRegistry(engine)
    totals = {"inserted": 0, "duplicates": 0, "raw_payloads": 0}
    for bundle_path in sorted(outbox.rglob("*.json.gz")):
        if "objects" in bundle_path.parts:
            continue
        result = registry.replay(read_bundle(bundle_path))
        totals["inserted"] += result["inserted"]
        totals["duplicates"] += result["duplicates"]
    for manifest_path in sorted(outbox.rglob("*.manifest.json")):
        manifest = read_json(manifest_path, {})
        for item in manifest.get("objects", []):
            if not isinstance(item, dict):
                continue
            added = registry.append_raw_payload(
                payload_hash=str(item["content_hash"]),
                provider=str(item.get("provider") or "unknown"),
                object_location=str(item["relative_path"]),
                byte_size=int(item["bytes"]),
                observed_at=iso(item.get("observed_at"), datetime.now(UTC)),
                schema_version=str(item.get("schema_version") or "unknown"),
            )
            totals["raw_payloads"] += int(added)
    return totals


def replay_to_directory(registry: Path, destination: Path) -> dict[str, object]:
    verification = verify_registry(registry)
    if verification["status"] != "PASSED":
        raise RuntimeError("registre durable invalide, replay bloqué")
    bundles_replayed = objects_replayed = 0
    for manifest in read_jsonl(registry / "manifests" / "index.jsonl"):
        bundle = registry / str(manifest["registry_bundle"])
        target = destination / "bundles" / bundle.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle, target)
        bundles_replayed += 1
        for item in manifest.get("objects", []):
            if not isinstance(item, dict):
                continue
            source = registry / str(item["relative_path"])
            raw_target = destination / "raw" / "payloads" / str(item["content_hash"])[:2] / (
                f"{item['content_hash']}.bin"
            )
            raw_target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(source, "rb") as stream:
                raw_target.write_bytes(stream.read())
            objects_replayed += 1
    return {
        "status": "REPLAY_CONFIRMED",
        "provider_calls": 0,
        "quota_consumed": 0,
        "bundles_replayed": bundles_replayed,
        "objects_replayed": objects_replayed,
    }


def acknowledge(state: Path, *, backend: str, commit: str | None) -> dict[str, object]:
    ack = {
        "status": "DURABLE_WRITE_CONFIRMED",
        "backend": backend,
        "commit": commit,
        "confirmed_at": datetime.now(UTC).isoformat(),
    }
    path = state / "durable" / "last-ack.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ack, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return ack


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage_parser = subparsers.add_parser("stage")
    stage_parser.add_argument("--state", type=Path, required=True)
    stage_parser.add_argument("--outbox", type=Path, required=True)
    stage_parser.add_argument("--current-run-id")
    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--outbox", type=Path, required=True)
    append_parser.add_argument("--registry", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--registry", type=Path, required=True)
    persist_parser = subparsers.add_parser("persist")
    persist_parser.add_argument("--outbox", type=Path, required=True)
    persist_parser.add_argument("--database-url", default=os.getenv("ROBIN_DATABASE_URL"))
    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--registry", type=Path, required=True)
    replay_parser.add_argument("--destination", type=Path, required=True)
    ack_parser = subparsers.add_parser("ack")
    ack_parser.add_argument("--state", type=Path, required=True)
    ack_parser.add_argument("--backend", required=True)
    ack_parser.add_argument("--commit")
    args = parser.parse_args()
    if args.command == "stage":
        result = stage(args.state, args.outbox, args.current_run_id)
    elif args.command == "append":
        result = append_bridge(args.outbox, args.registry)
    elif args.command == "verify":
        result = verify_registry(args.registry)
    elif args.command == "persist":
        if not args.database_url:
            raise SystemExit("ROBIN_DATABASE_URL absente")
        result = persist(args.outbox, args.database_url)
    elif args.command == "replay":
        result = replay_to_directory(args.registry, args.destination)
    else:
        result = acknowledge(
            args.state,
            backend=args.backend,
            commit=args.commit,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
