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
        groups: list[tuple[list[str], list[tuple[str, str, int]]]] = []
        agents: list[str] = []
        directives: list[tuple[str, str, int]] = []
        diag["phase"] = "PARSE"
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
                if re.fullmatch(r"\*|[A-Za-z_-]+", value) is None:
                    fail("UA_SYNTAX")
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
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
