"""Portable synthetic regression tests; no source, account or private file access."""
import copy
import hashlib
from datetime import datetime, timezone

import pytest

from robin.source_observatory import notbetting_prospective as reader

UID = "11111111-1111-1111-1111-111111111111"
LABEL = "Synthetic Owner"
TIP = "22222222-2222-2222-2222-222222222222"
SHA = "a" * 64
CLAIM = "SYNTHETIC.PUBLISHED.CALENDAR"
KO = "2026-11-27T19:30:00+00:00"
OBSERVED = datetime(2026, 11, 23, tzinfo=timezone.utc)


def row():
    return dict(id=TIP, event="Synthetic Home - Synthetic Away", pick="Synthetic opaque",
                competition="Bundesliga", date=KO, tipsterId=UID,
                tipster=dict(user=dict(id=UID, username=LABEL, tipster=dict(id=UID, userId=UID))))


def qualify(rows, observed=OBSERVED):
    fixture = dict(id="synthetic-fixture", home="Synthetic Home", away="Synthetic Away",
                   kickoff=KO, competition="Bundesliga", calendarSHA=SHA, calendarClaim=CLAIM)
    return reader.qualify_documents({"0": rows}, [fixture], observed,
                                   ownerSpec=dict(uid=UID, label=LABEL), competition="Bundesliga",
                                   responseSHA=SHA, parserSHA="b" * 64, calendarClaim=CLAIM, calendarSHA=SHA)


def calendar_bytes():
    return reader.canonical(dict(
        schemaVersion="robin-official-published-calendar-v1", claimId=CLAIM,
        status="ACCEPTED_PUBLISHED_UTC_PROGRAMME_ONLY", competition="Bundesliga", season="2026/27",
        matchday=11, nativeCalendarAccepted=True, bodyComplete=True, sourceUTCHeaderConfirmed=True,
        sourceCETHeaderConfirmed=True, pageCountFromPinnedPredicate=1,
        sourceObservedAt="2026-11-23T00:00:00+00:00", sourceClosedAt="2026-11-23T00:01:00+00:00",
        acceptedAt="2026-11-23T00:02:00+00:00", sourceResultRAW_SHA256=SHA, payloadSHA256="b" * 64,
        fixtures=[dict(home="Synthetic Home", away="Synthetic Away", scheduledUTC=KO,
                       semantic="DFL_SCHEDULED_UTC_ONLY")]))


def test_private_positive_does_not_grant_application_or_publication_authority():
    result = qualify([row()])
    assert result["status"] == "qualified" and len(result["picks"]) == 1
    pick = result["picks"][0]
    assert pick["publishedAt"] is None and pick["publicationUnknown"]
    assert not any(pick[k] for k in ("eligibleForApplication", "interpretationAllowed",
                                    "performanceEvaluationAllowed", "settlementAllowed"))
    assert result["permissionEstablished"] is False


def test_native_en_dash_is_an_explicit_separator():
    native = row()
    native["event"] = "Synthetic Home \u2013 Synthetic Away"
    assert len(qualify([native])["picks"]) == 1


def test_mojibake_character_is_not_a_separator():
    native = row()
    native["event"] = "Synthetic Home \u00e2 Synthetic Away"
    assert not qualify([native])["picks"]


def test_conflicting_id_vetoes_earlier_choice_before_calendar_filter():
    native = row()
    conflict = copy.deepcopy(native)
    conflict.update(event="Other Home - Other Away", pick="Conflicting synthetic choice")
    result = qualify([native, conflict])
    assert not result["picks"] and "contradictory_id" in result["reasons"]


def test_observation_at_kickoff_is_not_prematch():
    result = qualify([row()], observed=datetime.fromisoformat(KO))
    assert not result["picks"] and result["witnesses"][0]["reason"] == "post_kickoff"


def test_incomplete_traversal_clears_all_choices(monkeypatch):
    monkeypatch.setattr(reader, "MAX_VISITS", 1)
    result = qualify([row()])
    assert result["walkBoundHit"] and not result["traversalComplete"] and not result["picks"]


def test_calendar_adapter_binds_exact_supplied_bytes_and_canonical_names():
    raw = calendar_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    fixtures = reader.accepted_calendar(raw, digest, CLAIM)
    assert len(fixtures) == 1
    fixture = fixtures[0]
    assert (fixture["home"], fixture["away"], fixture["kickoff"]) == ("Synthetic Home", "Synthetic Away", KO)
    assert fixture["calendarSHA"] == digest and fixture["calendarClaim"] == CLAIM
    assert fixture["id"].startswith("calendar:")


def test_calendar_hash_rejection_precedes_json_decoding():
    with pytest.raises(ValueError, match="^ACCEPTED_CALENDAR_SHA$"):
        reader.accepted_calendar(b"not JSON", SHA, CLAIM)
