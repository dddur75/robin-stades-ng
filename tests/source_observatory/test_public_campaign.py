import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from robin.source_observatory.public_campaign import legal_digest, run_slot


def test_missing_authorization_refuses_before_any_network(tmp_path):
    (tmp_path/'plan.json').write_text('{}')
    (tmp_path/'manifest.json').write_text('{}')
    calls=[]
    with pytest.raises(FileNotFoundError):
        run_slot(tmp_path,get=lambda url:calls.append(url))
    assert not calls


def test_changed_grant_refuses_before_network(tmp_path):
    for name,value in [('plan',{'id':'x','authorizationText':'grant'}),('manifest',{'source_hash':'a'}),('authorization',{'planSha256':'wrong','statement':'grant'})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value))
    with pytest.raises(ValueError,match='exact owner'):
        run_slot(tmp_path,get=lambda url:pytest.fail('network forbidden'))


def test_no_catch_up_or_expired_network(tmp_path):
    from hashlib import sha256

    from robin.source_observatory.connectors import canonical
    plan={'id':'x','authorizationText':'grant','codePins':{},'slots':['2026-11-20T07:00:00Z']}
    digest=sha256(canonical(plan)).hexdigest()
    for name,value in [('plan',plan),('manifest',{'mission_id':'x','source_hash':digest,'expires_at':'2026-11-21T07:00:00Z'}),('authorization',{'planSha256':digest,'statement':'grant','manifestSha256':sha256(canonical({'mission_id':'x','source_hash':digest,'expires_at':'2026-11-21T07:00:00Z'})).hexdigest()})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value))
    assert run_slot(tmp_path,now=datetime(2026,11,20,7,4,tzinfo=UTC),get=lambda url:pytest.fail('no catchup'))['state']=='not_due'
    assert run_slot(tmp_path,now=datetime(2026,11,21,7,tzinfo=UTC),get=lambda url:pytest.fail('expired'))['state']=='expired'


def test_changed_or_absent_legal_block_refuses():
    with pytest.raises(ValueError):
        legal_digest(b'<div>Unknown terms</div>')
    body=('<div class="content">En accédant phpBB conditions '+('information '*60)+'</div>').encode()
    assert len(legal_digest(body))==64
    with pytest.raises(ValueError):
        legal_digest(body.replace(b'information',b'no scraping'))

def campaign(tmp_path):
    from datetime import timedelta
    from hashlib import sha256

    from robin.source_observatory.connectors import canonical
    from robin.source_observatory.forum_tipsters import __file__ as parser_file
    now=datetime(2026,11,19,10,0,tzinfo=UTC)
    terms=('<div class="content">En accédant phpBB conditions '+('information '*60)+'</div>').encode()
    profiles=[{'id':s,'robotsUrl':base+'/robots.txt','termsUrl':base+'/ucp.php?mode=terms','endpoint':base+f'/viewtopic.php?t={topic}','termsSha256':legal_digest(terms)} for s,base,topic in [('SRC_038','http://forum.sco1919.com','13259'),('SRC_058','https://legruppetto.fr','24850')]]
    plan={'id':'test','authorizationText':'exact test grant','codePins':{},'slots':[now.isoformat(),(now+timedelta(hours=2)).isoformat()], 'profiles':profiles,
          'claimId':'SYNTHETIC.TEST','fixtures':[{'id':'match','label':'Nice – PSG','homeAliases':['Nice'],'awayAliases':['PSG'],'kickoff':(now+timedelta(days=2)).isoformat(),'publicationWindowStart':'2026-11-09'}],
          'parserSha256':sha256(Path(parser_file).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),'calendarSha256':'c'*64}
    digest=sha256(canonical(plan)).hexdigest()
    manifest={'mission_id':'test','authorized_stages':['E1','E2'],'maximum_stage':'E2','external_effects':{'https_get_max':12,'per_source_max':6},'compute_budget':{},'time_budget':{'seconds':600},'source_hash':digest,'expires_at':(now+timedelta(days=1)).isoformat()}
    for name,value in [('plan',plan),('manifest',manifest),('authorization',{'planSha256':digest,'statement':plan['authorizationText'],'manifestSha256':sha256(canonical(manifest)).hexdigest()})]:
        (tmp_path/(name+'.json')).write_bytes(canonical(value)+b'\n')
    return now,terms


def test_authorized_due_slot_is_durable_and_never_repeated(tmp_path):
    from robin.source_observatory.connectors import Response
    from robin.source_observatory.public_collection import read_collection
    now,terms=campaign(tmp_path)
    calls=[]
    body=b'<div id="p123"><p class="author">par <a class="username">Alice</a> 18 Nov 2026</p><div class="content">Nice - PSG 1-3</div></div>'
    def get(url,**kwargs):
        calls.append(url)
        return Response(200,b'User-agent: *\nDisallow:\n' if url.endswith('robots.txt') else terms if 'mode=terms' in url else body,'text/html',None)
    assert run_slot(tmp_path,now=now,clock=lambda:now,get=get,sleep=lambda _:None)['picks']==2
    assert read_collection(tmp_path)['distinctPicks']==2
    assert run_slot(tmp_path,now=now,clock=lambda:now,get=get)['state']=='already_started'
    assert len(calls)==6
    bundle=next(tmp_path.glob('observations-*.json'))
    bundle.write_bytes(bundle.read_bytes()+b' ')
    with pytest.raises(ValueError,match='hash mismatch'):
        read_collection(tmp_path)


def test_terms_change_halts_campaign_without_later_network(tmp_path):
    from robin.source_observatory.connectors import Response
    now,terms=campaign(tmp_path)
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return Response(200,b'User-agent: *\nDisallow:\n' if url.endswith('robots.txt') else terms.replace(b'information',b'updated terms'),'text/html',None)
    with pytest.raises(ValueError,match='terms changed'):
        run_slot(tmp_path,now=now,clock=lambda:now,get=get,sleep=lambda _:None)
    assert run_slot(tmp_path,now=now,clock=lambda:now,get=get)['state']=='halted'
    assert len(calls)==2

def test_adjacent_restrictive_clause_cannot_escape_terms_guard():
    body=('<div class="content">En accédant phpBB conditions '+('information '*60)+'</div><p>Collecte automatisée interdite.</p>').encode()
    with pytest.raises(ValueError):
        legal_digest(body)


def test_manifest_cannot_change_under_plan_only_grant(tmp_path):
    now,_=campaign(tmp_path)
    manifest=json.loads((tmp_path/'manifest.json').read_bytes())
    manifest['time_budget']['seconds']=9000
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='authorization'):
        run_slot(tmp_path,now=now,clock=lambda:now,get=lambda *a,**k:pytest.fail('must refuse before network'))


def test_validation_is_read_only_even_in_due_slot(tmp_path):
    from robin.source_observatory.public_campaign import validate_campaign
    campaign(tmp_path)
    validate_campaign(tmp_path)
    assert not (tmp_path/'events.jsonl').exists()


def test_transport_deadline_is_bounded_and_failure_halts(tmp_path):
    from datetime import timedelta

    from robin.source_observatory.connectors import Response
    now,terms=campaign(tmp_path)
    current=[now]
    timeouts=[]
    def get(url,**kwargs):
        timeouts.append(kwargs['timeout'])
        current[0]+=timedelta(seconds=205)
        return Response(200,b'User-agent: *\nDisallow:\n','text/plain',None)
    with pytest.raises(ValueError,match='deadline'):
        run_slot(tmp_path,now=now,clock=lambda:current[0],get=get,sleep=lambda _:None)
    assert all(0<t<=30 for t in timeouts)
    assert run_slot(tmp_path,now=now,clock=lambda:now,get=get)['state']=='halted'

def test_future_campaign_view_is_cumulative_and_identified_as_recurring(tmp_path):
    from datetime import timedelta

    from robin.source_observatory.connectors import Response
    from robin.source_observatory.public_collection import read_collection
    now,terms=campaign(tmp_path)
    current=[now]
    def get(url,**kwargs):
        pid='123' if current[0]==now else '124'
        body=f'<div id="p{pid}"><p class="author"><a class="username">Alice</a> 18 Nov 2026</p><div class="content">Nice - PSG 1-3</div></div>'.encode()
        return Response(200,b'User-agent: *\nDisallow:\n' if url.endswith('robots.txt') else terms if 'mode=terms' in url else body,'text/html',None)
    for moment in [now,now+timedelta(hours=2)]:
        current[0]=moment
        run_slot(tmp_path,now=moment,clock=lambda:current[0],get=get,sleep=lambda _:None)
    view=read_collection(tmp_path)
    assert view['distinctPicks']==4
    assert view['recurring'] is True
