"""Prepare/check a bounded forum campaign. Execution needs an exact owner grant."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .collector import robots_policy
from .connectors import Journal, Response, canonical, permission, public_get
from .forum_tipsters import extract_posts, qualify_posts
from .public_formats import _Node, _Tree, decode_document
from .recurring import instant


def _visible(node: _Node) -> str:
    if node.tag in {'script', 'style', 'head', 'noscript', 'template', 'svg'}:
        return ''
    if 'hidden' in node.attrs or node.attrs.get('aria-hidden') == 'true':
        return ''
    return ' '.join(' '.join(_visible(c) if isinstance(c, _Node) else c
                             for c in node.children).split())


def legal_digest(body: bytes) -> str:
    tree = _Tree()
    tree.feed(decode_document(body))
    tree.close()
    text = _visible(tree.root)
    if len(text) < 500 or 'phpBB' not in text or 'accédant' not in text:
        raise ValueError('publisher terms need review')
    if permission(text, 'forum_html') != 'public_page_facts_only':
        raise ValueError('publisher terms need review')
    return sha256(text.encode()).hexdigest()


def validate_campaign(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan: dict[str, Any] = json.loads((directory / 'plan.json').read_bytes())
    manifest: dict[str, Any] = json.loads((directory / 'manifest.json').read_bytes())
    grant = json.loads((directory / 'authorization.json').read_bytes())
    digest = sha256(canonical(plan)).hexdigest()
    if (grant.get('planSha256') != digest or grant.get('statement') != plan['authorizationText']
            or grant.get('manifestSha256') != sha256(canonical(manifest)).hexdigest()
            or manifest['source_hash'] != digest or manifest['mission_id'] != plan['id']):
        raise ValueError('exact owner authorization required for plan and manifest')
    repo = Path(__file__).resolve().parents[3]
    for name, expected in plan['codePins'].items():
        if sha256((repo / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
            raise ValueError('code changed; new preparation required')
    return plan, manifest


def run_slot(directory: Path, *, now: datetime | None = None,
             get: Callable[..., Response] = public_get,
             sleep: Callable[[float], None] = time.sleep,
             clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict[str, Any]:
    current = now or clock()
    plan, manifest = validate_campaign(directory)
    if current >= instant(manifest['expires_at']):
        return {'state': 'expired', 'requests': 0}
    due = [s for s in plan['slots'] if 0 <= (current - instant(s)).total_seconds() <= 180]
    if len(due) != 1:
        return {'state': 'not_due', 'requests': 0}
    slot = due[0]
    deadline = instant(slot) + timedelta(seconds=210)
    lock = directory / 'campaign.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(slot)
    try:
        journal = Journal(directory, manifest, now=clock)
        if any(e['kind'] == 'CAMPAIGN_HALTED' for e in journal.events):
            return {'state': 'halted', 'requests': 0}
        if any(e['kind'] == 'PUBLIC_SLOT_STARTED' and e['slot'] == slot for e in journal.events):
            return {'state': 'already_started', 'requests': 0}
        journal.append('RUN_STARTED', slot=slot)
        journal.append('PUBLIC_SLOT_STARTED', slot=slot)
        picks = []
        try:
            for profile in plan['profiles']:
                rules = None
                for url in [profile['robotsUrl'], profile['termsUrl'], profile['endpoint']]:
                    delay = 2.0
                    if rules is not None:
                        allowed, delay = robots_policy(rules, url)
                        if not allowed or delay > 30:
                            raise ValueError('robots denied or pacing bound')
                    remaining = min(journal.remaining_seconds(), (deadline - clock()).total_seconds())
                    if remaining <= max(2, delay) + 1:
                        raise ValueError('slot deadline exhausted')
                    sleep(max(2, delay))
                    reservation = journal.reserve(profile['id'], url)
                    timeout = min(30.0, journal.remaining_seconds(), (deadline - clock()).total_seconds())
                    if timeout <= 0:
                        raise ValueError('slot deadline exhausted')
                    response = get(url, timeout=timeout)
                    if clock() >= deadline:
                        raise ValueError('slot deadline exceeded')
                    observed = clock()
                    body_sha = sha256(response.body).hexdigest()
                    journal.append('REQUEST_FINISHED', sourceId=profile['id'], url=url,
                                   reservation=reservation, httpStatus=response.status,
                                   responseSha256=body_sha)
                    if response.status != 200:
                        raise ValueError('public source unavailable')
                    if url == profile['robotsUrl']:
                        rules = decode_document(response.body)
                    elif url == profile['termsUrl']:
                        if legal_digest(response.body) != profile['termsSha256']:
                            raise ValueError('publisher terms changed')
                    else:
                        rows = qualify_posts(extract_posts(response.body, url, profile['id'], observed), plan['fixtures'])
                        picks.extend(rows)
                        journal.append('PUBLIC_PICKS_QUALIFIED', sourceId=profile['id'], url=url,
                                       responseSha256=body_sha, count=len(rows),
                                       parserSha256=plan['parserSha256'], calendarSha256=plan['calendarSha256'])
            if not picks:
                raise ValueError('no admissible personal pick; campaign halted')
            data = dict(schemaVersion='robin-public-tipsters-v1', missionId=plan['id'],
                        claimId=plan['claimId'], fixtures=plan['fixtures'], picks=picks,
                        parserSha256=plan['parserSha256'], calendarSha256=plan['calendarSha256'],
                        generatedAt=clock().isoformat(), recurring=True)
            raw = canonical(data) + b'\n'
            digest = sha256(raw).hexdigest()
            filename = 'observations-' + digest + '.json'
            with (directory / filename).open('xb') as stream:
                stream.write(raw)
            journal.append('PUBLIC_COLLECTION_ACCEPTED', observationFile=filename,
                           observationSha256=digest, count=len(picks),
                           authors=len({p['authorId'] for p in picks}), slot=slot)
            journal.append('PUBLIC_SLOT_FINISHED', slot=slot, count=len(picks))
            return {'state': 'succeeded', 'picks': len(picks), 'requests': 6}
        except Exception as exc:
            journal.append('CAMPAIGN_HALTED', slot=slot, reason=type(exc).__name__)
            raise
        finally:
            journal.append('RUN_FINISHED', slot=slot)
    finally:
        lock.unlink()
