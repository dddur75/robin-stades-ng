"""Import verified documentary CSV locally. No network or source activation."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.candidate_registry import import_candidates

p = argparse.ArgumentParser()
p.add_argument("--source", type=Path, required=True)
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--workbook-sha256", required=True)
a = p.parse_args()
print(
    json.dumps(import_candidates(a.source, a.directory, source_workbook_sha256=a.workbook_sha256))
)
