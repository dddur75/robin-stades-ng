"""One explicit legacy or opaque OLBG slot; no task or automatic authority."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from robin.source_observatory.olbg_campaign import run_olbg_slot, validate_olbg_campaign


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--opaque", action="store_true")
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--approval-sha")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.opaque:
        if args.approval is not None or args.approval_sha is not None or args.execute:
            parser.error("Opaque options require --opaque")
        if args.validate_only:
            validate_olbg_campaign(args.directory)
            result = dict(state="validated", requests=0)
        else:
            result = run_olbg_slot(args.directory)
    else:
        if args.approval is None or args.approval_sha is None:
            parser.error("Opaque mode requires --approval and --approval-sha")
        if args.execute and args.validate_only:
            parser.error("Choose --execute or --validate-only")
        with args.approval.open("rb") as stream:
            raw = stream.read(32769)
        if not 0 < len(raw) <= 32768 or sha256(raw).hexdigest() != args.approval_sha:
            raise PermissionError("CAMPAIGN_APPROVAL_PIN")
        from robin.source_observatory.olbg_opaque_campaign import (
            run_opaque_slot,
            validate_campaign,
        )
        approval = json.loads(raw)
        validate_campaign(args.directory, approval)
        result = (run_opaque_slot(args.directory, approval=approval) if args.execute
                  else dict(state="VALIDATED_ONLY", requests=0))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
