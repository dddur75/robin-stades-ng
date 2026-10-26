"""Synthetic documents only; no captured provider text or network access."""

import json
from datetime import UTC, datetime

import pytest

from robin.source_observatory import collector as c

URL = 'https://example.invalid/pronostics/'
DATE = '2026-10-26T12:00:00Z'


@pytest.mark.parametrize('encoding,prefix,content_type', [
    ('cp1252', '', 'text/html; charset=windows-1252'),
    ('iso-8859-1', '<meta charset="iso-8859-1">', ''),
    ('cp1252', '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">', ''),
    ('cp1252', '', ''),
    ('utf-16', '', 'text/html; charset=windows-1252'),
    ('utf-8-sig', '', ''),
])
def test_declared_charset_bom_and_legacy_fallback(encoding, prefix, content_type):
    body = (prefix + '<article id="p">Ligue 1 : victoire annoncée</article>').encode(encoding)
    post, = c.parse_publications(body, URL, content_type=content_type)
    assert post.text == 'Ligue 1 : victoire annoncée'


def test_dated_link_cards_preserve_scope_and_omit_private_profiles():
    body = f'''<nav><a href="/account">Private profile</a></nav><ul>
    <li class="row"><a class="topictitle" href="/match-a">Ligue 1 : A</a>
    <time datetime="{DATE}"></time><p>Victoire locale</p>
    <span class="username">Private commenter</span></li>
    <li class="row"><h2><a href="/match-b">Ligue 1 : B</a></h2>
    <time datetime="2026-10-27"></time><p>Match nul</p></li></ul>'''.encode()
    a, b = c.parse_publications(body, URL)
    assert a.url == 'https://example.invalid/match-a'
    assert 'Victoire locale' in a.text and 'Private' not in a.text
    assert a.announced_at == datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert b.url == 'https://example.invalid/match-b' and b.announced_at is None


def test_article_heading_link_is_permalink_without_bookmark():
    post, = c.parse_publications(b'<article><h2><a href="/pick">Ligue 1 : A</a>'
                                b'</h2><p>Victoire locale</p></article>', URL)
    assert post.url == 'https://example.invalid/pick'
    assert post.announced_at is None


@pytest.mark.parametrize('metadata', [
    '<link rel="canonical" href="/pick">',
    '<meta property="og:url" content="/pick">', '',
    '<link rel="canonical" href="https://elsewhere.invalid/pick">',
])
def test_single_dated_prediction_uses_safe_identity(metadata):
    body = (metadata + f'<main><h1>Pronostic Ligue 1 : A</h1><time datetime="{DATE}">'
            'Publié</time><p>Victoire locale</p></main>').encode()
    post, = c.parse_publications(body, URL)
    assert post.url.startswith('https://example.invalid/')
    if metadata and 'elsewhere' not in metadata:
        assert post.url == 'https://example.invalid/pick'
    else:
        assert post.url.startswith(URL + '#publication-')
    assert post.announced_at == datetime(2026, 10, 26, 12, tzinfo=UTC)


def test_generated_article_anchors_are_stable_and_distinct():
    body = f'''<article><h2>Ligue 1 : A</h2><time datetime="{DATE}"></time><p>A</p></article>
    <article><h2>Ligue 1 : B</h2><time datetime="{DATE}"></time><p>B</p></article>'''.encode()
    a, b = c.parse_publications(body, URL)
    changed = c.parse_publications(body.replace(b'<p>A</p>', b'<p>Updated</p>'), URL)
    assert a.url != b.url and a.url == changed[0].url


@pytest.mark.parametrize('wrapper', ['Article', 'NewsArticle', 'ItemList'])
def test_jsonld_static_articles_and_lists_without_authors(wrapper):
    article = {'@type': 'NewsArticle', 'headline': 'Ligue 1 : A', 'url': '/pick',
               'datePublished': DATE, 'articleBody': '<p>Victoire <b>locale</b></p>',
               'author': {'name': 'Private author'}}
    data = ({'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'item': article}]}
            if wrapper == 'ItemList' else article | {'@type': wrapper})
    body = ('<script type="application/ld+json">' + json.dumps(data) + '</script>'
            '<script>throw new Error("must never execute")</script>').encode()
    post, = c.parse_publications(body, URL)
    assert post.url == 'https://example.invalid/pick'
    assert 'Victoire locale' in post.text and '<' not in post.text
    assert 'Private' not in post.text and 'throw' not in post.text


def test_feed_html_is_cleaned_without_script_or_comment_author():
    body = b'''<rss><channel><item><link>/pick</link><description><![CDATA[
    <p>Ligue 1 : victoire locale</p><script>private()</script>
    <div class="comment-author">Private author</div>]]></description></item></channel></rss>'''
    post, = c.parse_publications(body, URL)
    assert post.text == 'Ligue 1 : victoire locale'


@pytest.mark.parametrize('body', [
    b'<main><h1>Pronostic Ligue 1</h1><p>Sans date</p></main>',
    b'<nav><a href="/pick">Ligue 1</a><time datetime="2026-10-26T12:00:00Z"></time></nav>',
    b'<script type="application/ld+json">{"@type":"Comment","text":"Private"}</script>',
    b'<article hidden id="x">Ligue 1 : private</article>',
    b'<article id="x" itemprop="comment">Ligue 1 : private</article>',
])
def test_unstructured_undated_navigation_and_private_content_are_not_posts(body):
    with pytest.raises(ValueError):
        c.parse_publications(body, URL)


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-32'])
def test_dtd_and_entities_refused_in_every_encoding(encoding):
    body = '<!DOCTYPE rss [<!ENTITY p "unsafe">]><rss><channel/></rss>'.encode(encoding)
    with pytest.raises(ValueError, match='unsupported'):
        c.parse_publications(body, URL)


def test_bounds_apply_before_decoding_or_tree_building():
    with pytest.raises(ValueError):
        c.parse_publications(b'x' * (c.MAX_BYTES + 1), URL)
    with pytest.raises(ValueError):
        c.parse_publications(b'<div>' * 300 + b'content' + b'</div>' * 300, URL)


def test_collector_forwards_response_charset(tmp_path, monkeypatch):
    from .test_collector import FakeHTTP, receipts, run

    class LegacyHTTP(FakeHTTP):
        def get(self, url):
            response = super().get(url)
            if url.endswith('/robots.txt'):
                return response
            return c.HttpResponse(200, '<article id="x">Ligue 1 : annoncé</article>'.encode('cp1252'),
                                  'text/html; charset=windows-1252')

    _, store = run(tmp_path, monkeypatch, http=LegacyHTTP())
    assert receipts(store)[0].status == 'ok' and len(receipts(store)[0].publication_ids) == 1


def test_forum_post_has_profile_keeps_body_but_removes_profile_and_author():
    body = b'''<div id="p42" class="post has-profile"><dl class="postprofile">
    <dt>Private name</dt></dl><div class="content">Ligue 1 : victoire locale</div></div>'''
    post, = c.parse_publications(body, URL)
    assert 'victoire locale' in post.text and 'Private' not in post.text
    assert post.url == URL + '#p42' and post.announced_at is None


def test_repeated_cards_same_link_are_one_publication_not_a_source_failure():
    body = (f'<div><h2><a href="/pick">Ligue 1 : A</a></h2>'
            f'<time datetime="{DATE}"></time><p>Victoire locale</p></div>').encode()
    post, = c.parse_publications(body * 2, URL)
    assert post.url == 'https://example.invalid/pick'


def test_event_time_is_date_evidence_but_never_announced_time():
    body = (f'<div><h2><a href="/pick">Ligue 1 : A</a></h2>'
            f'<time class="match-time" datetime="{DATE}">20:30</time>'
            '<p>Victoire locale</p></div>').encode()
    post, = c.parse_publications(body, URL)
    assert post.announced_at is None


def test_private_contact_and_profile_links_are_omitted():
    body = b'''<article id="x"><p>Ligue 1 : victoire locale</p>
    <a href="mailto:private@example.invalid">Private contact</a>
    <a href="/memberlist.php?mode=viewprofile&amp;u=42">Private name</a></article>'''
    post, = c.parse_publications(body, URL)
    assert post.text == 'Ligue 1 : victoire locale' and post.url.endswith('#x')


def test_jsonld_modified_date_never_replaces_missing_publication_date():
    data = {'@type': 'Article', 'headline': 'Ligue 1 : A', 'url': '/pick',
            'dateModified': DATE, 'author': 'Private author'}
    post, = c.parse_publications(('<script type="application/ld+json">' + json.dumps(data)
                                  + '</script>').encode(), URL)
    assert post.announced_at is None


def test_atom_xhtml_content_keeps_markup_until_private_content_is_removed():
    body = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="/pick"/>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">
    <p>Ligue 1 : victoire locale</p><script>private()</script>
    <span class="comment-author">Private name</span></div></content></entry></feed>'''
    post, = c.parse_publications(body, URL)
    assert post.text == 'Ligue 1 : victoire locale'


def test_canonical_precedes_generated_or_element_anchor_for_single_article():
    body = b'''<link rel="canonical" href="/pick"><article id="x">
    <h1>Pronostic Ligue 1</h1><p>Victoire locale</p></article>'''
    post, = c.parse_publications(body, URL)
    assert post.url == 'https://example.invalid/pick' and post.announced_at is None


def test_other_domain_and_credentials_cannot_become_article_permalink():
    body = (f'<article><h2><a href="https://elsewhere.invalid/pick">Ligue 1 : A</a></h2>'
            f'<time datetime="{DATE}"></time><p>Victoire locale</p></article>').encode()
    post, = c.parse_publications(body, URL)
    assert post.url.startswith(URL + '#publication-')
    body = body.replace(b'https://elsewhere.invalid', b'https://user:secret@example.invalid')
    post, = c.parse_publications(body, URL)
    assert post.url.startswith(URL + '#publication-') and 'secret' not in post.url


def test_structured_paywall_and_dtd_external_subset_are_rejected():
    with pytest.raises(ValueError):
        c.parse_publications(b'''<script type="application/ld+json">{"@type":"Article",
        "headline":"Ligue 1", "url":"/paid", "isAccessibleForFree":false}</script>''', URL)
    with pytest.raises(ValueError, match='unsupported'):
        c.parse_publications(b'<!DOCTYPE html SYSTEM "https://elsewhere.invalid/dtd">'
                             b'<article id="x">Ligue 1</article>', URL)


@pytest.mark.parametrize('date', ['tomorrow', '2026-99-99', ''])
def test_invalid_dates_cannot_authorize_generated_publication_identity(date):
    body = (f'<article><h2>Pronostic Ligue 1</h2><time datetime="{date}"></time>'
            '<p>Victoire locale</p></article>').encode()
    with pytest.raises(ValueError):
        c.parse_publications(body, URL)
    data = {'@type': 'Article', 'headline': 'Ligue 1 : A', 'datePublished': date}
    with pytest.raises(ValueError):
        c.parse_publications(('<script type="application/ld+json">' + json.dumps(data)
                              + '</script>').encode(), URL)


def test_conflicting_repeated_card_dates_are_unknown():
    body = (f'<div><h2><a href="/pick">Ligue 1 : A</a></h2>'
            f'<time datetime="{DATE}"></time><p>Victoire locale</p></div>').encode()
    post, = c.parse_publications(body + body.replace(b'12:00:00Z', b'14:00:00Z'), URL)
    assert post.announced_at is None
