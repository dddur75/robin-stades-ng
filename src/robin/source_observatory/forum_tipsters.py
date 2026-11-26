"""Passive, source-scoped phpBB picks. No network, scheduling or identity claim."""
from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .connectors import canonical
from .public_formats import _Node, _Tree, check_declarations, decode_document
from .recurring import instant

TOPICS = {'SRC_038': ('forum.sco1919.com', '13259'),
          'SRC_058': ('legruppetto.fr', '24850')}


def _walk(node: _Node) -> Iterator[_Node]:
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _classes(node: _Node) -> set[str]:
    return set((node.attrs.get('class') or '').split())


def _text(node: _Node) -> str:
    if node.tag in {'blockquote', 'cite', 'script', 'style', 'code', 'pre', 'svg',
                    'noscript', 'iframe'} or _classes(node) & {'signature', 'quote', 'hidden'}:
        return ''
    if 'hidden' in node.attrs or node.attrs.get('aria-hidden') == 'true':
        return ''
    if 'display:none' in re.sub(r'\s+', '', node.attrs.get('style') or '').lower():
        return ''
    if node.tag == 'br':
        return '\n'
    return ''.join(_text(c) if isinstance(c, _Node) else c for c in node.children)


def extract_posts(body: bytes, url: str, source: str, observed: datetime) -> list[dict[str, Any]]:
    """Keep local post author, stripped body and immutable observation, in memory only."""
    p = urlsplit(url)
    host, topic = TOPICS[source]
    query = parse_qs(p.query)
    if (p.scheme not in {'http', 'https'} or p.hostname != host or p.username or p.password
            or p.port not in {None, 80, 443} or not p.path.endswith('/viewtopic.php')
            or query.get('t') != [topic] or set(query) - {'t', 'f', 'start', 'p'}):
        raise ValueError('unapproved public topic URL')
    if observed.utcoffset() is None or len(body) > 2_000_000:
        raise ValueError('explicit observation or bounded body required')
    document = decode_document(body)
    # HTMLParser never loads a DTD; allow only the exact legacy phpBB declaration.
    legacy = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">'
    check_declarations(document.replace(legacy, ""))
    tree = _Tree()
    tree.feed(document)
    tree.close()
    posts = []
    for node in _walk(tree.root):
        pid = node.attrs.get('id') or ''
        if node.tag != 'div' or not re.fullmatch(r'p\d+', pid):
            continue
        authors = [n for n in _walk(node) if n.tag == 'p' and 'author' in _classes(n)]
        contents = [n for n in _walk(node) if 'content' in _classes(n)]
        if len(authors) != 1 or len(contents) != 1:
            continue
        names = [n for n in _walk(authors[0]) if n.tag in {'a', 'span', 'strong'}
                 and (_classes(n) & {'username', 'username-coloured'}
                      or n.tag == 'a' and 'mode=viewprofile' in (n.attrs.get('href') or ''))]
        if len(names) != 1:
            continue
        name = ' '.join(_text(names[0]).split())
        if not name or len(name) > 100 or name.casefold() in {'anonymous', 'anonyme', 'invité', 'guest'}:
            continue
        civil = re.search(r'\b(\d{1,2})\s+(?:nov\.?|novembre)[,\s]+(\d{4})\b', _text(authors[0]), re.I)
        if civil is None:
            continue
        try:
            published_date = date(int(civil[2]), 11, int(civil[1]))
        except ValueError:
            continue
        if published_date > observed.date():
            continue
        text = _text(contents[0]).strip()
        # Scoreboards, quoted picks and results cannot be retroactively promoted.
        if re.search(r'\b(résultats?|classement|bilan|résumé|final score|full.time)\b', text, re.I):
            continue
        stable = urlunsplit((p.scheme, p.netloc, p.path, urlencode({'t': topic, 'p': pid[1:]}), pid))
        posts.append(dict(sourceId=source, postId=pid, authorLabel=name,
                          authorId='public:' + sha256(canonical([source, name])).hexdigest(),
                          sourceUrl=stable, observedAt=observed.astimezone(UTC).isoformat(),
                          publishedAt=None, publishedCivilDate=published_date.isoformat(), text=text, responseSha256=sha256(body).hexdigest()))
    return posts


def qualify_posts(posts: Sequence[dict[str, Any]], fixtures: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exact known aliases only; local observation strictly precedes verified kickoff."""
    result = []
    for post in posts:
        if re.search(r"\b(?:ne\b.{0,100}\bpas|dernier|précédent|hypothèse|si je|si on|aurais|devais|historique)\b", post['text'], re.I):
            continue
        matches: dict[str, list[tuple[dict[str, Any], str]]] = {}
        for fixture in fixtures:
            start = fixture.get('publicationWindowStart')
            if (not start or not start <= post['publishedCivilDate'] <= fixture['kickoff'][:10]
                    or instant(post['observedAt']) >= instant(fixture['kickoff'])):
                continue
            home = '|'.join(re.escape(a) for a in fixture['homeAliases'])
            away = '|'.join(re.escape(a) for a in fixture['awayAliases'])
            pattern = rf'(?<!\w)(?:{home})\s*[-–—]\s*(?:{away})(?!\w)\s*:?\s*(\d{{1,2}})\s*[-:/–]\s*(\d{{1,2}})(?!\d)'
            patterns = [pattern]
            if post['sourceId'] == 'SRC_038':
                patterns.extend([
                    rf'(?<!\w)(?:{home})(?!\w)\s+(\d{{1,2}})\s*[-:/–]\s*(\d{{1,2}})\s+(?:{away})(?!\w)',
                    rf'(?<!\w)(?:{home})(?!\w)\s+(\d{{1,2}})\s+(?:{away})(?!\w)\s+(\d{{1,2}})(?!\d)',
                ])
            for match in (m for pat in patterns for m in re.finditer(pat, post['text'], re.I)):
                start = post['text'].rfind('\n', 0, match.start()) + 1
                end = post['text'].find('\n', match.end())
                end = len(post['text']) if end < 0 else end
                prefix = post['text'][start:match.start()].strip()
                suffix = post['text'][match.end():end].strip()
                if prefix and not re.fullmatch(r"(?:MB\s*[-–]|mon prono(?:stic)?\s*:|je (?:joue|pronostique)\s*:?)", prefix, re.I):
                    continue
                if suffix and not (post['sourceId'] == 'SRC_038' and re.fullmatch(r"(?:\([^0-9<>]{1,60}\)|[A-Z]{2,4})", suffix)):
                    continue
                key = re.sub(r'\s+', ' ', match.group(0)).casefold()
                matches.setdefault(key, []).append((fixture, f'{int(match[1])}-{int(match[2])}'))
        by_fixture: dict[str, list[tuple[dict[str, Any], str]]] = {}
        for candidates in matches.values():
            if len({f['id'] for f, _ in candidates}) != 1:
                continue
            for fixture, score in candidates:
                by_fixture.setdefault(fixture['id'], []).append((fixture, score))
        for candidates in by_fixture.values():
            if len({score for _, score in candidates}) != 1:
                continue
            fixture, score = candidates[0]
            facts = {k: v for k, v in post.items() if k != 'text'}
            facts.update(fixtureId=fixture['id'], fixtureLabel=fixture['label'], kickoff=fixture['kickoff'],
                         market='correct_score', selection=score, odds=None,
                         attributionBasis='public_post_pseudonym', identityCertified=False)
            facts['id'] = sha256(canonical([post['sourceId'], post['postId'], fixture['id'], 'correct_score'])).hexdigest()
            result.append(facts)
    return list({p['id']: p for p in result}.values())
