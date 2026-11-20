"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";
import type { PublicCampaign } from '../../lib/tipsters-campaign';
import { PublicCampaignCounters, PublicCampaignStatus } from './public-campaign-status';

type Pick = { id:string; authorId:string; authorLabel:string; sourceId:string; fixtureLabel:string;
 selection:string; market?:string; kickoff:string; observedAt:string; publishedCivilDate:string|null; sourceUrl:string };
type State = { status:string; distinctPicks:number; authorCount:number; requestCount:number;
 generatedAt:string; sourceObservedThrough?:string; claimId:string; claimIds?:string[]; recurring?:boolean; halted?:boolean; picks:Pick[];
 campaign?:PublicCampaign; sroCampaign?:PublicCampaign; olbgCampaign?:PublicCampaign; expandedOlbgCampaign?:PublicCampaign;
 personalCollection?:{state:string;claimId?:string;qualifiedAt?:string;nativeChoices?:number} };
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
   <p><strong>{(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId).length : data.distinctPicks)} pronostic(s) personnel(s) collecté(s)</strong> · {tipsterId ? (selected ? 1 : 0) : data.authorCount} pseudonyme(s).</p>
   <p>Choix attribués à leur source personnelle et observés avant match. Le type de choix est conservé tel que publié. Les pseudonymes ne certifient pas l’identité civile.</p>
   <p>Dossier fidèle en recette partielle.</p>
   {data.personalCollection?.state==='historical_observations_qualified'&&<p>Usage personnel local confirmé. Des calendriers officiels supplémentaires ont complété les preuves de choix déjà observés ; leurs dates de lecture d’origine sont conservées.</p>}
   {data.personalCollection?.state==='historical_observations_qualified'&&data.personalCollection.qualifiedAt&&<p>Dernière observation du catalogue : {formatDateTime(data.sourceObservedThrough??data.generatedAt,true)}. Qualification complémentaire du catalogue : {formatDateTime(data.personalCollection.qualifiedAt,true)}.</p>}
   {data.personalCollection?.state==='unavailable'&&<p role="alert">Les preuves personnelles complémentaires sont indisponibles. Les faits antérieurs restent conservés avec leur provenance.</p>}
   <p>Horaires des lectures et des coups d’envoi : heure de Paris.</p>
   {!tipsterId&&<p>{data.recurring ? "Historique de la collecte des forums" : "Lot de collecte ponctuelle"} · {data.requestCount} GET publics HTTP(S) pour ce lot initial. {!data.recurring && !data.campaign && "Aucune collecte automatique de ces forums n’est activée."}</p>}
   {!tipsterId && data.campaign && <div className="section-card">
    <h3>Campagne des deux forums</h3>
    <PublicCampaignStatus campaign={data.campaign} />
    <PublicCampaignCounters campaign={data.campaign} />
    {data.campaign.slots && Number.isFinite(Date.parse(data.campaign.expiresAt??'')) && <p>{data.campaign.slots} créneaux, toutes les deux heures. Fin le {formatDateTime(data.campaign.expiresAt!,true)}, heure de Paris.</p>}
    {Number.isFinite(Date.parse(data.campaign.native?.verifiedAt??'')) && <p>État Windows vérifié le {formatDateTime(data.campaign.native!.verifiedAt!,true)}.</p>}
   </div>}
   {(!tipsterId||selected?.sourceId==='SRC_039') && data.sroCampaign && data.sroCampaign.state!=='awaiting_preparation' && <div className="section-card">
    <h3>Collecte Stade Rennais Online</h3>
    <PublicCampaignStatus campaign={data.sroCampaign} />
    <PublicCampaignCounters campaign={data.sroCampaign} />
    <p>Un canari puis onze créneaux toutes les deux heures, du 20 novembre à 8 h au 21 à 4 h ; expiration à 8 h, heure de Paris. Le plafond inclut les trois GET du premier arrêt et du diagnostic. Usage personnel local uniquement.</p>
    <p>État Windows : {data.sroCampaign.native?.state??'vérification en cours'}.{Number.isFinite(Date.parse(data.sroCampaign.native?.verifiedAt??''))&&` Vérifié le ${formatDateTime(data.sroCampaign.native!.verifiedAt!,true)}.`}</p>
   </div>}
   {(!tipsterId||selected?.authorId==='olbg:648433') && data.olbgCampaign && data.olbgCampaign.state!=='awaiting_preparation' && <div className="section-card">
    <h3>Collecte OLBG · profil 648433</h3>
    <PublicCampaignStatus campaign={data.olbgCampaign} />
    <PublicCampaignCounters campaign={data.olbgCampaign} />
    <p>Un canari puis onze créneaux toutes les deux heures, du 20 novembre à 8 h au 21 à 4 h ; expiration à 8 h, heure de Paris. Profil 648433 uniquement, usage personnel local. Arrêt si aucun choix admissible ou si les conditions changent.</p>
    <p>État Windows : {data.olbgCampaign.native?.state??'vérification en cours'}.{Number.isFinite(Date.parse(data.olbgCampaign.native?.verifiedAt??''))&&` Vérifié le ${formatDateTime(data.olbgCampaign.native!.verifiedAt!,true)}.`}</p>
   </div>}
   {(!tipsterId||selected?.authorId==='olbg:383717') && data.expandedOlbgCampaign && <div className="section-card">
    <h3>Collecte OLBG · profil 383717</h3>
    <PublicCampaignStatus campaign={data.expandedOlbgCampaign}/>
    <PublicCampaignCounters campaign={data.expandedOlbgCampaign}/>
    {data.expandedOlbgCampaign.state==='unavailable'?<p>L’autorité récurrente de ce profil est indisponible. Aucune programmation active n’est certifiée par cette lecture.</p>:<p>Autorité distincte : un canari puis deux créneaux le 20 novembre à 14 h et 16 h, heure de Paris. Plafond neuf GET ; expiration à 16 h 15. Aucun autre profil n’est couvert.</p>}
    <p>État Windows : {data.expandedOlbgCampaign.native?.state??'indisponible'}.</p>
   </div>}
   {selected?.authorId==='olbg:383717'&&!data.expandedOlbgCampaign&&<p>Ce profil dispose d’une preuve ponctuelle. Son autorité récurrente est indisponible ; la campagne du profil 648433 ne le couvre pas.</p>}
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
