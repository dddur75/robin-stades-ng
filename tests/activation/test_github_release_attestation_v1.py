from __future__ import annotations

from pathlib import Path

import pytest

import scripts.github_release_attestation_v1 as attestation

REPOSITORY = "dddur75/robin-stades-ng"
WORKFLOW = ".github/workflows/chronos-production-bootstrap-v3.yml"
RUN_ID = "123456789"
MAIN_SHA = "1" * 40
ARTIFACT = f"chronos-preflight-v3-{RUN_ID}"
FILENAME = "chronos-preflight-artifact-v3.json"


def _github_response(path: str) -> dict[str, object]:
    if path.endswith(f"/actions/runs/{RUN_ID}"):
        return {
            "id": int(RUN_ID),
            "run_attempt": 1,
            "head_sha": MAIN_SHA,
            "head_branch": "main",
            "event": "workflow_dispatch",
            "status": "completed",
            "conclusion": "success",
            "path": WORKFLOW,
            "repository": {"full_name": REPOSITORY},
        }
    if path.endswith(f"/actions/runs/{RUN_ID}/artifacts?per_page=100"):
        return {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 987,
                    "name": ARTIFACT,
                    "expired": False,
                    "size_in_bytes": 123,
                    "workflow_run": {
                        "id": int(RUN_ID),
                        "head_sha": MAIN_SHA,
                        "head_branch": "main",
                    },
                }
            ],
        }
    raise AssertionError(path)


def test_attestation_requires_success_and_copies_one_exact_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attestation, "_github_json", _github_response)

    def download(**values: object) -> None:
        target = Path(str(values["target"]))
        (target / FILENAME).write_bytes(b'{"attested":true}\n')

    monkeypatch.setattr(attestation, "_download", download)
    output = tmp_path / "output" / FILENAME
    receipt = attestation.attest_and_download(
        repository=REPOSITORY,
        workflow_path=WORKFLOW,
        run_id=RUN_ID,
        main_sha=MAIN_SHA,
        artifact_name=ARTIFACT,
        artifact_filename=FILENAME,
        output_path=output,
    )
    assert output.read_bytes() == b'{"attested":true}\n'
    assert receipt["run_id"] == int(RUN_ID)
    assert receipt["artifact_id"] == 987
    assert receipt["conclusion"] == "success"


def test_attestation_rejects_failed_source_run_before_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(path: str) -> dict[str, object]:
        document = _github_response(path)
        if path.endswith(f"/actions/runs/{RUN_ID}"):
            document["conclusion"] = "failure"
        return document

    downloaded = False

    def forbidden_download(**_values: object) -> None:
        nonlocal downloaded
        downloaded = True

    monkeypatch.setattr(attestation, "_github_json", failed_run)
    monkeypatch.setattr(attestation, "_download", forbidden_download)
    with pytest.raises(
        attestation.GitHubReleaseAttestationError,
        match="GITHUB_RELEASE_RUN_MISMATCH",
    ):
        attestation.attest_and_download(
            repository=REPOSITORY,
            workflow_path=WORKFLOW,
            run_id=RUN_ID,
            main_sha=MAIN_SHA,
            artifact_name=ARTIFACT,
            artifact_filename=FILENAME,
            output_path=tmp_path / FILENAME,
        )
    assert downloaded is False


def test_current_main_attestation_fails_closed_on_stale_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = MAIN_SHA

    def reference(path: str) -> dict[str, object]:
        assert path.endswith("/git/ref/heads/main")
        return {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": observed},
        }

    monkeypatch.setattr(attestation, "_github_json", reference)
    assert attestation.assert_current_main(repository=REPOSITORY, main_sha=MAIN_SHA) == MAIN_SHA
    observed = "2" * 40
    with pytest.raises(
        attestation.GitHubReleaseAttestationError,
        match="GITHUB_RELEASE_MAIN_SHA_MISMATCH",
    ):
        attestation.assert_current_main(repository=REPOSITORY, main_sha=MAIN_SHA)


def test_attestation_rejects_duplicate_or_expired_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def duplicate(path: str) -> dict[str, object]:
        document = _github_response(path)
        if path.endswith("/artifacts?per_page=100"):
            artifacts = list(document["artifacts"])  # type: ignore[arg-type]
            document["artifacts"] = [*artifacts, dict(artifacts[0])]
            document["total_count"] = 2
        return document

    monkeypatch.setattr(attestation, "_github_json", duplicate)
    with pytest.raises(
        attestation.GitHubReleaseAttestationError,
        match="GITHUB_RELEASE_ARTIFACT_MISMATCH",
    ):
        attestation.attest_and_download(
            repository=REPOSITORY,
            workflow_path=WORKFLOW,
            run_id=RUN_ID,
            main_sha=MAIN_SHA,
            artifact_name=ARTIFACT,
            artifact_filename=FILENAME,
            output_path=tmp_path / FILENAME,
        )
