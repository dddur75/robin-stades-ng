import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const source=readFileSync(new URL('../scripts/catalogue-independent.ts',import.meta.url),'utf8');
const pendingSource=readFileSync(new URL('../scripts/telegram-pending-channel.ts',import.meta.url),'utf8');
const pendingURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(pendingSource)).toString('base64');
const notBettingSource=readFileSync(new URL('../scripts/notbetting-pending-source.ts',import.meta.url),'utf8');
const notBettingURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(notBettingSource)).toString('base64');
const olbgPendingSource=readFileSync(new URL('../scripts/olbg-pending-source.ts',import.meta.url),'utf8');
const olbgPendingURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(olbgPendingSource)).toString('base64');
const olbgApprovalSource=readFileSync(new URL('../scripts/olbg-reviewed-pending-approval.ts',import.meta.url),'utf8');
const olbgApprovalURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(olbgApprovalSource).replace("from './olbg-pending-source'","from '"+olbgPendingURL+"'")).toString('base64');
const olbgCandidateSource=readFileSync(new URL('../scripts/olbg-pending-candidate.ts',import.meta.url),'utf8');
const olbgCandidateURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(olbgCandidateSource)
  .replace("from './olbg-pending-source'","from '"+olbgPendingURL+"'")
  .replace("from './olbg-reviewed-pending-approval'","from '"+olbgApprovalURL+"'")).toString('base64');
const retainedSource=readFileSync(new URL('../scripts/olbg-retained-approved.ts',import.meta.url),'utf8');
const retainedURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(retainedSource)).toString('base64');
const retainedApprovalSource=readFileSync(new URL('../scripts/olbg-retained-approval.ts',import.meta.url),'utf8');
const retainedApprovalURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(retainedApprovalSource)).toString('base64');
const campaignSource=readFileSync(new URL('../scripts/olbg-campaign-companion.ts',import.meta.url),'utf8');
const campaignURL='data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(campaignSource)).toString('base64');
const resolvedSource=stripTypeScriptTypes(source)
  .replace("from './olbg-campaign-companion'","from '"+campaignURL+"'")
  .replace("from './olbg-retained-approved'","from '"+retainedURL+"'")
  .replace("from './olbg-retained-approval'","from '"+retainedApprovalURL+"'")
  .replace("from './telegram-pending-channel'","from '"+pendingURL+"'")
  .replace("from './notbetting-pending-source'","from '"+notBettingURL+"'")
  .replace("from './olbg-pending-source'","from '"+olbgPendingURL+"'")
  .replace("from './olbg-pending-candidate'","from '"+olbgCandidateURL+"'")
  .replace("from './olbg-reviewed-pending-approval'","from '"+olbgApprovalURL+"'");
const campaignModule=await import(campaignURL);
assert.equal(typeof campaignModule.applyOLBGCampaignCatalogue,'function');
assert.ok(source.includes("from './olbg-campaign-companion'"));
assert.equal(resolvedSource.includes("from './olbg-campaign-companion'"),false);
const m=await import('data:text/javascript;base64,'+Buffer.from(resolvedSource).toString('base64'));
assert.equal(typeof m.applyReviewedSourceObservations,'function');
const bytes=readFileSync(new URL('../../configs/source_observatory/reviewed-source-observations.json',import.meta.url));
const desc=JSON.parse(bytes).observations[0];
const target={id:desc.candidateId,sourceUrl:desc.sourceUrl,origin:{sheet:'Catalogue',row:308,workbookSha256:desc.workbookSHA256},collectionEnabled:null,operationalState:'unknown',qualification:{reason:'Historical TLS',picks:[]}};
const other={...target,id:'foreign',sourceUrl:'https://t.me/s/bextra_pronostics_foot'};
const third={...other,id:'dexter',sourceUrl:'https://notbetting.com/en/tipsters-league/Dexter'};
const base={status:'ok',count:3,candidates:[target,other,third],receipt:{registrySha256:desc.registrySHA256,sourceWorkbookSha256:desc.workbookSHA256},qualification:{status:'ok',qualifiedCount:0},rosterAssessments:[],enabledCount:null,operationalState:'unknown'};
const before=JSON.stringify(base),out=m.applyReviewedSourceObservations(base,bytes);
assert.equal(out.candidates[0].reviewedSourceObservation.messageCount,10);assert.deepEqual(out.candidates[1],other);assert.equal(JSON.stringify(base),before);
assert.equal(out.candidates[0].collectionEnabled,null);assert.equal(out.qualification.qualifiedCount,0);assert.deepEqual(out.candidates[0].qualification,target.qualification);
assert.deepEqual(m.applyReviewedSourceObservations(base,Buffer.from('{}')),base);
for(const changed of [{...target,sourceUrl:'https://foreign.example/'},{...target,id:'wrong'},{...target,origin:{...target.origin,workbookSha256:'0'.repeat(64)}}])assert.deepEqual(m.applyReviewedSourceObservations({...base,candidates:[changed,other]},bytes).candidates,[changed,other]);
const page={status:'ok',records:[{recordId:'catalogue-row',candidateId:target.id,sheet:'Catalogue',row:308,sourceUrl:target.sourceUrl},{recordId:'foreign',candidateId:target.id,sheet:'Catalogue',row:308,sourceUrl:other.sourceUrl}]};
const decorated=m.decorateIndependentInventory(page,out);assert.equal(decorated.records[0].reviewedSourceObservation.messageCount,10);assert.equal(decorated.records[1].reviewedSourceObservation,undefined);
assert.deepEqual(out.candidates[2],third);
for(const receipt of [{...base.receipt,registrySha256:'0'.repeat(64)},{...base.receipt,sourceWorkbookSha256:'0'.repeat(64)}])assert.deepEqual(m.applyReviewedSourceObservations({...base,receipt},bytes),{...base,receipt});
console.log('16 synthetic assertions PASS; three candidates');
