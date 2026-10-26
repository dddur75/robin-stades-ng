"""Offline C3 evaluation; opens only the two explicitly supplied JSONL files.

Usage: python -m robin.source_observatory.evaluate_extractor corpus.jsonl gold.jsonl

Corpus rows: {"id": "unique-id", "texte": "..."} (``text`` is also accepted).
Gold rows: {"id": "unique-id", "contributions": [...]} with the same ID set.
An empty contributions list means no prediction. Each annotation contains
``statut`` and, when resolved, exact ``marche`` and ``selection``; ``ligne`` is
required for line markets. ``cote_declaree`` is an explicit decimal string or
null/absent. A flat single-annotation row is also accepted. No fuzzy matching.

Matching is one-to-one per text. Resolved false positives and duplicates stay
in the precision denominator. Missed ambiguous annotations stay in the
unresolved-rate denominator. Zero denominators produce null, never 100%.
The evaluation clock describes the evaluation observation only; it does not
impute source publication times. No source text or extracted dossier is saved.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .extractor import extract_contributions, validate_contribution


def _load(path: str | Path) -> dict[str, dict[str, Any]]:
    result = {}
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
                raise ValueError('each JSONL row requires a nonempty string id')
            if row['id'] in result:
                raise ValueError('duplicate text id')
            result[row['id']] = row
    return result


def _annotations(row: dict[str, Any]) -> list[dict[str, Any]]:
    annotations = row.get('contributions', [row] if 'statut' in row else None)
    if not isinstance(annotations, list):
        raise ValueError('gold requires an explicit contributions list')
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get('statut') not in (
                'resolu', 'non_resolu'):
            raise ValueError('invalid gold status')
        if annotation['statut'] == 'resolu':
            if any(not isinstance(annotation.get(key), str) or not annotation[key].strip()
                   for key in ('marche', 'selection')):
                raise ValueError('resolved gold requires market and selection')
            if annotation['marche'] in ('total', 'handicap') and annotation.get('ligne') is None:
                raise ValueError('line market gold requires an explicit ligne')
        if annotation.get('cote_declaree') is not None:
            try:
                price = Decimal(str(annotation['cote_declaree']).replace(',', '.'))
            except InvalidOperation as exc:
                raise ValueError('invalid gold odds') from exc
            if not price.is_finite() or price < 1:
                raise ValueError('invalid gold odds')
    return annotations


def _same(prediction: dict[str, Any], annotation: dict[str, Any]) -> bool:
    return all(prediction.get(key) == annotation.get(key)
               for key in ('marche', 'selection', 'ligne'))


def _price(value: Any) -> Decimal | None:
    try:
        price = Decimal(str(value).replace(',', '.'))
    except InvalidOperation:
        return None
    return price if price.is_finite() and price >= 1 else None


def _explicit_price(text: str, price: Decimal) -> bool:
    # Independent check against source characters, not the parser's price helper.
    patterns = [
        r'\bc[oô]te\s+(?:(?:totale|globale|du combin[eé])\s+)?(?:[aà]\s+)?'
        r'(\d+[.,]\d+)(?=$|[^\w%.,]|[.,](?!\d))',
        r'@\s*(\d+[.,]\d+)(?=$|[^\w%.,]|[.,](?!\d))',
        r'\(\s*(\d+[.,]\d+)\s*\)',
    ]
    return any(_price(match[1]) == price for pattern in patterns
               for match in re.finditer(pattern, text, flags=re.IGNORECASE))


def evaluate_extractor(corpus_path: str | Path, gold_path: str | Path) -> dict[str, Any]:
    """Compute C3 metrics without opening any other corpus or changing criteria."""
    corpus, gold = _load(corpus_path), _load(gold_path)
    if corpus.keys() != gold.keys():
        raise ValueError('corpus and gold must contain exactly the same text IDs')
    counts = dict(textes=len(corpus), sorties=0, resolus_predits=0, resolus_annotes=0,
                  resolus_corrects=0, non_resolus_annotes=0, non_resolus_corrects=0,
                  sorties_conformes=0)
    invented = 0
    evaluated_at = datetime.now(UTC)
    for identifier, document in corpus.items():
        text = document.get('texte', document.get('text'))
        if not isinstance(text, str):
            raise ValueError('corpus requires texte or text as a string')
        annotations = _annotations(gold[identifier])
        predictions = extract_contributions(
            text, source_id='evaluation', publication_url='https://example.invalid/evaluation',
            author_id='evaluation-non-identifie', publication_id=identifier,
            version_id='evaluation:' + identifier, observed_at=evaluated_at,
        )
        counts['sorties'] += len(predictions)
        counts['resolus_annotes'] += sum(a['statut'] == 'resolu' for a in annotations)
        counts['non_resolus_annotes'] += sum(a['statut'] == 'non_resolu' for a in annotations)
        used: set[int] = set()
        for prediction in predictions:
            try:
                validate_contribution(prediction)
                counts['sorties_conformes'] += 1
            except ValueError:
                pass
            resolved = prediction.get('statut') == 'resolu'
            counts['resolus_predits'] += int(resolved)
            target = next((i for i, a in enumerate(annotations) if i not in used
                           and a['statut'] == prediction.get('statut')
                           and (_same(prediction, a) if resolved else True)), None)
            if target is not None:
                used.add(target)
                counts['resolus_corrects' if resolved else 'non_resolus_corrects'] += 1
            quote = prediction.get('cote_declaree')
            if quote is not None:
                price = _price(quote)
                # Matching consumption penalizes duplicate predictions in precision,
                # but repeating a genuine explicit quote does not invent a price.
                price_supported = any(
                    _price(a.get('cote_declaree')) == price
                    and a['statut'] == prediction.get('statut')
                    and (_same(prediction, a) if resolved else True) for a in annotations)
                if price is None or not price_supported or not _explicit_price(text, price):
                    invented += 1

    def ratio(numerator: str, denominator: str) -> float | None:
        return counts[numerator] / counts[denominator] if counts[denominator] else None

    precision = ratio('resolus_corrects', 'resolus_predits')
    unresolved = ratio('non_resolus_corrects', 'non_resolus_annotes')
    conformity = ratio('sorties_conformes', 'sorties')
    checks = {
        'echantillon_40_textes_minimum': counts['textes'] >= 40,
        'c3_1_precision_85': precision is not None and precision >= 0.85,
        'c3_2_aucune_cote_inventee': invented == 0,
        'c3_3_non_resolu_90': unresolved is not None and unresolved >= 0.90,
        'c3_4_rappel_rapporte': True,
        'c3_5_schema_100': conformity == 1,
    }
    return dict(
        precision_marche_selection=precision, cotes_inventees=invented,
        taux_non_resolu_correct=unresolved, rappel=ratio('resolus_corrects', 'resolus_annotes'),
        conformite_schema=conformity, effectifs=counts,
        c3=dict(statut='PASS' if all(checks.values()) else 'PARTIAL', controles=checks),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus_path', type=Path)
    parser.add_argument('gold_path', type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate_extractor(args.corpus_path, args.gold_path),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
