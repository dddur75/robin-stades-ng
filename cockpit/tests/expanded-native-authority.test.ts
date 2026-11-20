import test from 'node:test';
import assert from 'node:assert/strict';
import {gateSourceOperations} from '../scripts/tipsters-native-state';
const now=Date.parse('2026-11-20T10:00:00Z');
const ready={state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString()};
const disabled={...ready,state:'Disabled',enabled:false};
function data(){return {candidates:[{collectionEnabled:true,qualification:{sourceId:'SRC_014',expansionCampaignId:'ROBIN-OLBG-EXPANDED383717-20261120',expansionAuthorUrl:'https://www.olbg.com/tipsters/tips/383717'}}],enabledCount:1,qualification:{operationalBySource:{SRC_014:true}}};}
test('nouvel auteur indépendant du statut de la tâche Alexmur',()=>{const d=data();gateSourceOperations(d,{state:'unavailable',olbg:disabled,expansion:ready},now);assert.equal(d.candidates[0].collectionEnabled,true);});
test('une tâche Alexmur prête ne peut activer le nouvel auteur désactivé',()=>{const d=data();gateSourceOperations(d,{state:'unavailable',olbg:ready,expansion:disabled},now);assert.equal(d.candidates[0].collectionEnabled,false);});
test('autorité auteur absente, inconnue ou périmée reste fermée',()=>{for(const state of [undefined,{...ready,verifiedAt:new Date(now-31000).toISOString()}]){const d=data();gateSourceOperations(d,{state:'unavailable',olbg:ready,expansion:state},now);assert.equal(d.candidates[0].collectionEnabled,false);}const d=data();d.candidates[0].qualification.expansionCampaignId='unknown';gateSourceOperations(d,{state:'unavailable',olbg:ready,expansion:ready},now);assert.equal(d.candidates[0].collectionEnabled,false);});
