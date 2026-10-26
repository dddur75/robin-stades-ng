"""Frozen-prompt extraction into audited drafts, never accepted predictions.

The injected route accepts a request string (the exact frozen prompt followed by
one JSON input line) and returns JSONL in the frozen prompt's envelope format.
Call ``extract_contributions`` with text matching an existing PublicationVersion.
No raw source or model response is stored; excerpts require explicit permission.

Production transport: ROBIN_AGY_COMMAND is a JSON argv array, e.g.
``["agy", "-p", "--model", "gemini-4-argon-high"]``. The request goes to
stdin, never through shell interpolation or command arguments. The default
command uses that route; tools/permissions are not escalated by this adapter.
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # nosec B404
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from .extractor import _clauses, _history, _hypothetical, _intent, _normal, _picks, _team_name
from .models import (
    Contribution,
    EvidenceExcerpt,
    ExtractionRecord,
    Publication,
    PublicationVersion,
    _instant,
    _text,
    text_fingerprint,
)
from .schema_validation import validate_contribution
from .store import AppendOnlyStore

FROZEN_PROMPT_SHA256 = '69dafca29b2de56467427b0ff475bbcfaef27491d52a4c685304b2a8f567fe70'


@dataclass(frozen=True)
class AgyRoute:
    """Explicit subprocess transport, with bounded time and sanitized failures."""

    command: tuple[str, ...]
    timeout: float = 120.0

    def __post_init__(self) -> None:
        if (not self.command or any(not isinstance(arg, str) or not arg or '\0' in arg
                                    for arg in self.command)):
            raise ValueError('ROBIN_AGY_COMMAND must be a nonempty JSON argv array')
        if not 0 < self.timeout <= 600:
            raise ValueError('agy timeout must be in (0, 600]')

    @classmethod
    def from_env(cls) -> AgyRoute:
        raw = os.environ.get('ROBIN_AGY_COMMAND')
        if raw is None:
            return cls(('agy', '-p', '--model', 'gemini-4-argon-high', '--effort', 'high',
                        '--disable-slash-commands'))
        try:
            command = json.loads(raw)
        except ValueError:
            raise ValueError('ROBIN_AGY_COMMAND must be a JSON argv array') from None
        if not isinstance(command, list):
            raise ValueError('ROBIN_AGY_COMMAND must be a JSON argv array')
        return cls(tuple(command))

    def __call__(self, request: str) -> str:
        try:
            # Operator-supplied argv, shell disabled, input restricted to stdin.
            result = subprocess.run(  # nosec B603
                self.command, input=request, capture_output=True, text=True,
                encoding='utf-8', errors='strict', timeout=self.timeout, check=False,
                shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise RuntimeError('agy transport failed') from None
        if result.returncode:
            raise RuntimeError('agy process failed')
        return result.stdout


def _frozen_prompt(prompt_path: Path, freeze_path: Path) -> tuple[str, str]:
    try:
        raw = prompt_path.read_bytes().replace(b'\r\n', b'\n')
        freeze = freeze_path.read_text(encoding='utf-8')
        hashes = re.findall(r'^sha256_lf\s*:\s*([0-9a-f]{64})\s*$', freeze, re.MULTILINE)
        digest = sha256(raw).hexdigest()
        if hashes != [digest] or digest != FROZEN_PROMPT_SHA256:
            raise ValueError('prompt sha256 differs from frozen prompt')
        return raw.decode('utf-8'), digest
    except (OSError, UnicodeError):
        raise ValueError('frozen prompt unavailable') from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError('nonfinite JSON number')


def _envelope(line: str, version_id: str) -> dict[str, Any]:
    value = json.loads(line, object_pairs_hook=_unique_object, parse_float=Decimal,
                       parse_constant=_invalid_constant)
    if (not isinstance(value, dict)
            or set(value) != {'id', 'contributions', 'extrait_preuve'}
            or value['id'] != version_id or not isinstance(value['contributions'], list)
            or not isinstance(value['extrait_preuve'], str)
            or len(value['extrait_preuve']) > 500):
        raise ValueError('invalid extraction envelope')
    seen = set()
    for pick in value['contributions']:
        if (not isinstance(pick, dict) or set(pick) != {
                'marche', 'selection', 'ligne', 'cote_declaree', 'statut', 'raison_non_resolu'}
                or any(not isinstance(pick[key], str) or not pick[key].strip()
                       for key in ('marche', 'selection'))
                or pick['statut'] not in ('resolu', 'non_resolu')
                or (pick['ligne'] is not None and (not isinstance(pick['ligne'], str)
                    or re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?', pick['ligne']) is None))
                or (pick['cote_declaree'] is not None
                    and type(pick['cote_declaree']) not in (str, int, Decimal))
                or (pick['statut'] == 'resolu' and pick['raison_non_resolu'] is not None)
                or (pick['statut'] == 'non_resolu' and (
                    not isinstance(pick['raison_non_resolu'], str)
                    or not pick['raison_non_resolu'].strip()))):
            raise ValueError('invalid contribution shape')
        key = (pick['marche'], pick['selection'],
               Decimal(pick['ligne'].replace(',', '.')) if pick['ligne'] is not None else None)
        if key in seen:
            raise ValueError('duplicate selection in extraction envelope')
        seen.add(key)
    return value


def _canonical_pick(market: str, selection: str, line: str | None, text: str) -> bool:
    clause = re.sub(r'\bprix\b', 'cote', _normal(text))
    picks = _picks(clause)
    ambiguity = clause
    if any(p.marche == 'double_chance' and p.selection.endswith(' ou draw') for p in picks):
        ambiguity = re.sub(r'\bou\s+(?:nul|n)\b', '', ambiguity)
    if re.search(r'\b(?:ou|soit)\b', ambiguity):
        return False
    if market in ('total', 'handicap'):
        if line is None:
            return False
    elif line is not None:
        return False
    if market == '1N2' and selection in ('home', 'away'):
        return False
    if market in ('1N2', 'handicap') and _team_name(selection) != selection:
        return False
    if market == 'total':
        if re.search(r'\bbuts?\s+(?:pour|de|du|des)\b', clause):
            return False
        if line is None or Decimal(line) <= 0 or not re.search(
                r'\b(?:over|under|plus de|moins de)\s+' + re.escape(line).replace(r'\.', '[.,]')
                + r'\s+buts?\b', clause):
            return False
    if market == 'handicap' and (line is None or not line.startswith(('+', '-'))):
        return False
    if market == '1N2' and selection == 'draw' and not re.search(
            r'\bmatch\s+nul\b|\b(?:1n2|1x2)\s*[:=-]?\s*[nx]\b|'
            r'\b(?:pari|prono(?:stic)?|selection|choix)\s*:\s*(?:le\s+)?nul\b|'
            r'\b(?:joue|mise|parie|prends|vois)\s+(?:le\s+|un\s+)?nul\b|^\s*nul\b', clause):
        return False
    if market == 'combine':
        legs = re.split(r'\s+[+&x]\s+|\s+et\s+', clause)
        return (len(legs) >= 2 and len(picks) >= 2
                and all(len(_picks(leg)) == 1 for leg in legs)
                and all(_canonical_pick(p.marche, p.selection, p.ligne, clause) for p in picks)
                and selection == ' & '.join(
                    p.selection + (' ' + p.ligne if p.ligne else '') for p in picks))
    # Bind the literal team to the choice grammar, rather than treating every
    # source word (or part of a price) as a team when an intent marker is present.
    team = re.escape(selection)
    if (market == '1N2' and selection != 'draw' and not picks
            and re.search(r'[a-z]', selection)
            and re.search(
                r'\b(?:je (?:joue|mise|prends|parie(?: sur)?)|'
                r'(?:mon choix|(?:mon|notre) pari)\s*:)\s+' + team
                + r'\s*(?:cote\b|prix\b|@|vainqueur\b|$)|'
                r'(?<!\w)' + team + r'\s+vainqueur\b', clause)):
        return True
    return any(p.marche == market and p.selection == selection and (
        p.ligne == line or (p.ligne is not None and line is not None
                           and Decimal(p.ligne) == Decimal(line))) for p in picks)


def _literal_odds(value: Any, text: str, *, combined: bool = False) -> tuple[Decimal | None, bool]:
    if value is None:
        return None, True
    quote = str(value).replace(',', '.')
    if re.fullmatch(r'[1-9]\d*\.\d+', quote) is None:
        return None, False
    clause = _normal(text)
    tokens = []
    marker = (r'\bcote\s+(?:totale|globale|du combine)\s*(?:a\s+)?' if combined else
              r'(?:\b(?:cote|prix)\s*(?:a\s+)?|@\s*|\bvainqueur\s+a\s*)')
    for match in re.finditer(marker + r'([1-9]\d*[.,]\d+)(?!\w|[.,]\d)', clause):
        prefix = clause[:match.start()]
        suffix = clause[match.end():]
        if re.search(r'\b(?:ancienne|adverse|observee|relevee|bookmaker|probabilite|'
                     r'statistique|mise|xg)\b[^@()]*$', prefix):
            continue
        if re.match(r'\s*(?:%|€|buts?\b|corners?\b|cartons?\b|euros?\b|eur\b|'
                    r'xg\b|ou\b|/)', suffix):
            continue
        tokens.append(match[1].replace(',', '.'))
    if quote not in tokens or len(set(tokens)) != 1:
        return None, False
    return Decimal(quote), True


def _unasserted(clause: str) -> bool:
    # Inspect only the containing clause. An instruction elsewhere in the source
    # is data too, and cannot enable/disable validation of a separate prediction.
    if (_hypothetical.search(clause) or _history.search(clause)
            or re.search(r'\bignore\s+(?:tout|toutes)\b|'
                         r'\b(?:retourne|reponds)\s+marche\s*=|\bsystem\s*:', clause)):
        return True
    # Intensifying "si" ("le temps est si beau") is not a condition.
    conditions = re.sub(r'\b(?:est|sont|semble|parait|reste)\s+si\b', '', clause)
    if re.search(r'\b(?:si|sauf|peut[- ]etre|eventuellement|hypothese)\b', conditions):
        return True
    if re.search(r'\bsans\s+(?:choix|parier|jouer|miser)\b', clause):
        return True
    # Commas delimit independent assertions, but never decimal tokens. This keeps
    # "je ne regarde pas la meteo, mon pari ..." without accepting "ne joue pas".
    for part in re.split(r',(?=\s|$)', clause):
        if not (_picks(part) or _intent.search(part)):
            continue
        if re.search(r"\b(?:ne\b.*\b(?:pas|jamais|plus|rien|aucune?s?)\b|"
                     r"aucune?s?\b|ni\b|sans\b|"
                     r"pas de\b|(?:je|on) (?:joue|mise|parie|prends) pas\b)", part):
            return True
    return False


def _draft(pick: dict[str, Any], *, text: str, excerpt: str, version: PublicationVersion,
           publication: Publication, author_id: str, observed_at: datetime,
           preuve_permise: str | None, identity: str, slot: int,
           source_clauses: list[tuple[int, int, str]]) -> Contribution:
    start = text.find(excerpt)
    if not excerpt.strip() or start < 0 or len(excerpt) > 500:
        raise ValueError('nonliteral evidence excerpt')
    end = start + len(excerpt)
    if ((start > 0 and text[start - 1].isalnum())
            or (start > 1 and text[start - 1] in '.,' and text[start - 2].isdigit()
                and text[start].isdigit())
            or (end < len(text) and text[end].isalnum())
            or (end + 1 < len(text) and text[end] in '.,' and text[end + 1].isdigit())):
        raise ValueError('evidence cuts a source token')
    # Validate the containing source clause too: cropping away a negation must
    # not turn a refusal into a selection. Source prose never configures guards.
    clauses = [(begin, finish, clause) for begin, finish, clause in source_clauses
               if begin < end and finish > start]
    if len(clauses) != 1:
        raise ValueError('one asserted evidence clause required')
    begin, finish, original = clauses[0]
    clause = _normal(original)
    market, selection = pick['marche'], pick['selection']
    line = pick['ligne'].replace(',', '.') if pick['ligne'] is not None else None
    if (_unasserted(clause) or (finish < len(text) and text[finish] == '?')
            or not (_picks(clause) or _canonical_pick(market, selection, line, clause))):
        raise ValueError('evidence is not an asserted selection')
    odds, literal = _literal_odds(pick['cote_declaree'], excerpt, combined=market == 'combine')
    _, clause_literal = _literal_odds(pick['cote_declaree'], original,
                                     combined=market == 'combine')
    literal = literal and clause_literal
    canonical = (_canonical_pick(market, selection, line, original)
                 and _canonical_pick(market, selection, line, excerpt))
    reason = 'match_non_rapproche'
    if not literal:
        reason = 'cote_non_litterale'
    elif not canonical:
        reason = 'vocabulaire_non_canonique'
    elif pick['statut'] == 'non_resolu':
        # Do not persist unrestricted prose returned by the model.
        reason = 'extraction_non_resolue'
    if not literal or not canonical or pick['statut'] == 'non_resolu':
        odds = None
    if not canonical:
        market, selection, line = 'indetermine', 'indeterminee', None
    # Keep neighbouring context in the evidence, rather than persisting the
    # route's potentially misleading crop. Long safe clauses may still use a
    # bounded literal excerpt; uncertain context beyond that budget is refused.
    if finish - begin <= 500:
        start, end = begin, finish
    elif not literal or not canonical:
        raise ValueError('uncertain source context exceeds evidence budget')
    draft = Contribution(
        contribution_id=f'llm:{identity}:{slot}', version_id=version.version_id,
        source_id=publication.source_id, publication_url=publication.publication_url,
        text_sha256=version.text_sha256, langue='fr', marche=market, selection=selection,
        cote_declaree=odds, cote_observee=None, statut='non_resolu', raison_non_resolu=reason,
        extraits_preuve=(EvidenceExcerpt(version.text_sha256, start, end,
                                         text[start:end] if preuve_permise else None),),
        author_id=author_id, publication_id=publication.publication_id,
        preuve_permise=preuve_permise, liens_reprise=(), match_id=None,
        certitude_rapprochement='non_resolue', ligne=Decimal(line) if line is not None else None,
        periode='non_precisee', reglement=None,
        cote_declaree_provenance=f'auteur:texte:{version.text_sha256}' if odds else None,
        cote_declaree_at=observed_at if odds else None, cote_observee_provenance=None,
        cote_observee_at=None, bookmaker=None,
        categorie='selection_avec_cote' if odds else 'selection_sans_cote', probabilite=None,
        observed_at=observed_at, selection_key=f'selection-{slot}',
    )
    validate_contribution(draft.extraction_metadata())
    return draft


def extract_contributions(
    text: str, *, store: AppendOnlyStore, version_id: str, author_id: str,
    observed_at: datetime, route: Callable[[str], str], preuve_permise: str | None = None,
    prompt_path: Path = Path('data/source_observatory/prompt_extraction.md'),
    freeze_path: Path = Path('data/source_observatory/prompt_extraction.freeze.md'),
) -> list[dict[str, Any]]:
    """Verify lineage and prompt before invoking a route; append only safe drafts.

    Pass ``AgyRoute.from_env()`` explicitly for production. For tests supply an
    in-memory callable. Exactly one JSONL envelope is allowed for this version;
    prose, Markdown and multiple envelopes invalidate the whole response. Drafts are held
    in ExtractionRecord, never directly added to accepted Contribution entities.
    """
    prompt, prompt_digest = _frozen_prompt(prompt_path, freeze_path)
    if not isinstance(text, str):
        raise TypeError('source text must be a string')
    _instant(observed_at, 'extraction observation')
    _text(author_id, 'author_id')
    entities = store.entities()
    version = next((v for v in entities if isinstance(v, PublicationVersion)
                    and v.version_id == version_id), None)
    if version is None:
        raise ValueError('existing publication version required')
    if version.text_sha256 != text_fingerprint(text):
        raise ValueError('source text sha256 differs from publication version')
    if observed_at < version.usable_at:
        raise ValueError('extraction precedes usable version')
    publication = next(p for p in entities if isinstance(p, Publication)
                       and p.publication_id == version.publication_id)
    output = route(prompt + '\n' + json.dumps({'id': version_id, 'texte': text},
                                            ensure_ascii=False))
    if not isinstance(output, str):
        raise ValueError('route must return JSONL text')
    output_digest = text_fingerprint(output)
    identity = text_fingerprint(f'{version_id}|{prompt_digest}|{output_digest}|'
                                f'{observed_at.isoformat()}|{author_id}|{preuve_permise}')
    drafts: list[Contribution] = []
    rejected = 0
    lines = [line for line in output.splitlines() if line.strip()]
    try:
        if len(lines) != 1:
            raise ValueError('exactly one JSONL envelope required')
        envelope = _envelope(lines[0], version_id)
        source_clauses = _clauses(text)
        drafts = [_draft(
            pick, text=text, excerpt=envelope['extrait_preuve'], version=version,
            publication=publication, author_id=author_id, observed_at=observed_at,
            preuve_permise=preuve_permise, identity=identity, slot=index + 1,
            source_clauses=source_clauses,
        ) for index, pick in enumerate(envelope['contributions'])]
    except (ValueError, TypeError, ArithmeticError):
        rejected = max(1, len(lines))
    store.append(ExtractionRecord(
        'extraction:' + identity, version_id, version.text_sha256, prompt_digest,
        output_digest, observed_at, tuple(drafts), rejected,
    ))
    return [draft.extraction_metadata() | {'prompt_sha256': prompt_digest} for draft in drafts]
