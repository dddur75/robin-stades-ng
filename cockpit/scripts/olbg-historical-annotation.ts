import{createHash}from'node:crypto';
import{openSync,fstatSync,readSync,closeSync}from'node:fs';
import{resolve}from'node:path';
export type HistoricalAnnotationApproval={relativePath:string;sidecarSHA256:string;targetRowSHA256:string;targetIdSHA256:string;sourceTipIdSHA256:string;authorIdSHA256:string;fixtureIdSHA256:string;versionsSHA256:string;claimId:string};
const HASH=/^[a-f0-9]{64}$/;
export const HISTORICAL_LABEL="Observation enregistr\u00e9e avant le programme officiel conserv\u00e9";
function need(x:unknown):asserts x{if(!x)throw Error('HISTORICAL_ANNOTATION_UNAVAILABLE');}
function obj(x:unknown):Record<string,unknown>{need(x!==null&&typeof x==='object'&&!Array.isArray(x));return x as Record<string,unknown>;}
function canon(x:unknown):string{if(Array.isArray(x))return'['+x.map(canon).join(',')+']';if(x&&typeof x==='object')return'{'+Object.entries(x).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>JSON.stringify(k)+':'+canon(v)).join(',')+'}';const s=JSON.stringify(x);need(s!==undefined);return s;}
function sha(x:string|Buffer):string{return createHash('sha256').update(x).digest('hex');}
function utc(x:unknown):bigint{need(typeof x==='string'&&/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)$/.test(x));const ms=Date.parse(x);need(Number.isFinite(ms)&&new Date(ms).toISOString().slice(0,19)===x.slice(0,19));const fraction=(x.match(/\.([0-9]+)/)?.[1]??'').padEnd(6,'0');return BigInt(ms)*BigInt(1000)+BigInt(fraction.slice(3));}
export function applyHistoricalAnnotation<T extends Record<string,unknown>>(base:T,raw:Buffer,a:HistoricalAnnotationApproval):T{
 for(const k of ['sidecarSHA256','targetRowSHA256','targetIdSHA256','sourceTipIdSHA256','authorIdSHA256','fixtureIdSHA256','versionsSHA256']as const)need(HASH.test(a[k]));
 need(raw.length>0&&raw.length<=131072&&sha(raw)===a.sidecarSHA256&&a.claimId==='ENG.SOURCE_OBSERVATORY.OLBG.ONE.PROGRAMME.AUTHOR.NAMESPACE.FIX.RESULT.20261123');
 const proof=obj(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)));
 need(proof.sourceTipIdSHA256===a.sourceTipIdSHA256&&proof.observationBeforeRetainedOfficialProgramme===true&&proof.originalMembershipVerified===true&&proof.sourceVersionLinked===true&&proof.versionSelectionUnchanged===true&&proof.originalFlagsUnchanged===true&&proof.originalInputsUnchanged===true);
 for(const k of ['nativeOLBGTimezoneEstablished','nativePublicationTimeEstablished','actualKickoffEstablished','programmeKnownAtCaptureEstablished','programmeStabilityEstablished','sourceReady'])need(proof[k]===false);
 for(const k of ['sourceGET','newSourceAcquisitions','newFutureForecasts','admissions','appChanges','otherStockRequalified'])need(proof[k]===0);
 const observed=proof.collectorObservedUTC,programme=proof.officialProgrammeUTC;need(utc(observed)<utc(programme));
 need(Array.isArray(proof.sourceClaims)&&proof.sourceClaims.every(x=>typeof x==='string')&&Array.isArray(base.picks));
 const picks=base.picks as unknown[];const matches=picks.map((p,i)=>[p,i]as const).filter(([p])=>typeof obj(p).id==='string'&&sha(obj(p).id as string)===a.targetIdSHA256);need(matches.length===1);
 const [value,index]=matches[0],row=obj(value);
 need(sha(canon(row))===a.targetRowSHA256&&(typeof row.sourceTipId==='string'||(typeof row.sourceTipId==='number'&&Number.isSafeInteger(row.sourceTipId)&&row.sourceTipId>0))&&sha(String(row.sourceTipId))===a.sourceTipIdSHA256&&typeof row.authorId==='string'&&sha(row.authorId)===a.authorIdSHA256&&typeof row.fixtureId==='string'&&sha(row.fixtureId)===a.fixtureIdSHA256&&sha(canon(row.versions))===a.versionsSHA256);
 need(row.historicalProgrammeObservation===undefined);
 const annotation={kind:'retained_programme_historical_only',label:HISTORICAL_LABEL,proofSHA256:a.sidecarSHA256,claimId:a.claimId,collectorObservedUTC:observed,officialProgrammeUTC:programme,nativeTimezoneEstablished:false,actualKickoffEstablished:false,performanceAllowed:false,sourceReady:false};
 const output=picks.slice();output[index]={...row,historicalProgrammeObservation:annotation};return{...base,picks:output};
}
export function readHistoricalAnnotation<T extends Record<string,unknown>>(base:T,root:string,a:HistoricalAnnotationApproval):T{
 need(a.relativePath==='.ci/historical-programme/'+a.sidecarSHA256+'/sidecar.json');let fd:number|undefined;
 try{fd=openSync(resolve(root,a.relativePath),'r');const stat=fstatSync(fd);need(stat.isFile()&&stat.size>0&&stat.size<=131072);const b=Buffer.alloc(131073);let n=0;while(n<b.length){const got=readSync(fd,b,n,b.length-n,null);if(!got)break;n+=got;}need(n<=131072);return applyHistoricalAnnotation(base,b.subarray(0,n),a);}finally{if(fd!==undefined)closeSync(fd);}
}
