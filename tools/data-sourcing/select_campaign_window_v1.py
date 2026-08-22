#!/usr/bin/env python3
"""Freeze the complete current H24/H2/H1 universe and select its unique winner."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from robin.capture import (
    CampaignLeagueCorpusCountV1,
    CampaignWindowSelectionV1,
    CaptureContractError,
    FixtureTargetSetV1,
    RealCaptureWorkspaceReceiptV1,
    ScientificCorpusSnapshotV1,
)
from robin.capture.contracts import canonical_json_bytes, strict_json_loads, strict_json_object
from robin.capture.live_contracts import LIVE_ALLOWED_SPORT_KEYS
from robin.capture.storage import (
    CaptureStorageError,
    _safe_read_bounded,
    validate_exclusive_local_directory_identity,
)
from robin.capture.workspace_bootstrap import (
    WorkspaceBootstrapError,
    assert_real_capture_workspace_receipt_current_v1,
    assert_workspace_control_artifact_destination_v1,
    load_tracked_real_execution_mission_manifest_v1,
)

_MAXIMUM_ARTIFACT_BYTES = 4_194_304
ZERO_EFFECT_COUNT = 0


class CampaignSelectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _load(path: Path) -> Any:
    validate_exclusive_local_directory_identity(path.absolute().parent)
    return strict_json_loads(
        _safe_read_bounded(path.absolute(), maximum_bytes=_MAXIMUM_ARTIFACT_BYTES)
    )


def _load_corpus_snapshot(
    path: Path,
    *,
    workspace: RealCaptureWorkspaceReceiptV1,
    selected_at_utc: datetime,
) -> ScientificCorpusSnapshotV1:
    validate_exclusive_local_directory_identity(path.absolute().parent)
    evidence_bytes = _safe_read_bounded(path.absolute(), maximum_bytes=_MAXIMUM_ARTIFACT_BYTES)
    evidence = strict_json_object(evidence_bytes)
    if (
        set(evidence)
        != {
            "schema_version",
            "observed_at_utc",
            "admitted_fixture_counts",
        }
        or evidence.get("schema_version") != "robin-owner-observed-scientific-corpus-v1"
    ):
        raise CampaignSelectionError("CAMPAIGN_CORPUS_EVIDENCE_INVALID")
    raw_counts = evidence.get("admitted_fixture_counts")
    raw_observed = evidence.get("observed_at_utc")
    if not isinstance(raw_counts, dict) or set(raw_counts) != set(LIVE_ALLOWED_SPORT_KEYS):
        raise CampaignSelectionError("CAMPAIGN_CORPUS_COUNTS_INVALID")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in raw_counts.values()
    ):
        raise CampaignSelectionError("CAMPAIGN_CORPUS_COUNTS_INVALID")
    if not isinstance(raw_observed, str):
        raise CampaignSelectionError("CAMPAIGN_CORPUS_OBSERVED_AT_INVALID")
    try:
        observed_at = datetime.fromisoformat(raw_observed.replace("Z", "+00:00"))
    except ValueError:
        raise CampaignSelectionError("CAMPAIGN_CORPUS_OBSERVED_AT_INVALID") from None
    if not workspace.prepared_at_utc <= observed_at <= selected_at_utc:
        raise CampaignSelectionError("CAMPAIGN_CORPUS_NOT_POST_BOOTSTRAP")
    return ScientificCorpusSnapshotV1.issue(
        observed_at_utc=observed_at,
        source_evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        league_counts=tuple(
            CampaignLeagueCorpusCountV1(
                sport_key=sport_key,
                admitted_fixture_count=raw_counts[sport_key],
            )
            for sport_key in LIVE_ALLOWED_SPORT_KEYS
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-receipt", type=Path, required=True)
    parser.add_argument("--mission-manifest", type=Path, required=True)
    parser.add_argument(
        "--fixture-target-set",
        type=Path,
        required=True,
        action="append",
        dest="fixture_target_sets",
    )
    parser.add_argument("--corpus-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    selected_at = datetime.now(UTC)
    try:
        workspace = RealCaptureWorkspaceReceiptV1.model_validate(_load(arguments.workspace_receipt))
        if not workspace.authority_eligible_for_real_execution:
            raise CampaignSelectionError("WORKSPACE_IN_CLONE_VERIFY_REQUIRED")
        assert_real_capture_workspace_receipt_current_v1(workspace)
        manifest = load_tracked_real_execution_mission_manifest_v1(
            Path(workspace.runtime_repository_root),
            arguments.mission_manifest,
        )
        target_sets = tuple(
            FixtureTargetSetV1.model_validate(_load(path)) for path in arguments.fixture_target_sets
        )
        corpus = _load_corpus_snapshot(
            arguments.corpus_evidence,
            workspace=workspace,
            selected_at_utc=selected_at,
        )
        selection = CampaignWindowSelectionV1.issue(
            selected_at_utc=selected_at,
            workspace_receipt_sha256=workspace.canonical_receipt_hash,
            workspace_prepared_at_utc=workspace.prepared_at_utc,
            mission_manifest_sha256=manifest.canonical_manifest_sha256(),
            mission_expires_at_utc=manifest.expires_at,
            source_target_sets=target_sets,
            corpus_snapshot=corpus,
        )
        output = assert_workspace_control_artifact_destination_v1(
            workspace,
            arguments.output,
        )
        with output.open("xb") as stream:
            stream.write(canonical_json_bytes(selection.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except (
        CampaignSelectionError,
        CaptureContractError,
        CaptureStorageError,
        WorkspaceBootstrapError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        code = getattr(error, "code", "CAMPAIGN_SELECTION_INPUT_INVALID")
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 2
    winner = selection.selected_candidate()
    status_counts = {
        status: sum(candidate.status == status for candidate in selection.candidates)
        for status in (
            "MISSED_NOT_BACKDATED",
            "NON_ADMITTING_SCIENTIFIC_AUTHORITY",
            "FUTURE_INSUFFICIENT_MARGIN",
            "FUTURE_NOT_OPEN",
            "OPEN_INSUFFICIENT_MARGIN",
            "OPEN_SELECTABLE",
        )
    }
    print(
        json.dumps(
            {
                "status": (
                    "CAMPAIGN_SELECTED_READY_NOW"
                    if selection.selected_ready_at_selection
                    else "CAMPAIGN_SELECTED_FUTURE_WAIT_AND_REFRESH_REQUIRED"
                ),
                "campaign_selection_sha256": selection.canonical_selection_hash,
                "selected_candidate_id": winner.candidate_id,
                "selected_candidate_sha256": winner.canonical_candidate_hash,
                "fixture_target_set_sha256": winner.fixture_target_set.canonical_set_hash,
                "sport_key": winner.request.sport_key,
                "window_id": winner.window_id,
                "fixture_coverage": winner.fixture_coverage,
                "protocol_role_value": winner.protocol_role_value,
                "window_not_before_utc": winner.window_not_before_utc.isoformat(),
                "window_expires_at_utc": winner.window_expires_at_utc.isoformat(),
                "selected_not_before_utc": selection.selected_not_before_utc.isoformat(),
                "selected_ready_at_selection": selection.selected_ready_at_selection,
                "ranking_policy": selection.ranking_policy,
                "candidate_status_counts": status_counts,
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
