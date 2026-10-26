"""Synthetic lexicon cases, independent of the private reference corpus."""

import builtins
import copy
import json
from datetime import UTC, datetime

import pytest

from robin.source_observatory.extractor import extract_contributions, validate_contribution


def extract(text, **changes):
    return extract_contributions(text, **(dict(
        source_id='synthetic', publication_url='https://example.invalid/p',
        author_id='synthetic-author', publication_id='p', version_id='v',
        observed_at=datetime(2026, 10, 26, tzinfo=UTC),
    ) | changes))


@pytest.mark.parametrize('text,market,selection,line', [
    ('Mon pronostic : victoire de Toulouse cote 1.85', '1N2', 'toulouse', None),
    ('Victoire Saint-Étienne @1,85', '1N2', 'saint-etienne', None),
    ('Pronostic 1N2 : 2 (1.85)', '1N2', 'away', None),
    ('Mon pari : nul', '1N2', 'draw', None),
    ('Double chance : 1N', 'double_chance', 'home_or_draw', None),
    ('Double chance : N2', 'double_chance', 'draw_or_away', None),
    ('Double chance : 12', 'double_chance', 'home_or_away', None),
    ('Plus de 2,5 buts @1,85', 'total', 'over', '2.5'),
    ('Moins de 3 buts', 'total', 'under', '3'),
    ('Pronostic : Over 2.5', 'total', 'over', '2.5'),
    ('Handicap Toulouse -1,5', 'handicap', 'toulouse', '-1.5'),
    ('Les deux équipes marquent : oui', 'btts', 'yes', None),
    ('Les deux équipes marquent : non', 'btts', 'no', None),
    ('Les deux équipes marquent - non', 'btts', 'no', None),
    ('Score exact : 2-1', 'score_exact', '2-1', None),
    ("Victoire de l'Ajax @1.85", '1N2', 'ajax', None),
    ('Victoire du Stade Brestois 29', '1N2', 'stade brestois 29', None),
    ('Mon pronostic 1N2 : N', '1N2', 'draw', None),
])
def test_french_lexicon(text, market, selection, line):
    rows = extract(text)
    assert len(rows) == 1
    row = rows[0]
    assert (row['statut'], row['marche'], row['selection'], row['ligne']) == (
        'resolu', market, selection, line)
    validate_contribution(row)


@pytest.mark.parametrize('quote', ['cote 1.85', 'cote à 1,85', '@1,85', '@1,85,'])
def test_only_author_explicit_odds(quote):
    row = extract('Victoire de Reims ' + quote)[0]
    assert row['cote_declaree'] == '1.85'
    assert row['cote_observee'] is None
    assert row['cote_declaree_provenance']


@pytest.mark.parametrize('suffix', [
    '', 'probabilité 75%', 'mise 1.85 euros', 'statistique 1.85',
    'cote de repère de prix 1.85', 'cote observée 1.85',
    'ancienne cote 1.85', 'cote adverse 1.85', '(0.85)', '(1.85%)',
    '@1.85e2', 'probabilité (1.85)', 'cote de repère de prix (1.85)',
])
def test_numbers_and_non_author_quotes_never_become_declared_odds(suffix):
    row = extract('Victoire de Reims ' + suffix)[0]
    assert row['cote_declaree'] is None
    assert row['cote_declaree_at'] is None
    assert row['categorie'] == 'selection_sans_cote'


def test_alternative_prices_remain_unknown():
    row = extract('Victoire de Reims cote 1.85 ou 2.10')[0]
    assert row['statut'] == 'non_resolu'
    assert row['cote_declaree'] is None


@pytest.mark.parametrize('text', [
    'Pronostic : victoire de Reims ou de Metz', 'Double chance', 'Handicap Reims',
    'Score exact', 'Mon pronostic : une belle surprise', '1N2',
    'Plus de buts', 'Combiné Reims x Metz', 'Je ne joue pas la victoire de Reims',
    'Pronostic : nul ou victoire de Reims', 'Handicap Reims -1,5 ou -2,5',
    'Victoire de Reims cote 1.85 ou 2.10',
    'Victoire du favori', 'Victoire de Reims et score exact',
    'Combiné : victoire de Reims + plus de 2,5 buts + handicap Metz',
    'Plus de 2.5 ou 3.5 buts',
    'Victoire de Reims si le titulaire joue',
    'Victoire de Reims cote 1.85 / 2.10',
    'Plus de 2,5 corners', 'Mon pari : moins de 3 cartons',
    'Plus de 1,5 buts pour Reims',
])
def test_ambiguity_is_never_resolved(text):
    rows = extract(text)
    assert rows
    assert all(row['statut'] == 'non_resolu' and row['raison_non_resolu'] for row in rows)


@pytest.mark.parametrize('text', [
    '', 'Le stade ouvre à 18 h.', 'Résultat : Reims 2-1 Metz.',
    'Reims a gagné hier. Victoire de Reims 2-1.',
    'Qui parie encore sur Reims ?', 'Le match nul de dimanche était prévisible.',
    'Voici les compositions et les statistiques.',
    'Victoire de Reims au dernier match.',
    'Le règlement explique le handicap et le score exact.',
    'La victoire de prestige fait plaisir aux supporters.',
    'Les paris sportifs incluent le marché 1N2.',
])
def test_without_prediction_there_is_no_contribution(text):
    assert extract(text) == []


def test_multiple_picks_keep_local_odds_and_do_not_leak():
    rows = extract('Victoire de Reims @1.85\nPlus de 2,5 buts\nNul cote 3.20')
    assert [(r['selection'], r['cote_declaree']) for r in rows] == [
        ('reims', '1.85'), ('over', None), ('draw', '3.20')]
    assert len({r['contribution_id'] for r in rows}) == 3


def test_combination_keeps_legs_and_never_multiplies_prices():
    row = extract('Combiné : victoire de Reims @1.85 + plus de 2,5 buts @1.50')[0]
    assert row['marche'] == 'combine'
    assert row['statut'] == 'resolu'
    assert row['cote_declaree'] is None
    assert row['selection'] == 'reims & over 2.5'


def test_combination_accepts_only_an_explicit_total_quote():
    row = extract('Combiné cote totale 2,80 : victoire de Reims + moins de 4,5 buts')[0]
    assert row['cote_declaree'] == '2.80'


def test_prediction_headings_do_not_create_extra_unresolved_rows():
    rows = extract('Pronostic 1N2 du match Reims Metz\nNos pronostics gratuits\n'
                   'Notre pronostic : victoire de Reims @1.85')
    assert len(rows) == 1
    assert rows[0]['selection'] == 'reims'


def test_factual_background_and_followup_question_do_not_erase_a_prediction():
    rows = extract('Reims a gagné hier. Victoire de Reims demain @1.85. Votre avis ?')
    assert len(rows) == 1
    assert rows[0]['selection'] == 'reims'
    assert rows[0]['cote_declaree'] == '1.85'


def test_score_for_named_team_preserves_written_score_without_guessing_fixture():
    rows = extract('2-0 pour Reims ce dimanche')
    assert len(rows) == 1
    assert rows[0]['statut'] == 'resolu'
    assert rows[0]['marche'] == 'score_exact'
    assert rows[0]['selection'] == '2-0'
    assert rows[0]['match_id'] is None


def test_decomposed_accents_do_not_shift_original_evidence_offsets():
    text = 'Cafe\u0301. Victoire de Reims @1,85'
    row = extract(text, preuve_permise='https://example.invalid/permission')[0]
    evidence = row['extraits_preuve'][0]
    assert text[evidence['start']:evidence['end']] == evidence['text']


def test_evidence_is_offsets_only_without_explicit_permission_and_is_deterministic():
    text = 'Préambule. Victoire de Reims @1,85'
    rows = extract(text)
    assert rows == extract(text)
    assert all(e['text'] is None for e in rows[0]['extraits_preuve'])
    row = extract(text, preuve_permise='https://example.invalid/permission')[0]
    e = row['extraits_preuve'][0]
    assert e['text'] == text[e['start']:e['end']]


def test_schema_rejects_invalid_records_with_and_without_jsonschema(monkeypatch):
    row = extract('Mon pari : nul')[0]
    real_import = builtins.__import__

    def without_jsonschema(name, *args, **kwargs):
        if name == 'jsonschema':
            raise ImportError('dependency intentionally absent')
        return real_import(name, *args, **kwargs)

    for fallback in (False, True):
        if fallback:
            monkeypatch.setattr(builtins, '__import__', without_jsonschema)
        validate_contribution(row)
        mutations = [
            {'statut': 'resolu', 'raison_non_resolu': 'contradiction'},
            {'statut': 'non_resolu', 'raison_non_resolu': None},
            {'cote_declaree': '1.85'}, {'unexpected': 1}, {'text_sha256': 'bad'},
            {'publication_url': 'relative/path'}, {'ligne': 'nan'},
            {'categorie': 'probabilite_explicite', 'probabilite': None},
            {'match_id': None, 'certitude_rapprochement': 'certaine'},
            {'observed_at': {'utc': 'bad', 'origin_timezone': 'UTC', 'origin_offset_seconds': 0}},
            {'extraits_preuve': [{'text_sha256': 'a' * 64, 'start': True, 'end': 2, 'text': None}]},
            {'extraits_preuve': [{'text_sha256': 'a' * 64, 'start': 0, 'end': 2, 'text': 'xx'}]},
            {'liens_reprise': [{'publication_id': 'other', 'certainty': 'attestee',
                               'evidence_sha256': None}]},
            {'reglement': {'rule_id': 'incomplete'}},
            {'cote_observee': '1.85', 'cote_observee_provenance': None},
            {'observed_at': {'utc': '2026-10-26T00:00:00+00:00', 'origin_timezone': 'UTC',
                             'origin_offset_seconds': 86400}},
        ]
        for changes in mutations:
            with pytest.raises(ValueError):
                validate_contribution(copy.deepcopy(row) | changes)
        missing = copy.deepcopy(row)
        del missing['source_id']
        with pytest.raises(ValueError):
            validate_contribution(missing)
        for text in ('Victoire de Reims @1.85', 'Double chance',
                     'Combiné : victoire de Reims + moins de 4,5 buts'):
            rows = extract(text, preuve_permise='https://example.invalid/permission')
            assert rows
            for emitted in rows:
                validate_contribution(emitted)


def test_evaluation_counts_false_positives_duplicates_and_missing_predictions(tmp_path):
    from robin.source_observatory.evaluate_extractor import evaluate_extractor

    corpus = [
        {'id': 'a', 'texte': 'Victoire de Reims @1.85'},
        {'id': 'b', 'texte': 'Double chance'},
        {'id': 'c', 'texte': 'Mon pari : nul'},
        {'id': 'd', 'texte': 'Pas de sélection lisible.'},
        {'id': 'e', 'texte': 'Plus de 2,5 buts\nPlus de 2,5 buts'},
    ]
    gold = [
        {'id': 'a', 'contributions': [
            {'statut': 'resolu', 'marche': '1N2', 'selection': 'reims', 'cote_declaree': '1.85'}]},
        {'id': 'b', 'contributions': [{'statut': 'non_resolu'}]},
        {'id': 'c', 'contributions': []},
        {'id': 'd', 'contributions': [
            {'statut': 'resolu', 'marche': '1N2', 'selection': 'away'}]},
        {'id': 'e', 'contributions': [
            {'statut': 'resolu', 'marche': 'total', 'selection': 'over', 'ligne': '2.5'}]},
    ]
    paths = [tmp_path / 'corpus.jsonl', tmp_path / 'gold.jsonl']
    for path, rows in zip(paths, (corpus, gold), strict=True):
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    result = evaluate_extractor(*paths)
    assert result['precision_marche_selection'] == 0.5
    assert result['rappel'] == pytest.approx(2 / 3)
    assert result['taux_non_resolu_correct'] == 1
    assert result['cotes_inventees'] == 0
    assert result['conformite_schema'] == 1
    assert result['c3']['statut'] == 'PARTIAL'
    assert result['effectifs']['textes'] == 5


def test_evaluation_empty_denominators_are_unknown_and_ids_must_match(tmp_path):
    from robin.source_observatory.evaluate_extractor import evaluate_extractor

    corpus, gold = tmp_path / 'corpus.jsonl', tmp_path / 'gold.jsonl'
    corpus.write_text('{"id":"a","texte":"Bonjour"}\n', encoding='utf-8')
    gold.write_text('{"id":"a","contributions":[]}\n', encoding='utf-8')
    result = evaluate_extractor(corpus, gold)
    assert result['precision_marche_selection'] is None
    assert result['rappel'] is None
    assert result['taux_non_resolu_correct'] is None
    assert result['conformite_schema'] is None
    gold.write_text('{"id":"wrong","contributions":[]}\n', encoding='utf-8')
    with pytest.raises(ValueError):
        evaluate_extractor(corpus, gold)


@pytest.mark.parametrize('quote', ['@1.85', '@1,85,'])
def test_duplicate_explicit_prices_are_false_positives_but_not_invented(tmp_path, quote):
    from robin.source_observatory.evaluate_extractor import evaluate_extractor

    corpus, gold = tmp_path / 'corpus.jsonl', tmp_path / 'gold.jsonl'
    corpus.write_text(json.dumps({'id': 'a', 'texte':
                      f'Victoire de Reims {quote}\nVictoire de Reims {quote}'}), encoding='utf-8')
    gold.write_text(json.dumps({'id': 'a', 'contributions': [dict(
        statut='resolu', marche='1N2', selection='reims', cote_declaree='1.85')]}), encoding='utf-8')
    result = evaluate_extractor(corpus, gold)
    assert result['precision_marche_selection'] == 0.5
    assert result['cotes_inventees'] == 0


def test_evaluator_detects_a_price_missing_from_the_source_and_schema_damage(tmp_path, monkeypatch):
    from robin.source_observatory import evaluate_extractor as evaluation

    corpus, gold = tmp_path / 'corpus.jsonl', tmp_path / 'gold.jsonl'
    corpus.write_text(json.dumps({'id': 'a', 'texte': 'Victoire de Reims @1.85'}), encoding='utf-8')
    gold.write_text(json.dumps({'id': 'a', 'contributions': [dict(
        statut='resolu', marche='1N2', selection='reims', cote_declaree='1.99')]}), encoding='utf-8')
    real_extract = evaluation.extract_contributions

    def damaged(*args, **kwargs):
        rows = real_extract(*args, **kwargs)
        rows[0]['cote_declaree'] = '1.99'
        rows[0]['extra'] = 'schema damage'
        return rows

    monkeypatch.setattr(evaluation, 'extract_contributions', damaged)
    result = evaluation.evaluate_extractor(corpus, gold)
    assert result['cotes_inventees'] == 1
    assert result['conformite_schema'] == 0


@pytest.mark.parametrize('bad_gold', [
    [{'id': 'a', 'contributions': [{'statut': 'unknown'}]}],
    [{'id': 'a', 'contributions': [{'statut': 'resolu', 'marche': 'total', 'selection': 'over'}]}],
    [{'id': 'a', 'contributions': []}, {'id': 'a', 'contributions': []}],
    [{'id': 'a'}],
])
def test_invalid_gold_is_rejected_instead_of_producing_favorable_metrics(tmp_path, bad_gold):
    from robin.source_observatory.evaluate_extractor import evaluate_extractor

    corpus, gold = tmp_path / 'corpus.jsonl', tmp_path / 'gold.jsonl'
    corpus.write_text('{"id":"a","texte":"Bonjour"}\n', encoding='utf-8')
    gold.write_text(''.join(json.dumps(row) + '\n' for row in bad_gold), encoding='utf-8')
    with pytest.raises(ValueError):
        evaluate_extractor(corpus, gold)
