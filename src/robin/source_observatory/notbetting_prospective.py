"""Pure bounded prospective NotBetting qualification; no authority or acquisition.
Canonical fixture names only. The caller supplies reviewed calendar proof; this
module validates binding, never authenticates a decision or grants permission.
"""
import json
import re
from datetime import datetime, timezone
from hashlib import sha256

MAX_VISITS = 150000
MAX_DEPTH = 40
MAX_PICKS = 20
MAX_WITNESSES = 3
MAX_REFS = 12
HASH = re.compile('[a-f0-9]{64}')
UUID = re.compile('[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}')
SKIP = re.compile('stats|statistics|recommend|suggest|reco|analysis|description|biography|contact', re.I)
GATES = ('isPaid', 'isPremium', 'requiresAuth', 'authenticatedOnly', 'isLocked')

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def instant(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('AWARE_DATE_REQUIRED')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('AWARE_DATE_REQUIRED')
    return result.astimezone(timezone.utc)

def qualify_documents(documents, fixtures, observed, *, ownerSpec, competition, responseSHA, parserSHA, calendarClaim, calendarSHA, known=None, _observer=None):
    """Private opaque picks; partial traversal or global contradictions clear all."""
    if not isinstance(documents, dict) or not isinstance(fixtures, list) or (not 0 < len(fixtures) <= 32) or (not isinstance(observed, datetime)) or (observed.tzinfo is None) or (observed.utcoffset() is None) or (competition not in {'Premier League', 'Bundesliga'}) or (not isinstance(ownerSpec, dict)) or (set(ownerSpec) != {'uid', 'label'}) or (not isinstance(ownerSpec['uid'], str)) or (UUID.fullmatch(ownerSpec['uid']) is None) or (not isinstance(ownerSpec['label'], str)) or (not 0 < len(ownerSpec['label']) <= 96) or (not isinstance(calendarClaim, str)) or (not 0 < len(calendarClaim) <= 200) or any((not isinstance(h, str) or HASH.fullmatch(h) is None for h in (responseSHA, parserSHA, calendarSHA))):
        raise ValueError('INPUT_CONTRACT')
    observed = observed.astimezone(timezone.utc)
    uid, label = (ownerSpec['uid'], ownerSpec['label'])
    pool = []
    fixture_ids, pairs = (set(), set())
    for f in fixtures:
        if not isinstance(f, dict) or f.get('competition') != competition or f.get('calendarSHA') != calendarSHA or (f.get('calendarClaim') != calendarClaim) or (not all((isinstance(f.get(k), str) and 0 < len(f[k]) <= 200 for k in ('id', 'home', 'away', 'kickoff')))) or (f['home'] == f['away']) or (f['id'] in fixture_ids) or ((f['home'], f['away']) in pairs):
            raise ValueError('CALENDAR_BINDING')
        kickoff = instant(f['kickoff'])
        if not (f['kickoff'].endswith('Z') or f['kickoff'].endswith('+00:00')):
            raise ValueError('CALENDAR_UTC_REQUIRED')
        pool.append((f, kickoff))
        fixture_ids.add(f['id'])
        pairs.add((f['home'], f['away']))
    known = [] if known is None else known
    if not isinstance(known, list) or len(known) > 1000:
        raise ValueError('KNOWN_BOUND')
    known_ids = {}
    known_first = {}
    for item in known:
        if not isinstance(item, dict) or not isinstance(item.get('sourceTipId'), str) or (not isinstance(item.get('sourceFields'), dict)):
            raise ValueError('KNOWN_CONTRACT')
        identifier = item['sourceTipId']
        keys = ('id', 'event', 'pick', 'competition', 'date', 'tipsterId', 'tipster.user.id', 'tipster.user.tipster.id', 'tipster.user.tipster.userId', 'tipster.user.username')
        if any((key not in item['sourceFields'] for key in keys)):
            raise ValueError('KNOWN_CONTRACT')
        identity = canonical({key: item['sourceFields'][key] for key in keys})
        if identifier in known_ids and known_ids[identifier] != identity:
            raise ValueError('KNOWN_CONTRADICTION')
        known_ids[identifier] = identity
        if 'firstSeenAt' in item:
            first = instant(item['firstSeenAt'])
            if first > observed:
                raise ValueError('KNOWN_TIME')
            if identifier not in known_first or first < known_first[identifier]:
                known_first[identifier] = first
    result = dict(status='qualified', picks=[], reasons=[], witnesses=[], omittedWitnesses=0, omittedAdmissible=0, excludedOtherOwners=0, traversalComplete=True, visitedNodes=0, depthBoundHit=False, walkBoundHit=False, permissionEstablished=False)
    seen, owned, conflicts = ({}, set(), set())

    def reject(reason):
        if reason not in result['reasons']:
            result['reasons'].append(reason)
        result['status'] = 'partial'

    def incomplete(reason):
        result['traversalComplete'] = False
        reject(reason)

    def witness(reason):
        if len(result['witnesses']) < MAX_WITNESSES:
            result['witnesses'].append(dict(reason=reason, sampleOnly=True))
        else:
            result['omittedWitnesses'] += 1
    _capture_seen = set()
    _capture_bytes = 0

    def _capture(error, reference=None, depth=None, references=None):
        nonlocal _capture_bytes
        try:
            if _observer is None or len(_capture_seen) >= 4:
                return
            closed = frozenset(('gate_state_unproven', 'gated_reference', 'filtered_metadata_context', 'walk_bound', 'depth_bound', 'unsupported_required_reference', 'noncanonical_document_id', 'cyclic_reference', 'reference_bound', 'unresolved_data_reference', 'filtered_reference_segment', 'missing_property', 'invalid_list_index', 'property_target_unproven'))
            reason = error.args[0] if error.args and type(error.args[0]) is str and (error.args[0] in closed) else 'UNCLASSIFIED_REFERENCE_FAILURE'
            digest = sha256(reference.encode('utf-8')).hexdigest() if type(reference) is str and reference.startswith('$') and (len(reference) <= 4096) else None
            item = dict(reason=reason, referenceSHA256=digest, depth=depth if type(depth) is int and 0 <= depth <= 200000 else None, referenceCount=references if type(references) is int and 0 <= references <= 200000 else None)
            encoded = canonical(item)
            if encoded in _capture_seen or _capture_bytes + len(encoded) > 4096:
                return
            _capture_seen.add(encoded)
            _capture_bytes += len(encoded)
            _observer(item)
        except BaseException:
            return

    class ReferenceFailure(ValueError):
        pass

    def gate(value):
        if not isinstance(value, dict):
            return
        for key in ('isReco', *GATES):
            if key in value and type(value[key]) is not bool:
                raise ReferenceFailure('gate_state_unproven')
            if value.get(key) is True:
                raise ReferenceFailure('gated_reference')
        if any((isinstance(value.get(key), str) and SKIP.search(value[key]) for key in ('type', 'kind', '__typename'))):
            raise ReferenceFailure('filtered_metadata_context')
        if 'access' in value:
            access = value['access']
            if isinstance(access, str) and access in ('paid', 'subscription_required', 'authentication_required'):
                raise ReferenceFailure('gated_reference')
            raise ReferenceFailure('gate_state_unproven')

    def touch(value, depth):
        result['visitedNodes'] += 1
        if result['visitedNodes'] > MAX_VISITS:
            result['walkBoundHit'] = True
            raise ReferenceFailure('walk_bound')
        if depth > MAX_DEPTH:
            result['depthBoundHit'] = True
            raise ReferenceFailure('depth_bound')
        gate(value)

    def plain(reference, chain, depth):
        match = re.fullmatch('\\$([a-f0-9]+)((?::[^:\\x00-\\x1f]+)*)', reference)
        if match is None:
            raise ReferenceFailure('unsupported_required_reference')
        key = match[1]
        path = tuple(match[2][1:].split(':')) if match[2] else ()
        if key != format(int(key, 16), 'x'):
            raise ReferenceFailure('noncanonical_document_id')
        target = (key, path)
        if target in chain:
            raise ReferenceFailure('cyclic_reference')
        if len(chain) >= MAX_REFS:
            raise ReferenceFailure('reference_bound')
        if key not in documents:
            raise ReferenceFailure('unresolved_data_reference')
        active = (*chain, target)
        value = documents[key]
        depth += 1
        touch(value, depth)
        for segment in path:
            if isinstance(value, str) and value.startswith('$'):
                value, active, depth = plain(value, active, depth)
            gate(value)
            if isinstance(value, dict):
                if SKIP.search(segment):
                    raise ReferenceFailure('filtered_reference_segment')
                if segment not in value:
                    raise ReferenceFailure('missing_property')
                value = value[segment]
            elif isinstance(value, list):
                if re.fullmatch('0|[1-9][0-9]*', segment) is None or len(segment) > 7:
                    raise ReferenceFailure('invalid_list_index')
                index = int(segment)
                if index >= len(value):
                    raise ReferenceFailure('missing_property')
                value = value[index]
            else:
                raise ReferenceFailure('property_target_unproven')
            depth += 1
            touch(value, depth)
        if isinstance(value, str) and value.startswith('$'):
            return plain(value, active, depth)
        return (value, active, depth)

    def resolve(value, chain=()):
        if not isinstance(value, str) or not value.startswith('$'):
            gate(value)
            return value
        value, _, _ = plain(value, chain, 0)
        return value

    def examine(row):
        identifier = row.get('id')
        try:
            tipster = resolve(row.get('tipster'))
            user = resolve(tipster['user'])
            back = resolve(user['tipster'])
            ids = [resolve(row.get('tipsterId')), resolve(user.get('id')), resolve(back.get('id')), resolve(back.get('userId'))]
            username = resolve(user.get('username'))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            _capture(error)
            incomplete('owner_backlinks_unproven')
            return
        row = dict(row)
        try:
            for required_field in ('event', 'pick', 'competition', 'date'):
                row[required_field] = resolve(row.get(required_field))
        except ReferenceFailure as error:
            _capture(error, row.get(required_field))
            incomplete(str(error))
            return
        ours = uid in ids or identifier in known_ids
        if not isinstance(identifier, str) or UUID.fullmatch(identifier) is None:
            if ours:
                incomplete('source_owned_core_incomplete')
            return
        if not all((isinstance(row.get(k), str) and 0 < len(row[k]) <= 512 for k in ('event', 'pick', 'competition', 'date'))):
            if ours:
                incomplete('source_owned_core_incomplete')
            return
        fields = {k: row.get(k) for k in ('id', 'event', 'pick', 'competition', 'date', 'tipsterId')}
        fields.update({'tipster.user.id': ids[1], 'tipster.user.tipster.id': ids[2], 'tipster.user.tipster.userId': ids[3], 'tipster.user.username': username})
        signature = canonical(fields)
        if identifier in known_ids and (known_ids[identifier] != signature or ids != [uid] * 4 or username != label):
            conflicts.add(identifier)
        if ours:
            owned.add(identifier)
        if identifier in seen:
            prior_signature, prior_ours = seen[identifier]
            if (ours or prior_ours) and signature != prior_signature:
                conflicts.add(identifier)
            return
        seen[identifier] = (signature, ours)
        if not ours:
            result['excludedOtherOwners'] += 1
            return
        owned.add(identifier)
        if ids != [uid] * 4 or username != label:
            witness('owner_mismatch')
            return
        if row['competition'] != competition:
            witness('competition_unmatched')
            return
        names = re.split('\\s+[-\\u2013]\\s+', row['event'])
        matches = [(f, ko) for f, ko in pool if len(names) == 2 and names == [f['home'], f['away']]]
        if len(matches) != 1:
            witness('canonical_fixture_unmatched')
            return
        f, ko = matches[0]
        try:
            native_date = instant(row['date'])
        except ValueError:
            witness('native_date_unproven')
            return
        if native_date != ko:
            witness('native_date_mismatch')
            return
        if observed >= ko:
            witness('post_kickoff')
            return
        pick = dict(id='notbetting-tip:' + identifier, sourceId='NotBetting', sourceTipId=identifier, authorId='public:' + sha256(('notbetting:' + uid).encode()).hexdigest(), authorLabel=label, fixtureId=f['id'], kickoff=ko.isoformat(), selection=row['pick'], sourceFields=fields, sourceRecordFingerprint=sha256(signature).hexdigest(), observedAt=observed.isoformat(), firstSeenAt=known_first.get(identifier, observed).isoformat(), publishedAt=None, publicationUnknown=True, responseSHA=responseSHA, parserSHA=parserSHA, calendarSHA=calendarSHA, calendarClaim=calendarClaim, interpretationAllowed=False, performanceEvaluationAllowed=False, settlementAllowed=False, eligibleForApplication=False)
        if len(result['picks']) < MAX_PICKS:
            result['picks'].append(pick)
        else:
            result['omittedAdmissible'] += 1

    def walk(value, depth=0, chain=()):
        if result['walkBoundHit']:
            return
        try:
            touch(value, depth)
        except ReferenceFailure as error:
            _capture(error, value, depth, len(chain))
            incomplete(str(error))
            return
        if isinstance(value, str) and value.startswith('$'):
            if value == '$' or value.startswith(('$$', '$S', '$D', '$n')) or value in {'$I', '$-I', '$-0', '$N', '$u', '$undefined', '$Infinity', '$-Infinity', '$NaN'}:
                return
            if value.startswith('$L') and value[2:] in documents.get('__flight_import_ids', []):
                return
            try:
                target, active, selected_depth = plain(value, chain, depth)
            except ReferenceFailure as error:
                _capture(error, value, depth, len(chain))
                incomplete(str(error))
                return
            walk(target, selected_depth, active)
        elif isinstance(value, list):
            for item in value:
                if result['walkBoundHit']:
                    break
                walk(item, depth + 1, chain)
        elif isinstance(value, dict):
            if any((isinstance(value.get(k), str) and SKIP.search(value[k]) for k in ('type', 'kind', '__typename'))):
                return
            if 'event' in value and 'pick' in value or (isinstance(value.get('id'), str) and value['id'] in known_ids):
                examine(value)
            for key, item in value.items():
                if result['walkBoundHit']:
                    break
                if isinstance(key, str) and (not SKIP.search(key)) and (key not in {'tipster', 'user'}):
                    walk(item, depth + 1, chain)
    roots = [key for key in ('0', 'next_data') if key in documents]
    if not roots:
        incomplete('document_root_absent')
    for key in roots:
        walk(documents[key])
    if conflicts & (owned | set(known_ids)):
        reject('contradictory_id')
    if result['omittedAdmissible']:
        reject('retention_limit')
    if not result['traversalComplete'] or 'contradictory_id' in result['reasons'] or result['omittedAdmissible']:
        result['picks'] = []
    if not result['picks']:
        reject('no_admissible_choice')
    return result

def accepted_calendar(raw, expectedSHA, expectedClaim):
    """Bind retained accepted programme bytes. Caller authenticates authority."""
    if type(raw) is not bytes or not 0 < len(raw) <= 131072 or (not isinstance(expectedSHA, str)) or (HASH.fullmatch(expectedSHA) is None) or (not isinstance(expectedClaim, str)) or (not 0 < len(expectedClaim) <= 200):
        raise ValueError('ACCEPTED_CALENDAR_INPUT')
    if sha256(raw).hexdigest() != expectedSHA:
        raise ValueError('ACCEPTED_CALENDAR_SHA')

    def closed_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('CALENDAR_DUPLICATE_KEY')
            obj[key] = value
        return obj
    value = json.loads(raw.decode('utf8', 'strict'), object_pairs_hook=closed_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('CALENDAR_NUMBER')))
    if not isinstance(value, dict) or value.get('schemaVersion') != 'robin-official-published-calendar-v1' or value.get('claimId') != expectedClaim or (value.get('status') != 'ACCEPTED_PUBLISHED_UTC_PROGRAMME_ONLY') or (value.get('competition') != 'Bundesliga') or (value.get('season') != '2026/27') or (type(value.get('matchday')) is not int) or (value['matchday'] != 11) or (value.get('nativeCalendarAccepted') is not True) or (value.get('bodyComplete') is not True) or (value.get('sourceUTCHeaderConfirmed') is not True) or (value.get('sourceCETHeaderConfirmed') is not True) or (type(value.get('pageCountFromPinnedPredicate')) is not int) or (value['pageCountFromPinnedPredicate'] != 1) or (not isinstance(value.get('fixtures'), list)) or (not 0 < len(value['fixtures']) <= 10):
        raise ValueError('ACCEPTED_CALENDAR_SCHEMA')

    def utc(text):
        if not isinstance(text, str) or re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,6})?(?:Z|\\+00:00)', text) is None:
            raise ValueError('CALENDAR_UTC_REQUIRED')
        return instant(text)
    observed = utc(value.get('sourceObservedAt'))
    if utc(value.get('sourceClosedAt')) < observed or utc(value.get('acceptedAt')) < observed:
        raise ValueError('CALENDAR_TIME_ORDER')
    for key in ('sourceResultRAW_SHA256', 'payloadSHA256'):
        if not isinstance(value.get(key), str) or HASH.fullmatch(value[key]) is None:
            raise ValueError('CALENDAR_PROVENANCE')
    fixtures, teams, identifiers = ([], set(), set())
    for row in value['fixtures']:
        if not isinstance(row, dict) or set(row) != {'home', 'away', 'scheduledUTC', 'semantic'} or row['semantic'] != 'DFL_SCHEDULED_UTC_ONLY' or (not all((isinstance(row[k], str) and 0 < len(row[k]) <= 96 and (row[k] == row[k].strip()) for k in ('home', 'away')))) or (row['home'] == row['away']) or (row['home'] in teams) or (row['away'] in teams):
            raise ValueError('CALENDAR_CANONICAL_ROW')
        kickoff = utc(row['scheduledUTC'])
        if kickoff <= observed or not datetime(2026, 11, 23, tzinfo=timezone.utc) <= kickoff < datetime(2026, 11, 30, tzinfo=timezone.utc):
            raise ValueError('CALENDAR_DATE_RANGE')
        identifier = 'calendar:' + sha256(canonical([expectedSHA, row['home'], row['away'], kickoff.isoformat()])).hexdigest()
        if identifier in identifiers:
            raise ValueError('CALENDAR_DUPLICATE_FIXTURE')
        identifiers.add(identifier)
        teams.update((row['home'], row['away']))
        fixtures.append(dict(id=identifier, home=row['home'], away=row['away'], kickoff=kickoff.isoformat(), competition='Bundesliga', calendarSHA=expectedSHA, calendarClaim=expectedClaim))
    return fixtures
