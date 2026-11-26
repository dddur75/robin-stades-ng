import{createHash}from'node:crypto';
import{readFileSync,lstatSync,existsSync}from'node:fs';import{isAbsolute,join}from'node:path';
import type{MultiCaptureApproval}from'./olbg-multi-capture-types';
import{readAcceptedOLBGMultiNativeBatch}from'./olbg-native-validated-batch';
import{mergeCampaignPicks}from'./olbg-campaign-companion';
import{mergeMultiCapturedPicks}from'./olbg-multi-capture-merge';
import type{QualificationSnapshot,QualificationResult}from'../app/lib/tipster-qualification';
type J=Record<string,unknown>;const HASH=/^[a-f0-9]{64}$/,KEYS=['C0','C1','C3','C4'];
function need(v:unknown):asserts v{if(!v)throw Error('MULTI_CAPTURE_UNAVAILABLE')}
const obj=(v:unknown):J=>{need(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as J};
const arr=(v:unknown,n=26000):unknown[]=>{need(Array.isArray(v)&&v.length<=n);return v};
const str=(v:unknown,n=1000):string=>{need(typeof v==='string'&&v.length>0&&v.length<=n);return v};
const sha=(v:Uint8Array|string)=>createHash('sha256').update(v).digest('hex');
function canon(v:unknown):string{if(Array.isArray(v))return '['+v.map(canon).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canon((v as J)[k])).join(',')+'}';const s=JSON.stringify(v);need(s!==undefined);return s}
const same=(a:unknown,b:unknown)=>canon(a)===canon(b);
const utc=(v:unknown)=>{const s=str(v,80);need(/(?:Z|\+00:00)$/.test(s)&&Number.isFinite(Date.parse(s)));return Date.parse(s)};
function bytes(p:string,cap:number):Buffer{need(isAbsolute(p));const st=lstatSync(p);need(st.isFile()&&!st.isSymbolicLink()&&st.size>0&&st.size<=cap);const b=readFileSync(p);need(b.length>0&&b.length<=cap);return b}
function pin(p:string,digest:string,cap:number):Buffer{need(HASH.test(digest));const b=bytes(p,cap);need(sha(b)===digest);return b}
const decode=(b:Uint8Array)=>obj(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(b)));
function local(d:string,name:unknown,digest:unknown,cap:number):J{const n=str(name,220);need(/^[a-z0-9-]+\.json$/.test(n));return decode(pin(join(d,n),str(digest,64),cap))}
function chained(b:Buffer,council:boolean,previous:string,start:number):J[]{need(b.length===0||b.at(-1)===10);const rows:J[]=[];for(const line of b.toString('utf8').split('\n').filter(Boolean)){const r=obj(JSON.parse(line));need(canon(r)===line);const h=str(r.hash,64),copy={...r};delete copy.hash;need(HASH.test(h)&&sha(canon(copy))===h&&r[council?'previous_hash':'previousHash']===previous);if(!council)need(r.sequence===start+rows.length+1);rows.push(r);previous=h}return rows}
function decisions(a:MultiCaptureApproval):J[]{const s=a.spec,b=bytes(s.ledgerPath,16000000);need(b.length>=s.ledgerPrefix.bytes&&sha(b.subarray(0,s.ledgerPrefix.bytes))===s.ledgerPrefix.sha256);return [...b.subarray(0,s.ledgerPrefix.bytes).toString('utf8').trim().split('\n').map(v=>obj(JSON.parse(v))),...chained(b.subarray(s.ledgerPrefix.bytes),true,s.ledgerPrefix.head,0)]}
function ctx(r:J):J{return r.context===undefined||r.context===null?{}:obj(r.context)}
// BEGIN_CLOSED_TRANSIENT_HELPER
function closedTransientResponses(segment:J[],order:string[],reserved:J[],responses:J[],slot:string,loadProof:(name:unknown,digest:unknown,cap:number)=>J):boolean{
 const failed=segment.filter(e=>e.kind==='PUBLIC_PROFILE_CAPTURE_FAILED'),resolved=segment.filter(e=>e.kind==='HTTP_RESPONSE'||e.kind==='PUBLIC_PROFILE_CAPTURE_FAILED');
 need(resolved.length===reserved.length&&responses.length+failed.length===reserved.length);
 const seen=new Set<number>();let previous=-1;
 for(const e of resolved){
  const isHTTP=e.kind==='HTTP_RESPONSE',role=isHTTP?str(e.role):'profile'+String(e.profileId),index=order.indexOf(role);
  need(index>=0&&index<reserved.length&&index>previous&&!seen.has(index));previous=index;seen.add(index);
  const reservation=reserved[index];need(Number.isSafeInteger(e.sequence)&&Number(e.sequence)>Number(reservation.sequence)&&utc(e.at)>=utc(reservation.at));
  if(isHTTP){need(e.url===reservation.url);continue}
  need(Number.isSafeInteger(e.profileId)&&Number(e.profileId)>0&&e.slot===slot&&e.transient===true&&e.retrySameSlot===false&&e.terminal===false);
  const records=segment.filter(v=>v.kind==='PUBLIC_GET_FAILURE_RECORDED'&&v.slot===slot&&v.role===role);need(records.length===1);
  const record=records[0];need(Number(record.sequence)>Number(reservation.sequence)&&Number(record.sequence)<Number(e.sequence)&&utc(record.at)>=utc(reservation.at)&&utc(record.at)<=utc(e.at));
  const proof=loadProof(record.diagnosticFile,record.diagnosticSHA256,8192),trace=obj(proof.trace),counts=obj(proof.transportCounts);
  need(proof.schemaVersion==='OLBG_CLOSED_GET_FAILURE_V1'&&proof.slot===slot&&proof.role===role&&proof.retry===false);
  need(trace.transportClosed===true&&counts.auditRefused===false&&counts.activeGET===false);
  need(['DNS','TCP','REQUEST','RESPONSE_HEADERS','BODY_READ'].includes(String(trace.phase))&&(trace.httpStatus===null||trace.httpStatus===200));
  need((trace.reason==='REQUEST_TIMEOUT'&&trace.exceptionKind==='TIMEOUT')||(trace.reason==='TRANSPORT_UNPROVEN'&&trace.exceptionKind==='SOCKET_ERROR'));
  need(e.reason===trace.reason);
 }
 return failed.length>0;
}
// END_CLOSED_TRANSIENT_HELPER
// BEGIN_ARCHIVE_READ_WINDOW
function archiveReadWindowAllowed(spec:J,sourcePlan:J,readExpiry:number,sourceExpiry:number,now:number):boolean{
 if(spec.archiveReadOnly!==undefined&&typeof spec.archiveReadOnly!=='boolean')return false;
 if(spec.archiveReadOnly===true)return now>=sourceExpiry
  &&sourcePlan.id==='OLBG_131_NEW_TIPSTERS_SINGLE_CAPTURE_20261126'
  &&spec.sourceGrantHash==='92a6bcf6a68812e269518d37879ff44dd32ca895678325d245f58b5d3e001518'
  &&spec.planSHA256==='b67c8915facb77fa5ab01972c8cd51996029e2a8708af42ee16a7cb5a531aa1a'
  &&spec.manifestSHA256==='a32aa17d31828ba567f869d690e0e7610b3997af758f40cf2b0a10ea734d0d2e';
 return readExpiry<=sourceExpiry;
}
// END_ARCHIVE_READ_WINDOW
export type MultiRead={picks:J[];fixtures:J[];profiles:J[];claimId:string;closedSlots:string[];reserved:number;requestLimit:number;nativeFacts:number;partial:boolean;campaignActive:boolean;sourceExpiresAt:string};
export function readMultiCaptured(a:MultiCaptureApproval,now=Date.now()):MultiRead{
 const s=a.spec;need(sha(canon(s))===a.bindingSHA256);for(const r of s.consumerPins)pin(r.path,r.sha256,2000000);
 const d=s.directory,p=decode(pin(join(d,'plan.json'),s.planSHA256,65536)),m=decode(pin(join(d,'manifest.json'),s.manifestSHA256,16384)),sd=decode(pin(join(d,'authorization.json'),s.authorizationSHA256,32768));
 need(Object.keys(m).length===8&&m.mission_id===p.id&&m.source_hash===sha(canon(p))&&same(m.authorized_stages,['E1','E2'])&&m.maximum_stage==='E2');
 const uids=arr(p.profileIds,131).map(v=>{need(typeof v==='number'&&Number.isSafeInteger(v)&&v>0);return v});need(uids.length>=1&&uids.length<=131&&new Set(uids).size===uids.length&&(!uids.includes(203797)||s.includeExisting203797===true));
 const slots=arr(p.slots,12).map(v=>str(v,80));need(slots.length>=1&&slots.length<=12&&same(slots,[...new Set(slots)].sort())&&slots.every((v,i)=>!i||utc(v)-utc(slots[i-1])===7200000));
 const cap=slots.length*(uids.length+2),tb=obj(m.time_budget),cb=obj(m.compute_budget);const timings=[Number(tb.workerActiveMax),Number(tb.jobHardMax),Number(tb.externalMax)];const oldScope=same(timings,[540,550,560]),newScope=same(timings,[960,970,980]);need(oldScope||newScope);need(cb.sourceProfilesMax===uids.length&&cb.slotsMax===slots.length&&cb.nativeJobsMax===slots.length&&tb.HTTPMax===12&&[cb.rawPayloadWrites,cb.applicationAdmissions,cb.TaskMutations,cb.GitMutations,cb.SQLWrites,cb.R2Writes,cb.providerWrites].every(v=>v===0));const permissionMS=oldScope?700000:1200000,slotReserveMS=oldScope?900000:1500000;
 const routes={robots:'https://www.olbg.com/robots.txt',terms:'https://www.olbg.com/use',...Object.fromEntries(uids.map(uid=>['profile'+uid,'https://www.olbg.com/tipsters/tips/'+uid]))};need(same(p.routes,routes)&&same(m.external_effects,{https_get_max:cap,per_source_max:cap}));
 const fixtures=arr(p.fixtures,100).map(obj);need([55,64].includes(fixtures.length)&&p.calendarSha256===sha(canon(fixtures)));
 for(const v of arr(p.codePins,60)){const r=obj(v);pin(str(r.path),str(r.sha256,64),2000000)}
 for(const v of [p.cohort,p.core,p.bulkCore,p.sourceRuntime,p.python,...Object.values(obj(p.sourceRuntimeBinding)).filter(v=>v&&typeof v==='object')]){const r=obj(v);pin(str(r.path),str(r.sha256,64),2000000)}
 const c=obj(p.cohort),cohort=decode(pin(str(c.path),str(c.sha256,64),2000000)),profiles=arr(cohort.profiles,131).map(obj);need(same(profiles.map(v=>v.profileId),uids));
 for(const v of profiles){const q=obj(v.candidate),url=str(q.sourceUrl);need(q.platform==='OLBG'&&q.id==='catalogue:'+sha(url)&&[routes['profile'+v.profileId as keyof typeof routes],'https://www.olbg.com/tipsters/tips/history/'+v.profileId].includes(url)&&obj(q.origin).workbookSha256===cohort.workbookSHA256)}
 const rows=decisions(a),source=rows.find(r=>r.hash===s.sourceGrantHash);need(source&&source.record_type==='DECISION'&&source.decision==='PASS_AND_SCALE'&&source.responsible==='C0');const sc=ctx(source);
 need(sc.mission_id===p.id&&sc.stage==='E2'&&same(sc.keys,KEYS)&&sc.sourceAllowed===true&&sc.actualSourceAllowed===true&&sc.planSHA===sha(canon(p))&&sc.manifestSHA===sha(canon(m))&&same(sc.authorizedSlots,slots)&&sc.httpsGETMax===cap&&sc.nativeJobsMax===slots.length);
 need(sd.sourceDecisionLedgerHash===s.sourceGrantHash&&sd.missionId===p.id&&sd.authorizedAt===source.date&&sd.planSha256===sha(canon(p))&&sd.manifestSha256===sha(canon(m))&&same(sd.keys,KEYS));
 const grants=rows.filter(r=>r.record_type==='DECISION'&&ctx(r).mission_id===s.projectionMissionId&&ctx(r).purpose==='FINITE_MULTI_CAPTURE_APP_PROJECTION_V1'&&ctx(r).appProjectionAllowed===true);need(grants.length===1);const grant=grants[0],gc=ctx(grant),gm=obj(gc.manifest);need(grant.decision==='PASS_AND_SCALE'&&grant.responsible==='C0'&&gc.stage==='E2'&&same(gc.keys,KEYS)&&gc.sourceAllowed===false&&gc.bindingSHA256===a.bindingSHA256&&gc.sourceGrantHash===s.sourceGrantHash&&utc(grant.date)<=now);
 need(Object.keys(gm).length===8&&gm.mission_id===s.projectionMissionId&&gm.source_hash===a.bindingSHA256&&same(gm.authorized_stages,['E1','E2'])&&gm.maximum_stage==='E2'&&same(gm.external_effects,{Source_GET:0,Task:0,APP_data_writes:0,Git:0,SQL:0,R2:0})&&archiveReadWindowAllowed(s,p,utc(gm.expires_at),utc(m.expires_at),now));
 for(const r of rows.slice(rows.indexOf(grant)+1)){const x=ctx(r);need(!(r.record_type==='VETO'&&(x.global===true||x.severity==='CRITICAL'||[undefined,'GLOBAL','GOVERNANCE',p.id,s.projectionMissionId].includes(x.mission_id as string)))&&!(x.mission_id===s.projectionMissionId&&(x.authorityClosed===true||['FAIL_AND_STOP','FAIL_AND_REDESIGN','BLOCKED_EXTERNAL_ACTION'].includes(String(r.decision)))))}
 const end=Math.min(utc(m.expires_at),utc(sd.expiresAt),utc(sd.missionAuthorizedAt)+Number(tb.campaignWallSecondsMax)*1000);need(slots.every(v=>utc(v)>=utc(source.date)&&utc(v)+slotReserveMS<=end));
 let active:string|undefined;if(existsSync(join(d,'.execution.lock')))active=bytes(join(d,'.execution.lock'),1000).toString('utf8');const halt=existsSync(join(d,'campaign-halt.json'))?decode(bytes(join(d,'campaign-halt.json'),2000000)):null;
 const jb=existsSync(join(d,'events.jsonl'))?bytes(join(d,'events.jsonl'),16000000):Buffer.alloc(0),lastLF=jb.lastIndexOf(10)+1,events=chained(jb.subarray(0,lastLF),false,'0'.repeat(64),0);
 const all:J[]=[],closedSlots:string[]=[];let partial=Boolean(halt),nativeFacts=0;
 for(const slot of slots){const token=sha(slot),closurePath=join(d,'slot-closure-'+token+'.json');if(slot===active||utc(slot)>now||!existsSync(closurePath)||halt?.invalidClosureSlot===slot)continue;
  const closure=decode(bytes(closurePath,2000000));need(closure.schemaVersion==='OLBG_MULTI_FINAL_CONTROL_CLOSURE_V1'&&closure.slot===slot&&closure.sourceAllowedChecked===true&&closure.APP===0&&utc(closure.closedAt)<=now);
  const result=local(d,'slot-result-'+token+'.json',closure.resultSHA256,2000000),job=obj(result.job),launch=decode(bytes(join(d,'slot-job-'+token+'.json'),2048));need(result.schemaVersion==='OLBG_MULTI_SLOT_RESULT_V1'&&result.slot===slot&&result.candidateResult===true&&result.state===closure.state&&['succeeded','partial_capture_closed','halted'].includes(String(result.state))&&result.APP===0&&result.retry===false&&job.subtreeKillConfirmed===true&&job.activeSecondsMax===tb.workerActiveMax&&job.hardSeconds===tb.jobHardMax&&Number(result.RootElapsedSeconds)<Number(tb.externalMax));
  need(launch.slot===slot&&launch.missionId===p.id&&launch.campaignAuthorizationSHA256===s.authorizationSHA256&&launch.executionOnly===true&&utc(launch.startedAtUTC)>=utc(source.date)&&utc(launch.startedAtUTC)-utc(slot)>=0&&utc(launch.startedAtUTC)-utc(slot)<=180000&&utc(closure.closedAt)<=Math.min(end,utc(launch.startedAtUTC)+permissionMS));
  const pref=obj(result.journalPrefix);need(typeof pref.bytes==='number'&&Number.isSafeInteger(pref.bytes)&&pref.bytes<=jb.length&&sha(jb.subarray(0,pref.bytes))===pref.sha256);const er=chained(jb.subarray(0,pref.bytes),false,'0'.repeat(64),0);need(er.at(-1)?.hash===pref.head);const starts=er.filter(e=>e.kind==='PUBLIC_SLOT_STARTED'&&e.slot===slot);need(starts.length===1);const segment=er.slice(Number(starts[0].sequence)-1);need(segment.every(e=>utc(e.at)>=utc(launch.startedAtUTC)&&utc(e.at)<=utc(closure.closedAt)));
  const terminal=new Set(er.filter(e=>e.kind==='PUBLIC_PROFILE_STOPPED'&&String(e.slot)<slot).map(e=>e.profileId));const order=['robots','terms',...uids.filter(uid=>!terminal.has(uid)).map(uid=>'profile'+uid)],reserved=segment.filter(e=>e.kind==='REQUEST_RESERVED');need(reserved.length<=order.length&&reserved.every((e,i)=>e.sourceId==='SRC_014'&&e.url===routes[order[i] as keyof typeof routes]));
  const responses=segment.filter(e=>e.kind==='HTTP_RESPONSE');
  need(s.captureGrammar===undefined||s.captureGrammar==='OLBG_CLOSED_TRANSIENT_FAILURE_V1');
  if(s.captureGrammar==='OLBG_CLOSED_TRANSIENT_FAILURE_V1'){
   need(obj(p.sourceRuntime).sha256==='b9a7a054d5f0bd693650be43b8eda6e10128403c7a73ba338537b261fe19fae0'&&obj(obj(p.sourceRuntimeBinding).transport).sha256==='8e03df02fc0c747f1f6d100b1a00c1d2114a74ea4b5f1917136ae289aad01582'&&arr(p.codePins,60).some(v=>{const x=obj(v);return x.role==='multi:collect-multi.py'&&x.sha256==='fa53d03b9876e147d46a8bd76c31c23991724b3a4c00be52064d91ca1be288c9'}));
   const isolatedFailures=closedTransientResponses(segment,order,reserved,responses,slot,(name,digest,cap)=>local(d,name,digest,cap));partial=partial||isolatedFailures;
   if(result.state==='succeeded')need(job.exit===0&&job.timedOut===false&&reserved.length===order.length&&segment.some(e=>e.kind==='PUBLIC_SLOT_FINISHED'));
  }else{
   need(responses.length<=reserved.length&&responses.every((e,i)=>e.role===order[i]&&e.url===reserved[i].url&&utc(e.at)>=utc(reserved[i].at)));
   if(result.state==='succeeded')need(job.exit===0&&job.timedOut===false&&reserved.length===order.length&&responses.length===order.length&&segment.some(e=>e.kind==='PUBLIC_SLOT_FINISHED'));
  }
  const aggregateRecord=obj(result.aggregate),aggregate=local(d,aggregateRecord.file,aggregateRecord.sha256,2000000);need(aggregate.schemaVersion==='OLBG_MULTI_CLOSED_SLOT_V1'&&aggregate.slot===slot&&aggregate.missionId===p.id&&aggregate.claimId===p.claimId&&same(aggregate.journalPrefix,pref)&&aggregate.APP===0&&aggregate.sourceReady===false);
  const accepted=arr(aggregate.profiles,131).map(obj),qualified=segment.filter(e=>e.kind==='PUBLIC_PICKS_QUALIFIED');need(accepted.length===qualified.length&&new Set(accepted.map(e=>e.profileId)).size===accepted.length);
  for(const item of accepted){const uid=Number(item.profileId);need(uids.includes(uid));const event=qualified.find(e=>e.profileId===uid),response=responses.find(e=>e.role==='profile'+uid);need(event&&response&&response.status===200&&event.observationFile===item.observationFile&&event.observationSha256===item.observationSha256&&event.count===item.count&&event.responseSHA256===item.responseSHA256&&response.bodySHA256===item.responseSHA256);
   const facts=segment.find(e=>e.kind==='PUBLIC_FACTS_RETAINED'&&e.profileId===uid);need(facts&&facts.responseSHA256===item.responseSHA256&&Number(facts.sequence)>Number(response.sequence)&&Number(event.sequence)>Number(facts.sequence));const batchName=str(item.observationFile);need(/^[a-z0-9-]+\.json$/.test(batchName));const batchRaw=pin(join(d,batchName),str(item.observationSha256,64),131072);
   const picked=readAcceptedOLBGMultiNativeBatch(batchRaw,str(item.observationSha256,64),{...p,profileId:uid},str(item.responseSHA256,64),item.count);need(picked.every(q=>utc(q.observedAt)>=utc(response.at)&&utc(q.observedAt)<=utc(event.at)&&utc(q.observedAt)<end));all.push(...picked.filter(q=>utc(q.observedAt)<utc(gm.expires_at)));
  }
  nativeFacts+=segment.filter(e=>e.kind==='PUBLIC_FACTS_RETAINED').reduce((n,e)=>n+Number(e.count),0);closedSlots.push(slot);partial ||= result.state!=='succeeded';
 }
 const reserved=events.filter(e=>e.kind==='REQUEST_RESERVED').length;need(reserved<=cap&&all.length<=24000);const picks=mergeCampaignPicks([],all);
 return{picks,fixtures,profiles,claimId:s.claimId,closedSlots,reserved,requestLimit:cap,nativeFacts,partial,campaignActive:now<Math.min(end,utc(gm.expires_at))&&!halt&&((active!==undefined&&slots.includes(active))||slots.some(slot=>!closedSlots.includes(slot)&&utc(slot)+180000>=now)),sourceExpiresAt:new Date(end).toISOString()};
}
export function applyMultiPublic<T extends J>(base:T,a:MultiCaptureApproval|null,baseSHA:string):T{if(a===null)return base;try{need(a.spec.publicBaseSHA256===baseSHA);const c=readMultiCaptured(a),picks=mergeMultiCapturedPicks(arr(base.picks,2000).map(obj),c.picks),fixtures=arr(base.fixtures).map(obj);for(const f of c.fixtures){const old=fixtures.find(v=>v.id===f.id);if(old)need(['id','kickoff','label'].every(k=>same(old[k],f[k])));else fixtures.push(f)}return{...base,picks,fixtures,distinctPicks:picks.length,authorCount:new Set(picks.map(p=>p.authorId)).size,claimIds:[...new Set([...arr(base.claimIds??[base.claimId],500),c.claimId])],multiNativeCapture:{state:c.closedSlots.length?(c.partial?'partial_closed_capture':'accepted'):'awaiting_first_capture',claimId:c.claimId,sourceAccounts:c.profiles.length,closedSlots:c.closedSlots,records:c.picks.length,automaticAdmission:c.closedSlots.length>0,campaignActive:c.campaignActive,sourceGET:0}} as T}catch{return{...base,multiNativeCapture:{state:'waiting_or_unavailable',automaticAdmission:false,sourceGET:0}} as T}}

export function applyMultiCatalogue<T extends J>(base:T,a:MultiCaptureApproval|null):T{if(a===null)return base;try{const c=readMultiCaptured(a),candidates=arr(base.candidates,20000).map(v=>structuredClone(obj(v)));let out={...base,candidates} as J;
 for(const profile of c.profiles){const uid=Number(profile.profileId),captured=c.picks.filter(p=>p.authorId==='olbg:'+uid);if(!captured.length)continue;const document=obj(profile.candidate);let target=candidates.find(v=>v.sourceUrl===document.sourceUrl||v.sourceUrl==='https://www.olbg.com/tipsters/tips/'+uid||v.sourceUrl==='https://www.olbg.com/tipsters/tips/history/'+uid);
  if(!target){target={...structuredClone(document),collectionEnabled:null,operationalState:'unknown',documentarySupplement:{claimId:c.claimId,recordId:profile.recordId,source:'fixed_cohort_native_capture'}};candidates.push(target)}
  const q=target.qualification===undefined?{id:target.id,status:'documentary_only',documentaryIssues:[],picks:[],personallyProven:false}:obj(target.qualification),prior=q.picks===undefined?[]:arr(q.picks,2000).map(obj),merged=mergeMultiCapturedPicks(prior,captured);target.qualification={...q,picks:merged,personallyProven:merged.length>0,retainedClaimIds:[...new Set([...arr(q.retainedClaimIds??[],200),c.claimId])]};
 }
 const qualified=arr(out.candidates,20000).map(obj);out={...out,count:qualified.length,datedCount:qualified.filter(v=>v.declaredLastDate!==null).length,platformCount:new Set(qualified.map(v=>v.platform)).size,qualification:obj(base.qualification).status==='ok'?{...obj(base.qualification),qualifiedCount:qualified.filter(v=>v.qualification!==undefined&&obj(v.qualification).personallyProven===true).length}:base.qualification,multiNativeCapture:{state:c.closedSlots.length?(c.partial?'partial_closed_capture':'accepted'):'awaiting_first_capture',claimId:c.claimId,sourceAccounts:c.profiles.length,closedSlots:c.closedSlots,records:c.picks.length,automaticAdmission:c.closedSlots.length>0,campaignActive:c.campaignActive,sourceGET:0}};return out as T;
 }catch{return{...base,multiNativeCapture:{state:'waiting_or_unavailable',automaticAdmission:false,sourceGET:0}} as T}}
export function applyMultiQualification(base:QualificationSnapshot,a:MultiCaptureApproval|null):QualificationSnapshot{if(a===null)return base;const target=base.results.find(v=>v.id===(a.spec.qualificationRowId??'olbg-multi-fixed100-20261125'));if(!target)return base;try{const c=readMultiCaptured(a),latest=c.picks.map(p=>str(p.observedAt,80)).sort((x,y)=>utc(x)-utc(y)).at(-1);const row:QualificationResult={...target,label:'Collecte OLBG de '+c.profiles.length+' comptes',checkedAt:latest??target.checkedAt,dateKind:'observation',outcome:c.picks.length?'qualified':'no_eligible',summary:c.picks.length+' choix personnels distincts conservés pour '+new Set(c.picks.map(p=>p.authorId)).size+' comptes, dans '+c.closedSlots.length+' créneaux clôturés.',scope:c.reserved+' requêtes réservées sur '+c.requestLimit+' ; '+c.nativeFacts+' observations source retenues. '+(c.partial?'Capture partielle ; historique vérifié conservé. ':'')+'Fin autorisée : '+c.sourceExpiresAt+'.',nextStep:c.campaignActive?'Les prochains créneaux autorisés alimenteront automatiquement les fiches.':'Campagne terminée ou arrêtée ; aucune relance automatique.',metrics:{requests:c.reserved,nativeRecords:c.nativeFacts,footballRecords:null,candidates:c.picks.length,admitted:c.picks.length},claims:[c.claimId]};return{...base,capturedAt:new Date(Math.max(utc(base.capturedAt),utc(row.checkedAt))).toISOString(),results:base.results.map(v=>v===target?row:v)}}catch{return{...base,results:base.results.map(v=>v===target?{...v,outcome:'missing_evidence',summary:'La lecture des reçus de la campagne multi-comptes est indisponible. Historique déjà importé conservé.'}:v)}}}
