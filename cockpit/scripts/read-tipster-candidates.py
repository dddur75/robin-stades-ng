"""Read documentary candidates without contacting their sources."""

import argparse
import json
from pathlib import Path

from robin.source_observatory.candidate_registry import load_registry
from robin.source_observatory.olbg_store import read_olbg_companion
from robin.source_observatory.qualification_view import (
    APPROVED_ASSESSMENT_SHA,
    apply_qualification,
    read_sro_companion,
)
from robin.source_observatory.technical_access import (
    APPROVED_TECHNICAL_SHA256,
    apply_technical_access,
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
        combined, _, olbg_operational = read_olbg_companion(
            personal or dict(picks=[], claimId="DOCUMENTARY_ONLY"),
            root / "tipsters-olbg-e1-20261119",
            root / "tipsters-olbg-recurring-20261119-v2",
        )
        base = apply_qualification(
            base,
            root / "tipsters-qualification317-20261119",
            expected_sha256=APPROVED_ASSESSMENT_SHA,
            public_data=combined,
            operational=operational,
            operational_by_source={"SRC_039": operational, "SRC_014": olbg_operational},
        )
        try:
            base = apply_technical_access(
                base,
                Path(__file__).resolve().parents[2]
                / "reports/source_observatory/TIPSTERS-TECHNICAL-ACCESS-20261119.json",
                APPROVED_TECHNICAL_SHA256,
            )
        except (OSError, ValueError, KeyError, TypeError):
            base["qualification"]["technicalOverlayState"] = "unavailable"
    except (ValueError, OSError, KeyError, TypeError):
        base["qualification"] = dict(status="unavailable")
    print(json.dumps(base, ensure_ascii=False))
except (ValueError, OSError, KeyError, TypeError):
    print(
        json.dumps(
            {"status": "unavailable", "message": "Registre des candidats absent ou invalide."}
        )
    )
