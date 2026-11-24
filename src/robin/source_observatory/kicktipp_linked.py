"""Passive native-reference joins; no guessed teams, timezone, or source admission."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from .profile_pages import _all, _fold, _text, _walk
from .public_formats import _Node, _Tree, check_declarations, decode_document


def _references(node: _Node, base: str, *, author: bool = False) -> list[str]:
    result = []
    for child in _walk(node):
        if child.tag != "a" or not child.attrs.get("href"):
            continue
        url = urljoin(base, child.attrs["href"])
        parsed = urlsplit(url)
        # Source evidence retains this exact route/key set, not the key values or semantics.
        if parsed.path == "/the-predictor/tippuebersicht/spiel":
            native_query = parse_qs(parsed.query, keep_blank_values=True)
            if (
                not author
                and parsed.scheme == "https"
                and parsed.netloc == "www.kicktipp.fr"
                and not parsed.fragment
                and len(parsed.query) <= 256
                and set(native_query) == {"spieltagIndex", "tippsaisonId", "tippspielId"}
                and all(
                    len(values) == 1 and re.fullmatch(r"[0-9]{1,15}", values[0]) is not None
                    for values in native_query.values()
                )
            ):
                result.append(url)
            continue
        query = parse_qs(parsed.query)
        keys = ("rankingTeilnehmerId",) if author else ("spiel", "spielIndex", "spielId")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "www.kicktipp.fr"
            or not parsed.path.startswith("/the-predictor/")
            or any(
                k
                not in {
                    "rankingTeilnehmerId",
                    "spieltagIndex",
                    "tippsaisonId",
                    "ereignisIndex",
                    "spiel",
                    "spielIndex",
                    "spielId",
                }
                or len(v) != 1
                or re.fullmatch(r"[0-9]{1,15}", v[0]) is None
                for k, v in query.items()
            )
        ):
            continue
        if author and not parsed.path.endswith("/tippuebersicht/tipper"):
            continue
        if (not author and parsed.path.endswith("/spielinfo") and query) or any(
            k in query and len(query[k]) == 1 and re.fullmatch(r"[0-9]{1,15}", query[k][0])
            for k in keys
        ):
            result.append(url)
    return list(dict.fromkeys(result))[:4]


def _cells(row: _Node) -> list[_Node]:
    return [c for c in row.children if isinstance(c, _Node) and c.tag in ("th", "td")]


def project_linked_overview(body: bytes, content_type: str, source_url: str) -> dict[str, Any]:
    if (
        source_url != "https://www.kicktipp.fr/the-predictor/tableau-pronostics"
        or len(body) > 2_000_000
        or content_type.split(";")[0].strip().lower() not in ("text/html", "application/xhtml+xml")
    ):
        raise ValueError("exact passive Kicktipp scope/MIME/bound")
    text = decode_document(body, content_type)
    check_declarations(text)
    tree = _Tree()
    tree.feed(text)
    tree.close()
    nodes = list(_walk(tree.root))
    headings = " ".join(_text(n) for n in nodes if n.tag == "h1") + " ".join(
        "".join(c for c in n.children if isinstance(c, str))
        for n in _all(tree.root)
        if n.tag == "title"
    )
    if re.search(r"just a moment|verify you are human|access denied", headings, re.I) or any(
        n.attrs.get("id") in ("challenge-form", "cf-challenge-running") for n in nodes
    ):
        raise ValueError("rendered Kicktipp challenge")
    declarations: dict[str, list[dict[str, Any]]] = {}
    unbound_declarations = []
    schedule_count = 0
    for table in [n for n in nodes if n.tag == "table" and n.attrs.get("id") == "spielplanSpiele"][
        :1
    ]:
        headers = []
        for row in (n for n in _walk(table) if n.tag == "tr"):
            cells = _cells(row)
            labels = [_fold(_text(c)) for c in cells]
            if "date" in labels and "a domicile" in labels:
                headers = labels
                continue
            if not headers or len(cells) != len(headers) or "a l'exterieur" not in headers:
                continue
            schedule_count += 1
            if schedule_count > 20:
                continue
            refs = _references(row, source_url)
            mapped = dict(zip(headers, [_text(c)[:120] for c in cells], strict=True))
            if len(refs) == 1:
                declarations.setdefault(refs[0], []).append(
                    dict(
                        nativeFixtureRef=refs[0],
                        nativeDate=mapped["date"],
                        nativeHome=mapped["a domicile"],
                        nativeAway=mapped["a l'exterieur"],
                        nativeResult=mapped.get("resultat"),
                        sourceTimezone=None,
                    )
                )
            else:
                unbound_declarations.append(
                    dict(
                        nativeRowId=(row.attrs.get("id") or "")[:80],
                        nativeDate=mapped["date"],
                        nativeHome=mapped["a domicile"],
                        nativeAway=mapped["a l'exterieur"],
                        nativeResult=mapped.get("resultat"),
                        sourceTimezone=None,
                    )
                )
    participants: list[dict[str, Any]] = []
    header_diagnostics: list[dict[str, Any]] = []
    unbound_headers = 0
    for table in [n for n in nodes if n.tag == "table" and n.attrs.get("id") == "ranking"][:1]:
        author_column: int | None = None
        count = 0
        bound: dict[int, dict[str, Any]] = {}
        for row in (n for n in _walk(table) if n.tag == "tr"):
            cells = _cells(row)
            values = [_text(c) for c in cells]
            names = [_fold(v) for v in values]
            if any(
                n in ("nom", "name", "teilnehmer", "joueur") and cells[i].tag == "th"
                for i, n in enumerate(names)
            ):
                bound = {}
                count = len(cells)
                author_column = next(
                    i for i, n in enumerate(names) if n in ("nom", "name", "teilnehmer", "joueur")
                )
                for index, cell in enumerate(cells):
                    refs = _references(cell, source_url)
                    matches = [
                        declarations[r][0] for r in refs if len(declarations.get(r, [])) == 1
                    ]
                    if len(refs) == len(matches) == 1:
                        bound[index] = matches[0]
                    elif index > author_column and values[index] and len(header_diagnostics) < 12:
                        unbound_headers += 1
                    if len(header_diagnostics) < 12:
                        header_diagnostics.append(
                            dict(
                                label=values[index][:120],
                                nativeGameLinks=refs,
                                bound=index in bound,
                            )
                        )
                continue
            if author_column is None or len(cells) != count or len(participants) >= 3:
                continue
            label = values[author_column]
            if not 0 < len(label) <= 80:
                continue
            native = [
                dict(**fixture, nativeSelection=values[i])
                for i, fixture in sorted(
                    bound.items(),
                    key=lambda item: bool(
                        re.fullmatch(r"\d{1,2}\s*[:-]\s*\d{1,2}", item[1].get("nativeResult") or "")
                    ),
                )[:3]
                if re.fullmatch(r"\d{1,2}\s*[:-]\s*\d{1,2}", values[i])
            ]
            if native:
                authors = _references(cells[author_column], source_url, author=True)
                participants.append(
                    dict(
                        pseudonym=label,
                        nativeAuthorRef=authors[0] if len(authors) == 1 else None,
                        cells=native,
                    )
                )
    return dict(
        status="NATIVE_REFERENCE_CELLS_UNADMITTED"
        if participants
        else "NO_BOUND_PERSONAL_SCORE_CELLS",
        participants=participants,
        fixtureDeclarations=[d[0] for d in declarations.values() if len(d) == 1],
        unboundFixtureDeclarations=unbound_declarations,
        omittedScheduleRows=max(0, schedule_count - 20),
        headerDiagnostics=header_diagnostics,
        unboundHeaderCount=unbound_headers,
        admittedChoices=0,
        canonicalKickoffsEstablished=False,
        sourceTimezone=None,
        columnSelectionPolicy="Prefer source schedule rows without a numeric displayed result; this does not prove that the event is future.",
        publishedAt=None,
        limitation="Exact native game href joins only. Source abbreviations, ranking points, masked cells and missing author references do not establish an admissible prediction.",
    )
