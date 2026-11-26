import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {readReviewedPublicSnapshot,type SnapshotApproval} from '../scripts/reviewed-public-snapshot';
const hash=(x:string|Buffer)=>createHash('sha256').update(x).digest('hex');
const can=(v:unknown):string=>Array.isArray(v)?'['+v.map(can).join(',')+']':v&&typeof v==='object'?'{'+Object.entries(v).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,x])=>JSON.stringify(k)+':'+can(x)).join(',')+'}':JSON.stringify(v);
const fields=['id','firstSeenAt','observedAt','versions','authorLabel','selection','sourceUrl'];
function fixture(){
 const pick={id:'a'.repeat(64),authorId:'public:one',authorLabel:'Profil public',fixtureId:'f1',sourceId:'SRC_058',firstSeenAt:'2026-11-22T08:00:00Z',observedAt:'2026-11-22T08:00:00Z',kickoff:'2026-11-22T14:00:00Z',versions:['v1'],selection:'1-0',sourceUrl:'https://example.test/p1',lastSeenAt:'2026-11-22T08:00:00Z'};
 return {schemaVersion:'robin-public-tipsters-v1',status:'ok',distinctPicks:1,authorCount:1,picks:[pick],fixtures:[{id:'f1'}],generatedAt:'2026-11-22T08:01:00Z',sourceObservedThrough:'2026-11-22T08:00:00Z',claimId:'DATA.EXAMPLE',claimIds:['DATA.EXAMPLE'],requestCount:3,calendarSha256:'c'.repeat(64),recurring:true,halted:false,campaign:{state:'ready',operational:true,native:{verifiedAt:'2026-11-22T10:00:00Z'}},rosterNextCampaign:{state:'ready',successfulSlots:2},notbettingOccurrenceCompanion:{updates:{[pick.id]:{observations:[{observedAt:pick.observedAt}]}}},forumCompanion:{state:'available',updates:{[pick.id]:{lastSeenAt:pick.lastSeenAt}}}};
}
function setup(value=fixture()){
 const root=mkdtempSync(join(tmpdir(),'robin-retained-facts-')),raw=JSON.stringify(value),sha256=hash(raw);
 const rows=value.picks.map(p=>Object.fromEntries(fields.map(k=>[k,p[k as keyof typeof p]])));
 const approval:SnapshotApproval={relativePath:'.ci/public-tipsters-approved/'+sha256+'/snapshot.json',sha256,claimId:'DATA.SNAPSHOT.AUDIT',choices:1,pseudonyms:1,fixtures:1,maximumBytes:2000000,idsSHA256:hash(can(value.picks.map(p=>p.id).sort())),immutableSHA256:hash(can(rows))};
 const path=join(root,approval.relativePath);mkdirSync(join(path,'..'),{recursive:true});writeFileSync(path,raw);
 return {root,path,approval,raw};
}
function using(fn:(s:ReturnType<typeof setup>)=>void,value=fixture()){const s=setup(value);try{fn(s);}finally{assert.equal(dirname(resolve(s.root)),resolve(tmpdir()));assert.ok(s.root.startsWith(join(tmpdir(),'robin-retained-facts-')));rmSync(s.root,{recursive:true,force:true});}}
test('reviewed facts survive independently of expired operation metadata without stale ready flags',()=>using(s=>{
 const result=readReviewedPublicSnapshot(s.root,s.approval);
 assert.equal(result.distinctPicks,1);assert.equal(result.authorCount,1);assert.deepEqual(result.picks,fixture().picks);
 for(const k of ['campaign','rosterNextCampaign','recurring','halted'])assert.equal(result[k],undefined);
 assert.deepEqual(result.notbettingOccurrenceCompanion,fixture().notbettingOccurrenceCompanion);
 assert.equal((result.retainedSnapshot as {operationalState:string}).operationalState,'unknown');
 assert.equal(result.sourceObservedThrough,fixture().sourceObservedThrough);
}));
test('missing configured snapshot fails closed',()=>using(s=>{rmSync(s.path);assert.throws(()=>readReviewedPublicSnapshot(s.root,s.approval));}));
test('raw tamper fails before parsing',()=>using(s=>{writeFileSync(s.path,s.raw+' ');assert.throws(()=>readReviewedPublicSnapshot(s.root,s.approval));}));
test('bounded bytes reject a growing or oversized file',()=>using(s=>{writeFileSync(s.path,'x'.repeat(2000001));assert.throws(()=>readReviewedPublicSnapshot(s.root,s.approval));}));
test('path traversal and unrelated paths are refused',()=>using(s=>{for(const relativePath of ['../snapshot.json','snapshot.json','.ci/public-tipsters-approved/'+s.approval.sha256+'/../snapshot.json'])assert.throws(()=>readReviewedPublicSnapshot(s.root,{...s.approval,relativePath}));}));
test('schema mismatch and inconsistent counts are refused even under matching raw SHA',()=>{for(const key of ['schemaVersion','distinctPicks','authorCount']){const value=fixture();(value as Record<string,unknown>)[key]=key==='schemaVersion'?'v2':2;using(s=>assert.throws(()=>readReviewedPublicSnapshot(s.root,s.approval)),value);}});
test('contradictory native ID and immutable projections fail closed',()=>using(s=>{assert.throws(()=>readReviewedPublicSnapshot(s.root,{...s.approval,idsSHA256:'f'.repeat(64)}));assert.throws(()=>readReviewedPublicSnapshot(s.root,{...s.approval,immutableSHA256:'f'.repeat(64)}));}));
test('late or missing kickoff observations are refused',()=>{const value=fixture();value.picks[0].kickoff='2026-11-22T07:00:00Z';using(s=>assert.throws(()=>readReviewedPublicSnapshot(s.root,s.approval)),value);});
test('snapshot cannot fabricate a fresh collection date from current time',()=>using(s=>{const a=readReviewedPublicSnapshot(s.root,s.approval),b=readReviewedPublicSnapshot(s.root,s.approval);assert.deepEqual(a,b);assert.equal(a.generatedAt,fixture().generatedAt);assert.deepEqual(a.picks,fixture().picks);}));

test('configured endpoint never invokes historical subprocesses, including missing or corrupt snapshots',async()=>{
 const {createRequire,syncBuiltinESMExports}=await import('node:module');
 const {IncomingMessage}=await import('node:http');
 const {Socket}=await import('node:net');
 const require=createRequire(import.meta.url);
 const child=require('node:child_process') as typeof import('node:child_process');
 const original=Object.getOwnPropertyDescriptor(child,'execFile')!;let processCalls=0;
 Object.defineProperty(child,'execFile',{...original,value:()=>{processCalls++;throw Error('HISTORICAL_PROCESS_FORBIDDEN');}});syncBuiltinESMExports();
 const s=setup();
 try{
  const {publicTipsters}=await import('../scripts/public-tipsters-plugin');
  const plugin=publicTipsters(s.approval);
  (plugin.configResolved as (config:{root:string})=>void)({root:s.root});
  type Handler=(req:import('node:http').IncomingMessage,res:import('node:http').ServerResponse,next:()=>void)=>void;
  let handler:Handler|undefined;
  (plugin.configureServer as (server:{middlewares:{use(h:Handler):void}})=>void)({middlewares:{use(h){handler=h;}}});
  const request=(method='GET',address='127.0.0.1')=>{
   const req=new IncomingMessage(new Socket());Object.defineProperty(req.socket,'remoteAddress',{value:address});
   req.url='/api/tipsters/public';req.method=method;req.headers={host:'127.0.0.1:4173'};
   let body='';const res={statusCode:200,setHeader(){},end(value:string){body=value;}};
   assert.ok(handler);handler(req,res as unknown as import('node:http').ServerResponse,()=>{throw Error('UNEXPECTED_NEXT');});
   return {status:res.statusCode,value:JSON.parse(body)};
  };
  assert.equal(request().value.distinctPicks,1);
  assert.equal(request('POST').status,403);assert.equal(request('GET','192.0.2.1').status,403);
  writeFileSync(s.path,s.raw+' ');assert.equal(request().status,503);
  rmSync(s.path);assert.equal(request().status,503);
  assert.equal(processCalls,0);
 }finally{
  Object.defineProperty(child,'execFile',original);syncBuiltinESMExports();
  assert.equal(dirname(resolve(s.root)),resolve(tmpdir()));assert.ok(s.root.startsWith(join(tmpdir(),'robin-retained-facts-')));
  rmSync(s.root,{recursive:true,force:true});
 }
});

test('approved native source identifiers need not be SHA hashes',()=>{const value=fixture();value.picks[0].id='olbg-tip:296399226';using(s=>assert.equal(readReviewedPublicSnapshot(s.root,s.approval).distinctPicks,1),value);});

test('historical observation companions never carry cached operational flags',()=>{const value=fixture();Object.assign(value.notbettingOccurrenceCompanion,{active:false,pending:0});using(s=>{const c=readReviewedPublicSnapshot(s.root,s.approval).notbettingOccurrenceCompanion as Record<string,unknown>;assert.deepEqual(c,{updates:value.notbettingOccurrenceCompanion.updates});},value);});

test('reviewed historical SRO and forum batch provenance survives without operational flags',()=>{
 const value=fixture() as ReturnType<typeof fixture>&Record<string,unknown>;
 const historical={updates:{p:{lastSeenAt:'2026-11-22T08:00:00Z'}},claimId:'DATA.SRO',parentClaimId:'DATA.SRO.PARENT',sourceMissionId:'SRO.OLD',candidateSHA256:'a'.repeat(64),receiptSHA256:'b'.repeat(64),sourceResponseSHA256:'c'.repeat(64),sourceObservedAt:'2026-11-21T08:00:00Z',wrapperSHA256:'d'.repeat(64),decisionSHA256:'e'.repeat(64),approvedReobservationCount:1,approvedNewCount:0,kind:'historical'};
 const batch={state:'available',envelopeSHA256:'f'.repeat(64),missionId:'FORUM.OLD',claimId:'DATA.FORUM',decisionSHA256:'e'.repeat(64),preparedAt:'2026-11-22T08:00:00Z',approvedObservationCount:1,approvedNewCount:0,approvedReobservationCount:1};
 value.sroNextCompanion={...historical,active:true,native:{ready:true}};value.forumBatches=[{...batch,active:true,native:{ready:true}}];
 using(s=>{const result=readReviewedPublicSnapshot(s.root,s.approval);assert.deepEqual(result.sroNextCompanion,historical);assert.deepEqual(result.forumBatches,[batch]);assert.equal(result.sourceObservedThrough,value.sourceObservedThrough);assert.deepEqual(result.picks,value.picks);},value);
});
