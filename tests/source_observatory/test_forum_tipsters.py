from datetime import UTC, datetime, timedelta

import pytest

from robin.source_observatory.forum_tipsters import extract_posts, qualify_posts

NOW = datetime(2026, 11, 19, 9, 34, tzinfo=UTC)
URL = 'https://legruppetto.fr/forum/viewtopic.php?f=21&t=24850&start=240'
FIX = [{'id': 'nice-psg', 'publicationWindowStart': '2026-11-09', 'label': 'Nice vs Paris Saint-Germain', 'homeAliases': ['Nice'], 'awayAliases': ['PSG'], 'kickoff': (NOW + timedelta(days=2)).isoformat()}]


def post(content, author='Alice', pid='p123'):
    return f'<div class="post" id="{pid}"><dl class="postprofile"><a class="username">Wrong</a></dl><div class="postbody"><p class="author">par <a class="username" href="memberlist.php?u=1">{author}</a> » 18 Nov 2026, 15:56</p><div class="content">{content}</div></div></div>'.encode()


def picks(body):
    return qualify_posts(extract_posts(body, URL, 'SRC_058', NOW), FIX)


def test_local_author_score_and_observation_prove_pre_match():
    result = picks(post('Journée 11<br>Nice - PSG 1-3'))
    assert len(result) == 1
    assert result[0]['authorLabel'] == 'Alice'
    assert result[0]['selection'] == '1-3'
    assert result[0]['publishedAt'] is None
    assert result[0]['sourceUrl'].endswith('#p123')
    assert 'memberlist' not in str(result)


@pytest.mark.parametrize('content', [
    '<blockquote><cite>Bob</cite>Nice - PSG 1-3</blockquote>Bravo',
    '<div class="signature">Nice - PSG 1-3</div>Bonjour',
    'Résultats Journée 11<br>Nice - PSG 1-3',
    'Classement<br>Nice - PSG 1-3',
    'Nice - PSG',
    'PSG - Nice 1-3',
    'Nice - PSG 1-3<br>Nice - PSG 2-2',
])
def test_quotes_results_missing_reversed_or_conflicting_choices_excluded(content):
    assert picks(post(content)) == []


def test_no_borrowed_global_author_or_unknown_identity():
    assert picks(post('Nice - PSG 1-3', author='')) == []
    assert picks(post('Nice - PSG 1-3', author='Anonymous')) == []


def test_no_retroactive_or_ambiguous_fixture():
    posts = extract_posts(post('Nice - PSG 1-3'), URL, 'SRC_058', NOW)
    assert qualify_posts(posts, [{**FIX[0], 'kickoff': NOW.isoformat()}]) == []
    assert qualify_posts(posts, [*FIX, {**FIX[0], 'id': 'second'}]) == []


def test_host_topic_source_allowlist_and_explicit_timezone():
    with pytest.raises(ValueError):
        extract_posts(post('Nice - PSG 1-3'), 'https://example.com/viewtopic.php?t=24850', 'SRC_058', NOW)
    with pytest.raises(ValueError):
        extract_posts(post('Nice - PSG 1-3'), URL, 'SRC_038', NOW)
    with pytest.raises(ValueError):
        extract_posts(post('Nice - PSG 1-3'), URL, 'SRC_058', NOW.replace(tzinfo=None))

def test_exact_inert_phpbb_doctype_only():
    declared = b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">'
    assert len(picks(declared + post('Nice - PSG 1-3'))) == 1
    with pytest.raises(ValueError):
        picks(b'<!DOCTYPE html [<!ENTITY stolen SYSTEM "file:///secret">]>' + post('Nice - PSG 1-3'))

def test_legacy_phpbb_author_profile_anchor_without_css_class():
    body = post('Nice - PSG 1-3').replace(b'class="username" href="memberlist.php?u=1"', b'href="./memberlist.php?mode=viewprofile&amp;u=1"')
    assert picks(body)[0]['authorLabel'] == 'Alice'

@pytest.mark.parametrize('choice', ['Paris FC 2-0 SCO', 'PFC - SCO 3 - 0', 'Paris 2 Angers 0'])
def test_sco_score_positions_with_exact_known_aliases(choice):
    fixture = {**FIX[0], 'id': 'pfc-sco', 'label': 'Paris FC vs Angers', 'homeAliases': ['Paris FC', 'PFC', 'Paris'], 'awayAliases': ['SCO', 'Angers']}
    rows = extract_posts(post(choice), 'http://forum.sco1919.com/viewtopic.php?t=13259&start=300', 'SRC_038', NOW)
    assert len(qualify_posts(rows, [fixture])) == 1

def test_historical_post_cannot_be_mapped_to_future_fixture():
    historical = post('Nice - PSG 1-3').replace(b'18 Nov 2026', b'18 Nov 2025')
    assert picks(historical) == []


def test_missing_civil_date_is_not_guessed_from_retrieval():
    assert picks(post('Nice - PSG 1-3').replace(b'18 Nov 2026, 15:56', b'')) == []

def test_missing_or_tampered_local_bundle_fails_closed(tmp_path):
    from robin.source_observatory.public_collection import read_collection
    with pytest.raises((ValueError, FileNotFoundError)):
        read_collection(tmp_path)

@pytest.mark.parametrize('content', ['Je ne joue pas Nice - PSG 1-3', 'Le dernier match Nice - PSG 1-3', 'Si je devais choisir : Nice - PSG 1-3'])
def test_negative_historical_and_hypothetical_statements_are_not_choices(content):
    assert picks(post(content)) == []

@pytest.mark.parametrize('content', ['Bob pronostique Nice - PSG 1-3', 'Le modèle donne Nice - PSG 1-3'])
def test_reporting_another_forecaster_is_not_own_choice(content):
    assert picks(post(content)) == []
