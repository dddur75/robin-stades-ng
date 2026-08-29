"""Run the one-shot DATA TORRENT READY V1 cloud batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robin.chronos_production import ChronosProductionError
from robin.data_torrent.runtime import DataTorrentRuntimeError, execute_data_torrent

ROOT = Path(__file__).resolve().parents[1]


def _write_failure(output_dir: Path, code: str) -> None:
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
        _write_failure(args.output_dir, code)
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    except Exception:
        code = "DATA_TORRENT_UNCLASSIFIED_FAILURE"
        _write_failure(args.output_dir, code)
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(1) from None
    if result.get("data_torrent_ready") is not True:
        code = "DATA_TORRENT_LOSER_ZERO_EFFECTS"
        _write_failure(args.output_dir, code)
        print(f"DATA_TORRENT_RUN_FAILED:{code}")
        raise SystemExit(2)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
