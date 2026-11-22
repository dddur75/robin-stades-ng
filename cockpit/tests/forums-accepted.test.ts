import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdirSync, mkdtempSync, writeFileSync, unlinkSync, rmdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {test} from 'node:test';
import {applyAcceptedForums, applyReviewedForumBatches, mergeForumObservations, readForumEnvelope} from '../scripts/forums-accepted';

type Row = Record<string, unknown>;
const mission = 'FORUMS_SUCCESSOR_E1_R5_20261122';
const claim = 'DATA.SOURCE_OBSERVATORY.FORUMS.CURRENT.PREMATCH.ADMISSION.20261122';
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') {
    const row = value as Row;
    return '{' + Object.keys(row).sort().map(k => JSON.stringify(k) + ':' + canonical(row[k])).join(',') + '}';
  }
  return JSON.stringify(value);
}
function candidate(source: string, post: string, fixture: string, author: string): Row {
  const native = hash(canonical([source, post, fixture, 'correct_score']));
  const selection = '2-1';
  return {
    id: hash(canonical([mission, native])), versionId: hash(canonical([mission, native, 'correct_score', selection])),
    nativeChoiceId: native, nativeVersionId: hash(canonical([native, 'correct_score', selection])),
    sourceId: source, postId: post, authorId: 'public:' + hash(author), fixtureId: fixture,
    market: 'correct_score', selection, kickoff: '2026-11-22T14:00:00Z',
    observedAt: '2026-11-22T04:00:00.123456+00:00', publishedAt: null,
    publishedCivilDate: '2026-11-20', sourceTimezone: null, identityCertified: false,
    attributionBasis: 'public_post_pseudonym', eligibleForApplication: false,
    sourceUrl: (source === 'SRC_038' ? 'http://forum.sco1919.com/viewtopic.php?t=13259' : 'https://legruppetto.fr/forum/viewtopic.php?t=24850') + '&p=' + post.slice(1) + '#' + post,
    responseSha256: hash('synthetic response ' + post), parserSha256: 'a'.repeat(64), calendarSha256: 'b'.repeat(64),
  };
}
function fixture() {
  const a = candidate('SRC_038', 'p100', 'j11-paris-angers', 'synthetic-a');
  const b = candidate('SRC_058', 'p101', 'j11-lorient-rennes', 'synthetic-b');
  const n = candidate('SRC_038', 'p102', 'j11-paris-angers', 'synthetic-new');
  const old = (row: Row, label: string) => ({...row, id: row.nativeChoiceId,
    authorLabel: label, fixtureLabel: 'Synthetic retained fixture',
    observedAt: '2026-11-21T04:00:00Z', firstSeenAt: '2026-11-20T04:00:00Z', lastSeenAt: '2026-11-21T04:00:00Z',
    versions: [{selection: '2-1', observedAt: '2026-11-20T04:00:00Z'}], versionCount: 1});
  const base: Row = {status: 'ok', picks: [old(a, 'Retained A'), old(b, 'Retained B')], distinctPicks: 2, authorCount: 2, fixtureCount: 20, requestCount: null};
  const source: Row = {schemaVersion: 'forums-private-candidates-v1', missionId: mission, candidates: [a, b, n],
    diagnostics: {candidateCount: 3}, calendarSha256: 'b'.repeat(64), parserSha256: 'a'.repeat(64),
    admissions: 0, eligibleForApplication: false, eligibleCurrentCount: 3, newNativeChoiceCount: null,
    reobservedCount: null, distinctPicksIncrement: null, noveltyStatus: 'UNKNOWN_NO_BASELINE',
    publicationTimezoneStatus: 'UNKNOWN', noPerformanceOrSettlement: true,
    plan: 'c'.repeat(64), manifest: 'd'.repeat(64), grant: 'e'.repeat(64)};
  const envelope: Row = {schemaVersion: 'forums-approved-observations-v1', sourceCandidates: source,
    sourceCandidateRawSHA256: hash(canonical(source) + '\n'), acceptedClaimId: claim,
    preparedAt: '2026-11-22T05:00:00Z', newNativeChoiceIds: [n.nativeChoiceId],
    newAuthorLabels: {[String(n.authorId)]: 'Profil public SCO1919 · ' + String(n.authorId).slice(7, 15)}};
  return {base, envelope, source, a, b, n};
}
function resign(envelope: Row) { envelope.sourceCandidateRawSHA256 = hash(canonical(envelope.sourceCandidates) + '\n'); }
function picks(value: Row) { return value.picks as Row[]; }
function unavailable(base: Row, envelope: unknown) {
  const result = mergeForumObservations(base, envelope);
  assert.equal((result.forumCompanion as Row).state, 'unavailable');
  assert.deepEqual(result.picks, base.picks);
  assert.equal(result.distinctPicks, base.distinctPicks);
  return result;
}

test('one new native ID and two stable reobservations preserve existing history', () => {
  const {base, envelope, a, n} = fixture();
  const before = structuredClone(base);
  const output = mergeForumObservations(base, envelope);
  assert.equal(picks(output).length, 3);
  assert.equal(output.distinctPicks, 3);
  assert.equal(output.authorCount, 3);
  assert.equal(output.fixtureCount, 20);
  assert.deepEqual(base, before);
  const known = picks(output).find(p => p.id === a.nativeChoiceId)!;
  assert.equal(known.observedAt, picks(base)[0].observedAt);
  assert.equal(known.firstSeenAt, picks(base)[0].firstSeenAt);
  assert.equal(known.authorLabel, 'Retained A');
  assert.deepEqual(known.versions, picks(base)[0].versions);
  assert.equal(known.lastSeenAt, a.observedAt);
  assert.equal('observationCount' in known, false);
  const added = picks(output).find(p => p.id === n.nativeChoiceId)!;
  assert.equal(added.fixtureLabel, 'Synthetic retained fixture');
  assert.match(String(added.authorLabel), /^Profil public SCO1919 · [a-f0-9]{8}$/);
  assert.deepEqual(added.versions, [{selection: n.selection, observedAt: n.observedAt}]);
  assert.equal(added.identityCertified, false);
  const companion = output.forumCompanion as Row;
  assert.equal(companion.state, 'available');
  assert.deepEqual((companion.updates as Row)[String(a.nativeChoiceId)], {lastSeenAt: a.observedAt, claimId: claim});
});

test('repeat merge is strictly idempotent without duplicate IDs or versions', () => {
  const {base, envelope} = fixture();
  const once = mergeForumObservations(base, envelope);
  assert.equal(picks(once).length, 3);
  assert.deepEqual(mergeForumObservations(once, envelope), once);
});

test('identity, foreign source URL or changed latest literal selection rejects atomically', () => {
  for (const kind of ['author', 'url', 'selection', 'nativeId']) {
    const {base, envelope, source} = fixture();
    const row = (source.candidates as Row[])[0];
    if (kind === 'author') row.authorId = 'public:' + 'f'.repeat(64);
    if (kind === 'url') row.sourceUrl = 'https://elsewhere.invalid/topic';
    if (kind === 'selection') (picks(base)[0].versions as Row[])[0].selection = '0-0';
    if (kind === 'nativeId') row.nativeChoiceId = 'f'.repeat(64);
    resign(envelope);
    unavailable(base, envelope);
  }
});

test('UTC before kickoff and native civil/publication unknown contracts are mandatory', () => {
  for (const change of [{observedAt: '2026-11-22T14:00:00Z'}, {observedAt: '2026-11-22T13:00:00+01:00'},
    {publishedCivilDate: '2026-11-23'}, {publishedAt: '2026-11-20T00:00:00Z'}, {sourceTimezone: 'Europe/Paris'}]) {
    const {base, envelope, source} = fixture();
    Object.assign((source.candidates as Row[])[0], change);
    resign(envelope);
    unavailable(base, envelope);
  }
});

test('private file is bounded and exact raw hash is required; missing bundle preserves base', (t) => {
  const {base, envelope} = fixture();
  const root = mkdtempSync(join(tmpdir(), 'robin-forums-synthetic-'));
  const path = join(root, '.ci', 'forums-r5-approved', 'envelope.json');
  mkdirSync(dirname(path), {recursive: true});
  t.after(() => { unlinkSync(path); rmdirSync(dirname(path)); rmdirSync(join(root, '.ci')); rmdirSync(root); });
  const raw = Buffer.from(canonical(envelope) + '\n');
  writeFileSync(path, raw);
  assert.deepEqual(readForumEnvelope(root, hash(raw.toString())), envelope);
  assert.equal(picks(applyAcceptedForums(base, root, hash(raw.toString()))).length, 3);
  assert.equal((applyAcceptedForums(base, root, '0'.repeat(64)).forumCompanion as Row).state, 'unavailable');
  assert.equal((applyAcceptedForums(base, join(root, 'missing'), hash(raw.toString())).forumCompanion as Row).state, 'unavailable');
  writeFileSync(path, Buffer.alloc(128 * 1024 + 1, 32));
  assert.equal(readForumEnvelope(root, hash('oversized')), undefined);
  unavailable(base, undefined);
});

test('canonical source+LF hash and provenance flags are checked independently', () => {
  for (const kind of ['hash', 'claim', 'sourceFlag', 'extraNew']) {
    const {base, envelope, source} = fixture();
    if (kind === 'hash') envelope.sourceCandidateRawSHA256 = hash(canonical(source));
    if (kind === 'claim') envelope.acceptedClaimId = 'UNREVIEWED';
    if (kind === 'sourceFlag') source.eligibleForApplication = true;
    if (kind === 'extraNew') envelope.newNativeChoiceIds = (source.candidates as Row[]).map(r => r.nativeChoiceId);
    if (kind !== 'hash') resign(envelope);
    unavailable(base, envelope);
  }
});

test('unknown counters remain unknown and no historical observationCount is invented', () => {
  const {base, envelope} = fixture();
  base.distinctPicks = null;
  delete base.authorCount;
  (picks(base)[0]).observationCount = 7;
  const output = mergeForumObservations(base, envelope);
  assert.equal(picks(output).length, 3);
  assert.equal(output.distinctPicks, null);
  assert.equal('authorCount' in output, false);
  assert.equal(output.requestCount, null);
  assert.equal(picks(output)[0].observationCount, 7);
  assert.equal('observationCount' in picks(output)[1], false);
});

test('freshness dates advance deterministically with strict UTC and preserve unknown/refuse malformed', () => {
  const {base, envelope, source} = fixture();
  base.generatedAt = '2026-11-21T23:05:00Z';
  base.sourceObservedThrough = '2026-11-21T23:05:00Z';
  (source.candidates as Row[])[1].observedAt = '2026-11-22T04:05:00.000001+00:00';
  resign(envelope);
  const output = mergeForumObservations(base, envelope);
  assert.equal(output.sourceObservedThrough, '2026-11-22T04:05:00.000001+00:00');
  assert.equal(output.generatedAt, envelope.preparedAt);
  assert.deepEqual(mergeForumObservations(output, envelope), output);
  assert.equal(base.generatedAt, '2026-11-21T23:05:00Z');

  base.sourceObservedThrough = '2026-11-22T04:05:00.000000Z';
  assert.equal(mergeForumObservations(base, envelope).sourceObservedThrough, '2026-11-22T04:05:00.000001+00:00');

  base.generatedAt = '2026-11-22T06:00:00Z';
  base.sourceObservedThrough = '2026-11-22T05:30:00Z';
  const later = mergeForumObservations(base, envelope);
  assert.equal(later.generatedAt, base.generatedAt);
  assert.equal(later.sourceObservedThrough, base.sourceObservedThrough);

  base.generatedAt = '2026-11-21T23:05:00Z';
  assert.equal(mergeForumObservations(base, envelope).generatedAt, base.sourceObservedThrough);

  base.generatedAt = null;
  delete base.sourceObservedThrough;
  const unknown = mergeForumObservations(base, envelope);
  assert.equal(unknown.generatedAt, null);
  assert.equal('sourceObservedThrough' in unknown, false);

  for (const key of ['generatedAt', 'sourceObservedThrough']) {
    const broken = {...base, [key]: 'not-an-UTC-instant'};
    unavailable(broken, envelope);
  }
});

function approvalFor(envelope: Row) {
  const source = envelope.sourceCandidates as Row;
  const raw = JSON.stringify(envelope), sha = hash(raw);
  return {
    relativePath: '.ci/forums-approved/' + sha + '/envelope.json', envelopeSHA256: sha,
    missionId: String(source.missionId), claimId: String(envelope.acceptedClaimId),
    decisionSHA256: 'f'.repeat(64), sourceIds: ['SRC_038','SRC_058'],
    newNativeChoiceIds: [...envelope.newNativeChoiceIds as string[]], maximumRows: 42,
    plan: String(source.plan), manifest: String(source.manifest), grant: String(source.grant),
    parserSha256: String(source.parserSha256), calendarSha256: String(source.calendarSha256),
  };
}
function nextKnownBatch() {
  const {base,envelope,source} = fixture();
  const prefix = mergeForumObservations(base,envelope);
  source.missionId = 'SYNTHETIC_APPROVED_NEXT_E1';
  source.candidates = (source.candidates as Row[]).slice(0,2);
  source.eligibleCurrentCount = 2;
  for (const r of source.candidates as Row[]) {
    r.id = hash(canonical([source.missionId,r.nativeChoiceId]));
    r.versionId = hash(canonical([source.missionId,r.nativeChoiceId,r.market,r.selection]));
    r.observedAt = '2026-11-22T06:00:00.123457Z';
  }
  envelope.acceptedClaimId = 'DATA.SOURCE_OBSERVATORY.SYNTHETIC.APPROVED.NEXT';
  envelope.preparedAt = '2026-11-22T07:00:00Z';
  envelope.newNativeChoiceIds = []; envelope.newAuthorLabels = {};
  resign(envelope);
  return {prefix,envelope,source};
}
function writeBatch(t: {after: (fn:()=>void)=>void}, envelope: Row) {
  const root=mkdtempSync(join(tmpdir(),'robin-approved-batch-synthetic-'));
  const approval=approvalFor(envelope), path=join(root,approval.relativePath);
  mkdirSync(dirname(path),{recursive:true});writeFileSync(path,JSON.stringify(envelope));
  t.after(()=>{unlinkSync(path);rmdirSync(dirname(path));rmdirSync(dirname(dirname(path)));
    rmdirSync(join(root,'.ci'));rmdirSync(root);});
  return {root,approval,path};
}

test('approved later mission reobservations preserve prefix, history, labels and exact microseconds',()=>{
  const {prefix,envelope,source}=nextKnownBatch(), before=structuredClone(prefix);
  prefix.generatedAt='2026-11-22T06:00:00Z';prefix.sourceObservedThrough='2026-11-22T06:00:00.123456Z';
  const output=mergeForumObservations(prefix,envelope,approvalFor(envelope));
  assert.equal(output.distinctPicks,3);assert.equal(output.authorCount,3);
  assert.equal((output.forumCompanion as Row).approvedNewCount,0);
  assert.equal((output.forumCompanion as Row).approvedReobservationCount,2);
  assert.equal(output.sourceObservedThrough,'2026-11-22T06:00:00.123457Z');
  assert.equal(output.generatedAt,'2026-11-22T07:00:00Z');
  for(const prior of picks(before)){
    const now=picks(output).find(r=>r.id===prior.id)!;
    for(const key of ['firstSeenAt','observedAt','authorLabel','versions'])assert.deepEqual(now[key],prior[key]);
  }
  assert.equal(picks(output)[0].lastSeenAt,(source.candidates as Row[])[0].observedAt);
});

test('exact approved IO is idempotent and a missing later batch preserves the accepted prefix',(t)=>{
  const {prefix,envelope}=nextKnownBatch(), {root,approval}=writeBatch(t,envelope);
  const once=applyReviewedForumBatches(prefix,root,[approval]);
  assert.equal(once.distinctPicks,3);assert.equal((once.forumBatches as Row[])[0].state,'available');
  assert.deepEqual(applyReviewedForumBatches(once,root,[approval]),once);
  const missing={...approval,envelopeSHA256:'0'.repeat(64),relativePath:'.ci/forums-approved/'+'0'.repeat(64)+'/envelope.json'};
  const result=applyReviewedForumBatches(prefix,root,[approval,missing]);
  assert.deepEqual(result.picks,once.picks);assert.equal(result.distinctPicks,3);
  assert.deepEqual((result.forumBatches as Row[]).map(r=>r.state),['available','unavailable']);
});

test('duplicate descriptor stops at its boundary and preserves the first accepted batch',(t)=>{
  const {prefix,envelope}=nextKnownBatch(),{root,approval}=writeBatch(t,envelope);
  const output=applyReviewedForumBatches(prefix,root,[approval,approval]);
  assert.equal(output.distinctPicks,3);assert.equal(picks(output).length,3);
  assert.deepEqual((output.forumBatches as Row[]).map(r=>r.state),['available','unavailable']);
});

test('wrong mission, claim or tuple rejects the later batch without losing approved rows',()=>{
  for(const key of ['missionId','claimId','plan','manifest','grant','parserSha256','calendarSha256']){
    const {prefix,envelope}=nextKnownBatch();const approval=approvalFor(envelope);
    Object.assign(approval,{[key]:key==='missionId'?'OTHER_MISSION':key==='claimId'?'DATA.SOURCE_OBSERVATORY.OTHER':'1'.repeat(64)});
    const result=mergeForumObservations(prefix,envelope,approval);
    assert.equal((result.forumCompanion as Row).state,'unavailable');assert.deepEqual(result.picks,prefix.picks);
    assert.equal(result.distinctPicks,3);
  }
});

test('unapproved new IDs, changed selections, late observations and unknown slots are refused',()=>{
  for(const kind of ['newId','selection','late','slot']){
    const {prefix,envelope,source}=nextKnownBatch();
    const row=(source.candidates as Row[])[0];
    if(kind==='newId'){
      const added=candidate('SRC_038','p103','j11-paris-angers','synthetic-a');
      added.id=hash(canonical([source.missionId,added.nativeChoiceId]));
      added.versionId=hash(canonical([source.missionId,added.nativeChoiceId,added.market,added.selection]));
      (source.candidates as Row[]).push(added);source.eligibleCurrentCount=3;
    }
    if(kind==='selection'){
      row.selection='3-0';row.nativeVersionId=hash(canonical([row.nativeChoiceId,row.market,row.selection]));
      row.versionId=hash(canonical([source.missionId,row.nativeChoiceId,row.market,row.selection]));
    }
    if(kind==='late')row.observedAt=row.kickoff;
    if(kind==='slot')source.slot=0;
    resign(envelope);
    const result=mergeForumObservations(prefix,envelope,approvalFor(envelope));
    assert.equal((result.forumCompanion as Row).state,'unavailable');
    assert.deepEqual(result.picks,prefix.picks);
  }
});

test('a new choice by an existing pseudonym keeps its established label and author count',()=>{
  const {prefix,envelope,source}=nextKnownBatch();
  const added=candidate('SRC_038','p103','j11-paris-angers','synthetic-a');
  added.id=hash(canonical([source.missionId,added.nativeChoiceId]));
  added.versionId=hash(canonical([source.missionId,added.nativeChoiceId,added.market,added.selection]));
  (source.candidates as Row[]).push(added);source.eligibleCurrentCount=3;
  envelope.newNativeChoiceIds=[added.nativeChoiceId];resign(envelope);
  const output=mergeForumObservations(prefix,envelope,approvalFor(envelope));
  assert.equal(output.distinctPicks,4);assert.equal(output.authorCount,3);
  assert.equal(picks(output).find(r=>r.id===added.nativeChoiceId)!.authorLabel,'Retained A');
  assert.deepEqual(mergeForumObservations(output,envelope,approvalFor(envelope)),output);
});

test('descriptor paths, raw hash, source bounds and approval list bound fail closed',(t)=>{
  const {prefix,envelope}=nextKnownBatch(),{root,approval}=writeBatch(t,envelope);
  for(const wrong of [
    {...approval,relativePath:'../private/envelope.json'},
    {...approval,sourceIds:['OTHER']},
    {...approval,maximumRows:43},
    {...approval,envelopeSHA256:'0'.repeat(64),relativePath:'.ci/forums-approved/'+'0'.repeat(64)+'/envelope.json'},
  ]){
    const output=applyReviewedForumBatches(prefix,root,[wrong]);
    assert.deepEqual(output.picks,prefix.picks);
    assert.equal((output.forumBatches as Row[]).at(-1)!.state,'unavailable');
  }
  assert.deepEqual(applyReviewedForumBatches(prefix,root,Array(9).fill(approval)).picks,prefix.picks);
});

test('malformed internal batch history preserves approved picks without throwing',()=>{const base={status:'ok',picks:[{id:'retained'}],distinctPicks:479,forumBatches:[null]};const result=applyReviewedForumBatches(base,'',[{} as never]);assert.deepEqual(result.picks,base.picks);assert.equal(result.distinctPicks,479);assert.equal((result.forumBatches as Row[])[0].state,'unavailable');});
