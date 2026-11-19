"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {InlineLink,SectionHeading} from "../common/ui";

type Candidate={id:string;label:string;platform:string;sourceUrl:string;evidenceUrl:string;declaredLastDate:string|null;
 status:'pending_qualification';collectionEnabled:false;origin:{sheet:string;row:number;workbookSha256:string}};
type Registry={status:string;schemaVersion:string;count:number;platformCount:number;datedCount:number;candidates:Candidate[];receipt:{registrySha256:string;claimId:string}};
export function TipsterCandidates({compact=false,tipsterId}:{compact?:boolean;tipsterId?:string}){
 const [data,setData]=useState<Registry|null>(null);const[error,setError]=useState(false);
 const[q,setQ]=useState('');const[platform,setPlatform]=useState('');const[dated,setDated]=useState(false);const[page,setPage]=useState(0);
 useEffect(()=>{const c=new AbortController();let alive=true;
 void fetch('/api/tipsters/candidates',{cache:'no-store',signal:c.signal}).then(async r=>{const v=await r.json();
  if(!r.ok||v.status!=='ok'||v.schemaVersion!=='robin-candidate-registry-v1')throw new Error('unavailable');if(alive)setData(v);
 }).catch(()=>{if(alive)setError(true);});return()=>{alive=false;c.abort();};},[]);
 const rows=data?.candidates??[];const selected=rows.find(r=>r.id===tipsterId);
 const filtered=rows.filter(r=>(!platform||r.platform===platform)&&(!dated||r.declaredLastDate)&&`${r.label} ${r.platform}`.toLocaleLowerCase('fr').includes(q.trim().toLocaleLowerCase('fr')));
 const reset=()=>setPage(0);
 return <section className="section-card">
  <SectionHeading title={selected?.label??'Fiches Ligue 1 à qualifier'} />
  {error?<p role="alert">Le registre local des candidats est indisponible. Aucun total de fiches n’est déduit de cette erreur.</p>:!data?<p role="status">Lecture du registre local…</p>:<>
   <p>Registre : <strong>{data.count} fiches importées</strong> · {data.platformCount} libellés de plateforme · {data.datedCount} dates historiques renseignées.</p>
   <p>Statut : à qualifier. Collecte désactivée pour ces candidats. Leur import n’ajoute aucun pronostic au compteur des observations avant match.</p>
   {compact?<InlineLink href="/expert/catalogue-tipsters">Consulter les 317 fiches Ligue 1</InlineLink>:tipsterId?<>
    <InlineLink href="/expert/catalogue-tipsters">Retour aux fiches candidates</InlineLink>
    {selected?<article className="section-card">
     <p>{selected.platform} · À qualifier · Collecte désactivée</p>
     <p>Dernière date déclarée dans l’inventaire : {selected.declaredLastDate??'Non renseignée'}. Elle ne certifie pas une publication avant match.</p>
     <p>Provenance : Catalogue, ligne {selected.origin.row}. Classement historique A, Ligue 1.</p>
     <p>Aucun pronostic collecté n’est attribué à cette fiche par cet import.</p>
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
     <Link className="inline-link" href={`/expert/tipsters/${encodeURIComponent(r.id)}`}>{r.label}</Link> · {r.platform} · À qualifier · {r.declaredLastDate??'Date non renseignée'}
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
