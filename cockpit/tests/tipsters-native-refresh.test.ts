import assert from 'node:assert/strict';
import {test} from 'node:test';
import * as native from '../scripts/tipsters-native-state';

const at=Date.parse('2026-11-21T17:12:00Z');
const task=(time:number)=>({state:'Ready',enabled:true,verifiedAt:new Date(time).toISOString()});

test('first native response awaits the actual load and concurrent callers share it',async()=>{
 let calls=0,finish!:(value:{state:string;rosterNext:ReturnType<typeof task>})=>void;
 const reader=native.createNativeStateReader(()=>{calls++;return new Promise(resolve=>{finish=resolve;});},()=>at);
 let settled=false;
 const first=reader('root').then(value=>{settled=true;return value;});
 const second=reader('root');
 await Promise.resolve();
 assert.equal(calls,1);assert.equal(settled,false);
 finish({state:'Ready',rosterNext:task(at)});
 for(const value of await Promise.all([first,second]))assert.equal(native.sourceTaskIsCurrent(value.rosterNext,at),true);
});

test('a read after idle waits for a new native timestamp instead of returning stale',async()=>{
 let clock=at,calls=0;
 const reader=native.createNativeStateReader(async()=>{calls++;return {state:'Ready',rosterNext:task(clock)};},()=>clock);
 await reader('root');clock+=69000;
 const refreshed=await reader('root');
 assert.equal(calls,2);assert.equal(refreshed.rosterNext?.verifiedAt,new Date(clock).toISOString());
 assert.equal(native.sourceTaskIsCurrent(refreshed.rosterNext,clock),true);
});

test('a cached fresh read is reused and a failed refresh closes all task gates',async()=>{
 let clock=at,calls=0;
 const reader=native.createNativeStateReader(async()=>{calls++;if(calls>1)throw Error('unavailable');return {state:'Ready',rosterNext:task(clock)};},()=>clock);
 await reader('root');clock+=14000;
 assert.equal(native.sourceTaskIsCurrent((await reader('root')).rosterNext,clock),true);assert.equal(calls,1);
 clock+=1000;
 const failed=await reader('root');assert.equal(calls,2);
 assert.equal(failed.state,'unavailable');assert.equal(native.sourceTaskIsCurrent(failed.rosterNext,clock),false);
});

test('a source-supplied old timestamp is still rejected after a successful load',async()=>{
 const reader=native.createNativeStateReader(async()=>({state:'Ready',rosterNext:task(at-30001)}),()=>at);
 const old=await reader('root');assert.equal(old.rosterNext?.state,'stale');
 assert.equal(native.sourceTaskIsCurrent(old.rosterNext,at),false);
});
