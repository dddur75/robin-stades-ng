import json
import subprocess
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from robin.source_observatory import sro_successor_view as view


def observation():
    url = sorted(view.OWNER_URLS)[0]
    author = view.owner_id(url)
    pick = dict(id="pick-a", sourceId="SRC_039", authorId=author, authorUrl=url,
                fixtureId="fixture-a", kickoff="2026-11-22T15:00:00Z", selection="native",
                observedAt="2026-11-20T10:00:00Z", firstSeenAt="2026-11-19T10:00:00Z",
                lastSeenAt="2026-11-21T18:18:42Z", responseSha256="a"*64,
                publishedAt=None, publicationTimezone=None, performanceEligible=False,
                versions=[dict(selection="native", observedAt="2026-11-20T10:00:00Z")])
    campaign = dict(campaignId=view.CAMPAIGN_ID, startsAt="2026-11-21T20:00:00Z",
                    expiresAt="2026-11-22T08:10:00Z", slots=3, requests=0, requestsMax=9,
                    successfulSlots=0, state="scheduled", priorFamilyGET=42, familyGETMax=51,
                    canaryRequests=3, canaryReobservations=55,
                    authorIds=sorted(view.OWNER_IDS), poolAuthorIds=sorted(view.OWNER_IDS),
                    nativeXmlSha256="8"*64, canaryReceiptSHA256="9"*64,
                    canaryClaimId=view.CANARY_CLAIM, canaryObservedAt="2026-11-21T18:18:42Z",
                    governingAlgorithmClaimId=view.ALGORITHM_CLAIM, futureReceiptReview="PENDING",
                    canaryPickIds=["pick-a"], allowFutureSuccessfulSlots=False,
                    pendingFutureChoices=0)
    return dict(claimId=view.ALGORITHM_CLAIM, picks=[pick],
                fixtures=[dict(id="fixture-a", kickoff=pick["kickoff"])], sroNextCampaign=campaign)


def public_base():
    p = deepcopy(observation()["picks"][0])
    p["lastSeenAt"] = p["observedAt"]
    return dict(status="ok", claimId="OLD", claimIds=["OLD"], picks=[p],
                distinctPicks=1, authorCount=1, requestCount=39,
                generatedAt=p["observedAt"], sroCampaign=dict(state="expired", requests=39),
                fixtures=[dict(id="fixture-a", kickoff=p["kickoff"])])


def test_public_preserves_every_historical_field_and_adds_only_freshness(monkeypatch):
    base = public_base()
    original = deepcopy(base)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observation(), True))
    result = view.add_sro_next_public(base, Path("unused"))
    assert base == original
    assert result["picks"] == original["picks"]
    assert result["sroCampaign"] == original["sroCampaign"]
    assert result["requestCount"] == 39
    assert result["sroNextCampaign"]["requests"] == 0
    update = result["sroNextCompanion"]["updates"]["pick-a"]
    assert update["lastSeenAt"] == "2026-11-21T18:18:42Z"
    assert update["claimId"] == view.CANARY_CLAIM
    assert view.CANARY_CLAIM in result["claimIds"]
    assert result["distinctPicks"] == 1


@pytest.mark.parametrize("field,value", [
    ("selection", "changed"), ("firstSeenAt", "2026-11-18T00:00:00Z"),
    ("responseSha256", "b"*64), ("publishedAt", "2026-11-19T12:00:00Z"),
    ("performanceEligible", True), ("versions", []),
])
def test_full_fact_conflict_closes_without_replacing_any_history(monkeypatch, field, value):
    observed = observation()
    observed["picks"][0][field] = value
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "unavailable"
    assert "sroNextCompanion" not in result

def test_only_new_r2_fixed_packet_is_accepted_by_directory_guard(tmp_path, monkeypatch):
    assert view.PACKET.name == "sro-next3-e2-r2-20261121"
    path = tmp_path / view.CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(
        directory=str(view.PACKET.parent / "sro-next3-e2-20261121" / "runtime"),
        readerSha256="1"*64, sourceDecisionSha256="2"*64, privacyDecisionSha256="3"*64,
        scaleDecisionSha256="4"*64, taskDecisionSha256="5"*64,
        dataDecisionSha256="6"*64, nativeXmlSha256="7"*64)))
    monkeypatch.setattr(view.subprocess, "run", lambda *a, **k: pytest.fail("no child for old directory"))
    with pytest.raises(ValueError, match="directory"):
        view._read(tmp_path)


@pytest.mark.parametrize("starts,expires,accepted", [
    ("2026-11-21T20:00:00Z", "2026-11-22T08:10:00Z", True),
    ("2026-11-21T19:30:00Z", "2026-11-22T07:40:00Z", False),
    ("2026-11-21T20:00:00Z", "2026-11-22T07:40:00Z", False),
])
def test_app_calendar_binding_accepts_only_new_source_plan(monkeypatch, starts, expires, accepted):
    observed = observation()
    observed["sroNextCampaign"].update(startsAt=starts, expiresAt=expires)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert (result["sroNextCampaign"]["state"] == "scheduled") is accepted

    if not accepted:
        assert "sroNextCompanion" not in result


@pytest.mark.parametrize("mutate", [
    lambda o: o["picks"][0].update(sourceId="SRC_014"),
    lambda o: o["picks"][0].update(authorUrl="https://foreign.invalid/13380"),
    lambda o: o["picks"][0].update(authorId="0"*64),
    lambda o: o["picks"][0].update(fixtureId="missing"),
    lambda o: o["picks"][0].update(observedAt=o["picks"][0]["kickoff"]),
    lambda o: o["sroNextCampaign"].update(campaignId="OLD_SRO"),
    lambda o: o["sroNextCampaign"].update(state="unknown"),
    lambda o: o["sroNextCampaign"].update(requests=True),
    lambda o: o["sroNextCampaign"].update(requests=10),
    lambda o: o["sroNextCampaign"].update(priorFamilyGET=0),
    lambda o: o["sroNextCampaign"].update(poolAuthorIds=["foreign"]),
])
def test_invalid_source_owner_identity_state_or_budget_is_closed(monkeypatch, mutate):
    observed = observation()
    mutate(observed)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "unavailable"


def test_candidates_activate_only_exact_source_owner_and_keep_old_source_authority(monkeypatch):
    observed = observation()
    url = observed["picks"][0]["authorUrl"]
    pick = public_base()["picks"][0]
    row = dict(id="a", sourceUrl=url, collectionEnabled=False,
               qualification=dict(sourceId="SRC_039", picks=[pick], personallyProven=True))
    foreign = dict(id="b", sourceUrl=url, collectionEnabled=False,
                   qualification=dict(sourceId="SRC_014", picks=[]))
    base = dict(candidates=[row, foreign], enabledCount=0,
                qualification=dict(status="ok", sourceOperational=False,
                                   operationalBySource=dict(SRC_039=False)))
    original = deepcopy(base)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert base == original
    assert [r["collectionEnabled"] for r in result["candidates"]] == [True, False]
    assert result["candidates"][0]["qualification"]["picks"] == [pick]
    assert result["candidates"][0]["qualification"]["sroNextCampaignId"] == view.CAMPAIGN_ID
    assert result["qualification"]["sourceOperational"] is False
    assert result["qualification"]["operationalBySource"] == dict(SRC_039=False)


def test_failed_or_missing_reader_preserves_facts_but_never_reuses_next_activation(monkeypatch):
    base = dict(candidates=[dict(id="a", collectionEnabled=True,
                qualification=dict(sroNextCampaignId=view.CAMPAIGN_ID, picks=[dict(id="old")]))],
                qualification=dict(status="ok"), enabledCount=1)
    for response in [None, ValueError("no D")]:
        def read(*a, **k):
            if isinstance(response, Exception):
                raise response
            return response
        monkeypatch.setattr(view, "_read", read)
        result = view.add_sro_next_candidates(base, Path("unused"))
        assert result["candidates"][0]["collectionEnabled"] is False
        assert result["candidates"][0]["qualification"]["picks"] == [dict(id="old")]


def configured(tmp_path, monkeypatch):
    packet = tmp_path / "packet"
    packet.mkdir()
    reader = packet / "read.py"
    reader.write_text("# pinned read only")
    python = tmp_path / "python.exe"
    python.write_bytes(b"synthetic-python")
    (packet / "live").mkdir()
    config = dict(directory=str(packet / "live"), readerSha256=sha256(reader.read_bytes()).hexdigest(),
                  sourceDecisionSha256="1"*64, privacyDecisionSha256="2"*64,
                  scaleDecisionSha256="3"*64, taskDecisionSha256="4"*64,
                  dataDecisionSha256="5"*64, nativeXmlSha256="8"*64)
    path = tmp_path / view.CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(view, "PACKET", packet)
    monkeypatch.setattr(view, "READER_SHA256", sha256(reader.read_bytes()).hexdigest(), raising=False)
    monkeypatch.setattr(view, "PYTHON", python)
    monkeypatch.setattr(view, "PYTHON_SHA256", sha256(python.read_bytes()).hexdigest())
    return path, config


def test_reader_isolated_python_all_five_decisions_and_shared_deadline(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=json.dumps(dict(observed=observation(), operational=True)))
    monkeypatch.setattr(view.subprocess, "run", run)
    monkeypatch.setattr(view, "monotonic", lambda: 100)
    assert view._read(tmp_path, deadline=101)[1] is True
    command, options = calls[0]
    assert command[1:4] == ["-I", "-S", "-B"]
    for flag in ["source", "privacy", "scale", "task", "data"]:
        assert "--"+flag+"-decision-sha256" in command
    assert 0 < options["timeout"] <= 0.7
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with pytest.raises(TimeoutError):
        view._read(tmp_path, deadline=100.2)
    assert len(calls) == 1


@pytest.mark.parametrize("change", [
    lambda c: c.pop("dataDecisionSha256"),
    lambda c: c.update(dataDecisionSha256=""),
    lambda c: c.update(directory="foreign"),
    lambda c: c.update(extra="not allowed"),
    lambda c: c.update(readerSha256="0"*64),
])
def test_bad_config_refuses_before_child(tmp_path, monkeypatch, change):
    path, config = configured(tmp_path, monkeypatch)
    change(config)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(view.subprocess, "run", lambda *a, **k: pytest.fail("must not start child"))
    with pytest.raises((ValueError, OSError)):
        view._read(tmp_path)


def test_observed_xml_binding_and_operational_boolean_fail_closed(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    for value in [dict(observed=observation(), operational=1),
                  dict(observed=observation(), operational=True)]:
        if type(value["operational"]) is bool:
            value["observed"]["sroNextCampaign"]["nativeXmlSha256"] = "0"*64
        monkeypatch.setattr(view.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(stdout=json.dumps(value)))
        with pytest.raises(ValueError):
            view._read(tmp_path)

def test_pending_future_ids_are_held_without_losing_approved_history_or_canary(monkeypatch):
    observed = observation()
    future = {**deepcopy(observed["picks"][0]), "id": "future-a"}
    observed["picks"].append(future)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "scheduled"
    assert result["sroNextCompanion"]["pendingNewPickCount"] == 1
    assert result["sroNextCompanion"]["updates"]["pick-a"]["claimId"] == view.CANARY_CLAIM


def test_future_contract_needs_actual_receipt_and_does_not_inherit_canary_claim(monkeypatch):
    observed = observation()
    observed["sroNextCampaign"]["futureReceiptReview"] = "CONTRACT_VALIDATED"
    observed["sroNextCampaign"]["allowFutureSuccessfulSlots"] = True
    observed["picks"][0]["lastSeenAt"] = "2026-11-21T19:30:10Z"
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    assert view.add_sro_next_public(base, Path("unused"))["sroNextCampaign"]["state"] == "unavailable"
    observed["sroNextCampaign"]["receiptLineage"] = [dict(
        slot="2026-11-21T19:30:00Z", observedAt="2026-11-21T19:30:10Z",
        pickIds=["pick-a"], candidateSHA256="a"*64, receiptSHA256="b"*64,
        captureJournalPrefixSHA256="c"*64, captureJournalHead="d"*64,
        futureReceiptReview="CONTRACT_VALIDATED")]
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    update = result["sroNextCompanion"]["updates"]["pick-a"]
    assert update["claimId"] == view.ALGORITHM_CLAIM
    assert update["receiptSHA256"] == "b"*64
    assert update["receiptSHA256"] != observed["sroNextCampaign"]["canaryReceiptSHA256"]


def test_timeout_and_large_or_non_json_child_fail_closed(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("mock-source-reader", kwargs["timeout"])
    for result in [timeout, lambda *a, **k: SimpleNamespace(stdout="x"*4_000_001),
                   lambda *a, **k: SimpleNamespace(stdout="not JSON")]:
        monkeypatch.setattr(view.subprocess, "run", result)
        base = public_base()
        view_result = view.add_sro_next_public(base, tmp_path, deadline=view.monotonic()+1)
        assert view_result["picks"] == base["picks"]
        assert view_result["sroNextCampaign"]["state"] == "unavailable"


def test_no_qualifier_can_reassign_a_pick_from_another_owner(monkeypatch):
    observed = observation()
    old = {**public_base()["picks"][0], "authorUrl": sorted(view.OWNER_URLS)[1]}
    base = dict(candidates=[dict(id="old", sourceUrl=old["authorUrl"], collectionEnabled=False,
                qualification=dict(sourceId="SRC_039", picks=[old]))],
                qualification=dict(status="ok"), enabledCount=0)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert result["qualification"]["sroNextState"] == "unavailable"
    assert result["candidates"] == base["candidates"]

def test_malformed_time_is_closed_without_losing_base_facts(monkeypatch):
    observed = observation()
    observed["picks"][0]["lastSeenAt"] = False
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "unavailable"


def test_foreign_existing_pick_cannot_activate_an_unrelated_owner_row(monkeypatch):
    observed = observation()
    wrong_url = sorted(view.OWNER_URLS)[1]
    base = dict(candidates=[dict(id="wrong", sourceUrl=wrong_url, collectionEnabled=False,
                qualification=dict(sourceId="SRC_039", picks=public_base()["picks"]))],
                qualification=dict(status="ok"), enabledCount=0)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert result["qualification"]["sroNextState"] == "unavailable"
    assert result["candidates"] == base["candidates"]


def test_sparse_or_null_qualification_does_not_crash_closed_candidate_projection(monkeypatch):
    base = dict(candidates=[dict(id="a", collectionEnabled=False, qualification=None)],
                qualification=dict(status="ok"), enabledCount=0)
    monkeypatch.setattr(view, "_read", lambda *a, **k: None)
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert result["candidates"] == base["candidates"]
    assert result["qualification"]["sroNextState"] == "not_configured"

def test_reader_rejects_postprocessing_past_shared_deadline(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    ticks = iter([100.0, 101.1])
    monkeypatch.setattr(view, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(view.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=json.dumps(dict(
                            observed=observation(), operational=True))))
    with pytest.raises(TimeoutError):
        view._read(tmp_path, deadline=101.0)

def test_all_67_sro_facts_ignore_unrelated_dual_olbg_representations(monkeypatch):
    observed = observation()
    urls = sorted(view.OWNER_URLS)
    seed = observed["picks"][0]
    observed["picks"] = []
    rows = []
    for index, url in enumerate(urls):
        personal = []
        for number in range(index, 67, len(urls)):
            pick = {**deepcopy(seed), "id": f"sro-{number}", "authorUrl": url,
                    "authorId": view.owner_id(url)}
            if number >= 55:
                pick["lastSeenAt"] = pick["observedAt"]
            observed["picks"].append(pick)
            personal.append({**deepcopy(pick), "lastSeenAt": pick["observedAt"]})
        rows.append(dict(id=f"owner-{index}", sourceUrl=url, collectionEnabled=False,
                         qualification=dict(sourceId="SRC_039", picks=personal)))
    observed["sroNextCampaign"]["canaryPickIds"] = [f"sro-{n}" for n in range(55)]
    unrelated = [
        dict(id="olbg-a", sourceUrl="https://www.olbg.com/tipsters/tips/1",
             collectionEnabled=False, qualification=dict(sourceId="SRC_014",
             picks=[dict(id="olbg-existing", sourceId="SRC_014", market="source_native")])),
        dict(id="olbg-b", sourceUrl="https://www.olbg.com/tipsters/tips/1",
             collectionEnabled=False, qualification=dict(sourceId="SRC_014",
             picks=[dict(id="olbg-existing", sourceId="SRC_014", market="source_native_opaque")])),
    ]
    base = dict(candidates=rows+deepcopy(unrelated), qualification=dict(status="ok"), enabledCount=0)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert result["qualification"]["sroNextState"] == "ok"
    assert result["enabledCount"] == 8
    assert result["candidates"][-2:] == unrelated
    assert sum(len(row["qualification"].get("sroNextCompanion", {}).get("updates", {}))
               for row in result["candidates"]) == 55
    for before, after in zip(rows, result["candidates"]):
        assert after["qualification"]["picks"] == before["qualification"]["picks"]


def test_foreign_source_collision_on_an_incoming_sro_id_is_still_a_veto(monkeypatch):
    observed = observation()
    old = {**deepcopy(observed["picks"][0]), "sourceId": "SRC_014"}
    base = dict(candidates=[dict(id="foreign", sourceUrl="https://www.olbg.com/tipsters/tips/1",
                collectionEnabled=False, qualification=dict(sourceId="SRC_014", picks=[old]))],
                qualification=dict(status="ok"), enabledCount=0)
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    result = view.add_sro_next_candidates(base, Path("unused"))
    assert result["qualification"]["sroNextState"] == "unavailable"
    assert result["candidates"] == base["candidates"]


def test_pending_producer_filters_new_ids_but_preserves_its_exact_pending_count(monkeypatch):
    observed = observation()
    observed["sroNextCampaign"]["pendingFutureChoices"] = 1
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["pendingFutureChoices"] == 1
    assert result["sroNextCompanion"]["pendingNewPickCount"] == 1


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None])
def test_pending_producer_counter_must_be_a_nonnegative_integer(monkeypatch, value):
    observed = observation()
    observed["sroNextCampaign"]["pendingFutureChoices"] = value
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "unavailable"


@pytest.mark.parametrize("lineage", [[None], [False], ["bad"], {}, None])
def test_malformed_future_lineage_keeps_history_and_closes_overlay(monkeypatch, lineage):
    observed = observation()
    observed["sroNextCampaign"].update(futureReceiptReview="CONTRACT_VALIDATED",
                                     allowFutureSuccessfulSlots=True, receiptLineage=lineage)
    observed["picks"][0]["lastSeenAt"] = "2026-11-21T19:30:10Z"
    monkeypatch.setattr(view, "_read", lambda *a, **k: (observed, True))
    base = public_base()
    result = view.add_sro_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["sroNextCampaign"]["state"] == "unavailable"







def test_reader_digest_cannot_be_replaced_by_configuration(tmp_path, monkeypatch):
    path, config = configured(tmp_path, monkeypatch)
    reader = view.PACKET / 'read.py'
    reader.write_text('# different code with matching untrusted config hash')
    config['readerSha256'] = sha256(reader.read_bytes()).hexdigest()
    path.write_text(json.dumps(config))
    monkeypatch.setattr(view.subprocess, 'run', lambda *a, **k: pytest.fail('untrusted reader executed'))
    with pytest.raises(ValueError):
        view._read(tmp_path)

def test_same_named_packet_clone_is_rejected_before_child(tmp_path, monkeypatch):
    path, config = configured(tmp_path, monkeypatch)
    foreign = tmp_path / 'foreign' / view.PACKET.name / 'live'
    foreign.mkdir(parents=True)
    (foreign.parent / 'read.py').write_bytes((view.PACKET / 'read.py').read_bytes())
    config['directory'] = str(foreign)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(view.subprocess, 'run', lambda *a, **k: pytest.fail('foreign packet executed'))
    with pytest.raises(ValueError):
        view._read(tmp_path)


def test_sro_packet_link_refuses_before_child(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p == view.PACKET or original(p))
    monkeypatch.setattr(view.subprocess, 'run', lambda *a, **k: pytest.fail('redirected packet executed'))
    with pytest.raises(ValueError):
        view._read(tmp_path)


def test_missing_private_config_survives_a_shallow_checkout(tmp_path):
    from types import ModuleType
    shallow = Path(Path(view.__file__).anchor) / 'portable-reader-fixture'
    module = ModuleType('robin.source_observatory.portability_fixture')
    module.__package__ = 'robin.source_observatory'
    module.__file__ = str(shallow / 'src' / 'robin' / 'source_observatory' / Path(view.__file__).name)
    source = Path(view.__file__).read_text(encoding='utf-8')
    exec(compile(source, module.__file__, 'exec'), vars(module))
    assert module._read(tmp_path) is None
