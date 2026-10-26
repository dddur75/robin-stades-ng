"""Bounded, passive extraction of public HTML publication formats."""

from __future__ import annotations

import codecs
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

from .models import _url

_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_SKIP = frozenset('script style noscript template nav header footer aside form iframe svg '
                  'button select textarea dialog'.split())
_PRIVATE = re.compile(r'(?:^|\s)(?:author|username|postprofile|avatar|signature|comment|'
                      r'comments|commentauthor|user-info|profile)(?:$|\s|[-_])', re.I)
_DATE = re.compile(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/.]\d{1,2}[/.]\d{4}|'
                   r'\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|'
                   r'septembre|octobre|novembre|décembre)\s+\d{4})\b', re.I)
DateParser = Callable[[str | None], datetime | None]
ParsedPost = tuple[str, str, datetime | None]


def decode_document(body: bytes, content_type: str = '') -> str:
    """BOM wins, then HTTP charset, HTML meta/XML encoding, UTF-8, Windows-1252."""
    for marker, encoding in ((codecs.BOM_UTF32_LE, 'utf-32'),
                             (codecs.BOM_UTF32_BE, 'utf-32'),
                             (codecs.BOM_UTF8, 'utf-8-sig'),
                             (codecs.BOM_UTF16_LE, 'utf-16'),
                             (codecs.BOM_UTF16_BE, 'utf-16')):
        if body.startswith(marker):
            return body.decode(encoding)
    # Also detect XML's BOM-less UTF-16/32 signatures before checking declarations.
    for marker, encoding in ((b'\x00\x00\x00<', 'utf-32-be'),
                             (b'<\x00\x00\x00', 'utf-32-le'),
                             (b'\x00<\x00?', 'utf-16-be'), (b'<\x00?\x00', 'utf-16-le')):
        if body.startswith(marker):
            return body.decode(encoding)
    declared = re.search(r'charset\s*=\s*[\"\']?([\w.-]+)', content_type, re.I)
    if not declared:
        head = body[:8192].decode('ascii', errors='ignore')
        declared = re.search(r'<meta\b[^>]*charset\s*=\s*[\"\']?([\w.-]+)|'
                             r'<\?xml\b[^>]*encoding\s*=\s*[\"\']([\w.-]+)', head, re.I)
    if declared:
        encoding = next(v for v in declared.groups() if v)
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeError):
            raise ValueError('unsupported or invalid declared charset') from None
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('windows-1252')


def check_declarations(text: str) -> None:
    # Keep the existing inert HTML5 exception; no PUBLIC/SYSTEM/internal DTDs.
    declarations = re.sub(r'<!doctype\s+html\s*>', '', text, flags=re.I)
    if re.search(r'<!\s*(?:doctype|entity)\b', declarations, re.I) or '\x00' in text:
        raise ValueError('unsupported or oversized document')


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)


def _excluded(node: _Node) -> bool:
    a = node.attrs
    label = ' '.join((a.get('class') or '', a.get('id') or '', a.get('itemprop') or '',
                      a.get('rel') or ''))
    style = re.sub(r'\s+', '', (a.get('style') or '').lower())
    href = (a.get('href') or '').lower()
    private_link = node.tag == 'a' and (href.startswith(('mailto:', 'tel:'))
                    or bool(re.search(r'viewprofile|/(?:users?|members?|profiles?)/', href)))
    return (node.tag in _SKIP or 'hidden' in a or a.get('aria-hidden') == 'true'
            or bool(_PRIVATE.search(label)) or 'display:none' in style
            or 'visibility:hidden' in style or private_link)


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node('document')
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.rsplit(':', 1)[-1]
        self.count += 1
        if self.count > 40_000 or len(self.stack) > 128:
            raise ValueError('unsupported document complexity')
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.rsplit(':', 1)[-1] not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.rsplit(':', 1)[-1]
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _walk(node: _Node, *, metadata: bool = False) -> Iterator[_Node]:
    if _excluded(node) and not (metadata and node.tag == 'script'
            and (node.attrs.get('type') or '').lower() == 'application/ld+json'):
        return
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child, metadata=metadata)


def _text(node: _Node) -> str:
    if _excluded(node) or node.tag in ('head', 'meta', 'link'):
        return ''
    return ' '.join(' '.join(_text(c) if isinstance(c, _Node) else c
                             for c in node.children).split())


def clean_text(text: str) -> str:
    tree = _Tree()
    tree.feed(text)
    tree.close()
    return _text(tree.root)


def _target(base: str, href: str | None) -> str | None:
    if not href:
        return None
    target = urljoin(base, href.strip())
    try:
        _url(target)
        a, b = urlsplit(base), urlsplit(target)
        if (a.hostname or '').removeprefix('www.') != (b.hostname or '').removeprefix('www.'):
            return None
        if a.port != b.port:
            return None
    except ValueError:
        return None
    return target


def _title(node: _Node) -> str:
    for child in _walk(node):
        if child.tag in ('h1', 'h2', 'h3', 'h4') and _text(child):
            return _text(child)
    for child in _walk(node):
        if child.tag == 'a' and _text(child):
            return _text(child)
    return ''


def _article_link(node: _Node, url: str) -> str | None:
    nodes = list(_walk(node))
    links = [n for n in nodes if n.tag == 'a']
    preferred = [n for n in links if 'bookmark' in (n.attrs.get('rel') or '').split()]
    for n in nodes:
        if n.tag in ('h1', 'h2', 'h3', 'h4'):
            preferred.extend(c for c in _walk(n) if c.tag == 'a')
    preferred.extend(n for n in links if re.search('title|headline', n.attrs.get('class') or ''))
    preferred.extend(n for n in links if len(_text(n)) >= 8)
    for link in preferred:
        target = _target(url, link.attrs.get('href'))
        if target and target.rstrip('#') != url.rstrip('#'):
            return target
    return None


def _date_evidence(value: str, parse_date: DateParser) -> bool:
    if parse_date(value) is not None:
        return True
    try:
        # Naive or day-only ISO dates are evidence, never announced timestamps.
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _date(node: _Node, parse_date: DateParser) -> tuple[bool, datetime | None]:
    for n in _walk(node):
        a, label = n.attrs, _text(n).lower()
        prop = (a.get('itemprop') or '').lower()
        if prop == 'datemodified' or re.search(r'kickoff|coup d.envoi|match starts', label):
            continue
        value = a.get('datetime') if n.tag == 'time' else None
        if prop == 'datepublished':
            value = a.get('content') or value or label
        if value and _date_evidence(value, parse_date):
            # A fixture's date is not a platform publication timestamp.
            marker = ' '.join((a.get('class') or '', a.get('itemprop') or ''))
            if (re.search(r'match|kickoff|event|startDate', marker, re.I)
                    or re.fullmatch(r'(?:ce soir\s+)?\d{1,2}:\d{2}', label)):
                return True, None
            return True, parse_date(value)
        marker = ' '.join((a.get('class') or '', prop))
        if re.search('date|published|posted', marker, re.I) and _DATE.search(label):
            return True, None
    # A labelled publication date is evidence, but never an imputed timestamp.
    label = _text(node)
    if re.search(r'publi[ée]|published|posted', label, re.I) and _DATE.search(label):
        return True, None
    return False, None


def _anchor(url: str, identifier: str | None, title: str) -> str:
    fragment = (quote(identifier, safe='-_:.') if identifier else
                'publication-' + sha256(title.encode('utf-8')).hexdigest()[:24])
    return url.split('#', 1)[0] + '#' + fragment


def _json_posts(data: object, url: str, parse_date: DateParser) -> list[ParsedPost]:
    pending = [data]
    posts = []
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(reversed(value))
        elif isinstance(value, dict):
            kind = value.get('@type', [])
            kinds = [kind] if isinstance(kind, str) else kind
            if not isinstance(kinds, list):
                continue
            if set(str(k).rsplit('/', 1)[-1] for k in kinds) & {'Article', 'NewsArticle', 'BlogPosting'}:
                if value.get('isAccessibleForFree') in (False, 'false'):
                    continue
                title = value.get('headline') or value.get('name')
                body = value.get('articleBody') or value.get('description') or ''
                if not isinstance(title, str) or not title.strip() or not isinstance(body, str):
                    continue
                link = value.get('url') or value.get('mainEntityOfPage')
                if isinstance(link, dict):
                    link = link.get('@id')
                target = _target(url, link) if isinstance(link, str) else None
                date = value.get('datePublished')
                if not target and not (isinstance(date, str) and _date_evidence(date, parse_date)):
                    continue
                text = clean_text(title + ' ' + body)
                posts.append((target or _anchor(url, None, clean_text(title)), text,
                              parse_date(date) if isinstance(date, str) else None))
            else:
                # Only schema containers; never traverse authors, comments or arbitrary app state.
                for key in ('@graph', 'itemListElement', 'item'):
                    if key in value:
                        pending.append(value[key])
    return posts


def html_publications(text: str, url: str, parse_date: DateParser) -> list[ParsedPost]:
    tree = _Tree()
    tree.feed(text)
    tree.close()
    nodes = list(_walk(tree.root, metadata=True))
    metadata: list[str | None] = []
    structured = []
    for n in nodes:
        a = n.attrs
        if n.tag == 'link' and 'canonical' in (a.get('rel') or '').split():
            metadata.insert(0, _target(url, a.get('href')))
        if n.tag == 'meta' and a.get('property') == 'og:url':
            metadata.append(_target(url, a.get('content')))
        if n.tag == 'script' and (a.get('type') or '').lower() == 'application/ld+json':
            try:
                data = json.loads(''.join(c for c in n.children if isinstance(c, str)))
                structured.extend(_json_posts(data, url, parse_date))
            except (ValueError, RecursionError):
                continue
    canonical = next((v for v in metadata if v), None)
    articles = [n for n in nodes if n.tag == 'article' or (n.tag == 'div'
                and n.attrs.get('id') and 'post' in (n.attrs.get('class') or '').split())]
    posts: list[ParsedPost] = []
    consumed: set[int] = set()
    for n in articles:
        title = _title(n)
        dated, announced = _date(n, parse_date)
        target = _article_link(n, url)
        identifier = n.attrs.get('id')
        if not target and len(articles) == 1 and canonical:
            target = canonical
        if not target and identifier:
            target = _anchor(url, identifier, title)
        if not target and dated and title:
            target = canonical if len(articles) == 1 and canonical else _anchor(url, None, title)
        if not target:
            raise ValueError('publication without public permalink')
        text_body = _text(n)
        if text_body:
            posts.append((target, text_body, announced))
        consumed.update(id(c) for c in _walk(n))
    # Select smallest dated card containing a title and a same-domain article link.
    cards: list[ParsedPost] = []
    for n in reversed(nodes):
        if id(n) in consumed or n.tag not in ('div', 'li', 'section', 'a', 'tr'):
            continue
        if any(id(c) in consumed for c in _walk(n)):
            continue
        title, (dated, announced) = _title(n), _date(n, parse_date)
        target = _article_link(n, url)
        if title and dated and target:
            cards.append((target, _text(n), announced))
            consumed.update(id(c) for c in _walk(n))
    known = {p[0] for p in posts}
    unique_cards: dict[str, ParsedPost] = {}
    for p in reversed(cards):
        if p[0] not in known:
            previous = unique_cards.get(p[0])
            if previous is None:
                unique_cards[p[0]] = p
            elif previous[2] != p[2]:
                unique_cards[p[0]] = (previous[0], previous[1], None)
    posts.extend(unique_cards.values())
    if not posts and not structured:
        mains = [n for n in nodes if n.tag == 'main']
        for n in mains or [tree.root]:
            headings = [h for h in _walk(n) if h.tag == 'h1']
            dated, announced = _date(n, parse_date)
            if len(headings) == 1 and dated and re.search(
                    r'pronostic|prediction|betting tip', _text(headings[0]), re.I):
                title = _text(headings[0])
                posts.append((canonical or _anchor(url, None, title), _text(n), announced))
    # HTML and JSON-LD often describe the same publication. Prefer visible full text.
    known = {p[0] for p in posts}
    for p in structured:
        if p[0] not in known:
            posts.append(p)
            known.add(p[0])
    if not posts:
        raise ValueError('public publication format not supported')
    return posts
