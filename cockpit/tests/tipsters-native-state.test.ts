import assert from 'node:assert/strict';
import {test} from 'node:test';
import {sourceTaskIsCurrent,gateSourceOperations} from '../scripts/tipsters-native-state';
const now=Date.parse('2026-11-19T15:00:00Z');
test('only fresh enabled native tasks permit an operational flag',()=>{
 assert.equal(sourceTaskIsCurrent({state:'Ready',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
 assert.equal(sourceTaskIsCurrent({state:'Running',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
});
test('disabled removed missing or stale tasks never count active',()=>{
 for(const state of [undefined,{state:'Disabled',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'not_found'},{state:'Ready',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'Ready',enabled:true,verifiedAt:'2026-11-19T14:59:00Z'}])assert.equal(sourceTaskIsCurrent(state,now),false);
});

test('independent source tasks gate their own rows and preserve personal facts',()=>{
 for(const [sro,olbg] of [[true,false],[false,true],[true,true],[false,false]]){
  const data={enabledCount:2,candidates:[{collectionEnabled:true,qualification:{sourceId:'SRC_039'}},{collectionEnabled:true,qualification:{sourceId:'SRC_014'}}],qualification:{operationalBySource:{SRC_039:true,SRC_014:true}}};
  const task=(enabled:boolean)=>({state:enabled?'Ready':'Disabled',enabled,verifiedAt:new Date(now).toISOString()});
  gateSourceOperations(data,{state:'Ready',sro:task(sro),olbg:task(olbg)},now);
  assert.deepEqual(data.candidates.map(r=>r.collectionEnabled),[sro,olbg]);assert.equal(data.enabledCount,Number(sro)+Number(olbg));
 }
});
