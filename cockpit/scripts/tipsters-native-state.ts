import {execFile} from 'node:child_process';
import {resolve} from 'node:path';
import {promisify} from 'node:util';
export type TaskState={state:string;enabled?:boolean;verifiedAt?:string};
type NativeState=TaskState&{sro?:TaskState};
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
 return {...old(state),sro:state.sro?old(state.sro):{state:'checking'}};
}
