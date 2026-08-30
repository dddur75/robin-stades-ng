"""Run the one-shot DATA TORRENT READY V1 cloud batch."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from robin.chronos_production import ChronosProductionError
from robin.data_torrent.runtime import DataTorrentRuntimeError, execute_data_torrent

ROOT = Path(__file__).resolve().parents[1]


def _zero_effects() -> dict[str, Any]:
    return {
        "schema_version": "robin-data-torrent-live-runtime-effects-v1",
        "accounting_status": "COMPLETE_CONSERVATIVE",
        "postgresql": {
            "read_transactions_attempted": 0,
            "function_reads_attempted": 0,
            "mutating_function_calls_attempted": 0,
            "mutating_function_calls_completed": 0,
            "mutating_function_outcomes_ambiguous": 0,
            "possible_durable_mutations_upper_bound": 0,
            "connection_attempts_upper_bound": 0,
            "automatic_retries": 0,
        },
        "official": {"physical_reads_attempted": 0, "automatic_retries": 0},
        "odds": {
            "dns_resolutions_attempted": 0,
            "provider_requests_attempted": 0,
            "credits_used_upper_bound": 0,
            "automatic_retries": 0,
        },
        "r2": {
            "puts_attempted": 0,
            "gets_attempted": 0,
            "lists_attempted": 0,
            "deletes_attempted": 0,
            "put_outcomes_ambiguous_upper_bound": 0,
            "automatic_retries": 0,
        },
    }


def _write_failure(
    output_dir: Path,
    code: str,
    *,
    effects: Mapping[str, Any] | None = None,
) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "torrent-run-failure-v1.json"
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    {
                        "schema_version": "robin-data-torrent-run-failure-v1",
                        "status": "FAILED",
                        "error_code": code,
                        "effects": dict(effects) if effects is not None else _zero_effects(),
                        "secret_values_observed": False,  # nosec B105 - audit boolean.
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    except OSError:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "data" / "torrent-live-v1.json",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = execute_data_torrent(
            repository_root=ROOT,
            config_path=args.config,
            output_dir=args.output_dir,
        )
    except (ChronosProductionError, DataTorrentRuntimeError, ValueError) as error:
        code = str(error)
        _write_failure(
            args.output_dir,
            code,
            effects=getattr(error, "effect_receipt", None),
        )
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    except Exception as error:
        code = "DATA_TORRENT_UNCLASSIFIED_FAILURE"
        _write_failure(
            args.output_dir,
            code,
            effects=getattr(error, "effect_receipt", None),
        )
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    if result.get("data_torrent_ready") is not True:
        code = "DATA_TORRENT_LOSER_ZERO_EFFECTS"
        observed_effects = result.get("runtime_effects")
        _write_failure(
            args.output_dir,
            code,
            effects=observed_effects if isinstance(observed_effects, Mapping) else None,
        )
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
