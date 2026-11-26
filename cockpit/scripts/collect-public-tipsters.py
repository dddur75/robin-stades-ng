"""Run at most one authorized, due forum slot; no catch-up or implicit grant."""
import argparse
import json
from pathlib import Path

from robin.source_observatory.public_campaign import run_slot, validate_campaign

parser=argparse.ArgumentParser()
parser.add_argument('--directory',type=Path,required=True)
parser.add_argument('--validate-only',action='store_true')
args=parser.parse_args()
if args.validate_only:
    validate_campaign(args.directory)
    print(json.dumps({'state':'validated','requests':0}))
else:
    print(json.dumps(run_slot(args.directory)))
