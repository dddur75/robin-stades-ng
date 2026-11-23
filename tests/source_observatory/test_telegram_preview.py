import unittest
from datetime import datetime, timezone

from robin.source_observatory.telegram_preview import parse_preview_messages

NOW = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)

def message(i='1', date='2026-11-23T10:00:00Z', href=None, text='synthetic'):
    href = href or 'https://t.me/demo/' + i
    return f'<div class="tgme_widget_message" data-post="demo/{i}"><div class="tgme_widget_message_text">{text}</div><a href="{href}"><time datetime="{date}">ignored</time></a></div>'

def parse(s):
    return parse_preview_messages(s.encode(), channel='demo', observed_at=NOW)

class Tests(unittest.TestCase):

    def test_complete(self):
        x = parse(message() + message('2'))
        self.assertEqual(x['status'], 'STRUCTURED_SYNTHETIC_CONTRACT')
        self.assertEqual(len(x['messages']), 2)
        self.assertFalse(x['admissible'])
        self.assertEqual(x['messages'][0]['attribution'], 'CHANNEL')

    def test_contradictory(self):
        self.assertEqual(parse(message(href='https://t.me/demo/9'))['messages'], [])

    def test_missing(self):
        self.assertEqual(parse(message().replace('<time datetime="2026-11-23T10:00:00Z">ignored</time>', ''))['messages'], [])

    def test_duplicates(self):
        self.assertEqual(parse(message() + message())['messages'], [])

    def test_naive_future(self):
        self.assertEqual(parse(message(date='2026-11-23T10:00:00'))['messages'], [])
        self.assertEqual(parse(message(date='2026-11-24T10:00:00Z'))['messages'], [])

    def test_inert(self):
        x = parse('<!--' + message('8') + '--><script>' + message('9') + '</script>' + message(text='ok<style>poison</style><script>poison</script>tail'))
        self.assertEqual(len(x['messages']), 1)
        self.assertEqual(x['messages'][0]['text'], 'oktail')

    def test_ambiguous_markup(self):
        self.assertEqual(parse(message()[:-6])['messages'], [])
        self.assertEqual(parse(message().replace('data-post="demo/1"', 'data-post="demo/1" data-post="demo/2"'))['messages'], [])

    def test_foreign(self):
        self.assertEqual(parse(message().replace('data-post="demo/1"', 'data-post="other/1"'))['messages'], [])

    def test_bounds(self):
        self.assertEqual(parse(message(text='x' * 8193))['messages'], [])
        self.assertEqual(parse_preview_messages(b'x' * 2097153, channel='demo', observed_at=NOW)['messages'], [])

    def test_ordinary_html_envelope(self):
        wrapped = '<!doctype html><html><head><meta charset="utf-8"><title>Demo</title><link rel="icon" href="/icon"></head><body><img src="/avatar"><svg><path d="M0 0"/></svg>' + message() + '</body></html>'
        self.assertEqual(len(parse(wrapped)['messages']), 1)

    def test_unrelated_links_are_not_date_permalinks(self):
        body = message(text='See <a href="https://example.test/news">context</a>')
        body = body.replace('<div class="tgme_widget_message_text">', '<a href="https://t.me/demo">channel</a><a href="https://t.me/demo/1">media</a><div class="tgme_widget_message_text">')
        row = parse(body)
        self.assertEqual(len(row['messages']), 1)
        self.assertEqual(row['messages'][0]['text'], 'See context')

    def test_inert_context_message_is_not_publication(self):
        for tag in ['template', 'textarea', 'title', 'xmp', 'svg', 'foreignobject']:
            with self.subTest(tag=tag):
                self.assertEqual(parse('<' + tag + '>' + message() + '</' + tag + '>')['messages'], [])

    def test_svg_selfclosing_requires_svg_ancestry(self):
        self.assertEqual(parse('<path />' + message())['messages'], [])

    def test_plaintext_and_hidden_contexts(self):
        self.assertEqual(parse('<plaintext></plaintext>' + message())['messages'], [])
        self.assertEqual(parse('<div hidden>' + message() + '</div>')['messages'], [])
