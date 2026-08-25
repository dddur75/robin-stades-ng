#!/usr/bin/env python3
"""Default-preflight atomic one-shot DNS-to-Owner-Review-Pack runner."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import cast

from robin.capture.bootstrap_contracts import (
    OwnerReviewPackV1,
    RealCaptureWorkspaceReceiptV1,
)
from robin.capture.owner_review_pack import owner_authorization_statement_v1
from robin.capture.predns_orchestration import (
    HistoricalMarkerExpectationV1,
    inspect_provider_markers_read_only_v1,
    run_owner_review_pack_once_v1,
)
from robin.capture.storage import _safe_read_bounded
from robin.capture.workspace_bootstrap import (
    assert_real_capture_workspace_receipt_current_v1,
    assert_workspace_control_artifact_destination_v1,
    load_tracked_real_execution_mission_manifest_v1,
)

_MAXIMUM_JSON_BYTES = 4_194_304


def _read(path: Path) -> bytes:
    return _safe_read_bounded(path.absolute(), maximum_bytes=_MAXIMUM_JSON_BYTES)


def _system_resolver(
    host: str,
    port: int,
    family: int,
    socket_type: int,
    protocol: int,
) -> Iterable[tuple[object, ...]]:
    return cast(
        Iterable[tuple[object, ...]],
        socket.getaddrinfo(host, port, family, socket_type, protocol),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-receipt", required=True, type=Path)
    parser.add_argument("--mission-manifest", required=True, type=Path)
    parser.add_argument("--pre-dns-bundle", required=True, type=Path)
    parser.add_argument("--output-binding", required=True, type=Path)
    parser.add_argument("--output-pack-directory", required=True, type=Path)
    parser.add_argument("--historical-marker", required=True, type=Path)
    parser.add_argument("--historical-marker-manifest-sha256", required=True)
    parser.add_argument("--historical-marker-sha256", required=True)
    parser.add_argument("--historical-marker-acl-sha256", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--owner-present-for-review", action="store_true")
    parser.add_argument("--binding-ttl-seconds", type=int, default=900)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    execute = bool(arguments.execute)
    try:
        workspace = RealCaptureWorkspaceReceiptV1.model_validate_json(
            _read(arguments.workspace_receipt)
        )
        assert_real_capture_workspace_receipt_current_v1(workspace)
        manifest = load_tracked_real_execution_mission_manifest_v1(
            Path(workspace.runtime_repository_root),
            arguments.mission_manifest,
        )
        assert_workspace_control_artifact_destination_v1(
            workspace,
            arguments.output_binding,
        )
        assert_workspace_control_artifact_destination_v1(
            workspace,
            arguments.output_pack_directory,
        )
        marker_inspector = partial(
            inspect_provider_markers_read_only_v1,
            historical_marker=HistoricalMarkerExpectationV1(
                path=arguments.historical_marker,
                authority_manifest_sha256=arguments.historical_marker_manifest_sha256,
                raw_sha256=arguments.historical_marker_sha256,
                acl_sha256=arguments.historical_marker_acl_sha256,
            ),
        )
        result = run_owner_review_pack_once_v1(
            bundle_directory=arguments.pre_dns_bundle,
            workspace_receipt=workspace,
            mission_manifest=manifest,
            output_binding_path=arguments.output_binding,
            output_pack_directory=arguments.output_pack_directory,
            resolver=_system_resolver,
            marker_inspector=marker_inspector,
            execute=execute,
            owner_present_for_review=bool(arguments.owner_present_for_review),
            binding_ttl_seconds=arguments.binding_ttl_seconds,
        )
    except Exception as error:
        code = getattr(error, "code", "ATOMIC_OWNER_PACK_RUNNER_FAILED")
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 2
    statement: str | None = None
    if result.status == "OWNER_REVIEW_PACK_CREATED":
        pack_paths = tuple(arguments.output_pack_directory.glob("owner-review-pack-*.json"))
        if len(pack_paths) != 1:
            print(
                json.dumps(
                    {"status": "FAILED", "code": "OWNER_REVIEW_PACK_ARTIFACT_MISSING"},
                    sort_keys=True,
                )
            )
            return 2
        pack = OwnerReviewPackV1.model_validate_json(_read(pack_paths[0]))
        statement = owner_authorization_statement_v1(pack)
    print(
        json.dumps(
            {
                "status": result.status,
                "preflight_errors": result.preflight.errors,
                "preflight_checked_at_utc": result.preflight.checked_at_utc.isoformat().replace(
                    "+00:00", "Z"
                ),
                "usable_margin_seconds": result.preflight.usable_margin_seconds,
                "resolver_operations": result.resolver_operations,
                "resolver_retries": 0,
                "pack_builds": result.pack_builds,
                "provider_network_binding_sha256": result.binding_sha256,
                "owner_review_pack_sha256": result.pack_sha256,
                "receipt_path": str(result.receipt_path) if result.receipt_path else None,
                "hard_stop_code": result.hard_stop_code,
                "provider_tcp": 0,
                "provider_http": 0,
                "secret_reads": 0,
                "owner_authorized_artifacts": 0,
                "activations": 0,
                "captures": 0,
                "promotions": 0,
                "bets": 0,
                "owner_authorization_statement": statement,
            },
            sort_keys=True,
        )
    )
    return 0 if result.status in {"PREFLIGHT_ACCEPT", "OWNER_REVIEW_PACK_CREATED"} else 2


if __name__ == "__main__":
    sys.exit(main())
