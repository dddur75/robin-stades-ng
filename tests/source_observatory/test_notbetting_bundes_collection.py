"""Two frozen witnesses; synthetic negatives never read a provider."""

from copy import deepcopy
from hashlib import sha256

import pytest

from robin.source_observatory import notbetting_bundes_collection as m
from robin.source_observatory.connectors import canonical


def source():
    records, comparisons = [], []
    for identifier, event, kickoff in zip(
        m.TARGETS,
        ("Eintracht Frankfurt - Hoffenheim", "Schalke 04 - Stuttgart"),
        ("2026-11-21T14:30:00Z", "2026-11-21T17:30:00Z"),
        strict=True,
    ):
        fields = dict(
            id=identifier, event=event, pick="Synthetic literal choice", competition="Bundesliga"
        )
        fields.update({key: m.OWNER for key in m.OWNER_KEYS})
        fields["tipster.user.username"] = "ELIMAGAR"
        owner = dict(
            tipsterId=m.OWNER,
            tipster={
                k.removeprefix("tipster."): v for k, v in fields.items() if k.startswith("tipster.")
            },
        )
        row = dict(
            nativeFields=fields,
            linkedOwner=owner,
            nativeTemporalFields=dict(date=kickoff, createdAt="2026-11-21T00:24:00Z"),
        )
        resign(row)
        records.append(row)
        comparisons.append(
            dict(
                id=identifier,
                samePreviouslyRetainedNativeFields=True,
                changedPreviouslyRetainedFieldNames=[],
                firstSeenAt="2026-11-21T00:49:56.451686+00:00",
                newTemporalEvidenceObservedAt="2026-11-21T01:30:14.391200+00:00",
            )
        )
    return dict(
        sourceUrl=m.SOURCE_URL,
        baselineObservedAt="2026-11-21T00:49:56.451686+00:00",
        content=dict(
            status=200,
            observedAt="2026-11-21T01:30:14.391200+00:00",
            responseSha256="a" * 64,
                projection=dict(records=records, conflictingTargetIds=[], walkTruncated=True),
        ),
        targetComparison=comparisons,
    )


def resign(row):
    row["sourceRecordFingerprint"] = sha256(
        canonical(
            dict(
                fields=row["nativeFields"],
                linkedOwner=row["linkedOwner"],
                nativeTemporalFields=row["nativeTemporalFields"],
            )
        )
    ).hexdigest()


def test_two_source_clocks_and_opaque_fields_are_preserved():
    picks = m.build_bundes_choices(source(), m.bundes_fixtures(), parser_sha="b" * 64)
    assert [p["sourceTipId"] for p in picks] == list(m.TARGETS)
    for p in picks:
        assert (
            p["observedAt"]
            == p["temporalEvidenceFirstObservedAt"]
            == "2026-11-21T01:30:14.391200+00:00"
        )
        assert p["firstSeenAt"] == "2026-11-21T00:49:56.451686+00:00"
        assert (
            p["publishedAt"] is None and p["publishedCivilDate"] is None and "qualifiedAt" not in p
        )
        assert p["market"] == "source_native_opaque"
        assert p["sourceWalkTruncated"] is True
        assert p["evidenceScope"] == "CLOSED_NATIVE_OCCURRENCE_ONLY"
        assert p["globalVariantConsistency"] == "NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS"
        assert p["canonicalQualification"] is False
        assert all(
            p[k] is False
            for k in (
                "performanceEvaluationAllowed",
                "settlementAllowed",
                "marketInterpretationAllowed",
            )
        )


@pytest.mark.parametrize(
    "key,bad",
    [
        ("season", "2025/26"),
        ("sourceTimezone", "CET"),
        ("sourceUTCHeaderConfirmed", False),
        ("kickoff", "2026-11-22T14:30:00Z"),
        ("competition", "Bundesliga 2"),
        ("label", "Wrong fixture"),
    ],
)
def test_unproved_calendar_changes_are_refused(key, bad):
    fixtures = m.bundes_fixtures()
    fixtures[0][key] = bad
    with pytest.raises(ValueError):
        m.build_bundes_choices(source(), fixtures, parser_sha="b" * 64)


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "invalid",
        "owner",
        "date",
        "neighbor",
        "orientation",
        "at_ko",
        "first_seen",
        "comparison",
    ],
)
def test_native_proof_defects_fail_closed(defect):
    value = source()
    projection = value["content"]["projection"]
    row = projection["records"][0]
    if defect == "missing":
        projection["records"].pop()
    elif defect == "duplicate":
        projection["records"].append(deepcopy(row))
    elif defect == "invalid":
        projection["conflictingTargetIds"] = [m.TARGETS[0]]
    elif defect == "owner":
        row["nativeFields"]["tipster.user.id"] = "wrong-owner"
    elif defect == "date":
        row["nativeTemporalFields"]["date"] = "2026-11-22T14:30:00Z"
    elif defect == "neighbor":
        row["nativeTemporalFields"].pop("date")
        value["date"] = "2026-11-21T14:30:00Z"
    elif defect == "orientation":
        row["nativeFields"]["event"] = "Hoffenheim - Eintracht Frankfurt"
    elif defect == "comparison":
        value["targetComparison"][0]["samePreviouslyRetainedNativeFields"] = False
    else:
        if defect == "at_ko":
            value["content"]["observedAt"] = "2026-11-21T14:30:00Z"
            for c in value["targetComparison"]:
                c["newTemporalEvidenceObservedAt"] = value["content"]["observedAt"]
        else:
            value["baselineObservedAt"] = "2026-11-21T15:00:00Z"
            for c in value["targetComparison"]:
                c["firstSeenAt"] = value["baselineObservedAt"]
    resign(row)
    with pytest.raises(ValueError):
        m.build_bundes_choices(value, m.bundes_fixtures(), parser_sha="b" * 64)


def test_frozen_entrypoint_rejects_substituted_source_bytes():
    with pytest.raises(ValueError):
        m.qualify_frozen_bundes(b"{}", m.bundes_fixtures(), parser_sha="b" * 64)
