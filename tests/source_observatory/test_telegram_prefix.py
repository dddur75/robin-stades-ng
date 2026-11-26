"""Synthetic prefix limits and atomic refusal; no network or native messages."""
import unittest
from datetime import datetime, timezone

from robin.source_observatory.telegram_prefix import parse_preview_prefix
from robin.source_observatory.telegram_preview import parse_preview_messages

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def message(number: int, channel: str = 'sample') -> str:
    return (f'<div class="tgme_widget_message" data-post="{channel}/{number}">'
            '<div class="tgme_widget_message_text">SYNTHETIC</div>'
            f'<a href="https://t.me/{channel}/{number}">'
            '<time datetime="2026-01-01T00:00:00Z"></time></a></div>')


class PrefixTests(unittest.TestCase):
    def test_stops_before_eleventh_and_preserves_full_parser(self) -> None:
        body = ('<main>' + ''.join(message(n) for n in range(1, 12)) + '</main>').encode()
        result = parse_preview_prefix(body, channel='sample', observed_at=NOW)
        self.assertEqual(result['prefixCount'], 10)
        self.assertTrue(result['suffixHTMLUnexamined'])
        self.assertIsNone(result['totalMessageCount'])
        self.assertEqual(result['stopReason'], 'PREFIX_LIMIT_REACHED')
        self.assertEqual(parse_preview_messages(body, channel='sample', observed_at=NOW)['messages'], [])

    def test_completed_input_and_false_gates(self) -> None:
        result = parse_preview_prefix(message(1).encode(), channel='sample', observed_at=NOW)
        self.assertEqual(result['prefixCount'], 1)
        self.assertEqual(result['stopReason'], 'END_OF_INPUT')
        self.assertFalse(result['suffixHTMLUnexamined'])
        for key in ('sourceReady', 'admissible', 'personIdentityVerified', 'nativeMarkupContractProven'):
            self.assertFalse(result[key])

    def test_refusal_before_limit_is_atomic(self) -> None:
        body = (message(1) + message(1)).encode()
        result = parse_preview_prefix(body, channel='sample', observed_at=NOW)
        self.assertEqual(result['messages'], [])
        self.assertEqual(result['prefixCount'], 0)
        self.assertEqual(result['reason'], 'MESSAGE_ID')

    def test_only_suffix_after_complete_n_is_unexamined(self) -> None:
        body = ('<main>' + message(1) + '<script>bad</script>').encode()
        result = parse_preview_prefix(body, channel='sample', observed_at=NOW, limit=1)
        self.assertEqual(result['prefixCount'], 1)
        self.assertTrue(result['suffixHTMLUnexamined'])
        strict = parse_preview_prefix(body, channel='sample', observed_at=NOW, limit=2)
        self.assertEqual(strict['messages'], [])

    def test_incomplete_and_future_dates_refused(self) -> None:
        for body in (message(1)[:-6], message(1).replace('2026-01-01', '2027-01-01')):
            self.assertEqual(parse_preview_prefix(body.encode(), channel='sample', observed_at=NOW)['messages'], [])

    def test_input_limits(self) -> None:
        for limit in (0, 11, True):
            result = parse_preview_prefix(message(1).encode(), channel='sample', observed_at=NOW, limit=limit)
            self.assertEqual(result['reason'], 'INPUT_CONTRACT')
        self.assertEqual(parse_preview_prefix(b'\xff', channel='sample', observed_at=NOW)['reason'], 'UTF8')
        self.assertEqual(parse_preview_prefix(b'x' * 2097153, channel='sample', observed_at=NOW)['reason'], 'INPUT_CONTRACT')

    def test_calls_do_not_change_parent_class_or_other_channel(self) -> None:
        import robin.source_observatory.telegram_preview as parent
        before = parent.Preview
        one = parse_preview_prefix(message(1).encode(), channel='sample', observed_at=NOW, limit=1)
        other = parse_preview_prefix(message(2, 'second').encode(), channel='second', observed_at=NOW)
        self.assertEqual(one['messages'][0]['sourceId'], 'sample/1')
        self.assertEqual(other['messages'][0]['sourceId'], 'second/2')
        self.assertIs(parent.Preview, before)


if __name__ == '__main__':
    unittest.main()
