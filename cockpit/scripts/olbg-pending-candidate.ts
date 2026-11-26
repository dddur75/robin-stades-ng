import {projectOLBGPending,type OLBGApproval} from './olbg-pending-source';
import {OLBG_REVIEWED_APPROVAL,OLBG_REVIEWED_CANDIDATE as target} from './olbg-reviewed-pending-approval';
function object(v:unknown):v is Record<string,unknown>{return v!==null&&typeof v==='object'&&!Array.isArray(v);}
export function applyReviewedOLBGPendingToCandidate<T extends object>(base:T,raw:Uint8Array,receipt:Uint8Array,a:Readonly<OLBGApproval>=OLBG_REVIEWED_APPROVAL):T{
 try{
 const observation=projectOLBGPending(raw,receipt,a),rows=(base as {candidates?:unknown}).candidates;
 if(!Array.isArray(rows)||observation.sourceUrl!==target.sourceUrl)return base;
 const matches=rows.filter(v=>object(v)&&v.id===target.id);
 if(matches.length!==1)return base;
 const row=matches[0];
 if(!object(row)||row.platform!=='OLBG'||row.sourceUrl!==target.sourceUrl||!object(row.origin)||row.origin.sheet!==target.originSheet||row.origin.row!==target.originRow)return base;
 return {...base,candidates:rows.map(v=>v===row?{...row,pendingOLBGObservation:observation}:v)} as T;
 }catch{return base;}
}
