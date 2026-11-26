import {createHash} from 'node:crypto';
import {openSync,closeSync,fstatSync,readSync} from 'node:fs';
import {resolve} from 'node:path';

export type JsonObject=Record<string,unknown>;
export type Approval={relativePath:string;wrapperSHA256:string;parentClaimId:string;claimId:string;decisionSHA256:string;candidateSHA256:string;receiptSHA256:string;sourceResponseSHA256:string;sourceObservedAt:string;immutablePicksSHA256:string;allowedNativeChoiceIds:readonly string[];maximumUpdates:number;maximumBytes:number;choices:number;pseudonyms:number;fixtures:number};
const PARENT='DATA.SOURCE_OBSERVATORY.SRO.CANARY.R2.REOBSERVED.20261121';
const CLAIM='DATA.SOURCE_OBSERVATORY.SRO.HISTORICAL.CANARY.R2.APP.ADMISSION.20261122';
const MISSION='SRO_SUCCESSOR_MANUAL_CANARY_E1_R2_20261121';
const HASH=/^[a-f0-9]{64}$/;
const WRAPPER_KEYS='schemaVersion parentClaimId acceptedClaimId sourceMissionId candidateSHA256 receiptSHA256 sourceResponseSHA256 sourceObservedAt immutablePicksSHA256 updates'.split(' ');
const APPROVAL_KEYS='relativePath wrapperSHA256 parentClaimId claimId decisionSHA256 candidateSHA256 receiptSHA256 sourceResponseSHA256 sourceObservedAt immutablePicksSHA256 allowedNativeChoiceIds maximumUpdates maximumBytes choices pseudonyms fixtures'.split(' ');
function check(v:unknown):asserts v{if(!v)throw Error('SRO_HISTORICAL_UPDATES_UNAVAILABLE');}
function object(v:unknown):JsonObject{check(v!==null&&typeof v==='object'&&!Array.isArray(v));check([Object.prototype,null].includes(Object.getPrototypeOf(v)));return v as JsonObject;}
function exact(v:JsonObject,keys:string[]):void{check(Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k)));}
function text(v:unknown,max=256):string{check(typeof v==='string'&&v.length>0&&v.length<=max);return v;}
function canonical(v:unknown):string{
 if(v===null||typeof v==='string'||typeof v==='boolean')return JSON.stringify(v);
 if(typeof v==='number'){check(Number.isFinite(v));return JSON.stringify(v);}
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 const row=object(v);return '{'+Object.keys(row).sort().map(k=>JSON.stringify(k)+':'+canonical(row[k])).join(',')+'}';
}
function sha(v:string|Uint8Array):string{return createHash('sha256').update(v).digest('hex');}
function digest(v:unknown):string{return sha(canonical(v));}
function utc(v:unknown):bigint{
 const s=text(v,40),m=/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(s);check(m);
 const ms=Date.parse(m[1]+'Z');check(Number.isFinite(ms)&&new Date(ms).toISOString().slice(0,19)===m[1]);
 return BigInt(ms)*BigInt(1000)+BigInt((m[2]??'').padEnd(6,'0'));
}
/** Every pick field except lastSeenAt; sorted by original ID, without re-identification. */
export function immutablePicksSHA256(picks:unknown):string{
 check(Array.isArray(picks));const rows=picks.map(p=>object(p)).map(p=>Object.fromEntries(Object.entries(p).filter(([k])=>k!=='lastSeenAt')));
 rows.sort((a,b)=>text(a.id)<text(b.id)?-1:text(a.id)>text(b.id)?1:0);return digest(rows);
}
function approval(value:Approval):Approval{
 const a=object(value);exact(a,APPROVAL_KEYS);
 for(const k of ['wrapperSHA256','decisionSHA256','candidateSHA256','receiptSHA256','sourceResponseSHA256','immutablePicksSHA256'])check(HASH.test(text(a[k])));
 check(a.parentClaimId===PARENT&&a.claimId===CLAIM&&a.relativePath==='.ci/sro-historical-approved/'+a.wrapperSHA256+'/updates.json');
 for(const k of ['choices','pseudonyms','fixtures'])check(Number.isSafeInteger(a[k])&&Number(a[k])>0&&Number(a[k])<=2000);
 check(Number.isSafeInteger(a.maximumUpdates)&&Number(a.maximumUpdates)>0&&Number(a.maximumUpdates)<=55);
 check(a.maximumBytes===65536&&Array.isArray(a.allowedNativeChoiceIds)&&a.allowedNativeChoiceIds.length===a.maximumUpdates);
 check(a.allowedNativeChoiceIds.every(x=>HASH.test(text(x)))&&new Set(a.allowedNativeChoiceIds).size===a.allowedNativeChoiceIds.length);utc(a.sourceObservedAt);
 return value;
}

/** Pure preview only; an all-zero decision is never accepted by the filesystem entrypoint. */
export function projectSROHistoricalUpdates(base:JsonObject,value:unknown,binding:Approval):JsonObject{
 try{
  const a=approval(binding),w=object(value);exact(w,WRAPPER_KEYS);check(sha(canonical(w)+'\n')===a.wrapperSHA256);
  check(w.schemaVersion==='sro-approved-historical-updates-v1'&&w.parentClaimId===PARENT&&w.acceptedClaimId===CLAIM&&w.sourceMissionId===MISSION);
  for(const k of ['candidateSHA256','receiptSHA256','sourceResponseSHA256','sourceObservedAt','immutablePicksSHA256'])check(w[k]===a[k as keyof Approval]);
  check(base.status==='ok'&&Array.isArray(base.picks)&&base.picks.length===a.choices&&base.distinctPicks===a.choices&&base.authorCount===a.pseudonyms);
  const picks=base.picks.map(p=>object(p)),byId=new Map<string,JsonObject>();
  for(const p of picks){const id=text(p.id);check(!byId.has(id));byId.set(id,p);}
  check(new Set(picks.map(p=>text(p.authorId))).size===a.pseudonyms&&new Set(picks.map(p=>text(p.fixtureId))).size===a.fixtures);
  check(immutablePicksSHA256(picks)===a.immutablePicksSHA256);
  check(Array.isArray(base.fixtures)&&base.fixtures.length===a.fixtures);const fixtures=new Map<string,JsonObject>();
  for(const v of base.fixtures){const f=object(v),id=text(f.id);check(!fixtures.has(id));utc(f.kickoff);fixtures.set(id,f);}
  const observed=utc(w.sourceObservedAt);check(utc(base.sourceObservedThrough)>=observed);
  check(Array.isArray(w.updates)&&w.updates.length===a.maximumUpdates);
  const allowed=new Set(a.allowedNativeChoiceIds),seen=new Set<string>(),replacements=new Map<string,JsonObject>();
  const updates:Record<string,{lastSeenAt:string;claimId:string}>=Object.create(null);
  for(const v of w.updates){
   const u=object(v);exact(u,['id','lastSeenAt']);const id=text(u.id);check(allowed.has(id)&&!seen.has(id));seen.add(id);
   check(u.lastSeenAt===w.sourceObservedAt);const p=byId.get(id);check(p&&p.sourceId==='SRC_039'&&p.market==='correct_score');
   check(p.authorId===digest(['SRC_039',text(p.authorUrl)])&&id===digest(['SRC_039',p.authorId,p.fixtureId,'correct_score']));
   const fixture=fixtures.get(text(p.fixtureId));check(fixture&&utc(fixture.kickoff)===utc(p.kickoff)&&observed<utc(p.kickoff));
   check(utc(p.observedAt)<=observed&&utc(p.firstSeenAt)<=observed&&utc(p.lastSeenAt??p.observedAt)<=observed);
   replacements.set(id,{...p,lastSeenAt:u.lastSeenAt});updates[id]={lastSeenAt:text(u.lastSeenAt),claimId:CLAIM};
  }
  check(seen.size===allowed.size);
  const previous=base.sroNextCompanion===undefined?undefined:object(base.sroNextCompanion);
  if(previous?.sourceObservedAt!==undefined)check(utc(previous.sourceObservedAt)<=observed);
  const priorUpdates=previous?.updates===undefined?{}:object(previous.updates);
  for(const [id,value] of Object.entries(priorUpdates)){const u=object(value);exact(u,['lastSeenAt','claimId']);const pick=byId.get(id);check(pick?.sourceId==='SRC_039');utc(u.lastSeenAt);text(u.claimId);if(allowed.has(id))check(utc(u.lastSeenAt)<=observed);}
  const claims=base.claimIds===undefined?(base.claimId===undefined?[]:[base.claimId]):base.claimIds;check(Array.isArray(claims)&&claims.every(c=>typeof c==='string'));
  return {...base,picks:picks.map(p=>replacements.get(String(p.id))??p),claimIds:[...new Set([...claims,PARENT,CLAIM])],
   sroNextCompanion:{updates:{...priorUpdates,...updates},claimId:CLAIM,parentClaimId:PARENT,sourceMissionId:MISSION,
    candidateSHA256:a.candidateSHA256,receiptSHA256:a.receiptSHA256,sourceResponseSHA256:a.sourceResponseSHA256,
    sourceObservedAt:a.sourceObservedAt,wrapperSHA256:a.wrapperSHA256,decisionSHA256:a.decisionSHA256,
    approvedReobservationCount:a.maximumUpdates,approvedNewCount:0,kind:'historical_reobservations'}};
 }catch{return base;}
}

/** Local approved file only; every failure returns the unmodified base atomically. */
export function applyReviewedSROHistoricalUpdates(base:JsonObject,root:string,value:Approval):JsonObject{
 let fd:number|undefined;
 try{
  const a=approval(value);check(a.decisionSHA256!=='0'.repeat(64));fd=openSync(resolve(root,a.relativePath),'r');
  const info=fstatSync(fd);check(info.isFile()&&info.size>0&&info.size<=a.maximumBytes);
  const buffer=Buffer.alloc(a.maximumBytes+1);let size=0;
  while(size<buffer.length){const n=readSync(fd,buffer,size,buffer.length-size,null);if(!n)break;size+=n;}
  check(size>0&&size<=a.maximumBytes);const raw=buffer.subarray(0,size);check(sha(raw)===a.wrapperSHA256);
  const wrapper=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
  // Close succeeds before any projection is returned. No partial data survives failure.
  closeSync(fd);fd=undefined;return projectSROHistoricalUpdates(base,wrapper,a);
 }catch{return base;}
 finally{if(fd!==undefined){try{closeSync(fd);}catch{/* Rejected bundle returns its base. */}}}
}
