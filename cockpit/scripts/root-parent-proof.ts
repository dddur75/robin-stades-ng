import {createHash} from 'node:crypto';
import {closeSync,fstatSync,openSync,readSync} from 'node:fs';
import {resolve} from 'node:path';
import type {ParentProofIO} from './olbg-campaign-companion';

type J=Record<string,unknown>;
export type RootNamespaceRecord=Readonly<{path:string;sha256:string}>;
const CAPS={'primary.json':32768,'result.json':8192,'AUTHOR-STOP.json':4096} as const;
const NS_KEYS='schemaVersion campaignId campaignDirectory controlsRoot returnsRoot slots parentCallerSHA256 rootWrapperSHA256'.split(' ');
function check(v:unknown):asserts v{if(!v)throw Error('ROOT_PARENT_PROOF_UNAVAILABLE');}
function obj(v:unknown):J{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as J;}
function str(v:unknown):string{check(typeof v==='string'&&v.length>0&&v.length<=1024);return v;}
function hash(raw:Uint8Array|string):string{return createHash('sha256').update(raw).digest('hex');}
function read(path:string,cap:number):Uint8Array{check(resolve(path)===path);const fd=openSync(path,'r');try{const size=fstatSync(fd).size;check(size>0&&size<=cap&&Number.isSafeInteger(size));const b=Buffer.alloc(size+1),n=readSync(fd,b,0,b.length,0);check(n===size);return b.subarray(0,n);}finally{closeSync(fd);}}
function decode(raw:Uint8Array):J{return obj(JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(raw)));}
function namespace(record:RootNamespaceRecord):J{
 const raw=read(record.path,16384);check(hash(raw)===record.sha256);const ns=decode(raw);
 check(Object.keys(ns).length===NS_KEYS.length&&NS_KEYS.every(k=>Object.hasOwn(ns,k))&&ns.schemaVersion==='olbg-root-parent-namespace-v1');
 check(Array.isArray(ns.slots)&&ns.slots.length>0&&ns.slots.length<=12&&new Set(ns.slots).size===ns.slots.length);
 for(const key of ['campaignDirectory','controlsRoot','returnsRoot'])check(resolve(str(ns[key]))===ns[key]);
 return ns;
}
export function createRootParentProofIO(record:RootNamespaceRecord|null=null):ParentProofIO|undefined{
 if(record===null)return undefined;
 try{namespace(record);}catch{return undefined;}
 return {
  loadControl(slot,name){
   const ns=namespace(record);check((ns.slots as unknown[]).includes(slot)&&Object.hasOwn(CAPS,name));
   return read(resolve(str(ns.controlsRoot),hash(slot),name),CAPS[name]);
  },
  confirmExit(campaignId,slot,receiptSHA256){
   try{
    const ns=namespace(record);if(ns.campaignId!==campaignId||!(ns.slots as unknown[]).includes(slot))return false;
    const token=hash(slot),p=decode(read(resolve(str(ns.returnsRoot),'root-parent-return-'+token+'.json'),4096));
    check(p.schemaVersion==='olbg-root-parent-return-v1'&&p.campaignId===campaignId&&p.slot===slot&&p.parentExit===0&&p.parentReceiptSHA256===receiptSHA256&&p.parentCallerSHA256===ns.parentCallerSHA256&&p.rootWrapperSHA256===ns.rootWrapperSHA256&&p.rootGuardBeforeProof===true);
    check(['timedOut','overflow','readError','veto','sourceReady'].every(k=>p[k]===false));
    const raw=read(resolve(str(ns.returnsRoot),'root-parent-primary-'+token+'.json'),32768);check(hash(raw)===p.rootPrimarySHA256);
    const primary=decode(raw),stdout=obj(primary.stdout),stderr=obj(primary.stderr);
    check(primary.schemaVersion==='olbg-root-parent-process-v1'&&primary.parentExit===0&&['timedOut','overflow','readError','veto'].every(k=>primary[k]===false)&&stderr.bytes===0);
    const encoded=str(stdout.base64),bytes=Buffer.from(encoded,'base64');check(bytes.length<=8192&&bytes.toString('base64')===encoded&&bytes.length===stdout.bytes&&hash(bytes)===stdout.sha256);
    const returned=decode(bytes);return returned.accepted===true&&returned.parentReceiptSHA256===receiptSHA256;
   }catch{return false;}
  }
 };
}
