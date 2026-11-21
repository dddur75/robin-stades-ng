"""Source-scoped TLS repair; existing campaign transports stay immutable."""

from __future__ import annotations

import http.client
import ipaddress
import queue
import socket
import ssl
import threading
import time
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import certifi

from .collector import USER_AGENT
from .connectors import MAX_BYTES, Response, public_url


def verified_context(hostname: str, ca_sha256: str) -> ssl.SSLContext:
    if hostname != "stavka.tv":
        raise ValueError("unapproved CA source")
    import os

    if any(k in os.environ for k in ("SSLKEYLOGFILE", "SSL_CERT_FILE", "SSL_CERT_DIR")):
        raise ValueError("external TLS configuration")
    pem = Path(certifi.where()).read_bytes()
    if len(ca_sha256) != 64 or sha256(pem).hexdigest() != ca_sha256:
        raise ValueError("approved CA bundle changed")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cadata=pem.decode("ascii"))
    if (
        not ctx.check_hostname
        or ctx.verify_mode != ssl.CERT_REQUIRED
        or ctx.keylog_filename is not None
    ):
        raise ValueError("certificate verification required")
    return ctx


def public_get_stavka(url: str, *, ca_sha256: str, timeout: float = 12.0) -> Response:
    """Resolve once, reject non-public addresses, pin TCP and preserve TLS SNI.

    No redirects, proxies, cookies, credentials, retries or JavaScript execution.
    """
    parsed = urlsplit(public_url(url))
    hostname = parsed.hostname
    if parsed.scheme != "https" or hostname != "stavka.tv":
        raise ValueError("unapproved TLS source")
    ctx = verified_context(hostname, ca_sha256)
    if hostname is None:
        raise ValueError("public hostname required")
    port = 443 if parsed.scheme == "https" else 80
    deadline = time.monotonic() + timeout

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("transfer deadline")
        return min(12.0, value)

    resolved: queue.Queue[Any] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            resolved.put(socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM))
        except OSError as exc:
            resolved.put(exc)

    threading.Thread(target=resolve, daemon=True).start()
    try:
        addresses = resolved.get(timeout=remaining())
    except queue.Empty as exc:
        raise TimeoutError("DNS deadline") from exc
    if isinstance(addresses, OSError):
        raise addresses
    if not addresses or any(
        info[0] not in {socket.AF_INET, socket.AF_INET6}
        or info[4][1] != 443
        or not ipaddress.ip_address(info[4][0]).is_global
        or ipaddress.ip_address(info[4][0]).is_multicast
        for info in addresses
    ):
        raise ValueError("non-public DNS result")
    family, socktype, proto, _, address = addresses[0]
    connection = http.client.HTTPConnection(hostname, port, timeout=12)
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(remaining())
    active_socket = [sock]
    expired = threading.Event()

    def interrupt() -> None:
        expired.set()
        try:
            active_socket[0].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        active_socket[0].close()

    guard = threading.Timer(max(0.001, deadline - time.monotonic()), interrupt)
    guard.daemon = True
    guard.start()
    try:
        sock.connect(address)
        sock.settimeout(remaining())
        connection.sock = (
            ctx.wrap_socket(sock, server_hostname=hostname) if parsed.scheme == "https" else sock
        )
        active_socket[0] = connection.sock
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection.request(
            "GET", target, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        if connection.sock is None:
            raise OSError("public transport unavailable")
        transport = connection.sock
        transport.settimeout(remaining())
        response = connection.getresponse()
        # Error/redirect documents are not content and must not be stored/parsed.
        body = b""
        if response.status == 200:
            chunks = []
            size = 0
            while size <= MAX_BYTES:
                transport.settimeout(remaining())
                chunk = response.read1(min(65_536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            body = b"".join(chunks)
        if len(body) > MAX_BYTES:
            raise ValueError("response size limit")
        if expired.is_set():
            raise TimeoutError("transfer deadline")
        return Response(
            response.status,
            body,
            response.getheader("Content-Type", ""),
            response.getheader("Location"),
        )
    except (OSError, http.client.HTTPException) as exc:
        if expired.is_set():
            raise TimeoutError("transfer deadline") from exc
        raise
    finally:
        guard.cancel()
        connection.close()
        sock.close()
