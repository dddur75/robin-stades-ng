"""Expose accepted public-post facts locally, without network or mutation."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.campaign_view import read_public_view
from robin.source_observatory.expansion_view import add_public_expansion
from robin.source_observatory.family_collection import add_family_public
from robin.source_observatory.legacy_bridge import read_legacy_snapshot
from robin.source_observatory.olbg_store import read_olbg_companion
from robin.source_observatory.personal_access import add_personal_public
from robin.source_observatory.profile_collection import add_profile_public
from robin.source_observatory.qualification_view import read_sro_companion

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--campaign-directory", type=Path, required=True)
args = parser.parse_args()


def read_local_base() -> dict:
    view = read_public_view(args.directory, args.campaign_directory)
    view, _, _ = read_sro_companion(
        view, Path(__file__).resolve().parents[1] / ".ci/tipsters-sro-recurring-20261119-v4"
    )
    root = Path(__file__).resolve().parents[1] / ".ci"
    view, _, _ = read_olbg_companion(
        view, root / "tipsters-olbg-e1-20261119", root / "tipsters-olbg-recurring-20261119-v2"
    )
    view = add_public_expansion(view, Path(__file__).resolve().parents[2])
    view = add_personal_public(view, Path(__file__).resolve().parents[2])
    return view


try:
    view = read_legacy_snapshot(
        "read-public-tipsters.py",
        ["--directory", str(args.directory), "--campaign-directory", str(args.campaign_directory)],
    )
    if view is None:
        view = read_local_base()
    view = add_family_public(view, Path(__file__).resolve().parents[2])
    view = add_profile_public(view, Path(__file__).resolve().parents[2])
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
