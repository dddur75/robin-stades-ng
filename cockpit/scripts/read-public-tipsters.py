"""Expose accepted public-post facts locally, without network or mutation."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.campaign_view import read_public_view
from robin.source_observatory.qualification_view import read_sro_companion

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--campaign-directory", type=Path, required=True)
args = parser.parse_args()
try:
    view = read_public_view(args.directory, args.campaign_directory)
    view, _, _ = read_sro_companion(
        view, Path(__file__).resolve().parents[1] / ".ci/tipsters-sro-recurring-20261119-v4"
    )
    print(json.dumps(view, ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(
        json.dumps(
            {
                "status": "unavailable",
                "message": "Preuves de collecte publique absentes ou invalides.",
            }
        )
    )
