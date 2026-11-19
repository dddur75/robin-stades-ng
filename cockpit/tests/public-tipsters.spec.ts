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

test('SRO links use a typed forum route and preserve stored author hashes',async({page})=>{
 const bare='b'.repeat(64);const p={...data.picks[0],authorId:bare,authorLabel:'SRO synthétique',sourceId:'SRC_039'};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[p]}}));await page.goto('/expert/collecte-publique');
 const link=page.getByRole('link',{name:'SRO synthétique',exact:true});await expect(link).toHaveAttribute('href','/expert/tipsters/'+encodeURIComponent('forum:'+bare));await link.click();await expect(page.getByRole('heading',{name:'SRO synthétique',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Nice – PSG · score prévu 1-3',exact:true})).toBeVisible();
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

test('campagne programmée conserve les faits ponctuels sans prétendre une exécution',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,campaign:{state:'scheduled',startsAt:'2026-11-20T07:00:00Z',expiresAt:'2026-11-21T07:00:00Z',slots:12,requests:0,requestsMax:72,successfulSlots:0,native:{state:'Ready'}}}}));
 await page.goto('/expert/collecte-publique');await expect(page.getByText('Programmée : premier lancement',{exact:false})).toBeVisible();await expect(page.getByText('0 créneau(x) validé(s)',{exact:false})).toBeVisible();await expect(page.getByText('Aucune collecte automatique de ces forums',{exact:false})).toHaveCount(0);
});

test('SRO affiche son canari et son budget distinct du lot initial',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,recurring:true,sroCampaign:{state:'collecting',successfulSlots:1,requests:3,requestsMax:39,native:{state:'Ready',verifiedAt:'2026-11-19T15:00:00Z'}}}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('heading',{name:'Collecte Stade Rennais Online',exact:true})).toBeVisible();
 await expect(page.getByText('1 créneau(x) validé(s) · 3 GET réservés sur 39 maximum.',{exact:true})).toBeVisible();
 await expect(page.getByText('1 pronostic(s) personnel(s) collecté(s)',{exact:false})).toBeVisible();
});

test('OLBG preserves native choices and unknown publication without inventing scores',async({page})=>{
 const native={...data.picks[0],id:'olbg-tip:123',authorId:'olbg:648433',authorLabel:'Alexmur',sourceId:'SRC_014',market:'source_native',selection:'PSG',publishedCivilDate:null,sourceUrl:'https://www.olbg.com/tipsters/tips/648433'};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,distinctPicks:2,authorCount:2,picks:[...data.picks,native],olbgCampaign:{state:'collecting',successfulSlots:1,requests:3,requestsMax:36,native:{state:'Disabled'}}}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('heading',{name:'Nice – PSG · Choix publié (Win) : PSG',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Nice – PSG · score prévu 1-3',exact:true})).toBeVisible();
 await expect(page.getByText('Date civile affichée : non renseignée.',{exact:false})).toBeVisible();
 await expect(page.getByText('Marché normalisé et durée de jeu non certifiés.',{exact:false})).toBeVisible();
 await expect(page.getByText('score prévu PSG',{exact:false})).toHaveCount(0);
 await expect(page.getByText('État Windows : Disabled.',{exact:false})).toBeVisible();
 await page.getByRole('link',{name:'Alexmur',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Alexmur',exact:true})).toBeVisible();
 await expect(page.getByText('Historique de la collecte des forums',{exact:false})).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'Nice – PSG · Choix publié (Win) : PSG',exact:true})).toBeVisible();
});
