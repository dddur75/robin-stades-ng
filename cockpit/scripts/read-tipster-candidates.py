"""Read documentary candidates without contacting their sources."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.candidate_registry import load_registry

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
a = p.parse_args()
try:
    print(json.dumps(load_registry(a.directory), ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(
        json.dumps(
            {"status": "unavailable", "message": "Registre des candidats absent ou invalide."}
        )
    )
