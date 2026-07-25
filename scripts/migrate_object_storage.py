"""Migration progressive vers un stockage S3/R2, sans suppression de source."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
from typing import Any, cast

from robin.historical.critical_closure import ObjectStorageAdapter, S3CompatibleClient
from robin.historical.storage import write_json_atomic


def required_secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("data/historical"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-files", type=int, default=100)
    args = parser.parse_args()
    files = sorted(path for path in args.state.rglob("*") if path.is_file())
    report: dict[str, object] = {
        "mode": "EXECUTE" if args.execute else "DRY_RUN",
        "files_examined": len(files),
        "bytes_examined": sum(path.stat().st_size for path in files),
        "uploaded": 0,
        "replayed": 0,
        "hash_mismatches": 0,
        "deletions": 0,
        "double_write": True,
    }
    if args.execute:
        account = required_secret("R2_ACCOUNT_ID")
        access_key = required_secret("R2_ACCESS_KEY_ID")
        secret_key = required_secret("R2_SECRET_ACCESS_KEY")
        bucket = required_secret("R2_BUCKET_NAME")
        boto3 = importlib.import_module("boto3")
        client: Any = boto3.client(
            "s3",
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        adapter = ObjectStorageAdapter(cast(S3CompatibleClient, client), bucket)
        for path in files[: max(args.max_files, 0)]:
            key = path.relative_to(args.state).as_posix()
            outcome = adapter.upload(key, path.read_bytes())
            if outcome["uploaded"]:
                report["uploaded"] = int(report["uploaded"]) + 1
            else:
                report["replayed"] = int(report["replayed"]) + 1
    write_json_atomic(args.state / "storage" / "r2-migration-latest.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
