#!/usr/bin/env python3
"""Generate a fully synthetic terminal batch for contractual tests only."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from robin.capture import (
    CaptureBudget,
    CaptureHarness,
    CaptureStore,
    FixtureMapping,
    InternalRetentionPolicy,
    ProviderRequestSpec,
    RawPayloadReceipt,
)
from robin.capture.contracts import MappingStatus

BATCH_ID = "SYNTHETIC_FIVE_CANARY_RECEIPT_BATCH_V1"
CAPTURES = (
    ("C0", "H24", datetime(2030, 2, 4, 11, 55, tzinfo=UTC)),
    ("C1", "H12", datetime(2030, 2, 4, 23, 55, tzinfo=UTC)),
    ("C2", "H6", datetime(2030, 2, 5, 5, 55, tzinfo=UTC)),
    ("C3", "H2", datetime(2030, 2, 5, 9, 55, tzinfo=UTC)),
    ("C4", "H1", datetime(2030, 2, 5, 10, 55, tzinfo=UTC)),
)
KICKOFF = datetime(2030, 2, 5, 12, 0, tzinfo=UTC)
PayloadMarketMode = Literal["CONTRACT", "SPREADS_ONLY"]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _pretty(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _events(
    capture_index: int,
    observed: datetime,
    *,
    payload_market_mode: PayloadMarketMode,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event_index in range(5):
        home = f"Synthetic Home {event_index + 1}"
        away = f"Synthetic Away {event_index + 1}"
        bookmakers: list[dict[str, Any]] = []
        for bookmaker_index in range(5):
            market_time = observed - timedelta(seconds=bookmaker_index + 1)
            h2h = {
                "key": "h2h",
                "last_update": _utc(market_time),
                "outcomes": [
                    {"name": home, "price": 101 + capture_index + event_index / 10},
                    {"name": "Draw", "price": 102 + bookmaker_index / 10},
                    {"name": away, "price": 103 + event_index / 10},
                ],
            }
            totals = {
                "key": "totals",
                "last_update": _utc(market_time),
                "outcomes": [
                    {"name": "Over", "point": 2.5, "price": 104 + capture_index / 10},
                    {"name": "Under", "point": 2.5, "price": 105 + bookmaker_index / 10},
                ],
            }
            spreads = {
                "key": "spreads",
                "last_update": _utc(market_time),
                "outcomes": [
                    {"name": home, "point": -1.5, "price": 106 + capture_index / 10},
                    {"name": away, "point": 1.5, "price": 107 + bookmaker_index / 10},
                ],
            }
            bookmakers.append(
                {
                    "key": f"synthetic_bookmaker_{bookmaker_index + 1}",
                    "last_update": _utc(market_time),
                    "markets": ([h2h, totals] if payload_market_mode == "CONTRACT" else [spreads]),
                    "title": f"Synthetic Bookmaker {bookmaker_index + 1}",
                }
            )
        result.append(
            {
                "away_team": away,
                "bookmakers": bookmakers,
                "commence_time": _utc(KICKOFF),
                "home_team": home,
                "id": f"synthetic-event-{event_index + 1:03d}",
                "sport_key": "soccer_synthetic_alpha",
            }
        )
    return result


def generate_batch(root: Path, *, payload_market_mode: PayloadMarketMode = "CONTRACT") -> Path:
    if root.exists() and any(root.iterdir()):
        raise RuntimeError("SYNTHETIC_BATCH_OUTPUT_NOT_EMPTY")
    if payload_market_mode not in {"CONTRACT", "SPREADS_ONLY"}:
        raise RuntimeError("SYNTHETIC_PAYLOAD_MARKET_MODE_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    retention = InternalRetentionPolicy()
    store = CaptureStore(root, retention, approved_local_root=root)
    harness = CaptureHarness(
        store,
        CaptureBudget(maximum_requests=len(CAPTURES), maximum_credits=2 * len(CAPTURES)),
    )
    retention_bytes = _pretty(retention.model_dump(mode="json"))
    retention_path = root / "INTERNAL-MARKET-DATA-RETENTION-POLICY-V1.json"
    retention_path.write_bytes(retention_bytes)
    retention_sha = _sha(retention_bytes)
    windows: list[dict[str, Any]] = []
    capture_manifest_entries: list[dict[str, Any]] = []
    selected_fixtures: list[dict[str, Any]] | None = None
    for capture_index, (label, window, observed) in enumerate(CAPTURES):
        events = _events(
            capture_index,
            observed,
            payload_market_mode=payload_market_mode,
        )
        raw_bytes = _canonical(events)
        mappings = tuple(
            FixtureMapping(
                provider_event_id=str(event["id"]),
                fixture_id=str(event["id"]).replace("event", "fixture"),
                status=MappingStatus.MAPPED,
                candidate_fixture_ids=(str(event["id"]).replace("event", "fixture"),),
                mapping_revision="synthetic-pr59-strict-v1",
            )
            for event in events
        )
        if selected_fixtures is None:
            selected_fixtures = [
                {
                    "away_team": str(event["away_team"]),
                    "fixture_id": mapping.fixture_id,
                    "home_team": str(event["home_team"]),
                    "kickoff_at": str(event["commence_time"]),
                    "provider_event_id": mapping.provider_event_id,
                    "sport_key": str(event["sport_key"]),
                }
                for event, mapping in zip(events, mappings, strict=True)
            ]
        request = ProviderRequestSpec(
            endpoint="/v4/sports/soccer_synthetic_alpha/odds",
            sport_key="soccer_synthetic_alpha",
            markets=("h2h", "totals"),
        )
        ingested = observed + timedelta(seconds=1)
        technical_manifest = harness.record_offline_response(
            request,
            payload=raw_bytes,
            http_status=200,
            response_headers={
                "x-requests-last": "2",
                "x-requests-remaining": str(1000 - (capture_index + 1) * 2),
                "x-requests-used": str((capture_index + 1) * 2),
            },
            mappings=mappings,
            first_observed_at=observed,
            ingested_at=ingested,
        )
        receipt_path = root / "receipts" / f"{technical_manifest.receipt_id}.json"
        receipt = RawPayloadReceipt.model_validate_json(receipt_path.read_bytes())
        capture_manifest_entries.append(
            {
                "capture_label": label,
                "captured_at": _utc(technical_manifest.captured_at),
                "fixture_mappings": [
                    mapping.model_dump(mode="json")
                    for mapping in technical_manifest.fixture_mappings
                ],
                "mapping_revision": "synthetic-pr59-strict-v1",
                "normalized_observation_count": technical_manifest.observation_count,
                "normalized_path": technical_manifest.normalized_storage_key,
                "normalized_sha256": technical_manifest.normalized_sha256,
                "raw_payload_sha256": technical_manifest.raw_payload_sha256,
                "receipt_id": technical_manifest.receipt_id,
                "request_fingerprint_sha256": technical_manifest.request_fingerprint_sha256,
                "robin_first_observed_at": _utc(receipt.robin_first_observed_at),
                "robin_ingested_at": _utc(receipt.robin_ingested_at),
                "schema_fingerprint_sha256": technical_manifest.schema_fingerprint.schema_sha256,
                "snapshot_id": technical_manifest.snapshot_id,
                "window_id": window,
            }
        )
        for event in events:
            cutoff = datetime.fromisoformat(
                str(event["commence_time"]).replace("Z", "+00:00")
            ) - timedelta(hours=int(window[1:]))
            role = "TARGET" if window == "H1" else "PREDICTOR"
            maximum_staleness = timedelta(minutes=120 if window == "H24" else 15)
            windows.append(
                {
                    "capture_label": label,
                    "earliest_admissible": _utc(cutoff - maximum_staleness),
                    "fixture_id": event["id"].replace("event", "fixture"),
                    "kickoff": event["commence_time"],
                    "latest_admissible": _utc(
                        cutoff + timedelta(minutes=5) if role == "TARGET" else cutoff
                    ),
                    "temporal_role": role,
                    "window_id": window,
                }
            )
    manifest = {
        "batch_id": BATCH_ID,
        "capture_code_revision": "828dde735c9104ee033fb199922d115f7b08578e",
        "capture_harness_version": "robin-receipt-capture-harness-v1",
        "capture_windows": windows,
        "captures": capture_manifest_entries,
        "finalized_at": "2030-02-05T12:30:00Z",
        "retention_policy_sha256": retention_sha,
        "selected_fixtures": selected_fixtures,
        "status": "FINALIZED",
    }
    manifest_bytes = _pretty(manifest)
    manifest_path = root / "capture-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    checksum_paths = sorted(path for path in root.rglob("*") if path.is_file())
    checksums = (
        "\n".join(
            f"{_sha(path.read_bytes())}  {path.relative_to(root).as_posix()}"
            for path in checksum_paths
        )
        + "\n"
    )
    (root / "sha256sums.txt").write_text(checksums, encoding="utf-8", newline="\n")
    finalized = {
        "batch_id": BATCH_ID,
        "finalized_at": "2030-02-05T12:30:00Z",
        "manifest_path": "capture-manifest.json",
        "manifest_sha256": _sha(manifest_bytes),
        "sha256sums_path": "sha256sums.txt",
        "status": "FINALIZED",
    }
    # This marker is intentionally generated last.
    (root / "FINALIZED.json").write_bytes(_pretty(finalized))
    return root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generate_batch(args.output.resolve())
    print(json.dumps({"batch_id": BATCH_ID, "status": "SYNTHETIC_FINALIZED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
