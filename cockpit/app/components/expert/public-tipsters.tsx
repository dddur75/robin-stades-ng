"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";

type Pick = { id:string; authorId:string; authorLabel:string; sourceId:string; fixtureLabel:string;
 selection:string; market?:string; kickoff:string; observedAt:string; publishedCivilDate:string|null; sourceUrl:string };
type State = { status:string; distinctPicks:number; authorCount:number; requestCount:number;
 generatedAt:string; claimId:string; claimIds?:string[]; recurring?:boolean; halted?:boolean; picks:Pick[];
 campaign?:{state:string;startsAt?:string;expiresAt?:string;slots?:number;requests?:number;requestsMax?:number;successfulSlots?:number;native?:{state:string;verifiedAt?:string}};
 sroCampaign?:{state:string;startsAt?:string;expiresAt?:string;slots?:number;requests?:number;requestsMax?:number;successfulSlots?:number;native?:{state:string;verifiedAt?:string}};
 olbgCampaign?:{state:string;startsAt?:string;expiresAt?:string;slots?:number;requests?:number;requestsMax?:number;successfulSlots?:number;native?:{state:string;verifiedAt?:string}} };
export function PublicTipsters({ compact=false, tipsterId }: { compact?:boolean; tipsterId?:string }) {
 const [data,setData]=useState<State|null>(null); const [error,setError]=useState(false);
 useEffect(()=>{const controller=new AbortController();let alive=true;let pending=false;
  const read=()=>{if(pending)return;pending=true;
  void fetch('/api/tipsters/public',{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(15000)])}).then(async r=>{
   const value=await r.json();if(!r.ok||value.status!=='ok'||value.schemaVersion!=='robin-public-tipsters-v1')throw new Error('unavailable');
   if(alive){setData(value);setError(false);}
  }).catch(()=>{if(alive)setError(true);}).finally(()=>{pending=false;});};
  read();const timer=setInterval(()=>{if(!document.hidden)read();},15000);
  return()=>{alive=false;controller.abort();clearInterval(timer);};},[]);
 const authors=[...new Map((data?.picks??[]).map(p=>[p.authorId,p])).values()];
 const selected=tipsterId ? authors.find(p=>p.authorId===tipsterId):null;
 return <section className="section-card">
  <SectionHeading title={selected?.authorLabel??'Pronostics personnels collectés'} />
  {error ? <p role="alert">La collecte publique locale est indisponible : preuves absentes ou invalides.</p>:!data ? <p role="status">Lecture des preuves locales…</p>:<>
   <p><strong>{(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId).length : data.distinctPicks)} pronostic(s) personnel(s) collecté(s)</strong> · {tipsterId ? (selected ? 1 : 0) : data.authorCount} pseudonyme(s) · neuf rencontres au maximum par grille.</p>
   <p>Choix attribués à leur source personnelle et observés avant match. Le type de choix est conservé tel que publié. Les pseudonymes ne certifient pas l’identité civile.</p>
   <p>Dossier fidèle en recette partielle.</p>
   <p>Horaires des lectures et des coups d’envoi : heure de Paris.</p>
   {!tipsterId&&<p>{data.recurring ? "Historique de la collecte des forums" : "Lot de collecte ponctuelle"} · {data.requestCount} GET publics HTTP(S) pour ce lot initial. {!data.recurring && !data.campaign && "Aucune collecte automatique de ces forums n’est activée."}</p>}
   {!tipsterId && data.campaign && <div className="section-card">
    <h3>Campagne des deux forums</h3>
    {data.campaign.state==='scheduled' && data.campaign.native?.state==='Ready' ? <p>Programmée : premier lancement le {formatDateTime(data.campaign.startsAt!,true)}, heure de Paris.</p>:
     data.campaign.state==='halted'?<p role="alert">Campagne arrêtée : aucune nouvelle collecte autorisée.</p>:
     data.campaign.state==='expired'?<p>Campagne expirée. Les observations sont conservées.</p>:
     data.campaign.state==='invalid_package'?<p role="alert">Paquet de campagne invalide : exécution refusée.</p>:
     data.campaign.native?.state==='Disabled'?<p>Tâche Windows désactivée.</p>:
     data.campaign.state==='collecting'?<p>Campagne commencée. Les créneaux validés sont attestés par leurs reçus.</p>:
     <p>La programmation attend une confirmation native à jour.</p>}
    <p>{data.campaign.successfulSlots??0} créneau(x) validé(s) · {data.campaign.requests??0} GET réservés sur {data.campaign.requestsMax??72} maximum.</p>
    {data.campaign.slots && <p>{data.campaign.slots} créneaux, toutes les deux heures. Fin le {formatDateTime(data.campaign.expiresAt!,true)}, heure de Paris.</p>}
    {data.campaign.native?.verifiedAt && <p>État Windows vérifié le {formatDateTime(data.campaign.native.verifiedAt,true)}.</p>}
   </div>}
   {(!tipsterId||selected?.sourceId==='SRC_039') && data.sroCampaign && data.sroCampaign.state!=='awaiting_preparation' && <div className="section-card">
    <h3>Collecte Stade Rennais Online</h3>
    <p role={['halted','invalid_package','blocked_lock'].includes(data.sroCampaign.state)?'alert':'status'}>{data.sroCampaign.state==='halted'?'Campagne arrêtée, historique conservé.':data.sroCampaign.state==='expired'?'Campagne expirée.':data.sroCampaign.state==='invalid_package'?'Paquet invalide : exécution refusée.':data.sroCampaign.state==='blocked_lock'?'Collecte bloquée par un verrou : contrôle nécessaire.':data.sroCampaign.state==='collecting'?'Canari réel validé ; état de la programmation ci-dessous.':'En attente du premier canari.'}</p>
    <p>{data.sroCampaign.successfulSlots??0} créneau(x) validé(s) · {data.sroCampaign.requests??0} GET réservés sur {data.sroCampaign.requestsMax??39} maximum.</p>
    <p>Un canari puis onze créneaux toutes les deux heures, du 20 novembre à 8 h au 21 à 4 h ; expiration à 8 h, heure de Paris. Le plafond inclut les trois GET du premier arrêt et du diagnostic. Usage personnel local uniquement.</p>
    <p>État Windows : {data.sroCampaign.native?.state??'vérification en cours'}.{data.sroCampaign.native?.verifiedAt&&` Vérifié le ${formatDateTime(data.sroCampaign.native.verifiedAt,true)}.`}</p>
   </div>}
   {(!tipsterId||selected?.sourceId==='SRC_014') && data.olbgCampaign && data.olbgCampaign.state!=='awaiting_preparation' && <div className="section-card">
    <h3>Collecte OLBG · profil 648433</h3>
    <p role={['halted','invalid_package','blocked_lock'].includes(data.olbgCampaign.state)?'alert':'status'}>{data.olbgCampaign.state==='collecting'?'Canari réel validé ; état de la programmation ci-dessous.':data.olbgCampaign.state==='halted'?'Campagne arrêtée, historique conservé.':data.olbgCampaign.state==='expired'?'Campagne expirée.':data.olbgCampaign.state==='scheduled'?'En attente du premier canari.':'Collecte bloquée : contrôle du paquet nécessaire.'}</p>
    <p>{data.olbgCampaign.successfulSlots??0} créneau(x) validé(s) · {data.olbgCampaign.requests??0} GET réservés sur {data.olbgCampaign.requestsMax??36} maximum.</p>
    <p>Un canari puis onze créneaux toutes les deux heures, du 20 novembre à 8 h au 21 à 4 h ; expiration à 8 h, heure de Paris. Profil 648433 uniquement, usage personnel local. Arrêt si aucun choix admissible ou si les conditions changent.</p>
    <p>État Windows : {data.olbgCampaign.native?.state??'vérification en cours'}.{data.olbgCampaign.native?.verifiedAt&&` Vérifié le ${formatDateTime(data.olbgCampaign.native.verifiedAt,true)}.`}</p>
   </div>}
   {data.halted && <p role="alert">Campagne des forums arrêtée. Historique préservé ; aucune nouvelle lecture autorisée par cette campagne.</p>}
   {compact ? <InlineLink href="/expert/collecte-publique">Voir les fiches et les pronostics collectés</InlineLink>:<>
    <p><InlineLink href="/expert/collecte-publique">Tous les tipsters collectés</InlineLink></p>
    {!tipsterId && <ul>{authors.map(a=><li key={a.authorId}><Link href={`/expert/tipsters/${encodeURIComponent(a.sourceId==='SRC_039'&&/^[a-f0-9]{64}$/.test(a.authorId)?`forum:${a.authorId}`:a.authorId)}`}>{a.authorLabel}</Link> · {a.sourceId} · {data.picks.filter(p=>p.authorId===a.authorId).length} choix</li>)}</ul>}
    {!tipsterId && data.picks.length===0 && <p>Aucun pronostic personnel admissible dans ces preuves locales.</p>}
    {tipsterId && !selected && <p>Cette fiche ne figure pas dans les preuves locales actuelles.</p>}
    {(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId) : data.picks).map(p=><article key={p.id} className="section-card tipster-pick">
     <h3>{p.fixtureLabel} · {p.market==='source_native'?'Choix publié (Win) :':'score prévu'} {p.selection}</h3>
     <p>{p.authorLabel} · {p.sourceId}</p>
     <p>Coup d’envoi : {formatDateTime(p.kickoff,true)}.</p>
     <p>Observé avant match le {formatDateTime(p.observedAt,true)}.</p>
     <p>Date civile affichée : {p.publishedCivilDate??'non renseignée'}. Publication : heure et fuseau non certifiés.</p>
     {p.market==='source_native'&&<p>Marché normalisé et durée de jeu non certifiés. Évaluation de performance désactivée.</p>}
     <a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message source</a>
     <p>En observation · aucun résultat ni rendement calculé.</p>
    </article>)}
   </>}
   <p><small>Preuve {(data.claimIds??[data.claimId]).join(' · ')} · vue du {formatDateTime(data.generatedAt,true)}.</small></p>
  </>}
 </section>;
}
