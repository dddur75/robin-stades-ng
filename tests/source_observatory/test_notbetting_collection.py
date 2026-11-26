import json
from copy import deepcopy
from hashlib import sha256

import pytest

from robin.source_observatory import notbetting_collection
from robin.source_observatory.connectors import canonical
from robin.source_observatory.notbetting_collection import build_choices, merge_public

PICK_ID = "11111111-1111-4111-8111-111111111111"
OWNER_ID = "22222222-2222-4222-8222-222222222222"


def source():
    fields = {
        "id": PICK_ID,
        "tipsterId": OWNER_ID,
        "tipster.user.id": OWNER_ID,
        "tipster.user.tipster.id": OWNER_ID,
        "tipster.user.tipster.userId": OWNER_ID,
        "tipster.user.username": "SyntheticAlias",
        "event": "Home A - Away B",
        "competition": "Premier League",
        "pick": "Literal non-normalized choice",
    }
    times = {"date": "2026-11-21T15:00:00Z", "createdAt": "2026-11-21T00:25:00Z"}
    owner = {
        "tipsterId": OWNER_ID,
        "tipster": {
            k.removeprefix("tipster."): v for k, v in fields.items() if k.startswith("tipster.")
        },
    }
    record = {"nativeFields": fields, "nativeTemporalFields": times, "linkedOwner": owner}
    record["sourceRecordFingerprint"] = sha256(
        canonical(dict(fields=fields, linkedOwner=owner, nativeTemporalFields=times))
    ).hexdigest()
    return {
        "sourceUrl": "https://notbetting.com/en/tipsters-league/picks",
        "baselineObservedAt": "2026-11-21T00:49:00Z",
        "content": {
            "status": 200,
            "observedAt": "2026-11-21T01:30:14Z",
            "responseSha256": "a" * 64,
            "projection": {"records": [record], "conflictingTargetIds": []},
        },
        "targetComparison": [
            {
                "id": PICK_ID,
                "samePreviouslyRetainedNativeFields": True,
                "changedPreviouslyRetainedFieldNames": [],
                "firstSeenAt": "2026-11-21T00:49:00Z",
                "newTemporalEvidenceObservedAt": "2026-11-21T01:30:14Z",
            }
        ],
    }


def fixtures():
    return [
        {
            "id": "epl-synthetic",
            "label": "Home A – Away B",
            "homeAliases": ["Home A"],
            "awayAliases": ["Away B"],
            "kickoff": "2026-11-21T15:00:00Z",
        }
    ]


def build(value=None, calendar=None):
    return build_choices(value or source(), calendar or fixtures(), [PICK_ID], parser_sha="b" * 64)


def test_one_literal_choice_keeps_proof_clock_and_unknown_publication_separate():
    pick = build()[0]
    assert pick["observedAt"] == "2026-11-21T01:30:14Z"
    assert pick["firstSeenAt"] == "2026-11-21T00:49:00Z"
    assert pick["publishedAt"] is None and pick["publishedCivilDate"] is None
    assert pick["selection"] == "Literal non-normalized choice"
    assert pick["market"] == "source_native_opaque"
    assert pick["authorId"].startswith("public:") and pick["authorLabel"] == "SyntheticAlias"
    assert all(
        pick[k] is False
        for k in [
            "settlementAllowed",
            "performanceEvaluationAllowed",
            "marketInterpretationAllowed",
        ]
    )


@pytest.mark.parametrize("mutation", ["date", "owner", "selection", "conflict", "comparison"])
def test_changed_native_record_or_identity_is_refused(mutation):
    value = source()
    record = value["content"]["projection"]["records"][0]
    if mutation == "date":
        record["nativeTemporalFields"]["date"] = "2026-11-22T15:00:00Z"
    if mutation == "owner":
        record["nativeFields"]["tipster.user.id"] = "different"
    if mutation == "selection":
        record["nativeFields"]["pick"] = "Changed choice"
    if mutation == "conflict":
        value["content"]["projection"]["conflictingTargetIds"] = [PICK_ID]
    if mutation == "comparison":
        value["targetComparison"][0]["samePreviouslyRetainedNativeFields"] = False
    with pytest.raises(ValueError):
        build(value)


def test_native_date_does_not_match_a_different_official_edition():
    calendar = fixtures()
    calendar[0]["kickoff"] = "2026-11-22T15:00:00Z"
    with pytest.raises(ValueError):
        build(calendar=calendar)


def test_at_kickoff_is_not_before_match_and_created_at_cannot_replace_date():
    value = source()
    value["content"]["observedAt"] = "2026-11-21T15:00:00Z"
    with pytest.raises(ValueError):
        build(value)
    value = source()
    del value["content"]["projection"]["records"][0]["nativeTemporalFields"]["date"]
    with pytest.raises(ValueError):
        build(value)


def test_ambiguous_alias_match_and_unreviewed_id_are_refused():
    with pytest.raises(ValueError):
        build(calendar=fixtures() + fixtures())
    with pytest.raises(ValueError):
        build_choices(
            source(), fixtures(), ["33333333-3333-4333-8333-333333333333"], parser_sha="b" * 64
        )


def test_merge_preserves_previous_objects_and_deduplicates_without_activating():
    base = {
        "picks": [{"id": "old", "authorId": "old", "sourceId": "old"}],
        "fixtures": [],
        "claimIds": ["OLD"],
        "generatedAt": "2026-11-21T00:00:00Z",
        "requestCount": 12,
        "recurring": False,
        "campaign": {"state": "halted"},
    }
    original = deepcopy(base)
    bundle = {
        "picks": build(),
        "fixtures": fixtures(),
        "claimId": "SYNTHETIC.NOTBETTING",
        "qualifiedAt": "2026-11-21T01:32:00Z",
    }
    result = merge_public(base, bundle)
    assert base == original and result["picks"][0] == original["picks"][0]
    assert len(result["picks"]) == 2 and result["distinctPicks"] == 2 and result["authorCount"] == 2
    assert merge_public(result, bundle) == result
    assert result["requestCount"] == 12 and result["recurring"] is False
    assert result["campaign"] == {"state": "halted"}
    assert result["notbettingCollection"]["recurringAuthority"] is False


def test_merge_preserves_newer_source_reobservation_and_existing_fixture_entirely():
    fixture = fixtures()[0]
    fixture["originalExtraProof"] = "keep"
    base = dict(
        picks=[
            dict(
                id="old",
                sourceId="old",
                authorId="old",
                observedAt="2026-11-20T23:07:00Z",
                lastObservedAt="2026-11-21T05:07:00Z",
            )
        ],
        fixtures=[fixture],
        claimIds=["OLD"],
        sourceObservedThrough="2026-11-21T05:07:00Z",
        generatedAt="2026-11-21T08:00:00Z",
    )
    original = deepcopy(base)
    bundle = dict(
        picks=build(),
        fixtures=fixtures(),
        claimId="SYNTHETIC.NOTBETTING",
        qualifiedAt="2026-11-21T09:00:00Z",
    )
    result = merge_public(base, bundle)
    assert result["sourceObservedThrough"] == "2026-11-21T05:07:00Z"
    assert result["fixtures"] == original["fixtures"] and result["picks"][0] == original["picks"][0]
    assert merge_public(result, bundle) == result and base == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("kickoff", "2026-11-21T16:00:00Z"),
        ("label", "Different event"),
        ("homeAliases", ["Different team"]),
    ],
)
def test_existing_fixture_conflict_is_refused(field, value):
    fixture = fixtures()[0]
    fixture[field] = value
    base = dict(picks=[], fixtures=[fixture], claimIds=[], generatedAt="2026-11-21T00:00:00Z")
    original = deepcopy(base)
    bundle = dict(
        picks=build(),
        fixtures=fixtures(),
        claimId="SYNTHETIC.NOTBETTING",
        qualifiedAt="2026-11-21T01:32:00Z",
    )
    with pytest.raises(ValueError, match="fixture"):
        merge_public(base, bundle)
    assert base == original


def test_readback_is_anchored_and_corrupt_private_source_preserves_old_facts(tmp_path, monkeypatch):
    directory = tmp_path / "cockpit/.ci/notbetting-prospective-0130-v2-20261121"
    directory.mkdir(parents=True)
    report_dir = tmp_path / "reports/source_observatory"
    report_dir.mkdir(parents=True)
    raw = canonical(source()) + b"\n"
    (directory / "result.json").write_bytes(raw)
    source_sha = sha256(raw).hexdigest()
    bundle = dict(
        schemaVersion="robin-notbetting-opaque-bundle-v1",
        sourceResultSha256=source_sha,
        fixtures=fixtures(),
        picks=build(),
        acceptedSourceTipIds=[PICK_ID],
        claimId="SYNTHETIC.NOTBETTING",
        qualifiedAt="2026-11-21T01:32:00Z",
    )
    bundle_raw = canonical(bundle) + b"\n"
    bundle_sha = sha256(bundle_raw).hexdigest()
    (directory / f"observations-{bundle_sha}.json").write_bytes(bundle_raw)
    report = dict(
        schemaVersion="robin-notbetting-opaque-data-v1",
        scope="LOCAL_PERSONAL_NONCOMMERCIAL_NO_REDISTRIBUTION",
        bundleSha256=bundle_sha,
        sourceResultSha256=source_sha,
        nativeRecordsParserSha256="b" * 64,
        calendarSha256=sha256(canonical(fixtures())).hexdigest(),
        dataClaimId="SYNTHETIC.NOTBETTING",
    )
    report_raw = json.dumps(report).encode()
    (report_dir / notbetting_collection.REPORT_NAME).write_bytes(report_raw)
    monkeypatch.setattr(
        notbetting_collection, "APPROVED_REPORT_SHA256", sha256(report_raw).hexdigest()
    )
    base = dict(picks=[], fixtures=[], claimIds=[], generatedAt="2026-11-21T00:00:00Z")
    assert notbetting_collection.add_public(base, tmp_path)["distinctPicks"] == 1
    (directory / "result.json").write_bytes(raw + b" ")
    result = notbetting_collection.add_public(base, tmp_path)
    assert result["picks"] == [] and result["notbettingCollection"]["state"] == "unavailable"
    assert base["picks"] == []
