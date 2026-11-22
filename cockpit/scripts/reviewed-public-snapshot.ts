import {createHash} from 'node:crypto';
import {openSync,closeSync,fstatSync,readSync} from 'node:fs';
import {resolve} from 'node:path';
import type {JsonObject} from './forums-accepted';

export type SnapshotApproval={relativePath:string;sha256:string;claimId:string;choices:number;pseudonyms:number;fixtures:number;maximumBytes:number;idsSHA256:string;immutableSHA256:string};
const HASH=/^[a-f0-9]{64}$/;
const immutableFields=['id','firstSeenAt','observedAt','versions','authorLabel','selection','sourceUrl'];
const factFields=['schemaVersion','status','distinctPicks','authorCount','picks','fixtures','calendarEvidence','calendarSha256','parserSha256','missionId','generatedAt','sourceObservedThrough','claimId','claimIds','requestCount','observationSha256','notbettingOccurrenceCompanion','sroNextCompanion','forumCompanion'];
function check(v:unknown):asserts v {if(!v)throw Error('REVIEWED_PUBLIC_SNAPSHOT_UNAVAILABLE');}
function object(v:unknown):JsonObject {check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as JsonObject;}
function canonical(v:unknown):string{
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v&&typeof v==='object')return '{'+Object.entries(v).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,x])=>JSON.stringify(k)+':'+canonical(x)).join(',')+'}';
 const s=JSON.stringify(v);check(s!==undefined);return s;
}
function sha(v:Buffer|string):string{return createHash('sha256').update(v).digest('hex');}
function utc(v:unknown):number{check(typeof v==='string'&&/(?:Z|\+00:00)$/.test(v));const n=Date.parse(v);check(Number.isFinite(n));return n;}

/** Reads exactly one reviewed local fact snapshot; never consults a provider or an operational reader. */
export function readReviewedPublicSnapshot(root:string,a:SnapshotApproval):JsonObject{
 check(HASH.test(a.sha256)&&HASH.test(a.idsSHA256)&&HASH.test(a.immutableSHA256));
 check(a.relativePath==='.ci/public-tipsters-approved/'+a.sha256+'/snapshot.json');
 check(typeof a.claimId==='string'&&a.claimId.startsWith('DATA.'));
 check(Number.isSafeInteger(a.maximumBytes)&&a.maximumBytes>0&&a.maximumBytes<=2000000);
 for(const n of [a.choices,a.pseudonyms,a.fixtures])check(Number.isSafeInteger(n)&&n>0&&n<=2000);
 let fd:number|undefined;let raw:Buffer;
 try{
  fd=openSync(resolve(root,a.relativePath),'r');
  const stat=fstatSync(fd);check(stat.isFile()&&stat.size>0&&stat.size<=a.maximumBytes);
  const bytes=Buffer.alloc(a.maximumBytes+1);let size=0;
  while(size<bytes.length){const n=readSync(fd,bytes,size,bytes.length-size,null);if(!n)break;size+=n;}
  check(size>0&&size<=a.maximumBytes);raw=bytes.subarray(0,size);
 }finally{if(fd!==undefined)closeSync(fd);}
 check(sha(raw)===a.sha256);
 const value=object(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)));
 check(value.schemaVersion==='robin-public-tipsters-v1'&&value.status==='ok');
 check(Array.isArray(value.picks)&&value.picks.length===a.choices&&value.distinctPicks===a.choices&&value.authorCount===a.pseudonyms);
 const picks=value.picks.map(object);
 check(picks.every(p=>typeof p.id==='string'&&p.id.length>0&&p.id.length<=200&&typeof p.authorId==='string'&&typeof p.fixtureId==='string'));
 const ids=picks.map(p=>p.id as string).sort();
 check(new Set(ids).size===a.choices&&new Set(picks.map(p=>p.authorId)).size===a.pseudonyms&&new Set(picks.map(p=>p.fixtureId)).size===a.fixtures);
 check(sha(canonical(ids))===a.idsSHA256);
 const rows=picks.map(p=>Object.fromEntries(immutableFields.map(k=>[k,p[k]]))).sort((a,b)=>String(a.id)<String(b.id)?-1:String(a.id)>String(b.id)?1:0);
 check(sha(canonical(rows))===a.immutableSHA256);
 for(const p of picks){const kickoff=utc(p.kickoff);check(utc(p.observedAt)<kickoff&&utc(p.firstSeenAt)<kickoff);}
 utc(value.generatedAt);utc(value.sourceObservedThrough);
 const result:JsonObject={};
 for(const key of factFields)if(value[key]!==undefined)result[key]=value[key];
 for(const key of ['notbettingOccurrenceCompanion','sroNextCompanion'])if(value[key]!==undefined){const companion=object(value[key]);result[key]={updates:object(companion.updates)};}
 const claims=Array.isArray(value.claimIds)?value.claimIds:[value.claimId];
 check(claims.every(c=>typeof c==='string'));
 result.claimIds=[...new Set([...claims,a.claimId])];
 result.retainedSnapshot={state:'verified',claimId:a.claimId,snapshotSHA256:a.sha256,snapshotPreparedAt:value.generatedAt,operationalState:'unknown'};
 return result;
}
