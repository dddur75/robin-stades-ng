import { expect, test } from '@playwright/test';

const id=`public:${'a'.repeat(64)}`;
const data={status:'ok',schemaVersion:'robin-public-tipsters-v1',distinctPicks:1,authorCount:1,requestCount:3,
 generatedAt:'2026-11-19T09:45:00Z',recurring:false,claimId:'SYNTHETIC.TEST',
 picks:[{id:'p1',authorId:id,authorLabel:'Auteur synthétique',sourceId:'SRC_058',fixtureLabel:'Nice – PSG',market:'correct_score',selection:'1-3',
 kickoff:'2026-11-21T16:15:00Z',observedAt:'2026-11-19T09:34:00Z',publishedCivilDate:'2026-11-18',publishedAt:null,
 sourceUrl:'https://legruppetto.fr/forum/viewtopic.php?t=24850&p=123#p123'}]};

test('un lot de profils indisponible garde les choix antérieurs avec une alerte',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,rosterCollection:{state:'unavailable'}}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('alert')).toContainText('Une partie des preuves individuelles');
 await expect(page.getByRole('link',{name:'Auteur synthétique',exact:true})).toBeVisible();
});

test('un auteur hors registre affiche sa propre campagne de groupe et son canari distinct',async({page})=>{
 const now='2026-11-20T22:15:00Z';await page.clock.install({time:new Date(now)});
 const author='olbg:669101';const choice={...data.picks[0],authorId:author,authorLabel:'OliverL',sourceId:'SRC_014',market:'source_native'};
 const campaign={state:'collecting',campaignId:'ROBIN-OLBG-ROSTER42-E2V2-20261120',authorIds:[author],profileCount:42,successfulSlots:1,requests:4,requestsMax:133,startsAt:'2026-11-20T23:05:00Z',expiresAt:'2026-11-21T11:15:00Z',native:{state:'Ready',enabled:true,verifiedAt:now,nextRunTime:'2026-11-20T23:05:00Z'}};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[choice],rosterCampaign:campaign}}));
 await page.goto('/expert/tipsters/olbg%3A669101');
 await expect(page.getByRole('heading',{name:'Collecte du groupe OLBG · 42 profils',exact:true})).toBeVisible();
 await expect(page.getByText('Canari vérifié sur trois auteurs.',{exact:false})).toBeVisible();
 await expect(page.getByText('Prochain créneau Windows :',{exact:false})).toContainText('00 h 05');
 await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 669088',exact:true})).toHaveCount(0);
});

test('un reçu de groupe indisponible ne fabrique ni42profils ni canari réussi',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,rosterCampaign:{state:'unavailable'}}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('heading',{name:'Collecte du groupe OLBG',exact:true})).toBeVisible();
 await expect(page.getByText('Preuves du groupe indisponibles',{exact:false})).toBeVisible();
 await expect(page.getByText('Canari vérifié sur trois auteurs.',{exact:false})).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'Collecte du groupe OLBG · 42 profils',exact:true})).toHaveCount(0);
});

test('opaque choices show source literals without a score or performance interpretation',async({page})=>{
 await page.setViewportSize({width:360,height:900});
 const choice={...data.picks[0],market:'source_native_opaque',selection:'Under 2.50',sourceMarketLabel:'Total Goals',sourceBetType:'Win',sourceFields:{hcap:'2.50'},performanceEvaluationAllowed:false,settlementAllowed:false};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[choice]}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('heading',{name:'Nice – PSG · Choix publié (marché source non interprété) : Under 2.50',exact:true})).toBeVisible();
 await expect(page.getByText('Marché source : Total Goals · type source : Win · handicap source : 2.50.',{exact:true})).toBeVisible();
 await expect(page.getByText('Règlement et évaluation de performance désactivés.',{exact:false})).toBeVisible();
 await expect(page.getByText('score prévu Under',{exact:false})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('hepter shows its exact campaign without borrowing another author task',async({page})=>{
 const now='2026-11-20T20:00:00Z';await page.clock.install({time:new Date(now)});
 const choice={...data.picks[0],authorId:'olbg:669088',authorLabel:'Hepter',sourceId:'SRC_014',market:'source_native'};
 const campaign={state:'collecting',successfulSlots:1,requests:2,requestsMax:18,slots:9,startsAt:'2026-11-20T21:00:00Z',expiresAt:'2026-11-21T11:15:00Z',native:{state:'Ready',enabled:true,verifiedAt:now,nextRunTime:'2026-11-20T21:00:00Z'}};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[choice],profileCampaign:campaign}}));
 await page.goto('/expert/tipsters/olbg%3A669088');
 await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 669088',exact:true})).toBeVisible();
 await expect(page.getByText('1 créneau(x) validé(s) · 2 GET réservés sur 18 maximum.',{exact:true})).toBeVisible();
 await expect(page.getByText('Prochain créneau Windows :',{exact:false})).toContainText('22 h 00');
 await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 648433',exact:true})).toHaveCount(0);
});

test('observations du catalogue et qualification complémentaire ont deux dates distinctes',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,generatedAt:'2026-11-20T16:22:00Z',sourceObservedThrough:'2026-11-20T15:00:00Z',personalCollection:{state:'historical_observations_qualified',qualifiedAt:'2026-11-20T16:22:00Z'}}}));
 await page.goto('/expert/collecte-publique');
 const dates=page.getByText('Dernière observation du catalogue :',{exact:false});
 await expect(dates).toContainText('16 h 00');await expect(dates).toContainText('17 h 22');
 await page.getByRole('link',{name:'Auteur synthétique',exact:true}).click();
 await expect(page.getByText('Dernière observation du catalogue :',{exact:false})).toBeVisible();
});

test('complément personnel indisponible garde les faits antérieurs avec un avertissement',async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,personalCollection:{state:'unavailable'}}}));
 await page.goto('/expert/collecte-publique');
 await expect(page.getByRole('alert').filter({hasText:'preuves personnelles complémentaires'})).toBeVisible();
 await expect(page.getByText('1 pronostic(s) personnel(s) collecté(s)',{exact:false})).toBeVisible();
});
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

test('les profils OLBG ont des campagnes natives distinctes',async({page})=>{
 const now='2026-11-20T10:00:00Z';await page.clock.install({time:new Date(now)});const choice={...data.picks[0],authorId:'olbg:383717',authorLabel:'Auteur supplémentaire',sourceId:'SRC_014',market:'source_native',sourceUrl:'https://www.olbg.com/tipsters/tips/383717'};
 const alex={state:'collecting',requests:9,requestsMax:36,successfulSlots:3,slots:12,expiresAt:'2026-11-21T07:00:00Z',native:{state:'Ready',enabled:true,verifiedAt:now}};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[choice],olbgCampaign:alex}}));
 await page.goto('/expert/tipsters/olbg%3A383717');await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 648433'})).toHaveCount(0);await expect(page.getByText('Ce profil dispose d’une preuve ponctuelle.',{exact:false})).toBeVisible();
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,picks:[choice],olbgCampaign:alex,expandedOlbgCampaign:{state:'collecting',requests:3,requestsMax:9,successfulSlots:1,slots:3,expiresAt:'2026-11-20T15:15:00Z',native:{state:'Disabled',enabled:false,verifiedAt:now}}}}));await page.reload();await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 383717'})).toBeVisible();await expect(page.getByRole('heading',{name:'Collecte OLBG · profil 648433'})).toHaveCount(0);await expect(page.getByText('Tâche Windows désactivée.',{exact:false})).toBeVisible();
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
 const now=Date.now();
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:{...data,campaign:{state:'scheduled',startsAt:new Date(now+3600000).toISOString(),expiresAt:new Date(now+86400000).toISOString(),slots:12,requests:0,requestsMax:72,successfulSlots:0,native:{state:'Ready',enabled:true,verifiedAt:new Date(now).toISOString(),nextRunTime:new Date(now+3600000).toISOString()}}}}));
 await page.goto('/expert/collecte-publique');await expect(page.getByText('Programmation confirmée par Windows.',{exact:true})).toBeVisible();await expect(page.getByText('0 créneau(x) validé(s)',{exact:false})).toBeVisible();await expect(page.getByText('Aucune collecte automatique de ces forums',{exact:false})).toHaveCount(0);
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
