"""Expose accepted public-post facts locally, without network or mutation."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.campaign_view import read_public_view

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--campaign-directory", type=Path, required=True)
args = parser.parse_args()
try:
    print(json.dumps(read_public_view(args.directory, args.campaign_directory), ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(
        json.dumps(
            {
                "status": "unavailable",
                "message": "Preuves de collecte publique absentes ou invalides.",
            }
        )
    )
