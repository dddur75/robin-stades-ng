import React from 'react';
import type {OLBGPendingObservation} from '../../../scripts/olbg-pending-source';
import {formatDateTime} from '../../i18n';

export function OLBGPendingPanel({observation:o,assigned=false,candidateId}:{observation:OLBGPendingObservation;assigned?:boolean;candidateId?:string}):React.ReactElement{
 return <section aria-label="OLBG : observations source non qualifiées"><h3>OLBG · {o.records.length} observation(s) à qualifier</h3>
  <p>{assigned?"Ces observations sont rattachées au compte source de cette fiche.":"Le rattachement à une fiche tipster reste à établir."} Ces observations ne sont pas admises ; rencontre et antériorité au match restent à vérifier.</p>
  {assigned&&candidateId&&<a className="inline-link" href={"/expert/tipsters/"+encodeURIComponent(candidateId)}>Ouvrir la fiche tipster</a>}
  <p>Compte source : {o.sourceAccountAlias}. Son identité personnelle n’est pas certifiée.</p>
  <p>Observé le {formatDateTime(o.observedAtUTC,true)}. Couverture globale inconnue.</p>
  {o.records.map(record=><article className="section-card" key={record.key}><h4>Choix déclaré : {record.selection}</h4>
   <p>Événement déclaré : {record.eventText}.</p>
   <p>Marché déclaré : {record.marketText||'Non renseigné'}. Type déclaré : {record.betTypeText||'Non renseigné'}.</p>
   <p>Date déclarée par la source : {record.nativeDateText}. Cette valeur ne prouve ni publication ni coup d’envoi.</p>
   <a className="inline-link" href={o.sourceUrl} target="_blank" rel="noopener noreferrer">Consulter le profil source</a>
  </article>)}
  <details><summary>Références du contrôle</summary>{o.claimIds.map(id=><p key={id} style={{overflowWrap:'anywhere'}}>{id}</p>)}</details>
  <p>Interprétation du choix, publication avant match et évaluation des performances non établies. Ces observations restent hors des statistiques des pronostics admis.</p>
 </section>;
}
