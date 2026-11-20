import {execFile} from 'node:child_process';
import {resolve} from 'node:path';
import {promisify} from 'node:util';
export type TaskState={state:string;enabled?:boolean;verifiedAt?:string};
type NativeState=TaskState&{sro?:TaskState;olbg?:TaskState;expansion?:TaskState};
const runFile=promisify(execFile);
let state:NativeState={state:'checking'};
let pending:Promise<void>|undefined;
let refreshed=0;

export function sourceTaskIsCurrent(value:TaskState|undefined,now=Date.now()):boolean{
 const age=now-Date.parse(value?.verifiedAt??'');
 return Boolean(value?.enabled && ['Ready','Running'].includes(value.state)&&age>=0&&age<=30000);
}

export function readNativeState(root:string):NativeState{
 if(process.platform!=='win32')return{state:'unavailable'};
 if(!pending&&Date.now()-refreshed>=15000){
  pending=runFile('pwsh.exe',['-NoProfile','-NonInteractive','-File',resolve(root,'scripts/read-public-task-state.ps1')],{timeout:8000,maxBuffer:30000,windowsHide:true,encoding:'utf8'})
   .then(r=>{state=JSON.parse(r.stdout);})
   .catch(()=>{state={state:'unavailable'};})
   .finally(()=>{refreshed=Date.now();pending=undefined;});
 }
 const old=(s:TaskState)=>Date.now()-Date.parse(s.verifiedAt??'')>30000?{...s,state:'stale',enabled:false}:s;
 return {...old(state),sro:state.sro?old(state.sro):{state:'checking'},olbg:state.olbg?old(state.olbg):{state:'checking'},expansion:state.expansion?old(state.expansion):{state:'checking'}};
}

export function gateSourceOperations(data:{candidates:{collectionEnabled:boolean;qualification?:{sourceId?:string;expansionCampaignId?:string;expansionAuthorUrl?:string}}[];enabledCount:number;qualification:{operationalBySource?:Record<string,boolean>;sourceOperational?:boolean;nativeSRO?:TaskState;nativeOLBG?:TaskState;nativeExpansion?:TaskState}},native:NativeState,now=Date.now()):void{
 const states=data.qualification.operationalBySource??{'SRC_039':Boolean(data.qualification.sourceOperational)};
 const allowed:Record<string,boolean>={'SRC_039':Boolean(states.SRC_039&&sourceTaskIsCurrent(native.sro,now)),'SRC_014':Boolean(states.SRC_014&&sourceTaskIsCurrent(native.olbg,now))};
 data.qualification.nativeSRO=native.sro;data.qualification.nativeOLBG=native.olbg;
 data.qualification.nativeExpansion=native.expansion;
 data.qualification.operationalBySource=allowed;data.qualification.sourceOperational=allowed.SRC_039;
 for(const row of data.candidates){
  const q=row.qualification;
  const permitted=q?.expansionCampaignId
   ?q.expansionCampaignId==='ROBIN-OLBG-EXPANDED383717-20261120'&&q.expansionAuthorUrl==='https://www.olbg.com/tipsters/tips/383717'&&sourceTaskIsCurrent(native.expansion,now)
   :allowed[q?.sourceId??'SRC_039'];
  row.collectionEnabled=Boolean(row.collectionEnabled&&permitted);
 }
 data.enabledCount=data.candidates.filter(row=>row.collectionEnabled).length;
}
