from datetime import UTC, datetime
from hashlib import sha256
import json

import pytest

from robin.source_observatory.connectors import Response, canonical, read_events
from robin.source_observatory import profile_campaign as campaign

NOW = datetime(2026,11,20,20,tzinfo=UTC)


@pytest.fixture
def packet(tmp_path,monkeypatch):
    fixtures=[dict(id='test',label='Home – Away',kickoff='2026-11-21T12:30:00Z',homeAliases=['Home'],awayAliases=['Away'])]
    plan=dict(id='TEST',authorId=669088,endpoint='https://www.olbg.com/tipsters/tips/669088',robotsUrl='https://www.olbg.com/robots.txt',
        fixtures=fixtures,calendarSha256=sha256(canonical(fixtures)).hexdigest(),parserSha256='a'*64,
        claimId='SYNTHETIC.TEST',slots=['2026-11-20T21:00:00Z'],canaryNotBefore='2026-11-20T19:45:00Z',canaryExpires='2026-11-20T20:55:00Z')
    mission=dict(mission_id='TEST',authorized_stages=['E1','E2'],maximum_stage='E2',external_effects=dict(https_get_max=18,per_source_max=18),compute_budget={'workers':1},time_budget={'seconds':600},source_hash='a'*64,expires_at='2026-11-21T11:15:00Z')
    monkeypatch.setattr(campaign,'validate_packet',lambda directory:(plan,mission))
    return tmp_path,plan,mission


def transport(log, *, empty=False):
    def get(url,**kwargs):
        log.append(url)
        if url.endswith('/robots.txt'):return Response(200,b'User-agent: *\nAllow: /\n','text/plain',None)
        tips='' if empty else '{tipid:123,selection:"Home",eventname:"Home v Away",event_datetime:"2026-11-21 12:30:00",market:"",winew:"Win",hcap_market:false,result:"Open",vc_sport_id:1,eventid:999}'
        body=('<script>var data={mode:"current",effectiveTipsterId:669088,tipsterUsername:"Synthetic",tipsByDate:[{events:[{tips:['+tips+']}]}]};</script>').encode()
        return Response(200,body,'text/html',None)
    return get


def test_canary_real_parser_two_gets_and_no_duplicate_run(packet):
    directory,_,_=packet;calls=[]
    result=campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    assert result['picks']==1 and len(calls)==2
    events=read_events(directory/'events.jsonl')
    assert sum(e['kind']=='REQUEST_RESERVED' for e in events)==2
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    assert len(calls)==2
    view,enabled=campaign.read_campaign(directory,now=NOW)
    assert view['distinctPicks']==1 and view['profileCampaign']['successfulSlots']==1 and enabled


def test_no_admissible_pick_halts_without_retry(packet):
    directory,_,_=packet;calls=[]
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls,empty=True),clock=lambda:NOW,sleep=lambda _:None)
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    assert len(calls)==2


def test_missed_slot_and_orphan_never_make_another_get(packet):
    directory,_,mission=packet;calls=[]
    with pytest.raises(ValueError):campaign.run_slot(directory,get=transport(calls),clock=lambda:NOW.replace(hour=22),sleep=lambda _:None)
    assert calls==[]
    from robin.source_observatory.connectors import Journal
    journal=Journal(directory,mission,now=lambda:NOW)
    journal.append('RUN_STARTED',slot='canary')
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    assert calls==[]


def test_tampered_bundle_refuses_active_status(packet):
    directory,_,_=packet;calls=[]
    campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    path=next(directory.glob('observations-*.json'));value=json.loads(path.read_bytes());value['picks'][0]['selection']='Away';path.write_bytes(canonical(value)+b'\n')
    with pytest.raises(ValueError):campaign.read_campaign(directory,now=NOW)


def test_failed_later_slot_preserves_accepted_canary_and_disables_campaign(packet):
    directory,_,_=packet;calls=[]
    campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    with pytest.raises(ValueError):campaign.run_slot(directory,get=transport(calls,empty=True),clock=lambda:NOW.replace(hour=21),sleep=lambda _:None)
    data,enabled=campaign.read_campaign(directory,now=NOW.replace(hour=21))
    assert data['distinctPicks']==1 and not enabled
    assert data['profileCampaign']['state']=='halted'


def test_expiry_during_reservation_never_starts_transport(packet,monkeypatch):
    directory,_,_=packet;calls=[];clock=[NOW]
    from robin.source_observatory.connectors import Journal
    original=Journal.reserve
    def reserve(self,*args):
        result=original(self,*args);clock[0]=datetime(2026,11,21,11,15,tzinfo=UTC);return result
    monkeypatch.setattr(Journal,'reserve',reserve)
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:clock[0],sleep=lambda _:None)
    assert calls==[]


def test_missed_future_slot_is_inactive_but_keeps_canary(packet):
    directory,_,_=packet;calls=[]
    campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    data,enabled=campaign.read_campaign(directory,now=NOW.replace(hour=22))
    assert data['distinctPicks']==1 and not enabled
    assert data['profileCampaign']['state']=='missed_slot'
    with pytest.raises(ValueError):campaign.run_slot(directory,get=transport(calls),clock=lambda:NOW.replace(hour=22),sleep=lambda _:None)
    assert read_events(directory/'events.jsonl')[-1]['kind']=='CAMPAIGN_HALTED'
    assert len(calls)==2


def test_canary_window_expiring_during_polite_pause_forbids_profile_get(packet):
    directory,_,_=packet;calls=[];clock=[NOW.replace(hour=20,minute=54,second=59)]
    def pause(seconds):clock[0]=NOW.replace(hour=20,minute=55)
    with pytest.raises(ValueError):campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:clock[0],sleep=pause)
    assert calls==['https://www.olbg.com/robots.txt']


def test_crash_after_second_bundle_acceptance_keeps_only_closed_first_slot(packet):
    directory,_,_=packet;calls=[]
    campaign.run_slot(directory,canary=True,get=transport(calls),clock=lambda:NOW,sleep=lambda _:None)
    campaign.run_slot(directory,get=transport(calls),clock=lambda:NOW.replace(hour=21),sleep=lambda _:None)
    path=directory/'events.jsonl';lines=path.read_bytes().splitlines(keepends=True)
    assert json.loads(lines[-1])['kind']=='RUN_FINISHED'
    path.write_bytes(b''.join(lines[:-1]))
    data,enabled=campaign.read_campaign(directory,now=NOW.replace(hour=21))
    assert not enabled and data['profileCampaign']['successfulSlots']==1
    assert data['picks'][0]['observedAt']==NOW.isoformat()
