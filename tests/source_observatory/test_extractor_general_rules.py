"""Invented examples only: general grammar and price provenance regressions."""

import pytest

from .test_extractor import extract


@pytest.mark.parametrize('suffix', [
    '(2.5)', 'ligne (2.5)', 'probabilité 68.5 %', 'cote 68.5 %',
    '@68.5 %', 'mise (2.5)', 'cote 2.5 buts', 'cote 2.5 euros',
])
def test_numbers_require_unambiguous_price_syntax(suffix):
    rows = extract('Victoire de Dijon ' + suffix)
    assert rows
    assert all(row['cote_declaree'] is None for row in rows)


def test_unresolved_selection_never_acquires_a_price():
    row = extract('Mon pronostic : victoire du favori @2.17')[0]
    assert row['statut'] == 'non_resolu'
    assert row['cote_declaree'] is None


@pytest.mark.parametrize('text,market,selection,line', [
    ('Dijon gagne', '1N2', 'dijon', None),
    ('Mon choix : le FC Sion gagne demain', '1N2', 'fc sion', None),
    ('Dijon ou nul', 'double_chance', 'dijon ou draw', None),
    ('BTTS oui', 'btts', 'yes', None),
    ('BTTS non', 'btts', 'no', None),
    ('Les deux équipes marquent', 'btts', 'yes', None),
    ('Prono : O2,5', 'total', 'over', '2.5'),
    ('Prono : U3.5', 'total', 'under', '3.5'),
    ('3-2 pour Dijon', 'score_exact', '3-2', None),
    ('Pronostic : victoire de Dijon Dijon a inscrit neuf buts cette saison',
     '1N2', 'dijon', None),
])
def test_general_selection_grammar(text, market, selection, line):
    rows = extract(text)
    assert len(rows) == 1
    assert (rows[0]['statut'], rows[0]['marche'], rows[0]['selection'], rows[0]['ligne']) == (
        'resolu', market, selection, line)


@pytest.mark.parametrize('text', [
    "Si je devais parier, je jouerais la victoire de Dijon @2.17",
    "À titre d'exemple fictif : mon pronostic serait victoire de Dijon",
    'Supposons un pronostic : victoire de Dijon',
    "Qui choisit la victoire de Dijon ?",
    "Voici mes pronostics pour la prochaine journée.",
])
def test_hypothetical_predictions_and_headings_are_not_selections(text):
    assert extract(text) == []


@pytest.mark.parametrize('text', [
    'Victoire de Dijon ou de Sion @2.17',
    'Dijon gagne si son capitaine revient @2.17',
    'Combiné : Dijon x Sion @2.17',
    'Mon pronostic : victoire de Dijon et Sion @2.17',
    'Double chance : Dijon ou Sion',
])
def test_unsafe_alternatives_and_implicit_legs_stay_unresolved(text):
    rows = extract(text)
    assert rows
    assert all(row['statut'] == 'non_resolu' and row['cote_declaree'] is None for row in rows)


def test_inline_combination_keeps_its_written_price():
    rows = extract('Mon pari : "Victoire Dijon & + de 1,5 buts" (cote à 2,17)')
    assert len(rows) == 1
    assert (rows[0]['statut'], rows[0]['marche'], rows[0]['selection'],
            rows[0]['cote_declaree']) == ('resolu', 'combine', 'dijon & over 1.5', '2.17')


@pytest.mark.parametrize('separator', ['\n', ' '])
def test_table_rows_are_separate_predictions_despite_combination_heading(separator):
    text = ('Pronostics (combiné)' + separator +
            'Dijon vs Sion Over 1.5 68.5% @ 1.42' + separator +
            'Pau vs Caen Under 4.5 74.2% @ 1.24')
    rows = extract(text)
    assert [(r['statut'], r['marche'], r['selection'], r['ligne'], r['cote_declaree'])
            for r in rows] == [('resolu', 'total', 'over', '1.5', '1.42'),
                               ('resolu', 'total', 'under', '4.5', '1.24')]


def test_date_is_not_an_alternative_price_or_selection():
    row = extract('Notre pronostic : plus de 1,5 buts @1.42, relevée le 12/11 à 19h06')[0]
    assert row['statut'] == 'resolu'
    assert row['cote_declaree'] == '1.42'


def test_multiline_combination_remains_one_selection_with_total_quote():
    rows = extract('Combiné : victoire de Dijon\n+ moins de 4,5 buts\ncote totale 2,17')
    assert len(rows) == 1
    assert rows[0]['statut'] == 'resolu'
    assert rows[0]['selection'] == 'dijon & under 4.5'
    assert rows[0]['cote_declaree'] == '2.17'


@pytest.mark.parametrize('text', [
    'Victoire de Dijon @1.42 & plus de 1,5 buts',
    'Victoire de Dijon @1.42 & plus de 1,5 buts @1.42',
])
def test_leg_prices_are_not_the_combination_price_even_when_equal(text):
    rows = extract(text)
    assert rows
    assert all(row['cote_declaree'] is None for row in rows)


def test_prediction_label_does_not_turn_a_historical_result_into_a_pick():
    assert extract('Notre pronostic : victoire de Dijon hier @1.42') == []
