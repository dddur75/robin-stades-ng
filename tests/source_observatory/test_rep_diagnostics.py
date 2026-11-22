from __future__ import annotations

import json

import pytest

from robin.source_observatory.rep_diagnostics import RobotsPolicyError, policy

URL = "https://example.invalid/match?round=two"
PRODUCT = "RobinSourceObservatory"


def test_comment_markup_preserves_empty_disallow_permission() -> None:
    diag: dict[str, object] = {}
    assert policy(
        b"User-agent: *\nDisallow:\n# Documentation <https://example.invalid>\n",
        URL,
        PRODUCT,
        diagnostics=diag,
    ) == (True, 0.0)
    assert diag["result"] == "ALLOW"


def test_comment_markup_cannot_weaken_disallow() -> None:
    assert policy(b"User-agent: *\nDisallow: / # <documentation>\n", URL, PRODUCT) == (False, 0.0)


def test_genuine_html_is_still_unproven() -> None:
    with pytest.raises(RobotsPolicyError, match="HTML_MARKUP"):
        policy(b"<html>not a policy</html>", URL, PRODUCT)


@pytest.mark.parametrize(
    ("body", "reason", "line"),
    [
        (b"\xff", "UTF8", None),
        (b"User-agent: Bot/secret\nDisallow: /", "UA_SYNTAX", 1),
        (b"User-agent: *\nDisallow: /hidden%2Fprivate", "RULE_PERCENT", 2),
        (b"User-agent: *\nDisallow: /secret[abc]", "RULE_BRACKET_OR_BACKSLASH", 2),
        (b"User-agent: *\nCrawl-delay: NaN", "CRAWL_DELAY", 2),
        (b"User-agent: *\nRequest-rate: zero", "REQUEST_RATE", 2),
        (b"User-agent: *\nDisallow: secret", "RULE_PREFIX", 2),
        (b"User-agent: *\nDisallow: /secret$tail", "RULE_ANCHOR", 2),
        (b"Disallow: /", "ORPHAN_RULE", 1),
        (b"User-agent: *\nDisallow: /\x00", "NUL", None),
    ],
)
def test_failures_have_distinct_closed_reasons_without_source_text(
    body: bytes, reason: str, line: int | None
) -> None:
    diag: dict[str, object] = {"untrusted": "must disappear"}
    with pytest.raises(RobotsPolicyError) as error:
        policy(body, URL, PRODUCT, diagnostics=diag)
    assert error.value.reason == reason and str(error.value) == reason
    assert error.value.line == line and diag["line"] == line
    assert diag["reason"] == reason and diag["result"] == "UNPROVEN"
    assert set(diag) == {
        "phase",
        "reason",
        "line",
        "line_sha256",
        "body_sha256",
        "groups",
        "selected_groups",
        "selected_kind",
        "result",
    }
    assert "secret" not in json.dumps(diag) and "untrusted" not in diag


def test_delay_only_group_and_empty_lines_remain_supported() -> None:
    assert policy(b"User-agent: *\n\n# comment\nCrawl-delay: 10\n", URL, PRODUCT) == (True, 10.0)


def test_exact_product_deny_overrides_wildcard_allow() -> None:
    body = b"User-agent: *\nAllow: /\nUser-agent: robinsourceobservatory\nDisallow: /\n"
    assert policy(body, URL, PRODUCT) == (False, 0.0)


def test_unrelated_product_allow_cannot_override_wildcard_deny() -> None:
    body = b"User-agent: *\nDisallow: /\nUser-agent: WrongBot\nAllow: /\n"
    assert policy(body, URL, PRODUCT) == (False, 0.0)


def test_multiple_exact_groups_merge_and_allow_wins_equal_length() -> None:
    body = b"User-agent: RobinSourceObservatory\nDisallow: /match\nUser-agent: RobinSourceObservatory\nAllow: /match\n"
    assert policy(body, URL, PRODUCT) == (True, 0.0)


def test_blank_line_does_not_end_selected_group() -> None:
    assert policy(b"User-agent: RobinSourceObservatory\n\nDisallow: /\n", URL, PRODUCT) == (
        False,
        0.0,
    )


def test_literal_question_mark_and_terminal_anchor() -> None:
    body = b"User-agent: *\nDisallow: /match?round=two$\n"
    assert policy(body, URL, PRODUCT) == (False, 0.0)
    assert policy(body, URL + "-extra", PRODUCT) == (True, 0.0)


def test_request_rate_remains_a_pacing_floor() -> None:
    assert policy(b"User-agent: *\nRequest-rate: 2/10\n", URL, PRODUCT) == (True, 5.0)


def test_oversize_input_has_no_digest_in_diagnostics() -> None:
    diag: dict[str, object] = {}
    with pytest.raises(RobotsPolicyError, match="ARGUMENTS"):
        policy(b"x" * 65537, URL, PRODUCT, diagnostics=diag)
    assert diag["body_sha256"] is None


@pytest.mark.parametrize("body", [b"\xff", b"User-agent: Bot/unsupported\nDisallow: /"])
def test_metadata_before_selection_keeps_counts_unknown(body: bytes) -> None:
    diag: dict[str, object] = {}
    with pytest.raises(RobotsPolicyError):
        policy(body, URL, PRODUCT, diagnostics=diag)
    assert diag["groups"] is None and diag["selected_groups"] is None
    assert diag["selected_kind"] == "UNPROVEN"


@pytest.mark.parametrize(
    "body",
    [
        b"User-agent: *\n# last comment",
        b"User-agent: *\nDisallow: /\nUser-agent: RobinSourceObservatory\n# last comment",
    ],
)
def test_metadata_global_failure_has_no_fabricated_line(body: bytes) -> None:
    diag: dict[str, object] = {}
    with pytest.raises(RobotsPolicyError) as error:
        policy(body, URL, PRODUCT, diagnostics=diag)
    assert error.value.line is None and diag["line"] is None
    assert diag["line_sha256"] is None


def test_metadata_directive_hash_excludes_whitespace_and_comment() -> None:
    from hashlib import sha256

    diag: dict[str, object] = {}
    with pytest.raises(RobotsPolicyError, match="RULE_PERCENT"):
        policy(
            b"User-agent: *\n  Disallow: /private%2Fpath # <documentation>\n",
            URL,
            PRODUCT,
            diagnostics=diag,
        )
    assert diag["line"] == 2
    assert diag["line_sha256"] == sha256(b"Disallow: /private%2Fpath").hexdigest()


def test_metadata_successful_group_counts_are_measured() -> None:
    diag: dict[str, object] = {}
    assert policy(b"User-agent: *\nDisallow:\n", URL, PRODUCT, diagnostics=diag) == (True, 0.0)
    assert diag["groups"] == 1 and diag["selected_groups"] == 1
    assert diag["selected_kind"] == "WILDCARD"
