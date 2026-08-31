"""Validate the controller-bound Recovery V2 dispatch window before any job GET."""

from __future__ import annotations

import argparse
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from robin.chronos_production import (
    DATA_TORRENT_RECOVERY_V2_NOT_BEFORE,
    DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS,
    ChronosProductionError,
    validate_data_torrent_recovery_v2_authority,
)

_ROOT = Path(os.path.abspath(Path(__file__))).parents[1]
_SHA = re.compile(r"^[0-9a-f]{40}$")
_NONCE = re.compile(r"^[0-9a-f]{64}$")
_EPOCH = re.compile(r"^[1-9][0-9]{9,11}$")
_MAXIMUM_BOUND_WINDOW_SECONDS = {
    "E2": 600,
    "E3A": 900,
    "E3B": 900,
    "E4": 1_200,
}


class RecoveryV2DispatchEnvelopeError(RuntimeError):
    """Sanitized failure raised before a workflow may perform its first GET."""


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_ENVELOPE_INVALID") from None
    if (
        not value.endswith("Z")
        or parsed.tzinfo is None
        or parsed.utcoffset() != UTC.utcoffset(parsed)
    ):
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_ENVELOPE_INVALID")
    return parsed.astimezone(UTC)


def validate_dispatch_envelope(
    *,
    scale_stage: str,
    expected_main_sha: str,
    effect_deadline_epoch: str,
    dispatch_nonce: str,
    now: datetime | None = None,
    repository_root: Path = _ROOT,
) -> datetime:
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if observed.microsecond:
        observed = observed.replace(microsecond=0)
    if (
        scale_stage not in {"E2", "E3A", "E3B", "E4"}
        or _SHA.fullmatch(expected_main_sha) is None
        or _EPOCH.fullmatch(effect_deadline_epoch) is None
        or _NONCE.fullmatch(dispatch_nonce) is None
        or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.getenv("GITHUB_REF") != "refs/heads/main"
        or os.getenv("GITHUB_SHA") != expected_main_sha
        or os.getenv("GITHUB_RUN_ATTEMPT") != "1"
    ):
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_ENVELOPE_INVALID")
    deadline_value = int(effect_deadline_epoch)
    if deadline_value > 253_402_300_799:
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_ENVELOPE_INVALID")
    deadline = datetime.fromtimestamp(deadline_value, tz=UTC)
    mission_deadline = _timestamp(DATA_TORRENT_RECOVERY_V2_NOT_BEFORE) + timedelta(
        seconds=DATA_TORRENT_RECOVERY_V2_TIME_BUDGET_SECONDS
    )
    if (
        deadline <= observed
        or deadline > mission_deadline
        or deadline - observed
        > timedelta(seconds=_MAXIMUM_BOUND_WINDOW_SECONDS[scale_stage])
    ):
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_DEADLINE_INVALID")
    try:
        authority_deadline = validate_data_torrent_recovery_v2_authority(
            scale_stage=scale_stage,
            now=observed,
            repository_root=repository_root,
        )
    except ChronosProductionError:
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_AUTHORITY_INVALID") from None
    if authority_deadline.tzinfo is None or deadline > authority_deadline.astimezone(UTC):
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_DEADLINE_INVALID")
    if time.time() >= deadline_value:
        raise RecoveryV2DispatchEnvelopeError("RECOVERY_V2_DISPATCH_DEADLINE_EXCEEDED")
    return deadline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale-stage", required=True, choices=("E2", "E3A", "E3B", "E4"))
    parser.add_argument("--expected-main-sha", required=True)
    args = parser.parse_args()
    try:
        validate_dispatch_envelope(
            scale_stage=args.scale_stage,
            expected_main_sha=args.expected_main_sha,
            effect_deadline_epoch=os.getenv("RECOVERY_V2_EFFECT_DEADLINE_EPOCH", ""),
            dispatch_nonce=os.getenv("RECOVERY_V2_DISPATCH_NONCE", ""),
        )
    except RecoveryV2DispatchEnvelopeError as error:
        print(str(error))
        return 1
    print("RECOVERY_V2_DISPATCH_ENVELOPE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
