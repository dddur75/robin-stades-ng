"""Passive source-scoped personal picks; transport and grants live elsewhere."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from .connectors import canonical
from .forum_tipsters import _walk
from .public_formats import _Node, _Tree, decode_document
from .recurring import instant

SRO_HOST = "forum.stade-rennais-online.com"
SRO_TOPIC = "6368"


def _classes(node: _Node) -> set[str]:
    return set((node.attrs.get("class") or "").split())


def _content(node: _Node) -> str:
    if (
        node.tag
        in {
            "blockquote",
            "cite",
            "script",
            "style",
            "pre",
            "code",
            "noscript",
            "template",
            "del",
            "s",
            "strike",
            "svg",
            "head",
            "iframe",
        }
        or _classes(node) & {"postsignature", "signature", "quote", "hidden"}
        or "hidden" in node.attrs
        or node.attrs.get("aria-hidden") == "true"
        or "display:none" in re.sub(r"\s+", "", node.attrs.get("style") or "").lower()
    ):
        return ""
    if node.tag == "br":
        return "\n"
    value = "".join(_content(c) if isinstance(c, _Node) else c for c in node.children)
    return value + ("\n" if node.tag in {"p", "li", "div"} else "")


def extract_sro_posts(body: bytes, url: str, observed: datetime) -> list[dict[str, Any]]:
    p = urlsplit(url)
    query = parse_qs(p.query)
    if (
        p.scheme != "https"
        or p.hostname != SRO_HOST
        or p.username
        or p.password
        or p.port not in {None, 443}
        or p.path != "/viewtopic.php"
        or query.get("id") != [SRO_TOPIC]
        or set(query) - {"id", "p"}
        or p.fragment
        or observed.utcoffset() is None
        or len(body) > 2_000_000
    ):
        raise ValueError("unapproved source topic or observation")
    document = decode_document(body)
    if re.search(r"<!ENTITY|<!DOCTYPE[^>]*\[", document, re.I):
        raise ValueError("unsafe document declaration")
    tree = _Tree()
    tree.feed(document)
    result = []
    for node in _walk(tree.root):
        pid = node.attrs.get("id") or ""
        if node.tag != "div" or "blockpost" not in _classes(node) or not re.fullmatch(r"p\d+", pid):
            continue
        headers = [n for n in _walk(node) if n.tag == "h2"]
        dates = [
            m
            for h in headers
            for m in re.finditer(r"\b(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2}:\d{2})\b", _content(h))
        ]
        names = [
            a
            for n in _walk(node)
            if "postleft" in _classes(n)
            for dt in _walk(n)
            if dt.tag == "dt"
            for a in _walk(dt)
            if a.tag == "a"
        ]
        authors = {}
        for a in names:
            target = urlsplit(urljoin(url, a.attrs.get("href") or ""))
            ids = parse_qs(target.query).get("id", [])
            if (
                target.scheme == "https"
                and target.hostname == SRO_HOST
                and target.path == "/profile.php"
                and len(ids) == 1
                and ids[0].isdigit()
            ):
                authors["https://" + SRO_HOST + "/profile.php?id=" + str(int(ids[0]))] = _content(
                    a
                ).strip()
        contents = [
            n
            for n in _walk(node)
            if "postmsg" in _classes(n) and "postsignature" not in _classes(n)
        ]
        if len(dates) != 1 or len(authors) != 1 or len(contents) != 1:
            continue
        author_url, name = next(iter(authors.items()))
        if (
            not name
            or len(name) > 100
            or name.casefold() in {"invité", "guest", "anonyme", "anonymous"}
        ):
            continue
        m = dates[0]
        try:
            published = date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            continue
        if published > observed.date():
            continue
        text = _content(contents[0]).strip()
        if re.search(
            r"\b(résultats?|classement|bilan|historique|hypothèse|si je|aurais|devais|dernier|précédent|coupe)\b|"
            r"\bne\b.{0,100}\bpas\b|\b(?:grille|pronos?|pronostics?|choix)\s+(?:de|du|d['’])\b|"
            r"\b(?:selon|recopi[ée]|copi[ée]|d['’]après)\b",
            text,
            re.I,
        ):
            continue
        result.append(
            dict(
                sourceId="SRC_039",
                postId=pid,
                authorLabel=name,
                authorUrl=author_url,
                authorId=sha256(canonical(["SRC_039", author_url])).hexdigest(),
                sourceUrl="https://" + SRO_HOST + "/viewtopic.php?pid=" + pid[1:] + "#" + pid,
                publishedCivilDate=published.isoformat(),
                publishedLocalText=m[0],
                publicationTimezone=None,
                observedAt=observed.isoformat(),
                responseSha256=sha256(body).hexdigest(),
                text=text,
            )
        )
    return result


def qualify_sro_posts(
    posts: Sequence[dict[str, Any]], fixtures: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = {}
    for post in sorted(
        posts,
        key=lambda p: (p["publishedCivilDate"], p["publishedLocalText"][-8:], int(p["postId"][1:])),
    ):
        for fixture in fixtures:
            if (
                not fixture.get("publicationWindowStart")
                or not fixture["publicationWindowStart"]
                <= post["publishedCivilDate"]
                <= fixture["kickoff"][:10]
                or instant(post["observedAt"]) >= instant(fixture["kickoff"])
            ):
                continue
            home = "(?:" + "|".join(re.escape(x) for x in fixture["homeAliases"]) + ")"
            away = "(?:" + "|".join(re.escape(x) for x in fixture["awayAliases"]) + ")"
            pattern = (
                rf"(?:\d{{1,2}}:\d{{2}}\s+)?{home}\s+(\d{{1,2}})\s*[-:]\s*(\d{{1,2}})\s+{away}"
            )
            scores = {
                f"{int(m[1])}-{int(m[2])}"
                for line in post["text"].splitlines()
                if (m := re.fullmatch(pattern, line.strip(), re.I))
            }
            if len(scores) != 1:
                continue
            pick = {k: v for k, v in post.items() if k != "text"}
            pick.update(
                fixtureId=fixture["id"],
                fixtureLabel=fixture["label"],
                kickoff=fixture["kickoff"],
                market="correct_score",
                selection=next(iter(scores)),
                odds=None,
                identityCertified=False,
                attributionBasis="public_post_profile",
            )
            pick["id"] = sha256(
                canonical(["SRC_039", post["authorId"], fixture["id"], "correct_score"])
            ).hexdigest()
            result[pick["id"]] = pick
    return list(result.values())
