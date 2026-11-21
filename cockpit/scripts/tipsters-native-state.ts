import {execFile} from 'node:child_process';
import {resolve} from 'node:path';
import {promisify} from 'node:util';
import {isRosterAuthor,ROSTER_NEXT_CAMPAIGN_ID} from './roster-task-authority';
export type TaskState={state:string;enabled?:boolean;verifiedAt?:string};
type NativeState=TaskState&{sro?:TaskState;sroNext?:TaskState;olbg?:TaskState;expansion?:TaskState;hepter?:TaskState;roster?:TaskState;rosterNext?:TaskState;notbetting?:TaskState};
const runFile=promisify(execFile);
const sroNextOwners=new Set([13380,13604,14868,15220,15388,15772,15921,16361].map(id=>'https://forum.stade-rennais-online.com/profile.php?id='+id));

export function sourceTaskIsCurrent(value:TaskState|undefined,now=Date.now()):boolean{
 const age=now-Date.parse(value?.verifiedAt??'');
 return Boolean(value?.enabled && ['Ready','Running'].includes(value.state)&&age>=0&&age<=30000);
}

export function projectNativeState(value:NativeState,now=Date.now()):NativeState{
 const old=(s:TaskState)=>now-Date.parse(s.verifiedAt??'')>30000?{...s,state:'stale',enabled:false}:s;
 const child=(s:TaskState|undefined)=>s?old(s):{state:value.state==='unavailable'?'unavailable':'checking'};
 return {...old(value),sro:child(value.sro),sroNext:child(value.sroNext),olbg:child(value.olbg),expansion:child(value.expansion),hepter:child(value.hepter),roster:child(value.roster),rosterNext:child(value.rosterNext),notbetting:child(value.notbetting)};
}

export function createNativeStateReader(load:(root:string)=>Promise<NativeState>,now=Date.now):(root:string)=>Promise<NativeState>{
 let state:NativeState={state:'checking'};
 let pending:Promise<void>|undefined;
 let refreshed=-Infinity;
 return async(root:string)=>{
  if(!pending&&now()-refreshed>=15000){
   pending=Promise.resolve().then(()=>load(root))
    .then(value=>{state=value;})
    .catch(()=>{state={state:'unavailable'};})
    .finally(()=>{refreshed=now();pending=undefined;});
  }
  if(pending)await pending;
  return projectNativeState(state,now());
 };
}

const readWindowsNativeState=createNativeStateReader(async(root:string)=>{
 const result=await runFile('pwsh.exe',['-NoProfile','-NonInteractive','-File',resolve(root,'scripts/read-public-task-state.ps1')],{timeout:8000,maxBuffer:30000,windowsHide:true,encoding:'utf8'});
 return JSON.parse(result.stdout) as NativeState;
});

export async function readNativeState(root:string):Promise<NativeState>{
 if(process.platform!=='win32')return{state:'unavailable'};
 return readWindowsNativeState(root);
}

export function gateSourceOperations(data:{candidates:{collectionEnabled:boolean;qualification?:{sourceId?:string;sroNextCampaignId?:string;sroNextAuthorUrl?:string;expansionCampaignId?:string;expansionAuthorUrl?:string;profileCampaignId?:string;profileAuthorUrl?:string;rosterCampaignId?:string;rosterAuthorUrl?:string}}[];rosterAssessments?:{collectionEnabled:boolean;qualification?:{sourceId?:string;sroNextCampaignId?:string;sroNextAuthorUrl?:string;expansionCampaignId?:string;expansionAuthorUrl?:string;profileCampaignId?:string;profileAuthorUrl?:string;rosterCampaignId?:string;rosterAuthorUrl?:string}}[];enabledCount:number;qualification:{operationalBySource?:Record<string,boolean>;sourceOperational?:boolean;nativeSRO?:TaskState;nativeSRONext?:TaskState;nativeOLBG?:TaskState;nativeExpansion?:TaskState;nativeRoster?:TaskState;nativeRosterNext?:TaskState}},native:NativeState,now=Date.now()):void{
 const states=data.qualification.operationalBySource??{'SRC_039':Boolean(data.qualification.sourceOperational)};
 const allowed:Record<string,boolean>={'SRC_039':Boolean(states.SRC_039&&sourceTaskIsCurrent(native.sro,now)),'SRC_014':Boolean(states.SRC_014&&sourceTaskIsCurrent(native.olbg,now))};
 data.qualification.nativeSRONext=native.sroNext;data.qualification.nativeSRO=native.sro;data.qualification.nativeOLBG=native.olbg;
 data.qualification.nativeExpansion=native.expansion;data.qualification.nativeRoster=native.roster;data.qualification.nativeRosterNext=native.rosterNext;
 data.qualification.operationalBySource=allowed;data.qualification.sourceOperational=allowed.SRC_039;
 for(const row of [...data.candidates,...(data.rosterAssessments??[])]){
  const q=row.qualification;
  const permitted=q&&('sroNextCampaignId' in q||'sroNextAuthorUrl' in q)
   ?q.sroNextCampaignId==='ROBIN-SRO-NEXT3-20261121'&&q.sourceId==='SRC_039'&&sroNextOwners.has(q.sroNextAuthorUrl??'')&&native.sroNext?.enabled===true&&sourceTaskIsCurrent(native.sroNext,now)
   :q?.rosterCampaignId
   ?isRosterAuthor(q.rosterCampaignId,q.rosterAuthorUrl)&&sourceTaskIsCurrent(q.rosterCampaignId===ROSTER_NEXT_CAMPAIGN_ID?native.rosterNext:native.roster,now)
   :q?.profileCampaignId
   ?q.profileCampaignId==='ROBIN-OLBG-HEPTER669088-E2V2-20261120'&&q.profileAuthorUrl==='https://www.olbg.com/tipsters/tips/669088'&&sourceTaskIsCurrent(native.hepter,now)
   :q?.expansionCampaignId
   ?q.expansionCampaignId==='ROBIN-OLBG-EXPANDED383717-20261120'&&q.expansionAuthorUrl==='https://www.olbg.com/tipsters/tips/383717'&&sourceTaskIsCurrent(native.expansion,now)
   :allowed[q?.sourceId??'SRC_039'];
  row.collectionEnabled=Boolean(row.collectionEnabled&&permitted);
 }
 data.enabledCount=data.candidates.filter(row=>row.collectionEnabled).length;
}
