"""Restaurer et borner l'état durable GitHub Artifact du pipeline shadow."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

API_VERSION = "2022-11-28"
STATE_PREFIX = "shadow-state-"


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "robin-stades-shadow-state",
    }


def _open(
    request: urllib.request.Request,
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> Any:
    return (opener or urllib.request.urlopen)(request)  # noqa: S310


def list_state_artifacts(
    *,
    repository: str,
    token: str,
    api_url: str = "https://api.github.com",
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> list[dict[str, Any]]:
    url = f"{api_url.rstrip('/')}/repos/{repository}/actions/artifacts?per_page=100"
    request = urllib.request.Request(url, headers=_headers(token))
    with _open(request, opener) as response:
        payload = json.loads(response.read().decode("utf-8"))
    artifacts = payload.get("artifacts", [])
    return [
        item
        for item in artifacts
        if isinstance(item, dict)
        and str(item.get("name", "")).startswith(STATE_PREFIX)
        and not item.get("expired", False)
    ]


def select_latest_state(
    artifacts: list[dict[str, Any]],
    *,
    current_run_id: str | None = None,
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in artifacts
        if str((item.get("workflow_run") or {}).get("id", "")) != current_run_id
    ]
    return max(
        candidates,
        key=lambda item: (str(item.get("created_at", "")), int(item.get("id", 0))),
        default=None,
    )


def safe_extract_zip(payload: bytes, destination: Path) -> int:
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            target = (root / item.filename).resolve()
            if root not in target.parents:
                raise ValueError(f"chemin d'artefact interdit: {item.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            extracted += 1
    return extracted


def restore_latest_state(
    *,
    repository: str,
    token: str,
    destination: Path,
    current_run_id: str | None = None,
    api_url: str = "https://api.github.com",
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> dict[str, object]:
    artifacts = list_state_artifacts(
        repository=repository,
        token=token,
        api_url=api_url,
        opener=opener,
    )
    latest = select_latest_state(artifacts, current_run_id=current_run_id)
    if latest is None:
        return {
            "status": "STATE_NOT_FOUND",
            "artifact_id": None,
            "files_restored": 0,
        }
    request = urllib.request.Request(
        str(latest["archive_download_url"]),
        headers=_headers(token),
    )
    with _open(request, opener) as response:
        payload = response.read()
    restored = safe_extract_zip(payload, destination)
    return {
        "status": "STATE_RESTORED",
        "artifact_id": int(latest["id"]),
        "artifact_name": str(latest["name"]),
        "files_restored": restored,
    }


def prune_state_artifacts(
    *,
    repository: str,
    token: str,
    current_artifact_name: str,
    keep: int = 2,
    api_url: str = "https://api.github.com",
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> dict[str, object]:
    artifacts = list_state_artifacts(
        repository=repository,
        token=token,
        api_url=api_url,
        opener=opener,
    )
    names = {str(item.get("name")) for item in artifacts}
    if current_artifact_name not in names:
        return {
            "status": "PRUNE_DEFERRED",
            "deleted": 0,
            "reason": "current_artifact_not_visible",
        }
    ordered = sorted(
        artifacts,
        key=lambda item: (str(item.get("created_at", "")), int(item.get("id", 0))),
        reverse=True,
    )
    deleted = 0
    for item in ordered[max(1, keep) :]:
        url = (
            f"{api_url.rstrip('/')}/repos/{repository}/actions/artifacts/"
            f"{int(item['id'])}"
        )
        request = urllib.request.Request(
            url,
            headers=_headers(token),
            method="DELETE",
        )
        with _open(request, opener):
            deleted += 1
    return {"status": "PRUNED", "deleted": deleted, "kept": min(keep, len(ordered))}


def required_token(environment: Mapping[str, str]) -> str:
    token = (environment.get("GH_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("GH_TOKEN absent; aucune valeur de secret n'est affichée")
    return token


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--repo", required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--current-run-id")

    prune = subparsers.add_parser("prune")
    prune.add_argument("--repo", required=True)
    prune.add_argument("--current-artifact-name", required=True)
    prune.add_argument("--keep", type=int, default=2)

    args = parser.parse_args()
    token = required_token(os.environ)
    try:
        if args.command == "restore":
            result = restore_latest_state(
                repository=args.repo,
                token=token,
                destination=args.destination,
                current_run_id=args.current_run_id,
            )
        else:
            result = prune_state_artifacts(
                repository=args.repo,
                token=token,
                current_artifact_name=args.current_artifact_name,
                keep=args.keep,
            )
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"GitHub Artifact indisponible (HTTP {exc.code}); aucun secret affiché"
        ) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
