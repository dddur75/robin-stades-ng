"""Attest and download one exact GitHub Actions release artifact."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # nosec B404 - argv-only invocation of the attested GitHub CLI.
import tempfile
from pathlib import Path
from typing import Any, cast

from robin.chronos_production import EXPECTED_REPOSITORY, require_sha

_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_MAX_ARTIFACT_FILE_BYTES = 10 * 1024 * 1024


class GitHubReleaseAttestationError(RuntimeError):
    """Sanitized GitHub release-attestation error."""


def assert_current_main(*, repository: str, main_sha: str) -> str:
    if repository != EXPECTED_REPOSITORY:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_REPOSITORY_FORBIDDEN")
    expected_sha = require_sha(main_sha, field="main_sha")
    reference = _github_json(f"repos/{repository}/git/ref/heads/main")
    target = reference.get("object")
    if (
        reference.get("ref") != "refs/heads/main"
        or not isinstance(target, dict)
        or target.get("type") != "commit"
        or target.get("sha") != expected_sha
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_MAIN_SHA_MISMATCH")
    return expected_sha


def _github_json(path: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(  # nosec B603 B607 - fixed CLI and validated API path.
            ["gh", "api", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=60,
        )
        document = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ATTESTATION_API_FAILED") from None
    if not isinstance(document, dict):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ATTESTATION_API_INVALID")
    return cast(dict[str, Any], document)


def _download(*, repository: str, run_id: str, artifact_name: str, target: Path) -> None:
    try:
        subprocess.run(  # nosec B603 B607 - fixed CLI and validated identifiers.
            [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                repository,
                "--name",
                artifact_name,
                "--dir",
                str(target),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ATTESTATION_DOWNLOAD_FAILED") from None


def _exact_downloaded_file(root: Path, filename: str) -> Path:
    if not filename or Path(filename).name != filename:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_FILENAME_INVALID")
    candidates = list(root.rglob(filename))
    if len(candidates) != 1:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_FILE_MISMATCH")
    candidate = candidates[0]
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        stat = candidate.lstat()
    except OSError:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_FILE_INVALID") from None
    if (
        candidate.is_symlink()
        or not candidate.is_file()
        or not resolved.is_relative_to(resolved_root)
        or stat.st_size <= 0
        or stat.st_size > _MAX_ARTIFACT_FILE_BYTES
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_FILE_INVALID")
    return resolved


def attest_and_download(
    *,
    repository: str,
    workflow_path: str,
    run_id: str,
    main_sha: str,
    artifact_name: str,
    artifact_filename: str,
    output_path: Path,
) -> dict[str, Any]:
    """Prove one successful first-attempt run and copy its exact artifact file."""

    if repository != EXPECTED_REPOSITORY:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_REPOSITORY_FORBIDDEN")
    if _RUN_ID.fullmatch(run_id) is None:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_RUN_ID_INVALID")
    expected_sha = require_sha(main_sha, field="main_sha")
    if not workflow_path.startswith(".github/workflows/") or not workflow_path.endswith(
        (".yml", ".yaml")
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_WORKFLOW_PATH_INVALID")
    expected_artifact_name = artifact_name.replace("{run_id}", run_id)
    if not expected_artifact_name or expected_artifact_name != artifact_name:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_NAME_INVALID")

    run = _github_json(f"repos/{repository}/actions/runs/{run_id}")
    run_repository = run.get("repository")
    if (
        run.get("id") != int(run_id)
        or run.get("run_attempt") != 1
        or run.get("head_sha") != expected_sha
        or run.get("head_branch") != "main"
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("path") != workflow_path
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != repository
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_RUN_MISMATCH")

    listing = _github_json(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = listing.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or type(listing.get("total_count")) is not int
        or listing.get("total_count") != len(artifacts)
        or len(artifacts) > 100
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_LIST_INVALID")
    matches = [
        item for item in artifacts if isinstance(item, dict) and item.get("name") == artifact_name
    ]
    if len(matches) != 1:
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_MISMATCH")
    artifact = cast(dict[str, Any], matches[0])
    workflow_run = artifact.get("workflow_run")
    if (
        artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < cast(int, artifact["size_in_bytes"]) <= _MAX_ARTIFACT_FILE_BYTES
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != int(run_id)
        or workflow_run.get("head_sha") != expected_sha
        or workflow_run.get("head_branch") != "main"
    ):
        raise GitHubReleaseAttestationError("GITHUB_RELEASE_ARTIFACT_MISMATCH")

    with tempfile.TemporaryDirectory(prefix="robin-release-attestation-") as temp_name:
        temp_root = Path(temp_name)
        _download(
            repository=repository,
            run_id=run_id,
            artifact_name=artifact_name,
            target=temp_root,
        )
        source = _exact_downloaded_file(temp_root, artifact_filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output_path)

    return {
        "schema_version": "github-release-artifact-attestation-v1",
        "repository": repository,
        "workflow_path": workflow_path,
        "run_id": int(run_id),
        "run_attempt": 1,
        "head_sha": expected_sha,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "artifact_id": artifact.get("id"),
        "artifact_name": artifact_name,
        "artifact_filename": artifact_filename,
        "artifact_size_in_bytes": artifact.get("size_in_bytes"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=EXPECTED_REPOSITORY)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-filename", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = attest_and_download(
            repository=args.repository,
            workflow_path=args.workflow_path,
            run_id=args.run_id,
            main_sha=args.main_sha,
            artifact_name=args.artifact_name,
            artifact_filename=args.artifact_filename,
            output_path=args.output,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except Exception as error:
        code = (
            str(error)
            if isinstance(error, GitHubReleaseAttestationError)
            else "GITHUB_RELEASE_ATTESTATION_FAILED"
        )
        print(code)
        raise SystemExit(1) from None
    print(f"GITHUB_RELEASE_ARTIFACT_ATTESTED:{report['run_id']}")


if __name__ == "__main__":
    main()
