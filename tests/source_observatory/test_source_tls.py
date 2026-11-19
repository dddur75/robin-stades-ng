import ssl
from hashlib import sha256
from pathlib import Path

import certifi
import pytest

from robin.source_observatory.source_tls import public_get_stavka, verified_context


def test_explicit_existing_ca_retains_certificate_and_hostname_validation():
    pin = sha256(Path(certifi.where()).read_bytes()).hexdigest()
    c = verified_context("stavka.tv", pin)
    assert (
        c.check_hostname
        and c.verify_mode == ssl.CERT_REQUIRED
        and c.minimum_version >= ssl.TLSVersion.TLSv1_2
        and c.keylog_filename is None
    )


def test_changed_or_unapproved_ca_is_rejected_before_network(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: pytest.fail("network before CA proof")
    )
    with pytest.raises(ValueError, match="CA"):
        public_get_stavka("https://stavka.tv/robots.txt", ca_sha256="0" * 64)


def test_source_scope_and_keylog_are_not_widened(monkeypatch):
    pin = sha256(Path(certifi.where()).read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        verified_context("t.me", pin)
    monkeypatch.setenv("SSLKEYLOGFILE", "must-not-create")
    with pytest.raises(ValueError):
        verified_context("stavka.tv", pin)


def test_http_and_credential_urls_rejected_without_dns(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS"))
    for url in ["http://stavka.tv/", "https://u:p@stavka.tv/", "https://other.invalid/"]:
        with pytest.raises(ValueError):
            public_get_stavka(url, ca_sha256="0" * 64)


def test_multicast_dns_is_rejected_before_connect(monkeypatch):
    import socket

    pin = sha256(Path(certifi.where()).read_bytes()).hexdigest()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("224.0.0.1", 443))
        ],
    )
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("nonunicast connect"))
    with pytest.raises(ValueError, match="DNS"):
        public_get_stavka("https://stavka.tv/robots.txt", ca_sha256=pin)
