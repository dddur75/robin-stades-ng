from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.seal_chronos_identity_go_v2 as seal
from robin.chronos_production import (
    PRODUCTION_SAFETY_LOCKS,
    ChronosProductionError,
    validate_identity_seal_v2,
)
from robin.prospective_observatory.chronos_control_plane import (
    ConditionalPutOutcome,
    ConditionalPutResult,
    ObservedObject,
)
from scripts.chronos_live_path_artifact_guard_v2 import load_guarded_seal

MAIN_SHA = "a" * 40
IDENTITY_RUN_ID = "123"


@pytest.fixture(autouse=True)
def _exact_safety_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PRODUCTION_SAFETY_LOCKS.items():
        monkeypatch.setenv(name, value)


class _Store:
    def __init__(
        self,
        *,
        outcome: ConditionalPutOutcome = ConditionalPutOutcome.CREATED,
        mismatch: bool = False,
        put_error: Exception | None = None,
    ) -> None:
        self.outcome = outcome
        self.mismatch = mismatch
        self.put_error = put_error
        self.put_calls = 0
        self.get_calls = 0
        self.payload = b""
        self.metadata: dict[str, str] = {}

    def put_if_absent(
        self,
        _key: str,
        data: bytes,
        *,
        metadata: dict[str, str],
        on_dispatch: Any,
    ) -> ConditionalPutResult:
        on_dispatch()
        self.put_calls += 1
        self.payload = data
        self.metadata = metadata
        if self.put_error is not None:
            raise self.put_error
        return ConditionalPutResult(
            outcome=self.outcome,
            transport_attempts=1,
            automatic_retry_possible=False,
        )

    def get_object(self, _key: str) -> ObservedObject:
        self.get_calls += 1
        return ObservedObject(
            data=(self.payload + b"drift" if self.mismatch else self.payload),
            metadata=self.metadata,
        )


def _prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, bytes]:
    payload = b'{"schema_version":"neon-branch-identity-go-v2"}\n'
    payload_sha = hashlib.sha256(payload).hexdigest()
    identity_path = tmp_path / "identity.json"
    identity_path.write_bytes(payload)
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text(
        json.dumps(
            {
                "schema_version": "github-artifact-attestation-v2",
                "repository": "dddur75/robin-stades-ng",
                "workflow_path": (".github/workflows/chronos-neon-branch-identity-v2.yml"),
                "run_id": IDENTITY_RUN_ID,
                "run_attempt": "1",
                "head_sha": MAIN_SHA,
                "artifact_id": 456,
                "artifact_name": f"neon-branch-identity-go-v2-{IDENTITY_RUN_ID}",
                "payload_sha256": payload_sha,
                "archive_sha256": "b" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for name, value in {
        "GITHUB_REPOSITORY": "dddur75/robin-stades-ng",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": MAIN_SHA,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "789",
        "R2_ACCOUNT_ID": "account-synthetic",
        "R2_BUCKET_NAME": "bucket-synthetic",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(seal, "validate_data_torrent_recovery_v2_authority", lambda **_: None)
    monkeypatch.setattr(seal.readonly, "_github_actions_state", lambda *_a, **_k: (0, 0, 1))
    monkeypatch.setattr(
        seal.readonly,
        "_github_authority_window_dispatch_count",
        lambda *_a, **_k: 1,
    )
    monkeypatch.setattr(
        seal,
        "validate_neon_branch_identity_go_v2",
        lambda _value, *, main_sha: {"source": {"main_sha": main_sha, "run_id": IDENTITY_RUN_ID}},
    )
    return identity_path, attestation_path, payload


def test_seal_puts_then_gets_exact_bytes_metadata_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, payload = _prepare(tmp_path, monkeypatch)
    store = _Store()
    effects = seal.SealEffectsV2()
    report = seal.seal_identity_go(
        identity_path,
        attestation_path,
        expected_main_sha=MAIN_SHA,
        identity_run_id=IDENTITY_RUN_ID,
        store=store,  # type: ignore[arg-type]
        effects=effects,
    )
    assert report["schema_version"] == "durable-identity-seal-v2"
    assert report["verdict"] == "DURABLE_IDENTITY_SEAL_V2"
    assert report["identity_go"]["payload_sha256"] == hashlib.sha256(payload).hexdigest()  # type: ignore[index]
    assert report["effects"] == {
        "r2_puts": 1,
        "r2_gets": 1,
        "r2_objects_created": 1,
        "r2_lists": 0,
        "r2_deletes": 0,
        "r2_overwrites": 0,
        "automatic_retries": 0,
        "neon_gets": 0,
        "neon_mutations": 0,
        "postgresql_connections": 0,
        "sql_statements": 0,
        "provider_calls": 0,
        "purchases": 0,
        "sensitive_values_exposed": 0,
    }
    assert effects.r2_puts == store.put_calls == 1
    assert effects.r2_gets == store.get_calls == 1
    assert (
        validate_identity_seal_v2(
            report,
            main_sha=MAIN_SHA,
            expected_identity_run_id=IDENTITY_RUN_ID,
        )
        == report
    )


def test_seal_rechecks_exact_main_after_dispatch_window_before_r2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    store = _Store()
    events: list[str] = []

    def dispatch_window(*_args: object, **_kwargs: object) -> int:
        events.append("DISPATCH_WINDOW")
        return 1

    def terminal_main(*_args: object, **_kwargs: object) -> tuple[int, int, int]:
        events.append("EXACT_MAIN")
        raise seal.IdentitySealError("SYNTHETIC_MAIN_DRIFT")

    monkeypatch.setattr(seal.readonly, "_github_authority_window_dispatch_count", dispatch_window)
    monkeypatch.setattr(seal.readonly, "_github_actions_state", terminal_main)

    with pytest.raises(seal.IdentitySealError, match="SYNTHETIC_MAIN_DRIFT"):
        seal.seal_identity_go(
            identity_path,
            attestation_path,
            expected_main_sha=MAIN_SHA,
            identity_run_id=IDENTITY_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )
    assert events == ["DISPATCH_WINDOW", "EXACT_MAIN"]
    assert store.put_calls == store.get_calls == 0


@pytest.mark.parametrize(
    ("store", "match", "expected_gets"),
    [
        (_Store(outcome=ConditionalPutOutcome.PRECONDITION_FAILED), "PUT_NOT_CREATED", 0),
        (_Store(outcome=ConditionalPutOutcome.AMBIGUOUS), "PUT_AMBIGUOUS", 0),
        (_Store(mismatch=True), "READBACK_MISMATCH", 1),
        (_Store(put_error=RuntimeError("ambiguous")), "PUT_AMBIGUOUS", 0),
    ],
)
def test_seal_fails_closed_without_retry_or_hidden_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store: _Store,
    match: str,
    expected_gets: int,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    effects = seal.SealEffectsV2()
    with pytest.raises(seal.IdentitySealError, match=match):
        seal.seal_identity_go(
            identity_path,
            attestation_path,
            expected_main_sha=MAIN_SHA,
            identity_run_id=IDENTITY_RUN_ID,
            store=store,  # type: ignore[arg-type]
            effects=effects,
        )
    assert effects.r2_puts == store.put_calls == 1
    assert effects.r2_gets == store.get_calls == expected_gets
    if store.outcome is ConditionalPutOutcome.AMBIGUOUS or store.put_error is not None:
        assert effects.r2_objects_created == 1
        assert effects.r2_objects_created_exact is False


def test_v1_or_no_go_is_rejected_before_r2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        seal,
        "validate_neon_branch_identity_go_v2",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("v1 rejected")),
    )
    store = _Store()
    with pytest.raises(seal.IdentitySealError, match="IDENTITY_REPORT_INVALID"):
        seal.seal_identity_go(
            identity_path,
            attestation_path,
            expected_main_sha=MAIN_SHA,
            identity_run_id=IDENTITY_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )
    assert store.put_calls == store.get_calls == 0


def test_seal_rejects_missing_safety_lock_before_r2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    monkeypatch.delenv("PRODUCTION_LOCKED")
    store = _Store()
    with pytest.raises(seal.IdentitySealError, match="SAFETY_OR_AUTHORITY_INACTIVE"):
        seal.seal_identity_go(
            identity_path,
            attestation_path,
            expected_main_sha=MAIN_SHA,
            identity_run_id=IDENTITY_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )
    assert store.put_calls == store.get_calls == 0


def test_cross_run_identity_is_rejected_before_r2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(
        seal,
        "validate_neon_branch_identity_go_v2",
        lambda _value, *, main_sha: {"source": {"main_sha": main_sha, "run_id": "999"}},
    )
    store = _Store()
    with pytest.raises(seal.IdentitySealError, match="IDENTITY_REPORT_RUN_MISMATCH"):
        seal.seal_identity_go(
            identity_path,
            attestation_path,
            expected_main_sha=MAIN_SHA,
            identity_run_id=IDENTITY_RUN_ID,
            store=store,  # type: ignore[arg-type]
        )
    assert store.put_calls == store.get_calls == 0


def test_seal_guard_rejects_v1_and_counter_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_path, attestation_path, _ = _prepare(tmp_path, monkeypatch)
    report = seal.seal_identity_go(
        identity_path,
        attestation_path,
        expected_main_sha=MAIN_SHA,
        identity_run_id=IDENTITY_RUN_ID,
        store=_Store(),  # type: ignore[arg-type]
    )
    report["schema_version"] = "chronos-controlled-go-durable-seal-v1"
    with pytest.raises(ChronosProductionError, match="IDENTITY_SEAL_V2_INVALID"):
        validate_identity_seal_v2(
            report,
            main_sha=MAIN_SHA,
            expected_identity_run_id=IDENTITY_RUN_ID,
        )


@pytest.mark.parametrize("return_code", (seal.SUPERVISOR_TIMEOUT_EXIT, -15, 0))
def test_seal_supervisor_preserves_conservative_fallback_on_timeout_signal_or_invalid_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    return_code: int,
) -> None:
    def child(command: tuple[str, ...], **_kwargs: object) -> int:
        if return_code != seal.SUPERVISOR_TIMEOUT_EXIT:
            Path(command[-1]).write_bytes(b'{"truncated":')
        return return_code

    monkeypatch.setattr(seal, "run_child_once", child)
    report_path = tmp_path / "durable-identity-seal-v2.json"
    observed = seal._supervise(
        identity_report=tmp_path / "identity.json",
        attestation=tmp_path / "attestation.json",
        expected_main_sha=MAIN_SHA,
        identity_run_id=IDENTITY_RUN_ID,
        report=report_path,
    )
    assert observed == (
        seal.SUPERVISOR_EXPORT_EXIT if return_code == 0 else return_code
    )
    report = load_guarded_seal(
        report_path,
        expected_main_sha=MAIN_SHA,
        expected_identity_run_id=IDENTITY_RUN_ID,
    )
    assert report["failure_class"] == "TRANSPORT_AMBIGUOUS"
    assert report["effect_counter_certainty"] == "UNKNOWN_OR_UPPER_BOUND"
    assert report["effects"] == {
        "r2_puts": 1,
        "r2_gets": 1,
        "r2_objects_created": 1,
        "r2_objects_created_exact": False,
        "automatic_retries": 0,
    }
