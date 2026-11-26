from copy import deepcopy
from hashlib import sha256

import pytest

from robin.source_observatory import notbetting_occurrences as module
from robin.source_observatory.connectors import canonical


def fixture():
    return dict(
        id="synthetic-fixture",
        label="Home – Away",
        homeAliases=["Home"],
        awayAliases=["Away"],
        kickoff="2026-11-21T15:00:00Z",
    )


def capture(hour):
    fields = dict(
        id="11111111-1111-4111-8111-111111111111",
        event="Home - Away",
        pick="Literal pick",
        competition="Premier League",
        date="2026-11-21T15:00:00Z",
        tipsterId=module.OWNER,
    )
    fields.update(
        {
            "tipster.user.id": module.OWNER,
            "tipster.user.tipster.id": module.OWNER,
            "tipster.user.tipster.userId": module.OWNER,
            "tipster.user.username": "ELIMAGAR",
        }
    )
    clock = f"2026-11-21T{hour}:00:00Z"
    return dict(
        sourceUrl=module.SOURCE_URL,
        observedAt=clock,
        responseSha256="a" * 64,
        parserSha256="b" * 64,
        journalSha256=str(hour)[-1] * 64,
        eventHash="c" * 64,
        reasons=["depth_bound"],
        rows=[
            dict(
                sourceFields=fields,
                sourceRecordFingerprint=sha256(canonical(fields)).hexdigest(),
                observedAt=clock,
            )
        ],
    )


def test_two_consistent_native_occurrences_are_one_noncanonical_declaration():
    rows = module.build_occurrences([capture("03"), capture("04")], [fixture()])
    assert len(rows) == 1 and rows[0]["observationCount"] == 2
    assert rows[0]["firstSeenAt"] == "2026-11-21T03:00:00Z"
    assert rows[0]["lastObservedAt"] == "2026-11-21T04:00:00Z"
    assert rows[0]["canonicalQualification"] is False
    assert rows[0]["sourceWalkTruncated"] and rows[0]["sourceTraversalComplete"] is False
    assert rows[0]["globalVariantConsistency"] == "NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS"
    assert all(
        rows[0][k] is False
        for k in [
            "performanceEvaluationAllowed",
            "settlementAllowed",
            "marketInterpretationAllowed",
        ]
    )


@pytest.mark.parametrize(
    "defect",
    ["owner", "missing_owner", "date", "event", "fingerprint", "late", "choice", "competition"],
)
def test_no_rejected_or_conflicting_native_version_can_become_a_declaration(defect):
    first, second = capture("03"), capture("04")
    row = second["rows"][0]
    fields = row["sourceFields"]
    if defect == "owner":
        fields["tipster.user.id"] = "other"
    elif defect == "missing_owner":
        fields.pop("tipster.user.tipster.userId")
    elif defect == "date":
        fields["date"] = "2026-11-22T15:00:00Z"
    elif defect == "event":
        fields["event"] = "Away - Home"
    elif defect == "choice":
        fields["pick"] = "Other choice"
    elif defect == "competition":
        fields["competition"] = "Bundesliga"
    elif defect == "late":
        second["observedAt"] = row["observedAt"] = fixture()["kickoff"]
    if defect != "fingerprint":
        row["sourceRecordFingerprint"] = sha256(canonical(fields)).hexdigest()
    else:
        row["sourceRecordFingerprint"] = "d" * 64
    with pytest.raises(ValueError):
        module.build_occurrences([first, second], [fixture()])


def test_source_clock_and_opaque_fields_are_not_publication_or_performance():
    values = [capture("03"), capture("04")]
    for value in values:
        value["rows"][0]["sourceFields"]["createdAt"] = "2026-11-20T22:00:00Z"
        fields = value["rows"][0]["sourceFields"]
        value["rows"][0]["sourceRecordFingerprint"] = sha256(canonical(fields)).hexdigest()
    row = module.build_occurrences(values, [fixture()])[0]
    assert row["publishedAt"] is None and row["market"] == "source_native_opaque"
    assert row["firstSeenAt"] != "2026-11-20T22:00:00Z"


def test_one_capture_or_repeated_same_capture_is_not_two_independent_observations():
    with pytest.raises(ValueError):
        module.build_occurrences([capture("03")], [fixture()])
    with pytest.raises(ValueError):
        module.build_occurrences([capture("03"), deepcopy(capture("03"))], [fixture()])


def test_ambiguous_calendar_and_forged_complete_scope_are_rejected():
    with pytest.raises(ValueError):
        module.build_occurrences(
            [capture("03"), capture("04")], [fixture(), dict(fixture(), id="duplicate")]
        )
    value = capture("04")
    value["reasons"] = []
    with pytest.raises(ValueError):
        module.build_occurrences([capture("03"), value], [fixture()])
