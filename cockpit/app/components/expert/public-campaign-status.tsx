"use client";
import {useEffect,useState} from 'react';
import {formatDateTime} from '../../i18n';
import {campaignPresentation,type PublicCampaign} from '../../lib/tipsters-campaign';

export function PublicCampaignStatus({campaign}:{campaign:PublicCampaign}){
 const [now,setNow]=useState<number|null>(null);
 useEffect(()=>{
  const tick=()=>setNow(Date.now());tick();
  const timer=setInterval(tick,1000);
  document.addEventListener('visibilitychange',tick);window.addEventListener('focus',tick);
  return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',tick);window.removeEventListener('focus',tick);};
 },[]);
 const view=now===null?{kind:'unknown',nextAt:null}:campaignPresentation(campaign,now);
 const labels={scheduled:'Programmation confirmée par Windows.',ready:'Tâche Windows prête ; aucun prochain créneau confirmé.',running:'Collecte en cours sur Windows.',
  disabled:'Tâche Windows désactivée.',unknown:'Confirmation Windows à actualiser.',
  no_future_run:'Aucun prochain passage programmé. Les observations sont conservées.',
  halted:'Campagne arrêtée : historique conservé, aucune nouvelle collecte autorisée.',
  expired:'Campagne expirée. Les observations sont conservées.',
  invalid_package:'Paquet de campagne invalide : exécution refusée.',
  blocked_lock:'Collecte bloquée par un verrou : contrôle nécessaire.',
  missed_slot:'Créneau manqué : collecte arrêtée sans rattrapage, observations conservées.',
  completed:'Tous les créneaux sont terminés. Les observations sont conservées.'};
 return <>
  <p role={['halted','invalid_package','blocked_lock','missed_slot'].includes(view.kind)?'alert':'status'}>{labels[view.kind as keyof typeof labels]}</p>
  {view.nextAt&&<p>Prochain créneau Windows : {formatDateTime(view.nextAt,true)}, heure de Paris. Son exécution reste à vérifier.</p>}
 </>;
}

export function PublicCampaignCounters({campaign}:{campaign:PublicCampaign}){
 const values=[campaign.successfulSlots,campaign.requests,campaign.requestsMax];
 if(!values.every(v=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0))return <p>Compteurs indisponibles : preuves de campagne incomplètes.</p>;
 return <p>{campaign.successfulSlots} créneau(x) validé(s) · {campaign.requests} GET réservés sur {campaign.requestsMax} maximum.</p>;
}
