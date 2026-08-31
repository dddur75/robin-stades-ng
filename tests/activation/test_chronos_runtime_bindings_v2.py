from __future__ import annotations

import hashlib
import json
import subprocess
from base64 import b64encode
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.check_chronos_github_hold_v3 as hold
import scripts.install_chronos_runtime_bindings_v2 as installer
from robin.chronos_production import PRODUCTION_SAFETY_LOCKS, ChronosProductionError

MAIN_SHA = "a" * 40
OBSERVED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)
REAL_LOAD_PREFLIGHT_SOURCE = installer._load_preflight_source
REAL_REQUIRE_CANONICAL_PREFLIGHT_CACHE_PATH = installer._require_canonical_preflight_cache_path


@pytest.fixture(autouse=True)
def _exact_safety_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PRODUCTION_SAFETY_LOCKS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", "ab" * 32)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")


def test_gh_cli_requires_exact_binary_hash_size_and_version_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "gh.exe"
    binary.write_bytes(b"reviewed-gh-binary")
    monkeypatch.setattr(installer.shutil, "which", lambda _name: str(binary))
    monkeypatch.setattr(installer, "_PINNED_GH_CLI_SIZE", binary.stat().st_size)
    monkeypatch.setattr(
        installer,
        "_PINNED_GH_CLI_SHA256",
        hashlib.sha256(binary.read_bytes()).hexdigest(),
    )

    def completed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[str(binary), "--version"],
            returncode=0,
            stdout=("\n".join(installer._PINNED_GH_CLI_VERSION_LINES) + "\n").encode(),
        )

    monkeypatch.setattr(installer.subprocess, "run", completed)
    assert installer._require_pinned_gh_cli() == binary.resolve()

    def spoofed(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            args=[str(binary), "--version"],
            returncode=0,
            stdout=b"gh version 2.96.0 spoofed\n",
        )

    monkeypatch.setattr(installer.subprocess, "run", spoofed)
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_GH_VERSION_INVALID",
    ):
        installer._require_pinned_gh_cli()


def test_gh_cli_environment_is_github_com_only_and_ignores_ambient_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "exact-token")
    monkeypatch.setenv("GITHUB_TOKEN", "shadow-token")
    monkeypatch.setenv("GH_HOST", "evil.example")
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "enterprise-token")
    monkeypatch.setenv("GITHUB_ENTERPRISE_TOKEN", "enterprise-token-2")
    monkeypatch.setenv("GH_CONFIG_DIR", str(tmp_path / "evil-config"))
    monkeypatch.setenv("HTTPS_PROXY", "http://evil.example")
    monkeypatch.setenv("GH_BROWSER", "evil-browser")
    config_dir = tmp_path / "empty-config"

    environment = installer._github_cli_environment(
        config_dir=config_dir,
        require_token=True,
    )

    assert environment["GH_HOST"] == "github.com"
    assert environment["GH_TOKEN"] == "exact-token"
    assert environment["GH_CONFIG_DIR"] == str(config_dir)
    assert environment["GODEBUG"] == "http2client=0"
    assert "GH_HTTP_RETRY_MAX" not in environment
    for forbidden in (
        "GITHUB_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "HTTPS_PROXY",
        "GH_BROWSER",
    ):
        assert forbidden not in environment


def test_secret_encryption_uses_pinned_no_store_and_host_qualified_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    public_key = b64encode(b"k" * 32).decode("ascii")
    value = "value"
    ciphertext = b64encode(b"c" * (len(value.encode()) + 48)) + b"\n"
    observed: dict[str, object] = {}

    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=ciphertext,
            stderr=(
                "api trace\n"
                "* Request to https://api.github.com/repos/dddur75/robin-stades-ng/"
                "environments/chronos-control-plane-production/secrets/public-key\n"
                "> GET /repos/dddur75/robin-stades-ng/environments/"
                "chronos-control-plane-production/secrets/public-key HTTP/1.1\n"
                "< HTTP/1.1 200 OK\n"
                f'{{"key_id":"kid_1","key":"{public_key}"}}\n'
            ).encode(),
        )

    monkeypatch.setattr(installer.subprocess, "run", completed)
    encoded, key_id = installer._encrypt_secret_once(
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        value=value,
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        gh_cli_path=tmp_path / "gh.exe",
    )

    argv = observed["args"][0]  # type: ignore[index]
    kwargs = observed["kwargs"]  # type: ignore[assignment]
    assert argv == [
        str(tmp_path / "gh.exe"),
        "secret",
        "set",
        "CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        "--repo",
        "github.com/dddur75/robin-stades-ng",
        "--env",
        "chronos-control-plane-production",
        "--no-store",
    ]
    assert kwargs["input"] == value.encode()  # type: ignore[index]
    assert kwargs["env"]["GH_HOST"] == "github.com"  # type: ignore[index]
    assert encoded == ciphertext.decode().strip()
    assert key_id == "kid_1"


def test_secret_put_child_transport_has_exact_host_and_zero_retry_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Response:
        status_code = 204
        closed = False

        def close(self) -> None:
            self.closed = True

    response = Response()

    class Session:
        trust_env = True

        def mount(self, prefix: str, adapter: object) -> None:
            observed["mount"] = (prefix, adapter)

        def put(self, url: str, **kwargs: object) -> Response:
            observed["url"] = url
            observed["put"] = kwargs
            return response

        def close(self) -> None:
            observed["closed"] = True

    session = Session()
    monkeypatch.setattr(installer.requests, "Session", lambda: session)
    installer._put_encrypted_secret_direct(
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        encrypted_value="encrypted",
        key_id="kid_1",
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        token="synthetic-token",
        external_deadline_epoch=installer.time.time() + 1_000,
        external_deadline_monotonic=installer.time.monotonic() + 1_000,
    )

    assert session.trust_env is False
    assert observed["url"] == (
        "https://api.github.com/repos/dddur75/robin-stades-ng/environments/"
        "chronos-control-plane-production/secrets/CHRONOS_CONTROL_PLANE_GENERATION_NONCE"
    )
    put = observed["put"]  # type: ignore[assignment]
    assert put["allow_redirects"] is False
    assert put["stream"] is True
    assert put["json"] == {"encrypted_value": "encrypted", "key_id": "kid_1"}
    adapter = observed["mount"][1]  # type: ignore[index]
    assert adapter.max_retries.total == 0  # type: ignore[attr-defined]
    assert response.closed is True
    assert observed["closed"] is True


def test_secret_put_child_reserves_full_transport_window_after_session_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wall = [0.0]
    puts: list[str] = []
    monkeypatch.setattr(installer.time, "time", lambda: wall[0])
    monkeypatch.setattr(installer.time, "monotonic", lambda: 0.0)

    class Session:
        trust_env = True

        def mount(self, _prefix: str, _adapter: object) -> None:
            wall[0] = 90.5

        def put(self, url: str, **_kwargs: object) -> object:
            puts.append(url)
            pytest.fail("deadline-crossed PUT reached")

        def close(self) -> None:
            return None

    monkeypatch.setattr(installer.requests, "Session", Session)
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer._put_encrypted_secret_direct(
            name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
            encrypted_value="encrypted",
            key_id="kid_1",
            repository="dddur75/robin-stades-ng",
            environment="chronos-control-plane-production",
            token="synthetic-token",
            external_deadline_epoch=100.0,
            external_deadline_monotonic=100.0,
        )
    assert puts == []


def test_secret_put_parent_uses_one_disposable_child_with_total_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    observed: dict[str, object] = {}
    messages: list[tuple[str, None]] = []

    class Sender:
        def send(self, value: tuple[str, None]) -> None:
            messages.append(value)

        def close(self) -> None:
            return None

    class Receiver:
        def poll(self) -> bool:
            return bool(messages)

        def recv(self) -> tuple[str, None]:
            return messages.pop(0)

        def close(self) -> None:
            return None

    class Process:
        exitcode = 0

        def __init__(self, *, target: object, kwargs: dict[str, object]) -> None:
            observed["target"] = target
            observed["kwargs"] = kwargs

        def start(self) -> None:
            messages.append(("CONFIRMED", None))

        def join(self, timeout: float) -> None:
            observed.setdefault("joins", []).append(timeout)  # type: ignore[union-attr]

        def is_alive(self) -> bool:
            return False

        def terminate(self) -> None:
            pytest.fail("unexpected terminate")

        def kill(self) -> None:
            pytest.fail("unexpected kill")

        def close(self) -> None:
            observed["closed"] = True

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Receiver, Sender]:  # noqa: N802
            assert duplex is False
            return Receiver(), Sender()

        def Process(self, *, target: object, kwargs: dict[str, object]) -> Process:  # noqa: N802
            return Process(target=target, kwargs=kwargs)

    monkeypatch.setattr(installer.multiprocessing, "get_context", lambda mode: Context())
    report = tmp_path / "receipt.json"
    installer._put_encrypted_secret_once(
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        encrypted_value="encrypted",
        key_id="kid_1",
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        reservation_sha256="b" * 64,
        report_path=report,
        external_deadline_epoch=installer.time.time() + 1_000,
        external_deadline_monotonic=installer.time.monotonic() + 1_000,
    )
    assert observed["target"] is installer._secret_put_worker
    kwargs = observed["kwargs"]  # type: ignore[assignment]
    assert kwargs["token"] == "synthetic-token"
    assert kwargs["report_path"] == report
    assert observed["closed"] is True


def test_secret_put_worker_revalidates_exact_reservation_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", report)
    reservation = installer._reservation_bytes(main_sha=MAIN_SHA, preflight_run_id="300")
    report.write_bytes(reservation)
    monkeypatch.setattr(
        installer,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(installer, "assert_current_main", lambda **_kwargs: MAIN_SHA)
    writes: list[str] = []
    monkeypatch.setattr(
        installer,
        "_put_encrypted_secret_direct",
        lambda **kwargs: writes.append(str(kwargs["name"])),
    )
    messages: list[tuple[str, None]] = []

    class Connection:
        def send(self, value: tuple[str, None]) -> None:
            messages.append(value)

        def close(self) -> None:
            return None

    installer._secret_put_worker(
        Connection(),
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        encrypted_value="encrypted",
        key_id="kid_1",
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        token="synthetic-token",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        reservation_sha256=hashlib.sha256(reservation).hexdigest(),
        report_path=report,
        external_deadline_epoch=installer.time.time() + 1_000,
        external_deadline_monotonic=installer.time.monotonic() + 1_000,
    )
    assert messages == [("CONFIRMED", None)]
    assert writes == ["CHRONOS_CONTROL_PLANE_GENERATION_NONCE"]

    report.write_bytes(reservation + b" ")
    messages.clear()
    writes.clear()
    installer._secret_put_worker(
        Connection(),
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        encrypted_value="encrypted",
        key_id="kid_1",
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        token="synthetic-token",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        reservation_sha256=hashlib.sha256(reservation).hexdigest(),
        report_path=report,
        external_deadline_epoch=installer.time.time() + 1_000,
        external_deadline_monotonic=installer.time.monotonic() + 1_000,
    )
    assert messages == [("FAILED", None)]
    assert writes == []


def test_secret_put_worker_rechecks_monotonic_deadline_after_main_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", report)
    reservation = installer._reservation_bytes(main_sha=MAIN_SHA, preflight_run_id="300")
    report.write_bytes(reservation)
    monkeypatch.setattr(
        installer,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: None,
    )
    monotonic = [0.0]
    monkeypatch.setattr(installer.time, "time", lambda: 0.0)
    monkeypatch.setattr(installer.time, "monotonic", lambda: monotonic[0])

    def advance_during_main_validation(**_kwargs: object) -> str:
        monotonic[0] = 90.0
        return MAIN_SHA

    monkeypatch.setattr(installer, "assert_current_main", advance_during_main_validation)
    writes: list[str] = []
    monkeypatch.setattr(
        installer,
        "_put_encrypted_secret_direct",
        lambda **kwargs: writes.append(str(kwargs["name"])),
    )
    messages: list[tuple[str, None]] = []

    class Connection:
        def send(self, value: tuple[str, None]) -> None:
            messages.append(value)

        def close(self) -> None:
            return None

    installer._secret_put_worker(
        Connection(),
        name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
        encrypted_value="encrypted",
        key_id="kid_1",
        repository="dddur75/robin-stades-ng",
        environment="chronos-control-plane-production",
        token="synthetic-token",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        reservation_sha256=hashlib.sha256(reservation).hexdigest(),
        report_path=report,
        external_deadline_epoch=1_000.0,
        external_deadline_monotonic=100.0,
    )
    assert messages == [("FAILED", None)]
    assert writes == []


def test_public_key_trace_rejects_second_request() -> None:
    public_key = b64encode(b"k" * 32).decode("ascii")
    path = (
        "/repos/dddur75/robin-stades-ng/environments/"
        "chronos-control-plane-production/secrets/public-key"
    )
    trace = (
        f"* Request to https://api.github.com{path}\n"
        f"> GET {path} HTTP/1.1\n"
        "< HTTP/1.1 200 OK\n"
        f'{{"key_id":"kid_1","key":"{public_key}"}}\n'
        "> GET /unexpected HTTP/1.1\n"
    ).encode()
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_PUBLIC_KEY_INVALID",
    ):
        installer._public_key_trace(
            stderr=trace,
            repository="dddur75/robin-stades-ng",
            environment="chronos-control-plane-production",
        )


def _prepare(monkeypatch: pytest.MonkeyPatch, report_path: Path) -> None:
    monkeypatch.setattr(installer, "_REPOSITORY_ROOT", report_path.parent)
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", report_path)
    monkeypatch.setattr(installer, "_require_canonical_preflight_cache_path", lambda _path: None)
    payload = b"{}"
    monkeypatch.setattr(installer, "validate_data_torrent_recovery_v2_authority", lambda **_: None)
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_a, **_k: (
            payload,
            {"payload_sha256": hashlib.sha256(payload).hexdigest()},
        ),
    )
    monkeypatch.setattr(
        installer,
        "validate_preflight_controller_handoff_v2",
        lambda **_kwargs: "d" * 64,
    )
    monkeypatch.setattr(
        installer,
        "validate_preflight_artifact_v2",
        lambda *_a, **_k: {
            "preflight_run_id": "300",
            "preflight_hash": "b" * 64,
            "database_host": "ep-test.eu-central-1.aws.neon.tech",
            "database_port": 5432,
            "database_name": "db",
            "sslmode": "require",
            "channel_binding": "require",
            "created_at": "2026-08-30T11:00:00Z",
            "expires_at": "2026-08-30T13:00:00Z",
        },
    )
    monkeypatch.setattr(installer, "assert_current_main", lambda **_: MAIN_SHA)
    monkeypatch.setattr(installer, "_validate_global_hold", lambda **_: None)
    monkeypatch.setattr(installer, "_validate_no_concurrent_runs", lambda **_: None)
    monkeypatch.setattr(installer, "_require_pinned_gh_cli", lambda: Path("synthetic-gh.exe"))


def _preflight_cache(payload: bytes) -> dict[str, object]:
    return {
        "schema_version": "data-torrent-recovery-v2-singleton-cache-v1",
        "kind": "PREFLIGHT",
        "artifact_filename": "production-preflight-v2.json",
        "payload_base64": b64encode(payload).decode("ascii"),
        "attestation": {
            "schema_version": "github-artifact-attestation-v2",
            "repository": installer.EXPECTED_REPOSITORY,
            "workflow_path": ".github/workflows/chronos-production-bootstrap-v4.yml",
            "run_id": "300",
            "run_attempt": "1",
            "head_sha": MAIN_SHA,
            "artifact_id": 900,
            "artifact_name": "production-preflight-v2-300",
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "archive_sha256": "c" * 64,
        },
    }


def _write_preflight_cache(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_install_consumes_the_canonical_r3_predecessor_cache_without_raw_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    cache_path = (
        tmp_path
        / ".torrent"
        / "release"
        / "recovery-v2-predecessor-cache"
        / "production-preflight-v2.json"
    )
    payload = b"{}\n"
    _write_preflight_cache(cache_path, _preflight_cache(payload))
    _prepare(monkeypatch, receipt)
    monkeypatch.setattr(installer, "_load_preflight_source", REAL_LOAD_PREFLIGHT_SOURCE)
    monkeypatch.setattr(
        installer,
        "_require_canonical_preflight_cache_path",
        REAL_REQUIRE_CANONICAL_PREFLIGHT_CACHE_PATH,
    )
    monkeypatch.setattr(installer, "_set_secret", lambda **_kwargs: None)
    report = installer.install(
        preflight_artifact=cache_path,
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        report_path=receipt,
        observed_at=OBSERVED_AT,
    )
    assert report["verdict"] == "FOUR_RUNTIME_BINDINGS_INSTALLED_V2"
    assert report["preflight_controller_receipt_sha256"] == "d" * 64
    assert not (tmp_path / "production-preflight-v2.json").exists()
    source = Path(installer.__file__).read_text(encoding="utf-8")
    assert "attest_and_download_v2" not in source


def test_noncanonical_r3_cache_path_is_rejected_before_load_reservation_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    _prepare(monkeypatch, receipt)
    monkeypatch.setattr(
        installer,
        "_require_canonical_preflight_cache_path",
        REAL_REQUIRE_CANONICAL_PREFLIGHT_CACHE_PATH,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_args, **_kwargs: calls.append("LOAD") or ({}, {}),
    )
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **_kwargs: calls.append("SECRET"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_PREFLIGHT_PATH_FORBIDDEN",
    ):
        installer.install(
            preflight_artifact=tmp_path / "production-preflight-v2.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
        )
    assert calls == []
    assert not receipt.exists()


@pytest.mark.parametrize(
    ("container_field", "field", "value"),
    (
        ("cache", "kind", "IDENTITY"),
        ("cache", "artifact_filename", "wrong.json"),
        ("attestation", "head_sha", "b" * 40),
        ("attestation", "run_id", "301"),
        ("attestation", "payload_sha256", "d" * 64),
        ("cache", "payload_base64", b64encode(b'{"tampered":true}\n').decode("ascii")),
    ),
)
def test_invalid_r3_cache_is_rejected_before_reservation_network_or_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    container_field: str,
    field: str,
    value: object,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    cache_path = tmp_path / "recovery-v2-predecessor-cache" / "production-preflight-v2.json"
    payload = b"{}\n"
    cache = _preflight_cache(payload)
    target = cache if container_field == "cache" else cache["attestation"]
    assert isinstance(target, dict)
    target[field] = value
    _write_preflight_cache(cache_path, cache)
    _prepare(monkeypatch, receipt)
    monkeypatch.setattr(installer, "_load_preflight_source", REAL_LOAD_PREFLIGHT_SOURCE)
    external_calls: list[str] = []
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **_kwargs: external_calls.append("SECRET"),
    )
    with pytest.raises(installer.BindingInstallerV2Error, match="PREFLIGHT_INVALID"):
        installer.install(
            preflight_artifact=cache_path,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
        )
    assert external_calls == []
    assert not receipt.exists()


def test_r3_final_controller_failure_is_rejected_before_r4_reservation_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    cache_path = tmp_path / "recovery-v2-predecessor-cache" / "production-preflight-v2.json"
    payload = b"{}\n"
    _write_preflight_cache(cache_path, _preflight_cache(payload))
    _prepare(monkeypatch, receipt)
    monkeypatch.setattr(installer, "_load_preflight_source", REAL_LOAD_PREFLIGHT_SOURCE)
    monkeypatch.setattr(
        installer,
        "validate_preflight_controller_handoff_v2",
        lambda **_kwargs: (_ for _ in ()).throw(
            installer.RecoveryV2ControllerError("synthetic failed R3 journal")
        ),
    )
    external_calls: list[str] = []
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **_kwargs: external_calls.append("SECRET"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="PREFLIGHT_CONTROLLER_INVALID",
    ):
        installer.install(
            preflight_artifact=cache_path,
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
        )
    assert external_calls == []
    assert not receipt.exists()


@pytest.mark.parametrize("missing", ("TOKEN", "GH_PIN"))
def test_r4_local_prerequisites_fail_before_reservation_or_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    _prepare(monkeypatch, receipt)
    external_calls: list[str] = []
    if missing == "TOKEN":
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setattr(
            installer,
            "_require_pinned_gh_cli",
            lambda: (_ for _ in ()).throw(
                installer.BindingInstallerV2Error("CHRONOS_BINDING_V2_GH_HASH_INVALID")
            ),
        )
    with pytest.raises(installer.BindingInstallerV2Error):
        installer.install(
            preflight_artifact=tmp_path / "preflight-cache.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
        )
    assert external_calls == []
    assert not receipt.exists()


@pytest.mark.parametrize(("ttl_seconds", "accepted"), ((439, False), (440, True)))
def test_full_effect_schedule_must_fit_preflight_ttl_before_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ttl_seconds: int,
    accepted: bool,
) -> None:
    receipt = tmp_path / "chronos-runtime-bindings-v2.json"
    _prepare(monkeypatch, receipt)
    effects: list[str] = []
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda *, name, **_kwargs: effects.append(name),
    )
    observed = datetime(2026, 8, 30, 13, tzinfo=UTC) - installer.timedelta(
        seconds=ttl_seconds
    )
    if not accepted:
        with pytest.raises(
            installer.BindingInstallerV2Error,
            match="CHRONOS_BINDING_V2_PREFLIGHT_EXPIRED",
        ):
            installer.install(
                preflight_artifact=tmp_path / "preflight.json",
                expected_main_sha=MAIN_SHA,
                expected_preflight_run_id="300",
                report_path=receipt,
                observed_at=observed,
            )
        assert effects == []
        assert not receipt.exists()
        return
    report = installer.install(
        preflight_artifact=tmp_path / "preflight.json",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        report_path=receipt,
        observed_at=observed,
    )
    assert effects == installer.BINDING_ORDER
    assert report["verdict"] == "FOUR_RUNTIME_BINDINGS_INSTALLED_V2"


def test_bindings_are_written_exactly_once_in_fixed_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    _prepare(monkeypatch, receipt)
    observed: list[str] = []
    hold_checks: list[int] = []
    concurrency_checks: list[int] = []
    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: observed.append(name))
    report = installer.install(
        preflight_artifact=tmp_path / "preflight.json",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        report_path=receipt,
        observed_at=OBSERVED_AT,
        hold_validator=lambda: hold_checks.append(len(observed)),
        concurrency_validator=lambda: concurrency_checks.append(len(observed)),
    )
    assert observed == installer.BINDING_ORDER
    assert report["secret_names_in_order"] == installer.BINDING_ORDER
    assert report["secret_writes_attempted"] == report["secret_writes_confirmed"] == 4
    assert report["secret_value_readbacks"] == report["automatic_retries"] == 0
    assert report["global_hold_full_validations"] == 2
    assert report["concurrent_run_inventory_validations"] == 4
    assert report["github_api_gets_upper_bound"] == 55
    assert report["github_api_gets_exact"] is False
    assert report["github_cli_version"] == "2.96.0"
    assert report["github_cli_sha256"] == installer._PINNED_GH_CLI_SHA256
    assert report["effect_admission_deadline_seconds"] == 480
    assert report["stage_outer_timeout_seconds"] == 600
    assert hold_checks == [0, 4]
    assert concurrency_checks == [0, 1, 2, 3]


def test_preflight_expiring_during_final_hold_refuses_success_after_four_puts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    current = [datetime(2026, 8, 30, 12, 0, tzinfo=UTC)]
    expiry = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    writes: list[str] = []
    holds: list[int] = []

    def full_hold() -> None:
        holds.append(len(writes))
        if len(holds) == 2:
            current[0] = expiry

    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda *, name, **_kwargs: writes.append(name),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_PREFLIGHT_EXPIRED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            clock=lambda: current[0],
            hold_validator=full_hold,
        )

    assert writes == installer.BINDING_ORDER
    assert holds == [0, 4]
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["secret_writes_attempted"] == 4
    assert failure["secret_writes_confirmed"] == 4
    assert "installed_at" not in failure


def test_exact_main_is_revalidated_after_full_hold_before_first_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    events: list[str] = []
    writes: list[str] = []

    def full_hold() -> None:
        events.append("FULL_HOLD")

    def main_drift(**_kwargs: object) -> str:
        events.append("EXACT_MAIN")
        raise installer.BindingInstallerV2Error("SYNTHETIC_MAIN_DRIFT")

    def guarded_secret_write(*, name: str, **_kwargs: object) -> None:
        installer.assert_current_main(repository=installer.EXPECTED_REPOSITORY, main_sha=MAIN_SHA)
        writes.append(name)

    monkeypatch.setattr(installer, "assert_current_main", main_drift)
    monkeypatch.setattr(installer, "_set_secret", guarded_secret_write)

    with pytest.raises(installer.BindingInstallerV2Error, match="SYNTHETIC_MAIN_DRIFT"):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            hold_validator=full_hold,
        )
    assert events == ["FULL_HOLD", "EXACT_MAIN"]
    assert writes == []


def test_ambiguous_secret_write_stops_without_retry_or_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    calls: list[str] = []

    def fail_third(*, name: str, **_kwargs: object) -> None:
        calls.append(name)
        if len(calls) == 3:
            raise installer.BindingInstallerV2Error("ambiguous")

    monkeypatch.setattr(installer, "_set_secret", fail_third)
    with pytest.raises(installer.BindingInstallerV2Error):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
        )
    assert calls == installer.BINDING_ORDER[:3]
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["verdict"] == "FAIL_AND_STOP"
    assert failure["secret_writes_attempted"] == 3
    assert failure["secret_writes_confirmed"] == 2
    assert failure["automatic_retries"] == 0


def test_preflight_expiration_during_inventory_stops_before_secret_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    calls: list[str] = []
    moments = iter(
        [
            datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
            datetime(2026, 8, 30, 12, 59, 59, tzinfo=UTC),
            datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        ]
    )
    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: calls.append(name))
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_PREFLIGHT_EXPIRED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            clock=lambda: next(moments),
        )
    assert calls == []
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["secret_writes_attempted"] == 0
    assert failure["secret_writes_confirmed"] == 0
    assert failure["automatic_retries"] == 0


def test_secret_write_rechecks_deadline_after_encryption_before_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic = [50.0]
    puts: list[str] = []
    monkeypatch.setattr(installer.time, "time", lambda: 50.0)
    monkeypatch.setattr(installer.time, "monotonic", lambda: monotonic[0])
    monkeypatch.setattr(
        installer,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: None,
    )

    def encrypt(**_kwargs: object) -> tuple[str, str]:
        monotonic[0] = 85.0
        return "encrypted", "kid_1"

    monkeypatch.setattr(
        installer,
        "_encrypt_secret_once",
        encrypt,
    )
    monkeypatch.setattr(
        installer,
        "_put_encrypted_secret_once",
        lambda **kwargs: puts.append(str(kwargs["name"])),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer._set_secret(
            name="CHRONOS_CONTROL_PLANE_GENERATION_NONCE",
            value="a" * 64,
            repository=installer.EXPECTED_REPOSITORY,
            environment=installer.EXPECTED_ENVIRONMENT,
            gh_cli_path=Path("synthetic-gh.exe"),
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            reservation_sha256="b" * 64,
            report_path=installer.CANONICAL_REPORT_PATH,
            external_deadline_epoch=100.0,
            external_deadline_monotonic=100.0,
        )
    assert puts == []


def test_install_reuses_r3_cached_attestation_without_new_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    _prepare(monkeypatch, receipt)
    payload = b"{}"
    cached_attestation = {"payload_sha256": hashlib.sha256(payload).hexdigest()}
    observed_handoffs: list[dict[str, object]] = []

    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_args, **_kwargs: (payload, cached_attestation),
    )
    monkeypatch.setattr(
        installer,
        "validate_preflight_controller_handoff_v2",
        lambda **kwargs: observed_handoffs.append(dict(kwargs)) or "d" * 64,
    )
    monkeypatch.setattr(installer, "_set_secret", lambda **_kwargs: None)
    report = installer.install(
        preflight_artifact=tmp_path / "preflight.json",
        expected_main_sha=MAIN_SHA,
        expected_preflight_run_id="300",
        report_path=receipt,
        observed_at=OBSERVED_AT,
        monotonic_clock=lambda: 0.0,
        wall_clock=lambda: 1_000.0,
    )
    assert observed_handoffs == [
        {"main_sha": MAIN_SHA, "run_id": "300", "attestation": cached_attestation}
    ]
    assert report["github_api_gets_upper_bound"] == 55


def test_outer_deadline_is_captured_before_safety_lock_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    _prepare(monkeypatch, receipt)
    clocks = {"monotonic": 0.0, "wall": 1_000.0}
    attestations: list[str] = []

    def safety_lock(_environment: object) -> None:
        clocks["monotonic"] = 600.0
        clocks["wall"] = 1_600.0

    monkeypatch.setattr(installer, "assert_production_safety_locks", safety_lock)
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_args, **_kwargs: attestations.append("reached") or ({}, {}),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            monotonic_clock=lambda: clocks["monotonic"],
            wall_clock=lambda: clocks["wall"],
        )
    assert attestations == []
    assert not receipt.exists()


def test_global_concurrency_is_revalidated_before_every_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    writes: list[str] = []
    checks = 0

    def hold_check() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise installer.BindingInstallerV2Error("concurrent production run")

    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: writes.append(name))
    with pytest.raises(installer.BindingInstallerV2Error, match="concurrent production run"):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            concurrency_validator=hold_check,
        )
    assert checks == 2
    assert writes == installer.BINDING_ORDER[:1]
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["secret_writes_attempted"] == 1
    assert failure["secret_writes_confirmed"] == 1


def test_effect_deadline_is_rechecked_after_concurrency_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    clocks = {"monotonic": 0.0, "wall": 1_000.0}
    writes: list[str] = []

    def inventory() -> None:
        clocks["monotonic"] = 480.0
        clocks["wall"] = 1_480.0

    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: writes.append(name))
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            concurrency_validator=inventory,
            monotonic_clock=lambda: clocks["monotonic"],
            wall_clock=lambda: clocks["wall"],
        )
    assert writes == []
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["secret_writes_attempted"] == 0
    assert failure["secret_writes_confirmed"] == 0


def test_effect_deadline_refuses_first_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    writes: list[str] = []
    clocks = {"monotonic": 0.0, "wall": 1_000.0}

    def inventory() -> None:
        clocks["monotonic"] = 144.0
        clocks["wall"] = 1_144.0

    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: writes.append(name))
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            concurrency_validator=inventory,
            monotonic_clock=lambda: clocks["monotonic"],
            wall_clock=lambda: clocks["wall"],
        )
    assert writes == []
    failure = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure["secret_writes_attempted"] == 0
    assert failure["secret_writes_confirmed"] == 0


def test_outer_stage_deadline_includes_local_preconditions_and_ref_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "failure.json"
    _prepare(monkeypatch, receipt)
    writes: list[str] = []
    clocks = {"monotonic": 0.0, "wall": 1_000.0}
    payload = b"{}"

    def delayed_local_load(*_args: object, **_kwargs: object) -> tuple[bytes, dict[str, object]]:
        clocks["monotonic"] = 196.0
        clocks["wall"] = 1_196.0
        return payload, {"payload_sha256": hashlib.sha256(payload).hexdigest()}

    monkeypatch.setattr(installer, "_load_preflight_source", delayed_local_load)
    monkeypatch.setattr(installer, "_set_secret", lambda *, name, **_k: writes.append(name))
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_STAGE_DEADLINE_EXHAUSTED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            monotonic_clock=lambda: clocks["monotonic"],
            wall_clock=lambda: clocks["wall"],
        )
    assert writes == []
    assert not receipt.exists()


def test_default_global_hold_uses_explicit_token_and_no_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    observed: dict[str, object] = {}

    def verify(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"verdict": "WORKFLOW_HOLD_ESTABLISHED"}

    monkeypatch.setattr(installer, "verify_hold", verify)
    installer._validate_global_hold(
        repository="dddur75/robin-stades-ng",
        main_sha=MAIN_SHA,
    )
    assert observed == {
        "required_successful_ci_sha": MAIN_SHA,
        "recovery_v2": True,
        "repository_override": "dddur75/robin-stades-ng",
        "token_override": "synthetic-token",
        "current_run_id": 0,
    }


def test_second_invocation_is_refused_before_preflight_load_or_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "_REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", receipt)
    monkeypatch.setattr(installer, "validate_data_torrent_recovery_v2_authority", lambda **_: None)
    receipt.write_text("consumed\n", encoding="utf-8")
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_a, **_k: pytest.fail("second invocation loaded preflight"),
    )
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **_k: pytest.fail("second invocation reached a secret write"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_INVOCATION_ALREADY_CONSUMED",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
        )


def test_invocation_is_reserved_before_first_external_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    _prepare(monkeypatch, receipt)

    def fail_hold() -> None:
        reserved = json.loads(receipt.read_text(encoding="utf-8"))
        assert reserved["verdict"] == "INVOCATION_RESERVED"
        raise installer.BindingInstallerV2Error("synthetic pre-write failure")

    with pytest.raises(installer.BindingInstallerV2Error, match="synthetic pre-write failure"):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
            observed_at=OBSERVED_AT,
            hold_validator=fail_hold,
        )


@pytest.mark.parametrize("run_id", ["0", "01", "9" * 19, "9" * 5000])
def test_unbounded_preflight_run_id_is_rejected_before_reservation_or_preflight_load(
    run_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", receipt)
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_args, **_kwargs: pytest.fail("preflight load reached"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_PREFLIGHT_RUN_MISMATCH",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id=run_id,
            report_path=receipt,
        )
    assert not receipt.exists()


def test_missing_safety_lock_refuses_before_preflight_load_or_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", receipt)
    monkeypatch.delenv("PRODUCTION_LOCKED")
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_a, **_k: pytest.fail("preflight load reached"),
    )
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("subprocess reached"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_SAFETY_LOCK_INVALID",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
        )
    assert not receipt.exists()


@pytest.mark.parametrize("nonce", [None, "", "ab" * 31, "G" * 64])
def test_generation_nonce_is_required_before_reservation_or_external_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    nonce: str | None,
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", receipt)
    if nonce is None:
        monkeypatch.delenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", raising=False)
    else:
        monkeypatch.setenv("CHRONOS_CONTROL_PLANE_GENERATION_NONCE", nonce)
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_a, **_k: pytest.fail("invalid nonce reached preflight load"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_GENERATION_NONCE_INVALID",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=receipt,
        )
    assert not receipt.exists()


def test_secret_put_cli_child_surface_is_removed() -> None:
    source = Path(installer.__file__).read_text(encoding="utf-8")
    assert "--bounded-secret-put-child" not in source


def test_alternate_report_path_is_refused_before_preflight_load_or_secret_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical.json"
    monkeypatch.setattr(installer, "CANONICAL_REPORT_PATH", canonical)
    monkeypatch.setattr(
        installer,
        "_load_preflight_source",
        lambda *_a, **_k: pytest.fail("alternate path loaded preflight"),
    )
    monkeypatch.setattr(
        installer,
        "_set_secret",
        lambda **_k: pytest.fail("alternate path reached a secret write"),
    )
    with pytest.raises(
        installer.BindingInstallerV2Error,
        match="CHRONOS_BINDING_V2_REPORT_PATH_FORBIDDEN",
    ):
        installer.install(
            preflight_artifact=tmp_path / "preflight.json",
            expected_main_sha=MAIN_SHA,
            expected_preflight_run_id="300",
            report_path=tmp_path / "alternate.json",
        )


def test_recovery_v2_hold_requires_every_v1_and_v2_production_workflow_disabled() -> None:
    workflows = [
        {"id": index, "path": path, "state": "disabled_manually"}
        for index, path in enumerate(sorted(hold.RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS), start=1)
    ]
    receipt = hold._recovery_v2_workflow_quarantine(workflows)
    assert [item["workflow_path"] for item in receipt] == sorted(
        hold.RECOVERY_V2_REQUIRED_DISABLED_WORKFLOWS
    )
    assert all(item["state"] == "disabled_manually" for item in receipt)

    workflows[0]["state"] = "active"
    with pytest.raises(ChronosProductionError, match="CHRONOS_RECOVERY_V2_WORKFLOW_NOT_QUIESCENT"):
        hold._recovery_v2_workflow_quarantine(workflows)


def test_concurrency_inventory_covers_every_nonterminal_actions_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def github_get(path: str, _token: str, **_kwargs: object) -> dict[str, object]:
        status = path.split("status=", 1)[1].split("&", 1)[0]
        observed.append(status)
        runs = [{"id": 99, "status": status}] if status == "waiting" else []
        return {"total_count": len(runs), "workflow_runs": runs}

    monkeypatch.setattr(hold, "_github_get", github_get)
    with pytest.raises(ChronosProductionError, match="CHRONOS_CONCURRENT_RUN_PRESENT"):
        hold.verify_no_concurrent_runs(
            repository="dddur75/robin-stades-ng",
            token="synthetic",
        )
    assert observed == ["requested", "waiting", "pending", "queued", "in_progress"]


def test_concurrency_inventory_rejects_requested_to_queued_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = "requested"
    calls = 0

    def github_get(path: str, _token: str, **_kwargs: object) -> dict[str, object]:
        nonlocal calls, state
        status = path.split("status=", 1)[1].split("&", 1)[0]
        runs = [{"id": 99, "status": state}] if status == state else []
        if calls == 0:
            state = "queued"
        calls += 1
        return {"total_count": len(runs), "workflow_runs": runs}

    monkeypatch.setattr(hold, "_github_get", github_get)
    with pytest.raises(
        ChronosProductionError,
        match="CHRONOS_GITHUB_RUNS_INVENTORY_INVALID",
    ):
        hold.verify_no_concurrent_runs(
            repository="dddur75/robin-stades-ng",
            token="synthetic",
        )
    assert calls == 4


@pytest.mark.parametrize(
    "runs",
    [
        [{"id": "99", "status": "queued"}],
        [{"id": True, "status": "queued"}],
        [{"id": 0, "status": "queued"}],
        [{"id": 99, "status": "waiting"}],
        [{"id": 99, "status": "queued"}, {"id": 99, "status": "queued"}],
    ],
)
def test_concurrency_inventory_rejects_malformed_or_duplicate_runs(
    monkeypatch: pytest.MonkeyPatch,
    runs: list[dict[str, object]],
) -> None:
    def github_get(path: str, _token: str, **_kwargs: object) -> dict[str, object]:
        status = path.split("status=", 1)[1].split("&", 1)[0]
        selected = runs if status == "queued" else []
        return {"total_count": len(selected), "workflow_runs": selected}

    monkeypatch.setattr(hold, "_github_get", github_get)
    with pytest.raises(ChronosProductionError, match="CHRONOS_GITHUB_RUNS_INVENTORY_INVALID"):
        hold.verify_no_concurrent_runs(
            repository="dddur75/robin-stades-ng",
            token="synthetic",
        )


def test_final_hold_requires_one_exact_postmerge_run() -> None:
    run = {
        "id": 456,
        "run_attempt": 1,
        "head_sha": MAIN_SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
    }
    hold._require_exact_recovery_v2_final_ci_inventory(
        [run],
        expected_ci_sha=MAIN_SHA,
        expected_run_id=456,
    )
    with pytest.raises(ChronosProductionError, match="CHRONOS_POST_MERGE_CI_INVALID"):
        hold._require_exact_recovery_v2_final_ci_inventory(
            [run, {**run, "id": 457}],
            expected_ci_sha=MAIN_SHA,
            expected_run_id=456,
        )


def test_full_hold_refuses_active_workflow_missing_from_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(hold, "ROOT", tmp_path)

    def github_get(path: str, _token: str, **_kwargs: object) -> dict[str, object]:
        if path.endswith("/actions/workflows?per_page=100"):
            return {
                "total_count": 1,
                "workflows": [
                    {
                        "id": 99,
                        "path": ".github/workflows/unknown-active.yml",
                        "state": "active",
                    }
                ],
            }
        if path.endswith("/actions/workflows/ci.yml"):
            return {
                "id": 1,
                "path": ".github/workflows/ci.yml",
                "state": "disabled_manually",
            }
        if path.endswith("/environments/chronos-control-plane-production"):
            return {
                "name": "chronos-control-plane-production",
                "can_admins_bypass": False,
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                },
            }
        if path.endswith("/deployment-branch-policies"):
            return {
                "total_count": 1,
                "branch_policies": [{"name": "main", "type": "branch"}],
            }
        if "/actions/runs?status=" in path:
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(path)

    monkeypatch.setattr(hold, "_github_get", github_get)
    with pytest.raises(ChronosProductionError, match="CHRONOS_UNAUTHORIZED_ACTIVE_WORKFLOW"):
        hold.verify_hold(
            repository_override="dddur75/robin-stades-ng",
            token_override="synthetic",
            current_run_id=0,
        )


class _GitHubResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> list[bytes]:
        return [
            self.body[offset : offset + chunk_size]
            for offset in range(0, len(self.body), chunk_size)
        ]

    def close(self) -> None:
        self.closed = True


class _GitHubSession:
    def __init__(self, response: _GitHubResponse) -> None:
        self.response = response
        self.trust_env = True
        self.closed = False
        self.request: dict[str, object] | None = None

    def get(self, url: str, **kwargs: object) -> _GitHubResponse:
        self.request = {"url": url, "trust_env": self.trust_env, **kwargs}
        return self.response

    def close(self) -> None:
        self.closed = True


def _install_github_session(
    monkeypatch: pytest.MonkeyPatch, response: _GitHubResponse
) -> _GitHubSession:
    session = _GitHubSession(response)
    monkeypatch.setattr(hold.requests, "Session", lambda: session)
    return session


def test_github_hold_transport_disables_proxy_redirects_and_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _GitHubResponse(b'{"ok":true}')
    session = _install_github_session(monkeypatch, response)
    assert hold._github_get_direct("/repos/owner/repo", "secret") == {"ok": True}
    assert session.request is not None
    assert session.request["trust_env"] is False
    assert session.request["allow_redirects"] is False
    assert session.request["stream"] is True
    assert response.closed is session.closed is True


def test_github_hold_transport_refuses_redirect_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _GitHubResponse(b"", status_code=302, headers={"Location": "https://evil.test"})
    session = _install_github_session(monkeypatch, response)
    with pytest.raises(ChronosProductionError, match="CHRONOS_GITHUB_HOLD_API_REDIRECT_REFUSED"):
        hold._github_get_direct("/repos/owner/repo", "secret")
    assert response.closed is session.closed is True


def test_github_hold_transport_refuses_oversized_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _GitHubResponse(b"x" * (hold._MAX_GITHUB_BODY_BYTES + 1))
    session = _install_github_session(monkeypatch, response)
    with pytest.raises(ChronosProductionError, match="CHRONOS_GITHUB_HOLD_API_RESPONSE_TOO_LARGE"):
        hold._github_get_direct("/repos/owner/repo", "secret")
    assert response.closed is session.closed is True


def test_github_hold_transport_refuses_duplicate_json_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _GitHubResponse(b'{"ok":true,"ok":false}')
    session = _install_github_session(monkeypatch, response)
    with pytest.raises(ChronosProductionError, match="CHRONOS_GITHUB_HOLD_API_INVALID"):
        hold._github_get_direct("/repos/owner/repo", "secret")
    assert response.closed is session.closed is True


def test_github_hold_parent_bounds_whole_get_and_passes_token_only_on_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Completed:
        stdout = b'{"ok":true}'

    def run(argv: list[str], **kwargs: object) -> Completed:
        observed["argv"] = argv
        observed.update(kwargs)
        return Completed()

    monkeypatch.setattr(hold.subprocess, "run", run)
    assert hold._github_get("/repos/owner/repo", "secret-token") == {"ok": True}
    assert "secret-token" not in " ".join(observed["argv"])  # type: ignore[arg-type]
    assert observed["input"] == b"secret-token"
    assert observed["timeout"] == hold.GITHUB_GET_TOTAL_TIMEOUT_SECONDS


def test_github_hold_parent_turns_total_timeout_into_fail_closed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise hold.subprocess.TimeoutExpired(cmd="bounded", timeout=6)

    monkeypatch.setattr(hold.subprocess, "run", timeout)
    with pytest.raises(ChronosProductionError, match="CHRONOS_GITHUB_HOLD_API_UNAVAILABLE"):
        hold._github_get("/repos/owner/repo", "secret-token")
