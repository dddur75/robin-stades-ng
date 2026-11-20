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

test('nouvelle qualification indisponible conserve la provenance et signale le repli',()=>{
 const value={...legacy,qualification:{...legacy.qualification,personalOverlayState:'ok',compatibleAccessState:'unavailable'}};
 const result=decorateInventory({records:[person]},value,'2026-11-20T20:00:00Z');
 assert.equal(result.personalAccessState,'unavailable');
 assert.deepEqual(result.records[0].qualification,legacy.candidates[0].qualification);
});
test('la règle Kicktipp est propre au concours de la référence',()=>{
 const generic={platform:'Kicktipp',label:'Règles par concours',reason:'Non établi',requiredAccess:'Règles du concours',ownerAction:'Qualification technique'};
 const known={...generic,label:'Masqués',requiredAccess:'Export prospectif pour ce concours'};
 const legacy={status:'ok',candidates:[],qualification:{status:'ok',qualifiedCount:0,platforms:[{...generic,contestAssessments:{'pronostics-ligue1':known}}]}};
 const records=[{recordId:'de',sheet:'Catalogue',row:100,platform:'Kicktipp',sourceUrl:'https://www.kicktipp.de/bundesliga-tippspiel/tippuebersicht',collectionEnabled:false},{recordId:'fr',sheet:'Catalogue',row:101,platform:'Kicktipp',sourceUrl:'https://www.kicktipp.fr/pronostics-ligue1/tippuebersicht',collectionEnabled:false}];
 const result=decorateInventory({records},legacy,'2026-11-20T16:00:00Z');
 assert.equal(result.records[0].platformAssessment?.requiredAccess,'Règles du concours');
 assert.equal(result.records[1].platformAssessment?.requiredAccess,'Export prospectif pour ce concours');
 assert(result.records.every(r=>r.collectionEnabled===false));
});
