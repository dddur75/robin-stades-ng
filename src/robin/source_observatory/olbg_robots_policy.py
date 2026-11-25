"""Conservative REP subset with closed diagnostics; never performs network I/O.

This retains the reviewed subset's refusal of unsupported syntax. It is not a
claim of complete RFC 9309 conformance or of publisher permission.
"""

from __future__ import annotations

import math
import re
from fnmatch import fnmatchcase
from hashlib import sha256
from typing import NoReturn
from urllib.parse import urlsplit

REASONS = frozenset(
    {
        "ARGUMENTS",
        "UTF8",
        "NUL",
        "HTML_MARKUP",
        "URL",
        "TARGET_UNSUPPORTED",
        "LINE_SYNTAX",
        "DIRECTIVE_KEY",
        "UA_SYNTAX",
        "ORPHAN_RULE",
        "NO_POLICY",
        "EMPTY_SELECTED_GROUP",
        "CRAWL_DELAY",
        "REQUEST_RATE",
        "RULE_LENGTH_OR_ENCODING",
        "RULE_PERCENT",
        "RULE_BRACKET_OR_BACKSLASH",
        "RULE_CONTROL",
        "RULE_PREFIX",
        "RULE_ANCHOR",
        "INTERNAL_UNPROVEN",
    }
)


class RobotsPolicyError(ValueError):
    def __init__(self, reason: str, line: int | None = None) -> None:
        if reason not in REASONS:
            reason = "INTERNAL_UNPROVEN"
        super().__init__(reason)
        self.reason = reason
        self.line = line


# Closed documentary evidence, not a generalized UA syntax repair.
# Exact value digests derive from projection32bbc...3b76a, relative ONLY to
# RobinSourceObservatory. No source name/value is persisted by diagnostics.
NATIVE_FOREIGN_PRODUCT = "robinsourceobservatory"
NATIVE_FOREIGN_VALUE_SHA256 = frozenset({
    "064083eedbffe894014ee7ea9923b8cd252d6c3f40d21e5a22bec52deb1264f0",
    "0a4e1e1914ce7b322b48c6d81205d1da4927c9efe4cfb1f05f62941c44243b9c",
    "0c0a0b4b46a63c1ac1a47af2c613e75738f74c5b8c40ec5d5b816d8c120a0bc9",
    "2f7a2c4874bdc130f5915ea1a1fa23aadb16da2d93789932bec5fdad3e72f528",
    "30ecab6dfef2af8c6f2a03d3d9b937b770253580253e85e8dcb6f4340572fa68",
    "33e622832f4f16db450002f225bc3465f91f846c11b23f2d0431a1c437718e04",
    "38a2a3aefa1da551c2119b98a6990c1b39b88c9f9dceebe69531a02ad83de131",
    "39549ad5dbb2aa88cb6978f11747e1bd17f38e635896bdada03ae408d30129c6",
    "3c8b93176a48c956a49e1eb0482432f4de625904f4ce02f047891fc38ab81e57",
    "410065ebd08d229ad6b53517ca5b1824562ab417cbb30b3b6c633b1d897c345a",
    "4b717adb172b5888f4c675ca374e8bb7290c9be0694c22a629b8686af3b3bca8",
    "4bcb511e9b7aa0beb105d5b040d8c0d43d7582febd00f39e2f3964d7f46713aa",
    "51672b9d52ee77bd403f070379c7f218f55582762f12ba23074c71bb2e43f665",
    "622a207a8d7afaa53245f0159764d622c8e88518361b1ee0365a31b066af2e9e",
    "778c2227d608d0d7fa1a20c4c1919b4f961a5e73ea858dff93aac9325833f080",
    "7857aaf71745c453b0b5c29ece97d5a2b588df3faaae03f55ee44cf42293a799",
    "7c7ef384d1aadc6b4d9fef03ea7d487624583125ff7f8b9a17fc003dd8af8b8b",
    "7cbc411ce4c755c9dd8550a265abc6c117a557f9118e6ad081a6714f3312ee02",
    "7d545397f845a449cd1734ad637c2b1d527479736007e65d56bdae4fae81c2b4",
    "7ee91a31a0cef6602e58da73528fc553a40fdf6a08ba0cbbe1b8f7ca1e23af4a",
    "8d1325b7a6a282c138818d0256e171ecbc16e37f0b6639f6a0eadc9aa4bf6264",
    "8dee080947f467d307fa4b1531a34d4b9f79fc0f2ce3ece40ae2e3c4d13203c7",
    "92ba90aca4558c7a53010c1387616578feabf3d443262e5cd2842d485d52bb71",
    "95de31b8309201f6f32c00bb460df7d7c41b444f3b17dcf48b409473b26047ba",
    "98b8269573ea886c1c309235557429afd2c88de0c06e14b600d1d6578827c253",
    "b191fe95ffc707a5af3cd893612095d668ca8fba187cc9807d036b0df7ef0fc9",
    "bc1ab845766fdd325a09e7b6a8105a56d474015370c4d7ea56751d3219efae91",
    "be2b287598b4c7d134c38a68a82af94301ed5c5f6b3b9de498551174632a64b9",
    "bf12e32cd757156907392247961b90a57ebeb38bfe16034ac2096345e31d1feb",
    "c3d4a1e50bb4276f798d308c9551767baebdfa609ffef02957ae3d05487f77db",
    "c40ea5ee4b0d0967ad7d5bbed2dce20abac4d93c398f8a0fe957e3a0deb49f59",
    "d4c1aaabaf7315a044026070cab64fadee6228c1ee8398d28c1ad35df5afdf0d",
    "d4f4eb03056c8b68c45271e8ad2712b6b04249ffe91476e7ed2f56abb29b4a98",
    "d644a6ea9a33f7bf062eab1859b51734063b41ef0e03ef5c4c1c928e4f10b95b",
    "dff454ada3b5564672f67146f5ab208564264aa120a940623d1724784a296d9d",
    "e2d77fd1403e7a55fbe96d8beadd808f68e10462e68e706db257d69add603051",
    "e40540d52f28bed4b8597447058f3de46dfaf63d4f3e638ccb57cf39dd911df1",
})


def _foreign_invalid_ascii(value: str, product_token: str) -> bool:
    """Keep v1's class; additionally quarantine only 37 proven native values.

    The closed addition is tied to the fixed observer product, not a repair or
    generalized acceptance of spaces, arbitrary versions, quotes or encoding.
    None is still the only sentinel; no ignored header can become applicable.
    """
    safe = (
        value.isascii()
        and "*" not in value
        and "%" not in value
        and product_token.lower() not in value.lower()
    )
    return safe and (
        re.fullmatch(r"[A-Za-z_-][A-Za-z0-9_-]{0,127}(?:/[0-9][0-9A-Za-z._-]{0,63})?", value)
        is not None
        or (
            product_token.lower() == NATIVE_FOREIGN_PRODUCT
            and sha256(value.encode("utf-8")).hexdigest() in NATIVE_FOREIGN_VALUE_SHA256
        )
    )


def policy(
    body: bytes,
    url: str,
    product_token: str,
    *,
    max_delay_seconds: float = 60,
    max_bytes: int = 65536,
    diagnostics: dict[str, object] | None = None,
) -> tuple[bool, float]:
    """Return allow/delay or a fixed reason without source text.

    line_sha256 hashes UTF-8 after comment removal and whitespace stripping;
    it is not a hash of the original raw line. Global failures have no line.
    """
    diag = diagnostics if diagnostics is not None else {}
    diag.clear()
    diag.update(
        phase="INPUT",
        reason=None,
        line=None,
        line_sha256=None,
        body_sha256=None,
        groups=None,
        selected_groups=None,
        selected_kind="UNPROVEN",
        result="UNPROVEN",
        foreign_invalid_headers_seen=None,
        last_foreign_header_line=None,
        last_foreign_header_sha256=None,
        foreign_header_handling=None,
    )
    line_number: int | None = None
    current_line = ""

    def fail(reason: str) -> NoReturn:
        global_reason = reason in {
            "ARGUMENTS",
            "UTF8",
            "NUL",
            "URL",
            "TARGET_UNSUPPORTED",
            "NO_POLICY",
            "EMPTY_SELECTED_GROUP",
            "INTERNAL_UNPROVEN",
        }
        failure_line = None if global_reason else line_number
        diag.update(
            reason=reason,
            line=failure_line,
            line_sha256=(
                sha256(current_line.encode()).hexdigest()
                if current_line and failure_line is not None
                else None
            ),
        )
        raise RobotsPolicyError(reason, failure_line)

    try:
        if (
            type(body) is not bytes
            or type(product_token) is not str
            or re.fullmatch("[A-Za-z_-]+", product_token) is None
            or type(max_bytes) is not int
            or not 0 < max_bytes <= 65536
            or not 0 < len(body) <= max_bytes
            or type(max_delay_seconds) not in (int, float)
            or not math.isfinite(max_delay_seconds)
            or not 0 <= max_delay_seconds <= 60
        ):
            fail("ARGUMENTS")
        diag["body_sha256"] = sha256(body).hexdigest()
        try:
            text = body.decode("utf-8-sig", "strict")
        except UnicodeError:
            fail("UTF8")
        if "\x00" in text:
            fail("NUL")
        diag["phase"] = "URL"
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                fail("URL")
        except RobotsPolicyError:
            raise
        except ValueError:
            fail("URL")
        target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
        if "%" in target or not target.isascii() or any(ord(c) <= 32 for c in target):
            fail("TARGET_UNSUPPORTED")
        groups: list[tuple[list[str | None], list[tuple[str, str, int]]]] = []
        agents: list[str | None] = []
        directives: list[tuple[str, str, int]] = []
        diag["phase"] = "PARSE"
        foreign_seen = 0
        diag.update(foreign_invalid_headers_seen=0, foreign_header_handling="NONE_SEEN")
        for line_number, raw in enumerate(text.splitlines(), 1):
            current_line = raw.split("#", 1)[0].strip()
            if not current_line:
                continue
            # Comments are removed before the HTML guard, as with REP rules.
            if "<" in current_line:
                fail("HTML_MARKUP")
            if ":" not in current_line:
                fail("LINE_SYNTAX")
            key, value = (v.strip() for v in current_line.split(":", 1))
            key = key.lower()
            if re.fullmatch("[a-z][a-z0-9_-]*", key) is None:
                fail("DIRECTIVE_KEY")
            if key == "user-agent":
                foreign = False
                if re.fullmatch(r"\*|[A-Za-z_-]+", value) is None:
                    if not _foreign_invalid_ascii(value, product_token):
                        fail("UA_SYNTAX")
                    foreign = True
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                # Preserve the SAME group boundary rule as a valid UA header.
                # None cannot match any product or wildcard; its rules never leak
                # into the preceding group. Consecutive valid own headers remain.
                agents.append(None if foreign else value.lower())
                if foreign:
                    foreign_seen += 1
                    diag.update(
                        foreign_invalid_headers_seen=foreign_seen,
                        last_foreign_header_line=line_number,
                        last_foreign_header_sha256=sha256(current_line.encode()).hexdigest(),
                        foreign_header_handling="NONMATCHING_ASCII_NAME_SKIPPED",
                    )
            elif key in {"allow", "disallow", "crawl-delay", "request-rate"}:
                if not agents:
                    fail("ORPHAN_RULE")
                directives.append((key, value, line_number))
        if agents:
            groups.append((agents, directives))
        diag["groups"] = len(groups)
        if not groups or not any(rules for _, rules in groups):
            fail("NO_POLICY")
        product = product_token.lower()
        selected = [rules for names, rules in groups if product in names]
        diag["selected_kind"] = "EXACT" if selected else "NONE"
        if not selected:
            selected = [rules for names, rules in groups if "*" in names]
            if selected:
                diag["selected_kind"] = "WILDCARD"
        diag["selected_groups"] = len(selected)
        if selected and not any(selected):
            fail("EMPTY_SELECTED_GROUP")
        diag["phase"] = "RULES"
        matches: list[tuple[int, bool]] = []
        delay = 0.0
        raw_lines = text.splitlines()
        for rules in selected:
            for key, value, line_number in rules:
                current_line = raw_lines[line_number - 1].split("#", 1)[0].strip()
                if key == "crawl-delay":
                    try:
                        current = float(value)
                    except ValueError:
                        fail("CRAWL_DELAY")
                    if not math.isfinite(current) or not 0 <= current <= max_delay_seconds:
                        fail("CRAWL_DELAY")
                    delay = max(delay, current)
                elif key == "request-rate":
                    try:
                        count, seconds = (float(x) for x in value.split("/", 1))
                    except ValueError:
                        fail("REQUEST_RATE")
                    if (
                        not math.isfinite(count)
                        or not math.isfinite(seconds)
                        or count <= 0
                        or seconds <= 0
                    ):
                        fail("REQUEST_RATE")
                    current = seconds / count
                    if not math.isfinite(current) or current > max_delay_seconds:
                        fail("REQUEST_RATE")
                    delay = max(delay, current)
                elif value:
                    if len(value) > 2048 or not value.isascii():
                        fail("RULE_LENGTH_OR_ENCODING")
                    if "%" in value:
                        fail("RULE_PERCENT")
                    if "[" in value or "]" in value or "\\" in value:
                        fail("RULE_BRACKET_OR_BACKSLASH")
                    if any(ord(c) <= 32 or ord(c) == 127 for c in value):
                        fail("RULE_CONTROL")
                    if not value.startswith(("/", "*")):
                        fail("RULE_PREFIX")
                    anchored = value.endswith("$")
                    path = value[:-1] if anchored else value
                    if "$" in path:
                        fail("RULE_ANCHOR")
                    pattern = path.replace("?", "[?]") + ("" if anchored else "*")
                    if fnmatchcase(target, pattern):
                        matches.append((len(path.replace("*", "")), key == "allow"))
        allowed = max(matches)[1] if matches else True
        diag.update(
            phase="COMPLETE",
            result="ALLOW" if allowed else "DENY",
            reason=None,
            line=None,
            line_sha256=None,
        )
        return allowed, delay
    except RobotsPolicyError:
        raise
    except Exception:
        fail("INTERNAL_UNPROVEN")
