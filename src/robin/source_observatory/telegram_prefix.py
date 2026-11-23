"""Pure bounded Telegram prefix reader; every message remains unqualified."""
import re
from datetime import datetime, timezone

from .telegram_preview import Preview, Refusal, Result


class PrefixResult(Result):
    prefixCount: int
    totalMessageCount: None
    suffixHTMLUnexamined: bool
    stopReason: str


class _PrefixReached(Exception):
    pass


class _PrefixPreview(Preview):
    def __init__(self, channel: str, observed: datetime, limit: int) -> None:
        super().__init__(channel, observed)
        self.limit = limit
        self.reached = False
        self._stop = _PrefixReached()

    def handle_endtag(self, tag: str) -> None:
        super().handle_endtag(tag)
        if self.current is None and len(self.messages) == self.limit:
            self.reached = True
            raise self._stop

    def parse(self, text: str) -> None:
        try:
            super().parse(text)
        except _PrefixReached as stop:
            if stop is not self._stop:
                raise
            # The retained Nth wrapper is complete. Remaining DOM is unexamined.


def parse_preview_prefix(
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
        parser = _PrefixPreview(channel, observed_at.astimezone(timezone.utc), limit)
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
