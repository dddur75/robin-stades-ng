import {createHash} from 'node:crypto';
import {readFileSync,lstatSync} from 'node:fs';
import {isAbsolute} from 'node:path';

export const ARCHIVE_APP_PURPOSE='READONLY_ACCEPTED_TIPSTERS_ARCHIVE_V1';
const KEYS=['C0','C1','C3','C4'],HASH=/^[a-f0-9]{64}$/;
const PATHS=['/api/tipsters/public','/api/tipsters/candidates','/api/tipsters/qualification'];
const CAPS={routeBytes:8000000,items:2000,ledgerBytes:16000000};
const need=v=>{if(!v)throw Error('ACCEPTED_TIPSTERS_ARCHIVE_UNAVAILABLE')};
const sha=v=>createHash('sha256').update(v).digest('hex');
const obj=v=>{need(v&&typeof v==='object'&&!Array.isArray(v));return v};
const arr=v=>{need(Array.isArray(v)&&v.length<=CAPS.items);return v};
export function canonical(v){if(Array.isArray(v))return'['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';const s=JSON.stringify(v);need(s!==undefined);return s}
const equal=(a,b)=>canonical(a)===canonical(b);
const stamp=v=>{need(typeof v==='string'&&/(?:Z|\+00:00)$/.test(v)&&Number.isFinite(Date.parse(v)));return Date.parse(v)};
function bytes(path,cap){need(typeof path==='string'&&isAbsolute(path));const st=lstatSync(path);need(st.isFile()&&!st.isSymbolicLink()&&st.size>0&&st.size<=cap);const b=readFileSync(path);need(b.length===st.size);return b}
function pinned(r,cap){obj(r);need(HASH.test(r.sha256));const b=bytes(r.path,cap);need(sha(b)===r.sha256);return b}
const decode=b=>obj(JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(b)));
function identified(v){const rows=arr(v),seen=new Set();for(const r of rows){obj(r);need(typeof r.id==='string'&&r.id.length>0&&!seen.has(r.id));seen.add(r.id)}return rows}

// Same GET guard as RT scripts/tipsters-pilot-plugin.ts; do not trust the bind
// address alone, because a foreign Host/Origin can reach a loopback listener.
const loopback=new Set(['127.0.0.1','::1','::ffff:127.0.0.1']);
const hostnames=new Set(['127.0.0.1','localhost','[::1]']);
export function permitsLocalAcceptedArchiveRead(request){
 if(!loopback.has(request.socket.remoteAddress??'')||request.method!=='GET')return false;
 try{
  const host=request.headers.host;if(!host)return false;
  const address=new URL(`http://${host}`);
  if(!hostnames.has(address.hostname)||address.host!==host||address.pathname!=='/')return false;
  if(request.headers.origin&&request.headers.origin!==address.origin)return false;
  const site=request.headers['sec-fetch-site'];
  return !site||site==='same-origin'||site==='none';
 }catch{return false}
}

// MF.source_hash binds this core. The MF pin is instead bound by the actual grant,
// avoiding a hash cycle. Its own file hash and all eight fields are still verified.
export function approvalBinding(approval){const {grantHash,bindingSHA256,manifest,...core}=approval;return sha(canonical(core))}
export function admissionWindowAllows(grantDate,manifestExpiry,admissionDeadline){return stamp(grantDate)<=Math.min(stamp(manifestExpiry),stamp(admissionDeadline))}

export function validateAcceptedTipstersSnapshots(v){
 const pub=obj(v.public),cat=obj(v.candidates),qual=obj(v.qualification);
 need(PATHS.every((_,i)=>[pub,cat,qual][i].status==='ok'));
 const fixtures=identified(pub.fixtures),byFixture=new Map(fixtures.map(f=>[f.id,f]));
 for(const f of fixtures)stamp(f.kickoff);
 for(const p of identified(pub.picks)){const f=byFixture.get(p.fixtureId);need(f&&typeof p.authorId==='string'&&stamp(p.observedAt)<stamp(f.kickoff));if(p.kickoff!==undefined)need(stamp(p.kickoff)===stamp(f.kickoff))}
 for(const c of identified(cat.candidates)){
  need(typeof c.platform==='string'&&typeof c.sourceUrl==='string');
  if(c.qualification!==undefined){const q=obj(c.qualification);if(q.picks!==undefined)arr(q.picks);if(q.personallyProven===true)need(Array.isArray(q.picks)&&q.picks.length>0)}
 }
 stamp(qual.capturedAt);for(const row of identified(qual.results)){stamp(row.checkedAt);need(stamp(row.checkedAt)<=stamp(qual.capturedAt))}
 return v;
}

export function readAcceptedTipstersArchive(approval,now=Date.now()){
 const a=obj(approval);need(HASH.test(a.bindingSHA256)&&approvalBinding(a)===a.bindingSHA256);
 const m=decode(pinned(a.manifest,65536));
 need(equal(Object.keys(m).sort(),['mission_id','authorized_stages','maximum_stage','external_effects','compute_budget','time_budget','source_hash','expires_at'].sort()));
 need(m.mission_id===a.missionId&&m.source_hash===a.bindingSHA256&&equal(m.authorized_stages,['E1','E2'])&&m.maximum_stage==='E2');
 need(m.external_effects.SourceGET===0&&m.external_effects.Task===0);
 need(Array.isArray(a.consumerPins)&&a.consumerPins.length>=2&&a.consumerPins.length<=20);
 for(const pin of a.consumerPins)pinned(pin,2000000);
 const records=obj(a.archive),snapshots={};for(const name of ['public','candidates','qualification'])snapshots[name]=decode(pinned(records[name],CAPS.routeBytes));
 validateAcceptedTipstersSnapshots(snapshots);
 if(a.liveApproval!==null&&a.liveApproval!==undefined){obj(a.liveApproval);need(a.liveApproval.spec.publicBaseSHA256===records.public.sha256&&HASH.test(a.liveApproval.bindingSHA256))}
 const ledger=bytes(a.ledgerPath,CAPS.ledgerBytes),prefix=obj(a.ledgerPrefix);
 need(Number.isSafeInteger(prefix.bytes)&&prefix.bytes>0&&prefix.bytes<=ledger.length&&sha(ledger.subarray(0,prefix.bytes))===prefix.sha256);
 const head=ledger.subarray(0,prefix.bytes);need(head.at(-1)===10&&JSON.parse(head.toString('utf8').trimEnd().split('\n').at(-1)).hash===prefix.head);
 const tail=ledger.subarray(prefix.bytes);need(tail.length===0||tail.at(-1)===10);
 let previous=prefix.head;const rows=[];
 for(const line of tail.toString('utf8').split('\n').filter(Boolean)){const r=obj(JSON.parse(line)),{hash,...body}=r;need(canonical(r)===line&&HASH.test(hash)&&r.previous_hash===previous&&sha(canonical(body))===hash);rows.push(r);previous=hash}
 const grants=rows.filter(r=>r.hash===a.grantHash);need(grants.length===1);const grant=grants[0],g=obj(grant.context);
 need(grant.record_type==='DECISION'&&grant.decision==='PASS_AND_SCALE'&&grant.responsible==='C0'&&stamp(grant.date)<=now);
 need(g.mission_id===a.missionId&&g.stage==='E2'&&equal(g.keys,KEYS)&&g.purpose===ARCHIVE_APP_PURPOSE&&g.sourceAllowed===false&&g.appArchiveProjectionAllowed===true&&g.bindingSHA256===a.bindingSHA256&&g.manifestSHA256===sha(canonical(m)));
 need(admissionWindowAllows(grant.date,m.expires_at,a.admissionDeadline));
 for(const row of rows.slice(rows.indexOf(grant)+1)){
  const c=row.context??{},same=c.mission_id===a.missionId;
  const veto=row.record_type==='VETO'&&(same||c.global===true||c.severity==='CRITICAL'||[undefined,'GLOBAL','GOVERNANCE'].includes(c.mission_id));
  const denied=same&&(['FAILURE','REDESIGN'].includes(row.record_type)||['FAIL_AND_STOP','FAIL_AND_REDESIGN','BLOCKED_EXTERNAL_ACTION'].includes(row.decision));
  const passiveClosure=same&&['DECISION','STAGE_FINISHED'].includes(row.record_type)&&row.decision==='PASS_AND_HOLD'&&c.sourceAllowed===false&&c.archiveReadPreserved===true&&c.bindingSHA256===a.bindingSHA256;
  need(!veto&&!denied&&!(same&&c.authorityClosed===true&&!passiveClosure));
 }
 // Expiry limits the admission grant, not subsequent reads of accepted, pinned facts.
 return {snapshots,publicSHA256:records.public.sha256,claimId:a.claimId,archivedAt:snapshots.qualification.capturedAt,admittedAt:grant.date};
}

function archiveState(archive,now,liveState){return {state:'accepted_frozen_archive',claimId:archive.claimId,archivedAt:archive.archivedAt,admittedAt:archive.admittedAt,readAt:new Date(now).toISOString(),frozen:true,stale:true,snapshotAgeMilliseconds:Math.max(0,now-stamp(archive.archivedAt)),liveState,sourceGET:0}}
function checkedOutput(route,value){need(obj(value).status==='ok');if(route===PATHS[0]){identified(value.picks);identified(value.fixtures)}else if(route===PATHS[1])identified(value.candidates);else identified(value.results);need(Buffer.byteLength(JSON.stringify(value))<=CAPS.routeBytes);return value}

export function projectAcceptedTipstersRoute(route,archive,approval,liveFunctions=null,now=Date.now()){
 const at=PATHS.indexOf(route);need(at>=0);const name=['public','candidates','qualification'][at];
 const base=structuredClone(archive.snapshots[name]);let value=base,state='not_configured';
 if(approval.liveApproval!==null&&approval.liveApproval!==undefined){
  state='unavailable';
  try{
   const live=obj(liveFunctions);for(const key of ['readMultiCaptured','applyMultiPublic','applyMultiCatalogue','applyMultiQualification'])need(typeof live[key]==='function');
   need(approval.liveApproval.spec.publicBaseSHA256===archive.publicSHA256);
   const captured=live.readMultiCaptured(approval.liveApproval);need(Array.isArray(captured.closedSlots));
   state=captured.closedSlots.length?(captured.partial?'partial_closed_capture':'accepted'):'awaiting_first_capture';
   if(at===0)value=live.applyMultiPublic(structuredClone(base),approval.liveApproval,archive.publicSHA256);
   else if(at===1)value=live.applyMultiCatalogue(structuredClone(base),approval.liveApproval);
   // A waiting Source never proves no_eligible and never overwrites the ready admin row.
   else if(captured.closedSlots.length>0){value=live.applyMultiQualification(structuredClone(base),approval.liveApproval);need(!value.results.some(r=>r.id===approval.liveApproval.spec.qualificationRowId&&r.outcome==='missing_evidence'))}
   if(at<2)need(['accepted','partial_closed_capture','awaiting_first_capture'].includes(value.multiNativeCapture?.state));
   checkedOutput(route,value);
  }catch{value=base;state='unavailable'}
 }
 return checkedOutput(route,{...value,acceptedTipstersArchive:archiveState(archive,now,state)});
}

export function createAcceptedTipstersArchiveMiddleware(approval,{live=null}={}){
 return function acceptedArchive(req,res,next){
  let route;try{route=new URL(req.url,'http://127.0.0.1').pathname}catch{return next()}
  if(req.method!=='GET'||!PATHS.includes(route))return next();
  res.removeHeader('Access-Control-Allow-Origin');
  res.setHeader('X-Content-Type-Options','nosniff');
  if(!permitsLocalAcceptedArchiveRead(req)){
   res.statusCode=403;res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({status:'forbidden'}));return;
  }
  if(approval===null)return next();
  try{
   const archive=readAcceptedTipstersArchive(approval),value=projectAcceptedTipstersRoute(route,archive,approval,live),body=Buffer.from(JSON.stringify(value));
   res.statusCode=200;res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Length',String(body.length));res.end(body);
  }catch{
   res.statusCode=503;res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({status:'unavailable',error:'ACCEPTED_TIPSTERS_ARCHIVE_UNAVAILABLE'}));
  }
 };
}
