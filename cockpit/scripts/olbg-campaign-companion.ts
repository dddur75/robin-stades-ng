import {createHash} from 'node:crypto';
import {closeSync,fstatSync,openSync,readSync} from 'node:fs';
import {resolve} from 'node:path';

type J=Record<string,unknown>;
export type OLBGCampaignApproval=Readonly<{planSHA256:string;manifestSHA256:string;claimId:string;publicBaseSHA256:string;campaignDirectory?:string}>;
export const OLBG_CAMPAIGN_APPROVAL:OLBGCampaignApproval|null=null;
const HASH=/^[a-f0-9]{64}$/;
const IMMUTABLE=['id','sourceId','authorId','sourceTipId','sourceEventId','fixtureId','kickoff','sourceUrl','authorUrl','market','calendarSha256'];
const VERSION=['selection','sourceMarketLabel','sourceBetType','sourceFields'];
const FLAGS=['performanceEvaluationAllowed','settlementAllowed','marketInterpretationAllowed'];
function check(v:unknown):asserts v{if(!v)throw Error('OLBG_CAMPAIGN_COMPANION_REFUSED');}
function obj(v:unknown):J{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as J;}
function arr(v:unknown,max=2000):unknown[]{check(Array.isArray(v)&&v.length<=max);return v;}
function text(v:unknown,max=240):string{check(typeof v==='string'&&v.length>0&&v.length<=max);return v;}
function integer(v:unknown):number{check(typeof v==='number'&&Number.isSafeInteger(v)&&v>0);return v;}
function canonical(v:unknown):string{
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as J)[k])).join(',')+'}';
 const s=JSON.stringify(v);check(s!==undefined);return s;
}
function hash(v:Uint8Array|string):string{return createHash('sha256').update(v).digest('hex');}
function equal(a:unknown,b:unknown):boolean{return canonical(a??null)===canonical(b??null);}
function clone<T>(v:T):T{return JSON.parse(JSON.stringify(v)) as T;}
function utc(v:unknown):number{const s=text(v,80);check(/(?:Z|\+00:00)$/.test(s));const n=Date.parse(s);check(Number.isFinite(n));return n;}
function decode(raw:Uint8Array,sha:string,cap:number):unknown{check(raw.length>0&&raw.length<=cap&&HASH.test(sha)&&hash(raw)===sha);return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}
function bounded(path:string,cap:number):Uint8Array{const fd=openSync(path,'r');try{const size=fstatSync(fd).size;check(size>0&&size<=cap&&Number.isSafeInteger(size));const raw=Buffer.alloc(size+1);const n=readSync(fd,raw,0,raw.length,0);check(n===size);return raw.subarray(0,n);}finally{closeSync(fd);}}
function pickKey(p:J):string{return typeof p.sourceId==='string'&&typeof p.authorId==='string'&&typeof p.sourceTipId==='number'?canonical([p.sourceId,p.authorId,p.sourceTipId]):canonical(['legacy',text(p.id)]);}
function checkTimes(p:J):void{check(utc(p.firstSeenAt??p.observedAt)<=utc(p.observedAt)&&utc(p.observedAt)<=utc(p.lastSeenAt??p.observedAt)&&utc(p.lastSeenAt??p.observedAt)<utc(p.kickoff));}
export function mergeCampaignPicks(previous:unknown,additional:J[]):J[]{
 const out=arr(previous).map(v=>clone(obj(v))),keys=new Map<string,J>(),ids=new Map<string,string>();
 for(const p of out){checkTimes(p);const k=pickKey(p),id=text(p.id);check(!keys.has(k)&&!ids.has(id));keys.set(k,p);ids.set(id,k);}
 for(const incoming of additional){checkTimes(incoming);const p=clone(incoming),key=pickKey(p),id=text(p.id),old=keys.get(key);check(!ids.has(id)||ids.get(id)===key);check(utc(p.lastSeenAt??p.observedAt)<utc(p.kickoff)&&FLAGS.every(k=>p[k]===false));
  if(!old){p.lastSeenAt=p.lastSeenAt??p.observedAt;p.observationVersions=p.observationVersions??[Object.fromEntries([...VERSION,'observedAt','responseSha256'].map(k=>[k,clone(p[k])]))];out.push(p);keys.set(key,p);ids.set(id,key);continue;}
  check(IMMUTABLE.every(k=>equal(old[k],p[k])));check(utc(p.firstSeenAt??p.observedAt)>=utc(old.firstSeenAt??old.observedAt));
  const before=utc(old.lastSeenAt??old.observedAt),after=utc(p.lastSeenAt??p.observedAt);check(after>=before);
  if(after===before){check([...VERSION,'responseSha256'].every(k=>equal(old[k],p[k])));continue;}
  const first=old.firstSeenAt??old.observedAt;
  const observations=clone(arr(old.observationVersions??[Object.fromEntries([...VERSION,'observedAt','responseSha256'].map(k=>[k,old[k]]))],200));
    const incomingObservations=arr(p.observationVersions??[Object.fromEntries([...VERSION,'observedAt','responseSha256'].map(k=>[k,p[k]]))],200);
  for(const value of incomingObservations){const observation=obj(value),at=utc(observation.observedAt);check(at<=after&&at<utc(p.kickoff));const same=observations.find(v=>utc(obj(v).observedAt)===at);if(same)check(equal(same,observation));else if(at>before)observations.push(clone(observation));}
  observations.sort((a,b)=>utc(obj(a).observedAt)-utc(obj(b).observedAt));
  const versions=clone(arr(old.versions,200));for(const value of observations){const observation=obj(value);if(utc(observation.observedAt)>before&&obj(versions[versions.length-1]).selection!==observation.selection)versions.push({selection:observation.selection,observedAt:observation.observedAt});}
  Object.assign(old,p,{firstSeenAt:first,observedAt:p.observedAt,lastSeenAt:p.lastSeenAt??p.observedAt,versions,versionCount:versions.length,observationVersions:observations});
 }return out;
}
type Companion={picks:J[];fixtures:J[];claimId:string;calendarSHA256:string;batchCount:number;publicBaseSHA256:string;profileId?:number};
function companionProfile(c:Companion):{id:number;url:string}{
 check(c.picks.length>0);const author=text(c.picks[0].authorId),match=/^olbg:([1-9][0-9]*)$/.exec(author);check(match!==null);
 const id=c.profileId??Number(match[1]);check(typeof id==='number'&&Number.isSafeInteger(id)&&id>0&&author==='olbg:'+id);
 const url='https://www.olbg.com/tipsters/tips/'+id;check(c.picks.every(p=>p.authorId==='olbg:'+id&&p.sourceUrl===url&&p.authorUrl===url));return {id,url};
}
export type ParentProofIO={loadControl:(slot:string,name:'primary.json'|'result.json'|'AUTHOR-STOP.json')=>Uint8Array;confirmExit:(campaignId:string,slot:string,receiptSHA256:string)=>boolean};
const PARENT_KEYS='schemaVersion missionId slotRunMissionId slot sourceDecisionLedgerHash accepted childExit timedOut subtreeKillConfirmed batch primarySHA256 resultSHA256 STOP_SHA256 rawStdout rawStderr postChildFullGuardPassed sourceReady'.split(' ');
function verifyParent(plan:J,slot:string,receipt:J,loadFile:(name:string)=>Uint8Array,io:ParentProofIO|undefined):number{
 try{
  check(io!==undefined);
  const raw=loadFile('slot-parent-'+hash(slot)+'.json');check(raw.length>0&&raw.length<=16384);
  const r=obj(JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(raw)));
  check(Object.keys(r).length===PARENT_KEYS.length&&PARENT_KEYS.every(k=>Object.hasOwn(r,k)));
  check(r.schemaVersion==='olbg-slot-parent-accepted-v1'&&r.missionId===plan.id&&r.slot===slot&&r.accepted===true&&r.childExit===0&&r.timedOut===false&&r.subtreeKillConfirmed===true&&r.postChildFullGuardPassed===true&&r.sourceReady===false);
  text(r.slotRunMissionId,200);check(HASH.test(text(r.sourceDecisionLedgerHash)));
  const batch=obj(r.batch);check(Object.keys(batch).length===4&&batch.file===receipt.observationFile&&batch.sha256===receipt.observationSha256&&typeof batch.bytes==='number'&&Number.isSafeInteger(batch.bytes)&&batch.bytes>0&&batch.bytes<=131072&&batch.recordCount===receipt.count);
  const values=new Map<string,J>();
  for(const [name,field,cap] of [['primary.json','primarySHA256',32768],['result.json','resultSHA256',8192],['AUTHOR-STOP.json','STOP_SHA256',4096]]as const){
   const bytes=io!.loadControl(slot,name);values.set(name,obj(decode(bytes,text(r[field]),cap)));
  }
  const primary=values.get('primary.json')!,result=values.get('result.json')!,stop=values.get('AUTHOR-STOP.json')!,job=obj(primary.job);
  check(job.exit===0&&job.timedOut===false&&job.subtreeKillConfirmed===true&&primary.failureKind===null);
  check(result.schemaVersion==='olbg-slot-parent-result-v1'&&result.status==='SLOT_PROCESS_COMPLETE'&&result.accepted===true&&result.missionId===plan.id&&result.slot===slot&&equal(result.batch,batch)&&result.primarySHA256===r.primarySHA256&&obj(result.child).status==='OPAQUE_SLOT_DISPATCH_COMPLETE'&&stop.accepted===true&&stop.resultSHA256===r.resultSHA256);
  for(const[name,field]of[['stdout.raw','rawStdout'],['stderr.raw','rawStderr']]as const){
   const summary=obj(r[field]),retained=obj(obj(primary.rawStreams)[name]);check(Object.keys(summary).length===2&&Object.hasOwn(summary,'sha256')&&Object.hasOwn(summary,'bytes'));
   const encoded=typeof retained.base64==='string'?retained.base64:'';const decoded=Buffer.from(encoded,'base64');
   check(decoded.toString('base64')===encoded&&decoded.length<=8192&&decoded.length===summary.bytes&&retained.bytes===summary.bytes&&hash(decoded)===summary.sha256&&retained.sha256===summary.sha256);
  }
  // CALLER_R1 has childExit, not its own OS exit. ROOT must supply actual return proof.
  check(io!.confirmExit(text(plan.id),slot,hash(raw))===true);
  return batch.bytes as number;
 }catch{throw Error('OLBG_PARENT_RECEIPT_WAIT');}
}

/** Validate the owning producer's accepted native batch; no new JS qualifier. */
export function readAcceptedOLBGNativeBatch(batchRaw:Uint8Array,digest:string,plan:J,expectedResponseSHA:string,expectedCount:unknown):J[]{
 const profileId=plan.profileId??648433;check(typeof profileId==='number'&&Number.isSafeInteger(profileId)&&profileId>0);
 const URL='https://www.olbg.com/tipsters/tips/'+profileId,fixtures=arr(plan.fixtures,32).map(obj),proof={responseSha256:expectedResponseSHA},receipt={count:expectedCount},a={claimId:plan.claimId};
  const b=obj(decode(batchRaw,digest,131072));check(b.schemaVersion==='robin-olbg-opaque-campaign-batch-v1'&&b.missionId===plan.id&&b.claimId===a.claimId&&b.parserSha256===plan.parserSha256&&b.builderSha256===plan.builderSha256&&b.calendarSha256===plan.calendarSha256&&b.sourceReady===false&&b.applicationAdmissions===0&&b.recurrence===true);
  const source=obj(b.source);check(equal(source.fixtures,fixtures)&&source.calendarSha256===plan.calendarSha256);
  const profiles=arr(source.profiles,1);check(profiles.length===1);const profile=obj(profiles[0]),facts=obj(profile.facts),request=obj(profile.request);check(facts.authorId===profileId&&facts.mode==='current'&&request.url===URL&&request.responseSha256===proof.responseSha256);text(facts.authorLabel,80);utc(request.observedAt);
  const records=arr(facts.records,20).map(obj),accepted=arr(b.acceptedSourceTipIds,20).map(integer),rows=arr(b.picks,20).map(obj);check(rows.length>0&&rows.length===receipt.count&&rows.length===accepted.length&&new Set(accepted).size===accepted.length);
  check(new Set(rows.map(p=>p.sourceTipId)).size===rows.length);for(const p of rows){const tid=integer(p.sourceTipId),matches=records.filter(n=>n.tipid===tid);check(matches.length===1&&accepted.includes(tid));const native=matches[0],fixture=fixtures.find(f=>f.id===p.fixtureId);check(fixture&&equal(p.sourceFields,native)&&native.vc_sport_id===1&&native.result==='Open');integer(native.eventid);
   check(p.id==='olbg-tip:'+tid&&p.sourceId==='SRC_014'&&p.authorId==='olbg:'+profileId&&p.sourceEventId===native.eventid&&p.authorLabel===facts.authorLabel&&p.authorUrl===URL&&p.sourceUrl===URL&&p.kickoff===fixture.kickoff&&p.fixtureLabel===fixture.label);
   check(p.observedAt===request.observedAt&&p.firstSeenAt===request.observedAt&&utc(p.observedAt)<utc(p.kickoff)&&p.selection===native.selection&&p.sourceMarketLabel===native.market&&p.sourceBetType===native.winew&&p.sourceEventLocalText===native.event_datetime);
   check(p.responseSha256===proof.responseSha256&&p.parserSha256===plan.parserSha256&&p.calendarSha256===plan.calendarSha256&&p.market==='source_native_opaque'&&FLAGS.every(k=>p[k]===false)&&p.publishedAt===null&&p.publishedCivilDate===null&&p.sourceEventTimezone===null);
   check(p.versionCount===1&&equal(p.versions,[{selection:p.selection,observedAt:p.observedAt}]));text(p.selection,120);text(p.fixtureId);
  }
 return rows;
}

export function readCampaignBuffers(planRaw:Uint8Array,mfRaw:Uint8Array,journalRaw:Uint8Array,loadBatch:(name:string)=>Uint8Array,a:OLBGCampaignApproval,parentIO?:ParentProofIO):Companion{
 const plan=obj(decode(planRaw,a.planSHA256,65536)),mf=obj(decode(mfRaw,a.manifestSHA256,16384));
 const profileId=plan.profileId??648433;check(typeof profileId==='number'&&Number.isSafeInteger(profileId)&&profileId>0);const URL='https://www.olbg.com/tipsters/tips/'+profileId;
 check(Object.keys(mf).length===8&&mf.mission_id===plan.id&&mf.maximum_stage==='E2'&&equal(mf.authorized_stages,['E1','E2'])&&mf.source_hash===hash(canonical(plan)));
 check(plan.claimId===a.claimId&&plan.endpoint===URL&&plan.robotsUrl==='https://www.olbg.com/robots.txt'&&plan.termsUrl==='https://www.olbg.com/use'&&plan.zeroEligiblePolicy==='HALT');
 const slots=arr(plan.slots,12).map(v=>text(v,80));check(slots.length>0&&new Set(slots).size===slots.length&&equal(slots,[...slots].sort()));for(const s of slots)check(utc(s)<utc(mf.expires_at));
 check(equal(mf.external_effects,{https_get_max:slots.length*3,per_source_max:slots.length*3}));
 const fixtures=arr(plan.fixtures,32).map(obj);check(fixtures.length>0&&plan.calendarSha256===hash(canonical(fixtures)));
 check(HASH.test(text(plan.parserSha256))&&HASH.test(text(plan.builderSha256))&&HASH.test(a.publicBaseSHA256));
 check(journalRaw.length<=2_000_000);const journal=new TextDecoder('utf-8',{fatal:true}).decode(journalRaw);check(journal.length===0||journal.endsWith('\n'));
 const lines=journal.length?journal.slice(0,-1).split('\n'):[];check(lines.length<=2048);let previous='0'.repeat(64);
 const events=lines.map((line,index)=>{const e=obj(JSON.parse(line)),h=text(e.hash);const record={...e};delete record.hash;check(e.sequence===index+1&&e.previousHash===previous&&h===hash(canonical(record))&&line===canonical(e));previous=h;return e;});
 const starts=events.filter(e=>e.kind==='PUBLIC_SLOT_STARTED'),finishes=events.filter(e=>e.kind==='PUBLIC_SLOT_FINISHED'),receipts=events.filter(e=>e.kind==='PUBLIC_COLLECTION_ACCEPTED');
 check(new Set(starts.map(e=>e.slot)).size===starts.length&&new Set(receipts.map(e=>e.slot)).size===receipts.length&&receipts.length===finishes.length);
 check(events.filter(e=>e.kind==='RUN_STARTED').length===events.filter(e=>e.kind==='RUN_FINISHED').length);
 check(receipts.length>0&&equal([...new Set(starts.map(e=>e.slot))].sort(),[...new Set(finishes.map(e=>e.slot))].sort())&&equal([...new Set(starts.map(e=>e.slot))].sort(),[...new Set(receipts.map(e=>e.slot))].sort()));
 let picks:J[]=[];const used=new Set<string>();
 for(const receipt of receipts){const ss=starts.filter(e=>e.slot===receipt.slot),ff=finishes.filter(e=>e.slot===receipt.slot);check(slots.includes(text(receipt.slot))&&ss.length===1&&ff.length===1&&Number(ss[0].sequence)<Number(receipt.sequence)&&Number(receipt.sequence)<Number(ff[0].sequence)&&ff[0].count===receipt.count);
  const segment=events.slice(Number(ss[0].sequence),Number(receipt.sequence)-1),q=segment.filter(e=>e.kind==='PUBLIC_PICKS_QUALIFIED'),requests=segment.filter(e=>e.kind==='REQUEST_FINISHED'&&e.sourceId==='SRC_014'&&e.url===URL&&e.httpStatus===200);check(q.length===1&&requests.length===1);
  const proof=q[0];check(proof.responseSha256===requests[0].responseSha256&&proof.parserSha256===plan.parserSha256&&proof.calendarSha256===plan.calendarSha256&&proof.count===receipt.count);
  const digest=text(receipt.observationSha256),name=text(receipt.observationFile);check(HASH.test(digest)&&name==='observations-'+digest+'.json');
  const parentBytes=verifyParent(plan,text(receipt.slot),receipt,loadBatch,parentIO);const batchRaw=loadBatch(name);check(batchRaw.length===parentBytes);
  const rows=readAcceptedOLBGNativeBatch(batchRaw,digest,plan,text(proof.responseSha256),receipt.count);for(const p of rows)used.add(text(p.fixtureId));
  // The approved campaign writer performs the exact owning Python builder.
  // This consumer proves accepted-chain/code/field lineage, not a new JS qualifier.
  picks=mergeCampaignPicks(picks,rows);
 }
 check(finishes.every(e=>receipts.some(r=>r.slot===e.slot)));
 return {picks,fixtures:fixtures.filter(f=>used.has(text(f.id))),claimId:a.claimId,calendarSHA256:text(plan.calendarSha256),batchCount:receipts.length,publicBaseSHA256:a.publicBaseSHA256,profileId};
}
function mergePublic<T extends J>(base:T,c:Companion,baseSHA:string):T{
 check(baseSHA===c.publicBaseSHA256);const prior=arr(base.picks).map(obj),picks=mergeCampaignPicks(prior,c.picks),fixtures=arr(base.fixtures).map(v=>clone(obj(v)));
 for(const f of c.fixtures){const old=fixtures.find(x=>x.id===f.id);if(old)check(['id','kickoff','home','away','label'].every(k=>old[k]===undefined||equal(old[k],f[k])));else fixtures.push(clone(f));}
 const claims=arr(base.claimIds??[base.claimId],500);
 return {...base,picks,fixtures,distinctPicks:picks.length,authorCount:new Set(picks.map(p=>p.authorId)).size,claimIds:[...new Set([...claims,c.claimId])],olbgCampaignCompanion:{state:'accepted_batches',batches:c.batchCount,sourceReady:false,recurringCollectionActive:false,globalCoverage:'UNKNOWN'}} as T;
}
export function mergeCampaignCatalogue<T extends J>(base:T,c:Companion):T{
 const profile=companionProfile(c),URL=profile.url,history='https://www.olbg.com/tipsters/tips/history/'+profile.id,candidates=arr(base.candidates,20000).map(obj),matches=candidates.filter(x=>x.platform==='OLBG'&&(x.sourceUrl===URL||x.sourceUrl===history));check(matches.length===1);const target=matches[0],origin=obj(target.origin);check(target.id==='catalogue:'+hash(text(target.sourceUrl))&&origin.sheet==='Catalogue'&&typeof origin.row==='number'&&Number.isSafeInteger(origin.row)&&origin.row>0);
 const q=obj(target.qualification??{picks:[]}),picks=mergeCampaignPicks(q.picks??[],c.picks),ids=new Set(c.picks.map(p=>'olbg-pending-'+profile.id+'-'+integer(p.sourceTipId)));
 let pending=target.pendingOLBGObservation;if(pending!==undefined){const p=obj(pending);pending={...p,records:arr(p.records,20).filter(v=>!ids.has(text(obj(v).key)))};}
 const qualified={...q,picks,personallyProven:picks.length>0,retainedClaimIds:[...new Set([...arr(q.retainedClaimIds??[],200),...(!equal(picks,q.picks??[])?[c.claimId]:[])])]};
 const updated=candidates.map(row=>row===target?{...row,qualification:qualified,...(pending===undefined?{}:{pendingOLBGObservation:pending})}:row);
 const root=base.qualification===undefined?undefined:obj(base.qualification);const qualification=root?.status==='ok'?{...root,qualifiedCount:updated.filter(row=>obj(row.qualification??{}).personallyProven===true).length}:base.qualification;
 return {...base,candidates:updated,...(qualification===undefined?{}:{qualification}),olbgCampaignCompanion:{state:'accepted_batches',batches:c.batchCount,sourceReady:false,recurringCollectionActive:false,globalCoverage:'UNKNOWN'}} as T;
}
function readLocal(root:string,a:OLBGCampaignApproval,parentIO?:ParentProofIO):Companion{
 const legacy=resolve(root,'.ci/local-robin/olbg-opaque-campaign');
 const expected=resolve(root,'.ci/local-robin/olbg-opaque-campaigns',a.planSHA256);
 check(HASH.test(a.planSHA256)&&(a.campaignDirectory===undefined||a.campaignDirectory===legacy||a.campaignDirectory===expected));
 const dir=a.campaignDirectory??legacy;
 return readCampaignBuffers(bounded(resolve(dir,'plan.json'),65536),bounded(resolve(dir,'manifest.json'),16384),bounded(resolve(dir,'events.jsonl'),2_000_000),name=>bounded(resolve(dir,name),131072),a,parentIO);
}
export function applyOLBGCampaignCatalogue<T extends J>(base:T,root:string,a:OLBGCampaignApproval|null=OLBG_CAMPAIGN_APPROVAL,parentIO?:ParentProofIO):T{if(a===null)return base;try{return mergeCampaignCatalogue(base,readLocal(root,a,parentIO));}catch{return {...base,olbgCampaignCompanion:{state:'waiting_or_unavailable',sourceReady:false}} as T;}}
export function applyOLBGCampaignPublic<T extends J>(base:T,root:string,baseSHA:string,a:OLBGCampaignApproval|null=OLBG_CAMPAIGN_APPROVAL,parentIO?:ParentProofIO):T{if(a===null)return base;try{return mergePublic(base,readLocal(root,a,parentIO),baseSHA);}catch{return {...base,olbgCampaignCompanion:{state:'unavailable',sourceReady:false}} as T;}}
