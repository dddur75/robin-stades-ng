"""Synthetic E2 contracts. No real source request or scheduler installation."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from robin.source_observatory import notbetting_recurring_v4 as engine
from robin.source_observatory.connectors import Response, canonical, read_events

NOW = datetime(2026, 11, 21, 5, tzinfo=UTC)
NEW_ID = "11111111-1111-4111-8111-111111111111"


def fixtures():
    return [
        dict(
            id=f"epl-{i}",
            label=f"Home {i} – Away {i}",
            homeAliases=[f"Home {i}"],
            awayAliases=[f"Away {i}"],
            kickoff=f"2026-11-21T{hour}:00Z",
        )
        for i, hour in enumerate(("12:30", "15:00", "15:00", "15:00", "15:00"))
    ]


def native(identifier=NEW_ID, fixture=1):
    return dict(
        id=identifier,
        event=f"Home {fixture} - Away {fixture}",
        pick="Literal choice",
        competition="Premier League",
        date=fixtures()[fixture]["kickoff"],
        createdAt="2026-11-20T20:00:00Z",
        tipsterId=engine.OWNER,
        tipster={
            "user": {
                "id": engine.OWNER,
                "username": "ELIMAGAR",
                "tipster": {"id": engine.OWNER, "userId": engine.OWNER},
            }
        },
    )


def qualify(rows, observed=NOW, calendar=None):
    return engine.qualify_documents(
        {"0": rows}, calendar or fixtures(), observed, response_sha="a" * 64, parser_sha="b" * 64
    )


def test_unseen_uuid_is_admitted_with_its_own_four_owner_ids_date_and_choice():
    result = qualify([native()])
    assert result["status"] == "qualified"
    pick = result["picks"][0]
    assert pick["sourceTipId"] == NEW_ID
    assert pick["firstSeenAt"] == pick["observedAt"] == "2026-11-21T05:00:00+00:00"
    assert pick["publishedAt"] is None and pick["publishedCivilDate"] is None
    assert pick["sourceFields"]["createdAt"] == "2026-11-20T20:00:00Z"
    assert pick["market"] == "source_native_opaque"
    assert all(
        pick[k] is False
        for k in (
            "performanceEvaluationAllowed",
            "settlementAllowed",
            "marketInterpretationAllowed",
        )
    )
    assert not any(k == "name" or k.endswith(".name") for k in pick["sourceFields"])


@pytest.mark.parametrize(
    "defect", ["owner", "nested_owner", "username", "date", "neighbor", "reco"]
)
def test_unproved_native_context_is_not_admitted(defect):
    row = native()
    if defect == "owner":
        row["tipsterId"] = str(UUID(int=8))
    elif defect == "nested_owner":
        del row["tipster"]["user"]["tipster"]["userId"]
    elif defect == "username":
        row["tipster"]["user"]["username"] = "AnotherAlias"
    elif defect == "date":
        row["date"] = "2026-11-22T15:00:00Z"
    elif defect == "neighbor":
        del row["date"]
        row = {"date": "2026-11-21T15:00:00Z", "rows": [row]}
    else:
        row = {"recommendations": [row]}
    assert not qualify([row])["picks"]


def test_references_resolve_only_within_closed_owner_and_never_copy_civil_name():
    row = native()
    owner = row.pop("tipster")
    owner["user"]["name"] = "Forbidden Civil Name"
    row["tipster"] = "$1"
    result = engine.qualify_documents(
        {"0": [row], "1": owner}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert len(result["picks"]) == 1
    assert "Forbidden Civil Name" not in json.dumps(result)


def test_ambiguous_calendar_and_post_kickoff_record_are_individually_excluded():
    calendar = fixtures()
    calendar.append(dict(calendar[1], id="duplicate"))
    assert not qualify([native()], calendar=calendar)["picks"]
    result = qualify(
        [native(str(UUID(int=9)), fixture=0), native()], datetime(2026, 11, 21, 13, tzinfo=UTC)
    )
    assert [p["sourceTipId"] for p in result["picks"]] == [NEW_ID]
    assert result["witnesses"][0]["reason"] == "post_kickoff"


def test_same_id_contradiction_stops_without_selecting_a_favorable_variant():
    other = native()
    other["pick"] = "Contradiction"
    result = qualify([native(), other])
    assert result["status"] == "partial"
    assert result["reason"] == "contradictory_id"
    assert result["picks"] == []


def test_same_id_with_a_different_owner_variant_halts_in_both_orders():
    other = native()
    other["tipsterId"] = str(UUID(int=88))
    other["tipster"]["user"]["id"] = str(UUID(int=88))
    other["tipster"]["user"]["tipster"] = {"id": str(UUID(int=88)), "userId": str(UUID(int=88))}
    for rows in ([native(), other], [other, native()]):
        assert qualify(rows)["reason"] == "contradictory_id"


def test_explicit_gate_is_applied_to_content_but_premium_word_alone_is_not_a_gate():
    row = native()
    row["isPremium"] = True
    row["isFree"] = False
    assert len(qualify([row])["picks"]) == 1
    row["requiresSubscription"] = True
    assert not qualify([row])["picks"]
    assert not qualify([{"requiresAuthentication": True, "rows": [native()]}])["picks"]


def test_twenty_eligible_cap_and_three_witness_sample_are_distinct():
    rows = [native(str(UUID(int=i + 1))) for i in range(21)]
    result = qualify(rows)
    assert result["status"] == "partial" and result["omittedAdmissible"] == 1
    assert len(result["picks"]) == 20
    rows = [dict(native(str(UUID(int=i + 1))), competition="Other") for i in range(4)]
    result = qualify(rows)
    assert result["status"] == "partial" and result["omittedWitnesses"] == 1
    assert len(result["witnesses"]) == 3


def test_passive_flight_codec_does_not_execute_or_follow_any_script():
    flight = "0:" + json.dumps([native()]) + "\n"
    body = (
        "<script>self.__next_f.push(" + json.dumps([1, flight]) + ");</script>"
        '<script src="https://forbidden.example/x.js"></script>'
    ).encode()
    assert engine.decode_capture(body, "text/html")["0"][0]["id"] == NEW_ID


@pytest.mark.parametrize(
    "wrapper",
    [
        "<script type='text/plain'>{push}</script>",
        "<script type='application/json'>{push}</script>",
        "<script>const example = {quoted};</script>",
        "<script>/* {push} */</script>",
        "<script>// {push}\n</script>",
    ],
)
def test_passive_codec_never_promotes_inert_text_strings_or_comments(wrapper):
    flight = "0:" + json.dumps([native()]) + "\n"
    push = "self.__next_f.push(" + json.dumps([1, flight]) + ");"
    body = wrapper.format(push=push, quoted=json.dumps(push)).encode()
    assert engine.decode_capture(body, "text/html") == {}


def test_contradictory_next_data_documents_fail_closed():
    body = (
        "<script id='__NEXT_DATA__' type='application/json'>{\"value\":1}</script>"
        "<script id='__NEXT_DATA__' type='application/json'>{\"value\":2}</script>"
    ).encode()
    with pytest.raises(ValueError, match="contradictory"):
        engine.decode_capture(body, "text/html")


def test_native_flight_fragments_preserve_document_order_across_scripts():
    flight = "0:" + json.dumps([native()]) + "\n"
    parts = (flight[:17], flight[17:])
    body = "".join(
        "<script>self.__next_f.push(" + json.dumps([1, part]) + ");</script>" for part in parts
    ).encode()
    assert engine.decode_capture(body, "text/html")["0"][0]["id"] == NEW_ID


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


@pytest.fixture
def packet(tmp_path, monkeypatch):
    root = tmp_path / "root"
    directory = root / engine.PACKET_DIRECTORY
    root.mkdir()
    for name in engine.PIN_PATHS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic pinned code\n", encoding="utf-8")
    parent = fixtures() + [dict(fixtures()[1], id=f"j11-other-{i}") for i in range(9)]
    parent_hash = sha256(canonical(parent)).hexdigest()
    monkeypatch.setattr(engine, "PARENT_CALENDAR_SHA", parent_hash)
    monkeypatch.setattr(engine, "CANARY_ID", NEW_ID)
    monkeypatch.setattr(engine, "baseline_choices", lambda root: [])
    write_json(root / "private/parent.json", {"fixtures": parent})
    legal = root / "private/legal.json"
    write_json(legal, {"synthetic": True})
    monkeypatch.setattr(engine, "LEGAL_SHA", sha256(legal.read_bytes()).hexdigest())
    prior = {}
    for i, (count, elapsed) in enumerate(((4, 6203), (1, 1297), (2, 3125), (2, 9187))):
        path = (
            "cockpit/.ci/notbetting-recurring-e2-20261121/events.jsonl"
            if i == 3
            else f"private/receipt-{i}.jsonl"
        )
        d = root / f"private/receipt-{i}"
        mission = {
            "mission_id": "old",
            "authorized_stages": ["E1", "E2"],
            "maximum_stage": "E2",
            "external_effects": {},
            "compute_budget": 1,
            "time_budget": 600,
            "source_hash": "a" * 64,
            "expires_at": "2026-11-21T13:15:00Z",
        }
        journal = engine.Journal(d, mission, now=lambda: NOW)
        for _ in range(count):
            journal.append("REQUEST_RESERVED", elapsedMilliseconds=0)
        journal.append("FINISHED", elapsedMilliseconds=elapsed)
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes((d / "events.jsonl").read_bytes())
        prior[path] = sha256((root / path).read_bytes()).hexdigest()
    monkeypatch.setattr(engine, "PRIOR_PINS", prior)
    plan = engine.draft_plan(fixtures(), canary_at="2026-11-21T04:35:00Z")
    plan["parentCalendar"] = {
        "path": "private/parent.json",
        "sha256": sha256((root / "private/parent.json").read_bytes()).hexdigest(),
    }
    plan["legal"] = {
        "path": "private/legal.json",
        "sha256": engine.LEGAL_SHA,
        "observedAt": "2026-11-20T16:15:14.330276Z",
    }
    plan["priorReceiptPins"] = prior
    plan["codePins"] = engine.code_pins(root)
    digest = sha256(canonical(plan)).hexdigest()
    mission = engine.mission_for(plan)
    write_json(directory / "plan.json", plan)
    write_json(directory / "mission.json", mission)
    context = {
        "planSha256": digest,
        "manifestSha256": sha256(canonical(mission)).hexdigest(),
        "keys": ["C0", "C1", "C4"],
        "scaleDecision": "SCALE_APPROVED",
    }
    record = {
        "decision_id": "synthetic-scale",
        "record_type": "DECISION",
        "decision": "PASS_AND_SCALE",
        "previous_hash": "0" * 64,
        "context": context,
    }
    record["hash"] = sha256(canonical(record)).hexdigest()
    ledger = root / "reports/council/decision-ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_bytes(canonical(record) + b"\n")
    approval = {
        "planSha256": digest,
        "manifestSha256": context["manifestSha256"],
        "decisionId": record["decision_id"],
        "decisionHash": record["hash"],
    }
    write_json(directory / "approval.json", approval)
    return root, directory, digest, plan


def test_package_validation_is_readonly_and_rejects_code_or_authority_drift(packet):
    root, directory, digest, plan = packet
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    assert engine.validate_package(root, directory, digest, now=NOW)["plan"] == plan
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before
    (root / engine.PIN_PATHS[0]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="code"):
        engine.validate_package(root, directory, digest, now=NOW)


class Clock:
    def __init__(self):
        self.value = NOW
        self.elapsed = 0.0

    def now(self):
        return self.value

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds
        self.value += timedelta(seconds=seconds)


def response(url, rows=None):
    if url == engine.ROBOTS:
        return Response(
            200,
            b"User-agent: *\nAllow: /en/tipsters-league/picks\nDisallow: /api/\n",
            "text/plain",
            None,
        )
    flight = "0:" + json.dumps(rows if rows is not None else [native()]) + "\n"
    body = ("<script>self.__next_f.push(" + json.dumps([1, flight]) + ");</script>").encode()
    return Response(200, body, "text/html", None)


def accept_canary(root, directory, digest):
    # A real canary must exist and its exact result hash must be countersigned.
    now = datetime(2026, 11, 21, 4, 35, tzinfo=UTC)
    clock = Clock()
    clock.value = now
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "canary",
        get=lambda url, **kw: response(url),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "canary_pending_review"
    proof = {
        "planSha256": digest,
        "keys": ["C0", "C1", "C2", "C4"],
        "canaryEventHash": result["eventHash"],
        "decisionId": "canary-accepted",
    }
    original = root / "reports/council/decision-ledger.jsonl"
    records = [json.loads(x) for x in original.read_bytes().splitlines()]
    record = {
        "decision_id": "canary-accepted",
        "record_type": "DECISION",
        "decision": "PASS_AND_HOLD",
        "previous_hash": records[-1]["hash"],
        "context": proof,
    }
    record["hash"] = sha256(canonical(record)).hexdigest()
    original.write_bytes(original.read_bytes() + canonical(record) + b"\n")
    write_json(directory / "canary-acceptance.json", dict(proof, decisionHash=record["hash"]))


def test_canary_is_separate_and_recurring_slot_requires_four_key_acceptance(packet):
    root, directory, digest, _ = packet
    called = []
    with pytest.raises(ValueError, match="canary"):
        engine.execute_pass(
            root,
            directory,
            digest,
            "2026-11-21T05:00:00Z",
            get=lambda *a, **k: called.append(1),
            now=lambda: NOW,
        )
    assert called == []
    accept_canary(root, directory, digest)
    clock = Clock()
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda url, **kw: response(url),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "completed"
    assert result["newChoices"] == 0
    assert len(engine.read_companion(directory)["picks"]) == 1


def test_duplicate_slot_has_zero_get_and_orphan_lock_stops_campaign(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()

    def run():
        return engine.execute_pass(
            root,
            directory,
            digest,
            "2026-11-21T05:00:00Z",
            get=lambda url, **kw: response(url),
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert run()["state"] == "completed"
    assert run()["state"] == "duplicate"
    (directory / "busy.lock").write_text("orphan", encoding="utf-8")
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T07:00:00Z",
        get=lambda *a, **k: pytest.fail("orphan GET"),
        now=clock.now,
    )
    assert result["state"] == "halted"
    assert not engine.read_view(root, directory, digest, now=clock.value)["active"]


@pytest.mark.parametrize("failure", ["late", "timeout", "empty", "robots", "conflict"])
def test_runtime_failure_preserves_closed_facts_and_halts_without_retry(packet, failure):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if failure == "late":
            clock.sleep(125)
        if failure == "timeout":
            raise TimeoutError("synthetic")
        if failure == "robots":
            return Response(200, b"User-agent: *\nDisallow: /\n", "text/plain", None)
        row = native()
        if failure == "conflict":
            row["pick"] = "contradictory new value"
        return response(url, [] if failure == "empty" else [row])

    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=get,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert len(calls) <= 2
    assert len(engine.read_companion(directory)["picks"]) == 1
    assert engine.read_view(root, directory, digest, now=clock.value)["active"] is False


def test_reservation_fsync_expiry_is_rechecked_before_any_get(packet, monkeypatch):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    append = engine.Journal.append

    def delayed(self, kind, **payload):
        event = append(self, kind, **payload)
        if kind == "REQUEST_RESERVED":
            clock.sleep(125)
        return event

    monkeypatch.setattr(engine.Journal, "append", delayed)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda *a, **k: pytest.fail("expired GET"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert read_events(directory / "events.jsonl")[-1]["kind"] == "CAMPAIGN_HALTED"


def test_missed_slot_or_modified_manifest_never_permits_a_source_request(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    with pytest.raises(ValueError, match="manifest"):
        mission = json.loads((directory / "mission.json").read_text())
        mission["compute_budget"] = 999
        write_json(directory / "mission.json", mission)
        engine.validate_package(root, directory, digest, now=NOW)


def test_missed_predecessor_and_request_deadline_halt_without_catch_up(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T07:00:00Z",
        get=lambda *a, **k: pytest.fail("missed predecessor GET"),
        now=clock.now,
    )
    assert result["state"] == "halted"
    assert (
        read_events(directory / "events.jsonl")[-1]["reason"]
        == "earlier slot missed; catch-up forbidden"
    )


def test_response_crossing_twelve_seconds_is_charged_and_never_projected(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()

    def slow(url, **kwargs):
        clock.sleep(12.01)
        return response(url)

    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=slow,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert read_events(directory / "events.jsonl")[-1]["elapsedMilliseconds"] >= 20010


def test_overflow_keeps_bounded_unadmitted_projection_and_counts_omissions(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    rows = [native(str(UUID(int=i + 1))) for i in range(21)]
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda url, **kw: response(url, rows),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    rejected = [e for e in read_events(directory / "events.jsonl") if e["kind"] == "PASS_REJECTED"]
    assert rejected[0]["projection"]["omittedAdmissible"] == 1
    assert len(rejected[0]["projection"]["picks"]) == 20
    assert len(engine.read_companion(directory)["picks"]) == 1


def test_transport_rejects_every_route_except_the_two_exact_urls():
    with pytest.raises(ValueError, match="scope"):
        engine.public_get("https://notbetting.com/api/picks")


@pytest.mark.parametrize("size,accepted", [(4_000_000, True), (4_000_001, False)])
def test_isolated_transport_accepts_four_megabytes_and_reads_only_one_sentinel(
    monkeypatch, size, accepted
):
    calls = []
    stream = io.BytesIO(b"x" * size)

    class FakeSocket:
        def settimeout(self, seconds):
            assert 0 < seconds <= 12

        def connect(self, address):
            calls.append(("connect", address))

        def do_handshake(self):
            pass

        def shutdown(self, mode):
            pass

        def close(self):
            pass

    class Context:
        def wrap_socket(self, sock, *, server_hostname, do_handshake_on_connect):
            assert server_hostname == "notbetting.com"
            assert do_handshake_on_connect is False
            return sock

    class Incoming:
        status = 200

        def getheader(self, key, default=None):
            return {"Content-Type": "text/html", "Content-Encoding": "identity"}.get(key, default)

        def read1(self, maximum):
            return stream.read(maximum)

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, target, *, headers):
            assert method == "GET" and target == "/en/tipsters-league/picks"
            assert headers["Accept-Encoding"] == "identity"

        def getresponse(self):
            return Incoming()

        def close(self):
            pass

    monkeypatch.setattr(
        engine.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    monkeypatch.setattr(engine.socket, "socket", lambda *a: FakeSocket())
    monkeypatch.setattr(engine.ssl, "create_default_context", Context)
    monkeypatch.setattr(engine.http.client, "HTTPConnection", Connection)
    if accepted:
        assert len(engine.public_get(engine.SOURCE).body) == 4_000_000
    else:
        with pytest.raises(ValueError, match="body bound"):
            engine.public_get(engine.SOURCE)
    assert stream.tell() == size and len(calls) == 1


@pytest.mark.parametrize("phase", ["context", "handshake"])
def test_tls_setup_cannot_send_get_after_the_total_deadline(monkeypatch, phase):
    clock = [0.0]
    wrapped = []
    sent = []

    class FakeSocket:
        def settimeout(self, seconds):
            assert 0 < seconds <= 12

        def connect(self, address):
            pass

        def do_handshake(self):
            if phase == "handshake":
                clock[0] = 13.0

        def shutdown(self, mode):
            pass

        def close(self):
            pass

    class Context:
        def __init__(self):
            if phase == "context":
                clock[0] = 13.0

        def wrap_socket(self, sock, *, server_hostname, do_handshake_on_connect=True):
            wrapped.append(server_hostname)
            if do_handshake_on_connect:
                sock.do_handshake()
            return sock

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            sent.append(True)
            pytest.fail("GET after TLS consumed the total deadline")

        def close(self):
            pass

    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        engine.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    monkeypatch.setattr(engine.socket, "socket", lambda *a: FakeSocket())
    monkeypatch.setattr(engine.ssl, "create_default_context", Context)
    monkeypatch.setattr(engine.http.client, "HTTPConnection", Connection)
    with pytest.raises(TimeoutError, match="deadline"):
        engine.public_get(engine.SOURCE)
    assert not sent
    assert wrapped == ([] if phase == "context" else ["notbetting.com"])


def test_scalar_companion_journal_preserves_the_complete_e1_base(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    (directory / "events.jsonl").write_text("null\n", encoding="utf-8")
    base = base_view()
    base["picks"] = qualify([native()])["picks"]
    before = deepcopy(base)
    result = engine.read_view(root, directory, digest, now=NOW, base=base)
    assert base == before and result["picks"] == before["picks"]
    assert result["fixtures"] == before["fixtures"]
    assert result["state"] == "unavailable"
    assert result["active"] is False and result["recurringAuthority"] is False


@pytest.mark.parametrize("variable", ["SSLKEYLOGFILE", "SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_transport_environment_injection_is_refused_before_dns_or_reservation(
    packet, monkeypatch, variable
):
    root, directory, digest, _ = packet
    monkeypatch.setenv(variable, "synthetic-forbidden-path")
    monkeypatch.setattr(engine.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS attempted"))
    with pytest.raises(ValueError, match="TLS environment"):
        engine.public_get(engine.SOURCE)
    with pytest.raises(ValueError, match="TLS environment"):
        engine.execute_pass(
            root,
            directory,
            digest,
            "canary",
            get=lambda *a, **k: pytest.fail("GET attempted"),
            now=lambda: NOW,
        )
    assert not (directory / "events.jsonl").exists()


def test_five_passes_consume_exact_ten_and_reobservation_keeps_one_choice(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    calls = []
    clock = Clock()
    for slot in engine.SLOTS:
        clock.value = datetime.fromisoformat(slot.replace("Z", "+00:00"))

        def get(url, **kwargs):
            calls.append(url)
            return response(url)

        assert (
            engine.execute_pass(
                root,
                directory,
                digest,
                slot,
                get=get,
                now=clock.now,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )["state"]
            == "completed"
        )
    events = read_events(directory / "events.jsonl")
    assert sum(e["kind"] == "REQUEST_RESERVED" for e in events) == 10
    assert len(calls) == 8  # The distinct canary consumed the first two.
    assert len(engine.read_companion(directory)["picks"]) == 1


def test_budget_exhaustion_is_not_reset_by_a_new_slot(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    packet_data = engine.validate_package(root, directory, digest, now=NOW)
    journal = engine.Journal(directory, packet_data["mission"], now=lambda: NOW)
    for _ in range(8):
        journal.append("REQUEST_RESERVED", elapsedMilliseconds=10000)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda *a, **k: pytest.fail("exhausted GET"),
        now=lambda: NOW,
    )
    assert result["state"] == "halted"
    assert (
        sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(directory / "events.jsonl")) == 10
    )


def test_start_near_slot_close_cannot_reserve_an_unfinishable_get(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    clock.value = NOW + timedelta(seconds=110)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda *a, **k: pytest.fail("unfinishable GET"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert (
        sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(directory / "events.jsonl")) == 2
    )


@pytest.mark.parametrize(
    "body,media",
    [
        (b"<html>challenge</html>", "text/html"),
        (b"User-agent: *\nAllow: /\n# captcha", "text/plain"),
        (b"User-agent: *\nAllow: /\n\x00", "text/plain"),
    ],
)
def test_robots_200_challenge_never_reaches_content_get(packet, body, media):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return Response(200, body, media, None)

    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=get,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert calls == [engine.ROBOTS]


def test_reobservation_preserves_e1_first_seen_and_closed_identity(packet, monkeypatch):
    root, directory, digest, _ = packet
    old = qualify([native()], datetime(2026, 11, 21, 1, 30, tzinfo=UTC))["picks"][0]
    monkeypatch.setattr(engine, "baseline_choices", lambda root: [old])
    accept_canary(root, directory, digest)
    fact = engine.read_companion(directory)["picks"][0]
    assert fact["firstSeenAt"] == "2026-11-21T01:30:00+00:00"
    assert fact["sourceFields"]["tipster.user.tipster.userId"] == engine.OWNER


@pytest.mark.parametrize(
    "script", ["notbetting-v4-collect.py", "notbetting-v4-validate.py", "notbetting-v4-read.py"]
)
def test_cli_with_absent_package_refuses_without_creating_files(tmp_path, script):
    root = Path(__file__).resolve().parents[2]
    directory = tmp_path / "absent"
    process = subprocess.run(
        [
            sys.executable,
            "-B",
            str(root / "cockpit/scripts" / script),
            "--directory",
            str(directory),
            "--plan-sha256",
            "a" * 64,
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        check=False,
    )
    assert process.returncode == 2
    assert json.loads(process.stdout)["active"] is False
    assert not directory.exists()


def test_windows_validate_only_refuses_before_reaching_native_task_commands(tmp_path):
    pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    root = Path(__file__).resolve().parents[2]
    script = root / "cockpit/scripts/notbetting-v4-register.ps1"
    process = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            "-Directory",
            str(tmp_path / "absent"),
            "-PlanSha256",
            "a" * 64,
            "-Python",
            sys.executable,
            "-ValidateOnly",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode != 0
    assert "Independent canary receipt or exact package absent" in process.stderr
    assert not (tmp_path / "absent").exists()


def test_merge_keeps_e1_first_seen_and_does_not_regress_observation_horizon():
    e2 = qualify([native()])["picks"][0]
    old = dict(e2, firstSeenAt="2026-11-21T01:00:00Z", observedAt="2026-11-21T01:30:00Z")
    base = dict(
        picks=[old],
        fixtures=fixtures(),
        claimIds=["old"],
        generatedAt="2026-11-21T06:00:00Z",
        sourceObservedThrough="2026-11-21T06:00:00Z",
    )
    merged = engine.merge_view(
        base, {"picks": [e2], "fixtures": fixtures(), "claimId": "synthetic"}
    )
    assert len(merged["picks"]) == 1
    assert merged["picks"][0]["firstSeenAt"] == "2026-11-21T01:00:00Z"
    assert merged["sourceObservedThrough"] == "2026-11-21T06:00:00Z"
    changed = deepcopy(e2)
    changed["selection"] = "Changed"
    with pytest.raises(ValueError, match="contradict"):
        engine.merge_view(
            base, {"picks": [changed], "fixtures": fixtures(), "claimId": "synthetic"}
        )


def test_copied_packet_cannot_acquire_an_independent_budget_or_lock(packet):
    root, directory, digest, _ = packet
    copy = root / "private/copy"
    shutil.copytree(directory, copy)
    before = sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*"))
    with pytest.raises(ValueError, match="packet directory"):
        engine.execute_pass(
            root,
            copy,
            digest,
            "canary",
            now=lambda: NOW,
            get=lambda *a, **k: pytest.fail("copied packet GET"),
        )
    assert sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*")) == before


def test_contender_reloads_journal_only_after_acquiring_busy_lock(packet, monkeypatch):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    original_open = Path.open
    interleaved = False

    def open_with_completed_predecessor(path, mode="r", *args, **kwargs):
        nonlocal interleaved
        if path == directory / "busy.lock" and mode == "x" and not interleaved:
            interleaved = True
            assert (
                engine.execute_pass(
                    root,
                    directory,
                    digest,
                    "2026-11-21T05:00:00Z",
                    get=lambda url, **kw: response(url),
                    now=clock.now,
                    monotonic=clock.monotonic,
                    sleep=clock.sleep,
                )["state"]
                == "completed"
            )
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_completed_predecessor)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=lambda *a, **k: pytest.fail("duplicate contender GET"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "duplicate"
    events = read_events(directory / "events.jsonl")
    assert len([e for e in events if e["kind"] == "PASS_FINISHED"]) == 2


def test_fsync_leaving_eight_seconds_never_sends_the_reserved_request(packet, monkeypatch):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    clock = Clock()
    append = engine.Journal.append
    calls = []

    def delayed(self, kind, **payload):
        event = append(self, kind, **payload)
        if kind == "REQUEST_RESERVED" and payload["url"] == engine.SOURCE:
            clock.sleep(89)  # Three seconds of robots pacing already consumed, 8/100 remain.
        return event

    def get(url, **kwargs):
        calls.append(url)
        return response(url)

    monkeypatch.setattr(engine.Journal, "append", delayed)
    result = engine.execute_pass(
        root,
        directory,
        digest,
        "2026-11-21T05:00:00Z",
        get=get,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert calls == [engine.ROBOTS]


def base_view():
    return dict(
        picks=[],
        fixtures=fixtures(),
        claimIds=["base"],
        generatedAt="2026-11-21T01:00:00Z",
        sourceObservedThrough="2026-11-21T01:00:00Z",
    )


@pytest.mark.parametrize("defect", ["plan_hash", "canary_keys"])
def test_public_view_never_merges_unreviewed_or_wrong_plan_e2_facts(packet, defect):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    if defect == "plan_hash":
        digest = "0" * 64
    else:
        approval = json.loads((directory / "canary-acceptance.json").read_text())
        approval["keys"] = ["C0", "C1"]
        write_json(directory / "canary-acceptance.json", approval)
    base = base_view()
    old = qualify([native(str(UUID(int=700)))])["picks"][0]
    base["picks"] = [old]
    result = engine.read_view(root, directory, digest, now=NOW, base=base)
    assert [p["sourceTipId"] for p in result["picks"]] == [str(UUID(int=700))]
    assert result["active"] is False


def test_exact_reviewed_history_stays_readable_after_expiry(packet):
    root, directory, digest, _ = packet
    accept_canary(root, directory, digest)
    result = engine.read_view(
        root,
        directory,
        digest,
        now=datetime(2026, 11, 21, 14, tzinfo=UTC),
        base=base_view(),
        native_verified=True,
    )
    assert len(result["picks"]) == 1 and result["active"] is False


def test_aggregated_companion_last_observation_is_preserved_during_base_merge():
    old = qualify([native()])["picks"][0]
    aggregated = dict(old, observedAt="2026-11-21T05:00:00Z", lastObservedAt="2026-11-21T09:00:00Z")
    base = base_view()
    base["picks"] = [dict(old, lastObservedAt="2026-11-21T07:00:00Z")]
    result = engine.merge_view(
        base, dict(picks=[aggregated], fixtures=fixtures(), claimId="synthetic")
    )
    assert result["picks"][0]["lastObservedAt"] == "2026-11-21T09:00:00Z"
    assert result["sourceObservedThrough"] == "2026-11-21T09:00:00Z"


def test_valid_and_unresolved_owner_variants_poison_the_id_in_either_order():
    bad = dict(native(), tipster="$deadbeef")
    for rows in ([native(), bad], [bad, native()]):
        result = qualify(rows)
        assert result["status"] == "partial"
        assert result["picks"] == []


@pytest.mark.parametrize(
    "defect", ["date", "owner", "event", "unresolved_owner", "competition", "competition_absent"]
)
@pytest.mark.parametrize("reverse", [False, True])
def test_known_id_contradiction_precedes_calendar_exclusion_even_with_another_valid_pick(
    defect, reverse
):
    original = native()
    old = qualify([original])["picks"][0]
    bad = deepcopy(original)
    if defect == "date":
        bad["date"] = "2026-11-22T15:00:00Z"
    elif defect == "owner":
        other = str(UUID(int=88))
        bad["tipsterId"] = other
        bad["tipster"]["user"].update(id=other, tipster={"id": other, "userId": other})
    elif defect == "event":
        bad["event"] = "Other - Event"
    elif defect == "competition":
        bad["competition"] = "Bundesliga"
    elif defect == "competition_absent":
        bad.pop("competition")
    else:
        bad["tipster"] = "$deadbeef"
    rows = [bad, native(str(UUID(int=29)))]
    if reverse:
        rows.reverse()
    result = engine.qualify_documents(
        {"0": rows}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64, known=[old]
    )
    assert result["status"] == "partial" and result["picks"] == []


def test_unchanged_known_post_kickoff_record_is_excluded_without_poisoning_new_valid_pick():
    old = qualify([native(fixture=0)])["picks"][0]
    result = engine.qualify_documents(
        {"0": [native(fixture=0), native(str(UUID(int=33)))]},
        fixtures(),
        datetime(2026, 11, 21, 13, tzinfo=UTC),
        response_sha="a" * 64,
        parser_sha="b" * 64,
        known=[old],
    )
    assert result["status"] == "qualified"
    assert [p["sourceTipId"] for p in result["picks"]] == [str(UUID(int=33))]


def test_unrelated_non_scalar_id_wrapper_does_not_break_known_id_validation():
    old = qualify([native()])["picks"][0]
    result = engine.qualify_documents(
        {"0": {"id": {}, "rows": [native()]}},
        fixtures(),
        NOW,
        response_sha="a" * 64,
        parser_sha="b" * 64,
        known=[old],
    )
    assert result["status"] == "qualified" and len(result["picks"]) == 1


def golden_rows():
    return [native(str(UUID(int=i))) for i in (41, 42)] + [
        dict(native(str(UUID(int=i))), competition="Other") for i in range(100, 109)
    ]


def test_v4_witness_sample_is_limited_without_rejecting_complete_eligible_scan():
    result = qualify(golden_rows())
    assert result["status"] == "qualified" and result["reasons"] == []
    assert len(result["picks"]) == 2 and len(result["witnesses"]) == 3
    assert result["omittedWitnesses"] == 6 and result["omittedAdmissible"] == 0
    assert (
        result["witnessSampleLimited"]
        and result["traversalComplete"]
        and result["visitedNodes"] > 0
    )
    assert not result["depthBoundHit"] and not result["walkBoundHit"]


def test_v4_depth_failure_cannot_be_hidden_by_witness_sampling():
    tail = {}
    for _ in range(45):
        tail = {"inside": tail}
    result = engine.qualify_documents(
        {"0": {"rows": golden_rows(), "tail": tail}},
        fixtures(),
        NOW,
        response_sha="a" * 64,
        parser_sha="b" * 64,
    )
    assert result["status"] == "partial" and "depth_bound" in result["reasons"]
    assert (
        result["depthBoundHit"] and not result["traversalComplete"] and not result["walkBoundHit"]
    )
    assert result["omittedWitnesses"] == 6


def test_v4_late_invalid_variant_remains_a_veto_after_three_witnesses():
    rows = golden_rows()
    rows.append(dict(rows[0], tipster="$deadbeef"))
    result = qualify(rows)
    assert result["status"] == "partial" and result["picks"] == []
    assert "contradictory_id" in result["reasons"] and result["omittedWitnesses"] >= 6


def test_v4_eligible_overflow_remains_a_veto_with_complete_traversal():
    rows = [native(str(UUID(int=i))) for i in range(1, 22)] + golden_rows()[2:]
    result = qualify(rows)
    assert result["status"] == "partial" and "retention_limit" in result["reasons"]
    assert result["omittedAdmissible"] == 1 and result["traversalComplete"]


def test_v4_family_offsets_and_five_pass_ceiling_are_preserved():
    plan = engine.draft_plan(fixtures(), canary_at="2026-11-21T04:35:00Z")
    assert (plan["priorGetCount"], plan["priorMilliseconds"]) == (9, 19812)
    assert plan["requestMax"] == 10 and plan["requestMax"] + plan["priorGetCount"] == 19
    assert plan["newTimeMilliseconds"] + plan["priorMilliseconds"] == 600000
    assert len(plan["slots"]) == 4 and plan["expiresAt"] == "2026-11-21T11:15:00Z"
    assert engine.mission_for(plan)["external_effects"]["https_get_max"] == 10


def test_v4_known_reobservation_and_new_uuid_both_count_toward_twenty():
    rows = golden_rows()[:2]
    known = qualify([rows[0]])["picks"]
    result = engine.qualify_documents(
        {"0": rows}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64, known=known
    )
    assert result["status"] == "qualified" and len(result["picks"]) == 2


def test_v4_node_bound_and_retention_reasons_are_both_preserved():
    rows = [native(str(UUID(int=i))) for i in range(1, 22)]
    result = engine.qualify_documents(
        {"0": {"rows": rows, "wide": [None] * 150001}},
        fixtures(),
        NOW,
        response_sha="a" * 64,
        parser_sha="b" * 64,
    )
    assert result["status"] == "partial" and not result["traversalComplete"]
    assert result["walkBoundHit"] and not result["depthBoundHit"]
    assert {"walk_bound", "retention_limit"} <= set(result["reasons"])


@pytest.mark.parametrize(
    "documents",
    [
        {"a": "$b", "b": "$a", "0": "$a"},
        {"0": "$deadbeef"},
    ],
)
def test_v4_unresolved_or_cyclic_data_ref_cannot_claim_complete_traversal(documents):
    values = dict(documents)
    values["0"] = [native(), documents["0"]]
    result = engine.qualify_documents(
        values, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "partial" and result["traversalComplete"] is False
    assert set(result["reasons"]) & {"unresolved_data_reference", "cyclic_data_reference"}


@pytest.mark.parametrize(
    "marker",
    [
        "$",
        "$$literal",
        "$Sreact.suspense",
        "$D2026-11-21T00:00:00Z",
        "$n12",
        "$I",
        "$-I",
        "$-0",
        "$N",
        "$u",
    ],
)
def test_v4_inert_flight_scalar_markers_do_not_hide_a_data_reference(marker):
    result = engine.qualify_documents(
        {"0": [native(), marker]}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "qualified" and result["traversalComplete"]


@pytest.mark.parametrize("emitted", ["$undefined", "$Infinity", "$-Infinity", "$NaN"])
def test_v4_react_production_serializer_scalars_are_not_model_references(emitted):
    result = engine.qualify_documents(
        {"0": [native(), emitted]}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "qualified" and result["traversalComplete"]


def test_v4_lazy_import_is_inert_only_when_its_import_record_is_attested():
    flight = 'a:I[1,[],"default"]\n0:' + json.dumps([native(), "$La"]) + "\n"
    body = ("<script>self.__next_f.push(" + json.dumps([1, flight]) + ");</script>").encode()
    documents = engine.decode_capture(body, "text/html")
    result = engine.qualify_documents(
        documents, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "qualified" and result["traversalComplete"]
    documents.pop("__flight_import_ids")
    result = engine.qualify_documents(
        documents, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "partial" and not result["traversalComplete"]


@pytest.mark.parametrize(
    "reference", ["$Ldeadbeef", "$@deadbeef", "$Qdeadbeef", "$Tunknown", "$Ecode", "$Yomitted"]
)
def test_v4_unavailable_or_unsupported_protocol_data_is_never_complete(reference):
    result = engine.qualify_documents(
        {"0": [native(), reference]}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )
    assert result["status"] == "partial" and not result["traversalComplete"]


def test_v4_path_reference_checks_the_referenced_model_without_executing_code():
    result = engine.qualify_documents(
        {"0": "$a:rows", "a": {"rows": [native()]}},
        fixtures(),
        NOW,
        response_sha="a" * 64,
        parser_sha="b" * 64,
    )
    assert result["status"] == "qualified" and result["traversalComplete"]


@pytest.mark.parametrize("same_version", [True, False])
def test_prior_rejected_occurrence_only_supplies_clock_for_exact_same_version(same_version):
    earlier = qualify([native()], observed=NOW - timedelta(hours=1))["picks"][0]
    current = qualify([native()])["picks"][0]
    if not same_version:
        earlier["sourceFields"]["competition"] = "Other"
    event = dict(kind="PASS_REJECTED", hash="c" * 64, projection=dict(picks=[earlier]))
    engine.retain_prior_unaccepted_clock(current, [event])
    assert (
        current["observedAt"]
        == current["temporalEvidenceFirstObservedAt"]
        == "2026-11-21T05:00:00+00:00"
    )
    if same_version:
        assert (
            current["firstSeenAt"] == current["priorUnacceptedObservedAt"] == earlier["observedAt"]
        )
        assert current["priorUnacceptedObservation"]["eventHash"] == "c" * 64
    else:
        assert current["firstSeenAt"] == current["observedAt"]
        assert "priorUnacceptedObservedAt" not in current
