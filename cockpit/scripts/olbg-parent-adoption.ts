// Preserve an explicitly approved local admission while new parent proof is unavailable.
import {createHash} from 'node:crypto';
import {closeSync,fstatSync,openSync,readSync} from 'node:fs';
import {resolve} from 'node:path';
import {
 applyOLBGCampaignCatalogue,applyOLBGCampaignPublic,mergeCampaignCatalogue,
 mergeCampaignPicks,
} from './olbg-campaign-companion';
import type {OLBGCampaignApproval,ParentProofIO} from './olbg-campaign-companion';
import {createRootParentProofIO} from './root-parent-proof';
import type {RootNamespaceRecord} from './root-parent-proof';

type J=Record<string,unknown>;
type Companion=Parameters<typeof mergeCampaignCatalogue>[1];
type ApprovedCheckpoint=Companion&{admissionClaimId:string;priorClaimIds?:string[];priorCompanion?:Companion};
export type StableCheckpointApproval=Readonly<{
 data:RootNamespaceRecord;admissionReport:RootNamespaceRecord;sourceBatchSHA256:string;
}>;
export type ApprovedParentNamespace=Readonly<{
 namespace:RootNamespaceRecord;adoption:RootNamespaceRecord;
}>;
export const STABLE_CHECKPOINT_APPROVAL:StableCheckpointApproval|null=null;
export const PARENT_NAMESPACE_APPROVAL:ApprovedParentNamespace|null=null;
const ADMISSION='DATA.SOURCE_OBSERVATORY.OLBG.ONE.LOCAL.APP.ADMISSION.20261125';
const HASH=/^[a-f0-9]{64}$/;
function need(value:unknown):asserts value{if(!value)throw Error('OLBG_LOCAL_ADOPTION_WAIT');}
function obj(value:unknown):J{need(value!==null&&typeof value==='object'&&!Array.isArray(value));return value as J;}
function canonical(value:unknown):string{
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical((value as J)[k])).join(',')+'}';
 const result=JSON.stringify(value);need(result!==undefined);return result;
}
function equal(a:unknown,b:unknown):boolean{return canonical(a)===canonical(b);}
function hash(raw:Uint8Array):string{return createHash('sha256').update(raw).digest('hex');}
function readApproved(record:RootNamespaceRecord,cap:number):unknown{
 need(resolve(record.path)===record.path&&HASH.test(record.sha256));
 const fd=openSync(record.path,'r');
 try{
  const size=fstatSync(fd).size;need(Number.isSafeInteger(size)&&size>0&&size<=cap);
  const raw=Buffer.alloc(size+1),n=readSync(fd,raw,0,raw.length,0);
  need(n===size&&hash(raw.subarray(0,n))===record.sha256);
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw.subarray(0,n)));
 }finally{closeSync(fd);}
}
function checkpointV2(saved:J,report:J,a:StableCheckpointApproval):ApprovedCheckpoint{
 const priorRecord=obj(saved.priorCheckpoint);
 need(typeof priorRecord.sha256==='string'&&HASH.test(priorRecord.sha256)
  &&typeof priorRecord.path==='string'&&report.priorCheckpointSHA256===priorRecord.sha256);
 const prior=obj(readApproved(priorRecord as RootNamespaceRecord,262144)),priorC=obj(prior.companion);
 need((prior.schemaVersion==='olbg-admitted-r5-checkpoint-v1'&&prior.admissionClaimId===ADMISSION
   ||prior.schemaVersion==='olbg-admitted-checkpoint-v2'&&typeof prior.admissionClaimId==='string'&&/^DATA\.SOURCE_OBSERVATORY\.[A-Z0-9_.]+$/.test(prior.admissionClaimId))
  &&typeof prior.admissionReportSHA256==='string'&&HASH.test(prior.admissionReportSHA256)
  &&typeof prior.sourceBatchSHA256==='string'&&HASH.test(prior.sourceBatchSHA256)
  &&prior.sourceBatchSHA256!==a.sourceBatchSHA256&&Number.isSafeInteger(priorC.batchCount)&&Number(priorC.batchCount)>0&&Number(priorC.batchCount)<50
  &&typeof priorC.calendarSHA256==='string'&&HASH.test(priorC.calendarSHA256)
  &&typeof priorC.claimId==='string'&&priorC.claimId.length>0);
 const claim=report.claimId,newCount=report.newUniqueAdmitted,oldCount=report.oldPublicChoicesPreserved;
 need(typeof claim==='string'&&/^DATA\.SOURCE_OBSERVATORY\.[A-Z0-9_.]+$/.test(claim)&&claim!==ADMISSION
  &&Number.isSafeInteger(newCount)&&Number(newCount)>0&&Number(newCount)<=20
  &&Number.isSafeInteger(oldCount)&&Number(oldCount)>0&&report.publicChoices===Number(oldCount)+Number(newCount)
  &&Number.isSafeInteger(report.nativeAuthorId)&&Number(report.nativeAuthorId)>0
  &&report.documentaryPrematchRecertified===false&&report.sourceReady===false&&report.recurringCollectionActive===false
  &&saved.admissionClaimId===claim&&saved.admissionReportSHA256===a.admissionReport.sha256
  &&HASH.test(a.sourceBatchSHA256)&&saved.sourceBatchSHA256===a.sourceBatchSHA256&&report.sourceBatchSHA256===a.sourceBatchSHA256);
 const c=obj(saved.companion);
 need(Array.isArray(priorC.picks)&&priorC.picks.length>0&&priorC.picks.length<=50&&Array.isArray(priorC.fixtures)
  &&Array.isArray(c.picks)&&c.picks.length===priorC.picks.length+Number(newCount)&&c.picks.length<=50
  &&Array.isArray(c.fixtures)&&c.fixtures.length>0&&c.fixtures.length<=32&&c.batchCount===Number(priorC.batchCount)+1
  &&typeof c.claimId==='string'&&c.claimId.length>0&&typeof c.calendarSHA256==='string'&&HASH.test(c.calendarSHA256)
  &&typeof c.publicBaseSHA256==='string'&&HASH.test(c.publicBaseSHA256)
  &&c.publicBaseSHA256===priorC.publicBaseSHA256
  &&equal(c.picks.slice(0,priorC.picks.length),priorC.picks));
 need(c.picks.slice(priorC.picks.length).every(v=>obj(v).authorId===`olbg:${report.nativeAuthorId}`&&obj(v).calendarSha256===c.calendarSHA256));
 const fixtureIds=new Set<string>();
 for(const value of c.fixtures){const f=obj(value);need(typeof f.id==='string'&&!fixtureIds.has(f.id));fixtureIds.add(f.id);}
 for(const value of priorC.fixtures){const f=obj(value);need(c.fixtures.some(v=>equal(v,f)));}
 const ids=new Set<string>(),nativeKeys=new Set<string>();
 for(const value of c.picks){
  const p=obj(value);need(typeof p.id==='string'&&p.id.length>0&&!ids.has(p.id)
   &&typeof p.authorId==='string'&&/^olbg:[1-9]\d*$/.test(p.authorId)&&p.sourceUrl===`https://www.olbg.com/tipsters/tips/${p.authorId.slice(5)}`
   &&typeof p.sourceId==='string'&&Number.isSafeInteger(p.sourceTipId)&&Number(p.sourceTipId)>0
   &&typeof p.fixtureId==='string'&&fixtureIds.has(p.fixtureId)
   &&['performanceEvaluationAllowed','settlementAllowed','marketInterpretationAllowed'].every(k=>p[k]===false)
   &&typeof p.observedAt==='string'&&typeof p.kickoff==='string'&&Number.isFinite(Date.parse(p.observedAt))
   &&Number.isFinite(Date.parse(p.kickoff))&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(p.observedAt)&&/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(p.kickoff)
   &&Date.parse(p.observedAt)<Date.parse(p.kickoff));
  const fixture=obj(c.fixtures.find(v=>obj(v).id===p.fixtureId));need(fixture.kickoff===p.kickoff);
  const key=canonical([p.sourceId,p.authorId,p.sourceTipId]);need(!nativeKeys.has(key));nativeKeys.add(key);ids.add(p.id);
 }
 return {picks:c.picks.map(obj),fixtures:c.fixtures.map(obj),claimId:c.claimId,calendarSHA256:c.calendarSHA256,
  batchCount:Number(c.batchCount),publicBaseSHA256:c.publicBaseSHA256,admissionClaimId:claim,priorClaimIds:[ADMISSION,String(prior.admissionClaimId),priorC.claimId],
  priorCompanion:{picks:priorC.picks.map(obj),fixtures:priorC.fixtures.map(obj),claimId:priorC.claimId,
   calendarSHA256:priorC.calendarSHA256,batchCount:Number(priorC.batchCount),publicBaseSHA256:c.publicBaseSHA256}};
}
function checkpoint(a:StableCheckpointApproval):ApprovedCheckpoint{
 const report=obj(readApproved(a.admissionReport,16384));
 const saved=obj(readApproved(a.data,262144));
 if(saved.schemaVersion==='olbg-admitted-checkpoint-v2')return checkpointV2(saved,report,a);
 need(report.claimId===ADMISSION&&report.newUniqueAdmitted===1
  &&report.oldPublicChoicesPreserved===483&&report.publicChoices===484
  &&report.totalRecentOLBGChoices===4&&report.documentaryPrematchRecertified===false
  &&report.sourceReady===false&&report.recurringCollectionActive===false);
 readApproved(a.data,32768);
 need(saved.schemaVersion==='olbg-admitted-r5-checkpoint-v1'&&saved.admissionClaimId===ADMISSION
  &&saved.admissionReportSHA256===a.admissionReport.sha256
  &&HASH.test(a.sourceBatchSHA256)&&saved.sourceBatchSHA256===a.sourceBatchSHA256);
 const c=obj(saved.companion);
 need(Array.isArray(c.picks)&&c.picks.length===1&&Array.isArray(c.fixtures)&&c.fixtures.length===1
  &&typeof c.claimId==='string'&&typeof c.calendarSHA256==='string'&&HASH.test(c.calendarSHA256)
  &&typeof c.publicBaseSHA256==='string'&&HASH.test(c.publicBaseSHA256)&&c.batchCount===1);
 const p=obj(c.picks[0]),fixture=obj(c.fixtures[0]);
 need(p.fixtureId===fixture.id&&['performanceEvaluationAllowed','settlementAllowed','marketInterpretationAllowed'].every(k=>p[k]===false));
 return {picks:c.picks.map(obj),fixtures:c.fixtures.map(obj),claimId:c.claimId,
  calendarSHA256:c.calendarSHA256,batchCount:1,publicBaseSHA256:c.publicBaseSHA256,admissionClaimId:ADMISSION};
}
export function approvedParentIO(a:ApprovedParentNamespace|null=PARENT_NAMESPACE_APPROVAL):ParentProofIO|undefined{
 if(a===null)return undefined;
 try{
  const receipt=obj(readApproved(a.adoption,8192));
  need(receipt.schemaVersion==='olbg-parent-proof-local-adoption-v1'
   &&receipt.namespaceSHA256===a.namespace.sha256&&receipt.rootExit===0
   &&receipt.rootReturnObserved===true&&equal(receipt.approvedBy,['C0','C1','C4'])
   &&receipt.sourceReady===false&&receipt.applicationNewChoices===0);
  return createRootParentProofIO(a.namespace);
 }catch{return undefined;}
}
function waiting<T extends J>(stable:T):T{
 return {...stable,localParentProof:{state:'WAIT',applicationNewChoices:0,sourceReady:false,recurringCollectionActive:false}} as T;
}
export function restoreStablePublic<T extends J>(base:T,baseSHA:string,a:StableCheckpointApproval|null=STABLE_CHECKPOINT_APPROVAL):T{
 if(a===null)return base;
 const c=checkpoint(a);need(baseSHA===c.publicBaseSHA256&&Array.isArray(base.fixtures));
 const picks=mergeCampaignPicks(base.picks,c.picks),fixtures=structuredClone(base.fixtures) as J[];
 for(const fixture of c.fixtures){
  const prior=fixtures.find(v=>v.id===fixture.id);
  if(prior)need(['id','kickoff','home','away','label'].every(k=>prior[k]===undefined||equal(prior[k],fixture[k])));
  else fixtures.push(structuredClone(fixture));
 }
 const priorClaims=Array.isArray(base.claimIds)?base.claimIds:[base.claimId].filter(v=>v!==undefined);
 return {...base,picks,fixtures,distinctPicks:picks.length,authorCount:new Set(picks.map(p=>p.authorId)).size,
  claimIds:[...new Set([...priorClaims,...(c.priorClaimIds??[]),c.claimId,c.admissionClaimId])],
  localAdmittedCheckpoint:{state:'PRESERVED',restoredCampaignChoices:c.picks.length,applicationNewChoices:0,sourceReady:false}} as T;
}
export function restoreStableCatalogue<T extends J>(base:T,a:StableCheckpointApproval|null=STABLE_CHECKPOINT_APPROVAL):T{
 if(a===null)return base;
 const c=checkpoint(a);
 let restored=base;
 if(c.priorCompanion){
  for(const batch of [c.priorCompanion,{...c,picks:c.picks.slice(c.priorCompanion.picks.length)}]){
   const groups=new Map<string,J[]>();
   for(const p of batch.picks){const author=String(p.authorId);groups.set(author,[...(groups.get(author)??[]),p]);}
   for(const picks of groups.values())restored=mergeCampaignCatalogue(restored,{...batch,picks,fixtures:batch.fixtures.filter(f=>picks.some(p=>p.fixtureId===f.id))});
  }
 }else restored=mergeCampaignCatalogue(restored,c);
 return {...restored,
  localAdmittedCheckpoint:{state:'PRESERVED',restoredCampaignChoices:c.picks.length,applicationNewChoices:0,sourceReady:false}} as T;
}
export function preserveIdempotentProjection<T extends J>(stable:T,projected:T,kind:'public'|'catalogue'):T{
 const fields=kind==='public'?['picks','fixtures']:['candidates'];
 if(!fields.every(k=>equal(stable[k],projected[k])))return waiting(stable);
 return {...projected,localParentProof:{state:'VERIFIED_IDEMPOTENT',applicationNewChoices:0,sourceReady:false,recurringCollectionActive:false}} as T;
}
export function applyParentCampaignPublic<T extends J>(stable:T,root:string,baseSHA:string,approval:OLBGCampaignApproval|null=null,parent:ApprovedParentNamespace|null=PARENT_NAMESPACE_APPROVAL):T{
 if(approval===null)return stable;
 const io=approvedParentIO(parent);if(io===undefined)return waiting(stable);
 const projected=applyOLBGCampaignPublic(stable,root,baseSHA,approval,io);
 if(obj(projected.olbgCampaignCompanion??{}).state!=='accepted_batches')return waiting(stable);
 return preserveIdempotentProjection(stable,projected,'public');
}
export function applyParentCampaignCatalogue<T extends J>(stable:T,root:string,approval:OLBGCampaignApproval|null=null,parent:ApprovedParentNamespace|null=PARENT_NAMESPACE_APPROVAL):T{
 if(approval===null)return stable;
 const io=approvedParentIO(parent);if(io===undefined)return waiting(stable);
 const projected=applyOLBGCampaignCatalogue(stable,root,approval,io);
 if(obj(projected.olbgCampaignCompanion??{}).state!=='accepted_batches')return waiting(stable);
 return preserveIdempotentProjection(stable,projected,'catalogue');
}
