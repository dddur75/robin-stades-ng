"""Synthetic product, provenance and durable execution guards, without a source request."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest

from robin.source_observatory import notbetting_occurrence_campaign as engine
from robin.source_observatory import notbetting_recurring_v4 as frozen
from robin.source_observatory.connectors import Journal, Response, canonical, read_events

NOW = datetime(2026, 11, 21, 5, 40, tzinfo=UTC)


def fixtures():
    return [
        dict(
            id=f"epl-{i}",
            label=f"Home {i} – Away {i}",
            homeAliases=[f"Home {i}"],
            awayAliases=[f"Away {i}"],
            kickoff="2026-11-21T15:00:00Z",
        )
        for i in range(5)
    ]


def native(identifier):
    return dict(
        id=identifier,
        event="Home 1 - Away 1",
        pick="Literal opaque choice",
        competition="Premier League",
        date="2026-11-21T15:00:00Z",
        tipsterId=frozen.OWNER,
        tipster={
            "user": {
                "id": frozen.OWNER,
                "username": "ELIMAGAR",
                "tipster": {"id": frozen.OWNER, "userId": frozen.OWNER},
            }
        },
    )


def row(identifier):
    return frozen.qualify_documents(
        {"0": [native(identifier)]}, fixtures(), NOW, response_sha="a" * 64, parser_sha="b" * 64
    )["picks"][0]


def projection():
    return dict(
        picks=[row(i) for i in engine.CANARY_IDS],
        reasons=["depth_bound", "unresolved_data_reference"],
        walkBoundHit=False,
        depthBoundHit=True,
        omittedAdmissible=0,
        omittedWitnesses=6,
        traversalComplete=False,
        visitedNodes=1400,
    )


def test_bounded_product_accepts_closed_rows_while_complete_page_product_rejects():
    value = projection()
    assert value["traversalComplete"] is False
    assert len(engine.validate_projection(value, fixtures(), NOW)) == 2


@pytest.mark.parametrize(
    "defect", ["owner", "late", "fingerprint", "reason", "node", "overflow", "empty"]
)
def test_closed_rows_are_independently_revalidated_and_fatal_diagnostics_stop(defect):
    value = projection()
    now = NOW
    if defect == "owner":
        value["picks"][0]["sourceFields"]["tipster.user.id"] = "other"
        value["picks"][0]["sourceRecordFingerprint"] = sha256(
            canonical(value["picks"][0]["sourceFields"])
        ).hexdigest()
    elif defect == "late":
        now = datetime(2026, 11, 21, 15, tzinfo=UTC)
    elif defect == "fingerprint":
        value["picks"][0]["sourceRecordFingerprint"] = "c" * 64
    elif defect == "reason":
        value["reasons"].append("contradictory_id")
    elif defect == "node":
        value["walkBoundHit"] = True
    elif defect == "overflow":
        value["omittedAdmissible"] = 1
    else:
        value["picks"] = []
    with pytest.raises(ValueError):
        engine.validate_projection(value, fixtures(), now)


def observation(at, tag):
    return dict(
        observedAt=at.isoformat(),
        responseSha256="a" * 64,
        parserSha256="b" * 64,
        journalSha256=tag * 64,
        eventHash=tag * 64,
        captureReceiptSha256=tag * 64,
        journalHashScope="IMMUTABLE_PREFIX_THROUGH_CAPTURE_EVENT",
        reasons=["depth_bound"],
    )


def test_new_uuid_is_pending_until_two_distinct_matching_captures_then_conflict_veto():
    state = {}
    pick = row(str(UUID(int=12)))
    engine.add_observation(state, pick, observation(NOW, "c"), fixtures())
    assert state[pick["id"]]["state"] == "PENDING_NONCANONICAL"
    later = dict(pick, observedAt=(NOW + timedelta(hours=1)).isoformat())
    engine.add_observation(state, later, observation(NOW + timedelta(hours=1), "d"), fixtures())
    assert state[pick["id"]]["state"] == "DECLARED_NONCANONICAL"
    assert state[pick["id"]]["declaration"]["observationCount"] == 2
    with pytest.raises(ValueError):
        engine.add_observation(
            state,
            dict(later, selection="Changed"),
            observation(NOW + timedelta(hours=2), "e"),
            fixtures(),
        )


class Clock:
    def __init__(self):
        self.value, self.elapsed = NOW, 0.0

    def now(self):
        return self.value

    def monotonic(self):
        return self.elapsed

    def sleep(self, amount):
        self.value += timedelta(seconds=amount)
        self.elapsed += amount


@pytest.fixture
def packet(tmp_path, monkeypatch):
    root = tmp_path
    directory = root / engine.DIRECTORY
    directory.mkdir(parents=True)
    plan = engine.draft_plan(fixtures())
    plan["codePins"] = {engine.PIN_PATHS[3]: "b" * 64}
    mission = engine.mission_for(plan)
    (directory / "mission.json").write_bytes(canonical(mission) + b"\n")
    monkeypatch.setattr(
        engine,
        "validate_package",
        lambda *a, **kw: dict(
            plan=plan, mission=mission, baseline=dict(picks=[], fixtures=fixtures())
        ),
    )
    monkeypatch.setattr(engine, "load_baseline", lambda root: dict(picks=[], fixtures=fixtures()))
    monkeypatch.setattr(engine, "validate_projection", lambda value, calendar, now: value["picks"])
    monkeypatch.setattr(engine.frozen, "decode_capture", lambda *a: {})
    fixed_projection = projection()

    def project(*args, **kwargs):
        value = deepcopy(fixed_projection)
        for pick in value["picks"]:
            pick["observedAt"] = args[2].isoformat()
        return value

    monkeypatch.setattr(engine.frozen, "qualify_documents", project)
    return root, directory, plan


def get(url, **kwargs):
    return Response(
        200,
        b"User-agent: *\nAllow: /\n" if url == frozen.ROBOTS else b"<html></html>",
        "text/plain" if url == frozen.ROBOTS else "text/html",
        None,
    )


def test_capture_prefix_is_an_actual_immutable_journal_prefix_and_replay_is_verified(packet):
    root, directory, plan = packet
    clock = Clock()
    result = engine.execute_pass(
        root,
        directory,
        "a" * 64,
        "canary",
        get=get,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "canary_pending_review"
    events = read_events(directory / "events.jsonl")
    committed = [e for e in events if e["kind"] == "CAPTURE_COMMITTED"][0]
    capture = engine.read_capture(directory, committed, "a" * 64)
    assert capture["observation"]["journalHashScope"] == "IMMUTABLE_PREFIX_THROUGH_CAPTURE_EVENT"
    assert capture["observation"]["captureReceiptSha256"] != capture["observation"]["journalSha256"]
    receipt = json.loads((directory / committed["receiptFile"]).read_bytes())
    prefix = directory / receipt["prefixFile"]
    prefix.write_bytes(prefix.read_bytes() + b"x")
    with pytest.raises(ValueError):
        engine.read_capture(directory, committed, "a" * 64)


@pytest.mark.parametrize("delay", [92, 21300])
def test_fsync_leaving_eight_seconds_or_expiring_stops_before_reserved_get(
    packet, monkeypatch, delay
):
    root, directory, plan = packet
    clock = Clock()
    original = Journal.append

    def append(self, kind, **payload):
        event = original(self, kind, **payload)
        if kind == "REQUEST_RESERVED":
            clock.sleep(delay)
        return event

    monkeypatch.setattr(Journal, "append", append)
    result = engine.execute_pass(
        root,
        directory,
        "a" * 64,
        "canary",
        get=lambda *a, **k: pytest.fail("late GET"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"


def test_duplicate_has_no_get_and_orphan_never_restarts(packet):
    root, directory, plan = packet
    clock = Clock()
    args = dict(now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (
        engine.execute_pass(root, directory, "a" * 64, "canary", get=get, **args)["state"]
        == "canary_pending_review"
    )
    assert (
        engine.execute_pass(
            root,
            directory,
            "a" * 64,
            "canary",
            get=lambda *a, **k: pytest.fail("duplicate GET"),
            **args,
        )["state"]
        == "duplicate"
    )


def test_family_budget_template_preserves_prior_debt_and_new_workload_identity():
    plan = engine.draft_plan(fixtures())
    assert (plan["priorGetCount"], plan["priorMilliseconds"]) == (11, 29062)
    assert plan["requestMax"] == 8 and plan["newTimeMilliseconds"] == 570938
    assert engine.mission_for(plan)["source_hash"] == sha256(canonical(plan)).hexdigest()


def test_merge_keeps_original_e1_object_and_updates_only_companion():
    old = row(engine.CANARY_IDS[0])
    old["firstSeenAt"] = "2026-11-21T00:49:56.451686+00:00"
    base = dict(picks=[old], fixtures=fixtures(), sourceObservedThrough="2026-11-21T06:00:00Z")
    state = {}
    engine.add_observation(state, row(engine.CANARY_IDS[0]), observation(NOW, "c"), fixtures())
    later = NOW + timedelta(hours=1)
    engine.add_observation(
        state,
        dict(row(engine.CANARY_IDS[0]), observedAt=later.isoformat()),
        observation(later, "d"),
        fixtures(),
    )
    merged = engine.merge_view(base, state)
    assert merged["picks"][0] == old
    assert merged["sourceObservedThrough"] == later.isoformat()
    assert merged["generatedAt"] == later.isoformat() and merged["authorCount"] == 1


def test_direct_plain_validator_code_drift_is_rejected_before_execution(tmp_path, monkeypatch):
    root = tmp_path
    directory = root / engine.DIRECTORY
    directory.mkdir(parents=True)
    monkeypatch.setattr(engine, "load_baseline", lambda root: dict(picks=[], fixtures=fixtures()))
    for name in engine.PIN_PATHS:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic pinned code\n", encoding="utf-8")
    plan = engine.draft_plan(fixtures())
    plan["codePins"] = engine.code_pins(root)
    for name, value in (
        ("plan.json", plan),
        ("mission.json", engine.mission_for(plan)),
        ("approval.json", {}),
    ):
        (directory / name).write_bytes(canonical(value))
    (root / "src/robin/source_observatory/notbetting_collection.py").write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="immutable packet"):
        engine.execute_pass(
            root,
            directory,
            sha256(canonical(plan)).hexdigest(),
            "canary",
            now=lambda: NOW,
            get=lambda *a, **k: pytest.fail("drift GET"),
        )


def test_exhausted_budget_keeps_all_eight_reservations_without_a_ninth(packet):
    root, directory, plan = packet
    journal = Journal(directory, engine.mission_for(plan), now=lambda: NOW)
    for _ in range(8):
        journal.append("REQUEST_RESERVED", elapsedMilliseconds=10000)
    result = engine.execute_pass(
        root,
        directory,
        "a" * 64,
        "canary",
        now=lambda: NOW,
        get=lambda *a, **k: pytest.fail("exhausted GET"),
    )
    assert result["state"] == "halted"
    assert (
        sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(directory / "events.jsonl")) == 8
    )


def test_transport_watchdog_returns_halted_and_retains_reservation(packet):
    root, directory, plan = packet
    clock = Clock()

    def slow(url, **kwargs):
        clock.sleep(12.1)
        return get(url)

    result = engine.execute_pass(
        root,
        directory,
        "a" * 64,
        "canary",
        get=slow,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert result["state"] == "halted"
    assert (
        sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(directory / "events.jsonl")) == 1
    )


@pytest.mark.parametrize("failure_point", ["before_complete", "after_complete"])
def test_failed_finalisation_cannot_corroborate_a_pending_id(packet, monkeypatch, failure_point):
    root, directory, _ = packet
    clock = Clock()
    args = dict(get=get, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (
        engine.execute_pass(root, directory, "a" * 64, "canary", **args)["state"]
        == "canary_pending_review"
    )
    original = engine.Journal.append

    def fail_finalisation(self, kind, **fields):
        if kind == "PASS_COMPLETED" and fields.get("slot") == engine.SLOTS[0]:
            if failure_point == "before_complete":
                raise OSError("synthetic finalisation failure")
            result = original(self, kind, **fields)
            clock.sleep(121)
            return result
        return original(self, kind, **fields)

    monkeypatch.setattr(engine.Journal, "append", fail_finalisation)
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    assert (
        engine.execute_pass(root, directory, "a" * 64, engine.SLOTS[0], **args)["state"] == "halted"
    )
    state = engine.read_state(root, directory, "a" * 64)
    assert state and all(
        e["state"] == "PENDING_NONCANONICAL" and len(e["observations"]) == 1 for e in state.values()
    )


def test_unfinished_predecessor_never_opens_a_future_request(packet):
    root, directory, plan = packet
    clock = Clock()
    assert (
        engine.execute_pass(
            root,
            directory,
            "a" * 64,
            "canary",
            get=get,
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )["state"]
        == "canary_pending_review"
    )
    journal = Journal(directory, engine.mission_for(plan), now=clock.now)
    journal.append("CAPTURE_COMMITTED", slot=engine.SLOTS[0])
    clock.value = datetime(2026, 11, 21, 9, tzinfo=UTC)
    outcome = engine.execute_pass(
        root,
        directory,
        "a" * 64,
        engine.SLOTS[1],
        get=lambda *a, **k: pytest.fail("unfinished predecessor GET"),
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    assert outcome["state"] == "halted"
    assert (
        sum(e["kind"] == "REQUEST_RESERVED" for e in read_events(directory / "events.jsonl")) == 2
    )


def test_visible_completion_under_its_owner_lock_is_not_yet_public(packet, monkeypatch):
    root, directory, _ = packet
    clock = Clock()
    mid = []
    original = engine.Journal.append

    def observe_during_fsync(self, kind, **fields):
        result = original(self, kind, **fields)
        if kind == "PASS_COMPLETED":
            mid.append(engine.read_state(root, directory, "a" * 64))
        return result

    monkeypatch.setattr(engine.Journal, "append", observe_during_fsync)
    args = dict(get=get, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (
        engine.execute_pass(root, directory, "a" * 64, "canary", **args)["state"]
        == "canary_pending_review"
    )
    assert mid[-1] == {}
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    assert (
        engine.execute_pass(root, directory, "a" * 64, engine.SLOTS[0], **args)["state"]
        == "completed"
    )
    assert all(
        v["state"] == "PENDING_NONCANONICAL" and len(v["observations"]) == 1
        for v in mid[-1].values()
    )
    assert all(
        v["state"] == "DECLARED_NONCANONICAL"
        for v in engine.read_state(root, directory, "a" * 64).values()
    )


def test_halt_and_owner_release_between_snapshot_and_owner_refuses_first_stale_read(
    packet, monkeypatch
):
    root, directory, plan = packet
    clock = Clock()
    args = dict(get=get, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (
        engine.execute_pass(root, directory, "a" * 64, "canary", **args)["state"]
        == "canary_pending_review"
    )
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    assert (
        engine.execute_pass(root, directory, "a" * 64, engine.SLOTS[0], **args)["state"]
        == "completed"
    )
    owner = directory / "busy.lock"
    owner.write_bytes(canonical(dict(planSha256="a" * 64, slot=engine.SLOTS[0])))
    original = engine._locked_slot

    def halt_then_release(*args):
        if owner.exists():
            journal = Journal(directory, engine.mission_for(plan), now=clock.now)
            journal.append("CAMPAIGN_HALTED", slot=engine.SLOTS[0])
            owner.unlink()
        return original(*args)

    monkeypatch.setattr(engine, "_locked_slot", halt_then_release)
    with pytest.raises(ValueError, match="snapshot"):
        engine.read_state(root, directory, "a" * 64)
    state = engine.read_state(root, directory, "a" * 64)
    assert state and all(v["state"] == "PENDING_NONCANONICAL" for v in state.values())


def test_orphaned_owner_keeps_earlier_capture_readable_and_latest_capture_pending(packet):
    root, directory, _ = packet
    clock = Clock()
    args = dict(get=get, now=clock.now, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (
        engine.execute_pass(root, directory, "a" * 64, "canary", **args)["state"]
        == "canary_pending_review"
    )
    clock.value = datetime(2026, 11, 21, 7, tzinfo=UTC)
    assert (
        engine.execute_pass(root, directory, "a" * 64, engine.SLOTS[0], **args)["state"]
        == "completed"
    )
    (directory / "busy.lock").write_bytes(
        canonical(dict(planSha256="a" * 64, slot=engine.SLOTS[0]))
    )
    state = engine.read_state(root, directory, "a" * 64)
    assert state and all(
        v["state"] == "PENDING_NONCANONICAL" and len(v["observations"]) == 1 for v in state.values()
    )
