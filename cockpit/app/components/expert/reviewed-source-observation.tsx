import {formatDateTime} from '../../i18n';
import type {ReviewedSourceObservation} from '../../../scripts/catalogue-independent';
export function ReviewedSourceObservationPanel({observation:o}:{observation:ReviewedSourceObservation}){
 return <section aria-label="Observation récente de cette référence">
  <h4>Observation récente de cette référence</h4>
  <p>Lecture du {formatDateTime(o.sourceObservedAtUTC,true)} : {o.messageCount} messages structurés non qualifiés ; {o.admittedForecasts} pronostic admis.</p>
  <p>Publications de ce préfixe : {formatDateTime(o.publishedFrom,true)} au {formatDateTime(o.publishedThrough,true)}. Suite non examinée ; nombre total inconnu.</p>
  <p>Attribution au canal uniquement ; personne, rencontre et choix non qualifiés. Aucune collecte récurrente activée.</p>
  <p>Aucune correspondance littérale dans le programme borné de neuf rencontres ; aucune absence globale déduite.</p>
  <p><a className="inline-link" href={o.adminHref}>Consulter les contrôles dans l’administration</a></p>
  <small style={{overflowWrap:'anywhere'}}>Preuves : {o.claimIds.join(' · ')}</small>
 </section>;
}
