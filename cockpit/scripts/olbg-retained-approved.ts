import {createHash} from 'node:crypto';
import {openSync,closeSync,fstatSync,readSync} from 'node:fs';
import {resolve} from 'node:path';

type J=Record<string,unknown>;
export type OLBGRetainedApproval=Readonly<{
 envelopeSHA256:string;envelopeBytes:number;receiptSHA256:string;claimId:string;
 count:number;fixtureCount:number;inputCount:number;sourceObservedAtUTC:string;
 calendarObservedAtUTC:string;parserSHA256:string;builderSHA256:string;
 pendingSHA256:string;calendarSHA256:string;responseSHA256:string;
 sourceClaims:readonly string[];publicBaseSHA256:string;
}>;
export type OLBGCompanion={
 picks:J[];fixtures:J[];acceptedSourceTipIds:number[];claimId:string;claimIds:string[];
 sourceObservedAtUTC:string;qualifiedAt:string;publicBaseSHA256:string;sourceReady:false;
};
const TARGET='catalogue:d6120a2a545cd92a3d9b740d887d663e90af1023dfe8a64101e35cc8ea5415c1';
const URL='https://www.olbg.com/tipsters/tips/648433';
const HASH=/^[a-f0-9]{64}$/;
const PICK_KEYS='id sourceId authorId authorLabel authorUrl sourceUrl sourceTipId sourceEventId fixtureId fixtureLabel kickoff selection market marketLabel sourceMarketLabel sourceBetType sourceFields sourceEventLocalText sourceEventTimezone publishedAt publishedCivilDate observedAt firstSeenAt responseSha256 parserSha256 calendarSha256 performanceEvaluationAllowed settlementAllowed marketInterpretationAllowed versions versionCount'.split(' ');
const NATIVE_KEYS='tipid eventid eventname selection market winew event_datetime vc_sport_id result'.split(' ');
const FIXTURE_KEYS='id home away kickoff homeAliases awayAliases calendarSHA calendarClaim identityBasis nativeFixtureId actualWhistleProven label'.split(' ');
function check(v:unknown):asserts v{if(!v)throw Error('OLBG_RETAINED_COMPANION_REFUSED');}
function obj(v:unknown):J{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as J;}
function exact(v:unknown,keys:readonly string[]):J{const x=obj(v);check(Object.keys(x).length===keys.length&&keys.every(k=>Object.hasOwn(x,k)));return x;}
function str(v:unknown,max=240,empty=false):string{check(typeof v==='string'&&v.length<=(max)&&((empty&&v.length===0)||v.length>0)&&!/[\u0000-\u001f]/.test(v));return v;}
function integer(v:unknown):number{check(typeof v==='number'&&Number.isSafeInteger(v)&&v>0);return v;}
function list(v:unknown,max:number):unknown[]{check(Array.isArray(v)&&v.length<=max);return v;}
function canonical(v:unknown):string{
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as J)[k])).join(',')+'}';
 const text=JSON.stringify(v);check(text!==undefined);return text;
}
function hash(v:Uint8Array|string):string{return createHash('sha256').update(v).digest('hex');}
function equal(a:unknown,b:unknown):boolean{return canonical(a??null)===canonical(b??null);}
function clone<T>(v:T):T{return JSON.parse(JSON.stringify(v)) as T;}
function utc(v:unknown):number{const text=str(v,80);check(/(?:Z|\+00:00)$/.test(text));const n=Date.parse(text);check(Number.isFinite(n));return n;}
function decode(raw:Uint8Array,sha:string,cap:number):unknown{check(raw.length>0&&raw.length<=cap&&HASH.test(sha)&&hash(raw)===sha);return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}

export function readOLBGRetained(raw:Uint8Array,receiptRaw:Uint8Array,a:OLBGRetainedApproval):OLBGCompanion{
 check(a!==null&&a.count===3&&a.fixtureCount===3&&a.inputCount===17&&a.envelopeBytes===raw.length);
 for(const pin of [a.envelopeSHA256,a.receiptSHA256,a.parserSHA256,a.builderSHA256,a.pendingSHA256,a.calendarSHA256,a.responseSHA256,a.publicBaseSHA256])check(HASH.test(pin));
 const e=exact(decode(raw,a.envelopeSHA256,24576),['source','bundle','identities']);
 const r=obj(decode(receiptRaw,a.receiptSHA256,16384)),n=obj(r.normalization);
 check(r.status==='VERIFIED'&&equal(r.keys,['C0','C1','C4'])&&r.claimId===a.claimId&&str(a.claimId,200).startsWith('DATA.'));
 check(r.authorityClosed===true&&r.rawStdoutRetained===true&&r.sourceReady===false&&r.applicationAdmissions===0);
 check(r.normalizationEnvelopeSHA256===a.envelopeSHA256&&r.sourceObservedAtUTC===a.sourceObservedAtUTC&&r.calendarObservedAtUTC===a.calendarObservedAtUTC&&equal(r.sourceClaims,a.sourceClaims));
 check(n.status==='PRIVATE_OPAQUE_NORMALIZATION_READBACK_VERIFIED'&&n.envelopeSHA256===a.envelopeSHA256&&n.envelopeBytes===raw.length&&n.normalizedRows===3&&n.uniqueFixtureCount===3&&n.inputRecordOccurrences===17);
 check(n.fullBuilderCalls===18&&n.comparisonUpperBound===180&&n.sourceInputReads===2&&n.newOutputPayloadReadbacks===1&&n.totalDataBearingReads===3&&n.sourceGET===0);
 check(n.nativeEventTimezone===null&&n.nativeFixtureIDMissingIsVeto===false&&n.performanceEvaluationAllowed===false&&n.settlementAllowed===false&&n.marketInterpretationAllowed===false&&n.applicationAdmissions===0&&n.sourceReady===false);
 const s=exact(e.source,['profiles','fixtures','calendarSha256','sourceContextLineage']);
 const b=exact(e.bundle,['schemaVersion','claimId','recurrence','sourceResultSha256','lexicalParserSha256','acceptedSourceTipIds','fixtures','picks','qualifiedAt','sourceClaims']);
 check(b.schemaVersion==='robin-opaque-tipster-facts-v1'&&b.claimId===a.claimId&&b.recurrence===false&&b.lexicalParserSha256===a.parserSHA256);
 check(b.sourceResultSha256===hash(canonical(s)+'\n')&&s.calendarSha256===a.calendarSHA256&&equal(b.fixtures,s.fixtures)&&equal(b.sourceClaims,a.sourceClaims));
 check(utc(b.qualifiedAt)>=utc(a.sourceObservedAtUTC));
 const lineage=obj(s.sourceContextLineage);
 check(lineage.sourcePendingSHA256===a.pendingSHA256&&lineage.parserSHA256===a.parserSHA256&&lineage.pendingBuilderSHA256===a.builderSHA256);
 check(lineage.sourceClaim===a.sourceClaims[0]&&lineage.documentaryCalendarClaim===a.sourceClaims[1]&&lineage.sourceContextAdoptionClaim===a.sourceClaims[2]);
 check(equal(lineage.derivedFieldsFromAcceptedBuilderFilter,['mode=current','vc_sport_id=1','result=Open'])&&lineage.derivedFixtureIDProfile==='PROGRAMME_ROW_SHA_HOME_AWAY_UTC'&&lineage.fixtureLabelBasis==='DERIVED_HOME_SPACE_DASH_SPACE_AWAY');
 check(lineage.nativeFixtureIDsInvented===false&&lineage.personCivilIdentityRequired===false&&lineage.nativeDateTimezone===null&&lineage.actualWhistleProven===false);
 const profiles=list(s.profiles,1);check(profiles.length===1);const profile=exact(profiles[0],['facts','request']);
 const facts=exact(profile.facts,['authorId','authorLabel','mode','records']),request=exact(profile.request,['url','observedAt','responseSha256']);
 check(facts.authorId===648433&&facts.mode==='current');str(facts.authorLabel,80);
 check(request.url===URL&&request.observedAt===a.sourceObservedAtUTC&&request.responseSha256===a.responseSHA256);
 const identities=list(e.identities,1);check(identities.length===1);const identity=exact(identities[0],['candidateId','authorId','sourceUrl','sheet','row']);
 check(identity.candidateId===TARGET&&identity.authorId===648433&&identity.sourceUrl===URL&&identity.sheet==='Catalogue'&&identity.row===269);
 const fixtureRows=list(s.fixtures,9);check(fixtureRows.length===9);const fixtures=new Map<string,J>();
 for(const value of fixtureRows){
  const f=exact(value,FIXTURE_KEYS),id=str(f.id,80),home=str(f.home),away=str(f.away),kickoff=str(f.kickoff,80);utc(kickoff);
  check(!fixtures.has(id)&&id==='calendar:'+hash(canonical([a.calendarSHA256,home,away,kickoff])));
  check(equal(f.homeAliases,[home])&&equal(f.awayAliases,[away])&&f.label===home+' - '+away);
  check(f.calendarSHA===a.calendarSHA256&&f.calendarClaim===a.sourceClaims[1]&&f.identityBasis==='DERIVED_PROGRAMME_ROW'&&f.nativeFixtureId===null&&f.actualWhistleProven===false);fixtures.set(id,f);
 }
 const ids=list(b.acceptedSourceTipIds,3).map(integer);check(ids.length===3&&new Set(ids).size===3);
 const records=list(facts.records,3);check(records.length===3);const native=new Map<number,J>();
 for(const value of records){const row=exact(value,NATIVE_KEYS),id=integer(row.tipid);integer(row.eventid);check(ids.includes(id)&&!native.has(id)&&row.vc_sport_id===1&&row.result==='Open');str(row.eventname,240);str(row.selection,120);str(row.market,120,true);str(row.winew,80,true);str(row.event_datetime,40);native.set(id,row);}
 const values=list(b.picks,3);check(values.length===3);const seen=new Set<number>(),seenIDs=new Set<string>(),used=new Set<string>(),picks:J[]=[];
 for(const value of values){
  const p=exact(value,PICK_KEYS),id=integer(p.sourceTipId),nativeRow=native.get(id),fixture=fixtures.get(str(p.fixtureId,80));check(nativeRow&&fixture&&!seen.has(id)&&!seenIDs.has(str(p.id,200)));seen.add(id);seenIDs.add(str(p.id,200));used.add(str(p.fixtureId,80));
  check(p.id==='olbg-tip:'+id&&p.sourceId==='SRC_014'&&p.authorId==='olbg:648433'&&p.authorLabel===facts.authorLabel&&p.authorUrl===URL&&p.sourceUrl===URL&&p.sourceEventId===nativeRow.eventid);
  check(p.fixtureLabel===fixture.label&&p.kickoff===fixture.kickoff&&utc(p.observedAt)<utc(p.kickoff)&&p.observedAt===a.sourceObservedAtUTC&&p.firstSeenAt===a.sourceObservedAtUTC);
  check(p.selection===nativeRow.selection&&p.sourceMarketLabel===nativeRow.market&&p.sourceBetType===nativeRow.winew&&equal(p.sourceFields,nativeRow)&&p.sourceEventLocalText===nativeRow.event_datetime);
  check(p.sourceEventTimezone===null&&p.publishedAt===null&&p.publishedCivilDate===null&&p.market==='source_native_opaque');str(p.marketLabel,240);
  check(p.responseSha256===a.responseSHA256&&p.parserSha256===a.parserSHA256&&p.calendarSha256===a.calendarSHA256);
  check(p.performanceEvaluationAllowed===false&&p.settlementAllowed===false&&p.marketInterpretationAllowed===false&&p.versionCount===1&&equal(p.versions,[{selection:p.selection,observedAt:p.observedAt}]));
  picks.push(clone(p));
 }
 check(used.size===a.fixtureCount);
 return {picks,fixtures:[...used].map(id=>clone(fixtures.get(id)!)),acceptedSourceTipIds:ids,claimId:a.claimId,claimIds:[...new Set([...a.sourceClaims,a.claimId])],sourceObservedAtUTC:a.sourceObservedAtUTC,qualifiedAt:str(b.qualifiedAt,80),publicBaseSHA256:a.publicBaseSHA256,sourceReady:false};
}
function pickKey(p:J):string{return typeof p.sourceId==='string'&&typeof p.authorId==='string'&&typeof p.sourceTipId==='number'&&Number.isSafeInteger(p.sourceTipId)?canonical([p.sourceId,p.authorId,p.sourceTipId]):canonical(['legacy',str(p.id,200)]);}
function mergePicks(previous:unknown,additional:J[]):J[]{
 const prior=list(previous,2000).map(obj),keys=new Map<string,J>(),ids=new Map<string,J>();
 for(const p of prior){keys.set(pickKey(p),p);ids.set(str(p.id,200),p);}
 const out=[...prior];for(const p of additional){const old=keys.get(pickKey(p)),sameID=ids.get(str(p.id,200));check(!sameID||pickKey(sameID)===pickKey(p));
  if(old){for(const key of ['id','sourceId','authorId','sourceTipId','sourceEventId','fixtureId','kickoff','selection','market','sourceUrl','authorUrl','observedAt','firstSeenAt','sourceFields'])check(equal(old[key],p[key]));}
  else{const copied=clone(p);out.push(copied);keys.set(pickKey(p),copied);ids.set(str(p.id,200),copied);}
 }return out;
}
function unavailable<T extends J>(base:T,claimId:string):T{return {...base,olbgRetainedCompanion:{state:'unavailable',claimId}} as T;}
export function mergeOLBGCatalogue<T extends J>(base:T,c:OLBGCompanion|null):T{
 if(c===null)return base;const rows=list(base.candidates,317).map(obj),matches=rows.filter(row=>row.id===TARGET);if(matches.length!==1)return base;
 const target=matches[0],origin=obj(target.origin);if(target.platform!=='OLBG'||target.sourceUrl!==URL||origin.sheet!=='Catalogue'||origin.row!==269)return base;
 const q=target.qualification===undefined?{picks:[],documentaryIssues:[]}:obj(target.qualification),picks=mergePicks(q.picks??[],c.picks);
 const qualified:J={...q,picks,personallyProven:true,profileVisited:true,nativeAuthorId:'olbg:648433',observedAt:c.sourceObservedAtUTC,retainedClaimId:c.claimId,retainedClaimIds:[...new Set([...list(q.retainedClaimIds??[],200).map(v=>str(v,240)),...c.claimIds])],retainedQualifiedAt:c.qualifiedAt,label:'Choix personnels observés avant l’horaire officiel'};
 const admitted=new Set(c.acceptedSourceTipIds);if(Array.isArray(q.unadmittedFacts))qualified.unadmittedFacts=q.unadmittedFacts.filter(v=>{const id=obj(v).sourceTipId;return typeof id!=='number'||!Number.isSafeInteger(id)||!admitted.has(id);});
 let pending=target.pendingOLBGObservation;if(pending!==undefined){const p=obj(pending),records=list(p.records,20);const keys=new Set(c.acceptedSourceTipIds.map(id=>'olbg-pending-648433-'+id));pending={...p,records:records.filter(v=>!keys.has(str(obj(v).key,200)))};}
 const updated=rows.map(row=>row===target?{...row,qualification:qualified,...(pending===undefined?{}:{pendingOLBGObservation:pending})}:row);
 const root=base.qualification===undefined?undefined:obj(base.qualification);const qualification=root?.status==='ok'?{...root,qualifiedCount:updated.filter(row=>obj(row.qualification??{}).personallyProven===true).length}:base.qualification;
 return {...base,candidates:updated,...(qualification===undefined?{}:{qualification}),olbgRetainedCompanion:{state:'accepted_local_scheduled_prematch',claimId:c.claimId,rows:c.picks.length,sourceAccounts:1,usedFixtures:c.fixtures.length,sourceReady:false,globalCoverage:'UNKNOWN'}} as T;
}
export function mergeOLBGPublic<T extends J>(base:T,c:OLBGCompanion|null,baseApprovalSHA:string):T{
 if(c===null)return base;if(baseApprovalSHA!==c.publicBaseSHA256)return unavailable(base,c.claimId);
 const prior=list(base.picks,2000).map(obj),picks=mergePicks(prior,c.picks),oldFixtures=list(base.fixtures,2000).map(obj),byID=new Map(oldFixtures.map(f=>[str(f.id,200),f])),added:J[]=[];
 for(const f of c.fixtures){const old=byID.get(str(f.id,200));if(old){check(utc(old.kickoff)===utc(f.kickoff));for(const key of ['home','away','label'])if(old[key]!==undefined)check(equal(old[key],f[key]));}else{const value=clone(f);added.push(value);byID.set(str(f.id,200),value);}}
 const claims=list(base.claimIds??[base.claimId],500).map(v=>str(v,240));const oldGenerated=base.generatedAt===undefined?undefined:str(base.generatedAt,80),oldObserved=base.sourceObservedThrough===undefined?undefined:str(base.sourceObservedThrough,80);
 return {...base,picks,fixtures:[...oldFixtures,...added],distinctPicks:picks.length,authorCount:new Set(picks.map(p=>str(p.authorId,200))).size,claimIds:[...new Set([...claims,...c.claimIds])],generatedAt:oldGenerated&&utc(oldGenerated)>utc(c.qualifiedAt)?oldGenerated:c.qualifiedAt,sourceObservedThrough:oldObserved&&utc(oldObserved)>utc(c.sourceObservedAtUTC)?oldObserved:c.sourceObservedAtUTC,olbgRetainedCompanion:{state:'accepted_local_scheduled_prematch',claimId:c.claimId,addedChoices:picks.length-prior.length,addedFixtures:added.length,sourceReady:false,globalCoverage:'UNKNOWN'}} as T;
}
function bounded(path:string,cap:number):Uint8Array{const fd=openSync(path,'r');try{const size=fstatSync(fd).size;check(Number.isSafeInteger(size)&&size>0&&size<=cap);const raw=Buffer.alloc(size+1),count=readSync(fd,raw,0,raw.length,0);check(count===size);return raw.subarray(0,count);}finally{closeSync(fd);}}
function local(root:string,a:OLBGRetainedApproval):OLBGCompanion{return readOLBGRetained(bounded(resolve(root,'.ci/local-robin/olbg-normalized-uefa-envelope.json'),24576),bounded(resolve(root,'.ci/local-robin/olbg-normalized-uefa-receipt.json'),16384),a);}
export function applyLocalOLBGCatalogue<T extends J>(base:T,root:string,a:OLBGRetainedApproval|null):T{if(a===null)return base;try{return mergeOLBGCatalogue(base,local(root,a));}catch{return unavailable(base,a.claimId);}}
export function applyLocalOLBGPublic<T extends J>(base:T,root:string,a:OLBGRetainedApproval|null,baseApprovalSHA:string):T{if(a===null)return base;try{return mergeOLBGPublic(base,local(root,a),baseApprovalSHA);}catch{return unavailable(base,a.claimId);}}
