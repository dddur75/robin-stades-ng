"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";
import type { PublicCampaign } from '../../lib/tipsters-campaign';
import { PublicCampaignCounters, PublicCampaignStatus } from './public-campaign-status';
import {choiceHeading,OpaqueChoiceDetails,type SourceChoice} from './source-choice';

function CampaignBlock({title,campaign,children,counters=true}:{title:ReactNode;campaign:PublicCampaign;children?:ReactNode;counters?:boolean}){
 return <div className="section-card"><h3>{title}</h3><PublicCampaignStatus campaign={campaign}/>{counters&&<PublicCampaignCounters campaign={campaign}/>} {children}</div>;
}
function NativeDetail({campaign}:{campaign:PublicCampaign}){
 return <p>État Windows : {campaign.native?.state??'vérification en cours'}.{Number.isFinite(Date.parse(campaign.native?.verifiedAt??''))&&` Vérifié le ${formatDateTime(campaign.native!.verifiedAt!,true)}.`}</p>;
}

type Pick = SourceChoice & { id:string; authorId:string; authorLabel:string; sourceId:string; fixtureLabel:string;
 selection:string; market?:string; kickoff:string; observedAt:string; publishedCivilDate:string|null; sourceUrl:string };
type State = { status:string; distinctPicks:number; authorCount:number; requestCount:number;
 generatedAt:string; sourceObservedThrough?:string; claimId:string; claimIds?:string[]; recurring?:boolean; halted?:boolean; picks:Pick[];
 campaign?:PublicCampaign; sroCampaign?:PublicCampaign; olbgCampaign?:PublicCampaign; expandedOlbgCampaign?:PublicCampaign; profileCampaign?:PublicCampaign;
 personalCollection?:{state:string;claimId?:string;qualifiedAt?:string;nativeChoices?:number};
 familyCollection?:{state:string;nativeWinState?:string;opaqueState?:string}; rosterCollection?:{state:string}; notbettingCollection?:{state:string}; rosterCampaign?:PublicCampaign&{authorIds?:string[];poolAuthorIds?:string[];profileCount?:number} };
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
 const {campaign,sroCampaign,olbgCampaign,expandedOlbgCampaign,profileCampaign,rosterCampaign}=data??{};
 const authors=[...new Map((data?.picks??[]).map(p=>[p.authorId,p])).values()];
 const selected=tipsterId ? authors.find(p=>p.authorId===tipsterId):null;
 const personalCollection=selected?.sourceId==='NotBetting'?undefined:data?.personalCollection;
 return <section className="section-card">
  <SectionHeading title={selected?.authorLabel??'Pronostics personnels collectés'} />
  {error ? <p role="alert">La collecte publique locale est indisponible : preuves absentes ou invalides.</p>:!data ? <p role="status">Lecture des preuves locales…</p>:<>
   <p><strong>{(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId).length : data.distinctPicks)} pronostic(s) personnel(s) collecté(s)</strong> · {tipsterId ? (selected ? 1 : 0) : data.authorCount} pseudonyme(s).</p>
   <p>Choix personnels observés avant match, conservés tels que publiés. Pseudonymes sans identité civile certifiée.</p>
   <p>Dossier fidèle en recette partielle.</p>
   {personalCollection?.state==='historical_observations_qualified'&&<p>Usage personnel local confirmé. Des calendriers officiels supplémentaires ont complété les preuves de choix déjà observés ; leurs dates de lecture d’origine sont conservées.</p>}
   {personalCollection?.state==='historical_observations_qualified'&&personalCollection.qualifiedAt&&<p>Dernière observation du catalogue : {formatDateTime(data.sourceObservedThrough??data.generatedAt,true)}. Qualification complémentaire du catalogue : {formatDateTime(personalCollection.qualifiedAt,true)}.</p>}
   {personalCollection?.state==='unavailable'&&<p role="alert">Les preuves personnelles complémentaires sont indisponibles. Les faits antérieurs restent conservés avec leur provenance.</p>}
   {(rosterCampaign?.state==='unavailable'||data.rosterCollection?.state==='unavailable'||data.notbettingCollection?.state==='unavailable'||data.familyCollection?.state==='unavailable'||data.familyCollection?.nativeWinState==='unavailable'||data.familyCollection?.opaqueState==='unavailable')&&<p role="alert">Une partie des preuves individuelles supplémentaires est indisponible. Les autres observations restent conservées avec leur provenance.</p>}
   {(!tipsterId||selected?.sourceId==='NotBetting')&&data.notbettingCollection?.state==='qualified_one_time'&&<p>NotBetting : collecte ponctuelle qualifiée.</p>}
   <p>Horaires des lectures et des coups d’envoi : heure de Paris.</p>
   {!tipsterId&&<p>{data.recurring ? "Historique de la collecte des forums" : "Lot de collecte ponctuelle"} · {data.requestCount} GET publics HTTP(S) pour ce lot initial. {!data.recurring && !campaign && "Aucune collecte automatique de ces forums n’est activée."}</p>}
   {!tipsterId && campaign && <CampaignBlock title="Campagne des deux forums" campaign={campaign}>
    {campaign.slots && Number.isFinite(Date.parse(campaign.expiresAt??'')) && <p>{campaign.slots} créneaux, toutes les deux heures. Fin le {formatDateTime(campaign.expiresAt!,true)}, heure de Paris.</p>}
    {Number.isFinite(Date.parse(campaign.native?.verifiedAt??'')) && <p>État Windows vérifié le {formatDateTime(campaign.native!.verifiedAt!,true)}.</p>}
   </CampaignBlock>}
   {(!tipsterId||selected?.sourceId==='SRC_039') && sroCampaign && sroCampaign.state!=='awaiting_preparation' && <CampaignBlock title="Collecte Stade Rennais Online" campaign={sroCampaign}>
    <p>Canari puis onze créneaux toutes les deux heures, du 20/11 à 8 h au 21/11 à 4 h (Paris) ; expiration à 8 h. Plafond incluant les trois GET initiaux et du diagnostic. Usage personnel local.</p>
    <NativeDetail campaign={sroCampaign}/>
   </CampaignBlock>}
   {(!tipsterId||selected?.authorId==='olbg:648433') && olbgCampaign && olbgCampaign.state!=='awaiting_preparation' && <CampaignBlock title="Collecte OLBG · profil 648433" campaign={olbgCampaign}>
    <p>Profil 648433 seul : canari puis onze créneaux toutes les deux heures, du 20/11 à 8 h au 21/11 à 4 h (Paris), expiration à 8 h. Usage personnel local ; arrêt sans choix admissible ou si les conditions changent.</p>
    <NativeDetail campaign={olbgCampaign}/>
   </CampaignBlock>}
   {(!tipsterId||selected?.authorId==='olbg:383717') && expandedOlbgCampaign && <CampaignBlock title="Collecte OLBG · profil 383717" campaign={expandedOlbgCampaign}>
    {expandedOlbgCampaign.state==='unavailable'?<p>Autorité indisponible ; programmation active non certifiée.</p>:<p>Ce profil seul : canari puis deux créneaux le 20/11 à 14 h et 16 h (Paris). Neuf GET maximum ; expiration à 16 h 15.</p>}
    <p>État Windows : {expandedOlbgCampaign.native?.state??'indisponible'}.</p>
   </CampaignBlock>}
   {selected?.authorId==='olbg:383717'&&!expandedOlbgCampaign&&<p>Ce profil dispose d’une preuve ponctuelle. Autorité récurrente indisponible ; le profil 648433 ne le couvre pas.</p>}
   {(!tipsterId||selected?.authorId==='olbg:669088')&&profileCampaign&&<CampaignBlock title="Collecte OLBG · profil 669088" campaign={profileCampaign}>
    <p>Ce profil seul : canari et huit créneaux, 18 GET maximum sur cinq matchs vérifiés. Fin le 21/11 à 12 h 15 (Paris), avant le premier match. Réobservations comptées une fois.</p>
    <p>Conditions réutilisées pour cette période, sans relecture par créneau. Aucun résultat ni rendement calculé.</p>
   </CampaignBlock>}
   {rosterCampaign&&(!tipsterId||(rosterCampaign.poolAuthorIds??rosterCampaign.authorIds)?.includes(tipsterId))&&<CampaignBlock title={<>Collecte du groupe OLBG{typeof rosterCampaign.profileCount==='number'&&` · ${rosterCampaign.profileCount} profils`}</>} campaign={rosterCampaign} counters={rosterCampaign.state!=='unavailable'}>
    {rosterCampaign.state==='unavailable'?<p>Preuves du groupe indisponibles ; programmation non certifiée.</p>:<>
     {typeof rosterCampaign.successfulSlots==='number'&&rosterCampaign.successfulSlots>0&&<p>Canari vérifié sur trois auteurs. Trois passages prévus, y compris hors registre Ligue 1. Réobservations comptées une fois.</p>}
     <p>Fin le 21/11 à 12 h 15 (Paris). Profil arrêté sans choix admissible ; groupe arrêté sur refus, incident ou limite.</p>
     {tipsterId&&rosterCampaign.poolAuthorIds?.includes(tipsterId)&&!rosterCampaign.authorIds?.includes(tipsterId)&&<p>Profil arrêté par cette campagne ; observations conservées.</p>}
    </>}
   </CampaignBlock>}
   {data.halted && <p role="alert">Campagne des forums arrêtée. Historique préservé ; aucune nouvelle lecture autorisée par cette campagne.</p>}
   {compact ? <InlineLink href="/expert/collecte-publique">Voir les fiches et les pronostics collectés</InlineLink>:<>
    <p><InlineLink href="/expert/collecte-publique">Tous les tipsters collectés</InlineLink></p>
    {!tipsterId && <ul>{authors.map(a=><li key={a.authorId}><Link href={`/expert/tipsters/${encodeURIComponent(a.sourceId==='SRC_039'&&/^[a-f0-9]{64}$/.test(a.authorId)?`forum:${a.authorId}`:a.authorId)}`}>{a.authorLabel}</Link> · {a.sourceId} · {data.picks.filter(p=>p.authorId===a.authorId).length} choix</li>)}</ul>}
    {!tipsterId && data.picks.length===0 && <p>Aucun pronostic personnel admissible dans ces preuves locales.</p>}
    {tipsterId && !selected && <p>Cette fiche ne figure pas dans les preuves locales actuelles.</p>}
    {(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId) : data.picks).map(p=><article key={p.id} className="section-card tipster-pick">
     <h3>{p.fixtureLabel} · {choiceHeading(p)} {p.selection}</h3>
     <p>{p.authorLabel} · {p.sourceId}</p>
     <p>Coup d’envoi : {formatDateTime(p.kickoff,true)}.</p>
     <p>Observé avant match le {formatDateTime(p.observedAt,true)}.</p>
     <p>Date civile affichée : {p.publishedCivilDate??'non renseignée'}. Publication : heure et fuseau non certifiés.</p>
     {p.market==='source_native'&&<p>Marché normalisé et durée de jeu non certifiés. Évaluation de performance désactivée.</p>}
     <OpaqueChoiceDetails choice={p}/>
     <a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message source</a>
     <p>En observation · aucun résultat ni rendement calculé.</p>
    </article>)}
   </>}
   <p><small>Dossier actualisé le {formatDateTime(data.generatedAt,true)}.</small></p>
   <details><summary>Preuves du dossier</summary><p style={{overflowWrap:'anywhere'}}><small>{(data.claimIds??[data.claimId]).join(' · ')}</small></p></details>
  </>}
 </section>;
}
