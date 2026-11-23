"""Pure prospective SYNTHETIC markup contract; not native-source qualification."""
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import TypedDict

VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
SVG_SELF_CLOSING = frozenset({"path", "circle", "ellipse", "line", "polygon", "polyline", "rect", "use"})
FORBIDDEN_CONTEXTS = frozenset({"template", "textarea", "xmp", "plaintext", "iframe", "noembed", "noframes"})
INERT_CONTEXTS = frozenset({"script", "style", "head", "title", "noscript", "svg", "math", "foreignobject"})


class Message(TypedDict):
    sourceId: str
    permalink: str
    publishedAtUTC: str
    text: str
    attribution: str
    personIdentityVerified: bool

class Result(TypedDict):
    schemaVersion: str
    status: str
    reason: str | None
    messages: list[Message]
    sourceReady: bool
    admissible: bool
    personIdentityVerified: bool
    nativeMarkupContractProven: bool

class Refusal(ValueError):
    pass

class Preview(HTMLParser):
    def __init__(self, channel: str, observed: datetime) -> None:
        super().__init__(convert_charrefs=True)
        self.channel = channel
        self.observed = observed
        self.stack: list[tuple[str, bool, str | None, bool]] = []
        self.current: str | None = None
        self.text: list[str] = []
        self.text_size = 0
        self.links: list[str] = []
        self.dates: list[str] = []
        self.messages: list[Message] = []
        self.seen: set[str] = set()
        self.nodes = 0
        self.text_blocks = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.nodes += 1
        if self.nodes > 100000 or len(self.stack) >= 128:
            raise Refusal("STRUCTURAL_CAP")
        if len(attrs) != len(dict(attrs)):
            raise Refusal("DUPLICATE_ATTRIBUTE")
        if tag in FORBIDDEN_CONTEXTS:
            raise Refusal("AMBIGUOUS_CONTEXT")
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        inert = (tag in INERT_CONTEXTS or bool(self.stack and self.stack[-1][3])
                 or "hidden" in a or (a.get("aria-hidden") or "").casefold() == "true")
        text = bool(self.stack and self.stack[-1][1])
        anchor = self.stack[-1][2] if self.stack else None
        if not inert and "tgme_widget_message" in classes:
            if self.current is not None or len(self.messages) >= 10:
                raise Refusal("MESSAGE_CAP_OR_NESTING")
            post = a.get("data-post")
            if not isinstance(post, str) or re.fullmatch(re.escape(self.channel) + r"/[1-9][0-9]{0,19}", post) is None or post in self.seen:
                raise Refusal("MESSAGE_ID")
            self.current = post
            self.message_depth = len(self.stack)
            self.seen.add(post)
            self.text, self.links, self.dates = [], [], []
            self.text_size, self.text_blocks = 0, 0
        if not inert and self.current is not None:
            if "tgme_widget_message_text" in classes:
                self.text_blocks += 1
                if self.text_blocks != 1:
                    raise Refusal("DUPLICATE_TEXT")
                text = True
            if tag == "a":
                href = a.get("href")
                anchor = href
            if tag == "time":
                date = a.get("datetime")
                if anchor != "https://t.me/" + self.current or not isinstance(date, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", date) is None:
                    raise Refusal("DATE_OR_LINK")
                try:
                    stamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
                except ValueError as error:
                    raise Refusal("DATE_INVALID") from error
                if stamp.utcoffset() is None or stamp > self.observed:
                    raise Refusal("DATE_UNPROVEN")
                self.links.append("https://t.me/" + self.current)
                self.dates.append(stamp.astimezone(timezone.utc).isoformat())
        if tag in VOID_ELEMENTS:
            if tag == "br" and text and self.current is not None and not inert:
                self.append_text("\n")
            return
        self.stack.append((tag, text, anchor, inert))

    def append_text(self, data: str) -> None:
        self.text_size += len(data.encode("utf-8"))
        if self.text_size > 8192:
            raise Refusal("TEXT_CAP")
        self.text.append(data)

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.stack and self.stack[-1][1] and not self.stack[-1][3]:
            self.append_text(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1][0] != tag:
            raise Refusal("AMBIGUOUS_MARKUP")
        self.stack.pop()
        # The active wrapper is identified by its exact opening depth.
        if self.current is not None and len(self.stack) == self.message_depth:
            if len(self.links) != 1 or len(self.dates) != 1 or self.text_blocks != 1 or not "".join(self.text).strip():
                raise Refusal("MESSAGE_INCOMPLETE")
            self.messages.append(Message(sourceId=self.current, permalink=self.links[0], publishedAtUTC=self.dates[0], text="".join(self.text), attribution="CHANNEL", personIdentityVerified=False))
            self.current = None

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID_ELEMENTS | SVG_SELF_CLOSING:
            raise Refusal("NONVOID_SELF_CLOSE")
        if tag in SVG_SELF_CLOSING and (not any(f[0] == "svg" for f in self.stack)
                                           or any(f[0] == "foreignobject" for f in self.stack)):
            raise Refusal("SVG_CONTEXT_UNPROVEN")
        self.handle_starttag(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_decl(self, decl: str) -> None:
        if decl.lower() != "doctype html":
            raise Refusal("DECLARATION")

    def unknown_decl(self, data: str) -> None:
        raise Refusal("DECLARATION")

    message_depth = -1

    def parse(self, text: str) -> None:
        self.feed(text)
        self.close()
        if self.stack or self.current is not None:
            raise Refusal("UNCLOSED_MARKUP")


def parse_preview_messages(body: bytes, *, channel: str, observed_at: datetime) -> Result:
    result = Result(schemaVersion="telegram-preview-synthetic-contract-v1", status="UNPROVEN", reason=None, messages=[], sourceReady=False, admissible=False, personIdentityVerified=False, nativeMarkupContractProven=False)
    if type(body) is not bytes or len(body) > 2097152 or not isinstance(channel, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", channel) is None or not isinstance(observed_at, datetime) or observed_at.utcoffset() is None:
        result["reason"] = "INPUT_CONTRACT"
        return result
    try:
        parser = Preview(channel, observed_at.astimezone(timezone.utc))
        parser.parse(body.decode("utf-8", errors="strict"))
        if not parser.messages:
            raise Refusal("NO_MESSAGES")
        result["messages"] = parser.messages
        result["status"] = "STRUCTURED_SYNTHETIC_CONTRACT"
    except (UnicodeError, Refusal) as error:
        result["reason"] = str(error) if isinstance(error, Refusal) else "UTF8"
    return result
