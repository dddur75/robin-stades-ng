from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import robin.chronos_production as production
import robin.recovery_v2_filesystem as filesystem
import scripts.dispatch_data_torrent_recovery_v2_stage as controller
import scripts.install_chronos_runtime_bindings_v2 as bindings
import scripts.materialize_data_torrent_recovery_v2_delivery_evidence as delivery
import scripts.materialize_data_torrent_recovery_v2_terminal_evidence as terminal
import scripts.recovery_v2_supervision as supervision


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8").strip()


def _repository(root: Path) -> str:
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "recovery-v2@example.invalid")
    _git(root, "config", "user.name", "Recovery V2 Test")
    (root / "tracked.txt").write_bytes(b"clean\n")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "synthetic base")
    return _git(root, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("claim", "pr_b_number", "expected"),
    (
        (delivery._POST_202_B101_CORRECTION_RELEASE_CLAIM, None, True),
        (delivery._PR_B_RELEASE_CLAIM, 81, True),
        (delivery._EXACT_HEAD_CORRECTION_RELEASE_CLAIM, None, False),
        (delivery._POST_202_B101_CORRECTION_RELEASE_CLAIM, 81, False),
        (delivery._EXACT_HEAD_CORRECTION_RELEASE_CLAIM, 81, False),
        (delivery._PR_B_RELEASE_CLAIM, None, False),
        (
            "GOV.DATA_TORRENT_RECOVERY.V2.E1.IMPLEMENTATION."
            "PRECOMMIT_STATIC_RUNTIME_CORRECTION.RELEASE.001",
            None,
            False,
        ),
        (production._RECOVERY_V2_EXACT_HEAD_CI_FAILURE_CLAIM, None, False),
        ("GOV.DATA_TORRENT_RECOVERY.V2.UNKNOWN", None, False),
    ),
)
def test_delivery_release_claim_matches_exact_engineering_chain(
    claim: str,
    pr_b_number: int | None,
    expected: bool,
) -> None:
    assert (
        delivery._release_claim_matches_engineering_chain(
            claim,
            pr_b_number=pr_b_number,
        )
        is expected
    )


def test_posix_atomic_publish_uses_an_explicit_fail_closed_metadata_guard() -> None:
    source = inspect.getsource(filesystem.publish_exclusive_bytes)
    guard_source = inspect.getsource(filesystem._require_rollback_metadata)
    assert "assert metadata is not None" not in source
    assert "metadata = _require_rollback_metadata(metadata)" in source
    assert "if metadata is None:" in guard_source

    tree = ast.parse(textwrap.dedent(source))
    rollback_handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and any(
            isinstance(child, ast.Constant)
            and child.value == "RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED"
            for child in ast.walk(node)
        )
    ]
    assert len(rollback_handlers) == 1
    first_statement = rollback_handlers[0].body[0]
    assert isinstance(first_statement, ast.Assign)
    assert [target.id for target in first_statement.targets if isinstance(target, ast.Name)] == [
        "metadata"
    ]
    assert isinstance(first_statement.value, ast.Call)
    assert isinstance(first_statement.value.func, ast.Name)
    assert first_statement.value.func.id == "_require_rollback_metadata"
    guarded_unlinks = [
        node
        for node in ast.walk(rollback_handlers[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_posix_unlink_if_identity"
        and any(
            keyword.arg == "expected"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "metadata"
            for keyword in node.keywords
        )
    ]
    assert len(guarded_unlinks) == 2

    root = Path(__file__).resolve().parents[2]
    optimized = subprocess.run(
        (
            sys.executable,
            "-O",
            "-c",
            (
                "from robin.recovery_v2_filesystem import "
                "RecoveryV2FilesystemError, _require_rollback_metadata; "
                "\ntry: _require_rollback_metadata(None)"
                "\nexcept RecoveryV2FilesystemError as exc: print(str(exc))"
                "\nelse: raise SystemExit(9)"
            ),
        ),
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert optimized.returncode == 0, optimized.stderr
    assert optimized.stdout.strip() == "RECOVERY_V2_FILESYSTEM_ROLLBACK_FAILED"


@pytest.mark.parametrize("index_flag", ("--assume-unchanged", "--skip-worktree"))
@pytest.mark.parametrize("module", (terminal, delivery))
def test_materializers_reject_hidden_git_index_flags(
    tmp_path: Path,
    index_flag: str,
    module: ModuleType,
) -> None:
    root = tmp_path / "repository"
    _repository(root)
    _git(root, "update-index", index_flag, "tracked.txt")
    (root / "tracked.txt").write_bytes(b"hidden mutation\n")

    with pytest.raises(RuntimeError, match="WORKTREE|TRACKED_WORKTREE"):
        module._assert_index_flags_clear(root=root)


def test_terminal_snapshot_rejects_source_drift_and_never_binds_stale_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    main_sha = _repository(root)
    release = root / ".torrent" / "release"
    release.mkdir(parents=True)
    source = release / "source.json"
    initial = b'{"value":1}\n'
    source.write_bytes(initial)
    source.write_bytes(b'{"value":2}\n')

    with pytest.raises(terminal.TerminalEvidenceV2Error, match="SOURCE_DRIFT"):
        terminal._snapshot_worktree(
            root=root,
            main_sha=main_sha,
            expected_sources={source: "reports/evidence/source.json"},
            expected_source_payloads={source: initial},
        )


@pytest.mark.parametrize(
    ("module", "error_type"),
    (
        (terminal, terminal.TerminalEvidenceV2Error),
        (delivery, delivery.DeliveryEvidenceV2Error),
    ),
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX dirfd ancestry regression")
def test_materializer_exclusive_write_rejects_parent_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    error_type: type[Exception],
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    parent = root / "release"
    parent.mkdir()
    moved = root / "release-original"
    original_link = production.os.link
    exchanged = False

    def exchange(source: str, destination: str, **kwargs: Any) -> None:
        nonlocal exchanged
        if not exchanged:
            exchanged = True
            parent.rename(moved)
            parent.mkdir()
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(production.os, "link", exchange)
    with pytest.raises(error_type):
        module._write_exclusive(parent / "receipt.json", b'{"ok":true}\n', root=root)
    assert exchanged is True
    assert not (parent / "receipt.json").exists()
    assert not (moved / "receipt.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle ancestry regression")
@pytest.mark.parametrize(
    ("module", "error_type"),
    (
        (terminal, terminal.TerminalEvidenceV2Error),
        (delivery, delivery.DeliveryEvidenceV2Error),
    ),
)
def test_windows_materializer_handle_refuses_parent_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    error_type: type[Exception],
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    parent = root / "release"
    parent.mkdir()
    moved = root / "release-original"
    attempts = 0

    def attempt_exchange(capability_path: Path) -> None:
        nonlocal attempts
        if capability_path != parent:
            return
        attempts += 1
        with pytest.raises(OSError):
            parent.rename(moved)

    monkeypatch.setattr(filesystem, "_after_parent_capability_acquired", attempt_exchange)
    try:
        module._write_exclusive(parent / "receipt.json", b'{"ok":true}\n', root=root)
    except error_type as exc:  # pragma: no cover - the native success path is required
        pytest.fail(f"anchored Windows publication unexpectedly failed: {exc}")
    assert attempts == 1
    assert (parent / "receipt.json").read_bytes() == b'{"ok":true}\n'
    assert not moved.exists()


def test_atomic_capability_reads_exact_published_and_replaced_bytes(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    target = root / "nested" / "receipt.json"
    filesystem.publish_exclusive_bytes(target, b"before\n", repository_root=root)
    assert (
        filesystem.read_bytes(target, repository_root=root, maximum_bytes=64)
        == b"before\n"
    )

    filesystem.replace_bytes(target, b"after\n", repository_root=root)

    assert filesystem.read_bytes(target, repository_root=root, maximum_bytes=64) == b"after\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows native rename seam")
def test_windows_native_rename_failure_preserves_previous_complete_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    target = root / "receipt.json"
    filesystem.publish_exclusive_bytes(target, b"before\n", repository_root=root)

    def fail_rename(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic NtSetInformationFile failure")

    monkeypatch.setattr(filesystem, "_windows_rename_handle", fail_rename)
    with pytest.raises(OSError, match="NtSetInformationFile"):
        filesystem.replace_bytes(target, b"after\n", repository_root=root)

    assert filesystem.read_bytes(target, repository_root=root, maximum_bytes=64) == b"before\n"


def test_controller_replace_failure_preserves_previous_complete_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    receipt = release / "controller.json"
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)
    controller._write_receipt(receipt, {"state": "before"}, exclusive=True)

    def fail_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic replace interruption")

    monkeypatch.setattr(controller, "_recovery_v2_replace_bytes", fail_replace)
    with pytest.raises(controller.RecoveryV2ControllerError, match="RECEIPT_INVALID"):
        controller._write_receipt(receipt, {"state": "after"})

    assert json.loads(receipt.read_bytes()) == {"state": "before"}


def test_controller_exclusive_publish_failure_never_exposes_partial_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    receipt = release / "controller.json"
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)

    def fail_link(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic publication interruption")

    monkeypatch.setattr(controller, "_recovery_v2_publish_exclusive_bytes", fail_link)
    with pytest.raises(controller.RecoveryV2ControllerError, match="RECEIPT_INVALID"):
        controller._write_receipt(receipt, {"state": "complete"}, exclusive=True)
    assert not receipt.exists()


def test_controller_exclusive_race_preserves_complete_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    receipt = release / "controller.json"
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)

    def race_winner(path: Path, *_args: Any, **_kwargs: Any) -> None:
        path.write_bytes(b'{"state":"winner"}\n')
        raise FileExistsError("synthetic exclusive race")

    monkeypatch.setattr(controller, "_recovery_v2_publish_exclusive_bytes", race_winner)
    with pytest.raises(
        controller.RecoveryV2ControllerError,
        match="INVOCATION_ALREADY_CONSUMED",
    ):
        controller._write_receipt(receipt, {"state": "loser"}, exclusive=True)
    assert json.loads(receipt.read_bytes()) == {"state": "winner"}


def test_windows_atomic_flush_failure_preserves_previous_complete_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    receipt = release / "controller.json"
    monkeypatch.setattr(controller, "_REPOSITORY_ROOT", tmp_path)
    controller._write_receipt(receipt, {"state": "before"}, exclusive=True)

    if os.name != "nt":
        pytest.skip("Windows FlushFileBuffers seam")

    def fail_flush(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(filesystem, "_FLUSH_FILE_BUFFERS", fail_flush)
    with pytest.raises(controller.RecoveryV2ControllerError, match="RECEIPT_INVALID"):
        controller._write_receipt(receipt, {"state": "after"})
    assert json.loads(receipt.read_bytes()) == {"state": "before"}


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace flush seam")
def test_windows_postrename_parent_flush_failure_rolls_back_exclusive_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    target = root / "receipt.json"
    original_flush = filesystem._windows_flush_handle
    calls = 0

    def fail_parent_flush(handle: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic post-rename parent flush failure")
        original_flush(handle)

    monkeypatch.setattr(filesystem, "_windows_flush_handle", fail_parent_flush)
    with pytest.raises(OSError):
        filesystem.publish_exclusive_bytes(target, b"complete\n", repository_root=root)

    assert calls >= 2
    assert not target.exists()
    assert not (root / ".receipt.json.recovery-v2-create").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace flush seam")
def test_windows_postrename_parent_flush_failure_restores_previous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    target = root / "receipt.json"
    filesystem.publish_exclusive_bytes(target, b"before\n", repository_root=root)
    original_flush = filesystem._windows_flush_handle
    calls = 0

    def fail_parent_flush(handle: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic post-rename parent flush failure")
        original_flush(handle)

    monkeypatch.setattr(filesystem, "_windows_flush_handle", fail_parent_flush)
    with pytest.raises(OSError):
        filesystem.replace_bytes(target, b"after\n", repository_root=root)

    assert calls >= 2
    assert filesystem.read_bytes(target, repository_root=root, maximum_bytes=64) == b"before\n"
    assert not (root / ".receipt.json.recovery-v2-update").exists()


def test_directory_publication_is_atomic_and_never_replaces_a_race_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    source = root / "candidate" / "artifacts"
    source.mkdir(parents=True)
    (source / "proof.json").write_bytes(b'{"candidate":true}\n')
    destination = root / "published"

    if os.name == "nt":
        original_rename = filesystem._windows_rename_handle
        raced = False

        def race(*args: Any, **kwargs: Any) -> None:
            nonlocal raced
            if kwargs.get("destination_name") == destination.name and not raced:
                raced = True
                destination.mkdir()
                (destination / "winner.json").write_bytes(b'{"winner":true}\n')
            original_rename(*args, **kwargs)

        monkeypatch.setattr(filesystem, "_windows_rename_handle", race)
    else:
        original_rename = filesystem._posix_rename_noreplace
        raced = False

        def race(*args: Any, **kwargs: Any) -> None:
            nonlocal raced
            if kwargs.get("destination_name") == destination.name and not raced:
                raced = True
                destination.mkdir()
                (destination / "winner.json").write_bytes(b'{"winner":true}\n')
            original_rename(*args, **kwargs)

        monkeypatch.setattr(filesystem, "_posix_rename_noreplace", race)

    with pytest.raises(FileExistsError):
        filesystem.publish_directory_noreplace(
            source,
            destination,
            repository_root=root,
        )

    assert raced is True
    assert (destination / "winner.json").read_bytes() == b'{"winner":true}\n'
    assert (source / "proof.json").read_bytes() == b'{"candidate":true}\n'


def test_directory_publication_moves_only_a_complete_flat_directory(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    source = root / "candidate" / "artifacts"
    source.mkdir(parents=True)
    (source / "one.json").write_bytes(b"one\n")
    (source / "two.json").write_bytes(b"two\n")
    destination = root / "published"

    filesystem.publish_directory_noreplace(
        source,
        destination,
        repository_root=root,
    )

    assert not source.exists()
    assert sorted(path.name for path in destination.iterdir()) == ["one.json", "two.json"]
    assert (destination / "one.json").read_bytes() == b"one\n"
    assert (destination / "two.json").read_bytes() == b"two\n"


def test_directory_publication_rejects_expected_hash_drift_without_destination(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    source = root / "candidate" / "artifacts"
    source.mkdir(parents=True)
    payload = b'{"candidate":true}\n'
    (source / "proof.json").write_bytes(payload)
    destination = root / "published"

    with pytest.raises(
        filesystem.RecoveryV2FilesystemError,
        match="RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED",
    ):
        filesystem.publish_directory_noreplace(
            source,
            destination,
            repository_root=root,
            expected_files={"proof.json": hashlib.sha256(b"drift\n").hexdigest()},
        )

    assert not destination.exists()
    assert (source / "proof.json").read_bytes() == payload


@pytest.mark.skipif(os.name == "nt", reason="POSIX inherited descriptor contract")
def test_posix_anchored_temporary_descriptor_is_usable_by_child(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    parent = root / "candidate"
    parent.mkdir(parents=True)

    with filesystem.anchored_temporary_directory(
        parent,
        prefix=".lease-",
        repository_root=root,
    ) as lease:
        output = lease.runtime_path / "child-proof.json"
        result = subprocess.run(
            (
                sys.executable,
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b'child\\n')",
                str(output),
            ),
            check=False,
            close_fds=True,
            pass_fds=lease.pass_fds,
        )
        assert result.returncode == 0
        lease.require_attached()
        assert (lease.path / "child-proof.json").read_bytes() == b"child\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows inherited handle contract")
def test_windows_anchored_temporary_handle_is_usable_by_supervised_child(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    parent = root / "candidate"
    parent.mkdir(parents=True)

    with filesystem.anchored_temporary_directory(
        parent,
        prefix=".lease-",
        repository_root=root,
    ) as lease:
        assert len(lease.pass_handles) == 1
        child = (
            "import pathlib,sys;"
            "from robin.recovery_v2_filesystem import "
            "require_inherited_windows_directory_capability as require;"
            "handle=int(sys.argv[1]);path=pathlib.Path(sys.argv[2]);"
            "require(handle,path,repository_root=pathlib.Path(sys.argv[3]));"
            "(path/'child-proof.json').write_bytes(b'child\\n')"
        )
        result = supervision.run_child_once(
            (
                sys.executable,
                "-c",
                child,
                str(lease.pass_handles[0]),
                str(lease.path),
                str(root),
            ),
            timeout_seconds=10,
            pass_handles=lease.pass_handles,
        )
        assert result == 0
        lease.require_attached()
        assert (lease.path / "child-proof.json").read_bytes() == b"child\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows non-inherited handle contract")
def test_windows_foreign_handle_number_is_rejected_before_any_handle_reuse(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    parent = root / "candidate"
    parent.mkdir(parents=True)

    with filesystem.anchored_temporary_directory(
        parent,
        prefix=".lease-",
        repository_root=root,
    ) as lease:
        assert len(lease.pass_handles) == 1
        child = (
            "import pathlib,sys;"
            "from robin.recovery_v2_filesystem import "
            "require_inherited_windows_directory_capability as require;"
            "require(int(sys.argv[1]),pathlib.Path(sys.argv[2]),"
            "repository_root=pathlib.Path(sys.argv[3]))"
        )
        result = subprocess.run(
            (
                sys.executable,
                "-c",
                child,
                str(lease.pass_handles[0]),
                str(lease.path),
                str(root),
            ),
            check=False,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert result.returncode != 0
        lease.require_attached()


@pytest.mark.skipif(os.name == "nt", reason="POSIX detached directory contract")
def test_posix_anchored_temporary_lease_rejects_path_replacement_before_child(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    parent = root / "candidate"
    parent.mkdir(parents=True)

    with filesystem.anchored_temporary_directory(
        parent,
        prefix=".lease-",
        repository_root=root,
    ) as lease:
        detached = parent / "detached"
        lease.path.rename(detached)
        lease.path.mkdir()
        with pytest.raises(
            filesystem.RecoveryV2FilesystemError,
            match="RECOVERY_V2_FILESYSTEM_DIRECTORY_DETACHED",
        ):
            lease.require_attached()


@pytest.mark.skipif(os.name != "nt", reason="Windows post-rename mutation seam")
def test_windows_directory_postrename_mutation_is_rejected_and_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    source = root / "candidate" / "artifacts"
    source.mkdir(parents=True)
    original = b'{"candidate":true}\n'
    (source / "proof.json").write_bytes(original)
    destination = root / "published"
    original_open = filesystem._windows_open_directory
    mutated = False

    def mutate_after_rename(path: Path, **kwargs: Any) -> int:
        nonlocal mutated
        if path == destination and not mutated:
            mutated = True
            (destination / "proof.json").write_bytes(b'{"mutated":true}\n')
        return original_open(path, **kwargs)

    monkeypatch.setattr(filesystem, "_windows_open_directory", mutate_after_rename)
    with pytest.raises(
        filesystem.RecoveryV2FilesystemError,
        match="RECOVERY_V2_FILESYSTEM_DIRECTORY_CHANGED",
    ):
        filesystem.publish_directory_noreplace(
            source,
            destination,
            repository_root=root,
            expected_files={"proof.json": hashlib.sha256(original).hexdigest()},
        )

    assert mutated is True
    assert not destination.exists()
    assert source.is_dir()
    assert (source / "proof.json").read_bytes() == b'{"mutated":true}\n'


def test_binding_reservation_is_conservative_for_parent_process_loss() -> None:
    reservation = bindings._reservation_document(main_sha="a" * 40, preflight_run_id="300")
    assert reservation["effect_counter_certainty"] == "CONSERVATIVE_UPPER_BOUNDS"
    assert reservation["secret_writes_attempted_upper_bound"] == 4
    assert reservation["secret_writes_confirmed_upper_bound"] == 4
    assert reservation["secret_names_in_order"] == bindings.BINDING_ORDER
    assert reservation["secret_value_readbacks"] == 0
    assert reservation["automatic_retries"] == 0


def test_binding_replace_failure_preserves_conservative_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    receipt = release / "bindings.json"
    monkeypatch.setattr(bindings, "_REPOSITORY_ROOT", tmp_path)
    reservation = bindings._reservation_bytes(main_sha="a" * 40, preflight_run_id="300")
    bindings._write_report(receipt, reservation, exclusive=True)

    def fail_replace(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("synthetic replace interruption")

    monkeypatch.setattr(bindings, "_recovery_v2_replace_bytes", fail_replace)
    with pytest.raises(bindings.BindingInstallerV2Error, match="REPORT_PATH_FORBIDDEN"):
        bindings._write_report(receipt, b'{"verdict":"SUCCESS"}\n', exclusive=False)
    assert receipt.read_bytes() == reservation
    assert json.loads(receipt.read_bytes())["secret_writes_attempted_upper_bound"] == 4


def _observer_pull_run(
    *,
    run_id: int,
    head_sha: str,
    pr_number: int = 71,
    status: str = "completed",
    conclusion: str | None = "failure",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "path": delivery._WORKFLOW_PATH,
        "head_branch": delivery._BRANCH,
        "head_sha": head_sha,
        "event": "pull_request",
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion,
        "created_at": "2026-08-31T01:00:00Z",
        "updated_at": "2026-08-31T01:01:00Z",
        "repository": {"full_name": delivery.EXPECTED_REPOSITORY},
        "head_repository": {"full_name": delivery.EXPECTED_REPOSITORY},
        "pull_requests": [
            {
                "number": pr_number,
                "head": {
                    "ref": delivery._BRANCH,
                    "sha": head_sha,
                    "repo": {"full_name": delivery.EXPECTED_REPOSITORY},
                },
                "base": {
                    "ref": "main",
                    "repo": {"full_name": delivery.EXPECTED_REPOSITORY},
                },
            }
        ],
    }


def test_pr_c_observer_rejects_any_extra_run_for_the_same_pull_request() -> None:
    head_sha = "a" * 40
    document = {
        "total_count": 2,
        "workflow_runs": [
            _observer_pull_run(run_id=101, head_sha=head_sha),
            _observer_pull_run(run_id=102, head_sha="b" * 40),
        ],
    }

    with pytest.raises(delivery.DeliveryEvidenceV2Error, match="OBSERVER_RUN_INVALID"):
        delivery._observer_target_run(
            document,
            phase="C1",
            pr_number=71,
            expected_head_sha=head_sha,
        )


def test_pr_c_c2_observer_requires_exact_c1_and_c2_run_set() -> None:
    c1_sha = "a" * 40
    c2_sha = "b" * 40
    c1 = _observer_pull_run(run_id=101, head_sha=c1_sha)
    c1_proof = {
        "run_id": 101,
        "run_attempt": 1,
        "head_sha": c1_sha,
        "conclusion": "failure",
    }
    c2 = _observer_pull_run(
        run_id=102,
        head_sha=c2_sha,
        conclusion="success",
    )
    observed = delivery._observer_target_run(
        {"total_count": 2, "workflow_runs": [c1, c2]},
        phase="C2",
        pr_number=71,
        expected_head_sha=c2_sha,
        predecessor_run=c1_proof,
    )

    assert observed == c2


def test_materializer_execution_reservation_is_host_local_and_non_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    state_base = tmp_path / "state"
    state_base.mkdir()
    host_hash = "c" * 64
    monkeypatch.setattr(
        terminal,
        "_execution_state_context",
        lambda *, root: (state_base, host_hash),
    )
    arguments = {
        "kind": "TERMINAL",
        "root": repository,
        "main_sha": "a" * 40,
        "head_sha": "b" * 40,
        "reservation_commit_sha": "b" * 40,
        "terminal_intent_payload": b'{"terminal":true}\n',
        "delivery_intent_payload": b'{"delivery":true}\n',
        "remote_reads_conservatively_consumed": 14,
        "github_gets_conservatively_consumed": 13,
        "artifact_downloads_conservatively_consumed": 0,
        "additional_binding": {"live_run_id": "123"},
        "observed_at": delivery._timestamp("2026-08-31T01:00:00Z"),
    }

    receipt = terminal._reserve_materializer_execution(**arguments)
    assert receipt["host_identity_sha256"] == host_hash
    with pytest.raises(terminal.TerminalEvidenceV2Error, match="ALREADY_RESERVED"):
        terminal._reserve_materializer_execution(**arguments)


def test_materializers_reserve_before_their_first_remote_intent_validation() -> None:
    terminal_source = inspect.getsource(terminal.materialize_terminal_evidence)
    delivery_source = inspect.getsource(delivery.materialize_delivery_evidence)

    assert terminal_source.index("verify_remote=False") < terminal_source.index(
        "_reserve_materializer_execution("
    ) < terminal_source.rindex("_validate_authoritative_intent_set(")
    assert delivery_source.index("verify_remote=False") < delivery_source.index(
        "_reserve_materializer_execution("
    ) < delivery_source.rindex("_validate_authoritative_intent_set(")
