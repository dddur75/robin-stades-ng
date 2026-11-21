from copy import deepcopy

import pytest

from robin.source_observatory import notbetting_bundes_view as view


def base():
    return dict(
        picks=[dict(id="old", authorId="prior", observedAt="2026-11-21T03:00:00Z")],
        fixtures=[dict(id="oldfixture", label="Earlier fixture")],
        claimIds=["OLD"],
        generatedAt="2026-11-21T03:00:00Z",
        sourceObservedThrough="2026-11-21T03:00:00Z",
        distinctPicks=1,
        authorCount=1,
        notbettingCollection=dict(
            state="qualified_one_time",
            nativeChoices=1,
            unadmittedNativeWitnesses=2,
            claimId="PL_PROVENANCE",
        ),
        qualification=dict(qualifiedCount=24),
    )


def bundle():
    rows = [
        dict(
            id="new-" + str(i),
            authorId="bounded",
            fixtureId="fixture-" + str(i),
            observedAt="2026-11-21T01:30:00Z",
            sourceWalkTruncated=True,
            canonicalQualification=False,
            sourceTraversalComplete=False,
            globalVariantConsistency="NOT_ESTABLISHED_OUTSIDE_RETAINED_RECORDS",
            evidenceScope="CLOSED_NATIVE_OCCURRENCE_ONLY",
        )
        for i in (1, 2)
    ]
    return dict(
        picks=rows,
        fixtures=[dict(id="fixture-" + str(i), label="Fixture " + str(i)) for i in (1, 2)],
        claimId=view.CLAIM,
        qualifiedAt="2026-11-21T03:31:40Z",
        admissionScope="BOUNDED_OCCURRENCES_ONLY",
    )


def test_merge_preserves_primary_pl_summary_and_all_old_facts():
    original = base()
    old = deepcopy(original)
    result = view.merge_bounded(original, bundle())
    assert original == old and result["picks"][:1] == old["picks"]
    assert result["fixtures"][:1] == old["fixtures"]
    assert result["notbettingCollection"] == old["notbettingCollection"]
    assert result["qualification"] == old["qualification"]
    assert result["distinctPicks"] == 3 and result["authorCount"] == 2
    summary = result["notbettingBundesOccurrences"]
    assert summary["nativeOccurrences"] == 2 and summary["canonicalQualification"] is False
    assert summary["sourceWalkTruncated"] is True and summary["recurringAuthority"] is False
    assert summary["admissionScope"] == "BOUNDED_OCCURRENCES_ONLY"
    assert result["sourceObservedThrough"] == "2026-11-21T03:00:00Z"
    assert result["generatedAt"] == "2026-11-21T03:31:40Z"


@pytest.mark.parametrize("kind", ["pick", "fixture", "quality"])
def test_conflicts_and_missing_quality_fail_without_mutating_the_base(kind):
    original = base()
    proposal = bundle()
    if kind == "pick":
        original["picks"].append(dict(proposal["picks"][0], selection="Conflicting"))
    elif kind == "fixture":
        original["fixtures"].append(dict(proposal["fixtures"][0], label="Conflicting"))
    else:
        del proposal["picks"][0]["sourceWalkTruncated"]
    old = deepcopy(original)
    with pytest.raises(ValueError):
        view.merge_bounded(original, proposal)
    assert original == old


def test_repeat_merge_does_not_duplicate_bounded_occurrences():
    first = view.merge_bounded(base(), bundle())
    second = view.merge_bounded(first, bundle())
    assert second == first


def test_missing_proof_falls_back_to_all_previous_data(tmp_path):
    old = base()
    result = view.add_public(old, tmp_path)
    assert result["picks"] == old["picks"] and result["fixtures"] == old["fixtures"]
    assert result["notbettingCollection"] == old["notbettingCollection"]
    assert result["notbettingBundesOccurrences"]["state"] == "unavailable"
