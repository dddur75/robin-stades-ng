import {expect,test} from "@playwright/test";

test.beforeEach(async({page})=>{
 await page.route('**/api/tipsters/public',r=>r.fulfill({status:503,json:{status:'unavailable'}}));
});

const author=`forecaster:${"a".repeat(64)}`;
const data={status:"ok",schemaVersion:"robin-tipsters-pilot-v1",generatedAt:"2026-11-18T13:00:00Z",
 phase:"closed",source:"Forecast Record",missionId:"synthetic-recurring",startsAt:"2026-11-18T12:00:00Z",expiresAt:"2026-11-18T13:00:00Z",
 requestsMax:24,plannedSlots:2,plannedVisits:6,journalPresent:true,journalHead:"b".repeat(64),counts:{succeeded:2},
 requestCount:12,distinctPicks:1,lastObservationAt:"2026-11-18T12:05:00Z",technicalVerdict:"PASS_AND_HOLD",qualificationVerdict:"PASS_AND_HOLD",dossierVerdict:"PARTIAL",
 fixtures:[{id:"fixture",label:"PSG Lens",kickoff:"2026-11-21T16:15:00Z"}],visits:[],
 tipsters:[{id:author,label:"Attribution synthétique",attributionBasis:"declared",picks:1,fixtureIds:["fixture"],firstSeenAt:"2026-11-18T12:00:00Z",lastSeenAt:"2026-11-18T12:05:00Z"}],
 picks:[{id:"pick",providerId:"provider-pick",fixtureId:"fixture",authorId:author,attributionBasis:"declared",firstSeenAt:"2026-11-18T12:00:00Z",lastSeenAt:"2026-11-18T12:05:00Z",
 versions:[{observedAt:"2026-11-18T12:00:00Z",detectedAt:"2026-11-18T11:00:00Z",publishedAt:null,market:"total",selection:"over",period:"full_time",line:"2.5",odds:"1.85",sourceUrl:"https://www.youtube.com/watch?v=abcdef12345"}]}],
 evidence:{claimId:"SYNTHETIC.TEST",planSha256:"c".repeat(64),journalHeadSha256:"b".repeat(64),method:"synthetic"},
 campaign:{state:"awaiting_authorization",startsAt:"2026-11-19T07:00:00Z",expiresAt:"2026-11-26T07:00:00Z",slots:84,intervalMinutes:120,requestsMax:504,
 authorizationText:"Autorisation synthétique précise de 504 GET, sans achat.",planSha256:"d".repeat(64),manifestSha256:"e".repeat(64)}};

test("vrai parcours de récurrence avec attribution et provenance vidéo complète",async({page})=>{
 let writes=0;
 await page.route("**/api/tipsters/recurring",route=>{if(route.request().method()!=="GET")writes++;return route.fulfill({json:data});});
 await page.goto("/expert/collecte-recurrente?view=tipsters");
 await expect(page.getByText("Deux créneaux validés",{exact:false})).toBeVisible();
 await expect(page.getByText("Campagne prête, en attente de votre autorisation.",{exact:false})).toBeVisible();
 await page.getByRole("link",{name:"Attribution synthétique",exact:true}).click();
 await expect(page.getByText("Première version observée",{exact:true})).toBeVisible();
 await expect(page.getByRole("link",{name:"Consulter la source",exact:true})).toHaveAttribute("href","https://www.youtube.com/watch?v=abcdef12345");
 expect(writes).toBe(0);
});

for(const width of [360,375,390,430])test(`campagne récurrente accessible à ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.route("**/api/tipsters/recurring",r=>r.fulfill({json:data}));
 await page.goto("/expert/collecte-recurrente");
 const button=page.getByRole("button",{name:"Copier l’autorisation précise"});await button.focus();await expect(button).toBeFocused();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test("absence de preuve reste une erreur et ne devient pas une collecte vide réussie",async({page})=>{
 await page.route("**/api/tipsters/recurring",r=>r.fulfill({status:503,json:{status:"unavailable",message:"Preuve absente"}}));
 await page.goto("/expert/collecte-recurrente");
 await expect(page.getByRole("alert").filter({hasText:"Preuve absente"})).toBeVisible();
 await expect(page.getByRole("button",{name:"Copier l’autorisation précise"})).toHaveCount(0);
});


test("zéro personnel reste partiel malgré deux créneaux réseau réussis",async({page})=>{
 await page.route("**/api/tipsters/recurring",r=>r.fulfill({json:{...data,distinctPicks:0,tipsters:[],picks:[],technicalVerdict:"PARTIAL",qualificationVerdict:"PARTIAL",transportVerdict:"PASS_AND_HOLD",unresolvedAttributions:7}}));
 await page.goto("/expert/collecte-recurrente");
 await expect(page.getByText("0 pronostic(s) personnel(s) qualifié(s)",{exact:false})).toBeVisible();
 await expect(page.getByText("7 sélection(s) historique(s) exclue(s)",{exact:false})).toBeVisible();
 await expect(page.getByText("Recette du canari : Partielle.",{exact:false})).toBeVisible();
 await expect(page.getByText("Sur 2 créneaux prévus",{exact:true})).toBeVisible();
 await expect(page.getByText("2 vérifications robots.txt",{exact:false})).toHaveCount(0);
 await expect(page.getByRole("columnheader",{name:"Rencontre",exact:true})).toHaveCount(0);
});
for (const state of ["invalid_package","expired"]) test(`campagne ${state} ne propose aucune autorisation`,async({page})=>{
 await page.route("**/api/tipsters/recurring",r=>r.fulfill({json:{...data,campaign:{...data.campaign,state,authorizationText:null}}}));
 await page.goto("/expert/collecte-recurrente");
 await expect(page.getByText(state==="expired" ? "Campagne expirée" : "Paquet invalide",{exact:false})).toBeVisible();
 await expect(page.getByRole("button",{name:"Copier l’autorisation précise"})).toHaveCount(0);
});

test("arrêt de sécurité reste visible même si l’autorisation existe",async({page})=>{
 await page.route("**/api/tipsters/recurring",r=>r.fulfill({json:{...data,halted:true,distinctPicks:0,tipsters:[],picks:[],technicalVerdict:"PARTIAL",qualificationVerdict:"PARTIAL",campaign:{...data.campaign,state:"authorized",authorizationText:null}}}));
 await page.goto("/expert/collecte-recurrente");
 await expect(page.getByRole("alert").filter({hasText:"Campagne arrêtée"})).toBeVisible();
 await expect(page.getByText("Aucune nouvelle requête ne sera exécutée",{exact:false})).toBeVisible();
 await expect(page.getByRole("button",{name:"Copier l’autorisation précise"})).toHaveCount(0);
});

const clock=new Date('2026-11-20T01:30:00Z');
const publicCampaign={state:'collecting',successfulSlots:1,requests:3,requestsMax:36,expiresAt:'2026-11-21T07:00:00Z',
 native:{state:'Ready',enabled:true,verifiedAt:clock.toISOString(),nextRunTime:'2026-11-20T07:00:00Z'}};
const publicSnapshot={status:'ok',schemaVersion:'robin-public-tipsters-v1',distinctPicks:2,authorCount:1,
 requestCount:22,generatedAt:clock.toISOString(),claimId:'SYNTHETIC.TEST',picks:[],
 campaign:{...publicCampaign,state:'collecting',successfulSlots:0,requests:1,requestsMax:72},
 sroCampaign:{...publicCampaign,requests:6,requestsMax:39},
 olbgCampaign:{...publicCampaign,native:{...publicCampaign.native,state:'Disabled',enabled:false}}};

test('la page récurrente garde les campagnes publiques visibles si Forecast échoue',async({page})=>{
 await page.clock.install({time:clock});
 let writes=0;page.on('request',r=>{if(r.url().includes('/api/tipsters/')&&r.method()!=='GET')writes++;});
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:publicSnapshot}));
 await page.route('**/api/tipsters/recurring',r=>r.fulfill({status:503,json:{status:'unavailable',message:'Forecast indisponible'}}));
 await page.goto('/expert/collecte-recurrente');
 await expect(page.getByRole('heading',{level:1,name:'Collecte récurrente'})).toBeVisible();
 await expect(page.getByRole('heading',{level:1})).toHaveCount(1);
 await expect(page.getByText('2 pronostic(s) personnel(s) collecté(s)',{exact:false})).toBeVisible();
 const forums=page.locator('.section-card').filter({has:page.getByRole('heading',{name:'Campagne des deux forums',exact:true})}).last();
 await expect(forums.getByText('0 créneau(x) validé(s) · 1 GET réservés sur 72 maximum.',{exact:true})).toBeVisible();
 const sro=page.locator('.section-card').filter({has:page.getByRole('heading',{name:'Collecte Stade Rennais Online',exact:true})}).last();
 await expect(sro.getByText('Programmation confirmée par Windows.',{exact:true})).toBeVisible();
 await expect(sro.getByText('Prochain créneau Windows :',{exact:false})).toBeVisible();
 const olbg=page.locator('.section-card').filter({has:page.getByRole('heading',{name:'Collecte OLBG · profil 648433',exact:true})}).last();
 await expect(olbg.getByText('Tâche Windows désactivée.',{exact:true})).toBeVisible();
 await expect(olbg.getByText('Programmation confirmée par Windows.',{exact:true})).toHaveCount(0);
 await page.getByRole('link',{name:'Voir les fiches et les pronostics collectés',exact:true}).focus();
 expect(writes).toBe(0);
});

test('la confirmation Windows expire localement malgré une réponse ancienne répétée',async({page})=>{
 await page.clock.install({time:clock});
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:publicSnapshot}));
 await page.route('**/api/tipsters/recurring',r=>r.fulfill({json:data}));
 await page.goto('/expert/collecte-recurrente');
 await expect(page.getByText('Programmation confirmée par Windows.',{exact:true})).toHaveCount(2);
 await page.clock.fastForward(31_000);
 await expect(page.getByText('Programmation confirmée par Windows.',{exact:true})).toHaveCount(0);
 await expect(page.getByText('Prochain créneau Windows :',{exact:false})).toHaveCount(0);
 await expect(page.getByText('Confirmation Windows à actualiser.',{exact:true})).toHaveCount(3);
});

test('sans prochain créneau ou compteurs prouvés la page ne promet ni lecture ni faux zéro',async({page})=>{
 await page.clock.install({time:clock});
 const snapshot={...publicSnapshot,campaign:{...publicCampaign,native:{...publicCampaign.native,nextRunTime:undefined}},
  sroCampaign:{state:'invalid_package'},olbgCampaign:{...publicCampaign,native:{...publicCampaign.native,verifiedAt:'date illisible'}}};
 await page.route('**/api/tipsters/public',r=>r.fulfill({json:snapshot}));
 await page.route('**/api/tipsters/recurring',r=>r.fulfill({json:data}));
 await page.goto('/expert/collecte-recurrente');
 await expect(page.getByText('Tâche Windows prête ; aucun prochain créneau confirmé.',{exact:true})).toBeVisible();
 await expect(page.getByText('Programmation confirmée par Windows.',{exact:true})).toHaveCount(0);
 await expect(page.getByText('Compteurs indisponibles : preuves de campagne incomplètes.',{exact:true})).toBeVisible();
 await expect(page.getByText('0 créneau(x) validé(s) · 0 GET réservés',{exact:false})).toHaveCount(0);
 await expect(page.getByText('Confirmation Windows à actualiser.',{exact:true})).toBeVisible();
});
