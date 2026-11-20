"""Execute or validate only the independently reviewed finite group campaign."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.roster_campaign import (
    run_slot,
    validate_packet,
    validate_registration,
)

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--canary", action="store_true")
parser.add_argument("--validate-only", action="store_true")
parser.add_argument("--validate-registration", action="store_true")
args = parser.parse_args()
if args.validate_registration:
    print(json.dumps(validate_registration(args.directory, for_install=True)))
elif args.validate_only:
    plan, _ = validate_packet(args.directory)
    print(json.dumps(dict(status="valid", missionId=plan["id"])))
else:
    print(json.dumps(run_slot(args.directory, canary=args.canary)))
