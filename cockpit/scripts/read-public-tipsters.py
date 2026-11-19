"""Expose accepted public-post facts locally, without network or mutation."""
import argparse
import json
from pathlib import Path

from robin.source_observatory.public_collection import read_collection

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, required=True)
args = parser.parse_args()
try:
    print(json.dumps(read_collection(args.directory), ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(json.dumps({'status': 'unavailable', 'message': 'Preuves de collecte publique absentes ou invalides.'}))
