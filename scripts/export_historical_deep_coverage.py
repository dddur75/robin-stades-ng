"""Export a sanitized coverage proof from an explicit historical-deep lineage."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from robin.historical_deep.contracts import load_campaign_contract
from robin.historical_deep.coverage_proof import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DerivedR2ReadOnlyStore,
    build_coverage_proof,
    write_coverage_artifacts,
)

DEFAULT_CONFIG = Path("configs/historical-deep-data-harvest-v1.json")
DEFAULT_OUTPUT = Path("artifacts/historical-deep-coverage-proof")
_R2_SECRET_NAMES = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)


def _environment_guard(environment: Mapping[str, str]) -> None:
    if environment.get("API_FOOTBALL_KEY", "").strip():
        raise RuntimeError("COVERAGE_PROOF_API_FOOTBALL_KEY_MUST_NOT_BE_MOUNTED")
    if environment.get("API_FOOTBALL_CALLS_ALLOWED", "").strip() != "0":
        raise RuntimeError("COVERAGE_PROOF_PROVIDER_CALLS_MUST_BE_ZERO")
    if environment.get("ODDS_API_CREDITS_ALLOWED", "").strip() != "0":
        raise RuntimeError("COVERAGE_PROOF_ODDS_CREDITS_MUST_BE_ZERO")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-code-revision", required=True)
    parser.add_argument("--source-run-token", required=True)
    parser.add_argument("--exporter-code-revision", required=True)
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        default=DEFAULT_MAX_OUTPUT_BYTES,
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    selected_environment = dict(os.environ if environment is None else environment)
    _environment_guard(selected_environment)
    contract = load_campaign_contract(args.config)
    reader = DerivedR2ReadOnlyStore(selected_environment)
    proof = build_coverage_proof(
        reader,
        contract=contract,
        source_code_revision=args.source_code_revision,
        source_run_token=args.source_run_token,
        exporter_code_revision=args.exporter_code_revision,
    )
    secret_values = tuple(
        selected_environment.get(name, "")
        for name in _R2_SECRET_NAMES
        if selected_environment.get(name, "")
    )
    json_path, csv_path = write_coverage_artifacts(
        proof,
        output_directory=args.output,
        max_output_bytes=args.max_output_bytes,
        secret_values=secret_values,
    )
    print(
        json.dumps(
            {
                "status": "COVERAGE_PROOF_EXPORTED",
                "coverage_count": proof["coverage_count"],
                "proof_hash": proof["proof_hash"],
                "json": json_path.as_posix(),
                "csv": csv_path.as_posix(),
                "provider_calls": 0,
                "r2_writes": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
