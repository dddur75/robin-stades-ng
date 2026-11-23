"""Pure CHANNEL prefix profile; every message remains unqualified."""
import re
from datetime import datetime, timezone

from .telegram_prefix import PrefixResult, _PrefixPreview
from .telegram_preview import Refusal

NORMALIZATION_PROFILE = 'TG_ASCII_USERNAME_CANONICAL_V1'
SEMANTIC_PROFILE = 'TG_INHERITED_TEXT_REGION_V1'
REFERENCE_PROVENANCE = 'DERIVED_CANONICAL_CONFIGURED_ASCII_USERNAME_NOT_RAW_SOURCE_SPELLING'
_REDUNDANT_TEXT_TOKEN = re.compile(r'(?<!\S)tgme_widget_message_text(?!\S)')


class _ChannelPrefixPreview(_PrefixPreview):
    def __init__(self, channel: str, observed: datetime, limit: int) -> None:
        super().__init__(channel.lower(), observed, limit)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(attrs) != len(dict(attrs)):
            super().handle_starttag(tag, attrs)
            return
        original = dict(attrs)
        wrapper = 'tgme_widget_message' in (original.get('class') or '').split()
        inherited_text = bool(self.stack and self.stack[-1][1])
        copied: list[tuple[str, str | None]] = []
        for name, value in attrs:
            pattern = None
            head = ''
            if name == 'data-post' and wrapper:
                pattern = r'([A-Za-z][A-Za-z0-9_]{0,63})/([1-9][0-9]{0,19})'
            elif name == 'href' and tag == 'a':
                pattern = r'https://t[.]me/([A-Za-z][A-Za-z0-9_]{0,63})/([1-9][0-9]{0,19})'
                head = 'https://t.me/'
            if pattern is not None and isinstance(value, str):
                match = re.fullmatch(pattern, value)
                if match is not None and match.group(1).lower() == self.channel:
                    value = head + self.channel + '/' + match.group(2)
            if name == 'class' and inherited_text and isinstance(value, str):
                value = _REDUNDANT_TEXT_TOKEN.sub('', value)
            copied.append((name, value))
        super().handle_starttag(tag, copied)


def parse_channel_prefix(
    body: bytes, *, channel: str, observed_at: datetime, limit: int = 10
) -> PrefixResult:
    result = PrefixResult(
        schemaVersion='telegram-prefix-private-v1', status='UNPROVEN', reason=None,
        messages=[], sourceReady=False, admissible=False,
        personIdentityVerified=False, nativeMarkupContractProven=False,
        prefixCount=0, totalMessageCount=None, suffixHTMLUnexamined=False,
        stopReason='REFUSED',
    )
    if (type(body) is not bytes or len(body) > 2097152
            or not isinstance(channel, str)
            or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', channel) is None
            or not isinstance(observed_at, datetime) or observed_at.utcoffset() is None
            or type(limit) is not int or not 1 <= limit <= 10):
        result['reason'] = 'INPUT_CONTRACT'
        return result
    try:
        parser = _ChannelPrefixPreview(channel, observed_at.astimezone(timezone.utc), limit)
        parser.parse(body.decode('utf-8', errors='strict'))
        if not parser.messages:
            raise Refusal('NO_MESSAGES')
        result['messages'] = parser.messages
        result['status'] = 'PREFIX_PARTIAL'
        result['prefixCount'] = len(parser.messages)
        result['suffixHTMLUnexamined'] = parser.reached
        result['stopReason'] = 'PREFIX_LIMIT_REACHED' if parser.reached else 'END_OF_INPUT'
    except (UnicodeError, Refusal) as error:
        result['reason'] = str(error) if isinstance(error, Refusal) else 'UTF8'
    return result
