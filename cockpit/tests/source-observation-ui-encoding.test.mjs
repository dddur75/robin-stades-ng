import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const cases=[['workbook-catalogue.tsx',['État actuel de collecte non vérifié','Référence inventoriée, qualification individuelle à établir','Évaluation historique conservée']],['tipster-candidates.tsx',['À qualifier','Aucun choix personnel admissible n’est établi pour cette fiche.','Évaluation historique conservée']]];
for(const [name,labels]of cases){const source=readFileSync(new URL('../app/components/expert/'+name,import.meta.url),'utf8');assert.equal(!source.includes('\u00c3')&&!source.includes('\ufffd')&&labels.every(label=>source.includes(label)),true,'UTF8 original labels preserved: '+name);}
console.log('2 UTF8 regression assertions PASS');
