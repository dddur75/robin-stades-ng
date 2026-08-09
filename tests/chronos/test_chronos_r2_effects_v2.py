from __future__ import annotations

import importlib
from collections.abc import Mapping
from io import BytesIO
from typing import Any

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from robin.prospective_observatory.chronos_control_plane import ConditionalPutOutcome
from robin.prospective_observatory.chronos_r2 import (
    ChronosR2ConditionalStore,
    ChronosR2Error,
    create_single_attempt_r2_client,
)


def client_error(code: str, status: int | None) -> ClientError:
    metadata: dict[str, object] = {"RequestId": "request-1"}
    if status is not None:
        metadata["HTTPStatusCode"] = status
    return ClientError(
        {
            "Error": {"Code": code, "Message": "test"},
            "ResponseMetadata": metadata,
        },
        "PutObject",
    )


class FakeClient:
    def __init__(
        self,
        *,
        put_response: Mapping[str, object] | None = None,
        put_error: ClientError | None = None,
        get_response: Mapping[str, object] | None = None,
        get_error: ClientError | None = None,
    ) -> None:
        self.put_response = put_response or {
            "ETag": '"etag"',
            "ResponseMetadata": {"RequestId": "created-1"},
        }
        self.put_error = put_error
        self.get_response = get_response or {
            "Body": BytesIO(b"payload"),
            "Metadata": {"operation_id": "abc"},
        }
        self.get_error = get_error
        self.permit_committed = False
        self.put_kwargs: dict[str, object] = {}

    def put_object(self, **kwargs: object) -> Mapping[str, object]:
        assert self.permit_committed
        self.put_kwargs = kwargs
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    def get_object(self, **kwargs: object) -> Mapping[str, object]:
        del kwargs
        if self.get_error is not None:
            raise self.get_error
        return self.get_response


def test_permit_callback_precedes_put_and_request_is_conditional() -> None:
    client = FakeClient()
    store = ChronosR2ConditionalStore(client, "bucket")

    def permit() -> None:
        client.permit_committed = True

    result = store.put_if_absent(
        "key",
        b"payload",
        metadata={"operation_id": "abc"},
        on_dispatch=permit,
    )
    assert result.outcome is ConditionalPutOutcome.CREATED
    assert result.transport_attempts == 1
    assert result.automatic_retry_possible is False
    assert client.put_kwargs == {
        "Bucket": "bucket",
        "Key": "key",
        "Body": b"payload",
        "IfNoneMatch": "*",
        "Metadata": {"operation_id": "abc"},
    }


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("PreconditionFailed", 412, ConditionalPutOutcome.PRECONDITION_FAILED),
        ("UnknownPrecondition", 412, ConditionalPutOutcome.PRECONDITION_FAILED),
        ("412", 412, ConditionalPutOutcome.PRECONDITION_FAILED),
        ("ConditionalRequestConflict", 409, ConditionalPutOutcome.CONFLICT),
        ("PreconditionFailed", 409, ConditionalPutOutcome.CONFLICT),
        ("ConditionalRequestConflict", 412, ConditionalPutOutcome.PRECONDITION_FAILED),
        ("Conflict", 409, ConditionalPutOutcome.CONFLICT),
        ("409", 409, ConditionalPutOutcome.CONFLICT),
        ("AccessDenied", 403, ConditionalPutOutcome.DEFINITE_FAILURE),
        ("RequestTimeout", 400, ConditionalPutOutcome.AMBIGUOUS),
        ("RequestTimeout", 408, ConditionalPutOutcome.AMBIGUOUS),
        ("TooEarly", 425, ConditionalPutOutcome.AMBIGUOUS),
        ("SlowDown", 429, ConditionalPutOutcome.AMBIGUOUS),
        ("UnknownClientError", 418, ConditionalPutOutcome.AMBIGUOUS),
        ("InternalError", 500, ConditionalPutOutcome.AMBIGUOUS),
        ("PreconditionFailed", 500, ConditionalPutOutcome.AMBIGUOUS),
        ("ConditionalRequestConflict", 500, ConditionalPutOutcome.AMBIGUOUS),
        ("PreconditionFailed", None, ConditionalPutOutcome.PRECONDITION_FAILED),
        ("ConditionalRequestConflict", None, ConditionalPutOutcome.CONFLICT),
    ],
)
def test_409_412_and_ambiguous_responses_are_distinct(
    code: str,
    status: int | None,
    expected: ConditionalPutOutcome,
) -> None:
    client = FakeClient(put_error=client_error(code, status))
    client.permit_committed = True
    result = ChronosR2ConditionalStore(client, "bucket").put_if_absent(
        "key",
        b"payload",
        metadata={},
        on_dispatch=lambda: None,
    )
    assert result.outcome is expected
    assert result.request_id == "request-1"


def test_get_returns_exact_bytes_and_metadata_without_head_or_list() -> None:
    client = FakeClient()
    store = ChronosR2ConditionalStore(client, "bucket")
    observed = store.get_object("key")
    assert observed is not None
    assert observed.data == b"payload"
    assert observed.metadata == {"operation_id": "abc"}
    assert not hasattr(store, "list_objects")
    assert not hasattr(store, "head_object")
    assert not hasattr(store, "delete_object")


def test_get_missing_is_none_and_invalid_body_fails_closed() -> None:
    missing = FakeClient(get_error=client_error("NoSuchKey", 404))
    assert ChronosR2ConditionalStore(missing, "bucket").get_object("key") is None
    invalid = FakeClient(get_response={"Body": "not-readable", "Metadata": {}})
    with pytest.raises(ChronosR2Error, match="CHRONOS_R2_BODY_INVALID"):
        ChronosR2ConditionalStore(invalid, "bucket").get_object("key")


def test_factory_disables_all_sdk_write_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    client = FakeClient()

    class FakeBoto:
        @staticmethod
        def client(name: str, **kwargs: object) -> FakeClient:
            captured["name"] = name
            captured.update(kwargs)
            return client

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: FakeBoto(),
    )
    created, bucket = create_single_attempt_r2_client(
        {
            "R2_ACCOUNT_ID": "account",
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }
    )
    assert created is client
    assert bucket == "bucket"
    config = captured["config"]
    assert getattr(config, "retries") == {
        "total_max_attempts": 1,
        "mode": "standard",
    }
    assert captured["name"] == "s3"


def test_factory_requires_all_secrets_without_calling_boto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden(name: str) -> Any:
        nonlocal called
        called = True
        raise AssertionError(name)

    monkeypatch.setattr(importlib, "import_module", forbidden)
    with pytest.raises(ChronosR2Error, match="CHRONOS_MISSING_SECRET"):
        create_single_attempt_r2_client({})
    assert called is False
