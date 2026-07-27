"""Versioned datasets, deterministic hashes, and exact paired samples."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

PAIRING_FIELDS = (
    "competition",
    "fixture_id",
    "kickoff_at",
    "research_mode",
    "feature_cutoff",
    "market_source",
    "market_record_hash",
)


@dataclass(frozen=True, slots=True)
class PairedSample:
    keys: tuple[tuple[str, ...], ...]
    left: tuple[Mapping[str, object], ...]
    right: tuple[Mapping[str, object], ...]
    attrition_left: int = 0
    attrition_right: int = 0


def row_key(row: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for field in PAIRING_FIELDS:
        value = row.get(field)
        if value is None or str(value) == "":
            raise ValueError(f"PAIRING_FIELD_MISSING:{field}")
        values.append(str(value))
    return tuple(values)


def _unique_index(
    rows: Sequence[Mapping[str, object]],
    *,
    side: str,
) -> dict[tuple[str, ...], Mapping[str, object]]:
    index: dict[tuple[str, ...], Mapping[str, object]] = {}
    for row in rows:
        key = row_key(row)
        if key in index:
            raise ValueError(f"PAIRED_SAMPLE_DUPLICATE:{side}:{'|'.join(key)}")
        index[key] = row
    return index


def exact_pairing(
    left: Sequence[Mapping[str, object]],
    right: Sequence[Mapping[str, object]],
) -> PairedSample:
    """Require exact set equality; intersections cannot masquerade as pairing."""

    left_index = _unique_index(left, side="LEFT")
    right_index = _unique_index(right, side="RIGHT")
    left_keys = set(left_index)
    right_keys = set(right_index)
    if left_keys != right_keys:
        missing_left = len(right_keys - left_keys)
        missing_right = len(left_keys - right_keys)
        raise ValueError(
            "PAIRED_SAMPLE_KEYSET_MISMATCH:"
            f"missing_left={missing_left}:missing_right={missing_right}"
        )
    keys = tuple(sorted(left_keys))
    return PairedSample(
        keys=keys,
        left=tuple(left_index[key] for key in keys),
        right=tuple(right_index[key] for key in keys),
    )


def deterministic_dataset_hash(
    rows: Sequence[Mapping[str, object]],
) -> str:
    digest = hashlib.sha256()
    canonical_rows = sorted(
        (
            json.dumps(
                dict(row),
                default=str,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for row in rows
        )
    )
    for row in canonical_rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def checkpoint_key(
    *,
    campaign: str,
    dataset_hash: str,
    hypothesis_ids: Sequence[str],
    seed: int,
) -> str:
    payload = {
        "campaign": campaign,
        "dataset_hash": dataset_hash,
        "hypothesis_ids": sorted(hypothesis_ids),
        "seed": seed,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
