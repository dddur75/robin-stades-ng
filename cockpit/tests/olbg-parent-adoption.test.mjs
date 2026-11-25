// Synthetic cases for preserving an admitted choice while parent proof is unavailable.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {mkdtempSync,readFileSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
const data=source=>'data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(source)).toString('base64');
const readerURL=data(readFileSync(new URL('../scripts/olbg-campaign-companion.ts',import.meta.url),'utf8'));
const rootURL=data(readFileSync(new URL('../scripts/root-parent-proof.ts',import.meta.url),'utf8'));
const source=readFileSync(new URL('../scripts/olbg-parent-adoption.ts',import.meta.url),'utf8')
 .replaceAll("'./olbg-campaign-companion'",JSON.stringify(readerURL))
 .replaceAll("'./root-parent-proof'",JSON.stringify(rootURL));
const {restoreStablePublic,restoreStableCatalogue,applyParentCampaignPublic,applyParentCampaignCatalogue,approvedParentIO,preserveIdempotentProjection}=await import(data(source));
const hash=v=>createHash('sha256').update(v).digest('hex');
const bytes=v=>Buffer.from(JSON.stringify(v));
const claim='DATA.SOURCE_OBSERVATORY.OLBG.ONE.LOCAL.APP.ADMISSION.20261125';
function fixture(){
 const directory=mkdtempSync(join(tmpdir(),'olbg-adoption-synth-'));
 const baseSHA='a'.repeat(64),calendar='b'.repeat(64);
 const pick={id:'SYNTH_R5',sourceId:'SRC_014',authorId:'olbg:648433',sourceTipId:4,
  sourceEventId:44,fixtureId:'SYNTH_FIXTURE',kickoff:'2026-11-25T20:00:00+00:00',
  observedAt:'2026-11-25T01:00:00+00:00',firstSeenAt:'2026-11-25T01:00:00+00:00',
  sourceUrl:'https://www.olbg.com/tipsters/tips/648433',authorUrl:'https://www.olbg.com/tipsters/tips/648433',
  market:'source_native_opaque',calendarSha256:calendar,selection:'SYNTH ONLY',sourceMarketLabel:'SYNTH',
  sourceBetType:'SYNTH',sourceFields:{synthetic:true},responseSha256:'c'.repeat(64),
  versions:[{selection:'SYNTH ONLY',observedAt:'2026-11-25T01:00:00+00:00'}],versionCount:1,
  performanceEvaluationAllowed:false,settlementAllowed:false,marketInterpretationAllowed:false};
 const report={claimId:claim,newUniqueAdmitted:1,oldPublicChoicesPreserved:483,publicChoices:484,
  totalRecentOLBGChoices:4,documentaryPrematchRecertified:false,sourceReady:false,recurringCollectionActive:false};
 const reportRaw=bytes(report),reportPath=join(directory,'admission.json');writeFileSync(reportPath,reportRaw);
 const companion={picks:[pick],fixtures:[{id:pick.fixtureId,kickoff:pick.kickoff,label:'SYNTH FIXTURE'}],
  claimId:'SYNTH_CAMPAIGN',calendarSHA256:calendar,batchCount:1,publicBaseSHA256:baseSHA};
 const checkpoint={schemaVersion:'olbg-admitted-r5-checkpoint-v1',admissionClaimId:claim,
  admissionReportSHA256:hash(reportRaw),sourceBatchSHA256:'d'.repeat(64),companion};
 const payload=bytes(checkpoint),path=join(directory,'checkpoint.json');writeFileSync(path,payload);
 const approval={data:{path,sha256:hash(payload)},admissionReport:{path:reportPath,sha256:hash(reportRaw)},sourceBatchSHA256:'d'.repeat(64)};
 const old=[1,2,3].map(n=>({...structuredClone(pick),id:'SYNTH_PRIOR_'+n,sourceTipId:n}));
 return {directory,baseSHA,approval,base:{picks:old,fixtures:[],claimIds:['SYNTH_PRIOR']},checkpoint};
}
test('NULL defaults preserve the input object and do no approved IO',()=>{
 const f=fixture();assert.equal(restoreStablePublic(f.base,f.baseSHA),f.base);
 assert.equal(applyParentCampaignPublic(f.base,f.directory,f.baseSHA),f.base);
 assert.equal(approvedParentIO(),undefined);
});
test('checkpoint preserves three prior choices and replay is idempotent',()=>{
 const f=fixture(),once=restoreStablePublic(f.base,f.baseSHA,f.approval);
 assert.equal(once.picks.length,4);assert.deepEqual(once.picks.slice(0,3),f.base.picks);
 const twice=restoreStablePublic(once,f.baseSHA,f.approval);
 assert.deepEqual(twice.picks,once.picks);assert.deepEqual(twice.fixtures,once.fixtures);
 const target={id:'catalogue:d6120a2a545cd92a3d9b740d887d663e90af1023dfe8a64101e35cc8ea5415c1',platform:'OLBG',
  sourceUrl:'https://www.olbg.com/tipsters/tips/648433',origin:{sheet:'Catalogue',row:269},
  qualification:{picks:structuredClone(f.base.picks),personallyProven:true,retainedClaimIds:['SYNTH_PRIOR']},
  pendingOLBGObservation:{records:[{key:'olbg-pending-648433-4',synthetic:true},{key:'SYNTH_OTHER_PENDING',synthetic:true}]}};
 const other={id:'SYNTH_UNRELATED',qualification:{picks:[],personallyProven:false},preserved:{synthetic:true}};
 const catalogue={candidates:[target,other],qualification:{status:'ok',qualifiedCount:1}};
 const stable=restoreStableCatalogue(catalogue,f.approval),stableTarget=stable.candidates[0];
 assert.equal(stable.candidates.length,2);assert.deepEqual(stable.candidates[1],other);
 assert.deepEqual(stableTarget.qualification.picks.slice(0,3),target.qualification.picks);
 assert.equal(stableTarget.qualification.picks.length-target.qualification.picks.length,1);
 assert.deepEqual(stableTarget.pendingOLBGObservation.records,[target.pendingOLBGObservation.records[1]]);
 const replay=restoreStableCatalogue(stable,f.approval);assert.deepEqual(replay,stable);
 const next={planSHA256:'a'.repeat(64),manifestSHA256:'b'.repeat(64),claimId:'SYNTH_NEXT',publicBaseSHA256:f.baseSHA};
 const waited=applyParentCampaignCatalogue(stable,f.directory,next,null);
 assert.deepEqual(waited.candidates,stable.candidates);assert.deepEqual(waited.candidates[1],other);
 assert.equal(waited.localParentProof.state,'WAIT');assert.equal(waited.localParentProof.applicationNewChoices,0);
 assert.equal(waited.candidates[0].qualification.picks.length-stableTarget.qualification.picks.length,0);
});
test('missing or wrong-hash approved parent namespace waits with all four preserved',()=>{
 const f=fixture(),stable=restoreStablePublic(f.base,f.baseSHA,f.approval);
 const next={planSHA256:'a'.repeat(64),manifestSHA256:'b'.repeat(64),claimId:'SYNTH_NEXT',publicBaseSHA256:f.baseSHA};
 const validShape=proofFixture(f);writeFileSync(validShape.approval.namespace.path,bytes({tampered:true}));
 for(const proof of [null,{namespace:{path:join(f.directory,'missing.json'),sha256:'a'.repeat(64)},adoption:{path:join(f.directory,'missing-adoption.json'),sha256:'b'.repeat(64)}},validShape.approval]){
  const waited=applyParentCampaignPublic(stable,f.directory,f.baseSHA,next,proof);
  assert.deepEqual(waited.picks,stable.picks);assert.deepEqual(waited.fixtures,stable.fixtures);
  assert.equal(waited.localParentProof.state,'WAIT');assert.equal(waited.localParentProof.applicationNewChoices,0);
 }
});
function proofFixture(f,rootExit=0){
 const slot='2026-11-25T01:00:00+00:00',token=hash(slot),receiptSHA='e'.repeat(64);
 const namespace={schemaVersion:'olbg-root-parent-namespace-v1',campaignId:'SYNTH_CAMPAIGN',
  campaignDirectory:f.directory,controlsRoot:f.directory,returnsRoot:f.directory,slots:[slot],
  parentCallerSHA256:'f'.repeat(64),rootWrapperSHA256:'a'.repeat(64)};
 const nsRaw=bytes(namespace),nsPath=join(f.directory,'namespace.json');writeFileSync(nsPath,nsRaw);
 const receipt={schemaVersion:'olbg-parent-proof-local-adoption-v1',namespaceSHA256:hash(nsRaw),
  rootExit,rootReturnObserved:true,approvedBy:['C0','C1','C4'],sourceReady:false,applicationNewChoices:0};
 const rcRaw=bytes(receipt),rcPath=join(f.directory,'adoption.json');writeFileSync(rcPath,rcRaw);
 const returned=bytes({accepted:true,parentReceiptSHA256:receiptSHA});
 const primary=bytes({schemaVersion:'olbg-root-parent-process-v1',parentExit:0,timedOut:false,
  overflow:false,readError:false,veto:false,stderr:{bytes:0},
  stdout:{base64:returned.toString('base64'),bytes:returned.length,sha256:hash(returned)}});
 writeFileSync(join(f.directory,'root-parent-primary-'+token+'.json'),primary);
 writeFileSync(join(f.directory,'root-parent-return-'+token+'.json'),bytes({
  schemaVersion:'olbg-root-parent-return-v1',campaignId:namespace.campaignId,slot,parentExit:0,
  parentReceiptSHA256:receiptSHA,parentCallerSHA256:namespace.parentCallerSHA256,
  rootWrapperSHA256:namespace.rootWrapperSHA256,rootGuardBeforeProof:true,
  timedOut:false,overflow:false,readError:false,veto:false,sourceReady:false,rootPrimarySHA256:hash(primary)}));
 return {approval:{namespace:{path:nsPath,sha256:hash(nsRaw)},adoption:{path:rcPath,sha256:hash(rcRaw)}},slot,receiptSHA};
}
test('a nonzero Root return adoption is rejected before campaign data IO',()=>{
 const f=fixture(),p=proofFixture(f,1);assert.equal(approvedParentIO(p.approval),undefined);
});
test('real fixed-name Root IO confirms a synthetic return; only identical projections survive',()=>{
 const f=fixture(),p=proofFixture(f),io=approvedParentIO(p.approval);assert.ok(io);
 assert.equal(io.confirmExit('SYNTH_CAMPAIGN',p.slot,p.receiptSHA),true);
 assert.equal(io.confirmExit('SYNTH_CAMPAIGN',p.slot,'f'.repeat(64)),false);
 const stable=restoreStablePublic(f.base,f.baseSHA,f.approval);
 const result=preserveIdempotentProjection(stable,structuredClone(stable),'public');
 assert.deepEqual(result.picks,stable.picks);assert.equal(result.localParentProof.state,'VERIFIED_IDEMPOTENT');
 const changed=structuredClone(stable);changed.picks.push({...changed.picks[0],id:'SYNTH_NEW'});
 const refused=preserveIdempotentProjection(stable,changed,'public');
 assert.deepEqual(refused.picks,stable.picks);assert.equal(refused.localParentProof.state,'WAIT');
});
