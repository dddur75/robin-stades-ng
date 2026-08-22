#!/usr/bin/env python3
"""Freeze an owner-reviewed official schedule extraction into target authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from robin.capture import (
    CaptureContractError,
    FixtureTargetSetV1,
    OfficialFixtureTargetV1,
    RealCaptureWorkspaceReceiptV1,
)
from robin.capture.contracts import canonical_json_bytes, strict_json_object
from robin.capture.storage import (
    CaptureStorageError,
    _safe_read_bounded,
    validate_exclusive_local_directory_identity,
)
from robin.capture.workspace_bootstrap import (
    WorkspaceBootstrapError,
    assert_real_capture_workspace_receipt_current_v1,
    assert_workspace_control_artifact_destination_v1,
)

_MAXIMUM_EVIDENCE_BYTES = 1_048_576
_MAXIMUM_SOURCE_BYTES = 16_777_216


class OfficialTargetFreezeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def freeze_official_fixture_target_set_v1(
    *,
    evidence_bytes: bytes,
    official_source_content_bytes: bytes,
    workspace_receipt: RealCaptureWorkspaceReceiptV1,
    created_at_utc: datetime,
) -> FixtureTargetSetV1:
    evidence = strict_json_object(evidence_bytes)
    if (
        set(evidence)
        != {
            "schema_version",
            "target_set_id",
            "sport_key",
            "official_source_authority",
            "official_source_content_sha256",
            "source_observed_at_utc",
            "selection_horizon_not_before_utc",
            "selection_horizon_expires_at_utc",
            "official_schedule_fixture_count",
            "official_schedule_completeness",
            "fixtures",
        }
        or evidence.get("schema_version") != "robin-owner-observed-official-schedule-v1"
    ):
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_EVIDENCE_INVALID")
    fixtures = evidence.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_FIXTURES_INVALID")
    source_authority = evidence.get("official_source_authority")
    source_content_sha256 = evidence.get("official_source_content_sha256")
    source_observed = evidence.get("source_observed_at_utc")
    horizon_starts = evidence.get("selection_horizon_not_before_utc")
    horizon_expires = evidence.get("selection_horizon_expires_at_utc")
    fixture_count = evidence.get("official_schedule_fixture_count")
    completeness = evidence.get("official_schedule_completeness")
    if (
        not isinstance(source_authority, str)
        or not isinstance(source_observed, str)
        or not isinstance(source_content_sha256, str)
        or len(source_content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_content_sha256)
        or hashlib.sha256(official_source_content_bytes).hexdigest() != source_content_sha256
    ):
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_SOURCE_INVALID")
    if (
        not isinstance(horizon_starts, str)
        or not isinstance(horizon_expires, str)
        or isinstance(fixture_count, bool)
        or not isinstance(fixture_count, int)
        or fixture_count != len(fixtures)
        or completeness != "OWNER_REVIEWED_COMPLETE_OFFICIAL_HORIZON"
    ):
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_HORIZON_INVALID")
    try:
        source_observed_at = datetime.fromisoformat(source_observed.replace("Z", "+00:00"))
        horizon_starts_at = datetime.fromisoformat(horizon_starts.replace("Z", "+00:00"))
        horizon_expires_at = datetime.fromisoformat(horizon_expires.replace("Z", "+00:00"))
    except ValueError:
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_SOURCE_INVALID") from None
    evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    targets: list[OfficialFixtureTargetV1] = []
    for raw_fixture in fixtures:
        if not isinstance(raw_fixture, dict) or set(raw_fixture) != {
            "internal_fixture_target_id",
            "competition",
            "official_home_team",
            "official_away_team",
            "official_kickoff_utc",
        }:
            raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_FIXTURE_INVALID")
        fixture = cast(dict[str, Any], raw_fixture)
        kickoff = fixture["official_kickoff_utc"]
        if not isinstance(kickoff, str):
            raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_FIXTURE_INVALID")
        try:
            kickoff_at = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            targets.append(
                OfficialFixtureTargetV1.issue(
                    internal_fixture_target_id=fixture["internal_fixture_target_id"],
                    competition=fixture["competition"],
                    sport_key=evidence["sport_key"],
                    official_home_team=fixture["official_home_team"],
                    official_away_team=fixture["official_away_team"],
                    official_kickoff_utc=kickoff_at,
                    official_source_authority=source_authority,
                    source_observed_at_utc=source_observed_at,
                    source_evidence_sha256=evidence_sha256,
                )
            )
        except (CaptureContractError, KeyError, TypeError, ValueError):
            raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_FIXTURE_INVALID") from None
    try:
        return FixtureTargetSetV1.issue(
            target_set_id=evidence["target_set_id"],
            sport_key=evidence["sport_key"],
            workspace_receipt_sha256=workspace_receipt.canonical_receipt_hash,
            created_at_utc=created_at_utc,
            official_schedule_horizon_not_before_utc=horizon_starts_at,
            official_schedule_horizon_expires_at_utc=horizon_expires_at,
            official_schedule_fixture_count=fixture_count,
            official_schedule_completeness=completeness,
            targets=tuple(targets),
        )
    except (CaptureContractError, KeyError, TypeError, ValueError):
        raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_TARGET_SET_INVALID") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-receipt", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--official-source-content", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    created = datetime.now(UTC)
    try:
        validate_exclusive_local_directory_identity(arguments.workspace_receipt.absolute().parent)
        validate_exclusive_local_directory_identity(arguments.evidence.absolute().parent)
        validate_exclusive_local_directory_identity(
            arguments.official_source_content.absolute().parent
        )
        evidence_bytes = _safe_read_bounded(
            arguments.evidence.absolute(),
            maximum_bytes=_MAXIMUM_EVIDENCE_BYTES,
        )
        official_source_content_bytes = _safe_read_bounded(
            arguments.official_source_content.absolute(),
            maximum_bytes=_MAXIMUM_SOURCE_BYTES,
        )
        workspace_bytes = _safe_read_bounded(
            arguments.workspace_receipt.absolute(),
            maximum_bytes=_MAXIMUM_EVIDENCE_BYTES,
        )
        workspace = RealCaptureWorkspaceReceiptV1.model_validate_json(workspace_bytes)
        if not workspace.authority_eligible_for_real_execution:
            raise OfficialTargetFreezeError("WORKSPACE_IN_CLONE_VERIFY_REQUIRED")
        assert_real_capture_workspace_receipt_current_v1(workspace)
        output = assert_workspace_control_artifact_destination_v1(
            workspace,
            arguments.output,
        )
        if workspace.prepared_at_utc > created:
            raise OfficialTargetFreezeError("OFFICIAL_SCHEDULE_PRECEDES_WORKSPACE")
        target_set = freeze_official_fixture_target_set_v1(
            evidence_bytes=evidence_bytes,
            official_source_content_bytes=official_source_content_bytes,
            workspace_receipt=workspace,
            created_at_utc=created,
        )
        with output.open("xb") as stream:
            stream.write(canonical_json_bytes(target_set.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except (
        CaptureStorageError,
        CaptureContractError,
        OfficialTargetFreezeError,
        WorkspaceBootstrapError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        code = getattr(error, "code", "OFFICIAL_SCHEDULE_INPUT_INVALID")
        print(json.dumps({"status": "FAILED", "code": code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "status": "FROZEN",
                "fixture_target_set_sha256": target_set.canonical_set_hash,
                "fixture_count": len(target_set.targets),
                "source_evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                "official_source_content_sha256": hashlib.sha256(
                    official_source_content_bytes
                ).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
