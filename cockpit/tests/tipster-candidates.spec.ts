import {expect,test} from '@playwright/test';
const id=`catalogue:${'a'.repeat(64)}`;
const row={id,label:'Alice',platform:'Forum test',sourceUrl:'https://example.org/profile/alice',evidenceUrl:'https://example.org/post/123',declaredLastDate:'2026-10-30',status:'pending_qualification',collectionEnabled:false,origin:{sheet:'Catalogue',row:5,workbookSha256:'b'.repeat(64)}};
const data={status:'ok',schemaVersion:'robin-candidate-registry-v1',count:2,platformCount:2,datedCount:1,candidates:[row,{...row,id:`catalogue:${'c'.repeat(64)}`,label:'Bob',platform:'Autre forum',declaredLastDate:null}],receipt:{registrySha256:'d'.repeat(64),claimId:'SYNTHETIC.TEST'}};
test('annuaire filtrable vers fiche candidate sans activation',async({page})=>{
 let writes=0;await page.route('**/api/tipsters/candidates',r=>{if(r.request().method()!=='GET')writes++;return r.fulfill({json:data});});
 await page.goto('/expert/catalogue-tipsters');
 await expect(page.getByText('2 fiches importées',{exact:true})).toBeVisible();
 await page.getByLabel('Plateforme',{exact:true}).selectOption('Forum test');
 await page.getByLabel('Rechercher une fiche').fill('Alice');
 await expect(page.getByRole('link',{name:'Bob',exact:true})).toHaveCount(0);
 await page.getByRole('link',{name:'Alice',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Alice',exact:true})).toBeVisible();
 await expect(page.getByText('Aucun pronostic collecté n’est attribué à cette fiche par cet import.',{exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Ouvrir la fiche source',exact:true})).toHaveAttribute('href',row.sourceUrl);
 expect(writes).toBe(0);
});
test('filtres vides et indisponibilité restent distincts',async({page})=>{
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:data}));await page.goto('/expert/catalogue-tipsters');
 await page.getByLabel('Rechercher une fiche').fill('inexistant');await expect(page.getByText('Aucune fiche ne correspond à ces filtres.',{exact:true})).toBeVisible();
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({status:503,json:{status:'unavailable'}}));await page.reload();await expect(page.getByRole('alert').filter({hasText:'registre local'})).toBeVisible();
});
for(const width of [360,375,390,430])test(`candidats accessibles à ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:data}));await page.goto('/expert/catalogue-tipsters');
 const input=page.getByLabel('Rechercher une fiche');await input.focus();await expect(input).toBeFocused();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
