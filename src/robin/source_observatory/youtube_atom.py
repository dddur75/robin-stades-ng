"""Private offline spike for caller-supplied YouTube Atom/WebSub XML.

No request, subscription, transport authentication, terms grant, persistence,
fixture admission or human identification is performed. DTD/entities are rejected
before parsing. Caller-supplied bytes
may be synthetic: structural agreement does not prove publisher authenticity.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, TypedDict
from xml.etree import ElementTree  # nosec B405

from robin.source_observatory.extractor import extract_contributions
from robin.source_observatory.public_formats import decode_document

ATOM = '{http://www.w3.org/2005/Atom}'
YT = '{http://www.youtube.com/xml/schemas/2015}'
MEDIA = '{http://search.yahoo.com/mrss/}'
CHANNEL = re.compile(r'UC[A-Za-z0-9_-]{22}')
VIDEO = re.compile(r'[A-Za-z0-9_-]{11}')
INSTANT = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})')


class Provenance(TypedDict):
    adapter: Literal['youtube_atom_offline_spike']
    transport: Literal['caller_supplied_unverified']
    binding: Literal['xml_channel_video_consistent_only']
    attribution: Literal['channel_publisher_unverified_human']
    declaredLinkNormalization: Literal['scheme_upgrade_only']
    observedAt: str
    bodySha256: str


class ParsedFeed(TypedDict):
    provenance: Provenance
    sourceGrant: Literal['NOT_GRANTED']
    admissions: Literal[0]
    publications: list[dict[str, Any]]
    candidates: list[dict[str, Any]]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _one(parent: ElementTree.Element, tag: str, *, optional: bool = False) -> ElementTree.Element | None:
    nodes = parent.findall(tag)
    if len(nodes) == 1:
        return nodes[0]
    if optional and not nodes:
        return None
    raise ValueError('missing or ambiguous field')


def _text(parent: ElementTree.Element, tag: str) -> str:
    node = _one(parent, tag)
    if node is None or len(node) or not node.text or not node.text.strip():
        raise ValueError('nonempty scalar field required')
    return node.text.strip()


def _date(text: str, observed: datetime) -> datetime:
    if not INSTANT.fullmatch(text):
        raise ValueError('explicit RFC3339 timezone required')
    try:
        value = datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(UTC)
    except ValueError:
        raise ValueError('invalid date') from None
    if value > observed:
        raise ValueError('future timestamp')
    return value


def _author(parent: ElementTree.Element, channel: str) -> str:
    author = _one(parent, ATOM + 'author')
    allowed = {scheme + '://www.youtube.com/channel/' + channel for scheme in ('http', 'https')}
    if author is None or _text(author, ATOM + 'uri') not in allowed:
        raise ValueError('author channel mismatch')
    return _text(author, ATOM + 'name')


def _link(parent: ElementTree.Element, relation: str, expected: set[str]) -> str:
    links = [link for link in parent.findall(ATOM + 'link')
             if link.get('rel', 'alternate') == relation]
    if len(links) != 1 or links[0].get('href') not in expected:
        raise ValueError('missing or conflicting pinned URL')
    return str(links[0].get('href'))


def parse_youtube_atom(body: bytes, *, requested_channel_id: str, source_id: str,
                       observed_at: datetime) -> ParsedFeed:
    """Validate a single channel document and project minimal structured facts.

    Entry timestamps are publisher declarations, observed_at is the caller's
    observation, and no kickoff/physical human identity is inferred. Extraction
    retains only structured literal candidates; descriptions are optional.
    """
    if (not isinstance(body, bytes) or not body or len(body) > 2_000_000
            or not isinstance(requested_channel_id, str)
            or not CHANNEL.fullmatch(requested_channel_id)
            or not isinstance(source_id, str) or not re.fullmatch(r'SRC_\d{3}', source_id)):
        raise ValueError('bounded bytes and explicit source/channel required')
    if not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        raise ValueError('aware observation time required')
    observed = observed_at.astimezone(UTC)
    try:
        text = decode_document(body, 'application/atom+xml')
    except (UnicodeError, LookupError):
        raise ValueError('invalid XML encoding') from None
    # Reject every DTD, including HTML, before ElementTree can expand entities.
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I) or '\x00' in text:
        raise ValueError('DTD/entities forbidden')
    try:
        root = ElementTree.fromstring(text)  # nosec B314
    except ElementTree.ParseError:
        raise ValueError('invalid Atom XML') from None
    if root.tag != ATOM + 'feed':
        raise ValueError('Atom namespace required')
    channel = requested_channel_id
    _link(root, 'self', {f'https://www.youtube.com/{prefix}feeds/videos.xml?channel_id={channel}'
                         for prefix in ('', 'xml/')})
    feed_id = _one(root, ATOM + 'id', optional=True)
    if feed_id is not None and _text(root, ATOM + 'id') != 'yt:channel:' + channel:
        raise ValueError('feed identity mismatch')
    if root.findall(ATOM + 'author'):
        _author(root, channel)
    for channel_node in root.findall(YT + 'channelId'):
        if channel_node.text != channel or len(channel_node):
            raise ValueError('feed channel mismatch')
    if len(root.findall(YT + 'channelId')) > 1:
        raise ValueError('duplicate feed channel')
    for tag in ('published', 'updated'):
        node = _one(root, ATOM + tag, optional=True)
        if node is not None:
            _date(_text(root, ATOM + tag), observed)

    publications: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen: dict[str, bytes] = {}
    for item in root.findall(ATOM + 'entry'):
        video = _text(item, YT + 'videoId')
        if not VIDEO.fullmatch(video) or _text(item, YT + 'channelId') != channel:
            raise ValueError('entry channel/video mismatch')
        if _text(item, ATOM + 'id') != 'yt:video:' + video:
            raise ValueError('entry identity mismatch')
        # These are XML-declared identifiers, never fetch targets. Accept the
        # documented HTTP form only at the exact same host/path/validated ID.
        # Projection upgrades the scheme; no redirect or HTTP access occurs.
        _link(item, 'alternate', {scheme + '://www.youtube.com/watch?v=' + video
                                  for scheme in ('http', 'https')})
        url = 'https://www.youtube.com/watch?v=' + video
        author_name = _author(item, channel)
        title = _text(item, ATOM + 'title')
        published = _date(_text(item, ATOM + 'published'), observed)
        updated = _date(_text(item, ATOM + 'updated'), observed)
        if updated < published:
            raise ValueError('updated precedes published')
        description = None
        group = _one(item, MEDIA + 'group', optional=True)
        if group is not None:
            node = _one(group, MEDIA + 'description', optional=True)
            if node is not None:
                if len(node):
                    raise ValueError('scalar media description required')
                description = node.text or ''
        # Duplicate comparison binds all extracted metadata, including dates/name.
        identity = _canonical([channel, video, url, author_name, title, description,
                               published.isoformat(), updated.isoformat()])
        if video in seen:
            if seen[video] != identity:
                raise ValueError('contradictory duplicate video')
            continue
        seen[video] = identity
        content = title + ('\n' + description if description is not None else '')
        digest = sha256(content.encode()).hexdigest()
        publication_id = sha256(f'{source_id}|{url}'.encode()).hexdigest()
        author_id = 'author:' + sha256(f'{source_id}|channel:{channel}'.encode()).hexdigest()
        attribution = 'channel_publisher_unverified_human'
        dates = dict(announcedAt=published.isoformat(), updatedAt=updated.isoformat(),
                     observedAt=observed.isoformat())
        publications.append(dict(id=publication_id, sourceId=source_id, url=url,
            contentSha256=digest, authorId=author_id, authorStatus=attribution,
            verifiedPreMatch=False, **dates))
        for row in extract_contributions(content, source_id=source_id, publication_url=url,
                author_id=author_id, publication_id=publication_id, version_id=digest,
                observed_at=observed):
            candidates.append(dict(id=row['contribution_id'], sourceId=source_id,
                publicationId=publication_id, authorId=author_id, authorStatus=attribution,
                url=url, contentSha256=digest, market=row['marche'], selection=row['selection'],
                line=row['ligne'], declaredOdds=row['cote_declaree'], extractionStatus=row['statut'],
                status='unresolved_fixture', verifiedPreMatch=False, fixtureId=None,
                kickoff=None, **dates))
    return dict(sourceGrant='NOT_GRANTED', admissions=0, publications=publications,
        candidates=candidates, provenance=dict(adapter='youtube_atom_offline_spike',
            transport='caller_supplied_unverified', binding='xml_channel_video_consistent_only',
            attribution='channel_publisher_unverified_human',
            declaredLinkNormalization='scheme_upgrade_only', observedAt=observed.isoformat(),
            bodySha256=sha256(body).hexdigest()))
