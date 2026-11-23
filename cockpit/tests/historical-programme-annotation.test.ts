import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {applyHistoricalAnnotation,type HistoricalAnnotationApproval} from '../scripts/olbg-historical-annotation';
const hash=(value:string|Buffer)=>createHash('sha256').update(value).digest('hex');
function canonical(value:unknown):string{
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.entries(value).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>JSON.stringify(k)+':'+canonical(v)).join(',')+'}';
 const result=JSON.stringify(value);assert.notEqual(result,undefined);return result as string;
}
const cases:[string,unknown,boolean][]=[['integer',123,true],['string','123',true],['zero',0,false],['negative',-123,false],['fractional',123.5,false],['NaN',NaN,false],['infinite',Infinity,false],['boolean',true,false],['null',null,false],['object',{},false],['unsafe',Number.MAX_SAFE_INTEGER+1,false],['different','124',false]];
for(const [name,sourceTipId,accepted]of cases)test('historical annotation identity: '+name,()=>{
 const row={id:'SYNTHETIC_ROW',sourceTipId,authorId:'SYNTHETIC_AUTHOR',fixtureId:'SYNTHETIC_FIXTURE',versions:[{version:'SYNTHETIC_V1'}],flags:{sourceReady:false},observedAt:'2026-11-22T10:00:00.123456Z'};
 const proof={sourceTipIdSHA256:hash('123'),observationBeforeRetainedOfficialProgramme:true,originalMembershipVerified:true,sourceVersionLinked:true,versionSelectionUnchanged:true,originalFlagsUnchanged:true,originalInputsUnchanged:true,nativeOLBGTimezoneEstablished:false,nativePublicationTimeEstablished:false,actualKickoffEstablished:false,programmeKnownAtCaptureEstablished:false,programmeStabilityEstablished:false,sourceReady:false,sourceGET:0,newSourceAcquisitions:0,newFutureForecasts:0,admissions:0,appChanges:0,otherStockRequalified:0,collectorObservedUTC:'2026-11-22T10:00:00.123456Z',officialProgrammeUTC:'2026-11-22T11:00:00Z',sourceClaims:['SYNTHETIC']};
 const raw=Buffer.from(JSON.stringify(proof));
 const approval:HistoricalAnnotationApproval={relativePath:'.ci/historical-programme/'+hash(raw)+'/sidecar.json',sidecarSHA256:hash(raw),targetRowSHA256:hash(canonical(row)),targetIdSHA256:hash(row.id),sourceTipIdSHA256:hash('123'),authorIdSHA256:hash(row.authorId),fixtureIdSHA256:hash(row.fixtureId),versionsSHA256:hash(canonical(row.versions)),claimId:'ENG.SOURCE_OBSERVATORY.OLBG.ONE.PROGRAMME.AUTHOR.NAMESPACE.FIX.RESULT.20261123'};
 const base={picks:[row],generatedAt:'SYNTHETIC_UNCHANGED_CLOCK'},before=canonical(base);
 if(!accepted){assert.throws(()=>applyHistoricalAnnotation(base,raw,approval));assert.equal(canonical(base),before);return;}
 const output=applyHistoricalAnnotation(base,raw,approval);
 const annotated=output.picks[0] as typeof row&{historicalProgrammeObservation:Record<string,unknown>};
 const{historicalProgrammeObservation,...original}=annotated;
 assert.deepEqual(original,row);assert.equal(canonical(base),before);assert.equal(output.generatedAt,base.generatedAt);
 for(const flag of ['sourceReady','actualKickoffEstablished','nativeTimezoneEstablished','performanceAllowed'])assert.equal(historicalProgrammeObservation[flag],false);
 assert.equal(typeof original.sourceTipId,typeof sourceTipId);
});
