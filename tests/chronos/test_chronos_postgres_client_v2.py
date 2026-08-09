from __future__ import annotations

import traceback
from types import SimpleNamespace
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from robin.prospective_observatory.chronos_control_plane import (
    ChronosControlPlaneError,
)
from robin.prospective_observatory.chronos_postgres import (
    SQLAlchemyPostgresFunctionClient,
)


class FakeMappings:
    @staticmethod
    def one_or_none() -> dict[str, object]:
        return {"event_type": "PUT_DISPATCHED"}


class FakeResult:
    @staticmethod
    def mappings() -> FakeMappings:
        return FakeMappings()


class FakeConnection:
    def __init__(self, owner: FakeEngine) -> None:
        self.owner = owner

    def exec_driver_sql(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> FakeResult:
        assert self.owner.committed is False
        self.owner.statement = statement
        self.owner.parameters = parameters
        return FakeResult()


class FakeTransaction:
    def __init__(self, owner: FakeEngine) -> None:
        self.owner = owner

    def __enter__(self) -> FakeConnection:
        return FakeConnection(self.owner)

    def __exit__(self, *args: object) -> None:
        self.owner.committed = True


class FakeEngine:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self.hide_parameters = False
        self.committed = False
        self.statement = ""
        self.parameters: tuple[object, ...] = ()
        self.database_message = ""

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)


def test_function_result_is_returned_only_after_transaction_commit() -> None:
    engine = FakeEngine()
    client = SQLAlchemyPostgresFunctionClient(cast(Engine, cast(Any, engine)))
    row = client.fetch_one("SELECT function(%s)", ("permit",))
    assert engine.committed is True
    assert engine.statement == "SELECT function(%s)"
    assert engine.parameters == ("permit",)
    assert row == {"event_type": "PUT_DISPATCHED"}
    assert engine.hide_parameters is True


class FailingConnection(FakeConnection):
    def exec_driver_sql(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> FakeResult:
        raise DBAPIError(
            statement,
            parameters,
            RuntimeError(self.owner.database_message),
            hide_parameters=False,
        )


class FailingTransaction(FakeTransaction):
    def __enter__(self) -> FailingConnection:
        return FailingConnection(self.owner)


class FailingEngine(FakeEngine):
    def __init__(self, database_message: str) -> None:
        super().__init__()
        self.database_message = database_message

    def begin(self) -> FailingTransaction:
        return FailingTransaction(self)


@pytest.mark.parametrize(
    ("database_message", "expected"),
    [
        ("CHRONOS_AUTHORITY_NOT_ACTIVE: details", "CHRONOS_AUTHORITY_NOT_ACTIVE"),
        ("arbitrary database failure", "CHRONOS_POSTGRESQL_CALL_FAILED"),
    ],
)
def test_database_errors_are_allowlisted_without_leaking_the_nonce(
    database_message: str,
    expected: str,
) -> None:
    generation_nonce = bytes.fromhex("ab" * 32)
    engine = FailingEngine(database_message)
    client = SQLAlchemyPostgresFunctionClient(cast(Engine, cast(Any, engine)))
    with pytest.raises(ChronosControlPlaneError) as captured:
        client.fetch_one("SELECT function(%s)", (generation_nonce,))
    assert str(captured.value) == expected
    rendered = "".join(traceback.format_exception(captured.value))
    for secret_form in (repr(generation_nonce), generation_nonce.hex()):
        assert secret_form not in str(captured.value)
        assert secret_form not in repr(captured.value)
        assert secret_form not in rendered
    assert captured.value.__suppress_context__ is True
    assert captured.value.__context__ is None
    assert engine.hide_parameters is True


def test_non_postgresql_engine_is_rejected() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with pytest.raises(ChronosControlPlaneError, match="CHRONOS_POSTGRESQL_REQUIRED"):
        SQLAlchemyPostgresFunctionClient(engine)
    engine.dispose()
