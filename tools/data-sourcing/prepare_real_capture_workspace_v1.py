#!/usr/bin/env python3
"""Prepare or verify the standalone real-capture workspace (no provider access)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from robin.capture.workspace_bootstrap import (
    WorkspaceBootstrapError,
    prepare_real_capture_workspace_v1,
)

ZERO_EFFECT_COUNT = 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("CREATE", "VERIFY", "INSPECT"), required=True)
    parser.add_argument("--runtime-parent", type=Path)
    parser.add_argument("--expected-main-sha", required=True)
    parser.add_argument("--git-executable", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    prepared_at = datetime.now(UTC)
    try:
        receipt = prepare_real_capture_workspace_v1(
            runtime_parent=arguments.runtime_parent,
            expected_main_sha=arguments.expected_main_sha,
            git_executable=arguments.git_executable,
            mode=arguments.mode,
            prepared_at_utc=prepared_at,
            receipt_output=arguments.receipt_output,
        )
    except (ValueError, WorkspaceBootstrapError) as error:
        code = getattr(error, "code", "BOOTSTRAP_INPUT_INVALID")
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": (
                    "VERIFIED_AUTHORITY_ELIGIBLE"
                    if receipt.authority_eligible_for_real_execution
                    else "CREATED_OR_INSPECTED_REQUIRES_IN_CLONE_VERIFY"
                ),
                "bootstrap_mode": receipt.bootstrap_mode,
                "bootstrap_tool_source_repository_root": (
                    receipt.bootstrap_tool_source_repository_root
                ),
                "bootstrap_tool_loaded_from_runtime_repository": (
                    receipt.bootstrap_tool_loaded_from_runtime_repository
                ),
                "bootstrap_package_source_repository_root": (
                    receipt.bootstrap_package_source_repository_root
                ),
                "bootstrap_package_loaded_from_runtime_repository": (
                    receipt.bootstrap_package_loaded_from_runtime_repository
                ),
                "authority_eligible_for_real_execution": (
                    receipt.authority_eligible_for_real_execution
                ),
                "receipt_sha256": receipt.canonical_receipt_hash,
                "repository_root": receipt.runtime_repository_root,
                "repository_root_fingerprint": receipt.repository_root_fingerprint,
                "control_temp_root": receipt.control_temp_root,
                "control_temp_fingerprint": receipt.control_temp_fingerprint,
                "capture_root": receipt.capture_root,
                "capture_root_fingerprint": receipt.capture_root_fingerprint,
                "git_executable_path": receipt.git_executable_path,
                "git_executable_sha256": receipt.git_executable_sha256,
                "provider_http_requests": ZERO_EFFECT_COUNT,
                "provider_tcp_connections": ZERO_EFFECT_COUNT,
                "provider_secret_reads": ZERO_EFFECT_COUNT,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
