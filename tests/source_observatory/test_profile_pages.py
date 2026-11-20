"""Native profile reading must not confuse unrelated widgets with personal access."""

import pytest


def page(inner: str, extra: str = "") -> str:
    return '<html><main id="tipster-profile"><h1>Dexter</h1>' + inner + '</main>' + extra + '</html>'


TABLE = '<table><tr><th>Événement</th><th>Sélection</th><th>Date</th></tr><tr><td>Équipe A - Équipe B</td><td>1-0</td><td>21/11/2026</td></tr></table>'


def project(body: str):
    from robin.source_observatory.profile_pages import project_profile_page

    return project_profile_page(body.encode(), 'text/html; charset=utf-8',
                                'https://notbetting.com/en/tipster/Dexter', 'Dexter')


def test_global_loading_and_dormant_captcha_do_not_hide_native_rows():
    result = project(page(TABLE, '<footer>Loading news</footer><script>var captcha = false;</script>'))
    assert result['status'] == 'NATIVE_ROWS_UNADMITTED'
    assert result['ownerMatched'] is True
    assert result['rows'][0]['fields'] == {'Événement': 'Équipe A - Équipe B', 'Sélection': '1-0', 'Date': '21/11/2026'}
    assert result['admittedChoices'] == 0


def test_prefix_match_is_not_author_attribution():
    result = project(page(TABLE).replace('<h1>Dexter</h1>', '<h1>Dexterous</h1>'))
    assert result['ownerMatched'] is False
    assert result['rows'] == []


def test_actual_challenge_page_is_rejected():
    with pytest.raises(ValueError, match='access challenge'):
        project('<html><title>Verify you are human</title><form id="challenge-form">Captcha</form></html>')


def test_loading_inside_personal_scope_retains_unknown_without_rows():
    result = project(page('<section aria-busy="true">Chargement des pronostics</section>'))
    assert result['status'] == 'PERSONAL_LOADING'
    assert result['rows'] == []


def test_global_recommendations_are_not_attributed_to_owner():
    result = project(page('<p>Aucun choix disponible</p>', '<aside>' + TABLE + '</aside>'))
    assert result['rows'] == []


def test_canonical_other_profile_is_rejected():
    with pytest.raises(ValueError, match='profile canonical'):
        project(page(TABLE, '<link rel="canonical" href="https://notbetting.com/en/tipster/SomeoneElse">'))


@pytest.mark.parametrize('content', [
    '<section class="recommendations"><h2>OtherUser</h2>' + TABLE + '</section>',
    '<blockquote>' + TABLE + '</blockquote>',
    '<article data-author="SomeoneElse">' + TABLE + '</article>',
])
def test_other_authors_and_citations_are_not_personal_native_rows(content):
    assert project(page(content))['rows'] == []


def test_visible_challenge_is_not_cancelled_by_owner_heading():
    with pytest.raises(ValueError, match='access challenge'):
        project(page('<form id="challenge-form">Verify you are human</form>' + TABLE))


def test_structural_diagnostic_exposes_no_inline_script_or_article_body():
    result = project(page('<div class="personal-picks">Loading</div>',
        '<script src="/static/profile.js"></script><script>secretText="not retained"</script>'))
    assert result['structure']['scripts'] == ['https://notbetting.com/static/profile.js']
    assert any(x['class'] == 'personal-picks' for x in result['structure']['markers'])
    assert 'not retained' not in str(result)


def test_script_roster_excludes_unsafe_or_derived_urls_and_unmatched_headings():
    result = project(page('<h2>Another author biography</h2>',
        '<script src="http://notbetting.com/a.js"></script>'
        '<script src="https://user:pass@notbetting.com/b.js"></script>'
        '<script src="/c.js#token"></script><script src="/d.js?q=x"></script>'))
    assert result['structure']['scripts'] == []
    assert 'Another author biography' not in str(result)
