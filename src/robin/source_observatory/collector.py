"""Public pre-match observations. Run once for due visits; never a background crawler."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from xml.etree import ElementTree  # nosec B405 - DOCTYPE/ENTITY refusés avant analyse

from .models import (
    Entity,
    Publication,
    PublicationVersion,
    Source,
    Visit,
    VisitReceipt,
    _instant,
    _url,
    instant_text,
    text_fingerprint,
)
from .store import AppendOnlyStore

USER_AGENT = 'RobinSourceObservatory/1.0'
MAX_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class PilotSource:
    source_id: str
    name: str
    url: str
    state: str
    access: str
    terms: str
    competitions: str
    audience: str


@dataclass(frozen=True, slots=True)
class Fixture:
    fixture_id: str
    kickoff: datetime
    evidence_url: str

    def __post_init__(self) -> None:
        if not self.fixture_id:
            raise ValueError('fixture id required')
        _instant(self.kickoff, 'kickoff')
        _url(self.evidence_url)


@dataclass(frozen=True, slots=True)
class PublicPost:
    url: str
    text: str
    announced_at: datetime | None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str


class HTTP(Protocol):
    def get(self, url: str) -> HttpResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class PublicHTTP:
    """Anonymous bounded GET: no cookies, netrc, login, proxy or redirect following."""

    def get(self, url: str) -> HttpResponse:
        _url(url)
        request = Request(url, headers={'User-Agent': USER_AGENT})
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=20) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError('response too large')
                return HttpResponse(response.status, body,
                                    response.headers.get('Content-Type', ''))
        except HTTPError as exc:
            return HttpResponse(exc.code, b'', '')


def parse_instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _instant(instant, 'explicit timestamp')
    return instant


def _announced(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_instant(value)
    except ValueError:
        try:
            instant = parsedate_to_datetime(value)
            _instant(instant, 'platform date')
            return instant
        except (ValueError, TypeError, OverflowError):
            return None


def load_sources(path: Path) -> tuple[PilotSource, ...]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        sources = tuple(PilotSource(row['source_id'], row['nom'], row['adresse'],
            row['etat_connecteur'], row['mode_acces'], row['cgu_connues'],
            row['competitions'], row['categorie_audience']) for row in csv.DictReader(stream)
            if row['etat_connecteur'] in ('a_construire', 'manuel'))
    if not sources or len({s.source_id for s in sources}) != len(sources):
        raise ValueError('unique authorized pilot sources required')
    for source in sources:
        _url(source.url)
    return tuple(sorted(sources, key=lambda s: s.source_id))


def build_plan(sources: Iterable[PilotSource], fixtures: Iterable[Fixture], *,
               starts_at: datetime, registry_sha256: str) -> dict[str, Any]:
    _instant(starts_at, 'plan start')
    sources, fixtures = tuple(sources), tuple(sorted(fixtures, key=lambda f: f.fixture_id))
    if (not fixtures or not sources or any(f.kickoff <= starts_at for f in fixtures)
            or len({f.fixture_id for f in fixtures}) != len(fixtures)
            or len({s.source_id for s in sources}) != len(sources)
            or any(s.state not in ('a_construire', 'manuel') for s in sources)
            or re.fullmatch('[0-9a-f]{64}', registry_sha256) is None):
        raise ValueError('invalid plan sources, fixtures or registry hash')
    instants = set()
    current, end = starts_at, max(f.kickoff for f in fixtures)
    while current < end:
        instants.add(current)
        current += timedelta(hours=6)
    instants.update(f.kickoff - timedelta(minutes=1) for f in fixtures)
    visits = []
    for instant in sorted(t for t in instants if t >= starts_at):
        for source in sorted(sources, key=lambda s: s.source_id):
            key = source.source_id + ':' + instant_text(instant)
            visits.append(dict(visit_id='visit:' + text_fingerprint(key),
                source_id=source.source_id, planned_at=instant_text(instant),
                fixture_ids=[f.fixture_id for f in fixtures if instant < f.kickoff]))
    return dict(schema_version='source-observatory-visit-plan-v1',
                registry_sha256=registry_sha256, starts_at=instant_text(starts_at),
                interval_hours=6, sources=[asdict(s) for s in sorted(sources,
                    key=lambda s: s.source_id)], fixtures=[dict(fixture_id=f.fixture_id,
                    kickoff=instant_text(f.kickoff), evidence_url=f.evidence_url) for f in fixtures],
                visits=visits)


def write_plan(path: Path, plan: dict[str, Any]) -> None:
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != encoded:
            raise ValueError('immutable plan already exists with different contents')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded)


def _fold(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                   if not unicodedata.combining(c))


def _endpoint(source: PilotSource) -> tuple[str | None, str | None]:
    if source.state == 'manuel':
        return None, 'manuel_sans_collecte_automatisee'
    # Robots are a separate gate: their Allow cannot override contractual denial.
    terms = _fold(source.terms.split('; robots.txt')[0])
    if 'inconnu' in terms:
        return None, 'cgu_inconnues'
    match = re.search(r'https?://[^\s)]+', source.access)
    feed = match.group(0) if match and ('rss' in source.access or 'atom' in source.access) else None
    youtube_feed = bool(feed and urlsplit(feed).hostname == 'www.youtube.com'
                        and urlsplit(feed).path == '/feeds/videos.xml'
                        and 'channel_id=' in urlsplit(feed).query)
    cleaned = re.sub(r"\b(?:pas (?:de\s+|d')|aucune?\s+|sans\s+)(?:clause\s+)?(?:d'|de\s+)?"
                     r"(?:interdiction|anti-scraping|restriction)\b", '', terms)
    if re.search(r'interdit|interdiction|prohib|forbidden|not permitted|anti-scraping|'
                 r'usage personnel|non[- ]commercial|uniquement.*navigation|usage prive', cleaned):
        return None, 'cgu_collecte_automatisee_refusee'
    # Only an explicitly permitted official feed can be used on YouTube.
    if 'youtube.com' in source.url:
        if youtube_feed and re.search(r'flux (atom public|rss public|officiels)', terms):
            return feed, None
        return None, 'cgu_interface_officielle_non_documentee'
    endpoint = feed or source.url
    _url(endpoint)
    if urlsplit(endpoint).hostname.removeprefix('www.') != urlsplit(source.url).hostname.removeprefix('www.'):  # type: ignore[union-attr]
        return None, 'cgu_hote_non_documente'
    return endpoint, None


def robots_policy(text: str, url: str) -> tuple[bool, float]:
    """Longest matching rule, Allow on ties, wildcards and end anchors included."""
    if '<' in text or '\x00' in text:
        return False, 0.0
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        key, value = (v.strip() for v in line.split(':', 1))
        key = key.lower()
        if key == 'user-agent':
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif agents and key in ('allow', 'disallow', 'crawl-delay', 'request-rate'):
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    ua = USER_AGENT.lower()
    def specificity(names: list[str]) -> int:
        return max((len(name.replace('*', '')) for name in names
                    if name and re.search(re.escape(name).replace(r'\*', '.*'), ua)), default=-1)
    best = max((specificity(a) for a, _ in groups), default=-1)
    parsed = urlsplit(url)
    target = unquote(parsed.path or '/') + ('?' + unquote(parsed.query) if parsed.query else '')
    matches = []
    delay = 0.0
    for names, directives in groups:
        if specificity(names) != best or best < 0:
            continue
        for key, value in directives:
            if key == 'crawl-delay':
                delay = max(delay, float(value))
            elif key == 'request-rate':
                count, seconds = value.split('/', 1)
                delay = max(delay, float(seconds) / float(count))
            elif value:
                anchored = value.endswith('$')
                pattern = re.escape(unquote(value[:-1] if anchored else value)).replace(r'\*', '.*')
                if re.match('^' + pattern + ('$' if anchored else ''), target):
                    matches.append((len(value.rstrip('$').replace('*', '')), key == 'allow'))
    if not 0 <= delay <= 60:
        raise ValueError('unsupported robots delay')
    return (max(matches)[1] if matches else True), delay


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


class _Articles(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.url = url
        self.posts: list[PublicPost] = []
        self.depth = 0
        self.skip = 0
        self.parts: list[str] = []
        self.identifier: str | None = None
        self.post_url: str | None = None
        self.date: datetime | None = None
        self.time_candidate: tuple[datetime | None, bool, int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if not self.depth and (tag == 'article' or (tag == 'div' and values.get('id')
                and 'post' in (values.get('class') or '').split())):
            self.depth = 1
            self.identifier, self.post_url, self.date = values.get('id'), None, None
            self.time_candidate = None
            self.parts = []
            return
        if self.depth:
            if tag not in ('br', 'img', 'meta', 'link', 'input', 'hr', 'source', 'wbr'):
                self.depth += 1
            if tag in ('script', 'style'):
                self.skip += 1
            if tag == 'time' and self.date is None:
                explicit = ('datePublished' in (values.get('itemprop') or '').split()
                            or 'pubdate' in values
                            or bool({'published', 'entry-date'} & set(
                                (values.get('class') or '').split())))
                self.time_candidate = (_announced(values.get('datetime')), explicit, len(self.parts))
            if tag == 'a' and self.post_url is None and 'bookmark' in (values.get('rel') or '').split():
                href = values.get('href')
                target = urljoin(self.url, href) if href else None
                if target and target.rstrip('#') != self.url.rstrip('#'):
                    self.post_url = target

    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            if tag == 'time' and self.time_candidate is not None:
                candidate, explicit, start = self.time_candidate
                label = _fold(''.join(self.parts[start:]))
                if self.date is None and (explicit or re.search(
                        r'\b(?:publiee?|publication|published|posted)\b', label)):
                    self.date = candidate
                self.time_candidate = None
            if tag in ('script', 'style'):
                self.skip = max(0, self.skip - 1)
            if tag not in ('br', 'img', 'meta', 'link', 'input', 'hr', 'source', 'wbr'):
                self.depth -= 1
            if not self.depth:
                if not self.post_url and not self.identifier:
                    raise ValueError('publication without public permalink')
                target = self.post_url or (self.url + '#' + self.identifier
                                           if self.identifier else self.url)
                self.posts.append(PublicPost(target, ''.join(self.parts), self.date))

    def handle_data(self, data: str) -> None:
        if self.depth and not self.skip:
            self.parts.append(data)


def parse_publications(body: bytes, url: str) -> tuple[PublicPost, ...]:
    declarations = re.sub(br'<!doctype\s+html\s*>', b'', body, flags=re.IGNORECASE)
    if (len(body) > MAX_BYTES or b'<!DOCTYPE' in declarations.upper()
            or b'<!ENTITY' in declarations.upper()):
        raise ValueError('unsupported or oversized document')
    posts = []
    try:
        root = ElementTree.fromstring(body)  # nosec B314 - entrée bornée sans DOCTYPE/ENTITY
    except ElementTree.ParseError:
        root = None
    if root is not None and _local(root.tag) in ('rss', 'feed', 'RDF'):
        for entry in root.iter():
            if _local(entry.tag) not in ('item', 'entry'):
                continue
            fields = {_local(e.tag): ''.join(e.itertext()) for e in entry}
            if not fields.get('description', '').strip():
                fields['description'] = next((''.join(e.itertext()) for e in entry.iter()
                    if _local(e.tag) == 'description' and ''.join(e.itertext()).strip()), '')
            links = [e.attrib['href'] for e in entry if _local(e.tag) == 'link'
                     and 'href' in e.attrib and e.attrib.get('rel', 'alternate') == 'alternate']
            link = links[0] if links else fields.get('link')
            if not link:
                raise ValueError('publication without public permalink')
            text = next((fields[key] for key in ('encoded', 'content', 'description', 'title')
                         if fields.get(key, '').strip()), '')
            title = fields.get('title', '').strip()
            if title and title not in text:
                text = title + '\n' + text
            announced = _announced(fields.get('published') or fields.get('pubDate')
                                   or fields.get('date'))
            posts.append(PublicPost(urljoin(url, link.strip()), text, announced))
    else:
        parser = _Articles(url)
        parser.feed(body.decode('utf-8-sig'))
        if parser.depth or not parser.posts:
            raise ValueError('public publication format not supported')
        posts = parser.posts
    if len({p.url for p in posts}) != len(posts):
        raise ValueError('duplicate or unstable publication permalink')
    for post in posts:
        _url(post.url)
        if not post.text.strip():
            raise ValueError('publication text absent')
    return tuple(posts)


def _payload_root() -> Path:
    value = os.environ.get('SOURCE_OBSERVATORY_RAW_DIR')
    if not value:
        raise ValueError('SOURCE_OBSERVATORY_RAW_DIR required outside Git')
    root = Path(value).expanduser().resolve()
    repo = Path(__file__).resolve().parents[3]
    if root.is_relative_to(repo) or any((p / '.git').exists() for p in (root, *root.parents)):
        raise ValueError('raw payload directory must be outside every Git worktree')
    return root


def _prepare_post(entities: Iterable[Entity], source: PilotSource, post: PublicPost,
                  observed: datetime, raw_root: Path) -> tuple[str, tuple[Entity, ...]]:
    digest = text_fingerprint(post.text)
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / (digest + '.txt')
    if target.exists():
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('external payload integrity mismatch')
    else:
        with target.open('xb') as stream:
            stream.write(post.text.encode('utf-8'))
    pub_id = 'publication:' + text_fingerprint(source.source_id + ':' + post.url)
    entities = tuple(entities)
    pending: list[Entity] = []
    versions = [e for e in entities if isinstance(e, PublicationVersion)
                and e.publication_id == pub_id]
    if not any(isinstance(e, Publication) and e.publication_id == pub_id for e in entities):
        pending.append(Publication(pub_id, source.source_id, post.url))
    previous = versions[-1] if versions else None
    if previous is None or previous.text_sha256 != digest:
        version_id = 'version:' + text_fingerprint(pub_id + ':' + digest + ':' + instant_text(observed))
        pending.append(PublicationVersion(version_id, pub_id, digest, post.announced_at,
            previous.first_observed_by_robin_at if previous else observed,
            observed if previous else None, observed,
            previous.version_id if previous else None))
    return pub_id, tuple(pending)


def _summary(plan: dict[str, Any], store: AppendOnlyStore, dry_run: bool) -> dict[str, Any]:
    completed = {e.visit_id: e for e in store.entities() if isinstance(e, VisitReceipt)}
    by_source: dict[str, Any] = {}
    for source in plan['sources']:
        visits = [v for v in plan['visits'] if v['source_id'] == source['source_id']]
        successes = sum(v['visit_id'] in completed and completed[v['visit_id']].status == 'ok'
                        for v in visits)
        by_source[source['source_id']] = dict(planned=len(visits), succeeded=successes,
                                             coverage=str(Decimal(successes) / len(visits)))
    succeeded = sum(s['succeeded'] for s in by_source.values())
    return dict(dry_run=dry_run, planned=len(plan['visits']), succeeded=succeeded,
                coverage=str(Decimal(succeeded) / len(plan['visits'])), by_source=by_source)


def collect(plan: dict[str, Any], sources: Iterable[PilotSource], store: AppendOnlyStore, *,
            http: HTTP | None = None, clock: Callable[[], datetime] | None = None,
            sleep: Callable[[float], None] = time.sleep, dry_run: bool = False) -> dict[str, Any]:
    sources = tuple(sources)
    fixtures = tuple(Fixture(f['fixture_id'], parse_instant(f['kickoff']), f['evidence_url'])
                     for f in plan['fixtures'])
    expected = build_plan(sources, fixtures, starts_at=parse_instant(plan['starts_at']),
                          registry_sha256=plan['registry_sha256'])
    if expected != plan:
        raise ValueError('plan changed: deterministic plan required')
    if dry_run:
        return _summary(plan, store, True)
    raw_root = _payload_root()
    http, clock = http or PublicHTTP(), clock or (lambda: datetime.now(UTC))
    by_id = {s.source_id: s for s in sources}
    existing = store.entities()
    source_records = {e.source_id: e for e in existing if isinstance(e, Source)}
    for source in sources:
        record = Source(source.source_id, source.name, source.url)
        if source.source_id not in source_records:
            store.append(record)
        elif source_records[source.source_id] != record:
            raise ValueError('source metadata changed; new source identity required')
    visits = {e.visit_id: e for e in existing if isinstance(e, Visit)}
    for visit in plan['visits']:
        record_visit = Visit(visit['visit_id'], visit['source_id'],
                             parse_instant(visit['planned_at']), None, False)
        if record_visit.visit_id not in visits:
            store.append(record_visit)
        elif visits[record_visit.visit_id] != record_visit:
            raise ValueError('planned visit metadata mismatch')
    completed = {e.visit_id for e in existing if isinstance(e, VisitReceipt)}
    host_delays: dict[str, float] = {}
    requested_hosts: set[str] = set()

    def get_public(url: str) -> HttpResponse:
        host = urlsplit(url).netloc
        delay = host_delays.get(host, 0.0)
        if host in requested_hosts and delay:
            sleep(delay)
        requested_hosts.add(host)
        return http.get(url)

    def utc_now() -> datetime:
        value = clock()
        _instant(value, 'visit UTC timezone')
        return value.astimezone(UTC)

    for visit in plan['visits']:
        planned, observed = parse_instant(visit['planned_at']), utc_now()
        if planned > observed or visit['visit_id'] in completed:
            continue
        source = by_id[visit['source_id']]
        endpoint, reason = _endpoint(source)
        status: Any = 'echec'
        publication_ids: tuple[str, ...] = ()
        active = [f for f in fixtures if f.fixture_id in visit['fixture_ids']
                  and observed < f.kickoff]
        if not active:
            reason = 'hors_pre_match'
        elif observed - planned > timedelta(minutes=15):
            reason = 'visite_planifiee_manquee'
        elif endpoint is not None:
            try:
                parsed = urlsplit(endpoint)
                robots = get_public(f'{parsed.scheme}://{parsed.netloc}/robots.txt')
                if robots.status in (404, 410):
                    allowed, delay = True, 0.0
                elif robots.status == 200:
                    allowed, delay = robots_policy(robots.body.decode('utf-8-sig'), endpoint)
                else:
                    allowed, delay = False, 0.0
                host_delays[parsed.netloc] = delay
                if not allowed:
                    status, reason = 'bloque_robots', 'robots_refus_ou_indisponible'
                else:
                    response = get_public(endpoint)
                    # Observation occurs when content is actually available, after any delay.
                    observed = utc_now()
                    if response.status != 200:
                        reason = f'http_{response.status}'
                    elif not any(observed < f.kickoff for f in active):
                        reason = 'hors_pre_match'
                    else:
                        posts = parse_publications(response.body, endpoint)
                        # A global feed may mix leagues. Keep explicit Ligue 1 posts only.
                        selected = [p for p in posts if re.search(r'ligue[ -]?1|\bl1\b',
                                    _fold(p.text + ' ' + p.url))]
                        pending: list[Entity] = []
                        ids = []
                        existing_posts = store.entities()
                        for post in selected:
                            pub_id, records = _prepare_post((*existing_posts, *pending), source,
                                                           post, observed, raw_root)
                            ids.append(pub_id)
                            pending.extend(records)
                        receipt = VisitReceipt('receipt:' + visit['visit_id'], visit['visit_id'],
                                               observed, 'ok', tuple(ids), None)
                        store.append_batch((*pending, receipt))
                        continue
                        status, reason = 'ok', None
            except (OSError, ValueError, ElementTree.ParseError):
                reason = 'lecture_publique_echouee'
        store.append(VisitReceipt('receipt:' + visit['visit_id'], visit['visit_id'], observed,
                                   status, publication_ids, reason))
    return _summary(plan, store, False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=Path('data/source_observatory/pilot_sources.csv'))
    parser.add_argument('--plan', type=Path, default=Path('data/source_observatory/visit_plan_20261031_v2.json'))
    parser.add_argument('--journal', type=Path, default=Path('data/source_observatory/collection.jsonl'))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    sources = load_sources(args.sources)
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if plan['registry_sha256'] != sha256(args.sources.read_bytes()).hexdigest():
        raise ValueError('registry hash changed since plan creation')
    result = collect(plan, sources, AppendOnlyStore(args.journal), dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
