"""Build frozen J10 match evidence from local cache or pinned Git blobs."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from robin.hypothesis_evidence.contracts import (
    AUTHORITATIVE_HISTORICAL_REVISION,
    EvidenceBuildConfig,
)
from robin.hypothesis_evidence.factory import build_hypothesis_evidence
from robin.hypothesis_evidence.runtime import process_peak_memory_bytes

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXTRACTED_ROOT = ROOT / "artifacts" / "j10-frozen-reference" / "historical"
DEFAULT_OUTPUT = ROOT / "artifacts" / "hypothesis-evidence"
DEFAULT_REPORTS = ROOT / "reports" / "hypothesis-evidence"
DEFAULT_REGISTRY = ROOT / ".ci" / "hypothesis-j10" / "hypothesis-registry.jsonl"
DEFAULT_FULL_CAMPAIGN = ROOT / ".ci" / "hypothesis-j10" / "campaign-summary.json"
DEFAULT_COMPACT_CAMPAIGN = (
    ROOT / "reports" / "pattern-research" / "campaign-summary.json"
)


def _write_run_metrics(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Reconstruct all 700 frozen J10 rule memberships without network, "
            "providers, R2 or database writes."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--historical-root", type=Path)
    parser.add_argument(
        "--git-blobs",
        action="store_true",
        help="Read pinned commit blobs even when the extracted cache exists.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--full-campaign",
        type=Path,
        default=DEFAULT_FULL_CAMPAIGN,
    )
    parser.add_argument(
        "--compact-campaign",
        type=Path,
        default=DEFAULT_COMPACT_CAMPAIGN,
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--stop-after-batches",
        type=int,
        help="Test-only interruption hook; checkpoint remains resumable.",
    )
    args = parser.parse_args()

    historical_root: Path | None
    if args.git_blobs:
        historical_root = None
    elif args.historical_root is not None:
        historical_root = args.historical_root.resolve()
    elif DEFAULT_EXTRACTED_ROOT.is_dir():
        historical_root = DEFAULT_EXTRACTED_ROOT
    else:
        historical_root = None

    started = time.perf_counter()
    result = build_hypothesis_evidence(
        EvidenceBuildConfig(
            repo_root=args.repo_root.resolve(),
            historical_root=historical_root,
            output_root=args.output.resolve(),
            report_root=args.reports.resolve(),
            registry_path=args.registry.resolve(),
            full_campaign_path=args.full_campaign.resolve(),
            compact_campaign_path=args.compact_campaign.resolve(),
            historical_revision=AUTHORITATIVE_HISTORICAL_REVISION,
            batch_size=args.batch_size,
            resume=not args.no_resume,
            stop_after_batches=args.stop_after_batches,
        )
    )
    duration_seconds = time.perf_counter() - started
    memory_peak_bytes, memory_measurement = process_peak_memory_bytes()
    parquet_paths = sorted(args.output.resolve().glob("*.parquet"))
    parquet_bytes = {
        path.name: path.stat().st_size for path in parquet_paths
    }
    payload = {
        "schema_version": "j10-hypothesis-evidence-run-metrics-v1",
        "status": result.status,
        "historical_data_revision": AUTHORITATIVE_HISTORICAL_REVISION,
        "replay_hash": result.replay_hash,
        "fixture_rows": result.fixture_rows,
        "unique_matches": result.fixture_rows,
        "membership_rows": result.membership_rows,
        "memberships_created": result.membership_rows,
        "summary_rows": result.summary_rows,
        "hypotheses_processed": result.summary_rows,
        "completed_batches": result.completed_batches,
        "duration_seconds": duration_seconds,
        "processing_time_seconds": duration_seconds,
        "memory_peak_bytes": memory_peak_bytes,
        "memory_measurement": memory_measurement,
        "parquet_bytes": parquet_bytes,
        "bytes_parquet": sum(parquet_bytes.values()),
        "provider_calls": 0,
        "network_calls": 0,
        "r2_operations": 0,
        "database_writes": 0,
        "temporary_database_rows": 0,
        "postgresql_rows": 0,
    }
    _write_run_metrics(args.output.resolve() / "run-metrics.json", payload)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
