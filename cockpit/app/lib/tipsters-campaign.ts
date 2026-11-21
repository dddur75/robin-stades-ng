export type PublicCampaign = {
 state:string; startsAt?:string; expiresAt?:string; slots?:number; requests?:number;
 requestsMax?:number; successfulSlots?:number;
 native?:{state:string;enabled?:boolean;verifiedAt?:string;nextRunTime?:string};
};

type Kind='scheduled'|'ready'|'running'|'disabled'|'unknown'|'halted'|'expired'|'invalid_package'|'blocked_lock'|'missed_slot'|'completed'|'no_future_run';
export function campaignPresentation(campaign:PublicCampaign,now:number):{kind:Kind;nextAt:string|null}{
 const stopped=['halted','expired','invalid_package','blocked_lock','missed_slot','completed'] as const;
 for(const kind of stopped)if(campaign.state===kind)return{kind,nextAt:null};
 const expires=Date.parse(campaign.expiresAt??'');
 if(Number.isFinite(expires)&&expires<=now)return{kind:'expired',nextAt:null};
 const native=campaign.native;
 const age=now-Date.parse(native?.verifiedAt??'');
 if(!(age>=0&&age<=30000))return{kind:'unknown',nextAt:null};
 if(native?.state==='invalid_package')return{kind:'invalid_package',nextAt:null};
 if(['unavailable','stale','checking','not_found'].includes(native?.state??''))return{kind:'unknown',nextAt:null};
 if(native?.state==='Disabled'||native?.enabled===false)return{kind:'disabled',nextAt:null};
 if(Number.isFinite(expires)&&['scheduled','collecting'].includes(campaign.state)&&native?.enabled===true&&native.state==='no_future_run')return{kind:'no_future_run',nextAt:null};
 if(!Number.isFinite(expires)||!['scheduled','collecting'].includes(campaign.state)||
  native?.enabled!==true||!['Ready','Running'].includes(native.state)||!(age>=0&&age<=30000))return{kind:'unknown',nextAt:null};
 const next=Date.parse(native.nextRunTime??'');
 const start=campaign.startsAt===undefined?-Infinity:Date.parse(campaign.startsAt);
 const nextAt=next>now&&next<expires&&next>=start?native.nextRunTime!:null;
 return{kind:native.state==='Running'?'running':nextAt?'scheduled':'ready',nextAt};
}
