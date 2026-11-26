from datetime import UTC, datetime

import pytest

from robin.source_observatory.olbg import admit_facts, extract_profile

FIX = [
    dict(
        id="test-nice-paris",
        label="Nice – PSG",
        kickoff="2026-11-21T16:15:00Z",
        homeAliases=["Nice"],
        awayAliases=["PSG"],
    )
]
NOW = datetime(2026, 11, 19, 17, tzinfo=UTC)


def doc(extra="", mode="current", owner=42):
    return (
        (
            "<html><p>One's text</p><script>var data={mode:\""
            + mode
            + '",effectiveTipsterId:'
            + str(owner)
            + ',tipsterUsername:"Synthetic",tipsByDate:[{tips:[{tipid:123,selection:"PSG",eventname:"Nice v PSG",event_datetime:"2026-11-21 16:15:00",market:"",winew:"Win",hcap_market:false,result:"Open",vc_sport_id:1,eventid:999,odds:1.5,comment:"} {tipid:555,selection:bad}"}]}]'
            + extra
            + "};</script><p>Another's</p></html>"
        )
        .encode()
        .replace(b"tipsByDate:[{tips:", b"tipsByDate:[{events:[{tips:")
        .replace(b"}]}]", b"}]}]}]")
    )


def test_extract_only_personal_array_and_no_script_execution():
    f = extract_profile(doc(',recommended:[{tipid:888,selection:"Other"}]'), 42)
    assert len(f["records"]) == 1 and f["authorId"] == 42 and "comment" not in f["records"][0]


def test_wrong_owner_and_history_refused():
    with pytest.raises(ValueError):
        extract_profile(doc(), 43)
    with pytest.raises(ValueError):
        extract_profile(doc(mode="history"), 42)


@pytest.mark.parametrize(
    "old,new",
    [
        ('selection:"PSG"', 'selection:"PSG"+other'),
        ("effectiveTipsterId:42", "effectiveTipsterId:42+1"),
        ("odds:1.5", "odds:1.5e2"),
    ],
)
def test_expressions_cannot_be_truncated_to_scalars(old, new):
    with pytest.raises(ValueError):
        extract_profile(doc().replace(old.encode(), new.encode()), 42)


def test_recommended_and_nested_objects_are_not_personal():
    body = doc().replace(b"tips:[{tipid:", b"tips:[],recommendedTips:[{tipid:")
    assert extract_profile(body, 42)["records"] == []
    body = (
        doc()
        .replace(b"tips:[{tipid:", b"tips:[],nested:{tips:[{tipid:")
        .replace(b"}]}]};", b"}]}]}]};")
    )
    with pytest.raises(ValueError):
        extract_profile(body, 42)


def test_commented_hydration_is_not_active():
    with pytest.raises(ValueError):
        extract_profile(
            doc().replace(b"var data=", b"/* var data=").replace(b";</script>", b"; */</script>"),
            42,
        )


def test_native_selection_preserves_unknown_market_and_timezone():
    f = extract_profile(doc(), 42)
    p = admit_facts(
        f,
        "https://www.olbg.com/tipsters/tips/42",
        NOW,
        FIX,
        response_sha="1" * 64,
        parser_sha="2" * 64,
        calendar_sha="3" * 64,
    )
    assert len(p) == 1 and p[0]["market"] == "source_native" and p[0]["selection"] == "PSG"
    assert (
        p[0]["sourceMarketLabel"] == ""
        and p[0]["sourceEventTimezone"] is None
        and p[0]["publishedCivilDate"] is None
    )
    assert p[0]["kickoff"] == FIX[0]["kickoff"] and p[0]["performanceEvaluationAllowed"] is False


def test_after_kickoff_wrong_date_other_sport_or_settled_excluded():
    f = extract_profile(doc(), 42)
    assert not admit_facts(
        f,
        "https://www.olbg.com/tipsters/tips/42",
        datetime(2026, 11, 22, tzinfo=UTC),
        FIX,
        response_sha="1" * 64,
        parser_sha="2" * 64,
        calendar_sha="3" * 64,
    )
    for key, value in [
        ("vc_sport_id", 2),
        ("event_datetime", "2026-11-20 16:15:00"),
        ("result", "Won"),
        ("selection", "Another team"),
        ("market", "First half"),
    ]:
        f = extract_profile(doc(), 42)
        f["records"][0][key] = value
        assert not admit_facts(
            f,
            "https://www.olbg.com/tipsters/tips/42",
            NOW,
            FIX,
            response_sha="1" * 64,
            parser_sha="2" * 64,
            calendar_sha="3" * 64,
        )


def test_author_url_and_duplicate_ids_fail_closed():
    f = extract_profile(doc(), 42)
    with pytest.raises(ValueError):
        admit_facts(
            f,
            "https://www.olbg.com/tipsters/tips/43",
            NOW,
            FIX,
            response_sha="1" * 64,
            parser_sha="2" * 64,
            calendar_sha="3" * 64,
        )
    f["records"] *= 2
    with pytest.raises(ValueError):
        admit_facts(
            f,
            "https://www.olbg.com/tipsters/tips/42",
            NOW,
            FIX,
            response_sha="1" * 64,
            parser_sha="2" * 64,
            calendar_sha="3" * 64,
        )
