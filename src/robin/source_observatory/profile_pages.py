"""Passive personal-profile diagnostics; native rows are never admitted here."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import Any
from urllib.parse import urljoin, urlsplit

from .public_formats import _Node, _Tree, check_declarations, decode_document

_SKIP = frozenset("script style head noscript template svg nav footer aside blockquote".split())


def _fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )


def _hidden(node: _Node) -> bool:
    style = re.sub(r"\s+", "", node.attrs.get("style") or "").casefold()
    return (
        "hidden" in node.attrs
        or node.attrs.get("aria-hidden") == "true"
        or "display:none" in style
        or "visibility:hidden" in style
    )


def _walk(node: _Node) -> Iterator[_Node]:
    if node.tag in _SKIP or _hidden(node):
        return
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _text(node: _Node) -> str:
    if node.tag in _SKIP or _hidden(node):
        return ""
    return " ".join(
        " ".join(_text(c) if isinstance(c, _Node) else c for c in node.children).split()
    )


def _all(node: _Node) -> Iterator[_Node]:
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _all(child)


def _personal_nodes(node: _Node, owner: str) -> Iterator[_Node]:
    marker = (node.attrs.get("class") or "") + " " + (node.attrs.get("id") or "")
    attributed = node.attrs.get("data-author") or node.attrs.get("data-tipster")
    if (
        node.tag in _SKIP
        or _hidden(node)
        or re.search(r"recommend|ranking|leaderboard|histor|comments|statistics", marker, re.I)
        or (attributed is not None and _fold(attributed) != owner)
    ):
        return
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _personal_nodes(child, owner)


def _identity(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return (
        (parsed.hostname or "").removeprefix("www.").casefold(),
        parsed.path.rstrip("/").casefold(),
    )


def project_profile_page(
    body: bytes, content_type: str, source_url: str, author: str
) -> dict[str, Any]:
    """Read a fixed public profile, preserving unknown attribution/chronology.

    Only visible native tables inside a unique explicitly identified owner scope
    are projected. This function performs no HTTP, JavaScript or admission.
    """
    if len(body) > 2_000_000 or not author.strip():
        raise ValueError("profile input bound")
    if content_type.split(";")[0].strip().lower() not in ("text/html", "application/xhtml+xml"):
        raise ValueError("profile MIME")
    decoded = decode_document(body, content_type)
    check_declarations(decoded)
    tree = _Tree()
    tree.feed(decoded)
    tree.close()
    all_nodes = list(_all(tree.root))
    for node in all_nodes:
        if node.tag == "link" and "canonical" in (node.attrs.get("rel") or "").split():
            if _identity(urljoin(source_url, node.attrs.get("href") or "")) != _identity(
                source_url
            ):
                raise ValueError("profile canonical mismatch")
    nodes = list(_walk(tree.root))
    headings = [n for n in nodes if n.tag in ("h1", "h2")]
    expected = _fold(author.strip())
    labels = {
        expected,
        "pronostics de " + expected,
        "tips by " + expected,
        "tipster " + expected,
        "pronostics " + expected,
    }
    owners = [n for n in headings if _fold(_text(n)).strip(" :") in labels]
    # Challenge evidence must be rendered markup, never a dormant JS string.
    title = " ".join(
        "".join(c for c in n.children if isinstance(c, str)) for n in all_nodes if n.tag == "title"
    )
    primary = title + " " + " ".join(_text(n) for n in headings if n.tag == "h1")
    if re.search(
        r"verify (?:you are|that you are) human|just a moment|verification humaine", _fold(primary)
    ) or any(n.attrs.get("id") in ("challenge-form", "cf-challenge-running") for n in nodes):
        raise ValueError("profile access challenge")
    result: dict[str, Any] = dict(
        status="OWNER_NOT_ESTABLISHED",
        ownerMatched=len(owners) == 1,
        rows=[],
        admittedChoices=0,
        publishedAt=None,
        sourceTimezone=None,
        headingCount=len(headings),
        visibleTables=sum(n.tag == "table" for n in nodes),
    )
    script_refs: list[str] = []
    for node in all_nodes:
        if node.tag != "script" or not node.attrs.get("src"):
            continue
        target = urljoin(source_url, node.attrs["src"])
        parsed = urlsplit(target)
        try:
            valid_port = parsed.port in (None, 443)
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.hostname == urlsplit(source_url).hostname
            and not parsed.username
            and not parsed.password
            and valid_port
            and not parsed.query
            and not parsed.fragment
            and len(script_refs) < 8
        ):
            script_refs.append(target)
    result["structure"] = dict(
        markers=[
            dict(
                tag=n.tag,
                id=(n.attrs.get("id") or "")[:100],
                **{"class": (n.attrs.get("class") or "")[:160]},
            )
            for n in nodes
            if re.search(
                r"profile|tipster|picks|predictions|bets|prono",
                (n.attrs.get("id") or "") + " " + (n.attrs.get("class") or ""),
                re.I,
            )
        ][:40],
        scripts=script_refs,
        inlineScriptCount=sum(n.tag == "script" and not n.attrs.get("src") for n in all_nodes),
    )
    if len(owners) != 1:
        return result
    parents = {id(c): n for n in all_nodes for c in n.children if isinstance(c, _Node)}
    scope = parents.get(id(owners[0]))
    while scope is not None:
        marker = (scope.attrs.get("id") or "") + " " + (scope.attrs.get("class") or "")
        if scope.tag in ("main", "article") or re.search(r"profile|tipster", marker, re.I):
            break
        scope = parents.get(id(scope))
    result["status"] = "PERSONAL_SCOPE_UNESTABLISHED"
    if scope is None:
        return result
    scoped = list(_personal_nodes(scope, expected))
    if any(n.attrs.get("aria-busy") == "true" for n in scoped):
        result["status"] = "PERSONAL_LOADING"
        return result
    rows: list[dict[str, Any]] = []
    for table in [n for n in scoped if n.tag == "table"][:6]:
        headers: list[str] = []
        for tr in (n for n in _personal_nodes(table, expected) if n.tag == "tr"):
            cells = [c for c in tr.children if isinstance(c, _Node) and c.tag in ("th", "td")]
            values = [_text(c) for c in cells]
            if any(c.tag == "th" for c in cells):
                headers = values
                continue
            normalized = " ".join(_fold(h) for h in headers)
            if (
                not headers
                or len(headers) != len(values)
                or len(set(headers)) != len(headers)
                or not re.search(r"match|rencontre|event|evenement", normalized)
                or not re.search(r"prono|pick|selection|apuesta", normalized)
            ):
                continue
            if len(rows) >= 10 or any(len(v) > 180 for v in values):
                continue
            fields = {
                h: v
                for h, v in zip(headers, values, strict=True)
                if re.search(
                    r"match|rencontre|event|evenement|date|heure|prono|pick|selection|cote|odds|apuesta",
                    _fold(h),
                )
            }
            rows.append(dict(fields=fields, attribution="PROFILE_SCOPE_ONLY_UNADMITTED"))
    result.update(status="NATIVE_ROWS_UNADMITTED" if rows else "NO_TYPED_PERSONAL_ROWS", rows=rows)
    return result
