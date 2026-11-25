import {OLBG_CAMPAIGN_APPROVAL} from './olbg-campaign-companion';
import {restoreStableCatalogue,applyParentCampaignCatalogue} from './olbg-parent-adoption';
import {applyLocalOLBGCatalogue} from './olbg-retained-approved';
import {OLBG_RETAINED_APPROVAL} from './olbg-retained-approval';
import {applyReviewedOLBGPendingToCandidate} from './olbg-pending-candidate';
import {OLBG_REVIEWED_APPROVAL} from './olbg-reviewed-pending-approval';
import type {OLBGPendingObservation} from './olbg-pending-source';
import {applyNotBettingPlatformObservation,type PlatformPendingObservations} from './notbetting-pending-source';
import {applyPendingChannelObservation,type PendingChannelObservation} from './telegram-pending-channel';
import {createHash} from 'node:crypto';
import {openSync,closeSync,fstatSync,readSync} from 'node:fs';
import {resolve} from 'node:path';

export type FactObject=Record<string,unknown>;
export type Approval={registrySHA256:string;receiptSHA256:string;qualificationSHA256:string;workbookSHA256:string;csvSHA256:string;count:number;rosterCount:number;qualificationClaimId:string};
export const CATALOGUE_APPROVAL:Readonly<Approval>={
 registrySHA256:'74def990602b5d2bf1b2a030827967e8d155af664ed9016769cf81b4cdd236ce',
 receiptSHA256:'da1098fac5cf1b2606d10fef956f3b9e1e1d3962d72b8ad567cdad0f1f526414',
 qualificationSHA256:'c5775a1b108a7ad99637c11558c757713402662f1a49c05991630ca2edf433c9',
 workbookSHA256:'c6b15829bb11e40d3145bf25b6cce8a7066de6105897d2b48dc4a74ba9286622',
 csvSHA256:'4954d3333996243334cbd22b99e4ba2420bb63f99206ab85fa4dbb8713674fe4',
 count:317,rosterCount:137,qualificationClaimId:'ENG.SOURCE_OBSERVATORY.SRO.BRIDGE.R3.LOCAL.RECETTE.20261121'
};
const HASH=/^[a-f0-9]{64}$/;
const REGISTRY_FIELDS='id label platform sourceUrl evidenceUrl declaredLastDate origin historicalLabel status'.split(' ');
const QUAL_FIELDS='candidateCount documentaryClaimId documentaryIssues evidenceRefs expansionAuthorUrl expansionClaimId familyClaimId id label nativeAuthorId nativeFactCount observedAt omittedRecords ownerAction personalClaimId personalCollectionClaimId personallyProven platform profileAuthorUrl profileVisited reason requiredAccess responseUrl retainedClaimId retainedClaimIds retainedQualifiedAt rosterAuthorUrl rosterClaimId rosterObservedAt scope sourceId status technicalClaimId url'.split(' ');
const PREVIOUS='initialAssessment previousDocumentaryAssessment previousFamilyAssessment previousPersonalAssessment previousPersonalCollectionAssessment previousTechnicalAssessment previousExpansionAssessment'.split(' ');
const PICK_FIELDS='attributionBasis authorId authorLabel authorUrl calendarSha256 firstSeenAt fixtureId fixtureLabel id identityCertified kickoff lastSeenAt market marketInterpretationAllowed marketLabel observedAt odds parserSha256 performanceEvaluationAllowed postId publicationTimezone publishedAt publishedCivilDate publishedLocalText responseSha256 selection settlementAllowed sourceBetType sourceEventId sourceEventLocalText sourceEventTimezone sourceFields sourceId sourceMarketLabel sourceTipId sourceUrl versionCount versions'.split(' ');
const UNADMITTED_FIELDS='fixtureLabel marketLabel observedAt reason selection sourceEventText sourceTipId sourceUrl'.split(' ');
const ROOT_QUAL_FIELDS='status claimId assessedCount platformCount qualifiedCount observedAt technicalClaimId technicalClaimIds expansionClaimId personalClaimId compatibleClaimId familyClaimId rosterClaimId'.split(' ');
const RECEIPT_FIELDS='schemaVersion count platformCount datedCount registrySha256 csvSha256 sourceWorkbookSha256 claimId'.split(' ');
const INVENTORY_FIELDS='status schemaVersion total addressCount profileRows referenceRows page limit sheets platforms headers receipt'.split(' ');
const INVENTORY_ROW_FIELDS='recordId candidateId sheet row label platform kind sourceUrl documentaryLinkRejected historicalLevel historicalL1 status fields'.split(' ');

function check(v:unknown):asserts v{if(!v)throw Error('INDEPENDENT_CATALOGUE_UNAVAILABLE');}
function object(v:unknown):FactObject{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as FactObject;}
function string(v:unknown,max=2000):string{check(typeof v==='string'&&v.length>0&&v.length<=max&&!/[\u0000-\u001f]/.test(v));return v;}
function hash(v:Uint8Array|string):string{return createHash('sha256').update(v).digest('hex');}
function canonical(v:unknown):string{
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as FactObject)[k])).join(',')+'}';
 const text=JSON.stringify(v);check(text!==undefined);return text;
}
function decode(raw:Uint8Array,sha:string,cap:number):unknown{check(raw.length>0&&raw.length<=cap&&HASH.test(sha)&&hash(raw)===sha);return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}
function select(value:FactObject,keys:string[]):FactObject{
 const output:FactObject={};for(const key of keys)if(Object.hasOwn(value,key))output[key]=JSON.parse(JSON.stringify(value[key]));return output;
}
function url(value:unknown):string{
 const text=string(value);const parsed=new URL(text);
 check(['http:','https:'].includes(parsed.protocol)&&parsed.hostname&&!parsed.username&&!parsed.password);
 check(!['localhost','localhost.localdomain','127.0.0.1','::1','[::1]'].includes(parsed.hostname));return text;
}
function civil(value:unknown):void{
 if(value===null)return;const s=string(value,10);check(/^\d{4}-\d{2}-\d{2}$/.test(s));check(new Date(s+'T00:00:00Z').toISOString().slice(0,10)===s);
}
function origin(value:unknown,workbook:string):FactObject{
 const o=object(value);check(o.sheet==='Catalogue'&&Number.isSafeInteger(o.row)&&Number(o.row)>=5&&o.workbookSha256===workbook);
 return select(o,['sheet','row','workbookSha256']);
}
function qualification(value:unknown,depth=0):FactObject{
 check(depth<=8);const q=object(value),out=select(q,QUAL_FIELDS);
 if(q.picks!==undefined){check(Array.isArray(q.picks)&&q.picks.length<=2000);out.picks=q.picks.map(p=>select(object(p),PICK_FIELDS));}
 if(q.unadmittedFacts!==undefined){check(Array.isArray(q.unadmittedFacts)&&q.unadmittedFacts.length<=2000);out.unadmittedFacts=q.unadmittedFacts.map(p=>select(object(p),UNADMITTED_FIELDS));}
 for(const k of PREVIOUS)if(q[k]!==undefined)out[k]=qualification(q[k],depth+1);
 if(q.contestAssessments!==undefined){const c=object(q.contestAssessments);check(Object.keys(c).length<=100);out.contestAssessments=Object.fromEntries(Object.entries(c).map(([k,v])=>[k,qualification(v,depth+1)]));}
 return out;
}
export type Candidate=FactObject&{pendingOLBGObservation?:OLBGPendingObservation;pendingChannelObservation?:PendingChannelObservation;reviewedSourceObservation?:ReviewedSourceObservation;id:string;sourceUrl:string;origin:FactObject;collectionEnabled:null;operationalState:'unknown';qualification?:FactObject};
export type Catalogue=FactObject&{platformPendingObservations?:PlatformPendingObservations;receipt:FactObject;status:'ok';count:number;candidates:Candidate[];enabledCount:null;operationalState:'unknown';qualification:FactObject;rosterAssessments:FactObject[];historicalEvidence:FactObject};

function registryCandidate(value:unknown,workbook:string):Candidate{
 const r=object(value),source=url(r.sourceUrl),id=string(r.id);check(id==='catalogue:'+hash(source));
 check(r.status==='pending_qualification'&&r.collectionEnabled===false);string(r.label);string(r.platform);url(r.evidenceUrl);civil(r.declaredLastDate);
 return {...select(r,REGISTRY_FIELDS),id,sourceUrl:source,origin:origin(r.origin,workbook),collectionEnabled:null,operationalState:'unknown'};
}

export type CandidateSupplementApproval=Readonly<{relativePath:string;sha256:string;workbookSHA256:string;indexSHA256:string;sourceClaimId:string;candidateClaimId:string;count:number}>;
/** Public code carries no local documentary supplement authority. */
export const CANDIDATE_SUPPLEMENT_APPROVAL:CandidateSupplementApproval|null=null;
function exactKeys(value:FactObject,keys:string[]):void{check(Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k)));}
/** Add documentary identities only; native choices remain a separate admission. */
export function projectCandidateSupplement(base:Catalogue,raw:Uint8Array,a:CandidateSupplementApproval):Catalogue{
 check(Number.isSafeInteger(a.count)&&a.count>=1&&a.count<=50);
 for(const pin of [a.sha256,a.workbookSHA256,a.indexSHA256])check(HASH.test(pin));
 string(a.sourceClaimId);string(a.candidateClaimId);
 check(base.receipt.sourceWorkbookSha256===a.workbookSHA256&&base.count===base.candidates.length);
 const e=object(decode(raw,a.sha256,262144));
 exactKeys(e,['schemaVersion','workbookSHA256','indexSHA256','sourceClaimId','candidateClaimId','rows']);
 check(e.schemaVersion==='robin-candidate-supplement-v1'&&e.workbookSHA256===a.workbookSHA256&&e.indexSHA256===a.indexSHA256&&e.sourceClaimId===a.sourceClaimId&&e.candidateClaimId===a.candidateClaimId);
 check(Array.isArray(e.rows)&&e.rows.length===a.count);
 const ids=new Set(base.candidates.map(c=>c.id)),records=new Set<string>(),authors=new Set<number>();
 const added:Candidate[]=e.rows.map(value=>{
  const row=object(value);exactKeys(row,['candidate','recordId','mapping']);
  const r=object(row.candidate);exactKeys(r,[...REGISTRY_FIELDS,'collectionEnabled']);
  const c=registryCandidate(r,a.workbookSHA256),recordId=string(row.recordId);
  check(/^workbook:[a-f0-9]{64}$/.test(recordId)&&!records.has(recordId)&&!ids.has(c.id));
  exactKeys(c.origin,['sheet','row','workbookSha256']);
  const m=object(row.mapping);exactKeys(m,['documentaryURL','currentURL','profileId','nativeAuthorId','nativeMode','nativeResponseSHA256','nativeBatchSHA256']);
  check(c.platform==='OLBG'&&Number.isSafeInteger(m.profileId)&&Number(m.profileId)>0&&m.nativeAuthorId===m.profileId&&!authors.has(Number(m.profileId))&&m.nativeMode==='current');
  check([`https://www.olbg.com/tipsters/tips/history/${m.profileId}`,`https://www.olbg.com/tipsters/tips/${m.profileId}`].includes(c.sourceUrl)&&m.documentaryURL===c.sourceUrl&&m.currentURL===`https://www.olbg.com/tipsters/tips/${m.profileId}`);
  check(!base.candidates.some(prior=>prior.sourceUrl===m.currentURL||(prior.origin.sheet===c.origin.sheet&&prior.origin.row===c.origin.row&&prior.origin.workbookSha256===c.origin.workbookSha256)));
  check(HASH.test(string(m.nativeResponseSHA256))&&HASH.test(string(m.nativeBatchSHA256)));
  ids.add(c.id);records.add(recordId);authors.add(Number(m.profileId));
  return {...c,qualification:{id:c.id,status:'documentary_only',documentaryIssues:[],picks:[],personallyProven:false},
   documentarySupplement:{claimId:a.candidateClaimId,sourceClaimId:a.sourceClaimId,indexSHA256:a.indexSHA256,recordId,mapping:{...m}}};
 });
 const candidates=[...base.candidates,...added];
 return {...base,candidates,count:candidates.length,platformCount:new Set(candidates.map(c=>c.platform)).size,
  datedCount:candidates.filter(c=>c.declaredLastDate!==null).length,
  candidateSupplement:{claimId:a.candidateClaimId,sourceClaimId:a.sourceClaimId,indexSHA256:a.indexSHA256,workbookSHA256:a.workbookSHA256,baseRegistryCount:base.count,addedCandidates:added.length}};
}
export function applyApprovedCandidateSupplement(base:Catalogue,root:string,a:CandidateSupplementApproval|null=CANDIDATE_SUPPLEMENT_APPROVAL):Catalogue{
 if(a===null)return base;
 try{
  check(/^\.ci\/[a-zA-Z0-9/_-]+\.json$/.test(a.relativePath)&&!a.relativePath.split('/').includes('..'));
  return projectCandidateSupplement(base,readBounded(resolve(root,a.relativePath),262144),a);
 }catch{return base;}
}

/** Pure fact projection. Optional qualification failure never removes valid registry facts. */
export function projectCatalogue(registryRaw:Uint8Array,receiptRaw:Uint8Array,qualificationRaw:Uint8Array|undefined,a:Readonly<Approval>):Catalogue{
 check(Number.isSafeInteger(a.count)&&a.count>0&&a.count<=317&&Number.isSafeInteger(a.rosterCount)&&a.rosterCount>=0&&a.rosterCount<=137);
 const receipt=select(object(decode(receiptRaw,a.receiptSHA256,32768)),RECEIPT_FIELDS);
 check(receipt.schemaVersion==='robin-candidate-registry-v1'&&receipt.claimId==='DATA.SOURCE_OBSERVATORY.CANDIDATES317.20261119');
 check(receipt.registrySha256===a.registrySHA256&&receipt.sourceWorkbookSha256===a.workbookSHA256&&receipt.csvSha256===a.csvSHA256);
 const parsed=decode(registryRaw,a.registrySHA256,2_000_000);check(Array.isArray(parsed)&&parsed.length===a.count);
 const ids=new Set<string>();const candidates:Candidate[]=parsed.map(value=>{
  const candidate=registryCandidate(value,a.workbookSHA256);check(!ids.has(candidate.id));ids.add(candidate.id);return candidate;
 });
 check(receipt.count===candidates.length&&receipt.platformCount===new Set(candidates.map(r=>r.platform)).size&&receipt.datedCount===candidates.filter(r=>r.declaredLastDate!==null).length);
 const base:Catalogue={status:'ok',schemaVersion:'robin-candidate-registry-v1',count:a.count,platformCount:receipt.platformCount,datedCount:receipt.datedCount,receipt,
  candidates,enabledCount:null,operationalState:'unknown',qualification:{status:'unavailable'},rosterAssessments:[],
  historicalEvidence:{state:'unavailable',captureTimeCertified:false,currentStateVerified:false}};
 try{
  check(qualificationRaw!==undefined);const saved=object(decode(qualificationRaw,a.qualificationSHA256,2_000_000));
  check(saved.status==='ok'&&saved.schemaVersion===base.schemaVersion&&canonical(saved.receipt)===canonical(receipt));
  check(Array.isArray(saved.candidates)&&saved.candidates.length===a.count);
  const qualRoot=object(saved.qualification);check(qualRoot.status==='ok');const joined=new Map<string,FactObject>();
  for(const value of saved.candidates){
   const r=object(value),id=string(r.id);check(!joined.has(id));const target=candidates.find(c=>c.id===id);check(target);
   for(const k of REGISTRY_FIELDS)check(canonical(r[k])===canonical(target[k]));
   const q=object(r.qualification);check(q.id===undefined||q.id===id);
   check(Array.isArray(q.picks)&&Array.isArray(q.documentaryIssues)&&q.documentaryIssues.every(x=>typeof x==='string'));
   joined.set(id,qualification(q));
  }
  const root=select(qualRoot,ROOT_QUAL_FIELDS);check(Array.isArray(qualRoot.platforms)&&qualRoot.platforms.length<=100);root.platforms=qualRoot.platforms.map(p=>qualification(p));
  check(Array.isArray(saved.rosterAssessments)&&saved.rosterAssessments.length===a.rosterCount);const rosterIds=new Set<string>();
  const roster=saved.rosterAssessments.map(value=>{
   const r=object(value),recordId=string(r.recordId);check(!rosterIds.has(recordId));rosterIds.add(recordId);
   string(r.candidateId);string(r.sheet,80);check(Number.isSafeInteger(r.row)&&Number(r.row)>=1);url(r.sourceUrl);
   return {...select(r,['recordId','candidateId','sheet','row','sourceUrl']),qualification:qualification(r.qualification),collectionEnabled:null,operationalState:'unknown'};
  });
  return {...base,candidates:candidates.map(c=>{const q=joined.get(c.id);return q===undefined?c:{...c,qualification:q};}),qualification:root,rosterAssessments:roster,
   historicalEvidence:{state:'available',snapshotSHA256:a.qualificationSHA256,claimId:a.qualificationClaimId,sourceObservedAt:qualRoot.observedAt??null,
    captureTimeCertified:false,currentStateVerified:false}};
 }catch{return base;}
}

function readBounded(path:string,maximum:number):Uint8Array{
 let fd:number|undefined;
 try{fd=openSync(path,'r');const s=fstatSync(fd);check(s.isFile()&&s.size>0&&s.size<=maximum);const b=Buffer.alloc(maximum+1);let size=0;
  while(size<b.length){const n=readSync(fd,b,size,b.length-size,null);if(!n)break;size+=n;}check(size>0&&size<=maximum);return b.subarray(0,size);
 }finally{if(fd!==undefined)closeSync(fd);}
}
/** Fixed local reviewed inputs only; no Python, native state or source fallback. */
export function readIndependentCatalogue(root:string):Catalogue{
 const a=CATALOGUE_APPROVAL,dir=resolve(root,'.ci/catalogue-independent',a.registrySHA256);
 const registry=readBounded(resolve(dir,'registry.json'),2_000_000),receipt=readBounded(resolve(dir,'receipt.json'),32768);
 let optional:Uint8Array|undefined;try{optional=readBounded(resolve(root,'.ci/catalogue-independent',a.qualificationSHA256,'qualification.json'),2_000_000);}catch{/* Historical qualifications are optional. */}
 const base=projectCatalogue(registry,receipt,optional,a);
 let reviewed=base;try{reviewed=applyReviewedSourceObservations(base,readBounded(resolve(root,'../configs/source_observatory/reviewed-source-observations.json'),16384));}catch{/* Preserve base. */}
 let decorated=reviewed;
 try{decorated=applyPendingChannelObservation(reviewed,readBounded(resolve(root,'.ci/local-robin/telegram-channel-candidates.json'),65536));}catch{/* Preserve reviewed catalogue. */}
 let pending=decorated;
 try{pending=applyNotBettingPlatformObservation(decorated,readBounded(resolve(root,'.ci/local-robin/notbetting-pending-source-records.json'),32768),readBounded(resolve(root,'.ci/local-robin/notbetting-pending-source-receipt.json'),65536));}catch{/* Preserve reviewed catalogue. */}
 if(OLBG_REVIEWED_APPROVAL!==null){
  try{pending=applyReviewedOLBGPendingToCandidate(pending,readBounded(resolve(root,'.ci/local-robin/olbg-pending-profile-observations.json'),131072),readBounded(resolve(root,'.ci/local-robin/olbg-pending-profile-receipt.json'),65536),OLBG_REVIEWED_APPROVAL);}catch{/* Unapproved or unavailable OLBG snapshot never replaces existing facts. */}
 }
 const retained=applyLocalOLBGCatalogue(pending,root,OLBG_RETAINED_APPROVAL);
 const supplemented=applyApprovedCandidateSupplement(retained,root);
 const stable=restoreStableCatalogue(supplemented);
 return applyParentCampaignCatalogue(stable,root,OLBG_CAMPAIGN_APPROVAL);
}

export type InventoryRow=FactObject&{reviewedSourceObservation?:ReviewedSourceObservation;recordId:string;candidateId?:string;sheet:string;row:number;sourceUrl?:string|null;collectionEnabled:unknown;qualification?:FactObject;qualifiedRecordId?:string};
export type InventoryPage=FactObject&{records:InventoryRow[]};
/** Same exact joins as the historical decorator, without operational gates or a new readAt. */
export function decorateIndependentInventory(page:InventoryPage,registry:Catalogue|undefined):InventoryPage{
 const valid=registry?.qualification.status==='ok',byId=new Map(registry?.candidates.map(c=>[c.id,c])??[]);
 const output:InventoryPage={...select(page,INVENTORY_FIELDS),enabledCount:null,operationalState:'unknown',qualifiedRegistryState:valid?'historical':'unavailable',historicalEvidence:registry?.historicalEvidence??{state:'unavailable',captureTimeCertified:false,currentStateVerified:false},records:[]};
 delete output.readAt;delete output.personalAccessState;delete output.qualifiedCount;
 if(valid)output.qualifiedCount=registry?.qualification.qualifiedCount;
 output.records=page.records.map(r=>{
  const row:InventoryRow={...select(r,INVENTORY_ROW_FIELDS),recordId:r.recordId,sheet:r.sheet,row:r.row,collectionEnabled:null,operationalState:'unknown'};
  const observed=byId.get(r.candidateId??'');
  if(observed?.reviewedSourceObservation&&observed.sourceUrl===r.sourceUrl&&observed.origin.sheet===r.sheet&&observed.origin.row===r.row)row.reviewedSourceObservation=observed.reviewedSourceObservation;
  if(!valid)return row;
  const proposed=byId.get(r.candidateId??'');const prior=proposed&&proposed.origin.sheet===r.sheet&&proposed.origin.row===r.row&&proposed.sourceUrl===r.sourceUrl?proposed:undefined;
  const roster=registry?.rosterAssessments.find(x=>x.recordId===r.recordId&&x.candidateId===r.candidateId&&x.sheet===r.sheet&&x.row===r.row&&x.sourceUrl===r.sourceUrl);
  if(prior){row.qualifiedRecordId=prior.id;row.qualification=prior.qualification;}else if(roster)row.qualification=object(roster.qualification);
  const platforms=registry?.qualification.platforms;let platform=Array.isArray(platforms)?platforms.find(p=>object(p).platform===r.platform):undefined;
  if(platform&&r.platform==='Kicktipp'&&typeof r.sourceUrl==='string'){
   try{const u=new URL(r.sourceUrl),contests=object(platform).contestAssessments;if(['www.kicktipp.fr','www.kicktipp.de'].includes(u.hostname)&&contests)platform=object(contests)[u.pathname.split('/').filter(Boolean)[0]]??platform;}catch{/* Generic historical platform assessment remains. */}
  }
  if(platform)row.platformAssessment=platform;
  return row;
 });return output;
}

export type ReviewedSourceObservation={candidateId:string;sourceUrl:string;registrySHA256:string;workbookSHA256:string;sourceObservedAtUTC:string;sourceClosedAtUTC:string;messageCount:number;admittedForecasts:0;publishedFrom:string;publishedThrough:string;totalMessageCount:null;suffixHTMLUnexamined:true;claimIds:string[];adminHref:string};
const OBSERVATION_SHA='e4c97ea493c5ef304eae72e419f2e4ae9fd8b6709ddec5eb5d0ef6839e082853';
export function applyReviewedSourceObservations(base:Catalogue,raw:Uint8Array):Catalogue{
 try{
  const descriptor=object(decode(raw,OBSERVATION_SHA,16384));check(descriptor.schemaVersion==='robin-reviewed-source-observations-v1'&&Array.isArray(descriptor.observations)&&descriptor.observations.length===1);
  const value=object(descriptor.observations[0]);
  check(value.candidateId==='catalogue:fdf2c770bfb309bc55a9cbae8f6085742f6db7fa483bcf620679aa96414c4a0b'&&value.sourceUrl==='https://t.me/s/betsoccer');
  check(value.registrySHA256===object(base.receipt).registrySha256&&value.workbookSHA256===object(base.receipt).sourceWorkbookSha256);
  check(value.status==='STRUCTURED_MESSAGES_UNQUALIFIED'&&value.messageCount===10&&value.admittedForecasts===0&&value.sourceReady===false&&value.personalIdentityVerified===false&&value.recurringCollectionActive===false&&value.totalMessageCount===null&&value.suffixHTMLUnexamined===true);
  check(value.adminHref==='/expert/admin-collecte'&&Array.isArray(value.claimIds)&&value.claimIds.length===2);
  for(const k of ['sourceObservedAtUTC','sourceClosedAtUTC','publishedFrom','publishedThrough'])check(typeof value[k]==='string'&&Number.isFinite(Date.parse(value[k]as string)));
  const observation=JSON.parse(JSON.stringify(value))as ReviewedSourceObservation;
  const candidates=base.candidates.map(c=>c.id===value.candidateId&&c.sourceUrl===value.sourceUrl&&c.origin.sheet==='Catalogue'&&c.origin.row===308&&c.origin.workbookSha256===value.workbookSHA256?{...c,reviewedSourceObservation:observation}:c);
  return {...base,candidates};
 }catch{return base;}
}
