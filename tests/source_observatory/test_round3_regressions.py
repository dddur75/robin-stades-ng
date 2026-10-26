"""Round 3 pilot counterexamples, with synthetic public content only."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from robin.source_observatory import collector, models, schema_validation, service
from robin.source_observatory.store import AppendOnlyStore

from .test_collector import FakeHTTP, receipts, run, source
from .test_conception import H, T, contribution, match, rule, seed, version
from .test_extractor import extract
from .test_round2_regressions import combo_evidence


@pytest.mark.parametrize('agent', ['RobinSourceObservatory/1.0', 'RobinSourceObservatory*',
                                  'Robin*Observatory'])
def test_r3_1_targeted_agent_denial_never_fetches_content(tmp_path, monkeypatch, agent):
    http = FakeHTTP(robots=f'User-agent: {agent}\nDisallow: /\nUser-agent: *\nAllow: /'.encode())
    _, store = run(tmp_path, monkeypatch, http=http)
    assert receipts(store)[0].status == 'bloque_robots'
    assert len(http.calls) == 1


@pytest.mark.parametrize('terms', [
    'pas de flux RSS public, interdiction de scraping',
    'aucune autorisation accordee, interdiction extraction',
    'collecting not permitted', 'scraping forbidden', 'usage personnel uniquement',
    'usage non-commercial',
])
def test_r3_1_contractual_denial_never_fetches(tmp_path, monkeypatch, terms):
    http = FakeHTTP()
    _, store = run(tmp_path, monkeypatch, sources=(source(terms=terms),), http=http)
    assert http.calls == []
    assert receipts(store)[0].status == 'echec'


def test_r3_2_article_without_identity_cannot_inherit_old_observation(tmp_path, monkeypatch):
    http = FakeHTTP(body=b'<html><article>Ligue 1 : new publication</article></html>')
    _, store = run(tmp_path, monkeypatch, http=http)
    assert receipts(store)[0].status == 'echec'
    assert not any(isinstance(e, models.PublicationVersion) for e in store.entities())


@pytest.mark.parametrize('link', ['<a rel="bookmark">Post</a>',
    '<a rel="bookmark" href="">Post</a>',
    '<a rel="bookmark" href="https://example.invalid/ligue-1/">Post</a>'])
def test_r3_2_bookmark_must_not_point_to_the_listing(link):
    with pytest.raises(ValueError, match='permalink'):
        collector.parse_publications(f'<html><article>{link}Ligue 1</article></html>'.encode(),
                                     source().url)


@pytest.mark.parametrize('secondary', ['datetime="2026-10-31T20:45:00+01:00"', ''])
def test_r3_2_secondary_time_does_not_replace_publication_date(secondary):
    body = ('<html><article id="a"><time datetime="2026-10-25T17:00:00Z">Published</time>'
            f'<p>Ligue 1 <time {secondary}>Kickoff</time></p></article></html>').encode()
    post, = collector.parse_publications(body, source().url)
    assert post.announced_at == T - timedelta(hours=1)


def test_r3_2_kickoff_time_alone_is_not_publication_time():
    body = b'''<html><article id="a">Ligue 1
        <time datetime="2026-10-31T20:45:00+01:00">Coup d'envoi</time></article></html>'''
    post, = collector.parse_publications(body, source().url)
    assert post.announced_at is None


def test_r3_2_initial_version_cannot_disguise_first_observation():
    with pytest.raises(ValueError, match='initial|first'):
        version(modification_observed_at=T + timedelta(hours=1), usable_at=T + timedelta(hours=1))


def test_r3_2_observed_odds_cannot_precede_modified_content(tmp_path):
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    seed(store)
    later = T + timedelta(hours=1)
    store.append(version('v2', previous_version_id='v1', modification_observed_at=later,
                         usable_at=later))
    with pytest.raises(ValueError, match='odds'):
        store.append(contribution('c2', version_id='v2', observed_at=later,
            cote_observee=Decimal('2'), cote_observee_at=T,
            cote_observee_provenance='https://example.invalid/odds'))


def test_r3_3_removed_selection_survives_shift_of_remaining_selection():
    loser = contribution(selection='away', selection_key='selection-1')
    winner = contribution('winner', selection_key='selection-2', marche='total',
        selection='over', ligne=Decimal('1.5'), reglement=rule('total'))
    later = T + timedelta(minutes=30)
    v2 = version('v2', previous_version_id='v1', modification_observed_at=later, usable_at=later)
    shifted = replace(winner, contribution_id='shifted', version_id='v2',
                      selection_key='selection-1', observed_at=later)
    retained = service.pre_match_contributions([version(), loser, winner, v2, shifted],
                                               T + timedelta(hours=2))
    assert {c.contribution_id for c in retained} == {'c1', 'shifted'}


def test_r3_3_combo_cannot_repeat_the_same_match():
    c, m, r, evidence = combo_evidence()
    evidence = [replace(e, match_id='m1') if isinstance(e, (models.Contribution, models.MatchMarket))
                else e for e in evidence]
    assert not service.evaluate(c, m, r, odds_basis='cote_declaree', leg_evidence=evidence).evaluable


def test_r3_3_combo_version_must_precede_each_leg_kickoff():
    c, m, r, evidence = combo_evidence()
    later = T + timedelta(hours=2)
    c = replace(c, version_id='v2')
    m = replace(m, version_id='v2')
    evidence.extend([version('v2', previous_version_id='v1', modification_observed_at=later,
                             usable_at=later), c])
    assert not service.evaluate(c, m, r, odds_basis='cote_declaree', leg_evidence=evidence).evaluable


@pytest.mark.parametrize('text', [
    'Mon pari : victoire de Nice & plus de 1,5 buts @1.42',
    'Mon pari : victoire de Nice & (plus de 1,5 buts) @1.42',
    'Mon pari : victoire de Nice & "plus de 1,5 buts" @1.42',
])
def test_r3_4_last_leg_price_is_never_combination_price(text):
    row, = extract(text)
    assert row['marche'] == 'combine'
    assert row['cote_declaree'] is None
    assert row['categorie'] == 'selection_sans_cote'


@pytest.mark.parametrize('text,market,line,score', [
    ('Mon pronostic : victoire de Toulouse cote 1.85', '1N2', None, models.MatchScore(home=2, away=0)),
    ('Handicap Toulouse -1,5', 'handicap', Decimal('-1.5'), models.MatchScore(home=2, away=0)),
    ('Mon pari : qualification de Toulouse', 'qualification', None,
     models.MatchScore(home=2, away=0, qualified='home')),
])
def test_r3_4_named_team_settles_through_resolved_selection(text, market, line, score):
    row, = extract(text)
    c = contribution(selection=row['selection'], marche=market, ligne=line, reglement=rule(market))
    result = service.settle(c, match(c, selection_id='home'), result_id='r',
        observed_at=T + timedelta(hours=4), evidence_sha256=H, score=score)
    assert result.outcome == 'gagne'


def test_r3_4_unresolved_match_cannot_settle():
    c = contribution()
    m = match(c, statut='non_resolu', raison_non_resolu='identite_absente',
              match_id=None, market_id=None, selection_id=None)
    result = service.settle(c, m, result_id='r', observed_at=T + timedelta(hours=4),
        evidence_sha256=H, score=models.MatchScore(home=2, away=0))
    assert result.outcome == 'en_attente'


def test_r3_4_settlement_cannot_precede_kickoff():
    c = contribution()
    with pytest.raises(ValueError, match='kickoff'):
        service.settle(c, match(c), result_id='r', observed_at=T, evidence_sha256=H,
                       score=models.MatchScore(home=2, away=0))


def test_r3_4_settled_result_requires_documented_rule():
    with pytest.raises(ValueError, match='rule'):
        models.Result('r', 'mm', 'gagne', T + timedelta(hours=4), H)


def test_r3_4_store_refuses_settled_result_for_unresolved_match(tmp_path):
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    c = contribution()
    seed(store, c)
    m = match(c, statut='non_resolu', raison_non_resolu='identite_absente',
              match_id=None, market_id=None, selection_id=None)
    store.append(m)
    with pytest.raises(ValueError, match='resolved|resolu'):
        store.append(models.Result('r', m.match_market_id, 'gagne', T + timedelta(hours=4),
                                   H, c.reglement))


def test_r3_5_atom_media_description_retains_actual_prediction():
    body = b'''<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:media="http://search.yahoo.com/mrss/"><entry><title>Ligue 1</title>
        <link href="https://example.invalid/video"/><media:group>
        <media:description>Mon pronostic : victoire de Nice cote 1.85</media:description>
        </media:group></entry></feed>'''
    post, = collector.parse_publications(body, source().url)
    assert 'victoire de Nice cote 1.85' in post.text


def test_r3_5_atom_title_keeps_league_scope_when_description_has_only_pick(tmp_path, monkeypatch):
    body = b'''<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:media="http://search.yahoo.com/mrss/"><entry><title>Ligue 1</title>
        <link href="https://example.invalid/video"/><media:group>
        <media:description>Mon pronostic : victoire de Nice cote 1.85</media:description>
        </media:group></entry></feed>'''
    _, store = run(tmp_path, monkeypatch, http=FakeHTTP(body=body))
    assert len(receipts(store)[0].publication_ids) == 1
    post, = collector.parse_publications(body, source().url)
    assert 'Ligue 1' in post.text and 'victoire de Nice cote 1.85' in post.text


def test_r3_5_empty_encoded_content_falls_back_to_description():
    body = b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><item><link>https://example.invalid/post</link><content:encoded>   </content:encoded>
        <description>Ligue 1 : victoire de Nice</description></item></channel></rss>'''
    post, = collector.parse_publications(body, source().url)
    assert post.text == 'Ligue 1 : victoire de Nice'


def test_r3_5_full_plan_keeps_manual_sources_and_future_visits_in_denominator(tmp_path, monkeypatch):
    sources = (source(), source(source_id='manual', state='manuel'))
    result, store = run(tmp_path, monkeypatch, sources=sources)
    assert result['planned'] == 8 and result['succeeded'] == 1
    assert Decimal(result['coverage']) == Decimal('0.125')
    assert service.visit_coverage(store.entities()) == Decimal('0.125')


def test_r3_5_direct_negation_of_restriction_does_not_block_public_feed():
    endpoint, reason = collector._endpoint(source(terms="pas d'interdiction sur le flux RSS public"))
    assert endpoint == 'https://example.invalid/feed/' and reason is None


class NamelessZone(tzinfo):
    def utcoffset(self, dt):
        return timedelta(0)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return None


@pytest.mark.parametrize('zone', [timezone(timedelta(hours=1), 'Europe/Paris'), NamelessZone()])
def test_r3_6_undecodable_timestamp_rejected_before_any_write(tmp_path, zone):
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    store.append(models.Source('s1', 'test', source().url))
    before = store.path.read_bytes()
    invalid = datetime(2026, 7, 1, 12, tzinfo=zone)
    with pytest.raises(ValueError):
        store.append(models.Visit('v', 's1', invalid, invalid, True))
    assert store.path.read_bytes() == before
    assert len(AppendOnlyStore(store.path).entities()) == 1


def test_r3_6_second_payload_failure_cannot_leave_unreceipted_publication(tmp_path, monkeypatch):
    raw = tmp_path / 'outside-git'
    raw.mkdir()
    second = 'Ligue 1 : second'
    (raw / (models.text_fingerprint(second) + '.txt')).write_text('corrupted', encoding='utf-8')
    body = b'''<rss><channel>
        <item><link>https://example.invalid/first</link><description>Ligue 1 : first</description></item>
        <item><link>https://example.invalid/second</link><description>Ligue 1 : second</description></item>
        </channel></rss>'''
    _, store = run(tmp_path, monkeypatch, http=FakeHTTP(body=body))
    assert receipts(store)[0].status == 'echec'
    assert not any(isinstance(e, (models.Publication, models.PublicationVersion)) for e in store.entities())


def test_r3_7_direct_evaluation_cannot_inflate_anteriority():
    c = contribution(categorie='information_factuelle', observed_at=T + timedelta(minutes=119))
    m = match(c, contribution_usable_at=T)
    r = models.Result('r', m.match_market_id, 'gagne', T + timedelta(hours=4), H, c.reglement)
    evaluation = service.evaluate(c, m, r, odds_basis='cote_declaree')
    assert not evaluation.evaluable and evaluation.anteriority_seconds is None


def test_r3_7_fallback_rejects_float_metadata_offsets():
    with pytest.raises(ValueError, match='type'):
        schema_validation._fallback(0.0, {'type': 'integer'}, {})


def test_r3_6_frozen_plan_kickoffs_match_original_paris_source():
    original = json.loads(Path('data/source_observatory/kickoffs_20261031.json').read_text(encoding='utf-8'))
    frozen = json.loads(Path('data/source_observatory/visit_plan_20261031.json').read_text(encoding='utf-8'))
    expected_utc = ['2026-10-31T16:15:00+00:00', '2026-10-31T19:45:00+00:00',
        '2026-10-31T19:45:00+00:00', '2026-10-31T19:45:00+00:00',
        '2026-11-01T14:00:00+00:00', '2026-11-01T16:15:00+00:00',
        '2026-11-01T19:45:00+00:00']
    actual = {f['fixture_id']: f['kickoff'] for f in frozen['fixtures']}
    for fixture, utc in zip(original['fixtures'], expected_utc, strict=True):
        local = collector.parse_instant(fixture['kickoff'])
        assert local.utcoffset() == timedelta(hours=1)
        assert local.astimezone(ZoneInfo(original['timezone'])).isoformat() == fixture['kickoff']
        assert actual[fixture['fixture_id']] == utc == models.instant_text(local)


@pytest.mark.parametrize('early', [True, False])
def test_r3_4_combination_cannot_settle_before_kickoff_or_without_identity(early):
    c, m, r, _ = combo_evidence()
    if not early:
        m = replace(m, statut='non_resolu', raison_non_resolu='identite_absente',
                    match_id=None, market_id=None, selection_id=None)
    def settle():
        return service.settle_combined(c, m, result_id='r',
            observed_at=T if early else T + timedelta(hours=7), evidence_sha256=H, legs=r.legs)
    if early:
        with pytest.raises(ValueError, match='kickoff'):
            settle()
    else:
        assert settle().outcome == 'en_attente'
