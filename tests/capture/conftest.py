from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("CAPTURE_TEST_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "gethostbyname", forbidden)
    monkeypatch.setattr(socket, "gethostbyname_ex", forbidden)
    monkeypatch.setattr(socket, "gethostbyaddr", forbidden)
    monkeypatch.setattr(socket, "getnameinfo", forbidden)


@pytest.fixture(scope="session")
def synthetic_pack() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "synthetic-odds-responses-v1.json"
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture
def no_network_counter() -> Iterator[dict[str, int]]:
    counter = {"network_calls": 0, "provider_calls": 0}
    yield counter
    assert counter == {"network_calls": 0, "provider_calls": 0}
