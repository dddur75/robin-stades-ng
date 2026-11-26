from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from robin.source_observatory.connectors import (
    Journal,
    Response,
    build_profiles,
    collect_source,
    extract_feed,
    extract_html,
    permission,
    public_get,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


def test_exact_registry_scope_and_public_endpoints():
    profiles = build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv')
    assert len(profiles) == len({p['id'] for p in profiles}) == 57
    assert next(p for p in profiles if p['id'] == 'SRC_006')['adapter'] == 'rss_atom'
    assert next(p for p in profiles if p['id'] == 'SRC_041')['adapter'] == 'forum_html'
    assert next(p for p in profiles if p['id'] == 'SRC_031')['adapter'] == 'official_api_required'


def test_attribution_is_explicit_and_text_is_never_persisted():
    body = b'''<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
      <link>https://pensebet.com/prono-psg-lens</link><title>PSG - Lens</title>
      <dc:creator>Test tipster</dc:creator><pubDate>Wed, 18 Nov 2026 11:00:00 GMT</pubDate>
      <description>Mon pronostic : victoire PSG @ 1.85</description></item></channel></rss>'''
    publications, candidates = extract_feed(body, 'https://pensebet.com/feed/', 'SRC_006', NOW)
    assert len(publications) == len(candidates) == 1
    assert publications[0]['authorId'].startswith('author:')
    assert 'Test tipster' not in str(publications) + str(candidates)
    assert candidates[0]['status'] == 'unresolved_fixture'
    assert candidates[0]['verifiedPreMatch'] is False
    assert candidates[0]['declaredOdds'] == '1.85'
    assert 'victoire PSG' not in str(publications) + str(candidates)


def test_no_author_no_human_claim_and_dtd_refused():
    raw = b'<rss><channel><item><link>https://pensebet.com/a</link><title>Prono : victoire PSG</title></item></channel></rss>'
    pubs, picks = extract_feed(raw, 'https://pensebet.com/feed/', 'SRC_006', NOW)
    assert pubs[0]['authorId'] is None
    assert not picks
    with pytest.raises(ValueError):
        extract_feed(b'<!DOCTYPE rss><rss/>', 'https://pensebet.com/feed/', 'SRC_006', NOW)


@pytest.mark.parametrize('text', ['Automated scraping is prohibited.',
    'Terms of use. Automated access is not allowed on this website.',
    'Terms of use. No scraping or automated access is allowed.',
    'Toute reproduction est interdite sans autorisation.', 'Usage personnel et non commercial uniquement.'])
def test_terms_fail_closed(text):
    assert permission(text, 'rss_atom') != 'public_feed_facts_only'


def test_public_facts_policy_requires_current_terms_for_every_format():
    assert permission('Mentions légales. Editeur et hébergeur. Tous droits réservés.', 'rss_atom') == 'public_feed_facts_only'
    assert permission('Mentions légales. Editeur et hébergeur.', 'html_public') == 'public_page_facts_only'
    assert permission('', 'rss_atom') == 'terms_unverified'


def test_html_explicit_author_stable_version_and_no_invented_author():
    body = b'''<html><head><link rel="canonical" href="https://www.coteur.com/prono/a"/>
    <script type="application/ld+json">{"@type":"Article","url":"https://www.coteur.com/prono/a",
    "author":{"@type":"Person","name":"Synthetic Author"},"datePublished":"2026-11-18T10:00:00Z",
    "headline":"PSG Lens","articleBody":"Mon pronostic : victoire PSG @ 1.85"}</script></head><body></body></html>'''
    pubs, picks = extract_html(body, 'https://www.coteur.com/prono/a', 'SRC_002', NOW)
    assert len(pubs) == len(picks) == 1
    assert picks[0]['declaredOdds'] == '1.85'
    assert picks[0]['verifiedPreMatch'] is False
    assert 'Synthetic Author' not in str(pubs) + str(picks)
    without_author = body.replace(b'"author":{"@type":"Person","name":"Synthetic Author"},', b'')
    other_pubs, other_picks = extract_html(without_author, 'https://www.coteur.com/prono/a', 'SRC_002', NOW)
    assert other_pubs[0]['authorId'] is None
    assert not other_picks
    assert other_pubs[0]['contentSha256'] == pubs[0]['contentSha256']


def test_html_byline_is_scoped_to_its_article():
    raw = b'''<html><nav><a rel="author">Wrong Author</a></nav><article id="p1"><h1>Pronostic PSG Lens</h1>
      <a rel="author"><span>Synthetic Author</span></a><time datetime="2026-11-18T10:00:00Z"></time>
      <p>Mon pronostic : victoire PSG @ 1.85</p></article></html>'''
    pubs, picks = extract_html(raw, 'https://www.coteur.com/prono/a', 'SRC_002', NOW)
    assert pubs[0]['authorId'] is not None
    assert len(picks) == 1
    assert 'Synthetic Author' not in str(pubs) + str(picks)


def test_html_phase_requires_authorizing_decision_and_exact_predecessor():
    import runpy
    from hashlib import sha256

    from robin.source_observatory.connectors import canonical
    authorized = runpy.run_path(str(ROOT / 'cockpit/scripts/run-tipster-connectors.py'))['phase_authorized']
    phase = dict(predecessorHead='old-head', decisionId='correction')
    previous = dict(kind='RUN_FINISHED', hash='old-head')
    decision = dict(kind='DECISION', hash='decision-hash', responsible='C0', decisionId='correction',
                    predecessorHead='old-head', phaseSha256=sha256(canonical(phase)).hexdigest(), decision='PASS_AND_HOLD')
    assert authorized(phase, [previous, decision])
    assert not authorized(phase, [previous, decision | {'decision': 'FAIL_AND_STOP'}])
    assert not authorized(phase, [previous, decision | {'predecessorHead': 'wrong-head'}])


def make_journal(tmp_path, *, maximum=4):
    return Journal(tmp_path, {'mission_id': 'test', 'authorized_stages': ['E1', 'E2'],
        'maximum_stage': 'E2', 'external_effects': {'https_get_max': maximum, 'per_source_max': 4},
        'compute_budget': {'max_bytes': 2_000_000}, 'time_budget': {'seconds': 600},
        'source_hash': '0' * 64, 'expires_at': (NOW + timedelta(hours=1)).isoformat()}, now=lambda: NOW)


def test_reservation_survives_restart_and_tampering_stops(tmp_path):
    journal = make_journal(tmp_path, maximum=1)
    journal.reserve('SRC_006', 'https://pensebet.com/robots.txt')
    with pytest.raises(ValueError, match='budget'):
        make_journal(tmp_path, maximum=1).reserve('SRC_006', 'https://pensebet.com/feed/')
    path = tmp_path / 'events.jsonl'
    path.write_bytes(path.read_bytes().replace(b'SRC_006', b'SRC_007'))
    with pytest.raises(ValueError, match='integrity'):
        make_journal(tmp_path, maximum=1)


def test_robots_denial_never_reads_content(tmp_path):
    profile = next(p for p in build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv') if p['id'] == 'SRC_006')
    calls = []
    def get(url):
        calls.append(url)
        return Response(200, b'User-agent: *\nDisallow: /\n', 'text/plain', None)
    journal = make_journal(tmp_path)
    result = collect_source(profile, journal, get=get, sleep=lambda _: None)
    assert result['status'] == 'robots_denied'
    assert len(calls) == 1
    assert snapshot(tmp_path)['counts']['verifiedPreMatch'] == 0


def test_successful_real_path_keeps_receipts_and_separates_picks(tmp_path):
    profile = next(p for p in build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv') if p['id'] == 'SRC_006')
    def get(url):
        if url.endswith('robots.txt'):
            return Response(200, b'User-agent: *\nAllow: /\n', 'text/plain', None)
        if url.endswith('/terms'):
            return Response(200, b'<html>Mentions legales. Editeur et hebergeur.</html>', 'text/html', None)
        return Response(200, b'<rss><channel><item><link>https://pensebet.com/a</link><title>Actualite</title></item></channel></rss>', 'application/rss+xml', None)
    result = collect_source(profile, make_journal(tmp_path), get=get, sleep=lambda _: None)
    assert result['status'] == 'collected'
    view = snapshot(tmp_path)
    assert view['counts']['requests'] == 3
    assert view['counts']['publications'] == 1
    assert view['counts']['verifiedPreMatch'] == 0
    assert len(view['receipts']) == 3


def test_private_and_mixed_dns_refused_before_tcp(monkeypatch):
    import socket
    for addresses in [['127.0.0.1'], ['8.8.8.8', '192.168.1.1']]:
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in addresses])
        with pytest.raises(ValueError, match='non-public DNS'):
            public_get('https://pensebet.com/feed/')


def test_dns_has_effective_deadline(monkeypatch):
    import socket
    import time
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: time.sleep(.1))
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='DNS deadline'):
        public_get('https://pensebet.com/feed/', timeout=.005)
    assert time.monotonic() - started < .08


def test_source_budget_and_expiration_between_requests(tmp_path):
    journal = make_journal(tmp_path, maximum=10)
    for _ in range(4):
        journal.reserve('SRC_006', 'https://pensebet.com/feed/')
    with pytest.raises(ValueError, match='budget'):
        journal.reserve('SRC_006', 'https://pensebet.com/feed/')
    journal.now = lambda: NOW + timedelta(hours=2)
    with pytest.raises(ValueError, match='expired'):
        journal.reserve('SRC_007', 'https://mediapronos.com/feed/')


def test_challenge_never_qualifies_as_terms():
    assert permission('Just a moment. Verify you are human. Terms and conditions.', 'rss_atom') == 'terms_unverified'


def test_ambiguous_outputs_are_never_counted_as_selections(tmp_path):
    journal = make_journal(tmp_path)
    journal.append('SOURCE_FINISHED', sourceId='SRC_006', status='collected', publications=[],
        candidates=[dict(id='ambiguous', market='indetermine', extractionStatus='non_resolu')])
    before = (tmp_path / 'events.jsonl').read_bytes()
    view = snapshot(tmp_path)
    assert view['counts']['candidates'] == 0
    assert view['counts']['unresolvedExtractions'] == 1
    assert view['counts']['verifiedPreMatch'] == 0
    assert view['sources'][0]['candidates'] == []
    assert before == (tmp_path / 'events.jsonl').read_bytes()


def test_html_correction_reuses_exact_witness_without_resetting_budget(tmp_path):
    profile = next(p for p in build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv') if p['id'] == 'SRC_002')
    journal = make_journal(tmp_path)
    journal.reserve('SRC_002', profile['robotsUrl'])
    journal.reserve('SRC_002', profile['termsUrl'])
    calls, waits = [], []
    def get(url):
        calls.append(url)
        if url == profile['termsUrl']:
            return Response(200, b'<html>Mentions legales. Editeur et hebergeur.</html>', 'text/html', None)
        return Response(200, b'<html><article id="p1"><h1>PSG Lens</h1><p>Mon pronostic : victoire PSG</p></article></html>', 'text/html', None)
    witness = dict(sourceId='SRC_002', allowedUrls=[profile['endpoint'], profile['termsUrl']],
                   expiresAt=(NOW + timedelta(hours=1)).isoformat())
    result = collect_source(profile, journal, get=get, sleep=waits.append, robots_witness=witness)
    assert result['status'] == 'collected'
    assert calls == [profile['termsUrl'], profile['endpoint']]
    assert all(wait == 60 for wait in waits)
    assert snapshot(tmp_path)['counts']['requests'] == 4
    with pytest.raises(ValueError, match='budget'):
        journal.reserve('SRC_002', profile['endpoint'])


def test_html_witness_expiring_during_pacing_never_sends_get(tmp_path):
    profile = next(p for p in build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv') if p['id'] == 'SRC_002')
    journal = make_journal(tmp_path)
    journal.reserve('SRC_002', profile['termsUrl'])
    calls = []
    def sleep(seconds):
        journal.now = lambda: NOW + timedelta(seconds=60)
    witness = dict(sourceId='SRC_002', allowedUrls=[profile['endpoint'], profile['termsUrl']],
                   expiresAt=(NOW + timedelta(seconds=30)).isoformat())
    result = collect_source(profile, journal, get=calls.append, sleep=sleep, robots_witness=witness)
    assert not calls
    assert result['status'] == 'read_failed'
    assert snapshot(tmp_path)['counts']['requests'] == 1


def test_cli_existing_writer_lock_prevents_any_reservation(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    main = runpy.run_path(str(ROOT / 'cockpit/scripts/run-tipster-connectors.py'))['main']
    monkeypatch.setattr(sys, 'argv', ['runner', '--directory', str(tmp_path), '--init'])
    main()
    capsys.readouterr()
    (tmp_path / 'run.lock').write_text('other-writer', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['runner', '--directory', str(tmp_path), '--run', '--source-id', 'SRC_025'])
    with pytest.raises(FileExistsError):
        main()
    assert not (tmp_path / 'events.jsonl').exists()
    assert (tmp_path / 'run.lock').read_text() == 'other-writer'


def test_cli_pin_mutation_is_refused_before_lock_or_network(tmp_path, monkeypatch, capsys):
    import json
    import runpy
    import sys
    main = runpy.run_path(str(ROOT / 'cockpit/scripts/run-tipster-connectors.py'))['main']
    monkeypatch.setattr(sys, 'argv', ['runner', '--directory', str(tmp_path), '--init'])
    main()
    capsys.readouterr()
    path = tmp_path / 'plan.json'
    plan = json.loads(path.read_bytes())
    plan['codePins']['src/robin/source_observatory/collector.py'] = '0' * 64
    path.write_text(json.dumps(plan), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['runner', '--directory', str(tmp_path), '--run', '--source-id', 'SRC_025'])
    with pytest.raises(ValueError, match='pinned source/code mismatch'):
        main()
    assert not (tmp_path / 'run.lock').exists()
    assert not (tmp_path / 'events.jsonl').exists()


def test_incomplete_run_cannot_reset_elapsed_budget(tmp_path):
    journal = make_journal(tmp_path)
    journal.append('RUN_STARTED')
    journal.now = lambda: NOW + timedelta(minutes=11)
    journal.append('RUN_STARTED')
    with pytest.raises(ValueError, match='time budget'):
        journal.reserve('SRC_006', 'https://pensebet.com/feed/')


def test_slow_headers_are_interrupted_by_wall_clock(monkeypatch):
    import http.client
    import socket
    import threading
    import time
    stopped = threading.Event()
    class FakeSocket:
        def settimeout(self, value):
            pass
        def connect(self, address):
            assert address == ('8.8.8.8', 80)
        def shutdown(self, how):
            stopped.set()
        def close(self):
            pass
    class FakeConnection:
        sock = None
        def request(self, *a, **k):
            pass
        def getresponse(self):
            assert stopped.wait(.2)
            raise OSError('closed')
        def close(self):
            pass
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))])
    monkeypatch.setattr(socket, 'socket', lambda *a: FakeSocket())
    monkeypatch.setattr(http.client, 'HTTPConnection', lambda *a, **k: FakeConnection())
    started = time.monotonic()
    with pytest.raises(TimeoutError, match='transfer deadline'):
        public_get('http://pensebet.com/feed/', timeout=.01)
    assert time.monotonic() - started < .15


@pytest.mark.parametrize('link_header', [None, '<https://hub.example.test/>; rel="hub"'])
def test_public_get_preserves_link_header_for_protocol_discovery(monkeypatch, link_header):
    import http.client
    import socket

    class FakeSocket:
        def settimeout(self, value):
            pass
        def connect(self, address):
            assert address == ('8.8.8.8', 80)
        def shutdown(self, how):
            pass
        def close(self):
            pass

    class FakeResponse:
        status = 200
        body = b'<feed/>'
        def read1(self, size):
            chunk, self.body = self.body, b''
            return chunk
        def getheader(self, name, default=None):
            return {'Content-Type': 'application/atom+xml', 'Link': link_header}.get(name, default)

    class FakeConnection:
        sock = None
        def request(self, method, target, headers):
            assert method == 'GET' and target == '/feed/'
            assert headers['Accept-Encoding'] == 'identity'
        def getresponse(self):
            return FakeResponse()
        def close(self):
            pass

    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))])
    monkeypatch.setattr(socket, 'socket', lambda *a: FakeSocket())
    monkeypatch.setattr(http.client, 'HTTPConnection', lambda *a, **k: FakeConnection())
    result = public_get('http://pensebet.com/feed/', timeout=1)
    assert result.body == b'<feed/>'
    assert result.content_type == 'application/atom+xml' and result.location is None
    assert result.link_header == link_header
    assert Response(200, b'', 'application/atom+xml', None).link_header is None


@pytest.mark.parametrize('text', [
    'Conditions: usage personnel et non commercial uniquement.',
    'Terms: personal use and non-commercial purposes only.',
])
def test_personal_context_is_distinct_from_explicit_ban(text):
    assert permission(text, 'rss_atom') == 'personal_context_required'
    assert permission(text + ' Automated scraping is prohibited.', 'rss_atom') == 'permission_required'


def test_personal_context_does_not_open_content_fetch(tmp_path):
    profile = next(p for p in build_profiles(ROOT / 'data/source_observatory/pilot_sources.csv')
                   if p['id'] == 'SRC_006')
    calls = []
    def get(url):
        calls.append(url)
        if url.endswith('robots.txt'):
            return Response(200, b'User-agent: *\nAllow: /\n', 'text/plain', None)
        assert url == profile['termsUrl']
        return Response(200, b'Terms: personal use and non-commercial purposes only.', 'text/html', None)
    result = collect_source(profile, make_journal(tmp_path), get=get, sleep=lambda _: None)
    assert result['status'] == 'personal_context_required'
    assert calls == [profile['robotsUrl'], profile['termsUrl']]
