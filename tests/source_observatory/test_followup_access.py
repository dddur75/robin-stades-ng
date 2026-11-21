import json
from copy import deepcopy
from hashlib import sha256

import pytest

from robin.source_observatory.followup_access import apply_followup_access
from robin.source_observatory.technical_access import apply_technical_access


def fixture():
    def access(platform):
        return dict(
            platform=platform,
            label="Previous",
            reason="Previous reason",
            requiredAccess="Previous access",
            ownerAction="Previous action",
            observedAt="2026-11-19T18:00:00Z",
            status="unverified",
            evidenceRefs=["OLD"],
            technicalClaimId="OLD",
            initialAssessment={"label": "Original"},
        )

    return dict(
        qualification=dict(
            status="ok",
            technicalClaimId="OLD",
            qualifiedCount=5,
            platforms=[
                access(p) for p in ["NotBetting", "Telegram", "OLBG", "Kicktipp", "Stavka.tv"]
            ],
        ),
        enabledCount=5,
        candidates=[
            dict(
                platform=p,
                collectionEnabled=p == "OLBG",
                qualification={
                    **access(p),
                    "profileVisited": p == "NotBetting",
                    "personallyProven": p == "OLBG",
                    "picks": [{"id": "old-proof"}] if p == "OLBG" else [],
                },
            )
            for p in ["NotBetting", "Telegram", "OLBG", "Kicktipp", "Stavka.tv"]
        ],
    )


def report(path):
    rows = [
        dict(
            platform=p,
            label="Access blocked",
            reason="Real measured reason",
            requiredAccess="Official permission",
            ownerAction="Official source document",
            observedAt="2026-11-20T06:56:00Z",
            status="blocked",
            evidenceRefs=["NEW"],
        )
        for p in ["NotBetting", "Telegram"]
    ]
    raw = json.dumps(
        dict(schemaVersion="robin-nt-qualification-v1", claimId="NEW", platforms=rows)
    ).encode()
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def test_partial_followup_preserves_original_personal_facts_other_platforms_and_counts(tmp_path):
    base = fixture()
    unchanged = deepcopy(base)
    path = tmp_path / "report.json"
    pin = report(path)
    result = apply_followup_access(base, path, pin)
    assert base == unchanged
    assert result["qualification"]["qualifiedCount"] == 5 and result["enabledCount"] == 5
    assert result["qualification"]["technicalClaimIds"] == ["OLD", "NEW"]
    for before, after in zip(base["candidates"], result["candidates"], strict=True):
        assert after["collectionEnabled"] == before["collectionEnabled"]
        for field in ["initialAssessment", "profileVisited", "personallyProven", "picks"]:
            assert after["qualification"][field] == before["qualification"][field]
        if before["platform"] not in ["NotBetting", "Telegram"]:
            assert after == before
        else:
            assert after["qualification"]["technicalClaimId"] == "NEW"
            assert (
                after["qualification"]["previousTechnicalAssessment"]["technicalClaimId"] == "OLD"
            )
            assert "initialAssessment" not in after["qualification"]["previousTechnicalAssessment"]
    for before, after in zip(
        base["qualification"]["platforms"], result["qualification"]["platforms"], strict=True
    ):
        if before["platform"] not in ["NotBetting", "Telegram"]:
            assert after == before
        else:
            assert (
                after["initialAssessment"] == before["initialAssessment"]
                and after["previousTechnicalAssessment"]["technicalClaimId"] == "OLD"
            )


def test_followup_is_idempotent(tmp_path):
    path = tmp_path / "report.json"
    pin = report(path)
    first = apply_followup_access(fixture(), path, pin)
    assert apply_followup_access(first, path, pin) == first


def test_bad_or_missing_evidence_does_not_mutate_base(tmp_path):
    base = fixture()
    original = deepcopy(base)
    path = tmp_path / "report.json"
    report(path)
    with pytest.raises(ValueError):
        apply_followup_access(base, path, "0" * 64)
    with pytest.raises(OSError):
        apply_followup_access(base, tmp_path / "missing.json", "0" * 64)
    assert base == original


def test_report_must_contain_exactly_the_two_reviewed_platforms(tmp_path):
    path = tmp_path / "report.json"
    report(path)
    data = json.loads(path.read_bytes())
    data["platforms"].pop()
    raw = json.dumps(data).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        apply_followup_access(fixture(), path, sha256(raw).hexdigest())


def test_documentary_then_old_then_new_layer_preserves_both_histories(tmp_path):
    base = fixture()
    base["qualification"].pop("technicalClaimId")
    for item in base["qualification"]["platforms"] + [
        r["qualification"] for r in base["candidates"]
    ]:
        item.pop("initialAssessment")
        item.pop("technicalClaimId")
        item["label"] = "Original documentary assessment"
    rows = fixture()["qualification"]["platforms"]
    old_raw = json.dumps(
        dict(schemaVersion="robin-source-technical-access-v1", claimId="OLD", platforms=rows)
    ).encode()
    old_path = tmp_path / "old.json"
    old_path.write_bytes(old_raw)
    previous = apply_technical_access(base, old_path, sha256(old_raw).hexdigest())
    path = tmp_path / "new.json"
    result = apply_followup_access(previous, path, report(path))
    assert previous["qualification"]["technicalClaimId"] == "OLD"
    for before, after in zip(previous["candidates"], result["candidates"], strict=True):
        assert (
            before["qualification"]["initialAssessment"]
            == after["qualification"]["initialAssessment"]
        )
        assert before["qualification"]["picks"] == after["qualification"]["picks"]
    assert base["candidates"][0]["qualification"]["label"] == "Original documentary assessment"
