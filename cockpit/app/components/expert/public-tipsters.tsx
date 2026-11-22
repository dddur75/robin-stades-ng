"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";
import type { PublicCampaign } from '../../lib/tipsters-campaign';
import { PublicCampaignCounters, PublicCampaignStatus } from './public-campaign-status';
import {choiceHeading,OpaqueChoiceDetails,type SourceChoice} from './source-choice';

function CampaignBlock({title,campaign,children,counters=true}:{title:ReactNode;campaign:PublicCampaign;children?:ReactNode;counters?:boolean}){
 return <div className="section-card"><h3>{title}</h3><PublicCampaignStatus campaign={campaign}/>{counters&&<PublicCampaignCounters campaign={campaign}/>}
  {Number.isFinite(Date.parse(campaign.expiresAt??''))&&<p>Fin du plan : {formatDateTime(campaign.expiresAt!,true)}.</p>}
  {Number.isFinite(Date.parse(campaign.native?.verifiedAt??''))&&<p>État Windows vérifié le {formatDateTime(campaign.native!.verifiedAt!,true)}.</p>}{children}</div>;
}

type Pick = SourceChoice & { id:string; authorId:string; authorLabel:string; sourceId:string; fixtureLabel:string;
 selection:string; market?:string; kickoff:string; observedAt:string; firstSeenAt?:string; publishedCivilDate:string|null; sourceUrl:string; observationCount?:number; lastObservedAt?:string };

export function isSroReobservation(pick:{firstSeenAt?:string;observedAt:string},update:{lastSeenAt:string}|undefined):boolean{
 if(!update)return false;
 const first=Date.parse(pick.firstSeenAt??pick.observedAt),last=Date.parse(update.lastSeenAt);
 return Number.isFinite(first)&&Number.isFinite(last)&&last>first;
}
type State = { retainedSnapshot?:{state:string;operationalState:string;snapshotPreparedAt:string}; status:string; distinctPicks:number; authorCount:number; requestCount:number;
 generatedAt:string; sourceObservedThrough?:string; claimId:string; claimIds?:string[]; recurring?:boolean; halted?:boolean; picks:Pick[];
 forumCompanion?:{state:string;claimId?:string;approvedObservationCount?:number;approvedNewCount?:number;approvedReobservationCount?:number;updates?:Record<string,{lastSeenAt:string;claimId:string}>};
 sroNextCompanion?:{updates:Record<string,{lastSeenAt:string;claimId:string}>}; sroNextCampaign?:PublicCampaign&{canaryReobservations?:number;priorFamilyGET?:number;familyGETMax?:number;futureReceiptReview?:string;poolAuthorIds?:string[]};
 campaign?:PublicCampaign; sroCampaign?:PublicCampaign; olbgCampaign?:PublicCampaign; expandedOlbgCampaign?:PublicCampaign; profileCampaign?:PublicCampaign;
 personalCollection?:{state:string;claimId?:string;qualifiedAt?:string;nativeChoices?:number}; notbettingBundesOccurrences?:{state:string;nativeOccurrences?:number}; notbettingClosedOccurrences?:{state:string};
 notbettingOccurrenceCompanion?:{updates:Record<string,{lastObservedAt:string;observations:unknown[]}>}; notbettingOccurrenceCampaign?:PublicCampaign;
 familyCollection?:{state:string;nativeWinState?:string;opaqueState?:string}; rosterCollection?:{state:string}; notbettingCollection?:{state:string}; rosterNextCampaign?:PublicCampaign&{authorIds?:string[];poolAuthorIds?:string[];profileCount?:number}; rosterCampaign?:PublicCampaign&{authorIds?:string[];poolAuthorIds?:string[];profileCount?:number} };
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
 const {campaign,sroCampaign,sroNextCampaign,olbgCampaign,expandedOlbgCampaign,profileCampaign,rosterCampaign,rosterNextCampaign}=data??{};
 const authors=[...new Map((data?.picks??[]).map(p=>[p.authorId,p])).values()];
 const selected=tipsterId ? authors.find(p=>p.authorId===tipsterId):null;
 const showNotBetting=!tipsterId||selected?.sourceId==='NotBetting';
 const personalCollection=selected?.sourceId==='NotBetting'?undefined:data?.personalCollection;
 return <section className="section-card">
  <SectionHeading title={selected?.authorLabel??'Pronostics personnels collectés'} />
  {error ? <p role="alert">Preuves locales absentes ou invalides.</p>:!data ? <p role="status">Lecture des preuves locales…</p>:<>
   <p><strong>{(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId).length : data.distinctPicks)} pronostic(s) personnel(s) collecté(s)</strong> · {tipsterId ? (selected ? 1 : 0) : data.authorCount} pseudonyme(s).</p>
   <p>Choix relevés avant match, tels que publiés. Pseudonymes non certifiés.</p>
   <p>Dossier fidèle en recette partielle.</p>
   {data.retainedSnapshot&&<p>Historique validé conservé. L’état actuel des collectes automatiques n’est pas vérifié dans cette vue.</p>}
   {personalCollection?.state==='historical_observations_qualified'&&<p>Calendriers officiels et dates de lecture d’origine conservés.</p>}
   {personalCollection?.state==='historical_observations_qualified'&&personalCollection.qualifiedAt&&<p>Lecture du catalogue : {formatDateTime(data.sourceObservedThrough??data.generatedAt,true)}. Qualification : {formatDateTime(personalCollection.qualifiedAt,true)}.</p>}
   {personalCollection?.state==='unavailable'&&<p role="alert">Les preuves personnelles complémentaires sont indisponibles. Historique conservé.</p>}
   {[rosterCampaign?.state,data.rosterCollection?.state,data.notbettingCollection?.state,data.notbettingBundesOccurrences?.state,data.notbettingClosedOccurrences?.state,data.familyCollection?.state,data.familyCollection?.nativeWinState,data.familyCollection?.opaqueState,data.forumCompanion?.state].includes('unavailable')&&<p role="alert">Une partie des preuves individuelles supplémentaires est indisponible. Historique conservé.</p>}
   {data.forumCompanion?.state==='available'&&<p>Dernier lot de pronostics qualifié : {data.forumCompanion.approvedNewCount} nouveau choix et {data.forumCompanion.approvedReobservationCount} choix déjà connus relus avant match.</p>}
   {showNotBetting&&data.notbettingCollection?.state==='qualified_one_time'&&<p>NotBetting : collecte ponctuelle qualifiée.</p>}
   {showNotBetting&&data.notbettingBundesOccurrences?.state==='bounded_occurrences_qualified'&&<p>Deux occurrences supplémentaires proviennent d’une capture partielle. Cohérence globale des variantes non établie.</p>}
   {showNotBetting&&data.notbettingClosedOccurrences?.state==='bounded_declarations_qualified'&&<p>Une déclaration supplémentaire provient de deux lectures partielles concordantes. Variantes hors parcours inconnues.</p>}
   <p>Horaires : heure de Paris.</p>
   {showNotBetting&&data.notbettingOccurrenceCampaign&&<CampaignBlock title="Collecte NotBetting · ELIMAGAR" campaign={data.notbettingOccurrenceCampaign}>
    <p>Canari et trois passages, budget commun. Deux lectures avant match par nouvelle déclaration. Parcours partiel, variantes inconnues.</p>
   </CampaignBlock>}
   {!tipsterId&&<p>{data.retainedSnapshot ? "Historique qualifié" : data.recurring ? "Historique de la collecte des forums" : "Lot de collecte ponctuelle"} · {data.requestCount} GET publics HTTP(S) pour ce lot initial. {!data.retainedSnapshot && !data.recurring && !campaign && "Aucune collecte automatique de ces forums n’est activée."}</p>}
   {!tipsterId && campaign && <CampaignBlock title="Campagne des deux forums" campaign={campaign}>
    {campaign.slots&&<p>{campaign.slots} créneaux, toutes les deux heures.</p>}
   </CampaignBlock>}
   {sroNextCampaign&&(!tipsterId||sroNextCampaign.poolAuthorIds?.includes(tipsterId))&&<CampaignBlock title="Prochaine collecte Stade Rennais Online · huit auteurs" campaign={sroNextCampaign} counters={sroNextCampaign.state!=='unavailable'}>
    {sroNextCampaign.state==='unavailable'?<p>Preuves du nouveau plan indisponibles ; historique conservé.</p>:<>
     <p>Trois nouveaux passages, au maximum neuf GET. Budget familial : {sroNextCampaign.priorFamilyGET} GET antérieurs et neuf prévus, plafond {sroNextCampaign.familyGETMax}.</p>
     <p>Canari : {sroNextCampaign.canaryReobservations} choix déjà connus relus avant match ; aucun nouveau pronostic pour ce canari.</p>
     {sroNextCampaign.futureReceiptReview==='PENDING'&&<p>Les nouveaux choix éventuels attendent leur qualification indépendante.</p>}
    </>}
   </CampaignBlock>}
   {(!tipsterId||selected?.sourceId==='SRC_039') && sroCampaign && sroCampaign.state!=='awaiting_preparation' && <CampaignBlock title="Collecte Stade Rennais Online" campaign={sroCampaign}>
    <p>Budget incluant le diagnostic.</p>
   </CampaignBlock>}
   {(!tipsterId||selected?.authorId==='olbg:648433') && olbgCampaign && olbgCampaign.state!=='awaiting_preparation' && <CampaignBlock title="Collecte OLBG · profil 648433" campaign={olbgCampaign}>
   </CampaignBlock>}
   {(!tipsterId||selected?.authorId==='olbg:383717') && expandedOlbgCampaign && <CampaignBlock title="Collecte OLBG · profil 383717" campaign={expandedOlbgCampaign}>
    {expandedOlbgCampaign.state==='unavailable'&&<p>Autorité indisponible ; programmation non certifiée.</p>}
   </CampaignBlock>}
   {selected?.authorId==='olbg:383717'&&!expandedOlbgCampaign&&<p>Ce profil dispose d’une preuve ponctuelle. Récurrence non certifiée.</p>}
   {(!tipsterId||selected?.authorId==='olbg:669088')&&profileCampaign&&<CampaignBlock title="Collecte OLBG · profil 669088" campaign={profileCampaign}>
    <p>Ce profil seul : cinq matchs vérifiés. Conditions réutilisées pour la période.</p>
   </CampaignBlock>}
   {rosterCampaign&&(!tipsterId||(rosterCampaign.poolAuthorIds??rosterCampaign.authorIds)?.includes(tipsterId))&&<CampaignBlock title={<>Collecte du groupe OLBG{typeof rosterCampaign.profileCount==='number'&&` · ${rosterCampaign.profileCount} profils`}</>} campaign={rosterCampaign} counters={rosterCampaign.state!=='unavailable'}>
    {rosterCampaign.state==='unavailable'?<p>Preuves du groupe indisponibles ; programmation non certifiée.</p>:<>
     {typeof rosterCampaign.successfulSlots==='number'&&rosterCampaign.successfulSlots>0&&<p>Canari vérifié sur trois auteurs. Profils hors registre inclus.</p>}
     <p>Arrêt du profil sans choix ; du groupe sur refus, incident ou limite.</p>
     {tipsterId&&rosterCampaign.poolAuthorIds?.includes(tipsterId)&&!rosterCampaign.authorIds?.includes(tipsterId)&&<p>Profil arrêté ; historique conservé.</p>}
    </>}
   </CampaignBlock>}
   {rosterNextCampaign&&(!tipsterId||rosterNextCampaign.poolAuthorIds?.includes(tipsterId))&&<CampaignBlock title="Prochaine collecte OLBG · 42 profils au maximum" campaign={rosterNextCampaign} counters={rosterNextCampaign.state!=='unavailable'}>
    <p>Trois passages distincts de la campagne terminée. Leurs compteurs commencent à zéro.</p>
    {typeof rosterNextCampaign.successfulSlots==='number'&&rosterNextCampaign.successfulSlots>0&&<p>Les passages comptabilisés disposent d’un journal de collecte clôturé.</p>}
    <p>Sans choix admissible : arrêt du profil. Créneau manqué ou refus d’accès : arrêt sans rattrapage.</p>
   </CampaignBlock>}
   {data.halted && <p role="alert">Campagne des forums arrêtée. Historique préservé ; aucune nouvelle lecture autorisée par cette campagne.</p>}
   {compact ? <InlineLink href="/expert/collecte-publique">Voir les fiches et les pronostics collectés</InlineLink>:<>
    <p><InlineLink href="/expert/collecte-publique">Tous les tipsters collectés</InlineLink></p>
    {!tipsterId && <ul>{authors.map(a=><li key={a.authorId}><Link href={`/expert/tipsters/${encodeURIComponent(a.sourceId==='SRC_039'&&/^[a-f0-9]{64}$/.test(a.authorId)?`forum:${a.authorId}`:a.authorId)}`}>{a.authorLabel}</Link> · {a.sourceId} · {data.picks.filter(p=>p.authorId===a.authorId).length} choix</li>)}</ul>}
    {!tipsterId && data.picks.length===0 && <p>Aucun pronostic personnel admissible dans ces preuves locales.</p>}
    {tipsterId && !selected && <p>Cette fiche ne figure pas dans les preuves locales actuelles.</p>}
    {(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId) : data.picks).map(p=>{
     const sroUpdate=data.sroNextCompanion?.updates[p.id];
     const reobservation=sroUpdate??data.forumCompanion?.updates?.[p.id];
     const update=data.notbettingOccurrenceCompanion?.updates[p.id], count=update?.observations.length??p.observationCount, last=update?.lastObservedAt??p.lastObservedAt;
     return <article key={p.id} className="section-card tipster-pick">
     <h3>{p.fixtureLabel} · {choiceHeading(p)} {p.selection}</h3>
     <p>{p.authorLabel} · {p.sourceId}</p>
     <p>Coup d’envoi : {formatDateTime(p.kickoff,true)}.</p>
     <p>Observé avant match le {formatDateTime(p.observedAt,true)}.</p>
     {(update||p.sourceWalkTruncated)&&Number.isSafeInteger(count)&&count!>1&&last&&<p>{count} lectures concordantes{update&&' de la même source'}. Dernière : {formatDateTime(last,true)}.</p>}
     {reobservation&&isSroReobservation(p,reobservation)&&<p>Choix déjà connu, relu avant match le {formatDateTime(reobservation.lastSeenAt,true)}. Première observation conservée.</p>}
     <p>Date civile affichée : {p.publishedCivilDate??'non renseignée'}. Publication : heure et fuseau non certifiés.</p>
     {p.market==='source_native'&&<p>Marché normalisé et durée de jeu non certifiés. Évaluation de performance désactivée.</p>}
     <OpaqueChoiceDetails choice={p}/>
     <a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message source</a>
     <p>En observation · aucun résultat ni rendement calculé.</p>
    </article>})}
   </>}
   <p><small>Dossier actualisé le {formatDateTime(data.generatedAt,true)}.</small></p>
   <details><summary>Preuves du dossier</summary><p style={{overflowWrap:'anywhere'}}><small>{(data.claimIds??[data.claimId]).join(' · ')}</small></p></details>
  </>}
 </section>;
}
