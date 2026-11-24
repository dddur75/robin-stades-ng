import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const raw=readFileSync(new URL('../scripts/olbg-campaign-companion.ts',import.meta.url),'utf8');
const {readCampaignBuffers,mergeCampaignPicks,mergeCampaignCatalogue,applyOLBGCampaignCatalogue,applyOLBGCampaignPublic}=
 await import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(raw)).toString('base64'));
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const hash=v=>createHash('sha256').update(v).digest('hex'),bytes=v=>Buffer.from(canonical(v)+'\n');
const endpoint='https://www.olbg.com/tipsters/tips/648433',slots=['2026-11-27T12:00:00+00:00','2026-11-27T13:00:00+00:00'];
const fixture={id:'synth:match',home:'Home',away:'Away',label:'Home - Away',homeAliases:['Home'],awayAliases:['Away'],kickoff:'2026-11-27T20:00:00+00:00'};
function pack(){
 const cal=hash(canonical([fixture])),parser='a'.repeat(64),builder='b'.repeat(64),claim='SYNTH.NOT.REAL';
 const plan={id:'SYNTH_OPAQUE_CAMPAIGN',claimId:claim,endpoint,robotsUrl:'https://www.olbg.com/robots.txt',termsUrl:'https://www.olbg.com/use',zeroEligiblePolicy:'HALT',slots,fixtures:[fixture],calendarSha256:cal,parserSha256:parser,builderSha256:builder};
 const mf={mission_id:plan.id,authorized_stages:['E1','E2'],maximum_stage:'E2',external_effects:{https_get_max:6,per_source_max:6},compute_budget:{},time_budget:{seconds:600},source_hash:hash(canonical(plan)),expires_at:'2026-11-27T19:00:00+00:00'};
 const planRaw=bytes(plan),mfRaw=bytes(mf),approval={planSHA256:hash(planRaw),manifestSHA256:hash(mfRaw),claimId:claim,publicBaseSHA256:'f'.repeat(64)};
 const events=[],files=new Map();let previous='0'.repeat(64);
 function append(kind,data={}){const e={sequence:events.length+1,kind,at:slots[events.length>5?1:0],previousHash:previous,...data};e.hash=hash(canonical(e));previous=e.hash;events.push(e);}
 function batch(at,rows){
  const response=hash('SYNTH'+at),records=rows.map(([tid,selection])=>({tipid:tid,eventid:900,eventname:'Home v Away',selection,market:'synthetic market',winew:'',event_datetime:'2026-11-27 20:00:00',vc_sport_id:1,result:'Open'}));
  const picks=records.map(n=>({id:'olbg-tip:'+n.tipid,sourceId:'SRC_014',authorId:'olbg:648433',authorLabel:'Synthetic',authorUrl:endpoint,sourceUrl:endpoint,sourceTipId:n.tipid,sourceEventId:n.eventid,fixtureId:fixture.id,fixtureLabel:fixture.label,kickoff:fixture.kickoff,selection:n.selection,market:'source_native_opaque',marketLabel:'Synthetic opaque',sourceMarketLabel:n.market,sourceBetType:n.winew,sourceFields:n,sourceEventLocalText:n.event_datetime,sourceEventTimezone:null,publishedAt:null,publishedCivilDate:null,observedAt:at,firstSeenAt:at,responseSha256:response,parserSha256:parser,calendarSha256:cal,performanceEvaluationAllowed:false,settlementAllowed:false,marketInterpretationAllowed:false,versions:[{selection:n.selection,observedAt:at}],versionCount:1}));
  return {schemaVersion:'robin-olbg-opaque-campaign-batch-v1',missionId:plan.id,claimId:claim,source:{profiles:[{facts:{authorId:648433,authorLabel:'Synthetic',mode:'current',records},request:{url:endpoint,observedAt:at,responseSha256:response}}],fixtures:[fixture],calendarSha256:cal},acceptedSourceTipIds:records.map(r=>r.tipid),picks,parserSha256:parser,builderSha256:builder,calendarSha256:cal,sourceReady:false,applicationAdmissions:0,recurrence:true};
 }
 function accept(slot,rows){const b=batch(slot,rows),raw=bytes(b),digest=hash(raw),name='observations-'+digest+'.json',response=b.source.profiles[0].request.responseSha256;files.set(name,raw);
  append('RUN_STARTED',{slot});append('PUBLIC_SLOT_STARTED',{slot});
  append('REQUEST_FINISHED',{sourceId:'SRC_014',url:endpoint,httpStatus:200,responseSha256:response});
  append('PUBLIC_PICKS_QUALIFIED',{sourceId:'SRC_014',responseSha256:response,parserSha256:parser,calendarSha256:cal,count:b.picks.length});
  append('PUBLIC_COLLECTION_ACCEPTED',{slot,observationFile:name,observationSha256:digest,count:b.picks.length});
  append('PUBLIC_SLOT_FINISHED',{slot,count:b.picks.length});append('RUN_FINISHED',{slot});return b;
 }
 const read=()=>readCampaignBuffers(planRaw,mfRaw,Buffer.from(events.map(canonical).join('\n')+'\n'),name=>files.get(name),approval);
 return {approval,events,files,append,accept,read,batch};
}
test('two receipt batches count one recurring pick once and preserve old rows',()=>{
 const p=pack(),first=p.accept(slots[0],[[10,'FIRST']]);p.accept(slots[1],[[10,'UPDATED'],[11,'NEW']]);
 const c=p.read();assert.equal(c.picks.length,2);assert.equal(c.batchCount,2);
 const row=c.picks.find(x=>x.sourceTipId===10);assert.equal(row.observedAt,slots[1]);assert.equal(row.firstSeenAt,slots[0]);assert.equal(row.lastSeenAt,slots[1]);assert.equal(row.versionCount,2);assert.equal(row.observationVersions.length,2);
 const historical={...first.picks[0]},before=JSON.stringify(historical),merged=mergeCampaignPicks([historical],c.picks);
 assert.equal(merged.length,2);assert.equal(merged[0].lastSeenAt,slots[1]);assert.equal(JSON.stringify(historical),before);
 assert.equal(first.picks[0].selection,'FIRST');assert.equal(merged[0].performanceEvaluationAllowed,false);
 assert.equal(merged[0].observedAt,slots[1]);assert.equal(merged[0].responseSha256,row.responseSha256);assert.deepEqual(merged[0].sourceFields,row.sourceFields);
 const target={id:'catalogue:d6120a2a545cd92a3d9b740d887d663e90af1023dfe8a64101e35cc8ea5415c1',platform:'OLBG',sourceUrl:endpoint,origin:{sheet:'Catalogue',row:269},qualification:{picks:[],personallyProven:false}};
 const other={id:'synth:other',qualification:{picks:[],personallyProven:true}};const catalogue={candidates:[target,other],qualification:{status:'ok',qualifiedCount:1}};const rawBefore=JSON.stringify(catalogue),decorated=mergeCampaignCatalogue(catalogue,c);assert.equal(decorated.qualification.qualifiedCount,2);assert.equal(decorated.candidates[0].qualification.picks.length,2);assert.equal(JSON.stringify(catalogue),rawBefore);assert.deepEqual(decorated.candidates[1],other);
});
test('default denial, orphan, duplicate slot, body corruption and after KO fail closed',()=>{
 const base={picks:[],fixtures:[],candidates:[]};assert.equal(applyOLBGCampaignCatalogue(base,'unused'),base);assert.equal(applyOLBGCampaignPublic(base,'unused','f'.repeat(64)),base);
 const empty=pack();assert.throws(()=>empty.read());const started=pack();started.append('PUBLIC_SLOT_STARTED',{slot:slots[0]});assert.throws(()=>started.read());
 const orphan=pack();orphan.append('PUBLIC_SLOT_FINISHED',{slot:slots[0],count:1});assert.throws(()=>orphan.read());
 const duplicate=pack();duplicate.accept(slots[0],[[10,'FIRST']]);duplicate.accept(slots[0],[[10,'FIRST']]);assert.throws(()=>duplicate.read());
 const corrupt=pack();corrupt.accept(slots[0],[[10,'FIRST']]);const name=[...corrupt.files.keys()][0];corrupt.files.set(name,Buffer.from('{}'));assert.throws(()=>corrupt.read());
 const p=pack(),row=p.batch(slots[0],[[10,'FIRST']]).picks[0],late={...row,observedAt:'2026-11-27T21:00:00+00:00'};assert.throws(()=>mergeCampaignPicks([], [late]));
 const conflict={...row,fixtureId:'synth:other'};assert.throws(()=>mergeCampaignPicks([row],[conflict]));
 const backfill={...row,firstSeenAt:'2026-11-27T11:00:00+00:00',observedAt:slots[1],lastSeenAt:slots[1]};assert.throws(()=>mergeCampaignPicks([row],[backfill]));
 assert.throws(()=>mergeCampaignPicks([],[{...row,firstSeenAt:slots[1]}]));
});
