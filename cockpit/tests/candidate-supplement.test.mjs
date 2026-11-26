// Proposed one-method SYNTH check. C0 runs it once after independent review.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const source=stripTypeScriptTypes(readFileSync(new URL('../scripts/catalogue-independent.ts',import.meta.url),'utf8'))
 .replace(/^import .* from '\.\/[^']+';\r?\n/gm,'');
const {projectCandidateSupplement,applyApprovedCandidateSupplement}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const hash=v=>createHash('sha256').update(v).digest('hex');
test('documentary overlay preserves baseline and rejects ambiguous identities without default IO',()=>{
 const workbook='a'.repeat(64),url='https://www.olbg.com/tipsters/tips/history/642100';
 const base={status:'ok',count:1,platformCount:1,datedCount:0,candidates:[{id:'SYNTH_OLD',platform:'OLBG',sourceUrl:'https://www.olbg.com/tipsters/tips/history/1',declaredLastDate:null,origin:{sheet:'Catalogue',row:7,workbookSha256:workbook}}],receipt:{count:1,sourceWorkbookSha256:workbook},qualification:{status:'ok'}};
 const payload={schemaVersion:'robin-candidate-supplement-v1',workbookSHA256:workbook,indexSHA256:'b'.repeat(64),sourceClaimId:'SYNTH_SOURCE',candidateClaimId:'SYNTH_DOCUMENT',rows:[{
  candidate:{id:'catalogue:'+hash(url),label:'SYNTHETIC',platform:'OLBG',sourceUrl:url,evidenceUrl:url,declaredLastDate:null,origin:{sheet:'Catalogue',row:8,workbookSha256:workbook},historicalLabel:null,status:'pending_qualification',collectionEnabled:false},
  recordId:'workbook:'+'c'.repeat(64),mapping:{documentaryURL:url,currentURL:'https://www.olbg.com/tipsters/tips/642100',profileId:642100,nativeAuthorId:642100,nativeMode:'current',nativeResponseSHA256:'d'.repeat(64),nativeBatchSHA256:'e'.repeat(64)}}]};
 const apply=value=>{const raw=Buffer.from(JSON.stringify(value));return projectCandidateSupplement(base,raw,{relativePath:'.ci/synth/input.json',sha256:hash(raw),workbookSHA256:workbook,indexSHA256:payload.indexSHA256,sourceClaimId:payload.sourceClaimId,candidateClaimId:payload.candidateClaimId,count:value.rows.length});};
 assert.equal(applyApprovedCandidateSupplement(base,'MISSING_NO_DEFAULT_IO'),base);
 const out=apply(payload);assert.equal(out.count,2);assert.equal(out.platformCount,1);assert.equal(out.receipt,base.receipt);assert.equal(out.candidates[0],base.candidates[0]);assert.equal(base.candidates.length,1);
 assert.equal(out.candidates[1].sourceUrl,url);assert.equal(out.candidates[1].documentarySupplement.mapping.currentURL,payload.rows[0].mapping.currentURL);assert.deepEqual(out.candidates[1].qualification.picks,[]);
 const current=structuredClone(payload);current.rows[0].candidate.sourceUrl=current.rows[0].mapping.currentURL;current.rows[0].candidate.evidenceUrl=current.rows[0].mapping.currentURL;current.rows[0].candidate.id='catalogue:'+hash(current.rows[0].candidate.sourceUrl);current.rows[0].mapping.documentaryURL=current.rows[0].candidate.sourceUrl;assert.equal(apply(current).count,2);
 for(const mutate of [p=>{p.rows[0].mapping.nativeAuthorId=648433;},p=>{p.rows.push(structuredClone(p.rows[0]));},p=>{p.rows[0].candidate.id='SYNTH_OLD';},p=>{p.rows[0].candidate.sourceUrl='https://evil.invalid/tipsters/tips/history/642100';p.rows[0].candidate.id='catalogue:'+hash(p.rows[0].candidate.sourceUrl);},p=>{p.rows[0].mapping.profileId=true;}]){
  const changed=structuredClone(payload);mutate(changed);assert.throws(()=>apply(changed));
 }
});
