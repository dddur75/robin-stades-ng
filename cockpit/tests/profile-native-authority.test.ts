import test from 'node:test';
import assert from 'node:assert/strict';
import {gateSourceOperations} from '../scripts/tipsters-native-state';
import {applyCandidateNativeState} from '../scripts/tipster-candidates-plugin';
const now=Date.parse('2026-11-20T20:00:00Z');
const ready={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
const data=()=>({enabledCount:1,candidates:[{collectionEnabled:true,qualification:{sourceId:'SRC_014',profileCampaignId:'ROBIN-OLBG-HEPTER669088-E2V2-20261120',profileAuthorUrl:'https://www.olbg.com/tipsters/tips/669088'}}],qualification:{operationalBySource:{SRC_014:true}}});
test('hepter never borrows the Alex or Andy native grants',()=>{
 for(const hepter of [undefined,{...ready,enabled:false},{...ready,verifiedAt:new Date(now-31000).toISOString()}]){
  const d=data();gateSourceOperations(d,{state:'Ready',olbg:ready,expansion:ready,hepter},now);
  assert.equal(d.enabledCount,0);
 }
});
test('only the exact fresh hepter authority opens its own row',()=>{
 const d=data();gateSourceOperations(d,{state:'Ready',hepter:ready},now);assert.equal(d.enabledCount,1);
 d.candidates[0].qualification.profileCampaignId='unknown';gateSourceOperations(d,{state:'Ready',hepter:ready},now);assert.equal(d.enabledCount,0);
});

test('legacy qualification outage cannot skip the candidate API native gate',()=>{
 const d={...data(),status:'ok'};
 Object.assign(d.qualification,{status:'unavailable'});
 applyCandidateNativeState(d,{state:'unavailable',olbg:ready,hepter:{...ready,state:'Disabled',enabled:false}},now);
 assert.equal(d.enabledCount,0);
 assert.equal(d.candidates[0].collectionEnabled,false);
 assert.equal((d.qualification as {status?:string}).status,'unavailable');
});
