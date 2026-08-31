from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

import scripts.validate_data_torrent_recovery_v2_dispatch_envelope as envelope
from robin.data_torrent.runtime import FINAL_ARTIFACT_NAMES

ROOT = Path(__file__).resolve().parents[2]
MAIN_SHA = "a" * 40
NOW = datetime(2026, 8, 31, 4, 30, tzinfo=UTC)
DEADLINE = int((NOW + timedelta(minutes=10)).timestamp())
WORKFLOWS = (
    ROOT / ".github/workflows/chronos-neon-branch-identity-v2.yml",
    ROOT / ".github/workflows/chronos-identity-seal-v2.yml",
    ROOT / ".github/workflows/chronos-production-bootstrap-v4.yml",
    ROOT / ".github/workflows/data-torrent-live-v2.yml",
)


def _environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", MAIN_SHA)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(envelope.time, "time", lambda: NOW.timestamp())


def test_dispatch_envelope_accepts_only_the_controller_bound_absolute_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _environment(monkeypatch)
    calls: list[tuple[str, datetime, Path]] = []

    def authority(*, scale_stage: str, now: datetime, repository_root: Path) -> datetime:
        calls.append((scale_stage, now, repository_root))
        return NOW + timedelta(minutes=20)

    monkeypatch.setattr(envelope, "validate_data_torrent_recovery_v2_authority", authority)
    assert envelope.validate_dispatch_envelope(
        scale_stage="E4",
        expected_main_sha=MAIN_SHA,
        effect_deadline_epoch=str(DEADLINE),
        dispatch_nonce="b" * 64,
        now=NOW,
        repository_root=tmp_path,
    ) == datetime.fromtimestamp(DEADLINE, tz=UTC)
    assert calls == [("E4", NOW, tmp_path)]


@pytest.mark.parametrize(
    ("stage", "maximum_seconds"),
    (("E2", 600), ("E3A", 900), ("E3B", 900), ("E4", 1_200)),
)
def test_dispatch_envelope_enforces_each_stage_exact_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    maximum_seconds: int,
) -> None:
    _environment(monkeypatch)
    monkeypatch.setattr(
        envelope,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: NOW + timedelta(hours=1),
    )
    exact_deadline = int((NOW + timedelta(seconds=maximum_seconds)).timestamp())
    assert envelope.validate_dispatch_envelope(
        scale_stage=stage,
        expected_main_sha=MAIN_SHA,
        effect_deadline_epoch=str(exact_deadline),
        dispatch_nonce="b" * 64,
        now=NOW,
        repository_root=tmp_path,
    ) == datetime.fromtimestamp(exact_deadline, tz=UTC)

    with pytest.raises(envelope.RecoveryV2DispatchEnvelopeError, match="DEADLINE_INVALID"):
        envelope.validate_dispatch_envelope(
            scale_stage=stage,
            expected_main_sha=MAIN_SHA,
            effect_deadline_epoch=str(exact_deadline + 1),
            dispatch_nonce="b" * 64,
            now=NOW,
            repository_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("deadline", "nonce", "sha", "match"),
    (
        (int(NOW.timestamp()), "b" * 64, MAIN_SHA, "DEADLINE_INVALID"),
        (int((NOW + timedelta(seconds=1_201)).timestamp()), "b" * 64, MAIN_SHA, "DEADLINE_INVALID"),
        (DEADLINE, "not-a-nonce", MAIN_SHA, "ENVELOPE_INVALID"),
        (DEADLINE, "b" * 64, "c" * 40, "ENVELOPE_INVALID"),
    ),
)
def test_dispatch_envelope_rejects_stale_or_malformed_inputs_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deadline: int,
    nonce: str,
    sha: str,
    match: str,
) -> None:
    _environment(monkeypatch)
    monkeypatch.setattr(
        envelope,
        "validate_data_torrent_recovery_v2_authority",
        lambda **_kwargs: NOW + timedelta(minutes=20),
    )
    with pytest.raises(envelope.RecoveryV2DispatchEnvelopeError, match=match):
        envelope.validate_dispatch_envelope(
            scale_stage="E4",
            expected_main_sha=sha,
            effect_deadline_epoch=str(deadline),
            dispatch_nonce=nonce,
            now=NOW,
            repository_root=tmp_path,
        )


def test_workflows_declare_and_reuse_the_same_absolute_dispatch_envelope() -> None:
    for path in WORKFLOWS:
        source = path.read_text(encoding="utf-8")
        document = yaml.safe_load(source)
        trigger = document.get("on", document.get(True))
        inputs = trigger["workflow_dispatch"]["inputs"]
        for name in (
            "recovery_v2_effect_deadline_epoch",
            "recovery_v2_dispatch_nonce",
        ):
            assert inputs[name]["required"] is True
        assert "date +%s" not in source
        assert "validate_data_torrent_recovery_v2_dispatch_envelope.py" in source
        assert "${{ inputs.recovery_v2_effect_deadline_epoch }}" in source
        assert "${{ inputs.recovery_v2_dispatch_nonce }}" in source


def test_live_upload_is_an_explicit_regular_file_closure_without_globs() -> None:
    path = ROOT / ".github/workflows/data-torrent-live-v2.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = document["jobs"]["torrent"]["steps"]
    guard = next(
        step for step in steps if step.get("name") == "Require exactly the nineteen terminal artifacts"
    )
    source = guard["run"]
    for required in (
        "entries = list(root.iterdir())",
        "item.lstat()",
        "stat.S_ISREG",
        "not item.is_symlink()",
        "st_file_attributes",
    ):
        assert required in source
    upload = next(step for step in steps if "actions/upload-artifact@" in step.get("uses", ""))
    uploaded = set(upload["with"]["path"].splitlines())
    assert uploaded == {f".torrent/artifacts/{name}" for name in FINAL_ARTIFACT_NAMES}
    assert not any("*" in item for item in uploaded)
