import assert from 'node:assert/strict';
import {test} from 'node:test';
import {gateSourceOperations,projectNativeState} from '../scripts/tipsters-native-state';
const now=Date.parse('2026-11-21T19:00:00Z');
const fresh={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
const campaign='ROBIN-SRO-NEXT3-20261121';
const url='https://forum.stade-rennais-online.com/profile.php?id=13380';

test('SRO successor never inherits old source or OLBG native authority',()=>{
 for(const own of [undefined,fresh,{...fresh,verifiedAt:new Date(now-30001).toISOString()}]){
  const row={collectionEnabled:true,qualification:{sourceId:'SRC_039',sroNextCampaignId:campaign,sroNextAuthorUrl:url}};
  const data={enabledCount:1,candidates:[row],qualification:{operationalBySource:{SRC_039:true}}};
  gateSourceOperations(data,{state:'Ready',sro:fresh,rosterNext:fresh,sroNext:own},now);
  assert.equal(row.collectionEnabled,own===fresh);
 }
});

test('SRO successor exact campaign, source and eight native owners are required',()=>{
 for(const q of [
  {sourceId:'SRC_014',sroNextCampaignId:campaign,sroNextAuthorUrl:url},
  {sourceId:'SRC_039',sroNextCampaignId:'OLD',sroNextAuthorUrl:url},
  {sourceId:'SRC_039',sroNextCampaignId:campaign,sroNextAuthorUrl:url+'0'},
  {sourceId:'SRC_039',sroNextCampaignId:campaign,sroNextAuthorUrl:url.replace('https:','http:')},
  {sourceId:'SRC_039',sroNextCampaignId:campaign,sroNextAuthorUrl:undefined},
 ]){
  const row={collectionEnabled:true,qualification:q};
  const data={enabledCount:1,candidates:[row],qualification:{operationalBySource:{SRC_039:true,SRC_014:true}}};
  gateSourceOperations(data,{state:'Ready',sro:fresh,olbg:fresh,sroNext:fresh},now);
  assert.equal(row.collectionEnabled,false);
 }
 for(const owner of [13380,13604,14868,15220,15388,15772,15921,16361]){
  const row={collectionEnabled:true,qualification:{sourceId:'SRC_039',sroNextCampaignId:campaign,sroNextAuthorUrl:'https://forum.stade-rennais-online.com/profile.php?id='+owner}};
  const data={enabledCount:1,candidates:[row],qualification:{sourceOperational:false}};
  gateSourceOperations(data,{state:'Ready',sroNext:fresh},now);
  assert.equal(row.collectionEnabled,true);
  assert.equal(data.qualification.sourceOperational,false);
 }
});

test('missing or stale SRO successor task projects a closed separate child',()=>{
 assert.deepEqual(projectNativeState({state:'checking'},now).sroNext,{state:'checking'});
 assert.deepEqual(projectNativeState({state:'unavailable'},now).sroNext,{state:'unavailable'});
 assert.equal(projectNativeState({state:'Ready',sroNext:{...fresh,verifiedAt:new Date(now-30001).toISOString()}},now).sroNext?.state,'stale');
});

