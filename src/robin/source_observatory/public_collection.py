"""Read hash-checked public-post history without contacting suppliers."""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from .connectors import read_events
from .recurring import instant


def read_collection(directory: Path) -> dict[str, Any]:
    events = read_events(directory / 'events.jsonl')
    accepted = [e for e in events if e['kind'] == 'PUBLIC_COLLECTION_ACCEPTED']
    if not accepted:
        raise ValueError('accepted collection evidence absent')
    all_picks: dict[str, dict[str, Any]] = {}
    data: dict[str, Any] = {}
    recurring = False
    for event in accepted:
        digest = event['observationSha256']
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('invalid bundle digest')
        filename = 'observations-' + digest + '.json'
        if event['observationFile'] != filename:
            raise ValueError('unapproved bundle path')
        raw = (directory / filename).read_bytes()
        if len(raw) > 2_000_000 or sha256(raw).hexdigest() != digest:
            raise ValueError('collection hash mismatch')
        data = json.loads(raw)
        if data['schemaVersion'] != 'robin-public-tipsters-v1' or len(data['picks']) != event['count']:
            raise ValueError('collection schema/count mismatch')
        fixtures = {f['id']: f for f in data['fixtures']}
        recurring = recurring or data.get('recurring', False)
        for pick in data['picks']:
            fixture = fixtures[pick['fixtureId']]
            proof = [e for e in events if e['kind'] == 'PUBLIC_PICKS_QUALIFIED'
                     and e.get('sourceId') == pick['sourceId']
                     and e.get('responseSha256') == pick['responseSha256']
                     and e.get('parserSha256') == data['parserSha256']
                     and e.get('calendarSha256') == data['calendarSha256']]
            if (not proof or instant(pick['observedAt']) >= instant(fixture['kickoff'])
                    or not fixture['publicationWindowStart'] <= pick['publishedCivilDate'] <= fixture['kickoff'][:10]
                    or not re.fullmatch(r'\d{1,2}-\d{1,2}', pick['selection'])):
                raise ValueError('personal pre-match evidence missing')
            previous = all_picks.get(pick['id'])
            first = previous['firstSeenAt'] if previous else pick['observedAt']
            versions = list(previous['versions']) if previous else []
            if not versions or versions[-1]['selection'] != pick['selection']:
                versions.append(dict(selection=pick['selection'], observedAt=pick['observedAt']))
            all_picks[pick['id']] = dict(pick, firstSeenAt=first, lastSeenAt=pick['observedAt'],
                                         versions=versions, versionCount=len(versions))
    data.update(status='ok', picks=list(all_picks.values()), distinctPicks=len(all_picks),
                authorCount=len({p['authorId'] for p in all_picks.values()}),
                requestCount=sum(e['kind'] == 'REQUEST_RESERVED' for e in events),
                journalHead=events[-1]['hash'], observationSha256=accepted[-1]['observationSha256'],
                dossierVerdict='PARTIAL', recurring=recurring,
                halted=any(e['kind'] == 'CAMPAIGN_HALTED' for e in events))
    return data
