"""One explicit SRO slot; no automatic grant or catch-up."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.sro_campaign import run_sro_slot, validate_sro_campaign

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--validate-only", action="store_true")
a = p.parse_args()
if a.validate_only:
    validate_sro_campaign(a.directory)
    print(json.dumps(dict(state="validated", requests=0)))
else:
    print(json.dumps(run_sro_slot(a.directory)))
