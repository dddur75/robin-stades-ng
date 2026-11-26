"""Synthetic contract tests; fixtures contain no actual video or person data."""
import json
import unittest
from datetime import UTC, datetime

from robin.source_observatory.youtube_atom import parse_youtube_atom as PARSE

CHANNEL = 'UC' + 'A' * 22
OTHER = 'UC' + 'B' * 22
VIDEO = 'AbcdEF012_-'
NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)


def entry(title='Synthetic metadata only', description=None, **changes):
    values = dict(channel=CHANNEL, video=VIDEO, entry_id='yt:video:' + VIDEO,
                  author_channel=CHANNEL, watch=VIDEO,
                  published='2026-11-21T09:00:00Z', updated='2026-11-21T10:00:00Z')
    values.update(changes)
    media = (f'<media:group><media:description>{description}</media:description></media:group>'
             if description is not None else '')
    return (f'<entry><id>{values["entry_id"]}</id><yt:videoId>{values["video"]}</yt:videoId>'
            f'<yt:channelId>{values["channel"]}</yt:channelId><title>{title}</title>'
            f'<link rel="alternate" href="https://www.youtube.com/watch?v={values["watch"]}"/>'
            f'<author><name>Synthetic publisher NOT a person</name><uri>https://www.youtube.com/channel/'
            f'{values["author_channel"]}</uri></author><published>{values["published"]}</published>'
            f'<updated>{values["updated"]}</updated>{media}</entry>')


def feed(items=None, channel=CHANNEL):
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/">'
            f'<link rel="self" href="https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel}"/>'
            f'{entry() if items is None else items}</feed>').encode()


class AtomContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(PARSE), 'parse_youtube_atom prototype not implemented')

    def parse(self, body=None, **kwargs):
        return PARSE(feed() if body is None else body, requested_channel_id=CHANNEL,
                     source_id='SRC_023', observed_at=NOW, **kwargs)

    def test_notification_is_metadata_without_invented_choice_or_human(self):
        result = self.parse()
        self.assertEqual(len(result['publications']), 1)
        self.assertEqual(result['candidates'], [])
        pub = result['publications'][0]
        self.assertEqual(pub['url'], 'https://www.youtube.com/watch?v=AbcdEF012_-')
        self.assertEqual(pub['announcedAt'], '2026-11-21T09:00:00+00:00')
        self.assertEqual(pub['updatedAt'], '2026-11-21T10:00:00+00:00')
        self.assertEqual(pub['observedAt'], '2026-11-21T12:00:00+00:00')
        self.assertEqual(pub['authorStatus'], 'channel_publisher_unverified_human')
        self.assertFalse(pub['verifiedPreMatch'])
        self.assertEqual(result['admissions'], 0)
        self.assertEqual(result['sourceGrant'], 'NOT_GRANTED')
        self.assertEqual(result['provenance']['transport'], 'caller_supplied_unverified')

    def test_literal_title_choice_reuses_extractor_without_admission(self):
        result = self.parse(feed(entry(title='Mon pronostic : victoire PSG @ 1.85')))
        self.assertEqual(len(result['candidates']), 1)
        pick = result['candidates'][0]
        self.assertEqual((pick['market'], pick['selection'], pick['declaredOdds']), ('1N2', 'psg', '1.85'))
        self.assertEqual(pick['status'], 'unresolved_fixture')
        self.assertFalse(pick['verifiedPreMatch'])
        self.assertIsNone(pick['fixtureId'])
        self.assertIsNone(pick['kickoff'])
        self.assertEqual(pick['authorStatus'], 'channel_publisher_unverified_human')

    def test_optional_media_description_can_supply_literal_choice(self):
        result = self.parse(feed(entry(description='Mon pronostic : plus de 2.5 buts @ 1.90')))
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['market'], 'total')
        self.assertEqual(result['candidates'][0]['line'], '2.5')

    def test_no_prose_names_or_excerpts_retained(self):
        result = self.parse(feed(entry(title='Synthetic title SENTINEL',
                                      description='Mon pronostic : victoire PSG @ 1.85. PRIVATEPROSE')))
        serialized = json.dumps(result)
        for forbidden in ('Synthetic title', 'SENTINEL', 'PRIVATEPROSE', 'Synthetic publisher',
                          'extraits_preuve', 'description', 'title', '<entry', 'victoire PSG'):
            self.assertNotIn(forbidden, serialized)
        self.assertRegex(result['publications'][0]['authorId'], r'^author:[0-9a-f]{64}$')

    def test_cross_channel_or_video_spoofs_rejected(self):
        bodies = [feed(channel=OTHER), feed(entry(channel=OTHER)), feed(entry(author_channel=OTHER)),
                  feed(entry(entry_id='yt:video:XXXXXXXXXXX')), feed(entry(watch='XXXXXXXXXXX')),
                  feed(entry(video='bad')), feed().replace(b'https://www.youtube.com/watch', b'https://evil.invalid/watch'),
                  feed().replace(b'www.youtube.com/channel/', b'www.youtube.com.evil.invalid/channel/'),
                  feed().replace(b'?v=AbcdEF012_-', b'?v=AbcdEF012_-&amp;v=XXXXXXXXXXX'),
                  feed().replace(b'?channel_id=' + CHANNEL.encode(), b'?channel_id=' + OTHER.encode())]
        for body in bodies:
            with self.subTest(body_sha=__import__('hashlib').sha256(body).hexdigest()):
                with self.assertRaises(ValueError):
                    self.parse(body)

    def test_missing_conflicting_and_wrong_namespace_fields_rejected(self):
        for old, new in [
            (b'<yt:channelId>' + CHANNEL.encode() + b'</yt:channelId>', b''),
            (b'</author>', b'<uri>https://www.youtube.com/channel/' + OTHER.encode() + b'</uri></author>'),
            (b'<title>Synthetic metadata only</title>', b''),
            (b'<id>yt:video:' + VIDEO.encode() + b'</id>', b'<id>yt:video:' + VIDEO.encode() + b'</id><id>conflict</id>'),
            (b'http://www.w3.org/2005/Atom', b'http://evil.invalid/Atom'),
            (b'http://www.youtube.com/xml/schemas/2015', b'http://evil.invalid/yt'),
        ]:
            with self.subTest(old=old):
                with self.assertRaises(ValueError):
                    self.parse(feed().replace(old, new))

    def test_dates_are_aware_ordered_not_future_and_not_observation(self):
        for values in [dict(published='2026-11-21T09:00:00'), dict(updated='2026-11-21T10:00:00'),
                       dict(published='2026-11-22T09:00:00Z'), dict(updated='2026-11-22T10:00:00Z'),
                       dict(updated='2026-11-20T10:00:00Z'), dict(published='not a date')]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.parse(feed(entry(**values)))
        with self.assertRaises(ValueError):
            PARSE(feed(), requested_channel_id=CHANNEL, source_id='SRC_023', observed_at=NOW.replace(tzinfo=None))

    def test_identical_duplicates_dedup_and_conflicting_versions_fail(self):
        self.assertEqual(len(self.parse(feed(entry() + entry()))['publications']), 1)
        with self.assertRaises(ValueError):
            self.parse(feed(entry() + entry(title='Conflicting version')))

    def test_xml_entity_dtd_bom_and_size_rejected(self):
        for body in [b'<!DOCTYPE feed [<!ENTITY x SYSTEM "file:///private">]>' + feed(),
                     b'<!DOCTYPE html>' + feed(),
                     ('\ufeff<!DOCTYPE feed [<!ENTITY x "EXPANDED">]>' + feed().decode()).encode('utf-16'),
                     b'x' * 2_000_001, b'<feed>malformed', b'']:
            with self.subTest(size=len(body)):
                with self.assertRaises(ValueError):
                    self.parse(body)

    def test_channel_and_source_input_cannot_be_missing_or_malformed(self):
        for channel in ['', 'UCshort', 'UC' + 'A' * 23, 'UC' + '?' * 22, OTHER]:
            with self.subTest(channel=channel):
                with self.assertRaises(ValueError):
                    PARSE(feed(), requested_channel_id=channel, source_id='SRC_023', observed_at=NOW)
        with self.assertRaises(ValueError):
            PARSE(feed(), requested_channel_id=CHANNEL, source_id='', observed_at=NOW)

    def test_empty_valid_feed_has_no_publications_or_candidates(self):
        result = self.parse(feed(''))
        self.assertEqual(result['publications'], [])
        self.assertEqual(result['candidates'], [])

    def test_prefix_changes_do_not_change_publication_identity(self):
        first = self.parse()
        second = self.parse(feed().replace(b'xmlns:yt=', b'xmlns:video=').replace(b'<yt:', b'<video:').replace(b'</yt:', b'</video:'))
        self.assertEqual(first['publications'], second['publications'])

    def test_optional_feed_identifiers_cannot_contradict_requested_channel(self):
        for marker in [f'<id>yt:channel:{OTHER}</id>', f'<yt:channelId>{OTHER}</yt:channelId>']:
            with self.subTest(marker=marker):
                with self.assertRaises(ValueError):
                    self.parse(feed().replace(b'<link rel="self"', marker.encode() + b'<link rel="self"'))
        valid = feed().replace(b'<link rel="self"',
                              f'<id>yt:channel:{CHANNEL}</id>'.encode() + b'<link rel="self"')
        self.assertEqual(len(self.parse(valid)['publications']), 1)

    def test_google_sample_http_declared_links_canonicalize_without_http_topic(self):
        body = feed().replace(b'https://www.youtube.com/watch?', b'http://www.youtube.com/watch?')
        body = body.replace(b'https://www.youtube.com/channel/', b'http://www.youtube.com/channel/')
        try:
            result = self.parse(body)
        except ValueError as error:
            self.fail(f'Documented HTTP watch/author values must parse without a fetch: {error}')
        self.assertEqual(result['publications'][0]['url'], 'https://www.youtube.com/watch?v=AbcdEF012_-')
        self.assertEqual(result['provenance']['declaredLinkNormalization'], 'scheme_upgrade_only')
        self.assertEqual(result['sourceGrant'], 'NOT_GRANTED')
        topic_http = body.replace(b'https://www.youtube.com/xml/', b'http://www.youtube.com/xml/')
        with self.assertRaises(ValueError):
            self.parse(topic_http)
        for forbidden in ('http://www.youtube.com:80/watch?', 'http://admin@www.youtube.com/watch?',
                          'http://www.youtube.com.evil.invalid/watch?', 'http://youtube.com/watch?'):
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValueError):
                    self.parse(body.replace(b'http://www.youtube.com/watch?', forbidden.encode()))

    def test_choice_introduced_after_kickoff_is_never_backdated_to_publication(self):
        # Synthetic kickoff is 10:30Z; same publication at 09:00, choice added at 11:00.
        before = self.parse(feed(entry(updated='2026-11-21T10:00:00Z')))
        after = self.parse(feed(entry(updated='2026-11-21T11:00:00Z',
                                     description='Mon pronostic : victoire PSG @ 1.85')))
        self.assertEqual(before['candidates'], [])
        self.assertEqual(len(after['candidates']), 1)
        old_pub, new_pub = before['publications'][0], after['publications'][0]
        self.assertEqual(old_pub['id'], new_pub['id'])
        self.assertNotEqual(old_pub['contentSha256'], new_pub['contentSha256'])
        candidate = after['candidates'][0]
        self.assertEqual(candidate['announcedAt'], '2026-11-21T09:00:00+00:00')
        self.assertEqual(candidate['updatedAt'], '2026-11-21T11:00:00+00:00')
        self.assertEqual(candidate['observedAt'], '2026-11-21T12:00:00+00:00')
        self.assertFalse(candidate['verifiedPreMatch'])
        self.assertIsNone(candidate['kickoff'])
        self.assertEqual(after['admissions'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
