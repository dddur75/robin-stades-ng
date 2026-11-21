from copy import deepcopy

import pytest

from robin.source_observatory import notbetting_occurrence_view as view


def row(identifier):
    return dict(
        id=identifier,
        sourceId="NotBetting",
        authorId="public:synthetic",
        sourceTipId=identifier,
        fixtureId="fixture",
        kickoff="2026-11-21T15:00:00Z",
        selection="Literal",
        sourceFields=dict(
            id=identifier,
            event="Home - Away",
            pick="Literal",
            competition="Premier League",
            date="2026-11-21T15:00:00Z",
            tipsterId="owner",
        ),
        firstSeenAt="2026-11-21T03:15:00Z",
        lastObservedAt="2026-11-21T04:35:00Z",
        observedAt="2026-11-21T03:15:00Z",
        evidenceScope="CLOSED_NATIVE_OCCURRENCE_ONLY",
        canonicalQualification=False,
        sourceWalkTruncated=True,
        sourceTraversalComplete=False,
        globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
        performanceEvaluationAllowed=False,
        settlementAllowed=False,
        marketInterpretationAllowed=False,
        observations=[
            dict(observedAt="2026-11-21T03:15:00Z"),
            dict(observedAt="2026-11-21T04:35:00Z"),
        ],
        observationCount=2,
    )


def sample():
    old = row(view.CANARY_ID)
    old.update(firstSeenAt="2026-11-21T00:49:56Z", evidenceScope="ORIGINAL_E1")
    base = dict(
        status="ok",
        picks=[old, dict(id="other", authorId="other")],
        fixtures=[dict(id="fixture")],
        notbettingCollection=dict(state="qualified_one_time"),
        notbettingBundesOccurrences=dict(state="bounded_occurrences_qualified"),
        claimIds=["OLD"],
        sourceObservedThrough="2026-11-21T03:00:00Z",
    )
    bundle = dict(
        picks=[row(view.CANARY_ID), row("new")],
        fixtures=[dict(id="fixture")],
        claimId="SYNTHETIC",
        qualifiedAt="2026-11-21T04:45:00Z",
    )
    return base, bundle


def test_add_one_declaration_without_replacing_earlier_canonical_or_other_objects():
    base, bundle = sample()
    prior = deepcopy(base)
    result = view.merge_occurrences(base, bundle)
    assert result["picks"][:2] == base["picks"] == prior["picks"]
    assert len(result["picks"]) == 3 and result["picks"][-1]["id"] == "new"
    assert result["notbettingCollection"] == base["notbettingCollection"]
    assert result["notbettingBundesOccurrences"] == base["notbettingBundesOccurrences"]
    assert result["notbettingClosedOccurrences"]["nativeObservations"] == 4
    assert result["sourceObservedThrough"] == "2026-11-21T04:35:00Z"
    assert base == prior
    assert view.merge_occurrences(result, bundle) == result


@pytest.mark.parametrize("defect", ["collision", "source", "quality", "fixture"])
def test_conflict_never_overwrites_existing_facts_or_removes_boundaries(defect):
    base, bundle = sample()
    if defect == "collision":
        base["picks"][0]["sourceFields"]["pick"] = "Different"
    elif defect == "source":
        base["picks"][0]["sourceId"] = "Other"
    elif defect == "quality":
        bundle["picks"][1]["canonicalQualification"] = True
    else:
        bundle["fixtures"][0]["kickoff"] = "Different"
    with pytest.raises(ValueError):
        view.merge_occurrences(base, bundle)


def test_unavailable_loader_preserves_the_complete_input(tmp_path):
    base, _ = sample()
    result = view.add_public(base, tmp_path)
    assert result["picks"] == base["picks"] and result["fixtures"] == base["fixtures"]
    assert result["notbettingCollection"] == base["notbettingCollection"]
    assert result["notbettingClosedOccurrences"]["state"] == "unavailable"


@pytest.mark.parametrize("base_clock", ["2026-11-21T03:00:00Z", "2026-11-21T05:00:00Z"])
def test_view_generation_is_the_latest_qualification_without_falsifying_source_clocks(base_clock):
    base, bundle = sample()
    base["generatedAt"] = base_clock
    result = view.merge_occurrences(base, bundle)
    assert result["generatedAt"] == max(base_clock, bundle["qualifiedAt"])
    assert result["sourceObservedThrough"] == "2026-11-21T04:35:00Z"
    assert result["picks"][0]["firstSeenAt"] == "2026-11-21T00:49:56Z"
