"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { formatDateTime } from "../../i18n";
import { InlineLink, SectionHeading } from "../common/ui";

type Pick = { id:string; authorId:string; authorLabel:string; sourceId:string; fixtureLabel:string;
 selection:string; kickoff:string; observedAt:string; publishedCivilDate:string; sourceUrl:string };
type State = { status:string; distinctPicks:number; authorCount:number; requestCount:number;
 generatedAt:string; claimId:string; claimIds?:string[]; recurring?:boolean; halted?:boolean; picks:Pick[];
 campaign?:{state:string;startsAt?:string;expiresAt?:string;slots?:number;requests?:number;requestsMax?:number;successfulSlots?:number;native?:{state:string;verifiedAt?:string}} };
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
  <SectionHeading title={selected?.authorLabel??'Pronostics personnels collectés sur les forums'} />
  {error ? <p role="alert">La collecte publique locale est indisponible : preuves absentes ou invalides.</p>:!data ? <p role="status">Lecture des preuves locales…</p>:<>
   <p><strong>{(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId).length : data.distinctPicks)} pronostic(s) personnel(s) collecté(s)</strong> · {tipsterId ? (selected ? 1 : 0) : data.authorCount} pseudonyme(s) · neuf rencontres au maximum par grille.</p>
   <p>Choix de score attribués au message original, observés avant match. Les pseudonymes ne certifient pas l’identité civile.</p>
   <p>Dossier fidèle en recette partielle.</p>
   <p>Horaires des lectures et des coups d’envoi : heure de Paris.</p>
   <p>{data.recurring ? "Historique de la collecte des forums" : "Lot de collecte ponctuelle"} · {data.requestCount} GET publics HTTP(S) pour ce lot initial. {!data.recurring && !data.campaign && "Aucune collecte automatique de ces forums n’est activée."}</p>
   {data.campaign && <div className="section-card">
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
   {data.halted && <p role="alert">Campagne des forums arrêtée. Historique préservé ; aucune nouvelle lecture autorisée par cette campagne.</p>}
   {compact ? <InlineLink href="/expert/collecte-publique">Voir les fiches et les pronostics collectés</InlineLink>:<>
    <p><InlineLink href="/expert/collecte-publique">Tous les tipsters des forums</InlineLink></p>
    {!tipsterId && <ul>{authors.map(a=><li key={a.authorId}><Link href={`/expert/tipsters/${encodeURIComponent(a.authorId)}`}>{a.authorLabel}</Link> · {a.sourceId} · {data.picks.filter(p=>p.authorId===a.authorId).length} choix</li>)}</ul>}
    {!tipsterId && data.picks.length===0 && <p>Aucun pronostic personnel admissible dans ces preuves locales.</p>}
    {tipsterId && !selected && <p>Cette fiche ne figure pas dans les preuves locales actuelles.</p>}
    {(tipsterId ? data.picks.filter(p=>p.authorId===tipsterId) : data.picks).map(p=><article key={p.id} className="section-card tipster-pick">
     <h3>{p.fixtureLabel} · score prévu {p.selection}</h3>
     <p>{p.authorLabel} · {p.sourceId}</p>
     <p>Coup d’envoi : {formatDateTime(p.kickoff,true)}.</p>
     <p>Observé avant match le {formatDateTime(p.observedAt,true)}.</p>
     <p>Date civile affichée : {p.publishedCivilDate}. Publication : heure et fuseau non certifiés.</p>
     <a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message source</a>
     <p>En observation · aucun résultat ni rendement calculé.</p>
    </article>)}
   </>}
   <p><small>Preuve {(data.claimIds??[data.claimId]).join(' · ')} · vue du {formatDateTime(data.generatedAt,true)}.</small></p>
  </>}
 </section>;
}
