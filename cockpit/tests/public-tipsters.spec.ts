import { expect, test } from '@playwright/test';

const id=`public:${'a'.repeat(64)}`;
const data={status:'ok',schemaVersion:'robin-public-tipsters-v1',distinctPicks:1,authorCount:1,requestCount:3,
 generatedAt:'2026-11-19T09:45:00Z',recurring:false,claimId:'SYNTHETIC.TEST',
 picks:[{id:'p1',authorId:id,authorLabel:'Auteur synthétique',sourceId:'SRC_058',fixtureLabel:'Nice – PSG',market:'correct_score',selection:'1-3',
 kickoff:'2026-11-21T16:15:00Z',observedAt:'2026-11-19T09:34:00Z',publishedCivilDate:'2026-11-18',publishedAt:null,
 sourceUrl:'https://legruppetto.fr/forum/viewtopic.php?t=24850&p=123#p123'}]};
test('les faits publics conduisent à la fiche et à la source sans collecte navigateur',async({page})=>{
 let writes=0;await page.route('**/api/tipsters/public',r=>{if(r.request().method()!=='GET')writes++;return r.fulfill({json:data});});
 await page.goto('/expert/collecte-publique');
 await expect(page.getByText('1 pronostic(s) personnel(s) collecté(s)',{exact:false})).toBeVisible();
 await page.getByRole('link',{name:'Auteur synthétique',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Auteur synthétique',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Voir le message source',exact:true})).toHaveAttribute('href',data.picks[0].sourceUrl);
 await expect(page.getByText('Publication : heure et fuseau non certifiés.',{exact:false})).toBeVisible();
 expect(writes).toBe(0);
});
test('les preuves absentes sont affichées comme indisponibles',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({status:503,json:{status:'unavailable'}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('alert').filter({hasText:'collecte publique'})).toBeVisible();
 await expect(page.getByText('0 pronostic(s)',{exact:false})).toHaveCount(0);
});

for(const width of [360,375,390,430])test(`forums : clavier et largeur ${width}`,async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width,height:900});
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:data}));
 await page.goto('/expert/collecte-publique');
 const link=page.getByRole('link',{name:'Auteur synthétique',exact:true});await link.focus();await expect(link).toBeFocused();
 await expect(page.getByRole('heading',{level:1})).toHaveCount(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(errors).toEqual([]);
});
test('forums : recette partielle, arrêt récurrent et zoom200 restent lisibles',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,recurring:true,halted:true}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('alert').filter({hasText:'Campagne des forums arrêtée'})).toBeVisible();
 await expect(page.getByText('Dossier fidèle en recette partielle.',{exact:true})).toBeVisible();
 await expect(page.getByText('Aucune collecte automatique de ces forums',{exact:false})).toHaveCount(0);
 await page.evaluate(()=>{document.documentElement.style.zoom='2';});
 await expect(page.getByRole('link',{name:'Auteur synthétique',exact:true})).toBeVisible();
});
