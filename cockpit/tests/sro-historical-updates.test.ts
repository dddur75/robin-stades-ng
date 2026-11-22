import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
import {projectSROHistoricalUpdates,applyReviewedSROHistoricalUpdates,immutablePicksSHA256,type Approval} from '../scripts/sro-historical-updates';
const canonical=(v:unknown):string=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as Record<string,unknown>)[k])).join(',')+'}':JSON.stringify(v);
const sha=(v:unknown)=>createHash('sha256').update(canonical(v)).digest('hex');
const observed='2026-11-21T18:18:42.376705+00:00';
function pick(n:number){const authorUrl='https://forum.stade-rennais-online.com/profile.php?id='+n,authorId=sha(['SRC_039',authorUrl]);return {id:sha(['SRC_039',authorId,'fixture-a','correct_score']),sourceId:'SRC_039',authorId,authorUrl,authorLabel:'Synthetic '+n,fixtureId:'fixture-a',kickoff:'2026-11-21T19:45:00Z',market:'correct_score',selection:'1-0',sourceUrl:'https://forum.stade-rennais-online.com/viewtopic.php?pid='+n+'#p'+n,postId:'p'+n,observedAt:'2026-11-19T10:00:00Z',firstSeenAt:'2026-11-19T09:00:00Z',lastSeenAt:'2026-11-21T03:00:11Z',responseSha256:'a'.repeat(64),versions:[{selection:'1-0',observedAt:'2026-11-19T10:00:00Z'}],versionCount:1,identityCertified:false,publicationTimezone:null,publishedCivilDate:'2026-11-19'};}
const base={status:'ok',distinctPicks:3,authorCount:3,picks:[pick(1),pick(2),{...pick(3),id:'other-source-id',sourceId:'SRC_OTHER',fixtureId:'fixture-b'}],fixtures:[{id:'fixture-a',kickoff:'2026-11-21T19:45:00Z'},{id:'fixture-b',kickoff:'2026-11-22T19:45:00Z'}],sourceObservedThrough:'2026-11-22T12:15:12.294187+00:00',generatedAt:'2026-11-22T12:28:05.852Z',retainedSnapshot:{operationalState:'unknown'},forumCompanion:{state:'available',updates:{preserved:{lastSeenAt:'2026-11-22T09:00:00Z',claimId:'OTHER.CLAIM'}}},claimIds:['BASE.CLAIM']};
const envelope={schemaVersion:'sro-approved-historical-updates-v1',parentClaimId:'DATA.SOURCE_OBSERVATORY.SRO.CANARY.R2.REOBSERVED.20261121',acceptedClaimId:'DATA.SOURCE_OBSERVATORY.SRO.HISTORICAL.CANARY.R2.APP.ADMISSION.20261122',sourceMissionId:'SRO_SUCCESSOR_MANUAL_CANARY_E1_R2_20261121',candidateSHA256:'b'.repeat(64),receiptSHA256:'c'.repeat(64),sourceResponseSHA256:'d'.repeat(64),sourceObservedAt:observed,immutablePicksSHA256:immutablePicksSHA256(base.picks),updates:base.picks.slice(0,2).map(p=>({id:p.id,lastSeenAt:observed}))};
function approval(value=envelope):Approval{const wrapperSHA256=createHash('sha256').update(canonical(value)+'\n').digest('hex');return {relativePath:'.ci/sro-historical-approved/'+wrapperSHA256+'/updates.json',wrapperSHA256,parentClaimId:value.parentClaimId,claimId:value.acceptedClaimId,decisionSHA256:'0'.repeat(64),candidateSHA256:value.candidateSHA256,receiptSHA256:value.receiptSHA256,sourceResponseSHA256:value.sourceResponseSHA256,sourceObservedAt:value.sourceObservedAt,immutablePicksSHA256:value.immutablePicksSHA256,allowedNativeChoiceIds:value.updates.map(x=>x.id).sort(),maximumUpdates:2,maximumBytes:65536,choices:3,pseudonyms:3,fixtures:2};}
const a=approval(),out=projectSROHistoricalUpdates(base,envelope,a);
assert.notEqual(out,base);assert.equal(out.picks.length,3);assert.equal(out.distinctPicks,3);assert.equal(out.authorCount,3);
for(let n=0;n<3;n++){const {lastSeenAt:before,...immutableBefore}=base.picks[n],{lastSeenAt:after,...immutableAfter}=out.picks[n];assert.deepEqual(immutableAfter,immutableBefore);assert.equal(after,n<2?observed:before);}
assert.deepEqual(out.forumCompanion,base.forumCompanion);assert.equal(out.sourceObservedThrough,base.sourceObservedThrough);assert.equal(out.generatedAt,base.generatedAt);assert.deepEqual(out.retainedSnapshot,base.retainedSnapshot);
assert.equal(out.sroNextCompanion.updates[base.picks[0].id].claimId,a.claimId);assert.equal(out.sroNextCompanion.sourceResponseSHA256,envelope.sourceResponseSHA256);assert.equal(out.picks[0].responseSha256,'a'.repeat(64));
assert.deepEqual(projectSROHistoricalUpdates(out,envelope,a),out);
for(const value of [undefined,{...envelope,unexpected:true},{...envelope,updates:[]},{...envelope,updates:[envelope.updates[0],envelope.updates[0]]}])assert.equal(projectSROHistoricalUpdates(base,value,a),base);
const duplicate={...envelope,updates:[envelope.updates[0],envelope.updates[0]]};assert.equal(projectSROHistoricalUpdates(base,duplicate,approval(duplicate)),base);
const unknown={...envelope,updates:[envelope.updates[0],{id:'f'.repeat(64),lastSeenAt:observed}]};assert.equal(projectSROHistoricalUpdates(base,unknown,approval(unknown)),base);
const changed=structuredClone(base);changed.picks[0].selection='9-9';assert.equal(projectSROHistoricalUpdates(changed,envelope,a),changed);
const later=structuredClone(base);later.picks[0].lastSeenAt='2026-11-21T19:00:00Z';assert.equal(projectSROHistoricalUpdates(later,envelope,a),later);
const laterCompanion={...base,sroNextCompanion:{updates:{[base.picks[0].id]:{lastSeenAt:'2026-11-21T19:00:00Z',claimId:'PRIOR.CLAIM'}}}};assert.equal(projectSROHistoricalUpdates(laterCompanion,envelope,a),laterCompanion);
for(const sourceObservedAt of ['2026-11-22T00:00:00Z','invalid','2026-11-21T18:18:42']){
 const prior={...base,sroNextCompanion:{updates:{},sourceObservedAt}};assert.equal(projectSROHistoricalUpdates(prior,envelope,a),prior);
}
const olderCompanion={...base,sroNextCompanion:{updates:{},sourceObservedAt:'2026-11-21T18:00:00Z'}};assert.equal(projectSROHistoricalUpdates(olderCompanion,envelope,a).sroNextCompanion.sourceObservedAt,observed);
const late=structuredClone(base);late.picks[0].kickoff='2026-11-21T18:00:00Z';late.fixtures[0].kickoff=late.picks[0].kickoff;const lateEnvelope={...envelope,immutablePicksSHA256:immutablePicksSHA256(late.picks)};assert.equal(projectSROHistoricalUpdates(late,lateEnvelope,approval(lateEnvelope)),late);
const naive={...envelope,sourceObservedAt:'2026-11-21T18:18:42',updates:envelope.updates.map(x=>({...x,lastSeenAt:'2026-11-21T18:18:42'}))};assert.equal(projectSROHistoricalUpdates(base,naive,approval(naive)),base);
assert.equal(applyReviewedSROHistoricalUpdates(base,fileURLToPath(new URL('./missing-private-root',import.meta.url)),a),base); // zero decision is preview only
assert.equal(applyReviewedSROHistoricalUpdates(base,fileURLToPath(new URL('./missing-private-root',import.meta.url)),{...a,decisionSHA256:'e'.repeat(64)}),base);
assert.equal(Object.hasOwn(out,'sroCampaign'),false);assert.equal(Object.hasOwn(out,'sroNextCampaign'),false);
// Exercise actual bounded FS entrypoint using RAM file primitives only.
const original={openSync:fs.openSync,closeSync:fs.closeSync,fstatSync:fs.fstatSync,readSync:fs.readSync};
let bytes=Buffer.from(canonical(envelope)+'\n'),position=0,overflow=false,closeFails=false,readCalls=0;
fs.openSync=()=>{position=0;return 70001;};fs.closeSync=()=>{if(closeFails){closeFails=false;throw Error('SYNTHETIC_CLOSE_FAILURE');}};
fs.fstatSync=()=>({isFile:()=>true,size:overflow?65537:bytes.length});
fs.readSync=(fd,b,offset,len,p)=>{assert.equal(p,null);readCalls++;const count=Math.min(len,bytes.length-position);bytes.copy(b,offset,position,position+count);position+=count;return count;};syncBuiltinESMExports();
const final={...a,decisionSHA256:'e'.repeat(64)};
assert.deepEqual(applyReviewedSROHistoricalUpdates(base,'synthetic-root',final),projectSROHistoricalUpdates(base,envelope,final));
overflow=true;const readsBefore=readCalls;assert.equal(applyReviewedSROHistoricalUpdates(base,'synthetic-root',final),base);assert.equal(readCalls,readsBefore);overflow=false;
bytes=Buffer.from('corrupt');assert.equal(applyReviewedSROHistoricalUpdates(base,'synthetic-root',final),base);
bytes=Buffer.from([255]);const invalidUTF8={...final,wrapperSHA256:createHash('sha256').update(bytes).digest('hex')};invalidUTF8.relativePath='.ci/sro-historical-approved/'+invalidUTF8.wrapperSHA256+'/updates.json';assert.equal(applyReviewedSROHistoricalUpdates(base,'synthetic-root',invalidUTF8),base);
bytes=Buffer.from(canonical(envelope)+'\n');closeFails=true;assert.equal(applyReviewedSROHistoricalUpdates(base,'synthetic-root',final),base);
Object.assign(fs,original);syncBuiltinESMExports();
console.log(JSON.stringify({status:'PASS_SYNTHETIC_ONLY',picks:3,historicalUpdates:2,immutableFieldsPreserved:true,sourceRowHashesPreserved:true,idempotent:true,atomicReject:true,noRegression:true,noNewGlobalSourceFreshness:true,HTTP:0,source:0,Task:0,writes:0}));
