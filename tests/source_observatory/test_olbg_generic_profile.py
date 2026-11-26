"""Targeted personal-profile regression; no provider requests or corpus replay."""
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import unittest


class GenericPersonalProfile(unittest.TestCase):
    def test_new_profiles_default_and_mismatch(self):
        path = Path(__file__).resolve().parents[2] / "src/robin/source_observatory/olbg_opaque_campaign.py"
        spec = importlib.util.spec_from_file_location("olbg_generic_profile_proposal", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = {"id":"synth:match","label":"Home - Away",
                   "homeAliases":["Home"],"awayAliases":["Away"],
                   "kickoff":"2026-11-27T20:00:00+00:00"}
        native = {"tipid":1,"eventid":2,"eventname":"Home v Away",
                  "selection":"SYNTH_ONLY","market":"synthetic","winew":"",
                  "event_datetime":"2026-11-27 20:00:00","vc_sport_id":1,"result":"Open"}
        for requested in (None, 522767, 642100):
            profile_id = 648433 if requested is None else requested
            plan = {"id":"SYNTH_ONLY","claimId":"SYNTH_ONLY",
                    "endpoint":f"https://www.olbg.com/tipsters/tips/{profile_id}",
                    "fixtures":[fixture],"calendarSha256":"a"*64,
                    "parserSha256":"b"*64,"builderSha256":"c"*64}
            if requested is not None:
                plan["profileId"] = requested
            days = json.dumps([{"events":[{"tips":[native]}]}])
            body = (f'<script>const x={{effectiveTipsterId:{profile_id},'
                    'tipsterUsername:"Synthetic",mode:"current",tipsByDate:'
                    + days + '};</script>').encode()
            facts = module.extract_profile(body, module._profile_id(plan))
            batch = module.project_profile(facts,plan,datetime(2026,11,25,tzinfo=UTC),"d"*64)
            self.assertEqual(batch["picks"][0]["authorId"],f"olbg:{profile_id}")
            self.assertEqual(batch["picks"][0]["sourceUrl"],plan["endpoint"])
            foreign = deepcopy(facts)
            foreign["authorId"] = profile_id + 1
            with self.assertRaisesRegex(ValueError,"CAMPAIGN_PERSONAL_AUTHOR_MISMATCH"):
                module.project_profile(foreign,plan,datetime(2026,11,25,tzinfo=UTC),"d"*64)
            wrong = {**plan,"endpoint":plan["endpoint"] + "/"}
            with self.assertRaisesRegex(ValueError,"CAMPAIGN_PROFILE_SCOPE"):
                module._profile_id(wrong)
        for bad_id in (True, 0, -1, "522767"):
            with self.assertRaisesRegex(ValueError,"CAMPAIGN_PROFILE_SCOPE"):
                module._profile_id({"profileId":bad_id,
                    "endpoint":f"https://www.olbg.com/tipsters/tips/{bad_id}"})
