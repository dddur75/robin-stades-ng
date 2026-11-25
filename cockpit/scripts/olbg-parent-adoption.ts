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
function checkpoint(a:StableCheckpointApproval):Companion{
 const report=obj(readApproved(a.admissionReport,16384));
 need(report.claimId===ADMISSION&&report.newUniqueAdmitted===1
  &&report.oldPublicChoicesPreserved===483&&report.publicChoices===484
  &&report.totalRecentOLBGChoices===4&&report.documentaryPrematchRecertified===false
  &&report.sourceReady===false&&report.recurringCollectionActive===false);
 const saved=obj(readApproved(a.data,32768));
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
  calendarSHA256:c.calendarSHA256,batchCount:1,publicBaseSHA256:c.publicBaseSHA256};
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
  claimIds:[...new Set([...priorClaims,c.claimId,ADMISSION])],
  localAdmittedCheckpoint:{state:'PRESERVED',restoredCampaignChoices:1,applicationNewChoices:0,sourceReady:false}} as T;
}
export function restoreStableCatalogue<T extends J>(base:T,a:StableCheckpointApproval|null=STABLE_CHECKPOINT_APPROVAL):T{
 if(a===null)return base;
 return {...mergeCampaignCatalogue(base,checkpoint(a)),
  localAdmittedCheckpoint:{state:'PRESERVED',restoredCampaignChoices:1,applicationNewChoices:0,sourceReady:false}} as T;
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
