"""Read documentary candidates without contacting their sources."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.candidate_registry import load_registry
from robin.source_observatory.qualification_view import (
    APPROVED_ASSESSMENT_SHA,
    apply_qualification,
    read_sro_companion,
)

p = argparse.ArgumentParser()
p.add_argument("--directory", type=Path, required=True)
a = p.parse_args()
try:
    base = load_registry(a.directory)
    root = Path(__file__).resolve().parents[1] / ".ci"
    try:
        _, personal, operational = read_sro_companion(
            dict(picks=[], claimId="DOCUMENTARY_ONLY"), root / "tipsters-sro-recurring-20261119-v4"
        )
        base = apply_qualification(
            base,
            root / "tipsters-qualification317-20261119",
            expected_sha256=APPROVED_ASSESSMENT_SHA,
            public_data=personal,
            operational=operational,
        )
    except (ValueError, OSError, KeyError, TypeError):
        base["qualification"] = dict(status="unavailable")
    print(json.dumps(base, ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(
        json.dumps(
            {"status": "unavailable", "message": "Registre des candidats absent ou invalide."}
        )
    )
