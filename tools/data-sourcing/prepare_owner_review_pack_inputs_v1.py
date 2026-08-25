#!/usr/bin/env python3
"""Build immutable five-league PRE-DNS inputs without provider DNS or pack creation."""

from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from robin.capture.bootstrap_contracts import RealCaptureWorkspaceReceiptV1
from robin.capture.official_schedule_sources import BuiltinHttpsOfficialScheduleFetcher
from robin.capture.predns_orchestration import (
    HistoricalMarkerExpectationV1,
    inspect_provider_markers_read_only_v1,
    prepare_owner_review_pack_inputs_v1,
)
from robin.capture.storage import _safe_read_bounded
from robin.capture.workspace_bootstrap import (
    assert_real_capture_workspace_receipt_current_v1,
    assert_workspace_control_artifact_destination_v1,
    load_tracked_real_execution_mission_manifest_v1,
)

_MAXIMUM_JSON_BYTES = 4_194_304
_MAXIMUM_SOURCE_PLAN_BYTES = 1_048_576


def _read(path: Path, maximum_bytes: int = _MAXIMUM_JSON_BYTES) -> bytes:
    return _safe_read_bounded(path.absolute(), maximum_bytes=maximum_bytes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-receipt", required=True, type=Path)
    parser.add_argument("--mission-manifest", required=True, type=Path)
    parser.add_argument("--source-plan", required=True, type=Path)
    parser.add_argument("--scientific-corpus-evidence", required=True, type=Path)
    parser.add_argument("--review-dp6", required=True, type=Path)
    parser.add_argument("--review-c4", required=True, type=Path)
    parser.add_argument("--review-c2", required=True, type=Path)
    parser.add_argument("--review-a2", required=True, type=Path)
    parser.add_argument("--historical-marker", required=True, type=Path)
    parser.add_argument("--historical-marker-manifest-sha256", required=True)
    parser.add_argument("--historical-marker-sha256", required=True)
    parser.add_argument("--historical-marker-acl-sha256", required=True)
    parser.add_argument("--output-parent", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        workspace_bytes = _read(arguments.workspace_receipt)
        workspace = RealCaptureWorkspaceReceiptV1.model_validate_json(workspace_bytes)
        assert_real_capture_workspace_receipt_current_v1(workspace)
        manifest_bytes = _read(arguments.mission_manifest)
        manifest = load_tracked_real_execution_mission_manifest_v1(
            Path(workspace.runtime_repository_root),
            arguments.mission_manifest,
        )
        assert_workspace_control_artifact_destination_v1(
            workspace,
            arguments.output_parent / "pre-dns-owner-pack-inputs-pending",
        )
        reviews = {
            "DP6": _read(arguments.review_dp6),
            "C4": _read(arguments.review_c4),
            "C2": _read(arguments.review_c2),
            "A2": _read(arguments.review_a2),
        }
        marker_inspector = partial(
            inspect_provider_markers_read_only_v1,
            historical_marker=HistoricalMarkerExpectationV1(
                path=arguments.historical_marker,
                authority_manifest_sha256=arguments.historical_marker_manifest_sha256,
                raw_sha256=arguments.historical_marker_sha256,
                acl_sha256=arguments.historical_marker_acl_sha256,
            ),
        )
        result = prepare_owner_review_pack_inputs_v1(
            workspace_receipt=workspace,
            workspace_receipt_bytes=workspace_bytes,
            mission_manifest=manifest,
            mission_manifest_bytes=manifest_bytes,
            source_plan_bytes=_read(
                arguments.source_plan,
                maximum_bytes=_MAXIMUM_SOURCE_PLAN_BYTES,
            ),
            corpus_evidence_reader=lambda: _read(arguments.scientific_corpus_evidence),
            output_parent=arguments.output_parent,
            reviews=reviews,
            fetcher=BuiltinHttpsOfficialScheduleFetcher(),
            marker_inspector=marker_inspector,
        )
    except Exception as error:
        code = getattr(error, "code", "PRE_DNS_ORCHESTRATION_FAILED")
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": result.status,
                "bundle_directory": (
                    str(result.bundle_directory) if result.bundle_directory is not None else None
                ),
                "bundle_manifest_sha256": result.bundle_manifest_sha256,
                "campaign_selection_sha256": (
                    result.selection.canonical_selection_hash
                    if result.selection is not None
                    else None
                ),
                "recommended_refresh_utc": (
                    result.recommended_refresh_utc.isoformat().replace("+00:00", "Z")
                    if result.recommended_refresh_utc is not None
                    else None
                ),
                "recommended_refresh_europe_paris": (result.recommended_refresh_europe_paris),
                "counters": {
                    "iterations": result.counters.iterations,
                    "official_reads": result.counters.official_reads,
                    "supporting_official_reads": result.counters.supporting_official_reads,
                    "corpus_snapshots": result.counters.corpus_snapshots,
                    "corpus_validations": result.counters.corpus_validations,
                    "target_set_freezes": result.counters.target_set_freezes,
                    "selector_invocations": result.counters.selector_invocations,
                },
                "iteration_codes": result.iteration_codes,
                "provider_dns": 0,
                "provider_tcp": 0,
                "provider_http": 0,
                "secret_reads": 0,
                "owner_review_pack_builds": 0,
            },
            sort_keys=True,
        )
    )
    return 0 if result.status != "PRE_DNS_CONVERGENCE_EXHAUSTED" else 2


if __name__ == "__main__":
    sys.exit(main())
