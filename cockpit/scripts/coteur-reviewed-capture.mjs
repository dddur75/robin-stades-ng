import{createHash}from'node:crypto';
import{readFileSync,lstatSync}from'node:fs';
import{isAbsolute}from'node:path';
const HASH=/^[a-f0-9]{64}$/;
const ROUTES=new Set(['/api/tipsters/public','/api/tipsters/candidates','/api/tipsters/qualification']);
const KEYS=['C0','C1','C3','C4'];
export const COTEUR_APP_PURPOSE='COTEUR_REVIEWED_PROFILES_APP_PROJECTION_V1';
const need=v=>{if(!v)throw Error('COTEUR_REVIEWED_CAPTURE_UNAVAILABLE')};
const sha=v=>createHash('sha256').update(v).digest('hex');
export function canonical(v){if(Array.isArray(v))return'['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';const s=JSON.stringify(v);need(s!==undefined);return s}
const equal=(a,b)=>canonical(a)===canonical(b);
const obj=v=>{need(v&&typeof v==='object'&&!Array.isArray(v));return v};
const list=v=>{need(Array.isArray(v)&&v.length<=2000);return v};
const stamp=v=>{need(typeof v==='string'&&/(Z|\+00:00)$/.test(v)&&Number.isFinite(Date.parse(v)));return Date.parse(v)};
function bytes(path,cap){need(typeof path==='string'&&isAbsolute(path));const st=lstatSync(path);need(st.isFile()&&!st.isSymbolicLink()&&st.size>0&&st.size<=cap);const b=readFileSync(path);need(b.length===st.size);return b}
function pinned(path,digest,cap){need(HASH.test(digest));const b=bytes(path,cap);need(sha(b)===digest);return b}
const decode=b=>obj(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(b)));
export function approvalBinding(approval){const{grantHash,bindingSHA256,...binding}=approval;return sha(canonical(binding))}
export function readReviewedCoteur(approval,now=Date.now()){
 const a=obj(approval);need(HASH.test(a.bindingSHA256)&&approvalBinding(a)===a.bindingSHA256&&now<stamp(a.expiresAt));
 need(Array.isArray(a.consumerPins)&&a.consumerPins.length>0&&a.consumerPins.length<=20);
 for(const r of a.consumerPins)pinned(r.path,r.sha256,2000000);
 const packet=decode(pinned(a.packetPath,a.packetSHA256,4000000));
 need(packet.schemaVersion==='robin-coteur-reviewed-profiles-v1'&&packet.claimId===a.claimId);
 const fixtures=list(packet.fixtures),source=obj(packet.source);need(stamp(source.observedAt)<=now+300000);
 const byFixture=new Map();for(const f of fixtures){need(typeof f.id==='string'&&!byFixture.has(f.id));stamp(f.kickoff);byFixture.set(f.id,f)}
 const picks=list(packet.picks),candidates=list(packet.candidates),admin=obj(packet.adminResult);
 need(candidates.length>0&&candidates.length<=300&&picks.length<=2000);
 const ids=new Set(),authors=new Set();
 for(const p of picks){const f=byFixture.get(p.fixtureId);need(f&&typeof p.id==='string'&&!ids.has(p.id)&&typeof p.authorId==='string'&&stamp(p.observedAt)<stamp(f.kickoff)&&p.market==='source_native_opaque'&&p.sourceBetType==='native_ticket_component'&&p.settlementAllowed===false&&p.performanceEvaluationAllowed===false);ids.add(p.id);authors.add(p.authorId)}
 const candidateIds=new Set();for(const c of candidates){need(/^catalogue:[a-f0-9]{64}$/.test(c.id)&&!candidateIds.has(c.id)&&c.platform==='Coteur'&&c.qualification?.profileVisited===true&&Array.isArray(c.qualification.picks)&&c.qualification.personallyProven===(c.qualification.picks.length>0));candidateIds.add(c.id);for(const p of c.qualification.picks)need(ids.has(p.id)&&p.authorId===c.id&&equal(p,picks.find(x=>x.id===p.id)))}
 for(const a of authors)need(candidateIds.has(a));
 need(typeof admin.id==='string'&&Array.isArray(admin.claims)&&admin.claims.includes(a.claimId)&&stamp(admin.checkedAt)<=now+300000);
 const ledger=bytes(a.ledgerPath,16000000),prefix=obj(a.ledgerPrefix);need(Number.isSafeInteger(prefix.bytes)&&prefix.bytes>0&&prefix.bytes<=ledger.length&&sha(ledger.subarray(0,prefix.bytes))===prefix.sha256);
 const headRows=ledger.subarray(0,prefix.bytes).toString('utf8').trimEnd().split('\n');need(JSON.parse(headRows.at(-1)).hash===prefix.head);
 const tail=ledger.subarray(prefix.bytes);need(tail.length===0||tail.at(-1)===10);
 let previous=prefix.head;const rows=[];
 for(const line of tail.toString('utf8').split('\n').filter(Boolean)){const r=obj(JSON.parse(line)),{hash,...body}=r;need(canonical(r)===line&&HASH.test(hash)&&r.previous_hash===previous&&sha(canonical(body))===hash);rows.push(r);previous=hash}
 // Authority must be a new append after the bound prefix, never an inferred historic grant.
 const matches=rows.filter(r=>r.hash===a.grantHash);need(matches.length===1);const grant=matches[0],g=obj(grant.context);
 need(grant.record_type==='DECISION'&&grant.decision==='PASS_AND_SCALE'&&grant.responsible==='C0'&&stamp(grant.date)<=now&&g.mission_id===a.missionId&&g.stage==='E2'&&equal(g.keys,KEYS)&&g.purpose===COTEUR_APP_PURPOSE&&g.sourceAllowed===false&&g.appProjectionAllowed===true&&g.bindingSHA256===a.bindingSHA256&&g.packetSHA256===a.packetSHA256);
 for(const r of rows.slice(rows.indexOf(grant)+1)){const c=r.context??{},same=c.mission_id===a.missionId;need(!(r.record_type==='VETO'&&(c.global===true||c.severity==='CRITICAL'||c.mission_id===undefined||c.mission_id==='GLOBAL'||same))&&!(same&&(c.authorityClosed===true||['FAILURE','REDESIGN'].includes(r.record_type)||['FAIL_AND_STOP','FAIL_AND_REDESIGN','BLOCKED_EXTERNAL_ACTION'].includes(r.decision))))}
 return packet;
}
function mergeExact(base,delta){const out=list(base).slice(),seen=new Map();for(const x of out){need(x&&typeof x.id==='string'&&!seen.has(x.id));seen.set(x.id,x)}for(const x of list(delta)){if(seen.has(x.id))need(equal(seen.get(x.id),x));else{need(out.length<2000);out.push(x);seen.set(x.id,x)}}return out}
export function projectReviewedResponse(route,base,packet){
 need(base.status==='ok');
 if(route==='/api/tipsters/public'){const picks=mergeExact(base.picks,packet.picks),fixtures=list(base.fixtures).slice();for(const f of packet.fixtures){const old=fixtures.find(x=>x.id===f.id);if(old)need(['id','label'].every(k=>equal(old[k],f[k]))&&stamp(old.kickoff)===stamp(f.kickoff));else fixtures.push(f)}return{...base,picks,fixtures,distinctPicks:picks.length,authorCount:new Set(picks.map(p=>p.authorId)).size,claimIds:[...new Set([...(base.claimIds??[]),packet.claimId])],reviewedCoteurCapture:{claimId:packet.claimId,profiles:packet.candidates.length,records:packet.picks.length,source:packet.source}}}
 if(route==='/api/tipsters/candidates'){const candidates=list(base.candidates).slice(),positions=new Map(candidates.map((c,i)=>[c.id,i]));for(const c of packet.candidates){const at=positions.get(c.id);if(at!==undefined){const old=candidates[at];need(old.platform==='Coteur'&&old.sourceUrl===c.sourceUrl);candidates[at]={...old,qualification:c.qualification,reviewedNativeCapture:c.reviewedNativeCapture}}else{need(candidates.length<2000);candidates.push(c);positions.set(c.id,candidates.length-1)}}return{...base,candidates,count:candidates.length,datedCount:candidates.filter(c=>c.declaredLastDate!==null&&c.declaredLastDate!==undefined).length,platformCount:new Set(candidates.map(c=>c.platform)).size,qualification:base.qualification?.status==='ok'?{...base.qualification,qualifiedCount:candidates.filter(c=>c.qualification?.personallyProven===true).length}:base.qualification}}
 const results=mergeExact(base.results,[packet.adminResult]);return{...base,results,capturedAt:new Date(Math.max(stamp(base.capturedAt),stamp(packet.adminResult.checkedAt))).toISOString()};
}
export function createCoteurProjectionMiddleware(approval){
 return function reviewedCoteur(req,res,next){
  let path;try{path=new URL(req.url,'http://127.0.0.1').pathname}catch{return next()}
  if(req.method!=='GET'||!ROUTES.has(path))return next();
  if(approval===null)return next();
 const originalEnd=res.end.bind(res);let chunks=[],total=0,finished=false;
  const fail=()=>{chunks=[];res.statusCode=503;res.removeHeader('Content-Length');res.removeHeader('Content-Encoding');res.setHeader('Content-Type','application/json; charset=utf-8');return originalEnd(JSON.stringify({status:'unavailable',error:'COTEUR_REVIEWED_CAPTURE_UNAVAILABLE'}))};
  const add=(chunk,encoding)=>{if(chunk!==undefined&&chunk!==null){const b=Buffer.isBuffer(chunk)?chunk:Buffer.from(chunk,typeof encoding==='string'?encoding:undefined);total+=b.length;need(total<=8000000);chunks.push(b)}};
  res.write=function(chunk,encoding,callback){try{add(chunk,encoding);if(typeof encoding==='function')encoding();else if(typeof callback==='function')callback();return true}catch{finished=true;fail();return false}};
  res.end=function(chunk,encoding,callback){
   if(finished)return res;finished=true;
   try{add(chunk,encoding);const body=Buffer.concat(chunks);chunks=[];
    if(res.statusCode!==200)return originalEnd(body,typeof encoding==='function'?encoding:callback);
    need(!res.getHeader('Content-Encoding')||res.getHeader('Content-Encoding')==='identity');
    const packet=readReviewedCoteur(approval),base=decode(body),merged=projectReviewedResponse(path,base,packet),out=Buffer.from(JSON.stringify(merged));
    res.removeHeader('ETag');res.setHeader('Content-Length',String(out.length));res.setHeader('Content-Type','application/json; charset=utf-8');
    return originalEnd(out,typeof encoding==='function'?encoding:callback);
   }catch{return fail()}
  };
  return next();
 };
}
