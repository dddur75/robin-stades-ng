"use client";
import Link from 'next/link';
import {useEffect,useState} from 'react';
import {formatDateTime} from '../../i18n';

type Access={label:string;reason:string;requiredAccess:string;ownerAction:string};
type Row={recordId:string;label:string;platform:string;kind:string;sheet:string;row:number;sourceUrl:string|null;collectionEnabled:boolean;qualifiedRecordId?:string;qualification?:Access&{personallyProven:boolean};platformAssessment?:Access;historicalLevel?:string|null;historicalL1?:string|null;fields?:Record<string,string>};
type Data={status:string;records:Row[];total:number;addressCount:number;profileRows:number;referenceRows:number;page:number;limit:number;sheets:string[];platforms:string[];headers:Record<string,string>;receipt:{claimId:string;workbookSha256:string};qualifiedRegistryState?:string;readAt?:string;personalAccessState?:string};
export function WorkbookCatalogue(){
 const [q,setQ]=useState(''),[sheet,setSheet]=useState(''),[platform,setPlatform]=useState(''),[page,setPage]=useState(0),[id,setId]=useState('');
 const [revision,setRevision]=useState(0);
 const [data,setData]=useState<Data|null>(null),[loadedKey,setLoadedKey]=useState(''),[failedKey,setFailedKey]=useState<string|null>(null);
 const requestKey=JSON.stringify([q,sheet,platform,page,id,revision]);const error=failedKey===requestKey;const loading=loadedKey!==requestKey&&!error;
 useEffect(()=>{const timer=setTimeout(()=>{const selected=new URLSearchParams(window.location.search).get('id');if(selected&&selected.length<=100)setId(selected);},0);return()=>clearTimeout(timer);},[]);
 useEffect(()=>{const c=new AbortController();
  const timer=setTimeout(()=>{const p=new URLSearchParams({q,sheet,platform,page:String(page),limit:'25',...(id?{id}:{})});
   void fetch(`/api/tipsters/workbook?${p}`,{cache:'no-store',signal:AbortSignal.any([c.signal,AbortSignal.timeout(20000)])}).then(async r=>{const d=await r.json();if(!r.ok||d.status!=='ok')throw Error('unavailable');if(!c.signal.aborted){setData(d);setLoadedKey(requestKey);setFailedKey(null);}}).catch(()=>{if(!c.signal.aborted)setFailedKey(requestKey);});},250);
  return()=>{clearTimeout(timer);c.abort();};},[q,sheet,platform,page,id,requestKey]);
 const change=()=>{setPage(0);setId('');};
 return <section className="section-card">
  <p><Link className="inline-link" href="/expert/catalogue-tipsters">Fiches et preuves Ligue 1</Link></p>
  {error?<p role="alert">Le catalogue complet est indisponible. Les fiches Ligue 1 restent accessibles par le lien ci-dessus.</p>:data&&<>
   <p><strong>{data.addressCount.toLocaleString('fr-FR')} adresses distinctes</strong> dans Catalogue et Profils FR. {data.referenceRows.toLocaleString('fr-FR')} lignes de référence dans {data.sheets.length} onglets.</p>
   <p>Usage personnel local confirmé. Une référence peut désigner un auteur, un concours, un fil, une plateforme ou un dépôt. La lecture effective, le choix personnel et sa chronologie restent à établir pour chaque fiche.</p>
   <p>États de collecte relevés {data.readAt?`le ${formatDateTime(data.readAt,true)}`:'à une date non disponible'}. <button className="inline-link" onClick={()=>setRevision(n=>n+1)}>Actualiser les états</button></p>
   {data.qualifiedRegistryState==='unavailable'&&<p role="alert">Les états actuels du registre qualifié sont indisponibles ; aucune activation n’est déduite de l’inventaire.</p>}
   {data.personalAccessState==='unavailable'&&<p role="alert">L’actualisation personnelle est indisponible. Les évaluations précédentes restent affichées avec leur provenance.</p>}
  </>}
  <div className="filter-panel pilot-filters">
   <label>Rechercher dans le classeur<input type="search" maxLength={120} value={q} onChange={e=>{setQ(e.target.value);change();}}/></label>
   <label>Onglet<select aria-label="Onglet" value={sheet} onChange={e=>{setSheet(e.target.value);setPlatform('');change();}}><option value="">Catalogue et Profils FR</option>{data?.sheets.map(s=><option key={s}>{s}</option>)}</select></label>
   <label>Plateforme du profil<select aria-label="Plateforme du profil" value={platform} onChange={e=>{setPlatform(e.target.value);change();}}><option value="">Toutes les plateformes</option>{data?.platforms.map(p=><option key={p}>{p}</option>)}</select></label>
  </div>
  {loading?<p role="status">Lecture de la page du catalogue…</p>:!error&&data&&<>
   <p role="status">{data.total.toLocaleString('fr-FR')} référence(s) trouvée(s). Page {page+1} sur {Math.max(1,Math.ceil(data.total/data.limit))}.</p>
   {id?<button className="pilot-button" onClick={()=>setId('')}>Retour aux résultats</button>:null}
   {!data.records.length&&<p>Aucune référence ne correspond à ces filtres.</p>}
   <ul>{data.records.map(r=><li key={r.recordId} style={{overflowWrap:'anywhere',marginBottom:'1rem'}}>
    <button className="inline-link" onClick={()=>{setId(r.recordId);setPage(0);}}>{r.label}</button> · {r.platform||r.kind} · {r.sheet}, ligne {r.row}
    <p>{r.collectionEnabled?(data.readAt?'Collecte activée lors du relevé daté ci-dessus':'État de campagne à actualiser'):r.qualification?.label??'Référence inventoriée, qualification individuelle à établir'}</p>
    {id&&<>
     <p>{r.qualification?.reason??r.platformAssessment?.reason??'Aucune preuve personnelle actuelle ni autorisation de collecte n’est attribuée à cette référence par l’import.'}</p>
     {(r.qualification??r.platformAssessment)&&<><p>Accès à établir : {(r.qualification??r.platformAssessment)?.requiredAccess}</p><p>{(r.qualification??r.platformAssessment)?.ownerAction}</p></>}
     {r.sourceUrl&&<p><a className="inline-link" href={r.sourceUrl} target="_blank" rel="noopener noreferrer">Ouvrir la référence d’origine</a></p>}
     {r.qualifiedRecordId&&<p><Link className="inline-link" href={`/expert/tipsters/${encodeURIComponent(r.qualifiedRecordId)}`}>Consulter la fiche et ses preuves qualifiées</Link></p>}
     <details><summary>Champs historiques du classeur</summary><dl>{Object.entries(r.fields??{}).map(([k,v])=><div key={k}><dt><strong>{data.headers[k]??k}</strong></dt><dd>{v}</dd></div>)}</dl></details>
    </>}
   </li>)}</ul>
   {!id&&<nav className="pilot-actions" aria-label="Pages du catalogue complet"><button className="pilot-button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Page précédente</button><button className="pilot-button" disabled={(page+1)*data.limit>=data.total} onClick={()=>setPage(p=>p+1)}>Page suivante</button></nav>}
   <details><summary>Provenance du catalogue complet</summary><p>{data.receipt.claimId}</p><code style={{overflowWrap:'anywhere'}}>{data.receipt.workbookSha256}</code></details>
  </>}
 </section>;
}
