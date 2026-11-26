// Proposed one-method SYNTH check; no source fixture, runtime activation or HTTP.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {mkdtempSync,readFileSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {stripTypeScriptTypes} from 'node:module';
const data=s=>'data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(s)).toString('base64');
const companion=data(readFileSync(new URL('../scripts/olbg-campaign-companion.ts',import.meta.url),'utf8'));
const proof=data(readFileSync(new URL('../scripts/root-parent-proof.ts',import.meta.url),'utf8'));
const source=readFileSync(new URL('../scripts/olbg-parent-adoption.ts',import.meta.url),'utf8')
 .replaceAll("'./olbg-campaign-companion'",JSON.stringify(companion)).replaceAll("'./root-parent-proof'",JSON.stringify(proof));
const {restoreStablePublic,restoreStableCatalogue}=await import(data(source));
const hash=v=>createHash('sha256').update(v).digest('hex');
test('V2 retains the approved V1 prefix and two distinct new rows; defaults and refusals stay closed',()=>{
 const dir=mkdtempSync(join(tmpdir(),'olbg-checkpoint-v2-synth-')),baseSHA='a'.repeat(64),calendar='b'.repeat(64),oldClaim='DATA.SOURCE_OBSERVATORY.OLBG.ONE.LOCAL.APP.ADMISSION.20261125';
 const put=(name,value)=>{const raw=Buffer.from(JSON.stringify(value)),path=join(dir,name);writeFileSync(path,raw);return {path,sha256:hash(raw)};};
 const pick=(id,author,tip,fixture)=>({id,sourceId:'SRC_014',authorId:'olbg:'+author,sourceTipId:tip,sourceEventId:tip,fixtureId:fixture,kickoff:'2026-11-27T20:00:00+00:00',observedAt:'2026-11-25T11:00:00+00:00',firstSeenAt:'2026-11-25T11:00:00+00:00',sourceUrl:'https://www.olbg.com/tipsters/tips/'+author,authorUrl:'https://www.olbg.com/tipsters/tips/'+author,market:'source_native_opaque',calendarSha256:calendar,selection:'SYNTH_ONLY',sourceMarketLabel:'SYNTH',sourceBetType:'SYNTH',sourceFields:{synthetic:true},responseSha256:'d'.repeat(64),versions:[{selection:'SYNTH_ONLY',observedAt:'2026-11-25T11:00:00+00:00'}],versionCount:1,performanceEvaluationAllowed:false,settlementAllowed:false,marketInterpretationAllowed:false});
 const old=pick('SYNTH_OLD',648433,1,'SYNTH_FIX_OLD'),fresh=[pick('SYNTH_NEW_1',642100,2,'SYNTH_FIX_1'),pick('SYNTH_NEW_2',642100,3,'SYNTH_FIX_2')];
 const fixtures=[old,...fresh].map(p=>({id:p.fixtureId,kickoff:p.kickoff,label:'SYNTH_FIXTURE'}));
 const oldReport=put('old-report.json',{claimId:oldClaim,newUniqueAdmitted:1,oldPublicChoicesPreserved:483,publicChoices:484,totalRecentOLBGChoices:4,documentaryPrematchRecertified:false,sourceReady:false,recurringCollectionActive:false});
 const prior={schemaVersion:'olbg-admitted-r5-checkpoint-v1',admissionClaimId:oldClaim,admissionReportSHA256:oldReport.sha256,sourceBatchSHA256:'e'.repeat(64),companion:{picks:[old],fixtures:[fixtures[0]],claimId:'SYNTH_OLD_BATCH',calendarSHA256:calendar,batchCount:1,publicBaseSHA256:baseSHA}};
 const priorRecord=put('prior.json',prior),base={picks:[],fixtures:[],claimIds:['SYNTH_BASE']};
 assert.equal(restoreStablePublic(base,baseSHA),base);
 const v1=restoreStablePublic(base,baseSHA,{data:priorRecord,admissionReport:oldReport,sourceBatchSHA256:prior.sourceBatchSHA256});assert.equal(v1.picks.length,1);
 const report={claimId:'DATA.SOURCE_OBSERVATORY.SYNTH.LOCAL.ADMISSION.20261125',nativeAuthorId:642100,newUniqueAdmitted:2,oldPublicChoicesPreserved:484,publicChoices:486,priorCheckpointSHA256:priorRecord.sha256,sourceBatchSHA256:'f'.repeat(64),documentaryPrematchRecertified:false,sourceReady:false,recurringCollectionActive:false};
 const saved={schemaVersion:'olbg-admitted-checkpoint-v2',admissionClaimId:report.claimId,admissionReportSHA256:'',sourceBatchSHA256:report.sourceBatchSHA256,priorCheckpoint:priorRecord,companion:{...prior.companion,picks:[old,...fresh],fixtures,claimId:'SYNTH_NEW_BATCH',batchCount:2}};
 let count=0;
 const approval=(s,r=report)=>{const admissionReport=put('report-'+(++count)+'.json',r);s.admissionReportSHA256=admissionReport.sha256;return {data:put('saved-'+count+'.json',s),admissionReport,sourceBatchSHA256:r.sourceBatchSHA256};};
 const a=approval(structuredClone(saved)),out=restoreStablePublic(base,baseSHA,a);
 assert.equal(out.picks.length,3);assert.equal(out.localAdmittedCheckpoint.restoredCampaignChoices,3);assert.equal(out.localAdmittedCheckpoint.applicationNewChoices,0);assert.ok(out.claimIds.includes(oldClaim)&&out.claimIds.includes(report.claimId));
 assert.deepEqual(restoreStablePublic(out,baseSHA,a),out);assert.deepEqual(prior.companion.picks,[old]);
 const candidate=(author,row)=>{const sourceUrl='https://www.olbg.com/tipsters/tips/history/'+author;return {id:'catalogue:'+hash(sourceUrl),platform:'OLBG',sourceUrl,origin:{sheet:'Catalogue',row,workbookSha256:'9'.repeat(64)},qualification:{picks:[],personallyProven:false}};};
 const catalogue={candidates:[candidate(648433,7),candidate(642100,8)],qualification:{status:'ok',qualifiedCount:0}};
 const restored=restoreStableCatalogue(catalogue,a);assert.equal(restored.candidates[0].qualification.picks.length,1);assert.equal(restored.candidates[1].qualification.picks.length,2);
 assert.ok(restored.candidates[0].qualification.retainedClaimIds.includes('SYNTH_OLD_BATCH'));assert.ok(restored.candidates[1].qualification.retainedClaimIds.includes('SYNTH_NEW_BATCH'));
 assert.deepEqual(restoreStableCatalogue(restored,a),restored);assert.deepEqual(catalogue.candidates.map(c=>c.qualification.picks.length),[0,0]);
 const next=pick('SYNTH_THIRD',522767,4,'SYNTH_FIX_3'),nextReport={...report,claimId:'DATA.SOURCE_OBSERVATORY.SYNTH.NEXT.ADMISSION.20261125',nativeAuthorId:522767,newUniqueAdmitted:1,oldPublicChoicesPreserved:486,publicChoices:487,sourceBatchSHA256:'1'.repeat(64),priorCheckpointSHA256:a.data.sha256};
 next.calendarSha256='2'.repeat(64);
 const approvedPrevious=JSON.parse(readFileSync(a.data.path,'utf8'));
 const nextSaved={...approvedPrevious,admissionClaimId:nextReport.claimId,sourceBatchSHA256:nextReport.sourceBatchSHA256,priorCheckpoint:a.data,companion:{...approvedPrevious.companion,claimId:'SYNTH_THIRD_BATCH',calendarSHA256:next.calendarSha256,batchCount:3,picks:[...approvedPrevious.companion.picks,next],fixtures:[...fixtures,{id:next.fixtureId,kickoff:next.kickoff,label:'SYNTH_FIXTURE'}]}};
 const nextApproval=approval(nextSaved,nextReport);assert.equal(restoreStablePublic(base,baseSHA,nextApproval).picks.length,4);
 for(const mutate of [s=>{s.companion.picks[1].settlementAllowed=true;},s=>{s.companion.picks[1].observedAt=s.companion.picks[1].kickoff;},s=>{s.companion.picks[0].id='CHANGED_PRIOR';},s=>{s.companion.picks[2].id=s.companion.picks[1].id;},s=>{s.priorCheckpoint.sha256='0'.repeat(64);}]){const bad=structuredClone(saved);mutate(bad);assert.throws(()=>restoreStablePublic(base,baseSHA,approval(bad)));}
 assert.throws(()=>restoreStablePublic(base,baseSHA,approval(structuredClone(saved),{...report,publicChoices:487})));
});
