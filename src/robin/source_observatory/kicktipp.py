"""Bounded visible-score diagnostics; a contest rule is not source admission."""

from __future__ import annotations

import re
from typing import Any

from .profile_pages import _all, _fold, _text, _walk
from .public_formats import _Node, _Tree, check_declarations, decode_document


def project_overview(body: bytes, content_type: str) -> dict[str, Any]:
    if len(body) > 2_000_000 or content_type.split(";")[0].strip().lower() not in (
        "text/html",
        "application/xhtml+xml",
    ):
        raise ValueError("overview MIME/bound")
    decoded = decode_document(body, content_type)
    check_declarations(decoded)
    tree = _Tree()
    tree.feed(decoded)
    tree.close()
    nodes = list(_walk(tree.root))
    primary = " ".join(_text(n) for n in nodes if n.tag == "h1")
    primary += " ".join(
        "".join(c for c in n.children if isinstance(c, str))
        for n in _all(tree.root)
        if n.tag == "title"
    )
    if any(
        n.attrs.get("id") in ("challenge-form", "cf-challenge-running") for n in nodes
    ) or re.search(r"verify you are human|just a moment|verification humaine", _fold(primary)):
        raise ValueError("overview access challenge")
    participants: list[dict[str, Any]] = []
    declarations: list[dict[str, Any]] = []
    for table in [n for n in nodes if n.tag == "table"][:6]:
        headers: list[str] = []
        author_column: int | None = None
        fixture_columns: list[int] = []
        schedule_headers: list[str] = []
        for tr in (n for n in _walk(table) if n.tag == "tr"):
            cells = [c for c in tr.children if isinstance(c, _Node) and c.tag in ("th", "td")]
            values = [_text(c) for c in cells]
            if table.attrs.get("id") == "spielplanSpiele":
                if any(c.tag == "th" for c in cells) and "date" in [_fold(v) for v in values]:
                    schedule_headers = [_fold(v) for v in values]
                elif len(schedule_headers) == len(values) and all(
                    k in schedule_headers for k in ("date", "a domicile", "a l'exterieur")
                ):
                    mapped = dict(zip(schedule_headers, values, strict=True))
                    declarations.append(
                        dict(
                            nativeFixtureRef=tr.attrs.get("id"),
                            nativeDate=mapped["date"][:120],
                            nativeHome=mapped["a domicile"][:120],
                            nativeAway=mapped["a l'exterieur"][:120],
                            nativeResult=mapped.get("resultat", "")[:40],
                            sourceTimezone=None,
                        )
                    )
            if any(c.tag == "th" for c in cells) and any(
                _fold(v) in ("joueur", "nom", "name", "tipper", "teilnehmer", "participant")
                for v in values
            ):
                headers = values
                author_column = next(
                    (
                        i
                        for i, v in enumerate(headers)
                        if _fold(v)
                        in ("joueur", "nom", "name", "tipper", "teilnehmer", "participant")
                    ),
                    None,
                )
                fixture_columns = [
                    i
                    for i, v in enumerate(headers)
                    if re.search(r"\S\s+(?:-|–|vs\.?)\s+\S", v)
                    and not re.search(r"points|punkte|resultat|ergebnis", _fold(v))
                ][:3]
                continue
            if (
                author_column is None
                or not fixture_columns
                or len(headers) != len(values)
                or len(participants) >= 3
            ):
                continue
            label = values[author_column]
            if (
                not label
                or len(label) > 80
                or re.search(r"resultat|ergebnis|total|points|punkte", _fold(label))
            ):
                continue
            native = [
                dict(fixtureLabel=headers[i][:120], nativeSelection=values[i])
                for i in fixture_columns
                if re.fullmatch(r"\d{1,2}\s*:\s*\d{1,2}", values[i])
            ]
            if native:
                participants.append(dict(pseudonym=label, cells=native))
    structure = []
    for table in [n for n in nodes if n.tag == "table"][:3]:
        children = list(_walk(table))
        structure.append(
            dict(
                id=(table.attrs.get("id") or "")[:80],
                rowCount=sum(n.tag == "tr" for n in children),
                cellCount=sum(n.tag in ("td", "th") for n in children),
                headers=[_text(n)[:120] for n in children if n.tag == "th"][:12],
            )
        )
    return dict(
        status="VISIBLE_NATIVE_SCORE_CELLS_UNADMITTED"
        if participants
        else "NO_VISIBLE_TYPED_SCORE_CELLS",
        participants=participants,
        admittedChoices=0,
        publishedAt=None,
        canonicalKickoffsEstablished=False,
        fixtureDeclarations=sorted(
            declarations, key=lambda r: bool(re.search(r"\d\s*[-:]\s*\d", r["nativeResult"]))
        )[:3],
        tableCount=sum(n.tag == "table" for n in nodes),
        structure=structure,
        limitation="Only typed visible cells are projected. Empty/masked/unsupported tables do not prove absence of choices.",
    )
