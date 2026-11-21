"""Bounded read of the complete local documentary index, without publisher traffic."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.workbook_inventory import (
    APPROVED_INDEX_SHA256,
    load_inventory,
    query_inventory,
)

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--query", default="{}")
a = p.parse_args()
try:
    data = load_inventory(
        a.directory, expected_sha256=APPROVED_INDEX_SHA256, filename="index-v2.json"
    )
    result = query_inventory(data, **json.loads(a.query))
    result["receipt"]["indexSha256"] = APPROVED_INDEX_SHA256
    print(json.dumps(result, ensure_ascii=False))
except (OSError, ValueError, KeyError, TypeError):
    print(
        json.dumps(
            {
                "status": "unavailable",
                "message": "Index complet absent ou invalide ; les fiches Ligue 1 restent accessibles séparément.",
            }
        )
    )
