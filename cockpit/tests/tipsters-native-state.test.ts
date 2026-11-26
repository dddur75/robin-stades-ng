import assert from 'node:assert/strict';
import {test} from 'node:test';
import {sourceTaskIsCurrent,gateSourceOperations,projectNativeState} from '../scripts/tipsters-native-state';
const now=Date.parse('2026-11-19T15:00:00Z');

test('native startup and a failed read have distinct fail-closed child states',()=>{
 for(const status of ['checking','unavailable']){
  const result=projectNativeState({state:status},now);
  for(const key of ['sro','olbg','expansion','hepter','roster','notbetting']as const){
   assert.deepEqual(result[key],{state:status});
   assert.equal(sourceTaskIsCurrent(result[key],now),false);
  }
 }
 assert.equal(projectNativeState({state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()},now).roster?.state,'checking');
});

test('a successor requires its own native task and never inherits the completed task',()=>{
 const task={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
 for(const next of [undefined,task]){
  const row={collectionEnabled:true,qualification:{sourceId:'SRC_014',rosterCampaignId:'ROBIN-OLBG-ROSTER42-NEXT3-20261121',rosterAuthorUrl:'https://www.olbg.com/tipsters/tips/669101'}};
  const data={enabledCount:1,candidates:[row],qualification:{operationalBySource:{SRC_014:true}}};
  gateSourceOperations(data,{state:'Ready',roster:task,rosterNext:next},now);
  assert.equal(data.candidates[0].collectionEnabled,Boolean(next));
 }
});

test('native projection preserves independent fresh children and expires old ones',()=>{
 const fresh={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
 const stale={...fresh,verifiedAt:new Date(now-30001).toISOString()};
 const value={state:'Ready',sro:fresh,olbg:stale};
 const result=projectNativeState(value,now);
 assert.deepEqual(result.sro,fresh);
 assert.deepEqual(result.olbg,{...stale,state:'stale',enabled:false});
 assert.deepEqual(result.roster,{state:'checking'});
 assert.deepEqual(value.olbg,stale);
});

test('a fresh native recovery restores only independently permitted source rows',()=>{
 const original={enabledCount:2,candidates:[{collectionEnabled:true,qualification:{sourceId:'SRC_039'}},{collectionEnabled:false,qualification:{sourceId:'SRC_039'}},{collectionEnabled:true,qualification:{sourceId:'SRC_014'}}],qualification:{operationalBySource:{SRC_039:true,SRC_014:true}}};
 const failed=structuredClone(original);
 gateSourceOperations(failed,projectNativeState({state:'unavailable'},now),now);
 assert.deepEqual(failed.candidates.map(r=>r.collectionEnabled),[false,false,false]);
 const recovered=structuredClone(original);
 gateSourceOperations(recovered,projectNativeState({state:'Ready',sro:{state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()}},now),now);
 assert.deepEqual(recovered.candidates.map(r=>r.collectionEnabled),[true,false,false]);
 assert.equal(recovered.enabledCount,1);
});
test('only fresh enabled native tasks permit an operational flag',()=>{
 assert.equal(sourceTaskIsCurrent({state:'Ready',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
 assert.equal(sourceTaskIsCurrent({state:'Running',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
});
test('disabled removed missing or stale tasks never count active',()=>{
 for(const state of [undefined,{state:'Disabled',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'not_found'},{state:'Ready',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'Ready',enabled:true,verifiedAt:'2026-11-19T14:59:00Z'}])assert.equal(sourceTaskIsCurrent(state,now),false);
});

test('a successful task without a future trigger is not an active collection',()=>{
 assert.equal(sourceTaskIsCurrent({state:'no_future_run',enabled:true,verifiedAt:new Date(now).toISOString()},now),false);
});

test('independent source tasks gate their own rows and preserve personal facts',()=>{
 for(const [sro,olbg] of [[true,false],[false,true],[true,true],[false,false]]){
  const data={enabledCount:2,candidates:[{collectionEnabled:true,qualification:{sourceId:'SRC_039'}},{collectionEnabled:true,qualification:{sourceId:'SRC_014'}}],qualification:{operationalBySource:{SRC_039:true,SRC_014:true}}};
  const task=(enabled:boolean)=>({state:enabled?'Ready':'Disabled',enabled,verifiedAt:new Date(now).toISOString()});
  gateSourceOperations(data,{state:'Ready',sro:task(sro),olbg:task(olbg)},now);
  assert.deepEqual(data.candidates.map(r=>r.collectionEnabled),[sro,olbg]);assert.equal(data.enabledCount,Number(sro)+Number(olbg));
 }
});

test('roster rows and catalogue-only rows require their own fresh exact task',()=>{
 const task={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
 for(const own of [undefined,task]){
  const row={collectionEnabled:true,qualification:{sourceId:'SRC_014',rosterCampaignId:'ROBIN-OLBG-ROSTER42-E2V2-20261120',rosterAuthorUrl:'https://www.olbg.com/tipsters/tips/669101'}};
  const data={enabledCount:1,candidates:[structuredClone(row)],rosterAssessments:[structuredClone(row),{...structuredClone(row),qualification:{...row.qualification,rosterAuthorUrl:'https://www.olbg.com/tipsters/tips/669088'}}],qualification:{operationalBySource:{SRC_014:true}}};
  gateSourceOperations(data,{state:'Ready',olbg:task,hepter:task,roster:own},now);
  assert.equal(data.candidates[0].collectionEnabled,Boolean(own));
  assert.equal(data.rosterAssessments[0].collectionEnabled,Boolean(own));
  assert.equal(data.rosterAssessments[1].collectionEnabled,false);
 }
});
