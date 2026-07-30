"""Read and validate the frozen J10 historical market corpus without network I/O."""

from __future__ import annotations

import hashlib
import io
import re
import shutil

# Subprocess is restricted to an absolute local git binary with shell disabled.
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast, overload

import pandas as pd

from robin.hypothesis_evidence.contracts import (
    AUTHORITATIVE_HISTORICAL_REVISION,
    BYTE_IDENTICAL_REPLICA_REVISIONS,
    DATASET_HASH,
    EXPECTED_FIXTURES,
    EXPECTED_MARKET_COLUMNS,
    EXPECTED_PARTITIONS,
    HISTORICAL_PARQUET_TREE,
    EvidenceFactoryError,
    sha256_file,
)
from robin.patterns.campaign import _dataset_hash

MARKET_PATH_RE = re.compile(
    r"^historical/parquet/competition=(?P<competition>[^/]+)/"
    r"season=(?P<season>\d{4})/entity_type=historical_market/"
    r"dataset_version=historical_market_v1/[^/]+\.parquet$"
)


@dataclass(frozen=True, slots=True)
class PartitionEvidence:
    path: str
    sha256: str
    rows: int
    competition: str
    season: int


@dataclass(frozen=True, slots=True)
class LoadedHistoricalMarket:
    rows: tuple[dict[str, object], ...]
    partitions: tuple[PartitionEvidence, ...]
    source_mode: str
    dataset_hash: str
    authoritative_revision: str
    parquet_tree: str
    replica_trees: dict[str, str]


def _native(value: Any) -> object:
    missing = pd.isna(value)
    if isinstance(missing, bool) and missing:
        return None
    item = getattr(value, "item", None)
    return item() if callable(item) else value


@overload
def _git(
    repo_root: Path,
    *arguments: str,
    text: Literal[True] = True,
) -> str: ...


@overload
def _git(
    repo_root: Path,
    *arguments: str,
    text: Literal[False],
) -> bytes: ...


def _git(
    repo_root: Path,
    *arguments: str,
    text: bool = True,
) -> str | bytes:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise EvidenceFactoryError("LOCAL_GIT_EXECUTABLE_UNAVAILABLE")
    command = [git_executable, "-C", str(repo_root), *arguments]
    try:
        completed = subprocess.run(  # noqa: S603  # nosec B603
            command,
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError)
            and isinstance(exc.stderr, str)
            else ""
        )
        raise EvidenceFactoryError(
            f"FROZEN_GIT_OBJECT_UNAVAILABLE:{arguments[0]}:{stderr}"
        ) from exc
    if text:
        return cast(str, completed.stdout)
    return cast(bytes, completed.stdout)


def validate_git_provenance(
    repo_root: Path,
    *,
    revision: str = AUTHORITATIVE_HISTORICAL_REVISION,
) -> dict[str, str]:
    """Validate the campaign pin and record later byte-identical replicas."""

    if revision != AUTHORITATIVE_HISTORICAL_REVISION:
        raise EvidenceFactoryError(
            f"HISTORICAL_REVISION_NOT_AUTHORIZED:{revision}"
        )
    tree = str(
        _git(repo_root, "rev-parse", f"{revision}:historical/parquet")
    ).strip()
    if tree != HISTORICAL_PARQUET_TREE:
        raise EvidenceFactoryError(
            f"HISTORICAL_PARQUET_TREE_MISMATCH:{tree}"
        )
    replicas: dict[str, str] = {}
    for replica in BYTE_IDENTICAL_REPLICA_REVISIONS:
        replica_tree = str(
            _git(repo_root, "rev-parse", f"{replica}:historical/parquet")
        ).strip()
        if replica_tree != HISTORICAL_PARQUET_TREE:
            raise EvidenceFactoryError(
                f"HISTORICAL_REPLICA_TREE_MISMATCH:{replica}:{replica_tree}"
            )
        replicas[replica] = replica_tree
    return replicas


def _validate_frame(
    frame: pd.DataFrame,
    *,
    source_path: str,
    expected_competition_slug: str,
    expected_season: int,
) -> None:
    columns = tuple(str(column) for column in frame.columns)
    if columns != EXPECTED_MARKET_COLUMNS:
        raise EvidenceFactoryError(
            f"HISTORICAL_MARKET_SCHEMA_MISMATCH:{source_path}"
        )
    if frame.empty:
        raise EvidenceFactoryError(f"HISTORICAL_PARTITION_EMPTY:{source_path}")
    competitions = {str(value) for value in frame["competition"].unique()}
    expected_competitions = {
        expected_competition_slug,
        expected_competition_slug.replace("-", " "),
    }
    if len(competitions) != 1 or not competitions <= expected_competitions:
        raise EvidenceFactoryError(
            f"HISTORICAL_PARTITION_COMPETITION_MISMATCH:{source_path}"
        )
    seasons = {int(value) for value in frame["season"].unique()}
    if seasons != {expected_season}:
        raise EvidenceFactoryError(
            f"HISTORICAL_PARTITION_SEASON_MISMATCH:{source_path}"
        )


def _rows_from_frame(
    frame: pd.DataFrame,
    *,
    source_path: str,
    source_sha256: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in frame.to_dict(orient="records"):
        row = {str(key): _native(value) for key, value in raw.items()}
        row["__source_partition"] = source_path
        row["__source_partition_sha256"] = source_sha256
        rows.append(row)
    return rows


def _local_partitions(
    historical_root: Path,
) -> tuple[list[dict[str, object]], list[PartitionEvidence]]:
    base = historical_root / "parquet"
    paths = sorted(
        base.glob(
            "competition=*/season=*/entity_type=historical_market/"
            "dataset_version=historical_market_v1/*.parquet"
        ),
        key=lambda path: path.as_posix(),
    )
    if len(paths) != EXPECTED_PARTITIONS:
        raise EvidenceFactoryError(
            f"HISTORICAL_PARTITION_COUNT_MISMATCH:{len(paths)}"
        )
    rows: list[dict[str, object]] = []
    partitions: list[PartitionEvidence] = []
    for path in paths:
        relative = PurePosixPath(
            "historical",
            path.relative_to(historical_root).as_posix(),
        ).as_posix()
        match = MARKET_PATH_RE.fullmatch(relative)
        if match is None:
            raise EvidenceFactoryError(
                f"HISTORICAL_PARTITION_PATH_INVALID:{relative}"
            )
        digest = sha256_file(path)
        frame = pd.read_parquet(path)
        season = int(match.group("season"))
        competition = match.group("competition")
        _validate_frame(
            frame,
            source_path=relative,
            expected_competition_slug=competition,
            expected_season=season,
        )
        rows.extend(
            _rows_from_frame(
                frame,
                source_path=relative,
                source_sha256=digest,
            )
        )
        partitions.append(
            PartitionEvidence(
                path=relative,
                sha256=digest,
                rows=len(frame),
                competition=str(frame["competition"].iloc[0]),
                season=season,
            )
        )
    return rows, partitions


def _git_partitions(
    repo_root: Path,
    revision: str,
) -> tuple[list[dict[str, object]], list[PartitionEvidence]]:
    listing = str(
        _git(
            repo_root,
            "ls-tree",
            "-r",
            "--name-only",
            revision,
            "--",
            "historical/parquet",
        )
    )
    paths = sorted(
        path
        for path in listing.splitlines()
        if MARKET_PATH_RE.fullmatch(path)
    )
    if len(paths) != EXPECTED_PARTITIONS:
        raise EvidenceFactoryError(
            f"HISTORICAL_PARTITION_COUNT_MISMATCH:{len(paths)}"
        )
    rows: list[dict[str, object]] = []
    partitions: list[PartitionEvidence] = []
    for path in paths:
        match = MARKET_PATH_RE.fullmatch(path)
        if match is None:
            raise EvidenceFactoryError(
                f"HISTORICAL_PARTITION_PATH_INVALID:{path}"
            )
        payload = _git(
            repo_root,
            "cat-file",
            "blob",
            f"{revision}:{path}",
            text=False,
        )
        digest = hashlib.sha256(payload).hexdigest()
        frame = pd.read_parquet(io.BytesIO(payload))
        season = int(match.group("season"))
        competition = match.group("competition")
        _validate_frame(
            frame,
            source_path=path,
            expected_competition_slug=competition,
            expected_season=season,
        )
        rows.extend(
            _rows_from_frame(
                frame,
                source_path=path,
                source_sha256=digest,
            )
        )
        partitions.append(
            PartitionEvidence(
                path=path,
                sha256=digest,
                rows=len(frame),
                competition=str(frame["competition"].iloc[0]),
                season=season,
            )
        )
    return rows, partitions


def load_frozen_historical_market(
    repo_root: Path,
    *,
    historical_root: Path | None,
    revision: str = AUTHORITATIVE_HISTORICAL_REVISION,
) -> LoadedHistoricalMarket:
    """Load the extracted cache when supplied, otherwise read pinned Git blobs."""

    replicas = validate_git_provenance(repo_root, revision=revision)
    if historical_root is not None:
        if not historical_root.is_dir():
            raise EvidenceFactoryError(
                f"HISTORICAL_EXTRACTED_ROOT_UNAVAILABLE:{historical_root}"
            )
        rows, partitions = _local_partitions(historical_root)
        source_mode = "EXTRACTED_FROZEN_CACHE"
    else:
        rows, partitions = _git_partitions(repo_root, revision)
        source_mode = "PINNED_GIT_BLOBS"

    if len(rows) != EXPECTED_FIXTURES:
        raise EvidenceFactoryError(
            f"HISTORICAL_FIXTURE_COUNT_MISMATCH:{len(rows)}"
        )
    fixture_ids = [str(row.get("fixture_id")) for row in rows]
    if len(set(fixture_ids)) != EXPECTED_FIXTURES:
        raise EvidenceFactoryError("HISTORICAL_FIXTURE_ID_NOT_UNIQUE")
    record_hashes = [str(row.get("_record_hash")) for row in rows]
    if (
        len(set(record_hashes)) != EXPECTED_FIXTURES
        or any(len(value) != 64 for value in record_hashes)
    ):
        raise EvidenceFactoryError("HISTORICAL_RECORD_HASH_NOT_UNIQUE")
    if {str(row.get("source")) for row in rows} != {"FOOTBALL_DATA"}:
        raise EvidenceFactoryError("HISTORICAL_SOURCE_MISMATCH")
    if {
        str(row.get("observed_time_status")) for row in rows
    } != {"SOURCE_PRICE_CLASS_ONLY"}:
        raise EvidenceFactoryError("HISTORICAL_PRICE_TIME_STATUS_MISMATCH")

    canonical_rows = [
        {column: row[column] for column in EXPECTED_MARKET_COLUMNS}
        for row in rows
    ]
    dataset_hash = _dataset_hash(canonical_rows)
    if dataset_hash != DATASET_HASH:
        raise EvidenceFactoryError(
            f"HISTORICAL_DATASET_HASH_MISMATCH:{dataset_hash}"
        )
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row.get("kickoff_at") or row.get("match_date")),
                str(row.get("fixture_id")),
            ),
        )
    )
    return LoadedHistoricalMarket(
        rows=ordered,
        partitions=tuple(partitions),
        source_mode=source_mode,
        dataset_hash=dataset_hash,
        authoritative_revision=revision,
        parquet_tree=HISTORICAL_PARQUET_TREE,
        replica_trees=replicas,
    )
