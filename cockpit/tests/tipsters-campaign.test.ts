import assert from 'node:assert/strict';
import {test} from 'node:test';
import {campaignPresentation, type PublicCampaign} from '../app/lib/tipsters-campaign';

const now=Date.parse('2026-11-20T01:30:00Z');
const campaign:PublicCampaign={state:'collecting',successfulSlots:1,expiresAt:'2026-11-21T07:00:00Z',
 native:{state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString(),nextRunTime:'2026-11-20T08:00:00+01:00'}};

test('verified historical canary remains separate from the future native schedule',()=>{
 const value=campaignPresentation(campaign,now);
 assert.equal(value.kind,'scheduled');assert.equal(value.nextAt,campaign.native!.nextRunTime);
 assert.equal(campaignPresentation({...campaign,successfulSlots:0,requests:1},now).kind,'scheduled');
});
test('disabled missing stale future or unverified native tasks cannot attest scheduling',()=>{
 for(const native of [undefined,{state:'Ready'},{...campaign.native!,enabled:false},
  {...campaign.native!,state:'Disabled'},{...campaign.native!,verifiedAt:new Date(now-30001).toISOString()},
  {...campaign.native!,verifiedAt:new Date(now+1).toISOString()}]){
  const value=campaignPresentation({...campaign,native},now);
  assert.notEqual(value.kind,'scheduled');assert.equal(value.nextAt,null);
 }
 assert.equal(campaignPresentation({...campaign,native:{...campaign.native!,state:'stale',enabled:false,verifiedAt:new Date(now-60000).toISOString()}},now).kind,'unknown');
});
test('stop package and mission expiry override native task readiness',()=>{
 for(const state of ['halted','invalid_package','blocked_lock','expired']){
  const value=campaignPresentation({...campaign,state},now);assert.equal(value.kind,state);assert.equal(value.nextAt,null);
 }
 assert.equal(campaignPresentation({...campaign,expiresAt:new Date(now).toISOString()},now).kind,'expired');
 assert.equal(campaignPresentation({...campaign,expiresAt:undefined},now).kind,'unknown');
});
test('next run must be a valid future instant within the finite mission',()=>{
 for(const nextRunTime of ['invalid',new Date(now-1).toISOString(),campaign.expiresAt!,'2026-11-22T00:00:00Z']){
  const value=campaignPresentation({...campaign,native:{...campaign.native!,nextRunTime}},now);
  assert.equal(value.nextAt,null);assert.equal(value.kind,'ready');
 }
 assert.equal(campaignPresentation({...campaign,startsAt:'2026-11-20T08:00:00Z'},now).kind,'ready');
 assert.equal(campaignPresentation({...campaign,native:{...campaign.native!,state:'Running'}},now).kind,'running');
});
