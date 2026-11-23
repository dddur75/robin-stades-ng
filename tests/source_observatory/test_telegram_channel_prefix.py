"""Synthetic contracts for the explicit observed-channel prefix profile."""
from datetime import UTC, datetime

import pytest

from robin.source_observatory.telegram_channel_prefix import (
    NORMALIZATION_PROFILE,
    REFERENCE_PROVENANCE,
    SEMANTIC_PROFILE,
    parse_channel_prefix,
)
from robin.source_observatory.telegram_prefix import parse_preview_prefix

CHANNEL = "bextra_pronostics_foot"
OBSERVED = datetime(2026, 11, 23, tzinfo=UTC)


def wrap(inner=None, *, channel=CHANNEL, number=1):
    if inner is None:
        inner = '<div class="tgme_widget_message_text">ABC</div>'
    return (
        f'<div class="tgme_widget_message" data-post="{channel}/{number}">'
        f'{inner}<a href="https://t.me/{channel}/{number}">'
        '<time datetime="2026-01-01T00:00:00Z"></time></a></div>'
    ).encode()


def parse(body, **options):
    return parse_channel_prefix(body, channel=CHANNEL, observed_at=OBSERVED, **options)


def assert_unqualified(result):
    assert all(result[key] is False for key in (
        "sourceReady", "admissible", "personIdentityVerified", "nativeMarkupContractProven"
    ))
    assert result["totalMessageCount"] is None
    assert len(result) == 12


def test_case_canonical_references_are_explicitly_derived():
    result = parse(wrap(channel=CHANNEL.upper()))
    assert result["status"] == "PREFIX_PARTIAL"
    assert result["messages"][0]["sourceId"] == CHANNEL + "/1"
    assert result["messages"][0]["permalink"] == "https://t.me/" + CHANNEL + "/1"
    assert NORMALIZATION_PROFILE == "TG_ASCII_USERNAME_CANONICAL_V1"
    assert SEMANTIC_PROFILE == "TG_INHERITED_TEXT_REGION_V1"
    assert REFERENCE_PROVENANCE == "DERIVED_CANONICAL_CONFIGURED_ASCII_USERNAME_NOT_RAW_SOURCE_SPELLING"
    assert_unqualified(result)


@pytest.mark.parametrize("inner", [
    '<div class="tgme_widget_message_text">A<div class="tgme_widget_message_text">B</div>C</div>',
    '<div class="tgme_widget_message_text">A<span class="tgme_widget_message_text">B</span>C</div>',
    '<div class="tgme_widget_message_text">A<span class="other"><div class="tgme_widget_message_text">B</div></span>C</div>',
])
def test_inherited_region_retains_text_once_and_in_order(inner):
    result = parse(wrap(inner))
    assert result["reason"] is None
    assert result["messages"][0]["text"] == "ABC"
    assert_unqualified(result)


def test_two_independent_regions_remain_atomically_refused():
    result = parse(wrap('<div class="tgme_widget_message_text">A</div><div class="tgme_widget_message_text">B</div>'))
    assert result["reason"] == "DUPLICATE_TEXT"
    assert result["messages"] == []
    assert result["prefixCount"] == 0
    assert_unqualified(result)


@pytest.mark.parametrize(("body", "reason"), [
    (wrap(channel="foreign"), "MESSAGE_ID"),
    (wrap().replace(b'data-post=', b'data-post="x" data-post='), "DUPLICATE_ATTRIBUTE"),
    (wrap().replace(("https://t.me/" + CHANNEL + "/1").encode(), ("https://t.me/" + CHANNEL + "/1?x=1").encode()), "DATE_OR_LINK"),
    (wrap('<div class="tgme_widget_message_text">A' + wrap(number=2).decode() + '</div>'), "MESSAGE_CAP_OR_NESTING"),
])
def test_other_source_guards_are_preserved(body, reason):
    result = parse(body)
    assert result["reason"] == reason
    assert result["messages"] == []
    assert_unqualified(result)


def test_duplicate_case_variant_message_stays_refused():
    result = parse(wrap(channel=CHANNEL.upper()) + wrap())
    assert result["reason"] == "MESSAGE_ID"
    assert result["messages"] == []


def test_prefix_limits_are_isolated_between_invocations():
    body = wrap() + wrap(number=2)
    first = parse(body, limit=1)
    second = parse(body, limit=2)
    complete = parse(body)
    assert first["prefixCount"] == 1 and second["prefixCount"] == 2
    assert first["suffixHTMLUnexamined"] is True
    assert second["suffixHTMLUnexamined"] is True
    assert complete["prefixCount"] == 2
    assert complete["suffixHTMLUnexamined"] is False
    assert complete["stopReason"] == "END_OF_INPUT"


def test_original_strict_entrypoint_keeps_its_contract():
    uppercase = parse_preview_prefix(wrap(channel=CHANNEL.upper()), channel=CHANNEL, observed_at=OBSERVED)
    nested = parse_preview_prefix(wrap('<div class="tgme_widget_message_text">A<div class="tgme_widget_message_text">B</div>C</div>'), channel=CHANNEL, observed_at=OBSERVED)
    assert uppercase["reason"] == "MESSAGE_ID"
    assert nested["reason"] == "DUPLICATE_TEXT"


@pytest.mark.parametrize("limit", [0, 11, True])
def test_invalid_limit_never_weakens_the_bound(limit):
    result = parse(wrap(), limit=limit)
    assert result["reason"] == "INPUT_CONTRACT"
    assert result["messages"] == []
