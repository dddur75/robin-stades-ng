import test from 'node:test';
import assert from 'node:assert/strict';
import {decorateInventory} from '../scripts/workbook-inventory-state';
const person={recordId:'person',candidateId:'same-url',sheet:'Catalogue',row:5,platform:'Forum',collectionEnabled:false};
const platform={...person,recordId:'platform',sheet:'Plateformes'};
const legacy={status:'ok',candidates:[{id:'same-url',origin:{sheet:'Catalogue',row:5},collectionEnabled:true,qualification:{personallyProven:true}}],qualification:{status:'ok',qualifiedCount:1,platforms:[]}};
test('une URL exemple de plateforme ne devient pas une personne qualifiée',()=>{
 const result=decorateInventory({records:[person,platform]},legacy,'2026-11-20T10:00:00Z');
 assert.equal(result.records[0].collectionEnabled,true);assert.equal(result.records[1].collectionEnabled,false);assert.equal(result.records[1].qualifiedRecordId,undefined);assert.equal(result.records[1].qualification,undefined);
 assert.equal(result.readAt,'2026-11-20T10:00:00Z');
});
test('qualification absente reste inconnue malgré registre documentaire valide',()=>{
 const result=decorateInventory({records:[person],qualifiedCount:99},{...legacy,qualification:{status:'unavailable'}},'2026-11-20T10:00:00Z');
 assert.equal(result.qualifiedRegistryState,'unavailable');assert.equal(result.qualifiedCount,undefined);assert.equal(result.records[0].collectionEnabled,false);assert.equal(result.records[0].qualification,undefined);assert.equal(result.records[0].qualifiedRecordId,'same-url');
});
