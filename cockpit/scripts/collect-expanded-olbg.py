"""Run the separately authorized one-author expansion canary or due slot."""

import argparse
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from robin.source_observatory.expanded_olbg_campaign import run_slot, validate

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
p.add_argument("--canary", action="store_true")
p.add_argument("--validate-only", action="store_true")
a = p.parse_args()
validate(a.directory)
if a.validate_only:
    print(json.dumps({"state": "validated", "requests": 0}))
else:
    path = (
        Path(__file__).resolve().parents[1]
        / ".ci/tipsters-source-expansion-20261120-v2/transport.py"
    )
    spec = spec_from_file_location("robin_expanded_verified_transport", path)
    if spec is None or spec.loader is None:
        raise ValueError("transport loader unavailable")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    print(json.dumps(run_slot(a.directory, get=module.public_get_verified, canary=a.canary)))
