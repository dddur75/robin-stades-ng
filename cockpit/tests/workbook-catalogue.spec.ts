import {expect,test} from '@playwright/test';
const a={recordId:'workbook:a',candidateId:'catalogue:old',label:'Alice',platform:'Forum',kind:'auteur',sheet:'Catalogue',row:5,sourceUrl:'https://example.org/alice',collectionEnabled:false};
const b={...a,recordId:'workbook:b',label:'Bob',platform:'Autre',sheet:'Profils FR'};
const response={status:'ok',records:[a,b],total:18003,addressCount:18003,profileRows:18003,referenceRows:18375,page:0,limit:25,sheets:['Catalogue','Profils FR','Dépôts'],platforms:['Forum','Autre'],headers:{A:'Pseudo'},receipt:{claimId:'SYNTHETIC.COMPLETE',workbookSha256:'a'.repeat(64)}};

test('catalogue complet recherche côté serveur et conserve le grain',async({page})=>{
 let writes=0;const queries:string[]=[];
 await page.route('**/api/tipsters/workbook?*',r=>{if(r.request().method()!=='GET')writes++;const p=new URL(r.request().url()).searchParams;queries.push(p.toString());return r.fulfill({json:{...response,records:p.get('q')?[b]:[a,b],total:p.get('q')?1:18003}});});
 await page.goto('/expert/catalogue-sources');await expect(page.getByText('18 003 adresses distinctes')).toBeVisible();
 await page.getByLabel('Rechercher dans le classeur').fill('Bob');await expect(page.getByRole('button',{name:'Alice',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'Bob',exact:true})).toBeVisible();
 expect(queries.some(q=>q.includes('q=Bob'))).toBe(true);expect(writes).toBe(0);
});
test('fiche globale conserve champs historiques et lien qualifié',async({page})=>{
 await page.route('**/api/tipsters/workbook?*',r=>{const p=new URL(r.request().url()).searchParams;return r.fulfill({json:{...response,records:[{...b,...(p.get('id')?{fields:{A:'Bob'},qualifiedRecordId:'catalogue:old'}:{})}],total:1}});});
 await page.goto('/expert/catalogue-sources?id=workbook:b');await page.getByText('Champs historiques du classeur').click();await expect(page.getByText('Pseudo',{exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'Consulter la fiche et ses preuves qualifiées'})).toHaveAttribute('href','/expert/tipsters/catalogue%3Aold');
 await expect(page.getByText('Aucune preuve personnelle actuelle',{exact:false})).toBeVisible();
});
test('index absent préserve accès au registre historique mobile',async({page})=>{
 await page.setViewportSize({width:360,height:900});await page.route('**/api/tipsters/workbook?*',r=>r.fulfill({status:503,json:{status:'unavailable'}}));await page.goto('/expert/catalogue-sources');await expect(page.getByRole('alert')).toContainText('indisponible');await expect(page.getByRole('link',{name:'Fiches et preuves Ligue 1'})).toHaveAttribute('href','/expert/catalogue-tipsters');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('la sélection masque immédiatement la liste précédente en attendant sa propre réponse',async({page})=>{
 await page.route('**/api/tipsters/workbook?*',async r=>{const p=new URL(r.request().url()).searchParams;if(p.get('id'))await new Promise(done=>setTimeout(done,400));return r.fulfill({json:{...response,records:p.get('id')?[{...b,fields:{A:'Bob'}}]:[a,b],total:p.get('id')?1:2}});});
 await page.goto('/expert/catalogue-sources');await page.getByRole('button',{name:'Bob',exact:true}).click();await expect(page.getByRole('button',{name:'Alice',exact:true})).toHaveCount(0);await expect(page.getByText('Champs historiques du classeur')).toHaveCount(1);
});

test('un inventaire zéro est affiché seulement avec une mesure et sa propre date',async({page})=>{
 let measured=false;
 await page.route('**/api/tipsters/workbook?*',r=>r.fulfill({json:{...response,records:[{...b,qualification:{label:'Évaluation datée',reason:'Sans mesure',requiredAccess:'À établir',ownerAction:'Qualification',personallyProven:false,observedAt:'2026-11-20T21:00:00Z',...(measured?{nativeFactCount:0,rosterObservedAt:'2026-11-19T10:00:00Z'}:{})}}],total:1}}));
 await page.goto('/expert/catalogue-sources?id=workbook:b');
 await expect(page.getByText('Évaluation datée',{exact:true})).toBeVisible();
 await expect(page.getByText('Inventaire observé le',{exact:false})).toHaveCount(0);
 measured=true;await page.getByRole('button',{name:'Actualiser le catalogue',exact:true}).click();
 await expect(page.getByText('Inventaire observé le',{exact:false})).toContainText('0 fait(s) source');
 await expect(page.getByText('Inventaire observé le',{exact:false})).toContainText('19 novembre 2026');
});
