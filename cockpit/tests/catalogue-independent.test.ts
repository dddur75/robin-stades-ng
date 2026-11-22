import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {stripTypeScriptTypes} from 'node:module';
import {projectCatalogue,decorateIndependentInventory,type Approval} from '../scripts/catalogue-independent';

const hash=(s:string|Uint8Array)=>createHash('sha256').update(s).digest('hex');
const raw=(v:unknown)=>Buffer.from(JSON.stringify(v));
const workbook='a'.repeat(64),csv='b'.repeat(64);
const row=(n:number)=>{const url='https://example.org/profile/'+n;return {id:'catalogue:'+hash(url),label:'Synthetic '+n,platform:'Synthetic',sourceUrl:url,evidenceUrl:url+'/proof',declaredLastDate:'2026-09-04',origin:{sheet:'Catalogue',row:n+5,workbookSha256:workbook},historicalLabel:'Historical',status:'pending_qualification',collectionEnabled:false};};
const rows=[row(1),row(2)];
const pick={id:'pick-1',selection:'1-0',fixtureLabel:'Synthetic fixture',fixtureId:'fixture-1',sourceId:'SRC_SYNTH',sourceUrl:'https://example.org/post/1',market:'correct_score',observedAt:'2026-11-19T10:00:00Z',firstSeenAt:'2026-11-19T10:00:00Z',lastSeenAt:'2026-11-19T11:00:00Z',kickoff:'2026-11-22T14:00:00Z',publishedAt:null,versions:[{selection:'1-0',observedAt:'2026-11-19T10:00:00Z'}],versionCount:1};
const qualification={label:'Historical qualified',reason:'Synthetic fact',requiredAccess:'Historical',ownerAction:'None',profileVisited:true,personallyProven:true,picks:[pick],documentaryIssues:[],observedAt:'2026-11-19T11:00:00Z',profileCampaign:{enabled:true},rosterCampaignId:'OLD',nativeSRO:{running:true}};
const registryRaw=raw(rows);const receipt={schemaVersion:'robin-candidate-registry-v1',count:2,platformCount:1,datedCount:2,registrySha256:hash(registryRaw),csvSha256:csv,sourceWorkbookSha256:workbook,claimId:'DATA.SOURCE_OBSERVATORY.CANDIDATES317.20261119'};const receiptRaw=raw(receipt);
const retained={status:'ok',schemaVersion:receipt.schemaVersion,candidates:rows.map(r=>({...r,collectionEnabled:true,qualification})),receipt,qualification:{status:'ok',claimId:'HISTORICAL.CLAIM',observedAt:'2026-11-19T15:08:14.733936+00:00',qualifiedCount:2,assessedCount:2,platforms:[],sourceOperational:{running:true},nativeSRO:{running:true},rosterCollectionState:'ok'},rosterAssessments:[{recordId:'workbook:synthetic',candidateId:rows[0].id,sheet:'Profiles',row:9,sourceUrl:rows[0].sourceUrl,collectionEnabled:true,qualification}]};
const qualRaw=raw(retained);const approval:Approval={registrySHA256:hash(registryRaw),receiptSHA256:hash(receiptRaw),qualificationSHA256:hash(qualRaw),workbookSHA256:workbook,csvSHA256:csv,count:2,rosterCount:1,qualificationClaimId:'ENG.SYNTHETIC.RETAINED'};
const projected=projectCatalogue(registryRaw,receiptRaw,qualRaw,approval);
assert.equal(projected.count,2);assert.equal(projected.enabledCount,null);assert.equal(projected.operationalState,'unknown');
assert(projected.candidates.every(r=>r.collectionEnabled===null&&r.operationalState==='unknown'));
assert.deepEqual(projected.candidates[0].qualification?.picks,[pick]);assert.deepEqual(projected.candidates[0].origin,rows[0].origin);
assert.equal(projected.qualification?.observedAt,retained.qualification.observedAt);
assert.equal(projected.historicalEvidence.captureTimeCertified,false);assert.equal(projected.historicalEvidence.currentStateVerified,false);
assert(!JSON.stringify(projected).includes('sourceOperational'));assert(!JSON.stringify(projected).includes('nativeSRO'));assert(!JSON.stringify(projected).includes('profileCampaign'));assert(!JSON.stringify(projected).includes('rosterCampaignId'));
for(const missing of [undefined,Buffer.from('broken'),raw({...retained,status:'invalid'})]){
 const fallback=projectCatalogue(registryRaw,receiptRaw,missing,approval);assert.equal(fallback.count,2);assert.equal(fallback.qualification?.status,'unavailable');assert.equal(fallback.candidates[0].qualification,undefined);assert.equal(fallback.enabledCount,null);
}
assert.throws(()=>projectCatalogue(Buffer.from('broken'),receiptRaw,qualRaw,approval));
assert.throws(()=>projectCatalogue(registryRaw,Buffer.from('broken'),qualRaw,approval));
const wrongRows=[rows[0],{...rows[1],id:rows[0].id}],wrongRaw=raw(wrongRows);assert.throws(()=>projectCatalogue(wrongRaw,receiptRaw,qualRaw,{...approval,registrySHA256:hash(wrongRaw)}));
const duplicateReceiptRaw=raw({...receipt,registrySha256:hash(wrongRaw)});assert.throws(()=>projectCatalogue(wrongRaw,duplicateReceiptRaw,qualRaw,{...approval,registrySHA256:hash(wrongRaw),receiptSHA256:hash(duplicateReceiptRaw)}));
const mismatched={...retained,candidates:[{...retained.candidates[0],sourceUrl:'https://foreign.example/'},retained.candidates[1]]};const mismatchedRaw=raw(mismatched);
assert.equal(projectCatalogue(registryRaw,receiptRaw,mismatchedRaw,{...approval,qualificationSHA256:hash(mismatchedRaw)}).qualification.status,'unavailable');
const invalidStatusRaw=raw({...retained,status:'invalid'});assert.equal(projectCatalogue(registryRaw,receiptRaw,invalidStatusRaw,{...approval,qualificationSHA256:hash(invalidStatusRaw)}).qualification.status,'unavailable');
// C0's conservative bundle policy: one absent candidate block invalidates all qualification.
const absentRow={...retained,candidates:retained.candidates.map((r,i)=>i===1?Object.fromEntries(Object.entries(r).filter(([k])=>k!=='qualification')):r)};
const absentRaw=raw(absentRow),absentProjected=projectCatalogue(registryRaw,receiptRaw,absentRaw,{...approval,qualificationSHA256:hash(absentRaw)});
const microFailures:string[]=[];
if(Object.hasOwn(absentProjected.candidates[1],'qualification'))microFailures.push('ABSENT_ROW_QUAL_EMITTED');
if(absentProjected.qualification.status!=='unavailable'||absentProjected.candidates[0].qualification!==undefined)microFailures.push('PARTIAL_BUNDLE_ACCEPTED');
assert.equal(absentProjected.count,2);
const withoutQ=Object.fromEntries(Object.entries(retained.candidates[0]).filter(([k])=>k!=='qualification'));
const duplicateAbsentRaw=raw({...retained,candidates:[withoutQ,withoutQ]});
const duplicateAbsent=projectCatalogue(registryRaw,receiptRaw,duplicateAbsentRaw,{...approval,qualificationSHA256:hash(duplicateAbsentRaw)});
if(duplicateAbsent.qualification.status!=='unavailable')microFailures.push('DUPLICATE_ABSENT_BUNDLE_ACCEPTED');
assert.equal(duplicateAbsent.candidates.length,2);
for(const malformed of [{picks:undefined},{picks:null},{picks:{}},{documentaryIssues:undefined},{documentaryIssues:null},{documentaryIssues:'bad'},{documentaryIssues:[42]}]){
 const value={...retained,candidates:retained.candidates.map((r,i)=>i===1?{...r,qualification:{...qualification,...malformed}}:r)},b=raw(value);
 const result=projectCatalogue(registryRaw,receiptRaw,b,{...approval,qualificationSHA256:hash(b)});
 if(result.qualification.status!=='unavailable')microFailures.push('MALFORMED_ROW_QUAL_ACCEPTED');
 assert.equal(result.count,2);assert.equal(result.operationalState,'unknown');
}
assert.deepEqual(microFailures,[],'C3 row qualification shape guard');
const page={status:'ok',records:[{recordId:'original',candidateId:rows[0].id,sheet:'Catalogue',row:rows[0].origin.row,sourceUrl:rows[0].sourceUrl,platform:'Synthetic',collectionEnabled:true},{recordId:'workbook:synthetic',candidateId:rows[0].id,sheet:'Profiles',row:9,sourceUrl:rows[0].sourceUrl,platform:'Synthetic',collectionEnabled:true},{recordId:'foreign',candidateId:rows[1].id,sheet:'Catalogue',row:rows[1].origin.row,sourceUrl:'https://foreign.example/',platform:'Synthetic',collectionEnabled:true}]};
const decorated=decorateIndependentInventory(page,projected);assert.equal(decorated.records[0].qualifiedRecordId,rows[0].id);assert.deepEqual(decorated.records[1].qualification?.picks,[pick]);assert.equal(decorated.records[2].qualification,undefined);assert(decorated.records.every(r=>r.collectionEnabled===null));assert.equal(decorated.readAt,undefined);
const sourcePath=(name:string)=>fileURLToPath(new URL(name.endsWith('.tsx')?'../app/components/expert/'+name:'../scripts/'+name,import.meta.url));
for(const name of ['tipster-candidates-plugin.ts','workbook-inventory-plugin.ts']){const source=readFileSync(sourcePath(name),'utf8');assert(!source.includes('readNativeState'));assert(!source.includes('gateSourceOperations'));assert(!source.includes('read-tipster-candidates.py'));}
const inventorySource=readFileSync(sourcePath('workbook-inventory-plugin.ts'),'utf8');assert.equal((inventorySource.match(/await runFile\(/g)??[]).length,1);assert(inventorySource.includes('read-workbook-inventory.py'));assert(inventorySource.includes('query.limit>50'));
// Exercise both real middleware bodies with synthetic dependencies, no HTTP or subprocess.
const state={reads:0,processCalls:0,failRegistry:false};
const shared={readIndependentCatalogue:()=>{state.reads++;if(state.failRegistry)throw Error('bad registry');return projected;},decorateIndependentInventory};
(globalThis as Record<string,unknown>).__catalogueTest=shared;
(globalThis as Record<string,unknown>).__catalogueExec=(exe:string,args:string[],options:Record<string,unknown>,callback:(error:Error|null,out:string,err:string)=>void)=>{
 state.processCalls++;assert(args.some(v=>v.endsWith('read-workbook-inventory.py')));assert(!args.some(v=>v.endsWith('read-tipster-candidates.py')));assert.equal(options.windowsHide,true);callback(null,JSON.stringify(page),'');
};
const dataURL=(s:string)=>'data:text/javascript;base64,'+Buffer.from(s).toString('base64');
const helperURL=dataURL('export const {readIndependentCatalogue,decorateIndependentInventory}=globalThis.__catalogueTest;');
const processURL=dataURL('import{promisify}from"node:util";export const execFile=(...args)=>globalThis.__catalogueExec(...args);execFile[promisify.custom]=(...args)=>new Promise((resolve,reject)=>execFile(...args,(e,stdout,stderr)=>e?reject(e):resolve({stdout,stderr})));');
const guardURL=dataURL('export const permitsLocalPilotRead=r=>r.method==="GET"&&r.socket.remoteAddress==="127.0.0.1";');
type CapturedMiddleware=(request:unknown,response:unknown,next:()=>void)=>unknown;
async function middleware(name:string){
 const source=stripTypeScriptTypes(readFileSync(sourcePath(name),'utf8')).replaceAll("'./catalogue-independent'",JSON.stringify(helperURL)).replaceAll("'./tipsters-pilot-plugin'",JSON.stringify(guardURL)).replaceAll("'node:child_process'",JSON.stringify(processURL));
 const testedExports=await import(dataURL(source));const plugin=name.startsWith('tipster-')?testedExports.tipsterCandidates():testedExports.workbookInventory();let run:CapturedMiddleware|undefined;
 plugin.configResolved({root:'synthetic/cockpit'});plugin.configureServer({middlewares:{use:f=>{run=f;}}});assert(run);return run;
}
async function call(run:CapturedMiddleware,path:string){let body='',statusCode=200;const response={setHeader(){},get statusCode(){return statusCode;},set statusCode(n){statusCode=n;},end(v:string){body=v;}};await run({url:path,method:'GET',socket:{remoteAddress:'127.0.0.1'},headers:{}},response,()=>{throw Error('Unexpected next')});return {statusCode,body:JSON.parse(body)};}
const candidateMiddleware=await middleware('tipster-candidates-plugin.ts'),inventoryMiddleware=await middleware('workbook-inventory-plugin.ts');
assert.equal((await call(candidateMiddleware,'/api/tipsters/candidates')).body.count,2);assert.equal(state.processCalls,0);
assert.equal((await call(inventoryMiddleware,'/api/tipsters/workbook?limit=25')).body.records.length,3);assert.equal(state.processCalls,1);
assert.equal((await call(inventoryMiddleware,'/api/tipsters/workbook?limit=51')).statusCode,400);assert.equal(state.processCalls,1);
state.failRegistry=true;assert.equal((await call(candidateMiddleware,'/api/tipsters/candidates')).statusCode,503);assert.equal(state.processCalls,1);
const noDecoration=await call(inventoryMiddleware,'/api/tipsters/workbook?limit=25');assert.equal(state.processCalls,2);assert.equal(noDecoration.body.qualifiedRegistryState,'unavailable');assert(noDecoration.body.records.every(r=>r.collectionEnabled===null));
for(const name of ['tipster-candidates.tsx','workbook-catalogue.tsx']){const s=readFileSync(sourcePath(name),'utf8');assert(s.includes('collectionEnabled:boolean|null'));assert(s.includes('État actuel'));}
assert(readFileSync(sourcePath('workbook-catalogue.tsx'),'utf8').includes('Actualiser le catalogue'));
console.log(JSON.stringify({status:'PASS_SYNTHETIC_ONLY',fixtureRegistryRows:2,fixtureInventoryRows:3,optionalQualificationFailures:3,existingPickDatesAndVersionsPreserved:true,operationalPayloadsRemoved:true,nativeCalls:0,historicalPythonCalls:0,indexReads:0,HTTP:0,source:0,writes:0}));
