"""T7: no live HTTP, no provider APIs, synthetic publications only."""

import json
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from robin.source_observatory import collector, models
from robin.source_observatory.ranking import visit_coverage
from robin.source_observatory.store import AppendOnlyStore

from .test_conception import T


def source(**changes):
    return collector.PilotSource(**(dict(source_id='s1', name='test',
        url='https://example.invalid/ligue-1/', state='a_construire',
        access='rss_public (https://example.invalid/feed/)',
        terms='CGU : aucune clause anti-scraping ; robots.txt : ouvert',
        competitions='Ligue 1', audience='petit_auteur_inconnu') | changes))


def fixture():
    return collector.Fixture('test-match', T + timedelta(hours=14),
                              'https://example.invalid/calendrier')


def plan(sources=None):
    return collector.build_plan(sources or (source(),), (fixture(),),
                                 starts_at=T, registry_sha256='a' * 64)


def rss(text='Ligue 1 : victoire locale', date=''):
    return ('<rss><channel><item><link>https://example.invalid/post/1</link>'
        f'<title>Ligue 1</title><description>{text}</description>{date}'
        '</item></channel></rss>').encode()


class FakeHTTP:
    def __init__(self, *, robots=b'User-agent: *\nAllow: /\n', body=None, status=200):
        self.robots, self.body, self.status = robots, body if body is not None else rss(), status
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url.endswith('/robots.txt'):
            return collector.HttpResponse(200, self.robots, 'text/plain')
        if self.status == 0:
            raise OSError('timeout with private diagnostic that must not be persisted')
        return collector.HttpResponse(self.status, self.body, 'application/rss+xml')


def run(tmp_path, monkeypatch, *, sources=None, http=None, at=T, visit_plan=None, dry_run=False):
    monkeypatch.setenv('SOURCE_OBSERVATORY_RAW_DIR', str(tmp_path / 'outside-git'))
    sources = sources or (source(),)
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    result = collector.collect(visit_plan or plan(sources), sources, store,
        http=http or FakeHTTP(), clock=lambda: at, sleep=lambda seconds: None, dry_run=dry_run)
    return result, store


def receipts(store):
    return [e for e in store.entities() if isinstance(e, models.VisitReceipt)]


def test_plan_is_deterministic_every_six_hours_until_kickoff():
    a, b = source(), source(source_id='s2')
    first = collector.build_plan((a, b), (fixture(),), starts_at=T, registry_sha256='a' * 64)
    second = collector.build_plan((b, a), (fixture(),), starts_at=T, registry_sha256='a' * 64)
    assert first == second
    for sid in ('s1', 's2'):
        instants = [collector.parse_instant(v['planned_at']) for v in first['visits']
                    if v['source_id'] == sid]
        assert instants[0] == T
        assert max(y - x for x, y in zip(instants, instants[1:])) <= timedelta(hours=6)
        assert timedelta(0) < fixture().kickoff - instants[-1] <= timedelta(hours=6)
        assert all(t < fixture().kickoff for t in instants)
    assert len({v['visit_id'] for v in first['visits']}) == len(first['visits'])


def test_registry_only_selects_two_authorized_states():
    selected = collector.load_sources(Path('data/source_observatory/pilot_sources.csv'))
    assert selected and {s.state for s in selected} <= {'a_construire', 'manuel'}
    assert not any(s.source_id in ('SRC_033', 'SRC_034') for s in selected)


def test_dry_run_never_calls_http_or_journals_fake_success(tmp_path, monkeypatch):
    fake = FakeHTTP()
    result, store = run(tmp_path, monkeypatch, http=fake, dry_run=True)
    assert fake.calls == [] and store.entities() == ()
    assert result['succeeded'] == 0 and result['planned'] == len(plan()['visits'])
    assert result['coverage'] == '0' and not store.path.exists()
    assert not (tmp_path / 'outside-git').exists()


def test_ok_persists_only_metadata_hash_and_true_observation(tmp_path, monkeypatch):
    result, store = run(tmp_path, monkeypatch)
    receipt, = receipts(store)
    assert (receipt.status, receipt.completed_at) == ('ok', T)
    assert len(receipt.publication_ids) == 1
    versions = [e for e in store.entities() if isinstance(e, models.PublicationVersion)]
    v, = versions
    text = 'Ligue 1 : victoire locale'
    assert v.text_sha256 == sha256(text.encode()).hexdigest()
    assert v.announced_by_platform_at is None
    assert v.first_observed_by_robin_at == v.usable_at == T
    assert text not in store.path.read_text(encoding='utf-8')
    assert (tmp_path / 'outside-git' / (v.text_sha256 + '.txt')).read_text(encoding='utf-8') == text
    assert result['coverage'] == str(Decimal(1) / len(plan()['visits']))
    assert visit_coverage(store.entities()) == Decimal(1) / len(plan()['visits'])
    assert AppendOnlyStore(store.path).entities() == store.entities()


def test_platform_date_preserved_but_never_imputed(tmp_path, monkeypatch):
    fake = FakeHTTP(body=rss(date='<pubDate>Sun, 25 Oct 2026 17:00:00 +0000</pubDate>'))
    _, store = run(tmp_path, monkeypatch, http=fake)
    v = next(e for e in store.entities() if isinstance(e, models.PublicationVersion))
    assert v.announced_by_platform_at == T - timedelta(hours=1)
    assert v.first_observed_by_robin_at == T


@pytest.mark.parametrize('changes,reason', [
    ({'state': 'manuel'}, 'manuel'),
    ({'terms': 'CGU : collecte automatisee interdite ; robots.txt : Allow /'}, 'cgu'),
    ({'terms': 'CGU : scraping formellement interdit ; robots.txt : Allow /'}, 'cgu'),
    ({'terms': 'CGU : inconnu ; robots.txt : ouvert'}, 'cgu'),
    ({'terms': 'CGU : toute reproduction sans autorisation est interdite'}, 'cgu'),
    ({'terms': 'CGU : interdiction de collecte automatisee'}, 'cgu'),
])
def test_manual_or_forbidden_terms_do_not_fetch_even_robots(tmp_path, monkeypatch, changes, reason):
    fake = FakeHTTP()
    _, store = run(tmp_path, monkeypatch, sources=(source(**changes),), http=fake)
    assert fake.calls == []
    receipt, = receipts(store)
    assert receipt.status == 'echec' and reason in receipt.reason


def test_robots_denial_wins_over_source_registry_allow(tmp_path, monkeypatch):
    fake = FakeHTTP(robots=b'User-agent: *\nDisallow: /feed/\n')
    _, store = run(tmp_path, monkeypatch, http=fake)
    receipt, = receipts(store)
    assert receipt.status == 'bloque_robots' and len(fake.calls) == 1


def test_crawl_delay_is_observed_before_content_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_OBSERVATORY_RAW_DIR', str(tmp_path / 'outside-git'))
    fake = FakeHTTP(robots=b'User-agent: *\nAllow: /\nCrawl-delay: 5\n')
    waits = []
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    collector.collect(plan(), (source(),), store, http=fake, clock=lambda: T, sleep=waits.append)
    assert waits == [5]
    assert receipts(store)[0].status == 'ok'


@pytest.mark.parametrize('status', [0, 301, 401, 403, 429, 500])
def test_http_failures_or_redirects_never_look_like_success(tmp_path, monkeypatch, status):
    _, store = run(tmp_path, monkeypatch, http=FakeHTTP(status=status))
    receipt, = receipts(store)
    assert receipt.status == 'echec' and receipt.publication_ids == ()
    assert 'private diagnostic' not in store.path.read_text(encoding='utf-8')


def test_unknown_html_or_login_is_failure_not_empty_success(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch, http=FakeHTTP(body=b'<html>Login required</html>'))
    assert receipts(store)[0].status == 'echec'


def test_changed_hash_appends_and_unchanged_hash_does_not_duplicate(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch)
    original = store.path.read_bytes()
    for hours, text in [(6, 'Ligue 1 : texte corrige'), (12, 'Ligue 1 : texte corrige')]:
        collector.collect(plan(), (source(),), store, http=FakeHTTP(body=rss(text)),
            clock=lambda: T + timedelta(hours=hours), sleep=lambda seconds: None)
    versions = [e for e in store.entities() if isinstance(e, models.PublicationVersion)]
    assert len(versions) == 2 and len(receipts(store)) == 3
    a, b = versions
    assert b.previous_version_id == a.version_id and b.text_sha256 != a.text_sha256
    assert b.first_observed_by_robin_at == a.first_observed_by_robin_at == T
    assert b.modification_observed_at == b.usable_at == T + timedelta(hours=6)
    assert store.path.read_bytes().startswith(original)
    assert len(list((tmp_path / 'outside-git').glob('*.txt'))) == 2


def test_same_hash_returning_after_change_still_creates_new_version(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch)
    for hours, text in [(6, 'Ligue 1 : B'), (12, 'Ligue 1 : victoire locale')]:
        collector.collect(plan(), (source(),), store, http=FakeHTTP(body=rss(text)),
            clock=lambda: T + timedelta(hours=hours), sleep=lambda seconds: None)
    versions = [e for e in store.entities() if isinstance(e, models.PublicationVersion)]
    assert len(versions) == 3 and versions[0].text_sha256 == versions[2].text_sha256
    assert versions[2].previous_version_id == versions[1].version_id


def test_resuming_never_repeats_completed_visit(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch)
    before, fake = store.path.read_bytes(), FakeHTTP()
    collector.collect(plan(), (source(),), AppendOnlyStore(store.path), http=fake,
                      clock=lambda: T, sleep=lambda seconds: None)
    assert fake.calls == [] and store.path.read_bytes() == before


def test_missed_or_after_kickoff_visits_remain_failures_in_denominator(tmp_path, monkeypatch):
    fake = FakeHTTP()
    result, store = run(tmp_path, monkeypatch, http=fake, at=fixture().kickoff)
    assert fake.calls == [] and result['succeeded'] == 0
    assert len(receipts(store)) == len(plan()['visits'])
    assert result['coverage'] == '0'


def test_refuses_raw_directory_inside_git_before_http(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_OBSERVATORY_RAW_DIR', 'data/source_observatory/raw')
    fake = FakeHTTP()
    with pytest.raises(ValueError, match='Git|git'):
        collector.collect(plan(), (source(),), AppendOnlyStore(tmp_path / 'journal.jsonl'),
                          http=fake, clock=lambda: T)
    assert fake.calls == []


def test_missing_payload_environment_fails_before_network(tmp_path, monkeypatch):
    monkeypatch.delenv('SOURCE_OBSERVATORY_RAW_DIR', raising=False)
    fake = FakeHTTP()
    with pytest.raises(ValueError, match='SOURCE_OBSERVATORY_RAW_DIR'):
        collector.collect(plan(), (source(),), AppendOnlyStore(tmp_path / 'journal.jsonl'),
                          http=fake, clock=lambda: T)
    assert fake.calls == []


def test_feed_parser_supports_atom_public_youtube_without_transcript():
    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
    <id>yt:video:abc</id><title>Ligue 1 J9</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
    <published>2026-10-25T17:00:00Z</published></entry></feed>'''
    posts = collector.parse_publications(atom, 'https://www.youtube.com/feeds/videos.xml')
    assert len(posts) == 1 and posts[0].text == 'Ligue 1 J9'
    assert posts[0].announced_at == T - timedelta(hours=1)


def test_html_parser_hashes_public_article_only_and_keeps_date_absent():
    html = b'''<html><nav>menu</nav><article id="post-42"><p>Ligue 1 : A</p>
    <script>private_script</script></article><footer>footer</footer></html>'''
    post, = collector.parse_publications(html, 'https://example.invalid/pronos')
    assert 'Ligue 1 : A' in post.text
    assert all(word not in post.text for word in ('menu', 'private_script', 'footer'))
    assert post.announced_at is None and post.url.endswith('#post-42')


def test_wildcard_robots_and_most_specific_allow():
    text = 'User-agent: *\nDisallow: /*?lg=\nAllow: /public?lg=1$\n'
    assert not collector.robots_policy(text, 'https://example.invalid/tips?lg=fr')[0]
    assert collector.robots_policy(text, 'https://example.invalid/public?lg=1')[0]


def test_plan_json_is_written_once_and_is_reproducible(tmp_path):
    path = tmp_path / 'plan.json'
    collector.write_plan(path, plan())
    before = path.read_bytes()
    collector.write_plan(path, plan())
    assert path.read_bytes() == before and json.loads(before) == plan()
    altered = plan() | {'registry_sha256': 'b' * 64}
    with pytest.raises(ValueError):
        collector.write_plan(path, altered)


def test_plan_tampering_cannot_drop_planned_failures(tmp_path, monkeypatch):
    altered = plan() | {'visits': plan()['visits'][:1]}
    fake = FakeHTTP()
    with pytest.raises(ValueError, match='plan'):
        run(tmp_path, monkeypatch, http=fake, visit_plan=altered)
    assert fake.calls == []


def test_content_arriving_after_kickoff_cannot_be_observed_before_it(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_OBSERVATORY_RAW_DIR', str(tmp_path / 'outside-git'))
    times = iter([T])
    def clock():
        return next(times, fixture().kickoff + timedelta(seconds=1))
    store = AppendOnlyStore(tmp_path / 'journal.jsonl')
    collector.collect(plan(), (source(),), store, http=FakeHTTP(), clock=clock,
                      sleep=lambda seconds: None)
    assert not any(isinstance(e, models.PublicationVersion) for e in store.entities())
    assert all(e.completed_at > fixture().kickoff for e in receipts(store))


def test_naive_visit_clock_is_rejected_not_converted_to_local_time(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='timezone'):
        run(tmp_path, monkeypatch, at=T.replace(tzinfo=None))


def test_robots_html_challenge_is_fail_closed(tmp_path, monkeypatch):
    fake = FakeHTTP(robots=b'<html>Please login</html>')
    _, store = run(tmp_path, monkeypatch, http=fake)
    assert len(fake.calls) == 1 and receipts(store)[0].status == 'bloque_robots'


def test_receipt_cannot_be_replaced_to_turn_failed_visit_into_success(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch, http=FakeHTTP(status=500))
    receipt, = receipts(store)
    with pytest.raises(ValueError, match='completed|receipt'):
        store.append(models.VisitReceipt('second', receipt.visit_id, T, 'ok', (), None))


def test_version_cannot_be_backdated_after_collection_receipt(tmp_path, monkeypatch):
    _, store = run(tmp_path, monkeypatch)
    existing = next(e for e in store.entities() if isinstance(e, models.PublicationVersion))
    from dataclasses import replace
    with pytest.raises(ValueError):
        store.append(replace(existing, version_id='fake', usable_at=T - timedelta(seconds=1),
                             first_observed_by_robin_at=T - timedelta(seconds=1)))


def test_real_plan_matches_registry_and_requested_date_scope():
    sources = collector.load_sources(Path('data/source_observatory/pilot_sources.csv'))
    path = Path('data/source_observatory/visit_plan_20261031_v2.json')
    p = json.loads(path.read_text(encoding='utf-8'))
    fixtures = tuple(collector.Fixture(f['fixture_id'], collector.parse_instant(f['kickoff']),
                     f['evidence_url']) for f in p['fixtures'])
    registry = Path('data/source_observatory/pilot_sources.csv')
    assert p['registry_sha256'] == sha256(registry.read_bytes()).hexdigest()
    assert p == collector.build_plan(sources, fixtures,
        starts_at=collector.parse_instant(p['starts_at']), registry_sha256=p['registry_sha256'])
    assert all('2026-10-31' <= f['kickoff'][:10] <= '2026-11-02' for f in p['fixtures'])


def test_public_html5_doctype_is_not_mistaken_for_xml_entity_expansion():
    post, = collector.parse_publications(
        b'<!DOCTYPE html><html><article id="p1">Ligue 1</article></html>',
        'https://example.invalid/pronos')
    assert post.text == 'Ligue 1'


def test_xml_entities_remain_forbidden():
    with pytest.raises(ValueError):
        collector.parse_publications(
            b'<!DOCTYPE rss [<!ENTITY test "nested">]><rss><channel/></rss>',
            'https://example.invalid/feed/')
