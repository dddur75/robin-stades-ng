"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {InlineLink,SectionHeading} from "../common/ui";
import {formatDateTime} from "../../i18n";
import {choiceHeading,OpaqueChoiceDetails,type SourceChoice} from './source-choice';

type Access={platform:string;label:string;reason:string;requiredAccess:string;ownerAction:string;url:string;scope:string};
type Unadmitted={fixtureLabel:string;selection:string;marketLabel:string;sourceEventText:string;observedAt:string;sourceUrl:string;reason:string};
type Qualification=Access&{profileVisited:boolean;documentaryIssues:string[];personallyProven:boolean;unadmittedFacts?:Unadmitted[];expansionClaimId?:string;picks:(SourceChoice&{id:string;fixtureLabel:string;selection:string;market?:string;observedAt:string;kickoff:string;sourceUrl:string})[]};
type Candidate={id:string;label:string;platform:string;sourceUrl:string;evidenceUrl:string;declaredLastDate:string|null;
 status:'pending_qualification';collectionEnabled:boolean;qualification?:Qualification;origin:{sheet:string;row:number;workbookSha256:string}};
type Registry={status:string;schemaVersion:string;count:number;platformCount:number;datedCount:number;enabledCount?:number;candidates:Candidate[];receipt:{registrySha256:string;claimId:string};qualification?:{status:string;claimId?:string;technicalClaimId?:string;technicalClaimIds?:string[];followupOverlayState?:string;expansionState?:string;expansionClaimId?:string;personalOverlayState?:string;personalCollectionState?:string;personalClaimId?:string;compatibleAccessState?:string;compatibleClaimId?:string;familyCollectionState?:string;familyNativeWinState?:string;familyOpaqueState?:string;familyClaimId?:string;assessedCount?:number;qualifiedCount?:number;platforms?:Access[]}};
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
 const filtered=rows.filter(r=>(!platform||r.platform===platform)&&(!dated||r.declaredLastDate)&&`${r.label} ${r.platform}`.toLocaleLowerCase('fr').includes(q.trim().toLocaleLowerCase('fr')));
 const reset=()=>setPage(0);
 return <section className="section-card">
  <SectionHeading title={selected?.label??'Fiches Ligue 1 à qualifier'} />
  <InlineLink href="/expert/catalogue-sources">Catalogue complet des sources</InlineLink>
  {error?<p role="alert">Le registre local des candidats est indisponible. Aucun total de fiches n’est déduit de cette erreur.</p>:!data?<p role="status">Lecture du registre local…</p>:<>
   <p>Registre : <strong>{data.count} fiches importées</strong> · {data.platformCount} libellés de plateforme · {data.datedCount} dates historiques renseignées.</p>
   {data.qualification?.status==='ok'?<>
    <p>{data.qualification.assessedCount} fiches examinées : {data.qualification.qualifiedCount} avec des choix personnels observés avant match. {data.enabledCount??0} rattachée(s) au canari récurrent validé.</p>
    <p>Un contrôle de plateforme ne certifie pas chacun de ses profils. Les autres fiches conservent leur blocage ou attendent une preuve personnelle.</p>
    {data.qualification.followupOverlayState==='unavailable'&&<p role="alert">L’actualisation NotBetting et Telegram est indisponible. Les évaluations antérieures restent affichées avec leur provenance.</p>}
    {data.qualification.expansionState==='unavailable'&&<p role="alert">Le contrôle des profils supplémentaires est indisponible. Les preuves antérieures restent conservées.</p>}
    {(data.qualification.personalOverlayState==='unavailable'||data.qualification.personalCollectionState==='unavailable')&&<p role="alert">L’actualisation de la qualification personnelle est indisponible. Les évaluations et preuves antérieures restent affichées avec leur provenance.</p>}
    {[data.qualification.compatibleAccessState,data.qualification.familyCollectionState,data.qualification.familyNativeWinState,data.qualification.familyOpaqueState].includes('unavailable')&&<p role="alert">Une partie de la qualification complémentaire est indisponible. Les évaluations et choix antérieurs restent conservés.</p>}
    {data.qualification.compatibleClaimId&&<p style={{overflowWrap:'anywhere'}}>Dernière qualification des accès : {data.qualification.compatibleClaimId}</p>}
    {data.qualification.familyClaimId&&<p style={{overflowWrap:'anywhere'}}>Preuve des observations individuelles supplémentaires : {data.qualification.familyClaimId}</p>}
    {data.qualification.personalClaimId&&<p style={{overflowWrap:'anywhere'}}>Usage personnel local confirmé. Preuve de qualification : {data.qualification.personalClaimId}</p>}
    {data.qualification.expansionClaimId&&<p style={{overflowWrap:'anywhere'}}>Preuve des profils supplémentaires : {data.qualification.expansionClaimId}</p>}
    <details><summary>Accès et blocages par plateforme</summary><ul>{(data.qualification.platforms??[]).map(a=><li key={a.platform} style={{overflowWrap:'anywhere'}}><strong>{a.platform} · {a.label}</strong><p>{a.reason}</p><p>Accès à établir : {a.requiredAccess}</p><p>{a.ownerAction}</p><a className="inline-link" href={a.url} target="_blank" rel="noopener noreferrer">Consulter la plateforme</a></li>)}</ul><small style={{overflowWrap:'anywhere'}}>Preuve {data.qualification.claimId}{(data.qualification.technicalClaimIds??[data.qualification.technicalClaimId]).filter(Boolean).map(id=>` · ${id}`).join('')}</small></details>
   </>:<p>Statut : à qualifier. Collecte désactivée pour ces candidats. Leur import n’ajoute aucun pronostic au compteur des observations avant match.</p>}
   {compact?<InlineLink href="/expert/catalogue-tipsters">Consulter les 317 fiches Ligue 1</InlineLink>:tipsterId?<>
    <InlineLink href="/expert/catalogue-tipsters">Retour aux fiches candidates</InlineLink>
    {selected?<article className="section-card">
     <p>{selected.platform} · {selected.qualification?.label??'À qualifier'} · {selected.collectionEnabled?'Collecte autorisée dans la campagne':'Collecte désactivée'}</p>
     <p>Dernière date déclarée dans l’inventaire : {selected.declaredLastDate??'Non renseignée'}. Elle ne certifie pas une publication avant match.</p>
     <p>Provenance : Catalogue, ligne {selected.origin.row}. Classement historique A, Ligue 1.</p>
     {selected.qualification?<>
      <p>{selected.qualification.reason}</p><p>Accès à établir : {selected.qualification.requiredAccess}</p><p>{selected.qualification.ownerAction}</p>
      <p>{selected.qualification.profileVisited?'Route de profil déjà visitée dans l’historique des contrôles.':'Aucune visite individuelle du profil ; portée du contrôle précisée ci-dessus.'}</p>
      {selected.qualification.documentaryIssues.map((x,i)=><p key={i}>{x}</p>)}
      {selected.qualification.picks.length?<><h3>Choix personnels observés avant match</h3>{selected.qualification.picks.map(p=><article className="section-card" key={p.id}><h4>{p.fixtureLabel} · {choiceHeading(p)} {p.selection}</h4><p>Observé le {formatDateTime(p.observedAt,true)} · coup d’envoi le {formatDateTime(p.kickoff,true)}.</p>{p.market==='source_native'&&<p>Publication, marché normalisé et durée non certifiés ; évaluation de performance désactivée.</p>}<OpaqueChoiceDetails choice={p}/><a className="inline-link" href={p.sourceUrl} target="_blank" rel="noopener noreferrer">Voir le message original</a></article>)}</>:<p>Aucun choix personnel admissible n’est établi pour cette fiche.</p>}
      {!!selected.qualification.unadmittedFacts?.length&&<details><summary>{selected.qualification.unadmittedFacts.length} choix source lus, qualification avant match incomplète</summary><p>Ces faits restent séparés du compteur des pronostics admis. Leur date annoncée ne constitue pas un coup d’envoi canonique.</p>{selected.qualification.unadmittedFacts.map((f,i)=><article className="section-card" key={i}><h4>{f.fixtureLabel} · {f.selection}</h4><p>Marché source : {f.marketLabel}. Date annoncée : {f.sourceEventText}.</p><p>Lu le {formatDateTime(f.observedAt,true)}. Blocage : {f.reason}.</p><a className="inline-link" href={f.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter le choix sur sa source</a></article>)}</details>}
     </>:<p>Aucun pronostic collecté n’est attribué à cette fiche par cet import.</p>}
     <p><a className="inline-link" href={selected.sourceUrl} target="_blank" rel="noopener noreferrer">Ouvrir la fiche source</a></p>
     <p><a className="inline-link" href={selected.evidenceUrl} target="_blank" rel="noopener noreferrer">Consulter la référence historique</a></p>
     <details><summary>Empreinte du classeur d’origine</summary><code style={{overflowWrap:'anywhere'}}>{selected.origin.workbookSha256}</code></details>
    </article>:<p>Cette fiche candidate ne figure pas dans le registre vérifié.</p>}
   </>:<>
    <div className="filter-panel pilot-filters">
     <label>Rechercher une fiche<input type="search" value={q} onChange={e=>{setQ(e.target.value);reset();}} /></label>
     <label>Plateforme<select aria-label="Plateforme" value={platform} onChange={e=>{setPlatform(e.target.value);reset();}}><option value="">Toutes les plateformes</option>{[...new Set(rows.map(r=>r.platform))].sort().map(p=><option key={p}>{p}</option>)}</select></label>
     <label><input type="checkbox" checked={dated} onChange={e=>{setDated(e.target.checked);reset();}} /> Avec date historique renseignée</label>
    </div>
    <p role="status">{filtered.length} fiche(s) trouvée(s). Page {Math.min(page+1,Math.max(1,Math.ceil(filtered.length/25)))} sur {Math.max(1,Math.ceil(filtered.length/25))}.</p>
    {filtered.length?<ul>{filtered.slice(page*25,page*25+25).map(r=><li key={r.id} style={{overflowWrap:'anywhere'}}>
     <Link className="inline-link" href={`/expert/tipsters/${encodeURIComponent(r.id)}`}>{r.label}</Link> · {r.platform} · {r.qualification?.label??'À qualifier'} · {r.declaredLastDate??'Date non renseignée'}
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
