"""Fail-closed helpers for scanning JSON and source bytes for credentials."""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

_CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "accesstoken",
        "api_key",
        "apikey",
        "api_token",
        "apitoken",
        "auth",
        "authorization",
        "bearer",
        "bearer_token",
        "bearertoken",
        "client_secret",
        "clientsecret",
        "cookie",
        "google_access_id",
        "googleaccessid",
        "id_token",
        "idtoken",
        "password",
        "passwd",
        "private_key",
        "privatekey",
        "refresh_token",
        "refreshtoken",
        "secret",
        "secret_access_key",
        "secretaccesskey",
        "session_token",
        "sessiontoken",
        "set_cookie",
        "setcookie",
        "token",
        "x_api_key",
        "x_amz_credential",
        "x_amz_security_token",
        "x_amz_signature",
        "xapikey",
        "x_goog_credential",
        "x_goog_signature",
    }
)
_AUTHENTICATED_QUERY_KEYS = frozenset(
    {
        *_CREDENTIAL_KEYS,
        "se",
        "sig",
        "signature",
        "sp",
        "sv",
    }
)
_PLACEHOLDER = re.compile(
    r"(?:none|null|false|\*{3,}|x{5,}|redacted|placeholder|not[_-]?set|"
    r"the_odds_api_key|\{[A-Za-z_][A-Za-z0-9_]*\}|"
    r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$env:[A-Za-z_][A-Za-z0-9_]*|"
    r"%[A-Za-z_][A-Za-z0-9_]*%|<(?:redacted|placeholder|not[_-]?set)>|"
    r"os\.(?:environ\[['\"][A-Za-z_][A-Za-z0-9_]*['\"]\]|"
    r"getenv\(['\"][A-Za-z_][A-Za-z0-9_]*['\"]\)))",
    re.IGNORECASE,
)
_KNOWN_SECRET_TOKEN = re.compile(
    r"(?:gh[oprsu]_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})"
)
_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SECRET_LITERAL = re.compile(
    r"(?P<key>[\"']?[A-Za-z][A-Za-z0-9_-]*[\"']?)\s*[:=]\s*"
    r"(?P<value>[^,\r\n;]+)",
    re.IGNORECASE,
)


def _normalized_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


class _JsonObjectPairs(list[tuple[str, object]]):
    """Preserve every JSON member so duplicate keys cannot hide credential material."""


def is_secret_placeholder(value: object) -> bool:
    """Return whether a credential value is wholly a recognised non-secret placeholder."""

    if value is None or value is False:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return not stripped or _PLACEHOLDER.fullmatch(stripped) is not None


def authenticated_url_occurrences(value: str) -> int:
    """Count URLs carrying userinfo or a recognized credential/signature query field."""

    count = 0
    for match in _URL.finditer(value):
        candidate = match.group(0).rstrip(".,;:!?)")
        try:
            parsed = urlsplit(candidate)
            userinfo_values = tuple(
                item for item in (parsed.username, parsed.password) if item is not None
            )
            userinfo = bool(userinfo_values) and any(
                not is_secret_placeholder(item) for item in userinfo_values
            )
            credential_query = any(
                _normalized_key(key) in _AUTHENTICATED_QUERY_KEYS
                and not is_secret_placeholder(item)
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            )
        except ValueError:
            # A malformed URL cannot be proven credential-free.
            count += 1
            continue
        if userinfo or credential_query:
            count += 1
    return count


def _literal_secret_occurrences(value: str) -> int:
    count = 0
    without_urls = _URL.sub("", value)
    for match in _SECRET_LITERAL.finditer(without_urls):
        key = match.group("key").strip("\"'")
        if _normalized_key(key) not in _CREDENTIAL_KEYS:
            continue
        material = match.group("value").strip()
        if len(material) >= 2 and material[0] == material[-1] and material[0] in "\"'":
            material = material[1:-1]
        if not is_secret_placeholder(material):
            count += 1
    return count


def structured_secret_occurrences(value: object) -> int:
    """Count recursively exposed credential values and recognizable secret literals."""

    if isinstance(value, dict):
        count = 0
        for key, child in value.items():
            if _normalized_key(str(key)) in _CREDENTIAL_KEYS and not is_secret_placeholder(child):
                count += 1
            count += structured_secret_occurrences(child)
        return count
    if isinstance(value, list):
        return sum(structured_secret_occurrences(item) for item in value)
    if isinstance(value, str):
        return len(_KNOWN_SECRET_TOKEN.findall(value)) + _literal_secret_occurrences(value)
    return 0


def _parsed_json_secret_occurrences(value: object) -> int:
    if isinstance(value, _JsonObjectPairs):
        count = 0
        for key, child in value:
            if _normalized_key(key) in _CREDENTIAL_KEYS and not is_secret_placeholder(child):
                count += 1
            count += _parsed_json_secret_occurrences(child)
        return count
    if isinstance(value, list):
        return sum(_parsed_json_secret_occurrences(item) for item in value)
    if isinstance(value, str):
        return structured_secret_occurrences(value) + authenticated_url_occurrences(value)
    return structured_secret_occurrences(value)


def serialized_secret_or_authenticated_url_occurrences(value: bytes) -> int:
    """Count credential material in arbitrary source bytes without external access."""

    count = 0
    text = value.decode("utf-8", errors="ignore")
    count += len(_KNOWN_SECRET_TOKEN.findall(text))
    count += authenticated_url_occurrences(text)
    try:
        document = json.loads(
            value.decode("utf-8", errors="strict"),
            object_pairs_hook=_JsonObjectPairs,
        )
    except (UnicodeDecodeError, ValueError):
        return count + _literal_secret_occurrences(text)
    return count + _parsed_json_secret_occurrences(document)
