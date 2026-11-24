import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const D=path.dirname(fileURLToPath(import.meta.url)),req=createRequire(new URL('../package.json',import.meta.url)),ts=req('typescript'),cache=new Map(),counts={methods:0,helperCalls:0};
function load(name){if(cache.has(name))return cache.get(name).exports;const m={exports:{}};cache.set(name,m);const raw=fs.readFileSync(path.join(D,'../scripts',name+'.ts'),'utf8'),code=ts.transpileModule(raw,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;const read=n=>n.startsWith('./')?load(n.slice(2)):req(n);new Function('require','module','exports',code)(read,m,m.exports);return m.exports;}
const reader=load('olbg-pending-source'),helper=load('olbg-pending-candidate'),target=load('olbg-reviewed-pending-approval').OLBG_REVIEWED_CANDIDATE;
const sha=b=>crypto.createHash('sha256').update(b).digest('hex'),url=target.sourceUrl;
const p={schemaVersion:'olbg-private-pending-profile-observations-v1',status:'UNQUALIFIED_INDIVIDUAL_PROFILE_OBSERVATIONS',sourceId:'SRC_014',observedAtUTC:'2026-11-24T00:00:00+00:00',responseSHA256:'a'.repeat(64),parserSHA256:'b'.repeat(64),attribution:{kind:'SOURCE_PROFILE_ACCOUNT',nativeId:648433,label:'SYNTH_ALIAS',sourceUrl:url,personIdentityVerified:false},sourceRecordCount:1,records:[{sourceTipId:1,sourceEventId:2,eventText:'SYNTH_EVENT',selectionText:'SYNTH_SELECTION',marketText:'SYNTH_MARKET',betTypeText:'SYNTH_TYPE',nativeDateText:'SYNTH_DATE'}],omitted:{nonFootballOpen:0,invalidNativeFields:0},competition:null,canonicalFixture:null,kickoffUTC:null,sourceEventTimezone:null,publishedAt:null,preMatchProven:false,sourceReady:false,admissions:0,eligibleForApplication:false,interpretationAllowed:false,performanceEvaluationAllowed:false,settlementAllowed:false,globalCoverage:'UNKNOWN'};
const raw=Buffer.from(JSON.stringify(p)),claim='DATA.SOURCE_OBSERVATORY.OLBG.PENDING.SYNTH',a={pendingSHA256:sha(raw),receiptSHA256:'',bytes:raw.length,count:1,observedAtUTC:p.observedAtUTC,responseSHA256:p.responseSHA256,parserSHA256:p.parserSHA256,builderSHA256:'d6e1b1691fba712fd578eea81e6f6d4793e5a5054f31281af33fdb57acbb1882',claimId:claim};
const r={claimId:claim,status:'PARTIAL',sourceReady:false,admissions:0,authorityClosed:true,observedAtUTC:p.observedAtUTC,responseSHA256:p.responseSHA256,parserSHA256:p.parserSHA256,pendingBuilderSHA256:a.builderSHA256,sourceClaims:[reader.OLBG_PENDING_BUILDER_CLAIM],pending:{status:'PRIVATE_UNQUALIFIED_ONLY',SHA256:a.pendingSHA256,bytes:a.bytes,recordCount:1,applicationAdmissions:0}},receipt=Buffer.from(JSON.stringify(r));a.receiptSHA256=sha(receipt);
const base=()=>({count:317,admissions:0,picks:['SYNTH_HISTORICAL'],candidates:[{id:target.id,sourceUrl:url,platform:'OLBG',origin:{sheet:'Catalogue',row:269}},{id:'SYNTH_OTHER',sourceUrl:'https://example.test',platform:'OTHER',origin:{sheet:'SYNTH',row:1}}]});
const apply=(b,body=raw)=>{counts.helperCalls++;return helper.applyReviewedOLBGPendingToCandidate(b,body,receipt,a);},check=fn=>{counts.methods++;fn();};
let passed=false;
try{
check(()=>{const b=base(),o=apply(b);assert.equal(o.candidates[0].pendingOLBGObservation.records.length,1);assert.equal(o.candidates[1],b.candidates[1]);});
check(()=>{const b=base();b.candidates[0].sourceUrl='https://www.olbg.com/tipsters/tips/1';assert.equal(apply(b),b);});
check(()=>{const b=base();b.candidates[0].id='SYNTH_WRONG';assert.equal(apply(b),b);});
check(()=>{const b=base();b.candidates.push({...b.candidates[0]});assert.equal(apply(b),b);});
check(()=>{const b=base();assert.equal(apply(b,Buffer.from('SYNTH_CORRUPT')),b);});
check(()=>{const b=base(),before=JSON.stringify(b),o=apply(b);assert.equal(JSON.stringify(b),before);assert.deepEqual(o.picks,b.picks);assert.equal(o.count,317);assert.equal(o.admissions,0);assert.equal(o.candidates[0].pendingOLBGObservation.preMatchProven,false);assert.equal(o.candidates[0].pendingOLBGObservation.personIdentityVerified,false);});
passed=true;
}finally{console.log(JSON.stringify({status:passed?'PASS':'FAIL',counts,syntheticOnly:true,realPendingReads:0,sourceGET:0}));}
