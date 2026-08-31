from __future__ import annotations

import importlib
from collections.abc import Mapping
from io import BytesIO
from typing import Any

import pytest
from botocore.awsrequest import AWSResponse  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    ClientError,
    EndpointConnectionError,
)

from robin.prospective_observatory.chronos_control_plane import ConditionalPutOutcome
from robin.prospective_observatory.chronos_r2 import (
    MAX_R2_OBJECT_BYTES,
    ChronosR2ConditionalStore,
    ChronosR2Error,
    _deny_s3_head_bucket,
    _never_retry_s3,
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
            "ContentLength": len(b"payload"),
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


class _TrackedBody:
    def __init__(self, payload: bytes, *, fail_read: bool = False) -> None:
        self.payload = payload
        self.fail_read = fail_read
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if self.fail_read:
            raise OSError("synthetic read failure")
        return self.payload[:size]

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("content_length", [True, -1, MAX_R2_OBJECT_BYTES + 1, "7", None])
def test_get_rejects_invalid_declared_length(content_length: object) -> None:
    body = _TrackedBody(b"payload")
    client = FakeClient(
        get_response={"Body": body, "ContentLength": content_length, "Metadata": {}}
    )
    with pytest.raises(ChronosR2Error, match="CHRONOS_R2_BODY_INVALID"):
        ChronosR2ConditionalStore(client, "bucket").get_object("key")
    assert body.read_sizes == []
    assert body.closed is True


def test_get_is_bounded_closes_body_and_rejects_length_mismatch() -> None:
    body = _TrackedBody(b"payload-extra")
    client = FakeClient(get_response={"Body": body, "ContentLength": 7, "Metadata": {}})
    with pytest.raises(ChronosR2Error, match="CHRONOS_R2_BODY_INVALID"):
        ChronosR2ConditionalStore(client, "bucket").get_object("key")
    assert body.read_sizes == [MAX_R2_OBJECT_BYTES + 1]
    assert body.closed is True


def test_get_closes_body_when_bounded_read_fails() -> None:
    body = _TrackedBody(b"payload", fail_read=True)
    client = FakeClient(get_response={"Body": body, "ContentLength": 7, "Metadata": {}})
    with pytest.raises(ChronosR2Error, match="CHRONOS_R2_BODY_READ_FAILED"):
        ChronosR2ConditionalStore(client, "bucket").get_object("key")
    assert body.closed is True


def test_factory_disables_all_sdk_write_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    client = FakeClient()
    registrations: list[tuple[object, ...]] = []

    class Events:
        def register_first(self, *args: object, **kwargs: object) -> None:
            registrations.append((*args, kwargs))

    class Meta:
        events = Events()

    client.meta = Meta()  # type: ignore[attr-defined]

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
            "R2_ACCOUNT_ID": "a" * 32,
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
    assert getattr(config, "proxies") == {}
    assert registrations == [
        (
            "needs-retry.s3.PutObject",
            _never_retry_s3,
            {"unique_id": "chronos-r2-no-retry-putobject"},
        ),
        (
            "needs-retry.s3.GetObject",
            _never_retry_s3,
            {"unique_id": "chronos-r2-no-retry-getobject"},
        ),
        (
            "before-call.s3.HeadBucket",
            _deny_s3_head_bucket,
            {"unique_id": "chronos-r2-no-head-bucket"},
        ),
    ]
    assert captured["name"] == "s3"
    assert captured["endpoint_url"] == f"https://{'a' * 32}.r2.cloudflarestorage.com"


class _RawAwsBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def stream(self, _amt: int | None = None, decode_content: bool = False) -> list[bytes]:
        assert decode_content is False
        return [self.payload]


def _real_r2_client() -> Any:
    client, _bucket = create_single_attempt_r2_client(
        {
            "R2_ACCOUNT_ID": "a" * 32,
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }
    )
    return client


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (301, "PermanentRedirect"),
        (307, "TemporaryRedirect"),
        (400, "AuthorizationHeaderMalformed"),
    ],
)
def test_real_botocore_s3_redirect_errors_never_retry_transport(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
) -> None:
    client = _real_r2_client()
    calls: list[str] = []
    payload = (
        f"<Error><Code>{code}</Code><Region>us-east-1</Region><Message>redirect</Message></Error>"
    ).encode()

    def send(request: object) -> AWSResponse:
        url = str(getattr(request, "url"))
        calls.append(url)
        return AWSResponse(
            url,
            status,
            {
                "content-type": "application/xml",
                "content-length": str(len(payload)),
                "x-amz-bucket-region": "us-east-1",
            },
            _RawAwsBody(payload),
        )

    monkeypatch.setattr(client._endpoint.http_session, "send", send)
    with pytest.raises(Exception):
        client.put_object(Bucket="bucket", Key="key", Body=b"value", IfNoneMatch="*")
    assert len(calls) == 1


def test_real_botocore_transport_exception_never_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _real_r2_client()
    calls: list[str] = []

    def send(request: object) -> AWSResponse:
        url = str(getattr(request, "url"))
        calls.append(url)
        raise EndpointConnectionError(endpoint_url=url)

    monkeypatch.setattr(client._endpoint.http_session, "send", send)
    with pytest.raises(EndpointConnectionError):
        client.get_object(Bucket="bucket", Key="key")
    assert len(calls) == 1


def test_real_botocore_region_probe_is_locally_denied_without_second_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _real_r2_client()
    sends: list[str] = []
    payload = b"<Error><Code>PermanentRedirect</Code><Message>redirect</Message></Error>"

    def send(request: object) -> AWSResponse:
        url = str(getattr(request, "url"))
        sends.append(url)
        return AWSResponse(
            url,
            301,
            {"content-type": "application/xml", "content-length": str(len(payload))},
            _RawAwsBody(payload),
        )

    monkeypatch.setattr(client._endpoint.http_session, "send", send)
    with pytest.raises(ChronosR2Error, match="CHRONOS_R2_HEAD_FORBIDDEN"):
        client.put_object(Bucket="bucket", Key="key", Body=b"value", IfNoneMatch="*")
    assert len(sends) == 1


@pytest.mark.parametrize(
    ("name", "value", "code"),
    [
        ("R2_ACCOUNT_ID", "account", "CHRONOS_R2_ACCOUNT_ID_INVALID"),
        ("R2_ACCOUNT_ID", "a" * 31 + ".", "CHRONOS_R2_ACCOUNT_ID_INVALID"),
        ("R2_BUCKET_NAME", "UPPER", "CHRONOS_R2_BUCKET_INVALID"),
        ("R2_BUCKET_NAME", "bad..bucket", "CHRONOS_R2_BUCKET_INVALID"),
        ("R2_BUCKET_NAME", "127.0.0.1", "CHRONOS_R2_BUCKET_INVALID"),
    ],
)
def test_factory_rejects_endpoint_injection_before_import(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    code: str,
) -> None:
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda _name: pytest.fail("boto import reached"),
    )
    environment = {
        "R2_ACCOUNT_ID": "a" * 32,
        "R2_ACCESS_KEY_ID": "access",
        "R2_SECRET_ACCESS_KEY": "secret",
        "R2_BUCKET_NAME": "bucket",
    }
    environment[name] = value
    with pytest.raises(ChronosR2Error, match=code):
        create_single_attempt_r2_client(environment)


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
