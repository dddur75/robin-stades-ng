"""Two proposed packs. No real transport, source payload or task execution."""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from robin.source_observatory.connectors import Journal, Response, canonical
from robin.source_observatory.olbg import extract_profile
from robin.source_observatory.olbg_opaque_batches import merge_versions, read_campaign
from robin.source_observatory.olbg_opaque_campaign import (
    bind_source_runtime,
    project_profile,
    rules_digest,
    run_opaque_slot,
)
from robin.source_observatory.opaque_choices import build_opaque_choices

GET_CALLS = 0
TERMS = b"<main>1. Synthetic 7.1 Synthetic 9.2 Synthetic 17.4 Synthetic</main>"


def fixture() -> dict:
    return {"id": "synth:match", "label": "Home - Away", "home": "Home", "away": "Away",
            "homeAliases": ["Home"], "awayAliases": ["Away"],
            "kickoff": "2026-11-27T20:00:00+00:00"}


def native(tid: int, choice: str) -> dict:
    return {"tipid": tid, "eventid": 900, "eventname": "Home v Away",
            "selection": choice, "market": "synthetic market", "winew": "",
            "event_datetime": "2026-11-27 20:00:00", "vc_sport_id": 1, "result": "Open"}


def profile(rows: list[dict]) -> bytes:
    days = json.dumps([{"events": [{"tips": rows}]}])
    return ('<script>const x={effectiveTipsterId:648433,tipsterUsername:"Synthetic",'
            'mode:"current",tipsByDate:' + days + '};</script>').encode()


def setup(root: Path) -> tuple[dict, dict, dict]:
    parser = Path(extract_profile.__code__.co_filename)
    builder = Path(build_opaque_choices.__code__.co_filename)
    pins = [{"role": role, "path": str(path),
             "sha256": sha256(path.read_bytes()).hexdigest()}
            for role, path in (("parser", parser), ("builder", builder))]
    plan = {"id": "SYNTH_OPAQUE_CAMPAIGN", "claimId": "SYNTH.NOT.REAL",
            "endpoint": "https://www.olbg.com/tipsters/tips/648433",
            "robotsUrl": "https://www.olbg.com/robots.txt",
            "termsUrl": "https://www.olbg.com/use",
            "slots": ["2026-11-27T12:00:00+00:00", "2026-11-27T13:00:00+00:00"],
            "zeroEligiblePolicy": "HALT", "fixtures": [fixture()],
            "calendarSha256": sha256(canonical([fixture()])).hexdigest(),
            "parserSha256": pins[0]["sha256"], "builderSha256": pins[1]["sha256"],
            "rulesSha256": rules_digest(TERMS), "codePins": pins}
    mf = {"mission_id": plan["id"], "authorized_stages": ["E1", "E2"],
          "maximum_stage": "E2", "external_effects": {"https_get_max": 6, "per_source_max": 6},
          "compute_budget": {}, "time_budget": {"seconds": 600},
          "source_hash": sha256(canonical(plan)).hexdigest(),
          "expires_at": "2026-11-27T19:00:00+00:00"}
    p, m = canonical(plan) + b"\n", canonical(mf) + b"\n"
    (root / "plan.json").write_bytes(p)
    # Journal owns mission.json; manifest is the independently approved campaign input.
    (root / "manifest.json").write_bytes(m)
    return plan, mf, {"planSHA256": sha256(p).hexdigest(),
                      "manifestSHA256": sha256(m).hexdigest()}


class CampaignPacks(unittest.TestCase):
    def test_two_slots_versioned_distinct(self) -> None:
        global GET_CALLS
        GET_CALLS = 0
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, _, approval = setup(root)
            responses = [
                Response(200, b"User-agent: *\nAllow: /\n", "text/plain", None),
                Response(200, TERMS, "text/html", None),
                Response(200, profile([native(10, "FIRST")]), "text/html", None),
                Response(200, b"User-agent: *\nAllow: /\n", "text/plain", None),
                Response(200, TERMS, "text/html", None),
                Response(200, profile([native(10, "UPDATED"), native(11, "NEW")]),
                         "text/html", None)]
            def fake_get(_url: str, **_kwargs: object) -> Response:
                global GET_CALLS
                GET_CALLS += 1
                self.assertLessEqual(GET_CALLS, 6)
                return responses.pop(0)
            for slot in plan["slots"]:
                at = datetime.fromisoformat(slot)
                result = run_opaque_slot(root, approval=approval, synthetic_only=True,
                                         now=at, clock=lambda: at, sleep=lambda _s: None,
                                         get=fake_get)
                self.assertEqual(result["state"], "succeeded")
            merged = read_campaign(root, approval)
            self.assertEqual(GET_CALLS, 6)
            self.assertEqual(len(merged["picks"]), 2)
            old = next(p for p in merged["picks"] if p["sourceTipId"] == 10)
            self.assertEqual(old["observedAt"], plan["slots"][1])
            self.assertEqual(old["firstSeenAt"], plan["slots"][0])
            self.assertEqual(old["lastSeenAt"], plan["slots"][1])
            self.assertEqual(old["versionCount"], 2)
            self.assertEqual(len(old["observationVersions"]), 2)
            self.assertFalse(merged["sourceReady"])
            self.assertEqual(len(responses), 0)

    def test_orphan_duplicate_after_ko_and_default_deny(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, mf, approval = setup(root)
            now = datetime(2026, 11, 27, 12, tzinfo=UTC)
            with self.assertRaises(PermissionError):
                run_opaque_slot(root, now=now)
            with self.assertRaises(PermissionError):
                bind_source_runtime(root, plan, mf, approval)
            with self.assertRaises(ValueError):
                read_campaign(root, approval)
            journal = Journal(root, mf, now=lambda: now)
            journal.append("PUBLIC_SLOT_STARTED", slot=plan["slots"][0])
            with self.assertRaises(ValueError):
                read_campaign(root, approval)
            result = run_opaque_slot(root, approval=approval, synthetic_only=True,
                                     now=now, clock=lambda: now)
            self.assertEqual(result["state"], "already_started")
            journal = Journal(root, mf, now=lambda: now)
            journal.append("PUBLIC_SLOT_FINISHED", slot=plan["slots"][0], count=1)
            with self.assertRaises(ValueError):
                read_campaign(root, approval)
            facts = extract_profile(profile([native(10, "FIRST")]), 648433)
            with self.assertRaises(ValueError):
                project_profile(facts, plan, datetime(2026, 11, 27, 21, tzinfo=UTC), "a" * 64)
            batch = project_profile(facts, plan, now, "a" * 64)
            prior = deepcopy(batch["picks"])
            changed = deepcopy(prior)
            changed[0]["fixtureId"] = "synth:foreign"
            with self.assertRaises(ValueError):
                merge_versions(prior, changed)
            self.assertEqual(prior, batch["picks"])
            later = deepcopy(prior)
            later[0]["observedAt"] = plan["slots"][1]
            later[0]["firstSeenAt"] = "2026-11-27T11:00:00+00:00"
            later[0]["lastSeenAt"] = plan["slots"][1]
            with self.assertRaises(ValueError):
                merge_versions(prior, later)
            unordered = deepcopy(prior)
            unordered[0]["firstSeenAt"] = plan["slots"][1]
            with self.assertRaises(ValueError):
                merge_versions([], unordered)


if __name__ == "__main__":
    unittest.main()
