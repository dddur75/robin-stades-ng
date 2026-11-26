import{mergeCampaignPicks}from'./olbg-campaign-companion';
type J=Record<string,unknown>;
const key=(p:J)=>JSON.stringify([p.sourceId,p.authorId,p.sourceTipId]);
const copy=<T>(v:T):T=>structuredClone(v);
const same=(a:unknown,b:unknown)=>JSON.stringify(a)===JSON.stringify(b);
/** Keep the first admitted calendar association; bind later capture calendars explicitly. */
export function mergeMultiCapturedPicks(previous:J[],incoming:J[]):J[]{
 if(previous.length>2000||incoming.length>24000)throw Error('MULTI_CAPTURE_MERGE_CAP');
 const index=new Map(previous.filter(p=>p.sourceId==='SRC_014').map(p=>[key(p),p]));
 const adapted=incoming.filter(p=>{const old=index.get(key(p));return !old||Date.parse(String(p.lastSeenAt??p.observedAt))>=Date.parse(String(old.lastSeenAt??old.observedAt));}).map(p=>{
  const old=index.get(key(p));if(!old||old.calendarSha256===p.calendarSha256)return p;
  if(!['id','sourceId','authorId','sourceTipId','sourceEventId','fixtureId','kickoff','sourceUrl','authorUrl','market'].every(k=>same(old[k],p[k])))throw Error('MULTI_CAPTURE_IMMUTABLE_CONFLICT');
  const out=copy(p),calendar=String(p.calendarSha256);
  out.captureCalendarSha256=calendar;out.calendarSha256=old.calendarSha256;
  // This is projection metadata; immutable producer batches retain their original calendar.
  const fields=['selection','sourceMarketLabel','sourceBetType','sourceFields','observedAt','responseSha256'];
  const observations=Array.isArray(p.observationVersions)?p.observationVersions:[Object.fromEntries(fields.map(k=>[k,p[k]]))];
  out.observationVersions=observations.map(v=>({...v as J,captureCalendarSha256:calendar}));
  if(Date.parse(String(out.firstSeenAt??out.observedAt))<Date.parse(String(old.firstSeenAt??old.observedAt)))out.firstSeenAt=old.firstSeenAt??old.observedAt;
  return out;
 });
 return mergeCampaignPicks(previous,adapted);
}
