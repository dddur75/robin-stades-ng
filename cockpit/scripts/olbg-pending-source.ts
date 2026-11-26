import {createHash} from 'node:crypto';

export const OLBG_PENDING_BUILDER_CLAIM='ENG.SOURCE_OBSERVATORY.OLBG.PENDING.OBSERVATION.BUILDER.E1.RESULT.20261124';
export type OLBGApproval={pendingSHA256:string;receiptSHA256:string;bytes:number;count:number;observedAtUTC:string;responseSHA256:string;parserSHA256:string;builderSHA256:string;claimId:string};
/** No real pending observation has been approved for application adoption. */
export const REVIEWED_OLBG_PENDING_APPROVAL:Readonly<OLBGApproval>|null=null;
export type OLBGPendingObservation={status:'UNQUALIFIED_SOURCE_PROFILE_RECORDS';observedAtUTC:string;sourceAccountAlias:string;sourceUrl:string;records:{key:string;eventText:string;selection:string;marketText:string;betTypeText:string;nativeDateText:string}[];canonicalFixture:null;preMatchProven:false;personIdentityVerified:false;sourceReady:false;admissible:false;interpretationAllowed:false;performanceEvaluationAllowed:false;settlementAllowed:false;admissions:0;globalCoverage:'UNKNOWN';claimIds:readonly string[]};
type Obj=Record<string,unknown>;
const HASH=/^[a-f0-9]{64}$/;
const PAYLOAD_KEYS=['schemaVersion','status','sourceId','observedAtUTC','responseSHA256','parserSHA256','attribution','sourceRecordCount','records','omitted','competition','canonicalFixture','kickoffUTC','sourceEventTimezone','publishedAt','preMatchProven','sourceReady','admissions','eligibleForApplication','interpretationAllowed','performanceEvaluationAllowed','settlementAllowed','globalCoverage'];
function check(ok:unknown):asserts ok{if(!ok)throw Error('OLBG_PENDING_SOURCE_REFUSED');}
function object(v:unknown):Obj{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as Obj;}
function exact(v:unknown,keys:readonly string[]):Obj{const o=object(v);check(Object.keys(o).length===keys.length&&keys.every(k=>Object.hasOwn(o,k)));return o;}
function text(v:unknown,max:number,empty=false):string{check(typeof v==='string');const chars=Array.from(v);check(chars.length>=(empty?0:1)&&chars.length<=max&&!/[\u0000-\u001f\u007f-\u009f]/.test(v)&&chars.every(c=>{const n=c.codePointAt(0)!;return n<0xd800||n>0xdfff;}));return v;}
function integer(v:unknown):number{check(Number.isSafeInteger(v)&&Number(v)>0);return Number(v);}
function utc(v:unknown):string{const s=text(v,40);check(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(s)&&Number.isFinite(Date.parse(s))&&new Date(s).toISOString().slice(0,19)===s.slice(0,19));return s;}
function digest(raw:Uint8Array):string{return createHash('sha256').update(raw).digest('hex');}
export function projectOLBGPending(raw:Uint8Array,receiptRaw:Uint8Array,a:Readonly<OLBGApproval>):OLBGPendingObservation{
 check(raw instanceof Uint8Array&&receiptRaw instanceof Uint8Array&&raw.length===a.bytes&&raw.length>0&&raw.length<=131072&&receiptRaw.length>0&&receiptRaw.length<=65536&&Number.isSafeInteger(a.count)&&a.count>0&&a.count<=20);
 check([a.pendingSHA256,a.receiptSHA256,a.responseSHA256,a.parserSHA256,a.builderSHA256].every(h=>typeof h==='string'&&HASH.test(h))&&digest(raw)===a.pendingSHA256&&digest(receiptRaw)===a.receiptSHA256&&a.claimId.startsWith('DATA.SOURCE_OBSERVATORY.OLBG.PENDING.'));
 const observed=utc(a.observedAtUTC),decoder=new TextDecoder('utf-8',{fatal:true}),report=object(JSON.parse(decoder.decode(receiptRaw))),p=exact(JSON.parse(decoder.decode(raw)),PAYLOAD_KEYS),r=exact(report.pending,['status','SHA256','bytes','recordCount','applicationAdmissions']);
 check(report.claimId===a.claimId&&report.status==='PARTIAL'&&report.sourceReady===false&&report.admissions===0&&report.authorityClosed===true&&report.observedAtUTC===observed&&report.responseSHA256===a.responseSHA256&&report.parserSHA256===a.parserSHA256&&report.pendingBuilderSHA256===a.builderSHA256&&Array.isArray(report.sourceClaims)&&report.sourceClaims.includes(OLBG_PENDING_BUILDER_CLAIM));
 check(r.status==='PRIVATE_UNQUALIFIED_ONLY'&&r.SHA256===a.pendingSHA256&&r.bytes===a.bytes&&r.recordCount===a.count&&r.applicationAdmissions===0);
 check(p.schemaVersion==='olbg-private-pending-profile-observations-v1'&&p.status==='UNQUALIFIED_INDIVIDUAL_PROFILE_OBSERVATIONS'&&p.sourceId==='SRC_014'&&p.observedAtUTC===observed&&p.responseSHA256===a.responseSHA256&&p.parserSHA256===a.parserSHA256&&p.admissions===0&&p.globalCoverage==='UNKNOWN');
 for(const k of ['competition','canonicalFixture','kickoffUTC','sourceEventTimezone','publishedAt'])check(p[k]===null);
 for(const k of ['preMatchProven','sourceReady','eligibleForApplication','interpretationAllowed','performanceEvaluationAllowed','settlementAllowed'])check(p[k]===false);
 const author=exact(p.attribution,['kind','nativeId','label','sourceUrl','personIdentityVerified']),uid=integer(author.nativeId),alias=text(author.label,80),url='https://www.olbg.com/tipsters/tips/'+uid;
 check(author.kind==='SOURCE_PROFILE_ACCOUNT'&&author.personIdentityVerified===false&&author.sourceUrl===url);
 const omitted=exact(p.omitted,['nonFootballOpen','invalidNativeFields']);for(const value of Object.values(omitted))check(Number.isSafeInteger(value)&&Number(value)>=0);
 check(Number.isSafeInteger(p.sourceRecordCount)&&Number(p.sourceRecordCount)<=100&&Array.isArray(p.records)&&p.records.length===a.count&&Number(p.sourceRecordCount)===a.count+Number(omitted.nonFootballOpen)+Number(omitted.invalidNativeFields));
 const seen=new Set<number>();const records=p.records.map(input=>{const row=exact(input,['sourceTipId','sourceEventId','eventText','selectionText','marketText','betTypeText','nativeDateText']),id=integer(row.sourceTipId);integer(row.sourceEventId);check(!seen.has(id));seen.add(id);return {key:'olbg-pending-'+uid+'-'+id,eventText:text(row.eventText,240),selection:text(row.selectionText,120),marketText:text(row.marketText,120,true),betTypeText:text(row.betTypeText,80,true),nativeDateText:text(row.nativeDateText,40)};});
 return {status:'UNQUALIFIED_SOURCE_PROFILE_RECORDS',observedAtUTC:observed,sourceAccountAlias:alias,sourceUrl:url,records,canonicalFixture:null,preMatchProven:false,personIdentityVerified:false,sourceReady:false,admissible:false,interpretationAllowed:false,performanceEvaluationAllowed:false,settlementAllowed:false,admissions:0,globalCoverage:'UNKNOWN',claimIds:[a.claimId,OLBG_PENDING_BUILDER_CLAIM]};
}
export function applyOLBGPending<T extends object>(base:T,raw:Uint8Array,receiptRaw:Uint8Array,a:Readonly<OLBGApproval>|null=REVIEWED_OLBG_PENDING_APPROVAL):T{
 if(a===null)return base;
 try{const observation=projectOLBGPending(raw,receiptRaw,a),previous=(base as {platformPendingObservations?:Record<string,unknown>}).platformPendingObservations;return {...base,platformPendingObservations:{...previous,OLBG:observation}} as T;}catch{return base;}
}
