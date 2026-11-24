import type {OLBGPendingObservation} from './olbg-pending-source';
import {createHash} from 'node:crypto';

export const NOTBETTING_PICKS_URL='https://notbetting.com/en/tipsters-league/picks';
export const SOURCE_CLAIM='ENG.SOURCE_OBSERVATORY.NOTBETTING.PL.NATIVE.R2.ACTUAL.RESULT.20261124';
export const CALENDAR_CLAIM='DATA.SOURCE_OBSERVATORY.PREMIERLEAGUE.NOVEMBER.FUTURE.GMT.PROGRAMME.RESULT.20261124';
export type PendingApproval={pendingSHA256:string;reportSHA256:string;bytes:number;count:number;observedAtUTC:string;responseSHA256:string;pendingAdapterSHA256:string;calendarSHA256:string};
export const REVIEWED_PENDING_APPROVAL:Readonly<PendingApproval>=Object.freeze({pendingSHA256:'d676b71d18f9e9570724159771e81df362749bc74423649d7ee5dbc679a8128b',reportSHA256:'3ff30b9c2fa169f539e9d9e5e6404507fe6f4bb6858b9f313a630140e96d01df',bytes:1238,count:1,observedAtUTC:'2026-11-24T07:07:09.437437+00:00',responseSHA256:'492aa8b655d119e612ee29a5009183d218b0ede407e1f1b5cb7f87a17e7b1a3f',pendingAdapterSHA256:'138214bd7a5933e1fbcc56cecd076031296f982305c3fdf61bb3447bac5a23f6',calendarSHA256:'03fc95484ae179e4459190666103712baa1eea240feef0dd7907a54c79988eba'});
export type PendingSourceRecord={key:string;eventText:string;selection:string;competitionText:string;nativeDateText:string;sourceAccountAlias:string;sourceUrl:string};
export type NotBettingPendingObservation={status:'UNQUALIFIED_SOURCE_ACCOUNT_RECORDS';attribution:'SOURCE_ACCOUNT_UNVERIFIED';observedAtUTC:string;records:PendingSourceRecord[];canonicalFixture:null;preMatchProven:false;personIdentityVerified:false;sourceReady:false;admissible:false;interpretationAllowed:false;performanceEvaluationAllowed:false;settlementAllowed:false;admissions:0;globalCoverage:'UNKNOWN';claimIds:readonly string[]};
export type PlatformPendingObservations={NotBetting?:NotBettingPendingObservation;OLBG?:OLBGPendingObservation};
type Obj=Record<string,unknown>;
const HASH=/^[a-f0-9]{64}$/,UUID=/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/;
const FIELDS=['id','event','pick','competition','date','tipsterId','tipster.user.id','tipster.user.tipster.id','tipster.user.tipster.userId','tipster.user.username'];
function check(ok:unknown):asserts ok{if(!ok)throw Error('PENDING_SOURCE_REFUSED');}
function object(v:unknown):Obj{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as Obj;}
function exact(v:unknown,keys:readonly string[]):Obj{const o=object(v);check(Object.keys(o).length===keys.length&&keys.every(k=>Object.hasOwn(o,k)));return o;}
function text(v:unknown,max=512):string{check(typeof v==='string'&&v.length>0&&v.length<=max);return v;}
function utc(v:unknown):string{const s=text(v,40);check(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(s)&&Number.isFinite(Date.parse(s))&&new Date(s).toISOString().slice(0,19)===s.slice(0,19));return s;}
function digest(raw:Uint8Array):string{return createHash('sha256').update(raw).digest('hex');}
export function projectNotBettingPending(raw:Uint8Array,reportRaw:Uint8Array,a:Readonly<PendingApproval>=REVIEWED_PENDING_APPROVAL):NotBettingPendingObservation{
 check(raw instanceof Uint8Array&&reportRaw instanceof Uint8Array&&raw.length===a.bytes&&raw.length>0&&raw.length<=32768&&reportRaw.length>0&&reportRaw.length<=65536&&Number.isSafeInteger(a.bytes)&&Number.isSafeInteger(a.count)&&a.count>0&&a.count<=4);
 check([a.pendingSHA256,a.reportSHA256,a.responseSHA256,a.pendingAdapterSHA256,a.calendarSHA256].every(h=>typeof h==='string'&&HASH.test(h))&&digest(raw)===a.pendingSHA256&&digest(reportRaw)===a.reportSHA256);
 const observed=utc(a.observedAtUTC),decoder=new TextDecoder('utf-8',{fatal:true}),report=object(JSON.parse(decoder.decode(reportRaw))),r=object(report.pending);
 check(report.claimId===SOURCE_CLAIM&&report.status==='PARTIAL'&&report.sourceReady===false&&report.admissions===0&&report.authorityClosed===true&&report.observedAt===observed&&report.bodySHA===a.responseSHA256&&Array.isArray(report.sourceClaims)&&report.sourceClaims.includes(CALENDAR_CLAIM));
 check(r.status==='PRIVATE_UNQUALIFIED_ONLY'&&r.SHA256===a.pendingSHA256&&r.bytes===a.bytes&&r.recordCount===a.count&&r.applicationAdmissions===0);
 const value=exact(JSON.parse(decoder.decode(raw)),['schemaVersion','status','sourceReady','admissions','observedAtUTC','responseSHA','pendingAdapterSHA','calendarSHA','calendarClaim','records']);
 check(value.schemaVersion==='notbetting-private-pending-source-records-v1'&&value.status==='UNQUALIFIED'&&value.sourceReady===false&&value.admissions===0&&value.observedAtUTC===observed&&value.responseSHA===a.responseSHA256&&value.pendingAdapterSHA===a.pendingAdapterSHA256&&value.calendarSHA===a.calendarSHA256&&value.calendarClaim===CALENDAR_CLAIM&&Array.isArray(value.records)&&value.records.length===a.count);
 const seen=new Set<string>();
 const records:PendingSourceRecord[]=value.records.map((input,index)=>{
  const row=exact(input,['schemaVersion','status','sourceReady','admissions','eligibleForApplication','interpretationAllowed','performanceEvaluationAllowed','settlementAllowed','sourceFields']);
  check(row.schemaVersion==='notbetting-pending-source-fields-v1'&&row.status==='UNQUALIFIED'&&row.admissions===0&&['sourceReady','eligibleForApplication','interpretationAllowed','performanceEvaluationAllowed','settlementAllowed'].every(k=>row[k]===false));
  const f=exact(row.sourceFields,FIELDS);for(const key of FIELDS)text(f[key]);text(f['tipster.user.username'],96);
  const id=text(f.id);check(UUID.test(id)&&!seen.has(id));seen.add(id);const ids=['tipsterId','tipster.user.id','tipster.user.tipster.id','tipster.user.tipster.userId'].map(k=>text(f[k]));check(ids.every(v=>UUID.test(v)&&v===ids[0]));
  return {key:'notbetting-pending-'+index,eventText:text(f.event),selection:text(f.pick),competitionText:text(f.competition),nativeDateText:text(f.date),sourceAccountAlias:text(f['tipster.user.username'],96),sourceUrl:NOTBETTING_PICKS_URL};
 });
 return {status:'UNQUALIFIED_SOURCE_ACCOUNT_RECORDS',attribution:'SOURCE_ACCOUNT_UNVERIFIED',observedAtUTC:observed,records,canonicalFixture:null,preMatchProven:false,personIdentityVerified:false,sourceReady:false,admissible:false,interpretationAllowed:false,performanceEvaluationAllowed:false,settlementAllowed:false,admissions:0,globalCoverage:'UNKNOWN',claimIds:[SOURCE_CLAIM,CALENDAR_CLAIM]};
}
export function applyNotBettingPlatformObservation<T extends object>(base:T,raw:Uint8Array,reportRaw:Uint8Array,a:Readonly<PendingApproval>=REVIEWED_PENDING_APPROVAL):T{
 try{const observation=projectNotBettingPending(raw,reportRaw,a);const previous=(base as {platformPendingObservations?:PlatformPendingObservations}).platformPendingObservations;return {...base,platformPendingObservations:{...previous,NotBetting:observation}} as T;}catch{return base;}
}
