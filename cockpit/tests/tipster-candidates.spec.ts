import {expect,test} from '@playwright/test';
const id=`catalogue:${'a'.repeat(64)}`;
const row={id,label:'Alice',platform:'Forum test',sourceUrl:'https://example.org/profile/alice',evidenceUrl:'https://example.org/post/123',declaredLastDate:'2026-10-30',status:'pending_qualification',collectionEnabled:false,origin:{sheet:'Catalogue',row:5,workbookSha256:'b'.repeat(64)}};
const data={status:'ok',schemaVersion:'robin-candidate-registry-v1',count:2,platformCount:2,datedCount:1,candidates:[row,{...row,id:`catalogue:${'c'.repeat(64)}`,label:'Bob',platform:'Autre forum',declaredLastDate:null}],receipt:{registrySha256:'d'.repeat(64),claimId:'SYNTHETIC.TEST'}};

test('un lot complémentaire indisponible est signalé sans effacer le registre',async({page})=>{
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...data,qualification:{status:'ok',assessedCount:2,qualifiedCount:0,rosterCollectionState:'unavailable'}}}));
 await page.goto('/expert/catalogue-tipsters');
 await expect(page.getByRole('alert')).toContainText('Une partie de la qualification complémentaire');
 await expect(page.getByText('2 fiches importées',{exact:true})).toBeVisible();
});

test('opaque choices in candidate files preserve their literal market',async({page})=>{
 const access={platform:'OLBG',label:'Choix personnels observés avant match',reason:'Profil prouvé',requiredAccess:'Aucun compte',ownerAction:'Usage privé',url:'https://www.olbg.com/',scope:'one_profile'};
 const choice={id:'opaque',market:'source_native_opaque',fixtureLabel:'Troyes – Le Havre',selection:'Troyes (AH) -0.25',sourceMarketLabel:'Asian Hcap',sourceBetType:'Win',sourceFields:{hcap:'-0.25'},observedAt:'2026-11-20T19:01:57Z',kickoff:'2026-11-20T19:45:00Z',sourceUrl:'https://www.olbg.com/tipsters/tips/158'};
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...data,candidates:[{...row,qualification:{...access,profileVisited:true,documentaryIssues:[],personallyProven:true,picks:[choice]}}]}}));
 await page.goto(`/expert/tipsters/${encodeURIComponent(id)}`);
 await expect(page.getByRole('heading',{name:'Troyes – Le Havre · Choix publié (marché source non interprété) : Troyes (AH) -0.25',exact:true})).toBeVisible();
 await expect(page.getByText('Marché source : Asian Hcap · type source : Win · handicap source : -0.25.',{exact:true})).toBeVisible();
 await expect(page.getByText('Règlement et évaluation de performance désactivés.',{exact:false})).toBeVisible();
 await expect(page.getByText('score prévu Troyes',{exact:false})).toHaveCount(0);
});

test('native personal choices in candidate files retain their source type',async({page})=>{
 const access={platform:'OLBG',label:'Choix personnels observés avant match',reason:'Profil prouvé',requiredAccess:'Aucun compte',ownerAction:'Usage privé',url:'https://www.olbg.com/',scope:'one_profile'};
 const choice={id:'native',market:'source_native',fixtureLabel:'Nice – PSG',selection:'PSG',observedAt:'2026-11-19T18:00:00Z',kickoff:'2026-11-21T16:15:00Z',sourceUrl:'https://www.olbg.com/tipsters/tips/648433'};
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...data,candidates:[{...row,qualification:{...access,profileVisited:true,documentaryIssues:[],personallyProven:true,picks:[choice]}}]}}));
 await page.goto(`/expert/tipsters/${encodeURIComponent(id)}`);
 await expect(page.getByRole('heading',{name:'Nice – PSG · Choix publié (Win) : PSG',exact:true})).toBeVisible();
 await expect(page.getByText('score prévu PSG',{exact:false})).toHaveCount(0);
 await expect(page.getByText('évaluation de performance désactivée.',{exact:false})).toBeVisible();
});
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

test('qualification personnelle rejoint la fiche sans qualifier les autres',async({page})=>{
 const access={platform:'Forum test',label:'Accès public vérifié',reason:'Sujet courant contrôlé',requiredAccess:'Aucun compte pour ce sujet',ownerAction:'Campagne personnelle bornée',url:'https://example.org/',scope:'platform_only'};
 const choice={id:'synthetic-pick',fixtureLabel:'Nice – PSG',selection:'1-3',observedAt:'2026-11-19T14:00:00Z',kickoff:'2026-11-21T16:15:00Z',sourceUrl:'https://example.org/post/123'};
 const active={...data,enabledCount:1,qualification:{status:'ok',assessedCount:2,qualifiedCount:1,claimId:'SYNTHETIC.QUALIFICATION',platforms:[access]},candidates:[{...row,collectionEnabled:true,qualification:{...access,label:'Choix personnels observés avant match',profileVisited:false,documentaryIssues:[],personallyProven:true,picks:[choice]}},data.candidates[1]]};
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:active}));
 await page.goto('/expert/catalogue-tipsters');await expect(page.getByText('2 fiches examinées : 1 avec des choix personnels',{exact:false})).toBeVisible();
 await page.getByRole('link',{name:'Alice',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Nice – PSG · score prévu 1-3',exact:true})).toBeVisible();
 await expect(page.getByText('Collecte autorisée dans la campagne',{exact:false})).toBeVisible();
 await expect(page.getByText('Aucun pronostic collecté n’est attribué à cette fiche par cet import.',{exact:true})).toHaveCount(0);
});

test('blocages et geste précis sont consultables au clavier sur mobile',async({page})=>{
 await page.setViewportSize({width:390,height:850});
 const access={platform:'Forum test',label:'Accès refusé',reason:'HTTP403 observé',requiredAccess:'Flux officiel autorisé',ownerAction:'Aucun mot de passe à transmettre',url:'https://example.org/',scope:'platform_only'};
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...data,qualification:{status:'ok',assessedCount:2,qualifiedCount:0,platforms:[access]}}}));
 await page.goto('/expert/catalogue-tipsters');const detail=page.getByText('Accès et blocages par plateforme',{exact:true});await detail.focus();await page.keyboard.press('Enter');
 await expect(page.getByText('Accès à établir : Flux officiel autorisé',{exact:true})).toBeVisible();
 await expect(page.getByText('Aucun mot de passe à transmettre',{exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('une erreur de lecture se rétablit au prochain rafraîchissement local',async({page})=>{
 await page.clock.install();let reads=0;
 await page.route('**/api/tipsters/candidates',r=>++reads===1?r.fulfill({status:503,json:{status:'unavailable'}}):r.fulfill({json:data}));
 await page.goto('/expert/catalogue-tipsters');
 await expect(page.getByRole('alert').filter({hasText:'registre local'})).toBeVisible();
 await page.clock.fastForward(15000);
 await expect(page.getByText('2 fiches importées',{exact:true})).toBeVisible();
 await expect(page.getByRole('alert').filter({hasText:'registre local'})).toHaveCount(0);
});

const oldClaim='ENG.SOURCE_OBSERVATORY.PUBLIC.TECHNICAL.ACCESS.20261119';
const newClaim='ENG.SOURCE_OBSERVATORY.NT.QUALIFICATION.20261120';
const ntAccess={platform:'NotBetting',label:'Conditions non établies',reason:'Vue juridique incomplète ; aucun profil lu dans cette mission.',requiredAccess:'Conditions officielles lisibles et flux autorisé avant match.',ownerAction:'Aucun compte ou achat indispensable démontré.',url:'https://notbetting.com/en/terms',scope:'platform_rights_only'};
const nt={...data,enabledCount:0,qualification:{status:'ok',assessedCount:2,qualifiedCount:0,claimId:'SYNTHETIC.QUALIFICATION',technicalClaimId:oldClaim,technicalClaimIds:[oldClaim,newClaim],followupOverlayState:'ok',platforms:[ntAccess,{...ntAccess,platform:'Telegram',label:'Droits IA à établir',reason:'Les six canaux restent fermés avant lecture des messages.',requiredAccess:'Permission expresse et droits des contenus.'}]},candidates:[{...row,platform:'NotBetting',qualification:{...ntAccess,profileVisited:true,personallyProven:false,picks:[],documentaryIssues:[]}}]};

test('qualification N/T affiche les deux preuves et la fiche reste désactivée',async({page})=>{
 let writes=0;await page.setViewportSize({width:360,height:900});
 await page.route('**/api/tipsters/candidates',r=>{if(r.request().method()!=='GET')writes++;return r.fulfill({json:nt});});
 await page.goto('/expert/catalogue-tipsters');await page.getByText('Accès et blocages par plateforme',{exact:true}).click();
 await expect(page.getByText('Permission expresse et droits des contenus.',{exact:false})).toBeVisible();
 await expect(page.getByText(oldClaim,{exact:false})).toBeVisible();await expect(page.getByText(newClaim,{exact:false})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('link',{name:'Alice',exact:true}).click();
 await expect(page.getByText('Collecte désactivée',{exact:false})).toBeVisible();
 await expect(page.getByText('Route de profil déjà visitée dans l’historique des contrôles.',{exact:true})).toBeVisible();
 await expect(page.getByText('Aucun choix personnel admissible',{exact:false})).toBeVisible();expect(writes).toBe(0);
});

test('mise à jour absente conserve les évaluations précédentes avec un avertissement',async({page})=>{
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...nt,qualification:{...nt.qualification,technicalClaimIds:[oldClaim],followupOverlayState:'unavailable'}}}));
 await page.goto('/expert/catalogue-tipsters');
 await expect(page.getByRole('alert').filter({hasText:'actualisation NotBetting et Telegram'})).toBeVisible();
 await expect(page.getByText('2 fiches importées',{exact:true})).toBeVisible();
 await page.getByText('Accès et blocages par plateforme',{exact:true}).click();
 await expect(page.getByText(oldClaim,{exact:false})).toBeVisible();await expect(page.getByText(newClaim,{exact:false})).toHaveCount(0);
});

test('qualification personnelle absente conserve les faits et affiche le repli',async({page})=>{
 await page.route('**/api/tipsters/candidates',r=>r.fulfill({json:{...nt,qualification:{...nt.qualification,personalOverlayState:'unavailable',personalCollectionState:'unavailable'}}}));
 await page.goto('/expert/catalogue-tipsters');
 await expect(page.getByRole('alert').filter({hasText:'qualification personnelle'})).toBeVisible();
 await expect(page.getByText('2 fiches importées',{exact:true})).toBeVisible();
 await page.getByText('Accès et blocages par plateforme',{exact:true}).click();
 await expect(page.getByText(oldClaim,{exact:false})).toBeVisible();
});
