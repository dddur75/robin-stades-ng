from copy import deepcopy

import pytest

from robin.source_observatory.olbg_pending import project_pending_observations


def source():
    return {
        "profiles": [{
            "facts": {"authorId": 123, "authorLabel": "SYNTH_AUTHOR", "mode": "current", "records": [
                {"tipid": 1, "eventid": 11, "vc_sport_id": 1, "result": "Open", "eventname": "SYNTH_HOME v SYNTH_AWAY", "selection": "SYNTH_CHOICE", "market": "SYNTH_MARKET", "winew": "SYNTH_TYPE", "event_datetime": "2026-11-28 15:00:00", "ignored": "SYNTH_NOT_COPIED"}
            ]},
            "request": {"url": "https://www.olbg.com/tipsters/tips/123", "observedAt": "2026-11-24T12:00:00+00:00", "responseSha256": "a" * 64},
        }],
        "fixtures": [],
    }


def project(value=None):
    return project_pending_observations(source() if value is None else value, parser_sha="b" * 64)


def test_preserves_observation_without_inventing_fixture_or_prematch():
    value = source()
    original = deepcopy(value)
    result = project(value)
    assert value == original
    assert result["records"][0]["selectionText"] == "SYNTH_CHOICE"
    assert result["records"][0]["nativeDateText"] == "2026-11-28 15:00:00"
    assert "SYNTH_NOT_COPIED" not in str(result)
    assert result["attribution"]["kind"] == "SOURCE_PROFILE_ACCOUNT"
    assert result["attribution"]["personIdentityVerified"] is False
    assert result["competition"] is result["canonicalFixture"] is result["kickoffUTC"] is None
    assert result["preMatchProven"] is result["sourceReady"] is False
    assert result["admissions"] == 0
    assert result["performanceEvaluationAllowed"] is result["settlementAllowed"] is False
    assert result["interpretationAllowed"] is False


@pytest.mark.parametrize("key,value", [("authorId", True), ("authorId", 0), ("authorLabel", ""), ("mode", "history")])
def test_profile_attribution_is_required(key, value):
    data = source()
    data["profiles"][0]["facts"][key] = value
    with pytest.raises(ValueError, match="PENDING_PROFILE_REFUSED"):
        project(data)


@pytest.mark.parametrize("url", ["https://www.olbg.com/tipsters/tips/124", "http://www.olbg.com/tipsters/tips/123", "https://www.olbg.com/tipsters/tips/123?x=1"])
def test_profile_route_must_match_individual_account(url):
    data = source()
    data["profiles"][0]["request"]["url"] = url
    with pytest.raises(ValueError, match="PENDING_PROFILE_REFUSED"):
        project(data)


@pytest.mark.parametrize("stamp", ["2026-11-24T12:00:00", "2026-11-24T12:00:00+01:00", "not-a-clock"])
def test_observation_requires_utc_but_native_date_is_not_interpreted(stamp):
    data = source()
    data["profiles"][0]["request"]["observedAt"] = stamp
    with pytest.raises(ValueError, match="PENDING_PROVENANCE_REFUSED"):
        project(data)


def test_duplicate_or_boolean_native_tip_id_refuses_whole_batch():
    data = source()
    data["profiles"][0]["facts"]["records"] *= 2
    with pytest.raises(ValueError, match="PENDING_NATIVE_ID_REFUSED"):
        project(data)
    data = source()
    data["profiles"][0]["facts"]["records"][0]["tipid"] = True
    with pytest.raises(ValueError, match="PENDING_NATIVE_ID_REFUSED"):
        project(data)


def test_omissions_are_explicit_and_native_values_stay_bounded():
    data = source()
    rows = data["profiles"][0]["facts"]["records"]
    other, invalid = deepcopy(rows[0]), deepcopy(rows[0])
    other.update(tipid=2, vc_sport_id=2)
    invalid.update(tipid=3, selection="SYNTH\nCONTROL")
    rows.extend([other, invalid])
    result = project(data)
    assert len(result["records"]) == 1
    assert result["omitted"] == {"nonFootballOpen": 1, "invalidNativeFields": 1}
    assert result["sourceRecordCount"] == 3


def test_twenty_record_limit_refuses_overflow_without_truncation():
    data = source()
    base = data["profiles"][0]["facts"]["records"][0]
    data["profiles"][0]["facts"]["records"] = [dict(base, tipid=i) for i in range(1, 22)]
    with pytest.raises(ValueError, match="PENDING_RECORD_LIMIT"):
        project(data)


def test_provenance_hashes_cannot_be_missing_or_replaced():
    data = source()
    data["profiles"][0]["request"]["responseSha256"] = "bad"
    with pytest.raises(ValueError, match="PENDING_PROVENANCE_REFUSED"):
        project(data)
    with pytest.raises(ValueError, match="PENDING_PROVENANCE_REFUSED"):
        project_pending_observations(source(), parser_sha="bad")


def test_no_qualifiable_pending_record_creates_no_batch():
    data = source()
    data["profiles"][0]["facts"]["records"][0]["result"] = "Won"
    with pytest.raises(ValueError, match="NO_VALID_PENDING_RECORDS"):
        project(data)
