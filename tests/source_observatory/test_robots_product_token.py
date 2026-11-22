"""Synthetic regressions for selecting REP groups by the honest product token."""

import pytest

from robin.source_observatory import collector


@pytest.mark.parametrize('invalid', ['/', '1.0', 'RobinSourceObservatory/1.0', ''])
def test_invalid_agent_cannot_override_wildcard_denial(invalid):
    text = f'User-agent: *\nDisallow: /\nUser-agent: {invalid}\nAllow: /\n'
    with pytest.raises(ValueError, match='robots user-agent'):
        collector.robots_policy(text, 'https://example.invalid/tips')


def test_header_comment_is_not_a_second_crawler_identity(monkeypatch):
    monkeypatch.setattr(collector, 'USER_AGENT', 'RobinSourceObservatory/1.0 (Codex personal collection)')
    text = 'User-agent: *\nDisallow: /\nUser-agent: Codex\nAllow: /\n'
    assert collector.robots_policy(text, 'https://example.invalid/tips') == (False, 0.0)


def test_partial_product_name_does_not_override_wildcard_allowance():
    text = 'User-agent: *\nAllow: /\nUser-agent: Observatory\nDisallow: /\n'
    assert collector.robots_policy(text, 'https://example.invalid/tips') == (True, 0.0)
