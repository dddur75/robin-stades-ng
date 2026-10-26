"""Deterministic French prediction extraction, with no network or model calls.

``extract_contributions`` requires supplied publication lineage and observation
time. It does not identify fixtures, invent settlement rules or publication times.
Team names are normalized text, never guessed home/away identities. Periods not
explicitly supplied remain ``non_precisee``. Combinations join their ordered,
explicit legs with `` & ``; their prices are never multiplied.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from .models import instant_text, text_fingerprint
from .schema_validation import validate_contribution as validate_contribution

_number = r'\d+(?:[.,]\d+)?'
_decimal_odds = r'([1-9]\d*[.,]\d+)(?!\w|[.,]\d)(?!\s*%)'
_intent = re.compile(
    r'\b(?:prono(?:stic)?s?|(?:mon|notre) pari|misez|selection|mon choix|'
    r'je (?:ne\s+)?(?:vois|joue|mise|prends|parie)|'
    r'nous jouons|on joue|a jouer)\b')
_market = re.compile(
    r'\b(?:victoire|1n2|1x2|double chance|plus de|moins de|over|under|handicap|'
    r'les deux equipes marquent|btts|score exact|combine)\b')
_ambiguous = re.compile(
    r'\b(?:ou|soit|si|sauf|peut[- ]etre|ne .{0,35}pas|pas de|sans choix)\b')
_hypothetical = re.compile(
    r'\b(?:supposons|imaginons|fictif|fictive|hypothetique|'
    r'je (?:devais|devrais|jouerais|parierais)|pronostic serait)\b')
_history = re.compile(
    r'\b(?:hier|resultat|match termine|a gagne|ont gagne|etait|avait|au dernier match)\b')
_team_stop = (
    r'(?=$|["@(:,;+&\r\n]|\'(?=\s|$)|\s+(?:cote|ou|et|contre|face|ce|demain|aujourd|probabilite|mise|'
    r'statistique|ancienne|a|ont|est|produit|doit|reste|gagne|'
    r'a domicile|a l.exterieur|en deplacement)\b)'
)
_team = r"([a-z0-9][a-z0-9' .\-]*?)"
_bare_score = re.compile(r'\b(\d+)\s*-\s*(\d+)\s+pour\s+\S+')


def _normal(text: str) -> str:
    # Matching only; persisted offsets always come from the original clauses.
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if not unicodedata.combining(c)).replace('’', "'").replace('–', '-')


@dataclass(frozen=True)
class _Pick:
    marche: str
    selection: str
    ligne: str | None = None


def _team_name(value: str) -> str | None:
    team = value.strip(" '.-")
    team = re.sub(r"^(?:l'|le |la |les )", '', team)
    words = team.split()
    # A repeated name followed by prose is a heading/body boundary, not a club.
    for size in range(1, len(words) // 2 + 1):
        if words[:size] == words[size:2 * size]:
            words = words[:size]
            break
    if not words or len(words) > 6 or any(word in (
            'de', 'du', 'des', 'favori', 'visiteur', 'domicile', 'equipe',
            "l'equipe", 'x', 'eux', 'si', 'pas', 'sans') for word in words):
        return None
    return ' '.join(words)


def _picks(clause: str) -> list[_Pick]:
    picks: list[tuple[int, _Pick]] = []
    match: re.Match[str] | None
    for match in re.finditer(r'(?:\b(?:plus de|moins de|over|under)\s+|[+]\s*de\s+)(' + _number +
                             r')(?:\s+buts?)?\b', clause):
        if (match[0].startswith(('plus', 'moins')) and
                not re.search(r'\bbuts?\b', match[0])):
            continue
        if re.match(r'\s*(?:corners?|cartons?|tirs?|fautes?)\b', clause[match.end():]):
            continue
        direction = 'under' if match[0].startswith(('moins', 'under')) else 'over'
        picks.append((match.start(), _Pick('total', direction, match[1].replace(',', '.'))))
    for match in re.finditer(r'\b([ou])\s*(' + _number + r')(?![\d.,])', clause):
        picks.append((match.start(), _Pick('total', 'over' if match[1] == 'o' else 'under',
                                          match[2].replace(',', '.'))))
    for match in re.finditer(r'\bvictoire(?:\s+(?:de|du|des|d\'))?\s+' + _team +
                             _team_stop, clause):
        team = _team_name(match[1])
        if team:
            picks.append((match.start(), _Pick('1N2', team)))
    # Anchor free-form team grammar at the beginning or an explicit choice label.
    leader = r'(?:^\s*|\b(?:prono(?:stic)?|mon choix|mon pari)\s*:\s*)'
    for match in re.finditer(leader + _team + r'\s+gagne\b', clause):
        team = _team_name(match[1])
        if team:
            picks.append((match.start(), _Pick('1N2', team)))
    named_double = False
    for match in re.finditer(leader + _team + r'\s+ou\s+(?:nul|n)\b', clause):
        team = _team_name(match[1])
        if team:
            named_double = True
            picks.append((match.start(), _Pick('double_chance', team + ' ou draw')))
    match = re.search(r'\b(?:1n2|1x2)\s*[:=-]?\s*([1n2x])\b', clause)
    if match:
        picks.append((match.start(), _Pick('1N2', {
            '1': 'home', '2': 'away', 'n': 'draw', 'x': 'draw'}[match[1]])))
    if not named_double and re.search(r'\b(?:match\s+)?nul\b', clause):
        picks.append((clause.index('nul'), _Pick('1N2', 'draw')))
    match = re.search(r'\bdouble chance\s*[:=-]?\s*(1n|1x|n2|x2|12)\b', clause)
    if match:
        picks.append((match.start(), _Pick('double_chance', {
            '1n': 'home_or_draw', '1x': 'home_or_draw', 'n2': 'draw_or_away',
            'x2': 'draw_or_away', '12': 'home_or_away'}[match[1]])))
    for match in re.finditer(r'\bhandicap\s*:?\s*([a-z][a-z .\-]*?)\s+([+-]' +
                             _number + r')(?![\d.,])', clause):
        picks.append((match.start(), _Pick('handicap', match[1].strip(),
                                          str(Decimal(match[2].replace(',', '.'))))))
    match = re.search(r'\b(?:les deux equipes marquent|btts)(?:\s*[:-]\s*|\s+)?(oui|non)?\b',
                      clause)
    if match:
        picks.append((match.start(), _Pick('btts', 'no' if match[1] == 'non' else 'yes')))
    match = re.search(r'\bscore exact\s*:?\s*(\d+)\s*[-:]\s*(\d+)\b', clause)
    if match:
        picks.append((match.start(), _Pick('score_exact', f'{match[1]}-{match[2]}')))
    elif match := _bare_score.search(clause):
        picks.append((match.start(), _Pick('score_exact', f'{match[1]}-{match[2]}')))
    return [pick for _, pick in sorted(picks, key=lambda item: item[0])]


def _missing_market(clause: str, picks: list[_Pick]) -> bool:
    present = {pick.marche for pick in picks}
    return any(re.search(pattern, clause) and market not in present for pattern, market in (
        (r'\bhandicap\b', 'handicap'), (r'\bscore exact\b', 'score_exact'),
        (r'\bdouble chance\b', 'double_chance'),
        (r'\b(?:plus de|moins de|over|under)\b', 'total'),
        (r'\bvictoire\b', '1N2'),
    ))


def _odds(clause: str, *, combined: bool = False) -> tuple[str | None, bool]:
    """Only attached author quote syntax, never an unrelated decimal or a product."""
    if re.search(r'(?:\bcote\s*(?:a\s+)?|@\s*)' + _number +
                 r'\s*(?:ou|/)\s*' + _number, clause):
        return None, True
    if combined:
        patterns = [r'\bcote\s+(?:totale|globale|du combine)\s*(?:a\s+)?' + _decimal_odds]
    else:
        patterns = [r'\bcote\s*(?:a\s+)?' + _decimal_odds,
                    r'@\s*' + _decimal_odds]
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, clause):
            if re.match(r'\s*(?:buts?|corners?|cartons?|euros?|eur|%)\b|\s*€',
                        clause[match.end():]):
                continue
            prefix = clause[max(0, match.start() - 30):match.start()]
            if re.search(r'\b(?:ancienne|adverse|observee|relevee|repere|bookmaker|'
                         r'probabilite|statistique|mise|xg)\b[^@()]*$', prefix):
                continue
            value = match[1].replace(',', '.')
            if Decimal(value) >= 1:
                values.append(value)
    distinct = {Decimal(value) for value in values}
    return (values[0] if len(distinct) == 1 else None, len(distinct) > 1)


def _clauses(text: str) -> list[tuple[int, int, str]]:
    clauses = []
    start = 0
    for match in re.finditer(r'[;\n]+|[.!?](?!\d)', text):
        if text[start:match.start()].strip():
            clauses.append((start, match.start(), text[start:match.start()]))
        start = match.end()
    if text[start:].strip():
        clauses.append((start, len(text), text[start:]))
    merged: list[tuple[int, int, str]] = []
    for begin, end, original in clauses:
        # Explicit continuation lines belong to the preceding combination.
        if merged and re.match(r'\s*(?:[+&]|cote\s+(?:totale|globale))', _normal(original)):
            previous = merged.pop()
            merged.append((previous[0], end, text[previous[0]:end]))
        else:
            merged.append((begin, end, original))
    result: list[tuple[int, int, str]] = []
    for begin, end, original in merged:
        # Flattened tables still have independent rows, each ending at its quote.
        # Never split a leg followed by a conjunction in an actual combination.
        local = 0
        for quote in re.finditer(r'@\s*\d+[.,]\d+(?![\d.,%])', original):
            following = original[quote.end():]
            if re.match(r'\s+[\wÀ-ÿ]', following) and re.search(
                    r'\b(?:vs|versus)\b.*\b(?:over|under)\b', following, re.IGNORECASE):
                result.append((begin + local, begin + quote.end(), original[local:quote.end()]))
                local = quote.end()
        if original[local:].strip():
            result.append((begin + local, end, original[local:]))
    return result


def extract_contributions(
    text: str, *, source_id: str, publication_url: str, author_id: str,
    publication_id: str, version_id: str, observed_at: datetime,
    preuve_permise: str | None = None,
) -> list[dict[str, Any]]:
    """Return schema-validated metadata; no prediction yields an empty list.

    ``cote_declaree_at`` is the supplied observation time of the explicit quote,
    not an inferred publication time. Missing prices remain null. Evidence text
    is omitted unless a permission URL is supplied (one excerpt, <=500 chars).
    """
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    normalized = _normal(text)
    if not normalized.strip():
        return []
    clauses = _clauses(text)
    digest = text_fingerprint(text)
    if not isinstance(observed_at, datetime):
        raise ValueError('explicit observation time and timezone required')
    offset = observed_at.utcoffset()
    if offset is None:
        raise ValueError('explicit observation time and timezone required')
    instant = dict(utc=instant_text(observed_at),
                   origin_timezone=getattr(observed_at.tzinfo, 'key', None) or observed_at.tzname(),
                   origin_offset_seconds=int(offset.total_seconds()))
    rows: list[dict[str, Any]] = []
    for start, end, original in clauses:
        clause = _normal(original)
        direct = clause.lstrip(' \t\r\"\'*-')
        intent = bool(_intent.search(clause))
        question = end < len(text) and text[end] == '?'
        if question or _hypothetical.search(clause):
            continue
        # Headers and invitations describe a document, not an author's selection.
        if re.search(r'\b(?:voici|propose|decouvrez)\b.*\bpronostics?\b', clause):
            continue
        picks = _picks(clause)
        explicit_grammar = bool(re.match(
            r"\s*(?:[a-z][a-z0-9' .-]*?\s+(?:gagne|ou\s+nul)\b|[ou]\d)", clause))
        table_pick = bool(re.search(r'\b(?:vs|versus)\b', clause) and
                          re.search(r'@\s*\d', clause) and picks)
        if not (intent or _market.match(direct) or _bare_score.match(direct) or
                explicit_grammar or table_pick or re.match(r'\s*(?:nul|match nul)\b', clause)):
            continue
        if _history.search(clause) or (not intent and re.search(
                r'\bvictoire\b.*\d+\s*[-:]\s*\d+', clause)):
            continue
        if not picks and not _market.match(direct) and not re.search(
                r'\b(?:mon|notre)\s+(?:pronostic|pari)\s*:|\bprono\s*:', clause):
            continue
        linked = bool(re.search(r'\s[&x]\s|\s\+\s|\s+et\s+', clause))
        combined = linked and (len(picks) >= 2 or bool(re.search(r'\bcombine\b', clause)))
        reason = None
        odds, odds_conflict = _odds(clause, combined=combined)
        ambiguity_text = clause
        if any(p.marche == 'double_chance' and p.selection.endswith(' ou draw') for p in picks):
            ambiguity_text = re.sub(r'\bou\s+(?:nul|n)\b', '', ambiguity_text)
        if _ambiguous.search(ambiguity_text):
            reason = 'selection_ambigue_ou_niee'
        elif _missing_market(clause, picks):
            reason = 'marche_ou_selection_indeterminable'
        elif any(p.marche == 'total' for p in picks) and re.search(
                r'\bbuts?\s+(?:pour|de|du|des)\b', clause):
            reason = 'total_equipe_distinct_du_total_match'
        elif odds_conflict:
            reason = 'plusieurs_cotes_declarees'
        elif not picks:
            reason = 'marche_ou_selection_indeterminable'
        elif not combined and len(picks) != 1:
            reason = 'plusieurs_selections_sans_liaison_certaine'
        elif linked and not combined:
            reason = 'jambes_du_combine_indeterminables'
        if combined:
            # Every named leg must carry an explicit market; team names alone
            # cannot establish a victory/qualification/DNB selection.
            legs = re.split(r'\s+[+&x]\s+|\s+et\s+', clause)
            if len(picks) < 2 or any(
                    part.strip() and not _picks(part) and
                    not re.fullmatch(r'\s*(?:pronostics?[^:]*|combine[^:]*)\s*:?\s*', part)
                    for part in legs):
                reason = reason or 'jambes_du_combine_indeterminables'
            market = 'combine'
            selection = ' & '.join(
                p.selection + (' ' + p.ligne if p.ligne else '') for p in picks
            ) if picks else 'indeterminee'
            line = None
            # A single quote on an implicit, same-match conjunction is its price.
            # Explicit per-leg prices on named combinations are never multiplied.
            if ('&' in clause and not re.search(r'\bcombine\b', clause) and
                    not any(_odds(leg)[0] for leg in legs[:-1])):
                odds, odds_conflict = _odds(clause)
                if odds_conflict:
                    reason = reason or 'plusieurs_cotes_declarees'
        else:
            pick = picks[0] if len(picks) == 1 else _Pick('indetermine', 'indeterminee')
            market, selection, line = pick.marche, pick.selection, pick.ligne
        if reason:
            # A genuine number cannot be attributed to an unidentified selection.
            odds = None
        slot = len(rows) + 1
        identity = text_fingerprint(f'{source_id}|{publication_id}|{version_id}|{digest}|{slot}')
        # Offsets always refer to the original text, never the normalized copy.
        excerpt_end = min(end, start + 500)
        row = dict(
            source_id=source_id, publication_url=publication_url, text_sha256=digest,
            langue='fr', marche=market, selection=selection, ligne=line,
            cote_declaree=odds, cote_observee=None,
            statut='non_resolu' if reason else 'resolu', raison_non_resolu=reason,
            extraits_preuve=[dict(text_sha256=digest, start=start, end=excerpt_end,
                                 text=text[start:excerpt_end] if preuve_permise else None)],
            contribution_id='extraction:' + identity, version_id=version_id,
            author_id=author_id, publication_id=publication_id, preuve_permise=preuve_permise,
            liens_reprise=[], match_id=None, certitude_rapprochement='non_resolue',
            periode='non_precisee', reglement=None, bookmaker=None,
            categorie='selection_avec_cote' if odds else 'selection_sans_cote',
            probabilite=None, selection_key=f'selection-{slot}',
            cote_declaree_provenance=f'auteur:texte:{digest}:{start}:{end}' if odds else None,
            cote_declaree_at=instant if odds else None,
            cote_observee_provenance=None, cote_observee_at=None, observed_at=instant,
        )
        validate_contribution(row)
        rows.append(row)
    return rows
