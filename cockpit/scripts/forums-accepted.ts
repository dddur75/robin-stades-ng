import {createHash} from 'node:crypto';
import {closeSync, fstatSync, openSync, readSync} from 'node:fs';
import {resolve} from 'node:path';

export type JsonObject = Record<string, unknown>;
const MAX_BYTES = 128 * 1024;
const CLAIM = 'DATA.SOURCE_OBSERVATORY.FORUMS.CURRENT.PREMATCH.ADMISSION.20261122';
const MISSION = 'FORUMS_SUCCESSOR_E1_R5_20261122';
const FIXTURES = new Set(['j11-paris-angers', 'j11-lorient-rennes', 'j11-marseille-lemans']);
const HASH = /^[a-f0-9]{64}$/;
const CANDIDATE_KEYS = 'id versionId nativeChoiceId nativeVersionId sourceId postId authorId sourceUrl observedAt publishedAt publishedCivilDate responseSha256 fixtureId kickoff market selection identityCertified attributionBasis parserSha256 calendarSha256 eligibleForApplication sourceTimezone'.split(' ');

function check(value: unknown): asserts value {
  if (!value) throw new Error('FORUM_APPROVED_BUNDLE_UNAVAILABLE');
}
function object(value: unknown): JsonObject {
  check(value !== null && typeof value === 'object' && !Array.isArray(value));
  const prototype = Object.getPrototypeOf(value);
  check(prototype === Object.prototype || prototype === null);
  return value as JsonObject;
}
function exactKeys(row: JsonObject, keys: string[]): void {
  check(Object.keys(row).length === keys.length && keys.every(k => Object.hasOwn(row, k)));
}
function text(value: unknown, max = 256): string {
  check(typeof value === 'string' && value.length > 0 && value.length <= max);
  return value;
}
function sha(raw: string | Buffer): string { return createHash('sha256').update(raw).digest('hex'); }
function canonical(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return JSON.stringify(value);
  if (typeof value === 'number') { check(Number.isSafeInteger(value)); return JSON.stringify(value); }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  const row = object(value);
  return '{' + Object.keys(row).sort().map(k => JSON.stringify(k) + ':' + canonical(row[k])).join(',') + '}';
}
function digest(value: unknown): string { return sha(canonical(value)); }
function utc(value: unknown): bigint {
  const s = text(value, 40);
  const match = /^([0-9]{4}-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9])(?:\.([0-9]{1,6}))?(?:Z|\+00:00)$/.exec(s);
  check(match);
  const milliseconds = Date.parse(match[1] + 'Z');
  check(Number.isFinite(milliseconds) && new Date(milliseconds).toISOString().slice(0, 19) === match[1]);
  return BigInt(milliseconds) * BigInt(1000) + BigInt((match[2] ?? '').padEnd(6, '0'));
}
function civil(value: unknown): string {
  const s = text(value, 10);
  check(/^[0-9]{4}-[0-9][0-9]-[0-9][0-9]$/.test(s));
  utc(s + 'T00:00:00Z');
  return s;
}
function sourceUrl(source: string, post: string): string {
  const root = source === 'SRC_038' ? 'http://forum.sco1919.com/viewtopic.php?t=13259' : 'https://legruppetto.fr/forum/viewtopic.php?t=24850';
  return root + '&p=' + post.slice(1) + '#' + post;
}
type Candidate = {row: JsonObject; id: string; author: string; fixture: string; observed: string; kickoff: string; selection: string};
function candidate(value: unknown, source: JsonObject, prepared: bigint): Candidate {
  const row = object(value);
  exactKeys(row, CANDIDATE_KEYS);
  const sourceId = text(row.sourceId), post = text(row.postId), fixture = text(row.fixtureId);
  const author = text(row.authorId), selection = text(row.selection), observed = text(row.observedAt), kickoff = text(row.kickoff);
  check((sourceId === 'SRC_038' || sourceId === 'SRC_058') && /^p[0-9]{1,20}$/.test(post) && FIXTURES.has(fixture));
  check(/^public:[a-f0-9]{64}$/.test(author) && row.market === 'correct_score' && /^(?:0|[1-9][0-9]?)-(?:0|[1-9][0-9]?)$/.test(selection));
  const id = digest([sourceId, post, fixture, 'correct_score']);
  check(row.nativeChoiceId === id && row.id === digest([MISSION, id]));
  check(row.nativeVersionId === digest([id, 'correct_score', selection]) && row.versionId === digest([MISSION, id, 'correct_score', selection]));
  check(utc(observed) < utc(kickoff) && utc(observed) <= prepared);
  const date = civil(row.publishedCivilDate);
  check(date >= '2026-11-09' && date <= observed.slice(0, 10));
  check(row.publishedAt === null && row.sourceTimezone === null && row.identityCertified === false && row.eligibleForApplication === false);
  check(row.attributionBasis === 'public_post_pseudonym' && row.sourceUrl === sourceUrl(sourceId, post));
  check(row.parserSha256 === source.parserSha256 && row.calendarSha256 === source.calendarSha256 && HASH.test(text(row.responseSha256)));
  return {row, id, author, fixture, observed, kickoff, selection};
}
function unavailable(base: JsonObject): JsonObject { return {...base, forumCompanion: {state: 'unavailable'}}; }

function advanceTimestamp(base: JsonObject, output: JsonObject, key: string, dates: string[]): void {
  if (base[key] === null || base[key] === undefined) return;
  let latest = text(base[key], 40);
  utc(latest);
  for (const date of dates) if (utc(date) > utc(latest)) latest = date;
  output[key] = latest;
}

/** Pure immutable projection of an already hash-approved envelope; no source IO. */
export function mergeForumObservations(base: JsonObject, value: unknown): JsonObject {
  try {
    check(base.status === 'ok' && Array.isArray(base.picks));
    const envelope = object(value);
    exactKeys(envelope, ['schemaVersion', 'sourceCandidateRawSHA256', 'sourceCandidates', 'acceptedClaimId', 'preparedAt', 'newNativeChoiceIds', 'newAuthorLabels']);
    check(envelope.schemaVersion === 'forums-approved-observations-v1' && envelope.acceptedClaimId === CLAIM);
    const prepared = utc(envelope.preparedAt), source = object(envelope.sourceCandidates);
    exactKeys(source, 'schemaVersion missionId candidates diagnostics calendarSha256 parserSha256 admissions eligibleForApplication eligibleCurrentCount newNativeChoiceCount reobservedCount distinctPicksIncrement noveltyStatus publicationTimezoneStatus noPerformanceOrSettlement plan manifest grant'.split(' '));
    check(HASH.test(text(envelope.sourceCandidateRawSHA256)) && sha(canonical(source) + '\n') === envelope.sourceCandidateRawSHA256);
    check(source.schemaVersion === 'forums-private-candidates-v1' && source.missionId === MISSION && source.admissions === 0 && source.eligibleForApplication === false);
    check(source.noPerformanceOrSettlement === true && source.publicationTimezoneStatus === 'UNKNOWN' && source.noveltyStatus === 'UNKNOWN_NO_BASELINE');
    check(source.newNativeChoiceCount === null && source.reobservedCount === null && source.distinctPicksIncrement === null);
    for (const key of ['calendarSha256', 'parserSha256', 'plan', 'manifest', 'grant']) check(HASH.test(text(source[key])));
    check(Array.isArray(source.candidates) && source.candidates.length >= 1 && source.candidates.length <= 42 && source.eligibleCurrentCount === source.candidates.length);
    check(Array.isArray(envelope.newNativeChoiceIds) && envelope.newNativeChoiceIds.length === 1 && HASH.test(text(envelope.newNativeChoiceIds[0])));
    const approvedNew = envelope.newNativeChoiceIds[0] as string;
    const rows = source.candidates.map(row => candidate(row, source, prepared));
    check(new Set(rows.map(c => c.id)).size === rows.length);
    const newRow = rows.find(c => c.id === approvedNew);
    check(newRow && newRow.row.sourceId === 'SRC_038');
    const labels = object(envelope.newAuthorLabels);
    exactKeys(labels, [newRow.author]);
    check(labels[newRow.author] === 'Profil public SCO1919 · ' + newRow.author.slice(7, 15));

    const original = base.picks.map(object), byId = new Map<string, JsonObject>();
    const fixtures = new Map<string, {label: string; kickoff: string}>();
    const authors = new Set<string>();
    for (const pick of original) {
      const id = text(pick.id);
      check(!byId.has(id));
      byId.set(id, pick);
      if (typeof pick.authorId === 'string') authors.add(pick.authorId);
      if (typeof pick.fixtureId === 'string' && FIXTURES.has(pick.fixtureId)) {
        const label = text(pick.fixtureLabel), kickoff = text(pick.kickoff);
        const previous = fixtures.get(pick.fixtureId);
        check(!previous || utc(previous.kickoff) === utc(kickoff));
        if (!previous) fixtures.set(pick.fixtureId, {label, kickoff});
      }
    }
    const replacements = new Map<string, JsonObject>(), additions: JsonObject[] = [];
    const updates: Record<string, {lastSeenAt: string; claimId: string}> = Object.create(null);
    const addedAuthors = new Set<string>();
    for (const c of rows) {
      const fixture = fixtures.get(c.fixture);
      check(fixture && utc(fixture.kickoff) === utc(c.kickoff));
      const previous = byId.get(c.id);
      if (previous) {
        for (const key of ['sourceId', 'postId', 'fixtureId', 'market', 'authorId', 'sourceUrl', 'publishedCivilDate']) check(previous[key] === c.row[key]);
        check(previous.selection === c.selection && utc(previous.kickoff) === utc(c.kickoff));
        check(Array.isArray(previous.versions) && previous.versions.length > 0);
        const versions = previous.versions.map(object);
        check(versions[versions.length - 1].selection === c.selection);
        for (const version of versions) check(utc(version.observedAt) < utc(c.kickoff));
        check(utc(previous.observedAt) < utc(c.kickoff));
        const earlier = text(previous.lastSeenAt ?? previous.observedAt);
        const last = utc(earlier) >= utc(c.observed) ? earlier : c.observed;
        replacements.set(c.id, {...previous, lastSeenAt: last});
        if (c.id !== approvedNew) updates[c.id] = {lastSeenAt: last, claimId: CLAIM};
      } else {
        check(c.id === approvedNew && !authors.has(c.author));
        addedAuthors.add(c.author);
        const r = c.row;
        additions.push({id: c.id, sourceId: r.sourceId, postId: r.postId, authorId: c.author,
          authorLabel: labels[c.author], fixtureId: c.fixture, fixtureLabel: fixture.label,
          kickoff: fixture.kickoff, market: 'correct_score', selection: c.selection,
          observedAt: c.observed, firstSeenAt: c.observed, lastSeenAt: c.observed,
          publishedAt: null, publishedCivilDate: r.publishedCivilDate, sourceTimezone: null,
          identityCertified: false, attributionBasis: 'public_post_pseudonym', sourceUrl: r.sourceUrl,
          versions: [{selection: c.selection, observedAt: c.observed}], versionCount: 1,
          responseSha256: r.responseSha256, parserSha256: r.parserSha256, calendarSha256: r.calendarSha256,
          nativeChoiceId: c.id, nativeVersionId: r.nativeVersionId,
          acceptedClaimId: CLAIM, sourceCandidateRawSHA256: envelope.sourceCandidateRawSHA256});
      }
    }
    const output: JsonObject = {...base, picks: [...original.map(p => replacements.get(String(p.id)) ?? p), ...additions],
      forumCompanion: {state: 'available', claimId: CLAIM, preparedAt: envelope.preparedAt,
        sourceCandidateRawSHA256: envelope.sourceCandidateRawSHA256, approvedObservationCount: rows.length,
        approvedNewCount: 1, approvedReobservationCount: rows.length - 1, updates}};
    for (const [key, increment] of [['distinctPicks', additions.length], ['authorCount', addedAuthors.size]] as const) {
      if (typeof base[key] === 'number' && Number.isSafeInteger(base[key]) && base[key] >= 0) output[key] = base[key] + increment;
    }
    const observed = rows.map(c => c.observed);
    advanceTimestamp(base, output, 'sourceObservedThrough', observed);
    const generatedDates = [...observed, text(envelope.preparedAt)];
    if (output.sourceObservedThrough !== null && output.sourceObservedThrough !== undefined) generatedDates.push(text(output.sourceObservedThrough, 40));
    advanceTimestamp(base, output, 'generatedAt', generatedDates);
    return output;
  } catch { return unavailable(base); }
}

/** The caller supplies C0's final immutable envelope hash; no permissive default. */
export function readForumEnvelope(root: string, expectedSHA: string): unknown {
  let descriptor: number | undefined;
  let result: unknown;
  try {
    check(HASH.test(expectedSHA));
    descriptor = openSync(resolve(root, '.ci/forums-r5-approved/envelope.json'), 'r');
    const stat = fstatSync(descriptor);
    check(stat.isFile() && stat.size > 0 && stat.size <= MAX_BYTES);
    const bytes = Buffer.alloc(MAX_BYTES + 1);
    let size = 0;
    while (size < bytes.length) {
      const count = readSync(descriptor, bytes, size, bytes.length - size, null);
      if (count === 0) break;
      size += count;
    }
    check(size > 0 && size <= MAX_BYTES);
    const raw = bytes.subarray(0, size);
    check(sha(raw) === expectedSHA);
    result = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw)) as unknown;
  } catch { result = undefined; }
  finally {
    if (descriptor !== undefined) {
      try { closeSync(descriptor); } catch { result = undefined; }
    }
  }
  return result;
}
export function applyAcceptedForums(base: JsonObject, root: string, expectedSHA: string): JsonObject {
  return mergeForumObservations(base, readForumEnvelope(root, expectedSHA));
}
