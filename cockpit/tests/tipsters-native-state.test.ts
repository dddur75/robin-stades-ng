import assert from 'node:assert/strict';
import {test} from 'node:test';
import {sourceTaskIsCurrent} from '../scripts/tipsters-native-state';
const now=Date.parse('2026-11-19T15:00:00Z');
test('only fresh enabled native tasks permit an operational flag',()=>{
 assert.equal(sourceTaskIsCurrent({state:'Ready',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
 assert.equal(sourceTaskIsCurrent({state:'Running',enabled:true,verifiedAt:'2026-11-19T15:00:00Z'},now),true);
});
test('disabled removed missing or stale tasks never count active',()=>{
 for(const state of [undefined,{state:'Disabled',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'not_found'},{state:'Ready',enabled:false,verifiedAt:'2026-11-19T15:00:00Z'},{state:'Ready',enabled:true,verifiedAt:'2026-11-19T14:59:00Z'}])assert.equal(sourceTaskIsCurrent(state,now),false);
});
