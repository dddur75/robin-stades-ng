from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

import scripts.github_release_attestation_v2 as attestation

REPOSITORY = "dddur75/robin-stades-ng"
WORKFLOW = ".github/workflows/chronos-neon-branch-identity-v2.yml"
RUN_ID = "123456789"
MAIN_SHA = "1" * 40
ARTIFACT = f"chronos-neon-branch-identity-v2-{RUN_ID}"
FILENAME = "chronos-neon-branch-identity-v2.json"


def _zip(*names: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name in names:
            bundle.writestr(name, b'{"attested":true}\n')
    return stream.getvalue()


def _responses(archive: bytes, *, artifacts: list[object] | None = None):
    artifact_rows: list[object] = artifacts or [
        {
            "id": 987,
            "name": ARTIFACT,
            "expired": False,
            "size_in_bytes": len(archive),
            "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
            "workflow_run": {"id": int(RUN_ID), "head_sha": MAIN_SHA},
        }
    ]

    def api(
        path: str,
        *,
        binary: bool = False,
        effect_deadline_epoch: float | None = None,
        effect_deadline_monotonic: float | None = None,
    ) -> bytes | dict[str, Any]:
        assert effect_deadline_epoch is None
        assert effect_deadline_monotonic is None
        if path.endswith(f"/actions/runs/{RUN_ID}"):
            return {
                "id": int(RUN_ID),
                "run_attempt": 1,
                "head_sha": MAIN_SHA,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
                "updated_at": "2026-08-30T20:00:00Z",
                "path": WORKFLOW,
                "repository": {"full_name": REPOSITORY},
            }
        if path.endswith(f"/actions/runs/{RUN_ID}/artifacts?per_page=100"):
            return {"total_count": len(artifact_rows), "artifacts": artifact_rows}
        if path.endswith("/actions/artifacts/987/zip") and binary:
            return archive
        raise AssertionError(path)

    return api


def _attest(tmp_path: Path) -> dict[str, Any]:
    return attestation.attest_and_download_v2(
        repository=REPOSITORY,
        workflow_path=WORKFLOW,
        run_id=RUN_ID,
        main_sha=MAIN_SHA,
        artifact_name=ARTIFACT,
        artifact_filename=FILENAME,
        output_path=tmp_path / FILENAME,
    )


def test_v2_attestation_accepts_one_exact_root_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _zip(FILENAME)
    monkeypatch.setattr(attestation, "_api", _responses(archive))
    report = _attest(tmp_path)
    assert (tmp_path / FILENAME).read_bytes() == b'{"attested":true}\n'
    assert report["archive_sha256"] == hashlib.sha256(archive).hexdigest()


@pytest.mark.parametrize(
    "stage",
    (
        "RECOVERY_IDENTITY_V2",
        "DURABLE_IDENTITY_SEAL_V2",
        "PRODUCTION_PREFLIGHT_V2",
        "MIGRATE_0015",
        "VERIFY_0015",
        "LIVE_ONCE",
    ),
)
def test_v2_failure_attestation_accepts_only_exact_lf_terminated_supervisor_payload(
    stage: str,
) -> None:
    if stage == "RECOVERY_IDENTITY_V2":
        from scripts.chronos_neon_branch_identity_v2 import (
            IdentityExecutionState,
            _failure_report,
        )

        document = _failure_report(
            RuntimeError("synthetic"),
            IdentityExecutionState(),
            conservative_timeout=True,
            observed_at="2026-08-30T20:00:00Z",
        )
    elif stage == "DURABLE_IDENTITY_SEAL_V2":
        from scripts.seal_chronos_identity_go_v2 import _supervisor_fallback

        document = _supervisor_fallback()
    elif stage in {"PRODUCTION_PREFLIGHT_V2", "MIGRATE_0015", "VERIFY_0015"}:
        from scripts.chronos_production_recovery_v2 import _supervisor_fallback

        mode = {
            "PRODUCTION_PREFLIGHT_V2": "PREFLIGHT",
            "MIGRATE_0015": "MIGRATE",
            "VERIFY_0015": "VERIFY",
        }[stage]
        document = _supervisor_fallback(mode)
    else:
        from scripts.run_data_torrent_v2 import _supervisor_fallback

        document = _supervisor_fallback()
    exact = attestation.canonical_json_bytes(document) + b"\n"

    validated = attestation._validate_failure_payload_v2(
        stage=stage,
        payload=exact,
        main_sha=MAIN_SHA,
    )
    assert validated["effect_counter_certainty"] == "UNKNOWN_OR_UPPER_BOUND"
    for mutant in (exact[:-1], exact + b"\n"):
        with pytest.raises(
            attestation.GitHubReleaseAttestationV2Error,
            match="GITHUB_ATTESTATION_V2_FAILURE_PAYLOAD_INVALID",
        ):
            attestation._validate_failure_payload_v2(
                stage=stage,
                payload=mutant,
                main_sha=MAIN_SHA,
            )


def test_v2_bundle_attestation_binds_every_exact_flat_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filenames = ("a.json", "b.csv", "c.md")
    archive = _zip(*filenames)
    monkeypatch.setattr(attestation, "_api", _responses(archive))
    output = tmp_path / "bundle"
    report = attestation.attest_and_download_bundle_v2(
        repository=REPOSITORY,
        workflow_path=WORKFLOW,
        run_id=RUN_ID,
        main_sha=MAIN_SHA,
        artifact_name=ARTIFACT,
        expected_filenames=filenames,
        output_dir=output,
    )
    assert report["schema_version"] == "github-artifact-bundle-attestation-v2"
    assert report["archive_sha256"] == hashlib.sha256(archive).hexdigest()
    assert [item["filename"] for item in report["members"]] == list(filenames)
    assert all((output / filename).read_bytes() == b'{"attested":true}\n' for filename in filenames)


@pytest.mark.parametrize(
    "expected,names",
    [
        (("a.json", "b.json"), ("a.json",)),
        (("a.json",), ("a.json", "extra.json")),
        (("a.json",), ("nested/a.json",)),
        (("a.json",), ("a.json", "a.json")),
    ],
)
def test_v2_bundle_attestation_rejects_missing_extra_nested_or_duplicate_member(
    expected: tuple[str, ...],
    names: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _zip(*names)
    monkeypatch.setattr(attestation, "_api", _responses(archive))
    output = tmp_path / "bundle"
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_FILE_MISMATCH",
    ):
        attestation.attest_and_download_bundle_v2(
            repository=REPOSITORY,
            workflow_path=WORKFLOW,
            run_id=RUN_ID,
            main_sha=MAIN_SHA,
            artifact_name=ARTIFACT,
            expected_filenames=expected,
            output_dir=output,
        )
    assert not output.exists()


@pytest.mark.parametrize("run_id", ["0", "01", "9" * 19, "9" * 5000])
def test_v2_attestation_rejects_noncanonical_or_unbounded_run_id_before_api(
    run_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_calls: list[str] = []
    monkeypatch.setattr(
        attestation,
        "_api",
        lambda path, **_kwargs: api_calls.append(path) or pytest.fail("API reached"),
    )
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_INPUT_INVALID",
    ):
        attestation.attest_and_download_v2(
            repository=REPOSITORY,
            workflow_path=WORKFLOW,
            run_id=run_id,
            main_sha=MAIN_SHA,
            artifact_name=f"chronos-neon-branch-identity-v2-{run_id}",
            artifact_filename=FILENAME,
            output_path=tmp_path / FILENAME,
        )
    assert api_calls == []
    assert not (tmp_path / FILENAME).exists()


@pytest.mark.parametrize(
    "names",
    [
        (f"nested/{FILENAME}",),
        (f"nested\\{FILENAME}",),
        ("directory/", FILENAME),
        (FILENAME, "extra.json"),
    ],
)
def test_v2_attestation_rejects_non_exact_zip_topology(
    names: tuple[str, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _zip(*names)
    monkeypatch.setattr(attestation, "_api", _responses(archive))
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_FILE_MISMATCH",
    ):
        _attest(tmp_path)
    assert not (tmp_path / FILENAME).exists()


def test_v2_attestation_rejects_non_object_artifact_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _zip(FILENAME)
    monkeypatch.setattr(attestation, "_api", _responses(archive, artifacts=["forged"]))
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_LIST_INVALID",
    ):
        _attest(tmp_path)


class _RawHeaders:
    def __init__(self, lengths: list[str]) -> None:
        self._lengths = lengths

    def getlist(self, _name: str) -> list[str]:
        return self._lengths


class _Response:
    def __init__(
        self,
        *,
        status_code: int,
        chunks: list[bytes],
        headers: dict[str, str] | None = None,
        lengths: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {}
        self.raw = type("Raw", (), {"headers": _RawHeaders(lengths or [])})()
        self.closed = False

    def iter_content(self, *, chunk_size: int):
        assert chunk_size == 64 * 1024
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def test_direct_api_is_proxy_free_streaming_and_github_com_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"ok":true}'
    response = _Response(
        status_code=200,
        chunks=[payload],
        lengths=[str(len(payload))],
    )
    observed: dict[str, object] = {}

    class Session:
        trust_env = True

        def mount(self, prefix: str, adapter: object) -> None:
            observed["mount"] = (prefix, adapter)

        def get(self, url: str, **kwargs: object) -> _Response:
            observed["url"] = url
            observed["kwargs"] = kwargs
            return response

        def close(self) -> None:
            observed["closed"] = True

    session = Session()
    monkeypatch.setattr(attestation.requests, "Session", lambda: session)
    body = attestation._api_direct(
        f"repos/{REPOSITORY}/actions/runs/{RUN_ID}",
        token="synthetic-token",
        binary=False,
    )

    assert body == payload
    assert session.trust_env is False
    assert observed["url"] == (f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}")
    prefix, adapter = observed["mount"]  # type: ignore[misc]
    assert prefix == "https://"
    assert adapter.max_retries.total == 0
    assert adapter.max_retries.redirect == 0
    kwargs = observed["kwargs"]  # type: ignore[assignment]
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    assert kwargs["headers"]["X-GitHub-Api-Version"] == "2026-03-10"
    assert response.closed is True
    assert observed["closed"] is True


def test_direct_archive_refuses_invalid_redirect_before_second_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(
        status_code=302,
        chunks=[],
        headers={"Location": "https://evil.example/archive.zip"},
    )
    calls = 0

    class Session:
        trust_env = True

        def mount(self, _prefix: str, _adapter: object) -> None:
            return None

        def get(self, _url: str, **_kwargs: object) -> _Response:
            nonlocal calls
            calls += 1
            return response

        def close(self) -> None:
            return None

    monkeypatch.setattr(attestation.requests, "Session", Session)
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_REDIRECT_INVALID",
    ):
        attestation._api_direct(
            f"repos/{REPOSITORY}/actions/artifacts/987/zip",
            token="synthetic-token",
            binary=True,
        )
    assert calls == 1
    assert response.closed is True


@pytest.mark.parametrize(
    "archive_host",
    [
        "pipelines.actions.githubusercontent.com",
        "results.blob.core.windows.net",
    ],
)
def test_direct_archive_follows_one_validated_redirect_without_forwarding_token(
    archive_host: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = b"synthetic-archive"
    redirect = _Response(
        status_code=302,
        chunks=[],
        headers={"Location": f"https://{archive_host}/bounded/archive.zip?sig=opaque"},
    )
    downloaded = _Response(
        status_code=200,
        chunks=[archive],
        lengths=[str(len(archive))],
    )
    calls: list[tuple[str, dict[str, object]]] = []

    class Session:
        trust_env = True

        def mount(self, _prefix: str, _adapter: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> _Response:
            calls.append((url, kwargs))
            return redirect if len(calls) == 1 else downloaded

        def close(self) -> None:
            return None

    monkeypatch.setattr(attestation.requests, "Session", Session)
    assert (
        attestation._api_direct(
            f"repos/{REPOSITORY}/actions/artifacts/987/zip",
            token="synthetic-token",
            binary=True,
        )
        == archive
    )
    assert len(calls) == 2
    assert calls[0][0].startswith("https://api.github.com/")
    assert calls[0][1]["allow_redirects"] is False
    assert calls[1][0].startswith(f"https://{archive_host}/")
    assert calls[1][1]["allow_redirects"] is False
    assert "Authorization" not in calls[1][1]["headers"]
    assert redirect.closed is True
    assert downloaded.closed is True


def test_exact_main_sha_uses_one_bounded_api_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def api(
        path: str,
        *,
        binary: bool = False,
        effect_deadline_epoch: float | None = None,
        effect_deadline_monotonic: float | None = None,
    ) -> dict[str, object]:
        calls.append(path)
        assert binary is False
        assert effect_deadline_epoch is None
        assert effect_deadline_monotonic is None
        return {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": MAIN_SHA},
        }

    monkeypatch.setattr(attestation, "_api", api)
    assert attestation.exact_main_sha_v2() == MAIN_SHA
    assert calls == [f"repos/{REPOSITORY}/git/ref/heads/main"]


def test_bounded_body_stops_before_oversize_sentinel() -> None:
    sentinel_reached = False

    class Response(_Response):
        def iter_content(self, *, chunk_size: int):
            nonlocal sentinel_reached
            assert chunk_size == 64 * 1024
            yield b"x" * attestation._MAX_BYTES
            yield b"x"
            sentinel_reached = True
            yield b"unreachable"

    response = Response(status_code=200, chunks=[])
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_RESPONSE_TOO_LARGE",
    ):
        attestation._bounded_body(response)
    assert sentinel_reached is False


def test_parent_api_uses_private_bounded_process_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    observed: dict[str, object] = {}
    shared: dict[str, object] = {}

    class Sender:
        def send(self, value: object) -> None:
            shared["message"] = value

        def close(self) -> None:
            return None

    class Receiver:
        def poll(self, timeout: float) -> bool:
            observed["poll_timeout"] = timeout
            return "message" in shared

        def recv(self) -> object:
            return shared["message"]

        def close(self) -> None:
            observed["receiver_closed"] = True

    class Process:
        exitcode = 0

        def __init__(self, *, target: object, kwargs: dict[str, object]) -> None:
            observed["target"] = target
            observed["process_kwargs"] = kwargs
            self.target = target
            self.kwargs = kwargs

        def start(self) -> None:
            self.target(**self.kwargs)  # type: ignore[operator]

        def join(self, timeout: float) -> None:
            observed["join_timeout"] = timeout

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            observed["process_closed"] = True

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Receiver, Sender]:
            assert duplex is False
            return Receiver(), Sender()

        def Process(self, *, target: object, kwargs: dict[str, object]) -> Process:
            return Process(target=target, kwargs=kwargs)

    monkeypatch.setattr(attestation.multiprocessing, "get_context", lambda mode: Context())
    monkeypatch.setattr(
        attestation,
        "_api_direct",
        lambda path, **_kwargs: observed.__setitem__("path", path) or b'{"ok":true}',
    )
    result = attestation._api(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}")
    assert observed["target"] is attestation._api_worker
    assert observed["path"] == f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"
    assert observed["receiver_closed"] is True
    assert observed["process_closed"] is True
    assert result == {"ok": True}
    assert "--bounded-api-child" not in Path(attestation.__file__).read_text(encoding="utf-8")


def test_effect_timeout_refuses_monotonic_expiry_despite_wall_clock_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attestation.time, "time", lambda: -10_000.0)
    monkeypatch.setattr(attestation.time, "monotonic", lambda: 500.0)
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_DEADLINE_EXCEEDED",
    ):
        attestation._effect_timeout(
            10_000.0,
            maximum=15.0,
            effect_deadline_monotonic=500.0,
        )


def test_parent_api_refuses_confirmed_child_after_exact_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    moments = iter((0.0, 0.0, 0.0, 5.0))
    monkeypatch.setattr(attestation.time, "time", lambda: 0.0)
    monkeypatch.setattr(attestation.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(attestation, "_effect_timeout", lambda *_a, **_k: 15.0)

    class Connection:
        def poll(self, _timeout: float) -> bool:
            return True

        def recv(self) -> tuple[str, bytes]:
            return "CONFIRMED", b'{"ok":true}'

        def close(self) -> None:
            return None

    class Process:
        exitcode = 0

        def start(self) -> None:
            return None

        def join(self, _timeout: float) -> None:
            return None

        def is_alive(self) -> bool:
            return False

        def close(self) -> None:
            return None

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:  # noqa: N802
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **_kwargs: object) -> Process:  # noqa: N802
            return Process()

    monkeypatch.setattr(attestation.multiprocessing, "get_context", lambda _mode: Context())
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_API_FAILED",
    ):
        attestation._api(
            f"repos/{REPOSITORY}/actions/runs/{RUN_ID}",
            effect_deadline_epoch=100.0,
            effect_deadline_monotonic=5.0,
        )


def test_private_api_child_timeout_terminates_then_kills_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    observed = {"terminate": 0, "kill": 0, "joins": []}

    class Connection:
        def poll(self, timeout: float) -> bool:
            assert timeout == attestation._API_CHILD_WORK_TIMEOUT_SECONDS
            return False

        def close(self) -> None:
            return None

    class Process:
        exitcode: int | None = None
        alive = True

        def start(self) -> None:
            return None

        def join(self, timeout: float) -> None:
            observed["joins"].append(timeout)  # type: ignore[union-attr]

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            observed["terminate"] += 1

        def kill(self) -> None:
            observed["kill"] += 1
            self.alive = False
            self.exitcode = -9

        def close(self) -> None:
            return None

    process = Process()

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **_kwargs: object) -> Process:
            return process

    monkeypatch.setattr(attestation.multiprocessing, "get_context", lambda mode: Context())
    with pytest.raises(
        attestation.GitHubReleaseAttestationV2Error,
        match="GITHUB_ATTESTATION_V2_API_FAILED",
    ):
        attestation._api(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}")
    assert observed["terminate"] == 1
    assert observed["kill"] == 1
