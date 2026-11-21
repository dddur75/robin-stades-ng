"""Bounded public-source connectors, separate from the frozen J12 collector.

Provider bodies exist only in memory. Durable data consists of hashes, links,
timestamps, pseudonyms and extracted facts. A candidate is never a proven bet.
"""
from __future__ import annotations

import csv
import http.client
import ipaddress
import json
import os
import queue
import re
import socket
import ssl
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree  # nosec B405 - declarations rejected first

from .collector import USER_AGENT, _announced, parse_publications, robots_policy
from .extractor import extract_contributions
from .public_formats import (
    _anchor,
    _article_link,
    _Node,
    _Tree,
    _walk,
    check_declarations,
    clean_text,
    decode_document,
)

MAX_BYTES = 2_000_000
MAX_JOURNAL_BYTES = 16_000_000
ZERO = '0' * 64


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def stamp(now: datetime) -> str:
    if now.utcoffset() is None:
        raise ValueError('timezone required')
    return now.astimezone(UTC).isoformat()


def public_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in (None, 443 if parsed.scheme == 'https' else 80)
            or any(ord(c) <= 32 for c in url)
            or any(re.search('token|key|secret|password|auth|session', key, re.I)
                   for key, _ in parse_qsl(parsed.query))):
        raise ValueError('public URL required')
    return url


def build_profiles(path: Path) -> list[dict[str, Any]]:
    """One executable or explicitly gated adapter for every requested source ID."""
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = [row for row in csv.DictReader(stream) if row['etat_connecteur'] == 'a_construire']
    profiles = []
    for row in rows:
        access, url = row['mode_acces'], row['adresse']
        match = re.search(r'https?://[^\s)]+', access) if re.search('rss|atom', access, re.I) else None
        endpoint = match[0] if match else url
        terms = re.search(r'https?://[^\s)]+', row['cgu_connues'].split('; robots.txt')[0])
        adapter = 'rss_atom' if match else 'forum_html' if 'forum' in row['type'] else 'html_public'
        if 'youtube.com' in url:
            adapter = 'official_api_required'  # no permission inferred from an old CSV note
        origin = urlsplit(endpoint)
        terms_url = terms[0] if terms else None
        # Cross-domain feeds/legal services need a separate profile and robots policy.
        if origin.hostname.removeprefix('www.') != urlsplit(url).hostname.removeprefix('www.'):  # type: ignore[union-attr]
            adapter = 'cross_domain_permission_required'
        if terms_url and urlsplit(terms_url).netloc != origin.netloc:
            terms_url = None
        profiles.append(dict(id=row['source_id'], name=row['nom'], url=url,
            endpoint=public_url(endpoint), adapter=adapter, termsUrl=terms_url,
            robotsUrl=f'{origin.scheme}://{origin.netloc}/robots.txt',
            audience=row['categorie_audience'], language=row['langue'],
            humanEvidence='not_verified', registryCheckedAt=row['verifie_le']))
    if len(profiles) != 57 or len({p['id'] for p in profiles}) != 57:
        raise ValueError('exact 57-source registry required')
    return profiles


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str
    location: str | None
    link_header: str | None = None


def public_get(url: str, *, timeout: float = 40.0) -> Response:
    """Resolve once, reject non-public addresses, pin TCP and preserve TLS SNI.

    No redirects, proxies, cookies, credentials, retries or JavaScript execution.
    """
    parsed = urlsplit(public_url(url))
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError('public hostname required')
    port = 443 if parsed.scheme == 'https' else 80
    deadline = time.monotonic() + timeout
    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError('transfer deadline')
        return min(12.0, value)
    resolved: queue.Queue[Any] = queue.Queue(maxsize=1)
    def resolve() -> None:
        try:
            resolved.put(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            resolved.put(exc)
    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = resolved.get(timeout=remaining())
    except queue.Empty as exc:
        raise TimeoutError('DNS deadline') from exc
    if isinstance(addresses, OSError):
        raise addresses
    if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
        raise ValueError('non-public DNS result')
    family, socktype, proto, _, address = addresses[0]
    connection = http.client.HTTPConnection(hostname, port, timeout=12)
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(remaining())
    active_socket = [sock]
    expired = threading.Event()
    def interrupt() -> None:
        expired.set()
        try:
            active_socket[0].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        active_socket[0].close()
    guard = threading.Timer(max(.001, deadline - time.monotonic()), interrupt)
    guard.daemon = True
    guard.start()
    try:
        sock.connect(address)
        sock.settimeout(remaining())
        connection.sock = (ssl.create_default_context().wrap_socket(sock, server_hostname=hostname)
                           if parsed.scheme == 'https' else sock)
        active_socket[0] = connection.sock
        target = parsed.path or '/'
        if parsed.query:
            target += '?' + parsed.query
        connection.request('GET', target, headers={'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'})
        if connection.sock is None:
            raise OSError('public transport unavailable')
        transport = connection.sock
        transport.settimeout(remaining())
        response = connection.getresponse()
        # Error/redirect documents are not content and must not be stored/parsed.
        body = b''
        if response.status == 200:
            chunks = []
            size = 0
            while size <= MAX_BYTES:
                transport.settimeout(remaining())
                chunk = response.read1(min(65_536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b''.join(chunks)
        if len(body) > MAX_BYTES:
            raise ValueError('response size limit')
        if expired.is_set():
            raise TimeoutError('transfer deadline')
        return Response(response.status, body, response.getheader('Content-Type', ''),
                        response.getheader('Location'), response.getheader('Link'))
    except (OSError, http.client.HTTPException) as exc:
        if expired.is_set():
            raise TimeoutError('transfer deadline') from exc
        raise
    finally:
        guard.cancel()
        connection.close()
        sock.close()


def permission(text: str, adapter: str) -> str:
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                     if not unicodedata.combining(c))
    if (len(folded.strip()) < 30 or re.search(
            r'captcha|verify you are human|access denied|checking your browser|just a moment', folded)):
        return 'terms_unverified'
    # A public feed cannot override the publisher's contrary current conditions.
    if re.search(r'(?:automat|scrap|robots?|reproduc|represent|copi|extract|distribut).{0,180}'
                 r'(?:interdi|prohibit|forbidden|not permitted|permission|autorisation)|'
                 r'(?:interdi|prohibit|forbidden).{0,180}(?:scrap|automat|cop|reproduc)|'
                 r'usage personnel|non[- ]commercial|personal use|you may not|'
                 r'(?:automat|scrap).{0,100}not allowed|no scraping|no automated', folded, re.S):
        return 'permission_required'
    if not re.search(r'mentions legales|conditions|terms|legal|editeur|publisher|privacy', folded):
        return 'terms_unverified'
    return 'public_feed_facts_only' if adapter == 'rss_atom' else 'public_page_facts_only'


def _tag(element: Any) -> str:
    return str(element.tag).rsplit('}', 1)[-1].lower()


def extract_feed(body: bytes, endpoint: str, source_id: str,
                 observed: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = decode_document(body, 'application/xml')
    check_declarations(text)
    document = ElementTree.fromstring(text)  # nosec B314 - declarations rejected
    if _tag(document) not in {'rss', 'feed', 'rdf'}:
        raise ValueError('not a supported feed')
    publications, candidates = [], []
    for item in document.iter():
        if _tag(item) not in {'entry', 'item'}:
            continue
        values: dict[str, str] = {}
        link = None
        author = None
        for child in item:
            key = _tag(child)
            value = ''.join(child.itertext()).strip()
            if key == 'link':
                if child.get('rel', 'alternate') == 'alternate':
                    link = child.get('href') or value
            elif key in {'creator', 'author'}:
                # Explicit publisher attribution, hashed as a source-scoped identity.
                author = next((n.text for n in child if _tag(n) == 'name'), value)
            elif key in {'title', 'description', 'summary', 'content', 'encoded', 'pubdate', 'published', 'updated'}:
                values[key] = value
        if not link:
            continue
        try:
            public_url(urlsplit(link)._replace(fragment='').geturl())
        except ValueError:
            continue
        if urlsplit(link).hostname != urlsplit(endpoint).hostname:
            continue
        content = clean_text('\n'.join(values.get(k, '') for k in
                             ('title', 'description', 'summary', 'content', 'encoded')))
        if not content:
            continue
        announced = _announced(values.get('pubdate') or values.get('published'))
        author_id = 'author:' + sha256(f'{source_id}|{author}'.encode()).hexdigest() if author else None
        publication_id = sha256(f'{source_id}|{link}'.encode()).hexdigest()
        digest = sha256(content.encode()).hexdigest()
        publications.append(dict(id=publication_id, sourceId=source_id, url=link,
            contentSha256=digest, authorId=author_id, authorStatus='publisher_attributed_unverified_human'
            if author_id else 'missing', announcedAt=stamp(announced) if announced else None,
            observedAt=stamp(observed)))
        if not author_id or not announced or announced > observed:
            continue
        for row in extract_contributions(content, source_id=source_id, publication_url=link,
                author_id=author_id, publication_id=publication_id, version_id=digest,
                observed_at=observed):
            # No quotes, offsets, original author names, titles or prose in storage.
            candidates.append(dict(id=row['contribution_id'], sourceId=source_id,
                publicationId=publication_id, authorId=author_id, url=link,
                contentSha256=digest, market=row['marche'], selection=row['selection'],
                line=row['ligne'], declaredOdds=row['cote_declaree'],
                announcedAt=stamp(announced), observedAt=stamp(observed),
                status='unresolved_fixture', verifiedPreMatch=False,
                extractionStatus=row['statut'], fixtureId=None, kickoff=None))
    # A repeated feed item is one version, never an additional publication/pick.
    return (list({(p['id'], p['contentSha256']): p for p in publications}.values()),
            list({p['id']: p for p in candidates}.values()))


def extract_html(body: bytes, endpoint: str, source_id: str,
                 observed: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Passive HTML/JSON-LD/article/forum reader; author evidence stays scoped.

    Names from explicit article author markup are hashed in memory. A general
    page author, navigation/profile link or publisher never becomes a tipster.
    """
    text = decode_document(body)
    check_declarations(text)
    posts = parse_publications(body, endpoint, content_type='text/html')
    tree = _Tree()
    tree.feed(text)
    tree.close()
    authors: dict[str, set[str]] = {}

    def add_author(url: Any, author: Any) -> None:
        if (isinstance(url, str) and isinstance(author, str) and author.strip()
                and len(author) <= 300 and urlsplit(url).hostname == urlsplit(endpoint).hostname):
            authors.setdefault(url, set()).add(author.strip())

    def structured(data: Any, depth: int = 0) -> None:
        if depth > 12:
            return
        if isinstance(data, list):
            for row in data[:200]:
                structured(row, depth + 1)
        elif isinstance(data, dict):
            kind = data.get('@type')
            kinds = kind if isinstance(kind, list) else [kind]
            if any(k in {'Article', 'NewsArticle', 'BlogPosting', 'DiscussionForumPosting'} for k in kinds):
                target = data.get('url') or data.get('mainEntityOfPage') or data.get('@id')
                if isinstance(target, dict):
                    target = target.get('@id')
                author = data.get('author')
                if isinstance(author, dict) and author.get('@type') == 'Person':
                    add_author(target, author.get('name'))
            structured(data.get('@graph'), depth + 1)
            structured(data.get('itemListElement'), depth + 1)
            if data.get('@type') == 'ListItem':
                structured(data.get('item'), depth + 1)

    for node in _walk(tree.root, metadata=True):
        if node.tag == 'script' and node.attrs.get('type') == 'application/ld+json':
            try:
                structured(json.loads(''.join(c for c in node.children if isinstance(c, str))))
            except (ValueError, RecursionError):
                continue
        if (node.tag == 'article' or node.tag == 'div' and node.attrs.get('id')
                and 'post' in (node.attrs.get('class') or '').split()):
            target = _article_link(node, endpoint)
            if not target and node.attrs.get('id'):
                target = _anchor(endpoint, node.attrs['id'], '')
            if not target and len(posts) == 1:
                target = posts[0].url
            def bylines(parent: _Node) -> list[_Node]:
                found = []
                for child in parent.children:
                    if not isinstance(child, _Node) or child.tag in {'script', 'style', 'nav', 'footer', 'aside'}:
                        continue
                    if 'hidden' in child.attrs or child.attrs.get('aria-hidden') == 'true':
                        continue
                    if ('author' in (child.attrs.get('rel') or '').split()
                            or child.attrs.get('itemprop') == 'author'):
                        found.append(child)
                    else:
                        found.extend(bylines(child))
                return found
            def byline_text(parent: _Node) -> str:
                return ' '.join(byline_text(c) if isinstance(c, _Node) else c for c in parent.children)
            for child in bylines(node):
                if ('author' in (child.attrs.get('rel') or '').split()
                        or child.attrs.get('itemprop') == 'author'):
                    # Scope is this post only; do not traverse linked profiles.
                    name = byline_text(child).strip()
                    add_author(target, name)
    rss = ElementTree.Element('rss')
    channel = ElementTree.SubElement(rss, 'channel')
    for post in posts[:100]:
        item = ElementTree.SubElement(channel, 'item')
        ElementTree.SubElement(item, 'link').text = post.url
        ElementTree.SubElement(item, 'description').text = post.text
        if post.announced_at:
            ElementTree.SubElement(item, 'pubDate').text = stamp(post.announced_at)
        names = authors.get(post.url, set())
        if len(names) == 1:
            ElementTree.SubElement(item, 'author').text = next(iter(names))
    return extract_feed(ElementTree.tostring(rss), endpoint, source_id, observed)


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open('rb') as stream:
        data = stream.read(MAX_JOURNAL_BYTES + 1)
    if len(data) > MAX_JOURNAL_BYTES or (data and not data.endswith(b'\n')):
        raise ValueError('journal integrity/size failure')
    previous = ZERO
    events: list[dict[str, Any]] = []
    for line in data.splitlines(keepends=True):
        record = json.loads(line)
        digest = record.pop('hash')
        if (record.get('previousHash') != previous or sha256(canonical(record)).hexdigest() != digest
                or line != canonical(record | {'hash': digest}) + b'\n'
                or record.get('sequence') != len(events) + 1):
            raise ValueError('journal integrity failure')
        previous = digest
        events.append(record | {'hash': digest})
    return events


class Journal:
    """Caller holds the exclusive run lock across all reservation/network writes."""
    def __init__(self, directory: Path, mission: dict[str, Any], *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.directory, self.now = directory, now
        self.directory.mkdir(parents=True, exist_ok=True)
        required = {'mission_id', 'authorized_stages', 'maximum_stage', 'external_effects',
                    'compute_budget', 'time_budget', 'source_hash', 'expires_at'}
        if set(mission) != required or mission['maximum_stage'] != 'E2':
            raise ValueError('invalid bounded E1/E2 mission')
        self.mission = mission
        self.phase_id = 'initial'
        path = directory / 'mission.json'
        encoded = canonical(mission) + b'\n'
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        if path.read_bytes() != encoded:
            raise ValueError('immutable mission mismatch')
        self.events = read_events(directory / 'events.jsonl')

    def append(self, kind: str, **payload: Any) -> dict[str, Any]:
        record = dict(sequence=len(self.events) + 1, kind=kind, at=stamp(self.now()),
                      previousHash=self.events[-1]['hash'] if self.events else ZERO, **payload)
        record['hash'] = sha256(canonical(record)).hexdigest()
        encoded = canonical(record) + b'\n'
        path = self.directory / 'events.jsonl'
        if path.exists() and path.stat().st_size + len(encoded) > MAX_JOURNAL_BYTES:
            raise ValueError('journal size budget')
        with path.open('ab') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        self.events.append(record)
        return record

    def reserve(self, source_id: str, url: str) -> str:
        now = self.now()
        if now >= datetime.fromisoformat(self.mission['expires_at']):
            raise ValueError('mission expired')
        if self.remaining_seconds() <= 0:
            raise ValueError('time budget exhausted')
        reservations = [r for r in self.events if r['kind'] == 'REQUEST_RESERVED']
        limits = self.mission['external_effects']
        if (len(reservations) >= limits['https_get_max']
                or sum(r['sourceId'] == source_id for r in reservations) >= limits['per_source_max']):
            raise ValueError('request budget exhausted')
        return str(self.append('REQUEST_RESERVED', sourceId=source_id, url=public_url(url), phaseId=self.phase_id)['hash'])

    def remaining_seconds(self) -> float:
        elapsed = 0.0
        started = None
        for event in self.events:
            if event['kind'] == 'RUN_STARTED':
                started = started or datetime.fromisoformat(event['at'])
            elif event['kind'] == 'RUN_FINISHED' and started is not None:
                elapsed += (datetime.fromisoformat(event['at']) - started).total_seconds()
                started = None
        if started is not None:
            elapsed += (self.now() - started).total_seconds()
        expiry = (datetime.fromisoformat(self.mission['expires_at']) - self.now()).total_seconds()
        return min(float(self.mission['time_budget']['seconds']) - elapsed, expiry)


def collect_source(profile: dict[str, Any], journal: Journal, *,
                   get: Callable[[str], Response] = public_get,
                   sleep: Callable[[float], None] = time.sleep,
                   robots_witness: dict[str, Any] | None = None) -> dict[str, Any]:
    source_id, endpoint = profile['id'], profile['endpoint']
    result: dict[str, Any] = dict(sourceId=source_id, status='not_run', permission='not_checked',
        endpoint=endpoint, adapter=profile['adapter'], phaseId=journal.phase_id, publications=[], candidates=[])

    def finish(status: str) -> dict[str, Any]:
        result['status'] = status
        journal.append('SOURCE_FINISHED', **result)
        return result

    if profile['adapter'] in {'official_api_required', 'cross_domain_permission_required'}:
        return finish(profile['adapter'])
    robots: str | None = None
    delay = 1.0

    def fetch(url: str) -> Response:
        if url not in {endpoint, profile['robotsUrl'], profile['termsUrl']}:
            raise ValueError('endpoint outside pinned profile')
        if robots_witness and journal.now() >= datetime.fromisoformat(robots_witness['expiresAt']):
            raise ValueError('robots witness expired')
        if robots is not None:
            allowed, wait = robots_policy(robots, url)
            if not allowed:
                raise ValueError('robots target denied')
        else:
            wait = 0.0
        # Shared-host pacing uses the last durable reservation, including errors.
        host = urlsplit(url).netloc
        prior = next((event for event in reversed(journal.events)
                      if event['kind'] == 'REQUEST_RESERVED' and urlsplit(event['url']).netloc == host), None)
        if prior:
            remaining = max(delay, wait) - (journal.now() - datetime.fromisoformat(prior['at'])).total_seconds()
            if remaining > 0:
                if remaining >= journal.remaining_seconds():
                    raise ValueError('pacing exceeds time budget')
                sleep(remaining)
        if robots_witness and journal.now() >= datetime.fromisoformat(robots_witness['expiresAt']):
            raise ValueError('robots witness expired after pacing')
        reservation = journal.reserve(source_id, url)
        try:
            response = (public_get(url, timeout=min(40, journal.remaining_seconds()))
                        if get is public_get else get(url))
            if len(response.body) > MAX_BYTES:
                raise ValueError('response size limit')
            journal.append('REQUEST_FINISHED', reservation=reservation, sourceId=source_id,
                url=url, httpStatus=response.status, bytes=len(response.body),
                responseSha256=sha256(response.body).hexdigest(), contentType=response.content_type[:150])
            return response
        except Exception as exc:
            journal.append('REQUEST_FAILED', reservation=reservation, sourceId=source_id,
                           url=url, errorType=type(exc).__name__)
            raise

    try:
        if robots_witness is None:
            response = fetch(profile['robotsUrl'])
            if response.status != 200:
                return finish(f'robots_http_{response.status}')
            robots = decode_document(response.body, response.content_type)
            allowed, delay = robots_policy(robots, endpoint)
            if not allowed:
                return finish('robots_denied')
            if delay > 60:
                return finish('crawl_delay_exceeds_budget')
        else:
            # The phase runner validates this exact same-day prior path and pins.
            # It reached terms only after robots allowed endpoint AND terms URL.
            if (robots_witness.get('sourceId') != source_id
                    or set(robots_witness.get('allowedUrls', [])) != {endpoint, profile['termsUrl']}):
                raise ValueError('robots witness scope mismatch')
            delay = 60.0
            robots = 'User-agent: *\nAllow: /\n'
            journal.append('ROBOTS_WITNESS_REUSED', sourceId=source_id, witness=robots_witness)
        if not profile['termsUrl']:
            return finish('terms_unverified')
        terms = fetch(profile['termsUrl'])
        if terms.status != 200:
            return finish(f'terms_http_{terms.status}')
        result['termsSha256'] = sha256(terms.body).hexdigest()
        result['permission'] = permission(clean_text(decode_document(terms.body, terms.content_type)), profile['adapter'])
        if result['permission'] not in {'public_feed_facts_only', 'public_page_facts_only'}:
            return finish(result['permission'])
        response = fetch(endpoint)
        if response.status != 200:
            return finish(f'content_http_{response.status}')
        observed = journal.now()
        if profile['adapter'] == 'rss_atom':
            publications, candidates = extract_feed(response.body, endpoint, source_id, observed)
        else:
            publications, candidates = extract_html(response.body, endpoint, source_id, observed)
        result.update(publications=publications, candidates=candidates)
        return finish('collected' if publications else 'readable_no_publication')
    except (OSError, ValueError, http.client.HTTPException, ElementTree.ParseError):
        return finish('read_failed')


def snapshot(directory: Path) -> dict[str, Any]:
    events = read_events(directory / 'events.jsonl')
    latest = {r['sourceId']: r for r in events if r['kind'] == 'SOURCE_FINISHED'}
    # Reuse immutable observations. Ambiguous parser outputs are an examination
    # queue, never selections; the original records remain intact in the journal.
    unresolved: list[dict[str, Any]] = []
    for identifier, source in list(latest.items()):
        valid = [p for p in source['candidates'] if p.get('extractionStatus') == 'resolu'
                 and p.get('market') != 'indetermine']
        unresolved.extend(p for p in source['candidates'] if p not in valid)
        latest[identifier] = source | {'candidates': valid}
    publications = {(p['id'], p['contentSha256']): p for r in latest.values() for p in r['publications']}
    candidates = {p['id']: p for r in latest.values() for p in r['candidates']}
    return dict(status='ok', schemaVersion='robin-connectors-v1',
        claimId='ENG.SOURCE_OBSERVATORY.CONNECTORS57.20261118',
        journalHead=events[-1]['hash'] if events else ZERO,
        updatedAt=events[-1]['at'] if events else None,
        counts=dict(requests=sum(r['kind'] == 'REQUEST_RESERVED' for r in events),
                    attemptedSources=len(latest), collectedSources=sum(r['status'] == 'collected' for r in latest.values()),
                    publications=len(publications), candidates=len(candidates),
                    unresolvedExtractions=len(unresolved), verifiedPreMatch=0),
        statusCounts=dict(Counter(r['status'] for r in latest.values())),
        sources=list(latest.values()), publications=list(publications.values()),
        candidates=list(candidates.values()), unresolvedExtractions=unresolved,
        receipts=[r for r in events if r['kind'] in {'REQUEST_FINISHED', 'REQUEST_FAILED'}])
