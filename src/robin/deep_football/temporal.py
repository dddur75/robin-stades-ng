"""Adversarial input-level temporal and lineage guards."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

TARGET_FIELDS = {
    "home_goals",
    "away_goals",
    "target_home_goals",
    "target_away_goals",
    "final_score",
    "outcome",
    "result",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TemporalInput:
    input_id: str
    available_at: datetime
    cutoff_at: datetime
    lineage_hash: str
    source: str


def assert_input_available_strictly_before_cutoff(
    inputs: Sequence[TemporalInput],
) -> None:
    if not inputs:
        raise ValueError("TEMPORAL_INPUTS_REQUIRED")
    for item in inputs:
        if item.available_at >= item.cutoff_at:
            raise ValueError(f"INPUT_NOT_STRICTLY_BEFORE_CUTOFF:{item.input_id}")
        if not SHA256.fullmatch(item.lineage_hash):
            raise ValueError(f"INPUT_LINEAGE_HASH_INVALID:{item.input_id}")
        if not item.source:
            raise ValueError(f"INPUT_SOURCE_MISSING:{item.input_id}")


def assert_feature_allowlist(
    row: Mapping[str, object],
    allowed_features: Sequence[str],
) -> tuple[float | None, ...]:
    if any(feature in TARGET_FIELDS for feature in allowed_features):
        raise ValueError("TARGET_FIELD_IN_FEATURE_ALLOWLIST")
    values: list[float | None] = []
    for feature in allowed_features:
        raw = row.get(feature)
        if raw is None:
            values.append(None)
            continue
        try:
            values.append(float(str(raw)))
        except ValueError as exc:
            raise ValueError(f"NON_NUMERIC_FEATURE:{feature}") from exc
    return tuple(values)


def assert_market_alignment(
    *,
    feature_fixture_id: str,
    market_fixture_id: str,
    market_available_at: datetime | None,
    cutoff_at: datetime,
    require_exact_observed_at: bool,
) -> None:
    if feature_fixture_id != market_fixture_id:
        raise ValueError("MARKET_FIXTURE_ID_MISMATCH")
    if market_available_at is None:
        if require_exact_observed_at:
            raise ValueError("MARKET_EXACT_OBSERVED_AT_REQUIRED")
        return
    if market_available_at >= cutoff_at:
        raise ValueError("FUTURE_MARKET_PRICE_FORBIDDEN")
