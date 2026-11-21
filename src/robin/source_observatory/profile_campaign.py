"""One exact profile campaign; no authority is inherited from other OLBG jobs."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Any

from .collector import robots_policy
from .connectors import Journal, Response, canonical, public_get, read_events
from .olbg import admit_facts, extract_profile
from .olbg_store import read_bundle
from .qualification_view import merge_sro_collection
from .recurring import instant


def validate_packet(directory: Path) -> tuple[dict[str, Any],dict[str, Any]]:
    from .profile_campaign_authority import MANIFEST_SHA256, PLAN_SHA256
    root=Path(__file__).resolve().parents[3]
    plan=json.loads((directory/'plan.json').read_bytes())
    mission=json.loads((directory/'manifest.json').read_bytes())
    grant=json.loads((directory/'authorization.json').read_bytes())
    if (sha256(canonical(plan)).hexdigest()!=PLAN_SHA256
            or sha256(canonical(mission)).hexdigest()!=MANIFEST_SHA256
            or set(mission)!={'mission_id','authorized_stages','maximum_stage','external_effects','compute_budget','time_budget','source_hash','expires_at'}
            or mission['mission_id']!=plan['id'] or mission['source_hash']!=PLAN_SHA256
            or mission['maximum_stage']!='E2' or mission['authorized_stages']!=['E1','E2']
            or mission['external_effects']!={'https_get_max':18,'per_source_max':18}
            or mission['time_budget']!={'seconds':600} or mission['compute_budget']!={'workers':1}
            or plan['authorId']!=669088 or plan['endpoint']!='https://www.olbg.com/tipsters/tips/669088'
            or plan['robotsUrl']!='https://www.olbg.com/robots.txt'
            or len(plan['slots'])!=8 or len(set(plan['slots']))!=8
            or plan['slots']!=sorted(plan['slots'],key=instant)
            or grant!={'planSha256':PLAN_SHA256,'manifestSha256':MANIFEST_SHA256,'decisionId':plan['decisionId']}):
        raise ValueError('exact profile authority absent')
    expiry=instant(mission['expires_at'])
    if (expiry!=instant('2026-11-21T11:15:00Z')
            or any(instant(f['kickoff'])<expiry+timedelta(minutes=75) for f in plan['fixtures'])
            or sha256(canonical(plan['fixtures'])).hexdigest()!=plan['calendarSha256']):
        raise ValueError('profile calendar/expiry')
    for path,digest in plan['codePins'].items():
        if sha256((root/path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=digest:
            raise ValueError('profile code pin')
    legacy=Path(plan['legacyReadRoot'])
    for item in plan['reusedEvidence']:
        base=root if item['namespace']=='CURRENT_PUBLICATION_PRIVATE' else legacy
        if sha256((base/item['path']).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('profile evidence pin')
    rows=[json.loads(line) for line in (root/'reports/council/decision-ledger.jsonl').read_bytes().splitlines()]
    keys=[r for r in rows if r['decision_id']==plan['decisionId']]
    if (len(keys)!=1 or keys[0]['decision']!='PASS_AND_HOLD'
            or set(keys[0]['context']['keys'])!={'C0','C1','C4'}
            or keys[0]['context'].get('plan_sha256')!=PLAN_SHA256
            or keys[0]['context'].get('manifest_sha256')!=MANIFEST_SHA256):
        raise ValueError('profile independent keys')
    return plan,mission


def _completed(events: list[dict[str, Any]]) -> list[str]:
    starts=[e['slot'] for e in events if e['kind']=='RUN_STARTED']
    finishes=[e['slot'] for e in events if e['kind']=='RUN_FINISHED']
    accepted=[e['slot'] for e in events if e['kind']=='PUBLIC_COLLECTION_ACCEPTED']
    if (starts!=finishes or len(starts)!=len(set(starts)) or starts!=accepted
            or any(e['kind']=='CAMPAIGN_HALTED' for e in events)):
        raise ValueError('halted or orphan profile slot')
    return accepted


def run_slot(directory: Path, *, canary: bool=False,
             get: Callable[...,Response]=public_get, clock: Callable[[],datetime]=lambda:datetime.now(UTC),
             sleep: Callable[[float],None]=time.sleep) -> dict[str, Any]:
    plan,mission=validate_packet(directory)
    if any(name in os.environ for name in ('SSLKEYLOGFILE','SSL_CERT_FILE','SSL_CERT_DIR')):
        raise ValueError('external TLS configuration')
    now=clock()
    if now>=instant(mission['expires_at']):raise ValueError('profile expired')
    directory.mkdir(parents=True,exist_ok=True)
    lock=directory/'campaign.lock'
    lock.open('x').close()
    try:
        journal=Journal(directory,mission,now=clock)
        completed=_completed(journal.events)
        if canary:
            slot='canary'
            if completed or not instant(plan['canaryNotBefore'])<=now<instant(plan['canaryExpires']):
                raise ValueError('canary window/duplicate')
        else:
            if not completed or completed[0]!='canary':raise ValueError('canary proof absent')
            pending=[s for s in plan['slots'] if s not in completed]
            if not pending:raise ValueError('all profile slots finished')
            slot=pending[0]
            if now>=instant(slot)+timedelta(minutes=10):
                journal.append('CAMPAIGN_HALTED',slot=slot,reason='missed_slot_no_catchup')
                raise ValueError('slot missed; no catchup')
            if now<instant(slot):raise ValueError('slot premature')
        before=sum(e['kind']=='REQUEST_RESERVED' for e in journal.events)
        journal.append('RUN_STARTED',slot=slot)
        start=time.monotonic()
        window_end=instant(plan['canaryExpires']) if canary else instant(slot)+timedelta(minutes=10)
        try:
            def remaining() -> float:
                left=min(journal.remaining_seconds(),90-(time.monotonic()-start),
                         (window_end-clock()).total_seconds(),(instant(mission['expires_at'])-clock()).total_seconds())
                if left<=0:raise ValueError('profile time/window budget')
                return left
            def fetch(url: str) -> tuple[Response,datetime]:
                remaining()
                reservation=journal.reserve('SRC_014',url)
                response=get(url,timeout=min(12,remaining()))
                observed=clock()
                journal.append('REQUEST_FINISHED',slot=slot,url=url,reservation=reservation,
                    httpStatus=response.status,responseSha256=sha256(response.body).hexdigest(),observedAt=observed.isoformat())
                remaining()
                return response,observed
            robots,_=fetch(plan['robotsUrl'])
            if robots.status in (404,410):delay=0.
            elif robots.status==200 and robots.content_type.split(';')[0].strip().lower()=='text/plain':
                text=robots.body.decode('utf-8','strict')
                if '<' in text or '\x00' in text:raise ValueError('invalid robots')
                allowed,delay=robots_policy(text,plan['endpoint'])
                if not allowed or not 0<=delay<=5:raise ValueError('robots refusal/delay')
            else:raise ValueError('robots access refused')
            sleep(max(2,delay))
            response,observed=fetch(plan['endpoint'])
            if response.status!=200 or response.content_type.split(';')[0].strip().lower() not in ('text/html','application/xhtml+xml'):
                raise ValueError('profile access refused')
            facts=extract_profile(response.body,expected_author_id=plan['authorId'])
            if len(facts['records'])>40:raise ValueError('profile fact bound')
            picks=admit_facts(facts,plan['endpoint'],observed,plan['fixtures'],
                response_sha=sha256(response.body).hexdigest(),parser_sha=plan['parserSha256'],calendar_sha=plan['calendarSha256'])
            if not picks:raise ValueError('no admissible personal pick')
            data=dict(schemaVersion='robin-native-tipsters-v1',missionId=plan['id'],claimId=plan['claimId'],
                fixtures=plan['fixtures'],picks=picks,generatedAt=observed.isoformat(),recurring=True)
            raw=canonical(data)+b'\n';digest=sha256(raw).hexdigest();name=f'observations-{digest}.json'
            # Validate exactly the same strict NativeWin representation consumed by the application.
            with (directory/name).open('xb') as stream:stream.write(raw)
            read_bundle(directory/name,digest)
            journal.append('PUBLIC_COLLECTION_ACCEPTED',slot=slot,observationFile=name,observationSha256=digest,
                count=len(picks),responseSha256=sha256(response.body).hexdigest())
            return dict(state='succeeded',picks=len(picks),requests=2,slot=slot)
        except Exception as exc:
            journal.append('CAMPAIGN_HALTED',slot=slot,reason=type(exc).__name__)
            raise
        finally:
            journal.append('RUN_FINISHED',slot=slot,requests=sum(e['kind']=='REQUEST_RESERVED' for e in journal.events)-before)
    finally:
        lock.unlink()


def read_campaign(directory: Path, *, now: datetime|None=None) -> tuple[dict[str,Any],bool]:
    plan,mission=validate_packet(directory);now=now or datetime.now(UTC)
    events=read_events(directory/'events.jsonl')
    starts=[e['slot'] for e in events if e['kind']=='RUN_STARTED']
    finishes=[e['slot'] for e in events if e['kind']=='RUN_FINISHED']
    completed=[e['slot'] for e in events if e['kind']=='PUBLIC_COLLECTION_ACCEPTED']
    if (len(starts)!=len(set(starts)) or starts[:len(finishes)]!=finishes
            or len(starts)-len(finishes) not in (0,1) or starts[:len(completed)]!=completed
            or any(s not in ['canary',*plan['slots']] for s in starts)
            or len(completed)>len(starts) or len(starts)-len(completed)>1):
        raise ValueError('profile event ordering')
    # An accepted write without its closing record is not a completed slot.
    # Preserve all earlier closed observations while refusing further execution.
    completed=[s for s in completed if s in finishes]
    halted=any(e['kind']=='CAMPAIGN_HALTED' for e in events) or starts!=completed or starts!=finishes
    result:dict[str,Any]={}
    for e in events:
        if e['kind']!='PUBLIC_COLLECTION_ACCEPTED' or e['slot'] not in completed:continue
        name=e['observationFile'];digest=e['observationSha256']
        if name!=f'observations-{digest}.json':raise ValueError('profile receipt name')
        bundle=read_bundle(directory/name,digest)
        slot=e['slot'];start=next(i for i,r in enumerate(events) if r['kind']=='RUN_STARTED' and r['slot']==slot)
        end=next(i for i,r in enumerate(events) if r['kind']=='RUN_FINISHED' and r['slot']==slot)
        reservations=[r for r in events[start:end] if r['kind']=='REQUEST_RESERVED']
        responses=[r for r in events[start:end] if r['kind']=='REQUEST_FINISHED']
        reads=[r for r in responses if r['url']==plan['endpoint'] and r['httpStatus']==200]
        if (len(reservations)!=2 or len(responses)!=2 or len(reads)!=1
                or [r['url'] for r in reservations]!=[plan['robotsUrl'],plan['endpoint']]
                or any(r['url']!=q['url'] or r['reservation']!=q['hash'] for r,q in zip(responses,reservations))
                or responses[0]['httpStatus'] not in (200,404,410)
                or not instant(events[start]['at'])<=instant(reads[0]['observedAt'])<=instant(events[end]['at'])
                or bundle['generatedAt']!=reads[0]['observedAt']
                or bundle['missionId']!=plan['id'] or bundle['fixtures']!=plan['fixtures']
                or len(bundle['picks'])!=e['count']
                or any(p['authorUrl']!=plan['endpoint'] or p['parserSha256']!=plan['parserSha256']
                       or p['calendarSha256']!=plan['calendarSha256'] or p['responseSha256']!=reads[0]['responseSha256']
                       or p['observedAt']!=reads[0]['observedAt'] for p in bundle['picks'])):
            raise ValueError('profile slot lineage')
        observed=instant(reads[0]['observedAt'])
        if slot=='canary':
            valid_window=instant(plan['canaryNotBefore'])<=observed<instant(plan['canaryExpires'])
        else:
            valid_window=instant(slot)<=observed<instant(slot)+timedelta(minutes=10)
        if not valid_window or observed>=instant(mission['expires_at']):raise ValueError('profile observation window')
        result=merge_sro_collection(result,bundle) if result else bundle
    expired=now>=instant(mission['expires_at']);locked=(directory/'campaign.lock').exists()
    pending=[s for s in plan['slots'] if s not in completed]
    missed=bool(pending and now>=instant(pending[0])+timedelta(minutes=10))
    finished=not pending and bool(completed)
    result['profileCampaign']=dict(state='expired' if expired else 'halted' if halted else 'missed_slot' if missed else 'blocked_lock' if locked else 'completed' if finished else 'collecting' if completed else 'scheduled',
        successfulSlots=len(completed),slots=len(plan['slots'])+1,requests=sum(e['kind']=='REQUEST_RESERVED' for e in events),
        requestsMax=18,startsAt=plan['slots'][0],expiresAt=mission['expires_at'],authorUrl=plan['endpoint'],campaignId=plan['id'],
        termsMonitoring='Bounded reuse of source terms; no per-slot terms request.')
    return result,bool(completed and not expired and not locked and not halted and not missed and not finished)


def validate_registration(directory: Path) -> dict[str,Any]:
    data,enabled=read_campaign(directory)
    receipt=json.loads((directory/'canary-recette.json').read_bytes())
    plan,mission=validate_packet(directory)
    state=data['profileCampaign']
    events=read_events(directory/'events.jsonl')
    accepted=[e for e in events if e['kind']=='PUBLIC_COLLECTION_ACCEPTED']
    if (not enabled or state['successfulSlots']!=1 or state['requests']!=2 or accepted[0]['slot']!='canary'
            or receipt.get('status')!='PASS' or receipt.get('taskRegistrationAuthorized') is not True
            or receipt.get('keys')!=['C0','C1','C4']
            or receipt.get('planSha256')!=mission['source_hash']
            or receipt.get('journalSha256')!=sha256((directory/'events.jsonl').read_bytes()).hexdigest()
            or receipt.get('observationSha256')!=accepted[0]['observationSha256']):
        raise ValueError('independent canary recipe absent/changed')
    root=Path(__file__).resolve().parents[3]
    decisions=[json.loads(line) for line in (root/'reports/council/decision-ledger.jsonl').read_bytes().splitlines()]
    key=[r for r in decisions if r['decision_id']==plan['registrationDecisionId']]
    if (len(key)!=1 or key[0]['decision']!='PASS_AND_HOLD' or key[0]['hash']!=receipt.get('decisionRecordHash')
            or key[0]['context'].get('keys')!=['C0','C1','C4']
            or key[0]['context'].get('journal_sha256')!=receipt['journalSha256']
            or key[0]['context'].get('observation_sha256')!=receipt['observationSha256']):
        raise ValueError('independent canary registration key absent')
    return dict(status='valid',missionId=plan['id'])
