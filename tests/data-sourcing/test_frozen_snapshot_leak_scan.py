from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from robin.data_snapshot.freeze import scan_committable_reports


def _scan_bytes(payload: bytes) -> dict[str, Any]:
    reports = {"report.json": payload}
    batch = cast(Any, SimpleNamespace(leak_tokens={}))
    return cast(dict[str, Any], scan_committable_reports(reports, batch, forbidden_paths=()))


def _scan(document: object) -> dict[str, Any]:
    return _scan_bytes((json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n").encode())


@pytest.mark.parametrize(
    "document",
    (
        {"nested": {"access_token": "actual-token-0123456789"}},
        {"nested": {"refresh_token": "actual-token-0123456789"}},
        {"nested": {"id_token": "actual-token-0123456789"}},
        {"nested": {"token": "actual-token-0123456789"}},
        {"nested": {"password": 123456}},
        {"nested": {"passwd": "actual-password-0123456789"}},
        {"nested": {"private\u005fkey": "actual-key-0123456789"}},
        {"nested": {"client-secret": "actual-key-0123456789"}},
        {"items": [{"authorization": "Bearer actual-token"}]},
        {"items": [{"auth": "Bearer actual-token"}]},
        {"items": [{"cookie": "session=actual-token"}]},
        {"items": [{"set-cookie": "session=actual-token"}]},
        {"api-key": {"material": "actual-key-0123456789"}},
    ),
)
def test_report_scan_rejects_recursive_structured_secrets(document: object) -> None:
    scan = _scan(document)

    assert scan["structured_secret_occurrences"] > 0
    assert scan["total_failure_count"] > 0
    assert scan["verdict"] == "FAIL"


def test_report_scan_detects_a_json_escaped_credential_key() -> None:
    scan = _scan_bytes(b'{"access\\u005ftoken":"actual-token-0123456789"}\n')

    assert scan["structured_secret_occurrences"] == 1
    assert scan["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "placeholder",
    (
        "${ACCESS_TOKEN}",
        "<redacted>",
        "not_set",
        'os.environ["ACCESS_TOKEN"]',
        None,
        False,
    ),
)
def test_report_scan_allows_only_full_value_placeholders(placeholder: object) -> None:
    clean = _scan({"nested": {"access_token": placeholder}})
    contaminated = _scan({"nested": {"access_token": f"prefix-{placeholder}"}})

    assert clean["structured_secret_occurrences"] == 0
    assert clean["verdict"] == "PASS"
    assert contaminated["structured_secret_occurrences"] == 1
    assert contaminated["verdict"] == "FAIL"


@pytest.mark.parametrize(
    "url",
    (
        "https://example.invalid/object?X-Amz-Signature=deadbeefcafebabedeadbeef",
        "https://example.invalid/object?X-Amz-Credential=scope&X-Amz-Algorithm=AWS4-HMAC-SHA256",
        "https://example.invalid/object?X-Amz-Security-Token=actual-session-token",
        "https://example.invalid/container?sv=2025-01-01&sp=r&se=2026-08-17&sig=actual-sas",
        "https://storage.googleapis.invalid/object?X-Goog-Signature=deadbeefcafebabe",
        "https://storage.googleapis.invalid/object?GoogleAccessId=identity&Signature=actual",
        "https://user:password@example.invalid/object",
    ),
)
def test_report_scan_rejects_signed_or_authenticated_urls(url: str) -> None:
    scan = _scan({"download_reference": url})

    assert scan["authenticated_url_occurrences"] == 1
    assert scan["verdict"] == "FAIL"


def test_report_scan_allows_signed_url_placeholders_only_as_whole_values() -> None:
    clean = _scan(
        {
            "download_reference": "https://example.invalid/object?X-Amz-Signature=${SIGNATURE}",
            "refresh_token": "<redacted>",
            "userinfo_reference": "https://${USER}:${PASSWORD}@example.invalid/object",
        }
    )
    contaminated = _scan(
        {
            "download_reference": "https://example.invalid/object?X-Amz-Signature=prefix-${SIGNATURE}",
            "refresh_token": "prefix-<redacted>",
        }
    )

    assert clean["authenticated_url_occurrences"] == 0
    assert clean["structured_secret_occurrences"] == 0
    assert clean["verdict"] == "PASS"
    assert contaminated["authenticated_url_occurrences"] == 1
    assert contaminated["structured_secret_occurrences"] == 1
    assert contaminated["verdict"] == "FAIL"


def test_report_scan_rejects_known_secret_token_under_innocuous_key() -> None:
    scan = _scan(
        {"note": "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"}  # SECRET_SCANNER_TEST_FIXTURE
    )

    assert scan["structured_secret_occurrences"] == 1
    assert scan["verdict"] == "FAIL"


def test_report_scan_recurses_into_string_values_for_embedded_assignments() -> None:
    clean = _scan({"note": "api_key=${REPORT_API_KEY}"})
    literal = _scan({"note": "api_key=actual-secret-0123456789"})
    mixed = _scan({"note": "api_key=prefix-${REPORT_API_KEY}"})

    assert clean["structured_secret_occurrences"] == 0
    assert clean["verdict"] == "PASS"
    assert literal["structured_secret_occurrences"] == 1
    assert literal["verdict"] == "FAIL"
    assert mixed["structured_secret_occurrences"] == 1
    assert mixed["verdict"] == "FAIL"
