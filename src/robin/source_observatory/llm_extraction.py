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

from .extractor import _normal
from .extractor import extract_contributions as deterministic_extract
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
        raw = prompt_path.read_bytes()
        freeze = freeze_path.read_text(encoding='utf-8')
        hashes = re.findall(r'^sha256\s*:\s*([0-9a-f]{64})\s*$', freeze, re.MULTILINE)
        digest = sha256(raw).hexdigest()
        if hashes != [digest]:
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
            or not isinstance(value['extrait_preuve'], str)):
        raise ValueError('invalid extraction envelope')
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
    return value


def _canonical_pick(market: str, selection: str, line: str | None, text: str) -> bool:
    fixed = {
        'double_chance': {'home_or_draw', 'draw_or_away', 'home_or_away'},
        'total': {'over', 'under'}, 'btts': {'yes', 'no'},
    }
    if market in ('total', 'handicap'):
        if line is None:
            return False
    elif line is not None:
        return False
    if market in fixed:
        return selection in fixed[market]
    if market == 'score_exact':
        return re.fullmatch(r'\d+-\d+', selection) is not None
    if market == '1N2' and selection in ('home', 'away', 'draw'):
        return True
    if market in ('1N2', 'handicap'):
        return (re.fullmatch(r"[a-z0-9][a-z0-9 '.-]*", selection) is not None
                and re.search(r'(?<!\w)' + re.escape(selection) + r'(?!\w)', _normal(text))
                is not None)
    if market == 'combine':
        # The prompt has no closed leg syntax: retain only an unresolved draft.
        return False
    return False


def _literal_odds(value: Any, text: str) -> tuple[Decimal | None, bool]:
    if value is None:
        return None, True
    quote = str(value).replace(',', '.')
    tokens = {m[0].replace(',', '.') for m in re.finditer(
        r'(?<![\w.,])\d+(?:[.,]\d+)?(?!\w|[.,]\d)', text)}
    if re.fullmatch(r'[1-9]\d*(?:\.\d+)?', quote) is None or quote not in tokens:
        return None, False
    return Decimal(quote), True


def _draft(pick: dict[str, Any], *, text: str, excerpt: str, version: PublicationVersion,
           publication: Publication, author_id: str, observed_at: datetime,
           preuve_permise: str | None, identity: str, slot: int) -> Contribution:
    start = text.find(excerpt)
    if not excerpt.strip() or start < 0:
        raise ValueError('nonliteral evidence excerpt')
    end = min(start + len(excerpt), start + 500)
    odds, literal = _literal_odds(pick['cote_declaree'], text)
    market, selection = pick['marche'], pick['selection']
    line = pick['ligne'].replace(',', '.') if pick['ligne'] is not None else None
    canonical = _canonical_pick(market, selection, line, text)
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
    in-memory callable. Every nonempty invalid JSONL line is rejected as a whole;
    valid surrounding lines survive. Blank lines are ignored. Drafts are held
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
    # Reuse conservative French intent recognition, not the deterministic picks:
    # ambiguous/unknown picks can still be interpreted by the injected route.
    eligible = deterministic_extract(
        text, source_id=publication.source_id, publication_url=publication.publication_url,
        author_id=author_id, publication_id=publication.publication_id,
        version_id=version_id, observed_at=observed_at,
    )
    # The deterministic extractor also reports negated picks as ambiguous rows.
    # An explicit refusal is not permission for a model to manufacture a bet.
    has_bet = any(not re.search(
        r'\b(?:ne .{0,35}pas|aucun pari|pas de pari|sans pari|'
        r'(?:je|on) (?:joue|mise|parie|prends) pas)\b',
        _normal(text[row['extraits_preuve'][0]['start']:row['extraits_preuve'][0]['end']]),
    ) for row in eligible)
    output = ''
    if has_bet:
        output = route(prompt + '\n' + json.dumps({'id': version_id, 'texte': text},
                                                ensure_ascii=False))
        if not isinstance(output, str):
            raise ValueError('route must return JSONL text')
    output_digest = text_fingerprint(output)
    identity = text_fingerprint(f'{version_id}|{prompt_digest}|{output_digest}|'
                                f'{observed_at.isoformat()}|{author_id}|{preuve_permise}')
    drafts: list[Contribution] = []
    rejected = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            envelope = _envelope(line, version_id)
            pending = [_draft(
                pick, text=text, excerpt=envelope['extrait_preuve'], version=version,
                publication=publication, author_id=author_id, observed_at=observed_at,
                preuve_permise=preuve_permise, identity=identity, slot=len(drafts) + index + 1,
            ) for index, pick in enumerate(envelope['contributions'])]
        except (ValueError, TypeError, ArithmeticError):
            rejected += 1
            continue
        drafts.extend(pending)
    store.append(ExtractionRecord(
        'extraction:' + identity, version_id, version.text_sha256, prompt_digest,
        output_digest, observed_at, tuple(drafts), rejected,
    ))
    return [draft.extraction_metadata() for draft in drafts]
