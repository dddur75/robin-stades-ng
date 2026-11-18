"""Regressions for the read-only link between the frozen pilot and its cockpit."""

import importlib.util
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "cockpit/scripts/read-tipsters-pilot.py"
SPEC = importlib.util.spec_from_file_location("tipsters_pilot_projection", SCRIPT)
assert SPEC and SPEC.loader
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
NOW = datetime(2026, 11, 28, 18, tzinfo=timezone.utc)
SLOT = "2026-11-28T10:00:00Z"
SECOND = "2026-11-28T16:00:00Z"


@pytest.fixture
def packet(tmp_path):
    plan = {"id": "SYNTHETIC-READ-ONLY", "starts_at": SLOT,
            "expires_at": "2026-11-28T19:00:00Z", "requests_max": 4, "due_window_seconds": 180,
            "fixtures": [{"id": "test-match", "label": "Équipe A – Équipe B",
                          "kickoff": "2026-11-28T19:00:00Z"}],
            "slots": [{"at": SLOT, "fixtures": ["test-match"]},
                      {"at": SECOND, "fixtures": ["test-match"]}]}
    raw = pilot.canonical(plan)
    (tmp_path / "plan.json").write_bytes(raw)
    digest = sha256(raw).hexdigest()
    pins = pilot.canonical({"plan_sha256": digest})
    (tmp_path / "empreintes.json").write_bytes(pins)
    manifest = pilot.canonical({"mission_id": plan["id"], "source_hash": sha256(pins).hexdigest(),
                                "expires_at": plan["expires_at"], "compute_budget": {"requests_max": 4}})
    (tmp_path / "manifest.json").write_bytes(manifest)
    (tmp_path / "autorisation.json").write_bytes(pilot.canonical({
        "decision": "AUTHORIZED", "decision_reference": "synthetic-offline-proof",
        "mission_id": plan["id"], "requests_max": 4, "manifest_sha256": sha256(manifest).hexdigest(),
    }))
    return tmp_path, digest


def pick(**updates):
    return {"provider_observation_id": "synthetic-pick-1", "attribution_key": "a" * 64,
            "source_url": "https://example.invalid/tip", "market": "total", "selection": "over",
            "period": "full_time", "line": "2.5", "declared_odds": "1.95", "published_at": None,
            "forecast_record_detected_at": "2026-11-28T09:00:00Z"} | updates


def slot_records(digest, slot=SLOT, picks=None, status="ok"):
    return [{"kind": "slot_started", "slot": slot, "at": slot, "plan_sha256": digest},
            {"kind": "visit", "slot": slot, "fixture": "test-match", "plan_sha256": digest,
             "status": status, "http_status": 200, "observed_at": slot, "response_sha256": "b" * 64,
             "picks": [pick()] if picks is None else picks},
            {"kind": "slot_finished", "slot": slot, "at": slot, "plan_sha256": digest}]


def journal(packet, records):
    root, _ = packet
    previous = "0" * 64
    data = b""
    for record in records:
        record = record | {"previous_hash": previous}
        previous = sha256(pilot.canonical(record)).hexdigest()
        data += pilot.canonical(record | {"hash": previous}) + b"\n"
    (root / "observations.jsonl").write_bytes(data)
    return data


def test_absence_and_zero_are_distinct_and_read_does_not_write(packet):
    root, digest = packet
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    absent = pilot.project(root, digest, NOW)
    assert absent["distinctPicks"] is None
    assert absent["tipsters"] == [] and absent["counts"]["missed"] == 2
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    journal(packet, slot_records(digest, picks=[]))
    empty = pilot.project(root, digest, NOW)
    assert empty["distinctPicks"] == 0 and empty["counts"]["succeeded"] == 1


def test_repeat_reads_are_deduplicated_and_edits_keep_first_version(packet):
    root, digest = packet
    journal(packet, slot_records(digest) + slot_records(digest, SECOND))
    value = pilot.project(root, digest, NOW)
    assert value["distinctPicks"] == 1 and len(value["tipsters"]) == 1
    assert len(value["picks"][0]["versions"]) == 1
    journal(packet, slot_records(digest) + slot_records(digest, SECOND, [pick(declared_odds="2.10")]))
    value = pilot.project(root, digest, NOW)
    assert value["picks"][0]["versions"][0]["odds"] == "1.95"
    assert value["picks"][0]["versions"][1]["odds"] == "2.10"
    assert value["picks"][0]["firstSeenAt"] == "2026-11-28T10:00:00+00:00"
    assert value["technicalVerdict"] == "PENDING"
    closed = pilot.project(root, digest, datetime(2026, 11, 29, tzinfo=timezone.utc))
    assert closed["technicalVerdict"] == "PASS_AND_HOLD" and closed["dossierVerdict"] == "PARTIAL"


@pytest.mark.parametrize("change", [
    {"forecast_record_detected_at": "2026-11-28T19:00:00Z"},
    {"published_at": "2026-11-28T19:00:00Z"},
    {"author_key": "c" * 64}, {"source_url": "javascript:alert(1)"},
    {"source_url": "https://example.invalid/tip?secret=private"}, {"declared_odds": 2.0},
])
def test_semantic_failures_are_rejected_even_with_valid_chain(packet, change):
    root, digest = packet
    journal(packet, slot_records(digest, picks=[pick(**change)]))
    with pytest.raises(ValueError):
        pilot.project(root, digest, NOW)


def test_corruption_is_distinct_from_unfinished_append(packet):
    root, digest = packet
    valid = journal(packet, slot_records(digest))
    (root / "observations.jsonl").write_bytes(valid[:-8])
    assert pilot.project(root, digest, NOW)["status"] == "updating"
    (root / "observations.jsonl").write_bytes(valid.replace(b'"http_status":200', b'"http_status":201'))
    with pytest.raises(ValueError):
        pilot.project(root, digest, NOW)


def test_journal_sequence_and_late_local_reads_fail(packet):
    root, digest = packet
    records = slot_records(digest)
    for bad in [records[1:], records + records, records[:1] + records[2:]]:
        journal(packet, bad)
        with pytest.raises(ValueError):
            pilot.project(root, digest, NOW)
    records[1]["observed_at"] = "2026-11-28T19:00:00Z"
    journal(packet, records)
    with pytest.raises(ValueError):
        pilot.project(root, digest, datetime(2026, 11, 29, tzinfo=timezone.utc))


def test_running_and_interrupted_are_not_counted_as_observed_zero(packet):
    root, digest = packet
    journal(packet, slot_records(digest)[:1])
    running = pilot.project(root, digest, pilot.instant(SLOT))
    assert running["counts"]["running"] == 1 and running["distinctPicks"] is None
    later = pilot.project(root, digest, NOW)
    assert later["counts"]["interrupted"] == 1 and later["distinctPicks"] is None


def test_alias_is_publication_scoped_and_ambiguity_stops_projection(packet):
    root, digest = packet
    legacy = pick()
    legacy["author_key"] = legacy.pop("attribution_key")
    journal(packet, slot_records(digest, picks=[legacy]))
    assert pilot.project(root, digest, NOW)["tipsters"][0]["attributionBasis"] == "publication"
    journal(packet, slot_records(digest) + slot_records(digest, SECOND, [pick(attribution_key="d" * 64)]))
    with pytest.raises(ValueError):
        pilot.project(root, digest, NOW)


def test_different_authors_remain_separate_and_payload_is_allowlisted(packet):
    root, digest = packet
    journal(packet, slot_records(digest, picks=[pick(quote_text="private sentinel"),
        pick(provider_observation_id="synthetic-pick-2", attribution_key="f" * 64)]))
    value = pilot.project(root, digest, NOW)
    assert len(value["tipsters"]) == 2 and value["distinctPicks"] == 2
    assert "private sentinel" not in json.dumps(value)
    assert "decision_reference" not in json.dumps(value)


@pytest.mark.parametrize("status", ["read_failed", "blocked_robots", "skipped_delay_or_cutoff"])
def test_failed_and_blocked_visits_keep_full_denominator(packet, status):
    root, digest = packet
    journal(packet, slot_records(digest, status=status))
    result = pilot.project(root, digest, NOW)
    assert result["counts"][pilot.STATUSES[status]] == 1
    assert result["plannedVisits"] == 2 and result["distinctPicks"] is None


@pytest.mark.parametrize("at", ["private diagnostic sentinel", "2026-11-29T10:00:00Z",
                              "2026-11-28T09:00:00Z"])
def test_failed_visit_timestamps_are_validated_before_projection(packet, at):
    root, digest = packet
    records = slot_records(digest, status="read_failed")
    records[1]["observed_at"] = at
    journal(packet, records)
    with pytest.raises(ValueError):
        pilot.project(root, digest, NOW)


def test_closure_cannot_precede_the_last_read_and_absent_error_time_is_allowed(packet):
    root, digest = packet
    records = slot_records(digest)
    records[1]["observed_at"] = "2026-11-28T10:01:00Z"
    journal(packet, records)
    with pytest.raises(ValueError):
        pilot.project(root, digest, NOW)
    records = slot_records(digest, status="read_failed")
    records[1].pop("observed_at")
    journal(packet, records)
    result = pilot.project(root, digest, NOW)
    assert result["lastObservationAt"] is None
    assert result["counts"]["failed"] == 1
