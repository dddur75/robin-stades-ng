"use client";
import {OLBGPendingPanel} from './olbg-pending-panel';
import type {OLBGPendingObservation} from '../../../scripts/olbg-pending-source';
import type {NotBettingPendingObservation,PlatformPendingObservations} from '../../../scripts/notbetting-pending-source';
import {TipsterQualification} from "./tipster-qualification";
import {platformQualificationResultIds} from "../../lib/tipster-qualification";
import {ReviewedSourceObservationPanel} from './reviewed-source-observation';
import type {ReviewedSourceObservation} from '../../../scripts/catalogue-independent';
import type {PendingChannelObservation} from '../../../scripts/telegram-pending-channel';
import Link from "next/link";
import {useEffect,useState} from "react";
import {InlineLink,SectionHeading} from "../common/ui";
import {formatDateTime} from "../../i18n";
import {choiceHeading,OpaqueChoiceDetails,type SourceChoice} from './source-choice';

type Access={platform:string;label:string;reason:string;requiredAccess:string;ownerAction:string;url:string;scope:string};
type Unadmitted={fixtureLabel:string;selection:string;marketLabel:string;sourceEventText:string;observedAt:string;sourceUrl:string;reason:string};
type Qualification=Partial<Access>&{profileVisited?:boolean;documentaryIssues?:string[];personallyProven:boolean;observedAt?:string;lastObservedAt?:string;unadmittedFacts?:Unadmitted[];expansionClaimId?:string;picks:(SourceChoice&{id:string;fixtureLabel:string;selection:string;market?:string;observedAt:string;kickoff:string;sourceUrl:string})[]};
type Candidate={pendingOLBGObservation?:OLBGPendingObservation;pendingChannelObservation?:PendingChannelObservation;reviewedSourceObservation?:ReviewedSourceObservation;id:string;label:string;platform:string;sourceUrl:string;evidenceUrl:string;declaredLastDate:string|null;
 status:'pending_qualification';collectionEnabled:boolean|null;qualification?:Qualification;origin:{kind?:string;sheet?:string;row?:number;workbookSha256?:string;nativeContestLabel?:string;captureSHA256?:string;parentWorkbook?:{sheet:string;row:number;workbookSha256:string}}};
type Registry={platformPendingObservations?:PlatformPendingObservations;historicalEvidence?:{sourceObservedAt?:string|null};operationalState?:'unknown';status:string;schemaVersion:string;count:number;platformCount:number;datedCount:number;enabledCount?:number|null;candidates:Candidate[];receipt:{registrySha256:string;claimId:string};qualification?:{status:string;claimId?:string;technicalClaimId?:string;technicalClaimIds?:string[];followupOverlayState?:string;expansionState?:string;expansionClaimId?:string;personalOverlayState?:string;personalCollectionState?:string;personalClaimId?:string;compatibleAccessState?:string;compatibleClaimId?:string;rosterCollectionState?:string;rosterRecurringState?:string;familyCollectionState?:string;familyNativeWinState?:string;familyOpaqueState?:string;familyClaimId?:string;assessedCount?:number;qualifiedCount?:number;platforms?:Access[]}};
export function TipsterCandidates({compact=false,tipsterId}:{compact?:boolean;tipsterId?:string}){
 const [data,setData]=useState<Registry|null>(null);const[error,setError]=useState(false);
 const[q,setQ]=useState('');const[platform,setPlatform]=useState('');const[dated,setDated]=useState(false);const[page,setPage]=useState(0);
 useEffect(()=>{const c=new AbortController();let alive=true;let pending=false;
 const read=()=>{if(pending)return;pending=true;
 void fetch('/api/tipsters/candidates',{cache:'no-store',signal:AbortSignal.any([c.signal,AbortSignal.timeout(15000)])}).then(async r=>{const v=await r.json();
  if(!r.ok||v.status!=='ok'||v.schemaVersion!=='robin-candidate-registry-v1')throw new Error('unavailable');if(alive){setData(v);setError(false);}
 }).catch(()=>{if(alive)setError(true);}).finally(()=>{pending=false;});};read();
 const timer=setInterval(()=>{if(!document.hidden)read();},15000);return()=>{alive=false;c.abort();clearInterval(timer);};},[]);
 const rows=data?.candidates??[];const selected=rows.find(r=>r.id===tipsterId);
 const nativeProfile=selected?.origin.kind==='accepted_native_personal_profile';
 const platformResultIds=selected?platformQualificationResultIds(selected.platform):[];
 const filtered=rows.filter(r=>(!platform||r.platform===platform)&&(!dated||r.declaredLastDate)&&`${r.label} ${r.platform}`.toLocaleLowerCase('fr').includes(q.trim().toLocaleLowerCase('fr')));
 const reset=()=>setPage(0);
 return <section className="section-card">
  <SectionHeading title={selected?.label??'Fiches tipsters'} />
  <InlineLink href="/expert/catalogue-sources">Catalogue complet des sources</InlineLink>
  {error?<p role="alert">Le registre local des candidats est indisponible. Aucun total de fiches n’est déduit de cette erreur.</p>:!data?<p role="status">Lecture du registre local…</p>:<>
   <p>Registre : <strong>{data.count} fiches importées</strong> · {data.platformCount} libellés de plateforme · {data.datedCount} dates historiques renseignées.</p>
   {data.qualification?.status==='ok'?<>
    <p>Qualification historique conservée : {data.qualification.assessedCount} fiches examinées ; {data.qualification.qualifiedCount} avec des choix personnels observés avant match. État actuel des collectes non vérifié.</p>
    <p>Référence historique : {data.historicalEvidence?.sourceObservedAt?formatDateTime(data.historicalEvidence.sourceObservedAt,true):'date non renseignée'}. Ce champ source ne certifie pas l’heure de capture.</p>
    <p>Un contrôle de plateforme ne certifie pas chacun de ses profils. Les autres fiches conservent leur blocage ou attendent une preuve personnelle.</p>
    {data.qualification.followupOverlayState==='unavailable'&&<p role="alert">L’actualisation NotBetting et Telegram est indisponible. Les évaluations antérieures restent affichées avec leur provenance.</p>}
    {data.qualification.expansionState==='unavailable'&&<p role="alert">Le contrôle des profils supplémentaires est indisponible. Les preuves antérieures restent conservées.</p>}
    {(data.qualification.personalOverlayState==='unavailable'||data.qualification.personalCollectionState==='unavailable')&&<p role="alert">L’actualisation de la qualification personnelle est indisponible. Les évaluations et preuves antérieures restent affichées avec leur provenance.</p>}
    {[data.qualification.rosterRecurringState,data.qualification.rosterCollectionState,data.qualification.compatibleAccessState,data.qualification.familyCollectionState,data.qualification.familyNativeWinState,data.qualification.familyOpaqueState].includes('unavailable')&&<p role="alert">Une partie de la qualification complémentaire est indisponible. Les évaluations et choix antérieurs restent conservés.</p>}
    {data.qualification.compatibleClaimId&&<p style={{overflowWrap:'anywhere'}}>Dernière qualification des accès : {data.qualification.compatibleClaimId}</p>}
    {data.qualification.familyClaimId&&<p style={{overflowWrap:'anywhere'}}>Preuve des observations individuelles supplémentaires : {data.qualification.familyClaimId}</p>}
    {data.qualification.personalClaimId&&<p style={{overflowWrap:'anywhere'}}>Usage personnel local confirmé. Preuve de qualification : {data.qualification.personalClaimId}</p>}
    {data.qualification.expansionClaimId&&<p style={{overflowWrap:'anywhere'}}>Preuve des profils supplémentaires : {data.qualification.expansionClaimId}</p>}
    <details><summary>Accès et blocages par plateforme</summary><ul>{(data.qualification.platforms??[]).map(a=><li key={a.platform} style={{overflowWrap:'anywhere'}}><strong>{a.platform} · {a.label}</strong><p>{a.reason}</p><p>Accès à établir : {a.requiredAccess}</p><p>{a.ownerAction}</p><a className="inline-link" href={a.url} target="_blank" rel="noopener noreferrer">Consulter la plateforme</a></li>)}</ul><small style={{overflowWrap:'anywhere'}}>Preuve {data.qualification.claimId}{(data.qualification.technicalClaimIds??[data.qualification.technicalClaimId]).filter(Boolean).map(id=>` · ${id}`).join('')}</small></details>
   </>:<p>Qualifications historiques indisponibles ; les fiches documentaires restent visibles. État actuel des collectes non vérifié. Cet import n’ajoute aucun pronostic.</p>}
   {data.platformPendingObservations?.NotBetting&&(compact||selected?.platform==='NotBetting')&&<NotBettingPendingPanel observation={data.platformPendingObservations.NotBetting}/>}
   {compact&&rows.filter(c=>c.pendingOLBGObservation).map(c=><OLBGPendingPanel key={c.id} observation={c.pendingOLBGObservation!} assigned candidateId={c.id}/>)}
   {data.platformPendingObservations?.OLBG&&(compact||selected?.platform==='OLBG')&&<OLBGPendingPanel observation={data.platformPendingObservations.OLBG}/>} 
   {compact?<InlineLink href="/expert/catalogue-tipsters">Consulter les {data.count} fiches tipsters</InlineLink>:tipsterId?<>
    <InlineLink href="/expert/catalogue-tipsters">Retour aux fiches candidates</InlineLink>
    {selected?<article className="section-card">
     <p>{selected.platform} · {selected.reviewedSourceObservation?'Messages reçus, à qualifier':selected.qualification?.label??(selected.qualification?.personallyProven?'Choix personnels observés avant match':'À qualifier')} · {selected.collectionEnabled===null?'État actuel de collecte non vérifié':selected.collectionEnabled?'Collecte autorisée dans la campagne':'Collecte désactivée'}</p>
     {nativeProfile?<p>Publication : date et fuseau non certifiés.</p>:<p>Dernière date déclarée dans l’inventaire : {selected.declaredLastDate??'Non renseignée'}. Elle ne certifie pas une publication avant match.</p>}
     {nativeProfile?<p>Provenance : profil public {selected.platform}, observé lors de la collecte. Ce profil ne provient pas de l’import du classeur.</p>:selected.origin.nativeContestLabel?<p>Provenance : participant nommé du concours {selected.origin.nativeContestLabel}. Cette identité reste limitée au concours et à sa saison.</p>:<p>Provenance : Catalogue, ligne {selected.origin.row}. Classement historique A, Ligue 1.</p>}
     {selected.reviewedSourceObservation&&<ReviewedSourceObservationPanel observation={selected.reviewedSourceObservation}/>}
     {selected.pendingOLBGObservation&&<OLBGPendingPanel observation={selected.pendingOLBGObservation} assigned candidateId={selected.id}/>}
     {selected.pendingChannelObservation&&<PendingChannelPanel observation={selected.pendingChannelObservation}/>}
     {platformResultIds.length>0&&<TipsterQualification resultIds={platformResultIds} platformContext/>}
     {selected.qualification?<>
      <details open={!selected.reviewedSourceObservation}><summary>Évaluation historique conservée</summary>
      {nativeProfile?<p>Dernière observation source : {selected.qualification.lastObservedAt?formatDateTime(selected.qualification.lastObservedAt,true):'date non renseignée'}. Cet horaire ne certifie pas la publication.</p>:<p>Qualification historique : {selected.qualification.observedAt?formatDateTime(selected.qualification.observedAt,true):'date non renseignée'}. État actuel non vérifié.</p>}
      <p>{selected.qualification.reason}</p><p>Accès à établir : {selected.qualification.requiredAccess}</p><p>{selected.qualification.ownerAction}</p>
      <p>{nativeProfile?'Profil public observé lors de cette collecte.':selected.qualification.profileVisited?'Route de profil déjà visitée dans l’historique des contrôles.':'Aucune visite individuelle du profil ; portée du contrôle précisée ci-dessus.'}</p>
      {selected.qualification.documentaryIssues?.map((x,i)=><p key={i}>{x}</p>)}
      </details>
      {selected.qualification.picks.length?<><h3>Choix personnels conservés</h3>{selected.qualification.picks.map(p=><article className="section-card" key={p.id}><h4>{p.fixtureLabel} · {choiceHeading(p)} {p.selection}</h4><p>Observé le {formatDateTime(p.observedAt,true)} · coup d’envoi le {formatDateTime(p.kickoff,true)}.</p>{p.market==='source_native'&&<p>Publication, marché normalisé et durée non certifiés ; évaluation de performance désactivée.</p>}<OpaqueChoiceDetails choice={p}/><a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message original</a></article>)}</>:<p>Aucun choix personnel admissible n’est établi pour cette fiche.</p>}
      {!!selected.qualification.unadmittedFacts?.length&&<details><summary>{selected.qualification.unadmittedFacts.length} choix source lus, qualification avant match incomplète</summary><p>Ces faits restent séparés du compteur des pronostics admis. Leur date annoncée ne constitue pas un coup d’envoi canonique.</p>{selected.qualification.unadmittedFacts.map((f,i)=><article className="section-card" key={i}><h4>{f.fixtureLabel} · {f.selection}</h4><p>Marché source : {f.marketLabel}. Date annoncée : {f.sourceEventText}.</p><p>Lu le {formatDateTime(f.observedAt,true)}. Blocage : {f.reason}.</p><a className="inline-link" href={f.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter le choix sur sa source</a></article>)}</details>}
     </>:<p>Aucun pronostic collecté n’est attribué à cette fiche par cet import.</p>}
     <p><a className="inline-link" href={selected.sourceUrl} target="_blank" rel="noopener noreferrer">Ouvrir la fiche source</a></p>
     <p><a className="inline-link" href={selected.evidenceUrl} target="_blank" rel="noopener noreferrer">Consulter la référence historique</a></p>
     {nativeProfile?<details><summary>Provenance du profil public</summary><p>Identité : pseudonyme publié sur la plateforme. Cette fiche est distincte de l’inventaire Excel.</p></details>:selected.origin.nativeContestLabel?<details><summary>Provenance de la capture du concours</summary><p>Empreinte de capture : <code style={{overflowWrap:'anywhere'}}>{selected.origin.captureSHA256??'Non renseignée'}</code></p>{selected.origin.parentWorkbook&&<p>Référence documentaire du concours : {selected.origin.parentWorkbook.sheet}, ligne {selected.origin.parentWorkbook.row}. <code style={{overflowWrap:'anywhere'}}>{selected.origin.parentWorkbook.workbookSha256}</code></p>}</details>:<details><summary>Empreinte du classeur d’origine</summary><code style={{overflowWrap:'anywhere'}}>{selected.origin.workbookSha256}</code></details>}
    </article>:<p>Cette fiche candidate ne figure pas dans le registre vérifié.</p>}
   </>:<>
    <div className="filter-panel pilot-filters">
     <label>Rechercher une fiche<input type="search" value={q} onChange={e=>{setQ(e.target.value);reset();}} /></label>
     <label>Plateforme<select aria-label="Plateforme" value={platform} onChange={e=>{setPlatform(e.target.value);reset();}}><option value="">Toutes les plateformes</option>{[...new Set(rows.map(r=>r.platform))].sort().map(p=><option key={p}>{p}</option>)}</select></label>
     <label><input type="checkbox" checked={dated} onChange={e=>{setDated(e.target.checked);reset();}} /> Avec date historique renseignée</label>
    </div>
    <p role="status">{filtered.length} fiche(s) trouvée(s). Page {Math.min(page+1,Math.max(1,Math.ceil(filtered.length/25)))} sur {Math.max(1,Math.ceil(filtered.length/25))}.</p>
    {filtered.length?<ul>{filtered.slice(page*25,page*25+25).map(r=><li key={r.id} style={{overflowWrap:'anywhere'}}>
     <Link className="inline-link" href={`/expert/tipsters/${encodeURIComponent(r.id)}`}>{r.label}</Link> · {r.platform} · {r.qualification?.label??(r.qualification?.personallyProven?'Choix personnels observés avant match':'À qualifier')} · {r.declaredLastDate??'Date non renseignée'}
    </li>)}</ul>:<p>Aucune fiche ne correspond à ces filtres.</p>}
    <nav aria-label="Pages des fiches candidates" className="pilot-actions">
     <button className="pilot-button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Page précédente</button>
     <button className="pilot-button" disabled={(page+1)*25>=filtered.length} onClick={()=>setPage(p=>p+1)}>Page suivante</button>
    </nav>
   </>}
   <details><summary>Preuve de l’import documentaire</summary><p>{data.receipt.claimId}</p><code style={{overflowWrap:'anywhere'}}>{data.receipt.registrySha256}</code></details>
  </>}
 </section>;
}

function PendingChannelPanel({observation:o}:{observation:PendingChannelObservation}){
 return <section aria-label="Sélections du canal à qualifier"><h3>{o.choices.length} sélections du canal à qualifier</h3>
  <p>Sélections publiées par le canal. L’identité personnelle et le match restent à vérifier. Aucun pronostic validé ; collecte récurrente inactive.</p>
  <p>Collecté le {formatDateTime(o.observedAtUTC,true)}. Couverture globale inconnue.</p>
  {o.choices.map(choice=><article className="section-card" key={choice.key}><h4>{choice.selection}</h4>
   <p>Marché extrait : {choice.market}{choice.line!==null?' · ligne '+choice.line:''}. Cote déclarée : {choice.declaredOdds??'Non renseignée'}.</p>
   <p>Publication déclarée : {formatDateTime(choice.publicationDeclaredAtUTC,true)}. Cette date n’est pas un coup d’envoi.</p>
   <a className="inline-link" href={choice.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter la publication source</a>
  </article>)}<details><summary>Traçabilité de la collecte</summary>{o.claimIds.map(id=><p key={id} style={{overflowWrap:'anywhere'}}>{id}</p>)}</details><p>La publication avant le début du match et l’évaluation des performances ne sont pas établies.</p>
 </section>;
}

function NotBettingPendingPanel({observation:o}:{observation:NotBettingPendingObservation}){
 return <section aria-label="NotBetting : faits source non qualifiés"><h3>NotBetting · {o.records.length} fait(s) source à qualifier</h3>
  <p>Contexte de plateforme : ces faits ne sont pas attribués à cette fiche. Aucun pronostic admis ; identité personnelle et rencontre restent à établir.</p>
  <p>Observé le {formatDateTime(o.observedAtUTC,true)}. Couverture globale inconnue.</p>
  {o.records.map(record=><article className="section-card" key={record.key}><h4>Choix déclaré : {record.selection}</h4>
   <p>Événement déclaré : {record.eventText}. Compétition déclarée : {record.competitionText}.</p>
   <p>Alias du compte source : {record.sourceAccountAlias}. Cet alias ne certifie pas une personne.</p>
   <p>Date déclarée par la source : {record.nativeDateText}. Cette valeur ne prouve ni publication ni coup d’envoi.</p>
   <a className="inline-link" href={record.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter la page source</a>
  </article>)}<details><summary>Références du contrôle</summary>{o.claimIds.map(id=><p key={id} style={{overflowWrap:'anywhere'}}>{id}</p>)}</details>
  <p>La publication avant match, l’interprétation du choix et l’évaluation des performances ne sont pas établies. Collecte récurrente inactive.</p>
 </section>;
}
