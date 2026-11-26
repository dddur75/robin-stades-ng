import {createHash} from 'node:crypto';
type J=Record<string,unknown>;
const HASH=/^[a-f0-9]{64}$/;
const FLAGS=['performanceEvaluationAllowed','settlementAllowed','marketInterpretationAllowed'];
function check(v:unknown):asserts v{if(!v)throw Error('OLBG_CAMPAIGN_COMPANION_REFUSED');}
function obj(v:unknown):J{check(v!==null&&typeof v==='object'&&!Array.isArray(v));return v as J;}
function arr(v:unknown,max=2000):unknown[]{check(Array.isArray(v)&&v.length<=max);return v;}
function text(v:unknown,max=240):string{check(typeof v==='string'&&v.length>0&&v.length<=max);return v;}
function integer(v:unknown):number{check(typeof v==='number'&&Number.isSafeInteger(v)&&v>0);return v;}
function canonical(v:unknown):string{
 if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';
 if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical((v as J)[k])).join(',')+'}';
 const s=JSON.stringify(v);check(s!==undefined);return s;
}
function hash(v:Uint8Array|string):string{return createHash('sha256').update(v).digest('hex');}
function equal(a:unknown,b:unknown):boolean{return canonical(a??null)===canonical(b??null);}
function utc(v:unknown):number{const s=text(v,80);check(/(?:Z|\+00:00)$/.test(s));const n=Date.parse(s);check(Number.isFinite(n));return n;}
function decode(raw:Uint8Array,sha:string,cap:number):unknown{check(raw.length>0&&raw.length<=cap&&HASH.test(sha)&&hash(raw)===sha);return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}
export function readAcceptedOLBGMultiNativeBatch(batchRaw:Uint8Array,digest:string,plan:J,expectedResponseSHA:string,expectedCount:unknown):J[]{
 const profileId=plan.profileId;check(typeof profileId==='number'&&Number.isSafeInteger(profileId)&&profileId>0);
 const URL='https://www.olbg.com/tipsters/tips/'+profileId,fixtures=arr(plan.fixtures,100).map(obj),proof={responseSha256:expectedResponseSHA},receipt={count:expectedCount},a={claimId:plan.claimId};
  const b=obj(decode(batchRaw,digest,131072));check(b.schemaVersion==='robin-olbg-opaque-campaign-batch-v1'&&b.missionId===plan.id&&b.claimId===a.claimId&&b.parserSha256===plan.parserSha256&&b.builderSha256===plan.builderSha256&&b.calendarSha256===plan.calendarSha256&&b.sourceReady===false&&b.applicationAdmissions===0&&b.recurrence===true);
  const source=obj(b.source);check(equal(source.fixtures,fixtures)&&source.calendarSha256===plan.calendarSha256);
  const profiles=arr(source.profiles,1);check(profiles.length===1);const profile=obj(profiles[0]),facts=obj(profile.facts),request=obj(profile.request);check(facts.authorId===profileId&&facts.mode==='current'&&request.url===URL&&request.responseSha256===proof.responseSha256);text(facts.authorLabel,80);utc(request.observedAt);
  const records=arr(facts.records,20).map(obj),accepted=arr(b.acceptedSourceTipIds,20).map(integer),rows=arr(b.picks,20).map(obj);check(rows.length>0&&rows.length===receipt.count&&rows.length===accepted.length&&new Set(accepted).size===accepted.length);
  check(new Set(rows.map(p=>p.sourceTipId)).size===rows.length);for(const p of rows){const tid=integer(p.sourceTipId),matches=records.filter(n=>n.tipid===tid);check(matches.length===1&&accepted.includes(tid));const native=matches[0],fixture=fixtures.find(f=>f.id===p.fixtureId);check(fixture&&equal(p.sourceFields,native)&&native.vc_sport_id===1&&native.result==='Open');integer(native.eventid);
   check(p.id==='olbg-tip:'+tid&&p.sourceId==='SRC_014'&&p.authorId==='olbg:'+profileId&&p.sourceEventId===native.eventid&&p.authorLabel===facts.authorLabel&&p.authorUrl===URL&&p.sourceUrl===URL&&p.kickoff===fixture.kickoff&&p.fixtureLabel===fixture.label);
   check(p.observedAt===request.observedAt&&p.firstSeenAt===request.observedAt&&utc(p.observedAt)<utc(p.kickoff)&&p.selection===native.selection&&p.sourceMarketLabel===native.market&&p.sourceBetType===native.winew&&p.sourceEventLocalText===native.event_datetime);
   check(p.responseSha256===proof.responseSha256&&p.parserSha256===plan.parserSha256&&p.calendarSha256===plan.calendarSha256&&p.market==='source_native_opaque'&&FLAGS.every(k=>p[k]===false)&&p.publishedAt===null&&p.publishedCivilDate===null&&p.sourceEventTimezone===null);
   check(p.versionCount===1&&equal(p.versions,[{selection:p.selection,observedAt:p.observedAt}]));text(p.selection,120);text(p.fixtureId);
  }
 return rows;
}
