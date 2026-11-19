import json
from hashlib import sha256

import pytest

from robin.source_observatory.technical_access import apply_technical_access


def test_current_access_preserves_initial_assessment_and_personal_scope(tmp_path):
    access = dict(
        platform="OLBG",
        label="Personal adapter ready",
        reason="One profile proved; others unproved",
        requiredAccess="Individual proof required",
        ownerAction="Private campaign only",
        observedAt="2026-11-19T18:00:00Z",
        status="partially_qualified",
        evidenceRefs=["SYNTHETIC"],
    )
    base = dict(
        qualification=dict(platforms=[dict(platform="OLBG", label="Initial unresolved")]),
        candidates=[
            dict(
                platform="OLBG",
                collectionEnabled=False,
                qualification=dict(
                    label="Initial unresolved", profileVisited=False, personallyProven=True
                ),
            ),
            dict(
                platform="OLBG",
                collectionEnabled=False,
                qualification=dict(
                    label="Initial unresolved", profileVisited=False, personallyProven=False
                ),
            ),
        ],
    )
    path = tmp_path / "report.json"
    raw = json.dumps(
        dict(
            schemaVersion="robin-source-technical-access-v1",
            claimId="SYNTHETIC",
            platforms=[access],
        )
    ).encode()
    path.write_bytes(raw)
    data = apply_technical_access(base, path, sha256(raw).hexdigest())
    assert data["candidates"][0]["qualification"]["profileVisited"]
    assert not data["candidates"][1]["qualification"]["profileVisited"]
    assert (
        data["candidates"][0]["qualification"]["initialAssessment"]["label"] == "Initial unresolved"
    )
    assert all(not r["collectionEnabled"] for r in data["candidates"])
    assert base["candidates"][0]["qualification"]["label"] == "Initial unresolved"
    with pytest.raises(ValueError):
        apply_technical_access(base, path, "0" * 64)
